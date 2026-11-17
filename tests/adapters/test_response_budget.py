"""Tool responses stay within 2k tokens (blueprint 5.1), counted with tiktoken ``o200k_base`` on the JSON a client
receives; ``get_run`` downsamples data rows and ``list_runs`` trims entries to fit. Also checks that the service's
``approx_tokens`` never undercounts (it is the run-time guard, used without a tokenizer download)."""

from __future__ import annotations

import json
import warnings

import pytest

from b1500_test_agent.devtools import budget
from b1500_test_agent.service import RESPONSE_TOKEN_BUDGET, approx_tokens
from tests.adapters.helpers import call_tool, call_tools, mcp_server
from tests.integration.helpers import IDVG, World


@pytest.fixture(scope="module")
def count() -> budget.TokenCounter:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        counter = budget.load_counter()
    if not counter.method.startswith("tiktoken"):
        pytest.skip("o200k_base is not available offline; the chars/3.5 fallback cannot check JSON numbers")
    return counter


def check(counter: budget.TokenCounter, payload: dict) -> int:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tokens = counter.count(text)
    assert tokens <= RESPONSE_TOKEN_BUDGET, (tokens, text[:300])
    assert approx_tokens(text) >= tokens
    return tokens


def test_every_tool_response_fits(world: World, count: budget.TokenCounter) -> None:
    server = mcp_server(world)
    plan = call_tool(server, "validate_plan", **IDVG, params={"vg_points": 1001})
    assert plan["tier"] == "ok"
    run = call_tool(server, "run_plan", plan_id=plan["plan_id"])
    assert run["ok"], run["message"]
    run_id = run["run_id"]
    payloads = call_tools(server, [
        ("station_status", {}),
        ("list_recipes", {}),
        ("list_recipes", {"recipe_id": "mosfet.idvg"}),
        ("validate_plan", {**IDVG, "params": {"vg_stop": 60.0, "icomp_drain": 1.0}}),
        ("list_runs", {}),
        ("get_run", {"run_id": run_id}),
        ("get_run", {"run_id": run_id, "include": ["summary", "quality", "data", "audit", "notes"],
                     "max_points": 10000}),
        ("get_run", {"run_id": run_id, "include": ["data"], "max_points": 10000}),
        ("analyze_run", {"run_id": run_id, "method": "vth_linear_extrapolation"}),
        ("analyze_run", {"run_id": run_id, "method": "quality_report"}),
        ("annotate_run", {"run_id": run_id, "text": "x" * 2000}),
        ("safe_shutdown", {"reason": "budget"}),
    ])
    for payload in [plan, run, *payloads]:
        check(count, payload)
    data_only = payloads[7]["data"]
    assert data_only["rows_total"] == 1001 and 20 <= data_only["rows_returned"] < 1001
    everything = payloads[6]
    assert everything["data"]["rows_returned"] >= 10 and everything["audit"]


def test_list_runs_is_trimmed_to_the_budget(world: World, count: budget.TokenCounter) -> None:
    server = mcp_server(world)
    plan = call_tool(server, "validate_plan", **IDVG)
    run = call_tool(server, "run_plan", plan_id=plan["plan_id"])
    index = world.runs_dir / "index.jsonl"
    line = index.read_text(encoding="utf-8").splitlines()[0]
    entry = json.loads(line)
    with index.open("a", encoding="utf-8", newline="\n") as handle:
        for n in range(300):
            entry.update({"run_id": f"S20261117T{n:06d}Z-{n % 9999:04x}", "label": "batch " + "y" * 60,
                          "started_at": f"2026-11-17T{n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}+00:00"})
            handle.write(json.dumps(entry) + "\n")
    payload = call_tool(server, "list_runs", limit=200)
    check(count, payload)
    assert payload["total"] == 301 and 5 <= len(payload["runs"]) < 200
    assert payload["runs"][0]["run_id"] == run["run_id"]  # newest first


NOTES = ["测量完成，探针重新落针后漏电流正常。" * 20, "Vth = 0.4306 V; dVth < 5 mV, uA range, SIMULATED HRSMU " * 20,
         "S20261117T152235Z-5a8a,-1.000e+00,1.234e-12,N\n" * 30]


@pytest.mark.parametrize("text", NOTES)
def test_notes_of_any_script_stay_within_the_budget(world: World, count: budget.TokenCounter, text: str) -> None:
    server = mcp_server(world)
    plan = call_tool(server, "validate_plan", **IDVG)
    run = call_tool(server, "run_plan", plan_id=plan["plan_id"])
    for _ in range(4):
        assert call_tool(server, "annotate_run", run_id=run["run_id"], text=text[:2000])["ok"]
    payload = call_tool(server, "get_run", run_id=run["run_id"], include=["summary", "data", "notes"])
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert count.count(encoded) <= RESPONSE_TOKEN_BUDGET
    assert approx_tokens(text) >= 0.95 * count.count(text)  # within the 5 % trim headroom even for odd text
