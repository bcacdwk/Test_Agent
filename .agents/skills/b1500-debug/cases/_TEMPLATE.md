---
id: <YYYY-MM-DD>-<slug>          # = file name without .md; date of the observation
title: <one-line symptom>
status: draft                    # draft (written by the agent) | reviewed (set only by a human)
reviewed_by: null                # human name, set together with status: reviewed
runbook: <runbook id | new>      # the runbook that applied, or "new" if none did
backend: <sim | visa>
station: <station profile name, or "unknown">
device: <device type; DUT profile / dut_instance>
runs: [<run_id>]                 # every run involved; each one also carries an annotate_run note
sources: [<run notes>, <deck slide N>, <lab notebook page>]
---

# <Title>

Draft written by the agent for human review. Facts come from runs and the human's answers; label every guess.

## Symptom

What looked wrong, in one or two sentences, with the tool result that showed it.

## Observed data and status codes

Run ids, outcome, status-code counts, quality verdict and warnings, SNR, the values that looked wrong (with units).

## Physical checks

Each question asked and the human's answer (probes, cables, Guard, grounding, shield box, environment).

## Instrument checks

`station_status` findings, instrument errors, integration and range, cleanup reports, re-runs with their plan ids.

## DUT hypotheses

What could be wrong with the device itself, and what supports or rules out each hypothesis.

## Resolution

What fixed it or what is still open. "Unresolved" is a valid answer.

## Reproducible

Yes / no / not tried; how many times it was seen (a case seen twice becomes a runbook entry).

## Proposed follow-up

Runbook or card change to propose to the human (never applied by the agent).
