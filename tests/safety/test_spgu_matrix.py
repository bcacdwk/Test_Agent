"""SPGU fault matrix with the global invariant v2 (blueprint v2 2.6, 4.3, 8.1 ``safety/``; WP9.1).

A test-local SPGU body runs inside a transaction on the lab mainframe (a FeFET gate on SPGU 101): ``CN``, guarded PG
setup (hook ``configure``), ``SPUPD``, ``SRP`` (hook ``after_start``), then ``SPST?`` polling with host waits (hook
``during_wait`` at the first wait) until the count ends. Faults {``spgu_no_stop`` (never / after one ignored
``SPP``), ``spgu_load_mismatch``, ``disconnect``, ``cleanup_failure``, ``timeout`` on ``SPST?``, Ctrl-C, a buggy load
change outside the envelope} x positions {configure, after start, during the wait, during cleanup (the body leaves a
long output running)}. Every case asserts the invariant: no SPGU output beyond the envelope ever started (open-load
level, delivered level), the cleanup ran its steps in order with ``spgu_stop``, the lock and marker are gone, and
either the simulator is safe (SPGU stopped, every output off at 0 V) or the fault latch is set with
``cleanup_unverified``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.driver.errors import SpguStillActive
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.sim import (
    CleanupFailure,
    Disconnect,
    SimFault,
    SpguLoadMismatch,
    SpguNoStop,
    TimeoutFault,
)
from b1500_test_agent.models.sources import pulse_envelope
from b1500_test_agent.models.spgu import SpguChannel, SpguPulseProgram, SpguSource
from b1500_test_agent.session import CleanupUnverified, Transaction
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order, make_harness
from tests.sim.spgu_helpers import fefet_on_spgu

pytestmark = pytest.mark.spgu

PGU = 101


def program(*, count: int | None = 100, duration: float | None = None) -> SpguPulseProgram:
    source = SpguSource(width_s=1e-6, base_v=0.0, peak_v=4.0)
    return SpguPulseProgram(period_s=1e-4, count=count, duration_s=duration,
                            channels={PGU: SpguChannel(load_ohm=1e6, sources={1: source})})


def envelope_of(prog: SpguPulseProgram) -> CompiledEnvelope:
    pulse = pulse_envelope(prog.trains()[PGU], source_ohm=50.0)
    return CompiledEnvelope(channels={PGU: ChannelEnvelope(role="gate", max_abs_v=pulse.max_abs_v_dut,
                                                           max_abs_i=None, function="pgu", pulse=pulse)})


LONG = program(count=None, duration=10.0)
ENVELOPE = envelope_of(LONG)  # admits both the 100-pulse train and the 10 s train (same level, width, duty)


class SpguHook(HookTransport):
    """Fires ``after_start`` right after ``SRP`` and ``during_wait`` at the first host wait."""

    def write(self, cmd: str) -> None:
        super().write(cmd)
        if cmd == "SRP":
            self.fire("after_start")

    def wait(self, seconds: float) -> None:
        self.fire("during_wait")
        super().wait(seconds)


def spgu_harness(state_dir: Path) -> Harness:
    return make_harness(state_dir, fefet_on_spgu(), hook_type=SpguHook)


def body(tx: Transaction, h: Harness, *, leave_running: bool = False) -> None:
    """The SPGU body (module docstring); ``leave_running`` starts the 10 s train and returns without waiting."""
    driver = tx.driver
    driver.enable([PGU])
    driver.configure_pulse(LONG if leave_running else program())
    h.hook.fire("configure")
    driver.apply_pulse_setup()
    driver.start_pulses()
    if leave_running:
        return
    driver.wait_pulses_stopped(timeout_s=0.1, poll_s=0.01, check=tx.check_abort)
    tx.mark("pulses done")


@dataclass(frozen=True)
class Case:
    """``moment``: hook moment, or ``cleanup`` (inject after a body that leaves a 10 s output running)."""

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


POSITIONS = ("configure", "after_start", "during_wait", "during_cleanup")
C, S, W, X = "configure", "after_start", "during_wait", "cleanup"
NEVER, ONCE = SpguNoStop(), SpguNoStop(spp_ignored=1)

INJECTIONS: dict[tuple[str, str], Case] = {
    # the output never stops: the wait times out, both SPPs are ignored -> latched
    ("spgu_no_stop", "configure"): Case(C, sim(NEVER), raises=SpguStillActive, latched=True),
    ("spgu_no_stop", "after_start"): Case(S, sim(NEVER), raises=SpguStillActive, latched=True),
    ("spgu_no_stop", "during_wait"): Case(W, sim(NEVER), raises=SpguStillActive, latched=True),
    ("spgu_no_stop", "during_cleanup"): Case(X, sim(NEVER), raises=CleanupUnverified, latched=True),
    # the first SPP is ignored: the cleanup's retry SPP stops it -> verified
    ("spgu_no_stop_once", "configure"): Case(C, sim(ONCE), raises=SpguStillActive),
    ("spgu_no_stop_once", "after_start"): Case(S, sim(ONCE), raises=SpguStillActive),
    ("spgu_no_stop_once", "during_wait"): Case(W, sim(ONCE), raises=SpguStillActive),
    ("spgu_no_stop_once", "during_cleanup"): Case(X, sim(ONCE)),
    # the real load differs from SER: less reaches the gate, never more than the checked open-load level
    ("spgu_load_mismatch", "configure"): Case(C, sim(SpguLoadMismatch(channel=PGU, load_ohm=50.0))),
    ("spgu_load_mismatch", "after_start"): Case(S, sim(SpguLoadMismatch(load_ohm=10.0))),
    ("spgu_load_mismatch", "during_wait"): Case(W, sim(SpguLoadMismatch(channel=PGU, load_ohm=1e9))),
    ("spgu_load_mismatch", "during_cleanup"): Case(X, sim(SpguLoadMismatch(load_ohm=50.0))),
    # the link drops: nothing reaches the instrument any more -> latched
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", "after_start"): Case(S, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", "during_wait"): Case(W, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # DZ/CL time out once (the retry verifies) or always (latched)
    ("cleanup_failure", "configure"): Case(C, sim(CleanupFailure(count=1))),
    ("cleanup_failure", "after_start"): Case(S, sim(CleanupFailure(count=2))),
    ("cleanup_failure", "during_wait"): Case(W, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(CleanupFailure(count=1))),
    # SPST? never answers: the poll times out; the cleanup's device clear stops the output
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="query:SPST?")), raises=TransportTimeout),
    ("timeout", "after_start"): Case(S, sim(TimeoutFault(on="query:SPST?")), raises=TransportTimeout),
    ("timeout", "during_wait"): Case(W, sim(TimeoutFault(on="query:SPST?")), raises=TransportTimeout),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="query:SPST?"))),
    # Ctrl-C while the output runs
    ("keyboard_interrupt", "configure"): Case(C, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", "after_start"): Case(S, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_wait"): Case(W, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_cleanup"): Case(X, lambda h: setattr(h.hook, "raise_next", KeyboardInterrupt()),
                                                   raises=KeyboardInterrupt),
    # a buggy body asks for SER 50 Ohm (doubling): refused before the write
    ("envelope_violation", "configure"): Case(C, smaller_load, raises=EnvelopeViolation),
    ("envelope_violation", "after_start"): Case(S, smaller_load, raises=EnvelopeViolation),
    ("envelope_violation", "during_wait"): Case(W, smaller_load, raises=EnvelopeViolation),
    ("envelope_violation", "during_cleanup"): Case(X, smaller_load, raises=EnvelopeViolation),
}
FAULTS = sorted({fault for fault, _ in INJECTIONS})


def test_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}


def assert_spgu_invariant(h: Harness, tx: Transaction) -> None:
    """Global invariant v2, SPGU part (module docstring)."""
    instrument = h.sim.instrument
    limit = ENVELOPE.channels[PGU].pulse.max_abs_v_dut  # type: ignore[union-attr]
    for run in instrument.spgu_runs:
        assert set(run.channels) <= {1}, run
        record = run.channels[1]
        assert record.open_load_v <= limit * (1 + 1e-12), record  # nothing beyond the envelope ever started
        assert record.delivered_v <= record.open_load_v * (1 + 1e-12), record
        assert run.end_s is not None  # never free run
    events = h.events()
    assert_cleanup_order(events)
    sequence = [(e.data["attempt"], e.data["step"]) for e in events if e.ev == "cleanup_step" and e.data]
    for attempt in {a for a, _ in sequence}:
        assert (attempt, "spgu_stop") in sequence  # the lab mainframe has an SPGU: step 2 in every attempt
    latched = h.session.fault_latch.get() is not None
    assert latched == (tx.cleanup is not None and tx.cleanup.latched_fault)
    if latched:
        assert any(e.ev == "cleanup_unverified" for e in events)
    else:
        instrument.assert_safe()  # SPGU stopped (SPST? 0), every output off at 0 V, nothing pending
        assert not instrument.spgu_output_active()
    assert h.session.lock.holder() is None and not (h.state_dir / "inflight.json").exists()


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_spgu_fault_matrix(fault: str, position: str, tmp_path: Path) -> None:
    case = INJECTIONS[(fault, position)]
    h = spgu_harness(tmp_path)
    if case.moment != X:
        h.at(case.moment, lambda: case.inject(h))
    raised: BaseException | None = None
    tx: Transaction | None = None
    try:
        with h.transaction(envelope=ENVELOPE, intent="safety spgu") as tx:
            h.tx = tx
            body(tx, h, leave_running=case.moment == X)
            if case.moment == X:
                case.inject(h)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    assert tx is not None and tx.cleanup is not None
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_spgu_invariant(h, tx)
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"


def test_a_clean_run_sends_the_preview_then_stops_nothing() -> None:
    """Without a fault the train ends by its count: the cleanup reads SPST? 0 and sends no SPP; the FeFET gate was
    pulsed (4 V x 1 us x 100 at an open load)."""
    import tempfile

    h = spgu_harness(Path(tempfile.mkdtemp()))
    with h.transaction(envelope=ENVELOPE, intent="safety spgu") as tx:
        body(tx, h)
    assert_spgu_invariant(h, tx)
    log = [r.mnemonic for r in h.log if r.outcome == "ok"]
    assert "SRP" in log and "SPP" not in log and log[log.index("SRP"):].count("SPST?") >= 2
    assert h.sim.instrument.circuit.devices["dut"].p > 0.9  # type: ignore[attr-defined]
    assert tx.cleanup is not None and tx.cleanup.steps[0].detail == "SPST? 0: no SPGU output active"
