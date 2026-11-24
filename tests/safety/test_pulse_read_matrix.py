"""Kind ``pulse_read`` x faults x positions with the global invariant v2 (blueprint v2 2.6, 4.3, 8.1 ``safety/``; WP9.4
per-recipe AC ``tests/safety -k pulse_read``: selector at rest after every fault position).

Three bodies run the **real kind** (``PulseReadKind().acquire``) on plans compiled against the committed config,
inside a transaction whose station declares the recorded selectors, on ``fefet_lab``:

- **spgu**: ``fefet.pulse_write_read`` (reference read, erase, read, program, read; Id-Vg reads; HV-SPGU source);
- **spot**: ``spgu.program_smu_read`` on one cycle (spot reads; program then erase);
- **smu**: the test-only ``generic.smu_pulse_read`` (SMU pulse source: one SMU pulses and reads the gate).

Faults {``selector_stuck`` (on PGU / open), ``spgu_no_stop`` (never / after one ignored ``SPP``), ``disconnect``,
``cleanup_failure``, ``timeout`` of the route read-back ``ERSSP?``, Ctrl-C, a buggy body asking for a route outside
the plan} x positions {``route`` (right after the first ``ERSSP`` write: the read route before ``CN``), ``pulse``
(right after the first pulse starts: ``SRP``, or the first ``PV`` of an SMU pulse), ``read`` (the first read ``XE``
after a pulse operation), ``cleanup`` (the fault is injected at ``pulse`` and the body stops there, the output still
running)}. Every case asserts the invariant: no ``ERSSP`` outside the plan's routes or a rest state reached the link, no
SPGU output beyond the pulse envelope ever started and none ran free, the cleanup ran its steps in order with
``spgu_stop`` and ``routes`` in every attempt, lock and marker are gone, and either the simulator is safe (SPGU stopped,
outputs off, every selector port open: at rest) or the fault latch is set with ``cleanup_unverified`` audited.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import PulseReadKind
from b1500_test_agent.driver.errors import DriverError, RouteNotVerified
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sim import (
    CleanupFailure,
    Disconnect,
    SelectorStuck,
    SimFault,
    SpguNoStop,
    TimeoutFault,
)
from b1500_test_agent.session import CleanupUnverified, Transaction
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order
from tests.sim.pulse_read_helpers import PROGRAM_READ, SMU_PULSE_READ, WRITE_READ, pr_harness, pr_plan
from tests.sim.selector_helpers import selector_states

pytestmark = pytest.mark.spgu

PGU = 101


class LeaveRunning(Exception):
    """Stops a body at its first pulse with the output still running (position ``cleanup``)."""


class PulseReadHook(HookTransport):
    """Fires ``route`` after the first ``ERSSP`` write, ``pulse`` after the first ``SRP`` (HV-SPGU) or ``PV`` (SMU
    pulse) and ``read`` at the first read ``XE`` after a pulse (a sweep ``WV`` or spot ``MM 1`` set it up)."""

    pulsed = False
    reading = False

    def write(self, cmd: str) -> None:
        super().write(cmd)
        if cmd.startswith("ERSSP "):
            self.fire("route")
        if cmd == "SRP" or cmd.startswith("PV "):
            self.pulsed = True
            self.fire("pulse")
        if self.pulsed and cmd.startswith(("WV ", "MM 1,")):
            self.reading = True
        if cmd == "XE" and self.reading:
            self.fire("read")

    def write_block(self, cmd: str, data: bytes) -> None:
        super().write_block(cmd, data)


BODIES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "spgu": (WRITE_READ, {}),
    "spot": (PROGRAM_READ, {"cycles": 1}),
    "smu": (SMU_PULSE_READ, {}),
}
_PLANS: dict[str, PlanRecord] = {}


def plan_of(body: str, tmp_path_factory: pytest.TempPathFactory) -> PlanRecord:
    if body not in _PLANS:
        request, params = BODIES[body]
        _PLANS[body] = pr_plan(tmp_path_factory.mktemp(f"plan-{body}"), request, **params)
    return _PLANS[body]


@dataclass(frozen=True)
class Case:
    """``inject`` at ``moment`` (``cleanup``: at ``pulse``, then the body stops); the expected exception and latch."""

    inject: Callable[[Harness], None]
    raises: type[BaseException] | None = None
    latched: bool = False


def sim(fault: SimFault) -> Callable[[Harness], None]:
    return lambda h: h.sim.inject(fault)


def interrupt(_h: Harness) -> None:
    raise KeyboardInterrupt


def stray_route(h: Harness) -> None:
    """A buggy body routes SEL1.OUT2 to the PGU, which no phase of the plan names: refused before any write."""
    assert h.tx is not None
    h.tx.apply_routes([Route(switch="SEL1", output="OUT2", state="pgu")], phase="bug")


R, P, D, X = "route", "pulse", "read", "cleanup"
POSITIONS = (R, P, D, X)
L = LeaveRunning
FAULTS = ("selector_stuck_pgu", "selector_stuck_open", "spgu_no_stop", "spgu_no_stop_once", "disconnect",
          "cleanup_failure", "timeout", "keyboard_interrupt", "envelope_violation")


def case_of(fault: str, position: str, body: str) -> Case:
    """The expected outcome of one cell (module docstring); ``spgu`` and ``spot`` use the HV-SPGU, ``smu`` does not
    (an SPGU fault changes nothing there, and its gate never leaves the SMU path until the rest phase)."""
    spgu = body != "smu"
    if fault == "selector_stuck_pgu":  # the gate's relay sticks on the PGU: never back to rest -> latched
        return Case(sim(SelectorStuck(port=0, state="pgu")), L if position == X else RouteNotVerified, latched=True)
    if fault == "selector_stuck_open":  # the relay drops open: the next route to SMU/PGU fails; rest is open
        later_route = position == R or spgu  # the smu body changes no route after the start until rest (= open)
        return Case(sim(SelectorStuck(port=0, state="open")),
                    L if position == X else (RouteNotVerified if later_route else None))
    if fault in ("spgu_no_stop", "spgu_no_stop_once"):
        never = fault == "spgu_no_stop"
        inject = sim(SpguNoStop() if never else SpguNoStop(spp_ignored=1))
        if not spgu:
            return Case(inject, L if position == X else None)
        return Case(inject, L if position == X else DriverError, latched=never)
    if fault == "disconnect":
        return Case(sim(Disconnect(after_writes=1 if position == X else 0)), L if position == X else TransportError,
                    latched=True)
    if fault == "cleanup_failure":
        count = {R: 1, P: 2, D: None, X: 1}[position]
        latched = count is None
        return Case(sim(CleanupFailure(count=count)), L if position == X else (CleanupUnverified if latched else None),
                    latched=latched)
    if fault == "timeout":  # the next route read-back hangs; the cleanup's device clear recovers
        return Case(sim(TimeoutFault(on="query:ERSSP?")), L if position == X else TransportTimeout)
    if fault == "keyboard_interrupt":
        if position == X:
            return Case(lambda h: setattr(h.hook, "raise_next", KeyboardInterrupt()), L)
        return Case(interrupt, KeyboardInterrupt)
    assert fault == "envelope_violation"
    return Case(stray_route, EnvelopeViolation)


def allowed_erssp(body: str) -> set[tuple[int, int]]:
    """(port, status) every ``ERSSP`` may carry: the plan's SEL1.OUT1 routes and every port's rest state (open)."""
    rest = {(p, 0) for p in range(4)}
    return rest | {(0, 1)} | ({(0, 2)} if body != "smu" else set())


def assert_pulse_read_invariant(h: Harness, tx: Transaction, plan: PlanRecord, body: str) -> None:
    """Global invariant v2, SPGU and selector parts (module docstring)."""
    instrument = h.sim.instrument
    if body != "smu":
        limit = plan.envelope.channels[PGU].pulse.max_abs_v_dut  # type: ignore[union-attr]
        for run in instrument.spgu_runs:
            record = run.channels[1]
            assert record.open_load_v <= limit * (1 + 1e-12), record  # nothing beyond the envelope ever started
            assert run.end_s is not None  # never free run
    else:
        assert not instrument.spgu_runs
    for record in h.log:
        if record.mnemonic == "ERSSP":  # dropped writes included: nothing unplanned reached the link
            assert tuple(int(a) for a in record.args) in allowed_erssp(body), record.command
    events = h.events()
    assert_cleanup_order(events)
    sequence = [(e.data["attempt"], e.data["step"]) for e in events if e.ev == "cleanup_step" and e.data]
    for attempt in {a for a, _ in sequence}:
        assert (attempt, "spgu_stop") in sequence and (attempt, "routes") in sequence
    latched = h.session.fault_latch.get() is not None
    assert latched == (tx.cleanup is not None and tx.cleanup.latched_fault)
    if latched:
        assert any(e.ev == "cleanup_unverified" for e in events)
    else:
        instrument.assert_safe()  # SPGU stopped (SPST? 0), every output off at 0 V, nothing pending
        assert not instrument.spgu_output_active() and selector_states(h.sim) == {0: 0, 1: 0, 2: 0, 3: 0}
    assert h.session.lock.holder() is None and not (h.state_dir / "inflight.json").exists()


def test_matrix_is_complete() -> None:
    cells = {(f, p, b) for f in FAULTS for p in POSITIONS for b in BODIES}
    assert len(cells) == 108 and all(isinstance(case_of(f, p, b), Case) for f, p, b in cells)


@pytest.mark.parametrize("body", sorted(BODIES))
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_pulse_read_kind_fault_matrix(fault: str, position: str, body: str, tmp_path: Path,
                                      tmp_path_factory: pytest.TempPathFactory) -> None:
    case = case_of(fault, position, body)
    plan = plan_of(body, tmp_path_factory)
    h = pr_harness(tmp_path, hook_type=PulseReadHook)

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
    assert_pulse_read_invariant(h, tx, plan, body)
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"


@pytest.mark.parametrize("body", sorted(BODIES))
def test_pulse_read_kind_clean_run_ends_at_rest(body: str, tmp_path: Path,
                                                tmp_path_factory: pytest.TempPathFactory) -> None:
    plan = plan_of(body, tmp_path_factory)
    h = pr_harness(tmp_path, hook_type=PulseReadHook)
    with h.transaction(envelope=plan.envelope, intent=f"safety pulse_read {body}") as tx:
        raw = PulseReadKind().acquire(tx, plan)
    assert_pulse_read_invariant(h, tx, plan, body)
    assert raw.kind_result["reads_done"] == 3 and raw.kind_result["routes"].endswith("end rest SEL1.OUT1->open")
    assert "SPP" not in [r.mnemonic for r in h.log if r.outcome == "ok"]
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
