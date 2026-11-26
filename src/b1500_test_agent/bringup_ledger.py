"""Bring-up step sequence and step ledger, the base of ``b1500 bringup next | done | check`` (v2.1 plan §4.1).

Imports only ``models`` (layering test). Holds the stage-file readers (``frontmatter``, ``load_stage``,
``load_record``, the numbered items of a stage file; ``bringup.load_stage`` and ``bringup.load_record`` are these),
the loader of
``.agents/skills/b1500-bringup/steps.yaml`` (``StepsFile``), the ledger file and ``State``, the ledger read against
the sequence. The verbs are ``bringup_steps.py``, the verifiers ``bringup_verify.py``.

**Ledger.** ``<data>/state/bringup/ledger-<backend>.jsonl``, one ``LedgerEntry`` per ``done`` call, appended under a
lock file (``O_EXCL``, portable): each entry's ``sha256`` covers the entry and ``prev_sha256`` names the previous one
(the first names ``GENESIS_SHA256``), so a hand edit, a removed or an inserted line shows (``read_ledger`` stops at
the first such line). The simulator ledger is a different file: it never signs a hardware stage.

**Sequence** (``State``). Session 0 is the deployment group ``D``; afterwards every session starts with ``R1``… and
ends with ``E1``… (a session ends when its end steps passed, or after ``BREAK`` without an entry). The next step is
the first deployment step without a pass; then the end steps once one is recorded in the session; then the start
steps the session lacks; then the ``reconfirm`` steps of the current stage passed in an earlier session; then the
first stage step without a passing latest entry (it stays there after a ``fail``). Review steps ``<stage>.R`` never
block: they are awaiting review. A stage step can be recorded only after the deployment, the earlier stages and the
session start are complete (``State.order_problem``).
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.validation import (
    GENESIS_SHA256,
    LEDGER_DIR,
    STAGE_FILES_DIR,
    STEPS_FILE,
    EffectiveKind,
    LedgerEntry,
    StageFrontmatter,
    StepsFile,
    StepSpec,
    ValidationRecord,
    ledger_entry_sha256,
    stage_file_name,
    step_group,
)

BREAK = timedelta(hours=12)
"""A session ends after this long without a ledger entry (a night; a long run during the day does not end it)."""
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 120.0

# == stage files and records ==========================================================================================


def frontmatter(text: str) -> Any:
    """The YAML frontmatter of a Markdown file (``None`` when it has none)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    return None if end is None else yaml.safe_load("\n".join(lines[1:end]))


def load_stage(repo_root: Path, stage: str) -> tuple[Path, StageFrontmatter | None, str | None]:
    """``(path, frontmatter, problem)`` of the stage file of ``stage`` (frontmatter ``None`` when the file is missing
    or does not validate; ``problem`` says why in the latter case)."""
    path = Path(repo_root).joinpath(*STAGE_FILES_DIR, stage_file_name(stage))
    if not path.is_file():
        return path, None, None
    try:
        return path, StageFrontmatter.model_validate(frontmatter(path.read_text(encoding="utf-8"))), None
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
        return path, None, f"{path.name}: unreadable stage frontmatter ({type(exc).__name__})"


def load_record(path: Path) -> ValidationRecord:
    """A record file (raises ``ValueError`` with the reason when it is not one)."""
    try:
        return ValidationRecord.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
        reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else type(exc).__name__
        raise ValueError(f"{path.name} is not a validation record: {reason}") from None


def stage_sections(text: str) -> dict[int, list[str]]:
    """The lines of each ``## N. Title`` section of a stage file."""
    sections: dict[int, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        match = re.match(r"^## (\d+)\. ", line)
        if match:
            current = sections.setdefault(int(match[1]), [])
        elif line.startswith("## "):
            current = None
        elif current is not None:
            current.append(line)
    return sections


def stage_items(text: str) -> dict[str, str]:
    """The numbered items of a stage file: ``P<n>`` (section 2, physical steps) and ``A<n>`` (section 3, agent
    steps) -> the item's text on one line (continuation lines are indented)."""
    items: dict[str, list[str]] = {}
    sections = stage_sections(text)
    for number, prefix in ((2, "P"), (3, "A")):
        current: str | None = None
        for line in sections.get(number, []):
            match = re.match(r"^(\d+)\.\s+(.*)$", line)
            if match:
                current = f"{prefix}{match[1]}"
                items[current] = [match[2].strip()]
            elif current is not None and line[:1].isspace() and line.strip():
                items[current].append(line.strip())
            else:
                current = None
    return {key: " ".join(parts) for key, parts in items.items()}


def steps_path(repo_root: Path) -> Path:
    return Path(repo_root).joinpath(*STEPS_FILE)


def load_steps(repo_root: Path) -> StepsFile:
    """``steps.yaml`` of the repository (raises ``ValueError`` with the reason)."""
    path = steps_path(repo_root)
    try:
        return StepsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise ValueError(f"{'/'.join(STEPS_FILE)} is missing (it is committed with the repository)") from None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{'/'.join(STEPS_FILE)} is not readable YAML ({type(exc).__name__})") from None
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ValueError(f"{'/'.join(STEPS_FILE)} does not validate: {'.'.join(map(str, first['loc']))}: "
                         f"{first['msg']} (uv run b1500 dev lint-skills)") from None


# == the ledger =======================================================================================================


@dataclass
class Ledger:
    """The entries read in order up to the first problem (a line that does not parse, whose ``sha256`` does not
    match its content or that breaks the chain)."""

    path: Path
    entries: list[LedgerEntry]
    problems: list[str]


def ledger_path(bundle: Any) -> Path:
    return Path(bundle.paths.state_dir) / LEDGER_DIR / f"ledger-{bundle.backend}.jsonl"


def read_ledger(path: Path) -> Ledger:
    entries: list[LedgerEntry] = []
    if not path.is_file():
        return Ledger(path, entries, [])
    previous = GENESIS_SHA256
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = LedgerEntry.model_validate(json.loads(line))
        except (ValueError, ValidationError) as exc:
            return Ledger(path, entries, [f"line {number} is not a ledger entry ({type(exc).__name__})"])
        if entry.sha256 != ledger_entry_sha256(entry.model_dump(mode="json")):
            return Ledger(path, entries, [(f"line {number} ({entry.step}): its content does not match its sha256 "
                                          "(edited by hand?)")])
        if entry.prev_sha256 != previous or entry.seq != number:
            return Ledger(path, entries, [(f"line {number} ({entry.step}): the hash chain breaks here (a line was "
                                          "edited, removed or inserted before it)")])
        entries.append(entry)
        previous = entry.sha256
    return Ledger(path, entries, [])


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """An exclusive lock file next to the ledger (``O_EXCL``, portable); a lock older than ``LOCK_STALE_S`` is
    taken over."""
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"the ledger lock {lock.name} is held by another process") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def append_entry(path: Path, build: Callable[[int, str], LedgerEntry]) -> LedgerEntry:
    """Append the entry ``build(seq, prev_sha256)`` returns, under the lock (``ValueError`` on a damaged ledger)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        ledger = read_ledger(path)
        if ledger.problems:
            raise ValueError(f"the ledger is damaged: {ledger.problems[0]}")
        entry = build(len(ledger.entries) + 1, ledger.entries[-1].sha256 if ledger.entries else GENESIS_SHA256)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n")
    return entry


def make_entry(seq: int, prev: str, **fields: Any) -> LedgerEntry:
    """A ledger entry with its ``sha256`` (``fields``: everything but ``seq``, ``prev_sha256`` and ``sha256``)."""
    data = LedgerEntry(seq=seq, prev_sha256=prev, sha256=GENESIS_SHA256, **fields).model_dump(mode="json")
    data["sha256"] = ledger_entry_sha256(data)
    return LedgerEntry.model_validate(data)


# == the sequence =====================================================================================================


def effective_kind(spec: StepSpec, backend: Backend) -> EffectiveKind | None:
    """How ``done`` verifies ``spec`` on ``backend`` (``None``: not rehearsed on the simulator)."""
    if backend != "sim":
        return spec.verify
    return {"run_sim": spec.verify, "refusal": "refusal", "human_done": "confirm", "skip": None}[spec.rehearsal]


@dataclass
class State:
    """The ledger read against the sequence: latest entry per step overall and in the current session."""

    steps: StepsFile
    backend: Backend
    entries: list[LedgerEntry]
    now: datetime
    session_start: int = 0
    latest: dict[str, LedgerEntry] = field(default_factory=dict)
    session: dict[str, LedgerEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ends = {s.id for s in self.steps.session_end if self.required(s)}
        start = 0
        for index, entry in enumerate(self.entries):
            if index and entry.ts - self.entries[index - 1].ts > BREAK:
                start = max(start, index)
            if ends and entry.step in ends and ends <= {e.step for e in self.entries[start:index + 1]
                                                        if e.verdict == "pass"}:
                start = index + 1
        if self.entries and self.now - self.entries[-1].ts > BREAK:
            start = len(self.entries)
        self.session_start = start
        self.latest = {e.step: e for e in self.entries}
        self.session = {e.step: e for e in self.entries[start:]}

    def required(self, spec: StepSpec) -> bool:
        return effective_kind(spec, self.backend) is not None

    def passed(self, spec: StepSpec) -> bool:
        entry = self.latest.get(spec.id)
        return entry is not None and entry.verdict == "pass"

    def passed_in_session(self, spec: StepSpec) -> bool:
        entry = self.session.get(spec.id)
        return entry is not None and entry.verdict == "pass"

    def open_deployment(self) -> list[StepSpec]:
        return [s for s in self.steps.deployment if self.required(s) and not self.passed(s)]

    def stage_open(self, stage: str) -> list[StepSpec]:
        """Required steps of ``stage`` without a pass, review step left out."""
        return [s for s in self.steps.stages.get(stage, []) if self.required(s) and not s.is_review
                and not self.passed(s)]

    def position(self) -> StepSpec | None:
        """The first stage step (review steps left out) without a passing latest entry."""
        return next((opened[0] for stage in self.steps.stages if (opened := self.stage_open(stage))), None)

    def awaiting_review(self) -> list[str]:
        """Review steps of the stages whose other steps all passed."""
        return [s.id for stage, specs in self.steps.stages.items() if not self.stage_open(stage)
                for s in specs if s.is_review and self.required(s) and not self.passed(s)]

    def reconfirm(self, position: StepSpec | None) -> list[StepSpec]:
        """Steps of the current stage with ``reconfirm`` passed before this session and not in it."""
        if position is None:
            return []
        specs = self.steps.stages[position.group]
        before = specs[:specs.index(position)]
        return [s for s in before if s.reconfirm and self.required(s) and self.passed(s)
                and not self.passed_in_session(s)]

    def next(self) -> tuple[StepSpec | None, Literal["open", "failed", "reconfirm"]]:
        """The next step and why (module docstring)."""
        opened = self.open_deployment()
        if opened:
            return opened[0], self.state_of(opened[0])
        ending = any(step_group(step) == "E" for step in self.session)
        groups = (self.steps.session_end, self.steps.session_start) if ending else (self.steps.session_start,)
        for group in groups:
            for spec in group:
                if self.required(spec) and not self.passed_in_session(spec):
                    return spec, self.state_of(spec, session=True)
        position = self.position()
        again = self.reconfirm(position)
        if again:
            return again[0], "reconfirm"
        return position, self.state_of(position) if position is not None else "open"

    def state_of(self, spec: StepSpec, *, session: bool = False) -> Literal["open", "failed"]:
        entry = (self.session if session else self.latest).get(spec.id)
        return "failed" if entry is not None and entry.verdict == "fail" else "open"

    def progress(self) -> dict[str, str]:
        """Passed / required steps: ``D``, every stage (review step included), ``R`` and ``E`` of this session."""
        out = {"D": self._count(self.steps.deployment, self.passed)}
        out.update({stage: self._count(specs, self.passed) for stage, specs in self.steps.stages.items()})
        out["R"] = self._count(self.steps.session_start, self.passed_in_session)
        out["E"] = self._count(self.steps.session_end, self.passed_in_session)
        return out

    def _count(self, specs: Sequence[StepSpec], passed: Callable[[StepSpec], bool]) -> str:
        required = [s for s in specs if self.required(s)]
        return f"{sum(passed(s) for s in required)}/{len(required)}"

    def order_problem(self, spec: StepSpec) -> str | None:
        """Why ``spec`` cannot be recorded yet (``None``: it can)."""
        if spec.group == "D":
            return None
        opened = self.open_deployment()
        if opened:
            return (f"session 0 (deployment) is not complete: {', '.join(s.id for s in opened[:4])} first "
                    "(`uv run b1500 bringup next`)")
        if spec.group in ("R", "E") or spec.is_review:
            return None
        for stage in self.steps.stages:
            if stage == spec.group:
                break
            opened = self.stage_open(stage)
            if opened:
                return (f"stage {stage} is not complete ({', '.join(s.id for s in opened[:4])}"
                        f"{' ...' if len(opened) > 4 else ''}): its steps come first")
        start = [s.id for s in self.steps.session_start if self.required(s) and not self.passed_in_session(s)]
        if start:
            return f"this session starts with {', '.join(start)} (`uv run b1500 bringup next`)"
        return None
