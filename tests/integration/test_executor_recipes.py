"""Other recipes and failure paths at the executor level: ``system.*`` on the simulator, ``generic.smu_staircase``,
a fault during acquisition (raw kept, cleanup verified, run archived as failed), compliance flags. These tests
validate ``system.self_test``, ``system.self_cal`` and ``generic.smu_staircase`` on the simulator."""

from __future__ import annotations

import json

import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.analysis.dataset import find_run
from b1500_test_agent.archive import read_audit
from tests.integration.helpers import World, plan, run


@pytest.mark.parametrize(("recipe_id", "reason", "query"), [
    ("system.self_test", "system_self_test", "*TST?"),
    ("system.self_cal", "system_self_cal", "*CAL?"),
])
def test_system_recipes_on_the_simulator(world: World, recipe_id: str, reason: str, query: str) -> None:
    executor = world.executor()
    record = plan(executor, recipe_id=recipe_id, dut_profile=None)
    assert record.tier == "needs_confirmation" and record.rules.confirm_reasons == [reason]
    assert record.flex_preview == [query] and record.envelope.channels == {}
    assert record.summary == f"{recipe_id}@1 | no outputs | DUT none | pins mosfet-4t | sim | R-ALWAYS-01 {reason}"
    assert run(executor, record.plan_id).error_code == "confirmation_required"
    result = run(executor, record.plan_id, record.summary)
    assert result.ok and result.outcome == "completed" and result.cleanup_verified == "sim_state", result.message
    assert result.quality_verdict is None and result.analyses == []
    folder = find_run(result.run_id, data_root=world.data)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind_result"] == {"operation": recipe_id.split(".")[1], "result": 0, "failed_units": ""}
    assert not (folder / "data.csv").exists() and "raw/block-000.txt" not in manifest["files"]
    assert [r.command for r in world.sim_log() if r.command == query] == [query]
    assert not [r for r in world.sim_log() if r.source]


def test_system_recipes_are_not_implemented_on_hardware(world: World) -> None:
    registry = world.executor().registry()
    assert registry.effective_status("system.self_test", "visa") == "not_implemented"
    assert registry.effective_status("system.self_test", "sim") == registry.get("system.self_test").status


def test_last_self_calibration_reaches_rule_r_cal_01(world: World) -> None:
    executor = world.executor()
    cal = plan(executor, recipe_id="system.self_cal", dut_profile=None)
    cal_run = run(executor, cal.plan_id, cal.summary)
    measurement = run(executor, plan(executor).plan_id)
    manifest = load_run(measurement.run_id, data_root=world.data).manifest
    pre = manifest.rules[1]
    assert pre.phase == "pre_execute"
    infos = [f.message for f in pre.findings if f.rule_id == "R-CAL-01" and f.severity == "info"]
    assert any(cal_run.run_id in message for message in infos), pre.findings


def test_generic_staircase_with_a_matching_pin_map(world: World) -> None:
    world.write_config("pinmaps/generic-3t.yaml", {"certainty": "verified",
                                                    "terminals": {"sweep": 3, "bias": 1, "ground": "GNDU"}})
    world.write_config("duts/generic-3t.yaml", {"device_type": "nmos", "terminals": {
        "sweep": {"max_abs_v": 2.0, "max_abs_i": 1e-3}, "bias": {"max_abs_v": 2.0, "max_abs_i": 1e-3},
        "ground": {"max_abs_v": 0.0, "max_abs_i": 1e-2}}})
    executor = world.executor()
    record = plan(executor, recipe_id="generic.smu_staircase", pin_map="generic-3t", dut_profile="generic-3t",
                  params={"start": 0.0, "stop": 1.5, "points": 31, "icomp": 1e-3, "mode": "double",
                          "bias_v": 1.5, "bias_icomp": 1e-5})
    assert record.tier == "ok", record.rules.findings
    result = run(executor, record.plan_id)
    assert result.outcome == "completed" and result.quality_verdict == "ok", result.message
    data = load_run(result.run_id, data_root=world.data)
    table = data.table
    assert len(table) == 62 and list(table["segment"].unique()) == ["fwd", "rev"]
    assert table["sweep_V"].iloc[30] == pytest.approx(1.5) and table["bias_V"].unique().tolist() == [1.5]
    fwd = table[table["segment"] == "fwd"]
    assert fwd["sweep_I"].iloc[-1] > 1e-5 > abs(fwd["sweep_I"].iloc[0])  # output curve of nmos_basic at Vg 1.5 V


def test_failure_during_acquisition_keeps_raw_data(world: World) -> None:
    world.use_faults("garbage", [{"kind": "garbage_data", "at_step": 5}])
    executor = world.executor()
    record = plan(executor)
    result = run(executor, record.plan_id)
    assert (result.ok, result.status, result.outcome, result.error_code) == \
        (False, "error", "failed", "instrument_error")
    assert result.cleanup_verified == "sim_state" and result.run_id is not None
    folder = find_run(result.run_id, data_root=world.data)
    raw = (folder / "raw/block-000.txt").read_text(encoding="latin-1")
    assert raw.count(",") == 101 * 3 - 1
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "failed" and "FlexParseError" in manifest["message"]
    assert manifest["cleanup"]["verified"] == "sim_state" and not manifest["cleanup"]["latched_fault"]
    assert "raw/block-000.txt" in manifest["files"] and not (folder / "data.csv").exists()
    index = [json.loads(line) for line in (world.runs_dir / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(e["run_id"], e["outcome"]) for e in index] == [(result.run_id, "failed")]
    events = [e.ev for e in read_audit(folder)]
    assert events.count("data_block") == 1 and "cleanup_verified" in events
    log = world.sim_log("nmos_garbage")
    last_source = max(r.seq for r in log if r.source)
    assert {"DZ", "CL"} <= {r.mnemonic for r in log if r.seq > last_source and r.outcome == "ok"}


def test_compliance_aborts_the_sweep_and_flags_the_run(world: World) -> None:
    world.use_faults("compliance", [{"kind": "compliance_at", "step": 60, "ch": 3}])
    executor = world.executor()
    result = run(executor, plan(executor).plan_id)
    assert result.ok and result.outcome == "completed_with_flags", result.message
    assert result.quality_verdict == "untrusted" and result.status_counts["C"] == 1
    assert result.status_counts["V"] == 2 * 40  # automatic abort (WM 2): later steps read 199.999E+99
    assert result.analyses[0].outcome == "refused" and "data quality untrusted" in result.message
    manifest = load_run(result.run_id, data_root=world.data).manifest
    assert {f.rule_id for f in manifest.quality_findings} == {"R-QUAL-01", "R-QUAL-02", "R-QUAL-03"}
