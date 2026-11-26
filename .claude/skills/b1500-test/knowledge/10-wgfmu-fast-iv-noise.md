---
domain: 10-wgfmu-fast-iv-noise
maturity: seed
sources:
  - "WGFMU Instrument Library and Sample Software User's Guide Ed. 8 (WG), PDF pages cited inline"
  - "Keysight application note 5990-3705 (RTN of advanced MOSFETs with the B1500A WGFMU; AN-RTN), pages cited inline"
  - lwp/1530/LFN_noise_meas.cpp and meas_pt.csv (the lab's LFN layout; read-only evidence)
  - src/b1500_test_agent/catalog/waveforms.py (builders; dc_sample WP10.5), catalog/kinds/wgfmu_waveform.py
  - src/b1500_test_agent/analysis/noise.py, analysis/spectrum.py (it_statistics, psd_welch, rtn_levels, plot_psd)
  - docs/design/blueprint.md v2 sections 2.7.1, 2.10, 3.4, 4.2 (noise targets), 4.4 (nmos_rtn)
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# WGFMU fast I-V and noise (knowledge domain 10)

What the B1530A WGFMU measures fast, how a constant-bias record becomes random telegraph noise (RTN) and
low-frequency noise (LFN) numbers, and how to choose range, sampling and record length. Cards: `wgfmu-rtn-noise`
(recipes `wgfmu.rtn`, `wgfmu.lfn`), `wgfmu-pulsed-iv`, `wgfmu-custom-waveform`; PUND and fast program/read:
`fecap-pund`, `fefet-pulse-write-read`. Definitions of the analysis methods
here are identical to the docstrings of `src/b1500_test_agent/analysis/noise.py` (fit numerics in `spectrum.py`);
the code wins on any difference and a change to either must change both.

## Contents

- [WGFMU and RSU in one page](#wgfmu-and-rsu-in-one-page)
- [Fast I-V pulses ramps and timing](#fast-i-v-pulses-ramps-and-timing)
- [Constant-bias sampling dc_sample](#constant-bias-sampling-dc_sample)
- [PUND program read and the pulse_read WGFMU path](#pund-program-read-and-the-pulse_read-wgfmu-path)
- [Random telegraph noise physics](#random-telegraph-noise-physics)
- [Low-frequency noise physics](#low-frequency-noise-physics)
- [Choosing range sampling and record length](#choosing-range-sampling-and-record-length)
- [RTN analysis rtn_levels](#rtn-analysis-rtn_levels)
- [PSD analysis psd_welch and plot_psd](#psd-analysis-psd_welch-and-plot_psd)
- [Record statistics it_statistics](#record-statistics-it_statistics)
- [Module coverage and bring-up L8](#module-coverage-and-bring-up-l8)
- [Simulator behaviour](#simulator-behaviour)
- [Troubleshooting noise records](#troubleshooting-noise-records)

## WGFMU and RSU in one page

- Two channels per module (201, 202 in the lab), each with an RSU near the probe tips (AN-RTN p4 (4)): one RSU on
  the gate, one on the drain, source and bulk on the common (GNDU) - the lab's and the application note's RTN set-up.
- Modes: Fast IV (voltage out, voltage or current measured), PG (50 Ohm, voltage only), DC (static force/measure),
  SMU pass-through (WG p16 (1-4)). Force ranges 3 V, 5 V, -10..0 V, 0..10 V; the lab uses 5 V.
- Current ranges 1 uA, 10 uA, 100 uA, 1 mA, 10 mA (WG p142 (4-72) "6003" = 100 uA), no compliance: a reading
  beyond full scale saturates and is flagged `V` (untrusted). Resolution 0.014 % and noise floor about 0.2 % of the
  range (AN-RTN p5 (5)); bandwidth falls with the range: 10 mA ~16 MHz, 1 mA ~8 MHz, 100 uA ~2.4 MHz, 10 uA
  ~600 kHz, 1 uA ~80 kHz (AN-RTN p7 (7), 25 pF load; cables lower it).
- Sampling: 10 ns grid, interval 10 ns..1.34217728 s, averaging 10 ns..20.97 ms (<= the interval), about 4,000,000
  values per channel (AN-RTN p5 (5), WG p125 (4-55) "setMeasureEvent"). The time stamp of an averaged point is
  the centre of its window (WG p126 (4-56)). Readback runs in 100,000-value chunks (the lab code and the kernel).
- The RSU switches between its SMU input and the WGFMU; the kernel connects it only for the waveform and returns it
  in the cleanup (knowledge 11, RSU of the WGFMU). Its From SMU input takes at most +-25 V (WG p20 (1-8): above it
  the RSU is damaged) and the SMU path 100 mA, in any RSU state: the SMU cabled there stays within that in every
  plan (R-RSU-01, the guard).

## Fast I-V pulses ramps and timing

- `wgfmu.pulsed_iv`: one gate pulse per level, Id averaged over the flat top minus `settle` at both ends: the
  transfer curve with less self-heating and less slow-trap charging than DC (reduced, not removed); compare with DC
  Id-Vg (`pulsed_vs_dc`, knowledge 06b).
- `wgfmu.fast_iv`: microsecond up/down ramps, one point per interval: fast hysteresis; `wgfmu.pulse_train`: many
  identical pulses with several points per plateau: drift over a train. Its `gate_mode: pg` runs the gate channel in
  PG mode (WG p16 (1-4)): the set level is the open-load level behind 50 Ohm (an insulated gate sees all of it, a
  50 Ohm load half), 5 V ranges only (R-WG-02); the kernel does not measure on that channel (PG mode could measure
  voltage, WG p16 (1-4)); the drain stays in Fast IV.
- A shorter window is faster but noisier: averaging n samples (5 ns each) lowers white noise as 1/sqrt(n)
  (AN-RTN p7 (7) figure 6). Keep the window on the flat top: edges and cable ringing bias the average.

## Constant-bias sampling dc_sample

- Builder `dc_sample` (recipes `wgfmu.rtn`, `wgfmu.lfn`): every channel ramps 0 V -> its level in `edge`, holds it
  `settle` (traps reach their bias equilibrium), then one measurement event `sample` of `points` points every
  `interval`, each averaged over `average` (0 = one 5 ns sample), then back to 0 V. All channels share the timing,
  so the rows line up.
- The lab's LFN layout (`lwp/1530/LFN_noise_meas.cpp`): channel 1 (gate) measures its voltage, channel 2 (drain) its
  current on 100 uA, both Fast IV on the 5 V range, one event of 504,000 points at 100 ns with 100 ns averaging,
  merged output `time, ch1, ch2`. `wgfmu.lfn` keeps exactly this layout and these defaults (at a constant bias);
  `wgfmu.rtn` measures only the drain current (400,000 points at 10 us).
- Above 200,000 rows the run table is `data.npz` + `preview.csv`; the raw readback is `raw/wgfmu-<ch>-000.npz`;
  `get_run` shows at most 200 rows. Analyse with `analyze_run` (the server reads the whole record).

## PUND program read and the pulse_read WGFMU path

- Builders `pund` and `program_read` (`catalog/ferro_waveforms.py`, kind `wgfmu_waveform`): ONE sequencer run.
  `pund`: preset, P, U, N, D ramps on the top channel, the bottom channel at 0 V sampling each pulse contiguously
  (events P/U/N/D). `program_read`: per cycle the erase pulse, a gate staircase read (drain at `v`), the program
  pulse, a read; the read follows its pulse after the rest of the period (microseconds), events `erase`/`program`.
- Kind `pulse_read` with a `wgfmu` pulse role (`pulse_wgfmu.py`): the schedules of the SPGU path (cycles, endurance
  checkpoints, grid, retention) with WGFMU pulses, bipolar cycling bursts (one cycle pattern repeated up to 10^6 times
  per entry) and WGFMU reads (`wgfmu_read` `sweep` or `pund`), one execution per step inside one library phase (the
  output stays at its rest level between executions; that `WGFMU_update` keeps the level across an execution
  boundary is checked at bring-up L9 on `wgfmu.fast_bti`, `TODO(verify)[L9.A9]`).
- Simulator: a vertex step holds the level at its end, so a pulse's leading edge counts as time at the level for
  switching kinetics; long unmeasured repeats (cycling) are stepped in aggregated chunks with the devices' cycle
  counter (wake-up/fatigue exact, retention between pulses approximate).

## Random telegraph noise physics

- One trap at the gate-dielectric interface captures and emits a carrier: the drain current jumps between two
  levels. Capture lowers |Id| (number fluctuation); one electron shifts Vth by about q / (L W Cox), so RTN grows as
  devices shrink (AN-RTN p3 (3) "RTN"). Time constants range from microseconds to seconds.
- Two-state Markov process: the dwell time in the empty state (until capture) is exponential with mean `tau_c`, in
  the occupied state (until emission) with mean `tau_e`; occupancy = tau_e / (tau_c + tau_e).
- `dI/I` = step / empty-trap current; for a small trap dI/I ~ gm dVth / Id.
- PSD of one trap: a Lorentzian `4 dI^2 / ((tau_c + tau_e)((1/tau_c + 1/tau_e)^2 + (2 pi f)^2))`, flat below the
  corner `fc = (1/tau_c + 1/tau_e) / (2 pi)` and falling as 1/f^2 above it.
- tau_c and tau_e depend strongly on Vg (and Vd, temperature): the trap level moves against the Fermi level, the
  number of levels and the histogram peaks change with bias (AN-RTN p8 (8)). Measure RTN at several biases in
  separate runs; several traps give more than two levels (`rtn_levels` then warns via the dwell `cv`).

## Low-frequency noise physics

- Drain-current noise below ~1 MHz: `S_I(f) = A / f^gamma` with gamma near 1 (a commonly quoted range of about
  0.7..1.3 needs a checked source, `TODO(cite)`), plus a white floor and, in
  small devices, RTN Lorentzians. Many traps with spread time constants add up to 1/f.
- Normalized PSD `S_I/I^2` compares devices and biases. Number fluctuation (McWhorter): `S_I/I^2` follows
  (gm/I)^2 over bias; mobility fluctuation (Hooge): `S_I/I^2 = alpha_H / (N f)`, falling as 1/I. Input-referred gate
  noise `S_Vg = S_I / gm^2` (option `gm_s` of `psd_welch`; take gm from an Id-Vg at the same bias).
- With an RTN Lorentzian in the band a single power law is wrong: its 1/f^2 part steepens the slope. `psd_welch`
  model `auto` adds one Lorentzian when the spectrum shows a clear bump; the 1/f part then comes from the frequencies
  where it dominates.

## Choosing range sampling and record length

| choice | rule | why |
|---|---|---|
| current range | smallest range whose full scale is above the largest Id (about 2x) | floor scales with the range; over range saturates (`V`) |
| bandwidth | range bandwidth > 1 / (2 pi tau_min) x 10 | fast steps are rounded off on low ranges (AN-RTN p7 (7)) |
| interval | <= tau_min / 10 (RTN); 1 / (10 f_max) (LFN) | dwells shorter than ~2 points are missed |
| average | = interval | filters noise above the sampling rate (anti-alias); 0 = single 5 ns samples |
| record (RTN) | >= 100 (tau_c + tau_e), >= 200 transitions | tau error about 1/sqrt(dwells per state) |
| record (LFN) | T >= 3 (segments + 1) / (2 f_min) | lowest fitted frequency is 3 f_res = 3 (segments + 1) / (2 T) |
| points | <= 4,000,000 per channel | module memory (R-WG-02, policy `run_limits.max_points.wgfmu`) |
| settle | >= 10 x the slowest tau at the bias | traps start in equilibrium |

## RTN analysis rtn_levels

Record: one measured column `y` (default the only measured current) against `t_s`, trusted rows inside
`t_min..t_max`, the event with the most rows (or `event`), the longest uniformly sampled stretch (spacings within
10 % of the median); untrusted points refuse unless `force`; at least 64 points.

1. Levels: two-Gaussian mixture (EM on a 512-bin histogram, started at the 10th/90th percentiles) of the record and
   (unless `baseline_s` = 0) of the record minus its moving mean over +-n/200 points; the better separated one
   starts the classification (a drift or strong 1/f wander hides the steps in the raw histogram).
2. Hysteresis (Schmitt trigger): the state changes only when a point passes `lo + (1 + h)/2 dI` upwards or
   `lo + (1 - h)/2 dI` downwards (`hysteresis` h = 0.5: thresholds at 25 % and 75 % of the step).
3. Level tracking (unless `baseline_s` = 0): each level's moving mean over `baseline_s` (default 50 mean dwells, at
   least 64 points) of its own points, then classify again (twice): removes slow 1/f wander. `smooth` > 1 first
   averages that many points.
4. The trap is empty in the state with the larger |y| (`occupied="high"` swaps it). Dwells run between transition
   times (midway between the last point of a state and the first of the next); first and last dwell are dropped.
5. Results: `tau_c` = mean dwell in the empty state, `tau_e` = mean dwell in the occupied state (fit: `n`, `se` =
   tau/sqrt(n), `tau_fit_s` from the dwell survival function above 2 dt, `cv`), `delta_i` = mean difference of the
   local levels, `delta_i_rel` = delta / |empty level| (`delta_v` for a voltage); fit: `transitions`, `occupancy`,
   `separation` = delta / robust point noise, `dt_s`, `duration_s`.
6. Failed: no mixture with two levels (< 2 sigma apart or a level < 1 % of the points), tracked levels < 3 sigma
   apart, or < 3 complete dwells per state. Warned:
   < 200 transitions, tau < 10 dt, separation < 5, `cv` outside 0.6..1.4 (several traps), survival fit > 25 % away.

## PSD analysis psd_welch and plot_psd

- Welch: `segments` (8) Hann segments of length `2 n / (segments + 1)`, half overlapping, mean removed; one-sided
  `S = 2 dt |X|^2 / sum(w^2)` (white variance s^2 -> `2 s^2 dt`); `S/mean^2` is the normalized PSD.
- Fit window `f_min..f_max`, defaults 3 f_res and 1/(10 dt); log bins (10 per decade, bias-corrected `ln`),
  weighted by their FFT bins; models `power` = `A/f^gamma + W`, `power_lorentzian` = `+ B/(1 + (f/fc)^2)`; grid with
  non-negative amplitudes, then Levenberg-Marquardt in log space; `auto` keeps the Lorentzian when the BIC falls by
  > 10, `fc` lies in the window (x/÷ 3) and the bump is at least twice the 1/f part at `fc`.
- Results: `gamma` (classification = model; fit `gamma_se`, `a`, `white`, `rms_log`, window), `flicker_norm_1hz`
  = A/mean^2, `psd_at_f_ref` and `norm_psd_at_f_ref` (measured binned PSD at `f_ref`, default the lowest power of
  ten in the window), `corner_frequency` with a Lorentzian (fit `plateau`, `tau_rtn_s` = 1/(2 pi fc) =
  1/(1/tau_c + 1/tau_e)), `input_noise_at_f_ref` = S_I/gm^2 with `gm_s`. Warned: gamma at a grid end (0.2, 2.5),
  `rms_log` > 0.3.
- `plot_psd`: S and S/mean^2 vs f (log-log): Welch estimate, fitted bins, model and parts, shaded window.

## Record statistics it_statistics

`mean` (median, min, max, 1st/99th percentile), `std` (fit `white_estimate` = std of first differences / sqrt 2,
`skewness`, `excess_kurtosis`, Sarle's `bimodality` = (skew^2 + 1)/(excess kurtosis + 3): above 5/9 warned as a
likely two-level RTN), `noise_rel` = std/|mean|, `drift_rel` = linear slope x duration / |mean|, `sample_interval`
(fit `jitter_rel`). Also works on SMU sampling runs (`generic.smu_sampling`, `mosfet.id_t_sampling`).

## Module coverage and bring-up L8

- Recipes (blueprint v2 3.4, all `sim_validated`): `wgfmu.pulsed_iv`, `wgfmu.fast_iv`, `wgfmu.pulse_train` (card
  `wgfmu-pulsed-iv`), `wgfmu.rtn`, `wgfmu.lfn` (`wgfmu-rtn-noise`), `wgfmu.custom_waveform`, `wgfmu.dc_spot`
  (`wgfmu-custom-waveform`), `fecap.pund` (`fecap-pund`; `fecap.endurance_pund` at L9), `fefet.fast_program_read`
  (`fefet-pulse-write-read`), `wgfmu.fast_bti` (`bti-stress-measure`, L9), `system.wgfmu_self_test` and
  `system.wgfmu_self_cal` (`self-test-cal`).
- What the kernel calls (`WgfmuApi`, bound 1:1 by `WgfmuDll`): session open/close, `initialize`, `clear`, channel
  ids, modes, ranges, measure enable, patterns (`createPattern`, one `addVectors` per pattern), measure and range
  events, sequences, `update`, `connect`/`disconnect` (RSU), `execute`, status polls at most 1 s apart, chunked
  readback, DC force/measure, self-test/cal, error strings, and the warning summary after every run (library
  defaults kept: warnings are reported in `kind_result.wgfmu_warnings`/`wgfmu_warning_text` and the audit, never
  turned into errors; WG p138 (4-68) Table 4-4). Never: the library log file (the audit log has every call), the
  ASCII export (`program.json`), reads while the sequencer runs, pattern edits or transforms (host builders),
  trigger output, delay trims (coverage ledger, WP10.8).
- Bring-up L8 (skill `b1500-bringup`, `l8-wgfmu.md`): the library session probe, the library self-test and
  self-calibration, DC into the 100 kOhm standard through the RSU (I(R) +-3 %), pulsed vs DC Id-Vg through the RSU
  SMU inputs (explained), the fast ramp and a pulse train, the lab's own waveform files, RTN and LFN records, a
  FeCap PUND, the fast FeFET program/read; a scope on the RSU V Monitor shows each waveform and 0 V after it.
- Hardware facts behind the simulator's assumptions are bring-up L8 records; the stage file `l8-wgfmu.md`
  (Expected values) lists them with their checks: releasing the FLEX lock is enough for the library session
  (ATV-14; fallback `settings.wgfmu.flex_during_phase: close`), `initialize` leaves an SMU bias alone (ATV-17), the
  RSU SMU path (ATV-32), an accepted `disconnect` = the relay opened, the error-string format, the readback time of
  504,000 points, real noise floors and bandwidth with the lab's cables
  (`TODO(verify)[L8.A4, L8.A6, L8.A7, L8.A10, L8.A11]`).

## Simulator behaviour

- Attached `noise` device (scenario `nmos_rtn`): white noise per range, 1/f^gamma by spectral shaping (one
  independent realisation per measurement event, so no correlation below 1/record), one RTN trap sampled exactly
  at the point times (not averaged over the window), plus the WGFMU floor averaged as 1/sqrt(n).
- `nmos_rtn` truth (simulator example, not a real-device value): gamma 1, `S_I/I^2 = 1e-5/f`, tau_c 1 ms,
  tau_e 0.5 ms, dI/I 5 % (corner 477 Hz); at the card's bias (Vg 1 V, Vd 0.1 V) Id is about 11.7 uA. The
  realisation advances with every run (persisted call counter).
- Blueprint 4.2 targets met by the defaults: gamma +-0.1, tau_c and tau_e +-20 % (about 5,000 transitions),
  dI/I +-10 % (tests/integration/test_recipes_noise.py). Real noise floors and bandwidths are bring-up facts
  (`TODO(verify)[L8.A6]`); trap statistics are device facts that runs give.

## Troubleshooting noise records

| symptom | first check | then |
|---|---|---|
| `V` points, flat-topped record | range vs Id | next range up (runbook `wgfmu-range-overflow`) |
| `rtn_levels` failed: no two levels | `it_statistics` bimodality, `plot_timeseries` of a short window | other bias; smaller range; `smooth` |
| few transitions, large `se` | record vs tau_c + tau_e | more points or longer interval (memory budget) |
| tau near 10 dt, `cv` < 0.6 | interval vs dwells | sample faster; check range bandwidth |
| gamma at 0.2 or 2.5, `rms_log` high | `plot_psd` | narrow `f_min`/`f_max`; model `power_lorentzian`; line pickup (runbook `noisy-data`) |
| PSD flat at the floor | floor vs signal | smaller range, longer `average`; contact check |
