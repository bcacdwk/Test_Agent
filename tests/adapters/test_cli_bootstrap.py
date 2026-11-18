"""The plug-in-and-go CLI of WP6.1 (blueprint v2 7.1): ``doctor --probe``, ``bringup propose-station`` and the
human-only ``config init [--visa]`` / ``config adopt FILE --as KIND``.

Every test runs in a temporary clone: ``config init``/``adopt`` write into ``$B1500_CONFIG_DIR`` (``cli_world``) or
into the temporary clone's ``config/local/`` (``clone``); the repository's own ``config/local/`` is never touched.
These groups are documented CLI-only exceptions of the MCP/CLI parity rule (no MCP tool)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

import b1500_test_agent.adapters.cli as cli_package
from b1500_test_agent.adapters.cli import TOOL_COMMANDS, app
from b1500_test_agent.models.bringup import ProbeReport, StationProposal
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from b1500_test_agent.service import TOOL_NAMES
from tests.integration.helpers import REPO_ROOT, World

runner = CliRunner()


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args))


def as_json(result: Result) -> dict[str, Any]:
    return json.loads(result.stdout)


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary clone (committed config only, no ``config/local/``) selected through ``B1500_HOME``; no
    ``B1500_CONFIG_DIR``, as on the lab PC."""
    root = tmp_path / "clone"
    shutil.copytree(REPO_ROOT / "config", root / "config", ignore=shutil.ignore_patterns("local"))
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    monkeypatch.setenv(ENV_HOME, str(root))
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "data"))
    monkeypatch.delenv(ENV_CONFIG_DIR, raising=False)
    return root


# -- config init ----------------------------------------------------------------------------------------------------


def test_config_init_copies_the_missing_core_examples_and_never_overwrites(cli_world: World) -> None:
    result = invoke("config", "init")
    assert result.exit_code == 0, result.output
    for item in ("settings", "station", "policy"):
        copied = cli_world.cfg / f"{item}.yaml"
        assert copied.read_text(encoding="utf-8") == (REPO_ROOT / "config" / f"{item}.example.yaml").read_text(
            encoding="utf-8")
    assert (cli_world.cfg / "pinmaps").is_dir() and (cli_world.cfg / "duts").is_dir()
    assert "copied" in result.stdout and "config: valid" in result.stdout
    station = cli_world.cfg / "station.yaml"
    station.write_text(station.read_text(encoding="utf-8").replace("lab-b1500a-example", "my-lab"),
                       encoding="utf-8")
    again = invoke("config", "init", "--json")
    report = as_json(again)
    assert again.exit_code == 0 and report["copied"] == [] and len(report["kept"]) == 3
    assert "my-lab" in station.read_text(encoding="utf-8")  # never overwritten


def test_config_init_visa_on_the_lab_pc_layout(clone: Path) -> None:
    result = invoke("config", "init", "--visa", "--json")
    report = as_json(result)
    assert result.exit_code == 0, result.output
    assert report["target_dir"] == "config/local" and sorted(report["copied"]) == [
        "config/local/policy.yaml", "config/local/settings.yaml", "config/local/station.yaml"]
    settings = yaml.safe_load((clone / "config" / "local" / "settings.yaml").read_text(encoding="utf-8"))
    assert settings["backend"] == "visa"
    assert "# Runtime settings" in (clone / "config" / "local" / "settings.yaml").read_text(encoding="utf-8")
    assert report["check"]["ok"] is True and report["check"]["backend"] == "visa"
    check = invoke("config", "check")
    assert check.exit_code == 0 and "backend: visa: selected by config/local/settings.yaml" in check.stdout


def test_config_init_visa_reports_a_kept_sim_settings_file(cli_world: World) -> None:
    cli_world.use_scenario("nmos_basic")  # an existing settings.yaml (sim)
    result = invoke("config", "init", "--visa", "--json")
    report = as_json(result)
    assert "config/settings.yaml" not in report["copied"] and any("settings.yaml" in k for k in report["kept"])
    assert any("does not select backend visa" in note for note in report["notes"])
    assert yaml.safe_load((cli_world.cfg / "settings.yaml").read_text(encoding="utf-8"))["backend"] == "sim"


# -- config adopt ---------------------------------------------------------------------------------------------------


def test_config_adopt_validates_diffs_backs_up_and_copies(clone: Path, tmp_path: Path) -> None:
    assert invoke("config", "init").exit_code == 0
    local = clone / "config" / "local" / "station.yaml"
    before = local.read_text(encoding="utf-8")
    proposal = tmp_path / "station.proposed.yaml"
    proposal.write_text(before.replace("lab-b1500a-example", "lab-b1500a"), encoding="utf-8")
    result = invoke("config", "adopt", str(proposal), "--as", "station")
    assert result.exit_code == 0, result.output
    assert "-name: lab-b1500a-example" in result.stdout and "+name: lab-b1500a" in result.stdout
    assert local.read_text(encoding="utf-8") == proposal.read_text(encoding="utf-8")
    assert (clone / "config" / "local" / "station.yaml.bak").read_text(encoding="utf-8") == before
    assert "config: valid" in result.stdout
    again = as_json(invoke("config", "adopt", str(proposal), "--as", "station", "--json"))
    assert again["unchanged"] is True and again["adopted"] is False and again["ok"] is True


def test_config_adopt_refuses_an_invalid_file_and_writes_nothing(clone: Path, tmp_path: Path) -> None:
    assert invoke("config", "init").exit_code == 0
    local = clone / "config" / "local" / "station.yaml"
    before = local.read_text(encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    data = yaml.safe_load(before)
    data["modules"][0]["model"] = "B9999Z"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = invoke("config", "adopt", str(bad), "--as", "station")
    assert result.exit_code == 1 and "REFUSED, nothing written" in result.stdout and "B9999Z" in result.stdout
    assert local.read_text(encoding="utf-8") == before and not (local.parent / "station.yaml.bak").exists()
    duplicate = tmp_path / "dup.yaml"
    duplicate.write_text("backend: sim\nbackend: visa\n", encoding="utf-8")
    refused = as_json(invoke("config", "adopt", str(duplicate), "--as", "settings", "--json"))
    assert refused["ok"] is False and "duplicate key" in refused["problems"][0]
    missing = as_json(invoke("config", "adopt", str(tmp_path / "nope.yaml"), "--as", "policy", "--json"))
    assert missing["ok"] is False and "cannot read" in missing["problems"][0]


def test_config_adopt_names_pin_maps_and_duts_after_the_file(clone: Path) -> None:
    assert invoke("config", "init").exit_code == 0
    example = clone / "config" / "pinmaps" / "mosfet-3t-lab.example.yaml"
    result = as_json(invoke("config", "adopt", str(example), "--as", "pinmap", "--json"))
    assert result["adopted"] and result["target"] == "config/local/pinmaps/mosfet-3t-lab.yaml" and result["ok"]
    dut = as_json(invoke("config", "adopt", str(clone / "config" / "duts" / "nmos-generic.example.yaml"), "--as",
                         "dut", "--json"))
    assert dut["target"] == "config/local/duts/nmos-generic.yaml" and dut["backup"] is None and dut["diff"]


def test_config_adopt_reports_a_configuration_the_file_breaks(cli_world: World, tmp_path: Path) -> None:
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    station["switches"] = [s for s in station["switches"] if s["id"] != "SEL1"]  # pin map fefet-sel needs SEL1
    path = tmp_path / "station.yaml"
    path.write_text(yaml.safe_dump(station), encoding="utf-8")
    result = invoke("config", "adopt", str(path), "--as", "station", "--json")
    report = as_json(result)
    assert result.exit_code == 1 and report["adopted"] is True and report["ok"] is False
    assert any("SEL1" in p["message"] for p in report["check"]["problems"])


def test_config_adopt_rejects_an_unknown_kind(cli_world: World, tmp_path: Path) -> None:
    result = invoke("config", "adopt", str(tmp_path / "x.yaml"), "--as", "recipe")
    assert result.exit_code == 2 and "--as must be one of" in result.output


# -- doctor --probe and bringup propose-station on the simulator ----------------------------------------------------


def test_doctor_probe_on_the_simulator(cli_world: World) -> None:
    cli_world.use_scenario("lab_station")
    human = invoke("doctor", "--probe")
    assert human.exit_code == 0, human.output
    assert human.stdout.startswith("[SIMULATED] ok: SIMULATED probe of SIM::lab_station")
    assert re.search(r"^PASS  identity +Agilent Technologies B1500A, firmware A\.06\.02\.2023\.0401$", human.stdout,
                     re.MULTILINE)
    assert "INFO  visa library" in human.stdout and "raw answers: work/bringup/probe-" in human.stdout
    report = ProbeReport.model_validate(as_json(invoke("doctor", "--probe", "--json")))
    assert report.ok and report.simulated and report.record is not None
    assert (cli_world.root / report.record).is_file()


def test_doctor_probe_fails_with_exit_1_on_an_inventory_mismatch(cli_world: World) -> None:
    cli_world.use_scenario("lab_station")
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    station["modules"][4]["model"] = "B1511A"
    cli_world.write_config("station.yaml", station)
    result = invoke("doctor", "--probe")
    assert result.exit_code == 1 and "FAIL  inventory" in result.stdout
    assert "next: run b1500 bringup propose-station" in result.stdout


def test_bringup_propose_station_on_the_simulator(cli_world: World) -> None:
    cli_world.use_scenario("lab_station")
    result = invoke("bringup", "propose-station")
    assert result.exit_code == 0, result.output
    assert "[SIMULATED] ok: SIMULATED proposal for 7 modules written to work/bringup/station.proposed.yaml" in \
        result.stdout
    assert "no config/local/station.yaml yet" in result.stdout and "slot 7: B1520A MFCMU" in result.stdout
    path = cli_world.root / "work" / "bringup" / "station.proposed.yaml"
    text = path.read_text(encoding="utf-8")
    assert "SIMULATED: a rehearsal, not hardware" in text
    station = StationProfile.model_validate(yaml.safe_load(text))
    assert station.name == "lab-b1500a" and all(s.certainty == "unverified" for s in station.switches)
    payload = StationProposal.model_validate(as_json(invoke("bringup", "propose-station", "--json")))
    assert payload.diff is None and payload.base == "config/station.example.yaml" and payload.simulated


def test_bringup_propose_station_diffs_against_the_active_local_station(cli_world: World) -> None:
    cli_world.use_scenario("lab_station")
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    station["modules"][4]["model"] = "B1511A"  # the profile guessed slot 5 wrong
    cli_world.write_config("station.yaml", station)
    result = invoke("bringup", "propose-station", "--json")
    payload = as_json(result)
    assert result.exit_code == 0 and payload["matches_local"] is False and payload["local"].endswith("station.yaml")
    assert "-  model: B1511A" in payload["diff"] and "+  model: B1511B" in payload["diff"]
    assert "slot 5: B1511A in the base profile, B1511B installed" in payload["notes"]
    assert any("config adopt" in step and "human only" in step for step in payload["next_steps"])


def test_propose_station_refuses_an_invalid_configuration(cli_world: World) -> None:
    cli_world.write_config("policy.yaml", {"hard_limits": {"max_abs_voltage_v": 100}})
    result = invoke("bringup", "propose-station", "--json")
    assert result.exit_code == 1 and as_json(result)["error_code"] == "invalid_config"


# -- CLI-only exceptions of the parity rule -------------------------------------------------------------------------


def test_config_and_bringup_groups_are_documented_cli_only_exceptions() -> None:
    assert all(command[0] not in ("config", "bringup", "doctor") for command in TOOL_COMMANDS.values())
    assert len(TOOL_NAMES) == 10 and not any(n.startswith(("config", "bringup", "probe")) for n in TOOL_NAMES)
    doc = cli_package.__doc__ or ""
    assert "configuration (CLI only, no MCP tool)" in doc and "bring-up (CLI only, no MCP tool)" in doc
    assert "human-only ``config init [--visa]``" in doc
