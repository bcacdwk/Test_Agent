"""Harness versions (v2.1 plan §2.1, D-3, D-11; WP21.1): the committed ``config/harness/validated.yaml``, the install
method read from an executable's path (POSIX layouts and Windows paths by injection), the one installer per harness
and its switch commands, the local Windows qualification record, the ``doctor`` line ``harness versions``, and the
acceptance selection that no longer treats a version bump as a change every scenario depends on.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import pytest

from b1500_test_agent.devtools import doctor, harness_versions
from b1500_test_agent.devtools.acceptance.selection import GLOBAL_TOUCHES, glob_matches
from b1500_test_agent.devtools.harness_versions import Installed, install_method
from tests.adapters.stations import write_seed_validated

REPO_ROOT = Path(__file__).resolve().parents[2]
POSIX_LINKS = pytest.mark.skipif(os.name == "nt", reason="POSIX symlink layout")


# -- validated.yaml -------------------------------------------------------------------------------------------------


def test_validated_versions_point_to_their_passing_reports() -> None:
    """Each committed entry names its one install method and a committed PASS report of exactly that version, dated
    the day it was validated: the S1-S18 full-suite report (the WP21.1 seed) or, after a bump by
    ``uv run b1500 dev harness qualify``, that version's qualify report (Claude Code 2.1.332, WP21.9)."""
    validated = harness_versions.load_validated(REPO_ROOT)
    assert (validated.codex.version, validated.codex.install) == ("0.170.0", "npm")
    assert validated.claude.install == "native"
    for name in harness_versions.HARNESSES:
        entry = validated.get(name)
        report = REPO_ROOT / entry.report
        assert report.is_file(), entry.report
        head = report.read_text(encoding="utf-8")[:2000]
        stem = f"docs/acceptance/{entry.validated.isoformat()}-{name}-{entry.version}"
        if entry.report == f"{stem}.md":
            assert f"- Harness: `{name}` {entry.version}" in head
            assert "Result: **PASS** (18/18 scenarios meet the threshold)" in head  # the S1-S18 full suite
        else:
            assert entry.report == f"{stem}-qualify.md", entry.report
            assert f"- Harness: `{name}` {entry.version}" in head and "- Result: **PASS**" in head
            assert "- Ladder: T0 PASS → T1 PASS" in head
    assert validated.codex.validated == date(2026, 11, 26)


@pytest.mark.parametrize(("text", "says"), [
    (("codex: {version: 0.170.0, install: homebrew, validated: 2026-11-26, report: r}\n"
      "claude: {version: 2.1.328, install: native, validated: 2026-11-26, report: r}\n"),
     "install must be 'npm'"),
    (("codex: {version: 2.2, install: npm, validated: 2026-11-26, report: r}\n"
      "claude: {version: 2.1.328, install: native, validated: 2026-11-26, report: r}\n"),
     "codex.version"),
    ("codex: {version: 0.170.0, install: npm, validated: 2026-11-26, report: r}\n", "claude"),
    ("codex: [unclosed\n", "cannot be read"),
])
def test_an_invalid_file_says_why(tmp_path: Path, text: str, says: str) -> None:
    path = tmp_path / harness_versions.VALIDATED_FILE
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(harness_versions.ValidatedError, match=re.escape(says)):
        harness_versions.load_validated(tmp_path)


def test_a_missing_file_says_git_pull(tmp_path: Path) -> None:
    with pytest.raises(harness_versions.ValidatedError, match=r"missing \(git pull\)"):
        harness_versions.load_validated(tmp_path)


def test_a_version_bump_is_not_a_change_every_scenario_depends_on() -> None:
    """``selection.GLOBAL_TOUCHES`` lists the two templates, not ``config/harness/**`` (plan §2.1)."""
    def global_file(path: str) -> bool:
        return any(glob_matches(path, glob) for glob in GLOBAL_TOUCHES)

    assert not global_file("config/harness/validated.yaml")
    assert global_file("config/harness/codex.config.toml") and global_file("config/harness/mcp.json")


# -- versions and install methods ------------------------------------------------------------------------------------


def test_parse_and_order_versions() -> None:
    assert harness_versions.parse_version("codex-cli 0.170.0") == "0.170.0"
    assert harness_versions.parse_version("2.1.328 (Claude Code)") == "2.1.328"
    assert harness_versions.parse_version("codex (development build)") is None
    assert harness_versions.version_key("0.172.0") > harness_versions.version_key("0.170.0")
    assert harness_versions.version_key("2.1.328-beta.1") == (2, 1, 328)


@POSIX_LINKS
def test_install_method_of_the_mac_layouts(tmp_path: Path) -> None:
    """The Mac of 2026-11-26: Codex = the npm package under Homebrew's Node, Claude Code = the native build."""
    package = tmp_path / "opt" / "homebrew" / "lib" / "node_modules" / "@openai" / "codex" / "bin"
    package.mkdir(parents=True)
    (package / "codex.js").write_text("", encoding="utf-8")
    (tmp_path / "opt" / "homebrew" / "bin").mkdir()
    codex = tmp_path / "opt" / "homebrew" / "bin" / "codex"
    codex.symlink_to("../lib/node_modules/@openai/codex/bin/codex.js")
    assert install_method("codex", str(codex)) == "npm"
    versions = tmp_path / "home" / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True)
    (versions / "2.1.328").write_text("", encoding="utf-8")
    (tmp_path / "home" / ".local" / "bin").mkdir(parents=True)
    claude = tmp_path / "home" / ".local" / "bin" / "claude"
    claude.symlink_to(versions / "2.1.328")
    assert install_method("claude", str(claude)) == "native"
    cask = tmp_path / "opt" / "homebrew" / "Caskroom" / "codex" / "0.172.0" / "codex"
    cask.parent.mkdir(parents=True)
    cask.write_text("", encoding="utf-8")
    assert install_method("codex", str(cask)) == "homebrew"
    assert install_method("codex", "/usr/local/cargo/bin/codex") == "other"


@pytest.mark.parametrize(("name", "path", "method"), [
    ("claude", r"C:\Users\lab\.local\bin\claude.exe", "native"),
    ("claude", r"C:\Users\lab\AppData\Local\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_x\claude.exe", "winget"),
    ("claude", r"C:\Users\lab\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\cli.js", "npm"),
    ("codex", r"C:\Users\lab\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js", "npm"),
    ("codex", r"C:\Tools\codex\codex.exe", "other"),
])
def test_install_method_of_windows_paths(name: harness_versions.HarnessName, path: str, method: str) -> None:
    assert install_method(name, path) == method


def test_an_npm_shim_is_recognised_by_its_node_modules_folder(tmp_path: Path) -> None:
    """Windows npm: ``%APPDATA%\\npm\\codex.cmd`` next to ``node_modules\\@openai\\codex`` (no symlink to follow)."""
    npm = tmp_path / "AppData" / "Roaming" / "npm"
    (npm / "node_modules" / "@openai" / "codex").mkdir(parents=True)
    shim = npm / "codex.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    assert install_method("codex", str(shim)) == "npm"
    assert install_method("claude", str(npm / "claude.cmd")) == "other"


def test_find_installed_reads_the_version_and_the_method() -> None:
    found = harness_versions.find_installed(
        "codex", which=lambda name: "/opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js",
        run=lambda argv: (0, "codex-cli 0.170.0\n"))
    assert found == Installed(harness="codex", executable="/opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js",
                              version="0.170.0", raw="codex-cli 0.170.0", method="npm")
    assert harness_versions.find_installed("claude", which=lambda name: None, run=lambda argv: (0, "")) is None
    broken = harness_versions.find_installed("claude", which=lambda name: "/x/.local/bin/claude",
                                             run=lambda argv: (1, "error\n"))
    assert broken is not None and broken.version is None and broken.method == "native"


# -- installers ------------------------------------------------------------------------------------------------------


def test_the_one_installer_per_harness() -> None:
    assert harness_versions.installer_argv("codex", "0.170.0", "/usr/bin/npm") == \
        ["/usr/bin/npm", "install", "-g", "@openai/codex@0.170.0"]
    assert harness_versions.installer_argv("claude", "2.1.328", r"C:\Users\lab\.local\bin\claude.exe") == \
        [r"C:\Users\lab\.local\bin\claude.exe", "install", "2.1.328"]
    assert harness_versions.installer_command("codex", "0.170.0") == "npm install -g @openai/codex@0.170.0"
    assert harness_versions.installer_command("claude", "2.1.328") == "claude install 2.1.328"
    assert harness_versions.native_installer_command("2.1.328", windows=True) == \
        "& ([scriptblock]::Create((irm https://claude.ai/install.ps1))) 2.1.328"
    assert harness_versions.native_installer_command("2.1.328", windows=False) == \
        "curl -fsSL https://claude.ai/install.sh | bash -s 2.1.328"


def _found(name: harness_versions.HarnessName, method: harness_versions.InstallMethod, exe: str) -> Installed:
    return Installed(harness=name, executable=exe, version="9.9.9", raw="9.9.9", method=method)


def test_switch_commands_per_method_and_platform() -> None:
    switch = harness_versions.switch_command
    assert switch("codex", _found("codex", "homebrew", "/opt/homebrew/Caskroom/codex/x/codex"), "0.170.0",
                  windows=False) == ("`brew uninstall codex`, install Node.js LTS if `npm` is missing, then `npm "
                                     "install -g @openai/codex@0.170.0`")
    assert switch("codex", _found("codex", "other", r"C:\Tools\codex.exe"), "0.170.0", windows=True).startswith(
        r"remove the Codex at C:\Tools\codex.exe, ")
    assert switch("claude", _found("claude", "npm", "/usr/local/bin/claude"), "2.1.328", windows=False) == (
        "`claude install 2.1.328` (installs the native build), then `npm uninstall -g @anthropic-ai/claude-code`")
    assert switch("claude", _found("claude", "winget", r"C:\x\claude.exe"), "2.1.328", windows=True) == (
        "`winget uninstall Anthropic.ClaudeCode`, then install the native build: `& ([scriptblock]::Create((irm "
        "https://claude.ai/install.ps1))) 2.1.328`")
    assert "`brew uninstall --cask claude-code`, then install the native build: `curl -fsSL" in switch(
        "claude", _found("claude", "homebrew", "/opt/homebrew/Caskroom/claude-code/x/claude"), "2.1.328",
        windows=False)


# -- local Windows qualification -------------------------------------------------------------------------------------


def test_windows_qualification_record(tmp_path: Path) -> None:
    assert harness_versions.load_windows_qualification(tmp_path) == harness_versions.WindowsQualification()
    path = harness_versions.windows_qualification_path(tmp_path)
    assert path == tmp_path / "harness" / "windows.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"codex": {"version": "0.170.0", "qualified": "2026-12-01",
                                          "report": "work/harness/x.md"}, "future": 1}), encoding="utf-8")
    record = harness_versions.load_windows_qualification(tmp_path)
    assert record is not None and record.version("codex") == "0.170.0" and record.version("claude") is None
    path.write_text("{broken", encoding="utf-8")
    assert harness_versions.load_windows_qualification(tmp_path) is None


# -- doctor: harness versions ---------------------------------------------------------------------------------------

PATHS = {"codex": "/opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js",
         "claude": "/Users/lab/.local/share/claude/versions/2.1.328"}


@pytest.fixture(scope="module")
def seed_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clone with the WP21.1 seed of ``validated.yaml`` (Codex 0.170.0, Claude Code 2.1.328), so the doctor line is
    tested independently of the maintainer's later bumps."""
    repo = tmp_path_factory.mktemp("seed")
    write_seed_validated(repo)
    return repo


def _versions(root: Path, codex: str | None, claude: str | None, *, lab: bool = False,
              paths: dict[str, str] | None = None) -> doctor.DoctorCheck:
    installed = {"codex": codex, "claude": claude}
    where = paths or PATHS
    by_exe = {where[name]: version for name, version in installed.items()}

    def run(argv: list[str]) -> tuple[int | None, str]:
        version = by_exe[argv[0]]
        return (0, f"{version} (x)\n") if version != "garbage" else (0, "development build\n")

    return doctor.check_harness_versions(root, {}, lab=lab, run=run,
                                         which=lambda name: where[name] if installed[name] else None)


def test_doctor_harness_versions_pass_warn_info(seed_repo: Path) -> None:
    passed = _versions(seed_repo, "0.170.0", "2.1.328")
    assert passed.name == "harness versions" and passed.status == "PASS"
    assert passed.detail == "Codex 0.170.0 (npm), Claude Code 2.1.328 (native) = config/harness/validated.yaml"
    assert _versions(seed_repo, "0.170.0", None).status == "PASS"  # Claude Code is optional
    older = _versions(seed_repo, "0.169.0", "2.1.328")
    assert older.status == "WARN" and older.detail == (
        "Codex 0.169.0 installed, 0.170.0 validated; Claude Code 2.1.328 (native) = validated: run `uv run b1500 "
        "update`")
    newer = _versions(seed_repo, "0.170.0", "2.1.330")
    assert newer.status == "WARN" and newer.detail.endswith(
        "run `uv run b1500 update` or qualify it: `uv run b1500 dev harness qualify`")
    assert "qualify" not in _versions(seed_repo, "0.170.0", "2.1.330", lab=True).detail  # the lab PC never qualifies
    none = _versions(seed_repo, None, None)
    assert none.status == "INFO" and "no harness CLI on PATH" in none.detail and "Codex 0.170.0" in none.detail
    unreadable = _versions(seed_repo, "garbage", "2.1.328")
    assert unreadable.status == "WARN" and "Codex: cannot read its version" in unreadable.detail


def test_doctor_warns_about_another_install_method(seed_repo: Path) -> None:
    npm_claude = "/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js"
    check = _versions(seed_repo, "0.170.0", "2.1.328", paths={**PATHS, "claude": npm_claude})
    assert check.status == "WARN" and "Claude Code at /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js " \
        "is a npm install, the validated one is native" in check.detail


def test_doctor_without_the_file_warns(tmp_path: Path) -> None:
    check = doctor.check_harness_versions(tmp_path, {}, lab=False, which=lambda name: None, run=lambda argv: (0, ""))
    assert check.status == "WARN" and "validated.yaml is missing" in check.detail
