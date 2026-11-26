"""MFCMU measurement engine of the simulator (blueprint v2 4.1, 4.2 ``fixture`` + ``capacitor``, ``moscap``; WP8.1).

``CmuEngine`` is the base of ``CmuUnit`` (``units/cmu.py``, the FLEX handlers); it holds no handler. It evaluates
MFCMU measurements on the scenario circuit, independently of ``driver/cmu_data.py`` (no shared code):

- **Routing** (``_route_sides``): a terminal wired to ``"<slot>H"``/``"<slot>L"`` sees the MFCMU's DC bias (High)
  or 0 V (Low, the virtual ground the current is measured at) while the MFCMU output switch is on. With an SCUU on
  that MFCMU (``scenario.scuu``) the ``SSP`` path decides (PG p520 (4-202) Table 4-30): the side is the MFCMU, the
  SMU in slot ``slot - 1`` (High/Force1) or ``slot - 2`` (Low/Force2), or open; an SMU-routed side carries that SMU's
  level and its current counts as the SMU's.
- **Impedance** (``_dut_admittance``): the admittance between the two sides: ``AcDevice.admittance`` of two-terminal
  devices (``capacitor``, ``moscap``, ``fecap``, ``dielectric``) at their DC bias, a ``mosfet``'s ``gate_admittance``
  towards the terminals on the other side (split C-V), and for every other device the numeric DC small-signal
  conductance. Current into terminals on SMUs or the GNDU (AC ground) is not seen by the Low side. The oscillator
  swing is not infinitesimal (WP8.4, the C-ACV sweep MM 23): the MFCMU reports the fundamental of the current, which
  for a quasi-static nonlinear element is the describing function ``Y_1 = (2/π) ∫ Y(V0 + Vp u) √(1 - u²) du`` over
  the swing ``Vp = √2·Vac`` of the High side (``AC_QUADRATURE``: Gauss-Chebyshev nodes; exact for a linear element,
  ``C_1 ≈ C(V0) + C''(V0)·Vac²/4`` for a curved C-V).
- **Measurement path** (``_reading``): the ``fixture`` device wired to the sides (an ideal one when the scenario has
  none) adds its parasitics and, unless phase compensation is in effect (``ADJ`` mode 1 with a completed ``ADJ?``,
  or mode 2), the cable phase error (``FixtureDevice.measured``); the stored open/short/load data of the listed
  frequency, for the correction functions switched on, are removed (``fixture.compensate``; a non-ideal ``DCORR``
  open or short reference is removed from its standard's reading first); then the scenario's relative noise
  (``noise.rel`` at ``CMU_NOISE_REF_VRMS``, scaled by the averaging time and inversely by the oscillator level: the
  impedance error is a fixed current-measurement error over a smaller or larger signal) and the ``IMP`` conversion
  (Table 4-16, PDF 347).
- **Timing and data**: steps follow ``WT*``-style hold/delay/step delay (sweeps), ``PTDCV`` (pulses) and ``MTDCV``
  (C-t). Dynamic devices are advanced through every interval with the levels applied then, so a fast sweep into
  inversion shows deep depletion and a FeCap's polarization follows the bias. Data blocks per PDF 46-49 (see
  ``driver/cmu_data.py`` for the layout); automatic abort (``WMDCV``/``WMFC``/``WMACV`` 2) on status ``U``, ``D`` or
  ``V`` fills the rest with ``199.999E+99``; the source returns to the start value after an abort, else to the post
  value.

Simulator conventions (not from the manual; TODO(verify)[L6.A2, L6.A4, L6.A5]): ``ACT`` auto mode averages N x 8 ms
per point, PLC mode N / 50 Hz; ``CORR?`` takes 50 ms per listed frequency and ``ADJ?`` mode 1 30 s; corrections act
only at listed frequencies (exact match), anywhere else the reading stays uncorrected. A fixed ``RC`` range more than
100 x the measured |Z| saturates the IV amplifier (status ``D``): simulator convention, unreachable: every kind sets
the auto range (``catalog/kinds/cmu_measure.py`` calls ``B1500Driver.set_cmu_range(ch)``, ``RC ch,0``).
"""

from __future__ import annotations

import cmath
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from b1500_test_agent.models.sim import FixtureParams
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import AcDevice, Device
from b1500_test_agent.transport.sim.devices.fixture import FixtureDevice, compensate
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT
from b1500_test_agent.transport.sim.format import DUMMY_VALUE, Element
from b1500_test_agent.transport.sim.state import ChannelState, CmuCorrectionPoint, CmuPersistent
from b1500_test_agent.transport.sim.units.base import CMU_TYPES, Measurement

CMU_MODES = frozenset({17, 18, 19, 20, 22, 23, 26})
"""MFCMU measurement modes (PG Table 4-28, PDF 471-472)."""

MONITOR_MODES = frozenset({17, 18, 22, 23})
"""Modes where ``LMN 1`` adds the oscillator level and DC bias monitors (PG PDF 445)."""

SOURCE_TYPES = {18: "V", 20: "V", 22: "F", 23: "V"}
"""Data type of ``Source_data`` per sweep mode (PDF 48, Table 1-12)."""

CMU_AUTO_UNIT_S = 8e-3
"""Averaging time per ``ACT`` auto-mode coefficient (simulator convention)."""

CMU_NOISE_REF_S = 16e-3
"""Averaging time of the initial ``ACT 0,2``; noise scales with ``sqrt(CMU_NOISE_REF_S / time)``."""

CMU_NOISE_REF_VRMS = 0.03
"""Oscillator level at which the relative noise is ``noise.rel``; it scales with ``CMU_NOISE_REF_VRMS / Vac``
(simulator convention; the level is floored at ``CMU_NOISE_MIN_VRMS``)."""

CMU_NOISE_MIN_VRMS = 1e-3
"""Smallest oscillator level the noise scaling uses (the MFCMU measures from 10 mVrms; R-CMU-01)."""

AC_QUADRATURE: tuple[tuple[float, float], ...] = tuple(
    (math.cos(k * math.pi / 9), 2.0 / 9 * math.sin(k * math.pi / 9) ** 2) for k in range(1, 9))
"""(node ``u``, weight) of the eight-point Gauss-Chebyshev rule of the second kind for ``(2/π) ∫ f(u) √(1 - u²) du``
over ``-1..1`` (weights sum to 1; exact for polynomials up to degree 15)."""

SATURATION_RATIO = 100.0
"""A fixed range larger than ``SATURATION_RATIO`` x |Z| saturates the IV amplifier (status ``D``; convention)."""

CORR_POINT_S = 0.05
"""Time ``CORR?`` takes per listed frequency (simulator convention; the manual says it is short, PDF 251)."""

PHASE_COMPENSATION_S = 30.0
"""Time of ``ADJ? chnum,1`` (PG PDF 355: about 30 seconds)."""

IDEAL_FIXTURE = FixtureParams(c_open_f=0.0, r_open_ohm=1.0e18, r_short_ohm=0.0, l_short_h=0.0, phase_deg_per_mhz=0.0)
"""The measurement path of a scenario without a ``fixture`` device: no parasitics, no phase error."""

SSP_SIDES: dict[int, tuple[str, str]] = {1: ("smu", "open"), 2: ("open", "smu"), 3: ("smu", "smu"), 4: ("cmu", "cmu")}
"""``SSP`` path -> (High/output 1, Low/output 2) connection (PG p520 (4-202) Table 4-30)."""

IMP_TABLE: dict[int, tuple[tuple[str, str], tuple[str, str]]] = {
    1: (("R", "Z"), ("X", "Z")), 2: (("G", "Y"), ("B", "Y")), 10: (("Z", "Z"), ("rad", "R")),
    11: (("Z", "Z"), ("deg", "P")), 20: (("Y", "Y"), ("rad", "R")), 21: (("Y", "Y"), ("deg", "P")),
    100: (("Cp", "C"), ("G", "Y")), 101: (("Cp", "C"), ("Dp", "D")), 102: (("Cp", "C"), ("Qp", "Q")),
    103: (("Cp", "C"), ("Rp", "Z")), 200: (("Cs", "C"), ("Rs", "Z")), 201: (("Cs", "C"), ("Ds", "D")),
    202: (("Cs", "C"), ("Qs", "Q")), 300: (("Lp", "L"), ("G", "Y")), 301: (("Lp", "L"), ("DLp", "D")),
    302: (("Lp", "L"), ("QLp", "Q")), 303: (("Lp", "L"), ("Rp", "Z")), 400: (("Ls", "L"), ("Rs", "Z")),
    401: (("Ls", "L"), ("DLs", "D")), 402: (("Ls", "L"), ("QLs", "Q")),
}  # fmt: skip
"""``IMP`` mode -> ((primary, data type), (secondary, data type)) (Table 4-16, PDF 347; letters Table 1-12, PDF 55).
The names select the conversion in ``impedance_parameter``."""


def impedance_parameter(name: str, z: complex, f: float) -> float:
    """One Table 4-16 parameter of impedance ``z`` (Ohm) at ``f`` (Hz): series values from ``Z = R + jX``, parallel
    values from ``Y = 1/Z = G + jB``; D and Q of the C or L form named (``Dp`` = G/B, ``Ds`` = -R/X, ``DLp`` = -G/B,
    ``DLs`` = R/X, Q their inverse). May return a non-finite value (an open or a short), which the caller reports as
    over range."""
    w = 2.0 * math.pi * f
    r, x = z.real, z.imag
    y = 1.0 / z if z != 0 else complex(math.inf, 0.0)
    g, b = y.real, y.imag
    conversions: dict[str, Callable[[], float]] = {
        "R": lambda: r, "X": lambda: x, "G": lambda: g, "B": lambda: b, "Z": lambda: abs(z), "Y": lambda: abs(y),
        "rad": lambda: cmath.phase(z), "deg": lambda: math.degrees(cmath.phase(z)),
        "Cp": lambda: b / w, "Rp": lambda: 1.0 / g, "Dp": lambda: g / b, "Qp": lambda: b / g,
        "Cs": lambda: -1.0 / (w * x), "Rs": lambda: r, "Ds": lambda: -r / x, "Qs": lambda: -x / r,
        "Lp": lambda: -1.0 / (w * b), "DLp": lambda: -g / b, "QLp": lambda: -b / g,
        "Ls": lambda: x / w, "DLs": lambda: r / x, "QLs": lambda: x / r,
    }  # fmt: skip
    try:
        return float(conversions[name]())
    except ZeroDivisionError:
        return math.inf


def admittance_parameter_phase(name: str, z: complex, f: float) -> float:
    """Phase for the Y-theta modes 20/21: the admittance's phase (the negative of the impedance's)."""
    value = impedance_parameter(name, z, f)
    return -value if name in ("rad", "deg") else value


@dataclass
class CmuStep:
    """One measured point: the DC bias, AC level and frequency at the measurement, the source value reported, the
    intervals (duration, DC bias) the DUT holds before it, when its measurement starts (relative to ``XE``), its
    0-based position (the step-indexed faults) and, for C-t sampling, the sampling index ``Sampling_no``."""

    dc: float
    ac: float
    f: float
    source: float | None
    before: list[tuple[float, float]] = field(default_factory=list)
    start_s: float = 0.0
    position: int = 0
    index: int = 0


class CmuEngine:
    """MFCMU measurement engine of ``SimInstrument`` (see the module docstring)."""

    # -- routing --------------------------------------------------------------------------------------------------

    def _cmu_slots(self) -> list[int]:
        return [slot for slot in sorted(self._slots()) if self._module_type(slot) in CMU_TYPES]

    def _scuu_on(self, cmu: int) -> bool:
        return cmu in self.scenario.scuu and self._module_type(cmu) in CMU_TYPES

    def _side_routes(self, cmu: int) -> tuple[str, str]:
        """(High, Low) connection of MFCMU ``cmu``'s sides: ``cmu`` (no SCUU: always), ``smu`` or ``open``."""
        if not self._scuu_on(cmu):
            return ("cmu", "cmu")
        return SSP_SIDES.get(self.state.scuu_paths.get(cmu, 0), ("open", "open"))

    def _route_sides(self, levels: dict[int, float], dc_override: dict[int, float] | None = None,
                     ) -> tuple[dict[str, float], dict[str, int]]:
        """Levels of the MFCMU side nodes and the SMU each SCUU-routed side belongs to (module docstring).
        ``levels`` are the SMU levels in effect (trial levels during a compliance solve); ``dc_override`` replaces
        the MFCMU DC bias (a sweep step)."""
        sides: dict[str, float] = {}
        alias: dict[str, int] = {}
        wired = self._wired_sides()
        if not wired:
            return sides, alias  # no terminal on an MFCMU side: nothing to route (every v1 scenario)
        if dc_override is None:
            dc_override = getattr(self, "_cmu_dc_override", None)
        for cmu in self._cmu_slots():
            routes = self._side_routes(cmu)
            state = self.state.channels.get(cmu)
            for k, (suffix, route) in enumerate(zip(("H", "L"), routes, strict=True)):
                key = f"{cmu}{suffix}"
                if route == "cmu" and state is not None and state.output_on:
                    dc = state.voltage if dc_override is None else dc_override.get(cmu, state.voltage)
                    sides[key] = dc if suffix == "H" else 0.0
                elif route == "smu":
                    smu = cmu - (k + 1)
                    if smu in levels:
                        sides[key] = levels[smu]
                        alias[key] = smu
        return sides, alias

    def _wired_sides(self) -> frozenset[str]:
        """The MFCMU side nodes some device terminal is wired to (the wiring is fixed per scenario; cached)."""
        cached = self.__dict__.get("_sides_cache")
        if cached is None or cached[0] is not self.circuit:
            nodes = frozenset(t for terms in self.circuit.wiring.values() for t in terms.values() if isinstance(t, str)
                              and t != "GNDU")
            cached = (self.circuit, nodes)
            self.__dict__["_sides_cache"] = cached
        return cached[1]

    def _cmu_connected(self, cmu: int) -> bool:
        return self._side_routes(cmu) == ("cmu", "cmu")

    # -- impedance ------------------------------------------------------------------------------------------------

    def _cmu_fixture(self, cmu: int) -> FixtureDevice:
        high, low = f"{cmu}H", f"{cmu}L"
        for name, device in self.circuit.devices.items():
            wiring = self.circuit.wiring.get(name, {})
            if isinstance(device, FixtureDevice) and wiring.get("high") == high and wiring.get("low") == low:
                return device
        return FixtureDevice("ideal", IDEAL_FIXTURE)

    def _dut_admittance(self, cmu: int, levels: dict[int | str, float], f: float,
                        ac_vrms: float = 0.0) -> complex | None:
        """Admittance (S) between the High and Low side of ``cmu`` (``None``: nothing connects them); with an
        oscillator level ``ac_vrms`` the describing function over the High side's swing (module docstring)."""
        high, low = f"{cmu}H", f"{cmu}L"
        swing = math.sqrt(2.0) * ac_vrms
        total = 0j
        found = False
        for name, device in self.circuit.devices.items():
            if isinstance(device, FixtureDevice):
                continue
            wiring = self.circuit.wiring.get(name, {})
            hi = [t for t, target in wiring.items() if target == high]
            lo = [t for t, target in wiring.items() if target == low]
            if not hi or not lo:
                continue
            found = True
            if swing <= 0.0 or high not in levels:
                total += self._device_admittance(device, self.circuit.terminal_voltages(name, levels), hi, lo, f)
                continue
            for u, weight in AC_QUADRATURE:
                shifted = {**levels, high: levels[high] + swing * u}
                total += weight * self._device_admittance(device, self.circuit.terminal_voltages(name, shifted), hi,
                                                          lo, f)
        return total if found else None

    @staticmethod
    def _device_admittance(device: Device, v: dict[str, float | None], hi: list[str], lo: list[str],
                           f: float) -> complex:
        if getattr(device, "cv", None) is not None and hasattr(device, "gate_admittance") and \
                ("gate" in hi or "gate" in lo):
            other = lo if "gate" in hi else hi
            return complex(device.gate_admittance(v, f, other))  # type: ignore[attr-defined]
        if isinstance(device, AcDevice):
            a, b = device.terminals
            if (a in hi and b in lo) or (a in lo and b in hi):
                va, vb = v.get(a), v.get(b)
                return complex(device.admittance((va or 0.0) - (vb or 0.0), f))
            return 0j
        delta = 1e-3

        def low_current(shift: float) -> float:
            trial = {t: (None if value is None else value + shift if t in hi else value) for t, value in v.items()}
            currents = device.terminal_currents(trial)
            return sum(currents.get(t, 0.0) for t in lo)

        return complex(-(low_current(delta) - low_current(-delta)) / (2.0 * delta), 0.0)

    def _phase_adjusted(self, cmu: int) -> bool:
        mode = self._cmu_persistent(cmu).adj_mode
        return mode == 2 or (mode == 1 and self.state.cmu_phase_results.get(cmu) == 0)

    def _cmu_persistent(self, cmu: int) -> CmuPersistent:
        return self.state.cmu.setdefault(cmu, CmuPersistent())

    def _correction_point(self, cmu: int, f: float) -> CmuCorrectionPoint | None:
        for point in self._cmu_persistent(cmu).data:
            if math.isclose(point.freq_hz, f, rel_tol=1e-6):
                return point
        return None

    def _corrected(self, cmu: int, z: complex, f: float) -> complex:
        """Remove the stored standards' effects for the correction functions that are on (module docstring)."""
        on = self.state.cmu_corrections.get(cmu, {})
        point = self._correction_point(cmu, f) if any(on.values()) else None
        if point is None:
            return z
        w = 2.0 * math.pi * f
        standards = self._cmu_persistent(cmu).standards
        z_short = complex(*point.short) if on.get(2) and point.short else None
        if z_short is not None and 2 in standards:
            z_short -= complex(standards[2][2], w * standards[2][1])
        z_open = complex(*point.open) if on.get(1) and point.open else None
        if z_open is not None and 1 in standards:
            y_std = complex(standards[1][2], w * standards[1][1])
            y_fixture = 1.0 / (z_open - (z_short or 0.0)) - y_std
            if y_fixture != 0:
                z_open = (z_short or 0.0) + 1.0 / y_fixture
        load = None
        if on.get(3) and point.load and point.load_ref and z_open is not None and z_short is not None:
            load = (complex(*point.load), complex(*point.load_ref))
        return compensate(z, z_open=z_open, z_short=z_short, load=load)

    def _standard_reading(self, cmu: int, corr: int, f: float, ref: list[float] | None) -> complex:
        """What ``CORR?`` reads with the standard connected (the human connects it; ``ref`` = its ``DCORR``
        reference ``[mode, primary, secondary]``, the true value of the standard)."""
        fixture = self._cmu_fixture(cmu)
        adjusted = self._phase_adjusted(cmu)
        w = 2.0 * math.pi * f
        if corr == 1:
            y = complex(ref[2], w * ref[1]) if ref else 0j
            return fixture.measured(None if y == 0 else 1.0 / y, f, phase_adjusted=adjusted)
        z = complex(ref[2], w * ref[1]) if ref else 0j
        if corr == 2:
            return fixture.measured(z, f, phase_adjusted=adjusted)
        return fixture.standard("load", f, phase_adjusted=adjusted, z_load=z)

    # -- one reading ----------------------------------------------------------------------------------------------

    def _cmu_time(self) -> float:
        mode, n = self._act
        return n * CMU_AUTO_UNIT_S if mode == 0 else n / flex.LINE_FREQUENCY_HZ

    def _fixed_range(self, cmu: int, f: float) -> float | None:
        mode, value = self._rc.get(cmu, (0, 0))
        if mode != 2:
            return None
        available = [r for r in (50.0, 100.0, 300.0, 1e3, 3e3, 1e4, 3e4, 1e5, 3e5)
                     if not (r >= 1e5 and f > 2e5) and not (r >= 1e4 and f > 2e6)]
        chosen = [r for r in available if r <= max(value, 50.0)]
        return chosen[-1] if chosen else available[0]

    def _reading(self, cmu: int, levels: dict[int | str, float], f: float, rng: random.Random, ac_vrms: float,
                 ) -> tuple[complex, str]:
        """The impedance the MFCMU reports at ``f`` and oscillator level ``ac_vrms`` with ``levels`` applied, and its
        status letter."""
        y = self._dut_admittance(cmu, levels, f, ac_vrms) if self._cmu_connected(cmu) else None
        z_dut = None if y is None or y == 0 else 1.0 / y
        z = self._corrected(cmu, self._cmu_fixture(cmu).measured(z_dut, f, phase_adjusted=self._phase_adjusted(cmu)),
                            f)
        sigma = (self.scenario.noise.rel * math.sqrt(CMU_NOISE_REF_S / max(self._cmu_time(), 1e-6))
                 * CMU_NOISE_REF_VRMS / max(ac_vrms, CMU_NOISE_MIN_VRMS))
        if sigma > 0:
            z *= complex(1.0 + rng.gauss(0.0, sigma), rng.gauss(0.0, sigma))
        fixed = self._fixed_range(cmu, f)
        status = "D" if fixed is not None and abs(z) * SATURATION_RATIO < fixed else "N"
        return z, status

    def _parameter_elements(self, cmu: int, z: complex, f: float, status: str) -> list[str]:
        out: list[str] = []
        for name, dtype in IMP_TABLE[self._imp]:
            value = (admittance_parameter_phase(name, z, f) if self._imp in (20, 21)
                     else impedance_parameter(name, z, f))
            letter = status if math.isfinite(value) and abs(value) < 1e99 else "V"
            out.append(Element(letter, cmu, dtype, value if letter != "V" else DUMMY_VALUE).text())
        return out

    # -- measurement ----------------------------------------------------------------------------------------------

    def _cmu_measure(self, mode: int, channels: list[int], steps: list[CmuStep], t0: float,
                     on_end: Callable[[bool, bool], None], abort_enabled: bool) -> Measurement:
        """Evaluate ``steps`` of an MFCMU measurement started at ``t0`` (module docstring)."""
        cmu, smus = channels[0], channels[1:]
        factor = self.faults.slow_factor()
        rng = random.Random(f"{self.scenario.noise.seed}:cmu:{self.state.measurement_count}")
        self.state.measurement_count += 1
        t_meas = self._cmu_time()
        smu_levels = self._on_levels()
        icomps = {ch: self._icomp(ch) for ch in smu_levels}
        blocks: list[list[str]] = []
        step_ends: list[float] = []
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        aborted = False
        tripped = False
        last = len(steps) - 1
        for i, step in enumerate(steps):
            for duration, dc in step.before:
                self._advance_cmu(cmu, duration, dc, smu_levels)
            sides, _ = self._route_sides(smu_levels, {cmu: step.dc})
            levels: dict[int | str, float] = {**smu_levels, **sides}
            end = t0 + factor * (step.start_s + t_meas)
            step_ends.append(end)
            stamp = t0 + factor * step.start_s - self._timer_zero
            condition = None if aborted else self.faults.cmu_overload_at(step.position)
            if condition == "excess_current":
                self._queue_error(flex.ERR_CMU_EXCESS_CURRENT)
                tripped = aborted = True
            if aborted:
                blocks.append(self._cmu_block(mode, cmu, smus, step, stamp, None, "V", [], i == last))
                continue
            z, status = self._reading(cmu, levels, step.f, rng, step.ac)
            if condition is not None:
                status = "D" if condition == "saturation" else "U"
            currents: list[float] = []
            if smus:
                self._cmu_dc_override = {cmu: step.dc}
                try:
                    _, smu_currents, _ = self.solve(dict(smu_levels), icomps)
                finally:
                    self._cmu_dc_override = None
                currents = [smu_currents.get(ch, 0.0) for ch in smus]
            blocks.append(self._cmu_block(mode, cmu, smus, step, stamp, z, status, currents, i == last))
            self._advance_cmu(cmu, t_meas, step.dc, smu_levels)
            if self.circuit.has_state:
                device_states.append(self.circuit.export_state())
            if abort_enabled and status in "UDV":
                aborted = True  # automatic abort: the remaining steps carry dummy data
        self._sync_devices()
        return Measurement(t0, step_ends[-1], step_ends, blocks, None, None, None, device_states,
                           on_end=lambda ab: on_end(ab or aborted, tripped))

    def _advance_cmu(self, cmu: int, duration: float, dc: float, smu_levels: dict[int, float]) -> None:
        if not self.circuit.dynamic or duration < 0:
            return
        sides, _ = self._route_sides(smu_levels, {cmu: dc})
        self.circuit.advance(duration, {**smu_levels, **sides})

    def _cmu_block(self, mode: int, cmu: int, smus: list[int], step: CmuStep, stamp: float, z: complex | None,
                   status: str, currents: list[float], is_last: bool) -> list[str]:
        texts: list[str] = []
        if mode == 26 and self._fmt_mode != 0:
            texts.append(Element("N", cmu, "X", step.index).text())
        if self._tsc:
            texts.append(Element("N", cmu, "T", stamp).text())
        if z is None:
            texts += [Element("V", cmu, dtype, DUMMY_VALUE).text() for _, dtype in IMP_TABLE[self._imp]]
        else:
            texts += self._parameter_elements(cmu, z, step.f, status)
        if self._lmn and mode in MONITOR_MODES:
            monitor = "N" if z is not None else "V"
            texts += [Element(monitor, cmu, "V", step.ac).text(), Element(monitor, cmu, "V", step.dc).text()]
        for k, smu in enumerate(smus):
            if self._tsc:
                texts.append(Element("N", smu, "T", stamp).text())
            texts.append(Element("N" if z is not None else "V", smu, "I", currents[k] if currents else 0.0).text())
        if self._fmt_mode == 1 and mode in SOURCE_TYPES and step.source is not None:
            texts.append(Element("E" if is_last else "W", cmu, SOURCE_TYPES[mode], step.source).text())
        if self.faults.garbage_at(step.position):
            texts[0] = GARBAGE_ELEMENT
        return texts

    def _cmu_off(self, cmu: int) -> None:
        """Excess current: the MFCMU output switch was set to OFF (error 320, PG PDF 583)."""
        if not self.faults.stuck(cmu):
            self.state.channels[cmu] = ChannelState()

