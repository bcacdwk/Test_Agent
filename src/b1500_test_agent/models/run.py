"""Run lifecycle models: cleanup report, fault latch and lock records, run manifest, run program and run summary
(blueprint 2.4, 2.6, 2.7, 5.1; v2 2.10).

``RunManifest`` is written once to ``<run>/manifest.json`` at finalize; ``RunProgram`` is ``<run>/program.json``
(the pulse/waveform program a run executed); ``RunSummary`` is what ``run_plan`` and ``run_confirmed_plan`` return.
WP1.6/WP1.7 may extend these with the fields their implementations need.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from b1500_test_agent.models.analysis import ExtractionResult, RunId, TrustLevel
from b1500_test_agent.models.common import (
    Backend,
    ConfigFile,
    ErrorCode,
    JsonScalar,
    ResultEnvelope,
    Sha256Hex,
    StrictModel,
    Tier,
    ValidationStatus,
)
from b1500_test_agent.models.plan import ParamFile, PlanId, PlanRecord, RuleFinding, RulesReport
from b1500_test_agent.models.recipe import RecipeId
from b1500_test_agent.models.station import Identity, InstrumentError, ModuleInventory

Adapter = Literal["mcp", "cli"]
RunOutcome = Literal[
    "completed", "completed_with_flags", "failed", "aborted", "refused", "confirmation_required", "not_implemented",
]  # fmt: skip
"""Outcome of a run request (blueprint 5.1; ``aborted`` for runs interrupted by a fault or interrupt, 8.1)."""

CleanupVerification = Literal["lop", "sim_state", "unverified"]


class ClientInfo(StrictModel):
    """Who asked for an action: the adapter and the optional ``B1500_SESSION_TAG`` of the harness session."""

    adapter: Adapter
    session_tag: str | None = None


class LockHolder(StrictModel):
    """JSON sidecar of the instrument lock (blueprint 2.4)."""

    pid: int = Field(ge=0)
    host: str
    adapter: Adapter
    plan_id: PlanId | None = None
    since: AwareDatetime


class CleanupStep(StrictModel):
    """One step of the transaction cleanup ``AB → DZ → CL → ERRX drain → verify`` (blueprint 2.4)."""

    step: Literal["abort", "zero", "disconnect", "drain_errors", "verify", "device_clear"]
    ok: bool
    attempt: int = Field(default=1, ge=1)
    detail: str = ""


class CleanupReport(StrictModel):
    """Result of a cleanup: the steps run, how the safe state was verified, per-channel output state afterwards
    and whether the fault latch was set because verification failed. ``errors`` are the ``ERRX?`` entries drained
    by the cleanup (WP1.6; ``FaultLatch.clear`` requires none)."""

    steps: list[CleanupStep]
    verified: CleanupVerification
    outputs_after: dict[int, str]
    latched_fault: bool
    errors: list[InstrumentError] = Field(default_factory=list)


class FaultRecord(StrictModel):
    """Contents of ``<state_dir>/fault.json`` while the fault latch is set; every sourcing path then refuses."""

    reason: str = Field(min_length=1)
    run_id: RunId | None = None
    set_at: AwareDatetime


ProgramSource = Literal["spgu", "smu", "wgfmu"]
"""Module family that executes a pulse/waveform program: HV-SPGU pulses, SMU pulses, WGFMU waveforms."""


class ProgramEntry(StrictModel):
    """One pulse or waveform program of a run: the ``source`` family, the channels it drives, ``spec`` = the kind's
    program object as JSON (e.g. a ``WaveformProgram`` or an SPGU pulse setup, ``model_dump(mode="json")``) and
    ``preview`` = human-readable lines (e.g. ``WaveformProgram.preview()``)."""

    source: ProgramSource
    channels: list[int] = Field(min_length=1)
    spec: dict[str, JsonValue]
    preview: list[str] = Field(default_factory=list)


class RunProgram(StrictModel):
    """``<run>/program.json`` (blueprint v2 2.10): the pulse/waveform programs a run executed, by name (e.g.
    ``program``, ``erase``, ``read``, ``stress``), and the ``file`` parameters they were built from (the plan's
    ``ParamFile`` records: path, origin, sha256). Written once by the kind before the source starts; covered by the
    manifest's sha256 list."""

    kind: str = Field(min_length=1)
    programs: dict[str, ProgramEntry] = Field(min_length=1)
    files: dict[str, ParamFile] = Field(default_factory=dict)


class RunManifest(StrictModel):
    """``manifest.json`` of a run folder (blueprint 2.7). ``hashes`` are the plan's config hashes;
    ``config_files`` every config file used (path + sha256); ``rules`` the plan and pre-execute reports;
    ``files`` the sha256 of every file in the run folder (path relative to the run folder, POSIX separators)."""

    run_id: RunId
    plan: PlanRecord
    plan_hash: Sha256Hex
    recipe_id: RecipeId
    recipe_version: int = Field(ge=1)
    recipe_sha: Sha256Hex
    recipe_status: ValidationStatus
    backend: Backend
    simulated: bool
    identity: Identity | None = None
    inventory: ModuleInventory | None = None
    hashes: dict[str, Sha256Hex]
    config_files: list[ConfigFile]
    rules: list[RulesReport]
    tier: Tier
    confirmed_summary: str | None = None
    confirmed_via: Literal["run_confirmed_plan", "cli --confirm"] | None = None
    client: ClientInfo
    software_version: str
    dut_instance: str | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    outcome: RunOutcome
    cleanup: CleanupReport | None = None
    assumptions: list[str] = Field(default_factory=list)
    files: dict[str, Sha256Hex] = Field(default_factory=dict)
    message: str = ""
    """Why the run ended as it did (failure reason, refusal), empty for a clean completion (WP1.7)."""
    error_code: ErrorCode | None = None
    status_counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    """Measured values per status letter over all measured columns (``N``, ``C``, ``T``, ``V`` ...)."""
    quality_verdict: TrustLevel | None = None
    quality_findings: list[RuleFinding] = Field(default_factory=list)
    """R-QUAL-* findings of the post-run classification (blueprint 4.1 point 4)."""
    kind_result: dict[str, JsonScalar] = Field(default_factory=dict)
    """Kind-specific result facts, e.g. ``{"operation": "self_test", "result": 0}`` for system recipes."""
    timings: dict[str, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    """Durations in seconds (``transaction_s``, ``total_s`` ...)."""

    @model_validator(mode="after")
    def _consistent(self) -> RunManifest:
        if self.simulated != (self.backend == "sim"):
            raise ValueError("simulated must be true exactly when backend is 'sim'.")
        if self.run_id[0] != ("S" if self.backend == "sim" else "H"):
            raise ValueError("Simulator run ids start with S, hardware run ids with H.")
        if (self.confirmed_summary is None) != (self.confirmed_via is None):
            raise ValueError("confirmed_summary and confirmed_via are set together.")
        if self.plan_hash != self.plan.plan_hash:
            raise ValueError("plan_hash differs from the plan.")
        return self


class RunSummary(ResultEnvelope):
    """Result of ``run_plan``/``run_confirmed_plan`` (blueprint 5.1). ``run_id`` is ``None`` when the request was
    refused before a run folder existed; on ``summary_mismatch`` ``summary`` carries the current plan summary."""

    run_id: RunId | None = None
    plan_id: PlanId | None = None
    outcome: RunOutcome
    status_counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    quality_verdict: TrustLevel | None = None
    analyses: list[ExtractionResult] = Field(default_factory=list)
    cleanup_verified: CleanupVerification | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    summary: str | None = None
