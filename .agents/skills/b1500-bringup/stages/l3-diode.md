---
stage: L3
title: Known diode - voltage forcing, compliance flags, Is/n/Rs against the data sheet and EasyEXPERT
recipes: [basic.diode_iv, basic.iv_force_i]
checks:
  - {id: n, recipe: basic.diode_iv, quantity: n, method: diode_fit, reference: 'data sheet / EasyEXPERT fit of the same sweep', text: 'plausible: 1.0 to 2.0 for a Si diode'}
  - {id: is, recipe: basic.diode_iv, quantity: is, method: diode_fit, unit: A, reference: 'data sheet / EasyEXPERT fit of the same sweep', text: recorded (plausible order of magnitude)}
  - {id: rs, recipe: basic.diode_iv, quantity: rs, method: diode_fit, unit: Ohm, reference: data sheet, text: recorded}
  - {id: leakage, recipe: basic.diode_iv, quantity: leakage, method: leakage_at, unit: A, reference: EasyEXPERT reverse current at the same voltage, tolerance: {factor: 2}, text: 'within a factor 2 (both above 10 pA)'}
  - {id: cleanup, recipe: basic.diode_iv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: vf_1ma, recipe: basic.iv_force_i, quantity: vf, method: forward_voltage, unit: V, reference: 'EasyEXPERT forward voltage at 1 mA (current forcing), same diode', tolerance: {absolute: 0.005}, text: '+-5 mV'}
  - {id: n_force_i, recipe: basic.iv_force_i, quantity: n, method: diode_fit, reference: 'n of basic.diode_iv on the same diode (this stage)', tolerance: {rel: 0.05}, text: '+-5 % of the voltage-forced n'}
  - {id: force_i_cleanup, recipe: basic.iv_force_i, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
version: 1
---

# L3 - Known diode

Voltage forcing over five decades of current and the compliance flags. Recipe `basic.diode_iv` (card `diode-iv`):
reverse then forward staircase, defaults -5 V to 0.8 V, 291 points, 10 mA compliance, leakage limit 1 nA. Then
current forcing, `basic.iv_force_i` (same card): log current sweep 1 nA to 10 mA, 71 points, 2 V voltage compliance,
Vf at 1 mA. Every hardware plan needs consent (`first_hw_run`).

## 1. Preconditions

- L2 signed off for the anode SMU, which must be an HRSMU (role `anode` is low-current);
  `uv run b1500 bringup status` names L3.
- A known silicon diode with its data sheet; an EasyEXPERT I/V export of the same diode on the same wiring from the
  same day (-5 V to 0.8 V, 291 points, 10 mA compliance, about 1 PLC); without EasyEXPERT, the data-sheet values.

## 2. Physical steps (human)

1. Mount the diode: anode on the HRSMU force path, cathode on GNDU; shield box closed.
2. Adopt the pin map `diode-l3` (copy of `diode-2t`: `anode` = the HRSMU slot, `cathode: GNDU`) and the DUT
   profile `diode-l3` (copy of `diode-generic` with the data sheet's maximum reverse voltage and forward current;
   it must allow 5 V reverse and 10 mA) with `uv run b1500 config adopt FILE --as pinmap` and `--as dut`.
3. Switching between EasyEXPERT and the agent (ATV-3): before EasyEXPERT, `uv run b1500 lock status` shows the
   lock free and no run active; on the FlexGUI window choose Tools > Go to Local & Close (PG p24 (1-4)
   "Go to Local & Close"), then start EasyEXPERT; afterwards File > Exit and leave the Start EasyEXPERT button.

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status` clean; propose the pin map and DUT profile of physical step 2
   under `work/bringup/` and hand the adoption over.
2. `validate_plan` of `basic.diode_iv` with pin map `diode-l3`, DUT profile `diode-l3` and the defaults (adapt
   `v_rev`/`v_fwd` to the data sheet with `params`, inside the recipe ranges, and keep the EasyEXPERT sweep
   identical); tier `needs_confirmation` (`first_hw_run`); summary, stop, consent, `run_confirmed_plan`.
3. `get_run` (`summary`, `quality`); `analyze_run(run_id, "diode_fit")` and `analyze_run(run_id, "leakage_at")`
   when not already present. Report n, Is, Rs and the leakage as derived values with method and fit window, the
   status counts (compliance `C` rows are excluded from the fit), backend visa.
4. Ask the human for the EasyEXPERT values at the same voltages (forward current at 0.4, 0.5, 0.6 V; reverse
   current at `v_rev`) and compare.
5. `basic.iv_force_i` on the same pin map and profile, defaults: same flow; `forward_voltage` (Vf at 1 mA) and
   `diode_fit`; compare Vf with the EasyEXPERT value at 1 mA and n with step 3.
6. Hardware: `uv run b1500 bringup capture H... H...` of one `basic.diode_iv` run (blocks with compliance `C`)
   and one `basic.iv_force_i` run (current forcing) for the parser fixtures.
7. Hardware: the recipe records (section 6).

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `n` | 1.0 to 2.0 | plausibility (recorded) | `diode_fit` |
| `is` | the data sheet's order of magnitude | recorded | `diode_fit` |
| `rs` | ohms to tens of ohms for a small-signal diode | recorded | `diode_fit` |
| `leakage` | reverse current at `v_rev` | factor 2 of EasyEXPERT when both above 10 pA, else both below 10 pA | `leakage_at` |
| `cleanup` | every run `verified: lop` | pass/fail | run manifests |
| `vf_1ma` | anode voltage at 1 mA (`basic.iv_force_i`) | +-5 mV of EasyEXPERT | `forward_voltage` |
| `n_force_i` | n of the current-forced sweep | +-5 % of step 3's n | `diode_fit` |
| `force_i_cleanup` | every run `verified: lop` | pass/fail | run manifests |

- Forward current at 0.4, 0.5 and 0.6 V within +-5 % of the EasyEXPERT export (the reviewer compares the run's
  `data.csv` with the export; record the three deviations).
- Run `completed`, or `completed_with_flags` when the forward end reaches compliance; compliance flags (`C`)
  exactly where the current reaches 10 mA.
- TODO(verify) (blueprint v2 7.6 item 3): the status letters of real FMT 1 blocks at compliance (`C`) and under
  current forcing (one run of each recipe captured, agent step 6).

## 5. Abort criteria

- Compliance at a small forward voltage (below about 0.5 V); a reverse current orders of magnitude above the
  reference; deviations above 20 %; cleanup `unverified`.
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human. Never raise the
  compliance or widen a tolerance to pass.

## 6. Record

- Hardware: `uv run b1500 bringup record L3 --run H... --reference leakage=2.3e-11 --operator NAME` (the reference
  is the human's EasyEXPERT value); the human reviews it, adds the forward-current comparison and moves it to
  `validation/hw/basic.diode_iv.yaml`. Likewise `uv run b1500 bringup record L3 --run H... --reference vf_1ma=0.652
  --reference n_force_i=1.04 --operator NAME` → `validation/hw/basic.iv_force_i.yaml`.
- Simulator rehearsal: no record; say that hardware drafts the `basic.diode_iv` and `basic.iv_force_i` records.
