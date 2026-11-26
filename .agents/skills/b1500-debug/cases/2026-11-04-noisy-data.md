---
id: 2026-11-04-noisy-data
title: Large noise and point-to-point scatter
status: draft
reviewed_by: null
runbook: noisy-data
backend: visa
station: unknown
device: unknown (group experience; no device recorded)
runs: []
sources: [deck slide 17, PPT_slides_content.md p.18]
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
      not), then the same plan with a longer integration (deck step 1)
    expect:
      - landed_contact.classification('resistance') == 'open' and unlanded_contact.classification('resistance') == 'open'
      - landed_idvg.snr('drain_I') >= 10
      - symptom.snr('gate_I') < medium.snr('gate_I') < long.snr('gate_I')
      - long.snr('gate_I') >= 10
      - unlanded_long.snr('drain_I') < 10
open_questions: 5
---

# Large noise and point-to-point scatter

Seeded from the owner's deck (slide 17, "8 Debug经验记录", 2026-11-04): a group pitfall recorded before this agent
existed. No run, station or device data; the owner reviews and completes it. The lab facts below are the deck's;
the simulator reproduction has its own section.

## Symptom

The data were very noisy, with clear fluctuation from point to point.

## Observed data and status codes

Not recorded in the deck (open questions 1 to 3: current level, module, integration setting).

## Physical checks

- Shield box not closed, environmental interference (deck slide 17).
- Poor grounding (deck text only).

Deck order: after a longer integration time, close the shield box, then check grounding.

## Instrument checks

Integration time set too short (deck slide 17). The deck's order starts here: lengthen the integration time.

## DUT hypotheses

None in the deck: every listed cause is a station or setup cause.

## Resolution

Not recorded in the deck (open question 5).

## Reproducible

Recurring pitfall in the group (the deck lists it as a common problem); counts not recorded.

## Proposed follow-up

Basis of runbook `noisy-data`. The runbook adds a contact check before the deck's steps, because an unlanded probe
also reads as pure noise (simulator scenario `open_drain_noisy`); whether that is the lab's order is open
question 4.

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.4 (`git describe` 2b4d4d8-dirty: the tree of the WP21.4 commit), backend sim, all runs
SIMULATED (`S...`, in the local data folder `work/cases/2026-11-04-noisy-data/20261126T055822Z/`, not committed).
Regenerate: `uv run b1500 dev cases reproduce 2026-11-04-noisy-data`; the authority is
`tests/integration/test_debug_cases.py`. Two devices: `nmos_unshielded` (the `nmos_basic` transistor, landed, in an
open shield box: SMU floor raised to 5 pA on the HRSMU, gate leakage 1e-11 S) and `open_drain_noisy` (the drain
probe not landed, same raised floor). Grounding and real interference (50 Hz, ground loops) have no model: the
simulator's floor is white noise.

- Symptom: `mosfet.gate_leakage` with `integration: short` on the landed device, run `S20261126T055823Z-d6d0`: the
  gate current (0 to 30 pA over 0 to 3 V) has SNR 3.9, below 10 (at the noise floor). The Id-Vg of the unlanded
  device (`S20261126T055823Z-70be`, medium integration) looks the same: drain SNR 4.6.
- Discriminator (runbook order): both contact checks (`resistor-2t`, drain to source) read `open`
  (`S20261126T055822Z-523b` landed, `S20261126T055823Z-5536` unlanded), as a transistor pair does, so the device's
  own response decides: the landed Id-Vg has drain SNR 3599 (`S20261126T055823Z-9ac8`), the unlanded one stays at
  the floor. On the landed device a longer integration (deck step 1) resolves the gate current: SNR 3.9 (short),
  7.4 (medium, `S20261126T055823Z-b538`), 20.4 (long, `S20261126T055823Z-f452`). On the unlanded device it does
  not: drain SNR 5.9 with `integration: long` (`S20261126T055823Z-19ce`): re-land, no re-run helps.

## Open questions for the owner

1. At what current level was the data noisy (and over which bias range)?
2. Which module measured it (MPSMU or HRSMU, with or without ASU)?
3. Which integration setting was used?
4. Is "contact check before the deck's steps" the lab's order too?
5. Was it resolved, and which step fixed it (integration time, shield box, grounding)?
