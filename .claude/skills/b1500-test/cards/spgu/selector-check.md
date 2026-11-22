---
id: selector-check
title: 16440A selector check — every declared output through SMU, PGU, PGU open and back to rest, read back
family: spgu
intent: [selector check, 16440A, ERSSP, selector wiring, relay check, SEL1, SEL2, PGU open, route check]
recipes: [system.selector_check]
device_types: []
modules: []
routes: [selector_16440a:smu, selector_16440a:pgu, selector_16440a:pgu_open]
bringup_stage: L7
status: sim_validated
confirmation: conditional
knowledge: [knowledge/11-switching-routing.md#the-16440a-selector, knowledge/11-switching-routing.md#selector-check-and-recording-the-wiring, knowledge/11-switching-routing.md#cleanup-and-verification, knowledge/11-switching-routing.md#guard-and-rules, knowledge/03-probe-station-wiring.md#scuu-gswu-and-the-16440a-selector]
manual: [PG p433 (4-115) "ERSSP", PG p434 (4-116) "connection state", PG p419 (4-101) "ERMOD", PG p154 (2-66) "semiconductor relay", SEL p12 (6) "LEDs"]
debug: [cleanup-failed-fault, errx-codes, visa-no-connection]
sources: [blueprint v2 3.3 (system.selector_check), 2.6 (cleanup steps 5 and 8), 7.4 (stage L7), lwp SPGU_pulse.m]
version: 1
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# 16440A selector check

## 1. Purpose and applicable devices

Do the station's 16440A selectors follow the B1500A? Every declared selector output (station `switches` of kind
`selector_16440a`, not recorded absent) is stepped on its own: SMU on, PGU on, PGU open (CH 1 only, ports 0 and 2),
then back to its rest state (open), each state set with `ERMOD 1` + `ERSSP port,status` and read back with `ERSSP?`.
Each state is held `dwell_s` so the human at the station hears the relay and sees the front-panel LED change.

- Bring-up stage L7 (map the selector wiring, verify every state) and after any selector re-cabling, a lost control
  cable or a `RouteNotVerified` run failure.
- Nothing is sourced and no output is switched on: it is safe with any DUT landed or none.
- Not for: checking an SCUU or ASU (their paths are read back by every run's cleanup); pulsing a device (SPGU pulse
  cards, WP9.3+); measuring through a selector (cards whose recipes route their roles).

## 2. Wiring, pin map, modules

| terminal | role | module | notes |
|---|---|---|---|
| none | no DUT roles | 16440A selectors SEL1 (ports 0, 1) and SEL2 (ports 2, 3) via the digital I/O port | SMU inputs Force only; inputs may still be unrecorded |

- Any existing pin map may be named (no role binds); the example uses `fefet-sel`. No DUT profile.
- The station example declares `SEL1`/`SEL2` `present: true`, `certainty: unverified`, inputs `null`. The check runs
  without recorded inputs; that is how the human records them at L7.
- Routes per phase: one phase per step and output, e.g. `check-01: SEL1.OUT1 -> smu`, `check-02: SEL1.OUT1 -> pgu`,
  `check-03: SEL1.OUT1 -> pgu_open`, `check-04: SEL1.OUT1 -> open (rest)`, then `SEL1.OUT2` (no PGU open on CH 2),
  `SEL2.OUT1`, `SEL2.OUT2`; cleanup: every declared output to rest, verified.

## 3. Pre-run checklist

- `station_status` clean (no fault, no active run); its `switches` show every selector output at rest (if one is
  `off rest`, run `safe_shutdown` first).
- The human is at the station to listen to the relays and watch the selector LEDs (and the 16445A adapter powered).
- No other program drives the digital I/O port (EasyEXPERT closed, bring-up S0).

## 4. Recipe and parameters

| param | default | recommended | recipe range | why | effect |
|---|---|---|---|---|---|
| `mode` | `route_only` | `route_only` | `route_only` | fixed kind mode | no source, routes only |
| `pgu_open` | true | - | - | also check the CH 1 semiconductor relay | adds one state on ports 0 and 2 |
| `dwell_s` | 0.5 s | 0.2..2 s | 0..10 s | time to hear and see each state | longer run; no effect on the read-back |

Example plan (validated on the simulator by `b1500 dev lint-skills`):

```yaml
recipe_id: system.selector_check
params: {}
pin_map: fefet-sel
sim_scenario: lab_station
```

## 5. Limits and confirmation

- No outputs: the compiled envelope has no channel (the guard refuses `CN` and every source) and the kind requires
  `LOP?` all off and `SPST?` 0 before the first route. Only listed routes or rest states pass the guard. Destructive:
  no.
- `unverified_topology` (R-ROUTE-02) while the selectors are `certainty: unverified`, and `unverified_pin_map` for
  an unverified pin map: the example plan needs confirmation. On hardware also `first_hw_run` until the recipe is
  `hw_validated`, and a selector of unknown presence is blocked (R-ROUTE-01: the human records `present: true`).
- Pre-execute (R-ROUTE-01): every declared selector port must read its rest state.
- About 4 x `dwell_s` per CH 1 output and 3 x per CH 2 output: seconds, synchronous.

## 6. Quality criteria

- Pass: every state read back as set (`kind_result.states_verified` = the number of steps), the cleanup verified
  and `cleanup.switches_after` open for every declared output.
- A read-back mismatch stops the run (`RouteNotVerified`, the message names output, read and set state); never
  repeat it blindly: ask the human about the control cable, the adapter power and the LEDs.
- The human's observation counts: a step whose relay did not click or whose LED did not change is a failure even
  when `ERSSP?` agrees (it reports the commanded state, `TODO(verify)` at L7).

## 7. Analysis method

- No `analyze_run` method (no data table). Report from `get_run`: `kind_result` (`outputs_checked`,
  `states_verified`, `sequence`), the audit's `routes` checkpoints (phase, route, read-back), `cleanup.verified` and
  `cleanup.switches_after`, the backend (SIMULATED flag) and the human's observations per output.

## 8. Expected result shape

| item | expected | red flags |
|---|---|---|
| read-back per step | the state just set | any other state; an `ERSSP?` timeout |
| relays / LEDs (hardware) | one click and LED change per step | silence or no LED (adapter power, control cable) |
| cleanup | verified, every output `open` | `cleanup_unverified`, fault latched |

## 9. Common failures → debug

| symptom | likely cause | first safe check | runbook |
|---|---|---|---|
| `RouteNotVerified` | stuck relay, lost control, wrong control-cable chain | `safe_shutdown`; human checks cable, adapter, LEDs | `cleanup-failed-fault` |
| plan blocked: output not at rest | earlier run or human left it switched | `safe_shutdown`, then `station_status` | `cleanup-failed-fault` |
| fault latched after the run | a selector would not return to rest | keep the fault; human inspects the selector | `cleanup-failed-fault` |
| instrument error 120 / errors drained | control mode refused, wrong port | `station_status` errors | `errx-codes` |
| `busy` / bus not reachable | EasyEXPERT or another client holds the bus | close the other client | `visa-no-connection` |

## 10. Validation record

| backend | date | scenario or station | DUT | run_id | result | reviewer |
|---|---|---|---|---|---|---|
| sim | 2026-11-22 | lab_station | none | S20261122T081842Z-4ef0 | tier needs_confirmation (unverified_pin_map, unverified_topology); 14 states read back on 4 outputs; cleanup verified (sim_state), every selector output open | - |
| hw | pending (bring-up stage L7) | - | - | - | - | - |

Sim rows: the example plan run through `B1500Service` with temporary `B1500_CONFIG_DIR`/`B1500_DATA_DIR`; that run
folder was not kept. Hardware record: `validation/hw/system.selector_check.yaml` (reviewed by a human after bring-up
stage L7, skill `b1500-bringup`; drafts only from hardware `H...` runs, never from simulator `S...` runs). Until it
exists every hardware plan needs `first_hw_run` confirmation.
