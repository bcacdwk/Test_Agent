"""``uv run b1500 update`` (v2.1 plan §2.2): the operator's one command that brings this clone and its harnesses up
to date and says plainly whether the station is ready.

Steps, one line each, then ``Ready.`` (exit 0) or ``Not ready. Do this:`` with a numbered list (exit 1):

1. **guard**: refuses inside an agent session (a harness marker in the environment: ``CLAUDECODE``,
   ``CLAUDE_CODE_ENTRYPOINT``, ``AI_AGENT``, ``CODEX_SANDBOX*``, ``CODEX_MANAGED_BY_*``) and without an interactive
   terminal (two independent conditions); ``--check`` runs anywhere.
2. **repo**: on the default branch with a clean tracked tree, ``git pull --ff-only``. A changed tracked file, another
   branch, diverged history or no network stops it with one plain action; nothing is changed.
3. **environment**: ``uv sync --frozen``; when the pull brought commits it re-runs itself from the pulled code
   (``update --continue``: steps 4-8), so a change to ``update`` takes effect in the same call. Offline
   (``UV_OFFLINE``) with a changed ``uv.lock``: a new wheelhouse is needed (it stops before syncing).
4. **wiring**: ``harness init --check`` per generated config; drift is re-rendered (``harness init``) and checked
   again; a harness CLI without its config is a note, no config at all an action.
5. **versions**: each installed harness against ``config/harness/validated.yaml`` (``harness_versions``); another
   version is installed after a y/N question with the one installer per harness, then read again; another install
   method gets its one-time switch command; a missing CLI is skipped (Claude Code is optional), none at all is an
   action.
6. **hold** (lab station = backend ``visa``): Claude Code's auto-update off (``DISABLE_AUTOUPDATER`` in the environment
   or the user settings' ``env``; never ``DISABLE_UPDATES``) and, on Windows, the local qualification of the validated
   versions; notes, never a block.
7. **checks** (free): signed in (``codex login status``, ``claude auth status``), no bypass default in the user
   configs, ``claude doctor`` lists no invalid entry of ``.claude/settings.json`` (ATV-34), ``codex execpolicy
   check`` forbids the eight human-only commands, the clone trusted by each harness, ``dev mcp-smoke`` per generated
   config, ``b1500 doctor`` without FAIL.
8. **verdict**.

Fail-safe rule: output ``update`` cannot read (a changed ``claude doctor`` wording, an unreadable user config) is a
note, never a block: the same versions passed the maintainer's checks first. ``--check`` changes nothing (no pull,
sync, re-render or install; only the harnesses' own status commands and a throw-away server start run).
``operator_checks`` runs the checks of step 7 one by one per harness for the maintainer's ``dev harness qualify``
(T0, ``harness_qualify.py``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, Field

from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.devtools import doctor, harness, harness_versions, mcp_smoke
from b1500_test_agent.devtools.acceptance import harnesses as harness_runtime
from b1500_test_agent.devtools.harness_versions import HARNESSES, LABELS, HarnessName, Installed
from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.paths import Paths, find_repo_root

AGENT_MARKERS: Final = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT")
AGENT_MARKER_PREFIXES: Final = ("CODEX_SANDBOX", "CODEX_MANAGED_BY_")
"""Environment variables a harness sets in the shells of its agent (Codex's npm launcher sets ``CODEX_MANAGED_BY_*``;
its sandboxed shells ``CODEX_SANDBOX*``, ATV-40)."""
REFUSAL: Final = "Run `uv run b1500 update` yourself in a terminal window, not through the agent."
STEPS: Final = ("guard", "repo", "environment", "wiring", "versions", "hold", "checks")
PULL_TIMEOUT_S: Final = 300.0
SYNC_TIMEOUT_S: Final = 1800.0
INSTALL_TIMEOUT_S: Final = 1800.0
STATUS_TIMEOUT_S: Final = 60.0
LIST_MAX: Final = 4
_NETWORK = ("could not resolve host", "unable to access", "failed to connect", "could not read from remote",
            "connection timed out", "network is unreachable", "operation timed out", "connection refused",
            "connection reset", "ssl", "proxy", "could not connect")
_DIVERGED = ("not possible to fast-forward", "diverg", "cannot fast-forward", "non-fast-forward")

StepName = Literal["guard", "repo", "environment", "wiring", "versions", "hold", "checks"]
StepStatus = Literal["ok", "changed", "skipped", "action", "refused"]


class UpdateStep(BaseModel):
    """One step line: ``action`` when it added to the list of things to do."""

    step: StepName
    status: StepStatus
    detail: str


class UpdateReport(BaseModel):
    """What ``update`` did and found; ``ready`` is the verdict."""

    mode: Literal["update", "check", "continue"]
    ready: bool = False
    refused: bool = False
    steps: list[UpdateStep] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list, description="Numbered list of what the human does next.")
    notes: list[str] = Field(default_factory=list, description="Facts worth knowing that block nothing.")
    handed_over: int | None = Field(default=None, description="Exit code of `update --continue` run from the "
                                                              "pulled code (the verdict is that process's).")


@dataclass(frozen=True)
class Output:
    """A finished command: exit code (``None`` = could not run: missing, timeout, OS error), stdout and stderr."""

    code: int | None
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def text(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()

    def last_line(self) -> str:
        lines = [line.strip() for line in self.text.splitlines() if line.strip()]
        return lines[-1] if lines else ("could not run" if self.code is None else f"exit {self.code}")


@dataclass
class UpdateContext:
    """Everything ``update`` touches, injectable for tests (platform, environment, home folder, prompts, server
    smoke test, doctor, station facts)."""

    repo: Path
    environ: Mapping[str, str]
    windows: bool
    home: Path
    interactive: bool
    ask: Callable[[str], bool]
    say: Callable[[str], None]
    station: tuple[bool, Path, str] | None = None
    """``(lab station, state dir, backend)``; ``None`` = read from the configuration."""
    smoke: Callable[[Path, str], tuple[bool, str]] | None = None
    doctor_report: Callable[[], doctor.DoctorReport] | None = None

    @classmethod
    def default(cls, *, interactive: bool, ask: Callable[[str], bool], say: Callable[[str], None]) -> UpdateContext:
        return cls(repo=find_repo_root(), environ=os.environ, windows=sys.platform == "win32", home=Path.home(),
                   interactive=interactive, ask=ask, say=say)

    def env(self, name: str) -> str | None:
        """An environment variable; case-insensitive on Windows (PowerShell ``$env:`` names)."""
        if not self.windows:
            return self.environ.get(name)
        return next((v for k, v in self.environ.items() if k.upper() == name.upper()), None)

    def which(self, name: str) -> str | None:
        return shutil.which(name, path=self.env("PATH") or os.defpath)

    def run(self, argv: list[str], *, timeout: float = STATUS_TIMEOUT_S, cwd: Path | None = None,
            terminal: bool = False, live: bool = False) -> Output:
        """Run ``argv``; ``terminal`` keeps standard input (git credential prompts), ``live`` also the output."""
        try:
            result = subprocess.run(argv, cwd=cwd, env=dict(self.environ), timeout=timeout, check=False,
                                    stdin=None if terminal or live else subprocess.DEVNULL,
                                    capture_output=not live, text=True, encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError) as exc:
            return Output(None, "", str(exc))
        return Output(result.returncode, result.stdout or "", result.stderr or "")

    def runner(self) -> harness_versions.Runner:
        def run(argv: list[str]) -> tuple[int | None, str]:
            out = self.run(argv, timeout=harness_versions.VERSION_TIMEOUT_S)
            return out.code, out.text
        return run


@dataclass
class _Record:
    """The report under construction; prints each step line as it is decided."""

    ctx: UpdateContext
    report: UpdateReport
    _actions: dict[str, int] = field(default_factory=dict)

    def action(self, step: str, text: str) -> None:
        self.report.actions.append(text)
        self._actions[step] = self._actions.get(step, 0) + 1

    def note(self, text: str) -> None:
        self.report.notes.append(text)

    def step(self, step: StepName, detail: str, *, changed: bool = False, skipped: bool = False) -> None:
        status: StepStatus = ("action" if self._actions.get(step) else "changed" if changed
                              else "skipped" if skipped else "ok")
        self.report.steps.append(UpdateStep(step=step, status=status, detail=detail))
        self.ctx.say(f"{step:<12} {status:<8} {detail}")


def _listed(items: list[str]) -> str:
    more = f" (+{len(items) - LIST_MAX} more)" if len(items) > LIST_MAX else ""
    return ", ".join(items[:LIST_MAX]) + more


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


# -- 1 guard ---------------------------------------------------------------------------------------------------------


def agent_markers(environ: Mapping[str, str]) -> list[str]:
    """The harness markers present in ``environ`` (names compared in upper case: Windows names are case-free)."""
    return sorted(name for name in environ if name.upper() in AGENT_MARKERS
                  or name.upper().startswith(AGENT_MARKER_PREFIXES))


def _guard(ctx: UpdateContext, rec: _Record, *, check: bool) -> bool:
    if check:
        rec.step("guard", "--check changes nothing and runs anywhere", skipped=True)
        return True
    markers = agent_markers(ctx.environ)
    if not markers and ctx.interactive:
        rec.step("guard", "interactive terminal, no agent session")
        return True
    why = (f"agent session marker {', '.join(markers)} in the environment" if markers
           else "no interactive terminal (standard input is not a terminal)")
    rec.report.refused = True
    rec.report.steps.append(UpdateStep(step="guard", status="refused", detail=f"{why}; nothing was changed"))
    ctx.say(f"{'guard':<12} {'refused':<8} {why}; nothing was changed")
    return False


# -- 2 repo ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Pulled:
    before: str
    after: str
    lock_changed: bool


def _pull_problem(text: str, default: str) -> str:
    low = text.lower()
    if any(key in low for key in _DIVERGED):
        return (f"this clone has commits that are not on origin/{default} (the histories diverged): nothing was "
                "changed; ask the maintainer")
    if any(key in low for key in _NETWORK):
        return ("git could not reach origin (no network, proxy or sign-in problem): nothing was changed; connect "
                "and run `uv run b1500 update` again")
    if "no tracking information" in low:
        return f"branch {default} has no upstream (origin/{default}): nothing was changed; ask the maintainer"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return f"git pull failed ({lines[-1] if lines else 'no output'}): nothing was changed; ask the maintainer"


def _repo(ctx: UpdateContext, rec: _Record, *, check: bool) -> _Pulled | None:
    git = ctx.which("git")
    if git is None:
        rec.action("repo", "Git is not on PATH: install Git for Windows (deployment Step 1), then run `uv run b1500 "
                           "update` again")
        rec.step("repo", "git not found")
        return None

    def g(*args: str, timeout: float = STATUS_TIMEOUT_S, terminal: bool = False) -> Output:
        return ctx.run([git, "-C", str(ctx.repo), *args], timeout=timeout, terminal=terminal)

    head = g("rev-parse", "--abbrev-ref", "HEAD")
    if not head.ok:
        rec.action("repo", f"{ctx.repo.as_posix()} is not a usable git clone ({head.last_line()}): ask the "
                           "maintainer")
        rec.step("repo", "not a git clone")
        return None
    branch = head.stdout.strip()
    origin_head = g("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    default = origin_head.stdout.strip().removeprefix("origin/") if origin_head.ok and origin_head.stdout.strip() \
        else "main"
    found: list[str] = []
    if branch != default:
        rec.action("repo", f"the clone is on {'a detached HEAD' if branch == 'HEAD' else f'branch {branch}'}, not "
                           f"{default}: `git switch {default}`, then run `uv run b1500 update` again (nothing was "
                           "changed)")
        found.append(f"on {branch}, not {default}")
    status = g("status", "--porcelain=v1", "--untracked-files=no")
    dirty = [line[3:].strip() for line in status.stdout.splitlines() if line.strip()]
    if not status.ok or dirty:
        listed = _listed(dirty) if dirty else status.last_line()
        rec.action("repo", f"tracked files are changed in this clone ({listed}): nothing was changed; ask the "
                           "maintainer (files under git are never edited on this PC)")
        found.append(f"{len(dirty)} changed tracked file(s)")
    if check:  # report every finding and go on: --check changes nothing
        counts = g("rev-list", "--left-right", "--count", "HEAD...@{upstream}").stdout.split()
        behind = int(counts[1]) if len(counts) == 2 and counts[1].isdigit() else 0
        if behind:
            rec.note(f"origin/{default} had {behind} newer commit(s) at the last fetch: `uv run b1500 update` pulls "
                     "them")
        rec.step("repo", f"{branch}, {', '.join(found) or 'clean'} (--check: nothing fetched)")
        return _Pulled("", "", False)
    if found:
        rec.step("repo", "; ".join(found))
        return None
    before = g("rev-parse", "HEAD").stdout.strip()
    pull = g("pull", "--ff-only", timeout=PULL_TIMEOUT_S, terminal=True)
    if not pull.ok:
        rec.action("repo", _pull_problem(pull.text, default))
        rec.step("repo", f"git pull --ff-only failed on {default}")
        return None
    after = g("rev-parse", "HEAD").stdout.strip()
    if before == after:
        rec.step("repo", f"{default} is up to date ({after[:7]})")
        return _Pulled(before, after, False)
    changed = g("diff", "--name-only", before, after).stdout.splitlines()
    count = g("rev-list", "--count", f"{before}..{after}").stdout.strip() or "?"
    rec.step("repo", f"pulled {before[:7]}..{after[:7]} ({count} commit(s)) on {default}", changed=True)
    return _Pulled(before, after, "uv.lock" in {name.strip() for name in changed})


# -- 3 environment ---------------------------------------------------------------------------------------------------


def _environment(ctx: UpdateContext, rec: _Record, pulled: _Pulled, *, check: bool) -> bool:
    """Sync the environment; returns False when the update stops here or was handed to the pulled code."""
    uv = ctx.which("uv")
    if uv is None:
        rec.action("environment", "uv is not on PATH: install uv (deployment Step 1), then run `uv run b1500 "
                                  "update` again")
        rec.step("environment", "uv not found")
        return False
    project = ["--project", str(ctx.repo)]
    if check:
        out = ctx.run([uv, "sync", "--frozen", "--check", "--offline", *project], timeout=STATUS_TIMEOUT_S * 2)
        if out.ok:
            rec.step("environment", "matches uv.lock")
        elif out.code is None:
            rec.note(f"could not check the environment against uv.lock ({out.last_line()})")
            rec.step("environment", "not checked")
        else:
            rec.action("environment", "the environment does not match uv.lock: run `uv run b1500 update`")
            rec.step("environment", "differs from uv.lock")
        return True
    if pulled.lock_changed and _truthy(ctx.env("UV_OFFLINE")):
        rec.action("environment", "a new wheelhouse is needed: this pull changed uv.lock and uv is offline "
                                  "(UV_OFFLINE); build it on the Mac and install it (deployment-windows.md § Offline "
                                  "wheelhouse), then run `uv run b1500 update` again")
        rec.step("environment", "uv.lock changed, offline: not synced")
        return False
    out = ctx.run([uv, "sync", "--frozen", *project], timeout=SYNC_TIMEOUT_S, terminal=True)
    if not out.ok:
        rec.action("environment", f"`uv sync --frozen` failed ({out.last_line()}): close every Codex and Claude "
                                  "Code window (a running b1500 server keeps its files open on Windows), then run "
                                  "`uv run b1500 update` again")
        rec.step("environment", "uv sync --frozen failed")
        return False
    rec.step("environment", f"uv sync --frozen: {out.last_line()}")
    if pulled.before != pulled.after:
        ctx.say("update: continuing with the pulled code (update --continue)")
        child = ctx.run([uv, "run", "--frozen", *project, "b1500", "update", "--continue"], cwd=ctx.repo, live=True,
                        timeout=SYNC_TIMEOUT_S * 2)
        rec.report.handed_over = 1 if child.code is None else child.code
        if child.code is None:
            ctx.say(f"update --continue could not run ({child.last_line()}): run `uv run b1500 update` again")
        return False
    return True


# -- 4 wiring --------------------------------------------------------------------------------------------------------


def _wiring(ctx: UpdateContext, rec: _Record, *, check: bool) -> list[HarnessName]:
    """Check and repair the generated configs; returns the harnesses that have one."""
    generated: list[HarnessName] = [n for n, t in harness.TARGETS.items() if (ctx.repo / t.output).is_file()]
    for name in HARNESSES:
        if name not in generated and ctx.which(name) is not None and generated:
            rec.note(f"{LABELS[name]} is installed but not wired in this clone: `uv run b1500 harness init "
                     f"{harness.TARGETS[name].init_flag}` if you use it")
    if not generated:
        rec.action("wiring", "no harness is wired in this clone: `uv run b1500 harness init --codex` (and "
                             "`--claude` for Claude Code), then run `uv run b1500 update` again")
        rec.step("wiring", "no generated harness config")
        return generated
    repaired: list[str] = []
    for name in generated:
        target = harness.TARGETS[name]
        found = harness.check(ctx.repo, [name])
        if found.ok:
            continue
        if check:
            rec.action("wiring", f"{found.problems[0]}: `uv run b1500 update` (or `uv run b1500 harness init "
                                 f"{target.init_flag}`) re-renders it")
            continue
        harness.init(ctx.repo, [name])
        again = harness.check(ctx.repo, [name])
        if again.ok:
            repaired.append(target.output)
            continue
        more = f" (+{len(again.problems) - 1} more: `uv run b1500 harness init {target.init_flag} --check`)" \
            if len(again.problems) > 1 else ""
        rec.action("wiring", f"{again.problems[0]}{more}")
    outputs = ", ".join(harness.TARGETS[n].output for n in generated)
    rec.step("wiring", f"{outputs} checked" + (f"; re-rendered {', '.join(repaired)}" if repaired else ""),
             changed=bool(repaired))
    return generated


# -- 5 versions ------------------------------------------------------------------------------------------------------


def _install(ctx: UpdateContext, rec: _Record, found: Installed, want: str) -> Installed | None:
    """Install ``want`` with the one installer of the harness after the human's y/N; the CLI read again."""
    name, label = found.harness, LABELS[found.harness]
    command = harness_versions.installer_command(name, want)
    if not ctx.ask(f"Install {label} {want} now (installed: {found.version})?"):
        rec.action("versions", f"{label} {found.version} is not the validated {want}: run `uv run b1500 update` "
                               f"again and answer y, or install it yourself: `{command}`")
        return None
    tool = ctx.which("npm") if name == "codex" else found.executable
    if tool is None:
        rec.action("versions", f"npm is not on PATH: install Node.js LTS (deployment Step 1), then run `uv run b1500 "
                               f"update` again (it runs `{command}`)")
        return None
    ctx.say(f"installing {label} {want}: {command}")
    out = ctx.run(harness_versions.installer_argv(name, want, tool), timeout=INSTALL_TIMEOUT_S, terminal=True)
    again = harness_versions.find_installed(name, which=ctx.which, run=ctx.runner())
    if out.ok and again is not None and again.version == want:
        return again
    now = again.version if again is not None else "none"
    fallback = (f"`{harness_versions.native_installer_command(want, windows=ctx.windows)}`" if name == "claude"
                else f"`{command}`")
    result = f"the installer failed ({out.last_line()})" if not out.ok else f"`{name} --version` now says {now}"
    rec.action("versions", f"{label} {want} was not installed: {result}; install it yourself with {fallback}, then run "
                           "`uv run b1500 update` again")
    return None


def _versions(ctx: UpdateContext, rec: _Record, *, check: bool) -> dict[HarnessName, Installed]:
    """Bring each installed harness to its validated version; returns the CLIs that are on it."""
    try:
        validated = harness_versions.load_validated(ctx.repo)
    except harness_versions.ValidatedError as exc:
        rec.action("versions", f"{exc}; ask the maintainer")
        rec.step("versions", "no validated versions")
        return {}
    ready: dict[HarnessName, Installed] = {}
    parts: list[str] = []
    present = 0
    changed = False
    for name in HARNESSES:
        want, label = validated.get(name), LABELS[name]
        found = harness_versions.find_installed(name, which=ctx.which, run=ctx.runner())
        if found is None:
            parts.append(f"{label} not installed" + (" (optional)" if name == "claude" else ""))
            continue
        present += 1
        if found.method != want.install:
            switch = harness_versions.switch_command(name, found, want.version, windows=ctx.windows)
            rec.action("versions", f"{label} at {found.executable} is a {found.method} install, the validated one is "
                                   f"{want.install} (one install method per harness): {switch}; then run `uv run "
                                   "b1500 update` again")
            parts.append(f"{label} {found.version or '?'} ({found.method}, not {want.install})")
            continue
        if found.version is None:
            rec.note(f"could not read `{name} --version` ({found.raw!r}); the validated version is {want.version}")
            parts.append(f"{label} version unreadable")
            continue
        if found.version == want.version:
            ready[name] = found
            parts.append(f"{label} {found.version} = validated")
            continue
        if check:
            rec.action("versions", f"{label} {found.version} is installed, {want.version} is validated: run `uv run "
                                   "b1500 update`")
            parts.append(f"{label} {found.version} != {want.version}")
            continue
        installed = _install(ctx, rec, found, want.version)
        if installed is None:
            parts.append(f"{label} {found.version} != {want.version}")
            continue
        ready[name] = installed
        changed = True
        parts.append(f"{label} {found.version} -> {want.version} (installed)")
    if present == 0:
        rec.action("versions", "no coding harness is installed: install Codex (deployment Step 1: Node.js LTS, then "
                               f"`{harness_versions.installer_command('codex', validated.codex.version)}`), sign in, "
                               "then run `uv run b1500 update` again")
    rec.step("versions", "; ".join(parts), changed=changed)
    return ready


# -- 6 hold ----------------------------------------------------------------------------------------------------------


def claude_settings_path(ctx: UpdateContext) -> Path:
    """Claude Code's user settings (``$CLAUDE_CONFIG_DIR/settings.json`` or ``~/.claude/settings.json``)."""
    base = ctx.env("CLAUDE_CONFIG_DIR")
    return Path(base) / "settings.json" if base else ctx.home / ".claude" / "settings.json"


def codex_home(ctx: UpdateContext) -> Path:
    base = ctx.env("CODEX_HOME")
    return Path(base) if base else ctx.home / ".codex"


def _read_json(path: Path) -> tuple[dict[str, object] | None, str | None]:
    """``(data, None)``, ``({}, None)`` when the file is missing, ``(None, reason)`` when unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError) as exc:
        return None, str(exc)
    return (data, None) if isinstance(data, dict) else (None, "not a JSON object")


def _hold(ctx: UpdateContext, rec: _Record, *, lab: bool, backend: str, state_dir: Path,
          ready: dict[HarnessName, Installed]) -> None:
    if not lab:
        rec.step("hold", f"not the lab station (backend {backend}): nothing to hold", skipped=True)
        return
    parts: list[str] = []
    if ctx.which("claude") is not None:
        path = claude_settings_path(ctx)
        settings, problem = _read_json(path)
        raw = settings.get("env") if settings else None
        env: dict[str, object] = raw if isinstance(raw, dict) else {}
        if _truthy(ctx.env("DISABLE_UPDATES")) or _truthy(str(env.get("DISABLE_UPDATES", ""))):
            rec.note("DISABLE_UPDATES is set: it also blocks `claude install`, which `update` uses; remove it "
                     "(DISABLE_AUTOUPDATER=1 is the setting that holds the version)")
        if _truthy(ctx.env("DISABLE_AUTOUPDATER")):
            parts.append("Claude Code auto-update off (environment)")
        elif _truthy(str(env.get("DISABLE_AUTOUPDATER", ""))):
            parts.append(f"Claude Code auto-update off ({path.name})")
        else:
            unread = f" (it cannot be read now: {problem})" if problem else ""
            rec.note(f"Claude Code updates itself: add \"env\": {{\"DISABLE_AUTOUPDATER\": \"1\"}} to {path}{unread} "
                     "once (never DISABLE_UPDATES, which also blocks `claude install`)")
            parts.append("Claude Code auto-update on")
    if ctx.which("codex") is not None:
        parts.append("Codex from npm does not update itself")
    if ctx.windows and ready:
        record = harness_versions.load_windows_qualification(state_dir)
        missing = [f"{LABELS[n]} {found.version}" for n, found in ready.items()
                   if record is None or record.version(n) != found.version]
        if missing:
            rec.note(f"maintainer: run `uv run b1500 dev harness qualify --windows` once ({', '.join(missing)} not "
                     "yet qualified on this PC)")
        parts.append(f"Windows qualification {'missing for ' + ', '.join(missing) if missing else 'recorded'}")
    rec.step("hold", "; ".join(parts) or "no harness installed")


# -- 7 checks --------------------------------------------------------------------------------------------------------


def codex_bypass(text: str) -> list[str]:
    """The bypass defaults of a Codex config (top level and every ``[profiles.*]`` table)."""
    data = tomllib.loads(text)
    profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    tables = [("", data), *((f"profiles.{k}.", v) for k, v in profiles.items() if isinstance(v, dict))]
    found = []
    for where, table in tables:
        if table.get("sandbox_mode") == "danger-full-access":
            found.append(f'{where}sandbox_mode = "danger-full-access"')
        if table.get("approval_policy") == "never":
            found.append(f'{where}approval_policy = "never"')
    return found


def claude_doctor_entries(text: str) -> list[str] | None:
    """The entries of the ``Invalid settings`` section of ``claude doctor`` (``None`` when the output is not a
    ``claude doctor`` report); each entry with its continuation lines."""
    if "claude code doctor" not in text.lower():
        return None
    entries: list[str] = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower() == "invalid settings":
            inside = True
        elif inside and not stripped:
            if entries:
                inside = False
        elif inside and stripped.startswith("- "):
            entries.append(stripped[2:])
        elif inside and entries:
            entries[-1] += f" {stripped}"
    return entries


def _project_entry(entry: str, repo: Path) -> bool:
    low = entry.replace("\\", "/").lower()
    roots = {repo.as_posix().lower(), repo.resolve().as_posix().lower()}
    return any(f"{root}/.claude/settings.json" in low for root in roots)


def _signed_in(ctx: UpdateContext, rec: _Record, present: dict[HarnessName, str], parts: list[str]) -> None:
    signed = []
    for name, exe in present.items():
        argv = [exe, "login", "status"] if name == "codex" else [exe, "auth", "status"]
        out = ctx.run(argv)
        if out.ok:
            signed.append(LABELS[name])
        elif out.code is None:
            rec.note(f"could not run `{' '.join([name, *argv[1:]])}` ({out.last_line()})")
        else:
            login = "codex login" if name == "codex" else "claude auth login"
            rec.action("checks", f"{LABELS[name]} is not signed in: run `{login}`")
    if signed:
        parts.append(f"signed in: {', '.join(signed)}")


def _bypass(ctx: UpdateContext, rec: _Record, present: dict[HarnessName, str], parts: list[str]) -> None:
    clean = True
    if "codex" in present:
        home = codex_home(ctx)
        for path in [home / "config.toml", *sorted(home.glob("*.config.toml"))]:
            try:
                found = codex_bypass(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except (OSError, tomllib.TOMLDecodeError) as exc:
                rec.note(f"could not read {path} ({exc}); it must not set sandbox_mode = \"danger-full-access\" or "
                         "approval_policy = \"never\"")
                continue
            if found:
                clean = False
                rec.action("checks", f"Codex defaults to full access in {path}: remove {', '.join(found)}, then "
                                     "restart Codex (deployment step 8.2)")
    if "claude" in present:
        for path in (claude_settings_path(ctx), ctx.repo / ".claude" / "settings.local.json"):
            data, problem = _read_json(path)
            if data is None:
                rec.note(f"could not read {path} ({problem}); it must not set \"defaultMode\": \"bypassPermissions\"")
                continue
            perms = data.get("permissions")
            if isinstance(perms, dict) and perms.get("defaultMode") == "bypassPermissions":
                clean = False
                rec.action("checks", f"Claude Code defaults to bypass mode in {path}: remove \"defaultMode\": "
                                     "\"bypassPermissions\" (deployment step 9.3)")
    if present and clean:
        parts.append("no bypass default")


def _claude_doctor(ctx: UpdateContext, rec: _Record, exe: str, parts: list[str]) -> None:
    out = ctx.run([exe, "doctor"], cwd=ctx.repo)
    entries = claude_doctor_entries(out.stdout) if out.ok else None
    if entries is None:
        rec.note(f"could not read `claude doctor` ({out.last_line()}); `/doctor` in a Claude Code session shows "
                 "invalid settings too")
        return
    project = [e for e in entries if _project_entry(e, ctx.repo)]
    other = [e for e in entries if e not in project]
    if project:
        rec.action("checks", f"Claude Code ignores parts of .claude/settings.json: {project[0]}"
                             + (f" (+{len(project) - 1} more)" if len(project) > 1 else "")
                             + "; do not use Claude Code here and ask the maintainer")
    for entry in other[:LIST_MAX]:
        rec.note(f"`claude doctor` reports an invalid setting outside the project file: {entry}")
    if not project:
        parts.append("claude doctor: project settings valid")


def _execpolicy(ctx: UpdateContext, rec: _Record, exe: str, parts: list[str]) -> None:
    rules = ctx.repo / harness.CODEX_RULES
    allowed, unread = [], []
    for prefix in harness.FORBIDDEN_PREFIXES:
        out = ctx.run([exe, "execpolicy", "check", "--rules", str(rules), *prefix])
        data = _json(out.stdout) if out.ok else None
        if not isinstance(data, dict):
            unread.append(" ".join(prefix))
        elif data.get("decision") != "forbidden":
            allowed.append(" ".join(prefix))
    if allowed:
        rec.action("checks", f"Codex does not forbid {_listed([f'`{a}`' for a in allowed])} with {harness.CODEX_RULES}:"
                             " do not use Codex here and ask the maintainer")
    if unread:
        rec.note(f"could not read `codex execpolicy check` for {_listed(unread)}")
    if not allowed and not unread:
        parts.append(f"Codex forbids the {len(harness.FORBIDDEN_PREFIXES)} human-only commands")


def _json(text: str) -> object | None:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _trusted(ctx: UpdateContext, rec: _Record, present: dict[HarnessName, str], parts: list[str]) -> None:
    env = {**ctx.environ, "CODEX_HOME": str(codex_home(ctx))}
    checks = {"codex": lambda: harness_runtime.codex_project_trusted(ctx.repo, env),
              "claude": lambda: harness_runtime.claude_project_trusted(ctx.repo, env)}
    trusted = []
    for name in present:
        state = checks[name]()
        if state is True:
            trusted.append(LABELS[name])
        elif state is None:
            rec.note(f"could not read whether {LABELS[name]} trusts this clone")
        else:
            rec.action("checks", f"{LABELS[name]} does not trust this clone yet: start `{name}` in the clone once and "
                                 "accept the trust question, then close it")
    if trusted:
        parts.append(f"trusted by {', '.join(trusted)}")


def default_smoke(config: Path, backend: str) -> tuple[bool, str]:
    """``dev mcp-smoke``: the server starts as ``config`` says, ten tools, the configured backend."""
    try:
        report = mcp_smoke.run_smoke(mcp_smoke.load_launch(config), expect_backend=backend)
    except mcp_smoke.SmokeConfigError as exc:
        return False, str(exc)
    return report.ok, (f"{len(report.tools)} tools" if report.ok else (report.problems or ["failed"])[0])


def _servers(ctx: UpdateContext, rec: _Record, generated: list[HarnessName], backend: str, parts: list[str]) -> None:
    smoke = ctx.smoke or default_smoke
    started = []
    for name in generated:
        rel = harness.TARGETS[name].output
        ok, detail = smoke(ctx.repo / rel, backend)
        if ok:
            started.append(f"{rel} {detail}")
        else:
            expect = f" --expect-backend {backend}" if backend != "sim" else ""
            rec.action("checks", f"the b1500 server does not start as {rel} says ({detail}): details with `uv run "
                                 f"b1500 dev mcp-smoke --config {rel}{expect}`; ask the maintainer")
    if started:
        parts.append(f"server starts ({', '.join(started)})")


def _doctor(ctx: UpdateContext, rec: _Record, parts: list[str]) -> None:
    try:
        report = (ctx.doctor_report or (lambda: doctor.run_doctor(environ=ctx.environ, windows=ctx.windows)))()
    except Exception as exc:  # noqa: BLE001 - a doctor that cannot run is a note, never a block
        rec.note(f"`uv run b1500 doctor` could not run here ({type(exc).__name__}: {exc})")
        return
    fails = [c for c in report.checks if c.status == "FAIL"]
    for check in fails[:LIST_MAX]:
        rec.action("checks", f"`uv run b1500 doctor` FAIL {check.name}: {check.detail}")
    if len(fails) > LIST_MAX:
        rec.action("checks", f"`uv run b1500 doctor` has {len(fails) - LIST_MAX} more FAIL line(s)")
    warns = sum(c.status == "WARN" for c in report.checks)
    if not fails:
        parts.append(f"doctor without FAIL ({warns} WARN)")


def _checks(ctx: UpdateContext, rec: _Record, generated: list[HarnessName], backend: str) -> None:
    present: dict[HarnessName, str] = {n: exe for n in HARNESSES if (exe := ctx.which(n)) is not None}
    parts: list[str] = []
    _signed_in(ctx, rec, present, parts)
    _bypass(ctx, rec, present, parts)
    if "claude" in present:
        _claude_doctor(ctx, rec, present["claude"], parts)
    if "codex" in present:
        _execpolicy(ctx, rec, present["codex"], parts)
    _trusted(ctx, rec, present, parts)
    if generated:
        _servers(ctx, rec, generated, backend, parts)
    _doctor(ctx, rec, parts)
    rec.step("checks", "; ".join(parts) or "nothing passed")


@dataclass(frozen=True)
class OperatorCheck:
    """One free check of step 7 for one harness (``harness`` ``None``: independent of the harness): the step-line
    parts it contributed, its actions and its notes."""

    name: str
    harness: HarnessName | None
    passed: tuple[str, ...]
    actions: tuple[str, ...]
    notes: tuple[str, ...]


def operator_checks(ctx: UpdateContext, harnesses: Iterable[HarnessName], *, backend: str) -> list[OperatorCheck]:
    """The free checks of step 7, one ``OperatorCheck`` per check and installed harness of ``harnesses`` plus the
    harness-independent ``doctor`` (read-only, like ``--check``). A harness without its generated config gets a
    ``server`` action (the server must start as the harness's config says)."""
    found: list[OperatorCheck] = []

    def run(name: str, harness: HarnessName | None, check: Callable[[_Record, list[str]], None]) -> None:
        rec = _Record(ctx, UpdateReport(mode="check"))
        parts: list[str] = []
        check(rec, parts)
        found.append(OperatorCheck(name=name, harness=harness, passed=tuple(parts), actions=tuple(rec.report.actions),
                                   notes=tuple(rec.report.notes)))

    for name in harnesses:
        exe = ctx.which(name)
        if exe is None:
            continue
        one = {name: exe}
        run("signed in", name, lambda rec, parts, one=one: _signed_in(ctx, rec, one, parts))
        run("bypass default", name, lambda rec, parts, one=one: _bypass(ctx, rec, one, parts))
        if name == "claude":
            run("claude doctor", name, lambda rec, parts, exe=exe: _claude_doctor(ctx, rec, exe, parts))
        else:
            run("execpolicy", name, lambda rec, parts, exe=exe: _execpolicy(ctx, rec, exe, parts))
        run("trusted", name, lambda rec, parts, one=one: _trusted(ctx, rec, one, parts))
        target = harness.TARGETS[name]
        if (ctx.repo / target.output).is_file():
            run("server", name, lambda rec, parts, name=name: _servers(ctx, rec, [name], backend, parts))
        else:
            run("server", name, lambda rec, parts, target=target: rec.action(
                "checks", f"{target.output} is missing: `uv run b1500 harness init {target.init_flag}`"))
    run("doctor", None, lambda rec, parts: _doctor(ctx, rec, parts))
    return found


# -- run -------------------------------------------------------------------------------------------------------------


def station_facts(ctx: UpdateContext) -> tuple[bool, Path, str]:
    """``(lab station, state dir, backend)`` from the active configuration (backend ``visa`` = the lab station)."""
    if ctx.station is not None:
        return ctx.station
    try:
        paths = Paths.from_env(ctx.environ, repo_root=ctx.repo)
    except InvalidConfigError:
        return False, ctx.repo / "data" / "state", "sim"
    loader = ConfigLoader(paths)
    try:
        bundle = loader.get()
    except InvalidConfigError:
        return False, paths.state_dir, "sim"
    return bundle.backend == "visa", bundle.paths.state_dir, bundle.backend


def run_update(ctx: UpdateContext, *, check: bool = False, continued: bool = False) -> UpdateReport:
    """Run the steps of the module docstring; never raises for a finding."""
    mode: Literal["update", "check", "continue"] = "check" if check else "continue" if continued else "update"
    rec = _Record(ctx, UpdateReport(mode=mode))
    ctx.say(f"b1500 update{' --check (changes nothing)' if check else ''}: clone {ctx.repo.as_posix()}")
    if not _guard(ctx, rec, check=check):
        return rec.report
    if not continued:
        pulled = _repo(ctx, rec, check=check)
        if pulled is None or not _environment(ctx, rec, pulled, check=check):
            return rec.report
    lab, state_dir, backend = station_facts(ctx)
    generated = _wiring(ctx, rec, check=check)
    ready = _versions(ctx, rec, check=check)
    _hold(ctx, rec, lab=lab, backend=backend, state_dir=state_dir, ready=ready)
    _checks(ctx, rec, generated, backend)
    rec.report.ready = not rec.report.actions
    return rec.report


def format_verdict(report: UpdateReport) -> str:
    """The notes, then ``Ready.`` or ``Not ready. Do this:`` with the numbered actions (or the refusal)."""
    lines = [f"note: {note}" for note in report.notes]
    if report.refused:
        return "\n".join([*lines, REFUSAL])
    if report.ready:
        return "\n".join([*lines, "Ready."])
    return "\n".join([*lines, "Not ready. Do this:", *(f"{i}. {a}" for i, a in enumerate(report.actions, 1))])
