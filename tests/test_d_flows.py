"""Contracts for the fake D flow family: catalog, order, chaining, taint, validation, archive."""

import asyncio
import builtins
import copy
import io
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastmcp import Client
from pydantic import ValidationError

from b1500_test_agent.mcp import (
    a_atoms,
    a_flows,
    ab_flows,
    b_atoms,
    b_flows,
    c_atoms,
    c_flows,
    d_atoms,
)
from b1500_test_agent.mcp import d_flows as df
from b1500_test_agent.schemas import d_atom as ds
from b1500_test_agent.schemas import d_flow as schema

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / ".agents/skills/b1500-semiconductor-testing/references"
SOURCE = {"kind": "caller", "name": "test-criteria"}
GATE = [{"channel": 1, "terminal": "gate"}]
ROLES2 = [{"channel": 1, "terminal": "gate"}, {"channel": 2, "terminal": "drain"}]
WAVEFORM_CHANNEL = {
    "channel_id": 502,
    "pattern": "read_pulse",
    "vectors": [{"delta_time_s": 2e-6, "voltage_v": 0.2}],
    "events": [{"time_s": 1e-7, "points": 2}],
}
D_NAMES = [
    "D_flow_qualify_iv_dataset",
    "D_flow_screen_iv_leakage",
    "D_flow_archive_run_bundle",
    "D_flow_analyze_iv_transfer",
    "D_flow_analyze_iv_output",
    "D_flow_qualify_cv_dataset",
    "D_flow_qualify_timeseries_dataset",
]
RESERVED = ["D_flow_analyze_cv_capacitance", "D_flow_render_run_report", "D_flow_replay_run_bundle"]
FORBIDDEN = {"pass", "fail", "trusted", "trusted_with_flags"}


def _q(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


CRITERIA = [{"parameter": "leakage_current", "comparator": "le", "limit": _q(1e-9, "A")}]
LEAKAGE = {
    "terminal": "gate",
    "bias_points_v": [5.0],
    "criteria": CRITERIA,
    "criteria_source": SOURCE,
}
TRANSFER_ALL = {
    "gate_terminal": "gate",
    "drain_terminal": "drain",
    "polarity": "n",
    "vds": _q(0.05, "V"),
    "parameters": ["voltage_shift", "on_off", "ss", "vth", "gm_max"],
    "derivative": {"name": "central_difference"},
    "vth": {"method": "constant_current", "icc": _q(1e-7, "A")},
    "ss": {"current_window": {"low": 1e-11, "high": 1e-8, "unit": "A"}, "min_decades": 1.5},
    "on_off": {"vg_on": _q(5.0, "V"), "vg_off": _q(0.0, "V")},
    "segments": {"kind": "direction"},
    "shift_at_current": _q(1e-7, "A"),
    "criteria_source": SOURCE,
}
TRANSFER_VTH = {
    "gate_terminal": "gate",
    "drain_terminal": "drain",
    "polarity": "p",
    "vds": _q(-0.05, "V"),
    "parameters": ["vth"],
    "vth": {"method": "constant_current", "icc": _q(1e-7, "A")},
    "criteria_source": SOURCE,
}
EVENTS = [{"name": "meas", "time_s": 1e-7, "points": 2, "interval_s": 1e-7}]

Q_IV = [
    "D_atom_ingest_request_build_expectation",
    "D_atom_ingest_smu_build_dataset",
    "D_atom_qualify_dataset_classify_status",
    "D_atom_qualify_dataset_check_completeness",
    "D_atom_qualify_iv_check_compliance",
    "D_atom_qualify_iv_check_resolution",
    "D_atom_qualify_run_check_context",
    "D_atom_qualify_dataset_grade_trust",
]
TRACKING = "D_atom_qualify_iv_check_source_tracking"
Q_IV_RECORDS = [*Q_IV[:6], (TRACKING, "not_requested"), *Q_IV[6:]]


def _sweep(**request) -> dict:
    return c_flows.C_flow_sweep_smu_staircase({"start": 0.0, "stop": 5.0, **request})


def _iv(envelope: dict | None = None, **extra) -> dict:
    return {"source": "smu", "c_flow_envelope": envelope or _sweep(), **extra}


def _requests() -> dict[str, dict]:
    """One valid request per D flow, over real fake C envelopes."""
    sweep = _sweep()
    return {
        "D_flow_qualify_iv_dataset": {"evidence": _iv(sweep), "channel_roles": GATE},
        "D_flow_screen_iv_leakage": {
            "evidence": _iv(sweep),
            "channel_roles": GATE,
            "leakage": LEAKAGE,
        },
        "D_flow_archive_run_bundle": {
            "envelopes": [sweep],
            "intent": "Archive a synthetic staircase.",
        },
        "D_flow_analyze_iv_transfer": {
            "evidence": _iv(sweep),
            "channel_roles": ROLES2,
            "transfer": TRANSFER_ALL,
        },
        "D_flow_analyze_iv_output": {
            "members": [
                {"evidence": _iv(_sweep(stop=1.0)), "outer_value": _q(1.0, "V")},
                {"evidence": _iv(_sweep(stop=2.0)), "outer_value": _q(2.0, "V")},
            ],
            "channel_roles": ROLES2,
            "outer_parameter": "vgs",
            "drain_terminal": "drain",
            "ron_window": {"low": 0.0, "high": 0.1, "unit": "V"},
            "criteria_source": SOURCE,
        },
        "D_flow_qualify_cv_dataset": {
            "evidence": {"source": "cmu", "c_flow_envelope": c_flows.C_flow_sweep_cmu_cv()},
            "channel_roles": [{"channel": 7, "terminal": "gate"}],
            "imp_model": "Cp-G",
            "sweep_kind": "voltage",
        },
        "D_flow_qualify_timeseries_dataset": {
            "evidence": {
                "source": "wgfmu",
                "c_flow_envelope": c_flows.C_flow_waveform_wgfmu_acquire(
                    {"channels": [WAVEFORM_CHANNEL]}
                ),
            },
            "channel_roles": [{"channel": 502, "terminal": "drain"}],
            "measure_mode": "current",
            "event_plan": EVENTS,
        },
    }


def _run(name: str, request: dict) -> dict:
    return getattr(df, name)(request)


@pytest.fixture(scope="module")
def results() -> dict[str, dict]:
    requests = _requests()
    return {name: _run(name, requests[name]) for name in D_NAMES}


def _walk(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield path, key, item
            yield from _walk(item, (*path, key))
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, path)


def _strip(value):
    """Drop wall-clock fields for determinism comparisons."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in {"timestamp", "computed_at"}}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _patch_output(monkeypatch, atom: str, **changes):
    """Wrap a D atom so its (otherwise real) result carries injected labels or markers."""
    original = getattr(d_atoms, atom)

    def patched(**kwargs):
        result = original(**kwargs)
        for key, value in changes.items():
            if key.startswith("outputs."):
                result["outputs"][key.split(".", 1)[1]] = value
            else:
                result[key] = value
        return result

    monkeypatch.setattr(d_atoms, atom, patched)


def _spy_atoms(monkeypatch) -> list[str]:
    calls: list[str] = []
    for function in d_atoms.D_ATOM_FUNCTIONS:
        name = function.__name__

        def spy(*args, _name=name, _original=function, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(d_atoms, name, spy)
    return calls


# ---------------------------------------------------------------------------
# Catalog, naming, registration and docs
# ---------------------------------------------------------------------------


def test_catalog_has_seven_registered_flows_and_reserved_names_absent():
    names = [f.__name__ for f in df.D_FLOW_FUNCTIONS]
    assert names == D_NAMES
    assert tuple(RESERVED) == df.RESERVED_D_FLOWS
    for name in RESERVED:
        assert not hasattr(df, name)
    rows = {row["flow"]: row for row in df.d_flow_catalog()}
    assert set(rows) == set(D_NAMES)
    pattern = re.compile(r"^D_flow_(qualify|screen|analyze|archive)_(iv|cv|timeseries|run)_[a-z]+$")
    matrix = {
        ("qualify", "iv", "dataset"),
        ("qualify", "cv", "dataset"),
        ("qualify", "timeseries", "dataset"),
        ("screen", "iv", "leakage"),
        ("analyze", "iv", "transfer"),
        ("analyze", "iv", "output"),
        ("archive", "run", "bundle"),
    }
    assert {(r["category"], r["domain"], r["subject"]) for r in rows.values()} == matrix
    for name, row in rows.items():
        assert pattern.match(name)
        assert name == f"D_flow_{row['category']}_{row['domain']}_{row['subject']}"
    priorities = [rows[name]["priority"] for name in D_NAMES]
    assert priorities.count("P0") == 3 and priorities.count("P1") == 1
    assert priorities.count("P2") == 3


def test_response_names_carry_category_domain_subject(results):
    for name, result in results.items():
        row = next(r for r in df.d_flow_catalog() if r["flow"] == name)
        assert result["flow"] == name and result["flow_class"] == "D"
        assert (result["category"], result["domain"], result["subject"]) == (
            row["category"],
            row["domain"],
            row["subject"],
        )


def test_module_imports_only_d_atoms_and_schemas():
    code = (
        "import sys, json; import b1500_test_agent.mcp.d_flows; "
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('b1500'))))"
    )
    loaded = json.loads(
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
        ).stdout
    )
    forbidden = (
        "a_atoms", "b_atoms", "c_atoms", "a_flows", "b_flows", "c_flows", "ab_flows", "cd_flows",
    )  # fmt: skip
    assert not [m for m in loaded if m.rsplit(".", 1)[-1] in forbidden]
    assert not [m for m in loaded if m.startswith("b1500_test_agent.instruments")]


def test_mcp_discovery_counts_and_legacy_registration():
    from b1500_test_agent.mcp import cd_flows
    from b1500_test_agent.mcp.server import capabilities, mcp

    requests = json.loads(json.dumps(_requests()))

    async def exercise():
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            caps = capabilities()
            assert caps["D_flows"] == D_NAMES
            assert caps["CD_flows"] == [f.__name__ for f in cd_flows.CD_FLOW_FUNCTIONS]
            legacy = {
                "A_atoms": a_atoms.A_ATOM_FUNCTIONS,
                "B_atoms": b_atoms.B_ATOM_FUNCTIONS,
                "C_atoms": c_atoms.C_ATOM_FUNCTIONS,
                "D_atoms": d_atoms.D_ATOM_FUNCTIONS,
                "A_flows": a_flows.A_FLOW_FUNCTIONS,
                "B_flows": b_flows.B_FLOW_FUNCTIONS,
                "C_flows": c_flows.C_FLOW_FUNCTIONS,
                "AB_flows": ab_flows.AB_FLOW_FUNCTIONS,
            }
            counts = {"A_atoms": 82, "B_atoms": 59, "C_atoms": 99, "D_atoms": 42}
            counts |= {"A_flows": 20, "B_flows": 16, "C_flows": 31, "AB_flows": 19}
            for family, functions in legacy.items():
                assert caps[family] == [f.__name__ for f in functions]
                assert len(caps[family]) == counts[family]
            assert len(tools) == sum(counts.values()) + 7 + 4 == 379
            for name in RESERVED:
                assert name not in tools
            for name in D_NAMES:
                input_schema = tools[name].input_schema
                assert input_schema["required"] == ["request"]
                result = await client.call_tool(name, {"request": requests[name]})
                assert not result.is_error
                payload = result.structured_content
                assert payload["ok"] and payload["analysis_state"] == "not_computed"
            rejected = await client.call_tool(
                "D_flow_screen_iv_leakage",
                {"request": {**requests["D_flow_screen_iv_leakage"], "leakage": {}}},
                raise_on_error=False,
            )
            assert rejected.is_error

    asyncio.run(exercise())


def test_reference_docs_list_every_flow_and_reserved_name():
    catalog = (DOCS / "mcp-tools/d-flows.md").read_text()
    for name in D_NAMES + RESERVED:
        assert f"`{name}`" in catalog
    assert "d-flows.md" in (DOCS / "mcp-tools/README.md").read_text()
    overview = (DOCS / "instrument-interaction-tools.md").read_text()
    assert "D_flow_<operation>_<domain>_<subject>" in overview
    assert "D_flow" in (ROOT / "README.md").read_text()


# ---------------------------------------------------------------------------
# Boundary and exact order
# ---------------------------------------------------------------------------


def test_flows_call_only_d_atoms_through_the_atom_module(monkeypatch):
    requests = _requests()

    def forbidden(*args, **kwargs):
        raise AssertionError("D flows must not call A/B/C tools or other flows")

    for module in (a_atoms, b_atoms, c_atoms, a_flows, b_flows, c_flows, ab_flows):
        for attr in dir(module):
            if (attr[:2] in {"A_", "B_", "C_"} or attr.startswith("AB_")) and callable(
                getattr(module, attr)
            ):
                monkeypatch.setattr(module, attr, forbidden)
    originals = {name: getattr(df, name) for name in D_NAMES}
    for name in D_NAMES:
        monkeypatch.setattr(df, name, forbidden)
    calls = _spy_atoms(monkeypatch)
    for name in D_NAMES:
        calls.clear()
        result = originals[name](requests[name])
        assert result["ok"], result.get("error")
        assert calls == result["atoms_called"]
        assert all(atom.startswith("D_atom_") for atom in calls)


def _variants() -> list[tuple[str, str, dict, list]]:
    requests = _requests()
    qualify = requests["D_flow_qualify_iv_dataset"]
    expectation = df.product(
        d_atoms.D_atom_ingest_request_build_expectation(
            acquisition_kind="sweep_smu_staircase",
            c_request=qualify["evidence"]["c_flow_envelope"]["inputs"],
        )
    )
    expect_atom = "D_atom_ingest_request_build_expectation"
    supplied = [(expect_atom, "expectation_supplied"), *Q_IV_RECORDS[1:]]
    with_tracking = [*Q_IV[:6], TRACKING, *Q_IV[6:]]
    transfer_vth = {**requests["D_flow_analyze_iv_transfer"], "transfer": TRANSFER_VTH}
    split = "D_atom_shape_dataset_split_segments"
    transfer_atoms = [
        "D_atom_extract_transfer_gm_max",
        "D_atom_extract_transfer_vth",
        "D_atom_extract_transfer_ss",
        "D_atom_extract_transfer_on_off",
        "D_atom_extract_transfer_voltage_shift",
    ]
    vth_only = [(split, "not_requested")] + [
        atom if atom.endswith("_vth") else (atom, "not_requested") for atom in transfer_atoms
    ]
    table = "D_atom_render_dataset_build_table"
    archive = requests["D_flow_archive_run_bundle"]
    screened = _run("D_flow_screen_iv_leakage", requests["D_flow_screen_iv_leakage"])
    return [
        ("qualify", "D_flow_qualify_iv_dataset", qualify, Q_IV_RECORDS),
        (
            "qualify_supplied",
            "D_flow_qualify_iv_dataset",
            {**qualify, "expectation": expectation},
            supplied,
        ),
        (
            "qualify_tracking",
            "D_flow_qualify_iv_dataset",
            {**qualify, "source_tracking_tolerance": _q(0.01, "V")},
            with_tracking,
        ),
        (
            "screen",
            "D_flow_screen_iv_leakage",
            requests["D_flow_screen_iv_leakage"],
            [*Q_IV_RECORDS, "D_atom_extract_leakage_current", "D_atom_assess_value_check_limits"],
        ),
        (
            "transfer_all",
            "D_flow_analyze_iv_transfer",
            requests["D_flow_analyze_iv_transfer"],
            [*Q_IV_RECORDS, split, *transfer_atoms],
        ),
        ("transfer_vth", "D_flow_analyze_iv_transfer", transfer_vth, [*Q_IV_RECORDS, *vth_only]),
        (
            "output",
            "D_flow_analyze_iv_output",
            requests["D_flow_analyze_iv_output"],
            [
                *Q_IV_RECORDS,
                *Q_IV_RECORDS,
                "D_atom_shape_dataset_stack_family",
                "D_atom_extract_output_ron",
            ],
        ),
        (
            "cv",
            "D_flow_qualify_cv_dataset",
            requests["D_flow_qualify_cv_dataset"],
            [
                expect_atom,
                "D_atom_ingest_cmu_build_dataset",
                "D_atom_qualify_dataset_classify_status",
                "D_atom_qualify_dataset_check_completeness",
                "D_atom_qualify_cv_check_correction",
                "D_atom_qualify_run_check_context",
                "D_atom_qualify_dataset_grade_trust",
            ],
        ),
        (
            "timeseries",
            "D_flow_qualify_timeseries_dataset",
            requests["D_flow_qualify_timeseries_dataset"],
            [
                expect_atom,
                "D_atom_ingest_wgfmu_build_series",
                "D_atom_qualify_dataset_check_completeness",
                "D_atom_qualify_timeseries_check_events",
                "D_atom_qualify_run_check_context",
                "D_atom_qualify_dataset_grade_trust",
            ],
        ),
        (
            "archive",
            "D_flow_archive_run_bundle",
            archive,
            [
                "D_atom_archive_run_build_manifest",
                (table, "not_requested"),
                "D_atom_archive_run_write_bundle",
            ],
        ),
        (
            "archive_table",
            "D_flow_archive_run_bundle",
            {**archive, "envelopes": [archive["envelopes"][0], screened], "include_table": True},
            ["D_atom_archive_run_build_manifest", table, "D_atom_archive_run_write_bundle"],
        ),
    ]


@pytest.mark.parametrize("label,name,request_,expected", _variants(), ids=lambda v: str(v)[:20])
def test_exact_ordered_atoms_with_optional_skips(label, name, request_, expected):
    result = _run(name, request_)
    records = result["atom_results"]
    assert [r["atom"] for r in records] == [e if isinstance(e, str) else e[0] for e in expected]
    called = [e for e in expected if isinstance(e, str)]
    assert result["atoms_called"] == called
    for record, entry in zip(records, expected, strict=True):
        if isinstance(entry, tuple):
            assert record["status"] == "skipped" and record["optional"] is True
            assert record["reason"] == entry[1] and record["result"] is None
        else:
            assert record["status"] == "ok" and record["optional"] is False
            assert record["result"]["atom"] == entry
        assert record["phase"] == d_atoms._SPECS[record["atom"]].stage
    assert result["ok"] and not result["partial"], (label, result.get("error"))


# ---------------------------------------------------------------------------
# Stub chaining (DG1 placeholders end to end)
# ---------------------------------------------------------------------------


def test_stub_chaining_end_to_end_with_deterministic_products(results):
    again = {name: _run(name, request) for name, request in _requests().items()}
    for name, result in results.items():
        assert result["ok"] and not result["partial"], name
        assert result["analysis_state"] == "not_computed"
        assert result["analysis_completed"] is False
        assert result["fake"] is True and result["hardware_touched"] is False
        assert result["deterministic"] and not result["destructive"] and not result["consumptive"]
        for record in result["atom_results"]:
            if record["status"] == "ok":
                assert record["result"]["analysis_state"] == "not_computed"
        products = result["outputs"]["products"]
        assert products == again[name]["outputs"]["products"], name
        for ref in products.values():
            ds.ProductRef.model_validate(ref)
            assert ref["content"] is None and ref["ref_kind"] == "placeholder"
    screen = results["D_flow_screen_iv_leakage"]["outputs"]["products"]
    assert screen["dataset"]["upstream"] == [screen["expectation"]["product_id"]]
    assert screen["trust_summary"]["upstream"][0] == screen["dataset"]["product_id"]
    assert screen["leakage"]["upstream"] == [
        screen["dataset"]["product_id"],
        screen["trust_summary"]["product_id"],
    ]
    assert screen["verdict"]["upstream"] == [screen["leakage"]["product_id"]]
    transfer = results["D_flow_analyze_iv_transfer"]["outputs"]
    assert set(transfer["products"]) == {
        "expectation", "dataset", "trust_summary", "segments",
        "gm_max", "vth", "ss", "on_off", "voltage_shift",
    }  # fmt: skip
    assert (
        transfer["products"]["voltage_shift"]["upstream"][0]
        == (transfer["products"]["segments"]["product_id"])
    )
    assert transfer["selected_parameters"] == ["gm_max", "vth", "ss", "on_off", "voltage_shift"]
    output = results["D_flow_analyze_iv_output"]["outputs"]["products"]
    assert output["ron"]["upstream"] == [output["family"]["product_id"]]
    members = [r for r in results["D_flow_analyze_iv_output"]["atom_results"] if "member" in r]
    assert {r["member"] for r in members} == {0, 1}


def test_supplied_expectation_is_used_not_rebuilt():
    request = _requests()["D_flow_qualify_iv_dataset"]
    supplied = df.product(
        d_atoms.D_atom_ingest_request_build_expectation(
            acquisition_kind="sweep_smu_staircase",
            c_request=request["evidence"]["c_flow_envelope"]["inputs"],
        )
    )
    result = _run("D_flow_qualify_iv_dataset", {**request, "expectation": supplied})
    assert result["outputs"]["products"]["expectation"] == supplied
    assert result["outputs"]["products"]["dataset"]["upstream"] == [supplied["product_id"]]
    assert supplied["product_id"] in result["provenance"]["upstream"]


# ---------------------------------------------------------------------------
# Wiring, failures and audit retention
# ---------------------------------------------------------------------------


def _assert_stopped_at(result: dict, atom: str, error_type: str, reason: str = "earlier_failure"):
    records = result["atom_results"]
    index = next(i for i, r in enumerate(records) if r["atom"] == atom and r["status"] == "error")
    assert result["ok"] is False and result["partial"] is True
    assert result["analysis_state"] == "rejected_input"
    assert result["error"]["type"] == error_type and result["error"]["at"] == atom
    assert records[index]["error"]["type"] == error_type
    for record in records[:index]:
        assert record["status"] in {"ok", "skipped"} and record["timestamp"]
        if record["status"] == "ok":
            assert record["result"]["ok"] is True
    later = records[index + 1 :]
    assert all(r["status"] == "skipped" for r in later)
    assert all(r["reason"] in {reason, "not_requested"} for r in later)
    assert all(r["optional"] is False for r in later if r["reason"] == reason)
    assert result["atoms_called"][-1] == atom
    assert result["cleanup"] == {"owner": "none", "performed": False}
    json.dumps(result, allow_nan=False)
    return index


def test_miswired_product_type_is_rejected_at_the_next_step(monkeypatch):
    original = d_atoms.D_atom_ingest_smu_build_dataset

    def wrong_type(**kwargs):
        result = original(**kwargs)
        result["outputs"]["product"]["product_type"] = "trust_summary"
        return result

    monkeypatch.setattr(d_atoms, "D_atom_ingest_smu_build_dataset", wrong_type)
    result = _run("D_flow_screen_iv_leakage", _requests()["D_flow_screen_iv_leakage"])
    index = _assert_stopped_at(result, "D_atom_qualify_dataset_classify_status", "rejected_input")
    record = result["atom_results"][index]
    assert record["result"]["ok"] is False and "R3" in record["result"]["error"]["message"]
    assert result["outputs"]["verdict"] is None and result["outputs"]["trust_level"] is None


@pytest.mark.parametrize("returned", ["exception", "non_dict"])
def test_child_exception_or_non_dict_keeps_audit_and_skips_later(monkeypatch, returned):
    def broken(**kwargs):
        if returned == "exception":
            raise RuntimeError("injected atom failure")
        return "not a dict"

    monkeypatch.setattr(d_atoms, "D_atom_qualify_iv_check_compliance", broken)
    result = _run("D_flow_qualify_iv_dataset", _requests()["D_flow_qualify_iv_dataset"])
    index = _assert_stopped_at(result, "D_atom_qualify_iv_check_compliance", "internal_error")
    record = result["atom_results"][index]
    assert record["result"] is None
    if returned == "exception":
        assert "RuntimeError" in record["error"]["message"]


def test_child_error_type_is_propagated(monkeypatch):
    original = d_atoms.D_atom_extract_leakage_current
    monkeypatch.setattr(
        d_atoms,
        "D_atom_extract_leakage_current",
        lambda **kwargs: original(**{**kwargs, "terminal": None}),
    )
    result = _run("D_flow_screen_iv_leakage", _requests()["D_flow_screen_iv_leakage"])
    _assert_stopped_at(result, "D_atom_extract_leakage_current", "context_missing")


# ---------------------------------------------------------------------------
# Taint and labels
# ---------------------------------------------------------------------------


def test_synthetic_labels_and_no_pass_anywhere(results):
    for name, result in results.items():
        assert result["data_origin"] == "synthetic" and result["synthetic"] is True
        assert not FORBIDDEN & {value for _, value in df.labels(result)}, name
        for _, key, value in _walk(result):
            if key in {"verdict", "trust_level", "check_outcome"}:
                assert not (isinstance(value, str) and value in FORBIDDEN), (name, key)
        if result["category"] != "archive":
            assert result["outputs"]["trust_level"] == "synthetic_only", name
        assert all(c["check_outcome"] is None for c in result["outputs"]["check_outcomes"])
    screen = results["D_flow_screen_iv_leakage"]["outputs"]
    assert screen["verdict"] == "synthetic_only" and screen["verdict_scope"] is None
    assert screen["results"] == []
    assert screen["criteria_echo"] == {"criteria": [
        {**CRITERIA[0], "limit": {**CRITERIA[0]["limit"], "bound": "exact"}, "limit_high": None}
    ], "criteria_source": {**SOURCE, "sha256": None}}  # fmt: skip
    assert screen["evidence_citation"] == {
        "eligible": False,
        "blockers": ["synthetic_origin", "analysis_not_computed", "manifest_absent"],
        "external_requirements": [df.HUMAN_APPROVAL],
    }
    assert results["D_flow_qualify_iv_dataset"]["outputs"]["verdict"] is None


@pytest.mark.parametrize(
    "atom,changes,flow",
    [
        ("D_atom_assess_value_check_limits", {"outputs.verdict": "pass"}, "D_flow_screen_iv_leakage"),
        ("D_atom_assess_value_check_limits", {"outputs.verdict": "fail"}, "D_flow_screen_iv_leakage"),
        ("D_atom_qualify_dataset_grade_trust", {"outputs.trust_level": "trusted"}, "D_flow_screen_iv_leakage"),
        (
            "D_atom_qualify_dataset_grade_trust",
            {"outputs.trust_level": "trusted_with_flags"},
            "D_flow_qualify_cv_dataset",
        ),
        ("D_atom_qualify_dataset_classify_status", {"outputs.check_outcome": "pass"}, "D_flow_qualify_iv_dataset"),
        ("D_atom_ingest_smu_build_dataset", {"data_origin": "instrument", "synthetic": False}, "D_flow_analyze_iv_transfer"),
        ("D_atom_archive_run_build_manifest", {"data_origin": "fixture", "synthetic": False}, "D_flow_archive_run_bundle"),
    ],
)  # fmt: skip
def test_injected_pass_trusted_or_raised_origin_is_a_taint_violation(
    monkeypatch, atom, changes, flow
):
    _patch_output(monkeypatch, atom, **changes)
    result = _run(flow, _requests()[flow])
    index = _assert_stopped_at(result, atom, "taint_violation", reason="taint_violation")
    record = result["atom_results"][index]
    assert record["result"]["ok"] is True  # the child payload is retained unchanged
    outputs = result["outputs"]
    assert outputs["verdict"] is None
    assert outputs["trust_level"] in (None, "synthetic_only")
    assert outputs["trust_level"] is None or atom != "D_atom_qualify_dataset_grade_trust"
    assert result["data_origin"] == "synthetic"
    assert any(f["code"] == "taint_violation" for f in result["findings"])


@pytest.mark.parametrize(
    "changes,flag",
    [
        ({"fake": False}, "fake"),
        ({"hardware_touched": True}, "hardware_touched"),
        ({"fake": None}, "fake"),
    ],
)
def test_unexpected_marker_stops_the_flow(monkeypatch, changes, flag):
    _patch_output(monkeypatch, "D_atom_qualify_dataset_check_completeness", **changes)
    result = _run("D_flow_qualify_iv_dataset", _requests()["D_flow_qualify_iv_dataset"])
    _assert_stopped_at(result, "D_atom_qualify_dataset_check_completeness", "unexpected_marker")
    if flag == "fake":
        assert result["fake"] is False
    else:
        assert result["hardware_touched"] is True


@pytest.mark.parametrize("role_channel", [101, 1])
def test_any_c_channel_number_runs_end_to_end_without_mid_chain_rejection(role_channel):
    """Table 4-1 subchannel numbers (101-1002) are valid C channels; D must accept them.

    With a role on channel 1 the pin map is incomplete, but that is data, not a child
    validation failure after earlier atoms already ran.
    """
    envelope = _sweep(channel=101)
    roles = [{"channel": role_channel, "terminal": "gate"}]
    result = _run("D_flow_qualify_iv_dataset", {"evidence": _iv(envelope), "channel_roles": roles})
    assert result["ok"] is True and result["partial"] is False, result.get("error")
    compliance = next(
        r for r in result["atom_results"] if r["atom"] == "D_atom_qualify_iv_check_compliance"
    )
    assert compliance["inputs"]["compliance"][0]["channel"] == 101
    gaps = [f for f in result["findings"] if f["code"] == "pin_map_incomplete"]
    assert [f["channels"] for f in gaps] == ([[101]] if role_channel == 1 else [])


def test_declared_origin_never_raises_evidence():
    request = _requests()["D_flow_qualify_iv_dataset"]
    with pytest.raises(ValidationError, match="exceeds the evidence origin"):
        _run(
            "D_flow_qualify_iv_dataset",
            {**request, "evidence": {**request["evidence"], "declared_origin": "instrument"}},
        )
    lowered = _run(
        "D_flow_qualify_iv_dataset",
        {**request, "evidence": {**request["evidence"], "declared_origin": "synthetic"}},
    )
    assert lowered["ok"] and lowered["data_origin"] == "synthetic"


def test_upstream_ab_evidence_is_unverified_and_never_lifts_trust():
    request = _requests()["D_flow_screen_iv_leakage"]
    claims = [
        {"flow": "B_flow_preflight_b1500_gate", "fake": False, "ok": True},
        {"flow": "A_flow_drain_flex_errors", "fake": False, "data_origin": "instrument"},
    ]
    result = _run(
        "D_flow_screen_iv_leakage",
        {**request, "evidence": {**request["evidence"], "upstream_evidence": claims}},
    )
    assert result["ok"] and result["data_origin"] == "synthetic"
    assert result["outputs"]["trust_level"] == "synthetic_only"
    assert result["outputs"]["verdict"] == "synthetic_only"
    codes = {(f["source_atom"], f["code"]) for f in result["findings"]}
    assert ("D_atom_qualify_run_check_context", "evidence_unverified") in codes
    assert result["inputs"]["evidence"]["upstream_evidence"] == [c["flow"] for c in claims]


def test_evidence_origin_mirrors_the_atom_rule():
    envelopes = [
        {"fake": True},
        {"fake": False},
        {"fake": False, "data_origin": "fixture"},
        {"fake": False, "outputs": {"synthetic": True}},
        {"synthetic": True},
        {},
        {"fake": False, "data_origin": "instrument"},
        {"data_origin": "instrument"},
    ]
    for envelope in envelopes:
        assert schema.evidence_origin(envelope) == d_atoms._envelope_origin(envelope), envelope


# ---------------------------------------------------------------------------
# ok vs data outcomes (data never sets ok:false)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "atom,changes",
    [
        ("D_atom_extract_leakage_current", {"analysis_state": "not_extractable"}),
        ("D_atom_assess_value_check_limits", {"analysis_state": "inconclusive"}),
        ("D_atom_qualify_dataset_grade_trust", {"outputs.trust_level": "untrusted"}),
        ("D_atom_assess_value_check_limits", {"outputs.verdict": "inconclusive"}),
        ("D_atom_qualify_iv_check_compliance", {"passed": False, "status": "failed"}),
        ("D_atom_qualify_dataset_classify_status", {"result_code": -1, "outcome": "bad"}),
    ],
)
def test_data_outcomes_and_c_style_failure_keys_keep_ok_true(monkeypatch, atom, changes):
    _patch_output(monkeypatch, atom, **changes)
    result = _run("D_flow_screen_iv_leakage", _requests()["D_flow_screen_iv_leakage"])
    assert result["ok"] is True and result["partial"] is False and "error" not in result
    assert result["analysis_state"] == "not_computed"


def test_fail_verdict_on_instrument_origin_is_data_not_an_error(monkeypatch):
    envelope = _sweep()
    envelope["fake"] = False
    envelope["outputs"]["synthetic"] = False
    _patch_output(monkeypatch, "D_atom_assess_value_check_limits", **{"outputs.verdict": "fail"})
    request = {**_requests()["D_flow_screen_iv_leakage"], "evidence": _iv(envelope)}
    result = _run("D_flow_screen_iv_leakage", request)
    assert result["ok"] is True and result["data_origin"] == "instrument"
    assert result["outputs"]["verdict"] == "fail"
    assert result["outputs"]["trust_level"] is None  # stubs grade nothing off synthetic data
    assert result["outputs"]["evidence_citation"]["blockers"] == [
        "analysis_not_computed",
        "manifest_absent",
    ]


# ---------------------------------------------------------------------------
# Request validation before any atom call (U4, handoff, units)
# ---------------------------------------------------------------------------


def _with(base: dict, path: str, value) -> dict:
    """Copy ``base`` and set (or delete, for ...) one dotted path."""
    result = copy.deepcopy(base)
    node = result
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = int(keys[-1]) if isinstance(node, list) else keys[-1]
    if value is ...:
        del node[last]
    else:
        node[last] = value
    return result


def _state(envelope: dict, **changes) -> dict:
    return {**envelope, **changes}


def _no_read(envelope: dict) -> dict:
    changed = copy.deepcopy(envelope)
    changed["atom_results"][-1]["status"] = "skipped"
    return changed


def _invalid_cases():
    r = _requests()
    screen, transfer = r["D_flow_screen_iv_leakage"], r["D_flow_analyze_iv_transfer"]
    qualify, output = r["D_flow_qualify_iv_dataset"], r["D_flow_analyze_iv_output"]
    cv, ts, archive = (
        r["D_flow_qualify_cv_dataset"],
        r["D_flow_qualify_timeseries_dataset"],
        r["D_flow_archive_run_bundle"],
    )
    sweep = qualify["evidence"]["c_flow_envelope"]
    s, t, q = "D_flow_screen_iv_leakage", "D_flow_analyze_iv_transfer", "D_flow_qualify_iv_dataset"
    two_channels = c_flows.C_flow_waveform_wgfmu_acquire(
        {"channels": [WAVEFORM_CHANNEL, {**WAVEFORM_CHANNEL, "channel_id": 501, "pattern": "b"}]}
    )
    return [
        (s, _with(screen, "leakage.criteria", ...), "criteria"),
        (s, _with(screen, "leakage.criteria", []), "criteria"),
        (s, _with(screen, "leakage.criteria_source", ...), "criteria_source"),
        (s, _with(screen, "leakage.criteria.0.limit.unit", "V"), "unit 'V'"),
        (s, _with(screen, "leakage.criteria.0.parameter", "vth"), "leakage parameter"),
        (s, _with(screen, "leakage.bias_points_v", []), "bias_points_v, window_v"),
        (s, _with(screen, "leakage.bias_points_v", [6.0]), "not within"),
        (s, _with(screen, "leakage.window_v", [-1.0, 2.0]), "not inside the sweep"),
        (s, _with(screen, "leakage.window_v", [2.0, 1.0]), "low < high"),
        (s, _with(screen, "leakage.terminal", "drain"), "not a declared channel role"),
        (s, _with(screen, "leakage.criteria", [{**CRITERIA[0], "limit": _q(1e-3, "A")}]), "CD11"),
        (s, _with(screen, "leakage.criteria", [{"parameter": "leakage_current", "comparator": "within", "limit": _q(1e-12, "A"), "limit_high": _q(2e-3, "A")}]), "CD11"),
        (s, _with(screen, "channel_roles", [*GATE, {"channel": 2, "terminal": "gate"}]), "exactly one channel"),
        (s, _with(screen, "channel_roles", [{"channel": 2, "terminal": "gate"}]), "does not measure"),
        (
            s,
            _with(screen, "evidence.c_flow_envelope", _sweep(source="current", stop=1e-6)),
            "voltage-sourced",
        ),
        (
            s,
            _with(screen, "evidence.c_flow_envelope", c_flows.C_flow_spot_smu_iv({"level": 1.0})),
            "spot level",
        ),
        (t, _with(transfer, "transfer.derivative", ...), "derivative"),
        (t, _with(transfer, "transfer.vth", ...), "Vth method"),
        (t, _with(transfer, "transfer.vth", {"method": "linear_extrapolation"}), "constant_current"),
        (t, _with(transfer, "transfer.vth", {"method": "constant_current"}), "requires icc"),
        (
            t,
            _with(
                _with(transfer, "transfer.vth", {"method": "max_gm_linear_extrapolation"}),
                "transfer.derivative",
                ...,
            ),
            "derivative",
        ),
        (t, _with(transfer, "transfer.segments", ...), "segments and shift_at_current"),
        (t, _with(transfer, "transfer.shift_at_current", ...), "segments and shift_at_current"),
        (t, _with(transfer, "transfer.vds", _q(0.05, "A")), "vds has unit"),
        (t, _with(transfer, "transfer.ss.current_window.unit", "V"), "current_window has unit"),
        (t, _with(transfer, "transfer.parameters", ["vth", "vth"]), "unique"),
        (t, _with(transfer, "transfer.parameters", []), "parameters"),
        (t, _with(transfer, "transfer.parameters", ["vth", "gm_max"]), "unselected parameter"),
        (t, _with(transfer, "transfer.on_off.vg_on", _q(7.0, "V")), "outside the sweep"),
        (t, _with(transfer, "transfer.drain_terminal", "source"), "not a declared channel role"),
        (t, _with(transfer, "transfer.criteria_source", ...), "criteria_source"),
        (
            t,
            _with(transfer, "evidence.c_flow_envelope", c_flows.C_flow_spot_smu_iv()),
            "swept C request",
        ),
        (q, _with(qualify, "channel_roles", ...), "channel_roles"),
        (q, _with(qualify, "channel_roles", []), "channel_roles"),
        (q, _with(qualify, "channel_roles", GATE * 2), "each channel once"),
        (q, _with(qualify, "source_tracking_tolerance", _q(1.0, "Ohm")), "tolerance has unit"),
        (q, _with(qualify, "evidence.c_flow_envelope", _state(sweep, execution_state="awaiting_completion")), "pending"),
        (q, _with(qualify, "evidence.c_flow_envelope", _state(sweep, execution_state="configuration_only")), "configuration_only"),
        (q, _with(qualify, "evidence.c_flow_envelope", _state(sweep, ok=False, execution_state="failed")), "c_failed"),
        (q, _with(qualify, "evidence.c_flow_envelope", _no_read(sweep)), "c_no_data_record"),
        (q, _with(qualify, "evidence.c_flow_envelope", c_flows.C_flow_spot_cmu_impedance()), "not an admitted iv"),
        (q, _with(qualify, "evidence.c_flow_envelope", c_flows.C_flow_sweep_smu_qscv()), "not an admitted iv"),
        (q, _with(qualify, "evidence.c_flow_envelope", c_flows.C_flow_spot_smu_high_speed()), "not an admitted iv"),
        (q, _with(qualify, "evidence.c_flow_envelope", a_flows.A_flow_snapshot_flex_status()), "C flow envelope"),
        (q, _with(qualify, "evidence.source", "cmu"), "source"),
        (q, _with(qualify, "evidence.declared_origin", "fixture"), "exceeds the evidence origin"),
        (q, _with(qualify, "evidence.upstream_evidence", [{"flow": "A_flow_x"}] * 17), "upstream_evidence"),
        (q, _with(qualify, "raw_command", "XE"), "raw_command"),
        (q, _with(qualify, "measurement", {}), "measurement"),
        (q, _with(qualify, "trust_policy", {"near_compliance_ratio": 1.5}), "near_compliance_ratio"),
        ("D_flow_qualify_cv_dataset", _with(cv, "imp_model", "Cs-Rs"), "imp_model"),
        ("D_flow_qualify_cv_dataset", _with(cv, "imp_model", "C-G"), "imp_model"),
        ("D_flow_qualify_cv_dataset", _with(cv, "sweep_kind", "frequency"), "sweep_kind"),
        ("D_flow_qualify_timeseries_dataset", _with(ts, "evidence.c_flow_envelope", two_channels), "ambiguous"),
        ("D_flow_qualify_timeseries_dataset", _with(ts, "event_plan", []), "event_plan"),
        ("D_flow_qualify_timeseries_dataset", _with(ts, "measure_mode", ...), "measure_mode"),
        ("D_flow_analyze_iv_output", _with(output, "members", output["members"][:1]), "members"),
        ("D_flow_analyze_iv_output", _with(output, "members.1.outer_value.unit", "A"), "outer_value units"),
        ("D_flow_analyze_iv_output", _with(output, "members.1.outer_value.value", 1.0), "distinct"),
        ("D_flow_analyze_iv_output", _with(output, "ron_window.unit", "A"), "ron_window has unit"),
        ("D_flow_analyze_iv_output", _with(output, "outer_parameter", ...), "outer_parameter"),
        ("D_flow_analyze_iv_output", _with(output, "criteria_source", ...), "criteria_source"),
        ("D_flow_archive_run_bundle", _with(archive, "envelopes", []), "envelopes"),
        ("D_flow_archive_run_bundle", _with(archive, "envelopes", archive["envelopes"] * (schema.MAX_ARCHIVE_ENVELOPES + 1)), "envelopes"),
        ("D_flow_archive_run_bundle", _with(archive, "envelopes", [{"fake": True}]), "names no tool"),
        ("D_flow_archive_run_bundle", _with(archive, "intent", ""), "intent"),
        ("D_flow_archive_run_bundle", _with(archive, "data_root", "/tmp"), "data_root"),
    ]  # fmt: skip


@pytest.mark.parametrize("name,request_,match", _invalid_cases(), ids=lambda v: str(v)[:40])
def test_invalid_requests_fail_before_any_atom_call(monkeypatch, name, request_, match):
    calls = _spy_atoms(monkeypatch)
    with pytest.raises(ValidationError, match=match):
        _run(name, request_)
    assert calls == []


def test_criteria_and_methods_have_no_repo_defaults():
    required = {
        schema.LeakageSpec: {"terminal", "criteria", "criteria_source"},
        schema.TransferSpec: {
            "gate_terminal", "drain_terminal", "polarity", "vds", "parameters", "criteria_source",
        },
        schema.SsSpec: {"current_window", "min_decades"},
        schema.OnOffSpec: {"vg_on", "vg_off"},
        schema.DAnalyzeIvOutput: {"ron_window", "criteria_source", "drain_terminal", "outer_parameter"},
        schema.DQualifyCv: {"imp_model", "sweep_kind"},
        schema.DQualifyTimeseries: {"measure_mode", "event_plan"},
    }  # fmt: skip
    for model, names in required.items():
        fields = model.model_fields
        assert {n for n in names if fields[n].is_required()} == names, model.__name__
    for name in ("derivative", "vth", "ss", "on_off", "segments", "shift_at_current"):
        assert schema.TransferSpec.model_fields[name].default is None
    for model in (*required, schema.DQualifyIv, schema.DScreenIvLeakage, schema.DArchiveRun):
        assert not set(model.model_fields) & ds.BANNED_RESULT_KEYS, model.__name__


# ---------------------------------------------------------------------------
# Archive (U2): planned paths only, nothing written
# ---------------------------------------------------------------------------


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()}


def test_no_flow_writes_a_file_and_archive_refuses(tmp_path, monkeypatch):
    requests = _requests()
    data_root = ROOT / "data"
    before_repo, before_tmp = _files(data_root), _files(tmp_path)
    monkeypatch.chdir(tmp_path)
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"D flow attempted a file write: {file}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    calls = _spy_atoms(monkeypatch)
    outcomes = {name: _run(name, requests[name]) for name in D_NAMES}
    table = _run(
        "D_flow_archive_run_bundle",
        {
            "envelopes": [
                requests["D_flow_archive_run_bundle"]["envelopes"][0],
                outcomes[D_NAMES[1]],
            ],
            "intent": "Archive with table.",
            "include_table": True,
            "created_at": "2026-11-17T00:00:00Z",
            "station": {"name": "example-station", "sha256": "0" * 64},
        },
    )
    monkeypatch.undo()
    assert _files(data_root) == before_repo and _files(tmp_path) == before_tmp
    assert "D_atom_archive_run_load_bundle" not in calls
    for result in [*outcomes.values(), table]:
        assert result["side_effects"] == {
            "hardware": "none",
            "filesystem_writes": [],
            "artifact_written": False,
        }
    for archived in (outcomes["D_flow_archive_run_bundle"], table):
        archive = archived["outputs"]["archive"]
        assert archive["artifact_written"] is False
        assert archive["write_refusal"] == ["fake_mode", "synthetic_origin"]
        assert archive["manifest_ref"]["product_type"] == "manifest"
        for path in archive["planned_paths"]:
            assert not path.startswith("/") and ".." not in path.split("/")
        assert archive["planned_paths"][0].endswith("/manifest.json")
    assert len(outcomes["D_flow_archive_run_bundle"]["outputs"]["archive"]["planned_paths"]) == 1
    paths = table["outputs"]["archive"]["planned_paths"]
    assert len(paths) == 2 and paths[1].endswith(".csv")
    manifest_upstream = table["outputs"]["archive"]["manifest_ref"]["upstream"]
    screen_products = outcomes[D_NAMES[1]]["outputs"]["products"]
    assert {ref["product_id"] for ref in screen_products.values()} <= set(manifest_upstream)


def test_archive_table_without_dataset_products_is_rejected_before_any_atom(monkeypatch):
    calls = _spy_atoms(monkeypatch)
    request = {**_requests()["D_flow_archive_run_bundle"], "include_table": True}
    with pytest.raises(ValidationError, match="include_table needs at least one dataset"):
        _run("D_flow_archive_run_bundle", request)
    assert calls == []  # previously build_manifest ran before the table step failed


def test_archive_cap_is_derived_and_every_envelope_reaches_the_manifest():
    assert schema.MAX_ARCHIVE_ENVELOPES == (
        schema.CD_ARCHIVED_C_FLOWS + schema.CD_ARCHIVED_D_CHILDREN + schema.MAX_UPSTREAM_EVIDENCE
    )
    sweep = _sweep()
    envelopes = [{**sweep, "n": i} for i in range(schema.MAX_ARCHIVE_ENVELOPES)]
    result = _run("D_flow_archive_run_bundle", {"envelopes": envelopes, "intent": "Cap."})
    assert result["ok"] and not result["partial"], result.get("error")
    manifest = result["atom_results"][0]
    assert manifest["atom"] == "D_atom_archive_run_build_manifest"
    assert len(manifest["inputs"]["envelopes"]) == schema.MAX_ARCHIVE_ENVELOPES
    assert len(manifest["result"]["provenance"]["input_fingerprints"]) == len(envelopes) + 1
    assert not any("manifest cap" in warning for warning in result["warnings"])


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_banned_keys_absent_and_json_safe(results):
    for name, result in results.items():
        json.dumps(result, allow_nan=False)
        assert not set(result) & ds.BANNED_RESULT_KEYS, name
        assert not set(result["inputs"]) & ds.BANNED_RESULT_KEYS, name
        for _, key, _ in _walk(result["outputs"]):
            assert key not in ds.BANNED_RESULT_KEYS, (name, key)
        for record in result["atom_results"]:
            for _, key, _ in _walk(record["inputs"]):
                assert key not in ds.BANNED_RESULT_KEYS, (name, key)
            if record["result"] is not None:
                for _, key, _ in _walk(record["result"]):
                    assert key not in ds.BANNED_RESULT_KEYS, (name, record["atom"], key)


def test_evidence_is_summarized_never_re_embedded(results):
    request = _requests()["D_flow_screen_iv_leakage"]
    envelope = request["evidence"]["c_flow_envelope"]
    result = _run("D_flow_screen_iv_leakage", request)
    text = json.dumps(result)
    for record in envelope["atom_results"]:
        assert record["timestamp"] not in text
    assert "C_atom_smu_configure_sweep_timing" not in text
    summary = result["inputs"]["evidence"]
    assert summary == {
        "source": "smu",
        "c_flow": "C_flow_sweep_smu_staircase",
        "execution_state": "simulated_complete",
        "handoff_state": "empty",
        "designated_record": 7,
        "element_count": 0,
        "upstream_evidence": [],
        "declared_origin": None,
    }
    assert df.EMPTY_DATA_WARNING in result["warnings"]


def test_response_size_is_independent_of_point_count():
    def sized(points: int) -> int:
        envelope = _sweep(steps=11)
        envelope["atom_results"][-1]["result"]["parameters"]["rows"] = [0.0] * points
        request = {**_requests()["D_flow_qualify_iv_dataset"], "evidence": _iv(envelope)}
        result = _run("D_flow_qualify_iv_dataset", request)
        assert result["ok"], result.get("error")
        assert result["inputs"]["evidence"]["handoff_state"] == "received"
        return len(json.dumps(_strip(result)))

    assert abs(sized(100_000) - sized(10)) < 64


def test_records_have_utc_timestamps_and_runs_are_identical_apart_from_time(results):
    for result in results.values():
        for record in result["atom_results"]:
            stamp = datetime.fromisoformat(record["timestamp"])
            assert stamp.utcoffset() == timedelta(0)
    requests = _requests()
    for name in D_NAMES:
        assert _strip(_run(name, requests[name])) == _strip(_run(name, requests[name])), name


# ---------------------------------------------------------------------------
# Review follow-ups 2026-11-17: held-bias leakage, role coverage
# ---------------------------------------------------------------------------

BIASED = {
    "channel": 1,
    "start": 0.0,
    "stop": 2.0,
    "bias_channels": [
        {"channel": 2, "level": 0.05, "compliance": 0.01},
        {"channel": 3, "level": 0.0, "compliance": 0.01},
    ],
    "measured_channels": [{"channel": 2}, {"channel": 1}],
}
ROLES3 = [*ROLES2, {"channel": 3, "terminal": "source"}]


def _biased_screen(c_request: dict | None = None, **leakage) -> dict:
    envelope = c_flows.C_flow_sweep_smu_staircase_biased(c_request or BIASED)
    spec = {
        "terminal": "drain",
        "bias_points_v": [0.05],
        "criteria": CRITERIA,
        "criteria_source": SOURCE,
        **leakage,
    }
    return {"evidence": _iv(envelope), "channel_roles": ROLES3, "leakage": spec}


@pytest.mark.parametrize(
    "leakage",
    [
        {},
        {"bias_points_v": [], "window_v": [0.0, 0.1]},
        {"criteria": [{**CRITERIA[0], "limit": _q(5e-3, "A")}]},  # below the drain's 10 mA
        {"terminal": "gate", "bias_points_v": [1.0], "window_v": [0.5, 1.5]},
    ],
    ids=["held_level", "window_contains_level", "drain_compliance", "swept_gate"],
)
def test_held_bias_leakage_is_evaluated_at_its_held_level(leakage):
    result = _run("D_flow_screen_iv_leakage", _biased_screen(**leakage))
    assert result["ok"] and not result["partial"], result.get("error")
    assert "D_atom_extract_leakage_current" in result["atoms_called"]


@pytest.mark.parametrize(
    "c_request,leakage,match",
    [
        # Inside the swept gate trajectory, but not the drain's held 0.05 V: no longer accepted.
        (None, {"bias_points_v": [1.0]}, "held bias level 0.05 V of channel 2"),
        (None, {"bias_points_v": [], "window_v": [0.5, 1.5]}, "does not contain the held bias"),
        (None, {"criteria": [{**CRITERIA[0], "limit": _q(0.02, "A")}]}, "compliance 0.01 A"),
        (
            None,
            {"terminal": "gate", "bias_points_v": [1.0], "criteria": [{**CRITERIA[0], "limit": _q(5e-3, "A")}]},
            "compliance 0.001 A",
        ),
        (None, {"terminal": "source", "bias_points_v": [0.0]}, "does not measure"),
        (
            {**BIASED, "bias_channels": [{"channel": 2, "source": "current", "level": 1e-6, "compliance": 1.0}, BIASED["bias_channels"][1]]},
            {"bias_points_v": [0.0]},
            "voltage-sourced",
        ),
    ],
    ids=["point_off_level", "window_off_level", "drain_cd11", "gate_cd11", "unmeasured", "current_bias"],
)  # fmt: skip
def test_held_bias_leakage_rejections_happen_before_any_atom(
    monkeypatch, c_request, leakage, match
):
    request = _biased_screen(c_request, **leakage)
    calls = _spy_atoms(monkeypatch)
    with pytest.raises(ValidationError, match=match):
        _run("D_flow_screen_iv_leakage", request)
    assert calls == []


def _role_gap_cases():
    r = _requests()
    output = copy.deepcopy(r["D_flow_analyze_iv_output"])
    output["members"][1]["evidence"] = _iv(_sweep(channel=3, stop=2.0))
    biased = {
        "evidence": _iv(c_flows.C_flow_sweep_smu_staircase_biased(BIASED)),
        "channel_roles": GATE,
    }
    return [
        ("D_flow_qualify_iv_dataset", {**r["D_flow_qualify_iv_dataset"], "channel_roles": [{"channel": 2, "terminal": "gate"}]}, [1], None),
        ("D_flow_qualify_iv_dataset", biased, [2], None),
        ("D_flow_screen_iv_leakage", {**_biased_screen(), "channel_roles": [ROLES2[1]], "leakage": {**LEAKAGE, "terminal": "drain", "bias_points_v": [0.05]}}, [1], None),
        ("D_flow_analyze_iv_output", output, [3], 1),
        ("D_flow_qualify_cv_dataset", {**r["D_flow_qualify_cv_dataset"], "channel_roles": [{"channel": 8, "terminal": "gate"}]}, [7], None),
        ("D_flow_qualify_timeseries_dataset", {**r["D_flow_qualify_timeseries_dataset"], "channel_roles": [{"channel": 5, "terminal": "drain"}]}, [502], None),
    ]  # fmt: skip


@pytest.mark.parametrize(
    "name,request_,unmapped,member", _role_gap_cases(), ids=lambda v: str(v)[:30]
)
def test_standalone_role_gap_is_a_finding_not_a_rejection(name, request_, unmapped, member):
    result = _run(name, request_)
    assert result["ok"] and not result["partial"], result.get("error")
    gaps = [f for f in result["findings"] if f["code"] == "pin_map_incomplete"]
    assert len(gaps) == 1, gaps
    gap = gaps[0]
    assert (gap["source_atom"], gap["check"], gap["severity"]) == (None, "pin_map", "warning")
    assert gap["channels"] == unmapped and gap["count"] == len(unmapped)
    assert gap.get("member") == member
    assert result["outputs"]["trust_level"] == "synthetic_only"  # already below the cap


def test_canonical_requests_have_complete_pin_maps(results):
    for name, result in results.items():
        assert not [f for f in result["findings"] if f["code"] == "pin_map_incomplete"], name


def test_role_gap_caps_a_graded_trust_level_and_never_invents_one(monkeypatch):
    envelope = _sweep()
    envelope["fake"] = False
    envelope["outputs"]["synthetic"] = False
    gap_roles = [{"channel": 2, "terminal": "gate"}]
    ungraded = _run(
        "D_flow_qualify_iv_dataset", {"evidence": _iv(envelope), "channel_roles": gap_roles}
    )
    assert ungraded["data_origin"] == "instrument" and ungraded["outputs"]["trust_level"] is None
    _patch_output(
        monkeypatch, "D_atom_qualify_dataset_grade_trust", **{"outputs.trust_level": "trusted"}
    )
    full = _run("D_flow_qualify_iv_dataset", {"evidence": _iv(envelope), "channel_roles": GATE})
    assert full["ok"] and full["outputs"]["trust_level"] == "trusted"
    capped = _run(
        "D_flow_qualify_iv_dataset", {"evidence": _iv(envelope), "channel_roles": gap_roles}
    )
    assert capped["ok"] and not capped["partial"]
    assert capped["outputs"]["trust_level"] == df.PIN_MAP_TRUST_CAP == "needs_review"
    _patch_output(
        monkeypatch, "D_atom_qualify_dataset_grade_trust", **{"outputs.trust_level": "untrusted"}
    )
    lower = _run(
        "D_flow_qualify_iv_dataset", {"evidence": _iv(envelope), "channel_roles": gap_roles}
    )
    assert lower["outputs"]["trust_level"] == "untrusted"  # a cap only lowers
