"""``cmu_measure`` rows of the safety matrix with the global invariant v2 (blueprint v2 2.6, 4.3, 8.1 ``safety/``;
WP8.3; the C-V variants of WP8.4).

The body is the real ``cmu_measure`` kind (``CmuMeasureKind.acquire``) running committed recipes compiled by the real
planner: ``cmu.spot`` (MM 17, two frequencies, three samples each; ``capacitor_100p``), ``moscap.cv`` (MM 18;
``moscap_basic``), ``mosfet.cgd_cv`` (MM 18 with the source SMU at 0 V; ``nmos_cv``), ``moscap.cv_ac_level`` (MM 23)
and ``moscap.pulsed_cv`` (MM 20; ``moscap_basic``), ``moscap.cf`` (MM 22) and ``moscap.ct`` (MM 26 with time stamps;
``moscap_dit``) and ``fecap.cv_butterfly`` (MM 18 double; ``fecap_basic``), each inside ONE transaction on the
noiseless scenario. Positions: ``configure`` = right before the first measurement mode is set (``MM``),
``during_read`` = at the first data read, ``during_cleanup`` = after the body. Faults: ``cmu_overload`` (excess
current: error 320, the MFCMU output switched off), a hang of ``XE``, ``disconnect``, an ``ERRX?`` entry, ``ignore_dz``
on the MFCMU, ``cleanup_failure``, ``garbage_data``, KeyboardInterrupt and an ``EnvelopeViolation`` (a buggy kind
asking for 0.2 V rms or a DC bias beyond the sweep). Global invariant v2: after any exit every channel is at 0 V and
``CL``, the MFCMU at DC 0 V and AC 0 V rms, or the fault latch is set with ``cleanup_unverified``; no MFCMU source or
frequency and no SMU level outside the compiled envelope ever reached the transport.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import CmuMeasureKind
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_config
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.sim import (
    CleanupFailure,
    CmuOverload,
    Disconnect,
    ErrxFault,
    GarbageData,
    IgnoreDz,
    SimFault,
    TimeoutFault,
)
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules import RulesEngine
from b1500_test_agent.session import CleanupUnverified
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order, make_harness
from tests.safety.test_cmu_matrix import assert_cmu_within_envelope
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.rules_factory import T0

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = CmuMeasureKind()
CMU = 7
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
CASES: dict[str, tuple[str, str, str, str] | tuple[str, str, str, str, dict[str, object]]] = {
    "spot": ("cmu.spot", "capacitor_100p", "capacitor-cmu", "capacitor-100p"),
    "cv": ("moscap.cv", "moscap_basic", "moscap-cmu", "moscap-generic"),
    "cgd": ("mosfet.cgd_cv", "nmos_cv", "mosfet-split-cv", "nmos-cv"),
    "acv": ("moscap.cv_ac_level", "moscap_basic", "moscap-cmu", "moscap-generic"),
    "pulsed": ("moscap.pulsed_cv", "moscap_basic", "moscap-cmu", "moscap-generic", {"points": 21}),
    "cf": ("moscap.cf", "moscap_dit", "moscap-cmu", "moscap-generic"),
    "ct": ("moscap.ct", "moscap_dit", "moscap-cmu", "moscap-generic", {"points": 51}),
    "butterfly": ("fecap.cv_butterfly", "fecap_basic", "fecap-cmu", "fecap-generic", {"points": 41}),
}
"""Case -> (recipe, scenario, pin map, DUT profile[, parameters]): fewer points where the default is long."""
POSITIONS = ("configure", "during_read", "during_cleanup")
FAULTS = ("cmu_overload", "timeout", "disconnect", "errx", "ignore_dz", "cleanup_failure", "garbage_data",
          "keyboard_interrupt", "envelope_violation")


def plan_of(name: str) -> PlanRecord:
    recipe_id, _, pin_map, dut, *rest = CASES[name]
    cfg = load_config(Paths.from_env({}, repo_root=REPO_ROOT))
    req = PlanRequest.model_validate({"recipe_id": recipe_id, "pin_map": pin_map, "dut_profile": dut,
                                      "params": rest[0] if rest else {}})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, RulesEngine(cfg, clock=lambda: T0))
    blocks = {f.rule_id for f in plan.rules.findings if f.severity == "block"}
    assert blocks == {"R-CORR-01"}, plan.summary  # no correction records here; the body runs regardless
    return plan


PLANS = {name: plan_of(name) for name in CASES}


class MeasureHook(HookTransport):
    """``configure`` fires right before the first ``MM`` write (measurement mode), ``during_read`` at the first data
    read (``HookTransport``)."""

    def write(self, cmd: str) -> None:
        if cmd.startswith("MM "):
            self.fire("configure")
        super().write(cmd)


def harness(tmp_path: Path, name: str) -> Harness:
    def hook(sim: SimTransport) -> HookTransport:
        return MeasureHook(sim)

    return make_harness(tmp_path, noiseless(load_scenario(CASES[name][1])), hook_type=hook)


@dataclass(frozen=True)
class Case:
    """``moment``: hook moment or ``cleanup``; ``raises``: exception leaving the ``with`` block (a tuple when it
    depends on the plan); ``latched``: fault latch set."""

    moment: str
    inject: Callable[[Harness], None]
    raises: tuple[type[BaseException] | None, ...] = (None,)
    latched: bool = False


def sim(make: Callable[[], SimFault]) -> Callable[[Harness], None]:
    return lambda h: h.sim.inject(make())


def interrupt(_h: Harness) -> None:
    raise KeyboardInterrupt


def arm_interrupt(h: Harness) -> None:
    h.hook.raise_next = KeyboardInterrupt()


def buggy_source(h: Harness) -> None:
    """A buggy kind asks for 0.2 V rms (envelope 0.03 V rms): the guard refuses before writing."""
    assert h.tx is not None
    h.tx.driver.set_cmu_ac(CMU, 0.2)


def arm_violation(h: Harness) -> None:
    try:
        h.tx.driver.guard.check_ac(CMU, 0.2, 0.0, 1e5)  # type: ignore[union-attr]
    except EnvelopeViolation as exc:
        h.hook.raise_next = exc


C, R, X = "configure", "during_read", "cleanup"
INJECTIONS: dict[tuple[str, str], Case] = {
    # excess current: error 320, the MFCMU output switched off; the readings are invalid (V), the run's own drain or
    # the cleanup reports the error; the outputs end safe
    ("cmu_overload", "configure"): Case(C, sim(lambda: CmuOverload(at_step=0, condition="excess_current")),
                                        raises=(None, AcquisitionError)),
    ("cmu_overload", "during_read"): Case(R, sim(lambda: CmuOverload(at_step=0, condition="excess_current")),
                                          raises=(None, AcquisitionError)),
    ("cmu_overload", "during_cleanup"): Case(X, sim(lambda: CmuOverload(at_step=0, condition="excess_current"))),
    # XE never completes: the read times out, the cleanup aborts and verifies
    ("timeout", "configure"): Case(C, sim(lambda: TimeoutFault(on="XE")), raises=(TransportTimeout,)),
    ("timeout", "during_read"): Case(R, sim(lambda: TimeoutFault(on="read")), raises=(TransportTimeout,)),
    ("timeout", "during_cleanup"): Case(X, sim(lambda: TimeoutFault(on="DZ"))),
    ("disconnect", "configure"): Case(C, sim(lambda: Disconnect(after_writes=0)), raises=(TransportError,),
                                      latched=True),
    ("disconnect", "during_read"): Case(R, sim(lambda: Disconnect(after_writes=0)), raises=(TransportError,),
                                        latched=True),
    ("disconnect", "during_cleanup"): Case(X, sim(lambda: Disconnect(after_writes=1)), raises=(CleanupUnverified,),
                                           latched=True),
    # an instrument error before XE aborts the setup (ERRX? drain); during the read it is reported by the cleanup
    ("errx", "configure"): Case(C, sim(lambda: ErrxFault(after_cmd="MM", code=100)), raises=(AcquisitionError,)),
    ("errx", "during_read"): Case(R, sim(lambda: ErrxFault(after_cmd="FC", code=100)),
                                  raises=(None, AcquisitionError)),
    ("errx", "during_cleanup"): Case(X, sim(lambda: ErrxFault(after_cmd="DZ", code=100))),
    ("ignore_dz", "configure"): Case(C, sim(lambda: IgnoreDz(channels=[CMU])), raises=(CleanupUnverified,),
                                     latched=True),
    ("ignore_dz", "during_read"): Case(R, sim(lambda: IgnoreDz(channels=[CMU])), raises=(CleanupUnverified,),
                                       latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, sim(lambda: IgnoreDz(channels=[CMU])), raises=(CleanupUnverified,),
                                          latched=True),
    ("cleanup_failure", "configure"): Case(C, sim(lambda: CleanupFailure(count=1))),
    ("cleanup_failure", "during_read"): Case(R, sim(lambda: CleanupFailure(count=2))),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(lambda: CleanupFailure()), raises=(CleanupUnverified,),
                                                latched=True),
    # unparsable data: the parser refuses the block (raw data kept), the cleanup runs
    ("garbage_data", "configure"): Case(C, sim(lambda: GarbageData(at_step=0)), raises=(FlexParseError,)),
    ("garbage_data", "during_read"): Case(R, sim(lambda: GarbageData(at_step=0)), raises=(None, FlexParseError)),
    ("garbage_data", "during_cleanup"): Case(X, sim(lambda: GarbageData(at_step=0))),
    ("keyboard_interrupt", "configure"): Case(C, interrupt, raises=(KeyboardInterrupt,)),
    ("keyboard_interrupt", "during_read"): Case(R, interrupt, raises=(KeyboardInterrupt,)),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm_interrupt, raises=(KeyboardInterrupt,)),
    ("envelope_violation", "configure"): Case(C, buggy_source, raises=(EnvelopeViolation,)),
    ("envelope_violation", "during_read"): Case(R, buggy_source, raises=(EnvelopeViolation,)),
    ("envelope_violation", "during_cleanup"): Case(X, arm_violation),  # the first cleanup step fails, the retry works
}


def assert_measure_invariant(h: Harness, plan: PlanRecord) -> None:
    """The global invariant v2 for one capacitance transaction (module docstring)."""
    log = h.log
    assert_cmu_within_envelope(log, plan.envelope)
    for record in log:
        if record.mnemonic in ("DV", "DI") and record.outcome != "dropped":
            channel = int(record.args[0])
            env = plan.envelope.channels.get(channel)
            assert env is not None and abs(float(record.args[2])) <= env.max_abs_v, record.command
    events = h.events()
    latched = h.session.fault_latch.get() is not None and any(e.ev == "cleanup_unverified" for e in events)
    if not latched:
        h.sim.instrument.assert_safe()  # every channel off at 0 V; the MFCMU also at AC 0 V rms
        sent = [r.mnemonic for r in log if r.outcome == "ok"]
        if "CN" in sent:
            assert {"DZ", "CL"} <= set(sent[sent.index("CN"):]), "DZ/CL missing after CN"
    assert h.session.lock.holder() is None and not h.session.lock.is_held()
    assert not (h.state_dir / "inflight.json").exists()
    assert_cleanup_order(events)
    assert [e.ev for e in events].count("lock_released") == 1


def test_cmu_measure_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_cmu_measure_fault_matrix(fault: str, position: str, name: str, tmp_path: Path) -> None:
    case = INJECTIONS[(fault, position)]
    plan = PLANS[name]
    h = harness(tmp_path, name)
    if case.moment != X:
        h.at(case.moment, lambda: case.inject(h))
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent=f"safety {plan.recipe_id}") as tx:
            h.tx = tx
            KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc

    assert_measure_invariant(h, plan)
    assert (None if raised is None else type(raised)) in case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_capacitance_run_ends_at_dc_0_and_ac_0(name: str, tmp_path: Path) -> None:
    h = harness(tmp_path, name)
    plan = PLANS[name]
    with h.transaction(envelope=plan.envelope, intent="safety capacitance") as tx:
        raw = KIND.acquire(tx, plan)
    assert raw.ok and raw.blocks
    assert_measure_invariant(h, plan)
    commands = [r.command for r in h.log if r.outcome == "ok"]
    last_xe = max(i for i, c in enumerate(commands) if c == "XE")
    assert f"DCV {CMU},0" in commands[last_xe:] and f"ACV {CMU},0" in commands[last_xe:]
    assert {"DZ", "CL"} <= set(commands[last_xe:])
    if name == "cgd":
        assert "DV 6,0,0,0.001" in commands  # the source SMU at 0 V (AC ground), within its envelope
