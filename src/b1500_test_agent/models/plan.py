"""Plan request and frozen plan record with its binding, envelope, estimate and rule reports (blueprint v1 2.1, 2.5;
v2 2.3).

``PlanRecord`` is stored as ``<state_dir>/plans/<plan_id>.json`` and re-verified on every load; ``plan_id`` is
``"P-" + base32(plan_hash)[:10]``. Shapes the blueprint leaves open (``ChannelBinding``, ``CompiledEnvelope``) carry
what the rules, the ``OutputGuard`` and the plan summary need.

v2 additions: a role may be bound through a switch (``BoundChannel.via``, the route it needs) or to an MFCMU side
(``cmu_side``); a channel envelope may carry a pulse envelope (sources without compliance: SPGU, SMU pulse, WGFMU)
and an AC envelope (MFCMU); the compiled envelope lists the allowed routes and per-channel waveform limits; the
plan record names its execution ``mode`` (sync/async), its routes per phase and the ``file`` parameters it read
(with their sha256, so the plan hash covers the file content); ``RunProgress`` is the progress record of a run.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, field_serializer, model_validator

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
from b1500_test_agent.models.recipe import COMPLIANCE_FREE_FUNCTIONS, RecipeId, RoleFunction
from b1500_test_agent.models.routing import Route
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
    """One recipe role bound through the pin map: the terminal, and the channel/module or the GNDU behind it.

    ``cmu_side`` is set when the terminal is an MFCMU side (``"7H"``/``"7L"``). ``via`` is set when the terminal is
    wired through a switch output: the route (switch, output, state for the role's resource) the role needs; its
    ``channel`` is then the channel wired to that input of the switch port, or ``None`` when the wiring is unknown
    (R-PIN-01/R-ROUTE-01 block such a plan).
    """

    role: str
    terminal: str
    gndu: bool = False
    channel: Channel | None = None
    slot: Slot | None = None
    module_type: ModuleType | None = None
    module_model: str | None = None
    alias: Alias | None = None
    cmu_side: Literal["H", "L"] | None = None
    via: Route | None = None

    @model_validator(mode="after")
    def _channel_xor_gndu(self) -> BoundChannel:
        if self.gndu and (self.channel is not None or self.via is not None or self.cmu_side is not None):
            raise ValueError("A role bound to the GNDU has no channel, route or MFCMU side.")
        if not self.gndu and self.channel is None and self.via is None:
            raise ValueError("A role is bound either to a channel, through a switch route, or to the GNDU.")
        if self.cmu_side is not None and self.channel is None:
            raise ValueError("An MFCMU side needs the MFCMU channel.")
        return self


class ChannelBinding(StrictModel):
    """Role → channel binding of a plan (rule R-PIN-01 checks it against the station profile)."""

    pin_map: ConfigName
    roles: dict[str, BoundChannel]


class PulseEnvelope(StrictModel):
    """What a pulse source (SPGU, SMU pulse, WGFMU) may apply on one channel (``OutputGuard.check_pulse``).

    ``max_abs_v_dut`` is the worst case at the DUT including the ``SER`` divider / open-load doubling of a 50 Ohm
    source; ``max_on_time_s`` the total time at pulse level; ``max_short_circuit_a`` = ``V_open / (R_source +
    min_series_ohm)`` (R-SPGU-01; a ``high_z`` terminal makes it a residual shown in the summary).
    """

    max_abs_v_dut: float = Field(ge=0)
    min_width_s: float = Field(gt=0)
    max_width_s: float = Field(gt=0)
    max_duty: float = Field(gt=0, le=1)
    max_count: int = Field(ge=1)
    max_on_time_s: float = Field(ge=0)
    max_short_circuit_a: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> PulseEnvelope:
        if self.min_width_s > self.max_width_s:
            raise ValueError("min_width_s must not exceed max_width_s.")
        return self


class AcEnvelope(StrictModel):
    """What the MFCMU may apply on one channel (``OutputGuard.check_ac``): AC level, |DC bias| and frequency span."""

    max_vrms: float = Field(ge=0)
    max_dc_v: float = Field(ge=0)
    f_min_hz: float = Field(gt=0)
    f_max_hz: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> AcEnvelope:
        if self.f_min_hz > self.f_max_hz:
            raise ValueError("f_min_hz must not exceed f_max_hz.")
        return self


class WaveformLimits(StrictModel):
    """Size of the WGFMU waveform one channel may load (``OutputGuard.check_waveform``): vectors per pattern,
    measured points, total sequence time and the time grid every vector must lie on (10 ns)."""

    max_vectors: int = Field(ge=1)
    max_points: int = Field(ge=0)
    total_time_s: float = Field(ge=0)
    grid_s: float = Field(default=1e-8, gt=0)


class ChannelEnvelope(StrictModel):
    """Largest |V| and |I| (level or compliance) the plan may apply on one channel.

    ``function``, ``v_start`` and ``v_stop`` describe what the role does on the channel (first and last forced
    voltage; equal for a bias) so that the canonical plan summary can show it (blueprint 2.5). They are optional and
    must lie inside ``max_abs_v``, which stays the enforced limit. ``max_abs_i`` is ``None`` only for sources without
    a compliance (``pgu``/``wgfmu`` roles), which the pulse and waveform envelopes bound instead. ``pulse`` and
    ``ac`` are the pulse and AC envelopes of pulse and MFCMU roles.
    """

    role: str
    max_abs_v: float = Field(ge=0)
    max_abs_i: float | None = Field(ge=0)
    function: RoleFunction | None = None
    v_start: float | None = None
    v_stop: float | None = None
    pulse: PulseEnvelope | None = None
    ac: AcEnvelope | None = None

    @model_validator(mode="after")
    def _levels_inside_envelope(self) -> ChannelEnvelope:
        if (self.v_start is None) != (self.v_stop is None):
            raise ValueError("v_start and v_stop are set together.")
        for level in (self.v_start, self.v_stop):
            if level is not None and abs(level) > self.max_abs_v:
                raise ValueError(f"level {level} V lies outside max_abs_v {self.max_abs_v} V.")
        if self.max_abs_i is None and self.function not in COMPLIANCE_FREE_FUNCTIONS:
            raise ValueError(f"max_abs_i may be left out only for pgu/wgfmu roles, not {self.function}.")
        if self.pulse is not None and self.pulse.max_abs_v_dut > self.max_abs_v:
            raise ValueError("pulse.max_abs_v_dut lies outside max_abs_v.")
        if self.ac is not None and self.ac.max_dc_v > self.max_abs_v:
            raise ValueError("ac.max_dc_v lies outside max_abs_v.")
        return self


class CompiledEnvelope(StrictModel):
    """Per-channel allowlist enforced by the ``OutputGuard`` on every source command (blueprint v1 2.3, v2 2.3).

    ``routes`` are the switch routes the plan may set (a route to a switch's ``rest`` state is always allowed);
    ``waveform`` the WGFMU waveform limits per channel. Routes serialise sorted, so the plan hash is deterministic.
    """

    channels: dict[Channel, ChannelEnvelope]
    routes: frozenset[Route] = frozenset()
    waveform: dict[Channel, WaveformLimits] = Field(default_factory=dict)

    @field_serializer("routes")
    def _sorted_routes(self, routes: frozenset[Route]) -> list[Route]:
        return sorted(routes, key=Route.sort_key)

    @property
    def max_abs_v(self) -> float:
        """Largest |V| over all channels (0 when the plan sources nothing)."""
        return max((c.max_abs_v for c in self.channels.values()), default=0.0)

    @property
    def max_abs_i(self) -> float:
        """Largest |I| over the channels with a current limit (0 when the plan sources nothing)."""
        return max((c.max_abs_i for c in self.channels.values() if c.max_abs_i is not None), default=0.0)


class Estimate(StrictModel):
    """Size of a run: measurement points and expected duration.

    ``max_segment_s`` is the longest stretch between two checkpoints of the run (``tx.checkpoint``), i.e. the worst
    cancel latency; ``None`` means the kind has no checkpoints (the whole run is one segment). R-RUN-02 bounds it by
    ``policy.run_limits.segment_max_s`` for asynchronous runs.
    """

    points: int = Field(ge=0)
    duration_s: float = Field(ge=0)
    max_segment_s: float | None = Field(default=None, ge=0)


class ParamFile(StrictModel):
    """A ``file`` parameter's CSV as the planner found it (hashed into the plan; re-checked before every run).

    ``path`` is the parameter value (``recipes/waveforms/...`` or ``work/waveforms/...``), ``origin`` the folder
    kind (``work`` = ad-hoc, confirmed as ``adhoc_recipe``). ``sha256`` and ``size_bytes`` describe the file content;
    ``problem`` says why it could not be used (missing, too large, outside the allowed folders) and blocks the plan
    (R-PARAM-01).
    """

    path: str = Field(min_length=1)
    origin: Literal["library", "work"]
    sha256: Sha256Hex | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    problem: str | None = None

    @model_validator(mode="after")
    def _content_xor_problem(self) -> ParamFile:
        if (self.problem is None) != (self.sha256 is not None and self.size_bytes is not None):
            raise ValueError("A parameter file has either its sha256 and size or a problem.")
        return self


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
    mode: Literal["sync", "async"] = "sync"
    """``async`` when the estimate exceeds ``policy.run_limits.max_sync_run_s`` (R-RUN-02): ``run_plan`` returns
    ``running`` and progress is read with ``get_run``."""
    routes_by_phase: dict[str, list[Route]] = Field(default_factory=dict)
    """Switch routes the kind sets, per phase name (``main``, ``program``, ``read`` ...), in the order applied; every
    route is in ``envelope.routes`` or returns a switch to its ``rest`` state (checked by R-ROUTE-01 and the
    guard)."""
    files: dict[str, ParamFile] = Field(default_factory=dict)
    """``file`` parameters by name: path, origin and sha256 of the CSV read at validation."""
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

    @property
    def est_s(self) -> float:
        """Estimated run duration in seconds (``estimate.duration_s``)."""
        return self.estimate.duration_s


class RunProgress(StrictModel):
    """Progress of a run (``progress.json`` in the run folder; ``get_run include=progress``; blueprint v2 2.6).

    ``done``/``total`` count the kind's checkpoint units (points, segments, cycles); ``phase`` names the current
    phase; ``last_values`` holds the latest measured values by column for a live glance; ``eta_s`` is ``None`` when
    unknown.
    """

    state: Literal["running", "completed", "cancelled", "failed"]
    done: int = Field(ge=0)
    total: int = Field(ge=0)
    phase: str = ""
    elapsed_s: float = Field(ge=0)
    eta_s: float | None = Field(default=None, ge=0)
    last_values: dict[str, float] = Field(default_factory=dict)
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _done_within_total(self) -> RunProgress:
        if self.done > self.total:
            raise ValueError("done must not exceed total.")
        return self
