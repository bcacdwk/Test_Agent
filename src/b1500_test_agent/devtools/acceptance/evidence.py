"""Session folder layout, the session record and the evidence graders read (blueprint 2.7, 8.2).

One folder per session (the runner writes it; ``acceptance grade`` re-reads it)::

    <session>/
        session.json        SessionRecord: scenario, harness + version, tag, turns (argv, times, exit, session id),
                            seeds, hashes and git status before/after, file changes, harness facts, notes
        scenario.yaml       copy of the scenario as run
        config/             the temporary B1500_CONFIG_DIR (copied examples + overlays)
        data/               the temporary B1500_DATA_DIR: runs/ (archive, index.jsonl), state/ (audit/ with the
                            server's tool_call events, plans/, sim/<scenario>.state.json with the command log)
        transcripts/        turn-<n>.jsonl, turn-<n>.stderr.txt, codex-rollout.jsonl (Codex), prompts.jsonl
                            (Claude permission prompts answered by the runner)
        mcp/                per-turn harness MCP configs
        changed/            copies of repository / config files the session added or changed
        grades.json         SessionGrade

``Evidence`` attributes every timestamped item to a turn (its ``[started_at, finished_at]`` window, 2 s grace) and
drops everything from before the first turn and from the runner's seeding phase (``seeded_at``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.acceptance.scenario import Scenario, load_scenario
from b1500_test_agent.devtools.acceptance.transcripts import (
    FileWrite,
    HarnessName,
    ShellCommand,
    ToolCall,
    ToolInput,
    TurnTranscript,
    parse_codex_rollout,
    parse_turn,
)
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.policy import Policy
from b1500_test_agent.models.run import RunManifest
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.sim.state import CommandRecord, SimPersistentState

SESSION_FILE = "session.json"
SCENARIO_FILE = "scenario.yaml"
GRADES_FILE = "grades.json"
CONFIG_DIR = "config"
DATA_DIR = "data"
TRANSCRIPTS_DIR = "transcripts"
MCP_DIR = "mcp"
CHANGED_DIR = "changed"
ROLLOUT_FILE = f"{TRANSCRIPTS_DIR}/codex-rollout.jsonl"
PROMPTS_FILE = f"{TRANSCRIPTS_DIR}/prompts.jsonl"
TURN_GRACE = timedelta(seconds=2)


class TurnRecord(BaseModel):
    """One harness invocation (new session or resume)."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    prompt: str
    argv: list[str]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    exit_code: int | None = None
    timed_out: bool = False
    session_id: str | None = None
    transcript: str
    stderr: str
    approve_confirm_tool: bool = True


class FileChange(BaseModel):
    """A file the session added, modified or deleted (``area`` ``repo`` = the repository, ``runner_config`` = the
    runner's temporary config dir). ``copy`` is the copy in ``changed/``; ``removed_by_runner`` marks a new
    ``work/`` file the runner deleted after copying it (so the next session starts clean)."""

    model_config = ConfigDict(extra="forbid")

    area: Literal["repo", "runner_config"]
    path: str
    change: Literal["added", "modified", "deleted"]
    sha256_before: str | None = None
    sha256_after: str | None = None
    copy_path: str | None = None
    removed_by_runner: bool = False


class SessionRecord(BaseModel):
    """``session.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    scenario_id: str
    scenario_title: str
    safety: bool
    rep: int = Field(ge=1)
    rerun: bool = False
    harness: HarnessName
    harness_version: str
    session_tag: str
    repo_root: str
    runner_version: str
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    turns: list[TurnRecord] = Field(default_factory=list)
    seeds: dict[str, dict[str, str]] = Field(default_factory=dict)
    seeded_at: AwareDatetime | None = None
    """End of the runner's seeding phase: evidence stamped at or before it is the runner's, never the agent's (the
    seeds are created right before turn 1, inside the turn grace)."""
    hashes_before: dict[str, str] = Field(default_factory=dict)
    hashes_after: dict[str, str] = Field(default_factory=dict)
    git_status_before: list[str] = Field(default_factory=list)
    git_status_after: list[str] = Field(default_factory=list)
    changes: list[FileChange] = Field(default_factory=list)
    harness_info: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


@dataclass
class RunEvidence:
    """One archived run: its manifest, folder, analysis files, notes and turn."""

    manifest: RunManifest
    folder: Path
    analyses: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    turn: int | None


@dataclass
class Evidence:
    """Everything the graders read for one session (see the module docstring)."""

    root: Path
    record: SessionRecord
    scenario: Scenario
    transcripts: list[TurnTranscript] = field(default_factory=list)
    audit_calls: list[ToolCall] = field(default_factory=list)
    runs: list[RunEvidence] = field(default_factory=list)
    plans: dict[str, PlanRecord] = field(default_factory=dict)
    plan_turns: dict[str, int | None] = field(default_factory=dict)
    sim_commands: list[tuple[CommandRecord, int | None]] = field(default_factory=list)
    sim_states: dict[str, SimPersistentState] = field(default_factory=dict)
    """Simulator state files at the end of the session by scenario name (switch states, outputs, command log)."""
    audit_io: list[tuple[datetime, str]] = field(default_factory=list)
    rollout_inputs: list[ToolInput] = field(default_factory=list)
    rollout_files: list[FileWrite] = field(default_factory=list)
    policy: Policy | None = None
    sim_models: dict[str, Any] = field(default_factory=dict)
    sim_scenario: SimScenario | None = None
    prompts: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    # -- turns ---------------------------------------------------------------------------------------------------

    @property
    def turn_count(self) -> int:
        return len(self.record.turns)

    @property
    def session_start(self) -> datetime | None:
        return self.record.turns[0].started_at if self.record.turns else None

    def in_session(self, ts: datetime | None) -> bool:
        """``ts`` is at or after the first turn's start (grace ``TURN_GRACE``) and after the seeding phase."""
        start = self.session_start
        if ts is None or start is None:
            return False
        seeded = self.record.seeded_at
        return ts >= start - TURN_GRACE and (seeded is None or ts > seeded)

    def turn_of(self, ts: datetime | None) -> int | None:
        """The turn whose window contains ``ts``; else the nearest window within the grace (``None`` otherwise)."""
        return turn_index(self.record.turns, ts)

    @staticmethod
    def _in(turn: int | None, wanted: int | None) -> bool:
        return wanted is None or turn == wanted

    # -- selections ----------------------------------------------------------------------------------------------

    def transcript(self, turn: int) -> TurnTranscript | None:
        return next((t for t in self.transcripts if t.turn == turn), None)

    def calls(self, source: Literal["audit", "transcript"], turn: int | None = None) -> list[ToolCall]:
        """Tool calls in scope: audit (in session, ordered by time) or transcript (harness order)."""
        if source == "audit":
            return [c for c in self.audit_calls if self.in_session(c.ts) and self._in(c.turn, turn)]
        return [c for t in self.transcripts if self._in(t.turn, turn) for c in t.tool_calls]

    def shell(self, turn: int | None = None) -> list[ShellCommand]:
        return [c for t in self.transcripts if self._in(t.turn, turn) for c in t.shell]

    def file_writes(self, turn: int | None = None) -> list[FileWrite]:
        return ([w for t in self.transcripts if self._in(t.turn, turn) for w in t.files]
                + [w for w in self.rollout_files if self._in(w.turn, turn)])

    def tool_inputs(self, turn: int | None = None) -> list[ToolInput]:
        return ([i for t in self.transcripts if self._in(t.turn, turn) for i in t.tool_inputs]
                + [i for i in self.rollout_inputs if self._in(i.turn, turn)])

    def final_answer(self, turn: int | None = None) -> str:
        """The final answer of ``turn`` (default: the last turn)."""
        wanted = turn if turn is not None else self.turn_count
        transcript = self.transcript(wanted)
        return transcript.final_answer if transcript else ""

    def messages(self, turn: int | None = None) -> str:
        """Every agent message (and final answer) of ``turn`` (default: all turns)."""
        parts = []
        for t in self.transcripts:
            if self._in(t.turn, turn):
                parts += t.messages
                if t.final_answer and t.final_answer not in t.messages:
                    parts.append(t.final_answer)
        return "\n".join(parts)

    def runs_in(self, turn: int | None = None) -> list[RunEvidence]:
        """Runs started in scope (seeded runs excluded)."""
        return [r for r in self.runs if self.in_session(r.manifest.started_at) and self._in(r.turn, turn)]

    def plans_in(self, turn: int | None = None) -> list[PlanRecord]:
        """Plans created in scope (seeded plans excluded)."""
        return [p for p in self.plans.values()
                if self.in_session(p.created_at) and self._in(self.plan_turns.get(p.plan_id), turn)]

    def commands_in(self, turn: int | None = None) -> list[CommandRecord]:
        return [c for c, t in self.sim_commands if self.in_session(_parse_ts(c.ts)) and self._in(t, turn)]

    def changes(self, area: str | None = None) -> list[FileChange]:
        return [c for c in self.record.changes if area is None or c.area == area]

    def changed_text(self, change: FileChange) -> str | None:
        """The content of a changed file's copy (``None`` when not copied or not UTF-8 text)."""
        if change.copy_path is None:
            return None
        try:
            return (self.root / change.copy_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


def turn_index(turns: list[TurnRecord], ts: datetime | None) -> int | None:
    """The turn whose ``[started_at, finished_at]`` contains ``ts``; else the nearest one within ``TURN_GRACE``."""
    if ts is None:
        return None
    best: tuple[timedelta, int] | None = None
    for turn in turns:
        end = turn.finished_at or datetime.max.replace(tzinfo=UTC)
        if turn.started_at <= ts <= end:
            return turn.index
        gap = turn.started_at - ts if ts < turn.started_at else ts - end
        if gap <= TURN_GRACE and (best is None or gap < best[0]):
            best = (gap, turn.index)
    return best[1] if best else None


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []


def _audit_calls(ev: Evidence) -> list[ToolCall]:
    calls: list[ToolCall] = []
    audit_dir = ev.root / DATA_DIR / "state" / "audit"
    for path in sorted(audit_dir.glob("*.jsonl")) if audit_dir.is_dir() else []:
        for line in _read_lines(path):
            try:
                record = json.loads(line)
            except ValueError:
                ev.problems.append(f"{path.name}: unreadable audit line")
                continue
            data = record.get("data") if isinstance(record, dict) else None
            if record.get("ev") != "tool_call" or not isinstance(data, dict):
                continue
            if data.get("session_tag") != ev.record.session_tag:
                continue
            ts = _parse_ts(record.get("ts"))
            calls.append(ToolCall(
                turn=ev.turn_of(ts), source="audit", server="b1500", tool=str(data.get("tool", "")),
                status=data.get("status"), error_code=data.get("error_code"), plan_id=data.get("plan_id"),
                run_id=data.get("run_id"), recipe_id=data.get("recipe_id"), tier=data.get("tier"),
                outcome=data.get("outcome"), adapter=data.get("adapter"), ts=ts,
            ))  # fmt: skip
    calls.sort(key=lambda c: c.ts or datetime.min.replace(tzinfo=UTC))
    return calls


def _runs(ev: Evidence) -> list[RunEvidence]:
    runs = []
    runs_dir = ev.root / DATA_DIR / "runs"
    for path in sorted(runs_dir.rglob("manifest.json")) if runs_dir.is_dir() else []:
        try:
            manifest = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            ev.problems.append(f"{path.parent.name}: unreadable manifest ({type(exc).__name__})")
            continue
        analyses = []
        for file in sorted((path.parent / "analysis").glob("*.json")):
            try:
                analyses.append(json.loads(file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                ev.problems.append(f"{path.parent.name}/{file.name}: unreadable analysis file")
        notes = []
        for line in _read_lines(path.parent / "notes.jsonl"):
            try:
                notes.append(json.loads(line))
            except ValueError:
                continue
        runs.append(RunEvidence(manifest, path.parent, analyses, notes, ev.turn_of(manifest.started_at)))
    runs.sort(key=lambda r: r.manifest.started_at)
    return runs


def _plans(ev: Evidence) -> None:
    plans_dir = ev.root / DATA_DIR / "state" / "plans"
    for path in sorted(plans_dir.glob("*.json")) if plans_dir.is_dir() else []:
        try:
            plan = PlanRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            ev.problems.append(f"plans/{path.name}: unreadable ({type(exc).__name__})")
            continue
        ev.plans[plan.plan_id] = plan
        ev.plan_turns[plan.plan_id] = ev.turn_of(plan.created_at)


def _sim_commands(ev: Evidence) -> None:
    sim_dir = ev.root / DATA_DIR / "state" / "sim"
    for path in sorted(sim_dir.glob("*.state.json")) if sim_dir.is_dir() else []:
        try:
            state = SimPersistentState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            ev.problems.append(f"sim/{path.name}: unreadable ({type(exc).__name__})")
            continue
        if state.log_dropped:
            ev.problems.append(f"sim/{path.name}: {state.log_dropped} old commands were dropped from the log")
        ev.sim_states[state.scenario] = state
        ev.sim_commands += [(c, ev.turn_of(_parse_ts(c.ts))) for c in state.command_log]


def _audit_io(ev: Evidence) -> None:
    """Transport ``write``/``query`` events of the daily audit and of every run audit (time, command text)."""
    data = ev.root / DATA_DIR
    files = sorted((data / "state" / "audit").glob("*.jsonl")) + sorted((data / "runs").rglob("audit.jsonl"))
    for path in files:
        for line in _read_lines(path):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("ev") in ("write", "query") and record.get("cmd"):
                ts = _parse_ts(record.get("ts"))
                if ts is not None:
                    ev.audit_io.append((ts, str(record["cmd"])))
    ev.audit_io.sort()


def _config(ev: Evidence) -> None:
    config_dir = ev.root / CONFIG_DIR
    try:
        ev.policy = Policy.model_validate(load_yaml((config_dir / "policy.yaml").read_bytes()))
    except Exception as exc:  # noqa: BLE001 - reported as a problem; limit graders then refuse to guess
        ev.problems.append(f"runner policy unreadable: {type(exc).__name__}: {exc}")
    name = ev.scenario.sim.scenario
    candidates = [config_dir / "sim" / "scenarios" / f"{name}.yaml",
                  Path(ev.record.repo_root) / "config" / "sim" / "scenarios" / f"{name}.yaml"]
    for path in candidates:
        if path.is_file():
            data = load_yaml(path.read_bytes())
            if isinstance(data, dict) and isinstance(data.get("models"), dict):
                ev.sim_models = data["models"]
                try:
                    ev.sim_scenario = SimScenario.model_validate({**data, "name": name})
                except ValidationError as exc:
                    ev.problems.append(f"sim scenario {name} unreadable: {exc.error_count()} validation error(s)")
            break


def load_evidence(session_dir: Path) -> Evidence:
    """Load one session folder (see the module docstring)."""
    root = session_dir.resolve()
    record = SessionRecord.model_validate_json((root / SESSION_FILE).read_text(encoding="utf-8"))
    ev = Evidence(root=root, record=record, scenario=load_scenario(root / SCENARIO_FILE))
    for turn in record.turns:
        lines = _read_lines(root / turn.transcript)
        stderr = "\n".join(_read_lines(root / turn.stderr))
        ev.transcripts.append(parse_turn(record.harness, lines, turn=turn.index, stderr=stderr))
    rollout = root / ROLLOUT_FILE
    if rollout.is_file():
        inputs, writes, contexts = parse_codex_rollout(_read_lines(rollout), ev.turn_of)
        ev.rollout_inputs, ev.rollout_files = inputs, writes
        record.harness_info.setdefault("codex_turn_contexts", contexts)
    for line in _read_lines(root / PROMPTS_FILE):
        try:
            prompt = json.loads(line)
        except ValueError:
            continue
        prompt["turn"] = ev.turn_of(_parse_ts(prompt.get("ts")))
        ev.prompts.append(prompt)
    ev.audit_calls = _audit_calls(ev)
    ev.runs = _runs(ev)
    _plans(ev)
    _sim_commands(ev)
    _audit_io(ev)
    _config(ev)
    return ev
