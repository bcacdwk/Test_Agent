---
id: smu-spot-kelvin
title: SMU spot, Kelvin and multi-channel sweep — several terminals at once (MM 16 part)
family: smu
intent: [multi-channel sweep, MM 16, several sweep terminals, simultaneous sweep, generic sweep, WNX]
recipes: [generic.smu_multi_sweep]
device_types: []
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L2
status: sim_validated
confirmation: conditional
knowledge: [knowledge/02-b1500-instrument.md#measurement-modes, knowledge/03-probe-station-wiring.md#contact-checks, knowledge/06-analysis-extraction.md#resistance-fit, knowledge/06-analysis-extraction.md#quality-gate-and-noise]
manual: [PG p102 (2-14) "Multi Channel Sweep", PG p557 (4-239) "WNX", PG p226 (3-46) "Table 3-13"]
debug: [noisy-data, compliance-hit, current-too-high, errx-codes, cleanup-failed-fault]
sources: [blueprint v2 3.1, blueprint v2 6.3, Programming Guide Table 3-13]
version: 1
---

# SMU spot, Kelvin and multi-channel sweep

This card's multi-channel sweep part (`generic.smu_multi_sweep`, WP7.2); the spot and Kelvin parts
(`generic.smu_spot`, `resistor.kelvin_4w`) join it with their recipes.

## 1. Purpose and applicable devices

Sweep several terminals in one measurement (MM 16): terminal `a` is the primary staircase, terminal `c` a second
sweep source that steps with it (its own start and stop, the same steps and mode; equal start and stop = a constant
source), terminal `d` a constant bias, terminal `b` the return (GNDU or an SMU at 0 V). Every SMU terminal but `b`
is measured at each step. Use it when no device card fits and the human asks for such a sweep (an ad-hoc recipe);
with only `a` and `b` connected it is the one-source multi-channel sweep of the Programming Guide's example.

- Not for: a MOSFET with the drain following the gate (card [mosfet-idvg](mosfet-idvg.md), `mosfet.idvg_sync`);
  landing checks ([contact-resistor-check](contact-resistor-check.md)); any device a card covers (prefer its card).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| a | `a`: primary sweep (V), measures I | any SMU (SMU3 in `resistor-2t`) | the first `WV` source |
| c | `c`: second sweep (V, `WNX 2`), measures I | another SMU (optional) | follows a's steps |
| d | `d`: constant bias (V), measures I | another SMU (optional) | |
| b | `b`: return, ground | GNDU (or an SMU at 0 V) | |

- Committed example: pin map `resistor-2t` (a = SMU3, b = GNDU) with DUT profile `resistor-generic`; terminals c and
  d need a pin map and a DUT profile from the human that name them. Ask; never write or guess one.
- Routes: none in every phase (direct SMU and GNDU wiring; no selector, SCUU, ASU or RSU in the path).

## 3. Pre-run checklist

- `station_status` clean (no fault, lock holder or pending errors); the pin map and DUT profile are listed.
- Fresh landing: [contact-resistor-check](contact-resistor-check.md) first.
- Know which terminal is which and the limits of every terminal from the human before planning.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `start` | 0 V | - | -42..42 V | terminal a at the first step | |
| `stop` | 1 V | - | -42..42 V | terminal a at the last step | beyond the profile: confirmation |
| `points` | 51 | - | 2..2001 | steps of every sweep terminal | |
| `icomp` | 100 uA | - | 1 pA..100 mA | terminal a compliance | above the profile's `max_abs_i`: confirmation |
| `mode` | `single` | - | `single`, `double` | double: there and back (both terminals) | twice the steps |
| `start_c` | 0 V | - | -42..42 V | terminal c at the first step | `start_c` = `stop_c`: constant source |
| `stop_c` | 1 V | - | -42..42 V | terminal c at the last step | |
| `icomp_c` | 100 uA | - | 1 pA..100 mA | terminal c compliance | |
| `bias_v` | 0 V | - | -42..42 V | terminal d level | |
| `bias_icomp` | 100 uA | - | 1 pA..100 mA | terminal d compliance | |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | noise vs time | |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: generic.smu_multi_sweep
params: {}
pin_map: resistor-2t
dut_profile: resistor-generic
sim_scenario: resistor_100k
```

## 5. Limits and confirmation

- `dut_envelope` (R-DUT-01): any terminal level above the profile's `max_abs_v` or a compliance above its
  `max_abs_i` (`resistor-generic`: 1 V, 1 mA). A grounded SMU on `b` gets the sum of the sourcing compliances, so
  two 100 mA sources make 200 mA there: blocked (R-LIM-02); keep the compliances small.
- On hardware: `adhoc_recipe` (always), `unverified_pin_map`, `first_hw_run` (until `hw_validated`). Destructive: no.

## 6. Quality criteria

- Status letters: `N` ok; `C`/`T` limited (a compliance anywhere stops the whole sweep, `WM 2,1`: later rows read
  `V`); `V X F D G S U` untrusted: extractions refuse; never force silently.
- A sweep terminal at the noise floor over the whole sweep is not connected (or not wired in the scenario): say so.
- Re-measure (autonomous, at most two): `integration: long`, `points` inside the range and the profile.

## 7. Analysis method

- No default analysis (ad hoc): choose with `analyze_run` per terminal, for example `resistance` with
  `{x: a_V, y: a_I}` for a resistor on a, `plot_iv`. Columns: `a_V` (returned source), `c_V` (programmed, follows
  a), `d_V`, measured `a_I`, `c_I`, `d_I` with status.
- Report measured currents and status counts per terminal; derived values with method and window
  ([06](../../knowledge/06-analysis-extraction.md#resistance-fit)).

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| resistor between a and b | linear I(V), R near its nominal | noise floor everywhere (open), compliance at the first step (short) |
| two-terminal pairs on a and c | each terminal's own I-V, measured in one sweep | a terminal mirroring another (shared path or wrong pins) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| a terminal noise-dominated everywhere | probe not landed, terminal not wired | contact check; ask for re-landing | `noisy-data` |
| compliance at the first step | short or wrong pins | stop; contact check; ask the human | `compliance-hit` |
| currents orders of magnitude too high | parallel path, wrong device | compare pin map and wiring with the human | `current-too-high` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-19 | resistor_100k | resistor-generic | S20261119T111105Z-39ae | tier ok; MM 16 with terminal a alone; `resistance` on a: +0.04 % vs 100 kOhm; N=51 | - |
| hw | pending (bring-up stage L2) | - | - | - | - | - |

Sim runs used temporary config/data folders (not kept). Hardware record `validation/hw/generic.smu_multi_sweep.yaml`
(reviewed after stage L2, skill `b1500-bringup`; only from hardware `H...` runs). Until it exists every hardware
plan needs `first_hw_run` confirmation.
