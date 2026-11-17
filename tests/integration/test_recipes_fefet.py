"""Recipe validation on the simulator (WP2.2, blueprint 9.3 AC and scenario S10): ``fefet.dual_sweep_mw`` on
``fefet_basic`` gives a memory window within 10 % of the model loop truth with both branch thresholds; this test sets
its ``status: sim_validated``.

Truth: ``FefetDevice.loop_truth(-4, 4)`` of a fresh device (the run starts erased, P = -1); the thresholds of the
constant-current method sit below the model threshold by the same offset on both branches (the current at the model
threshold is several times I_crit), so each branch Vth is compared with the same extractor on the noiseless model
loop (±10 mV) and with the loop truth (±0.1 V), the window with the loop truth (±10 %)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import load_run, run_method, with_trust
from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.transport.sim.devices import Circuit, FefetDevice
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.helpers import World, plan, run

MW = {"recipe_id": "fefet.dual_sweep_mw", "pin_map": "mosfet-4t", "dut_profile": "fefet-generic"}


def fresh_device(world: World) -> FefetDevice:
    device = Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]
    assert isinstance(device, FefetDevice)
    return device


def noiseless_loop(device: FefetDevice, vg: np.ndarray, vd: float) -> list[float]:
    """Drain currents of the noiseless model along the sweep (each step commits its gate voltage, as the sim)."""
    currents = []
    for v in vg:
        voltages = {"gate": float(v), "drain": vd, "source": 0.0, "bulk": 0.0}
        currents.append(device.terminal_currents(voltages)["drain"])
        device.commit(voltages)
    return currents


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def test_dual_sweep_memory_window_matches_the_loop_truth(world: World) -> None:
    world.use_scenario("fefet_basic")
    device = fresh_device(world)
    truth = device.loop_truth(-4.0, 4.0)
    executor = world.executor()
    record = plan(executor, **MW)
    assert record.tier == "ok", record.rules.findings
    assert record.summary.startswith("fefet.dual_sweep_mw@1 | ")
    result = run(executor, record.plan_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 644}

    found = by_quantity(result.analyses)
    assert list(found) == ["memory_window", "vth_fwd", "vth_rev", "ion_fwd", "ioff_fwd", "ion_rev", "ioff_rev"]
    mw, vth_fwd, vth_rev = found["memory_window"], found["vth_fwd"], found["vth_rev"]
    assert mw.value == pytest.approx(truth["memory_window"], rel=0.10)  # S10 bound
    assert mw.value == pytest.approx(vth_fwd.value - vth_rev.value) and mw.value > 0
    assert vth_fwd.value == pytest.approx(truth["vth_fwd"], abs=0.1)
    assert vth_rev.value == pytest.approx(truth["vth_rev"], abs=0.1)

    data = load_run(result.run_id, data_root=world.data)
    table = data.table
    assert table["segment"].tolist() == ["fwd"] * 161 + ["rev"] * 161
    reference_table = pd.DataFrame({"step": table["step"], "segment": table["segment"], "gate_V": table["gate_V"],
                                    "drain_I": noiseless_loop(fresh_device(world), table["gate_V"].to_numpy(), 0.05),
                                    "drain_I_status": "N"})
    reference = by_quantity(run_method("memory_window", RunData(data.manifest, with_trust(reference_table)),
                                       {"vth_method": "vth_constant_current", "i_crit_a": 1e-7}))
    assert vth_fwd.value == pytest.approx(reference["vth_fwd"].value, abs=0.01)
    assert vth_rev.value == pytest.approx(reference["vth_rev"].value, abs=0.01)
    for branch in ("fwd", "rev"):  # per-branch on/off: on at +4 V, off at -4 V
        ion, ioff = found[f"ion_{branch}"], found[f"ioff_{branch}"]
        assert ion.fit["v"] == 4.0 and ioff.fit["v"] == -4.0 and ion.value > 1e3 * ioff.value

    state = load_state_file(sim_state_file(world.state_dir, "fefet_basic"))
    assert state is not None and state.devices["dut"]["p"] < -0.9  # the loop ends erased at -4 V


@pytest.mark.parametrize("method", ["vth_linear_extrapolation", "vth_max_gm"])
def test_the_window_is_method_independent(world: World, method: str) -> None:
    world.use_scenario("fefet_basic")
    truth = fresh_device(world).loop_truth(-4.0, 4.0)
    executor = world.executor()
    result = run(executor, plan(executor, **MW).plan_id)
    data = load_run(result.run_id, data_root=world.data)
    criteria = executor.registry().get("fefet.dual_sweep_mw").quality
    mw = by_quantity(run_method("memory_window", data, {"vth_method": method}, criteria=criteria))["memory_window"]
    assert mw.outcome == "ok" and mw.value == pytest.approx(truth["memory_window"], rel=0.10)
