---
id: 2026-11-04-igzo-vth-drift
title: IGZO TFT Vth differs with every measurement
status: draft
reviewed_by: null
runbook: vth-drift-igzo
backend: visa
station: unknown
device: igzo_tft (group experience; no device recorded)
runs: []
sources: [deck slide 17, PPT_slides_content.md p.18]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# IGZO TFT Vth differs with every measurement

Seeded from the owner's deck (slide 17, "8 Debug经验记录", 2026-11-04): a group pitfall recorded before this agent
existed. No run, station or device data; the owner reviews and completes it.

## Symptom

The Vth of an IGZO TFT was different every time it was measured.

## Observed data and status codes

Not recorded in the deck. TODO(owner): size and direction of the shift, sweep range, time between runs.

## Physical checks

Deck order: control ambient temperature and humidity first.

## Instrument checks

Deck order after the environment: reduce the sweep voltage range, then shorten the measurement time.

## DUT hypotheses

- Water adsorption or desorption changes the back-channel potential (deck slide 17).
- The voltage stress of the measurement itself shifts Vth (deck slide 17).
- Temperature changes alter the oxygen-vacancy concentration (deck text only).

## Resolution

Not recorded in the deck. TODO(owner).

## Reproducible

Recurring pitfall in the group (the deck lists it as a common problem); counts not recorded.

## Proposed follow-up

Basis of runbook `vth-drift-igzo`. TODO(owner): a recommended rest time between sweeps and a maximum gate range
for IGZO Id-Vg, to become a card recommendation once validated.
