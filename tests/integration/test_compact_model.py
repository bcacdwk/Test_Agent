"""Compact models on simulator runs (WP7.7, blueprint v2 2.10 ``model.py``, 10.3 AC): ``compact_model_fit`` recovers
the ``nmos_basic`` EKV truth from ``mosfet.idvg`` (Vth +-10 mV, n +-5 %) and, with ``fit_rs``, every parameter from
``mosfet.idvd``; ``model_compare`` validates a model fitted on one run against another; ``export_spice_netlist``
writes its two files into the run folder's ``analysis/`` through ``analyze_run`` (and the CLI lists them), and the
written netlist passes the SPICE-syntax parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from b1500_test_agent.adapters.cli.core import analyze_lines
from b1500_test_agent.config import load_config
from b1500_test_agent.models.results import AnalysisResult
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.devices.mosfet import MosfetEkv
from tests.integration.helpers import World
from tests.unit import spice_syntax as spice

pytestmark = pytest.mark.smu

REQUESTS = {"mosfet.idvg": "mosfet-4t", "mosfet.idvd": "mosfet-4t", "mosfet.idvg_family": "mosfet-4t",
            "mosfet.idvg_sync": "mosfet-4t"}


def truth(world: World) -> MosfetEkv:
    device = Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]
    assert isinstance(device, MosfetEkv)
    return device


def measure(world: World, recipe_id: str) -> str:
    service = world.service()
    plan = service.validate_plan(recipe_id=recipe_id, pin_map=REQUESTS[recipe_id], dut_profile="nmos-generic")
    assert plan.tier == "ok" and plan.plan_id is not None, plan.message
    run = service.run_plan(plan.plan_id)
    assert run.ok and run.run_id is not None and run.quality_verdict == "ok", run.message
    return run.run_id


def analyze(world: World, run_id: str, method: str, **options: object) -> AnalysisResult:
    result = world.service().analyze_run(run_id=run_id, method=method, options=dict(options))
    assert result.ok, result.message
    return result


def values(result: AnalysisResult) -> dict[str, float]:
    return {r.quantity: r.value for r in result.results if r.value is not None}


@pytest.fixture
def nmos(world: World) -> World:
    world.use_scenario("nmos_basic")
    return world


def test_ekv_fit_of_the_transfer_curve_recovers_the_simulator_truth(nmos: World) -> None:
    device = truth(nmos)
    result = analyze(nmos, measure(nmos, "mosfet.idvg"), "compact_model_fit")
    found = values(result)
    assert found["vth"] == pytest.approx(device.params.vth0, abs=0.010)  # AC: Vth +-10 mV (0.42 V)
    assert found["n"] == pytest.approx(device.params.slope_factor, rel=0.05)  # AC: n +-5 % (1.3)
    assert found["beta"] == pytest.approx(device.params.beta, rel=0.05)
    assert result.simulated and "derived from SIMULATED data" in result.message
    assert result.results[0].fit["rms_log"] < 0.02


def test_ekv_fit_of_the_output_family_with_series_resistance(nmos: World) -> None:
    p = truth(nmos).params
    found = values(analyze(nmos, measure(nmos, "mosfet.idvd"), "compact_model_fit", fit_rs=True))
    assert found["vth"] == pytest.approx(p.vth0, abs=0.010)
    assert found["n"] == pytest.approx(p.slope_factor, rel=0.05)
    assert found["beta"] == pytest.approx(p.beta, rel=0.05)
    assert found["theta"] == pytest.approx(p.theta, rel=0.15)
    assert found["lambda"] == pytest.approx(p.lambda_, rel=0.10)
    assert found["rs"] == pytest.approx(p.rs_ohm, rel=0.25)


def test_a_model_fitted_on_one_run_validates_against_another(nmos: World) -> None:
    family = measure(nmos, "mosfet.idvg_family")
    fitted = analyze(nmos, family, "compact_model_fit", fit_rs=True)
    params = {k: v for k, v in fitted.results[0].fit.items() if k in ("vt0", "n", "beta", "theta", "lambda", "rs")}
    output = measure(nmos, "mosfet.idvd")
    compared = analyze(nmos, output, "model_compare", params=params)
    found = values(compared)
    assert found["rms_rel"] < 0.03 and found["rms_log"] < 0.02  # a validation on unseen bias conditions
    assert compared.results[0].warnings == [] and "rms_rel@gate_V=1.5" in compared.results[0].fit
    level1 = values(analyze(nmos, output, "model_compare", model="level1",
                            params={"vto": params["vt0"], "beta": params["beta"], "lambda": params["lambda"]}))
    assert level1["rms_rel"] > found["rms_rel"]  # level 1 has no mobility degradation or series resistance


def test_export_writes_the_model_card_and_netlist_into_the_run_folder(nmos: World) -> None:
    run_id = measure(nmos, "mosfet.idvd")
    result = analyze(nmos, run_id, "export_spice_netlist", fit_rs=True, dialect="hspice")
    assert [Path(f).name for f in result.files] == ["spice-ekv-1.lib", "spice-ekv-1.sp"]
    assert "SPICE model and netlist written (derived from SIMULATED data)" in result.message
    assert any("ngspice or HSPICE" in step for step in result.next_steps)
    folder = Path(result.files[0]).parent
    payload = json.loads((folder / "export_spice_netlist-1.json").read_text(encoding="utf-8"))
    assert payload["outcome"] == "ok" and [Path(f).name for f in payload["files"]] == ["spice-ekv-1.lib",
                                                                                       "spice-ekv-1.sp"]
    netlist = Path(result.files[1]).read_text(encoding="utf-8")
    deck = spice.parse_deck(netlist, "hspice", netlist=True)
    assert deck.dc[0][0] == "VD" and deck.dc[1][0] == "VG" and run_id in netlist
    spice.parse_deck(Path(result.files[0]).read_text(encoding="utf-8"), "hspice", netlist=False)
    again = analyze(nmos, run_id, "export_spice_netlist", model="level1")
    assert [Path(f).name for f in again.files] == ["spice-level1-1.lib", "spice-level1-1.sp"]
    assert any(line.startswith("file: ") and line.endswith("spice-level1-1.sp") for line in analyze_lines(again))


def test_a_synchronous_sweep_fits_but_exports_no_netlist(nmos: World) -> None:
    run_id = measure(nmos, "mosfet.idvg_sync")
    assert values(analyze(nmos, run_id, "compact_model_fit"))["vth"] == pytest.approx(truth(nmos).params.vth0,
                                                                                      abs=0.010)
    failed = nmos.service().analyze_run(run_id=run_id, method="export_spice_netlist", options={})
    assert not failed.ok and failed.files == [] and "synchronous" in failed.message
