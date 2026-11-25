"""PUND analysis of ferroelectric capacitor runs (blueprint v2 2.10 ``nvm.py`` row: ``pund_polarization``,
``plot_pund``; WP10.6; the module is separate from ``nvm.py`` only to keep that file small): ``fecap.pund`` (kind
``wgfmu_waveform``, builder ``pund``) and ``fecap.endurance_pund`` (kind ``pulse_read``, WGFMU PUND reads at
endurance checkpoints).

Definitions (the single source of the section "PUND" of knowledge file ``06b-analysis-time-pulse.md`` of skill
``b1500-test``; change both together):

- **Data.** One PUND read = the rows of events ``P``, ``U``, ``N``, ``D`` (one group per ``cycle`` when the table has
  that column, e.g. the endurance checkpoints): per row the time ``t_s``, the forcing voltage ``v`` (default the
  ``_V`` source column that varies: the programmed top-electrode level at the sample) and the measured current ``i``
  (default the only measured ``_I`` column: the bottom electrode). Each sample is the mean current over one
  sampling interval ``dt`` (the median spacing of ``t_s`` within the pulse), so the charge a pulse moves up to sample
  ``k`` is ``Q(k) = s sum_{j<=k} I_j dt``. The sign ``s`` orients the current so that charge follows voltage: the
  sign of the U pulse's extreme charge times the sign of its voltage (a capacitor's displacement charge has the
  voltage's sign whichever electrode is measured).
- **Remanent polarization** ``pr`` (uC/cm^2): ``Pr+ = (Q_P - Q_U) / 2A`` with the whole-pulse charges (the switched
  charge stays, the dielectric and reversible charge return), ``Pr- = -(Q_N - Q_D) / 2A``; ``pr`` = their mean
  (``fit``: ``pr_pos``, ``pr_neg``, ``q_switch_c`` = the mean switched charge ``2 Pr A`` in C). Needs the area
  (``geometry.area_um2`` of the DUT profile, or option ``area_um2``).
- **Linear dielectric** ``c_lin`` (F): the slope of ``Q`` against ``V`` of the U and D pulses (which do not switch)
  on their rising part between ``c_window`` = (10 %, 50 %) of their peak |V| by least squares; the mean of the two.
- **Saturation polarization** ``ps`` (uC/cm^2): the polarization at the peak field reached from the opposite
  remanent state, the dielectric charge removed: ``Ps+ = ((Qmax_P + Qmax_U) / 2 - C_lin |V_P|) / A`` with ``Qmax``
  the largest charge during the pulse (at the end of its rise or flat top), ``Ps-`` alike from N and D; ``ps`` =
  their mean.
- **Coercive voltage and field**: the switching current ``s (I_P - I_U)`` (sample by sample: P and U see the same
  voltage) peaks at ``Vc+``, ``s (I_N - I_D)`` at ``Vc-`` (a parabola through the five samples around each peak);
  ``vc = (Vc+ - Vc-) / 2`` (V), ``v_imprint = (Vc+ + Vc-) / 2`` (V), ``ec = vc / t`` (MV/cm) with the film thickness
  ``t`` (``geometry.tox_nm`` or option ``thickness_nm``). The peak needs a triangular or trapezoid ramp (a step has
  no voltage at which it switches): a peak at a ramp end is flagged.
- **Trust**: every sample of a read enters the integrals, so a read with an untrusted sample (``V``: the WGFMU range
  saturated) is refused unless ``force``; limited samples (``C``/``T``, an SMU measurement) are refused alike.
- **Several reads** (endurance): ``pr``, ``ps``, ``ec`` and the other quantities are those of the last usable read
  (its ``cycle`` in ``fit``), plus ``pr_initial`` (the first usable read), ``pr_max``, ``wake_up = pr_max /
  pr_initial - 1``, ``fatigue = 1 - pr_final / pr_max`` and ``cycles_to_failure`` (the first cycle count after the
  maximum where Pr falls below ``fail_fraction`` x ``pr_max``, interpolated in log10 N; never reached: a lower bound
  at the last read). Every value is derived (``ExtractionResult``); the window is the forcing voltage span.

``plot_pund``: the last read's current against time per pulse, its polarization (or charge, without the area)
against voltage (P, U, N, D, each starting from its remanent level), and Pr against cycles for several reads.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import Results, policy_params, trust_policy, window_of
from b1500_test_agent.analysis.dataset import CYCLE, RunData, measured_columns, source_columns, work_dir_for
from b1500_test_agent.analysis.plots import PlotSet, RenderedPlot, figure_png, new_figure
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)

PUND_EVENTS = ("P", "U", "N", "D")
EVENT, T_S = "event", "t_s"
UM2_TO_CM2 = 1e-8
UC = 1e6
"""C/cm^2 -> uC/cm^2."""
PEAK_HALF = 2
"""Samples on each side of a peak for the parabola refinement."""


@dataclass
class Pulse:
    """One pulse of a read: times, forcing voltage, oriented current and the sampling interval."""

    t: np.ndarray
    v: np.ndarray
    i: np.ndarray
    dt: float

    @property
    def charge(self) -> np.ndarray:
        """Cumulative charge at the end of each sample (C)."""
        return np.cumsum(self.i) * self.dt

    @property
    def peak_v(self) -> float:
        return float(self.v[int(np.argmax(np.abs(self.v)))])

    def extreme(self, sign: float) -> tuple[float, float]:
        """``(charge, voltage)`` where the oriented charge is largest in the pulse's direction (the end of its rise or
        flat top): the charge at the end of that sample and the voltage there (half a sample past the sample's centre
        on a ramp)."""
        q = sign * self.charge
        k = int(np.argmax(q) if self.peak_v > 0 else np.argmin(q))
        v_end = self.v[k] + 0.5 * (self.v[k] - self.v[k - 1]) if k > 0 else self.v[k]
        return float(q[k]), float(v_end)

    @property
    def rising(self) -> np.ndarray:
        """Indices up to the first sample at the peak |V|."""
        return np.arange(int(np.argmax(np.abs(self.v))) + 1)


@dataclass
class Read:
    """One PUND read (a ``cycle`` group) and what came out of it."""

    cycle: int
    pulses: dict[str, Pulse]
    points: int
    sign: float = 1.0
    values: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _columns(d: RunData, i: str | None, v: str | None) -> tuple[str, str]:
    table = d.table
    for name in (EVENT, T_S):
        if name not in table.columns:
            raise InvalidInputError(f"pund_polarization: run {d.run_id} has no {name!r} column; it needs a PUND run "
                                    "(fecap.pund or fecap.endurance_pund)")
    events = set(table[EVENT].astype(str))
    if not set(PUND_EVENTS) <= events:
        raise InvalidInputError(f"pund_polarization: run {d.run_id} has events {sorted(events)}; a PUND read has "
                                f"{list(PUND_EVENTS)}")
    currents = [c for c in measured_columns(table) if c.endswith("_I")]
    current = i or (currents[0] if len(currents) == 1 else None)
    if current is None or current not in table.columns:
        raise InvalidInputError(f"pund_polarization: give option i (the measured current column; found {currents})")
    pund_rows = table[table[EVENT].astype(str).isin(PUND_EVENTS)]
    varying = [c for c in source_columns(table) if c.endswith("_V") and pund_rows[c].nunique(dropna=True) > 1]
    voltage = v or (varying[0] if len(varying) == 1 else None)
    if voltage is None or voltage not in table.columns:
        raise InvalidInputError(f"pund_polarization: give option v (the forcing voltage column; found {varying})")
    return current, voltage


def _reads(d: RunData, current: str, voltage: str, policy: TrustPolicy, force: bool,
           out: Results) -> tuple[list[Read], list[str]]:
    """Every PUND read of the run in cycle order; reads with untrusted samples are left out (named in the second
    list) unless ``force``."""
    table = d.table
    status = f"{current}_status"
    cycles = table[CYCLE].astype(int) if CYCLE in table.columns else np.zeros(len(table), dtype=int)
    reads: list[Read] = []
    dropped: list[str] = []
    for cycle in sorted({int(c) for c in cycles}):
        rows = table[(np.asarray(cycles) == cycle) & table[EVENT].astype(str).isin(PUND_EVENTS)]
        if rows.empty:
            continue
        bad = [str(s) for s in rows[status].astype(str)] if status in rows.columns else []
        flagged = sorted({s for s in bad if policy.classify(s) != "ok"})
        if flagged and not force:
            dropped.append(f"cycle {cycle}: status {','.join(flagged)} (the integrals need every sample)")
            continue
        if flagged:
            out.flag([f"read of cycle {cycle} has status {','.join(flagged)}"])
        pulses: dict[str, Pulse] = {}
        for name in PUND_EVENTS:
            sub = rows[rows[EVENT].astype(str) == name].sort_values(T_S)
            t = sub[T_S].to_numpy(dtype=float)
            if len(t) < 5:
                dropped.append(f"cycle {cycle}: pulse {name} has {len(t)} samples (at least 5)")
                break
            dt = float(np.median(np.diff(t)))
            pulses[name] = Pulse(t=t, v=sub[voltage].to_numpy(dtype=float), i=sub[current].to_numpy(dtype=float),
                                 dt=dt)
        else:
            reads.append(Read(cycle=cycle, pulses=pulses, points=len(rows)))
    return reads, dropped


def _peak(signal: np.ndarray, v: np.ndarray) -> tuple[float, bool]:
    """Voltage at the maximum of ``signal`` (parabola through the samples around it) and whether it lies at an end."""
    k = int(np.argmax(signal))
    edge = k < PEAK_HALF or k > len(signal) - 1 - PEAK_HALF
    if edge:
        return float(v[k]), True
    idx = np.arange(k - PEAK_HALF, k + PEAK_HALF + 1)
    a, b, _ = np.polyfit(idx - k, signal[idx], 2)
    offset = float(np.clip(-b / (2 * a), -1.0, 1.0)) if a < 0 else 0.0
    return float(np.interp(k + offset, np.arange(len(v)), v)), False


def _c_lin(pulse: Pulse, sign: float, window: tuple[float, float]) -> float | None:
    rising = pulse.rising
    v = pulse.v[rising]
    q = sign * pulse.charge[rising]
    peak = abs(pulse.peak_v)
    sel = (np.abs(v) >= window[0] * peak) & (np.abs(v) <= window[1] * peak)
    if int(sel.sum()) < 3:
        return None
    return float(np.polyfit(v[sel], q[sel], 1)[0])


def _evaluate(read: Read, window: tuple[float, float]) -> None:
    """The per-read quantities (module docstring) in ``read.values`` (charges in C, voltages in V)."""
    p = read.pulses
    u = p["U"]
    q_u = u.charge
    k = int(np.argmax(np.abs(q_u)))
    read.sign = float(np.sign(q_u[k]) * np.sign(u.v[k])) or 1.0
    s = read.sign
    totals = {name: s * float(pulse.charge[-1]) for name, pulse in p.items()}
    extremes = {name: pulse.extreme(s) for name, pulse in p.items()}
    c_values = [c for c in (_c_lin(p["U"], s, window), _c_lin(p["D"], s, window)) if c is not None]
    vc_pos, edge_pos = _peak(s * (p["P"].i - p["U"].i), p["P"].v)
    vc_neg, edge_neg = _peak(-s * (p["N"].i - p["D"].i), p["N"].v)
    if edge_pos or edge_neg:
        read.warnings.append(f"cycle {read.cycle}: the switching current peaks at a ramp end (a step pulse, or the "
                             "amplitude does not reach beyond the coercive voltage): Vc is not resolved")
    read.values.update(q_sw_pos=totals["P"] - totals["U"], q_sw_neg=-(totals["N"] - totals["D"]),
                       q_max_pos=(extremes["P"][0] + extremes["U"][0]) / 2.0,
                       q_max_neg=-(extremes["N"][0] + extremes["D"][0]) / 2.0,
                       v_pos=abs(extremes["P"][1] + extremes["U"][1]) / 2.0,
                       v_neg=abs(extremes["N"][1] + extremes["D"][1]) / 2.0, vc_pos=vc_pos, vc_neg=vc_neg)
    if c_values:
        read.values["c_lin"] = float(np.mean(c_values))
    if len(c_values) < 2:
        read.warnings.append(f"cycle {read.cycle}: too few U/D samples in the c_window to fit the dielectric")


@validate_call(config=_CALL_CONFIG)
def pund_polarization(
    d: RunData,
    *,
    i: str | None = None,
    v: str | None = None,
    c_window: tuple[float, float] = (0.1, 0.5),
    area_um2: float | None = Field(default=None, gt=0),
    thickness_nm: float | None = Field(default=None, gt=0),
    fail_fraction: float = Field(default=0.5, gt=0, lt=1),
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Pr, Ps, Ec (Vc, imprint, C_lin) of a PUND run; over several reads also wake-up, fatigue and cycles to failure
    (module docstring)."""
    if not 0.0 <= c_window[0] < c_window[1] <= 1.0:
        raise InvalidInputError(f"c_window must be 0 <= low < high <= 1 (fractions of the peak |V|), got {c_window}")
    policy = trust_policy(criteria)
    current, voltage = _columns(d, i, v)
    geometry = d.manifest.dut_geometry
    area = area_um2 if area_um2 is not None else (geometry.area_um2 if geometry is not None else None)
    thickness = thickness_nm if thickness_nm is not None else (geometry.tox_nm if geometry is not None else None)
    out = Results("pund_polarization", {"i": current, "v": voltage, "c_window": list(c_window), "area_um2": area,
                                         "thickness_nm": thickness, "fail_fraction": fail_fraction, "force": force,
                                         "trust_policy": policy_params(policy)})
    reads, dropped = _reads(d, current, voltage, policy, force, out)
    out.warnings.extend(f"read left out: {why}" for why in dropped)
    names = [("pr", "uC/cm^2"), ("ps", "uC/cm^2"), ("ec", "MV/cm"), ("vc", "V"), ("v_imprint", "V"), ("c_lin", "F"),
             ("q_switch", "C")]
    if not reads:
        why = "no usable PUND read" + (f" ({'; '.join(dropped)})" if dropped else "")
        outcome = "refused" if dropped and all("status" in w for w in dropped) else "failed"
        return [out.not_ok(n, u, outcome, why, excluded={}) for n, u in names]  # type: ignore[arg-type]
    for read in reads:
        _evaluate(read, c_window)
    last = reads[-1]
    for read in reads:
        out.warnings.extend(read.warnings)
    window = window_of(np.concatenate([p.v for p in last.pulses.values()]), "V")
    results = _quantities(out, last, area, thickness, window, d)
    if len(reads) > 1:
        results += _endurance(out, reads, area, fail_fraction)
    return results


def _area_cm2(area_um2: float | None) -> float | None:
    return None if area_um2 is None else area_um2 * UM2_TO_CM2


def _quantities(out: Results, read: Read, area_um2: float | None, thickness: float | None, window: Any,
                d: RunData) -> list[ExtractionResult]:
    values = read.values
    area = _area_cm2(area_um2)
    used = read.points
    base = {"cycle": float(read.cycle)}
    results: list[ExtractionResult] = []
    q_switch = (values["q_sw_pos"] + values["q_sw_neg"]) / 2.0
    results.append(out.ok("q_switch", q_switch, "C", excluded={}, points_used=used, window=window,
                          fit={**base, "q_pos_c": values["q_sw_pos"], "q_neg_c": values["q_sw_neg"]}))
    profile = d.manifest.plan.request.dut_profile or "(none)"
    if area is None:
        why = (f"DUT profile {profile} has no geometry.area_um2; give options.area_um2 or a human adds the device "
               "geometry to the DUT profile")
        results += [out.not_ok("pr", "uC/cm^2", "refused", "Refused: " + why, excluded={}),
                    out.not_ok("ps", "uC/cm^2", "refused", "Refused: " + why, excluded={})]
    else:
        pr_pos, pr_neg = values["q_sw_pos"] / (2 * area) * UC, values["q_sw_neg"] / (2 * area) * UC
        results.append(out.ok("pr", (pr_pos + pr_neg) / 2.0, "uC/cm^2", excluded={}, points_used=used, window=window,
                              fit={**base, "pr_pos": pr_pos, "pr_neg": pr_neg, "q_switch_c": q_switch,
                                   "area_um2": float(area_um2 or 0.0)}))
        c_lin = values.get("c_lin")
        if c_lin is None:
            results.append(out.failed("ps", "uC/cm^2", "no dielectric fit (see warnings)", excluded={}))
        else:  # (Qmax_P + Qmax_U) / 2 = A Ps + C_lin V (the P pulse adds Pr, the U pulse takes it)
            ps_pos = (values["q_max_pos"] - c_lin * values["v_pos"]) / area * UC
            ps_neg = (values["q_max_neg"] - c_lin * values["v_neg"]) / area * UC
            results.append(out.ok("ps", (ps_pos + ps_neg) / 2.0, "uC/cm^2", excluded={}, points_used=used,
                                  window=window, fit={**base, "ps_pos": ps_pos, "ps_neg": ps_neg, "c_lin_f": c_lin}))
    vc = (values["vc_pos"] - values["vc_neg"]) / 2.0
    fit_v = {**base, "vc_pos": values["vc_pos"], "vc_neg": values["vc_neg"]}
    results.append(out.ok("vc", vc, "V", excluded={}, points_used=used, window=window, fit=fit_v))
    results.append(out.ok("v_imprint", (values["vc_pos"] + values["vc_neg"]) / 2.0, "V", excluded={},
                          points_used=used, window=window, fit=fit_v))
    if thickness is None:
        results.append(out.not_ok("ec", "MV/cm", "refused", f"Refused: DUT profile {profile} has no geometry.tox_nm "
                                  "(the film thickness); give options.thickness_nm or a human adds it", excluded={}))
    else:
        results.append(out.ok("ec", vc / (thickness * 1e-7) / 1e6, "MV/cm", excluded={}, points_used=used,
                              window=window, fit={**fit_v, "thickness_nm": thickness}))
    if "c_lin" in values:
        results.append(out.ok("c_lin", values["c_lin"], "F", excluded={}, points_used=used, window=window,
                              fit=base))
    else:
        results.append(out.failed("c_lin", "F", "too few U/D samples in the c_window", excluded={}))
    return results


def pr_series(reads: Sequence[Read], area_um2: float) -> list[tuple[int, float]]:
    """``(cycle, Pr)`` of evaluated reads (uC/cm^2)."""
    area = area_um2 * UM2_TO_CM2
    return [(r.cycle, (r.values["q_sw_pos"] + r.values["q_sw_neg"]) / (4 * area) * UC) for r in reads]


def _endurance(out: Results, reads: Sequence[Read], area_um2: float | None,
               fail_fraction: float) -> list[ExtractionResult]:
    names = [("pr_initial", "uC/cm^2"), ("pr_max", "uC/cm^2"), ("wake_up", "1"), ("fatigue", "1"),
             ("cycles_to_failure", "1")]
    if area_um2 is None:
        return [out.not_ok(n, u, "refused", "Refused: no geometry.area_um2 (see pr)", excluded={})  # type: ignore[arg-type]
                for n, u in names]
    series = pr_series(reads, area_um2)
    cycles = np.array([max(c, 1) for c, _ in series], dtype=float)
    pr = np.array([p for _, p in series])
    window = window_of(cycles, "1")
    n = len(series)
    k_max = int(np.argmax(pr))
    first, top, last = series[0], series[k_max], series[-1]
    results = [
        out.ok("pr_initial", first[1], "uC/cm^2", excluded={}, points_used=1, fit={"cycle": float(first[0])}),
        out.ok("pr_max", top[1], "uC/cm^2", excluded={}, points_used=n, window=window,
               fit={"cycle_at_max": float(top[0]), "reads": float(n)}),
    ]
    if first[1] <= 0 or top[1] <= 0:
        return [*results, *(out.failed(q, "1", "Pr is not positive: no switching", excluded={})
                            for q in ("wake_up", "fatigue", "cycles_to_failure"))]
    results.append(out.ok("wake_up", top[1] / first[1] - 1.0, "1", excluded={}, points_used=n, window=window,
                          fit={"pr_initial": first[1], "pr_max": top[1]}))
    results.append(out.ok("fatigue", 1.0 - last[1] / top[1], "1", excluded={}, points_used=n, window=window,
                          fit={"pr_max": top[1], "pr_final": last[1], "cycle_final": float(last[0])}))
    criterion = fail_fraction * top[1]
    below = np.nonzero(pr[k_max:] < criterion)[0]
    fit = {"criterion_uc_cm2": criterion}
    if below.size == 0:
        results.append(out.ok("cycles_to_failure", float(cycles[-1]), "1", excluded={}, points_used=n,
                              window=window, fit=fit, bound="lower",
                              warnings=[f"Pr stayed above {criterion:.4g} uC/cm^2 up to the last read: a lower bound"]))
        return results
    k = k_max + int(below[0])
    if k == k_max:
        value = float(cycles[k])
    else:
        l0, l1 = math.log10(cycles[k - 1]), math.log10(cycles[k])
        value = 10.0 ** (l0 + (criterion - pr[k - 1]) * (l1 - l0) / (pr[k] - pr[k - 1]))
    results.append(out.ok("cycles_to_failure", value, "1", excluded={}, points_used=n, window=window, fit=fit))
    return results


# -- plot ------------------------------------------------------------------------------------------------------------


def render_pund(d: RunData, *, i: str | None = None, v: str | None = None, area_um2: float | None = None,
                criteria: TrustPolicy | None = None) -> PlotSet:
    """The PUND plots of ``d`` (module docstring) as a ``PlotSet``."""
    policy = trust_policy(criteria)
    current, voltage = _columns(d, i, v)
    out = Results("plot_pund", {})
    reads, _ = _reads(d, current, voltage, policy, True, out)  # plots never refuse: untrusted reads are drawn too
    if not reads:
        raise InvalidInputError(f"plot_pund: run {d.run_id} has no complete PUND read")
    for read in reads:
        _evaluate(read, (0.1, 0.5))
    geometry = d.manifest.dut_geometry
    area = area_um2 if area_um2 is not None else (geometry.area_um2 if geometry is not None else None)
    last = reads[-1]
    images: list[RenderedPlot] = []
    fig = new_figure()
    ax = fig.add_subplot()
    for name, pulse in last.pulses.items():
        ax.plot((pulse.t - pulse.t[0]) * 1e6, pulse.i * 1e6, label=name)
    ax.set_xlabel("time in pulse (us)")
    ax.set_ylabel(f"{current} (uA)")
    ax.set_title(f"PUND currents, cycle {last.cycle} ({d.run_id})")
    ax.legend()
    images.append(RenderedPlot(name="pund-current", png=figure_png(fig)))
    fig = new_figure()
    ax = fig.add_subplot()
    scale = (1.0 / (area * UM2_TO_CM2) * UC) if area else 1e12
    unit = "uC/cm^2" if area else "pC"
    q_sw = (last.values["q_sw_pos"] + last.values["q_sw_neg"]) / 4.0
    starts = {"P": -q_sw, "U": q_sw, "N": q_sw, "D": -q_sw}
    for name, pulse in last.pulses.items():
        ax.plot(pulse.v, (starts[name] + last.sign * pulse.charge) * scale, label=name)
    ax.set_xlabel(f"{voltage} (V)")
    ax.set_ylabel(f"polarization incl. dielectric ({unit})")
    ax.set_title("PUND P-V (each pulse from its remanent level)")
    ax.legend()
    images.append(RenderedPlot(name="pund-loop", png=figure_png(fig)))
    if len(reads) > 1 and area:
        series = pr_series(reads, area)
        fig = new_figure()
        ax = fig.add_subplot()
        ax.semilogx([max(c, 1) for c, _ in series], [p for _, p in series], "o-")
        ax.set_xlabel("cycles")
        ax.set_ylabel("Pr (uC/cm^2)")
        ax.set_title("Pr versus program/erase cycles")
        images.append(RenderedPlot(name="pund-endurance", png=figure_png(fig)))
    return PlotSet(plots=tuple(images), x=voltage, y=(current,), scale="linear",
                   warnings=tuple(w for r in reads for w in r.warnings))


def plot_pund_method(d: RunData, *, i: str | None = None, v: str | None = None, area_um2: float | None = None,
                     criteria: TrustPolicy | None = None) -> PlotSet:
    """The registered ``plot_pund`` method: ``render_pund`` with JSON options; the caller stores the ``PlotSet``."""
    return render_pund(d, i=i, v=v, area_um2=area_um2, criteria=criteria)


def plot_pund(d: RunData, *, i: str | None = None, v: str | None = None, area_um2: float | None = None,
              out_dir: Path | None = None, criteria: TrustPolicy | None = None) -> list[Path]:
    """Render the PUND plots of ``d`` into ``out_dir`` (default ``work/<run_id>/plots/``) and return the PNG paths.
    For agent scripts; ``analyze_run`` stores them in the run folder instead."""
    rendered = render_pund(d, i=i, v=v, area_um2=area_um2, criteria=criteria)
    target = out_dir if out_dir is not None else work_dir_for(d.run_id) / "plots"
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for plot in rendered.plots:
        path = target / f"{plot.name}.png"
        path.write_bytes(plot.png)
        paths.append(path)
    return paths


__all__ = ["PUND_EVENTS", "plot_pund", "plot_pund_method", "pr_series", "pund_polarization", "render_pund"]
