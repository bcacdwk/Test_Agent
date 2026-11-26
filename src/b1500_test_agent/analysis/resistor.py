"""Two-terminal resistance and contact classification (blueprint 2.8 ``resistance``; card ``contact-resistor-check``)
and the four-wire resistance (blueprint v2 2.10 ``kelvin_resistance``; card ``smu-spot-kelvin``).

Definition (the source of knowledge file ``06-analysis-extraction.md``; change both together): a straight-line
least-squares fit I = G·V + I0 of the measured current ``y`` against the forced voltage ``x`` (defaults: the source
voltage column that varies most and the measured current of the same role, e.g. ``a_V``/``a_I``) over the trusted
points of ``segment`` gives **R = 1/G** (``resistance``, Ohm), the **linearity** r2 of the fit (``linearity_r2``)
and the **offset current** I0 at 0 V (``offset_current``, A; ``fit["v_offset"]`` = -I0/G). Classification
(``classification`` of the ``resistance`` result) against two fixed thresholds, options of this method (defaults
``r_short_ohm`` 100 Ohm and ``r_open_ohm`` 1 GOhm, also the ``basic.contact_resistor`` analysis defaults), never the
DUT profile's expected value: compare R with that value yourself. With the recipe's ±0.1 V and 1 mA compliance any
structure below 100 Ohm (a metal line, two probes on one pad) reaches the compliance and always reads ``short``:

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

**Four-wire resistance** (``kelvin_resistance``; force current, sense voltage, ``resistor.kelvin_4w``; the source
of knowledge file ``03-probe-station-wiring.md`` section "Four-wire resistance", change both together): a
straight-line least-squares fit V = R·I + V0 of the sensed voltage ``y`` against the forced current ``x``
(defaults: the source current column that varies most, e.g. ``a_I``, and the measured voltage of the same role,
``a_V``) over the trusted points gives **R** (``resistance``, Ohm), the **offset voltage** V0 (``offset_voltage``,
V: thermoelectric and amplifier offsets, which a current reversal ±I cancels from R) and the linearity r2
(``linearity_r2``); ``fit`` holds the residual standard deviation ``residual_v`` and the points per current. It
needs at least two distinct currents (the recipe default reverses each current). Classification: ``open`` when a
point reached the voltage compliance (status ``C`` on ``y``: the current could not be delivered) → R ≥ |V|/|I| at
the first such point, reported as that lower bound (``bound="lower"``; nothing is fitted); otherwise ``in_range``, or
``short`` when the sensed voltage span is noise-dominated (below ``MIN_SNR`` x the residual) → R ≤ ``MIN_SNR`` x
residual / current span (``bound="upper"``). A non-positive R with a clean signal → ``failed`` (sense lines swapped
or not landed). Four-wire sensing removes the leads and contacts from R only when Sense is landed at the pads: a
two-wire landing reads the leads too (the card's check).
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
from b1500_test_agent.analysis.dataset import RunData, Segment, parse_value_column
from b1500_test_agent.analysis.mosfet import MIN_R2
from b1500_test_agent.analysis.quality import MIN_SNR, noise_sigma
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, TrustPolicy

DEFAULT_R_SHORT_OHM = 100.0
"""At or below: ``short`` (a method threshold, not from the DUT profile; a 1 mA compliance at 0.1 V also means
R ≤ 100 Ohm)."""

DEFAULT_R_OPEN_OHM = 1e9
"""At or above: ``open`` (1 GOhm; a method threshold, not from the DUT profile)."""

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


def kelvin_columns(d: RunData, x: str | None, y: str | None) -> tuple[str, str]:
    """Default columns of a four-wire measurement: ``x`` = the source current column with the most distinct values,
    ``y`` = the measured voltage of the same role, else the only measured voltage."""
    if x is None:
        candidates = [c for c in d.source_columns if c.endswith("_I")]
        if not candidates:
            raise InvalidInputError(f"kelvin_resistance: run {d.run_id} has no forced-current column; pass "
                                    "x=<column>.")
        x = max(candidates, key=lambda c: int(d.table[c].nunique()))
    if y is None:
        parsed = parse_value_column(x)
        same = f"{parsed[0]}_V" if parsed else ""
        voltages = [c for c in d.measured_columns if c.endswith("_V")]
        if same in voltages:
            y = same
        elif len(voltages) == 1:
            y = voltages[0]
        else:
            raise InvalidInputError(f"kelvin_resistance: cannot choose the voltage column of run {d.run_id} among "
                                    f"{voltages}; pass y=<column>.")
    if d.unit(x) != "A" or d.unit(y) != "V":
        raise InvalidInputError(f"kelvin_resistance needs a current x and a voltage y; got {x}, {y}.")
    return x, y


@validate_call(config=_CALL_CONFIG)
def kelvin_resistance(
    d: RunData,
    *,
    force: bool = False,
    x: str | None = None,
    y: str | None = None,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Four-wire resistance R, offset voltage and linearity of a force-current / sense-voltage measurement with an
    open/short/in_range classification (module docstring). Returns ``resistance`` (+ ``offset_voltage`` and
    ``linearity_r2`` when fitted); one non-ok ``resistance`` result on refusal or failure."""
    policy = trust_policy(criteria)
    x, y = kelvin_columns(d, x, y)
    r = analysed_rows(d, x, y, policy, segment=None)
    out = Results("kelvin_resistance", {"force": force, "x": x, "y": y, "trust_policy": policy_params(policy)})
    problems = r.problems("the run", noise=False)
    if problems and not force:
        return [out.refused("resistance", "Ohm", problems, excluded=r.excluded())]
    out.flag(problems)
    stop = first_compliance(r)
    if stop is not None:
        i_c, v_c = stop
        if i_c == 0:
            return [out.failed("resistance", "Ohm", "Voltage compliance reported at 0 A forced current.",
                               excluded=r.excluded())]
        bound = abs(v_c) / abs(i_c)
        return [out.ok("resistance", bound, "Ohm", excluded=r.excluded(), points_used=1, bound="lower",
                       classification="open", fit={"i_compliance": i_c, "v_compliance": v_c},
                       warnings=[(f"Voltage compliance at {x} = {i_c:g} A ({abs(v_c):.3g} V): open, R >= {bound:.3g} "
                                 "Ohm. Check the force and sense landings.")])]
    xs, ys = r.xs, r.ys
    distinct = np.unique(xs)
    if distinct.size < 2:
        return [out.failed("resistance", "Ohm", f"{distinct.size} distinct forced current(s) among the trusted "
                           "points; a four-wire resistance needs two (preferably +I and -I).", excluded=r.excluded())]
    slope, intercept, r2 = line_fit(xs, ys)
    residual = ys - (intercept + slope * xs)
    dof = max(xs.size - 2, 1)
    residual_v = float(np.sqrt(np.sum(residual**2) / dof)) if xs.size > 2 else 0.0
    window = window_of(xs, "A")
    r.use(np.arange(xs.size))
    excluded = r.excluded()
    fit = {"slope": slope, "intercept": intercept, "r2": r2, "residual_v": residual_v,
           "points_per_current": xs.size / distinct.size}
    offset = out.ok("offset_voltage", intercept, "V", excluded=excluded, points_used=int(xs.size), window=window)
    linearity = out.ok("linearity_r2", r2, "1", excluded=excluded, points_used=int(xs.size), window=window)
    span_v = abs(slope) * float(np.ptp(xs))
    if residual_v > 0 and span_v < MIN_SNR * residual_v:
        upper = MIN_SNR * residual_v / float(np.ptp(xs))
        return [out.ok("resistance", upper, "Ohm", excluded=excluded, points_used=int(xs.size), window=window,
                       bound="upper", classification="short", fit=fit,
                       warnings=[(f"{y} is noise-dominated (span {span_v:.3g} V below {MIN_SNR:g}x the residual "
                                 f"{residual_v:.3g} V): short or below the resolution, R <= {upper:.3g} Ohm.")]),
                offset, linearity]
    if slope <= 0:
        return [out.failed("resistance", "Ohm", f"Non-positive four-wire resistance {slope:.3g} Ohm with a clean "
                           "signal: sense lines swapped or not landed (check the Kelvin wiring).", excluded=excluded)]
    warnings = [f"Non-linear V-I (r2 = {r2:.4f} < {MIN_R2}): not an ohmic resistor or heating."] if r2 < MIN_R2 else []
    return [out.ok("resistance", slope, "Ohm", excluded=excluded, points_used=int(xs.size), window=window, fit=fit,
                   warnings=warnings, classification="in_range"), offset, linearity]
