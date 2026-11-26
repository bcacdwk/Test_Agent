---
id: 2026-11-05-bad-reproduction
title: A reproduction with unknown names
status: draft
reviewed_by: null
runbook: noisy-data
origin: observed
backend: none
station: unknown
device: unknown
runs: []
sources: [fixture]
reproduction:
  scenario: nmos_nowhere
  steps:
    - {id: symptom, recipe: mosfet.idvg, pin_map: mosfet-9t, dut_profile: nmos-generic, params: {vg_steps: 11}}
  expect:
    - symptom.snr('drain_I') < 10
  discriminator:
    check: runbook noisy-data, a longer integration
    expect:
      - symptom.count('C') == 0
open_questions: 2
---

# A reproduction with unknown names

## Symptom

Noise.

## Observed data and status codes

None.

## Physical checks

None.

## Instrument checks

None.

## DUT hypotheses

None.

## Resolution

Open.

## Reproducible

Not tried.

## Proposed follow-up

None.

## Simulator reproduction (SIMULATED)

Not run yet.

## Open questions for the owner

1. Which current level?
