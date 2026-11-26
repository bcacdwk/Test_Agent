---
id: wgfmu-range-overflow
title: WGFMU current or voltage at full scale (status V, clipped plateau)
maturity: seed
sources: [blueprint v2 2.8 (R-QUAL WGFMU flags), 4.2 (WGFMU engine saturation), WG p16 (1-4) "full scale", WG p142 (4-72) "6001", WG p128 (4-58) "setRangeEvent", WG p141 (4-71) "5 V fixed range", WG5 p24 (1-14) "0.014 % of range"]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# WGFMU reading at full scale

## Symptom

- Points with status `V` in a WGFMU run (`completed_with_flags`, quality verdict `untrusted`); `pulse_plateau`,
  `gm_max` or `resistance` refuse ("untrusted points").
- The drain current is flat at exactly 1 uA, 10 uA, 100 uA, 1 mA or 10 mA (the range's full scale), or a voltage
  reading sits at 5 V / 10 V.
- `dc_spot` reads the same current at several levels.

## Likely causes

1. The current range (`irange`, or an events-file range code) is smaller than the device current: the WGFMU has no
   compliance, its reading saturates at the range's full scale (WG p16 (1-4)).
2. A range event switched to a small range before a high-current section (custom waveform).
3. A short or a much larger device than planned (Ion far above what the human expects for this device).
4. A voltage-measuring channel whose level exceeds its voltage measurement range (±5 V or ±10 V, default 10 V:
   WG p141 (4-71)).

## First safe checks

1. `get_run(run_id, include=[summary, quality])`: status counts per column, the `<role>_range` column at the `V`
   points, the plan's `irange` and summary levels.
2. Compare the largest current with the range: Table 4-9 ranges 1 uA, 10 uA, 100 uA, 1 mA, 10 mA (WG p142 (4-72)).
3. A new plan one range up (`irange`), validated (tier as before); for a custom waveform, a range code in the events
   file at time 0 (initial) or a range-only row (points 0) outside every averaging window.
4. Suspect a short (current at 10 mA full scale on a small device): contact check on that terminal pair first.

## Physical checks to ask the human

- Is the landed device the one in the DUT profile (size, W/L)? Any visible damage at the gate or drain pad?

## Do not

- Report a value from `V` points or force an extraction across them.
- Raise the gate or drain level to compensate; the range is the knob, inside the DUT envelope.
- Choose a range larger than needed "to be safe": resolution and noise scale with the range's full scale
  (current: resolution 0.014 % and noise up to 0.2 % of range, WG5 p24 (1-14)).

## Stop and call safe_shutdown

- Full-scale current on the 10 mA range on a small device: possible short or breakdown; keep the outputs off and
  hand over.
