"""Kind ``spgu_pulse``, mode ``route_only`` (``catalog/kinds/spgu_pulse.py``; WP9.2): the compiled selector check
(steps, one route per phase, allowed routes, the FLEX preview of its writes, estimate), its refusals, and the
card-lint hook for the routes the kind sets by itself."""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.catalog.kinds import default_kinds
from b1500_test_agent.catalog.kinds.spgu_pulse import SpguPulseKind, check_sequence
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.devtools.skills.cards import recipe_routes
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import ChannelBinding
from b1500_test_agent.models.routing import SELECTOR_SETTLE_S, Route
from b1500_test_agent.models.station import StationProfile
from tests.sim.helpers import REPO_ROOT
from tests.sim.selector_helpers import SEL1, SEL2, recorded_station

KIND = SpguPulseKind()
REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
RECIPE = REGISTRY.get("system.selector_check")
STATION = StationProfile.model_validate(recorded_station())
BINDING = ChannelBinding(pin_map="fefet-sel", roles={})


def params(**values: Any) -> dict[str, Quantity]:
    base: dict[str, Any] = {"mode": "route_only", "pgu_open": True, "dwell_s": 0.5, **values}
    return {name: Quantity(value=value, unit="s" if name == "dwell_s" else None) for name, value in base.items()}


def test_the_kind_is_registered_on_both_backends() -> None:
    assert isinstance(default_kinds()["spgu_pulse"], SpguPulseKind)
    assert KIND.implemented_on == frozenset({"sim", "visa"})
    assert REGISTRY.effective_status("system.selector_check", "sim") == "sim_validated"


def test_each_output_steps_through_its_states_one_phase_each() -> None:
    plan = KIND.compile(RECIPE, params(), BINDING, STATION)
    steps = plan.program["steps"]
    assert [(s["switch"], s["output"], s["port"], s["state"]) for s in steps] == [  # type: ignore[index, union-attr]
        ("SEL1", "OUT1", 0, "smu"), ("SEL1", "OUT1", 0, "pgu"), ("SEL1", "OUT1", 0, "pgu_open"),
        ("SEL1", "OUT1", 0, "open"), ("SEL1", "OUT2", 1, "smu"), ("SEL1", "OUT2", 1, "pgu"),
        ("SEL1", "OUT2", 1, "open"), ("SEL2", "OUT1", 2, "smu"), ("SEL2", "OUT1", 2, "pgu"),
        ("SEL2", "OUT1", 2, "pgu_open"), ("SEL2", "OUT1", 2, "open"), ("SEL2", "OUT2", 3, "smu"),
        ("SEL2", "OUT2", 3, "pgu"), ("SEL2", "OUT2", 3, "open")]
    assert list(plan.routes_by_phase) == [f"check-{i:02d}" for i in range(1, 15)]
    assert all(len(routes) == 1 for routes in plan.routes_by_phase.values())
    assert plan.envelope.channels == {}  # no source: the guard refuses CN and every level
    assert plan.envelope.routes == {Route(switch=s, output=o, state=st) for s, o, st in [
        ("SEL1", "OUT1", "smu"), ("SEL1", "OUT1", "pgu"), ("SEL1", "OUT1", "pgu_open"), ("SEL1", "OUT2", "smu"),
        ("SEL1", "OUT2", "pgu"), ("SEL2", "OUT1", "smu"), ("SEL2", "OUT1", "pgu"), ("SEL2", "OUT1", "pgu_open"),
        ("SEL2", "OUT2", "smu"), ("SEL2", "OUT2", "pgu")]}
    assert plan.flex_preview[:6] == ["ERMOD 1", "ERSSP 0,1", "ERMOD 1", "ERSSP 0,2", "ERMOD 1", "ERSSP 0,3"]
    assert len(plan.flex_preview) == 28 and not [line for line in plan.flex_preview if "?" in line]  # writes only
    assert plan.estimate.points == 0
    assert plan.estimate.duration_s == pytest.approx(14 * (SELECTOR_SETTLE_S + 0.5 + 0.05))
    assert plan.estimate.max_segment_s == pytest.approx(SELECTOR_SETTLE_S + 0.5 + 0.05)
    assert plan.program["sequence"] == ("SEL1.OUT1 smu,pgu,pgu_open,open; SEL1.OUT2 smu,pgu,open; "
                                       "SEL2.OUT1 smu,pgu,pgu_open,open; SEL2.OUT2 smu,pgu,open")


def test_pgu_open_off_and_a_non_open_rest_state() -> None:
    plan = KIND.compile(RECIPE, params(pgu_open=False), BINDING, STATION)
    assert all(s["state"] != "pgu_open" for s in plan.program["steps"])  # type: ignore[index, union-attr]
    smu_rest = SEL1.model_copy(update={"rest": "smu"})
    assert check_sequence(smu_rest, "OUT1", pgu_open=True) == ["pgu", "pgu_open", "open", "smu"]
    assert check_sequence(SEL2, "OUT2", pgu_open=True) == ["smu", "pgu", "open"]  # CH 2: no PGU open


def test_absent_selectors_are_skipped_and_none_left_is_a_compile_error() -> None:
    one = STATION.model_copy(update={"switches": [s.model_copy(update={"present": False}) if s.id == "SEL2" else s
                                                  for s in STATION.switches]})
    plan = KIND.compile(RECIPE, params(), BINDING, one)
    assert {s["switch"] for s in plan.program["steps"]} == {"SEL1"}  # type: ignore[union-attr, index]
    none = STATION.model_copy(update={"switches": [s for s in STATION.switches if s.kind != "selector_16440a"]})
    with pytest.raises(CompileError, match="declares no 16440A selector"):
        KIND.compile(RECIPE, params(), BINDING, none)


@pytest.mark.parametrize(("change", "message"), [
    ({"mode": "free_run"}, "mode must be one of"),  # pg and alwg exist since WP9.3
    ({"pgu_open": "yes"}, "pgu_open must be a bool"),
    ({"dwell_s": 61.0}, "dwell_s must be"),
])
def test_bad_parameters_are_compile_errors(change: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        KIND.compile(RECIPE, params(**change), BINDING, STATION)


def test_a_route_only_recipe_has_no_roles() -> None:
    with_role = RECIPE.model_copy(update={"roles": REGISTRY.get("mosfet.idvg").roles})
    with pytest.raises(CompileError, match="no DUT roles"):
        KIND.compile(with_role, params(), BINDING, STATION)


def test_checkpoints_and_card_routes() -> None:
    plan = KIND.compile(RECIPE, params(), BINDING, STATION)

    class Plan:
        program = plan.program

    assert KIND.checkpoint_total(Plan()) == 14  # type: ignore[arg-type]
    assert recipe_routes(RECIPE) == set()  # no role: no route from a resource
    assert recipe_routes(RECIPE, KIND) == {"selector_16440a:smu", "selector_16440a:pgu", "selector_16440a:pgu_open"}
