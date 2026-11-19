"""Read-only evidence of archived runs and probe records for ``b1500 bringup capture | record`` (blueprint v2 7.1).

The bring-up helpers (``bringup.py``) may import only ``service`` and ``models``; this module is their window on the
archive, the recipe registry and the driver's response parsers. Nothing here talks to the instrument or writes a
file.

- ``run_facts``: the manifest of a finished run, every analysis result in ``analysis/``, ``quality.json``, the
  instrument answers of its ``audit.jsonl`` parsed as golden-fixture exchanges, and the files whose sha256 no longer
  matches the manifest (evidence edited after the run).
- ``probe_facts``: a probe record ``work/bringup/probe-<UTC>.json`` (``probe``/``latest`` = the newest one) with its
  raw answers parsed the same way.
- ``recipe_facts``: the current recipe file's version, raw digest and definition digest
  (``models.validation.recipe_definition_sha256``).
- ``parse_exchange``: one answer → ``CapturedExchange`` (fixture kind from the query mnemonic, ``expect`` in the
  shape the parser tests of ``tests/unit/test_driver_discovery.py`` use, or one point per FMT 1/5 data element). A
  query without a fixture kind gives ``None``; an answer the parser rejects keeps the parser's message in
  ``problem``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from b1500_test_agent.analysis.dataset import MANIFEST_FILE, load_manifest
from b1500_test_agent.archive.store import ANALYSIS_DIR, QUALITY_FILE, RunStore
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.discovery import (
    parse_adj,
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


_QUERIES: dict[str, tuple[FixtureKind, Callable[[str], Any]]] = {
    _head(flex.IDN_Q): ("idn", lambda t: parse_idn(t).model_dump(mode="json", exclude={"raw"})),
    _head(flex.UNT_Q): ("unt", lambda t: {str(m.slot): m.model for m in parse_unt(t).modules}),
    _head(flex.ERRX_Q): ("errx", _errx),
    _head(flex.LOP_Q): ("lop", lambda t: {str(slot): out.state for slot, out in parse_lop(t).items()}),
    _head(flex.STB_Q): ("stb", _stb),
    _head(flex.TST_Q): ("tst", _tst),
    _head(flex.CAL_Q): ("tst", _tst),
    _head(flex.lrn_q(flex.LRN_SETTINGS)): ("lrn", _lrn),
    _head(flex.ERMOD_Q): ("ermod", _ermod),
    _head(flex.erssp_q(0)): ("erssp", lambda t: {"state": parse_erssp(t)}),
    _head(flex.SPST_Q): ("spst", lambda t: {"active": parse_spst(t)}),
    _head(flex.corrst_q(1, "open")): ("corrst", lambda t: {"on": parse_corrst(t)}),
    _head(flex.adj_q(1, flex.ADJ_READ_LAST)): ("adj", lambda t: {"result": parse_adj(t)}),
}
"""Query mnemonic -> (fixture kind, parser giving the fixture's ``expect``); mnemonics come from the FLEX builders."""
_LRN_ARGUMENT = _arguments(flex.lrn_q(flex.LRN_SETTINGS))
_FORMAT_HEAD = _head(flex.fmt(1, 1))
_EXECUTE = flex.XE


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
    head = _head(command)
    entry = _QUERIES.get(head)
    if entry is None or (entry[0] == "lrn" and _arguments(command) != _LRN_ARGUMENT):
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


def audit_exchanges(folder: Path) -> list[CapturedExchange]:
    """The instrument answers of a run's ``audit.jsonl``: every query with a fixture kind, and every data block
    (``raw/block-NNN.txt``) read in format 1 or 5 with the setting commands since the last format command."""
    path = folder / AUDIT_FILE
    if not path.is_file():
        return []
    exchanges: list[CapturedExchange] = []
    setup: list[str] = []
    fmt: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = AuditEvent.from_json_line(line)
        except (ValueError, ValidationError):
            continue
        if event.ev == "write" and event.cmd:
            if _head(event.cmd) == _FORMAT_HEAD:
                fmt, setup = _format_of(event.cmd), []
            setup.append(event.cmd)
        elif event.ev == "query" and event.cmd and event.resp is not None:
            exchange = parse_exchange(event.cmd, event.resp)
            if exchange is not None:
                exchanges.append(exchange)
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
    return exchanges


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        if rel != MANIFEST_FILE and (not target.is_file() or _sha256(target) != digest):
            changed.append(rel)
    return RunFacts(manifest=manifest, folder=bundle.paths.display(folder.path), analyses=analyses, quality=quality,
                    exchanges=audit_exchanges(folder.path), changed_files=changed)


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
    return ProbeFacts(path=bundle.paths.display(path), report=report, exchanges=exchanges)


def recipe_facts(svc: B1500Service, bundle: ConfigBundle, recipe_id: str) -> RecipeFacts:
    """The current recipe file of ``recipe_id`` (raises ``UnknownRecipeError``)."""
    recipe = svc.executor.registry(bundle).get(recipe_id)
    return RecipeFacts(recipe_id=recipe_id, version=recipe.version, file_sha256=recipe.sha256,
                       definition_sha256=recipe_definition_sha256(recipe), status=recipe.status)
