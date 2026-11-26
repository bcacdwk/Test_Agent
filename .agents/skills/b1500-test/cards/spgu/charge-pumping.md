---
id: charge-pumping
title: MOSFET charge pumping — Icp vs frequency and base level, charge per cycle Qcp, Nit and Dit
family: spgu
intent: [charge pumping, Icp, interface traps, Dit, Nit, base-level sweep, gate pulses, substrate current]
recipes: [mosfet.charge_pumping]
device_types: [nmos, pmos]
modules: [HVSPGU, HRSMU, MPSMU]
routes: [selector_16440a:pgu]
bringup_stage: L7
status: sim_validated
confirmation: conditional
knowledge: [knowledge/05-reliability-defects.md#charge-pumping, knowledge/05-reliability-defects.md#interface-traps-dit, knowledge/09-pulse-spgu-selector.md#readings-during-a-train, knowledge/09-pulse-spgu-selector.md#hv-spgu-output-and-the-ser-load, knowledge/11-switching-routing.md#the-16440a-selector]
manual: [EX p518 (9-12) "Charge Pumping", PG p142 (2-54) "SPST", PG p507 (4-189) "SER", PG p512 (4-194) "SPRM"]
debug: [spgu-pulse-no-effect, spgu-load-mismatch, spgu-selector-state, noisy-data]
sources: [blueprint v2 3.3 (mosfet.charge_pumping, nmos_cv), 2.7 (SMU spot during the train), Groeseneken et al. IEEE TED 31 42 (1984; not checked in the repo; TODO(cite))]
version: 1
---

# MOSFET charge pumping

## 1. Purpose and applicable devices

How many interface traps does the gate stack have? Gate pulse trains from the HV-SPGU swing the surface from
accumulation to inversion; the bulk SMU reads the recombination current `Icp = q f A D̄it ΔE` while each train runs.
`Icp` must grow linearly with the frequency; its slope `Qcp` (charge per cycle) gives `Nit = Qcp/(q A)`.

- n- or p-channel MOSFETs with a separate bulk (substrate, well or chuck) contact and accessible source and drain.
- Frequency sweep (default, base below Vfb): `Qcp` and its linearity. Base-level sweep (several `v_base`): the
  plateau, its edges near Vth - amplitude and Vfb.
- Not for: devices without a bulk contact (SOI, TFTs: no recombination path); DC Dit estimates (SS, C-V).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| gate | `gate` (pgu) | HV-SPGU 101 via `SEL1.OUT1` (PGU input) | 1 MOhm `SER`: the gate is an open load |
| bulk | `bulk` (measure_only, I) | HRSMU 4 | Icp: estimate `q f A Dit dE` for your device before choosing the range; guarded triax to the substrate or chuck |
| drain | `drain` (bias_v) | MPSMU 5 | reverse bias `v_r` |
| source | `source` (bias_v) | MPSMU 6 | reverse bias `v_r` |

- Example pin map `mosfet-cp` (simulator scenario `nmos_cv`). Routes per phase: `pulse: SEL1.OUT1 -> pgu`; `rest:
  SEL1.OUT1 -> open`; cleanup: every declared selector output to rest, verified.
- The SMUs are on before the first train (0 V on the bulk, `v_r` on drain and source) and stay on between trains.

## 3. Pre-run checklist

- Id-Vg on the same landing first (gate through `SEL1.OUT1 -> smu`): Vth known, gate not leaky.
- DUT profile with the gate `high_z` and a `pulse` envelope, the geometry (W, L) for `nit`.
- Base below Vfb and top above Vth with margin (from the Id-Vg and C-V of your device, or ask the owner); amplitude
  within the gate's pulse `max_abs_v`. The level defaults (section 4) are examples for the simulator's device.
- `station_status` clean; selectors at rest; no SPGU output running.

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `mode` | pg | pg | pg | fixed kind mode | PG trains with SMU readings |
| `v_base` | -2 V | - | -10..10 V | base levels (list; example: below your device's Vfb) | several = base-level sweep |
| `amplitude` | 4 V | - | 0.1..10 V | top = base + amplitude (example: set it per device) | must pass Vfb and Vth |
| `duty` | 0.5 | 0.3..0.5 | 0.05..0.5 | width / period | equal accumulation and inversion times |
| `t_edge` | 100 ns | 20 ns..1 us | 8 ns..10 us | rise and fall | sets the energy window dE (log) |
| `frequency` | 10 kHz, 20 kHz, 50 kHz, 100 kHz, 200 kHz, 500 kHz, 1 MHz | - | 10 Hz..5 MHz | pulse frequencies | Icp proportional to f |
| `duration` | 0.2 s | 0.1..1 s | 1 ms..30 s | output time per train | covers settle + reading |
| `settle` | 10 ms | - | 0..1 s | wait before the reading | - |
| `load_ohm` | 1 MOhm | - | 1 kOhm..1 MOhm | declared load SER | gate = open load |
| `v_r` | 0 V | 0..0.5 V | -2..2 V | drain/source reverse bias | n-channel: >= 0 |
| `icomp_bulk` | 1 uA | 10 nA..10 uA | 1 pA..1 mA | bulk compliance | above the largest Icp |
| `icomp_sd` | 100 uA | - | 1 nA..1 mA | drain/source compliance | - |
| `integration` | medium | medium, long | short, medium, long | ADC preset | long: lower noise, longer trains |
| `samples` | 1 | 1..4 | 1..100 | readings per train | longer trains |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: mosfet.charge_pumping
params: {}
pin_map: mosfet-cp
dut_profile: nmos-cv
sim_scenario: nmos_cv
```

## 5. Limits and confirmation

- The gate has no compliance: guard and R-SPGU-01 bound the open-load level (`|V| (SER + 50) / SER`), R-PULSE-02
  the DUT pulse envelope; a `high_z` gate with `load_ohm` < 1 kOhm is blocked. SMU compliances as set.
- The default plan applies about 376,000 pulses (7 frequencies x 0.2 s): `soft_pulse` (above 10,000 per run), plus
  `unverified_topology`/`unverified_pin_map` on the lab example. Fewer frequencies or shorter trains stay below.
- Each train must outlast its reading: `settle + 2 x samples x read time + 50 ms` (compile error otherwise).

## 6. Quality criteria

- Every reading during its train (`SPST?` 1 after the reading, else the run fails); bulk readings trusted (`N`).
- `qcp` classification `linear` (every Icp within 10 % of the line); offset `I0` small against Icp at 10 kHz.
- Icp at the lowest frequency at least 10x the bulk SMU's noise floor (else more `samples` or `integration: long`).

## 7. Analysis method

- Default `charge_pumping`: Icp per frequency (maximum over the base levels), `qcp` (C) = slope of Icp vs f with
  `r2`, `offset_a`, `max_deviation`, `icp_max` (A); plateau edges for a base sweep. Options: `area_um2` (W x L from
  the DUT geometry) -> `nit` (cm^-2); `delta_e_ev` -> `dit` (cm^-2 eV^-1): an assumption to state (about 0.7 eV
  for 100 ns edges if sigma = 1e-16 cm^2; the owner's sigma is unknown:
  [05](../../knowledge/05-reliability-defects.md#charge-pumping)).
- Report Icp as measured, `qcp`/`nit`/`dit` as derived (method, frequencies used, assumptions), SIMULATED flag.

## 8. Expected result shape

No checked typical values for your devices: compare with the human's expectation or earlier runs of the same device; only physics bounds and sign rules are fixed.

| item | expected (source) | red flags |
|---|---|---|
| Icp vs f | straight line through about 0 (`Icp = q f A Dit dE`, physics) | offset (leakage), bend at high f (incomplete pumping) |
| Icp vs base | plateau, falling on both sides | no plateau (amplitude too small), monotonic rise (leakage) |
| magnitude | compute `q f A Dit dE` for your device (physics; no typical Dit for your stack) | noise floor only (no pumping) |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| Icp at the noise floor | selector not on PGU, base/top not crossing Vfb/Vth | audit routes; Id-Vg Vth | `spgu-pulse-no-effect` |
| Icp too large, offset | gate leakage, forward-biased junction | `v_r` sign; gate leakage card | `spgu-load-mismatch` |
| noisy Icp at low f | HRSMU range/integration | `integration: long`, `samples` | `noisy-data` |
| plan blocked, selector not at rest | earlier run left it on PGU | `safe_shutdown` | `spgu-selector-state` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | nmos_cv | nmos-cv | S20261122T092630Z-d7b5 | needs_confirmation (unverified_pin_map, soft_pulse, unverified_topology); qcp 6.178e-14 C linear vs truth 6.183e-14 C (W/L 100/10 um, Dit 5e10, dE 0.77 eV), selectors open | - |
| hw | pending (bring-up stage L7) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware record: `validation/hw/mosfet.charge_pumping.yaml` (reviewed by a human after stage
L7; drafts only from hardware `H...` runs). Until then every hardware plan needs `first_hw_run` confirmation.
