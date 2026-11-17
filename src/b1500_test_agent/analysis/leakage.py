"""Leakage at a bias against a limit (blueprint 2.8 ``leakage_at``; cards ``gate-leakage`` and ``diode-iv``).

Definition (the source of knowledge file ``06-analysis-extraction.md``; change both together): the **leakage**
|I(v)| of the measured current ``y`` at the forced voltage ``x`` = ``v`` (defaults: the swept source voltage and the
measured current of the same role, e.g. ``gate_V``/``gate_I``), linearly interpolated between the bracketing
trusted points, compared with ``limit_a``: ``classification`` ``pass`` when |I(v)| ≤ limit, else ``fail``.
``v`` and ``limit_a`` default to the run plan's resolved parameters named ``v_param`` (default ``v_op``, volts) and
``limit_param`` (default ``leak_limit_a``, amperes); without a limit no classification is made.

- **Compliance stop**: when ``y`` reached its compliance (status ``C``) at a voltage between 0 and ``v`` (inclusive),
  the leakage at ``v`` is at least the compliance current (leakage grows with |V|): the result is that lower bound
  (``bound="lower"``) and ``fail`` when the limit is at most that current (a limit above the compliance cannot be
  decided → ``failed``: raise the compliance within the card's limits). The dummy rows after the automatic abort
  count as ``aborted`` (no data); a compliance stop beyond ``v`` leaves the value at ``v`` exact.
- **Noise floor**: when log10|I| is rough around ``v`` (``common.floor_limit``) the current is below the detection
  limit; the result is the upper bound of 3 noise standard deviations (``bound="upper"``), ``pass`` when that bound
  is within the limit. A noise-dominated leakage is a measurement result, not a refusal.

Trust otherwise as every method (``mosfet.py`` docstring): any other untrusted point refuses the call unless
``force``.
"""

from __future__ import annotations

from typing import Annotated

import numpy as np
from pydantic import ConfigDict, Field, validate_call

from b1500_test_agent.analysis.common import (
    Results,
    analysed_rows,
    first_compliance,
    floor_limit,
    interpolate,
    policy_params,
    sweep_columns,
    trust_policy,
)
from b1500_test_agent.analysis.dataset import RunData, Segment
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Bound, ExtractionResult, TrustPolicy, Unit

V_PARAM = "v_op"
"""Resolved plan parameter holding the operating bias (V) at which the leakage is judged."""

LIMIT_PARAM = "leak_limit_a"
"""Resolved plan parameter holding the leakage limit (A)."""

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)
Amps = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Volts = Annotated[float, Field(allow_inf_nan=False)]


def _param(d: RunData, name: str, unit: Unit, what: str) -> float | None:
    quantity = d.param(name)
    if quantity is None:
        return None
    if not quantity.is_number or quantity.unit != unit:
        raise InvalidInputError(f"Plan parameter {name!r} ({what}) is not a scalar in {unit}: {quantity.value!r} "
                                f"{quantity.unit}.")
    return quantity.as_float()


@validate_call(config=_CALL_CONFIG)
def leakage_at(
    d: RunData,
    *,
    v: Volts | None = None,
    limit_a: Amps | None = None,
    v_param: str = V_PARAM,
    limit_param: str = LIMIT_PARAM,
    segment: Segment = "fwd",
    force: bool = False,
    x: str | None = None,
    y: str | None = None,
    criteria: TrustPolicy | None = None,
) -> ExtractionResult:
    """|I| at bias ``v`` against ``limit_a`` (module docstring). One ``ExtractionResult`` (``quantity="leakage"``,
    unit A, ``classification`` pass/fail when a limit is known)."""
    policy = trust_policy(criteria)
    x, y = sweep_columns(d, x, y, "leakage_at")
    v_source = "argument"
    if v is None:
        v, v_source = _param(d, v_param, "V", "the leakage bias"), f"plan.resolved_params.{v_param}"
        if v is None:
            raise InvalidInputError(f"leakage_at needs the bias: run {d.run_id} has no resolved plan parameter "
                                    f"{v_param!r}; pass v=<volts> (or v_param=<name>).")
    limit_source = "argument" if limit_a is not None else None
    if limit_a is None:
        limit_a = _param(d, limit_param, "A", "the leakage limit")
        limit_source = f"plan.resolved_params.{limit_param}" if limit_a is not None else None
    r = analysed_rows(d, x, y, policy, segment=segment, abort_aware=True)
    out = Results("leakage_at", {"v": v, "v_source": v_source, "limit_a": limit_a, "limit_source": limit_source,
                                 "segment": segment, "force": force, "x": x, "y": y,
                                 "trust_policy": policy_params(policy)})
    problems = r.problems(f"segment {segment}", noise=False)
    if problems and not force:
        return out.refused("leakage", "A", problems, excluded=r.excluded())
    out.flag(problems)
    fit = {"v": v} | ({"limit_a": limit_a} if limit_a is not None else {})

    stop = first_compliance(r)
    if stop is not None and _between(stop[0], v):
        v_c, i_c = stop
        current = abs(i_c)
        warnings = [(f"{y} reached its compliance at {x} = {v_c:g} V; the leakage at {v:g} V is at least "
                    f"{current:.3g} A.")]
        if limit_a is not None and limit_a > current:
            return out.failed("leakage", "A", f"Compliance {current:.3g} A at {v_c:g} V is below the limit "
                              f"{limit_a:.3g} A: pass/fail cannot be decided; raise the compliance within the card's "
                              "limits.", excluded=r.excluded(), fit=fit)
        return out.ok("leakage", current, "A", excluded=r.excluded(), points_used=1, bound="lower",
                      classification="fail" if limit_a is not None else None,
                      fit={**fit, "v_compliance": v_c, "i_compliance": i_c}, warnings=warnings)

    xs, ys = r.xs, r.ys
    found = interpolate(xs, ys, v) if xs.size else None
    if found is None:
        span = f"{xs.min():g}..{xs.max():g} V" if xs.size else "no trusted points"
        return out.failed("leakage", "A", f"{x} = {v:g} V lies outside the trusted sweep range ({span}).",
                          excluded=r.excluded(), fit=fit)
    signed, position = found
    order = np.argsort(xs, kind="stable")
    r.use([int(order[position])])
    value = abs(signed)
    bound: Bound = "exact"
    warnings = []
    floor = floor_limit(xs, ys, position)
    if floor is not None and value <= floor:
        value, bound = floor, "upper"
        warnings.append(f"{y} is at the noise floor around {v:g} V: the leakage is below the detection limit "
                        f"{floor:.3g} A (upper bound).")
    if stop is not None:
        warnings.append(f"The sweep stopped on compliance at {x} = {stop[0]:g} V, beyond the leakage bias.")
    classification = None
    if limit_a is not None:
        classification = "pass" if value <= limit_a else "fail"
    return out.ok("leakage", value, "A", excluded=r.excluded(), points_used=1, bound=bound,
                  classification=classification, fit={**fit, "i_signed": signed}, warnings=warnings)


def _between(v_c: float, v: float) -> bool:
    """True when ``v_c`` lies between 0 and ``v`` (inclusive, same polarity)."""
    lo, hi = sorted((0.0, v))
    return lo - 1e-12 <= v_c <= hi + 1e-12
