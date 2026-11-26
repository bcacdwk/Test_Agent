"""Charge-pumping analysis (blueprint v2 3.3 ``mosfet.charge_pumping``, WP9.3): ``charge_pumping`` on runs of kind
``spgu_pulse`` whose SMU read the substrate (bulk) current while gate pulse trains ran.

Definitions (the single source of the section "Charge pumping" of knowledge file ``05-reliability-defects.md`` of
skill ``b1500-test``; change both together; Groeseneken et al., IEEE TED 31, 42, 1984, not page-checked):

- **Table.** One row per reading during a train: ``freq_hz`` (the pulse frequency), the gate's programmed base level
  ``x`` (default: the one source ``<role>_V`` column, no status, whose values vary; none = one base level) and the
  measured current ``y`` (default: the measured current of role ``bulk``, else the only measured current).
  Untrusted readings refuse the call unless ``force`` (flagged); limited (``C``/``T``) readings never enter.
- **Icp per frequency.** The readings of one frequency and base level are averaged (``|y|``); a base-level sweep's
  charge-pumping current at that frequency is the maximum over the base levels (the plateau, where the base reaches
  accumulation and the top inversion). ``plateau`` (fit ``plateau_low_v``/``plateau_high_v``): the base levels whose
  ``Icp`` is at least ``plateau_fraction`` (0.9) of the maximum, at the frequency with the most base levels.
- **Charge per cycle.** ``Icp = Qcp·f + I0`` by least squares over the frequencies (at least 2; with one frequency
  ``Qcp = Icp/f``, flagged): ``qcp`` (C, the charge pumped per cycle = ``q·A·D̄it·ΔE``), fit ``offset_a`` (``I0``: the
  frequency-independent leakage, ideally 0), ``r2`` and ``max_deviation`` (the largest ``|Icp - Qcp·f - I0|/Icp``).
  Classification ``linear`` when ``max_deviation <= linearity_tol`` (0.1), else ``nonlinear`` (incomplete pumping at
  high frequency, a geometric component at slow edges, or leakage: see the card).
- ``icp_max`` (A): the largest ``Icp`` (highest frequency).
- **Traps.** With ``area_um2`` (the gate area W·L of the DUT profile geometry): ``nit`` = ``Qcp/(q·A)`` (cm^-2, the
  traps per area swept in the energy window ``ΔE``); with ``delta_e_ev`` too: ``dit`` = ``nit/ΔE`` (cm^-2 eV^-1, the
  mean interface-trap density). ``ΔE`` is an assumption the caller states; nothing here derives it. Textbook estimate:
  ``ΔE ≈ 2 kT ln(1/(v_th n_i σ t_em))`` with ``t_em`` = edge time x |Vth - Vfb| / amplitude; with the assumed σ =
  1e-16 cm², v_th = 1e7 cm/s, n_i = 1e10 cm^-3 and ``t_em`` = 100 ns it gives 2 x 0.0259 eV x ln(1e6) = 0.71 eV at
  300 K (the device's σ is unknown). Without ``delta_e_ev`` ``dit`` is not reported.

Every result is derived (``ExtractionResult``) with the method, its parameters and the readings used; refusals and
failures are results, never exceptions (``InvalidInputError`` only for unusable calls: no ``freq_hz`` column, an
unknown or non-current column).
"""

from __future__ import annotations

from typing import Annotated

import numpy as np
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import Results, analysed_rows, line_fit, policy_params, trust_policy, window_of
from b1500_test_agent.analysis.dataset import FREQ_HZ, RunData, parse_value_column
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy

Q_E = 1.602176634e-19
"""Elementary charge (C)."""

UM2_TO_CM2 = 1.0e-8

DEFAULT_LINEARITY_TOL = 0.1
"""Largest relative deviation of an ``Icp`` from the fitted line for ``linear`` (blueprint v2 10.5: +-10 %)."""

DEFAULT_PLATEAU_FRACTION = 0.9

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Fraction = Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]


def _current_column(d: RunData, y: str | None) -> str:
    measured = [c for c in d.measured_columns if (p := parse_value_column(c)) is not None and p[1] == "I"]
    if y is not None:
        if y not in measured:
            raise InvalidInputError(f"charge_pumping: {y!r} is not a measured current column of run {d.run_id}; "
                                    f"measured currents: {measured}.")
        return y
    if "bulk_I" in measured:
        return "bulk_I"
    if len(measured) == 1:
        return measured[0]
    raise InvalidInputError(f"charge_pumping: run {d.run_id} measures {measured}; name the substrate current with "
                            "option y.")


def _base_column(d: RunData, x: str | None) -> str | None:
    """The gate's programmed base level: ``x``, else the one source ``<role>_V`` column (no status) whose values vary
    (a base-level sweep); ``None`` when none varies (one base level: nothing to group by)."""
    sources = [c for c in d.source_columns if c.endswith("_V")]
    if x is not None:
        if x not in sources:
            raise InvalidInputError(f"charge_pumping: {x!r} is not a source voltage column of run {d.run_id}; "
                                    f"source voltages: {sources}.")
        return x
    varying = [c for c in sources if d.table[c].nunique(dropna=True) > 1]
    if len(varying) > 1:
        raise InvalidInputError(f"charge_pumping: several source voltages vary in run {d.run_id} ({varying}); name "
                                "the gate base level with option x.")
    return varying[0] if varying else None


@validate_call(config=_CALL_CONFIG)
def charge_pumping(
    d: RunData,
    *,
    y: str | None = None,
    x: str | None = None,
    area_um2: Positive | None = None,
    delta_e_ev: Positive | None = None,
    linearity_tol: Fraction = DEFAULT_LINEARITY_TOL,
    plateau_fraction: Fraction = DEFAULT_PLATEAU_FRACTION,
    force: bool = False,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Charge per cycle, its linearity in frequency, the largest ``Icp`` and (with the area) the trap density
    (module docstring). Returns ``qcp`` and ``icp_max`` (+ ``nit``/``dit`` when ``area_um2``/``delta_e_ev`` are
    given); one non-ok ``qcp`` result on refusal or failure."""
    if FREQ_HZ not in d.table.columns:
        raise InvalidInputError(f"charge_pumping: run {d.run_id} has no {FREQ_HZ} column (not a pulse-train read).")
    policy = trust_policy(criteria)
    y = _current_column(d, y)
    base = _base_column(d, x)
    rows = d.rows(None)
    r = analysed_rows(d, FREQ_HZ, y, policy, segment=None, rows=rows)
    out = Results("charge_pumping", {"y": y, "x": base, "area_um2": area_um2, "delta_e_ev": delta_e_ev,
                                     "linearity_tol": linearity_tol, "plateau_fraction": plateau_fraction,
                                     "force": force, "trust_policy": policy_params(policy)})
    problems = r.problems("the readings", noise=False)
    if problems and not force:
        return [out.refused("qcp", "C", problems, excluded=r.excluded())]
    out.flag(problems)
    used = r.rows[r.ok]
    if used.empty:
        return [out.failed("qcp", "C", "No trusted reading.", excluded=r.excluded())]
    keys = [FREQ_HZ, base] if base is not None else [FREQ_HZ]
    means = used.assign(_abs=used[y].abs()).groupby(keys)["_abs"].mean()
    per_f = means.groupby(level=0).max() if base is not None else means
    freqs = per_f.index.to_numpy(dtype=float)
    icp = per_f.to_numpy(dtype=float)
    fit: dict[str, float] = {"frequencies": float(freqs.size)}
    warnings: list[str] = []
    if base is not None:
        counts = means.groupby(level=0).size()
        f_most = float(counts.idxmax())
        curve = means.xs(f_most, level=0)
        top = float(curve.max())
        plateau = curve[curve >= plateau_fraction * top].index.to_numpy(dtype=float)
        if curve.size > 1 and plateau.size:
            fit.update(plateau_low_v=float(plateau.min()), plateau_high_v=float(plateau.max()), plateau_freq_hz=f_most)
    if freqs.size >= 2:
        slope, offset, r2 = line_fit(freqs, icp)
        deviation = float(np.max(np.abs(icp - (slope * freqs + offset)) / np.maximum(icp, 1e-300)))
        fit.update(offset_a=offset, r2=r2, max_deviation=deviation)
        classification = "linear" if deviation <= linearity_tol else "nonlinear"
        if classification == "nonlinear":
            warnings.append(f"Icp deviates from Qcp*f + I0 by up to {deviation:.1%} (> {linearity_tol:.0%}): "
                            "incomplete pumping at high frequency, a geometric component or leakage (see the card).")
    else:
        slope, classification = float(icp[0] / freqs[0]), None
        warnings.append("One frequency only: Qcp = Icp/f without a linearity check (add frequencies).")
    if slope <= 0:
        return [out.failed("qcp", "C", f"Icp does not grow with the frequency (slope {slope:.3g} C): no charge "
                           "pumping (check that the base reaches accumulation and the top inversion).",
                           excluded=r.excluded(), fit=fit)]
    window = window_of(freqs, "Hz")
    excluded = r.excluded()
    results = [out.ok("qcp", slope, "C", excluded=excluded, points_used=len(used), window=window, fit=fit,
                      warnings=warnings, classification=classification),
               out.ok("icp_max", float(icp.max()), "A", excluded=excluded, points_used=len(used), window=window,
                      fit={"freq_hz": float(freqs[int(np.argmax(icp))])})]
    if area_um2 is not None:
        nit = slope / (Q_E * area_um2 * UM2_TO_CM2)
        results.append(out.ok("nit", nit, "cm^-2", excluded=excluded, points_used=len(used), window=window,
                              fit={"area_um2": area_um2}))
        if delta_e_ev is not None:
            results.append(out.ok("dit", nit / delta_e_ev, "cm^-2 eV^-1", excluded=excluded, points_used=len(used),
                                  window=window, fit={"area_um2": area_um2, "delta_e_ev": delta_e_ev},
                                  warnings=[f"Dit assumes the energy window dE = {delta_e_ev:g} eV (caller)."]))
    return results
