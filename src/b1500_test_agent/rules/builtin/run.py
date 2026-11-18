"""Built-in rules: run size, always-confirm recipes, pre-existing errors and calibration (blueprint 2.8 / v1 4.2 table
rows R-RUN-01, R-ALWAYS-01, R-ERRX-01, R-CAL-01, in table order), plus the post-run R-QUAL-* classification
(``quality_findings``, reached through ``RulesEngine.quality``)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from b1500_test_agent.models.analysis import TrustPolicy
from b1500_test_agent.models.plan import RuleFinding
from b1500_test_agent.models.station import MODULE_FAMILY
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, info, rule, warn

# -- R-RUN-01 --------------------------------------------------------------------------------------------------------


@rule("R-RUN-01", {"plan"})
def run_size(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Points and estimated duration within ``policy.run_limits``. The point limit is the smallest
    ``max_points.<family>`` over the measuring families of the bound channels (``smu`` when none is bound)."""
    limits, estimate = ctx.policy.run_limits, ctx.plan.estimate
    families = sorted({MODULE_FAMILY[b.module_type] for b in ctx.plan.binding.roles.values()
                       if b.module_type is not None and b.module_type in MODULE_FAMILY}) or ["smu"]
    family = min(families, key=limits.max_points.for_family)
    max_points = limits.max_points.for_family(family)
    if estimate.points > max_points:
        yield block(f"{estimate.points} points exceed the {family} run limit {max_points}",
                    source=env.policy(f"run_limits.max_points.{family}"), observed=estimate.points,
                    limit=max_points)
    if estimate.duration_s > limits.max_sync_run_s:
        yield block(f"estimated {estimate.duration_s:g} s exceeds the synchronous run limit "
                    f"{limits.max_sync_run_s:g} s", source=env.policy("run_limits.max_sync_run_s"),
                    observed=estimate.duration_s, limit=limits.max_sync_run_s)


# -- R-ALWAYS-01 -----------------------------------------------------------------------------------------------------


@rule("R-ALWAYS-01", {"plan"})
def always_confirm(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Recipe ``always_confirm`` reasons (destructive, system self-test/self-calibration, physical setup), and an
    ad-hoc ``file`` parameter from ``work/waveforms/`` (``adhoc_recipe``: a human reviews a waveform no recipe
    ships)."""
    recipe = ctx.recipe
    for reason in recipe.always_confirm:
        yield confirm(reason, f"recipe {recipe.id} always needs confirmation ({reason})",
                      source=env.recipe(recipe, "always_confirm"), observed=reason, limit=None)
    for name, record in sorted(ctx.plan.files.items()):
        if record.origin == "work":
            yield confirm("adhoc_recipe", f"parameter {name} uses the ad-hoc file {record.path} (not in the "
                          "committed waveform library)", subject=name, source=env.plan(f"files.{name}"),
                          observed=record.path, limit="recipes/waveforms/")


# -- R-ERRX-01 -------------------------------------------------------------------------------------------------------


@rule("R-ERRX-01", {"plan", "pre_execute"})
def preexisting_errors(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Pre-existing ``ERRX?`` entries drained by the snapshot are recorded as warnings."""
    if ctx.live is None:
        return
    for error in ctx.live.errors:
        yield warn(f"pre-existing instrument error {error.code}: {error.message or '(no message)'} "
                   "(drained and recorded)", source=env.live("errors"), observed=error.code, limit=0)


# -- R-CAL-01 --------------------------------------------------------------------------------------------------------


@rule("R-CAL-01", {"pre_execute"})
def calibration_recorded(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Auto-calibration state and the last self-calibration are recorded; unknown → warn."""
    cal = ctx.calibration
    auto = None if cal is None else cal.auto_calibration
    if auto is None:
        yield warn("auto-calibration state was not read", source=env.live("auto_calibration"), observed=None,
                   limit="recorded")
    else:
        yield info(f"auto-calibration is {'on' if auto else 'off'}", source=env.live("auto_calibration"),
                   observed=auto)
    last = None if cal is None else cal.last_self_calibration
    if last is None:
        yield warn("no completed self-calibration is recorded (recipe system.self_cal)", source=env.runs_index(),
                   observed=None, limit="recorded")
    else:
        run = cal.last_self_calibration_run if cal is not None else None
        yield info(f"last self-calibration {last.isoformat()}" + (f" (run {run})" if run else ""),
                   source=env.runs_index(), observed=last.isoformat())


# -- R-QUAL-* (post-run) ---------------------------------------------------------------------------------------------


def quality_findings(counts: Mapping[str, int], trust: TrustPolicy, *, source: str) -> list[RuleFinding]:
    """R-QUAL-* classification of per-point status counts (letter → number of points) after a run.

    R-QUAL-01 (info) records the per-class counts; R-QUAL-02 (warn) flags ``limited`` points, which fits exclude;
    R-QUAL-03 (warn) flags ``untrusted`` points, from which extraction is refused unless forced (then flagged).
    Unknown letters classify as untrusted (``TrustPolicy.classify``). Report only; never changes a tier.
    """
    by_class: dict[str, dict[str, int]] = {"ok": {}, "limited": {}, "untrusted": {}}
    for letter, count in sorted(counts.items()):
        if count:
            by_class[trust.classify(letter)][letter] = count
    totals = {level: sum(letters.values()) for level, letters in by_class.items()}
    total = sum(totals.values())

    def detail(level: str) -> str:
        return ", ".join(f"{letter} {n}" for letter, n in by_class[level].items())

    findings = [
        RuleFinding(rule_id="R-QUAL-01", severity="info",
                    message=f"{total} points: {totals['ok']} ok, {totals['limited']} limited, "
                            f"{totals['untrusted']} untrusted", observed=total, source=source)
    ]
    if totals["limited"]:
        findings.append(RuleFinding(rule_id="R-QUAL-02", severity="warn",
                                    message=f"{totals['limited']} limited points ({detail('limited')}) are excluded "
                                            "from fits", observed=totals["limited"], limit=0, source=source))
    if totals["untrusted"]:
        findings.append(RuleFinding(rule_id="R-QUAL-03", severity="warn",
                                    message=f"{totals['untrusted']} untrusted points ({detail('untrusted')}): "
                                            "extraction is refused unless forced, and then flagged",
                                    observed=totals["untrusted"], limit=0, source=source))
    return findings
