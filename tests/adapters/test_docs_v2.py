"""The v2 docs stay true to the code they describe (blueprint v2 9 "Docs", 10.7 row 11.4; WP11.4).

- ``docs/safety-model.md``: every registered rule has its row; the residual-risk section names the residuals the plan
  and the work packages handed over (routes, sources without compliance with the SPGU ``high_z`` residual, the WGFMU
  without compliance, async residuals incl. the Codex headless turn end, the locked bus) and the kinds without a
  cancel point are exactly the kinds whose safety-matrix bodies never reach a segment boundary (WP11.3).
- ``docs/roadmap.md``: the M12 table of what each stage settles is the stage files' ``TODO(verify)`` lines (a resolved
  item names no stage).
- ``docs/architecture.md``: every file or folder of the package that "Adding a module family" and the module map
  name exists, and the dependency line is the import-layering test's.
- ``README.md``: the status names the plan totals and points to the hardware session.
"""

from __future__ import annotations

import re
from pathlib import Path

from b1500_test_agent.catalog.kinds import default_kinds
from b1500_test_agent.rules.engine import registered_rules
from tests.safety.global_matrix import BODIES
from tests.skills.test_bringup_stages import DEFERRED_ITEMS, RESOLVED_ITEMS, STAGE_DEFERRED

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "b1500_test_agent"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = re.search(r"^## ", text[start + len(heading):], re.MULTILINE)
    return text[start:start + len(heading) + following.start()] if following else text[start:]


# -- safety-model.md ------------------------------------------------------------------------------------------------


def test_every_registered_rule_has_a_row_in_the_safety_model() -> None:
    import b1500_test_agent.rules.builtin  # noqa: F401 - registers the built-in rules

    table = _section(_read("docs/safety-model.md"), "## Implemented rules")
    ids = [spec.rule_id for spec in registered_rules()]
    assert len(ids) >= 30
    assert [rule for rule in ids if f"`{rule}`" not in table and f"| {rule} " not in table] == []


def test_the_residual_risk_section_names_every_handed_over_residual() -> None:
    residuals = " ".join(_section(_read("docs/safety-model.md"), "## Residual risks (v2)").split())
    for needle in ("`ERSSP?` reports the commanded selector state", "Sources without compliance",
                   "SPGU `high_z` residual (OD-3)", "`Isc<=X A residual`", "WGFMU (no compliance)", "R-GNDU-01",
                   "Cancel latency", "Codex headless turn end (WP7.7)", "`aborted`", "SIGTERM", "`cancelled`",
                   "Locked bus", "latches the fault", "R-FAULT-01", "`busy`",
                   "Harness built-ins outside the guard hook (owner decision OD21-5 = c, v2.1)", "`Monitor`",
                   "`harness contract` WARN", "Interactive-only facts"):
        assert needle in residuals, needle


def test_the_kinds_without_a_cancel_point_are_the_matrix_kinds_without_a_boundary() -> None:
    """The table of one-segment kinds lists exactly the kinds none of whose safety-matrix bodies honours a cancel
    request inside the body (WP11.3 handoff), each with a bound."""
    without = {b.kind for b in BODIES} - {b.kind for b in BODIES if "boundary" in b.features}
    assert {b.kind for b in BODIES} == set(default_kinds())
    residuals = _section(_read("docs/safety-model.md"), "## Residual risks (v2)")
    rows = re.findall(r"^\| `([a-z_]+)` \| [^|]+ \| ([^|]+) \|$", residuals, re.MULTILINE)
    assert {kind for kind, _bound in rows} == without == {"smu_staircase", "smu_search", "smu_qscv",
                                                          "cmu_correction", "system"}
    assert all(re.search(r"\d+ s", bound) for _kind, bound in rows), rows


# -- roadmap.md -----------------------------------------------------------------------------------------------------


def test_the_roadmap_m12_table_is_the_stage_files_deferral_lists() -> None:
    section = _section(_read("docs/roadmap.md"), "## M12 — Hardware session (owner)")
    rows = {int(item): cell for item, cell in re.findall(r"^\| (\d+) [^|]+\| ([^|]+) \|$", section, re.MULTILINE)}
    assert set(rows) == set(DEFERRED_ITEMS)
    for item, cell in rows.items():
        named = set(re.findall(r"\b(S0|L10|L\d)\b", cell))
        assert named == {stage for stage, items in STAGE_DEFERRED.items() if item in items}, (item, cell)
        assert (item in RESOLVED_ITEMS) == cell.startswith("resolved"), (item, cell)  # v2.1: item 14 (OD-4)
    status = _section(_read("docs/roadmap.md"), "## M11 — Integration and closure")
    for wp in ("11.1", "11.2", "11.3", "11.4", "11.5"):
        assert f"| {wp} " in status, wp


# -- architecture.md ------------------------------------------------------------------------------------------------

PATH_SPAN = re.compile(r"`((?:[a-z_]+/)+[a-z_<>.]*)`")
RUNTIME = ("config/local/", "work/", "data/", "plots/")
"""Folders that exist only at run time (gitignored) or inside a run folder."""
RETIRED = ("recipes/reserved/",)
"""Named as deleted (WP11.2) in the module map's history."""


def test_the_files_architecture_names_exist() -> None:
    """Every path of two or more parts in backticks (``driver/flex/__init__.py``, ``units/spgu.py``) exists under
    the repository, ``tests/``, ``src/`` or one of the package's folders; ``<family>``-style placeholders, run-time
    folders and the retired ones named as deleted are skipped."""
    text = _read("docs/architecture.md")
    bases = [ROOT, ROOT / "tests", ROOT / "src", PACKAGE, *(p for p in PACKAGE.rglob("*") if p.is_dir())]
    missing = []
    for rel in sorted(set(PATH_SPAN.findall(text))):
        if "<" in rel or rel.startswith(RUNTIME + RETIRED):
            continue
        if not any((base / rel).exists() for base in bases):
            missing.append(rel)
    assert missing == []
    adding = _section(text, "## Adding a module family")
    for registry in ("`default_kinds()`", "`ANALYSIS_METHODS`", "`FAMILY_MODULES`", "`flex.SUPPORTED`", "`BODIES`",
                     "`MODULES`", "`LEDGER_FAMILIES`", "`STAGES`", "`RecipeFamily`", "`ModuleType`",
                     "`SimInstrument.unsafe_reasons`", "`run_cleanup`"):
        assert registry in adding, registry


def test_the_dependency_lines_are_the_layering_test() -> None:
    """The dependency line of the architecture page, the README and AGENTS.md follows the import test's ranks, and
    the architecture page names its "imports only" rules."""
    from tests.unit.test_import_layering import ONLY, RANKS

    line = ("adapters → {bringup →} service → {catalog, rules, archive, analysis, manuals} → session → driver → "
            "transport")
    for rel in ("docs/architecture.md", "README.md", "AGENTS.md"):
        assert line in " ".join(_read(rel).replace("`", " ").split()), rel
    steps = [re.findall(r"[a-z]+", step) for step in line.split("→")]
    ranks = [{RANKS[name] for name in step} for step in steps if step != ["bringup"]]
    assert all(len(r) == 1 for r in ranks) and [r.pop() for r in ranks] == [7, 6, 5, 4, 3, 2]
    assert RANKS["bringup"] > RANKS["service"]
    architecture = " ".join(_read("docs/architecture.md").split())
    assert set(ONLY) == {"fsio", "manuals", "bringup", "bringup_ledger", "bringup_verify", "bringup_steps"}
    assert ONLY["fsio"] == {"models", "errors"} and "fsio: file primitives" in architecture
    assert "imports only models and errors" in architecture
    assert ("manuals: imports only models, paths and fsio; bringup: imports only service, models and fsio"
            in architecture)
    # v2.1 (WP21.5): the bring-up step modules, a chain below bringup
    assert "bringup_steps → bringup_verify → bringup_ledger" in architecture
    assert ONLY["manuals"] == {"models", "paths", "fsio"} and ONLY["bringup_ledger"] == {"models", "fsio"}
    assert ONLY["bringup"] - {"service", "models", "fsio"} == {"bringup_ledger", "bringup_steps"}
    assert all(RANKS[name] == RANKS["bringup"] for name in ("bringup_ledger", "bringup_verify", "bringup_steps"))


# -- README.md ------------------------------------------------------------------------------------------------------


def test_the_readme_status_names_the_totals_and_the_hardware_session() -> None:
    readme = " ".join(_read("README.md").replace("\n> ", "\n").split())  # the status is a block quote
    for needle in ("68 recipes, 14 measurement kinds and 34 test cards", "M12", "WP11.5",
                   "No code path has run against a real instrument yet", "docs/deployment-windows.md",
                   "docs/hardware-bringup.md", "docs/coverage.md"):
        assert needle in readme, needle
