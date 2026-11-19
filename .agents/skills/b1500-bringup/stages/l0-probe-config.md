---
stage: L0
title: Read-only probe and configuration - bus, identity, inventory, errors; config/local adopted by the human
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
  - {id: fault_latch, quantity: fault_latch, reference: doctor --probe, text: 'PASS: no fault latched'}
version: 1
---

# L0 - Read-only probe and configuration

First contact over GPIB. Nothing here switches an output on: the probe sends queries only (`*IDN?`, `UNT?`,
`ERRX?`, `*STB?`, `LOP?`, `*LRN? 31`, `ERMOD?`/`ERSSP?`, `SPST?`, `CORRST?`/`ADJ? ch,0`) through a read-only link
that refuses any setting command. You probe and propose; the human creates and adopts the configuration.

## 1. Preconditions

- S0 signed off (reviewed record or the human's explicit "go on"); `uv run b1500 bringup status` names L0.
- DUT disconnected; EasyEXPERT exited, Start EasyEXPERT button shown or minimized.
- Only the human runs the configuration bootstrap; you never run the init or adopt commands, never write
  `config/local/**`.

## 2. Physical steps (human)

1. Create the local configuration in a PowerShell window at the clone root: `uv run b1500 config init --visa`
   (human only: copies the missing examples into `config/local/`, `backend: visa`, resource `GPIB0::17::INSTR`;
   change `visa.resource` if S0 recorded another address).
2. After your proposal (agent step 4): review `work/bringup/station.proposed.yaml` and its diff, fill the cable
   records from S0 and, where already known, the selector and RSU inputs (unknown wiring stays `null` until L7),
   then adopt it: `uv run b1500 config adopt work/bringup/station.proposed.yaml --as station` (human only; it
   validates, shows the diff and keeps the old file as `.bak`).
3. Pin maps and DUT profiles: copy the needed examples or the agent's proposals from `work/bringup/` with
   `uv run b1500 config adopt FILE --as pinmap` or `--as dut`; keep `certainty: unverified` until you have checked
   the wiring yourself.
4. One-process check (ATV-4, ATV-13): with the coding agent open and idle, run `uv run b1500 status` in a second
   window ten times; it must answer each time (no session is held between calls).

## 3. Agent steps

Simulator rehearsal: the configuration already selects the simulator, so there is no init; do steps 2 and 4 in
one turn, give the human the adoption command in chat and stop (skill part 4).

1. `uv run b1500 doctor` (installation; no FAIL), then `uv run b1500 config check` once the human has run the
   init command.
2. `uv run b1500 doctor --probe` (read-only). Read every line; raw answers go to `work/bringup/probe-<UTC>.json`.
   The first probe after power-on may WARN about old error-queue entries (it drains them): probe again; the
   second must show none.
3. A FAIL line: stop (section 5). A `busy` bus: EasyEXPERT or another VISA program still holds the instrument;
   the human ends it.
4. `uv run b1500 bringup propose-station` writes `work/bringup/station.proposed.yaml` from `*IDN?` and `UNT?`
   and prints the diff against the active station file. Show the human the path and that diff (quote the command's
   output; never run your own `diff` or redirect output next to a configuration file), hand step 2 of section 2 to
   them and stop the turn.
5. After the human's "adopted": `uv run b1500 config check` (valid, backend visa), then
   `uv run b1500 doctor --probe` again: `inventory` must now PASS against the adopted station.
6. `station_status`: backend visa, the same identity and modules as the CLI; ask the human for step 4 of section 2.
7. Hardware: `uv run b1500 bringup capture probe` writes anonymized fixtures of the probe answers
   (`*IDN?` serial replaced by 0) to `work/bringup/fixtures/`;
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
| `fault_latch` | none | PASS | `doctor --probe` |

- Terminations (ATV-2): every query answered without a timeout, no stray CR or trailing space in the raw
  answers, the FlexGUI window shows `RMT`. Fallback: the human sets `visa.write_termination` and
  `visa.read_termination` in `config/local/settings.yaml` and L0 is repeated.
- Status byte bit 3 (ATV-10) is an event (a refused high-voltage request), not the interlock state; the physical
  state is the S0 test. Fallback (in the code): rule R-IL-01 also checks errors 202/203.
- Per-call open, lock, unlock and close below 100 ms (ATV-13, from the `bus_*` lines of the daily audit). Fallback,
  an owner decision: `visa.session: process` in `config/local/settings.yaml`.
- Line frequency of S0 equals the policy's `line_hz` (ATV-31); otherwise the human corrects the policy.
- The WGFMU library session check of the probe arrives with the WGFMU work package; L8 checks the library.

## 5. Abort criteria

- No answer or timeouts after the termination fallback; `*IDN?` without `B1500A`; a `UNT?` module the station
  does not know.
- `LOP?` not all `00`; the error queue not empty on the second probe; status byte bit 3 or 5 set on two probes.
  Simulator rehearsal only: the simulator keeps bit 3 set while the interlock is open (it models the interlock
  state, not the manual's event, PG p76 (1-56)), so `*STB?` reads 24 with the interlock open as S0 requires; there
  bit 3 alone is no abort criterion (bit 5 still is). On hardware the criterion stands.
- Any setting or source command in the L0 audit (the daily `data/state/audit/<UTC date>.jsonl` must hold
  `"ev":"query"` lines only for the probe).
- On any of them: `safe_shutdown(reason)`, report the line and the raw answer, wait for the human.

## 6. Record

- Hardware: the stage record from the newest probe
  (`uv run b1500 bringup record L0 --probe latest --operator NAME`), reviewed by the human and moved to
  `validation/hw/stage-l0.yaml`; the probe fixtures from `uv run b1500 bringup capture probe`, moved by the human
  to `tests/fixtures/hw/`.
- Simulator rehearsal: the probe reads the simulator (every line SIMULATED); no record, no capture.
