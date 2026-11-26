---
id: noisy-data
title: Noisy data or a response at the noise floor
maturity: seed
sources: [general practice (not checked against a source), PG p33 (1-13) integration time,
  UG p63 (2-23) "Minimum range", UG p72 (2-32) "1 pA range", UG p119 (3-41) "guard", analysis/quality.py (MIN_SNR),
  lwp/matlab_B1500/IdVg_test_2025100*.csv (lab HRSMU floor), example case example-noisy-data (illustrative)]
---

# Noisy data

## Symptom

- Large point-to-point scatter on a curve that should be smooth.
- Quality warning "signal range is only N x its noise estimate ... at the noise floor" on the response column
  (SNR below 10; pure white noise gives about 5).
- `analyze_run` refuses: "`<column>` is noise-dominated". The run itself may still say quality `ok`, because all
  points carry status N: the status codes do not catch an open probe.

A bias or leakage column at its floor is normal; the column being analysed (for example `drain_I` of Id-Vg) is a
red flag.

## Likely causes

1. Nothing is connected: a probe is lifted or off its pad, so the SMU reads only its noise floor.
2. Integration time too short (general practice; integration settings: PG p33 (1-13)).
3. Shield box open or environmental interference (general practice). Simulator: `nmos_unshielded` (landed, raised
   floor; long integration resolves it) against `open_drain_noisy` (not landed); example case `example-noisy-data`
   (illustrative, SIMULATED reproduction).
4. Poor grounding (general practice).
5. The real current is below what the module resolves: an MPSMU's smallest range is 1 nA without an ASU
   (UG p63 (2-23)); sub-pA work needs the 1 pA range of an ASU channel (UG p72 (2-32)).

## First safe checks

1. Report no derived value. Do not retry `analyze_run` with `force`.
2. `get_run(run_id, include=[summary, quality])`: which column, its SNR, its magnitude against the module floor.
   Only the lab HRSMU floor on its Id-Vg path is on record (standard deviation about 0.07 pA at 1 PLC,
   `lwp/matlab_B1500/IdVg_test_2025100*.csv`); other modules and paths are recorded at bring-up
   (`TODO(verify)[L1.A4]`): until then their floor is unknown and step 5 measures it.
3. Contact check first, on every landing (card `contact-resistor-check` in skill `b1500-test`; cheap, tier `ok`, no
   stress), on the terminal pair of the noisy column: `resistor-2t` on a `mosfet-4t` landing checks drain to
   source/bulk with the gate SMU off. Use the pin map the card names; if none fits, ask the human for one. On a
   resistor or contact structure `open` means the probe is not landed. On a transistor or diode pair `open` is
   expected and does not prove the landing by itself: the check rules out a short or parallel path and records the
   terminal floor (compare with the module floor: a raised floor also points to causes 3-4); the "not landed"
   verdict comes from the device's own response (Id flat at the floor over the whole Vg sweep, no forward diode
   current). Either way, with a noise-floor device response: stop and ask for re-landing; no re-run helps before
   that. `short`: runbook `compliance-hit`.
4. Landing proven (`in_range` on a resistor; a transistor or diode response above the floor): re-run the same
   recipe with `integration: long` (or the next longer preset) as a new `validate_plan` that stays tier `ok`.
   Compare SNR. At most two such re-runs.
5. Still noisy: open-circuit floor with the probes lifted (contact-check plan) to see whether the station itself is
   noisy.

## Physical checks to ask the human

Order (general practice, not a recorded lab procedure): the landing first, then a longer integration time, a closed
shield box, the grounding:

- Are all probes landed? Please re-land the probe on the noisy terminal and confirm under the microscope.
- Is the shield box closed and connected to the B1500A chassis ground; is the GNDU connected?
- Any new equipment, pumps or lamps running near the prober?
- Is the low-current terminal on an HRSMU (with ASU for sub-pA work), with Guard connected (UG p119 (3-41))?

## Do not

- Report a Vth, SS or any fit from noise-dominated data, even "approximately".
- Average, smooth or drop points to make the noise go away.
- Raise the drain or gate bias to "lift the signal above the noise": that is a new plan with the human's consent.

## Stop and call safe_shutdown

- Not landed: the contact check reads `open` on a resistor structure, or a transistor or diode response stays at
  the noise floor (its contact check `open`, no short): hand over for physical re-landing and wait.
- Two re-runs with longer integration did not raise the SNR above 10.
- The scatter comes with status X (oscillation, output not settled) or V (over range) points: the data are
  untrusted; ask the human about cabling, Guard and the DUT.
