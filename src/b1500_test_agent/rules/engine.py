"""Rules engine (blueprint 2.5, 4.1-4.3): rule registry, rule context, finding sources and evaluation.

A rule is one small function registered with a stable id and the phases it runs in::

    @rule("R-LIM-03", {"plan"})
    def soft_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
        ...
        yield confirm("soft_limit", "...", source=env.policy("soft_limits.voltage_v"), observed=v, limit=soft)

Rules return ``Finding`` drafts; the engine stamps them with the rule's own id, so a rule cannot speak for another
one. ``RulesEngine.evaluate`` runs every rule of a phase in registration order (the order of the blueprint 4.2
table, which ``builtin.py`` follows), keeps each rule's own finding order, and derives the tier: any ``block`` →
``blocked``; else any ``confirm`` → ``needs_confirmation``; else ``ok``. A rule that raises is reported as a
``block`` finding of that rule (fail closed), never as an exception.

Every finding names its ``source``: the resolved config file path and key (``config/local/policy.yaml#soft_limits
.voltage_v``), the recipe field, a code constant (``code:...``), the live snapshot (``live:...``), the plan
(``plan:...``) or a state file under ``data/state/``. Thresholds come only from config, recipes and the code tables
(``driver/modules.py``, the hard-limit ceiling); rules never hard-code their own.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import AwareDatetime, model_validator

from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.models.analysis import RunId, TrustPolicy
from b1500_test_agent.models.common import (
    Backend,
    ConfigReport,
    ConfirmReason,
    JsonScalar,
    StrictModel,
    ValidationStatus,
)
from b1500_test_agent.models.plan import PlanRecord, RuleFinding, RulesReport
from b1500_test_agent.models.policy import DutProfile, Policy
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.run import FaultRecord
from b1500_test_agent.models.station import LiveState, PinMap, StationProfile

Phase = Literal["plan", "pre_execute"]
"""Evaluation phases of ``RulesEngine.evaluate`` (blueprint 4.1): ``plan`` at ``validate_plan`` and again without
I/O at the start of every run; ``pre_execute`` under the instrument lock with fresh live state."""

PHASES: Final[frozenset[str]] = frozenset({"plan", "pre_execute"})

Severity = Literal["info", "warn", "confirm", "block"]

STATUS_RANK: Final[dict[str, int]] = {"not_implemented": 0, "draft": 1, "sim_validated": 2, "hw_validated": 3}
"""Recipe validation statuses from least to most validated."""

_RULE_ID = re.compile(r"^R-[A-Z]+-\d{2}$")
BUILTIN_MODULE: Final = "b1500_test_agent.rules.builtin"


# -- Context ---------------------------------------------------------------------------------------------------------


class CalibrationState(StrictModel):
    """Calibration facts recorded by rule R-CAL-01 (warn only).

    ``auto_calibration`` is the instrument's auto-calibration switch as read by the session (``None`` = not read);
    ``last_self_calibration`` and ``last_self_calibration_run`` come from the newest completed ``system.self_cal``
    run in the archive (``None`` = none recorded).
    """

    auto_calibration: bool | None = None
    last_self_calibration: AwareDatetime | None = None
    last_self_calibration_run: RunId | None = None


class RuleContext(StrictModel):
    """Everything a rule may look at (blueprint 2.5), assembled by the executor.

    Additions to the blueprint signature: ``effective_status`` (the registry's status of the recipe for this
    backend, so a kind missing on the backend makes it ``not_implemented``; R-REC-01), ``fault`` and
    ``inflight_unrecovered`` (fault latch and in-flight marker; R-FAULT-01), ``calibration`` (R-CAL-01) and
    ``recipe_source`` (the recipe file path, used in finding sources). ``pin_map`` and ``dut`` are ``None`` when
    the request names a pin map or DUT profile that does not exist, so that R-PIN-01 and R-DUT-01 can block it.
    ``live`` is ``None`` when no snapshot was taken (always at the zero-I/O re-check of a run).
    """

    plan: PlanRecord
    recipe: Recipe
    effective_status: ValidationStatus
    station: StationProfile
    policy: Policy
    pin_map: PinMap | None
    dut: DutProfile | None
    live: LiveState | None = None
    backend: Backend
    fault: FaultRecord | None = None
    inflight_unrecovered: bool = False
    calibration: CalibrationState | None = None
    recipe_source: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RuleContext:
        plan, recipe = self.plan, self.recipe
        if (plan.recipe_id, plan.recipe_version, plan.recipe_sha) != (recipe.id, recipe.version, recipe.sha256):
            raise ValueError("The recipe (id, version, sha256) differs from the plan's.")
        if plan.kind != recipe.kind:
            raise ValueError("The plan's kind differs from the recipe's.")
        if self.pin_map is not None and self.pin_map.name != plan.binding.pin_map:
            raise ValueError("pin_map is not the plan's pin map.")
        if self.dut is not None and self.dut.name != plan.request.dut_profile:
            raise ValueError("dut is not the plan's DUT profile.")
        if STATUS_RANK[self.effective_status] > STATUS_RANK[recipe.status]:
            raise ValueError("effective_status cannot be more validated than the recipe's own status.")
        return self


# -- Findings --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A rule's result before the engine stamps it with the rule id (see ``block``/``confirm``/``warn``/``info``)."""

    severity: Severity
    message: str
    source: str
    subject: str | None = None
    observed: JsonScalar = None
    limit: JsonScalar = None
    reason: ConfirmReason | None = None


def block(message: str, *, source: str, subject: str | None = None, observed: JsonScalar = None,
          limit: JsonScalar = None) -> Finding:
    """A finding that makes the plan ``blocked``."""
    return Finding("block", message, source, subject, observed, limit)


def confirm(reason: ConfirmReason, message: str, *, source: str, subject: str | None = None,
            observed: JsonScalar = None, limit: JsonScalar = None) -> Finding:
    """A finding that makes the plan ``needs_confirmation`` with ``reason`` (plan-phase rules only)."""
    return Finding("confirm", message, source, subject, observed, limit, reason)


def warn(message: str, *, source: str, subject: str | None = None, observed: JsonScalar = None,
         limit: JsonScalar = None) -> Finding:
    """A recorded warning; does not change the tier."""
    return Finding("warn", message, source, subject, observed, limit)


def info(message: str, *, source: str, subject: str | None = None, observed: JsonScalar = None,
         limit: JsonScalar = None) -> Finding:
    """A recorded fact; does not change the tier."""
    return Finding("info", message, source, subject, observed, limit)


# -- Sources ---------------------------------------------------------------------------------------------------------


class RuleEnv:
    """What a rule gets besides the context: the phase, the loaded config and source-string builders."""

    def __init__(self, config: ConfigBundle, phase: Phase, *, recipe_source: str | None = None) -> None:
        self.config = config
        self.phase: Phase = phase
        self._recipe_source = recipe_source

    def config_source(self, key: str, field: str | None = None) -> str:
        """``<resolved file path>#<field>`` of config item ``key`` (``config:<key>`` when no file was loaded)."""
        file = self.config.files.get(key)
        where = file.path if file is not None else f"config:{key}"
        return f"{where}#{field}" if field else where

    def policy(self, field: str) -> str:
        return self.config_source("policy", field)

    def station(self, field: str) -> str:
        return self.config_source("station", field)

    def settings(self, field: str) -> str:
        return self.config_source("settings", field)

    def pin_map(self, name: str, field: str | None = None) -> str:
        return self.config_source(f"pinmaps/{name}", field)

    def dut(self, name: str, field: str | None = None) -> str:
        return self.config_source(f"duts/{name}", field)

    def recipe(self, recipe: Recipe, field: str) -> str:
        """``<recipe file>#<field>``, or ``recipe:<id>@<version>#<field>`` when the file path is unknown."""
        return f"{self._recipe_source or f'recipe:{recipe.id}@{recipe.version}'}#{field}"

    def state(self, name: str) -> str:
        """Display path of a file in the state directory (``data/state/fault.json``)."""
        paths = self.config.paths
        return paths.display(paths.state_dir / name)

    def runs_index(self) -> str:
        paths = self.config.paths
        return paths.display(paths.runs_dir / "index.jsonl")

    @staticmethod
    def code(symbol: str) -> str:
        """A threshold defined in code, e.g. ``code:b1500_test_agent.rules.tiers.HARD_CEILING_V``."""
        return f"code:{symbol}"

    @staticmethod
    def live(field: str) -> str:
        """A field of the live instrument snapshot, e.g. ``live:status_byte.bit3``."""
        return f"live:{field}"

    @staticmethod
    def plan(field: str) -> str:
        """A field of the plan record, e.g. ``plan:estimate.points``."""
        return f"plan:{field}"


# -- Registry --------------------------------------------------------------------------------------------------------

RuleFn = Callable[[RuleContext, RuleEnv], Iterable[Finding]]


@dataclass(frozen=True)
class RuleSpec:
    """A registered rule: stable id, phases and the function."""

    rule_id: str
    phases: frozenset[str]
    fn: RuleFn

    @property
    def symbol(self) -> str:
        return f"{self.fn.__module__}.{self.fn.__qualname__}"


class RuleRegistry:
    """Ordered rule registry; ``REGISTRY`` holds the built-in rules, tests may build their own."""

    def __init__(self) -> None:
        self._rules: dict[str, RuleSpec] = {}

    def rule(self, rule_id: str, phases: set[str]) -> Callable[[RuleFn], RuleFn]:
        """Registration decorator; raises ``ValueError`` for a malformed or duplicate id or an unknown phase."""
        if not _RULE_ID.match(rule_id):
            raise ValueError(f"rule id {rule_id!r} does not match R-<AREA>-<nn>")
        phase_set = frozenset(phases)
        if not phase_set or not phase_set <= PHASES:
            raise ValueError(f"rule {rule_id}: phases must be a non-empty subset of {sorted(PHASES)}")
        if rule_id in self._rules:
            raise ValueError(f"rule {rule_id} is already registered")

        def register(fn: RuleFn) -> RuleFn:
            self._rules[rule_id] = RuleSpec(rule_id, phase_set, fn)
            return fn

        return register

    def rules(self) -> tuple[RuleSpec, ...]:
        return tuple(self._rules.values())


REGISTRY = RuleRegistry()


def rule(rule_id: str, phases: set[str]) -> Callable[[RuleFn], RuleFn]:
    """Register a built-in rule (blueprint 2.5); see ``RuleRegistry.rule``."""
    return REGISTRY.rule(rule_id, phases)


def registered_rules() -> tuple[RuleSpec, ...]:
    """The built-in rules in registration (blueprint 4.2 table) order."""
    importlib.import_module(BUILTIN_MODULE)
    return REGISTRY.rules()


def rule_rank(rule_id: str) -> int:
    """Position of a built-in rule id in the table order; unknown ids rank after all built-in rules."""
    ids = [spec.rule_id for spec in registered_rules()]
    return ids.index(rule_id) if rule_id in ids else len(ids)


# -- Engine ----------------------------------------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RulesEngine:
    """Evaluates the registered rules for one configuration (blueprint 2.5).

    ``rules`` defaults to the built-in rules; ``clock`` supplies ``evaluated_at`` (tests pin it).
    """

    def __init__(
        self,
        config: ConfigBundle,
        *,
        rules: Sequence[RuleSpec] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.rules: tuple[RuleSpec, ...] = tuple(rules) if rules is not None else registered_rules()
        self._clock = clock or _utc_now

    def evaluate(self, ctx: RuleContext, phase: Phase) -> RulesReport:
        """Run every rule of ``phase``; never raises for a failing rule (it becomes a ``block`` finding)."""
        if phase not in PHASES:
            raise ValueError(f"unknown phase {phase!r}; expected one of {sorted(PHASES)}")
        env = RuleEnv(self.config, phase, recipe_source=ctx.recipe_source)
        findings: list[RuleFinding] = []
        for spec in self.rules:
            if phase in spec.phases:
                findings.extend(self._run(spec, ctx, env))
        return RulesReport.from_findings(
            phase, findings, policy_digest=self.config.sha256("policy"), evaluated_at=self._clock()
        )

    def _run(self, spec: RuleSpec, ctx: RuleContext, env: RuleEnv) -> list[RuleFinding]:
        try:
            out: list[RuleFinding] = []
            for draft in spec.fn(ctx, env):
                if not isinstance(draft, Finding):
                    raise TypeError(f"rule returned {type(draft).__name__}, not Finding")
                if draft.severity == "confirm" and env.phase != "plan":
                    raise ValueError("confirm findings are plan-phase only (live-state rules block or warn)")
                out.append(
                    RuleFinding(
                        rule_id=spec.rule_id,
                        severity=draft.severity,
                        message=draft.message,
                        subject=draft.subject,
                        observed=draft.observed,
                        limit=draft.limit,
                        source=draft.source,
                        reason=draft.reason,
                    )
                )
            return out
        except Exception as exc:  # noqa: BLE001 - fail closed: a broken rule blocks, never passes silently
            return [
                RuleFinding(
                    rule_id=spec.rule_id,
                    severity="block",
                    message=f"rule {spec.rule_id} failed ({type(exc).__name__}: {exc}); blocked to fail closed",
                    source=RuleEnv.code(spec.symbol),
                )
            ]

    def quality(self, counts: Mapping[str, int], *, recipe: Recipe | None = None,
                recipe_source: str | None = None) -> list[RuleFinding]:
        """R-QUAL-* classification of per-point status counts after a run, with the recipe's ``quality`` classes
        when given, else the policy's (see ``builtin.quality_findings``)."""
        builtin = importlib.import_module(BUILTIN_MODULE)
        env = RuleEnv(self.config, "plan", recipe_source=recipe_source)
        trust: TrustPolicy = recipe.quality if recipe is not None else self.config.policy.quality
        source = env.recipe(recipe, "quality") if recipe is not None else env.policy("quality")
        return builtin.quality_findings(counts, trust, source=source)


def config_findings(report: ConfigReport) -> list[RuleFinding]:
    """R-CFG-01 ``block`` findings for an invalid configuration (error code ``invalid_config``), one per problem,
    with the problem's file and field as ``source``; empty for a valid report."""
    findings = []
    for problem in report.problems:
        where = problem.file or "config"
        source = f"{where}#{problem.location}" if problem.location else where
        findings.append(
            RuleFinding(rule_id="R-CFG-01", severity="block", message=problem.message, subject=problem.location,
                        source=source)
        )
    return findings
