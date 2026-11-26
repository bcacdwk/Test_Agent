---
stage: L4
title: Known-good MOSFET - DC set against EasyEXPERT on the same die (Id-Vg, Id-Vd, gate leakage, Id-Vg families)
recipes: [mosfet.idvg, mosfet.idvd, mosfet.gate_leakage, mosfet.idvg_family, mosfet.idvg_sync, mosfet.body_effect]
checks:
  - {id: vth, recipe: mosfet.idvg, quantity: vth, method: vth_linear_extrapolation, unit: V, reference: 'EasyEXPERT export, same die, same method and window', tolerance: {absolute: 0.010}, text: '+-10 mV'}
  - {id: ss, recipe: mosfet.idvg, quantity: ss, method: subthreshold_swing, unit: mV/dec, reference: 'EasyEXPERT export, same die', tolerance: {rel: 0.05}, text: '+-5 %'}
  - {id: idvg_cleanup, recipe: mosfet.idvg, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: approval_prompt, recipe: mosfet.idvg, quantity: approval_prompt, reference: 'the human at the harness approval prompt of the first L4 run (ATV-7, ATV-11)', text: 'the prompt appeared in the default mode and showed the summary of the chat'}
  - {id: ron, recipe: mosfet.idvd, quantity: ron, method: output_metrics, unit: Ohm, reference: 'EasyEXPERT export, same curve', tolerance: {rel: 0.05}, text: '+-5 % (provisional)'}
  - {id: idvd_cleanup, recipe: mosfet.idvd, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: gate_leakage, recipe: mosfet.gate_leakage, quantity: leakage, method: leakage_at, unit: A, reference: EasyEXPERT Ig at the same bias, tolerance: {factor: 2}, text: 'within a factor 2 (both above 10 pA; provisional)'}
  - {id: leakage_cleanup, recipe: mosfet.gate_leakage, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: dibl, recipe: mosfet.idvg_family, quantity: dibl, method: dibl, unit: mV/V, reference: 'EasyEXPERT constant-current Vth at the same drain biases, same die', tolerance: {absolute: 5.0}, text: '+-5 mV/V (provisional)'}
  - {id: family_cleanup, recipe: mosfet.idvg_family, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: vth_sync, recipe: mosfet.idvg_sync, quantity: vth, method: vth_constant_current, unit: V, reference: 'EasyEXPERT synchronous sweep with the same drain ends, same criterion', tolerance: {absolute: 0.010}, text: '+-10 mV (provisional)'}
  - {id: sync_cleanup, recipe: mosfet.idvg_sync, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: body_effect, recipe: mosfet.body_effect, quantity: body_effect, method: body_effect, reference: 'EasyEXPERT Vth at the same body biases', tolerance: {absolute: 0.02}, text: '+-0.02 V/V (provisional)'}
  - {id: body_cleanup, recipe: mosfet.body_effect, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
version: 1
---

# L4 - Known-good MOSFET

The v1 MOSFET set on a reference transistor, compared with EasyEXPERT on the same die and wiring: `mosfet.idvg`
(card `mosfet-idvg`), `mosfet.idvd` (`mosfet-idvd`), `mosfet.gate_leakage` (`gate-leakage`), then the Id-Vg variants
of the `mosfet-idvg` card: `mosfet.idvg_family` (DIBL), `mosfet.idvg_sync` (Vd follows Vg) and `mosfet.body_effect` (bulk
on an SMU). Every hardware plan needs consent (`first_hw_run`); this is also where the human checks the harness
approval prompt.

## 1. Preconditions

- L3 signed off; `uv run b1500 bringup status` names L4; `station_status` clean.
- A known-good n-MOSFET (discrete or on-wafer reference) with its ratings; EasyEXPERT exports from the same day on
  the same wiring with the sweeps of the agent's plans, e.g. the recipe defaults (examples, not device values): Id-Vg
  at Vd = 0.05 V, Vg -1 to 3 V, 101 points; Id-Vd with Vg 0.5 to 1.5 V in 5 steps, Vd 0 to 3 V, 101 points; Ig-Vg
  0 to 3 V; about 1 PLC (the lab's own Id-Vg script ran Vd 0.1 V, Vg -2 to 2 V, 61 points, 10 ms delay:
  `lwp/matlab_B1500/test_IdVg.m`; then the plans take that sweep).

## 2. Physical steps (human)

1. Land the MOSFET: gate and drain on HRSMUs (the gate-leakage recipe needs an HRSMU gate), source and bulk on
   GNDU; shield box closed.
2. Adopt the pin map `mosfet-l4` (copy of `mosfet-4t`, `certainty: unverified` until checked) and the DUT profile
   `nmos-l4` (copy of `nmos-generic` with the device's real limits): `uv run b1500 config adopt FILE --as pinmap`,
   `--as dut`.
3. Switch between EasyEXPERT and the agent as in L3 (Go to Local & Close, then back with File > Exit).
4. Approval prompt (ATV-11, ATV-7): when the harness asks to approve `run_confirmed_plan`, compare the summary in
   the prompt with the one the agent printed in chat, then approve. Report whether the prompt showed the summary
   and whether it appeared at all.
5. Before `mosfet.body_effect`: move the bulk contact (well probe or chuck) from GNDU to an SMU and adopt the pin
   map `mosfet-l4b` (copy of `mosfet-4t-body`, `unverified` until checked); the DUT profile names the bulk limits.

## 3. Agent steps

1. `uv run b1500 bringup status`; propose the pin map and DUT profile under `work/bringup/`; hand the adoption
   over and stop.
2. `mosfet.idvg` with pin map `mosfet-l4`, DUT profile `nmos-l4` and the export's sweep
   (`params {vg_start: -1, vg_stop: 3, vg_points: 101, vd: 0.05}`): `validate_plan`, summary, stop, consent,
   `run_confirmed_plan`; `analyze_run` with `vth_linear_extrapolation` (max-gm window, Vd/2 subtracted) and
   `subthreshold_swing`.
3. `mosfet.idvd` with the export's gate steps and Vd range: same flow; `analyze_run` with `output_metrics`.
4. `mosfet.gate_leakage` with the defaults: same flow; `leakage_at` at the operating bias.
5. `mosfet.idvg_family`, `mosfet.idvg_sync` (pin map `mosfet-l4`) and `mosfet.body_effect` (pin map `mosfet-l4b`,
   the bulk on an SMU; the human lands and adopts it) with the defaults: same flow; `dibl`, `vth_constant_current`,
   `body_effect` (constant-current Vth, 100 nA).
6. Report every value as derived (method, fit window), the status counts and backend visa; ask the human for the
   EasyEXPERT values of the same quantities, computed with the same method and window (or say which EasyEXPERT
   function they used).
7. Hardware: one record per recipe (section 6).

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `vth` | Vth of `vth_linear_extrapolation` | +-10 mV of EasyEXPERT, same method | `mosfet.idvg` |
| `ss` | minimum subthreshold swing | +-5 % of EasyEXPERT | `mosfet.idvg` |
| `idvg_cleanup` | every run `verified: lop` | pass/fail | manifests |
| `approval_prompt` | the harness prompt appeared in the default mode and showed the chat's summary | pass/fail | the human (physical step 4) |
| `ron` | Ron of the strongest curve (`output_metrics`) | +-5 % of EasyEXPERT (provisional) | `mosfet.idvd` |
| `idvd_cleanup` | every run `verified: lop` | pass/fail | manifests |
| `gate_leakage` | Ig at the operating bias (`leakage_at` passes its limit) | factor 2 of EasyEXPERT when both above 10 pA (provisional) | `mosfet.gate_leakage` |
| `leakage_cleanup` | every run `verified: lop` | pass/fail | manifests |
| `dibl` | DIBL of the family (lowest vs highest Vd) | +-5 mV/V of EasyEXPERT, same criterion (provisional) | `mosfet.idvg_family` |
| `vth_sync` | constant-current Vth, drain following the gate | +-10 mV of EasyEXPERT (provisional) | `mosfet.idvg_sync` |
| `body_effect` | dVth/dVsb over the body biases | +-0.02 V/V of EasyEXPERT (provisional) | `mosfet.body_effect` |
| `family_cleanup`, `sync_cleanup`, `body_cleanup` | every run `verified: lop` | pass/fail | manifests |

- Every run: quality `ok`, error queue empty; Id at three gate voltages above Vth within +-2 % of the export
  (provisional).
- Basis: `vth` +-10 mV and `ss` +-5 % are the blueprint v2 7.4 L4 defaults (the owner may tighten); the others are
  provisional criteria (basis: none). All assume a stable Si reference; another device (the lab's only Id-Vg on
  record shows about 210 mV/dec, knowledge 01 "MOSFET subthreshold swing") needs the owner's values. `TODO(owner)`:
  which known-good transistor is the L4 reference, and which tolerances against EasyEXPERT does the lab accept for
  `ron`, `gate_leakage`, `dibl`, `vth_sync`, `body_effect` and the Id points?
- ATV-11: the approval prompt shows the `summary` argument. Fallback: approve only after comparing the summary the
  agent printed in chat; record it (`approval_prompt`). ATV-7 (Claude Code): the prompt appears in the default
  permission mode. Fallback: the policy flag `confirmation.claude_require_user_interaction: true`; with no prompt
  at all, do not use that harness for hardware runs.
- TODO(verify) (blueprint v2 7.6 items 6, 11, 12): Vth, SS and Id against EasyEXPERT on the same die (the golden
  comparison, item 11); the approval-prompt facts above (ATV-7, ATV-11, `approval_prompt`); the ASU path (ATV-28 for
  the switches): the `asu` option of `mosfet.gate_leakage` runs only where L0 recorded `ASU3`/`ASU4` `present: true`
  (else blocked).

## 5. Abort criteria

- Any deviation above twice the tolerance; gate current near its compliance; cleanup `unverified`; a run without
  the human's consent or without the approval prompt (stop using that harness; record it).
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human.

## 6. Record

- Hardware, one recipe record each, with the human's EasyEXPERT values as references:
  `uv run b1500 bringup record L4 --run H... --reference vth=<EasyEXPERT V> --reference ss=<EasyEXPERT mV/dec>
  --operator NAME`, likewise `--reference ron=<EasyEXPERT Ohm>` and `--reference gate_leakage=<EasyEXPERT A>`.
  The human reviews them and moves them to `validation/hw/mosfet.idvg.yaml`, `validation/hw/mosfet.idvd.yaml`,
  `validation/hw/mosfet.gate_leakage.yaml`; the variants likewise (`--reference dibl=<EasyEXPERT mV/V>`,
  `vth_sync=<EasyEXPERT V>`, `body_effect=<EasyEXPERT V/V>`) to `validation/hw/mosfet.idvg_family.yaml`,
  `validation/hw/mosfet.idvg_sync.yaml`, `validation/hw/mosfet.body_effect.yaml`; promotions to `hw_validated` are a
  later developer change.
- `generic.smu_staircase` (ad hoc) and `fefet.dual_sweep_mw` (L7) are not validated here.
- Simulator rehearsal: no record; say which six records hardware drafts.
