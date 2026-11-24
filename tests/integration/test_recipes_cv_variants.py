"""The C-V variants of kind ``cmu_measure`` on the simulator (blueprint v2 10.4 row 8.4 AC, per-recipe AC; WP8.4):
``moscap.cf`` (MM 22) and ``moscap.ct`` (MM 26) on ``moscap_dit``, ``moscap.cv_ac_level`` (MM 23) and
``moscap.pulsed_cv`` (MM 20, MM 19 for one point) on ``moscap_basic``, ``fecap.cv_butterfly`` (MM 18 double) on
``fecap_basic``, each through ``B1500Service`` after the phase/open/short corrections of its pin map (R-CORR-01).

Fidelity against the model truth of the scenario's device (built from the committed scenario; blueprint v2 4.2):
C-f: Dit at the bias within 25 % (the "Dit peak +-25 %" target), the trap time constant within 10 %; C-t: the
inversion-layer formation time within 10 %, the equilibrium capacitance within 1 %, the deep-depletion capacitance
within 2 %; C-ACV: the small-signal capacitance within 0.5 % and the curvature of the model's C-V within 25 %; pulsed
C-V: Cox +-1 %, Vfb +-20 mV of the model and of a DC C-V swept from the same (accumulation) state, deep depletion in
inversion; FeCap butterfly: peaks at +-Vc (= +-Ec x t) within 5 %. The C-f list must be covered by the corrections
at every frequency (the default correction list does not hold its 4-per-decade points). WP8.5: ``moscap_dit`` lands
the device through the SCUU of CMU1 (one landing for QSCV and C-V), so its runs use pin map ``moscap-scuu``
(``DIT``): the MFCMU is connected by ``SSP 7,4`` and the plans add ``unverified_topology``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.models.results import PlanValidation
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.models.sim import FecapParams, MoscapParams
from b1500_test_agent.rules.builtin.cmu import CORRECTION_NEXT_STEP
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices.ferro import FecapDevice
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from tests.integration.helpers import REPO_ROOT, World

CORRECTIONS = ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short")
MOSCAP = {"pin_map": "moscap-cmu", "dut_profile": "moscap-generic"}
DIT = {"pin_map": "moscap-scuu", "dut_profile": "moscap-generic"}
"""The ``moscap_dit`` landing: through SCUU1 (WP8.5)."""
FECAP = {"recipe_id": "fecap.cv_butterfly", "pin_map": "fecap-cmu", "dut_profile": "fecap-generic"}
CF_LIST = [1e3, 1778.279, 3162.278, 5623.413, 1e4, 17782.79, 31622.78, 56234.13, 1e5, 177827.9, 316227.8, 562341.3,
           1e6]
"""The default C-f list of ``moscap.cf`` (1 kHz to 1 MHz, 4 per decade, at the MFCMU setting resolution)."""


def recipe(recipe_id: str) -> pytest.MarkDecorator:
    """Parametrize with the recipe id, so ``pytest tests/integration -k <recipe id>`` selects the test."""
    return pytest.mark.parametrize("recipe_id", [recipe_id])


def scenario(name: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / f"config/sim/scenarios/{name}.yaml").read_text(encoding="utf-8"))


def moscap(name: str) -> MoscapDevice:
    return MoscapDevice("dut", MoscapParams(**scenario(name)["models"]["dut"]["params"]))


def fecap() -> FecapDevice:
    return FecapDevice("cv", FecapParams(**scenario("fecap_basic")["models"]["cv"]["params"]))


def correct(svc: B1500Service, pin_map: str, **params: Any) -> None:
    """Phase compensation, open and short with ``pin_map`` (each confirmed with its own summary: the test stands in
    for the human who set the probes up)."""
    for name in CORRECTIONS:
        extra = {} if name == "cmu.phase_compensation" else params
        plan = svc.validate_plan(recipe_id=name, params=extra or None, pin_map=pin_map)
        assert plan.tier == "needs_confirmation" and plan.summary is not None, plan.message
        result = svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]
        assert result.ok, result.message


def run(svc: B1500Service, request: dict[str, Any], **params: Any) -> tuple[PlanValidation, RunSummary]:
    plan = svc.validate_plan(**request, params=params or None)
    assert plan.tier == "needs_confirmation" and plan.summary is not None, (plan.message, plan.findings)
    return plan, svc.run_confirmed_plan(plan.plan_id, summary=plan.summary)  # type: ignore[arg-type]


def value(result: RunSummary, method: str, quantity: str) -> float:
    found = next(a for a in result.analyses if a.method == method and a.quantity == quantity)
    assert found.outcome == "ok" and found.value is not None, found.error
    return found.value


def sent(world: World, scenario_name: str) -> list[str]:
    return [r.command for r in world.sim_log(scenario_name) if r.outcome == "ok"]


@pytest.fixture
def svc(world: World) -> B1500Service:
    return world.service()


# -- moscap.cf -------------------------------------------------------------------------------------------------------


@recipe("moscap.cf")
def test_cf_needs_corrections_at_every_listed_frequency_then_meets_the_dit_truth(recipe_id: str, world: World,
                                                                                 svc: B1500Service) -> None:
    world.use_scenario("moscap_dit")
    request = {"recipe_id": recipe_id, **DIT}
    correct(svc, "moscap-scuu")  # the 23 default correction frequencies: 1-2-5 steps, not the 4-per-decade list
    uncovered = svc.validate_plan(**request)
    assert uncovered.tier == "blocked" and CORRECTION_NEXT_STEP in uncovered.next_steps
    assert any(f.rule_id == "R-CORR-01" and "does not cover 1778.28 Hz" in f.message for f in uncovered.findings)
    correct(svc, "moscap-scuu", freqs_hz=CF_LIST)
    plan, result = run(svc, request)
    assert set(plan.confirm_reasons) == {"unverified_pin_map", "dut_envelope", "unverified_topology"}
    assert plan.summary is not None and "gate=CMU1 via SCUU1.OUT1 1 kHz..1 MHz 30 mVrms DC -0.6 V corr <1h" in \
        plan.summary
    assert result.ok and result.outcome == "completed" and result.simulated, result.message
    assert result.cleanup_verified == "sim_state" and result.quality_verdict == "ok"
    truth = moscap("moscap_dit").interface_trap_truth(-0.6, 1e5)
    assert value(result, "cf_dispersion", "dit") == pytest.approx(truth["dit_cm2_ev"], rel=0.25)
    assert value(result, "cf_dispersion", "tau_it") == pytest.approx(truth["tau_s"], rel=0.10)
    assert value(result, "cf_dispersion", "f_peak") == pytest.approx(truth["f_peak_hz"], rel=0.10)
    assert value(result, "cf_dispersion", "c_dispersion") > 0.05  # the traps add capacitance at low frequency
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(table) == 13 and np.allclose(table["freq_hz"], CF_LIST, rtol=1e-5)
    assert set(table["dc_v"]) == {-0.6} and set(table["gate_Cp_status"]) == {"N"}
    commands = sent(world, "moscap_dit")
    assert "WFC 7,2,1000,1000000,13" in commands and "MM 22,7" in commands and "WMFC 2,1" in commands
    precise = svc.analyze_run(result.run_id, "cf_dispersion",  # type: ignore[arg-type]
                              {"cox_f": moscap("moscap_dit").cox, "rs_ohm": 5.0})
    assert precise.ok and next(r.value for r in precise.results if r.quantity == "dit") == pytest.approx(
        truth["dit_cm2_ev"], rel=0.10)


@recipe("moscap.cf")
def test_cf_frequencies_off_a_stair_or_a_peak_outside_the_sweep_are_refused(recipe_id: str, world: World,
                                                                          svc: B1500Service) -> None:
    world.use_scenario("moscap_dit")
    off = svc.validate_plan(recipe_id=recipe_id, **DIT, params={"freqs_hz": [1e3, 2e3, 5e3, 1e4]})
    assert not off.ok and off.plan_id is None and "equally spaced" in off.message
    correct(svc, "moscap-scuu", freqs_hz=CF_LIST)
    _, result = run(svc, {"recipe_id": recipe_id, **DIT}, dc_v=-0.2)  # near midgap: the peak is below 1 kHz
    assert result.ok, result.message
    failed = next(a for a in result.analyses if a.quantity == "dit")
    assert failed.outcome == "failed" and "lies outside the measured" in (failed.error or "")
    assert result.outcome == "completed_with_flags"


# -- moscap.ct -------------------------------------------------------------------------------------------------------


@recipe("moscap.ct")
def test_ct_recovers_the_inversion_layer_formation_time(recipe_id: str, world: World, svc: B1500Service) -> None:
    world.use_scenario("moscap_dit")
    correct(svc, "moscap-scuu")
    plan, result = run(svc, {"recipe_id": recipe_id, **DIT})
    assert plan.summary is not None and "gate=CMU1 via SCUU1.OUT1 1 MHz 30 mVrms DC -2.5..2 V corr <1h" in \
        plan.summary
    assert result.ok and result.outcome == "completed", result.message
    device = moscap("moscap_dit")
    assert value(result, "ct_recovery", "tau_recovery") == pytest.approx(device.params.tau_inv_s, rel=0.10)
    assert value(result, "ct_recovery", "beta") == pytest.approx(1.0, abs=0.1)
    assert value(result, "ct_recovery", "c_final") == pytest.approx(device.equilibrium_capacitance(2.0, 1e6),
                                                                    rel=0.01)
    assert value(result, "ct_recovery", "c_initial") == pytest.approx(device.deep_depletion_capacitance(2.0, 1e6),
                                                                      rel=0.02)
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(table) == 301 and table["t_s"].iloc[0] == pytest.approx(0.0, abs=1e-6)
    assert np.allclose(np.diff(table["t_s"]), 0.02, atol=1e-6) and set(table["dc_v"]) == {2.0}
    commands = sent(world, "moscap_dit")
    run_part = commands[commands.index("TSC 1"):]
    assert ["TSR", "MM 26,7"] == run_part[run_part.index("TSR"):run_part.index("TSR") + 2]
    assert "MTDCV 0,0.02,301,1" in run_part and "MDCV 7,-2.5,2,2" in run_part


@recipe("moscap.ct")
def test_a_long_ct_transient_runs_as_chained_blocks_with_continuous_time(recipe_id: str, world: World,
                                                                         svc: B1500Service) -> None:
    world.use_scenario("moscap_dit")
    correct(svc, "moscap-scuu")
    plan, result = run(svc, {"recipe_id": recipe_id, **DIT}, interval_s=0.1, points=900)  # 90 s of sampling
    assert plan.resolved is not None and plan.resolved.est_s > 90.0
    assert result.ok and result.outcome == "completed", result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    record = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert record["plan"]["estimate"]["max_segment_s"] <= 30.0  # R-RUN-02 segments: blocks of at most 25 s
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(table) == 900 and np.allclose(np.diff(table["t_s"]), 0.1, atol=0.011)  # one 10 ms hold grid step
    assert table["t_s"].iloc[-1] == pytest.approx(89.9, abs=0.05)
    commands = sent(world, "moscap_dit")
    assert commands.count("TSR") == 1 and sum(c.startswith("MDCV 7,2,2,2") for c in commands) == 3
    events = [json.loads(line) for line in (folder / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    progress = [e["data"] for e in events if e.get("ev") == "checkpoint" and (e.get("data") or {}).get("label")
                == "progress"]
    assert [(p["done"], p["total"]) for p in progress] == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert value(result, "ct_recovery", "tau_recovery") == pytest.approx(moscap("moscap_dit").params.tau_inv_s,
                                                                         rel=0.10)


# -- moscap.cv_ac_level -----------------------------------------------------------------------------------------------


@recipe("moscap.cv_ac_level")
def test_ac_level_sweep_gives_the_small_signal_capacitance_and_curvature(recipe_id: str, world: World,
                                                                         svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    correct(svc, "moscap-cmu")
    plan, result = run(svc, {"recipe_id": recipe_id, **MOSCAP})
    assert set(plan.confirm_reasons) == {"unverified_pin_map", "dut_envelope", "soft_cmu"}  # up to 100 mVrms
    assert plan.summary is not None and "gate=CMU1:H 1 MHz 100 mVrms DC -0.6 V" in plan.summary
    assert result.ok and result.outcome == "completed", result.message
    device = moscap("moscap_basic")
    c0 = device.capacitance(-0.6, 1e6)
    h = 1e-3
    curvature = (device.capacitance(-0.6 + h, 1e6) - 2 * c0 + device.capacitance(-0.6 - h, 1e6)) / h**2
    assert value(result, "cv_ac_dependence", "c_small_signal") == pytest.approx(c0, rel=0.005)
    found = next(a for a in result.analyses if a.quantity == "c_small_signal")
    assert found.fit["d2c_dv2"] == pytest.approx(curvature, rel=0.25)
    limit = value(result, "cv_ac_dependence", "ac_limit")
    assert limit == pytest.approx(np.sqrt(0.01 * 4 * c0 / abs(curvature)), rel=0.15)
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert np.allclose(table["ac_vrms"], np.linspace(0.01, 0.1, 10), atol=1e-6)
    assert "WACV 7,1,0.01,0.1,10" in sent(world, "moscap_basic")


# -- moscap.pulsed_cv ------------------------------------------------------------------------------------------------


@recipe("moscap.pulsed_cv")
def test_pulsed_cv_matches_the_dc_cv_outside_inversion_and_shows_deep_depletion(recipe_id: str, world: World,
                                                                                 svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    correct(svc, "moscap-cmu")
    plan, pulsed = run(svc, {"recipe_id": recipe_id, **MOSCAP})
    assert plan.summary is not None and "gate=CMU1:H 1 MHz 30 mVrms DC -2.5..2 V" in plan.summary
    assert pulsed.ok and pulsed.outcome == "completed", pulsed.message
    _, dc = run(svc, {"recipe_id": "moscap.cv", **MOSCAP}, v_start=-2.5, v_stop=2.0)  # the same trap state
    device = moscap("moscap_basic")
    empty = device.vfb(0.0)  # pulses from the accumulation base: border traps emptied before every point
    assert value(pulsed, "cv_cox", "cox") == pytest.approx(device.cox, rel=0.01)
    assert value(pulsed, "cv_flatband", "vfb") == pytest.approx(empty, abs=0.020)
    assert value(pulsed, "cv_doping_profile", "nsub") == pytest.approx(device.params.nsub_cm3, rel=0.10)
    assert value(pulsed, "cv_cox", "cox") == pytest.approx(value(dc, "cv_cox", "cox"), rel=0.01)
    assert value(pulsed, "cv_flatband", "vfb") == pytest.approx(value(dc, "cv_flatband", "vfb"), abs=0.020)
    compared = svc.analyze_run(pulsed.run_id, "cv_pulsed_vs_dc", {"reference_run": dc.run_id})  # type: ignore[arg-type]
    assert compared.ok, compared.message
    found = {r.quantity: r.value for r in compared.results}
    assert abs(found["delta_vfb"]) < 0.020 and found["cox_ratio"] == pytest.approx(1.0, abs=0.01)
    # each point is read in the last 8 ms (ACT 0,1) of its 10 ms pulse: 2 ms of inversion-layer formation
    # (simulator convention, TODO(verify) at bring-up L6); the DC sweep into inversion lags equilibrium a little
    pulse_c = device.transient_capacitance(2.0, 1e6, 0.002)
    table = load_run(pulsed.run_id, data_root=world.data).table  # type: ignore[arg-type]
    reference = load_run(dc.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(table) == 91 and table["dc_v"].iloc[0] == pytest.approx(-2.5) and table["dc_v"].iloc[-1] == 2.0
    assert table["gate_Cp"].iloc[-1] == pytest.approx(pulse_c, rel=0.02)
    assert pulse_c < 0.7 * device.equilibrium_capacitance(2.0, 1e6)  # deep depletion
    assert found["c_ratio_inversion"] == pytest.approx(table["gate_Cp"].iloc[-1] / reference["gate_Cp"].iloc[-1],
                                                       rel=1e-3)
    assert found["c_ratio_inversion"] < 0.8
    commands = sent(world, "moscap_basic")
    assert "PWDCV 7,1,-2.5,-2.5,2,91" in commands and "PTDCV 1,0.01,0" in commands and "ACT 0,1" in commands


@recipe("moscap.pulsed_cv")
def test_one_point_is_the_pulsed_spot_c(recipe_id: str, world: World, svc: B1500Service) -> None:
    world.use_scenario("moscap_basic")
    correct(svc, "moscap-cmu")
    _, result = run(svc, {"recipe_id": recipe_id, **MOSCAP}, points=1, v_start=2.0, v_stop=2.0)
    assert result.ok, result.message
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert len(table) == 1 and table["dc_v"].iloc[0] == 2.0
    assert table["gate_Cp"].iloc[0] == pytest.approx(moscap("moscap_basic").transient_capacitance(2.0, 1e6, 0.002),
                                                     rel=0.02)
    commands = sent(world, "moscap_basic")
    assert "MM 19,7" in commands and "PDCV 7,-2.5,2" in commands
    width = svc.validate_plan(recipe_id=recipe_id, **MOSCAP, params={"freqs_hz": [1e4], "width_s": 0.02})
    assert not width.ok and width.plan_id is None and "below the 50 ms" in width.message


# -- fecap.cv_butterfly ----------------------------------------------------------------------------------------------


@recipe("fecap.cv_butterfly")
def test_fecap_butterfly_peaks_at_plus_minus_the_coercive_voltage(recipe_id: str, world: World,
                                                                  svc: B1500Service) -> None:
    world.use_scenario("fecap_basic")
    blocked = svc.validate_plan(**FECAP)
    assert blocked.tier == "blocked" and CORRECTION_NEXT_STEP in blocked.next_steps
    correct(svc, "fecap-cmu")
    plan, result = run(svc, FECAP)
    assert plan.confirm_reasons == ["unverified_pin_map"]
    assert plan.summary is not None and "top=CMU1:H 100 kHz 30 mVrms DC -3..3 V corr <1h" in plan.summary
    assert result.ok and result.outcome == "completed", result.message
    device = fecap()
    truth = device.butterfly_truth()
    assert value(result, "cv_butterfly", "v_peak_up") == pytest.approx(truth["v_peak_up"], rel=0.05)
    assert value(result, "cv_butterfly", "v_peak_down") == pytest.approx(truth["v_peak_down"], rel=0.05)
    assert value(result, "cv_butterfly", "vc") == pytest.approx(device.vc, rel=0.05)
    assert value(result, "cv_butterfly", "ec") == pytest.approx(device.params.ec_mv_cm, rel=0.05)
    assert abs(value(result, "cv_butterfly", "v_imprint")) < 0.05
    table = load_run(result.run_id, data_root=world.data).table  # type: ignore[arg-type]
    assert list(table["segment"].unique()) == ["fwd", "rev"] and len(table) == 242
    plots = svc.analyze_run(result.run_id, "plot_cv")  # type: ignore[arg-type]
    assert plots.ok and [Path(p).name for p in plots.plots] == ["cv-1.png", "cv-inverse-square-1.png"], plots.message


def plot_record(world: World, run_id: str) -> dict[str, Any]:
    folder = next(p for p in world.runs_dir.rglob(run_id) if p.is_dir())
    return json.loads((folder / "analysis" / "plot_cv-1.json").read_text(encoding="utf-8"))


def test_cf_ct_and_ac_level_runs_plot_against_their_own_axis(world: World, svc: B1500Service) -> None:
    world.use_scenario("moscap_dit")
    correct(svc, "moscap-scuu", freqs_hz=CF_LIST)
    _, cf = run(svc, {"recipe_id": "moscap.cf", **DIT})
    _, ct = run(svc, {"recipe_id": "moscap.ct", **DIT}, points=50)
    _, acv = run(svc, {"recipe_id": "moscap.cv_ac_level", **DIT})
    for result, axis, name in ((cf, "freq_hz", "cf"), (ct, "t_s", "ct"), (acv, "ac_vrms", "cv-ac")):
        plotted = svc.analyze_run(result.run_id, "plot_cv")  # type: ignore[arg-type]
        assert plotted.ok and [Path(p).name for p in plotted.plots] == [f"{name}-1.png"], plotted.message
        assert plot_record(world, str(result.run_id))["x"] == axis
