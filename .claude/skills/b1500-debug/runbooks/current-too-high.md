---
id: current-too-high
title: Current orders of magnitude above expected
maturity: seed
sources: [deck slide 17, PPT_slides_content.md p.18 (Guard cause), case 2026-11-04-current-orders-too-high]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Current too high

## Symptom

- Measured current is orders of magnitude above the card's expected result or the DUT profile's nominal values.
- Off-state current close to on-state current, current at 0 V bias, or an ohmic (straight) curve on a device that
  should switch.

## Likely causes

1. Probe not on its pad, touching a neighbouring line (deck slide 17).
2. Guard not connected: cable insulation leakage adds to a low current (deck text).
3. Wrong pin map or swapped terminals; wrong die (the `dut_instance` label does not match what is landed).
4. Device already broken down, shorted or defective (deck slide 17); simulator scenario `gd_short` models a
   gate-drain short (SIMULATED reproduction: debug case `2026-11-04-current-orders-too-high`).

## First safe checks

1. Report no derived value from the run. `get_run(run_id, include=[summary, quality])`: which terminal, at which
   bias, and whether any point is C or T (then also see [compliance-hit](compliance-hit.md)).
2. `station_status`: pin map and DUT profile in use, instrument errors, outputs on.
3. Contact check (card `contact-resistor-check`, skill `b1500-test`) on the pair that carries the excess current,
   for example gate-drain or gate-source: `short` or a low resistance confirms a leakage path (a healthy gate pair
   reads `open`). The example station's gate-drain map is `mosfet-gd-2t`; on the lab station ask for the pair's map.
4. Open-circuit floor: ask the human to lift the probes, then run the same contact-check plan. A current well above
   the floor with the probes up points at cables, Guard or fixture, not at the DUT.
5. After the human re-lands, or lands on a neighbouring device, re-run the original plan with a new
   `dut_instance` label. Same plan, same tier; nothing else changes.

## Physical checks to ask the human

Deck order (slide 17): lift the probes and measure the open current, re-land, check the Guard, measure another
device.

- Are all probes on their pads, none touching a neighbouring line?
- Is the Guard of each triax connected through to the prober?
- Does the landed die match the label and the pin map?
- Any visible damage on the device (burn marks, cracked pad)?

## Do not

- Raise compliance or voltage, or relax the DUT profile, to see "how high it goes".
- Call the device defective before the contact and open-circuit checks are done.
- Report Vth, Ion/Ioff or any fit from this run.

## Stop and call safe_shutdown

- The contact check reads `short`, or the current reaches compliance again after re-landing.
- Error 305 (excess current; all outputs were switched off) or any error from 300-399.
- The open-circuit current is high with the probes lifted: hand the station check (cables, Guard) to the human.
