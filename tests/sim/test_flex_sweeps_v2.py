"""Simulator FLEX of WP7.2 (blueprint v2 4.1): current sources ``DI`` (PG PDF 391-392) and ``WI`` (551-552), the
synchronous sources ``WSV``/``WSI`` (560-563) and the multi-channel sweep ``MM 16`` with ``WNX``/``WNCC`` (556-559,
PDF 102-103), their errors (220, 223, 224, PDF 578-579; 212 for ``DI``), the ``LOP?`` codes of current sources
(Table 4-26, PDF 446: 02/03 forcing, 11 voltage compliance) and the post-sweep levels of every sweep source.

The test mainframe (``tests/sim/helpers.NMOS_SLOTS``) has MPSMUs in slots 1-2 and HRSMUs in 3-4;
``resistor_scenario`` puts a resistor between SMU1 (``a``) and SMU3 (``b``)."""

from __future__ import annotations

import pytest

from b1500_test_agent.models.sim import ComplianceAt, IgnoreDz
from tests.sim.helpers import FIXTURE_DIR, elements, errx_all, resistor_scenario, run, scenario_with, values
from tests.unit.flex_fixtures import load_fixture

R = 1000.0


def resistor_to_gndu(r_ohm: float = R):
    """A resistor from SMU1 to the GNDU."""
    return scenario_with({"r": {"model": "resistor", "params": {"r_ohm": r_ohm}}}, {"r": {"a": 1, "b": "GNDU"}})


# -- DI --------------------------------------------------------------------------------------------------------------


def test_di_forces_a_current_and_the_voltage_follows(make_sim) -> None:
    sim = make_sim(resistor_to_gndu())
    run(sim, "CN 1", "DI 1,0,1E-3,5", "CMM 1,2", "MM 1,1", "XE")
    assert values(sim.read()) == pytest.approx([1.0])  # V = I R
    state = sim.instrument.outputs()[1]
    assert (state.mode, state.current, state.vcomp, state.voltage) == ("I", 1e-3, 5.0, 0.0)
    assert sim.query("LOP?").startswith("LOP02,")
    run(sim, "DI 1,0,-2E-3,5")
    assert sim.query("LOP?").startswith("LOP03,")
    run(sim, "CMM 1,1", "XE")
    assert values(sim.read()) == pytest.approx([-2e-3])  # the current reading of a current source


def test_di_at_the_voltage_compliance_clamps_and_reports_c(make_sim) -> None:
    sim = make_sim(resistor_to_gndu())
    run(sim, "CN 1", "DI 1,0,1E-2,5", "MM 1,1", "XE")  # 10 mA into 1 kOhm needs 10 V
    [element] = elements(sim.read())
    assert element.startswith("CAV") and float(element[3:]) == pytest.approx(5.0)  # compliance side: V
    assert sim.query("LOP?").startswith("LOP11,")


def test_di_compliance_default_is_the_previous_vcomp(make_sim) -> None:
    sim = make_sim(resistor_to_gndu())
    run(sim, "CN 1", "DI 1,0,1E-4,2", "DI 1,0,5E-4", "MM 1,1", "XE")
    assert values(sim.read()) == pytest.approx([0.5]) and sim.instrument.outputs()[1].vcomp == 2.0


@pytest.mark.parametrize(("command", "code"), [
    ("DI 1,0,1E-3", 212),  # no Vcomp set yet
    ("DI 1,0,1E-3,0", 212),
    ("DI 1,0,5E-2,50", 212),  # Table 4-6: 40 V maximum at 50 mA
    ("DI 1,0,0.12,10", 212),  # above 100 mA
    ("DI 1,7,1E-3,5", 124),  # not a current output range of the MPSMU
    ("DI 1,0,1E-3,5,2", 120),
    ("DI 1,0,1E-3,50", 202),  # Vcomp above 42 V with the interlock open
])
def test_di_errors(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    run(sim, "CN 1")
    sim.write(command)
    assert errx_all(sim) == [code]
    assert sim.instrument.outputs()[1].mode == "V"


def test_di_needs_the_output_switch_on(make_sim) -> None:
    sim = make_sim()
    sim.write("DI 1,0,1E-3,5")
    assert errx_all(sim) == [200]


def test_dz_and_cl_end_a_current_source(make_sim) -> None:
    sim = make_sim(resistor_to_gndu())
    run(sim, "CN 1", "DI 1,0,1E-3,5")
    assert "channel 1: forcing 0.001 A" in sim.instrument.unsafe_reasons()
    run(sim, "DZ")
    state = sim.instrument.outputs()[1]
    assert (state.mode, state.voltage, state.current) == ("V", 0.0, 0.0) and state.output_on
    assert sim.query("LOP?").startswith("LOP01,")
    run(sim, "DI 1,0,1E-3,5", "CL")
    sim.instrument.assert_safe()


def test_ignore_dz_keeps_the_current_source_and_stays_unsafe(make_sim) -> None:
    sim = make_sim(resistor_to_gndu(), faults=[IgnoreDz()])
    run(sim, "CN 1", "DI 1,0,1E-3,5", "DZ")
    assert sim.instrument.outputs()[1].mode == "I"
    assert any("forcing" in reason for reason in sim.instrument.unsafe_reasons())


def test_current_forcing_into_a_diode_reads_its_forward_voltage(make_sim) -> None:
    diode = {"model": "diode", "params": {"is_a": 1e-14, "n": 1.0, "rs_ohm": 10.0}}
    sim = make_sim(scenario_with({"d": diode}, {"d": {"anode": 3, "cathode": "GNDU"}}))
    run(sim, "CN 3", "DI 3,0,1E-3,2", "MM 1,3", "XE")
    [vf] = values(sim.read())
    device = sim.instrument.circuit.devices["d"]
    assert device.current(vf) == pytest.approx(1e-3, rel=1e-4)  # the solved voltage carries the forced current


# -- WI --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("wi", "currents"), [
    ("WI 1,1,0,0,1E-3,5,5", [0, 0.25e-3, 0.5e-3, 0.75e-3, 1e-3]),
    ("WI 1,2,0,1E-6,1E-4,3,5", [1e-6, 1e-5, 1e-4]),
    ("WI 1,3,0,0,1E-3,3,5", [0, 0.5e-3, 1e-3, 1e-3, 0.5e-3, 0]),
    ("WI 1,4,0,-1E-6,-1E-4,3,5", [-1e-6, -1e-5, -1e-4, -1e-4, -1e-5, -1e-6]),
])
def test_wi_sweep_modes(make_sim, wi: str, currents: list[float]) -> None:
    """``WI`` modes 1-4: the source data (type I) shows the forced currents, the measured voltage is I R."""
    sim = make_sim(resistor_to_gndu())
    run(sim, "FMT 1,1", "CN 1", "MM 2,1", "CMM 1,2", wi, "XE")
    data = elements(sim.read())
    assert {e[1:3] for e in data[1::2]} == {"AI"} and data[-1][0] == "E"
    assert values(",".join(data[1::2])) == pytest.approx(currents)
    assert values(",".join(data[0::2])) == pytest.approx([i * R for i in currents])


def test_wi_block_matches_the_golden_fixture(make_sim) -> None:
    """``tests/fixtures/flex/fmt1_current_sweep_source.txt`` (shared with the driver parser tests) is exactly what
    the simulator formats for its command line."""
    fixture = load_fixture(FIXTURE_DIR / "flex" / "fmt1_current_sweep_source.txt")
    sim = make_sim(scenario_with({"r": {"model": "resistor", "params": {"r_ohm": 1e4}}}, {"r": {"a": 3, "b": "GNDU"}}))
    run(sim, "CN 3", *(c.strip() for c in fixture.command.split(";")))
    assert sim.read() == fixture.body


def test_wi_reaches_the_voltage_compliance_and_aborts(make_sim) -> None:
    sim = make_sim(resistor_to_gndu())
    run(sim, "FMT 1,1", "CN 1", "MM 2,1", "WI 1,2,0,1E-4,1E-2,3,5", "XE")  # 10 mA needs 10 V
    data = elements(sim.read())
    assert [e[:3] for e in data[0::2]] == ["NAV", "NAV", "CAV"]  # CMM 0: a current source measures V
    assert float(data[4][3:]) == pytest.approx(5.0)
    assert sim.instrument.outputs()[1].current == 1e-4  # aborted: back to the start value (PDF 553)


@pytest.mark.parametrize(("command", "code"), [
    ("WI 1,5,0,0,1E-3,5,5", 120), ("WI 1,1,7,0,1E-3,5,5", 124), ("WI 1,2,0,0,1E-3,5,5", 130),
    ("WI 1,1,0,0,1E-3,5,0", 223), ("WI 1,1,0,0,0.05,5,50", 223), ("WI 1,1,0,0,1E-3,5,5,0.1", 100),
    ("WI 1,1,0,0,0.2,5,5", 120), ("WI 1,1,0,0,1E-3,5", 223), ("WI 1,1,0,0,1E-3,5,45", 202),
])  # fmt: skip
def test_wi_errors(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == [code]


# -- WSV / WSI -------------------------------------------------------------------------------------------------------


def test_wsv_steps_with_the_primary(make_sim) -> None:
    """``WSV`` on SMU3 (the resistor's other end) from 0 to -1 V while SMU1 sweeps 0 to 1 V: 2 V across at the end."""
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,1", "CN 1,3", "MM 2,1", "CMM 1,1", "WV 1,1,0,0,1,3,1E-2", "WSV 3,0,0,-1,1E-2", "XE")
    data = elements(sim.read())
    assert values(",".join(data[0::2])) == pytest.approx([0, 1e-3, 2e-3])
    assert values(",".join(data[1::2])) == pytest.approx([0, 0.5, 1.0])  # the primary's source data only
    assert sim.instrument.outputs()[3].voltage == 0.0  # post 1: every source back to its start value
    run(sim, "WM 1,2", "WV 1,1,0,0,1,3,1E-2", "WSV 3,0,0,-1,1E-2", "XE")
    sim.read()
    assert (sim.instrument.outputs()[1].voltage, sim.instrument.outputs()[3].voltage) == (1.0, -1.0)


def test_wsi_steps_with_a_current_primary(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,1", "CN 1,3", "MM 2,1,3", "CMM 1,2", "CMM 3,2", "WI 1,2,0,1E-5,1E-3,3,5",
        "WSI 3,0,-1E-5,-1E-3,5", "XE")
    data = elements(sim.read())
    va, vb = values(",".join(data[0::3])), values(",".join(data[1::3]))
    # SMU1 pushes I into the resistor and SMU3 sinks it (the floating pair's common mode is arbitrary): I R across
    assert [a - b for a, b in zip(va, vb, strict=True)] == pytest.approx([0.01, 0.1, 1.0])
    assert values(",".join(data[2::3])) == pytest.approx([1e-5, 1e-4, 1e-3])  # the primary's source data


@pytest.mark.parametrize(("setup", "code"), [
    (("WI 1,1,0,0,1E-3,3,5", "WSV 3,0,0,1,1E-3"), 224),  # sync output mode differs from the primary
    (("WV 1,1,0,0,1,3,1E-3", "WSV 1,0,0,1,1E-3"), 224),  # sync on the primary channel
])
def test_sync_source_errors_at_xe(make_sim, setup: tuple[str, ...], code: int) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "CN 1,3", "MM 2,1", *setup)
    sim.write("XE")
    assert errx_all(sim) == [code] and not sim.instrument.measurement_pending


@pytest.mark.parametrize(("command", "code"), [
    ("WSV 3,0,0,1,1E-3", 220),  # no primary sweep yet
    ("WSI 3,0,0,1E-3,5", 220),
])
def test_a_sync_source_needs_a_primary(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == [code]


def test_wv_clears_the_sync_source_and_log_needs_one_polarity(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "CN 1,3", "MM 2,1", "WV 1,1,0,0,1,3,1E-2", "WSV 3,0,0,-1,1E-2", "WV 1,1,0,0,1,3,1E-2", "XE")
    sim.read()
    assert sim.instrument.outputs()[3].voltage == 0.0  # WV cleared WSV: SMU3 stayed at its DC level
    run(sim, "WV 1,2,0,0.1,1,3,1E-2")
    sim.write("WSV 3,0,0.1,-1,1E-2")
    assert errx_all(sim) == [130]


# -- MM 16 / WNX -----------------------------------------------------------------------------------------------------


def test_mm16_runs_the_primary_and_every_wnx_source(make_sim) -> None:
    """Voltage primary on SMU1, a current WNX source on SMU3 (resistor between them): mixed output modes."""
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,1", "CN 1,3", "MM 16,1,3", "CMM 1,1", "CMM 3,2", "WV 1,1,0,0,1,3,1E-2",
        "WNX 2,3,2,0,0,-1E-4,10", "XE")
    data = elements(sim.read())
    i1, v3 = values(",".join(data[0::3])), values(",".join(data[1::3]))
    assert i1 == pytest.approx([0, 5e-5, 1e-4])  # SMU3 sinks the programmed current from SMU1
    assert v3 == pytest.approx([0, 0.5 - 0.05, 1.0 - 0.1])
    state = sim.instrument.outputs()[3]
    assert (state.mode, state.current) == ("I", 0.0)  # post 1: the WNX source at its start value


def test_mm16_with_the_primary_alone_is_a_staircase(make_sim) -> None:
    sim = make_sim(resistor_to_gndu())
    run(sim, "FMT 1,1", "CN 1", "MM 16,1", "WV 1,1,0,0,1,3,1E-2", "XE")
    assert values(",".join(elements(sim.read())[0::2])) == pytest.approx([0, 5e-4, 1e-3])


def test_wnx_replaces_a_repeated_channel_and_wncc_clears(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "CN 1,3", "MM 16,1", "WV 1,1,0,0,1,3,1E-2", "WNX 2,3,1,0,0,-1,1E-2", "WNX 3,3,1,0,0,1,1E-2")
    assert {n: s.stop for n, s in sim.instrument._wnx.items()} == {3: 1.0}  # same channel: the last one wins
    run(sim, "WNCC", "XE")
    sim.read()
    assert sim.instrument._wnx == {} and sim.instrument.outputs()[3].voltage == 0.0
    run(sim, "WNX 2,3,1,0,0,-1,1E-2", "WV 1,1,0,0,1,3,1E-2")
    assert sim.instrument._wnx == {}  # WV clears WNX (PDF 557)


@pytest.mark.parametrize(("setup", "command", "code"), [
    (("CN 1,3", "MM 16,1", "WNX 2,3,1,0,0,1,1E-3"), "XE", 220),  # WNX without WV/WI (MM 28 takes it, WP7.3)
    (("WV 1,1,0,0,1,3,1E-3",), "WNX 11,3,1,0,0,1,1E-3", 120),
    (("WV 1,1,0,0,1,3,1E-3",), "WNX 2,3,3,0,0,1,1E-3", 120),
    (("WV 1,1,0,0,1,3,1E-3",), "WNX 2,3,1,0,0,1,0", 223),
    (("WV 1,2,0,0.1,1,3,1E-3",), "WNX 2,3,1,0,0,1,1E-3", 130),  # log primary: the source must avoid 0
    (("CN 1,3", "MM 16,1", "WV 1,1,0,0,1,3,1E-3", "WNX 1,3,1,0,0,1,1E-3"), "XE", 120),  # N = 1 is MM 28's
])
def test_wnx_errors(make_sim, setup: tuple[str, ...], command: str, code: int) -> None:
    sim = make_sim()
    run(sim, *setup)
    sim.write(command)
    assert errx_all(sim) == [code]


def test_mm16_refuses_a_wnx_source_on_the_primary_and_mm2_ignores_wnx(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "CN 1,3", "MM 16,1", "WV 1,1,0,0,1,3,1E-2", "WNX 2,1,1,0,0,1,1E-2")
    sim.write("XE")
    assert errx_all(sim) == [224]
    run(sim, "DV 3,0,0,1E-2", "WV 1,1,0,0,1,3,1E-2", "WNX 2,3,1,0,0,-1,1E-2", "MM 2,1", "XE")
    assert values(sim.read()) == pytest.approx([0, 5e-4, 1e-3])  # MM 2: SMU3 not swept, stays at 0 V


def test_ab_returns_every_sweep_source_to_its_start(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "FMT 1,1", "CN 1,3", "WT 0,1.0", "MM 16,1", "WV 1,1,0,0.2,1,5,1E-2", "WNX 2,3,1,0,-0.2,-1,1E-2",
        "XE")
    sim.instrument.clock += 2.5
    run(sim, "AB")
    assert (sim.instrument.outputs()[1].voltage, sim.instrument.outputs()[3].voltage) == (0.2, -0.2)


def test_compliance_fault_on_a_current_source_reads_its_vcomp(make_sim) -> None:
    sim = make_sim(resistor_to_gndu(), faults=[ComplianceAt(step=1, ch=1)])
    run(sim, "FMT 1,1", "WM 1,1", "CN 1", "MM 2,1", "WI 1,1,0,0,1E-4,3,2", "XE")
    data = elements(sim.read())
    assert [e[:3] for e in data[0::2]] == ["NAV", "CAV", "NAV"] and float(data[2][3:]) == pytest.approx(2.0)


def test_source_commands_are_marked_for_the_safety_spy(make_sim) -> None:
    sim = make_sim(resistor_scenario(R))
    run(sim, "CN 1,3", "DI 3,0,1E-6,1", "WV 1,1,0,0,1,3,1E-3", "WSV 3,0,0,1,1E-3", "WNX 2,3,1,0,0,1,1E-3")
    marked = {r.mnemonic for r in sim.instrument.command_log if r.source}
    assert marked == {"DI", "WV", "WSV", "WNX"}
