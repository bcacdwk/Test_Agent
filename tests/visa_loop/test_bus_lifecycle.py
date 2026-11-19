"""Bus lifecycle on backend visa through ``B1500Service`` (blueprint v2 2.4, decision 7; ATV-13; v2 4.3
``bus_locked``).

Per transaction and per status snapshot the session opens the VISA session, takes the exclusive lock, unlocks and
closes, so nothing is held between calls; ``visa.session: process`` (the ATV-13 fallback) keeps the session open and
still locks per transaction. A bus held by another client (EasyEXPERT, the ``bus_locked`` fault) makes a status
``busy`` and a run ``refused``/``busy`` with nothing sent, and a ``safe_shutdown`` that cannot reach the instrument
latches the fault. The ATV-13 measurement reads the ``bus_*`` audit durations (visa-loop numbers only; the GPIB
numbers are a bring-up item, blueprint 7.6).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime

import pytest

from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.sim import BusLockedFault
from b1500_test_agent.service import B1500Admin
from tests.visa_loop.helpers import MEASUREMENT_CASES, VisaWorld, per_transaction_overhead_ms, run_case

IDVG = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "mosfet.idvg")
BUS_EVENTS = ("bus_open", "bus_lock", "bus_unlock", "bus_close")


def snapshot_bus_events(world: VisaWorld) -> dict[str, list[str]]:
    """``tx`` -> bus events of the status snapshots in the daily audit."""
    groups: dict[str, list[str]] = defaultdict(list)
    for event in world.daily_events():
        if event.ev in BUS_EVENTS and event.intent == "snapshot" and event.tx:
            groups[event.tx].append(event.ev)
    return groups


def test_each_status_snapshot_opens_locks_unlocks_and_closes_the_bus(world: VisaWorld) -> None:
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    for _ in range(3):
        status = service.station_status()
        assert status.ok and status.live == "fresh" and status.backend == "visa"
        assert bus.lock_is_free() and all(s.closed for s in bus.sessions)  # nothing held between calls
    groups = snapshot_bus_events(world)
    assert len(groups) == 3 and all(events == list(BUS_EVENTS) for events in groups.values())
    opens = [e for e in world.daily_events() if e.ev == "session_open"]
    assert len(opens) == 1 and opens[0].data is not None and opens[0].data["bus"] == "transaction"
    assert bus.stats.opens == bus.stats.closes == 3


def test_two_processes_alternate_without_ever_waiting_for_each_other(world: VisaWorld) -> None:
    """In-process stand-in for the MCP server and the CLI (two ``LoopBus`` objects = two VISA libraries, one
    instrument): with a lock timeout of 0 any lock still held by the other would fail the call at once."""
    world.set_visa(lock_timeout_ms=0)
    server_bus, cli_bus = world.bus("nmos_basic"), world.bus("nmos_basic")
    server = world.service(server_bus, adapter="mcp")
    cli = world.service(cli_bus, lock_timeout_s=0.0)
    assert run_case(server, IDVG).ok  # the MCP server measures, then sits idle
    status = cli.station_status()
    assert status.ok and status.live == "fresh" and status.outputs_on == []
    assert server.station_status().ok
    assert run_case(cli, IDVG).ok
    assert server.station_status().ok
    assert server_bus.lock_is_free()
    assert server_bus.stats.loads >= 1 and cli_bus.stats.loads >= 1  # each saw the other's saved instrument state
    assert {s.closed for s in server_bus.sessions + cli_bus.sessions} == {True}


def test_a_client_holding_the_bus_makes_status_busy_and_refuses_runs_without_sending(world: VisaWorld) -> None:
    """EasyEXPERT (or v1's MCP server, which kept its session and lock for its whole life) holds the bus."""
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    validation = service.validate_plan(recipe_id=IDVG["recipe_id"], **IDVG["request"])
    before = len(bus.instrument.command_log)
    with bus.foreign_lock():
        status = service.station_status()
        assert (status.status, status.error_code, status.live) == ("busy", "instrument_busy", "unavailable")
        assert "500 ms" in (status.live_error or "")
        result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert (result.ok, result.status, result.outcome, result.error_code) == (
        False, "busy", "refused", "instrument_busy")
    assert any("another client holds the instrument bus" in step for step in result.next_steps)
    assert len(bus.instrument.command_log) == before  # not a single command reached the instrument
    session = service.executor.session(service.config.get())
    assert session.fault_latch.get() is None and session.inflight() is None and session.lock.holder() is None
    assert run_case(service, IDVG).ok  # free again: the next run works


def test_bus_locked_fault_refuses_the_run_keeps_the_audit_trail_and_latches_an_unreachable_shutdown(
        world: VisaWorld) -> None:
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    validation = service.validate_plan(recipe_id=IDVG["recipe_id"], **IDVG["request"])
    bus.inject(BusLockedFault(count=2))
    before = len(bus.instrument.command_log)
    status = service.station_status()
    assert (status.status, status.error_code) == ("busy", "instrument_busy")
    result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert (result.status, result.outcome, result.error_code, result.cleanup_verified) == (
        "busy", "refused", "instrument_busy", None)
    assert len(bus.instrument.command_log) == before and bus.stats.lock_refusals == 2
    events = world.run_events(result.run_id)
    assert [e.ev for e in events if e.ev.startswith(("bus_", "lock_"))] == [
        "lock_acquired", "bus_open", "bus_lock", "bus_close", "lock_released"]
    refused = next(e for e in events if e.ev == "bus_lock")
    assert refused.error is not None and refused.error.startswith("BusLocked")
    manifest = (world.run_dir(result.run_id) / "manifest.json").read_text(encoding="utf-8")
    assert '"outcome": "refused"' in manifest and '"error_code": "instrument_busy"' in manifest

    bus.inject(BusLockedFault())  # the other client keeps the bus: the shutdown cannot verify anything
    shutdown = service.safe_shutdown(reason="operator stop")
    assert (shutdown.ok, shutdown.status, shutdown.error_code) == (False, "fault", "cleanup_unverified")
    assert "BusLocked" in shutdown.cleanup.steps[0].detail
    assert len(bus.instrument.command_log) == before
    bus.clear_faults()
    cleared = B1500Admin(service).fault_clear(by="owner")  # the human's command, exercised in a test
    assert cleared.ok and cleared.cleared and cleared.cleanup.verified == "lop"
    assert run_case(service, IDVG).ok


def test_process_mode_keeps_the_session_but_still_releases_the_lock_between_calls(world: VisaWorld) -> None:
    world.set_visa(session="process")
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    for _ in range(3):
        assert service.station_status().ok
        assert bus.lock_is_free()  # another client may lock between calls
    assert run_case(service, IDVG).ok
    assert bus.stats.opens == 1 and bus.stats.locks == bus.stats.unlocks == 4 and bus.stats.closes == 0
    session = service.executor.session(service.config.get())
    assert session.bus_mode == "process" and session.bus_open
    opens = [e for e in world.daily_events() if e.ev == "session_open"]
    assert len(opens) == 1 and opens[0].data["bus"] == "process"
    with bus.foreign_lock():
        assert service.station_status().status == "busy"
    assert session.bus_open  # a refused lock does not tear down a healthy process session
    assert service.station_status().ok
    service.close()
    assert bus.stats.closes == 1 and not session.bus_open and all(s.closed for s in bus.sessions)


def test_process_mode_reopens_a_session_that_died_between_calls(world: VisaWorld) -> None:
    world.set_visa(session="process")
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    assert service.station_status().ok
    bus.sessions[-1].close()  # power cycle or cable pulled while idle: the VISA session is invalid
    assert service.station_status().ok
    assert bus.stats.opens == 2 and not bus.sessions[-1].closed


@pytest.mark.wall_clock
@pytest.mark.parametrize("mode", ["transaction", "process"])
def test_atv13_per_transaction_bus_overhead_on_visa_loop(world: VisaWorld, mode: str,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    """ATV-13 on visa-loop: open + lock + unlock + close per snapshot from the ``bus_*`` audit durations. The fake
    has no GPIB latency, so this proves the measurement path and the < 100 ms budget of the software side; the GPIB
    figure is measured at bring-up L0/L1 (blueprint 7.6 item 1)."""
    world.set_visa(session=mode)
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    for _ in range(20):
        assert service.station_status().ok
    overhead = sorted(per_transaction_overhead_ms(world.daily_events()))
    assert len(overhead) == 20
    p95 = overhead[18]
    with capsys.disabled():
        print(f"\nATV-13 visa-loop {mode}: median {statistics.median(overhead):.3f} ms, p95 {p95:.3f} ms, "
              f"max {overhead[-1]:.3f} ms per snapshot (n=20)")
    assert p95 < 100.0


def test_overhead_helper_sums_the_bus_events_per_transaction() -> None:
    """Guards the ATV-13 arithmetic: only ``bus_*`` durations count, grouped by transaction id."""

    def event(ev: str, tx: str, ms: float) -> AuditEvent:
        return AuditEvent(ts=datetime.now(UTC), ev=ev, backend="visa", tx=tx, dur_ms=ms)

    events = [event("bus_open", "T1", 1.0), event("bus_lock", "T1", 2.0), event("query", "T1", 50.0),
              event("bus_unlock", "T1", 0.5), event("bus_close", "T1", 0.5), event("bus_open", "T2", 4.0)]
    assert sorted(per_transaction_overhead_ms(events)) == [4.0, 4.0]
