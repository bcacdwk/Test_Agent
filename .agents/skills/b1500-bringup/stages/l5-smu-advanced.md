---
stage: L5
title: SMU advanced - pulsed I-V against DC, sampling time grid, Vth by search (QSCV leakage in stage L6)
recipes: [mosfet.idvg_pulsed, mosfet.idvd_pulsed, basic.pulsed_spot, generic.smu_multi_pulsed, mosfet.id_t_sampling, generic.smu_sampling, mosfet.vth_search]
checks:
  - {id: pulsed_vs_dc, recipe: mosfet.idvg_pulsed, quantity: pulsed_over_dc, method: pulsed_vs_dc, unit: '1', reference: 'DC mosfet.idvg on the same die at the same Vd (options.reference_run), low duty', tolerance: {absolute: 0.02}, text: '1 +-0.02 (pulsed = DC within 2 %)'}
  - {id: idvg_pulsed_cleanup, recipe: mosfet.idvg_pulsed, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: idvd_pulsed_ratio, recipe: mosfet.idvd_pulsed, quantity: pulsed_over_dc, method: pulsed_vs_dc, unit: '1', reference: 'DC mosfet.idvd on the same die (options.reference_run), low duty', tolerance: {absolute: 0.02}, text: '1 +-0.02 at low duty (self-heating shows above)'}
  - {id: idvd_pulsed_cleanup, recipe: mosfet.idvd_pulsed, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: pulsed_spot_r, recipe: basic.pulsed_spot, quantity: resistance, method: resistance, unit: Ohm, reference: DMM reading of the 100 kOhm standard, tolerance: {rel: 0.01}, text: '+-1 % of the DMM'}
  - {id: pulsed_spot_cleanup, recipe: basic.pulsed_spot, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: multi_pulsed_cleanup, recipe: generic.smu_multi_pulsed, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: id_t_gaps, recipe: mosfet.id_t_sampling, quantity: index_gaps, method: kind_result, reference: 'the plan''s interval and points', tolerance: {max_abs: 0.5}, text: 0 skipped samples (grid as set)}
  - {id: id_t_samples, recipe: mosfet.id_t_sampling, quantity: samples_measured, method: kind_result, reference: 'the plan''s points', text: recorded (= points unless aborted)}
  - {id: id_t_tau, recipe: mosfet.id_t_sampling, quantity: tau, method: sampling_summary, unit: s, reference: 'EasyEXPERT or lab script (lwp IVt_sampling) on the same device', tolerance: {rel: 0.15}, text: '+-15 % of the reference fit'}
  - {id: id_t_cleanup, recipe: mosfet.id_t_sampling, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: sampling_gaps, recipe: generic.smu_sampling, quantity: index_gaps, method: kind_result, reference: 'the plan''s interval and points', tolerance: {max_abs: 0.5}, text: 0 skipped samples (grid as set)}
  - {id: sampling_cleanup, recipe: generic.smu_sampling, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: vth_search, recipe: mosfet.vth_search, quantity: vth, method: vth_search_value, unit: V, reference: 'vth_constant_current of the L4 mosfet.idvg run, same criterion and Vd', tolerance: {absolute: 0.005}, text: '+-5 mV of the constant-current Vth'}
  - {id: search_cleanup, recipe: mosfet.vth_search, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
version: 1
---

# L5 - SMU advanced: pulsed, sampling, search

The SMU modes beyond the DC staircase on the L4 reference MOSFET and the 100 kOhm standard: pulsed I-V (MM 3/4/5/27/28,
card `smu-pulsed-iv`), sampling I(t) (MM 10, card `smu-sampling`) and the binary Vth search (MM 15, card
`smu-search`). Each is compared with the DC result of L2/L4 on the same device. QSCV leakage compensation (§7.4)
needs a MOS capacitor and its MFCMU landing: it runs in stage L6 with `moscap.qscv` (card `moscap-dit`). Every
hardware plan needs consent (`first_hw_run`).

## 1. Preconditions

- L4 signed off; `uv run b1500 bringup status` names L5; `station_status` clean; the L4 `mosfet.idvg` and
  `mosfet.idvd` runs of the same die (their `H...` run ids are the DC references) and the L2 100 kOhm standard.
- For `mosfet.id_t_sampling`: the lab's reference transient (EasyEXPERT or the lwp `IVt_sampling` script) of the
  same device and gate step, if the owner has one; else the check is recorded only.

## 2. Physical steps (human)

1. Land the L4 MOSFET as in L4 (pin map `mosfet-l4`, DUT profile `nmos-l4` with a pulse envelope that allows the
   SMU pulse width 1 ms and the period); confirm in chat.
2. For `basic.pulsed_spot`: land the 100 kOhm standard on the L2 pin map `res-smuN` with DUT profile `r100k`; read
   it with the DMM first.
3. Keep EasyEXPERT closed while the agent runs (as in L3/L4).

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status`; note the L4 DC run ids.
2. `mosfet.idvg_pulsed` (width 1 ms, period 100 ms: duty 1 %) on `mosfet-l4`: validate, summary, stop, consent,
   run; `analyze_run(run, pulsed_vs_dc, {reference_run: <L4 mosfet.idvg run>})`. Then `mosfet.idvd_pulsed` the same
   way against the L4 `mosfet.idvd` run.
3. `basic.pulsed_spot` on the 100 kOhm standard: `resistance`; `generic.smu_multi_pulsed` with the card's example
   (two pulsed channels): cleanup and the status counts only.
4. `mosfet.id_t_sampling` with the lab's gate step and interval (card defaults otherwise):
   `get_run` `kind_result` (`index_gaps`, `samples_measured`, `time_source`), `sampling_summary` with the
   stretched-exponential fit. Then `generic.smu_sampling` (card example): the grid only.
5. `mosfet.vth_search` with the L4 criterion (`i_crit_a`, `w_over_l`, Vd): `vth_search_value`; compare with
   `vth_constant_current` of the L4 Id-Vg (same criterion).
6. Report each value as derived (method, window, status counts, backend visa); `time_source` other than
   `timestamp` is a finding (ATV-22 fallback: host or index time), skipped samples go to runbook
   `smu-sampling-skips` of skill `b1500-debug`.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `pulsed_vs_dc` | pulsed/DC current at the largest pulsed Id | 1 +-0.02 at 1 % duty | L4 `mosfet.idvg` |
| `idvd_pulsed_ratio` | pulsed/DC current of the output family | 1 +-0.02 at low duty | L4 `mosfet.idvd` |
| `pulsed_spot_r` | resistance of the standard by pulsed spot | +-1 % of the DMM | DMM |
| `id_t_gaps`, `sampling_gaps` | skipped samples (`kind_result.index_gaps`) | 0 | the plan |
| `id_t_samples` | samples measured | = points (recorded) | the plan |
| `id_t_tau` | tau of the stretched exponential | +-15 % of the reference fit | lab reference |
| `vth_search` | Vth found by the binary search | +-5 mV of the constant-current Vth | L4 `mosfet.idvg` |
| `idvg_pulsed_cleanup`, `idvd_pulsed_cleanup`, `pulsed_spot_cleanup`, `multi_pulsed_cleanup`, `id_t_cleanup`, `sampling_cleanup`, `search_cleanup` | every run `verified: lop` | pass/fail | manifests |

- Pulsed at higher duty or longer width may read below DC (self-heating) or above (trapping): that is physics, not a
  failure of the stage, as long as the low-duty point agrees.
- Sampling: `time_source: timestamp` expected (TSC 1); the timer over long chains is a TODO(verify) item of L9.

## 5. Abort criteria

- Pulsed/DC outside 0.95..1.05 at 1 % duty, any `C`/`T` in the pulsed fit window, a search status `G`/`S` on a
  device whose Vth lies in the range, a sampling run that aborts (`aborted: true`) without compliance in the
  plan, cleanup `unverified`.
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human.

## 6. Record

- Hardware, one record per recipe with checks: `uv run b1500 bringup record L5 --run H... --operator NAME`
  (pulsed runs with their DC reference run in the record's notes; `--reference id_t_tau=<lab value>` and
  `--reference vth_search=<L4 constant-current Vth>`). The human reviews them and moves them to
  `validation/hw/mosfet.idvg_pulsed.yaml`, `validation/hw/mosfet.idvd_pulsed.yaml`,
  `validation/hw/basic.pulsed_spot.yaml`, `validation/hw/generic.smu_multi_pulsed.yaml`,
  `validation/hw/mosfet.id_t_sampling.yaml`, `validation/hw/generic.smu_sampling.yaml`,
  `validation/hw/mosfet.vth_search.yaml`.
- Simulator rehearsal: no record; say which seven records hardware drafts.
