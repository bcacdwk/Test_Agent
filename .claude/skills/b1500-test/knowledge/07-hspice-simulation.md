---
domain: 07-hspice-simulation
maturity: seed
sources:
  - deck slide 16 (domain 7 seed; workflow, level-1 first, BSIM4 later)
  - deck slide 7 (plan to combine HSPICE with Verilog-A models)
  - deck text PPT_slides_content.md (domain 7 page; example netlist generator)
  - recipes/reserved/hspice.compare.yaml (reserved slot and preconditions)
  - "former references/hspice/README.md (v0.2 notes, folded here)"
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# HSPICE simulation (knowledge domain 7)

Seeded from deck slide 16. Reserved: there is no simulation tool, kind or analysis method in v1, and the recipe
`hspice.compare` is `not_implemented`. This file records the intended workflow so later work starts from it. If a
user asks for a simulation comparison now, say it is reserved, offer the measured and derived values, and do not
improvise a simulator call.

## Status and boundaries

- Simulation is optional and stays outside the instrument path: it never runs inside a measurement transaction,
  never needs the instrument lock, and nothing about it can change safety rules, limits or plans.
- Open points from the deck: HSPICE invocation interface and licence availability on the lab PC; which model
  levels to support first.
- Preconditions to un-reserve (from the reserved recipe): this workflow reviewed by a human, a netlist/model input
  format, and a non-instrument kind with its own tests.

## Planned workflow

From deck slide 16 and the former v0.2 notes:

1. Extract device parameters from a measured run (Vth, mobility, Cox, lambda) with the analysis methods of
   [06](06-analysis-extraction.md); keep the run id and method records.
2. Fill a model card (level 1 first, BSIM4 or Verilog-A later).
3. Generate a netlist that reproduces the measured bias conditions (same sweep, same fixed biases).
4. Run HSPICE (or a compatible simulator) outside the measurement service.
5. Parse the simulated curves.
6. Compare with the measured curve and report the error; feed systematic mismatch back into measurement planning
   (for example missing points near Vth, or a sweep that never reaches saturation).

## Level-1 model card from measured parameters

| Model parameter | From | Note |
|---|---|---|
| `VTO` (V) | Vth by linear extrapolation | same Vd correction as the measurement |
| `KP` (A/V^2) | mu Cox: from gm_max = KP (W/L) Vd in the linear region | mu in cm^2/Vs times Cox in F/cm^2 is already A/V^2 |
| `LAMBDA` (1/V) | gds / Id in saturation (output metrics) | needs an Id-Vd run |
| `TOX` | DUT profile or the human | unit convention of the chosen level `TODO(verify)` |
| `W`, `L` | DUT profile or the human | never guessed |

- Level 1 is a square-law model with no subthreshold conduction: compare only above threshold. Subthreshold
  slope, DIBL, mobility degradation and series resistance need BSIM4 (or a Verilog-A model).
- Oxide TFTs and FeFETs are poorly described by level 1; the deck plans Verilog-A models for them (deck slide 7).

## Example netlist

From the deck text (generator sketch for an NMOS Id-Vg at Vd = 50 mV over the default `mosfet.idvg` gate range):

```text
* MOSFET Id-Vgs simulation
.model nmos1 nmos level=1
+ vto=<Vth> kp=<KP in A/V^2> tox=<tox>
M1 drain gate 0 0 nmos1 W=<W> L=<L>
Vgs gate 0 DC 0
Vds drain 0 DC 0.05
.dc Vgs -1 3 0.01
.print DC I(Vds)
.end
```

- The deck's generator computes `kp` as `mu * cox * 1e4`; check the units of mu and Cox before reusing it
  `TODO(verify)`.
- `I(Vds)` is the current into the positive node of the source, i.e. minus the drain current in the SMU sign
  convention: flip the sign before comparing.
- Use the measured sweep's start, stop and step (or interpolate the simulation onto the measured points).

## Comparing measured and simulated curves

- Compare only trusted measured points (no limited or untrusted rows,
  [06](06-analysis-extraction.md#run-table-and-trust-classes)).
- Above threshold: relative error of Id; subthreshold: error of log10|Id| (a relative error there is dominated by
  the smallest currents). Report RMS and maximum error and where the maximum occurs.
- Also compare derived values extracted from both curves with the same method and options (Vth, gm_max, SS); a
  difference in derived values is easier to interpret than a pointwise error.
- The comparison is a derived result: record model card, simulator version, netlist and run id; ad-hoc work goes
  in `work/<run_id>/` with the script path cited.

## BSIM4 and Verilog-A later

- BSIM4 brings subthreshold, short-channel and mobility models but needs many parameters; fit them only with a
  dedicated extraction flow, not by hand from one curve.
- Verilog-A device models (FeFET polarization, oxide TFT) can be run in HSPICE alongside the extracted parameters;
  the deck plans experiment-simulation co-tuning with such models (deck slides 7 and 16).
