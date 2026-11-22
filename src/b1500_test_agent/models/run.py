"""Run lifecycle models: cleanup report, fault latch and lock records, abort request, run manifest, run program and
run summary (blueprint 2.4, 2.6, 2.7, 5.1; v2 2.6, 2.10).

``RunManifest`` is written once to ``<run>/manifest.json`` at finalize; ``RunProgram`` is ``<run>/program.json``
(the pulse/waveform program a run executed); ``RunSummary`` is what ``run_plan`` and ``run_confirmed_plan`` return;
``AbortRequest`` is ``<state_dir>/abort.json``, written by ``safe_shutdown`` (any process) and consumed by the run it
cancels (v2 2.6, ``session/abort.py``).
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
    "running", "cancelled",
]  # fmt: skip
"""Outcome of a run request (blueprint 5.1; ``aborted`` for runs interrupted by a fault or interrupt, 8.1). v2 2.6:
``running`` = an asynchronous run started and is still going (``run_plan`` returns at once; ``get_run`` follows it);
``cancelled`` = ``safe_shutdown`` stopped it at a checkpoint (verified cleanup; the rows acquired so far stay in
``partial.csv``)."""

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
    """One step of the transaction cleanup ``AB → SPP → DZ → routes → CL → ERRX drain → verify`` (blueprint 2.4, v2
    2.6); ``spgu_stop`` (v2 step 2) reads ``SPST?`` and sends ``SPP`` when an SPGU output is active, on instruments
    with an SPGU; ``routes`` (v2 step 5, WP9.2) returns every declared switch output to its ``rest`` state (16440A
    ``ERMOD 1`` + ``ERSSP``, SCUU ``SSP``, ASU ``SAP``) on stations that declare switches; ``restore`` comes after
    the verification and puts back a setting the run changed (v2 2.6, R-CAL-02: the auto-calibration state of an
    asynchronous run), never touching an output."""

    step: Literal["abort", "spgu_stop", "zero", "routes", "disconnect", "drain_errors", "verify", "device_clear",
                  "restore"]
    ok: bool
    attempt: int = Field(default=1, ge=1)
    detail: str = ""


class PositiveControl(StrictModel):
    """The ``LOP?`` positive control of a hardware transaction (blueprint v2 10.2 row 6.2; v1 ATV-1, ATV-23).

    ``LOP?`` is read once while the run's SMU output switches are on (right after ``CN``, before any source level
    is applied: the outputs force 0 V). ``codes`` holds the two-digit code of each of their slots (PG p446-447
    (4-128) Table 4-26: ``00`` = off, ``01`` = forcing voltage, ...). ``ok`` = every slot reported a non-``00`` code,
    which shows that ``LOP?`` sees this instrument's output switches; only then is the cleanup's all-``00`` answer
    evidence that the outputs are off (``verified: lop``). A failed control aborts the run before any level is set
    and leaves the cleanup unverified (fault latched). Not used on the simulator, whose cleanup reads the simulated
    state directly (``verified: sim_state``).
    """

    channels: list[int] = Field(min_length=1)
    """The channels the run switched on with ``CN``."""
    codes: dict[int, str]
    """Slot -> ``LOP?`` code read after ``CN`` (the slots of ``channels``)."""
    ok: bool
    detail: str = ""


class CleanupReport(StrictModel):
    """Result of a cleanup: the steps run, how the safe state was verified, per-channel output state afterwards
    and whether the fault latch was set because verification failed. ``errors`` are the ``ERRX?`` entries drained
    by the cleanup (WP1.6; ``FaultLatch.clear`` requires none). ``positive_control`` is the hardware ``LOP?``
    reading taken while the run's outputs were on (``None`` on the simulator and in transactions that switch no
    output on, e.g. ``system.*`` and ``safe_shutdown``): with ``verified: lop`` the two readings together are the
    cleanup-verification evidence (v2 WP6.2)."""

    steps: list[CleanupStep]
    verified: CleanupVerification
    outputs_after: dict[int, str]
    latched_fault: bool
    errors: list[InstrumentError] = Field(default_factory=list)
    positive_control: PositiveControl | None = None
    switches_after: dict[str, str] = Field(default_factory=dict)
    """Declared switch output (``SEL1.OUT1``) -> the state the verification read back (``open``, ``smu`` ...;
    ``unreadable`` when the read failed, ``not installed`` for an SCUU/ASU that does not answer; v2 2.6 step 8,
    WP9.2); empty when the station declares no switch."""


class FaultRecord(StrictModel):
    """Contents of ``<state_dir>/fault.json`` while the fault latch is set; every sourcing path then refuses."""

    reason: str = Field(min_length=1)
    run_id: RunId | None = None
    set_at: AwareDatetime


class AbortRequest(StrictModel):
    """``<state_dir>/abort.json`` (blueprint v2 2.6): a request to cancel the running run, written by ``safe_shutdown``
    of any process (MCP server, CLI), by the MCP server's shutdown hook or by the CLI's Ctrl-C. ``run_id`` names the
    run it targets (``None`` = whichever run is running); a run ignores requests made before it started and requests
    for another run. The run that honours it removes it after its verified cleanup (``consume``); the writer removes
    it when no run took it (``withdraw``)."""

    id: str = Field(pattern=r"^[0-9a-f]{8,32}$")
    requested_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=300)
    adapter: Adapter | None = None
    pid: int = Field(default=0, ge=0)
    host: str = "unknown"
    run_id: RunId | None = None


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
    refused before a run folder existed; on ``summary_mismatch`` ``summary`` carries the current plan summary. An
    asynchronous run (v2 2.6) returns ``outcome: running`` with its ``run_id`` and ``eta_s`` (estimated seconds
    until it ends) as soon as it has started; ``get_run`` follows it."""

    run_id: RunId | None = None
    plan_id: PlanId | None = None
    outcome: RunOutcome
    status_counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    quality_verdict: TrustLevel | None = None
    analyses: list[ExtractionResult] = Field(default_factory=list)
    cleanup_verified: CleanupVerification | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    summary: str | None = None
    eta_s: float | None = Field(default=None, ge=0)
