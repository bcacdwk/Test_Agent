---
stage: L8
title: WGFMU and RSU - library session, self-test and self-calibration, DC into a known resistor through the RSU, fast versus DC Id-Vg, the lab waveform rerun, RTN and LFN records, FeCap PUND, fast FeFET program/read
recipes: [system.wgfmu_self_test, system.wgfmu_self_cal, wgfmu.dc_spot, wgfmu.pulsed_iv, wgfmu.fast_iv, wgfmu.pulse_train, wgfmu.custom_waveform, wgfmu.rtn, wgfmu.lfn, fecap.pund, fefet.fast_program_read]
checks:
  - {id: session_probe, quantity: wgfmu_session, reference: 'doctor --probe --wgfmu-session at the start of L8', text: 'PASS: the library lists 201 and 202, idle, session closed again'}
  - {id: lock_cycle, quantity: lock_cycle, reference: 'audit of every L8 run (checkpoints wgfmu_phase, wgfmu_phase_end; ATV-14)', text: 'FLEX lock released before and taken back after every WGFMU phase; no BusLocked'}
  - {id: rsu_vmonitor, quantity: rsu_vmonitor, reference: 'oscilloscope (high impedance) on the RSU201 V Monitor (WG p20 (1-8))', text: 'the waveform during a run, 0 V after it (RSU back on its SMU path)'}
  - {id: no_fw_errors, quantity: library_errors, reference: 'wgfmu_call errors in the audit of every L8 run; kind_result.wgfmu_warnings', text: 'no 30xx/33xx firmware code (module, RSU, memory, setup); every library warning explained'}
  - {id: wgfmu_self_test_result, recipe: system.wgfmu_self_test, quantity: result, method: kind_result, reference: 'library self-test result (0 = pass)', tolerance: {max_abs: 0.5}, text: 'result 0, no failed unit'}
  - {id: wgfmu_self_test_cleanup, recipe: system.wgfmu_self_test, quantity: cleanup, reference: run manifests, text: 'verified: lop; session closed, FLEX relocked'}
  - {id: wgfmu_self_cal_result, recipe: system.wgfmu_self_cal, quantity: result, method: kind_result, reference: 'library self-calibration result (0 = pass)', tolerance: {max_abs: 0.5}, text: 'result 0, no failed unit'}
  - {id: wgfmu_self_cal_cleanup, recipe: system.wgfmu_self_cal, quantity: cleanup, reference: run manifests, text: 'verified: lop; session closed, FLEX relocked'}
  - {id: r_wgfmu, recipe: wgfmu.dc_spot, quantity: resistance, method: resistance, unit: Ohm, reference: 'DMM reading of the 100 kOhm standard (L2 r_dmm)', tolerance: {rel: 0.03}, text: 'I(R) through the RSU: +-3 % vs DMM'}
  - {id: dc_spot_cleanup, recipe: wgfmu.dc_spot, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: pulsed_vs_dc, recipe: wgfmu.pulsed_iv, quantity: pulsed_over_dc, method: pulsed_vs_dc, unit: '1', reference: 'mosfet.idvg on mosfet-4t through the RSU SMU inputs, same vd (options.reference_run)', text: 'recorded and explained: about 1 at 1 % duty; a difference has a named cause'}
  - {id: pulsed_cleanup, recipe: wgfmu.pulsed_iv, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: fast_iv_gm, recipe: wgfmu.fast_iv, quantity: gm_max, method: gm_max, unit: S, reference: 'gm_max of the DC reference Id-Vg (same vd)', text: recorded (up and down ramp; fast hysteresis)}
  - {id: fast_iv_cleanup, recipe: wgfmu.fast_iv, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: train_plateau, recipe: wgfmu.pulse_train, quantity: plateau_current, method: pulse_plateau, unit: A, reference: 'the pulsed_iv plateau at the same gate level', text: recorded (drift over the train)}
  - {id: train_cleanup, recipe: wgfmu.pulse_train, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: lwp_values, recipe: wgfmu.custom_waveform, quantity: values, method: kind_result, reference: 'the lab''s own run of the same CSV files (lwp/1530; 2 x 55,200 for the committed sample)', text: 'every event value read back, as many as the lab''s run'}
  - {id: custom_cleanup, recipe: wgfmu.custom_waveform, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: rtn_tau_c, recipe: wgfmu.rtn, quantity: tau_c, method: rtn_levels, unit: s, reference: 'lab RTN data of the device, if any', text: recorded with tau_e and delta_i_rel (at least 200 transitions)}
  - {id: rtn_cleanup, recipe: wgfmu.rtn, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: lfn_gamma, recipe: wgfmu.lfn, quantity: gamma, method: psd_welch, unit: '1', reference: 'the lab LFN record of the same device (lwp/1530 LFN_noise_meas)', text: recorded with the PSD at f_ref}
  - {id: lfn_cleanup, recipe: wgfmu.lfn, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: pund_pr, recipe: fecap.pund, quantity: pr, method: pund_polarization, unit: uC/cm^2, reference: 'lab P-V data of the film, if any', text: 'recorded with Ps, Ec and the window'}
  - {id: pund_vc, recipe: fecap.pund, quantity: vc, method: pund_polarization, unit: V, reference: 'the butterfly peaks of fecap.cv_butterfly (L6) on a sister capacitor', text: 'recorded; same sign and order of magnitude as the butterfly'}
  - {id: pund_cleanup, recipe: fecap.pund, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
  - {id: fast_mw, recipe: fefet.fast_program_read, quantity: memory_window, method: memory_window_pulse, unit: V, reference: 'pulse_mw of fefet.pulse_write_read at L7 (same FeFET)', text: 'same sign as the L7 pulse MW; ratio recorded'}
  - {id: fast_pr_cleanup, recipe: fefet.fast_program_read, quantity: cleanup, reference: run manifests, text: 'verified: lop; every WGFMU channel disconnected, RSUs at rest'}
version: 1
---

# L8 - WGFMU and RSU

The B1530A WGFMU through its instrument library and the RSUs: first the library session and the module's own
self-test and self-calibration (card `self-test-cal`), then DC into the 100 kOhm standard through the RSU (card
`wgfmu-custom-waveform`), then the L4 MOSFET: pulsed Id-Vg against a DC Id-Vg through the RSU SMU inputs, the fast
ramp and a pulse train (card `wgfmu-pulsed-iv`), the lab's own waveform files and RTN/LFN records (cards
`wgfmu-custom-waveform`, `wgfmu-rtn-noise`), then a FeCap PUND (card `fecap-pund`) and the fast program/read of the
L7 FeFET (card `fefet-pulse-write-read`). The WGFMU has no compliance: the guard checks every vector of a program
before the library sees it (R-WG-02), the ranges only bound the reading. Endurance PUND and fast BTI are L9.

## 1. Preconditions

- L7 (L4 at least) signed off; L0's `wgfmu_library` and `wgfmu_session` PASS (x64 library >= A.03.00);
  `uv run b1500 bringup status` names L8; `station_status` clean: no fault, no run, RSUs at rest.
- The 100 kOhm standard with its DMM reading (L2), the L4 MOSFET (EasyEXPERT reference), a FeCap with area and
  thickness known (DUT profile reviewed: pulse envelope, `geometry`), the L7 FeFET; an oscilloscope if available.

## 2. Physical steps (human)

1. Mount RSU201 and RSU202 near the probes, cable WGFMU 201 -> RSU201 and 202 -> RSU202, and SMU4/SMU3 Force to the
   RSUs' From SMU inputs, with no DUT on the RSU outputs (WG p20 (1-8)); tell the agent which SMU feeds which RSU,
   check its proposal and adopt it: `uv run b1500 config adopt work/bringup/station.proposed.yaml --as station`.
2. Lift the probes (RSU outputs open) for agent step 2; confirm in chat.
3. Land the 100 kOhm standard between the RSU201 output and ground (pin map `resistor-wgfmu`); confirm.
4. Land the L4 MOSFET: gate RSU201, drain RSU202, source GNDU (pin map `mosfet-wgfmu`; through the RSU SMU paths the
   same landing is `mosfet-4t`); a scope on the RSU201 V Monitor if you have one (`rsu_vmonitor`). For the lab's own
   waveforms copy the CSV files to `work/waveforms/` and name them in chat.
5. Land the FeCap: top RSU201, bottom RSU202 (pin map `fecap-wgfmu`, DUT profile with area and thickness); confirm.
6. Land the L7 FeFET with gate RSU201, drain RSU202, source GNDU (pin map `fefet-wgfmu`); confirm.

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status`; `uv run b1500 doctor --probe --wgfmu-session` (read-only:
   `session_probe`). Wiring of step 1: `uv run b1500 bringup propose-station`, write the `smu` inputs of the RSUs
   into `work/bringup/station.proposed.yaml`, show the diff, hand the adoption over, stop.
2. Open terminals: `system.wgfmu_self_test`, then `system.wgfmu_self_cal` (pin map `open-smus`): validate
   (`system_self_test`/`system_self_cal`, `first_hw_run`), summary and the open-terminal question, stop, consent,
   run; report `kind_result` (result, failed units).
3. `wgfmu.dc_spot` on `resistor-wgfmu`, DUT `resistor-generic` (card params): `resistance` against the DMM.
4. DC reference: `mosfet.idvg` on `mosfet-4t` (DUT `nmos-wgfmu`; vd 1 V, vg 0 to 2 V in 21 points, as the pulsed
   plan; ATV-32), then `wgfmu.pulsed_iv` on `mosfet-wgfmu` (card example) and `analyze_run(run, "pulsed_vs_dc",
   {reference_run: <DC run>})`; explain any difference (knowledge 10). Then `wgfmu.fast_iv` (`gm_max`) and `wgfmu.pulse_train`
   (`pulse_plateau`; card example).
5. `wgfmu.custom_waveform`: the human's CSV files from `work/waveforms/` (`adhoc_recipe`) or the committed sample;
   compare `kind_result.values` and the shapes with the lab's own run of the same files.
6. `wgfmu.rtn`, then `wgfmu.lfn` (card examples; a short `points` first): `rtn_levels`, `psd_welch`.
7. FeCap (physical step 5): `fecap.pund` on `fecap-wgfmu` (card example): `pund_polarization` (Pr, Ps, Ec, Vc).
8. FeFET (physical step 6): `fefet.fast_program_read` on `fefet-wgfmu`: `memory_window_pulse` next to L7's MW.
9. After each run `get_run(run, include=[summary, audit])`: the `wgfmu_phase` checkpoints (`lock_cycle`), library
   errors and warnings (`kind_result.wgfmu_warnings`, `wgfmu_warning_text`: `no_fw_errors`), the cleanup. Report
   every value as derived (method id, window), status counts, backend.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `session_probe` | library lists 201, 202; idle; closed again | PASS | `doctor --probe` (ATV-16) |
| `lock_cycle`, `no_fw_errors` | lock released and retaken around each phase; no 30xx/33xx code; warnings explained | pass/fail | audit, `kind_result` |
| `rsu_vmonitor` | waveform at the V Monitor during a run, 0 V after it | pass/fail | oscilloscope |
| `wgfmu_self_test_result`, `wgfmu_self_cal_result` | `kind_result.result` 0 through the library | 0 | WG p92 (4-22) "WGFMU_doSelfTest" |
| `r_wgfmu` | 100 kOhm standard through the RSU, 10 uA range | +-3 % of the DMM | `resistance` |
| `pulsed_vs_dc` | pulsed/DC Id at 1 % duty (no self-heating, few traps) | recorded, explained | `pulsed_vs_dc` |
| `fast_iv_gm`, `train_plateau` | fast ramp gm; plateau current over the train | recorded | `gm_max`, `pulse_plateau` |
| `lwp_values` | every value of the lab's events read back | as the lab's run | `kind_result` |
| `rtn_tau_c`, `lfn_gamma` | trap times; 1/f exponent near 1 | recorded | `rtn_levels`, `psd_welch` |
| `pund_pr`, `pund_vc` | Pr, Vc (and Ps, Ec) of the PUND | recorded | `pund_polarization` |
| `fast_mw` | fast program/read MW, same sign as L7 | recorded | `memory_window_pulse` |
| `wgfmu_self_test_cleanup`, `wgfmu_self_cal_cleanup`, `dc_spot_cleanup`, `pulsed_cleanup`, `fast_iv_cleanup`, `train_cleanup`, `custom_cleanup`, `rtn_cleanup`, `lfn_cleanup`, `pund_cleanup`, `fast_pr_cleanup` | every run verified, every channel disconnected, session closed | pass/fail | manifests |

- TODO(verify) (blueprint v2 7.6 items 1, 5, 8, 9, 10, 13): releasing the FLEX lock is enough for the library
  session and the relock is clean
  (ATV-14; else `settings.wgfmu.flex_during_phase: close`); `initialize` leaves an SMU bias alone (ATV-17); the RSU
  SMU path reaches the DUT (ATV-32); a `disconnect` the library accepts means the RSU relay opened; the library's
  error-string and warning-summary formats; 3307 vs 3304 above 2,048 vectors; readback time of 504,000 points; DC spot and
  self-test/cal durations; noise floors and bandwidth with the real cables; `wgfmu.pulse_train` with `gate_mode: pg`
  (WP11.2): the PG level on the RSU V Monitor equals the set level on the open gate; fast-IV timing; the real
  device's RTN statistics behind the `wgfmu.rtn` defaults.

## 5. Abort criteria

- A 3000 (module) or 3001 (RSU) code, any 30xx code twice, a phase that does not relock (`BusLocked`), a cleanup
  not verified, the V Monitor still showing a level after a run, `r_wgfmu` off by more than 10 %, status `V` on
  every point of a read (runbooks `wgfmu-library-error`, `wgfmu-rsu-route`, `wgfmu-range-overflow`,
  `wgfmu-memory-budget`).
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human; never raise a limit,
  never touch the library yourself (no script, no `config/local` edit).

## 6. Record

- Hardware: one recipe record per recipe (`uv run b1500 bringup record L8 --run H... --operator NAME`; with
  `--reference r_wgfmu=<DMM Ohm>`, `--reference fast_mw=<L7 pulse MW>`) and the stage record (`--recipe` omitted,
  `--probe latest`, the runs of steps 2 to 4; the human adds `rsu_vmonitor`, `lock_cycle`, `no_fw_errors`). The human
  reviews them and moves them to `validation/hw/stage-l8.yaml`, `validation/hw/system.wgfmu_self_test.yaml`,
  `validation/hw/system.wgfmu_self_cal.yaml`, `validation/hw/wgfmu.dc_spot.yaml`, `validation/hw/wgfmu.pulsed_iv.yaml`,
  `validation/hw/wgfmu.fast_iv.yaml`, `validation/hw/wgfmu.pulse_train.yaml`, `validation/hw/wgfmu.custom_waveform.yaml`,
  `validation/hw/wgfmu.rtn.yaml`, `validation/hw/wgfmu.lfn.yaml`, `validation/hw/fecap.pund.yaml`,
  `validation/hw/fefet.fast_program_read.yaml`.
- Simulator rehearsal (scenarios `resistor_100k`, `nmos_wgfmu`, `nmos_rtn`, `fecap_basic`, `fefet_lab`): no record
  from `S...` runs; say which records hardware drafts.
