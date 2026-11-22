"""``mosfet.charge_pumping`` through ``B1500Service`` on the simulator (blueprint v2 3.3, scenario ``nmos_cv``; WP9.3
per-recipe AC and "Icp proportional to f within +-10 % of the model"): tier as the card says, every bulk reading taken
while its gate train runs (SEL1.OUT1 on PGU), the default analysis ``charge_pumping`` against the device truth
(``Mosfet.charge_pumping_truth``: Qcp, every Icp/f), Nit and Dit with the geometry, the base-level plateau, and a
train too short for its reading refused at compile time."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.transport.sim.devices import Circuit
from tests.integration.helpers import World
from tests.sim.helpers import load_scenario
from tests.sim.spgu_pulse_helpers import CHARGE_PUMPING

RECIPE = "mosfet.charge_pumping"
pytestmark = [pytest.mark.spgu, pytest.mark.parametrize("recipe_id", [RECIPE])]

SCENARIO = "nmos_cv"
SER = 1e6
LEVEL = (SER + 50.0) / SER
"""The gate is an open load: it sees the set level x (SER + 50) / SER."""
FREQS = [1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6]
EDGE = 1e-7


def device() -> Any:
    return Circuit(load_scenario(SCENARIO)).devices["dut"]


def truth(base: float = -2.0, amplitude: float = 4.0, f: float = 1e5) -> dict[str, float]:
    return device().charge_pumping_truth(base * LEVEL, (base + amplitude) * LEVEL, f, EDGE, EDGE)


def run(world: World, **params: Any) -> tuple[Any, Any, pd.DataFrame]:
    world.use_scenario(SCENARIO)
    service = world.service()
    validation = service.validate_plan(**CHARGE_PUMPING, params=params)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert result.ok and result.outcome == "completed", result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    return validation, result, pd.read_csv(folder / DATA_FILE)


def test_card_example_needs_the_pulse_and_topology_confirmations(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**CHARGE_PUMPING)
    assert validation.tier == "needs_confirmation"
    assert sorted(validation.confirm_reasons) == ["soft_pulse", "unverified_pin_map", "unverified_topology"]
    summary = str(validation.summary)
    assert "gate=SPGU1:101 via SEL1.OUT1 pulse -2->2 V 500 ns..50 us x376000 SER 1 MOhm Isc<=0.04 A residual" in summary
    assert "bulk=SMU4(HRSMU) measure at 0 V Icomp 1 uA" in summary


def test_icp_is_proportional_to_f_within_ten_percent_of_the_model(recipe_id: str, world: World) -> None:
    """The WP9.3 AC: Icp proportional to f within +-10 % of the model, reported by the default analysis."""
    _, result, table = run(world)
    assert list(table.columns) == ["step", "freq_hz", "gate_V", "drain_V", "source_V", "bulk_I", "bulk_I_status",
                                   "trust"]  # gate: the base level; drain/source: the reverse bias
    assert table["freq_hz"].tolist() == pytest.approx(FREQS) and set(table["bulk_I_status"]) == {"N"}
    model = truth()
    for f, icp in zip(table["freq_hz"], table["bulk_I"], strict=True):  # every point on the model line
        assert icp == pytest.approx(model["qcp_c"] * f, rel=0.10)
    found = {r.quantity: r for r in result.analyses}
    qcp = found["qcp"]
    assert qcp.outcome == "ok" and qcp.unit == "C" and qcp.classification == "linear"
    assert qcp.value == pytest.approx(model["qcp_c"], rel=0.10)  # Qcp = q A Dit dE
    assert qcp.fit["r2"] > 0.999 and abs(qcp.fit["offset_a"]) < 0.05 * table["bulk_I"].iloc[0]
    assert found["icp_max"].value == pytest.approx(truth(f=1e6)["icp_a"], rel=0.10)
    assert qcp.derived and qcp.method_record.name == "charge_pumping"


def test_nit_and_dit_with_the_gate_area_and_energy_window(recipe_id: str, world: World) -> None:
    _, result, _ = run(world)
    model = truth()
    area_um2 = 100.0 * 10.0  # DUT profile nmos-cv geometry (W x L)
    analysis = world.service().analyze_run(str(result.run_id), "charge_pumping",
                                           {"area_um2": area_um2, "delta_e_ev": model["delta_e_ev"]})
    assert analysis.ok, analysis.message
    found = {r.quantity: r for r in analysis.results}
    assert found["nit"].unit == "cm^-2" and found["nit"].value == pytest.approx(model["nit_cm2"], rel=0.10)
    assert found["dit"].unit == "cm^-2 eV^-1" and found["dit"].value == pytest.approx(5e10, rel=0.10)


def test_every_reading_is_taken_while_its_train_runs(recipe_id: str, world: World) -> None:
    _, result, _ = run(world)
    log = [r for r in world.sim_log(SCENARIO) if r.outcome == "ok"]
    sent = [r.command for r in log]
    assert sent.index("ERSSP 0,2") < sent.index("CN 4,5,6,101")  # gate routed to the PGU before the outputs go on
    starts = [i for i, c in enumerate(sent) if c == "SRP"]
    reads = [i for i, c in enumerate(sent) if c == "XE"]
    assert len(starts) == len(reads) == len(FREQS)
    for start, read in zip(starts, reads, strict=True):
        assert start < read and "SPUPD 101" not in sent[start:read]  # the same train, still running (checked)
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert data["kind_result"]["readings"] == len(FREQS) and data["kind_result"]["spp_fallbacks"] == 0
    assert data["cleanup"]["switches_after"]["SEL1.OUT1"] == "open" and data["cleanup"]["verified"] == "sim_state"


def test_base_level_sweep_shows_the_plateau(recipe_id: str, world: World) -> None:
    bases = [-4.0, -3.5, -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0]
    _, result, table = run(world, v_base=bases, frequency=[1e5])
    assert table["gate_V"].tolist() == bases
    model_top = max(truth(base=b)["icp_a"] for b in bases)
    assert table["bulk_I"].max() == pytest.approx(model_top, rel=0.05)
    qcp = next(r for r in result.analyses if r.quantity == "qcp")
    assert any("One frequency only" in w for w in qcp.warnings)
    # plateau (Icp >= 90 % of the top): the top passes Vth (0.7 V) and the base stays below Vfb (-0.62 V)
    assert -3.5 <= qcp.fit["plateau_low_v"] <= -2.5 and -1.5 <= qcp.fit["plateau_high_v"] <= -0.5


def test_a_train_too_short_for_its_reading_is_refused(recipe_id: str, world: World) -> None:
    world.use_scenario(SCENARIO)
    validation = world.service().validate_plan(**CHARGE_PUMPING, params={"duration": 0.05})
    assert not validation.ok and validation.error_code == "invalid_input"
    assert "ends before its read" in validation.message
