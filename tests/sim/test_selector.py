"""Simulated 16440A selectors (blueprint v2 4.2 "Switches", 4.3 ``selector_stuck``; WP9.2): ``ERMOD``/``ERSSP``
state machine per PG p419-421, p433-434 and p154, the relay settle time, the cabling of ``SimScenario.selectors``
and the routed circuit: a pad on a selector output sees the SMU or SPGU channel its state connects, and floats
(noise floor) on the wrong path."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.routing import SELECTOR_SETTLE_S
from b1500_test_agent.models.sim import SelectorStuck
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from tests.sim.helpers import errx_all, load_scenario, noiseless, run
from tests.sim.selector_helpers import selector_states
from tests.sim.spgu_helpers import LAB_SLOTS

pytestmark = pytest.mark.spgu

IDN = "Agilent Technologies,B1500A,0,A.06.02.2023.0401"


def resistor_on_port0(r_ohm: float = 1e4, **cabling: int | None) -> SimScenario:
    """A resistor from selector output port 0 to the GNDU; port 0 cabled SMU3 / SPGU 101 unless ``cabling``."""
    port0 = {"smu": 3, "pgu": 101} if not cabling else cabling
    return SimScenario.model_validate({
        "name": "selector_test", "idn": IDN, "slots": LAB_SLOTS, "selectors": {0: port0},
        "wiring": {"r": {"a": "SELPORT0", "b": "GNDU"}},
        "models": {"r": {"model": "resistor", "params": {"r_ohm": r_ohm}}},
        "noise": {"floor_a": {}, "rel": 0.0, "seed": 1},
    })


def open_sim(scenario: SimScenario, state_file: Path | None = None) -> SimTransport:
    sim = SimTransport(scenario, state_file=state_file)
    sim.open()
    return sim


def smu3_current(sim: SimTransport, volts: float = 1.0) -> float:
    """``CN 3``, ``DV 3`` and one spot reading of SMU3's current."""
    run(sim, "CN 3", f"DV 3,0,{volts},1E-3", "FMT 1,0", "MM 1,3", "CMM 3,1")
    sim.write("XE")
    return float(sim.read()[3:])


# -- state machine ----------------------------------------------------------------------------------------------


def test_ermod_enables_and_disables_modes_and_reads_back_the_sum() -> None:
    sim = open_sim(resistor_on_port0())
    assert sim.query("ERMOD?") == "0"  # power-on: general purpose (PG p421 (4-103))
    run(sim, "ERMOD 1", "ERMOD 4", "ERMOD 8")
    assert sim.query("ERMOD?") == "13"
    run(sim, "ERMOD 4,0")
    assert sim.query("ERMOD?") == "9"
    run(sim, "ERMOD 0")  # general purpose: every mode off
    assert sim.query("ERMOD?") == "0"
    for bad in ("ERMOD 3", "ERMOD 1,2"):
        sim.write(bad)
    assert errx_all(sim) == [120, 120] and sim.query("ERMOD?") == "0"


def test_erssp_needs_the_control_mode_and_the_manual_domain() -> None:
    sim = open_sim(resistor_on_port0())
    sim.write("ERSSP 0,1")  # without ERMOD 1: refused (simulator convention; the driver always sends ERMOD 1 first)
    assert errx_all(sim) == [120] and sim.query("ERSSP? 0") == "0"
    run(sim, "ERMOD 1", "ERSSP 0,1", "ERSSP 1,2", "ERSSP 2,3")
    assert [sim.query(f"ERSSP? {p}") for p in range(4)] == ["1", "2", "3", "0"]
    for bad in ("ERSSP 1,3", "ERSSP 3,3", "ERSSP 4,0", "ERSSP 0,4"):  # PGU open only on CH 1; ports/states 0-3
        sim.write(bad)
    assert errx_all(sim) == [120, 120, 120, 120]
    assert selector_states(sim) == {0: 1, 1: 2, 2: 3, 3: 0}


def test_reset_and_device_clear_return_every_port_open_and_the_mode_off() -> None:
    sim = open_sim(resistor_on_port0())
    run(sim, "ERMOD 1", "ERSSP 0,2", "ERSSP 3,1")
    sim.write("*RST")
    assert sim.query("ERMOD?") == "0" and selector_states(sim) == {0: 0, 1: 0, 2: 0, 3: 0}
    run(sim, "ERMOD 1", "ERSSP 2,2")
    sim.device_clear()
    assert sim.query("ERMOD?") == "0" and selector_states(sim)[2] == 0


def test_the_state_persists_across_processes(tmp_path: Path) -> None:
    state = sim_state_file(tmp_path, "selector_test")
    first = open_sim(resistor_on_port0(), state)
    run(first, "ERMOD 1", "ERSSP 0,2")
    first.save_state()
    second = open_sim(resistor_on_port0(), state)
    assert second.query("ERMOD?") == "1" and second.query("ERSSP? 0") == "2"


def test_selector_stuck_holds_its_state_through_every_command() -> None:
    sim = open_sim(resistor_on_port0())
    sim.inject(SelectorStuck(port=0, state="pgu"))
    assert sim.query("ERSSP? 0") == "2"  # a human or an earlier run left it there; ERSSP? reports it
    run(sim, "ERMOD 1", "ERSSP 0,0", "ERSSP 1,1")
    assert sim.query("ERSSP? 0") == "2" and sim.query("ERSSP? 1") == "1"  # only port 0 is stuck
    sim.write("*RST")
    sim.device_clear()
    assert sim.query("ERSSP? 0") == "2" and sim.query("ERSSP? 1") == "0"
    with pytest.raises(ValidationError):
        SelectorStuck(port=1, state="pgu_open")


# -- routed circuit ---------------------------------------------------------------------------------------------


def test_an_smu_reaches_the_pad_only_through_its_selector_route_after_the_settle_time() -> None:
    sim = open_sim(resistor_on_port0(1e4))
    assert smu3_current(sim) == 0.0  # selector open: the pad floats, SMU3 sees nothing
    run(sim, "ERMOD 1", "ERSSP 0,1")
    sim.write("XE")
    assert float(sim.read()[3:]) == 0.0  # relays still switching (break before make)
    sim.wait(SELECTOR_SETTLE_S)
    sim.write("XE")
    assert float(sim.read()[3:]) == pytest.approx(1e-4)  # 1 V / 10 kOhm through SEL port 0
    for wrong in ("ERSSP 0,2", "ERSSP 0,3", "ERSSP 0,0"):  # PGU (output off), PGU open, open: the pad floats
        run(sim, wrong)
        sim.wait(SELECTOR_SETTLE_S)
        sim.write("XE")
        assert float(sim.read()[3:]) == 0.0, wrong


def test_the_wrong_path_reads_the_smu_noise_floor() -> None:
    scenario = resistor_on_port0(1e4).model_copy(update={"noise": load_scenario("lab_station").noise})
    sim = open_sim(scenario)
    floor = abs(smu3_current(sim))
    assert floor < 1e-11  # HRSMU floor 1e-13 A of the lab scenario, nowhere near 100 uA
    run(sim, "ERMOD 1", "ERSSP 0,1")
    sim.wait(SELECTOR_SETTLE_S)
    sim.write("XE")
    assert float(sim.read()[3:]) == pytest.approx(1e-4, rel=1e-2)


def test_an_uncabled_input_connects_nothing() -> None:
    sim = open_sim(resistor_on_port0(1e4, smu=None, pgu=101))
    run(sim, "ERMOD 1", "ERSSP 0,1")
    sim.wait(SELECTOR_SETTLE_S)
    assert smu3_current(sim) == 0.0


def test_the_spgu_level_reaches_the_pad_through_the_pgu_route() -> None:
    """SPGU 101 at 2 V with SER 50 Ohm into a 1 kOhm pad: open load (4 V) while the selector is open, the SER divider
    level (blueprint v2 4.2 SPGU row) once the PGU route connects the pad."""
    sim = open_sim(resistor_on_port0(1e3))
    run(sim, "CN 101", "SIM 0", "SPRM 1,10", "SPPER 1E-3", "SER 101,50", "SPM 101,1", "SPT 101,1,0,1E-4,2E-8,2E-8",
        "SPV 101,1,2,2", "SPUPD 101")
    floating = sim.instrument._spgu_levels()[1]  # type: ignore[attr-defined]
    run(sim, "ERMOD 1", "ERSSP 0,2")
    sim.wait(SELECTOR_SETTLE_S)
    routed = sim.instrument._spgu_levels()[1]  # type: ignore[attr-defined]
    assert floating == pytest.approx(4.0)  # 2 V x (50 + 50) / 50, nothing connected
    assert routed == pytest.approx(4.0 * 1e3 / (1e3 + 50.0))
    current = sim.instrument.circuit.channel_currents({1: routed})[1]
    assert current == pytest.approx(routed / 1e3)  # the pad's current counts as the SPGU channel's


def test_fefet_lab_programs_through_pgu_and_reads_through_smu() -> None:
    """The committed ``fefet_lab``: gate on SEL1.OUT1. A +4.5 V x 10 us SPGU train through the PGU path programs the
    FeFET (low Vth), the SMU path then reads it; the same train with the selector open, or started before the relay
    settled, leaves it erased."""
    def program(route: str, settle: float = SELECTOR_SETTLE_S) -> float:
        sim = open_sim(noiseless(load_scenario("fefet_lab")))
        run(sim, "ERMOD 1", route)
        sim.wait(settle)
        run(sim, "CN 101", "SIM 0", "SPRM 1,10", "SPPER 1E-4", "SER 101,1E6", "SPM 101,1",
            "SPT 101,1,0,1E-5,2E-8,2E-8", "SPV 101,1,0,4.5", "SPUPD 101", "SRP")
        sim.wait(2e-3)
        assert sim.query("SPST?") == "0"
        run(sim, "SPP", "CL", "ERSSP 0,1")
        sim.wait(SELECTOR_SETTLE_S)
        run(sim, "CN 3,4", "DV 3,0,0.8,1E-4", "DV 4,0,0.1,1E-3", "FMT 1,0", "MM 1,4", "CMM 4,1")
        sim.write("XE")
        return float(sim.read()[3:])

    programmed = program("ERSSP 0,2")
    untouched = program("ERSSP 0,0")
    too_early = program("ERSSP 0,2", settle=0.0)  # the 1 ms train ends inside the 10 ms relay settle time
    assert programmed > 10 * untouched > 0  # Vth fell by about the memory window: the pulses reached the gate
    assert too_early == pytest.approx(untouched)


def test_selector_targets_validate_against_the_cabling() -> None:
    base = resistor_on_port0().model_dump(mode="json")
    with pytest.raises(ValidationError, match="selectors lists no cabling"):
        SimScenario.model_validate({**base, "selectors": {1: {"smu": 3}}})
    with pytest.raises(ValidationError, match="not an SMU"):
        SimScenario.model_validate({**base, "selectors": {0: {"smu": 101}}})
    with pytest.raises(ValidationError, match="HV-SPGU"):
        SimScenario.model_validate({**base, "selectors": {0: {"pgu": 3}}})
    with pytest.raises(ValidationError, match="cabled to a 16440A selector input"):
        SimScenario.model_validate({**base, "wiring": {"r": {"a": "SELPORT0", "b": 3}}})
    with pytest.raises(ValidationError):
        SimScenario.model_validate({**base, "wiring": {"r": {"a": "SELPORT4", "b": "GNDU"}}})
