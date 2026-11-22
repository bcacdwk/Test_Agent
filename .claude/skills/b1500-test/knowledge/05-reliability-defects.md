---
domain: 05-reliability-defects
maturity: seed
sources:
  - deck slide 14 (domain 5 seed)
  - deck text PPT_slides_content.md (domain 5 page; BTI log-spaced read times, TDDB Weibull)
  - deck slide 17 (IGZO Vth drift case)
  - recipes/reliability/tddb_cvs.yaml (WP7.4); recipes/reliability/{bti_sms,hci,silc}.yaml, recipes/igzo/bias_stress.yaml
    and src/b1500_test_agent/analysis/stress.py (WP7.6); recipes/reserved (wgfmu.fast_bti)
  - "Kaczer et al., IRPS 2008 (BTI power law and recovery); Takeda & Suzuki, IEEE EDL 4, 111, 1983 (HCI)"
  - "DiMaria & Cartier, J. Appl. Phys. 78, 3883, 1995 (SILC)"
  - "D. K. Schroder, Semiconductor Material and Device Characterization, 3rd ed. (not page-checked)"
  - "Groeseneken, Maes, Beltran, De Keersmaecker, IEEE TED 31, 42, 1984 (charge pumping); recipes/mosfet/charge_pumping.yaml, analysis/charge_pumping.py (WP9.3)"
  - "JEDEC reliability test methods for BTI, HCI and TDDB (not consulted yet; TODO(verify))"
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Reliability and defect physics (knowledge domain 5)

Seeded from deck slide 14; the deck plans to extend it from EDTM tutorial and IRPS material. Stress tests change
or destroy the device: every stress recipe is destructive and always confirmed (`destructive`), long ones also
`long_run` and asynchronous. The SMU stress recipes share the composite kind `stress_measure` (WP7.6): a reference
read, then stress holds timed by the instrument and reads at log-spaced (or listed) cumulative stress times, then
optional recovery reads. Numbers marked `TODO(verify)` are literature typicals, not limits.

## Scope and v1 status

| Topic | v1 | Recipe |
|---|---|---|
| Gate leakage Ig(Vg), non-destructive | yes | `mosfet.gate_leakage` (card `gate-leakage`) |
| BTI stress-measure-stress (SMU) | yes (WP7.6, destructive) | `reliability.bti_sms` (card `bti-stress-measure`) |
| Fast BTI (WGFMU, µs reads) | reserved | `wgfmu.fast_bti` (M10) |
| HCI | yes (WP7.6, destructive) | `reliability.hci` (card `hci-silc`) |
| SILC | yes (WP7.6, destructive) | `reliability.silc` (card `hci-silc`) |
| TDDB constant-voltage stress | yes (WP7.4, destructive) | `reliability.tddb_cvs` (card `tddb-bdv`) |
| IGZO bias stress dVth(t) (PBS/NBS) | yes (WP7.6, destructive) | `igzo.bias_stress` (card `igzo-bias-stress`) |
| IGZO bias-stress transient Id(t) | yes (WP7.4) | `mosfet.id_t_sampling` (card `smu-sampling`) |
| Dit by C-V or charge pumping | reserved | `moscap.cv`, `moscap.qscv` |

Never imitate a stress with a sweep recipe (for example a long or repeated high-voltage sweep): it bypasses the
destructive-test confirmation and produces data without a defined stress history.

## Gate leakage and TDDB-safe envelope

The gate-leakage card measures Ig(Vg) with drain and source grounded; it must not stress the oxide.

- Conduction mechanisms: direct tunnelling (very thin oxides, weak field dependence), Fowler-Nordheim tunnelling
  (high field, ln(J/E^2) linear in 1/E), trap-assisted tunnelling and Poole-Frenkel emission (high-k and defective
  films, temperature dependent), displacement current C dV/dt during the sweep.
- Oxide field estimate: Eox about (Vg - Vfb) / tox (upper bound; part of the voltage drops in the semiconductor).
  1 V across 10 nm is 1 MV/cm.
- Breakdown fields: thermal SiO2 about 10 MV/cm; high-k (HfO2) and ferroelectric HZO films a few MV/cm
  `TODO(verify)` per stack. Long-term safe operating fields are far lower than the ramp breakdown field.
- Safe-envelope principles (non-destructive), as `mosfet.gate_leakage` implements them (checked against the
  recipe in WP2.5; the recipe and the card fix the actual values):
  - gate voltage within the DUT profile `max_abs_v` of the gate (the authority), never extended by the agent;
    a plan above it needs confirmation (`dut_envelope`); default sweep 0 → 3 V in 31 points;
  - sweep from 0 V outwards, one polarity per run, so the high-field point is reached last and briefly (the
    recommended start, -1..0 V, allows only a small low-field excursion before 0 V);
  - low gate compliance (default 100 nA, recommended 1 nA to 1 uA, at most 100 uA) with automatic abort on
    compliance, so a breakdown is current-limited and the sweep stops at once;
  - drain held at 0 V by its SMU and measured (a gate-drain path shows there), source and bulk on the GNDU, so
    the gate current is the only path being driven;
  - the gate always on an HRSMU (the recipe requires `low_current`; an MPSMU's smallest native range is 1 nA),
    long integration (16 PLC) and a hold (0.5 s) and step delay (50 ms) against displacement current.
- Read the result as leakage at the operating bias versus the limit: `leakage_at(v, limit_a)`
  ([06](06-analysis-extraction.md#leakage-at-bias)); normalise by gate area (A/cm^2) only when the area is known.
- Signs of damage: an abrupt, irreversible current jump (hard breakdown), a noisy step-like increase (soft
  breakdown), or a higher low-voltage leakage after the sweep than before (stress-induced leakage current, SILC).
  Compare a low-voltage leakage point before and after when in doubt.
- Never re-run at a higher voltage or compliance on your own after a compliance hit or a jump: that is a new plan,
  and a suspected breakdown goes to the human (skill `b1500-debug`).
- Gate leakage also sets the floor of Id at low currents (it reaches the drain through the gate-drain overlap):
  check it before trusting Ioff or SS on leaky stacks.

## BTI stress-measure-stress

Implemented (`reliability.bti_sms`, kind `stress_measure`, card `bti-stress-measure`; WP7.6). Seeded from deck
slide 14 and the deck text.

- Bias temperature instability: gate stress (negative for PMOS NBTI, positive for NMOS PBTI) with drain and source
  grounded, usually at elevated temperature; Vth shifts by charge trapping and interface-state generation.
- Stress-measure-stress: a reference Id-Vg before the stress, then interrupt the stress for a short Id-Vg (or Id at
  one Vg) at log-spaced cumulative stress times (for example 3 per decade: 1, 2.15, 4.64, 10 ... s; deck text:
  1, 3, 10, 30 ... s), resume. The stress clock (`t_s`) excludes the reads.
- Delta Vth(t) usually follows a power law A t^n (n about 0.1-0.3) `TODO(verify)`. Recovery starts the moment the
  stress is removed: every read and its setup lets the device relax, so slow SMU reads underestimate the shift
  (fewer points, `short` integration and spot reads shorten the read; the µs reads need the WGFMU,
  `wgfmu.fast_bti`). Report the read duration with n.
- The kind holds the stress with instrument-timed sampling blocks (one gate/drain current sample each, 25 s per
  block at most): the gate leakage during the stress is recorded too, and a gate breakdown (compliance) stops the
  run.

## Hot-carrier injection HCI

Implemented (`reliability.hci`, kind `stress_measure`, card `hci-silc`; WP7.6). Seeded from deck slide 14.

- Stress with high gate and drain voltages at the same time; energetic carriers near the drain damage the
  interface and the oxide. Monitor Vth shift, gm (peak) degradation and Ioff or Idsat change at periodic reads.
- Worst-case stress bias depends on the technology (classically Vg about Vd/2 for long-channel NMOS, Vg about Vd for
  short channels) `TODO(verify)`. Damage is local to the drain end: forward and reverse (source/drain swapped)
  reads differ.
- The linear-region drain current degrades as a power law |dId/Id0| = b t^m (m about 0.3-0.6) `TODO(verify)`; keep
  the gate stress below the BTI onset when the HCI part alone is wanted (a BTI shift adds -gm dVth to dId). The
  drain current under stress is recorded at every hold block.

## TDDB constant-voltage stress

Implemented (`reliability.tddb_cvs`, kind `smu_sampling`, card `tddb-bdv`; WP7.4). Seeded from deck slide 14.

- Constant-voltage stress on the gate while sampling the leakage current versus time; breakdown criterion: the
  stress source reaching its compliance (`icomp`, the breakdown current limit; the sampling then aborts and the
  source returns to 0 V), a sudden current jump, or a current threshold (state it). Soft breakdown (noisy,
  partial) precedes hard breakdown in thin oxides; the leakage first rises slowly (SILC, trapping).
- Statistics over many devices: Weibull F = 1 - exp(-(t/eta)^beta), plot ln(-ln(1 - F)) versus ln(t); shape beta
  and characteristic life eta = t63 (63.2 % failed); survivors are right-censored. Field acceleration (E model
  t_bd ∝ exp(-gamma E)) and area scaling extrapolate to use conditions (not automated) `TODO(verify)`.
- Destructive by definition: one site per stress, explicit human confirmation (`destructive`), never re-stress a
  broken site.

## Interface traps Dit

Seeded from deck slide 14 (high Dit stretches C-V curves and increases SS).

- Interface states exchange charge with the channel as the Fermi level moves: they stretch the C-V curve along
  the voltage axis, add a frequency-dependent conductance peak, and raise the subthreshold swing.
- From SS (rough, includes depletion capacitance): Dit about (Cox / q) (SS / (ln(10) kT/q) - 1) - Cd / q. Use only
  as a relative indicator between devices of the same stack.
- Proper methods: charge pumping (below; `mosfet.charge_pumping`), high-low frequency C-V, conductance method,
  Terman (high-frequency) method (the C-V ones with the MFCMU recipes).
- Physics of SS: [01](01-device-physics.md#mosfet-subthreshold-swing).

## Charge pumping

Groeseneken et al., IEEE TED 31, 42 (1984); EasyEXPERT has it as "Charge Pumping2" (SMU + SPGU, EX p518 (9-12)).

- Gate pulses swing the surface from accumulation (base below Vfb) to inversion (top above Vth); every period the
  interface traps fill with minority carriers from source/drain and recombine with majority carriers from the bulk.
  The bulk SMU reads the DC recombination current `Icp = q f A D̄it ΔE` (n-channel: positive into the bulk; source and
  drain held at a reverse bias Vr carry `-Icp` together).
- `ΔE`: the traps that cannot re-emit during an edge, about `2 kT ln(1/(v_th n_i σ t_em))` with `t_em` = edge time x
  |Vth - Vfb| / amplitude; 0.6-0.8 eV for 100 ns edges (σ 1e-16 cm²). Slower edges shrink `ΔE` slowly (log).
- **Base-level sweep** (fixed amplitude, several `v_base`): `Icp` rises once the top passes Vth, plateaus, falls
  once the base no longer reaches Vfb; the plateau edges estimate Vth - amplitude and Vfb.
- **Frequency sweep** (plateau base): `Icp` proportional to f; the slope `Qcp = dIcp/df` (C per cycle) gives
  `Nit = Qcp/(q A)` and `D̄it = Nit/ΔE`. An offset or a bend at high f: leakage, incomplete pumping (pulse shorter
  than the capture time), or a geometric component of slow edges on long channels.
- Method `charge_pumping` (analysis): `Icp` per frequency = the maximum over the base levels; least-squares
  `Icp = Qcp f + I0`: results `qcp` (C, classification `linear` within 10 % or `nonlinear`), `icp_max` (A); `nit`
  (cm^-2) with option `area_um2` (W x L of the DUT profile geometry) and `dit` (cm^-2 eV^-1) with `delta_e_ev` too
  (a stated assumption). Untrusted readings refuse; C/T never enter.
- Pitfalls: a floating bulk or floating source and drain gives no Icp; forward-biased junctions (Vr wrong sign) add
  diode current; gate leakage of a thin oxide adds an offset; too many pulses on a fragile gate is a stress (soft
  band `soft_pulse`).

## Oxide traps SILC and charge trapping

Seeded from deck slide 14.

- Stress-induced leakage current (SILC): leakage at low field rises after a high-field stress because the stress
  created traps that assist tunnelling. It is a damage indicator for the gate-leakage card and the measurement of
  `reliability.silc` (card `hci-silc`; WP7.6): a high-field gate stress interrupted by low-field leakage reads at
  `v_sense`; the SILC ratio (Ig - Ig0)/Ig0 grows with the injected charge (q_inj, from the stress current) and
  usually sub-linearly in time (exponent 0.3-1) `TODO(verify)`; a sudden jump is soft or hard breakdown (TDDB).
- Charge trapping in the oxide or high-k bulk shifts Vth and causes Id-Vg hysteresis. For an n-channel device,
  electron trapping at positive gate voltage moves the reverse branch to higher Vth (opposite to ferroelectric
  switching, [04](04-ferroelectric-oxide.md#fefet-memory-window-by-dual-sweep)).
- Fast traps follow the sweep (hysteresis depends on sweep rate and dwell time); slow traps cause drift between
  runs. Report sweep settings with any hysteresis value.

## IGZO instability mechanisms

Seeded from deck slide 14 and the deck slide 17 case "IGZO TFT Vth differs every time".

- Oxygen vacancies are donors in IGZO; their density changes with temperature and atmosphere, shifting Vth.
- Back-channel adsorption: water and oxygen adsorb and desorb on the exposed back surface, changing its potential
  (deck: moisture sensitivity).
- Bias stress: positive gate bias stress shifts Vth positive (electron trapping); negative bias under illumination
  shifts it negative (photo-ionised vacancies). The measurement sweep itself is a short bias stress. The shift
  follows a stretched exponential dV(t) = dV_inf (1 - exp(-(t/tau)^beta)), beta about 0.3-0.7 (Libsch and
  Kanicki, APL 62, 1286, 1993) `TODO(verify)`; `mosfet.id_t_sampling` samples Id after a gate step and fits tau and
  beta of the relaxing current (linear region: the same tau and beta as Vth).
- Deck triage for drifting Vth: control temperature and humidity, then reduce the sweep range, then shorten the
  measurement time. The full runbook is `vth-drift-igzo` in skill `b1500-debug`.
- Bias-stress test (`igzo.bias_stress`, card `igzo-bias-stress`; WP7.6): PBS (positive gate stress) and NBS
  (negative), Id-Vg reads at log-spaced stress times, dVth(t) fitted with the stretched exponential (tau, beta,
  dV_inf); recovery reads show how much relaxes. NBS under light (NBIS) is the stronger instability; the station is
  dark unless the human says otherwise.

## Stress-measure analysis

Implemented (`analysis/stress.py`, WP7.6; the docstring there is the definition, this section repeats it):

- Reads: the rows with `phase` `read` grouped by `cycle`; cycle 0 is the reference read (`t_s` 0); a later read is a
  stress or a recovery read by the phase of its cycle's hold rows. `t_s` of a stress read = cumulative stress time;
  recovery time = `t_s` - the last stress read's `t_s`. Hold rows (`phase` `stress`/`recovery`) hold the monitor
  current at the end of each block.
- Per read: `vth` (staircase reads; `vth_method` `constant_current`, default 100 nA x `w_over_l`, or
  `linear_extrapolation`, both as in [06](06-analysis-extraction.md#vth-constant-current)); `id`/`ig` (a spot read's
  mean over its trusted samples, or a sweep's value at `at_v`). A read with untrusted points is refused (left out
  with a warning) unless `force`; a refused reference read refuses every result.
- Change dX = X(t) - X(0); `relative` divides by |X(0)|. Power law |dX| = b t^m: least squares of log|dX| on log t
  over the stress reads with the majority sign and |dX| >= `min_change` (at least 3 reads). Stretched exponential
  (IGZO): dX = dX_inf (1 - exp(-(t/tau)^beta)), the `sampling_summary` fit, at least 8 reads.
- Recovery: `recovery` = 1 - dX(last recovery read)/dX(last stress read); `recovery_rate` = minus the slope of
  dX/dX_end against log10(t_rec) (fraction per decade).
- `bti_power_law`: `n`, `a` (V, |dVth| at 1 s), `dvth` (signed, last stress read) [+ `recovery`, `recovery_rate`].
  `degradation_vs_time`: `quantity` `id` (relative, default; HCI), `vth` or `ig`; `delta` + `b`, `m` (power law) or
  `tau`, `beta`, `delta_inf` (stretched) [+ `recovery`]. `silc`: |Ig| at `v_sense`; `silc_ratio` (last stress read),
  `silc_exponent` (reads above max(`min_ratio` 2 %, 3 sqrt2 x the reference read's standard error)), `ig0`, `q_inj`
  (C, trapezoid integral of the stress monitor current over `t_s`).
- Report measured reads (counts, status letters, read duration) and derived values with method, Vth criterion and
  the reads used; a simulated run is SIMULATED.

## Ferroelectric wake-up imprint and fatigue

Seeded from deck slide 14 (fatigue, wake-up, imprint, breakdown, oxygen vacancies, charge injection).

- Wake-up: Pr (and the memory window) grows during the first cycles as defects (oxygen vacancies) redistribute
  and pinched loops open.
- Fatigue: Pr falls after many cycles (domain pinning by charged defects); the FeFET window closes. Endurance of
  HfO2 FeFETs is often limited by interfacial-layer breakdown and trapping before ferroelectric fatigue
  `TODO(verify)`.
- Imprint: after holding one state, the loop shifts along the voltage axis, so the opposite state becomes harder
  to write and its Vth drifts; retention measurements show it as asymmetric drift.
- In v1 only dual sweeps exist: a memory window that changes over repeated loops hints at wake-up or trapping; the
  quantitative cycling studies wait for the pulse recipes.
