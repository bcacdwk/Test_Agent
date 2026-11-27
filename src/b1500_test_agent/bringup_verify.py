"""Verifiers of ``b1500 bringup done`` and re-verification of ``b1500 bringup check`` (v2.1 plan §4.1), one per
``VerifyKind`` (``models/validation.py``) plus ``refusal`` (a rehearsed record or capture on the simulator).

Imports only ``service``, ``models`` and ``bringup_ledger`` (layering test). A verifier returns ``(verdict, reason)``
and fills ``Ctx.ev`` with the evidence it read; it raises ``Refused`` when there is nothing to verify (a missing
option, a run id that is not archived, a file that does not exist): then nothing is recorded. Evidence that exists
but does not hold is a ``fail``: a run of another backend (``S…`` on the hardware ledger), another recipe or outcome,
changed files, an unverified cleanup or a failed ``LOP?`` positive control on hardware, untrusted quality; a probe
with FAIL lines; a proposal or adopted file that does not validate or differs; a failing draft record; fixtures not
written by ``b1500 bringup capture``; a JUnit report with failures or gate skips; unreviewed records; a station with a
fault, a lock holder or a running run; doctor FAIL lines; a ledger gap.

``reverify`` checks a passing entry again against the current files for ``check``: runs (manifest digest and files),
probe records, draft records (moved to ``validation/hw/`` after review: a note), JUnit reports, fixture folders
(moved to ``tests/fixtures/hw/``: a note) and reviewed records; proposals and adopted configuration may change later
(notes).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

import yaml
from pydantic import BaseModel, ValidationError

from b1500_test_agent.bringup_ledger import load_record, load_stage
from b1500_test_agent.fsio import sha256_file
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.policy import DutProfile, Policy
from b1500_test_agent.models.station import PinMap, Settings, StationProfile
from b1500_test_agent.models.validation import (
    BRINGUP_WORK_DIR,
    DRAFTS_DIR,
    FIXTURES_DIR,
    VALIDATION_DIR,
    EvidenceItem,
    LedgerEntry,
    LedgerGap,
    StepsFile,
    StepSpec,
    reviewed_record_problems,
)
from b1500_test_agent.service import B1500Service
from b1500_test_agent.service import evidence as evidence_reader

DEFAULT_OUTCOMES = ("completed", "completed_with_flags")
RUN_ID = re.compile(r"^[SH]\d{8}T\d{6}Z-[0-9a-f]{4}$")
OBSERVE = re.compile(r"^(?P<key>[a-z][a-z0-9_]{0,63})=(?P<value>.+)$", re.DOTALL)
GATE_SKIP = "hardware test:"
"""Prefix of the skip reason of the hardware gate (``tests/hardware/support.py``): such a skip is not a pass."""
CONFIG_MODELS: dict[str, type[BaseModel]] = {"settings": Settings, "station": StationProfile, "policy": Policy,
                                             "pinmap": PinMap, "dut": DutProfile}
CONFIG_KEYS = {"pinmap": "pinmaps", "dut": "duts"}
NAME_SUFFIXES = (".example.yaml", ".yaml", ".yml")
DoctorLines = Sequence[tuple[str, str, str]]
"""``b1500 doctor`` lines (name, PASS/INFO/WARN/FAIL, detail); the CLI runs the doctor (``devtools``)."""


@dataclass(frozen=True)
class StepArgs:
    """The evidence options of ``b1500 bringup done``."""

    runs: tuple[str, ...] = ()
    probe: str | None = None
    drafts: tuple[str, ...] = ()
    fixtures: tuple[str, ...] = ()
    """One fixture folder of ``b1500 bringup capture`` per captured run or probe record."""
    observe: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    human: str | None = None
    by: str | None = None


class Refused(Exception):
    """Nothing to verify: the step is not recorded."""


@dataclass
class Ctx:
    """One verification: the step, its effective kind and the evidence gathered so far."""

    service: B1500Service
    bundle: Any
    steps: StepsFile
    spec: StepSpec
    kind: str
    args: StepArgs
    doctor: Callable[[], DoctorLines] | None = None
    gaps: Callable[[], list[LedgerGap]] | None = None
    ev: dict[str, Any] = field(default_factory=dict)

    @property
    def backend(self) -> Backend:
        return self.bundle.backend

    @property
    def repo(self) -> Path:
        return Path(self.bundle.paths.repo_root)

    def shown(self, path: Path) -> str:
        return self.bundle.paths.display(path)

    def add(self, key: str, item: Any) -> None:
        self.ev.setdefault(key, []).append(item)


Verdict = tuple[Literal["pass", "fail"], str]


def model_digest(model: BaseModel) -> str:
    """sha256 of a model's JSON (run manifests and probe reports as the ledger pins them)."""
    return hashlib.sha256(model.model_dump_json().encode("utf-8")).hexdigest()


def _resolve(ctx: Ctx, ref: str, *, under: Path | None, what: str) -> Path:
    """An existing file or folder named on the command line (relative to the repository root), inside ``under``."""
    path = Path(ref)
    path = (path if path.is_absolute() else ctx.repo / path).resolve()
    if under is not None:
        try:
            path.relative_to(under.resolve())
        except ValueError:
            raise Refused(f"{ref}: a {what} lies under {ctx.shown(under)}/") from None
    if not path.exists():
        raise Refused(f"{ref}: no such {what}")
    return path


def _bringup_dir(ctx: Ctx) -> Path:
    return Path(ctx.bundle.paths.work_dir) / BRINGUP_WORK_DIR


def _runs(ctx: Ctx, run_ids: Sequence[str]) -> list[Any]:
    """The run facts (refused when an id is malformed or the run is not archived)."""
    bad = [r for r in run_ids if not RUN_ID.match(r)]
    if bad:
        raise Refused(f"not run ids: {', '.join(bad)} (S or H, UTC stamp, 4 hex)")
    facts = []
    for run_id in run_ids:
        try:
            facts.append(evidence_reader.run_facts(ctx.bundle, run_id))
        except Exception as exc:  # noqa: BLE001 - any unreadable run is refused with the reader's reason
            raise Refused(f"run {run_id}: {exc}") from None
    return facts


def run_problems(facts: Any, spec: StepSpec, backend: Backend) -> list[str]:
    """Why an archived run is no evidence for ``spec`` on ``backend`` (empty: it is)."""
    manifest = facts.manifest
    run_id = manifest.run_id
    if manifest.backend != backend:
        wanted = "hardware runs (H...)" if backend == "visa" else "simulator runs (S...)"
        return [f"run {run_id} ran on backend {manifest.backend}: the {backend} ledger takes {wanted} only"]
    problems = []
    if manifest.recipe_id not in spec.recipes:
        problems.append(f"run {run_id} is a run of {manifest.recipe_id}; {spec.id} takes {', '.join(spec.recipes)}")
    outcomes = spec.outcomes or DEFAULT_OUTCOMES
    if manifest.outcome not in outcomes:
        problems.append(f"run {run_id} ended {manifest.outcome}; {spec.id} needs {' or '.join(outcomes)}")
    if facts.changed_files:
        problems.append(f"run {run_id}: files changed since the run ({', '.join(facts.changed_files)})")
    cleanup = manifest.cleanup
    if manifest.outcome != "running":
        expected = "lop" if backend == "visa" else "sim_state"
        if cleanup is None:
            problems.append(f"run {run_id}: no cleanup report")
        elif cleanup.verified != expected or cleanup.latched_fault:
            problems.append(f"run {run_id}: cleanup verified {cleanup.verified!r}, fault latched "
                            f"{cleanup.latched_fault} (needs {expected!r}, no fault)")
        elif backend == "visa":
            control = cleanup.positive_control
            if control is not None and not control.ok:
                problems.append(f"run {run_id}: the LOP? positive control failed ({control.detail or control.codes})")
            elif control is None and manifest.status_counts and manifest.outcome != "aborted":
                problems.append(f"run {run_id}: measured values without a LOP? positive control")
    if manifest.quality_verdict == "untrusted":
        problems.append(f"run {run_id}: quality untrusted (skill b1500-debug before it counts)")
    return problems


def verify_run(ctx: Ctx) -> Verdict:
    if not ctx.args.runs:
        raise Refused(f"give the runs: --run RUN_ID (repeatable; recipes {', '.join(ctx.spec.recipes)})")
    facts = _runs(ctx, ctx.args.runs)
    ctx.ev["runs"] = [EvidenceItem(ref=f.manifest.run_id, sha256=model_digest(f.manifest)) for f in facts]
    problems = [p for f in facts for p in run_problems(f, ctx.spec, ctx.backend)]
    found = {f.manifest.recipe_id for f in facts}
    missing = [r for r in ctx.spec.required_recipes if r not in found]
    if missing:
        problems.append(f"no run of {', '.join(missing)} among the runs given")
    if problems:
        return "fail", "; ".join(problems)
    return "pass", f"{len(facts)} run(s) verified: " + ", ".join(f"{f.manifest.run_id} {f.manifest.recipe_id} "
                                                                 f"{f.manifest.outcome}" for f in facts)


def verify_probe(ctx: Ctx) -> Verdict:
    if not ctx.args.probe:
        raise Refused("give the probe record: --probe latest (or a probe-<UTC>.json name)")
    try:
        facts = evidence_reader.probe_facts(ctx.bundle, ctx.args.probe)
    except Exception as exc:  # noqa: BLE001 - no probe record: refused with the reader's reason
        raise Refused(str(exc)) from None
    report = facts.report
    ctx.ev["probe"] = EvidenceItem(ref=facts.path, sha256=model_digest(report))
    failed = [c.name for c in report.checks if c.status == "FAIL"]
    if report.backend != ctx.backend:
        return "fail", f"{facts.path} is a probe on backend {report.backend}, not {ctx.backend}"
    if failed or not report.ok:
        return "fail", f"{facts.path}: FAIL lines {', '.join(failed) or '(probe not ok)'}"
    warned = [c.name for c in report.checks if c.status == "WARN"]
    return "pass", f"{facts.path}: no FAIL ({len(report.checks)} lines" + (
        f"; WARN {', '.join(warned)})" if warned else ")")


def _config_kind(ctx: Ctx, path: Path) -> tuple[str, str]:
    """``(kind, config key)`` of a configuration file among the step's ``config`` kinds (``Refused`` when it is not
    YAML, ``ValueError`` with the validation message when it is none of them)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise Refused(f"{ctx.shown(path)} is not readable YAML ({type(exc).__name__})") from None
    messages = [] if isinstance(data, dict) else ["the top level must be a mapping"]
    for kind in ctx.spec.config if isinstance(data, dict) else []:
        name = data.get("name") if isinstance(data.get("name"), str) and data.get("name") else next(
            (path.name[:-len(s)] for s in NAME_SUFFIXES if path.name.endswith(s)), path.stem)
        candidate = {**data, "name": name} if kind in CONFIG_KEYS else data
        try:
            CONFIG_MODELS[kind].model_validate(candidate)
        except ValidationError as exc:
            messages.append(f"not a {kind}: {exc.errors()[0]['msg']}")
            continue
        return kind, f"{CONFIG_KEYS[kind]}/{name}" if kind in CONFIG_KEYS else kind
    raise ValueError(f"{ctx.shown(path)}: " + "; ".join(messages))


def _normalized(text: str) -> str:
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def verify_proposal(ctx: Ctx) -> Verdict:
    if not ctx.args.drafts:
        raise Refused(f"give the proposal files: --draft work/bringup/<FILE>.yaml ({', '.join(ctx.spec.config)})")
    paths = [_resolve(ctx, ref, under=_bringup_dir(ctx), what="proposal file") for ref in ctx.args.drafts]
    problems, kinds = [], set()
    for path in paths:
        ctx.add("drafts", EvidenceItem(ref=ctx.shown(path), sha256=sha256_file(path)))
        try:
            kinds.add(_config_kind(ctx, path)[0])
        except ValueError as exc:
            problems.append(str(exc))
    missing = [k for k in ctx.spec.config if k not in kinds]
    if missing:
        problems.append(f"no {', '.join(missing)} proposal among the files")
    return ("fail", "; ".join(problems)) if problems else ("pass", (f"{len(paths)} schema-valid proposal(s): "
                                                           f"{', '.join(sorted(kinds))}"))


def verify_config(ctx: Ctx) -> Verdict:
    paths = [_resolve(ctx, ref, under=None, what="file") for ref in ctx.args.drafts]
    adopted: list[tuple[Path, str, str]] = []
    problems = []
    for path in paths:
        try:
            kind, key = _config_kind(ctx, path)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        adopted.append((path, kind, key))
    named = {kind for _path, kind, _key in adopted}
    missing = [k for k in ctx.spec.config if k in CONFIG_KEYS and k not in named]
    if missing and not problems:
        raise Refused(f"name the adopted {' and '.join(missing)} file(s): --draft FILE (the proposal or example the "
                      "human adopted)")
    report = ctx.service.config.check()
    if not report.ok:
        problems.append("config check: " + "; ".join(p.message for p in report.problems[:3]))
    files = ctx.bundle.files
    for path, _kind, key in adopted:
        ctx.add("drafts", EvidenceItem(ref=ctx.shown(path), sha256=sha256_file(path)))
        problems += _adopted_problems(ctx, key, files.get(key), path)
    for kind in ctx.spec.config:
        if kind not in CONFIG_KEYS and kind not in named:
            problems += _adopted_problems(ctx, kind, files.get(kind), None)
    if problems:
        return "fail", "; ".join(problems)
    return "pass", "adopted: " + ", ".join(item.ref for item in ctx.ev.get("config", []))


def _adopted_problems(ctx: Ctx, key: str, used: Any, source: Path | None) -> list[str]:
    if used is None:
        return [f"{key} is not in the configuration (not adopted)"]
    ctx.add("config", EvidenceItem(ref=key, sha256=used.sha256))
    if ctx.backend == "visa" and used.source not in ("local", "override"):
        return [(f"{key} comes from {used.source} ({used.path}), not config/local: the human adopts it "
                "(`uv run b1500 config adopt FILE --as KIND`)")]
    if source is None:
        return []
    local = Path(used.path) if Path(used.path).is_absolute() else ctx.repo / used.path
    try:
        same = _normalized(local.read_text(encoding="utf-8")) == _normalized(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        same = False
    return [] if same else [f"{used.path} differs from {ctx.shown(source)} (adopt the reviewed file again)"]


def verify_record(ctx: Ctx) -> Verdict:
    if not ctx.args.drafts:
        raise Refused("give the draft records: --draft work/bringup/records/<DRAFT>.yaml (repeatable)")
    folder = _bringup_dir(ctx) / DRAFTS_DIR
    paths = [_resolve(ctx, ref, under=folder, what="draft record") for ref in ctx.args.drafts]
    front = load_stage(ctx.repo, ctx.spec.group)[1]
    keys = {k or f"stage-{ctx.spec.group.lower()}" for k in front.record_keys()} if front else set()
    problems, notes = [], []
    for path in paths:
        ctx.add("drafts", EvidenceItem(ref=ctx.shown(path), sha256=sha256_file(path)))
        try:
            record = load_record(path)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        ctx.add("facts", f"record {record.key}")
        if record.stage != ctx.spec.group or record.key not in keys:
            problems.append(f"{path.name}: a {record.stage} {record.key} record; stage {ctx.spec.group} records "
                            f"{', '.join(sorted(keys))}")
        elif record.result == "fail":
            problems.append(f"{path.name}: result fail (the stage is repeated, the record is not moved)")
        elif not record.result:
            notes.append(f"{record.key} undecided (the reviewer judges)")
    if problems:
        return "fail", "; ".join(problems)
    return "pass", f"{len(paths)} draft record(s)" + (f"; {'; '.join(notes)}" if notes else "")


def verify_capture(ctx: Ctx) -> Verdict:
    """Fixture folders of ``b1500 bringup capture``: one per run or probe record given (``work/bringup/fixtures/<run
    id or probe stem>``), every file written by the capture, the runs valid evidence of the step's recipes and every
    required recipe captured."""
    if not ctx.args.fixtures or not (ctx.args.runs or ctx.args.probe):
        raise Refused("give the capture: --run H... (or --probe latest) and --fixtures work/bringup/fixtures/<name>, "
                      "one --fixtures per captured run or probe record")
    root = _bringup_dir(ctx) / FIXTURES_DIR
    folders = [_resolve(ctx, ref, under=root, what="fixture folder") for ref in ctx.args.fixtures]
    tags: set[str] = set()
    problems: list[str] = []
    if ctx.args.runs:
        facts = _runs(ctx, ctx.args.runs)
        ctx.ev["runs"] = [EvidenceItem(ref=f.manifest.run_id, sha256=model_digest(f.manifest)) for f in facts]
        problems += [p for f in facts for p in run_problems(f, ctx.spec, ctx.backend)]
        tags |= {f.manifest.run_id for f in facts}
        missing = [r for r in ctx.spec.required_recipes if r not in {f.manifest.recipe_id for f in facts}]
        if missing:
            problems.append(f"no run of {', '.join(missing)} among the captured runs")
    if ctx.args.probe:
        try:
            probe = evidence_reader.probe_facts(ctx.bundle, ctx.args.probe)
        except Exception as exc:  # noqa: BLE001 - no probe record: refused with the reader's reason
            raise Refused(str(exc)) from None
        ctx.ev["probe"] = EvidenceItem(ref=probe.path, sha256=model_digest(probe.report))
        tags.add(Path(probe.path).stem)
    ctx.ev["fixtures"] = [EvidenceItem(ref=ctx.shown(f), sha256=_folder_sha(f)) for f in folders]
    names = [folder.name for folder in folders]
    for folder in folders:
        files = sorted(p for p in folder.rglob("*.txt") if p.is_file())
        if folder.name not in tags:
            problems.append(f"{ctx.shown(folder)} is not the fixture folder of {', '.join(sorted(tags))}")
        if not files:
            problems.append(f"{ctx.shown(folder)} holds no fixture file")
        stray = [p.name for p in files if not p.read_text(encoding="utf-8").startswith("# source: hardware capture")]
        if stray:
            problems.append(f"not written by `uv run b1500 bringup capture`: {', '.join(stray[:5])}")
    uncaptured = sorted(tags - set(names))
    if uncaptured:
        problems.append(f"no fixture folder of {', '.join(uncaptured)} (one --fixtures per run or probe record)")
    if problems:
        return "fail", "; ".join(problems)
    count = sum(1 for folder in folders for p in folder.rglob("*.txt") if p.is_file())
    return "pass", f"{count} fixture file(s) in {', '.join(ctx.shown(f) for f in folders)}"


def _folder_sha(folder: Path) -> str:
    lines = [f"{p.relative_to(folder).as_posix()}:{sha256_file(p)}" for p in sorted(folder.rglob("*")) if p.is_file()]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def verify_observation(ctx: Ctx) -> Verdict:
    return "pass", "observed: " + ", ".join(f"{k}={v}" for k, v in _observed(ctx.args).items())


def _observed(args: StepArgs) -> dict[str, str]:
    return {m["key"]: m["value"].strip() for item in args.observe if (m := OBSERVE.match(item.strip()))}


def verify_hw_suite(ctx: Ctx) -> Verdict:
    if len(ctx.args.drafts) != 1:
        raise Refused("give the JUnit file of the hardware tests: --draft work/bringup/hw-<UTC>.xml")
    path = _resolve(ctx, ctx.args.drafts[0], under=Path(ctx.bundle.paths.work_dir), what="JUnit file")
    ctx.add("drafts", EvidenceItem(ref=ctx.shown(path), sha256=sha256_file(path)))
    try:
        cases = list(ElementTree.parse(path).getroot().iter("testcase"))
    except (OSError, ElementTree.ParseError) as exc:
        return "fail", f"{path.name} is not a JUnit XML file ({type(exc).__name__})"
    failed = [c.get("name", "?") for c in cases if c.find("failure") is not None or c.find("error") is not None]
    gated = [c.get("name", "?") for c in cases if (s := c.find("skipped")) is not None
             and (s.get("message") or "").removeprefix("Skipped: ").startswith(GATE_SKIP)]
    skipped = sum(c.find("skipped") is not None for c in cases)
    problems = []
    if not cases:
        problems.append(f"{path.name} lists no test")
    if failed:
        problems.append(f"{len(failed)} failed: {', '.join(failed[:5])}")
    if gated:
        problems.append(f"{len(gated)} skipped by the gate (B1500_HW=1 and backend visa needed): HARDWARE SUITE NOT "
                        "RUN")
    if problems:
        return "fail", f"{path.name}: " + "; ".join(problems)
    return "pass", f"{path.name}: {len(cases)} test(s), {skipped} skipped (no record yet), none failed"


def verify_confirm(ctx: Ctx) -> Verdict:
    return "pass", f"the human's words ({ctx.args.by})"


def verify_review(ctx: Ctx) -> Verdict:
    front = load_stage(ctx.repo, ctx.spec.group)[1]
    if front is None:
        return "fail", f"stage {ctx.spec.group} has no readable stage file"
    folder = ctx.repo.joinpath(*VALIDATION_DIR)
    problems = []
    for key in front.record_keys():
        name = f"{key or 'stage-' + ctx.spec.group.lower()}.yaml"
        path = folder / name
        if not path.is_file():
            problems.append(f"validation/hw/{name} missing")
            continue
        ctx.add("drafts", EvidenceItem(ref=ctx.shown(path), sha256=sha256_file(path)))
        try:
            record = load_record(path)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        problems += [f"{name}: {p}" for p in reviewed_record_problems(record, name)]
    if problems:
        return "fail", "; ".join(problems)
    return "pass", f"{len(front.record_keys())} reviewed record(s) in validation/hw/"


def verify_station(ctx: Ctx) -> Verdict:
    status = ctx.service.station_status(refresh=False)
    problems = []
    if status.fault is not None:
        problems.append(f"fault latched: {status.fault.reason}")
    if status.active_run is not None:
        problems.append(f"run {status.active_run.run_id} still running")
    if status.lock_holder is not None:
        problems.append(f"lock held by pid {status.lock_holder.pid} ({status.lock_holder.adapter})")
    if status.inflight_marker:
        problems.append("in-flight marker present (the next transaction recovers it)")
    if not problems and not status.ok:
        problems.append(f"station_status {status.status}: {status.message[:200]}")
    ctx.add("facts", "station: " + ("; ".join(problems) or "no fault, no lock holder, no running run"))
    return ("fail", "; ".join(problems)) if problems else ("pass", "station_status clean")


def verify_doctor(ctx: Ctx) -> Verdict:
    if ctx.doctor is None:
        raise Refused("this step runs `uv run b1500 doctor`: record it with `uv run b1500 bringup done`")
    lines = list(ctx.doctor())
    failed = [name for name, status, _detail in lines if status == "FAIL"]
    warned = [name for name, status, _detail in lines if status == "WARN"]
    ctx.add("facts", f"doctor: {len(lines)} checks, FAIL {', '.join(failed) or 'none'}, WARN "
                     f"{', '.join(warned) or 'none'}")
    statuses = {name: status for name, status, _detail in lines}
    accepted = ("PASS", "INFO") if ctx.backend == "sim" else ("PASS",)
    unmet = [f"{name} {statuses.get(name, 'missing')}" for name in ctx.spec.must_pass
             if statuses.get(name) not in accepted]
    if failed or unmet:
        return "fail", "doctor: " + "; ".join([f"FAIL {', '.join(failed)}" if failed else "",
                                                f"must PASS: {', '.join(unmet)}" if unmet else ""]).strip("; ")
    return "pass", f"doctor without FAIL ({len(lines)} checks)"


def verify_ledger(ctx: Ctx) -> Verdict:
    if ctx.gaps is None:
        raise Refused("this step runs `uv run b1500 bringup check`: record it with `uv run b1500 bringup done`")
    gaps = ctx.gaps()
    if gaps:
        return "fail", f"{len(gaps)} gap(s): " + "; ".join(f"{g.step}: {g.reason}" for g in gaps[:5])
    return "pass", "`uv run b1500 bringup check`: every recorded entry re-verified, no gap"


def verify_refusal(ctx: Ctx) -> Verdict:
    if ctx.args.runs:
        facts = _runs(ctx, ctx.args.runs)
        ctx.ev["runs"] = [EvidenceItem(ref=f.manifest.run_id, sha256=model_digest(f.manifest)) for f in facts]
        wrong = [f.manifest.run_id for f in facts if f.manifest.backend != ctx.backend]
        if wrong:
            return "fail", f"runs of another backend: {', '.join(wrong)}"
    return "pass", ("rehearsed: on hardware this step drafts records or captures fixtures; the simulator refuses "
                    "both by design")


VERIFIERS: dict[str, Callable[[Ctx], Verdict]] = {
    "run": verify_run, "probe": verify_probe, "config": verify_config, "proposal": verify_proposal,
    "record": verify_record, "capture": verify_capture, "observation": verify_observation,
    "hw_suite": verify_hw_suite, "confirm": verify_confirm, "review": verify_review, "station": verify_station,
    "doctor": verify_doctor, "ledger": verify_ledger, "refusal": verify_refusal,
}


def reverify(ctx: Ctx, entry: LedgerEntry) -> tuple[list[str], list[str]]:
    """``(problems, notes)`` of a passing entry against the current files (module docstring)."""
    problems: list[str] = []
    notes: list[str] = []
    ev = entry.evidence
    for item in ev.runs:
        try:
            facts = evidence_reader.run_facts(ctx.bundle, item.ref)
        except Exception as exc:  # noqa: BLE001 - a run that cannot be read is a gap
            problems.append(f"run {item.ref}: {exc}")
            continue
        if model_digest(facts.manifest) != item.sha256:
            problems.append(f"run {item.ref}: its manifest changed since the entry")
        if facts.changed_files:
            problems.append(f"run {item.ref}: files changed since the run ({', '.join(facts.changed_files)})")
    if ev.probe is not None:
        try:
            same = model_digest(evidence_reader.probe_facts(ctx.bundle, ev.probe.ref).report) == ev.probe.sha256
        except Exception:  # noqa: BLE001 - a probe record that cannot be read is a gap
            same = False
        if not same:
            problems.append(f"probe record {ev.probe.ref} missing or changed since the entry")
    records = [f.removeprefix("record ") for f in ev.facts if f.startswith("record ")]
    for item in ev.drafts:
        path = ctx.repo / item.ref if not Path(item.ref).is_absolute() else Path(item.ref)
        current = sha256_file(path) if path.is_file() else None
        if current == item.sha256:
            continue
        if entry.verify in ("proposal", "config"):
            notes.append(f"{item.ref} {'changed' if current else 'gone'} since (a later proposal or adoption)")
        elif entry.verify == "record" and current is None and any(
                ctx.repo.joinpath(*VALIDATION_DIR, f"{key}.yaml").is_file() for key in records):
            notes.append(f"{item.ref} moved to validation/hw/ after review")
        elif entry.verify == "review" and current is not None:
            notes.append(f"{item.ref} edited since the review step (reviewed again?)")
        else:
            problems.append(f"{item.ref} {'changed' if current else 'missing'} since the entry")
    for item in ev.fixtures:
        folder = ctx.repo / item.ref
        if folder.is_dir():
            if _folder_sha(folder) != item.sha256:
                problems.append(f"{item.ref} changed since the entry")
        elif ctx.repo.joinpath("tests", "fixtures", "hw", folder.name).is_dir():
            notes.append(f"{item.ref} moved to tests/fixtures/hw/ after review")
        else:
            problems.append(f"{item.ref} missing")
    for item in ev.config:
        used = ctx.bundle.files.get(item.ref)
        if used is None or used.sha256 != item.sha256:
            notes.append(f"{item.ref} {'re-adopted' if used else 'gone'} since")
    return problems, notes
