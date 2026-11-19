---
stage: S0
title: Physical prerequisites - interlock, shield box, cables, EasyEXPERT records, GPIB 17, FLEX control released
recipes: []
checks:
  - {id: interlock_test, quantity: interlock_test, reference: EasyEXPERT Interlock Open/Close and High Voltage LED tests, text: both pass}
  - {id: interlock_state, quantity: interlock_state, reference: owner decision, text: open for all work up to 42 V (recorded)}
  - {id: self_test, quantity: self_test, reference: EasyEXPERT Start Self Test, text: mainframe and every module pass}
  - {id: self_cal, quantity: self_cal, reference: EasyEXPERT Module Self Calibration, text: completed without error}
  - {id: module_list, quantity: module_list, reference: EasyEXPERT Modules tab, text: slot and model recorded}
  - {id: firmware, quantity: firmware, reference: EasyEXPERT Main Frame tab, text: recorded}
  - {id: line_frequency, quantity: line_frequency, unit: Hz, reference: EasyEXPERT Main Frame tab, text: recorded (50 Hz assumed until then)}
  - {id: cables, quantity: cables, reference: station cabling, text: 'triax per SMU, GNDU on 16493L, Guard free'}
  - {id: gpib_settings, quantity: gpib_settings, reference: Keysight Connection Expert on the B1500A, text: 'address recorded, System Controller No, Auto-discover No'}
  - {id: flex_released, quantity: flex_released, reference: B1500A screen, text: 'EasyEXPERT exited, Start EasyEXPERT button shown or minimized'}
  - {id: dut_set, quantity: dut_set, reference: OD-2 bring-up DUT set, text: standards and references at hand}
version: 1
---

# S0 - Physical prerequisites

Everything in this stage is done by the human at the instrument. You hand the steps over, wait for the human's own
confirmation in chat, and talk to the instrument not at all: no probe, no plan, no run.

## 1. Preconditions

- The lab PC is set up with `docs/deployment-windows.md` up to `uv sync --frozen`; `uv run b1500 doctor` shows no
  FAIL (it checks the PC only; the configuration is still the simulator example).
- `uv run b1500 bringup status` names S0 as the next stage.
- The B1500A is powered on; the DUT is disconnected (probes lifted or fixture socket empty): self-test and
  self-calibration need open measurement terminals (UG p142 (3-64) "Open the measurement terminals").

## 2. Physical steps (human)

Give the human this block in one message; they confirm each item in chat (in a simulator rehearsal they may simply
answer "done"). Never mark an item done yourself.

1. Interlock: find how the rear-panel Interlock terminal is wired (shield-box door switch, test fixture, or not
   wired). Run the Interlock Open/Close test and the High Voltage LED test in EasyEXPERT (Configuration window,
   Main Frame tab; UG p142 (3-64) "Interlock Open/Close test"), once a day after power-on.
2. Interlock state: keep the interlock circuit open for all bring-up work. With it open the B1500A limits SMU
   outputs to 42 V (EX p368 (4-74) "Interlock"), the physical backstop under the kernel's own 42 V / 100 mA ceiling.
   If closing the shield box would close it, unplug the interlock cable at the B1500A (owner's decision; record it).
3. Shield box: closed and light-tight during measurements, shield connected as the station requires.
4. Cables: a triaxial cable on every SMU a pin map will use; the GNDU on its own 16493L cable; no BNC adapter in a
   low-current path; Guard connected to nothing (UG p93 (3-15) "Guard"). Note cable type, length, Guard and Kelvin
   per module alias for `topology.cables` (the human enters them at L0).
5. EasyEXPERT records (Configuration window): model, firmware, EasyEXPERT revision and line frequency (Main Frame
   tab); the slot list (Modules tab); run Start Self Test and Module Self Calibration; note the auto-calibration
   setting and the SMU Zero Cancel state (it shifts low-current offsets).
6. GPIB settings on the B1500A (Keysight Connection Expert, GPIB0, Change Properties): GPIB address (factory 17),
   System Controller No, Auto-discover No; a change needs a reboot (PG p23 (1-3) "System Controller"). With a
   USB/GPIB adapter the guide recommends an even address if serial-poll errors appear.
7. Release the instrument for FLEX control: File > Exit in EasyEXPERT, then leave the Start EasyEXPERT button on
   the screen or minimized to the task bar; its service must keep running for external control (PG p23 (1-3)
   "Start EasyEXPERT"; WG p39 (2-17)).
8. Bring-up DUT set at hand (owner decision OD-2): 100 kOhm and 1 MOhm metal-film resistors (1 %) with fresh DMM
   readings; a known silicon diode with its data sheet; a known-good n-MOSFET with EasyEXPERT reference exports of
   the same day (Id-Vg, Id-Vd, Ig-Vg); later stages add a 1 Ohm Kelvin standard, a 100 pF standard or MOS-C, a FeFET
   and a FeCap.

## 3. Agent steps

1. `uv run b1500 bringup status`: confirm that S0 is next; read this file.
2. Send the human the block of section 2 and stop the turn; one block per message.
3. When the human reports results, compare them with section 4. Ask again for anything missing; never fill in a
   value they did not give.
4. Run nothing against the instrument here (`uv run b1500 doctor` checks only the PC and may be repeated).
5. On hardware, when every item is confirmed: `uv run b1500 bringup record S0 --operator NAME` drafts the
   checklist record (`--note "TEXT"` carries the values the human reported); tell the human to review it.
6. Then move on to L0 (`stages/l0-probe-config.md`) only after the human's own "go on".

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `interlock_test` | Interlock Open/Close and High Voltage LED tests pass | pass/fail | EasyEXPERT |
| `interlock_state` | open (outputs limited to 42 V) | recorded | owner decision |
| `self_test` | mainframe and every module pass | pass/fail | EasyEXPERT |
| `self_cal` | completed without error | pass/fail | EasyEXPERT |
| `module_list` | slot, model per slot (lab: SPGU 1, WGFMU 2, HRSMU 3-4, MPSMU 5-6, MFCMU 7) | recorded | Modules tab |
| `firmware` | firmware revision (the lab's: A.06.02) | recorded | Main Frame tab |
| `line_frequency` | 50 Hz or 60 Hz | recorded | Main Frame tab |
| `cables` | triax per SMU, GNDU on 16493L, Guard free | pass/fail | station |
| `gpib_settings` | address (17), System Controller No, Auto-discover No | pass/fail | Connection Expert |
| `flex_released` | EasyEXPERT exited, Start EasyEXPERT button shown or minimized | pass/fail | B1500A screen |
| `dut_set` | standards and references present | pass/fail | owner |

- FLEX control after EasyEXPERT (ATV-3): the guide's "Before Starting" steps above; at L0 the FlexGUI window opens
  on the first GPIB command (PG p24 (1-4) "FlexGUI"). Fallback: follow the current guide's steps and record them.

## 5. Abort criteria

- The interlock or High Voltage LED test fails; a self-test or self-calibration error; a Guard conductor touches
  anything; a damaged or unknown cable; a module the human did not expect; EasyEXPERT cannot be exited.
- On any of them: stop, report which item failed, and wait for the human. Nothing was switched on, so no
  `safe_shutdown` is needed in this stage; never continue to L0.

## 6. Record

- Hardware: one stage record (`uv run b1500 bringup record S0 --operator NAME`) in `work/bringup/records/`; the
  human fills `observed` and `passed` of each item from their own observations while reviewing it, then moves it
  to `validation/hw/stage-s0.yaml`.
- Simulator rehearsal: no record; say that on hardware this stage drafts `stage-s0`.
