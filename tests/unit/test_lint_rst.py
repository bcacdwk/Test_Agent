"""``*RST`` lint (blueprint 2.1 lint ownership): the ``*RST`` builder is called only by kind ``system``.

``*RST`` resets the whole instrument (PG PDF 179-180, Tables 2-12 and 2-13: CMU corrections off, SPGU back to
free-run, ``SER`` 50 Ohm, switch paths reset), so it may reach the instrument only through one guarded path:

- the builder constant ``flex.RST`` (defined in ``driver/flex/core.py``, re-exported by ``driver/flex/__init__.py``)
  is referenced only by ``B1500Driver.reset`` in ``driver/ops/core.py``;
- ``.reset(...)`` is called only in ``catalog/kinds/system.py`` (the ``system`` kind; ``*RST`` stays inside
  ``system.*`` recipes, blueprint 1.2).

Detector: the AST of every ``*.py`` under ``src/b1500_test_agent`` (``driver/flex/`` itself and the simulator, which
implements the instrument side, are exempt): attribute access ``<x>.RST``, ``from ... import RST``, a bare name
``RST`` and any call of an attribute named ``reset``. Function-level and ``TYPE_CHECKING`` code counts too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "src" / "b1500_test_agent"

EXEMPT_PREFIXES = {
    "driver/flex/": "the builder package defines and re-exports RST",
    "transport/sim/": "simulator: the instrument side of *RST (blueprint 4)",
}
RST_REFERENCE_ALLOWED = {"driver/ops/core.py": "reset"}
"""File -> the one function in it that may reference ``RST``."""
RESET_CALL_ALLOWED = frozenset({"catalog/kinds/system.py"})
FLEX_PACKAGE = "b1500_test_agent.driver.flex"


def _functions_by_node(tree: ast.AST) -> dict[int, str]:
    """``id(node)`` -> name of the innermost enclosing function, for every node inside a function."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, function: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function
            if name is not None:
                owner[id(child)] = name
            visit(child, name)

    visit(tree, None)
    return owner


def rst_findings(source: str) -> list[tuple[int, str, str | None]]:
    """``(line, what, enclosing function)`` of every ``RST`` reference and every ``.reset(...)`` call."""
    tree = ast.parse(source)
    owner = _functions_by_node(tree)
    found: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
        if name == "RST":
            found.append((node.lineno, "RST reference", owner.get(id(node))))
        elif isinstance(node, ast.ImportFrom) and any(
                alias.name == "RST" or (alias.name == "*" and (node.module or "").startswith(FLEX_PACKAGE))
                for alias in node.names):
            found.append((node.lineno, "RST import", owner.get(id(node))))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "reset":
            found.append((node.lineno, "reset() call", owner.get(id(node))))
    return found


def problems_of(source: str, rel: str) -> list[str]:
    """Lint problems of one package file at ``rel`` (POSIX, relative to the package directory)."""
    problems = []
    for line, what, function in rst_findings(source):
        if what == "reset() call":
            if rel not in RESET_CALL_ALLOWED:
                problems.append(f"{rel}:{line}: reset() (*RST) is called only by kind system "
                                f"({', '.join(sorted(RESET_CALL_ALLOWED))})")
        elif function is None or RST_REFERENCE_ALLOWED.get(rel) != function:
            problems.append(f"{rel}:{line}: {what} outside B1500Driver.reset (driver/ops/core.py)")
    return problems


def _scanned_files() -> list[Path]:
    return [p for p in sorted(PACKAGE_DIR.rglob("*.py"))
            if not p.relative_to(PACKAGE_DIR).as_posix().startswith(tuple(EXEMPT_PREFIXES))]


def test_rst_reaches_the_instrument_only_through_kind_system() -> None:
    files = _scanned_files()
    assert len(files) > 50
    problems = [p for path in files
                for p in problems_of(path.read_text(encoding="utf-8"), path.relative_to(PACKAGE_DIR).as_posix())]
    assert problems == []


def test_the_reset_method_is_the_one_rst_reference_so_the_lint_is_not_vacuous() -> None:
    source = (PACKAGE_DIR / "driver" / "ops" / "core.py").read_text(encoding="utf-8")
    assert [(what, function) for _, what, function in rst_findings(source)] == [("RST reference", "reset")]
    flex_core = (PACKAGE_DIR / "driver" / "flex" / "core.py").read_text(encoding="utf-8")
    assert any(what == "RST reference" for _, what, _ in rst_findings(flex_core))  # the definition


@pytest.mark.parametrize(
    ("rel", "source"),
    [
        ("session/transaction.py", "def cleanup(tx):\n    tx.driver.reset()\n"),
        ("service.py", "def f(d):\n    d.reset()\n"),
        ("catalog/kinds/smu_staircase.py", "from b1500_test_agent.driver import flex\nX = [flex.RST]\n"),
        ("catalog/kinds/system.py", "from b1500_test_agent.driver import flex\nQ = flex.RST\n"),
        ("driver/ops/core.py", "def zero(self):\n    self._write(flex.RST)\n"),
        ("driver/ops/smu.py", "from b1500_test_agent.driver.flex import RST\n"),
        ("driver/ops/smu.py", "from b1500_test_agent.driver.flex.core import *\n"),
        ("session/session.py", "def f():\n    from b1500_test_agent.driver.flex import RST\n    return RST\n"),
    ],
)
def test_detector_flags_rst_outside_the_system_path(rel: str, source: str) -> None:
    assert problems_of(source, rel)


@pytest.mark.parametrize(
    ("rel", "source"),
    [
        ("catalog/kinds/system.py", "def acquire(tx):\n    tx.driver.reset()\n"),
        ("driver/ops/core.py", "def reset(self):\n    self._write(flex.RST)\n"),
        ("session/transaction.py", "def cleanup(tx):\n    tx.driver.zero()\n    tx.driver.disconnect()\n"),
        ("service.py", "text = 'reset the plan'\nRESET = 1\n"),
        ("transport/factory.py", "def f(state):\n    state.reset_settings()\n"),
    ],
)
def test_detector_accepts_everything_else(rel: str, source: str) -> None:
    assert problems_of(source, rel) == []
