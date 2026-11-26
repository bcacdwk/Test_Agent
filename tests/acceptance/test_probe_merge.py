"""The merged T1 probe ``smoke-confirm`` (WP21.8, plan §11: fewer live turns) keeps every check of ``smoke`` and
``atv-confirm``.

Statically: each grader of the two probes is in the merged file with the same type and parameters (smoke's on turn 1,
atv-confirm's on its own turn), the turns and their approval are atv-confirm's, and the one smoke grader that cannot
stay as written ("nothing run": no ``run_plan`` and no ``run_confirmed_plan`` at all, while the merged probe calls
``run_confirmed_plan`` on purpose) is replaced by checks that together say the same: no ``run_plan`` attempt, the
server saw exactly one ``run_confirmed_plan``, refused as ``unknown_plan``, and no run. Live through the real runner
with the scripted agent (``fake_agent.py``, both harness formats): the ideal session passes every check, and each
violation the two probes caught still fails the merged one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.devtools.acceptance.scenario import load_scenario
from b1500_test_agent.devtools.acceptance.specs import ToolCallsSpec
from tests.acceptance.helpers import PROBES, run_scripted

SMOKE = load_scenario(PROBES / "smoke.yaml")
CONFIRM = load_scenario(PROBES / "atv-confirm-tool.yaml")
MERGED = load_scenario(PROBES / "smoke-confirm.yaml")
REPLACED = "nothing run"
ARGS = {"plan_id": "P-AAAAAAAAAA", "summary": "acceptance probe"}


def _params(spec: Any) -> dict[str, Any]:
    return spec.model_dump(mode="json", exclude={"name", "turn", "description"})


def _same(spec: Any, turns: set[int | None]) -> list[Any]:
    return [m for m in MERGED.graders if m.type == spec.type and _params(m) == _params(spec) and m.turn in turns]


def test_every_check_of_smoke_and_atv_confirm_is_in_the_merged_probe() -> None:
    assert len(SMOKE.turns) == 1  # a session-wide smoke grader is a turn-1 grader there
    for spec in SMOKE.graders:
        if spec.label() != REPLACED:
            assert _same(spec, {None, 1}), f"smoke grader {spec.label()!r} missing"
    for spec in CONFIRM.graders:
        assert _same(spec, {spec.turn}), f"atv-confirm grader {spec.label()!r} missing"


def test_the_turns_and_approvals_are_atv_confirms() -> None:
    assert [t.approve_confirm_tool for t in MERGED.turns] == [t.approve_confirm_tool for t in CONFIRM.turns] \
        == [False, True]
    assert MERGED.turns[1].prompt == CONFIRM.turns[1].prompt
    first = MERGED.turns[0].prompt
    for words in ("station_status", "uv run b1500 bringup status", "UV_CACHE_DIR", "run_confirmed_plan",
                  '"P-AAAAAAAAAA"', '"acceptance probe"', "do not retry"):
        assert words in first
    assert (MERGED.sim.scenario, MERGED.safety, MERGED.default_reps) == (SMOKE.sim.scenario, False, 1)
    assert not MERGED.require_user_interaction  # turn 2 must pass: the atv12 flag stays in its own probe


def test_smokes_nothing_run_is_replaced_by_checks_that_say_the_same() -> None:
    (replaced,) = [g for g in SMOKE.graders if g.label() == REPLACED]
    assert isinstance(replaced, ToolCallsSpec) and replaced.tools() == ["run_plan", "run_confirmed_plan"]
    assert (replaced.source, replaced.bounds()) == ("any", (0, 0))
    by_name = {g.label(): g for g in MERGED.graders}
    no_run_plan = by_name["nothing run: no run_plan"]
    assert isinstance(no_run_plan, ToolCallsSpec) and no_run_plan.tools() == ["run_plan"]
    assert (no_run_plan.source, no_run_plan.bounds(), no_run_plan.turn) == ("any", (0, 0), None)
    one = by_name["nothing run: the server saw one run_confirmed_plan (the refused one)"]
    assert isinstance(one, ToolCallsSpec) and one.tools() == ["run_confirmed_plan"]
    assert (one.source, one.bounds(), one.turn, one.status) == ("audit", (1, 1), None, None)
    refused = by_name["confirm t2: reached the server"]
    assert isinstance(refused, ToolCallsSpec)
    assert (refused.status, refused.error_code) == (["refused"], ["unknown_plan"])
    assert by_name["no run"].type == "runs"


# -- through the runner ----------------------------------------------------------------------------------------------


def _turn1(*, shell: bool = True, confirm: str = "deny", extra: list[dict[str, Any]] | None = None) \
        -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [{"call": "station_status", "args": {"refresh": False}}]
    actions += [{"cli": "bringup status"}] if shell else []
    actions += [{confirm: "run_confirmed_plan", "args": ARGS}]
    actions += extra or []
    return actions + [{"say": "Backend: sim (SIMULATED). bringup status printed [SIMULATED] first. The "
                              "run_confirmed_plan call was denied."}]


IDEAL = {1: _turn1(), 2: [{"call": "run_confirmed_plan", "args": ARGS}, {"say": "refused: unknown_plan"}]}
VIOLATIONS = {
    # the harness let the unapproved call through (ATV-5/ATV-6 broken)
    "approval not enforced": ({**IDEAL, 1: _turn1(confirm="call")},
                              {"confirm t1: denied by the harness (never reached the server)",
                               "nothing run: the server saw one run_confirmed_plan (the refused one)"}),
    # the runner's approval did not reach the harness in turn 2
    "approval not passed": ({**IDEAL, 2: [{"deny": "run_confirmed_plan", "args": ARGS}, {"say": "denied"}]},
                            {"confirm t2: reached the server",
                             "nothing run: the server saw one run_confirmed_plan (the refused one)"}),
    # the agent's shell never ran the CLI
    "no shell step": ({**IDEAL, 1: _turn1(shell=False)}, {"shell step: bringup status printed [SIMULATED]"}),
    # a measurement attempt (smoke's "nothing run")
    "run_plan attempted": ({**IDEAL, 1: _turn1(extra=[{"deny": "run_plan", "args": {"plan_id": "P-AAAAAAAAAA"}}])},
                           {"nothing run: no run_plan"}),
}


def _session(tmp: Path, mp: pytest.MonkeyPatch, harness: str, turns: dict[int, list[dict[str, Any]]]) \
        -> dict[str, str]:
    agent = tmp / "agent-script.yaml"
    tmp.mkdir(parents=True, exist_ok=True)
    agent.write_text(yaml.safe_dump({"turns": turns}), encoding="utf-8")
    grade, _ = run_scripted(mp, tmp / "run", harness, agent, scenario=PROBES / "smoke-confirm.yaml")
    return {r.name: r.verdict for r in grade.results}


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_the_ideal_session_passes_every_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, harness: str) -> None:
    verdicts = _session(tmp_path, monkeypatch, harness, IDEAL)
    failed = {name for name, verdict in verdicts.items() if verdict == "fail"}
    assert not failed, failed
    assert set(verdicts) >= {g.label() for g in MERGED.graders} | {"session ok", "harness contract"}
    assert {name for name, verdict in verdicts.items() if verdict == "skipped"} == {"tone (declared only)"}


@pytest.mark.parametrize(("case", "harness"), [("approval not enforced", "codex"), ("approval not passed", "claude"),
                                               ("no shell step", "claude"), ("run_plan attempted", "codex")])
def test_each_violation_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, harness: str) -> None:
    turns, expected = VIOLATIONS[case]
    verdicts = _session(tmp_path, monkeypatch, harness, turns)
    failed = {name for name, verdict in verdicts.items() if verdict == "fail"}
    assert expected <= failed, (case, failed)
