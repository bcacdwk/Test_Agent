"""Simulator SMU search unit (``transport/sim/units/search.py``, WP7.5; Programming Guide Ed. 15 physical PDF pages):
linear search MM 14 (p110-111), binary search MM 15 normal/cautious/repeat (p108-109, p370-372), the synchronous
search source (p132), the automatic abort and post values (p134, p370, p455), the quasi-pulsed spot MM 9 (p106-107:
detection at the compliance, ``S`` within 10 V of start, ``N`` at stop), the data ``Data_search,Data_sense`` (p47)
with status ``N``/``G``/``S`` (Table 1-10, p53), timing in virtual time and the errors 270-279, 610 (p581-584)."""

from __future__ import annotations

import pytest

from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import elements, errx_all, resistor_scenario, run, values

R = 1000.0


@pytest.fixture
def sim(make_sim) -> SimTransport:
    """A 1 kOhm resistor between SMU1 (MPSMU, ``a``) and SMU3 (HRSMU, ``b`` at 0 V), both switched on."""
    transport = make_sim(resistor_scenario(R))
    run(transport, "FMT 1,0", "CN 1,3", "DV 3,0,0,0.1")
    return transport


def headers(text: str) -> list[str]:
    return [e[:3] for e in elements(text)]


# -- linear search (MM 14) ------------------------------------------------------------------------------------------


def test_linear_search_stops_at_the_first_step_reaching_the_target(sim: SimTransport) -> None:
    run(sim, "MM 14", "LSM 2,1", "LSVM 1", "LSTM 0.1,0.001", "LGI 1,1,0,5E-04", "LSV 1,0,0,1,0.1,0.01", "XE")
    data = sim.read()
    assert headers(data) == ["NAV", "NAI"]
    assert values(data) == pytest.approx([0.5, 0.5 / R])
    assert sim.instrument.outputs()[1].voltage == 0.0  # LSM post 1: the start value (PDF 455)
    per_point = 0.001 + sim.instrument.integration_time(1)
    assert sim.instrument.clock == pytest.approx(0.1 + 6 * per_point, rel=1e-6)  # hold + 6 measured steps


def test_linear_search_post_last_and_only_the_search_data(sim: SimTransport) -> None:
    run(sim, "MM 14", "LSM 2,3", "LSVM 0", "LSTM 0,0", "LGI 1,1,0,5E-04", "LSV 1,0,0,1,0.1,0.01", "XE")
    data = sim.read()
    assert headers(data) == ["NAV"] and values(data) == pytest.approx([0.5])
    assert sim.instrument.outputs()[1].voltage == pytest.approx(0.5)  # post 3: the value at the target


def test_linear_search_not_found_returns_the_last_value_with_g(sim: SimTransport) -> None:
    run(sim, "MM 14", "LSM 2,2", "LSVM 1", "LSTM 0,0", "LGI 1,1,0,5E-03", "LSV 1,0,0,1,0.25,0.01", "XE")
    data = sim.read()
    assert headers(data) == ["GAV", "NAI"] and values(data) == pytest.approx([1.0, 1.0 / R])
    assert sim.instrument.outputs()[1].voltage == pytest.approx(1.0)  # a normal end: post 2 (stop)


def test_a_negative_ramp_judges_below_the_target(sim: SimTransport) -> None:
    run(sim, "MM 14", "LSM 2,1", "LSVM 1", "LSTM 0,0", "LGI 1,0,0,-3E-04", "LSV 1,0,0,-1,-0.1,0.01", "XE")
    assert values(sim.read()) == pytest.approx([-0.3, -0.3 / R])


def test_another_channel_in_compliance_stops_the_search_with_s(make_sim) -> None:
    """SMU3 (0 V, Icomp 0.2 mA) limits at 0.2 V: the automatic abort stops the search (S, the monitor T); without
    the abort the target is never reached (G)."""
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,0", "CN 1,3", "DV 3,0,0,2E-04", "MM 14", "LSM 2,1", "LSVM 1", "LSTM 0,0", "LGI 1,1,0,5E-04",
        "LSV 1,0,0,1,0.1,0.01", "XE")
    data = sim.read()
    assert headers(data) == ["SAV", "TAI"] and values(data)[0] == pytest.approx(0.3)
    assert sim.instrument.outputs()[1].voltage == 0.0  # aborted: the start value (PDF 134)
    run(sim, "LSM 1,1", "XE")
    assert headers(sim.read()) == ["GAV", "TAI"]


# -- binary search (MM 15) ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("control", [0, 1])
def test_binary_search_converges_within_the_limit(sim: SimTransport, control: int) -> None:
    run(sim, "MM 15", f"BSM {control},2,1", "BSVM 1", "BST 0,0", "BGI 1,0,1E-06,0,3.7E-04", "BSV 1,0,0,2,0.01",
        "XE")
    data = sim.read()
    assert headers(data) == ["NAV", "NAI"]
    v, i = values(data)
    assert abs(i - 3.7e-4) <= 1e-6 and v == pytest.approx(0.37, abs=1e-3)


def test_binary_search_normal_control_checks_the_range_first(sim: SimTransport) -> None:
    run(sim, "MM 15", "BSM 0,2,1", "BSVM 1", "BST 0,0", "BGI 1,0,1E-06,0,3E-03", "BSV 1,0,0,2,0.01", "XE")
    data = sim.read()  # 3 mA lies beyond the 2 mA at the stop value: G after start and stop
    assert headers(data) == ["GAV", "NAI"] and values(data) == pytest.approx([2.0, 2.0 / R])
    per_point = sim.instrument.integration_time(1)
    assert sim.instrument.clock == pytest.approx(2 * per_point, rel=1e-6)


def test_binary_repeat_mode_returns_the_point_closest_to_the_target(sim: SimTransport) -> None:
    run(sim, "MM 15", "BSM 1,2,1", "BSVM 1", "BST 0,0", "BGI 1,1,3,0,6E-04", "BSV 1,0,0,1,0.01", "XE")
    data = sim.read()  # start 0, then 0.5, 0.75, 0.625: closest 0.625 V
    assert headers(data) == ["NAV", "NAI"] and values(data)[0] == pytest.approx(0.625)


def test_the_synchronous_source_follows_the_search(make_sim) -> None:
    """BSSV on SMU3 with polarity -1: the resistor sees twice the search voltage (PDF 132)."""
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,0", "CN 1,3", "MM 15", "BSM 1,2,3", "BSVM 1", "BST 0,0", "BGI 1,0,1E-06,0,4E-04",
        "BSV 1,0,0,1,0.01", "BSSV 3,0,0,0.01", "XE")
    v, i = values(sim.read())
    assert v == pytest.approx(0.2, abs=1e-3) and i == pytest.approx(4e-4, abs=1e-6)
    out = sim.instrument.outputs()
    assert out[1].voltage == pytest.approx(v, abs=1e-5) and out[3].voltage == pytest.approx(-v, abs=1e-5)  # post 3
    run(sim, "BSV 1,0,0,1,0.01")
    assert sim.instrument._bssx is None  # BSV clears BSSV (PDF 374)


# -- quasi-pulsed spot (MM 9) ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("r_ohm", "header", "reading"), [
    (15e3, "CAV", 15.0),  # 1 mA at 15 V: compliance after a 15 V change -> C, the detection voltage
    (5e3, "SAV", 5.0),  # 1 mA at 5 V: compliance within 10 V of start -> S (PDF 53)
    (1e5, "NAV", 20.0),  # 0.2 mA at 20 V: no detection before stop -> N at stop
])
def test_quasi_pulse_detects_the_compliance(make_sim, r_ohm: float, header: str, reading: float) -> None:
    sim = make_sim(resistor_scenario(r_ohm))
    run(sim, "FMT 1,0", "CN 1,3", "DV 3,0,0,0.1", "MM 9,1", "BDT 0.01,0", "BDM 0,0", "BDV 1,0,0,20,1E-03", "XE")
    data = sim.read()
    assert headers(data) == [header] and values(data) == pytest.approx([reading], abs=1e-6)
    assert sim.instrument.outputs()[1].voltage == 0.0  # back to the start value (PDF 107)
    expected = 0.01 + reading / 6.0e4 + sim.instrument.integration_time(1)
    assert sim.instrument.clock == pytest.approx(expected, rel=1e-6)


def test_quasi_pulse_current_mode_reads_the_compliance(make_sim) -> None:
    sim = make_sim(resistor_scenario(15e3))
    run(sim, "FMT 1,0", "CN 1,3", "DV 3,0,0,0.1", "MM 9", "BDT 0,0", "BDM 1,1", "BDV 1,0,0,20,1E-03", "XE")
    data = sim.read()
    assert headers(data) == ["CAI"] and values(data) == pytest.approx([1e-3])


# -- errors ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("commands", "code"), [
    (["MM 14", "LGI 1,1,0,1E-04", "XE"], 270),  # no search source
    (["MM 15", "BSV 1,0,0,1,0.01", "XE"], 271),  # no monitor
    (["MM 14", "LSSV 3,1,0,0.01"], 270),  # synchronous source before its search source
    (["MM 14", "LSV 1,0,0,1,0.1,0.01", "LSSI 3,1,0,1"], 273),  # other output mode
    (["MM 14", "LGI 1,1,0,0.02", "LSV 1,0,0,1,0.1,0.01", "XE"], 275),  # target above the 10 mA compliance
    (["MM 14", "LSV 1,0,1,1,0.1,0.01"], 276),
    (["MM 14", "LSV 1,0,0,1,1E-06,0.01"], 277),  # step below the 100 uV resolution of the 2 V range
    (["MM 15", "BGI 1,0,1E-06,0,1E-04", "BSV 1,0,0,1,0.01", "BSSV 1,1,0,0.01", "XE"], 278),
    (["MM 14", "LGV 1,1,0,0.5", "LSV 1,0,0,1,0.1,0.01", "XE"], 279),  # a voltage source monitors its current
    (["MM 9", "XE"], 610),
    (["MM 14,1"], 122),  # MM 14 takes no channel (PDF 470)
    (["BDV 1,0,0,9,1E-03"], 120),  # |start - stop| >= 10 V (PDF 365)
    (["BDV 1,0,0,50,1E-03"], 202),  # 50 V with the interlock open (42 V)
])
def test_search_errors(sim: SimTransport, commands: list[str], code: int) -> None:
    for command in commands:
        sim.write(command)
    assert errx_all(sim) == [code]


def test_ab_returns_the_search_sources_to_start(sim: SimTransport) -> None:
    run(sim, "MM 14", "LSM 2,3", "LSVM 1", "LSTM 5,0", "LGI 1,1,0,5E-04", "LSV 1,0,0.2,1,0.1,0.01")
    sim.write("XE")
    sim.instrument.advance(1.0)
    sim.write("AB")
    assert not sim.instrument.measurement_pending
    assert sim.instrument.outputs()[1].voltage == pytest.approx(0.2)  # aborted: the start value
