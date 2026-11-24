"""Pulsed-measurement rows of the fault matrix with the global invariant (blueprint v2 2.6, 8.1 ``safety/``, WP7.3).

The body is the real ``smu_pulsed`` kind (``SmuPulsedKind.acquire``) running the committed ``mosfet.idvd_pulsed``
recipe (MM 5: drain staircase, gate pulsed per step), compiled by the real planner, inside ONE transaction on the
noiseless ``nmos_basic`` simulator, with a host list of four gate pulse levels (one ``XE`` each; ``PV`` re-programmed
in between, ``pulsed_update``). Every fault of the staircase matrix is injected at every position: ``configure`` =
right before the ``MM`` write, ``after_xe`` = right after the second ``XE``, ``during_read`` = at the start of the
second data read, ``during_cleanup`` = after the body. Instrument-side faults injected mid-loop act on the next trigger
(the simulator evaluates a whole trigger at its ``XE``).

Every case asserts the global invariant v2 (the pulse sources too: base and pulse levels and the compliance of every
``PV``/``PWV``/``MCP*`` against the channel envelope), the expected exception and fault-latch outcome, the triggers
read and the stop-on-flag behaviour of the host loop. Separate tests check that the pulse timing written (``PT``) lies
inside the compiled pulse envelope, and that tampered programs (a 3.5 V gate pulse, a 400 us pulse, a period giving
duty 0.5) are refused by the guard before any byte is written.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import PulsedProgram, SmuPulsedKind
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops import core as driver_module  # parse_data/parse_errx are looked up here
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.policy import TerminalPulse
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
from tests.unit.rules_factory import T0, bundle, dut, engine, pin_map_exact

pytestmark = pytest.mark.smu

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = SmuPulsedKind()
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "parser_exception", "envelope_violation")
ERRX_CODE = 305
DRAIN, GATE = 3, 4  # the nmos_basic wiring: gate SMU4, drain SMU3, source on the GNDU
LEVELS = [0.5, 1.0, 1.5, 2.0]
NTH = 2
"""The ``after_xe``/``during_read`` moments fire at the second XE / data read (mid-loop)."""

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
PULSE_MAP = pin_map_exact("pulsed-3t", {"gate": GATE, "drain": DRAIN, "source": "GNDU"})
_BASE_DUT = dut("pulsed-3t")
PULSE_DUT = _BASE_DUT.model_copy(update={"terminals": {
    **_BASE_DUT.terminals,
    "gate": _BASE_DUT.terminals["gate"].model_copy(update={"pulse": TerminalPulse(
        max_abs_v=3.0, max_width_s=2.0, max_duty=0.5, max_count=100000)}),
}})


def pulsed_plan(**params: object) -> PlanRecord:
    cfg = bundle(pin_maps=[PULSE_MAP], duts=[PULSE_DUT])
    req = PlanRequest.model_validate({"recipe_id": "mosfet.idvd_pulsed", "pin_map": "pulsed-3t",
                                      "dut_profile": "pulsed-3t",
                                      "params": {"vg_levels": LEVELS, "vd_stop": 1.0, "vd_points": 5, **params}})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "ok", plan.summary
    return plan


PLAN = pulsed_plan()
TRIGGERS = len(LEVELS)


class PulsedHook(HookTransport):
    """``configure`` fires right before the ``MM`` write, ``after_xe`` after the NTH ``XE``, ``during_read`` at the
    NTH data read; ``raise_next`` as in ``HookTransport``."""

    def __init__(self, inner: SimTransport) -> None:
        super().__init__(inner)
        self.xe = 0
        self.reads = 0

    def write(self, cmd: str) -> None:
        self._armed()
        if cmd.startswith("MM "):
            self.fire("configure")
        self.inner.write(cmd)
        if cmd == "XE":
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
    """As in the spot matrix: ``blocks`` = triggers read when the body completes (``None`` when it raises)."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    blocks: int | None = TRIGGERS
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


def tampered_setup(**pulse_changes: object) -> object:
    program = PulsedProgram.load(PLAN.program)
    pulse = program.setup.pulses[0].model_copy(update=pulse_changes)
    return program.setup.model_copy(update={"pulses": (pulse,)})


def buggy_pulse(h: Harness, _mp: pytest.MonkeyPatch) -> None:
    """A deliberately buggy kind re-programs a 3.5 V gate pulse (envelope 2 V): refused before writing."""
    assert h.tx is not None
    h.tx.driver.pulsed_update(tampered_setup(peak=3.5))  # type: ignore[arg-type]


def violation() -> BaseException:
    try:
        OutputGuard(PLAN.envelope).check(GATE, "V", 3.5, 1e-4)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("the guard accepted 3.5 V")


def parse_error() -> BaseException:
    return FlexParseError("injected parser failure", raw="NAI+?")


def bad_parse_data_nth(_h: Harness, mp: pytest.MonkeyPatch) -> None:
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

PULSED: dict[tuple[str, str], Case] = {
    # compliance at staircase step 0 of the first trigger (WM abort, the loop stops), of the third trigger (injected
    # mid-loop: the second was evaluated at its XE), on the unmeasured gate (T on the drain), none (cleanup)
    ("compliance_at", "configure"): Case(C, sim(ComplianceAt(step=0, ch=DRAIN)), blocks=1),
    ("compliance_at", "after_xe"): Case(A, sim(ComplianceAt(step=0, ch=DRAIN)), blocks=3),
    ("compliance_at", "during_read"): Case(R, sim(ComplianceAt(step=0, ch=GATE)), blocks=3),
    ("compliance_at", "during_cleanup"): Case(X, sim(ComplianceAt(step=0, ch=DRAIN))),
    # an error after MM (the setup drain aborts before any XE), after the third XE (drained before the fourth
    # trigger), after DZ / CL in the cleanup (drained into the cleanup report)
    ("errx", "configure"): Case(C, sim(ErrxFault(after_cmd="MM", code=ERRX_CODE)), raises=AcquisitionError,
                                blocks=None),
    ("errx", "after_xe"): Case(A, sim(ErrxFault(after_cmd="XE", code=ERRX_CODE)), raises=AcquisitionError,
                               blocks=None),
    ("errx", "during_read"): Case(R, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_cleanup"): Case(X, sim(ErrxFault(after_cmd="CL", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="MM")), raises=TransportTimeout, blocks=None),
    ("timeout", "after_xe"): Case(A, sim(TimeoutFault(on="XE")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_read"): Case(R, sim(TimeoutFault(on="read")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "after_xe"): Case(A, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_read"): Case(R, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    ("interlock_open", "configure"): Case(C, sim(InterlockOpen())),
    ("interlock_open", "after_xe"): Case(A, sim(InterlockOpen(at_step=0))),
    ("interlock_open", "during_read"): Case(R, sim(InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(InterlockOpen())),
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True,
                                      blocks=None),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                     blocks=None),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                        blocks=None),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    ("oscillation", "configure"): Case(C, sim(Oscillation(steps=[0])), blocks=1),
    ("oscillation", "after_xe"): Case(A, sim(Oscillation(steps=[0])), blocks=3),
    ("oscillation", "during_read"): Case(R, sim(Oscillation(steps=[0])), blocks=3),
    ("oscillation", "during_cleanup"): Case(X, sim(Oscillation())),
    ("ignore_dz", "configure"): Case(C, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "after_xe"): Case(A, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_read"): Case(R, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "configure"): Case(C, sim(CleanupFailure(count=1))),
    ("cleanup_failure", "after_xe"): Case(A, sim(CleanupFailure(count=2))),
    ("cleanup_failure", "during_read"): Case(R, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
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
    ("envelope_violation", "configure"): Case(C, buggy_pulse, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "after_xe"): Case(A, buggy_pulse, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "during_read"): Case(R, buggy_pulse, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "during_cleanup"): Case(X, arm(violation)),
}


def test_pulsed_matrix_is_complete() -> None:
    assert set(PULSED) == {(f, p) for f in FAULTS for p in POSITIONS}


def test_the_plan_pulses_the_gate_once_per_staircase_step() -> None:
    assert [line.split()[0] for line in PLAN.flex_preview if line.split()[0] in ("PT", "WV", "PV", "XE")] == [
        "PT", "WV", "PV", "XE", "PV", "XE", "PV", "XE", "PV", "XE"]
    pulse = PLAN.envelope.channels[GATE].pulse
    assert pulse is not None and pulse.max_abs_v_dut == 2.0 and pulse.max_count == 5
    assert (pulse.min_width_s, pulse.max_width_s, pulse.max_duty) == (1e-3, 1e-3, 0.05)


def run_case(h: Harness, case: Case, plan: PlanRecord, monkeypatch: pytest.MonkeyPatch
             ) -> tuple[RawAcquisition | None, BaseException | None]:
    if case.moment == "setup":
        case.inject(h, monkeypatch)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch))
    result: RawAcquisition | None = None
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent="pulsed safety run") as tx:
            h.tx = tx
            result = KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h, monkeypatch)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return result, raised


def assert_timing_within_the_pulse_envelope(h: Harness) -> None:
    """Every PT that reached the instrument lies inside the gate's compiled pulse envelope (width, duty)."""
    pulse = PLAN.envelope.channels[GATE].pulse
    assert pulse is not None
    for record in h.log:
        if record.mnemonic == "PT":
            width, period = float(record.args[1]), float(record.args[2])
            assert pulse.min_width_s <= width <= pulse.max_width_s and width / period <= pulse.max_duty


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_pulsed_fault_matrix(fault: str, position: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = PULSED[(fault, position)]
    h = make_harness(tmp_path, hook_type=PulsedHook)
    result, raised = run_case(h, case, PLAN, monkeypatch)
    tx = h.tx
    assert tx is not None

    assert_global_invariant(h, envelope=PLAN.envelope)
    assert_timing_within_the_pulse_envelope(h)
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert tx.cleanup.latched_fault == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())
        assert [e.code for e in tx.cleanup.errors] == list(case.errors)
        assert all(state.mode == "V" and state.voltage == 0.0 for state in h.sim.instrument.outputs().values())
    if case.raises is None or case.raises is CleanupUnverified:
        assert result is not None and case.blocks is not None
        assert len(result.blocks) == case.blocks == result.kind_result["triggers_done"]
        assert result.kind_result["triggers_planned"] == TRIGGERS
        assert result.kind_result["stopped_early"] is (case.blocks < TRIGGERS)
        assert len(h.run.raw) == case.blocks
        assert sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log) == case.blocks
        if case.blocks < TRIGGERS:
            assert "were not run" in str(result.kind_result["stop_reason"])
            assert len(KIND.to_table(result, PLAN)) == case.blocks * 5
    if isinstance(raised, AcquisitionError):
        assert [e.code for e in raised.errors] == [ERRX_CODE]
        triggered = sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log)
        assert triggered == (0 if position == "configure" else 3)
    if case.latched:
        assert any(e.ev == "fault" for e in h.daily.events)
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())


@pytest.mark.parametrize(("changes", "reason"), [
    ({"peak": 3.5}, "level_exceeds_envelope"),
    ({"width": 4e-4}, "pulse_width_outside_envelope"),
    ({"comp": 1e-3}, "compliance_exceeds_envelope"),
])
def test_tampered_pulse_programs_never_reach_the_instrument(changes: dict[str, object], reason: str,
                                                            tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=PulsedHook)
    with pytest.raises(EnvelopeViolation) as info, h.transaction(envelope=PLAN.envelope, intent="tamper") as tx:
        h.tx = tx
        tx.driver.pulsed_setup(tampered_setup(**changes))  # type: ignore[arg-type]
    assert info.value.reason == reason
    assert not any(r.mnemonic in ("PV", "PT", "MM") for r in h.log)
    assert_global_invariant(h, envelope=PLAN.envelope)


def test_a_duty_above_the_envelope_is_refused(tmp_path: Path) -> None:
    program = PulsedProgram.load(PLAN.program)
    h = make_harness(tmp_path, hook_type=PulsedHook)
    with pytest.raises(EnvelopeViolation) as info, h.transaction(envelope=PLAN.envelope, intent="tamper") as tx:
        tx.driver.pulsed_setup(program.setup.model_copy(update={"period": 0.005}))
    assert info.value.reason == "duty_exceeds_envelope" and not any(r.mnemonic == "PT" for r in h.log)
