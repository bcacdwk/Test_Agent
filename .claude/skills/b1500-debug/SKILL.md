---
name: b1500-debug
description: Use when B1500A data look noisy, impossible, too high, compliance-limited or drifting (IGZO Vth), on a fault, fault_latched or cleanup_unverified result, instrument (ERRX) or VISA errors, or an interlock question. Triage order, runbooks, safe checks; never raise limits to get past a symptom.
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# B1500A debug

Knowledge domain 08 of skill `b1500-test` (deck slide 17). You diagnose with read-only tools and validated
plans; the human does every physical step. Backend `sim`: symptoms and fixes are SIMULATED.

## 1. First moves

1. Fault, error, stop request, `cleanup_unverified` or outputs in doubt: `safe_shutdown(reason)` first (never
   gated); then report "cleanup verified" (or unverified, from its `cleanup`) and a stopped run's rows as partial.
2. Report no derived value from the suspect run: no Vth, SS or fit from untrusted or noise-floor data, no `force`.
3. `station_status`: fault latch, lock holder, interlock bit, instrument errors, outputs on, config problems.
4. Pick the runbook (part 3), work through it in order, then record the case (part 7).

## 2. Triage order (deck slide 17)

1. Physical connection: probe contact, cables, Guard, grounding, shield box.
2. Instrument state: calibration, correction, range, integration time, error queue.
3. Data: status codes, quality verdict, noise and SNR, shape against the card's expected result.
4. DUT: process defect, damage, material effects (oxide TFTs, ferroelectrics); never blamed before steps 1-3 are
   cleared. One change at a time; note each result.

## 3. Symptom index

| Symptom | Runbook |
|---|---|
| Current orders of magnitude above expected, Ioff near Ion, ohmic curve on a switching device | [current-too-high](runbooks/current-too-high.md) |
| Scatter, "at the noise floor" warning, `noise-dominated` refusal | [noisy-data](runbooks/noisy-data.md) |
| Status C or T, `completed_with_flags`, verdict `limited`, sweep stopped early | [compliance-hit](runbooks/compliance-hit.md) |
| IGZO or oxide TFT Vth differs from run to run | [vth-drift-igzo](runbooks/vth-drift-igzo.md) |
| Instrument errors, `instrument_error`, an ERRX code | [errx-codes](runbooks/errx-codes.md) |
| `transport_error`, timeouts, no identity on the visa backend | [visa-no-connection](runbooks/visa-no-connection.md) |
| Interlock OPEN or unknown, errors 202, 203, 310 | [interlock-open](runbooks/interlock-open.md) |
| `fault`, `fault_latched`, `cleanup_unverified`, fault latch set | [cleanup-failed-fault](runbooks/cleanup-failed-fault.md) |
| MFCMU: C-V blocked or refused by R-CORR-01, corrections missing, stale or lost; C-V shape wrong (Cmax above Cox, stretch-out, deep depletion, branches apart, status U/D); Cp falls with frequency, large D or `rs` | [cmu-correction-stale](runbooks/cmu-correction-stale.md), [cmu-cv-distortion](runbooks/cmu-cv-distortion.md), [cmu-series-resistance](runbooks/cmu-series-resistance.md) |
| Selector off rest, SPGU output running, SPP fallback (`spp_fallbacks`) | [spgu-selector-state](runbooks/spgu-selector-state.md) |
| SPGU pulses did nothing (no switching, no charge-pumping current) | [spgu-pulse-no-effect](runbooks/spgu-pulse-no-effect.md) |
| Pulse level at the pad not the set level, R-SPGU-01 SER/high_z block | [spgu-load-mismatch](runbooks/spgu-load-mismatch.md) |
| Sampling run with skipped samples, `index_gaps`, host/index time, early abort | [smu-sampling-skips](runbooks/smu-sampling-skips.md) |
| BTI/HCI/SILC/IGZO stress: no shift, wrong sign, huge shift, odd exponent | [stress-degradation-unexpected](runbooks/stress-degradation-unexpected.md) |
| WGFMU: library/session error or 30xx/33xx code; RSU not at rest, 3001, level missing at the DUT, SMU path through the RSU open; status V at full scale; too many stored values or 3050 | [wgfmu-library-error](runbooks/wgfmu-library-error.md), [wgfmu-rsu-route](runbooks/wgfmu-rsu-route.md), [wgfmu-range-overflow](runbooks/wgfmu-range-overflow.md), [wgfmu-memory-budget](runbooks/wgfmu-memory-budget.md) |

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
