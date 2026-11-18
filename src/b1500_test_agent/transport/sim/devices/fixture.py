"""CMU measurement-path parasitics (``fixture``) and impedance compensation (blueprint 4.2 ``fixture`` + ``capacitor``).

The fixture sits between the CMU and the DUT: an open admittance ``Yo`` (stray capacitance ∥ insulation leakage)
across the DUT and a short impedance ``Zs`` (contact resistance + lead inductance) in series, so the CMU reads
``Zm = Zs + 1/(Yo + 1/Zdut)``, rotated by a cable phase error until phase compensation (``ADJ``) has run. The
instrument removes the parasitics only with the matching correction data (Keysight Impedance Measurement Handbook,
6th ed., section 4 "compensation"): open removes ``Yo``, short removes ``Zs``, load (with open and short) removes any
bilinear residual including the phase error.

Hooks for the CMU unit (WP8.1/8.2; the unit owns the correction state: which standards were acquired, with which
phase state, and whether each correction is on):

- ``measured(z_dut, f, phase_adjusted=...)``: the uncorrected reading of a DUT impedance (``None`` = nothing
  connected, the open standard);
- ``standard(kind, f, phase_adjusted=..., z_load=...)``: the reading while acquiring an open, short or load standard;
- ``compensate(z_meas, z_open=..., z_short=..., load=...)``: the correction the instrument applies with the stored
  standards (each one optional);
- ``phase_error(f)``.
"""

from __future__ import annotations

import cmath
import math
from typing import Literal

from b1500_test_agent.models.sim import FixtureParams
from b1500_test_agent.transport.sim.devices.base import Voltages, check_frequency, two_terminal

Standard = Literal["open", "short", "load"]


class FixtureDevice:
    """``fixture``: the CMU path parasitics of ``FixtureParams`` (terminals ``high``/``low``, wired to the CMU).

    At DC only the open leakage ``(V_high - V_low)/r_open_ohm`` flows; the AC behaviour is applied by the CMU unit
    through ``measured``/``standard``/``compensate``. Stateless.
    """

    terminals = ("high", "low")

    def __init__(self, name: str, params: FixtureParams) -> None:
        self.name = name
        self.model = "fixture"
        self.params = params

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "high", "low")
        current = 0.0 if dv is None else dv / self.params.r_open_ohm
        return {"high": current, "low": -current}

    # -- parasitics ----------------------------------------------------------------------------------------------------

    def y_open(self, f: float) -> complex:
        """Open admittance ``1/r_open + jω·c_open`` (S) across the DUT terminals."""
        omega = 2.0 * math.pi * check_frequency(f)
        return complex(1.0 / self.params.r_open_ohm, omega * self.params.c_open_f)

    def z_short(self, f: float) -> complex:
        """Short impedance ``r_short + jω·l_short`` (Ω) in series with the DUT."""
        omega = 2.0 * math.pi * check_frequency(f)
        return complex(self.params.r_short_ohm, omega * self.params.l_short_h)

    def phase_error(self, f: float) -> float:
        """Phase error (rad) of an uncompensated reading at ``f``: ``phase_deg_per_mhz·f/1 MHz`` (cable delay)."""
        return math.radians(self.params.phase_deg_per_mhz * check_frequency(f) / 1.0e6)

    def measured(self, z_dut: complex | None, f: float, *, phase_adjusted: bool) -> complex:
        """Uncorrected CMU reading (Ω) of ``z_dut`` (``None``: nothing connected; 0: a short) through the
        fixture."""
        if z_dut is not None and z_dut == 0:
            z = self.z_short(f)  # the short bypasses the open admittance
        else:
            y = self.y_open(f) + (0.0 if z_dut is None else 1.0 / z_dut)
            z = self.z_short(f) + 1.0 / y
        return z if phase_adjusted else z * cmath.exp(1j * self.phase_error(f))

    def standard(self, kind: Standard, f: float, *, phase_adjusted: bool, z_load: complex | None = None) -> complex:
        """The reading while acquiring correction standard ``kind`` (``load`` needs the standard's ``z_load``)."""
        if kind == "open":
            return self.measured(None, f, phase_adjusted=phase_adjusted)
        if kind == "short":
            return self.measured(0.0, f, phase_adjusted=phase_adjusted)
        if z_load is None:
            raise ValueError("the load standard needs z_load")
        return self.measured(z_load, f, phase_adjusted=phase_adjusted)

    def truth(self) -> dict[str, float]:
        """The parasitics a missing correction leaves in a reading."""
        p = self.params
        return {"c_open_f": p.c_open_f, "r_open_ohm": p.r_open_ohm, "r_short_ohm": p.r_short_ohm,
                "l_short_h": p.l_short_h, "phase_deg_per_mhz": p.phase_deg_per_mhz}


def compensate(z_meas: complex, *, z_open: complex | None = None, z_short: complex | None = None,
               load: tuple[complex, complex] | None = None) -> complex:
    """Corrected impedance from a reading and the stored standard readings (all at the same frequency).

    Open/short: ``Z = (Zm - Zs)(Zo - Zs)/(Zo - Zm)`` (exact for the fixture model; a missing open means ``Yo = 0``,
    ``Z = Zm - Zs``; a missing short means ``Zs = 0``). With ``load = (Zstd_measured, Zstd_true)`` (needs open and
    short): ``Z = Zstd·(Zo - Zsm)(Zm - Zs)/((Zo - Zm)(Zsm - Zs))``, which also removes a phase error.
    """
    zs = 0.0 if z_short is None else z_short
    if load is not None:
        if z_open is None or z_short is None:
            raise ValueError("load compensation needs the open and short standards")
        z_std_meas, z_std = load
        return z_std * (z_open - z_std_meas) * (z_meas - zs) / ((z_open - z_meas) * (z_std_meas - zs))
    if z_open is None:
        return z_meas - zs
    return (z_meas - zs) * (z_open - zs) / (z_open - z_meas)


def cp_g(z: complex, f: float) -> tuple[float, float]:
    """Parallel capacitance (F) and conductance (S) of impedance ``z`` at ``f`` (the CMU's Cp-G model)."""
    y = 1.0 / z
    return y.imag / (2.0 * math.pi * check_frequency(f)), y.real
