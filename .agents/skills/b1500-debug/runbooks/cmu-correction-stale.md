---
id: cmu-correction-stale
title: MFCMU corrections missing, stale or lost (R-CORR-01)
maturity: seed
sources: [blueprint v2 0 (decision 11), blueprint v2 2.8 (R-CORR-01), Programming Guide Ed. 15 PDF 175, 251, 382-389]
---

# MFCMU corrections missing, stale or lost

## Symptom

- `validate_plan` of a capacitance recipe is `blocked` by R-CORR-01: "no phase/open/short correction record", "is
  N h old", "measured with another station profile or pin map", "does not cover F Hz" or "another mainframe".
- A run is `refused` before execution: "CORRST? reports the open correction off", "phase compensation data are no
  longer in effect".
- A correction run ends `completed_with_flags`: "record(s) were discarded".
- `station_status.corrections` reads `not fresh: ...`; C-V data offset by a fraction of a pF or with a phase tilt.

## Likely causes

1. Never measured in this data folder, or older than `policy.corrections.max_age_h` (default 8 h).
2. Measured with another pin map or station profile (a re-landing or a config change makes them stale on purpose).
3. A frequency of the plan is not in the correction list (corrections act only at listed frequencies).
4. The instrument lost them: `*RST`, a device clear (also the cleanup's retry after an error), a power cycle, or
   another program (EasyEXPERT) changed the list or standards (PG PDF 175, 388).
5. A new phase compensation, or a correction run with another frequency list, invalidated the others (by design).

## First safe checks

1. `station_status`: `corrections` per MFCMU (kind, state, age); `identity` vs the record's mainframe.
2. Read the blocking finding: which kind, which frequency, which pin map; compare with the plan request.
3. `list_runs(recipe_id="cmu.*")` and `get_run(run_id, include=[summary, audit])` of the last correction runs:
   `setup kept|rewritten`, `after_*` read-back, discarded records.
4. Plan the renewal with card `cmu-correction` (skill `b1500-test`): same pin map as the measurement, `freqs_hz`
   covering every measurement frequency, same AC level; order phase, open, short (load).

## Physical checks to ask the human

- Were the probes or cables moved, re-landed or swapped since the corrections? (Then renew them.)
- Was the instrument restarted, reset, or used from EasyEXPERT in between?
- For each correction: are the probes really lifted (open), on a short, or on the load standard, and kept there
  until the run ends?

## Do not

- Raise `max_age_h`, drop a kind from `corrections.require`, edit `data/state/corrections/*.json` or the station
  profile to get past R-CORR-01: only fresh corrections fix it.
- Run a correction without the human's own confirmation of the physical state, or with the probes on the DUT.
- Report capacitance from an uncorrected run as corrected.

## Stop and call safe_shutdown

- A correction or phase compensation fails twice (result 1/2) with the human confirming the physical state.
- Errors 680-685 persist, a fault is latched or the cleanup is unverified (runbook `cleanup-failed-fault`).
