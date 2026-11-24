---
stage: L9
title: Long runs (SMU part) - async BTI with cancel and kill-recovery drills, auto-calibration restored, destructive stress and breakdown recipes
recipes: [reliability.bti_sms, igzo.bias_stress, reliability.hci, reliability.silc, reliability.tddb_cvs, dielectric.bdv, basic.breakdown_search]
checks:
  - {id: async_progress, quantity: async_progress, reference: get_run progress of the 10 min BTI run, text: 'running, progress advancing per checkpoint, completed'}
  - {id: cancel_drill, quantity: cancel_drill, reference: human observation + manifest, text: 'safe_shutdown from the CLI: cancelled within one checkpoint, cleanup verified, partial rows kept'}
  - {id: recovery_drill, quantity: recovery_drill, reference: human observation + audit, text: 'kill during a run: next transaction runs recovery_cleanup, verified, run finalized aborted'}
  - {id: autocal_restored, quantity: autocal_restored, reference: '*LRN? 31 before and after (R-CAL-02)', text: 'CM state after = before every async run'}
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
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# L9 - Long runs (SMU part)

Asynchronous runs on hardware: `reliability.bti_sms` held for 10 min (card `bti-stress-measure`) while the agent
polls `get_run`, a cancel drill (`safe_shutdown` from the CLI) and a kill-and-recover drill; then the other SMU
stress and breakdown recipes (cards `igzo-bias-stress`, `hci-silc`, `tddb-bdv`). Every one is destructive or long:
`needs_confirmation` (`destructive`, `long_run` above 10 min, `first_hw_run`) with the human's own consent per run,
always on a sacrificial device. The WGFMU part (`wgfmu.fast_bti`) joins with M10.

## 1. Preconditions

- L5 signed off; `uv run b1500 bringup status` names L9; `station_status` clean; no other run active.
- Sacrificial devices of the L4 type (BTI, HCI, SILC), an IGZO TFT if the lab has one, a capacitor with the
  dielectric profile (TDDB, BDV) and a diode (breakdown search), each with a DUT profile whose stress envelope the
  owner signed; references from the lab where they exist (else the checks are recorded only).
- Auto-calibration state known (`*LRN? 31` in the L1 record).

## 2. Physical steps (human)

1. Land the sacrificial MOSFET (`mosfet-l4`, DUT profile `nmos-l4-stress`, a copy of `nmos-l4` with the stress
   limits); confirm in chat.
2. Cancel drill: about 3 min into the 10 min BTI run (agent step 3) run `uv run b1500 shutdown --reason "L9 cancel
   drill"` in your own PowerShell window; tell the agent when.
3. Kill drill: start the second BTI run (agent step 5); 2 min in, end the harness's MCP server process (close the
   coding agent window, or Task Manager on `b1500-mcp`); wait 1 min; restart the agent in the clone.
4. Re-land on the next sacrificial device for each recipe of agent step 7 and confirm.

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
5. Third run for the kill drill (physical step 3): after the restart `station_status` and
   `uv run b1500 runs --status running`; the next transaction (`safe_shutdown("L9 recovery")`) runs the recovery
   cleanup; `get_run` of the killed run: finalized `aborted` with its partial rows.
6. Report each drill as observed (audit lines, outcome, cleanup verification, lock free, no fault).
7. One run each, new consent per run: `igzo.bias_stress` (`degradation_vs_time` quantity vth), `reliability.hci`
   (`degradation_vs_time`), `reliability.silc` (`silc`), `reliability.tddb_cvs` (`time_to_breakdown`),
   `dielectric.bdv` (`breakdown_voltage`), `basic.breakdown_search` on the diode (`breakdown_voltage`).

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `async_progress` | `running` at once, progress per checkpoint, then `completed` | pass/fail | `get_run` |
| `cancel_drill` | `cancelled` within one checkpoint (about 30 s), cleanup verified, partial rows kept | pass/fail | manifest, audit |
| `recovery_drill` | `recovery_cleanup` in the next transaction's audit, verified; killed run `aborted` | pass/fail | audit, `get_run` |
| `autocal_restored` | `CM` state after the run = before | pass/fail | `*LRN? 31` |
| `bti_n` | BTI exponent n | +-0.05 of the reference | lab reference |
| `igzo_dvth`, `hci_m`, `silc_ratio` | stress degradation | recorded | lab data |
| `tddb_tbd` | time to breakdown | one sample interval of the compliance row | the run |
| `bdv` | breakdown voltage of the ramp | +-5 % of the reference | EasyEXPERT |
| `breakdown_search` | diode breakdown voltage | +-5 % of the reference | datasheet / EasyEXPERT |
| `bti_cleanup`, `igzo_cleanup`, `hci_cleanup`, `silc_cleanup`, `tddb_cleanup`, `bdv_cleanup`, `search_bd_cleanup` | every run `verified: lop` | pass/fail | manifests |

- TODO(verify) at this stage: the timer runs on over hours without a reset (sampling `time_source` stays
  `timestamp`), host overhead per hold block, auto-calibration over hours with outputs off.

## 5. Abort criteria

- A cancel that does not stop within two checkpoints; a recovery cleanup that is not verified; a fault latched;
  the lock still held after a drill; `CM` not restored.
- Gate current at its compliance in a BTI read (premature breakdown: runbook `stress-degradation-unexpected`).
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human; never clear a fault.

## 6. Record

- Hardware: the stage record of the drills (`uv run b1500 bringup record L9 --run H... --run H... --operator
  NAME`; the human adds the observations) and one recipe record each (`--recipe reliability.bti_sms` and so on, with
  `--reference` values where the lab has them). The human reviews them and moves them to `validation/hw/stage-l9.yaml`,
  `validation/hw/reliability.bti_sms.yaml`, `validation/hw/igzo.bias_stress.yaml`, `validation/hw/reliability.hci.yaml`,
  `validation/hw/reliability.silc.yaml`, `validation/hw/reliability.tddb_cvs.yaml`, `validation/hw/dielectric.bdv.yaml`,
  `validation/hw/basic.breakdown_search.yaml`.
- Simulator rehearsal (`timing: scaled` scenario `nmos_bti`): the drills run the same way on `S...` runs;
  no record from them; say which records hardware drafts.
