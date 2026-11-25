"""``validate_plan``'s ``resolved`` block lists the switch routes per phase (blueprint v2 2.9; WP9.4 closes the gap
WP9.3 reported): an additive field, empty without switches, present over MCP and in the CLI text, and the responses of
the routed plans (the pulse_read card example, the selector check with one phase per step, a 10-cycle program/read
plan) stay within the 2k response budget (tiktoken ``o200k_base`` on the JSON a client receives)."""

from __future__ import annotations

import json
import warnings
from typing import Any

import pytest

from b1500_test_agent.adapters.cli.core import plan_lines
from b1500_test_agent.devtools import budget
from b1500_test_agent.service import RESPONSE_TOKEN_BUDGET, approx_tokens
from tests.adapters.helpers import call_tool, mcp_server
from tests.integration.helpers import IDVG, World

pytestmark = pytest.mark.spgu

WRITE_READ = {"recipe_id": "fefet.pulse_write_read", "pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
SELECTOR_CHECK = {"recipe_id": "system.selector_check", "pin_map": "open-smus"}


def tokens(payload: dict[str, Any]) -> int:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        counter = budget.load_counter()
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    count = counter.count(text) if counter.method.startswith("tiktoken") else approx_tokens(text)
    assert approx_tokens(text) >= count
    return count


def test_routes_per_phase_over_mcp_within_budget(world: World) -> None:
    world.use_scenario("fefet_lab")
    server = mcp_server(world)
    plan = call_tool(server, "validate_plan", **WRITE_READ)
    assert plan["tier"] == "needs_confirmation"
    assert plan["resolved"]["routes"] == {"erase": ["SEL1.OUT1->pgu"], "program": ["SEL1.OUT1->pgu"],
                                          "read": ["SEL1.OUT1->smu"], "rest": ["SEL1.OUT1->open"]}
    assert tokens(plan) <= RESPONSE_TOKEN_BUDGET
    long = call_tool(server, "validate_plan", **WRITE_READ, params={"cycles": 50, "sequence": "program_erase"})
    assert list(long["resolved"]["routes"]) == ["program", "erase", "read", "rest"]  # per phase, not per cycle
    assert tokens(long) <= RESPONSE_TOKEN_BUDGET


def test_the_selector_check_lists_every_step_within_budget(world: World) -> None:
    world.use_scenario("lab_station")
    plan = call_tool(mcp_server(world), "validate_plan", **SELECTOR_CHECK)
    routes = plan["resolved"]["routes"]
    assert routes and all(phase.startswith("check-") for phase in routes)
    assert routes["check-01"] == ["SEL1.OUT1->smu"]
    assert tokens(plan) <= RESPONSE_TOKEN_BUDGET


def test_plans_without_switches_have_no_routes(world: World) -> None:
    plan = call_tool(mcp_server(world), "validate_plan", **IDVG)
    assert plan["resolved"]["routes"] == {}


def test_cli_text_shows_the_routes(world: World) -> None:
    world.use_scenario("fefet_lab")
    validation = world.service().validate_plan(**WRITE_READ)
    lines = plan_lines(validation)
    assert ("routes: erase SEL1.OUT1->pgu; program SEL1.OUT1->pgu; read SEL1.OUT1->smu; rest SEL1.OUT1->open"
            in lines)
    assert not any(line.startswith("routes:") for line in plan_lines(world.service().validate_plan(**IDVG)))


@pytest.mark.parametrize("recipe_id", ["fefet.pulse_write_read"])
def test_resolved_routes_follow_routes_by_phase(recipe_id: str, world: World) -> None:
    world.use_scenario("fefet_lab")
    service = world.service()
    validation = service.validate_plan(**WRITE_READ, params={"sequence": "program_erase"})
    plan = world.executor().load_plan(validation.plan_id or "")
    assert validation.resolved is not None
    assert validation.resolved.routes == {p: [str(r) for r in items] for p, items in plan.routes_by_phase.items()}
