"""The visa-loop recipe cases, collected from the suite's own tests (WP11.3; blueprint v2 8.1 ``visa_loop/``).

Every test of this suite whose name says it runs a recipe ``..._on_backend_visa...`` is parametrized over its cases
(a ``case`` dict with ``recipe_id``, ``scenario`` and ``request``, or a ``recipe_id`` whose case is a module-level
dict of the same module). ``collect_cases`` reads those parametrizations from the imported test modules, so the
registry coverage (``test_registry_coverage``) and the refusal check (``tests/safety/test_refusals_open_no_bus``)
see exactly the cases the suite runs; nothing is listed by hand.

``prepare`` applies the per-family configuration the suite's tests write before such a run (recorded selector wiring,
SCUU recorded present, the load standard, extra local files; the RSU "From SMU" inputs as the scenario cables them,
WP21.13) and ``correct`` the MFCMU corrections a C-V plan needs.
"""

from __future__ import annotations

import functools
import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.service import B1500Service

RUN_TEST_MARK = "_on_backend_visa"
"""The name part of every test that runs recipes on backend visa through ``VisaTransport``."""

FIXTURE_RECIPES = frozenset({"generic.smu_pulse_read"})
"""Test-only recipes (``tests/fixtures/recipes/``) some visa-loop cases run besides the registry's."""

SELECTOR_PIN_MAPS = frozenset({"fefet-sel", "mosfet-cp"})
"""Pin maps that reach a terminal through a 16440A selector: their runs need the wiring recorded (bring-up L7)."""

FUNCTION_FAMILY: dict[str, str | None] = {"pgu": "spgu", "wgfmu": "wgfmu", "cmu_high": "cmu", "cmu_low": "cmu",
                                          "ground": None}
"""Role function -> family path it drives (``None``: the ground unit); any other function is an SMU path."""


def recipe_families(recipe: Recipe) -> set[str]:
    """The family paths a recipe drives: its role functions', or for a recipe without roles (``system.*``, the
    selector check) the FLEX path, or the WGFMU library for kind ``system``'s ``wgfmu_*`` operations."""
    families = {FUNCTION_FAMILY.get(role.function, "smu") for role in recipe.roles.values()}
    if not recipe.roles:
        operation = recipe.params.get("operation")
        families.add("wgfmu" if operation is not None and str(operation.default).startswith("wgfmu") else "flex")
    return {f for f in families if f is not None}


@dataclass(frozen=True)
class VisaCase:
    """One recipe case of a visa-loop run test (``test``: ``module::function``)."""

    recipe_id: str
    case: dict[str, Any]
    test: str


def _parameter_sets(mark: Any) -> Iterator[dict[str, Any]]:
    argnames = mark.args[0]
    names = [a.strip() for a in argnames.split(",")] if isinstance(argnames, str) else list(argnames)
    for value in mark.args[1]:
        if isinstance(value, tuple) and hasattr(value, "marks"):  # pytest.param(...)
            values = tuple(value.values)
        else:
            values = tuple(value) if len(names) > 1 else (value,)
        yield dict(zip(names, values, strict=True))


def _module_case(module: Any, recipe_id: str) -> dict[str, Any] | None:
    for value in vars(module).values():
        if isinstance(value, dict) and value.get("recipe_id") == recipe_id and "request" in value:
            return value
    return None


@functools.cache
def collect_cases() -> tuple[VisaCase, ...]:
    """Every recipe case of every visa-loop run test (module docstring), in module order."""
    found: list[VisaCase] = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        module = importlib.import_module(f"tests.visa_loop.{path.stem}")
        for name, function in vars(module).items():
            if not (name.startswith("test_") and RUN_TEST_MARK in name and callable(function)):
                continue
            for mark in getattr(function, "pytestmark", []):
                if mark.name != "parametrize":
                    continue
                for params in _parameter_sets(mark):
                    case = params.get("case")
                    if isinstance(case, dict) and "recipe_id" in case:
                        found.append(VisaCase(case["recipe_id"], case, f"{path.stem}::{name}"))
                    elif isinstance(params.get("recipe_id"), str):
                        module_case = _module_case(module, params["recipe_id"])
                        assert module_case is not None, f"{path.stem}::{name}: no case for {params['recipe_id']}"
                        found.append(VisaCase(params["recipe_id"], module_case, f"{path.stem}::{name}"))
    return tuple(found)


def case_of(recipe_id: str) -> VisaCase:
    """The first collected case of ``recipe_id``."""
    for found in collect_cases():
        if found.recipe_id == recipe_id:
            return found
    raise LookupError(f"no visa-loop case runs {recipe_id}")


def prepare(world: Any, recipe: Recipe, case: dict[str, Any]) -> None:
    """Write the configuration the suite's tests write before running ``case`` (module docstring)."""
    from tests.sim.selector_helpers import recorded_station
    from tests.visa_loop.test_cmu_correction_visa import with_load_standard
    from tests.visa_loop.test_cv_visa import scuu_station

    request = case.get("request", {})
    if request.get("pin_map") in SELECTOR_PIN_MAPS or recipe.id == "system.selector_check":
        world.write_local("station.yaml", recorded_station())
    elif case.get("scuu") or request.get("pin_map") == "moscap-scuu":
        world.write_local("station.yaml", scuu_station())
    elif recipe.kind == "cmu_correction":
        with_load_standard(world)
    for rel, data in case.get("config", {}).items():
        world.write_local(rel, data)
    # The RSU inputs as bring-up L8 records them (the search suite does: R-RSU-01 blocks its 30 V BDV while unknown).
    world.record_rsu_inputs(case["scenario"])


def correct(service: B1500Service, recipe: Recipe, case: dict[str, Any]) -> None:
    """Run the MFCMU corrections a ``cmu_measure`` plan needs (R-CORR-01), as the C-V tests do."""
    if recipe.kind == "cmu_measure":
        from tests.visa_loop.test_cv_visa import correct as run_corrections

        run_corrections(service, case["request"]["pin_map"], case.get("corrections"))


def registry() -> RecipeRegistry:
    from tests.visa_loop.helpers import REPO_ROOT

    return RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
