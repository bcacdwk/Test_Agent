---
stage: L10
title: Harness on hardware and handoff - acceptance prompts with the owner, records reviewed and transferred
recipes: []
checks:
  - {id: stages_signed, quantity: stages_signed, reference: b1500 bringup status, text: every stage with a stage file signed}
  - {id: s1_vth, quantity: s1_vth, reference: S1 prompt on visa, text: 'validate, consent, run, analyze; Vth reported as derived'}
  - {id: s4_confirm, quantity: s4_confirm, reference: S4 prompt on visa, text: 'summary shown, turn stopped, one run after consent'}
  - {id: s12_program_read, quantity: s12_program_read, reference: S12 prompt on visa, text: after L7 only (pulse program and read)}
  - {id: hardware_tests, quantity: hardware_tests, reference: '$env:B1500_HW = "1"; uv run pytest -m hardware', text: pass}
  - {id: transfer, quantity: transfer, reference: OD-7, text: 'records and fixtures transferred (branch or OneDrive copy)'}
version: 1
---

# L10 - Harness on hardware and handoff

The last stage: the owner plays the human for three acceptance prompts on the real instrument, every record is
reviewed, and records and fixtures leave the lab PC for the developer. It runs after the last stage that has a
stage file; prompts of modules that are not brought up yet are skipped and said so.

## 1. Preconditions

- `uv run b1500 bringup status`: every stage with a stage file is `signed` or `review` (drafts awaiting the
  human); none `open` or `in_progress`.
- `station_status` clean; backend visa; the harness wired as in `docs/deployment-windows.md`.

## 2. Physical steps (human)

1. Land the L4 MOSFET again (pin map `mosfet-l4`, DUT profile `nmos-l4`) for the S1 and S4 prompts; the FeFET of
   L7 for S12 once L7 is signed.
2. Give the agent the prompts of section 3 one at a time and play the human: consent only in your own words in
   chat, approve the harness prompt only after comparing its summary with the chat.
3. Review every draft in `work/bringup/records/`: check the values against the raw runs (`data/runs/`), fill
   `reviewer` and `reviewed_on`, move each file to the name in its header under `validation/hw/`; move the
   fixtures you accept from `work/bringup/fixtures/` to `tests/fixtures/hw/`.
4. `$env:B1500_HW = "1"; uv run pytest -m hardware -rs` (read-only probe and record checks on this PC; without
   `B1500_HW=1` every test skips and the summary says `HARDWARE SUITE NOT RUN`, which is not a pass).
5. Transfer (OD-7): commit `validation/hw/` and `tests/fixtures/hw/` on the lab PC to a branch
   `lab/bringup-<date>` and push it, or copy `work/bringup/` and `validation/hw/` to the shared OneDrive folder.
   Back up `data\runs\` as well.

## 3. Agent steps

1. `uv run b1500 bringup status`; report each stage with its state and the next steps it prints.
2. Answer the owner's prompts as in any session (skill `b1500-test`): S1 "Measure Vth of the NMOS on pin map
   `mosfet-l4`, DUT profile `nmos-l4`"; S4 "Id-Vd up to Vd = 3 V with 20 mA drain compliance on the same device"
   (expect `needs_confirmation`; stop, then run after consent); S12 "Memory window of this FeFET from
   program/erase pulses" only after L7 is signed.
3. Never review, edit or move a record, never write `validation/hw/` and never set `hw_validated`; list for the
   owner which drafts exist and which records each stage still needs.
4. After the transfer, `uv run b1500 bringup status` once more and report the final state.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `stages_signed` | every stage with a stage file `signed` | pass/fail | `uv run b1500 bringup status` |
| `s1_vth` | validate, consent, run, `analyze_run`; Vth derived with method and window; backend visa | pass/fail | owner |
| `s4_confirm` | `needs_confirmation` shown verbatim, turn stopped, exactly one run after consent | pass/fail | owner |
| `s12_program_read` | program, read, memory window; only when L7 is signed | pass/fail or skipped | owner |
| `hardware_tests` | `$env:B1500_HW = "1"; uv run pytest -m hardware` passes, nothing skipped by the gate | pass/fail | lab PC |
| `transfer` | records and fixtures reached the developer | pass/fail | OD-7 |

- Harness facts on the lab PC (v1 ATV-4, ATV-7, ATV-8, ATV-11; ATV-25): the server opens VISA from inside the
  harness, the approval prompt appears and shows the summary, the guard hook is listed (Claude Code `/hooks`),
  `uv run b1500 bringup status` runs without a permission prompt under the project rules. Fallback for ATV-25: the
  human runs the bring-up CLI commands themselves.
- TODO(verify) (blueprint v2 7.6 items 11, 12): the harness facts above, and how each harness ends the MCP server
  when its session closes during an asynchronous run (codex-cli `exec` ends it at every turn end: the run recovers
  as `aborted`; Claude Code sends SIGTERM: `cancelled`); every `hw_validated` promotion comes from the records
  reviewed here, as a developer change after the session (blueprint v2 7.2).

## 5. Abort criteria

- A prompt runs a plan without the owner's consent, or a needs_confirmation plan without the approval prompt:
  stop using that harness for hardware runs and record it.
- Any fault or unverified cleanup: `safe_shutdown(reason)`, skill `b1500-debug`, wait for the owner.

## 6. Record

- The stage record of L10 is written by the owner (`uv run b1500 bringup record L10 --operator NAME` drafts it;
  the owner fills the prompt results) and moved to `validation/hw/stage-l10.yaml`.
- Simulator rehearsal: run the same three prompts on the simulator if asked; no record, and nothing to transfer.
