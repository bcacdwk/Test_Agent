---
name: b1500-debug
description: Use when B1500A data look noisy, impossible, too high, compliance-limited or drifting (IGZO Vth), on a fault, fault_latched, cleanup_unverified or interrupted-run result, ERRX or VISA errors, or an interlock question. Triage order, runbooks, safe checks; never raise limits to get past a symptom.
---

# B1500A debug

Knowledge domain 08 of skill `b1500-test` (deck slide 17). You diagnose with read-only tools and validated
plans; the human does every physical step. Backend `sim`: symptoms and fixes are SIMULATED.

## 1. First moves

1. Fault, error, stop request, interrupted long run, `cleanup_unverified` or outputs in doubt: `safe_shutdown(reason)`
   first (never gated); then report "cleanup verified" (or unverified, from its `cleanup`) and a stopped run's rows
   as partial.
2. Report no derived value from the suspect run: no Vth, SS or fit from untrusted or noise-floor data, no `force`.
3. `station_status`: fault latch, lock holder, interlock bit, instrument errors, outputs on, config problems.
4. Pick the runbook (part 3), work through it in order, then record the case (part 7).

## 2. Triage order (deck slide 17)

1. Physical connection: probe contact, cables, Guard, grounding, shield box.
2. Instrument state: calibration, correction, range, integration time, error queue.
3. Data: status codes, quality verdict, noise and SNR, shape against the card's expected result.
4. DUT: process defect, damage, material effects (oxide TFTs, ferroelectrics); never blamed before steps 1-3 are
   cleared. One change at a time; note each result.

## 3. Symptom router (family x symptom)

Check the `any` rows first, then the row of the card's family (cards/README.md); follow the runbook in order.

| Family | Symptom -> runbook |
|---|---|
| any state | fault, `fault_latched`, `cleanup_unverified` [cleanup-failed-fault](runbooks/cleanup-failed-fault.md); `instrument_error`, an ERRX code [errx-codes](runbooks/errx-codes.md); `transport_error`, timeouts, no identity (visa) [visa-no-connection](runbooks/visa-no-connection.md); interlock OPEN or unknown, 202/203/310 [interlock-open](runbooks/interlock-open.md); a long run cancelled by a closed session, killed with its server, `aborted` by a recovery, in-flight marker [async-run-interrupted](runbooks/async-run-interrupted.md) |
| any data | scatter, noise floor, `noise-dominated` [noisy-data](runbooks/noisy-data.md); status C or T, `limited`, stopped early [compliance-hit](runbooks/compliance-hit.md); current orders above expected, Ioff near Ion [current-too-high](runbooks/current-too-high.md) |
| smu | oxide TFT Vth differs run to run [vth-drift-igzo](runbooks/vth-drift-igzo.md); sampling `index_gaps`, skipped samples, host time [smu-sampling-skips](runbooks/smu-sampling-skips.md) |
| cmu | blocked by R-CORR-01, corrections missing, stale or lost [cmu-correction-stale](runbooks/cmu-correction-stale.md); C-V shape wrong (Cmax above Cox, stretch-out, deep depletion, status U/D) [cmu-cv-distortion](runbooks/cmu-cv-distortion.md); Cp falls with frequency, large D or `rs` [cmu-series-resistance](runbooks/cmu-series-resistance.md) |
| spgu | selector off rest, SPGU running, `spp_fallbacks` [spgu-selector-state](runbooks/spgu-selector-state.md); pulses did nothing [spgu-pulse-no-effect](runbooks/spgu-pulse-no-effect.md); level at the pad wrong, R-SPGU-01 SER/high_z [spgu-load-mismatch](runbooks/spgu-load-mismatch.md) |
| wgfmu | library or session error, 30xx/33xx [wgfmu-library-error](runbooks/wgfmu-library-error.md); RSU not at rest, 3001, level missing at the DUT [wgfmu-rsu-route](runbooks/wgfmu-rsu-route.md); status V at full scale [wgfmu-range-overflow](runbooks/wgfmu-range-overflow.md); too many stored values, 3050 [wgfmu-memory-budget](runbooks/wgfmu-memory-budget.md) |
| nvm | FeFET pulses (SPGU) no switching [spgu-pulse-no-effect](runbooks/spgu-pulse-no-effect.md), selector or level [spgu-selector-state](runbooks/spgu-selector-state.md) [spgu-load-mismatch](runbooks/spgu-load-mismatch.md); FeCap PUND or fast program (WGFMU) [wgfmu-rsu-route](runbooks/wgfmu-rsu-route.md) [wgfmu-range-overflow](runbooks/wgfmu-range-overflow.md) [wgfmu-library-error](runbooks/wgfmu-library-error.md) [wgfmu-memory-budget](runbooks/wgfmu-memory-budget.md); butterfly C-V [cmu-correction-stale](runbooks/cmu-correction-stale.md) [cmu-cv-distortion](runbooks/cmu-cv-distortion.md); memory window drifts [vth-drift-igzo](runbooks/vth-drift-igzo.md) |
| reliability | no shift, wrong sign, huge shift, odd exponent, early breakdown [stress-degradation-unexpected](runbooks/stress-degradation-unexpected.md); IGZO recovery drift [vth-drift-igzo](runbooks/vth-drift-igzo.md); TDDB sampling gaps [smu-sampling-skips](runbooks/smu-sampling-skips.md); fast BTI (WGFMU) [wgfmu-range-overflow](runbooks/wgfmu-range-overflow.md) [wgfmu-library-error](runbooks/wgfmu-library-error.md) |
| system | self-test or self-calibration failure bits (stop) [errx-codes](runbooks/errx-codes.md); WGFMU self-test/cal [wgfmu-library-error](runbooks/wgfmu-library-error.md); zero-check floor high [noisy-data](runbooks/noisy-data.md), constant offset (cable charging, Guard) [current-too-high](runbooks/current-too-high.md) |

No match: follow part 2 and record a case.

## 4. Safe software checks

- `station_status` (read-only) and `get_run(run_id, include=[summary, quality, audit, notes])`.
- `list_runs` plus `get_run`: compare with earlier runs of the same plan, DUT instance or recipe.
- `analyze_run(run_id, "quality_report")`: status counts, trust fractions, noise and SNR per column.
- Contact check: card `contact-resistor-check` of skill `b1500-test` (recipe `basic.contact_resistor`, about
  0.1 V) on the suspect terminal pair; it classifies open, short or in range.
- Open-circuit noise floor: after the human lifts the probes, run the same contact-check plan again. The
  reading is the station floor (cables, Guard, fixture), the baseline for every low-current claim.
- Re-run with a longer `integration`, fewer points or a narrower sweep inside the card's recommended range:
  always a new `validate_plan` that stays tier `ok`; at most two such re-runs (skill `b1500-test`, part 7).
- `safe_shutdown(reason)` at any time.

## 5. Physical checks: ask the human

You cannot see or touch the station. Ask one concrete question at a time, wait for the answer, note it:

- Probes on the right pads (microscope view), not touching a neighbour line; re-land if unsure.
- Triax cables seated, Guard connected for pA work, GNDU connected; shield box closed and grounded.
- Which die or device is landed; does it match the `dut_instance` label?
- Instrument front panel: errors, output indicators; EasyEXPERT released (visa only).
- Environment: temperature, humidity, light on the sample (oxide TFTs).

## 6. Forbidden "fixes"

Never, even when asked and even if the symptom would go away:

- Raising |V|, |I| or compliance to get past a symptom. A deliberate change is a new plan with its own tier and
  the human's consent, decided after the diagnosis.
- Editing limits, DUT profiles, pin maps or anything in `config/local/**`, `data/**`, `recipes/` or harness config.
- Bypass modes or looser approval settings; raw FLEX, PyVISA or own scripts that touch the instrument.
- Running `b1500 fault clear` or deleting the latch or inflight files; only the human clears a fault.
- Reporting a value from untrusted or noise-floor data as valid; tuning a fit window to hit an expected value.

Stop, call `safe_shutdown(reason)` and hand over when a fault is latched, an error from 300-399 or a self-test or
calibration error appears, a short or breakdown is suspected, a physical check is needed, or two re-runs did not
change the picture. Say what you saw, what you ruled out and what the human should check next.

## 7. Recording a case

1. `annotate_run(run_id, text, tags=["debug", "<runbook id>"])` on each run involved: symptom, checks, result.
2. Draft `.agents/skills/b1500-debug/cases/<YYYY-MM-DD>-<slug>.md` from [the case template](cases/_TEMPLATE.md)
   with `status: draft`. Write only there (`.claude/skills/` is a generated copy and is overwritten). Tell the human
   the draft waits for their review; never set `status: reviewed` yourself.

## 8. Iteration policy

- A case seen twice becomes a runbook entry; a validated parameter fix becomes a card recommendation.
- The human reviews both; any change to skill, card or rule text must pass the M3 acceptance suite again.
- Seed cases from deck slide 17, all `draft`:
  [current too high](cases/2026-11-04-current-orders-too-high.md), [noisy data](cases/2026-11-04-noisy-data.md),
  [IGZO Vth drift](cases/2026-11-04-igzo-vth-drift.md).
