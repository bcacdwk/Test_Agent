"""Stepped-sweep rows of the fault matrix with the global invariant (blueprint 3, 8.1 ``safety/``).

The body is the real ``smu_stepped`` kind (``SmuSteppedKind.acquire``) running the committed ``mosfet.idvd``
recipe, compiled by the real planner (drain 0..1 V in 11 points for each of the gate steps 0.5, 0.7, 0.9, 1.1 V),
inside ONE transaction on the noiseless ``nmos_basic`` simulator. Every fault of the staircase matrix is injected at
every position; for the loop the positions are: ``configure`` = right before the sweep setup (``WV``) is written,
``after_xe`` = right after the second ``XE`` (mid-loop), ``during_read`` = at the start of the second data read,
``during_cleanup`` = after the body. Instrument-side faults injected mid-loop act on the following sweep.

Every case asserts the global invariant against the plan's own envelope, the expected exception and fault-latch
outcome, how many sweeps were read, and the abort-on-compliance behaviour of the host loop (a flagged sweep stops
the loop; ``kind_result`` says so). Separate tests drive a tampered program that asks for 50 V and check that it
never reaches the simulator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import SmuSteppedKind
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops import core as driver_module  # parse_data/parse_errx are looked up here
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
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
from b1500_test_agent.session import CleanupUnverified
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.safety.helpers import Harness, HookTransport, assert_global_invariant, make_harness
from tests.unit.rules_factory import T0, bundle, dut, engine, pin_map

pytestmark = pytest.mark.smu

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = SmuSteppedKind()
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "parser_exception", "envelope_violation")
ERRX_CODE = 305
GATE, DRAIN = 5, 3  # SMU5 (MPSMU) and SMU3 (HRSMU) of the lab-shaped example station
NTH = 2
"""The ``after_xe``/``during_read`` moments fire at the second XE / data read (mid-loop)."""


def stepped_plan() -> PlanRecord:
    registry = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
    cfg = bundle(pin_maps=[pin_map()], duts=[dut()])
    req = PlanRequest.model_validate({
        "recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic",
        "params": {"vd_stop": 1.0, "vd_points": 11, "vg_start": 0.5, "vg_stop": 1.1, "vg_points": 4}})
    plan = Planner(registry, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "ok" and plan.program["step_values"] == [0.5, 0.7, 0.9, 1.1]
    return plan


PLAN = stepped_plan()
STEPS = len(PLAN.program["step_values"])  # type: ignore[arg-type]


class SteppedHook(HookTransport):
    """``configure`` fires right before the ``WV`` write, ``after_xe`` after the NTH ``XE``, ``during_read`` at the
    NTH data read; ``raise_next`` as in ``HookTransport``."""

    def __init__(self, inner: SimTransport) -> None:
        super().__init__(inner)
        self.xe = 0
        self.reads = 0

    def write(self, cmd: str) -> None:
        self._armed()
        if cmd.startswith("WV "):
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
    """``moment``: hook moment, ``cleanup`` (end of the body) or ``setup`` (before the transaction); ``raises``:
    exact exception type leaving the ``with`` block; ``latched``: fault latch set; ``blocks``: sweeps read when the
    body completes (``None`` when it raises); ``errors``: error codes drained by the cleanup."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    blocks: int | None = STEPS
    errors: tuple[int, ...] = ()


def sim(fault: SimFault) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    return lambda h, _mp: h.sim.inject(fault)


def raise_now(make: Callable[[], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    def action(_h: Harness, _mp: pytest.MonkeyPatch) -> None:
        raise make()

    return action


def arm(make: Callable[[], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    """Raise once on the next transport call (the first cleanup step)."""

    def action(h: Harness, _mp: pytest.MonkeyPatch) -> None:
        h.hook.raise_next = make()

    return action


def buggy_50v(h: Harness, _mp: pytest.MonkeyPatch) -> None:
    """A deliberately buggy kind asks for 50 V on the gate (envelope 1.1 V): the guard refuses before writing."""
    assert h.tx is not None
    h.tx.driver.force_v(GATE, 50.0, icomp=1e-6)


def violation() -> BaseException:
    try:
        OutputGuard(PLAN.envelope).check(GATE, "V", 50.0, 1e-6)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("the guard accepted 50 V")


def parse_error() -> BaseException:
    return FlexParseError("injected parser failure", raw="NAI+?")


def bad_parse_data_nth(_h: Harness, mp: pytest.MonkeyPatch) -> None:
    """The NTH measurement block fails to parse."""
    original = driver_module.parse_data
    calls = {"n": 0}

    def flaky(raw: str, fmt: int) -> object:
        calls["n"] += 1
        if calls["n"] == NTH:
            raise FlexParseError("injected parser failure on measurement data", raw=raw)
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

STEPPED: dict[tuple[str, str], Case] = {
    # compliance in the first sweep (loop stops after it), in the third sweep (injected mid-loop), none (cleanup)
    ("compliance_at", "configure"): Case(C, sim(ComplianceAt(step=0, ch=DRAIN)), blocks=1),
    ("compliance_at", "after_xe"): Case(A, sim(ComplianceAt(step=5, ch=DRAIN)), blocks=3),
    ("compliance_at", "during_read"): Case(R, sim(ComplianceAt(step=10, ch=GATE)), blocks=3),
    ("compliance_at", "during_cleanup"): Case(X, sim(ComplianceAt(step=0, ch=DRAIN))),
    # an error after WV (setup drain aborts before any XE), after the third XE (drained before the fourth step),
    # after DZ / CL in the cleanup (drained into the cleanup report)
    ("errx", "configure"): Case(C, sim(ErrxFault(after_cmd="WV", code=ERRX_CODE)), raises=AcquisitionError,
                                blocks=None),
    ("errx", "after_xe"): Case(A, sim(ErrxFault(after_cmd="XE", code=ERRX_CODE)), raises=AcquisitionError,
                               blocks=None),
    ("errx", "during_read"): Case(R, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_cleanup"): Case(X, sim(ErrxFault(after_cmd="CL", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    # WV hangs; the third XE never completes; the second data read times out; DZ hangs in the cleanup
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="WV")), raises=TransportTimeout, blocks=None),
    ("timeout", "after_xe"): Case(A, sim(TimeoutFault(on="XE")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_read"): Case(R, sim(TimeoutFault(on="read")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    # unparsable element in the first sweep, in the third sweep (two mid-loop injections), none (cleanup)
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "after_xe"): Case(A, sim(GarbageData(at_step=5)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_read"): Case(R, sim(GarbageData(at_step=10)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    # the interlock opens (no effect below 42 V; STB bit 3 stays clear: an event, PG p76 (1-56))
    ("interlock_open", "configure"): Case(C, sim(InterlockOpen())),
    ("interlock_open", "after_xe"): Case(A, sim(InterlockOpen(at_step=5))),
    ("interlock_open", "during_read"): Case(R, sim(InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(InterlockOpen())),
    # the link drops: before WV, right after the second XE, before the second read, after the first cleanup write
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True,
                                      blocks=None),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                     blocks=None),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                        blocks=None),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # oscillation in the first sweep (loop stops), in the third sweep, every step after the body
    ("oscillation", "configure"): Case(C, sim(Oscillation(steps=[0])), blocks=1),
    ("oscillation", "after_xe"): Case(A, sim(Oscillation(steps=[5])), blocks=3),
    ("oscillation", "during_read"): Case(R, sim(Oscillation(steps=[10])), blocks=3),
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
    # host side: Ctrl-C before the setup, between the second XE and its read, in the second read, inside cleanup
    ("keyboard_interrupt", "configure"): Case(C, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt,
                                              blocks=None),
    ("keyboard_interrupt", "after_xe"): Case(A, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt,
                                             blocks=None),
    ("keyboard_interrupt", "during_read"): Case(R, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt,
                                                blocks=None),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm(KeyboardInterrupt), raises=KeyboardInterrupt),
    ("parser_exception", "configure"): Case(C, raise_now(parse_error), raises=FlexParseError, blocks=None),
    ("parser_exception", "after_xe"): Case(A, raise_now(parse_error), raises=FlexParseError, blocks=None),
    ("parser_exception", "during_read"): Case("setup", bad_parse_data_nth, raises=FlexParseError, blocks=None),
    ("parser_exception", "during_cleanup"): Case(X, bad_parse_errx_once),
    # a buggy kind requests 50 V: refused by the guard before any byte is written
    ("envelope_violation", "configure"): Case(C, buggy_50v, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "after_xe"): Case(A, buggy_50v, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "during_read"): Case(R, buggy_50v, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "during_cleanup"): Case(X, arm(violation)),
}


def test_stepped_matrix_is_complete() -> None:
    assert set(STEPPED) == {(f, p) for f in FAULTS for p in POSITIONS}


def run_case(h: Harness, case: Case, plan: PlanRecord, monkeypatch: pytest.MonkeyPatch
             ) -> tuple[RawAcquisition | None, BaseException | None]:
    if case.moment == "setup":
        case.inject(h, monkeypatch)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch))
    result: RawAcquisition | None = None
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent="stepped safety run") as tx:
            h.tx = tx
            result = KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h, monkeypatch)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return result, raised


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_stepped_fault_matrix(fault: str, position: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = STEPPED[(fault, position)]
    h = make_harness(tmp_path, hook_type=SteppedHook)
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
        assert result is not None and case.blocks is not None
        assert len(result.blocks) == case.blocks == result.kind_result["steps_done"]
        assert result.kind_result["steps_planned"] == STEPS
        assert result.kind_result["stopped_early"] is (case.blocks < STEPS)
        assert len(h.run.raw) == case.blocks
        assert sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log) == case.blocks
        if case.blocks < STEPS:  # abort on compliance/oscillation: the flagged sweep is the last one
            assert "were not run" in str(result.kind_result["stop_reason"])
            table = KIND.to_table(result, PLAN)
            assert len(table) == case.blocks * 11
    if isinstance(raised, AcquisitionError):
        assert [e.code for e in raised.errors] == [ERRX_CODE]
        triggered = sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log)
        assert triggered == (0 if position == "configure" else 3)  # nothing triggered after the error
    if case.latched:
        assert any(e.ev == "fault" for e in h.daily.events)
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())


def test_clean_stepped_run_sends_exactly_the_flex_preview(tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=SteppedHook)
    with h.transaction(envelope=PLAN.envelope) as tx:
        result = KIND.acquire(tx, PLAN)
    assert_global_invariant(h, envelope=PLAN.envelope)
    writes = [r.command for r in h.log if not r.mnemonic.endswith("?") and r.outcome == "ok"]
    assert writes[:len(PLAN.flex_preview)] == PLAN.flex_preview
    assert writes[len(PLAN.flex_preview):] == ["DZ", "CL"]  # then the transaction's cleanup
    assert result.kind_result == {"steps_planned": 4, "steps_done": 4, "stopped_early": False, "stop_reason": ""}
    table = KIND.to_table(result, PLAN)
    assert table["gate_V"].unique().tolist() == [0.5, 0.7, 0.9, 1.1] and table["step"].tolist() == list(range(44))
    marks = [e.data["label"] for e in h.events() if e.ev == "checkpoint" and e.data]
    assert [m for m in marks if str(m).startswith("step ")] == [f"step {i}: gate = {v:g} V" for i, v in
                                                                enumerate([0.5, 0.7, 0.9, 1.1])]


def tampered(**program: object) -> PlanRecord:
    """``PLAN`` with parts of its stored program replaced (envelope unchanged): a buggy or tampered kind program."""
    data = dict(PLAN.program)
    data.update(program)
    return PLAN.model_copy(update={"program": data})


def test_tampered_step_value_of_50_v_never_reaches_the_simulator(tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=SteppedHook)
    plan = tampered(step_values=[0.5, 50.0, 0.9])
    with pytest.raises(EnvelopeViolation) as caught, h.transaction(envelope=plan.envelope) as tx:
        KIND.acquire(tx, plan)
    assert caught.value.reason == "level_exceeds_envelope" and caught.value.limit == 1.1
    assert_global_invariant(h, envelope=plan.envelope)
    assert [r.command for r in h.log if r.mnemonic == "DV" and r.args[0] == str(GATE)] == [f"DV {GATE},0,0.5,1E-06"]
    assert sum(r.mnemonic == "XE" for r in h.log) == 1  # the first sweep ran; nothing after the refusal
    assert not any(e.ev == "write" and e.cmd and "50" in e.cmd for e in h.events())
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"


def test_tampered_sweep_of_50_v_is_refused_before_the_setup(tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=SteppedHook)
    staircase = dict(PLAN.program["staircase"])  # type: ignore[arg-type]
    staircase["sweep"] = {**staircase["sweep"], "stop": 50.0}  # type: ignore[dict-item]
    plan = tampered(staircase=staircase)
    with pytest.raises(EnvelopeViolation), h.transaction(envelope=plan.envelope) as tx:
        KIND.acquire(tx, plan)
    assert_global_invariant(h, envelope=plan.envelope)
    assert not any(r.mnemonic in {"MM", "WV", "WT", "WM", "XE"} for r in h.log)
    assert not any(r.source and "50" in r.command for r in h.log)
