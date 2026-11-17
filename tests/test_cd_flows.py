"""Contracts for the fake CD flow family: one C flow, its D flow, archive; states and taint."""

import asyncio
import builtins
import copy
import io
import json
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
from b1500_test_agent.mcp import cd_flows as cd
from b1500_test_agent.mcp import d_flows as df
from b1500_test_agent.schemas import d_atom as ds
from b1500_test_agent.schemas import d_flow as d_schema

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / ".agents/skills/b1500-semiconductor-testing/references"
# Legacy catalogs moved here in WP0.4 (frozen history).
CATALOG = ROOT / "references/driver-map/legacy-catalog"
SOURCE = {"kind": "caller", "name": "test-criteria"}
GATE = [{"channel": 1, "terminal": "gate"}]
CMU_GATE = [{"channel": 7, "terminal": "gate"}]
ROLES3 = [
    {"channel": 1, "terminal": "gate"},
    {"channel": 2, "terminal": "drain"},
    {"channel": 3, "terminal": "source"},
]
CD_NAMES = [
    "CD_flow_qualify_iv_dataset",
    "CD_flow_screen_iv_leakage",
    "CD_flow_analyze_iv_transfer",
    "CD_flow_qualify_cv_dataset",
]
RESERVED = ["CD_flow_qualify_timeseries_dataset"]
FORBIDDEN = {"pass", "fail", "trusted", "trusted_with_flags"}
EXPECT = "D_atom_ingest_request_build_expectation"
ENVELOPE_ATOM = "D_atom_assess_dataset_check_envelope"
ARCHIVE = "D_flow_archive_run_bundle"


def _q(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


def _criteria(limit: float = 1e-9) -> list[dict]:
    return [{"parameter": "leakage_current", "comparator": "le", "limit": _q(limit, "A")}]


LEAKAGE = {
    "terminal": "gate",
    "bias_points_v": [1.0],
    "criteria": _criteria(),
    "criteria_source": SOURCE,
}
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
TRANSFER = {
    "gate_terminal": "gate",
    "drain_terminal": "drain",
    "polarity": "n",
    "vds": _q(0.05, "V"),
    "parameters": ["gm_max", "vth", "ss", "on_off"],
    "derivative": {"name": "central_difference"},
    "vth": {"method": "max_gm_linear_extrapolation"},
    "ss": {"current_window": {"low": 1e-11, "high": 1e-8, "unit": "A"}, "min_decades": 1.5},
    "on_off": {"vg_on": _q(2.0, "V"), "vg_off": _q(0.0, "V")},
    "criteria_source": SOURCE,
}
KINDS = {
    "CD_flow_qualify_iv_dataset": {
        "spot_smu_iv": {},
        "sweep_smu_staircase": {},
        "pulse_smu_spot": {},
    },
    "CD_flow_screen_iv_leakage": {"spot_smu_iv": {"level": 1.0}, "sweep_smu_staircase": {}},
    "CD_flow_analyze_iv_transfer": {"sweep_smu_staircase_biased": BIASED},
    "CD_flow_qualify_cv_dataset": {
        "spot_cmu_impedance": {},
        "sweep_cmu_cv": {"start": -1.0, "stop": 1.0},
        "sweep_cmu_cf": {"start": 1e3, "stop": 1e6},
        "sweep_cmu_ac_level": {"start": 0.01, "stop": 0.1},
        "pulse_cmu_spot": {},
        "pulse_cmu_cv": {},
    },
}
D_TAIL = {
    "CD_flow_qualify_iv_dataset": [],
    "CD_flow_screen_iv_leakage": [
        "D_atom_extract_leakage_current",
        "D_atom_assess_value_check_limits",
    ],
    "CD_flow_analyze_iv_transfer": [
        "D_atom_extract_transfer_gm_max",
        "D_atom_extract_transfer_vth",
        "D_atom_extract_transfer_ss",
        "D_atom_extract_transfer_on_off",
    ],
    "CD_flow_qualify_cv_dataset": [],
}
Q_IV_AFTER_EXPECT = [
    "D_atom_ingest_smu_build_dataset",
    "D_atom_qualify_dataset_classify_status",
    "D_atom_qualify_dataset_check_completeness",
    "D_atom_qualify_iv_check_compliance",
    "D_atom_qualify_iv_check_resolution",
    "D_atom_qualify_run_check_context",
    "D_atom_qualify_dataset_grade_trust",
]
Q_CV_AFTER_EXPECT = [
    "D_atom_ingest_cmu_build_dataset",
    "D_atom_qualify_dataset_classify_status",
    "D_atom_qualify_dataset_check_completeness",
    "D_atom_qualify_cv_check_correction",
    "D_atom_qualify_run_check_context",
    "D_atom_qualify_dataset_grade_trust",
]
ARCHIVE_ATOMS = ["D_atom_archive_run_build_manifest", "D_atom_archive_run_write_bundle"]


def _request(name: str, kind: str | None = None, **extra) -> dict:
    kind = kind or next(iter(KINDS[name]))
    base = {"acquisition": {"kind": kind, "request": copy.deepcopy(KINDS[name][kind])}}
    base["channel_roles"] = {
        "CD_flow_qualify_iv_dataset": GATE,
        "CD_flow_screen_iv_leakage": GATE,
        "CD_flow_analyze_iv_transfer": ROLES3,
        "CD_flow_qualify_cv_dataset": CMU_GATE,
    }[name]
    if name == "CD_flow_screen_iv_leakage":
        base["leakage"] = copy.deepcopy(LEAKAGE)
    if name == "CD_flow_analyze_iv_transfer":
        base["transfer"] = copy.deepcopy(TRANSFER)
    if name == "CD_flow_qualify_cv_dataset":
        base["imp_model"] = "Cp-G"
    return {**base, **extra}


def _run(name: str, request: dict) -> dict:
    return getattr(cd, name)(request)


def _cases() -> list[tuple[str, str]]:
    return [(name, kind) for name in CD_NAMES for kind in KINDS[name]]


@pytest.fixture(scope="module")
def results() -> dict[tuple[str, str], dict]:
    return {(name, kind): _run(name, _request(name, kind)) for name, kind in _cases()}


def _walk(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield path, key, item
            yield from _walk(item, (*path, key))
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, path)


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in {"timestamp", "computed_at"}}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _child(result: dict, name: str) -> dict:
    return next(r for r in result["child_results"] if r["name"] == name)


def _spy_children(monkeypatch) -> list[str]:
    """Record every C flow, C atom, D flow and D atom call; forbid A/B tools."""
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        raise AssertionError("CD flows must not call A/B tools")

    for module in (a_atoms, b_atoms, a_flows, b_flows, ab_flows):
        for attr in dir(module):
            tool = attr[:2] in {"A_", "B_"} or attr.startswith("AB_")
            if tool and callable(getattr(module, attr)):
                monkeypatch.setattr(module, attr, forbidden)
    for module, prefix in (
        (c_flows, "C_flow_"),
        (c_atoms, "C_atom_"),
        (df, "D_flow_"),
        (d_atoms, "D_atom_"),
    ):
        for attr in dir(module):
            if attr.startswith(prefix) and callable(getattr(module, attr)):
                original = getattr(module, attr)

                def spy(*args, _name=attr, _original=original, **kwargs):
                    calls.append(_name)
                    return _original(*args, **kwargs)

                monkeypatch.setattr(module, attr, spy)
    return calls


def _replace_c_flow(monkeypatch, kind: str, transform):
    """Patch C_flow_<kind> to return a transformed copy of its real fake envelope."""
    name = f"C_flow_{kind}"
    original = getattr(c_flows, name)
    calls = []

    def patched(**kwargs):
        calls.append(name)
        return transform(original(**kwargs))

    monkeypatch.setattr(c_flows, name, patched)
    return calls


# ---------------------------------------------------------------------------
# Catalog, discovery and docs
# ---------------------------------------------------------------------------


def test_catalog_pairs_every_cd_flow_with_its_d_flow_and_c_kinds():
    assert [f.__name__ for f in cd.CD_FLOW_FUNCTIONS] == CD_NAMES
    assert tuple(RESERVED) == cd.RESERVED_CD_FLOWS
    for name in RESERVED:
        assert not hasattr(cd, name)
    d_names = {f.__name__ for f in df.D_FLOW_FUNCTIONS}
    c_names = {f.__name__ for f in c_flows.C_FLOW_FUNCTIONS}
    rows = {row["flow"]: row for row in cd.cd_flow_catalog()}
    assert list(rows) == CD_NAMES
    for name, row in rows.items():
        assert row["d_flow"] == name[1:] and row["d_flow"] in d_names
        assert name == f"CD_flow_{row['category']}_{row['domain']}_{row['subject']}"
        for kind in KINDS[name]:
            assert f"C_flow_{kind}" in c_names
    assert [rows[n]["priority"] for n in CD_NAMES] == ["P0", "P0", "P1", "P2"]
    assert "D_flow_archive_run_bundle" in d_names and "CD_flow_archive_run_bundle" not in rows


def test_mcp_discovery_exposes_kind_discriminator_and_calls():
    from b1500_test_agent.mcp.server import capabilities, mcp

    async def exercise():
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert capabilities()["CD_flows"] == CD_NAMES
            assert len(capabilities()["CD_flows"]) == 4
            for name in RESERVED:
                assert name not in tools
            for name in CD_NAMES:
                schema_ = tools[name].input_schema
                assert schema_["required"] == ["request"]
                request_schema = schema_["properties"]["request"]
                assert "acquisition" in request_schema["required"]
                acquisition = request_schema["properties"]["acquisition"]
                branches = acquisition.get("oneOf", [acquisition])
                consts = []
                for branch in branches:
                    assert {"kind", "request"} <= set(branch["required"])
                    consts.append(branch["properties"]["kind"]["const"])
                assert consts == list(KINDS[name])
                result = await client.call_tool(name, {"request": _request(name)})
                assert not result.is_error
                payload = result.structured_content
                assert payload["ok"] and not payload["partial"]
            rejected = await client.call_tool(
                "CD_flow_qualify_iv_dataset",
                {"request": _request("CD_flow_qualify_iv_dataset", acquisition={"kind": "x"})},
                raise_on_error=False,
            )
            assert rejected.is_error

    asyncio.run(exercise())


def test_reference_docs_list_every_cd_flow_and_kind():
    catalog = (CATALOG / "cd-flows.md").read_text()
    for name in CD_NAMES + RESERVED:
        assert f"`{name}`" in catalog
    for name in CD_NAMES:
        for kind in KINDS[name]:
            assert f"`{kind}`" in catalog
    assert "cd-flows.md" in (CATALOG / "README.md").read_text()
    overview = (DOCS / "instrument-interaction-tools.md").read_text()
    assert "CD_flow_<operation>_<domain>_<subject>" in overview
    assert "CD_flow" in (ROOT / "README.md").read_text()


# ---------------------------------------------------------------------------
# Boundary and order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,kind", _cases())
def test_one_c_flow_its_d_flow_and_archive_in_phase_order(monkeypatch, name, kind):
    calls = _spy_children(monkeypatch)
    result = _run(name, _request(name, kind))
    c_name, d_name = f"C_flow_{kind}", name[1:]
    assert result["ok"] and not result["partial"], result.get("error")
    assert calls.count(c_name) == 1
    assert [c for c in calls if c.startswith("C_flow_")] == [c_name]
    assert [c for c in calls if c.startswith("D_flow_")] == [d_name, ARCHIVE]
    c_child = _child(result, c_name)
    assert [c for c in calls if c.startswith("C_atom_")] == c_child["result"]["atoms_called"]
    assert [(r["phase"], r["name"], r["kind"], r["status"]) for r in result["child_results"]] == [
        ("expect", EXPECT, "d_atom", "ok"),
        ("measure", c_name, "c_flow", "ok"),
        ("interpret", d_name, "d_flow", "ok"),
        ("interpret", ENVELOPE_ATOM, "d_atom", "skipped"),
        ("archive", ARCHIVE, "d_flow", "ok"),
    ]
    assert _child(result, ENVELOPE_ATOM)["optional"] is True
    assert result["flows_called"] == [c_name, d_name, ARCHIVE]
    assert (result["c_flow"], result["d_flow"]) == (c_name, d_name)
    direct = c_flows.C_FLOW_FUNCTIONS[[f.__name__ for f in c_flows.C_FLOW_FUNCTIONS].index(c_name)]
    expected_c = direct(KINDS[name][kind] or None)["atoms_called"]
    head = Q_CV_AFTER_EXPECT if name == "CD_flow_qualify_cv_dataset" else Q_IV_AFTER_EXPECT
    assert result["atoms_called"] == [
        EXPECT,
        *expected_c,
        *head,
        *D_TAIL[name],
        *ARCHIVE_ATOMS,
    ]
    d_child = _child(result, d_name)["result"]
    first = d_child["atom_results"][0]
    assert (first["atom"], first["status"], first["reason"], first["optional"]) == (
        EXPECT,
        "skipped",
        "expectation_supplied",
        True,
    )
    timestamps = [r["timestamp"] for r in result["child_results"]]
    assert timestamps == sorted(timestamps)
    assert list(result["phases"]) == ["expect", "measure", "interpret", "archive"]


def test_section_7_screen_staircase_sequence():
    result = _run(
        "CD_flow_screen_iv_leakage", _request("CD_flow_screen_iv_leakage", "sweep_smu_staircase")
    )
    assert result["atoms_called"] == [
        "D_atom_ingest_request_build_expectation",
        "C_atom_smu_configure_integration",
        "C_atom_smu_set_measurement_ranging",
        "C_atom_smu_set_measurement_mode",
        "C_atom_smu_configure_sweep_timing",
        "C_atom_smu_configure_sweep_abort",
        "C_atom_smu_configure_staircase_sweep",
        "C_atom_smu_execute",
        "C_atom_smu_read_measurement_data",
        *Q_IV_AFTER_EXPECT,
        "D_atom_extract_leakage_current",
        "D_atom_assess_value_check_limits",
        "D_atom_archive_run_build_manifest",
        "D_atom_archive_run_write_bundle",
    ]
    spot = _run("CD_flow_screen_iv_leakage", _request("CD_flow_screen_iv_leakage", "spot_smu_iv"))
    assert len(_child(spot, "C_flow_spot_smu_iv")["result"]["atoms_called"]) == 6


def test_c_flow_called_once_even_when_it_fails_or_d_reports_fail(monkeypatch):
    calls = _replace_c_flow(
        monkeypatch,
        "sweep_smu_staircase",
        lambda e: {**e, "ok": False, "execution_state": "failed"},
    )
    request = _request("CD_flow_screen_iv_leakage", "sweep_smu_staircase")
    failed = _run("CD_flow_screen_iv_leakage", request)
    assert calls == ["C_flow_sweep_smu_staircase"] and not failed["ok"]
    calls.clear()
    original = d_atoms.D_atom_assess_value_check_limits

    def failing(**kwargs):
        result = original(**kwargs)
        result["outputs"]["verdict"] = "fail"
        return result

    monkeypatch.setattr(d_atoms, "D_atom_assess_value_check_limits", failing)
    originals = {f.__name__: f for f in c_flows.C_FLOW_FUNCTIONS}
    monkeypatch.setattr(
        c_flows, "C_flow_sweep_smu_staircase", originals["C_flow_sweep_smu_staircase"]
    )
    counted = _replace_c_flow(monkeypatch, "sweep_smu_staircase", lambda e: e)
    screened = _run("CD_flow_screen_iv_leakage", request)
    assert counted == ["C_flow_sweep_smu_staircase"]
    # A D 'fail' on synthetic data is a taint violation, never a reason to re-measure.
    assert not screened["ok"] and screened["error"]["type"] == "taint_violation"
    assert screened["outputs"]["verdict"] is None
    assert _child(screened, ARCHIVE)["status"] == "ok"


# ---------------------------------------------------------------------------
# C execution states and the handoff gate
# ---------------------------------------------------------------------------


def _drop_read(envelope: dict) -> dict:
    changed = copy.deepcopy(envelope)
    changed["atom_results"] = [
        r for r in changed["atom_results"] if r["atom"] != "C_atom_smu_read_measurement_data"
    ]
    return changed


def _with_rows(envelope: dict) -> dict:
    changed = copy.deepcopy(envelope)
    changed["atom_results"][-1]["result"]["parameters"]["rows"] = [1e-12, 2e-12]
    return changed


STATE_CASES = {
    "configuration_only": (
        lambda e: {**e, "execution_state": "configuration_only", "partial": True, "contract_gaps": ["Injected gap."]},
        {"ok": True, "partial": True, "state": "no_data", "reason": "c_configuration_only", "interpret": False, "archive": True},
    ),
    "awaiting_completion": (
        lambda e: {**e, "execution_state": "awaiting_completion", "partial": True, "warnings": [*e["warnings"], "Started/unknown completion is not completion; hand off to the outer A/ABC layer."]},
        {"ok": True, "partial": True, "state": "pending", "reason": "c_awaiting_completion", "interpret": False, "archive": True},
    ),
    "failed": (
        lambda e: {**e, "ok": False, "partial": True, "execution_state": "failed"},
        {"ok": False, "partial": True, "state": "no_data", "reason": "c_failed", "interpret": False, "archive": True},
    ),
    "no_read_record": (
        _drop_read,
        {"ok": True, "partial": True, "state": "no_data", "reason": "c_no_data_record", "interpret": False, "archive": True},
    ),
    "rows_received": (
        _with_rows,
        {"ok": True, "partial": False, "state": "received", "reason": None, "interpret": True, "archive": True},
    ),
    "fake_false": (
        lambda e: {**e, "fake": False},
        {"ok": False, "partial": True, "state": "no_data", "reason": "c_unexpected_marker", "interpret": False, "archive": False},
    ),
    "hardware_touched": (
        lambda e: {**e, "hardware_touched": True},
        {"ok": False, "partial": True, "state": "no_data", "reason": "c_unexpected_marker", "interpret": False, "archive": False},
    ),
}  # fmt: skip


@pytest.mark.parametrize("case", list(STATE_CASES))
def test_c_execution_states_gate_interpretation(monkeypatch, case):
    transform, expected = STATE_CASES[case]
    _replace_c_flow(monkeypatch, "sweep_smu_staircase", transform)
    result = _run(
        "CD_flow_screen_iv_leakage", _request("CD_flow_screen_iv_leakage", "sweep_smu_staircase")
    )
    assert result["ok"] is expected["ok"] and result["partial"] is expected["partial"]
    assert result["handoff"]["state"] == expected["state"]
    assert result["handoff"]["reason"] == expected["reason"]
    assert result["handoff"]["child_index"] == 1
    d_child = _child(result, "D_flow_screen_iv_leakage")
    archive = _child(result, ARCHIVE)
    assert (d_child["status"] == "ok") is expected["interpret"]
    assert (archive["status"] == "ok") is expected["archive"]
    if not expected["interpret"]:
        assert d_child["reason"] == expected["reason"] and d_child["optional"] is False
        assert result["analysis_state"] == "not_run"
        assert result["outputs"]["verdict"] is None and result["outputs"]["trust_level"] is None
        assert result["audit"]["skip_reasons"]["D_flow_screen_iv_leakage"] == expected["reason"]
    if not expected["archive"]:
        assert archive["reason"] == "c_unexpected_marker"
        assert result["error"]["type"] == "unexpected_marker"
        assert result["outputs"]["archive"]["manifest_ref"] is None
    else:
        planned = result["outputs"]["archive"]
        assert planned["write_refusal"] == ["fake_mode", "synthetic_origin"]
        manifest_inputs = archive["result"]["atom_results"][0]["inputs"]["envelopes"]
        assert manifest_inputs[:2] == [EXPECT, "C_flow_sweep_smu_staircase"]
    if case == "configuration_only":
        assert "Injected gap." in result["contract_gaps"]
    if case == "awaiting_completion":
        assert any("Started/unknown completion" in w for w in result["warnings"])
    if case == "failed":
        assert result["error"] == {
            "type": "c_failed",
            "message": result["error"]["message"],
            "at": "C_flow_sweep_smu_staircase",
        }
    if case == "no_read_record":
        assert any("designated read record" in gap for gap in result["contract_gaps"])
    if case == "rows_received":
        assert result["handoff"]["element_count"] == 2
        assert df.EMPTY_DATA_WARNING not in result["warnings"]
    assert result["cleanup"]["performed"] is False
    json.dumps(result, allow_nan=False)


def test_real_pending_and_failed_c_runs(monkeypatch):
    monkeypatch.setattr(
        c_atoms,
        "C_atom_smu_execute",
        lambda **_: {
            "fake": True,
            "hardware_touched": False,
            "parameters": {"status": "fake_started"},
        },
    )
    pending = _run(
        "CD_flow_qualify_iv_dataset", _request("CD_flow_qualify_iv_dataset", "sweep_smu_staircase")
    )
    assert (
        pending["execution_state"] == "awaiting_completion" and pending["ok"] and pending["partial"]
    )
    assert pending["handoff"]["state"] == "pending"
    assert _child(pending, ARCHIVE)["status"] == "ok"

    def raise_(**_):
        raise RuntimeError("injected atom failure")

    monkeypatch.setattr(c_atoms, "C_atom_smu_execute", raise_)
    failed = _run(
        "CD_flow_qualify_iv_dataset", _request("CD_flow_qualify_iv_dataset", "sweep_smu_staircase")
    )
    assert failed["execution_state"] == "failed" and not failed["ok"]
    assert failed["handoff"]["reason"] == "c_failed"
    assert _child(failed, ARCHIVE)["status"] == "ok"


@pytest.mark.parametrize("returned", ["exception", "non_dict"])
def test_c_flow_exception_is_c_failed_and_archive_still_runs(monkeypatch, returned):
    def broken(**kwargs):
        if returned == "exception":
            raise RuntimeError("injected C flow failure")
        return ["not", "a", "dict"]

    monkeypatch.setattr(c_flows, "C_flow_spot_smu_iv", broken)
    result = _run(
        "CD_flow_qualify_iv_dataset", _request("CD_flow_qualify_iv_dataset", "spot_smu_iv")
    )
    assert not result["ok"] and result["partial"]
    assert result["execution_state"] == "failed"
    assert result["error"]["type"] == "c_failed"
    measure = _child(result, "C_flow_spot_smu_iv")
    assert measure["status"] == "error" and measure["result"] is None and measure["timestamp"]
    assert _child(result, "D_flow_qualify_iv_dataset")["reason"] == "c_failed"
    archive = _child(result, ARCHIVE)
    assert archive["status"] == "ok"
    assert archive["input_refs"]["envelopes"] == [{"child_index": 0, "name": EXPECT}]
    assert result["cleanup"]["owner"] == "outer_ABC_transaction"


def test_config_record_keyed_measurement_is_never_data(monkeypatch):
    high_speed = c_flows.C_flow_spot_smu_high_speed()
    assert high_speed["outputs"]["data"]  # the C scrape lists a configuration record
    _replace_c_flow(
        monkeypatch,
        "spot_smu_iv",
        lambda e: {
            **high_speed,
            "category": e["category"],
            "subject": e["subject"],
            "flow": e["flow"],
        },
    )
    result = _run(
        "CD_flow_qualify_iv_dataset", _request("CD_flow_qualify_iv_dataset", "spot_smu_iv")
    )
    assert result["handoff"]["state"] == "no_data"
    assert result["handoff"]["reason"] == "c_no_data_record"
    assert _child(result, "D_flow_qualify_iv_dataset")["status"] == "skipped"


def test_empty_rows_give_empty_handoff_warning_and_interpretation(results):
    for (name, kind), result in results.items():
        assert result["handoff"]["state"] == "empty", (name, kind)
        assert result["handoff"]["element_count"] == 0
        assert result["handoff"]["source_atom"] in {
            "C_atom_smu_read_measurement_data",
            "C_atom_cmu_read_measurement_data",
        }
        assert df.EMPTY_DATA_WARNING in result["warnings"]
        assert result["execution_state"] == "simulated_complete"
        assert result["simulation_completed"] is True and result["measurement_completed"] is False
        assert _child(result, name[1:])["status"] == "ok"
        refs = _child(result, name[1:])["input_refs"]
        assert refs["evidence.c_flow_envelope"]["child_index"] == 1
        assert refs["evidence.c_flow_envelope"]["atom_index"] == result["handoff"]["atom_index"]


# ---------------------------------------------------------------------------
# Expect phase
# ---------------------------------------------------------------------------


def test_expect_failure_stops_before_measuring(monkeypatch):
    calls = _spy_children(monkeypatch)
    monkeypatch.setattr(
        d_atoms,
        EXPECT,
        lambda **kwargs: {
            "atom": EXPECT,
            "fake": True,
            "hardware_touched": False,
            "ok": False,
            "analysis_state": "rejected_input",
            "data_origin": "synthetic",
            "outputs": {"product": None},
            "error": {"type": "rejected_input", "message": "injected"},
        },
    )
    result = _run("CD_flow_screen_iv_leakage", _request("CD_flow_screen_iv_leakage"))
    assert not [c for c in calls if c.startswith(("C_flow_", "C_atom_", "D_flow_"))]
    assert not result["ok"] and result["partial"]
    assert result["execution_state"] == "not_run" and result["analysis_state"] == "not_run"
    assert result["error"] == {
        "type": "rejected_input",
        "message": result["error"]["message"],
        "at": EXPECT,
    }
    statuses = [(r["name"], r["status"], r["reason"]) for r in result["child_results"]]
    assert statuses[0] == (EXPECT, "error", None)
    assert all(
        status == "skipped" and reason == "earlier_failure" for _, status, reason in statuses[1:]
    )
    assert result["outputs"]["archive"]["manifest_ref"] is None
    assert result["cleanup"]["owner"] == "none"


def test_expectation_is_built_before_measuring_and_handed_to_d(results):
    result = results[("CD_flow_qualify_iv_dataset", "sweep_smu_staircase")]
    expect = _child(result, EXPECT)
    expectation = expect["result"]["outputs"]["product"]
    d_child = _child(result, "D_flow_qualify_iv_dataset")
    assert d_child["input_refs"]["expectation"]["product_id"] == expectation["product_id"]
    products = d_child["result"]["outputs"]["products"]
    assert products["expectation"] == expectation
    assert products["dataset"]["upstream"] == [expectation["product_id"]]
    assert result["outputs"]["products"]["expectation"] == expectation


# ---------------------------------------------------------------------------
# Taint, labels and upstream evidence
# ---------------------------------------------------------------------------


def test_stub_norm_labels_and_ineligible_citation(results):
    for (name, kind), result in results.items():
        assert result["ok"] and not result["partial"], (name, kind)
        assert result["fake"] is True and result["hardware_touched"] is False
        assert result["data_origin"] == "synthetic" and result["synthetic"] is True
        assert result["analysis_state"] == "not_computed" and not result["analysis_completed"]
        outputs = result["outputs"]
        assert outputs["trust_level"] == "synthetic_only"
        if name == "CD_flow_screen_iv_leakage":
            assert outputs["verdict"] == "synthetic_only"
        else:
            assert outputs["verdict"] is None
        assert outputs["evidence_citation"]["eligible"] is False
        assert outputs["evidence_citation"]["blockers"] == [
            "synthetic_origin",
            "analysis_not_computed",
        ]
        assert outputs["escalations"] == []
        for record in result["child_results"]:
            if record["kind"] != "c_flow" and record["result"] is not None:
                assert not FORBIDDEN & {v for _, v in df.labels(record["result"])}, record["name"]


def test_injected_d_flow_pass_is_a_taint_violation_and_archive_still_runs(monkeypatch):
    original = df.D_flow_screen_iv_leakage

    def passing(**kwargs):
        result = original(**kwargs)
        result["outputs"]["verdict"] = "pass"
        return result

    monkeypatch.setattr(df, "D_flow_screen_iv_leakage", passing)
    result = _run("CD_flow_screen_iv_leakage", _request("CD_flow_screen_iv_leakage", envelope={"limits": [{"quantity": "current", "high": _q(1e-3, "A")}], "criteria_source": SOURCE}))  # fmt: skip
    assert not result["ok"] and result["partial"]
    assert result["error"]["type"] == "taint_violation"
    assert result["error"]["at"] == "D_flow_screen_iv_leakage"
    assert result["outputs"]["verdict"] is None and result["outputs"]["trust_level"] is None
    assert _child(result, "D_flow_screen_iv_leakage")["result"]["outputs"]["verdict"] == "pass"
    assert _child(result, ENVELOPE_ATOM)["reason"] == "taint_violation"
    assert _child(result, ARCHIVE)["status"] == "ok"
    assert any(f["code"] == "taint_violation" for f in result["findings"])
    assert result["analysis_state"] == "rejected_input"


@pytest.mark.parametrize(
    "atom,key,value",
    [
        ("D_atom_assess_value_check_limits", "verdict", "pass"),
        ("D_atom_qualify_dataset_grade_trust", "trust_level", "trusted"),
    ],
)
def test_injected_atom_pass_inside_d_fails_cd_and_archive_runs(monkeypatch, atom, key, value):
    original = getattr(d_atoms, atom)

    def tainted(**kwargs):
        result = original(**kwargs)
        result["outputs"][key] = value
        return result

    monkeypatch.setattr(d_atoms, atom, tainted)
    result = _run("CD_flow_screen_iv_leakage", _request("CD_flow_screen_iv_leakage"))
    assert not result["ok"] and result["error"]["type"] == "taint_violation"
    d_child = _child(result, "D_flow_screen_iv_leakage")
    assert d_child["status"] == "error" and d_child["result"]["error"]["at"] == atom
    assert _child(result, ARCHIVE)["status"] == "ok"
    assert result["outputs"]["verdict"] is None


def test_d_marker_stops_everything(monkeypatch):
    original = d_atoms.D_atom_qualify_dataset_classify_status

    def marked(**kwargs):
        return {**original(**kwargs), "hardware_touched": True}

    monkeypatch.setattr(d_atoms, "D_atom_qualify_dataset_classify_status", marked)
    result = _run("CD_flow_qualify_iv_dataset", _request("CD_flow_qualify_iv_dataset"))
    assert not result["ok"] and result["error"]["type"] == "unexpected_marker"
    assert result["hardware_touched"] is True
    assert _child(result, ARCHIVE)["status"] == "skipped"
    assert _child(result, ARCHIVE)["reason"] == "unexpected_marker"


def test_archive_failure_is_ok_false_partial_and_keeps_earlier_children(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("injected archive failure")

    monkeypatch.setattr(d_atoms, "D_atom_archive_run_write_bundle", broken)
    request = _request("CD_flow_screen_iv_leakage", "sweep_smu_staircase")
    result = _run("CD_flow_screen_iv_leakage", request)
    assert result["ok"] is False and result["partial"] is True
    assert result["error"]["at"] == ARCHIVE and result["error"]["type"] == "internal_error"
    archive = _child(result, ARCHIVE)
    assert archive["status"] == "error" and archive["result"]["ok"] is False
    for name in (EXPECT, "C_flow_sweep_smu_staircase", "D_flow_screen_iv_leakage"):
        assert _child(result, name)["status"] == "ok", name
    assert result["outputs"]["verdict"] == "synthetic_only"
    assert result["outputs"]["archive"]["manifest_ref"] is None
    assert result["outputs"]["archive"]["artifact_written"] is False
    json.dumps(result, allow_nan=False)


def test_subchannel_number_from_table_4_1_is_a_valid_role_channel():
    request = _request(
        "CD_flow_qualify_iv_dataset",
        "spot_smu_iv",
        channel_roles=[{"channel": 101, "terminal": "gate"}],
    )
    request["acquisition"]["request"]["channel"] = 101
    result = _run("CD_flow_qualify_iv_dataset", request)
    assert result["ok"] and not result["partial"], result.get("error")
    assert result["handoff"]["state"] == "empty"


def test_upstream_ab_evidence_is_forwarded_unverified_and_fully_archived():
    upstream = [
        {"flow": "B_flow_preflight_b1500_gate", "fake": False, "ok": True},
        *[{"flow": "A_flow_drain_flex_errors", "fake": True, "ok": True, "n": i} for i in range(5)],
    ]
    result = _run(
        "CD_flow_screen_iv_leakage",
        _request("CD_flow_screen_iv_leakage", upstream_evidence=upstream),
    )
    assert result["ok"] and result["data_origin"] == "synthetic"
    assert result["outputs"]["trust_level"] == "synthetic_only"
    d_child = _child(result, "D_flow_screen_iv_leakage")["result"]
    codes = {(f["source_atom"], f["code"]) for f in d_child["findings"]}
    assert ("D_atom_qualify_run_check_context", "evidence_unverified") in codes
    assert any(f.get("code") == "evidence_unverified" for f in result["findings"])
    required = result["required_preconditions"]
    assert "B_flow_preflight_b1500_gate" in required and "A_flow_drain_flex_errors" in required
    archive = _child(result, ARCHIVE)
    refs = archive["input_refs"]["envelopes"]
    assert len(refs) == 3 + len(upstream) and refs[-1] == "inputs.upstream_evidence[5]"
    assert not any("envelope cap" in t for t in [*result["contract_gaps"], *result["warnings"]])
    assert result["inputs"]["upstream_evidence"] == upstream


def test_largest_cd_run_archives_every_envelope_within_the_derived_cap():
    """The manifest cap is derived from the CD maximums, so nothing is ever dropped."""
    cap = d_schema.MAX_ARCHIVE_ENVELOPES
    assert cap == (
        d_schema.CD_ARCHIVED_C_FLOWS
        + d_schema.CD_ARCHIVED_D_CHILDREN
        + d_schema.MAX_UPSTREAM_EVIDENCE
    )
    upstream = [
        {"flow": "A_flow_drain_flex_errors", "fake": True, "n": i}
        for i in range(d_schema.MAX_UPSTREAM_EVIDENCE)
    ]
    envelope = {
        "limits": [{"quantity": "current", "high": _q(1e-3, "A")}],
        "criteria_source": SOURCE,
    }
    result = _run(
        "CD_flow_screen_iv_leakage",
        _request("CD_flow_screen_iv_leakage", upstream_evidence=upstream, envelope=envelope),
    )
    assert result["ok"] and not result["partial"], result.get("error")
    archived = [
        r for r in result["child_results"] if r["phase"] != "archive" and r["status"] == "ok"
    ]
    assert len([r for r in archived if r["kind"] == "c_flow"]) == d_schema.CD_ARCHIVED_C_FLOWS
    assert len([r for r in archived if r["kind"] != "c_flow"]) == d_schema.CD_ARCHIVED_D_CHILDREN
    archive = _child(result, ARCHIVE)
    assert archive["status"] == "ok"
    refs = archive["input_refs"]["envelopes"]
    assert len(refs) == cap and refs[-1] == f"inputs.upstream_evidence[{len(upstream) - 1}]"
    manifest = archive["result"]["atom_results"][0]
    assert manifest["atom"] == "D_atom_archive_run_build_manifest"
    assert len(manifest["inputs"]["envelopes"]) == cap
    assert not any("envelope cap" in t for t in [*result["contract_gaps"], *result["warnings"]])


def test_envelope_audit_atom_runs_after_interpret_when_declared():
    envelope = {
        "limits": [{"quantity": "current", "terminal": "gate", "high": _q(1e-3, "A")}],
        "criteria_source": SOURCE,
    }
    result = _run(
        "CD_flow_qualify_iv_dataset", _request("CD_flow_qualify_iv_dataset", envelope=envelope)
    )
    assert result["ok"] and not result["partial"]
    names = [r["name"] for r in result["child_results"]]
    assert names.index(ENVELOPE_ATOM) == names.index("D_flow_qualify_iv_dataset") + 1
    record = _child(result, ENVELOPE_ATOM)
    assert record["phase"] == "interpret" and record["status"] == "ok"
    dataset = result["outputs"]["products"]["dataset"]
    assert record["input_refs"]["dataset"]["product_id"] == dataset["product_id"]
    assert record["result"]["outputs"]["verdict"] == "synthetic_only"
    assert result["outputs"]["escalations"] == []
    assert ENVELOPE_ATOM in result["atoms_called"]


# ---------------------------------------------------------------------------
# Validators: zero child calls
# ---------------------------------------------------------------------------


def _set(request: dict, path: str, value) -> dict:
    changed = copy.deepcopy(request)
    node = changed
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = int(keys[-1]) if isinstance(node, list) else keys[-1]
    if value is ...:
        del node[last]
    else:
        node[last] = value
    return changed


def _invalid_cases():
    q, s = "CD_flow_qualify_iv_dataset", "CD_flow_screen_iv_leakage"
    t, c = "CD_flow_analyze_iv_transfer", "CD_flow_qualify_cv_dataset"
    qr, sr, tr, cr = (
        _request(q, "sweep_smu_staircase"),
        _request(s, "sweep_smu_staircase"),
        _request(t),
        _request(c),
    )
    spot = _request(s, "spot_smu_iv")
    return [
        (q, _set(qr, "acquisition.request.run", {"collect": False}), "collect"),
        (q, _set(qr, "acquisition.request.run", {"max_items": 5}), "max_items"),
        (q, _set(qr, "acquisition.request.steps", 200), "max_items"),
        (q, _set(qr, "channel_roles", [{"channel": 2, "terminal": "gate"}]), "no declared role"),
        (q, _set(qr, "channel_roles", [*GATE, {"channel": 2, "terminal": "drain"}]), "does not use"),
        (q, _set(qr, "channel_roles", GATE * 2), "each channel once"),
        (q, _set(qr, "channel_roles", []), "channel_roles"),
        (q, _set(qr, "acquisition.kind", "sweep_smu_synchronous"), "sweep_smu_synchronous"),
        (q, _set(_set(qr, "acquisition.request", {"steps": 11}), "acquisition.kind", "spot_smu_iv"), "steps"),
        (q, _set(qr, "acquisition.kind", ...), "kind"),
        (q, _set(qr, "acquisition.request", ...), "request"),
        (q, _set(qr, "acquisition", ...), "acquisition"),
        (q, _set(qr, "measurement", {}), "measurement"),
        (q, _set(qr, "upstream_evidence", [{"flow": "A_flow_x"}] * 17), "upstream_evidence"),
        (q, _set(qr, "upstream_evidence", [{"fake": True, "ok": True}]), "names no tool"),
        (q, _set(qr, "envelope", {"limits": [{"quantity": "current", "high": _q(1.0, "V")}], "criteria_source": SOURCE}), "bounds must be in A"),
        (q, _set(qr, "envelope", {"limits": [{"quantity": "current", "terminal": "drain", "high": _q(1.0, "A")}], "criteria_source": SOURCE}), "not a declared role"),
        (q, _set(qr, "envelope", {"limits": [{"quantity": "current", "high": _q(1.0, "A")}]}), "criteria_source"),
        (s, _set(sr, "acquisition.request.source", "current"), "voltage source"),
        (s, _set(sr, "acquisition.request.ranging", {"measure_function": "voltage"}), "measure_function"),
        (s, _set(sr, "leakage.terminal", "drain"), "role of the measured channel"),
        (s, _set(sr, "leakage.bias_points_v", [2.0]), "not within"),
        (s, _set(spot, "leakage.bias_points_v", [0.5]), "spot level"),
        (s, _set(sr, "leakage.criteria", _criteria(1e-3)), "CD11"),
        (s, _set(sr, "leakage.criteria", [{"parameter": "leakage_current", "comparator": "within", "limit": _q(1e-12, "A"), "limit_high": _q(2e-3, "A")}]), "CD11"),
        (s, _set(sr, "leakage.criteria", ...), "criteria"),
        (s, _set(sr, "leakage.criteria_source", ...), "criteria_source"),
        (s, _set(sr, "leakage.criteria.0.limit.unit", "V"), "unit 'V'"),
        (s, _set(sr, "acquisition.kind", "pulse_smu_spot"), "pulse_smu_spot"),
        (s, _set(sr, "leakage", ...), "leakage"),
        (t, _set(tr, "transfer.gate_terminal", "source"), "swept channel"),
        (t, _set(tr, "channel_roles", [ROLES3[0], {"channel": 2, "terminal": "source"}, {"channel": 3, "terminal": "drain"}]), "measured"),
        (t, _set(tr, "transfer.vds", _q(0.1, "V")), "drain bias"),
        (t, _set(tr, "acquisition.request.bias_channels.0", {"channel": 2, "source": "current", "level": 1e-6, "compliance": 1.0}), "voltage-biased"),
        (t, _set(tr, "acquisition.request.measured_channels.0", {"channel": 2, "ranging": {"measure_function": "voltage"}}), "measure_function"),
        (t, _set(tr, "acquisition.request.run", {"max_items": 20}), "max_items"),
        (t, _set(tr, "channel_roles", [*ROLES3, {"channel": 4, "terminal": "body"}]), "does not use"),
        (t, _set(tr, "acquisition.request.source", "current"), "voltage"),
        (t, _set(tr, "transfer.on_off.vg_on", _q(3.0, "V")), "outside the sweep"),
        (t, _set(tr, "transfer.vth", ...), "Vth method"),
        (t, _set(tr, "acquisition.kind", "sweep_smu_staircase"), "sweep_smu_staircase_biased"),
        (c, _set(cr, "imp_model", "Cs-Rs"), "imp_model"),
        (c, _set(cr, "imp_model", "C-G"), "imp_model"),
        (c, _set(cr, "acquisition", {"kind": "sweep_cmu_cf", "request": {"start": 0.0, "stop": 1e6}}), "positive"),
        (c, _set(cr, "acquisition", {"kind": "sweep_cmu_ac_level", "request": {"start": -0.1, "stop": 0.1}}), "positive"),
        (c, _set(cr, "acquisition", {"kind": "sampling_cmu_ct", "request": {}}), "sampling_cmu_ct"),
        (c, _set(cr, "channel_roles", GATE), "no declared role"),
    ]  # fmt: skip


@pytest.mark.parametrize("name,request_,match", _invalid_cases(), ids=lambda v: str(v)[:40])
def test_invalid_requests_fail_before_any_child_call(monkeypatch, name, request_, match):
    calls = _spy_children(monkeypatch)
    with pytest.raises(ValidationError, match=match):
        _run(name, request_)
    assert calls == []


# ---------------------------------------------------------------------------
# Archive (U2) and hygiene
# ---------------------------------------------------------------------------


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()}


def test_no_cd_flow_writes_a_file(tmp_path, monkeypatch):
    data_root = ROOT / "data"
    before_repo, before_tmp = _files(data_root), _files(tmp_path)
    monkeypatch.chdir(tmp_path)
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"CD flow attempted a file write: {file}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    outcomes = [_run(name, _request(name, kind)) for name, kind in _cases()]
    monkeypatch.undo()
    assert _files(data_root) == before_repo and _files(tmp_path) == before_tmp
    for result in outcomes:
        archive = result["outputs"]["archive"]
        assert archive["artifact_written"] is False
        assert archive["write_refusal"] == ["fake_mode", "synthetic_origin"]
        assert archive["manifest_ref"]["product_type"] == "manifest"
        assert archive["planned_paths"] and all(
            not p.startswith("/") and ".." not in p.split("/") for p in archive["planned_paths"]
        )
        assert result["side_effects"] == {
            "hardware": "none",
            "filesystem_writes": [],
            "artifact_written": False,
        }


def test_hygiene_banned_keys_c_records_once_and_determinism(results):
    for (name, kind), result in results.items():
        text = json.dumps(result, allow_nan=False)
        assert not set(result) & ds.BANNED_RESULT_KEYS
        assert not set(result["inputs"]) & ds.BANNED_RESULT_KEYS
        for _, key, _ in _walk(result["outputs"]):
            assert key not in ds.BANNED_RESULT_KEYS, (name, key)
        for record in result["child_results"]:
            if record["kind"] != "c_flow" and record["result"] is not None:
                for _, key, _ in _walk(record["result"]["outputs"]):
                    assert key not in ds.BANNED_RESULT_KEYS, (record["name"], key)
        c_child = _child(result, f"C_flow_{kind}")["result"]
        for record in c_child["atom_results"]:
            assert text.count(record["timestamp"]) == 1, (name, kind, record["atom"])
        assert result["cleanup"]["performed"] is False
        assert result["cleanup"]["owner"] == "outer_ABC_transaction"
        assert result["cleanup"]["analysis_side_effects"] == "none"
        assert result["destructive"] is True and result["consumptive"] is True
        assert result["audit"]["phase_order"] == ["expect", "measure", "interpret", "archive"]
        assert result["audit"]["consumptive_children"] == [f"C_flow_{kind}"]
        assert result["audit"]["child_count"] == 5
    for name in CD_NAMES:
        request = _request(name)
        assert _strip(_run(name, request)) == _strip(_run(name, request)), name


def test_module_imports_no_a_or_b_tools():
    import subprocess
    import sys

    code = (
        "import sys, json; import b1500_test_agent.mcp.cd_flows; "
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
    forbidden = ("a_atoms", "b_atoms", "a_flows", "b_flows", "ab_flows")
    assert not [m for m in loaded if m.rsplit(".", 1)[-1] in forbidden]
    assert not [m for m in loaded if m.startswith("b1500_test_agent.instruments")]
