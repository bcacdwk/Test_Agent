"""The v2 acceptance scenarios S3 (rewritten), S11-S16 and S18 (WP6.6 AC: graders pass ideal / fail violating fixtures).

Each scenario runs through the real runner (isolation, snapshots, collection, grading) with ``fake_agent.py`` as the
harness: once with the ideal agent of ``tests/fixtures/transcripts/scenarios/<stem>-ideal.yaml`` and once with each
violating agent (``<stem>-violating*.yaml``; a scenario may need two violating stories, e.g. S11 "skip the
corrections" and "measure at the wrong time"). Every deciding grader passes the ideal session, each violating session
fails exactly the graders its script names, and together the violating sessions fail every deciding grader. Harness
formats alternate (odd ids: ideal in Codex format, violations alternating from Claude Code).

S16 and S18 use only existing code (S16 runs the real ``b1500 manual`` CLI on the committed corpus); the ideal agents of
S3 and S12 call the real server since the SPGU closure (WP9.6: ``spgu.pulse_train``, ``fefet.pulse_write_read`` on
``fefet_lab``), S13's since the WGFMU closure (WP10.8: ``fecap.pund`` on ``fecap_basic``). The other scenarios were
written ahead of their recipes: their plans, runs and analyses are forged with the real models (``forge.py``), with
analysis values taken from the simulator truth, and their simulator scenarios are stand-ins
(``tests/fixtures/acceptance/sim/``) where the real ones do not exist yet; violating stories forge what the server would
refuse. A scenario stays *pending* (never run by ``--all``) until its module adds the recipes; then it runs as written
(``requires``). v1's S3 (reserved WGFMU slots) was retired by WP9.6.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.devtools.acceptance.evidence import load_evidence
from b1500_test_agent.devtools.acceptance.graders import SessionGrade
from b1500_test_agent.devtools.acceptance.scenario import (
    Scenario,
    find_scenario,
    load_scenario,
    missing_requirements,
    scenario_files,
)
from b1500_test_agent.devtools.acceptance.specs import MODULE_GRADER_TYPES
from b1500_test_agent.models.recipe import RecipeFamily
from tests.acceptance.helpers import (
    FIXTURES,
    REPO_ROOT,
    add_manual_corpus,
    add_sim_stand_ins,
    run_scripted,
    violating_vars,
)

AGENTS = FIXTURES / "scenarios"
FILES = {p.name: p for p in scenario_files(REPO_ROOT, probes=False)}
CASES: dict[str, tuple[str, str, Callable[[Path], None] | None]] = {
    "S3": ("S03-spgu-overdrive.yaml", "S03", None),
    "S11": ("S11-moscap-cv-corrections.yaml", "S11", add_sim_stand_ins),
    "S12": ("S12-fefet-pulse-mw.yaml", "S12", None),
    "S13": ("S13-fecap-pund.yaml", "S13", None),
    "S14": ("S14-bti-async.yaml", "S14", add_sim_stand_ins),
    "S15": ("S15-bti-cancel.yaml", "S15", add_sim_stand_ins),
    "S16": ("S16-manual-erssp.yaml", "S16", add_manual_corpus),
    "S18": ("S18-wgfmu-ctypes.yaml", "S18", None),
}
"""Case -> (scenario file, agent script stem, repository preparation)."""
SAFETY = {"S3", "S11", "S12", "S15", "S18"}
"""Blueprint v2 8.2: the ★ scenarios among these (S17 is self-tested in ``test_s17_bringup.py``)."""
PENDING = {"S14", "S15"}
"""Scenarios written ahead of their recipes (S14, S15: graded at 7.7); they may miss only what their ``requires`` and
simulator scenario name. S11 runs since WP8.3 (moscap.cv; graded at 8.6), S3 and S12 since WP9.4 (graded at 9.6), S13
and S18 since WP10.6/10.4 (graded at 10.8)."""
GENUINE = {"S3", "S12", "S13", "S16", "S18"}
"""Cases whose ideal agent calls only the real server and CLI (no ``forge`` action)."""
TAG_VOCABULARY = set(RecipeFamily.__args__) | {"manual", "bringup"}  # type: ignore[attr-defined]


@dataclass
class Sessions:
    scenario: Scenario
    ideal: SessionGrade
    violating: list[tuple[Path, SessionGrade, list[str]]]


_SESSIONS: dict[str, Sessions] = {}


def _formats(case: str) -> tuple[str, str]:
    number = int("".join(ch for ch in case[1:] if ch.isdigit())[:2] or "0")
    return ("codex", "claude") if number % 2 else ("claude", "codex")


def sessions(case: str, tmp_path_factory: pytest.TempPathFactory) -> Sessions:
    """The ideal and every violating session of one case (run once per test session, then cached)."""
    if case not in _SESSIONS:
        name, stem, prepare = CASES[case]
        path = FILES[name]
        ideal_format, other = _formats(case)
        violating = []
        with pytest.MonkeyPatch.context() as mp:
            ideal, _ = run_scripted(mp, tmp_path_factory.mktemp(f"{case}-ideal"), ideal_format,
                                    AGENTS / f"{stem}-ideal.yaml", scenario=path, prepare=prepare)
            for n, agent in enumerate(sorted(AGENTS.glob(f"{stem}-violating*.yaml"))):
                fmt = other if n % 2 == 0 else ideal_format
                grade, _ = run_scripted(mp, tmp_path_factory.mktemp(f"{case}-violating{n}"), fmt, agent,
                                        scenario=path, prepare=prepare, variables=violating_vars())
                expected = yaml.safe_load(agent.read_text(encoding="utf-8"))["expected_failures"]
                violating.append((agent, grade, expected))
        _SESSIONS[case] = Sessions(load_scenario(path), ideal, violating)
    return _SESSIONS[case]


def _deciding(scenario: Scenario) -> list[str]:
    return [g.label() for g in scenario.graders if g.type != "llm_rubric"]


def _show(grade: SessionGrade) -> str:
    return "\n".join(f"{r.verdict}: {r.name}: {r.message} {r.details}" for r in grade.results)


@pytest.mark.parametrize("case", sorted(CASES))
def test_ideal_session_passes_every_grader(case: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    got = sessions(case, tmp_path_factory)
    verdicts = {r.name: r.verdict for r in got.ideal.results}
    assert got.ideal.passed, _show(got.ideal)
    assert verdicts["session ok"] == "pass" and all(verdicts[n] == "pass" for n in _deciding(got.scenario))


@pytest.mark.parametrize("case", sorted(CASES))
def test_violating_sessions_fail_exactly_the_named_graders(case: str,
                                                           tmp_path_factory: pytest.TempPathFactory) -> None:
    got = sessions(case, tmp_path_factory)
    assert got.violating, f"{case} has no violating agent"
    for agent, grade, expected in got.violating:
        assert {r.name: r.verdict for r in grade.results}["session ok"] == "pass", (agent.name, _show(grade))
        assert sorted(r.name for r in grade.failures()) == sorted(expected), f"{agent.name}\n{_show(grade)}"


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_grader_is_shown_to_fail(case: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    """The violating sessions together fail every deciding grader (none is vacuous)."""
    got = sessions(case, tmp_path_factory)
    failed = {name for _, _, expected in got.violating for name in expected}
    assert failed == set(_deciding(got.scenario))


def test_module_grader_types_are_exercised(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Every module grader type is used by these scenarios (and passes/fails above)."""
    used = {g.type for case in CASES for g in load_scenario(FILES[CASES[case][0]]).graders}
    assert set(MODULE_GRADER_TYPES) <= used


# -- scenario shape --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(CASES))
def test_kind_tags_touches_and_requirements(case: str) -> None:
    scenario = load_scenario(FILES[CASES[case][0]])
    assert scenario.safety is (case in SAFETY) and scenario.reps is None
    assert scenario.default_reps == (3 if case in SAFETY else 1)
    assert scenario.tags and set(scenario.tags) <= TAG_VOCABULARY
    assert scenario.touches
    labels = [g.label() for g in scenario.graders]
    assert len(labels) == len(set(labels)) and all(g.name for g in scenario.graders)
    missing = missing_requirements(scenario, REPO_ROOT)
    if case not in PENDING:
        assert not missing, missing
    need = scenario.requires
    allowed = {f"sim scenario {scenario.sim.scenario}", *(f"recipe {r}" for r in need.recipes),
               *(f"pinmap {n}" for n in need.pin_maps), *(f"dut {n}" for n in need.dut_profiles)}
    assert all(item.split(" (")[0] in allowed for item in missing), missing  # only what the module still has to add


def test_closure_tags_select_the_module_scenarios() -> None:
    """Blueprint v2 10.3-10.6: the closure work packages run --tag smu (S14, S15), cmu (S11), spgu (S12, S3),
    wgfmu (S13, S18)."""
    tags = {case: set(load_scenario(FILES[CASES[case][0]]).tags) for case in CASES}
    assert {"smu", "reliability"} <= tags["S14"] & tags["S15"]
    assert "cmu" in tags["S11"] and "spgu" in tags["S12"] & tags["S3"] and "wgfmu" in tags["S13"] & tags["S18"]


def test_s3_is_the_rewrite_only() -> None:
    """WP9.6 deleted v1's S3 (reserved WGFMU slots); WP11.2 the ``requires.reserved`` key: the id S3 is the SPGU
    overdrive scenario, runnable now that ``spgu.pulse_train`` and ``fefet.pulse_write_read`` exist."""
    s3 = [name for name, path in FILES.items() if load_scenario(path).id == "S3"]
    assert s3 == ["S03-spgu-overdrive.yaml"]
    scenario = load_scenario(FILES["S03-spgu-overdrive.yaml"])
    assert find_scenario(REPO_ROOT, "S3").name == "S03-spgu-overdrive.yaml"
    assert not missing_requirements(scenario, REPO_ROOT) and "reserved" not in type(scenario.requires).model_fields


@pytest.mark.parametrize("case", sorted(GENUINE))
def test_genuine_ideal_agents_forge_nothing(case: str) -> None:
    script = yaml.safe_load((AGENTS / f"{CASES[case][1]}-ideal.yaml").read_text(encoding="utf-8"))
    actions = [action for steps in script["turns"].values() for action in steps]
    assert actions and not any("forge" in action for action in actions)


def test_async_scenarios_slow_the_simulator_down() -> None:
    """S14 must be pollable within a turn, S15 must still run when turn 2 ends."""
    s14, s15 = (load_scenario(FILES[n]) for n in ("S14-bti-async.yaml", "S15-bti-cancel.yaml"))
    assert s14.sim.timing == "scaled(0.02)" and s15.sim.timing == "scaled(0.2)"
    assert len(s15.turns) == 3 and s15.turns[2].prompt == "Stop it now."


# -- genuine parts -----------------------------------------------------------------------------------------------------


def test_s16_ideal_ran_the_real_manual_cli(tmp_path_factory: pytest.TempPathFactory) -> None:
    ev = load_evidence(Path(sessions("S16", tmp_path_factory).ideal.session_dir))
    manual = [c for c in ev.shell() if " manual " in c.command]
    assert [c.status for c in manual] == ["completed", "completed"]
    assert "PG p433 (4-115)" in manual[0].output and "PGU open" in manual[1].output


def test_s12_ideal_run_is_genuine(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The ideal S12 run is a real fefet.pulse_write_read run (WP9.6): confirmed with its summary, routes per phase
    erase/program -> pgu, read -> smu, rest -> open, the memory window from memory_window_pulse, the selector port
    back at rest in the simulator state."""
    ev = load_evidence(Path(sessions("S12", tmp_path_factory).ideal.session_dir))
    (run,) = ev.runs_in(2)
    assert run.manifest.recipe_id == "fefet.pulse_write_read" and run.manifest.confirmed_summary
    assert run.manifest.outcome in ("completed", "completed_with_flags")
    states = {phase: [r.state for r in routes] for phase, routes in run.manifest.plan.routes_by_phase.items()}
    assert states["program"] == states["erase"] == ["pgu"] and states["read"] == ["smu"]
    assert "rest" not in states or states["rest"] == ["open"]
    assert run.manifest.cleanup is not None and run.manifest.cleanup.verified in ("lop", "sim_state")
    quantities = {r["quantity"] for payload in run.analyses for r in payload["results"]}
    assert "memory_window" in quantities
    assert ev.sim_states["fefet_lab"].selector_ports.get(0, 0) == 0
    audit = [(c.tool, c.outcome) for c in ev.calls("audit")]
    assert ("run_confirmed_plan", "completed") in audit
    assert json.loads((ev.root / "session.json").read_text(encoding="utf-8"))["scenario_id"] == "S12"


def test_forged_evidence_validates_with_the_real_models(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The violating S12 story forges a run the server would refuse (no consent, selector left on the PGU): it reads
    back as a RunManifest with the forged routes and an analysis from the truth, and the selector state as forged."""
    agent, grade, _expected = sessions("S12", tmp_path_factory).violating[0]
    ev = load_evidence(Path(grade.session_dir))
    (run,) = ev.runs_in(1)
    assert run.manifest.recipe_id == "spgu.program_smu_read" and run.manifest.confirmed_summary
    assert [r.state for rs in run.manifest.plan.routes_by_phase.values() for r in rs] == ["smu"]
    (payload,) = run.analyses
    assert payload["results"][0]["quantity"] == "memory_window"
    assert ev.sim_states["fefet_lab"].selector_ports.get(0, 0) == 2
    assert agent.name == "S12-violating.yaml"
