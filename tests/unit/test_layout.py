"""Source layout lints (blueprint 9 "Splits", WP5.2).

- File size: no Python source file under ``src/`` has more than 1,000 lines; a module that grows past it is split
  per family (one file per instrument family or concern), never exempted.
- Per-family packages: the v1 monoliths split by WP5.2 stay packages (``driver/flex/``, ``driver/ops/``,
  ``transport/sim/units/``, ``transport/sim/devices/``, ``rules/builtin/``, ``adapters/cli/``, ``devtools/skills/``)
  with one module per family or concern; no single-file module of the same name comes back next to them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PACKAGE_DIR = SRC / "b1500_test_agent"
MAX_LINES = 1_000

FAMILY_PACKAGES: dict[str, str] = {
    "driver/flex": "FLEX builders, the only home of FLEX literals",
    "driver/ops": "operations mixins behind the B1500Driver facade",
    "transport/sim/units": "simulator units behind the SimInstrument dispatcher",
    "transport/sim/devices": "simulator device models and the circuit",
    "rules/builtin": "built-in rules in table order",
    "adapters/cli": "the b1500 CLI",
    "devtools/skills": "the skill lint",
}
"""Package (relative to the package directory) -> what it holds."""


def line_count(path: Path) -> int:
    """Lines of a text file (a final line without a newline counts)."""
    return len(path.read_text(encoding="utf-8").splitlines())


def oversized(files: list[Path], base: Path, limit: int = MAX_LINES) -> list[str]:
    """``<path relative to base>: <n> lines`` for every file above ``limit``."""
    return [f"{p.relative_to(base).as_posix()}: {n} lines" for p in files if (n := line_count(p)) > limit]


def test_no_source_file_exceeds_1000_lines() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 100
    assert oversized(files, ROOT) == [], f"split these per family (limit {MAX_LINES} lines)"


def test_the_size_check_counts_lines(tmp_path: Path) -> None:
    small, large = tmp_path / "small.py", tmp_path / "large.py"
    small.write_text("x = 1\n" * MAX_LINES, encoding="utf-8")
    large.write_text("x = 1\n" * MAX_LINES + "y = 2", encoding="utf-8")
    assert line_count(small) == MAX_LINES and line_count(large) == MAX_LINES + 1
    assert oversized([small, large], tmp_path) == [f"large.py: {MAX_LINES + 1} lines"]


@pytest.mark.parametrize("package", sorted(FAMILY_PACKAGES))
def test_split_modules_stay_packages(package: str) -> None:
    folder = PACKAGE_DIR / package
    assert (folder / "__init__.py").is_file(), f"{package}/ must be a package: {FAMILY_PACKAGES[package]}"
    assert len(list(folder.glob("*.py"))) >= 3, f"{package}/ holds one module per family or concern"
    assert not (PACKAGE_DIR / f"{package}.py").exists(), f"{package}.py came back next to the {package}/ package"
