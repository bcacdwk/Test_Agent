---
id: smu-spot-kelvin
title: SMU spot, four-wire (Kelvin) and multi-channel sweep — spot I/V at bias levels; R, offset voltage; MM 16
family: smu
intent: [spot measurement, single bias point, bias list, current forcing, Kelvin, 4-wire, low resistance, milliohm, multi-channel sweep, MM 16, several sweep terminals, WNX]
recipes: [generic.smu_spot, resistor.kelvin_4w, generic.smu_multi_sweep]
device_types: [resistor]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L2
status: sim_validated
confirmation: conditional
knowledge: [knowledge/03-probe-station-wiring.md#kelvin-four-wire-connection, knowledge/03-probe-station-wiring.md#four-wire-resistance, knowledge/06-analysis-extraction.md#resistance-fit, knowledge/02-b1500-instrument.md#integration-time-and-ranging, knowledge/02-b1500-instrument.md#measurement-modes, knowledge/01-device-physics.md#resistor-contact-versus-bulk-resistance]
manual: [PG p391 (4-73) "DI", PG p396 (4-78) "DV", PG p470 (4-152) "MM", PG p380 (4-62) "CMM", PG p102 (2-14) "Multi Channel Sweep", PG p557 (4-239) "WNX", PG p226 (3-46) "Table 3-13"]
debug: [noisy-data, compliance-hit, current-too-high, errx-codes, cleanup-failed-fault, async-run-interrupted]
sources: [blueprint v2 2.7 (smu_spot), blueprint v2 3.1 (generic.smu_spot; resistor.kelvin_4w; generic.smu_multi_sweep), blueprint v2 6.3, blueprint v2 7.4 (L2), deck slide 12, Programming Guide Table 3-13]
version: 2
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# SMU spot, four-wire resistance and multi-channel sweep

## 1. Purpose and applicable devices

`MM 1` spot: each measured terminal is read once per bias level, all at once. `MM 16`: several terminals sweep together.

- `resistor.kelvin_4w`: R of a low-ohmic structure (1 Ohm standard, metal line, contact chain): force current, sense
  voltage on Kelvin probes; leads and contacts drop out of R when both Sense lines are landed.
- `generic.smu_spot` (ad-hoc): `a` through a list of voltages (I measured), optional bias `c`, optional current source
  `d` (V measured; `d_i: 0` = voltmeter); default analysis: the two-wire `resistance` of a's points.
- `generic.smu_multi_sweep` (ad-hoc): `a` the primary staircase, `c` a second sweep on a's steps (equal start and stop
  = constant), `d` a constant bias; all SMU terminals but `b` measured; `a` + `b` alone = the PG one-source example.
- Not for: one device's curves (staircase cards, e.g. [contact-resistor-check](contact-resistor-check.md),
  [mosfet-idvg](mosfet-idvg.md) with `mosfet.idvg_sync`); the floor check ([zero-check](../system/zero-check.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| a | 4-wire: forces I, senses V; spot: V levels, measures I; multi: primary sweep (`WV`), measures I | SMU3 (HRSMU; MPSMU allowed) | 4-wire: Force and Sense both landed on pad a |
| b | `b`: return, ground | GNDU (or an SMU at 0 V) | 4-wire: GNDU Force and Sense both landed on pad b |
| c | optional; spot: constant V; multi: second sweep (`WNX 2`); measures I | another SMU | from the human's pin map |
| d | optional; spot: constant I (measures V); multi: constant V (measures I) | another SMU | from the human's pin map |

- 4-wire: pin map `resistor-4w` (a = SMU3, b = GNDU), DUT profile `resistor-1r`; the pin map cannot show whether
  Sense is landed: ask. Kelvin roles never go through a 16440A selector (Force only; R-ROUTE-01 blocks).
- Generic: `resistor-2t` (a = SMU3, b = GNDU), `resistor-generic`; c and d need the human's pin map (never guess one).
- Routes: none in every phase (direct SMU and GNDU wiring; no selector, SCUU, ASU path change or RSU).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md) first (`short`/`open` stop the work).
- 4-wire: the human confirms Force and Sense landed on both pads (Kelvin probes) and the station profile records
  `kelvin` cabling. Without Sense the recipe silently reads a two-wire value.
- `station_status` clean; pin map, DUT profile and the limits of every terminal given by the human.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `currents` | [-10, -5, 5, 10] mA | -50..50 mA | -50..50 mA | ±I reversal cancels thermal offsets | \|I\| x R must stay well below `vcomp` |
| `vcomp` | 1 V | 0.1..2 V | 0.01..10 V | limits the voltage on an open landing | an open stops at vcomp: class `open` |
| `samples` (`resistor.kelvin_4w`) | 4 | 1..16 | 1..100 | averaging per current | more: lower noise, longer run |
| `integration` (`resistor.kelvin_4w`) | `long` | `long` | `short`, `medium`, `long` | millivolt signals need 16 PLC | shorter: noisier R |
| `a_levels` | [-0.1, -0.05, 0, 0.05, 0.1] V | -1..1 V | -42..42 V | levels of a, in order | three distinct levels for the `resistance` default |
| `a_icomp` | 1 mA | 1 nA..1 mA | 1 pA..100 mA | current compliance of a | above the DUT profile: confirmation |
| `c_v` | 0 V | - | -42..42 V | bias of c | only with c in the pin map |
| `c_icomp` | 100 uA | - | 1 pA..100 mA | compliance of c | |
| `d_i` | 0 A | - | -100..100 mA | current of d; 0 = voltmeter | only with d in the pin map |
| `d_vcomp` | 1 V | 0.1..10 V | 1 mV..42 V | voltage compliance of d | |
| `samples` (`generic.smu_spot`) | 1 | 1..10 | 1..1000 | readings per level | |
| `integration` (`generic.smu_spot`, `generic.smu_multi_sweep`) | `medium` | `medium`, `long` | `short`, `medium`, `long` | noise vs time | |
| `start` | 0 V | - | -42..42 V | multi: terminal a at the first step | |
| `stop` | 1 V | - | -42..42 V | multi: terminal a at the last step | beyond the profile: confirmation |
| `points` | 51 | - | 2..2001 | multi: steps of every sweep terminal | |
| `icomp` | 100 uA | - | 1 pA..100 mA | multi: terminal a compliance | above the profile's `max_abs_i`: confirmation |
| `mode` | `single` | - | `single`, `double` | multi: double = there and back (both terminals) | twice the steps |

Multi sweep: c (`start_c`, `stop_c`, `icomp_c`) and d (`bias_v`, `bias_icomp`) default 0 V, 1 V, 100 uA; 0 V, 100 uA.

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: resistor.kelvin_4w
params: {}
pin_map: resistor-4w
dut_profile: resistor-1r
sim_scenario: resistor_1r_kelvin
```

## 5. Limits and confirmation

- `dut_envelope` (R-DUT-01): a level, current or compliance above the DUT profile (`resistor-1r`: 1 V, 20 mA, so
  `currents: [-0.03, 0.03]` needs confirmation; `resistor-generic`: 1 V, 1 mA). A grounded SMU on `b` gets the sum
  of the sourcing compliances (two 100 mA sources: 200 mA, blocked by R-LIM-02).
- `soft_limit` (R-LIM-03): above 10 mA or 10 V (example policy; live limits in `station_status`); hard limits 42 V /
  100 mA always; module current-source corners: R-LIM-01.
- On hardware: `first_hw_run`, `unverified_pin_map`; generic recipes also `adhoc_recipe`. Destructive: no; a spot
  plan beyond 300 s runs asynchronously, beyond 600 s needs `long_run`.

## 6. Quality criteria

- Status letters: `N` ok; `C` on `a_V` (4-wire) = voltage compliance, the current did not flow: the run stops there,
  class `open`; `T` limited; `V X F D G S U` untrusted: refusal, never force silently.
- 4-wire: r2 below 0.999 or an offset above a few hundred µV: heating, a bad sense contact or thermal EMF; re-land
  (human), repeat with `integration: long`, `samples` up to 16 (autonomous, at most two re-measures).
- Generic spot: as the contact check. Multi sweep: a compliance anywhere stops the sweep (`WM 2,1`: later rows `V`);
  a terminal at the noise floor throughout is not connected (or not wired in the scenario): say so.

## 7. Analysis method

- 4-wire default `kelvin_resistance`: line V = R·I + V0 over the trusted points; reports `resistance` (class
  `in_range`, `open` lower bound or `short` upper bound), `offset_voltage`, `linearity_r2`, `fit.residual_v`
  ([03](../../knowledge/03-probe-station-wiring.md#four-wire-resistance)).
- Generic spot default `resistance` of `a_V`/`a_I` ([06](../../knowledge/06-analysis-extraction.md#resistance-fit));
  `kelvin_resistance` also fits a generic run with a current source (`x`/`y` options).
- Multi sweep: no default analysis; per terminal, e.g. `resistance` with `{x: a_V, y: a_I}`, `plot_iv`. Columns:
  `a_V` (returned source), `c_V` (programmed, follows a), `d_V`, measured `a_I`, `c_I`, `d_I` with status.
- Report measured points with status counts; derived R with class, offset, r2, method, window; Sense landed or not.

## 8. Expected result shape

| structure | expected | red flags |
|---|---|---|
| 1 Ohm standard, 4-wire | R within the standard's tolerance, offset µV, r2 > 0.9999 | R near 1 Ohm + 2 x lead (ohms): Sense not landed |
| metal line or via chain | R scales with length; V symmetric in ±I | asymmetric V(+I), V(-I): diode-like contact, heating |
| two-wire spot or multi sweep on 100 kOhm | R near nominal plus probe and contact resistance | `open`/`short` as in the contact check |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| `open` (voltage compliance) at the first current; current compliance at the first sweep step | probe not landed, broken line; short or wrong pins | stop; contact check; ask the human | `compliance-hit` |
| R about 2x nominal or a few ohms high | Sense not landed (two-wire reading) | ask about the sense probes; compare with `resistor-2t` contact check | `current-too-high` |
| negative R or `failed` | sense lines swapped or floating | stop; ask the human to check the Kelvin wiring | `noisy-data` |
| scattered V, low r2; a terminal noise-dominated | thermal EMF, short integration; probe not landed | `integration: long`, more `samples`; contact check | `noisy-data` |
| run `failed`, fault latched; `aborted` after the session ended | instrument error, unverified cleanup; server killed | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault`, `async-run-interrupted` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-19 | resistor_1r_kelvin | resistor-1r | S20261119T105038Z-8427 | tier ok; R +0.0004 % vs the 1 Ohm truth, `in_range`, r2 > 0.99999; N=16 | - |
| sim | 2026-11-19 | resistor_1r_kelvin without Sense landed | resistor-1r | S20261119T105038Z-44a3 | R = 2.00 Ohm = truth + 2 x 0.5 Ohm leads (two-wire reading, as required) | - |
| sim | 2026-11-19 | resistor_100k (generic.smu_spot) | resistor-generic | S20261119T105038Z-5f23 | tier ok; R -0.09 % vs model truth, `in_range`; N=5 | - |
| sim | 2026-11-19 | resistor_100k (generic.smu_multi_sweep) | resistor-generic | S20261119T111105Z-39ae | tier ok; MM 16 with terminal a alone; `resistance` on a: +0.04 % vs 100 kOhm; N=51 | - |
| hw | pending (bring-up stage L2) | - | - | - | - | - |

Sim runs used temporary config/data folders (not kept). Hardware records `validation/hw/generic.smu_spot.yaml`,
`validation/hw/resistor.kelvin_4w.yaml` and `validation/hw/generic.smu_multi_sweep.yaml` (after stage L2, skill
`b1500-bringup`, from `H...` runs only); until they exist every hardware plan needs `first_hw_run` confirmation.
