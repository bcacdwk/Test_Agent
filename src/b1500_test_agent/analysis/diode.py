"""Diode forward fit (blueprint 2.8 ``diode_fit``; card ``diode-iv``).

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
from b1500_test_agent.analysis.dataset import RunData, Segment
from b1500_test_agent.analysis.quality import noise_sigma
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
    x, y = sweep_columns(d, x, y, "diode_fit")
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
