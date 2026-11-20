---
stage: L2
title: Known resistors - DC accuracy against a DMM (100 kOhm, 1 MOhm)
recipes: [basic.contact_resistor, generic.smu_multi_sweep]
checks:
  - {id: r_dmm, recipe: basic.contact_resistor, quantity: resistance, method: resistance, unit: Ohm, reference: DMM reading of the same resistor just before, tolerance: {rel: 0.01}, text: '+-1 % vs DMM'}
  - {id: linearity, recipe: basic.contact_resistor, quantity: linearity_r2, method: resistance, reference: a linear resistor, text: 'recorded (expect r2 above 0.999)'}
  - {id: offset, recipe: basic.contact_resistor, quantity: offset_current, method: resistance, unit: A, reference: L1 floor of the same SMU, text: recorded}
  - {id: cleanup, recipe: basic.contact_resistor, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: multi_r, recipe: generic.smu_multi_sweep, quantity: resistance, method: resistance, unit: Ohm, reference: DMM reading of the 100 kOhm resistor on terminal a, tolerance: {rel: 0.01}, text: '+-1 % vs DMM (one-source multi-channel sweep)'}
  - {id: multi_cleanup, recipe: generic.smu_multi_sweep, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# L2 - Known resistors

DC accuracy of each SMU used later, on metal-film resistors measured with a DMM just before. Recipe
`basic.contact_resistor` (card `contact-resistor-check`): -0.1 V to +0.1 V, 21 points, 1 mA compliance, so about
+-1 uA through 100 kOhm and +-100 nA through 1 MOhm. The multi-channel sweep `generic.smu_multi_sweep` (card
`smu-spot-kelvin`, MM 16) repeats the 100 kOhm reading with `params {start: -0.1, stop: 0.1, points: 21}`. The 1 Ohm
Kelvin and the multi-terminal spot checks join this stage with their recipes. Every hardware plan needs the
human's consent (`first_hw_run`; generic recipes also `adhoc_recipe`).

## 1. Preconditions

- L1 signed off for every SMU used here (at least those L3 and L4 use); `uv run b1500 bringup status` names L2.
- Instrument warmed up (the data sheet's warm-up time; TODO(verify) the time at the station).
- The S0 resistors with fresh DMM readings (model, range, 2- or 4-wire, reading, temperature).

## 2. Physical steps (human)

1. Mount the 100 kOhm resistor between the SMU force path under test and GNDU (fixture or probes); shield box
   closed. Tell the agent the DMM reading.
2. Adopt the pin map `res-smuN` per SMU (`a` = the slot, `b` = `GNDU`; the agent proposes it under
   `work/bringup/`) and the DUT profiles `r100k` and `r1m` (copies of `resistor-generic` with `nominal.r` = the DMM
   value): `uv run b1500 config adopt FILE --as pinmap`, `--as dut`. Mark a pin map `verified` only after checking
   the wiring yourself.
3. After the 100 kOhm runs: swap in the 1 MOhm resistor and give its DMM reading.

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status` clean.
2. Propose the pin maps and DUT profiles of physical step 2 under `work/bringup/`; hand the adoption over; stop.
3. Per SMU and resistor: `validate_plan` of `basic.contact_resistor` with pin map `res-smuN` and DUT profile
   `r100k` (or `r1m`), default params; tier `needs_confirmation` (`first_hw_run`, `unverified_pin_map` while
   unverified); summary, stop, consent, `run_confirmed_plan`.
4. `get_run` (`summary`, `quality`); `analyze_run(run_id, "resistance")` when the default analysis was not kept;
   report R, linearity and offset as derived values (method `resistance`, window -0.1..0.1 V) next to the DMM
   value, with the deviation in percent.
5. `annotate_run(run_id, "DMM <value> (<model>, 4-wire), <temperature>")` so the reference stays with the run.
6. `generic.smu_multi_sweep` on the 100 kOhm resistor (pin map `res-smuN`, DUT profile `r100k`, `params {start:
   -0.1, stop: 0.1, points: 21}`): same flow; `analyze_run(run_id, "resistance", {"x": "a_V", "y": "a_I"})`.
7. Hardware: the recipe records (section 6) with one `--reference` per run.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `r_dmm` | R of the `resistance` analysis, classification `in_range` | +-1 % of the DMM reading | DMM |
| `linearity` | `linearity_r2` close to 1 | recorded (above 0.999) | `resistance` |
| `offset` | `offset_current` near the L1 floor of the SMU | recorded | `resistance` |
| `cleanup` | every run `verified: lop`, error queue empty | pass/fail | run manifests |
| `multi_r` | R of the multi-channel sweep's terminal a | +-1 % of the DMM reading | DMM |
| `multi_cleanup` | every run `verified: lop` | pass/fail | run manifests |

- Plans: tier `needs_confirmation` with `first_hw_run` (and `unverified_pin_map` while unverified).
- Runs: outcome `completed`, every status `N`, quality `ok`.

## 5. Abort criteria

- A deviation above 5 %, classification `open` or `short`, or compliance statuses (`C`): stop, check wiring and
  contacts with the human before repeating. Between 1 % and 5 %: not passed; check the DMM mode and temperature,
  repeat with `params {integration: long}`.
- Cleanup `unverified` or a latched fault: `safe_shutdown(reason)`, skill `b1500-debug`, wait for the human.
- Never widen the tolerance to pass; the owner may only tighten it.

## 6. Record

- Hardware: one recipe record of `basic.contact_resistor` over all L2 runs, each with its own DMM reference:
  `uv run b1500 bringup record L2 --run H... --run H... --reference r_dmm@H...=99870 --reference r_dmm@H...=1.0021e6 --operator NAME`.
  The human reviews it and moves it to `validation/hw/basic.contact_resistor.yaml`; the promotion to
  `hw_validated` is a later developer change (`uv run b1500 dev recipe-check` checks the record).
- `generic.smu_multi_sweep`: `uv run b1500 bringup record L2 --run H... --reference multi_r=99870 --operator NAME`
  → `validation/hw/generic.smu_multi_sweep.yaml`.
- Simulator rehearsal: no record (runs are `S...`); say that hardware drafts the `basic.contact_resistor` and
  `generic.smu_multi_sweep` records.
