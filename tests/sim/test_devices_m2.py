"""M2 device-model truth (blueprint 3, 8.1): diode (Is, n, Rs, leakage, soft breakdown), resistor_100k, FeFET loop
width against ``FefetDevice.loop_truth`` and polarization persistence across ``SimTransport`` instances, damaged
MOSFET variants, and the wiring of the committed M2 scenarios against the example pin maps. Values are recovered
with tiny fits inside the tests (``analysis/`` is not imported)."""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.models.sim import DiodeParams, FefetParams, MosfetDamagedParams, MosfetEkvParams
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.base import TransportError
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from b1500_test_agent.transport.sim.devices import Circuit, StatefulDevice
from b1500_test_agent.transport.sim.devices.basic import DiodeDevice
from b1500_test_agent.transport.sim.devices.ferro import FefetDevice
from b1500_test_agent.transport.sim.devices.mosfet import DamagedMosfet, MosfetEkv
from tests.sim.helpers import REPO_ROOT, load_scenario, noiseless, run, scenario_with, values

PINMAP_DIR = REPO_ROOT / "config" / "pinmaps"
VD = 0.05


def linear_fit(x: list[float], y: list[float]) -> tuple[float, float]:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sum((a - mx) ** 2 for a in x)
    return slope, my - slope * mx


def linspace(start: float, stop: float, points: int) -> list[float]:
    return [start + (stop - start) * i / (points - 1) for i in range(points)]


def sweep(sim: SimTransport, *setup: str, channel: int, start: float, stop: float, points: int,
          icomp: float = 1e-2, mode: int = 1) -> list[float]:
    """``setup`` commands, then a staircase on ``channel`` (``WV`` mode 1 single, 3 double) and the read values."""
    run(sim, *setup, f"WV {channel},{mode},0,{start},{stop},{points},{icomp}", "XE")
    return values(sim.read())


def maxgm_vth(vg: list[float], ids: list[float], vd: float) -> float:
    """Linear extrapolation at the maximum transconductance, minus Vd/2."""
    gm = [(ids[k + 1] - ids[k - 1]) / (vg[k + 1] - vg[k - 1]) for k in range(1, len(vg) - 1)]
    k = max(range(len(gm)), key=gm.__getitem__) + 1
    return vg[k] - ids[k] / gm[k - 1] - vd / 2


def cc_vth(vg: list[float], ids: list[float], i_crit: float) -> float:
    """Gate voltage where the current first crosses ``i_crit`` (log-linear interpolation)."""
    for k in range(len(vg) - 1):
        a, b = ids[k], ids[k + 1]
        if a < i_crit <= b:
            frac = (math.log10(i_crit) - math.log10(max(a, 1e-30))) / (math.log10(b) - math.log10(max(a, 1e-30)))
            return vg[k] + frac * (vg[k + 1] - vg[k])
    raise AssertionError(f"current never crosses {i_crit}")


# -- diode -----------------------------------------------------------------------------------------------------------


def diode_params(scenario: str = "diode_basic") -> DiodeParams:
    return DiodeParams.model_validate(load_scenario(scenario).models["dut"].params)


def test_diode_current_solves_the_series_resistance_equation() -> None:
    device = DiodeDevice("d", diode_params())
    p = device.params
    assert device.current(0.0) == 0.0
    for v in (-20.0, -12.0, -5.0, -0.2, 0.1, 0.4, 0.6, 0.75, 0.9, 2.0, 42.0):
        current = device.current(v)
        vj = v - current * p.rs_ohm
        expected = p.is_a * math.expm1(vj / device.n_ut) + p.leak_s * vj \
            - p.ibv_a * (math.exp(-(vj + p.bv_v) / p.bv_width_v) - math.exp(-p.bv_v / p.bv_width_v))
        assert current == pytest.approx(expected, rel=1e-9, abs=1e-24), v
        assert math.copysign(1.0, current) == math.copysign(1.0, v)
    currents = [device.current(v) for v in linspace(-15.0, 1.0, 321)]
    assert all(b > a for a, b in itertools.pairwise(currents))  # strictly increasing
    assert device.terminal_currents({"anode": 0.7, "cathode": None}) == {"anode": 0.0, "cathode": 0.0}
    assert device.terminal_currents({"anode": 0.0, "cathode": -0.7})["cathode"] == pytest.approx(-device.current(0.7))


def test_diode_is_n_and_rs_are_recoverable(make_sim) -> None:
    truth = diode_params()
    sim = make_sim(load_scenario("diode_basic"))  # committed scenario, with noise
    vf = linspace(0.0, 0.9, 181)
    current = sweep(sim, "CN 3", "MM 2,3", channel=3, start=0.0, stop=0.9, points=181)
    ut = 8.617333262e-5 * truth.temperature_k
    window = [(v, math.log(i)) for v, i in zip(vf, current, strict=True) if 0.25 <= v <= 0.45]
    slope, intercept = linear_fit([w[0] for w in window], [w[1] for w in window])
    assert 1 / (slope * ut) == pytest.approx(truth.n, rel=0.01)
    assert math.exp(intercept) == pytest.approx(truth.is_a, rel=0.1)
    # Rs: the excess voltage over the ideal junction grows as I x Rs at high current
    high = [(v, i) for v, i in zip(vf, current, strict=True) if i > 1e-3]
    excess = [v - truth.n * ut * math.log1p(i / truth.is_a) for v, i in high]
    rs, _ = linear_fit([i for _, i in high], excess)
    assert rs == pytest.approx(truth.rs_ohm, rel=0.05)


def test_diode_reverse_leakage_and_soft_breakdown(make_sim) -> None:
    truth = diode_params()
    device = DiodeDevice("d", truth)
    assert device.current(-5.0) == pytest.approx(-truth.leak_s * 5.0, rel=0.05)  # leakage dominates at -5 V
    assert device.current(-truth.bv_v) == pytest.approx(-truth.ibv_a, rel=0.01)
    assert abs(device.current(-13.0)) > 5 * abs(device.current(-12.0)) > 25 * abs(device.current(-11.0))
    sim = make_sim(noiseless(load_scenario("diode_basic")))
    leakage = sweep(sim, "CN 3", "MM 2,3", channel=3, start=0.0, stop=-5.0, points=11)
    assert leakage[-1] == pytest.approx(device.current(-5.0), rel=1e-6)
    # into breakdown with a 10 uA compliance and automatic abort (WM 2): the sweep stops at the compliance step
    vr = linspace(0.0, -14.0, 29)
    data = sweep(sim, "WM 2,1", "MM 2,3", channel=3, start=0.0, stop=-14.0, points=29, icomp=1e-5)
    limited = next(i for i, v in enumerate(data) if abs(v) >= 1e-5 * (1 - 1e-9))
    assert data[limited] == pytest.approx(-1e-5, rel=1e-6)  # clamped at Icomp
    assert vr[limited] < -truth.bv_v  # only beyond the soft breakdown voltage
    assert all(v > 1e90 for v in data[limited + 1:])  # dummy data after the abort


def test_resistor_100k_is_recoverable(make_sim) -> None:
    sim = make_sim(load_scenario("resistor_100k"))  # committed scenario, with noise
    vs = linspace(-0.1, 0.1, 21)
    current = sweep(sim, "CN 3", "MM 2,3", channel=3, start=-0.1, stop=0.1, points=21)
    slope, offset = linear_fit(vs, current)
    assert 1 / slope == pytest.approx(1.0e5, rel=0.005)
    assert abs(offset) < 1e-9


# -- FeFET -----------------------------------------------------------------------------------------------------------


def fefet(state_file: Path | None = None, *, noisy: bool = True) -> SimTransport:
    scenario = load_scenario("fefet_basic")
    transport = SimTransport(scenario if noisy else noiseless(scenario), state_file=state_file)
    transport.open()
    return transport


def dual_sweep(sim: SimTransport, lo: float = -4.0, hi: float = 4.0, points: int = 161
               ) -> tuple[list[float], list[float], list[float]]:
    """Gate double sweep ``lo → hi → lo`` at Vd = 50 mV; forward and reverse drain currents on the same Vg grid."""
    data = sweep(sim, "CN 3,4", f"DV 3,0,{VD},1E-3", "MM 2,3", channel=4, start=lo, stop=hi, points=points,
                 icomp=1e-4, mode=3)
    return linspace(lo, hi, points), data[:points], data[points:][::-1]


def test_fefet_loop_width_matches_the_model_truth() -> None:
    sim = fefet()
    device = sim.instrument.circuit.devices["dut"]
    assert isinstance(device, FefetDevice) and isinstance(device, StatefulDevice)
    truth = device.loop_truth(-4.0, 4.0)  # computed before the sweep, from the initial state
    assert truth["memory_window"] == pytest.approx(0.995, abs=0.005) and truth["p_fwd"] < -0.99 < 0.99 < truth["p_rev"]
    vg, fwd, rev = dual_sweep(sim)
    offset = (device.params.slope_factor - 1) * VD / 2  # EKV linear region: extrapolation sits (n-1)Vd/2 higher
    vth_f, vth_r = maxgm_vth(vg, fwd, VD), maxgm_vth(vg, rev, VD)
    assert vth_f == pytest.approx(truth["vth_fwd"] + offset, abs=0.02)
    assert vth_r == pytest.approx(truth["vth_rev"] + offset, abs=0.02)
    assert vth_f - vth_r == pytest.approx(truth["memory_window"], rel=0.03)
    cc_f, cc_r = cc_vth(vg, fwd, 1e-7), cc_vth(vg, rev, 1e-7)  # constant-current method: same window
    assert cc_f - cc_r == pytest.approx(truth["memory_window"], rel=0.03)
    # the loop leaves the device on the descending branch at -4 V
    assert device.p == pytest.approx(device.p_down(-4.0)) and sim.instrument.state.devices == {"dut": {"p": device.p}}


def test_fefet_partial_loop_truth_follows_the_sweep_range() -> None:
    sim = fefet(noisy=False)
    device = sim.instrument.circuit.devices["dut"]
    assert isinstance(device, FefetDevice)
    truth = device.loop_truth(-3.2, 3.2)  # not saturated: a smaller window
    assert 0.5 < truth["memory_window"] < 0.9
    vg, fwd, rev = dual_sweep(sim, -3.2, 3.2, 129)
    assert cc_vth(vg, fwd, 1e-7) - cc_vth(vg, rev, 1e-7) == pytest.approx(truth["memory_window"], rel=0.03)


def test_fefet_polarization_persists_across_two_transports(tmp_path: Path) -> None:
    """Process A programs the FeFET and saves the state; process B (a new SimTransport on the same state file)
    reads the low-Vth state; a transport without the file starts erased."""
    path = sim_state_file(tmp_path, "fefet_basic")
    writer = fefet(path, noisy=False)
    device = writer.instrument.circuit.devices["dut"]
    assert isinstance(device, FefetDevice) and device.p == -1.0
    run(writer, "CN 3,4", "DV 4,0,4.5,1E-6")  # program pulse (DC) on the gate
    assert device.p == pytest.approx(device.p_up(4.5))
    run(writer, "DZ", "CL")  # 0 V retains the state
    assert device.p == pytest.approx(device.p_up(4.5))
    writer.save_state()
    stored = json.loads(path.read_text(encoding="utf-8"))["devices"]
    assert stored == {"dut": {"p": device.p}}

    reader = fefet(path, noisy=False)
    programmed = reader.instrument.circuit.devices["dut"]
    assert isinstance(programmed, FefetDevice) and programmed.p == device.p
    vg = linspace(-0.5, 1.5, 81)
    read = sweep(reader, "CN 3,4", f"DV 3,0,{VD},1E-3", "MM 2,3", channel=4, start=-0.5, stop=1.5, points=81,
                 icomp=1e-4)
    erased = fefet(None, noisy=False)
    fresh = sweep(erased, "CN 3,4", f"DV 3,0,{VD},1E-3", "MM 2,3", channel=4, start=-0.5, stop=1.5, points=81,
                  icomp=1e-4)
    shift = cc_vth(vg, fresh, 1e-7) - cc_vth(vg, read, 1e-7)
    assert shift == pytest.approx(programmed.vth_at(-1.0) - programmed.vth_at(programmed.p), abs=0.01)
    assert shift == pytest.approx(0.99, abs=0.02)  # a full memory window between the two states

    run(reader, "DV 4,0,-4.5,1E-6", "DZ", "CL")  # erase
    reader.save_state()
    writer.load_state()  # under the lock, process A reloads before its next transaction
    assert writer.instrument.circuit.devices["dut"].p == pytest.approx(programmed.p_down(-4.5))  # type: ignore[attr-defined]


def test_fefet_state_rolls_back_when_a_sweep_is_aborted() -> None:
    sim = fefet(noisy=False)
    device = sim.instrument.circuit.devices["dut"]
    assert isinstance(device, FefetDevice)
    run(sim, "CN 3,4", f"DV 3,0,{VD},1E-3", "MM 2,3", "WT 0,0.01")
    before = device.p
    assert before == pytest.approx(device.p_up(0.0)) and before > -1.0  # 0 V on the gate (CN) clamps P_init
    run(sim, "WV 4,1,0,0,4.5,46,1E-4", "XE")
    sim.write("AB")  # no virtual time has passed: no step completed, so the program sweep never happened
    assert device.p == before and sim.instrument.state.devices["dut"]["p"] == before
    run(sim, "XE")
    sim.read()  # the measurement completes: every step acted on the device
    assert device.p == pytest.approx(device.p_up(4.5))


def test_fefet_corrupt_device_state_is_a_transport_error(tmp_path: Path) -> None:
    path = sim_state_file(tmp_path, "fefet_basic")
    sim = fefet(path)
    sim.save_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["devices"]["dut"]["p"] = 3.0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TransportError, match=r"\[-1, 1\]"):
        fefet(path)


def test_fefet_hysteresis_band_and_p_channel() -> None:
    params = FefetParams(vth0=0.6, k_v=0.5, vc_v=2.0, delta_v=0.2)
    device = FefetDevice("f", params)
    assert device.polarization_after(0.0, 0.3) == 0.3  # inside the band: retained
    assert device.polarization_after(3.0, -1.0) == pytest.approx(math.tanh(5.0))
    assert device.polarization_after(-3.0, 1.0) == pytest.approx(math.tanh(-5.0))
    trial = device.terminal_currents({"gate": 3.0, "drain": 0.1, "source": 0.0, "bulk": 0.0})
    assert device.p == -1.0  # a trial evaluation never changes the state
    assert trial["drain"] == pytest.approx(MosfetEkv("m", params).channel_current(
        3.0, 0.1, vth=device.vth_at(device.polarization_after(3.0))) - 0.5 * params.gate_leak_s * 2.9)
    device.commit({"gate": 3.0, "drain": 0.1, "source": None})  # floating source: no drive, no change
    assert device.p == -1.0
    pfet = FefetDevice("p", FefetParams(polarity="p", vth0=-0.6, k_v=0.5, vc_v=2.0, delta_v=0.2, p_init=1.0))
    assert pfet.vth == pytest.approx(-1.1)  # positive P makes a p-channel threshold more negative
    pfet.commit({"gate": -3.0, "drain": -0.1, "source": 0.0})
    assert pfet.vth == pytest.approx(-0.6 + 0.5 * math.tanh(5.0))
    with pytest.raises(ValueError, match="exactly 'p'"):
        device.import_state({"p": 0.0, "q": 1})


# -- damaged variants ------------------------------------------------------------------------------------------------


def damaged(damage: str, **extra: float) -> DamagedMosfet:
    base = load_scenario("nmos_basic").models["dut"].params
    return DamagedMosfet("m", MosfetDamagedParams.model_validate({**base, "damage": damage, **extra}))


def test_gate_drain_short_mirrors_the_gate_current_into_the_drain() -> None:
    device = damaged("gate_drain_short", short_r_ohm=1000.0)
    healthy = MosfetEkv("h", MosfetEkvParams.model_validate(load_scenario("nmos_basic").models["dut"].params))
    v = {"gate": 1.0, "drain": 0.05, "source": 0.0, "bulk": 0.0}
    out, ref = device.terminal_currents(v), healthy.terminal_currents(v)
    assert out["gate"] - ref["gate"] == pytest.approx(0.95e-3)
    assert out["drain"] - ref["drain"] == pytest.approx(-0.95e-3)
    assert out["source"] == pytest.approx(ref["source"]) and sum(out.values()) == pytest.approx(0.0, abs=1e-15)


def test_gd_short_scenario_hits_the_gate_compliance_at_the_first_step(make_sim) -> None:
    sim = make_sim(load_scenario("gd_short"))
    data = sweep(sim, "CN 3,4", f"DV 3,0,{VD},1E-3", "WM 2,1", "MM 2,4,3", channel=4, start=-1.0, stop=3.0,
                 points=41, icomp=1e-6)
    gate, drain = data[0::2], data[1::2]
    assert gate[0] == pytest.approx(-1e-6, rel=0.01)  # clamped at the gate compliance (out of the gate)
    assert drain[0] == pytest.approx(1e-6, rel=0.05)  # the same current enters the drain through the short
    applied = sim.instrument.solve({4: -1.0, 3: VD}, {4: 1e-6, 3: 1e-3})
    assert applied[2] == {4} and applied[0][4] == pytest.approx(VD - 1e-6 * 1000.0, abs=1e-6)  # gate pulled to Vd
    assert all(v > 1e90 for v in gate[1:])  # automatic abort: dummy data after the compliance step


def test_open_drain_scenario_measures_only_the_noise_floor(make_sim) -> None:
    scenario = load_scenario("open_drain_noisy")
    sim = make_sim(scenario)
    data = sweep(sim, "CN 3,4", f"DV 3,0,{VD},1E-3", "AIT 0,2,1", "MM 2,4,3", channel=4, start=-1.0, stop=3.0,
                 points=101, icomp=1e-6)  # 1 PLC: noise multiplier 1
    drain = data[1::2]
    sigma = scenario.noise.floor_a["HRSMU"]
    mean = sum(drain) / len(drain)
    std = math.sqrt(sum((d - mean) ** 2 for d in drain) / (len(drain) - 1))
    assert std == pytest.approx(sigma, rel=0.3) and abs(mean) < 4 * sigma / math.sqrt(len(drain))
    assert max(abs(d) for d in drain) < 5 * sigma  # nothing but noise: no transfer curve
    healthy = make_sim(noiseless(load_scenario("nmos_basic")))
    reference = sweep(healthy, "CN 3,4", f"DV 3,0,{VD},1E-3", "MM 2,3", channel=4, start=-1.0, stop=3.0,
                      points=101, icomp=1e-6)
    assert reference[-1] > 1e-5  # the same device with the drain landed
    # the gate-source half of the gate leakage remains (below the raised HRSMU noise floor here)
    device = damaged("open_drain")
    assert device.terminal_currents({"gate": 2.0, "drain": 0.05, "source": 0.0, "bulk": 0.0}) == {
        "gate": pytest.approx(1e-12), "drain": 0.0, "source": pytest.approx(-1e-12), "bulk": 0.0}


def test_leaky_gate_adds_conductance_and_keeps_the_channel() -> None:
    device = damaged("leaky_gate", leak_s=2e-7)
    healthy = MosfetEkv("h", MosfetEkvParams.model_validate(load_scenario("nmos_basic").models["dut"].params))
    v = {"gate": 2.0, "drain": 1.0, "source": 0.0, "bulk": 0.0}
    out, ref = device.terminal_currents(v), healthy.terminal_currents(v)
    assert out["gate"] - ref["gate"] == pytest.approx(1e-7 * 2.0 + 1e-7 * 1.0)
    assert out["drain"] + out["source"] == pytest.approx(-out["gate"])
    assert out["drain"] - ref["drain"] == pytest.approx(-1e-7 * 1.0)  # the channel current itself is unchanged


def test_damaged_and_stateless_scenarios_store_no_device_state() -> None:
    for name in ("nmos_basic", "gd_short", "open_drain_noisy", "diode_basic", "resistor_100k"):
        circuit = Circuit(load_scenario(name))
        assert not circuit.has_state and circuit.export_state() == {}
    assert Circuit(load_scenario("fefet_basic")).export_state() == {"dut": {"p": -1.0}}


def test_two_fefets_keep_separate_states() -> None:
    params = {"vth0": 0.6, "k_v": 0.5, "vc_v": 2.0, "delta_v": 0.2}
    scenario: SimScenario = scenario_with(
        {"a": {"model": "fefet", "params": params}, "b": {"model": "fefet", "params": params}},
        {"a": {"gate": 1, "drain": 3, "source": "GNDU"}, "b": {"gate": 2, "drain": 4, "source": "GNDU"}})
    sim = SimTransport(scenario, state_file=None)
    sim.open()
    run(sim, "CN 1,2", "DV 1,0,3,1E-6")
    b = sim.instrument.circuit.devices["b"]
    assert isinstance(b, FefetDevice)
    assert sim.instrument.state.devices == {"a": {"p": pytest.approx(math.tanh(5.0))},
                                            "b": {"p": pytest.approx(b.polarization_after(0.0, -1.0))}}


# -- committed scenarios ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("scenario", "pin_map"), [
    ("diode_basic", "diode-2t"), ("resistor_100k", "resistor-2t"), ("fefet_basic", "mosfet-4t"),
    ("open_drain_noisy", "mosfet-4t"), ("gd_short", "mosfet-4t"),
])
def test_scenario_wiring_matches_the_example_pin_map(scenario: str, pin_map: str) -> None:
    """The example pin maps are ``certainty: verified`` because they match these simulated wirings."""
    pins = yaml.safe_load((PINMAP_DIR / f"{pin_map}.example.yaml").read_text(encoding="utf-8"))
    assert pins["certainty"] == "verified"
    assert load_scenario(scenario).wiring["dut"] == pins["terminals"]
