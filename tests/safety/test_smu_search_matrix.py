"""Search-measurement rows of the fault matrix with the global invariant (blueprint v2 2.6, 8.1 ``safety/``, WP7.5).

The body is the real ``smu_search`` kind (``SmuSearchKind.acquire``) running the committed ``mosfet.vth_search``
recipe (MM 15 binary search: gate search source, drain bias and monitor), compiled by the real planner, inside ONE
transaction on the noiseless ``nmos_basic`` simulator. Every fault of the staircase matrix is injected at every
position: ``configure`` = right before the ``MM`` write, ``after_xe`` = right after the ``XE``, ``during_read`` = at
the start of the data read, ``during_cleanup`` = after the body. A search is one ``XE`` that the simulator evaluates
at once, so an instrument-side fault injected after it acts on nothing but the cleanup.

Every case asserts the global invariant v2 (the search sources too: ``BSV``'s start and stop and its compliance against
the channel envelope), the expected exception and fault-latch outcome and the search status the read reports
(``S`` when a compliance or an oscillation stops the search: automatic abort ``BSM x,2``). Separate tests refuse
tampered programs (a gate search to 3.5 V, a synchronous source beyond the envelope, a quasi-pulse beyond it, a larger
compliance) in the guard before any byte is written, and run the linear and quasi-pulsed breakdown recipes with a
compliance fault and the cleanup verified.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import SearchProgram, SmuSearchKind
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.driver.b1500 import SyncSource
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
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.rules_factory import T0, bundle, dut, engine, pin_map_exact

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = SmuSearchKind()
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "parser_exception", "envelope_violation")
ERRX_CODE = 305
DRAIN, GATE = 3, 4  # the nmos_basic wiring: gate SMU4, drain SMU3, source on the GNDU

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
SEARCH_MAP = pin_map_exact("search-3t", {"gate": GATE, "drain": DRAIN, "source": "GNDU", "bulk": "GNDU"})
DIELECTRIC_MAP = pin_map_exact("dielectric-2t", {"gate": 4, "bulk": "GNDU"})


def plan_of(recipe_id: str, pin_map: str, dut_name: str, **params: object) -> PlanRecord:
    duts = [dut("search-3t"), dut("thin-film", device_type="dielectric", gate=(10.0, 1e-2), bulk=(1.0, 1e-2)),
            dut("thick-film", device_type="dielectric", gate=(30.0, 1e-2), bulk=(1.0, 1e-2))]
    cfg = bundle(pin_maps=[SEARCH_MAP, DIELECTRIC_MAP], duts=duts)
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map, "dut_profile": dut_name,
                                      "params": params})
    return Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))


PLAN = plan_of("mosfet.vth_search", "search-3t", "search-3t")


class SearchHook(HookTransport):
    """``configure`` fires right before the ``MM`` write, ``after_xe`` after the ``XE``, ``during_read`` at the data
    read; ``raise_next`` as in ``HookTransport``."""

    def __init__(self, inner: SimTransport) -> None:
        super().__init__(inner)

    def write(self, cmd: str) -> None:
        self._armed()
        if cmd.startswith("MM "):
            self.fire("configure")
        self.inner.write(cmd)
        if cmd == "XE":
            self.fire("after_xe")

    def read(self, *, timeout_s: float | None = None) -> str:
        self._armed()
        self.fire("during_read")
        return self.inner.read(timeout_s=timeout_s)


@dataclass(frozen=True)
class Case:
    """``status`` = the ``Data_search`` status the completed body reports (``None`` when it raises)."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    status: str | None = "N"
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


def tampered(plan: PlanRecord, **source_changes: object) -> object:
    program = SearchProgram.model_validate(plan.program)
    assert program.search is not None
    source = program.search.source.model_copy(update=source_changes)
    return program.search.model_copy(update={"source": source})


def buggy_search(h: Harness, _mp: pytest.MonkeyPatch) -> None:
    """A deliberately buggy kind sets up a gate search to 3.5 V (envelope 2 V): refused before writing."""
    assert h.tx is not None
    h.tx.driver.search_setup(tampered(PLAN, stop=3.5))  # type: ignore[arg-type]


def violation() -> BaseException:
    try:
        OutputGuard(PLAN.envelope).check(GATE, "V", 3.5, 1e-6)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("the guard accepted 3.5 V")


def parse_error() -> BaseException:
    return FlexParseError("injected parser failure", raw="NDV+?")


def bad_parse_data(_h: Harness, mp: pytest.MonkeyPatch) -> None:
    original = driver_module.parse_data

    def flaky(raw: str, fmt: int) -> object:
        if raw.startswith(("N", "G", "S")) and "," in raw:
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

SEARCH: dict[tuple[str, str], Case] = {
    # compliance on the drain (the monitor) or the gate at the first point stops the search (S: automatic abort);
    # after the XE the search is already evaluated
    ("compliance_at", "configure"): Case(C, sim(ComplianceAt(step=0, ch=DRAIN)), status="S"),
    ("compliance_at", "after_xe"): Case(A, sim(ComplianceAt(step=0, ch=DRAIN))),
    ("compliance_at", "during_read"): Case(R, sim(ComplianceAt(step=0, ch=GATE))),
    ("compliance_at", "during_cleanup"): Case(X, sim(ComplianceAt(step=0, ch=DRAIN))),
    # an error after MM (the setup drain aborts before the XE); injected after the XE (there is no second one) or
    # later: after DZ / CL of the cleanup (drained into the cleanup report)
    ("errx", "configure"): Case(C, sim(ErrxFault(after_cmd="MM", code=ERRX_CODE)), raises=AcquisitionError,
                                status=None),
    ("errx", "after_xe"): Case(A, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_read"): Case(R, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("errx", "during_cleanup"): Case(X, sim(ErrxFault(after_cmd="CL", code=ERRX_CODE)), errors=(ERRX_CODE,)),
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="MM")), raises=TransportTimeout, status=None),
    ("timeout", "after_xe"): Case(A, sim(TimeoutFault(on="read")), raises=TransportTimeout, status=None),
    ("timeout", "during_read"): Case(R, sim(TimeoutFault(on="read")), raises=TransportTimeout, status=None),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError, status=None),
    ("garbage_data", "after_xe"): Case(A, sim(GarbageData(at_step=0))),
    ("garbage_data", "during_read"): Case(R, sim(GarbageData(at_step=0))),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    ("interlock_open", "configure"): Case(C, sim(InterlockOpen())),  # 2 V: no high-voltage state
    ("interlock_open", "after_xe"): Case(A, sim(InterlockOpen(at_step=0))),
    ("interlock_open", "during_read"): Case(R, sim(InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(InterlockOpen())),
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True,
                                      status=None),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                     status=None),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True,
                                        status=None),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    ("oscillation", "configure"): Case(C, sim(Oscillation(steps=[0])), status="S"),
    ("oscillation", "after_xe"): Case(A, sim(Oscillation(steps=[0]))),
    ("oscillation", "during_read"): Case(R, sim(Oscillation(steps=[0]))),
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
                                              status=None),
    ("keyboard_interrupt", "after_xe"): Case(A, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt,
                                             status=None),
    ("keyboard_interrupt", "during_read"): Case(R, raise_now(KeyboardInterrupt), raises=KeyboardInterrupt,
                                                status=None),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm(KeyboardInterrupt), raises=KeyboardInterrupt),
    ("parser_exception", "configure"): Case(C, raise_now(parse_error), raises=FlexParseError, status=None),
    ("parser_exception", "after_xe"): Case(A, raise_now(parse_error), raises=FlexParseError, status=None),
    ("parser_exception", "during_read"): Case("setup", bad_parse_data, raises=FlexParseError, status=None),
    ("parser_exception", "during_cleanup"): Case(X, bad_parse_errx_once),
    ("envelope_violation", "configure"): Case(C, buggy_search, raises=EnvelopeViolation, status=None),
    ("envelope_violation", "after_xe"): Case(A, raise_now(violation), raises=EnvelopeViolation, status=None),
    ("envelope_violation", "during_read"): Case(R, raise_now(violation), raises=EnvelopeViolation, status=None),
    ("envelope_violation", "during_cleanup"): Case(X, arm(violation)),
}


def test_search_matrix_is_complete() -> None:
    assert set(SEARCH) == {(f, p) for f in FAULTS for p in POSITIONS}


def test_the_plan_searches_the_gate_inside_its_envelope() -> None:
    assert PLAN.tier == "ok", PLAN.summary
    assert [line for line in PLAN.flex_preview if line.split()[0] in ("MM", "BSM", "BGI", "BSV", "XE")] == [
        "MM 15", "BSM 1,2,1", "BGI 3,0,1E-09,0,1E-07", "BSV 4,0,0,2,1E-06", "XE"]
    gate = PLAN.envelope.channels[GATE]
    assert (gate.max_abs_v, gate.max_abs_i, gate.v_start, gate.v_stop) == (2.0, 1e-6, 0.0, 2.0)


def run_case(h: Harness, case: Case, plan: PlanRecord, monkeypatch: pytest.MonkeyPatch
             ) -> tuple[RawAcquisition | None, BaseException | None]:
    if case.moment == "setup":
        case.inject(h, monkeypatch)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch))
    result: RawAcquisition | None = None
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent="search safety run") as tx:
            h.tx = tx
            result = KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h, monkeypatch)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    return result, raised


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_smu_search_fault_matrix(fault: str, position: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = SEARCH[(fault, position)]
    h = make_harness(tmp_path, hook_type=SearchHook)
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
        assert all(state.mode == "V" and state.voltage == 0.0 for state in h.sim.instrument.outputs().values())
    if case.raises is None or case.raises is CleanupUnverified:
        assert result is not None and case.status is not None
        assert result.kind_result["search_status"] == case.status
        assert result.kind_result["found"] is (case.status == "N")
        assert len(result.blocks) == 1 == len(h.run.raw)
        assert sum(r.mnemonic == "XE" and r.outcome == "ok" for r in h.log) == 1
        assert len(KIND.to_table(result, PLAN)) == 1
    if isinstance(raised, AcquisitionError):
        assert [e.code for e in raised.errors] == [ERRX_CODE]
        assert not any(r.mnemonic == "XE" for r in h.log)
    if case.latched:
        assert any(e.ev == "fault" for e in h.daily.events)
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())


@pytest.mark.parametrize(("changes", "reason"), [
    ({"stop": 3.5}, "level_exceeds_envelope"),
    ({"start": -2.5}, "level_exceeds_envelope"),
    ({"comp": 1e-3}, "compliance_exceeds_envelope"),
])
def test_tampered_search_programs_never_reach_the_instrument(changes: dict[str, object], reason: str,
                                                             tmp_path: Path) -> None:
    h = make_harness(tmp_path, hook_type=SearchHook)
    with pytest.raises(EnvelopeViolation) as info, h.transaction(envelope=PLAN.envelope, intent="tamper") as tx:
        h.tx = tx
        tx.driver.search_setup(tampered(PLAN, **changes))  # type: ignore[arg-type]
    assert info.value.reason == reason
    assert not any(r.mnemonic in ("MM", "BSV", "BSM", "BGI") for r in h.log)
    assert_global_invariant(h, envelope=PLAN.envelope)


def test_a_synchronous_source_beyond_its_envelope_is_refused(tmp_path: Path) -> None:
    """The drain is a constant 0.05 V bias: a tampered synchronous drain source following the gate to 2 V leaves its
    envelope and nothing is written."""
    program = SearchProgram.model_validate(PLAN.program)
    assert program.search is not None
    setup = program.search.model_copy(update={"sync": SyncSource(channel=DRAIN, polarity=1, offset=0.0, comp=1e-3)})
    h = make_harness(tmp_path, hook_type=SearchHook)
    with pytest.raises(EnvelopeViolation) as info, h.transaction(envelope=PLAN.envelope, intent="tamper") as tx:
        tx.driver.search_setup(setup)
    assert info.value.reason == "level_exceeds_envelope" and info.value.channel == DRAIN
    assert not any(r.mnemonic in ("MM", "BSV", "BSSV") for r in h.log)


@pytest.mark.parametrize(("recipe_id", "scenario", "dut_name", "params", "status"), [
    ("dielectric.bdv", "dielectric_tddb", "thin-film", {"method": "linear", "v_stop": 10.0}, "N"),
    ("dielectric.bdv", "dielectric_thick", "thick-film", {"v_stop": 30.0}, "C"),
])
def test_breakdown_searches_end_safe_after_the_breakdown(recipe_id: str, scenario: str, dut_name: str,
                                                        params: dict[str, object], status: str,
                                                        tmp_path: Path) -> None:
    """The destructive searches: the film breaks (the source hits its compliance), the cleanup zeroes and verifies,
    nothing outside the envelope was written; a tampered quasi-pulse beyond the envelope is refused."""
    plan = plan_of(recipe_id, "dielectric-2t", dut_name, **params)
    assert plan.tier == "needs_confirmation" and "destructive" in plan.summary
    h = make_harness(tmp_path, scenario=noiseless(load_scenario(scenario)), hook_type=SearchHook)
    with h.transaction(envelope=plan.envelope, intent="breakdown") as tx:
        h.tx = tx
        result = KIND.acquire(tx, plan)
    assert result.kind_result["search_status"] == status and result.kind_result["found"] is True
    assert_global_invariant(h, envelope=plan.envelope)
    assert h.sim.instrument.circuit.export_state()["dut"]["broken"] is True
    if status == "C":
        program = SearchProgram.model_validate(plan.program)
        assert program.quasi is not None
        h2 = make_harness(tmp_path / "tamper", scenario=noiseless(load_scenario(scenario)), hook_type=SearchHook)
        with pytest.raises(EnvelopeViolation), h2.transaction(envelope=plan.envelope, intent="tamper") as tx2:
            tx2.driver.quasi_pulse_setup(program.quasi.model_copy(update={"stop": 35.0}))
        assert not any(r.mnemonic in ("MM", "BDV") for r in h2.log)
