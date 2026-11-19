"""Lab bring-up helpers (blueprint v2 2.1, 7.1, 7.2, 7.4), all agent ok: ``propose_station`` (``b1500 bringup
propose-station``), ``bringup_status`` (``status``), ``capture`` (``capture RUN_ID…|probe``) and ``record``
(``record STAGE --run H…``).

Imports only ``service`` and ``models`` (layering test): the instrument is read through the service's read-only
inventory reading (``B1500Admin.read_inventory``: ``*IDN?`` and ``UNT?``, queries only), the configuration through
``B1500Service.config``, archived runs and probe records through ``service/evidence.py``. Nothing here writes
``config/local/`` or ``validation/hw/``: proposals, fixtures and draft records go to ``work/bringup/``; only the human
adopts a proposal (``b1500 config adopt FILE --as station``, human-only, blocked for agents) and only a human reviewer
moves a draft record to ``validation/hw/``.

**Status** (``bringup_status``): for every stage in order (``models.validation.STAGES``) the records that sign it
off (``StageFrontmatter.record_keys``: one per recipe with checks, plus the stage record) looked up among the
reviewed records in ``validation/hw/`` and the drafts in ``work/bringup/records/``; the next stage is the first one
not signed (a stage without a stage file is not ready: its module work package brings it).

**Capture** (``capture``): the instrument answers of hardware runs (``H…``, backend visa, run files unchanged since
the run) or of a hardware probe record become anonymized golden fixtures in the ``tests/fixtures/flex/`` format
(``tests/unit/flex_fixtures.py``) under ``work/bringup/fixtures/<run id or probe stem>/<kind>_<nn>.txt``: one file per
distinct answer, the ``*IDN?`` serial replaced by ``0``, ``expect`` from the driver's parsers, ``source`` naming the
capture and the Programming Guide page of the format; answers the parser rejects go to ``unparsed/`` with the
parser's message. Simulator runs and simulated probes are refused (fixtures never come from the simulator).

**Record** (``record``): a draft ``ValidationRecord`` in ``work/bringup/records/<stage>-<recipe id|stage>-<UTC>.yaml``
from hardware runs only. Refused, before anything is read, for simulator run ids (``S…``) and on a station whose
backend is not visa; refused for runs whose manifest says another backend, whose files changed since the run, or
whose recipe file changed since (the record pins the recipe's definition digest). A recipe record when the runs are
of one recipe that has checks in the stage (or ``recipe_id`` names it), else the stage record. Measured values are
copied from the runs (analysis results, quality noise per column, ``kind_result``, cleanup verification, probe
lines), never edited; each stage check (``StageFrontmatter.checks``) is matched with them and judged against its
tolerance when a reference was given (``references``: check id, optionally ``@RUN_ID``, to value) or not needed.
``reviewer`` stays empty.

**The proposal** = the active station profile (``config/local/station.yaml``; the committed example while there is
none) fitted to the live inventory:

- ``modules`` = every installed module ``UNT?`` lists (slot, model, type, channels per PG Table 4-1); the alias of
  the base module in the same slot with the same type is kept, otherwise ``SMU<slot>``, ``CMU<slot>``,
  ``SPGU<slot>`` or ``WGFMU<slot>``; a model this kernel does not know is left out with a note;
- ``mainframe.model`` from ``*IDN?`` (anything but a B1500A is refused);
- switches are copied from the base: wiring the base does not know stays ``null`` (the example's selector inputs),
  an input whose module is no longer installed becomes ``null``, a switch whose own module (RSU WGFMU channel,
  SCUU/ASU SMU) is missing is dropped, and every changed switch is ``certainty: unverified``; when the base is the
  committed example every switch is ``unverified``;
- cables and correction standards of aliases that no longer exist are dropped (noted);
- one provenance note (``*IDN?``, time, backend) replaces the previous one.

The result is validated as a ``StationProfile`` and written to ``work/bringup/station.proposed.yaml``; the unified
diff against the active local station file (both normalised by the same YAML dump, comments and the provenance note
dropped) is returned.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from b1500_test_agent.models.bringup import StationProposal
from b1500_test_agent.models.common import Backend, ErrorCode
from b1500_test_agent.models.routing import SwitchSpec
from b1500_test_agent.models.station import (
    ASU_SCUU_SMU_TYPES,
    MODULE_TYPE_BY_MODEL,
    SMU_TYPES,
    SWITCH_INPUT_TYPES,
    TWO_CHANNEL_TYPES,
    ModuleInventory,
    ModuleSlot,
    StationProfile,
)
from b1500_test_agent.models.validation import (
    BRINGUP_WORK_DIR,
    DRAFTS_DIR,
    FIXTURES_DIR,
    STAGE_FILES_DIR,
    STAGE_ORDER,
    STAGES,
    VALIDATION_DIR,
    BringupStatus,
    CapturedExchange,
    CapturedFixture,
    CaptureReport,
    ProbeFacts,
    RecordDraft,
    RecordDut,
    RecordItemState,
    RecordMeasurement,
    RecordRun,
    RecordStation,
    RunFacts,
    StageCheck,
    StageFrontmatter,
    StageProgress,
    StageRecordItem,
    StageStateName,
    ValidationRecord,
    reviewed_record_problems,
    stage_file_name,
)
from b1500_test_agent.service import B1500Admin, B1500Service
from b1500_test_agent.service import evidence as evidence_reader

BRINGUP_DIR = "bringup"
PROPOSAL_FILE = "station.proposed.yaml"
PROVENANCE = "Proposed by b1500 bringup propose-station"
"""Prefix of the provenance note; a new proposal replaces the old note."""

ALIAS_PREFIX = {"MFCMU": "CMU", "HVSPGU": "SPGU", "WGFMU": "WGFMU"}
"""Default alias prefix per module type (SMU types: ``SMU``), followed by the slot number as in the lab code."""

HEADER = """\
# Station profile PROPOSED by `b1500 bringup propose-station` (blueprint v2 7.1); schema: StationProfile.
# Generated from the live *IDN? / UNT? answers and the base profile named below; not used until a human reviews it
# and adopts it into config/local/station.yaml (human only). Switch wiring stays null / unverified until a human
# records it (bring-up L7).
# base: {base}
# backend: {backend}{simulated}
"""


def _default_alias(module_type: str, slot: int) -> str:
    return f"{'SMU' if module_type in SMU_TYPES else ALIAS_PREFIX.get(module_type, module_type)}{slot}"


def _modules(inventory: ModuleInventory, base: StationProfile, notes: list[str]) -> list[ModuleSlot]:
    """The installed modules as station entries (see the module docstring)."""
    by_slot = {m.slot: m for m in base.modules}
    taken = {s.id for s in base.switches}
    modules: list[ModuleSlot] = []
    for installed in sorted(inventory.modules, key=lambda m: m.slot):
        module_type = MODULE_TYPE_BY_MODEL.get(installed.model)
        if module_type is None:
            notes.append(f"slot {installed.slot}: model {installed.model} is not a module type this kernel knows; "
                         "left out (a reviewed code change adds it)")
            continue
        slot = installed.slot
        channels = [slot * 100 + 1, slot * 100 + 2] if module_type in TWO_CHANNEL_TYPES else [slot]
        previous = by_slot.get(slot)
        alias = previous.alias if previous is not None and previous.type == module_type else None
        if alias is None or alias in taken:
            alias = _default_alias(module_type, slot)
            while alias in taken:
                alias += "x"
        taken.add(alias)
        if previous is None:
            notes.append(f"slot {slot}: {installed.model} added (not in the base profile)")
        elif previous.model != installed.model:
            notes.append(f"slot {slot}: {previous.model} in the base profile, {installed.model} installed")
        modules.append(ModuleSlot(slot=slot, model=installed.model, type=module_type, channels=channels,
                                  alias=alias))
    for slot, previous in sorted(by_slot.items()):
        if not any(m.slot == slot for m in modules) and not any(i.slot == slot for i in inventory.modules):
            notes.append(f"slot {slot}: {previous.model} in the base profile, nothing installed; removed")
    return modules


def _fit_switch(switch: SwitchSpec, modules: list[ModuleSlot], *, force_unverified: bool,
                notes: list[str]) -> dict[str, Any] | None:
    """The switch as a station entry fitted to ``modules`` (``None`` = dropped; see the module docstring)."""

    def module_of(channel: int) -> ModuleSlot | None:
        normalized = channel * 100 + 1 if channel <= 10 else channel
        return next((m for m in modules if any((c * 100 + 1 if c <= 10 else c) == normalized for c in m.channels)),
                    None)

    data = switch.model_dump(mode="json")
    changed = False
    for output, port in data["ports"].items():
        if switch.kind != "selector_16440a":
            owner = module_of(port["index"])
            fits = owner is not None and (owner.type == "WGFMU" if switch.kind == "rsu"
                                          else owner.type in ASU_SCUU_SMU_TYPES)
            if not fits:
                notes.append(f"switch {switch.id}: its channel {port['index']} is not installed; switch left out")
                return None
        for side, channel in port["inputs"].items():
            if channel is None:
                continue
            owner = module_of(channel)
            allowed = ASU_SCUU_SMU_TYPES if side == "smu" and switch.kind in ("asu", "scuu") else \
                SWITCH_INPUT_TYPES[side]
            if owner is None or owner.type not in allowed:
                port["inputs"][side] = None
                changed = True
                notes.append(f"switch {switch.id}.{output}: input {side} -> channel {channel} is not installed; set "
                             "to null (unknown)")
    if changed or force_unverified:
        data["certainty"] = "unverified"
    return data


def _normalized(station: StationProfile, *, provenance: bool = True) -> str:
    """The profile as YAML (one dump for the file and both sides of the diff); ``provenance=False`` leaves out the
    provenance note, so two proposals of the same station compare equal whenever they were made."""
    data = station.model_dump(mode="json")
    if not provenance:
        data["notes"] = [n for n in data["notes"] if not n.startswith(PROVENANCE)]
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _failure(message: str, code: ErrorCode, backend: Backend = "sim") -> StationProposal:
    return StationProposal(ok=False, status="busy" if code == "instrument_busy" else "error", error_code=code,
                           backend=backend, simulated=backend == "sim", message=message,
                           next_steps=["fix the reported problem, then run b1500 bringup propose-station again"])


def propose_station(service: B1500Service, *, now: datetime | None = None) -> StationProposal:
    """Read ``*IDN?``/``UNT?`` read-only and write ``work/bringup/station.proposed.yaml`` (module docstring)."""
    report = service.config.check()
    if not report.ok:
        problems = "; ".join(f"{p.file or 'config'}: {p.message}" for p in report.problems[:3])
        return _failure(f"configuration invalid: {problems} (b1500 config check)", "invalid_config",
                        report.backend or "sim")
    bundle = service.config.get()
    backend = bundle.backend
    reading = B1500Admin(service).read_inventory()
    if not reading.ok or reading.identity is None or reading.inventory is None:
        return _failure(f"cannot read the instrument: {reading.message}", reading.error_code or "internal",
                        backend)
    identity, inventory = reading.identity, reading.inventory
    if identity.model.strip() != "B1500A":
        return _failure(f"the instrument identifies as {identity.raw!r}; this kernel supports the B1500A "
                                 "only", "instrument_error", backend)
    used = bundle.files["station"]
    base = bundle.station
    from_example = used.source == "example"
    notes: list[str] = []
    modules = _modules(inventory, base, notes)
    if not modules:
        return _failure("the instrument lists no module this kernel knows; nothing to propose",
                        "instrument_error", backend)
    same_inventory = {(m.slot, m.model) for m in modules} == {(m.slot, m.model) for m in base.modules}
    switches = [fitted for switch in base.switches
                if (fitted := _fit_switch(switch, modules, force_unverified=from_example or not same_inventory,
                                          notes=notes)) is not None]
    aliases = {m.alias for m in modules}
    cmu_aliases = {m.alias for m in modules if m.type == "MFCMU"}
    data = base.model_dump(mode="json")
    dropped_cables = sorted(set(base.topology.cables) - aliases)
    dropped_corrections = sorted(set(base.corrections) - cmu_aliases)
    if dropped_cables:
        notes.append(f"cable records of {', '.join(dropped_cables)} dropped (alias no longer present)")
    if dropped_corrections:
        notes.append(f"correction standards of {', '.join(dropped_corrections)} dropped (no such MFCMU alias)")
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    provenance = (f"{PROVENANCE} at {stamp} from the live identity {identity.raw!r} and module list (backend "
                  f"{backend}{', SIMULATED' if backend == 'sim' else ''}); base {used.path}.")
    data.update(
        name=base.name.removesuffix("-example") if from_example else base.name,
        modules=[m.model_dump(mode="json") for m in modules],
        switches=switches,
        notes=[n for n in base.notes if not n.startswith(PROVENANCE)] + [provenance],
    )
    data["topology"]["cables"] = {k: v for k, v in data["topology"]["cables"].items() if k in aliases}
    data["corrections"] = {k: v for k, v in data["corrections"].items() if k in cmu_aliases}
    try:
        station = StationProfile.model_validate(data)
    except ValidationError as exc:
        return _failure(f"the fitted profile does not validate: {exc.errors()[0]['msg']}", "internal",
                        backend)
    folder = bundle.paths.work_dir / BRINGUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / PROPOSAL_FILE
    header = HEADER.format(base=used.path, backend=backend, simulated=" (SIMULATED: a rehearsal, not hardware)"
                           if backend == "sim" else "")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + _normalized(station))
    shown = bundle.paths.display(path)
    diff: list[str] | None = None
    local: str | None = None
    if used.source in ("local", "override"):
        local = used.path
        diff = list(difflib.unified_diff(_normalized(base, provenance=False).splitlines(),
                                         _normalized(station, provenance=False).splitlines(),
                                         fromfile=f"{local} (normalised)", tofile=shown, lineterm=""))
    matches = None if diff is None else not diff
    if diff is None:
        verdict = "no config/local/station.yaml yet: adopting it creates one"
    elif matches:
        verdict = f"identical to {local}"
    else:
        verdict = f"differs from {local} (diff below)"
    flag = "SIMULATED " if backend == "sim" else ""
    message = f"{flag}proposal for {len(modules)} modules written to {shown}; {verdict}"
    steps = [(f"show the human {shown} and the diff; only the human adopts it: b1500 config adopt {shown} --as "
              "station (human only), then b1500 config check")]
    if any(s.get("certainty") == "unverified" for s in switches):
        steps.append("switch wiring stays null/unverified until the human records it at bring-up L7")
    return StationProposal(ok=True, status="ok", backend=backend, simulated=backend == "sim", message=message,
                           next_steps=steps, path=shown, base=used.path, local=local, diff=diff, notes=notes,
                           identity=identity, inventory=inventory, station=station, matches_local=matches)



# == shared helpers ==================================================================================================

RUN_ID = re.compile(r"^[SH]\d{8}T\d{6}Z-[0-9a-f]{4}$")
REFERENCE = re.compile(r"^(?P<check>[a-z][a-z0-9_]*)(?:@(?P<run>[SH]\d{8}T\d{6}Z-[0-9a-f]{4}))?=(?P<value>.+)$")
NO_SIM_RECORD = ("records and fixtures come only from hardware runs (H..., backend visa); a simulator run never "
                 "becomes one, rehearsal or not")
REHEARSAL_STEP = ("rehearsal: say which record the stage would draft on hardware; never write a record, fixture or "
                  "validation/hw/ file by hand")


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _stamp(now: datetime) -> str:
    """Windows-safe UTC file stamp ``20261201T093012Z`` (no ``:``)."""
    return now.strftime("%Y%m%dT%H%M%SZ")


def _bringup_dir(bundle: Any) -> Path:
    return Path(bundle.paths.work_dir) / BRINGUP_WORK_DIR


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


def _refused(result_type: Any, backend: Backend, message: str, steps: Sequence[str] = (), **extra: Any) -> Any:
    return result_type(ok=False, status="refused", error_code="invalid_input", backend=backend,
                       simulated=backend == "sim", message=message, next_steps=list(steps), **extra)


def _simulated_runs(sources: Iterable[str]) -> list[str]:
    return [s for s in sources if RUN_ID.match(s) and s.startswith("S")]


# == status ==========================================================================================================


def bringup_status(service: B1500Service) -> BringupStatus:
    """Stages done and next, from ``validation/hw/`` and ``work/bringup/records/`` (module docstring)."""
    return B1500Admin(service).call("bringup_status", {}, BringupStatus, _status)


def _reviewed_records(bundle: Any, notes: list[str]) -> dict[tuple[str, str | None], str]:
    folder = Path(bundle.paths.repo_root).joinpath(*VALIDATION_DIR)
    found: dict[tuple[str, str | None], str] = {}
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            record = load_record(path)
        except ValueError as exc:
            notes.append(f"validation/hw: {exc}")
            continue
        problems = reviewed_record_problems(record, path.name)
        if problems:
            notes.append(f"validation/hw/{path.name}: {'; '.join(problems)} (not counted)")
            continue
        found[(record.stage, record.recipe_id)] = bundle.paths.display(path)
    return found


def _draft_records(bundle: Any, notes: list[str]) -> dict[tuple[str, str | None], str]:
    folder = _bringup_dir(bundle) / DRAFTS_DIR
    found: dict[tuple[str, str | None], str] = {}
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            record = load_record(path)
        except ValueError as exc:
            notes.append(f"work/bringup/records: {exc}")
            continue
        found[(record.stage, record.recipe_id)] = bundle.paths.display(path)  # newest name wins (UTC stamp)
    return found


def _stage_state(items: list[StageRecordItem]) -> StageStateName:
    states = {item.state for item in items}
    if states == {"reviewed"}:
        return "signed"
    if "missing" not in states:
        return "review"
    return "in_progress" if states - {"missing"} else "open"


def _status(bundle: Any) -> BringupStatus:
    notes: list[str] = []
    reviewed = _reviewed_records(bundle, notes)
    drafts = _draft_records(bundle, notes)
    stages: list[StageProgress] = []
    for stage in STAGE_ORDER:
        path, front, problem = load_stage(bundle.paths.repo_root, stage)
        if problem:
            notes.append(problem)
        if front is None:
            stages.append(StageProgress(stage=stage, title=STAGES[stage][1], state="no_stage_file"))
            continue
        items = []
        for recipe_id in front.record_keys():
            key = (stage, recipe_id)
            state: RecordItemState = "reviewed" if key in reviewed else "draft" if key in drafts else "missing"
            items.append(StageRecordItem(recipe_id=recipe_id, state=state,
                                         path=reviewed.get(key) or drafts.get(key)))
        stages.append(StageProgress(stage=stage, title=front.title, file=bundle.paths.display(path),
                                    state=_stage_state(items), records=items))
    current = next((s for s in stages if s.state != "signed"), None)
    backend = bundle.backend
    flag = "SIMULATED " if backend == "sim" else ""
    if current is None:
        message, steps = f"{flag}every bring-up stage is signed", ["L10: hand the reviewed records over (OD-7)"]
    elif current.state == "no_stage_file":
        message = f"{flag}next stage {current.stage} ({current.title}) has no stage file yet: not ready"
        steps = [f"stop here: stage {current.stage} arrives with its module work package"]
    else:
        message = f"{flag}next stage {current.stage}: {current.title} ({current.state})"
        steps = [f"read {current.file} and work it from its preconditions"]
        if current.state == "review":
            steps = [f"the human reviews the drafts of {current.stage} and moves them to validation/hw/ (human only)"]
    if backend == "sim":
        steps.append("simulator: a rehearsal; no record is ever drafted from simulator runs")
    return BringupStatus(ok=True, status="ok", backend=backend, simulated=backend == "sim", message=message,
                         next_steps=steps, stages=stages, next_stage=current.stage if current else None,
                         reviewed=sorted(reviewed.values()), drafts=sorted(drafts.values()), notes=notes)


# == capture =========================================================================================================

PG = "Keysight B1500 Series Programming Guide, Edition 15"
FORMAT_PAGES: dict[str, str] = {
    "fmt1": f"{PG}, PDF 46-55 (printed 1-26 to 1-35, Tables 1-6 to 1-12), PDF 436-438 (FMT)",
    "fmt5": f"{PG}, PDF 46-55 (Tables 1-6 to 1-12), PDF 437 (FMT 5: every element ends with ',')",
    "idn": f"{PG}, PDF 440 (printed 4-122, *IDN? response)",
    "unt": f"{PG}, PDF 545 (printed 4-227, UNT? response)",
    "errx": f"{PG}, PDF 432 (printed 4-114, ERRX? response)",
    "lop": f"{PG}, PDF 446-447 (printed 4-128 to 4-129, LOP? response, Table 4-26)",
    "stb": f"{PG}, PDF 523 (printed 4-205, *STB?), PDF 76-77 (status byte bits)",
    "tst": f"{PG}, PDF 540-541 (printed 4-222 to 4-223, *TST?/*CAL? result, Table 4-32)",
    "lrn": f"{PG}, PDF 448 (printed 4-130, *LRN? type 31 response)",
    "ermod": f"{PG}, PDF 421 (printed 4-103, ERMOD? response)",
    "erssp": f"{PG}, PDF 434 (printed 4-116, ERSSP? port response)",
    "spst": f"{PG}, PDF 513-514 (printed 4-195 to 4-196, SPST? response)",
    "corrst": f"{PG}, PDF 388 (printed 4-70, CORRST? response)",
    "adj": f"{PG}, PDF 355-356 (printed 4-37 to 4-38, ADJ? response)",
}
"""Programming Guide pages of each fixture kind's response format (the fixture loader needs a ``PDF <page>``)."""
ANONYMIZED_SERIAL = "0"


def capture(service: B1500Service, sources: Sequence[str]) -> CaptureReport:
    """Write anonymized golden fixtures of hardware runs and probe records (module docstring)."""
    runs = [s for s in sources if RUN_ID.match(s)]
    args = {"sources": list(sources), "run_id": runs[0] if runs else None}
    return B1500Admin(service).call("bringup_capture", args, CaptureReport,
                                    lambda bundle: _capture(bundle, list(sources)))


def _anonymize(exchange: CapturedExchange) -> tuple[CapturedExchange, list[str]]:
    """The ``*IDN?`` serial replaced by ``0`` (the manual's own example answers ``0``, PG PDF 440)."""
    parts = exchange.response.split(",")
    if exchange.kind != "idn" or len(parts) != 4 or parts[2].strip() == ANONYMIZED_SERIAL:
        return exchange, []
    parts[2] = ANONYMIZED_SERIAL
    expect = dict(exchange.expect) if isinstance(exchange.expect, dict) else exchange.expect
    if isinstance(expect, dict):
        expect["serial"] = ANONYMIZED_SERIAL
    return exchange.model_copy(update={"response": ",".join(parts), "expect": expect}), [
        "serial number replaced by 0 (anonymized; the manual's own example answers 0, PG PDF 440)"]


def fixture_text(exchange: CapturedExchange, source: str, notes: Sequence[str]) -> str:
    """One fixture file in the ``tests/fixtures/flex/`` convention (``tests/unit/flex_fixtures.py``)."""
    lines = [f"# source: {source}; response format: {FORMAT_PAGES[exchange.kind]}", f"# kind: {exchange.kind}",
             f"# command: {exchange.command}"]
    if exchange.problem is not None:
        lines.append(f"# note: the driver parser rejected this answer: {exchange.problem}")
    elif exchange.kind in ("fmt1", "fmt5"):
        lines.append(f"# terminator: {exchange.terminator}")
        lines += [f"# point: {point}" for point in exchange.points]
    else:
        lines.append(f"# expect: {json.dumps(exchange.expect, ensure_ascii=False)}")
    lines += [f"# note: {note}" for note in notes]
    return "\n".join([*lines, exchange.response]) + "\n"


def _capture_sources(bundle: Any, sources: list[str]) -> tuple[list[tuple[str, str, list[CapturedExchange]]],
                                                                str | None]:
    """``[(tag, capture description, exchanges)]`` of every source, or a refusal message."""
    found: list[tuple[str, str, list[CapturedExchange]]] = []
    for source in sources:
        if RUN_ID.match(source):
            facts = evidence_reader.run_facts(bundle, source)
            manifest = facts.manifest
            if manifest.backend != "visa":
                return [], f"run {source} ran on backend {manifest.backend}: {NO_SIM_RECORD}"
            if facts.changed_files:
                return [], f"run {source}: files changed since the run ({', '.join(facts.changed_files)})"
            when = manifest.started_at.astimezone(UTC).date().isoformat()
            found.append((source, f"hardware capture of run {source} ({when}, b1500 bringup capture)",
                          facts.exchanges))
        else:
            probe = evidence_reader.probe_facts(bundle, source)
            if probe.report.backend != "visa":
                return [], f"{probe.path} is a SIMULATED probe: {NO_SIM_RECORD}"
            tag = Path(probe.path).stem
            when = probe.report.taken_at.date().isoformat() if probe.report.taken_at else "date unknown"
            found.append((tag, (f"hardware capture of probe record {Path(probe.path).name} ({when}, b1500 bringup "
                               "capture)"), probe.exchanges))
    return found, None


def _capture(bundle: Any, sources: list[str]) -> CaptureReport:
    backend: Backend = bundle.backend
    if not sources:
        return _refused(CaptureReport, backend, "name hardware run ids (H...) or probe (the newest probe record)")
    simulated = _simulated_runs(sources)
    if simulated:
        return _refused(CaptureReport, backend, f"refused: {', '.join(simulated)}: {NO_SIM_RECORD}",
                        [REHEARSAL_STEP])
    found, problem = _capture_sources(bundle, sources)
    if problem is not None:
        return _refused(CaptureReport, backend, f"refused: {problem}", [REHEARSAL_STEP])
    root = _bringup_dir(bundle) / FIXTURES_DIR
    written: list[CapturedFixture] = []
    skipped: list[str] = []
    for tag, description, exchanges in found:
        seen: set[tuple[str, str, str]] = set()
        counts: dict[str, int] = {}
        for raw in exchanges:
            key = (raw.kind, raw.command, raw.response)
            if key in seen:
                continue
            seen.add(key)
            if "\n" in raw.response or "\r" in raw.response:
                skipped.append(f"{tag}: {raw.command}: multi-line answer (not a single-line fixture)")
                continue
            exchange, notes = _anonymize(raw)
            counts[exchange.kind] = counts.get(exchange.kind, 0) + 1
            folder = root / tag / ("unparsed" if exchange.problem else "")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{exchange.kind}_{counts[exchange.kind]:02d}.txt"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(fixture_text(exchange, description, notes))
            written.append(CapturedFixture(path=bundle.paths.display(path), kind=exchange.kind,
                                           command=exchange.command, source=tag, parsed=exchange.problem is None))
    folder = bundle.paths.display(root)
    unparsed = sum(not w.parsed for w in written)
    message = f"{len(written)} fixture file(s) from {len(found)} source(s) written to {folder}"
    if unparsed:
        message += f"; {unparsed} answer(s) the parser rejected are in unparsed/ (a parser finding)"
    steps = [("the human reviews the files and moves them to tests/fixtures/hw/ (OD-7); a developer adds the parser "
             "tests")]
    return CaptureReport(ok=True, status="ok", backend=backend, simulated=backend == "sim", message=message,
                         next_steps=steps, written=written, skipped=skipped, folder=folder)


# == record ==========================================================================================================


def record(service: B1500Service, stage: str, run_ids: Sequence[str] = (), *, recipe_id: str | None = None,
           probe: str | None = None, references: Sequence[str] = (), operator: str = "",
           dut_instance: str | None = None, notes: Sequence[str] = (), now: datetime | None = None) -> RecordDraft:
    """Draft a validation record of ``stage`` from hardware runs (module docstring)."""
    args = {"stage": stage, "run_id": run_ids[0] if run_ids else None, "run_ids": list(run_ids),
            "recipe_id": recipe_id, "probe": probe}
    return B1500Admin(service).call(
        "bringup_record", args, RecordDraft,
        lambda bundle: _record(service, bundle, stage, list(run_ids), recipe_id=recipe_id, probe=probe,
                               references=list(references), operator=operator, dut_instance=dut_instance,
                               notes=list(notes), now=_now(now)))


def parse_references(items: Sequence[str]) -> dict[tuple[str, str | None], float]:
    """``CHECK=VALUE`` / ``CHECK@RUN_ID=VALUE`` -> {(check, run id or None): value}; raises ``ValueError``."""
    parsed: dict[tuple[str, str | None], float] = {}
    for item in items:
        match = REFERENCE.match(item.strip())
        if match is None:
            raise ValueError(f"reference {item!r} is not CHECK=VALUE or CHECK@RUN_ID=VALUE")
        try:
            parsed[(match["check"], match["run"])] = float(match["value"])
        except ValueError:
            raise ValueError(f"reference {item!r}: {match['value']!r} is not a number") from None
    return parsed


def _method_text(result: Any) -> str:
    text = result.method
    if result.window is not None:
        text += f", window {result.window.low:g}..{result.window.high:g} {result.window.unit}"
    return text


def _unit_of(column: str) -> str:
    return {"I": "A", "V": "V", "C": "F", "T": "s"}.get(column.rsplit("_", 1)[-1], "")


def _candidates(facts: list[RunFacts], probe: ProbeFacts | None) -> list[RecordMeasurement]:
    """Every value the runs and the probe record hold (copied, never edited)."""
    found: list[RecordMeasurement] = []
    for item in facts:
        run_id = item.manifest.run_id
        for result in item.analyses:
            if result.outcome == "ok":
                found.append(RecordMeasurement(quantity=result.quantity, value=result.value, unit=result.unit,
                                               observed=result.classification or "", run_id=run_id,
                                               method=_method_text(result)))
        for column, noise in (item.quality.noise if item.quality else {}).items():
            name = re.sub(r"[^A-Za-z0-9_]", "_", f"noise_{column}")
            found.append(RecordMeasurement(quantity=name, value=noise, unit=_unit_of(column), run_id=run_id,
                                           method="quality_report noise (robust estimate)"))
        control = getattr(item.manifest.cleanup, "positive_control", None)  # LOP? right after CN (WP6.2)
        if control is not None:
            shown = control.model_dump_json() if hasattr(control, "model_dump_json") else json.dumps(control)
            found.append(RecordMeasurement(quantity="positive_control", observed=shown[:300], run_id=run_id,
                                           method="run manifest cleanup.positive_control"))
        for key, value in item.manifest.kind_result.items():
            if re.match(r"^[A-Za-z][A-Za-z0-9_]{0,63}$", key):
                numeric = isinstance(value, int | float) and not isinstance(value, bool)
                found.append(RecordMeasurement(quantity=key, value=float(value) if numeric else None,
                                               observed="" if numeric else str(value), run_id=run_id,
                                               method="kind_result"))
    for line in probe.report.checks if probe else []:
        verdict = {"PASS": True, "FAIL": False}.get(line.status)
        found.append(RecordMeasurement(quantity=re.sub(r"[^A-Za-z0-9_]", "_", line.name.strip()) or "probe",
                                       observed=f"{line.status}: {line.detail}", method="b1500 doctor --probe",
                                       passed=verdict))
    return found


def _cleanup_measurement(check: StageCheck, facts: list[RunFacts]) -> RecordMeasurement:
    verified = [(f.manifest.run_id, f.manifest.cleanup.verified if f.manifest.cleanup else "not run") for f in facts]
    return RecordMeasurement(check=check.id, quantity="cleanup", observed=", ".join(f"{r}: {v}" for r, v in verified)
                             or "no runs", method="run manifest cleanup", reference_source=check.reference,
                             tolerance=check.text, passed=all(v == "lop" for _, v in verified) if verified else None)


def _measurements(checks: list[StageCheck], facts: list[RunFacts], probe: ProbeFacts | None,
                  references: Mapping[tuple[str, str | None], float]) -> list[RecordMeasurement]:
    """Each check matched with the candidates (module docstring), then the unmatched candidates."""
    candidates = _candidates(facts, probe)
    used: set[int] = set()
    out: list[RecordMeasurement] = []
    for check in checks:
        if check.quantity == "cleanup":
            out.append(_cleanup_measurement(check, facts))
            continue
        matches = [i for i, m in enumerate(candidates) if m.quantity == check.quantity
                   and (check.method is None or m.method.split(",")[0] in (check.method, "b1500 doctor --probe"))]
        if not matches:
            out.append(RecordMeasurement(check=check.id, quantity=check.quantity, unit=check.unit,
                                         observed="not measured in the given runs", reference_source=check.reference,
                                         tolerance=check.text))
            continue
        for index in matches:
            used.add(index)
            found = candidates[index]
            reference = references.get((check.id, found.run_id), references.get((check.id, None)))
            passed = check.tolerance.check(found.value, reference) if check.tolerance else found.passed
            out.append(found.model_copy(update={"check": check.id, "reference": reference, "passed": passed,
                                                "reference_source": check.reference, "tolerance": check.text}))
    out += [m for i, m in enumerate(candidates) if i not in used]
    return out


def _result(measurements: list[RecordMeasurement], checks: list[StageCheck]) -> str:
    """``fail`` when a check failed; ``pass`` when every judged check (a tolerance, ``cleanup`` or a probe line)
    passed and none is undecided; else ``""`` (recorded-only checks are left to the reviewer)."""
    judged = {c.id for c in checks if c.tolerance is not None or c.quantity == "cleanup"}
    decided = [m.passed for m in measurements if m.check is not None and (m.check in judged or m.passed is not None)]
    if any(p is False for p in decided):
        return "fail"
    return "pass" if decided and all(p is True for p in decided) else ""


def _run_record(item: RunFacts) -> RecordRun:
    manifest = item.manifest
    return RecordRun(run_id=manifest.run_id, recipe_id=manifest.recipe_id, recipe_file_sha256=manifest.recipe_sha,
                     plan_hash=manifest.plan_hash, pin_map=manifest.plan.request.pin_map,
                     dut_profile=manifest.plan.request.dut_profile, started_at=manifest.started_at,
                     outcome=manifest.outcome,
                     cleanup=manifest.cleanup.verified if manifest.cleanup is not None else "not run",
                     quality_verdict=manifest.quality_verdict, status_counts=dict(manifest.status_counts))


def _load_runs(bundle: Any, run_ids: list[str]) -> tuple[list[RunFacts], str | None]:
    facts = []
    for run_id in run_ids:
        item = evidence_reader.run_facts(bundle, run_id)
        if item.manifest.backend != "visa":
            return [], f"run {run_id} ran on backend {item.manifest.backend}: {NO_SIM_RECORD}"
        if item.changed_files:
            return [], (f"run {run_id}: files changed since the run ({', '.join(item.changed_files)}); evidence "
                       "must be the archive as written")
        facts.append(item)
    return facts, None


def _record_recipe(front: StageFrontmatter, facts: list[RunFacts], recipe_id: str | None) -> tuple[str | None,
                                                                                                    str | None]:
    """``(recipe id of the record or None for the stage record, refusal or None)``."""
    recipes = list(dict.fromkeys(f.manifest.recipe_id for f in facts))
    if recipe_id is not None:
        if recipe_id not in front.recipes:
            return None, f"stage {front.stage} does not run {recipe_id} (its recipes: {', '.join(front.recipes)})"
        others = sorted(set(recipes) - {recipe_id})
        if others or not facts:
            return None, f"a {recipe_id} record lists only runs of {recipe_id}" + (f" (got {others})" if others
                                                                                    else " (none given)")
        return recipe_id, None
    if len(recipes) == 1 and front.checks_for(recipes[0]):
        return recipes[0], None
    return None, None


def _record(service: B1500Service, bundle: Any, stage: str, run_ids: list[str], *, recipe_id: str | None,
            probe: str | None, references: list[str], operator: str, dut_instance: str | None, notes: list[str],
            now: datetime) -> RecordDraft:
    backend: Backend = bundle.backend
    simulated = _simulated_runs(run_ids)
    if simulated:
        return _refused(RecordDraft, backend, f"refused: {', '.join(simulated)} is a simulator run: {NO_SIM_RECORD}",
                        [REHEARSAL_STEP])
    if stage not in STAGES:
        return _refused(RecordDraft, backend, f"unknown stage {stage!r}; stages: {', '.join(STAGE_ORDER)}")
    malformed = [r for r in run_ids if not RUN_ID.match(r)]
    if malformed:
        return _refused(RecordDraft, backend, f"not run ids: {', '.join(malformed)} (H + UTC stamp + 4 hex)")
    if backend != "visa":
        return _refused(RecordDraft, backend, f"refused: this station runs backend {backend}; records are drafted "
                                              "only on the lab PC with backend visa", [REHEARSAL_STEP])
    path, front, problem = load_stage(bundle.paths.repo_root, stage)
    if front is None:
        return _refused(RecordDraft, backend, problem or f"stage {stage} has no stage file yet "
                                                         f"({bundle.paths.display(path)}): not ready")
    try:
        parsed = parse_references(references)
    except ValueError as exc:
        return _refused(RecordDraft, backend, str(exc))
    unknown = sorted({c for c, _ in parsed} - {c.id for c in front.checks})
    if unknown:
        return _refused(RecordDraft, backend, f"stage {stage} has no check(s) {unknown}; its checks: "
                                              f"{', '.join(c.id for c in front.checks) or 'none'}")
    facts, refusal = _load_runs(bundle, run_ids)
    if refusal is None:
        key, refusal = _record_recipe(front, facts, recipe_id)
    if refusal is not None:
        return _refused(RecordDraft, backend, f"refused: {refusal}")
    probe_facts = evidence_reader.probe_facts(bundle, probe) if probe else None
    if probe_facts is not None and probe_facts.report.backend != "visa":
        return _refused(RecordDraft, backend, f"refused: {probe_facts.path} is a SIMULATED probe: {NO_SIM_RECORD}")
    version = digest = None
    if key is not None:
        recipe = evidence_reader.recipe_facts(service, bundle, key)
        stale = [f.manifest.run_id for f in facts if f.manifest.recipe_sha != recipe.file_sha256]
        if stale:
            return _refused(RecordDraft, backend, f"refused: the recipe file {key} changed since run(s) "
                                                  f"{', '.join(stale)}; re-run the stage with the current recipe")
        version, digest = recipe.version, recipe.definition_sha256
    checks = front.checks_for(key)
    measurements = _measurements(checks, facts, probe_facts, parsed)
    first = facts[0].manifest if facts else None
    identity = first.identity if first else (probe_facts.report.identity if probe_facts else None)
    started = first.started_at.astimezone(UTC) if first else now
    auto = [(f"drafted by b1500 bringup record at {now.isoformat(timespec='seconds').replace('+00:00', 'Z')} from "
            f"{len(facts)} hardware run(s){' and ' + probe_facts.path if probe_facts else ''}; values copied from "
            "the run archive, never edited")]
    draft = ValidationRecord(
        stage=stage, recipe_id=key, recipe_version=version, recipe_sha256=digest,
        station=RecordStation(name=bundle.station.name, idn=identity.raw if identity else "",
                              firmware=identity.firmware if identity else ""),
        dut=RecordDut(profile=(first.plan.request.dut_profile or "") if first else "",
                      instance=dut_instance or (first.dut_instance or "" if first else "")),
        runs=[f.manifest.run_id for f in facts], evidence=[_run_record(f) for f in facts],
        probe=probe_facts.path if probe_facts else None, measurements=measurements,
        result=_result(measurements, checks), operator=operator.strip(), date=started.date().isoformat(),
        notes=[*notes, *auto])  # type: ignore[arg-type]
    folder = _bringup_dir(bundle) / DRAFTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stage}-{key or 'stage'}-{_stamp(now)}.yaml"
    header = (f"# DRAFT hardware validation record (b1500 bringup record; schema models/validation.py "
              f"ValidationRecord).\n# Review it against the raw runs; then the reviewer (a human) fills reviewer and "
              f"reviewed_on and moves it to validation/hw/{draft.file_name()}.\n")
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + yaml.safe_dump(draft.model_dump(mode="json"), sort_keys=False, allow_unicode=True,
                                             width=120))
    shown = bundle.paths.display(target)
    open_checks = sorted({m.check for m in measurements if m.passed is None and any(
        c.id == m.check and c.tolerance is not None for c in checks)})
    remarks = [(f"checks without a decision: {', '.join(open_checks)} (give the human's reference values with "
               "--reference CHECK=VALUE, or the reviewer judges them)")] if open_checks else []
    steps = [(f"show the human {shown}; the reviewer checks it against the raw runs, fills reviewer and reviewed_on "
             f"and moves it to validation/hw/{draft.file_name()} (human only)")]
    return RecordDraft(ok=True, status="ok", backend=backend, simulated=False, stage=stage, path=shown,
                       record=draft, notes=remarks, next_steps=steps,
                       message=f"draft {draft.key} record of stage {stage} written to {shown} (result "
                               f"{draft.result or 'undecided'}; reviewer empty)")
