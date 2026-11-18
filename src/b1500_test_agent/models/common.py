"""Shared base model, vocabulary literals, the result envelope and config-file records (blueprint 2.1, 4.1).

Every model in this package derives from ``StrictModel``: unknown fields, non-finite numbers and edits after
construction are rejected, so a model that validated once stays valid. Literal vocabularies are spelled exactly as
in the blueprint because they appear in tool results, plan files and run manifests.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Backend = Literal["sim", "visa"]
"""Instrument backend: the in-process simulator or a real B1500A over VISA. Nothing ever selects visa implicitly."""

ValidationStatus = Literal["not_implemented", "draft", "sim_validated", "hw_validated"]
"""Recipe validation status (blueprint 2.6, decision 7)."""

Tier = Literal["ok", "needs_confirmation", "blocked"]
"""Plan tier (blueprint 4.3): ``ok`` runs via ``run_plan``; ``needs_confirmation`` only via ``run_confirmed_plan``."""

ResultStatus = Literal["ok", "refused", "needs_confirmation", "blocked", "not_implemented", "busy", "fault", "error"]
"""``ResultEnvelope.status`` of every service and tool result."""

ErrorCode = Literal[
    "invalid_input", "invalid_config", "unknown_plan", "plan_expired", "plan_stale",
    "blocked_by_rules", "confirmation_required", "summary_mismatch", "not_implemented", "instrument_busy",
    "fault_latched", "transport_error", "instrument_error", "cleanup_unverified", "internal", "run_cancelled",
]  # fmt: skip
"""Machine-readable error codes of ``ResultEnvelope.error_code`` (``run_cancelled``: a run stopped at a checkpoint
because ``safe_shutdown`` asked for it, v2 2.6)."""

ConfirmReason = Literal[
    "soft_limit", "dut_envelope", "unverified_pin_map", "draft_recipe", "first_hw_run",
    "adhoc_recipe", "destructive", "system_self_test", "system_self_cal",
    "soft_pulse", "soft_cmu", "long_run", "physical_setup", "unverified_topology",
]  # fmt: skip
"""Why a plan needs a human confirmation (v1 blueprint 2.5, v2 blueprint 2.1/2.8); set on ``confirm`` rule findings
and recipe ``always_confirm``. v2 adds ``soft_pulse`` (above ``policy.pulse`` soft bands, R-PULSE-03), ``soft_cmu``
(above ``policy.cmu`` soft bands, R-CMU-01), ``long_run`` (estimate above ``run_limits.long_run_confirm_s``,
R-RUN-02), ``physical_setup`` (the human changes the probe state, e.g. CMU open/short corrections) and
``unverified_topology`` (an ``unverified`` switch or wiring is involved, R-ROUTE-02); custom waveform files from
``work/`` reuse ``adhoc_recipe``."""

JsonScalar = str | int | float | bool | None
"""A JSON scalar, e.g. the observed value or limit of a rule finding."""

ConfigSource = Literal["override", "local", "example"]
"""Where a config file was found: ``override`` = ``$B1500_CONFIG_DIR`` (tests and the M3 runner only),
``local`` = ``config/local/`` (human-owned live config), ``example`` = committed file under ``config/``."""

ConfigName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
"""Name of a pin map, DUT profile or sim scenario: its file name without ``.yaml``/``.example.yaml``."""

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
"""Lower-case hex SHA-256 digest."""

Alias = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")]
"""Human-readable name of a module (``SMU3``, ``CMU1``) or a switch (``SEL1``, ``RSU201``) in the station profile."""


class StrictModel(BaseModel):
    """Strict, immutable base: unknown fields, non-finite numbers and post-construction edits are rejected."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True, frozen=True)


class ResultEnvelope(StrictModel):
    """Common head of every service and MCP tool result (blueprint 2.1).

    ``simulated`` is true exactly when ``backend`` is ``sim``, so a reader can never mistake simulator output for a
    measurement.
    """

    ok: bool
    status: ResultStatus
    backend: Backend
    simulated: bool
    message: str = ""
    error_code: ErrorCode | None = None
    next_steps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _simulated_matches_backend(self) -> ResultEnvelope:
        if self.simulated != (self.backend == "sim"):
            raise ValueError("simulated must be true exactly when backend is 'sim'.")
        return self


class ConfigFile(StrictModel):
    """One configuration file actually used: hashed into plans and recorded in every run manifest.

    ``key`` names the config item (``settings``, ``station``, ``policy``, ``pinmaps/<name>``, ``duts/<name>``,
    ``sim/scenarios/<name>``, ``sim/faults/<name>``). ``path`` is repository-relative (POSIX separators) when the
    file is inside the repository, else absolute. ``sha256`` is the digest of the raw file bytes.
    """

    key: str = Field(min_length=1)
    path: str = Field(min_length=1)
    source: ConfigSource
    sha256: Sha256Hex


class ConfigProblem(StrictModel):
    """One reason why the configuration is invalid (error code ``invalid_config``, rule R-CFG-01).

    ``file`` is the config key or path the problem belongs to (``None`` for global problems such as a missing
    repository); ``location`` is the dotted field path inside that file when the problem is a schema error.
    """

    file: str | None = None
    location: str | None = None
    message: str = Field(min_length=1)


class ConfigReport(StrictModel):
    """Result of ``b1500 config check`` and the config part of ``station_status``; never raises.

    ``backend`` is the backend the settings select (``None`` when no settings file could be read);
    ``backend_reason`` says which file chose it and why. ``files`` lists every file used, ``problems`` the reasons
    for ``invalid_config``, ``warnings`` non-blocking hints, ``paths`` the effective runtime directories.
    """

    ok: bool
    error_code: ErrorCode | None = None
    backend: Backend | None = None
    backend_reason: str = ""
    files: list[ConfigFile] = Field(default_factory=list)
    problems: list[ConfigProblem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    paths: dict[str, str] = Field(default_factory=dict)
    digest: Sha256Hex | None = None

    @model_validator(mode="after")
    def _ok_iff_no_problems(self) -> ConfigReport:
        if self.ok != (not self.problems):
            raise ValueError("ok must be true exactly when there are no problems.")
        if self.ok != (self.error_code is None):
            raise ValueError("error_code is set exactly when ok is false.")
        return self
