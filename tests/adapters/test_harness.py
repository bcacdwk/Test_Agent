"""Harness wiring (blueprint 5.4): ``b1500 harness init --codex|--claude [--check]``, the committed harness files and
the doctor check. Generated configs are rendered into temporary clones whose path has spaces and non-ASCII
characters; the committed examples, settings, rules and hook are checked in place."""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.devtools import doctor, harness
from b1500_test_agent.paths import ENV_HOME
from b1500_test_agent.service import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ("config/harness", ".codex/config.example.toml", ".codex/rules", ".mcp.example.json",
             ".claude/settings.json", "scripts/hooks", "pyproject.toml")
runner = CliRunner()


def make_clone(tmp_path: Path) -> Path:
    """A temporary clone holding the committed harness files, under a path with spaces and non-ASCII characters."""
    root = tmp_path / "Lab Clone 测试 µ" / "test_agent"
    for rel in COMMITTED:
        source = ROOT / rel
        if source.is_dir():
            shutil.copytree(source, root / rel)
        else:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, root / rel)
    return root


def template(name: harness.HarnessName) -> str:
    return (ROOT / harness.TARGETS[name].template).read_text(encoding="utf-8")


# -- committed files ---------------------------------------------------------------------------------------------------


def test_committed_harness_files_are_wired_and_examples_match_templates() -> None:
    checked, problems = harness.committed_problems(ROOT, harness.TARGETS)
    assert problems == []
    assert {".claude/settings.json", ".codex/rules/b1500.rules", ".mcp.example.json", ".codex/config.example.toml",
            "scripts/hooks/b1500_guard.py"} <= set(checked)


def test_examples_carry_the_placeholder_not_a_local_path() -> None:
    for target in harness.TARGETS.values():
        text = (ROOT / target.example).read_text(encoding="utf-8")
        assert harness.EXAMPLE_REPO in text
        assert str(ROOT) not in text and ROOT.as_posix() not in text
        assert harness.REPO_TOKEN not in text and harness.NOTE_TOKEN not in text


def test_claude_settings_have_confirm_tool_in_ask_only_and_the_deny_rules() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    perms = settings["permissions"]
    assert perms["ask"] == ["mcp__b1500__run_confirmed_plan"]
    assert sorted(perms["allow"]) == sorted(f"mcp__b1500__{t}" for t in TOOL_NAMES if t != "run_confirmed_plan")
    assert set(perms["deny"]) == harness.CLAUDE_DENY
    assert all("run_confirmed_plan" not in rule for rule in perms["allow"] + perms["deny"])


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda s: s["permissions"]["allow"].append("mcp__b1500__run_confirmed_plan"), "allow must be exactly"),
        (lambda s: s["permissions"]["allow"].append("mcp__b1500"), "allow must be exactly"),
        (lambda s: s["permissions"].update(ask=[]), "ask must be exactly"),
        (lambda s: s["permissions"]["deny"].remove("Edit(data/**)"), "deny lacks"),
        (lambda s: s["permissions"]["deny"].append("mcp__b1500__run_confirmed_plan"), "must be asked, not denied"),
        (lambda s: s["permissions"].update(defaultMode="bypassPermissions"), "bypassPermissions"),
        (lambda s: s.pop("hooks"), "does not cover"),
        (lambda s: s["hooks"]["PreToolUse"][0].update(matcher="Bash"), "does not cover"),
    ],
)
def test_settings_check_detects_weakening(mutate: Callable[[dict], object], fragment: str) -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    mutate(settings)
    problems = harness.claude_settings_problems(json.dumps(settings))
    assert any(fragment in p for p in problems), problems


def test_rules_check_detects_a_missing_or_weakened_rule() -> None:
    text = (ROOT / ".codex" / "rules" / "b1500.rules").read_text(encoding="utf-8")
    assert harness.codex_rules_problems(text) == []
    weakened = text.replace('decision = "forbidden"', 'decision = "prompt"', 1)
    assert harness.codex_rules_problems(weakened) != []


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed")
@pytest.mark.parametrize(
    ("argv", "decision"),
    [
        (["b1500", "fault", "clear"], "forbidden"),
        (["uv", "run", "b1500", "fault", "clear"], "forbidden"),
        (["b1500", "run", "--confirm", "P-X"], "forbidden"),
        (["uv", "run", "b1500", "run", "--confirm", "P-X"], "forbidden"),
        (["uv", "run", "b1500", "run", "P-X"], None),
        (["b1500", "status"], None),
    ],
)
def test_codex_parses_and_applies_the_rules(argv: list[str], decision: str | None) -> None:
    """``codex execpolicy check`` loads the rules file (its match/not_match examples are verified at load time)."""
    result = subprocess.run(["codex", "execpolicy", "check", "--rules", str(ROOT / ".codex/rules/b1500.rules"), *argv],
                            capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout).get("decision") == decision


# -- rendering -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "repo",
    [
        PureWindowsPath(r"C:\Users\张 三\05 Manuals\test_agent"),
        PurePosixPath("/Users/x/OneDrive-个人/Files/05 Manuals/test_agent"),
        PurePosixPath('/tmp/odd "quoted" back\\slash\ttab/test_agent'),
    ],
)
def test_rendered_paths_survive_toml_and_json(repo: PurePosixPath | PureWindowsPath) -> None:
    expected = repo.as_posix()
    codex = tomllib.loads(harness.render(harness.TARGETS["codex"], template("codex"), repo))["mcp_servers"]["b1500"]
    claude = json.loads(harness.render(harness.TARGETS["claude"], template("claude"), repo))["mcpServers"]["b1500"]
    assert codex["args"] == claude["args"] == ["run", "--frozen", "--project", expected, "b1500-mcp"]
    assert codex["cwd"] == expected
    if isinstance(repo, PureWindowsPath):
        assert expected == "C:/Users/张 三/05 Manuals/test_agent"


def test_rendered_codex_config_has_the_per_tool_approval_modes() -> None:
    text = harness.render(harness.TARGETS["codex"], template("codex"), PurePosixPath("/lab/test_agent"))
    server = tomllib.loads(text)["mcp_servers"]["b1500"]
    assert server["default_tools_approval_mode"] == "auto"
    assert {tool: cfg["approval_mode"] for tool, cfg in server["tools"].items()} == {
        "run_plan": "approve", "run_confirmed_plan": "prompt", "safe_shutdown": "approve"}
    assert (server["command"], server["startup_timeout_sec"], server["tool_timeout_sec"]) == ("uv", 30, 600)
    assert server["env"] == {"PYTHONUTF8": "1"}
    assert harness.codex_config_problems(text, "/lab/test_agent") == []
    weakened = text.replace('approval_mode = "prompt"', 'approval_mode = "approve"')
    assert any("run_confirmed_plan" in p for p in harness.codex_config_problems(weakened, "/lab/test_agent"))


# -- init / check in a temporary clone ------------------------------------------------------------------------------


def test_init_renders_both_configs_and_check_passes(tmp_path: Path) -> None:
    root = make_clone(tmp_path)
    report = harness.init(root, ["codex", "claude"])
    assert report.ok, report.problems
    assert report.written == [".codex/config.toml", ".mcp.json"]
    repo = root.resolve().as_posix()
    codex = tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]["b1500"]
    claude = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["b1500"]
    assert codex["args"][3] == claude["args"][3] == repo
    assert "测试 µ" in repo and " " in repo
    assert harness.check(root, ["codex", "claude"]).ok
    again = harness.init(root, ["codex", "claude"])
    assert again.ok and again.written == [] and again.unchanged == [".codex/config.toml", ".mcp.json"]


def test_check_fails_on_drift_and_on_missing_generated_configs(tmp_path: Path) -> None:
    root = make_clone(tmp_path)
    missing = harness.check(root, ["codex", "claude"])
    assert not missing.ok
    assert any(".codex/config.toml: missing" in p for p in missing.problems)
    harness.init(root, ["codex", "claude"])
    config = root / ".codex" / "config.toml"
    config.write_text(config.read_text(encoding="utf-8").replace('"prompt"', '"approve"'), encoding="utf-8")
    drift = harness.check(root, ["codex"])
    assert not drift.ok
    assert any("differs from config/harness/codex.config.toml" in p for p in drift.problems)
    assert any("run_confirmed_plan.approval_mode" in p for p in drift.problems)
    assert harness.init(root, ["codex"]).ok  # a config written by init is re-rendered
    assert harness.check(root, ["codex"]).ok


def test_check_fails_when_a_template_changes_without_the_example(tmp_path: Path) -> None:
    root = make_clone(tmp_path)
    tpl = root / "config" / "harness" / "mcp.json"
    tpl.write_text(tpl.read_text(encoding="utf-8").replace('"1"', '"0"'), encoding="utf-8")
    problems = harness.check(root, ["claude"]).problems
    assert any(".mcp.example.json: differs" in p for p in problems)
    assert any("PYTHONUTF8" in p for p in problems)


def test_init_keeps_a_foreign_config_unless_forced(tmp_path: Path) -> None:
    root = make_clone(tmp_path)
    foreign = {"mcpServers": {"other": {"command": "x"}, "b1500": {"command": "python"}}}
    (root / ".mcp.json").write_text(json.dumps(foreign), encoding="utf-8")
    refused = harness.init(root, ["claude"])
    assert not refused.ok and refused.written == []
    assert json.loads((root / ".mcp.json").read_text(encoding="utf-8")) == foreign
    assert harness.init(root, ["claude"], force=True).ok


def test_example_rewrite_only_on_request(tmp_path: Path) -> None:
    root = make_clone(tmp_path)
    (root / ".mcp.example.json").write_text("{}", encoding="utf-8")
    assert not harness.init(root, ["claude"]).ok
    report = harness.init(root, ["claude"], examples=True)
    assert report.ok and ".mcp.example.json" in report.written


# -- CLI -----------------------------------------------------------------------------------------------------------


def test_cli_harness_init_and_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_clone(tmp_path)
    monkeypatch.setenv(ENV_HOME, str(root))
    assert runner.invoke(app, ["harness", "init"]).exit_code == 2
    checked = runner.invoke(app, ["harness", "init", "--codex", "--check"])
    assert checked.exit_code == 1 and ".codex/config.toml: missing" in checked.output
    written = runner.invoke(app, ["harness", "init", "--codex", "--claude"])
    assert written.exit_code == 0, written.output
    assert "wrote      .codex/config.toml" in written.output
    result = runner.invoke(app, ["harness", "init", "--codex", "--claude", "--check", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ok"] is True
    assert not (root / ".codex" / "config.example.toml").read_text(encoding="utf-8").count(str(root))


# -- doctor ----------------------------------------------------------------------------------------------------------


def test_doctor_harness_check(tmp_path: Path) -> None:
    root = make_clone(tmp_path)
    assert doctor.check_harness_files(root).status == "WARN"
    harness.init(root, ["codex"])
    passed = doctor.check_harness_files(root)
    assert passed.status == "PASS", passed.detail
    assert "run_confirmed_plan prompt" in passed.detail and "claude: not generated" in passed.detail
    harness.init(root, ["claude"])
    both = doctor.check_harness_files(root)
    assert both.status == "PASS" and "run_confirmed_plan ask" in both.detail
    (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    assert doctor.check_harness_files(root).status == "FAIL"
