"""Kind ``pulse_read`` schedules of WP9.5 x faults x positions with the global invariant v2 (blueprint v2 2.6, 4.3,
8.1 ``safety/``; per-recipe AC ``tests/safety -k pulse_read``).

Three more bodies run the **real kind** on small plans of the WP9.5 recipes, inside a transaction whose station
declares the recorded selectors, on ``fefet_lab`` (the WP9.4 matrix, ``test_pulse_read_matrix.py``, covers the cycle
schedule's bodies):

- **kinetics**: ``fefet.switching_kinetics`` on a 2 x 2 grid with 10 wake-up pre-cycles (a three-level burst first);
- **endurance**: ``fefet.endurance`` to 100 cycles with checkpoints 1, 10, 100 (bursts of 8 and 89 cycles between);
- **retention**: ``fefet.retention`` to 2 s per state (MM 10 hold blocks between the reads).

The faults of the WP9.4 matrix at its positions ``route``, ``pulse``, ``read`` and ``cleanup``, plus ``burst`` (the
first ``SRP`` of a three-level cycling burst) for the bodies that burst and ``hold`` (the first ``XE`` of an MM 10
retention hold) for the retention body. A burst fault behaves as a pulse fault, a hold fault as a read fault (the
expected outcomes are the WP9.4 matrix's ``case_of`` for those positions). Every case asserts the same invariant: no
``ERSSP`` outside the plan's routes or a rest state reached the link, no SPGU output beyond the pulse envelope ever
started and none ran free, the cleanup ran ``spgu_stop`` and ``routes`` in every attempt, and either the simulator is
safe (SPGU stopped, outputs off, every selector port at rest) or the fault latch is set with ``cleanup_unverified``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import PulseReadKind
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.session import Transaction
from tests.safety.test_pulse_read_matrix import (
    FAULTS,
    LeaveRunning,
    PulseReadHook,
    assert_pulse_read_invariant,
    case_of,
)
from tests.sim.pulse_read_helpers import BASE, pr_harness, pr_plan

pytestmark = pytest.mark.spgu

R, P, B, H, D, X = "route", "pulse", "burst", "hold", "read", "cleanup"

BODIES: dict[str, tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]] = {
    "kinetics": ({"recipe_id": "fefet.switching_kinetics", **BASE},
                 {"amplitudes": [3.6, 4.4], "widths": [1e-8, 1e-6], "precycles": 10}, (R, P, B, D, X)),
    "endurance": ({"recipe_id": "fefet.endurance", **BASE},
                  {"cycles": 100, "reads_per_decade": 1, "cycle_period": 1e-5}, (R, P, B, D, X)),
    "retention": ({"recipe_id": "fefet.retention", **BASE}, {"retention_time": 2.0}, (R, P, H, D, X)),
}
_PLANS: dict[str, PlanRecord] = {}

CELLS = [(f, p, b) for b, (_, _, positions) in BODIES.items() for p in positions for f in FAULTS]


class ScheduleHook(PulseReadHook):
    """WP9.4's moments plus ``burst`` (the first ``SRP`` after a three-level ``SPM``) and ``hold`` (the first ``XE``
    after an ``MM 10`` setup)."""

    three = False
    holding = False

    def write(self, cmd: str) -> None:
        super().write(cmd)
        if cmd.startswith("SPM ") and cmd.endswith(",3"):
            self.three = True
        if cmd == "SRP" and self.three:
            self.fire("burst")
        if cmd.startswith("MM 10,"):
            self.holding = True
        if cmd == "XE" and self.holding:
            self.fire("hold")


def plan_of(body: str, tmp_path_factory: pytest.TempPathFactory) -> PlanRecord:
    if body not in _PLANS:
        request, params, _ = BODIES[body]
        _PLANS[body] = pr_plan(tmp_path_factory.mktemp(f"plan-{body}"), request, **params)
    return _PLANS[body]


def test_matrix_is_complete() -> None:
    assert len(CELLS) == 9 * 5 * 3
    assert all(case_of(f, {B: P, H: D}.get(p, p), "spgu") is not None for f, p, _ in CELLS)


@pytest.mark.parametrize(("fault", "position", "body"), CELLS)
def test_pulse_read_schedule_fault_matrix(fault: str, position: str, body: str, tmp_path: Path,
                                          tmp_path_factory: pytest.TempPathFactory) -> None:
    case = case_of(fault, {B: P, H: D}.get(position, position), "spgu")
    plan = plan_of(body, tmp_path_factory)
    h = pr_harness(tmp_path, hook_type=ScheduleHook)

    def stop() -> None:
        case.inject(h)
        raise LeaveRunning

    h.at(P if position == X else position, stop if position == X else (lambda: case.inject(h)))
    raised: BaseException | None = None
    tx: Transaction | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent=f"safety pulse_read {body}") as tx:
            h.tx = tx
            PulseReadKind().acquire(tx, plan)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    assert tx is not None and tx.cleanup is not None
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_pulse_read_invariant(h, tx, plan, "spgu")
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"


@pytest.mark.parametrize("body", sorted(BODIES))
def test_pulse_read_schedule_clean_run_ends_at_rest(body: str, tmp_path: Path,
                                                    tmp_path_factory: pytest.TempPathFactory) -> None:
    plan = plan_of(body, tmp_path_factory)
    h = pr_harness(tmp_path, hook_type=ScheduleHook)
    with h.transaction(envelope=plan.envelope, intent=f"safety pulse_read {body}") as tx:
        raw = PulseReadKind().acquire(tx, plan)
    assert_pulse_read_invariant(h, tx, plan, "spgu")
    assert not raw.kind_result["stopped_early"] and raw.kind_result["routes"].endswith("end rest SEL1.OUT1->open")
    assert "SPP" not in [r.mnemonic for r in h.log if r.outcome == "ok"]
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
    sent = [r.command for r in h.log if r.outcome == "ok"]
    marker = "MM 10,3,4" if body == "retention" else "SPM 101,3"  # the hold, or the three-level cycling burst
    assert marker in sent and all(run.end_s is not None for run in h.sim.instrument.spgu_runs)
