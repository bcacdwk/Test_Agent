"""Diode forward fit and forward voltage (blueprint 2.8 ``diode_fit``; WP7.2 ``forward_voltage``; card ``diode-iv``).

Definition (the source of knowledge file ``06-analysis-extraction.md``; change both together): on the forward
branch (``x`` > 0 and ``y`` > 0; defaults: the swept source voltage and the measured current of the same role, e.g.
``anode_V``/``anode_I``) the Shockley diode with series resistance satisfies

    V = n·U_T·ln(I/Is) + Rs·I        (I ≫ Is; U_T = k·T/q at ``temperature_k``)

which is linear in the unknowns (n·U_T, -n·U_T·ln Is, Rs). One linear least-squares fit of V against
(ln I, 1, I) over the fit window gives the ideality **n**, the saturation current **Is** and the series resistance
**Rs** (results ``n`` (1), ``is`` (A), ``rs`` (Ohm)), with r2 and the rms voltage residual in ``fit``.

Fit window: forward points with ``i_min_a`` ≤ I ≤ ``i_max_a``. Default ``i_min_a``: 100 x the larger of the noise
estimate of the reverse branch and the shunt leakage G·V at that forward voltage (G = median |I/V| of the reverse
points below -0.1 V), so neither noise nor leakage biases n by more than about 1 %; 1 nA when the run has no reverse
branch. Default ``i_max_a``: the largest trusted forward current. The window needs at least ``MIN_POINTS`` points
spanning at least one decade of current. Compliance (``C``/``T``) points are excluded like everywhere; the reverse
branch (and with it any breakdown) never enters the fit. Trust and refusal as every method (``mosfet.py`` docstring):
untrusted points or a noise-dominated current refuse the call unless ``force``.

Both methods take the run's I-V columns by default from the sweep: a voltage sweep (``basic.diode_iv``) gives the
swept source voltage ``x`` and the measured current ``y`` of the same role; a current sweep (``basic.iv_force_i``,
``WI``) gives the measured voltage ``x`` and the forced source current ``y`` of the swept role. ``x``/``y`` override.

**Forward voltage** (``forward_voltage``, result ``vf`` in V): the voltage at which the forward current reaches
``i_a`` (default the plan parameter ``i_param`` when given, else 1 mA), interpolated linearly in log10 I between
the two trusted forward points (I > 0) that bracket it, walking up in current; ``fit`` names the bracketing currents.
Fails when no trusted forward point lies on each side of ``i_a``. The dummy rows after an automatic abort (``V`` data
after the first compliance, e.g. a current sweep reaching its voltage compliance) count as ``aborted``, not as
untrusted, as in ``leakage_at``: a voltage read before the stop stays valid.
"""

from __future__ import annotations

from typing import Annotated

import numpy as np
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    analysed_rows,
    policy_params,
    sweep_columns,
    trust_policy,
    window_of,
)
from b1500_test_agent.analysis.dataset import RunData, Segment, parse_value_column
from b1500_test_agent.analysis.quality import noise_sigma
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy

BOLTZMANN_OVER_Q = 8.617333262e-5
"""k/q in V/K."""

MIN_POINTS = 5
LEAKAGE_MARGIN = 100.0
"""The fit window starts where the current exceeds noise and shunt leakage by this factor."""

DEFAULT_I_MIN_A = 1e-9
"""Lower window edge when the run has no reverse branch to estimate noise and leakage from."""

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
Amps = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Kelvin = Annotated[float, Field(gt=0, le=1000)]


@validate_call(config=_CALL_CONFIG)
def diode_fit(
    d: RunData,
    *,
    i_min_a: Amps | None = None,
    i_max_a: Amps | None = None,
    temperature_k: Kelvin = 300.0,
    segment: Segment = "fwd",
    force: bool = False,
    x: str | None = None,
    y: str | None = None,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Ideality n, saturation current Is and series resistance Rs from the forward branch (module docstring).
    Returns ``n``, ``is`` and ``rs``; one non-ok ``n`` result on refusal or failure."""
    policy = trust_policy(criteria)
    x, y = iv_columns(d, x, y, "diode_fit")
    r = analysed_rows(d, x, y, policy, segment=segment)
    params = {"i_min_a": i_min_a, "i_max_a": i_max_a, "temperature_k": temperature_k, "segment": segment,
              "force": force, "x": x, "y": y, "trust_policy": policy_params(policy)}
    out = Results("diode_fit", params)
    problems = r.problems(f"segment {segment}")
    if problems and not force:
        return [out.refused("n", "1", problems, excluded=r.excluded())]
    out.flag(problems)
    xs, ys = r.xs, r.ys
    forward = (xs > 0) & (ys > 0)
    reverse = xs < -0.1
    lower_edge = _lower_edge(xs, ys, reverse, i_min_a)
    upper = i_max_a if i_max_a is not None else float(ys[forward].max()) if forward.any() else 0.0
    chosen = np.flatnonzero(forward & (ys >= lower_edge(xs)) & (ys <= upper))
    if chosen.size < MIN_POINTS:
        return [out.failed("n", "1", f"Only {chosen.size} forward point(s) inside the fit window (I from "
                           f"{float(np.min(lower_edge(xs[forward]))) if forward.any() else 0.0:.3g} A); diode_fit "
                           f"needs {MIN_POINTS}. Extend the forward sweep or set i_min_a.", excluded=r.excluded())]
    fv, fi = xs[chosen], ys[chosen]
    if np.log10(fi.max() / fi.min()) < 1.0:
        return [out.failed("n", "1", "The fit window spans less than one decade of current.",
                           excluded=r.excluded())]
    basis = np.column_stack([np.log(fi), np.ones_like(fi), fi])
    scale = np.abs(basis).max(axis=0)
    coeffs, *_ = np.linalg.lstsq(basis / scale, fv, rcond=None)
    a, b, rs = (float(c) for c in coeffs / scale)
    residual = fv - (basis @ (coeffs / scale))
    spread = float(np.sum((fv - fv.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual**2)) / spread if spread > 0 else 1.0
    r.use(chosen)
    excluded = r.excluded()
    if a <= 0:
        return [out.failed("n", "1", "The fitted n·U_T is not positive: the forward branch is not exponential.",
                           excluded=excluded)]
    ut = BOLTZMANN_OVER_Q * temperature_k
    n = a / ut
    i_s = float(np.exp(-b / a))
    window = window_of(fv, "V")
    fit = {"n_ut": a, "r2": r2, "rms_residual_v": float(np.sqrt(np.mean(residual**2))), "i_low": float(fi.min()),
           "i_high": float(fi.max()), "temperature_k": temperature_k}
    warnings = []
    if rs < 0:
        warnings.append(f"Fitted Rs {rs:.3g} Ohm < 0: series resistance not resolved (the window's I·Rs drop is "
                        "below the fit's resolution); extend the forward sweep to higher current.")
    if float(fi.max()) * max(rs, 0.0) < 0.1 * a:
        warnings.append("The largest current's I·Rs drop is below 0.1 n·U_T; Rs is poorly determined.")
    used = int(chosen.size)
    return [
        out.ok("n", n, "1", excluded=excluded, points_used=used, window=window, fit=fit),
        out.ok("is", i_s, "A", excluded=excluded, points_used=used, window=window, fit=fit),
        out.ok("rs", rs, "Ohm", excluded=excluded, points_used=used, window=window, fit=fit, warnings=warnings),
    ]


def _lower_edge(xs: np.ndarray, ys: np.ndarray, reverse: np.ndarray, i_min_a: float | None):
    """The window's lower current edge as a function of the forward voltage (see the module docstring)."""
    if i_min_a is not None:
        return lambda v: np.full_like(np.asarray(v, dtype=float), i_min_a)
    if int(reverse.sum()) < 3:
        return lambda v: np.full_like(np.asarray(v, dtype=float), DEFAULT_I_MIN_A)
    sigma = noise_sigma(ys[reverse]) or 0.0
    conductance = float(np.median(np.abs(ys[reverse] / xs[reverse])))
    return lambda v: LEAKAGE_MARGIN * np.maximum(sigma, conductance * np.abs(np.asarray(v, dtype=float)))


DEFAULT_VF_CURRENT_A = 1e-3
"""Current at which ``forward_voltage`` reports Vf without ``i_a``/``i_param`` (1 mA)."""


def iv_columns(d: RunData, x: str | None, y: str | None, method: str) -> tuple[str, str]:
    """Voltage ``x`` and current ``y`` columns of a single-terminal I-V (module docstring): the voltage sweep's
    columns (``sweep_columns``), or, when the run swept a current (a varying ``<role>_I`` source column), that
    current and the measured voltage of the same role."""
    if x is None and y is None:
        forced = [c for c in d.source_columns if c.endswith("_I") and d.table[c].nunique() > 1]
        if forced:
            y = max(forced, key=lambda c: int(d.table[c].nunique()))
            parsed = parse_value_column(y)
            same = f"{parsed[0]}_V" if parsed else ""
            voltages = [c for c in d.measured_columns if c.endswith("_V")]
            if same in voltages:
                x = same
            elif len(voltages) == 1:
                x = voltages[0]
            else:
                raise InvalidInputError(f"{method}: cannot choose the voltage column of run {d.run_id} among "
                                        f"{voltages}; pass x=<column>.")
    return sweep_columns(d, x, y, method)


@validate_call(config=_CALL_CONFIG)
def forward_voltage(
    d: RunData,
    *,
    i_a: Amps | None = None,
    i_param: str | None = None,
    segment: Segment = "fwd",
    force: bool = False,
    x: str | None = None,
    y: str | None = None,
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """Forward voltage at a current (module docstring): one ``ExtractionResult`` ``vf`` (V)."""
    policy = trust_policy(criteria)
    x, y = iv_columns(d, x, y, "forward_voltage")
    target, source = _target_current(d, i_a, i_param)
    r = analysed_rows(d, x, y, policy, segment=segment, abort_aware=True)
    out = Results("forward_voltage", {"i_a": target, "i_from": source, "segment": segment, "force": force, "x": x,
                                      "y": y, "trust_policy": policy_params(policy)})
    problems = r.problems(f"segment {segment}")
    if problems and not force:
        return out.refused("vf", "V", problems, excluded=r.excluded())
    out.flag(problems)
    xs, ys = r.xs, r.ys
    forward = np.flatnonzero(ys > 0)
    if forward.size < 2:
        return out.failed("vf", "V", f"Only {forward.size} trusted forward point(s) (I > 0) in segment {segment}.",
                          excluded=r.excluded())
    order = forward[np.argsort(ys[forward], kind="stable")]
    currents = ys[order]
    above = np.flatnonzero(currents >= target)
    if not above.size or above[0] == 0:
        return out.failed("vf", "V", f"The trusted forward current ({currents.min():.3g}..{currents.max():.3g} A) "
                          f"does not bracket {target:.3g} A; extend the sweep.", excluded=r.excluded())
    hi = int(above[0])
    lo = hi - 1
    i0, i1 = order[lo], order[hi]
    frac = ((np.log10(target) - np.log10(currents[lo])) / (np.log10(currents[hi]) - np.log10(currents[lo]))
            if currents[hi] > currents[lo] else 1.0)
    value = float(xs[i0] + frac * (xs[i1] - xs[i0]))
    r.use([int(i0), int(i1)])
    warnings = []
    if xs[i1] < xs[i0]:
        warnings.append("The voltage falls between the bracketing points (non-monotonic forward branch).")
    return out.ok("vf", value, "V", excluded=r.excluded(), points_used=2, window=window_of(xs[[i0, i1]], "V"),
                  fit={"i_a": target, "i_below": float(currents[lo]), "i_above": float(currents[hi])},
                  warnings=warnings)


def _target_current(d: RunData, i_a: float | None, i_param: str | None) -> tuple[float, str]:
    if i_a is not None:
        return i_a, "argument"
    if i_param is not None:
        quantity = d.param(i_param)
        if quantity is None or not quantity.is_number or quantity.unit != "A":
            raise InvalidInputError(f"forward_voltage: plan parameter {i_param!r} of run {d.run_id} is not a current "
                                    "in A; pass i_a=<amperes>.")
        value = quantity.as_float()
        if not value > 0:
            raise InvalidInputError(f"forward_voltage: plan parameter {i_param!r} must be a positive current.")
        return value, f"plan.resolved_params.{i_param}"
    return DEFAULT_VF_CURRENT_A, "default"
