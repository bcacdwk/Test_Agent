---
id: example-current-orders-too-high
title: "Example: Measured current orders of magnitude above expected"
status: draft
reviewed_by: null
runbook: current-too-high
origin: illustrative
backend: none
station: none
device: any (illustrative; no device)
runs: []
sources: ["owner planning deck slide 17 (PPT_slides_content.md p.18): an illustrative list, not a lab record"]
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
      runbook current-too-high (general practice): open-circuit current with the probes lifted (First safe checks 4),
      contact check on the gate-drain pair (3), the same plan on another device (5)
    expect:
      - lifted.classification('resistance') == 'open'
      - contact.result('resistance') < 1.0e+6
      - other_contact.classification('resistance') == 'open'
      - other_device.count('C') == 0 and other_device.result('vth') > 0
open_questions: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Example: Measured current orders of magnitude above expected

Illustrative example, not an observed lab case: written from a troubleshooting list in the owner's planning deck,
which shows the kind of problem a lab meets, not a recorded event. No run, station, device or date was observed. The
causes are general practice; the simulator section shows how the runbook separates them (SIMULATED).

## Symptom

Example symptom: the measured current is several orders of magnitude larger than the human expects for the device
and bias.

## Observed data and status codes

None (illustrative).

## Physical checks

- Probe not landed correctly on the pad and touching a neighbouring trace (general practice).
- Guard not connected, so cable leakage adds to the measurement (general practice; the triax guard is driven at the
  signal voltage to decrease leakage, CC p44 (2-2)).

Order (general practice): lift the probes and measure the open-circuit current, then re-land, then check the Guard
connection.

## Instrument checks

None specific to this symptom; the runbook's instrument checks apply (integration time, range, error queue).

## DUT hypotheses

Device already broken down, or a process defect (general practice). Last step: measure another device to separate
a station problem from a device problem.

## Resolution

Not applicable (illustrative).

## Reproducible

Not observed in the lab.

## Proposed follow-up

Runbook `current-too-high` rests on general practice, not on this example. A number for its open-circuit check is
the station's open-circuit current per SMU path, which bring-up records (`TODO(verify)[L1.A4]`); the lab's
open-probe Id-Vg runs on an HRSMU read within about ±2e-13 A at 1 PLC (`lwp/matlab_B1500/IdVg_test_20251004_*.csv`).

## Simulator reproduction (SIMULATED)

Made 2026-11-26 in WP21.11 (commit 9589796 plus this WP's uncommitted edits), backend sim, all runs SIMULATED
(`S...`, in the local data folder `work/cases/example-current-orders-too-high/20261126T114152Z/`, not committed).
Regenerate: `uv run b1500 dev cases reproduce example-current-orders-too-high`; the authority is
`tests/integration/test_debug_cases.py`. It models only the device cause (the DUT hypothesis above): scenario
`gd_short`, the `nmos_basic` transistor with a 1 kOhm gate-drain short (simulator example, not a real-device value).
A probe touching a neighbouring trace and the Guard have no simulator model.

- Symptom: `mosfet.idvg` (pin map `mosfet-4t`, default plan) run `S20261126T114152Z-688f`: the gate is in
  compliance (`C`, -1.0 uA) at the first step, the drain reads 1.0 uA (`T`) where the healthy `nmos_basic` reads
  0.42 pA at the same step (`S20261126T114152Z-bea8`), and the automatic abort fills the other 100 steps with
  dummy data (`V`): quality untrusted, Vth refused.
- Discriminator, in the runbook's order: with the probes lifted (scenario `lab_station`, nothing landed) the
  gate-drain contact check reads `open` (`S20261126T114152Z-9051`): the station's open-circuit current is at its
  floor, so cables and Guard are not the cause. On the landing the same check (`basic.contact_resistor`, pin map
  `mosfet-gd-2t`) reads R = 1.0 kOhm (`S20261126T114152Z-e66a`; classified `in_range`, the short threshold is
  100 Ohm) where a healthy gate-drain pair reads `open` (`S20261126T114152Z-5f2a`): a leakage path between gate and
  drain. Another device with the same plan is normal: no `C`, Vth 0.431 V (`S20261126T114152Z-bea8`).

## Open questions for the owner

1. Has the lab seen this problem? If yes, record it as an observed case (date, device, runs, what fixed it).
