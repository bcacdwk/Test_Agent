"""Sampling rows of the fault matrix with the global invariant v2 (WP7.4; blueprint v2 2.6, 4.3, 8.1 ``safety/``;
per-recipe AC ``tests/safety -k smu_sampling``).

The body is the real ``smu_sampling`` kind (``SmuSamplingKind.acquire``) running the committed
``reliability.tddb_cvs`` recipe compiled by the real planner (gate stress 0 -> 4.5 V, 101 samples at 1 s: a chain of
five ``MM 10`` blocks of 25, 25, 25, 25 and 1 samples, continuation blocks holding the stress), inside ONE
transaction on the noiseless ``dielectric_tddb`` simulator (gate SMU4; no natural breakdown at 4.5 V). Every fault
of the stepped matrix plus ``breakdown_at`` is injected at every position: ``configure`` = right before the first
``MT`` (the sampling setup), ``after_xe`` = right after the second ``XE`` (between blocks; the simulator evaluates a
block at its trigger, so instrument faults act on the third block), ``during_read`` = at the second data read,
``during_cleanup`` = after the body.

Every case asserts the global invariant against the plan's own envelope (``MV`` levels and Icomp included), the
expected exception and fault-latch outcome, how many blocks were read, and the automatic abort (MSC 2): a block with
a compliance, overflow or oscillation sample ends the chain and ``kind_result`` says so. Separate tests drive a
tampered program (a stress above the envelope) and a clean run (exactly the FLEX preview on the wire).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import SamplingProgram, SmuSamplingKind
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

pytestmark = pytest.mark.smu

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = SmuSamplingKind()
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "parser_exception", "envelope_violation",
          "breakdown_at")
ERRX_CODE = 305
GATE = 4  # the dielectric_tddb wiring: gate electrode on SMU4 (HRSMU), substrate on the GNDU
NTH = 2
SCENARIO = noiseless(load_scenario("dielectric_tddb"))


def sampling_plan() -> PlanRecord:
    registry = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
    cfg = bundle(pin_maps=[pin_map(gate=GATE, drain=None)],
                 duts=[dut("dielectric-generic", "dielectric", gate=(6.0, 1e-2), bulk=(1.0, 1e-2))])
    req = PlanRequest.model_validate({
        "recipe_id": "reliability.tddb_cvs", "pin_map": "mosfet-4t", "dut_profile": "dielectric-generic",
        "params": {"v_stress": 4.5, "duration": 100.0, "interval": 1.0}})
    plan = Planner(registry, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "needs_confirmation" and set(plan.rules.confirm_reasons) == {"destructive"}
    assert [b["number"] for b in plan.program["blocks"]] == [25, 25, 25, 25, 1]  # type: ignore[index]
    return plan


PLAN = sampling_plan()
BLOCKS = 5


class SamplingHook(HookTransport):
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
    the ``with`` block; ``latched``: fault latch set; ``blocks``: blocks read when the body completes (``None`` when it
    raises); ``errors``: error codes drained by the cleanup."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    blocks: int | None = BLOCKS
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
    """A deliberately buggy kind asks for 50 V on the stressed gate (envelope 4.5 V): refused before writing."""
    assert h.tx is not None
    h.tx.driver.force_v(GATE, 50.0, icomp=1e-3)


def violation() -> BaseException:
    try:
        OutputGuard(PLAN.envelope).check(GATE, "V", 50.0, 1e-3)
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
            raise FlexParseError("injected parser failure on sampling data", raw=raw)
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

SAMPLING: dict[tuple[str, str], Case] = {
    # compliance at the first sample of every block (the first block aborts), at sample 5 / 10 of the third block
    ("compliance_at", "configure"): Case(C, sim(ComplianceAt(step=0, ch=GATE)), blocks=1),
    ("compliance_at", "after_xe"): Case(A, sim(ComplianceAt(step=5, ch=GATE)), blocks=3),
    ("compliance_at", "during_read"): Case(R, sim(ComplianceAt(step=10, ch=GATE)), blocks=3),
    ("compliance_at", "during_cleanup"): Case(X, sim(ComplianceAt(step=0, ch=GATE))),
    # an error after MT (setup drain aborts before any XE), after the third XE... caught before the fourth block,
    # after DZ / CL in the cleanup (drained into the cleanup report)
    ("errx", "configure"): Case(C, sim(ErrxFault(after_cmd="MT", code=ERRX_CODE)), raises=AcquisitionError,
                                blocks=None),
    ("errx", "after_xe"): Case(A, sim(ErrxFault(after_cmd="XE", code=ERRX_CODE)), raises=AcquisitionError,
                               blocks=None),
    ("errx", "during_read"): Case(R, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_cleanup"): Case(X, sim(ErrxFault(after_cmd="CL", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    # MT hangs; the third XE never completes; the second data read times out; DZ hangs in the cleanup
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="MT")), raises=TransportTimeout, blocks=None),
    ("timeout", "after_xe"): Case(A, sim(TimeoutFault(on="XE")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_read"): Case(R, sim(TimeoutFault(on="read")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    # unparsable element in the first block, in the third block, none (cleanup)
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "after_xe"): Case(A, sim(GarbageData(at_step=5)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_read"): Case(R, sim(GarbageData(at_step=10)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    # the interlock opens (no effect below 42 V, STB bit 3 only)
    ("interlock_open", "configure"): Case(C, sim(InterlockOpen())),
    ("interlock_open", "after_xe"): Case(A, sim(InterlockOpen(at_step=5))),
    ("interlock_open", "during_read"): Case(R, sim(InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(InterlockOpen())),
    # the link drops: before MT, right after the second XE, before the second read, after the first cleanup write
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True,
                                      blocks=None),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                     blocks=None),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                        blocks=None),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # oscillation in the first block (aborts), in the third block, at every later sample (none left)
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
    # host side: Ctrl-C before the sampling setup, between blocks, in the second read, inside cleanup
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
    # the dielectric breaks: at the first sample, 10 s into the third block, 30 s after the third block's start
    # (inside the fourth), never (no sampling after the body); the automatic abort ends the chain
    ("breakdown_at", "configure"): Case(C, sim(BreakdownAt(t_s=0.0)), blocks=1),
    ("breakdown_at", "after_xe"): Case(A, sim(BreakdownAt(t_s=10.0)), blocks=3),
    ("breakdown_at", "during_read"): Case(R, sim(BreakdownAt(t_s=30.0)), blocks=4),
    ("breakdown_at", "during_cleanup"): Case(X, sim(BreakdownAt(t_s=0.0))),
}


def test_sampling_matrix_is_complete() -> None:
    assert set(SAMPLING) == {(f, p) for f in FAULTS for p in POSITIONS}


def run_case(h: Harness, case: Case, plan: PlanRecord, monkeypatch: pytest.MonkeyPatch
             ) -> tuple[RawAcquisition | None, BaseException | None]:
    if case.moment == "setup":
        case.inject(h, monkeypatch)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch))
    result: RawAcquisition | None = None
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent="sampling safety run") as tx:
            h.tx = tx
            result = KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h, monkeypatch)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return result, raised


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_smu_sampling_fault_matrix(fault: str, position: str, tmp_path: Path,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    case = SAMPLING[(fault, position)]
    h = make_harness(tmp_path, SCENARIO, hook_type=SamplingHook)
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
        kind_result = result.kind_result
        assert len(result.blocks) == case.blocks == kind_result["blocks_done"]
        assert kind_result["blocks_planned"] == BLOCKS
        assert kind_result["stopped_early"] is (case.blocks < BLOCKS) is kind_result["aborted"]
        assert len(h.run.raw) == case.blocks
        assert sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log) == case.blocks
        table = KIND.to_table(result, PLAN)
        if case.blocks < BLOCKS:  # automatic abort: the flagged block is the last one; its dummy samples dropped
            assert "automatic abort" in str(kind_result["abort_reason"])
            last = table.iloc[-1]
            assert last["gate_I_status"] in ("C", "X") and kind_result["abort_t_s"] == last["t_s"]
            assert len(table) + int(kind_result["samples_after_abort"]) == 25 * case.blocks
        else:
            assert len(table) == 101 and (table["gate_I_status"] == "N").all()
    if isinstance(raised, AcquisitionError):
        assert [e.code for e in raised.errors] == [ERRX_CODE]
        triggered = sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log)
        assert triggered == (0 if position == "configure" else 3)  # nothing triggered after the error
    if case.latched:
        assert any(e.ev == "fault" for e in h.daily.events)
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())


def test_clean_sampling_run_sends_exactly_the_flex_preview(tmp_path: Path) -> None:
    h = make_harness(tmp_path, SCENARIO, hook_type=SamplingHook)
    with h.transaction(envelope=PLAN.envelope) as tx:
        result = KIND.acquire(tx, PLAN)
    assert_global_invariant(h, envelope=PLAN.envelope)
    writes = [r.command for r in h.log if not r.mnemonic.endswith("?") and r.outcome == "ok"]
    assert writes[:len(PLAN.flex_preview)] == PLAN.flex_preview
    assert writes[len(PLAN.flex_preview):] == ["DZ", "CL"]  # then the transaction's cleanup
    assert result.kind_result["blocks_done"] == BLOCKS and result.kind_result["aborted"] is False
    assert h.sim.instrument.circuit.devices["dut"].damage > 0  # stressed, not broken


def test_a_tampered_stress_above_the_envelope_never_reaches_the_instrument(tmp_path: Path) -> None:
    """The plan program is edited to stress at 5.9 V (envelope 4.5 V): the guard refuses the MV before any byte."""
    program = dict(PLAN.program)
    sources = [dict(s) for s in program["synchronous"]]  # type: ignore[union-attr]
    sources[0] = {**sources[0], "source": {**sources[0]["source"], "bias": 5.9}}
    tampered = PLAN.model_copy(update={"program": {**program, "synchronous": sources}})
    h = make_harness(tmp_path, SCENARIO, hook_type=SamplingHook)
    with pytest.raises(EnvelopeViolation), h.transaction(envelope=PLAN.envelope) as tx:
        KIND.acquire(tx, tampered)
    assert_global_invariant(h, envelope=PLAN.envelope)
    assert not [r for r in h.log if r.mnemonic in ("MV", "MI", "XE")]
    assert not h.sim.instrument.circuit.devices["dut"].broken


def test_a_tampered_continuation_block_is_checked_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard checks every continuation ``MV`` too: a buggy kind raising the stress between blocks is refused
    there, after one block, and the transaction cleans up."""
    original = SamplingProgram.setup

    def buggy_setup(self: SamplingProgram, block: Any, *, hold: bool) -> Any:
        setup = original(self, block, hold=hold)
        if not hold:
            return setup
        return setup.model_copy(update={"sources": tuple(s.model_copy(update={"base": 5.9, "bias": 5.9})
                                                         for s in setup.sources)})

    monkeypatch.setattr(SamplingProgram, "setup", buggy_setup)
    h = make_harness(tmp_path, SCENARIO, hook_type=SamplingHook)
    with pytest.raises(EnvelopeViolation), h.transaction(envelope=PLAN.envelope) as tx:
        KIND.acquire(tx, PLAN)
    assert_global_invariant(h, envelope=PLAN.envelope)
    assert sum(r.mnemonic == "XE" for r in h.log) == 1
    assert [r.args[3] for r in h.log if r.mnemonic == "MV"] == ["4.5"]  # only the first block's MV was written
