"""The simulator's quasi-static C-V unit (``transport/sim/units/qscv.py``, WP8.5; blueprint v2 4.1, 4.2 ``moscap``):
the ``QS*`` commands per the Programming Guide (PDF 493-500; errors 240-247), the QSCV engine against the device truth
(a linear capacitor, the MOS-C's quasi-static ``dQ/dV``), leakage compensation in both modes, the joined transitions,
the double sweep, the automatic abort, the ``QSZ`` offset measurement and cancel, ``*LRN? 49``, the post value, the SCUU
path of ``moscap_dit`` and the GNDU accounting of the circuit."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from b1500_test_agent.models.sim import MoscapParams
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.devices.circuit import GNDU_MAX_A
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from b1500_test_agent.transport.sim.units.qscv import QSCV_STRAY_F
from tests.sim.helpers import errx_all, load_scenario, noiseless, run, scenario_with

pytestmark = pytest.mark.cmu

C100 = 100e-12
SETUP = ("FMT 1,1", "CN 3", "MM 13,3", "QSC 0", "QSO 0", "QSL 1,1", "QSM 2,1", "QSR -11",
         "QST 0.1,0.1,0,0,0")


def capacitor(make_sim: Callable[..., SimTransport], *, g_s: float = 0.0) -> SimTransport:
    """A 100 pF capacitor (optionally with a parallel conductance) between HRSMU 3 and the GNDU."""
    scenario = scenario_with({"c": {"model": "capacitor", "params": {"c_f": C100, "g_s": g_s}}},
                             {"c": {"a": 3, "b": "GNDU"}})
    return make_sim(scenario)


def blocks(sim: SimTransport, width: int = 3) -> list[list[str]]:
    data = sim.read(timeout_s=600).split(",")
    return [data[k:k + width] for k in range(0, len(data), width)]


def value(element: str) -> float:
    return float(element[3:])


def test_a_capacitor_reads_its_capacitance_plus_the_path_offset(make_sim: Callable[..., SimTransport]) -> None:
    sim = capacitor(make_sim)
    run(sim, *SETUP, "QSV 3,1,0,0,1,0.1,9,1E-06", "QSZ 0", "XE")
    got = blocks(sim)
    assert len(got) == 9 and [b[2][:3] for b in got] == ["WCV"] * 8 + ["ECV"]
    assert [value(b[2]) for b in got] == pytest.approx([0.1 * k for k in range(1, 10)])
    for leak, cap, _ in got:
        assert leak[:3] == "NCI" and value(leak) == pytest.approx(0.0, abs=1e-15)
        assert cap[:3] == "NCC" and value(cap) == pytest.approx(C100 + QSCV_STRAY_F, rel=1e-6)
    assert sim.instrument.state.channels[3].voltage == 0.0  # QSM post 1: back to start


def test_leakage_compensation_removes_a_parallel_conductance(make_sim: Callable[..., SimTransport]) -> None:
    g = 1e-9  # 1 nS: 1 nA at 1 V against 10 pA of charge current
    for operation in ("0", "1"):
        sim = capacitor(make_sim, g_s=g)
        run(sim, *[c if c != "QSC 0" else f"QSC {operation}" for c in SETUP if c != "QSO 0" or operation == "0"],
            "QSR -12", "QSV 3,1,0,0,1,0.1,9,1E-06", "XE")
        for leak, cap, src in blocks(sim):
            assert value(cap) == pytest.approx(C100 + QSCV_STRAY_F, rel=1e-6)
            assert value(leak) == pytest.approx(g * value(src), rel=1e-6)  # the leakage at the step voltage
    sim = capacitor(make_sim, g_s=g)
    run(sim, *SETUP, "QSL 1,0", "QSR -12", "QSV 3,1,0,0,1,0.1,9,1E-06", "XE")
    for _, cap, src in blocks(sim):  # without compensation the leakage charge reads as capacitance
        expected = C100 + QSCV_STRAY_F + g * value(src) * 0.1 / 0.1
        assert value(cap) == pytest.approx(expected, rel=1e-6)


def test_joined_and_separate_transitions_take_their_time(make_sim: Callable[..., SimTransport]) -> None:
    sim = capacitor(make_sim)
    run(sim, *SETUP, "QST 0.1,0.1,2,0,0", "QSV 3,1,0,0,1,0.1,9,1E-06")
    start = sim.instrument.clock
    sim.write("XE")
    blocks(sim)
    assert sim.instrument.clock - start == pytest.approx(2.0 + 0.3 + 8 * 0.2, abs=1e-6)
    sim = capacitor(make_sim)
    run(sim, *SETUP, "QST 0.1,0.1,0,0.05,0.02", "QSV 3,1,0,0,1,0.05,9,1E-06")  # cvoltage < step: apart
    start = sim.instrument.clock
    sim.write("XE")
    got = blocks(sim)
    assert sim.instrument.clock - start == pytest.approx(9 * (0.05 + 0.1 + 0.1 + 0.1 + 0.02), abs=1e-6)
    assert value(got[0][1]) == pytest.approx(C100 + QSCV_STRAY_F, rel=1e-6)


def test_double_sweep_and_one_point(make_sim: Callable[..., SimTransport]) -> None:
    sim = capacitor(make_sim)
    run(sim, *SETUP, "QSM 2,2", "QSV 3,3,0,0,1,0.1,9,1E-06", "XE")
    got = blocks(sim)
    assert len(got) == 18 and value(got[8][2]) == pytest.approx(0.9) and value(got[9][2]) == pytest.approx(0.9)
    assert value(got[-1][2]) == pytest.approx(0.1) and all(value(b[1]) > 0 for b in got)  # same sign both ways
    assert sim.instrument.state.channels[3].voltage == pytest.approx(1.0)  # QSM post 2: stop
    sim = capacitor(make_sim)
    run(sim, *SETUP, "QSR -12", "QSV 3,1,0,0,2,0.1,1,1E-06", "XE")  # step 1, span <= 10 V: one point, cvoltage ignored
    ((_, cap, src),) = blocks(sim)
    assert value(src) == pytest.approx(1.0) and value(cap) == pytest.approx(C100 + QSCV_STRAY_F, rel=1e-6)


def test_the_quasi_static_moscap_curve_is_dq_dv(make_sim: Callable[..., SimTransport]) -> None:
    scenario = noiseless(load_scenario("moscap_dit"))
    sim = make_sim(scenario)
    run(sim, "FMT 1,1", "SSP 7,3", "DV 5,0,0,1E-06", "MM 13,6", "QSL 1,1", "QSM 2,1", "QSR -12",
        "QST 0.1,0.1,5,0,0", "QSV 6,1,0,2,-2.5,0.05,89,1E-06", "QSZ 0", "XE")
    got = blocks(sim)
    device = MoscapDevice("t", MoscapParams(**scenario.models["dut"].params))
    v = np.array([value(b[2]) for b in got])
    c = np.array([value(b[1]) for b in got]) - QSCV_STRAY_F
    truth = np.array([(device.charge(x + 0.025) - device.charge(x - 0.025)) / 0.05 for x in v])
    depletion = (v > -0.8) & (v < 0.1)  # no minority-carrier lag here
    assert np.allclose(c[depletion], truth[depletion], rtol=2e-3)
    accumulation = v < -1.5
    assert np.allclose(c[accumulation], truth[accumulation], rtol=2e-3)
    assert {b[1][:3] for b in got} == {"NFC"}  # the MFCMU sides routed to SMU6 (gate) through the SCUU


def test_the_automatic_abort_stops_with_dummy_data_and_error_242(make_sim: Callable[..., SimTransport]) -> None:
    sim = capacitor(make_sim, g_s=1e-8)  # 10 nA at 1 V: over the 1 nA range halfway
    run(sim, *SETUP, "QSV 3,1,0,0,1,0.1,9,1E-06")
    sim.write("XE")
    got = blocks(sim)
    statuses = [b[1][0] for b in got]
    first = statuses.index("V")
    assert all(s == "N" for s in statuses[:first]) and all(s == "V" for s in statuses[first:])
    assert value(got[-1][1]) == pytest.approx(199.999e99)
    assert errx_all(sim) == [242] and sim.instrument.state.channels[3].voltage == 0.0  # start value after an abort


def test_offset_measurement_and_cancel(make_sim: Callable[..., SimTransport]) -> None:
    sim = capacitor(make_sim)
    run(sim, *SETUP, "QSV 3,1,0,0,1,0.1,9,1E-06", "QSZ 2")
    offset = sim.read(timeout_s=5)
    assert offset.startswith("NCC") and value(offset) == pytest.approx(QSCV_STRAY_F, rel=1e-6)
    assert sim.instrument.state.qscv_offsets == {3: pytest.approx(QSCV_STRAY_F, rel=1e-6)}
    run(sim, "QSZ 1", "XE")
    assert all(value(b[1]) == pytest.approx(C100, rel=1e-6) for b in blocks(sim))
    run(sim, "*RST")  # power-on state: no stored offset (simulator convention)
    assert sim.instrument.state.qscv_offsets == {}


@pytest.mark.parametrize(("commands", "code"), [
    (("CN 3", "MM 13,3", "XE"), 240),  # no QSV
    (("QSR -8",), 241),
    (("CN 3", "MM 1,3", "QSZ 0"), 243),  # QSZ needs MM 13 first
    (("CN 3", "QSV 3,2,0,0,1,0.1,9,1E-06"), 246),
    (("CN 3", "CN 4", "MM 13,3", "QSO 1,4", "QSV 3,1,0,0,1,0.1,9,1E-06", "XE"), 100),  # smart operation not simulated
    (("CN 3", "MM 13,3", "QSO 1,3", "QSV 3,1,0,0,1,0.1,9,1E-06", "XE"), 247),  # dedicated = measurement channel
    (("CN 1", "MM 13,1", "QSR -10", "QSV 1,1,0,0,1,0.1,9,1E-06", "XE"), 124),  # 100 pA: not on an MPSMU
    (("MM 13,3", "QSV 3,1,0,0,1,0.1,9,1E-06", "XE"), 200),  # output switch off
    (("CN 3", "QSV 3,1,0,0,1,0.00001,9,1E-06"), 120),  # cvoltage below twice the resolution
    (("CN 3", "QST 0.001,0.1,0,0,0"), 120),
    (("MM 13,3,4",), 122),
])
def test_setup_errors(make_sim: Callable[..., SimTransport], commands: tuple[str, ...], code: int) -> None:
    sim = capacitor(make_sim)
    for command in commands:
        sim.write(command)
    assert code in errx_all(sim)


def test_lrn_49_reports_the_setup(make_sim: Callable[..., SimTransport]) -> None:
    sim = capacitor(make_sim)
    run(sim, *SETUP, "QST 0.35,0.1,5,0.2,0.2", "QSV 3,1,0,0,1,0.1,9,1E-06")
    answer = sim.query("*LRN? 49")
    assert answer.startswith("QSM2,1;QSL1,1;QSZ0;QSO0;QSC0;QST0.36,0.1,5,0.2,0.2;QSR-11;QSV3,1,0,0,1,0.1,9,1e-06")


def test_gndu_accounting_follows_the_applied_states(make_sim: Callable[..., SimTransport]) -> None:
    scenario = scenario_with({"r": {"model": "resistor", "params": {"r_ohm": 1000.0}}}, {"r": {"a": 3, "b": "GNDU"}})
    sim = make_sim(scenario)
    assert sim.instrument.gndu_peak_a == 0.0
    run(sim, "CN 3", "DV 3,0,2,0.01")
    assert sim.instrument.gndu_peak_a == pytest.approx(2e-3, rel=1e-9)  # 2 V into 1 kOhm, back through the GNDU
    run(sim, "DV 3,0,1,0.01")
    assert sim.instrument.gndu_peak_a == pytest.approx(2e-3, rel=1e-9)  # the peak stays
    run(sim, "DV 3,0,5,0.001")  # compliance-limited: 1 mA, not the 5 mA a trial step evaluates
    assert sim.instrument.gndu_peak_a == pytest.approx(2e-3, rel=1e-9) and sim.instrument.gndu_peak_a < GNDU_MAX_A
    sim.instrument.sync_gndu()
    assert sim.instrument.state.gndu_peak_a == pytest.approx(2e-3, rel=1e-9)
