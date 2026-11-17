"""``b1500 dev mcp-smoke``: config parsing, and the server started exactly as both rendered harness configs say."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app
from b1500_test_agent.devtools import harness, mcp_smoke
from b1500_test_agent.service import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()
needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")


def rendered(tmp_path: Path, name: harness.HarnessName) -> Path:
    """The real clone's config of ``name`` rendered into ``tmp_path`` (the repository itself is not touched)."""
    target = harness.TARGETS[name]
    text = harness.render(target, (ROOT / target.template).read_text(encoding="utf-8"), ROOT)
    path = tmp_path / Path(target.output).name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_launch_from_codex_toml(tmp_path: Path) -> None:
    launch = mcp_smoke.load_launch(rendered(tmp_path, "codex"))
    assert launch.command == "uv"
    assert launch.args == ["run", "--frozen", "--project", ROOT.as_posix(), "b1500-mcp"]
    assert launch.cwd == ROOT.as_posix()
    assert launch.env == {"PYTHONUTF8": "1"}
    assert (launch.startup_timeout_s, launch.tool_timeout_s) == (30, 600)


def test_load_launch_from_mcp_json_expands_variables(tmp_path: Path) -> None:
    config = tmp_path / ".mcp.json"
    config.write_text(json.dumps({"mcpServers": {"b1500": {
        "command": "${UVX:-uv}", "args": ["run", "--project", "${HOME_X}/repo"], "env": {"A": "${MISSING}"}}}}),
        encoding="utf-8")
    launch = mcp_smoke.load_launch(config, environ={"HOME_X": "/h"})
    assert launch.command == "uv"
    assert launch.args == ["run", "--project", "/h/repo"]
    assert launch.env == {"A": ""}
    assert launch.cwd == tmp_path.resolve().as_posix()


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("c.json", '{"mcpServers": {}}'),
        ("c.json", '{"mcpServers": {"b1500": {"type": "http", "command": "x"}}}'),
        ("c.json", "not json"),
        ("c.toml", "[mcp_servers.other]\ncommand = 'x'\n"),
        ("c.yaml", "x: 1"),
    ],
)
def test_load_launch_rejects_unusable_configs(tmp_path: Path, name: str, text: str) -> None:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    with pytest.raises(mcp_smoke.SmokeConfigError):
        mcp_smoke.load_launch(path)


def test_a_server_that_cannot_start_is_a_finding_not_a_crash(tmp_path: Path) -> None:
    launch = mcp_smoke.ServerLaunch(config="x", server="b1500", command="b1500-no-such-command-xyz", args=[],
                                    startup_timeout_s=10)
    report = mcp_smoke.run_smoke(launch)
    assert not report.ok
    assert report.problems


@needs_uv
@pytest.mark.parametrize("name", ["codex", "claude"])
def test_smoke_against_the_rendered_configs(tmp_path: Path, name: harness.HarnessName) -> None:
    """The AC: started exactly as configured, the server lists the ten tools and reports backend sim."""
    data = tmp_path / "data"
    report = mcp_smoke.run_smoke(mcp_smoke.load_launch(rendered(tmp_path, name)), data_dir=data)
    assert report.ok, mcp_smoke.format_report(report)
    assert sorted(report.tools) == sorted(TOOL_NAMES)
    assert (report.backend, report.simulated) == ("sim", True)
    assert report.server_info is not None and report.server_info.startswith("b1500 ")


@needs_uv
def test_cli_mcp_smoke_reports_a_backend_mismatch(tmp_path: Path) -> None:
    config = rendered(tmp_path, "claude")
    result = runner.invoke(app, ["dev", "mcp-smoke", "--config", str(config), "--expect-backend", "visa", "--json"])
    assert result.exit_code == 1
    report = json.loads(result.output)
    assert report["backend"] == "sim" and len(report["tools"]) == 10
    assert any("expected 'visa'" in p for p in report["problems"])
    assert runner.invoke(app, ["dev", "mcp-smoke", "--config", str(tmp_path / "none.json")]).exit_code == 2
