"""``b1500 doctor`` check ``local config`` (blueprint v2 7.1, WP11.4): the ``config/local`` facts only the human can
record (switch wiring and presence, DUT pulse/AC envelopes, local pin maps and DUT profiles, the load standard) are
reported, warned about where plans stay blocked without them, and never block the simulator's committed examples.

Every configuration here is a temporary repository (``repo`` fixture: a copy of the committed ``config/`` tree);
``config/local/`` files are written the way the owner adopts them on the lab PC."""

from __future__ import annotations

import shutil
from pathlib import Path

from b1500_test_agent.config import load_config
from b1500_test_agent.devtools.doctor import (
    DoctorCheck,
    check_local_config,
    run_doctor,
    switch_gaps,
    terminal_needs,
)
from b1500_test_agent.models.station import PinMap
from b1500_test_agent.paths import Paths
from tests.unit.helpers import read_yaml, write_yaml

LOCAL = ("config", "local")


def local(repo: Path, *parts: str) -> Path:
    return repo.joinpath(*LOCAL, *parts)


def visa_core(repo: Path) -> None:
    """``config init --visa`` on a temporary clone: the three core examples copied to ``config/local/``."""
    for item in ("settings", "station", "policy"):
        target = local(repo, f"{item}.yaml")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / "config" / f"{item}.example.yaml", target)
    settings = read_yaml(local(repo, "settings.yaml"))
    write_yaml(local(repo, "settings.yaml"), {**settings, "backend": "visa"})


def adopt(repo: Path, kind: str, name: str, edit: dict | None = None) -> None:
    """``config adopt`` of an example pin map (``pinmaps``) or DUT profile (``duts``), optionally edited."""
    data = read_yaml(repo / "config" / kind / f"{name}.example.yaml")
    write_yaml(local(repo, kind, f"{name}.yaml"), {**data, **(edit or {})})


def record_selector(repo: Path) -> None:
    """The human records the SEL1 cabling at stage L7 (SMU3/SMU4 and the SPGU's two channels)."""
    station = read_yaml(local(repo, "station.yaml"))
    sel1 = next(s for s in station["switches"] if s["id"] == "SEL1")
    sel1["ports"]["OUT1"]["inputs"] = {"smu": 3, "pgu": 101}
    sel1["ports"]["OUT2"]["inputs"] = {"smu": 4, "pgu": 102}
    write_yaml(local(repo, "station.yaml"), station)


def test_committed_examples_pass_on_the_simulator(repo_paths: Paths) -> None:
    check = check_local_config(load_config(repo_paths))
    assert check.name == "local config" and check.status == "PASS", check.detail
    assert check.detail.startswith("examples (no config/local/")
    assert "pulse/AC terminals of the pin maps covered by a fitting DUT profile" in check.detail
    # the lab-shaped example leaves the selector inputs null: listed, never warned about on the simulator
    assert "SEL1.OUT1 pgu" in check.detail and "scenario's cabling stands in" in check.detail
    assert "unverified_topology" in check.detail


def test_visa_without_local_pin_maps_or_duts_warns(repo: Path, repo_paths: Paths) -> None:
    visa_core(repo)
    check = check_local_config(load_config(repo_paths))
    assert check.status == "WARN" and check.detail.startswith("config/local: ")
    assert "no pin map in config/local/pinmaps" in check.detail and "R-PIN-01" in check.detail
    assert "no DUT profile in config/local/duts" in check.detail and "R-DUT-01" in check.detail
    # no pin map routes through a switch yet: the unrecorded wiring is listed, not warned about
    assert "switch wiring not recorded" not in check.detail
    assert "unrecorded on switches no pin map uses" in check.detail


def test_visa_null_selector_inputs_behind_a_pin_map_warn_until_recorded(repo: Path, repo_paths: Paths) -> None:
    visa_core(repo)
    adopt(repo, "pinmaps", "fefet-sel")
    adopt(repo, "duts", "fefet-lab")
    check = check_local_config(load_config(repo_paths))
    assert check.status == "WARN", check.detail
    assert "switch wiring not recorded: SEL1.OUT1 pgu/SEL1.OUT1 smu" in check.detail
    assert "(pin maps fefet-sel)" in check.detail and "R-ROUTE-01" in check.detail
    assert "no fitting DUT profile" not in check.detail  # fefet-lab declares the gate's pulse envelope
    record_selector(repo)
    check = check_local_config(load_config(repo_paths))
    assert check.status == "PASS", check.detail
    assert "all 1 pulse/AC terminals of the pin maps covered" in check.detail


def test_visa_notes_that_unknown_rsu_inputs_block_smus_above_25_v(repo: Path, repo_paths: Paths) -> None:
    """WP21.13: an RSU's unknown "From SMU" input blocks every SMU plan above +-25 V on hardware (R-RSU-01); the
    check names it until stage L8 records the wiring (an SMU channel, or the smu side deleted), and never on the
    simulator, where the scenario's cabling stands in."""
    note = "RSU From SMU input unknown (RSU201.OUT, RSU202.OUT)"
    assert note not in check_local_config(load_config(repo_paths)).detail  # simulator
    visa_core(repo)
    check = check_local_config(load_config(repo_paths))
    assert note in check.detail and "R-RSU-01" in check.detail and "stage L8" in check.detail
    station = read_yaml(local(repo, "station.yaml"))
    for switch in station["switches"]:
        if switch["kind"] == "rsu":
            switch["ports"]["OUT"]["inputs"] = ({"wgfmu": 201, "smu": 4} if switch["id"] == "RSU201" else
                                                {"wgfmu": 202})
    write_yaml(local(repo, "station.yaml"), station)
    assert "RSU From SMU input unknown" not in check_local_config(load_config(repo_paths)).detail


def test_visa_missing_pulse_envelope_on_an_spgu_terminal_warns(repo: Path, repo_paths: Paths) -> None:
    visa_core(repo)
    record_selector(repo)
    adopt(repo, "pinmaps", "fefet-sel")
    dut = read_yaml(repo / "config" / "duts" / "fefet-lab.example.yaml")
    del dut["terminals"]["gate"]["pulse"]
    write_yaml(local(repo, "duts", "fefet-lab.yaml"), dut)
    check = check_local_config(load_config(repo_paths))
    assert check.status == "WARN"
    assert "fefet-sel.gate pulse (SPGU via SEL1.OUT1; R-PULSE-02)" in check.detail
    assert "never invented" in check.detail


def test_visa_missing_ac_envelope_and_a_dut_that_does_not_fit_warn(repo: Path, repo_paths: Paths) -> None:
    visa_core(repo)
    adopt(repo, "pinmaps", "moscap-cmu")
    adopt(repo, "duts", "capacitor-100p")  # terminals a, b: does not fit a gate/bulk landing
    check = check_local_config(load_config(repo_paths))
    assert check.status == "WARN"
    assert "moscap-cmu.bulk ac (MFCMU 7L; R-CMU-01)" in check.detail
    assert "moscap-cmu.gate ac (MFCMU 7H; R-CMU-01)" in check.detail
    dut = read_yaml(repo / "config" / "duts" / "moscap-generic.example.yaml")
    write_yaml(local(repo, "duts", "moscap-generic.yaml"), dut)
    assert check_local_config(load_config(repo_paths)).status == "PASS"
    del dut["terminals"]["bulk"]["ac"]
    write_yaml(local(repo, "duts", "moscap-generic.yaml"), dut)
    check = check_local_config(load_config(repo_paths))
    assert check.status == "WARN" and "moscap-cmu.bulk ac" in check.detail and "moscap-cmu.gate ac" not in check.detail


def test_a_required_load_correction_needs_the_load_standard(repo: Path, repo_paths: Paths) -> None:
    visa_core(repo)
    adopt(repo, "pinmaps", "moscap-cmu")
    adopt(repo, "duts", "moscap-generic")
    assert check_local_config(load_config(repo_paths)).status == "PASS"
    policy = read_yaml(local(repo, "policy.yaml"))
    policy.setdefault("corrections", {})["require"] = ["phase", "open", "short", "load"]
    write_yaml(local(repo, "policy.yaml"), policy)
    check = check_local_config(load_config(repo_paths))
    assert check.status == "WARN" and "load standard of CMU1 is not recorded" in check.detail
    station = read_yaml(local(repo, "station.yaml"))
    station["corrections"]["CMU1"]["load"] = {"ls_h": 0.0, "rs_ohm": 100.0}
    write_yaml(local(repo, "station.yaml"), station)
    assert check_local_config(load_config(repo_paths)).status == "PASS"


def test_terminal_needs_of_direct_channels_and_switch_inputs(repo_paths: Paths) -> None:
    station = load_config(repo_paths).station
    pin_map = PinMap(name="direct", certainty="unverified",
                     terminals={"a": 101, "b": 201, "c": 7, "d": "7L", "e": 3, "f": "GNDU", "g": "SCUU1.OUT1",
                                "h": "RSU202.OUT"})
    needs = {(n.terminal, n.envelope, n.via) for n in terminal_needs(station, pin_map)}
    assert needs == {("a", "pulse", "SPGU channel 101"), ("b", "pulse", "WGFMU channel 201"),
                     ("c", "ac", "MFCMU channel 7"), ("d", "ac", "MFCMU 7L"), ("g", "ac", "MFCMU via SCUU1.OUT1"),
                     ("h", "pulse", "WGFMU via RSU202.OUT")}


def test_switch_gaps_skip_switches_declared_absent(repo_paths: Paths) -> None:
    station = load_config(repo_paths).station
    gaps = switch_gaps(station)
    assert gaps["SCUU1"] == ["SCUU1 presence unknown"] and "SEL1.OUT1 pgu" in gaps["SEL1"]
    absent = station.model_copy(update={"switches": [s.model_copy(update={"present": False})
                                                     for s in station.switches]})
    assert switch_gaps(absent) == {}


def _no_server() -> DoctorCheck:
    return DoctorCheck(name="mcp server", status="PASS", detail="not started in this test")


def test_doctor_runs_the_check_and_an_invalid_config_is_only_info(repo: Path) -> None:
    env = {"B1500_HOME": str(repo)}
    report = run_doctor(environ=env, windows=False, mcp_check=_no_server)
    checks = {c.name: c for c in report.checks}
    assert checks["local config"].status == "PASS"
    write_yaml(repo / "config" / "station.example.yaml", {"name": "broken"})
    report = run_doctor(environ=env, windows=False, mcp_check=_no_server)
    checks = {c.name: c for c in report.checks}
    assert checks["config"].status == "FAIL" and checks["local config"].status == "INFO"
