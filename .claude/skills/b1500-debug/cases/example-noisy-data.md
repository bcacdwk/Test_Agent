---
id: example-noisy-data
title: "Example: Large noise and point-to-point scatter"
status: draft
reviewed_by: null
runbook: noisy-data
origin: illustrative
backend: none
station: none
device: any (illustrative; no device)
runs: []
sources: ["owner planning deck slide 17 (PPT_slides_content.md p.18): an illustrative list, not a lab record"]
reproduction:
  scenario: nmos_unshielded
  steps:
    - {id: landed_contact, recipe: basic.contact_resistor, pin_map: resistor-2t, dut_profile: resistor-generic}
    - {id: landed_idvg, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic}
    - {id: symptom, recipe: mosfet.gate_leakage, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {integration: short}}
    - {id: medium, recipe: mosfet.gate_leakage, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {integration: medium}}
    - {id: long, recipe: mosfet.gate_leakage, pin_map: mosfet-4t, dut_profile: nmos-generic,
       params: {integration: long}}
    - {id: unlanded_contact, scenario: open_drain_noisy, recipe: basic.contact_resistor, pin_map: resistor-2t,
       dut_profile: resistor-generic}
    - {id: unlanded_idvg, scenario: open_drain_noisy, recipe: mosfet.idvg, pin_map: mosfet-4t,
       dut_profile: nmos-generic}
    - {id: unlanded_long, scenario: open_drain_noisy, recipe: mosfet.idvg, pin_map: mosfet-4t,
       dut_profile: nmos-generic, params: {integration: long}}
  expect:
    - symptom.snr('gate_I') < 10
    - unlanded_idvg.snr('drain_I') < 10
  discriminator:
    check: >-
      runbook noisy-data, First safe checks 3 and 4: contact check and the device's own response first (landed or
      not), then the same plan with a longer integration
    expect:
      - landed_contact.classification('resistance') == 'open' and unlanded_contact.classification('resistance') == 'open'
      - landed_idvg.snr('drain_I') >= 10
      - symptom.snr('gate_I') < medium.snr('gate_I') < long.snr('gate_I')
      - long.snr('gate_I') >= 10
      - unlanded_long.snr('drain_I') < 10
open_questions: 2
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Example: Large noise and point-to-point scatter

Illustrative example, not an observed lab case: written from a troubleshooting list in the owner's planning deck,
which shows the kind of problem a lab meets, not a recorded event. No run, station, device or date was observed. The
causes are general practice; the simulator section shows how the runbook separates them (SIMULATED).

## Symptom

Example symptom: the data are very noisy, with clear fluctuation from point to point.

## Observed data and status codes

None (illustrative).

## Physical checks

- Shield box not closed, environmental interference (general practice).
- Poor grounding (general practice).

## Instrument checks

Integration time set too short (general practice: a longer integration averages more of the noise).

## DUT hypotheses

None: every listed cause is a station or setup cause. An unlanded probe also reads as pure noise (simulator
scenario `open_drain_noisy`), which is why the runbook checks the contact first.

## Resolution

Not applicable (illustrative).

## Reproducible

Not observed in the lab.

## Proposed follow-up

Runbook `noisy-data` rests on general practice, not on this example: contact check first, then a longer
integration, then the shield box and grounding. Whether the lab works in that order is open question 2.

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.11 (commit 9589796 plus this WP's uncommitted edits), backend sim, all runs SIMULATED
(`S...`, in the local data folder `work/cases/example-noisy-data/20261126T114154Z/`, not committed). Regenerate:
`uv run b1500 dev cases reproduce example-noisy-data`; the authority is `tests/integration/test_debug_cases.py`. Two
devices (simulator examples, not real-device values): `nmos_unshielded` (the `nmos_basic` transistor, landed, in an
open shield box: SMU floor raised to 5 pA on the HRSMU, gate leakage 1e-11 S) and `open_drain_noisy` (the drain
probe not landed, same raised floor). Grounding and real interference (50 Hz, ground loops) have no model: the
simulator's floor is white noise.

- Symptom: `mosfet.gate_leakage` with `integration: short` on the landed device, run `S20261126T114154Z-a440`: the
  gate current (0 to 30 pA over 0 to 3 V) has SNR 3.9, below 10 (at the noise floor). The Id-Vg of the unlanded
  device (`S20261126T114154Z-9e90`, medium integration) looks the same: drain SNR 4.6.
- Discriminator (runbook order): both contact checks (`resistor-2t`, drain to source) read `open`
  (`S20261126T114154Z-67f7` landed, `S20261126T114154Z-0896` unlanded), as a transistor pair does, so the device's
  own response decides: the landed Id-Vg has drain SNR 3599 (`S20261126T114154Z-c0d8`), the unlanded one stays at
  the floor. On the landed device a longer integration resolves the gate current: SNR 3.9 (short), 7.4 (medium,
  `S20261126T114154Z-8f57`), 20.4 (long, `S20261126T114154Z-c984`). On the unlanded device it does not: drain SNR
  5.9 with `integration: long` (`S20261126T114155Z-36c3`): re-land, no re-run helps.

## Open questions for the owner

1. Has the lab seen this problem? If yes, record it as an observed case (date, device, runs, what fixed it).
2. Does the lab check the probe contact before it lengthens the integration time and checks the shield box and
   grounding (the runbook's order), or does it work in another order?
