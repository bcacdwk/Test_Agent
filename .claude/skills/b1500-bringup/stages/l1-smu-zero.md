---
stage: L1
title: SMU zero - outputs safe at 0 V, cleanup verified, one mid-run stop, CLI and MCP coexist, self-test/cal
recipes: [system.zero_check, system.self_test, system.self_cal]
checks:
  - {id: cleanup_lop, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: floor_smu3, quantity: smu3_floor, method: zero_floor, unit: A, reference: 'provisional sanity bound 1 pA: about 15x the lab HRSMU open-circuit 0.07 pA rms at 1 PLC (lwp/matlab_B1500/IdVg_test_20251004_*.csv, open probes); offset bound EX p339 (4-45)', text: recorded (lowest range)}
  - {id: floor_smu4, quantity: smu4_floor, method: zero_floor, unit: A, reference: 'provisional sanity bound 1 pA: about 15x the lab HRSMU open-circuit 0.07 pA rms at 1 PLC (lwp/matlab_B1500/IdVg_test_20251004_*.csv, open probes); offset bound EX p339 (4-45)', text: recorded (lowest range)}
  - {id: floor_smu5, quantity: smu5_floor, method: zero_floor, unit: A, reference: 'provisional sanity bound 100 pA (basis: none, no MPSMU floor on record); offset bound EX p339 (4-45)', text: recorded (lowest range)}
  - {id: floor_smu6, quantity: smu6_floor, method: zero_floor, unit: A, reference: 'provisional sanity bound 100 pA (basis: none, no MPSMU floor on record); offset bound EX p339 (4-45)', text: recorded (lowest range)}
  - {id: shutdown_drill, quantity: shutdown_drill, reference: human observation, text: 'run stopped, cleanup verified, lock free, no fault'}
  - {id: coexistence, quantity: coexistence, reference: human observation, text: CLI status answers while the agent is idle}
  - {id: lop_positive_control, quantity: positive_control, reference: run manifest cleanup.positive_control, text: 'every connected slot non-00 right after CN'}
  - {id: self_test_result, recipe: system.self_test, quantity: result, reference: '*TST? result (0 = pass)', tolerance: {max_abs: 0.5}, text: result 0}
  - {id: self_cal_result, recipe: system.self_cal, quantity: result, reference: '*CAL? result (0 = pass)', tolerance: {max_abs: 0.5}, text: result 0}
  - {id: self_test_s, recipe: system.self_test, quantity: tst_s, unit: s, reference: '*TST? query time in the run audit; the kind estimate (system.py)', text: recorded}
  - {id: self_cal_s, recipe: system.self_cal, quantity: cal_s, unit: s, reference: '*CAL? query time in the run audit; the kind estimate (system.py)', text: recorded}
  - {id: idle_lop, quantity: outputs_after, reference: 'run manifests cleanup.outputs_after (ATV-23)', text: 'every slot 00 after the cleanup, idle SPGU/WGFMU/CMU slots included; codes recorded'}
  - {id: bus_overhead, quantity: bus_call_s, unit: s, reference: 'slowest bus_open/lock/unlock/close dur_ms of the run audits (ATV-13)', text: 'recorded; the ATV-13 criterion of stage L0'}
version: 4
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# L1 - SMU zero, cleanup, interruption

The first stage that switches outputs on, at 0 V on open terminals. Zero check: `system.zero_check` (card
`zero-check`) holds every SMU of the pin map at 0 V and reads each 100 times on five fixed current ranges;
`zero_floor` gives the floor per SMU and range and the offsets (the M6 interim used `basic.contact_resistor` at 0 V). Every
hardware plan is `needs_confirmation` (`first_hw_run`, plus `unverified_pin_map` while a map is unverified):
summary, stop, the human's own consent, one run per consent (skill `b1500-test`).

## 1. Preconditions

- L0 signed off; `uv run b1500 bringup status` names L1; `station_status` clean (no fault, no lock holder, no run).
- `config/local/` adopted; `uv run b1500 config check` valid with backend visa.

## 2. Physical steps (human)

1. DUT disconnected (probes lifted or socket empty) with the production cabling; shield box closed; interlock open.
2. Adopt the agent's proposals from `work/bringup/` (agent step 2): the pin map `open-smus` (terminal `smuN` = the SMU
   in slot N, every SMU of the station, `certainty: unverified`) and the DUT profile `open-circuit` (terminals
   `smu1`..`smu10` at 0.1 V, 1 mA): `uv run b1500 config adopt FILE --as pinmap` and `--as dut`.
3. Shutdown drill (agent step 6), in your own PowerShell window: `uv run b1500 run --confirm PLAN_ID` (human
   only) with the zero-check plan the agent validated; press Ctrl+C about 10 s after it starts measuring. Repeat
   once and, instead of Ctrl+C, run `uv run b1500 shutdown --reason "L1 drill"` in a second window.
4. Coexistence: while the coding agent is open and idle, run `uv run b1500 status` and `uv run b1500 lock status`
   in a second window.

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status`.
2. Write the proposals of physical step 2 as files under `work/bringup/` (copies of
   `config/pinmaps/open-smus.example.yaml` listing exactly the station's SMU slots, and
   `config/duts/open-circuit.example.yaml`; YAML only, the adoption command never goes into a file); give the
   adoption command in chat, hand the adoption to the human and stop. Simulator rehearsal, or a write the harness
   refuses: show the YAML in chat instead, without a shell workaround. Then stop in a rehearsal too: no L1 plan,
   not even `validate_plan`, before the human reports the L1 physical steps done.
3. After that report: self-test, then self-calibration, with open terminals: `validate_plan` of `system.self_test`
   (any adopted pin map, e.g. `open-smus`), tier `needs_confirmation` (`system_self_test`, `first_hw_run`); ask the
   human to confirm the open terminals in the same message as the summary; stop; after consent
   `run_confirmed_plan`. Same for `system.self_cal`. Report `kind_result` (result, failed units) from `get_run`.
   The WGFMU library's own self-test and self-calibration belong to stage L8.
4. Zero check: `validate_plan` of `system.zero_check` with pin map `open-smus` and DUT profile `open-circuit`,
   default params (about 50 s); summary, stop, consent, `run_confirmed_plan`; `get_run` with `summary`, `quality`,
   `audit`; report the default `zero_floor` results (floor per SMU and range, offsets; derived; integration and
   samples; status counts) from your own `analyze_run(run_id, "zero_floor")`.
5. Once more with `params {integration: long, samples: 50}` (about 5.5 min, asynchronous: poll `get_run`): a
   white-noise floor falls as 1/sqrt(integration time) (16 PLC against 1 PLC: about 1/4), line and 1/f noise do not
   average; report the observed ratio per SMU and range (no prior value for this station).
6. Drill: hand the plan id of the default zero check (step 4) to the human for physical step 3; afterwards
   `get_run` of both drill runs, `safe_shutdown("L1 after drill")`, `station_status`.
7. Ask for physical step 4 and note the answers.
8. Hardware: one short zero check (`params {ranges: [1e-11], samples: 10}`, consent as in step 4) and
   `uv run b1500 bringup capture H...` of it (ten MM 1 FMT 1 blocks of HRSMU and MPSMU; with ASUs or an SCUU
   declared, their `*LRN? 62`/`81` read-backs) for the parser fixtures; then the records of section 6.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `cleanup_lop` | every run's cleanup `verified: lop`, all slots `00`, error queue empty | pass/fail | run manifests |
| `floor_smu3`, `floor_smu4` | HRSMU floor on its lowest range (10 pA, UG p69 (2-29); 1 PLC); sanity bound 1 pA | recorded (bound provisional) | `zero_floor` |
| `floor_smu5`, `floor_smu6` | MPSMU floor on its lowest range (1 nA, UG p63 (2-23); 1 PLC); sanity bound 100 pA | recorded (bound provisional) | `zero_floor` |
| `shutdown_drill` | Ctrl+C: outcome `aborted`, audit `AB`, `DZ`, `CL`, `ERRX?`, `LOP?` all `00`; `shutdown` from a second window: the run stops at its next checkpoint or the call answers `busy` naming the holder; either way cleanup verified, lock free, no fault | pass/fail | audit, `uv run b1500 lock status` |
| `coexistence` | `status` answers while the agent's server is idle | pass/fail | human |
| `lop_positive_control` | non-`00` on every connected slot right after `CN`, every run | recorded | manifest, audit |
| `self_test_result` | `kind_result.result` 0, no failed unit | 0 | `*TST?` (PG p540 (4-222) "open the measurement terminals") |
| `self_cal_result` | `kind_result.result` 0 | 0 | `*CAL?` |
| `self_test_s`, `self_cal_s` | `*TST?` and `*CAL?` query times (record fields `tst_s`, `cal_s` from the run audit) | recorded | audit |
| `idle_lop` | `LOP?` after every cleanup: all `00`, idle SPGU/WGFMU/CMU slots too (`outputs_after`) | recorded | manifest (ATV-23) |
| `bus_overhead` | slowest per-call bus open, lock, unlock or close of the runs (`bus_call_s`) | recorded | audit (ATV-13) |

- Zero-check runs: every status letter `N`; floors and offsets within the sanity bounds, recorded per range. Floor
  bounds are provisional criteria: HRSMU 1 pA is about 15x the lab HRSMU's open-probe noise (0.07 pA rms at 1 PLC,
  `lwp/matlab_B1500/IdVg_test_20251004_*.csv`), MPSMU 100 pA has no basis (no MPSMU floor on record). Offset
  bounds: the largest offsets EasyEXPERT's offset cancel accepts (EX p339 (4-45): +-400 fA on 10 pA, +-10 pA on
  1 nA). `TODO(owner)`: which floor and offset bounds per SMU type and range does the lab accept at L1? SMUs in other
  slots appear in the record as extra `smuN_floor` measurements.
- `LOP?` (ATV-1): after `CL` every slot reads `00`, idle SPGU/WGFMU/CMU slots too (ATV-23; record their codes).
  Positive control: right after `CN` the transaction reads `LOP?` and needs a non-`00` code on every connected slot
  (evidence: run manifest `cleanup.positive_control`, audit checkpoint `lop_positive_control`). Fallback when an
  idle slot reads non-`00` or the control fails: verification through `*LRN? 0` (a code change); stop here.
- `*LRN? 31` raw text of the pre-execute snapshot recorded (async auto-calibration restore).
- TODO(verify) (blueprint v2 7.6 items 1, 3, 4, 8, 10): the per-call bus cost (ATV-13, `bus_overhead`); `LOP?`
  as the verification (v1 ATV-1) and the idle SPGU/WGFMU/CMU codes (ATV-23, `idle_lop`); the real FMT 1 SMU blocks
  (`bringup capture`); the floor and offset per SMU range at this integration (they replace the simulator's noise
  assumptions); `*TST?` and `*CAL?` durations against the kind's 120 s / 60 s estimates (`self_test_s`,
  `self_cal_s`).

## 5. Abort criteria

- A status letter other than `N` at 0 V (the run stops at that point: something is connected or leaking); a floor
  or offset above the sanity bound.
- Cleanup `unverified`, a latched fault, a non-`00` `LOP?` code after cleanup, an `ERRX?` entry (e.g. 202/203).
- A `00` slot right after `CN` (positive control failed: the run ends `cleanup_unverified`, fault latched before
  any level is applied).
- After the drill an output still on or the lock still held.
- Self-test or self-calibration result not 0.
- On any of them: `safe_shutdown(reason)`, report, follow skill `b1500-debug`, wait for the human; never clear a
  fault yourself (the latch is cleared only by the human with `uv run b1500 fault clear --by NAME`).

## 6. Record

- Hardware: the stage record from the zero-check and drill runs
  (`uv run b1500 bringup record L1 --run H... --run H... --operator NAME`; the human adds the drill and
  coexistence observations while reviewing), the recipe record of `system.zero_check`
  (`uv run b1500 bringup record L1 --run H... --recipe system.zero_check`) and one each for `system.self_test` and
  `system.self_cal` (`--recipe system.self_test`). The human reviews them and moves them to
  `validation/hw/stage-l1.yaml`, `validation/hw/system.zero_check.yaml`, `validation/hw/system.self_test.yaml`,
  `validation/hw/system.self_cal.yaml`; FMT fixtures to `tests/fixtures/hw/`.
- Simulator rehearsal: runs are `S...` and every value SIMULATED; `bringup record` refuses them: no record, no
  fixture; say which records the stage would draft on hardware.
