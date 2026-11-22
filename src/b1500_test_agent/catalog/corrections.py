"""Correction-store wiring of the executor (blueprint v2 0 #11, 2.6 "correction store", 2.8 R-CORR-01; WP8.2).

The correction store (``archive/corrections.py``) must describe what the MFCMU really holds, so the executor keeps it
in step with the instrument at three moments, all inside the run's own transaction or right after it:

1. **Before execution** of every plan that uses an MFCMU (``read_live_corrections``): the pre-execute snapshot gets
   ``LiveState.cmu_corrections`` from ``CmuOps.correction_state`` (``CORRST?`` per correction, ``ADJ? ch,0`` and
   ``*LRN? 90``; queries only) for each MFCMU the plan binds, which R-CORR-01's live part checks. Records of
   corrections the instrument no longer holds (``CORRST?`` off, phase compensation not in effect: a ``*RST``, a
   device clear, a power cycle or another program) are discarded right away (``reconcile``), so the next
   ``validate_plan`` already blocks with "no record" and ``station_status`` shows them missing.
2. **After a correction run** (``record_run``): the same reconciliation from the state the run read back
   (``kind_result`` ``after_*``; a phase compensation switched the data corrections off, a rewritten correction
   set-up cleared their data), then, when the run completed, one ``CorrectionRecord`` (kind, frequencies, run id,
   time, ``*IDN?``, pin-map and station sha256, ``CORRST?`` answers).
3. **After any run whose cleanup sent a device clear** (``record_run``): a device clear initializes the instrument
   like ``*RST`` (PG p175 (2-87)), which switches every correction off, so every MFCMU's records are cleared.

Each change returns notes; the executor flags the run with them (``completed_with_flags``) and audits them, so the
agent learns which correction to renew (card ``cmu/cmu-correction``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from b1500_test_agent.archive.corrections import CorrectionStore
from b1500_test_agent.catalog.kinds.cmu_correction import DATA_CORRECTIONS, live_after
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.run import CleanupReport
from b1500_test_agent.models.station import (
    CmuCorrectionLive,
    CorrectionKind,
    CorrectionRecord,
    LiveState,
    StationProfile,
)
from b1500_test_agent.rules.builtin.cmu import CORRECTION_CARD, CORRECTION_RECIPES

CORRECTION_KIND = "cmu_correction"


def plan_mfcmus(plan: PlanRecord) -> dict[str, int]:
    """``{alias: channel}`` of the MFCMUs the plan's roles are bound to (alias ``CH<n>`` when the station names
    none, as in R-CORR-01 and the store)."""
    found: dict[str, int] = {}
    for bound in plan.binding.roles.values():
        if bound.module_type == "MFCMU" and bound.channel is not None:
            found.setdefault(bound.alias or f"CH{bound.channel}", bound.channel)
    return found


def station_mfcmus(station: StationProfile) -> list[str]:
    """Aliases of every MFCMU of the station profile (``CH<n>`` without one)."""
    return [m.alias or f"CH{m.channels[0]}" for m in station.modules if m.type == "MFCMU"]


def lost_kinds(live: CmuCorrectionLive) -> list[CorrectionKind]:
    """The correction kinds ``live`` reports as not in effect (unknown states are not counted)."""
    kinds: list[CorrectionKind] = ["phase"] if live.phase is False else []
    kinds += [k for k in DATA_CORRECTIONS if live.corr_state.get(k) is False]
    return kinds


@dataclass
class CorrectionChanges:
    """What the executor changed in the correction store: discarded kinds per MFCMU, MFCMUs cleared after a device
    clear, the record added (and the store file it went to) and the notes for the run."""

    discarded: dict[str, list[str]] = field(default_factory=dict)
    cleared: list[str] = field(default_factory=list)
    record: CorrectionRecord | None = None
    path: Path | None = None
    notes: list[str] = field(default_factory=list)

    def audit(self) -> dict[str, str | None]:
        """Scalar audit payload (``checkpoint`` ``corrections``)."""
        return {"discarded": "; ".join(f"{a}: {', '.join(k)}" for a, k in self.discarded.items()) or None,
                "cleared": ", ".join(self.cleared) or None,
                "record": f"{self.record.kind} {self.record.run_id}" if self.record is not None else None,
                "notes": " | ".join(self.notes)[:500] or None}

    @property
    def changed(self) -> bool:
        return bool(self.discarded or self.cleared or self.record is not None or self.notes)


def reconcile(store: CorrectionStore, alias: str, live: CmuCorrectionLive) -> list[str]:
    """Discard the records of ``alias`` whose correction ``live`` reports as not in effect; returns the kinds that had
    records and lost them (sorted in ``phase, open, short, load`` order)."""
    lost = lost_kinds(live)
    if not lost:
        return []
    present = {r.kind for r in store.records(alias)}
    removed = [k for k in lost if k in present]
    if removed:
        store.discard(alias, removed)
    return removed


def _lost_note(alias: str, kinds: list[str], why: str) -> str:
    recipes = ", ".join(CORRECTION_RECIPES[k] for k in kinds)
    return (f"MFCMU {alias}: the {', '.join(kinds)} correction record(s) were discarded ({why}); run {recipes} again "
            f"before the next capacitance measurement (card {CORRECTION_CARD})")


def read_live_corrections(driver: B1500Driver, plan: PlanRecord, live: LiveState,
                          store: CorrectionStore) -> tuple[LiveState, CorrectionChanges]:
    """Step 1 of the module docstring: ``live`` with ``cmu_corrections`` for the plan's MFCMUs (unchanged for plans
    without one) and the store reconciled. An MFCMU whose state cannot be read stays out of ``cmu_corrections`` (the
    rule then blocks: "not read"); a link error propagates (the run fails with its cleanup)."""
    changes = CorrectionChanges()
    channels = plan_mfcmus(plan)
    if not channels:
        return live, changes
    states: dict[str, CmuCorrectionLive] = {}
    for alias, channel in sorted(channels.items()):
        try:
            states[alias] = driver.correction_state(channel)
        except DriverError as exc:
            changes.notes.append(f"MFCMU {alias}: correction state unreadable ({exc})")
            continue
        try:
            removed = reconcile(store, alias, states[alias])
        except B1500Error as exc:
            changes.notes.append(f"MFCMU {alias}: correction store not updated ({exc})")
            continue
        if removed:
            changes.discarded[alias] = removed
            changes.notes.append(_lost_note(alias, removed, "the instrument no longer holds them: CORRST?/ADJ? read "
                                                            "before this run"))
    return live.model_copy(update={"cmu_corrections": states}), changes


def record_run(store: CorrectionStore, *, plan: PlanRecord, raw: RawAcquisition | None, live: LiveState | None,
               cleanup: CleanupReport | None, completed: bool, run_id: str, now: datetime,
               station: StationProfile) -> CorrectionChanges:
    """Steps 2 and 3 of the module docstring after a run's transaction; ``completed`` = the run acquired without an
    error and the kind reported success. Store problems become notes (never an exception: the run is already
    archived)."""
    changes = CorrectionChanges()
    try:
        if plan.kind == CORRECTION_KIND and raw is not None:
            _correction_run(store, changes, plan=plan, raw=raw, live=live, completed=completed, run_id=run_id,
                            now=now)
        if cleanup is not None and any(step.step == "device_clear" for step in cleanup.steps):
            for alias in station_mfcmus(station):
                if store.clear(alias):
                    changes.cleared.append(alias)
            if changes.cleared:
                changes.record = None
                changes.notes.append(f"a device clear in the cleanup initialized the instrument (PG p175 (2-87)), "
                                     f"which switches the MFCMU corrections off: the correction records of "
                                     f"{', '.join(changes.cleared)} were cleared; run the corrections again (card "
                                     f"{CORRECTION_CARD})")
    except B1500Error as exc:
        changes.notes.append(f"correction store not updated: {exc}")
    return changes


def _correction_run(store: CorrectionStore, changes: CorrectionChanges, *, plan: PlanRecord, raw: RawAcquisition,
                    live: LiveState | None, completed: bool, run_id: str, now: datetime) -> None:
    program = plan.program
    alias, kind = program.get("alias"), program.get("correction")
    if not isinstance(alias, str) or kind not in CORRECTION_RECIPES:
        return
    after = live_after(dict(raw.kind_result))
    if after is not None:
        removed = [k for k in reconcile(store, alias, after) if k != kind]
        if removed:
            changes.discarded[alias] = removed
            why = ("a new phase compensation invalidates the data corrections measured with the old one, so the run "
                   "switched them off" if kind == "phase" else
                   "the run rewrote the correction frequency list or standards, which clears every correction's data")
            changes.notes.append(_lost_note(alias, removed, why))
    if not completed or after is None:
        return
    identity = live.identity if live is not None else None
    station_sha, pin_map_sha = plan.hashes.get("station"), plan.hashes.get("pin_map")
    if identity is None or station_sha is None or pin_map_sha is None:
        changes.notes.append(f"MFCMU {alias}: no correction record written (instrument identity or config hashes "
                             "unknown)")
        return
    freqs = program.get("freqs_hz") if kind != "phase" else []
    record = CorrectionRecord(
        kind=kind, freqs_hz=[float(f) for f in freqs] if isinstance(freqs, list) else [],  # type: ignore[arg-type]
        run_id=run_id, ts=now, idn=identity.raw.strip(), pin_map_sha=pin_map_sha, station_sha=station_sha,
        corr_state=dict(after.corr_state))
    store.add(alias, record)
    changes.record = record
    changes.path = store.path(alias)
