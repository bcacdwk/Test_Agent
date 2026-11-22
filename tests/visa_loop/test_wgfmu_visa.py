"""The WGFMU library on backend visa (blueprint v2 2.8 R-WG-01 live, 7.1 ``doctor --probe --wgfmu-session``, ATV-14,
ATV-15, ATV-16; WP10.2), through the real ``VisaTransport`` (visa-loop) and the real ``WgfmuDll`` over the fake ABI
(``LoopBus.wgfmu_library``: the probe reads the world's synthetic x64 DLL with the platform injected as Windows, the
loaded "library" is the ctypes-shaped fake backed by ``SimWgfmu`` on the loop's instrument).

- ``b1500 doctor --probe --wgfmu-session``: the FLEX part, then the DLL probe, then the library's own session with the
  FLEX link closed (``open -> channel_ids -> status -> close``); read-only by construction; failures are lines.
- A transaction's pre-execute snapshot of a WGFMU plan: the DLL probe, the channel ids and the RSU states (rest path
  accepted by the library, WP10.3) read while the FLEX exclusive lock is released, then R-WG-01 (pre) on that
  snapshot.
"""

from __future__ import annotations

import pytest
import yaml

from b1500_test_agent.models.audit import BUS_EVENTS, TRANSPORT_EVENTS
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.models.sim import WgfmuErrorFault
from b1500_test_agent.service import B1500Admin, B1500Service
from b1500_test_agent.service.probe import _Probe
from b1500_test_agent.session.wgfmu_live import SessionCheck, read_channels
from b1500_test_agent.transport.readonly import is_query
from b1500_test_agent.transport.sim.state import WgfmuChannelState
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.adapters.test_cli_bootstrap import plain
from tests.unit import rules_factory_v2 as v2
from tests.unit.rules_factory import engine
from tests.visa_loop.helpers import VisaWorld
from tests.visa_loop.loop import DEFAULT_RESOURCE, LoopBus, LoopWgfmuLibrary
from tests.visa_loop.test_probe import FLEX_PART
from tests.wgfmu_abi.pe_builder import X86, write_dll

pytestmark = pytest.mark.wgfmu

SESSION_LINES = [*FLEX_PART[:-1], "wgfmu session", "fault latch"]
SESSION_CALLS = ["WGFMU_openSession", "WGFMU_getChannelIds", "WGFMU_getStatus", "WGFMU_closeSession"]
"""The audited protocol calls of the session check (``open_session``, ``channel_ids``, ``status``, close)."""
SESSION_C_CALLS = ["WGFMU_openSession", "WGFMU_getChannelIdSize", "WGFMU_getChannelIds", "WGFMU_getStatus",
                   "WGFMU_closeSession"]
"""The C functions behind them."""


def probe(world: VisaWorld, bus: LoopBus, **kwargs: object) -> ProbeReport:
    return B1500Admin(world.service(bus)).probe(**kwargs)  # type: ignore[arg-type]


def line(report: ProbeReport, name: str):
    return next(c for c in report.checks if c.name == name)


@pytest.fixture
def flex_state_at_library_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """``(C function, every FLEX VISA session closed and the exclusive lock free)`` at each library call."""
    seen: list[tuple[str, bool]] = []
    original = LoopWgfmuLibrary.dispatch

    def dispatch(self: LoopWgfmuLibrary, name: str, args: tuple) -> int:
        seen.append((name, all(s.closed for s in self.bus.sessions) and self.bus.lock_is_free()))
        return original(self, name, args)

    monkeypatch.setattr(LoopWgfmuLibrary, "dispatch", dispatch)
    return seen


# -- doctor --probe --wgfmu-session ---------------------------------------------------------------------------------


def test_the_session_check_passes_with_the_flex_link_closed_and_only_reads(
        world: VisaWorld, flex_state_at_library_calls: list[tuple[str, bool]]) -> None:
    bus = world.bus("lab_station")
    before = bus.instrument.export_state().model_dump(mode="json")
    report = probe(world, bus, wgfmu_session=True)
    assert report.ok and [c.name for c in report.checks] == SESSION_LINES, report.checks
    assert all(c.status in ("PASS", "INFO") for c in report.checks), report.checks
    session = line(report, "wgfmu session")
    assert session.status == "PASS" and "channels 201, 202" in session.detail and "status idle" in session.detail
    assert "FLEX link closed" in session.detail
    assert report.wgfmu_channels == [201, 202] and report.wgfmu_library is not None
    assert report.wgfmu_library.loadable and bus.stats.wgfmu_loads == 1
    # the library ran only while no FLEX session was open, and only these four calls
    assert flex_state_at_library_calls == [(name, True) for name in SESSION_C_CALLS]
    events = world.daily_events()
    library = [e for e in events if e.ev == "wgfmu_call"]
    assert [e.cmd for e in library] == SESSION_CALLS and all(e.data["rc"] == 0 for e in library)
    assert {e.intent for e in library} == {"probe: wgfmu session"} and len({e.tx for e in library}) == 1
    assert all(e.backend == "visa" for e in library)
    flex_io = [e for e in events if e.ev in TRANSPORT_EVENTS]
    assert flex_io and all(e.ev == "query" and is_query(e.cmd or "") for e in flex_io)
    lifecycle = [e.ev for e in events if e.ev in BUS_EVENTS]
    assert lifecycle == ["bus_open", "bus_lock", "bus_unlock", "bus_close"]  # one FLEX session, before the library
    bus.sync_in()
    after = bus.instrument.export_state().model_dump(mode="json")["wgfmu"]
    initial = WgfmuChannelState().model_dump(mode="json")  # read-only: every channel as after power-on
    assert before["wgfmu"] == {} and all(state == initial for state in after.values()), after
    assert not bus.instrument.source_commands() and bus.lock_is_free()
    stored = ProbeReport.model_validate_json((world.root / report.record).read_text(encoding="utf-8"))
    assert stored.wgfmu_channels == [201, 202] and stored.wgfmu_library == report.wgfmu_library


def test_the_cli_runs_the_session_check_only_with_the_probe(world: VisaWorld) -> None:
    from typer.testing import CliRunner

    from b1500_test_agent.adapters.cli import app
    from b1500_test_agent.adapters.cli import core as cli_core

    bus = world.bus("lab_station")
    original = cli_core.make_service
    cli_core.make_service = lambda: world.service(bus)
    try:
        runner = CliRunner()
        result = runner.invoke(app, ["doctor", "--probe", "--wgfmu-session"])
        assert result.exit_code == 0, result.output
        assert "PASS  wgfmu library" in result.stdout and "PASS  wgfmu session" in result.stdout
        alone = runner.invoke(app, ["doctor", "--wgfmu-session"])
        assert alone.exit_code == 2 and "--wgfmu-session is part of the probe" in plain(alone.output)
    finally:
        cli_core.make_service = original
    assert bus.stats.wgfmu_loads == 1


def test_a_32_bit_library_fails_before_anything_is_loaded(world: VisaWorld, tmp_path) -> None:
    settings = yaml.safe_load((world.local / "settings.yaml").read_text(encoding="utf-8"))
    settings["wgfmu"]["library"] = write_dll(tmp_path / "SysWOW64" / "wgfmu.dll", machine=X86)
    world.write_local("settings.yaml", settings)
    bus = world.bus("lab_station")
    report = probe(world, bus, wgfmu_session=True)
    assert not report.ok and report.error_code == "instrument_error"
    library, session = line(report, "wgfmu library"), line(report, "wgfmu session")
    assert library.status == "FAIL" and "install library >= A.03.00" in library.detail
    assert session.status == "FAIL" and "not loadable" in session.detail
    assert any("A.03.00" in step for step in report.next_steps)
    assert bus.stats.wgfmu_loads == 0 and [e for e in world.daily_events() if e.ev == "wgfmu_call"] == []
    assert line(report, "identity").status == "PASS"  # the FLEX part is unaffected


def test_a_library_session_refused_by_another_visa_client(world: VisaWorld) -> None:
    """The library's own VISA session is refused (another client holds the B1500A): FAIL, with the step to end it."""
    bus = world.bus("lab_station")
    bus.inject(WgfmuErrorFault(fn="open_session", code=api.COMMUNICATION_ERROR))
    report = probe(world, bus, wgfmu_session=True)
    session = line(report, "wgfmu session")
    assert session.status == "FAIL" and "open_session" in session.detail
    assert report.error_code == "transport_error" and any("EasyEXPERT" in s for s in report.next_steps)
    calls = [e.cmd for e in world.daily_events() if e.ev == "wgfmu_call"]
    assert calls == ["WGFMU_openSession"]  # nothing to close after a failed open


def test_a_failure_after_the_open_still_closes_the_library_session(world: VisaWorld) -> None:
    bus = world.bus("lab_station")
    bus.inject(WgfmuErrorFault(fn="status", code=3015))
    report = probe(world, bus, wgfmu_session=True)
    session = line(report, "wgfmu session")
    assert session.status == "FAIL" and "3015" in session.detail and report.error_code == "instrument_error"
    calls = [e.cmd for e in world.daily_events() if e.ev == "wgfmu_call"]
    assert calls == SESSION_CALLS
    assert bus.instrument.wgfmu_unit.session is None


def test_a_station_without_a_wgfmu_opens_no_library_session(world: VisaWorld) -> None:
    station = yaml.safe_load((world.local / "station.yaml").read_text(encoding="utf-8"))
    station["modules"] = [m for m in station["modules"] if m["type"] != "WGFMU"]
    station["switches"] = [s for s in station["switches"] if s["kind"] != "rsu"]
    world.write_local("station.yaml", station)
    for rel in ("pinmaps/fecap-wgfmu.yaml",):  # the only pin map wired to the RSUs
        (world.local / rel).unlink()
    from tests.sim.helpers import load_scenario

    scenario = load_scenario("lab_station")
    data = scenario.model_dump(mode="json")
    data["slots"] = [s for s in data["slots"] if s["slot"] != 2]
    bus = LoopBus(world.bus_dir, type(scenario).model_validate(data))
    report = probe(world, bus, wgfmu_session=True)
    assert line(report, "wgfmu library").status == "INFO" and line(report, "wgfmu session").status == "INFO"
    assert report.ok and bus.stats.wgfmu_loads == 0


def test_the_session_check_is_not_run_when_the_flex_part_failed(world: VisaWorld) -> None:
    world.set_visa(lock_timeout_ms=50)
    bus = world.bus("lab_station")
    with bus.foreign_lock():
        report = probe(world, bus, wgfmu_session=True)
    assert line(report, "bus").status == "FAIL" and line(report, "wgfmu session").status == "FAIL"
    assert "not run" in line(report, "wgfmu session").detail and bus.stats.wgfmu_loads == 0


@pytest.mark.parametrize(("result", "status", "fragment"), [
    (SessionCheck(channels=[201, 202], status=(api.STATUS_IDLE, 0.0, 0.0)), "PASS", "status idle"),
    (SessionCheck(channels=[201], status=(api.STATUS_IDLE, 0.0, 0.0)), "FAIL", "declares 202 it does not"),
    (SessionCheck(channels=[201, 202, 301, 302], status=(api.STATUS_COMPLETED, 1.0, 1.0)), "WARN",
     "installed but not in"),
    (SessionCheck(channels=[201, 202], status=(api.STATUS_RUNNING, 0.5, 2.0)), "FAIL", "sequencer is running"),
    (SessionCheck(channels=[201, 202], status=(api.STATUS_IDLE, 0.0, 0.0),
                  close_error=WgfmuError(api.UNIDENTIFIED_ERROR, "close_session: broken", function="close_session")),
     "FAIL", "closing the session failed"),
])
def test_session_verdicts(world: VisaWorld, result: SessionCheck, status: str, fragment: str) -> None:
    service = world.service(world.bus("lab_station"))
    checker = _Probe(service.config.get(), DEFAULT_RESOURCE)
    got, detail, _ = checker._session_verdict(result, DEFAULT_RESOURCE)
    assert got == status and fragment in detail, detail


# -- R-WG-01 live: the pre-execute snapshot of a WGFMU plan ----------------------------------------------------------


def pre_execute_live(service: B1500Service):
    session = service.executor.session(service.config.get())
    with session.transaction(intent="pre-execute", envelope=None, run=None) as tx:
        return tx.snapshot(wgfmu=True)


def wg01(live) -> list[tuple[str, str]]:
    cfg, ctx = v2.wgfmu(backend="visa", live=live)
    report = engine(cfg).evaluate(ctx, "pre_execute")
    return [(f.severity, f.message) for f in report.findings if f.rule_id == "R-WG-01"]


def test_the_pre_execute_snapshot_reads_the_library_and_r_wg_01_passes(
        world: VisaWorld, flex_state_at_library_calls: list[tuple[str, bool]]) -> None:
    bus = world.bus("lab_station")
    live = pre_execute_live(world.service(bus))
    assert live.backend == "visa" and live.wgfmu_channels == [201, 202]
    assert live.wgfmu_library is not None and live.wgfmu_library.loadable and live.wgfmu_library.machine == "x64"
    # the FLEX session stayed open but released its exclusive lock for the library, then took it again; each declared
    # RSU's channel is put on its rest path, which the library accepting is the RSU reading (WP10.3)
    assert flex_state_at_library_calls == [(name, False) for name in (
        "WGFMU_openSession", "WGFMU_getChannelIdSize", "WGFMU_getChannelIds", "WGFMU_disconnect", "WGFMU_disconnect",
        "WGFMU_closeSession")]
    assert live.switch_states is not None
    assert {k: v for k, v in live.switch_states.items() if k.startswith("RSU")} == {"RSU201.OUT": "open",
                                                                                   "RSU202.OUT": "open"}
    assert bus.stats.locks == 2 and bus.stats.unlocks == 2 and bus.lock_is_free()
    lifecycle = [e.ev for e in world.daily_events() if e.ev in BUS_EVENTS]
    assert lifecycle == ["bus_open", "bus_lock", "bus_unlock", "bus_lock", "bus_unlock", "bus_close"]
    assert not [f for f in wg01(live) if f[0] == "block"]


def test_the_library_refuses_while_the_flex_lock_is_held(world: VisaWorld) -> None:
    """ATV-14 on the loop: the library's session cannot work while the FLEX link holds the exclusive VISA lock."""
    service = world.service(world.bus("lab_station"))
    session = service.executor.session(service.config.get())
    with session.transaction(intent="locked", envelope=None, run=None), pytest.raises(WgfmuError) as caught:
        read_channels(session.bus.wgfmu, DEFAULT_RESOURCE)
    assert caught.value.rc == api.COMMUNICATION_ERROR


def test_r_wg_01_blocks_a_32_bit_library_on_visa(world: VisaWorld, tmp_path) -> None:
    settings = yaml.safe_load((world.local / "settings.yaml").read_text(encoding="utf-8"))
    settings["wgfmu"]["library"] = write_dll(tmp_path / "x86" / "wgfmu.dll", machine=X86)
    world.write_local("settings.yaml", settings)
    bus = world.bus("lab_station")
    live = pre_execute_live(world.service(bus))
    assert live.wgfmu_library is not None and live.wgfmu_library.machine == "x86" and live.wgfmu_channels is None
    blocks = [message for severity, message in wg01(live) if severity == "block"]
    assert any("install the WGFMU instrument library >= A.03.00" in m for m in blocks), blocks
    assert any("channel ids were not read" in m for m in blocks), blocks
    assert bus.stats.wgfmu_loads == 0
    marks = [e for e in world.daily_events() if e.ev == "checkpoint"
             and (e.data or {}).get("label") == "wgfmu_channels_unread"]
    assert len(marks) == 1 and "install library >= A.03.00" in (marks[0].error or "")


def test_status_snapshots_on_visa_carry_the_library_probe(world: VisaWorld) -> None:
    service = world.service(world.bus("lab_station"))
    status = service.station_status()
    assert status.ok and "WGFMU library x64 A.04.00.2440.5403 loadable" in status.message, status.message
    live = service.executor.session(service.config.get()).last_live
    assert live is not None and live.wgfmu_library is not None and live.wgfmu_library.loadable
    assert live.wgfmu_channels is None  # a status snapshot opens no library session
