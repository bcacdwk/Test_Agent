---
stage: L9
title: Long runs (SMU, HV-SPGU and WGFMU parts) - async runs with a cancel and a kill-recovery drill per bus family, auto-calibration restored, destructive stress and breakdown recipes, FeFET endurance and retention, fast BTI, FeCap endurance by PUND
recipes: [reliability.bti_sms, igzo.bias_stress, reliability.hci, reliability.silc, reliability.tddb_cvs, dielectric.bdv, basic.breakdown_search, fefet.endurance, fefet.retention, wgfmu.fast_bti, fecap.endurance_pund]
checks:
  - {id: async_progress, quantity: async_progress, reference: get_run progress of the 10 min BTI run, text: 'running, progress advancing per checkpoint, completed'}
  - {id: cancel_drill, quantity: cancel_drill, reference: human observation + manifest, text: 'SMU (reliability.bti_sms): safe_shutdown from the CLI: cancelled within one checkpoint, cleanup verified, partial rows kept'}
  - {id: recovery_drill, quantity: recovery_drill, reference: human observation + audit, text: 'SMU: kill during a run: next transaction runs recovery_cleanup, verified, run finalized aborted'}
  - {id: cancel_drill_spgu, quantity: cancel_drill_spgu, reference: human observation + manifest, text: 'HV-SPGU (fefet.endurance): cancelled at the next burst checkpoint, SPST? 0, SEL1 at rest, verified'}
  - {id: recovery_drill_spgu, quantity: recovery_drill_spgu, reference: human observation + audit, text: 'HV-SPGU: kill mid-burst: recovery stops the SPGU, selector at rest, verified, run aborted'}
  - {id: cancel_drill_wgfmu, quantity: cancel_drill_wgfmu, reference: human observation + manifest, text: 'WGFMU (fecap.endurance_pund): cancelled within one 1 s poll, channels disconnected, session closed, RSUs at rest'}
  - {id: recovery_drill_wgfmu, quantity: recovery_drill_wgfmu, reference: human observation + audit, text: 'WGFMU: kill mid-execution: recovery aborts and disconnects through the library, RSUs at rest, verified, run aborted'}
  - {id: autocal_restored, quantity: autocal_restored, reference: '*LRN? 31 before and after (R-CAL-02)', text: 'CM state after = before every async run, also after each cancel and each recovery (restore step)'}
  - {id: timer_hours, quantity: time_source, method: kind_result, reference: 'kind_result.time_source of an hours-long linear generic.smu_sampling chain (PG p539 (4-221))', text: 'timestamp at the end of the chain (the timer ran on without a reset; index or host = the fallback)'}
  - {id: correction_drift, quantity: correction_drift, reference: 'open_cp_f and short_rs_ohm of new corrections against the L6 values, with the days between (corrections.max_age_h)', text: recorded (the owner decides max_age_h from it)}
  - {id: bti_n, recipe: reliability.bti_sms, quantity: n, method: bti_power_law, unit: '1', reference: 'the lab''s own BTI on a sister device, same stress and read delay (published data are no reference)', tolerance: {absolute: 0.05}, text: '+-0.05 of the reference exponent (provisional)'}
  - {id: bti_cleanup, recipe: reliability.bti_sms, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: igzo_dvth, recipe: igzo.bias_stress, quantity: delta, method: degradation_vs_time, unit: V, reference: lab IGZO bias-stress data, text: recorded (sign and magnitude)}
  - {id: igzo_cleanup, recipe: igzo.bias_stress, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: hci_m, recipe: reliability.hci, quantity: m, method: degradation_vs_time, unit: '1', reference: lab HCI data, text: recorded}
  - {id: hci_cleanup, recipe: reliability.hci, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: silc_ratio, recipe: reliability.silc, quantity: silc_ratio, method: silc, unit: '1', reference: lab SILC data, text: recorded}
  - {id: silc_cleanup, recipe: reliability.silc, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: tddb_tbd, recipe: reliability.tddb_cvs, quantity: t_bd, method: time_to_breakdown, unit: s, reference: the run's own compliance stop, text: 'within one sample interval of the compliance row'}
  - {id: tddb_cleanup, recipe: reliability.tddb_cvs, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: bdv, recipe: dielectric.bdv, quantity: bdv, method: breakdown_voltage, unit: V, reference: 'EasyEXPERT ramp on a sister capacitor at the same ramp rate (breakdown spreads device to device)', tolerance: {rel: 0.05}, text: '+-5 % of the reference ramp (provisional)'}
  - {id: bdv_cleanup, recipe: dielectric.bdv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: breakdown_search, recipe: basic.breakdown_search, quantity: bdv, method: breakdown_voltage, unit: V, reference: 'EasyEXPERT reverse sweep of the same diode at the same current criterion (a data-sheet V_BR is a minimum rating, no reference)', tolerance: {rel: 0.05}, text: '+-5 % of the reference (provisional)'}
  - {id: search_bd_cleanup, recipe: basic.breakdown_search, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: endurance_mw, recipe: fefet.endurance, quantity: memory_window_final, method: endurance_summary, unit: V, reference: 'lab FeFET endurance data (wake-up, fatigue)', text: 'recorded with the cycle count reached; MW of the first checkpoint consistent with L7'}
  - {id: endurance_cleanup, recipe: fefet.endurance, quantity: cleanup, reference: run manifests, text: 'verified: lop, SPGU stopped, selector at rest, also after the cancel'}
  - {id: retention_slope, recipe: fefet.retention, quantity: retention_slope_program, method: retention_fit, unit: V/dec, reference: 'lab FeFET retention data', text: recorded for both states}
  - {id: retention_cleanup, recipe: fefet.retention, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, selector at rest'}
  - {id: fast_bti_n, recipe: wgfmu.fast_bti, quantity: n, method: fast_bti_shift, unit: '1', reference: 'the lab''s fast-BTI data of a sister device at the same read delay (not bti_n: slower SMU reads recover more)', tolerance: {absolute: 0.05}, text: '+-0.05 of the reference exponent (provisional)'}
  - {id: fast_vs_smu, recipe: wgfmu.fast_bti, quantity: dvth, method: fast_bti_shift, unit: V, reference: 'dvth of reliability.bti_sms on a sister device at the same stress and time', text: 'fast dVth >= SMU dVth (less recovery during the reads); ratio recorded'}
  - {id: rsu_smu_path, recipe: wgfmu.fast_bti, quantity: vth0, unit: V, reference: 'mosfet.idvg on mosfet-4t through the RSU SMU inputs (ATV-32), same 1 uA criterion', tolerance: {absolute: 0.02}, text: 'fast reference read Vth = DC Vth +-20 mV (provisional)'}
  - {id: fast_bti_cleanup, recipe: wgfmu.fast_bti, quantity: cleanup, reference: run manifests, text: 'WGFMU channels disconnected, session closed, FLEX relocked; SMUs verified'}
  - {id: run_boundary, recipe: wgfmu.fast_bti, quantity: run_boundary, reference: audit time stamps between two WGFMU executions, text: 'host time per boundary recorded; output stays at the stress level (V Monitor or scope)'}
  - {id: pund_wake_fatigue, recipe: fecap.endurance_pund, quantity: fatigue, method: pund_polarization, unit: '1', reference: 'lab FeCap endurance data of the film, if any', text: 'recorded with pr_initial (consistent with L8 pund_pr), wake_up, cycles_to_failure and the cycles reached'}
  - {id: pund_endurance_cleanup, recipe: fecap.endurance_pund, quantity: cleanup, reference: run manifests, text: 'verified: lop; WGFMU disconnected, RSUs at rest, also after the cancel'}
version: 5
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# L9 - Long runs (SMU, HV-SPGU and WGFMU parts)

Async runs with a cancel drill (`safe_shutdown` from the CLI) and a kill-and-recover drill per bus: SMU, HV-SPGU (L7
signed off) and WGFMU (L8 signed off); the stress, breakdown, endurance and retention recipes; the sampling timer over
hours and the drift of the L6 corrections. Destructive or long: the human's consent per run, sacrificial devices.
The long plans of L5-L8 take the same asynchronous path (debug runbook `async-run-interrupted`).

## 1. Preconditions

- L5 signed off; `uv run b1500 bringup status` names L9; `station_status` clean; no other run active.
- Sacrificial devices of the L4 type (BTI, HCI, SILC), an IGZO TFT if the lab has one, a capacitor with the
  dielectric profile (TDDB, BDV) and a diode (breakdown search), each with a DUT profile whose stress envelope the
  owner signed; lab references where they exist (else recorded only); the `*LRN? 31` state of the L1 record. SMU4/SMU3
  feed the RSUs since L8 (+-25 V, WG p20 (1-8)): above 25 V land on an SMU no RSU is cabled to (else R-RSU-01 blocks).

## 2. Physical steps (human)

1. Land the sacrificial MOSFET (`mosfet-l4`, DUT profile `nmos-l4-stress`: `nmos-l4` with stress limits); confirm.
2. Cancel drills: 3 min into the 10 min BTI run, and during `fefet.endurance` and `fecap.endurance_pund` (agent steps
   3, 8, 10): `uv run b1500 shutdown --reason "L9 cancel drill"` in your own PowerShell window; tell the agent.
3. Kill drills: 2 min into the second BTI run (agent step 5), and into a second `fefet.endurance` and
   `fecap.endurance_pund` run, end the MCP server process (Task Manager on `b1500-mcp`, or close the coding agent
   window); wait 1 min; restart the agent in the clone; tell it which run was killed.
4. Re-land on the next sacrificial device for each recipe of agent step 7 and confirm.
5. Land a spare FeFET (pin map `fefet-sel`, the L7 wiring; DUT profile with the gate's pulse `max_count` reviewed
   for 2 x 10^6 pulses); confirm in chat.
6. Fast BTI: a sister MOSFET on the RSU outputs (gate RSU201, drain RSU202; pin map `mosfet-wgfmu`; `mosfet-4t`
   reaches it through the From SMU inputs L8 recorded); optionally a scope on the RSU201 V Monitor; confirm in chat.
7. Land a spare FeCap of the L8 film (top RSU201, bottom RSU202; pin map `fecap-wgfmu`, DUT profile with the pulse
   `max_count` reviewed for 2 x 10^7 pulses); confirm.
8. Land the 100 kOhm standard on the L5 pin map `res-sampling` (DUT profile `r100k`) for agent step 11; confirm.
9. L6 signed off, for agent step 12: the probes of the L6 reference-capacitor pin map lifted, then on a short, each
   when the agent asks, as at L6; confirm each.

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status`.
2. `reliability.bti_sms` with stress 10 min (`stress_time: 600`, the card's log-time reads, DUT profile
   `nmos-l4-stress`): validate (tier `needs_confirmation`: `destructive`, `long_run`, `first_hw_run`), show the
   summary, stop; after consent `run_confirmed_plan` (outcome `running`).
3. Poll `get_run(run, include=[progress])` about once a minute; report checkpoints and the last read; the human
   cancels it (physical step 2): `get_run` shows `cancelled`, cleanup verified, `partial.csv` rows (partial data).
4. Run once more to completion (same plan, new consent): `bti_power_law` (n, A, recovery); `*LRN? 31` state before
   and after in the manifest (auto-calibration suspended by `CM 0` and restored, R-CAL-02).
5. Third run for the kill drill (physical step 3): after the restart `station_status` (in-flight marker) and
   `uv run b1500 runs --status running`; the next transaction (`safe_shutdown("L9 recovery")`) runs the recovery
   cleanup and its `restore` step; `get_run` of the killed run: `aborted`, consent record and partial rows kept.
6. Report each drill as observed (audit lines, outcome, cleanup verification, `restore` step, lock free, no fault).
7. One run each, new consent per run: `igzo.bias_stress` (`degradation_vs_time` quantity vth), `reliability.hci`
   (`degradation_vs_time`), `reliability.silc` (`silc`), `reliability.tddb_cvs` (`time_to_breakdown`),
   `dielectric.bdv` (`breakdown_voltage`), `basic.breakdown_search` on the diode (`breakdown_voltage`).
8. FeFET (physical step 5), new consent per run: `fefet.endurance` (`soft_pulse`, `dut_envelope`, `long_run`;
   poll `get_run`; `endurance_summary`), then `fefet.retention` on a fresh FeFET (`retention_fit`); report MW(N),
   wake-up, fatigue, the retention slopes and any extrapolation as derived. Drills: one `fefet.endurance` cancelled
   and one killed as in steps 3 and 5 (`cancel_drill_spgu`, `recovery_drill_spgu`: `SPST?` 0, `SEL1.OUT1` open).
9. Fast BTI (physical step 6): `mosfet.idvg` on `mosfet-4t` (DC reference through the RSU SMU path, ATV-32), then
   `wgfmu.fast_bti` (`stress_time: 600`, same stress as step 2): `fast_bti_shift`; compare `n`, `dvth` with step 4's
   `bti_power_law`; the audit's time stamps between two WGFMU executions give `run_boundary`.
10. FeCap (physical step 7): `fecap.endurance_pund` (card defaults: 10^7 cycles, PUND reads per decade; `long_run`,
    `soft_pulse`, `dut_envelope`): poll `get_run`; `pund_polarization` (Pr per read, wake-up, fatigue, cycles to
    failure) next to L8's `pund_pr`. Drills on spare FeCaps: one cancelled, one killed (`cancel_drill_wgfmu`,
    `recovery_drill_wgfmu`: channels disconnected, session closed, `RSU201.OUT`/`RSU202.OUT` open).
11. Timer over hours (physical step 8): the L5 `generic.smu_sampling` plan, linear, with an `interval` and `points`
    that span hours (the owner chooses, within the policy's points cap; asynchronous, poll `get_run`): at the end
    `kind_result.time_source` is still `timestamp` (`timer_hours`); index or host is the ATV-22 fallback.
12. Correction drift (physical step 9): `cmu.phase_compensation`, `cmu.correction_open` and `cmu.correction_short`
    on the L6 reference-capacitor pin map as at L6: `open_cp_f` and `short_rs_ohm` against the L6 values and the
    days between (`correction_drift`, the basis of `corrections.max_age_h`: the owner's decision).

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `async_progress`, `autocal_restored` | `running` at once, progress per checkpoint, then `completed`; `CM` state after = before, also after each cancel and recovery (`restore` step) | pass/fail | `get_run`, `*LRN? 31` |
| `cancel_drill`, `cancel_drill_spgu`, `cancel_drill_wgfmu` | `cancelled` within one checkpoint (SMU hold block 25 s, SPGU burst, WGFMU 1 s poll), cleanup verified on that bus, partial rows kept | pass/fail | manifest, audit |
| `recovery_drill`, `recovery_drill_spgu`, `recovery_drill_wgfmu` | `recovery_cleanup` in the next transaction's audit, verified on every bus; killed run `aborted` with its consent record | pass/fail | audit, `get_run` |
| `timer_hours`, `correction_drift` | `time_source` `timestamp` at the end of an hours-long sampling chain; change of `open_cp_f`, `short_rs_ohm` since L6 with the days between | pass/fail; recorded | `kind_result`, correction runs |
| `bti_n` | BTI exponent n | +-0.05 of the reference (provisional) | the lab's sister-device BTI |
| `igzo_dvth`, `hci_m`, `silc_ratio`, `endurance_mw`, `retention_slope` | stress degradation; MW versus cycles; Vth slope per decade | recorded | lab data |
| `tddb_tbd` | time to breakdown | one sample interval of the compliance row | the run |
| `bdv`, `breakdown_search` | breakdown voltage of the ramp (same ramp rate); of the diode (same current criterion) | +-5 % of the reference (provisional) | EasyEXPERT |
| `bti_cleanup`, `igzo_cleanup`, `hci_cleanup`, `silc_cleanup`, `tddb_cleanup`, `bdv_cleanup`, `search_bd_cleanup`, `endurance_cleanup`, `retention_cleanup` | every run `verified: lop` | pass/fail | manifests |
| `fast_bti_n`, `fast_vs_smu`, `rsu_smu_path` | fast exponent; fast dVth >= SMU dVth; fast reference Vth = DC Vth through the RSU SMU path (ATV-32) | +-0.05 (provisional); recorded; +-20 mV (provisional) | lab fast BTI; SMU BTI; `mosfet.idvg` on `mosfet-4t` |
| `fast_bti_cleanup`, `run_boundary`, `pund_wake_fatigue`, `pund_endurance_cleanup` | WGFMU safe state verified; boundary time; Pr versus cycles (wake-up, fatigue) | pass/fail; recorded | manifest, audit, `pund_polarization` |

- Basis: none (provisional criteria): exponents depend on read delay and recovery, breakdown spreads device to device
  and with the ramp rate, `rsu_smu_path` is drift beyond a few-mV instrument part (WG5 p24 (1-14)). `TODO(owner)`:
  which tolerances does the lab accept for `bti_n`, `fast_bti_n`, `rsu_smu_path`, `bdv` and `breakdown_search`?
- TODO(verify) (blueprint v2 7.6 items 7, 8, 10, 13): the timer runs on for hours (`timer_hours`), host overhead
  per hold block, auto-calibration over hours with outputs off; MFCMU correction drift over days (`correction_drift`);
  WGFMU: the next execution keeps the stress level, the RSU SMU path reaches the DUT (ATV-32; fallback: separate SMU
  wiring in the pin map); IGZO drift, FeFET retention and endurance of the real devices behind the card defaults.

## 5. Abort criteria

- A cancel that does not stop within two checkpoints; a recovery cleanup not verified (any bus: SMU, SPGU `SPST?`,
  selector, WGFMU channels/RSUs); a fault latched; the lock still held after a drill; `CM` not restored.
- Gate current at its compliance in a BTI read (premature breakdown: runbook `stress-degradation-unexpected`).
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human; never clear a fault.

## 6. Record

- Hardware: the stage record of the drills, the timer and the correction runs (`uv run b1500 bringup record L9 --run
  H... --run H... --operator NAME`; the human adds the observations) and one recipe record each (`--recipe
  reliability.bti_sms` and so on); the human moves them to `validation/hw/stage-l9.yaml` and `<recipe>.yaml`.
- Simulator rehearsal (`timing: scaled` scenarios `nmos_bti`, `fefet_lab`, `fecap_basic`): the drills run the
  same way on `S...` runs; no record from them; say which records hardware drafts.
