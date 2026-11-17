---
id: 2026-11-04-current-orders-too-high
title: Measured current orders of magnitude above expected
status: draft
reviewed_by: null
runbook: current-too-high
backend: visa
station: unknown
device: unknown (group experience; no device recorded)
runs: []
sources: [deck slide 17, PPT_slides_content.md p.18]
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Measured current orders of magnitude above expected

Seeded from the owner's deck (slide 17, "8 Debug经验记录", 2026-11-04): a group pitfall recorded before this agent
existed. No run, station or device data; the owner reviews and completes it.

## Symptom

The measured current was several orders of magnitude larger than expected.

## Observed data and status codes

Not recorded in the deck. TODO(owner): typical magnitude, device type, which terminal.

## Physical checks

- Probe not landed correctly on the pad and touching a neighbouring trace (deck slide 17).
- Guard line not connected, so cable leakage adds to the measurement (deck text only).

Deck order: lift the probes and measure the open-circuit current, then re-land, then check the Guard connection.

## Instrument checks

None listed in the deck for this symptom. TODO(owner): integration time, range, error queue at the time.

## DUT hypotheses

Device already broken down, or a process defect (deck slide 17). Last deck step: measure another device to
separate a station problem from a device problem.

## Resolution

Not recorded in the deck. TODO(owner).

## Reproducible

Recurring pitfall in the group (the deck lists it as a common problem); counts not recorded.

## Proposed follow-up

Basis of runbook `current-too-high`. TODO(owner): typical open-circuit current of the station, to put a number
into the runbook's open-circuit check.
