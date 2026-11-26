---
id: compliance-hit
title: Compliance hit (status C or T)
maturity: seed
sources: [PG p52-53 (1-32) Table 1-10 status codes, PG p579 (5-7) "Sweep measurement was aborted", PG p583 (5-11)
  errors 303-320, general practice (causes; not checked against a source)]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Compliance hit

## Symptom

- Run outcome `completed_with_flags`, quality verdict `limited`, status counts with C (this channel reached its
  compliance) or T (another channel did).
- A stepped sweep reports `stopped_early`; error 227 "Sweep measurement was aborted".
- Analyses exclude C and T points; too many in the fit window and the method refuses.

## Likely causes

1. The DUT draws more current than planned: short, breakdown or damage (simulator scenario `gd_short`).
2. Wrong pin map or swapped terminals; a probe touching a neighbouring line.
3. The sweep runs into a region the card does not intend (deep forward bias, strong inversion at high Vd).
4. Compliance chosen too low for this device size, a planning question for the human, not a debug fix.

Status V (over range, sweep aborted) or F (force saturation) is untrusted, not limited: treat as a hard stop.

## First safe checks

1. `get_run(run_id, include=[summary, quality, data])`: which channel, which step and bias, C or T. A gate C on a
   gate-leakage or Id-Vg run is an oxide warning sign.
2. Compare the shape qualitatively with the card's expected result shape (the card has no checked typical values:
   numbers come from the human or earlier runs of the same device). Sudden jumps or a current flat at the compliance
   value suggest a short or breakdown; a smooth approach suggests a sweep range issue.
3. Contact check (card `contact-resistor-check`, skill `b1500-test`) on the pair whose current hit compliance.
4. If the hit is at the end of the range and the contact is fine: a new `validate_plan` with a narrower sweep
   inside the original plan's range (narrower, never wider) that stays tier `ok`. At most two such re-runs.

## Physical checks to ask the human

- Do the probes sit on the pads the pin map names, none on a neighbouring line?
- Is the device size (W/L, area) what the DUT profile assumes?
- Any visible damage on the device after the run?

## Do not

- Raise compliance, voltage or the DUT envelope to get past the flag. If the human decides the device needs more
  current, that is a new plan with its own tier and their consent.
- Repeat the same sweep into compliance: repeated stress can damage the device.
- Fit through C or T points or `force` an extraction.

## Stop and call safe_shutdown

- Gate current at compliance, or a jump that looks like breakdown (destructive: no re-run without the human).
- Contact check reads `short`; error 303, 305 or 320 (excess voltage or current, outputs off: PG p583 (5-11)) or
  any error from 300-399.
- Compliance persists after narrowing the range once.
