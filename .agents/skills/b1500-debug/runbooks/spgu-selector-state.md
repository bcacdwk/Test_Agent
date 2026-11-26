---
id: spgu-selector-state
title: Selector or SPGU left switched or running (off rest, SPST? 1, SPP fallback)
maturity: seed
sources: [blueprint v2 2.6 (cleanup steps 2, 5, 8), 2.8 (R-ROUTE-01), 11 (ATV-18, ATV-19), PG p433 (4-115) "ERSSP", PG p142 (2-54) "SPST", PG p512 (4-194) "SPRM", PG p419 (4-101) "ERMOD", SEL p15 (9), CC p48 (2-6)]
---

# Selector or SPGU left switched or running

## Symptom

- A plan is blocked before the run: R-ROUTE-01 "SEL1.OUT1 is pgu, not its rest state open" (pre-execute).
- `station_status` shows a selector output `off rest: pgu (rest open)` or `not read`, or an SPGU output active.
- A pulse run reports `kind_result.spp_fallbacks` > 0 (`SPST?` stayed 1 after the planned time; `SPP` stopped it).
- A run refuses "an SPGU output is already running (SPST? 1)".

## Likely causes

1. An earlier run was killed (or a human used the front panel / EasyEXPERT) and left a selector on PGU or SMU.
2. A previous program left an SPGU output running: free run is the initial `SPRM` mode, so an output started
   without a count runs until `SPP` (PG p512 (4-194)); `SPST?` reads 1 while it runs (PG p142 (2-54)).
3. `SPST?` does not fall at the end of the count (ATV-19, verified at bring-up L7) or the output ignores stops
   (simulator fault `spgu_no_stop`).
4. The selector's control mode is off (`ERMOD` 0, the initial setting, PG p419 (4-101); after power-on, ATV-18):
   status reads `not read`.

## First safe checks

1. `safe_shutdown(reason)`: it stops every SPGU output (`SPP`), returns every declared selector output to rest
   (`ERMOD 1`, `ERSSP p,rest`) and verifies `SPST?` 0 and each `ERSSP?`.
2. `station_status`: every selector output at its rest state, no fault. If the fault latch is set: runbook
   `cleanup-failed-fault`.
3. `get_run(run_id, include=[audit])` of the last pulse run: the `routes` checkpoints (`pulse`, `rest`) and the
   marks "SPGU output started / ended" or "ATV-19 fallback: SPP".
4. Re-validate the blocked plan only after `station_status` is clean.

## Physical checks to ask the human

- Selector front-panel LEDs: which input is lit on each output? Does it match `station_status`?
- Is the 16445A adapter powered and its control input cabled to the B1500A digital I/O
  (SEL p15 (9), CC p48 (2-6))?
- Is EasyEXPERT or another program running that drives the SPGU or the selectors?

## Do not

- Write `ERSSP`/`SPP` by hand, edit the station profile to call a stuck state "rest", or clear a fault.
- Trust a pulse count after an SPP fallback: the train may have run longer or shorter than planned.
- Start the next pulse plan while `station_status` shows an output off rest.

## Stop and call safe_shutdown

- `cleanup_unverified` or a latched fault: the selector or the SPGU would not return; a human inspects it.
- `spp_fallbacks` repeat on every run: ATV-19 is wrong on this station; record a case for the bring-up L7 review.
