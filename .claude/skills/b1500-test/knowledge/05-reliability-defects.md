---
domain: 05-reliability-defects
maturity: seed
sources:
  - deck slide 14 (domain 5 seed)
  - deck text PPT_slides_content.md (domain 5 page; BTI log-spaced read times, TDDB Weibull)
  - deck slide 17 (IGZO Vth drift case)
  - recipes/reserved (reliability.bti_sms, reliability.hci, reliability.tddb_cvs, wgfmu.fast_bti)
  - "D. K. Schroder, Semiconductor Material and Device Characterization, 3rd ed. (not page-checked)"
  - "JEDEC reliability test methods for BTI, HCI and TDDB (not consulted yet; TODO(verify))"
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Reliability and defect physics (knowledge domain 5)

Seeded from deck slide 14; the deck plans to extend it from EDTM tutorial and IRPS material. Stress tests change
or destroy the device, so in v1 every stress method is a reserved recipe (`not_implemented`, destructive, always
confirmed once implemented). What v1 can do is non-destructive: gate leakage inside a safe envelope, Id-Vg before
and after a human-run stress, and dual sweeps. Numbers marked `TODO(verify)` are literature typicals, not limits.

## Scope and v1 status

| Topic | v1 | Recipe |
|---|---|---|
| Gate leakage Ig(Vg), non-destructive | yes | `mosfet.gate_leakage` (card `gate-leakage`) |
| BTI stress-measure-stress | reserved | `reliability.bti_sms`, `wgfmu.fast_bti` |
| HCI | reserved | `reliability.hci` |
| TDDB constant-voltage stress | reserved | `reliability.tddb_cvs` |
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

Reserved. Seeded from deck slide 14 and the deck text.

- Bias temperature instability: gate stress (negative for PMOS NBTI, positive for NMOS PBTI) with drain and source
  grounded, usually at elevated temperature; Vth shifts by charge trapping and interface-state generation.
- Stress-measure-stress: interrupt the stress, measure a fast Id-Vg (or Id at one Vg) to get Vth, resume. Read
  times log-spaced, for example 1, 3, 10, 30, 100, 300, 1000 s (deck text).
- Delta Vth(t) usually follows a power law A t^n (n about 0.1-0.3) `TODO(verify)`. Recovery starts the moment the
  stress is removed, so slow SMU reads underestimate the shift: fast reads need the WGFMU (`wgfmu.fast_bti`).
- Needs asynchronous long runs, a stress-budget field in DUT profiles and a stress-measure kind (reserved
  preconditions).

## Hot-carrier injection HCI

Reserved. Seeded from deck slide 14.

- Stress with high gate and drain voltages at the same time; energetic carriers near the drain damage the
  interface and the oxide. Monitor Vth shift, gm (peak) degradation and Ioff or Idsat change at periodic reads.
- Worst-case stress bias depends on the technology (classically Vg about Vd/2 for long-channel NMOS, Vg about Vd for
  short channels) `TODO(verify)`. Damage is local to the drain end: forward and reverse (source/drain swapped)
  reads differ.

## TDDB constant-voltage stress

Reserved (`reliability.tddb_cvs`, SMU sampling mode 10). Seeded from deck slide 14 and the deck text.

- Constant-voltage stress on the gate while sampling the leakage current versus time; breakdown criterion: a sudden
  current jump or a current threshold (state it). Soft breakdown (noisy, partial) precedes hard breakdown in thin
  oxides.
- Statistics over many devices: Weibull plot ln(-ln(1 - F)) versus ln(t); shape factor beta and characteristic
  time t63 (63.2 % failed). Area scaling and voltage acceleration extrapolate to use conditions.
- Destructive by definition: one device per stress, explicit human confirmation, abort and cleanup on breakdown.

## Interface traps Dit

Seeded from deck slide 14 (high Dit stretches C-V curves and increases SS).

- Interface states exchange charge with the channel as the Fermi level moves: they stretch the C-V curve along
  the voltage axis, add a frequency-dependent conductance peak, and raise the subthreshold swing.
- From SS (rough, includes depletion capacitance): Dit about (Cox / q) (SS / (ln(10) kT/q) - 1) - Cd / q. Use only
  as a relative indicator between devices of the same stack.
- Proper methods (all reserved): high-low frequency C-V, conductance method, Terman (high-frequency) method, charge
  pumping.
- Physics of SS: [01](01-device-physics.md#mosfet-subthreshold-swing).

## Oxide traps SILC and charge trapping

Seeded from deck slide 14.

- Stress-induced leakage current (SILC): leakage at low field rises after a high-field stress because the stress
  created traps that assist tunnelling. It is a damage indicator for the gate-leakage card.
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
  shifts it negative (photo-ionised vacancies). The measurement sweep itself is a short bias stress.
- Deck triage for drifting Vth: control temperature and humidity, then reduce the sweep range, then shorten the
  measurement time. The full runbook is `vth-drift-igzo` in skill `b1500-debug`.

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
