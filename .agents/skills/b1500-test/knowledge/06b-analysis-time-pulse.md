---
domain: 06b-analysis-time-pulse
maturity: seed
sources:
  - src/b1500_test_agent/analysis/reliability.py (sampling_summary, time_to_breakdown, weibull_fit; WP7.4)
  - src/b1500_test_agent/analysis/pulse.py (pulsed_vs_dc, pulse_plateau; WP7.3)
  - src/b1500_test_agent/analysis/registry.py (two-run methods, options.reference_run)
  - docs/design/blueprint.md sections 2.9 (analyze_run reference_run) and 2.10 (pulse.py)
last_reviewed: null
---

# Analysis of time series and pulsed runs (knowledge domain 6b)

Split from [06](06-analysis-extraction.md) when it reached 300 lines (WP7.3); trust classes, the quality gate and the
reporting rules there apply here too. Definitions here are identical to the docstrings of
`src/b1500_test_agent/analysis/reliability.py` and `pulse.py`; the code wins on any difference and a change to
either must change both.

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
