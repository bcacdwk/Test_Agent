---
id: 2026-11-04-current-orders-too-high
title: Measured current orders of magnitude above expected
status: draft
reviewed_by: null
runbook: current-too-high
backend: visa
station: unknown
device: unknown (group experience; no device recorded)
runs: []
sources: [deck slide 17, PPT_slides_content.md p.18]
reproduction:
  scenario: gd_short
  steps:
    - {id: symptom, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic}
    - {id: lifted, scenario: lab_station, recipe: basic.contact_resistor, pin_map: mosfet-gd-2t,
       dut_profile: resistor-generic}
    - {id: contact, recipe: basic.contact_resistor, pin_map: mosfet-gd-2t, dut_profile: resistor-generic}
    - {id: other_device, scenario: nmos_basic, recipe: mosfet.idvg, pin_map: mosfet-4t, dut_profile: nmos-generic}
    - {id: other_contact, scenario: nmos_basic, recipe: basic.contact_resistor, pin_map: mosfet-gd-2t,
       dut_profile: resistor-generic}
  expect:
    - symptom.status('gate_I', 0) == 'C'
    - abs(symptom.value('drain_I', 0)) >= 1000 * abs(other_device.value('drain_I', 0))
  discriminator:
    check: >-
      runbook current-too-high (deck order): open-circuit current with the probes lifted (First safe checks 4), contact
      check on the gate-drain pair (3), the same plan on another device (5)
    expect:
      - lifted.classification('resistance') == 'open'
      - contact.result('resistance') < 1.0e+6
      - other_contact.classification('resistance') == 'open'
      - other_device.count('C') == 0 and other_device.result('vth') > 0
open_questions: 5
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Measured current orders of magnitude above expected

Seeded from the owner's deck (slide 17, "8 Debug经验记录", 2026-11-04): a group pitfall recorded before this agent
existed. No run, station or device data; the owner reviews and completes it. The lab facts below are the deck's;
the simulator reproduction has its own section.

## Symptom

The measured current was several orders of magnitude larger than expected.

## Observed data and status codes

Not recorded in the deck (open questions 1 and 2: magnitude, device type, terminal).

## Physical checks

- Probe not landed correctly on the pad and touching a neighbouring trace (deck slide 17).
- Guard line not connected, so cable leakage adds to the measurement (deck text only).

Deck order: lift the probes and measure the open-circuit current, then re-land, then check the Guard connection.

## Instrument checks

None listed in the deck for this symptom (open question 3: integration time, range, error queue at the time).

## DUT hypotheses

Device already broken down, or a process defect (deck slide 17). Last deck step: measure another device to
separate a station problem from a device problem.

## Resolution

Not recorded in the deck (open question 5).

## Reproducible

Recurring pitfall in the group (the deck lists it as a common problem); counts not recorded.

## Proposed follow-up

Basis of runbook `current-too-high`. The station's typical open-circuit current (open question 4) would put a
number into the runbook's open-circuit check.

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.4 (`git describe` 2b4d4d8-dirty: the tree of the WP21.4 commit), backend sim, all runs
SIMULATED (`S...`, in the local data folder `work/cases/2026-11-04-current-orders-too-high/20261126T055820Z/`, not
committed). Regenerate: `uv run b1500 dev cases reproduce 2026-11-04-current-orders-too-high`; the authority is
`tests/integration/test_debug_cases.py`. It models only the device cause (deck cause 3): scenario `gd_short`, the
`nmos_basic` transistor with a 1 kOhm gate-drain short. A probe touching a neighbouring trace and the Guard have
no simulator model.

- Symptom: `mosfet.idvg` (pin map `mosfet-4t`, default plan) run `S20261126T055821Z-734c`: the gate is in
  compliance (`C`, -1.0 uA) at the first step, the drain reads 1.0 uA (`T`) where the healthy `nmos_basic` reads
  0.42 pA at the same step (`S20261126T055821Z-6141`), and the automatic abort fills the other 100 steps with
  dummy data (`V`): quality untrusted, Vth refused.
- Discriminator, in deck order: with the probes lifted (scenario `lab_station`, nothing landed) the gate-drain
  contact check reads `open` (`S20261126T055821Z-8b6a`): the station's open-circuit current is at its floor, so
  cables and Guard are not the cause. On the landing the same check (`basic.contact_resistor`, pin map
  `mosfet-gd-2t`) reads R = 1.0 kOhm (`S20261126T055821Z-87b3`; classified `in_range`, the short threshold is
  100 Ohm) where a healthy gate-drain pair reads `open` (`S20261126T055821Z-c5b0`): a leakage path between gate and
  drain. Another device with the same plan is normal: no `C`, Vth 0.431 V (`S20261126T055821Z-6141`).

## Open questions for the owner

1. What magnitude was measured, and what was expected (current and bias)?
2. Which device type, and on which terminal did the excess current appear?
3. Integration time, current range and the instrument error queue at the time?
4. What is the station's typical open-circuit current with the probes lifted (per SMU and integration time)? It
   would set the number in the runbook's open-circuit check.
5. Was it resolved, and which cause was it (probe on a neighbouring trace, Guard, damaged device)?
