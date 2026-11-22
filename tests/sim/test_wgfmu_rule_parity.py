"""R-WG-02 live (blueprint v2 2.8; WP10.3): the plan rule against what the guarded driver and the simulated library
do with the same program. Every program R-WG-02 lets through loads and runs without a library or firmware error, and
every program the guard or the library refuses (setup errors, firmware 3302-3316 at ``update``/``execute``, run-time
3050-3052) is one R-WG-02 blocks, so a WGFMU plan that validates does not fail on the instrument for a limit the
plan could have shown. (R-WG-02 is stricter in places: an off-grid event time is rounded by the library but blocked
by the rule.) The envelope here is deliberately wide (10 V, 10,000 vectors, 10 s) so that the library's own limits
are reached; the guard's envelope checks have their own tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.wgfmu import WgfmuDriver
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope, WaveformLimits
from b1500_test_agent.models.sources import WaveformProgram
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.safety.wgfmu_helpers import BOTTOM, TOP, wg_scenario
from tests.sim.wgfmu_examples import ADDRESS, station
from tests.unit import rules_factory_v2 as v2
from tests.unit.rules_factory import engine
from tests.unit.rules_factory_v2 import RSU201, RSU202, lab_station, wave

pytestmark = pytest.mark.wgfmu

WIDE = WaveformLimits(max_vectors=10_000, max_points=4_000_000, total_time_s=10.0)
WIDE_ENVELOPE = CompiledEnvelope(
    channels={ch: ChannelEnvelope(role=role, max_abs_v=10.0, max_abs_i=None, function="wgfmu")
              for ch, role in ((TOP, "top"), (BOTTOM, "bottom"))},
    routes=frozenset({RSU201, RSU202}), waveform={TOP: WIDE, BOTTOM: WIDE})


def put(path: tuple[Any, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def edit(data: dict[str, Any]) -> None:
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return edit


def event(index: int, **changes: Any) -> Callable[[dict[str, Any]], None]:
    return lambda data: data["events"][index].update(changes)


def add_event(**item: Any) -> Callable[[dict[str, Any]], None]:
    return lambda data: data["events"].append(item)


def chain(*edits: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def edit(data: dict[str, Any]) -> None:
        for item in edits:
            item(data)
    return edit


CASES: dict[str, Callable[[dict[str, Any]], None] | None] = {
    "default": None,
    "pg_10v_range_3302": put(("channels", "201"), {"mode": "pg", "force_range": "10v"}),
    "pg_current_3303": put(("channels", "202", "mode"), "pg"),
    "2049_vectors": chain(put(("patterns", "drive", "vectors"), [[1e-8, 0.0]] * 2049), event(0, points=2048)),
    "2048_vectors": chain(put(("patterns", "drive", "vectors"), [[1e-8, 0.0]] * 2048), event(0, points=2047)),
    "level_outside_range_3310": put(("channels", "201", "force_range"), "-10v"),
    "513_sequences_3305": put(("sequences", "201"), [["drive", 1]] * 513),
    "512_sequences": put(("sequences", "201"), [["drive", 1]] * 512),
    "count_0": put(("sequences", "201"), [["drive", 0]]),
    "empty_pattern_3306": chain(put(("patterns", "idle"), {"v0": 0.0, "vectors": []}),
                                put(("sequences", "201"), [["drive", 10], ["idle", 1]])),
    "interval_3312": event(0, points=1, interval=2.0),
    "average_3315": chain(event(1, points=1, interval=0.05, average=0.03),
                          put(("patterns", "sense", "vectors"), [[0.04, 0.0]])),
    "average_above_interval_3316": event(1, points=10, interval=1e-8, average=2e-8),
    "event_after_pattern_3313": event(0, points=1000),
    "range_event_on_voltage_3314": add_event(kind="range", pattern="drive", event="r", t=1e-6, range="10ma"),
    "range_event_ok": chain(event(1, average=0.0),
                            add_event(kind="range", pattern="sense", event="r", t=1e-6, range="10ma")),
    "range_events_too_close_3052": chain(event(1, average=0.0), *(
        add_event(kind="range", pattern="sense", event=f"r{i}", t=i * 1e-6, range="10ma") for i in range(3))),
    "range_event_inside_averaging_3314": chain(event(1, points=40, interval=1e-7, average=5e-8),
                                               add_event(kind="range", pattern="sense", event="r", t=1.2e-7,
                                                         range="10ma")),
    "off_grid_vector": put(("patterns", "drive", "vectors", 3), [1.0015e-6, 0.0]),
    "off_grid_event_time": event(0, t=5e-9, points=300),
}


def rule_blocks(mutate: Callable[[dict[str, Any]], None] | None) -> list[str]:
    cfg, ctx = v2.wgfmu(mutate=mutate) if mutate is not None else v2.wgfmu()
    report = engine(cfg).evaluate(ctx, "plan")
    return [f.message for f in report.findings if f.rule_id == "R-WG-02" and f.severity == "block"]


def instrument_outcome(mutate: Callable[[dict[str, Any]], None] | None) -> str:
    """``runs``, ``guard: <reason>`` or ``library: <code>`` for the program on the simulated B1500A."""
    data = wave()
    if mutate is not None:
        mutate(data)
    try:
        program = WaveformProgram.model_validate(data)
    except ValueError as exc:  # the program model itself refuses it (no library call possible)
        return f"model: {exc}"
    st = station(wg_scenario())
    wg = WgfmuDriver(st.wg, OutputGuard(WIDE_ENVELOPE, switches=lab_station().switches), wait=lambda _s: None)
    st.wg.open_session(ADDRESS)
    try:
        wg.load(program)
        block = wg.run()
        assert block.status == "completed"
        return "runs"
    except EnvelopeViolation as exc:
        return f"guard: {exc.reason}"
    except WgfmuError as exc:
        return f"library: {exc.wgfmu_code}"
    finally:
        wg.safe_state()
        st.wg.close_session()


@pytest.mark.parametrize("name", sorted(CASES))
def test_r_wg_02_agrees_with_the_guarded_library(name: str) -> None:
    blocks = rule_blocks(CASES[name])
    outcome = instrument_outcome(CASES[name])
    if not blocks:
        assert outcome == "runs", f"R-WG-02 passes {name}, but on the instrument: {outcome}"
    if outcome != "runs":
        assert blocks, f"{name} fails on the instrument ({outcome}) although R-WG-02 lets it through"


def test_the_cases_cover_both_sides() -> None:
    outcomes = {name: instrument_outcome(mutate) for name, mutate in CASES.items()}
    library = {name for name, outcome in outcomes.items() if outcome.startswith("library")}
    assert {"pg_10v_range_3302", "pg_current_3303", "513_sequences_3305", "empty_pattern_3306",
            "level_outside_range_3310", "interval_3312", "event_after_pattern_3313", "average_3315",
            "average_above_interval_3316", "range_events_too_close_3052"} <= library, outcomes
    assert {name for name, outcome in outcomes.items() if outcome == "runs"} >= {
        "default", "2048_vectors", "512_sequences", "range_event_ok"}
