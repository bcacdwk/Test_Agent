"""MFCMU correction rows of the safety matrix with the global invariant v2 (blueprint v2 2.6, 4.3, 8.1 ``safety/``;
WP8.2).

The body is the real ``cmu_correction`` kind (``CmuCorrectionKind.acquire``) running the committed recipes
``cmu.phase_compensation`` and ``cmu.correction_open``, compiled by the real planner (pin map ``capacitor-cmu``),
inside ONE transaction on the noiseless ``capacitor_100p`` simulator. Positions: ``configure`` = right before the
measurement query (``ADJ? 7,1`` / ``CORR? 7,1``), ``after_measure`` = right after its answer (before ``CORRST`` and
the read-back), ``during_cleanup`` = after the body. Faults: ``cmu_correction_lost`` (the module forgets everything,
as a power glitch would), a hang of the measurement or of a later command, ``disconnect``, an ``ERRX?`` entry,
``ignore_dz`` on the MFCMU, ``cleanup_failure``, KeyboardInterrupt and an ``EnvelopeViolation`` (a buggy kind asking
for 0.2 V rms). Global invariant v2 (MFCMU part): after any exit the MFCMU is at DC 0 V, AC 0 V rms and ``CL``, or
the fault latch is set with ``cleanup_unverified``; no MFCMU source or frequency outside the compiled envelope ever
reached the transport. A correction lost during the run is reported by the run itself (its read-back shows the
correction off: ``ok`` False), never as a fresh correction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import CmuCorrectionKind
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.sim import (
    CleanupFailure,
    CmuCorrectionLost,
    Disconnect,
    ErrxFault,
    IgnoreDz,
    SimFault,
    TimeoutFault,
)
from b1500_test_agent.session import CleanupUnverified
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim import SimTransport
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order, make_harness
from tests.safety.test_cmu_matrix import assert_cmu_within_envelope
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.rules_factory import T0, bundle, engine, pin_map_exact

pytestmark = pytest.mark.cmu

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = CmuCorrectionKind()
CMU = 7
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
CAP_MAP = pin_map_exact("capacitor-cmu", {"a": "7H", "b": "7L"})
RECIPES = {"phase": "cmu.phase_compensation", "open": "cmu.correction_open"}
MEASURE = {"phase": "ADJ?", "open": "CORR?"}
POSITIONS = ("configure", "after_measure", "during_cleanup")
FAULTS = ("cmu_correction_lost", "timeout", "disconnect", "errx", "ignore_dz", "cleanup_failure", "keyboard_interrupt",
          "envelope_violation")


def correction_plan(kind: str) -> PlanRecord:
    cfg = bundle(pin_maps=[CAP_MAP])
    req = PlanRequest.model_validate({"recipe_id": RECIPES[kind], "pin_map": "capacitor-cmu"})
    plan = Planner(REGISTRY, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "needs_confirmation" and plan.rules.confirm_reasons == ["physical_setup"], plan.summary
    return plan


PLANS = {kind: correction_plan(kind) for kind in RECIPES}


class CorrectionHook(HookTransport):
    """``configure`` fires right before the measurement query (``ADJ? 7,1``/``CORR? 7,...``), ``after_measure``
    right after its answer; ``raise_next`` as in ``HookTransport``."""

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        measuring = cmd.startswith("CORR? ") or cmd == f"ADJ? {CMU},1"
        if measuring:
            self.fire("configure")
        answer = super().query(cmd, timeout_s=timeout_s)
        if measuring:
            self.fire("after_measure")
        return answer


def harness(tmp_path: Path) -> Harness:
    def hook(sim: SimTransport) -> HookTransport:
        return CorrectionHook(sim)

    return make_harness(tmp_path, noiseless(load_scenario("capacitor_100p")), hook_type=hook)


@dataclass(frozen=True)
class Case:
    """``moment``: hook moment or ``cleanup``; ``raises``: exception leaving the ``with`` block; ``latched``: fault
    latch set; ``ok``: the kind's own verdict when the body completes (``None`` when it raises)."""

    moment: str
    inject: Callable[[Harness, str], None]
    raises: type[BaseException] | None = None
    latched: bool = False
    ok: bool | None = True


def sim(make: Callable[[str], SimFault]) -> Callable[[Harness, str], None]:
    return lambda h, kind: h.sim.inject(make(kind))


def interrupt(_h: Harness, _kind: str) -> None:
    raise KeyboardInterrupt


def arm_interrupt(h: Harness, _kind: str) -> None:
    h.hook.raise_next = KeyboardInterrupt()


def buggy_ac(h: Harness, _kind: str) -> None:
    """A buggy kind asks for 0.2 V rms (envelope 0.03 / 0 V rms): the guard refuses before writing."""
    assert h.tx is not None
    h.tx.driver.set_cmu_ac(CMU, 0.2)


def arm_violation(h: Harness, kind: str) -> None:
    try:
        h.tx.driver.guard.check_ac(CMU, 0.2, 0.0, 1e5)  # type: ignore[union-attr]
    except EnvelopeViolation as exc:
        h.hook.raise_next = exc


C, A, X = "configure", "after_measure", "cleanup"
INJECTIONS: dict[tuple[str, str], Case] = {
    # lost right after the measurement: the read-back shows it off, the run says so (never a fresh correction);
    # lost after the read-back or at CL: the run is fine, the next run's live check (R-CORR-01) catches it
    ("cmu_correction_lost", "configure"): Case(C, sim(lambda k: CmuCorrectionLost(after_cmd=MEASURE[k])), ok=False),
    ("cmu_correction_lost", "after_measure"): Case(A, sim(lambda k: CmuCorrectionLost(after_cmd="*LRN?")), ok=True),
    ("cmu_correction_lost", "during_cleanup"): Case(X, sim(lambda k: CmuCorrectionLost(after_cmd="CL"))),
    # the measurement never answers; CORRST?/the read-back hangs; DZ hangs (retry after the device clear)
    ("timeout", "configure"): Case(C, sim(lambda k: TimeoutFault(on=f"query:{MEASURE[k]}")), raises=TransportTimeout,
                                   ok=None),
    ("timeout", "after_measure"): Case(A, sim(lambda k: TimeoutFault(on="query:CORRST?")), raises=TransportTimeout,
                                       ok=None),
    ("timeout", "during_cleanup"): Case(X, sim(lambda k: TimeoutFault(on="DZ"))),
    ("disconnect", "configure"): Case(C, sim(lambda k: Disconnect(after_writes=0)), raises=TransportError,
                                      latched=True, ok=None),
    ("disconnect", "after_measure"): Case(A, sim(lambda k: Disconnect(after_writes=0)), raises=TransportError,
                                          latched=True, ok=None),
    ("disconnect", "during_cleanup"): Case(X, sim(lambda k: Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # an instrument error is drained by the cleanup and reported; the correction itself completed
    ("errx", "configure"): Case(C, sim(lambda k: ErrxFault(after_cmd=MEASURE[k], code=684))),
    ("errx", "after_measure"): Case(A, sim(lambda k: ErrxFault(after_cmd="CORRST?", code=685))),
    ("errx", "during_cleanup"): Case(X, sim(lambda k: ErrxFault(after_cmd="DZ", code=100))),
    # a stuck MFCMU output: the verification fails and latches
    ("ignore_dz", "configure"): Case(C, sim(lambda k: IgnoreDz(channels=[CMU])), raises=CleanupUnverified,
                                     latched=True),
    ("ignore_dz", "after_measure"): Case(A, sim(lambda k: IgnoreDz(channels=[CMU])), raises=CleanupUnverified,
                                         latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, sim(lambda k: IgnoreDz(channels=[CMU])), raises=CleanupUnverified,
                                          latched=True),
    ("cleanup_failure", "configure"): Case(C, sim(lambda k: CleanupFailure(count=1))),
    ("cleanup_failure", "after_measure"): Case(A, sim(lambda k: CleanupFailure(count=2))),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(lambda k: CleanupFailure()), raises=CleanupUnverified,
                                                latched=True),
    ("keyboard_interrupt", "configure"): Case(C, interrupt, raises=KeyboardInterrupt, ok=None),
    ("keyboard_interrupt", "after_measure"): Case(A, interrupt, raises=KeyboardInterrupt, ok=None),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm_interrupt, raises=KeyboardInterrupt),
    ("envelope_violation", "configure"): Case(C, buggy_ac, raises=EnvelopeViolation, ok=None),
    ("envelope_violation", "after_measure"): Case(A, buggy_ac, raises=EnvelopeViolation, ok=None),
    ("envelope_violation", "during_cleanup"): Case(X, arm_violation),  # the first cleanup step fails, the retry works
}


def assert_correction_invariant(h: Harness, plan: PlanRecord) -> None:
    """The global invariant v2 for one correction transaction (module docstring)."""
    log = h.log
    assert_cmu_within_envelope(log, plan.envelope)
    assert not [r for r in log if r.mnemonic in ("DV", "DI", "WV", "WI")], "an SMU source in a correction run"
    events = h.events()
    latched = h.session.fault_latch.get() is not None and any(e.ev == "cleanup_unverified" for e in events)
    if not latched:
        h.sim.instrument.assert_safe()  # every channel off at 0 V; the MFCMU also at AC 0 V rms
        after_cn = [r.mnemonic for r in log if r.outcome == "ok"]
        if "CN" in after_cn:
            assert {"DZ", "CL"} <= set(after_cn[after_cn.index("CN"):]), "DZ/CL missing after CN"
    assert h.session.lock.holder() is None and not h.session.lock.is_held()
    assert not (h.state_dir / "inflight.json").exists()
    assert_cleanup_order(events)
    assert [e.ev for e in events].count("lock_released") == 1


def test_cmu_correction_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}


@pytest.mark.parametrize("kind", sorted(RECIPES))
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_cmu_correction_fault_matrix(fault: str, position: str, kind: str, tmp_path: Path) -> None:
    case = INJECTIONS[(fault, position)]
    plan = PLANS[kind]
    h = harness(tmp_path)
    if case.moment != X:
        h.at(case.moment, lambda: case.inject(h, kind))
    raised: BaseException | None = None
    raw: RawAcquisition | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent=f"safety {RECIPES[kind]}") as tx:
            h.tx = tx
            raw = KIND.acquire(tx, plan)
            if case.moment == X:
                case.inject(h, kind)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc

    assert_correction_invariant(h, plan)
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if case.ok is not None and case.moment != X:
        assert raw is not None and raw.ok is case.ok, raw.message if raw else None
    if case.ok is False:
        assert raw is not None and "not in effect" in raw.message
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())
    if fault == "errx" and position != "during_cleanup":
        assert {684, 685} & {e.code for e in tx.cleanup.errors}


@pytest.mark.parametrize("kind", sorted(RECIPES))
def test_cmu_correction_run_zeroes_the_mfcmu_and_leaves_the_correction_in_effect(kind: str, tmp_path: Path) -> None:
    h = harness(tmp_path)
    plan = PLANS[kind]
    with h.transaction(envelope=plan.envelope, intent="safety correction") as tx:
        raw = KIND.acquire(tx, plan)
    assert raw.ok and raw.kind_result["result_code"] == 0
    assert_correction_invariant(h, plan)
    commands = [r.command for r in h.log if r.outcome == "ok"]
    measured = max(i for i, c in enumerate(commands) if c.startswith(("CORR? ", "ADJ? 7,1")))
    assert {"DZ", "CL"} <= set(commands[measured:])
    state = h.sim.instrument.state
    if kind == "phase":
        assert state.cmu_phase_results[CMU] == 0 and not any(state.cmu_corrections.get(CMU, {}).values())
        assert not [c for c in commands if c.startswith(("FC", "ACV", "DCV"))]  # no programmed signal at all
    else:
        assert state.cmu_corrections[CMU][1] is True
        assert f"ACV {CMU},0" in commands and commands.index(f"ACV {CMU},0") > commands.index(f"CORR? {CMU},1")
