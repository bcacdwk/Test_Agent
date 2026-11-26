---
id: 2026-11-04-cv-shape-abnormal
title: C-V curve not S-shaped
status: draft
reviewed_by: null
runbook: cmu-cv-distortion
backend: visa
station: unknown
device: unknown (group experience; no device recorded)
runs: []
sources: [deck slide 17, PPT_slides_content.md p.18]
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
      deck order and runbook cmu-cv-distortion First safe checks 4 and 5: redo the corrections, then the default AC
      level (moscap.cv_ac_level at the distorted bias gives ac_limit), then measure the gate leakage first
    expect:
      - abs(cv_redone.result('cox') / 6.906e-11 - 1) < 0.01
      - 0.03 < ac_sweep.result('ac_limit') < 0.1
      - abs(cv_default_ac.value_at('gate_Cp', 'dc_v', -0.6) / ac_sweep.result('c_small_signal') - 1) < 0.01
      - leakage.kind('leakage_max_a') > 1.0e-9
      - abs(cv_leaky_1mhz.result('cox') / 6.906e-11 - 1) < 0.01
open_questions: 4
---

# C-V curve not S-shaped

Seeded from the owner's deck (slide 17, "8 Debug经验记录", 2026-11-04; the fourth symptom of the slide, added in
v2.1): a group pitfall recorded before this agent existed. No run, station or device data; the owner reviews and
completes it. The lab facts below are the deck's; the simulator reproduction has its own section.

## Symptom

The C-V curve had an abnormal shape: not the typical S shape.

## Observed data and status codes

Not recorded in the deck (open question 1: device, frequency, AC level and what the curve looked like).

## Physical checks

None listed in the deck for this symptom.

## Instrument checks

- Open/short compensation not done or expired (deck slide 17).
- AC oscillator level too large, so the signal is distorted (deck slide 17).

Deck order: redo the compensation, then lower the AC level, then measure the gate leakage first to judge.

## DUT hypotheses

Gate leakage current too large, so the capacitance measurement is unreliable (deck slide 17).

## Resolution

Not recorded in the deck (open questions 2 and 3).

## Reproducible

Recurring pitfall in the group (the deck lists it as a common problem); counts not recorded.

## Proposed follow-up

Runbook `cmu-cv-distortion` covers the three causes (its causes 1, 4 and 3); v2.1 added the deck's order to its
first safe checks.

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.4 (`git describe` 2b4d4d8-dirty: the tree of the WP21.4 commit), backend sim, all runs
SIMULATED (`S...`, in the local data folder `work/cases/2026-11-04-cv-shape-abnormal/20261126T055826Z/`, not
committed). Regenerate: `uv run b1500 dev cases reproduce 2026-11-04-cv-shape-abnormal`; the authority is
`tests/integration/test_debug_cases.py`. One part per deck cause, on the `moscap_basic` MOS capacitor (Cox 69.06
pF, Vfb -0.86 V; `moscap.cv` 2 to -2.5 V, 1 MHz, pin map `moscap-cmu`) and on `moscap_leaky` (the same capacitor
with a 1 MOhm ohmic oxide leakage, through the SCUU: pin map `moscap-scuu`). Each corrected run had fresh phase,
open and short corrections with its pin map (their run ids are in the folder's `report.json`).

- Compensation lost (fault `cmu_correction_lost` after the first C-V, a module power glitch): the C-V before it is
  normal (`S20261126T055826Z-5fc0`); the next one is refused before any source command because `CORRST?` reads the
  corrections off (`S20261126T055827Z-1a17`, outcome `refused`), and the next validation is blocked by R-CORR-01.
  With this agent a missing or expired correction never yields a distorted curve: the kernel refuses the C-V (the
  deck's curve needs corrections that exist but do not fit the landing: runbook `cmu-correction-stale`, no
  simulator model). Redoing the corrections (deck step 1) restores it: Cox 69.17 pF (`S20261126T055827Z-61c5`).
- AC level too large: at 100 mVrms (`S20261126T055827Z-9213`) the depletion part is smeared: Cp 22.39 pF at
  -0.65 V against 21.69 pF at the default 30 mVrms (`S20261126T055827Z-b22f`), +3.2 %; Cox and Vfb barely move.
  `moscap.cv_ac_level` at -0.6 V (`S20261126T055827Z-4133`) gives ac_limit 56 mVrms (1 % criterion), below the
  100 mVrms used and above the default; at 30 mVrms the C-V agrees with the small-signal C0 there (19.26 against
  19.21 pF): lowering the AC level (deck step 2) removes it.
- Gate leakage: at 1 kHz the leaky capacitor's C-V is not S-shaped (`S20261126T055828Z-18e5`): Cp peaks at 92.6 pF
  at -1.3 V (Cox 69 pF), falls to 78 pF at -2.5 V with D = 1.88 there, and has no accumulation plateau (`cv_cox`
  fails), although the corrections are fresh and the AC level is the default. The leakage check (deck step 3:
  `moscap.qscv` over +-0.5 V, leakage data; `S20261126T055828Z-793b`) reads 0.45 uA, far above the 1 nA guideline
  of DUT profile `moscap-generic`. At 1 MHz the same device is normal (Cox 69.19 pF, `S20261126T055828Z-b941`).
  The model's leakage is ohmic; a real oxide leaks by tunnelling, exponentially in |V|.

## Open questions for the owner

1. Which device, frequency, AC level and sweep, and what did the curve look like (Cmax above Cox, a hump, no
   plateau, stretched)?
2. Which of the three causes was it?
3. Was it resolved, and how?
4. The deck says about ten debug entries were recorded (`PPT_slides_content.md:689`), but its slide lists four
   (these four cases): where are the other six or so, so that they can become cases too?
