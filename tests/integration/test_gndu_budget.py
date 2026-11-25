"""GNDU budget rows (blueprint v2 2.8 R-GNDU-01, 10.4 row 8.5 AC; WP8.5): real recipes compiled by the real planner on
pin maps that land a pad on the GNDU run through ``B1500Service`` on the simulator; for each, the rule's bound
(``rules.builtin.limits.gndu_return_a``: the compliances plus the expected currents of the sources without
compliance) stays within the GNDU's 4.2 A (UG p58 (2-18)), the plan carries no R-GNDU-01 block, and the current the
simulator accounted as returning through the GNDU (``gndu_peak_a``, persisted in its state) never exceeds the bound.
A pin map without a GNDU pad (the SCUU landing of ``moscap.qscv``) owes the GNDU nothing and the simulator sees nothing
return there. The rule's ok/block rows on synthetic plans are ``tests/unit/test_rules_v2.py`` (``gndu-*``)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.rules.builtin.limits import gndu_return_a
from b1500_test_agent.transport.sim.devices.circuit import GNDU_MAX_A
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.helpers import World

pytestmark = pytest.mark.cmu

ROWS: list[tuple[str, str, str, str | None, dict[str, Any]]] = [
    ("mosfet.idvg", "nmos_basic", "mosfet-4t", "nmos-generic", {}),
    ("basic.diode_iv", "diode_basic", "diode-2t", "diode-generic", {}),
    ("mosfet.idvg_pulsed", "nmos_selfheat", "mosfet-4t", "nmos-pulsed", {"vd": 3.0}),
    ("mosfet.id_t_sampling", "igzo_transient", "mosfet-4t", "nmos-generic", {"vd": 0.1}),
    ("spgu.pulse_train", "fefet_lab", "fefet-sel", "fefet-lab", {}),
    ("fefet.pulse_write_read", "fefet_lab", "fefet-sel", "fefet-lab", {}),
]
"""(recipe, scenario, pin map, DUT profile, parameters): card example plans whose pin map lands a pad on the GNDU,
with SMU, pulsed-SMU, sampling and HV-SPGU sources (the SPGU's return current is its short-circuit bound)."""
PULSE_ONLY = frozenset({"spgu.pulse_train"})
"""Rows whose only source is a gate pulse train with the drain floating: nothing needs to return through the GNDU."""


def run_row(world: World, recipe_id: str, scenario: str, pin_map: str, dut: str | None,
            params: dict[str, Any]) -> tuple[dict[str, Any], float]:
    world.use_scenario(scenario)
    svc = world.service()
    plan = svc.validate_plan(recipe_id=recipe_id, pin_map=pin_map, dut_profile=dut, params=params or None)
    assert plan.tier in ("ok", "needs_confirmation") and plan.plan_id is not None, (plan.message, plan.findings)
    assert not any(f.rule_id == "R-GNDU-01" for f in plan.findings)
    result = (svc.run_plan(plan.plan_id) if plan.tier == "ok"
              else svc.run_confirmed_plan(plan.plan_id, summary=plan.summary))  # type: ignore[arg-type]
    assert result.ok, result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    record = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    state = load_state_file(sim_state_file(world.state_dir, scenario))
    assert state is not None
    return record, state.gndu_peak_a


@pytest.mark.parametrize(("recipe_id", "scenario", "pin_map", "dut", "params"), ROWS, ids=[r[0] for r in ROWS])
def test_the_gndu_bound_holds_what_the_simulator_sees_return(recipe_id: str, scenario: str, pin_map: str,
                                                             dut: str | None, params: dict[str, Any],
                                                             world: World) -> None:
    record, peak = run_row(world, recipe_id, scenario, pin_map, dut, params)
    envelope = CompiledEnvelope.model_validate(record["plan"]["envelope"])
    station = world.service().config.get().station
    dc, pulsed = gndu_return_a(envelope, station)
    assert 0.0 < dc + pulsed <= GNDU_MAX_A
    assert peak <= dc + pulsed  # never more than the rule allowed for
    if recipe_id not in PULSE_ONLY:
        assert peak > 0.0  # the drain or anode current returned through the GNDU


def test_a_landing_without_a_gndu_pad_owes_the_gndu_nothing(world: World) -> None:
    record, peak = run_row(world, "moscap.qscv", "moscap_dit", "moscap-scuu", "moscap-generic", {})
    assert not any(f["rule_id"] == "R-GNDU-01" for report in record["rules"] for f in report["findings"])
    assert peak == 0.0
