"""Device-model truth (blueprint 3, 8.1): resistor/short/open, and the EKV MOSFET whose Vth and subthreshold swing
are recovered from a simulated sweep with a tiny fit inside the test (``analysis/`` is not imported)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.sim import MosfetEkvParams, ResistorParams, ShortParams
from b1500_test_agent.models.station import SimDeviceModel, SimScenario
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.devices.basic import OpenDevice, ResistorDevice
from b1500_test_agent.transport.sim.devices.mosfet import MosfetEkv
from tests.sim.helpers import load_scenario, noiseless, run, values

VD_LIN = 0.1


def idvg(make_sim, scenario: SimScenario, *, vd: float, start: float = -0.5, stop: float = 2.0,
         points: int = 251) -> tuple[list[float], list[float]]:
    """Gate sweep on SMU4, drain bias and current on SMU3 (the ``nmos_basic`` wiring)."""
    sim = make_sim(scenario)
    run(sim, "CN 3,4", f"DV 3,0,{vd},1E-2", "MM 2,3", f"WV 4,1,0,{start},{stop},{points},1E-4", "XE")
    vg = [start + (stop - start) * i / (points - 1) for i in range(points)]
    return vg, values(sim.read())


def linear_fit(x: list[float], y: list[float]) -> tuple[float, float]:
    """Least-squares slope and intercept."""
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sum((a - mx) ** 2 for a in x)
    return slope, my - slope * mx


def test_ekv_vth_is_recoverable_by_max_gm_extrapolation(make_sim) -> None:
    scenario = noiseless(load_scenario("nmos_basic"))
    truth = scenario.models["dut"].params
    vg, ids = idvg(make_sim, scenario, vd=VD_LIN)
    gm = [(ids[i + 1] - ids[i - 1]) / (vg[i + 1] - vg[i - 1]) for i in range(1, len(vg) - 1)]
    k = max(range(len(gm)), key=gm.__getitem__) + 1
    vth = vg[k] - ids[k] / gm[k - 1] - VD_LIN / 2
    assert vg[k] > truth["vth0"] + 0.05  # mobility degradation: gm peaks above threshold, then falls
    assert gm[-1] < 0.8 * gm[k - 1]
    expected = truth["vth0"] + (truth["slope_factor"] - 1) * VD_LIN / 2  # EKV linear region, Vd/2 subtracted
    assert vth == pytest.approx(expected, abs=0.01)
    assert vth == pytest.approx(truth["vth0"], abs=0.03)


def test_ekv_subthreshold_swing_is_recoverable(make_sim) -> None:
    scenario = noiseless(load_scenario("nmos_basic"))
    vg, ids = idvg(make_sim, scenario, vd=VD_LIN)
    window = [(v, math.log10(i)) for v, i in zip(vg, ids, strict=True) if -0.1 <= v <= 0.2]
    slope, _ = linear_fit([w[0] for w in window], [w[1] for w in window])
    device = MosfetEkv("dut", MosfetEkvParams.model_validate(scenario.models["dut"].params))
    assert 1 / slope == pytest.approx(device.subthreshold_swing, rel=0.02)
    assert device.subthreshold_swing == pytest.approx(1.3 * 8.617333262e-5 * 300 * math.log(10))


def test_ekv_saturation_square_law_and_clm(make_sim) -> None:
    params = MosfetEkvParams(vth0=0.4, slope_factor=1.0, beta=1e-3, lambda_=0.1)
    device = MosfetEkv("m", params)
    vov = 1.0
    sat = device.channel_current(vg=0.4 + vov, vd=3.0)
    assert sat == pytest.approx(params.beta / 2 * vov**2 * (1 + 0.1 * 3.0), rel=0.02)
    assert device.channel_current(vg=1.4, vd=3.0) > device.channel_current(vg=1.4, vd=2.0)  # lambda > 0


def test_ekv_series_resistance_reduces_the_current() -> None:
    base = {"vth0": 0.4, "beta": 2e-3}
    without = MosfetEkv("m", MosfetEkvParams(**base)).channel_current(vg=2.0, vd=0.1)
    with_rs = MosfetEkv("m", MosfetEkvParams(**base, rs_ohm=50.0)).channel_current(vg=2.0, vd=0.1)
    assert with_rs < without
    # the solved current satisfies the internal-node equation
    device = MosfetEkv("m", MosfetEkvParams(**base, rs_ohm=50.0))
    internal = device._intrinsic(2.0, 0.1 - with_rs * 50.0, with_rs * 50.0)
    assert with_rs == pytest.approx(internal, rel=1e-6)


def test_ekv_p_channel_mirrors_the_n_channel() -> None:
    n = MosfetEkv("n", MosfetEkvParams(polarity="n", vth0=0.4))
    p = MosfetEkv("p", MosfetEkvParams(polarity="p", vth0=-0.4))
    assert p.channel_current(vg=-1.5, vd=-0.1) == pytest.approx(-n.channel_current(vg=1.5, vd=0.1))
    assert p.channel_current(vg=1.0, vd=-0.1) == pytest.approx(0.0, abs=1e-12)  # off for positive gate


def test_ekv_gate_leakage_and_terminal_balance() -> None:
    device = MosfetEkv("m", MosfetEkvParams(vth0=0.4, gate_leak_s=1e-9))
    currents = device.terminal_currents({"gate": 2.0, "drain": 0.5, "source": 0.0, "bulk": 0.0})
    assert currents["gate"] == pytest.approx(0.5e-9 * 2.0 + 0.5e-9 * 1.5)
    assert sum(currents.values()) == pytest.approx(0.0, abs=1e-18)


def test_ekv_floating_terminals() -> None:
    device = MosfetEkv("m", MosfetEkvParams(vth0=0.4))
    assert set(device.terminal_currents({"gate": None, "drain": 1.0, "source": 0.0}).values()) == {0.0}
    floating_bulk = device.terminal_currents({"gate": 1.5, "drain": 0.1, "source": 0.0, "bulk": None})
    tied_bulk = device.terminal_currents({"gate": 1.5, "drain": 0.1, "source": 0.0, "bulk": 0.0})
    assert floating_bulk == tied_bulk


def test_resistor_short_and_open() -> None:
    resistor = ResistorDevice("r", "resistor", ResistorParams(r_ohm=2000.0))
    assert resistor.terminal_currents({"a": 1.0, "b": -1.0}) == {"a": pytest.approx(1e-3), "b": pytest.approx(-1e-3)}
    assert resistor.terminal_currents({"a": 1.0, "b": None}) == {"a": 0.0, "b": 0.0}
    assert OpenDevice("o").terminal_currents({"x": 5.0, "y": 0.0}) == {"x": 0.0, "y": 0.0}
    short = ResistorDevice("s", "short", ShortParams())
    assert short.terminal_currents({"a": 0.01, "b": 0.0})["a"] == pytest.approx(0.1)  # 0.1 Ohm default


def test_circuit_follows_the_physical_wiring_not_the_pin_map() -> None:
    """A wrong pin map behaves like mis-wiring: forcing a channel the DUT is not wired to measures nothing."""
    scenario = noiseless(load_scenario("nmos_basic"))  # gate on SMU4, drain on SMU3
    circuit = Circuit(scenario)
    on = circuit.channel_currents({4: 1.5, 3: 0.1})
    swapped = circuit.channel_currents({2: 1.5, 3: 0.1})  # agent believes the gate is on SMU2
    assert on[3] > 1e-5
    assert abs(swapped[3]) < 1e-12 and swapped[2] == 0.0


def test_truth_parameters_are_typed_and_exposed(nmos: SimScenario) -> None:
    circuit = Circuit(nmos)
    device = circuit.devices["dut"]
    assert isinstance(device.params, MosfetEkvParams)
    assert device.params.vth0 == 0.42 and device.params.lambda_ == 0.05
    assert device.params.model_dump()["lambda"] == 0.05  # YAML key "lambda" round-trips


@pytest.mark.parametrize(
    "spec",
    [{"model": "mosfet_ekv", "params": {"vth0": 0.4, "bogus": 1}}, {"model": "mosfet_ekv", "params": {"vth0": 0.4,
     "polarity": "x"}}, {"model": "resistor", "params": {}}, {"model": "resistor", "params": {"r_ohm": -1}},
     {"model": "diode", "params": {}}],
)  # fmt: skip
def test_device_params_are_validated(spec: dict) -> None:
    with pytest.raises(ValidationError):
        SimDeviceModel.model_validate(spec)


def test_scenario_rejects_unknown_terminal_names(nmos: SimScenario) -> None:
    data = nmos.model_dump()
    data["wiring"]["dut"]["collector"] = 2
    with pytest.raises(ValidationError, match="no terminal"):
        SimScenario.model_validate(data)
