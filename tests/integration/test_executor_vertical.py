"""Vertical path at the executor level (blueprint 8.1 ``integration/``, M1): plan → run → archive → ``load_run`` →
``vth_linear_extrapolation`` on ``nmos_basic``, the run folder contract of blueprint 2.7, plan identity and die
batches. This test validates recipe ``mosfet.idvg`` on the simulator (its ``status: sim_validated``)."""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from b1500_test_agent.analysis import load_run, vth_linear_extrapolation, with_trust
from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.archive import read_audit
from b1500_test_agent.config import load_config
from b1500_test_agent.transport.sim.devices import Circuit
from tests.integration.helpers import IDVG, MCP, World, plan, run

VTH0 = 0.42
"""Truth of config/sim/scenarios/nmos_basic.yaml."""


def noiseless_reference(world: World, data: RunData) -> RunData:
    """The run's table with the drain current replaced by the noiseless model current at the same gate voltages."""
    scenario = load_config(world.paths).sim_scenario
    assert scenario is not None and scenario.name == "nmos_basic"
    circuit = Circuit(scenario)
    vd = data.param("vd").as_float()  # type: ignore[union-attr]
    table = pd.DataFrame({
        "step": data.table["step"],
        "gate_V": data.table["gate_V"],
        "drain_I": [circuit.channel_currents({1: vg, 3: vd})[3] for vg in data.table["gate_V"]],
        "drain_I_status": "N",
    })
    return RunData(manifest=data.manifest, table=with_trust(table))


def test_vertical_path_idvg_vth(world: World) -> None:
    executor = world.executor()
    record = plan(executor, label="W3 batch")
    assert record.tier == "ok", record.rules.findings
    assert record.summary == ("mosfet.idvg@1 | drain=SMU3(HRSMU) bias 0.05 V Icomp 1 mA; gate=SMU1(MPSMU) sweep "
                              "-1..3 V Icomp 1 uA | DUT nmos-generic | pins mosfet-4t | sim")
    result = run(executor, record.plan_id, dut="W3-D12")
    assert result.ok and result.status == "ok" and result.outcome == "completed", result.message
    assert result.simulated and result.backend == "sim" and result.cleanup_verified == "sim_state"
    assert result.status_counts == {"N": 202} and result.quality_verdict == "ok"

    data = load_run(result.run_id, data_root=world.data)  # verifies data.csv against the manifest sha256
    assert len(data.table) == 101 and data.measured_columns == ["gate_I", "drain_I"]
    assert data.source_columns == ["gate_V", "drain_V"]
    vth = vth_linear_extrapolation(data, criteria=executor.registry().get("mosfet.idvg").quality)
    reference = vth_linear_extrapolation(noiseless_reference(world, data))
    assert vth.outcome == "ok" and reference.outcome == "ok"
    assert vth.value == pytest.approx(reference.value, abs=0.030)
    assert vth.value == pytest.approx(VTH0, abs=0.100)
    assert result.analyses[0].method == "vth_linear_extrapolation"
    assert result.analyses[0].value == pytest.approx(vth.value, abs=1e-12)


def test_run_folder_contract(world: World) -> None:
    executor = world.executor()
    record = plan(executor)
    result = run(executor, record.plan_id, dut="W1-D1")
    folder = world.run_dirs()[0]
    assert folder.name == result.run_id
    assert folder.relative_to(world.runs_dir).as_posix() == \
        f"{result.run_id[1:5]}/{result.run_id[5:7]}/{result.run_id[7:9]}/{result.run_id}"
    manifest = load_run(result.run_id, data_root=world.data).manifest
    assert manifest.plan.plan_id == record.plan_id and manifest.plan_hash == record.plan_hash
    assert manifest.plan.summary == record.summary and manifest.plan.envelope == record.envelope
    assert manifest.plan.rules.evaluated_at >= record.rules.evaluated_at  # re-evaluated at run time (step 3)
    assert (manifest.recipe_id, manifest.recipe_version, manifest.recipe_sha) == \
        ("mosfet.idvg", 1, record.recipe_sha)
    assert manifest.identity is not None and manifest.identity.model == "B1500A"
    assert manifest.inventory is not None and manifest.inventory.model_in_slot(3) == "B1517A"
    assert set(manifest.hashes) == {"station", "policy", "pin_map", "dut_profile"}
    assert {f.key for f in manifest.config_files} >= {"settings", "station", "policy", "pinmaps/mosfet-4t",
                                                      "duts/nmos-generic", "sim/scenarios/nmos_basic"}
    assert [r.phase for r in manifest.rules] == ["plan", "pre_execute"]
    assert manifest.tier == "ok" and manifest.confirmed_summary is None and manifest.dut_instance == "W1-D1"
    assert manifest.client.adapter == "cli" and manifest.software_version.startswith("0.1.0")
    assert manifest.cleanup is not None and manifest.cleanup.verified == "sim_state"
    assert manifest.outcome == "completed" and manifest.finished_at is not None
    assert any(a.startswith("SIMULATED") for a in manifest.assumptions)
    expected = {"audit.jsonl", "raw/block-000.txt", "data.csv", "quality.json",
                "analysis/vth_linear_extrapolation-1.json"}
    assert set(manifest.files) == expected
    for rel, digest in manifest.files.items():
        assert hashlib.sha256((folder / rel).read_bytes()).hexdigest() == digest, rel
    reads = [e.resp for e in read_audit(folder) if e.ev == "read" and e.error is None]
    assert reads == [(folder / "raw/block-000.txt").read_bytes().decode("latin-1")]
    events = [e.ev for e in read_audit(folder)]
    assert events[0] == "lock_acquired" and "tier_check" in events and "rule_report" in events
    assert events.index("cleanup_verified") < events.index("lock_released") < events.index("run_status")
    index = [json.loads(line) for line in (world.runs_dir / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert index == [{**index[0], "run_id": result.run_id, "path": folder.relative_to(world.runs_dir).as_posix(),
                      "outcome": "completed", "dut_instance": "W1-D1"}]


def test_flex_preview_is_what_the_instrument_received(world: World) -> None:
    executor = world.executor()
    record = plan(executor, params={"vg_points": 41, "integration": "short"})
    assert run(executor, record.plan_id).outcome == "completed"
    log = [r for r in world.sim_log() if r.outcome == "ok"]
    first = next(i for i, r in enumerate(log) if r.mnemonic == "FMT")
    last = next(i for i, r in enumerate(log) if r.mnemonic == "XE")
    writes = [r.command for r in log[first:last + 1] if not r.command.endswith("?") and "?" not in r.mnemonic]
    assert writes == record.flex_preview
    after = {r.mnemonic for r in log[last + 1:]}
    assert {"DZ", "CL"} <= after


def test_plan_id_is_stable_and_label_independent(world: World) -> None:
    executor = world.executor()
    first = plan(executor, label="batch A")
    second = plan(executor, label="batch B")
    assert first.plan_id == second.plan_id and first.plan_hash == second.plan_hash
    stored = executor.load_plan(first.plan_id)
    assert stored.request.label == "batch B"
    assert plan(executor, params={"vd": 0.1}).plan_id != first.plan_id
    assert plan(executor, dut_profile="fefet-generic").plan_id != first.plan_id


def test_one_plan_serves_a_die_batch(world: World) -> None:
    executor = world.executor()
    record = plan(executor)
    results = [run(executor, record.plan_id, dut=die, client=MCP) for die in ("W1-D1", "W1-D2", "W1-D3")]
    assert all(r.outcome == "completed" for r in results)
    assert len({r.run_id for r in results}) == 3
    manifests = [load_run(r.run_id, data_root=world.data).manifest for r in results]
    assert [m.dut_instance for m in manifests] == ["W1-D1", "W1-D2", "W1-D3"]
    assert {m.plan.plan_id for m in manifests} == {record.plan_id}
    assert all(m.client.session_tag == "test-session" for m in manifests)
    lines = (world.runs_dir / "index.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["dut_instance"] for line in lines] == ["W1-D1", "W1-D2", "W1-D3"]


def test_plan_request_shape(world: World) -> None:
    """The example request validates as the blueprint 2.1 PlanRequest (label excluded from the hash)."""
    executor = world.executor()
    record = plan(executor, params={"vg_points": 101.0, "vg_stop": 3})
    assert record.resolved_params["vg_points"].value == 101 and record.resolved_params["vg_stop"].value == 3.0
    assert record.request.recipe_id == IDVG["recipe_id"]
