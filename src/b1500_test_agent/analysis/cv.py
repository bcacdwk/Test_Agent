"""Capacitance-voltage analysis (blueprint v2 2.10 ``cv.py``; WP8.3): ``cv_cox``, ``cv_flatband``,
``cv_doping_profile``, ``cv_vth``, ``cv_hysteresis``, ``impedance_convert`` and the plots of ``plot_cv``. The
definitions below are the source of knowledge file ``08-capacitance-cv.md`` (skill ``b1500-test``); change both
together.

**Data.** A ``cmu_measure`` run table holds the MFCMU pair of the ``cmu_high`` role (``<role>_Cp``/``_G``,
``_Cs``/``_Rs``, ``_Cp``/``_D``, ``_Cs``/``_D`` or ``_Z``/``_theta``) with ``freq_hz``, ``ac_vrms`` and ``dc_v``.
Every method first converts the pair to the admittance ``Y = G + jwCp`` at ``w = 2 pi f`` (``to_admittance``;
``Cs``/``Rs`` and ``Z``/``theta`` through ``Z = 1/Y``; ``D = G/(wCp)`` (parallel) or ``Rs w Cs`` (series)), optionally
removes a series resistance ``rs_ohm`` (``remove_series_r``: ``Y_c = 1/(1/Y - Rs)``), and analyses one frequency
(``freq_hz``; default the first in the table) and one segment (``fwd``/``rev`` of a double sweep). Trust follows the
shared rules (``common.py``): untrusted points (MFCMU status ``U D V X``) refuse the extraction unless ``force``
(flagged).

**Structure.** ``moscap`` (MOS capacitor, the default) or ``split`` (split C-V of a MOSFET, recipes ``mosfet.cgc_cv``
and ``mosfet.cgd_cv``); ``structure: auto`` decides by the recipe.

**MOS capacitor** (Nicollian & Brews, *MOS Physics and Technology*, 1982, ch. 9; Sze & Ng, 2007, ch. 4). The
substrate type follows from the curve: the high-capacitance end is accumulation (p substrate: negative gate bias).
One fit (``moscap_fit``) iterates to a consistent set:

- ``Cox`` by **accumulation extrapolation** (``plateau_extrapolation``): the majority charge grows as ``dQ = C dV``
  and in strong accumulation ``Cs = Q / (2 U_T)``, so ``1/C = 1/Cox + 2 U_T / Q``. Over the strong-accumulation tail
  (``C >= acc_frac x Cmax``) ``Q = Q0 + int C dV`` from the tail's first point, ``Q0`` (the charge already there) is
  chosen for the straightest line of ``1/C`` against ``1/Q``, and the intercept is ``1/Cox``; no flatband voltage is
  needed. ``Cmax`` itself is ``Cox`` in series with the accumulation layer (a few % low for thin oxides). ``EOT =
  3.9 eps0 A / Cox`` (needs ``geometry.area_um2``).
- **Doping** from the depletion slope (``1/C^2``): with ``A`` the gate area, ``1/C^2 = 1/Cox^2 + 2 (V - Vfb - U_T) /
  (q eps_s N A^2)`` exactly in depletion, so ``N = 2 / (q eps_s A^2 |d(1/C^2)/dV|)`` from a line over the points with
  band bending ``psi = |int_Vfb^V (1 - C/Cox) dV|`` between ``4 U_T`` and ``2 phi_B - 3 U_T`` (``phi_B = U_T ln(N /
  ni)``; outside it the Debye tail or the inversion charge bend the line); depth ``W = eps_s A (1/C - 1/Cox)``.
- ``Vfb`` by the **flatband capacitance**: ``C_FB = A Cox' C_D / (Cox' + C_D)``, ``C_D = eps_s / L_D``, ``L_D =
  sqrt(eps_s U_T / (q N))`` (``Cox' = Cox / A``); ``Vfb`` is the bias where the curve crosses ``C_FB``.
- ``Vth = Vfb + 2 phi_B + sqrt(2 q eps_s N 2 phi_B) / Cox'`` (sign mirrored for an n substrate): the strong-inversion
  onset of the fitted ideal electrostatics (not a measured crossing).
- **Hysteresis** of a double sweep: ``Vfb(rev) - Vfb(fwd)``, each the crossing of the ``fwd`` branch's ``C_FB`` (or,
  without an area, the mid level ``(Cmax + Cmin)/2``) nearest to the ``fwd`` flatband; negative when the return
  branch lies at lower bias.

Defaults: ``T = 300 K``, ``ni = 1e10 cm^-3``, ``eps_s = 11.7 eps0`` (silicon), ``eps_ox = 3.9 eps0`` (SiO2 EOT).
Without ``geometry.area_um2`` the doping, flatband, threshold and EOT values are refused (naming the field); ``Cox``
(F) needs no geometry.

**Split C-V** (Koomen 1973; Sodini et al. 1982). The low-capacitance end is accumulation; its floor (median of the
three smallest values) is the overlap capacitance and is removed (``c = C - floor``). In strong inversion ``1/c =
1/(Cox W L) + k / Q`` with ``Q`` the inversion charge, so the same ``plateau_extrapolation`` over ``c >= acc_frac x
c_max`` gives the plateau ``Cox W L`` (``cv_cox`` reports it as ``cox``; per area and EOT with ``geometry`` W and L or
``area_um2``). ``Vth`` (``cv_vth``) is the **onset** of the
inversion capacitance, the maximum of ``d^2 c / dV^2`` (local quadratic fits over five points, vertex refined) in the
rising part (``0.01 .. 0.7 x c_max``). For ``mosfet.cgd_cv`` the plateau is about ``Cox W L / 2 + Cov``; only
``cv_vth`` applies.

**impedance_convert** reports a run's readings in another parameter pair (``to``: ``cp_g``, ``cp_d``, ``cs_rs``,
``cs_d``, ``z_theta`` (radian)) at one point per frequency: the mean over a spot run's samples, the point nearest
``at_v`` of a sweep (default: the largest capacitance, i.e. strong accumulation or inversion). ``series_r``:
``none``, ``value`` (``rs_ohm``) or ``accumulation``: ``Rs = G_ma / (G_ma^2 + w^2 C_ma^2)`` from the parallel values
at the largest capacitance (strong accumulation; Nicollian & Brews eq. 5.12), removed before converting and reported
as ``rs``. The full converted curve is ``convert_table`` (ad-hoc scripts) and ``plot_cv(model=...)``.

**plot_cv** draws C-V (``C`` and ``G/w`` or the pair's second quantity, per frequency and segment; trusted points as
lines, limited as circles, untrusted as crosses), ``1/C^2`` against ``V`` for a MOS capacitor, ``C`` against
frequency for a C-f run or a spot run with several frequencies, against ``t_s`` for a C-t run and against the AC level
for a C-V (AC level) run (WP8.4). Plots never refuse and never extract anything.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    Rows,
    analysed_rows,
    excluded_counts,
    policy_params,
    trust_policy,
    window_of,
)
from b1500_test_agent.analysis.dataset import (
    AC_VRMS,
    DC_V,
    FREQ_HZ,
    SEGMENT,
    T_S,
    RunData,
    Segment,
    parse_value_column,
    trust_levels,
    work_dir_for,
)
from b1500_test_agent.analysis.plots import INVALID_ABOVE, PlotSet, RenderedPlot, figure_png, new_figure
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy, Unit

Q_E = 1.602176634e-19
EPS0_F_CM = 8.8541878128e-14
K_B = 1.380649e-23
EPS_SI = 11.7
EPS_SIO2 = 3.9
UM2_TO_CM2 = 1e-8
DEFAULT_NI_CM3 = 1.0e10
DEFAULT_T_K = 300.0

Structure = Literal["auto", "moscap", "split"]
Model = Literal["cp_g", "cp_d", "cs_rs", "cs_d", "z_theta"]
SeriesR = Literal["none", "value", "accumulation"]

PAIRS: dict[str, tuple[str, str]] = {
    "cp_g": ("Cp", "G"), "cp_d": ("Cp", "D"), "cs_rs": ("Cs", "Rs"), "cs_d": ("Cs", "D"), "z_theta": ("Z", "theta"),
}  # fmt: skip
"""Parameter pair -> run-table quantities (``analysis/dataset.py`` columns)."""

UNITS: dict[str, Unit] = {"Cp": "F", "G": "S", "Cs": "F", "Rs": "Ohm", "D": "1", "Z": "Ohm", "theta": "rad"}
SPLIT_RECIPES = frozenset({"mosfet.cgc_cv", "mosfet.cgd_cv"})
ACC_FRAC = 0.85
PLATEAU_FRAC = 0.85
MIN_FIT_POINTS = 3
ITERATIONS = 6
_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


# -- impedance models ------------------------------------------------------------------------------------------------


def pair_of(d: RunData) -> tuple[str, str, str]:
    """``(role, primary, secondary)`` of the run's MFCMU pair (the measured columns with MFCMU quantities).

    Raises:
        InvalidInputError: If the run has no MFCMU pair (not a capacitance run).
    """
    found: dict[str, set[str]] = {}
    for column in d.measured_columns:
        parsed = parse_value_column(column)
        if parsed is not None and parsed[1] in UNITS:
            found.setdefault(parsed[0], set()).add(parsed[1])
    for role, quantities in found.items():
        for primary, secondary in PAIRS.values():
            if {primary, secondary} <= quantities:
                return role, primary, secondary
    raise InvalidInputError(f"run {d.run_id} has no MFCMU parameter pair (columns <role>_Cp/_G, _Cs/_Rs, _Cp/_D, "
                            "_Cs/_D or _Z/_theta); C-V methods need a capacitance run")


def to_admittance(primary: str, secondary: str, p: np.ndarray, s: np.ndarray, omega: np.ndarray) -> np.ndarray:
    """Complex admittance ``Y`` (S) of each reading of pair (``primary``, ``secondary``) at ``omega`` (rad/s)."""
    if (primary, secondary) == ("Cp", "G"):
        return s + 1j * omega * p
    if (primary, secondary) == ("Cp", "D"):
        return omega * p * s + 1j * omega * p
    if (primary, secondary) == ("Cs", "Rs"):
        return 1.0 / (s - 1j / (omega * p))
    if (primary, secondary) == ("Cs", "D"):
        return 1.0 / (s / (omega * p) - 1j / (omega * p))
    if (primary, secondary) == ("Z", "theta"):
        return 1.0 / (p * np.exp(1j * s))
    raise InvalidInputError(f"unknown MFCMU pair {primary}-{secondary}")


def from_admittance(model: str, y: np.ndarray, omega: np.ndarray) -> dict[str, np.ndarray]:
    """The quantities of ``model`` (``PAIRS``) from complex admittances ``y`` at ``omega``."""
    z = 1.0 / y
    cp, g = y.imag / omega, y.real
    cs, rs = -1.0 / (omega * z.imag), z.real
    values = {"cp_g": {"Cp": cp, "G": g}, "cp_d": {"Cp": cp, "D": g / (omega * cp)},
              "cs_rs": {"Cs": cs, "Rs": rs}, "cs_d": {"Cs": cs, "D": rs * omega * cs},
              "z_theta": {"Z": np.abs(z), "theta": np.angle(z)}}
    return values[model]


def remove_series_r(y: np.ndarray, rs_ohm: float) -> np.ndarray:
    """Admittances with a series resistance ``rs_ohm`` removed: ``1 / (1/Y - Rs)``."""
    return y if rs_ohm == 0 else 1.0 / (1.0 / y - rs_ohm)


def accumulation_rs(cp: float, g: float, omega: float) -> float:
    """Series resistance from the parallel values in strong accumulation, ``G / (G^2 + w^2 C^2)`` (module
    docstring)."""
    return g / (g * g + omega * omega * cp * cp)


def convert_table(d: RunData, model: Model = "cs_rs", *, rs_ohm: float = 0.0) -> pd.DataFrame:
    """The run's MFCMU readings as ``model`` (``step``, ``segment``, ``freq_hz``, ``dc_v`` and the two quantities as
    ``<role>_<qty>``), after removing ``rs_ohm`` (for ad-hoc scripts; results go to ``work/<run_id>/``)."""
    role, primary, secondary = pair_of(d)
    table = d.table
    omega = 2.0 * math.pi * table[FREQ_HZ].to_numpy(dtype=float)
    y = remove_series_r(to_admittance(primary, secondary, table[f"{role}_{primary}"].to_numpy(dtype=float),
                                      table[f"{role}_{secondary}"].to_numpy(dtype=float), omega), rs_ohm)
    out = table[[c for c in ("step", SEGMENT, FREQ_HZ, DC_V) if c in table.columns]].copy()
    for quantity, values in from_admittance(model, y, omega).items():
        out[f"{role}_{quantity}"] = values
    return out


# -- the analysed curve ----------------------------------------------------------------------------------------------


@dataclass
class Curve:
    """One frequency and segment of a C-V run: bias ``v`` (ascending), parallel ``c``/``g`` and the rows' trust."""

    rows: Rows
    v: np.ndarray
    c: np.ndarray
    g: np.ndarray
    freq_hz: float
    omega: float
    problems: list[str] = field(default_factory=list)

    @property
    def excluded(self) -> dict[str, int]:
        return self.rows.excluded()


def frequencies(d: RunData) -> list[float]:
    """The run's frequencies in table order."""
    if FREQ_HZ not in d.table.columns:
        raise InvalidInputError(f"run {d.run_id} has no freq_hz column; C-V methods need a capacitance run")
    return [float(f) for f in pd.unique(d.table[FREQ_HZ].dropna())]


def _select(d: RunData, freq_hz: float | None, segment: Segment | None) -> tuple[pd.DataFrame, float]:
    freqs = frequencies(d)
    if not freqs:
        raise InvalidInputError(f"run {d.run_id} has no frequency")
    freq = freqs[0] if freq_hz is None else freq_hz
    if not any(math.isclose(freq, f, rel_tol=1e-9) for f in freqs):
        raise InvalidInputError(f"run {d.run_id} has no frequency {freq:g} Hz; frequencies: {freqs}")
    rows = d.rows(segment) if segment is not None else d.table
    rows = rows[np.isclose(rows[FREQ_HZ].to_numpy(dtype=float), freq, rtol=1e-9)]
    return rows, freq


def load_curve(d: RunData, policy: TrustPolicy, *, freq_hz: float | None, segment: Segment | None,
               rs_ohm: float) -> Curve:
    """The trusted points of one frequency and segment as parallel ``C``/``G`` (series ``rs_ohm`` removed), sorted
    by bias; ``problems`` lists why an extraction must be refused (untrusted points)."""
    role, primary, secondary = pair_of(d)
    rows, freq = _select(d, freq_hz, segment)
    analysed = analysed_rows(d, DC_V, f"{role}_{primary}", policy, rows=rows)
    ok = analysed.ok & np.isfinite(rows[f"{role}_{secondary}"].to_numpy(dtype=float))
    omega = 2.0 * math.pi * freq
    v = rows[DC_V].to_numpy(dtype=float)[ok]
    y = remove_series_r(to_admittance(primary, secondary, rows[f"{role}_{primary}"].to_numpy(dtype=float)[ok],
                                      rows[f"{role}_{secondary}"].to_numpy(dtype=float)[ok], np.full(v.size, omega)),
                        rs_ohm)
    order = np.argsort(v, kind="stable")
    curve = Curve(rows=analysed, v=v[order], c=(y.imag / omega)[order], g=y.real[order], freq_hz=freq, omega=omega)
    curve.problems = analysed.problems(f"{role}_{primary} at {freq:g} Hz", noise=False)
    return curve


def _cumulative(v: np.ndarray, y: np.ndarray) -> np.ndarray:
    """``int_{v[0]}^{v} y dV`` at every point (trapezoids; ``v`` ascending)."""
    return np.concatenate([[0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(v))])


def _integral_from(v: np.ndarray, y: np.ndarray, v0: float) -> np.ndarray:
    """``int_{v0}^{v} y dV`` at every point (``v`` ascending)."""
    total = _cumulative(v, y)
    return total - float(np.interp(v0, v, total))


def _line(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    slope, intercept = (float(c) for c in np.polyfit(x, y, 1))
    residual = y - (intercept + slope * x)
    spread = float(np.sum((y - y.mean()) ** 2))
    return slope, intercept, 1.0 - float(np.sum(residual**2)) / spread if spread > 0 else 1.0


def _crossing(v: np.ndarray, c: np.ndarray, level: float, near: float) -> float | None:
    """The bias where ``c`` crosses ``level`` (linear interpolation), the crossing nearest ``near``."""
    found: list[float] = []
    for i in range(v.size - 1):
        a, b = c[i] - level, c[i + 1] - level
        if a == 0:
            found.append(float(v[i]))
        elif a * b < 0:
            found.append(float(v[i] + (v[i + 1] - v[i]) * a / (a - b)))
    if c.size and c[-1] == level:
        found.append(float(v[-1]))
    return min(found, key=lambda x: abs(x - near)) if found else None


# -- MOS capacitor fit -----------------------------------------------------------------------------------------------


@dataclass
class MoscapFit:
    """Result of ``moscap_fit``: substrate sign ``s`` (+1 p, -1 n), ``cox`` (F) and, with an area, ``nsub``
    (cm^-3), ``vfb`` (V), ``c_fb`` (F), ``vth`` (V); the fit windows and their point counts; ``warnings``."""

    s: float
    cox: float
    acc_window: tuple[float, float]
    acc_points: int
    acc_r2: float
    vfb_guess: float
    area_cm2: float | None = None
    nsub: float | None = None
    vfb: float | None = None
    c_fb: float | None = None
    vth: float | None = None
    phi_b: float | None = None
    dep_window: tuple[float, float] | None = None
    dep_points: int = 0
    depth_m: tuple[float, float] | None = None
    warnings: list[str] = field(default_factory=list)


class FitError(ValueError):
    """The curve does not allow the fit (too few points in a window, no crossing)."""


def substrate_sign(v: np.ndarray, c: np.ndarray) -> float:
    """+1 when the high-capacitance end is at negative bias (p substrate), else -1 (median of three points each)."""
    k = max(1, min(3, v.size // 4))
    return 1.0 if float(np.median(c[:k])) >= float(np.median(c[-k:])) else -1.0


OFFSET_GRID_V = (1e-4, 20.0, 600)
"""Search grid of the charge offset ``Q0`` in units of ``Cmax x 1 V`` (``plateau_extrapolation``)."""


@dataclass(frozen=True)
class Plateau:
    """Result of ``plateau_extrapolation``: the extrapolated capacitance, the fit window (indices into the ordered
    curve), the charge offset ``q0`` (C) and the line's ``r2``."""

    value: float
    first: int
    points: int
    q0: float
    r2: float
    at_grid_edge: bool


def plateau_extrapolation(x: np.ndarray, c: np.ndarray, frac: float) -> Plateau:
    """Extrapolate a capacitance plateau (module docstring): ``x`` is the bias ordered towards the plateau (strong
    accumulation of a MOS-C, strong inversion of split C-V), ``c`` the capacitance. Over the contiguous tail with
    ``c >= frac x max(c)`` the responding charge is ``Q = Q0 + int c dx`` from the window's first point, and ``1/c``
    is a straight line in ``1/Q`` whose intercept is ``1/plateau``; ``Q0`` (the charge already present at the window's
    first point) is chosen for the straightest line (least squares over a log grid), so no flatband or threshold
    voltage is needed.

    Raises:
        FitError: If the tail has fewer than ``MIN_FIT_POINTS`` points or the line has no positive intercept.
    """
    top = float(c.max())
    first = c.size
    while first > 0 and c[first - 1] >= frac * top:
        first -= 1
    points = c.size - first
    if points < MIN_FIT_POINTS:
        raise FitError(f"fewer than {MIN_FIT_POINTS} points on the plateau (C >= {frac:g} x Cmax at the end of the "
                       "sweep); sweep further into strong accumulation or inversion")
    xs, cs = x[first:], c[first:]
    q_rel = _cumulative(xs, cs)
    low, high, count = OFFSET_GRID_V
    best: tuple[float, float, float, float, int] | None = None
    for k, unit in enumerate(np.geomspace(low, high, count)):
        q = unit * top + q_rel
        slope, intercept, r2 = _line(1.0 / q, 1.0 / cs)
        residual = float(np.sum((1.0 / cs - (intercept + slope / q)) ** 2))
        if best is None or residual < best[0]:
            best = (residual, intercept, unit * top, r2, k)
    assert best is not None
    _, intercept, q0, r2, k = best
    if intercept <= 0:
        raise FitError("the plateau extrapolation has no positive intercept (no plateau in the data)")
    return Plateau(value=1.0 / intercept, first=first, points=points, q0=q0, r2=r2,
                   at_grid_edge=k in (0, count - 1))


def _cox_extrapolated(v: np.ndarray, c: np.ndarray, s: float, acc_frac: float,
                      ) -> tuple[float, tuple[float, float], int, float, list[str]]:
    """``Cox`` of a MOS-C branch (``v`` ascending): accumulation is at low bias for ``s`` = +1 (p substrate)."""
    order = np.arange(v.size)[::-1] if s > 0 else np.arange(v.size)
    plateau = plateau_extrapolation(-s * v[order], c[order], acc_frac)
    used = v[order][plateau.first:]
    warnings = ["the charge offset of the accumulation fit is at its search limit"] if plateau.at_grid_edge else []
    return plateau.value, (float(used.min()), float(used.max())), plateau.points, plateau.r2, warnings


def moscap_fit(v: np.ndarray, c: np.ndarray, *, area_cm2: float | None, acc_frac: float = ACC_FRAC,
               ni_cm3: float = DEFAULT_NI_CM3, temperature_k: float = DEFAULT_T_K) -> MoscapFit:
    """The MOS-capacitor fit of the module docstring on one HF C-V branch (``v`` ascending, ``c`` parallel F).

    Raises:
        FitError: If a window has too few points or the flatband level is not crossed.
    """
    if v.size < 2 * MIN_FIT_POINTS:
        raise FitError(f"only {v.size} trusted points")
    s = substrate_sign(v, c)
    ut = K_B * temperature_k / Q_E
    eps_s = EPS_SI * EPS0_F_CM
    cmax, cmin = float(c.max()), float(c.min())
    mid = _crossing(v, c, 0.5 * (cmax + cmin), float(np.median(v)))
    vfb = (mid if mid is not None else float(np.median(v))) - s * 0.3
    guess = vfb
    nsub: float | None = None
    cox, acc_window, acc_points, r2, warnings = _cox_extrapolated(v, c, s, acc_frac)
    fit = MoscapFit(s=s, cox=cox, acc_window=acc_window, acc_points=acc_points, acc_r2=r2, vfb_guess=guess,
                    area_cm2=area_cm2, warnings=warnings)
    for _ in range(ITERATIONS if area_cm2 is not None else 0):
        inv_c2 = 1.0 / c**2
        if nsub is None:
            local = np.abs(np.gradient(inv_c2, v))
            depletion = (s * (v - vfb) > 0) & (c > 1.05 * cmin) & (local > 0)
            if not depletion.any():
                raise FitError("no depletion points beyond the flatband estimate")
            nsub = float(np.percentile(2.0 / (Q_E * eps_s * area_cm2**2 * local[depletion]), 20))
        phi_b = ut * math.log(nsub / ni_cm3)
        psi = s * _integral_from(v, 1.0 - c / cox, vfb)
        window = (psi > 4 * ut) & (psi < 2 * phi_b - 3 * ut) & (s * (v - vfb) > 0)
        if int(window.sum()) >= MIN_FIT_POINTS:
            slope = _line(v[window], inv_c2[window])[0]
            if slope == 0:
                raise FitError("the depletion region has no 1/C^2 slope")
            nsub = 2.0 / (Q_E * eps_s * area_cm2**2 * abs(slope))
            fit.dep_window = (float(v[window].min()), float(v[window].max()))
            fit.dep_points = int(window.sum())
            widths = eps_s * area_cm2 * (1.0 / c[window] - 1.0 / cox) * 1e-2
            fit.depth_m = (float(widths.min()), float(widths.max()))
        cox_a = cox / area_cm2
        l_d = math.sqrt(eps_s * ut / (Q_E * nsub))
        c_d = eps_s / l_d
        c_fb = area_cm2 * cox_a * c_d / (cox_a + c_d)
        near = (s * (v - vfb) > -1.0) & (s * (v - vfb) < 1.0)
        crossing = _crossing(v[near], c[near], c_fb, vfb) if near.sum() >= 2 else None
        if crossing is None:
            crossing = _crossing(v, c, c_fb, vfb)
        if crossing is None:
            raise FitError(f"the curve never reaches the flatband capacitance {c_fb:.4g} F")
        vfb = crossing
        phi_b = ut * math.log(nsub / ni_cm3)
        fit.nsub, fit.vfb, fit.c_fb, fit.phi_b = nsub, vfb, c_fb, phi_b
        fit.vth = vfb + s * (2.0 * phi_b + math.sqrt(2.0 * Q_E * eps_s * nsub * 2.0 * phi_b) / cox_a)
    if fit.area_cm2 is not None and fit.dep_points < MIN_FIT_POINTS:
        raise FitError(f"fewer than {MIN_FIT_POINTS} points in depletion (band bending 4 kT/q .. 2 phi_B - 3 kT/q); "
                       "use a finer bias step")
    return fit


# -- split C-V fit ---------------------------------------------------------------------------------------------------


@dataclass
class SplitFit:
    """Result of ``split_fit``: channel sign ``s`` (+1: inversion at positive bias), overlap ``floor`` (F),
    extrapolated ``plateau`` (F), the plateau window, the onset ``vth`` (V)."""

    s: float
    floor: float
    plateau: float
    window: tuple[float, float]
    points: int
    r2: float
    vth: float | None
    warnings: list[str] = field(default_factory=list)


def _local_second_derivative(v: np.ndarray, c: np.ndarray, k: int = 2) -> np.ndarray:
    out = np.full(c.size, np.nan)
    for i in range(c.size):
        lo, hi = max(0, i - k), min(c.size, i + k + 1)
        if hi - lo >= 4:
            out[i] = 2.0 * float(np.polyfit(v[lo:hi] - v[i], c[lo:hi], 2)[0])
    return out


def split_fit(v: np.ndarray, c: np.ndarray, *, plateau_frac: float = PLATEAU_FRAC) -> SplitFit:
    """The split C-V fit of the module docstring (``v`` ascending, ``c`` parallel F).

    Raises:
        FitError: If the plateau window has too few points or the curve does not rise.
    """
    if v.size < 2 * MIN_FIT_POINTS:
        raise FitError(f"only {v.size} trusted points")
    k = max(1, min(3, v.size // 4))
    s = 1.0 if float(np.median(c[-k:])) >= float(np.median(c[:k])) else -1.0
    xv, xc = (v, c) if s > 0 else (-v[::-1], c[::-1])  # accumulation first, inversion last
    floor = float(np.median(np.sort(xc)[:3]))
    cc = xc - floor
    top = float(cc.max())
    if top <= 0:
        raise FitError("the capacitance does not rise above the accumulation floor")
    plateau = plateau_extrapolation(xv, cc, plateau_frac)
    d2 = _local_second_derivative(xv, cc)
    rising = (cc > 0.01 * top) & (cc < 0.7 * top)
    candidates = np.where(rising & np.isfinite(d2), d2, -np.inf)
    vth: float | None = None
    warnings = ["the charge offset of the plateau fit is at its search limit"] if plateau.at_grid_edge else []
    if np.isfinite(candidates).any() and float(candidates.max()) > 0:
        i = int(np.argmax(candidates))
        vth = float(xv[i])
        if 0 < i < xv.size - 1 and np.isfinite(d2[i - 1]) and np.isfinite(d2[i + 1]):
            y0, y1, y2 = d2[i - 1], d2[i], d2[i + 1]
            den = y0 - 2 * y1 + y2
            if den < 0:
                vth += float(0.5 * (y0 - y2) / den * (xv[i + 1] - xv[i]))
    else:
        warnings.append("no onset of the inversion capacitance found")
    sel = xv[plateau.first:] * (1 if s > 0 else -1)
    return SplitFit(s=s, floor=floor, plateau=plateau.value, window=(float(sel.min()), float(sel.max())),
                    points=plateau.points, r2=plateau.r2, vth=None if vth is None else vth * (1 if s > 0 else -1),
                    warnings=warnings)


# -- shared method plumbing ------------------------------------------------------------------------------------------


def structure_of(d: RunData, structure: Structure) -> Literal["moscap", "split"]:
    """``moscap`` or ``split`` (``auto``: split for the recipes ``mosfet.cgc_cv``/``mosfet.cgd_cv``)."""
    if structure != "auto":
        return structure
    return "split" if d.manifest.recipe_id in SPLIT_RECIPES else "moscap"


def area_cm2(d: RunData, *, split: bool) -> tuple[float | None, str]:
    """The gate area (cm^2) from the run's DUT geometry (``area_um2``, or ``w_um x l_um``) and the field a refusal
    names when it is missing."""
    geometry = d.manifest.dut_geometry
    profile = d.manifest.plan.request.dut_profile or "(none)"
    wanted = "geometry.w_um and geometry.l_um (or geometry.area_um2)" if split else "geometry.area_um2"
    missing = f"DUT profile {profile} has no {wanted}; a human adds the device geometry to the DUT profile"
    if geometry is None:
        return None, missing
    if geometry.area_um2 is not None:
        return geometry.area_um2 * UM2_TO_CM2, missing
    if geometry.w_um is not None and geometry.l_um is not None:
        return geometry.w_um * geometry.l_um * UM2_TO_CM2, missing
    return None, missing


def _params(curve_args: dict[str, object], policy: TrustPolicy, **extra: object) -> dict[str, object]:
    return {**curve_args, **extra, "trust_policy": policy_params(policy)}


def _start(method: str, d: RunData, criteria: TrustPolicy | None, *, freq_hz: float | None, segment: Segment,
           rs_ohm: float, force: bool, **extra: object) -> tuple[Results, Curve | None, list[str]]:
    """Results builder, the curve and the refusal problems (empty when forced, then flagged)."""
    policy = trust_policy(criteria)
    curve = load_curve(d, policy, freq_hz=freq_hz, segment=segment if d.has_segments else None, rs_ohm=rs_ohm)
    out = Results(method, _params({"freq_hz": curve.freq_hz, "segment": segment, "rs_ohm": rs_ohm, "force": force},
                                  policy, **extra))
    if curve.problems and force:
        out.flag(curve.problems)
        return out, curve, []
    return out, curve, list(curve.problems)


def _refuse_all(out: Results, names: Sequence[tuple[str, Unit]], problems: list[str],
                curve: Curve) -> list[ExtractionResult]:
    return [out.refused(name, unit, problems, excluded=curve.excluded) for name, unit in names]


def _fail_all(out: Results, names: Sequence[tuple[str, Unit]], error: str, curve: Curve) -> list[ExtractionResult]:
    return [out.failed(name, unit, error, excluded=curve.excluded) for name, unit in names]


def _no_geometry(out: Results, names: Sequence[tuple[str, Unit]], why: str, curve: Curve) -> list[ExtractionResult]:
    return [out.not_ok(name, unit, "refused", f"Refused: {why}.", excluded=curve.excluded) for name, unit in names]


def _common(curve: Curve, low: float, high: float, points: int) -> dict[str, object]:
    return {"excluded": curve.excluded, "points_used": points, "window": window_of(np.array([low, high]), "V")}


# -- methods ---------------------------------------------------------------------------------------------------------


@validate_call(config=_CALL_CONFIG)
def cv_cox(d: RunData, *, freq_hz: float | None = None, segment: Segment = "fwd", structure: Structure = "auto",
           acc_frac: float = Field(default=ACC_FRAC, gt=0.5, lt=1.0), rs_ohm: float = Field(default=0.0, ge=0.0),
           force: bool = False, criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Oxide capacitance (module docstring): ``cox`` (F; MOS-C accumulation extrapolation, or the split C-V plateau
    ``Cox W L`` with ``c_floor`` the removed overlap), plus ``cox_per_area`` (F/m^2) and ``eot`` (m) with the DUT
    geometry."""
    kind = structure_of(d, structure)
    out, curve, problems = _start("cv_cox", d, criteria, freq_hz=freq_hz, segment=segment, rs_ohm=rs_ohm,
                                  force=force, structure=kind, acc_frac=acc_frac)
    assert curve is not None
    names: list[tuple[str, Unit]] = [("cox", "F")] + ([("c_floor", "F")] if kind == "split" else [])
    if problems:
        return _refuse_all(out, names, problems, curve)
    area, missing = area_cm2(d, split=kind == "split")
    try:
        if kind == "split":
            sf = split_fit(curve.v, curve.c, plateau_frac=acc_frac)
            cox, low, high, points, r2 = sf.plateau, *sf.window, sf.points, sf.r2
            results = [out.ok("cox", cox, "F", fit={"r2": r2, "c_max": float(curve.c.max()) - sf.floor},
                              warnings=sf.warnings, **_common(curve, low, high, points)),
                       out.ok("c_floor", sf.floor, "F", excluded=curve.excluded, points_used=3)]
        else:
            mf = moscap_fit(curve.v, curve.c, area_cm2=None, acc_frac=acc_frac)
            cox, (low, high), points = mf.cox, mf.acc_window, mf.acc_points
            results = [out.ok("cox", cox, "F", fit={"r2": mf.acc_r2, "c_max": float(curve.c.max()),
                                                    "c_max_over_cox": float(curve.c.max()) / cox},
                              **_common(curve, low, high, points))]
    except FitError as exc:
        return _fail_all(out, names, str(exc), curve)
    extra: list[tuple[str, Unit]] = [("cox_per_area", "F/m^2"), ("eot", "m")]
    if area is None:
        return [*results, *_no_geometry(out, extra, missing, curve)]
    per_area = cox / (area * 1e-4)  # F/m^2
    eot = EPS_SIO2 * EPS0_F_CM * 1e2 / per_area  # m
    return [*results, out.ok("cox_per_area", per_area, "F/m^2", fit={"area_cm2": area}, **_common(curve, low, high,
                                                                                                    points)),
            out.ok("eot", eot, "m", fit={"area_cm2": area, "eps_ox_rel": EPS_SIO2}, **_common(curve, low, high,
                                                                                               points))]


def _moscap(method: str, d: RunData, criteria: TrustPolicy | None, names: list[tuple[str, Unit]], *,
            freq_hz: float | None, segment: Segment, acc_frac: float, ni_cm3: float, temperature_k: float,
            rs_ohm: float, force: bool) -> tuple[Results, Curve, MoscapFit | None, list[ExtractionResult]]:
    """Shared start of the geometry-dependent MOS-C methods: the fit, or the refusal/failure results."""
    out, curve, problems = _start(method, d, criteria, freq_hz=freq_hz, segment=segment, rs_ohm=rs_ohm, force=force,
                                  acc_frac=acc_frac, ni_cm3=ni_cm3, temperature_k=temperature_k)
    assert curve is not None
    if problems:
        return out, curve, None, _refuse_all(out, names, problems, curve)
    area, missing = area_cm2(d, split=False)
    if area is None:
        return out, curve, None, _no_geometry(out, names, missing, curve)
    try:
        return out, curve, moscap_fit(curve.v, curve.c, area_cm2=area, acc_frac=acc_frac, ni_cm3=ni_cm3,
                                      temperature_k=temperature_k), []
    except FitError as exc:
        return out, curve, None, _fail_all(out, names, str(exc), curve)


@validate_call(config=_CALL_CONFIG)
def cv_doping_profile(d: RunData, *, freq_hz: float | None = None, segment: Segment = "fwd",
                      acc_frac: float = Field(default=ACC_FRAC, gt=0.5, lt=1.0),
                      ni_cm3: float = Field(default=DEFAULT_NI_CM3, gt=0), temperature_k: float = Field(
                          default=DEFAULT_T_K, gt=0, le=600), rs_ohm: float = Field(default=0.0, ge=0.0),
                      force: bool = False, criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Substrate doping ``nsub`` (cm^-3) from the depletion slope of ``1/C^2`` (module docstring; needs
    ``geometry.area_um2``); ``fit`` holds the depth window (m) and the substrate type (+1 p, -1 n)."""
    names: list[tuple[str, Unit]] = [("nsub", "cm^-3")]
    out, curve, fit, early = _moscap("cv_doping_profile", d, criteria, names, freq_hz=freq_hz, segment=segment,
                                     acc_frac=acc_frac, ni_cm3=ni_cm3, temperature_k=temperature_k, rs_ohm=rs_ohm,
                                     force=force)
    if fit is None:
        return early
    assert fit.nsub is not None and fit.dep_window is not None and fit.depth_m is not None
    info = {"substrate_p": fit.s, "depth_min_m": fit.depth_m[0], "depth_max_m": fit.depth_m[1], "cox_f": fit.cox}
    return [out.ok("nsub", fit.nsub, "cm^-3", fit=info, **_common(curve, *fit.dep_window, fit.dep_points))]


@validate_call(config=_CALL_CONFIG)
def cv_flatband(d: RunData, *, freq_hz: float | None = None, segment: Segment = "fwd",
                acc_frac: float = Field(default=ACC_FRAC, gt=0.5, lt=1.0),
                ni_cm3: float = Field(default=DEFAULT_NI_CM3, gt=0), temperature_k: float = Field(
                    default=DEFAULT_T_K, gt=0, le=600), rs_ohm: float = Field(default=0.0, ge=0.0),
                force: bool = False, criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Flatband voltage ``vfb`` (V) by the flatband capacitance and ``c_fb`` (F) (module docstring; needs
    ``geometry.area_um2``)."""
    names: list[tuple[str, Unit]] = [("vfb", "V"), ("c_fb", "F")]
    out, curve, fit, early = _moscap("cv_flatband", d, criteria, names, freq_hz=freq_hz, segment=segment,
                                     acc_frac=acc_frac, ni_cm3=ni_cm3, temperature_k=temperature_k, rs_ohm=rs_ohm,
                                     force=force)
    if fit is None:
        return early
    assert fit.vfb is not None and fit.c_fb is not None and fit.dep_window is not None
    info = {"cox_f": fit.cox, "nsub_cm3": fit.nsub, "substrate_p": fit.s}
    low, high = min(fit.acc_window[0], fit.dep_window[0]), max(fit.acc_window[1], fit.dep_window[1])
    common = _common(curve, low, high, fit.acc_points + fit.dep_points)
    return [out.ok("vfb", fit.vfb, "V", fit=info, **common), out.ok("c_fb", fit.c_fb, "F", fit=info, **common)]


@validate_call(config=_CALL_CONFIG)
def cv_vth(d: RunData, *, freq_hz: float | None = None, segment: Segment = "fwd", structure: Structure = "auto",
           acc_frac: float = Field(default=ACC_FRAC, gt=0.5, lt=1.0),
           ni_cm3: float = Field(default=DEFAULT_NI_CM3, gt=0), temperature_k: float = Field(
               default=DEFAULT_T_K, gt=0, le=600), rs_ohm: float = Field(default=0.0, ge=0.0),
           force: bool = False, criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """Threshold voltage ``vth`` (V): MOS-C from the fitted electrostatics (needs ``geometry.area_um2``), split C-V
    from the onset of the inversion capacitance (module docstring)."""
    names: list[tuple[str, Unit]] = [("vth", "V")]
    if structure_of(d, structure) == "split":
        out, curve, problems = _start("cv_vth", d, criteria, freq_hz=freq_hz, segment=segment, rs_ohm=rs_ohm,
                                      force=force, structure="split", acc_frac=acc_frac)
        assert curve is not None
        if problems:
            return _refuse_all(out, names, problems, curve)
        try:
            sf = split_fit(curve.v, curve.c, plateau_frac=acc_frac)
        except FitError as exc:
            return _fail_all(out, names, str(exc), curve)
        if sf.vth is None:
            return _fail_all(out, names, "; ".join(sf.warnings), curve)
        return [out.ok("vth", sf.vth, "V", fit={"method_onset": 1.0, "plateau_f": sf.plateau, "floor_f": sf.floor},
                       excluded=curve.excluded, points_used=int(curve.v.size),
                       window=window_of(curve.v, "V"), warnings=sf.warnings)]
    out, curve, fit, early = _moscap("cv_vth", d, criteria, names, freq_hz=freq_hz, segment=segment,
                                     acc_frac=acc_frac, ni_cm3=ni_cm3, temperature_k=temperature_k, rs_ohm=rs_ohm,
                                     force=force)
    if fit is None:
        return early
    assert fit.vth is not None and fit.dep_window is not None
    info = {"vfb_v": fit.vfb, "nsub_cm3": fit.nsub, "cox_f": fit.cox, "phi_b_v": fit.phi_b, "substrate_p": fit.s}
    return [out.ok("vth", fit.vth, "V", fit=info, **_common(curve, *fit.dep_window, fit.dep_points))]


@validate_call(config=_CALL_CONFIG)
def cv_hysteresis(d: RunData, *, freq_hz: float | None = None, acc_frac: float = Field(default=ACC_FRAC, gt=0.5,
                                                                                         lt=1.0),
                  ni_cm3: float = Field(default=DEFAULT_NI_CM3, gt=0), temperature_k: float = Field(
                      default=DEFAULT_T_K, gt=0, le=600), rs_ohm: float = Field(default=0.0, ge=0.0),
                  force: bool = False, criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """C-V hysteresis of a double sweep: ``hysteresis`` = ``vfb_rev - vfb_fwd`` (V) at the flatband capacitance of
    the ``fwd`` branch (mid level without an area; module docstring)."""
    names: list[tuple[str, Unit]] = [("hysteresis", "V"), ("vfb_fwd", "V"), ("vfb_rev", "V")]
    if not d.has_segments:
        policy = trust_policy(criteria)
        out = Results("cv_hysteresis", {"force": force, "trust_policy": policy_params(policy)})
        return [out.failed(n, u, f"run {d.run_id} is a single sweep; hysteresis needs sweep_mode double",
                           excluded={}) for n, u in names]
    out, fwd, problems = _start("cv_hysteresis", d, criteria, freq_hz=freq_hz, segment="fwd", rs_ohm=rs_ohm,
                                force=force, acc_frac=acc_frac)
    assert fwd is not None
    rev = load_curve(d, trust_policy(criteria), freq_hz=freq_hz, segment="rev", rs_ohm=rs_ohm)
    problems = problems + ([] if force else rev.problems)
    if force and rev.problems:
        out.flag(rev.problems)
    if problems:
        return _refuse_all(out, names, problems, fwd)
    area, _ = area_cm2(d, split=False)
    try:
        fit = moscap_fit(fwd.v, fwd.c, area_cm2=area, acc_frac=acc_frac, ni_cm3=ni_cm3, temperature_k=temperature_k)
    except FitError as exc:
        return _fail_all(out, names, str(exc), fwd)
    if fit.c_fb is not None and fit.vfb is not None:
        level, near, how = fit.c_fb, fit.vfb, "flatband capacitance"
    else:
        level = 0.5 * (float(fwd.c.max()) + float(fwd.c.min()))
        near = _crossing(fwd.v, fwd.c, level, float(np.median(fwd.v))) or float(np.median(fwd.v))
        how = "mid level (Cmax + Cmin)/2: no geometry.area_um2"
    v_fwd, v_rev = _crossing(fwd.v, fwd.c, level, near), _crossing(rev.v, rev.c, level, near)
    if v_fwd is None or v_rev is None:
        return _fail_all(out, names, f"a branch does not cross the {how} {level:.4g} F", fwd)
    info = {"level_f": level, "cox_f": fit.cox}
    common = {"excluded": excluded_counts(pd.concat([fwd.rows.reasons, rev.rows.reasons])),
              "points_used": int(fwd.v.size + rev.v.size), "window": window_of(np.array([v_fwd, v_rev]), "V")}
    warnings = [] if fit.c_fb is not None else [f"crossings at the {how}"]
    return [out.ok("hysteresis", v_rev - v_fwd, "V", fit=info, warnings=warnings, **common),
            out.ok("vfb_fwd", v_fwd, "V", fit=info, warnings=warnings, **common),
            out.ok("vfb_rev", v_rev, "V", fit=info, warnings=warnings, **common)]


@validate_call(config=_CALL_CONFIG)
def impedance_convert(d: RunData, *, to: Model = "cs_rs", series_r: SeriesR = "none",
                      rs_ohm: float | None = Field(default=None, ge=0.0), at_v: float | None = None,
                      segment: Segment = "fwd", force: bool = False,
                      criteria: TrustPolicy | None = None) -> list[ExtractionResult]:
    """The readings as the pair ``to`` at one point per frequency, optionally after removing a series resistance
    (module docstring); ``rs`` (Ohm) is reported when one was removed."""
    if series_r == "value" and rs_ohm is None:
        raise InvalidInputError("impedance_convert: series_r value needs rs_ohm")
    policy = trust_policy(criteria)
    out = Results("impedance_convert", {"to": to, "series_r": series_r, "rs_ohm": rs_ohm, "at_v": at_v,
                                        "segment": segment, "force": force, "trust_policy": policy_params(policy)})
    results: list[ExtractionResult] = []
    for freq in frequencies(d):
        curve = load_curve(d, policy, freq_hz=freq, segment=segment if d.has_segments else None, rs_ohm=0.0)
        names: list[tuple[str, Unit]] = [(q.lower(), UNITS[q]) for q in PAIRS[to]]
        if series_r != "none":
            names.append(("rs", "Ohm"))
        if curve.problems and not force:
            results += [out.refused(n, u, curve.problems, excluded=curve.excluded) for n, u in names]
            continue
        if curve.problems:
            out.flag(curve.problems)
        if curve.v.size == 0:
            results += [out.failed(n, u, f"no trusted point at {freq:g} Hz", excluded=curve.excluded)
                        for n, u in names]
            continue
        y = curve.g + 1j * curve.omega * curve.c
        rs = 0.0
        if series_r == "accumulation":
            top = int(np.argmax(curve.c))
            rs = accumulation_rs(float(curve.c[top]), float(curve.g[top]), curve.omega)
        elif series_r == "value":
            rs = float(rs_ohm or 0.0)
        y = remove_series_r(y, rs)
        spot = bool(np.allclose(curve.v, curve.v[0]))
        if spot:
            chosen = np.arange(y.size)
        else:
            index = int(np.argmin(np.abs(curve.v - at_v))) if at_v is not None else int(np.argmax(curve.c))
            chosen = np.array([index])
        values = from_admittance(to, y[chosen], np.full(chosen.size, curve.omega))
        info: dict[str, float] = {"freq_hz": freq, "dc_v": float(np.mean(curve.v[chosen]))}
        for quantity, array in values.items():
            stats = {**info, "std": float(np.std(array, ddof=1))} if array.size > 1 else info
            results.append(out.ok(quantity.lower(), float(np.mean(array)), UNITS[quantity], fit=stats,
                                  excluded=curve.excluded, points_used=int(array.size)))
        if series_r != "none":
            results.append(out.ok("rs", rs, "Ohm", fit=info, excluded=curve.excluded, points_used=1))
    return results


# -- plots -----------------------------------------------------------------------------------------------------------


def render_cv(d: RunData, *, model: Model | None = None, criteria: TrustPolicy | None = None) -> PlotSet:
    """Render the C-V plots of ``d`` (module docstring) as a ``PlotSet``; nothing is written."""
    policy = trust_policy(criteria)
    role, primary, secondary = pair_of(d)
    table = d.table
    levels = trust_levels(table, policy).to_numpy()
    omega = 2.0 * math.pi * table[FREQ_HZ].to_numpy(dtype=float)
    y = to_admittance(primary, secondary, table[f"{role}_{primary}"].to_numpy(dtype=float),
                      table[f"{role}_{secondary}"].to_numpy(dtype=float), omega)
    target = model or next(k for k, pair in PAIRS.items() if pair == (primary, secondary))
    values = from_admittance(target, y, omega)
    first, second = PAIRS[target]
    shown = {first: values[first], second: values[second] / omega if second == "G" else values[second]}
    labels = {first: f"{first} ({UNITS[first]})", second: "G/w (F)" if second == "G" else f"{second} "
                                                                                         f"({UNITS[second]})"}
    freqs = frequencies(d)
    segments = list(pd.unique(table[SEGMENT])) if SEGMENT in table.columns else [None]
    dc = table[DC_V].to_numpy(dtype=float)
    x_name = (T_S if T_S in table.columns else AC_VRMS if len(pd.unique(table[AC_VRMS])) > 1
              else FREQ_HZ if len(pd.unique(table[DC_V])) == 1 else DC_V)
    spot = x_name == FREQ_HZ
    title = f"{d.run_id} {d.manifest.recipe_id} ({'SIMULATED' if d.manifest.simulated else 'measured'})"
    plots: list[RenderedPlot] = []
    warnings: list[str] = []
    x_values = table[x_name].to_numpy(dtype=float)
    x_labels = {T_S: "t_s (s)", AC_VRMS: f"{AC_VRMS} (V rms)", FREQ_HZ: "frequency (Hz)", DC_V: f"{DC_V} (V)"}
    figure = new_figure(width_in=6.5, height_in=6.0)
    skipped = 0
    for panel, quantity in enumerate((first, second)):
        axes = figure.add_subplot(2, 1, panel + 1)
        for freq in ([None] if spot else freqs):
            for segment in segments:
                mask = np.ones(len(table), dtype=bool)
                if freq is not None:
                    mask &= np.isclose(table[FREQ_HZ].to_numpy(dtype=float), freq)
                if segment is not None:
                    mask &= (table[SEGMENT] == segment).to_numpy()
                xv, yv, lv = x_values[mask], shown[quantity][mask], levels[mask]
                drawable = np.isfinite(xv) & np.isfinite(yv) & (np.abs(yv) < INVALID_ABOVE)
                skipped += int((~drawable).sum())
                ok = drawable & (lv == "ok")
                label = " ".join(x for x in (f"{freq:g} Hz" if freq else "", segment or "") if x) or None
                line = axes.plot(xv[ok], yv[ok], "-" if not spot else "o-", linewidth=1.2, label=label)
                color = line[0].get_color()
                for level, marker in (("limited", "o"), ("untrusted", "x")):
                    pick = drawable & (lv == level)
                    if pick.any():
                        axes.plot(xv[pick], yv[pick], marker, mfc="none", color=color, markersize=5)
        if spot:
            axes.set_xscale("log")
        axes.set_xlabel(x_labels[x_name])
        axes.set_ylabel(labels[quantity])
        axes.grid(True, alpha=0.3)
        if len(freqs) * len(segments) > 1 and not spot:
            axes.legend(fontsize=7)
    figure.suptitle(title, fontsize=9)
    if skipped:
        warnings.append(f"{skipped} point(s) not drawn (invalid data)")
    plots.append(RenderedPlot(name={T_S: "ct", AC_VRMS: "cv-ac", FREQ_HZ: "cf", DC_V: "cv"}[x_name],
                              png=figure_png(figure)))
    if x_name == DC_V and structure_of(d, "auto") == "moscap" and first in ("Cp", "Cs"):
        figure = new_figure(width_in=6.5, height_in=3.5)
        axes = figure.add_subplot(1, 1, 1)
        c = values[first]
        for freq in freqs:
            for segment in segments:
                mask = np.isclose(table[FREQ_HZ].to_numpy(dtype=float), freq) & (levels == "ok") & (c > 0)
                if segment is not None:
                    mask &= (table[SEGMENT] == segment).to_numpy()
                axes.plot(dc[mask], 1.0 / c[mask] ** 2, "-", linewidth=1.2,
                          label=" ".join(x for x in (f"{freq:g} Hz", segment or "") if x))
        axes.set_xlabel(f"{DC_V} (V)")
        axes.set_ylabel(f"1/{first}^2 (1/F^2)")
        axes.grid(True, alpha=0.3)
        figure.suptitle(title, fontsize=9)
        plots.append(RenderedPlot(name="cv-inverse-square", png=figure_png(figure)))
    return PlotSet(plots=tuple(plots), x=x_name, y=(f"{role}_{primary}", f"{role}_{secondary}"), scale="linear",
                   warnings=tuple(warnings))


@validate_call(config=_CALL_CONFIG)
def plot_cv(d: RunData, *, model: Model | None = None, out_dir: Path | None = None,
            criteria: TrustPolicy | None = None) -> list[Path]:
    """Render the C-V plots of ``d`` into ``out_dir`` (default ``work/<run_id>/plots/``) and return the PNG paths
    (agent scripts; ``analyze_run`` stores them in the run folder instead)."""
    rendered = render_cv(d, model=model, criteria=criteria)
    target = out_dir if out_dir is not None else work_dir_for(d.run_id) / "plots"
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for plot in rendered.plots:
        path = target / f"{plot.name}.png"
        path.write_bytes(plot.png)
        paths.append(path)
    return paths


@validate_call(config=_CALL_CONFIG)
def plot_cv_method(d: RunData, *, model: Model | None = None, criteria: TrustPolicy | None = None) -> PlotSet:
    """The registered ``plot_cv`` method: ``render_cv`` with JSON options; the caller stores the ``PlotSet``."""
    return render_cv(d, model=model, criteria=criteria)


__all__ = [
    "FitError",
    "MoscapFit",
    "SplitFit",
    "accumulation_rs",
    "convert_table",
    "cv_cox",
    "cv_doping_profile",
    "cv_flatband",
    "cv_hysteresis",
    "cv_vth",
    "from_admittance",
    "impedance_convert",
    "moscap_fit",
    "plot_cv",
    "plot_cv_method",
    "remove_series_r",
    "render_cv",
    "split_fit",
    "to_admittance",
]

