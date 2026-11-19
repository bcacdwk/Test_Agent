---
id: self-test-cal
title: Instrument self-test (*TST?) and self-calibration (*CAL?) — pass/fail and failed units
family: system
intent: [self-test, self-calibration, '*TST?', '*CAL?', module check, recalibrate]
recipes: [system.self_test, system.self_cal]
device_types: []
modules: []
routes: []
bringup_stage: L1
status: sim_validated
confirmation: always
knowledge: [knowledge/02-b1500-instrument.md#self-test-self-calibration-and-auto-calibration, knowledge/02-b1500-instrument.md#status-byte-errors-and-interlock, knowledge/02-b1500-instrument.md#measurement-sequence-and-cleanup]
manual: ['PG p540-541 (4-222) "*TST?"', 'PG p376-377 (4-58) "*CAL?"', PG p377 (4-59) "open the measurement terminals"]
debug: [errx-codes, cleanup-failed-fault]
sources: [blueprint 3.1, blueprint 6.3, deck slide 9]
version: 1
---

# Instrument self-test and self-calibration

## 1. Purpose and applicable devices

Check that the mainframe and every installed module pass the built-in self-test (`system.self_test`, `*TST?`), or
recalibrate them (`system.self_cal`, `*CAL?`): at bring-up, after a module was swapped or reseated, after a large
ambient temperature change, or when the human asks for it. No device is measured.

- Not for: checking a probe landing ([contact-resistor-check](../smu/contact-resistor-check.md)); open-circuit
  offsets of each SMU (zero check, not available yet); the WGFMU library self-test (not available yet).
- Never a "fix" for bad data: the physical and instrument checks of skill `b1500-debug` come first.

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| (none) | no DUT roles | mainframe and every installed module | outputs end in the `CL` state (relays open) |

- The measurement terminals must be open: the human lifts the probes or disconnects the DUT cables first
  (PG p377 (4-59) "open the measurement terminals").
- The request still names a pin map (any existing one, for example `resistor-2t`); it binds nothing. No DUT profile.
- Routes: none in every phase (no switch is driven; selectors stay at rest).

## 3. Pre-run checklist

- `station_status` clean: no fault, no lock holder, no active run, no pending errors.
- Ask the human to open the measurement terminals and to say so in chat; put that in the same message as the
  plan summary you show for confirmation.
- Hardware: both recipes run on visa too; until a reviewed validation record exists every hardware run is also
  `first_hw_run`. Never emulate a self-test with other recipes or raw commands.
- Auto-calibration state: `station_status` (rule R-CAL-01 warns when it is on).

## 4. Recipe and parameters

Each recipe has one fixed parameter; nothing else can be set.

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `operation` (`system.self_test`) | `self_test` | - | `self_test` | fixed by the recipe | `*TST?`: self-test and calibration of all modules |
| `operation` (`system.self_cal`) | `self_cal` | - | `self_cal` | fixed by the recipe | `*CAL?`: self-calibration of all modules |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: system.self_test
params: {}
pin_map: resistor-2t
sim_scenario: resistor_100k
```

## 5. Limits and confirmation

- Always `needs_confirmation`: `system_self_test` or `system_self_cal` (rule R-ALWAYS-01). Show the summary
  verbatim, ask the human to confirm with open terminals, stop the turn; one consent, one run.
- No source command: the compiled envelope is empty, so the output guard refuses any output. No DUT limits apply.
  Destructive: no, but a connected DUT would see the relay switching and calibration signals. No output switch is
  turned on, so the cleanup's `LOP?` check has no positive control in these runs (`cleanup.positive_control` null).
- Duration estimates: self-test about 120 s, self-calibration about 60 s (TODO(verify) at bring-up stage L1).
- On hardware also `first_hw_run` until the recipe is `hw_validated`.

## 6. Quality criteria

- No data table, so no status counts and no quality verdict: the run's `kind_result` carries the result code
  (`0` = pass) and the failed units.
- Any failed unit: report it, do not measure with that module, follow runbook `errx-codes`; the human decides
  about service. Re-run at most once, after the human confirms that the terminals are open.

## 7. Analysis method

No `analyze_run` method applies (no table). Report from `get_run` (include `summary`, `audit`): outcome, result
code, failed units, duration, backend. Never derive measurement offsets from these runs.

## 8. Expected result shape

| operation | typical | red flags |
|---|---|---|
| self-test | result 0, no failed unit, one to two minutes | a non-zero result; a slot listed as failed; a timeout |
| self-calibration | result 0 | a failure on one slot (often a DUT still connected): re-check the open terminals |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| self-test fails on one slot | DUT or cable still connected; module fault | ask the human to open the terminals; one re-run | `errx-codes` |
| run `failed` with instrument errors | error queue, timeout | `station_status` errors | `errx-codes` |
| fault latched, cleanup unverified | interrupted run | `safe_shutdown`, then skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | resistor_100k | none | S20261118T063040Z-4171 | `system.self_test`: tier needs_confirmation (system_self_test); confirmed run completed, result 0 | - |
| sim | 2026-11-18 | resistor_100k | none | S20261118T063040Z-45f4 | `system.self_cal`: tier needs_confirmation (system_self_cal); confirmed run completed, result 0 | - |
| hw | pending (bring-up stage L1) | - | - | - | - | - |

Sim rows: the example plan (and the same request for `system.self_cal`) validated and run with the summary
through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run folders were not kept.
Hardware records: `validation/hw/system.self_test.yaml`, `validation/hw/system.self_cal.yaml` (reviewed by a human
after bring-up stage L1, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...`
runs).
