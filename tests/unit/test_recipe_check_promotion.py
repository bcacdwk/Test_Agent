"""The promotion rule of ``b1500 dev recipe-check`` (blueprint v2 7.2, WP6.3 AC): ``hw_validated`` ⇔ a reviewed,
passing record in ``validation/hw/<recipe_id>.yaml`` with ``H…`` runs and the current recipe's definition digest.

The AC case is the committed fixture ``tests/fixtures/validation/hw_validated_without_record/`` (a fake
``hw_validated`` copy of ``basic.contact_resistor`` and no record): recipe-check must fail. Reviewed records are
built in temporary folders only, never in ``validation/hw/`` (guardrail 6: no fabricated hardware evidence).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.catalog.schema import parse_recipe
from b1500_test_agent.devtools.recipe_check import check_recipes, format_report
from b1500_test_agent.models.validation import recipe_definition_sha256
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, ENV_HOME

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "validation" / "hw_validated_without_record"
RECIPE = "basic/contact_resistor.yaml"
RUN = "H20261201T093012Z-1a2b"


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    shutil.copytree(FIXTURE, root)
    return root


def _digest(root: Path) -> str:
    raw = (root / "recipes" / RECIPE).read_bytes()
    return recipe_definition_sha256(parse_recipe(raw, source=RECIPE))


def _record(digest: str, **changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "L2", "recipe_id": "basic.contact_resistor", "recipe_version": 1, "recipe_sha256": digest,
        "backend": "visa", "runs": [RUN], "result": "pass", "operator": "test", "date": "2026-12-01",
        "reviewer": "test reviewer", "reviewed_on": "2026-12-02",
    }
    record.update(changes)
    return record


def _write(root: Path, name: str, data: Any) -> Path:
    path = root / "validation" / "hw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _check(root: Path):
    return check_recipes(root / "recipes", repo_root=root, validation_dir=root / "validation" / "hw")


def test_fake_hw_validated_recipe_without_a_record_fails() -> None:
    """The AC: the committed fixture fails recipe-check."""
    report = check_recipes(FIXTURE / "recipes", repo_root=FIXTURE, validation_dir=FIXTURE / "validation" / "hw")
    assert not report.ok
    assert report.problems == [("recipes/basic/contact_resistor.yaml: status hw_validated without a reviewed record "
                               "validation/hw/basic.contact_resistor.yaml (blueprint v2 7.2; promotions follow the "
                               "hardware review)")]
    assert not (FIXTURE / "validation").exists()


def test_a_reviewed_matching_record_satisfies_the_rule(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _write(root, "basic.contact_resistor.yaml", _record(_digest(root)))
    _write(root, "README.md", "# reviewed records\n")
    report = _check(root)
    assert report.ok, report.problems
    assert report.recipes[0].record == "validation/hw/basic.contact_resistor.yaml"
    assert [r.problems for r in report.records] == [[]]
    assert "record:validation/hw/basic.contact_resistor.yaml" in format_report(report)


def test_the_promotion_itself_does_not_invalidate_the_record(tmp_path: Path) -> None:
    """Status, provenance, card and comments are outside the digest; parameters are inside."""
    root = _tree(tmp_path)
    digest = _digest(root)
    path = root / "recipes" / RECIPE
    text = path.read_text(encoding="utf-8")
    path.write_text("# promoted after the L2 review\n" + text.replace("validation_runs: []",
                                                                      f"validation_runs: [{RUN}]"), encoding="utf-8")
    assert _digest(root) == digest
    _write(root, "basic.contact_resistor.yaml", _record(digest))
    assert _check(root).ok
    path.write_text(text.replace("default: 21", "default: 31", 1), encoding="utf-8")
    assert _digest(root) != digest
    report = _check(root)
    assert not report.ok and any("pins another recipe definition" in p for p in report.problems)


@pytest.mark.parametrize("changes, message", [
    ({"reviewer": "", "reviewed_on": None}, "reviewer is empty"),
    ({"result": "fail"}, "validation/hw/ holds passing records only"),
    ({"result": ""}, "result is empty"),
    ({"runs": []}, "a recipe record lists its hardware runs"),
    ({"runs": ["S20261201T093012Z-1a2b"]}, "not a validation record: Value error, runs must be hardware runs"),
    ({"backend": "sim"}, "not a validation record"),
    ({"reviewed_on": None}, "a reviewed record gives reviewed_on"),
])  # fmt: skip
def test_an_unusable_record_is_a_problem(tmp_path: Path, changes: dict[str, Any], message: str) -> None:
    root = _tree(tmp_path)
    _write(root, "basic.contact_resistor.yaml", _record(_digest(root), **changes))
    report = _check(root)
    assert not report.ok
    assert any(message in p for p in report.problems), report.problems
    assert any("status hw_validated without a reviewed record" in p for p in report.problems)


def test_misnamed_unknown_and_stray_files_are_problems(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    digest = _digest(root)
    _write(root, "basic.contact_resistor.yaml", _record(digest))
    _write(root, "contact.yaml", _record(digest))
    _write(root, "mosfet.idvg.yaml", _record(digest, recipe_id="mosfet.idvg"))
    _write(root, "notes.txt", "x")
    _write(root, "stage-l1.yaml", _record(None, stage="L1", recipe_id=None, recipe_version=None, runs=[]))
    report = _check(root)
    problems = "\n".join(report.problems)
    assert "contact.yaml: a recipe record of basic.contact_resistor is named basic.contact_resistor.yaml" in problems
    assert "mosfet.idvg.yaml: no registered recipe mosfet.idvg" in problems
    assert "notes.txt: validation/hw/ holds <recipe_id>.yaml" in problems
    assert "stage-l1.yaml" not in problems  # a reviewed stage record is valid


def test_a_reviewed_record_of_an_unpromoted_recipe_is_a_note(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    digest = _digest(root)
    path = root / "recipes" / RECIPE
    path.write_text(path.read_text(encoding="utf-8").replace("status: hw_validated", "status: sim_validated"),
                    encoding="utf-8")
    _write(root, "basic.contact_resistor.yaml", _record(digest))
    report = _check(root)
    assert report.ok and report.notes == [("validation/hw/basic.contact_resistor.yaml is a reviewed record of a "
                                          "sim_validated recipe: promotion pending")]


def test_the_repository_holds_no_hardware_record() -> None:
    """Guardrail 6: until the owner's hardware session ``validation/hw/`` holds only its README."""
    assert sorted(p.name for p in (ROOT / "validation" / "hw").iterdir()) == ["README.md"]
    report = check_recipes()
    assert report.ok and report.records == [] and report.validation_dir == "validation/hw"
    assert all(r.status != "hw_validated" for r in report.recipes)


def test_cli_fails_on_the_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path)
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    for name in (ENV_CONFIG_DIR, ENV_DATA_DIR):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ENV_HOME, str(root))
    result = CliRunner().invoke(app, ["dev", "recipe-check"])
    assert result.exit_code == 1 and "status hw_validated without a reviewed record" in result.output
    _write(root, "basic.contact_resistor.yaml", _record(_digest(root)))
    result = CliRunner().invoke(app, ["dev", "recipe-check"])
    assert result.exit_code == 0, result.output
