---
id: diode-iv
title: Diode I-V (voltage staircase or log current sweep) — Is, n, Rs, leakage at Vr, Vf at a current
family: smu
intent: [diode, Is, ideality, Rs, reverse leakage, forward I-V, forward voltage, Vf, current forcing]
recipes: [basic.diode_iv, basic.iv_force_i]
device_types: [diode]
modules: [HRSMU, GNDU]
routes: []
bringup_stage: L3
status: sim_validated
confirmation: conditional
knowledge: [knowledge/01-device-physics.md#pn-diode-shockley-equation-and-ideality-factor, knowledge/01-device-physics.md#diode-series-resistance-reverse-leakage-and-breakdown, knowledge/06-analysis-extraction.md#diode-fit-is-n-and-rs, knowledge/06-analysis-extraction.md#forward-voltage, knowledge/06-analysis-extraction.md#leakage-at-bias, knowledge/03-probe-station-wiring.md#guard-for-low-current]
manual: [PG p568-569 (4-250) "WV", PG p551-552 (4-233) "WI", PG p552 (4-234) "WM"]
debug: [compliance-hit, current-too-high, noisy-data, errx-codes, cleanup-failed-fault]
sources: [blueprint 6.4, deck slide 10, deck slide 9]
version: 1
---

# Diode I-V

## 1. Purpose and applicable devices

Ideality factor n, saturation current Is and series resistance Rs from the forward branch, and the reverse leakage
at `v_rev` against a limit (pass/fail), from one staircase on the anode: `v_rev` → 0 V → `v_fwd` (`basic.diode_iv`).
`basic.iv_force_i` forces the anode current instead (log sweep `i_start` → `i_stop`, voltage measured): the forward
voltage Vf at `i_vf` (default 1 mA) and n, Is, Rs over many decades, without a reverse branch. Applies to pn and
Schottky diodes and to junctions with their own two-terminal pin map and diode DUT profile from the human.

- Not for: breakdown voltage (destructive; excluded here by the DUT envelope and compliance abort, and not offered in
  v1), C-V or doping profiles ([reserved](../reserved/README.md)), resistors or landing checks
  ([contact-resistor-check](contact-resistor-check.md)).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| anode | `anode`: sweeps V, measures I (`basic.iv_force_i`: sweeps I, measures V) | SMU3 (HRSMU required for `basic.diode_iv`) | Guard connected for pA leakage |
| cathode | `cathode`: ground | GNDU | |

- Example pin map `diode-2t` (anode = SMU3, cathode = GNDU) with DUT profile `diode-generic`. An MPSMU anode is
  blocked (R-PIN-01): reverse leakage needs the HRSMU.
- A cathode-up structure or another pad pair needs a pin map written by the human. Ask; never write one.
- Routes: none in every phase (direct SMU and GNDU wiring; no selector, SCUU, ASU or RSU in the path).

## 3. Pre-run checklist

- Fresh landing: [contact-resistor-check](contact-resistor-check.md) with `resistor-2t` + `resistor-generic` on the
  same landing (SMU3 = anode probe). Expected `open` or a non-linear warning (below turn-on); `short` stops the work.
- `station_status` clean (no fault, no lock holder, no errors); `diode-2t` and a diode DUT profile listed. Unknown
  diode or missing profile: ask the human for the profile (reverse and forward limits); never invent one.
- Check `v_rev` against the profile and any known breakdown voltage before planning.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `v_rev` | -5 V | -5..-1 V | -20..0 V | reverse bias where leakage is judged (sweep start) | more negative: nearer breakdown; beyond the profile: confirmation |
| `v_fwd` | 0.8 V | 0.6..1 V | 0..2 V | reach the Rs-dominated top of the forward branch | too low: Rs not resolved; too high: compliance |
| `points` (`basic.diode_iv`) | 291 | 201..581 | 21..2001 | 20 mV steps by default | finer steps: more fit points per decade |
| `icomp` | 10 mA | 1..10 mA | 1 nA..100 mA | forward current limit; stops a breakdown | above 10 mA: confirmation |
| `leak_limit_a` | 1 nA | 1 pA..1 uA | 1 fA..1 mA | pass/fail limit at `v_rev` (analysis only) | no effect on the sweep |
| `integration` | `medium` | `medium`, `long` | `short`, `medium`, `long` | `long` for pA leakage | slower sweep |
| `i_start` (`basic.iv_force_i`) | 1 nA | 100 pA..10 nA | 1 pA..1 mA | lowest forced current (log sweep start) | lower: more decades for n |
| `i_stop` (`basic.iv_force_i`) | 10 mA | 1..10 mA | 1 nA..100 mA | top decade resolves Rs | above 10 mA: confirmation |
| `points` (`basic.iv_force_i`) | 71 | 41..141 | 11..1001 | 10 points per decade by default | |
| `vcomp` (`basic.iv_force_i`) | 2 V | 1..3 V | 0.1..10 V | anode voltage limit: an open contact stops here | above the profile: confirmation |
| `i_vf` (`basic.iv_force_i`) | 1 mA | 1 uA..10 mA | 1 pA..100 mA | current of the reported Vf (analysis only) | must lie inside the sweep |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: basic.diode_iv
params: {}
pin_map: diode-2t
dut_profile: diode-generic
sim_scenario: diode_basic
```

Current forcing (tier `ok` on `diode_basic`): `uv run b1500 plan basic.iv_force_i --pin-map diode-2t --dut diode-generic`.

## 5. Limits and confirmation

- `soft_limit` (R-LIM-03): `v_rev` below -10 V, `icomp` or `i_stop` above 10 mA (example policy; live limits in
  `station_status`).
- `dut_envelope` (R-DUT-01): |`v_rev`|, `v_fwd` or `vcomp` above the profile's `max_abs_v` (`diode-generic`: 5 V) or
  `icomp`/`i_stop` above its `max_abs_i` (10 mA). Example: `v_rev: -12` triggers both reasons.
- Hard limits 42 V / 100 mA and the HRSMU rating (R-LIM-01) are never reached inside the recipe ranges.
- On hardware: `unverified_pin_map`, `first_hw_run` (until `hw_validated`). Destructive: no; never move `v_rev`
  towards breakdown to "see where it breaks" (that is a destructive test v1 does not offer).

## 6. Quality criteria

- Status letters: `N` ok; `C`/`T` limited and excluded from the fit (≤ 5 % in the fit window, else a warning);
  `V X F D G S U` untrusted: the fit refuses; never force it silently.
- `C` at the top of the forward branch: `icomp` limited the current and the sweep stopped there (rows after it count
  as `aborted`); the fit uses the points below. `C` on the reverse branch: breakdown or short, stop and report.
- Reverse current at the noise floor is normal: `leakage_at` reports an upper bound (below detection), not a refusal.
  A noise-dominated forward branch is not: the diode is not contacted. `basic.iv_force_i`: `C` = the anode reached
  `vcomp` (open contact, or the current needs more voltage): the sweep stopped, rows after it are `aborted`.
- Re-measure (autonomous, at most two, stays `ok`): `integration: long` for leakage, `points` and `v_fwd` inside
  the recommended range. Never extend `v_rev` or raise `icomp` beyond the profile without a new confirmed plan.

## 7. Analysis method

- Defaults (`run_plan` only previews them; report the values from your own `analyze_run` calls): `diode_fit`:
  least-squares fit of V = n·U_T·ln(I/Is) + Rs·I over the forward window `i_min_a`..`i_max_a` (default: 100x above
  noise and shunt leakage up to the largest trusted current), U_T = kT/q at `temperature_k` 300 K; results `n`, `is`,
  `rs` with r2 and rms residual. `leakage_at` with `{v_param: v_rev, limit_param: leak_limit_a}`: |I(`v_rev`)|, class
  `pass`/`fail`, bound exact, upper (noise floor) or lower (compliance). `basic.iv_force_i`: `forward_voltage`
  `{i_param: i_vf}` (Vf at 1 mA, log-I interpolation) and `diode_fit` on the measured V against the forced I.
- Options: `i_min_a`, `i_max_a` (narrow the window), `temperature_k` (state the real chuck temperature); leakage at
  another bias: `analyze_run(run_id, "leakage_at", {"v": -1.0, "limit_a": 1e-9})`; `plot_iv` with `scale: log`.
- Report: measured branch currents and status counts; derived n, Is, Rs with the fit window and points used;
  leakage at `v_rev` with bound, limit and class; the temperature assumption
  ([06](../../knowledge/06-analysis-extraction.md#diode-fit-is-n-and-rs)).

## 8. Expected result shape

| device | typical | red flags |
|---|---|---|
| Si pn junction (small signal) | n 1.0-2 (near 1 when diffusion dominates); Is about 1e-16 to 1e-12 A (area dependent); Rs ohms to tens of ohms; leakage pA to nA at a few volts reverse | n < 1 (noise or wrong window); n > 2 over the whole window |
| Schottky diode | n about 1.0-1.3; Is orders of magnitude above a pn junction of the same area; higher leakage | ohmic, symmetric curve (short or resistor) |
| any diode | about 60·n mV per decade of forward current over several decades at 300 K | compliance on the reverse branch; steep reverse rise (soft breakdown); noise-dominated forward branch |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| forward branch stops early with `C` | `icomp` below the forward current at `v_fwd` | analyse the points below; next plan with a lower `v_fwd` | `compliance-hit` |
| compliance or a jump on the reverse branch | breakdown, damaged junction, short | stop; report; ask the human (no higher \|V\|) | `compliance-hit` |
| current orders of magnitude too high, ohmic | short, wrong pads or pin map | contact check; compare the pin map with the wiring | `current-too-high` |
| forward branch noise-dominated | probe not landed | contact check; ask for re-landing | `noisy-data` |
| run `failed`, errors, fault latched | instrument error, unverified cleanup | `safe_shutdown`, then skill `b1500-debug` | `errx-codes`, `cleanup-failed-fault` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-18 | diode_basic | diode-generic | S20261117T174641Z-f3e0 | tier ok; n +0.03 %, Is +0.5 %, Rs -0.2 % vs model truth; leakage at `v_rev` +2 %, `pass`; N=291 | - |
| sim | 2026-11-19 | diode_basic | diode-generic | S20261119T111102Z-8f17 | `basic.iv_force_i` tier ok; Vf at 1 mA -0.2 uV vs the model; n +0.01 %, Is +0.2 %, Rs -0.02 %; N=71 | - |
| hw | pending (bring-up stage L3) | - | - | - | - | - |

Sim runs used temporary config/data folders (not kept). Hardware records `validation/hw/basic.diode_iv.yaml`,
`validation/hw/basic.iv_force_i.yaml` (reviewed after stage L3, skill `b1500-bringup`; only from hardware `H...`
runs, never `S...`). Until they exist every hardware plan needs `first_hw_run` confirmation.
