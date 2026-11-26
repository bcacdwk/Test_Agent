---
id: errx-codes
title: Instrument error codes (ERRX? queue)
maturity: seed
sources: [Programming Guide Ed. 15 chapter 5 (PDF 574-616), PG p583 (5-11) "Excess current in HPSMU", PG p587-601 (5-15) operation errors, PG p602 (5-30) "Self-test/Calibration Error", references/manuals/structured/b1500a-error-codes.yaml]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Instrument error codes

## Symptom

- `station_status` lists instrument errors (code and message, sometimes ending in `; SLOTn`).
- A run ends `failed` with `instrument_error`: the recipe drains the queue after connecting and after setup and
  aborts before the measurement on any entry.
- `validate_plan` or a run reports a warning that earlier queue entries were drained and recorded.

## Likely causes

Look the code up in `references/manuals/structured/b1500a-error-codes.yaml` (partial extract; the Programming
Guide chapter 5 is complete). Typical groups:

| Code | Meaning | Usual cause, next runbook |
|---|---|---|
| 100-199 | Command syntax or parameter rejected (100 undefined command, 120 bad value, 150 input buffer full) | Driver bug or firmware mismatch: report with run_id; never resend commands by hand |
| 152, 153 | Module failed self-test or calibration; no module in that slot | Station profile vs installed modules: human |
| 200, 201 | Output switch not on; compliance not set | Recipe or driver sequence: report |
| 202, 203 | Interlock must be closed; cannot enable channel | [interlock-open](interlock-open.md) |
| 227 | Sweep aborted (compliance, overflow, oscillation, power compliance) | [compliance-hit](compliance-hit.md) |
| 260 | Data output buffer full | Too many points not read: report |
| 301 | Line power failure | Hardware: stop |
| 303, 304, 305, 320 | Excess voltage in an MPSMU or excess current in an HPSMU (all output switches set off); ground unit abuse; excess current in the CMU (its output switch set off) (PG p583 (5-11)) | Hardware or DUT short: stop |
| 310 | Interlock opened in a high-voltage state; instrument initialized | [interlock-open](interlock-open.md); stop |
| 600-699 | Incompatible measurement settings | Recipe or kind bug: report |
| 7xx, and codes prefixed with the slot number N (1760 = slot 1) | Self-test or calibration failure (PG p602-616 (5-30)) | Human; service may be needed |
| 9xx, 1xxx, 3xxx, 5xxx, 6xxx | Other operation errors: expanders and DIO modes, HCSMU/MCSMU, SPGU ALWG data (PG p587-601 (5-15)) | Look the code up; hardware-side: stop |

Codes 400-599 are not documented in the manual.

## First safe checks

1. `station_status`: is the error still in the queue now, which slot, is a fault latched?
2. `get_run(run_id, include=[summary, audit])`: the audit shows when the error appeared (baseline, setup,
   measurement, cleanup) and the command sent just before it.
3. An error that was already in the queue before the run (drained at the start) is history, not this run's cause;
   record it in the case note.
4. Software-side codes (100-299 except 202/203/227, 600-699): report the code, message, run_id and the audit
   excerpt. Re-running the same plan reproduces the same error.

## Physical checks to ask the human

- Front panel or EasyEXPERT status: does the instrument show the same error?
- After a hardware code: power, module LEDs, cables at the named slot.
- Self-test or calibration codes: run a self-test only with the human (recipe `system.self_test`, always
  confirmed) and only after they agree.

## Do not

- Send raw FLEX commands, `*RST` or a device clear to "clear" the queue; never use the sim console on hardware.
- Treat a drained error as gone: it is recorded in the audit and belongs in the report.
- Re-run a plan that failed with a hardware code.

## Stop and call safe_shutdown

- Any code from 300-399, any self-test or calibration code, 202, 203 or 310.
- The same software-side code twice: stop and report it as a bug.
