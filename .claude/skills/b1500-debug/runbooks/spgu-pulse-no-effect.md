---
id: spgu-pulse-no-effect
title: SPGU pulses had no effect (no switching, no charge-pumping current)
maturity: seed
sources: [blueprint v2 2.7 (spgu_pulse), 4.2 (SPGU output), PG p507 (4-189) "SER", PG p146 (2-58) "3-level", PG p433 (4-115) "ERSSP"]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# SPGU pulses had no effect

## Symptom

- After a program/erase train the read shows no change (FeFET memory window unchanged, Vth where it was).
- Charge pumping: the bulk current stays at the noise floor at every frequency, or does not grow with the frequency
  (`charge_pumping` failed: "Icp does not grow with the frequency").
- The run completed, cleanup verified, no error: the pulses were generated but did not reach or act on the device.

## Likely causes

1. The pulse never reached the pad: selector on the wrong port or state, the gate not on the selector output the pin
   map names, the PGU input cabled to the other SPGU channel (wiring recorded wrong at L7).
2. The pulse was too small or too short: amplitude below the coercive voltage, width below the switching time;
   charge pumping: the base does not reach accumulation (below Vfb) or the top inversion (above Vth).
3. Floating return: FeFET source/drain or the MOSFET bulk not connected; charge pumping needs bulk and source/drain.
4. A three-level program whose sources cancel (base2/peak2 opposite to source 1 at the same time).

## First safe checks

1. `get_run(run_id, include=[audit])`: routes `pulse: SEL1.OUT1 -> pgu` read back, "SPGU output started/ended", the
   pulses and output time in `kind_result`; the plan's summary (levels, width, `SER`).
2. Station profile vs pin map: which channel is on the selector's PGU input (`station_status` switches, the station
   profile `inputs`); the SPGU channel in the summary (`SPGU1:101`).
3. Physics: compare amplitude and width with the card's recommended window and the device (coercive voltage, Vth
   and Vfb from an Id-Vg on the same landing). A new plan inside the card's window, validated, never above the DUT
   envelope.
4. Charge pumping: a base-level sweep at one frequency (several `v_base`) shows whether any base gives a plateau.

## Physical checks to ask the human

- Which selector output is the gate probe cabled to? Which SPGU channel feeds that selector's PGU input?
- Are the bulk (chuck or substrate contact) and source/drain probes landed and cabled to the SMUs of the pin map?
- At bring-up L7: a scope on the selector output during a 1 MOhm pulse check (level and width as planned).

## Do not

- Raise the amplitude, width or count past the card window or the DUT pulse envelope to "make it work".
- Lower `load_ohm` to 50 Ohm to get more voltage: on an open gate that doubles the level (R-SPGU-01 blocks it).
- Report a memory window or Dit from a run whose pulses did not reach the device.

## Stop and call safe_shutdown

- The read shows damage (gate leakage jump, Id collapse) after the train: possible breakdown.
- The audit shows a route other than planned, or the selector LEDs disagree with `station_status`.
