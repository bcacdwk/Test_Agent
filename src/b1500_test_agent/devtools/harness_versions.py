"""Harness versions (v2.1 plan §2.1, D-3, D-11): the committed truth ``config/harness/validated.yaml``, the installed
version and install method of each harness CLI, and the one installer per harness.

- **Validated versions**: ``config/harness/validated.yaml`` names, per harness, the version the maintainer qualified,
  its install method, the date and the report. ``uv run b1500 update`` installs exactly these versions;
  ``uv run b1500 doctor`` compares them with the installed CLIs (line ``harness versions``).
- **One install method per harness on every OS** (D-11): Codex is the npm package ``@openai/codex``
  (``npm install -g @openai/codex@<version>``), Claude Code the native build (``claude install <version>``).
  Anything else (Homebrew, WinGet, a standalone binary, Claude Code through npm) gets a one-time switch command.
- **Install method from the executable path** (no harness is started): npm when the path (or its symlink target)
  lies in ``node_modules/<package>`` or an npm shim sits next to ``node_modules/<package>`` (Windows
  ``%APPDATA%\\npm\\codex.cmd``; POSIX ``<prefix>/bin`` next to ``<prefix>/lib/node_modules``); native Claude Code
  under ``~/.local/share/claude/versions/`` or as ``~/.local/bin/claude[.exe]``; Homebrew under ``Caskroom``/``Cellar``;
  WinGet under ``WinGet``; ``other`` otherwise.
- **Local Windows qualification** (§2.2, §2.3): ``<state_dir>/harness/windows.json`` records the versions the
  maintainer qualified on this lab PC (``uv run b1500 dev harness qualify --windows`` writes it, WP21.2); ``update``
  adds a note while the validated version is not in it.

Commands run here are read-only (``--version``); installers are run by ``update`` only, after a human's y/N.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

HarnessName = Literal["codex", "claude"]
InstallMethod = Literal["npm", "native", "homebrew", "winget", "other"]

HARNESSES: Final[tuple[HarnessName, ...]] = ("codex", "claude")
LABELS: Final[dict[HarnessName, str]] = {"codex": "Codex", "claude": "Claude Code"}
VALIDATED_FILE: Final = "config/harness/validated.yaml"
INSTALL_METHOD: Final[dict[HarnessName, InstallMethod]] = {"codex": "npm", "claude": "native"}
"""The one install method per harness (D-11)."""
NPM_PACKAGES: Final[dict[HarnessName, str]] = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code"}
VERSION_TIMEOUT_S: Final = 30.0
WINDOWS_QUALIFICATION: Final = ("harness", "windows.json")
"""Below the state directory: the local Windows qualification record (written by WP21.2's ``--windows``)."""
_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.]+)?")

Runner = Callable[[list[str]], tuple[int | None, str]]
"""``argv -> (exit code or None when it could not run, stdout + stderr)``."""
Which = Callable[[str], str | None]


class ValidatedError(ValueError):
    """``config/harness/validated.yaml`` is missing or invalid."""


class ValidatedVersion(BaseModel):
    """One harness entry of ``validated.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(strict=True, pattern=r"^\d+\.\d+\.\d+([-+.][0-9A-Za-z.]+)?$",
                         description="The validated version (a string: quote a version YAML reads as a number).")
    install: InstallMethod
    validated: date = Field(description="When the maintainer qualified it.")
    report: str = Field(min_length=1, description="The acceptance or qualify report, repository-relative.")


class ValidatedHarnesses(BaseModel):
    """``config/harness/validated.yaml``: the versions ``update`` installs, one entry per harness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex: ValidatedVersion
    claude: ValidatedVersion

    @model_validator(mode="after")
    def _one_install_method(self) -> ValidatedHarnesses:
        for name in HARNESSES:
            entry = self.get(name)
            if entry.install != INSTALL_METHOD[name]:
                raise ValueError(f"{name}: install must be {INSTALL_METHOD[name]!r} (one install method per harness), "
                                 f"found {entry.install!r}")
        return self

    def get(self, name: HarnessName) -> ValidatedVersion:
        return self.codex if name == "codex" else self.claude


def load_validated(repo_root: Path) -> ValidatedHarnesses:
    """The validated versions of ``repo_root``; raises ``ValidatedError`` with a plain reason."""
    path = repo_root / VALIDATED_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidatedError(f"{VALIDATED_FILE} is missing (git pull)") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ValidatedError(f"{VALIDATED_FILE} cannot be read: {exc}") from exc
    try:
        return ValidatedHarnesses.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "file"
        raise ValidatedError(f"{VALIDATED_FILE} is invalid: {where}: {first['msg']}") from exc


# -- installed CLIs --------------------------------------------------------------------------------------------------


class Installed(BaseModel):
    """A harness CLI found on ``PATH``: where, which version (``None`` when unreadable) and how it was installed."""

    model_config = ConfigDict(frozen=True)

    harness: HarnessName
    executable: str
    version: str | None
    raw: str = Field(description="What --version printed (first line).")
    method: InstallMethod


def parse_version(text: str) -> str | None:
    """The first ``x.y.z`` version in ``text`` (``codex-cli 0.170.0``, ``2.1.328 (Claude Code)``)."""
    match = _VERSION.search(text)
    return match.group() if match else None


def version_key(version: str) -> tuple[int, ...]:
    """Numeric sort key of a version (``2.1.328`` -> ``(2, 1, 328)``; a suffix is ignored)."""
    core = re.split(r"[-+]", version, maxsplit=1)[0]
    return tuple(int(part) for part in re.findall(r"\d+", core)[:3])


def _norm(path: str) -> str:
    return path.replace("\\", "/").lower()


def install_method(harness: HarnessName, executable: str) -> InstallMethod:
    """How the CLI at ``executable`` was installed, from its path, its symlink target and an npm shim's folder (see
    the module docstring). Windows paths work on every OS (separators and case are normalized)."""
    resolved = os.path.realpath(executable) if os.path.exists(executable) else executable
    texts = (_norm(executable), _norm(resolved))
    package = NPM_PACKAGES[harness]
    exe = Path(executable)
    shim_dirs = (exe.parent / "node_modules", exe.parent.parent / "lib" / "node_modules") if exe.is_absolute() else ()
    if any(f"/node_modules/{package}/" in f"{text}/" for text in texts) or \
            any((folder / package).is_dir() for folder in shim_dirs):
        return "npm"
    if harness == "claude" and (any("/.local/share/claude/versions/" in text for text in texts)
                                or re.search(r"/\.local/bin/claude(\.[a-z]+)?$", texts[0])):
        return "native"
    if any("/caskroom/" in text or "/cellar/" in text for text in texts):
        return "homebrew"
    if any("/winget/" in text for text in texts):
        return "winget"
    return "other"


def run_text(argv: list[str], environ: Mapping[str, str] | None = None,
             timeout: float = VERSION_TIMEOUT_S) -> tuple[int | None, str]:
    """Run ``argv`` without a terminal and return ``(exit code, stdout + stderr)``; ``None`` when it could not run."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, stdin=subprocess.DEVNULL, check=False,
                                env=None if environ is None else dict(environ))
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    return result.returncode, f"{result.stdout}{result.stderr}"


def find_installed(harness: HarnessName, *, which: Which, run: Runner) -> Installed | None:
    """The harness CLI on ``PATH`` with its version and install method; ``None`` when it is not installed."""
    executable = which(harness)
    if executable is None:
        return None
    code, text = run([executable, "--version"])
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    version = parse_version(first) if code == 0 else None
    return Installed(harness=harness, executable=executable, version=version, raw=first or f"exit {code}",
                     method=install_method(harness, executable))


def default_which(environ: Mapping[str, str]) -> Which:
    """``shutil.which`` over the ``PATH`` of ``environ``."""
    path = environ.get("PATH") or environ.get("Path") or os.defpath
    return lambda name: shutil.which(name, path=path)


# -- installers ------------------------------------------------------------------------------------------------------


def installer_argv(harness: HarnessName, version: str, executable: str) -> list[str]:
    """The one installer per harness; ``executable`` is ``npm`` (Codex) or the installed ``claude`` (Claude Code)."""
    if harness == "codex":
        return [executable, "install", "-g", f"{NPM_PACKAGES['codex']}@{version}"]
    return [executable, "install", version]


def installer_command(harness: HarnessName, version: str) -> str:
    """The installer as the human types it."""
    return " ".join(installer_argv(harness, version, "npm" if harness == "codex" else "claude"))


def native_installer_command(version: str, *, windows: bool) -> str:
    """The documented Claude Code native installer with a version argument (ATV-39 fallback when ``claude install``
    leaves another version in place; PowerShell on Windows)."""
    if windows:
        return f"& ([scriptblock]::Create((irm https://claude.ai/install.ps1))) {version}"
    return f"curl -fsSL https://claude.ai/install.sh | bash -s {version}"


def switch_command(harness: HarnessName, found: Installed, version: str, *, windows: bool) -> str:
    """The one-time switch from another install method to the one of D-11 (a message; ``update`` never runs it)."""
    target = f"`{installer_command(harness, version)}`"
    where = f"the {LABELS[harness]} at {found.executable}"
    if harness == "codex":
        remove = {"homebrew": "`brew uninstall codex`"}.get(found.method, f"remove {where}")
        return f"{remove}, install Node.js LTS if `npm` is missing, then {target}"
    native = f"`{native_installer_command(version, windows=windows)}`"
    if found.method == "npm":
        return f"{target} (installs the native build), then `npm uninstall -g {NPM_PACKAGES['claude']}`"
    remove = {"homebrew": "`brew uninstall --cask claude-code`",
              "winget": "`winget uninstall Anthropic.ClaudeCode`"}.get(found.method, f"remove {where}")
    return f"{remove}, then install the native build: {native}"


# -- local Windows qualification -------------------------------------------------------------------------------------


class QualifiedVersion(BaseModel):
    """One harness version qualified on this PC (``dev harness qualify --windows``)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    version: str
    qualified: str = Field(description="ISO date or timestamp of the qualification.")
    report: str | None = Field(default=None, description="Its report (under work/harness/).")


class WindowsQualification(BaseModel):
    """``<state_dir>/harness/windows.json``: the harness versions qualified on this lab PC."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    codex: QualifiedVersion | None = None
    claude: QualifiedVersion | None = None

    def version(self, name: HarnessName) -> str | None:
        entry = self.codex if name == "codex" else self.claude
        return entry.version if entry is not None else None


def windows_qualification_path(state_dir: Path) -> Path:
    return state_dir.joinpath(*WINDOWS_QUALIFICATION)


def load_windows_qualification(state_dir: Path) -> WindowsQualification | None:
    """The local record; an empty one when the file does not exist, ``None`` when it cannot be read."""
    path = windows_qualification_path(state_dir)
    try:
        return WindowsQualification.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return WindowsQualification()
    except (OSError, ValidationError):
        return None
