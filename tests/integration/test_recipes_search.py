"""Recipe validation of the search kind on the simulator (WP7.5; blueprint v2 10.3 row 7.5, per-recipe AC: tier, run,
default analysis vs the 4.2 fidelity target). These tests set ``status: sim_validated`` of ``mosfet.vth_search``,
``basic.breakdown_search`` and ``dielectric.bdv``.

- ``mosfet.vth_search`` (scenario ``nmos_basic``, MM 15 binary search): Vth within 5 mV of the constant-current Vth
  (``vth_constant_current``) of an Id-Vg run at the same criterion and drain bias (row 7.5 AC), and within the search
  tolerance of the model's Vth at that current; tier ``ok``; ``G`` when the target lies outside the range.
- ``basic.breakdown_search`` (``diode_basic``, MM 14 linear search): the anode voltage where the reverse current reaches
  1 uA within one step of the model's soft breakdown; no breakdown up to stop -> a lower bound.
- ``dielectric.bdv`` (blueprint 4.2 ``dielectric``: BDV +-2 %): method ``linear`` on ``dielectric_tddb`` (5 nm, BDV 6 V)
  and method ``quasi_pulsed`` (MM 9) on ``dielectric_thick`` (20 nm, BDV 24 V); the quasi-pulse on the 6 V film reads
  status ``S`` (compliance before a 10 V change from start, PG p53 (1-33)) and the analysis refuses with the hint.
- Destructive recipes always need confirmation (``destructive``), even inside every envelope; ``run_plan`` refuses them.
"""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.config import load_config
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.plan import PlanRequest
from b1500_test_agent.service import B1500Service
from b1500_test_agent.transport.sim.devices import Circuit
from tests.integration.helpers import World

VTH = {"recipe_id": "mosfet.vth_search", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
IDVG = {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
BREAKDOWN = {"recipe_id": "basic.breakdown_search", "pin_map": "diode-2t", "dut_profile": "diode-generic"}
BDV_THIN = {"recipe_id": "dielectric.bdv", "pin_map": "mosfet-4t", "dut_profile": "dielectric-generic"}
BDV_THICK = {"recipe_id": "dielectric.bdv", "pin_map": "mosfet-4t", "dut_profile": "dielectric-thick"}


def truth_device(world: World) -> Any:
    return Circuit(load_config(world.paths).sim_scenario).devices["dut"]  # type: ignore[arg-type]


def bisect(f: Any, low: float, high: float) -> float:
    """The root of the monotonic ``f`` between ``low`` and ``high``."""
    f_low = f(low)
    for _ in range(200):
        mid = 0.5 * (low + high)
        if (f(mid) > 0) == (f_low > 0):
            low, f_low = mid, f(mid)
        else:
            high = mid
    return 0.5 * (low + high)


def confirmed_run(service: B1500Service, request: dict[str, Any], reasons: list[str], **params: Any) -> Any:
    """Validate (expecting exactly ``reasons``), check that ``run_plan`` refuses, run with the plan's summary."""
    validation = service.validate_plan(**{**request, "params": params})
    assert validation.ok and validation.tier == "needs_confirmation" and validation.plan_id, validation.message
    assert sorted(validation.confirm_reasons) == sorted(reasons)
    refused = service.run_plan(validation.plan_id)
    assert not refused.ok and refused.outcome == "confirmation_required" and refused.run_id is None
    result = service.run_confirmed_plan(validation.plan_id, validation.summary)
    assert result.ok and result.outcome in ("completed", "completed_with_flags"), result.message
    return validation, result


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def preview(world: World, request: dict[str, Any], **params: Any) -> list[str]:
    """The FLEX preview of the plan of ``request`` with ``params``."""
    return world.executor().plan(PlanRequest.model_validate({**request, "params": params})).flex_preview


# -- mosfet.vth_search ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["mosfet.vth_search"])
def test_vth_search_is_within_5_mv_of_the_constant_current_vth(recipe_id: str, world: World) -> None:
    """AC: Vth(search) within 5 mV of the constant-current Vth (blueprint 10.3 row 7.5)."""
    world.use_scenario("nmos_basic")
    service = world.service()
    validation = service.validate_plan(**{**VTH, "recipe_id": recipe_id})
    assert validation.ok and validation.tier == "ok" and validation.plan_id, validation.message
    assert validation.resolved is not None and validation.resolved.mode == "sync"
    result = service.run_plan(validation.plan_id)
    assert result.ok and result.outcome == "completed" and result.quality_verdict == "ok", result.message
    assert result.status_counts == {"N": 2}
    vth = by_quantity(result.analyses)["vth"]
    assert vth.outcome == "ok" and vth.method == "vth_search_value"
    assert abs(vth.fit["rel_error"]) <= 0.01  # the binary search stopped within limit_rel of I_crit x W/L

    idvg = service.validate_plan(**IDVG, params={"vg_start": 0.0, "vg_stop": 1.0, "vg_points": 201})
    assert idvg.plan_id is not None
    reference = service.run_plan(idvg.plan_id)
    assert reference.ok, reference.message
    cc = service.analyze_run(reference.run_id or "", "vth_constant_current", {"i_crit_a": 1e-7})
    assert cc.ok, cc.message
    vth_cc = cc.results[0].value
    assert vth.value is not None and vth_cc is not None
    assert abs(vth.value - vth_cc) <= 5e-3  # AC: within 5 mV

    device = truth_device(world)
    model = bisect(lambda vg: device.terminal_currents(
        {"gate": vg, "drain": 0.05, "source": 0.0, "bulk": 0.0})["drain"] - 1e-7, 0.0, 2.0)
    assert vth.value == pytest.approx(model, abs=1e-3)  # 1 % of the current is 0.4 mV at 77 mV/dec

    data = load_run(result.run_id or "", data_root=world.data)
    assert list(data.table.columns) == ["step", "gate_V", "gate_V_status", "drain_I", "drain_I_status", "drain_V",
                                        "trust"]
    assert data.manifest.kind_result["measurement_mode"] == 15 and data.manifest.kind_result["found"] is True
    lines = preview(world, VTH)
    assert "MM 15" in lines and "BGI 3,0,1E-09,0,1E-07" in lines and "BSV 4,0,0,2,1E-06" in lines
    service.close()


def test_vth_search_normal_control_agrees_and_a_wrong_range_is_not_found(world: World) -> None:
    world.use_scenario("nmos_basic")
    service = world.service()
    cautious = service.validate_plan(**VTH)
    normal = service.validate_plan(**VTH, params={"control": "normal"})
    assert cautious.plan_id and normal.plan_id
    assert "BSM 1,2,1" in preview(world, VTH) and "BSM 0,2,1" in preview(world, VTH, control="normal")
    first = by_quantity(service.run_plan(cautious.plan_id).analyses)["vth"]
    second = by_quantity(service.run_plan(normal.plan_id).analyses)["vth"]
    assert first.value is not None and second.value is not None
    assert first.value == pytest.approx(second.value, abs=1e-3)
    below = service.validate_plan(**VTH, params={"vg_stop": 0.2})  # Vth ~ 0.31 V lies above the range
    assert below.plan_id is not None
    result = service.run_plan(below.plan_id)
    assert result.ok and result.outcome == "completed_with_flags" and result.status_counts.get("G") == 1
    failed = by_quantity(result.analyses)["vth"]
    assert failed.outcome == "failed" and "status G" in (failed.error or "")
    service.close()


# -- basic.breakdown_search -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["basic.breakdown_search"])
def test_breakdown_search_finds_the_junction_breakdown_within_one_step(recipe_id: str, world: World) -> None:
    world.use_scenario("diode_basic")
    service = world.service()
    _, result = confirmed_run(service, {**BREAKDOWN, "recipe_id": recipe_id},
                              ["destructive", "dut_envelope", "soft_limit"], v_stop=-20.0)
    assert result.status_counts == {"N": 2}
    bdv = by_quantity(result.analyses)["bdv"]
    assert bdv.outcome == "ok" and bdv.classification == "breakdown" and bdv.value is not None
    device = truth_device(world)
    model = bisect(lambda v: device.current(v) + 1e-6, -20.0, -1.0)  # anode current -1 uA (soft breakdown)
    assert model - 0.1 <= bdv.value <= model + 1e-9  # the first 0.1 V step at or beyond the criterion
    assert bdv.window is not None and bdv.window.low == pytest.approx(bdv.value) and bdv.fit["step_v"] == 0.1
    lines = preview(world, BREAKDOWN, v_stop=-20.0)
    assert "LSV 3,0,0,-20,-0.1,0.001" in lines and "LGI 3,0,0,-1E-06" in lines and "LSM 2,1" in lines
    service.close()


def test_breakdown_search_without_breakdown_reports_a_lower_bound(world: World) -> None:
    world.use_scenario("diode_basic")
    service = world.service()
    _, result = confirmed_run(service, BREAKDOWN, ["destructive", "dut_envelope"], v_stop=-8.0)
    assert result.outcome == "completed_with_flags" and result.status_counts == {"G": 1, "N": 1}
    bdv = by_quantity(result.analyses)["bdv"]
    assert (bdv.outcome, bdv.bound, bdv.classification) == ("ok", "lower", "no_breakdown")
    assert bdv.value == pytest.approx(-8.0)
    service.close()


# -- dielectric.bdv --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id", ["dielectric.bdv"])
def test_bdv_linear_ramp_on_the_tddb_film_within_two_percent(recipe_id: str, world: World) -> None:
    """Blueprint 4.2 ``dielectric``: BDV +-2 % (method linear on the 5 nm film of ``dielectric_tddb``)."""
    world.use_scenario("dielectric_tddb")
    service = world.service()
    _, result = confirmed_run(service, {**BDV_THIN, "recipe_id": recipe_id}, ["destructive", "dut_envelope"],
                              method="linear", v_stop=10.0)
    assert result.status_counts == {"N": 1, "C": 1}  # the breakdown step reads the compliance
    bdv = by_quantity(result.analyses)["bdv"]
    truth = truth_device(world).bdv
    assert truth == pytest.approx(6.0)
    assert bdv.outcome == "ok" and bdv.value == pytest.approx(truth, rel=0.02)
    data = load_run(result.run_id or "", data_root=world.data)
    assert data.table["gate_I_status"].tolist() == ["C"]
    service.close()


@pytest.mark.parametrize("recipe_id", ["dielectric.bdv"])
def test_bdv_quasi_pulsed_on_a_thick_film_within_two_percent(recipe_id: str, world: World) -> None:
    """Blueprint 4.2 ``dielectric``: BDV +-2 % (method quasi_pulsed, MM 9, on the 20 nm film)."""
    world.use_scenario("dielectric_thick")
    service = world.service()
    _, result = confirmed_run(service, {**BDV_THICK, "recipe_id": recipe_id}, ["destructive", "soft_limit"],
                              v_stop=30.0)
    lines = preview(world, BDV_THICK, v_stop=30.0)
    assert lines[lines.index("MM 9,4"):lines.index("XE")] == ["MM 9,4", "BDT 0,0", "BDM 0,0", "BDV 4,0,0,30,0.001"]
    assert result.status_counts == {"C": 1}
    bdv = by_quantity(result.analyses)["bdv"]
    truth = truth_device(world).bdv
    assert truth == pytest.approx(24.0)
    assert bdv.outcome == "ok" and bdv.classification == "breakdown"
    assert bdv.value == pytest.approx(truth, rel=0.02)
    service.close()


def test_bdv_quasi_pulsed_on_the_thin_film_reads_status_s_and_refuses(world: World) -> None:
    world.use_scenario("dielectric_tddb")
    service = world.service()
    _, result = confirmed_run(service, BDV_THIN, ["destructive", "dut_envelope"], v_stop=10.0)
    assert result.outcome == "completed_with_flags" and result.status_counts == {"S": 1}
    bdv = by_quantity(result.analyses)["bdv"]
    assert bdv.outcome == "refused" and "method linear" in (bdv.error or "")
    blocked = service.validate_plan(**BDV_THIN, params={"v_stop": 8.0})  # MM 9 needs |stop - start| >= 10 V
    assert blocked.status == "refused" and "10 V" in blocked.message
    service.close()


@pytest.mark.parametrize("request_", [
    {**BREAKDOWN, "params": {"v_stop": -4.0, "icomp": 1e-3}},
    {**BDV_THIN, "params": {"method": "linear", "v_stop": 5.0}},
    {**BDV_THICK, "params": {"v_stop": 10.0}},
], ids=["basic.breakdown_search", "dielectric.bdv-linear", "dielectric.bdv-quasi"])
def test_destructive_recipes_always_need_confirmation(request_: dict[str, Any], world: World) -> None:
    """AC: destructive -> always confirm, even with every level inside the DUT profile and the soft limits."""
    world.use_scenario("dielectric_thick" if request_["dut_profile"] == "dielectric-thick" else "nmos_basic")
    service = world.service()
    validation = service.validate_plan(**request_)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    assert validation.confirm_reasons == ["destructive"]
    service.close()
