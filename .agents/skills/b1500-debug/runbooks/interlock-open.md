---
id: interlock-open
title: Interlock open, unknown, or interlock errors
maturity: seed
sources: [User Guide (PDF 55, 92), Programming Guide Ed. 15 status byte (PDF 76), errors 202/203 (PDF 577) and 310 (PDF 583), blueprint 4.2 R-IL-01 and 4.4]
---

# Interlock open

## Symptom

- `station_status` shows interlock `OPEN` (or `unknown` before a live read).
- Instrument error 202 "Interlock circuit must be closed", 203 "Cannot enable channel" or 310 "Interlock open
  operation error. Initialized."
- A request (often from a user) to "close the interlock" so a higher voltage can be used.

## Likely causes

1. Normal v1 state. With the interlock open the B1500A cannot apply more than 42 V (User Guide), and v1 has no
   high-voltage workflow: the code ceiling is 42 V and 100 mA (rule R-LIM-02), so R-IL-01 never triggers. The
   simulator scenarios model this open interlock, so `OPEN` is expected there.
2. On hardware the `interlock` field is status-byte bit 3: it is set only when a voltage output or voltage
   compliance above the interlock-open limit was requested while the interlock was open, and clears on a serial
   poll, `*RST` or device clear (Programming Guide PDF 76; ATV-10, confirmed at hardware bring-up). v1 never plans
   above 42 V, so on hardware treat `OPEN` like error 202.
3. Errors 202 or 203: something asked for a high-voltage output or voltage compliance. v1 plans cannot, so this is
   a bug or a tampered setup.
4. Error 310: the interlock opened while an output was in a high-voltage state and the instrument initialized
   itself. Possible module fault; the manual asks for a self-test.

## First safe checks

1. `station_status`: backend, interlock field, instrument errors, outputs on, fault latch.
2. Simulator without errors: nothing to fix. Say so and go back to skill `b1500-test`.
3. Hardware `OPEN`, 202, 203 or 310: `get_run(run_id, include=[summary, audit])` on the last runs to find the
   command and the planned levels. Every v1 plan stays at or below 42 V; anything else goes into the report
   verbatim.

## Physical checks to ask the human

- Only after a hardware `OPEN`, 202, 203 or 310: what state are the shield box lid and the interlock cable in, did
  anyone open the box during a run, does the front panel show an error or the high-voltage LED?
- After 310: the human decides whether to run a self-test (recipe `system.self_test`, always confirmed) or to call
  service.

## Do not

- Suggest closing, jumpering, bridging or defeating the interlock, or wiring around the shield box switch.
- Plan anything above 42 V or offer a "high-voltage mode": v1 has none. High voltage waits for the hardware
  bring-up interlock verification (M4) and the owner's decision.
- Edit limits or the policy's interlock section.

## Stop and call safe_shutdown

- Hardware `OPEN`, or any 202, 203 or 310 error: `safe_shutdown(reason)`, report the runs, wait for the human.
- The shield box was opened during a run.
