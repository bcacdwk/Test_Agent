"""Built-in rules of the MFCMU family: R-CORR-01 correction records (blueprint 2.8; v1 placeholder until the CMU
kinds of M8 make it live)."""

from __future__ import annotations

from collections.abc import Iterator

from b1500_test_agent.rules.builtin.common import CMU_CORRECTIONS, is_real
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, rule

# -- R-CORR-01 -------------------------------------------------------------------------------------------------------


@rule("R-CORR-01", {"plan"})
def cmu_correction(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Capacitance (MFCMU) plans need performed phase compensation, open and short corrections whose frequency
    ranges cover every frequency parameter. Declared for completeness: CMU kinds are ``not_implemented`` in v1."""
    recipe, plan = ctx.recipe, ctx.plan
    uses_cmu = (
        recipe.kind.startswith("cmu")
        or any(b.module_type == "MFCMU" for b in plan.binding.roles.values())
        or any("MFCMU" in r.module_types for r in recipe.roles.values())
    )
    if not uses_cmu:
        return
    corrections = ctx.station.corrections.cmu
    if corrections is None:
        yield block("capacitance measurement without an MFCMU correction record",
                    source=env.station("corrections.cmu"), observed=None, limit="performed corrections")
        return
    freqs: list[float] = []
    for quantity in plan.resolved_params.values():
        if quantity.unit == "Hz":
            values = quantity.value if isinstance(quantity.value, list) else [quantity.value]
            freqs.extend(float(v) for v in values if is_real(v))
    for name in CMU_CORRECTIONS:
        record = getattr(corrections, name)
        if record.status != "performed":
            yield block(f"MFCMU {name} correction is {record.status}", subject=name,
                        source=env.station(f"corrections.cmu.{name}.status"), observed=record.status,
                        limit="performed")
            continue
        if name == "phase_compensation" or not freqs:
            continue
        span = record.frequency_range_hz
        outside = [f for f in sorted(set(freqs)) if span is None or not span[0] <= f <= span[1]]
        if outside:
            yield block(f"MFCMU {name} correction does not cover {outside[0]:g} Hz", subject=name,
                        source=env.station(f"corrections.cmu.{name}.frequency_range_hz"), observed=outside[0],
                        limit=None if span is None else f"{span[0]:g}..{span[1]:g}")


