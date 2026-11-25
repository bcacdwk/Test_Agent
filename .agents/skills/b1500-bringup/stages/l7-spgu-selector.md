---
stage: L7
title: HV-SPGU and 16440A selector - selector map and wiring record, pulses into 1 MOhm, FeFET program/read against the dual sweep, switching kinetics, charge pumping
recipes: [system.selector_check, spgu.pulse_train, spgu.alwg_sequence, fefet.dual_sweep_mw, fefet.pulse_write_read, spgu.program_smu_read, fefet.switching_kinetics, mosfet.charge_pumping]
checks:
  - {id: selector_states, recipe: system.selector_check, quantity: states_verified, method: kind_result, reference: 'the plan''s steps: 4 per CH 1 output, 3 per CH 2 output', text: 'ERSSP? read back as set in every state (= the steps)'}
  - {id: selector_cleanup, recipe: system.selector_check, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, every selector output open'}
  - {id: relays_observed, quantity: relays_observed, reference: 'the human at the selectors (relay click, front-panel LED)', text: one click and LED change per step on every output}
  - {id: wiring_recorded, quantity: wiring_recorded, reference: 'config/local/station.yaml switches, adopted by the human (ATV-28)', text: 'every selector input the pin maps use recorded (no null); certainty verified only after the scope check'}
  - {id: pulse_level_1meg, quantity: pulse_level_1meg, unit: V, reference: 'oscilloscope (10:1 probe) across the 1 MOhm load, SER 1 MOhm', text: 'peak = v_peak +-5 % (ATV-20)'}
  - {id: pulse_level_ser50, quantity: pulse_level_ser50, unit: V, reference: 'oscilloscope across the 1 MOhm load, SER 50 Ohm', text: 'peak = 2 x v_peak +-5 % (open-load doubling, ATV-20)'}
  - {id: train_spst, recipe: spgu.pulse_train, quantity: spp_fallbacks, method: kind_result, reference: 'ATV-19: SPST? reads 0 at the end of the count', tolerance: {max_abs: 0.5}, text: '0 (every train ended by itself)'}
  - {id: train_waited, recipe: spgu.pulse_train, quantity: waited_s, method: kind_result, unit: s, reference: kind_result output_s_planned of the same run, text: recorded (planned output time plus polling)}
  - {id: train_cleanup, recipe: spgu.pulse_train, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, SPST? 0, selector at rest'}
  - {id: alwg_spst, recipe: spgu.alwg_sequence, quantity: spp_fallbacks, method: kind_result, reference: 'ATV-19 for ALWG sequences', tolerance: {max_abs: 0.5}, text: '0 (every sequence output ended by itself)'}
  - {id: alwg_cleanup, recipe: spgu.alwg_sequence, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, SPST? 0, selector at rest'}
  - {id: dual_sweep_mw, recipe: fefet.dual_sweep_mw, quantity: memory_window, method: memory_window, unit: V, reference: 'EasyEXPERT or lab loop of the same FeFET, if any', text: recorded (the DC reference of pulse_mw)}
  - {id: dual_sweep_cleanup, recipe: fefet.dual_sweep_mw, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run'}
  - {id: pulse_mw, recipe: fefet.pulse_write_read, quantity: memory_window, method: memory_window_pulse, unit: V, reference: 'dual_sweep_mw of the same FeFET (--reference pulse_mw=<V>)', tolerance: {rel: 0.2}, text: 'MW consistent with the dual sweep: same sign, +-20 %'}
  - {id: pulse_routes, recipe: fefet.pulse_write_read, quantity: routes, method: kind_result, reference: 'the plan''s routes per phase', text: 'PGU before and SMU after every operation, rest at the end'}
  - {id: pulse_rw_cleanup, recipe: fefet.pulse_write_read, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, selector at rest'}
  - {id: spot_ratio, recipe: spgu.program_smu_read, quantity: current_ratio, method: memory_window_pulse, unit: '1', reference: 'the Id ratio of the pulse_mw reads at vg_read', text: recorded (erase over program read current)}
  - {id: spot_cleanup, recipe: spgu.program_smu_read, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, selector at rest'}
  - {id: kinetics_tau0, recipe: fefet.switching_kinetics, quantity: tau0, method: switching_kinetics_fit, unit: s, reference: 'lab switching data of the film, if any', text: recorded with beta and va (NLS fit)}
  - {id: kinetics_cleanup, recipe: fefet.switching_kinetics, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, selector at rest'}
  - {id: cp_qcp, recipe: mosfet.charge_pumping, quantity: qcp, method: charge_pumping, unit: C, reference: 'Icp linear in f over the frequency list', text: recorded with nit (fit window and r2)}
  - {id: cp_cleanup, recipe: mosfet.charge_pumping, quantity: cleanup, reference: run manifests, text: 'verified: lop on every run, SPST? 0, selector at rest'}
version: 1
---

# L7 - HV-SPGU and 16440A selector

First the selectors (SEL1 ports 0/1, SEL2 ports 2/3, card `selector-check`) without any output, then the human records
the selector input wiring (ATV-28), then SPGU pulses into a known 1 MOhm load (card `spgu-pulse-train`; ATV-19 `SPST?`,
ATV-20 SER levels), then the lab FeFET: DC loop, pulse program/read through `SEL1.OUT1` (cards `fefet-dual-sweep-mw`,
`fefet-pulse-write-read`, `fefet-switching-kinetics`), and charge pumping on a MOSFET (card `charge-pumping`). The
SPGU has no compliance: every pulse plan is bounded and checked (R-SPGU-01, R-PULSE-01..03). FeFET endurance and
retention are L9.

## 1. Preconditions

- L4 (L5, L6 when signed off) done; `uv run b1500 bringup status` names L7; `station_status` clean: no fault, no
  run, every selector output at rest, `SPST?` 0 (`uv run b1500 doctor --probe` lists `ERMOD?`/`ERSSP?`/`SPST?`).
- 16445A adapter powered, control cable B1500A digital I/O -> SEL1 -> SEL2; station `switches` `present: true`.
- A 1 MOhm resistor (DMM reading), an oscilloscope with a 10:1 probe; the lab FeFET (DUT profile `fefet-lab`
  reviewed: gate pulse envelope against the film's coercive voltage); a MOSFET with a body contact for charge pumping.

## 2. Physical steps (human)

1. Cable each SMU Force to a selector SMU input (Sense stays open) and each SPGU channel to a PGU input; note which
   channel feeds which input and which pad each output reaches. Stand at the selectors for agent step 2: report per
   output whether every state clicked and changed its LED.
2. Give the agent that wiring in chat; check its proposal, then adopt it yourself:
   `uv run b1500 config adopt work/bringup/station.proposed.yaml --as station` (still `certainty: unverified`).
3. Land the 1 MOhm load from the `SEL1.OUT1` pad to ground with the scope probe across it; adopt the proposed pin
   map `sel1-load` and DUT profile `r1m-pulse` (`--as pinmap`, `--as dut`). Read the scope during agent step 4.
4. After agent step 4: only if the scope showed the pulses on the right pad, have the agent mark the selectors
   `certainty: verified` in the proposal (or edit it yourself) and adopt it again (as in step 2).
5. Land the FeFET with its gate probe straight on SMU3 Force (pin map `fefet-direct`, proposed, adopted) for agent
   step 6; then move the gate probe back to `SEL1.OUT1` (pin map `fefet-sel`) and confirm.
6. For agent step 9 land the MOSFET on pin map `mosfet-cp` (gate `SEL1.OUT1`, bulk SMU4) with a DUT profile you
   reviewed (copy of `nmos-cv`).

## 3. Agent steps

1. `uv run b1500 bringup status`; `station_status`; `uv run b1500 doctor --probe` (read-only).
2. `system.selector_check` (pin map `fefet-sel`, `params {dwell_s: 1.0}`): validate (`unverified_topology`,
   `first_hw_run`), summary, stop, consent, run; `get_run` `kind_result` and the audit `routes`; collect the human's
   observation per output. A read-back mismatch: abort criteria.
3. Wiring: `uv run b1500 bringup propose-station`; write the inputs the human gave into
   `work/bringup/station.proposed.yaml` (`switches[].ports.OUTn.inputs`), show the diff, hand over the adoption,
   stop. Propose `sel1-load`, `r1m-pulse` (gate `impedance: resistive`, `min_series_ohm: 1.0e+6`, pulse envelope 5 V)
   and `fefet-direct` (gate 3, drain 4, source GNDU) under `work/bringup/`.
4. `spgu.pulse_train` on `sel1-load`: default train (4 V, 1 us, 1000 pulses, `load_ohm` 1 MOhm), then
   `{v_peak: 2.0, load_ohm: 50}`; each validated, consented, run. The human reads the peaks; `kind_result`
   `spp_fallbacks`, `waited_s` vs `output_s_planned`. Then `spgu.alwg_sequence` (card example) the same way.
5. After the human's re-adoption (physical step 4): `station_status` switches, `uv run b1500 config check`; the
   SMU path of the selector is checked by the reads of steps 7 and 8.
6. `fefet.dual_sweep_mw` on `fefet-direct` (card params): `memory_window` = the DC reference.
7. `fefet.pulse_write_read` on `fefet-sel` (card example; `soft_pulse` if outside the bands): MW from
   `memory_window_pulse`; `kind_result.routes`. Then `spgu.program_smu_read` (spot reads; `adhoc_recipe`):
   `current_ratio`. Report both as derived next to the DC MW.
8. `fefet.switching_kinetics` (card example, grid): `switching_kinetics_fit` (tau0, beta, va); compare with the
   pulse MW (a 1 us pulse at the program level should switch most of the film).
9. `mosfet.charge_pumping` on `mosfet-cp`: `charge_pumping` (Qcp, Nit, the fit window).
10. Report every value as derived (method, window, status counts, backend visa) and each human observation as such.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `selector_states` | every state read back as set (`kind_result.states_verified` = steps) | pass/fail | `get_run` |
| `relays_observed` | one relay click and LED change per step | pass/fail | the human |
| `wiring_recorded` | every used selector input recorded; `verified` only after the scope check (step 4) | pass/fail | station file |
| `pulse_level_1meg` | scope peak = `v_peak` (4 V) at SER 1 MOhm | +-5 % | oscilloscope |
| `pulse_level_ser50` | scope peak = 2 x `v_peak` (4 V for 2 V) at SER 50 Ohm | +-5 % | oscilloscope |
| `train_spst`, `alwg_spst` | `spp_fallbacks` 0 (`SPST?` fell to 0 by itself) | 0 | `kind_result` |
| `train_waited` | `waited_s` close to `output_s_planned` | recorded | `kind_result` |
| `dual_sweep_mw` | DC memory window (both branch Vths) | recorded | `memory_window` |
| `pulse_mw` | pulse MW, same sign as the DC MW | +-20 % of `dual_sweep_mw` | `memory_window_pulse` |
| `pulse_routes` | `c1 erase SEL1.OUT1->pgu; c1 read SEL1.OUT1->smu; ...; end rest` | pass/fail | `kind_result` |
| `spot_ratio` | erase/program read-current ratio well above 1 | recorded | `memory_window_pulse` |
| `kinetics_tau0` | tau0, beta, va of the NLS fit | recorded | `switching_kinetics_fit` |
| `cp_qcp` | Qcp (Icp linear in f), Nit | recorded | `charge_pumping` |
| `selector_cleanup`, `train_cleanup`, `alwg_cleanup`, `dual_sweep_cleanup`, `pulse_rw_cleanup`, `spot_cleanup`, `kinetics_cleanup`, `cp_cleanup` | every run `verified: lop`, every selector output open | pass/fail | manifests |

- TODO(verify) at this stage: `ERSSP?` reports the relay state, not only the command (ATV-18); the 10 ms selector
  settle time; `SPST?` 0 at the end of a count (ATV-19); `DZ`/`AB` do not stop a running SPGU (PG p142 (2-54)).

## 5. Abort criteria

- An `ERSSP?` read-back mismatch (`RouteNotVerified`), a silent relay, a selector off rest after a run, `SPST?`
  still 1 after a train (`spp_fallbacks` > 0 twice), a scope level off by more than 10 % or a pulse on the wrong pad.
- A FeFET read at compliance or a pulse MW of the opposite sign (runbooks `spgu-pulse-no-effect`,
  `spgu-selector-state`, `spgu-load-mismatch`).
- On any of them: `safe_shutdown(reason)`, report, skill `b1500-debug`, wait for the human; never raise a limit.

## 6. Record

- Hardware: one recipe record per recipe with checks, e.g. `uv run b1500 bringup record L7 --run H... --operator
  NAME` (with `--reference pulse_mw=<dual sweep MW>`), and the stage record (`--recipe` omitted, runs of steps 2 and
  4; the human adds `relays_observed`, `wiring_recorded` and the scope readings). The human reviews them and moves
  them to `validation/hw/stage-l7.yaml`, `validation/hw/system.selector_check.yaml`,
  `validation/hw/spgu.pulse_train.yaml`, `validation/hw/spgu.alwg_sequence.yaml`,
  `validation/hw/fefet.dual_sweep_mw.yaml`, `validation/hw/fefet.pulse_write_read.yaml`,
  `validation/hw/spgu.program_smu_read.yaml`, `validation/hw/fefet.switching_kinetics.yaml`,
  `validation/hw/mosfet.charge_pumping.yaml`.
- Simulator rehearsal (scenario `lab_station` or `fefet_lab`; null selector inputs take the scenario's cabling):
  no record from `S...` runs; say which records hardware drafts.
