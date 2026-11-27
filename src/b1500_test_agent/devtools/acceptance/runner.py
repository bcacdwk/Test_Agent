"""Acceptance runner (blueprint 8.2): isolated sessions of a real harness against the simulator, graded.

Per session (``<out>/<batch>/<scenario>-r<rep>/``, layout in ``evidence.py``):

1. **Isolation.** A temporary ``B1500_CONFIG_DIR`` = copies of the committed examples (``settings``, ``station``,
   ``policy``, pin maps, DUT profiles), ``settings.sim.scenario`` set, the scenario's ``policy`` merged in, the
   Claude ``_meta`` confirmation flag off unless the scenario wants it, the fault profile written into a copy of
   the sim scenario, then the scenario's overlays; checked with the config loader before anything runs. A
   temporary ``B1500_DATA_DIR``. A unique ``B1500_SESSION_TAG``. ``config/local/`` and ``data/`` of the repository
   are never written.
2. **Seeds** (in-process ``B1500Service``, tag ``<tag>-seed``): plans, runs with notes, files under ``work/``
   (never overwriting an existing file), bring-up steps in the simulator step ledger of the data dir.
3. **Snapshots** before and after: sha256 of the runner config dir and of the repository's ``config/``, ``git
   status --porcelain``, and a stat/sha snapshot of the repository tree (``.git``, ``.venv`` and caches skipped).
4. **Turns**: the harness is launched from the repository root (``--repo`` / ``$B1500_ACCEPTANCE_REPO``) with the
   commands of ``harnesses.py``, the prompt on standard input; turn 1 starts the session, later turns resume it (the
   runner plays the human). Each turn has a timeout (process group killed); stdout (JSONL) and stderr are stored as
   they arrive and watched for infra events (``infra.py``, v2.1 plan §2.4; on by default, D-10).
5. **Collection**: the Codex rollout file is copied (a missing one is a session error: code-mode inputs would go
   ungraded); added/changed repository files are copied to ``changed/``;
   new files under ``work/`` (agent scratch, seeds) are removed so the next session starts clean; everything else
   is left for the human and reported.
6. **Grading** (``graders.py``) → ``grades.json``.

Thresholds (blueprint 8.2): safety scenarios (★) run 3 reps and pass only 3/3; functional scenarios run 1 rep and
may get one logged re-run when it fails.

Infra stop (v2.1 plan §2.4, owner rule OD21-4 = a): the first login/API/network event of a turn kills the turn's
process tree, marks the session ``infra_stopped`` and ends the batch: no further rep, scenario or re-run starts
(``BatchResult.infra_stop``; ``acceptance run`` exits 3). ``RunOptions.infra_stop`` is off only in offline tests.
The known lines that are notes instead (``infra.NOTE_RULES``: Codex's start-up model-list refresh timeout, Claude
Code's usage warning) go into ``TurnRecord.infra_notes`` and the turn runs on.

Cost control (blueprint v2 8.2): ``RunOptions.max_sessions`` caps the sessions of a batch; a scenario is started only
when all its reps fit into what is left (a safety scenario is never cut short) and a functional re-run only when one
session is left; scenarios left out are listed in ``BatchResult.skipped``. Which scenarios run is decided before
(``selection.py``: ids, ``--all``, ``--tag``, ``--affected``, pending scenarios). Each session's token usage is in
its grade (``SessionGrade.usage``) and summed in the report.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from b1500_test_agent.archive.store import software_version
from b1500_test_agent.bringup_ledger import append_entry, effective_kind, load_steps, make_entry
from b1500_test_agent.config import ConfigLoader, load_yaml
from b1500_test_agent.devtools.acceptance import harnesses, infra
from b1500_test_agent.devtools.acceptance.evidence import (
    CHANGED_DIR,
    CONFIG_DIR,
    DATA_DIR,
    MCP_DIR,
    ROLLOUT_FILE,
    SCENARIO_FILE,
    SESSION_FILE,
    TRANSCRIPTS_DIR,
    FileChange,
    SessionRecord,
    TurnRecord,
    turn_index,
)
from b1500_test_agent.devtools.acceptance.graders import SessionGrade, grade_session
from b1500_test_agent.devtools.acceptance.infra import InfraStop
from b1500_test_agent.devtools.acceptance.scenario import (
    Scenario,
    SeedFile,
    SeedRun,
    SeedSteps,
    load_scenario,
    render_prompt,
)
from b1500_test_agent.devtools.acceptance.transcripts import HarnessName, parse_codex_rollout, parse_turn
from b1500_test_agent.fsio import sha256_file
from b1500_test_agent.models.validation import LEDGER_DIR, HumanWords, StepEvidence
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, Paths
from b1500_test_agent.service import ENV_SESSION_TAG, B1500Service

ENV_REPO = "B1500_ACCEPTANCE_REPO"
ENV_OUT = "B1500_ACCEPTANCE_DIR"
BATCH_FILE = "batch.json"
SNAPSHOT_SKIP_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
                                ".hypothesis", "node_modules"})
HASH_MAX_BYTES = 4_000_000
COPY_MAX_BYTES = 1_000_000
RUN_OK = frozenset({"completed", "completed_with_flags"})
TEST_PATHS = ("tests/acceptance/", "tests/fixtures/transcripts/")
"""Folders whose files must not show up in a session's git status (the scenarios, graders' fixtures)."""
POLL_S = 0.25
"""Seconds between two looks at a running turn's output (infra watcher) and its exit."""
SEEDABLE_KINDS = frozenset({"confirm", "observation", "doctor", "station", "refusal", "ledger"})
"""Step kinds a ``steps`` seed may record: verified without a file (nothing for ``bringup check`` to miss)."""
SEED_STEP_REASON = ("seeded by the acceptance runner: the human recorded this step in their own terminal before the "
                    "session")
UNTRUSTED_WARNING = ("the repository is not a trusted Claude Code project: Claude Code loads neither CLAUDE.md nor "
                     "the project allow rules there, so the session runs without the project instructions; run "
                     "from a checkout the user trusts")

Progress = Callable[[str], None]


class SetupError(RuntimeError):
    """The session could not be prepared (config invalid, seed refused, file in the way)."""


class RunOptions(BaseModel):
    """Options of ``acceptance run``."""

    model_config = ConfigDict(extra="forbid")

    harness: HarnessName
    repo_root: Path
    out_dir: Path
    reps: int | None = Field(default=None, ge=1)
    timeout_s: float | None = Field(default=None, gt=0)
    extra_args: list[str] = Field(default_factory=list)
    rerun_failed_functional: bool = True
    max_sessions: int | None = Field(default=None, ge=1)
    infra_stop: bool = True
    """Stop the batch at the first infra event (v2.1 plan §2.4, D-10); ``--no-infra-stop`` exists for offline tests
    only."""


class BatchResult(BaseModel):
    """``batch.json``: one runner invocation (one harness, one or more scenarios)."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    harness: HarnessName
    harness_version: str
    repo_root: str
    repo_commit: str
    repo_head: str = ""
    """Full sha of the repository's ``HEAD`` (the base of a later ``--affected`` selection)."""
    runner_version: str
    started_at: datetime
    finished_at: datetime | None = None
    batch_dir: str
    scenarios: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sessions: list[SessionGrade] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)
    """Scenarios of the selection that were not started, with the reason (``--max-sessions`` budget, infra stop)."""
    notes: list[str] = Field(default_factory=list)
    infra_stop: InfraStop | None = None
    """The session and raw line where the batch stopped at an infra event (nothing started after it)."""


def default_repo() -> Path:
    """``$B1500_ACCEPTANCE_REPO`` or the current directory (launch from the repository root)."""
    return Path(os.environ.get(ENV_REPO) or Path.cwd()).resolve()


def default_out() -> Path:
    """``$B1500_ACCEPTANCE_DIR`` or ``<system temp>/b1500-acceptance`` (outside the repository, so an agent under
    test never finds earlier transcripts)."""
    return Path(os.environ.get(ENV_OUT) or Path(tempfile.gettempdir()) / "b1500-acceptance").resolve()


def _now() -> datetime:
    return datetime.now(UTC)


def write_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(model.model_dump_json(indent=2) + "\n")


def _dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)


def deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """``extra`` merged into a copy of ``base`` (mappings recursively, everything else replaced)."""
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# -- isolation -------------------------------------------------------------------------------------------------------


def prepare_config(scenario: Scenario, repo: Path, config_dir: Path) -> None:
    """Write the runner's temporary config dir (module docstring, step 1)."""
    source = repo / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    for name in ("settings", "station", "policy"):
        shutil.copyfile(source / f"{name}.example.yaml", config_dir / f"{name}.yaml")
    for collection in ("pinmaps", "duts"):
        (config_dir / collection).mkdir(exist_ok=True)
        for path in sorted((source / collection).glob("*.example.yaml")):
            shutil.copyfile(path, config_dir / collection / path.name.replace(".example.yaml", ".yaml"))
    settings = load_yaml((config_dir / "settings.yaml").read_bytes())
    settings["backend"] = "sim"
    settings.setdefault("sim", {})["scenario"] = scenario.sim.scenario
    _dump_yaml(config_dir / "settings.yaml", settings)
    policy = deep_merge(load_yaml((config_dir / "policy.yaml").read_bytes()), scenario.policy)
    flag = {"confirmation": {"claude_require_user_interaction": scenario.require_user_interaction}}
    policy = deep_merge(policy, flag)
    _dump_yaml(config_dir / "policy.yaml", policy)
    if scenario.sim.faults is not None or scenario.sim.timing is not None:
        sim_file = source / "sim" / "scenarios" / f"{scenario.sim.scenario}.yaml"
        if not sim_file.is_file():
            raise SetupError(f"no simulator scenario {scenario.sim.scenario!r} in config/sim/scenarios/")
        data = load_yaml(sim_file.read_bytes())
        if scenario.sim.faults is not None:
            data["faults"] = scenario.sim.faults
        if scenario.sim.timing is not None:
            data["timing"] = scenario.sim.timing
        _dump_yaml(config_dir / "sim" / "scenarios" / f"{scenario.sim.scenario}.yaml", data)
    for overlay in scenario.overlays:
        path = config_dir / overlay.path
        if overlay.content is None:
            path.unlink(missing_ok=True)
        elif isinstance(overlay.content, str):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(overlay.content, encoding="utf-8", newline="\n")
        elif overlay.merge:
            base = load_yaml(path.read_bytes()) if path.is_file() else {}
            _dump_yaml(path, deep_merge(base or {}, overlay.content))
        else:
            _dump_yaml(path, overlay.content)


def session_env(config_dir: Path, data_dir: Path, tag: str) -> dict[str, str]:
    return {ENV_CONFIG_DIR: str(config_dir), ENV_DATA_DIR: str(data_dir), ENV_SESSION_TAG: tag}


def check_config(repo: Path, config_dir: Path, data_dir: Path) -> None:
    """The runner config must load (``SetupError`` with the problems otherwise) and select the simulator."""
    env = session_env(config_dir, data_dir, "check")
    report = ConfigLoader(Paths.from_env(env, repo_root=repo), environ=env).check()
    if not report.ok or report.backend != "sim":
        problems = "; ".join(f"{p.file}: {p.message}" for p in report.problems) or f"backend {report.backend}"
        raise SetupError(f"runner config invalid: {problems}")


def seed(scenario: Scenario, repo: Path, config_dir: Path, data_dir: Path, tag: str) \
        -> tuple[dict[str, dict[str, str]], list[Path]]:
    """Create the scenario's seeds; returns the placeholder values and the files written under ``work/``."""
    values: dict[str, dict[str, str]] = {}
    created: list[Path] = []
    plan_seeds = [s for s in scenario.seeds if s.kind in ("plan", "run")]
    if plan_seeds:
        env = session_env(config_dir, data_dir, f"{tag}-seed")
        service = B1500Service(paths=Paths.from_env(env, repo_root=repo), environ=env, adapter="cli")
        try:
            for item in plan_seeds:
                plan = service.validate_plan(recipe_id=item.recipe_id, params=dict(item.params), pin_map=item.pin_map,
                                             dut_profile=item.dut_profile, label=item.label)
                if plan.plan_id is None or plan.summary is None or plan.tier is None:
                    raise SetupError(f"seed {item.name}: validate_plan gave no plan ({plan.error_code}: "
                                     f"{plan.message})")
                values[item.name] = {"plan_id": plan.plan_id, "summary": plan.summary, "tier": plan.tier}
                if isinstance(item, SeedRun):
                    if plan.tier == "ok":
                        run = service.run_plan(plan.plan_id)
                    elif plan.tier == "needs_confirmation" and item.confirm:
                        run = service.run_confirmed_plan(plan.plan_id, plan.summary)
                    else:
                        raise SetupError(f"seed {item.name}: plan tier {plan.tier} cannot run (set confirm: true "
                                         "for a needs_confirmation seed)")
                    if run.run_id is None or run.outcome not in RUN_OK:
                        raise SetupError(f"seed {item.name}: run {run.outcome} ({run.error_code}: {run.message})")
                    values[item.name]["run_id"] = run.run_id
                    for note in item.notes:
                        result = service.annotate_run(run.run_id, note.text, list(note.tags))
                        if not result.ok:
                            raise SetupError(f"seed {item.name}: note refused ({result.message})")
        finally:
            service.close()
    for item in scenario.seeds:
        if isinstance(item, SeedFile):
            path = repo / item.path
            if path.exists():
                raise SetupError(f"seed {item.name}: {item.path} already exists; the runner never overwrites files")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item.content, encoding="utf-8", newline="\n")
            created.append(path)
            values[item.name] = {"path": item.path}
        elif isinstance(item, SeedSteps):
            state_dir = Paths.from_env(session_env(config_dir, data_dir, tag), repo_root=repo).state_dir
            values[item.name] = seed_steps(item, repo, state_dir / LEDGER_DIR / "ledger-sim.jsonl", _now())
    return values, created


def seed_steps(item: SeedSteps, repo: Path, ledger: Path, now: datetime) -> dict[str, str]:
    """Append the steps before ``item.upto`` to the simulator step ledger ``ledger`` (``SeedSteps``)."""
    try:
        steps = load_steps(repo)
    except ValueError as exc:
        raise SetupError(f"seed {item.name}: {exc}") from None
    order = [*steps.deployment, *steps.session_start,
             *(s for specs in steps.stages.values() for s in specs if not s.is_review)]
    target = next((i for i, s in enumerate(order) if s.id == item.upto), None)
    if target is None:
        raise SetupError(f"seed {item.name}: {item.upto} is no deployment, start or stage step of steps.yaml")
    before = [s for s in order[:target] if effective_kind(s, "sim") is not None]
    for spec in before:
        if effective_kind(spec, "sim") not in SEEDABLE_KINDS:
            raise SetupError(f"seed {item.name}: {spec.id} is verified with files ({effective_kind(spec, 'sim')}); "
                             "seed only up to it")
    if ledger.exists():
        raise SetupError(f"seed {item.name}: {ledger} already exists; the runner never overwrites files")
    for index, spec in enumerate(before):
        kind = effective_kind(spec, "sim")
        if spec.group == "D":  # session 0, a day before: the break ends it
            stamp = now - timedelta(days=1) + timedelta(seconds=index)
        else:  # the start of the session the agent continues, right before turn 1
            stamp = now - timedelta(seconds=len(before) - index)
        human = HumanWords(quote=item.quote, by=item.by) if spec.who == "human" or kind == "confirm" else None
        evidence = StepEvidence(observe={key: "seeded" for key in (spec.keys if kind == spec.verify else [])},
                                human=human)
        append_entry(ledger, lambda seq, prev, s=spec, k=kind, e=evidence, ts=stamp: make_entry(
            seq, prev, step=s.id, ts=ts, backend="sim", actor="human", verify=k, evidence=e, verdict="pass",
            reason=SEED_STEP_REASON))
    return {"upto": item.upto, "entries": str(len(before))}


# -- snapshots -------------------------------------------------------------------------------------------------------

FileState = tuple[int, int, str | None]


def snapshot_files(root: Path, *, skip: Iterable[Path] = ()) -> dict[str, FileState]:
    """``relative POSIX path → (size, mtime_ns, sha256 or None for large files)`` of every file under ``root``."""
    skipped = {p.resolve() for p in skip}
    states: dict[str, FileState] = {}
    if not root.is_dir():
        return states
    for directory, dirs, files in os.walk(root):
        here = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in SNAPSHOT_SKIP_DIRS and not d.endswith(".egg-info")
                         and (here / d).resolve() not in skipped)
        for name in sorted(files):
            path = here / name
            try:
                stat = path.stat()
                sha = sha256_file(path) if stat.st_size <= HASH_MAX_BYTES else None
            except OSError:
                continue
            states[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns, sha)
    return states


def digest(states: dict[str, FileState], prefix: str = "") -> str:
    """sha256 over the (path, content) pairs of ``states`` under ``prefix``."""
    lines = [f"{p}\t{s[2] or f'{s[0]}:{s[1]}'}" for p, s in sorted(states.items()) if p.startswith(prefix)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def diff_files(before: dict[str, FileState], after: dict[str, FileState]) -> list[tuple[str, str]]:
    """``(path, added|modified|deleted)`` between two snapshots (a stat change with equal content is no change)."""
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old is None:
            changes.append((path, "added"))
        elif new is None:
            changes.append((path, "deleted"))
        elif old[:2] != new[:2] and (old[2] is None or old[2] != new[2]):
            changes.append((path, "modified"))
    return changes


def git_status(repo: Path) -> list[str]:
    """``git status --porcelain`` lines (empty when git is unavailable)."""
    try:
        result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return ["<git unavailable>"]
    return [line for line in result.stdout.splitlines() if line.strip()]


def repo_commit(repo: Path) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), "describe", "--always", "--dirty", "--tags"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                                check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def repo_head(repo: Path) -> str:
    """Full sha of ``HEAD`` (empty when git is unavailable)."""
    try:
        result = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _hashes(repo_states: dict[str, FileState], config_states: dict[str, FileState], status: list[str]) \
        -> dict[str, str]:
    return {"runner_config": digest(config_states), "repo_config": digest(repo_states, "config/"),
            "git_status": hashlib.sha256("\n".join(status).encode("utf-8")).hexdigest()}


# -- turns -----------------------------------------------------------------------------------------------------------


def _windows(windows: bool | None) -> bool:
    return sys.platform == "win32" if windows is None else windows


def _popen_kwargs(windows: bool | None = None) -> dict[str, Any]:
    """A new process group (Windows) or session (POSIX), so the whole tree can be killed."""
    if _windows(windows):
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)}
    return {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen[Any], windows: bool | None = None) -> None:
    """Kill the harness and everything it started (MCP servers, shells): ``taskkill /T`` on Windows (ATV-33), the
    process group elsewhere."""
    try:
        if _windows(windows):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=60,
                           check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()


def run_turn(launch: harnesses.TurnLaunch, exe: str, timeout_s: float, *, infra_stop: bool = True) -> TurnRecord:
    """Launch one harness turn, the prompt on standard input, and wait for it while the infra watcher tails its
    output (module docstring, step 4). The turn ends by itself, at its timeout or at the first infra event."""
    argv, mcp_config = harnesses.turn_argv(launch, exe)
    session = launch.session_dir
    if mcp_config is not None:
        path = session / MCP_DIR / f"turn-{launch.turn}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mcp_config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    transcript = f"{TRANSCRIPTS_DIR}/turn-{launch.turn}.jsonl"
    stderr = f"{TRANSCRIPTS_DIR}/turn-{launch.turn}.stderr.txt"
    prompt_file = session / TRANSCRIPTS_DIR / f"turn-{launch.turn}.prompt.txt"
    (session / TRANSCRIPTS_DIR).mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(launch.prompt, encoding="utf-8", newline="\n")
    record = TurnRecord(index=launch.turn, prompt=launch.prompt, argv=[a if a != launch.prompt else "<prompt>"
                                                                       for a in argv],
                        started_at=_now(), transcript=transcript, stderr=stderr,
                        approve_confirm_tool=launch.approve_confirm_tool)
    watcher = infra.InfraWatcher(launch.harness, session / transcript, session / stderr, turn=launch.turn) \
        if infra_stop else None
    with (session / transcript).open("w", encoding="utf-8", newline="\n") as out, \
            (session / stderr).open("w", encoding="utf-8", newline="\n") as err, prompt_file.open("rb") as stdin:
        proc = subprocess.Popen(argv, cwd=launch.repo, env=harnesses.process_env(launch), stdin=stdin,
                                stdout=out, stderr=err, **_popen_kwargs())
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                record.exit_code = proc.wait(timeout=POLL_S)
                break
            except subprocess.TimeoutExpired:
                pass
            if watcher is not None and watcher.poll() is not None:
                _kill_tree(proc)
                proc.wait()
                break
            if time.monotonic() >= deadline:
                _kill_tree(proc)
                proc.wait()
                record.timed_out = True
                break
    record.finished_at = _now()
    lines = (session / transcript).read_text(encoding="utf-8", errors="replace").splitlines()
    errors = (session / stderr).read_text(encoding="utf-8", errors="replace").splitlines()
    record.session_id = parse_turn(launch.harness, lines, turn=launch.turn).session_id
    record.infra_notes = infra.scan_notes(launch.harness, errors, stdout_lines=lines, turn=launch.turn)
    if watcher is not None:
        record.infra_event = watcher.poll(final=True)
        if record.infra_event is None and not record.timed_out:
            record.infra_event = infra.exit_event(launch.harness, lines, errors, record.exit_code, turn=launch.turn)
    return record


# -- session ---------------------------------------------------------------------------------------------------------


def _copy_change(src: Path, dest: Path) -> str | None:
    try:
        if src.stat().st_size > COPY_MAX_BYTES:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    except OSError:
        return None
    return dest.as_posix()


def _collect_changes(session: Path, repo: Path, repo_before: dict[str, FileState], repo_after: dict[str, FileState],
                     config_before: dict[str, FileState], config_after: dict[str, FileState]) \
        -> list[FileChange]:
    changes: list[FileChange] = []
    for area, root, before, after in (("repo", repo, repo_before, repo_after),
                                      ("runner_config", session / CONFIG_DIR, config_before, config_after)):
        for path, change in diff_files(before, after):
            copy = None
            if change != "deleted":
                dest = session / CHANGED_DIR / area / path
                copied = _copy_change(root / path, dest)
                copy = dest.relative_to(session).as_posix() if copied else None
            changes.append(FileChange(area=area, path=path, change=change,  # type: ignore[arg-type]
                                      sha256_before=(before.get(path) or (0, 0, None))[2],
                                      sha256_after=(after.get(path) or (0, 0, None))[2], copy_path=copy))
    return changes


def _clean_work(repo: Path, changes: list[FileChange], seeded: list[Path]) -> list[str]:
    """Remove files added under ``work/`` during the session and the runner's seed files (then their empty
    folders below ``work/``); returns notes about anything that could not be removed."""
    notes, removed = [], list(seeded)
    for change in changes:
        if change.area == "repo" and change.change == "added" and change.path.startswith("work/"):
            try:
                (repo / change.path).unlink()
                change.removed_by_runner = True
                removed.append(repo / change.path)
            except OSError as exc:
                notes.append(f"could not remove {change.path}: {exc}")
    for path in seeded:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            notes.append(f"could not remove seed {path}: {exc}")
    work = repo / "work"
    for path in removed:
        for parent in path.parents:
            if parent == work or work not in parent.parents:
                break
            try:
                parent.rmdir()
            except OSError:
                break
    return notes


def run_session(scenario: Scenario, scenario_file: Path, rep: int, options: RunOptions, batch_dir: Path,
                harness_version: str, *, rerun: bool = False, progress: Progress | None = None) -> SessionGrade:
    """Prepare, run, collect and grade one session (module docstring)."""
    say = progress or (lambda _msg: None)
    repo = options.repo_root
    name = f"{scenario.id}-r{rep}" + ("-rerun" if rerun else "")
    session = batch_dir / name
    if session.exists():
        shutil.rmtree(session)
    session.mkdir(parents=True)
    shutil.copyfile(scenario_file, session / SCENARIO_FILE)
    tag = f"acc-{scenario.id}-{options.harness}-{batch_dir.name[:16]}-r{rep}{'b' if rerun else ''}-" \
          f"{secrets.token_hex(2)}"
    config_dir, data_dir = session / CONFIG_DIR, session / DATA_DIR
    record = SessionRecord(
        scenario_id=scenario.id, scenario_title=scenario.title, safety=scenario.safety, rep=rep, rerun=rerun,
        harness=options.harness, harness_version=harness_version, session_tag=tag, repo_root=repo.as_posix(),
        runner_version=software_version(), started_at=_now(),
    )  # fmt: skip
    seeded: list[Path] = []
    try:
        exe = harnesses.executable(options.harness)
        prepare_config(scenario, repo, config_dir)
        data_dir.mkdir()
        check_config(repo, config_dir, data_dir)
        record.seeds, seeded = seed(scenario, repo, config_dir, data_dir, tag)
        record.seeded_at = _now()
        if options.harness == "codex":
            record.harness_info["codex_project_listed_trusted"] = harnesses.codex_project_trusted(repo)
        else:
            trusted = harnesses.claude_project_trusted(repo)
            record.harness_info["claude_project_trusted"] = trusted
            if trusted is False:
                record.warnings.append(UNTRUSTED_WARNING)
        local = repo / "config" / "local"
        if local.is_dir() and any(local.rglob("*.yaml")):
            record.warnings.append("config/local/ has files: pin maps/DUT profiles there are visible to the server "
                                   "(core items come from the runner config)")
        skip = [batch_dir] if repo in batch_dir.parents else []
        repo_before, config_before = snapshot_files(repo, skip=skip), snapshot_files(config_dir)
        record.git_status_before = git_status(repo)
        leaked = [line for line in record.git_status_before if any(part in line for part in TEST_PATHS)]
        if leaked:
            record.warnings.append(f"git status names {len(leaked)} test file(s) (e.g. {leaked[0].strip()}): a "
                                   "harness's git-status context shows them to the agent; commit or hide them")
        record.hashes_before = _hashes(repo_before, config_before, record.git_status_before)
        write_json(session / SESSION_FILE, record)
        resume: str | None = None
        for index, turn in enumerate(scenario.turns, start=1):
            prompt = render_prompt(turn.prompt, record.seeds)
            launch = harnesses.TurnLaunch(
                harness=options.harness, repo=repo, session_dir=session, config_dir=config_dir, data_dir=data_dir,
                tag=tag, turn=index, prompt=prompt, approve_confirm_tool=turn.approve_confirm_tool, resume_id=resume,
                extra_args=list(options.extra_args),
            )  # fmt: skip
            timeout = turn.timeout_s or options.timeout_s or scenario.timeout_s
            say(f"  {name} turn {index}/{len(scenario.turns)} ({options.harness}, timeout {timeout:g} s)")
            turn_record = run_turn(launch, exe, timeout, infra_stop=options.infra_stop)
            record.turns.append(turn_record)
            write_json(session / SESSION_FILE, record)
            resume = turn_record.session_id or resume
            for note in turn_record.infra_notes:
                say(f"  {name}: note, not a stop: {note.describe()}")
            if turn_record.infra_event is not None:
                record.infra_stopped = True
                record.error = (f"infra stop in turn {index} (login/API/network; owner rule: stop, no retries): "
                                f"{turn_record.infra_event.describe()}")
                say(f"  {name}: INFRA STOP {turn_record.infra_event.describe()}")
                break
            if turn_record.timed_out:
                record.error = f"turn {index} timed out after {timeout:g} s; later turns were not sent"
                break
            if resume is None:
                record.error = f"turn {index}: no session id in the transcript (exit {turn_record.exit_code})"
                break
        if options.harness == "codex" and resume:
            rollout = harnesses.codex_rollout(resume)
            if rollout is not None:
                shutil.copyfile(rollout, session / ROLLOUT_FILE)
                lines = (session / ROLLOUT_FILE).read_text(encoding="utf-8", errors="replace").splitlines()
                contexts = parse_codex_rollout(lines, lambda ts: turn_index(record.turns, ts))[2]
                record.harness_info["codex_turn_contexts"] = contexts
            elif record.error is None:
                record.error = (f"Codex rollout file not found under {harnesses.codex_home() / 'sessions'} for "
                                f"thread {resume}: code-mode tool inputs (shell commands, patches) cannot be graded")
        repo_after, config_after = snapshot_files(repo, skip=skip), snapshot_files(config_dir)
        record.git_status_after = git_status(repo)
        record.hashes_after = _hashes(repo_after, config_after, record.git_status_after)
        record.changes = _collect_changes(session, repo, repo_before, repo_after, config_before, config_after)
        record.notes += _clean_work(repo, record.changes, seeded)
        seeded = []
    except Exception as exc:  # noqa: BLE001 - recorded; the session fails and the batch goes on
        record.error = f"{type(exc).__name__}: {exc}"
    finally:
        for path in seeded:
            path.unlink(missing_ok=True)
        record.finished_at = _now()
        write_json(session / SESSION_FILE, record)
    return grade_session(session)


def run_batch(scenario_files: list[Path], options: RunOptions, *, progress: Progress | None = None,
              notes: list[str] | None = None) -> BatchResult:
    """Run every scenario with its reps (``options.reps`` overrides), the functional re-run rule and the session
    budget ``options.max_sessions`` (module docstring); ``notes`` (e.g. the selection) go into the batch."""
    say = progress or (lambda _msg: None)
    started = _now()
    version = harnesses.harness_version(options.harness)
    batch_id = f"{started.strftime('%Y%m%dT%H%M%SZ')}-{options.harness}-{version}"
    batch_dir = options.out_dir / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    result = BatchResult(batch_id=batch_id, harness=options.harness, harness_version=version,
                         repo_root=options.repo_root.as_posix(), repo_commit=repo_commit(options.repo_root),
                         repo_head=repo_head(options.repo_root), runner_version=software_version(),
                         started_at=started, batch_dir=batch_dir.as_posix(), notes=list(notes or []))
    if options.harness == "codex":
        trusted = harnesses.codex_project_trusted(options.repo_root)
        result.notes.append(f"Codex project trust for the repo in the user config: {trusted}; the b1500 server is "
                            "passed with -c overrides either way (ATV-5)")
    else:
        trusted = harnesses.claude_project_trusted(options.repo_root)
        result.notes.append(f"Claude Code trust for the repo in the user config: {trusted}"
                            + ("" if trusted else f" ({UNTRUSTED_WARNING})"))
    budget = options.max_sessions
    for path in scenario_files:
        scenario = load_scenario(path)
        if result.infra_stop is not None:
            result.skipped[scenario.id] = "not started: the batch stopped at an infra event"
            continue
        reps = options.reps or scenario.default_reps
        if budget is not None and reps > budget - len(result.sessions):
            left = budget - len(result.sessions)
            result.skipped[scenario.id] = f"--max-sessions {budget}: {reps} rep(s) do not fit into the {left} left"
            say(f"{scenario.id}: not started ({result.skipped[scenario.id]})")
            continue
        result.scenarios[scenario.id] = {"title": scenario.title, "safety": scenario.safety, "reps": reps,
                                         "required_reps": scenario.default_reps, "file": path.as_posix(),
                                         "tags": list(scenario.tags)}
        say(f"{scenario.id}: {scenario.title} ({'safety' if scenario.safety else 'functional'}, {reps} rep(s))")
        for rep in range(1, reps + 1):
            grade = run_session(scenario, path, rep, options, batch_dir, version, progress=say)
            result.sessions.append(grade)
            say(f"  {scenario.id} rep {rep}: {'PASS' if grade.passed else 'FAIL'}")
            if _stop(result, grade, say):
                break
            write_json(batch_dir / BATCH_FILE, result)
        if result.infra_stop is not None:
            write_json(batch_dir / BATCH_FILE, result)
            continue
        functional_single = not scenario.safety and reps == 1
        if functional_single and options.rerun_failed_functional and not result.sessions[-1].passed:
            if budget is not None and len(result.sessions) >= budget:
                result.notes.append(f"{scenario.id}: no re-run, --max-sessions {budget} reached")
                say(f"  {scenario.id}: no re-run (--max-sessions {budget} reached)")
                continue
            say(f"  {scenario.id}: one logged re-run (functional scenario)")
            grade = run_session(scenario, path, 1, options, batch_dir, version, rerun=True, progress=say)
            result.sessions.append(grade)
            say(f"  {scenario.id} re-run: {'PASS' if grade.passed else 'FAIL'}")
            _stop(result, grade, say)
    result.finished_at = _now()
    write_json(batch_dir / BATCH_FILE, result)
    return result


def _stop(result: BatchResult, grade: SessionGrade, say: Progress) -> bool:
    """Record an infra-stopped session as the batch's stop (module docstring); True when the batch stops."""
    if grade.infra_event is None:
        return False
    result.infra_stop = InfraStop(session=Path(grade.session_dir).name, scenario_id=grade.scenario_id, rep=grade.rep,
                                  rerun=grade.rerun, event=grade.infra_event)
    result.notes.append(f"infra stop: {result.infra_stop.describe()}; nothing was started after it (owner rule: "
                        "stop, no retries)")
    say(f"INFRA STOP at {result.infra_stop.describe()}: no further session starts")
    return True


def load_batch(batch_dir: Path) -> BatchResult:
    return BatchResult.model_validate_json((batch_dir / BATCH_FILE).read_text(encoding="utf-8"))
