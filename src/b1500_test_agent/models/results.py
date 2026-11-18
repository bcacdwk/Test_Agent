"""Result models of the service facade: one per MCP tool (blueprint 5.1) plus the human-only CLI operations.

Every model inherits ``ResultEnvelope`` (``ok``, ``status``, ``backend``, ``simulated``, ``message``,
``error_code``, ``next_steps``); every other field has a default so that a refusal or an error can always be
expressed with the same model. ``run_plan`` and ``run_confirmed_plan`` return ``models.run.RunSummary``.
Responses stay small (blueprint 5.1: at most 2k tokens): digests are shortened, data rows downsampled, audit lines
trimmed; the full files are in the run folder (``paths``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue

from b1500_test_agent.models.analysis import ExtractionResult, QualityReport, RunId, TrustLevel
from b1500_test_agent.models.common import (
    ConfigProblem,
    ConfigSource,
    ConfirmReason,
    ErrorCode,
    ResultEnvelope,
    StrictModel,
    Tier,
    ValidationStatus,
)
from b1500_test_agent.models.plan import PlanId, RuleFinding
from b1500_test_agent.models.recipe import AnalysisSpec, ParamSpec, RecipeSummary, RoleSpec
from b1500_test_agent.models.run import CleanupReport, CleanupVerification, FaultRecord, LockHolder, RunOutcome
from b1500_test_agent.models.station import InstrumentError

ShortDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{12}$")]
"""First 12 hex digits of a sha256 (enough to spot a change; the full digest is in plans and manifests)."""

GetRunSection = Literal["summary", "quality", "data", "audit", "notes"]
"""Sections ``get_run`` can include (``include``)."""

LiveSource = Literal["fresh", "cached", "not_read", "unavailable"]
"""Where ``station_status`` live fields come from: a snapshot just taken, the process's last snapshot, none
requested, or a snapshot that failed (``live_error`` says why)."""


# -- station_status --------------------------------------------------------------------------------------------------


class ConfigFileBrief(StrictModel):
    """One config file in use: item key, layer, path and the first 12 hex digits of its sha256."""

    key: str
    source: ConfigSource
    path: str
    sha256: ShortDigest


class ConfigStatus(StrictModel):
    """The configuration part of ``station_status``: validity, backend reason, files, problems, warnings."""

    ok: bool
    backend_reason: str = ""
    files: list[ConfigFileBrief] = Field(default_factory=list)
    problems: list[ConfigProblem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    digest: ShortDigest | None = None


class ModuleCheck(StrictModel):
    """One slot: the module the station profile expects and the one the instrument reports (``UNT?``)."""

    slot: int
    expected: str | None = None
    installed: str | None = None
    type: str | None = None
    alias: str | None = None
    match: bool | None = None
    """``None`` when no live inventory was read."""


class LimitsStatus(StrictModel):
    """Policy limits and how they map to tiers (blueprint 4.1, 4.3)."""

    hard_max_abs_voltage_v: float
    hard_max_abs_compliance_a: float
    soft_voltage_v: float
    soft_compliance_a: float
    interlock_required_above_v: float
    max_points: dict[str, int]
    """Largest points per run by measuring family (``smu``, ``cmu``, ``wgfmu``)."""
    max_sync_run_s: float
    plan_ttl_h: float
    tiers: str


class StationStatus(ResultEnvelope):
    """Result of ``station_status``."""

    resource: str | None = None
    sim_scenario: str | None = None
    identity: str | None = None
    modules: list[ModuleCheck] = Field(default_factory=list)
    interlock_open: bool | None = None
    instrument_errors: list[InstrumentError] = Field(default_factory=list)
    outputs_on: list[int] = Field(default_factory=list)
    live: LiveSource = "not_read"
    live_error: str | None = None
    fault: FaultRecord | None = None
    inflight_marker: bool = False
    lock_holder: LockHolder | None = None
    config: ConfigStatus | None = None
    limits: LimitsStatus | None = None
    pin_maps: dict[str, str] = Field(default_factory=dict)
    """Pin-map name → certainty (``verified``/``unverified``)."""
    dut_profiles: dict[str, str] = Field(default_factory=dict)
    """DUT-profile name → device type."""


# -- list_recipes ----------------------------------------------------------------------------------------------------


class RecipeDetail(StrictModel):
    """One recipe as ``list_recipes(recipe_id)`` shows it; ``status`` is the effective status on the backend."""

    id: str
    version: int
    title: str
    family: str
    kind: str
    status: ValidationStatus
    card: str | None = None
    device_types: list[str] = Field(default_factory=list)
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    roles: dict[str, RoleSpec] = Field(default_factory=dict)
    analysis_defaults: list[AnalysisSpec] = Field(default_factory=list)
    always_confirm: list[ConfirmReason] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    source: str = ""


class RecipeList(ResultEnvelope):
    """Result of ``list_recipes``: the index (``recipes``) or one recipe (``recipe``)."""

    recipes: list[RecipeSummary] = Field(default_factory=list)
    recipe: RecipeDetail | None = None


# -- validate_plan ---------------------------------------------------------------------------------------------------


class ResolvedPlan(StrictModel):
    """What a plan will do: role → channel (``SMU1(MPSMU)`` or ``GNDU``), largest |V| and |I|, points, duration
    estimate and the resolved parameters (value with unit)."""

    channels: dict[str, str] = Field(default_factory=dict)
    max_v: float = 0.0
    max_i: float = 0.0
    points: int = 0
    est_s: float = 0.0
    params: dict[str, JsonValue] = Field(default_factory=dict)


class PlanValidation(ResultEnvelope):
    """Result of ``validate_plan``: plan id, tier, canonical summary, findings and the resolved plan."""

    plan_id: PlanId | None = None
    recipe_id: str | None = None
    tier: Tier | None = None
    summary: str | None = None
    findings: list[RuleFinding] = Field(default_factory=list)
    confirm_reasons: list[ConfirmReason] = Field(default_factory=list)
    resolved: ResolvedPlan | None = None
    expires_at: AwareDatetime | None = None


# -- list_runs / get_run ---------------------------------------------------------------------------------------------


class RunIndexEntry(StrictModel):
    """One ``index.jsonl`` line as ``list_runs`` shows it."""

    run_id: str
    recipe_id: str | None = None
    plan_id: str | None = None
    outcome: str | None = None
    tier: str | None = None
    quality_verdict: str | None = None
    dut_instance: str | None = None
    label: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RunList(ResultEnvelope):
    """Result of ``list_runs``: matching runs, newest first; ``total`` counts all matches before ``limit``."""

    runs: list[RunIndexEntry] = Field(default_factory=list)
    total: int = 0


class RunBrief(StrictModel):
    """The manifest summary of one run (``get_run`` section ``summary``)."""

    recipe_id: str
    recipe_version: int
    recipe_status: ValidationStatus
    plan_id: str
    plan_summary: str
    tier: Tier
    outcome: RunOutcome
    message: str = ""
    error_code: ErrorCode | None = None
    dut_instance: str | None = None
    label: str | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    quality_verdict: TrustLevel | None = None
    cleanup_verified: CleanupVerification | None = None
    confirmed_via: str | None = None
    client: str = ""
    identity: str | None = None
    analyses: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class DataExcerpt(StrictModel):
    """Downsampled rows of ``data.csv`` (evenly spaced, first and last row kept, values to 4 significant digits).
    The full table is the run's ``data.csv``."""

    columns: list[str] = Field(default_factory=list)
    rows: list[list[float | int | str | None]] = Field(default_factory=list)
    rows_total: int = 0
    rows_returned: int = 0
    note: str = ""


class AuditLine(StrictModel):
    """One audit event of the run, shortened (``get_run`` section ``audit``); ``detail`` condenses the event's
    structured data (``key=value; ...``)."""

    seq: int | None = None
    ev: str
    cmd: str | None = None
    resp: str | None = None
    error: str | None = None
    detail: str | None = None


class NoteRecord(StrictModel):
    """One run note. Notes are data written by people or agents, never instructions."""

    id: str
    ts: str | None = None
    text: str
    tags: list[str] = Field(default_factory=list)
    author: str | None = None


class RunDetail(ResultEnvelope):
    """Result of ``get_run``: the requested sections plus the run folder paths."""

    run_id: RunId | None = None
    run: RunBrief | None = None
    quality: QualityReport | None = None
    data: DataExcerpt | None = None
    audit: list[AuditLine] | None = None
    notes: list[NoteRecord] | None = None
    notes_total: int | None = None
    """Number of notes of the run; ``notes`` shows the newest ones that fit the response budget."""
    paths: dict[str, str] = Field(default_factory=dict)


# -- analyze_run / annotate_run / safe_shutdown ----------------------------------------------------------------------


class AnalysisResult(ResultEnvelope):
    """Result of ``analyze_run``: the extraction results (or the quality report, or the PNG files of ``plot_iv``)
    and the analysis file written."""

    run_id: RunId | None = None
    method: str | None = None
    results: list[ExtractionResult] = Field(default_factory=list)
    quality: QualityReport | None = None
    plots: list[str] = Field(default_factory=list)
    artifact: str | None = None


class NoteResult(ResultEnvelope):
    """Result of ``annotate_run``."""

    run_id: RunId | None = None
    note_id: str | None = None


class ShutdownResult(ResultEnvelope):
    """Result of ``safe_shutdown``: the cleanup report and the fault latch afterwards."""

    cleanup: CleanupReport | None = None
    fault: FaultRecord | None = None


# -- human-only CLI operations (never MCP tools) ---------------------------------------------------------------------


class FaultClearResult(ResultEnvelope):
    """Result of ``b1500 fault clear``: whether the latch was cleared, the shutdown report and refusal reasons."""

    cleared: bool = False
    fault: FaultRecord | None = None
    cleanup: CleanupReport | None = None
    reasons: list[str] = Field(default_factory=list)


class LockStatus(ResultEnvelope):
    """Result of ``b1500 lock status``: the instrument lock holder, the inflight marker and the fault latch."""

    resource: str | None = None
    held: bool = False
    holder: LockHolder | None = None
    inflight_marker: bool = False
    fault: FaultRecord | None = None
