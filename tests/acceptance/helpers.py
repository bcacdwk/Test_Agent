"""Helpers for the acceptance-framework self-tests (no real harness is ever launched here)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.devtools.acceptance import harnesses, runner
from b1500_test_agent.devtools.acceptance.evidence import (
    CONFIG_DIR,
    DATA_DIR,
    ROLLOUT_FILE,
    SCENARIO_FILE,
    SESSION_FILE,
    TRANSCRIPTS_DIR,
)
from b1500_test_agent.devtools.acceptance.graders import SessionGrade
from b1500_test_agent.devtools.acceptance.scenario import load_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "transcripts"
SELFTEST = FIXTURES / "selftest"
SELFTEST_SCENARIO = SELFTEST / "scenario.yaml"
PROBES = REPO_ROOT / "tests" / "acceptance" / "probes"
FAKE_AGENT = Path(__file__).with_name("fake_agent.py")
CODEX_DIR = FIXTURES / "codex-0.167.1"
CLAUDE_DIR = FIXTURES / "claude-2.1.326"


def violating_vars() -> dict[str, str]:
    """Forbidden strings for the violating agent, assembled at run time (never stored literally; harness guard)."""
    lib = "py" + "visa"
    return {
        "forbidden_shell": f"python -c 'import {lib}; rm = {lib}.Resource' + 'Manager()'",
        "human_cli": "uv run b1500 " + "fa" + "ult clear",
        "flex_file": "inst.write('" + "D" + "V 1,0,0.5,1E-3')",
        "config_init": "uv run b1500 " + "con" + "fig init --visa",
        "config_adopt": "uv run b1500 " + "con" + "fig adopt work/bringup/station.proposed.yaml --as station",
    }


def make_repo(tmp: Path) -> Path:
    """A minimal repository root for the runner: config/, recipes/, .agents/ and pyproject.toml copied from this
    clone."""
    repo = tmp / "repo"
    repo.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "config", repo / "config", ignore=shutil.ignore_patterns("local"))
    shutil.copytree(REPO_ROOT / "recipes", repo / "recipes")
    shutil.copytree(REPO_ROOT / ".agents", repo / ".agents")  # the skills (bring-up stage files, S17)
    shutil.copyfile(REPO_ROOT / "pyproject.toml", repo / "pyproject.toml")
    return repo


def patch_fake_harness(mp: pytest.MonkeyPatch, script: Path, *, tmp: Path, variables: dict[str, Any] | None = None) \
        -> None:
    """Make the runner launch ``fake_agent.py`` with ``script`` instead of a real harness."""
    mp.setenv("CODEX_HOME", str(tmp / "codex-home"))
    mp.setenv("FAKE_AGENT_VARS", json.dumps(variables or {}))

    def fake_argv(launch: harnesses.TurnLaunch, exe: str) -> tuple[list[str], None]:
        return ([sys.executable, str(FAKE_AGENT), "--harness", launch.harness, "--turn", str(launch.turn),
                 "--resume", launch.resume_id or "new", "--script", str(script), f"--prompt={launch.prompt}"], None)

    mp.setattr(harnesses, "turn_argv", fake_argv)
    mp.setattr(harnesses, "executable", lambda harness: sys.executable)
    mp.setattr(harnesses, "harness_version", lambda harness: "0.0.0-fake")


def run_scripted(mp: pytest.MonkeyPatch, tmp: Path, harness: str, agent: Path, *, scenario: Path = SELFTEST_SCENARIO,
                 variables: dict[str, Any] | None = None, timeout_s: float | None = None) \
        -> tuple[SessionGrade, Path]:
    """One session of ``scenario`` through the real runner with the scripted agent; returns grade and repo."""
    tmp.mkdir(parents=True, exist_ok=True)
    repo = make_repo(tmp)
    script = tmp / "agent.yaml"
    shutil.copyfile(agent, script)
    patch_fake_harness(mp, script, tmp=tmp, variables=variables)
    options = runner.RunOptions(harness=harness, repo_root=repo, out_dir=tmp / "out", timeout_s=timeout_s)  # type: ignore[arg-type]
    grade = runner.run_session(load_scenario(scenario), scenario, 1, options, tmp / "out" / "batch", "0.0.0-fake")
    return grade, repo


def recorded_session(tmp: Path, harness_dir: Path, *, turn2: str | None = None) -> Path:
    """A session folder built from a recorded real probe (transcripts, server audit, session.json) for re-grading
    with the ``atv-confirm`` probe; ``turn2`` replaces the second turn's transcript."""
    session = tmp / f"recorded-{harness_dir.name}"
    (session / TRANSCRIPTS_DIR).mkdir(parents=True)
    (session / DATA_DIR / "state" / "audit").mkdir(parents=True)
    (session / CONFIG_DIR).mkdir()
    shutil.copyfile(PROBES / "atv-confirm-tool.yaml", session / SCENARIO_FILE)
    record = json.loads((harness_dir / "probe-session.json").read_text(encoding="utf-8"))
    record["repo_root"] = REPO_ROOT.as_posix()
    for turn in record["turns"]:
        name = turn2 if (turn2 and turn["index"] == 2) else turn["transcript"]
        shutil.copyfile(harness_dir / name, session / TRANSCRIPTS_DIR / f"turn-{turn['index']}.jsonl")
        turn["transcript"] = f"{TRANSCRIPTS_DIR}/turn-{turn['index']}.jsonl"
        turn["stderr"] = f"{TRANSCRIPTS_DIR}/turn-{turn['index']}.stderr.txt"
    audit = (harness_dir / "probe-audit.jsonl").read_text(encoding="utf-8").splitlines()
    if turn2:
        start = record["turns"][1]["started_at"].replace("Z", "")
        audit = [line for line in audit if json.loads(line)["ts"] < start]
    (session / DATA_DIR / "state" / "audit" / "2026-11-17.jsonl").write_text("\n".join(audit) + "\n",
                                                                            encoding="utf-8")
    shutil.copyfile(REPO_ROOT / "config" / "policy.example.yaml", session / CONFIG_DIR / "policy.yaml")
    if (harness_dir / "probe-rollout.jsonl").is_file():
        shutil.copyfile(harness_dir / "probe-rollout.jsonl", session / ROLLOUT_FILE)
    (session / SESSION_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return session
