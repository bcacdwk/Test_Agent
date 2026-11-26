---
id: <YYYY-MM-DD>-<slug>          # = file name without .md; date of the observation (illustrative: example-<slug>)
title: <one-line symptom>        # illustrative: "Example: <symptom>"
status: draft                    # draft (written by the agent) | reviewed (set only by a human)
reviewed_by: null                # human name, set together with status: reviewed
runbook: <runbook id | new>      # the runbook that applied, or "new" if none did; its sources name this case
origin: observed                 # observed (seen in the lab) | illustrative (an example: nothing was observed)
backend: <sim | visa | none>     # backend of the runs; none: no run of this agent (illustrative, or a lab record)
station: <station profile name, "unknown", or "none" (illustrative)>
device: <device type; DUT profile / dut_instance>   # illustrative: "<type> (illustrative; no device)"
runs: [<run_id>]                 # every run of the observation (H... on visa, S... on sim, none: []), each annotated
sources: [<run notes>, <lab notebook page>]   # records of the observation; the owner's deck is illustrative, never one
reproduction: null               # or the simulator reproduction: scenario, scenarios, steps, expect, discriminator
open_questions: 0                # = the numbered questions of "Open questions for the owner"
---

# <Title>

Draft written by the agent for human review. Facts come from runs, lab records and the human's answers; label every
guess. An illustrative case (an example of a kind of problem, written from a list rather than an event) says so in
its first sentence, has no runs, no `visa` backend and no observation date, and uses no past tense for the lab.

## Symptom

What looked wrong, in one or two sentences, with the tool result that showed it (illustrative: "Example symptom: ...").

## Observed data and status codes

Run ids, outcome, status-code counts, quality verdict and warnings, SNR, the values that looked wrong (with units).
Illustrative: "None (illustrative)."

## Physical checks

Each question asked and the human's answer (probes, cables, Guard, grounding, shield box, environment).

## Instrument checks

`station_status` findings, instrument errors, integration and range, cleanup reports, re-runs with their plan ids.

## DUT hypotheses

What could be wrong with the device itself, and what supports or rules out each hypothesis.

## Resolution

What fixed it or what is still open. "Unresolved" is a valid answer; illustrative: "Not applicable (illustrative)."

## Reproducible

Yes / no / not tried; how many times it was seen (an observed case seen twice becomes a runbook entry; an
illustrative case was never seen: "Not observed in the lab").

## Proposed follow-up

Runbook or card change to propose to the human (never applied by the agent).

## Simulator reproduction (SIMULATED)

Only for a cause the simulator models; otherwise say which causes have no model and why `reproduction: null`.
The steps, the symptom signature (`expect`) and the runbook check that separates the causes (`discriminator`)
are in the frontmatter (grammar: docstring of `src/b1500_test_agent/devtools/skills/cases.py`; checked by
`uv run b1500 dev cases check`). Quote one run of `uv run b1500 dev cases reproduce <id>` here: date, commit, run
ids and the values its expectations read, all labelled SIMULATED. Never copy them into the sections above or into
`runs`.

## Open questions for the owner

A numbered list (`1. ...`): each fact only the human can give, one question per item; `open_questions` counts the
items. No `TODO(owner)` anywhere else in the case. The human answers them in the sections above, then sets
`status: reviewed` and `reviewed_by` (agents never do).
