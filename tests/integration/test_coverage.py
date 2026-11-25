"""Coverage closure (WP11.2; blueprint v2 0 row 1, 1.2, 3, 9 "Docs" ``coverage.md``, "Delete when done").

- ``docs/coverage.md`` is current and the coverage has no gap (``b1500 dev coverage --check`` in the gate);
- every in-scope mode of ``devtools.coverage.MODES`` is reached: the named recipe's compiled plan shows it;
- the gap checks fire (an open ledger entry, a rule in no table, a recipe whose stage file does not run it);
- the v1 reserved machinery is gone: no ``not_implemented`` status, slot, kind or card anywhere in the live tree.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.catalog.kinds import default_kinds
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools import coverage
from b1500_test_agent.models.common import ErrorCode, ResultStatus, ValidationStatus
from b1500_test_agent.models.plan import PlanRecord, PlanRequest
from b1500_test_agent.models.run import RunOutcome
from tests.integration.helpers import REPO_ROOT, World

PROBES: dict[str, tuple[str, str, str | None, dict[str, Any]]] = {
    "spot (MM 1)": ("resistor_100k", "resistor-2t", "resistor-generic", {}),
    "staircase sweep (MM 2; WV/WI, WSV/WSI)": ("nmos_basic", "mosfet-4t", "nmos-generic", {}),
    "multi-channel sweep (MM 16; WNX)": ("resistor_100k", "resistor-2t", "resistor-generic", {}),
    "pulsed spot (MM 3)": ("resistor_100k", "resistor-2t", "resistor-generic", {}),
    "pulsed sweep (MM 4)": ("nmos_selfheat", "mosfet-4t", "nmos-pulsed", {"vd": 3.0}),
    "staircase with pulsed bias (MM 5)": ("nmos_selfheat", "mosfet-4t", "nmos-pulsed", {}),
    "multi-channel pulsed spot (MM 27; `points: 1`)": ("resistor_100k", "resistor-2t", "resistor-generic",
                                                       {"points": 1}),
    "multi-channel pulsed sweep (MM 28)": ("resistor_100k", "resistor-2t", "resistor-generic", {}),
    "sampling (MM 10; time stamps)": ("igzo_transient", "mosfet-4t", "nmos-generic", {"vd": 0.1}),
    "quasi-pulsed spot (MM 9; BDV)": ("dielectric_tddb", "mosfet-4t", "dielectric-generic", {"v_stop": 20.0}),
    "linear search (MM 14)": ("diode_basic", "diode-2t", "diode-generic", {"v_stop": -5.0}),
    "binary search (MM 15)": ("nmos_basic", "mosfet-4t", "nmos-generic", {}),
    "quasi-static C-V (MM 13)": ("moscap_dit", "moscap-scuu", "moscap-generic", {}),
    "spot C (MM 17)": ("capacitor_100p", "capacitor-cmu", "capacitor-100p", {}),
    "C-V (MM 18; DC bias sweep)": ("moscap_basic", "moscap-cmu", "moscap-generic", {}),
    "pulsed spot C (MM 19; `points: 1`)": ("moscap_basic", "moscap-cmu", "moscap-generic",
                                          {"points": 1, "v_stop": -2.5}),
    "pulsed C-V (MM 20)": ("moscap_basic", "moscap-cmu", "moscap-generic", {}),
    "C-f sweep (MM 22)": ("moscap_dit", "moscap-scuu", "moscap-generic", {}),
    "C-V (MM 23; AC level sweep)": ("moscap_basic", "moscap-cmu", "moscap-generic", {}),
    "C-t sampling (MM 26)": ("moscap_basic", "moscap-cmu", "moscap-generic", {}),
    "phase compensation (ADJ, ADJ?)": ("capacitor_100p", "capacitor-cmu", None, {}),
    "open/short/load correction data (CORR?, CORRST)": ("capacitor_100p", "capacitor-cmu", None, {}),
    "PG two-level (SIM 0, SPM mode 1)": ("fefet_lab", "fefet-sel", "fefet-lab", {}),
    "PG three-level (SPM 3; `three_level: true`)": ("fefet_lab", "fefet-sel", "fefet-lab", {"three_level": True}),
    "ALWG (SIM 1, ALW/ALS)": ("fefet_lab", "fefet-sel", "fefet-lab", {}),
    "selector states open, SMU, PGU, PGU open (ERSSP)": ("lab_station", "fefet-sel", None, {}),
    "DC (dcforceVoltage, dcmeasureValue)": ("resistor_100k", "resistor-wgfmu", "resistor-generic", {}),
    "Fast IV (patterns, measure events)": ("nmos_wgfmu", "mosfet-wgfmu", "nmos-wgfmu", {}),
    "PG (50 Ohm pulse output; `gate_mode: pg`)": ("nmos_wgfmu", "mosfet-wgfmu", "nmos-wgfmu", {"gate_mode": "pg"}),
    "WGFMU path (connect: RSU -> wgfmu)": ("nmos_wgfmu", "mosfet-wgfmu", "nmos-wgfmu", {}),
}
"""The request that compiles each mode's recipe (scenario, pin map, DUT profile, parameters)."""

NOT_IMPLEMENTED = "not_" + "implemented"
"""The retired v1 status, spelled so that this file does not contain it."""


@pytest.fixture(scope="module")
def sources() -> Any:
    src, problems = coverage.load_sources(REPO_ROOT)
    assert src is not None, problems
    return src


def test_the_coverage_page_is_current_and_has_no_gap() -> None:
    report = coverage.coverage(REPO_ROOT, check=True)
    assert report.problems == [] and not report.drift, coverage.format_report(report)
    assert report.ok and report.recipes == 68 and report.kinds == 14 and report.ledger["open"] == 0
    text = (REPO_ROOT / coverage.COVERAGE_REL).read_text(encoding="utf-8")
    assert text.startswith(coverage.MARKER) and "\r" not in text
    for module in coverage.MODULES:
        assert f"| {module.name} |" in text, module.name


def test_the_cli_checks_and_writes_the_page(tmp_path: Path) -> None:
    runner = CliRunner()
    checked = runner.invoke(app, ["dev", "coverage", "--check", "--root", str(REPO_ROOT)])
    assert checked.exit_code == 0, checked.output
    assert "coverage: up to date (docs/coverage.md;" in checked.stdout and "0 open" in checked.stdout
    both = runner.invoke(app, ["dev", "coverage", "--check", "--write", "--root", str(REPO_ROOT)])
    assert both.exit_code == 2


def test_every_module_has_recipes_and_every_kind_a_module(sources: Any) -> None:
    _rows, members = coverage._module_rows(sources)
    assert all(members[m.name] for m in coverage.MODULES), {m: len(ids) for m, ids in members.items()}
    registry: RecipeRegistry = sources.registry
    assert set(registry.kinds) == set(default_kinds()) and len(registry.kinds) == 14
    covered = {registry.get(r).kind for ids in members.values() for r in ids}
    assert covered == set(registry.kinds)
    assert members["Mainframe (system)"] == [r for r in registry.ids() if registry.get(r).family == "system"]
    assert "system.selector_check" in members["16440A selector x2"]  # family spgu: the selector's own check
    assert "mosfet.gate_leakage" in members["ASU (if declared)"]
    assert "fefet.fast_program_read" in members["RSU"] and "fefet.fast_program_read" not in members[
        "16440A selector x2"]


def test_every_registered_rule_is_in_exactly_the_tables(sources: Any) -> None:
    listed = set(coverage.KERNEL_RULES).union(*coverage.MODULE_RULES.values())
    assert listed == set(sources.rules)
    assert set(coverage.MODULE_RULES) == {m.name for m in coverage.MODULES}
    assert not set(coverage.KERNEL_RULES) & set().union(*coverage.MODULE_RULES.values())


def test_the_gap_checks_fire(sources: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _rows, members = coverage._module_rows(sources)
    ledger = {family: {kind: dict(scopes) for kind, scopes in kinds.items()}
              for family, kinds in sources.ledger.items()}
    ledger["system"]["commands"]["open"] = 2
    stages = {stage: set(recipes) - {"mosfet.idvg"} for stage, recipes in sources.stage_recipes.items()}
    broken = replace(sources, ledger=ledger, rules=[*sources.rules, "R-NEW-01"], stage_recipes=stages,
                     cards=[c for c in sources.cards if c[1].id != "zero-check"])
    problems = coverage.coverage_problems(broken, {**members, "GNDU": []}, {"mapped": 1, "out_of_scope": 1,
                                                                             "open": 2})
    assert "module GNDU: no recipe uses it" in problems
    assert "rule R-NEW-01: in no rule table (KERNEL_RULES or MODULE_RULES)" in problems
    assert any(p.startswith("ledger: 2 entries are still open") for p in problems)
    assert "recipe mosfet.idvg: bring-up stage L4 has no stage file that runs it" in problems
    assert "recipe system.zero_check: no card" in problems
    assert not [p for p in problems if p.startswith("cards:")]  # 33 cards, but PLAN_NOTES explains the split
    assert coverage.coverage_problems(sources, members, {"open": 0}) == []
    monkeypatch.setitem(coverage.PLAN_TOTALS, "kinds", 15)
    assert coverage.coverage_problems(sources, members, {"open": 0}) == [
        "kinds: 14 in the tree, 15 in blueprint v2 3, and no PLAN_NOTES entry says why"]


def _plan(world: World, mode: coverage.Mode) -> PlanRecord:
    scenario, pin_map, dut, params = PROBES[mode.mode]
    world.use_scenario(scenario)
    request = PlanRequest(recipe_id=mode.recipe, pin_map=pin_map, dut_profile=dut, params=params)
    return world.executor().plan(request)


def _shows(world: World, plan: PlanRecord, marker: str) -> bool:
    kind, _, value = marker.partition(":")
    if kind == "flex":
        return any(re.search(value, line) for line in plan.flex_preview)
    if kind == "wgfmu":
        channels = plan.program.get("sources", {}).get("waveform", {}).get("channels", {})
        return any(setup.get("mode") == value for setup in channels.values())
    switch_kind, _, state = value.partition(":")
    station = world.executor().config.get().station
    kinds = {switch.id: switch.kind for switch in station.switches}
    return any(kinds.get(route.switch) == switch_kind and route.state == state for route in plan.envelope.routes)


@pytest.mark.parametrize("mode", [m for m in coverage.MODES if not m.marker.startswith("test:")],
                         ids=lambda m: m.mode)
def test_every_mode_is_reached_by_its_recipe(mode: coverage.Mode, world: World) -> None:
    """Blueprint v2 0 row 1: the named recipe's plan, compiled on the simulator from the committed example config,
    shows the mode (the tier does not matter here: CMU plans wait for corrections, a pulse needs a DUT envelope)."""
    plan = _plan(world, mode)
    assert plan.kind == mode.kind and plan.program, (plan.tier, plan.rules.findings)
    assert _shows(world, plan, mode.marker), (mode.marker, plan.flex_preview[:20])


def test_every_mode_has_a_probe_and_the_wgfmu_modes_cover_the_in_scope_list() -> None:
    compiled = {m.mode for m in coverage.MODES if not m.marker.startswith("test:")}
    assert compiled == set(PROBES)
    wgfmu = {m.marker for m in coverage.MODES if m.marker.startswith("wgfmu:")}
    assert wgfmu == {"wgfmu:dc", "wgfmu:fastiv", "wgfmu:pg"}  # SMU mode: the RSU SMU path (test: marker)
    mm = {int(n) for m in coverage.MODES for n in re.findall(r"^flex:\^MM (\d+)", m.marker)}
    assert mm == {1, 2, 3, 4, 5, 9, 10, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 26, 27, 28}  # blueprint v2 1.2


# -- the v1 reserved machinery is gone (blueprint v2 7.2, 9 "Delete when done") ----------------------------------


LIVE_TREES = ("src", "recipes", ".agents", ".claude/skills", "config", "scripts", "docs", "references/driver-map")
HISTORY = ("docs/design/", "docs/acceptance/20")
"""Dated history that may quote the retired status: the plan of record, the progress log, acceptance reports."""


def _live_files() -> list[str]:
    """Repository-relative paths of the tracked and new (not ignored) files of the live trees (``git ls-files``;
    without git: every file under them except caches and build output)."""
    try:
        listed = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard", "--", *LIVE_TREES, "AGENTS.md", "CLAUDE.md", "README.md"],
                                capture_output=True, check=True).stdout.decode("utf-8")
        return [name for name in listed.split("\0") if name and (REPO_ROOT / name).is_file()]
    except (OSError, subprocess.CalledProcessError):
        paths = [REPO_ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "README.md")]
        for tree in LIVE_TREES:
            paths += [p for p in (REPO_ROOT / tree).rglob("*") if p.is_file()
                      and not {"__pycache__", "build"} & set(p.parts) and ".egg-info" not in p.as_posix()]
        return [p.relative_to(REPO_ROOT).as_posix() for p in paths]


def test_no_retired_status_is_left_in_the_live_tree() -> None:
    """Blueprint v2 7.2 / AC ``rg -n "<status>" src recipes .agents`` empty, extended to every live tree (code,
    recipes, skills and their mirror, config, scripts, docs, the driver map, the top-level instructions); the plan of
    record, the progress log and the dated acceptance reports are history and keep their words."""
    offenders = [rel for rel in _live_files() if not rel.startswith(HISTORY)
                 and NOT_IMPLEMENTED.encode() in (REPO_ROOT / rel).read_bytes()]
    assert offenders == []


def test_the_status_vocabularies_hold_no_retired_value() -> None:
    from typing import get_args

    for literal in (ValidationStatus, ResultStatus, ErrorCode, RunOutcome):
        assert NOT_IMPLEMENTED not in get_args(literal)
    assert get_args(ValidationStatus) == ("draft", "sim_validated", "hw_validated")


def test_no_reserved_slot_kind_or_card_is_left() -> None:
    assert not (REPO_ROOT / "recipes" / "reserved").exists()
    assert not (REPO_ROOT / ".agents" / "skills" / "b1500-test" / "cards" / "reserved").exists()
    assert not (REPO_ROOT / "src" / "b1500_test_agent" / "catalog" / "kinds" / "unimplemented.py").exists()
    kinds = default_kinds()
    assert all(kind.implemented_on == {"sim", "visa"} for kind in kinds.values()), kinds
    assert "wgfmu_pulse_sequence" not in kinds  # retired: no blueprint v2 3 recipe uses it (WP10.6, WP11.2)
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "v1 is SMU I-V only" not in agents and len(agents.splitlines()) <= 80
    # the rest of blueprint v2 9 "Delete when done", gone with earlier work packages (WP5.8, WP6.1)
    assert not (REPO_ROOT / "scripts" / "extract_manuals.py").exists()
    assert not (REPO_ROOT / "docs" / "manual-extraction.md").exists() and (REPO_ROOT / "docs" / "manuals.md").is_file()


def test_the_recipes_listing_has_only_the_three_statuses(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC: ``uv run b1500 recipes --json`` (overview, every family, one recipe) names no retired status."""
    for name, value in world.env().items():
        monkeypatch.setenv(name, value)
    runner = CliRunner()
    overview = runner.invoke(app, ["recipes", "--json"])
    assert overview.exit_code == 0, overview.output
    assert NOT_IMPLEMENTED not in overview.stdout and '"runnable"' in overview.stdout
    statuses: set[str] = set()
    for family in ("smu", "cmu", "spgu", "wgfmu", "nvm", "reliability", "system"):
        listing = runner.invoke(app, ["recipes", "--family", family, "--json"])
        assert listing.exit_code == 0 and NOT_IMPLEMENTED not in listing.stdout, listing.output
        statuses |= set(re.findall(r'"status": "([a-z_]+)"', listing.stdout))
    assert statuses == {"ok", "sim_validated"}  # the envelope's ok and every recipe's status
    detail = runner.invoke(app, ["recipes", "wgfmu.pulse_train", "--json"])
    assert detail.exit_code == 0 and '"runnable": true' in detail.stdout and '"gate_mode"' in detail.stdout
