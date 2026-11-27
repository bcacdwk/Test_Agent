"""Read-only evidence of archived runs and probe records for ``b1500 bringup capture | record`` (blueprint v2 7.1).

The bring-up helpers (``bringup.py``) may import only ``service`` and ``models``; this module is their window on the
archive, the recipe registry and the driver's response parsers. Nothing here talks to the instrument or writes a
file.

- ``run_facts``: the manifest of a finished run, every analysis result in ``analysis/``, ``quality.json``, the
  instrument answers of its ``audit.jsonl`` parsed as golden-fixture exchanges, the timings the bring-up records
  carry (``audit_facts``) and the files whose sha256 no longer matches the manifest (evidence edited after the run).
- ``probe_facts``: a probe record ``work/bringup/probe-<UTC>.json`` (``probe``/``latest`` = the newest one) with its
  raw answers parsed the same way, plus the WGFMU library's file version (``wgfmu_version``) when the probe read it.
- ``recipe_facts``: the current recipe file's version, raw digest and definition digest
  (``models.validation.recipe_definition_sha256``).
- ``parse_exchange``: one answer → ``CapturedExchange`` (fixture kind from the query mnemonic and, for ``*LRN?`` and
  ``CORRL?``, its arguments; ``expect`` in the shape of the driver parser, or one point per FMT 1/5 data element). A
  query without a fixture kind gives ``None``; an answer the parser rejects keeps the parser's message in
  ``problem``.

Fixture kinds (v2.1 plan §4.6: every raw answer a bring-up stage settles has one): the probe's queries (``idn``,
``unt``, ``errx``, ``stb``, ``lop``, ``tst`` for ``*TST?``/``*CAL?``, ``lrn`` for ``*LRN? 31``, ``ermod``, ``erssp``,
``spst``, ``corrst``, ``adj``), the switch read-backs ``lrn62``/``lrn63`` (ASU paths and 1 pA ranging) and ``lrn81``
(SCUU paths), the MFCMU set-up read-backs ``lrn90`` (phase compensation mode), ``corrl`` (correction list: count or
one frequency), ``dcorr`` (standard reference value) and ``corrdt`` (correction data), the data blocks ``fmt1``/
``fmt5``, and the WGFMU instrument library's strings from the ``wgfmu_call`` audit events: ``wgfmu_error`` (the error
text of a failed call with its return and firmware code) and ``wgfmu_warnings`` (a non-empty warning summary).

Timings (``audit_facts``, the record fields of facts that otherwise live only in the audit): ``bus_call_s`` (the
slowest ``bus_open``/``bus_lock``/``bus_unlock``/``bus_close``, ATV-13), ``tst_s``/``cal_s`` (``*TST?``/``*CAL?``),
``adj_s``/``corr_s`` (the slowest ``ADJ?``/``CORR?``), ``wgfmu_self_test_s``/``wgfmu_self_cal_s``/``wgfmu_dc_read_s``
(the library calls) and ``wgfmu_readback_s_per_value`` (readback time over values read), in seconds from ``dur_ms``.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from b1500_test_agent.analysis.dataset import MANIFEST_FILE, load_manifest
from b1500_test_agent.archive.store import ANALYSIS_DIR, QUALITY_FILE, RunStore
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.cmu_data import (
    parse_adj_mode,
    parse_correction_data,
    parse_corrl_count,
    parse_corrl_frequency,
    parse_dcorr,
    parse_lrn_channel_items,
    parse_scuu_path,
)
from b1500_test_agent.driver.discovery import (
    parse_adj,
    parse_asu_1pa,
    parse_asu_paths,
    parse_auto_calibration,
    parse_corrst,
    parse_ermod,
    parse_erssp,
    parse_idn,
    parse_lop,
    parse_lrn_settings,
    parse_spst,
    parse_unt,
)
from b1500_test_agent.driver.errors import (
    FlexParseError,
    failed_units,
    parse_errx,
    parse_self_test_result,
    parse_status_byte,
    status_flags,
)
from b1500_test_agent.driver.parser import parse_data
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.fsio import sha256_file
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.models.validation import (
    BRINGUP_WORK_DIR,
    CapturedExchange,
    FixtureKind,
    ProbeFacts,
    RecipeFacts,
    RunFacts,
    recipe_definition_sha256,
)
from b1500_test_agent.transport.wgfmu.api import C_FUNCTIONS

if TYPE_CHECKING:
    from b1500_test_agent.service.core import B1500Service

AUDIT_FILE = "audit.jsonl"
PROBE_GLOB = "probe-*.json"
LATEST_PROBE = frozenset({"probe", "latest"})


def _head(command: str) -> str:
    """The mnemonic of a command (``ERSSP? 0`` -> ``ERSSP?``)."""
    return command.strip().split(" ", 1)[0].upper()


def _arguments(command: str) -> str:
    parts = command.strip().split(" ", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _lrn(text: str) -> dict[str, Any]:
    return {"settings": parse_lrn_settings(text), "auto_calibration": parse_auto_calibration(text)}


def _ermod(text: str) -> dict[str, Any]:
    value = parse_ermod(text)
    return {"value": value, "selector": bool(value & flex.ERMOD_SELECTOR)}


def _errx(text: str) -> dict[str, Any] | None:
    error = parse_errx(text)
    return None if error is None else error.model_dump(mode="json")


def _stb(text: str) -> dict[str, Any]:
    status = parse_status_byte(text)
    return {"value": status.value, "flags": status_flags(status)}


def _tst(text: str) -> dict[str, Any]:
    result = parse_self_test_result(text)
    return {"value": result, "failed": failed_units(result)}


def _lrn81(text: str) -> dict[str, int]:
    """``*LRN? 81``: SCUU path (``SSP``) per MFCMU channel, each checked by the driver's parser."""
    items = parse_lrn_channel_items(text, flex.LRN_SCUU_ITEM)
    for channel in items:
        parse_scuu_path(text, channel)
    return {str(channel): int(values[0]) for channel, values in items.items()}


def _lrn90(text: str) -> dict[str, int]:
    """``*LRN? 90``: phase compensation mode (``ADJ``) per MFCMU channel."""
    return {str(channel): parse_adj_mode(text, channel) for channel in parse_lrn_channel_items(text, flex.LRN_ADJ_ITEM)}


def _dcorr(text: str) -> dict[str, Any]:
    mode, primary, secondary = parse_dcorr(text)
    return {"mode": mode, "primary": primary, "secondary": secondary}


Parser = Callable[[str], Any]

_QUERIES: dict[str, tuple[FixtureKind, Parser]] = {
    _head(flex.IDN_Q): ("idn", lambda t: parse_idn(t).model_dump(mode="json", exclude={"raw"})),
    _head(flex.UNT_Q): ("unt", lambda t: {str(m.slot): m.model for m in parse_unt(t).modules}),
    _head(flex.ERRX_Q): ("errx", _errx),
    _head(flex.LOP_Q): ("lop", lambda t: {str(slot): out.state for slot, out in parse_lop(t).items()}),
    _head(flex.STB_Q): ("stb", _stb),
    _head(flex.TST_Q): ("tst", _tst),
    _head(flex.CAL_Q): ("tst", _tst),
    _head(flex.ERMOD_Q): ("ermod", _ermod),
    _head(flex.erssp_q(0)): ("erssp", lambda t: {"state": parse_erssp(t)}),
    _head(flex.SPST_Q): ("spst", lambda t: {"active": parse_spst(t)}),
    _head(flex.corrst_q(1, "open")): ("corrst", lambda t: {"on": parse_corrst(t)}),
    _head(flex.adj_q(1, flex.ADJ_READ_LAST)): ("adj", lambda t: {"result": parse_adj(t)}),
    _head(flex.dcorr_q(1, "open")): ("dcorr", _dcorr),
    _head(flex.corrdt_q(1, 1)): ("corrdt", lambda t: dataclasses.asdict(parse_correction_data(t))),
}
"""Query mnemonic -> (fixture kind, parser giving the fixture's ``expect``); mnemonics come from the FLEX builders.
``*LRN?`` and ``CORRL?`` depend on their arguments (``_LRN_KINDS``, ``_query_kind``)."""
_LRN_KINDS: dict[int, tuple[FixtureKind, Parser]] = {
    flex.LRN_SETTINGS: ("lrn", _lrn),
    flex.LRN_ASU_PATH: ("lrn62", lambda t: {str(ch): state for ch, state in parse_asu_paths(t).items()}),
    flex.LRN_ASU_1PA: ("lrn63", lambda t: {str(ch): on for ch, on in parse_asu_1pa(t).items()}),
    flex.LRN_SCUU_PATH: ("lrn81", _lrn81),
    flex.LRN_ADJ_MODE: ("lrn90", _lrn90),
}
"""``*LRN?`` type -> fixture kind (PG PDF 448, 451-452): the settings, the ASU and SCUU switch read-backs, the phase
compensation mode."""
_LRN_HEAD = _head(flex.lrn_q(flex.LRN_SETTINGS))
_CORRL_HEAD = _head(flex.corrl_q(1))
_FORMAT_HEAD = _head(flex.fmt(1, 1))
_EXECUTE = flex.XE


def _query_kind(command: str) -> tuple[FixtureKind, Parser] | None:
    """The fixture kind and parser of a query command (``None``: no fixture kind)."""
    head, arguments = _head(command), _arguments(command)
    if head == _LRN_HEAD:
        return _LRN_KINDS.get(int(arguments)) if arguments.isdigit() else None
    if head == _CORRL_HEAD:  # CORRL? ch: the list's length; CORRL? ch,index: one listed frequency (PG PDF 385)
        return "corrl", ((lambda t: {"frequency_hz": parse_corrl_frequency(t)}) if "," in arguments
                         else (lambda t: {"count": parse_corrl_count(t)}))
    return _QUERIES.get(head)


def parse_exchange(command: str, response: str, *, fmt: int | None = None) -> CapturedExchange | None:
    """One answer as a fixture exchange (module docstring); ``fmt`` (1 or 5) marks a measurement data block."""
    if fmt is not None:
        kind: FixtureKind = "fmt1" if fmt == 1 else "fmt5"
        terminator = "crlf" if fmt == 1 else "comma"
        body = response.rstrip("\r\n")
        try:
            points = [f"{p.raw[0]} {p.raw[1]} {p.raw[2]} {p.raw[3:]}" for p in parse_data(body, fmt)]
        except (FlexParseError, ValueError) as exc:
            return CapturedExchange(kind=kind, command=command, response=body, terminator=terminator,
                                    problem=str(exc))
        return CapturedExchange(kind=kind, command=command, response=body, terminator=terminator, points=points)
    entry = _query_kind(command)
    if entry is None:
        return None
    kind, parse = entry
    body = response.rstrip("\r\n")
    try:
        expect = parse(body)
    except (FlexParseError, ValueError) as exc:
        return CapturedExchange(kind=kind, command=command.strip(), response=body, problem=str(exc))
    return CapturedExchange(kind=kind, command=command.strip(), response=body, expect=expect)


def _format_of(command: str) -> int | None:
    try:
        return int(_arguments(command).split(",")[0])
    except ValueError:
        return None


BUS_TIMING = "bus_call_s"
QUERY_TIMINGS: dict[str, str] = {_head(flex.TST_Q): "tst_s", _head(flex.CAL_Q): "cal_s",
                                 _head(flex.adj_q(1, flex.ADJ_MEASURE)): "adj_s",
                                 _head(flex.corr_q(1, "open")): "corr_s"}
LIBRARY_TIMINGS: dict[str, str] = {C_FUNCTIONS["self_test"][0]: "wgfmu_self_test_s",
                                   C_FUNCTIONS["self_calibration"][0]: "wgfmu_self_cal_s",
                                   C_FUNCTIONS["dc_measure_value"][0]: "wgfmu_dc_read_s"}
READBACK_TIMING = "wgfmu_readback_s_per_value"
"""Record field names of the audit timings (module docstring), in seconds."""
_BUS_EVENTS = frozenset({"bus_open", "bus_lock", "bus_unlock", "bus_close"})
_READBACK_FUNCTION = C_FUNCTIONS["measure_values"][0]
_WARNINGS_FUNCTION = C_FUNCTIONS["warnings"][0]
_READ_COUNT = re.compile(r"^n=(\d+)$")
_EXCEPTION_PREFIX = re.compile(r"^[A-Za-z_]\w*(?:Error|Exception|Refused|Failed)\w*: ")
_WARNING_COUNT = re.compile(r"^(?P<count>\d+) warning\(s\)(?:: (?P<lines>.*))?$", re.DOTALL)


def wgfmu_exchange(event: AuditEvent) -> CapturedExchange | None:
    """A WGFMU library string of one ``wgfmu_call`` audit event as a fixture exchange: the error text of a failed
    call (``wgfmu_error``: ``rc`` and the firmware ``code`` the wrapper recorded) or a non-empty warning summary
    (``wgfmu_warnings``: count and lines as the audit renders them); ``None`` otherwise."""
    if event.ev != "wgfmu_call" or not event.cmd:
        return None
    data = event.data or {}
    if event.error:
        rc, function = data.get("rc"), data.get("fn")
        text = _EXCEPTION_PREFIX.sub("", event.error, count=1)  # the audit writes "<exception>: <fn>: <library text>"
        text = text.removeprefix(f"{function}: ") if isinstance(function, str) else text
        return CapturedExchange(kind="wgfmu_error", command=event.cmd, response=text,
                                expect={"function": function, "rc": rc, "code": data.get("code", rc)})
    if event.cmd == _WARNINGS_FUNCTION and event.resp:
        match = _WARNING_COUNT.match(event.resp)
        if match is None:
            return CapturedExchange(kind="wgfmu_warnings", command=event.cmd, response=event.resp,
                                    problem="the warning summary is not '<n> warning(s): line | line'")
        if int(match["count"]) == 0:
            return None
        lines = match["lines"].split(" | ") if match["lines"] else []
        return CapturedExchange(kind="wgfmu_warnings", command=event.cmd, response=event.resp,
                                expect={"count": int(match["count"]), "lines": lines})
    return None


@dataclasses.dataclass
class _Timings:
    """The slowest call per timing name, and the readback time and values (``audit_facts``)."""

    slowest: dict[str, float] = dataclasses.field(default_factory=dict)
    readback_s: float = 0.0
    readback_values: int = 0

    def add(self, name: str, seconds: float) -> None:
        self.slowest[name] = max(seconds, self.slowest.get(name, 0.0))

    def event(self, event: AuditEvent) -> None:
        if event.dur_ms is None:
            return
        seconds = event.dur_ms / 1e3
        if event.ev in _BUS_EVENTS:
            self.add(BUS_TIMING, seconds)
        elif event.ev == "query" and event.cmd and _head(event.cmd) in QUERY_TIMINGS:
            self.add(QUERY_TIMINGS[_head(event.cmd)], seconds)
        elif event.ev == "wgfmu_call" and event.cmd and not event.error:
            if event.cmd in LIBRARY_TIMINGS:
                self.add(LIBRARY_TIMINGS[event.cmd], seconds)
            elif event.cmd == _READBACK_FUNCTION and (match := _READ_COUNT.match(event.resp or "")):
                self.readback_s += seconds
                self.readback_values += int(match[1])

    def result(self) -> dict[str, float]:
        found = dict(self.slowest)
        if self.readback_values:
            found[READBACK_TIMING] = self.readback_s / self.readback_values
        return found


def audit_facts(folder: Path) -> tuple[list[CapturedExchange], dict[str, float]]:
    """The instrument answers and the timings of a run's ``audit.jsonl``: every query with a fixture kind, every data
    block (``raw/block-NNN.txt``) read in format 1 or 5 with the setting commands since the last format command, every
    WGFMU library string (``wgfmu_exchange``); the timings of the module docstring."""
    path = folder / AUDIT_FILE
    if not path.is_file():
        return [], {}
    exchanges: list[CapturedExchange] = []
    timings = _Timings()
    setup: list[str] = []
    fmt: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = AuditEvent.from_json_line(line)
        except (ValueError, ValidationError):
            continue
        timings.event(event)
        if event.ev == "write" and event.cmd:
            if _head(event.cmd) == _FORMAT_HEAD:
                fmt, setup = _format_of(event.cmd), []
            setup.append(event.cmd)
        elif event.ev == "query" and event.cmd and event.resp is not None:
            exchange = parse_exchange(event.cmd, event.resp)
            if exchange is not None:
                exchanges.append(exchange)
        elif event.ev == "wgfmu_call":
            library = wgfmu_exchange(event)
            if library is not None:
                exchanges.append(library)
        elif event.ev == "data_block" and event.data and isinstance(event.data.get("file"), str):
            if fmt not in (1, 5):
                continue
            raw = folder / str(event.data["file"])
            try:
                text = raw.read_bytes().decode("latin-1")
            except OSError:
                continue
            command = "; ".join(setup if _EXECUTE in setup else [*setup, _EXECUTE])
            data = parse_exchange(command, text, fmt=fmt)
            if data is not None:
                exchanges.append(data)
    return exchanges, timings.result()


def audit_exchanges(folder: Path) -> list[CapturedExchange]:
    """The instrument answers of a run's ``audit.jsonl`` (``audit_facts`` without the timings)."""
    return audit_facts(folder)[0]


def run_facts(bundle: ConfigBundle, run_id: str) -> RunFacts:
    """Facts of a finished run (module docstring). Raises ``RunNotFoundError``/``InvalidInputError`` (run id) or
    ``RunFormatError`` (a manifest that does not validate, e.g. a hardware id with a simulator backend)."""
    folder = RunStore(bundle.paths.runs_dir).open(run_id)
    manifest = load_manifest(folder.path)
    analyses: list[ExtractionResult] = []
    for file in sorted((folder.path / ANALYSIS_DIR).glob("*.json")):
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
            analyses += [ExtractionResult.model_validate(r) for r in payload.get("results") or []]
        except (OSError, ValueError, ValidationError, AttributeError):
            continue
    quality = None
    if (folder.path / QUALITY_FILE).is_file():
        try:
            quality = QualityReport.model_validate_json((folder.path / QUALITY_FILE).read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            quality = None
    changed = []
    for rel, digest in sorted(manifest.files.items()):
        target = folder.path / rel
        if rel != MANIFEST_FILE and (not target.is_file() or sha256_file(target) != digest):
            changed.append(rel)
    exchanges, timings = audit_facts(folder.path)
    return RunFacts(manifest=manifest, folder=bundle.paths.display(folder.path), analyses=analyses, quality=quality,
                    exchanges=exchanges, timings=timings, changed_files=changed)


def probe_path(bundle: ConfigBundle, ref: str) -> Path:
    """The probe record ``ref`` names: ``probe``/``latest`` (newest ``work/bringup/probe-*.json``), a file name in
    ``work/bringup/`` or a path. Raises ``InvalidInputError`` when there is none."""
    folder = bundle.paths.work_dir / BRINGUP_WORK_DIR
    if ref in LATEST_PROBE:
        found = sorted(folder.glob(PROBE_GLOB)) if folder.is_dir() else []
        if not found:
            raise InvalidInputError(f"no probe record in {bundle.paths.display(folder)}; run b1500 doctor --probe "
                                    "first")
        return found[-1]
    candidates = [Path(ref), bundle.paths.repo_root / ref, folder / ref, folder / f"{ref}.json"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise InvalidInputError(f"no probe record {ref!r} (give probe, latest, a probe-<UTC>.json name or a path)")


def probe_facts(bundle: ConfigBundle, ref: str) -> ProbeFacts:
    """A probe record with its answers parsed (module docstring)."""
    path = probe_path(bundle, ref)
    try:
        report = ProbeReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise InvalidInputError(f"{bundle.paths.display(path)} is not a probe record: {exc}") from None
    exchanges = []
    for item in report.transcript:
        if item.resp is not None:
            exchange = parse_exchange(item.cmd, item.resp)
            if exchange is not None:
                exchanges.append(exchange)
    library = report.wgfmu_library
    if library is not None and library.file_version:  # the version resource of wgfmu.dll (ATV-15, stage L0)
        name = PureWindowsPath(library.path).name if library.path else "wgfmu.dll"
        exchanges.append(CapturedExchange(kind="wgfmu_version", command=f"file version resource of {name}",
                                          response=library.file_version,
                                          expect={"machine": library.machine, "file_version": library.file_version}))
    return ProbeFacts(path=bundle.paths.display(path), report=report, exchanges=exchanges)


def recipe_facts(svc: B1500Service, bundle: ConfigBundle, recipe_id: str) -> RecipeFacts:
    """The current recipe file of ``recipe_id`` (raises ``UnknownRecipeError``)."""
    recipe = svc.executor.registry(bundle).get(recipe_id)
    return RecipeFacts(recipe_id=recipe_id, version=recipe.version, file_sha256=recipe.sha256,
                       definition_sha256=recipe_definition_sha256(recipe), status=recipe.status)
