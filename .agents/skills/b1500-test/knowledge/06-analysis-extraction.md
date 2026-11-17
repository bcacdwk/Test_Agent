---
domain: 06-analysis-extraction
maturity: seed
sources:
  - deck slide 6 (Vth by linear extrapolation, quality check)
  - deck slide 9 (status codes, report rules)
  - deck slide 15 (domain 6 seed; Vth three methods, SS, gm, gds, on/off, C-V extraction)
  - src/b1500_test_agent/analysis/mosfet.py (gm, vth_linear_extrapolation; M1)
  - src/b1500_test_agent/analysis/quality.py, dataset.py, registry.py (trust, noise, run table; M1)
  - docs/design/blueprint.md section 2.8 (M2 method names and options)
last_reviewed: null
---

# Analysis and extraction (knowledge domain 6)

Seeded from deck slide 15. Definitions here must be identical to the code in `src/b1500_test_agent/analysis/`;
the code wins on any difference. Sections for M1 methods restate the code. Sections for M2 methods follow the
plan and carry `TODO(verify): sync with analysis/<module>.py docstring after WP2.2`. `list_recipes` and
`analyze_run` say which methods are implemented; a declared method returns `not_implemented`.

## Run table and trust classes

- Each run folder has `data.csv`: `step` (acquisition index), optional `segment` (`fwd`/`rev` for double sweeps),
  value columns `<role>_<V|I>` with a `<role>_<V|I>_status` letter when measured (a value column without status is
  the programmed source value), and `trust`.
- Trust per value from the recipe's `quality` block: `N` ok; `C`, `T` limited; `V X F D G S U` and any unknown
  letter untrusted (letters: [02](02-b1500-instrument.md#data-status-codes)). A row's trust is the worst of its
  measured values.
- Limited and untrusted rows never enter a derivative or a fit. An extraction is refused (`outcome` `refused`, no
  value) when the analysed segment holds any untrusted row, unless `force=true`: then it uses the trusted rows and
  is flagged (`forced_on_untrusted`, warning). Never force silently; say why in the report.
- `points_excluded` counts excluded rows by status letter, `missing` (empty cell) and `outside_window`.

## Quality gate and noise

`quality_report` / `assess_quality` (implemented):

- Status counts overall and per measured column, row trust fractions, verdict = worst row level (`ok`, `limited`,
  `untrusted`; no points = untrusted).
- Noise per measured column: sigma = 1.4826 median(|y[i+1] - 2 y[i] + y[i-1]|) / sqrt(6) over trusted points in
  acquisition order within each segment (needs at least 7 points). SNR = value range / sigma.
- SNR below 10 (`MIN_SNR`) = at the noise floor: normal for a leakage or bias current, a red flag for the response
  being analysed. Extractions refuse a noise-dominated response unless forced.
- Limited points inside a fit window above `max_limited_fraction_in_fit` (recipe default 0.05) give a warning.
  Deck slide 9 suggests re-measuring when more than 10 % of all points are abnormal; v1 checks the fit window.

## Transconductance gm

Implemented (`gm`, used inside the Vth methods):

- gm = dId/dVg per row: slope at each point of a local quadratic least-squares fit over `smooth` neighbouring
  trusted points (default 5; odd, 3-101; window shifted inward at the ends). `smooth=1` = central differences.
  Equivalent to Savitzky-Golay on a uniform grid, exact on a non-uniform one.
- Computed per segment on trusted rows only; other rows are NaN. Unit S for A over V. Vg must be strictly
  monotonic within a segment.
- Dense or noisy sweeps: raise `smooth` (and `fit_points` for Vth).

## Vth linear extrapolation

Implemented (`vth_linear_extrapolation`, M1; default of `mosfet.idvg`; deck slide 6):

- Fit Id = a + b Vg by least squares through the window; Vg0 = -a/b (Vg-axis intercept); report
  Vth = Vg0 - Vd/2 when `subtract_half_vd` (default true), because linear-region Id is proportional to
  (Vg - Vth - Vd/2) Vd ([01](01-device-physics.md#mosfet-threshold-voltage-definitions)).
- Window `max_gm` (default): the `fit_points` (default 5) trusted points centred on the maximum of |gm| (clamped at
  the sweep ends), i.e. the tangent at maximum gm. Or an explicit `window: [lo, hi]` in volts (all trusted points
  inside).
- Vd: the `vd` option if given, else the run plan's parameter `vd` (`vd_param`); missing gives an error (pass `vd`
  or `subtract_half_vd: false`).
- `segment` `fwd` by default (`rev` for the reverse branch of a double sweep).
- Fails (no value) with fewer than max(`fit_points`, 3) trusted points, fewer than 2 points in an explicit window,
  or a flat fitted line. Warnings: r2 < 0.99, |gm| maximum at a sweep end, Vth outside the swept range, too many
  limited points in the window.
- `fit` holds `slope`, `intercept`, `r2`, `x_intercept`, `vd`, and for `max_gm` also `gm_max`, `x_at_gm_max`.
- Deck slide 15's sketch uses `np.gradient` and a fixed 5-point slice; the code differs on purpose (local
  quadratic derivative, |gm| for PMOS, Vd/2 correction, trust exclusion).

## Vth constant current

Planned (`vth_constant_current`, M2). `TODO(verify): sync with analysis/mosfet.py docstring after WP2.2`.

- Vth = Vg at which |Id| equals the criterion current: `i_crit_a`, multiplied by W/L when `w_over_l` is given (deck
  slide 15: W/L x 100 nA). Interpolation between the two trusted points that bracket the criterion (expected:
  linear in log10|Id|).
- No value when the trusted curve never crosses the criterion. Report the criterion with the value.

## Vth at maximum gm

Planned (`vth_max_gm`, M2). `TODO(verify): sync with analysis/mosfet.py docstring after WP2.2`.

- Vth = Vg at the maximum of |gm| (same `gm` definition as above). Simple but method-specific: it lies above the
  extrapolated Vth (deck slide 15); never compare it with linear-extrapolation values.

## Subthreshold swing

Planned (`subthreshold_swing`, M2). `TODO(verify): sync with analysis/mosfet.py docstring after WP2.2`.

- SS = dVg / d(log10 |Id|) in mV/dec; the plan reports the minimum over the subthreshold region, optionally as the
  average over `decades` decades of current around the steepest part.
- Only trusted points clearly above the noise floor count. Deck slide 15 fits a line to log10(Id) versus Vg below
  Vth (Id > 1 pA); report the window either way.
- Physics and red flags: [01](01-device-physics.md#mosfet-subthreshold-swing).

## Maximum transconductance

Planned (`gm_max`, M2). `TODO(verify): sync with analysis/mosfet.py docstring after WP2.2`.

- gm_max = maximum of |gm| over the trusted points of a segment, with the gate voltage where it occurs. Same value
  as `fit.gm_max` of `vth_linear_extrapolation` when the options match.

## On and off current

Planned (`ion_ioff`, M2). `TODO(verify): sync with analysis/mosfet.py docstring after WP2.2`.

- Ion = |Id| at Vg = `v_on`, Ioff = |Id| at Vg = `v_off` (trusted points; interpolated or nearest point), ratio
  Ion/Ioff. Report both bias points and Vd.
- An Ioff at the noise floor is an upper bound and the ratio a lower bound
  ([01](01-device-physics.md#mosfet-on-off-current-ratio)).

## Output metrics Ron and gds

Planned (`output_metrics`, M2; recipe `mosfet.idvd`). `TODO(verify): sync with analysis/mosfet.py docstring
after WP2.2`.

- Per gate step (rows grouped by the stepped gate voltage `gate_V`): Ron = dVd/dId from a linear fit at the
  smallest drain voltages, gds = dId/dVd near the highest drain voltages (saturation).
- Physics: [01](01-device-physics.md#mosfet-output-characteristics).

## Resistance fit

Planned (`resistance`, M2; recipe `basic.contact_resistor`). `TODO(verify): sync with analysis/resistor.py docstring
after WP2.2`.

- Linear least-squares fit of I versus V over trusted points: R = 1 / slope, offset (current at 0 V), linearity
  (r2 and residuals). Class `open`, `short` or `in_range` against the expected resistance; thresholds are defined
  in the code.
- Two-wire: R includes probes, cables and contacts ([03](03-probe-station-wiring.md#contact-checks)).

## Diode fit Is n and Rs

Planned (`diode_fit`, M2; recipe `basic.diode_iv`). `TODO(verify): sync with analysis/diode.py docstring after
WP2.2`.

- Forward branch: in the exponential region, fit log(I) versus V; n = 1 / (Vt x slope of ln I), Is = I at the
  line's V = 0 intercept; Vt = kT/q at the stated temperature (300 K unless given). Rs from the deviation at high
  current: V - n Vt ln(I/Is + 1) = I Rs.
- Report the fit windows; compliance-limited points (C) at the top of the forward sweep are excluded.
- Physics: [01](01-device-physics.md#pn-diode-shockley-equation-and-ideality-factor).

## Leakage at bias

Planned (`leakage_at`, M2; recipes `mosfet.gate_leakage`, `basic.diode_iv`). `TODO(verify): sync with
analysis/leakage.py docstring after WP2.2`.

- |I| at the bias `v` (trusted points; interpolated or nearest), compared with `limit_a`: pass when below.
- A value at the noise floor means "below the floor", not a measured leakage; report the floor.
- Envelope and damage signs: [05](05-reliability-defects.md#gate-leakage-and-tddb-safe-envelope).

## Memory window

Planned (`memory_window`, M2; recipe `fefet.dual_sweep_mw`). `TODO(verify): sync with analysis/fefet.py docstring
after WP2.2` (the M1 registry stub still describes rev - fwd; WP2.2 fixes the sign).

- MW = Vth_fwd - Vth_rev: Vth extracted on the `fwd` and `rev` segments with the same `vth_method` and options
  (constant current is the usual choice for FeFETs `TODO(verify)` default). Positive for ferroelectric switching
  in an n-channel FeFET, negative when charge trapping dominates
  ([04](04-ferroelectric-oxide.md#fefet-memory-window-by-dual-sweep)).
- Report Vth_fwd, Vth_rev, MW with sign, the method, and per-branch Ion/Ioff when asked.

## Plots

Planned (`plot_iv`, M2). `TODO(verify): sync with analysis/plots.py docstring after WP2.2`.

- PNG plots of the run table, `scale` linear or log (deck slide 15: linear and log axes), written by the server
  next to the run's analysis results; returns the file paths. Rendering uses a non-interactive backend.

## Reporting rules measured versus derived

Seeded from deck slide 9 (report conditions, point counts, abnormal points with their status codes, the method
used; separate measured from derived).

- Measured: V and I read by the instrument, with units and status-letter counts. Derived: every result of an
  analysis method (`derived: true`) with method, window or criterion, points used and excluded, warnings.
- Name the method and window, for example "Vth = 0.43 V (linear extrapolation at max gm, Vd/2 corrected,
  window 0.55-0.63 V, 5 points)"; deck slide 9 example: "Vth by linear extrapolation, fit Vgs 0.5-1.5 V".
- A `refused` or `failed` result is no value: report the reason, never a guess. Forced results carry the flag and
  the reason they were forced.
- Backend `sim`: every value is SIMULATED; say so in the first line of the report.
- Ad-hoc analysis (skill part 9) is derived too: cite the script path in `work/<run_id>/` and the method.

## C-V extraction reserved

Seeded from deck slide 15; no C-V kind or method exists in v1.

- Cox: accumulation capacitance (maximum of the C-V curve, after correction). Vfb: flat-band capacitance method
  or, as the deck lists, from a 1/C^2 versus V fit (Mott-Schottky; gives doping and built-in or flat-band voltage)
  `TODO(verify)` which convention. Dit: multi-frequency (high-low) or Terman method.
- Requires CMU open/short/load correction covering the frequency, SCUU paths and a leakage check first.
