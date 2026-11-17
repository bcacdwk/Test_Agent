"""Typed contracts for the fake D atom family (post-acquisition analysis placeholders).

D atoms consume evidence that A/C tools already returned and emit placeholder products.
Under user decision U1 every D atom is a fake stub: products are ``ProductRef`` placeholders
whose ``content`` is always ``None``. No model here authorizes, approves or gates hardware.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from b1500_test_agent.schemas import c_flow

SCHEMA_VERSION = "d_atom/1"
PLACEHOLDER_ALGORITHM_VERSION = "placeholder-0"
U3_TRUST_POLICY_VERSION = "u3-2026-11-17"
MAX_INLINE_POINTS = 100_000

# ---------------------------------------------------------------------------
# Closed vocabularies (adding a token requires arbitration)
# ---------------------------------------------------------------------------

Stage = Literal["ingest", "qualify", "shape", "derive", "extract", "assess", "archive", "render"]
D_STAGES: tuple[str, ...] = get_args(Stage)

D_STAGE_SUBJECTS: dict[str, tuple[str, ...]] = {
    "ingest": ("request", "smu", "cmu", "wgfmu", "easyexpert"),
    "qualify": ("dataset", "run", "iv", "cv", "timeseries"),
    "shape": ("dataset",),
    "derive": ("curve", "dataset", "timeseries"),
    "extract": ("leakage", "transfer", "output", "cv"),
    "assess": ("value", "dataset"),
    "archive": ("run",),
    "render": ("dataset", "run"),
}

D_VERBS: tuple[str, ...] = (
    "classify_status",
    "grade_trust",
    "split_segments",
    "stack_family",
    "normalize_geometry",
    "compute_derivative",
    "interpolate",
    "fit_linear",
    "compare_reference",
    "write_bundle",
    "load_bundle",
)
D_VERB_PREFIXES: tuple[str, ...] = ("build_", "check_", "summarize_")
D_EXTRACT_ACTIONS: tuple[str, ...] = (
    "current",
    "vth",
    "gm_max",
    "ss",
    "on_off",
    "voltage_shift",
    "ron",
    "breakdown_voltage",
    "cox",
    "vfb",
)
D_FORBIDDEN_NAME_TOKENS: tuple[str, ...] = (
    "mosfet",
    "fefet",
    "sweep",
    "pulse",
    "validate",
    "approve",
    "safe",
)

# Keys read by the C runner as failures or scraped as measurement data (c_flows.py).
BANNED_RESULT_KEYS: frozenset[str] = frozenset(
    {"status", "passed", "result_code", "rows", "values", "sample", "measurement", "outcome"}
)

ProductType = Literal[
    "expectation",
    "dataset",
    "check_report",
    "trust_summary",
    "view",
    "derived",
    "extraction_result",
    "verdict",
    "manifest",
    "bundle_plan",
    "plot_spec",
    "table",
    "report",
]
PRODUCT_TYPES: tuple[str, ...] = get_args(ProductType)

DataOrigin = Literal["synthetic", "fixture", "instrument"]
# Weakest first: weakest wins when origins are combined.
DATA_ORIGIN_ORDER: tuple[str, ...] = ("synthetic", "fixture", "instrument")

AnalysisState = Literal[
    "not_computed", "complete", "inconclusive", "not_extractable", "rejected_input"
]
ErrorType = Literal[
    "rejected_input", "context_missing", "unit_mismatch", "size_limit", "internal_error"
]
CheckOutcome = Literal["pass", "flag", "fail", "inconclusive", "not_applicable"]
TrustLevel = Literal["trusted", "trusted_with_flags", "needs_review", "untrusted", "synthetic_only"]
VerdictLabel = Literal["pass", "fail", "inconclusive", "synthetic_only"]
VerdictScope = Literal["instrument", "fixture"]
Severity = Literal["info", "warning", "error"]
Bound = Literal["exact", "upper", "lower"]
WriteRefusal = Literal["fake_mode", "synthetic_origin", "fixture_requires_test_root"]

# Units are never inferred from magnitude; SS may also be stated in mV/dec.
Unit = Literal[
    "V", "A", "s", "Hz", "F", "S", "Ohm", "H", "rad", "deg", "1",
    "A/m", "A/m^2", "F/m^2", "V/dec", "mV/dec",
]  # fmt: skip

# C flow kinds (``C_flow_<kind>``) whose typed request can seed a D expectation.
AcquisitionKind = Literal[
    "spot_smu_iv",
    "sweep_smu_staircase",
    "sweep_smu_staircase_biased",
    "pulse_smu_spot",
    "spot_cmu_impedance",
    "sweep_cmu_cv",
    "sweep_cmu_cf",
    "sweep_cmu_ac_level",
    "pulse_cmu_spot",
    "pulse_cmu_cv",
    "waveform_wgfmu_acquire",
]

# MFCMU measurement parameters, PG Ed. 15 Table 4-16 (name -> IMP code).
IMP_MODEL_CODES: dict[str, int] = {
    "R-X": 1,
    "G-B": 2,
    "Z-theta_rad": 10,
    "Z-theta_deg": 11,
    "Y-theta_rad": 20,
    "Y-theta_deg": 21,
    "Cp-G": 100,
    "Cp-D": 101,
    "Cp-Q": 102,
    "Cp-Rp": 103,
    "Cs-Rs": 200,
    "Cs-D": 201,
    "Cs-Q": 202,
    "Lp-G": 300,
    "Lp-D": 301,
    "Lp-Q": 302,
    "Lp-Rp": 303,
    "Ls-Rs": 400,
    "Ls-D": 401,
    "Ls-Q": 402,
}
ImpModel = Literal[
    "R-X", "G-B", "Z-theta_rad", "Z-theta_deg", "Y-theta_rad", "Y-theta_deg",
    "Cp-G", "Cp-D", "Cp-Q", "Cp-Rp", "Cs-Rs", "Cs-D", "Cs-Q",
    "Lp-G", "Lp-D", "Lp-Q", "Lp-Rp", "Ls-Rs", "Ls-D", "Ls-Q",
]  # fmt: skip

# Named parameters that criteria may target, with the units each accepts.
CriterionParameter = Literal[
    "leakage_current",
    "leakage_current_max",
    "vth",
    "gm_max",
    "vg_at_gm_max",
    "ss",
    "ion",
    "ioff",
    "on_off_ratio",
    "voltage_shift",
    "ron",
    "breakdown_voltage",
    "cox",
    "vfb",
]
PARAMETER_UNITS: dict[str, frozenset[str]] = {
    "leakage_current": frozenset({"A"}),
    "leakage_current_max": frozenset({"A"}),
    "vth": frozenset({"V"}),
    "gm_max": frozenset({"S"}),
    "vg_at_gm_max": frozenset({"V"}),
    "ss": frozenset({"V/dec", "mV/dec"}),
    "ion": frozenset({"A", "A/m"}),
    "ioff": frozenset({"A", "A/m"}),
    "on_off_ratio": frozenset({"1"}),
    "voltage_shift": frozenset({"V"}),
    "ron": frozenset({"Ohm"}),
    "breakdown_voltage": frozenset({"V"}),
    "cox": frozenset({"F", "F/m^2"}),
    "vfb": frozenset({"V"}),
}

# Same bound as the C request channel (schemas/c_flow.py): any channel a C flow accepts must be
# nameable in D, including subchannel numbers 101-1002 (PG Ed.15 Table 4-1, PDF 334).
Channel = c_flow.Channel
Terminal = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
ColumnName = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveFloat = Annotated[float, Field(gt=0)]


class DModel(BaseModel):
    """Reject unknown fields and non-finite values before any D stub runs."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


# ---------------------------------------------------------------------------
# Placeholder product reference (amendment M1 / DG1)
# ---------------------------------------------------------------------------


class ProductRef(DModel):
    """Reference to a D product; under U1 always a content-free placeholder.

    ``product_id`` is ``placeholder:<producer>:<16 hex of SHA-256 of canonical inputs>`` and
    never contains a timestamp. A placeholder can never carry content, so no number can
    ride on it.
    """

    ref_kind: Literal["placeholder"] = "placeholder"
    product_type: ProductType
    product_id: Annotated[str, Field(pattern=r"^placeholder:D_atom_[a-z0-9_]+:[0-9a-f]{16}$")]
    producer: Annotated[str, Field(pattern=r"^D_atom_[a-z0-9_]+$")]
    analysis_state: Literal["not_computed"] = "not_computed"
    data_origin: DataOrigin
    synthetic: bool
    content: dict[str, Any] | None = None
    upstream: Annotated[list[str], Field(max_length=64)] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_placeholder(self) -> "ProductRef":
        if self.ref_kind == "placeholder" and self.content is not None:
            raise ValueError("A placeholder ProductRef must have content None.")
        if self.synthetic != (self.data_origin == "synthetic"):
            raise ValueError("synthetic must equal (data_origin == 'synthetic').")
        if not self.product_id.startswith(f"placeholder:{self.producer}:"):
            raise ValueError("product_id must embed the producer name.")
        return self


# ---------------------------------------------------------------------------
# Shared input pieces
# ---------------------------------------------------------------------------


class Quantity(DModel):
    """A unit-carrying scalar; ``bound`` marks floor- or ceiling-limited values."""

    value: float
    unit: Unit
    bound: Bound = "exact"


class QuantityRange(DModel):
    """A closed window in one unit (for example a fit or bias window)."""

    low: float
    high: float
    unit: Unit

    @model_validator(mode="after")
    def check_order(self) -> "QuantityRange":
        if not self.low < self.high:
            raise ValueError("low must be smaller than high.")
        return self


class SourceRef(DModel):
    """Where declared criteria or methods come from (U4: never repo-wide defaults)."""

    kind: Literal["device_profile", "recipe", "caller"]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    sha256: Sha256Hex | None = None


class StationRef(DModel):
    """Station identity by name plus hash only; private station files are never read."""

    name: Annotated[str, Field(min_length=1, max_length=100)]
    sha256: Sha256Hex


class ChannelRole(DModel):
    """Declared channel -> terminal role; roles are never inferred."""

    channel: Channel
    terminal: Terminal


class RawRef(DModel):
    """Capture-time reference to the raw instrument payload (owned by A/C, gap G1)."""

    sha256: Sha256Hex
    byte_count: Annotated[int, Field(ge=0)]


class ParserContractEcho(DModel):
    """What the A/C parser was told to decode; ``fmt_source`` says if FMT was verified."""

    module_type: Literal["SMU", "CMU", "WGFMU"]
    fmt: Literal[1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 21, 22, 25] | None = None
    fmt_output_mode: Annotated[int, Field(ge=0, le=10)] | None = None
    fmt_source: Literal["declared", "verified"] = "declared"
    measurement_mode: Annotated[int, Field(ge=1, le=30)] | None = None
    channels: Annotated[list[Channel], Field(max_length=20)] = Field(default_factory=list)
    timestamp: bool | None = None
    imp_model: ImpModel | None = None


class AcquisitionEvidence(DModel):
    """A caller-held A/C envelope passed in explicitly; D never fetches or re-decodes it.

    ``designated_record`` indexes ``envelope.atom_results`` when the envelope is a C flow,
    so D reads exactly one designated read record and never guesses which one.
    """

    envelope: dict[str, Any]
    designated_record: Annotated[int, Field(ge=0)] | None = None
    raw_ref: RawRef | None = None


class EvidenceSummary(DModel):
    """Compact, banned-key-free echo of one evidence envelope."""

    name: str | None
    family_class: str | None
    family_object: str | None
    fake: bool | None
    hardware_touched: bool | None
    ok: bool | None
    execution_state: str | None
    data_origin: DataOrigin
    element_count: int | None = None
    fingerprint: str


class ChannelCompliance(DModel):
    """Compliance limit that was programmed on one channel (A or V)."""

    channel: Channel
    limit: Quantity


class TrustPolicy(DModel):
    """Versioned U3 fit-exclusion policy; echoed, never silently changed."""

    version: str = U3_TRUST_POLICY_VERSION
    exclude_letter_codes: list[Literal["C", "T", "V", "X", "F", "U", "D", "G", "S"]] = Field(
        default_factory=lambda: ["C", "T", "V", "X", "F", "U", "D"]
    )
    exclude_numeric_bits: list[Literal[1, 2, 4, 8, 16, 32, 64]] = Field(
        default_factory=lambda: [1, 2, 4, 8, 64]
    )
    exclude_unknown_codes: bool = True
    exclude_search_codes_outside_search_modes: bool = True
    source_status_codes: list[Literal["W", "E"]] = Field(default_factory=lambda: ["W", "E"])
    near_compliance_ratio: Annotated[float, Field(gt=0, lt=1)] = 0.95


class AxisSpec(DModel):
    """Declared x/y column names; never inferred."""

    x: ColumnName
    y: ColumnName


class DerivativeMethod(DModel):
    """Declared derivative method; no smoothing beyond the declared window."""

    name: Literal["central_difference", "savitzky_golay"]
    window_points: Annotated[int, Field(ge=3, le=101)] | None = None
    polyorder: Annotated[int, Field(ge=1, le=5)] | None = None

    @model_validator(mode="after")
    def check_window(self) -> "DerivativeMethod":
        if self.name == "savitzky_golay":
            if self.window_points is None or self.polyorder is None:
                raise ValueError("savitzky_golay requires window_points and polyorder.")
            if self.window_points % 2 == 0 or self.polyorder >= self.window_points:
                raise ValueError("window_points must be odd and larger than polyorder.")
        elif self.window_points is not None or self.polyorder is not None:
            raise ValueError("central_difference takes no window_points or polyorder.")
        return self


class VthSpec(DModel):
    """Declared Vth method; the ``linear_extrapolation`` alias is rejected (gap G13)."""

    method: Literal["constant_current", "max_gm_linear_extrapolation"]
    icc: Quantity | None = None
    width_m: PositiveFloat | None = None
    length_m: PositiveFloat | None = None

    @model_validator(mode="after")
    def check_method(self) -> "VthSpec":
        if self.method == "constant_current" and self.icc is None:
            raise ValueError("constant_current requires icc.")
        if self.method != "constant_current" and self.icc is not None:
            raise ValueError("icc applies only to constant_current.")
        if (self.width_m is None) != (self.length_m is None):
            raise ValueError("width_m and length_m must be declared together.")
        return self


class VfbSpec(DModel):
    """Declared Vfb method with explicit physical assumptions (CMU stub)."""

    method: Literal["flatband_capacitance", "max_derivative"]
    substrate_type: Literal["n", "p"]
    doping_per_m3: PositiveFloat
    oxide_relative_permittivity: PositiveFloat
    semiconductor_relative_permittivity: PositiveFloat
    temperature_k: PositiveFloat


class SegmentRule(DModel):
    """How a dataset is split into lossless segments."""

    kind: Literal["direction", "var2", "repeat", "event"]
    expected_segments: Annotated[int, Field(ge=1, le=1024)] | None = None


class FamilyMember(DModel):
    """One member of a curve family: its dataset, trust summary and outer value."""

    dataset: ProductRef
    trust: ProductRef
    outer_value: Quantity


class Geometry(DModel):
    """Declared device geometry; exactly one of width or area."""

    width_m: PositiveFloat | None = None
    area_m2: PositiveFloat | None = None

    @model_validator(mode="after")
    def check_one(self) -> "Geometry":
        if (self.width_m is None) == (self.area_m2 is None):
            raise ValueError("Declare exactly one of width_m or area_m2.")
        return self


class ContinuityThresholds(DModel):
    """Declared report-only thresholds for spikes and steps."""

    spike_ratio: PositiveFloat | None = None
    step_ratio: PositiveFloat | None = None

    @model_validator(mode="after")
    def check_any(self) -> "ContinuityThresholds":
        if self.spike_ratio is None and self.step_ratio is None:
            raise ValueError("Declare at least one threshold.")
        return self


class CompensationRecord(DModel):
    """Declared CMU compensation record (correction is instrument-side, owned by B)."""

    kinds: Annotated[list[Literal["open", "short", "load", "phase"]], Field(min_length=1)]
    frequencies_hz: Annotated[list[PositiveFloat], Field(min_length=1, max_length=64)]
    recorded_at: datetime


class WgfmuEventSpec(DModel):
    """One planned WGFMU measure event (stub; real input blocked by gap G4)."""

    name: Annotated[str, Field(min_length=1, max_length=64)]
    time_s: Annotated[float, Field(ge=0)]
    points: Annotated[int, Field(ge=1, le=MAX_INLINE_POINTS)]
    interval_s: Annotated[float, Field(ge=1e-8)]
    average_s: Annotated[float, Field(ge=0)] = 0.0
    rdata: Literal["averaged", "raw"] = "averaged"


class Criterion(DModel):
    """One declared acceptance criterion; units must match the parameter exactly."""

    parameter: CriterionParameter
    comparator: Literal["le", "ge", "within"]
    limit: Quantity
    limit_high: Quantity | None = None

    @model_validator(mode="after")
    def check_shape(self) -> "Criterion":
        if self.comparator == "within":
            if self.limit_high is None:
                raise ValueError("within requires limit_high.")
            if self.limit_high.unit != self.limit.unit:
                raise ValueError("limit and limit_high must share a unit.")
            if not self.limit.value < self.limit_high.value:
                raise ValueError("limit must be smaller than limit_high.")
        elif self.limit_high is not None:
            raise ValueError("limit_high applies only to within.")
        return self


class EnvelopeLimit(DModel):
    """Declared post-hoc audit envelope for observed extrema (not a safety gate)."""

    quantity: Literal["voltage", "current"]
    terminal: Terminal | None = None
    low: Quantity | None = None
    high: Quantity | None = None

    @model_validator(mode="after")
    def check_any(self) -> "EnvelopeLimit":
        if self.low is None and self.high is None:
            raise ValueError("Declare low, high or both.")
        return self


class ReportedValue(DModel):
    """A value reported by another analysis (for example EasyEXPERT), marked as reported."""

    parameter: CriterionParameter
    quantity: Quantity
    reporter: Annotated[str, Field(min_length=1, max_length=100)]


class Tolerance(DModel):
    """Declared comparison tolerance for one parameter."""

    parameter: CriterionParameter
    absolute: Quantity | None = None
    relative: Annotated[float, Field(gt=0, lt=1)] | None = None

    @model_validator(mode="after")
    def check_any(self) -> "Tolerance":
        if self.absolute is None and self.relative is None:
            raise ValueError("Declare absolute, relative or both.")
        return self


# ---------------------------------------------------------------------------
# Response pieces
# ---------------------------------------------------------------------------


class Finding(DModel):
    """One structured finding; data findings never turn into ``ok: false``."""

    check: str
    severity: Severity
    code: str
    count: int | None = None
    indices: list[int] | None = None
    basis: list[str] = Field(default_factory=list)
    manual_note: str | None = None


class MethodRecord(DModel):
    """Declared method echo."""

    name: str
    version: str
    params: dict[str, Any] = Field(default_factory=dict)


class Provenance(DModel):
    """Lineage of one D result; ``computed_at`` is excluded from every hash."""

    upstream: list[str]
    input_fingerprints: list[str]
    output_fingerprint: str
    algorithm_version: str = PLACEHOLDER_ALGORITHM_VERSION
    status_table_version: str | None = None
    schema_version: str = SCHEMA_VERSION
    replayed: bool = False
    computed_at: str


class SideEffects(DModel):
    """D atoms never touch hardware; this phase never writes files."""

    hardware: Literal["none"] = "none"
    filesystem_writes: Annotated[list[str], Field(max_length=0)] = Field(default_factory=list)
    artifact_written: Literal[False] = False


class DError(DModel):
    """Tool error; present only when ``ok`` is false."""

    type: ErrorType
    message: str


class ProductOutputs(DModel):
    """Every stub returns its primary product as ``outputs.product``."""

    product: ProductRef | None


class ExpectationOutputs(ProductOutputs):
    """Expectation stub outputs: the C flow the expectation was built for."""

    c_flow: str | None = None


class DatasetOutputs(ProductOutputs):
    """Ingest stub outputs; mapping results stay empty until real computation (U1)."""

    unmapped_elements: list[str] = Field(default_factory=list)
    reported_parameters: list[str] = Field(default_factory=list)


class CheckOutputs(ProductOutputs):
    """Qualify-check stub outputs: ``check_outcome`` is always null for a stub (M2)."""

    check_outcome: CheckOutcome | None = None


class TrustOutputs(ProductOutputs):
    """Trust stub outputs: ``synthetic_only`` under synthetic origin, otherwise null (M2)."""

    trust_level: TrustLevel | None = None
    fit_mask: None = None


class ExtractOutputs(ProductOutputs):
    """Extract stub outputs: empty results plus the product reference (M2)."""

    results: list["ExtractionResult"] = Field(default_factory=list)
    trust_override: bool = False


class AssessOutputs(ProductOutputs):
    """Assess stub outputs: ``synthetic_only`` under synthetic origin, otherwise null (M2)."""

    verdict: VerdictLabel | None = None
    verdict_scope: VerdictScope | None = None
    escalate: bool | None = None


class BundlePlanOutputs(ProductOutputs):
    """write_bundle outputs: planned relative paths and refusal codes; nothing is written."""

    planned_paths: list[str] = Field(default_factory=list)
    artifact_written: Literal[False] = False
    write_refusal: list[WriteRefusal] = Field(default_factory=list)


class LoadOutputs(ProductOutputs):
    """load_bundle outputs: nothing is read in this phase."""

    artifacts: list[ProductRef] = Field(default_factory=list)
    hash_ok: bool | None = None
    artifact_read: Literal[False] = False


class DAtomEnvelope(DModel):
    """Standard D atom response envelope (D atom arbitration section 6)."""

    model_config = ConfigDict(populate_by_name=True)

    atom: str
    atom_class: Literal["D"] = Field(default="D", alias="class")
    stage: Stage
    subject: str
    fake: Literal[True] = True
    hardware_touched: Literal[False] = False
    basis: list[str] = Field(default_factory=list)
    warning: str
    ok: bool
    analysis_state: AnalysisState
    deterministic: Literal[True] = True
    parameters: dict[str, Any]
    outputs: dict[str, Any]
    findings: list[Finding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    method: MethodRecord | None = None
    data_origin: DataOrigin
    synthetic: bool
    provenance: Provenance
    required_inputs: list[str] = Field(default_factory=list)
    evidence_missing: list[str] = Field(default_factory=list)
    side_effects: SideEffects = Field(default_factory=SideEffects)
    error: DError | None = None

    @model_validator(mode="after")
    def check_consistency(self) -> "DAtomEnvelope":
        if self.ok == (self.error is not None):
            raise ValueError("error is present exactly when ok is false.")
        if self.synthetic != (self.data_origin == "synthetic"):
            raise ValueError("synthetic must equal (data_origin == 'synthetic').")
        banned = BANNED_RESULT_KEYS & set(self.parameters)
        if banned:
            raise ValueError(f"Banned keys in parameters: {sorted(banned)}")
        return self


# ---------------------------------------------------------------------------
# Inline product models. Reserved contract shapes: unreachable under U1, because every
# product is a placeholder ProductRef with content None. Kept typed for the promotion round.
# ---------------------------------------------------------------------------


class DataExpectation(DModel):
    """Data contract implied by a C request (reserved inline content)."""

    c_flow: str
    module_type: Literal["SMU", "CMU", "WGFMU"]
    columns: list[ColumnName]
    units: list[Unit]
    expected_points: Annotated[int, Field(ge=0, le=MAX_INLINE_POINTS)] | None = None
    status_encoding: Literal["letter", "numeric", "none"] | None = None
    timestamp_available: bool | None = None


class PointStatus(DModel):
    """Verbatim per-point status token and its class."""

    model_config = ConfigDict(populate_by_name=True)

    code: str | int | None
    encoding: Literal["letter", "numeric", "none"]
    status_class: str = Field(alias="class")


class AnalysisColumn(DModel):
    """One dataset column with unit, terminal role and column origin."""

    name: ColumnName
    unit: Unit
    terminal: Terminal | None = None
    origin: Literal["measured", "programmed", "derived", "reported"]


class AnalysisDataset(DModel):
    """Canonical dataset shape (reserved inline content; ``dataset_ref`` is reserved)."""

    columns: list[AnalysisColumn]
    point_count: Annotated[int, Field(ge=0, le=MAX_INLINE_POINTS)]
    data_origin: DataOrigin


class CheckReport(DModel):
    """Qualify check result (reserved inline content)."""

    check: str
    check_outcome: CheckOutcome
    findings: list[Finding] = Field(default_factory=list)


class TrustSummary(DModel):
    """Trust grade and fit mask (reserved inline content)."""

    trust_level: TrustLevel
    reasons: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    policy_version: str = U3_TRUST_POLICY_VERSION


class ExtractionResult(DModel):
    """Named parameter with method, window and bound (reserved inline content)."""

    parameter: CriterionParameter
    quantity: Quantity
    method: MethodRecord
    window: QuantityRange | None = None
    derived_from_flagged_points: Annotated[int, Field(ge=0)] = 0


class Verdict(DModel):
    """Verdict against declared criteria (reserved inline content)."""

    verdict: VerdictLabel
    verdict_scope: VerdictScope | None = None
    criteria: list[Criterion] = Field(default_factory=list)


class RunManifest(DModel):
    """Audit manifest (reserved inline content)."""

    intent: str
    tool_chain: list[str]
    station: StationRef | None = None
    raw_hashes: list[Sha256Hex] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


ExtractOutputs.model_rebuild()
