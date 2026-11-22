"""``b1500 doctor --probe --wgfmu-session`` and ``b1500 doctor``'s WGFMU line on the simulator (blueprint v2 7.1, 7.4
L0 rehearsal; WP10.2). On backend sim the library is the simulator's: the ``wgfmu library`` line is INFO (no DLL is
read), the session check opens the simulated library's session with the FLEX link closed and reads the channel ids
and the status; nothing changes on the instrument. The visa path is ``tests/visa_loop/test_wgfmu_visa.py``."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.models.bringup import ProbeReport
from tests.adapters.test_cli_bootstrap import plain
from tests.integration.helpers import World

pytestmark = pytest.mark.wgfmu

runner = CliRunner()


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args))


def as_json(result: Result) -> dict[str, Any]:
    return json.loads(result.stdout)


def test_the_session_check_on_the_simulator(cli_world: World) -> None:
    cli_world.use_scenario("lab_station")
    human = invoke("doctor", "--probe", "--wgfmu-session")
    assert human.exit_code == 0, human.output
    assert "INFO  wgfmu library" in human.stdout and "backend sim" in human.stdout
    assert "PASS  wgfmu session" in human.stdout and "channels 201, 202" in human.stdout
    report = ProbeReport.model_validate(as_json(invoke("doctor", "--probe", "--wgfmu-session", "--json")))
    assert report.ok and report.simulated and report.wgfmu_channels == [201, 202] and report.wgfmu_library is None
    names = [c.name for c in report.checks]
    assert names[-3:] == ["wgfmu library", "wgfmu session", "fault latch"]
    events = [e for e in cli_world.audit_events() if e.ev == "wgfmu_call"]
    assert [e.cmd for e in events] == ["WGFMU_openSession", "WGFMU_getChannelIds", "WGFMU_getStatus",
                                       "WGFMU_closeSession"] * 2
    assert all(e.backend == "sim" and e.intent == "probe: wgfmu session" for e in events)
    log = cli_world.sim_log("lab_station")
    assert log and all(record.command.split()[0].endswith("?") for record in log)  # FLEX: queries only


def test_without_the_flag_no_library_session_is_opened(cli_world: World) -> None:
    cli_world.use_scenario("lab_station")
    report = ProbeReport.model_validate(as_json(invoke("doctor", "--probe", "--json")))
    assert report.ok and "wgfmu session" not in [c.name for c in report.checks]
    assert next(c for c in report.checks if c.name == "wgfmu library").status == "INFO"
    assert [e for e in cli_world.audit_events() if e.ev == "wgfmu_call"] == []


def test_the_flag_belongs_to_the_probe(cli_world: World) -> None:
    result = invoke("doctor", "--wgfmu-session")
    assert result.exit_code == 2 and "--wgfmu-session is part of the probe" in plain(result.output)


def test_a_missing_simulated_library_fails_the_session_line(cli_world: World) -> None:
    cli_world.use_faults("no_library", [{"kind": "wgfmu_dll_missing"}])  # nmos_basic: the lab layout, WGFMU slot 2
    result = invoke("doctor", "--probe", "--wgfmu-session")
    assert result.exit_code == 1 and "FAIL  wgfmu session" in result.stdout
    assert "no WGFMU instrument library on this bus" in result.stdout
