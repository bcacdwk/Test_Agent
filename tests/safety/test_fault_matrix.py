"""Fault matrix with the global invariant (blueprint 3, 8.1 ``safety/``).

Faults {compliance_at, errx, timeout, garbage_data, interlock_open, disconnect, oscillation, ignore_dz,
cleanup_failure, bus_locked, KeyboardInterrupt, parser exception, EnvelopeViolation} x positions {configure, after
XE, during read, during cleanup}. The position is where the fault takes effect; ``INJECTIONS`` says when it is
injected (an instrument-side fault that acts on the measurement is injected during configure, before ``XE``
computes the data) and with which parameters. ``bus_locked`` (v2 4.3) inside a transaction must change nothing (the
transaction already holds the bus); its refusal of the next transaction, a snapshot, a shutdown and a recovery is in
``test_bus_locked.py``. Simulator faults use ``SimTransport.inject``; host-side faults are raised by the hook
or monkeypatched into the driver. A few combinations cannot act any more (data faults injected for the cleanup
phase); they still run, because the invariant must hold for every case.

Every case asserts the global invariant (``helpers.assert_global_invariant``) plus the expected exception, the
expected fault-latch outcome and the error-queue capture.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops import core as driver_module  # parse_data/parse_errx are looked up here
from b1500_test_agent.models.sim import (
    BusLockedFault,
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
from tests.safety.helpers import ENVELOPE, GATE, Harness, acquire, assert_global_invariant, make_harness

POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
          "ignore_dz", "cleanup_failure", "bus_locked", "keyboard_interrupt", "parser_exception",
          "envelope_violation")
ERRX_CODE = 305


@dataclass(frozen=True)
class Case:
    """``moment``: when the injection runs (hook moment or ``cleanup`` = end of the body); ``inject``: what it does;
    ``raises``: exact exception type leaving the ``with`` block (``None`` = none); ``latched``: fault latch set."""

    moment: str
    inject: Callable[[Harness, pytest.MonkeyPatch], None]
    raises: type[BaseException] | None = None
    latched: bool = False


def sim(fault: SimFault) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    return lambda h, _mp: h.sim.inject(fault)


def raise_now(make: Callable[[Harness], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    def action(h: Harness, _mp: pytest.MonkeyPatch) -> None:
        raise make(h)

    return action


def arm(make: Callable[[Harness], BaseException]) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    """Raise once on the next transport call (the first cleanup step)."""

    def action(h: Harness, _mp: pytest.MonkeyPatch) -> None:
        h.hook.raise_next = make(h)

    return action


def buggy_50v(h: Harness, _mp: pytest.MonkeyPatch) -> None:
    """A deliberately buggy kind asks for 50 V on the gate (envelope 2 V): the guard must refuse before writing."""
    assert h.tx is not None
    h.tx.driver.force_v(GATE, 50.0, icomp=1e-6)


def violation(_h: Harness) -> BaseException:
    try:
        OutputGuard(ENVELOPE).check(GATE, "V", 50.0, 1e-6)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("the guard accepted 50 V")


def parse_error(_h: Harness) -> BaseException:
    return FlexParseError("injected parser failure", raw="NAI+?")


def bad_parse_data(h: Harness, mp: pytest.MonkeyPatch) -> None:
    def broken(raw: str, fmt: int) -> list[object]:
        raise FlexParseError("injected parser failure on measurement data", raw=raw)

    mp.setattr(driver_module, "parse_data", broken)


def bad_parse_errx_once(h: Harness, mp: pytest.MonkeyPatch) -> None:
    original = driver_module.parse_errx
    calls = {"n": 0}

    def flaky(text: str) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlexParseError("injected ERRX? parser failure", raw=text)
        return original(text)

    mp.setattr(driver_module, "parse_errx", flaky)


def interrupt(_h: Harness) -> BaseException:
    return KeyboardInterrupt()


C, A, R, X = "configure", "after_xe", "during_read", "cleanup"

INJECTIONS: dict[tuple[str, str], Case] = {
    # compliance at the first, a middle and the last step (auto abort fills the rest with dummy data)
    ("compliance_at", "configure"): Case(C, sim(ComplianceAt(step=0, ch=3))),
    ("compliance_at", "after_xe"): Case(C, sim(ComplianceAt(step=5, ch=3))),
    ("compliance_at", "during_read"): Case(C, sim(ComplianceAt(step=10, ch=3))),
    ("compliance_at", "during_cleanup"): Case(X, sim(ComplianceAt(step=0, ch=3))),
    # an error queued after WV, after XE, during cleanup after DZ / CL; drained into the cleanup report
    ("errx", "configure"): Case(C, sim(ErrxFault(after_cmd="WV", code=ERRX_CODE))),
    ("errx", "after_xe"): Case(C, sim(ErrxFault(after_cmd="XE", code=ERRX_CODE))),
    ("errx", "during_read"): Case(R, sim(ErrxFault(after_cmd="DZ", code=ERRX_CODE))),
    ("errx", "during_cleanup"): Case(X, sim(ErrxFault(after_cmd="CL", code=ERRX_CODE))),
    # WV hangs (later commands held), XE never completes, the data read times out, DZ hangs
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="WV")), raises=TransportTimeout),
    ("timeout", "after_xe"): Case(C, sim(TimeoutFault(on="XE")), raises=TransportTimeout),
    ("timeout", "during_read"): Case(C, sim(TimeoutFault(on="read")), raises=TransportTimeout),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    # unparsable element at the first / middle / last step
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError),
    ("garbage_data", "after_xe"): Case(C, sim(GarbageData(at_step=5)), raises=FlexParseError),
    ("garbage_data", "during_read"): Case(C, sim(GarbageData(at_step=10)), raises=FlexParseError),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    # the interlock opens (no effect below 42 V, STB bit 3 only)
    ("interlock_open", "configure"): Case(C, sim(InterlockOpen())),
    ("interlock_open", "after_xe"): Case(C, sim(InterlockOpen(at_step=5))),
    ("interlock_open", "during_read"): Case(R, sim(InterlockOpen())),
    ("interlock_open", "during_cleanup"): Case(X, sim(InterlockOpen())),
    # the link drops: before WV, right after XE, before the read, after the first cleanup write
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # oscillation at the first / middle / last step
    ("oscillation", "configure"): Case(C, sim(Oscillation(steps=[0]))),
    ("oscillation", "after_xe"): Case(C, sim(Oscillation(steps=[5]))),
    ("oscillation", "during_read"): Case(C, sim(Oscillation(steps=[10]))),
    ("oscillation", "during_cleanup"): Case(X, sim(Oscillation())),
    # stuck outputs: verification must fail and latch
    ("ignore_dz", "configure"): Case(C, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "after_xe"): Case(A, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_read"): Case(R, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, sim(IgnoreDz()), raises=CleanupUnverified, latched=True),
    # DZ/CL writes time out: once (retry succeeds), twice (retry succeeds), always (latch)
    ("cleanup_failure", "configure"): Case(C, sim(CleanupFailure(count=1))),
    ("cleanup_failure", "after_xe"): Case(A, sim(CleanupFailure(count=2))),
    ("cleanup_failure", "during_read"): Case(R, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    # another client wants the bus while this transaction holds it: nothing changes for this transaction
    ("bus_locked", "configure"): Case(C, sim(BusLockedFault())),
    ("bus_locked", "after_xe"): Case(A, sim(BusLockedFault())),
    ("bus_locked", "during_read"): Case(R, sim(BusLockedFault())),
    ("bus_locked", "during_cleanup"): Case(X, sim(BusLockedFault())),
    # host side: Ctrl-C mid-configure, between XE and the read, in the read, inside cleanup (deferred, re-raised)
    ("keyboard_interrupt", "configure"): Case(C, raise_now(interrupt), raises=KeyboardInterrupt),
    ("keyboard_interrupt", "after_xe"): Case(A, raise_now(interrupt), raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_read"): Case(R, raise_now(interrupt), raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm(interrupt), raises=KeyboardInterrupt),
    ("parser_exception", "configure"): Case(C, raise_now(parse_error), raises=FlexParseError),
    ("parser_exception", "after_xe"): Case(A, raise_now(parse_error), raises=FlexParseError),
    ("parser_exception", "during_read"): Case("setup", bad_parse_data, raises=FlexParseError),
    ("parser_exception", "during_cleanup"): Case(X, bad_parse_errx_once),
    # a buggy kind requests 50 V: refused by the guard before any byte is written
    ("envelope_violation", "configure"): Case(C, buggy_50v, raises=EnvelopeViolation),
    ("envelope_violation", "after_xe"): Case(A, buggy_50v, raises=EnvelopeViolation),
    ("envelope_violation", "during_read"): Case(R, buggy_50v, raises=EnvelopeViolation),
    ("envelope_violation", "during_cleanup"): Case(X, arm(violation)),
}


def test_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_fault_matrix(fault: str, position: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = INJECTIONS[(fault, position)]
    h = make_harness(tmp_path)
    if case.moment == "setup":
        case.inject(h, monkeypatch)
    elif case.moment != X:
        h.at(case.moment, lambda: case.inject(h, monkeypatch))
    raised: BaseException | None = None
    try:
        with h.transaction() as tx:
            h.tx = tx
            acquire(tx, h.hook)
            if case.moment == X:
                case.inject(h, monkeypatch)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc

    assert_global_invariant(h)
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert tx.cleanup.latched_fault == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())
    if fault == "errx":
        assert [e.code for e in tx.cleanup.errors] == [ERRX_CODE]
        assert any(e.ev == "instrument_error" and e.data and e.data["code"] == ERRX_CODE for e in h.events())
    if case.latched:
        assert any(e.ev == "fault" for e in h.daily.events)
    if isinstance(raised, EnvelopeViolation):
        assert any(e.ev == "envelope_violation" for e in h.events())


def test_retry_path_is_audited_with_device_clear(tmp_path: Path) -> None:
    """``cleanup_failure(count=1)``: DZ times out once, so attempt 1 fails, a device clear runs and attempt 2
    verifies; DZ and CL of attempt 2 are what the invariant sees."""
    h = make_harness(tmp_path)
    with h.transaction() as tx:
        acquire(tx, h.hook)
        h.sim.inject(CleanupFailure(count=1))
    assert_global_invariant(h)
    steps = [(s.attempt, s.step, s.ok) for s in tx.cleanup.steps]  # type: ignore[union-attr]
    assert steps[:2] == [(1, "spgu_stop", True), (1, "zero", False)]  # SPST? 0: no SPP (v2 cleanup step 2)
    assert (2, "device_clear", True) in steps
    assert steps[-1] == (2, "verify", True)
    assert any(r.mnemonic == "<device_clear>" for r in h.log)
