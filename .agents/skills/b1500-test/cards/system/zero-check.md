---
id: zero-check
title: SMU zero check — every SMU at 0 V on open terminals; offset and noise floor per current range
family: system
intent: [zero check, noise floor, offset current, open terminals, SMU floor, baseline]
recipes: [system.zero_check]
device_types: []
modules: [HRSMU, MPSMU]
routes: []
bringup_stage: L1
status: sim_validated
confirmation: conditional
knowledge: [knowledge/02b-smu-modes.md#zero-check-floor, knowledge/02-b1500-instrument.md#integration-time-and-ranging, knowledge/03-probe-station-wiring.md#guard-for-low-current, knowledge/03-probe-station-wiring.md#shielding-grounding-and-interlock, knowledge/02-b1500-instrument.md#measurement-sequence-and-cleanup]
manual: [PG p470 (4-152) "MM", PG p501 (4-183) "RI", PG p337 (4-19) "1 pA limited auto", PG p396 (4-78) "DV"]
debug: [noisy-data, compliance-hit, current-too-high, cleanup-failed-fault, errx-codes, async-run-interrupted]
sources: [blueprint v2 3.1 (system.zero_check), 7.4 (stage L1 floors), "deck slide 12 (topics only, illustrative: not evidence)", lwp/matlab_B1500/IdVg_test_20251004_*.csv]
version: 1
---

# SMU zero check

## 1. Purpose and applicable devices

What does each SMU read with nothing connected? Every SMU named by the pin map holds 0 V with a small compliance,
its terminal open, and is read `samples` times on each listed current range (fixed ranges); analysis `zero_floor`
gives per SMU the noise floor (standard deviation) of every range and the offset (mean).

- Bring-up stage L1 (outputs safe at 0 V, verified cleanup, floors recorded) and later as a station baseline:
  after re-cabling, before low-current work, when leakage data look noisy.
- Not for: a landed device (use [contact-resistor-check](../smu/contact-resistor-check.md)); self-test or
  calibration ([self-test-cal](self-test-cal.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| smu3 .. smu6 (lab example) | `smuN`: the SMU in slot N, 0 V, measures I | SMU3, SMU4 (HRSMU), SMU5, SMU6 (MPSMU) | terminal open: probes lifted, socket empty |

- Example pin map `open-smus` (terminal `smuN` = slot N; slots 3-6) with DUT profile `open-circuit`. A station with
  other SMU slots needs the human's own copy listing exactly its SMUs; never write or guess one.
- The GNDU and non-SMU modules are not part of the check.
- Routes: none in every phase (the SMUs' own outputs; an ASU stays on its SMU side, its 1 pA range is used only
  when the station declares that ASU `present: true`).

## 3. Pre-run checklist

- The human has lifted the probes (or opened the socket) and closed the shield box: an open terminal is the point.
- `station_status` clean (no fault, lock holder or pending errors); pin map and DUT profile listed.
- Know the integration: the floor scales with it (record it with the result).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `ranges` | [10 pA, 1 nA, 100 nA, 10 uA, 1 mA] | 1 pA..100 mA | 1 pA..100 mA | ranges to read; each SMU uses its smallest range at or above | an MPSMU reads 10 pA on its 1 nA range (MPSMU minimum range 1 nA without ASU: UG p63 (2-23)) |
| `samples` | 100 | 50..200 | 10..1000 | readings per range | floor uncertainty about 1/sqrt(2 x samples) |
| `icomp` | 100 uA | 1 uA..100 uA | 1 nA..1 mA | compliance at 0 V | a hit means the terminal is not open |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | floor vs time | `long`: lower floor, 16x longer |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: system.zero_check
params: {}
pin_map: open-smus
dut_profile: open-circuit
sim_scenario: lab_station
```

## 5. Limits and confirmation

- 0 V on every SMU; the compliance (≤ 1 mA) stays inside `open-circuit` (1 mA) and every soft limit: the example
  plan is tier `ok`. Destructive: no.
- `long_run` (R-RUN-02): a plan above 600 s (e.g. `integration: long` with `samples: 1000`) needs confirmation;
  above 300 s it runs asynchronously (poll `get_run`, cancel with `safe_shutdown`).
- On hardware: `first_hw_run` until the recipe is `hw_validated`; `unverified_pin_map` while the map is unverified.

## 6. Quality criteria

- Every status letter `N`. `C` (current compliance at 0 V) or `T`: something is connected or leaking: stop, ask the
  human. `V` on a fixed range: the reading exceeds that range (not open). Never force the analysis.
- The run stops at the first `C`/`T`/`V`/`X` point (`kind_result.stop_reason`).
- Re-measure (autonomous, at most two, tier stays `ok`): `integration: long`, `samples` up to 200.

## 7. Analysis method

- Default `zero_floor`: per SMU one result `<role>_floor` (standard deviation on its lowest range); `fit` holds the
  floor of every range (`10pA`, `1nA` ...), `offset` (mean, lowest range) and `max_abs_offset`. Options
  `max_floor_a`, `max_offset_a` give `pass`/`fail` only against bounds the human sets (the L1 stage's sanity bounds
  are provisional, `TODO(verify)[L1.A4]`); without them report the floors with no verdict
  ([02](../../knowledge/02b-smu-modes.md#zero-check-floor)). At most five SMUs per pin map keep the result
  inside the 2k-token tool response: a larger station runs two pin maps.
- `quality_report` for status counts. Report floor and offset per SMU and range as derived values (method, integration,
  samples), the run's cleanup verification and the backend (SIMULATED flag).

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| SMU | floor on its lowest range (source) | red flags |
|---|---|---|
| HRSMU (10 pA range, 1 PLC) | lab HRSMU with open probes: about 0.07 pA rms at 1 PLC, auto ranging (`lwp/matlab_B1500/IdVg_test_20251004_*.csv`); cable, guard and shield dependent; this station's fixed-range floor `TODO(verify)[L1.A4]` | above the human's bound; offset growing with time (charging) |
| MPSMU (1 nA range) | unknown until bring-up (`TODO(verify)[L1.A4]`) | above the human's bound |
| any SMU, higher ranges | floor grows with the range (UG resolution tables) | `C`/`V` statuses; offset far above the floor |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| floor far above the expectation | probe still landed, open shield box, cable noise | ask the human (probes, shield); repeat with `integration: long` | `noisy-data` |
| `C` at 0 V, run stopped | terminal connected to a DUT or a leakage path | stop; ask the human to lift the probes | `compliance-hit` |
| large constant offset | charging cable, guard not connected | wait and repeat; ask about Guard | `current-too-high` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |
| run `cancelled` or `aborted` after the session ended | harness closed or killed its MCP server mid-run | `safe_shutdown`, then `get_run` (outcome, partial rows) | `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-19 | lab_station | open-circuit | S20261119T105038Z-8d17 | tier ok; floors -7 to +3 % vs the scenario floor (HRSMU 1e-13 A, MPSMU 1e-11 A); N=2000 statuses | - |
| hw | pending (bring-up stage L1) | - | - | - | - | - |

Sim rows: the example plan through `B1500Service`, temporary config/data dirs (not kept). Hardware record: `validation/hw/system.zero_check.yaml` (reviewed by a human after bring-up stage
L1, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs). Until it exists
every hardware plan needs `first_hw_run` confirmation.
