"""Transaction safety over the real ``VisaTransport`` (blueprint 2.4 cleanup, v2 2.4 bus lifecycle, 8.1 safety).

The v1 safety matrix runs on ``SimTransport``; here the same staircase body (``tests.safety.helpers.acquire``) runs
through a ``Session`` on backend visa over the visa-loop, so the VISA error translation (VI_ERROR_TMO ->
``TransportTimeout``, VI_ERROR_CONN_LOST -> ``TransportError``, a refused lock -> ``BusLocked``) is what feeds the
cleanup: ``AB`` for a hung measurement, device clear and one retry after a failed step, ``LOP?`` verification, the
fault latch when nothing can be verified. Every case asserts the global invariant and that the bus is closed and
its lock free afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from b1500_test_agent.models.sim import (
    BusLockedFault,
    CleanupFailure,
    Disconnect,
    ErrxFault,
    IgnoreDz,
    SimFault,
    TimeoutFault,
)
from b1500_test_agent.models.station import Settings
from b1500_test_agent.session import CleanupUnverified, Session
from b1500_test_agent.transport.audit import MemoryAuditSink
from b1500_test_agent.transport.base import BusLocked, TransportError, TransportTimeout
from b1500_test_agent.transport.factory import make_bus
from tests.safety.helpers import Harness, MemoryRun, acquire, assert_global_invariant
from tests.sim.helpers import load_scenario, noiseless
from tests.visa_loop.loop import LoopBus


class InjectHook:
    """The hook ``acquire`` fires (``configure`` after the drain bias, before the sweep): injects ``faults`` then."""

    def __init__(self, bus: LoopBus) -> None:
        self.bus = bus
        self.at_configure: list[SimFault] = []

    def fire(self, moment: str) -> None:
        if moment == "configure":
            for fault in self.at_configure:
                self.bus.inject(fault)


def visa_harness(state_dir: Path, bus: LoopBus) -> Harness:
    settings = Settings.model_validate({"backend": "visa", "visa": {"timeout_ms": 1000, "lock_timeout_ms": 200}})
    daily = MemoryAuditSink()
    session = Session(settings, lambda: make_bus(settings, daily, rm_factory=bus.manager), daily,
                      state_dir=state_dir)
    return Harness(session=session, sim=SimpleNamespace(instrument=bus.instrument),  # type: ignore[arg-type]
                   hook=InjectHook(bus), daily=daily, run=MemoryRun(), state_dir=state_dir)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Case:
    """``fault`` is active from the start, or from the configure moment with ``at_configure``."""

    fault: SimFault | None
    raises: type[BaseException] | None
    latched: bool
    check: Callable[[Harness, LoopBus], None] | None = None
    at_configure: bool = False


def device_clear_ran(h: Harness, bus: LoopBus) -> None:
    assert bus.stats.clears >= 1
    assert any(e.ev == "device_clear" for e in h.events())


def drained_305(h: Harness, bus: LoopBus) -> None:
    assert any(e.ev == "instrument_error" and e.data and e.data["code"] == 305 for e in h.events())
    assert any(e.ev == "query" and e.resp and e.resp.startswith('+305,"') for e in h.events())  # the lab form


def aborted(h: Harness, bus: LoopBus) -> None:
    abort = [r for r in bus.instrument.command_log if r.mnemonic == "AB" and r.outcome == "ok"]
    assert abort, "the hung measurement was not aborted"


CASES: dict[str, Case] = {
    "no_fault": Case(None, None, False),
    "errx_after_xe": Case(ErrxFault(after_cmd="XE", code=305), None, False, drained_305),
    "xe_hangs": Case(TimeoutFault(on="XE"), TransportTimeout, False, aborted),
    "read_times_out": Case(TimeoutFault(on="read"), TransportTimeout, False, aborted, at_configure=True),
    "baseline_read_times_out": Case(TimeoutFault(on="read"), TransportTimeout, False),
    "cleanup_fails_once": Case(CleanupFailure(count=1), None, False, device_clear_ran),
    "cleanup_always_fails": Case(CleanupFailure(), CleanupUnverified, True, device_clear_ran),
    "link_lost": Case(Disconnect(after_writes=3), TransportError, True),
    "stuck_output": Case(IgnoreDz(), CleanupUnverified, True),
}


@pytest.mark.parametrize("name", list(CASES))
def test_visa_transaction_cleans_up_or_latches(name: str, tmp_path: Path) -> None:
    case = CASES[name]
    bus = LoopBus(tmp_path / "bus", noiseless(load_scenario("nmos_basic")))
    h = visa_harness(tmp_path / "state", bus)
    if case.fault is not None and case.at_configure:
        h.hook.at_configure.append(case.fault)  # type: ignore[attr-defined]
    elif case.fault is not None:
        bus.inject(case.fault)
    raised: BaseException | None = None
    tx = h.transaction()
    try:
        with tx:
            acquire(tx, h.hook)  # type: ignore[arg-type]
    except BaseException as exc:  # noqa: BLE001 - every outcome is asserted below
        raised = exc
    assert (None if raised is None else type(raised)) is case.raises, repr(raised)
    assert_global_invariant(h)
    assert tx.cleanup is not None and tx.cleanup.latched_fault == case.latched
    assert (h.session.fault_latch.get() is not None) == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "lop"  # LOP? on the hardware path
        assert all(state == "00" for state in tx.cleanup.outputs_after.values())
    if case.check is not None:
        case.check(h, bus)
    assert not h.session.bus_open and all(s.closed for s in bus.sessions) and bus.lock_is_free()
    bus_events = [e.ev for e in h.events() if e.ev.startswith("bus_")]
    assert bus_events[:2] == ["bus_open", "bus_lock"] and bus_events[-2:] == ["bus_unlock", "bus_close"]


def test_bus_locked_refuses_the_transaction_before_any_command(tmp_path: Path) -> None:
    bus = LoopBus(tmp_path / "bus", noiseless(load_scenario("nmos_basic")))
    h = visa_harness(tmp_path / "state", bus)
    bus.inject(BusLockedFault(count=1))
    tx = h.transaction()
    with pytest.raises(BusLocked), tx:
        pytest.fail("the body must not run")  # pragma: no cover
    assert bus.instrument.command_log == [] and tx.cleanup is None
    assert h.session.fault_latch.get() is None and h.session.lock.holder() is None
    assert not (h.state_dir / "inflight.json").exists()
    assert [e.ev for e in h.events() if e.ev.startswith(("bus_", "lock_"))] == [
        "lock_acquired", "bus_open", "bus_lock", "bus_close", "lock_released"]
    assert all(s.closed for s in bus.sessions) and bus.lock_is_free()
    h.run = MemoryRun()
    with h.transaction() as tx:  # the other client let go: the next transaction runs normally
        acquire(tx, h.hook)  # type: ignore[arg-type]
    assert_global_invariant(h)
    assert tx.cleanup is not None and tx.cleanup.verified == "lop"
