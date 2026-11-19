"""Child pytest runs of the hardware suite for the CI tests of this folder (``test_suite.py``, ``test_readonly.py``,
``test_record_checks.py``).

``run_suite`` starts ``python -m pytest tests/hardware ...`` from the repository root in a fresh process with a clean
environment (no ``B1500_*``/``PYTEST_*`` variables of this process) plus the variables given, writes a JUnit XML
report and returns every test's outcome. With a ``VisaWorld`` and its ``LoopBus`` it runs the suite as on the lab
PC (``B1500_HW=1``, backend visa from the world's ``config/local/``) over the visa-loop (``loop_plugin.py``).

``snapshot`` records the sha256 of every file under a folder, so a test can show which files a run created or
changed.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.hardware.support import ENV_HW
from tests.visa_loop.helpers import VisaWorld
from tests.visa_loop.loop import LoopBus

REPO_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT_S = 240.0
LOOP_PLUGIN = "tests.hardware.loop_plugin"


@dataclass(frozen=True)
class Outcome:
    """One test of a child run: ``passed``, ``failed``, ``error`` or ``skipped``, with the message of the latter."""

    status: str
    message: str = ""


@dataclass
class SuiteRun:
    returncode: int
    output: str
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    """Test id (``test_probe.py::test_x``, ``test_records.py::test_stage_records[L1]``) -> outcome."""

    def with_status(self, status: str) -> list[str]:
        return sorted(name for name, outcome in self.outcomes.items() if outcome.status == status)


def child_env(extra: Mapping[str, str]) -> dict[str, str]:
    """This environment without ``B1500_*``/``PYTEST_*`` variables and the active virtualenv marker, plus ``extra``."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("B1500_", "PYTEST_")) and k != "VIRTUAL_ENV"}
    return {**env, "PYTHONUTF8": "1", **extra}


def _outcomes(junit: Path) -> dict[str, Outcome]:
    found: dict[str, Outcome] = {}
    if not junit.is_file():
        return found
    for case in ET.parse(junit).getroot().iter("testcase"):
        module = case.get("classname", "").rsplit(".", 1)[-1]
        name = f"{module}.py::{case.get('name', '')}"
        status, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                status = "failed" if tag == "failure" else tag
                message = node.get("message", "") or (node.text or "")
                break
        found[name] = Outcome(status, message)
    return found


def run_suite(tmp_path: Path, args: Sequence[str], env: Mapping[str, str]) -> SuiteRun:
    """``python -m pytest <args>`` from the repository root with ``child_env(env)``; JUnit report under ``tmp_path``."""
    junit = tmp_path / f"junit-{len(list(tmp_path.glob('junit-*.xml')))}.xml"
    command = [sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider", "-rA", f"--junitxml={junit}"]
    done = subprocess.run(command, cwd=REPO_ROOT, env=child_env(env), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=TIMEOUT_S, check=False)
    return SuiteRun(done.returncode, done.stdout + done.stderr, _outcomes(junit))


def run_on_loop(world: VisaWorld, bus: LoopBus, tmp_path: Path, *selection: str,
                env: Mapping[str, str] | None = None) -> SuiteRun:
    """The hardware suite (or ``selection``: paths and ``-k`` options) as on the lab PC, over the visa-loop; ``env``
    adds environment variables."""
    args = list(selection) or ["tests/hardware"]
    child = {**world.env(bus), ENV_HW: "1", **(env or {})}
    return run_suite(tmp_path, [*args, "-m", "hardware", "-p", LOOP_PLUGIN], child)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    """Relative POSIX path -> sha256 of every file under ``root`` (empty when it does not exist)."""
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): _sha256(p) for p in sorted(root.rglob("*")) if p.is_file()}


def changes(before: Mapping[str, str], after: Mapping[str, str]) -> tuple[list[str], list[str], list[str]]:
    """(created, changed, removed) relative paths between two snapshots."""
    created = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    return created, changed, removed
