---
id: cmu-correction
title: MFCMU phase compensation and open/short/load correction — correction records for C-V
family: cmu
intent: [phase compensation, open correction, short correction, load correction, CMU correction, R-CORR-01, ADJ, 'CORR?']
recipes: [cmu.phase_compensation, cmu.correction_open, cmu.correction_short, cmu.correction_load]
device_types: [capacitor, moscap, fecap]
modules: [MFCMU]
routes: [scuu:cmu]
bringup_stage: L6
status: sim_validated
confirmation: always
knowledge: [knowledge/02-b1500-instrument.md#mfcmu-phase-compensation-and-correction, knowledge/03-probe-station-wiring.md#signal-path-from-smu-to-pad]
manual: ['PG p251 (3-71) "Data Correction"', 'PG p355 (4-37) "ADJ"', 'PG p382 (4-64) "CORR?"', 'PG p379 (4-61) "CLCORR"', 'PG p389 (4-71) "DCORR"', 'PG p384 (4-66) "CORRDT?"', 'PG p175 (2-87) "device clear"']
debug: [cmu-correction-stale, cmu-cv-distortion, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 0 (decision 11), blueprint v2 2.6, blueprint v2 3.2, blueprint v2 4.2]
version: 1
---

# MFCMU phase compensation and open/short/load correction

## 1. Purpose and applicable devices

Every capacitance measurement (C-V, C-f, spot C) needs fresh corrections of the MFCMU path it uses: rule R-CORR-01
blocks it otherwise and points here. The recipes measure the cables and probes, not a device:

1. `cmu.phase_compensation` (probes lifted), 2. `cmu.correction_open` (probes lifted), 3. `cmu.correction_short`
   (probes on a short), 4. `cmu.correction_load` (load standard; only when `policy.corrections.require` lists it).

- Order matters: a new phase compensation switches the open/short/load corrections off (they were measured with the
  old phase data), so after it open and short are needed again.
- Not for: measuring the DUT; a check of the result with a known capacitor (100 pF standard: card `cmu-spot`).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| the pin map's `<ch>H` terminal (`gate`, `a`) | `high` (cmu_high) | MFCMU High (Hc/Hp) | role binds by MFCMU side |
| the pin map's `<ch>L` terminal (`bulk`, `b`) | `low` (cmu_low) | MFCMU Low (Lc/Lp) | role binds by MFCMU side |

- Use the **same pin map as the capacitance measurement** (`moscap-cmu`, `capacitor-cmu`): a record counts only for
  the pin map and station profile it was measured with. No DUT profile (the probes never touch the DUT).
- Routes per phase: none with a direct pin map; through an SCUU (pin map `moscap-scuu`): measure `SCUU1.OUT1/OUT2
  -> cmu`, then rest (the corrections then include the SCUU path; the C-V uses the same SCUU pin map).

## 3. Pre-run checklist

- `station_status`: no fault, no active run; `corrections` shows what is fresh, stale or missing per MFCMU.
- Same cables, landing position, prober and temperature as the measurement that follows.
- Ask the human for each physical state and wait for the answer in chat before running:
  - phase compensation and open: "Please lift the probes off the device (open terminals at the device end) and keep
    them lifted until I report the run done."
  - short: "Please land both probes on a short (shorting bar or one metal pad) and keep them there."
  - load: "Please connect the load standard (station profile `corrections.<alias>.load`) at the device end."
- After the last correction, in the same answer: validate the measurement plan (R-CORR-01 now passes), show its
  summary and ask "Please land the probes on the device again; reply go ahead to run this plan". It needs
  confirmation too: `unverified_pin_map` (example pin maps) and, on `moscap-generic`, `dut_envelope` (the MFCMU has
  no compliance: its nominal AC current `sqrt(2) x Vac / 50 Ohm` exceeds the 1 uA terminal limit; an intact oxide
  draws only leakage). A reply that confirms the landing and says go ahead is the consent for that summary; a reply
  with the landing only: ask for the consent. Never run a C-V while the probes are lifted or on the short.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `correction` (`cmu.phase_compensation`) | `phase` | - | `phase` | fixed by the recipe | `ADJ?` (about 30 s) |
| `correction` (`cmu.correction_open`) | `open` | - | `open` | fixed by the recipe | `CORR?` open |
| `correction` (`cmu.correction_short`) | `short` | - | `short` | fixed by the recipe | `CORR?` short |
| `correction` (`cmu.correction_load`) | `load` | - | `load` | fixed by the recipe | `CORR?` load |
| `freqs_hz` (`cmu.correction_open`) | [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 1200, 1500, 2000, 2500, 2700, 3000, 3200, 3500, 3700, 4000, 4200, 4500, 5000] kHz | 1 kHz..5 MHz | 1 kHz..5 MHz | list every C-V frequency (R-CORR-01 coverage); at most 64 | corrected only at listed ones; a new list clears the others |
| `freqs_hz` (`cmu.correction_short`) | [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 1200, 1500, 2000, 2500, 2700, 3000, 3200, 3500, 3700, 4000, 4200, 4500, 5000] kHz | 1 kHz..5 MHz | 1 kHz..5 MHz | list every C-V frequency (R-CORR-01 coverage); at most 64 | corrected only at listed ones; a new list clears the others |
| `freqs_hz` (`cmu.correction_load`) | [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 1200, 1500, 2000, 2500, 2700, 3000, 3200, 3500, 3700, 4000, 4200, 4500, 5000] kHz | 1 kHz..5 MHz | 1 kHz..5 MHz | list every C-V frequency (R-CORR-01 coverage); at most 64 | corrected only at listed ones; a new list clears the others |
| `ac_vrms` (`cmu.correction_open`) | 30 mV | 10..50 mV | 10..250 mV | use the measurement's level | above 50 mV: `soft_cmu` |
| `ac_vrms` (`cmu.correction_short`) | 30 mV | 10..50 mV | 10..250 mV | use the measurement's level | above 50 mV: `soft_cmu` |
| `ac_vrms` (`cmu.correction_load`) | 30 mV | 10..50 mV | 10..250 mV | use the measurement's level | above 50 mV: `soft_cmu` |

The phase compensation has no other parameter (the MFCMU uses its own internal signal).

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: cmu.correction_open
params: {}
pin_map: capacitor-cmu
sim_scenario: capacitor_100p
```

## 5. Limits and confirmation

- Always `needs_confirmation`: `physical_setup` (R-ALWAYS-01; the finding names the probe state). Show the summary
  verbatim with the physical step, stop the turn; every run needs consent to its shown summary. Phase compensation
  and open share the lifted state: show both summaries together; one reply (lifted, go ahead) consents to both, run
  them in order. Unverified pin maps add `unverified_pin_map`; on hardware `first_hw_run` until `hw_validated`.
- AC level within 10..250 mVrms and the MFCMU's 1 kHz..5 MHz (R-CMU-01), DC bias 0 V; no compliance on the MFCMU.
- `cmu.correction_load` cannot be planned without the load standard in the station profile (`invalid_input`;
  only a human records it). Not destructive; sync runs (phase about 35 s, data corrections about 0.5 s per
  frequency).

## 6. Quality criteria

- No data table: the run's `kind_result` holds `result_code` (0 = completed), `setup` (`kept`/`rewritten`) and the
  read-back state `after_phase`, `after_open`, `after_short`, `after_load`.
- `completed_with_flags` with "record(s) were discarded": another correction was invalidated (new phase
  compensation, or a rewritten frequency list). Run the named recipes again in order.
- Result 1 (failed) or 2 (aborted): the physical state was wrong; ask the human, re-run once.
- Data read back (`CORRDT?`, medians over the list): `open_cp_f` is the stray capacitance of the lifted probes
  (simulator 0.3 pF; a probe pair about 0.1..2 pF, TODO(verify) at L6): tens of pF means the probes were on a device.
  `short_rs_ohm` (cable and probe, below about 1 Ohm) and `short_ls_h` (tens of nH): hundreds of Ohm means they
  were not on the short. Either: ask the human, repeat the correction in the right state (runbook `cmu-cv-distortion`).

## 7. Analysis method

No `analyze_run` method. Report from `get_run` (summary, audit, `kind_result`): result per correction,
frequencies, AC level, the data read back (`open_cp_f`, `short_rs_ohm`), `station_status.corrections` afterwards. Check the corrections with a known capacitor (card `cmu-spot`) at L6.

## 8. Expected result shape

| correction | typical | red flags |
|---|---|---|
| phase | result 0 after about 30 s; `after_phase` true | result 1: something touches the probes |
| open | result 0; `after_open` true; `open_cp_f` below a few pF | result 1/2 or `open_cp_f` of tens of pF: probes on the DUT |
| short | result 0; `after_short` true, `after_open` still true; `short_rs_ohm` below 1 Ohm | open record discarded: the list or standards changed; `short_rs_ohm` of 100s of Ohm |
| any | a fresh record in `station_status.corrections` | records missing after a device clear, `*RST` or power cycle |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| C-V blocked by R-CORR-01 | missing, stale, other pin map, frequency not listed | `station_status.corrections` | `cmu-correction-stale` |
| corrections lost before a run | `*RST`, device clear, power cycle | pre-execute finding, `station_status` | `cmu-correction-stale` |
| result 1 or 2, errors 680-685 | wrong probe state, AC 0, no load reference | `get_run` audit, ask the human | `errx-codes` |
| `open_cp_f` tens of pF, `short_rs_ohm` 100s of Ohm | probes not lifted / not on the short | ask the human, repeat | `cmu-cv-distortion` |
| fault latched, cleanup unverified | interrupted run | `safe_shutdown`, skill `b1500-debug` | `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | capacitor_100p | 100 pF standard | S20261122T082459Z-9300 | `cmu.phase_compensation`: needs_confirmation (physical_setup); result 0, phase record | - |
| sim | 2026-11-22 | capacitor_100p | 100 pF standard | S20261122T082459Z-5cae | `cmu.correction_open`: result 0, set-up rewritten, open record | - |
| sim | 2026-11-22 | capacitor_100p | 100 pF standard | S20261122T082459Z-6109 | `cmu.correction_short`: set-up kept, open still on; then 100 pF read 100.003 pF (100 kHz), 99.969 pF (1 MHz), uncorrected about +0.3 pF | - |
| sim | 2026-11-22 | capacitor_100p (load 100 Ohm declared) | 100 pF standard | S20261122T082510Z-82ba | `cmu.correction_load`: result 0 after phase, open, short; load record | - |
| hw | pending (bring-up stage L6) | - | - | - | - | - |

Sim rows: the example plan (and the same request for the other recipes) validated and run with the summary through
`B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`, then a test-only C-V-shaped spot read; those run
folders were not kept (`tests/integration/test_recipes_cmu_correction.py` repeats it). Hardware records:
`validation/hw/cmu.phase_compensation.yaml`, `validation/hw/cmu.correction_open.yaml`,
`validation/hw/cmu.correction_short.yaml`, `validation/hw/cmu.correction_load.yaml` (reviewed by a human after
bring-up stage L6, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
