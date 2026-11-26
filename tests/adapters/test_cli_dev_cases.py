"""``b1500 dev cases list|check|reproduce`` (v2.1 plan §3 item 6, WP21.4): the review tooling of the debug cases.

``list`` shows every case's status, runbook, lab runs, reproduction verdict (SIMULATED) and open questions; ``check``
lints the cases (``--reproduce`` also runs them); ``reproduce`` runs one case into its own folder (default
``work/cases/<case>/<UTC stamp>/`` of the clone) and keeps ``data/`` and ``report.json``. Reproductions run on the
simulator only, whatever the clone's configuration says; the clone of these tests is a temporary copy, so nothing
here writes into the repository.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.devtools import cases
from b1500_test_agent.paths import ENV_HOME
from tests.unit.helpers import REPO_ROOT

runner = CliRunner()
CASE = "2026-11-04-current-orders-too-high"
CASE_FILE = Path(".agents", "skills", "b1500-debug", "cases", f"{CASE}.md")


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary clone (skills, recipes, committed config) selected through ``B1500_HOME``; its ``config/local``
    says ``backend: visa`` like a lab PC's, which a reproduction must ignore."""
    root = tmp_path / "clone"
    shutil.copytree(REPO_ROOT / ".agents", root / ".agents")
    shutil.copytree(REPO_ROOT / "recipes", root / "recipes")
    shutil.copytree(REPO_ROOT / "config", root / "config", ignore=shutil.ignore_patterns("local"))
    (root / "config" / "local").mkdir()
    (root / "config" / "local" / "settings.yaml").write_text(
        yaml.safe_dump({"backend": "visa", "visa": {"resource": "GPIB0::17::INSTR"}}), encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    monkeypatch.setenv(ENV_HOME, str(root))
    return root


def invoke(*args: str) -> Any:
    return runner.invoke(app, ["dev", "cases", *args])


def test_list_without_reproduction(clone: Path) -> None:
    result = invoke("list", "--no-reproduce")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "cases: ok (4 cases, 20 open questions for the owner, 0 problem(s))"
    assert (f"  {CASE}: draft; runbook current-too-high; backend visa, 0 lab run(s); reproduction not run; "
            "5 open question(s)") in lines


def test_list_reproduces_every_case_on_the_simulator(clone: Path) -> None:
    result = invoke("list", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True and payload["problems"] == []
    assert {row["id"]: row["reproduction"] for row in payload["cases"]} == {
        "2026-11-04-current-orders-too-high": "pass", "2026-11-04-cv-shape-abnormal": "pass",
        "2026-11-04-igzo-vth-drift": "pass", "2026-11-04-noisy-data": "pass"}
    for report in payload["reproductions"]:
        assert report["simulated"] is True and report["backend"] == "sim" and report["data_dir"] is None
    assert not (clone / "work").exists() and not (clone / "data").exists()  # temporary folders only


def test_check_lints_and_reports_a_failing_reproduction(clone: Path) -> None:
    assert invoke("check").exit_code == 0
    path = clone / CASE_FILE
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("contact.result('resistance') < 1.0e+6", "contact.result('resistance') > 1.0e+6"),
                    encoding="utf-8")
    result = invoke("check", "--reproduce")
    assert result.exit_code == 1
    assert f"{CASE}: draft; runbook current-too-high; backend visa, 0 lab run(s); reproduction fail" in result.output
    assert "[fail] contact.result('resistance') > 1.0e+6" in result.output
    assert "contact.result('resistance') = 999.9" in result.output
    path.write_text(text.replace("open_questions: 5", "open_questions: 3"), encoding="utf-8")
    broken = invoke("check")
    assert broken.exit_code == 1 and "open_questions is 3 but the section" in broken.output
    listed = invoke("list")  # a case with lint problems is not reproduced
    assert listed.exit_code == 1 and f"{CASE}: draft; runbook current-too-high; backend visa, 0 lab run(s); " \
        "reproduction not run" in listed.output
    refused = invoke("reproduce", CASE)
    assert refused.exit_code == 2 and "has 1 lint problem(s), first: open_questions is 3" in refused.output


def test_reproduce_keeps_the_runs_and_the_report(clone: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = invoke("reproduce", CASE, "--out", str(out))
    assert result.exit_code == 0, result.output
    assert result.output.startswith(f"case {CASE}: reproduction PASS [SIMULATED] (backend sim, commit ")
    assert "[pass] symptom.status('gate_I', 0) == 'C'" in result.output
    report = json.loads((out / cases.REPORT_FILE).read_text(encoding="utf-8"))
    assert report["ok"] is True and report["data_dir"] == (out / "data").as_posix()
    run_ids = [step["run_id"] for step in report["steps"]]
    assert all(run_id.startswith("S") for run_id in run_ids)
    assert {p.name for p in (out / "data" / "runs").rglob("S*") if p.is_dir()} == set(run_ids)
    again = invoke("reproduce", CASE, "--out", str(out))  # never over an existing reproduction
    assert again.exit_code == 2 and "exists and is not empty" in again.output


def test_reproduce_defaults_to_the_clones_work_folder(clone: Path) -> None:
    result = invoke("reproduce", CASE, "--json")
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    data_dir = Path(report["data_dir"])
    assert data_dir.parent.parent == (clone / "work" / "cases" / CASE).resolve()
    assert (data_dir.parent / cases.REPORT_FILE).is_file() and not (clone / "data").exists()


def test_reproduce_refuses_an_unknown_case(clone: Path) -> None:
    result = invoke("reproduce", "2026-11-04-unknown")
    assert result.exit_code == 2 and "no valid case '2026-11-04-unknown'" in result.output
    path = clone / CASE_FILE
    text = path.read_text(encoding="utf-8")
    start, end = text.index("reproduction:\n"), text.index("open_questions:")
    path.write_text(text[:start] + "reproduction: null\n" + text[end:], encoding="utf-8")
    result = invoke("reproduce", CASE)
    assert result.exit_code == 2 and "has no reproduction" in result.output


def test_a_reproduction_never_runs_on_another_backend(clone: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two layers: a temporary configuration that selected visa would be invalid (``B1500_CONFIG_DIR`` is for the
    simulator only, R-CFG-01), and a bundle that still said visa is refused before the first step."""
    found, _ = cases.load_cases(clone)
    case = next(c for c in found if c.id == CASE)
    assert case.front.reproduction is not None
    registry = RecipeRegistry.load(clone / "recipes", repo_root=clone)

    def visa(self: Any, scenario: str) -> None:
        self._write("settings.yaml", {"backend": "visa", "visa": {"resource": "GPIB0::17::INSTR"},
                                      "sim": {"scenario": scenario}})

    with monkeypatch.context() as patch:
        patch.setattr(cases._World, "use", visa)
        report = cases.run_reproduction(CASE, case.front.reproduction, root=clone, registry=registry)
    assert not report.ok and report.steps == [] and report.expect == []
    assert report.error is not None and "B1500_CONFIG_DIR is set" in report.error
    monkeypatch.setattr(ConfigBundle, "backend", property(lambda self: "visa"))
    report = cases.run_reproduction(CASE, case.front.reproduction, root=clone, registry=registry)
    assert not report.ok and report.steps == []
    assert report.error == "refused: the reproduction configuration selects backend visa, not sim"
