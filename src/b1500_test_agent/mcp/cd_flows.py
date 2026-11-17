"""CD-class fake MCP flows: measure with one C flow, interpret with its D flow, archive.

Phases are ``expect -> measure -> interpret -> archive``:

1. expect: ``D_atom_ingest_request_build_expectation`` from the typed C request;
2. measure: exactly one ``C_flow_<acquisition.kind>`` call (never retried or repeated);
3. interpret: the D flow with the same name, only on the C flow's designated read record
   after ``simulated_complete`` (handoff ``received`` or ``empty``), then the optional P1
   ``D_atom_assess_dataset_check_envelope``;
4. archive: ``D_flow_archive_run_bundle`` whenever measure was attempted (planned paths only).

CD never calls A/B tools or C atoms directly: A/B prerequisites are reported, and caller-passed
A/B evidence is forwarded as unverified and never lifts trust. ``ok`` reflects composition
errors only, never a verdict. CD stays fake-only (user decision U7) and performs no cleanup.
Contract: ``tmp/cd_flow_design_arbitration.md``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP

from b1500_test_agent.schemas import cd_flow as schema
from b1500_test_agent.schemas import d_flow as d_schema

from . import c_flows, d_atoms, d_flows
from .d_flows import (
    EMPTY_DATA_WARNING,
    collect,
    evidence_citation,
    marker_problem,
    now,
    origin_of,
    product,
    taint_problem,
    worst_state,
)

_EXPECT_ATOM = "D_atom_ingest_request_build_expectation"
_ENVELOPE_ATOM = "D_atom_assess_dataset_check_envelope"
_ARCHIVE_FLOW = "D_flow_archive_run_bundle"
_PHASES = ("expect", "measure", "interpret", "archive")
# U7: CD is fake-only. Every C child that passes the marker check is fake, so the evidence
# ceiling is synthetic; a non-fake child stops the run as an unexpected marker.
_CEILING = "synthetic"
_CD_WARNING = (
    "Fake CD composition (U7): C -> D runs here only as a contract composition; real runs are "
    "C -> outer safe state -> D -> archive. No hardware, no cleanup, no file writes."
)
_CD_ASSUMPTION = (
    "Cleanup belongs to the outer ABC transaction; it must be installed before CD is called."
)
_HANDOFF_GAPS = {
    "c_no_data_record": "Handoff: the C flow completed without a designated read record.",
    "c_ambiguous_read_records": "Handoff: several read records; D never guesses which one.",
    "c_read_record_without_data": "Handoff: the designated read record carries no data field.",
    "c_unknown_execution_state": "Handoff: unknown C execution_state; interpretation skipped.",
}


@dataclass(frozen=True)
class _CdSpec:
    """Static catalog entry; the D flow and source are declared, never parsed from names."""

    category: str
    domain: str
    subject: str
    d_flow: str
    source: str
    priority: str
    purpose: str


_CATALOG: dict[str, _CdSpec] = {
    "CD_flow_qualify_iv_dataset": _CdSpec(
        "qualify", "iv", "dataset", "D_flow_qualify_iv_dataset", "smu", "P0",
        "Measure one SMU IV dataset with one C flow and qualify it.",
    ),
    "CD_flow_screen_iv_leakage": _CdSpec(
        "screen", "iv", "leakage", "D_flow_screen_iv_leakage", "smu", "P0",
        "Measure a voltage-sourced spot or staircase and screen its leakage.",
    ),
    "CD_flow_analyze_iv_transfer": _CdSpec(
        "analyze", "iv", "transfer", "D_flow_analyze_iv_transfer", "smu", "P1",
        "Measure a gate sweep with held drain bias and extract transfer parameters.",
    ),
    "CD_flow_qualify_cv_dataset": _CdSpec(
        "qualify", "cv", "dataset", "D_flow_qualify_cv_dataset", "cmu", "P2",
        "Measure one MFCMU dataset and qualify it (fake-only; CMU real use blocked).",
    ),
}  # fmt: skip

RESERVED_CD_FLOWS: tuple[str, ...] = ("CD_flow_qualify_timeseries_dataset",)


class _CdRun:
    """Ordered child bookkeeping; payloads are retained unchanged with UTC timestamps."""

    def __init__(self) -> None:
        self.children: list[dict[str, Any]] = []
        self.error: dict[str, Any] | None = None
        self.findings: list[dict[str, Any]] = []

    def _record(
        self,
        phase: str,
        name: str,
        kind: str,
        inputs: dict | None,
        refs: dict | None,
        optional: bool,
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "name": name,
            "kind": kind,
            "inputs": inputs or {},
            "input_refs": refs or {},
            "timestamp": now(),
            "optional": optional,
            "reason": None,
        }

    def skip(
        self, phase: str, name: str, kind: str, reason: str, *, optional: bool = False
    ) -> None:
        record = self._record(phase, name, kind, None, None, optional)
        self.children.append({**record, "status": "skipped", "reason": reason, "result": None})

    def call(
        self,
        phase: str,
        name: str,
        kind: str,
        function: Callable[..., Any],
        arguments: dict[str, Any],
        *,
        inputs: dict | None = None,
        refs: dict | None = None,
        taint: bool = True,
    ) -> tuple[str, dict | None]:
        """Invoke one child; return (outcome, result) with outcome ok|failed|marker|taint."""
        record = self._record(phase, name, kind, inputs, refs, False)
        failure = "c_failed" if kind == "c_flow" else "internal_error"
        try:
            result = function(**arguments)
        # Child adapters may raise any exception type; retain the audit at this boundary.
        except Exception as exc:  # noqa: BLE001
            error = {"type": failure, "message": f"{type(exc).__name__}: {exc}"[:1000]}
            self.children.append({**record, "status": "error", "result": None, "error": error})
            self._fail(failure, f"{name} raised {type(exc).__name__}.", name)
            return "failed", None
        if not isinstance(result, dict):
            error = {"type": failure, "message": "child returned a non-dict result"}
            self.children.append({**record, "status": "error", "result": None, "error": error})
            self._fail(failure, f"{name} returned a non-dict result.", name)
            return "failed", None
        child_error = result.get("error") if isinstance(result.get("error"), dict) else {}
        outcome, kind_of_error, message = "ok", None, ""
        if (problem := marker_problem(result)) or child_error.get("type") == "unexpected_marker":
            outcome, kind_of_error = "marker", "unexpected_marker"
            message = f"{name} {problem or 'reported an unexpected marker'}."
        elif result.get("ok") is not True:
            outcome = "failed"
            kind_of_error = failure if kind == "c_flow" else child_error.get("type") or failure
            message = f"{name} returned ok=false: {child_error.get('message', '')}"[:1500]
        elif taint and (problem := taint_problem(result, _CEILING)):
            outcome, kind_of_error, message = "taint", "taint_violation", f"{name} {problem}."
        if outcome == "ok":
            self.children.append({**record, "status": "ok", "result": result})
        else:
            error = {"type": kind_of_error, "message": message}
            self.children.append({**record, "status": "error", "result": result, "error": error})
            self._fail(kind_of_error, message, name)
        return outcome, result

    def _fail(self, kind: str, message: str, name: str) -> None:
        if self.error is None:
            self.error = {"type": kind, "message": message, "at": name}
        if kind in ("taint_violation", "unexpected_marker"):
            self.findings.append(
                {
                    "source": name,
                    "check": "taint" if kind == "taint_violation" else "marker",
                    "severity": "error",
                    "code": kind,
                    "manual_note": message,
                }
            )


def _ref(run: _CdRun, index: int | None, **extra: Any) -> dict[str, Any] | None:
    if index is None:
        return None
    return {"child_index": index, "name": run.children[index]["name"], **extra}


def _cd_compose(flow: str, q: schema.CdBase, interpret_extra: dict[str, Any]) -> dict:
    """Run expect -> measure -> interpret -> archive and build the CD envelope (section 9)."""
    spec = _CATALOG[flow]
    acquisition = q.acquisition  # type: ignore[attr-defined]
    kind = acquisition.kind
    c_name = f"C_flow_{kind}"
    run = _CdRun()
    warnings: list[str] = [_CD_WARNING]
    gaps: list[str] = []
    handoff: dict[str, Any] = {
        "state": "no_data",
        "source_atom": None,
        "child_index": None,
        "atom_index": None,
        "element_count": None,
        "reason": "c_not_run",
    }
    c_result: dict | None = None
    c_index: int | None = None
    d_result: dict | None = None
    d_outcome = "not_run"
    halted = False

    # -- expect: expectation from the typed C request, before measuring ----------------
    outcome, expect = run.call(
        "expect",
        _EXPECT_ATOM,
        "d_atom",
        getattr(d_atoms, _EXPECT_ATOM),
        {"acquisition_kind": kind, "c_request": acquisition.request.model_dump(mode="json")},
        inputs={"acquisition_kind": kind},
        refs={"c_request": "inputs.acquisition.request"},
    )
    expectation = product(expect) if outcome == "ok" else None
    if outcome != "ok":
        halted = True
        reason = "unexpected_marker" if outcome == "marker" else "earlier_failure"
        run.skip("measure", c_name, "c_flow", reason)
        run.skip("interpret", spec.d_flow, "d_flow", reason)
        run.skip("interpret", _ENVELOPE_ATOM, "d_atom", reason, optional=q.envelope is None)
        run.skip("archive", _ARCHIVE_FLOW, "d_flow", reason)

    # -- measure: exactly one C flow call ------------------------------------------------
    if not halted:
        c_index = len(run.children)
        outcome, c_result = run.call(
            "measure",
            c_name,
            "c_flow",
            getattr(c_flows, c_name),
            {"request": acquisition.request},
            inputs={"kind": kind},
            refs={"request": "inputs.acquisition.request"},
            taint=False,
        )
        if outcome == "marker":
            halted = True
            handoff = {**handoff, "child_index": c_index, "reason": "c_unexpected_marker"}
            run.skip("interpret", spec.d_flow, "d_flow", "c_unexpected_marker")
            run.skip(
                "interpret",
                _ENVELOPE_ATOM,
                "d_atom",
                "c_unexpected_marker",
                optional=q.envelope is None,
            )
            run.skip("archive", _ARCHIVE_FLOW, "d_flow", "c_unexpected_marker")
        else:
            located = d_schema.locate_handoff(c_result, spec.source)
            handoff = {**located, "child_index": c_index}

    # -- interpret: D only on the designated read record ----------------------------------
    if not halted and handoff["state"] in d_schema.USABLE_HANDOFF:
        if handoff["state"] == "empty":
            warnings.append(EMPTY_DATA_WARNING)
        d_request = {
            "evidence": {
                "source": spec.source,
                "c_flow_envelope": c_result,
                "upstream_evidence": q.upstream_evidence,
            },
            "channel_roles": [role.model_dump(mode="json") for role in q.channel_roles],
            "expectation": expectation,
            "trust_policy": q.trust_policy.model_dump(mode="json"),
            **interpret_extra,
        }
        d_index = len(run.children)
        d_outcome, d_result = run.call(
            "interpret",
            spec.d_flow,
            "d_flow",
            getattr(d_flows, spec.d_flow),
            {"request": d_request},
            inputs={"evidence": {"source": spec.source}, **interpret_extra},
            refs={
                "evidence.c_flow_envelope": _ref(run, c_index, atom_index=handoff["atom_index"]),
                "evidence.upstream_evidence": "inputs.upstream_evidence",
                "channel_roles": "inputs.channel_roles",
                "trust_policy": "inputs.trust_policy",
                "expectation": _ref(run, 0, product_id=(expectation or {}).get("product_id")),
            },
        )
        halted = d_outcome == "marker"
        if q.envelope is None:
            run.skip("interpret", _ENVELOPE_ATOM, "d_atom", "not_requested", optional=True)
        elif d_outcome != "ok":
            reason = {"taint": "taint_violation", "marker": "unexpected_marker"}.get(
                d_outcome, "earlier_failure"
            )
            run.skip("interpret", _ENVELOPE_ATOM, "d_atom", reason)
        else:
            dataset = d_result["outputs"]["products"].get("dataset")  # type: ignore[index]
            envelope_spec = q.envelope.model_dump(mode="json")
            envelope_outcome, _ = run.call(
                "interpret",
                _ENVELOPE_ATOM,
                "d_atom",
                getattr(d_atoms, _ENVELOPE_ATOM),
                {
                    "dataset": dataset,
                    "envelope": envelope_spec["limits"],
                    "criteria_source": envelope_spec["criteria_source"],
                },
                inputs=envelope_spec,
                refs={"dataset": _ref(run, d_index, product_id=(dataset or {}).get("product_id"))},
            )
            halted = envelope_outcome == "marker"
    elif not halted and c_index is not None:
        reason = handoff["reason"] or "c_no_data_record"
        run.skip("interpret", spec.d_flow, "d_flow", reason)
        run.skip("interpret", _ENVELOPE_ATOM, "d_atom", reason, optional=q.envelope is None)
        if reason in _HANDOFF_GAPS:
            gaps.append(_HANDOFF_GAPS[reason])

    # -- archive: whenever measure was attempted, except after an unexpected marker -------
    if halted and not any(r["name"] == _ARCHIVE_FLOW for r in run.children):
        run.skip("archive", _ARCHIVE_FLOW, "d_flow", "unexpected_marker")
    elif not halted and c_index is not None:
        # Every envelope is archived: MAX_ARCHIVE_ENVELOPES is derived from the CD maximums
        # (one C flow, three D children, MAX_UPSTREAM_EVIDENCE), so nothing is ever dropped.
        sources = [
            index
            for index, record in enumerate(run.children)
            if record["status"] != "skipped" and isinstance(record["result"], dict)
        ]
        upstream = q.upstream_evidence
        intent = q.intent_note or (
            f"{flow}: measure {c_name}, interpret {spec.d_flow} (fake composition)."
        )
        station = None if q.station is None else q.station.model_dump(mode="json")
        envelopes = [run.children[index]["result"] for index in sources] + upstream
        run.call(
            "archive",
            _ARCHIVE_FLOW,
            "d_flow",
            getattr(d_flows, _ARCHIVE_FLOW),
            {"request": {"envelopes": envelopes, "intent": intent, "station": station}},
            inputs={"intent": intent, "station": station},
            refs={
                "envelopes": [_ref(run, index) for index in sources]
                + [f"inputs.upstream_evidence[{k}]" for k in range(len(upstream))]
            },
        )
    return _cd_response(flow, q, run, handoff, warnings, gaps)


def _child(run: _CdRun, name: str) -> dict | None:
    return next((r for r in run.children if r["name"] == name), None)


def _cd_response(
    flow: str,
    q: schema.CdBase,
    run: _CdRun,
    handoff: dict[str, Any],
    warnings: list[str],
    gaps: list[str],
) -> dict:
    """CD envelope (CD doc section 9). Child payloads are kept once, in ``child_results``."""
    spec = _CATALOG[flow]
    kind = q.acquisition.kind  # type: ignore[attr-defined]
    c_name = f"C_flow_{kind}"
    called = [r for r in run.children if r["status"] != "skipped"]
    results = [(r, r["result"]) for r in called if isinstance(r["result"], dict)]
    c_record = _child(run, c_name)
    c_result = c_record["result"] if c_record and isinstance(c_record["result"], dict) else None
    d_record = _child(run, spec.d_flow)
    d_ok = d_record is not None and d_record["status"] == "ok"
    d_outputs = d_record["result"]["outputs"] if d_ok else {}
    archive_record = _child(run, _ARCHIVE_FLOW)
    archive_ok = archive_record is not None and archive_record["status"] == "ok"
    ok = run.error is None

    if c_result is not None:
        execution_state = c_result.get("execution_state")
    else:
        execution_state = (
            "not_run" if c_record is None or c_record["status"] == "skipped" else "failed"
        )
    interpret = [r for r in called if r["phase"] == "interpret"]
    if not interpret:
        analysis_state = "not_run"
    elif any(r["status"] == "error" for r in interpret):
        analysis_state = "rejected_input"
    else:
        analysis_state = (
            worst_state([r["result"].get("analysis_state") for r in interpret]) or "not_computed"
        )
    origins = [d_schema.evidence_origin(item) for item in q.upstream_evidence]
    if c_result is not None:
        origins.append(d_schema.evidence_origin(c_result))
    origins += [origin_of(result) for record, result in results if record["kind"] != "c_flow"]
    origin = d_schema.weakest(origins)

    products = {"expectation": product(_child(run, _EXPECT_ATOM)["result"])}  # type: ignore[index]
    products.update(d_outputs.get("products", {}))
    trust, verdict = d_outputs.get("trust_level"), d_outputs.get("verdict")
    archive_outputs = archive_record["result"]["outputs"]["archive"] if archive_ok else {}
    envelope_record = _child(run, _ENVELOPE_ATOM)
    escalations = []
    if (
        envelope_record
        and envelope_record["status"] == "ok"
        and envelope_record["result"]["outputs"].get("escalate") is True
    ):
        escalations.append({"atom": _ENVELOPE_ATOM, "product": product(envelope_record["result"])})

    required: list[tuple[str | None, Any]] = []
    if c_result is not None:
        required += [(None, item) for item in c_result.get("required_preconditions") or []]
        gaps = [*(c_result.get("contract_gaps") or []), *gaps]
    warning_pairs: list[tuple[str | None, Any]] = [(None, w) for w in warnings]
    assumption_pairs: list[tuple[str | None, Any]] = [(None, _CD_ASSUMPTION)]
    missing_pairs: list[tuple[str | None, Any]] = []
    findings = list(run.findings)
    for record, result in results:
        name = record["name"]
        warning_pairs += [(name, item) for item in result.get("warnings") or []]
        if record["kind"] == "c_flow":
            continue
        assumption_pairs += [(name, item) for item in result.get("assumptions") or []]
        missing_pairs += [(name, item) for item in result.get("evidence_missing") or []]
        required += [
            (None, item)
            for item in result.get("required_inputs") or []
            if str(item).startswith(("A_", "B_"))
        ]
        gaps += [gap for gap in result.get("contract_gaps") or [] if gap not in gaps]
        for finding in result.get("findings") or []:
            if isinstance(finding, dict):
                findings.append({"source": name, **finding})
    cleanup = (
        dict(c_result["cleanup"])
        if c_result and isinstance(c_result.get("cleanup"), dict)
        else {
            "owner": "outer_ABC_transaction"
            if c_record and c_record["status"] != "skipped"
            else "none",
            "performed": False,
        }
    )
    cleanup.update({"performed": False, "analysis_side_effects": "none"})
    atoms_called: list[str] = []
    for record in called:
        if record["kind"] == "d_atom":
            atoms_called.append(record["name"])
        elif isinstance(record["result"], dict):
            atoms_called += list(record["result"].get("atoms_called") or [])
    envelope: dict[str, Any] = {
        "flow": flow,
        "flow_class": "CD",
        "category": spec.category,
        "domain": spec.domain,
        "subject": spec.subject,
        "purpose": spec.purpose,
        "c_flow": c_name,
        "d_flow": spec.d_flow,
        "fake": all(result.get("fake") is True for _, result in results),
        "hardware_touched": any(result.get("hardware_touched") is True for _, result in results),
        "ok": ok,
        "partial": any(
            r["status"] == "error" or (r["status"] == "skipped" and not r["optional"])
            for r in run.children
        )
        or any(result.get("partial") is True for _, result in results),
        "destructive": bool(c_result and c_result.get("destructive")),
        "consumptive": bool(c_result and c_result.get("consumptive")),
        "phases": {
            phase: [
                {"child_index": index, "name": r["name"], "status": r["status"]}
                for index, r in enumerate(run.children)
                if r["phase"] == phase
            ]
            for phase in _PHASES
        },
        "flows_called": [r["name"] for r in called if r["kind"] in ("c_flow", "d_flow")],
        "atoms_called": atoms_called,
        "child_results": run.children,
        "execution_state": execution_state,
        "measurement_completed": False,
        "simulation_completed": bool(c_result and c_result.get("simulation_completed")),
        "handoff": handoff,
        "analysis_state": analysis_state,
        "analysis_completed": False,
        "data_origin": origin,
        "synthetic": origin == "synthetic",
        "inputs": q.model_dump(mode="json"),
        "outputs": {
            "products": {name: ref for name, ref in products.items() if ref is not None},
            "trust_level": trust,
            "verdict": verdict,
            "verdict_scope": d_outputs.get("verdict_scope"),
            "evidence_citation": evidence_citation(
                origin,
                analysis_state,
                trust,
                verdict,
                manifest_present=bool(archive_outputs.get("manifest_ref")),
            ),
            "escalations": escalations,
            "archive": {
                "manifest_ref": archive_outputs.get("manifest_ref"),
                "planned_paths": list(archive_outputs.get("planned_paths", [])),
                "artifact_written": False,
                "write_refusal": list(archive_outputs.get("write_refusal", [])),
            },
        },
        "required_preconditions": collect(required),
        "contract_gaps": gaps,
        "findings": findings,
        "warnings": collect(warning_pairs),
        "assumptions": collect(assumption_pairs),
        "evidence_missing": collect(missing_pairs),
        "side_effects": {"hardware": "none", "filesystem_writes": [], "artifact_written": False},
        "cleanup": cleanup,
        "audit": {
            "phase_order": list(_PHASES),
            "child_count": len(run.children),
            "skipped_children": [r["name"] for r in run.children if r["status"] == "skipped"],
            "skip_reasons": {
                r["name"]: r["reason"] for r in run.children if r["status"] == "skipped"
            },
            "consumptive_children": [
                r["name"] for r, result in results if result.get("consumptive") is True
            ],
        },
    }
    if not ok:
        envelope["error"] = run.error
    return envelope


# ---------------------------------------------------------------------------
# CD flow tools
# ---------------------------------------------------------------------------


def CD_flow_qualify_iv_dataset(request: schema.CdQualifyIv) -> dict:
    """Measure one SMU IV dataset (kind: spot_smu_iv | sweep_smu_staircase | pulse_smu_spot)
    and qualify it with D_flow_qualify_iv_dataset; then plan the archive. Fake-only (U7)."""
    q = schema.CdQualifyIv.model_validate(request)
    return _cd_compose("CD_flow_qualify_iv_dataset", q, {})


def CD_flow_screen_iv_leakage(request: schema.CdScreenIvLeakage) -> dict:
    """Measure a voltage-sourced spot or staircase (kind: spot_smu_iv | sweep_smu_staircase)
    and screen leakage against declared criteria below compliance (U4, CD11). Fake-only."""
    q = schema.CdScreenIvLeakage.model_validate(request)
    return _cd_compose(
        "CD_flow_screen_iv_leakage", q, {"leakage": q.leakage.model_dump(mode="json")}
    )


def CD_flow_analyze_iv_transfer(request: schema.CdAnalyzeIvTransfer) -> dict:
    """Measure a gate sweep with held drain bias (kind: sweep_smu_staircase_biased, U8) and
    extract the selected transfer parameters with D_flow_analyze_iv_transfer. No verdict."""
    q = schema.CdAnalyzeIvTransfer.model_validate(request)
    return _cd_compose(
        "CD_flow_analyze_iv_transfer", q, {"transfer": q.transfer.model_dump(mode="json")}
    )


def CD_flow_qualify_cv_dataset(request: schema.CdQualifyCv) -> dict:
    """Measure one MFCMU dataset (six CMU kinds) and qualify it. Fake-only: real C-V waits
    for correction, SCUU and leakage validation (AGENTS.md)."""
    q = schema.CdQualifyCv.model_validate(request)
    sweep_kind = d_schema.CV_SWEEP_KIND[q.acquisition.kind]
    return _cd_compose(
        "CD_flow_qualify_cv_dataset", q, {"imp_model": q.imp_model, "sweep_kind": sweep_kind}
    )


CD_FLOW_FUNCTIONS: list[Callable[..., dict]] = [
    CD_flow_qualify_iv_dataset,
    CD_flow_screen_iv_leakage,
    CD_flow_analyze_iv_transfer,
    CD_flow_qualify_cv_dataset,
]


def cd_flow_catalog() -> list[dict[str, str]]:
    """Static catalog rows (name, category, domain, subject, D flow, priority)."""
    return [
        {
            "flow": name,
            "category": spec.category,
            "domain": spec.domain,
            "subject": spec.subject,
            "d_flow": spec.d_flow,
            "priority": spec.priority,
        }
        for name, spec in _CATALOG.items()
    ]


def register_cd_flows(mcp: FastMCP) -> None:
    """Register all CD_flow_* tools (fake C -> D compositions) with typed requests."""
    for tool in CD_FLOW_FUNCTIONS:
        mcp.tool(tool)
