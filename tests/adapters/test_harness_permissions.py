"""The owner-authorized harness permission change sets, each applied once by the orchestrator: OD-5 (blueprint v2
§12 OD-5, §0 row 32, §10.0 guardrail 5; WP6.1) to ``.claude/settings.json`` and ``.codex/rules/b1500.rules``, and
OD21-6 (v2.1 plan §9; WP21.5: the three step-ledger commands ``bringup next|done|check``) to ``.claude/settings.json``,
and the owner decision of 2026-11-27 (WP21.9: the four exact read-only ``doctor`` lines; ``--wgfmu-session`` still
asks) to ``.claude/settings.json``.

The change sets are written in ``docs/deployment-windows.md`` §"Harness permissions"; these tests assert the applied
files carry exactly those lines, that the document and ``devtools/harness.py`` agree, and (with the Codex CLI
installed) that ``codex execpolicy check`` forbids the configuration bootstrap with and without ``uv run`` while
read-only manual queries and the bring-up commands stay unmatched. Command strings are lists of argv words, never
shell text.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from b1500_test_agent.devtools import harness

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / ".claude" / "settings.json"
RULES = ROOT / ".codex" / "rules" / "b1500.rules"
DEPLOYMENT = ROOT / "docs" / "deployment-windows.md"

B1500 = "b1500"
OD5_ALLOW = [
    f"Bash(uv run {B1500} manual *)",
    f"Bash(uv run {B1500} bringup status*)",
    f"Bash(uv run {B1500} bringup propose-station*)",
    f"Bash(uv run {B1500} bringup capture*)",
    f"Bash(uv run {B1500} bringup record*)",
]
OD21_6_ALLOW = [
    f"Bash(uv run {B1500} bringup next*)",
    f"Bash(uv run {B1500} bringup done*)",
    f"Bash(uv run {B1500} bringup check*)",
]
DOCTOR_ALLOW = [
    f"Bash(uv run {B1500} doctor)",
    f"Bash(uv run {B1500} doctor --json)",
    f"Bash(uv run {B1500} doctor --probe)",
    f"Bash(uv run {B1500} doctor --probe --json)",
]
OD5_DENY = [
    f"Bash({B1500} config init*)",
    f"Bash(uv run {B1500} config init*)",
    f"Bash({B1500} config adopt*)",
    f"Bash(uv run {B1500} config adopt*)",
]
OD5_FORBIDDEN = [
    [B1500, "config", "init"],
    ["uv", "run", B1500, "config", "init"],
    [B1500, "config", "adopt"],
    ["uv", "run", B1500, "config", "adopt"],
]


def harness_section() -> str:
    text = DEPLOYMENT.read_text(encoding="utf-8")
    match = re.search(r"^## Harness permissions\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "docs/deployment-windows.md has no '## Harness permissions' section"
    return match.group(0)


def test_claude_settings_carry_the_od5_lines() -> None:
    perms = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]
    assert set(OD5_ALLOW) <= set(perms["allow"]) and set(OD5_DENY) <= set(perms["deny"])
    assert not set(OD5_ALLOW) & set(perms["deny"]) and not set(OD5_DENY) & set(perms["allow"])
    assert perms["ask"] == ["mcp__b1500__run_confirmed_plan"]
    assert harness.claude_settings_problems(SETTINGS.read_text(encoding="utf-8")) == []


def test_claude_settings_carry_the_od21_6_lines() -> None:
    """WP21.5: the three step-ledger commands are allowed, nothing else changed (allow = OD-5 + OD21-6 + the nine
    tools; WP21.9 adds the doctor lines, next test), and ``uv run b1500 harness init --claude --check`` accepts the
    file."""
    perms = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]
    assert set(OD21_6_ALLOW) <= set(perms["allow"]) and not set(OD21_6_ALLOW) & set(perms["deny"])
    tools = {f"mcp__b1500__{tool}" for tool in harness.TOOL_NAMES if tool != harness.CONFIRM_TOOL}
    assert set(perms["allow"]) == tools | set(OD5_ALLOW) | set(OD21_6_ALLOW) | set(DOCTOR_ALLOW)
    assert len(perms["allow"]) == len(set(perms["allow"])) == 21
    assert harness.claude_settings_problems(SETTINGS.read_text(encoding="utf-8")) == []


def test_claude_settings_carry_the_four_exact_doctor_lines() -> None:
    """WP21.9 (owner decision 2026-11-27): ``doctor`` and ``doctor --probe``, each also with ``--json``, are allowed as
    exact lines (no wildcard), so ``--wgfmu-session`` (it opens the WGFMU library session) and any other option or
    argument still ask."""
    perms = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]
    assert set(DOCTOR_ALLOW) <= set(perms["allow"]) and not set(DOCTOR_ALLOW) & set(perms["deny"])
    doctor = [rule for rule in perms["allow"] if "doctor" in rule]
    assert sorted(doctor) == sorted(DOCTOR_ALLOW) and not any("*" in rule for rule in doctor)
    assert not any("wgfmu-session" in rule for rule in perms["allow"])


@pytest.mark.parametrize("lines", [OD21_6_ALLOW, DOCTOR_ALLOW], ids=["od21_6", "doctor"])
def test_a_settings_file_without_a_change_set_is_a_problem(lines: list[str]) -> None:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    data["permissions"]["allow"] = [rule for rule in data["permissions"]["allow"] if rule not in lines]
    problems = harness.claude_settings_problems(json.dumps(data))
    assert problems and all(line in problems[0] for line in lines)


def test_a_settings_file_with_a_doctor_wildcard_is_a_problem() -> None:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    data["permissions"]["allow"] = [*data["permissions"]["allow"], f"Bash(uv run {B1500} doctor*)"]
    assert harness.claude_settings_problems(json.dumps(data))


def test_codex_rules_forbid_the_configuration_bootstrap() -> None:
    text = RULES.read_text(encoding="utf-8")
    assert harness.codex_rules_problems(text) == []
    for prefix in OD5_FORBIDDEN:
        assert json.dumps(prefix) in text, prefix
    # every rule carries match / not_match examples (Codex verifies them when it loads the file)
    rules = re.findall(r"prefix_rule\((.*?)\n\)", text, re.DOTALL)
    assert len(rules) == 8 and all("match = [" in r and "not_match = [" in r for r in rules)


def test_the_code_expects_exactly_the_documented_change_set() -> None:
    assert harness.CLAUDE_ALLOW_OD5 == frozenset(OD5_ALLOW)
    assert harness.CLAUDE_ALLOW_OD21_6 == frozenset(OD21_6_ALLOW)
    assert harness.CLAUDE_ALLOW_DOCTOR == frozenset(DOCTOR_ALLOW)
    assert harness.CLAUDE_ALLOW_COMMANDS == frozenset(OD5_ALLOW + OD21_6_ALLOW + DOCTOR_ALLOW)
    assert set(OD5_DENY) <= harness.CLAUDE_DENY
    assert {tuple(p) for p in OD5_FORBIDDEN} <= set(harness.FORBIDDEN_PREFIXES)
    section = harness_section()
    for line in [*OD5_ALLOW, *OD21_6_ALLOW, *DOCTOR_ALLOW, *OD5_DENY]:
        assert f'"{line}"' in section, line
    assert "OD21-6" in section and "2026-11-27" in section and "--wgfmu-session" in section
    for prefix in OD5_FORBIDDEN:
        assert json.dumps(prefix) in section, prefix


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed")
@pytest.mark.parametrize(
    ("argv", "decision"),
    [
        *[(prefix, "forbidden") for prefix in OD5_FORBIDDEN],
        (["uv", "run", B1500, "config", "adopt", "work/bringup/station.proposed.yaml", "--as", "station"],
         "forbidden"),
        (["uv", "run", B1500, "manual", "search", "x"], None),
        (["uv", "run", B1500, "bringup", "propose-station"], None),
        (["uv", "run", B1500, "bringup", "next"], None),
        (["uv", "run", B1500, "bringup", "done", "L1.A4", "--run", "H20261201T093012Z-1a2b"], None),
        (["uv", "run", B1500, "bringup", "check", "--all"], None),
        (["uv", "run", B1500, "config", "check"], None),
    ],
)
def test_codex_execpolicy_applies_the_od5_rules(argv: list[str], decision: str | None) -> None:
    result = subprocess.run(["codex", "execpolicy", "check", "--rules", str(RULES), *argv], capture_output=True,
                            text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout).get("decision") == decision
