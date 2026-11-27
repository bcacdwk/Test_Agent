"""The design register ``docs/design/register.md``: every plan id the repository cites resolves to a row there, and no
file outside ``docs/design/`` points into the gitignored maintainer scratch (``tmp/``).

Plans, decisions and ids live in ``docs/design/`` (the committed plans, the progress logs, the register); code, tests,
skills and docs cite ids such as ``OD21-10`` or ``ATV-14``. These checks keep every citation resolvable in a fresh
clone: an id cited outside ``docs/design/`` needs a register row; every id a committed plan defines has one; each row
is well formed (status vocabulary, the defining file names the id, ``settled at`` names real bring-up steps); the
living design files link only to files that exist; and a path into the orchestration scratch outside ``docs/design/``
fails. The scanned files are the tracked and new, not ignored, ones (``git ls-files``); binary files are skipped.
The v1 owner decisions ``D1``-``D3`` are registered but not scanned for: the deployment steps share that spelling.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DESIGN_REL = "docs/design/"
DESIGN = ROOT / DESIGN_REL
REGISTER = DESIGN / "register.md"
STEPS = ROOT / ".agents" / "skills" / "b1500-bringup" / "steps.yaml"

NAMESPACES = ("OD", "OD21", "OD30", "KD", "D", "D30", "ATV")
CITED = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(NAMESPACES) + r")-\d+(?!\d)")
"""A plan id as other files cite it; the look-behind keeps ``OD-5`` from also counting as ``D-5``."""
ROW_ID = re.compile(r"(?:D[1-3]|(?:" + "|".join(NAMESPACES) + r")-\d+)")
SCRATCH = re.compile(r"tmp/v\d+_orch")
"""A path into the maintainer's orchestration scratch (plans, briefs, repros before they were committed)."""
STATUS = re.compile(r"(open|resolved|dropped|settled at)\b")
DEFINED = re.compile(r"^\| (?P<table>" + ROW_ID.pattern + r") \||\*\*(?P<bold>" + ROW_ID.pattern + r")(?![\d-])")
"""How a plan defines an id: the first cell of a table row (assumptions, v2 owner decisions) or a bold lead-in."""
PLANS = ("blueprint.md", "plan-v2.1.md", "plan-v3.md")
LIVING = ("README.md", "register.md", "progress-v3.md")
"""The design files kept current; the frozen ones are checked only for their header lines."""
HEADER_LINES = 10
"""A frozen file's header: the blockquote lines among its first lines (its own links are history)."""
FROZEN_SIZES = {"D": 11, "OD": 7, "OD21": 11, "KD": 8}
"""Namespaces of closed plans (v2, v2.1): their size never changes. v1's D1-D3 and ATV-1..40 are checked below."""
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _repository_files() -> list[str]:
    """Repository-relative paths of the tracked and new (not ignored) files."""
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, check=True).stdout.decode("utf-8")
    return sorted(name for name in listed.split("\0") if name and (ROOT / name).is_file())


def _text(path: Path) -> str | None:
    """The file's UTF-8 text, or ``None`` for a binary file."""
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan(root: Path, rels: Iterable[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Cited ids (id -> ``file:line`` places) and scratch paths (``file:line``) of the files outside
    ``docs/design/``."""
    cited: dict[str, list[str]] = {}
    scratch: list[str] = []
    for rel in rels:
        if rel.startswith(DESIGN_REL):
            continue
        text = _text(root / rel)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for found in CITED.findall(line):
                cited.setdefault(found, []).append(f"{rel}:{number}")
            if SCRATCH.search(line):
                scratch.append(f"{rel}:{number}")
    return cited, scratch


def unresolved(cited: dict[str, list[str]], registered: Iterable[str]) -> dict[str, list[str]]:
    """The cited ids without a register row, with their places."""
    known = set(registered)
    return {ident: places for ident, places in sorted(cited.items()) if ident not in known}


def register_rows(text: str) -> list[tuple[str, str, str, str]]:
    """(id, statement, status, defined in) of every register table row whose first cell is an id."""
    rows = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]] if line.startswith("| ") else []
        if cells and ROW_ID.fullmatch(cells[0]):
            assert len(cells) == 4, line
            rows.append((cells[0], cells[1], cells[2], cells[3]))
    return rows


@pytest.fixture(scope="module")
def rows() -> dict[str, tuple[str, str, str]]:
    found = register_rows(REGISTER.read_text(encoding="utf-8"))
    ids = [ident for ident, *_ in found]
    duplicates = sorted({ident for ident in ids if ids.count(ident) > 1})
    assert not duplicates, f"register rows twice: {duplicates}"
    return {ident: (statement, status, defined) for ident, statement, status, defined in found}


def _number(ident: str) -> tuple[str, int]:
    prefix, _, number = ident.rpartition("-")
    return (prefix, int(number)) if prefix else ("v1 D", int(ident[1:]))


def _bringup_ids() -> set[str]:
    steps = yaml.safe_load(STEPS.read_text(encoding="utf-8"))
    ids = {step["id"] for step in steps["deployment"]}
    for stage, entries in steps["stages"].items():
        ids |= {stage} | {step["id"] for step in entries}
    return ids


def test_every_cited_id_outside_design_has_a_register_row(rows: dict[str, tuple[str, str, str]]) -> None:
    cited, _ = scan(ROOT, _repository_files())
    assert len(cited) > 30, sorted(cited)  # the scan sees the repository (ATV ids alone are cited in dozens of files)
    missing = unresolved(cited, rows)
    assert not missing, "ids without a row in docs/design/register.md: " + "; ".join(
        f"{ident} ({', '.join(places[:3])})" for ident, places in missing.items())


def test_no_file_outside_design_points_into_the_maintainer_scratch() -> None:
    _, scratch = scan(ROOT, _repository_files())
    assert not scratch, f"paths into the gitignored orchestration scratch (cite docs/design/ instead): {scratch}"


def test_an_unknown_id_or_a_scratch_path_fails(tmp_path: Path, rows: dict[str, tuple[str, str, str]]) -> None:
    unknown = "OD30-" + "999"  # built here, so this file cites no unknown id itself
    scratch = "tmp/" + "v9_orch/notes.md"
    files = {
        "docs/guide.md": f"Owner decision {unknown} applies.\nSee {scratch} and OD21-10.\n",
        "src/pkg/mod.py": f'"""Rule from ATV-14 and {unknown}."""\n',
        "docs/design/plan.md": f"{unknown} defined here; notes in {scratch}.\n",  # history: not scanned
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    (tmp_path / "data.bin").write_bytes(b"\0" + unknown.encode("ascii"))  # binary: skipped
    cited, found_scratch = scan(tmp_path, [*files, "data.bin"])
    assert unresolved(cited, rows) == {unknown: ["docs/guide.md:1", "src/pkg/mod.py:1"]}
    assert found_scratch == ["docs/guide.md:2"]
    assert set(cited) == {unknown, "OD21-10", "ATV-14"}


def test_the_id_pattern_tells_the_namespaces_apart() -> None:
    line = "OD-5, KD-2, OD21-4, D30-7, ATV-3 and D-9; not ATV-x, WP30.1, D1-D12, R-LIM-02, PUND-1 or 3D-4"
    assert CITED.findall(line) == ["OD-5", "KD-2", "OD21-4", "D30-7", "ATV-3", "D-9"]


def test_register_rows_are_well_formed(rows: dict[str, tuple[str, str, str]]) -> None:
    problems = []
    for ident, (statement, status, defined) in rows.items():
        source = defined.split()[0]
        if not statement:
            problems.append(f"{ident}: empty statement")
        if not STATUS.match(status):
            problems.append(f"{ident}: status {status!r} is not open, resolved, dropped or settled at <steps>")
        if source == "plan-v1":
            continue  # the v1 plan is the tag plan-v1 (not fetched by every clone)
        path = DESIGN / source
        if not path.is_file():
            problems.append(f"{ident}: defined in {source!r}, which is not a file in docs/design/")
        elif not re.search(rf"(?<![A-Za-z0-9_]){re.escape(ident)}(?!\d)", path.read_text(encoding="utf-8")):
            problems.append(f"{ident}: {source} does not name it")
    assert not problems, problems


def test_settled_rows_name_real_bringup_steps(rows: dict[str, tuple[str, str, str]]) -> None:
    known = _bringup_ids()
    settled = {ident: status for ident, (_, status, _) in rows.items() if status.startswith("settled at ")}
    assert settled, "no hardware-bound row"
    unknown = {ident: step for ident, status in settled.items()
               for step in status.removeprefix("settled at ").split(" — ")[0].split(", ") if step not in known}
    assert not unknown, f"steps that steps.yaml does not define: {unknown}"


def test_every_id_a_committed_plan_defines_has_a_row(rows: dict[str, tuple[str, str, str]]) -> None:
    defined: dict[str, str] = {}
    for name in PLANS:
        for line in (DESIGN / name).read_text(encoding="utf-8").splitlines():
            for match in DEFINED.finditer(line):
                defined.setdefault(match.group("table") or match.group("bold"), name)
    assert {"ATV-13", "OD-7", "OD21-11", "D-11", "KD-8", "ATV-40", "OD30-1", "D30-1"} <= set(defined)  # forms found
    missing = {ident: name for ident, name in defined.items() if ident not in rows}
    assert not missing, f"ids a plan defines without a register row: {missing}"


def test_namespaces_are_contiguous_and_the_closed_ones_complete(rows: dict[str, tuple[str, str, str]]) -> None:
    numbers: dict[str, list[int]] = {}
    for ident in rows:
        prefix, number = _number(ident)
        numbers.setdefault(prefix, []).append(number)
    for prefix, found in numbers.items():
        assert sorted(found) == list(range(1, max(found) + 1)), f"{prefix}: gaps in {sorted(found)}"
    assert max(numbers["v1 D"]) == 3 and max(numbers["ATV"]) >= 40
    assert {prefix: max(numbers[prefix]) for prefix in FROZEN_SIZES} == FROZEN_SIZES
    assert {"OD30", "D30"} <= set(numbers)


def test_design_links_resolve_and_the_readme_lists_every_design_file() -> None:
    broken = []
    for path in sorted(DESIGN.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if path.name not in LIVING:  # a frozen plan or log: only its blockquote header at the top is current
            text = "\n".join(line for line in text.splitlines()[:HEADER_LINES] if line.startswith(">"))
        for target in LINK.findall(text):
            if "://" in target or target.startswith("#"):
                continue
            if not (path.parent / target.split("#", 1)[0]).exists():
                broken.append(f"{path.name}: {target}")
    assert not broken, broken
    readme = (DESIGN / "README.md").read_text(encoding="utf-8")
    unlisted = [p.name for p in sorted(DESIGN.glob("*.md")) if p.name != "README.md" and f"]({p.name})" not in readme]
    assert not unlisted, f"docs/design/README.md does not list {unlisted}"
