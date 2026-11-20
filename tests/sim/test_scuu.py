"""SCUU in the simulator (``units/switch.py`` + ``CmuEngine._route_sides``; blueprint v2 4.1, 4.2 "Switches: SCUU
(SSP resets SMU)"; WP8.1): the ``SSP`` paths and their side effects on the SMUs (PG p520 (4-202), ATV-27), the
routing of the DUT terminals on the SCUU outputs to the MFCMU, the SMUs or nothing, ``CN``/``*RST``/``*LRN?``
behaviour and the scenario validation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import errx_all, load_scenario, noiseless, run

LAB_SLOTS = [{"slot": 1, "model": "B1525A"}, {"slot": 2, "model": "B1530A"}, {"slot": 3, "model": "B1517A"},
             {"slot": 4, "model": "B1517A"}, {"slot": 5, "model": "B1511B"}, {"slot": 6, "model": "B1511B"},
             {"slot": 7, "model": "B1520A"}]
"""The lab mainframe: MPSMUs in slots 5 and 6 feed an SCUU on the MFCMU in slot 7 (Force1 = slot 6, Force2 = 5)."""


def scuu_scenario(models: dict[str, Any] | None = None, wiring: dict[str, Any] | None = None,
                  **extra: Any) -> SimScenario:
    data: dict[str, Any] = {
        "name": "scuu_test", "idn": "Keysight Technologies,B1500A,0,A.06.01.2024.0101", "slots": LAB_SLOTS,
        "scuu": [7], "noise": {"floor_a": {}, "rel": 0.0, "seed": 1},
        "models": models if models is not None else {"r": {"model": "resistor", "params": {"r_ohm": 1e6}}},
        "wiring": wiring if wiring is not None else {"r": {"a": "7H", "b": "7L"}},
    }
    data.update(extra)
    return SimScenario.model_validate(data)


@pytest.fixture
def sim(make_sim: Callable[..., SimTransport]) -> SimTransport:
    return make_sim(scuu_scenario())


def test_power_on_outputs_are_open(sim: SimTransport) -> None:
    assert sim.query("*LRN? 81") == "SSP7,0" and sim.query("*LRN? 80") == "SSL7,1"
    assert not any(state.output_on for state in sim.instrument.outputs().values())


def test_ssp_to_the_smus_switches_them_on(sim: SimTransport) -> None:
    run(sim, "SSP 7,3")
    outputs = sim.instrument.outputs()
    assert outputs[6].output_on and outputs[5].output_on and not outputs[7].output_on
    assert (outputs[6].voltage, outputs[6].icomp) == (0.0, 1e-4)
    assert sim.query("*LRN? 81") == "SSP7,3"


def test_ssp_resets_smu_output(sim: SimTransport) -> None:
    """ATV-27 per the manual text (PG p520 (4-202)): from SMU to MFCMU the SMU goes to 0 V, 100 V range, 20 mA
    compliance; back from MFCMU to SMU it goes to 0 V, 20 V range, 100 uA, output switch on."""
    run(sim, "SSP 7,3", "DV 6,0,1.5,1E-3", "DV 5,0,-0.5,1E-3")
    run(sim, "SSP 7,4")
    outputs = sim.instrument.outputs()
    for smu in (6, 5):
        assert (outputs[smu].voltage, outputs[smu].vrange, outputs[smu].icomp) == (0.0, 14, 0.02)
    assert outputs[7].output_on
    run(sim, "DV 6,0,0.7,1E-3", "SSP 7,1")  # output 1 back to SMU 6, output 2 open
    outputs = sim.instrument.outputs()
    assert (outputs[6].output_on, outputs[6].voltage, outputs[6].vrange, outputs[6].icomp) == (True, 0.0, 12, 1e-4)
    assert outputs[5].icomp == 0.02  # output 2 went from MFCMU to open: no reset stated, the SMU keeps its setting


def test_routing_follows_the_path(sim: SimTransport) -> None:
    """A 1 MOhm resistor between the SCUU outputs: SMU 6 and SMU 5 see it on path 3, the MFCMU on path 4, the SMU
    alone sees an open on paths 1/2."""
    run(sim, "SSP 7,3", "DV 6,0,1,1E-3", "DV 5,0,0,1E-3", "MM 1,6,5", "XE")
    i6, i5 = (float(e[3:]) for e in sim.read().split(","))
    assert (i6, i5) == pytest.approx((1e-6, -1e-6))
    run(sim, "SSP 7,1", "DV 6,0,1,1E-3", "MM 1,6", "XE")
    assert float(sim.read()[3:]) == pytest.approx(0.0, abs=1e-15)  # output 2 open: no return path
    run(sim, "SSP 7,4", "ACV 7,0.03", "FC 7,1E5", "MM 17,7", "XE")
    _, g = sim.read().split(",")
    assert float(g[3:]) == pytest.approx(1e-6, rel=1e-6)  # G = 1/R
    run(sim, "SSP 7,3", "MM 17,7", "XE")
    _, g = sim.read().split(",")
    assert float(g[3:]) == pytest.approx(0.0, abs=1e-12)  # the MFCMU sees the SCUU open


def test_cn_of_scuu_modules_is_error_323(sim: SimTransport) -> None:
    for command in ("CN 6", "CN 7", "CN 3,5"):
        sim.write(command)
    assert errx_all(sim) == [323, 323, 323]
    assert not sim.instrument.outputs()[3].output_on  # nothing of the refused line ran


def test_bare_cn_connects_the_mfcmu_path(sim: SimTransport) -> None:
    run(sim, "CN")
    outputs = sim.instrument.outputs()
    assert outputs[3].output_on and outputs[4].output_on and outputs[7].output_on
    assert not outputs[5].output_on and not outputs[6].output_on
    assert sim.query("*LRN? 81") == "SSP7,4"


def test_rst_opens_the_scuu_and_enables_the_indicator(sim: SimTransport) -> None:
    run(sim, "SSP 7,4", "SSL 7,0")
    assert sim.query("*LRN? 80") == "SSL7,0"
    run(sim, "*RST")
    assert sim.query("*LRN? 81") == "SSP7,0" and sim.query("*LRN? 80") == "SSL7,1"


def test_ssp_errors(make_sim: Callable[..., SimTransport], sim: SimTransport) -> None:
    for command in ("SSP 6,4", "SSP 7,5", "SSL 7,2"):
        sim.write(command)
    assert errx_all(sim) == [671, 120, 120]
    lab = make_sim(noiseless(load_scenario("lab_station")))  # no SCUU declared
    lab.write("SSP 7,4")
    assert errx_all(lab) == [671] and lab.query("*LRN? 81") == ""


def test_cmu_dc_bias_through_the_scuu_reaches_stateful_devices(make_sim: Callable[..., SimTransport]) -> None:
    sim = make_sim(scuu_scenario({"c": {"model": "capacitor", "params": {"c_f": 1e-10}}}, {"c": {"a": "7H",
                                                                                             "b": "7L"}}))
    run(sim, "SSP 7,4", "DCV 7,2")
    assert sim.instrument.state.devices["c"]["v"] == 2.0
    run(sim, "SSP 7,3", "DV 6,0,1,1E-3")
    assert sim.instrument.state.devices["c"]["v"] == 1.0  # now SMU 6 drives output 1 (SMU 5 at 0 V)


@pytest.mark.parametrize(("change", "match"), [
    ({"scuu": [6]}, "needs an MFCMU"),
    ({"scuu": [7], "slots": [{"slot": 6, "model": "B1511B"}, {"slot": 7, "model": "B1520A"}]}, "needs an MFCMU"),
    ({"wiring": {"r": {"a": 6, "b": "7L"}}}, "feeds the SCUU"),
    ({"scuu": [], "wiring": {"r": {"a": "4H", "b": "7L"}}}, "holds no MFCMU"),
])
def test_scenario_validation(change: dict[str, Any], match: str) -> None:
    data = {**scuu_scenario().model_dump(mode="json"), **change}
    with pytest.raises(ValidationError, match=match):
        SimScenario.model_validate(data)
