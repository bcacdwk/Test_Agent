"""FeFET memory window from a double gate sweep (blueprint 2.8 ``memory_window``; card ``fefet-dual-sweep-mw``).

Definition (the source of knowledge file ``06-analysis-extraction.md``; change both together): the threshold voltage
of each branch of a double sweep is extracted with one of the transfer-curve methods of ``mosfet.py``
(``vth_method``: ``vth_constant_current`` (default, I_crit = ``i_crit_a`` x ``w_over_l``), ``vth_linear_extrapolation``
or ``vth_max_gm``) on segment ``fwd`` (the first branch in acquisition order, start → stop) and ``rev`` (stop →
start), and

    MW = Vth_fwd - Vth_rev

which is positive for the counter-clockwise loop of an n-channel FeFET swept upwards first (programming on the way
up lowers Vth for the way down). A negative MW gets a warning (sweep direction or polarity). Any method offset (e.g.
(n - 1)·Vd/2 of linear extrapolation, or I_crit below the model threshold current) is the same on both branches and
cancels in MW. Per branch, Ion and Ioff come from ``ion_ioff`` (``v_on``/``v_off``, default the sweep ends).

Results: ``memory_window`` (V), ``vth_fwd``, ``vth_rev`` (V), ``ion_fwd``, ``ioff_fwd``, ``ion_rev``, ``ioff_rev``
(A; the on/off ratio of each branch in the Ion result's ``fit``); the branch results carry a short record (branch
method and segment), the call's options are in the ``memory_window`` result's record. Trust and refusal as every
method (``mosfet.py`` docstring), per branch: when a branch's Vth is refused or fails, the call returns ``vth_fwd``,
``vth_rev`` (with their outcomes) and a non-ok ``memory_window``.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, validate_call

from b1500_test_agent.analysis.common import METHOD_VERSION, Results, policy_params, trust_policy
from b1500_test_agent.analysis.dataset import SEGMENTS, RunData
from b1500_test_agent.analysis.mosfet import (
    DEFAULT_I_CRIT_A,
    DRAIN_BIAS_PARAM,
    PositiveFloat,
    Smooth,
    ion_ioff,
    vth_constant_current,
    vth_linear_extrapolation,
    vth_max_gm,
)
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, MethodRecord, TrustPolicy, VthMethod

_CALL_CONFIG = ConfigDict(arbitrary_types_allowed=True)


def _branch_vth(d: RunData, segment: str, method: VthMethod, *, i_crit_a: float, w_over_l: float | None,
                subtract_half_vd: bool, vd: float | None, vd_param: str, smooth: int, force: bool, x: str, y: str,
                criteria: TrustPolicy) -> ExtractionResult:
    common: dict[str, Any] = {"segment": segment, "force": force, "x": x, "y": y, "criteria": criteria}
    if method == "vth_constant_current":
        return vth_constant_current(d, i_crit_a=i_crit_a, w_over_l=w_over_l, **common)
    biased: dict[str, Any] = {"subtract_half_vd": subtract_half_vd, "vd": vd, "vd_param": vd_param,
                              "smooth": smooth, **common}
    if method == "vth_max_gm":
        return vth_max_gm(d, **biased)
    return vth_linear_extrapolation(d, **biased)


@validate_call(config=_CALL_CONFIG)
def memory_window(
    d: RunData,
    *,
    vth_method: VthMethod = "vth_constant_current",
    i_crit_a: PositiveFloat = DEFAULT_I_CRIT_A,
    w_over_l: PositiveFloat | None = None,
    subtract_half_vd: bool = True,
    v_on: float | None = None,
    v_off: float | None = None,
    force: bool = False,
    x: str = "gate_V",
    y: str = "drain_I",
    vd: float | None = None,
    vd_param: str = DRAIN_BIAS_PARAM,
    smooth: Smooth = 5,
    criteria: TrustPolicy | None = None,
) -> list[ExtractionResult]:
    """Memory window MW = Vth_fwd - Vth_rev of a double sweep with per-branch Vth, Ion and Ioff (module
    docstring)."""
    policy = trust_policy(criteria)
    if not d.has_segments or set(d.segments()) != set(SEGMENTS):
        raise InvalidInputError(f"memory_window needs a double sweep (segment column with fwd and rev); run "
                                f"{d.run_id} has {d.segments()}.")
    params: dict[str, Any] = {"vth_method": vth_method, "i_crit_a": i_crit_a, "w_over_l": w_over_l,
                              "subtract_half_vd": subtract_half_vd, "v_on": v_on, "v_off": v_off, "force": force,
                              "x": x, "y": y, "vd": vd, "vd_param": vd_param, "smooth": smooth,
                              "trust_policy": policy_params(policy)}
    if vth_method == "vth_constant_current":
        for key in ("subtract_half_vd", "vd", "vd_param", "smooth"):
            params.pop(key)
    out = Results("memory_window", params)
    branch = {segment: _branch_vth(d, segment, vth_method, i_crit_a=i_crit_a, w_over_l=w_over_l,
                                   subtract_half_vd=subtract_half_vd, vd=vd, vd_param=vd_param, smooth=smooth,
                                   force=force, x=x, y=y, criteria=policy) for segment in SEGMENTS}
    renamed = {segment: _as_memory_window(result, f"vth_{segment}", segment) for segment, result in branch.items()}
    fwd, rev = branch["fwd"], branch["rev"]
    excluded = {f"{s}:{k}": v for s, res in branch.items() for k, v in res.points_excluded.items()}
    if fwd.value is None or rev.value is None:
        outcomes = {fwd.outcome, rev.outcome}
        errors = "; ".join(f"{s}: {res.error}" for s, res in branch.items() if res.error)
        window = out.not_ok("memory_window", "V", "refused" if "refused" in outcomes else "failed",
                            f"No memory window: the {vth_method} threshold of a branch is missing ({errors})",
                            excluded=excluded)
        return [window, renamed["fwd"], renamed["rev"]]
    out.forced = fwd.forced_on_untrusted or rev.forced_on_untrusted
    value = fwd.value - rev.value
    warnings = [f"fwd: {w}" for w in fwd.warnings] + [f"rev: {w}" for w in rev.warnings]
    if value < 0:
        warnings.append("Negative memory window: Vth_fwd < Vth_rev (clockwise loop). Check the sweep direction "
                        "(fwd = first branch) and the device polarity.")
    results = [out.ok("memory_window", value, "V", excluded=excluded,
                      points_used=fwd.points_used + rev.points_used,
                      fit={"vth_fwd": fwd.value, "vth_rev": rev.value}, warnings=warnings),
               renamed["fwd"], renamed["rev"]]
    for segment in SEGMENTS:
        on_off = ion_ioff(d, v_on=v_on, v_off=v_off, segment=segment, force=force, x=x, y=y, criteria=policy)
        by_name = {res.quantity: res for res in on_off}
        ratio = by_name.get("on_off_ratio")
        for quantity in ("ion", "ioff"):
            res = by_name.get(quantity)
            if res is None:  # refused or failed: one non-ok "ion" result
                results.append(_as_memory_window(on_off[0], f"{on_off[0].quantity}_{segment}", segment))
                break
            extra = {"on_off_ratio": ratio.value} if quantity == "ion" and ratio is not None and ratio.value else {}
            renamed_res = _as_memory_window(res, f"{quantity}_{segment}", segment)
            results.append(renamed_res.model_copy(update={"fit": {**renamed_res.fit, **extra}}))
    return results


def _as_memory_window(result: ExtractionResult, quantity: str, segment: str) -> ExtractionResult:
    """A branch result relabelled as part of a ``memory_window`` call: method ``memory_window``, the given
    ``quantity`` and a short record naming the branch method and segment (the call's full options are in the
    record of the ``memory_window`` result)."""
    record = MethodRecord(name="memory_window", version=METHOD_VERSION,
                          params={"branch_method": result.method, "segment": segment})
    return result.model_copy(update={"method": "memory_window", "quantity": quantity, "method_record": record})
