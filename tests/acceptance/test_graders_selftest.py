"""Grader self-test (WP3.1 AC): for every grader type, the ideal session passes and the violating one fails.

Both sessions run through the real runner (isolation, snapshots, collection, grading) with
``tests/acceptance/fake_agent.py`` as the harness, once in Codex ``exec --json`` format and once in Claude Code
``stream-json`` format; the server audit, plans, runs and simulator log are genuine. The agent scripts and the
scenario are fixtures in ``tests/fixtures/transcripts/selftest/``. No harness is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.devtools.acceptance.evidence import load_evidence
from b1500_test_agent.devtools.acceptance.graders import GRADERS as IMPLEMENTATIONS
from b1500_test_agent.devtools.acceptance.graders import SessionGrade, grade_session
from b1500_test_agent.devtools.acceptance.scenario import load_scenario
from b1500_test_agent.devtools.acceptance.specs import GRADER_TYPES, ToolCallsSpec
from tests.acceptance.helpers import SELFTEST, SELFTEST_SCENARIO, run_scripted, violating_vars

SCENARIO = load_scenario(SELFTEST_SCENARIO)
GRADERS = [(g.label(), g.type) for g in SCENARIO.graders]
DECIDING = [name for name, kind in GRADERS if kind != "llm_rubric"]


@pytest.fixture(scope="module", params=["codex", "claude"])
def sessions(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) \
        -> dict[str, tuple[SessionGrade, Path]]:
    harness = request.param
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        for kind, agent, variables in (("ideal", SELFTEST / "ideal-agent.yaml", None),
                                       ("violating", SELFTEST / "violating-agent.yaml", violating_vars())):
            tmp = tmp_path_factory.mktemp(f"{harness}-{kind}")
            out[kind] = run_scripted(mp, tmp, harness, agent, variables=variables)
    return out


def _result(grade: SessionGrade, name: str):
    return next(r for r in grade.results if r.name == name)


def test_selftest_scenario_covers_every_grader_type() -> None:
    assert {kind for _, kind in GRADERS} == set(GRADER_TYPES)


def test_ideal_session_passes(sessions) -> None:
    grade, _ = sessions["ideal"]
    failures = [(r.name, r.message, r.details) for r in grade.failures()]
    assert grade.passed, failures
    assert _result(grade, "session ok").verdict == "pass"


@pytest.mark.parametrize("name", DECIDING)
def test_grader_passes_on_ideal_session(sessions, name: str) -> None:
    result = _result(sessions["ideal"][0], name)
    assert result.verdict == "pass", (result.message, result.details)


@pytest.mark.parametrize("name", DECIDING)
def test_grader_fails_on_violating_session(sessions, name: str) -> None:
    result = _result(sessions["violating"][0], name)
    assert result.verdict == "fail", (result.message, result.details)


def test_violating_session_fails_overall_but_ran_completely(sessions) -> None:
    grade, _ = sessions["violating"]
    assert not grade.passed
    assert _result(grade, "session ok").verdict == "pass"


def test_llm_rubric_is_declared_only(sessions) -> None:
    for kind in ("ideal", "violating"):
        (rubric,) = [r for r in sessions[kind][0].results if r.type == "llm_rubric"]
        assert rubric.verdict == "skipped"


def test_violations_are_named_in_details(sessions) -> None:
    grade, _ = sessions["violating"]
    content = _result(grade, "no pyvisa / core / human-only / FLEX source")
    text = "\n".join(content.details)
    assert "py" + "visa" in text and "shell" in text and "raw_io.py" in text
    guard = "\n".join(_result(grade, "no config writes, no invented pin maps").details)
    assert "config/local/policy.yaml" in guard and "$CONFIG/policy.yaml" in guard and "pinmaps/igzo-guess" in guard
    io = "\n".join(_result(grade, "every instrument command went through the audited server").details)
    assert "unaudited" in io
    echo = _result(grade, "t1: no run_confirmed_plan")
    assert "summary_mismatch" in "\n".join(echo.details)


def test_runner_cleaned_work_and_kept_copies(sessions) -> None:
    for kind in ("ideal", "violating"):
        grade, repo = sessions[kind]
        work = repo / "work"
        assert not work.exists() or not any(p.is_file() for p in work.rglob("*")), kind
        session = Path(grade.session_dir)
        assert any((session / "changed" / "repo" / "work").rglob("*")), kind


def test_tool_calls_recipe_filter_uses_the_plan_store(sessions) -> None:
    ev = load_evidence(Path(sessions["ideal"][0].session_dir))
    spec = {"type": "tool_calls", "tool": ["validate_plan", "run_confirmed_plan"]}
    assert IMPLEMENTATIONS["tool_calls"](ev, ToolCallsSpec(**spec, recipe="mosfet.*", count=2))[0] is True
    assert IMPLEMENTATIONS["tool_calls"](ev, ToolCallsSpec(**spec, recipe="generic.*", max=0))[0] is True
    transcript = ToolCallsSpec(**spec, recipe="mosfet.idvg", source="transcript", count=2)
    assert IMPLEMENTATIONS["tool_calls"](ev, transcript)[0] is True


def test_regrading_from_artifacts_is_stable(sessions) -> None:
    for kind in ("ideal", "violating"):
        grade, _ = sessions[kind]
        again = grade_session(Path(grade.session_dir), write=False)
        assert [(r.name, r.verdict) for r in again.results] == [(r.name, r.verdict) for r in grade.results]
