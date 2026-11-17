"""D-class fake MCP atom tools: post-acquisition analysis placeholders.

D owns what A/C data means; A/C own what the instrument said. Under user decision U1 every
D atom is a fake placeholder stub: it validates typed inputs, echoes them, propagates data
origin (weakest wins) and returns a content-free ``ProductRef`` placeholder. No number,
``pass`` verdict or trust grade above ``synthetic_only`` is ever produced, no file is
written (U2), and no A/B/C atom, flow or hardware transport is imported or called.

Naming: ``D_atom_<stage>_<subject>_<action>`` with closed vocabularies in
``schemas/d_atom.py``. Responses carry ``stage`` and ``subject`` so callers never parse names.
"""

import functools
import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, get_type_hints

from fastmcp import FastMCP
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from b1500_test_agent.schemas import c_flow as c_schema
from b1500_test_agent.schemas.d_atom import (
    DATA_ORIGIN_ORDER,
    IMP_MODEL_CODES,
    MAX_INLINE_POINTS,
    PARAMETER_UNITS,
    PLACEHOLDER_ALGORITHM_VERSION,
    PRODUCT_TYPES,
    AcquisitionEvidence,
    AcquisitionKind,
    AssessOutputs,
    AxisSpec,
    BundlePlanOutputs,
    ChannelCompliance,
    ChannelRole,
    CheckOutputs,
    ColumnName,
    CompensationRecord,
    ContinuityThresholds,
    Criterion,
    DataOrigin,
    DatasetOutputs,
    DAtomEnvelope,
    DerivativeMethod,
    DError,
    EnvelopeLimit,
    EvidenceSummary,
    ExpectationOutputs,
    ExtractOutputs,
    FamilyMember,
    Finding,
    Geometry,
    ImpModel,
    LoadOutputs,
    MethodRecord,
    ParserContractEcho,
    ProductOutputs,
    ProductRef,
    Provenance,
    Quantity,
    QuantityRange,
    ReportedValue,
    SegmentRule,
    SourceRef,
    StationRef,
    Terminal,
    Tolerance,
    TrustOutputs,
    TrustPolicy,
    VfbSpec,
    VthSpec,
    WgfmuEventSpec,
)
from b1500_test_agent.schemas.d_flow import MAX_ARCHIVE_ENVELOPES

from .common import _fake_response

_D_FAKE_WARNING = (
    "Fake D atom placeholder (U1): no analysis was computed; outputs are content-free "
    "placeholder references with no numbers, no pass verdict and no trust grade."
)
_SYNTHETIC_WARNING = (
    "Synthetic origin: products are labels only; no verdict or trust above synthetic_only "
    "can be produced from synthetic data."
)
_VOLATILE_KEYS = frozenset({"timestamp", "computed_at"})
_ERROR_PRECEDENCE = (
    "rejected_input",
    "unit_mismatch",
    "size_limit",
    "context_missing",
    "internal_error",
)
_READ_ATOMS = {
    "smu": frozenset({"C_atom_smu_read_measurement_data"}),
    "cmu": frozenset({"C_atom_cmu_read_measurement_data"}),
    "wgfmu": frozenset(
        {"C_atom_wgfmu_read_measurement_values", "C_atom_wgfmu_read_measurement_values_partial"}
    ),
}
# Typed C request model per acquisition kind (C_flow_<kind>); schema import only.
_KIND_MODELS: dict[str, type[BaseModel]] = {
    "spot_smu_iv": c_schema.SmuSpot,
    "sweep_smu_staircase": c_schema.SmuSweep,
    "sweep_smu_staircase_biased": c_schema.BiasedSweep,
    "pulse_smu_spot": c_schema.SmuPulse,
    "spot_cmu_impedance": c_schema.CmuSetup,
    "sweep_cmu_cv": c_schema.CmuSweep,
    "sweep_cmu_cf": c_schema.CmuPositiveSweep,
    "sweep_cmu_ac_level": c_schema.CmuPositiveSweep,
    "pulse_cmu_spot": c_schema.CmuPulse,
    "pulse_cmu_cv": c_schema.CmuPulseSweep,
    "waveform_wgfmu_acquire": c_schema.WgfmuWaveform,
}
_ARTIFACT_LAYOUT = {
    "table": ("processed", "csv"),
    "plot_spec": ("processed", "json"),
    "report": ("reports", "md"),
}

Envelopes = Annotated[list[dict[str, Any]], Field(max_length=16)]
Refs = Annotated[list[ProductRef], Field(max_length=64)]


@dataclass(frozen=True)
class _Spec:
    """Static catalog entry; stage and subject are declared, never parsed from names."""

    stage: str
    subject: str
    product_type: str
    priority: str
    module: str
    outputs: type[ProductOutputs] = ProductOutputs
    basis: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()


def _s(stage: str, subject: str, product: str, priority: str, module: str, **kw: Any) -> _Spec:
    defaults = {
        "ingest": DatasetOutputs,
        "qualify": CheckOutputs,
        "extract": ExtractOutputs,
        "assess": AssessOutputs,
    }
    kw.setdefault("outputs", defaults.get(stage, ProductOutputs))
    return _Spec(stage, subject, product, priority, module, **kw)


_SPECS: dict[str, _Spec] = {
    "D_atom_ingest_request_build_expectation": _s(
        "ingest", "request", "expectation", "P0", "SMU; CMU/WGFMU fields stub",
        outputs=ExpectationOutputs, basis=("PG Ed.15 Table 4-24 (FMT)",),
        required_inputs=("A_atom_flex_set_data_format",),
    ),
    "D_atom_ingest_smu_build_dataset": _s(
        "ingest", "smu", "dataset", "P0", "SMU",
        basis=("PG Ed.15 Tables 1-6 to 1-11",),
        required_inputs=(
            "C_atom_smu_read_measurement_data",
            "A_atom_flex_set_data_format",
            "A_flow_prepare_flex_output_buffer",
        ),
    ),
    "D_atom_ingest_easyexpert_build_dataset": _s(
        "ingest", "easyexpert", "dataset", "P1", "EasyEXPERT (after gap G5)",
        required_inputs=("A_atom_easyexpert_fetch_result", "A_flow_collect_easyexpert_result"),
    ),
    "D_atom_ingest_cmu_build_dataset": _s(
        "ingest", "cmu", "dataset", "P2", "CMU stub",
        basis=("PG Ed.15 Table 4-16 (IMP)",),
        required_inputs=(
            "C_atom_cmu_read_measurement_data",
            "C_atom_cmu_set_impedance_model",
            "A_atom_flex_set_data_format",
        ),
    ),
    "D_atom_ingest_wgfmu_build_series": _s(
        "ingest", "wgfmu", "dataset", "P2", "WGFMU stub",
        required_inputs=(
            "C_atom_wgfmu_read_measurement_values",
            "A_atom_wgfmu_get_channel_status",
        ),
    ),
    "D_atom_qualify_dataset_classify_status": _s(
        "qualify", "dataset", "check_report", "P0", "SMU; CMU classes stub",
        basis=("PG Ed.15 Tables 1-7 to 1-10",),
        required_inputs=("A_atom_flex_set_data_format",),
    ),
    "D_atom_qualify_dataset_check_completeness": _s(
        "qualify", "dataset", "check_report", "P0", "gen",
        required_inputs=("A_atom_flex_query_buffer_count", "A_flow_drain_flex_errors"),
    ),
    "D_atom_qualify_iv_check_compliance": _s(
        "qualify", "iv", "check_report", "P0", "SMU",
        basis=("PG Ed.15 Table 1-10 (C/T)", "LIM?", "LOP?"),
        required_inputs=("A_atom_flex_query_compliance_status",),
    ),
    "D_atom_qualify_iv_check_resolution": _s(
        "qualify", "iv", "check_report", "P0", "SMU",
        basis=("PG Ed.15 Table 4-3",),
        required_inputs=("C_atom_smu_set_measurement_ranging", "A_atom_flex_list_modules"),
    ),
    "D_atom_qualify_run_check_context": _s(
        "qualify", "run", "check_report", "P0", "gen (WGFMU inputs stub)",
        required_inputs=(
            "A_flow_drain_flex_errors",
            "A_flow_snapshot_flex_status",
            "B_flow_preflight_b1500_gate",
        ),
    ),
    "D_atom_qualify_dataset_grade_trust": _s(
        "qualify", "dataset", "trust_summary", "P0", "gen", outputs=TrustOutputs,
    ),
    "D_atom_qualify_iv_check_source_tracking": _s(
        "qualify", "iv", "check_report", "P1", "SMU",
        required_inputs=("A_atom_flex_set_data_format",),
    ),
    "D_atom_qualify_dataset_check_continuity": _s(
        "qualify", "dataset", "check_report", "P2", "gen",
    ),
    "D_atom_qualify_cv_check_correction": _s(
        "qualify", "cv", "check_report", "P2", "CMU stub",
        basis=("CORRST?", "CORRL?"),
        required_inputs=(
            "A_atom_flex_query_cmu_correction_status",
            "A_atom_flex_query_cmu_correction_freq_list",
            "B_flow_correction_cmu_open_short_load",
        ),
    ),
    "D_atom_qualify_timeseries_check_events": _s(
        "qualify", "timeseries", "check_report", "P2", "WGFMU stub",
        required_inputs=("A_atom_wgfmu_get_channel_status", "A_flow_drain_wgfmu_errors"),
    ),
    "D_atom_shape_dataset_split_segments": _s("shape", "dataset", "view", "P1", "gen"),
    "D_atom_shape_dataset_stack_family": _s("shape", "dataset", "view", "P1", "gen"),
    "D_atom_shape_dataset_normalize_geometry": _s("shape", "dataset", "view", "P2", "gen"),
    "D_atom_derive_curve_compute_derivative": _s("derive", "curve", "derived", "P1", "gen"),
    "D_atom_derive_curve_interpolate": _s("derive", "curve", "derived", "P1", "gen"),
    "D_atom_derive_curve_fit_linear": _s("derive", "curve", "derived", "P1", "gen"),
    "D_atom_derive_dataset_summarize_columns": _s("derive", "dataset", "derived", "P1", "gen"),
    "D_atom_derive_timeseries_summarize_windows": _s(
        "derive", "timeseries", "derived", "P2", "SMU sampling; WGFMU stub",
    ),
    "D_atom_extract_leakage_current": _s(
        "extract", "leakage", "extraction_result", "P0", "SMU",
    ),
    "D_atom_extract_transfer_vth": _s("extract", "transfer", "extraction_result", "P1", "SMU"),
    "D_atom_extract_transfer_gm_max": _s(
        "extract", "transfer", "extraction_result", "P1", "SMU",
    ),
    "D_atom_extract_transfer_ss": _s("extract", "transfer", "extraction_result", "P1", "SMU"),
    "D_atom_extract_transfer_on_off": _s(
        "extract", "transfer", "extraction_result", "P1", "SMU",
    ),
    "D_atom_extract_transfer_voltage_shift": _s(
        "extract", "transfer", "extraction_result", "P1", "SMU",
    ),
    "D_atom_extract_output_ron": _s("extract", "output", "extraction_result", "P2", "SMU"),
    "D_atom_extract_leakage_breakdown_voltage": _s(
        "extract", "leakage", "extraction_result", "P2", "SMU",
    ),
    "D_atom_extract_cv_cox": _s("extract", "cv", "extraction_result", "P2", "CMU stub"),
    "D_atom_extract_cv_vfb": _s("extract", "cv", "extraction_result", "P2", "CMU stub"),
    "D_atom_assess_value_check_limits": _s("assess", "value", "verdict", "P0", "gen"),
    "D_atom_assess_dataset_check_envelope": _s("assess", "dataset", "verdict", "P1", "gen"),
    "D_atom_assess_dataset_compare_reference": _s("assess", "dataset", "verdict", "P2", "gen"),
    "D_atom_archive_run_build_manifest": _s(
        "archive", "run", "manifest", "P0", "gen",
        required_inputs=("A_atom_flex_list_modules",),
    ),
    "D_atom_archive_run_write_bundle": _s(
        "archive", "run", "bundle_plan", "P0", "gen", outputs=BundlePlanOutputs,
    ),
    "D_atom_archive_run_load_bundle": _s(
        "archive", "run", "manifest", "P1", "gen", outputs=LoadOutputs,
    ),
    "D_atom_render_dataset_build_plot_spec": _s("render", "dataset", "plot_spec", "P1", "gen"),
    "D_atom_render_dataset_build_table": _s("render", "dataset", "table", "P1", "gen"),
    "D_atom_render_run_build_report": _s("render", "run", "report", "P2", "gen"),
}  # fmt: skip


# ---------------------------------------------------------------------------
# Pure helpers (hashing, origin, evidence summaries)
# ---------------------------------------------------------------------------


def _strip_volatile(value: Any) -> Any:
    """Drop wall-clock fields so fingerprints and product ids stay deterministic."""
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_strip_volatile(v) for v in value]
    return value


def _sha256(value: Any) -> str:
    canonical = json.dumps(
        _strip_volatile(value), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _weakest(origins: list[str]) -> str:
    return min(origins, key=DATA_ORIGIN_ORDER.index)


def _envelope_origin(envelope: dict[str, Any]) -> str:
    """Derive origin from evidence markers; unmarked evidence counts as synthetic."""
    outputs = envelope.get("outputs")
    if (
        envelope.get("fake") is True
        or envelope.get("synthetic") is True
        or envelope.get("data_origin") == "synthetic"
        or (isinstance(outputs, dict) and outputs.get("synthetic") is True)
    ):
        return "synthetic"
    if envelope.get("data_origin") == "fixture":
        return "fixture"
    if envelope.get("fake") is False and envelope.get("data_origin") in (None, "instrument"):
        return "instrument"
    return "synthetic"


def _family_object(name: str | None) -> str | None:
    """Object/interface/target token of an A/B/C/D tool name (for wiring checks only)."""
    if not name:
        return None
    parts = name.split("_")
    if len(parts) < 3 or parts[0] not in {"A", "B", "C", "D", "AB", "CD"}:
        return None
    if parts[1] == "atom" and parts[0] in {"A", "C"}:
        return parts[2]
    return parts[3] if len(parts) > 3 else None


def _element_count(result: Any) -> int | None:
    """Count decoded elements in one A/C read result without reading their content."""
    if not isinstance(result, dict):
        return None
    parameters = result.get("parameters")
    payload = {**result, **parameters} if isinstance(parameters, dict) else result
    for key in ("rows", "values", "items"):
        if isinstance(payload.get(key), list):
            return len(payload[key])
    if any(isinstance(payload.get(key), dict) for key in ("sample", "measurement")):
        return 1
    return None


def _summarize(envelope: dict[str, Any], designated: int | None = None) -> EvidenceSummary:
    """Banned-key-free summary of one caller-held envelope."""
    raw_name = envelope.get("flow") or envelope.get("atom")
    name = raw_name if isinstance(raw_name, str) else None
    count = None
    records = envelope.get("atom_results")
    if designated is not None and isinstance(records, list) and designated < len(records):
        record = records[designated]
        count = _element_count(record.get("result")) if isinstance(record, dict) else None
    elif designated is None:
        count = _element_count(envelope)

    def flag(key: str) -> bool | None:
        value = envelope.get(key)
        return value if isinstance(value, bool) else None

    state = envelope.get("execution_state")
    return EvidenceSummary(
        name=name,
        family_class=name.split("_", 1)[0] if name else None,
        family_object=_family_object(name),
        fake=flag("fake"),
        hardware_touched=flag("hardware_touched"),
        ok=flag("ok"),
        execution_state=state if isinstance(state, str) else None,
        data_origin=_envelope_origin(envelope),
        element_count=count,
        fingerprint="sha256:" + _sha256(envelope),
    )


def _jsonable(value: Any) -> Any:
    """Echo inputs as scalars, product ids and evidence summaries, never datasets."""
    if isinstance(value, ProductRef):
        return value.product_id
    if isinstance(value, AcquisitionEvidence):
        return {
            "summary": _summarize(value.envelope, value.designated_record).model_dump(),
            "designated_record": value.designated_record,
            "raw_ref": None if value.raw_ref is None else value.raw_ref.model_dump(),
        }
    if isinstance(value, BaseModel):
        return {name: _jsonable(getattr(value, name)) for name in type(value).model_fields}
    if isinstance(value, dict):
        return _summarize(value).model_dump()
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Stub call context and response envelope
# ---------------------------------------------------------------------------


class _Call:
    """Collects one stub invocation: echo, product wiring, origin and errors."""

    def __init__(self, atom: str, inputs: dict[str, Any]) -> None:
        self.atom = atom
        self.spec = _SPECS[atom]
        self.params: dict[str, Any] = {k: _jsonable(v) for k, v in inputs.items()}
        self.refs: list[ProductRef] = []
        self.evidence: list[EvidenceSummary] = []
        self.errors: list[tuple[str, str]] = []
        self.findings: list[Finding] = []
        self.warnings: list[str] = []
        self.assumptions: list[str] = []
        self.evidence_missing: list[str] = []
        self.required_inputs: list[str] = list(self.spec.required_inputs)
        self.method: MethodRecord | None = None
        self.declared_origin: str | None = None

    # -- error bookkeeping -------------------------------------------------
    def fail(self, error_type: str, message: str) -> None:
        self.errors.append((error_type, message))

    def reject(self, message: str) -> None:
        self.fail("rejected_input", message)

    def need(self, name: str, value: Any, hint: str = "") -> bool:
        """Required context (criteria, methods, roles): absent means context_missing."""
        if value is None or (isinstance(value, (list, str)) and not value):
            suffix = f" ({hint})" if hint else ""
            self.fail("context_missing", f"{name} is required and has no default{suffix}.")
            return False
        return True

    def unit(self, name: str, value: Quantity | QuantityRange | None, allowed: set[str]) -> None:
        if value is not None and value.unit not in allowed:
            self.fail(
                "unit_mismatch", f"{name} has unit {value.unit!r}; expected {sorted(allowed)}."
            )

    def optional_evidence(self, name: str, value: Any, note: str) -> None:
        if value is None or value == []:
            self.evidence_missing.append(f"{name}: {note}")

    # -- product wiring (R1-R4) -------------------------------------------
    def product(
        self,
        name: str,
        ref: ProductRef | None,
        accepted: set[str],
        *,
        required: bool = True,
        producers: set[str] | None = None,
    ) -> None:
        if ref is None:
            if required:
                self.fail("context_missing", f"Required product {name!r} is missing (R2).")
            return
        if ref.product_type not in accepted:
            self.reject(
                f"{name}: product_type {ref.product_type!r} is not one of {sorted(accepted)} (R3)."
            )
        elif producers and ref.producer not in producers:
            self.reject(f"{name}: producer {ref.producer!r} is not one of {sorted(producers)}.")
        self.refs.append(ref)

    def products(
        self,
        name: str,
        refs: list[ProductRef] | None,
        accepted: set[str],
        *,
        required: bool = True,
        min_items: int = 1,
        max_items: int | None = None,
    ) -> None:
        if not refs:
            if required:
                self.fail("context_missing", f"Required product list {name!r} is missing (R2).")
            return
        if len(refs) < min_items or (max_items is not None and len(refs) > max_items):
            limit = f"{min_items}..{max_items}" if max_items else f">= {min_items}"
            self.reject(f"{name} needs {limit} products; got {len(refs)}.")
        for index, ref in enumerate(refs):
            self.product(f"{name}[{index}]", ref, accepted)

    # -- evidence -----------------------------------------------------------
    def envelope(
        self,
        name: str,
        evidence: AcquisitionEvidence | None,
        *,
        family: str | None = None,
        required: bool = True,
        read_record: bool = True,
    ) -> None:
        """Register one A/C envelope; a data read from a C flow needs its designated record."""
        if evidence is None:
            if required:
                self.fail("context_missing", f"{name} (A/C envelope) is required.")
            else:
                self.evidence_missing.append(f"{name}: no A/C envelope supplied")
            return
        env = evidence.envelope
        summary = _summarize(env, evidence.designated_record)
        self.evidence.append(summary)
        if summary.name is None:
            self.findings.append(
                Finding(check="evidence", severity="warning", code="evidence_unidentified")
            )
        if family and summary.family_object not in (None, family):
            self.reject(f"{name}: envelope {summary.name!r} is not {family} evidence.")
        if not read_record:
            return
        if isinstance(env.get("flow"), str):
            self._designated(name, evidence, family)
        if summary.element_count is not None and summary.element_count > MAX_INLINE_POINTS:
            self.fail(
                "size_limit",
                f"{name}: {summary.element_count} elements exceed the inline cap "
                f"{MAX_INLINE_POINTS}; dataset_ref is reserved, not implemented.",
            )
        if evidence.raw_ref is None:
            self.evidence_missing.append(f"{name}.raw_ref: raw payload hash not captured (G1)")

    def _designated(self, name: str, evidence: AcquisitionEvidence, family: str | None) -> None:
        index = evidence.designated_record
        records = evidence.envelope.get("atom_results")
        if index is None:
            self.fail(
                "context_missing",
                f"{name}.designated_record is required for a C flow envelope; D never guesses.",
            )
            return
        if not isinstance(records, list) or index >= len(records):
            self.reject(f"{name}.designated_record {index} does not exist.")
            return
        record = records[index] if isinstance(records[index], dict) else {}
        read_atoms = _READ_ATOMS.get(family or "", frozenset())
        if read_atoms and record.get("atom") not in read_atoms:
            self.reject(f"{name}.designated_record is not a {family} read record.")
        elif record.get("status") != "ok":
            self.reject(f"{name}.designated_record was not read (handoff not received).")

    def envelopes(self, name: str, envelopes: list[dict[str, Any]] | None) -> None:
        for envelope in envelopes or []:
            self.evidence.append(_summarize(envelope))

    # -- origin and labels -------------------------------------------------
    def origin(self) -> str:
        """Weakest-wins origin; a declared origin may lower it, never raise it (R4)."""
        sources = [ref.data_origin for ref in self.refs] + [e.data_origin for e in self.evidence]
        derived = _weakest(sources) if sources else "synthetic"
        if self.declared_origin and DATA_ORIGIN_ORDER.index(
            self.declared_origin
        ) < DATA_ORIGIN_ORDER.index(derived):
            return self.declared_origin
        return derived

    def label(self) -> str | None:
        """M2 stub label: synthetic_only under synthetic origin, otherwise null."""
        return "synthetic_only" if not self.errors and self.origin() == "synthetic" else None

    def digest(self) -> str:
        return _sha256({"atom": self.atom, "inputs": self.params})[:16]

    # -- envelope ----------------------------------------------------------
    def finish(self, **outputs: Any) -> dict:
        spec = self.spec
        origin = self.origin()
        synthetic = origin == "synthetic"
        warnings = list(self.warnings)
        assumptions = list(self.assumptions)
        if not (self.refs or self.evidence):
            assumptions.append(
                "No origin-bearing input; data_origin defaults to the weakest value (synthetic)."
            )
        if self.declared_origin and self.declared_origin != origin:
            warnings.append(
                f"declared_origin {self.declared_origin!r} cannot raise origin {origin!r}."
            )
        if synthetic:
            warnings.append(_SYNTHETIC_WARNING)
        error = None
        if self.errors:
            kinds = [kind for kind, _ in self.errors]
            first = next(kind for kind in _ERROR_PRECEDENCE if kind in kinds)
            error = DError(type=first, message=" ".join(msg for _, msg in self.errors)[:2000])
            body = spec.outputs(product=None).model_dump(mode="json")
        else:
            product = ProductRef(
                product_type=spec.product_type,
                product_id=f"placeholder:{self.atom}:{self.digest()}",
                producer=self.atom,
                data_origin=origin,
                synthetic=synthetic,
                upstream=[ref.product_id for ref in self.refs],
            )
            body = spec.outputs(product=product, **outputs).model_dump(mode="json")
        input_fingerprints = ["sha256:" + _sha256(self.params)] + [
            e.fingerprint for e in self.evidence
        ]
        envelope = DAtomEnvelope(
            atom=self.atom,
            stage=spec.stage,
            subject=spec.subject,
            basis=list(spec.basis),
            warning=_D_FAKE_WARNING,
            ok=error is None,
            analysis_state="not_computed" if error is None else "rejected_input",
            parameters=self.params,
            outputs=body,
            findings=self.findings,
            warnings=warnings,
            assumptions=assumptions,
            method=self.method,
            data_origin=origin,
            synthetic=synthetic,
            provenance=Provenance(
                upstream=[ref.product_id for ref in self.refs],
                input_fingerprints=input_fingerprints,
                output_fingerprint="sha256:" + _sha256(body),
                computed_at=datetime.now(timezone.utc).isoformat(),
            ),
            required_inputs=self.required_inputs,
            evidence_missing=self.evidence_missing,
            error=error,
        )
        payload = envelope.model_dump(mode="json", by_alias=True)
        if payload["error"] is None:
            del payload["error"]
        return _fake_response(payload.pop("atom"), payload.pop("basis"), **payload)


def _d_atom(func: Callable[..., dict]) -> Callable[..., dict]:
    """Validate direct-Python inputs like the MCP boundary does.

    FastMCP already validates arguments; direct callers (future D flows, tests) may pass
    dicts. A validation failure becomes an ``ok: false`` ``rejected_input`` envelope.
    """
    signature = inspect.signature(func)
    hints = get_type_hints(func, include_extras=True)
    adapters = {name: TypeAdapter(hints[name]) for name in signature.parameters}

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            bound = signature.bind(*args, **kwargs)
            coerced = {
                name: adapters[name].validate_python(value)
                for name, value in bound.arguments.items()
            }
        except (TypeError, ValidationError) as exc:
            call = _Call(func.__name__, {})
            call.reject(f"Input validation failed: {exc}"[:1500])
            return call.finish()
        return func(**coerced)

    return wrapper


def _method(call: _Call, name: str, params: BaseModel | dict[str, Any] | None) -> None:
    dumped = params.model_dump(mode="json") if isinstance(params, BaseModel) else params or {}
    call.method = MethodRecord(name=name, version=PLACEHOLDER_ALGORITHM_VERSION, params=dumped)


def _roles(call: _Call, roles: list[ChannelRole] | None) -> None:
    if call.need("channel_roles", roles, "declared channel -> terminal map; never inferred"):
        channels = [role.channel for role in roles or []]
        if len(set(channels)) != len(channels):
            call.reject("channel_roles must name each channel once.")


def _contract(call: _Call, echo: ParserContractEcho | None, module: str) -> None:
    if echo is None:
        call.evidence_missing.append("contract_echo: parser contract not echoed by A/C (G1)")
        return
    if echo.module_type != module:
        call.reject(f"contract_echo.module_type {echo.module_type!r} is not {module!r}.")
    if echo.fmt_source == "declared":
        call.findings.append(
            Finding(
                check="contract",
                severity="warning",
                code="format_declared_not_verified",
                basis=["PG Ed.15 Table 4-24"],
            )
        )


def _origin_finding(call: _Call) -> None:
    if not call.errors and call.origin() == "synthetic":
        call.findings.append(
            Finding(
                check="data_origin",
                severity="warning",
                code="synthetic_origin",
                basis=["D atom arbitration #6", "amendment M2"],
            )
        )


def _extract(
    call: _Call,
    dataset: ProductRef | None,
    trust: ProductRef | None,
    allow_untrusted: bool,
) -> None:
    call.product("dataset", dataset, {"dataset", "view"})
    call.product("trust", trust, {"trust_summary"})
    if allow_untrusted:
        call.warnings.append(
            "allow_untrusted set: trust_override is recorded, assess must return inconclusive, "
            "and synthetic_only is never lifted."
        )


# ---------------------------------------------------------------------------
# D class - ingest: A/C evidence -> canonical placeholders (chain heads)
# ---------------------------------------------------------------------------


@_d_atom
def D_atom_ingest_request_build_expectation(
    acquisition_kind: AcquisitionKind | None = None,
    c_request: dict[str, Any] | None = None,
    contract_echo: ParserContractEcho | None = None,
    evidence: AcquisitionEvidence | None = None,
    declared_origin: DataOrigin | None = None,
) -> dict:
    """Build the data contract (expectation) implied by a typed C request.

    Pure and usable before or after C runs. ``c_request`` is validated against the typed
    C flow schema of ``C_flow_<acquisition_kind>``. Returns an ``expectation`` placeholder.
    """
    call = _Call("D_atom_ingest_request_build_expectation", locals())
    call.declared_origin = declared_origin
    c_flow = None
    if call.need("acquisition_kind", acquisition_kind) and call.need("c_request", c_request):
        c_flow = f"C_flow_{acquisition_kind}"
        call.required_inputs.insert(0, c_flow)
        try:
            request = _KIND_MODELS[acquisition_kind].model_validate(c_request)
            call.params["c_request"] = request.model_dump(mode="json")
        except ValidationError as exc:
            call.reject(f"c_request does not match the {c_flow} request schema: {exc}"[:1500])
        module = acquisition_kind.split("_")[1].upper()
        _contract(call, contract_echo, module)
    call.envelope("evidence", evidence, required=False, read_record=False)
    evidence_name = _summarize(evidence.envelope).name if evidence else None
    if c_flow and evidence_name not in (None, c_flow):
        call.reject(f"evidence envelope {evidence_name!r} is not {c_flow}.")
    return call.finish(c_flow=c_flow)


@_d_atom
def D_atom_ingest_smu_build_dataset(
    evidence: AcquisitionEvidence | None = None,
    expectation: ProductRef | None = None,
    channel_roles: Annotated[list[ChannelRole], Field(max_length=20)] | None = None,
    contract_echo: ParserContractEcho | None = None,
    declared_origin: DataOrigin | None = None,
) -> dict:
    """Turn the designated C SMU read record into a dataset placeholder.

    Fixes SI units, channel -> terminal roles and data origin; keeps point status verbatim.
    Needs the C flow envelope with its designated read record, the expectation and the
    declared channel roles.
    """
    call = _Call("D_atom_ingest_smu_build_dataset", locals())
    call.declared_origin = declared_origin
    call.envelope("evidence", evidence, family="smu")
    call.product("expectation", expectation, {"expectation"})
    _roles(call, channel_roles)
    _contract(call, contract_echo, "SMU")
    if contract_echo and channel_roles:
        unmapped = set(contract_echo.channels) - {role.channel for role in channel_roles}
        if unmapped:
            call.findings.append(
                Finding(
                    check="pin_map",
                    severity="warning",
                    code="pin_map_incomplete",
                    count=len(unmapped),
                )
            )
    _origin_finding(call)
    return call.finish()


@_d_atom
def D_atom_ingest_easyexpert_build_dataset(
    evidence: AcquisitionEvidence | None = None,
    channel_roles: Annotated[list[ChannelRole], Field(max_length=20)] | None = None,
    declared_origin: DataOrigin | None = None,
) -> dict:
    """Turn A-parsed EasyEXPERT vectors into a dataset placeholder (blocked by gap G5).

    EasyEXPERT analysis values would be marked ``origin: reported``.
    """
    call = _Call("D_atom_ingest_easyexpert_build_dataset", locals())
    call.declared_origin = declared_origin
    call.envelope("evidence", evidence, family="easyexpert")
    call.optional_evidence("channel_roles", channel_roles, "device ID -> target map not declared")
    call.warnings.append("A_atom_easyexpert_fetch_result returns no parsed vectors yet (G5).")
    _origin_finding(call)
    return call.finish()


@_d_atom
def D_atom_ingest_cmu_build_dataset(
    evidence: AcquisitionEvidence | None = None,
    expectation: ProductRef | None = None,
    imp_model: ImpModel | None = None,
    sweep_kind: Literal["spot", "voltage", "frequency", "ac_level", "time"] | None = None,
    channel_roles: Annotated[list[ChannelRole], Field(max_length=20)] | None = None,
    contract_echo: ParserContractEcho | None = None,
    declared_origin: DataOrigin | None = None,
) -> dict:
    """Turn a C CMU read record into an IMP-model dataset placeholder (CMU stub).

    Primary/secondary columns follow PG Table 4-16 (rad vs deg); real C-V use waits for
    correction, SCUU and leakage validation.
    """
    call = _Call("D_atom_ingest_cmu_build_dataset", locals())
    call.declared_origin = declared_origin
    call.envelope("evidence", evidence, family="cmu")
    call.product("expectation", expectation, {"expectation"})
    call.need("imp_model", imp_model, "PG Table 4-16; never guessed")
    call.need("sweep_kind", sweep_kind)
    _roles(call, channel_roles)
    _contract(call, contract_echo, "CMU")
    if contract_echo and contract_echo.imp_model and imp_model != contract_echo.imp_model:
        call.reject("imp_model does not match contract_echo.imp_model.")
    if imp_model:
        call.params["imp_code"] = IMP_MODEL_CODES[imp_model]
    call.warnings.append("CMU analysis is stub-only (AGENTS.md: correction/SCUU/leakage first).")
    _origin_finding(call)
    return call.finish()


@_d_atom
def D_atom_ingest_wgfmu_build_series(
    evidence: AcquisitionEvidence | None = None,
    expectation: ProductRef | None = None,
    measure_mode: Literal["voltage", "current"] | None = None,
    event_plan: Annotated[list[WgfmuEventSpec], Field(max_length=256)] | None = None,
    channel_roles: Annotated[list[ChannelRole], Field(max_length=20)] | None = None,
    declared_origin: DataOrigin | None = None,
) -> dict:
    """Turn WGFMU per-channel arrays into a timeseries dataset placeholder (WGFMU stub).

    Real input is blocked by gap G4 (reads carry no time axis or event structure).
    """
    call = _Call("D_atom_ingest_wgfmu_build_series", locals())
    call.declared_origin = declared_origin
    call.envelope("evidence", evidence, family="wgfmu")
    call.product("expectation", expectation, {"expectation"})
    call.need("measure_mode", measure_mode)
    _roles(call, channel_roles)
    call.optional_evidence("event_plan", event_plan, "event segmentation not declared")
    call.warnings.append("WGFMU reads lack time arrays and event structure (G4).")
    _origin_finding(call)
    return call.finish()


# ---------------------------------------------------------------------------
# D class - qualify: data trust (never alters values, never a safety gate)
# ---------------------------------------------------------------------------


@_d_atom
def D_atom_qualify_dataset_classify_status(
    dataset: ProductRef | None = None,
    contract_echo: ParserContractEcho | None = None,
    status_table_version: str | None = None,
) -> dict:
    """Classify per-point status (letter, EEE, W/E, channel Z, 199.999E+99) by module and MM.

    Classification needs module type and MM from the contract echo; the verified versioned
    status table is not built yet (gaps G10/G11).
    """
    call = _Call("D_atom_qualify_dataset_classify_status", locals())
    call.product("dataset", dataset, {"dataset"})
    if contract_echo is None:
        call.evidence_missing.append("contract_echo: module type and MM not echoed (G1)")
    call.optional_evidence(
        "status_table_version", status_table_version, "verified status table not built (G11)"
    )
    return call.finish()


@_d_atom
def D_atom_qualify_dataset_check_completeness(
    dataset: ProductRef | None = None,
    expectation: ProductRef | None = None,
    buffer_evidence: Envelopes | None = None,
) -> dict:
    """Check expected vs received points, truncation, sentinel runs and index monotonicity."""
    call = _Call("D_atom_qualify_dataset_check_completeness", locals())
    call.product("dataset", dataset, {"dataset"})
    call.product("expectation", expectation, {"expectation"})
    call.envelopes("buffer_evidence", buffer_evidence)
    call.optional_evidence("buffer_evidence", buffer_evidence, "buffer count/error queue absent")
    return call.finish()


@_d_atom
def D_atom_qualify_iv_check_compliance(
    dataset: ProductRef | None = None,
    compliance: Annotated[list[ChannelCompliance], Field(max_length=20)] | None = None,
    near_ratio: Annotated[float, Field(gt=0, lt=1)] = 0.95,
    readback_evidence: Envelopes | None = None,
) -> dict:
    """Check C/T compliance hits, onset and near-compliance by value ratio (U3: 0.95)."""
    call = _Call("D_atom_qualify_iv_check_compliance", locals())
    call.product("dataset", dataset, {"dataset"})
    for index, item in enumerate(compliance or []):
        call.unit(f"compliance[{index}].limit", item.limit, {"A", "V"})
    call.envelopes("readback_evidence", readback_evidence)
    call.optional_evidence("compliance", compliance, "programmed compliance limits absent")
    call.optional_evidence("readback_evidence", readback_evidence, "LIM?/LOP? not captured")
    return call.finish()


@_d_atom
def D_atom_qualify_iv_check_resolution(
    dataset: ProductRef | None = None,
    module_type: Literal["MPSMU", "HRSMU"] | None = None,
    range_mode: Literal["auto", "fixed", "limited_auto"] | None = None,
    range_value: Annotated[float, Field(ge=0)] | None = None,
    asu: bool | None = None,
) -> dict:
    """Check range-floor proximity; floor-limited points would become bounds (Table 4-3)."""
    call = _Call("D_atom_qualify_iv_check_resolution", locals())
    call.product("dataset", dataset, {"dataset"})
    call.optional_evidence("module_type", module_type, "module model not declared")
    call.optional_evidence("range_mode", range_mode, "ranging not declared; range_unknown")
    return call.finish()


@_d_atom
def D_atom_qualify_run_check_context(
    c_evidence: AcquisitionEvidence | None = None,
    upstream_evidence: Envelopes | None = None,
    dataset: ProductRef | None = None,
    declared_origin: DataOrigin | None = None,
) -> dict:
    """Turn upstream run evidence into findings (execution state, errors, FMT, taint).

    Caller-passed A/B envelopes are recorded as ``evidence_unverified`` and never lift a
    trust cap until evidence binding exists (amendment M6).
    """
    call = _Call("D_atom_qualify_run_check_context", locals())
    call.declared_origin = declared_origin
    call.product("dataset", dataset, {"dataset"}, required=False)
    if c_evidence is not None:
        summary = _summarize(c_evidence.envelope, c_evidence.designated_record)
        call.evidence.append(summary)
    else:
        call.evidence_missing.append("c_evidence: C flow envelope not supplied")
    call.envelopes("upstream_evidence", upstream_evidence)
    if upstream_evidence:
        call.findings.append(
            Finding(
                check="context",
                severity="warning",
                code="evidence_unverified",
                count=len(upstream_evidence),
                basis=["amendment M6"],
                manual_note="Caller-passed envelopes cannot lift trust caps (no evidence binding).",
            )
        )
    else:
        call.evidence_missing.append("upstream_evidence: no A/B error, status or gate evidence")
    if any(e.data_origin == "synthetic" for e in call.evidence):
        call.findings.append(
            Finding(check="context", severity="warning", code="upstream_synthetic")
        )
    return call.finish()


@_d_atom
def D_atom_qualify_dataset_grade_trust(
    dataset: ProductRef | None = None,
    reports: Annotated[list[ProductRef], Field(max_length=16)] | None = None,
    policy: TrustPolicy | None = None,
) -> dict:
    """Reduce check reports under the versioned U3 TrustPolicy to a trust summary.

    Stub label (M2): ``trust_level`` is ``synthetic_only`` under synthetic origin and null
    otherwise; ``fit_mask`` stays null. Never ``trusted`` or ``trusted_with_flags``.
    """
    call = _Call("D_atom_qualify_dataset_grade_trust", locals())
    call.product("dataset", dataset, {"dataset"})
    call.products("reports", reports, {"check_report"})
    applied = policy or TrustPolicy()
    call.params["policy"] = applied.model_dump(mode="json")
    if policy is None:
        call.assumptions.append(f"Default U3 trust policy {applied.version} applied (echoed).")
    return call.finish(trust_level=call.label())


@_d_atom
def D_atom_qualify_iv_check_source_tracking(
    dataset: ProductRef | None = None,
    tolerance: Quantity | None = None,
) -> dict:
    """Compare measured source data (FMT mode != 0) with programmed setpoints."""
    call = _Call("D_atom_qualify_iv_check_source_tracking", locals())
    call.product("dataset", dataset, {"dataset"})
    if call.need("tolerance", tolerance, "declared tracking tolerance"):
        call.unit("tolerance", tolerance, {"V", "A"})
    return call.finish()


@_d_atom
def D_atom_qualify_dataset_check_continuity(
    dataset: ProductRef | None = None,
    axes: AxisSpec | None = None,
    thresholds: ContinuityThresholds | None = None,
) -> dict:
    """Report spikes, steps and range-change glitches; report-only, never masks."""
    call = _Call("D_atom_qualify_dataset_check_continuity", locals())
    call.product("dataset", dataset, {"dataset"})
    call.need("axes", axes)
    call.need("thresholds", thresholds, "declared spike/step thresholds")
    return call.finish()


@_d_atom
def D_atom_qualify_cv_check_correction(
    dataset: ProductRef | None = None,
    correction_evidence: Envelopes | None = None,
    compensation: CompensationRecord | None = None,
    max_age_s: Annotated[float, Field(gt=0)] | None = None,
) -> dict:
    """Check correction state and coverage of measured frequencies (CMU stub)."""
    call = _Call("D_atom_qualify_cv_check_correction", locals())
    call.product("dataset", dataset, {"dataset"})
    call.envelopes("correction_evidence", correction_evidence)
    call.optional_evidence("correction_evidence", correction_evidence, "CORRST?/CORRL? absent")
    call.optional_evidence("compensation", compensation, "compensation record absent")
    call.optional_evidence("max_age_s", max_age_s, "correction age limit not declared")
    return call.finish()


@_d_atom
def D_atom_qualify_timeseries_check_events(
    dataset: ProductRef | None = None,
    event_plan: Annotated[list[WgfmuEventSpec], Field(max_length=256)] | None = None,
    status_evidence: Envelopes | None = None,
) -> dict:
    """Check events vs plan, the 10 ns grid and readable channel status (WGFMU stub)."""
    call = _Call("D_atom_qualify_timeseries_check_events", locals())
    call.product("dataset", dataset, {"dataset"})
    call.need("event_plan", event_plan)
    call.envelopes("status_evidence", status_evidence)
    call.optional_evidence("status_evidence", status_evidence, "channel status/errors absent")
    return call.finish()


# ---------------------------------------------------------------------------
# D class - shape: lossless views
# ---------------------------------------------------------------------------


@_d_atom
def D_atom_shape_dataset_split_segments(
    dataset: ProductRef | None = None,
    rule: SegmentRule | None = None,
) -> dict:
    """Split a dataset into forward/reverse, VAR2, repeat or event segments; values untouched."""
    call = _Call("D_atom_shape_dataset_split_segments", locals())
    call.product("dataset", dataset, {"dataset"})
    call.need("rule", rule)
    return call.finish()


@_d_atom
def D_atom_shape_dataset_stack_family(
    members: Annotated[list[FamilyMember], Field(max_length=16)] | None = None,
    outer_parameter: Terminal | None = None,
) -> dict:
    """Stack 2..16 same-schema datasets by an outer parameter (for example per gate bias)."""
    call = _Call("D_atom_shape_dataset_stack_family", locals())
    call.need("outer_parameter", outer_parameter)
    if call.need("members", members):
        if not 2 <= len(members or []) <= 16:
            call.reject("members needs 2..16 entries.")
        units = {member.outer_value.unit for member in members or []}
        if len(units) > 1:
            call.fail("unit_mismatch", f"outer_value units differ: {sorted(units)}.")
        for index, member in enumerate(members or []):
            call.product(f"members[{index}].dataset", member.dataset, {"dataset"})
            call.product(f"members[{index}].trust", member.trust, {"trust_summary"})
    return call.finish()


@_d_atom
def D_atom_shape_dataset_normalize_geometry(
    dataset: ProductRef | None = None,
    geometry: Geometry | None = None,
) -> dict:
    """Add W- or area-normalized derived columns (A/m, A/m^2, F/m^2) as a new view."""
    call = _Call("D_atom_shape_dataset_normalize_geometry", locals())
    call.product("dataset", dataset, {"dataset", "view"})
    call.need("geometry", geometry, "declared device geometry")
    return call.finish()


# ---------------------------------------------------------------------------
# D class - derive: generic numerics on masked rows (declared methods only)
# ---------------------------------------------------------------------------


@_d_atom
def D_atom_derive_curve_compute_derivative(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    axes: AxisSpec | None = None,
    method: DerivativeMethod | None = None,
) -> dict:
    """dy/dx on masked rows by a declared method; never bridges excluded rows."""
    call = _Call("D_atom_derive_curve_compute_derivative", locals())
    call.product("dataset", dataset, {"dataset", "view"})
    call.product("trust", trust, {"trust_summary"}, required=False)
    call.optional_evidence("trust", trust, "no fit mask supplied")
    call.need("axes", axes)
    if call.need("method", method, "declared derivative method"):
        _method(call, method.name, method)
    return call.finish()


@_d_atom
def D_atom_derive_curve_interpolate(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    axes: AxisSpec | None = None,
    mode: Literal["y_at_x", "x_at_y", "resample"] | None = None,
    targets: Annotated[list[Quantity], Field(max_length=256)] | None = None,
    scale: Literal["linear", "log_y"] = "linear",
    crossing: Literal["first_rising", "first_falling"] = "first_rising",
    extrapolate: bool = False,
) -> dict:
    """Interpolate y_at_x, x_at_y (first crossing with direction) or resample; no extrapolation."""
    call = _Call("D_atom_derive_curve_interpolate", locals())
    call.product("dataset", dataset, {"dataset", "view"})
    call.product("trust", trust, {"trust_summary"}, required=False)
    call.need("axes", axes)
    call.need("mode", mode)
    call.need("targets", targets)
    if mode:
        _method(call, f"interpolate_{mode}", {"scale": scale, "crossing": crossing})
    if extrapolate:
        call.warnings.append("extrapolate=true: results outside the data would be bounds only.")
    return call.finish()


@_d_atom
def D_atom_derive_curve_fit_linear(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    axes: AxisSpec | None = None,
    window: QuantityRange | None = None,
) -> dict:
    """Least-squares line over a declared x window (slope, intercepts, r^2, residual RMS, n)."""
    call = _Call("D_atom_derive_curve_fit_linear", locals())
    call.product("dataset", dataset, {"dataset", "view"})
    call.product("trust", trust, {"trust_summary"}, required=False)
    call.need("axes", axes)
    call.need("window", window, "declared fit window")
    _method(call, "least_squares_linear", {})
    return call.finish()


@_d_atom
def D_atom_derive_dataset_summarize_columns(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    columns: Annotated[list[ColumnName], Field(max_length=32)] | None = None,
    group_by: ColumnName | None = None,
) -> dict:
    """mean/std/median/min/max/n per column or segment on masked rows (repeat noise)."""
    call = _Call("D_atom_derive_dataset_summarize_columns", locals())
    call.product("dataset", dataset, {"dataset", "view"})
    call.product("trust", trust, {"trust_summary"}, required=False)
    call.need("columns", columns)
    return call.finish()


@_d_atom
def D_atom_derive_timeseries_summarize_windows(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    windows: Annotated[list[QuantityRange], Field(max_length=256)] | None = None,
    events: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=256)]
    | None = None,
) -> dict:
    """Per-window or per-event statistics and drift slope (SMU sampling; WGFMU stub)."""
    call = _Call("D_atom_derive_timeseries_summarize_windows", locals())
    call.product("dataset", dataset, {"dataset", "view"})
    call.product("trust", trust, {"trust_summary"}, required=False)
    if not windows and not events:
        call.need("windows or events", None)
    for index, window in enumerate(windows or []):
        call.unit(f"windows[{index}]", window, {"s"})
    return call.finish()


# ---------------------------------------------------------------------------
# D class - extract: named parameters, trust-gated (atom #7), criteria mandatory (U4)
# ---------------------------------------------------------------------------


@_d_atom
def D_atom_extract_leakage_current(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    terminal: Terminal | None = None,
    bias_points: Annotated[list[Quantity], Field(max_length=256)] | None = None,
    window: QuantityRange | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """|I| at declared bias points and max |I| over a declared window; floor gives a bound."""
    call = _Call("D_atom_extract_leakage_current", locals())
    _extract(call, dataset, trust, allow_untrusted)
    call.need("terminal", terminal)
    if not bias_points and window is None:
        call.need("bias_points or window", None, "U4: declared bias points or window")
    for index, point in enumerate(bias_points or []):
        call.unit(f"bias_points[{index}]", point, {"V"})
    call.unit("window", window, {"V"})
    _method(call, "abs_current_at_bias", {"terminal": terminal})
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_transfer_vth(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    vth: VthSpec | None = None,
    derivative: DerivativeMethod | None = None,
    polarity: Literal["n", "p"] | None = None,
    vds: Quantity | None = None,
    gate_terminal: Terminal | None = None,
    drain_terminal: Terminal | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """Vth by constant_current (Icc, optional W/L) or max_gm_linear_extrapolation."""
    call = _Call("D_atom_extract_transfer_vth", locals())
    _extract(call, dataset, trust, allow_untrusted)
    if call.need("vth", vth, "U4: declared Vth method"):
        call.unit("vth.icc", vth.icc, {"A"})
        if vth.method == "max_gm_linear_extrapolation":
            call.need("derivative", derivative, "required by max_gm_linear_extrapolation")
        _method(call, vth.method, vth)
    call.need("polarity", polarity)
    if call.need("vds", vds):
        call.unit("vds", vds, {"V"})
    call.need("gate_terminal", gate_terminal)
    call.need("drain_terminal", drain_terminal)
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_transfer_gm_max(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    derivative: DerivativeMethod | None = None,
    gate_terminal: Terminal | None = None,
    drain_terminal: Terminal | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """gm_max (S) and Vg at gm_max with a declared derivative method."""
    call = _Call("D_atom_extract_transfer_gm_max", locals())
    _extract(call, dataset, trust, allow_untrusted)
    if call.need("derivative", derivative, "U4: declared derivative method"):
        _method(call, "gm_max", derivative)
    call.need("gate_terminal", gate_terminal)
    call.need("drain_terminal", drain_terminal)
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_transfer_ss(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    current_window: QuantityRange | None = None,
    min_decades: Annotated[float, Field(gt=0, le=12)] | None = None,
    gate_terminal: Terminal | None = None,
    drain_terminal: Terminal | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """Minimum dVg/dlog10|Id| over a declared current window; floor-aware (V/dec, mV/dec)."""
    call = _Call("D_atom_extract_transfer_ss", locals())
    _extract(call, dataset, trust, allow_untrusted)
    if call.need("current_window", current_window, "U4: declared current window"):
        call.unit("current_window", current_window, {"A"})
    call.need("min_decades", min_decades, "U4: declared minimum decades")
    call.need("gate_terminal", gate_terminal)
    call.need("drain_terminal", drain_terminal)
    _method(call, "min_inverse_log_slope", {"min_decades": min_decades})
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_transfer_on_off(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    vg_on: Quantity | None = None,
    vg_off: Quantity | None = None,
    drain_terminal: Terminal | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """Ion and Ioff at declared gate biases and their ratio with bound propagation."""
    call = _Call("D_atom_extract_transfer_on_off", locals())
    _extract(call, dataset, trust, allow_untrusted)
    for name, value in (("vg_on", vg_on), ("vg_off", vg_off)):
        if call.need(name, value, "U4: declared bias"):
            call.unit(name, value, {"V"})
    call.need("drain_terminal", drain_terminal)
    _method(call, "current_at_declared_bias", {})
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_transfer_voltage_shift(
    segments: ProductRef | None = None,
    datasets: Annotated[list[ProductRef], Field(max_length=2)] | None = None,
    trust: ProductRef | None = None,
    at_current: Quantity | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """Signed voltage shift between two segments or two datasets at a declared current.

    Used for hysteresis; recipes reuse it for memory window or BTI shifts.
    """
    call = _Call("D_atom_extract_transfer_voltage_shift", locals())
    if segments is None and not datasets:
        call.need("segments or datasets", None, "split view or exactly two datasets")
    call.product("segments", segments, {"view"}, required=False)
    if datasets:
        call.products("datasets", datasets, {"dataset"}, min_items=2, max_items=2)
    call.product("trust", trust, {"trust_summary"})
    if call.need("at_current", at_current, "U4: declared current"):
        call.unit("at_current", at_current, {"A"})
    if allow_untrusted:
        call.warnings.append("allow_untrusted set: trust_override recorded; assess inconclusive.")
    _method(call, "voltage_at_current_difference", {})
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_output_ron(
    family: ProductRef | None = None,
    window: QuantityRange | None = None,
    drain_terminal: Terminal | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """Ron = 1/slope near Vds = 0 per outer-parameter segment of a stacked family view.

    Member trust summaries are bound into the family view by ``stack_family``.
    """
    call = _Call("D_atom_extract_output_ron", locals())
    call.product("family", family, {"view"}, producers={"D_atom_shape_dataset_stack_family"})
    if call.need("window", window, "U4: declared Vds window"):
        call.unit("window", window, {"V"})
    call.need("drain_terminal", drain_terminal)
    _method(call, "inverse_slope_near_zero", {})
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_leakage_breakdown_voltage(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    threshold: Quantity | None = None,
    direction: Literal["increasing", "decreasing"] | None = None,
    terminal: Terminal | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """First voltage where |I| >= threshold (or compliance onset); post hoc only.

    Breakdown measurements themselves need human approval; this atom never runs one.
    """
    call = _Call("D_atom_extract_leakage_breakdown_voltage", locals())
    _extract(call, dataset, trust, allow_untrusted)
    if call.need("threshold", threshold, "U4: declared current threshold"):
        call.unit("threshold", threshold, {"A"})
    call.need("direction", direction)
    call.need("terminal", terminal)
    _method(call, "first_threshold_crossing", {"direction": direction})
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_cv_cox(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    correction: ProductRef | None = None,
    window: QuantityRange | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """Cox from a declared accumulation plateau; needs the correction check (CMU stub)."""
    call = _Call("D_atom_extract_cv_cox", locals())
    _extract(call, dataset, trust, allow_untrusted)
    call.product(
        "correction",
        correction,
        {"check_report"},
        producers={"D_atom_qualify_cv_check_correction"},
    )
    if call.need("window", window, "U4: declared accumulation window"):
        call.unit("window", window, {"V"})
    _method(call, "accumulation_plateau", {})
    return call.finish(trust_override=allow_untrusted)


@_d_atom
def D_atom_extract_cv_vfb(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    vfb: VfbSpec | None = None,
    allow_untrusted: bool = False,
) -> dict:
    """Vfb by a declared method with explicit physical assumptions (CMU stub)."""
    call = _Call("D_atom_extract_cv_vfb", locals())
    _extract(call, dataset, trust, allow_untrusted)
    if call.need("vfb", vfb, "U4: declared method and physical assumptions"):
        _method(call, vfb.method, vfb)
    return call.finish(trust_override=allow_untrusted)


# ---------------------------------------------------------------------------
# D class - assess: declared criteria -> verdict label (never an action or gate)
# ---------------------------------------------------------------------------


def _criteria(call: _Call, criteria: list[Criterion] | None, source: SourceRef | None) -> None:
    if call.need("criteria", criteria, "U4: no repo-wide defaults"):
        for index, criterion in enumerate(criteria or []):
            allowed = set(PARAMETER_UNITS[criterion.parameter])
            call.unit(f"criteria[{index}].limit", criterion.limit, allowed)
    call.need("criteria_source", source, "U4: device profile, recipe or caller")


@_d_atom
def D_atom_assess_value_check_limits(
    results: Annotated[list[ProductRef], Field(max_length=32)] | None = None,
    criteria: Annotated[list[Criterion], Field(max_length=32)] | None = None,
    criteria_source: SourceRef | None = None,
) -> dict:
    """Compare extracted quantities with declared criteria (exact units, bound-aware).

    Stub label (M2): ``verdict`` is ``synthetic_only`` under synthetic origin and null
    otherwise; ``verdict_scope`` is null. Never ``pass`` or ``fail``.
    """
    call = _Call("D_atom_assess_value_check_limits", locals())
    call.products("results", results, {"extraction_result"})
    _criteria(call, criteria, criteria_source)
    return call.finish(verdict=call.label())


@_d_atom
def D_atom_assess_dataset_check_envelope(
    dataset: ProductRef | None = None,
    envelope: Annotated[list[EnvelopeLimit], Field(max_length=32)] | None = None,
    criteria_source: SourceRef | None = None,
) -> dict:
    """Post-hoc audit of observed extrema vs a declared envelope; escalates, never gates."""
    call = _Call("D_atom_assess_dataset_check_envelope", locals())
    call.product("dataset", dataset, {"dataset"})
    if call.need("envelope", envelope, "declared audit envelope"):
        for index, limit in enumerate(envelope or []):
            allowed = {"V"} if limit.quantity == "voltage" else {"A"}
            call.unit(f"envelope[{index}].low", limit.low, allowed)
            call.unit(f"envelope[{index}].high", limit.high, allowed)
    call.need("criteria_source", criteria_source, "U4: device profile, recipe or caller")
    return call.finish(verdict=call.label())


@_d_atom
def D_atom_assess_dataset_compare_reference(
    target: ProductRef | None = None,
    reference: ProductRef | None = None,
    reported_values: Annotated[list[ReportedValue], Field(max_length=64)] | None = None,
    tolerances: Annotated[list[Tolerance], Field(max_length=32)] | None = None,
    criteria_source: SourceRef | None = None,
) -> dict:
    """Deltas vs a prior run or reported (for example EasyEXPERT) values within tolerance."""
    call = _Call("D_atom_assess_dataset_compare_reference", locals())
    call.product("target", target, {"dataset", "extraction_result"})
    call.product("reference", reference, {"dataset", "extraction_result"}, required=False)
    if reference is None and not reported_values:
        call.need("reference or reported_values", None)
    for index, item in enumerate(reported_values or []):
        call.unit(f"reported_values[{index}]", item.quantity, set(PARAMETER_UNITS[item.parameter]))
    if call.need("tolerances", tolerances, "U4: declared tolerances"):
        for index, tolerance in enumerate(tolerances or []):
            allowed = set(PARAMETER_UNITS[tolerance.parameter])
            call.unit(f"tolerances[{index}].absolute", tolerance.absolute, allowed)
    call.need("criteria_source", criteria_source, "U4: device profile, recipe or caller")
    return call.finish(verdict=call.label())


# ---------------------------------------------------------------------------
# D class - archive: manifest, write-once bundle plan, verified load (U2)
# ---------------------------------------------------------------------------


@_d_atom
def D_atom_archive_run_build_manifest(
    envelopes: Annotated[list[dict[str, Any]], Field(max_length=MAX_ARCHIVE_ENVELOPES)]
    | None = None,
    products: Refs | None = None,
    intent: Annotated[str, Field(max_length=500)] | None = None,
    station: StationRef | None = None,
    created_at: datetime | None = None,
    declared_origin: DataOrigin | None = None,
) -> dict:
    """Build the audit manifest inline (never written here).

    Records intent, tool chain, station name+hash, envelope fingerprints, products and
    assumptions. Deterministic except the injectable ``created_at``.
    """
    call = _Call("D_atom_archive_run_build_manifest", locals())
    call.declared_origin = declared_origin
    if call.need("envelopes", envelopes, "at least one A/C/D envelope"):
        call.envelopes("envelopes", envelopes)
    call.need("intent", intent)
    for index, ref in enumerate(products or []):
        call.product(f"products[{index}]", ref, set(PRODUCT_TYPES))
    call.optional_evidence("station", station, "station name+hash not supplied")
    if created_at is None:
        call.assumptions.append("created_at not injected; manifest time left unset.")
    return call.finish()


@_d_atom
def D_atom_archive_run_write_bundle(
    manifest: ProductRef | None = None,
    artifacts: Annotated[list[ProductRef], Field(max_length=16)] | None = None,
) -> dict:
    """The single D writer: plans a write-once, content-addressed bundle (U2).

    There are no path inputs; ``planned_paths`` are relative to the configured data root.
    In this phase nothing is written: ``artifact_written`` is false and ``write_refusal``
    always holds ``fake_mode`` plus the origin refusal (``synthetic_origin`` for synthetic).
    """
    call = _Call("D_atom_archive_run_write_bundle", locals())
    call.product("manifest", manifest, {"manifest"})
    for index, ref in enumerate(artifacts or []):
        call.product(f"artifacts[{index}]", ref, set(_ARTIFACT_LAYOUT))
    key = f"d-bundle-{call.digest()}"
    planned = [f"processed/{key}/manifest.json"]
    for ref in artifacts or []:
        if ref.product_type in _ARTIFACT_LAYOUT:
            folder, extension = _ARTIFACT_LAYOUT[ref.product_type]
            planned.append(f"{folder}/{key}/{ref.product_type}-{ref.product_id[-16:]}.{extension}")
    origin_refusal = {
        "synthetic": ["synthetic_origin"],
        "fixture": ["fixture_requires_test_root"],
        "instrument": [],
    }[call.origin()]
    return call.finish(
        planned_paths=planned,
        artifact_written=False,
        write_refusal=["fake_mode", *origin_refusal],
    )


@_d_atom
def D_atom_archive_run_load_bundle(
    manifest: ProductRef | None = None,
    bundle_key: Annotated[str, Field(pattern=r"^d-bundle-[0-9a-f]{16}$")] | None = None,
) -> dict:
    """Read-only bundle load with per-artifact hash verification (for replay, U6).

    Stub: nothing is read; ``hash_ok`` is null and ``artifact_read`` is false.
    """
    call = _Call("D_atom_archive_run_load_bundle", locals())
    if manifest is None and bundle_key is None:
        call.need("manifest or bundle_key", None)
    call.product("manifest", manifest, {"manifest"}, required=False)
    return call.finish()


# ---------------------------------------------------------------------------
# D class - render: deterministic inline content (no files, no LLM text)
# ---------------------------------------------------------------------------


@_d_atom
def D_atom_render_dataset_build_plot_spec(
    dataset: ProductRef | None = None,
    trust: ProductRef | None = None,
    axes: AxisSpec | None = None,
    segments: ProductRef | None = None,
) -> dict:
    """Plot spec JSON: raw first, linear and semilog |I|, masked/flagged markers, units."""
    call = _Call("D_atom_render_dataset_build_plot_spec", locals())
    call.product("dataset", dataset, {"dataset", "view", "derived"})
    call.product("trust", trust, {"trust_summary"}, required=False)
    call.product("segments", segments, {"view"}, required=False)
    call.need("axes", axes)
    return call.finish()


@_d_atom
def D_atom_render_dataset_build_table(
    datasets: Annotated[list[ProductRef], Field(max_length=16)] | None = None,
    table_format: Literal["csv", "json"] = "csv",
) -> dict:
    """CSV or JSON table text with a unit header and a metadata block (returned inline)."""
    call = _Call("D_atom_render_dataset_build_table", locals())
    call.products("datasets", datasets, {"dataset", "view", "derived"})
    return call.finish()


@_d_atom
def D_atom_render_run_build_report(
    manifest: ProductRef | None = None,
    results: Annotated[list[ProductRef], Field(max_length=32)] | None = None,
    specs: Annotated[list[ProductRef], Field(max_length=16)] | None = None,
) -> dict:
    """Template Markdown report: measured, derived, assumptions, warnings, verdict sections."""
    call = _Call("D_atom_render_run_build_report", locals())
    call.product("manifest", manifest, {"manifest"})
    call.products("results", results, {"extraction_result", "verdict"}, required=False)
    call.products("specs", specs, {"plot_spec", "table"}, required=False)
    return call.finish()


D_ATOM_FUNCTIONS: list[Callable[..., dict]] = [
    D_atom_ingest_request_build_expectation,
    D_atom_ingest_smu_build_dataset,
    D_atom_ingest_easyexpert_build_dataset,
    D_atom_ingest_cmu_build_dataset,
    D_atom_ingest_wgfmu_build_series,
    D_atom_qualify_dataset_classify_status,
    D_atom_qualify_dataset_check_completeness,
    D_atom_qualify_iv_check_compliance,
    D_atom_qualify_iv_check_resolution,
    D_atom_qualify_run_check_context,
    D_atom_qualify_dataset_grade_trust,
    D_atom_qualify_iv_check_source_tracking,
    D_atom_qualify_dataset_check_continuity,
    D_atom_qualify_cv_check_correction,
    D_atom_qualify_timeseries_check_events,
    D_atom_shape_dataset_split_segments,
    D_atom_shape_dataset_stack_family,
    D_atom_shape_dataset_normalize_geometry,
    D_atom_derive_curve_compute_derivative,
    D_atom_derive_curve_interpolate,
    D_atom_derive_curve_fit_linear,
    D_atom_derive_dataset_summarize_columns,
    D_atom_derive_timeseries_summarize_windows,
    D_atom_extract_leakage_current,
    D_atom_extract_transfer_vth,
    D_atom_extract_transfer_gm_max,
    D_atom_extract_transfer_ss,
    D_atom_extract_transfer_on_off,
    D_atom_extract_transfer_voltage_shift,
    D_atom_extract_output_ron,
    D_atom_extract_leakage_breakdown_voltage,
    D_atom_extract_cv_cox,
    D_atom_extract_cv_vfb,
    D_atom_assess_value_check_limits,
    D_atom_assess_dataset_check_envelope,
    D_atom_assess_dataset_compare_reference,
    D_atom_archive_run_build_manifest,
    D_atom_archive_run_write_bundle,
    D_atom_archive_run_load_bundle,
    D_atom_render_dataset_build_plot_spec,
    D_atom_render_dataset_build_table,
    D_atom_render_run_build_report,
]


def d_atom_catalog() -> list[dict[str, str]]:
    """Static catalog rows (name, stage, subject, product type, priority, module scope)."""
    return [
        {
            "atom": name,
            "stage": spec.stage,
            "subject": spec.subject,
            "product_type": spec.product_type,
            "priority": spec.priority,
            "module": spec.module,
        }
        for name, spec in _SPECS.items()
    ]


def register_d_atoms(mcp: FastMCP) -> None:
    """Register all D_atom_* tools (fake placeholder stubs) on a FastMCP instance."""
    for tool in D_ATOM_FUNCTIONS:
        mcp.tool(tool)
