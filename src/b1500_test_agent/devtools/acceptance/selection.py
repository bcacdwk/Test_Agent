"""Which scenarios an ``acceptance run`` launches (blueprint v2 8.2 cost policy): ids, ``--all``, ``--tag``,
``--affected``, pending scenarios and the session budget.

- **Base set**: the ``--scenario`` ids/files, else the whole suite (``tests/acceptance/scenarios/``) when ``--all``,
  ``--tag`` or ``--affected`` is given.
- **Tags** (``--tag F``, repeatable): keep scenarios carrying any of them (families ``smu cmu spgu wgfmu nvm
  reliability system``, topics ``manual bringup``); a module closure work package runs ``--tag <family>``.
- **Affected** (``--affected``): keep scenarios whose own file, ``touches`` globs or the ``GLOBAL_TOUCHES`` (files
  every session loads: AGENTS.md, CLAUDE.md, the entry skill, the harness wiring, the runner itself) match a file
  changed since the base: ``--since REF``, else the merge-base of ``HEAD`` with the commit of the newest committed
  report of this harness (``docs/acceptance/<date>-<harness>-<version>.md``). Changed = ``git diff --name-only
  <base>`` (commits, staged and unstaged, both sides of a rename) plus untracked files; a change in the generated
  ``.claude/skills/`` mirror counts as the same change in ``.agents/skills/``.
- **Pending**: a scenario whose ``requires`` are not met (``scenario.missing_requirements``) is skipped with the
  reason; naming it with ``--scenario`` is an error.
- **Budget** (``--max-sessions N``, applied by the runner): a scenario is started only when all its reps fit in what
  is left, so a safety scenario is never cut short; a functional re-run needs one more session.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from b1500_test_agent.devtools.acceptance.scenario import (
    Scenario,
    find_scenario,
    load_scenario,
    missing_requirements,
    recipe_statuses,
    scenario_files,
)

REPORT_DIR = "docs/acceptance"
GLOBAL_TOUCHES: tuple[str, ...] = (
    "AGENTS.md", "CLAUDE.md", ".agents/skills/b1500-test/SKILL.md", ".claude/settings.json", ".codex/rules/**",
    "config/harness/codex.config.toml", "config/harness/mcp.json", "scripts/hooks/**",
    "src/b1500_test_agent/adapters/mcp_server.py",
    "src/b1500_test_agent/devtools/harness.py", "src/b1500_test_agent/devtools/acceptance/runner.py",
    "src/b1500_test_agent/devtools/acceptance/infra.py",
    "src/b1500_test_agent/devtools/acceptance/harnesses.py", "src/b1500_test_agent/devtools/acceptance/approver.py",
    "src/b1500_test_agent/devtools/acceptance/scenario.py", "config/policy.example.yaml",
)  # fmt: skip
"""Files every session depends on (always-loaded instructions, entry skill, permission and harness wiring, the tool
surface, the runner with its infra watcher): a change to any of them affects every scenario. Of ``config/harness/``
only the two MCP launch templates count: a bump of ``validated.yaml`` (v2.1 plan §2.1) changes no session."""
MIRROR = (".claude/skills/", ".agents/skills/")
_REPORT_NAME = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<harness>[a-z]+)-(?P<version>.+)\.md$")
_COMMIT_LINE = re.compile(r"^- Repository commit: `?(?P<sha>[0-9a-f]{7,40})`?", re.MULTILINE)
_DESCRIBE_LINE = re.compile(r"repository (?P<describe>\S+) at ", re.MULTILINE)


class SelectionError(ValueError):
    """The selection cannot be made (unknown or pending scenario, no git base, duplicate ids)."""


@dataclass
class Selected:
    """One selected scenario: its file, parsed scenario and why it was selected."""

    path: Path
    scenario: Scenario
    why: list[str] = field(default_factory=list)

    @property
    def reps(self) -> int:
        return self.scenario.default_reps


@dataclass
class Selection:
    """The scenarios to run, the ones left out with the reason, and the facts behind ``--affected``."""

    selected: list[Selected] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    base: str | None = None
    base_source: str | None = None
    changed: list[str] = field(default_factory=list)

    def sessions(self, reps: int | None = None) -> int:
        """Planned sessions without re-runs (``reps`` overrides every scenario's reps)."""
        return sum(reps or item.reps for item in self.selected)

    def notes(self) -> list[str]:
        """Batch notes describing the selection (scenarios left out for the same reason are grouped)."""
        out = []
        if self.base is not None:
            out.append(f"--affected: base {self.base[:12]} ({self.base_source}); {len(self.changed)} changed file(s)")
        grouped: dict[str, list[str]] = {}
        for key, why in self.skipped.items():
            grouped.setdefault(why, []).append(key)
        out += [f"not run ({why}): {', '.join(keys)}" for why, keys in grouped.items()]
        return out


# -- git -------------------------------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SelectionError(f"git {' '.join(args)}: {exc}") from exc
    if result.returncode != 0:
        raise SelectionError(f"git {' '.join(args)}: {result.stderr.strip() or result.returncode}")
    return result.stdout


def resolve_commit(repo: Path, ref: str) -> str:
    """The full sha of ``ref`` (a sha, branch, tag or ``git describe`` output; a ``-dirty`` suffix is dropped)."""
    name = ref.removesuffix("-dirty")
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}").strip()


def report_commit(text: str) -> str | None:
    """The repository commit a report names: the ``Repository commit`` line (reports since WP6.6) or the ``git
    describe`` of the ``Runner`` line (older reports)."""
    match = _COMMIT_LINE.search(text)
    if match:
        return match.group("sha")
    match = _DESCRIBE_LINE.search(text)
    return match.group("describe") if match else None


def previous_report(repo: Path, harness: str) -> Path | None:
    """The newest committed report of ``harness`` (by the date in its name, then the version)."""
    found = []
    for path in (repo / REPORT_DIR).glob("*.md"):
        match = _REPORT_NAME.match(path.name)
        if match and match.group("harness") == harness:
            found.append((match.group("date"), match.group("version"), path))
    return max(found)[2] if found else None


def affected_base(repo: Path, harness: str, since: str | None = None) -> tuple[str, str]:
    """``(base sha, where it came from)`` for ``--affected`` (module docstring)."""
    if since is not None:
        return resolve_commit(repo, since), f"--since {since}"
    report = previous_report(repo, harness)
    if report is None:
        raise SelectionError(f"no committed {harness} report in {REPORT_DIR}/ to compare with; give --since REF")
    named = report_commit(report.read_text(encoding="utf-8"))
    if named is None:
        raise SelectionError(f"{report.name} names no repository commit; give --since REF")
    try:
        commit = resolve_commit(repo, named)
    except SelectionError as exc:
        raise SelectionError(f"{report.name} names commit {named!r}, which this clone does not have; give --since "
                             "REF") from exc
    base = _git(repo, "merge-base", "HEAD", commit).strip()
    return base, f"merge-base of HEAD and {report.name} ({named})"


def changed_files(repo: Path, base: str) -> list[str]:
    """Repository paths changed since ``base`` (committed, staged, unstaged; both sides of renames) and untracked
    files, with the ``.claude/skills/`` mirror mapped to ``.agents/skills/``."""
    names = _git(repo, "diff", "--name-only", "--no-renames", base).splitlines()
    names += _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    out = []
    for name in names:
        name = name.strip()
        if name.startswith(MIRROR[0]):
            name = MIRROR[1] + name[len(MIRROR[0]):]
        if name:
            out.append(name)
    return sorted(set(out))


# -- matching --------------------------------------------------------------------------------------------------------


def glob_matches(path: str, glob: str) -> bool:
    """Full match of a repository path against a glob: ``**`` crosses folders, ``*`` and ``?`` stay in one."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append(r"(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(r".*")
            i += 2
        elif glob[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.fullmatch("".join(out), path) is not None


def affected_by(scenario: Scenario, path: Path, repo: Path, changed: list[str]) -> list[str]:
    """The changed files that affect ``scenario`` (its own file, its ``touches``, ``GLOBAL_TOUCHES``)."""
    try:
        own = path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        own = None
    globs = [*scenario.touches, *GLOBAL_TOUCHES]
    return [name for name in changed if name == own or any(glob_matches(name, glob) for glob in globs)]


# -- selection -------------------------------------------------------------------------------------------------------


def _key(scenario: Scenario, path: Path) -> str:
    """How a pending scenario is named in notes: id and file (a rewritten scenario shares its id with the old one)."""
    return f"{scenario.id} ({path.name})"


def select(repo: Path, *, harness: str, scenarios: list[str] | None = None, all_: bool = False,
           tags: list[str] | None = None, affected: bool = False, since: str | None = None) -> Selection:
    """The scenarios of one ``acceptance run`` (module docstring)."""
    explicit = list(scenarios or [])
    if explicit and all_:
        raise SelectionError("give --scenario ID (repeatable) or --all, not both")
    if not (explicit or all_ or tags or affected):
        raise SelectionError("give --scenario ID (repeatable), --all, --tag F or --affected")
    statuses = recipe_statuses(repo)
    selection = Selection()
    if explicit:
        paths = [find_scenario(repo, s) for s in explicit]
    else:
        paths = scenario_files(repo, probes=False)
    candidates: list[Selected] = []
    for path in paths:
        scenario = load_scenario(path)
        missing = missing_requirements(scenario, repo, statuses)
        if missing:
            if explicit:
                raise SelectionError(f"{scenario.id} is pending: missing {', '.join(missing)}")
            selection.skipped[_key(scenario, path)] = "pending: missing " + ", ".join(missing)
            continue
        candidates.append(Selected(path, scenario, ["named" if explicit else "suite"]))
    if tags:
        wanted = set(tags)
        kept = []
        for item in candidates:
            hit = sorted(wanted & set(item.scenario.tags))
            if hit:
                item.why.append("tag " + ",".join(hit))
                kept.append(item)
            else:
                selection.skipped[item.scenario.id] = f"no tag of {sorted(wanted)}"
        candidates = kept
    if affected:
        selection.base, selection.base_source = affected_base(repo, harness, since)
        selection.changed = changed_files(repo, selection.base)
        kept = []
        for item in candidates:
            hits = affected_by(item.scenario, item.path, repo, selection.changed)
            if hits:
                item.why.append(f"affected by {hits[0]}" + (f" (+{len(hits) - 1})" if len(hits) > 1 else ""))
                kept.append(item)
            else:
                selection.skipped[item.scenario.id] = "not affected by the changes since the base"
        candidates = kept
    ids = [item.scenario.id for item in candidates]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SelectionError(f"several runnable scenario files carry the id(s) {duplicates}")
    selection.selected = candidates
    return selection
