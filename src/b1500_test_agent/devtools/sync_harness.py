"""``b1500 dev sync-harness [--check]``: the generated Claude Code copy of the canonical skills (blueprint 6.6).

Codex reads ``.agents/skills/``; Claude Code reads only ``.claude/skills/``. This tool writes a **full copy** (no
symlinks, no pointer stubs) of every skill folder under ``.agents/skills/`` that holds a ``SKILL.md`` (today
``b1500-test`` and, once it exists, ``b1500-debug``) into ``.claude/skills/<skill>/``, so relative links inside a
skill resolve identically in both harnesses.

- Markdown files (``*.md``) get ``GENERATED_LINE`` right after their YAML frontmatter (at the top when there is
  none); their text is normalised to UTF-8 without BOM and LF line endings, so the output is byte-stable on macOS
  and Windows. Every other file is copied byte for byte.
- Files in a mirrored skill folder that have no source are deleted, and so is the whole mirror folder of a skill
  whose source is gone (recognised by ``GENERATED_LINE`` in its ``SKILL.md``). Folders under ``.claude/skills/``
  that were not generated and have no source of the same name are left alone.
- OS junk (``.DS_Store``, ``Thumbs.db``, ``desktop.ini``, ``__pycache__/``) is ignored on both sides.

``check`` compares the expected copy with the mirror without writing anything and lists every drifted path as
``missing``, ``extra`` or ``changed`` (a symlink in the mirror counts as changed); ``sync`` writes only what
differs and then re-checks. ``b1500 doctor`` and the pytest suite run ``check`` on the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from b1500_test_agent.models.common import StrictModel

GENERATED_LINE = "<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->"
SOURCE_DIR = ".agents/skills"
MIRROR_DIR = ".claude/skills"
SKILL_FILE = "SKILL.md"
MARKDOWN_SUFFIX = ".md"
JUNK_FILES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
JUNK_DIRS = frozenset({"__pycache__"})
DriftKind = Literal["missing", "extra", "changed"]


class SyncError(ValueError):
    """A source tree that cannot be mirrored (a Markdown file that is not UTF-8, a symlinked directory)."""


class DriftItem(StrictModel):
    """One path where the mirror differs from the expected copy (``path`` is repository-relative, POSIX)."""

    kind: DriftKind
    path: str
    detail: str = ""


class SyncReport(StrictModel):
    """Outcome of ``check`` or ``sync``: ``ok`` iff there are no problems and no drift (after writing, for sync)."""

    ok: bool
    mode: Literal["check", "sync"]
    root: str
    skills: list[str] = Field(default_factory=list)
    files: int = 0
    written: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    drift: list[DriftItem] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


# -- Markdown rendering ----------------------------------------------------------------------------------------------


def normalize_text(raw: bytes) -> str:
    """UTF-8 text without BOM and with LF line endings; raises ``UnicodeDecodeError`` for non-UTF-8 bytes."""
    text = raw.decode("utf-8")
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def frontmatter_end(lines: list[str]) -> int | None:
    """Index of the closing ``---`` line of a YAML frontmatter that opens on line 0, else ``None``."""
    if not lines or lines[0].rstrip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            return index
    return None


def render_markdown(raw: bytes) -> bytes:
    """The mirrored form of one Markdown file: ``GENERATED_LINE`` after the frontmatter (or first), UTF-8, LF."""
    text = normalize_text(raw)
    lines = text.split("\n")
    end = frontmatter_end(lines)
    if end is None:
        return (GENERATED_LINE + "\n" + text).encode("utf-8")
    head = "\n".join(lines[: end + 1]) + "\n"
    rest = "\n".join(lines[end + 1 :])
    return (head + GENERATED_LINE + "\n" + rest).encode("utf-8")


def render_file(rel: str, raw: bytes) -> bytes:
    """Mirrored bytes of the source file at skill-relative ``rel``."""
    if rel.lower().endswith(MARKDOWN_SUFFIX):
        try:
            return render_markdown(raw)
        except UnicodeDecodeError as exc:
            raise SyncError(f"{rel}: not UTF-8 ({exc.reason} at byte {exc.start})") from None
    return raw


# -- Trees -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tree:
    """Regular files (relative POSIX path → absolute path) and symlinks found under one folder."""

    files: dict[str, Path]
    links: list[str]


def scan_tree(top: Path) -> Tree:
    """Walk ``top`` without following symlinks, skipping OS junk; paths relative to ``top``."""
    files: dict[str, Path] = {}
    links: list[str] = []
    for current, dirnames, filenames in os.walk(top, followlinks=False):
        base = Path(current)
        rel_base = base.relative_to(top)
        kept = []
        for name in sorted(dirnames):
            if name in JUNK_DIRS:
                continue
            if (base / name).is_symlink():
                links.append((rel_base / name).as_posix())
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            if name in JUNK_FILES:
                continue
            path = base / name
            rel = (rel_base / name).as_posix()
            if path.is_symlink():
                links.append(rel)
            else:
                files[rel] = path
    return Tree(files=files, links=sorted(links))


def source_skills(root: Path) -> list[str]:
    """Names of the skill folders under ``.agents/skills/`` that hold a ``SKILL.md``, sorted."""
    base = Path(root) / SOURCE_DIR
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / SKILL_FILE).is_file())


def _generated_skills(root: Path) -> list[str]:
    """Mirror folders whose ``SKILL.md`` carries ``GENERATED_LINE`` (written by this tool)."""
    base = Path(root) / MIRROR_DIR
    if not base.is_dir() or base.is_symlink():
        return []
    found = []
    for folder in base.iterdir():
        skill = folder / SKILL_FILE
        if folder.is_dir() and not folder.is_symlink() and skill.is_file():
            try:
                if GENERATED_LINE.encode("utf-8") in skill.read_bytes():
                    found.append(folder.name)
            except OSError:
                continue
    return sorted(found)


def expected_mirror(root: Path) -> dict[str, bytes]:
    """The expected mirror: repository-relative POSIX path under ``.claude/skills/`` → bytes."""
    root = Path(root)
    expected: dict[str, bytes] = {}
    for skill in source_skills(root):
        tree = scan_tree(root / SOURCE_DIR / skill)
        for rel in tree.links:
            target = root / SOURCE_DIR / skill / rel
            if target.is_dir():
                raise SyncError(f"{SOURCE_DIR}/{skill}/{rel}: symlinked directories are not mirrored; use a real "
                                "folder")
            if target.is_file():
                tree.files[rel] = target  # a file symlink is copied as its content (copies, never symlinks)
            else:
                raise SyncError(f"{SOURCE_DIR}/{skill}/{rel}: dangling symlink")
        for rel in sorted(tree.files):
            expected[f"{MIRROR_DIR}/{skill}/{rel}"] = render_file(rel, tree.files[rel].read_bytes())
    return expected


def _managed(root: Path) -> list[str]:
    return sorted(set(source_skills(root)) | set(_generated_skills(root)))


def _actual(root: Path, skills: list[str]) -> tuple[dict[str, Path], list[str]]:
    """Regular files and symlinks of the managed mirror folders (repository-relative POSIX paths)."""
    files: dict[str, Path] = {}
    links: list[str] = []
    mirror = root / MIRROR_DIR
    if mirror.is_symlink():
        return files, [MIRROR_DIR]
    for skill in skills:
        folder = mirror / skill
        prefix = f"{MIRROR_DIR}/{skill}"
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            links.append(prefix)
            continue
        if not folder.is_dir():
            continue
        tree = scan_tree(folder)
        files.update({f"{prefix}/{rel}": path for rel, path in tree.files.items()})
        links.extend(f"{prefix}/{rel}" for rel in tree.links)
    return files, sorted(links)


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def diff(expected: dict[str, bytes], files: dict[str, Path], links: list[str]) -> list[DriftItem]:
    """Drift between the expected copy and the mirror's files and symlinks, sorted by path."""
    items: list[DriftItem] = []
    for path, data in expected.items():
        link = next((link for link in links if _under(path, link)), None)
        if link is not None:
            items.append(DriftItem(kind="changed", path=path, detail=f"{link} is a symlink or not a folder"))
        elif path not in files:
            items.append(DriftItem(kind="missing", path=path))
        elif files[path].read_bytes() != data:
            items.append(DriftItem(kind="changed", path=path, detail="content differs from the rendered source"))
    items += [DriftItem(kind="extra", path=path, detail="no source file") for path in files if path not in expected]
    for link in links:
        if not any(_under(path, link) for path in expected):
            items.append(DriftItem(kind="extra", path=link, detail="symlink"))
    return sorted(items, key=lambda item: (item.path, item.kind))


# -- Commands --------------------------------------------------------------------------------------------------------


def check(root: Path) -> SyncReport:
    """Compare the mirror with the expected copy; writes nothing."""
    root = Path(root)
    try:
        expected = expected_mirror(root)
    except (SyncError, OSError) as exc:
        return SyncReport(ok=False, mode="check", root=root.as_posix(), problems=[str(exc)])
    skills = _managed(root)
    files, links = _actual(root, skills)
    drift = diff(expected, files, links)
    return SyncReport(ok=not drift, mode="check", root=root.as_posix(), skills=source_skills(root),
                      files=len(expected), drift=drift)


def _remove(path: Path) -> None:
    """Remove a file or a symlink (never follows a symlink into its target)."""
    if path.is_symlink() or path.is_file():
        path.unlink()


def _make_dirs(root: Path, folder: Path) -> None:
    """Create ``folder`` below ``root``, replacing any file or symlink that sits where a folder must be."""
    current = root
    for part in folder.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            current.unlink()
        if not current.exists():
            current.mkdir()


def _prune_empty(top: Path) -> None:
    """Remove folders under ``top`` (and ``top`` itself) that hold nothing but OS junk, bottom-up. Only ever
    called on generated mirror folders."""
    if not top.is_dir() or top.is_symlink():
        return
    for current, _, _ in sorted(os.walk(top), key=lambda entry: -len(Path(entry[0]).parts)):
        folder = Path(current)
        if not folder.is_dir() or folder.is_symlink():
            continue
        entries = list(folder.iterdir())
        if all(entry.name in JUNK_FILES and entry.is_file() for entry in entries):
            for entry in entries:
                entry.unlink()
            folder.rmdir()


def _write(root: Path, expected: dict[str, bytes], files: dict[str, Path], written: list[str]) -> None:
    """Write every expected file whose mirror copy is missing or differs; appends each written path."""
    for path, data in expected.items():
        target = root / path
        if path in files and target.is_file() and not target.is_symlink() and target.read_bytes() == data:
            continue
        _make_dirs(root, target.parent)
        if target.is_dir() and not target.is_symlink():
            raise SyncError(f"{path}: a non-empty folder sits where a file must be written; remove it by hand")
        target.write_bytes(data)
        written.append(path)


def sync(root: Path) -> SyncReport:
    """Write the expected copy into ``.claude/skills/`` (only changed files), delete stale files, then re-check."""
    root = Path(root)
    try:
        expected = expected_mirror(root)
    except (SyncError, OSError) as exc:
        return SyncReport(ok=False, mode="sync", root=root.as_posix(), problems=[str(exc)])
    skills = _managed(root)
    mirror = root / MIRROR_DIR
    removed: list[str] = []
    written: list[str] = []
    try:
        if mirror.is_symlink():
            mirror.unlink()
            removed.append(MIRROR_DIR)
        files, links = _actual(root, skills)
        for link in reversed(links):  # deepest first; unlinking never touches the link target
            _remove(root / link)
            removed.append(link)
        for path in sorted(files):
            if path not in expected:
                _remove(root / path)
                removed.append(path)
        for skill in skills:
            _prune_empty(mirror / skill)
        _write(root, expected, files, written)
    except (SyncError, OSError) as exc:
        report = check(root)
        return report.model_copy(update={"ok": False, "mode": "sync", "written": written, "removed": removed,
                                         "problems": [*report.problems, str(exc)]})
    after = check(root)
    return after.model_copy(update={"mode": "sync", "written": written, "removed": removed})


def format_report(report: SyncReport) -> str:
    """Human-readable report: verdict, then written/removed paths or the drift list."""
    skills = ", ".join(report.skills) or "none"
    if report.problems:
        head = f"skills mirror: ERROR ({MIRROR_DIR} from {SOURCE_DIR})"
    elif report.ok:
        head = f"skills mirror: in sync ({report.files} files; skills: {skills})"
    else:
        head = f"skills mirror: DRIFT ({len(report.drift)} paths; run uv run b1500 dev sync-harness)"
    lines = [head]
    lines += [f"  wrote   {path}" for path in report.written]
    lines += [f"  removed {path}" for path in report.removed]
    lines += [f"  {item.kind:<7} {item.path}" + (f" ({item.detail})" if item.detail else "") for item in report.drift]
    lines += [f"  problem: {problem}" for problem in report.problems]
    return "\n".join(lines)
