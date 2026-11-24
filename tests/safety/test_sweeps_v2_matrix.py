"""Fault matrix of the WP7.2 sweeps with the global invariant (blueprint v2 8.1 ``safety/``; v1 3).

Kind ``smu_staircase`` with every new source shape, each compiled by the real planner and run by the real kind
inside ONE transaction on a noiseless simulator:

- ``wi``: ``basic.iv_force_i`` (log ``WI`` current sweep, voltage measured) on ``diode_basic``;
- ``wsv``: ``mosfet.idvg_sync`` (``WV`` + synchronous ``WSV``) on ``nmos_basic``;
- ``wsi``: test-only ``generic.sync_current`` (``WI`` + ``WSI``) on the two-resistor scenario;
- ``mm16``: test-only ``generic.multi_mixed`` (MM 16, ``WV`` + a current ``WNX`` source) on the two-resistor scenario;

x every fault x {configure (right before the primary sweep command), after XE, during the read, during cleanup}.
Kind ``smu_stepped`` with ``step_i`` (test-only ``generic.current_family``: ``DI`` per curve, four curves of 11
points, sweep on SMU3, step on SMU5) runs the whole stepped matrix of ``test_stepped_matrix.py`` (same shape, same
channels). Every case asserts the global invariant against the plan's own envelope (current sources: |I| within the
envelope's current, Vcomp within its voltage), the expected exception and the fault-latch outcome; separate tests
drive tampered programs (a 50 mA current source, a 50 V synchronous source) that never reach the simulator.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import SmuStaircaseKind, SmuSteppedKind
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops import core as driver_module
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.policy import DutProfile, DutTerminal
from b1500_test_agent.models.sim import (
    CleanupFailure,
    ComplianceAt,
    Disconnect,
    ErrxFault,
    GarbageData,
    IgnoreDz,
    InterlockOpen,
    Oscillation,
    SimFault,
    TimeoutFault,
)
from b1500_test_agent.models.station import PinMap, SimScenario
from b1500_test_agent.session import CleanupUnverified
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.integration.sweep_cases import TWO_RESISTORS, TWO_RESISTORS_NAME
from tests.safety.helpers import Harness, HookTransport, assert_global_invariant, make_harness
from tests.safety.test_stepped_matrix import STEPPED, SteppedHook
from tests.safety.test_stepped_matrix import run_case as run_stepped_case
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.rules_factory import T0, bundle, dut, engine, pin_map

pytestmark = pytest.mark.smu

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
FIXTURES = RecipeRegistry.load(REPO_ROOT / "tests" / "fixtures" / "recipes", repo_root=REPO_ROOT)
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "parser_exception", "envelope_violation")
ERRX_CODE = 305
POINTS = 11
TWO_R = PinMap(name="two-r", certainty="verified", terminals={"a": 3, "b": 5, "g": "GNDU"})
TWO_R_DUT = DutProfile(name="two-r", device_type="resistor", terminals={
    "a": DutTerminal(max_abs_v=2.0, max_abs_i=1e-3), "b": DutTerminal(max_abs_v=2.0, max_abs_i=1e-3),
    "g": DutTerminal(max_abs_v=0.0, max_abs_i=1e-2)})


def two_resistors() -> SimScenario:
    return SimScenario.model_validate({**TWO_RESISTORS, "name": TWO_RESISTORS_NAME})


def make_plan(registry: RecipeRegistry, recipe_id: str, pm: PinMap, du: DutProfile, **params: Any) -> PlanRecord:
    cfg = bundle(pin_maps=[pm], duts=[du])
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pm.name, "dut_profile": du.name,
                                      "params": params})
    plan = Planner(registry, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "ok", plan.rules.findings
    return plan


@dataclass(frozen=True)
class Variant:
    """One sweep shape: its plan, simulator scenario, the primary sweep channel and mnemonic."""

    plan: PlanRecord
    scenario: Callable[[], SimScenario]
    primary: int
    mnemonic: str


DIODE_PM = PinMap(name="diode-2t", certainty="verified", terminals={"anode": 3, "cathode": "GNDU"})
DIODE_DUT = DutProfile(name="diode-generic", device_type="diode", terminals={
    "anode": DutTerminal(max_abs_v=5.0, max_abs_i=1e-2), "cathode": DutTerminal(max_abs_v=5.0, max_abs_i=1e-2)})
VARIANTS: dict[str, Variant] = {
    "wi": Variant(make_plan(REGISTRY, "basic.iv_force_i", DIODE_PM, DIODE_DUT, points=POINTS),
                  lambda: noiseless(load_scenario("diode_basic")), 3, "WI"),
    "wsv": Variant(make_plan(REGISTRY, "mosfet.idvg_sync", pin_map(gate=4), dut(), vg_points=POINTS),
                   lambda: noiseless(load_scenario("nmos_basic")), 4, "WV"),
    "wsi": Variant(make_plan(FIXTURES, "generic.sync_current", TWO_R, TWO_R_DUT, points=POINTS), two_resistors, 3,
                   "WI"),
    "mm16": Variant(make_plan(FIXTURES, "generic.multi_mixed", TWO_R, TWO_R_DUT, points=POINTS), two_resistors, 3,
                    "WV"),
}
STEP_I = make_plan(FIXTURES, "generic.current_family", TWO_R, TWO_R_DUT)


class SweepHook(HookTransport):
    """``configure`` fires right before the primary sweep command (``WV``/``WI``) is written."""

    primary = "WV"

    def write(self, cmd: str) -> None:
        self._armed()
        if cmd.startswith(self.primary + " "):
            self.fire("configure")
        self.inner.write(cmd)
        if cmd == flex.XE:
            self.fire("after_xe")


def hook_for(mnemonic: str) -> Callable[[SimTransport], HookTransport]:
    def build(inner: SimTransport) -> HookTransport:
        hook = SweepHook(inner)
        hook.primary = mnemonic
        return hook

    return build


@dataclass(frozen=True)
class Case:
    """``moment``: hook moment, ``cleanup`` (end of the body) or ``setup`` (before the transaction); ``raises``:
    exact exception leaving the ``with`` block; ``latched``: fault latch; ``errors``: codes drained by the cleanup."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch, Variant], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    errors: tuple[int, ...] = ()


def sim(make: Callable[[Variant], SimFault]) -> Callable[[Harness, pytest.MonkeyPatch, Variant], None]:
    return lambda h, _mp, v: h.sim.inject(make(v))


def raise_now(make: Callable[[], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch, Variant], None]:
    def action(_h: Harness, _mp: pytest.MonkeyPatch, _v: Variant) -> None:
        raise make()

    return action


def arm(make: Callable[[Variant], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch, Variant], None]:
    def action(h: Harness, _mp: pytest.MonkeyPatch, v: Variant) -> None:
        h.hook.raise_next = make(v)

    return action


def buggy_50v(h: Harness, _mp: pytest.MonkeyPatch, v: Variant) -> None:
    """A buggy kind forces 50 V on the primary channel: the guard refuses before writing."""
    assert h.tx is not None
    h.tx.driver.force_v(v.primary, 50.0, icomp=1e-6)


def violation(v: Variant) -> BaseException:
    try:
        OutputGuard(v.plan.envelope).check(v.primary, "V", 50.0, 1e-6)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("the guard accepted 50 V")


def parse_error() -> BaseException:
    return FlexParseError("injected parser failure", raw="NAV+?")


def bad_parse_data(_h: Harness, mp: pytest.MonkeyPatch, _v: Variant) -> None:
    def broken(raw: str, fmt: int) -> list[object]:
        raise FlexParseError("injected parser failure on measurement data", raw=raw)

    mp.setattr(driver_module, "parse_data", broken)


def bad_parse_errx_once(_h: Harness, mp: pytest.MonkeyPatch, _v: Variant) -> None:
    original = driver_module.parse_errx
    calls = {"n": 0}

    def flaky(text: str) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlexParseError("injected ERRX? parser failure", raw=text)
        return original(text)

    mp.setattr(driver_module, "parse_errx", flaky)


C, A, R, X = "configure", "after_xe", "during_read", "cleanup"

CASES: dict[tuple[str, str], Case] = {
    # compliance at the first, a middle and the last step of the primary (auto abort: dummy data after it)
    ("compliance_at", "configure"): Case(C, sim(lambda v: ComplianceAt(step=0, ch=v.primary))),
    ("compliance_at", "after_xe"): Case(C, sim(lambda v: ComplianceAt(step=5, ch=v.primary))),
    ("compliance_at", "during_read"): Case(C, sim(lambda v: ComplianceAt(step=10, ch=v.primary))),
    ("compliance_at", "during_cleanup"): Case(X, sim(lambda v: ComplianceAt(step=0, ch=v.primary))),
    # an error after the primary sweep command (setup drain aborts before XE), after XE, after DZ / CL
    ("errx", "configure"): Case(C, sim(lambda v: ErrxFault(after_cmd=v.mnemonic, code=ERRX_CODE)),
                                raises=AcquisitionError),
    ("errx", "after_xe"): Case(C, sim(lambda v: ErrxFault(after_cmd="XE", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_read"): Case(R, sim(lambda v: ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_cleanup"): Case(X, sim(lambda v: ErrxFault(after_cmd="CL", code=ERRX_CODE)),
                                     errors=(ERRX_CODE,)),
    # the primary sweep command hangs; XE never completes; the read times out; DZ hangs in the cleanup
    ("timeout", "configure"): Case(C, sim(lambda v: TimeoutFault(on=v.mnemonic)), raises=TransportTimeout),
    ("timeout", "after_xe"): Case(C, sim(lambda v: TimeoutFault(on="XE")), raises=TransportTimeout),
    ("timeout", "during_read"): Case(C, sim(lambda v: TimeoutFault(on="read")), raises=TransportTimeout),
    ("timeout", "during_cleanup"): Case(X, sim(lambda v: TimeoutFault(on="DZ"))),
    ("garbage_data", "configure"): Case(C, sim(lambda v: GarbageData(at_step=0)), raises=FlexParseError),
    ("garbage_data", "after_xe"): Case(C, sim(lambda v: GarbageData(at_step=5)), raises=FlexParseError),
    ("garbage_data", "during_read"): Case(C, sim(lambda v: GarbageData(at_step=10)), raises=FlexParseError),
    ("garbage_data", "during_cleanup"): Case(X, sim(lambda v: GarbageData(at_step=0))),
    ("interlock_open", "configure"): Case(C, sim(lambda v: InterlockOpen())),
    ("interlock_open", "after_xe"): Case(C, sim(lambda v: InterlockOpen(at_step=5))),
    ("interlock_open", "during_read"): Case(R, sim(lambda v: InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(lambda v: InterlockOpen())),
    ("disconnect", "configure"): Case(C, sim(lambda v: Disconnect(after_writes=1)), raises=TransportError,
                                      latched=True),
    ("disconnect", "after_xe"): Case(A, sim(lambda v: Disconnect(after_writes=0)), raises=TransportError,
                                     latched=True),
    ("disconnect", "during_read"): Case(R, sim(lambda v: Disconnect(after_writes=0)), raises=TransportError,
                                        latched=True),
    ("disconnect", "during_cleanup"): Case(X, sim(lambda v: Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    ("oscillation", "configure"): Case(C, sim(lambda v: Oscillation(steps=[0]))),
    ("oscillation", "after_xe"): Case(C, sim(lambda v: Oscillation(steps=[5]))),
    ("oscillation", "during_read"): Case(C, sim(lambda v: Oscillation(steps=[10]))),
    ("oscillation", "during_cleanup"): Case(X, sim(lambda v: Oscillation())),
    # stuck outputs (a current source keeps forcing): verification must fail and latch
    ("ignore_dz", "configure"): Case(C, sim(lambda v: IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "after_xe"): Case(A, sim(lambda v: IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_read"): Case(R, sim(lambda v: IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, sim(lambda v: IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "configure"): Case(C, sim(lambda v: CleanupFailure(count=1))),
    ("cleanup_failure", "after_xe"): Case(A, sim(lambda v: CleanupFailure(count=2))),
    ("cleanup_failure", "during_read"): Case(R, sim(lambda v: CleanupFailure()), raises=CleanupUnverified,
                                             latched=True),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(lambda v: CleanupFailure()), raises=CleanupUnverified,
                                                latched=True),
    ("keyboard_interrupt", "configure"): Case(C, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt),
    ("keyboard_interrupt", "after_xe"): Case(A, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_read"): Case(R, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm(lambda v: KeyboardInterrupt()), raises=KeyboardInterrupt),
    ("parser_exception", "configure"): Case(C, raise_now(parse_error), raises=FlexParseError),
    ("parser_exception", "after_xe"): Case(A, raise_now(parse_error), raises=FlexParseError),
    ("parser_exception", "during_read"): Case("setup", bad_parse_data, raises=FlexParseError),
    ("parser_exception", "during_cleanup"): Case(X, bad_parse_errx_once),
    ("envelope_violation", "configure"): Case(C, buggy_50v, raises=EnvelopeViolation),
    ("envelope_violation", "after_xe"): Case(A, buggy_50v, raises=EnvelopeViolation),
    ("envelope_violation", "during_read"): Case(R, buggy_50v, raises=EnvelopeViolation),
    ("envelope_violation", "during_cleanup"): Case(X, arm(violation)),
}


def test_smu_staircase_v2_matrix_is_complete() -> None:
    assert set(CASES) == {(f, p) for f in FAULTS for p in POSITIONS}
    assert {v.mnemonic for v in VARIANTS.values()} == {"WI", "WV"}
    previews = {name: " ".join(v.plan.flex_preview) for name, v in VARIANTS.items()}
    assert "WSV" in previews["wsv"] and "WSI" in previews["wsi"] and "WNX 2,5,2" in previews["mm16"]
    assert "DI 5" in " ".join(STEP_I.flex_preview) and "WI 3,2" in previews["wi"]


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_smu_staircase_v2_fault_matrix(variant: str, fault: str, position: str, tmp_path: Path,
                            monkeypatch: pytest.MonkeyPatch) -> None:
    v = VARIANTS[variant]
    case = CASES[(fault, position)]
    h = make_harness(tmp_path, v.scenario(), hook_type=hook_for(v.mnemonic))
    if case.moment == "setup":
        case.inject(h, monkeypatch, v)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch, v))
    raised: BaseException | None = None
    result = None
    try:
        with h.transaction(envelope=v.plan.envelope, intent=f"{variant} safety run") as tx:
            h.tx = tx
            result = SmuStaircaseKind().acquire(tx, v.plan)
            if case.moment == X:
                case.inject(h, monkeypatch, v)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc

    assert_global_invariant(h, envelope=v.plan.envelope)
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())
        assert [e.code for e in tx.cleanup.errors] == list(case.errors)
    if case.raises is None:
        assert result is not None and len(result.blocks) == 1
        assert len(SmuStaircaseKind().to_table(result, v.plan)) == POINTS
    if isinstance(raised, AcquisitionError):
        assert not any(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log)  # nothing triggered after the error
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_smu_stepped_step_i_fault_matrix(fault: str, position: str, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """The stepped matrix (``test_stepped_matrix.STEPPED``) with a current step role: ``DI`` per curve."""
    case = STEPPED[(fault, position)]
    h = make_harness(tmp_path, two_resistors(), hook_type=SteppedHook)
    result, raised = run_stepped_case(h, case, STEP_I, monkeypatch)
    tx = h.tx
    assert tx is not None
    assert_global_invariant(h, envelope=STEP_I.envelope)
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None and (h.session.fault_latch.get() is not None) == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert [e.code for e in tx.cleanup.errors] == list(case.errors)
    if case.raises is None or case.raises is CleanupUnverified:
        assert result is not None and case.blocks is not None
        assert len(result.blocks) == case.blocks == result.kind_result["steps_done"]
        assert sum(r.mnemonic == "DI" and r.outcome == "ok" for r in h.log) == case.blocks


def test_smu_staircase_and_smu_stepped_clean_runs_send_their_previews(tmp_path: Path) -> None:
    for name, v in VARIANTS.items():
        h = make_harness(tmp_path / name, v.scenario(), hook_type=hook_for(v.mnemonic))
        with h.transaction(envelope=v.plan.envelope) as tx:
            SmuStaircaseKind().acquire(tx, v.plan)
        assert_global_invariant(h, envelope=v.plan.envelope)
        writes = [r.command for r in h.log if not r.mnemonic.endswith("?") and r.outcome == "ok"]
        assert writes == [*v.plan.flex_preview, "DZ", "CL"], name
    h = make_harness(tmp_path / "step_i", two_resistors(), hook_type=SteppedHook)
    with h.transaction(envelope=STEP_I.envelope) as tx:
        result = SmuSteppedKind().acquire(tx, STEP_I)
    assert_global_invariant(h, envelope=STEP_I.envelope)
    table = SmuSteppedKind().to_table(result, STEP_I)
    assert table["b_I"].unique().tolist() == [1e-6, 2e-6, 3e-6, 4e-6]


def tampered(plan: PlanRecord, path: tuple[str, ...], value: Any) -> PlanRecord:
    """``plan`` with one stored program value replaced (envelope unchanged): a buggy or tampered kind program."""
    data = copy.deepcopy(dict(plan.program))
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return plan.model_copy(update={"program": data})


@pytest.mark.parametrize(("variant", "path", "value", "reason"), [
    ("wi", ("sweep", "stop"), 0.05, "level_exceeds_envelope"),  # 50 mA current sweep (envelope 10 mA)
    ("wi", ("sweep", "vcomp"), 40.0, "compliance_exceeds_envelope"),  # Vcomp above the envelope's 2 V
    ("wsv", ("sweep", "sync", "stop"), 50.0, "level_exceeds_envelope"),  # synchronous source at 50 V
    ("mm16", ("sweep", "sources", 0, "stop"), 0.05, "level_exceeds_envelope"),  # WNX current source at 50 mA
])
def test_smu_staircase_tampered_sources_never_reach_the_simulator(variant: str, path: tuple[Any, ...], value: float,
                                                                  reason: str, tmp_path: Path) -> None:
    v = VARIANTS[variant]
    plan = tampered(v.plan, path, value)
    h = make_harness(tmp_path, v.scenario(), hook_type=hook_for(v.mnemonic))
    with pytest.raises(EnvelopeViolation) as caught, h.transaction(envelope=plan.envelope) as tx:
        SmuStaircaseKind().acquire(tx, plan)
    assert caught.value.reason == reason
    assert_global_invariant(h, envelope=plan.envelope)
    assert not any(r.mnemonic in {"MM", "WV", "WI", "WSV", "WSI", "WNX", "XE"} for r in h.log)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"


def test_smu_stepped_tampered_step_current_never_reaches_the_simulator(tmp_path: Path) -> None:
    plan = STEP_I.model_copy(update={"program": {**STEP_I.program, "step_values": [1e-6, 5e-2, 3e-6]}})
    h = make_harness(tmp_path, two_resistors(), hook_type=SteppedHook)
    with pytest.raises(EnvelopeViolation) as caught, h.transaction(envelope=plan.envelope) as tx:
        SmuSteppedKind().acquire(tx, plan)
    assert caught.value.reason == "level_exceeds_envelope" and caught.value.limit == 4e-6
    assert_global_invariant(h, envelope=plan.envelope)
    assert [r.command for r in h.log if r.mnemonic == "DI"] == ["DI 5,0,1E-06,2"]
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
