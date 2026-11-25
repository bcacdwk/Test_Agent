"""Driver map (WP0.4): committed YAML stays consistent and reproducible from the archive tag.

These tests never import or read the working-tree legacy MCP package (removed in WP0.5): the consistency checks
run on the committed YAML alone, and the reproducibility check rebuilds from git tag `archive/v0.2-fake-mcp`
(skipped when git or the tag is unavailable, e.g. a shallow CI checkout without tags).
"""

from __future__ import annotations

import copy
import importlib.util
import re
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
# -- coverage ledger: the HV-SPGU and 16440A selector rows (WP9.6) ---------------------------------------------------


@pytest.mark.spgu
def test_every_spgu_entry_is_mapped_or_out_of_scope_with_a_reason(doc: dict) -> None:
    """Blueprint v2 1.2 HV-SPGU and 16440A rows: the PG/ALWG settings, the run control, CORRSER? and ERMOD/ERSSP(?)
    are mapped; setup read-backs, the SPGU as a sampling source and raw digital I/O are out of scope with a reason."""
    assert {"smu", "cmu", "spgu"} <= set(builder.CLOSED_FAMILIES)
    spgu = doc["counts"]["ledger"]["spgu"]
    assert {kind: spgu[kind]["open"] for kind in ("atoms", "flows", "commands")} == {"atoms": 0, "flows": 0,
                                                                                     "commands": 0}
    by_command = {c["command"]: c for c in doc["commands"]}
    in_scope = ("SIM", "SPRM", "SPPER", "SER", "SPM", "SPT", "SPV", "ODSW", "STGP", "ALW", "ALS", "SPUPD", "SRP",
                "SPP", "SPST?", "CORRSER?", "ERMOD", "ERMOD?", "ERSSP", "ERSSP?")
    for mnemonic in in_scope:
        assert (by_command[mnemonic]["scope"], by_command[mnemonic]["family"]) == ("mapped", "spgu"), mnemonic
    assert sum(c["family"] == "spgu" and c["scope"] == "mapped" for c in doc["commands"]) == len(in_scope)
    for mnemonic in ("SIM?", "SPV?", "SER?", "ALW?", "MSP", "ERM", "ERC", "ERS?"):
        assert by_command[mnemonic]["scope"] == "out_of_scope" and by_command[mnemonic]["reason"], mnemonic
    assert "blueprint v2 1.2" in by_command["ERC"]["reason"] and "ERSSP?" in by_command["ERC"]["reason"]
    for mnemonic in ("SOPC", "SOPC?", "SOVC", "SOVC?"):  # expander output comparison, not an SPGU function
        assert (by_command[mnemonic]["family"], by_command[mnemonic]["scope"]) == ("smu", "out_of_scope")
        assert "HVMCU" in by_command[mnemonic]["reason"]
    flows = {f["id"]: f for f in doc["flows"]}
    assert flows["C_flow_pulse_spgu_train"]["target"] == ["recipe:spgu.pulse_train", "kind:spgu_pulse"]
    assert flows["C_flow_waveform_spgu_sequence"]["target"] == ["recipe:spgu.alwg_sequence", "kind:spgu_pulse"]
    assert flows["C_flow_sampling_smu_spgu_bias"]["scope"] == "out_of_scope"


@pytest.mark.spgu
def test_spgu_atoms_whose_legacy_command_v2_replaces_map_to_their_successor(doc: dict) -> None:
    """CNX (enable) and ERS? (raw digital I/O bits, read as "selector status" by v0.2) are served by CN and ERSSP?:
    the atoms are mapped to those driver targets and keep the legacy command as ``unmapped_flex``."""
    atoms = {a["id"]: a for a in doc["atoms"]}
    enable, status = atoms["B_atom_output_spgu_enable_channels"], atoms["A_atom_flex_query_selector_status"]
    assert (enable["target"], enable["unmapped_flex"]) == (["B1500Driver.enable"], ["CNX"])
    assert (status["target"], status["unmapped_flex"]) == (["B1500Driver.selector_state"], ["ERS?"])
    assert all(a["scope"] == "mapped" and a["note"].startswith("successor: ") for a in (enable, status))
    assert {a for a in builder.ATOM_SUCCESSORS if builder.entry_family(a) == "spgu"} == {
        "B_atom_output_spgu_enable_channels", "A_atom_flex_query_selector_status"}
    for atom_id in ("A_atom_flex_query_spgu_open_comp", "B_atom_correction_spgu_set_short_comp",
                    "A_atom_flex_query_spgu_setup", "C_atom_spgu_configure_sampling_pulse",
                    "B_atom_routing_dio_set_mode"):
        assert atoms[atom_id]["scope"] == "out_of_scope" and atoms[atom_id]["family"] == "spgu", atom_id


@pytest.mark.spgu
def test_ledger_check_rejects_open_spgu_entries(doc: dict) -> None:
    broken = copy.deepcopy(doc)
    command = next(c for c in broken["commands"] if c["command"] == "SPV?")
    command.update(scope="open")
    del command["reason"]
    flow = next(f for f in broken["flows"] if f["id"] == "C_flow_pulse_spgu_train")
    flow.update(scope="open")
    del flow["target"]
    problems = builder.check_ledger(broken["atoms"], broken["flows"], broken["commands"])
    assert any("command SPV?: spgu entry is neither mapped nor out_of_scope" in p for p in problems)
    assert any("flow C_flow_pulse_spgu_train: spgu entry is neither mapped nor out_of_scope" in p for p in problems)


# -- coverage ledger: the WGFMU and RSU rows (WP10.8) -----------------------------------------------------------------


@pytest.mark.wgfmu
def test_every_wgfmu_entry_is_mapped_or_out_of_scope_with_a_reason(doc: dict) -> None:
    """Blueprint v2 1.2 WGFMU + RSU row: session, initialize, self-test/cal, modes, ranges, patterns/vectors, events,
    sequences, execute/wait/abort, chunked readback, DC force/measure, connect/disconnect and the error and warning
    queues are mapped onto the WGFMU targets; log file, ASCII export, realtime event reads, setup read-backs, pattern
    edits, trigger output and delay trims are out of scope with a reason (WP10.8 handoff of 10.3)."""
    assert {"smu", "cmu", "spgu", "wgfmu"} <= set(builder.CLOSED_FAMILIES)
    wgfmu = doc["counts"]["ledger"]["wgfmu"]
    assert {kind: wgfmu[kind]["open"] for kind in ("atoms", "flows", "commands")} == {"atoms": 0, "flows": 0,
                                                                                       "commands": 0}
    assert wgfmu["atoms"]["mapped"] >= 41 and wgfmu["flows"]["mapped"] >= 13
    atoms = {a["id"]: a for a in doc["atoms"]}
    expected = {
        "A_atom_wgfmu_open_session": ["Transaction.wgfmu_phase", "WgfmuLink.read_live"],
        "A_atom_wgfmu_close_session": ["WgfmuLink.safe_state_step"],
        "C_atom_wgfmu_add_vectors": ["WgfmuDriver.load"], "C_atom_wgfmu_execute": ["WgfmuDriver.run"],
        "C_atom_wgfmu_read_measurement_values": ["WgfmuDriver.read"], "B_atom_output_wgfmu_connect":
        ["WgfmuDriver.connect"], "B_atom_diagnostic_wgfmu_self_test": ["WgfmuDriver.maintenance"],
        "C_atom_wgfmu_dc_force_measure": ["WgfmuDriver.force_dc", "WgfmuDriver.measure_dc"],
        "A_atom_wgfmu_wait_until_completed": ["WgfmuApi.wait_until_completed"],
        "A_atom_wgfmu_read_warning_summary": ["WgfmuDriver.warnings"],  # read after every run (orchestrator, 1.2)
        "A_atom_wgfmu_set_warning_level": ["WgfmuApi.set_warning_level"],
        "B_atom_policy_wgfmu_treat_warnings_as_errors": ["WgfmuApi.treat_warnings_as_errors"],
    }
    for atom_id, target in expected.items():
        assert (atoms[atom_id]["target"], atoms[atom_id]["scope"]) == (target, "mapped"), atom_id
    assert atoms["C_atom_wgfmu_add_vectors"]["unmapped_wgfmu"] == ["WGFMU_addVector"]  # one call per pattern
    for atom_id in ("A_atom_wgfmu_open_log", "A_atom_wgfmu_export_ascii",
                    "A_atom_wgfmu_is_event_completed", "C_atom_wgfmu_transform_pattern",
                    "C_atom_wgfmu_set_trigger_event", "C_atom_wgfmu_configure_force_measure_delay"):
        assert atoms[atom_id]["scope"] == "out_of_scope" and atoms[atom_id]["reason"], atom_id
    assert "blueprint v2 1.2" in atoms["C_atom_wgfmu_set_trigger_out_mode"]["reason"]
    flows = {f["id"]: f for f in doc["flows"]}
    assert flows["C_flow_spot_wgfmu_dc"]["target"][0] == "recipe:wgfmu.dc_spot"
    assert "recipe:system.wgfmu_self_test" in flows["B_flow_maintenance_wgfmu_self_test_calibration"]["target"]
    assert flows["AB_flow_recovery_wgfmu_abort_disconnect"]["target"] == ["WgfmuLink.safe_state_step"]
    assert flows["A_flow_prepare_wgfmu_logging"]["scope"] == "out_of_scope"


@pytest.mark.wgfmu
def test_wgfmu_targets_name_real_methods_and_every_bound_function() -> None:
    """Every WGFMU target names a method of its class, and the function table covers exactly the C functions the
    protocol binds (``C_FUNCTIONS``): a library call the binding makes is mapped, one it never makes is not."""
    from b1500_test_agent.driver.wgfmu import WgfmuDriver
    from b1500_test_agent.session.transaction import Transaction
    from b1500_test_agent.session.wgfmu_phase import WgfmuLink
    from b1500_test_agent.transport.wgfmu.api import API_METHODS, C_FUNCTIONS

    owners = {"WgfmuDriver": WgfmuDriver, "WgfmuLink": WgfmuLink, "Transaction": Transaction}
    for target in builder.WGFMU_TARGETS:
        owner, method = target.split(".", 1)
        if owner == "WgfmuApi":
            assert method in API_METHODS, target
        else:
            assert callable(getattr(owners[owner], method, None)), target
    bound = {name for names in C_FUNCTIONS.values() for name in names}
    assert set(builder.WGFMU_FUNCTION_TARGETS) == bound
    for function, targets in builder.WGFMU_FUNCTION_TARGETS.items():
        assert targets and set(targets) <= set(builder.WGFMU_TARGETS), function
    for method, functions in C_FUNCTIONS.items():  # a protocol method no driver calls is its own target
        api_targets = {t for f in functions for t in builder.WGFMU_FUNCTION_TARGETS[f] if t.startswith("WgfmuApi.")}
        assert api_targets <= {f"WgfmuApi.{method}"}, method


@pytest.mark.wgfmu
def test_wgfmu_successor_atoms_keep_the_legacy_function(doc: dict) -> None:
    atoms = {a["id"]: a for a in doc["atoms"]}
    summary = atoms["A_atom_wgfmu_read_error_summary"]
    assert summary["target"] == ["WgfmuApi.errors"] and summary["note"].startswith("successor: ")
    assert summary["unmapped_wgfmu"] == ["WGFMU_getErrorSummarySize", "WGFMU_getErrorSummary"]
    assert atoms["B_atom_lifecycle_wgfmu_abort_channel"]["unmapped_wgfmu"] == ["WGFMU_abortChannel"]
    assert atoms["C_atom_wgfmu_dc_measure_averaged"]["target"] == ["WgfmuDriver.measure_dc"]
    assert {a for a in builder.ATOM_SUCCESSORS if builder.entry_family(a) == "wgfmu"} == {
        "A_atom_wgfmu_read_error_summary", "A_atom_wgfmu_get_measure_times", "B_atom_lifecycle_wgfmu_abort_channel",
        "C_atom_wgfmu_dc_measure_averaged"}


@pytest.mark.wgfmu
def test_ledger_check_rejects_open_wgfmu_entries_and_unknown_wgfmu_targets(doc: dict) -> None:
    broken = copy.deepcopy(doc)
    atom = next(a for a in broken["atoms"] if a["id"] == "A_atom_wgfmu_export_ascii")
    atom.update(scope="open")
    del atom["reason"]
    flow = next(f for f in broken["flows"] if f["id"] == "C_flow_spot_wgfmu_dc")
    flow["target"] = ["WgfmuDriver.no_such_method"]
    problems = builder.check_ledger(broken["atoms"], broken["flows"], broken["commands"])
    assert any("atom A_atom_wgfmu_export_ascii: wgfmu entry is neither mapped nor out_of_scope" in p for p in problems)
    assert any("WgfmuDriver.no_such_method is not a driver target" in p for p in problems)


# -- coverage ledger: the system rows and the closure of every family (WP11.2) -----------------------------------------


def test_every_family_is_closed_and_no_entry_is_open(doc: dict) -> None:
    """Blueprint v2 0 row 1, 3, 9: after M11 every atom, flow and command is mapped or out of scope with a reason."""
    assert builder.CLOSED_FAMILIES == builder.LEDGER_FAMILIES == ("smu", "cmu", "spgu", "wgfmu", "system")
    ledger = doc["counts"]["ledger"]
    assert {family: sum(ledger[family][kind]["open"] for kind in ("atoms", "flows", "commands"))
            for family in builder.LEDGER_FAMILIES} == dict.fromkeys(builder.LEDGER_FAMILIES, 0)
    entries = [*doc["atoms"], *doc["flows"], *doc["commands"]]
    assert [e.get("id", e.get("command")) for e in entries if e["scope"] == "open"] == []
    assert all(e["reason"] for e in entries if e["scope"] == "out_of_scope")
    assert sum(e["scope"] == "mapped" for e in entries) + sum(e["scope"] == "out_of_scope" for e in entries) == (
        282 + 97 + 280)


def test_check_mode_reports_zero_unmapped_entries(capsys: pytest.CaptureFixture[str]) -> None:
    """AC ``build_driver_map.py --check`` -> 0 unmapped: the ledger line of the check output (no git needed: the
    committed YAML is checked through ``check_map`` and the line comes from its counts)."""
    if not _archive_tag_available():
        pytest.skip("git tag archive/v0.2-fake-mcp not available")
    assert builder.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "ledger (5/5 families closed): " in out and " 0 unmapped (open)" in out


def test_an_open_system_entry_fails_the_check(doc: dict) -> None:
    broken = copy.deepcopy(doc)
    command = next(c for c in broken["commands"] if c["command"] == "ST")
    command.update(scope="open")
    del command["reason"]
    flow = next(f for f in broken["flows"] if f["id"] == "A_flow_discover_flex_session")
    flow["target"] = ["tool:no_such_tool", "Session.no_such_method", "kind:no_such_kind"]
    problems = builder.check_ledger(broken["atoms"], broken["flows"], broken["commands"])
    assert any("command ST: system entry is neither mapped nor out_of_scope" in p for p in problems)
    assert any("no_such_tool is not one of the ten MCP tools" in p for p in problems)
    assert any("Session.no_such_method is not a driver target" in p for p in problems)
    assert any("kind no_such_kind is no recipe's kind" in p for p in problems)


def test_system_entries_follow_blueprint_section_1_2(doc: dict) -> None:
    """System row of blueprint v2 1.2: the in-scope commands are mapped; program memory, *SRE, ERR? and EasyEXPERT
    remote control are out of scope, and every other system command has a written reason (WP11.2)."""
    by_command = {c["command"]: c for c in doc["commands"]}
    in_scope = ("*IDN?", "UNT?", "ERRX?", "*STB?", "*OPC?", "LOP?", "*LRN?", "*TST?", "*CAL?", "CM", "AB", "DZ", "CL",
                "FMT", "TSC", "TSR")
    for mnemonic in in_scope:
        assert (by_command[mnemonic]["family"], by_command[mnemonic]["scope"]) == ("system", "mapped"), mnemonic
    assert by_command["*RST"]["scope"] == "mapped"  # only kind system may call it (lint)
    for mnemonic in ("ST", "END", "DO", "RU", "SCR", "LST?", "VAR", "VAR?"):
        assert "program memory" in by_command[mnemonic]["reason"] and "blueprint v2 1.2" in by_command[mnemonic][
            "reason"], mnemonic
    assert "blueprint v2 1.2" in by_command["*SRE"]["reason"] and "blueprint v2 1.2" in by_command["ERR?"]["reason"]
    assert "servicing" in by_command["RCV"]["reason"] and "*CAL?" in by_command["CA"]["reason"]
    system = [c for c in doc["commands"] if c["family"] == "system"]
    assert {c["scope"] for c in system} == {"mapped", "out_of_scope"} and len(system) == 59
    atoms = {a["id"]: a for a in doc["atoms"]}
    easyexpert = [a for a in doc["atoms"] if "easyexpert" in a["id"].split("_")]
    assert easyexpert and all(a["scope"] == "out_of_scope" and "EasyEXPERT" in a["reason"] for a in easyexpert)
    flows = {f["id"]: f for f in doc["flows"]}
    assert all(f["scope"] == "out_of_scope" for f in doc["flows"] if "easyexpert" in f["id"].split("_"))
    assert flows["A_flow_discover_flex_session"]["target"][0] == "tool:station_status"
    assert "tool:safe_shutdown" in flows["B_flow_emergency_b1500_abort_zero"]["target"]
    assert "recipe:system.self_cal" in flows["AB_flow_maintenance_flex_self_test_calibration"]["target"]
    successors = {"A_atom_flex_lookup_error": ["B1500Driver.errors"],
                  "B_atom_output_b1500_confirm_zero": ["B1500Driver.output_state"],
                  "B_atom_safety_b1500_check_interlock": ["B1500Driver.status_byte"],
                  "A_atom_flex_read_timestamp": ["B1500Driver.set_time_stamp", "B1500Driver.reset_timer"],
                  "A_atom_flex_disconnect": ["Session.close"]}
    for atom_id, target in successors.items():
        assert (atoms[atom_id]["target"], atoms[atom_id]["scope"]) == (target, "mapped"), atom_id
    for atom_id in ("D_atom_derive_dataset_summarize_columns", "D_atom_assess_value_check_limits",
                    "D_atom_assess_dataset_check_envelope", "D_atom_render_run_build_report"):
        assert atoms[atom_id]["successor"] and atoms[atom_id]["scope"] == "mapped", atom_id


def test_session_targets_and_tools_name_real_methods_and_the_ten_tools() -> None:
    from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
    from b1500_test_agent.catalog.kinds import default_kinds
    from b1500_test_agent.service.common import TOOL_NAMES
    from b1500_test_agent.session.session import Session

    assert builder.MCP_TOOLS == TOOL_NAMES
    for target in builder.SESSION_TARGETS:
        owner, method = target.split(".", 1)
        assert owner == "Session" and callable(getattr(Session, method, None)), target
    kinds = set(default_kinds())
    for flow, targets in builder.FLOW_TARGETS.items():
        for target in targets:
            prefix, _, value = target.partition(":")
            if prefix == "kind":
                assert value in kinds, (flow, target)
            elif prefix == "analysis":
                assert value in ANALYSIS_METHODS, (flow, target)


def test_readme_counts_match_the_map(doc: dict) -> None:
    """The count table and the priority table of references/driver-map/README.md say what the YAML says."""
    text = (MAP.parent / "README.md").read_text(encoding="utf-8")
    ledger = doc["counts"]["ledger"]
    total = {kind: [0, 0] for kind in ("atoms", "flows", "commands")}
    for family in builder.LEDGER_FAMILIES:
        cells = []
        for kind in ("atoms", "flows", "commands"):
            mapped, out = ledger[family][kind]["mapped"], ledger[family][kind]["out_of_scope"]
            total[kind][0] += mapped
            total[kind][1] += out
            cells.append(f"{mapped} / {out}")
        assert f"| {family} | {' | '.join(cells)} |" in text, family
    assert "| total | " + " | ".join(f"{m} / {o}" for m, o in total.values()) + " |" in text
    for priority, count in doc["counts"]["atoms_by_priority"].items():
        assert re.search(rf"^\| `{priority}` \|.*\| {count} \|$", text, re.MULTILINE), priority
    assert f"stays `unmapped` on {doc['counts']['atoms_unmapped']} atoms" in text


@pytest.mark.parametrize(("entry_id", "family"), [
    ("C_atom_smu_force_voltage", "smu"), ("C_atom_smu_configure_qscv", "cmu"),
    ("B_atom_routing_asu_set_path", "smu"), ("C_atom_hvsmu_execute_iv", "smu"),
    ("B_atom_output_b1500_zero_all", "system"), ("D_atom_extract_transfer_vth", "smu"),
    ("D_atom_extract_cv_cox", "cmu"), ("C_flow_pulse_spgu_train", "spgu"), ("A_atom_easyexpert_identify", "system"),
    ("CD_flow_screen_iv_leakage", "smu"), ("A_flow_snapshot_flex_status", "system"),
])
def test_entry_families(entry_id: str, family: str) -> None:
    assert builder.entry_family(entry_id) == family
