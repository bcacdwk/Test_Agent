---
id: 2026-11-04-noisy-data
title: Large noise and point-to-point scatter
status: draft
reviewed_by: null
runbook: noisy-data
backend: visa
station: unknown
device: unknown (group experience; no device recorded)
runs: []
sources: [deck slide 17, PPT_slides_content.md p.18]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Large noise and point-to-point scatter

Seeded from the owner's deck (slide 17, "8 Debug经验记录", 2026-11-04): a group pitfall recorded before this agent
existed. No run, station or device data; the owner reviews and completes it.

## Symptom

The data were very noisy, with clear fluctuation from point to point.

## Observed data and status codes

Not recorded in the deck. TODO(owner): current level, module (MPSMU or HRSMU), integration setting.

## Physical checks

- Shield box not closed, environmental interference (deck slide 17).
- Poor grounding (deck text only).

Deck order: after a longer integration time, close the shield box, then check grounding.

## Instrument checks

Integration time set too short (deck slide 17). The deck's order starts here: lengthen the integration time.

## DUT hypotheses

None in the deck: every listed cause is a station or setup cause.

## Resolution

Not recorded in the deck. TODO(owner).

## Reproducible

Recurring pitfall in the group (the deck lists it as a common problem); counts not recorded.

## Proposed follow-up

Basis of runbook `noisy-data`. The runbook adds a contact check before the deck's steps, because an unlanded probe
also reads as pure noise (simulator scenario `open_drain_noisy`). TODO(owner): confirm that order for the lab.
