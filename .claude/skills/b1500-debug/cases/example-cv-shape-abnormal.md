---
id: example-cv-shape-abnormal
title: "Example: C-V curve not S-shaped"
status: draft
reviewed_by: null
runbook: cmu-cv-distortion
origin: illustrative
backend: none
station: none
device: moscap (illustrative; no device)
runs: []
sources: ["owner planning deck slide 17 (PPT_slides_content.md p.18): an illustrative list, not a lab record"]
reproduction:
  scenario: moscap_basic
  scenarios:
    glitch: {base: moscap_basic, faults: [{kind: cmu_correction_lost, after_cmd: XE}]}
  steps:
    - {id: cv_fresh, scenario: glitch, recipe: moscap.cv, pin_map: moscap-cmu, dut_profile: moscap-generic,
       corrections: true}
    - {id: cv_lost, scenario: glitch, recipe: moscap.cv, pin_map: moscap-cmu, dut_profile: moscap-generic}
    - {id: cv_blocked, scenario: glitch, recipe: moscap.cv, pin_map: moscap-cmu, dut_profile: moscap-generic}
    - {id: cv_redone, scenario: glitch, recipe: moscap.cv, pin_map: moscap-cmu, dut_profile: moscap-generic,
       corrections: true}
    - {id: cv_high_ac, recipe: moscap.cv, pin_map: moscap-cmu, dut_profile: moscap-generic, corrections: true,
       params: {ac_vrms: 0.1}}
    - {id: ac_sweep, recipe: moscap.cv_ac_level, pin_map: moscap-cmu, dut_profile: moscap-generic}
    - {id: cv_default_ac, recipe: moscap.cv, pin_map: moscap-cmu, dut_profile: moscap-generic}
    - {id: cv_leaky, scenario: moscap_leaky, recipe: moscap.cv, pin_map: moscap-scuu, dut_profile: moscap-generic,
       corrections: true, params: {freqs_hz: [1000.0]},
       analyze: [{method: impedance_convert, options: {to: cp_d, at_v: -2.5}}]}
    - {id: leakage, scenario: moscap_leaky, recipe: moscap.qscv, pin_map: moscap-scuu, dut_profile: moscap-generic,
       params: {v_start: 0.5, v_stop: -0.5, irange_a: 1.0e-6, leakage: data}}
    - {id: cv_leaky_1mhz, scenario: moscap_leaky, recipe: moscap.cv, pin_map: moscap-scuu,
       dut_profile: moscap-generic}
  expect:
    - cv_fresh.outcome == 'completed' and cv_lost.outcome == 'refused' and 'R-CORR-01' in cv_blocked.blocked_by
    - abs(cv_high_ac.value_at('gate_Cp', 'dc_v', -0.65) / cv_default_ac.value_at('gate_Cp', 'dc_v', -0.65) - 1) > 0.02
    - cv_leaky.value_at('gate_Cp', 'dc_v', -1.3) > 1.25 * 6.906e-11 and cv_leaky.result('d') > 1
  discriminator:
    check: >-
      runbook cmu-cv-distortion First safe checks 4 and 5 (general practice): redo the corrections, then the default
      AC level (moscap.cv_ac_level at the distorted bias gives ac_limit), then measure the gate leakage first
    expect:
      - abs(cv_redone.result('cox') / 6.906e-11 - 1) < 0.01
      - 0.03 < ac_sweep.result('ac_limit') < 0.1
      - abs(cv_default_ac.value_at('gate_Cp', 'dc_v', -0.6) / ac_sweep.result('c_small_signal') - 1) < 0.01
      - leakage.kind('leakage_max_a') / 0.5 > 0.1 * 6283.2 * 6.906e-11
      - abs(cv_leaky_1mhz.result('cox') / 6.906e-11 - 1) < 0.01
open_questions: 2
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Example: C-V curve not S-shaped

Illustrative example, not an observed lab case: written from a troubleshooting list in the owner's planning deck,
which shows the kind of problem a lab meets, not a recorded event. No run, station, device or date was observed. The
causes are general practice; the simulator section shows how the runbook separates them (SIMULATED).

## Symptom

Example symptom: the C-V curve has an abnormal shape, not the typical S shape of a MOS capacitor.

## Observed data and status codes

None (illustrative).

## Physical checks

None specific to this symptom; the runbook's physical checks apply.

## Instrument checks

- Open/short compensation not done, or no longer fitting the landing (general practice).
- AC oscillator level too large, so the signal is distorted (general practice).

Order (general practice): redo the compensation, then lower the AC level, then measure the gate leakage first to
judge.

## DUT hypotheses

Gate leakage too large compared with the capacitive current, so the capacitance reading is unreliable (general
practice: what matters is the leakage conductance against wC at the measurement frequency, not a fixed current).

## Resolution

Not applicable (illustrative).

## Reproducible

Not observed in the lab.

## Proposed follow-up

Runbook `cmu-cv-distortion` covers the three causes (its causes 1, 4 and 3) and rests on general practice, not on
this example.

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.11 (commit 9589796 plus this WP's uncommitted edits), backend sim, all runs SIMULATED
(`S...`, in the local data folder `work/cases/example-cv-shape-abnormal/20261126T114158Z/`, not committed).
Regenerate: `uv run b1500 dev cases reproduce example-cv-shape-abnormal`; the authority is
`tests/integration/test_debug_cases.py`. One part per cause above, on the `moscap_basic` MOS capacitor (simulator
example, not a real-device value: Cox 69.06 pF, Vfb -0.86 V; `moscap.cv` 2 to -2.5 V, 1 MHz, pin map `moscap-cmu`)
and on `moscap_leaky` (the same capacitor with a 1 MOhm ohmic oxide leakage, through the SCUU: pin map
`moscap-scuu`). Each corrected run had fresh phase, open and short corrections with its pin map (their run ids are
in the folder's `report.json`).

- Compensation lost (fault `cmu_correction_lost` after the first C-V, a module power glitch): the C-V before it is
  normal (`S20261126T114158Z-1c52`); the next one is refused before any source command because `CORRST?` reads the
  corrections off (`S20261126T114159Z-042b`, outcome `refused`), and the next validation is blocked by R-CORR-01.
  With this agent a missing correction never yields a distorted curve: the kernel refuses the C-V. Corrections
  that exist but do not fit the landing (runbook `cmu-correction-stale`) have no simulator model. Redoing the
  corrections (the first step of the order) restores it: Cox 69.17 pF (`S20261126T114159Z-34cc`).
- AC level too large: at 100 mVrms (`S20261126T114159Z-f3af`) the depletion part is smeared: Cp 22.39 pF at
  -0.65 V against 21.69 pF at the default 30 mVrms (`S20261126T114159Z-fb1e`), +3.2 %; Cox and Vfb barely move.
  `moscap.cv_ac_level` at -0.6 V (`S20261126T114159Z-0a19`) gives ac_limit 56 mVrms (1 % criterion), below the
  100 mVrms used and above the default; at 30 mVrms the C-V agrees with the small-signal C0 there (19.26 against
  19.21 pF): lowering the AC level (the second step) removes it.
- Gate leakage: at 1 kHz the leaky capacitor's C-V is not S-shaped (`S20261126T114200Z-2ae1`): Cp peaks at 92.6 pF
  at -1.3 V (Cox 69 pF), falls to 78 pF at -2.5 V with D = 1.88 there, and has no accumulation plateau (`cv_cox`
  fails), although the corrections are fresh and the AC level is the default. The leakage check (the third step:
  `moscap.qscv` over +-0.5 V, leakage data; `S20261126T114200Z-8230`) reads 0.45 uA, a conductance of about 0.9 uS
  against wC = 0.43 uS of Cox at 1 kHz: D = G/(wC) above 1, so Cp is unreliable there (the criterion is G against
  wC at the measurement frequency, not a fixed leakage current). At 1 MHz the same device is normal (Cox 69.19 pF,
  `S20261126T114200Z-2664`). The model's leakage is ohmic; a real oxide leaks by tunnelling, exponentially in |V|.

## Open questions for the owner

1. Has the lab seen this problem? If yes, record it as an observed case (date, device, runs, what fixed it).
2. Does the lab keep real debug records (notebook, chat, files)? Each observed problem can become a case.
