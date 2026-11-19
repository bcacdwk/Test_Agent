---
stage: L1
title: SMU zero - outputs safe at 0 V, cleanup verified, one mid-run stop, CLI and MCP coexist, self-test/cal
recipes: [basic.contact_resistor, system.self_test, system.self_cal]
checks:
  - {id: cleanup_lop, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: floor, quantity: noise_a_I, unit: A, reference: 'range floor; the simulator assumes 1e-13 A (HRSMU), 1e-11 A (MPSMU)', text: recorded per SMU}
  - {id: open_path, quantity: resistance, method: resistance, unit: Ohm, reference: nothing connected, text: 'classification open at +-0.1 V'}
  - {id: shutdown_drill, quantity: shutdown_drill, reference: human observation, text: 'run stopped, cleanup verified, lock free, no fault'}
  - {id: coexistence, quantity: coexistence, reference: human observation, text: CLI status answers while the agent is idle}
  - {id: lop_positive_control, quantity: positive_control, reference: run manifest cleanup.positive_control, text: 'every connected slot non-00 right after CN'}
  - {id: self_test_result, recipe: system.self_test, quantity: result, reference: '*TST? result (0 = pass)', tolerance: {max_abs: 0.5}, text: result 0}
  - {id: self_cal_result, recipe: system.self_cal, quantity: result, reference: '*CAL? result (0 = pass)', tolerance: {max_abs: 0.5}, text: result 0}
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# L1 - SMU zero, cleanup, interruption

The first stage that switches outputs on, at 0 V on open terminals. Zero check: `basic.contact_resistor` with
`v_start=0` and `v_stop=0` (a 21-point staircase that stays at 0 V) on every SMU; the dedicated `system.zero_check`
recipe replaces it when the SMU work package brings it. Every hardware plan is `needs_confirmation`
(`first_hw_run`, plus `unverified_pin_map` while a map is unverified): summary, stop, the human's own consent, one
run per consent (skill `b1500-test`).

## 1. Preconditions

- L0 signed off; `uv run b1500 bringup status` names L1; `station_status` clean (no fault, no lock holder, no run).
- `config/local/` adopted; `uv run b1500 config check` valid with backend visa.

## 2. Physical steps (human)

1. DUT disconnected (probes lifted or socket empty) with the production cabling; shield box closed; interlock open.
2. Adopt the agent's proposals from `work/bringup/` (agent step 2): one pin map `open-smuN` per SMU slot (`a` = the
   slot, `b` = `GNDU`, `certainty: unverified`) and the DUT profile `open-circuit` (`device_type: resistor`,
   terminals `a`/`b` at 1 V, 1 mA): `uv run b1500 config adopt FILE --as pinmap` and `--as dut`.
3. Shutdown drill (agent step 6), in your own PowerShell window: `uv run b1500 run --confirm PLAN_ID` (human
   only) with the long 0 V plan the agent validated; press Ctrl+C about 10 s after it starts measuring. Repeat once
   and, instead of Ctrl+C, run `uv run b1500 shutdown --reason "L1 drill"` in a second window.
4. Coexistence: while the coding agent is open and idle, run `uv run b1500 status` and `uv run b1500 lock status`
   in a second window.

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status`.
2. Write the proposals of physical step 2 as files under `work/bringup/` (copies of
   `config/pinmaps/resistor-2t.example.yaml` and `config/duts/resistor-generic.example.yaml` with the slot and
   limits changed); hand the adoption to the human and stop.
3. Self-test, then self-calibration, with open terminals: `validate_plan` of `system.self_test` (any adopted pin
   map, e.g. `open-smu3`), tier `needs_confirmation` (`system_self_test`, `first_hw_run`); ask the human to confirm
   the open terminals in the same message as the summary; stop; after consent `run_confirmed_plan`. Same for
   `system.self_cal`. Report `kind_result` (result, failed units) from `get_run`.
4. Per SMU slot N: `validate_plan` of `basic.contact_resistor` with `params {v_start: 0, v_stop: 0}`, pin map
   `open-smuN`, DUT profile `open-circuit`; summary, stop, consent, `run_confirmed_plan`; `get_run` with `summary`,
   `quality`, `audit`. Expect `completed_with_flags` (the resistance analysis needs three distinct voltages).
5. Per SMU: the same request without the 0 V params (+-0.1 V, the default) on the open path: classification `open`.
6. Drill: `validate_plan` of the 0 V request with `params {v_start: 0, v_stop: 0, points: 201, integration: long}`
   (about 65 s) and hand the plan id to the human for physical step 3; afterwards `get_run` of both runs,
   `safe_shutdown("L1 after drill")`, `station_status`.
7. Ask for physical step 4 and note the answers.
8. Hardware: `uv run b1500 bringup capture H...` for one 0 V run per module type (HRSMU, MPSMU): FMT 1 blocks
   for the parser fixtures; then the records of section 6.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `cleanup_lop` | every run's cleanup `verified: lop`, all slots `00`, error queue empty | pass/fail | run manifests |
| `floor` | quality noise of `a_I` per SMU; sanity: HRSMU below 1 pA, MPSMU below 100 pA | recorded | `quality.json` |
| `open_path` | resistance classification `open` at +-0.1 V, statuses `N` | recorded | `resistance` |
| `shutdown_drill` | Ctrl+C: outcome `aborted`, audit `AB`, `DZ`, `CL`, `ERRX?`, `LOP?` all `00`; `shutdown` from a second window: the run stops at its next checkpoint or the call answers `busy` naming the holder; either way cleanup verified, lock free, no fault | pass/fail | audit, `uv run b1500 lock status` |
| `coexistence` | `status` answers while the agent's server is idle | pass/fail | human |
| `lop_positive_control` | non-`00` on every connected slot right after `CN`, every run | recorded | manifest, audit |
| `self_test_result` | `kind_result.result` 0, no failed unit | 0 | `*TST?` (PG p540 (4-222) "open the measurement terminals") |
| `self_cal_result` | `kind_result.result` 0 | 0 | `*CAL?` |

- 0 V runs: every status letter `N`; mean current within the sanity bounds of `floor` (record it; the owner
  tightens the bounds after the first runs).
- `LOP?` (ATV-1): after `CL` every slot reads `00`, idle SPGU/WGFMU/CMU slots too (ATV-23; record their codes).
  Positive control: right after `CN` the transaction reads `LOP?` and needs a non-`00` code on every connected slot
  (evidence: run manifest `cleanup.positive_control`, audit checkpoint `lop_positive_control`). Fallback when an
  idle slot reads non-`00` or the control fails: verification through `*LRN? 0` (a code change); stop here.
- `*LRN? 31` raw text of the pre-execute snapshot recorded (async auto-calibration restore).

## 5. Abort criteria

- A status letter other than `N` at 0 V; a mean current above the sanity bound; a classification other than
  `open` on the open path.
- Cleanup `unverified`, a latched fault, a non-`00` `LOP?` code after cleanup, an `ERRX?` entry (e.g. 202/203).
- A `00` slot right after `CN` (positive control failed: the run ends `cleanup_unverified`, fault latched before
  any level is applied).
- After the drill an output still on or the lock still held.
- Self-test or self-calibration result not 0.
- On any of them: `safe_shutdown(reason)`, report, follow skill `b1500-debug`, wait for the human; never clear a
  fault yourself (the latch is cleared only by the human with `uv run b1500 fault clear --by NAME`).

## 6. Record

- Hardware: the stage record from the 0 V, +-0.1 V and drill runs
  (`uv run b1500 bringup record L1 --run H... --run H... --operator NAME`; the human adds the drill and
  coexistence observations while reviewing), and one recipe record each for `system.self_test` and
  `system.self_cal` (`uv run b1500 bringup record L1 --run H... --recipe system.self_test`). The human reviews them
  and moves them to `validation/hw/stage-l1.yaml`, `validation/hw/system.self_test.yaml`,
  `validation/hw/system.self_cal.yaml`; FMT fixtures to `tests/fixtures/hw/`.
- Simulator rehearsal: runs are `S...` and every value SIMULATED; `bringup record` refuses them: no record, no
  fixture; say which records the stage would draft on hardware.
