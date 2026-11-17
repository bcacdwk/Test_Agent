---
id: <kebab-id>                     # = file name without .md
title: <measurement — extracted quantities>
recipes: [<recipe.id>]             # lint: each exists and its recipe `card:` points back to this file
device_types: [<types>]            # lint: subset of the recipes' device_types
modules: [<e.g. 2x SMU (HRSMU on drain preferred) + GNDU>]
status: <draft|sim_validated|hw_validated>   # lint: = the recipe's effective status on the simulator
confirmation: <never|conditional|always>     # lint: never = example plan tier ok; always = needs_confirmation
knowledge: [<knowledge/NN-file.md#heading-id>]   # lint: file and heading id exist
debug: [<runbook ids>]             # lint: ../b1500-debug/runbooks/<id>.md exists
sources: [<deck slide N>, <manual PDF p.N>]
version: 1
---

# <Card title>

Copy this file to `cards/<id>.md`, replace every `<...>` and each guidance line; keep the ten `## N. Title`
headings exactly (use `###` inside a section). A card stays within 150 lines; `uv run b1500 dev lint-skills`
checks it, including the example plan on the simulator. New cards need human review.

## 1. Purpose and applicable devices

<Question this card answers; devices it applies to; when NOT to use it and which card to use instead.>

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| <gate> | <recipe role> | <SMU slot (type)> | <guard, Kelvin, GNDU, low-current notes> |

<Example pin map name in `config/pinmaps/`; what a human must check before writing a new one.>

## 3. Pre-run checklist

- <Contact check (`contact-resistor-check`) on a fresh landing; `station_status` clean; DUT profile chosen.>

## 4. Recipe and parameters

<One row per recipe parameter; default and recipe range copied from `list_recipes(recipe_id)`.>

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `<param>` | <recipe default, e.g. 50 mV> | <low..high unit> | <recipe range low..high unit> | <reason> | <effect on data> |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: <recipe.id>
params: {}                    # only values that differ from the recipe defaults
pin_map: <pin map name>
dut_profile: <DUT profile name>
sim_scenario: <config/sim/scenarios name>
```

## 5. Limits and confirmation

<Binding limits (module, policy, DUT profile); which params trigger which confirm reason; destructive yes/no.>

## 6. Quality criteria

<Status-code policy; max limited fraction in the fit window; noise; shape sanity; when to re-measure, which knobs.>

## 7. Analysis method

<Default `analyze_run` method + options + window rule; alternatives and when to use them; fields to report.>

## 8. Expected result shape

<Typical ranges per device type and sim scenario; red flags that mean the data are not trustworthy.>

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| <symptom> | <cause> | <non-sourcing or in-envelope check> | <runbook id> |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | <YYYY-MM-DD> | <scenario> | <DUT profile> | <run_id> | <value vs model truth> | - |
| hw (M4) | <YYYY-MM-DD> | <station> | <DUT> | <run_id> | <value vs reference> | <name> |
