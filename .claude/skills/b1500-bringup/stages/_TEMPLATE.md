---
stage: <S0|L0..L10>                # lint: the stage of this file name (s0-physical.md = S0, l4-mosfet.md = L4 ...)
title: <stage goal>
recipes: [<recipe ids the stage runs>]   # lint: registered; includes every recipe of the cards
                                         # whose bringup_stage is this stage
checks:                                  # the machine-readable rows of section 4 (b1500 bringup record copies them)
  - id: <check id>                       # lint: named as `<check id>` in section 4
    recipe: <recipe id>                  # omit for a check of the stage record
    quantity: <quantity>                 # analysis quantity, noise_<column>, result, cleanup or a probe line name
    method: <analysis method>            # omit for any method
    unit: <unit>
    reference: <what the value is compared with>
    tolerance: {rel: 0.01}               # omit = recorded only; or {absolute: X}, {factor: X}, {max_abs: X}
    text: <criterion as shown in section 4>
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# <Stage id> - <title>

Copy this file to `stages/<file name of the stage>.md` (the list is in part 2 of `SKILL.md`), replace every
`<...>` and each guidance line, keep the six `## N. Title` headings exactly (use `###` inside a section). A stage
file stays within 150 lines; `uv run b1500 dev lint-skills` checks it. Name only commands that exist in
`uv run b1500 --help`. Stage files need human review.

## 1. Preconditions

- <previous stage signed off (`uv run b1500 bringup status`); `station_status` clean; `uv run b1500 doctor` without
  FAIL>
- <standards, DUTs and references at hand (values, certificates, EasyEXPERT files)>

## 2. Physical steps (human)

<Numbered steps only the human does (cabling, probes, instrument front panel, external meters, `config adopt`),
each with what the human confirms in chat. The agent never does them and never assumes they are done.>

## 3. Agent steps

<Numbered: read-only checks first, then each validated plan (recipe, params, pin map, DUT profile, expected tier
and confirm reasons), the quality gate and the `analyze_run` method. Consent per plan as in skill b1500-test.>

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `<check id>` | <value and unit> | <+- tolerance (owner may tighten)> | <reference: DMM, certificate, EasyEXPERT, manual citation> |

- TODO(verify) (blueprint v2 7.6 items <n, ...>): <the hardware facts this stage settles; the only TODO(verify) of
  the file; the roadmap's M12 table lists the items per stage>

## 5. Abort criteria

- <observation> → `safe_shutdown(reason)`, report, wait for the human. <Never relax the criterion.>

## 6. Record

<The records this stage needs: one per recipe with checks and the stage record
(`uv run b1500 bringup record STAGE --run H...`), `H...` runs only; the human reviews them and moves them to
`validation/hw/`. Rehearsal: none.>
