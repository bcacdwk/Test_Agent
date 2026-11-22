"""Kind ``spgu_pulse`` pulse modes x faults x positions with the global invariant v2 (blueprint v2 2.6, 4.3, 8.1
``safety/``; WP9.3 per-recipe AC ``tests/safety -k spgu_pulse``).

Three bodies run the **real kind** (``SpguPulseKind().acquire``) on plans of the committed recipes compiled against the
committed config, inside a transaction whose station declares the recorded selectors:

- **pg**: ``spgu.pulse_train`` (4 V x 1 us x 100 at 10 kHz through SEL1.OUT1) on ``fefet_lab``;
- **alwg**: ``spgu.alwg_sequence`` (the bipolar +-4 V pattern x 100) on ``fefet_lab``;
- **measure**: ``mosfet.charge_pumping`` at 100 kHz (SMU bulk read during a 0.2 s train) on ``nmos_cv``.

Faults {``spgu_no_stop`` (never / after one ignored ``SPP``), ``spgu_load_mismatch``, ``selector_stuck`` (on PGU /
open), ``disconnect``, ``cleanup_failure`` (once / always), ``timeout`` on ``SPST?``, Ctrl-C, a buggy ``SER`` change
outside the envelope} x positions {``configure`` (the first SPGU setup write), ``after_start`` (right after ``SRP``),
``during_wait`` (the first host wait after ``SRP``: the settle of a read, or the ``SPST?`` poll), ``cleanup`` (the
fault is injected there and the body stops with the train still running)}. Every case asserts the invariant: no SPGU
output beyond the plan's pulse envelope ever started and none ran free, no ``ERSSP`` outside the plan's routes or a
rest state reached the instrument, the cleanup ran its steps in order with ``spgu_stop`` and ``routes`` in every
attempt, the lock and marker are gone, and either the simulator is safe (SPGU stopped, outputs off, every selector
port open) or the fault latch is set with ``cleanup_unverified`` audited.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import SpguPulseKind
from b1500_test_agent.driver.errors import DriverError, RouteNotVerified
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.sim import (
    CleanupFailure,
    Disconnect,
    SelectorStuck,
    SimFault,
    SpguLoadMismatch,
    SpguNoStop,
    TimeoutFault,
)
from b1500_test_agent.session import CleanupUnverified, Transaction
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order
from tests.sim.selector_helpers import selector_states
from tests.sim.spgu_pulse_helpers import ALWG, CHARGE_PUMPING, PULSE_TRAIN, compile_plan, pulse_harness

pytestmark = pytest.mark.spgu

PGU = 101


class LeaveRunning(Exception):
    """Stops a body at its first wait after ``SRP`` with the train still running (position ``cleanup``)."""


class PulseHook(HookTransport):
    """Fires ``configure`` at the first SPGU setup write (``SIM``), ``after_start`` right after ``SRP`` and
    ``during_wait`` at the first host wait after ``SRP``."""

    started = False

    def write(self, cmd: str) -> None:
        super().write(cmd)
        if cmd.startswith("SIM "):
            self.fire("configure")
        if cmd == "SRP":
            self.started = True
            self.fire("after_start")

    def write_block(self, cmd: str, data: bytes) -> None:
        super().write_block(cmd, data)

    def wait(self, seconds: float) -> None:
        if self.started:
            self.fire("during_wait")
        super().wait(seconds)


BODIES: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {
    "pg": ("fefet_lab", PULSE_TRAIN, {"count": 100}),
    "alwg": ("fefet_lab", ALWG, {}),
    "measure": ("nmos_cv", CHARGE_PUMPING, {"frequency": [1e5]}),
}
_PLANS: dict[str, PlanRecord] = {}


def plan_of(body: str, tmp_path_factory: pytest.TempPathFactory) -> PlanRecord:
    if body not in _PLANS:
        scenario, request, params = BODIES[body]
        _PLANS[body] = compile_plan(tmp_path_factory.mktemp(f"plan-{body}"), scenario, request, **params)
    return _PLANS[body]


@dataclass(frozen=True)
class Case:
    """``moment``: hook moment, or ``cleanup`` (inject at the first wait after ``SRP``, then stop the body)."""

    moment: str
    inject: Callable[[Harness], None]
    raises: type[BaseException] | None = None
    latched: bool = False


def sim(fault: SimFault) -> Callable[[Harness], None]:
    return lambda h: h.sim.inject(fault)


def interrupt(_h: Harness) -> None:
    raise KeyboardInterrupt


def smaller_load(h: Harness) -> None:
    """A buggy body lowers SER to 50 Ohm: the open-load level doubles beyond the envelope."""
    assert h.tx is not None
    h.tx.driver.set_pulse_load(PGU, 50.0)


C, S, W, X = "configure", "after_start", "during_wait", "cleanup"
POSITIONS = (C, S, W, X)
NEVER, ONCE = SpguNoStop(), SpguNoStop(spp_ignored=1)
STUCK_PGU, STUCK_OPEN = SelectorStuck(port=0, state="pgu"), SelectorStuck(port=0, state="open")
L = LeaveRunning

INJECTIONS: dict[tuple[str, str], Case] = {
    # the output never stops: the fallback SPP and the cleanup's SPPs are ignored -> latched
    ("spgu_no_stop", C): Case(C, sim(NEVER), raises=DriverError, latched=True),
    ("spgu_no_stop", S): Case(S, sim(NEVER), raises=DriverError, latched=True),
    ("spgu_no_stop", W): Case(W, sim(NEVER), raises=DriverError, latched=True),
    ("spgu_no_stop", X): Case(X, sim(NEVER), raises=L, latched=True),
    # the fallback SPP is ignored (the run fails: still active); the cleanup's SPP stops it -> verified
    ("spgu_no_stop_once", C): Case(C, sim(ONCE), raises=DriverError),
    ("spgu_no_stop_once", S): Case(S, sim(ONCE), raises=DriverError),
    ("spgu_no_stop_once", W): Case(W, sim(ONCE), raises=DriverError),
    ("spgu_no_stop_once", X): Case(X, sim(ONCE), raises=L),
    # the real load differs from SER: less reaches the pad, never more than the checked open-load level
    ("spgu_load_mismatch", C): Case(C, sim(SpguLoadMismatch(channel=PGU, load_ohm=50.0))),
    ("spgu_load_mismatch", S): Case(S, sim(SpguLoadMismatch(load_ohm=10.0))),
    ("spgu_load_mismatch", W): Case(W, sim(SpguLoadMismatch(channel=PGU, load_ohm=1e9))),
    ("spgu_load_mismatch", X): Case(X, sim(SpguLoadMismatch(load_ohm=50.0)), raises=L),
    # the gate's relay will not leave the PGU path: the rest phase fails its read-back; nothing returns it -> latched
    ("selector_stuck_pgu", C): Case(C, sim(STUCK_PGU), raises=RouteNotVerified, latched=True),
    ("selector_stuck_pgu", S): Case(S, sim(STUCK_PGU), raises=RouteNotVerified, latched=True),
    ("selector_stuck_pgu", W): Case(W, sim(STUCK_PGU), raises=RouteNotVerified, latched=True),
    ("selector_stuck_pgu", X): Case(X, sim(STUCK_PGU), raises=L, latched=True),
    # the relay drops open: the pulses reach nothing (the rest state reads back) -> verified
    ("selector_stuck_open", C): Case(C, sim(STUCK_OPEN)),
    ("selector_stuck_open", S): Case(S, sim(STUCK_OPEN)),
    ("selector_stuck_open", W): Case(W, sim(STUCK_OPEN)),
    ("selector_stuck_open", X): Case(X, sim(STUCK_OPEN), raises=L),
    # the link drops: nothing reaches the instrument any more -> latched
    ("disconnect", C): Case(C, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", S): Case(S, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", W): Case(W, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", X): Case(X, sim(Disconnect(after_writes=1)), raises=L, latched=True),
    # DZ/CL time out once (the retry verifies) or always (latched)
    ("cleanup_failure", C): Case(C, sim(CleanupFailure(count=1))),
    ("cleanup_failure", S): Case(S, sim(CleanupFailure(count=2))),
    ("cleanup_failure", W): Case(W, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", X): Case(X, sim(CleanupFailure(count=1)), raises=L),
    # SPST? never answers: the poll (or the check after a read) times out; the cleanup's device clear stops it
    ("timeout", C): Case(C, sim(TimeoutFault(on="query:SPST?")), raises=TransportTimeout),
    ("timeout", S): Case(S, sim(TimeoutFault(on="query:SPST?")), raises=TransportTimeout),
    ("timeout", W): Case(W, sim(TimeoutFault(on="query:SPST?")), raises=TransportTimeout),
    ("timeout", X): Case(X, sim(TimeoutFault(on="query:SPST?")), raises=L),
    # Ctrl-C while the output runs (during the cleanup: the body's exception is already in flight)
    ("keyboard_interrupt", C): Case(C, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", S): Case(S, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", W): Case(W, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", X): Case(X, lambda h: setattr(h.hook, "raise_next", KeyboardInterrupt()), raises=L),
    # a buggy body asks for SER 50 Ohm (doubling the open-load level): refused before the write
    ("envelope_violation", C): Case(C, smaller_load, raises=EnvelopeViolation),
    ("envelope_violation", S): Case(S, smaller_load, raises=EnvelopeViolation),
    ("envelope_violation", W): Case(W, smaller_load, raises=EnvelopeViolation),
    ("envelope_violation", X): Case(X, smaller_load, raises=EnvelopeViolation),
}
FAULTS = sorted({fault for fault, _ in INJECTIONS})
ALLOWED_ERSSP = {(0, 0), (1, 0), (2, 0), (3, 0), (0, 2)}
"""(port, status) every ``ERSSP`` may carry: the plan's SEL1.OUT1 -> PGU and every port's rest state (open)."""


def test_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}


def assert_pulse_invariant(h: Harness, tx: Transaction, plan: PlanRecord) -> None:
    """Global invariant v2, SPGU and selector parts (module docstring)."""
    instrument = h.sim.instrument
    limit = plan.envelope.channels[PGU].pulse.max_abs_v_dut  # type: ignore[union-attr]
    for run in instrument.spgu_runs:
        assert set(run.channels) <= {1}, run
        record = run.channels[1]
        assert record.open_load_v <= limit * (1 + 1e-12), record  # nothing beyond the envelope ever started
        assert record.delivered_v <= record.open_load_v * (1 + 1e-12), record
        assert run.end_s is not None  # never free run
    for record in h.log:
        if record.mnemonic == "ERSSP":  # dropped writes included: nothing unplanned reached the link
            assert tuple(int(a) for a in record.args) in ALLOWED_ERSSP, record.command
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


@pytest.mark.parametrize("body", sorted(BODIES))
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_spgu_pulse_kind_fault_matrix(fault: str, position: str, body: str, tmp_path: Path,
                                      tmp_path_factory: pytest.TempPathFactory) -> None:
    case = INJECTIONS[(fault, position)]
    plan = plan_of(body, tmp_path_factory)
    h = pulse_harness(tmp_path, BODIES[body][0], hook_type=PulseHook)

    def stop() -> None:
        case.inject(h)
        raise LeaveRunning

    h.at(W if case.moment == X else case.moment, stop if case.moment == X else (lambda: case.inject(h)))
    raised: BaseException | None = None
    tx: Transaction | None = None
    try:
        with h.transaction(envelope=plan.envelope, intent=f"safety spgu_pulse {body}") as tx:
            h.tx = tx
            SpguPulseKind().acquire(tx, plan)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    assert tx is not None and tx.cleanup is not None
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_pulse_invariant(h, tx, plan)
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"


@pytest.mark.parametrize("body", sorted(BODIES))
def test_spgu_pulse_kind_clean_run_ends_at_rest_without_spp(body: str, tmp_path: Path,
                                                            tmp_path_factory: pytest.TempPathFactory) -> None:
    plan = plan_of(body, tmp_path_factory)
    h = pulse_harness(tmp_path, BODIES[body][0], hook_type=PulseHook)
    with h.transaction(envelope=plan.envelope, intent=f"safety spgu_pulse {body}") as tx:
        raw = SpguPulseKind().acquire(tx, plan)
    assert_pulse_invariant(h, tx, plan)
    assert raw.kind_result["spp_fallbacks"] == 0 and "SPP" not in [r.mnemonic for r in h.log if r.outcome == "ok"]
    assert tx.cleanup is not None and tx.cleanup.steps[0].detail == "SPST? 0: no SPGU output active"
    assert len(raw.blocks) == (1 if body == "measure" else 0)
