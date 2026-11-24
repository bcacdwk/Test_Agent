"""Built-in rules: run size and mode, always-confirm recipes, pre-existing errors and calibration (blueprint 2.8 /
v1 4.2 table rows R-RUN-01, R-RUN-02, R-ALWAYS-01, R-ERRX-01, R-CAL-01, R-CAL-02, in table order), plus the post-run
R-QUAL-* classification (``quality_findings``, reached through ``RulesEngine.quality``) and the status letters the
MFCMU and WGFMU kinds give their points (``cmu_status_letter``, ``wgfmu_status_letter``)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Final

from b1500_test_agent.driver.parser import CmuStatus
from b1500_test_agent.models.analysis import StatusLetter, TrustPolicy
from b1500_test_agent.models.plan import RuleFinding
from b1500_test_agent.models.station import MODULE_FAMILY
from b1500_test_agent.rules.builtin.common import source_plan_of
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, info, rule, warn

PHYSICAL_SETUP_KINDS: Final = frozenset({"cmu_correction"})
"""Kinds whose runs need the human to change the probe state (open/short/load standards): always ``physical_setup``
(blueprint v2 decision 11), even if a recipe forgot to declare it."""

# -- R-RUN-01 --------------------------------------------------------------------------------------------------------


@rule("R-RUN-01", {"plan"})
def run_size(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Points within ``policy.run_limits.max_points``. WGFMU points count per channel against ``max_points.wgfmu``
    (R-WG-02, from the waveform program); the remaining points against the smallest ``max_points.<family>`` over the
    other measuring families of the bound channels (``smu`` when none is bound). The duration and the execution mode
    are R-RUN-02's."""
    limits, estimate = ctx.policy.run_limits, ctx.plan.estimate
    families = {MODULE_FAMILY[b.module_type] for b in ctx.plan.binding.roles.values()
                if b.module_type is not None and b.module_type in MODULE_FAMILY}
    points = estimate.points
    sources, _ = source_plan_of(ctx)
    if sources.waveform is not None and "wgfmu" in families:
        families.discard("wgfmu")
        points = max(points - sum(sources.waveform.points(ch) for ch in sources.waveform.sequences), 0)
        if not families:
            return
    family = min(sorted(families) or ["smu"], key=limits.max_points.for_family)
    max_points = limits.max_points.for_family(family)
    if points > max_points:
        yield block(f"{points} points exceed the {family} run limit {max_points}",
                    source=env.policy(f"run_limits.max_points.{family}"), observed=points, limit=max_points)


# -- R-RUN-02 --------------------------------------------------------------------------------------------------------


def _duration(seconds: float) -> str:
    if seconds >= 7200:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 60:.0f} min" if seconds >= 120 else f"{seconds:g} s"


@rule("R-RUN-02", {"plan"})
def run_mode(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Execution mode by estimated duration (``policy.run_limits``): above ``max_sync_run_s`` the plan must run
    asynchronously (``mode: async``; a synchronous plan that long is blocked), above ``long_run_confirm_s`` it needs
    confirmation (``long_run``), above ``max_async_run_s`` it is blocked. An asynchronous plan needs checkpoints at
    most ``segment_max_s`` apart (``estimate.max_segment_s``), so a cancel lands within one segment."""
    limits, estimate, mode = ctx.policy.run_limits, ctx.plan.estimate, ctx.plan.mode
    est = estimate.duration_s
    if est > limits.max_async_run_s:
        yield block(f"estimated {_duration(est)} exceeds the longest allowed run {_duration(limits.max_async_run_s)}",
                    source=env.policy("run_limits.max_async_run_s"), observed=est, limit=limits.max_async_run_s)
        return
    if est > limits.max_sync_run_s:
        if mode == "sync":
            yield block(f"estimated {_duration(est)} exceeds the synchronous run limit "
                        f"{_duration(limits.max_sync_run_s)}; only an asynchronous plan may run that long",
                        source=env.policy("run_limits.max_sync_run_s"), observed=est, limit=limits.max_sync_run_s)
        else:
            yield info(f"runs asynchronously (estimated {_duration(est)}): progress via get_run, cancel via "
                       "safe_shutdown", source=env.policy("run_limits.max_sync_run_s"), observed=est,
                       limit=limits.max_sync_run_s)
    if est > limits.long_run_confirm_s:
        yield confirm("long_run", f"estimated {_duration(est)} is longer than {_duration(limits.long_run_confirm_s)}",
                      source=env.policy("run_limits.long_run_confirm_s"), observed=est,
                      limit=limits.long_run_confirm_s)
    if mode == "async":
        segment = estimate.max_segment_s
        if segment is None:
            yield block("an asynchronous plan without checkpoints cannot be cancelled within a segment",
                        source=env.plan("estimate.max_segment_s"), observed=None, limit=limits.segment_max_s)
        elif segment > limits.segment_max_s:
            yield block(f"segments of {segment:g} s between checkpoints exceed {limits.segment_max_s:g} s",
                        source=env.policy("run_limits.segment_max_s"), observed=segment,
                        limit=limits.segment_max_s)


# -- R-ALWAYS-01 -----------------------------------------------------------------------------------------------------


@rule("R-ALWAYS-01", {"plan"})
def always_confirm(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Recipe ``always_confirm`` reasons (destructive, system self-test/self-calibration, physical setup); the
    correction kinds always need ``physical_setup`` (the human sets the probe state), declared or not, and so does any
    plan whose program carries a probe-state prompt (``program["setup"]``: lift the probes, land them on a short ...;
    WP8.5: the QSCV offset measurement of kind ``smu_qscv``), the message carrying the prompt; an ad-hoc ``file``
    parameter from ``work/waveforms/`` (``adhoc_recipe``: a human reviews a waveform no recipe ships)."""
    recipe = ctx.recipe
    setup = ctx.plan.program.get("setup")
    prompt = f": the human must first {setup}" if isinstance(setup, str) and setup else ""
    for reason in recipe.always_confirm:
        yield confirm(reason, f"recipe {recipe.id} always needs confirmation ({reason})"
                      + (prompt if reason == "physical_setup" else ""),
                      source=env.recipe(recipe, "always_confirm"), observed=reason, limit=None)
    if recipe.kind in PHYSICAL_SETUP_KINDS and "physical_setup" not in recipe.always_confirm:
        yield confirm("physical_setup", f"kind {recipe.kind} changes the probe setup (correction standards); a human "
                      f"confirms it{prompt}",
                      source=env.code("b1500_test_agent.rules.builtin.run.PHYSICAL_SETUP_KINDS"), observed=recipe.kind,
                      limit=None)
    elif prompt and "physical_setup" not in recipe.always_confirm:
        yield confirm("physical_setup", f"this plan of kind {recipe.kind} changes the probe setup; a human confirms "
                      f"it{prompt}", source=env.plan("program.setup"), observed=recipe.kind, limit=None)
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


# -- R-CAL-02 --------------------------------------------------------------------------------------------------------


@rule("R-CAL-02", {"pre_execute"})
def async_auto_calibration(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """An asynchronous run turns auto-calibration off (``CM 0``) for its duration, because auto-calibration fires
    after 30 min with outputs off (long retention waits), and restores the state read here afterwards (recorded)."""
    if ctx.plan.mode != "async":
        return
    auto = None if ctx.calibration is None else ctx.calibration.auto_calibration
    state = "unknown" if auto is None else ("on" if auto else "off")
    yield info(f"asynchronous run: auto-calibration is {state}; the run turns it off and restores it afterwards",
               source=env.live("auto_calibration"), observed=auto, limit=False)


# -- R-QUAL-* (post-run) ---------------------------------------------------------------------------------------------

STATUS_MEANINGS: Final[dict[str, str]] = {
    "C": "compliance", "T": "other channel in compliance", "V": "over range or aborted", "X": "oscillation or error",
    "F": "force saturation", "G": "search target not found", "S": "search stopped", "U": "CMU NULL loop unbalance",
    "D": "CMU IV amplifier saturation",
}  # fmt: skip
"""What each non-normal status letter means (PG Table 1-10; WGFMU flags map onto V and X)."""

CMU_STATUS_LETTERS: Final[tuple[tuple[CmuStatus, StatusLetter], ...]] = (
    (CmuStatus.INVALID_DATA, "V"), (CmuStatus.ADC_OVERFLOW, "V"), (CmuStatus.IV_AMP_SATURATION, "D"),
    (CmuStatus.NULL_LOOP_UNBALANCE, "U"),
)  # fmt: skip
"""Summed MFCMU status ``EEE`` bits (PG Table 1-9) to letters, most severe first: invalid data / A/D overflow -> V,
IV amplifier saturation -> D, NULL loop unbalance -> U."""


def cmu_status_letter(eee: int) -> StatusLetter:
    """The status letter of one MFCMU data point from its summed ``EEE`` code (most severe bit wins; 0 -> ``N``).

    Raises:
        ValueError: If ``eee`` has bits the MFCMU does not assign (8, 16, 32) or is outside 0..255.
    """
    if not 0 <= eee <= 255 or eee & 0b111000:
        raise ValueError(f"MFCMU status {eee} has bits not assigned for the CMU")
    for bit, letter in CMU_STATUS_LETTERS:
        if eee & int(bit):
            return letter
    return "N"


def wgfmu_status_letter(*, range_overflow: bool, error: bool) -> StatusLetter:
    """The status letter of one WGFMU data point: an error -> ``X``, a range overflow -> ``V``, else ``N``."""
    if error:
        return "X"
    return "V" if range_overflow else "N"



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
        counted = ", ".join(f"{letter} {n}" for letter, n in by_class[level].items())
        meanings = "; ".join(f"{letter} = {STATUS_MEANINGS[letter]}" for letter in by_class[level]
                             if letter in STATUS_MEANINGS)
        return f"{counted}: {meanings}" if meanings else counted

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
