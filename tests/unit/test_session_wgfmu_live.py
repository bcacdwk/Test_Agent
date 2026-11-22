"""Live WGFMU facts in the session on the simulator (blueprint v2 2.8 R-WG-01 "bound channels within channel_ids()
(pre)", 7.1 ``--wgfmu-session``, ATV-14/16; WP10.2): a transaction's pre-execute snapshot of a WGFMU plan reads the
library's channel ids through a short library session while the FLEX exclusive lock is released, then relocks; the
read-only session check opens the library with the FLEX link closed. The visa path (the real ``VisaTransport`` and
``WgfmuDll`` over the fake ABI) is ``tests/visa_loop/test_wgfmu_visa.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.sim import BusLockedFault, WgfmuDllMissing, WgfmuErrorFault
from b1500_test_agent.models.station import Settings
from b1500_test_agent.session import InstrumentBusy, Session
from b1500_test_agent.session.wgfmu_live import check_session, read_channels
from b1500_test_agent.transport.audit import MemoryAuditSink
from b1500_test_agent.transport.base import BusLocked, unwrap
from b1500_test_agent.transport.factory import make_bus
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.sim.helpers import load_scenario

pytestmark = pytest.mark.wgfmu


def lab_session(tmp_path: Path, *faults: object) -> tuple[Session, MemoryAuditSink]:
    scenario = load_scenario("lab_station")
    settings = Settings.model_validate({"sim": {"scenario": scenario.name}})
    sink = MemoryAuditSink()
    session = Session(settings, lambda: make_bus(settings, sink, scenario=scenario, faults=list(faults),
                                                 state_dir=tmp_path / "state"),
                      sink, state_dir=tmp_path / "state")
    return session, sink


def events(sink: MemoryAuditSink, *kinds: str) -> list[AuditEvent]:
    return [e for e in sink.events if e.ev in kinds]


def test_a_wgfmu_snapshot_reads_the_channels_with_the_flex_lock_released(tmp_path: Path) -> None:
    session, sink = lab_session(tmp_path)
    with session.transaction(intent="pre-execute", envelope=None, run=None) as tx:
        live = tx.snapshot(wgfmu=True)
        assert unwrap(session.transport).locked  # relocked for the rest of the transaction
        sim = unwrap(session.bus.wgfmu)
        assert sim.session is None  # the library session is closed again
    assert live.wgfmu_channels == [201, 202] and live.wgfmu_library is None  # the simulated library has no DLL
    order = [(e.ev, e.cmd) for e in events(sink, "bus_unlock", "bus_lock", "wgfmu_call")]
    assert order == [("bus_lock", None), ("bus_unlock", None), ("wgfmu_call", "WGFMU_openSession"),
                     ("wgfmu_call", "WGFMU_getChannelIds"), ("wgfmu_call", "WGFMU_closeSession"),
                     ("bus_lock", None), ("bus_unlock", None)]
    library_calls = events(sink, "wgfmu_call")
    assert {e.tx for e in library_calls} == {tx.tx_id} and {e.intent for e in library_calls} == {"pre-execute"}
    assert session.last_live == live


def test_a_snapshot_without_wgfmu_roles_opens_no_library_session(tmp_path: Path) -> None:
    session, sink = lab_session(tmp_path)
    with session.transaction(intent="pre-execute", envelope=None, run=None) as tx:
        live = tx.snapshot()
    assert live.wgfmu_channels is None and events(sink, "wgfmu_call") == []
    assert session.snapshot().wgfmu_library is None  # sim: no DLL probe


def test_the_library_refuses_while_the_flex_link_holds_the_exclusive_lock(tmp_path: Path) -> None:
    """Why the snapshot releases the lock (ATV-14): the simulated library answers like the lab's VISA would."""
    session, _ = lab_session(tmp_path)
    with session.transaction(intent="locked", envelope=None, run=None), pytest.raises(WgfmuError) as caught:
        read_channels(session.bus.wgfmu, session.transport.resource)
    assert caught.value.rc == api.COMMUNICATION_ERROR and caught.value.code == "transport_error"


def test_without_a_library_the_channels_stay_unread_and_audited(tmp_path: Path) -> None:
    session, sink = lab_session(tmp_path, WgfmuDllMissing())
    assert session.bus.wgfmu is None
    with session.transaction(intent="pre-execute", envelope=None, run=None) as tx:
        live = tx.snapshot(wgfmu=True)
    assert live.wgfmu_channels is None
    marks = [e for e in sink.events if e.ev == "checkpoint" and (e.data or {}).get("label") == "wgfmu_channels_unread"]
    assert len(marks) == 1 and "no WGFMU instrument library" in (marks[0].error or "")
    assert not events(sink, "bus_unlock")[:-1]  # no lock release for a library that is not there


def test_a_library_failure_leaves_the_channels_unread_and_the_session_closed(tmp_path: Path) -> None:
    session, sink = lab_session(tmp_path, WgfmuErrorFault(fn="channel_ids", code=api.COMMUNICATION_ERROR))
    with session.transaction(intent="pre-execute", envelope=None, run=None) as tx:
        live = tx.snapshot(wgfmu=True)
        assert unwrap(session.transport).locked
    assert live.wgfmu_channels is None and unwrap(session.bus.wgfmu).session is None
    marks = [e for e in sink.events if e.ev == "checkpoint" and (e.data or {}).get("label") == "wgfmu_channels_unread"]
    assert len(marks) == 1 and "channel_ids" in (marks[0].error or "")
    assert [e.cmd for e in events(sink, "wgfmu_call")] == ["WGFMU_openSession", "WGFMU_getChannelIds",
                                                          "WGFMU_closeSession"]


def test_a_refused_relock_ends_the_transaction(tmp_path: Path) -> None:
    session, _ = lab_session(tmp_path)
    with pytest.raises(BusLocked), session.transaction(intent="pre-execute", envelope=None, run=None) as tx:
        session.bus.flex.inner.inject(BusLockedFault())  # another client grabs the bus meanwhile
        tx.snapshot(wgfmu=True)
    assert not unwrap(session.transport).locked


def test_the_read_only_session_check_runs_with_the_flex_link_closed(tmp_path: Path) -> None:
    session, sink = lab_session(tmp_path)
    result = session.check_wgfmu_session("probe: wgfmu session")
    assert result.ok and result.channels == [201, 202] and result.status is not None
    assert result.status[0] == api.STATUS_IDLE and not session.bus_open
    calls = events(sink, "wgfmu_call")
    assert [e.cmd for e in calls] == ["WGFMU_openSession", "WGFMU_getChannelIds", "WGFMU_getStatus",
                                      "WGFMU_closeSession"]
    assert len({e.tx for e in calls}) == 1 and calls[0].intent == "probe: wgfmu session"
    assert events(sink, "bus_open", "bus_lock") == []  # the FLEX link was never opened for it
    assert (tmp_path / "state" / "sim" / "lab_station.state.json").is_file()  # state saved for other processes


def test_the_session_check_waits_for_the_instrument_lock(tmp_path: Path) -> None:
    session, _ = lab_session(tmp_path)
    other, _ = lab_session(tmp_path)
    with other.transaction(intent="busy elsewhere", envelope=None, run=None), pytest.raises(InstrumentBusy):
        session.check_wgfmu_session("probe", lock_timeout_s=0.05)


def test_check_session_reports_failures_and_still_closes() -> None:
    class Flaky:
        def __init__(self, fail: str) -> None:
            self.fail, self.closed = fail, False

        def _maybe(self, name: str) -> None:
            if name == self.fail:
                raise WgfmuError(api.UNIDENTIFIED_ERROR, f"{name}: broken", function=name)

        def open_session(self, address: str) -> None:
            self._maybe("open_session")

        def channel_ids(self) -> list[int]:
            self._maybe("channel_ids")
            return [101]

        def status(self) -> tuple[int, float, float]:
            self._maybe("status")
            return api.STATUS_IDLE, 0.0, 0.0

        def close_session(self) -> None:
            self.closed = True
            self._maybe("close_session")

    opened = Flaky("open_session")
    assert check_session(opened, "R").error is not None and not opened.closed  # nothing to close
    for name in ("channel_ids", "status"):
        flaky = Flaky(name)
        result = check_session(flaky, "R")
        assert result.error is not None and result.error.function == name and flaky.closed and not result.ok
    closing = check_session(Flaky("close_session"), "R")
    assert closing.channels == [101] and closing.error is None and closing.close_error is not None
    assert not closing.ok
