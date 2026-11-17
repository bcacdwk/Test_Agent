"""Plan request and frozen plan record with its binding, envelope, estimate and rule reports (blueprint 2.1, 2.5).

``PlanRecord`` is stored as ``<state_dir>/plans/<plan_id>.json`` and re-verified on every load; ``plan_id`` is
``"P-" + base32(plan_hash)[:10]``. Shapes the blueprint leaves open (``ChannelBinding``, ``CompiledEnvelope``) carry
what the rules, the ``OutputGuard`` and the plan summary need; WP1.4/WP1.7 may extend them.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import (
    Backend,
    ConfigName,
    ConfirmReason,
    JsonScalar,
    Sha256Hex,
    StrictModel,
    Tier,
)
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.recipe import RecipeId, RoleFunction
from b1500_test_agent.models.station import Alias, ModuleType, Slot

PlanId = Annotated[str, Field(pattern=r"^P-[A-Z2-7]{10}$")]
"""``"P-"`` + the first 10 characters of the RFC 4648 base32 encoding of the plan hash."""

RuleId = Annotated[str, Field(pattern=r"^R-[A-Z]+-(\d{2}|\*)$")]
"""Stable rule id, e.g. ``R-LIM-03`` (blueprint 4.2)."""

ParamInput = float | int | str | bool | list[float]
"""A parameter value as submitted by the agent (``PlanRequest.params``)."""


class PlanRequest(StrictModel):
    """What the agent submits to ``validate_plan``. ``label`` is audit text and excluded from the plan hash; the
    die/instance label is passed at run time, so one validated plan serves a die batch."""

    recipe_id: RecipeId
    params: dict[str, ParamInput] = Field(default_factory=dict)
    pin_map: ConfigName
    dut_profile: ConfigName | None = None
    label: str | None = Field(default=None, max_length=200)


class BoundChannel(StrictModel):
    """One recipe role bound through the pin map: the terminal, and the channel/module or the GNDU behind it."""

    role: str
    terminal: str
    gndu: bool = False
    channel: Channel | None = None
    slot: Slot | None = None
    module_type: ModuleType | None = None
    module_model: str | None = None
    alias: Alias | None = None

    @model_validator(mode="after")
    def _channel_xor_gndu(self) -> BoundChannel:
        if self.gndu == (self.channel is not None):
            raise ValueError("A role is bound either to a channel or to the GNDU.")
        return self


class ChannelBinding(StrictModel):
    """Role → channel binding of a plan (rule R-PIN-01 checks it against the station profile)."""

    pin_map: ConfigName
    roles: dict[str, BoundChannel]


class ChannelEnvelope(StrictModel):
    """Largest |V| and |I| (level or compliance) the plan may apply on one channel.

    ``function``, ``v_start`` and ``v_stop`` describe what the role does on the channel (first and last forced
    voltage; equal for a bias) so that the canonical plan summary can show it (blueprint 2.5). They are optional and
    must lie inside ``max_abs_v``, which stays the enforced limit.
    """

    role: str
    max_abs_v: float = Field(ge=0)
    max_abs_i: float = Field(ge=0)
    function: RoleFunction | None = None
    v_start: float | None = None
    v_stop: float | None = None

    @model_validator(mode="after")
    def _levels_inside_envelope(self) -> ChannelEnvelope:
        if (self.v_start is None) != (self.v_stop is None):
            raise ValueError("v_start and v_stop are set together.")
        for level in (self.v_start, self.v_stop):
            if level is not None and abs(level) > self.max_abs_v:
                raise ValueError(f"level {level} V lies outside max_abs_v {self.max_abs_v} V.")
        return self


class CompiledEnvelope(StrictModel):
    """Per-channel allowlist enforced by the ``OutputGuard`` on every source command (blueprint 2.3)."""

    channels: dict[Channel, ChannelEnvelope]

    @property
    def max_abs_v(self) -> float:
        """Largest |V| over all channels (0 when the plan sources nothing)."""
        return max((c.max_abs_v for c in self.channels.values()), default=0.0)

    @property
    def max_abs_i(self) -> float:
        """Largest |I| over all channels (0 when the plan sources nothing)."""
        return max((c.max_abs_i for c in self.channels.values()), default=0.0)


class Estimate(StrictModel):
    """Size of a run: measurement points and expected duration."""

    points: int = Field(ge=0)
    duration_s: float = Field(ge=0)


class RuleFinding(StrictModel):
    """One rule result. ``reason`` is set exactly when ``severity`` is ``confirm``; ``source`` names the config
    file and key the threshold came from (e.g. ``config/local/policy.yaml#soft_limits.voltage_v``)."""

    rule_id: RuleId
    severity: Literal["info", "warn", "confirm", "block"]
    message: str = Field(min_length=1)
    subject: str | None = None
    observed: JsonScalar = None
    limit: JsonScalar = None
    source: str
    reason: ConfirmReason | None = None

    @model_validator(mode="after")
    def _reason_iff_confirm(self) -> RuleFinding:
        if (self.reason is not None) != (self.severity == "confirm"):
            raise ValueError("reason is set exactly when severity is 'confirm'.")
        return self


def tier_from_findings(findings: Iterable[RuleFinding]) -> Tier:
    """Any ``block`` → ``blocked``; else any ``confirm`` → ``needs_confirmation``; else ``ok`` (blueprint 4.3)."""
    severities = {f.severity for f in findings}
    if "block" in severities:
        return "blocked"
    if "confirm" in severities:
        return "needs_confirmation"
    return "ok"


def confirm_reasons_of(findings: Iterable[RuleFinding]) -> list[ConfirmReason]:
    """Confirm reasons of ``confirm`` findings, deduplicated in first-seen order."""
    reasons: list[ConfirmReason] = []
    for finding in findings:
        if finding.reason is not None and finding.reason not in reasons:
            reasons.append(finding.reason)
    return reasons


class RulesReport(StrictModel):
    """Result of one rule evaluation. ``tier`` and ``confirm_reasons`` must agree with ``findings``."""

    phase: Literal["plan", "pre_execute"]
    tier: Tier
    findings: list[RuleFinding]
    confirm_reasons: list[ConfirmReason]
    policy_digest: Sha256Hex
    evaluated_at: AwareDatetime

    @model_validator(mode="after")
    def _tier_matches_findings(self) -> RulesReport:
        if self.tier != tier_from_findings(self.findings):
            raise ValueError(f"tier {self.tier!r} contradicts the findings ({tier_from_findings(self.findings)!r}).")
        if self.confirm_reasons != confirm_reasons_of(self.findings):
            raise ValueError("confirm_reasons must list the confirm findings' reasons in first-seen order.")
        return self

    @classmethod
    def from_findings(
        cls,
        phase: Literal["plan", "pre_execute"],
        findings: Iterable[RuleFinding],
        *,
        policy_digest: str,
        evaluated_at: AwareDatetime,
    ) -> RulesReport:
        """Build a report whose tier and confirm reasons are derived from ``findings``."""
        items = list(findings)
        return cls(
            phase=phase,
            tier=tier_from_findings(items),
            findings=items,
            confirm_reasons=confirm_reasons_of(items),
            policy_digest=policy_digest,
            evaluated_at=evaluated_at,
        )


class PlanRecord(StrictModel):
    """A validated, frozen plan (blueprint 2.1). ``plan_hash`` covers recipe id/version/sha, resolved params,
    binding, envelope, estimate, FLEX preview, kind program, config hashes and backend, but not the label, rule
    reports, tier, summary or timestamps (``catalog.planner.plan_hash_of``). ``hashes`` holds
    the sha256 of the ``station``, ``policy``, ``pin_map`` and ``dut_profile`` files; ``summary`` is the canonical
    one-line ``plan_summary`` (ASCII, at most 400 characters)."""

    plan_id: PlanId
    plan_hash: Sha256Hex
    request: PlanRequest
    recipe_id: RecipeId
    recipe_version: int = Field(ge=1)
    recipe_sha: Sha256Hex
    kind: str
    resolved_params: dict[str, Quantity]
    binding: ChannelBinding
    envelope: CompiledEnvelope
    estimate: Estimate
    flex_preview: list[str]
    hashes: dict[str, Sha256Hex]
    backend: Backend
    program: dict[str, JsonValue] = Field(default_factory=dict)
    """The measurement kind's compiled program (JSON): exactly what ``kind.acquire`` executes; covered by
    ``plan_hash`` like everything except the label, rule reports, tier, summary and timestamps (WP1.7)."""
    rules: RulesReport
    tier: Tier
    summary: Annotated[str, Field(min_length=1, max_length=400, pattern=r"^[\x20-\x7e]+$")]
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> PlanRecord:
        if self.recipe_id != self.request.recipe_id:
            raise ValueError("recipe_id differs from the request.")
        if self.binding.pin_map != self.request.pin_map:
            raise ValueError("binding.pin_map differs from the request.")
        if self.rules.phase != "plan" or self.tier != self.rules.tier:
            raise ValueError("tier must equal the plan-phase rules report's tier.")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at.")
        return self
