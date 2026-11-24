"""Kind ``wgfmu_waveform`` rows of the fault matrix with the global invariant v2 on both buses (blueprint v2 2.6, 4.3,
8.1 ``safety/``; WP10.4).

The body is the real kind (``WgfmuWaveformKind.acquire``) running plans the real planner compiled from the committed
recipes, inside ONE transaction on the noiseless ``nmos_wgfmu`` scenario with both links spied
(``wgfmu_helpers``): ``wgfmu.pulsed_iv`` with an SMU body bias on SMU5 (FLEX ``CN``/``DV`` before the WGFMU phase, held
through it: WG Ex. 10) and ``wgfmu.dc_spot`` (DC mode: RSU connect, DC levels, DC readings; no sequencer).

Faults {``wgfmu_error``, ``wgfmu_hang``, ``wgfmu_disconnect_fails``, ``wgfmu_dll_missing``, Ctrl-C, a buggy WGFMU level
outside the envelope, FLEX ``errx`` and ``timeout`` on the SMU bias} x positions {bias (the SMU level write), open
(entering the phase), load, run (sequencer started / first DC level), readback (sequencer read / first DC reading),
cleanup (the phase exit's first safe-state call)}. Every case asserts the invariant: no level outside the plan's
envelope reached the library or FLEX, the library ran only with the FLEX exclusive lock released, and afterwards every
SMU is at 0 V and off, every WGFMU channel disconnected and idle, the library session closed and the FLEX link locked
again, or the fault latch is set with ``cleanup_unverified``. The cleanup ran in order; lock and in-flight marker are
gone. Tampered plans (a level above the envelope) are refused before the first library call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

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

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
KIND = WgfmuWaveformKind()
BODY = pin_map_exact("body", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU", "bulk": 5})
RESISTOR = pin_map_exact("r-wg", {"a": "RSU201.OUT", "b": "GNDU"})
PULSE = TerminalPulse(max_abs_v=5.0, max_width_s=1e-2, max_duty=0.5, max_count=1_000_000)
NMOS = DutProfile(name="body", device_type="nmos", terminals={
    "gate": DutTerminal(max_abs_v=5.0, max_abs_i=1e-3, pulse=PULSE),
    "drain": DutTerminal(max_abs_v=3.0, max_abs_i=1e-2), "source": DutTerminal(max_abs_v=1.0, max_abs_i=1e-2),
    "bulk": DutTerminal(max_abs_v=2.0, max_abs_i=1e-3)})
RES = DutProfile(name="r-wg", device_type="resistor", terminals={"a": DutTerminal(max_abs_v=1.0, max_abs_i=1e-3),
                                                                  "b": DutTerminal(max_abs_v=1.0, max_abs_i=1e-3)})
GATE, BULK = 201, 5


def make_plan(recipe_id: str, pin_map: str, dut: str, **params: Any) -> PlanRecord:
    cfg = bundle(station_profile=lab_station(), pin_maps=[BODY, RESISTOR], duts=[NMOS, RES])
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map, "dut_profile": dut,
                                      "params": params})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "ok", plan.summary
    return plan


PULSED = make_plan("wgfmu.pulsed_iv", "body", "body", vg_points=4, vb=-0.5)
DC = make_plan("wgfmu.dc_spot", "r-wg", "r-wg", a_levels=[-0.1, 0.0, 0.1], samples=2)
PLANS = {"pulsed": PULSED, "dc": DC}

MOMENTS = {
    "pulsed": {"open": "before:open_session", "load": "before:create_pattern", "run": "after:execute",
               "readback": "before:measure_value_size", "cleanup": "before:abort"},
    "dc": {"open": "before:open_session", "load": "before:set_operation_mode", "run": "after:dc_force_voltage",
           "readback": "before:dc_measure_value", "cleanup": "before:abort"},
}
"""Position -> spy moment on the library (``bias`` is a FLEX moment: the SMU level write)."""
POSITIONS = ("bias", "open", "load", "run", "readback", "cleanup")


@dataclass(frozen=True)
class Case:
    inject: Callable[[WgHarness], None]
    raises: type[BaseException] | None = None
    latched: bool = False


def sim(fault: SimFault) -> Callable[[WgHarness], None]:
    return lambda h: h.sim.inject(fault)


def interrupt(_h: WgHarness) -> None:
    raise KeyboardInterrupt


def too_high(h: WgHarness) -> None:
    """A buggy body asks the WGFMU for 5 V on a channel whose envelope is lower: refused before the library."""
    assert h.tx is not None
    link = h.tx.wgfmu_link
    wg = link.driver if link.driver is not None else WgfmuDriver(h.session.bus.wgfmu, h.tx.driver.guard)  # type: ignore[arg-type]
    wg.force_dc(GATE, 5.0)


E, SSF, KI, EV, TO = WgfmuError, WgfmuSafeStateFailed, KeyboardInterrupt, EnvelopeViolation, TransportTimeout
STUCK = WgfmuDisconnectFails()
LIBRARY: dict[str, dict[str, Case]] = {
    "wgfmu_error": {"open": Case(sim(WgfmuErrorFault(fn="open_session", code=api.COMMUNICATION_ERROR)), E),
                    "load": Case(sim(WgfmuErrorFault(fn="add_vectors", code=api.PARAMETER_OUT_OF_RANGE)), E),
                    "run": Case(sim(WgfmuErrorFault(fn="status", code=3050)), E),
                    "readback": Case(sim(WgfmuErrorFault(fn="measure_values", code=3015)), E),
                    "cleanup": Case(sim(WgfmuErrorFault(fn="disconnect", code=3001)), SSF)},
    "wgfmu_hang": {"open": Case(sim(WgfmuHang(fn="initialize")), E),
                   "load": Case(sim(WgfmuHang(fn="execute")), E),
                   "run": Case(sim(WgfmuHang(fn="status")), E),
                   "readback": Case(sim(WgfmuHang(fn="measure_value_size")), E),
                   "cleanup": Case(sim(WgfmuHang(fn="abort")), SSF)},
    "wgfmu_disconnect_fails": {p: Case(sim(STUCK), SSF, latched=True)
                               for p in ("open", "load", "run", "readback", "cleanup")},
    "wgfmu_dll_missing": {"open": Case(sim(WgfmuDllMissing()), E), "load": Case(sim(WgfmuDllMissing())),
                          "run": Case(sim(WgfmuDllMissing())), "readback": Case(sim(WgfmuDllMissing())),
                          "cleanup": Case(sim(WgfmuDllMissing()))},
    "keyboard_interrupt": {p: Case(interrupt, KI) for p in ("open", "load", "run", "readback", "cleanup")},
    "envelope_violation": {**{p: Case(too_high, EV) for p in ("open", "load", "run", "readback")},
                           "cleanup": Case(too_high, SSF)},
}
"""Library-side faults (positions after the SMU bias)."""
DC_OVERRIDES: dict[tuple[str, str], Case] = {
    ("wgfmu_error", "load"): Case(sim(WgfmuErrorFault(fn="set_operation_mode", code=api.PARAMETER_OUT_OF_RANGE)), E),
    ("wgfmu_error", "run"): Case(sim(WgfmuErrorFault(fn="dc_measure_value", code=3015)), E),
    ("wgfmu_error", "readback"): Case(sim(WgfmuErrorFault(fn="dc_measure_value", code=3015)), E),
    ("wgfmu_hang", "load"): Case(sim(WgfmuHang(fn="dc_force_voltage")), E),
    ("wgfmu_hang", "run"): Case(sim(WgfmuHang(fn="dc_measure_value")), E),
    ("wgfmu_hang", "readback"): Case(sim(WgfmuHang(fn="dc_measure_value")), E),
}
"""The DC path has no sequencer: its run and readback faults hit the DC functions."""
FLEX = {"errx": Case(sim(ErrxFault(after_cmd="DV", code=305)), Exception),
        "timeout": Case(sim(TimeoutFault(on="query:ERRX?")), TO)}
"""SMU-bias faults (position ``bias``: injected right before the bulk's ``DV``)."""


def case_for(plan: str, fault: str, position: str) -> Case | None:
    if position == "bias":
        return FLEX.get(fault) if plan == "pulsed" else None
    if fault in FLEX:
        return None
    if plan == "dc" and (fault, position) in DC_OVERRIDES:
        return DC_OVERRIDES[(fault, position)]
    return LIBRARY[fault][position]


CASES = [(plan, fault, position) for plan in PLANS for fault in (*LIBRARY, *FLEX) for position in POSITIONS
         if case_for(plan, fault, position) is not None]


def assert_waveform_invariant(h: WgHarness, tx: Transaction, envelope: CompiledEnvelope) -> None:
    """Global invariant v2 for the plan's envelope (module docstring)."""
    limit = max(e.max_abs_v for e in envelope.channels.values() if e.function == "wgfmu")
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


def harness(tmp_path: Path) -> WgHarness:
    return make_wg_harness(tmp_path, noiseless(load_scenario("nmos_wgfmu")))


def run_body(h: WgHarness, plan: PlanRecord) -> tuple[Transaction | None, BaseException | None, Any]:
    raised: BaseException | None = None
    tx: Transaction | None = None
    raw = None
    try:
        with h.transaction(envelope=plan.envelope) as tx:
            h.tx = tx
            raw = KIND.acquire(tx, plan)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return tx, raised, raw


def test_matrix_is_complete() -> None:
    assert len(CASES) == 2 * 6 * 5 + 2  # both plans x six library faults x five positions + two FLEX bias faults
    assert {"wgfmu_error", "wgfmu_hang", "wgfmu_disconnect_fails", "wgfmu_dll_missing"} <= set(LIBRARY)


@pytest.mark.parametrize(("plan", "fault", "position"), CASES)
def test_wgfmu_waveform_fault_matrix(plan: str, fault: str, position: str, tmp_path: Path) -> None:
    case = case_for(plan, fault, position)
    assert case is not None
    h = harness(tmp_path)
    if position == "bias":
        original = h.hook.write

        def write(cmd: str) -> None:
            if cmd.startswith("DV 5,"):
                case.inject(h)
            original(cmd)

        h.hook.write = write  # type: ignore[method-assign]
    else:
        h.spy.actions[MOMENTS[plan][position]] = lambda: case.inject(h)
    tx, raised, _ = run_body(h, PLANS[plan])
    assert tx is not None and tx.cleanup is not None
    if case.raises is None:
        assert raised is None, raised
    else:
        assert raised is not None and isinstance(raised, case.raises), f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_waveform_invariant(h, tx, PLANS[plan].envelope)
    if position == "bias":
        assert "open_session" not in h.spy.names()  # a FLEX failure before the phase never opens the library
    if case.raises is EV and position != "cleanup":
        assert all(args[1] != 5.0 for name, args in h.spy.calls if name == "dc_force_voltage")


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_a_clean_run_leaves_both_buses_safe(plan: str, tmp_path: Path) -> None:
    h = harness(tmp_path)
    tx, raised, raw = run_body(h, PLANS[plan])
    assert raised is None and tx is not None and isinstance(raw, WaveformAcquisition)
    assert_waveform_invariant(h, tx, PLANS[plan].envelope)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
    assert tx.wgfmu_phases == (["unlocked (flex_io)"] if plan == "pulsed" else ["unlocked"])
    log = [r.command for r in h.sim.instrument.command_log if r.outcome == "ok"]
    if plan == "pulsed":
        assert log.index("CN 5") < log.index("DV 5,0,-0.5,0.0001")
        assert len(raw.traces[202]) == 4
    else:
        assert "CN" not in {c.split(" ")[0] for c in log} and len(raw.dc_rows) == 6


@pytest.mark.parametrize(("path", "value"), [
    (("waveform", "patterns", "gate", "vectors", 5, 1), 3.5),
    (("waveform", "patterns", "drain", "v0"), -1.5),
])  # fmt: skip
def test_a_tampered_program_is_refused_before_any_library_call(path: tuple[Any, ...], value: float,
                                                               tmp_path: Path) -> None:
    data = PULSED.model_dump(mode="json")
    target = data["program"][SOURCE_PLAN_KEY]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    tampered = PlanRecord.model_validate(data)
    h = harness(tmp_path)
    tx, raised, _ = run_body(h, tampered)
    assert isinstance(raised, EnvelopeViolation) and raised.reason == "level_exceeds_envelope"
    assert not {"create_pattern", "add_vectors", "connect", "execute"} & set(h.spy.names())
    assert tx is not None
    assert_waveform_invariant(h, tx, PULSED.envelope)


def test_a_tampered_dc_level_is_refused_before_any_library_call(tmp_path: Path) -> None:
    data = DC.model_dump(mode="json")
    data["program"][SOURCE_PLAN_KEY]["waveform"]["dc"]["201"][1] = 0.6
    h = harness(tmp_path)
    tx, raised, _ = run_body(h, PlanRecord.model_validate(data))
    assert isinstance(raised, EnvelopeViolation) and "dc_force_voltage" not in h.spy.names()
    assert tx is not None
    assert_waveform_invariant(h, tx, DC.envelope)
