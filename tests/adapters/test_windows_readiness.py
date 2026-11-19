"""Windows readiness (blueprint v2 7.1 "Windows CI", 8.1, AGENTS.md "Windows-safe code"; WP6.5), tested on every OS by
platform injection: the Windows behaviour is exercised from macOS too, and the Windows CI job runs the same tests
natively.

- File names: everything a lab session writes (run archive, analysis, plots, notes, audit, simulator state, probe and
  station proposal under ``work/bringup/``) and every tracked file is a valid Windows name (no ``<>:"/\\|?*``, no
  reserved device name, no trailing dot or space) and short enough for ``MAX_PATH`` under a clone path of up to
  80 characters (the ``b1500 doctor`` WARN limit); no two tracked paths differ only in letter case.
- Line ends: ``.gitattributes`` checks text out with LF on every clone, so plan hashes of committed files match.
- Windows-only modules (``winreg``, ``msvcrt``, ``ctypes.WinDLL`` ...) are imported only inside functions with an
  ``ImportError`` fallback, ``ctypes`` only in ``transport/wgfmu/dll.py`` (WP10.2; absent until then), and every
  module of the package imports on this OS.
- ``b1500 doctor`` Windows checks with ``windows=True`` injected: path length, ``PYTHONUTF8``, ``LongPathsEnabled``
  without ``winreg``.
- Console encoding: the CLI on a cp1252 or cp936 stdout (Windows without ``PYTHONUTF8``) never fails on ``Ω``, ``µ``
  or CJK text; it writes ``\\uXXXX`` escapes instead (``adapters/streams.py``).
- ``file`` parameters spelled with backslashes are refused with a hint to use ``/``.
"""

from __future__ import annotations

import ast
import importlib
import io
import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner, Result

import b1500_test_agent
from b1500_test_agent.adapters import streams
from b1500_test_agent.adapters.cli import app, main
from b1500_test_agent.devtools import doctor
from b1500_test_agent.models.recipe import ParamSpec
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules.builtin.common import param_problem
from tests.integration.helpers import REPO_ROOT, World

runner = CliRunner()

WINDOWS_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])$", re.IGNORECASE)
MAX_PATH = 260
"""Classic Windows path limit including the terminating NUL (without ``LongPathsEnabled``)."""
CLONE_PATH_MAX = doctor.WINDOWS_PATH_WARN
REL_BUDGET = MAX_PATH - 1 - CLONE_PATH_MAX - 1
"""Longest repository-relative path that still fits ``MAX_PATH`` under an 80-character clone path (178)."""
WINDOWS_ONLY_MODULES = frozenset({"winreg", "_winreg", "msvcrt", "_winapi", "winsound", "_overlapped", "nt"})
WINDOWS_ONLY_CTYPES = frozenset({"WinDLL", "windll", "OleDLL", "oledll", "WinError", "wintypes", "HRESULT"})
CTYPES_ALLOWED = frozenset({"src/b1500_test_agent/transport/wgfmu/dll.py"})


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args))


def windows_name_problem(name: str) -> str | None:
    """Why ``name`` (one path component) is not a valid Windows file name, else ``None``."""
    if WINDOWS_INVALID.search(name):
        return "has a character Windows forbids"
    if name.endswith((" ", ".")) and name not in (".", ".."):
        return "ends with a dot or a space"
    if RESERVED.match(name.split(".", 1)[0]):
        return "is a reserved device name"
    if len(name) > 255:
        return "is longer than 255 characters"
    return None


def path_problems(rel: str) -> list[str]:
    problems = [f"{rel}: {part!r} {why}" for part in rel.split("/") if (why := windows_name_problem(part))]
    if len(rel) > REL_BUDGET:
        problems.append(f"{rel}: {len(rel)} characters > {REL_BUDGET} (MAX_PATH under an 80-character clone path)")
    return problems


def test_the_name_check_knows_the_windows_rules() -> None:
    assert windows_name_problem("probe-20261119T035020123Z.json") is None
    assert windows_name_problem("S20261119T03:50:20Z") == "has a character Windows forbids"
    for bad in ("CON", "nul.txt", "Com1.yaml", "LPT9", "a?b", "trail.", "trail "):
        assert windows_name_problem(bad) is not None, bad
    assert windows_name_problem("console.md") is None and windows_name_problem("com10") is None


# -- what a session writes ------------------------------------------------------------------------------------------


def test_every_file_a_session_writes_is_a_valid_windows_path(cli_world: World) -> None:
    """A measurement with analysis, plot, note, status, probe, station proposal and shutdown on the simulator: every
    file and folder it creates under the clone (``data/``, ``work/``) has a Windows-valid name, in particular no
    ``:`` from an ISO timestamp, and fits the path budget."""
    plan = json.loads(invoke("plan", "mosfet.idvg", "--pin-map", "mosfet-4t", "--dut", "nmos-generic",
                             "--json").stdout)
    ran = invoke("run", plan["plan_id"], "--json")
    assert ran.exit_code == 0, ran.output
    run_id = json.loads(ran.stdout)["run_id"]
    for args in (("analyze", run_id, "vth_linear_extrapolation"), ("analyze", run_id, "plot_iv"),
                 ("note", run_id, "Ω µ 状态: checked at 10:15"), ("status",), ("doctor", "--probe"),
                 ("bringup", "propose-station"), ("shutdown", "--reason", "end: 10:20")):
        result = invoke(*args)
        assert result.exit_code == 0, (args, result.output)
    # as the clone would hold them: <clone>/data/... (B1500_DATA_DIR here) and <clone>/work/...
    rels = sorted([f"data/{p.relative_to(cli_world.data).as_posix()}" for p in cli_world.data.rglob("*")]
                  + [f"work/{p.relative_to(cli_world.root / 'work').as_posix()}"
                     for p in (cli_world.root / "work").rglob("*")])
    assert any(r.startswith("data/runs/") and "/analysis/" in r for r in rels), rels
    assert any(r.startswith("data/runs/") and "/plots/" in r for r in rels), rels
    assert any(r.startswith("work/bringup/probe-") for r in rels) and "work/bringup/station.proposed.yaml" in rels
    assert any(r.startswith("data/state/audit/") for r in rels)
    problems = [problem for rel in rels for problem in path_problems(rel)]
    assert not problems, "\n".join(problems)


# -- what the repository holds --------------------------------------------------------------------------------------


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    return subprocess.run([git, "-C", str(REPO_ROOT), *args], capture_output=True, check=True, timeout=60)


def test_every_tracked_path_is_valid_on_windows() -> None:
    tracked = [p for p in _git("ls-files", "-z").stdout.decode("utf-8").split("\0") if p]
    assert len(tracked) > 500
    problems = [problem for rel in tracked for problem in path_problems(rel)]
    folded: dict[str, str] = {}
    for rel in tracked:
        other = folded.setdefault(rel.casefold(), rel)
        if other != rel:
            problems.append(f"{rel} and {other} differ only in letter case (one file on Windows)")
    assert not problems, "\n".join(problems)


def test_text_files_check_out_with_lf_on_every_clone() -> None:
    """Committed recipes, configuration, fixtures and waveform tables keep LF on a Windows clone (``.gitattributes``):
    the plan hash binds a ``file`` parameter's bytes and golden fixtures compare bytes. Binary formats are never
    converted."""
    files = ["recipes/basic/contact_resistor.yaml", "config/station.example.yaml", "tests/fixtures/lab/idvg_real.csv",
             ".agents/skills/b1500-test/SKILL.md", "src/b1500_test_agent/paths.py", "uv.lock"]
    out = _git("check-attr", "eol", "--", *files).stdout.decode("utf-8")
    assert out.count(": eol: lf") == len(files), out
    binary = _git("check-attr", "binary", "--", "x.png", "x.npz", "x.gz", "x.pdf", "x.whl").stdout.decode("utf-8")
    assert binary.count(": binary: set") == 5, binary


# -- Windows-only modules -------------------------------------------------------------------------------------------


def _guarded_by_import_error(handlers: list[ast.ExceptHandler]) -> bool:
    names: set[str] = set()
    for handler in handlers:
        if handler.type is None:
            return True
        for node in ast.walk(handler.type):
            if isinstance(node, ast.Name):
                names.add(node.id)
    return bool(names & {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})


def windows_only_imports(source: str) -> list[tuple[int, str, bool, bool]]:
    """``(line, module, inside a function, inside a try with an ImportError fallback)`` of every Windows-only
    import (module or ``ctypes`` name) and every ``ctypes`` import in ``source``."""
    found: list[tuple[int, str, bool, bool]] = []

    def visit(node: ast.AST, in_function: bool, guarded: bool) -> None:
        if isinstance(node, ast.Import | ast.ImportFrom):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                modules = [node.module or ""] if node.level == 0 else []
                if node.module == "ctypes" and any(a.name in WINDOWS_ONLY_CTYPES for a in node.names):
                    modules.append("ctypes.WinDLL")
            for module in modules:
                root = module.split(".", 1)[0]
                if root in WINDOWS_ONLY_MODULES or root == "ctypes" or module == "ctypes.WinDLL":
                    found.append((node.lineno, module, in_function, guarded))
        for child in ast.iter_child_nodes(node):
            if isinstance(node, ast.Try) and child in node.body:
                visit(child, in_function, guarded or _guarded_by_import_error(node.handlers))
            else:
                visit(child, in_function or isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef), guarded)

    visit(ast.parse(source), False, False)
    return found


def test_windows_only_modules_are_imported_lazily_with_a_fallback() -> None:
    """``winreg`` and friends exist only on Windows: a module-level import would make the package unimportable on
    the Mac and an unguarded one would crash ``doctor`` there. ``ctypes`` belongs to ``transport/wgfmu/dll.py``."""
    problems = []
    source_root = REPO_ROOT / "src"
    for path in sorted(source_root.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line, module, in_function, guarded in windows_only_imports(path.read_text(encoding="utf-8")):
            if module.startswith("ctypes") and rel not in CTYPES_ALLOWED:
                problems.append(f"{rel}:{line}: imports {module} (only {sorted(CTYPES_ALLOWED)} may)")
            elif not module.startswith("ctypes") and not (in_function and guarded):
                problems.append(f"{rel}:{line}: {module} must be imported inside a function with an ImportError "
                                "fallback")
    assert not problems, "\n".join(problems)
    found = windows_only_imports((REPO_ROOT / "src/b1500_test_agent/devtools/doctor.py").read_text(encoding="utf-8"))
    assert [(module, inside, guarded) for _, module, inside, guarded in found] == [("winreg", True, True)]


def test_the_import_check_sees_unguarded_and_module_level_imports() -> None:
    assert windows_only_imports("import winreg\n") == [(1, "winreg", False, False)]
    assert windows_only_imports("def f():\n    import msvcrt\n") == [(2, "msvcrt", True, False)]
    guarded = "def f():\n    try:\n        import winreg\n    except ImportError:\n        pass\n"
    assert windows_only_imports(guarded) == [(3, "winreg", True, True)]
    assert windows_only_imports("from ctypes import WinDLL\n")[-1][1] == "ctypes.WinDLL"


def test_every_module_of_the_package_imports_on_this_os() -> None:
    names = [m.name for m in pkgutil.walk_packages(b1500_test_agent.__path__, "b1500_test_agent.")]
    assert len(names) > 100
    failures = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - collected and reported together
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not failures, "\n".join(failures)


# -- b1500 doctor with the platform injected ------------------------------------------------------------------------


def test_doctor_long_paths_check_survives_a_missing_winreg() -> None:
    assert doctor.check_long_paths(windows=False).status == "PASS"
    check = doctor.check_long_paths(windows=True)
    if sys.platform == "win32":
        assert check.status in ("PASS", "WARN")  # the registry value of this machine
    else:
        assert check.status == "WARN" and "winreg is not available" in check.detail


def test_doctor_warns_about_a_long_clone_path_on_windows_only(tmp_path: Path) -> None:
    base = Paths.from_env({}, repo_root=REPO_ROOT)
    long_root = Path(tmp_path.anchor) / ("b1500-" + "x" * CLONE_PATH_MAX) / "test_agent"
    deep = base.model_copy(update={"repo_root": long_root})
    assert doctor.check_path_length(deep, windows=True).status == "WARN"
    assert doctor.check_path_length(deep, windows=False).status == "PASS"
    short = base.model_copy(update={"repo_root": Path(tmp_path.anchor) / "b1500" / "test_agent"})
    assert doctor.check_path_length(short, windows=True).status == "PASS"


def test_doctor_pythonutf8_check_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "sys", SimpleNamespace(flags=SimpleNamespace(utf8_mode=0)))
    assert doctor.check_pythonutf8({}, windows=True).status == "WARN"
    assert doctor.check_pythonutf8({"PYTHONUTF8": "1"}, windows=True).status == "PASS"
    assert doctor.check_pythonutf8({}, windows=False).status == "PASS"
    monkeypatch.setattr(doctor, "sys", SimpleNamespace(flags=SimpleNamespace(utf8_mode=1)))
    assert doctor.check_pythonutf8({}, windows=True).status == "PASS"


# -- console encoding -----------------------------------------------------------------------------------------------

LEGACY_CODE_PAGES = ("cp1252", "cp936")
"""ANSI code pages of a western and a Chinese Windows: what a redirected stdout uses without ``PYTHONUTF8``."""


def _console_run(monkeypatch: pytest.MonkeyPatch, encoding: str, *args: str) -> tuple[int, bytes, bytes]:
    """Run ``main()`` (the console script) with stdout/stderr on ``encoding`` as a pipe on Windows would be."""
    out, err = io.BytesIO(), io.BytesIO()
    stdout = io.TextIOWrapper(out, encoding=encoding, errors="strict", newline="\n", write_through=True)
    stderr = io.TextIOWrapper(err, encoding=encoding, errors="strict", newline="\n", write_through=True)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "argv", ["b1500", *args])
    with pytest.raises(SystemExit) as exit_info:
        main()
    stdout.flush()
    stderr.flush()
    code = exit_info.value.code
    return (code if isinstance(code, int) else 1), out.getvalue(), err.getvalue()


@pytest.mark.parametrize("encoding", LEGACY_CODE_PAGES)
@pytest.mark.parametrize(("args", "expect", "needs_world"), [
    (("manual", "search", "随机电报噪声", "--top", "3"), "AN-RTN", False),  # the committed corpus of this clone
    (("manual", "page", "PG", "--printed", "4-189"), "PG", False),
    (("config", "check"), "config: valid", True),
    (("--help",), "Usage", False),
], ids=["manual-search-cjk", "manual-page-ohm", "config-check", "help"])
def test_cli_output_survives_a_legacy_windows_code_page(request: pytest.FixtureRequest,
                                                         monkeypatch: pytest.MonkeyPatch, encoding: str,
                                                         args: tuple[str, ...], expect: str,
                                                         needs_world: bool) -> None:
    if needs_world:
        request.getfixturevalue("cli_world")
    code, out, err = _console_run(monkeypatch, encoding, *args)
    text = out.decode(encoding)  # valid bytes of the code page, nothing else
    assert code == 0, (text, err.decode(encoding))
    assert expect in text and "Traceback" not in err.decode(encoding)


def test_the_stream_fix_keeps_utf8_and_degrades_legacy_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", newline="\n")
    utf8 = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", legacy)
    monkeypatch.setattr(sys, "stderr", utf8)
    assert streams.safe_streams() == ["stdout"]
    assert legacy.errors == "backslashreplace" and utf8.errors == "strict"
    legacy.write("50 Ω, 状态\n")
    legacy.flush()
    assert legacy.buffer.getvalue() == b"50 \\u03a9, \\u72b6\\u6001\n"  # type: ignore[attr-defined]
    assert streams.safe_streams() == []  # idempotent
    assert streams.is_utf("UTF8") and streams.is_utf("utf_8_sig") and not streams.is_utf("cp936")
    assert not streams.is_utf("no-such-codec")


def test_a_cli_process_on_a_cp1252_pipe_prints_cjk_without_failing() -> None:
    """The real console script in a child process with ``PYTHONUTF8`` off and a cp1252 pipe (``PYTHONIOENCODING``
    stands for the code page of a redirected Windows stdout)."""
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"}
    for key in ("B1500_HOME", "B1500_CONFIG_DIR", "B1500_DATA_DIR"):
        env.pop(key, None)
    result = subprocess.run([sys.executable, "-c", "from b1500_test_agent.adapters.cli import main; main()",
                             "manual", "search", "随机电报噪声", "--top", "3"],
                            capture_output=True, timeout=120, env=env, cwd=REPO_ROOT, check=False)
    stderr = result.stderr.decode("cp1252", errors="replace")
    assert result.returncode == 0 and "UnicodeEncodeError" not in stderr, stderr
    text = result.stdout.decode("cp1252")
    assert "AN-RTN" in text and "'\\u968f\\u673a\\u7535\\u62a5\\u566a\\u58f0'" in text  # the query, escaped


# -- file parameters ------------------------------------------------------------------------------------------------


def test_backslash_file_parameters_are_refused_with_a_hint() -> None:
    spec = ParamSpec(type="file")
    assert param_problem(spec, "work/waveforms/pulse.csv") is None
    problem: Any = param_problem(spec, "work\\waveforms\\pulse.csv")
    assert problem is not None and "uses \\ separators" in problem[0] and "work/waveforms/<name>.csv" in problem[3]
    assert "is not a CSV path" in (param_problem(spec, "C:/b1500/pulse.csv") or ("",))[0]
