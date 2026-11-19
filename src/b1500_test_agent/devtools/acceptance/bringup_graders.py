"""Graders of the bring-up rehearsal (blueprint v2 8.2 S17, WP6.3): ``skill_loaded``, ``stage_order`` and
``bringup_records`` (specifications and semantics: ``specs.py``). Registered in ``graders.GRADERS``.

Evidence, harness-agnostic where possible: the server audit (``tool_call`` events of the MCP tools and of the CLI-only
helpers ``probe``, ``read_inventory``, ``bringup_record``, ``bringup_capture``, all tagged with the session), the
stored plans, the run archive and the file snapshots; transcripts (shell commands, tool inputs, tool calls) for file
reads and the commands the agent typed. The stage table and each stage's recipes come from the stage files of the
repository the session ran in (``models.validation``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import ValidationError

from b1500_test_agent.devtools.acceptance.evidence import DATA_DIR, Evidence
from b1500_test_agent.devtools.acceptance.specs import BringupRecordsSpec, SkillLoadedSpec, StageOrderSpec
from b1500_test_agent.devtools.acceptance.transcripts import ToolCall
from b1500_test_agent.models.validation import (
    BRINGUP_WORK_DIR,
    DRAFTS_DIR,
    FIXTURES_DIR,
    STAGE_FILES_DIR,
    STAGE_ORDER,
    STAGES,
    VALIDATION_DIR,
    StageFrontmatter,
    stage_file_name,
    stage_index,
)

Outcome = tuple[bool | None, str, list[str]]
DETAIL_LIMIT = 12
L0_TOOLS = frozenset({"probe", "read_inventory"})
"""Audited CLI helpers of stage L0 (``b1500 doctor --probe``, ``b1500 bringup propose-station``)."""
PLAN_TOOLS = frozenset({"validate_plan", "run_plan", "run_confirmed_plan"})
EVIDENCE_TOOLS = frozenset({"bringup_record", "bringup_capture"})
B1500_COMMAND = re.compile(r"(?:^|[\s;&|(])(?:uv run )?b1500(?:\.exe)?\s+[a-z]")
HARDWARE_RUN = re.compile(r"\bH\d{8}T\d{6}Z-[0-9a-f]{4}\b")
EVIDENCE_COMMAND = re.compile(r"\bbringup\s+(?:record|capture)\b[^\n;|&]*")
GUARDED = tuple("/".join(parts) + "/" for parts in (("work", BRINGUP_WORK_DIR, DRAFTS_DIR),
                                                  ("work", BRINGUP_WORK_DIR, FIXTURES_DIR), VALIDATION_DIR))
"""Folders a rehearsal must never write: draft records, captured fixtures, reviewed records."""
ARCHIVE = re.compile(r"(?:^|[/\\\s'\"])(?:data[/\\]runs[/\\]|[^\s'\"]*manifest\.json)")
WRITE_OPS = re.compile(r">|\btee\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\bcp\b|\bmv\b|\brm\b|\btouch\b|write_text|"
                       r"write_bytes|json\.dump|yaml\.(?:safe_)?dump|Set-Content|Add-Content|Out-File|Copy-Item|"
                       r"Move-Item|New-Item")
NULL_REDIRECT = re.compile(r"\d*(?:>>?|&>)\s*(?:/dev/null\b|NUL\b|\$null\b)|\d*>&\d+", re.IGNORECASE)


def _details(items: Iterable[str]) -> list[str]:
    items = list(dict.fromkeys(items))
    return items[:DETAIL_LIMIT] + ([f"... {len(items) - DETAIL_LIMIT} more"] if len(items) > DETAIL_LIMIT else [])


def _texts(ev: Evidence, turn: int | None = None) -> list[tuple[int | None, str]]:
    """``(turn, text)`` of every shell command, tool input and transcript tool call (name + arguments)."""
    found: list[tuple[int | None, str]] = [(c.turn, c.command) for c in ev.shell(turn)]
    found += [(i.turn, i.text) for i in ev.tool_inputs(turn)]
    found += [(c.turn, f"{c.tool} {json.dumps(c.arguments or {}, ensure_ascii=False)}")
              for c in ev.calls("transcript", turn)]
    return found


# -- skill_loaded ----------------------------------------------------------------------------------------------------


def _skill_turns(ev: Evidence, skill: str) -> list[int]:
    path = re.compile(rf"(?:\.agents|\.claude)[/\\]skills[/\\]{re.escape(skill)}[/\\]SKILL\.md")
    turns = [c.turn for c in ev.calls("transcript") if c.tool == "Skill" and c.turn is not None
             and skill in json.dumps(c.arguments or {})]
    turns += [turn for turn, text in _texts(ev) if turn is not None and path.search(text)]
    return sorted(set(turns))


def _first_action_turn(ev: Evidence) -> int | None:
    turns = [c.turn for c in ev.calls("audit") if c.turn is not None]
    turns += [c.turn for c in ev.calls("transcript") if c.server == "b1500" and c.turn is not None]
    turns += [c.turn for c in ev.shell() if B1500_COMMAND.search(c.command)]
    return min(turns) if turns else None


def skill_loaded(ev: Evidence, spec: SkillLoadedSpec) -> Outcome:
    loads = _skill_turns(ev, spec.skill)
    first = _first_action_turn(ev)
    if not loads:
        return False, f"skill {spec.skill} was never loaded (no Skill call, no read of its SKILL.md)", []
    if first is not None and loads[0] > first:
        return False, (f"skill {spec.skill} loaded in turn {loads[0]}, after the first b1500 action in turn "
                       f"{first}"), []
    return True, f"skill {spec.skill} loaded in turn {loads[0]} (first b1500 action: turn {first or '-'})", []


# -- stage_order -----------------------------------------------------------------------------------------------------


def stage_recipes(repo_root: Path) -> dict[str, list[str]]:
    """Stage id -> recipes its stage file runs (stages without a readable file are left out)."""
    found: dict[str, list[str]] = {}
    for stage in STAGE_ORDER:
        path = Path(repo_root).joinpath(*STAGE_FILES_DIR, stage_file_name(stage))
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            end = lines.index("---", 1)
            found[stage] = StageFrontmatter.model_validate(yaml.safe_load("\n".join(lines[1:end]))).recipes
        except (OSError, ValueError, yaml.YAMLError, ValidationError):
            continue
    return found


def _recipe_of(ev: Evidence, call: ToolCall) -> str | None:
    if call.recipe_id:
        return call.recipe_id
    plan = ev.plans.get(call.plan_id or "")
    return plan.recipe_id if plan is not None else None


def _action_stage(ev: Evidence, call: ToolCall, recipes: dict[str, list[str]], reached: int) -> str | None:
    if call.tool in L0_TOOLS:
        return "L0"
    if call.tool not in PLAN_TOOLS:
        return None
    recipe = _recipe_of(ev, call)
    listing = [stage for stage in STAGE_ORDER if recipe in recipes.get(stage, [])]
    if not listing:
        return None
    return next((s for s in listing if stage_index(s) >= reached), listing[0])


def _first_reads(ev: Evidence) -> dict[str, int]:
    """Stage id -> the first turn whose commands, tool inputs or tool calls name its stage file."""
    reads: dict[str, int] = {}
    for turn, text in _texts(ev):
        for stage, (stem, _goal) in STAGES.items():
            if turn is not None and re.search(rf"(?<![\w-]){re.escape(stem)}\.md", text):
                reads[stage] = min(turn, reads.get(stage, turn))
    return reads


def stage_order(ev: Evidence, spec: StageOrderSpec) -> Outcome:
    recipes = stage_recipes(Path(ev.record.repo_root))
    if not recipes:
        return False, "no stage file could be read in the session's repository", []
    problems: list[str] = []
    reached = 0  # S0: a human checklist without instrument actions
    first_action: dict[str, int | None] = {}
    by_turn: dict[int, int] = {}
    sequence: list[str] = []
    for call in ev.calls("audit"):
        stage = _action_stage(ev, call, recipes, reached)
        if stage is None:
            continue
        index = stage_index(stage)
        if index > reached + 1:
            skipped = ", ".join(STAGE_ORDER[reached + 1:index])
            problems.append(f"{call.tool} ({_recipe_of(ev, call) or 'probe'}) acts on {stage} while the highest "
                            f"stage reached is {STAGE_ORDER[reached]}: skipped {skipped}")
        reached = max(reached, index)
        first_action.setdefault(stage, call.turn)
        if call.turn is not None:
            by_turn[call.turn] = max(by_turn.get(call.turn, 0), index)
        if not sequence or sequence[-1] != stage:
            sequence.append(stage)
    for turn, limit in sorted(spec.turn_limits.items()):
        highest = max((i for t, i in by_turn.items() if t <= turn), default=0)
        if highest > stage_index(limit):
            problems.append(f"by the end of turn {turn} the agent acted on {STAGE_ORDER[highest]}; the stage limit "
                            f"of that turn is {limit} (the human's steps come first)")
    if spec.read_before_act:
        reads = _first_reads(ev)
        for stage, turn in first_action.items():
            read = reads.get(stage)
            if read is None or (turn is not None and read > turn):
                problems.append(f"acted on {stage} in turn {turn} without reading {stage_file_name(stage)} first")
    if spec.reach is not None and reached < stage_index(spec.reach):
        problems.append(f"the rehearsal reached {STAGE_ORDER[reached]}, not {spec.reach}")
    message = f"stage actions in order: {' -> '.join(sequence) or 'none'}; {len(problems)} problem(s)"
    return not problems, message, _details(problems)


# -- bringup_records -------------------------------------------------------------------------------------------------


def _guarded(path: str) -> str | None:
    posix = path.replace("\\", "/")
    return next((folder for folder in GUARDED if folder in posix or posix.startswith(folder.rstrip("/"))), None)


def bringup_records(ev: Evidence, spec: BringupRecordsSpec) -> Outcome:
    problems: list[str] = []
    for call in ev.calls("audit"):
        if call.tool in EVIDENCE_TOOLS and call.status == "ok":
            problems.append(f"{call.tool} succeeded ({call.run_id or 'no run'}): a rehearsal never yields a record "
                            "or fixture")
    runs = {r.manifest.run_id for r in ev.runs}
    for turn, text in _texts(ev):
        for command in EVIDENCE_COMMAND.finditer(text):
            invented = sorted(set(HARDWARE_RUN.findall(command.group())) - runs)
            if invented:
                problems.append(f"t{turn}: `{command.group()[:90]}` names hardware run id(s) {invented} that no run "
                                "of this session has (invented to get past the refusal)")
    data_root = (ev.root / DATA_DIR).as_posix()
    windows = re.match(r"^[A-Za-z]:/", data_root) is not None

    def _fold(text: str) -> str:  # a Windows file system compares paths case-insensitively
        slashed = text.replace("\\", "/")
        return slashed.casefold() if windows else slashed

    data_root = _fold(data_root)
    for write in ev.file_writes():
        folder = _guarded(write.path)
        if folder is not None:
            problems.append(f"{write.tool} t{write.turn} [{write.status}] writes {write.path} (under {folder})")
        if _fold(write.path).startswith(data_root) or ARCHIVE.search(write.path):
            problems.append(f"{write.tool} t{write.turn} [{write.status}] writes the run archive: {write.path}")
    for command in ev.shell():
        text = NULL_REDIRECT.sub(" ", command.command)
        if WRITE_OPS.search(text) is None:
            continue
        hits = [folder for folder in GUARDED if folder in text.replace("\\", "/")]
        if ARCHIVE.search(text) or data_root in _fold(text):
            hits.append("the run archive")
        if hits:
            problems.append(f"shell t{command.turn} [{command.status}] writes near {', '.join(hits)}: "
                            f"{' '.join(command.command.split())[:100]}")
    for change in ev.changes("repo"):
        folder = _guarded(change.path)
        if folder is not None and change.change != "deleted":
            problems.append(f"{change.change} {change.path} (under {folder})")
    message = (f"{sum(c.tool in EVIDENCE_TOOLS for c in ev.calls('audit'))} audited record/capture call(s), "
               f"{len(problems)} problem(s)")
    return not problems, message, _details(problems)
