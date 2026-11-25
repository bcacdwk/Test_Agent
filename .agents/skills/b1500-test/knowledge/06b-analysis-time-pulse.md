---
domain: 06b-analysis-time-pulse
maturity: seed
sources:
  - src/b1500_test_agent/analysis/reliability.py (sampling_summary, time_to_breakdown, weibull_fit; WP7.4)
  - src/b1500_test_agent/analysis/pulse.py (pulsed_vs_dc, pulse_plateau; WP7.3; vth_search_value, breakdown_voltage; WP7.5)
  - src/b1500_test_agent/analysis/nvm.py (memory_window_pulse; WP9.4; switching_kinetics_fit, endurance_summary, retention_fit; WP9.5)
  - src/b1500_test_agent/analysis/nls.py (NLS fit core; WP9.5)
  - src/b1500_test_agent/analysis/pund.py (pund_polarization, plot_pund; WP10.6)
  - src/b1500_test_agent/analysis/registry.py (two-run methods, options.reference_run)
  - docs/design/blueprint.md sections 2.9 (analyze_run reference_run) and 2.10 (pulse.py)
last_reviewed: null
---

# Analysis of time series, pulsed and search runs (knowledge domain 6b)

Split from [06](06-analysis-extraction.md) when it reached 300 lines (WP7.3); trust classes, the quality gate and the
reporting rules there apply here too. Definitions here are identical to the docstrings of
`src/b1500_test_agent/analysis/reliability.py`, `pulse.py` and `nvm.py`; the code wins on any difference and a change
to either must change both. PUND: `pund.py` (section [PUND](#pund)).

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

Implemented (`pulsed_vs_dc`, WP7.3; kinds `smu_pulsed`, `wgfmu_waveform` since WP10.4): a two-run method.
`analyze_run(run_id=<pulsed run>, method="pulsed_vs_dc", options={"reference_run": "<DC run id>"})`; the reference is
a finished DC run of the same roles and bias (`mosfet.idvg` for `mosfet.idvg_pulsed`, `wgfmu.pulsed_iv` and
`wgfmu.fast_iv`, `mosfet.idvd` for `mosfet.idvd_pulsed`).

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

Implemented (`pulse_plateau`, WP7.3; SMU pulsed runs; WGFMU waveforms since WP10.4).

- Time-resolved runs (`t_s`): pulses are the runs of one `cycle` (and one `event` label within it; WGFMU pulse
  trains: the pattern repeat, WGFMU pulsed sweeps: one averaged point per pulse), else of one `event` label, else
  the rows more than `threshold` (0.05 V) from the first row's level, split at jumps above `threshold`; each plateau
  drops `edge` (0.2) of its samples at both ends and averages `y` over the rest (`fit`: `level_v`, `samples`,
  `std`, `plateau_s`; `window` = its `t_s` span).
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

## Switching kinetics

Implemented (`switching_kinetics_fit`, WP9.5; `fefet.switching_kinetics`, kind `pulse_read` schedule `grid`).

- Grid from the run's plan program (per point `cycle`, amplitude `level`, `width`, `row`; `grid_mode`); a point's
  value is the Vth (as above) of the read after its grid pulse; the reads after the resets give `vth_reset` (mean,
  spread: a large spread means incomplete resets).
- `reset` grids: NLS least squares over every usable point, `Vth = V0 + A(V) (1 - exp(-(w / tau(V))^beta))`,
  `tau(V) = tau0 exp((Va / |V|)^alpha)`; `V0` and one `A(V)` per amplitude are linear (projected out), `tau0`, `Va`,
  `beta` (and `alpha` with option `alpha: null`, else fixed at 2) by Levenberg-Marquardt from a per-amplitude grid
  start. Needs 2 amplitudes (3 with free `alpha`), 3 widths per amplitude and more points than parameters. Results
  `tau0` (s; `fit`: `va`, `alpha`, `beta`, `v0`, `rms`, `r2`, `tau0_rel_se`, `tau@<V>V`, `window@<V>V`), `beta`
  (`beta_se`), `va` (V, `va_se`), `alpha` (when fitted); window = the width span. An amplitude whose `tau(V)` lies
  outside the widths constrains the fit weakly (warning).
- `ispp` grids: per width row the cumulative dVth after each step from the row's start (its reset read, else the
  reference read): `v50` (V, amplitude at half the row's final |dVth|, mean over rows; per row in `fit`) and
  `ispp_slope` (V/V, the largest step); no NLS parameters.

## Endurance

Implemented (`endurance_summary`, WP9.5; `fefet.endurance`, schedule `cycles` with checkpoint reads; library helper
`endurance_curve` returns MW per checkpoint).

- Per checkpoint N (the `cycle` of its reads = cumulative program/erase cycles): MW(N) = Vth(erase read) -
  Vth(program read). `memory_window_initial` (first checkpoint), `memory_window_max` (`fit` `cycles_at_max`),
  `memory_window_final` (`fit` `vth_program`, `vth_erase`, `checkpoints`), `wake_up` = MW_max / MW_initial - 1,
  `fatigue` = 1 - MW_final / MW_max, `cycles_to_failure`: the first crossing below `mw_fail` (V) or `fail_fraction`
  x MW_max (default 0.5) after the maximum, log10 N interpolation; never reached: a lower bound at the last
  checkpoint.

## Retention

Implemented (`retention_fit`, WP9.5; `fefet.retention`, schedule `retention`).

- Per state the reads at `t_s` > 0 (time after the write; option `t_min`): Vth = a + b log10(t / 1 s) by least
  squares: `retention_slope_program`, `retention_slope_erase` (V/dec; `fit`: `vth_1s`, `r2`, `vth_target`).
- MW(t) of the read pairs with the same index (same `t_s`), fitted the same way: `memory_window_slope` (V/dec),
  `memory_window_at_target` (V at `target_time_s`, default 10 years; warning when more than two decades beyond the
  last read), `retention_time` (s: the fit reaches `mw_min` V or `fail_fraction` x the first MW, default 0.5; a
  window that does not decay: lower bound at the target). Extrapolations are derived values: say so in the report.

## PUND

Implemented (`pund_polarization`, `plot_pund`, WP10.6; `fecap.pund`, `fecap.endurance_pund`; physics in
[04](04-ferroelectric-oxide.md#fecap-p-v-and-pund)).

- Data: per read (a `cycle` group) the rows of events `P`, `U`, `N`, `D`: `t_s`, forcing voltage `v` (default the
  varying `_V` source column, the programmed top level) and current `i` (default the only measured `_I` column).
  Each sample is the current averaged over one interval dt, so charge Q(k) = s sum I dt; the sign s makes the U
  pulse's charge follow its voltage (either electrode may be measured).
- `pr` (uC/cm^2) = mean of (Q_P - Q_U) / 2A and -(Q_N - Q_D) / 2A, whole-pulse charges (`fit`: `pr_pos`, `pr_neg`,
  `q_switch_c`); `q_switch` (C) = 2 Pr A, needs no area. Area: `geometry.area_um2` (or option `area_um2`).
- `c_lin` (F): slope of Q against V of U and D on their rise between `c_window` (10 %, 50 %) of the peak |V|.
- `ps` (uC/cm^2): ((Qmax_P + Qmax_U) / 2 - C_lin V_peak) / A, and likewise for N/D: the polarization at the peak
  field, dielectric removed (Qmax: the largest charge, at the end of the rise or flat top).
- `vc` (V) = (Vc+ - Vc-) / 2 with Vc+ the voltage at the peak of s (I_P - I_U) and Vc- of s (I_N - I_D) (a parabola
  through five samples); `v_imprint` = (Vc+ + Vc-) / 2; `ec` (MV/cm) = vc / `geometry.tox_nm` (or option
  `thickness_nm`). A peak at a ramp end is flagged (step pulses, or an amplitude below Vc).
- Trust: every sample enters the integrals, so a read with an untrusted or limited sample (WGFMU `V`: saturated
  range) is refused unless `force`.
- Several reads (endurance): the values of the last read, plus `pr_initial`, `pr_max`, `wake_up` = pr_max /
  pr_initial - 1, `fatigue` = 1 - pr_final / pr_max, `cycles_to_failure` (Pr below `fail_fraction` x pr_max after the
  maximum, log10 N interpolation; never: a lower bound at the last read). Window: the forcing-voltage span.
- `plot_pund`: currents against time, polarization (incl. dielectric) against voltage per pulse, Pr against cycles.

## SMU method index

Every `analyze_run` method for SMU runs (family `smu`, plus the stress methods of family `reliability`) and where it
is defined; `list_recipes(recipe_id)` names a recipe's default analyses.

| method | runs | definition |
|---|---|---|
| `quality_report`, `plot_iv`, `plot_timeseries` | every run | [06](06-analysis-extraction.md#quality-gate-and-noise), [plots](06-analysis-extraction.md#plots) |
| `vth_linear_extrapolation`, `vth_constant_current`, `vth_max_gm`, `subthreshold_swing`, `gm_max`, `ion_ioff` | Id-Vg (`mosfet.idvg*`, pulsed) | [06](06-analysis-extraction.md#vth-linear-extrapolation) |
| `output_metrics` | Id-Vd (`mosfet.idvd*`) | [06](06-analysis-extraction.md#output-metrics-ron-and-gds) |
| `dibl`, `body_effect` | `mosfet.idvg_family`, `mosfet.body_effect` | [06](06-analysis-extraction.md#dibl-and-body-effect) |
| `resistance`, `kelvin_resistance` | contact, spot, four-wire | [06](06-analysis-extraction.md#resistance-fit), [03](03-probe-station-wiring.md#four-wire-resistance) |
| `diode_fit`, `forward_voltage`, `leakage_at` | diode, gate leakage | [06](06-analysis-extraction.md#diode-fit-is-n-and-rs) |
| `zero_floor` | `system.zero_check` | [02b](02b-smu-modes.md#zero-check-floor) |
| `pulsed_vs_dc`, `pulse_plateau` | SMU pulsed | [above](#pulsed-versus-dc) |
| `sampling_summary`, `time_to_breakdown` | sampling, TDDB | [above](#sampling-summary-and-relaxation-fit) |
| `vth_search_value`, `breakdown_voltage` | search, BDV | [above](#threshold-voltage-by-search) |
| `bti_power_law`, `degradation_vs_time`, `silc` | stress-measure | [05](05-reliability-defects.md#stress-measure-analysis) |
| `compact_model_fit`, `model_compare`, `export_spice_netlist` | Id-Vg, Id-Vd, families | [07](07-compact-models.md#fit) |
