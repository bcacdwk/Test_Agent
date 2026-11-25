"""Kind ``pulse_read``, WGFMU path (``fecap.endurance_pund``; the test-only ``generic.wgfmu_pulse_read`` with an SMU
bias), and kind ``wgfmu_waveform``'s builders ``pund`` (``fecap.pund``) and ``program_read``
(``fefet.fast_program_read``): rows of the fault matrix with the global invariant v2 on both buses (blueprint v2 2.6,
4.3, 8.1 ``safety/``; WP10.6 AC "both buses clean after faults").

The body is the real kind (``PulseReadKind.acquire`` / ``WgfmuWaveformKind.acquire``) running plans the real planner
compiled, inside ONE transaction on noiseless copies of the ``fecap_basic`` and ``fefet_lab`` scenarios with both
links spied (``wgfmu_helpers``):

- ``pund``: an endurance PUND of 10 cycles (PUND read at cycle 1, a cycling burst of 8 cycles, PUND read at cycle
  10: three WGFMU executions);
- ``biased``: the FeFET through the WGFMU path with staircase reads (reference read, erase, read, program, read: five
  executions) and an SMU bias on SMU5 switched on inside the WGFMU phase (FLEX ``CN``/``DV`` and an ``ERRX?`` drain
  after every execution: WG Ex. 10);
- ``builders``: ``fecap.pund`` and ``fefet.fast_program_read`` (one execution each).

Faults {``wgfmu_error``, ``wgfmu_hang``, ``wgfmu_disconnect_fails``, ``wgfmu_dll_missing``, Ctrl-C, a buggy WGFMU level
outside the envelope; FLEX ``errx`` and ``timeout`` on the SMU side} x positions {bias (the SMU's level write), open
(entering the phase), load (the first execution's setup), first (its sequencer started), second (the second
execution's sequencer started: a burst or a pulse), readback (the last read's readback), between (the ERRX? drain
after the first execution), cleanup (the phase exit's first safe-state call)}. Every case asserts the invariant: no
level outside the plan's envelope reached the library or FLEX, the library ran only with the FLEX exclusive lock
released, and afterwards every SMU is at 0 V and off, every WGFMU channel disconnected and idle, the library session
closed and the FLEX link locked again, or the fault latch is set with ``cleanup_unverified``.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds.pulse_read import PulseReadKind
from b1500_test_agent.catalog.kinds.pulse_wgfmu import WgfmuPulseAcquisition, stored
from b1500_test_agent.catalog.kinds.wgfmu_waveform import WaveformAcquisition, WgfmuWaveformKind
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.driver.wgfmu import WgfmuDriver, WgfmuSafeStateFailed
from b1500_test_agent.models.plan import CompiledEnvelope, PlanRecord, PlanRequest
from b1500_test_agent.models.policy import DutProfile, DutTerminal, TerminalPulse
from b1500_test_agent.models.sim import (
    ErrxFault,
    SimFault,
    TimeoutFault,
    WgfmuDisconnectFails,
    WgfmuDllMissing,
    WgfmuErrorFault,
    WgfmuHang,
)
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY
from b1500_test_agent.session import Transaction
from b1500_test_agent.transport.base import TransportTimeout
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.safety.helpers import assert_cleanup_order, assert_within_envelope
from tests.safety.wgfmu_helpers import (
    WgHarness,
    assert_lock_windows,
    library_levels,
    make_wg_harness,
    relocked_after_library,
)
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import T0, bundle, engine, pin_map_exact
from tests.unit.rules_factory_v2 import lab_station

pytestmark = pytest.mark.wgfmu

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "recipes" / "generic" / "wgfmu_pulse_read.yaml"
_RECIPES = Path(tempfile.mkdtemp(prefix="b1500-pr-wgfmu-")) / "recipes"
shutil.copytree(REPO_ROOT / "recipes", _RECIPES)
shutil.copy(FIXTURE, _RECIPES / "generic" / FIXTURE.name)
REGISTRY = RecipeRegistry.load(_RECIPES, repo_root=REPO_ROOT)

CAP = pin_map_exact("cap", {"top": "RSU201.OUT", "bottom": "RSU202.OUT"})
FET = pin_map_exact("fet", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU"})
FET_BIAS = pin_map_exact("fet-bias", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU", "bias": 5})
PULSE = TerminalPulse(max_abs_v=5.0, max_width_s=1e-3, max_duty=0.5, max_count=10**9)
FECAP = DutProfile(name="cap", device_type="fecap", terminals={
    "top": DutTerminal(max_abs_v=4.0, max_abs_i=1e-3, impedance="high_z", pulse=PULSE),
    "bottom": DutTerminal(max_abs_v=4.0, max_abs_i=1e-3, impedance="high_z", pulse=PULSE)})
FEFET = DutProfile(name="fet", device_type="fefet", terminals={
    "gate": DutTerminal(max_abs_v=5.0, max_abs_i=1e-3, pulse=PULSE),
    "drain": DutTerminal(max_abs_v=1.0, max_abs_i=1e-3), "source": DutTerminal(max_abs_v=1.0, max_abs_i=1e-3),
    "bias": DutTerminal(max_abs_v=1.0, max_abs_i=1e-3)})
GATE = 201


def make_plan(recipe_id: str, pin_map: str, dut: str, **params: Any) -> PlanRecord:
    cfg = bundle(station_profile=lab_station(), pin_maps=[CAP, FET, FET_BIAS], duts=[FECAP, FEFET])
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map, "dut_profile": dut,
                                      "params": params})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "ok", plan.summary
    return plan


PUND_PLAN = make_plan("fecap.endurance_pund", "cap", "cap", cycles=10, reads_per_decade=1)
BIASED = make_plan("generic.wgfmu_pulse_read", "fet-bias", "fet", cycles=1, vg_points=5, vb=-0.2)
PLANS = {"pund": PUND_PLAN, "biased": BIASED}
SCENARIOS = {"pund": "fecap_basic", "biased": "fefet_lab"}
BUILDERS = {"fecap.pund": make_plan("fecap.pund", "cap", "cap"),
            "fefet.fast_program_read": make_plan("fefet.fast_program_read", "fet", "fet", vg_points=11)}
BUILDER_SCENARIOS = {"fecap.pund": "fecap_basic", "fefet.fast_program_read": "fefet_lab"}

MOMENTS = {"open": ("before:open_session", 1), "load": ("before:create_pattern", 1), "first": ("after:execute", 1),
           "second": ("after:execute", 2), "cleanup": ("before:abort", 1)}
READBACK = {"pund": ("before:measure_value_size", 2), "biased": ("before:measure_value_size", 3)}
"""Library positions: ``(spy moment, which occurrence)``; ``readback`` = the last read's; ``bias`` and ``between``
are FLEX moments."""
POSITIONS = ("bias", "open", "load", "first", "second", "readback", "between", "cleanup")
LIBRARY_POSITIONS = ("open", "load", "first", "second", "readback", "cleanup")


@dataclass(frozen=True)
class Case:
    inject: Callable[[WgHarness], None]
    raises: type[BaseException] | None = None
    latched: bool = False


def sim(fault: SimFault) -> Callable[[WgHarness], None]:
    return lambda h: h.sim.inject(fault)


def interrupt(_h: WgHarness) -> None:
    raise KeyboardInterrupt


def too_high_level(h: WgHarness) -> None:
    """A buggy body asks the WGFMU for 6 V on the pulsed channel, whose envelope is lower: refused before the
    library."""
    assert h.tx is not None
    link = h.tx.wgfmu_link
    wg = link.driver if link.driver is not None else WgfmuDriver(h.session.bus.wgfmu, h.tx.driver.guard)  # type: ignore[arg-type]
    wg.force_dc(GATE, 6.0)


E, SSF, KI, EV, TO = WgfmuError, WgfmuSafeStateFailed, KeyboardInterrupt, EnvelopeViolation, TransportTimeout
STUCK = WgfmuDisconnectFails()
LIBRARY: dict[str, dict[str, Case]] = {
    "wgfmu_error": {"open": Case(sim(WgfmuErrorFault(fn="open_session", code=api.COMMUNICATION_ERROR)), E),
                    "load": Case(sim(WgfmuErrorFault(fn="add_vectors", code=api.PARAMETER_OUT_OF_RANGE)), E),
                    "first": Case(sim(WgfmuErrorFault(fn="status", code=3050)), E),
                    "second": Case(sim(WgfmuErrorFault(fn="status", code=3050)), E),
                    "readback": Case(sim(WgfmuErrorFault(fn="measure_values", code=3015)), E),
                    "cleanup": Case(sim(WgfmuErrorFault(fn="disconnect", code=3001)), SSF)},
    "wgfmu_hang": {"open": Case(sim(WgfmuHang(fn="initialize")), E),
                   "load": Case(sim(WgfmuHang(fn="execute")), E),
                   "first": Case(sim(WgfmuHang(fn="status")), E),
                   "second": Case(sim(WgfmuHang(fn="status")), E),
                   "readback": Case(sim(WgfmuHang(fn="measure_value_size")), E),
                   "cleanup": Case(sim(WgfmuHang(fn="abort")), SSF)},
    "wgfmu_disconnect_fails": {p: Case(sim(STUCK), SSF, latched=True) for p in LIBRARY_POSITIONS},
    "wgfmu_dll_missing": {"open": Case(sim(WgfmuDllMissing()), E), "load": Case(sim(WgfmuDllMissing())),
                          "first": Case(sim(WgfmuDllMissing())), "second": Case(sim(WgfmuDllMissing())),
                          "readback": Case(sim(WgfmuDllMissing())), "cleanup": Case(sim(WgfmuDllMissing()))},
    "keyboard_interrupt": {p: Case(interrupt, KI) for p in LIBRARY_POSITIONS},
    "envelope_violation": {**{p: Case(too_high_level, EV) for p in LIBRARY_POSITIONS if p != "cleanup"},
                           "cleanup": Case(too_high_level, SSF)},
}
"""Library-side faults."""
FLEX: dict[str, dict[str, Case]] = {
    "errx": {"bias": Case(sim(ErrxFault(after_cmd="DV", code=305)), Exception)},
    "timeout": {"bias": Case(sim(TimeoutFault(on="query:ERRX?")), TO),
                "between": Case(sim(TimeoutFault(on="query:ERRX?")), TO)},
}
"""SMU-side faults (``bias``: right before the bias ``DV``; ``between``: after the first execution, so the ``ERRX?``
drain that follows it hangs)."""


def case_for(plan: str, fault: str, position: str) -> Case | None:
    if position in ("bias", "between"):
        return FLEX[fault].get(position) if plan == "biased" and fault in FLEX else None
    if fault in FLEX:
        return None
    return LIBRARY[fault][position]


CASES = [(plan, fault, position) for plan in PLANS for fault in (*LIBRARY, *FLEX) for position in POSITIONS
         if case_for(plan, fault, position) is not None]


def arm(h: WgHarness, moment: str, occurrence: int, action: Callable[[], None]) -> None:
    """Run ``action`` at the ``occurrence``-th ``moment`` of the library spy."""
    left = [occurrence]

    def step() -> None:
        left[0] -= 1
        if left[0] == 0:
            action()
        else:
            h.spy.actions[moment] = step

    h.spy.actions[moment] = step


def assert_invariant(h: WgHarness, tx: Transaction, envelope: CompiledEnvelope) -> None:
    """Global invariant v2 for the plan's envelope (module docstring)."""
    limit = max((e.max_abs_v for e in envelope.channels.values() if e.function == "wgfmu"), default=0.0)
    assert all(abs(v) <= limit for v in library_levels(h.spy)), "a WGFMU level outside the envelope reached the library"
    assert {args[0] for name, args in h.spy.calls if name == "connect"} <= set(envelope.waveform)
    flex = CompiledEnvelope(channels={ch: e for ch, e in envelope.channels.items() if e.function != "wgfmu"})
    assert_within_envelope(h.sim.instrument.command_log, flex)
    events = h.events()
    assert_lock_windows(events)
    assert_cleanup_order(events)
    latched = h.session.fault_latch.get() is not None
    assert tx.cleanup is not None and latched == tx.cleanup.latched_fault
    if latched:
        assert any(e.ev == "cleanup_unverified" for e in events)
    else:
        instrument = h.sim.instrument
        instrument.assert_safe()  # SMUs at 0 V and off; no WGFMU channel connected or running; no library session
        assert all(not s.connected and not s.running for s in instrument.state.wgfmu.values())
        assert h.library.session is None and relocked_after_library(events)
    assert h.session.lock.holder() is None and not (h.state_dir / "inflight.json").exists()


def harness(tmp_path: Path, scenario: str) -> WgHarness:
    return make_wg_harness(tmp_path, noiseless(load_scenario(scenario)))


def run_body(h: WgHarness, plan: PlanRecord, kind: Any) -> tuple[Transaction | None, BaseException | None, Any]:
    raised: BaseException | None = None
    tx: Transaction | None = None
    raw = None
    try:
        with h.transaction(envelope=plan.envelope) as tx:
            h.tx = tx
            raw = kind.acquire(tx, plan)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return tx, raised, raw


def test_pulse_read_wgfmu_matrix_is_complete() -> None:
    assert len(CASES) == 2 * 6 * 6 + 3  # both plans x six library faults x six positions + three SMU-side faults
    assert {"wgfmu_error", "wgfmu_hang", "wgfmu_disconnect_fails", "wgfmu_dll_missing"} <= set(LIBRARY)
    assert [s.action for s in stored(PUND_PLAN)[0].steps()] == ["read", "burst", "read"]
    assert [s.action for s in stored(BIASED)[0].steps()] == ["read", "pulse", "read", "pulse", "read"]


@pytest.mark.parametrize(("plan", "fault", "position"), CASES)
def test_pulse_read_wgfmu_fault_matrix(plan: str, fault: str, position: str, tmp_path: Path) -> None:
    case = case_for(plan, fault, position)
    assert case is not None
    h = harness(tmp_path, SCENARIOS[plan])
    if position == "bias":
        original = h.hook.write

        def write(cmd: str) -> None:
            if cmd.startswith("DV 5,"):
                case.inject(h)
            original(cmd)

        h.hook.write = write  # type: ignore[method-assign]
    elif position == "between":
        arm(h, "after:execute", 1, lambda: case.inject(h))
    else:
        moment, occurrence = READBACK[plan] if position == "readback" else MOMENTS[position]
        arm(h, moment, occurrence, lambda: case.inject(h))
    tx, raised, _ = run_body(h, PLANS[plan], PulseReadKind())
    assert tx is not None and tx.cleanup is not None
    if case.raises is None:
        assert raised is None, raised
    else:
        assert raised is not None and isinstance(raised, case.raises), f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_invariant(h, tx, PLANS[plan].envelope)
    if case.raises is EV and position != "cleanup":
        assert all(args[1] != 6.0 for name, args in h.spy.calls if name == "dc_force_voltage")


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_pulse_read_wgfmu_clean_run_leaves_both_buses_safe(plan: str, tmp_path: Path) -> None:
    h = harness(tmp_path, SCENARIOS[plan])
    tx, raised, raw = run_body(h, PLANS[plan], PulseReadKind())
    assert raised is None and tx is not None and isinstance(raw, WgfmuPulseAcquisition)
    assert_invariant(h, tx, PLANS[plan].envelope)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
    names = h.spy.names()
    assert names.count("execute") == (3 if plan == "pund" else 5) and names.count("open_session") == 1
    log = [r.command for r in h.sim.instrument.command_log if r.outcome == "ok"]
    if plan == "biased":
        assert tx.wgfmu_phases == ["unlocked (flex_io)"]
        assert names.index("initialize") < names.index("execute")
        assert log.index("CN 5") < log.index("DV 5,0,-0.2,0.0001")
    else:
        assert tx.wgfmu_phases == ["unlocked"] and "CN" not in {c.split(" ")[0] for c in log}


def test_pulse_read_wgfmu_tampered_catalog_is_refused_before_any_level(tmp_path: Path) -> None:
    data = PUND_PLAN.model_dump(mode="json")
    pattern = data["program"][SOURCE_PLAN_KEY]["waveform"]["patterns"]["top_cycling_8"]
    pattern["vectors"][1][1] = 4.5
    tampered = PlanRecord.model_validate(data)
    h = harness(tmp_path, "fecap_basic")
    tx, raised, _ = run_body(h, tampered, PulseReadKind())
    assert isinstance(raised, EnvelopeViolation) and raised.reason == "level_exceeds_envelope"
    assert not {"create_pattern", "add_vectors", "connect", "execute"} & set(h.spy.names())
    assert tx is not None
    assert_invariant(h, tx, PUND_PLAN.envelope)


# -- kind wgfmu_waveform: builders pund and program_read -------------------------------------------------------------

BUILDER_FAULTS: dict[str, Case] = {
    "error_run": Case(sim(WgfmuErrorFault(fn="status", code=3050)), E),
    "hang_readback": Case(sim(WgfmuHang(fn="measure_value_size")), E),
    "stuck_relay": Case(sim(STUCK), SSF, latched=True),
    "interrupt": Case(interrupt, KI),
}
BUILDER_MOMENTS = {"error_run": "after:execute", "hang_readback": "before:measure_value_size",
                   "stuck_relay": "after:execute", "interrupt": "after:execute"}


@pytest.mark.parametrize("fault", sorted(BUILDER_FAULTS))
@pytest.mark.parametrize("recipe_id", sorted(BUILDERS))
def test_wgfmu_waveform_ferro_builder_faults_leave_both_buses_safe(recipe_id: str, fault: str,
                                                                   tmp_path: Path) -> None:
    case = BUILDER_FAULTS[fault]
    h = harness(tmp_path, BUILDER_SCENARIOS[recipe_id])
    arm(h, BUILDER_MOMENTS[fault], 1, lambda: case.inject(h))
    tx, raised, _ = run_body(h, BUILDERS[recipe_id], WgfmuWaveformKind())
    assert tx is not None and tx.cleanup is not None
    assert raised is not None and isinstance(raised, case.raises), f"expected {case.raises}, got {raised!r}"  # type: ignore[arg-type]
    assert tx.cleanup.latched_fault == case.latched
    assert_invariant(h, tx, BUILDERS[recipe_id].envelope)


@pytest.mark.parametrize("recipe_id", sorted(BUILDERS))
def test_wgfmu_waveform_ferro_builder_clean_run(recipe_id: str, tmp_path: Path) -> None:
    h = harness(tmp_path, BUILDER_SCENARIOS[recipe_id])
    tx, raised, raw = run_body(h, BUILDERS[recipe_id], WgfmuWaveformKind())
    assert raised is None and tx is not None and isinstance(raw, WaveformAcquisition)
    assert_invariant(h, tx, BUILDERS[recipe_id].envelope)
    assert h.spy.names().count("execute") == 1 and tx.cleanup is not None and tx.cleanup.verified == "sim_state"
