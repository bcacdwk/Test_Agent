---
domain: 06b-analysis-time-pulse
maturity: seed
sources:
  - src/b1500_test_agent/analysis/reliability.py (sampling_summary, time_to_breakdown, weibull_fit; WP7.4)
  - src/b1500_test_agent/analysis/pulse.py (pulsed_vs_dc, pulse_plateau; WP7.3; vth_search_value, breakdown_voltage; WP7.5)
  - src/b1500_test_agent/analysis/nvm.py (memory_window_pulse; WP9.4)
  - src/b1500_test_agent/analysis/registry.py (two-run methods, options.reference_run)
  - docs/design/blueprint.md sections 2.9 (analyze_run reference_run) and 2.10 (pulse.py)
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Analysis of time series, pulsed and search runs (knowledge domain 6b)

Split from [06](06-analysis-extraction.md) when it reached 300 lines (WP7.3); trust classes, the quality gate and the
reporting rules there apply here too. Definitions here are identical to the docstrings of
`src/b1500_test_agent/analysis/reliability.py`, `pulse.py` and `nvm.py`; the code wins on any difference and a change
to either must change both.

## Sampling summary and relaxation fit

Implemented (`sampling_summary`, WP7.4; kind `smu_sampling`). Over the trusted points of one column `y` (default the
only measured current) against `t_s` (seconds since the bias step), inside `t_min`..`t_max`:

- `initial`, `final` = medians of the first and last `edge` (10) points; `mean`, `std`; `drift` = (final - initial)
  / |initial|.
- `fit: stretched_exp`: y(t) = y_inf + (y0 - y_inf) exp(-(t/tau)^beta), linear least squares for y_inf, y0 at each
  (tau, beta), a log grid then Levenberg-Marquardt: `tau` (s), `beta`, `y_inf`; fit `r2`, standard errors. A tau
  beyond 3x the last time or beta at 0.1/1.5 is flagged (poorly constrained). Untrusted points refuse.

## Time to breakdown and Weibull

Implemented (`time_to_breakdown`, WP7.4; recipe `reliability.tddb_cvs`) and the library helper `weibull_fit`.

- t_bd = `t_s` of the first sample of `y` in compliance (`C`), or jumping `jump_factor` (10) above the median of
  the previous `window` (5) samples, or reaching `i_bd_a`; resolution one interval (`fit.t_prev_s`). No breakdown:
  the last time as a lower bound, `classification: no_breakdown` (censored). Breakdown at the first sample is flagged.
- `weibull_fit(runs)` (agent scripts; not an `analyze_run` method): t_bd per run, then the two-parameter Weibull by
  maximum likelihood with right censoring (`weibull_beta`, `weibull_eta` = 63 % life; fit `n`, `failures`,
  `censored`, `beta_se`), or `method: rank` (median ranks, complete data). At least two breakdowns.

## Pulsed versus DC

Implemented (`pulsed_vs_dc`, WP7.3; kind `smu_pulsed`): a two-run method. `analyze_run(run_id=<pulsed run>,
method="pulsed_vs_dc", options={"reference_run": "<DC run id>"})`; the reference is a finished DC run of the same
roles and bias (`mosfet.idvg` for `mosfet.idvg_pulsed`, `mosfet.idvd` for `mosfet.idvd_pulsed`).

- `x` defaults to the swept voltage, `y` to the measured current (of another role when several: Id of a gate
  sweep); constant source columns of both runs (e.g.
  `drain_V`) must agree within 1 mV + 0.1 %, else `failed`. A family (Id-Vd) compares one curve: `curve` (step
  level; default the largest |level| both runs have).
- Over the common x window the DC run is interpolated at the pulsed x: `pulsed_minus_dc` and `pulsed_over_dc` at
  `v` (default the x of the largest pulsed current: the highest power), `max_rel_difference` = the largest
  |Delta|/|I_dc| where |I_dc| >= `min_current_a` (default 1 % of its maximum).
- Reading: pulsed > DC on an n-type transistor, growing with Id x Vd, is DC self-heating (mobility loss); a
  difference at negligible power is charge trapping (slow traps fill during DC) or a mismatch of the runs (rerun DC).

## Pulse plateau

Implemented (`pulse_plateau`, WP7.3; SMU pulsed runs, WGFMU waveforms later).

- Time-resolved runs (`t_s`, several rows per pulse): pulses are the runs of one `event` label, else the rows more
  than `threshold` (0.05 V) from the first row's level, split at jumps above `threshold`; each plateau drops `edge`
  (0.2) of its samples at both ends and averages `y` over the rest (`fit`: `level_v`, `samples`, `std`,
  `plateau_s`; `window` = its `t_s` span).
- One row per pulse (SMU pulsed spot/sweep): each row already is the pulse-end reading over the ADC time.
- Result `plateau_current` (or `plateau_voltage`) at level `v` (interpolated), pulse number `pulse`, or by default
  the pulse with the largest |level|.

## Threshold voltage by search

Implemented (`vth_search_value`, WP7.5; recipe `mosfet.vth_search`, kind `smu_search`, MM 15 binary search).

- The instrument bisects the gate until the drain current is within `limit_rel` (1 %) of I_crit x W/L and returns the
  gate voltage there (`gate_V`, status `N`) and the drain current it read: Vth = that voltage (`fit`:
  `i_measured_a`, `target`, `rel_error`). It is the constant-current Vth ([06](06-analysis-extraction.md#vth-constant-current))
  at the same criterion and drain bias, without interpolation; 1 % of the current is ~0.4 mV at 80 mV/dec.
- Status `G` (target not between start and stop): `failed`, widen the range; `S` (automatic abort: gate or drain
  compliance) or an untrusted drain reading: refused unless `force`.

## Breakdown voltage

Implemented (`breakdown_voltage`, WP7.5; recipes `basic.breakdown_search`, `dielectric.bdv`), read by the search kind:

- Linear search (MM 14 ramp): BDV = the source voltage of the first step whose current reached the criterion
  (status `N`), within one step (`window` previous step .. BDV, `fit.step_v`); `S` with the monitor in compliance is
  the breakdown step stopped by the compliance (same value, warning).
- Quasi-pulsed (MM 9): BDV = the measured voltage where the source hit its compliance (status `C`). `S` (compliance
  before a 10 V change from start) or `G` (detection timeout) refuse: use the linear ramp, the long interval.
- No breakdown up to stop (linear `G`, quasi-pulsed `N`): the stop value as a `lower` bound, `classification:
  no_breakdown` (censored). The value is signed as forced (a reverse junction breakdown is negative;
  `fit.magnitude_v`). Report the criterion (`target`, `icomp`), the step, the status counts and that the site is
  destroyed.

## Program read memory window

Implemented (`memory_window_pulse`, WP9.4; kind `pulse_read`: `fefet.pulse_write_read`, `spgu.program_smu_read`).

- Reads: one group of rows per `cycle` and `phase`; `read` (cycle 0) is the reference read before any pulse,
  `program` / `erase` rows are the read after that operation in that cycle (programmed / erased state).
- Per read (`quantity`, default `auto`): `vth` of a staircase read (`x` default `gate_V`, else the only swept source
  column, e.g. `gate_read_V`; `y` default `drain_I`) by `vth_method` `constant_current` (default; `i_crit_a` x
  `w_over_l`, 100 nA) or `linear_extrapolation`; `current` = the mean of a spot read's trusted samples, or a sweep's
  `y` at `x = at_v` (default the plan parameter `vg_read`). Untrusted points refuse that read unless `force`
  (flagged); `C`/`T` points never enter; a refused or failed read drops out with a warning.
- `memory_window` (V) = mean Vth(erase) - mean Vth(program) (positive for an n-channel FeFET; negative is flagged:
  polarity or naming); `fit`: per-cycle `mw_min`, `mw_max`, `mw_std`, `cycles`, `vth_initial`. Per state
  `vth_program`, `vth_erase`, `vth_initial` (mean; `fit` `first`, `last`, `std`, `reads`). A program-only sequence
  has no window: its state's mean, first and last read show the cumulative shift.
- Spot reads: `i_program`, `i_erase`, `i_initial` (A) and `current_ratio` = |I(program)| / |I(erase)| (1).
