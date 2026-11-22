"""MFCMU correction store (blueprint v2 2.6, decision 11): ``<state_dir>/corrections/<cmu_alias>.json``.

Each file is a JSON array of ``CorrectionRecord`` objects (``models/station.py``), oldest first, written only by the
server: the executor appends a record after a successful correction run (phase compensation ``ADJ``, open/short/load
data correction; the ``cmu_correction`` kind) and discards the records of corrections the instrument no longer holds
(``discard``; ``clear`` after a device clear, which initializes the instrument like ``*RST``; WP8.2,
``catalog/corrections.py``). Nobody edits these files by hand; a correction is renewed by running
the correction recipe again. Writes are atomic (temporary file + ``os.replace``), so readers in other processes
never see a half-written file; writers are serialized by the instrument lock (only a run writes records). Each kind
keeps its newest ``MAX_RECORDS_PER_KIND`` records.

Queries:

- ``records_for(cmu_alias)``: the stored records of one MFCMU (``[]`` when there are none) - the plain provider
  that rule R-CORR-01 and ``station_status`` wrap;
- ``freshness(cmu_alias, records, require=..., max_age_h=..., now=..., freqs_hz=..., idn=..., pin_map_sha=...,
  station_sha=...)``: for each required kind, whether a usable record exists. The checks run in R-CORR-01's order
  and stop at the first that leaves no record: ``missing`` (no record of the kind) → ``other_setup`` (the station
  profile or pin map hash differs; only checked when given) → ``other_instrument`` (the mainframe ``*IDN?``
  differs; only when given) → ``stale`` (older than ``max_age_h`` at ``now``) → ``uncovered`` (no fresh record of a
  data-correction kind lists every plan frequency, as R-CORR-01 asks: one correction run must cover the whole plan;
  ``missing_hz`` = the frequencies the newest fresh record lacks; phase compensation covers every frequency) →
  ``fresh`` (the newest record that passes every check decides ``run_id``/``age_h``).
  ``freshness_for`` applies a ``CorrectionPolicy`` (``policy.corrections``) to the stored records.

A corrupt file raises ``CorrectionStoreError`` (code ``invalid_input``) naming the file; it is never read as "no
records", so a broken store cannot hide a correction problem (R-CORR-01 then blocks with the error message).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from b1500_test_agent.analysis.dataset import default_paths
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.common import Alias
from b1500_test_agent.models.policy import CorrectionPolicy
from b1500_test_agent.models.station import (
    CorrectionCheck,
    CorrectionFreshness,
    CorrectionKind,
    CorrectionRecord,
    CorrectionState,
)
from b1500_test_agent.session.lock import atomic_write_json

CORRECTIONS_DIR = "corrections"
MAX_RECORDS_PER_KIND = 20
"""Records kept per correction kind and MFCMU (the oldest are dropped when a new one is added)."""

_ALIAS = TypeAdapter(Alias)
_RECORDS = TypeAdapter(list[CorrectionRecord])


class CorrectionStoreError(InvalidInputError):
    """A correction-store file cannot be read or does not hold a list of correction records."""


def corrections_dir(state_dir: Path) -> Path:
    """``<state_dir>/corrections``."""
    return Path(state_dir) / CORRECTIONS_DIR


def _check_alias(cmu_alias: str) -> str:
    try:
        return _ALIAS.validate_python(cmu_alias)
    except ValidationError:
        raise InvalidInputError(f"{cmu_alias!r} is not an MFCMU alias (a letter, then letters, digits, '_' or '-', "
                                "at most 32 characters).") from None


class CorrectionStore:
    """The correction records under ``<state_dir>/corrections/`` (see the module docstring)."""

    def __init__(self, state_dir: Path) -> None:
        self.directory = corrections_dir(state_dir)

    def path(self, cmu_alias: str) -> Path:
        """``<state_dir>/corrections/<cmu_alias>.json`` (the alias is validated: no path tricks)."""
        return self.directory / f"{_check_alias(cmu_alias)}.json"

    def aliases(self) -> list[str]:
        """MFCMU aliases that have a store file, sorted."""
        if not self.directory.is_dir():
            return []
        return sorted(p.stem for p in self.directory.glob("*.json") if p.is_file())

    def records(self, cmu_alias: str) -> list[CorrectionRecord]:
        """The stored records of ``cmu_alias``, oldest first (``[]`` without a file). Raises
        ``CorrectionStoreError`` for a corrupt file."""
        path = self.path(cmu_alias)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records = _RECORDS.validate_python(data)
        except (OSError, ValueError) as exc:
            raise CorrectionStoreError(f"correction store {path.name} is unreadable ({exc}); run the correction "
                                       "recipes again, never edit the file") from exc
        return sorted(records, key=lambda r: r.ts)

    def all(self) -> dict[str, list[CorrectionRecord]]:
        """Records of every MFCMU with a store file, by alias."""
        return {alias: self.records(alias) for alias in self.aliases()}

    def add(self, cmu_alias: str, record: CorrectionRecord) -> list[CorrectionRecord]:
        """Append ``record`` (atomic rewrite of the file; the newest ``MAX_RECORDS_PER_KIND`` of each kind are
        kept) and return the stored list."""
        records = sorted([*self.records(cmu_alias), record], key=lambda r: r.ts)
        kept: list[CorrectionRecord] = []
        for kind in sorted({r.kind for r in records}):
            kept.extend([r for r in records if r.kind == kind][-MAX_RECORDS_PER_KIND:])
        kept.sort(key=lambda r: r.ts)
        atomic_write_json(self.path(cmu_alias), [r.model_dump(mode="json") for r in kept])
        return kept

    def discard(self, cmu_alias: str, kinds: Iterable[CorrectionKind]) -> int:
        """Remove the records of ``kinds`` (the instrument no longer holds those corrections: ``CORRST?`` off, phase
        compensation not in effect, or data cleared by a rewritten correction set-up; WP8.2) and return how many were
        removed; the file is rewritten only when something was removed (deleted when nothing is left)."""
        drop = set(kinds)
        records = self.records(cmu_alias)
        kept = [r for r in records if r.kind not in drop]
        if len(kept) == len(records):
            return 0
        if kept:
            atomic_write_json(self.path(cmu_alias), [r.model_dump(mode="json") for r in kept])
        else:
            with contextlib.suppress(FileNotFoundError):
                self.path(cmu_alias).unlink()
        return len(records) - len(kept)

    def clear(self, cmu_alias: str) -> int:
        """Remove every record of ``cmu_alias`` (e.g. after a ``*RST`` lost the corrections; also a corrupt file);
        returns how many readable records there were."""
        try:
            count = len(self.records(cmu_alias))
        except CorrectionStoreError:
            count = 0  # a corrupt file is removed as well
        with contextlib.suppress(FileNotFoundError):
            self.path(cmu_alias).unlink()
        return count

    def freshness(self, cmu_alias: str, policy: CorrectionPolicy, *, now: datetime,
                  freqs_hz: Sequence[float] = (), idn: str | None = None, pin_map_sha: str | None = None,
                  station_sha: str | None = None) -> CorrectionFreshness:
        """``freshness`` of the stored records under ``policy`` (``require``, ``max_age_h``)."""
        return freshness(cmu_alias, self.records(cmu_alias), require=policy.require, max_age_h=policy.max_age_h,
                         now=now, freqs_hz=freqs_hz, idn=idn, pin_map_sha=pin_map_sha, station_sha=station_sha)


def _store(state_dir: Path | None) -> CorrectionStore:
    return CorrectionStore(state_dir if state_dir is not None else default_paths().state_dir)


def records_for(cmu_alias: str, *, state_dir: Path | None = None) -> list[CorrectionRecord]:
    """The stored correction records of MFCMU ``cmu_alias``, oldest first (``[]`` when there are none).
    ``state_dir`` defaults to the configured ``<data_root>/state``. Raises ``CorrectionStoreError``."""
    return _store(state_dir).records(cmu_alias)


def add_record(cmu_alias: str, record: CorrectionRecord, *, state_dir: Path | None = None) -> list[CorrectionRecord]:
    """Append ``record`` to the store of ``cmu_alias`` (``CorrectionStore.add``)."""
    return _store(state_dir).add(cmu_alias, record)


def freshness_for(cmu_alias: str, policy: CorrectionPolicy, *, now: datetime, freqs_hz: Sequence[float] = (),
                  idn: str | None = None, pin_map_sha: str | None = None, station_sha: str | None = None,
                  state_dir: Path | None = None) -> CorrectionFreshness:
    """``freshness`` of the stored records of ``cmu_alias`` under ``policy`` (``policy.corrections``)."""
    return _store(state_dir).freshness(cmu_alias, policy, now=now, freqs_hz=freqs_hz, idn=idn,
                                       pin_map_sha=pin_map_sha, station_sha=station_sha)


def _newest(records: Iterable[CorrectionRecord]) -> CorrectionRecord | None:
    return max(records, key=lambda r: r.ts, default=None)


def _check(kind: CorrectionKind, records: list[CorrectionRecord], *, max_age_h: float, now: datetime,
           freqs: list[float], idn: str | None, pin_map_sha: str | None, station_sha: str | None) -> CorrectionCheck:
    def result(state: CorrectionState, deciding: CorrectionRecord | None,
               missing_hz: Sequence[float] = ()) -> CorrectionCheck:
        if deciding is None:
            return CorrectionCheck(kind=kind, state=state)
        return CorrectionCheck(kind=kind, state=state, run_id=deciding.run_id, age_h=round(deciding.age_h(now), 6),
                               missing_hz=list(missing_hz))

    matching = [r for r in records if r.kind == kind]
    if not matching:
        return result("missing", None)
    setup = [r for r in matching if (station_sha is None or r.station_sha == station_sha)
             and (pin_map_sha is None or r.pin_map_sha == pin_map_sha)]
    if not setup:
        return result("other_setup", None)
    same_idn = [r for r in setup if idn is None or r.idn == idn]
    if not same_idn:
        return result("other_instrument", None)
    fresh = [r for r in same_idn if r.age_h(now) <= max_age_h]
    if not fresh:
        return result("stale", _newest(same_idn))
    covering = [r for r in fresh if r.covers(freqs)]
    if not covering:
        best = _newest(fresh)
        assert best is not None
        return result("uncovered", best, [f for f in freqs if not best.covers([f])])
    return result("fresh", _newest(covering))


def freshness(cmu_alias: str, records: Sequence[CorrectionRecord], *, require: Sequence[CorrectionKind],
              max_age_h: float, now: datetime, freqs_hz: Sequence[float] = (), idn: str | None = None,
              pin_map_sha: str | None = None, station_sha: str | None = None) -> CorrectionFreshness:
    """For each kind in ``require``: is there a usable correction record of MFCMU ``cmu_alias`` (module
    docstring)? ``pin_map_sha``/``station_sha``/``idn`` restrict the records when given; ``freqs_hz`` are the plan
    frequencies every data correction must cover (none: coverage is not checked)."""
    alias = _check_alias(cmu_alias)
    freqs = sorted({float(f) for f in freqs_hz})
    checks = [_check(kind, list(records), max_age_h=max_age_h, now=now, freqs=freqs, idn=idn,
                     pin_map_sha=pin_map_sha, station_sha=station_sha) for kind in dict.fromkeys(require)]
    return CorrectionFreshness(cmu=alias, checked_at=now, max_age_h=max_age_h, freqs_hz=freqs, checks=checks,
                               fresh=all(c.state == "fresh" for c in checks))
