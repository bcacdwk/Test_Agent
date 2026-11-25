"""``smu_qscv`` rows of the safety matrix with the global invariant v2 (blueprint v2 2.6, 4.3, 8.1 ``safety/``; WP8.5).

The body is the real ``smu_qscv`` kind (``SmuQscvKind.acquire``) running the committed recipe ``moscap.qscv``, compiled
by the real planner, inside ONE transaction on the noiseless ``moscap_dit`` scenario: the card example through the SCUU
(``SSP 7,3`` switches SMU6/SMU5 on; the session declares SCUU1, so the guard admits the route and cleanup step 5
restores and verifies it), a direct landing (gate on HRSMU 3, bulk on the GNDU, ``CN``) and the offset measurement
(``QSZ 2``). Positions: ``configure`` = right before ``MM 13``, ``during_read`` = at the data read, ``during_cleanup`` =
after the body. Faults: a hang of ``XE``/the read/``DZ``, ``disconnect``, an ``ERRX?`` entry, ``ignore_dz`` on the
source, ``cleanup_failure``, ``garbage_data``, a compliance and an oscillation (the automatic abort: error 242, the run
keeps its data), KeyboardInterrupt and an ``EnvelopeViolation`` (a buggy kind forcing the gate beyond the envelope).
Global invariant v2: after any exit every channel is at 0 V and off and the SCUU at rest, or the fault latch is set
with ``cleanup_unverified``; no source level outside the compiled envelope ever reached the transport.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import SmuQscvKind
from b1500_test_agent.catalog.kinds.smu_staircase import AcquisitionError
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import load_config
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.sim import (
    CleanupFailure,
    ComplianceAt,
    Disconnect,
    ErrxFault,
    GarbageData,
    IgnoreDz,
    Oscillation,
    SimFault,
    TimeoutFault,
)
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules import RulesEngine
from b1500_test_agent.session import CleanupUnverified
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order, assert_within_envelope, make_harness
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.rules_factory import T0

pytestmark = pytest.mark.cmu

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = SmuQscvKind()
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
CONFIG = load_config(Paths.from_env({}, repo_root=REPO_ROOT))
SCUU = [s for s in CONFIG.station.switches if s.id == "SCUU1"]
CASES: dict[str, tuple[str, dict[str, object]]] = {
    "scuu": ("moscap-scuu", {"v_start": 1.0, "v_stop": -1.0, "step_v": 0.1}),
    "direct": ("moscap-direct", {"v_start": 1.0, "v_stop": -1.0, "step_v": 0.1, "irange_a": 1e-8}),
    "offset": ("moscap-scuu", {"offset": "measure"}),
}
"""Case -> (pin map, parameters); ``moscap-direct`` (gate HRSMU 3, bulk GNDU) is a test pin map written below."""
SOURCE = {"scuu": 6, "direct": 3, "offset": 6}


def plan_of(name: str) -> PlanRecord:
    pin_map, params = CASES[name]
    cfg = CONFIG
    if pin_map == "moscap-direct":
        direct = cfg.pin_maps["moscap-cmu"].model_copy(update={"name": "moscap-direct",
                                                               "terminals": {"gate": 3, "bulk": "GNDU"}})
        cfg = cfg.model_copy(update={"pin_maps": {**cfg.pin_maps, "moscap-direct": direct}})
    req = PlanRequest.model_validate({"recipe_id": "moscap.qscv", "pin_map": pin_map, "dut_profile": "moscap-generic",
                                      "params": params})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, RulesEngine(cfg, clock=lambda: T0))
    blocks = [f for f in plan.rules.findings if f.severity == "block"]
    assert not blocks, [f.message for f in blocks]
    return plan


PLANS = {name: plan_of(name) for name in CASES}


class QscvHook(HookTransport):
    """``configure`` fires right before ``MM 13``, ``during_read`` at the first data read (``HookTransport``)."""

    def write(self, cmd: str) -> None:
        if cmd.startswith("MM "):
            self.fire("configure")
        super().write(cmd)


def harness(tmp_path: Path, name: str) -> Harness:
    def hook(sim: SimTransport) -> HookTransport:
        return QscvHook(sim)

    scenario = noiseless(load_scenario("moscap_dit"))
    if name == "direct":  # the moscap landed on HRSMU 3 and the GNDU (no SCUU path)
        scenario = scenario.model_copy(update={"wiring": {**scenario.wiring, "dut": {"gate": 3, "bulk": "GNDU"}},
                                               "scuu": []})
    return make_harness(tmp_path, scenario, hook_type=hook, switches=SCUU if name != "direct" else [])


@dataclass(frozen=True)
class Case:
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
    """A buggy kind forces the gate to 5 V (envelope 1 V): the guard refuses before writing."""
    assert h.tx is not None
    channel = next(ch for ch, env in h.tx.driver.guard.envelope.channels.items() if env.function == "sweep_v")  # type: ignore[union-attr]
    h.tx.driver.force_v(channel, 5.0, icomp=1e-6)


def arm_violation(h: Harness) -> None:
    try:
        h.tx.driver.guard.check(6, "V", 5.0, 1e-6)  # type: ignore[union-attr]
    except EnvelopeViolation as exc:
        h.hook.raise_next = exc


C, R, X = "configure", "during_read", "cleanup"
INJECTIONS: dict[tuple[str, str], Case] = {
    ("timeout", "configure"): Case(C, lambda h: h.sim.inject(TimeoutFault(on="QSZ" if h.name == "offset" else "XE")),
                                   raises=(TransportTimeout,)),  # the trigger never completes (XE, or QSZ 2)
    ("timeout", "during_read"): Case(R, sim(lambda: TimeoutFault(on="read")), raises=(TransportTimeout,)),
    ("timeout", "during_cleanup"): Case(X, sim(lambda: TimeoutFault(on="DZ"))),
    ("disconnect", "configure"): Case(C, sim(lambda: Disconnect(after_writes=0)), raises=(TransportError,),
                                      latched=True),
    ("disconnect", "during_read"): Case(R, sim(lambda: Disconnect(after_writes=0)), raises=(TransportError,),
                                        latched=True),
    ("disconnect", "during_cleanup"): Case(X, sim(lambda: Disconnect(after_writes=1)), raises=(CleanupUnverified,),
                                           latched=True),
    ("errx", "configure"): Case(C, sim(lambda: ErrxFault(after_cmd="QSV", code=100)), raises=(AcquisitionError,)),
    ("errx", "during_read"): Case(R, sim(lambda: ErrxFault(after_cmd="QSV", code=100)),
                                  raises=(None, AcquisitionError)),
    ("errx", "during_cleanup"): Case(X, sim(lambda: ErrxFault(after_cmd="DZ", code=100))),
    ("ignore_dz", "configure"): Case(C, lambda h: h.sim.inject(IgnoreDz(channels=[SOURCE[h.name]])),
                                     raises=(CleanupUnverified,), latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, lambda h: h.sim.inject(IgnoreDz(channels=[SOURCE[h.name]])),
                                          raises=(CleanupUnverified,), latched=True),
    ("cleanup_failure", "configure"): Case(C, sim(lambda: CleanupFailure(count=1))),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(lambda: CleanupFailure()), raises=(CleanupUnverified,),
                                                latched=True),
    ("garbage_data", "configure"): Case(C, sim(lambda: GarbageData(at_step=0)), raises=(FlexParseError,)),
    # the automatic abort (QSM 2): compliance or oscillation at the first step, dummy data, error 242 recorded
    ("compliance", "configure"): Case(C, lambda h: h.sim.inject(ComplianceAt(step=0, ch=SOURCE[h.name]))),
    ("oscillation", "configure"): Case(C, sim(lambda: Oscillation(steps=[1]))),
    ("keyboard_interrupt", "configure"): Case(C, interrupt, raises=(KeyboardInterrupt,)),
    ("keyboard_interrupt", "during_read"): Case(R, interrupt, raises=(KeyboardInterrupt,)),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm_interrupt, raises=(KeyboardInterrupt,)),
    ("envelope_violation", "configure"): Case(C, buggy_source, raises=(EnvelopeViolation,)),
    ("envelope_violation", "during_cleanup"): Case(X, arm_violation),
}


def assert_qscv_invariant(h: Harness, plan: PlanRecord) -> None:
    """The global invariant v2 for one QSCV transaction (module docstring)."""
    log = h.log
    assert_within_envelope(log, plan.envelope)
    events = h.events()
    latched = h.session.fault_latch.get() is not None and any(e.ev == "cleanup_unverified" for e in events)
    if not latched:
        h.sim.instrument.assert_safe()  # every channel off at 0 V
        if h.session.switches:
            assert h.sim.instrument.state.scuu_paths.get(7) in (None, 3)  # SCUU1 at rest (SMU/SMU) or power-on
        sent = [r.mnemonic for r in log if r.outcome == "ok"]
        first = next((i for i, m in enumerate(sent) if m in ("CN", "SSP")), None)
        if first is not None:
            assert {"DZ", "CL"} <= set(sent[first:]), "DZ/CL missing after the outputs were switched on"
    assert h.session.lock.holder() is None and not h.session.lock.is_held()
    assert not (h.state_dir / "inflight.json").exists()
    assert_cleanup_order(events)
    assert [e.ev for e in events].count("lock_released") == 1


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize(("fault", "position"), sorted(INJECTIONS))
def test_smu_qscv_fault_matrix(fault: str, position: str, name: str, tmp_path: Path) -> None:
    case = INJECTIONS[(fault, position)]
    if name == "offset" and fault in ("garbage_data", "compliance", "oscillation"):
        pytest.skip("the offset measurement returns one datum without step faults")
    plan = PLANS[name]
    h = harness(tmp_path, name)
    h.name = name  # type: ignore[attr-defined]
    if case.moment != X:
        h.at(case.moment, lambda: case.inject(h))
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent=f"safety {plan.recipe_id}") as tx:
            h.tx = tx
            raw = KIND.acquire(tx, plan)
            if fault in ("compliance", "oscillation"):
                assert raw.kind_result["aborted"] is True
            if case.moment == X:
                case.inject(h)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    assert_qscv_invariant(h, plan)
    assert (None if raised is None else type(raised)) in case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_qscv_run_ends_safe_with_the_scuu_at_rest(name: str, tmp_path: Path) -> None:
    h = harness(tmp_path, name)
    plan = PLANS[name]
    with h.transaction(envelope=plan.envelope, intent="safety qscv") as tx:
        raw = KIND.acquire(tx, plan)
    assert raw.ok and raw.blocks and raw.kind_result["aborted"] is False
    assert_qscv_invariant(h, plan)
    commands = [r.command for r in h.log if r.outcome == "ok"]
    if name == "direct":
        assert "CN 3" in commands and not any(c.startswith("SSP") for c in commands)
    else:
        assert "SSP 7,3" in commands and not any(c.startswith("CN") for c in commands)
        assert tx.cleanup is not None and tx.cleanup.switches_after["SCUU1.OUT1"] == "smu"
    assert ("QSZ 2" in commands) == (name == "offset")
    assert {"DZ", "CL"} <= set(commands[max(i for i, c in enumerate(commands) if c in ("XE", "QSZ 2")):])
