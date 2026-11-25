"""``fixture`` + ``capacitor`` device truth (blueprint 4.2, WP5.9): an uncorrected 100 pF reads +0.3 pF, open and
short corrections remove exactly their own parasitic (corrected ±0.1 %), the phase error stays until ADJ (or a load
correction), and the capacitor's own admittance, displacement current and state."""

from __future__ import annotations

import cmath
import math

import numpy as np
import pytest

from b1500_test_agent.models.sim import CapacitorParams, FixtureParams
from b1500_test_agent.transport.sim.devices.basic import CapacitorDevice
from b1500_test_agent.transport.sim.devices.fixture import FixtureDevice, compensate, cp_g

pytestmark = pytest.mark.cmu

FREQS = [1.0e3, 1.0e4, 1.0e5, 1.0e6, 5.0e6]  # MFCMU 1 kHz - 5 MHz


def setup() -> tuple[FixtureDevice, CapacitorDevice]:
    return FixtureDevice("fx", FixtureParams()), CapacitorDevice("c", CapacitorParams(c_f=100e-12))


def z_of(device: CapacitorDevice, f: float) -> complex:
    return 1.0 / device.admittance(0.0, f)


def test_uncorrected_100pf_reads_plus_0_3pf() -> None:
    fixture, cap = setup()
    for f in (1.0e3, 1.0e4, 1.0e5):
        cp, _ = cp_g(fixture.measured(z_of(cap, f), f, phase_adjusted=True), f)
        assert cp - 100e-12 == pytest.approx(0.3e-12, abs=0.005e-12)
    cp, _ = cp_g(fixture.measured(z_of(cap, 1.0e6), 1.0e6, phase_adjusted=True), 1.0e6)
    series_l = (2 * math.pi * 1.0e6) ** 2 * 50e-9 * 100.3e-12  # the 50 nH lead adds ω²LC at 1 MHz
    assert cp == pytest.approx(100.3e-12 * (1 + series_l), rel=1e-4)


@pytest.mark.parametrize("f", FREQS)
def test_open_short_corrections_recover_the_capacitor(f: float) -> None:
    fixture, cap = setup()
    z_meas = fixture.measured(z_of(cap, f), f, phase_adjusted=True)
    z_open = fixture.standard("open", f, phase_adjusted=True)
    z_short = fixture.standard("short", f, phase_adjusted=True)
    cp, g = cp_g(compensate(z_meas, z_open=z_open, z_short=z_short), f)
    assert cp == pytest.approx(100e-12, rel=1e-3)
    assert abs(g) < 1e-3 * 2 * math.pi * f * 100e-12  # dissipation below 1e-3
    assert compensate(z_meas, z_open=z_open, z_short=z_short) == pytest.approx(z_of(cap, f), rel=1e-9)


def test_each_correction_removes_only_its_own_parasitic() -> None:
    fixture, cap = setup()
    f = 1.0e5
    z_meas = fixture.measured(z_of(cap, f), f, phase_adjusted=True)
    z_open = fixture.standard("open", f, phase_adjusted=True)
    z_short = fixture.standard("short", f, phase_adjusted=True)
    open_only, _ = cp_g(compensate(z_meas, z_open=z_open), f)
    short_only, _ = cp_g(compensate(z_meas, z_short=z_short), f)
    assert open_only == pytest.approx(100e-12, rel=1e-4)  # at 100 kHz the short parasitic is negligible for C
    assert short_only - 100e-12 == pytest.approx(0.3e-12, abs=0.005e-12)  # open capacitance still there
    f = 5.0e6  # the lead inductance matters at 5 MHz: only the short correction removes it
    z_meas = fixture.measured(z_of(cap, f), f, phase_adjusted=True)
    z_open = fixture.standard("open", f, phase_adjusted=True)
    open_only, _ = cp_g(compensate(z_meas, z_open=z_open), f)
    lc = (2 * math.pi * f) ** 2 * 50e-9 * 100e-12
    assert open_only == pytest.approx(100e-12 / (1 - lc), rel=1e-4)  # +0.49 %: the series L remains


def test_phase_error_stays_until_adj_or_load_correction() -> None:
    fixture, cap = setup()
    f = 2.0e6
    phi = fixture.phase_error(f)
    assert phi == pytest.approx(math.radians(2.0))  # 1 deg/MHz default
    z_true = z_of(cap, f)
    raw = fixture.measured(z_true, f, phase_adjusted=False)
    z_open = fixture.standard("open", f, phase_adjusted=False)
    z_short = fixture.standard("short", f, phase_adjusted=False)
    corrected = compensate(raw, z_open=z_open, z_short=z_short)
    assert cmath.phase(corrected / z_true) == pytest.approx(phi, rel=1e-6)  # open/short keep the rotation
    _, g = cp_g(corrected, f)
    assert g / (2 * math.pi * f * 100e-12) == pytest.approx(math.sin(phi), rel=1e-3)  # a false dissipation
    adjusted = compensate(fixture.measured(z_true, f, phase_adjusted=True),
                          z_open=fixture.standard("open", f, phase_adjusted=True),
                          z_short=fixture.standard("short", f, phase_adjusted=True))
    assert adjusted == pytest.approx(z_true, rel=1e-9)
    load = CapacitorDevice("std", CapacitorParams(c_f=47e-12, g_s=1e-7))  # a known load standard fixes it as well
    z_load = z_of(load, f)
    with_load = compensate(raw, z_open=z_open, z_short=z_short,
                           load=(fixture.standard("load", f, phase_adjusted=False, z_load=z_load), z_load))
    assert with_load == pytest.approx(z_true, rel=1e-9)
    with pytest.raises(ValueError, match="load"):
        compensate(raw, load=(z_load, z_load))
    with pytest.raises(ValueError, match="z_load"):
        fixture.standard("load", f, phase_adjusted=True)


def test_fixture_dc_leakage_and_truth() -> None:
    fixture, _ = setup()
    assert fixture.terminal_currents({"high": 1.0, "low": 0.0}) == {"high": 1e-9, "low": -1e-9}
    assert fixture.terminal_currents({"high": 1.0, "low": None}) == {"high": 0.0, "low": 0.0}
    assert fixture.truth() == {"c_open_f": 0.3e-12, "r_open_ohm": 1e9, "r_short_ohm": 0.5, "l_short_h": 50e-9,
                               "phase_deg_per_mhz": 1.0}


def test_capacitor_admittance_displacement_and_state() -> None:
    cap = CapacitorDevice("c", CapacitorParams(c_f=1e-9, g_s=1e-6, esr_ohm=10.0))
    f = 1.0e5
    w = 2 * math.pi * f
    assert cap.admittance(0.0, f) == pytest.approx(1 / (10.0 + 1 / complex(1e-6, w * 1e-9)), rel=1e-12)
    assert cap.terminal_currents({"a": 1.0, "b": 0.0})["a"] == pytest.approx(1.0 / (10.0 + 1e6))
    ramp = np.linspace(0.0, 1.0, 101)
    charge = 0.0
    for v in ramp[1:]:
        charge += (cap.advance(1e-3, {"a": float(v), "b": 0.0})["a"] - cap._dc(float(v))) * 1e-3
    assert charge == pytest.approx(1e-9 * 1.0, rel=1e-12)  # ∫ displacement current = C·ΔV
    assert cap.export_state() == {"v": 1.0}
    other = CapacitorDevice("c2", CapacitorParams(c_f=1e-9))
    other.import_state({"v": 1.0})
    assert other.advance(1e-3, {"a": 1.0, "b": 0.0})["a"] == 0.0  # same voltage: no displacement
    other.import_state(None)
    assert other.v == 0.0
    with pytest.raises(ValueError, match="exactly"):
        other.import_state({"v": 1.0, "q": 2.0})
