"""v2 device registry, circuit API and persistence (blueprint 4.1, 4.2, WP5.9): every new model is selectable from
scenario YAML with typed params and terminals; ``Circuit.advance`` drives dynamic devices on virtual time; attached
noise is found per channel; device state survives two ``SimTransport`` instances (processes) through the state
file; the v1 instrument (commit path) works with the new stateful devices; the shared effective-time laws are exact
however a constant stress is split into steps."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.models.sim import DEVICE_PARAMS, DEVICE_TERMINALS
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from b1500_test_agent.transport.sim.devices import AcDevice, Circuit, DynamicDevice, StatefulDevice
from b1500_test_agent.transport.sim.devices.circuit import DEVICE_BUILDERS
from b1500_test_agent.transport.sim.devices.dielectric import DielectricDevice
from b1500_test_agent.transport.sim.devices.ferro import FefetDevice
from b1500_test_agent.transport.sim.devices.kinetics import (
    endurance_scale,
    log_decay,
    play,
    power_law_step,
    stretched_remaining,
    stretched_step,
)
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from b1500_test_agent.transport.sim.devices.mosfet import Mosfet
from b1500_test_agent.transport.sim.devices.noise import NoiseSource
from tests.sim.helpers import run, scenario_with, values

V2_MODELS: dict[str, dict[str, Any]] = {
    "mosfet": {"params": {"vth0": 0.5, "bti_a": 5e-3, "rth_k_per_w": 1000.0},
               "wiring": {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}},
    "moscap": {"params": {"nsub_cm3": 3e16, "hysteresis_v": 0.05}, "wiring": {"gate": 4, "bulk": "GNDU"}},
    "capacitor": {"params": {"c_f": 100e-12}, "wiring": {"a": 4, "b": "GNDU"}},
    "fixture": {"params": {}, "wiring": {"high": 7, "low": "GNDU"}},
    "dielectric": {"params": {"seed": 2}, "wiring": {"top": 4, "bottom": "GNDU"}},
    "fecap": {"params": {"wake_frac": 0.1}, "wiring": {"top": 4, "bottom": "GNDU"}},
}


def single(model: str) -> SimScenario:
    spec = V2_MODELS[model]
    return scenario_with({"dut": {"model": model, "params": spec["params"]}}, {"dut": spec["wiring"]})


def test_registry_lists_the_same_models_everywhere() -> None:
    assert set(DEVICE_PARAMS) == set(DEVICE_BUILDERS) == set(DEVICE_TERMINALS)
    assert {"mosfet", "moscap", "capacitor", "fixture", "dielectric", "fecap", "noise"} <= set(DEVICE_PARAMS)


@pytest.mark.parametrize("model", sorted(V2_MODELS))
def test_every_v2_model_is_selectable_from_a_scenario(model: str) -> None:
    circuit = Circuit(single(model))
    device = circuit.devices["dut"]
    assert device.model == model
    dynamic = model not in ("fixture",)
    assert isinstance(device, DynamicDevice) == dynamic
    assert isinstance(device, StatefulDevice) == dynamic
    if model in ("moscap", "capacitor", "dielectric", "fecap"):
        assert isinstance(device, AcDevice) and device.capacitance(0.0, 1e5) > 0.0


def test_scenario_validation_rejects_bad_params_and_terminals() -> None:
    with pytest.raises(ValueError, match="Invalid moscap params"):
        scenario_with({"dut": {"model": "moscap", "params": {"nsub_cm3": 1.0}}}, {"dut": {"gate": 4}})
    with pytest.raises(ValueError, match="no terminal"):
        scenario_with({"dut": {"model": "fecap", "params": {}}}, {"dut": {"gate": 4}})
    with pytest.raises(ValueError, match="pr_uc_cm2 must be below"):
        scenario_with({"dut": {"model": "fecap", "params": {"pr_uc_cm2": 30.0}}}, {"dut": {"top": 4}})
    with pytest.raises(ValueError, match="given together"):
        scenario_with({"dut": {"model": "mosfet", "params": {"vth0": 0.5, "w_um": 1.0}}}, {"dut": {"gate": 4}})


def noisy_scenario(**noise: Any) -> SimScenario:
    return scenario_with(
        {"dut": {"model": "mosfet", "params": {"vth0": 0.5}},
         "rtn": {"model": "noise", "params": {"attach": "dut", "terminal": "drain", "rtn_tau_c_s": 1e-3,
                                              "rtn_tau_e_s": 1e-3, "rtn_delta_rel": 0.05, **noise}}},
        {"dut": {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}, "rtn": {}})


def test_noise_attaches_to_the_channel_of_its_terminal() -> None:
    circuit = Circuit(noisy_scenario())
    assert [s.name for s in circuit.noise_on(3)] == ["rtn"] and circuit.noise_on(301) == circuit.noise_on(3)
    assert circuit.noise_on(4) == [] and circuit.noise_on("GNDU") == []
    assert circuit.channel_currents({3: 0.1, 4: 1.5}) == Circuit(scenario_with(
        {"dut": {"model": "mosfet", "params": {"vth0": 0.5}}},
        {"dut": {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}})).channel_currents({3: 0.1, 4: 1.5})
    with pytest.raises(ValueError, match="attach 'nope'"):
        Circuit(noisy_scenario(attach="nope"))
    with pytest.raises(ValueError, match="no wired terminal 'bulk_x'"):
        Circuit(noisy_scenario(terminal="bulk_x"))


def test_circuit_advance_drives_dynamic_devices_on_virtual_time() -> None:
    scenario = scenario_with(
        {"cap": {"model": "capacitor", "params": {"c_f": 1e-9}},
         "ox": {"model": "dielectric", "params": {"tbd_eta_s": 1.0, "tbd_v_ref": 4.0, "seed": 1}},
         "r": {"model": "resistor", "params": {"r_ohm": 1e3}}},
        {"cap": {"a": 1, "b": "GNDU"}, "ox": {"top": 2, "bottom": "GNDU"}, "r": {"a": 3, "b": "GNDU"}})
    circuit = Circuit(scenario)
    currents = circuit.advance(1e-3, {1: 1.0, 2: 4.0, 3: 1.0})
    assert currents[1] == pytest.approx(1e-9 * 1.0 / 1e-3)  # displacement C·ΔV/dt
    assert currents[3] == pytest.approx(1e-3)  # a stateless device answers its DC current
    ox = circuit.devices["ox"]
    assert isinstance(ox, DielectricDevice)
    t_bd = ox.t_bd(4.0)
    circuit.advance(t_bd * 1.01, {1: 1.0, 2: 4.0, 3: 1.0})
    assert ox.broken
    assert circuit.export_state()["ox"]["broken"] is True
    assert circuit.advance(0.0, {1: 1.0})[1] == 0.0  # no change, no time: no displacement
    with pytest.raises(ValueError, match="dt >= 0"):
        circuit.advance(-1.0, {1: 0.0})


def test_v2_state_survives_two_transports(tmp_path: Path) -> None:
    """Process A stresses and switches devices and saves; process B (a new transport on the same state file) sees
    the same internal state; a transport without the file starts fresh."""
    scenario = scenario_with(
        {"fet": {"model": "mosfet", "params": {"vth0": 0.5, "bti_a": 5e-3}},
         "fe": {"model": "fefet", "params": {"vth0": 0.6, "retention_rate": 0.05, "wake_frac": 0.2}},
         "mos": {"model": "moscap", "params": {"hysteresis_v": 0.05, "hysteresis_vc_v": 1.5}},
         "rtn": {"model": "noise", "params": {"attach": "fet", "terminal": "drain", "rtn_tau_c_s": 1e-3,
                                              "rtn_tau_e_s": 1e-3, "rtn_delta_rel": 0.1}}},
        {"fet": {"gate": 1, "drain": 3, "source": "GNDU", "bulk": "GNDU"},
         "fe": {"gate": 2, "drain": 4, "source": "GNDU", "bulk": "GNDU"},
         "mos": {"gate": 2, "bulk": "GNDU"}, "rtn": {}})
    path = sim_state_file(tmp_path, scenario.name)
    writer = SimTransport(scenario, state_file=path)
    writer.open()
    circuit = writer.instrument.circuit
    circuit.advance(100.0, {1: 2.0, 2: 4.5, 3: 0.0, 4: 0.0})  # BTI stress, FeFET program, border traps charge
    circuit.advance(10.0, {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0})  # recovery and retention at 0 V
    rtn = circuit.devices["rtn"]
    assert isinstance(rtn, NoiseSource)
    rtn.sample(1e-6, 1e-5, 100)
    writer.instrument._sync_devices()
    writer.save_state()
    stored = json.loads(path.read_text(encoding="utf-8"))["devices"]
    assert set(stored) == {"fet", "fe", "mos", "rtn"}
    assert stored["fe"]["cycles"] == 0.5 and stored["rtn"]["calls"] == 1 and stored["mos"]["s_bt"] > 0.9

    reader = SimTransport(scenario, state_file=path)
    reader.open()
    for name in ("fet", "fe", "mos", "rtn"):
        assert reader.instrument.circuit.devices[name].export_state() == circuit.devices[name].export_state()
    fet = reader.instrument.circuit.devices["fet"]
    assert isinstance(fet, Mosfet) and fet.bti_recovering and fet.vth > 0.5
    fe = reader.instrument.circuit.devices["fe"]
    assert isinstance(fe, FefetDevice) and fe.t_ret == pytest.approx(10.0)
    fresh = SimTransport(scenario, state_file=None)
    fresh.open()
    mos = fresh.instrument.circuit.devices["mos"]
    assert isinstance(mos, MoscapDevice) and mos.s_bt == 0.0


def test_corrupt_v2_state_is_a_transport_error(tmp_path: Path) -> None:
    from b1500_test_agent.transport.base import TransportError

    scenario = single("dielectric")
    path = sim_state_file(tmp_path, scenario.name)
    sim = SimTransport(scenario, state_file=path)
    sim.open()
    sim.save_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["devices"]["dut"]["damage"] = 2.0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TransportError, match="damage"):
        SimTransport(scenario, state_file=path).open()


def test_smu_staircase_breaks_the_dielectric_at_bdv(make_sim) -> None:
    """The v1 instrument commits each step to the new stateful devices: a staircase finds the BDV and the broken
    state persists in the simulator state."""
    sim = make_sim(single("dielectric"))
    run(sim, "CN 4", "MM 2,4", "WV 4,1,0,0.1,8.0,80,1E-2", "XE")
    currents = values(sim.read())
    device = sim.instrument.circuit.devices["dut"]
    assert isinstance(device, DielectricDevice)
    k = next(i for i, c in enumerate(currents) if c > 1e-4)
    assert 0.1 * (k + 1) == pytest.approx(device.bdv, abs=0.1 + 1e-9)  # 6.0 V for 5 nm at 12 MV/cm
    assert device.broken and sim.instrument.state.devices["dut"]["broken"] is True


# -- shared time laws ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("pieces", [1, 3, 17])
def test_effective_time_laws_are_exact_under_constant_stress(pieces: int) -> None:
    x_s, x_p = -1.0, 0.0
    for _ in range(pieces):
        x_s = stretched_step(x_s, 0.8, -1.0, 2.0 / pieces, 1.5, 0.7)
        x_p = power_law_step(x_p, 0.02, 0.2, 500.0 / pieces)
    assert x_s == pytest.approx(0.8 - 1.8 * math.exp(-((2.0 / 1.5) ** 0.7)), rel=1e-12)
    assert x_p == pytest.approx(0.02 * 500.0 ** 0.2, rel=1e-12)


def test_law_edge_cases() -> None:
    assert stretched_step(0.3, 0.8, -1.0, 0.0, 1.0, 1.0) == 0.3  # no time
    assert stretched_step(0.3, 0.8, -1.0, 1.0, math.inf, 1.0) == 0.3  # no switching
    assert stretched_step(0.9, 0.8, -1.0, 1.0, 1.0, 1.0) == 0.8  # past the target: settles on it
    assert stretched_step(-2.0, 0.8, -1.0, 1.0, 1.0, 1.0) == pytest.approx(0.8 - 2.8 * math.exp(-1.0))
    assert stretched_remaining(1e300, 1e-300, 2.0) == 0.0 and stretched_remaining(1.0, 0.0, 1.0) == 0.0
    assert power_law_step(0.5, 0.0, 0.3, 10.0) == 0.5 and power_law_step(0.5, 1e-9, 0.3, 1.0) >= 0.5
    assert log_decay(1.0, 1e30, 0.5, 1.0) == 0.0 and log_decay(1.0, 0.0, 0.5, 1.0) == 1.0
    assert play(2.0, -1.0, 1.0) == 1.0 and play(0.2, -1.0, 1.0) == 0.2
    assert endurance_scale(0.0, 0.3, 10.0, 0.0, 0.5) == pytest.approx(0.7)
    assert endurance_scale(1e5, 0.0, 10.0, 1e5, 1.0) == pytest.approx(0.5)
