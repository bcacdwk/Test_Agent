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
  - {id: bti_n, recipe: reliability.bti_sms, quantity: n, method: bti_power_law, unit: '1', reference: 'lab BTI on a sister device (EasyEXPERT or published process data)', tolerance: {absolute: 0.05}, text: '+-0.05 of the reference exponent'}
  - {id: bti_cleanup, recipe: reliability.bti_sms, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: igzo_dvth, recipe: igzo.bias_stress, quantity: delta, method: degradation_vs_time, unit: V, reference: lab IGZO bias-stress data, text: recorded (sign and magnitude)}
  - {id: igzo_cleanup, recipe: igzo.bias_stress, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: hci_m, recipe: reliability.hci, quantity: m, method: degradation_vs_time, unit: '1', reference: lab HCI data, text: recorded}
  - {id: hci_cleanup, recipe: reliability.hci, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: silc_ratio, recipe: reliability.silc, quantity: silc_ratio, method: silc, unit: '1', reference: lab SILC data, text: recorded}
  - {id: silc_cleanup, recipe: reliability.silc, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: tddb_tbd, recipe: reliability.tddb_cvs, quantity: t_bd, method: time_to_breakdown, unit: s, reference: the run's own compliance stop, text: 'within one sample interval of the compliance row'}
  - {id: tddb_cleanup, recipe: reliability.tddb_cvs, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: bdv, recipe: dielectric.bdv, quantity: bdv, method: breakdown_voltage, unit: V, reference: 'EasyEXPERT ramp on a sister capacitor', tolerance: {rel: 0.05}, text: '+-5 % of the reference ramp'}
  - {id: bdv_cleanup, recipe: dielectric.bdv, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: breakdown_search, recipe: basic.breakdown_search, quantity: bdv, method: breakdown_voltage, unit: V, reference: 'diode datasheet or EasyEXPERT reverse sweep', tolerance: {rel: 0.05}, text: '+-5 % of the reference'}
  - {id: search_bd_cleanup, recipe: basic.breakdown_search, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: endurance_mw, recipe: fefet.endurance, quantity: memory_window_final, method: endurance_summary, unit: V, reference: 'lab FeFET endurance data (wake-up, fatigue)', text: 'recorded with the cycle count reached; MW of the first checkpoint consistent with L7'}
  - {id: endurance_cleanup, recipe: fefet.endurance, quantity: cleanup, reference: run manifests, text: 'verified: lop, SPGU stopped, selector at rest, also after the cancel'}
  - {id: retention_slope, recipe: fefet.retention, quantity: retention_slope_program, method: retention_fit, unit: V/dec, reference: 'lab FeFET retention data', text: recorded for both states}
  - {id: retention_cleanup, recipe: fefet.retention, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, selector at rest'}
  - {id: fast_bti_n, recipe: wgfmu.fast_bti, quantity: n, method: fast_bti_shift, unit: '1', reference: 'bti_n of a sister device (SMU reads) or lab fast-BTI data', tolerance: {absolute: 0.05}, text: '+-0.05 of the reference exponent'}
  - {id: fast_vs_smu, recipe: wgfmu.fast_bti, quantity: dvth, method: fast_bti_shift, unit: V, reference: 'dvth of reliability.bti_sms on a sister device at the same stress and time', text: 'fast dVth >= SMU dVth (less recovery during the reads); ratio recorded'}
  - {id: rsu_smu_path, recipe: wgfmu.fast_bti, quantity: vth0, unit: V, reference: 'mosfet.idvg on mosfet-4t through the RSU SMU inputs (ATV-32), same 1 uA criterion', tolerance: {absolute: 0.02}, text: 'fast reference read Vth = DC Vth +-20 mV'}
  - {id: fast_bti_cleanup, recipe: wgfmu.fast_bti, quantity: cleanup, reference: run manifests, text: 'WGFMU channels disconnected, session closed, FLEX relocked; SMUs verified'}
  - {id: run_boundary, recipe: wgfmu.fast_bti, quantity: run_boundary, reference: audit time stamps between two WGFMU executions, text: 'host time per boundary recorded; output stays at the stress level (V Monitor or scope)'}
  - {id: pund_wake_fatigue, recipe: fecap.endurance_pund, quantity: fatigue, method: pund_polarization, unit: '1', reference: 'lab FeCap endurance data of the film, if any', text: 'recorded with pr_initial (consistent with L8 pund_pr), wake_up, cycles_to_failure and the cycles reached'}
  - {id: pund_endurance_cleanup, recipe: fecap.endurance_pund, quantity: cleanup, reference: run manifests, text: 'verified: lop; WGFMU disconnected, RSUs at rest, also after the cancel'}
version: 4
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# L9 - Long runs (SMU, HV-SPGU and WGFMU parts)

Asynchronous runs on hardware, with a cancel drill (`safe_shutdown` from the CLI) and a kill-and-recover drill on
each bus family: SMU with `reliability.bti_sms` held for 10 min (card `bti-stress-measure`) while the agent polls
`get_run`, then the other SMU stress and breakdown recipes (cards `igzo-bias-stress`, `hci-silc`, `tddb-bdv`).
HV-SPGU part (L7 signed off): `fefet.endurance` (10^6 bipolar cycles, about 18 min) and `fefet.retention` (hours;
card `fefet-endurance-retention`) on a spare FeFET through `SEL1.OUT1`. WGFMU part (L8 signed off): `wgfmu.fast_bti`
on a sister MOSFET through the RSUs (cancel within one 1 s status poll) and `fecap.endurance_pund` on a spare FeCap
(card `fecap-pund`; about 17 min). Each is destructive or long: `needs_confirmation`, the human's own consent per
run, sacrificial devices. The long plans of L5-L8 (sampling, C-t, trains, RTN/LFN) take the same asynchronous path,
covered per bus by these drills (debug runbook `async-run-interrupted`).

## 1. Preconditions

- L5 signed off; `uv run b1500 bringup status` names L9; `station_status` clean; no other run active.
- Sacrificial devices of the L4 type (BTI, HCI, SILC), an IGZO TFT if the lab has one, a capacitor with the
  dielectric profile (TDDB, BDV) and a diode (breakdown search), each with a DUT profile whose stress envelope the
  owner signed; lab references where they exist (else recorded only). SMU4/SMU3 feed the RSUs since L8 (+-25 V,
  WG p20 (1-8)): a stress or ramp above 25 V needs a landing on an SMU no RSU is cabled to (else R-RSU-01 blocks).
- Auto-calibration state known (`*LRN? 31` in the L1 record).

## 2. Physical steps (human)

1. Land the sacrificial MOSFET (`mosfet-l4`, DUT profile `nmos-l4-stress`, a copy of `nmos-l4` with the stress
   limits); confirm in chat.
2. Cancel drills: about 3 min into the 10 min BTI run (agent step 3), and again during `fefet.endurance` and
   `fecap.endurance_pund` (steps 8, 10), run `uv run b1500 shutdown --reason "L9 cancel drill"` in your own
   PowerShell window; tell the agent when.
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

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status`.
2. `reliability.bti_sms` with stress 10 min (`stress_time: 600`, the card's log-time reads, DUT profile
   `nmos-l4-stress`): validate (tier `needs_confirmation`: `destructive`, `long_run`, `first_hw_run`), show the
   summary, stop; after consent `run_confirmed_plan` (outcome `running`).
3. Poll `get_run(run, include=[progress])` about once a minute; report checkpoints and the last read; the human
   cancels it (physical step 2): `get_run` shows `cancelled`, cleanup verified, `partial.csv` rows; report them as
   partial data.
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

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `async_progress` | `running` at once, progress per checkpoint, then `completed` | pass/fail | `get_run` |
| `cancel_drill`, `cancel_drill_spgu`, `cancel_drill_wgfmu` | `cancelled` within one checkpoint (SMU hold block 25 s, SPGU burst, WGFMU 1 s poll), cleanup verified on that bus, partial rows kept | pass/fail | manifest, audit |
| `recovery_drill`, `recovery_drill_spgu`, `recovery_drill_wgfmu` | `recovery_cleanup` in the next transaction's audit, verified on every bus; killed run `aborted` with its consent record | pass/fail | audit, `get_run` |
| `autocal_restored` | `CM` state after = before, also after each cancel and recovery (`restore` step) | pass/fail | `*LRN? 31` |
| `bti_n` | BTI exponent n | +-0.05 of the reference | lab reference |
| `igzo_dvth`, `hci_m`, `silc_ratio` | stress degradation | recorded | lab data |
| `tddb_tbd` | time to breakdown | one sample interval of the compliance row | the run |
| `bdv` | breakdown voltage of the ramp | +-5 % of the reference | EasyEXPERT |
| `breakdown_search` | diode breakdown voltage | +-5 % of the reference | datasheet / EasyEXPERT |
| `endurance_mw`, `retention_slope` | MW versus cycles; Vth slope per decade | recorded | lab FeFET data |
| `bti_cleanup`, `igzo_cleanup`, `hci_cleanup`, `silc_cleanup`, `tddb_cleanup`, `bdv_cleanup`, `search_bd_cleanup`, `endurance_cleanup`, `retention_cleanup` | every run `verified: lop` | pass/fail | manifests |
| `fast_bti_n`, `fast_vs_smu` | fast exponent; fast dVth >= SMU dVth | +-0.05; recorded | sister device |
| `rsu_smu_path` | fast reference Vth = DC Vth through the RSU SMU path (ATV-32) | +-20 mV | `mosfet.idvg` on `mosfet-4t` |
| `fast_bti_cleanup`, `run_boundary` | WGFMU safe state verified; boundary time recorded | pass/fail; recorded | manifest, audit |
| `pund_wake_fatigue`, `pund_endurance_cleanup` | Pr versus cycles (wake-up, fatigue); safe state verified | recorded; pass/fail | `pund_polarization` |

- TODO(verify) (blueprint v2 7.6 items 8, 10, 13): timer runs on for hours without a reset (`time_source` stays
  `timestamp`), host overhead per hold block, auto-calibration over hours with outputs off; WGFMU: the next
  execution keeps the stress level, the RSU SMU path reaches the DUT (ATV-32; fallback: separate SMU wiring in the
  pin map); IGZO drift, FeFET retention and endurance of the real devices behind the card defaults.

## 5. Abort criteria

- A cancel that does not stop within two checkpoints; a recovery cleanup not verified (any bus: SMU, SPGU `SPST?`,
  selector, WGFMU channels/RSUs); a fault latched; the lock still held after a drill; `CM` not restored.
- Gate current at its compliance in a BTI read (premature breakdown: runbook `stress-degradation-unexpected`).
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human; never clear a fault.

## 6. Record

- Hardware: the stage record of the drills (`uv run b1500 bringup record L9 --run H... --run H... --operator
  NAME`; the human adds the observations) and one recipe record each (`--recipe reliability.bti_sms` and so on, with
  `--reference` values where the lab has them). The human reviews them and moves them to `validation/hw/stage-l9.yaml`
  and `validation/hw/<recipe>.yaml` for each of the eleven recipes of this stage (e.g. `reliability.bti_sms.yaml`).
- Simulator rehearsal (`timing: scaled` scenarios `nmos_bti`, `fefet_lab`, `fecap_basic`): the drills run the
  same way on `S...` runs; no record from them; say which records hardware drafts.
