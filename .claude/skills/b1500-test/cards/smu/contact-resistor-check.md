---
id: contact-resistor-check
title: Contact / resistor check (±0.1 V) — R, linearity, offset; open, short or in range
family: smu
intent: [contact check, landing, resistance, open/short, 2-wire R]
recipes: [basic.contact_resistor]
device_types: [resistor, nmos, pmos, igzo_tft, fefet, diode]
modules: [HRSMU, MPSMU, GNDU]
routes: []
bringup_stage: L2
status: sim_validated
confirmation: conditional
knowledge: [knowledge/03-probe-station-wiring.md#contact-checks, knowledge/01-device-physics.md#resistor-contact-versus-bulk-resistance, knowledge/06-analysis-extraction.md#resistance-fit, knowledge/03-probe-station-wiring.md#probe-contact-and-overdrive]
manual: [PG p568-569 (4-250) "WV", PG p552 (4-234) "WM"]
debug: [noisy-data, compliance-hit, current-too-high, errx-codes, cleanup-failed-fault]
sources: [blueprint 6.4, "deck slide 12, 17 (topics only, illustrative: not evidence)", lwp/matlab_B1500/IdVg_test_20251004_*.csv]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Contact / resistor check

## 1. Purpose and applicable devices

Is the probe landed, and does the terminal pair behave as expected? A ±0.1 V staircase between two terminals gives
R, linearity and offset current, classified `open`, `short` or `in_range`. It never stresses a device, so it is the
gate-keeper on every fresh landing and the first safe check of skill `b1500-debug`.

- Structures of known R well above 100 Ohm (a resistor, two pads of one device): compare R with the expected value
  yourself; the class uses `r_short_ohm`/`r_open_ohm`, not the DUT profile. A metal line or two probes on one pad
  (below 100 Ohm: 1 mA compliance at 0.1 V) always reads `short` here.
- Transistor or diode landings: catches shorts. A normally-off transistor's drain-source path with the gate off and
  a diode below turn-on read `open` by design (a normally-on, depletion TFT conducts with the gate off: ask the
  human for the Vth sign), so `open` alone does not prove the landing: the device response does (Id rising with
  Vg, forward diode current). After a noise-floor Id-Vg or diode curve, still run this check as step 3 of runbook
  `noisy-data` (skill `b1500-debug`): it rules out a short or parallel path and records the terminal floor; the
  "not landed" verdict there comes from the flat device response.
- Not for: precise low resistance (two-wire includes probes and cables: four-wire [smu-spot-kelvin](smu-spot-kelvin.md)),
  diode or transistor parameters ([diode-iv](diode-iv.md), [mosfet-idvg](mosfet-idvg.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| a | `a`: forced side, sweeps V, measures I | SMU3 (HRSMU; MPSMU/HPSMU allowed) | HRSMU resolves the open-circuit floor |
| b | `b`: return side, ground | GNDU | |

- Example pin map `resistor-2t` (a = SMU3, b = GNDU) with DUT profile `resistor-generic`. Roles bind to pin-map
  terminals of the same name, so the check needs a two-terminal map.
- On a `mosfet-4t` landing SMU3 is the drain probe and the GNDU carries source and bulk: `resistor-2t` then checks
  drain to source/bulk with the gate SMU switched off. Use it on any landing of the example station.
- Another pair (for example the gate probe on SMU4) needs a two-terminal pin map written by the human. Ask; never
  write or guess one.
- Routes: none in every phase (direct SMU and GNDU wiring; no selector, SCUU, ASU or RSU in the path).

## 3. Pre-run checklist

- Fresh landing (probes just placed or moved, new die, or you do not know): run this card before any other card.
- `station_status`: backend shown, no latched fault, no lock holder, no pending errors; `resistor-2t` (or the
  human's map) and `resistor-generic` (or the human's profile) are listed. Missing: ask the human.
- Know the expected answer before running: resistor near its nominal; normally-off transistor or diode pair `open`
  (normally-on TFT: ask).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `v_start` | -0.1 V | -0.1..-0.01 V | -1..0 V | small and symmetric about 0 V | larger \|V\| leaves the linear contact regime |
| `v_stop` | 0.1 V | 0.01..0.1 V | 0..1 V | as `v_start` | same |
| `points` | 21 | 11..41 | 5..201 | 10 mV steps by default | more points: better r2 estimate, longer run |
| `icomp` | 1 mA | 100 uA..1 mA | 1 nA..10 mA | 1 mA at 0.1 V marks R ≤ 100 Ohm as short | above the DUT profile: confirmation |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | noise vs time | `long` lowers the floor for open checks |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: basic.contact_resistor
params: {}
pin_map: resistor-2t
dut_profile: resistor-generic
sim_scenario: resistor_100k
```

## 5. Limits and confirmation

- Module (R-LIM-01) and policy hard limits (42 V, 100 mA) are far away; the recipe ranges (|V| ≤ 1 V, compliance
  ≤ 10 mA) stay at or below the example policy's soft limits (10 V, 10 mA): no `soft_limit` unless a human
  tightened them (live limits in `station_status`).
- `dut_envelope` (R-DUT-01): `icomp` above the profile's `max_abs_i` (`resistor-generic`: 1 mA; example
  `icomp: 0.005` needs confirmation) or |V| above its `max_abs_v` (1 V).
- On hardware: `unverified_pin_map` while the map says `certainty: unverified`; `first_hw_run` until the recipe is
  `hw_validated`. Destructive: no. The example plan is tier `ok`.

## 6. Quality criteria

- Status letters: `N` ok. `C` on `a_I` is the evidence for `short` (the sweep aborts there; later rows count as
  `aborted`). `T` limited. `V X F D G S U` untrusted: the analysis refuses; never force it.
- A noise-dominated current (signal range < 10x noise) is the evidence for `open`, reported as a lower bound of R
  with the warning "Check the probe landing"; on a transistor or diode pair that `open` is the expected reading.
- Linearity r2 < 0.99 gives a warning "not an ohmic contact" on a resistor: barrier or oxide at a tip.
- Re-measure (autonomous, at most two, must stay tier `ok`): `integration: long`, `points` inside 11..41. A
  `failed` short classification (compliance bound above `r_short_ohm`) is no reason to raise `icomp` above the
  profile: report it and ask.

## 7. Analysis method

- Default `resistance` with `{r_short_ohm: 100, r_open_ohm: 1e9}` (recipe default; `run_plan` only previews it; report
  the value from your own `analyze_run` call): least-squares line I = G·V + I0 over the trusted points; R = 1/G,
  `linearity_r2`, `offset_current` = I0 (`fit.v_offset`).
- Classes: `short` = compliance at the first compliance point (R upper bound) or R ≤ `r_short_ohm`; `open` = noise
  floor (R lower bound) or R ≥ `r_open_ohm`; else `in_range`.
- Options: set `r_short_ohm`/`r_open_ohm` around the profile nominal with `analyze_run(run_id, "resistance",
  {...})`; `plot_iv` with `scale: linear` for a picture; `quality_report` for noise and SNR.
- Report: measured a_V/a_I points and status counts; derived R with its bound (exact, upper, lower) and class, r2,
  offset current, window, method ([06](../../knowledge/06-analysis-extraction.md#resistance-fit)).

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| structure | expected (source) | red flags |
|---|---|---|
| resistor structure (well above 100 Ohm) | `in_range`, R near nominal plus probe and contact resistance, r2 > 0.999 (general practice, not checked against a source), offset ≪ signal | `open`, `short`, R off by orders of magnitude, r2 < 0.99, asymmetric curve |
| normally-off transistor drain-source, gate off | `open`; current at the module floor (lab HRSMU, open probes, 1 PLC: about 0.07 pA rms, readings within about ±0.2 pA; `lwp/matlab_B1500/IdVg_test_20251004_*.csv`) | `short`; an `in_range` R on a normally-off device (a normally-on TFT conducts with the gate off: ask for the Vth sign first) |
| diode pair at ±0.1 V | `open` or a non-linear warning (below turn-on; a low-barrier Schottky or large-area diode may conduct measurably) | `short`; ohmic and symmetric |
| probes lifted (floor check) | `open`; R lower bound shows the station floor | offset or slope well above the floor: leakage path, charging cable |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| `open` on a resistor structure | probe not landed, wrong pad, broken line | repeat once with `integration: long`; ask the human to re-land | `noisy-data` |
| `short`, compliance at the first step | probes touching, wrong pads, damaged structure | stop; ask the human to inspect the landing | `compliance-hit` |
| R orders of magnitude below nominal | parallel path, wrong pads or pin map | compare the pin map with the wiring together with the human | `current-too-high` |
| non-linear or asymmetric I-V | oxide or contamination on a tip | ask for re-landing or tip cleaning; re-run | `noisy-data` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | resistor_100k | resistor-generic | S20261117T174641Z-9f17 | tier ok; `in_range`, R -0.02 % vs model truth, r2 > 0.99999; N=21 | - |
| sim | 2026-11-18 | open_drain_noisy (mosfet-4t landing, drain lifted) | resistor-generic | S20261117T174642Z-d11c | `open` (R lower bound; current noise-dominated) | - |
| sim | 2026-11-18 | nmos_basic (healthy transistor, gate off) | resistor-generic | S20261117T174642Z-0333 | `open` (R lower bound): the expected transistor reading | - |
| hw | pending (bring-up stage L2) | - | - | - | - | - |

Sim rows: the example plan (or the named damaged scenario) run through `B1500Service` with temporary
`B1500_CONFIG_DIR`/`B1500_DATA_DIR`; those run folders were not kept. Hardware record: `validation/hw/basic.contact_resistor.yaml`
(reviewed by a human after bring-up stage L2, skill `b1500-bringup`; drafts only from hardware `H...` runs,
never from simulator `S...` runs). Until it exists every hardware plan needs `first_hw_run` confirmation.
