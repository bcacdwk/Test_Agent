"""Two-terminal resistance and contact classification (blueprint 2.8 ``resistance``; card ``contact-resistor-check``).

Definition (the source of knowledge file ``06-analysis-extraction.md``; change both together): a straight-line
least-squares fit I = G·V + I0 of the measured current ``y`` against the forced voltage ``x`` (defaults: the source
voltage column that varies most and the measured current of the same role, e.g. ``a_V``/``a_I``) over the trusted
points of ``segment`` gives **R = 1/G** (``resistance``, Ohm), the **linearity** r2 of the fit (``linearity_r2``)
and the **offset current** I0 at 0 V (``offset_current``, A; ``fit["v_offset"]`` = -I0/G). Classification
(``classification`` of the ``resistance`` result), thresholds as options:

- ``short``: the forced terminal reached its compliance (status ``C`` on ``y``): R ≤ |V|/|I| at the first compliance
  point, reported as that upper bound (``bound="upper"``) and nothing is fitted (the sweep was aborted there), when
  that bound is at most ``r_short_ohm``; or a fitted R ≤ ``r_short_ohm``. A compliance stop with a bound above
  ``r_short_ohm`` cannot be classified → ``failed`` (raise the compliance or lower |V| within the card's limits).
- ``open``: the current is noise-dominated (range < ``MIN_SNR`` x noise; the probe measures only the noise floor) →
  R ≥ ΔV / (``MIN_SNR`` x noise), reported as that lower bound (``bound="lower"``); or a fitted R ≥ ``r_open_ohm``.
- ``in_range``: otherwise.

Trust: as every method (``mosfet.py`` docstring), except that the dummy rows after a compliance abort count as
``aborted`` (they carry no data), the compliance point itself is the evidence for ``short`` and a noise-dominated
current is the evidence for ``open`` (not a refusal). Any other untrusted point refuses the call unless ``force``.
A non-positive fitted conductance with a clean signal → ``failed`` (not a resistor: check the wiring).
"""

from __future__ import annotations

from typing import Annotated

import numpy as np
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    analysed_rows,
    first_compliance,
    line_fit,
    policy_params,
    sweep_columns,
    trust_policy,
    window_of,
)
from b1500_test_agent.analysis.dataset import RunData, Segment
from b1500_test_agent.analysis.mosfet import MIN_R2
from b1500_test_agent.analysis.quality import MIN_SNR, noise_sigma
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy

DEFAULT_R_SHORT_OHM = 100.0
"""At or below: ``short`` (a 1 mA compliance at 0.1 V also means R ≤ 100 Ohm)."""

DEFAULT_R_OPEN_OHM = 1e9
"""At or above: ``open`` (1 GOhm; an unlanded HRSMU probe reads far above this)."""

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
Ohms = Annotated[float, Field(gt=0, allow_inf_nan=False)]


@validate_call(config=_CALL_CONFIG)
def resistance(
    d: RunData,
    *,
    r_short_ohm: Ohms = DEFAULT_R_SHORT_OHM,
    r_open_ohm: Ohms = DEFAULT_R_OPEN_OHM,
    segment: Segment = "fwd",
    force: bool = False,
    x: str | None = None,
    y: str | None = None,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Resistance, linearity and offset of an I-V line with an open/short/in_range classification (module
    docstring). Returns ``resistance`` (+ ``linearity_r2`` and ``offset_current`` when fitted); one non-ok
    ``resistance`` result on refusal or failure."""
    policy = trust_policy(criteria)
    x, y = sweep_columns(d, x, y, "resistance")
    r = analysed_rows(d, x, y, policy, segment=segment, abort_aware=True)
    out = Results("resistance", {"r_short_ohm": r_short_ohm, "r_open_ohm": r_open_ohm, "segment": segment,
                                 "force": force, "x": x, "y": y, "trust_policy": policy_params(policy)})
    problems = r.problems(f"segment {segment}", noise=False)
    if problems and not force:
        return [out.refused("resistance", "Ohm", problems, excluded=r.excluded())]
    out.flag(problems)

    stop = first_compliance(r)
    if stop is not None:
        v_c, i_c = stop
        if i_c == 0:
            return [out.failed("resistance", "Ohm", "Compliance reported with zero current.", excluded=r.excluded())]
        bound = abs(v_c) / abs(i_c)
        if bound > r_short_ohm:
            return [out.failed("resistance", "Ohm", f"Compliance at {x} = {v_c:g} V limits only R <= {bound:.3g} Ohm, "
                               f"above r_short_ohm {r_short_ohm:g} Ohm: raise the compliance or lower |V| within the "
                               "card's limits to classify.", excluded=r.excluded())]
        return [out.ok("resistance", bound, "Ohm", excluded=r.excluded(), points_used=1, bound="upper",
                       classification="short", fit={"v_compliance": v_c, "i_compliance": i_c},
                       warnings=[(f"Compliance at {x} = {v_c:g} V ({abs(i_c):.3g} A): short, R <= {bound:.3g} Ohm; "
                                 "the sweep aborted there.")])]

    xs, ys = r.xs, r.ys
    if xs.size < 3 or float(np.ptp(xs)) <= 0:
        return [out.failed("resistance", "Ohm", f"Only {xs.size} trusted point(s) over distinct voltages; "
                           "resistance needs 3.", excluded=r.excluded())]
    slope, intercept, r2 = line_fit(xs, ys)
    sigma = noise_sigma(ys)
    span = float(np.ptp(xs))
    window = window_of(xs, "V")
    r.use(np.arange(xs.size))
    excluded = r.excluded()
    offset_fit = {"v_offset": -intercept / slope} if slope != 0 else {}
    offset = out.ok("offset_current", intercept, "A", excluded=excluded, points_used=int(xs.size), window=window,
                    fit=offset_fit)
    if sigma and float(np.ptp(ys)) / sigma < MIN_SNR:
        snr = float(np.ptp(ys)) / sigma
        lower = span / (MIN_SNR * sigma)
        return [out.ok("resistance", lower, "Ohm", excluded=excluded, points_used=int(xs.size), window=window,
                       bound="lower", classification="open", fit={"noise_a": sigma, "snr": snr},
                       warnings=[(f"{y} is at the noise floor (range {snr:.1f}x the noise estimate): open, R >= "
                                 f"{lower:.3g} Ohm. Check the probe landing.")]), offset]
    if slope <= 0:
        return [out.failed("resistance", "Ohm", f"Non-positive conductance {slope:.3g} S with a clean signal: not a "
                           "resistor (check the wiring and the pin map).", excluded=excluded)]
    value = 1.0 / slope
    classification = "short" if value <= r_short_ohm else "open" if value >= r_open_ohm else "in_range"
    warnings = [f"Non-linear I-V (r2 = {r2:.4f} < {MIN_R2}): not an ohmic contact."] if r2 < MIN_R2 else []
    fit = {"conductance": slope, "intercept": intercept, "r2": r2}
    if sigma:
        fit["noise_a"] = float(sigma)
    return [
        out.ok("resistance", value, "Ohm", excluded=excluded, points_used=int(xs.size), window=window, fit=fit,
               warnings=warnings, classification=classification),
        out.ok("linearity_r2", r2, "1", excluded=excluded, points_used=int(xs.size), window=window),
        offset,
    ]
