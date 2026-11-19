"""The hardware suite's contract, checked in CI (blueprint v2 10.2 row 6.4 AC; 7.1 ``tests/hardware/``, 7.4, 8.1).

- AC: ``uv run pytest -m hardware --collect-only`` lists the probe and record tests (each with ``hardware`` and one
  stage marker), and without ``B1500_HW=1`` every one of them is skipped with a reason that says why; with
  ``B1500_HW=1`` on a simulator configuration they skip too (backend not visa);
- the gate (``support.hardware_gate``), the stage-marker rule and the marker registration in ``pyproject.toml``;
- the ``hardware`` marker is used only in ``tests/hardware/`` (the gate lives in its ``conftest.py``);
- the probe tests' second paths (an error queue an earlier client left, selector outputs read back) on the
  visa-loop, called directly with an in-process probe.
"""

from __future__ import annotations

import json
import re
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME
from b1500_test_agent.service import B1500Admin
from tests.hardware import support
from tests.hardware import test_probe as hw_probe
from tests.hardware.rehearsal import REPO_ROOT, run_on_loop, run_suite
from tests.hardware.support import ENV_HW, STAGE_IDS, hardware_gate, stage_marker, stage_marker_problems
from tests.visa_loop.helpers import make_visa_world

PROBE_TESTS = {f"test_probe.py::{name}" for name in dir(hw_probe) if name.startswith("test_")}
RECORD_TESTS = {f"test_records.py::test_stage_records[{stage}]" for stage in STAGE_IDS} | {
    "test_records.py::test_every_record_file_belongs_to_a_stage"}
NODE = re.compile(r"^tests/hardware/(test_\w+\.py::\S+)$", re.MULTILINE)


# -- AC ----------------------------------------------------------------------------------------------------------------


def test_collect_only_lists_the_probe_and_record_tests(tmp_path: Path) -> None:
    run = run_suite(tmp_path, ["tests/hardware", "-m", "hardware", "--collect-only", "-q"], {})
    assert run.returncode == 0, run.output[-3000:]
    assert set(NODE.findall(run.output)) == PROBE_TESTS | RECORD_TESTS
    assert len(PROBE_TESTS) == 15 and len(RECORD_TESTS) == len(STAGE_IDS) + 1
    assert "hardware test(s) collected; they skip: hardware test: B1500_HW is unset" in run.output


def test_without_b1500_hw_every_hardware_test_skips_and_says_why(tmp_path: Path) -> None:
    run = run_suite(tmp_path, ["tests/hardware", "-m", "hardware"], {})
    assert run.returncode == 0, run.output[-3000:]
    assert set(run.outcomes) == PROBE_TESTS | RECORD_TESTS
    assert {o.status for o in run.outcomes.values()} == {"skipped"}
    assert all("B1500_HW is unset, not 1" in o.message for o in run.outcomes.values())
    assert f"HARDWARE SUITE NOT RUN: {len(run.outcomes)} hardware test(s) skipped" in run.output


@pytest.mark.parametrize("value", ["0", "true"])
def test_any_other_b1500_hw_value_skips(tmp_path: Path, value: str) -> None:
    run = run_suite(tmp_path, ["tests/hardware", "-m", "hardware and hw_l0"], {ENV_HW: value})
    assert run.returncode == 0 and set(run.outcomes) == PROBE_TESTS | {"test_records.py::test_stage_records[L0]"}
    assert all(o.status == "skipped" and f"B1500_HW is {value!r}, not 1" in o.message for o in run.outcomes.values())


def test_b1500_hw_on_a_simulator_configuration_skips(tmp_path: Path, repo: Path) -> None:
    env = {ENV_HW: "1", ENV_HOME: str(repo), ENV_DATA_DIR: str(tmp_path / "data")}
    run = run_suite(tmp_path, ["tests/hardware", "-m", "hardware"], env)
    assert run.returncode == 0 and set(run.outcomes) == PROBE_TESTS | RECORD_TESTS
    assert all(o.status == "skipped" and "settings backend is 'sim'" in o.message for o in run.outcomes.values())


# -- the gate ----------------------------------------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A temporary repository with the committed configuration examples (backend sim)."""
    world = make_visa_world(tmp_path / "w")
    for path in (world.root / "config" / "local").rglob("*"):
        if path.is_file():
            path.unlink()
    return world.root


def visa_repo(tmp_path: Path) -> Path:
    return make_visa_world(tmp_path / "v").root


def test_gate_is_off_unless_b1500_hw_is_1() -> None:
    for environ in ({}, {ENV_HW: "0"}, {ENV_HW: "yes"}, {ENV_HW: " 1"}):
        gate = hardware_gate(environ)
        assert not gate.enabled and "B1500_HW is" in gate.reason and "lab PC" in gate.reason


def test_gate_is_off_on_the_simulator(repo: Path) -> None:
    gate = hardware_gate({ENV_HW: "1", ENV_HOME: str(repo)})
    assert not gate.enabled and "backend is 'sim'" in gate.reason and "config/local/settings.yaml" in gate.reason


def test_gate_is_on_with_b1500_hw_and_backend_visa(tmp_path: Path) -> None:
    gate = hardware_gate({ENV_HW: "1", ENV_HOME: str(visa_repo(tmp_path))})
    assert gate.enabled and "visa: selected by config/local/settings.yaml" in gate.reason


def test_gate_stays_on_when_a_visa_configuration_does_not_load(tmp_path: Path) -> None:
    """The owner asked for the hardware suite: an invalid configuration fails its tests instead of hiding them."""
    root = visa_repo(tmp_path)
    environ = {ENV_HW: "1", ENV_HOME: str(root), ENV_CONFIG_DIR: str(tmp_path / "override")}
    assert hardware_gate(environ).enabled
    report = ConfigLoader(environ=environ).check()
    assert not report.ok and report.backend == "visa"


def test_hardware_tests_fail_on_a_visa_configuration_that_does_not_load(tmp_path: Path) -> None:
    world = make_visa_world(tmp_path / "w")
    try:
        bus = world.bus("lab_station")
        run = run_on_loop(world, bus, tmp_path, "tests/hardware/test_probe.py",
                          env={ENV_CONFIG_DIR: str(tmp_path / "override")})
    finally:
        world.close()
    assert run.returncode == 1 and set(run.outcomes) == PROBE_TESTS, run.output[-3000:]
    assert all(o.status == "error" and "the configuration does not load" in o.message for o in run.outcomes.values())
    assert bus.instrument.command_log == [] and not bus.state_file.exists()


def test_gate_reports_an_unreadable_settings_file(tmp_path: Path) -> None:
    root = visa_repo(tmp_path)
    (root / "config" / "local" / "settings.yaml").write_text("backend: [visa\n", encoding="utf-8")
    gate = hardware_gate({ENV_HW: "1", ENV_HOME: str(root)})
    assert not gate.enabled and "backend is unreadable" in gate.reason


# -- markers -----------------------------------------------------------------------------------------------------------


class Item:
    def __init__(self, nodeid: str, *names: str) -> None:
        self.nodeid = nodeid
        self.names = names

    def iter_markers(self, name: str | None = None) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=n) for n in self.names if name is None or n == name]


def test_every_hardware_test_needs_exactly_one_stage_marker() -> None:
    items = [Item("ok", "hardware", "hw_l0"), Item("none", "hardware"), Item("two", "hardware", "hw_l1", "hw_l2"),
             Item("not hardware", "hw_l3"), Item("plain")]
    problems = stage_marker_problems(items)
    assert [p.split(":")[0] for p in problems] == ["none", "two"]
    assert "found none" in problems[0] and "found hw_l1, hw_l2" in problems[1]


def test_stage_markers_follow_the_stage_ids() -> None:
    assert STAGE_IDS == ("S0", "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10")
    assert [stage_marker(s) for s in STAGE_IDS] == list(support.STAGE_MARKERS)
    with pytest.raises(ValueError, match="unknown bring-up stage"):
        stage_marker("L11")


def test_pyproject_registers_hardware_and_every_stage_marker() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markers = {line.split(":", 1)[0].strip() for line in config["tool"]["pytest"]["ini_options"]["markers"]}
    assert "hardware" in markers
    assert {m for m in markers if m.startswith("hw_")} == set(support.STAGE_MARKERS)
    assert "--strict-markers" in config["tool"]["pytest"]["ini_options"]["addopts"]


def test_the_hardware_marker_is_used_only_in_tests_hardware() -> None:
    """The gate is ``tests/hardware/conftest.py``: a hardware test elsewhere would run without it."""
    pattern = re.compile(r"mark\.hardware\b")
    offenders = [p.relative_to(REPO_ROOT).as_posix() for p in sorted((REPO_ROOT / "tests").rglob("*.py"))
                 if p.parent.name != "hardware" and pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


# -- how the docs tell the owner to run it -----------------------------------------------------------------------------

HARDWARE_RUN = re.compile(r"pytest -m \"?hardware\b")


def doc_texts() -> dict[str, str]:
    """Hand-written docs and skill sources that may name the hardware run (not the plan or acceptance reports)."""
    paths = [REPO_ROOT / name for name in ("README.md", "AGENTS.md", "CLAUDE.md")]
    paths += sorted((REPO_ROOT / "docs").glob("*.md")) + sorted((REPO_ROOT / ".agents" / "skills").rglob("*.md"))
    return {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8") for p in paths if p.is_file()}


def test_every_doc_that_names_the_hardware_run_sets_b1500_hw() -> None:
    """``uv run pytest -m hardware`` alone skips every test and checks nothing: each paragraph, list or table that
    names it also sets ``B1500_HW``."""
    missing = []
    for name, text in doc_texts().items():
        for block in re.split(r"\n\s*\n", text):
            if HARDWARE_RUN.search(block) and "B1500_HW" not in block:
                missing.append(f"{name}: {HARDWARE_RUN.search(block)[0]!r} without B1500_HW in: {block[:120]!r}")
    assert missing == []


def test_the_bringup_overview_says_how_to_run_the_suite() -> None:
    text = " ".join((REPO_ROOT / "docs" / "hardware-bringup.md").read_text(encoding="utf-8").split())
    assert '`$env:B1500_HW = "1"; uv run pytest -m hardware -rs`' in text
    assert "HARDWARE SUITE NOT RUN" in text and "hw_l1" in text and "only reads" in text


# -- helpers -----------------------------------------------------------------------------------------------------------


def test_audit_events_since_reads_the_daily_files_from_that_moment(tmp_path: Path) -> None:
    state = tmp_path / "state"
    (state / "audit").mkdir(parents=True)
    since = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    events = [AuditEvent(ts=since - timedelta(days=1), ev="query", cmd="UNT?", intent="probe", backend="visa"),
              AuditEvent(ts=since - timedelta(seconds=1), ev="query", cmd="UNT?", intent="probe", backend="visa"),
              AuditEvent(ts=since, ev="query", cmd="*IDN?", intent="probe", backend="visa"),
              AuditEvent(ts=since + timedelta(seconds=1), ev="query", cmd="LOP?", intent="status", backend="visa")]
    for event in events:
        path = state / "audit" / f"{event.ts:%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_record()) + "\n")
    assert [e.cmd for e in support.audit_events_since(state, since)] == ["*IDN?", "LOP?"]
    assert [e.cmd for e in support.audit_events_since(state, since, intent="probe")] == ["*IDN?"]
    assert support.audit_events_since(tmp_path / "nowhere", since) == []


# -- second paths of the probe tests (in-process, visa-loop) -----------------------------------------------------------


def test_an_error_queue_left_by_another_client_is_drained_and_probed_again(tmp_path: Path) -> None:
    world = make_visa_world(tmp_path)
    try:
        bus = world.bus("lab_station")
        bus.instrument.handle("BOGUS")  # error 100 left by an earlier client
        service = world.service(bus)
        report = B1500Admin(service).probe()
        assert {c.name: c.status for c in report.checks}["error queue"] == "WARN"
        hw_probe.test_error_queue_is_drained(report, service)  # drains, probes again, finds the queue empty
        assert len(list((world.root / "work" / "bringup").glob("probe-*.json"))) == 2
    finally:
        world.close()


def test_selector_outputs_read_back_at_rest_pass(tmp_path: Path) -> None:
    world = make_visa_world(tmp_path)
    try:
        bus = world.bus("lab_station")
        bus.instrument.state.selector_mode = 1
        service = world.service(bus)
        report = B1500Admin(service).probe()
        assert report.switch_states == {"SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open",
                                        "SEL2.OUT2": "open"}
        hw_probe.test_selector_outputs_are_at_rest(report, service.config.get())
        station = yaml.safe_load((world.local / "station.yaml").read_text(encoding="utf-8"))
        assert {s["id"] for s in station["switches"] if s["kind"] == "selector_16440a"} == {"SEL1", "SEL2"}
    finally:
        world.close()
