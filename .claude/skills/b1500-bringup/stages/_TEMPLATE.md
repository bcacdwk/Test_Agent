---
stage: <S0|L0..L10>                # lint: the stage of this file name (s0-physical.md = S0, l4-mosfet.md = L4 ...)
title: <stage goal>
recipes: [<recipe ids the stage runs>]   # lint: registered, not reserved; includes every recipe of the cards
                                         # whose bringup_stage is this stage
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# <Stage id> — <title>

Copy this file to `stages/<file name of the stage>.md` (the list is in part 2 of `SKILL.md`), replace every
`<...>` and each guidance line, keep the six `## N. Title` headings exactly (use `###` inside a section). A stage
file stays within 150 lines; `uv run b1500 dev lint-skills` checks it. Name only commands that exist in
`uv run b1500 --help`. Stage files need human review.

## 1. Preconditions

- <previous stage signed off by the human; `station_status` clean; `uv run b1500 doctor` without FAIL>
- <standards, DUTs and references at hand (values, certificates, EasyEXPERT files)>

## 2. Physical steps (human)

<Numbered steps only the human does (cabling, probes, instrument front panel, external meters), each with what
the human confirms in chat. The agent never does them and never assumes they are done.>

## 3. Agent steps

<Numbered: read-only checks first, then each validated plan (recipe, params, pin map, DUT profile, expected tier
and confirm reasons), the quality gate and the `analyze_run` method. Consent per plan as in skill b1500-test.>

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| <quantity> | <value and unit> | <± tolerance (owner may tighten)> | <reference: DMM, certificate, EasyEXPERT, manual citation> |

## 5. Abort criteria

- <observation> → `safe_shutdown(reason)`, report, wait for the human. <Never relax the criterion.>

## 6. Record

<Draft records this stage produces from `records/_TEMPLATE.yaml` (one per recipe), the quantities they hold,
`H...` runs only; the human reviews them and moves them to `validation/hw/<recipe_id>.yaml`.>
