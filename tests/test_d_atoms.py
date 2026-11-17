"""Contracts for the fake D atom placeholder family (U1): typing, labels, chaining, refusal."""

import asyncio
import builtins
import inspect
import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from fastmcp import Client

from b1500_test_agent.mcp import a_atoms, a_flows, ab_flows, b_atoms, b_flows, c_atoms, c_flows
from b1500_test_agent.mcp import d_atoms as d
from b1500_test_agent.schemas import d_atom as ds

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / ".agents/skills/b1500-semiconductor-testing/references"
WAVEFORM = {
    "channels": [
        {
            "channel_id": 502,
            "pattern": "read_pulse",
            "vectors": [{"delta_time_s": 2e-6, "voltage_v": 0.2}],
            "events": [{"time_s": 1e-7, "points": 2}],
        }
    ]
}
FORBIDDEN_LABELS = {"pass", "fail", "trusted", "trusted_with_flags"}
SOURCE = {"kind": "caller", "name": "test-criteria"}
GATE = [{"channel": 1, "terminal": "gate"}]


def _q(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


def _record_index(envelope: dict, atom: str) -> int:
    return next(
        i
        for i, record in enumerate(envelope["atom_results"])
        if record["atom"] == atom and record["status"] == "ok"
    )


def _product(result: dict) -> dict:
    assert result["ok"], result.get("error")
    return result["outputs"]["product"]


def _iv_chain() -> dict[str, dict]:
    """Run the P0 path over a real fake C staircase envelope."""
    envelope = c_flows.C_flow_sweep_smu_staircase()
    evidence = {
        "envelope": envelope,
        "designated_record": _record_index(envelope, "C_atom_smu_read_measurement_data"),
    }
    out: dict[str, dict] = {"_envelope": envelope, "_evidence": evidence}
    out["expectation"] = d.D_atom_ingest_request_build_expectation(
        acquisition_kind="sweep_smu_staircase",
        c_request=envelope["inputs"],
        evidence={"envelope": envelope},
    )
    expectation = _product(out["expectation"])
    out["dataset"] = d.D_atom_ingest_smu_build_dataset(
        evidence=evidence, expectation=expectation, channel_roles=GATE
    )
    dataset = _product(out["dataset"])
    out["classify"] = d.D_atom_qualify_dataset_classify_status(dataset=dataset)
    out["completeness"] = d.D_atom_qualify_dataset_check_completeness(
        dataset=dataset, expectation=expectation
    )
    out["compliance"] = d.D_atom_qualify_iv_check_compliance(dataset=dataset)
    out["resolution"] = d.D_atom_qualify_iv_check_resolution(dataset=dataset)
    out["context"] = d.D_atom_qualify_run_check_context(
        c_evidence=evidence,
        upstream_evidence=[{"flow": "A_flow_drain_flex_errors", "fake": True, "ok": True}],
        dataset=dataset,
    )
    reports = [
        _product(out[key])
        for key in ("classify", "completeness", "compliance", "resolution", "context")
    ]
    out["trust"] = d.D_atom_qualify_dataset_grade_trust(dataset=dataset, reports=reports)
    trust = _product(out["trust"])
    out["leakage"] = d.D_atom_extract_leakage_current(
        dataset=dataset, trust=trust, terminal="gate", bias_points=[_q(0.5, "V")]
    )
    out["limits"] = d.D_atom_assess_value_check_limits(
        results=[_product(out["leakage"])],
        criteria=[{"parameter": "leakage_current", "comparator": "le", "limit": _q(1e-9, "A")}],
        criteria_source=SOURCE,
    )
    out["manifest"] = d.D_atom_archive_run_build_manifest(
        envelopes=[envelope],
        products=[_product(out[key]) for key in ("dataset", "trust", "leakage", "limits")],
        intent="Gate leakage screen (synthetic).",
    )
    out["bundle"] = d.D_atom_archive_run_write_bundle(manifest=_product(out["manifest"]))
    return out


def _all_args() -> dict[str, dict]:
    """Valid keyword arguments for every D atom, built from real fake upstream envelopes."""
    chain = _iv_chain()
    evidence = chain["_evidence"]
    expectation = _product(chain["expectation"])
    dataset = _product(chain["dataset"])
    trust = _product(chain["trust"])
    leak = _product(chain["leakage"])
    manifest = _product(chain["manifest"])
    view = _product(
        d.D_atom_shape_dataset_split_segments(dataset=dataset, rule={"kind": "direction"})
    )
    members = [{"dataset": dataset, "trust": trust, "outer_value": _q(v, "V")} for v in (0.5, 1.0)]
    family = _product(d.D_atom_shape_dataset_stack_family(members=members, outer_parameter="vgs"))
    cmu_env = c_flows.C_flow_spot_cmu_impedance()
    cmu_evidence = {
        "envelope": cmu_env,
        "designated_record": _record_index(cmu_env, "C_atom_cmu_read_measurement_data"),
    }
    cmu_expect = _product(
        d.D_atom_ingest_request_build_expectation(
            acquisition_kind="spot_cmu_impedance", c_request=cmu_env["inputs"]
        )
    )
    correction = _product(d.D_atom_qualify_cv_check_correction(dataset=dataset))
    wg_env = c_flows.C_flow_waveform_wgfmu_acquire(WAVEFORM)
    wg_evidence = {
        "envelope": wg_env,
        "designated_record": _record_index(wg_env, "C_atom_wgfmu_read_measurement_values"),
    }
    events = [{"name": "meas", "time_s": 1e-7, "points": 2, "interval_s": 1e-7}]
    axes = {"x": "v_gate", "y": "i_gate"}
    criteria = [{"parameter": "leakage_current", "comparator": "le", "limit": _q(1e-9, "A")}]
    table = _product(d.D_atom_render_dataset_build_table(datasets=[dataset]))
    spec = _product(d.D_atom_render_dataset_build_plot_spec(dataset=dataset, axes=axes))
    return {
        "D_atom_ingest_request_build_expectation": {
            "acquisition_kind": "sweep_smu_staircase",
            "c_request": chain["_envelope"]["inputs"],
        },
        "D_atom_ingest_smu_build_dataset": {
            "evidence": evidence,
            "expectation": expectation,
            "channel_roles": GATE,
        },
        "D_atom_ingest_easyexpert_build_dataset": {
            "evidence": {"envelope": a_atoms.A_atom_easyexpert_fetch_result()}
        },
        "D_atom_ingest_cmu_build_dataset": {
            "evidence": cmu_evidence,
            "expectation": cmu_expect,
            "imp_model": "Cp-G",
            "sweep_kind": "spot",
            "channel_roles": [{"channel": 7, "terminal": "gate"}],
        },
        "D_atom_ingest_wgfmu_build_series": {
            "evidence": wg_evidence,
            "expectation": expectation,
            "measure_mode": "current",
            "event_plan": events,
            "channel_roles": [{"channel": 5, "terminal": "drain"}],
        },
        "D_atom_qualify_dataset_classify_status": {"dataset": dataset},
        "D_atom_qualify_dataset_check_completeness": {
            "dataset": dataset,
            "expectation": expectation,
        },
        "D_atom_qualify_iv_check_compliance": {
            "dataset": dataset,
            "compliance": [{"channel": 1, "limit": _q(1e-3, "A")}],
        },
        "D_atom_qualify_iv_check_resolution": {"dataset": dataset, "module_type": "HRSMU"},
        "D_atom_qualify_run_check_context": {"c_evidence": evidence, "dataset": dataset},
        "D_atom_qualify_dataset_grade_trust": {
            "dataset": dataset,
            "reports": [_product(chain["classify"])],
        },
        "D_atom_qualify_iv_check_source_tracking": {
            "dataset": dataset,
            "tolerance": _q(0.01, "V"),
        },
        "D_atom_qualify_dataset_check_continuity": {
            "dataset": dataset,
            "axes": axes,
            "thresholds": {"spike_ratio": 10.0},
        },
        "D_atom_qualify_cv_check_correction": {"dataset": dataset},
        "D_atom_qualify_timeseries_check_events": {"dataset": dataset, "event_plan": events},
        "D_atom_shape_dataset_split_segments": {"dataset": dataset, "rule": {"kind": "direction"}},
        "D_atom_shape_dataset_stack_family": {"members": members, "outer_parameter": "vgs"},
        "D_atom_shape_dataset_normalize_geometry": {
            "dataset": dataset,
            "geometry": {"width_m": 1e-6},
        },
        "D_atom_derive_curve_compute_derivative": {
            "dataset": dataset,
            "trust": trust,
            "axes": axes,
            "method": {"name": "central_difference"},
        },
        "D_atom_derive_curve_interpolate": {
            "dataset": dataset,
            "axes": axes,
            "mode": "y_at_x",
            "targets": [_q(0.5, "V")],
        },
        "D_atom_derive_curve_fit_linear": {
            "dataset": dataset,
            "axes": axes,
            "window": {"low": 0.1, "high": 0.5, "unit": "V"},
        },
        "D_atom_derive_dataset_summarize_columns": {"dataset": dataset, "columns": ["i_gate"]},
        "D_atom_derive_timeseries_summarize_windows": {
            "dataset": dataset,
            "windows": [{"low": 0.0, "high": 1.0, "unit": "s"}],
        },
        "D_atom_extract_leakage_current": {
            "dataset": dataset,
            "trust": trust,
            "terminal": "gate",
            "window": {"low": 0.0, "high": 1.0, "unit": "V"},
        },
        "D_atom_extract_transfer_vth": {
            "dataset": dataset,
            "trust": trust,
            "vth": {"method": "constant_current", "icc": _q(1e-7, "A")},
            "polarity": "n",
            "vds": _q(0.05, "V"),
            "gate_terminal": "gate",
            "drain_terminal": "drain",
        },
        "D_atom_extract_transfer_gm_max": {
            "dataset": dataset,
            "trust": trust,
            "derivative": {"name": "central_difference"},
            "gate_terminal": "gate",
            "drain_terminal": "drain",
        },
        "D_atom_extract_transfer_ss": {
            "dataset": dataset,
            "trust": trust,
            "current_window": {"low": 1e-11, "high": 1e-8, "unit": "A"},
            "min_decades": 1.5,
            "gate_terminal": "gate",
            "drain_terminal": "drain",
        },
        "D_atom_extract_transfer_on_off": {
            "dataset": dataset,
            "trust": trust,
            "vg_on": _q(1.0, "V"),
            "vg_off": _q(0.0, "V"),
            "drain_terminal": "drain",
        },
        "D_atom_extract_transfer_voltage_shift": {
            "segments": view,
            "trust": trust,
            "at_current": _q(1e-7, "A"),
        },
        "D_atom_extract_output_ron": {
            "family": family,
            "window": {"low": 0.0, "high": 0.1, "unit": "V"},
            "drain_terminal": "drain",
        },
        "D_atom_extract_leakage_breakdown_voltage": {
            "dataset": dataset,
            "trust": trust,
            "threshold": _q(1e-6, "A"),
            "direction": "increasing",
            "terminal": "gate",
        },
        "D_atom_extract_cv_cox": {
            "dataset": dataset,
            "trust": trust,
            "correction": correction,
            "window": {"low": -2.0, "high": -1.0, "unit": "V"},
        },
        "D_atom_extract_cv_vfb": {
            "dataset": dataset,
            "trust": trust,
            "vfb": {
                "method": "flatband_capacitance",
                "substrate_type": "p",
                "doping_per_m3": 1e23,
                "oxide_relative_permittivity": 3.9,
                "semiconductor_relative_permittivity": 11.7,
                "temperature_k": 300.0,
            },
        },
        "D_atom_assess_value_check_limits": {
            "results": [leak],
            "criteria": criteria,
            "criteria_source": SOURCE,
        },
        "D_atom_assess_dataset_check_envelope": {
            "dataset": dataset,
            "envelope": [{"quantity": "current", "high": _q(1e-3, "A")}],
            "criteria_source": SOURCE,
        },
        "D_atom_assess_dataset_compare_reference": {
            "target": leak,
            "reported_values": [
                {"parameter": "leakage_current", "quantity": _q(1e-12, "A"), "reporter": "ee"}
            ],
            "tolerances": [{"parameter": "leakage_current", "relative": 0.1}],
            "criteria_source": SOURCE,
        },
        "D_atom_archive_run_build_manifest": {
            "envelopes": [chain["_envelope"]],
            "intent": "Gate leakage screen (synthetic).",
        },
        "D_atom_archive_run_write_bundle": {"manifest": manifest, "artifacts": [table, spec]},
        "D_atom_archive_run_load_bundle": {"manifest": manifest},
        "D_atom_render_dataset_build_plot_spec": {"dataset": dataset, "axes": axes},
        "D_atom_render_dataset_build_table": {"datasets": [dataset, view]},
        "D_atom_render_run_build_report": {"manifest": manifest, "results": [leak]},
    }


@pytest.fixture(scope="module")
def all_args() -> dict[str, dict]:
    return _all_args()


@pytest.fixture(scope="module")
def all_results(all_args) -> dict[str, dict]:
    return {f.__name__: f(**all_args[f.__name__]) for f in d.D_ATOM_FUNCTIONS}


def _walk(value, path=()):
    """Yield (path, key, value) for every dict entry in a nested structure."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield path, key, item
            yield from _walk(item, (*path, key))
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, path)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


# ---------------------------------------------------------------------------
# Catalog, naming and registration
# ---------------------------------------------------------------------------


def test_catalog_has_42_atoms_with_contract_counts():
    names = [f.__name__ for f in d.D_ATOM_FUNCTIONS]
    assert len(names) == len(set(names)) == 42
    assert set(names) == set(d._SPECS)
    stages = Counter(spec.stage for spec in d._SPECS.values())
    assert stages == {
        "ingest": 5,
        "qualify": 10,
        "shape": 3,
        "derive": 5,
        "extract": 10,
        "assess": 3,
        "archive": 3,
        "render": 3,
    }
    # Amendment M3: write_bundle moves to P0 -> P0 12, P1 17, P2 13.
    assert Counter(spec.priority for spec in d._SPECS.values()) == {"P0": 12, "P1": 17, "P2": 13}
    assert d._SPECS["D_atom_archive_run_write_bundle"].priority == "P0"
    assert {spec.product_type for spec in d._SPECS.values()} == set(ds.PRODUCT_TYPES)


@pytest.mark.parametrize("function", d.D_ATOM_FUNCTIONS, ids=lambda f: f.__name__)
def test_names_follow_closed_vocabularies(function):
    name = function.__name__
    spec = d._SPECS[name]
    assert spec.stage in ds.D_STAGES
    assert spec.subject in ds.D_STAGE_SUBJECTS[spec.stage]
    prefix = f"D_atom_{spec.stage}_{spec.subject}_"
    assert name.startswith(prefix)
    action = name[len(prefix) :]
    if spec.stage == "extract":
        assert action in ds.D_EXTRACT_ACTIONS
    else:
        assert action in ds.D_VERBS or action.startswith(ds.D_VERB_PREFIXES)
    tokens = name.lower().split("_")
    assert not set(tokens) & set(ds.D_FORBIDDEN_NAME_TOKENS)


def test_module_imports_no_abc_tools_or_hardware_transport():
    code = (
        "import sys, json; import b1500_test_agent.mcp.d_atoms; "
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
    forbidden = ("a_atoms", "b_atoms", "c_atoms", "a_flows", "b_flows", "c_flows", "ab_flows")
    assert not [m for m in loaded if m.rsplit(".", 1)[-1] in forbidden]
    assert not [m for m in loaded if m.startswith("b1500_test_agent.instruments")]


def test_mcp_discovery_typed_schemas_and_legacy_registration(all_args):
    from b1500_test_agent.mcp.server import capabilities, mcp

    async def exercise():
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            caps = capabilities()
            assert caps["D_atoms"] == [f.__name__ for f in d.D_ATOM_FUNCTIONS]
            assert len(caps["D_atoms"]) == 42
            legacy = {
                "A_atoms": a_atoms.A_ATOM_FUNCTIONS,
                "B_atoms": b_atoms.B_ATOM_FUNCTIONS,
                "C_atoms": c_atoms.C_ATOM_FUNCTIONS,
                "A_flows": a_flows.A_FLOW_FUNCTIONS,
                "B_flows": b_flows.B_FLOW_FUNCTIONS,
                "C_flows": c_flows.C_FLOW_FUNCTIONS,
                "AB_flows": ab_flows.AB_FLOW_FUNCTIONS,
            }
            families = set(caps) - {"atom", "fake", "hardware_touched", "basis"}
            # D_flows and CD_flows joined later (tests/test_d_flows.py, tests/test_cd_flows.py).
            later = {"D_atoms", "D_flows", "CD_flows"}
            assert families - {"implementation_status"} == set(legacy) | later
            registered = set()
            for family, functions in legacy.items():
                assert caps[family] == [f.__name__ for f in functions]
                assert not any(name.startswith("D_") for name in caps[family])
                registered |= set(caps[family])
            assert set(tools) == registered.union(*(caps[family] for family in later))
            for function in d.D_ATOM_FUNCTIONS:
                schema = tools[function.__name__].input_schema
                assert schema["type"] == "object" and schema["properties"]
                assert schema.get("additionalProperties") is False
                text = json.dumps(schema)
                if any(k in all_args[function.__name__] for k in ("dataset", "manifest")):
                    assert '"product_type"' in text and '"placeholder"' in text
                arguments = json.loads(json.dumps(all_args[function.__name__], default=str))
                result = await client.call_tool(function.__name__, arguments)
                assert not result.is_error
                payload = result.structured_content
                assert payload["ok"] and payload["analysis_state"] == "not_computed"
                assert payload["outputs"]["product"]["content"] is None
            missing = await client.call_tool("D_atom_qualify_dataset_classify_status", {})
            assert missing.structured_content["error"]["type"] == "context_missing"

    asyncio.run(exercise())


def test_reference_docs_list_every_atom():
    catalog = (DOCS / "mcp-tools/d-atoms.md").read_text()
    for function in d.D_ATOM_FUNCTIONS:
        assert f"`{function.__name__}`" in catalog
    assert "d-atoms.md" in (DOCS / "mcp-tools/README.md").read_text()
    overview = (DOCS / "instrument-interaction-tools.md").read_text()
    assert "D_atom_<stage>_<subject>_<action>" in overview


# ---------------------------------------------------------------------------
# Envelope, fake markers, banned keys and synthetic labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("function", d.D_ATOM_FUNCTIONS, ids=lambda f: f.__name__)
def test_every_atom_is_a_fake_placeholder(function, all_results):
    result = all_results[function.__name__]
    spec = d._SPECS[function.__name__]
    assert result["atom"] == function.__name__
    assert result["fake"] is True and result["hardware_touched"] is False
    assert result["class"] == "D" and result["deterministic"] is True
    assert (result["stage"], result["subject"]) == (spec.stage, spec.subject)
    assert result["ok"] is True and "error" not in result
    assert result["analysis_state"] == "not_computed"
    assert result["side_effects"] == {
        "hardware": "none",
        "filesystem_writes": [],
        "artifact_written": False,
    }
    product = ds.ProductRef.model_validate(result["outputs"]["product"])
    assert product.ref_kind == "placeholder" and product.content is None
    assert product.product_type == spec.product_type
    assert product.producer == function.__name__
    assert product.product_id.startswith(f"placeholder:{function.__name__}:")
    assert result["data_origin"] == product.data_origin == "synthetic"
    assert result["synthetic"] is True and product.synthetic is True
    assert result["provenance"]["upstream"] == product.upstream
    ds.DAtomEnvelope.model_validate(result)
    json.dumps(result, allow_nan=False)


def _error_results(all_args) -> list[dict]:
    dataset = all_args["D_atom_qualify_dataset_classify_status"]["dataset"]
    return [
        d.D_atom_qualify_dataset_classify_status(),
        d.D_atom_qualify_dataset_grade_trust(dataset=dataset, reports=[dataset]),
        d.D_atom_extract_leakage_current(dataset=dataset),
        d.D_atom_ingest_smu_build_dataset(
            evidence={"envelope": c_flows.C_flow_spot_cmu_impedance()}
        ),
        d.D_atom_qualify_dataset_classify_status(dataset={"product_type": "dataset"}),
    ]


def test_banned_result_keys_absent_everywhere(all_results, all_args):
    for result in [*all_results.values(), *_error_results(all_args)]:
        for path, key, _ in _walk(result):
            assert key not in ds.BANNED_RESULT_KEYS, (result["atom"], path, key)


def test_no_pass_or_trusted_label_on_synthetic_data(all_results):
    for name, result in all_results.items():
        assert not FORBIDDEN_LABELS & set(_strings(result["outputs"])), name
        assert not FORBIDDEN_LABELS & set(_strings(result["findings"])), name
        outputs = result["outputs"]
        if result["stage"] == "qualify" and "check_outcome" in outputs:
            assert outputs["check_outcome"] is None
        if result["stage"] == "extract":
            assert outputs["results"] == []
    assert all_results["D_atom_qualify_dataset_grade_trust"]["outputs"]["trust_level"] == (
        "synthetic_only"
    )
    assert all_results["D_atom_qualify_dataset_grade_trust"]["outputs"]["fit_mask"] is None
    for name in (
        "D_atom_assess_value_check_limits",
        "D_atom_assess_dataset_check_envelope",
        "D_atom_assess_dataset_compare_reference",
    ):
        assert all_results[name]["outputs"]["verdict"] == "synthetic_only"
        assert all_results[name]["outputs"]["verdict_scope"] is None


def test_atoms_never_call_abc_tools(monkeypatch, all_args):
    def forbidden(*args, **kwargs):
        raise AssertionError("D atoms must not call A/B/C tools")

    for module in (a_atoms, b_atoms, c_atoms, a_flows, b_flows, c_flows, ab_flows):
        for attr in dir(module):
            tool_name = attr[:2] in {"A_", "B_", "C_"} or attr.startswith("AB_")
            if tool_name and callable(getattr(module, attr)):
                monkeypatch.setattr(module, attr, forbidden)
    for function in d.D_ATOM_FUNCTIONS:
        result = function(**all_args[function.__name__])
        assert result["ok"] and result["hardware_touched"] is False


# ---------------------------------------------------------------------------
# ProductRef chaining (R1-R4) and origin propagation
# ---------------------------------------------------------------------------


def test_p0_chain_placeholders_in_and_out_with_deterministic_ids():
    first, second = _iv_chain(), _iv_chain()
    keys = [k for k in first if not k.startswith("_")]
    for key in keys:
        assert first[key]["ok"] and first[key]["analysis_state"] == "not_computed", key
        assert _product(first[key])["product_id"] == _product(second[key])["product_id"], key
        assert first[key]["outputs"] == second[key]["outputs"], key
    dataset = _product(first["dataset"])
    assert dataset["upstream"] == [_product(first["expectation"])["product_id"]]
    trust = _product(first["trust"])
    assert trust["upstream"][0] == dataset["product_id"] and len(trust["upstream"]) == 6
    assert _product(first["leakage"])["upstream"] == [dataset["product_id"], trust["product_id"]]
    assert _product(first["limits"])["product_type"] == "verdict"
    assert first["limits"]["outputs"]["verdict"] == "synthetic_only"
    assert first["dataset"]["data_origin"] == "synthetic"
    codes = {f["code"] for f in first["context"]["findings"]}
    assert {"evidence_unverified", "upstream_synthetic"} <= codes


def test_inputs_change_product_ids():
    chain = _iv_chain()
    dataset = _product(chain["dataset"])
    trust = _product(chain["trust"])
    a = d.D_atom_extract_leakage_current(
        dataset=dataset, trust=trust, terminal="gate", bias_points=[_q(0.5, "V")]
    )
    b = d.D_atom_extract_leakage_current(
        dataset=dataset, trust=trust, terminal="gate", bias_points=[_q(0.6, "V")]
    )
    assert _product(a)["product_id"] != _product(b)["product_id"]


@pytest.mark.parametrize(
    "call",
    [
        lambda: d.D_atom_qualify_dataset_classify_status(),
        lambda: d.D_atom_qualify_dataset_grade_trust(),
        lambda: d.D_atom_assess_value_check_limits(criteria_source=SOURCE),
        lambda: d.D_atom_archive_run_write_bundle(),
        lambda: d.D_atom_ingest_smu_build_dataset(channel_roles=GATE),
    ],
)
def test_missing_required_product_is_context_missing(call):
    result = call()
    assert result["ok"] is False and result["analysis_state"] == "rejected_input"
    assert result["error"]["type"] == "context_missing"
    assert result["outputs"]["product"] is None
    assert result["fake"] is True and result["hardware_touched"] is False


def test_miswired_product_type_is_rejected_input(all_args):
    chain = _iv_chain()
    expectation = _product(chain["expectation"])
    dataset = _product(chain["dataset"])
    trust = _product(chain["trust"])
    cases = [
        d.D_atom_qualify_dataset_classify_status(dataset=expectation),
        d.D_atom_qualify_dataset_grade_trust(dataset=dataset, reports=[trust]),
        d.D_atom_extract_leakage_current(
            dataset=dataset, trust=dataset, terminal="gate", bias_points=[_q(0.1, "V")]
        ),
        d.D_atom_archive_run_write_bundle(manifest=dataset),
        d.D_atom_extract_cv_cox(
            dataset=dataset,
            trust=trust,
            correction=_product(chain["classify"]),
            window={"low": -2.0, "high": -1.0, "unit": "V"},
        ),
    ]
    for result in cases:
        assert result["ok"] is False
        assert result["error"]["type"] == "rejected_input", result["error"]
        assert result["outputs"]["product"] is None


def test_placeholder_cannot_carry_content():
    ref = {
        "product_type": "dataset",
        "product_id": "placeholder:D_atom_ingest_smu_build_dataset:" + "0" * 16,
        "producer": "D_atom_ingest_smu_build_dataset",
        "data_origin": "synthetic",
        "synthetic": True,
    }
    with pytest.raises(ValueError):
        ds.ProductRef.model_validate({**ref, "content": {"i_gate": [1e-12]}})
    with pytest.raises(ValueError):
        ds.ProductRef.model_validate({**ref, "synthetic": False})
    result = d.D_atom_qualify_dataset_classify_status(dataset={**ref, "content": {"x": 1}})
    assert result["ok"] is False and result["error"]["type"] == "rejected_input"


def _ref(product_type: str, producer: str, origin: str) -> ds.ProductRef:
    return ds.ProductRef(
        product_type=product_type,
        product_id=f"placeholder:{producer}:{'ab' * 8}",
        producer=producer,
        data_origin=origin,
        synthetic=origin == "synthetic",
    )


def test_origin_weakest_wins_and_is_never_raised():
    inst_dataset = _ref("dataset", "D_atom_ingest_smu_build_dataset", "instrument")
    inst_report = _ref("check_report", "D_atom_qualify_dataset_classify_status", "instrument")
    graded = d.D_atom_qualify_dataset_grade_trust(dataset=inst_dataset, reports=[inst_report])
    assert graded["data_origin"] == "instrument" and graded["synthetic"] is False
    assert graded["outputs"]["trust_level"] is None
    mixed = d.D_atom_qualify_dataset_grade_trust(
        dataset=inst_dataset,
        reports=[_ref("check_report", "D_atom_qualify_dataset_classify_status", "synthetic")],
    )
    assert mixed["data_origin"] == "synthetic"
    assert mixed["outputs"]["trust_level"] == "synthetic_only"
    fixture = _ref("extraction_result", "D_atom_extract_leakage_current", "fixture")
    verdict = d.D_atom_assess_value_check_limits(
        results=[fixture],
        criteria=[{"parameter": "leakage_current", "comparator": "le", "limit": _q(1e-9, "A")}],
        criteria_source=SOURCE,
    )
    assert verdict["data_origin"] == "fixture"
    assert verdict["outputs"]["verdict"] is None and verdict["outputs"]["verdict_scope"] is None
    envelope = c_flows.C_flow_sweep_smu_staircase()
    raised = d.D_atom_ingest_smu_build_dataset(
        evidence={
            "envelope": envelope,
            "designated_record": _record_index(envelope, "C_atom_smu_read_measurement_data"),
        },
        expectation=_ref("expectation", "D_atom_ingest_request_build_expectation", "instrument"),
        channel_roles=GATE,
        declared_origin="instrument",
    )
    assert raised["ok"] and raised["data_origin"] == "synthetic"
    assert any("cannot raise" in w for w in raised["warnings"])
    lowered_ctx = d.D_atom_qualify_run_check_context(
        upstream_evidence=[{"flow": "A_flow_drain_flex_errors", "fake": False}],
        declared_origin="fixture",
    )
    assert lowered_ctx["data_origin"] == "fixture"


# ---------------------------------------------------------------------------
# Inputs: U4 criteria, units, evidence wiring
# ---------------------------------------------------------------------------


def test_u4_criteria_and_methods_are_mandatory(all_args):
    dataset = all_args["D_atom_qualify_dataset_classify_status"]["dataset"]
    trust = all_args["D_atom_extract_leakage_current"]["trust"]
    leak = all_args["D_atom_assess_value_check_limits"]["results"][0]
    for result in (
        d.D_atom_assess_value_check_limits(results=[leak], criteria_source=SOURCE),
        d.D_atom_assess_value_check_limits(
            results=[leak],
            criteria=all_args["D_atom_assess_value_check_limits"]["criteria"],
        ),
        d.D_atom_extract_leakage_current(dataset=dataset, trust=trust, terminal="gate"),
        d.D_atom_extract_transfer_vth(dataset=dataset, trust=trust),
        d.D_atom_ingest_cmu_build_dataset(
            **{
                **all_args["D_atom_ingest_cmu_build_dataset"],
                "imp_model": None,
            }
        ),
    ):
        assert result["ok"] is False and result["error"]["type"] == "context_missing"
    alias = d.D_atom_extract_transfer_vth(
        dataset=dataset, trust=trust, vth={"method": "linear_extrapolation"}
    )
    assert alias["error"]["type"] == "rejected_input"


def test_units_are_never_inferred(all_args):
    dataset = all_args["D_atom_qualify_dataset_classify_status"]["dataset"]
    trust = all_args["D_atom_extract_leakage_current"]["trust"]
    leak = all_args["D_atom_assess_value_check_limits"]["results"][0]
    bad_bias = d.D_atom_extract_leakage_current(
        dataset=dataset, trust=trust, terminal="gate", bias_points=[_q(0.5, "A")]
    )
    bad_limit = d.D_atom_assess_value_check_limits(
        results=[leak],
        criteria=[{"parameter": "leakage_current", "comparator": "le", "limit": _q(1, "V")}],
        criteria_source=SOURCE,
    )
    for result in (bad_bias, bad_limit):
        assert result["ok"] is False and result["error"]["type"] == "unit_mismatch"


def test_evidence_wiring_is_checked_not_guessed():
    smu = c_flows.C_flow_sweep_smu_staircase()
    cmu = c_flows.C_flow_spot_cmu_impedance()
    expectation = _ref("expectation", "D_atom_ingest_request_build_expectation", "synthetic")
    base = {"expectation": expectation, "channel_roles": GATE}
    wrong_family = d.D_atom_ingest_smu_build_dataset(
        evidence={
            "envelope": cmu,
            "designated_record": _record_index(cmu, "C_atom_cmu_read_measurement_data"),
        },
        **base,
    )
    wrong_record = d.D_atom_ingest_smu_build_dataset(
        evidence={"envelope": smu, "designated_record": 0}, **base
    )
    no_record = d.D_atom_ingest_smu_build_dataset(evidence={"envelope": smu}, **base)
    duplicate_roles = d.D_atom_ingest_smu_build_dataset(
        evidence={
            "envelope": smu,
            "designated_record": _record_index(smu, "C_atom_smu_read_measurement_data"),
        },
        expectation=expectation,
        channel_roles=[{"channel": 1, "terminal": "gate"}, {"channel": 1, "terminal": "drain"}],
    )
    wrong_kind = d.D_atom_ingest_request_build_expectation(
        acquisition_kind="spot_smu_iv", c_request={}, evidence={"envelope": smu}
    )
    bad_request = d.D_atom_ingest_request_build_expectation(
        acquisition_kind="sweep_smu_staircase", c_request={"raw_command": "XE"}
    )
    assert wrong_family["error"]["type"] == "rejected_input"
    assert wrong_record["error"]["type"] == "rejected_input"
    assert no_record["error"]["type"] == "context_missing"
    assert duplicate_roles["error"]["type"] == "rejected_input"
    assert wrong_kind["error"]["type"] == "rejected_input"
    assert bad_request["error"]["type"] == "rejected_input"


def test_inline_size_cap_gives_size_limit():
    smu = c_flows.C_flow_sweep_smu_staircase()
    index = _record_index(smu, "C_atom_smu_read_measurement_data")
    smu["atom_results"][index]["result"]["parameters"]["rows"] = [0] * (ds.MAX_INLINE_POINTS + 1)
    result = d.D_atom_ingest_smu_build_dataset(
        evidence={"envelope": smu, "designated_record": index},
        expectation=_ref("expectation", "D_atom_ingest_request_build_expectation", "synthetic"),
        channel_roles=GATE,
    )
    assert result["ok"] is False and result["error"]["type"] == "size_limit"


# ---------------------------------------------------------------------------
# Archive: single writer refuses; nothing is written (U2, M4)
# ---------------------------------------------------------------------------


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()}


def test_write_bundle_refuses_and_creates_no_file(tmp_path, monkeypatch, all_args):
    data_root = ROOT / "data"
    before_repo, before_tmp = _files(data_root), _files(tmp_path)
    monkeypatch.chdir(tmp_path)
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"D atom attempted a file write: {file}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    manifest = d.D_atom_archive_run_build_manifest(**all_args["D_atom_archive_run_build_manifest"])
    bundle = d.D_atom_archive_run_write_bundle(**all_args["D_atom_archive_run_write_bundle"])
    loaded = d.D_atom_archive_run_load_bundle(manifest=_product(manifest))
    monkeypatch.undo()
    assert _files(data_root) == before_repo and _files(tmp_path) == before_tmp
    outputs = bundle["outputs"]
    assert outputs["artifact_written"] is False
    assert outputs["write_refusal"] == ["fake_mode", "synthetic_origin"]
    assert outputs["planned_paths"][0].endswith("/manifest.json")
    assert len(outputs["planned_paths"]) == 3
    for path in outputs["planned_paths"]:
        assert not path.startswith("/") and ".." not in path.split("/")
        assert path.split("/")[0] in {"processed", "reports"}
    assert bundle["side_effects"]["filesystem_writes"] == []
    assert loaded["outputs"]["artifact_read"] is False and loaded["outputs"]["hash_ok"] is None
    params = inspect.signature(d.D_atom_archive_run_write_bundle).parameters
    assert set(params) == {"manifest", "artifacts"}


def test_write_bundle_refusal_follows_origin():
    fixture = d.D_atom_archive_run_write_bundle(
        manifest=_ref("manifest", "D_atom_archive_run_build_manifest", "fixture")
    )
    assert fixture["outputs"]["write_refusal"] == ["fake_mode", "fixture_requires_test_root"]
    instrument = d.D_atom_archive_run_write_bundle(
        manifest=_ref("manifest", "D_atom_archive_run_build_manifest", "instrument")
    )
    assert instrument["outputs"]["write_refusal"] == ["fake_mode"]
    assert instrument["outputs"]["artifact_written"] is False


def test_build_manifest_accepts_the_derived_archive_cap_and_rejects_above():
    from b1500_test_agent.schemas.d_flow import MAX_ARCHIVE_ENVELOPES

    envelope = c_flows.C_flow_spot_smu_iv()
    at_cap = d.D_atom_archive_run_build_manifest(
        envelopes=[envelope] * MAX_ARCHIVE_ENVELOPES, intent="Largest CD run."
    )
    assert at_cap["ok"] is True, at_cap.get("error")
    above = d.D_atom_archive_run_build_manifest(
        envelopes=[envelope] * (MAX_ARCHIVE_ENVELOPES + 1), intent="Too many."
    )
    assert above["ok"] is False and above["error"]["type"] == "rejected_input"


@pytest.mark.parametrize("kind", ["sweep_cmu_cf", "sweep_cmu_ac_level"])
def test_expectation_rejects_non_positive_cmu_endpoints_like_the_c_schema(kind):
    result = d.D_atom_ingest_request_build_expectation(
        acquisition_kind=kind, c_request={"start": 0.0, "stop": 1.0}
    )
    assert result["ok"] is False and result["error"]["type"] == "rejected_input"
    assert "positive" in result["error"]["message"]
