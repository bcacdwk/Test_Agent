---
domain: 06-analysis-extraction
maturity: seed
sources:
  - "deck slides 6, 9 and 15: topics only (illustrative, not evidence: owner 2026-11-26)"
  - src/b1500_test_agent/analysis/mosfet.py, mosfet_family.py (gm, Vth methods, SS, gm_max, Ion/Ioff, output, DIBL)
  - src/b1500_test_agent/analysis/resistor.py, diode.py, leakage.py, fefet.py, plots.py (M2 methods, forward voltage)
  - src/b1500_test_agent/analysis/reliability.py (plot_timeseries)
  - src/b1500_test_agent/analysis/quality.py, dataset.py, registry.py (trust, noise, run table; M1)
  - docs/design/blueprint.md section 2.8 (M2 method names and options)
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Analysis and extraction (knowledge domain 6)

Definitions here are identical to the docstrings of the code in
`src/b1500_test_agent/analysis/` (`quality.py`, `dataset.py`, `mosfet.py`, `mosfet_family.py`, `resistor.py`,
`diode.py`, `leakage.py`, `fefet.py`, `plots.py`, `reliability.py`); the code wins on any difference and a change to
either must change both (synced in WP2.5, WP5.7). `list_recipes` and `analyze_run` say which methods apply to a run.
Time series (sampling, breakdown), pulsed and search runs (pulsed vs DC, plateau, Vth/BDV by search): [06b](06b-analysis-time-pulse.md).
Compact models (EKV and level-1 fits, model vs run, SPICE export): [07](07-compact-models.md). Every SMU method and
where it is defined: [06b](06b-analysis-time-pulse.md#smu-method-index).

## Run table and trust classes

- Each run folder has `data.csv` (up to 200,000 rows) or, for larger runs (WGFMU records), `data.npz` plus
  `preview.csv` (2,000 evenly spaced rows); `get_run` shows at most 200 rows of an npz run, `analyze_run` and
  `load_run` read the whole table. Columns: `step` (acquisition index), value columns `<role>_<qty>` with a
  `<role>_<qty>_status` letter when measured (a `V`/`I` column without status is the programmed source value) and
  `trust`. Quantities: `V` (V), `I` (A); MFCMU `Cp`, `Cs` (F), `G` (S), `Rs`, `Z` (Ohm), `D` (1), `theta` (rad).
  Optional context columns: `t_s` (s since the run's time origin), `cycle`, `segment` (`fwd`/`rev` of a double
  sweep), `phase` (`stress`, `read`, `program`, `erase`, `recovery`, `correction`), `event` (WGFMU measure event),
  `range`/`<role>_range` (range label), `freq_hz`, `ac_vrms`, `dc_v` (MFCMU conditions).
- Trust per value from the recipe's `quality` block: `N` ok; `C`, `T` limited; `V X F D G S U` and any unknown letter
  untrusted (letters: [02](02-b1500-instrument.md#data-status-codes)); a row takes its worst value's trust.
- Limited and untrusted rows never enter a derivative, a fit or an interpolation. An extraction is refused
  (`outcome` `refused`, no value) when the analysed segment (curve) holds any untrusted row or its trusted response
  is noise-dominated (range < 10x noise), unless `force=true`: then it uses the trusted rows and is flagged
  (`forced_on_untrusted`, warning). Never force silently; say why in the report.
- Data that do not allow the method (too few points, no crossing, no subthreshold region): `outcome` `failed`.
  `resistance` and `leakage_at` read a compliance stop as a result (short; leakage above the compliance) and a
  noise-dominated response as a measurement at the floor; rows after an automatic abort count as `aborted`.
- M2 methods round derived numbers to 7 significant digits, finer than the instrument resolves.
- `points_excluded` counts excluded rows by status letter, `missing` (empty cell) and `outside_window`.

## Quality gate and noise

`quality_report` / `assess_quality` (implemented):

- Status counts overall and per measured column, row trust fractions, verdict = worst row level (`ok`, `limited`,
  `untrusted`; no points = untrusted).
- Noise per measured column: sigma = 1.4826 median(|y[i+1] - 2 y[i] + y[i-1]|) / sqrt(6) over trusted points in
  acquisition order within each segment (needs at least 7 points). SNR = value range / sigma.
- SNR below 10 (`MIN_SNR`) = at the noise floor: normal for a leakage or bias current, a red flag for the response
  being analysed. Extractions refuse a noise-dominated response unless forced.
- Limited points inside a fit window above `max_limited_fraction_in_fit` (recipe default 0.05, a software default)
  give a warning; v1 checks the fit window, not the whole run.

## Transconductance gm

Implemented (`gm`, used inside the Vth methods):

- gm = dId/dVg per row: slope at each point of a local quadratic least-squares fit over `smooth` neighbouring
  trusted points (default 5; odd, 3-101; window shifted inward at the ends). `smooth=1` = central differences.
  Equivalent to Savitzky-Golay on a uniform grid, exact on a non-uniform one.
- Per segment on trusted rows only (other rows NaN; unit S); Vg strictly monotonic within a segment.
- Dense or noisy sweeps: raise `smooth` (and `fit_points` for Vth).

## Vth linear extrapolation

Implemented (`vth_linear_extrapolation`, M1; default of `mosfet.idvg`):

- Fit Id = a + b Vg by least squares through the window; Vg0 = -a/b (Vg-axis intercept); report
  Vth = Vg0 - Vd/2 when `subtract_half_vd` (default true), because linear-region Id is proportional to
  (Vg - Vth - Vd/2) Vd ([01](01-device-physics.md#mosfet-threshold-voltage-definitions)).
- Window `max_gm` (default): the `fit_points` (default 5) trusted points centred on the maximum of |gm| (the first
  of maxima equal within 1e-9 relative; clamped at the sweep ends), i.e. the tangent at maximum gm. Or an explicit
  `window: [lo, hi]` in volts (all trusted points inside).
- Vd: the `vd` option if given, else the run plan's parameter `vd` (`vd_param`); missing gives an error (pass `vd`
  or `subtract_half_vd: false`).
- `segment` `fwd` by default (`rev` for the reverse branch of a double sweep).
- Fails with fewer than max(`fit_points`, 3) trusted points, fewer than 2 in an explicit window, or a flat fitted line.
  Warnings: r2 < 0.99, |gm| maximum at a sweep end, Vth outside the swept range, too many limited points in the window.
- `fit` holds `slope`, `intercept`, `r2`, `x_intercept`, `vd`, and for `max_gm` also `gm_max`, `x_at_gm_max`.
- Deck slide 15's sketch uses `np.gradient` and a fixed 5-point slice; the code differs on purpose (local
  quadratic derivative, |gm| for PMOS, Vd/2 correction, trust exclusion).

## Vth constant current

Implemented (`vth_constant_current`, M2; option of `memory_window`; a common convention).

- Vth = the gate voltage at which |Id| first reaches the critical current I_crit = `i_crit_a` x `w_over_l`
  (`i_crit_a` alone without `w_over_l`; default 100 nA, an example criterion: set it per device and report it),
  walking the trusted points
  in the direction of increasing |Id| (rising Vg for n-type, falling Vg for p-type). log10|Id| is interpolated
  linearly in Vg between the two bracketing points. More than one crossing gives a warning.
- No crossing on the trusted curve: `failed`, no value. Report the criterion with the value.

## Vth at maximum gm

Implemented (`vth_max_gm`, M2): the maximum of the gm *change*, the second-derivative or transconductance-change
method, not the gate voltage of maximum gm.

- Vth = the gate voltage where gm rises fastest, the maximum of s·dgm/dVg (s = +1 when |Id| grows with Vg, -1
  otherwise; both derivatives with `smooth` points), refined by a parabola through the peak and its two
  neighbours, minus Vd/2 (`subtract_half_vd`, default true: in the linear region gm turns on between Vth and
  Vth + Vd). `fit` also reports the gate voltage of maximum gm.
- Vd as for linear extrapolation (`vd` option, else the plan's `vd`). Method-specific: never compare it with
  linear-extrapolation or constant-current values.

## Subthreshold swing

Implemented (`subthreshold_swing`, M2; mV/dec).

- SS = 1000 / |d log10|Id| / dVg| from a straight-line fit of log10|Id| against Vg over a sliding window, reported
  for the window with the smallest SS (the steepest part of the subthreshold region).
- Window: `fit_points` (default 5) consecutive trusted points, or, with `decades`, the shortest run of consecutive
  points whose |Id| spans at least `decades` decades. A window counts only when |Id| is non-zero and strictly
  monotonic in it, grows in the transfer direction and its fit has r2 ≥ `min_r2` (default 0.99); this rejects the
  noise floor, where log10|Id| scatters. No such window: `failed`.
- Physics and red flags: [01](01-device-physics.md#mosfet-subthreshold-swing).

## Maximum transconductance

Implemented (`gm_max`, M2; S).

- gm_max = gm at the trusted point of maximum |gm| (signed value, `gm` definition above, `smooth` points), with its
  gate voltage and drain current in `fit` (`x_at_gm_max`, `y_at_gm_max`). The same quantity as `fit.gm_max` of
  `vth_linear_extrapolation` with the same `smooth` and segment. A maximum at a sweep end gives a warning.

## On and off current

Implemented (`ion_ioff`, M2): results `ion`, `ioff` (A) and `on_off_ratio`.

- Ion = |Id| at `v_on`, Ioff = |Id| at `v_off`, each linearly interpolated between the bracketing trusted points;
  on/off ratio = Ion/Ioff. Defaults: `v_on` = the sweep end with the larger |Id|, `v_off` = the other end. Report
  both bias points and Vd.
- A current at the noise floor (log10|Id| rough around the point) is reported as an upper bound of 3 noise standard
  deviations (`bound: upper`); the ratio is then a lower bound ([01](01-device-physics.md#mosfet-on-off-current-ratio)).

## Output metrics Ron and gds

Implemented (`output_metrics`, M2; recipe `mosfet.idvd`): x `drain_V`, y `drain_I`, curves grouped by the step
column `step` (default the other varying source voltage, `gate_V`).

- Per curve: **Ron** = 1/gd at the lowest |Vd| (gd = dId/dVd, local quadratic fit over `smooth` points: the
  deep-linear-region on-resistance including series resistance); **gds** = slope of a straight-line fit of Id
  against Vd over the trusted points in the top `sat_window` (default 0.2) fraction of the |Vd| span (saturation
  output conductance); **Vd_sat** = the first |Vd|, walking away from Vd = 0, at which gd falls to `sat_ratio`
  (default 0.1) x gd(Vd_min), interpolated linearly (saturation onset).
- The results (`ron` Ohm, `gds` S, `vd_sat` V) are those of one curve: `curve` = its step level, default the
  strongest drive (largest |step|, in `fit.step_v`). Each result lists that quantity for every curve in `fit` under
  `<step>=<level>` (for example `gate_V=1.5`), and the other curves' refusals or failures as warnings.
- Physics: [01](01-device-physics.md#mosfet-output-characteristics).

## DIBL and body effect

Implemented (`dibl`, `body_effect`, M7; recipes `mosfet.idvg_family`, `mosfet.body_effect`): curves x `gate_V`, y
`drain_I` per level of the step column (default the other varying source voltage: `drain_V`, `bulk_V`), each with its
constant-current Vth ([above](#vth-constant-current)); a curve without one is left out with a warning (two needed).

- **DIBL** (mV/V) = s·(Vth(Vd_lo) - Vth(Vd_hi))/(|Vd_hi| - |Vd_lo|), lowest- vs highest-|Vd| curve (s = +1 n-type,
  -1 p-type; an end curve without Vth refuses or fails it), plus `vth_lin`, `vth_sat`; `fit`: every Vth and, from
  three curves, `slope_mv_per_v`. Keep Vd_lo ≥ 0.1 V ([01](01-device-physics.md#mosfet-threshold-voltage-definitions)).
- **Body effect** (V/V) = least-squares dVth/dVsb, Vsb = V_source - V_bulk (`source_v`, default 0 V), positive under
  reverse body bias, plus `vth_vsb0` at Vsb = 0; r2 < 0.99 warns that the square-root law bends.

## Resistance fit

Implemented (`resistance`, M2; recipe `basic.contact_resistor`).

- Straight-line least-squares fit I = G·V + I0 of the measured current against the forced voltage (defaults: the
  source voltage column that varies most and the measured current of the same role, e.g. `a_V`/`a_I`) over the
  trusted points: R = 1/G (`resistance`, Ohm), linearity r2 (`linearity_r2`), offset current I0 at 0 V
  (`offset_current`, A; `fit.v_offset` = -I0/G).
- `classification`, thresholds as options: `short` = the forced terminal reached its compliance (status C): R ≤
  |V|/|I| at the first compliance point, reported as that upper bound with nothing fitted, when the bound is at most
  `r_short_ohm` (default 100 Ohm); or a fitted R ≤ `r_short_ohm`. A compliance stop with a bound above `r_short_ohm`
  cannot be classified: `failed`. `open` = the current is noise-dominated (range < 10x noise): R ≥ ΔV / (10 x noise),
  reported as that lower bound; or a fitted R ≥ `r_open_ohm` (default 1 GOhm). Otherwise `in_range`.
- A non-positive fitted conductance with a clean signal: `failed` (not a resistor: check the wiring).
- Two-wire: R includes probes, cables and contacts ([03](03-probe-station-wiring.md#contact-checks)).

## Diode fit Is n and Rs

Implemented (`diode_fit`, M2; recipe `basic.diode_iv`): results `n` (1), `is` (A), `rs` (Ohm).

- On the forward branch (V > 0 and I > 0) the Shockley diode with series resistance satisfies
  V = n·U_T·ln(I/Is) + Rs·I (I ≫ Is; U_T = kT/q at `temperature_k`, default 300 K), linear in the unknowns
  (n·U_T, -n·U_T·ln Is, Rs). One linear least-squares fit of V against (ln I, 1, I) over the fit window gives n, Is
  and Rs, with r2 and the rms voltage residual in `fit`.
- Fit window: forward points with `i_min_a` ≤ I ≤ `i_max_a`. Default `i_min_a`: 100 x the larger of the reverse
  branch's noise estimate and the shunt leakage G·V at that forward voltage (G = median |I/V| of the reverse points
  below -0.1 V); 1 nA when the run has no reverse branch. Default `i_max_a`: the largest trusted forward current.
  The window needs at least 5 points spanning at least one decade of current; else `failed`.
- Compliance points (C/T) are excluded; the reverse branch, and with it any breakdown, never enters the fit.
- Physics: [01](01-device-physics.md#pn-diode-shockley-equation-and-ideality-factor).
- Current-forced runs (`basic.iv_force_i`): x = the measured anode voltage, y = the forced current (default columns).

## Forward voltage

Implemented (`forward_voltage`, M7; recipes `basic.iv_force_i`, `basic.diode_iv`): `vf` (V) where the forward current
reaches `i_a` (default parameter `i_param`, else 1 mA), log10 I interpolated between the bracketing trusted forward
points, else `failed`. Columns as for the diode fit; rows after a compliance stop are `aborted`.

## Leakage at bias

Implemented (`leakage_at`, M2; recipes `mosfet.gate_leakage`, `basic.diode_iv`).

- Leakage = |I(v)| of the measured current at the forced voltage v (defaults: the swept source voltage and the
  measured current of the same role, e.g. `gate_V`/`gate_I`), linearly interpolated between the bracketing trusted
  points, compared with `limit_a`: `classification` `pass` when |I(v)| ≤ limit, else `fail`. `v` and `limit_a`
  default to the plan parameters named `v_param` (default `v_op`) and `limit_param` (default `leak_limit_a`); the
  diode recipe passes `v_param: v_rev`. Without a limit no classification is made.
- Compliance stop: the current reached its compliance (C) between 0 V and v (inclusive): the leakage at v is at
  least the compliance current, reported as that lower bound and `fail` when the limit is at most that current (a
  limit above the compliance cannot be decided: `failed`). A compliance stop beyond v leaves the value at v exact.
- Noise floor: log10|I| rough around v means below the detection limit: the result is an upper bound of 3 noise
  standard deviations, `pass` when that bound is within the limit. A floor value is a measurement, not a refusal.
- Envelope and damage signs: [05](05-reliability-defects.md#gate-leakage-and-tddb-safe-envelope).

## Memory window

Implemented (`memory_window`, M2; recipe `fefet.dual_sweep_mw`).

- The threshold voltage of each branch of a double sweep is extracted with one transfer-curve method
  (`vth_method`: `vth_constant_current` (default; I_crit = `i_crit_a` x `w_over_l`), `vth_linear_extrapolation` or
  `vth_max_gm`) on segment `fwd` (the first branch, start → stop) and `rev` (stop → start); MW = Vth_fwd - Vth_rev.
- Positive for the counter-clockwise ferroelectric loop of a FeFET swept upwards first, n- or p-channel alike; a
  negative MW gets a warning (a downward-first sweep, or charge trapping dominating; the channel type does not flip
  the sign: [04](04-ferroelectric-oxide.md#fefet-memory-window-by-dual-sweep)). Method offsets (for example
  (n - 1)·Vd/2 of linear extrapolation, or I_crit below the threshold current) are the same on both branches and
  cancel in MW.
- Results: `memory_window`, `vth_fwd`, `vth_rev` (V), `ion_fwd`, `ioff_fwd`, `ion_rev`, `ioff_rev` (A; per-branch
  on/off ratio in the Ion result's `fit`, from `ion_ioff` with `v_on`/`v_off`). When a branch Vth is refused or
  fails, the call returns both branch results with their outcomes and a non-ok `memory_window`.
- Report Vth_fwd, Vth_rev, MW with sign, the method and criterion, and per-branch Ion/Ioff.

## Plots

Implemented (`plot_iv`, M2; never refuses, never extracts).

- One figure per scale (`linear`: I against V; `log`: |I| on a log axis; `both`, the default), one panel per
  measured current column (`y`, default all), x = the swept source voltage. A stepped run draws one curve per step
  level, a double sweep one line per segment. Trusted points are joined by lines, limited (C/T) points drawn as
  open circles and untrusted ones as crosses; invalid data (199.999E+99) and zero currents on a log axis are left out
  and counted in the figure's note.
- `analyze_run` stores the PNG files in the run folder (`plots/<name>-<n>.png`); agent scripts call `plot_iv` with
  `out_dir` (default `work/<run_id>/plots/`), because run folders are written only by the server. Rendering uses a
  non-interactive backend (no display needed).

Implemented (`plot_timeseries`, WP5.7; never refuses, never extracts).

- One figure per scale (`linear`, the default; `log`: absolute values on a log axis; `both`), one panel per value
  column (`y`, default all measured columns) against `x` = `t_s` (default when present), else `cycle`, else `step`
  (the figure then says the run has no time base); `log_time=true` puts time on a log axis (log-time stress and
  retention schedules). One curve per `phase` (else per `segment`, else per WGFMU `event`). Trust markers and
  left-out points as in `plot_iv` (on log axes also times <= 0). Curves longer than `max_points` (default 5,000) keep
  the min and max of each of `max_points/2` index buckets, so spikes and steps stay visible (noted on the figure).

## Reporting rules measured versus derived

Report the conditions, the point counts, the abnormal points with their status codes and the method used; keep
measured and derived apart.

- Measured: V and I read by the instrument, with units and status-letter counts. Derived: every result of an
  analysis method (`derived: true`) with method, window or criterion, points used and excluded, warnings.
- Name the method and window, in the form "Vth = <value> V (linear extrapolation at max gm, Vd/2 corrected,
  window <lo>-<hi> V, 5 points)".
- A `refused` or `failed` result is no value: report the reason, never a guess; forced results carry the flag and why.
- Backend `sim`: every value is SIMULATED; say so in the first line of the report.
- Ad-hoc analysis (skill part 9) is derived too: cite the script path in `work/<run_id>/` and the method.

## C-V extraction

C-V methods (`cv_cox`, `cv_flatband`, `cv_doping_profile`, `cv_vth`, `cv_hysteresis`, `impedance_convert`,
`plot_cv`; WP8.3) are defined in [08](08-capacitance-cv.md#oxide-capacitance-and-eot) (06 is at its size limit).
- Cox by accumulation extrapolation, Vfb by the flatband capacitance, doping from the 1/C^2 slope; split C-V plateau
  Cox W L and onset Vth. Corrections covering every frequency first (R-CORR-01).
