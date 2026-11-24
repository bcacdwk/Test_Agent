"""The WGFMU builders and the kind's data layout against the simulated library (blueprint v2 2.7.1, 4.2 "WGFMU engine":
event timing exact on the 10 ns grid; WP10.4). Each committed ``wgfmu_waveform`` recipe is compiled by the real kind,
loaded through the guarded ``WgfmuDriver`` and run on ``SimWgfmu`` (scenario ``nmos_wgfmu``, noiseless); then:

- every channel stores exactly the values ``WaveformProgram.points`` counts and ``catalog.waveforms.point_layout``
  places (the library's time stamp = window start + average / 2, WG p126 (4-56));
- ``program_levels`` equals the library's interpolated force value at the data times and at times inside the 50 ns
  gaps between sequence entries;
- the drain current at each plateau equals the device model's quasi-static current at the programmed levels (on a
  ramp it lies between the currents at the two ends of its averaging window);
- the RSU connect goes through the guard (``check_route``), and the simulator's RSU "From SMU" cabling applies before
  any library session ever recorded a channel state (an SMU reaches the DUT through the RSU's normal path).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.kinds.wgfmu_waveform import WgfmuWaveformKind, stored, waveform_table
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.driver.wgfmu import WgfmuDriver
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.sources import WaveformProgram
from b1500_test_agent.transport.sim.devices import Circuit
from tests.sim import wgfmu_examples as ex
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station, pin_map_exact

pytestmark = pytest.mark.wgfmu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
MOSFET = pin_map_exact("mosfet-wgfmu", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU"})
CASES = {
    "wgfmu.pulsed_iv": {"vg_points": 5},
    "wgfmu.fast_iv": {"ramp": 2e-6, "interval": 1e-7, "cycles": 2},
    "wgfmu.pulse_train": {"count": 4, "samples": 3},
    "wgfmu.rtn": {"points": 500, "interval": 1e-6, "average": 1e-6, "settle": 1e-5},  # dc_sample (WP10.5)
}


def compiled(recipe_id: str, **values: Any) -> tuple[Any, PlanRecord]:
    rec = REGISTRY.get(recipe_id)
    binding = bind_roles(rec, MOSFET, STATION, MOSFET.name)
    out = WgfmuWaveformKind().compile(rec, resolve_params(rec, values)[0], binding, STATION)
    plan = PlanRecord.model_construct(plan_id="P-TESTTESTTE", program=out.program)
    return out, plan


def run_on_sim(out: Any) -> tuple[ex.Station, Any, Any]:
    station = ex.station(noiseless(load_scenario("nmos_wgfmu")))
    driver = WgfmuDriver(station.sim, OutputGuard(out.envelope, switches=STATION.switches))
    station.sim.open_session(ex.ADDRESS)
    station.sim.initialize()
    waveform = WaveformProgram.model_validate(out.program["sources"]["waveform"])
    driver.load(waveform)
    block = driver.run(poll_s=0.5)
    return station, waveform, block


def model_drain(vg: np.ndarray, vd: np.ndarray) -> np.ndarray:
    device = Circuit(load_scenario("nmos_wgfmu")).devices["dut"]
    return np.asarray([device.terminal_currents({"gate": g, "drain": d, "source": 0.0, "bulk": 0.0})["drain"]
                       for g, d in zip(vg, vd, strict=True)])


@pytest.mark.parametrize("recipe_id", sorted(CASES))
def test_layout_levels_and_currents_match_the_simulated_library(recipe_id: str) -> None:
    out, plan = compiled(recipe_id, **CASES[recipe_id])
    station, waveform, block = run_on_sim(out)
    assert block.status == "completed" and set(block.traces) == {202}
    trace = block.traces[202]
    layout = wf.point_layout(waveform, 202)
    assert len(trace) == len(layout) == waveform.points(202)
    np.testing.assert_allclose(trace.time_s, layout.start_s + layout.average_s / 2, rtol=0, atol=1e-12)
    np.testing.assert_allclose(station.sim.measure_times(202), trace.time_s, rtol=0, atol=1e-12)
    for ch in (201, 202):
        np.testing.assert_allclose(wf.program_levels(waveform, ch, trace.time_s),
                                   station.sim.force_levels(ch, trace.time_s), rtol=0, atol=1e-12)
    probes = np.linspace(0.0, waveform.total_time_s() * 1.01, 4001)
    for ch in (201, 202):  # also inside the 50 ns gaps between entries and after the end
        np.testing.assert_allclose(wf.program_levels(waveform, ch, probes), station.sim.force_levels(ch, probes),
                                   rtol=0, atol=1e-12)
    program, _, _ = stored(plan)
    table = waveform_table(program, waveform, block.traces)
    assert set(table["drain_I_status"]) == {"N"}
    measured = table["drain_I"].to_numpy()
    vd = table["drain_V"].to_numpy()
    if recipe_id == "wgfmu.fast_iv":
        # an average over a window of the ramp lies between the currents at the window's two ends (Id rises with Vg)
        start = model_drain(wf.program_levels(waveform, 201, layout.start_s), vd)
        end = model_drain(wf.program_levels(waveform, 201, layout.start_s + layout.average_s), vd)
        low, high = np.minimum(start, end), np.maximum(start, end)
        assert np.all(measured >= low * (1 - 1e-6) - 1e-15) and np.all(measured <= high * (1 + 1e-6) + 1e-15)
    else:  # flat tops: the reading is the quasi-static current at the programmed levels
        np.testing.assert_allclose(measured, model_drain(table["gate_V"].to_numpy(), vd), rtol=1e-6, atol=1e-12)


def test_dc_sample_in_the_lab_layout_measures_both_channels_at_the_same_times() -> None:
    """``wgfmu.lfn`` (builder ``dc_sample``, WP10.5): channel 201 reads back its own 1 V (voltage measurement),
    channel 202 the drain current, both at the same window centres on the 10 ns grid."""
    out, plan = compiled("wgfmu.lfn", points=300, interval=1e-7, average=1e-7, settle=1e-6)
    _, waveform, block = run_on_sim(out)
    assert block.status == "completed" and set(block.traces) == {201, 202}
    gate, drain = block.traces[201], block.traces[202]
    assert (gate.quantity, drain.quantity) == ("V", "I") and len(gate) == len(drain) == 300
    np.testing.assert_array_equal(gate.time_s, drain.time_s)
    layout = wf.point_layout(waveform, 201)
    np.testing.assert_allclose(gate.time_s, layout.start_s + layout.average_s / 2, rtol=0, atol=1e-15)
    np.testing.assert_allclose(gate.value, 1.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(drain.value, model_drain(np.full(300, 1.0), np.full(300, 0.1)), rtol=1e-6, atol=1e-12)
    program, _, _ = stored(plan)
    table = waveform_table(program, waveform, block.traces)
    assert list(table.columns) == ["step", "t_s", "event", "drain_range", "gate_V", "gate_V_status", "drain_V",
                                   "drain_I", "drain_I_status"]


def test_the_rsu_routes_go_through_the_guard() -> None:
    out, _ = compiled("wgfmu.pulsed_iv", vg_points=2)
    assert out.envelope.routes == frozenset(out.routes_by_phase["waveform"])
    assert [r.state for r in out.routes_by_phase["rest"]] == ["open", "open"]
    station, _, _ = run_on_sim(out)
    assert station.sim.rsu_path(201) == "wgfmu"  # connected for the run (until the phase's safe state)


def test_an_smu_reaches_the_dut_through_the_rsu_before_any_library_session() -> None:
    """``SimScenario.rsu_smu``: the RSU's normal path is its SMU input (WG p19 (1-7)) also when no library session
    ever recorded a state for the channel (the DC reference of the pulsed I-V AC runs first)."""
    station = ex.station(noiseless(load_scenario("nmos_wgfmu")))
    assert station.flex.instrument.state.wgfmu == {}
    station.flex_run("CN 4,3", "DV 4,0,2,1E-4", "DV 3,0,1,1E-3")
    station.flex_run("MM 1,3", "CMM 3,1", "XE")
    current = float(station.flex.read().split(",")[0].strip()[3:])
    assert current == pytest.approx(model_drain(np.asarray([2.0]), np.asarray([1.0]))[0], rel=1e-3)
