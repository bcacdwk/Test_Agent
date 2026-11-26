---
id: current-too-high
title: Current orders of magnitude above expected
maturity: seed
sources: [general practice (not checked against a source), CC p44 (2-2) "leakage current", UG p119 (3-41) "guard",
  PG p583 (5-11) errors 303-320, lwp/matlab_B1500/IdVg_test_2025100*.csv (lab HRSMU floor), example case
  example-current-orders-too-high (illustrative)]
---

# Current too high

## Symptom

- Measured current is orders of magnitude above what the human expects for this device (ask for the expected
  current and bias: the card's ranges and an example profile's nominal values are no expectations).
- Off-state current close to on-state current, current at 0 V bias, or an ohmic (straight) curve on a device that
  should switch.

## Likely causes

1. Probe not on its pad, touching a neighbouring line (general practice).
2. Guard not connected: cable insulation leakage adds to a low current (the guard surrounds the signal to decrease
   leakage: CC p44 (2-2), UG p119 (3-41)).
3. Wrong pin map or swapped terminals; wrong die (the `dut_instance` label does not match what is landed).
4. Device already broken down, shorted or defective (general practice); simulator scenario `gd_short` models a
   gate-drain short (SIMULATED reproduction: example case `example-current-orders-too-high`, illustrative).

## First safe checks

1. Report no derived value from the run. `get_run(run_id, include=[summary, quality])`: which terminal, at which
   bias, and whether any point is C or T (then also see [compliance-hit](compliance-hit.md)).
2. `station_status`: pin map and DUT profile in use, instrument errors, outputs on.
3. Contact check (card `contact-resistor-check`, skill `b1500-test`) on the pair that carries the excess current,
   for example gate-drain or gate-source: `short` or a low resistance confirms a leakage path (a healthy gate pair
   reads `open`). The example station's gate-drain map is `mosfet-gd-2t`; on the lab station ask for the pair's map.
4. Open-circuit floor: ask the human to lift the probes, then run the same contact-check plan. A current well above
   the floor with the probes up points at cables, Guard or fixture, not at the DUT. Only the lab HRSMU floor on its
   Id-Vg path is on record (standard deviation about 0.07 pA at 1 PLC, `lwp/matlab_B1500/IdVg_test_2025100*.csv`);
   other SMUs and paths are recorded at bring-up (`TODO(verify)[L1.A4]`): until then compare with earlier
   open-circuit runs of this station, or report the floor as unknown.
5. After the human re-lands, or lands on a neighbouring device, re-run the original plan with a new
   `dut_instance` label. Same plan, same tier; nothing else changes.

## Physical checks to ask the human

Order (general practice, not a recorded lab procedure): lift the probes and measure the open current, re-land,
check the Guard, measure another device.

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
- Errors 303 (MPSMU excess voltage) and 305 (HPSMU excess current) set all output switches off, 320 (CMU excess
  current) the CMU's; 304 (ground unit abuse); any error from 300-399 (PG p583 (5-11)).
- The open-circuit current is high with the probes lifted: hand the station check (cables, Guard) to the human.
