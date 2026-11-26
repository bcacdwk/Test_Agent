---
id: 2026-11-04-igzo-vth-drift
title: IGZO TFT Vth differs with every measurement
status: draft
reviewed_by: null
runbook: vth-drift-igzo
backend: visa
station: unknown
device: igzo_tft (group experience; no device recorded)
runs: []
sources: [deck slide 17, PPT_slides_content.md p.18]
reproduction:
  scenario: igzo_drift_repeat
  scenarios:
    rested_narrow: {base: igzo_drift_repeat}
    rested_short: {base: igzo_drift_repeat}
  steps:
    - {id: first, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0}}
    - {id: second, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0}}
    - {id: third, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0}}
    - {id: control_1, scenario: igzo_transient, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0}}
    - {id: control_2, scenario: igzo_transient, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0}}
    - {id: control_3, scenario: igzo_transient, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0}}
    - {id: narrow_1, scenario: rested_narrow, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0, vg_stop: 1.5}}
    - {id: narrow_2, scenario: rested_narrow, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0, vg_stop: 1.5}}
    - {id: narrow_3, scenario: rested_narrow, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0, vg_stop: 1.5}}
    - {id: short_1, scenario: rested_short, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0, vg_stop: 1.5, vg_points: 41}}
    - {id: short_2, scenario: rested_short, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0, vg_stop: 1.5, vg_points: 41}}
    - {id: short_3, scenario: rested_short, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {vg_start: 0.0, vg_stop: 1.5, vg_points: 41}}
  expect:
    - first.result('vth') < second.result('vth') < third.result('vth')
    - >-
      min(second.result('vth') - first.result('vth'), third.result('vth') - second.result('vth'))
      > 3 * (max(control_1.result('vth'), control_2.result('vth'), control_3.result('vth'))
      - min(control_1.result('vth'), control_2.result('vth'), control_3.result('vth')))
  discriminator:
    check: >-
      runbook vth-drift-igzo, First safe checks 4 (deck order steps 2 and 3): a narrower gate sweep, then fewer
      points (a shorter sweep), each series on a rested device
    expect:
      - narrow_3.result('vth') - narrow_1.result('vth') < third.result('vth') - first.result('vth')
      - short_3.result('vth') - short_1.result('vth') < narrow_3.result('vth') - narrow_1.result('vth')
open_questions: 6
---

# IGZO TFT Vth differs with every measurement

Seeded from the owner's deck (slide 17, "8 Debug经验记录", 2026-11-04): a group pitfall recorded before this agent
existed. No run, station or device data; the owner reviews and completes it. The lab facts below are the deck's;
the simulator reproduction has its own section.

## Symptom

The Vth of an IGZO TFT was different every time it was measured.

## Observed data and status codes

Not recorded in the deck (open questions 1 to 3: size and direction of the shift, sweep range, time between runs).

## Physical checks

Deck order: control ambient temperature and humidity first.

## Instrument checks

Deck order after the environment: reduce the sweep voltage range, then shorten the measurement time.

## DUT hypotheses

- Water adsorption or desorption changes the back-channel potential (deck slide 17).
- The voltage stress of the measurement itself shifts Vth (deck slide 17).
- Temperature changes alter the oxygen-vacancy concentration (deck text only).

## Resolution

Not recorded in the deck (open question 6).

## Reproducible

Recurring pitfall in the group (the deck lists it as a common problem); counts not recorded.

## Proposed follow-up

Basis of runbook `vth-drift-igzo`. A recommended rest time between sweeps and a maximum gate range for IGZO Id-Vg
(open question 4) would become a card recommendation once validated.

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.4 (`git describe` 2b4d4d8-dirty: the tree of the WP21.4 commit), backend sim, all runs
SIMULATED (`S...`, in the local data folder `work/cases/2026-11-04-igzo-vth-drift/20261126T055824Z/`, not
committed). Regenerate: `uv run b1500 dev cases reproduce 2026-11-04-igzo-vth-drift`; the authority is
`tests/integration/test_debug_cases.py`. It models only the second DUT hypothesis (the measurement as a bias
stress): scenario `igzo_drift_repeat`, the `igzo_transient` TFT (Vth0 0.8 V; drift towards 0.05 V per volt of gate
bias, tau 4 s, beta 0.5) whose every DC sweep step ages it, with a 1 h recovery. Moisture, temperature and light
have no model. `igzo_transient` itself is the control: in the simulator a DC sweep of it is a quasi-static read
(ATV-37, WP21.4), so its Vth does not move from run to run.

- Symptom: three back-to-back `mosfet.idvg` runs (0 to 3 V, 101 points, `mosfet-4t`) give Vth 0.878, 0.929 and
  0.942 V (`S20261126T055824Z-83b3`, `S20261126T055824Z-1847`, `S20261126T055824Z-eebe`): +51 mV and +13 mV, each
  above three times the run-to-run spread of the same plan on the control (0.8659, 0.8664, 0.8659 V, 0.5 mV;
  `S20261126T055824Z-6659`, `S20261126T055824Z-b3d5`, `S20261126T055825Z-61b1`). Each run starts where the last
  one left the device.
- Discriminator (deck steps 2 and 3, each series on a rested device): a sweep only to 1.5 V shifts Vth by 23.7 mV
  over three runs (0.884 to 0.908 V, `S20261126T055825Z-b423` to `S20261126T055825Z-05bb`) instead of 64.2 mV; the
  same narrow sweep with 41 instead of 101 points (a shorter sweep) by 16.6 mV (0.876 to 0.893 V,
  `S20261126T055825Z-0457` to `S20261126T055825Z-11b6`). Smaller stress, smaller drift: the measurement drives it.

## Open questions for the owner

1. How large was the shift, and in which direction (Vth up or down from run to run)?
2. Which sweep range and number of points (and integration time) were used?
3. How much time passed between the runs?
4. What rest time between sweeps and what maximum gate range do you recommend for IGZO Id-Vg (a card
   recommendation once validated)?
5. Can light on the sample (microscope lamp) be a cause here (runbook `vth-drift-igzo`, cause 4)?
6. Was it resolved, and which step helped (environment, sweep range, measurement time)?
