"""Calibration of the simulator scenario ``lab_nmos_2025`` against the lab's own Id-Vg curve (blueprint v2 4.4,
10.2 row 6.2 AC "calibration test within tolerance").

``mosfet.idvg`` runs through ``B1500Service`` on the scenario with the lab script's measurement (lwp
``test_IdVg.m``: pin map ``mosfet-3t-lab``, gate -2..2 V in 61 steps, Vd 0.1 V, 1 PLC) and the simulated curve is
compared with ``tests/fixtures/lab/idvg_real.csv``. Stated tolerances:

- above the floor (the 37 lab points above 5 pA, Vg >= -0.4 V): log10 Id within **0.05 decade rms** and **0.12
  decade** at any point (the fit leaves 0.022 / 0.08; the simulated noise adds less than 0.005);
- off state (Vg <= -0.9 V): both curves at the pA floor (|Id| < 2.5 pA), the simulated one inside **+-3e-13 A**
  (the lab's open-circuit floor is +-2e-13 A for 99 % of its readings; the scenario's sigma is 7e-14 A);
- the v1 extractions of the simulated run against those of the lab curve: Vth **30 mV** (linear extrapolation),
  **50 mV** (maximum gm change), **15 mV** (constant current at 10 nA); subthreshold swing **10 %**; gm max
  **12 %**. Measured: +24 mV, +36 mV, +5 mV, -6.8 %, +8.4 %. These are the limits of the EKV compact model, not
  of the fit: its weak inversion is one exponential (205 mV/dec here), while the lab device's local swing runs
  from 212 to about 270 mV/dec within one decade (a trap-limited, oxide-TFT-like turn-on), so the shape-sensitive
  definitions (curvature of gm) differ most. Closer agreement would need a different device model, not a refit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import load_run, mosfet
from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.models.analysis import ExtractionResult
from tests.integration.helpers import World, make_world
from tests.unit.lab_fixtures import REAL_VD, log_decades, real_idvg, real_idvg_run
from tests.unit.test_analysis_lab_data import I_CRIT_A

SCENARIO = "lab_nmos_2025"
LAB_REQUEST = {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-3t-lab", "dut_profile": "nmos-generic",
               "params": {"vg_start": -2.0, "vg_stop": 2.0, "vg_points": 61, "vd": REAL_VD}}
"""The lab script's measurement as a ``mosfet.idvg`` request (the other parameters stay at the recipe defaults)."""

LOG_RMS_DECADES = 0.05
LOG_MAX_DECADES = 0.12
ABOVE_FLOOR_A = 5e-12
OFF_GATE_V = -0.9
OFF_LIMIT_A = 3e-13
VTH_TOLERANCE_V = {"vth_linear_extrapolation": 0.030, "vth_max_gm": 0.050, "vth_constant_current": 0.015}
RELATIVE_TOLERANCE = {"subthreshold_swing": 0.10, "gm_max": 0.12}


def simulated_run(world: World) -> RunData:
    world.use_scenario(SCENARIO)
    service = world.service()
    try:
        validation = service.validate_plan(**LAB_REQUEST)
        assert validation.ok and validation.tier == "needs_confirmation", validation.message
        assert sorted(validation.confirm_reasons) == ["dut_envelope", "unverified_pin_map"]
        result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)  # the test confirms
        assert result.ok and result.outcome == "completed" and result.simulated, result.message
        assert result.quality_verdict == "ok" and result.cleanup_verified == "sim_state"
    finally:
        service.close()
    return load_run(result.run_id, data_root=world.data)


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[RunData, RunData]:
    return simulated_run(make_world(tmp_path_factory.mktemp("lab"))), real_idvg_run()


def single(result: ExtractionResult | list[ExtractionResult]) -> float:
    one = result[0] if isinstance(result, list) else result
    assert one.outcome == "ok" and one.value is not None, (one.method, one.error)
    return float(one.value)


def test_the_simulated_run_is_the_lab_measurement(runs: tuple[RunData, RunData]) -> None:
    sim, _ = runs
    table = sim.table
    real = real_idvg()
    assert len(table) == len(real) == 61
    assert np.allclose(table["gate_V"].to_numpy(), real["V_G"].to_numpy(), atol=1e-3)  # same 61 gate levels
    assert set(table["drain_V"]) == {REAL_VD} and "source_V" not in table  # the grounded SMU adds no column
    assert set(table["drain_I_status"]) == {"N"} and set(table["gate_I_status"]) == {"N"}


def test_drain_current_above_the_floor_matches_the_lab_curve(runs: tuple[RunData, RunData]) -> None:
    sim, _ = runs
    real = real_idvg()
    above = (real["I_D"] > ABOVE_FLOOR_A).to_numpy()
    assert above.sum() == 37
    error = log_decades(sim.table["drain_I"].to_numpy()[above], real["I_D"].to_numpy()[above])
    assert float(np.sqrt(np.mean(error ** 2))) <= LOG_RMS_DECADES
    assert float(np.max(np.abs(error))) <= LOG_MAX_DECADES


def test_off_state_is_the_floor_in_both(runs: tuple[RunData, RunData]) -> None:
    sim, _ = runs
    real = real_idvg()
    off = (real["V_G"] <= OFF_GATE_V).to_numpy()
    simulated = pd.Series(sim.table["drain_I"].to_numpy()[off])
    assert real["I_D"][off].abs().max() < 2.5e-12 and simulated.abs().max() < OFF_LIMIT_A
    assert 3.5e-14 <= simulated.std() <= 1.4e-13  # the scenario's 7e-14 A sigma, within a factor of two


@pytest.mark.parametrize("method", sorted(VTH_TOLERANCE_V))
def test_each_vth_method_gives_the_lab_value(runs: tuple[RunData, RunData], method: str) -> None:
    options = {"i_crit_a": I_CRIT_A} if method == "vth_constant_current" else {}
    sim, real = runs
    function = getattr(mosfet, method)
    assert single(function(sim, **options)) == pytest.approx(single(function(real, **options)),
                                                             abs=VTH_TOLERANCE_V[method])


@pytest.mark.parametrize("method", sorted(RELATIVE_TOLERANCE))
def test_swing_and_gm_match(runs: tuple[RunData, RunData], method: str) -> None:
    sim, real = runs
    function = getattr(mosfet, method)
    assert single(function(sim)) == pytest.approx(single(function(real)), rel=RELATIVE_TOLERANCE[method])
