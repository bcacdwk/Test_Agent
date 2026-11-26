---
stage: L0
title: Read-only probe and configuration - bus, identity, inventory, errors, WGFMU library; config/local adopted by the human
recipes: []
checks:
  - {id: visa_resources, quantity: visa_resources, reference: doctor --probe, text: 'PASS: the resource is listed'}
  - {id: bus, quantity: bus, reference: doctor --probe, text: 'PASS: opened and exclusively locked'}
  - {id: identity, quantity: identity, reference: S0 firmware record, text: 'PASS: B1500A, firmware as at S0'}
  - {id: inventory, quantity: inventory, reference: config/local/station.yaml as adopted, text: 'PASS: UNT? equals the station (R-INV-01)'}
  - {id: error_queue, quantity: error_queue, reference: second probe, text: 'PASS: empty (0, and +0, both empty)'}
  - {id: status_byte, quantity: status_byte, reference: PG status byte, text: 'PASS: bits 3 and 5 clear'}
  - {id: outputs, quantity: outputs, reference: 'LOP? answer', text: 'PASS: every slot 00'}
  - {id: release, quantity: release, reference: doctor --probe, text: 'PASS: unlocked and closed'}
  - {id: wgfmu_library, quantity: wgfmu_library, reference: doctor --probe, text: 'PASS: x64 wgfmu.dll loadable (library >= A.03.00); INFO without a WGFMU'}
  - {id: wgfmu_session, quantity: wgfmu_session, reference: doctor --probe --wgfmu-session, text: 'PASS: the library lists the WGFMU channels of UNT?, no sequencer running'}
  - {id: fault_latch, quantity: fault_latch, reference: doctor --probe, text: 'PASS: no fault latched'}
  - {id: terminations, quantity: terminations, reference: 'raw answers of the second probe file; the FlexGUI window (ATV-2)', text: 'every query answered, no timeout, no stray CR or blank; FlexGUI shows RMT'}
  - {id: server_visa, quantity: server_visa, reference: 'station_status through the harness (v1 ATV-4)', text: 'backend visa, the identity and modules of the probe'}
  - {id: asu_presence, quantity: asu_presence, reference: 'the human at the SMU cables (ATV-28)', text: 'ASU3, ASU4 present true or false in the adopted station (none null)'}
  - {id: scuu_presence, quantity: scuu_presence, reference: 'the human at the MFCMU front (ATV-28)', text: 'SCUU1 present true or false in the adopted station (not null)'}
version: 2
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# L0 - Read-only probe and configuration

First contact over GPIB. Nothing here switches an output on: the probe sends queries only (`*IDN?`, `UNT?`,
`ERRX?`, `*STB?`, `LOP?`, `*LRN? 31`, `ERMOD?`/`ERSSP?`, `SPST?`, `CORRST?`/`ADJ? ch,0`) through a read-only link
that refuses any setting command; it reads the WGFMU library's file without loading it, and `--wgfmu-session` opens
the library's own session with the GPIB link closed only to list the channels and the status. You probe and
propose; the human adopts the configuration (`config/local/` exists since deployment step D7).

## 1. Preconditions

- S0 signed off (reviewed record or the human's explicit "go on"); `uv run b1500 bringup status` names L0.
- DUT disconnected; EasyEXPERT exited, Start EasyEXPERT button shown or minimized; `config/local/` from deployment
  step D7 (backend visa, no instrument contact yet).
- Only the human runs the configuration bootstrap; you never run the init or adopt commands, never write
  `config/local/**`.

## 2. Physical steps (human)

1. Check the local configuration of deployment step D7 (`uv run b1500 config init --visa`, human only; run it now if
   D7 did not): `config/local/settings.yaml` says `backend: visa` and resource `GPIB0::17::INSTR`; change
   `visa.resource` if S0 recorded another address.
2. After your proposal (agent step 4): review `work/bringup/station.proposed.yaml` and its diff, fill the cable
   records from S0, `present: true` or `false` of ASU3 and ASU4 (an ASU box on the SMU cable) and of SCUU1 (on the
   MFCMU front) as you see them, never `null`, and, where already known, the selector and RSU inputs (unknown wiring
   stays `null` until L7/L8), then adopt it: `uv run b1500 config adopt work/bringup/station.proposed.yaml --as
   station` (human only; it validates, shows the diff and keeps the old file as `.bak`).
3. Pin maps and DUT profiles: copy the needed examples or the agent's proposals from `work/bringup/` with
   `uv run b1500 config adopt FILE --as pinmap` or `--as dut`; keep `certainty: unverified` until you have checked
   the wiring yourself.
4. One-process check (ATV-4, ATV-13): with the coding agent open and idle, run `uv run b1500 status` in a second
   window ten times; it must answer each time (no session is held between calls). Say whether the FlexGUI window on
   the B1500A shows `RMT` (ATV-2).

## 3. Agent steps

Simulator rehearsal: the configuration already selects the simulator, so there is no init; do steps 2 and 4 in
one turn, give the human the adoption command in chat and stop (skill part 4).

1. `uv run b1500 doctor` (installation; no FAIL), then `uv run b1500 config check` (the D7 configuration).
2. `uv run b1500 doctor --probe --wgfmu-session` (read-only). Read every line; raw answers go to
   `work/bringup/probe-<UTC>.json`.
   The first probe after power-on may WARN about old error-queue entries (it drains them): probe again; the
   second must show none, and its raw answers no timeout, stray CR or blank (`terminations`).
3. A FAIL line: stop (section 5). A `busy` bus: EasyEXPERT or another VISA program still holds the instrument;
   the human ends it.
4. `uv run b1500 bringup propose-station` writes `work/bringup/station.proposed.yaml` from `*IDN?` and `UNT?`
   and prints the diff against the active station file. Show the human the path and that diff (quote the command's
   output; never run your own `diff` or redirect output next to a configuration file), hand step 2 of section 2 to
   them and stop the turn.
5. After the human's "adopted": `uv run b1500 config check` (valid, backend visa), then
   `uv run b1500 doctor --probe` again: `inventory` must now PASS against the adopted station.
6. `station_status`: backend visa, the same identity and modules as the CLI (`server_visa`: the server opens VISA
   inside the harness, v1 ATV-4); ask the human for step 4 of section 2.
7. Hardware: `uv run b1500 bringup capture probe` writes anonymized fixtures of the probe answers
   (`*IDN?` serial replaced by 0; the `wgfmu.dll` file version too) to `work/bringup/fixtures/`;
   `uv run b1500 bringup record L0 --probe latest --operator NAME` drafts the stage record from the newest probe.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `visa_resources` | the configured resource is listed | PASS | `doctor --probe` |
| `bus` | opened and locked; never `busy` | PASS | `doctor --probe` |
| `identity` | `B1500A`, firmware equal to the S0 record | PASS | `*IDN?` |
| `inventory` | every slot of `config/local/station.yaml` matches `UNT?`; empty slots `0,0` | PASS | `UNT?`, R-INV-01 |
| `error_queue` | empty on the second probe | PASS | `ERRX?` |
| `status_byte` | bits 3 (8) and 5 (32) clear; bit 4 (16) may be set | PASS | `*STB?` (PG p76 (1-56) "Status Byte") |
| `outputs` | every slot `00` | PASS | `LOP?` (PG p446 (4-128) "LOP?") |
| `release` | unlocked and closed | PASS | `doctor --probe` |
| `wgfmu_library` | the x64 `wgfmu.dll` (System32, or `wgfmu.library`) with every export the binding needs | PASS | `doctor --probe` (ATV-15) |
| `wgfmu_session` | channels = the WGFMU of `UNT?` (e.g. 201, 202); status idle; session closed | PASS | `doctor --probe --wgfmu-session` (ATV-16) |
| `fault_latch` | none | PASS | `doctor --probe` |
| `terminations` | every raw answer complete, no stray CR or blank; FlexGUI shows `RMT` | pass/fail | probe file, the human |
| `server_visa` | `station_status` through the harness: backend visa, the probe's identity and modules | pass/fail | v1 ATV-4 |
| `asu_presence`, `scuu_presence` | ASU3, ASU4, SCUU1 `present` true or false as the human saw them | recorded | station file (ATV-28) |

- Terminations (ATV-2): every query answered without a timeout, no stray CR or trailing space in the raw
  answers, the FlexGUI window shows `RMT`. Fallback: the human sets `visa.write_termination` and
  `visa.read_termination` in `config/local/settings.yaml` and L0 is repeated.
- Status byte bit 3 (ATV-10) is an event (a refused high-voltage request, PG p76 (1-56)), not the interlock state:
  with the interlock open as S0 requires `*STB?` still reads 16 (the simulator does the same); the physical state
  is the S0 test. A set bit 3 WARNs (a program asked for > 42 V). Fallback (in the code): R-IL-01 also checks
  errors 202/203 (PG p577 (5-5)).
- Per-call open, lock, unlock and close below 100 ms (ATV-13; L1's `bus_overhead` reads the `bus_*` lines of the
  run audits). Fallback, an owner decision: `visa.session: process` in `config/local/settings.yaml`.
- Line frequency of S0 equals the policy's `line_hz` (ATV-31); otherwise the human corrects the policy.
- WGFMU library (ATV-15): a 32-bit DLL or a missing one FAILs with "install library >= A.03.00" (x64 since A.03.00:
  Keysight release notes 9018-80226, blueprint v2 0.1; not in the manual corpus); the human installs the B1530A
  WGFMU Instrument Library A.04.00 (x64 into System32) or sets `wgfmu.library`; record the file version the line
  shows. Session (ATV-16): opening it, listing the channels and the status must change no output (`LOP?`
  of a second probe still all `00`). Fallback when only the session line fails: probe without `--wgfmu-session`
  and leave the session check to L8.
- TODO(verify) (blueprint v2 7.6 items 1, 2, 3, 4, 5, 6, 12): GPIB address, terminations, timeouts and the VISA
  vendor (ATV-2), per-call open cost (ATV-13); the real `UNT?` (slots 8-10, B1511A or B) and firmware; ASU and
  SCUU presence (ATV-28); the `ERRX?` success text (`0,` or `+0,`) and every raw probe answer as a fixture (the
  `wgfmu.dll` file version too); status byte bit 3 (v1 ATV-10); `wgfmu.dll` install, version and load (ATV-15),
  the probe-safe session (ATV-16); the server opens VISA inside the harness (v1 ATV-4, `server_visa`).

## 5. Abort criteria

- No answer or timeouts after the termination fallback; `*IDN?` without `B1500A`; a `UNT?` module the station
  does not know.
- `LOP?` not all `00`; the error queue not empty on the second probe; status byte bit 3 or 5 set on two probes;
  a `wgfmu_library` FAIL (WGFMU recipes cannot load the library: the human installs library >= A.03.00,
  deployment step D3, `docs/deployment-windows.md` step 1.5).
- Any setting or source command in the L0 audit (the daily `data/state/audit/<UTC date>.jsonl` must hold
  `"ev":"query"` lines only for the probe).
- On any of them: `safe_shutdown(reason)`, report the line and the raw answer, wait for the human.

## 6. Record

- Hardware: the stage record from the newest probe
  (`uv run b1500 bringup record L0 --probe latest --operator NAME`), reviewed by the human and moved to
  `validation/hw/stage-l0.yaml`; the probe fixtures from `uv run b1500 bringup capture probe`, moved by the human
  to `tests/fixtures/hw/`.
- Simulator rehearsal: the probe reads the simulator (every line SIMULATED); no record, no capture.
