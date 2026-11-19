"""``b1500 doctor``: installation and station-readiness checks without instrument I/O (blueprint 7).

Each check is PASS, INFO, WARN or FAIL; the command exits non-zero when any check FAILs. Checks: Python version and
architecture; ``uv.lock`` in sync with ``pyproject.toml`` (``uv lock --check --offline``); imports of the runtime
dependencies (``pyvisa`` only located, never imported outside ``transport/visa.py``); configuration (rule R-CFG-01:
schemas, active files example vs local, why the backend was chosen); ``data/`` writable and free space; clone path
length (WARN above 80 characters on Windows); stale inflight marker or latched fault; skills mirror
(``.claude/skills/`` = the generated copy of ``.agents/skills/``: FAIL on drift, WARN when there is no skill); harness
files (the committed ``.claude/settings.json``, Codex rules, guard hook and
examples wired as blueprint 5.4 says; each generated ``.codex/config.toml`` / ``.mcp.json`` free of drift, both on
the same ``b1500-mcp`` entry point, ``run_confirmed_plan`` = ``prompt`` / ``ask``; WARN when none is generated yet);
the MCP server starts with exactly the ten tools within the token budget; the manual corpus (blueprint 5.2: PASS
when the committed corpus is current, WARN when stale or missing) and the manual PDFs (optional: PASS when all are
found, INFO when some or all are absent, WARN on an edition mismatch); ``PYTHONUTF8`` and ``LongPathsEnabled``
(Windows).

The read-only instrument probe (``b1500 doctor --probe``: VISA library and resources, identity, inventory, error
queue, status byte, outputs, selectors, SPGU, MFCMU corrections; never ``CN`` or a setting command) is a service
operation (``service/probe.py``, ``B1500Admin.probe``), not one of these installation checks.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import shutil
import struct
import subprocess
import sys
import uuid
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from b1500_test_agent.config import ConfigBundle, ConfigLoader
from b1500_test_agent.devtools import budget, harness, sync_harness
from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.manuals import search as manual_search
from b1500_test_agent.manuals.catalog import ManualError, ManualPaths
from b1500_test_agent.models.station import Settings
from b1500_test_agent.paths import Paths
from b1500_test_agent.service import TOOL_NAMES
from b1500_test_agent.session import read_inflight
from b1500_test_agent.session.fault import FaultLatch
from b1500_test_agent.session.lock import InstrumentLock
from b1500_test_agent.transport.audit import NullAuditSink

CheckStatus = Literal["PASS", "INFO", "WARN", "FAIL"]
MCP_SERVER_SPEC = "b1500_test_agent.adapters.mcp_server:create_server"
RUNTIME_MODULES = ("pydantic", "yaml", "numpy", "pandas", "matplotlib", "typer", "filelock", "fastmcp")
BUDGET_TOTAL = 4500
BUDGET_PER_TOOL = 700
WINDOWS_PATH_WARN = 80
MIN_FREE_BYTES = 1 << 30


class DoctorCheck(BaseModel):
    """One check: name, PASS/INFO/WARN/FAIL and what was found (INFO: optional item absent, nothing to fix)."""

    name: str
    status: CheckStatus
    detail: str


class DoctorReport(BaseModel):
    """All checks; ``ok`` is false when any check FAILed."""

    ok: bool
    checks: list[DoctorCheck]


def _check(name: str, status: CheckStatus, detail: str) -> DoctorCheck:
    return DoctorCheck(name=name, status=status, detail=detail)


def check_python() -> DoctorCheck:
    version = sys.version_info
    bits = struct.calcsize("P") * 8
    detail = f"{platform.python_implementation()} {platform.python_version()} {platform.machine()} ({bits}-bit)"
    if not (3, 11) <= version[:2] < (3, 14):
        return _check("python", "FAIL", detail + "; requires >=3.11,<3.14")
    if bits != 64:
        return _check("python", "FAIL", detail + "; a 64-bit interpreter is required")
    return _check("python", "PASS", detail)


def check_uv_lock(repo_root: Path) -> DoctorCheck:
    lock = repo_root / "uv.lock"
    if not lock.is_file():
        return _check("uv.lock", "FAIL", f"{lock.as_posix()} is missing (git pull, then uv sync --frozen)")
    uv = shutil.which("uv")
    if uv is None:
        return _check("uv.lock", "WARN", "uv not found on PATH; cannot check that uv.lock matches pyproject.toml")
    try:
        result = subprocess.run([uv, "lock", "--check", "--offline", "--project", str(repo_root)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return _check("uv.lock", "WARN", f"uv lock --check could not run: {exc}")
    lines = [line.strip() for line in f"{result.stderr}\n{result.stdout}".splitlines() if line.strip()]
    if result.returncode == 0:
        return _check("uv.lock", "PASS", "in sync with pyproject.toml")
    if any("needs to be updated" in line for line in lines):
        return _check("uv.lock", "FAIL", "uv.lock does not match pyproject.toml (git pull, then uv sync --frozen)")
    errors = [line for line in lines if line.lower().startswith("error")] or lines
    return _check("uv.lock", "WARN", f"could not check offline: {errors[0] if errors else result.returncode}")


def check_imports(backend: str | None) -> DoctorCheck:
    missing = []
    for name in RUNTIME_MODULES:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            missing.append(f"{name} ({exc})")
    visa_found = importlib.util.find_spec("pyvisa") is not None  # located only, never imported here
    if missing:
        return _check("imports", "FAIL", "missing: " + ", ".join(missing) + " (uv sync --frozen)")
    if not visa_found:
        status: CheckStatus = "FAIL" if backend == "visa" else "WARN"
        return _check("imports", status, "runtime packages import; pyvisa is not installed (needed for visa)")
    return _check("imports", "PASS", f"{', '.join(RUNTIME_MODULES)} import; pyvisa installed")


def check_config(loader: ConfigLoader) -> tuple[DoctorCheck, ConfigBundle | None]:
    report = loader.check()
    if not report.ok:
        problems = "; ".join(f"{p.file or 'config'}: {p.message}" for p in report.problems[:5])
        return _check("config", "FAIL", f"invalid_config: {problems} (b1500 config check)"), None
    sources: dict[str, list[str]] = {}
    for item in report.files:
        sources.setdefault(item.source, []).append(item.key)
    used = "; ".join(f"{source}: {', '.join(keys)}" for source, keys in sorted(sources.items()))
    detail = f"backend {report.backend_reason}; files {used}"
    status: CheckStatus = "WARN" if report.warnings else "PASS"
    if report.warnings:
        detail += "; warnings: " + "; ".join(report.warnings[:3])
    return _check("config", status, detail), loader.get()


def check_data_dir(paths: Paths) -> DoctorCheck:
    root = paths.data_root
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".doctor-{uuid.uuid4().hex[:8]}.tmp"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return _check("data dir", "FAIL", f"{root.as_posix()} is not writable: {exc}")
    free = shutil.disk_usage(root).free
    detail = f"{paths.display(root)} writable, {free / 1e9:.1f} GB free"
    return _check("data dir", "WARN" if free < MIN_FREE_BYTES else "PASS", detail)


def check_path_length(paths: Paths, *, windows: bool) -> DoctorCheck:
    length = len(str(paths.repo_root))
    detail = f"clone path has {length} characters"
    if windows and length > WINDOWS_PATH_WARN:
        return _check("path length", "WARN", detail + f" (> {WINDOWS_PATH_WARN}); prefer a short ASCII path")
    return _check("path length", "PASS", detail + ("" if windows else " (the 80-character limit applies on Windows)"))


def check_state(bundle: ConfigBundle | None, paths: Paths) -> DoctorCheck:
    state_dir = bundle.paths.state_dir if bundle is not None else paths.state_dir
    fault = FaultLatch(state_dir, audit=NullAuditSink(), backend=bundle.backend if bundle else "sim").get()
    if fault is not None:
        return _check("state", "FAIL", f"fault latched since {fault.set_at.isoformat()}: {fault.reason} (a human "
                                       "reviews it, then b1500 fault clear)")
    marker = read_inflight(state_dir / "inflight.json")
    if marker is not None:
        held = False
        if bundle is not None:
            resource = (f"SIM::{bundle.settings.sim.scenario}" if bundle.backend == "sim"
                        else bundle.settings.visa.resource)
            try:
                held = InstrumentLock(state_dir, resource).is_held()
            except ValueError:
                held = False
        if not held:
            return _check("state", "WARN", f"stale inflight marker of {marker.intent!r}: the next transaction "
                                           "recovers it (or run b1500 shutdown)")
        return _check("state", "PASS", f"a transaction is running ({marker.intent})")
    return _check("state", "PASS", "no fault latched, no inflight marker")


def check_skills_mirror(repo_root: Path) -> DoctorCheck:
    """``.claude/skills/`` (Claude Code) is the up-to-date generated copy of ``.agents/skills/`` (blueprint 6.6)."""
    report = sync_harness.check(repo_root)
    fix = "run uv run b1500 dev sync-harness"
    if report.problems:
        return _check("skills mirror", "FAIL", "; ".join(report.problems[:3]))
    if report.drift:
        listed = ", ".join(f"{item.kind} {item.path}" for item in report.drift[:3])
        more = f" (+{len(report.drift) - 3} more)" if len(report.drift) > 3 else ""
        return _check("skills mirror", "FAIL", f"{sync_harness.MIRROR_DIR} drifted from {sync_harness.SOURCE_DIR}: "
                                               f"{listed}{more}; {fix}")
    if not report.skills:
        return _check("skills mirror", "WARN", f"no skill under {sync_harness.SOURCE_DIR} (git pull)")
    return _check("skills mirror", "PASS", f"{sync_harness.MIRROR_DIR} in sync ({report.files} files; "
                                           f"{', '.join(report.skills)})")


def check_harness_files(repo_root: Path) -> DoctorCheck:
    """Committed harness files wired per blueprint 5.4; generated configs free of drift on one entry point."""
    _, problems = harness.committed_problems(repo_root, harness.TARGETS)
    generated = [t for t in harness.TARGETS.values() if (repo_root / t.output).is_file()]
    for target in generated:
        problems += harness.rendered_problems(repo_root, target)
    if problems:
        more = f" (+{len(problems) - 3} more; b1500 harness init --codex --claude --check)" if len(problems) > 3 else ""
        return _check("harness files", "FAIL", "; ".join(problems[:3]) + more)
    modes = {"codex": f"{harness.CONFIRM_TOOL} prompt", "claude": f"{harness.CONFIRM_TOOL} ask"}
    parts = [f"{t.name}: {t.output} ({modes[t.name]})" if t in generated else f"{t.name}: not generated"
             for t in harness.TARGETS.values()]
    launch = harness.expected_launch("<clone>")
    entry = f"{launch.command} {' '.join(launch.args)} -> {harness.ENTRY_POINT_TARGET}"
    detail = "; ".join(parts) + f"; entry point {entry}"
    if not generated:
        return _check("harness files", "WARN", detail + " (run b1500 harness init --codex and/or --claude)")
    return _check("harness files", "PASS", detail)


def check_mcp_server(spec: str = MCP_SERVER_SPEC) -> DoctorCheck:
    try:
        app = budget.load_app(spec)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            report = budget.measure_app(app, label=spec)
    except Exception as exc:  # noqa: BLE001 - any failure to start the server is the finding
        return _check("mcp server", "FAIL", f"server does not start: {type(exc).__name__}: {exc}")
    names = tuple(row.name for row in report.tools)
    largest = max((row.tokens for row in report.tools), default=0)
    detail = f"{len(names)} tools, {report.total_tokens} tokens (largest {largest}; {report.method})"
    if sorted(names) != sorted(TOOL_NAMES):
        return _check("mcp server", "FAIL", detail + f"; expected exactly {list(TOOL_NAMES)}")
    if report.total_tokens > BUDGET_TOTAL or largest > BUDGET_PER_TOOL:
        return _check("mcp server", "FAIL", detail + f"; budget {BUDGET_TOTAL} total, {BUDGET_PER_TOOL} per tool")
    return _check("mcp server", "PASS", detail)


def check_manuals(repo_root: Path, setting: str, environ: Mapping[str, str]) -> list[DoctorCheck]:
    """``manual corpus`` (committed page corpus current?) and ``manual PDFs`` (optional source PDFs present?)."""
    paths = ManualPaths.for_repo(repo_root, setting, environ)
    fix = "uv run b1500 manual build (needs the PDFs)"
    if not paths.catalog.is_file():
        return [_check("manual corpus", "WARN", f"no manual catalog at {paths.display(paths.catalog)} (git pull)"),
                _check("manual PDFs", "INFO", "not checked without a catalog")]
    try:
        status = manual_search.status(paths)
    except ManualError as exc:
        return [_check("manual corpus", "FAIL", str(exc)), _check("manual PDFs", "INFO", "not checked")]
    size = f"{status.corpus_bytes / 1000:.0f} kB"
    corpus = {
        "current": _check("manual corpus", "PASS", f"{status.docs_in_corpus} docs, {status.pages_in_corpus} pages "
                                                   f"({size}) in {status.corpus_dir}; b1500 manual search|page|toc"),
        "stale": _check("manual corpus", "WARN", f"stale: built from another catalog; {fix}"),
        "missing": _check("manual corpus", "WARN", f"missing in {status.corpus_dir}: manual queries answer from the "
                                                   f"structured extracts only (git pull, or {fix})"),
        "invalid": _check("manual corpus", "FAIL", status.message),
    }[status.corpus]
    where = f"{status.manuals_dir} ({status.manuals_dir_source})"
    missing = [d.id for d in status.docs if d.pdf == "missing"]
    mismatch = [d.id for d in status.docs if d.pdf == "mismatch"]
    total = len(status.docs)
    if mismatch:
        pdfs = _check("manual PDFs", "WARN", f"edition mismatch (sha256 differs from the catalog): "
                                             f"{', '.join(mismatch)} in {where}; see b1500 manual status")
    elif not missing:
        pdfs = _check("manual PDFs", "PASS", f"{total}/{total} PDFs in {where}")
    else:
        found = f"{total - len(missing)}/{total} PDFs in {where}" + (
            f" (missing {', '.join(missing)})" if len(missing) < total else "")
        pdfs = _check("manual PDFs", "INFO", f"{found}; optional - the committed corpus answers manual queries, "
                                             "PDFs are needed only for figures and manual build (B1500_MANUALS_DIR)")
    return [corpus, pdfs]


def check_pythonutf8(environ: Mapping[str, str], *, windows: bool) -> DoctorCheck:
    value = environ.get("PYTHONUTF8")
    if value == "1" or sys.flags.utf8_mode:
        return _check("PYTHONUTF8", "PASS", "UTF-8 mode on")
    if windows:
        return _check("PYTHONUTF8", "WARN", "PYTHONUTF8 is not 1 here; the generated harness MCP configs set it")
    return _check("PYTHONUTF8", "PASS", "not set (needed on Windows only; harness MCP configs set it)")


def check_long_paths(*, windows: bool) -> DoctorCheck:
    if not windows:
        return _check("LongPathsEnabled", "PASS", "not applicable on this OS")
    try:
        import winreg  # Windows-only standard library module (absent elsewhere: platform-injected tests)

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem")
        value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
    except ImportError:
        return _check("LongPathsEnabled", "WARN", "cannot read the registry value: winreg is not available here")
    except OSError as exc:
        return _check("LongPathsEnabled", "WARN", f"cannot read the registry value: {exc}")
    if value == 1:
        return _check("LongPathsEnabled", "PASS", "enabled")
    return _check("LongPathsEnabled", "WARN", "disabled; keep the clone path short (run paths must stay < 200 chars)")


def run_doctor(*, environ: Mapping[str, str] | None = None, windows: bool | None = None,
               mcp_check: Callable[[], DoctorCheck] | None = None) -> DoctorReport:
    """Run every non-probe check (see the module docstring); never raises for a failing check."""
    env = os.environ if environ is None else environ
    on_windows = sys.platform == "win32" if windows is None else windows
    loader = ConfigLoader(environ=env)
    checks = [check_python()]
    try:
        paths = Paths.from_env(env)
    except InvalidConfigError as exc:
        checks.append(_check("repository", "FAIL", str(exc)))
        return DoctorReport(ok=False, checks=checks)
    config_check, bundle = check_config(loader)
    if bundle is not None:
        paths = bundle.paths
    checks += [
        check_uv_lock(paths.repo_root),
        check_imports(bundle.backend if bundle is not None else None),
        config_check,
        check_data_dir(paths),
        check_path_length(paths, windows=on_windows),
        check_state(bundle, paths),
        check_skills_mirror(paths.repo_root),
        check_harness_files(paths.repo_root),
        (mcp_check or check_mcp_server)(),
        *check_manuals(paths.repo_root, (bundle.settings if bundle is not None else Settings()).manuals_dir, env),
        check_pythonutf8(env, windows=on_windows),
        check_long_paths(windows=on_windows),
    ]
    return DoctorReport(ok=all(c.status != "FAIL" for c in checks), checks=checks)


def format_report(report: DoctorReport) -> str:
    width = max(len(c.name) for c in report.checks)
    lines = [f"{c.status:<4}  {c.name:<{width}}  {c.detail}" for c in report.checks]
    fails = sum(c.status == "FAIL" for c in report.checks)
    warns = sum(c.status == "WARN" for c in report.checks)
    infos = sum(c.status == "INFO" for c in report.checks)
    lines.append(f"doctor: {'ok' if report.ok else 'FAIL'} ({fails} fail, {warns} warn, {infos} info, "
                 f"{len(report.checks)} checks)")
    return "\n".join(lines)
