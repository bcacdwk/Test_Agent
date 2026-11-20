"""Simulator additions of WP7.1 (blueprint v2 4.1, 4.2): the DC current source ``DI`` (solved voltage, voltage
compliance, ``CMM`` sides, ``LOP?`` codes, ``DZ``/``CL``), four-wire sensing of the ``resistor`` model (``lead_ohm``,
``kelvin``) and the ASU (``SAP``/``SAR``/``SAL``, ``*LRN? 62/63``, the 1 pA range, ``CN``/``CL``/``*RST`` resets,
persistence). Manual pages: DI PG p391-392 (4-73), LOP? p446 (4-128), SAP/SAR/SAL p505-506 (4-187), *LRN? p451."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.models.sim import ResistorParams
from b1500_test_agent.models.station import SimScenario, SimSlot
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import NMOS_SLOTS, errx_all, resistor_scenario, run, scenario_with, values


def kelvin_scenario(kelvin: str, *, r_ohm: float = 1.0, lead_ohm: float = 0.5, asu: bool = False) -> SimScenario:
    """A resistor from SMU3 (``a``) to the GNDU (``b``) with force-path resistance and the given Sense landing."""
    slots = [{**slot, "asu": asu and slot["slot"] == 3} for slot in NMOS_SLOTS]
    return scenario_with({"r": {"model": "resistor", "params": {"r_ohm": r_ohm, "lead_ohm": lead_ohm,
                                                                 "kelvin": kelvin}}},
                         {"r": {"a": 3, "b": "GNDU"}}, slots=slots)


def spot(sim: SimTransport, *setup: str) -> list[float]:
    run(sim, "FMT 1,0", *setup, "XE")
    return values(sim.read())


# -- DI ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("kelvin", "seen"), [("both", 1.0), ("a", 1.5), ("b", 1.5), ("none", 2.0)])
def test_current_source_measures_the_voltage_at_its_sense_point(make_sim, kelvin: str, seen: float) -> None:
    sim = make_sim(kelvin_scenario(kelvin))
    for current in (0.01, -0.005):
        [v] = spot(sim, "CN 3", f"DI 3,0,{current},1", "MM 1,3", "CMM 3,2")
        assert v == pytest.approx(current * seen, rel=1e-6)


def test_resistor_params_seen_resistance() -> None:
    assert ResistorParams(r_ohm=1.0, lead_ohm=0.5, kelvin="both").seen_ohm() == 1.0
    assert ResistorParams(r_ohm=1.0, lead_ohm=0.5).seen_ohm() == 2.0  # v1 default: two-wire, no lead
    assert ResistorParams(r_ohm=100.0).seen_ohm() == 100.0


def test_current_source_into_an_open_terminal_hits_its_voltage_compliance(make_sim) -> None:
    sim = make_sim(scenario_with({"o": {"model": "open", "params": {}}}, {"o": {"x": 3}}))
    run(sim, "FMT 1,0", "CN 3", "DI 3,0,-0.001,2", "MM 1,3", "CMM 3,2", "XE")
    text = sim.read()
    assert text.startswith("CC") and values(text) == [-2.0]  # status C, clamped at -Vcomp
    assert sim.query("LOP?") == "LOP00,00,11,00,00,00,00,00,00,00"  # voltage compliance (Table 4-26)


def test_zero_ampere_voltmeter_reads_the_node_voltage(make_sim) -> None:
    """SMU1 forces 1 V into a 1 kOhm resistor whose other end is a 0 A voltmeter on SMU3: no current, so the
    voltmeter reads 1 V."""
    sim = make_sim(resistor_scenario(1000.0))
    readings = spot(sim, "CN 1,3", "DV 1,0,1,1E-3", "DI 3,0,0,5", "MM 1,1,3", "CMM 1,1", "CMM 3,2")
    assert readings == pytest.approx([0.0, 1.0], abs=1e-9)


def test_cmm_sides_follow_the_source_type(make_sim) -> None:
    """CMM 0 = compliance side (V of a current source), CMM 3 = force side (its current) (PG p380 (4-62))."""
    sim = make_sim(kelvin_scenario("both"))
    [v] = spot(sim, "CN 3", "DI 3,0,0.002,1", "MM 1,3", "CMM 3,0")
    [i] = spot(sim, "CMM 3,3")
    assert v == pytest.approx(0.002) and i == pytest.approx(0.002)


@pytest.mark.parametrize(("command", "code"), [  # 0.2 A: no Vcomp is legal above 100 mA (Table 4-6) -> 212
    ("DI 3,0,0.001,0", 212), ("DI 3,0,0.2,1", 212), ("DI 3,0,0.03,50", 212), ("DI 3,7,0.001,1", 124),
    ("DI 3,8,0.001,1", 124), ("DI 3,0,0.001,1,2", 120),
])
def test_current_source_parameter_errors(make_sim, command: str, code: int) -> None:
    sim = make_sim(kelvin_scenario("both"))
    run(sim, "CN 3")
    sim.write(command)
    assert errx_all(sim) == [code]


def test_di_needs_the_output_on_and_dz_cl_end_the_current_source(make_sim) -> None:
    sim = make_sim(kelvin_scenario("both"))
    sim.write("DI 3,0,0.001,1")
    assert errx_all(sim) == [200]
    run(sim, "CN 3", "DI 3,0,0.005,1")
    assert sim.query("LOP?").split(",")[2] == "02"  # forcing positive current
    run(sim, "DI 3,0,-0.005,1")
    assert sim.query("LOP?").split(",")[2] == "03"
    run(sim, "DZ")
    state = sim.instrument.outputs()[3]
    assert (state.mode, state.current, state.voltage, state.output_on) == ("V", 0.0, 0.0, True)
    run(sim, "DI 3,0,0.005,1", "CL")
    sim.instrument.assert_safe()
    assert sim.instrument.outputs()[3].mode == "V"


def test_dv_after_di_forces_voltage_again(make_sim) -> None:
    sim = make_sim(kelvin_scenario("both", r_ohm=100.0, lead_ohm=0.0))
    run(sim, "CN 3", "DI 3,0,0.001,1", "DV 3,0,0.5,0.01")
    [i] = spot(sim, "MM 1,3", "CMM 3,1")
    assert i == pytest.approx(0.005)


# -- ASU -----------------------------------------------------------------------------------------------------------


def test_an_asu_can_only_sit_on_hrsmu_or_b1511b() -> None:
    assert SimSlot(slot=3, model="B1517A", asu=True).asu and SimSlot(slot=1, model="B1511B", asu=True).asu
    with pytest.raises(ValueError, match="ASU works only"):
        SimSlot(slot=1, model="B1511A", asu=True)
    with pytest.raises(ValueError, match="ASU works only"):
        SimSlot(slot=7, model="B1520A", asu=True)


def test_asu_adds_the_1_pa_range(make_sim) -> None:
    without = make_sim(kelvin_scenario("both"))
    without.write("RI 3,8")
    assert errx_all(without) == [124]  # 1 pA only with an ASU (Table 4-3)
    with_asu = make_sim(kelvin_scenario("both", asu=True))
    run(with_asu, "RI 3,8", "RI 3,-8", "CN 3", "DI 3,8,1E-12,1")
    assert with_asu.instrument.outputs()[3].irange == 8


def test_asu_commands_need_an_asu(make_sim) -> None:
    sim = make_sim(kelvin_scenario("both", asu=True))
    for command in ("SAP 4,1", "SAR 4,0", "SAL 4,0"):  # SMU4 has no ASU
        sim.write(command)
        assert errx_all(sim) == [151], command
    for command in ("SAP 3,2", "SAR 3,5", "SAL 3,9"):
        sim.write(command)
        assert errx_all(sim) == [120], command


def test_asu_state_reads_back_and_resets(make_sim) -> None:
    sim = make_sim(kelvin_scenario("both", asu=True))
    assert sim.query("*LRN? 62") == "SAP3,0" and sim.query("*LRN? 63") == "SAR3,1"  # initial settings
    run(sim, "SAP 3,1", "SAR 3,0", "SAL 3,0")
    assert sim.query("*LRN? 62") == "SAP3,1" and sim.query("*LRN? 63") == "SAR3,0"
    assert sim.instrument.state.asu_indicator == {3: False}
    run(sim, "CN 3")  # CN returns the output to the SMU side (PG p505 (4-187))
    assert sim.query("*LRN? 62") == "SAP3,0"
    run(sim, "SAP 3,1", "CL")
    assert sim.query("*LRN? 62") == "SAP3,0"
    run(sim, "SAP 3,1", "*RST")
    assert sim.query("*LRN? 62") == "SAP3,0" and sim.query("*LRN? 63") == "SAR3,1"
    assert sim.instrument.state.asu_indicator == {}


def test_no_asu_answers_an_empty_learn_string(make_sim) -> None:
    sim = make_sim(kelvin_scenario("both"))
    assert sim.query("*LRN? 62") == "" and sim.query("*LRN? 63") == ""


def test_the_aux_path_disconnects_the_smu_from_the_dut(make_sim) -> None:
    sim = make_sim(kelvin_scenario("both", r_ohm=100.0, lead_ohm=0.0, asu=True))
    run(sim, "CN 3", "DV 3,0,0.5,0.01", "FMT 1,0", "MM 1,3", "CMM 3,1")
    run(sim, "XE")
    assert values(sim.read()) == pytest.approx([0.005])
    run(sim, "SAP 3,1", "XE")
    assert values(sim.read()) == [0.0]  # the DUT side is on the AUX input now
    run(sim, "SAP 3,0", "XE")
    assert values(sim.read()) == pytest.approx([0.005])


def test_asu_state_survives_a_save_and_load(tmp_path: Path) -> None:
    scenario = kelvin_scenario("both", asu=True)
    path = tmp_path / "state.json"
    first = SimTransport(scenario, state_file=path)
    first.open()
    run(first, "SAP 3,1", "SAR 3,0")
    first.save_state()
    second = SimTransport(scenario, state_file=path)
    second.open()
    second.load_state()
    assert second.query("*LRN? 62") == "SAP3,1" and second.query("*LRN? 63") == "SAR3,0"
