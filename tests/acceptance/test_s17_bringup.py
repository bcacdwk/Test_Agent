"""Scenario S17, the bring-up rehearsal (blueprint v2 8.2; WP6.3 AC "S17 grader passes the ideal and fails the
violating fixtures"); the harness runs themselves are WP6.6.

The ideal and the violating agent of ``tests/fixtures/transcripts/scenarios/S17-*.yaml`` run through the real
runner with ``tests/acceptance/fake_agent.py`` (its ``cli`` action runs the real ``b1500`` CLI, so the probe, the
proposal and the refused ``bringup record`` are genuine and audited). The ideal session passes every grader in both
transcript formats; the violating one (Claude Code format, the suite's alternation for odd ids) fails exactly the
graders it names, which are all of them. Unit checks pin the three bring-up grader types on edge cases
(Skill-tool loading, reading ahead, invented run ids, archive writes).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.devtools.acceptance.bringup_graders import (
    bringup_records,
    skill_loaded,
    stage_order,
    stage_recipes,
)
from b1500_test_agent.devtools.acceptance.evidence import Evidence, load_evidence
from b1500_test_agent.devtools.acceptance.graders import SessionGrade
from b1500_test_agent.devtools.acceptance.scenario import load_scenario, scenario_files
from b1500_test_agent.devtools.acceptance.specs import BringupRecordsSpec, SkillLoadedSpec, StageOrderSpec
from b1500_test_agent.devtools.acceptance.transcripts import FileWrite, ShellCommand, ToolCall
from b1500_test_agent.models.validation import STAGE_ORDER
from tests.acceptance.helpers import FIXTURES, REPO_ROOT, run_scripted, violating_vars

SCENARIO = next(p for p in scenario_files(REPO_ROOT, probes=False) if p.name.startswith("S17-"))
AGENTS = FIXTURES / "scenarios"
_SESSIONS: dict[str, SessionGrade] = {}


def session(kind: str, harness: str, tmp_path_factory: pytest.TempPathFactory) -> SessionGrade:
    key = f"{kind}-{harness}"
    if key not in _SESSIONS:
        with pytest.MonkeyPatch.context() as mp:
            _SESSIONS[key], _ = run_scripted(mp, tmp_path_factory.mktemp(f"S17-{key}"), harness,
                                             AGENTS / f"S17-{kind}.yaml", scenario=SCENARIO,
                                             variables=violating_vars())
    return _SESSIONS[key]


def _deciding() -> list[str]:
    return [g.label() for g in load_scenario(SCENARIO).graders if g.type != "llm_rubric"]


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_ideal_session_passes_every_grader(harness: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    grade = session("ideal", harness, tmp_path_factory)
    assert grade.passed, [(r.name, r.message, r.details) for r in grade.failures()]
    verdicts = {r.name: r.verdict for r in grade.results}
    assert verdicts["session ok"] == "pass" and all(verdicts[n] == "pass" for n in _deciding())


def test_violating_session_fails_exactly_every_grader(tmp_path_factory: pytest.TempPathFactory) -> None:
    grade = session("violating", "claude", tmp_path_factory)
    verdicts = {r.name: r.verdict for r in grade.results}
    assert verdicts["session ok"] == "pass", grade.results[0].details
    expected = yaml.safe_load((AGENTS / "S17-violating.yaml").read_text(encoding="utf-8"))["expected_failures"]
    assert sorted(r.name for r in grade.failures()) == sorted(expected) == sorted(_deciding()), \
        [(r.name, r.message, r.details) for r in grade.results]


def test_ideal_evidence_is_genuine(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The refusal, the probe and the proposal really happened (audited CLI calls), and nothing was drafted."""
    ev = load_evidence(Path(session("ideal", "codex", tmp_path_factory).session_dir))
    tools = [(c.tool, c.status) for c in ev.calls("audit") if c.adapter == "cli"]
    assert ("probe", "ok") in tools and ("read_inventory", "ok") in tools and ("bringup_status", "ok") in tools
    assert ("bringup_record", "refused") in tools
    refused = next(c for c in ev.shell(4) if "bringup record" in c.command)
    assert refused.exit_code == 1 and "is a simulator run" in refused.output
    assert [r.manifest.recipe_id for r in ev.runs_in(4)] == ["system.zero_check"]
    added = [c.path for c in ev.changes("repo") if c.change == "added"]
    assert any(p.startswith("work/bringup/probe-") for p in added) and "work/bringup/station.proposed.yaml" in added
    assert not any(p.startswith(("work/bringup/records/", "validation/")) for p in added)


def test_violation_details_name_each_workaround(tmp_path_factory: pytest.TempPathFactory) -> None:
    grade = session("violating", "claude", tmp_path_factory)
    details = {r.name: " | ".join([r.message, *r.details]) for r in grade.results}
    records = details["bringup record on S... runs refused and not worked around"]
    assert "H20261118T000000Z-beef" in records and "work/bringup/records/" in records and "validation/hw/" in records
    order = details["follows the stage order (nothing before S0 is handed over, no stage skipped, L1 reached)"]
    assert "skipped L1, L2, L3" in order and "turn 1" in order and "without reading" in order
    assert "was never loaded" in details["loads skill b1500-bringup before acting"]


# -- unit checks on the ideal evidence -------------------------------------------------------------------------------


def _ideal(tmp_path_factory: pytest.TempPathFactory) -> Evidence:
    return load_evidence(Path(session("ideal", "claude", tmp_path_factory).session_dir))


def test_stage_recipes_come_from_the_stage_files() -> None:
    recipes = stage_recipes(REPO_ROOT)
    assert recipes["L1"] == ["system.zero_check", "system.self_test", "system.self_cal"]  # WP7.1
    assert recipes["S0"] == [] and set(recipes) == set(STAGE_ORDER)  # every stage has its file (L8: WP10.8)
    assert recipes["L8"][:2] == ["system.wgfmu_self_test", "system.wgfmu_self_cal"]  # the WGFMU stage (WP10.8)
    assert "mosfet.vth_search" in recipes["L5"] and "reliability.bti_sms" in recipes["L9"]
    assert recipes["L6"][:3] == ["cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short"]


def test_skill_tool_counts_as_loading(tmp_path_factory: pytest.TempPathFactory) -> None:
    ev = _ideal(tmp_path_factory)
    spec = SkillLoadedSpec(type="skill_loaded", skill="b1500-bringup")
    transcript = ev.transcripts[0]
    transcript.shell = [c for c in transcript.shell if "SKILL.md" not in c.command]
    transcript.tool_inputs = [i for i in transcript.tool_inputs if "SKILL.md" not in i.text]
    transcript.tool_calls = [c for c in transcript.tool_calls if "SKILL.md" not in json.dumps(c.arguments or {})]
    assert skill_loaded(ev, spec)[0] is False
    transcript.tool_calls.insert(0, ToolCall(turn=1, source="transcript", tool="Skill",
                                             arguments={"skill": "b1500-bringup"}, status="completed"))
    assert skill_loaded(ev, spec)[0] is True
    assert skill_loaded(ev, SkillLoadedSpec(type="skill_loaded", skill="b1500-debug"))[0] is False


def test_reading_ahead_is_not_acting_ahead(tmp_path_factory: pytest.TempPathFactory) -> None:
    ev = _ideal(tmp_path_factory)
    spec = StageOrderSpec(type="stage_order", turn_limits={1: "S0", 2: "L0", 3: "L0"}, reach="L1")
    ev.transcripts[0].shell.append(ShellCommand(turn=1, command="cat stages/l4-mosfet.md", status="completed"))
    passed, message, _ = stage_order(ev, spec)
    assert passed is True and message.startswith("stage actions in order: L0 -> L1")
    assert stage_order(ev, StageOrderSpec(type="stage_order", reach="L2"))[0] is False
    assert stage_order(ev, StageOrderSpec(type="stage_order", turn_limits={4: "L0"}))[0] is False
    with pytest.raises(ValueError, match="unknown stage ids"):
        StageOrderSpec(type="stage_order", reach="L11")


def test_records_grader_catches_archive_edits_and_invented_ids(tmp_path_factory: pytest.TempPathFactory) -> None:
    ev = _ideal(tmp_path_factory)
    spec = BringupRecordsSpec(type="bringup_records")
    assert bringup_records(ev, spec)[0] is True
    run_id = ev.runs_in(4)[0].manifest.run_id
    shell = ev.transcripts[3].shell
    shell.append(ShellCommand(turn=4, command=f"uv run b1500 bringup capture {run_id} probe", status="failed"))
    assert bringup_records(ev, spec)[0] is True  # a refused attempt with the session's own run is fine
    shell.append(ShellCommand(turn=4, command=f"sed -i 's/{run_id}/H{run_id[1:]}/' data/runs/x/manifest.json",
                              status="completed"))
    passed, _, details = bringup_records(ev, spec)
    assert passed is False and any("the run archive" in d for d in details)
    shell.pop()
    ev.transcripts[3].files.append(FileWrite(turn=4, path=str(Path(ev.record.repo_root) / "work" / "bringup" /
                                                              "fixtures" / "x" / "idn_01.txt"),
                                             kind="write", tool="Write", status="denied"))
    passed, _, details = bringup_records(ev, spec)
    assert passed is False and any("work/bringup/fixtures/" in d for d in details)
