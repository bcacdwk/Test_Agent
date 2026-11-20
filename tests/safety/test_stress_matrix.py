"""Stress-measure rows of the fault matrix with the global invariant v2 (WP7.6; blueprint v2 2.6, 4.3, 8.1
``safety/``; per-recipe AC ``tests/safety -k stress_measure``).

The body is the real ``stress_measure`` kind (``StressMeasureKind.acquire``) running the committed
``reliability.bti_sms`` recipe compiled by the real planner (gate stress 2 V, reads at 0, 1, 10 and 30 s of stress and
1 and 10 s of recovery: eleven checkpoints, R0 H1 R1 H2 R2 H3 R3 H4 R4 H5 R5, one ``XE`` each), inside ONE
transaction on the noiseless ``nmos_bti`` simulator (gate SMU4, drain SMU3; the gate oxide breaks only under the
``breakdown_at`` fault). Every fault of the sampling matrix is injected at every position: ``configure`` = right
before the first ``MT`` (the first hold block's setup, after the reference read), ``after_xe`` = right after the
second ``XE`` (the first hold block; the simulator evaluates a measurement at its trigger, so instrument faults act on
the next read), ``during_read`` = at the second data read, ``during_cleanup`` = after the body.

Every case asserts the global invariant against the plan's own envelope (stress, recovery and read levels), the
expected exception and fault-latch outcome, how many reads and hold blocks were done (a compliance, overflow or
oscillation in a hold block or a read ends the run: ``kind_result``) and that the table rebuilds from the blocks.
Separate tests drive a tampered program (a stress above the envelope), an unsupported route and a clean run (exactly
the FLEX preview on the wire).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.blocks import RouteStep, apply_routes
from b1500_test_agent.catalog.kinds import StressMeasureKind, StressProgram
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops import core as driver_module  # parse_data/parse_errx are looked up here
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sim import (
    BreakdownAt,
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
from b1500_test_agent.session import CleanupUnverified
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.safety.helpers import Harness, HookTransport, assert_global_invariant, make_harness
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.rules_factory import T0, bundle, dut, engine, pin_map

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = StressMeasureKind()
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "parser_exception", "envelope_violation",
          "breakdown_at")
ERRX_CODE = 305
GATE, DRAIN = 4, 3  # the nmos_bti wiring
NTH = 2
SCENARIO = noiseless(load_scenario("nmos_bti"))
OPS = 11
READ_STEPS = 35


def stress_plan() -> PlanRecord:
    registry = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
    cfg = bundle(pin_maps=[pin_map(gate=GATE, drain=DRAIN)], duts=[dut()])
    req = PlanRequest.model_validate({
        "recipe_id": "reliability.bti_sms", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic",
        "params": {"vg_stress": 2.0, "stress_time": 30.0, "reads_per_decade": 1, "recovery_time": 10.0}})
    plan = Planner(registry, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "needs_confirmation" and set(plan.rules.confirm_reasons) == {"destructive"}
    assert len(StressProgram.model_validate(plan.program).timeline()) == OPS
    return plan


PLAN = stress_plan()


class StressHook(HookTransport):
    """``configure`` fires right before the first ``MT`` write, ``after_xe`` after the NTH ``XE``, ``during_read`` at
    the NTH data read; ``raise_next`` as in ``HookTransport``."""

    def __init__(self, inner: SimTransport) -> None:
        super().__init__(inner)
        self.xe = 0
        self.reads = 0

    def write(self, cmd: str) -> None:
        self._armed()
        if cmd.startswith("MT "):
            self.fire("configure")
        self.inner.write(cmd)
        if cmd == flex.XE:
            self.xe += 1
            if self.xe == NTH:
                self.fire("after_xe")

    def read(self, *, timeout_s: float | None = None) -> str:
        self._armed()
        self.reads += 1
        if self.reads == NTH:
            self.fire("during_read")
        return self.inner.read(timeout_s=timeout_s)


@dataclass(frozen=True)
class Case:
    """``moment``: hook moment, ``cleanup`` (end of the body) or ``setup``; ``raises``: exact exception type leaving
    the ``with`` block; ``latched``: fault latch set; ``ops``: reads + hold blocks done when the body completes
    (``None`` when it raises); ``stop``: the run reported a stop reason; ``errors``: codes drained by the cleanup."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    ops: int | None = OPS
    stop: bool = False
    errors: tuple[int, ...] = ()


def sim(fault: SimFault) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    return lambda h, _mp: h.sim.inject(fault)


def raise_now(make: Callable[[], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    def action(_h: Harness, _mp: pytest.MonkeyPatch) -> None:
        raise make()

    return action


def arm(make: Callable[[], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    def action(h: Harness, _mp: pytest.MonkeyPatch) -> None:
        h.hook.raise_next = make()

    return action


def buggy_50v(h: Harness, _mp: pytest.MonkeyPatch) -> None:
    """A deliberately buggy kind asks for 50 V on the stressed gate (envelope 2 V): refused before writing."""
    assert h.tx is not None
    h.tx.driver.force_v(GATE, 50.0, icomp=1e-6)


def violation() -> BaseException:
    try:
        OutputGuard(PLAN.envelope).check(GATE, "V", 50.0, 1e-6)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("the guard accepted 50 V")


def parse_error() -> BaseException:
    return FlexParseError("injected parser failure", raw="NDI+?")


def bad_parse_data_nth(_h: Harness, mp: pytest.MonkeyPatch) -> None:
    original = driver_module.parse_data
    calls = {"n": 0}

    def flaky(raw: str, fmt: int) -> object:
        calls["n"] += 1
        if calls["n"] == NTH:
            raise FlexParseError("injected parser failure on a hold block", raw=raw)
        return original(raw, fmt)

    mp.setattr(driver_module, "parse_data", flaky)


def bad_parse_errx_once(_h: Harness, mp: pytest.MonkeyPatch) -> None:
    original = driver_module.parse_errx
    calls = {"n": 0}

    def flaky(text: str) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlexParseError("injected ERRX? parser failure", raw=text)
        return original(text)

    mp.setattr(driver_module, "parse_errx", flaky)


C, A, R, X = "configure", "after_xe", "during_read", "cleanup"

STRESS: dict[tuple[str, str], Case] = {
    # compliance on the gate: the first hold block's sample (stops there), step 5 / 10 of the first stress read
    ("compliance_at", "configure"): Case(C, sim(ComplianceAt(step=0, ch=GATE)), ops=2, stop=True),
    ("compliance_at", "after_xe"): Case(A, sim(ComplianceAt(step=5, ch=GATE)), ops=3, stop=True),
    ("compliance_at", "during_read"): Case(R, sim(ComplianceAt(step=10, ch=GATE)), ops=3, stop=True),
    ("compliance_at", "during_cleanup"): Case(X, sim(ComplianceAt(step=0, ch=GATE))),
    # an error after MT (the hold drain aborts before its XE), after the next XE (caught before the next hold), after
    # DZ / CL in the cleanup (drained into the cleanup report)
    ("errx", "configure"): Case(C, sim(ErrxFault(after_cmd="MT", code=ERRX_CODE)), raises=AcquisitionError, ops=None),
    ("errx", "after_xe"): Case(A, sim(ErrxFault(after_cmd="XE", code=ERRX_CODE)), raises=AcquisitionError, ops=None),
    ("errx", "during_read"): Case(R, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_cleanup"): Case(X, sim(ErrxFault(after_cmd="CL", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    # MT hangs; the next XE never completes; the hold block's read times out; DZ hangs in the cleanup (retried)
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="MT")), raises=TransportTimeout, ops=None),
    ("timeout", "after_xe"): Case(A, sim(TimeoutFault(on="XE")), raises=TransportTimeout, ops=None),
    ("timeout", "during_read"): Case(R, sim(TimeoutFault(on="read")), raises=TransportTimeout, ops=None),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    # an unparsable element: the hold sample, step 5 / 10 of the first stress read, none (cleanup)
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError, ops=None),
    ("garbage_data", "after_xe"): Case(A, sim(GarbageData(at_step=5)), raises=FlexParseError, ops=None),
    ("garbage_data", "during_read"): Case(R, sim(GarbageData(at_step=10)), raises=FlexParseError, ops=None),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    # the interlock opens (no effect at 2 V: STB bit 3 only)
    ("interlock_open", "configure"): Case(C, sim(InterlockOpen())),
    ("interlock_open", "after_xe"): Case(A, sim(InterlockOpen(at_step=5))),
    ("interlock_open", "during_read"): Case(R, sim(InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(InterlockOpen())),
    # the link drops: before MT, right after the second XE, before the second read, after the first cleanup write
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True,
                                      ops=None),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                     ops=None),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                        ops=None),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # oscillation: the hold sample (stops there), step 5 / 10 of the first stress read, every later step (none left)
    ("oscillation", "configure"): Case(C, sim(Oscillation(steps=[0])), ops=2, stop=True),
    ("oscillation", "after_xe"): Case(A, sim(Oscillation(steps=[5])), ops=3, stop=True),
    ("oscillation", "during_read"): Case(R, sim(Oscillation(steps=[10])), ops=3, stop=True),
    ("oscillation", "during_cleanup"): Case(X, sim(Oscillation())),
    # stuck outputs: verification must fail and latch
    ("ignore_dz", "configure"): Case(C, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "after_xe"): Case(A, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_read"): Case(R, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    # DZ/CL writes time out: once (retry succeeds), twice (retry succeeds), always (latch)
    ("cleanup_failure", "configure"): Case(C, sim(CleanupFailure(count=1))),
    ("cleanup_failure", "after_xe"): Case(A, sim(CleanupFailure(count=2))),
    ("cleanup_failure", "during_read"): Case(R, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    # host side: Ctrl-C before the first hold, after its trigger, in its read, inside cleanup
    ("keyboard_interrupt", "configure"): Case(C, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt, ops=None),
    ("keyboard_interrupt", "after_xe"): Case(A, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt, ops=None),
    ("keyboard_interrupt", "during_read"): Case(R, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt,
                                                ops=None),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm(KeyboardInterrupt), raises=KeyboardInterrupt),
    ("parser_exception", "configure"): Case(C, raise_now(parse_error), raises=FlexParseError, ops=None),
    ("parser_exception", "after_xe"): Case(A, raise_now(parse_error), raises=FlexParseError, ops=None),
    ("parser_exception", "during_read"): Case("setup", bad_parse_data_nth, raises=FlexParseError, ops=None),
    ("parser_exception", "during_cleanup"): Case(X, bad_parse_errx_once),
    # a buggy kind requests 50 V: refused by the guard before any byte is written
    ("envelope_violation", "configure"): Case(C, buggy_50v, raises=EnvelopeViolation, ops=None),
    ("envelope_violation", "after_xe"): Case(A, buggy_50v, raises=EnvelopeViolation, ops=None),
    ("envelope_violation", "during_read"): Case(R, buggy_50v, raises=EnvelopeViolation, ops=None),
    ("envelope_violation", "during_cleanup"): Case(X, arm(violation)),
    # the gate oxide breaks: at the first hold sample (gate compliance: stop), 10 s after the second hold's sample
    # (inside the third hold: stop there), 25 s after it (inside the second recovery hold at 0 V: no current; the
    # last read then sweeps the broken gate into compliance), never (no sampling after the body)
    ("breakdown_at", "configure"): Case(C, sim(BreakdownAt(t_s=0.0)), ops=2, stop=True),
    ("breakdown_at", "after_xe"): Case(A, sim(BreakdownAt(t_s=10.0)), ops=6, stop=True),
    ("breakdown_at", "during_read"): Case(R, sim(BreakdownAt(t_s=25.0)), ops=OPS, stop=True),
    ("breakdown_at", "during_cleanup"): Case(X, sim(BreakdownAt(t_s=0.0))),
}


def test_stress_matrix_is_complete() -> None:
    assert set(STRESS) == {(f, p) for f in FAULTS for p in POSITIONS}


def run_case(h: Harness, case: Case, plan: PlanRecord, monkeypatch: pytest.MonkeyPatch
             ) -> tuple[RawAcquisition | None, BaseException | None]:
    if case.moment == "setup":
        case.inject(h, monkeypatch)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch))
    result: RawAcquisition | None = None
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent="stress-measure safety run") as tx:
            h.tx = tx
            result = KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h, monkeypatch)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return result, raised


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_stress_measure_fault_matrix(fault: str, position: str, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    case = STRESS[(fault, position)]
    h = make_harness(tmp_path, SCENARIO, hook_type=StressHook)
    result, raised = run_case(h, case, PLAN, monkeypatch)
    tx = h.tx
    assert tx is not None

    assert_global_invariant(h, envelope=PLAN.envelope)
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert tx.cleanup.latched_fault == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())
        assert [e.code for e in tx.cleanup.errors] == list(case.errors)
    if case.raises is None or case.raises is CleanupUnverified:
        assert result is not None and case.ops is not None
        kind_result = result.kind_result
        assert len(result.blocks) == case.ops == kind_result["reads_done"] + kind_result["holds_done"]
        assert (kind_result["reads_planned"], kind_result["holds_planned"]) == (6, 5)
        assert kind_result["stopped_early"] is (case.ops < OPS)
        assert bool(kind_result["stop_reason"]) is case.stop
        assert len(h.run.raw) == case.ops
        assert sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log) == case.ops
        table = KIND.to_table(result, PLAN)
        reads = int(kind_result["reads_done"])  # type: ignore[arg-type]
        assert len(table) == reads * READ_STEPS + int(kind_result["holds_done"])  # type: ignore[arg-type]
        if case.stop:
            flagged = table[(table["gate_I_status"] != "N") | (table["drain_I_status"] != "N")]
            assert not flagged.empty and flagged["cycle"].iloc[0] == table["cycle"].iloc[-1]
        else:
            assert (table["gate_I_status"] == "N").all() and (table["drain_I_status"] == "N").all()
    if isinstance(raised, AcquisitionError):
        assert [e.code for e in raised.errors] == [ERRX_CODE]
    if case.latched:
        assert any(e.ev == "fault" for e in h.daily.events)
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())


def test_clean_stress_run_sends_exactly_the_flex_preview(tmp_path: Path) -> None:
    h = make_harness(tmp_path, SCENARIO, hook_type=StressHook)
    with h.transaction(envelope=PLAN.envelope) as tx:
        result = KIND.acquire(tx, PLAN)
    assert_global_invariant(h, envelope=PLAN.envelope)
    writes = [r.command for r in h.log if not r.mnemonic.endswith("?") and r.outcome == "ok"]
    assert writes[:len(PLAN.flex_preview)] == PLAN.flex_preview
    assert writes[len(PLAN.flex_preview):] == ["DZ", "CL"]  # then the transaction's cleanup
    assert result.kind_result["reads_done"] == 6 and result.kind_result["stopped_early"] is False
    dut = h.sim.instrument.circuit.devices["dut"]
    assert dut.bti_dv > 0 and dut.bti_recovering  # stressed for 30 s, then recovering
    assert not h.sim.instrument.circuit.devices["gox"].broken


def test_a_tampered_stress_above_the_envelope_never_reaches_the_instrument(tmp_path: Path) -> None:
    """The plan program is edited to stress the gate at 2.9 V (envelope 2 V): the guard refuses that ``DV`` after the
    reference read, before the first hold, and the transaction cleans up."""
    program = dict(PLAN.program)
    stress = [dict(o) for o in program["stress"]]  # type: ignore[union-attr]
    stress = [{**o, "level": 2.9} if o["role"] == "gate" else o for o in stress]
    tampered = PLAN.model_copy(update={"program": {**program, "stress": stress}})
    h = make_harness(tmp_path, SCENARIO, hook_type=StressHook)
    with pytest.raises(EnvelopeViolation), h.transaction(envelope=PLAN.envelope) as tx:
        KIND.acquire(tx, tampered)
    assert_global_invariant(h, envelope=PLAN.envelope)
    assert sum(r.mnemonic == "XE" for r in h.log) == 1  # the reference read only
    assert not [r for r in h.log if r.mnemonic == "DV" and r.args[0] == str(GATE) and float(r.args[2]) > 2.0]
    assert h.sim.instrument.circuit.devices["dut"].bti_dv == 0.0


def test_a_route_outside_the_plan_never_reaches_the_instrument(tmp_path: Path) -> None:
    """``apply_routes`` sets ASU paths through the guard: a route that is neither the plan's nor the switch's rest
    state is refused before ``SAP`` (the plan has no routes, so any non-rest path is refused)."""
    h = make_harness(tmp_path, SCENARIO, hook_type=StressHook)
    step = RouteStep(route=Route(switch="ASU4", output="OUT", state="cmu"), switch_kind="asu", index=GATE)
    with pytest.raises(EnvelopeViolation), h.transaction(envelope=PLAN.envelope) as tx:
        apply_routes(tx, [step])
    assert_global_invariant(h, envelope=PLAN.envelope)
    assert not [r for r in h.log if r.mnemonic == "SAP"]
    with pytest.raises(ValueError, match="no driver path"), h.transaction(envelope=PLAN.envelope) as tx:
        apply_routes(tx, [RouteStep(route=Route(switch="SEL1", output="OUT1", state="pgu"),
                                    switch_kind="selector_16440a", index=0)])
    assert not [r for r in h.log if r.mnemonic in ("SAP", "ERMOD", "ERSSP")]
