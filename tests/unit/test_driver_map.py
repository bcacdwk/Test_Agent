"""Driver map (WP0.4): committed YAML stays consistent and reproducible from the archive tag.

These tests never import or read the working-tree legacy MCP package (removed in WP0.5): the consistency checks
run on the committed YAML alone, and the reproducibility check rebuilds from git tag `archive/v0.2-fake-mcp`
(skipped when git or the tag is unavailable, e.g. a shallow CI checkout without tags).
"""

from __future__ import annotations

import copy
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_driver_map.py"
MAP = ROOT / "references" / "driver-map" / "flex-driver-map.yaml"
SUMMARY = ROOT / "references" / "manuals" / "structured" / "b1500a-command-summary.yaml"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_driver_map", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


@pytest.fixture(scope="module")
def doc() -> dict:
    return yaml.safe_load(MAP.read_text(encoding="utf-8"))


def test_committed_map_passes_builder_checks(doc: dict) -> None:
    assert builder.check_map(doc) == []


def test_atom_and_flow_counts(doc: dict) -> None:
    assert doc["counts"]["atoms"] == {"A": 82, "B": 59, "C": 99, "D": 42, "total": 282}
    assert len(doc["atoms"]) == 282
    assert len({a["id"] for a in doc["atoms"]}) == 282
    assert doc["counts"]["flows"]["total"] == 97
    assert len({f["id"] for f in doc["flows"]}) == 97
    assert all(f["id"].startswith(f"{f['class']}_flow_") for f in doc["flows"])


def test_every_summary_command_is_mapped_or_unmapped(doc: dict) -> None:
    summary = yaml.safe_load(SUMMARY.read_text(encoding="utf-8"))
    names = {rec["command"] for rec in summary["commands"]}
    names |= {name for group in summary["grouped_command_index"] for name in group["commands"]}
    by_command = {c["command"]: c for c in doc["commands"]}
    allowed = set(doc["driver_targets"]) | {"unmapped"}
    missing = sorted(names - set(by_command))
    assert missing == []
    assert {name: by_command[name]["target"] for name in names if by_command[name]["target"] not in allowed} == {}


def test_targets_use_the_section_2_3_driver_vocabulary(doc: dict) -> None:
    methods = {
        "identify", "modules", "errors", "status_byte", "output_state", "abort", "zero", "disconnect", "reset",
        "self_test", "self_calibrate", "set_format", "set_integration", "set_range", "enable", "force_v",
        "staircase_v", "execute_and_read",
    }  # fmt: skip
    assert {f"B1500Driver.{m}" for m in methods} <= set(doc["driver_targets"])
    for atom in doc["atoms"]:
        assert atom["target"] == "unmapped" or set(atom["target"]) <= set(doc["driver_targets"]), atom["id"]
        assert atom["priority"] in ("m1", "m2", "later"), atom["id"]
    assert all(a["target"] == "unmapped" and a["flex"] == [] for a in doc["atoms"] if a["class"] == "D")
    m1_staircase = {"C_atom_smu_configure_staircase_sweep", "C_atom_smu_force_voltage", "C_atom_smu_execute"}
    assert {a["id"] for a in doc["atoms"] if a["priority"] == "m1"} >= m1_staircase


def test_render_is_deterministic(doc: dict) -> None:
    assert builder.render_yaml(doc) == MAP.read_text(encoding="utf-8")


def test_checks_detect_a_missing_command_and_a_missing_atom(doc: dict) -> None:
    broken = copy.deepcopy(doc)
    broken["commands"] = [c for c in broken["commands"] if c["command"] != "WV"]
    broken["atoms"] = broken["atoms"][1:]
    problems = builder.check_map(broken)
    assert any("'WV' missing" in p for p in problems)
    assert any(p.startswith("atom counts") for p in problems)


def _archive_tag_available() -> bool:
    if shutil.which("git") is None:
        return False
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{builder.DEFAULT_REF}^{{commit}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result.returncode == 0


@pytest.mark.skipif(not _archive_tag_available(), reason="git tag archive/v0.2-fake-mcp not available")
def test_builder_check_mode_reproduces_committed_map_from_archive_tag(capsys: pytest.CaptureFixture[str]) -> None:
    assert builder.main(["--check"]) == 0, capsys.readouterr().err
