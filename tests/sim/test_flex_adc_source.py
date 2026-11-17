"""FLEX rows "ADC/range" (``AAD`` ``AIT`` ``AV`` ``RI`` ``RV``) and "Mode/source" (``MM 1|2`` ``CMM`` ``DV`` ``WV``
lin/log single/double, ``WT``, ``WM``, ``XE``) of blueprint 3, plus status-code generation."""

from __future__ import annotations

import statistics

import pytest

from b1500_test_agent.models.station import SimScenario
from tests.sim.helpers import errx_all, resistor_scenario, run, scenario_with, values

# -- ADC / range -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("commands", "seconds", "multiplier"),
    [
        ((), 1 / 50 / 128, 3.0),  # initial setting: high-speed ADC, auto, N=1 -> short
        (("AIT 0,2,1",), 1 / 50, 1.0),  # 1 PLC -> medium
        (("AV -10",), 10 / 50, 0.3),  # AV with a negative number = PLC mode -> long
        (("AV 64,1",), 64 / 50 / 128, 1.0),  # 64 samples = 0.5 PLC -> medium
        (("AAD 3,1", "AIT 1,1,100"), 100 * 80e-6, 1.0),  # high-resolution manual: N x 80 us
        (("AAD 3,1", "AIT 1,2,5"), 5 / 50, 0.3),
        (("AAD 3,2",), 1 / 50 / 128, 3.0),  # pulsed ADC is never used for DC: previous type stays
    ],
)
def test_integration_time_and_noise_multiplier(make_sim, commands: tuple[str, ...], seconds: float,
                                               multiplier: float) -> None:
    sim = make_sim()
    run(sim, *commands)
    assert sim.instrument.integration_time(3) == pytest.approx(seconds)
    assert sim.instrument.noise_multiplier(3) == multiplier


@pytest.mark.parametrize(
    ("command", "code"),
    [("AAD 3,3", 120), ("AAD 7,0", 151), ("AIT 1,3", 120), ("AIT 0,0,1024", 120), ("AIT 1,0,128", 120),
     ("AIT 2,0", 120), ("AV 0", 120), ("AV -101", 120), ("RI 1,9", 124), ("RI 3,9", None), ("RI 3,-20", 124),
     ("RV 3,3", 124), ("RV 3,-1000", None), ("AIT 0,3,0.01", None), ("AIT 0,3,0.03", 120)],
)  # fmt: skip
def test_adc_and_range_parameters_are_validated(make_sim, command: str, code: int | None) -> None:
    """MPSMU (slots 1-2) has no 10 pA range without the ASU; HRSMU (slots 3-4) does (Table 4-3, PDF 337)."""
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == ([] if code is None else [code])


def test_noise_scales_with_the_integration_setting(make_sim, nmos) -> None:
    """Open-circuit current noise: floor x multiplier (MPSMU floor 1e-11 A in ``nmos_basic``)."""
    def spread(*setup: str) -> float:
        sim = make_sim(nmos)
        run(sim, *setup, "CN 2", "MM 2,2", "WV 2,1,0,0,0.1,401,1E-3", "XE")
        return statistics.pstdev(values(sim.read(timeout_s=1e3)))  # 401 points x 10 PLC = 80 s (virtual)

    short, medium, long = spread(), spread("AV -1"), spread("AV -10")
    assert short == pytest.approx(3e-11, rel=0.15)
    assert medium == pytest.approx(1e-11, rel=0.15)
    assert long == pytest.approx(3e-12, rel=0.15)


def test_noise_is_deterministic_for_a_seed(make_sim, nmos) -> None:
    def sweep() -> str:
        sim = make_sim(nmos)
        run(sim, "CN 1,3", "DV 3,0,0.1,1E-2", "MM 2,3", "WV 1,1,0,0,1.5,31,1E-4", "XE")
        return sim.read()

    assert sweep() == sweep()


def test_fixed_range_overflow_reports_v_and_the_dummy_value(make_sim) -> None:
    """Fixed 1 uA range (``RI 3,-14``) with 1 mA flowing: status V, value 199.999E+99 (Table 1-10, PDF 53)."""
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "CN 1,3", "DV 3,0,0,1E-2", "RI 3,-14", "MM 2,3", "WV 1,1,0,0,1,3,1E-2", "XE")
    data = sim.read().split(",")
    assert data[0].startswith("NCI")  # 0 V: no current
    assert data[1] == data[2] == "VCI+199.999E+99"
    run(sim, "RI 3,14", "XE")  # limited auto ranging never overflows
    assert all(e.startswith("NCI") for e in sim.read().split(","))


# -- Mode / source ---------------------------------------------------------------------------------------------------


def test_mm1_spot_measures_each_channel_in_mm_order(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "CN 1,3", "DV 1,0,0.5,1E-2", "DV 3,0,-0.5,1E-2", "MM 1,3,1", "XE")
    data = sim.read().split(",")
    assert [e[:3] for e in data] == ["NCI", "NAI"]
    assert values(",".join(data)) == pytest.approx([-1e-3, 1e-3])


@pytest.mark.parametrize("mode", [3, 4, 5, 9, 10, 13, 14, 15, 16, 28])
def test_other_mm_modes_are_unsupported(make_sim, mode: int) -> None:
    sim = make_sim()
    sim.write(f"MM {mode},1")
    assert errx_all(sim) == [100]
    assert sim.instrument.commands(mnemonic="MM")[-1].outcome == "unsupported"


@pytest.mark.parametrize(("command", "code"), [("MM 0,1", 120), ("MM 1", 122), ("MM 2,1,1", 122), ("MM 1,7", 151),
                                               ("CMM 3,4", 120), ("CMM 3,5", 120)])
def test_mm_and_cmm_parameters_are_validated(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == [code]


def test_cmm_selects_current_or_voltage(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "CN 1,3", "DV 1,0,0.4,1E-2", "DV 3,0,0,1E-2", "CMM 1,2", "MM 1,1,3", "XE")
    data = sim.read().split(",")
    assert data[0][:3] == "NAV" and float(data[0][3:]) == pytest.approx(0.4)
    assert data[1][:3] == "NCI" and float(data[1][3:]) == pytest.approx(-0.4e-3)


@pytest.mark.parametrize(
    ("command", "code"),
    [("DV 1,0,1.0,1E-3", 200), ("DV 1,3,1.0,1E-3", 124), ("DV 1,0,101,1E-3", 120), ("DV 1,0,1.0,0", 212),
     ("DV 1,0,30,0.1", 212), ("DV 1,0,1.0,1E-3,2", 120), ("DV 1,0,1.0,1E-3,0,9", 124), ("DV 1,0,1.O,1E-3", 102),
     ("DV 1,0", 103), ("DV 7,0,1.0,1E-3", 151), ("DV 1,0,50,1E-3", 202)],
)  # fmt: skip
def test_dv_errors(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    if code != 200:
        run(sim, "CN 1,7")
    sim.write(command)
    assert errx_all(sim) == [code]


def test_dv_above_42_v_needs_a_closed_interlock(make_sim) -> None:
    """Interlock open: no output above 42 V (error 202, PG PDF 577; INTLKVTH 42 V, PDF 442)."""
    closed = scenario_with({"o": {"model": "open"}}, {"o": {"x": 1}}, interlock_closed=True)
    sim = make_sim(closed)
    run(sim, "CN 1", "DV 1,0,42,1E-3", "DV 1,0,50,1E-3")
    assert sim.instrument.outputs()[1].voltage == 50


@pytest.mark.parametrize(
    ("wv", "expected"),
    [
        ("WV 1,1,0,0,1,5,1E-3", [0, 0.25, 0.5, 0.75, 1.0]),
        ("WV 1,2,0,0.01,1,3,1E-3", [0.01, 0.1, 1.0]),
        ("WV 1,3,0,0,1,3,1E-3", [0, 0.5, 1.0, 1.0, 0.5, 0]),
        ("WV 1,4,0,-0.01,-1,3,1E-3", [-0.01, -0.1, -1.0, -1.0, -0.1, -0.01]),
        ("WV 1,1,0,0.3,0.3,1,1E-3", [0.3]),
    ],
)
def test_wv_sweep_modes(make_sim, wv: str, expected: list[float]) -> None:
    """Linear/log, single/double staircase (``WV`` mode 1-4, PG PDF 568-569); source data shows the steps."""
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "FMT 1,1", "CN 1,3", "DV 3,0,0,1E-2", "MM 2,3", wv, "XE")
    data = sim.read().split(",")
    assert [float(e[3:]) for e in data[1::2]] == pytest.approx(expected)
    assert [float(e[3:]) for e in data[0::2]] == pytest.approx([-v / 1000 for v in expected])


@pytest.mark.parametrize(
    ("command", "code"),
    [("WV 1,5,0,0,1,5,1E-3", 120), ("WV 1,1,3,0,1,5,1E-3", 124), ("WV 1,2,0,0,1,5,1E-3", 130),
     ("WV 1,2,0,-1,1,5,1E-3", 130), ("WV 1,1,0,0,1,10002,1E-3", 120), ("WV 1,1,0,0,1,5,0", 223),
     ("WV 1,1,0,0,30,5,0.1", 223), ("WV 1,1,0,0,1,5,1E-3,0.1", 100), ("WV 1,1,0,0,50,5,1E-3", 202),
     ("WV 1,1,0,0,101,5,1E-3", 120)],
)  # fmt: skip
def test_wv_errors(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == [code]


@pytest.mark.parametrize(("command", "code"), [("WT 656,0", 120), ("WT 0,0.1,2", 120), ("WT 0,0.1,0,0.2", 120),
                                               ("WT 0", 103), ("WM 3", 120), ("WM 1,3", 120)])
def test_wt_and_wm_errors(make_sim, command: str, code: int) -> None:
    sim = make_sim()
    sim.write(command)
    assert errx_all(sim) == [code]


def test_wt_sets_the_measurement_duration(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "CN 1,3", "DV 3,0,0,1E-2", "MM 2,3", "WV 1,1,0,0,1,10,1E-3", "WT 2,0.1,0.5", "XE")
    measurement = sim.instrument._measurement  # timing internals
    assert measurement is not None
    assert measurement.end - measurement.start == pytest.approx(2 + 10 * (0.1 + 0.5))


def test_wm_post_value_and_start_value(make_sim) -> None:
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "CN 1,3", "DV 3,0,0,1E-2", "MM 2,3", "WV 1,1,0,0.2,1,5,1E-2", "XE")
    sim.read()
    assert sim.instrument.outputs()[1].voltage == 0.2  # WM post 1 (initial): start value
    run(sim, "WM 1,2", "XE")
    sim.read()
    assert sim.instrument.outputs()[1].voltage == 1.0  # post 2: stop value


def test_wm_automatic_abort_returns_dummy_data_after_the_abort(make_sim) -> None:
    """``WM 2``: compliance stops the sweep; later points are ``V`` with 199.999E+99 (PG PDF 553)."""
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "WM 2,2", "CN 1,3", "DV 3,0,0,1E-2", "MM 2,1", "WV 1,1,0,0,1,5,0.6E-3", "XE")
    data = sim.read().split(",")
    assert [e[:3] for e in data] == ["NAI", "NAI", "NAI", "CAI", "VAI"]
    assert data[-1] == "VAI+199.999E+99"
    assert sim.instrument.outputs()[1].voltage == 0  # aborted: start value, not the post (stop) value


@pytest.mark.parametrize(("setup", "code"), [((), 214), (("MM 2,1",), 220), (("MM 1,1",), 200),
                                             (("CN 1", "MM 2,1,3", "WV 1,1,0,0,1,5,1E-3"), 200)])
def test_xe_preconditions(make_sim, setup: tuple[str, ...], code: int) -> None:
    sim = make_sim()
    for command in setup:
        sim.write(command)
    sim.write("XE")
    assert errx_all(sim) == [code]
    assert not sim.instrument.measurement_pending


# -- Status codes ----------------------------------------------------------------------------------------------------


def test_compliance_bisects_the_applied_voltage_c_on_that_channel_t_on_others(make_sim) -> None:
    """1 kOhm, Icomp 0.5 mA on the sweep source: above 0.5 V the source is limited (C) and SMU3 sees T."""
    sim = make_sim(resistor_scenario(1000.0))
    run(sim, "FMT 1,1", "CN 1,3", "DV 3,0,0,1E-2", "CMM 1,2", "MM 2,1,3", "WV 1,1,0,0,1,5,0.5E-3", "XE")
    data = sim.read().split(",")
    blocks = [data[i:i + 3] for i in range(0, len(data), 3)]
    assert [(b[0][0], b[1][0]) for b in blocks] == [("N", "N"), ("N", "N"), ("N", "N"), ("C", "T"), ("C", "T")]
    applied = [float(b[0][3:]) for b in blocks]
    current = [float(b[1][3:]) for b in blocks]
    assert applied[3:] == pytest.approx([0.5, 0.5], abs=1e-6)  # bisected so |I| = Icomp
    assert current[3:] == pytest.approx([-0.5e-3, -0.5e-3], rel=1e-5)
    assert [float(b[2][3:]) for b in blocks] == [0, 0.25, 0.5, 0.75, 1.0]  # source data = programmed value


def test_short_drives_compliance_at_any_voltage(make_sim) -> None:
    short = scenario_with({"s": {"model": "short"}}, {"s": {"a": 1, "b": "GNDU"}})
    sim = make_sim(short)
    run(sim, "CN 1", "MM 2,1", "WV 1,1,0,0,1,3,1E-3", "XE")
    data = sim.read().split(",")
    assert [e[0] for e in data] == ["N", "C", "C"]
    assert values(",".join(data))[1:] == pytest.approx([1e-3, 1e-3], rel=1e-6)


def test_open_device_measures_only_the_noise_floor(make_sim, nmos) -> None:
    probe_up = SimScenario.model_validate({**nmos.model_dump(), "models": {"dut": {"model": "open"}}})
    sim = make_sim(probe_up)
    run(sim, "CN 1,3", "DV 3,0,0.1,1E-3", "MM 2,3", "WV 1,1,0,0,2,21,1E-3", "XE")
    readings = values(sim.read())
    assert max(abs(r) for r in readings) < 2e-12  # HRSMU floor 1e-13 A x 3 (short integration)
    assert any(r != 0 for r in readings)


def test_status_severity_x_beats_compliance() -> None:
    from b1500_test_agent.transport.sim.format import worst_status

    assert worst_status(["N", "T", "C"]) == "C"
    assert worst_status(["C", "X"]) == "X" and worst_status(["V", "C"]) == "V" and worst_status([]) == "N"
