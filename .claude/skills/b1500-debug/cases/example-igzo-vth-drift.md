---
id: example-igzo-vth-drift
title: "Example: IGZO TFT Vth differs with every measurement"
status: draft
reviewed_by: null
runbook: vth-drift-igzo
origin: illustrative
backend: none
station: none
device: igzo_tft (illustrative; no device)
runs: []
sources: ["owner planning deck slide 17 (PPT_slides_content.md p.18): an illustrative list, not a lab record"]
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
      runbook vth-drift-igzo, First safe checks 4: a narrower gate sweep, then fewer points (a shorter sweep), each
      series on a rested device
    expect:
      - narrow_3.result('vth') - narrow_1.result('vth') < third.result('vth') - first.result('vth')
      - short_3.result('vth') - short_1.result('vth') < narrow_3.result('vth') - narrow_1.result('vth')
open_questions: 2
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Example: IGZO TFT Vth differs with every measurement

Illustrative example, not an observed lab case: written from a troubleshooting list in the owner's planning deck,
which shows the kind of problem a lab meets, not a recorded event. No run, station, device or date was observed. The
causes are general practice; the simulator section shows how the runbook separates them (SIMULATED).

## Symptom

Example symptom: the Vth of an IGZO TFT differs every time it is measured.

## Observed data and status codes

None (illustrative).

## Physical checks

Ambient temperature and humidity first (general practice).

## Instrument checks

After the environment: a narrower sweep voltage range, then a shorter measurement time (general practice: less
stress per run).

## DUT hypotheses

- Water adsorption or desorption changes the back-channel potential (general knowledge, not checked against a
  source).
- The voltage stress of the measurement itself shifts Vth (general knowledge).
- Temperature dependence (mechanism and size: `TODO(cite)`).

## Resolution

Not applicable (illustrative).

## Reproducible

Not observed in the lab.

## Proposed follow-up

Runbook `vth-drift-igzo` rests on general practice, not on this example. A rest time between sweeps (open question
2) and a maximum gate range for IGZO Id-Vg would become a card recommendation once validated on the lab's devices.

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.11 (commit 9589796 plus this WP's uncommitted edits), backend sim, all runs SIMULATED
(`S...`, in the local data folder `work/cases/example-igzo-vth-drift/20261126T114156Z/`, not committed). Regenerate:
`uv run b1500 dev cases reproduce example-igzo-vth-drift`; the authority is `tests/integration/test_debug_cases.py`.
It models only the second DUT hypothesis (the measurement as a bias stress): scenario `igzo_drift_repeat`, the
`igzo_transient` TFT (simulator parameters, not IGZO data: Vth0 0.8 V; drift towards 0.05 V per volt of gate bias,
tau 4 s, beta 0.5) whose every DC sweep step ages it, with a 1 h recovery. Moisture, temperature and light have no
model. `igzo_transient` itself is the control: in the simulator a DC sweep of it is a quasi-static read (ATV-37,
WP21.4), so its Vth does not move from run to run.

- Symptom: three back-to-back `mosfet.idvg` runs (0 to 3 V, 101 points, `mosfet-4t`) give Vth 0.878, 0.929 and
  0.942 V (`S20261126T114156Z-73d7`, `S20261126T114156Z-ecfc`, `S20261126T114156Z-b871`): +51 mV and +13 mV, each
  above three times the run-to-run spread of the same plan on the control (0.8659, 0.8664, 0.8659 V, 0.5 mV;
  `S20261126T114156Z-b0f9`, `S20261126T114156Z-4e62`, `S20261126T114156Z-c96f`). Each run starts where the last
  one left the device.
- Discriminator (runbook order, each series on a rested device): a sweep only to 1.5 V shifts Vth by 23.7 mV over
  three runs (0.884 to 0.908 V, `S20261126T114156Z-4132` to `S20261126T114157Z-ecd3`) instead of 64.2 mV; the same
  narrow sweep with 41 instead of 101 points (a shorter sweep) by 16.6 mV (0.876 to 0.893 V,
  `S20261126T114157Z-3544` to `S20261126T114157Z-92be`). Smaller stress, smaller drift: the measurement drives it.

## Open questions for the owner

1. Has the lab seen this problem? If yes, record it as an observed case (date, device, runs, what fixed it).
2. What rest time between IGZO Id-Vg sweeps does the lab use, so that one measurement does not shift the next?
   (The oxide-TFT bias ranges are asked once, in `b1500-test/knowledge/04-ferroelectric-oxide.md`.)
