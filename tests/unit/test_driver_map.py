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


# -- coverage ledger (blueprint v2 9, WP7.7: the SMU rows) -----------------------------------------------------------


@pytest.mark.smu
def test_every_smu_entry_is_mapped_or_out_of_scope_with_a_reason(doc: dict) -> None:
    ledger = doc["counts"]["ledger"]
    assert set(ledger) == set(builder.LEDGER_FAMILIES) and {"smu", "cmu"} <= set(builder.CLOSED_FAMILIES)
    smu = ledger["smu"]
    assert {kind: smu[kind]["open"] for kind in ("atoms", "flows", "commands")} == {"atoms": 0, "flows": 0,
                                                                                     "commands": 0}
    assert smu["atoms"]["mapped"] >= 40 and smu["flows"]["mapped"] >= 20 and smu["commands"]["mapped"] >= 60
    for entry in [*doc["atoms"], *doc["flows"], *doc["commands"]]:
        assert entry["scope"] in ("mapped", "out_of_scope", "open")
        if entry["scope"] == "out_of_scope":
            assert entry["reason"]
    by_command = {c["command"]: c for c in doc["commands"]}
    for mnemonic in ("FL", "SSR", "AZ", "AV", "RM", "WNCC"):  # blueprint v2 1.2 in-scope SMU conditioning
        assert by_command[mnemonic]["scope"] == "mapped" and by_command[mnemonic]["family"] == "smu"
    for mnemonic in ("TI", "TDV", "DSMPLARM", "HVSMUOP"):  # blueprint v2 1.2 out-of-scope column
        assert by_command[mnemonic]["scope"] == "out_of_scope"
    assert by_command["MSP"]["family"] == "spgu" and by_command["SSP"]["family"] == "cmu"
    assert by_command["QSV"]["family"] == "cmu"  # QSCV belongs to the CMU work package (8.5)
    flows = {f["id"]: f for f in doc["flows"]}
    assert flows["C_flow_search_smu_target"]["target"] == ["recipe:mosfet.vth_search", "recipe:basic.breakdown_search",
                                                            "kind:smu_search"]
    assert flows["C_flow_sweep_smu_qscv"]["family"] == "cmu"


@pytest.mark.smu
def test_ledger_check_rejects_open_smu_entries_and_bad_flow_targets(doc: dict) -> None:
    broken = copy.deepcopy(doc)
    command = next(c for c in broken["commands"] if c["command"] == "FL")
    command.update(scope="open")
    flow = next(f for f in broken["flows"] if f["id"] == "C_flow_pulse_smu_spot")
    flow["target"] = ["recipe:basic.no_such_recipe", "B1500Driver.no_such_method", "plot:iv"]
    oos = next(c for c in broken["commands"] if c["command"] == "TI")
    del oos["reason"]
    problems = builder.check_ledger(broken["atoms"], broken["flows"], broken["commands"])
    assert any("command FL: smu entry is neither mapped nor out_of_scope" in p for p in problems)
    assert any("recipe basic.no_such_recipe does not exist" in p for p in problems)
    assert any("B1500Driver.no_such_method is not a driver target" in p for p in problems)
    assert any("'plot:iv' is not recipe:/kind:/analysis:" in p for p in problems)
    assert any("command TI: out_of_scope without a reason" in p for p in problems)


# -- coverage ledger: the CMU rows (WP8.6; MFCMU + SCUU + QSCV; the GNDU has no legacy atom, flow or command) ------


@pytest.mark.cmu
def test_every_cmu_entry_is_mapped_or_out_of_scope_with_a_reason(doc: dict) -> None:
    cmu = doc["counts"]["ledger"]["cmu"]
    assert {kind: cmu[kind]["open"] for kind in ("atoms", "flows", "commands")} == {"atoms": 0, "flows": 0,
                                                                                     "commands": 0}
    assert cmu["atoms"]["mapped"] >= 40 and cmu["flows"]["mapped"] >= 18 and cmu["commands"]["mapped"] >= 43
    by_command = {c["command"]: c for c in doc["commands"]}
    for mnemonic in ("CORRDT?", "CORRL?", "DCORR?", "CORR?", "ADJ?", "SSP", "QSZ", "WMDCV", "MTDCV"):  # 1.2 in scope
        assert by_command[mnemonic]["scope"] == "mapped" and by_command[mnemonic]["family"] == "cmu", mnemonic
    assert by_command["CORRDT?"]["target"] == "B1500Driver.correction_data"
    assert by_command["CORRDT?"]["pdf_pages"] == [384]
    for mnemonic in ("TC", "TTC", "TMACV", "TMDCV", "TACV", "TDCV"):  # high-speed spot C, timer-start outputs
        assert by_command[mnemonic]["scope"] == "out_of_scope" and by_command[mnemonic]["reason"], mnemonic
    flows = {f["id"]: f for f in doc["flows"]}
    assert flows["C_flow_sweep_cmu_cv"]["target"][0] == "recipe:moscap.cv"
    assert "recipe:cmu.correction_short" in flows["B_flow_correction_cmu_open_short_load"]["target"]
    assert flows["C_flow_spot_cmu_high_speed"]["scope"] == "out_of_scope"
    atoms = {a["id"]: a for a in doc["atoms"]}
    assert atoms["A_atom_flex_query_cmu_correction_data"]["target"] == ["B1500Driver.correction_data"]
    assert atoms["D_atom_extract_cv_cox"]["successor"].startswith("analysis.cv_cox")
    assert not [e for e in [*doc["atoms"], *doc["flows"], *doc["commands"]]
                if "gndu" in str(e.get("id", e.get("command"))).lower()]  # GNDU: v2 only (R-GNDU-01, sim budget)


@pytest.mark.cmu
def test_ledger_check_rejects_an_open_cmu_entry(doc: dict) -> None:
    broken = copy.deepcopy(doc)
    next(c for c in broken["commands"] if c["command"] == "CORRDT?").update(scope="open")
    next(f for f in broken["flows"] if f["id"] == "C_flow_sweep_cmu_cf").update(scope="open")
    problems = builder.check_ledger(broken["atoms"], broken["flows"], broken["commands"])
    assert any("command CORRDT?: cmu entry is neither mapped nor out_of_scope" in p for p in problems)
    assert any("flow C_flow_sweep_cmu_cf: cmu entry is neither mapped nor out_of_scope" in p for p in problems)


@pytest.mark.parametrize(("entry_id", "family"), [
    ("C_atom_smu_force_voltage", "smu"), ("C_atom_smu_configure_qscv", "cmu"),
    ("B_atom_routing_asu_set_path", "smu"), ("C_atom_hvsmu_execute_iv", "smu"),
    ("B_atom_output_b1500_zero_all", "system"), ("D_atom_extract_transfer_vth", "smu"),
    ("D_atom_extract_cv_cox", "cmu"), ("C_flow_pulse_spgu_train", "spgu"), ("A_atom_easyexpert_identify", "system"),
    ("CD_flow_screen_iv_leakage", "smu"), ("A_flow_snapshot_flex_status", "system"),
])
def test_entry_families(entry_id: str, family: str) -> None:
    assert builder.entry_family(entry_id) == family
