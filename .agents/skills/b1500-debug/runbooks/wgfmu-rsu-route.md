---
id: wgfmu-rsu-route
title: WGFMU RSU route wrong or unread (RSU not at rest, 3001, signal missing at the DUT, SMU path through the RSU open)
maturity: seed
sources: [blueprint v2 2.6 (cleanup step 3, RSU states), 2.8 (R-ROUTE-01, R-PIN-01, R-WG-01), 11 (ATV-32), v2.1 plan 12 (R-RSU-01, WP21.13), WG p16 (1-4) "SMU mode", WG p19 (1-7) "RSU", WG p20 (1-8) "From SMU", WG p85 (4-15) "WGFMU_connect", WG p152 (4-82) "3001"]
---

# WGFMU RSU route wrong or unread

## Symptom

- `validate_plan` or the pre-execute check blocked on an RSU output (R-ROUTE-01: `RSU201.OUT` unread or not at its
  rest state; R-PIN-01: RSU target absent or its input not recorded; R-WG-01: a WGFMU role not on its RSU).
- A WGFMU run fails at `connect` with firmware code 3001 "RSU is not connected" (WG p152 (4-82)).
- The data look like an open circuit: the forced level never reaches the DUT (gate_V flat, drain current at the
  range's noise floor, `wgfmu.dc_spot` R above 1 GOhm, PUND without switching current).
- An SMU measurement through the RSU's SMU input (the DC reference of fast I-V, `mosfet-4t` on an RSU landing) reads
  the noise floor while the WGFMU path works (ATV-32).
- An SMU plan blocked by R-RSU-01 ("From SMU input"): the SMU is recorded on an RSU input and asks for more than
  +-25 V or 100 mA (WG p20 (1-8): the RSU would be damaged), or, on hardware, an RSU input is still `null`; a run
  refused `rsu_input_exceeded` by the guard.
- Cleanup: step 3 incomplete (a channel not disconnected), `cleanup.switches_after` without the RSU at rest,
  `cleanup_unverified`, fault latched.

## Likely causes

1. Cabling: a WGFMU channel on the other RSU (201 and 202 swapped) or on none (3001); the RSU output on the wrong
   pad. The library switches the RSU of the channel it is told; a swap moves the waveform to the other terminal.
2. SMU path: no SMU Force cable on the RSU's From SMU input, or another SMU than the station says
   (`switches[].ports.OUT.inputs.smu`); normally the RSU connects its SMU input to the output (WG p19 (1-7)).
3. Station or pin map: the pin map names an RSU output the station does not declare, or the RSU is `unverified`
   (every plan through it confirms `unverified_topology`). R-RSU-01: the level is above what the From SMU input
   takes (keep the SMU within +-25 V, or a landing on an SMU no RSU is cabled to), or L8 has not recorded the RSU
   inputs yet.
4. A crashed session or a foreign program (EasyEXPERT) left a channel connected: the pre-execute read disconnects
   every declared RSU channel; a refused disconnect leaves the output unread and the plan blocked.

## First safe checks

1. `get_run(run_id, include=[summary, audit])`: the `wgfmu_call` lines of `connect`/`disconnect` (rc, error text,
   3001), checkpoints `rsu_unread`, the manifest's routes per phase and `cleanup.switches_after`.
2. `station_status`: the switches part (each RSU output and its state), the fault latch, the WGFMU library line.
3. Re-validate the same request: the R-ROUTE-01/R-PIN-01 finding names the RSU output and the reason.
4. Path check with a known resistor: `wgfmu.dc_spot` on `resistor-wgfmu` (card `wgfmu-custom-waveform`): R within
   3 % = WGFMU path right; R above 1 GOhm = open (cable, pad or RSU). Same landing through the SMU input:
   `basic.contact_resistor` with the SMU the station records on that RSU: open = From SMU cable (ATV-32).
5. On visa, with the human's go: `uv run b1500 doctor --probe --wgfmu-session` (read-only: channel ids, status).

## Physical checks to ask the human

- Which WGFMU channel feeds which RSU (cable labels), and which pad each RSU output reaches.
- Which SMU Force cable is on each RSU's From SMU input; recabling only with the DUT lifted from the output
  (WG p20 (1-8) "From SMU").
- A scope (high impedance) on the RSU's V Monitor: the waveform during a run, 0 V after it (the monitor is grounded
  on the SMU path); a level after the run means the RSU stayed on the WGFMU path.

## Do not

- Load the library, switch an RSU or send FLEX yourself (no script, no ctypes, no `wgfmu.dll`): only the server's
  WGFMU phase and cleanup switch RSUs.
- Swap channel numbers or terminals in a plan to undo a cabling error; edit the station or a pin map (the human
  recables, or adopts a corrected proposal from `uv run b1500 bringup propose-station`).
- Get past R-RSU-01 by recording an RSU input as empty or as another SMU than the one cabled there: a wrong record
  is the one path to a damaged RSU.
- Report a value from a run whose RSU path is in doubt.

## Stop and call safe_shutdown

- 3001 twice on the same channel, a refused `disconnect`, an RSU not at rest after the cleanup, a latched fault
  (runbook `cleanup-failed-fault`): hand over to the human; only the human clears a fault.
