"""Import layering of ``src/b1500_test_agent`` (blueprint 2):

    adapters -> service -> {catalog, rules, archive, analysis} -> session -> driver -> transport;  models is a leaf.

Ranks (a module may import its own component, the package root and components of lower or equal rank):

==== ==========================================================================================================
rank components
==== ==========================================================================================================
0    ``models`` (leaf: imports only ``models``)
1    ``errors``, ``paths``, ``config`` (shared foundations: import only ``models`` and each other)
2    ``transport``
3    ``driver``
4    ``session``
5    ``catalog``, ``rules``, ``archive``, ``analysis`` (peers)
6    ``service``
7    ``adapters``, ``devtools`` (peers; ``adapters/cli.py`` runs the dev tools)
==== ==========================================================================================================

Extra rules: ``analysis`` never imports ``session``, ``driver``, ``transport`` or ``catalog`` (blueprint 2 and
``analysis/AGENTS.md``); only ``adapters/mcp_server.py`` imports ``fastmcp`` (``devtools/`` is exempt: its token
counter loads FastMCP apps, WP0.3). Every import statement counts, including function-level and ``TYPE_CHECKING``
imports. A new top-level module must be added to ``RANKS`` before it can be imported.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "b1500_test_agent"
PACKAGE_DIR = ROOT / "src" / PACKAGE

RANKS: dict[str, int] = {
    "models": 0,
    "errors": 1,
    "paths": 1,
    "config": 1,
    "transport": 2,
    "driver": 3,
    "session": 4,
    "catalog": 5,
    "rules": 5,
    "archive": 5,
    "analysis": 5,
    "service": 6,
    "adapters": 7,
    "devtools": 7,
}
FORBIDDEN: dict[str, frozenset[str]] = {"analysis": frozenset({"session", "driver", "transport", "catalog"})}
FASTMCP_ALLOWED_FILES = frozenset({"adapters/mcp_server.py"})
FASTMCP_ALLOWED_COMPONENTS = frozenset({"devtools"})
_FASTMCP = re.compile(r"^fastmcp(\.|$)")


def _module_parts(rel: str) -> list[str]:
    """``driver/b1500.py`` -> ``[PACKAGE, "driver", "b1500"]``; ``__init__.py`` names its package."""
    parts = [PACKAGE, *rel.removesuffix(".py").split("/")]
    return parts[:-1] if parts[-1] == "__init__" else parts


def imported_modules(source: str, rel: str) -> list[tuple[int, str]]:
    """``(line, absolute module name)`` of every import in a package file at ``rel`` (POSIX, package-relative).

    ``from X import name`` yields ``X.name`` so that ``from b1500_test_agent import config`` resolves to the
    ``config`` component; relative imports are resolved against the file's package.
    """
    is_package = rel.endswith("__init__.py")
    module_parts = _module_parts(rel)
    package_parts = module_parts if is_package else module_parts[:-1]
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.extend((node.lineno, f"{module}.{alias.name}" if module else alias.name) for alias in node.names)
    return found


def component_of(module: str) -> str | None:
    """Package component of an absolute module name: ``b1500_test_agent.driver.x`` -> ``driver``; ``""`` for the
    package root (or a root attribute such as ``__version__``); ``None`` outside the package."""
    parts = module.split(".")
    if parts[0] != PACKAGE:
        return None
    if len(parts) == 1 or (parts[1] not in RANKS and parts[1].startswith("__")):
        return ""
    return parts[1]


def layering_problems(source: str, rel: str) -> list[str]:
    """Problems of one package file (``rel`` relative to the package directory)."""
    parts = _module_parts(rel)
    own = parts[1] if len(parts) > 1 else ""
    problems: list[str] = []
    if own and own not in RANKS:
        return [f"{rel}: component {own!r} has no rank in RANKS"]
    for line, module in imported_modules(source, rel):
        where = f"{rel}:{line}"
        if _FASTMCP.match(module) and rel not in FASTMCP_ALLOWED_FILES and own not in FASTMCP_ALLOWED_COMPONENTS:
            problems.append(f"{where}: imports {module} (only adapters/mcp_server.py may import fastmcp)")
        target = component_of(module)
        if target is None or target == "" or target == own:
            continue
        if target not in RANKS:
            problems.append(f"{where}: imports unknown component {target!r}")
        elif own == "":
            problems.append(f"{where}: the package root must not import {target}")
        elif own == "models":
            problems.append(f"{where}: models is a leaf and must not import {target}")
        elif target in FORBIDDEN.get(own, frozenset()):
            problems.append(f"{where}: {own} must never import {target}")
        elif RANKS[target] > RANKS[own]:
            problems.append(f"{where}: {own} (rank {RANKS[own]}) must not import {target} (rank {RANKS[target]})")
    return problems


def test_package_follows_the_layering() -> None:
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert len(files) > 20
    problems = []
    for path in files:
        rel = path.relative_to(PACKAGE_DIR).as_posix()
        problems.extend(layering_problems(path.read_text(encoding="utf-8"), rel))
    assert problems == []


def test_every_top_level_component_has_a_rank() -> None:
    components = {p.stem if p.is_file() else p.name for p in PACKAGE_DIR.iterdir() if p.suffix == ".py" or p.is_dir()}
    components -= {"__init__", "__pycache__"}
    assert components <= set(RANKS), sorted(components - set(RANKS))


@pytest.mark.parametrize(
    ("rel", "source"),
    [
        ("driver/b1500.py", "from b1500_test_agent.session.session import Session"),
        ("driver/b1500.py", "from ..session import Session"),
        ("transport/base.py", "from b1500_test_agent.driver import commands"),
        ("analysis/mosfet.py", "from b1500_test_agent.driver.parser import parse_fmt1"),
        ("analysis/mosfet.py", "import b1500_test_agent.transport.base"),
        ("analysis/dataset.py", "from b1500_test_agent import catalog"),
        ("models/plan.py", "from b1500_test_agent.config import ConfigLoader"),
        ("config.py", "from b1500_test_agent.driver.modules import module_spec"),
        ("session/transaction.py", "from b1500_test_agent.catalog.executor import Executor"),
        ("rules/builtin.py", "from b1500_test_agent.service import B1500Service"),
        ("service.py", "from b1500_test_agent.adapters import cli"),
        ("service.py", "import fastmcp"),
        ("adapters/cli.py", "from fastmcp import FastMCP"),
        ("driver/b1500.py", "def f():\n    from b1500_test_agent.catalog import kinds\n"),
        ("newlayer/x.py", "import os"),
    ],
)
def test_checker_flags_violations(rel: str, source: str) -> None:
    assert layering_problems(source, rel)


TYPE_CHECKING_IMPORT = """
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from b1500_test_agent.transport.base import Transport
"""


@pytest.mark.parametrize(
    ("rel", "source"),
    [
        ("driver/b1500.py", TYPE_CHECKING_IMPORT),
        ("driver/b1500.py", "from . import commands\nfrom .guard import OutputGuard\nfrom ..models.plan import X"),
        ("driver/guard.py", "from b1500_test_agent.errors import B1500Error"),
        ("session/transaction.py", "from b1500_test_agent.driver.b1500 import B1500Driver"),
        ("catalog/executor.py", "from b1500_test_agent.rules import engine\nfrom b1500_test_agent import archive"),
        ("analysis/dataset.py", "from b1500_test_agent.archive.store import RunStore\nimport pandas"),
        ("analysis/dataset.py", "from b1500_test_agent.config import ConfigLoader"),
        ("service.py", "from b1500_test_agent.session.session import Session"),
        ("adapters/mcp_server.py", "from fastmcp import FastMCP\nfrom b1500_test_agent.service import B1500Service"),
        ("adapters/cli.py", "from b1500_test_agent.devtools import budget"),
        ("devtools/budget.py", "def f():\n    from fastmcp import Client\n"),
        ("models/plan.py", "from b1500_test_agent.models.common import StrictModel"),
        ("models/plan.py", "from b1500_test_agent import __version__"),
        ("paths.py", "from b1500_test_agent.errors import InvalidConfigError"),
        ("__init__.py", "import os"),
    ],
)
def test_checker_accepts_allowed_imports(rel: str, source: str) -> None:
    assert layering_problems(source, rel) == []
