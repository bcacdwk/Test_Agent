"""Spot-measurement rows of the fault matrix with the global invariant (blueprint v2 2.6, 8.1 ``safety/``, WP7.1).

The body is the real ``smu_spot`` kind (``SmuSpotKind.acquire``) running the committed ``generic.smu_spot`` recipe,
compiled by the real planner, inside ONE transaction on the noiseless ``nmos_basic`` simulator: terminal ``a`` (the
drain, SMU3) steps through four voltages (one ``XE`` each, the host list), ``b`` returns through the GNDU and ``d``
(the gate, SMU4) is a ``DI`` voltmeter at 0 A, so both source commands of the kind (``DV`` and ``DI``) are under
test. Every fault of the staircase matrix is injected at every position: ``configure`` = right before the ``MM``
write, ``after_xe`` = right after the second ``XE``, ``during_read`` = at the start of the second data read,
``during_cleanup`` = after the body. Instrument-side faults injected mid-loop act on the following point.

Every case asserts the global invariant v2 (current sources included: ``DI`` levels against the channel's |I|, its
voltage compliance against |V|), the expected exception and fault-latch outcome, the number of points read and the
stop-on-flag behaviour of the host loop. Separate tests drive tampered programs (50 V on ``a``, 50 mA on ``d``) and
the ASU live check (``RI ch,8`` without an ASU aborts before ``XE``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import SmuSpotKind, SmuStaircaseKind
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops import core as driver_module  # parse_data/parse_errx are looked up here
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.routing import SwitchPort, SwitchSpec
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
from tests.unit.rules_factory import T0, bundle, dut, engine, example_station, pin_map_exact

pytestmark = pytest.mark.smu

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = SmuSpotKind()
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "parser_exception", "envelope_violation")
ERRX_CODE = 305
DRAIN, GATE = 3, 4  # the nmos_basic wiring: a = drain (SMU3), d = gate (SMU4), b = source on the GNDU
LEVELS = [0.05, 0.1, 0.15, 0.2]
NTH = 2
"""The ``after_xe``/``during_read`` moments fire at the second XE / data read (mid-loop)."""

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
SPOT_MAP = pin_map_exact("spot-3t", {"a": DRAIN, "b": "GNDU", "d": GATE})
SPOT_DUT = dut("spot-3t", "nmos", a=(3.0, 1e-3), b=(1.0, 1e-3), d=(3.0, 1e-3))


def spot_plan(**params: object) -> PlanRecord:
    cfg = bundle(pin_maps=[SPOT_MAP], duts=[SPOT_DUT])
    req = PlanRequest.model_validate({"recipe_id": "generic.smu_spot", "pin_map": "spot-3t", "dut_profile": "spot-3t",
                                      "params": {"a_levels": LEVELS, "d_vcomp": 2.0, **params}})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "ok", plan.summary
    return plan


PLAN = spot_plan()
POINTS = len(LEVELS)


class SpotHook(HookTransport):
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
    """``moment``: hook moment, ``cleanup`` (end of the body) or ``setup`` (before the transaction); ``raises``:
    exception type leaving the ``with`` block; ``latched``: fault latch set; ``blocks``: points read when the body
    completes (``None`` when it raises); ``errors``: error codes drained by the cleanup."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    blocks: int | None = POINTS
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


def buggy_50ma(h: Harness, _mp: pytest.MonkeyPatch) -> None:
    """A deliberately buggy kind forces 50 mA on the voltmeter (envelope 0 A): the guard refuses before writing."""
    assert h.tx is not None
    h.tx.driver.force_i(GATE, 0.05, vcomp=2.0)


def violation() -> BaseException:
    try:
        OutputGuard(PLAN.envelope).check(GATE, "I", 0.05, 2.0)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("the guard accepted 50 mA")


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

SPOT: dict[tuple[str, str], Case] = {
    # every spot point is measurement step 0: compliance on the first point (the loop stops), on the third point
    # (injected mid-loop), none (cleanup)
    ("compliance_at", "configure"): Case(C, sim(ComplianceAt(step=0, ch=DRAIN)), blocks=1),
    ("compliance_at", "after_xe"): Case(A, sim(ComplianceAt(step=0, ch=DRAIN)), blocks=3),
    ("compliance_at", "during_read"): Case(R, sim(ComplianceAt(step=0, ch=GATE)), blocks=3),
    ("compliance_at", "during_cleanup"): Case(X, sim(ComplianceAt(step=0, ch=DRAIN))),
    # an error after MM (setup drain aborts before any XE), after the third XE (drained before the fourth level),
    # after DZ / CL in the cleanup (drained into the cleanup report)
    ("errx", "configure"): Case(C, sim(ErrxFault(after_cmd="MM", code=ERRX_CODE)), raises=AcquisitionError,
                                blocks=None),
    ("errx", "after_xe"): Case(A, sim(ErrxFault(after_cmd="XE", code=ERRX_CODE)), raises=AcquisitionError,
                               blocks=None),
    ("errx", "during_read"): Case(R, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_cleanup"): Case(X, sim(ErrxFault(after_cmd="CL", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    # MM hangs; the third XE never completes; the second data read times out; DZ hangs in the cleanup
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="MM")), raises=TransportTimeout, blocks=None),
    ("timeout", "after_xe"): Case(A, sim(TimeoutFault(on="XE")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_read"): Case(R, sim(TimeoutFault(on="read")), raises=TransportTimeout, blocks=None),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    # unparsable element in the first point, in the third point, none (cleanup)
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "after_xe"): Case(A, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_read"): Case(R, sim(GarbageData(at_step=0)), raises=FlexParseError, blocks=None),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    # the interlock opens (no effect below 42 V, STB bit 3 only)
    ("interlock_open", "configure"): Case(C, sim(InterlockOpen())),
    ("interlock_open", "after_xe"): Case(A, sim(InterlockOpen(at_step=0))),
    ("interlock_open", "during_read"): Case(R, sim(InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(InterlockOpen())),
    # the link drops: before MM, right after the second XE, before the second read, after the first cleanup write
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True,
                                      blocks=None),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                     blocks=None),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                        blocks=None),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # oscillation on the first point (loop stops), on the third point, on every point after the body
    ("oscillation", "configure"): Case(C, sim(Oscillation(steps=[0])), blocks=1),
    ("oscillation", "after_xe"): Case(A, sim(Oscillation(steps=[0])), blocks=3),
    ("oscillation", "during_read"): Case(R, sim(Oscillation(steps=[0])), blocks=3),
    ("oscillation", "during_cleanup"): Case(X, sim(Oscillation())),
    # stuck outputs (the current source too): verification must fail and latch
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
    # a buggy kind forces 50 mA on the voltmeter: refused by the guard before any byte is written
    ("envelope_violation", "configure"): Case(C, buggy_50ma, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "after_xe"): Case(A, buggy_50ma, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "during_read"): Case(R, buggy_50ma, raises=EnvelopeViolation, blocks=None),
    ("envelope_violation", "during_cleanup"): Case(X, arm(violation)),
}


def test_spot_matrix_is_complete() -> None:
    assert set(SPOT) == {(f, p) for f in FAULTS for p in POSITIONS}


def test_the_plan_forces_voltage_and_current() -> None:
    sources = [line.split()[0] for line in PLAN.flex_preview if line.split()[0] in ("DV", "DI")]
    assert sources == ["DI", "DV", "DV", "DV", "DV"]  # the voltmeter once, then the drain at every level
    assert PLAN.envelope.channels[GATE].max_abs_i == 0.0 and PLAN.envelope.channels[GATE].max_abs_v == 2.0


def run_case(h: Harness, case: Case, plan: PlanRecord, monkeypatch: pytest.MonkeyPatch
             ) -> tuple[RawAcquisition | None, BaseException | None]:
    if case.moment == "setup":
        case.inject(h, monkeypatch)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch))
    result: RawAcquisition | None = None
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent="spot safety run") as tx:
            h.tx = tx
            result = KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h, monkeypatch)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return result, raised


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_spot_fault_matrix(fault: str, position: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = SPOT[(fault, position)]
    h = make_harness(tmp_path, hook_type=SpotHook)
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
        assert all(state.mode == "V" and state.current == 0.0 for state in h.sim.instrument.outputs().values())
    if case.raises is None or case.raises is CleanupUnverified:
        assert result is not None and case.blocks is not None
        assert len(result.blocks) == case.blocks == result.kind_result["points_done"]
        assert result.kind_result["points_planned"] == POINTS
        assert result.kind_result["stopped_early"] is (case.blocks < POINTS)
        assert len(h.run.raw) == case.blocks
        assert sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log) == case.blocks
        if case.blocks < POINTS:  # the flagged point is the last one
            assert "were not measured" in str(result.kind_result["stop_reason"])
            assert len(KIND.to_table(result, PLAN)) == case.blocks
    if isinstance(raised, AcquisitionError):
        assert [e.code for e in raised.errors] == [ERRX_CODE]
        triggered = sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log)
        assert triggered == (0 if position == "configure" else 3)  # nothing triggered after the error
    if case.latched:
        assert any(e.ev == "fault" for e in h.daily.events)
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())
        assert not any(r.mnemonic == "DI" and r.args[2] == "0.05" for r in h.log)


def test_clean_spot_run_sends_exactly_the_flex_preview(tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=SpotHook)
    with h.transaction(envelope=PLAN.envelope) as tx:
        result = KIND.acquire(tx, PLAN)
    assert_global_invariant(h, envelope=PLAN.envelope)
    writes = [r.command for r in h.log if not r.mnemonic.endswith("?") and r.outcome == "ok"]
    assert writes[:len(PLAN.flex_preview)] == PLAN.flex_preview
    assert writes[len(PLAN.flex_preview):] == ["DZ", "CL"]  # then the transaction's cleanup
    assert result.kind_result == {"points_planned": 4, "points_done": 4, "stopped_early": False, "stop_reason": ""}
    table = KIND.to_table(result, PLAN)
    assert table["a_V"].tolist() == LEVELS and table["step"].tolist() == [0, 1, 2, 3]
    assert table["d_I"].tolist() == [0.0] * 4  # the voltmeter's programmed current is a source column
    assert table["d_V"].tolist() == pytest.approx([v / 2 for v in LEVELS], rel=1e-6)  # gate leak splits evenly
    marks = [e.data["label"] for e in h.events() if e.ev == "checkpoint" and e.data]
    assert [m for m in marks if str(m).startswith("level ")] == [f"level {i}: a = {v:g} V" for i, v in
                                                                 enumerate(LEVELS)]


def tampered(plan: PlanRecord, **program: object) -> PlanRecord:
    """``plan`` with parts of its stored program replaced (envelope unchanged): a buggy or tampered kind program."""
    data = dict(plan.program)
    data.update(program)
    return plan.model_copy(update={"program": data})


def test_tampered_level_of_50_v_never_reaches_the_simulator(tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=SpotHook)
    level_list = dict(PLAN.program["level_list"])  # type: ignore[arg-type]
    plan = tampered(PLAN, level_list={**level_list, "values": [0.05, 50.0, 0.15]})
    with pytest.raises(EnvelopeViolation) as caught, h.transaction(envelope=plan.envelope) as tx:
        KIND.acquire(tx, plan)
    assert caught.value.reason == "level_exceeds_envelope" and caught.value.limit == 0.2
    assert_global_invariant(h, envelope=plan.envelope)
    assert sum(r.mnemonic == "XE" for r in h.log) == 1  # the first point ran; nothing after the refusal
    assert not any(r.source and "50" in r.command for r in h.log)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"


def test_tampered_current_source_is_refused_before_the_setup(tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=SpotHook)
    outputs = [dict(o) for o in PLAN.program["outputs"]]  # type: ignore[union-attr]
    for output in outputs:
        if output["role"] == "d":
            output["level"] = 0.01  # 10 mA into the gate, outside its 0 A envelope
    plan = tampered(PLAN, outputs=outputs)
    with pytest.raises(EnvelopeViolation), h.transaction(envelope=plan.envelope) as tx:
        KIND.acquire(tx, plan)
    assert_global_invariant(h, envelope=plan.envelope)
    assert not any(r.mnemonic in {"DI", "MM", "XE"} for r in h.log)


# -- ASU: the 1 pA range is checked live before the trigger ---------------------------------------------------------


def _gate_leakage_asu() -> PlanRecord:
    """``mosfet.gate_leakage`` with ``asu_1pa`` on the gate (SMU4), the station declaring ASU4 present."""
    station = example_station()
    switches = [s for s in station.switches if s.id != "ASU4"]
    asu4 = SwitchSpec(id="ASU4", kind="asu", present=True, certainty="verified", rest="smu",
                      ports={"OUT": SwitchPort(index=GATE, inputs={"smu": GATE})})
    station = station.model_copy(update={"switches": [*switches, asu4]})
    cfg = bundle(station_profile=station, pin_maps=[pin_map_exact("mosfet-4t", {
        "gate": GATE, "drain": DRAIN, "source": "GNDU", "bulk": "GNDU"})], duts=[dut()])
    req = PlanRequest.model_validate({"recipe_id": "mosfet.gate_leakage", "pin_map": "mosfet-4t",
                                      "dut_profile": "nmos-generic", "params": {"asu_1pa": True, "vg_points": 4}})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "ok", plan.summary
    assert f"RI {GATE},8" in plan.flex_preview
    return plan


def test_asu_range_without_an_asu_on_the_instrument_aborts_before_xe(tmp_path: Path) -> None:
    """The station claims an ASU the (simulated) mainframe does not have: ``RI 4,8`` is an instrument error, the
    setup drain aborts before any ``XE`` and the cleanup verifies."""
    plan = _gate_leakage_asu()
    h = make_harness(tmp_path)
    with pytest.raises(AcquisitionError) as caught, h.transaction(envelope=plan.envelope) as tx:
        SmuStaircaseKind().acquire(tx, plan)
    assert [e.code for e in caught.value.errors] == [124]  # incorrect range value for this channel
    assert_global_invariant(h, envelope=plan.envelope)
    assert not any(r.mnemonic == "XE" for r in h.log)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"


def test_asu_range_with_the_asu_present_runs(tmp_path: Path) -> None:
    from tests.sim.helpers import load_scenario, noiseless

    scenario = noiseless(load_scenario("nmos_basic"))
    slots = [s.model_copy(update={"asu": s.slot == GATE}) for s in scenario.slots]
    plan = _gate_leakage_asu()
    h = make_harness(tmp_path, scenario.model_copy(update={"slots": slots}))
    with h.transaction(envelope=plan.envelope) as tx:
        result = SmuStaircaseKind().acquire(tx, plan)
    assert_global_invariant(h, envelope=plan.envelope)
    assert [r.command for r in h.log if r.mnemonic == "RI"] == [f"RI {GATE},8"]
    assert len(result.blocks) == 1 and result.blocks[0].complete
