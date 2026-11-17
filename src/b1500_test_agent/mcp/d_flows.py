"""D-class fake MCP flows: deterministic compositions of D atom placeholders.

A D flow interprets evidence the caller already holds (a C flow envelope with a designated read
record). It calls only ``D_atom_*`` tools from a fixed catalog, serially and in catalog order,
and adds only ordering, skip bookkeeping, product-reference passing, label aggregation and
taint checks. It never computes numbers, fingerprints, trust or verdicts, never calls A/B/C
tools or other flows, and never writes files. Under user decision U1 every child is a
placeholder stub: the best reachable ``analysis_state`` is ``not_computed`` and synthetic data
can never pass.

Naming: ``D_flow_<operation>_<domain>_<subject>``; responses carry ``category`` (the
operation), ``domain`` and ``subject`` so callers never parse names.
Contract: ``tmp/d_flow_design_arbitration.md``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP

from b1500_test_agent.schemas import d_flow as schema
from b1500_test_agent.schemas.d_atom import DATA_ORIGIN_ORDER

from . import d_atoms

_STAGES: dict[str, str] = {row["atom"]: row["stage"] for row in d_atoms.d_atom_catalog()}
_ATOM_ERRORS = frozenset(
    {"rejected_input", "context_missing", "unit_mismatch", "size_limit", "internal_error"}
)
FORBIDDEN_LABELS = frozenset({"pass", "fail", "trusted", "trusted_with_flags"})
_LABEL_KEYS = ("verdict", "trust_level", "check_outcome")
# Worst first: the worst state over called children wins.
_STATE_ORDER = ("rejected_input", "not_computed", "not_extractable", "inconclusive", "complete")
_TRUST_ORDER = ("synthetic_only", "untrusted", "needs_review", "trusted_with_flags", "trusted")
_ENVELOPE_KEYS = frozenset({"evidence", "c_evidence"})
_ENVELOPE_LIST_KEYS = frozenset({"upstream_evidence", "envelopes"})
_FLOW_WARNING = (
    "Fake D flow (U1): placeholder composition over held evidence; no analysis was computed, "
    "no verdict or trust above synthetic_only can be produced, and no file was written."
)
EMPTY_DATA_WARNING = "Empty synthetic data is not evidence of quality."
HUMAN_APPROVAL = "human_approval (AGENTS.md); D never gates"
# Missing context caps trust at needs_review (D atom arbitration #14); an incomplete pin map
# needs human review (AGENTS.md), so standalone D reports it instead of rejecting.
PIN_MAP_TRUST_CAP = "needs_review"

_Q_IV = (
    "D_atom_ingest_request_build_expectation",
    "D_atom_ingest_smu_build_dataset",
    "D_atom_qualify_dataset_classify_status",
    "D_atom_qualify_dataset_check_completeness",
    "D_atom_qualify_iv_check_compliance",
    "D_atom_qualify_iv_check_resolution",
    "D_atom_qualify_iv_check_source_tracking",
    "D_atom_qualify_run_check_context",
    "D_atom_qualify_dataset_grade_trust",
)
_TRANSFER_ATOMS = {
    "gm_max": "D_atom_extract_transfer_gm_max",
    "vth": "D_atom_extract_transfer_vth",
    "ss": "D_atom_extract_transfer_ss",
    "on_off": "D_atom_extract_transfer_on_off",
    "voltage_shift": "D_atom_extract_transfer_voltage_shift",
}


@dataclass(frozen=True)
class _FlowSpec:
    """Static catalog entry; category/domain/subject are declared, never parsed from names."""

    category: str
    domain: str
    subject: str
    priority: str
    purpose: str


_CATALOG: dict[str, _FlowSpec] = {
    "D_flow_qualify_iv_dataset": _FlowSpec(
        "qualify", "iv", "dataset", "P0", "Trust-graded SMU IV dataset with check reports (Q_IV)."
    ),
    "D_flow_screen_iv_leakage": _FlowSpec(
        "screen", "iv", "leakage", "P0",
        "Q_IV, leakage at declared biases, one verdict label per declared criterion set.",
    ),
    "D_flow_archive_run_bundle": _FlowSpec(
        "archive", "run", "bundle", "P0",
        "Run manifest plus write-once bundle plan; nothing is written (U2).",
    ),
    "D_flow_analyze_iv_transfer": _FlowSpec(
        "analyze", "iv", "transfer", "P1",
        "Q_IV, optional segmentation, then the selected transfer extractions; no verdict.",
    ),
    "D_flow_analyze_iv_output": _FlowSpec(
        "analyze", "iv", "output", "P2",
        "Q_IV per family member, stacked family view and Ron extraction; no verdict.",
    ),
    "D_flow_qualify_cv_dataset": _FlowSpec(
        "qualify", "cv", "dataset", "P2",
        "Trust-graded MFCMU dataset (Q_CV); CMU real use blocked (AGENTS.md).",
    ),
    "D_flow_qualify_timeseries_dataset": _FlowSpec(
        "qualify", "timeseries", "dataset", "P2",
        "Trust-graded WGFMU series (Q_TS); real input blocked by gap G4.",
    ),
}  # fmt: skip

RESERVED_D_FLOWS: tuple[str, ...] = (
    "D_flow_analyze_cv_capacitance",
    "D_flow_render_run_report",
    "D_flow_replay_run_bundle",
)


# ---------------------------------------------------------------------------
# Shared helpers (also used by the CD runner)
# ---------------------------------------------------------------------------


def now() -> str:
    """UTC ISO timestamp for audit records."""
    return datetime.now(timezone.utc).isoformat()


def tool_name(envelope: Any) -> str | None:
    """Name of a tool envelope (flow or atom), or None for anonymous evidence."""
    if not isinstance(envelope, dict):
        return None
    name = envelope.get("flow") or envelope.get("atom")
    return name if isinstance(name, str) else None


def origin_of(result: dict) -> str:
    """Declared origin of a D result; a missing or unknown value counts as synthetic."""
    origin = result.get("data_origin")
    return origin if origin in DATA_ORIGIN_ORDER else "synthetic"


def labels(value: Any):
    """Yield (key, label) for verdict, trust and check labels anywhere in an outputs tree."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _LABEL_KEYS and isinstance(item, str):
                yield key, item
            else:
                yield from labels(item)
    elif isinstance(value, list):
        for item in value:
            yield from labels(item)


def marker_problem(result: dict) -> str | None:
    """U1 phase rule: D children must be ``fake: true`` and ``hardware_touched: false``."""
    if result.get("fake") is not True or result.get("hardware_touched") is not False:
        return (
            f"returned fake={result.get('fake')!r}, hardware_touched="
            f"{result.get('hardware_touched')!r}; only fake, hardware-free children are accepted"
        )
    return None


def taint_problem(result: dict, ceiling: str) -> str | None:
    """A stronger origin than the evidence, or a pass/fail/trusted label off instrument data."""
    origin = result.get("data_origin")
    if origin in DATA_ORIGIN_ORDER and schema.stronger(origin, ceiling):
        return f"reported data_origin {origin!r} above the evidence origin {ceiling!r}"
    if ceiling != "instrument":
        for key, value in labels(result.get("outputs")):
            if value in FORBIDDEN_LABELS:
                return f"reported {key} {value!r} on {ceiling} data"
    return None


def worst_state(states: list[Any]) -> str | None:
    known = [state for state in states if state in _STATE_ORDER]
    return min(known, key=_STATE_ORDER.index) if known else None


def worst_trust(levels: list[Any]) -> str | None:
    known = [level for level in levels if level in _TRUST_ORDER]
    return min(known, key=_TRUST_ORDER.index) if known else None


def evidence_citation(
    origin: str, analysis_state: str, trust_level: Any, verdict: Any, manifest_present: bool
) -> dict[str, Any]:
    """U5 citation label (never a gate). Eligibility needs instrument origin, computed
    analysis, trust >= trusted_with_flags, verdict pass and a manifest; approval is external."""
    blockers = []
    if origin != "instrument":
        blockers.append(f"{origin}_origin")
    if analysis_state != "complete":
        blockers.append("analysis_not_computed")
    else:
        if trust_level not in ("trusted", "trusted_with_flags"):
            blockers.append("trust_below_trusted_with_flags")
        if verdict != "pass":
            blockers.append("verdict_not_pass")
    if not manifest_present:
        blockers.append("manifest_absent")
    return {
        "eligible": not blockers,
        "blockers": blockers,
        "external_requirements": [HUMAN_APPROVAL],
    }


def collect(pairs: list[tuple[str | None, Any]]) -> list[str]:
    """Format (source, message) pairs once per message, prefixed by the first source."""
    collected: list[str] = []
    seen: set[str] = set()
    for source, message in pairs:
        text = str(message)
        if text not in seen:
            seen.add(text)
            collected.append(f"{source}: {text}" if source else text)
    return collected


def product(result: dict | None) -> dict | None:
    """The primary placeholder product of a D atom result (never fabricated)."""
    outputs = result.get("outputs") if isinstance(result, dict) else None
    ref = outputs.get("product") if isinstance(outputs, dict) else None
    return ref if isinstance(ref, dict) else None


def _echo(inputs: dict[str, Any]) -> dict[str, Any]:
    """Audit echo of atom inputs: scalars and ProductRefs, envelopes by name only."""
    echoed: dict[str, Any] = {}
    for key, value in inputs.items():
        if key in _ENVELOPE_KEYS and isinstance(value, dict):
            echoed[key] = {
                "envelope": tool_name(value.get("envelope")),
                "designated_record": value.get("designated_record"),
            }
        elif key in _ENVELOPE_LIST_KEYS and isinstance(value, list):
            echoed[key] = [tool_name(item) for item in value]
        else:
            echoed[key] = value
    return echoed


# ---------------------------------------------------------------------------
# Runner (DF1): D atoms only, stop on failure, taint checks, ProductRef passing
# ---------------------------------------------------------------------------


class _Runner:
    """Serial D atom runner. The first failure stops later steps; payloads are kept as is."""

    def __init__(self, ceiling: str) -> None:
        self.ceiling = ceiling
        self.records: list[dict[str, Any]] = []
        self.error: dict[str, Any] | None = None
        self.stop_reason: str | None = None
        self.findings: list[dict[str, Any]] = []
        self.trust_cap: str | None = None

    def _record(self, atom: str, inputs: dict, member: int | None, optional: bool) -> dict:
        record = {
            "phase": _STAGES[atom],
            "atom": atom,
            "inputs": _echo(inputs),
            "timestamp": now(),
            "optional": optional,
            "reason": None,
        }
        if member is not None:
            record["member"] = member
        return record

    def skip(
        self,
        atom: str,
        reason: str,
        inputs: dict | None = None,
        *,
        member: int | None = None,
        optional: bool = True,
    ) -> None:
        record = self._record(atom, inputs or {}, member, optional)
        self.records.append({**record, "status": "skipped", "reason": reason, "result": None})

    def call(self, atom: str, inputs: dict, *, member: int | None = None) -> dict | None:
        """Call one catalog atom; return its result only when it may feed later steps."""
        if self.stop_reason:
            self.skip(atom, self.stop_reason, inputs, member=member, optional=False)
            return None
        record = self._record(atom, inputs, member, optional=False)
        try:
            result = getattr(d_atoms, atom)(**inputs)
        # Atom adapters may raise any exception type; retain the audit at this boundary.
        except Exception as exc:  # noqa: BLE001
            error = {"type": "internal_error", "message": f"{type(exc).__name__}: {exc}"[:1000]}
            self.records.append({**record, "status": "error", "result": None, "error": error})
            self._fail("internal_error", f"{atom} raised {type(exc).__name__}.", atom)
            return None
        if not isinstance(result, dict):
            error = {"type": "internal_error", "message": "child returned a non-dict result"}
            self.records.append({**record, "status": "error", "result": None, "error": error})
            self._fail("internal_error", f"{atom} returned a non-dict result.", atom)
            return None
        kind, message = None, ""
        if problem := marker_problem(result):
            kind, message = "unexpected_marker", f"{atom} {problem}."
        elif result.get("ok") is not True:
            child_error = result.get("error") if isinstance(result.get("error"), dict) else {}
            kind = child_error.get("type") if child_error.get("type") in _ATOM_ERRORS else None
            kind = kind or "internal_error"
            message = f"{atom} returned ok=false: {child_error.get('message', '')}"[:1500]
        elif problem := taint_problem(result, self.ceiling):
            kind, message = "taint_violation", f"{atom} {problem}."
        if kind is None:
            self.records.append({**record, "status": "ok", "result": result})
            return result
        error = {"type": kind, "message": message}
        self.records.append({**record, "status": "error", "result": result, "error": error})
        self._fail(kind, message, atom)
        return None

    def _fail(self, kind: str, message: str, atom: str) -> None:
        if self.error is None:
            self.error = {"type": kind, "message": message, "at": atom}
        self.stop_reason = "taint_violation" if kind == "taint_violation" else "earlier_failure"
        if kind in ("taint_violation", "unexpected_marker"):
            self.findings.append(
                {
                    "source_atom": atom,
                    "check": "taint" if kind == "taint_violation" else "marker",
                    "severity": "error",
                    "code": kind,
                    "manual_note": message,
                }
            )


# ---------------------------------------------------------------------------
# Shared chains (code helpers, not tools): Q_IV, Q_CV, Q_TS
# ---------------------------------------------------------------------------


def _check_pin_map(
    run: _Runner, evidence: schema._Evidence, roles: list[dict], member: int | None = None
) -> None:
    """Role coverage (the CD check, shared): a measured channel without a declared role is a
    ``pin_map_incomplete`` finding and caps trust at ``needs_review``; never a rejection."""
    measured = schema.measured_channels(evidence.c_flow_envelope["inputs"])
    unmapped = schema.unmapped_channels(measured, [role["channel"] for role in roles])
    if not unmapped:
        return
    finding: dict[str, Any] = {
        "source_atom": None,
        "check": "pin_map",
        "severity": "warning",
        "code": "pin_map_incomplete",
        "count": len(unmapped),
        "channels": unmapped,
        "basis": ["AGENTS.md: incomplete pin maps require human approval", "D atom #14"],
        "manual_note": (
            f"Measured channels {unmapped} have no declared role; trust is capped at "
            f"{PIN_MAP_TRUST_CAP}. Roles are never inferred."
        ),
    }
    if member is not None:
        finding["member"] = member
    run.findings.append(finding)
    run.trust_cap = PIN_MAP_TRUST_CAP


def _designated(evidence: schema._Evidence) -> dict[str, Any]:
    handoff = evidence.handoff()
    return {"envelope": evidence.c_flow_envelope, "designated_record": handoff["atom_index"]}


def _expectation(
    run: _Runner,
    evidence: schema._Evidence,
    supplied: dict | None,
    member: int | None = None,
) -> dict | None:
    """Chain head: build the expectation from the C request echo, or skip when supplied."""
    atom = "D_atom_ingest_request_build_expectation"
    if supplied is not None:
        run.skip(atom, "expectation_supplied", {"expectation": supplied}, member=member)
        return supplied
    envelope = evidence.c_flow_envelope
    inputs = {
        "acquisition_kind": evidence.kind(),
        "c_request": envelope.get("inputs"),
        "evidence": {"envelope": envelope},
        "declared_origin": evidence.declared_origin,
    }
    return product(run.call(atom, inputs, member=member))


def _compliance(c_request: dict[str, Any]) -> list[dict] | None:
    """Programmed compliance per channel, echoed from the typed C request (A or V by source)."""
    items = []
    if all(key in c_request for key in ("channel", "source", "compliance")):
        unit = "A" if c_request["source"] == "voltage" else "V"
        items.append(
            {
                "channel": c_request["channel"],
                "limit": {"value": c_request["compliance"], "unit": unit},
            }
        )
    for bias in c_request.get("bias_channels") or []:
        unit = "A" if bias.get("source") == "voltage" else "V"
        items.append(
            {"channel": bias["channel"], "limit": {"value": bias["compliance"], "unit": unit}}
        )
    return items or None


def _resolution(c_request: dict[str, Any]) -> dict[str, Any]:
    """Single-channel ranging echo; per-channel ranging stays evidence_missing (not guessed)."""
    ranging = c_request.get("ranging")
    if not isinstance(ranging, dict):
        return {}
    return {
        "module_type": ranging.get("module_type"),
        "range_mode": ranging.get("range_mode"),
        "range_value": ranging.get("range_value"),
    }


def _context_and_grade(
    run: _Runner,
    evidence: schema._Evidence,
    dataset: dict | None,
    reports: list[dict | None],
    policy: dict,
    member: int | None,
) -> dict | None:
    context = run.call(
        "D_atom_qualify_run_check_context",
        {
            "c_evidence": _designated(evidence),
            "upstream_evidence": evidence.upstream_evidence,
            "dataset": dataset,
            "declared_origin": evidence.declared_origin,
        },
        member=member,
    )
    reports = [*reports, product(context)]
    graded = run.call(
        "D_atom_qualify_dataset_grade_trust",
        {"dataset": dataset, "reports": reports, "policy": policy},
        member=member,
    )
    return product(graded)


def _q_iv(
    run: _Runner,
    evidence: schema.IvEvidence,
    roles: list[dict],
    supplied: dict | None,
    policy: dict,
    tolerance: dict | None,
    member: int | None = None,
) -> dict[str, dict | None]:
    """Q_IV: expectation -> ingest_smu -> status -> completeness -> compliance -> resolution
    -> [source_tracking] -> context -> grade_trust."""
    c_request = evidence.c_flow_envelope["inputs"]
    _check_pin_map(run, evidence, roles, member)
    expectation = _expectation(run, evidence, supplied, member)
    dataset = product(
        run.call(
            "D_atom_ingest_smu_build_dataset",
            {
                "evidence": _designated(evidence),
                "expectation": expectation,
                "channel_roles": roles,
                "declared_origin": evidence.declared_origin,
            },
            member=member,
        )
    )
    reports = [
        product(
            run.call("D_atom_qualify_dataset_classify_status", {"dataset": dataset}, member=member)
        ),
        product(
            run.call(
                "D_atom_qualify_dataset_check_completeness",
                {"dataset": dataset, "expectation": expectation},
                member=member,
            )
        ),
        product(
            run.call(
                "D_atom_qualify_iv_check_compliance",
                {
                    "dataset": dataset,
                    "compliance": _compliance(c_request),
                    "near_ratio": policy["near_compliance_ratio"],
                },
                member=member,
            )
        ),
        product(
            run.call(
                "D_atom_qualify_iv_check_resolution",
                {"dataset": dataset, **_resolution(c_request)},
                member=member,
            )
        ),
    ]
    tracking = "D_atom_qualify_iv_check_source_tracking"
    if tolerance is not None:
        reports.append(
            product(run.call(tracking, {"dataset": dataset, "tolerance": tolerance}, member=member))
        )
    else:
        run.skip(tracking, "not_requested", member=member)
    trust = _context_and_grade(run, evidence, dataset, reports, policy, member)
    return {"expectation": expectation, "dataset": dataset, "trust_summary": trust}


def _dump(model: Any) -> Any:
    return None if model is None else model.model_dump(mode="json")


def _roles(roles: list) -> list[dict]:
    return [role.model_dump(mode="json") for role in roles]


def _evidence_summary(evidence: schema._Evidence) -> dict[str, Any]:
    """Evidence echo: summarized, never re-embedded (D doc section 7)."""
    handoff = evidence.handoff()
    return {
        "source": evidence.source,
        "c_flow": tool_name(evidence.c_flow_envelope),
        "execution_state": evidence.c_flow_envelope.get("execution_state"),
        "handoff_state": handoff["state"],
        "designated_record": handoff["atom_index"],
        "element_count": handoff["element_count"],
        "upstream_evidence": [tool_name(item) for item in evidence.upstream_evidence],
        "declared_origin": evidence.declared_origin,
    }


_EVIDENCE_EXCLUDE = {"evidence": {"c_flow_envelope", "upstream_evidence"}}


def _request_echo(q: Any) -> dict[str, Any]:
    echo = q.model_dump(mode="json", exclude=_EVIDENCE_EXCLUDE)
    echo["evidence"] = _evidence_summary(q.evidence)
    return echo


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _ok_results(run: _Runner, atom: str) -> list[dict]:
    return [r["result"] for r in run.records if r["status"] == "ok" and r["atom"] == atom]


def _results(run: _Runner, *atoms: str) -> list[Any]:
    """ExtractionResult entries reported by ok extract children (empty under U1)."""
    return [
        item
        for atom in atoms
        for result in _ok_results(run, atom)
        for item in result["outputs"].get("results", [])
    ]


def _d_flow_response(
    flow: str,
    run: _Runner,
    inputs: dict[str, Any],
    products: dict[str, dict | None],
    *,
    upstream: list[str],
    extra_outputs: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    contract_gaps: list[str] | None = None,
) -> dict:
    """Standard D flow envelope (D doc section 7); a sibling of ``_flow_response``."""
    spec = _CATALOG[flow]
    called = [r for r in run.records if r["status"] != "skipped"]
    results = [r["result"] for r in called if isinstance(r.get("result"), dict)]
    ok = run.error is None
    origin = schema.weakest([run.ceiling, *(origin_of(result) for result in results)])
    state = worst_state([result.get("analysis_state") for result in results]) or "not_computed"
    if not ok:
        state = "rejected_input"
    partial = any(
        r["status"] == "error" or (r["status"] == "skipped" and not r["optional"])
        for r in run.records
    )
    check_outcomes = []
    for record in run.records:
        outputs = record["result"].get("outputs") if record["status"] == "ok" else None
        if isinstance(outputs, dict) and "check_outcome" in outputs:
            entry = {"atom": record["atom"], "check_outcome": outputs["check_outcome"]}
            if "member" in record:
                entry["member"] = record["member"]
            check_outcomes.append(entry)
    trust = worst_trust(
        [
            r["outputs"].get("trust_level")
            for r in _ok_results(run, "D_atom_qualify_dataset_grade_trust")
        ]
    )
    if trust is not None and run.trust_cap is not None:
        # A cap only lowers a graded label; it never invents one (U1: no trust is computed).
        trust = worst_trust([trust, run.trust_cap])
    assessed = _ok_results(run, "D_atom_assess_value_check_limits")
    verdict = assessed[-1]["outputs"].get("verdict") if assessed else None
    scope = assessed[-1]["outputs"].get("verdict_scope") if assessed else None
    findings = list(run.findings)
    warning_pairs: list[tuple[str | None, Any]] = [
        (None, w) for w in [_FLOW_WARNING, *(warnings or [])]
    ]
    assumption_pairs: list[tuple[str | None, Any]] = []
    missing_pairs: list[tuple[str | None, Any]] = []
    required_pairs: list[tuple[str | None, Any]] = []
    for record in called:
        result = record.get("result")
        if not isinstance(result, dict):
            continue
        atom = record["atom"]
        for finding in result.get("findings") or []:
            if isinstance(finding, dict):
                entry = {"source_atom": atom, **finding}
                if "member" in record:
                    entry["member"] = record["member"]
                findings.append(entry)
        warning_pairs += [(atom, item) for item in result.get("warnings") or []]
        assumption_pairs += [(atom, item) for item in result.get("assumptions") or []]
        missing_pairs += [(atom, item) for item in result.get("evidence_missing") or []]
        required_pairs += [(None, item) for item in result.get("required_inputs") or []]
    outputs: dict[str, Any] = {
        "products": {name: ref for name, ref in products.items() if ref is not None},
        "check_outcomes": check_outcomes,
        "trust_level": trust,
        "verdict": verdict,
        "verdict_scope": scope,
        **(extra_outputs or {}),
    }
    envelope: dict[str, Any] = {
        "flow": flow,
        "flow_class": "D",
        "category": spec.category,
        "domain": spec.domain,
        "subject": spec.subject,
        "purpose": spec.purpose,
        "fake": all(result.get("fake") is True for result in results),
        "hardware_touched": any(result.get("hardware_touched") is True for result in results),
        "deterministic": True,
        "ok": ok,
        "partial": partial,
        "destructive": False,
        "consumptive": False,
        "analysis_state": state,
        "analysis_completed": False,
        "data_origin": origin,
        "synthetic": origin == "synthetic",
        "atoms_called": [r["atom"] for r in called],
        "atom_results": run.records,
        "inputs": inputs,
        "outputs": outputs,
        "findings": findings,
        "warnings": collect(warning_pairs),
        "assumptions": collect(assumption_pairs),
        "evidence_missing": collect(missing_pairs),
        "required_inputs": collect(required_pairs),
        "contract_gaps": list(contract_gaps or []),
        "provenance": {
            "flow_version": schema.FLOW_VERSION,
            "schema_version": schema.SCHEMA_VERSION,
            "status_table_version": None,
            "upstream": upstream,
        },
        "side_effects": {"hardware": "none", "filesystem_writes": [], "artifact_written": False},
        "cleanup": {"owner": "none", "performed": False},
    }
    if not ok:
        envelope["error"] = run.error
    return envelope


def _evidence_warnings(*evidences: schema._Evidence) -> list[str]:
    if any(evidence.handoff()["state"] == "empty" for evidence in evidences):
        return [EMPTY_DATA_WARNING]
    return []


def _upstream(evidence: schema._Evidence, supplied: dict | None) -> list[str]:
    names = [tool_name(evidence.c_flow_envelope)]
    names += [tool_name(item) for item in evidence.upstream_evidence]
    if supplied is not None:
        names.append(supplied.get("product_id"))
    return [name for name in names if name]


# ---------------------------------------------------------------------------
# D flow tools
# ---------------------------------------------------------------------------


def D_flow_qualify_iv_dataset(request: schema.DQualifyIv) -> dict:
    """Qualify one held SMU dataset (Q_IV): expectation, ingest, status, completeness,
    compliance, resolution, [source tracking], context, trust grade. Placeholder products only.
    """
    q = schema.DQualifyIv.model_validate(request)
    run = _Runner(q.evidence.origin())
    supplied = _dump(q.expectation)
    chain = _q_iv(
        run, q.evidence, _roles(q.channel_roles), supplied, _dump(q.trust_policy),
        _dump(q.source_tracking_tolerance),
    )  # fmt: skip
    return _d_flow_response(
        "D_flow_qualify_iv_dataset",
        run,
        _request_echo(q),
        chain,
        upstream=_upstream(q.evidence, supplied),
        warnings=_evidence_warnings(q.evidence),
    )


def D_flow_screen_iv_leakage(request: schema.DScreenIvLeakage) -> dict:
    """Screen leakage: Q_IV, leakage extraction at declared biases, verdict label against
    declared criteria (U4: mandatory). Synthetic data yields ``synthetic_only``, never pass.
    """
    q = schema.DScreenIvLeakage.model_validate(request)
    run = _Runner(q.evidence.origin())
    supplied = _dump(q.expectation)
    chain = _q_iv(
        run, q.evidence, _roles(q.channel_roles), supplied, _dump(q.trust_policy),
        _dump(q.source_tracking_tolerance),
    )  # fmt: skip
    spec = q.leakage
    leak = run.call(
        "D_atom_extract_leakage_current",
        {
            "dataset": chain["dataset"],
            "trust": chain["trust_summary"],
            "terminal": spec.terminal,
            "bias_points": [{"value": v, "unit": "V"} for v in spec.bias_points_v] or None,
            "window": None
            if spec.window_v is None
            else {"low": spec.window_v[0], "high": spec.window_v[1], "unit": "V"},
        },
    )
    criteria = [criterion.model_dump(mode="json") for criterion in spec.criteria]
    source = spec.criteria_source.model_dump(mode="json")
    limits = run.call(
        "D_atom_assess_value_check_limits",
        {"results": [product(leak)], "criteria": criteria, "criteria_source": source},
    )
    products = {**chain, "leakage": product(leak), "verdict": product(limits)}
    envelope = _d_flow_response(
        "D_flow_screen_iv_leakage",
        run,
        _request_echo(q),
        products,
        upstream=_upstream(q.evidence, supplied),
        warnings=_evidence_warnings(q.evidence),
        extra_outputs={
            "results": _results(run, "D_atom_extract_leakage_current"),
            "criteria_echo": {"criteria": criteria, "criteria_source": source},
        },
    )
    outputs = envelope["outputs"]
    outputs["evidence_citation"] = evidence_citation(
        envelope["data_origin"],
        envelope["analysis_state"],
        outputs["trust_level"],
        outputs["verdict"],
        manifest_present=False,
    )
    return envelope


def D_flow_analyze_iv_transfer(request: schema.DAnalyzeIvTransfer) -> dict:
    """Analyze a transfer curve: Q_IV, [split_segments], then the selected gm_max, Vth, SS,
    on/off and voltage-shift extractions in catalog order. Parameters only, never a verdict.
    """
    q = schema.DAnalyzeIvTransfer.model_validate(request)
    run = _Runner(q.evidence.origin())
    supplied = _dump(q.expectation)
    chain = _q_iv(
        run, q.evidence, _roles(q.channel_roles), supplied, _dump(q.trust_policy),
        _dump(q.source_tracking_tolerance),
    )  # fmt: skip
    t = q.transfer
    dataset, trust = chain["dataset"], chain["trust_summary"]
    split = "D_atom_shape_dataset_split_segments"
    segments = None
    if t.segments is not None:
        segments = product(run.call(split, {"dataset": dataset, "rule": _dump(t.segments)}))
    else:
        run.skip(split, "not_requested")
    terminals = {"gate_terminal": t.gate_terminal, "drain_terminal": t.drain_terminal}
    step_inputs: dict[str, dict[str, Any]] = {
        "gm_max": {"derivative": _dump(t.derivative), **terminals},
        "vth": {
            "vth": _dump(t.vth),
            "derivative": _dump(t.derivative),
            "polarity": t.polarity,
            "vds": _dump(t.vds),
            **terminals,
        },
        "ss": {
            "current_window": None if t.ss is None else _dump(t.ss.current_window),
            "min_decades": None if t.ss is None else t.ss.min_decades,
            **terminals,
        },
        "on_off": {
            "vg_on": None if t.on_off is None else _dump(t.on_off.vg_on),
            "vg_off": None if t.on_off is None else _dump(t.on_off.vg_off),
            "drain_terminal": t.drain_terminal,
        },
    }
    products: dict[str, dict | None] = {**chain, "segments": segments}
    selected = set(t.selected())
    for name in schema.TRANSFER_ORDER:
        atom = _TRANSFER_ATOMS[name]
        if name not in selected:
            run.skip(atom, "not_requested")
            continue
        if name == "voltage_shift":
            inputs = {"segments": segments, "trust": trust, "at_current": _dump(t.shift_at_current)}
        else:
            inputs = {"dataset": dataset, "trust": trust, **step_inputs[name]}
        products[name] = product(run.call(atom, inputs))
    return _d_flow_response(
        "D_flow_analyze_iv_transfer",
        run,
        _request_echo(q),
        products,
        upstream=_upstream(q.evidence, supplied),
        warnings=_evidence_warnings(q.evidence),
        extra_outputs={
            "results": _results(run, *_TRANSFER_ATOMS.values()),
            "selected_parameters": t.selected(),
            "criteria_source": t.criteria_source.model_dump(mode="json"),
        },
    )


def D_flow_analyze_iv_output(request: schema.DAnalyzeIvOutput) -> dict:
    """Analyze an output-curve family: Q_IV per member (2..16, serial), stack_family by the
    declared outer parameter, then Ron per segment over the declared Vds window. No verdict.
    """
    q = schema.DAnalyzeIvOutput.model_validate(request)
    ceiling = schema.weakest([member.evidence.origin() for member in q.members])
    run = _Runner(ceiling)
    roles, policy = _roles(q.channel_roles), _dump(q.trust_policy)
    products: dict[str, dict | None] = {}
    family_members = []
    for index, member in enumerate(q.members):
        chain = _q_iv(run, member.evidence, roles, None, policy, None, member=index)
        products[f"members[{index}].dataset"] = chain["dataset"]
        products[f"members[{index}].trust_summary"] = chain["trust_summary"]
        family_members.append(
            {
                "dataset": chain["dataset"],
                "trust": chain["trust_summary"],
                "outer_value": _dump(member.outer_value),
            }
        )
    family = product(
        run.call(
            "D_atom_shape_dataset_stack_family",
            {"members": family_members, "outer_parameter": q.outer_parameter},
        )
    )
    ron = run.call(
        "D_atom_extract_output_ron",
        {"family": family, "window": _dump(q.ron_window), "drain_terminal": q.drain_terminal},
    )
    products.update({"family": family, "ron": product(ron)})
    echo = q.model_dump(
        mode="json",
        exclude={"members": {"__all__": {"evidence": {"c_flow_envelope", "upstream_evidence"}}}},
    )
    for index, member in enumerate(q.members):
        echo["members"][index]["evidence"] = _evidence_summary(member.evidence)
    upstream = [name for member in q.members for name in _upstream(member.evidence, None)]
    return _d_flow_response(
        "D_flow_analyze_iv_output",
        run,
        echo,
        products,
        upstream=upstream,
        warnings=_evidence_warnings(*(member.evidence for member in q.members)),
        extra_outputs={
            "results": _results(run, "D_atom_extract_output_ron"),
            "criteria_source": q.criteria_source.model_dump(mode="json"),
        },
    )


def D_flow_qualify_cv_dataset(request: schema.DQualifyCv) -> dict:
    """Qualify one held MFCMU dataset (Q_CV): expectation, ingest_cmu, status, completeness,
    correction check, context, trust grade. CMU stub; real C-V waits for correction/SCUU/leakage.
    """
    q = schema.DQualifyCv.model_validate(request)
    run = _Runner(q.evidence.origin())
    supplied = _dump(q.expectation)
    _check_pin_map(run, q.evidence, _roles(q.channel_roles))
    expectation = _expectation(run, q.evidence, supplied)
    dataset = product(
        run.call(
            "D_atom_ingest_cmu_build_dataset",
            {
                "evidence": _designated(q.evidence),
                "expectation": expectation,
                "imp_model": q.imp_model,
                "sweep_kind": q.sweep_kind,
                "channel_roles": _roles(q.channel_roles),
                "declared_origin": q.evidence.declared_origin,
            },
        )
    )
    reports = [
        product(run.call("D_atom_qualify_dataset_classify_status", {"dataset": dataset})),
        product(
            run.call(
                "D_atom_qualify_dataset_check_completeness",
                {"dataset": dataset, "expectation": expectation},
            )
        ),
        product(run.call("D_atom_qualify_cv_check_correction", {"dataset": dataset})),
    ]
    trust = _context_and_grade(run, q.evidence, dataset, reports, _dump(q.trust_policy), None)
    return _d_flow_response(
        "D_flow_qualify_cv_dataset",
        run,
        _request_echo(q),
        {"expectation": expectation, "dataset": dataset, "trust_summary": trust},
        upstream=_upstream(q.evidence, supplied),
        warnings=_evidence_warnings(q.evidence),
    )


def D_flow_qualify_timeseries_dataset(request: schema.DQualifyTimeseries) -> dict:
    """Qualify one held WGFMU series (Q_TS): expectation, ingest_wgfmu, completeness, events,
    context, trust grade. No status classification (WGFMU has no per-point status). Stub (G4).
    """
    q = schema.DQualifyTimeseries.model_validate(request)
    run = _Runner(q.evidence.origin())
    supplied = _dump(q.expectation)
    _check_pin_map(run, q.evidence, _roles(q.channel_roles))
    expectation = _expectation(run, q.evidence, supplied)
    plan = [event.model_dump(mode="json") for event in q.event_plan]
    dataset = product(
        run.call(
            "D_atom_ingest_wgfmu_build_series",
            {
                "evidence": _designated(q.evidence),
                "expectation": expectation,
                "measure_mode": q.measure_mode,
                "event_plan": plan,
                "channel_roles": _roles(q.channel_roles),
                "declared_origin": q.evidence.declared_origin,
            },
        )
    )
    reports = [
        product(
            run.call(
                "D_atom_qualify_dataset_check_completeness",
                {"dataset": dataset, "expectation": expectation},
            )
        ),
        product(
            run.call(
                "D_atom_qualify_timeseries_check_events", {"dataset": dataset, "event_plan": plan}
            )
        ),
    ]
    trust = _context_and_grade(run, q.evidence, dataset, reports, _dump(q.trust_policy), None)
    return _d_flow_response(
        "D_flow_qualify_timeseries_dataset",
        run,
        _request_echo(q),
        {"expectation": expectation, "dataset": dataset, "trust_summary": trust},
        upstream=_upstream(q.evidence, supplied),
        warnings=_evidence_warnings(q.evidence),
    )


def D_flow_archive_run_bundle(request: schema.DArchiveRun) -> dict:
    """Archive a run: build_manifest -> [render table if include_table] -> write_bundle.

    Under U2 nothing is written: ``planned_paths`` are relative to the configured data root,
    ``artifact_written`` is false and ``write_refusal`` explains why.
    """
    q = schema.DArchiveRun.model_validate(request)
    ceiling = schema.weakest([schema.evidence_origin(envelope) for envelope in q.envelopes])
    run = _Runner(ceiling)
    found = len(schema.envelope_products(q.envelopes))
    refs = q.manifest_products()
    warnings = []
    if found > len(refs):
        warnings.append(
            f"{found} product refs exceed the manifest cap {schema.MAX_MANIFEST_PRODUCTS}; "
            "the remainder is recorded only inside the archived envelopes."
        )
    manifest = product(
        run.call(
            "D_atom_archive_run_build_manifest",
            {
                "envelopes": q.envelopes,
                "products": refs,
                "intent": q.intent,
                "station": _dump(q.station),
                "created_at": None if q.created_at is None else q.created_at.isoformat(),
            },
        )
    )
    table_atom = "D_atom_render_dataset_build_table"
    table = None
    if q.include_table:
        # The request validator guarantees at least one dataset, view or derived ref here.
        datasets = q.table_datasets()
        table = product(run.call(table_atom, {"datasets": datasets, "table_format": "csv"}))
    else:
        run.skip(table_atom, "not_requested")
    bundle = run.call(
        "D_atom_archive_run_write_bundle",
        {"manifest": manifest, "artifacts": [table] if table else None},
    )
    bundle_outputs = bundle["outputs"] if bundle else {}
    echo = q.model_dump(mode="json", exclude={"envelopes"})
    echo["envelopes"] = [
        {
            "name": tool_name(envelope),
            "fake": envelope.get("fake"),
            "hardware_touched": envelope.get("hardware_touched"),
            "ok": envelope.get("ok"),
        }
        for envelope in q.envelopes
    ]
    return _d_flow_response(
        "D_flow_archive_run_bundle",
        run,
        echo,
        {"manifest": manifest, "table": table, "bundle_plan": product(bundle)},
        upstream=[name for name in map(tool_name, q.envelopes) if name],
        warnings=warnings,
        extra_outputs={
            "archive": {
                "manifest_ref": manifest,
                "bundle_plan_ref": product(bundle),
                "planned_paths": list(bundle_outputs.get("planned_paths", [])),
                "artifact_written": False,
                "write_refusal": list(bundle_outputs.get("write_refusal", [])),
            }
        },
    )


D_FLOW_FUNCTIONS: list[Callable[..., dict]] = [
    D_flow_qualify_iv_dataset,
    D_flow_screen_iv_leakage,
    D_flow_archive_run_bundle,
    D_flow_analyze_iv_transfer,
    D_flow_analyze_iv_output,
    D_flow_qualify_cv_dataset,
    D_flow_qualify_timeseries_dataset,
]


def d_flow_catalog() -> list[dict[str, str]]:
    """Static catalog rows (name, category, domain, subject, priority)."""
    return [
        {
            "flow": name,
            "category": spec.category,
            "domain": spec.domain,
            "subject": spec.subject,
            "priority": spec.priority,
        }
        for name, spec in _CATALOG.items()
    ]


def register_d_flows(mcp: FastMCP) -> None:
    """Register all D_flow_* tools (fake placeholder compositions) with typed requests."""
    for tool in D_FLOW_FUNCTIONS:
        mcp.tool(tool)
