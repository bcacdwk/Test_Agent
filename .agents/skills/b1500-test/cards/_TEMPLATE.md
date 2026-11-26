---
id: <kebab-id>                     # = file name without .md
title: <measurement — extracted quantities>
family: <smu|cmu|spgu|wgfmu|nvm|reliability|system>   # lint: = the folder cards/<family>/ and every recipe's family
intent: [<keywords a request uses, e.g. Vth, gm, SS>]  # shown in the generated index cards/README.md
recipes: [<recipe.id>]             # lint: each exists and its recipe `card:` points back to this file
analysis: []                       # optional: analysis methods the card documents; recipes [] = analysis-only card
device_types: [<types>]            # lint: subset of the recipes' device_types (empty only if they name none)
modules: [<HRSMU, MPSMU, MFCMU, HVSPGU, WGFMU, GNDU ...>]   # lint: subset of the module types the recipe roles use
routes: [<switch kind:state, e.g. selector_16440a:pgu>]   # lint: subset of the routes the roles' resources need
bringup_stage: <S0|L0..L10>        # lint: a blueprint 7.4 stage; once its stage file exists it runs these recipes
recipe_stages: {}                  # optional: {<recipe.id>: <stage>} for a recipe another stage validates
status: <draft|sim_validated|hw_validated>   # lint: = the recipe's effective status on the simulator
confirmation: <never|conditional|always>     # lint: never = example plan tier ok; always = needs_confirmation
knowledge: [<knowledge/NN-file.md#heading-id>]   # lint: file and heading id exist
manual: [<PG p433 (4-115) "ERSSP">]   # lint: canonical citations of catalog documents (page, label, keyword)
debug: [<runbook ids>]             # lint: ../b1500-debug/runbooks/<id>.md exists
sources: [<manual page>, <lwp file>, <blueprint section>, <application note>]   # never the deck (illustrative only)
version: 1
---

# <Card title>

Copy this file to `cards/<family>/<id>.md`, replace every `<...>` and each guidance line; keep the ten
`## N. Title` headings exactly (use `###` inside a section). A card stays within 150 lines. Set the recipe's
`card:` to the new path, then run `uv run b1500 dev gen-index` (the index is generated) and
`uv run b1500 dev lint-skills` (it also validates the example plan on the simulator). New cards need human review.

## 1. Purpose and applicable devices

<Question this card answers; devices it applies to; when NOT to use it and which card to use instead.>

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| <gate> | <recipe role> | <SMU slot (type), or SEL1.OUT1 via a selector> | <guard, Kelvin, GNDU, low-current notes> |

<Example pin map name in `config/pinmaps/`; what a human must check before writing a new one.>

- Routes: <per phase, e.g. "program: SEL1.OUT1 -> PGU; read: SEL1.OUT1 -> SMU; cleanup: rest"; or "none in every
  phase" when no switch is involved>.

## 3. Pre-run checklist

- <Contact check (`contact-resistor-check`) on a fresh landing; `station_status` clean; DUT profile chosen.>

## 4. Recipe and parameters

<One row per recipe parameter; default and recipe range copied from `list_recipes(recipe_id)`. When the card's
recipes differ for a parameter, write one row per recipe: `` `param` (`recipe.id`) ``. Defaults are examples, not
values for the human's device: say "example default, set it per device" in `why` where a device sets the value.
`recommended`: a method convention or a sourced value (manual page, `lwp/...` file), otherwise `-` (the recipe
range and the DUT profile bound it); the agent re-measures on its own only inside a sourced range.>

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `<param>` | <recipe default, e.g. 50 mV> | <sourced low..high unit, or -> | <recipe range low..high unit> | <reason> | <effect on data> |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: <recipe.id>
params: {}                    # only values that differ from the recipe defaults
pin_map: <pin map name>
dut_profile: <DUT profile name>
sim_scenario: <config/sim/scenarios name>
```

## 5. Limits and confirmation

<Binding limits (module, policy, DUT profile; pulse, AC or stress envelopes); which params trigger which confirm
reason (`dut_envelope`, `soft_limit`, `soft_pulse`, `soft_cmu`, `long_run`, `physical_setup`,
`unverified_topology`, `destructive` ...); destructive yes/no; sync or async (long runs).>

## 6. Quality criteria

<Status-code policy; max limited fraction in the fit window; noise; shape sanity; when to re-measure, which knobs.>

## 7. Analysis method

<Default `analyze_run` method + options + window rule; alternatives and when to use them; fields to report.>

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| device | expected (source) | red flags |
|---|---|---|
| <device type> | <a value with its source (manual page, `lwp/...` file, hardware validation record, code default named as such), a physical bound labelled (physics) or (textbook), or a blank: `TODO(owner)`: <question?>, `TODO(verify)[<step ids>]`, `TODO(cite)`, or "unknown" with a link to the knowledge section that holds it. Never simulator truth, never deck text.> | <signs of untrustworthy data; thresholds only from bring-up repeatability (`TODO(verify)[<step>]`) or the human> |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| <symptom> | <cause> | <non-sourcing or in-envelope check> | <runbook id> |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | <YYYY-MM-DD> | <scenario> | <DUT profile> | <S... run_id> | <value vs model truth> | - |
| hw | pending (bring-up stage <Lx>) | - | - | - | - | - |

Hardware record: `validation/hw/<recipe.id>.yaml` (one per recipe; reviewed by a human after bring-up stage
<Lx>, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs).
