"""The transaction's WGFMU phase on backend visa (blueprint v2 0 #7, 2.6; ATV-14, ATV-17; WP10.3), through the real
``VisaTransport`` (visa-loop) and the real ``WgfmuDll`` over the fake ABI (``LoopWgfmuLibrary``: ``SimWgfmu`` on the
loop's instrument; its online calls fail while any VISA session holds the exclusive lock, as the lab's VISA would).

- ATV-14: the library runs while the FLEX VISA session is open without its exclusive lock, and the transaction locks
  again afterwards; the fallback ``settings.wgfmu.flex_during_phase: close`` closes the FLEX session instead.
- Another client taking the bus during the phase: the relock is refused, so the cleanup cannot verify and latches.
- Hardware verification of the WGFMU part (``verified: lop``): it rests on step 3 succeeding (the library cannot
  read the RSU relays back), so a stuck relay or a library that cannot open its session leaves the cleanup
  unverified, whatever the simulated state behind the loop shows.
- ``safe_shutdown`` opens a library session only to abort and disconnect, and only when the DLL is loadable.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from b1500_test_agent.driver.wgfmu import WgfmuSafeStateFailed
from b1500_test_agent.models.sim import WgfmuDisconnectFails, WgfmuDllMissing
from b1500_test_agent.service import B1500Service
from b1500_test_agent.session import Session, Transaction
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.safety.wgfmu_helpers import BOTTOM, ENVELOPE, R_WG_OHM, SMU, TOP, program, wg_scenario
from tests.visa_loop.helpers import VisaWorld
from tests.visa_loop.loop import LoopBus, LoopWgfmuLibrary
from tests.wgfmu_abi.pe_builder import X86, write_dll

pytestmark = pytest.mark.wgfmu


@pytest.fixture
def lock_state(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool, bool]]:
    """``(C function, exclusive VISA lock free, every FLEX session closed)`` at each library call."""
    seen: list[tuple[str, bool, bool]] = []
    original = LoopWgfmuLibrary.dispatch

    def dispatch(self: LoopWgfmuLibrary, name: str, args: tuple[Any, ...]) -> int:
        seen.append((name, self.bus.lock_is_free(), all(s.closed for s in self.bus.sessions)))
        return original(self, name, args)

    monkeypatch.setattr(LoopWgfmuLibrary, "dispatch", dispatch)
    return seen


def setup(world: VisaWorld, **wgfmu: Any) -> tuple[LoopBus, B1500Service, Session]:
    if wgfmu:
        path = world.local / "settings.yaml"
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
        settings["wgfmu"].update(wgfmu)
        world.write_local("settings.yaml", settings)
    bus = LoopBus(world.bus_dir, wg_scenario())
    service = world.service(bus)
    return bus, service, service.executor.session(service.config.get())


def phase_body(session: Session, bus: LoopBus, *, flex_io: bool = True):
    with session.transaction(intent="visa wgfmu", envelope=ENVELOPE, run=None) as tx:
        tx.driver.enable([SMU])
        tx.driver.force_v(SMU, 0.5, icomp=1e-3)
        with tx.wgfmu_phase(flex_io=flex_io) as wg:
            wg.load(program())
            block = wg.run()
            assert bus.lock_is_free()  # inside the phase the FLEX session holds no lock
        assert not bus.lock_is_free()  # relocked by this transaction's FLEX session
        held = [s for s in bus.sessions if not s.closed and s.holds_lock]
        assert len(held) == 1
    return tx, block


def wgfmu_only(tx: Transaction) -> None:
    with tx.wgfmu_phase() as wg:
        wg.load(program())
        wg.run()


def test_atv14_the_library_works_with_the_flex_lock_released_and_the_transaction_relocks(
        world: VisaWorld, lock_state: list[tuple[str, bool, bool]]) -> None:
    bus, _, session = setup(world)
    tx, block = phase_body(session, bus)
    assert block.status == "completed" and min(block.traces[BOTTOM].value) == pytest.approx(-3.0 / R_WG_OHM,
                                                                                            rel=0.02)
    assert lock_state and all(free and not closed for _, free, closed in lock_state)  # open session, no lock
    assert lock_state[0][0] == "WGFMU_openSession" and lock_state[-1][0] == "WGFMU_closeSession"
    assert bus.stats.wgfmu_loads == 1 and bus.stats.locks == 2 and bus.stats.unlocks == 2  # phase + final release
    assert tx.cleanup is not None and tx.cleanup.verified == "lop" and not tx.cleanup.latched_fault
    assert "wgfmu" not in [s.step for s in tx.cleanup.steps]
    assert tx.cleanup.switches_after["RSU201.OUT"] == "open" and bus.lock_is_free()
    bus.sync_in()
    assert all(not s.connected and not s.running for s in bus.instrument.state.wgfmu.values())


def test_atv14_fallback_closes_the_flex_session_for_a_wgfmu_only_phase(
        world: VisaWorld, lock_state: list[tuple[str, bool, bool]]) -> None:
    bus, _, session = setup(world, flex_during_phase="close")
    with session.transaction(intent="visa wgfmu close", envelope=ENVELOPE, run=None) as tx:
        with tx.wgfmu_phase() as wg:
            wg.load(program())
            assert wg.run().status == "completed"
        assert not bus.lock_is_free()
    assert lock_state and all(free and closed for _, free, closed in lock_state)  # every FLEX session closed
    assert bus.stats.opens == 2 and tx.wgfmu_link.phases == ["closed"]
    assert tx.cleanup is not None and tx.cleanup.verified == "lop"


def test_atv14_fallback_keeps_the_flex_session_for_a_combined_phase(
        world: VisaWorld, lock_state: list[tuple[str, bool, bool]]) -> None:
    bus, _, session = setup(world, flex_during_phase="close")
    tx, _ = phase_body(session, bus, flex_io=True)
    assert all(free and not closed for _, free, closed in lock_state)
    assert bus.stats.opens == 1 and tx.wgfmu_link.phases == ["unlocked (flex_io)"]


def test_another_client_taking_the_bus_during_the_phase_latches_the_fault(world: VisaWorld,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """FLEX relocked or fault latched: a foreign client takes the exclusive lock while the phase has released it."""
    world.set_visa(lock_timeout_ms=50)
    bus, _, session = setup(world)
    foreign = bus.visa_lock()
    original = LoopWgfmuLibrary.dispatch

    def dispatch(self: LoopWgfmuLibrary, name: str, args: tuple[Any, ...]) -> int:
        rc = original(self, name, args)
        if name == "WGFMU_execute" and not foreign.is_locked:
            foreign.acquire(timeout=1.0)  # EasyEXPERT grabs the B1500A while the sequencer runs
        return rc

    monkeypatch.setattr(LoopWgfmuLibrary, "dispatch", dispatch)
    try:
        with pytest.raises(WgfmuError) as caught, session.transaction(intent="grabbed", envelope=ENVELOPE,
                                                                     run=None) as tx:
            wgfmu_only(tx)
    finally:
        if foreign.is_locked:
            foreign.release()
    assert tx.cleanup is not None and tx.cleanup.latched_fault
    assert session.fault_latch.get() is not None
    assert caught.value.rc == api.COMMUNICATION_ERROR and tx.wgfmu_link.pending  # the poll saw the foreign lock
    assert any("flex relocked FAILED" in s.detail for s in tx.cleanup.steps if s.step == "wgfmu")


def test_hardware_verification_needs_every_disconnect(world: VisaWorld) -> None:
    bus, _, session = setup(world)
    bus.inject(WgfmuDisconnectFails(channels=[TOP]))
    with pytest.raises(WgfmuSafeStateFailed), session.transaction(intent="stuck", envelope=ENVELOPE, run=None) as tx:
        wgfmu_only(tx)
    assert tx.cleanup is not None and tx.cleanup.verified == "unverified" and tx.cleanup.latched_fault
    verify = [s for s in tx.cleanup.steps if s.step == "verify"]
    assert verify and all("WGFMU safe state not confirmed" in s.detail for s in verify)


def test_a_relay_that_opens_on_the_retry_verifies_on_hardware(world: VisaWorld) -> None:
    bus, _, session = setup(world)
    bus.inject(WgfmuDisconnectFails(channels=[TOP], count=1))
    with pytest.raises(WgfmuSafeStateFailed), session.transaction(intent="once", envelope=ENVELOPE, run=None) as tx:
        wgfmu_only(tx)
    assert tx.cleanup is not None and tx.cleanup.verified == "lop" and not tx.cleanup.latched_fault
    verify = next(s for s in tx.cleanup.steps if s.step == "verify")
    assert "every channel disconnected, session closed, FLEX relocked" in verify.detail


def test_safe_shutdown_aborts_and_disconnects_through_its_own_library_session(
        world: VisaWorld, lock_state: list[tuple[str, bool, bool]]) -> None:
    _, service, _ = setup(world)
    result = service.safe_shutdown(reason="operator stop")
    assert result.ok and result.cleanup is not None and result.cleanup.verified == "lop"
    names = [name for name, _, _ in lock_state]
    assert names[0] == "WGFMU_openSession" and names[-1] == "WGFMU_closeSession"
    assert "WGFMU_connect" not in names and "WGFMU_execute" not in names and "WGFMU_addVectors" not in names
    assert names.count("WGFMU_disconnect") == 2 and "WGFMU_abort" in names and "WGFMU_initialize" in names
    assert all(free for _, free, _ in lock_state)


def test_safe_shutdown_on_hardware_cannot_confirm_a_wgfmu_whose_session_fails(world: VisaWorld) -> None:
    bus, service, _ = setup(world)
    bus.inject(WgfmuDllMissing())
    result = service.safe_shutdown(reason="operator stop")
    assert not result.ok and result.cleanup is not None and result.cleanup.verified == "unverified"
    assert any("open_session FAILED" in s.detail for s in result.cleanup.steps if s.step == "wgfmu")


def test_safe_shutdown_skips_a_library_that_is_not_loadable(world: VisaWorld, tmp_path) -> None:
    bus, service, _ = setup(world, library=write_dll(tmp_path / "x86" / "wgfmu.dll", machine=X86))
    result = service.safe_shutdown(reason="operator stop")
    assert result.ok and result.cleanup is not None and "wgfmu" not in [s.step for s in result.cleanup.steps]
    assert bus.stats.wgfmu_loads == 0

