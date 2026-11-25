"""Kind ``stress_measure``, WGFMU path (``wgfmu.fast_bti``), rows of the fault matrix with the global invariant v2 on
both buses (blueprint v2 2.6, 4.3, 8.1 ``safety/``; WP10.7 AC "both buses clean after faults").

The body is the real kind (``StressMeasureKind.acquire``) running plans the real planner compiled from the committed
recipe, inside ONE transaction on the noiseless ``nmos_bti`` scenario with both links spied (``wgfmu_helpers``): a
short fast BTI (reference read, then four stress reads in a second WGFMU execution) with an SMU body bias on SMU5
(FLEX ``CN``/``DV`` inside the WGFMU phase, one ``XE`` of the bulk between the two executions: WG Ex. 10/11), and the
same without the bias. Kind ``system``'s WGFMU library self-test runs through the same phase: its library faults
leave both buses safe too.

Faults {``wgfmu_error``, ``wgfmu_hang``, ``wgfmu_disconnect_fails``, ``wgfmu_dll_missing``, Ctrl-C, a buggy WGFMU level
outside the envelope; FLEX ``errx`` and ``timeout`` on the SMU side} x positions {bias (the bulk's level write), open
(entering the phase), load (the reference execution's setup), reference (its sequencer started), stress (the second
execution's sequencer started), readback (the second execution's readback), between (the bulk's reading between the
executions), cleanup (the phase exit's first safe-state call)}. Every case asserts the invariant: no level outside the
plan's envelope reached the library or FLEX, the library ran only with the FLEX exclusive lock released, and
afterwards every SMU is at 0 V and off, every WGFMU channel disconnected and idle, the library session closed and the
FLEX link locked again, or the fault latch is set with ``cleanup_unverified``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds.stress_measure import StressMeasureKind
from b1500_test_agent.catalog.kinds.stress_wgfmu import WgfmuStressAcquisition
from b1500_test_agent.catalog.kinds.system import SystemKind
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.driver.wgfmu import WgfmuDriver, WgfmuSafeStateFailed
from b1500_test_agent.models.plan import CompiledEnvelope, PlanRecord, PlanRequest
from b1500_test_agent.models.policy import DutProfile, DutTerminal
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
KIND = StressMeasureKind()
BODY = pin_map_exact("body", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU", "bulk": 5})
THREE = pin_map_exact("three", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU"})
DUT = DutProfile(name="nmos", device_type="nmos", terminals={
    "gate": DutTerminal(max_abs_v=5.0, max_abs_i=1e-3), "drain": DutTerminal(max_abs_v=3.0, max_abs_i=1e-2),
    "source": DutTerminal(max_abs_v=1.0, max_abs_i=1e-2), "bulk": DutTerminal(max_abs_v=2.0, max_abs_i=1e-3)})
GATE = 201


def make_plan(pin_map: str, **params: Any) -> PlanRecord:
    cfg = bundle(station_profile=lab_station(), pin_maps=[BODY, THREE], duts=[DUT])
    req = PlanRequest.model_validate({"recipe_id": "wgfmu.fast_bti", "pin_map": pin_map, "dut_profile": "nmos",
                                      "params": {"vg_stress": 2.0, "stress_time": 0.01, **params}})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "needs_confirmation" and plan.rules.confirm_reasons == ["destructive"], plan.summary
    return plan


BIASED = make_plan("body", vb=-0.5)
PLAIN = make_plan("three")
PLANS = {"biased": BIASED, "plain": PLAIN}

MOMENTS = {"open": ("before:open_session", 1), "load": ("before:create_pattern", 1),
           "reference": ("after:execute", 1), "stress": ("after:execute", 2),
           "readback": ("before:measure_value_size", 2), "cleanup": ("before:abort", 1)}
"""Library positions: ``(spy moment, which occurrence)``; ``bias`` and ``between`` are FLEX moments."""
POSITIONS = ("bias", "open", "load", "reference", "stress", "readback", "between", "cleanup")


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
    """A buggy body asks the WGFMU for 5 V on the gate, whose envelope is 2 V: refused before the library."""
    assert h.tx is not None
    link = h.tx.wgfmu_link
    wg = link.driver if link.driver is not None else WgfmuDriver(h.session.bus.wgfmu, h.tx.driver.guard)  # type: ignore[arg-type]
    wg.force_dc(GATE, 5.0)


E, SSF, KI, EV, TO = WgfmuError, WgfmuSafeStateFailed, KeyboardInterrupt, EnvelopeViolation, TransportTimeout
STUCK = WgfmuDisconnectFails()
LIBRARY_POSITIONS = ("open", "load", "reference", "stress", "readback", "cleanup")
LIBRARY: dict[str, dict[str, Case]] = {
    "wgfmu_error": {"open": Case(sim(WgfmuErrorFault(fn="open_session", code=api.COMMUNICATION_ERROR)), E),
                    "load": Case(sim(WgfmuErrorFault(fn="add_vectors", code=api.PARAMETER_OUT_OF_RANGE)), E),
                    "reference": Case(sim(WgfmuErrorFault(fn="status", code=3050)), E),
                    "stress": Case(sim(WgfmuErrorFault(fn="status", code=3050)), E),
                    "readback": Case(sim(WgfmuErrorFault(fn="measure_values", code=3015)), E),
                    "cleanup": Case(sim(WgfmuErrorFault(fn="disconnect", code=3001)), SSF)},
    "wgfmu_hang": {"open": Case(sim(WgfmuHang(fn="initialize")), E),
                   "load": Case(sim(WgfmuHang(fn="execute")), E),
                   "reference": Case(sim(WgfmuHang(fn="status")), E),
                   "stress": Case(sim(WgfmuHang(fn="status")), E),
                   "readback": Case(sim(WgfmuHang(fn="measure_value_size")), E),
                   "cleanup": Case(sim(WgfmuHang(fn="abort")), SSF)},
    "wgfmu_disconnect_fails": {p: Case(sim(STUCK), SSF, latched=True) for p in LIBRARY_POSITIONS},
    "wgfmu_dll_missing": {"open": Case(sim(WgfmuDllMissing()), E), "load": Case(sim(WgfmuDllMissing())),
                          "reference": Case(sim(WgfmuDllMissing())), "stress": Case(sim(WgfmuDllMissing())),
                          "readback": Case(sim(WgfmuDllMissing())), "cleanup": Case(sim(WgfmuDllMissing()))},
    "keyboard_interrupt": {p: Case(interrupt, KI) for p in LIBRARY_POSITIONS},
    "envelope_violation": {**{p: Case(too_high_level, EV) for p in LIBRARY_POSITIONS if p != "cleanup"},
                           "cleanup": Case(too_high_level, SSF)},
}
"""Library-side faults."""
FLEX: dict[str, dict[str, Case]] = {
    "errx": {"bias": Case(sim(ErrxFault(after_cmd="DV", code=305)), Exception),
             "between": Case(sim(ErrxFault(after_cmd="XE", code=305)), Exception)},
    "timeout": {"bias": Case(sim(TimeoutFault(on="query:ERRX?")), TO),
                "between": Case(sim(TimeoutFault(on="query:ERRX?")), TO)},
}
"""SMU-side faults (``bias``: right before the bulk's ``DV``; ``between``: right before the bulk's ``XE``)."""


def case_for(plan: str, fault: str, position: str) -> Case | None:
    if position in ("bias", "between"):
        return FLEX[fault][position] if plan == "biased" and fault in FLEX else None
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


def assert_stress_invariant(h: WgHarness, tx: Transaction, envelope: CompiledEnvelope) -> None:
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


def harness(tmp_path: Path) -> WgHarness:
    return make_wg_harness(tmp_path, noiseless(load_scenario("nmos_bti")))


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


def test_stress_measure_wgfmu_matrix_is_complete() -> None:
    assert len(CASES) == 2 * 6 * 6 + 2 * 2  # both plans x six library faults x six positions + four SMU-side faults
    assert {"wgfmu_error", "wgfmu_hang", "wgfmu_disconnect_fails", "wgfmu_dll_missing"} <= set(LIBRARY)
    assert len(BIASED.program["runs"]) == 2  # the reference execution, then the stress execution


@pytest.mark.parametrize(("plan", "fault", "position"), CASES)
def test_stress_measure_wgfmu_fault_matrix(plan: str, fault: str, position: str, tmp_path: Path) -> None:
    case = case_for(plan, fault, position)
    assert case is not None
    h = harness(tmp_path)
    if position in ("bias", "between"):
        prefix = "DV 5," if position == "bias" else "XE"
        original = h.hook.write

        def write(cmd: str) -> None:
            if cmd.startswith(prefix):
                case.inject(h)
            original(cmd)

        h.hook.write = write  # type: ignore[method-assign]
    else:
        moment, occurrence = MOMENTS[position]
        arm(h, moment, occurrence, lambda: case.inject(h))
    tx, raised, _ = run_body(h, PLANS[plan])
    assert tx is not None and tx.cleanup is not None
    if case.raises is None:
        assert raised is None, raised
    else:
        assert raised is not None and isinstance(raised, case.raises), f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_stress_invariant(h, tx, PLANS[plan].envelope)
    if case.raises is EV and position != "cleanup":
        assert all(args[1] != 5.0 for name, args in h.spy.calls if name == "dc_force_voltage")


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_stress_measure_wgfmu_clean_run_leaves_both_buses_safe(plan: str, tmp_path: Path) -> None:
    h = harness(tmp_path)
    tx, raised, raw = run_body(h, PLANS[plan])
    assert raised is None and tx is not None and isinstance(raw, WgfmuStressAcquisition)
    assert_stress_invariant(h, tx, PLANS[plan].envelope)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
    assert len(raw.traces) == 2 and raw.kind_result["runs_done"] == 2
    log = [r.command for r in h.sim.instrument.command_log if r.outcome == "ok"]
    if plan == "biased":
        assert tx.wgfmu_phases == ["unlocked (flex_io)"]
        assert log.index("CN 5") < log.index("DV 5,0,-0.5,0.0001") < log.index("XE")
        names = h.spy.names()
        assert names.index("initialize") < names.index("execute")  # the bias follows initialize (ATV-17 order)
    else:
        assert tx.wgfmu_phases == ["unlocked"] and "CN" not in {c.split(" ")[0] for c in log}


def test_stress_measure_wgfmu_tampered_program_is_refused_before_any_level(tmp_path: Path) -> None:
    data = PLAIN.model_dump(mode="json")
    data["program"][SOURCE_PLAN_KEY]["waveform"]["patterns"]["gate_h1"]["vectors"][1][1] = 3.5
    tampered = PlanRecord.model_validate(data)
    h = harness(tmp_path)
    tx, raised, _ = run_body(h, tampered)
    assert isinstance(raised, EnvelopeViolation) and raised.reason == "level_exceeds_envelope"
    assert not {"create_pattern", "add_vectors", "connect", "execute"} & set(h.spy.names())
    assert tx is not None
    assert_stress_invariant(h, tx, PLAIN.envelope)


# -- kind system: the WGFMU library self-test and self-calibration ------------------------------------------------


SYSTEM_KIND = SystemKind()
SYSTEM_PLANS = {op: Planner(REGISTRY, clock=lambda: T0).plan(PlanRequest.model_validate(
    {"recipe_id": f"system.{op}", "pin_map": "three", "dut_profile": None, "params": {}}),
    (cfg := bundle(station_profile=lab_station(), pin_maps=[BODY, THREE], duts=[DUT])), engine(cfg))
    for op in ("wgfmu_self_test", "wgfmu_self_cal")}
SYSTEM_CASES = {
    "error": Case(sim(WgfmuErrorFault(fn="self_test", code=api.LIBRARY_ERROR)), E),
    "hang": Case(sim(WgfmuHang(fn="self_test")), E),
    "interrupt": Case(interrupt, KI),
}
"""Library faults during the self-test (no channel is connected, so a stuck RSU relay has nothing to open)."""


@pytest.mark.parametrize("fault", sorted(SYSTEM_CASES))
def test_system_wgfmu_self_test_faults_leave_both_buses_safe(fault: str, tmp_path: Path) -> None:
    plan = SYSTEM_PLANS["wgfmu_self_test"]
    case = SYSTEM_CASES[fault]
    h = harness(tmp_path)
    arm(h, "before:self_test", 1, lambda: case.inject(h))
    raised: BaseException | None = None
    tx: Transaction | None = None
    try:
        with h.transaction(envelope=plan.envelope) as tx:
            h.tx = tx
            SYSTEM_KIND.acquire(tx, plan)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    assert tx is not None and tx.cleanup is not None
    assert raised is not None and isinstance(raised, case.raises), f"expected {case.raises}, got {raised!r}"  # type: ignore[arg-type]
    assert tx.cleanup.latched_fault == case.latched
    assert_stress_invariant(h, tx, plan.envelope)
    assert not {"create_pattern", "add_vectors", "connect", "execute"} & set(h.spy.names())


@pytest.mark.parametrize("operation", sorted(SYSTEM_PLANS))
def test_system_wgfmu_maintenance_clean_run(operation: str, tmp_path: Path) -> None:
    plan = SYSTEM_PLANS[operation]
    h = harness(tmp_path)
    with h.transaction(envelope=plan.envelope) as tx:
        raw = SYSTEM_KIND.acquire(tx, plan)
    assert raw.ok and raw.kind_result["result"] == 0 and tx.wgfmu_phases == ["unlocked"]
    assert_stress_invariant(h, tx, plan.envelope)
    assert h.sim.instrument.command_log == [] or all(not r.source for r in h.sim.instrument.command_log)
