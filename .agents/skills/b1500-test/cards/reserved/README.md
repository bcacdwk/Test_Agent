# Reserved measurement slots

These measurements are planned but **not implemented** in v1. Each one is registered as a recipe with status
`not_implemented` in `recipes/reserved/` (the registry source), so `list_recipes` shows it and `validate_plan`
blocks it (R-REC-01) with zero instrument I/O. There is no card for them yet.

When a request needs one of them:

- Say plainly that it is reserved (`not_implemented`) in v1 and name the recipe id.
- Offer the validated alternative from the table below, if one fits, through its card.
- Never emulate a reserved measurement with another recipe (`generic.smu_staircase`, repeated or long sweeps,
  higher voltages), never write FLEX or PyVISA code, never edit recipes to change a status.

## Slots

| recipe | measurement | validated alternative today |
|---|---|---|
| `wgfmu.pulsed_iv` | WGFMU fast pulsed I-V (Id-Vg/Id-Vd with short pulses) | DC staircase: [mosfet-idvg](../smu/mosfet-idvg.md), [mosfet-idvd](../smu/mosfet-idvd.md) |
| `wgfmu.fast_bti` | WGFMU fast BTI with on-the-fly Vth monitoring (destructive) | SMU stress-measure-stress (slower reads): [bti-stress-measure](../reliability/bti-stress-measure.md) |
| `spgu.program_smu_read` | SPGU/HV-SPGU program pulse, then SMU read via the 16440A selector | none |
| `fefet.pulse_write_read` | FeFET pulse write/read, endurance, retention (destructive) | [fefet-dual-sweep-mw](../nvm/fefet-dual-sweep-mw.md) |
| `fecap.pund` | Ferroelectric capacitor PUND (Pr, Ec) | none (FeFET: [fefet-dual-sweep-mw](../nvm/fefet-dual-sweep-mw.md)) |
| `cmu.correction` | MFCMU phase compensation and open/short/load correction | none |
| `moscap.cv` | MOS capacitor C-V with the MFCMU | none |
| `moscap.qscv` | Quasi-static C-V with SMUs | none |
| `mosfet.cgd_cv` | MOSFET gate-drain capacitance C-V with the MFCMU | none |
| `hspice.compare` | Compare a measured run with an HSPICE simulation | ad-hoc analysis of archived runs (skill part 9) |

## Preconditions to un-reserve

From each recipe's `preconditions` list (the recipe file is authoritative). Common to all: a human-reviewed status
change, a card from [the template](../_TEMPLATE.md), a passing `b1500 dev lint-skills` and the M3 suite re-run;
`sim_validated` only after a simulator test against model truth, `hw_validated` only with an M4 validation record.

- `wgfmu.pulsed_iv`: WGFMU instrument-library (B1530A) commands extracted from the manual into
  `references/manuals/structured/`; RSU wiring and WGFMU channels in the station profile and pin maps;
  pulse-envelope rules (amplitude, width, duty cycle) with tests; a simulator model of the pulsed response and a
  safety-matrix row for the new kind; sim validation, then an M4 hardware validation record.
- `wgfmu.fast_bti`: `wgfmu.pulsed_iv` validated first; asynchronous runs (`outcome: running`, `get_run` progress) for stresses
  longer than `policy.run_limits.max_sync_run_s`; stress-envelope rules and a DUT-profile stress budget; knowledge
  05 reviewed by a human; sim and hardware validation.
- `spgu.program_smu_read`: 16440A selector and SPGU commands extracted from the manuals; selector topology recorded
  and verified in the station profile; a switching driver path whose cleanup leaves the selector on the SMU side;
  pulse-envelope rules; sim model; sim and hardware validation.
- `fefet.pulse_write_read`: a validated pulse source kind (WGFMU or SPGU); the simulator's FeFET polarization model
  extended to pulse programming; `memory_window` and `vth_shift` analysis plus `endurance_trend`; write-pulse
  envelope reviewed against film thickness and coercive field (DUT profile); sim and hardware validation.
- `fecap.pund`: WGFMU pulse sequences with fast current sampling; PUND charge-integration analysis (Pr, Ec)
  documented in knowledge 04; capacitor DUT profiles with field limits; sim model; sim and hardware validation.
- `cmu.correction`: MFCMU correction commands extracted from the manual; SCUU path and correction records in the
  station profile (rule R-CORR-01); a human-guided open/short/load procedure with fixtures and its validation.
- `moscap.cv`: `cmu.correction` implemented with corrections covering the frequencies (R-CORR-01); SCUU switching
  and leakage-validation flows; the reserved C-V extraction in knowledge 06 written and reviewed; sim and hardware
  validation.
- `moscap.qscv`: QSCV commands extracted from the manual and a leakage-compensation flow; low-current pin maps on
  HRSMU (with ASU when available); sim and hardware validation.
- `mosfet.cgd_cv`: a leakage check passed on the same landing; open/short correction current for 1 MHz
  (`cmu.correction`, R-CORR-01); pin map verified, SCUU/Guard topology recorded; sim and hardware validation.
- `hspice.compare`: the knowledge 07 workflow reviewed; a netlist/model input format and a non-instrument kind (no
  transaction) with its own tests.
