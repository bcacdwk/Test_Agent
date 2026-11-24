"""``smu_stepped`` and the M2 simulator models at the executor level (blueprint 2.6, 3, 8.1 ``integration/``):
the Id-Vd family of ``mosfet.idvd`` on ``nmos_basic`` against the model truth, the host loop stopping on compliance,
and the ``fefet_basic`` scenario through ``generic.smu_staircase``: a double sweep whose ``segment`` rows give the
model's memory window, and the FeFET polarization persisting from one executor (process) to the next.

``mosfet.idvd`` is validated with ``output_metrics`` by ``test_recipes_mosfet.py`` (WP2.2); these tests keep the
four-step family of WP2.1 by passing ``vg_points=4``."""

from __future__ import annotations

import itertools
import json
import math

import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.config import load_config
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.devices.ferro import FefetDevice
from b1500_test_agent.transport.sim.devices.mosfet import MosfetEkv
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.helpers import REPO_ROOT, World, plan, run

pytestmark = pytest.mark.smu

IDVD = {"recipe_id": "mosfet.idvd", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}


def nmos_truth(world: World) -> MosfetEkv:
    scenario = load_config(world.paths).sim_scenario
    assert scenario is not None and scenario.name == "nmos_basic"
    device = Circuit(scenario).devices["dut"]
    assert isinstance(device, MosfetEkv)
    return device


def test_idvd_family_on_nmos_basic(world: World) -> None:
    executor = world.executor()
    record = plan(executor, **IDVD, params={"vg_stop": 1.5, "vg_points": 4})
    assert record.tier == "ok" and record.kind == "smu_stepped", record.rules.findings
    assert record.summary == ("mosfet.idvd@1 | drain=SMU3(HRSMU) sweep 0..3 V Icomp 1 mA; gate=SMU4(HRSMU) step "
                              "0.5..1.5 V Icomp 1 uA | DUT nmos-generic | pins mosfet-4t | sim")
    result = run(executor, record.plan_id)
    assert result.ok and result.outcome == "completed", result.message  # output_metrics ran (WP2.2)
    assert result.quality_verdict == "ok" and result.status_counts == {"N": 808}
    assert result.cleanup_verified == "sim_state"

    data = load_run(result.run_id, data_root=world.data)
    table = data.table
    assert data.measured_columns == ["drain_I", "gate_I"] and data.source_columns == ["drain_V", "gate_V"]
    assert table["step"].tolist() == list(range(404))
    steps = [0.5, 0.833333333, 1.166666667, 1.5]
    assert table["gate_V"].unique().tolist() == steps
    manifest = data.manifest
    assert manifest.kind_result == {"steps_planned": 4, "steps_done": 4, "stopped_early": False, "stop_reason": ""}
    assert any("host loop" in a for a in manifest.assumptions)
    truth = nmos_truth(world)
    at_3v = []
    for vg, curve in table.groupby("gate_V", sort=False):
        vd, i_d = curve["drain_V"].to_numpy(), curve["drain_I"].to_numpy()
        assert len(curve) == 101 and vd[0] == 0.0 and vd[-1] == pytest.approx(3.0)
        model = [truth.channel_current(float(vg), float(v)) for v in vd]
        for measured, expected in zip(i_d[1:], model[1:], strict=True):
            assert measured == pytest.approx(expected, rel=0.01, abs=1e-12)
        linear = (i_d[5] - i_d[0]) / (vd[5] - vd[0])
        saturated = (i_d[-1] - i_d[-6]) / (vd[-1] - vd[-6])
        assert 0 < saturated < 0.2 * linear  # output curve: steep in the linear region, flat in saturation
        at_3v.append(i_d[-1])
    assert all(b > 1.5 * a for a, b in itertools.pairwise(at_3v))  # the family opens up with Vg
    writes = [r for r in world.sim_log() if r.mnemonic == "XE" and r.outcome == "ok"]
    assert len(writes) == 4


def test_compliance_stops_the_host_loop(world: World) -> None:
    executor = world.executor()
    record = plan(executor, **IDVD, params={"vg_start": 2.0, "vg_stop": 0.5, "vg_points": 4})  # hardest step first
    assert record.tier == "ok"
    result = run(executor, record.plan_id)
    assert result.ok and result.outcome == "completed_with_flags", result.message
    assert result.quality_verdict == "untrusted" and result.status_counts["C"] == 1
    manifest = load_run(result.run_id, data_root=world.data).manifest
    assert manifest.kind_result["steps_done"] == 1 and manifest.kind_result["stopped_early"] is True
    assert "3 step(s) were not run" in str(manifest.kind_result["stop_reason"])
    table = load_run(result.run_id, data_root=world.data).table
    assert len(table) == 101 and table["gate_V"].unique().tolist() == [2.0]
    log = world.sim_log()
    assert sum(r.mnemonic == "XE" and r.outcome == "ok" for r in log) == 1
    last_source = max(r.seq for r in log if r.source)
    assert {"DZ", "CL"} <= {r.mnemonic for r in log if r.seq > last_source and r.outcome == "ok"}


# -- FeFET through generic.smu_staircase --------------------------------------------------------------------------


def use_fefet(world: World) -> FefetDevice:
    """Select ``fefet_basic`` and a pin map/DUT profile for ``generic.smu_staircase`` (sweep = gate on SMU4, bias =
    drain on SMU3, ground = GNDU); returns a fresh device with the scenario's truth parameters."""
    settings = yaml.safe_load((REPO_ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"))
    settings["sim"]["scenario"] = "fefet_basic"
    world.write_config("settings.yaml", settings)
    world.write_config("pinmaps/fefet-3t.yaml", {"certainty": "verified",
                                                  "terminals": {"sweep": 4, "bias": 3, "ground": "GNDU"}})
    world.write_config("duts/fefet-3t.yaml", {"device_type": "fefet", "terminals": {
        "sweep": {"max_abs_v": 5.0, "max_abs_i": 1e-4}, "bias": {"max_abs_v": 1.0, "max_abs_i": 1e-3},
        "ground": {"max_abs_v": 0.0, "max_abs_i": 1e-2}}})
    scenario = load_config(world.paths).sim_scenario
    assert scenario is not None and scenario.name == "fefet_basic"
    device = Circuit(scenario).devices["dut"]  # a fresh device: P = p_init
    assert isinstance(device, FefetDevice)
    return device


def gate_sweep(world: World, start: float, stop: float, points: int, mode: str = "single") -> str:
    executor = world.executor()  # a new executor = a new session and SimTransport (like another process)
    record = plan(executor, recipe_id="generic.smu_staircase", pin_map="fefet-3t", dut_profile="fefet-3t",
                  params={"start": start, "stop": stop, "points": points, "icomp": 1e-4, "mode": mode,
                          "bias_v": 0.05, "bias_icomp": 1e-3})
    assert record.tier == "ok", record.rules.findings
    result = run(executor, record.plan_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    executor.close()
    assert result.run_id is not None
    return result.run_id


def cc_vth(vg: list[float], ids: list[float], i_crit: float = 1e-7) -> float:
    """Gate voltage where the drain current first crosses ``i_crit`` (log-linear interpolation)."""
    for k in range(len(vg) - 1):
        a, b = ids[k], ids[k + 1]
        if a < i_crit <= b:
            frac = (math.log10(i_crit) - math.log10(max(a, 1e-30))) / (math.log10(b) - math.log10(max(a, 1e-30)))
            return vg[k] + frac * (vg[k + 1] - vg[k])
    raise AssertionError("no crossing")


def test_fefet_double_sweep_segments_give_the_model_memory_window(world: World) -> None:
    truth = use_fefet(world).loop_truth(-4.0, 4.0)
    run_id = gate_sweep(world, -4.0, 4.0, 161, mode="double")
    table = load_run(run_id, data_root=world.data).table
    assert table["segment"].tolist() == ["fwd"] * 161 + ["rev"] * 161
    fwd = table[table["segment"] == "fwd"]
    rev = table[table["segment"] == "rev"].iloc[::-1]  # same ascending gate grid as the forward branch
    assert fwd["sweep_V"].tolist() == pytest.approx(rev["sweep_V"].tolist())
    vg = fwd["sweep_V"].tolist()
    vth_fwd = cc_vth(vg, fwd["bias_I"].tolist())
    vth_rev = cc_vth(vg, rev["bias_I"].tolist())
    assert vth_fwd - vth_rev == pytest.approx(truth["memory_window"], rel=0.03)
    state = load_state_file(sim_state_file(world.state_dir, "fefet_basic"))
    assert state is not None and state.devices["dut"]["p"] == pytest.approx(-0.98, abs=0.02)  # ends at -4 V


def test_fefet_polarization_persists_between_executors(world: World) -> None:
    device = use_fefet(world)
    erased = load_run(gate_sweep(world, -0.5, 1.6, 85), data_root=world.data).table
    gate_sweep(world, 0.0, 4.5, 46)  # program; the sweep returns to 0 V, which retains the state
    state = load_state_file(sim_state_file(world.state_dir, "fefet_basic"))
    assert state is not None
    p_programmed = state.devices["dut"]["p"]
    assert p_programmed == pytest.approx(device.p_up(4.5))
    programmed = load_run(gate_sweep(world, -0.5, 1.6, 85), data_root=world.data).table
    shift = cc_vth(erased["sweep_V"].tolist(), erased["bias_I"].tolist()) \
        - cc_vth(programmed["sweep_V"].tolist(), programmed["bias_I"].tolist())
    p_erased = device.polarization_after(0.0, -1.0)  # the first run starts erased; CN at 0 V clamps P_init
    assert shift == pytest.approx(device.vth_at(p_erased) - device.vth_at(float(p_programmed)), abs=0.01)
    manifests = sorted(world.runs_dir.rglob("manifest.json"))
    assert len(manifests) == 3
    assert all(json.loads(m.read_text(encoding="utf-8"))["simulated"] for m in manifests)
