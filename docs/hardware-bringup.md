# Hardware bring-up checklist (M4)

Status: **checklist only.** Nothing here has run on hardware yet. It is executed later on the lab PC with the owner
present; values marked `TODO(verify)` are confirmed during execution. Plan of record: blueprint §9.5 (WP4.1), §4,
§7, §9.7 (ATV-1, -2, -3, -4, -7, -10, -11). The lab PC itself is set up with
[deployment-windows.md](deployment-windows.md).

## How to use this checklist

| Stage | Goal | Outputs switched on? | Coding agent |
|---|---|---|---|
| Stage 0 | Physical setup, interlock, EasyEXPERT state | no (EasyEXPERT self-test only) | closed |
| L0 | Read-only probe over GPIB | no (queries only) | closed (one read at the end) |
| L1 | 0 V open circuit per SMU, cleanup verification, interrupt test | yes, 0 V (plus ±0.1 V) | closed |
| L2 | Known resistors 100 kΩ and 1 MΩ vs a DMM | yes, ±0.1 V | closed |
| L3 | Known diode vs a reference | yes, −5 V … +0.8 V | closed |
| L4 | Known-good MOSFET vs EasyEXPERT; promote recipes to `hw_validated` | yes, ≤ 3 V | one agent run |

- Go strictly in order. A stage starts only after the previous stage's sign-off line is filled in. Stop at the first
  failed abort criterion; never skip ahead.
- **The owner (a human at the instrument) does every step.** All commands are typed by the owner in a PowerShell
  window at the clone root. `uv run b1500 run --confirm PLAN_ID` and `uv run b1500 fault clear` are human-only
  commands; the harness rules stop a coding agent from running them.
- **Nobody types FLEX commands.** `CN`, `DV`, `WV`, `XE`, `DZ`, `CL` and the queries are sent by the recipes, the
  transaction cleanup, `b1500 status` and `b1500 shutdown`. You read them back in the run's audit with
  `uv run b1500 show RUN_ID --include audit` (or `audit.jsonl` in the run folder).
- On hardware every recipe is still `sim_validated`, so every plan is `needs_confirmation` (`first_hw_run`, plus
  `unverified_pin_map` while a pin map says `certainty: unverified`). That is expected: read the printed summary, then
  run it with `uv run b1500 run --confirm PLAN_ID` and answer `y`.
- Hardware run ids start with `H`. Each run folder (`data\runs\YYYY\MM\DD\RUN_ID\`) keeps `manifest.json`,
  `audit.jsonl`, `raw\block-NNN.txt`, `data.csv`, `quality.json` and `analysis\`. Add remarks with
  `uv run b1500 note RUN_ID "TEXT" --tag m4`.
- **Abort** means: stop, then `uv run b1500 shutdown --reason "M4 STAGE abort: WHY"` and continue with "If cleanup
  fails" when it does not report a verified cleanup.

**CLI and harness coexist.** Every b1500 call opens the VISA session, takes its exclusive lock
(`visa.exclusive_lock: true`), and unlocks and closes it before it returns (blueprint v2 2.4), so the b1500 MCP
server inside an idle Codex or Claude Code session holds nothing and `uv run b1500 status` in another window works.
Only a program that keeps the instrument (EasyEXPERT, another VISA tool) makes a call answer `busy`
(`instrument_busy`, nothing sent) after `visa.lock_timeout_ms`; a `b1500 shutdown` that cannot take the bus latches
the fault, by design. Exit EasyEXPERT before Stage 0. L0 checks this once.

**If cleanup fails** (a run reports cleanup `unverified`, or `fault: latched` appears in `uv run b1500 status`):
check the front panel and the DUT, run `uv run b1500 lock status`, then `uv run b1500 shutdown --reason "WHY"`. When
the shutdown reports a verified cleanup and an empty error queue, clear the latch with
`uv run b1500 fault clear --by NAME` (it runs another verified shutdown first and refuses otherwise). Never delete
files under `data\state\` by hand. Last resort, when the software cannot reach the instrument and an output may still
be on: switch the B1500A off at its power switch.

---

## Stage 0 — Physical setup

### Preconditions

- Lab PC prepared with [deployment-windows.md](deployment-windows.md) up to its config step (clone, `uv sync --frozen`,
  `config\local\` drafted). No harness running.
- B1500A powered on; DUT **disconnected** (probe needles lifted or fixture socket empty) — self-test and
  self-calibration need open measurement terminals (User Guide, UG PDF 142).

### Commands

Physical and EasyEXPERT steps only (no `b1500` command talks to the instrument in this stage):

1. **Interlock wiring.** Find how the rear-panel Interlock terminal is wired: shield-box door switch, 16442B test
   fixture, or not wired (UG PDF 55; circuit UG PDF 113). Run the **Interlock Open/Close test** and the
   **High Voltage LED test** in EasyEXPERT: Configuration window, Main Frame tab (UG PDF 55, 142; required once a
   day after power-on).
2. **Interlock state for v1.** v1 never needs more than 42 V, and the blueprint's physical backstop is "keep the
   interlock open": with the circuit open the B1500A itself limits SMU outputs to ±42 V. If closing the shield box
   would close the interlock circuit, unplug the interlock cable at the B1500A for all v1 work (owner's decision;
   record it). Record the result in `config\local\station.yaml` `interlock.available` (`true` only after the test of
   step 1 passed) and `interlock.note`.
3. **Shield box.** Closed and light-tight during measurements; shield connected as the station requires
   (`.agents/skills/b1500-test/knowledge/03-probe-station-wiring.md`, "Shielding grounding and interlock").
4. **Cables.** Triaxial cable on every SMU that a pin map will use; GNDU on its own 16493L cable; no BNC adapters in
   low-current paths; Guard connected to nothing (connecting it damages the SMU, UG PDF 93). Record cable type,
   length, Guard and Kelvin per module alias in `config\local\station.yaml` `topology.cables`.
5. **EasyEXPERT records.** Configuration window, Main Frame tab: model, firmware revision, EasyEXPERT revision and
   **line frequency** (run-time estimates assume 50 Hz) (EasyEXPERT User's Guide PDF 108-109). Modules tab: slot
   list → `config\local\station.yaml` `modules` (slot, model, type); run **Start Self Test** (PDF 109-110).
   Calibration: run **Module Self Calibration** and record the auto-calibration setting and the **SMU Zero Cancel**
   state (it shifts low-current offsets) (PDF 102-103). The `system.self_test`/`system.self_cal` recipes are
   `not_implemented` on visa in v1 (kind `system` is simulator-only); TODO (M4 code): enable kind `system` on visa
   and confirm its 120 s / 60 s run-time estimates.
6. **B1500A GPIB settings** (instrument's own Keysight Connection Expert; Programming Guide "Before Starting", PG
   PDF 23): GPIB address (factory 17), System Controller `No`, Auto-discover `No`; a change needs a B1500A reboot.
   With a USB/GPIB adapter the guide recommends an **even** address if intermittent serial-poll errors appear (then
   change it here and in `config\local\settings.yaml` `visa.resource`).
7. **Release the instrument for FLEX control (ATV-3).** In EasyEXPERT select File > Exit. Leave the
   **Start EasyEXPERT** button on the screen or minimized to the task bar: the Start EasyEXPERT service must keep
   running for external control (PG PDF 23). ATV-3 check: the Programming Guide Ed. 15 confirms the assumption
   (EasyEXPERT is ended before FLEX control); at L0 the FlexGUI window must open on the first GPIB command.
   Fallback (if the guide changes): follow the current guide's "Before Starting" steps and record them here.

### Expected values

- Interlock Open/Close test and High Voltage LED test: pass.
- Self-test: pass for the mainframe and every module. Self-calibration: completed without error.
- Module list equals what `config\local\station.yaml` will claim (slot, model).
- B1500A screen shows the Start EasyEXPERT button (or it is minimized); EasyEXPERT main window closed.

### Abort criteria

- Interlock or High Voltage LED test fails; self-test or self-calibration error (EasyEXPERT User's Guide, self-test
  and calibration errors, PDF 674-688).
- A Guard conductor touches anything; damaged or unknown cables; unexpected module in a slot.

### Sign-off

`Stage 0 passed: interlock test [ ] HV LED [ ] self-test [ ] self-cal [ ] line frequency ____ Hz [ ]
station.yaml updated [ ] EasyEXPERT exited [ ] — name ________ date ________`

---

## L0 — Read-only probe

Nothing in this stage turns an output switch on: only queries (`*IDN?`, `UNT?`, `ERRX?`, `*STB?`, `LOP?`).

### Preconditions

- Stage 0 signed off; DUT disconnected; EasyEXPERT exited (Start EasyEXPERT button visible or minimized).
- `config\local\settings.yaml` has `backend: visa` and the resource (default `GPIB0::17::INSTR`);
  `config\local\station.yaml` and `config\local\policy.yaml` exist. No harness running.

### Commands

```powershell
uv run b1500 config check
uv run b1500 doctor
uv run b1500 doctor --probe
uv run b1500 status
uv run b1500 status
uv run b1500 status --json
uv run b1500 lock status
```

- `doctor --probe` is **not implemented on visa in v1**: it prints "doctor --probe is not implemented yet" and exits
  with code 2. TODO (M4 code, before this stage is executed): implement the read-only probe of blueprint §7 (VISA
  library loads, `list_resources()` lists the resource, `*IDN?` contains `B1500A`, `UNT?` equals the station profile,
  `ERRX?` clear, STB decoded; never `CN`). Until then `uv run b1500 status` sends the same queries read-only, and the
  vendor tool (Keysight Connection Expert or NI MAX) shows the VISA library and the resource list.
- Run `status` twice: the first call after power-on may drain old error-queue entries.

**Raw capture → `tests/fixtures/hw/`.** Every query and its raw answer is in the daily audit
`data\state\audit\YYYY-MM-DD.jsonl` (UTC date; lines with `"ev":"query"`, fields `cmd` and `resp`):

```powershell
Select-String -Path data\state\audit\*.jsonl -Pattern '"ev":"query"'
```

Create one file per answer — `tests/fixtures/hw/idn_l0.txt`, `unt_l0.txt`, `errx_l0.txt`, `stb_l0.txt`,
`lop_l0.txt` — in the header format of `tests/fixtures/flex/` (documented in `tests/unit/flex_fixtures.py`):
`# source:` (M4 L0 capture, date, audit file and `seq`, plus the PG page of the format), `# kind:`, `# command:`,
`# expect:` (parsed JSON), `# note:`, then the body exactly as received. Anonymize: a serial number in the `*IDN?`
answer becomes `0` (as in the manual's own example) with a `# note:`; no station or user names. Hand the files to
the developer (or commit them). TODO (dev): a parser test over `tests/fixtures/hw/` and a comparison with the
simulator's answers.

### Expected values

| Check | Expected | If not |
|---|---|---|
| `config check` | `config: valid`; backend `visa` because of `config\local\settings.yaml` | fix `config\local\` |
| `doctor` | no FAIL line | follow the line's hint |
| `*IDN?` | contains `B1500A`; firmware equals Stage 0 record | wrong resource or address |
| `UNT?` | every slot of `station.yaml` shows `match True`; empty slots read `0,0` (parser assumption in `driver/discovery.py`) | fix `station.yaml` (rule R-INV-01 blocks every plan meanwhile); another empty-slot token → TODO parser fix + fixture |
| `ERRX?` | second `status`: `errors none` (raw `0,"No Error."`) | abort |
| `*STB?` | bit 3 (8) and bit 5 (32) clear; bit 4 (16, "set ready") may be set: `0` or `16`; record the value | see ATV-10 below |
| `LOP?` | `outputs on none` (raw `LOP00,00,00,00,00,00,00,00,00,00`) | abort |
| `lock status` | lock free, no inflight marker, no fault | see "If cleanup fails" |
| Audit | only queries (`*IDN?`, `UNT?`, `ERRX?`, `*STB?`, `LOP?`); no `CN` | abort, report |

**ATV-2 check (GPIB address 17; write `\n`, read `\n`/EOI).** Every query is answered without a timeout; the `resp`
fields carry no stray `\r` or trailing spaces; the B1500A shows the FlexGUI window with the GPIB address and `RMT`
green (PG PDF 23-24). Fallback: set `visa.resource`, `visa.write_termination` and `visa.read_termination` in
`config\local\settings.yaml` (the human edits it) and repeat L0.

**ATV-10 check (STB bit 3).** The manual describes bit 3 as an event, not the circuit state: it is set when a voltage
output or voltage compliance above the interlock-open limit is requested while the interlock is open, and cleared
by a serial poll, `*RST` or device clear (PG PDF 76). With the interlock open (Stage 0) and v1's 42 V ceiling the
expected value is therefore `0`. On hardware the `status` line "interlock closed" only means "no refused high-voltage
request"; the physical state is the Stage 0 test result. Fallback (already applied in code): rule R-IL-01 also checks
errors 202/203, and every sweep aborts on any error after `CN`. TODO (M4 code): label the field on visa as an
interlock event, not as "closed".

**ATV-4 and one-process check** (last step of L0; harness wired per [deployment-windows.md](deployment-windows.md)):

1. Start Codex in the clone and ask: "Call station_status and report backend, identity and modules."
   Expected: `backend: visa`, the same `*IDN?` and module table as the CLI. ATV-4 fallback (the server cannot open
   VISA from inside Codex while the CLI can): follow the Codex documentation for MCP servers that need device access
   and record the setting used in [deployment-windows.md](deployment-windows.md).
2. With Codex still open and idle, run `uv run b1500 status` in a second PowerShell window. Expected: status ok
   with the same identity (the server holds no VISA session between calls). ATV-13: run `uv run b1500 status` ten
   times and add up `dur_ms` of the `bus_open`, `bus_lock`, `bus_unlock` and `bus_close` lines per call in
   `data\state\audit\<date>.jsonl`; expected below 100 ms per call and no errors. Record both. If opening per call
   is slow or unstable over GPIB, the owner may set `visa.session: process` in `config\local\settings.yaml` (the
   VISA session stays open, the lock is still taken per call); that is an owner decision.

### Abort criteria

- No answer or timeouts after the ATV-2 fallback; `*IDN?` without `B1500A`.
- `LOP?` not all `00`; error queue not empty on the second `status`; STB bit 3 or bit 5 set on two consecutive reads.
- Any source or channel command (`CN`, `DV`, `WV`, `XE`, …) in the L0 audit.

### Sign-off

`L0 passed: IDN ________ firmware ________ UNT matches [ ] empty-slot token ____ STB ____ LOP all 00 [ ]
terminations ok [ ] fixtures captured [ ] ATV-2 ____ ATV-10 ____ ATV-4 ____ one-process check ____ —
name ________ date ________`

---

## L1 — 0 V open circuit, per SMU

### Preconditions

- L0 signed off. DUT disconnected (needles lifted or socket empty) with the production cabling; shield box closed;
  interlock open (Stage 0). No harness running.
- For every SMU slot N of `station.yaml`, the owner writes `config\local\pinmaps\open-smuN.yaml`:

  ```yaml
  description: M4 L1 open circuit on SMU3 (nothing connected)
  certainty: unverified
  terminals:
    a: 3
    b: GNDU
  ```

  and one DUT profile `config\local\duts\open-circuit.yaml` (a copy of `config\duts\resistor-generic.example.yaml`:
  `device_type: resistor`, terminals `a` and `b` with `max_abs_v: 1.0`, `max_abs_i: 1.0e-3`).
  `uv run b1500 config check` is valid.

### Commands

The 0 V measurement uses recipe `basic.contact_resistor` with `v_start=0` and `v_stop=0`: a 21-point staircase that
stays at exactly 0 V. Per SMU (example SMU3):

```powershell
uv run b1500 recipes basic.contact_resistor
uv run b1500 plan basic.contact_resistor -p v_start=0 -p v_stop=0 --pin-map open-smu3 --dut open-circuit --label "M4 L1 SMU3 0 V"
uv run b1500 run --confirm PLAN_ID
uv run b1500 show RUN_ID --include summary --include quality --include audit
uv run b1500 analyze RUN_ID quality_report
uv run b1500 plan basic.contact_resistor --pin-map open-smu3 --dut open-circuit --label "M4 L1 SMU3 +-0.1 V"
uv run b1500 run --confirm PLAN_ID
```

What the instrument receives (from the audit; on the simulator for SMU3 with the defaults; the verify step is
`LOP?` on hardware):

| Phase | FLEX (sent by) |
|---|---|
| Baseline and pre-execute snapshot | `ERRX?`, `*IDN?`, `UNT?`, `ERRX?`, `*STB?`, `LOP?` (transaction) |
| Setup | `FMT 1,1`, `AAD 3,0`, `AIT 0,2,1`, `CN 3`, `ERRX?`, `MM 2,3`, `CMM 3,1`, `WV 3,1,0,0,0,21,0.001`, `WT 0,0`, `WM 2,1`, `ERRX?` (recipe kind `smu_staircase`) |
| Measure | `XE`, one read → `raw\block-000.txt` |
| Cleanup | `DZ`, `CL`, `ERRX?`, `LOP?` (transaction cleanup; `AB` first when a measurement is pending) |

The blueprint's `CN / DV 0 / XE / DZ / CL` sequence is thus exercised with `WV` at 0 V instead of `DV 0`. TODO (M4
code, optional): a spot recipe (kind `smu_spot`: `CN`, `DV 0`, measure, `DZ`, `CL`) if the literal `DV` path must
be tested; v1 has none. FMT 5 is not exercised (every v1 kind uses `FMT 1,1`); a hardware FMT 5 fixture stays TODO.

**Real FMT blocks → parser and simulator fixtures.** Copy `raw\block-000.txt` of one 0 V run per module type
(MPSMU, HRSMU) to `tests/fixtures/hw/fmt1_l1_<type>.txt` with the header of `tests/fixtures/flex/` (`kind: fmt1`,
`command:` = the setup above from the audit, `terminator: crlf`, one `# point:` line per element). TODO (dev): add
them to the parser golden tests and compare them with the simulator formatter (as
`tests/unit/test_sim_parser_crosscheck.py` does for the manual fixtures).

**`LOP?` vs `*LRN?` decision (ATV-1).**

1. Evidence A: every L1 cleanup reports `verified: lop` with all slots `00` (`manifest.json` → `cleanup`; the raw
   `LOP?` answer is in `audit.jsonl`). Record the idle codes of the WGFMU and SPGU slots too: Table 4-26 has no codes
   for them (PG PDF 446-447).
2. Evidence B (positive control): `LOP?` must show a non-`00` code (e.g. `01`, forcing voltage) while an SMU output
   switch is on. v1 cannot query `LOP?` between `CN` and `CL`. TODO (M4 code): a `hardware`-marked test in
   `tests/hardware/` (skipped unless `B1500_HW=1`) that does `CN` → `DV 0` → `LOP?` → `CL` → `LOP?` on one open SMU
   inside a transaction.
3. Decision: A and B hold → keep `LOP?` for SMU and MFCMU slots (ATV-1 holds; `*LRN?` is needed only for SPGU/WGFMU
   slots, which v1 never sources). Fallback if A or B fails, or if an idle SPGU/WGFMU slot reads non-`00`: verify via
   `*LRN? 0` (output-switch list, PG PDF 447) — a code change; until it exists hardware cleanup reports
   `verified: unverified` with a warning, which latches the fault after every run, so stop the bring-up here.

**Interrupt test (once, on one SMU).** Trigger a cleanup in the middle of a sweep:

```powershell
uv run b1500 plan basic.contact_resistor -p v_start=0 -p v_stop=0 -p points=201 -p integration=long --pin-map open-smu3 --dut open-circuit --label "M4 L1 interrupt test"
uv run b1500 run --confirm PLAN_ID
uv run b1500 lock status
uv run b1500 shutdown --reason "M4 L1 after interrupt"
uv run b1500 runs --limit 3
```

The plan estimates about 65 s. Confirm, wait about 10 s (the B1500A is measuring), then press **Ctrl+C** in that
window. Afterwards check `lock status`, run the explicit `shutdown`, and list the runs. Then repeat the long run once
and, while it measures, run `uv run b1500 shutdown --reason "M4 L1 shutdown during run"` in a second window: record
what it reports (expected: busy, naming the lock holder, after about 5 s — a running transaction keeps the instrument
until its own cleanup has finished; the in-window Ctrl+C is the mid-run stop). Let that run finish.

### Expected values

- Plan: tier `needs_confirmation` with confirm reasons `first_hw_run` and `unverified_pin_map`; summary names
  `a=SMUn(...) sweep 0 V Icomp 1 mA` and backend `visa`.
- 0 V run: outcome `completed_with_flags` — expected, because the default `resistance` analysis needs three distinct
  voltages ("resistance needs 3"); status counts all `N`; quality verdict `ok`; cleanup `verified: lop`, all slots
  `00`; error queue empty.
- Noise floor per SMU (record it): `quality.json` → `noise` → `a_I` (amperes) and the mean of `a_I` in `data.csv`.
  Coarse sanity bounds, not specifications: HRSMU |mean| < 1 pA, MPSMU |mean| < 100 pA at `integration=medium`
  (TODO(verify) against the B1500A data-sheet accuracy of the range used; tighten after the first runs). The
  simulator scenarios assume floors of 1e-13 A (HRSMU) and 1e-11 A (MPSMU); TODO (dev): update them if the hardware
  differs by more than ×10, and re-check the analysis `MIN_SNR`.
- ±0.1 V run on the open path: all statuses `N`; `resistance` classification `open`.
- Interrupt test: run outcome `aborted`; the audit shows `AB` (sent alone), `DZ`, `CL`, `ERRX?`, `LOP?` with all
  `00`; cleanup verified; `lock status` free, no inflight marker, no fault; the explicit `shutdown` reports verified.
  If the process ended without its cleanup instead (`lock status` shows an inflight marker), the explicit `shutdown`
  runs the recovery cleanup (`recovery_cleanup` in the daily audit) and must report verified; record which happened.

### Abort criteria

- Any status letter other than `N` at 0 V; a mean current above the sanity bound; classification other than `open`.
- Cleanup `unverified`, fault latched, any non-`00` `LOP?` code after cleanup, or an `ERRX?` entry (e.g. 202/203).
- After the interrupt test an output is still on or the lock is still held.

### Sign-off

| SMU | slot | type | 0 V run id | mean I (A) | noise (A) | ±0.1 V class | LOP after | ok |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

`L1 passed: all SMUs [ ] FMT fixtures captured [ ] ATV-1 decision: keep LOP? / fallback ________
interrupt run id ________ verified [ ] shutdown-during-run result ________ — name ________ date ________`

---

## L2 — Known resistors (100 kΩ, 1 MΩ)

### Preconditions

- L1 signed off for every SMU used here (at least the SMUs that L3 and L4 use).
- Instrument warmed up (TODO(verify): warm-up time from the B1500A data sheet).
- Two metal-film resistors, 100 kΩ and 1 MΩ, measured just before with a DMM (record model, range, 2- or 4-wire,
  reading, temperature), mounted between the SMU force path and GNDU in the fixture or on the probes; shield box
  closed.
- Pin maps `config\local\pinmaps\res-smuN.yaml` (copy of `config\pinmaps\resistor-2t.example.yaml`: `a: N`,
  `b: GNDU`; `certainty: unverified` until you have checked the wiring yourself, then `verified`). DUT profiles
  `config\local\duts\r100k.yaml` and `r1m.yaml` (copies of `resistor-generic` with `nominal.r` = the DMM value).

### Commands

Per resistor and per SMU (example SMU3, 100 kΩ):

```powershell
uv run b1500 plan basic.contact_resistor --pin-map res-smu3 --dut r100k --label "M4 L2 100k SMU3"
uv run b1500 run --confirm PLAN_ID
uv run b1500 show RUN_ID --include summary --include quality
uv run b1500 note RUN_ID "DMM VALUE (MODEL, 4-wire), TEMPERATURE" --tag m4-l2
```

Defaults: −0.1 V … +0.1 V, 21 points, compliance 1 mA, so about ±1 µA (100 kΩ) and ±100 nA (1 MΩ).

### Expected values

- Plan `needs_confirmation` (`first_hw_run`, plus `unverified_pin_map` while unverified).
- Run `completed`; all statuses `N`; quality `ok`; cleanup `verified: lop`.
- `resistance`: classification `in_range`; **R within ±1 % of the DMM value** for both resistors on every SMU tested;
  offset current and linearity recorded.

### Abort criteria

- Deviation above 5 %, classification `open` or `short`, or compliance statuses (`C`): stop and check wiring and
  contacts before repeating. Between 1 % and 5 %: not passed; check DMM mode, temperature, `-p integration=long`.
- Cleanup `unverified` or fault latched.

### Sign-off

| SMU | R nominal | DMM value | b1500 R | deviation | run id | ok |
|---|---|---|---|---|---|---|
| | 100 kΩ | | | | | |
| | 1 MΩ | | | | | |

`L2 passed (all within ±1 %) [ ] — name ________ date ________`

---

## L3 — Known diode

### Preconditions

- L2 signed off for the anode SMU, which must be an HRSMU (recipe role `anode` is `low_current`).
- A known silicon diode with its data sheet; reference data from the same day: an EasyEXPERT I/V sweep of the same
  diode on the same wiring (−5 V → 0.8 V, 291 points, compliance 10 mA, about 1 PLC), exported as CSV; if
  EasyEXPERT is not available, the data-sheet values.
- Pin map `config\local\pinmaps\diode-l3.yaml` (copy of `diode-2t`: `anode` = the HRSMU slot, `cathode: GNDU`) and
  DUT profile `config\local\duts\diode-l3.yaml` (copy of `diode-generic` with the data sheet's maximum reverse
  voltage and forward current; it must allow 5 V reverse and 10 mA).
- Switching between EasyEXPERT and b1500 (ATV-3): before EasyEXPERT, `uv run b1500 lock status` shows the lock free
  and no harness is running; on the B1500A FlexGUI window choose Tools > Go to Local & Close (PG PDF 24), then start
  EasyEXPERT. After EasyEXPERT: File > Exit and leave the Start EasyEXPERT button (PG PDF 23).

### Commands

```powershell
uv run b1500 plan basic.diode_iv --pin-map diode-l3 --dut diode-l3 --label "M4 L3 diode"
uv run b1500 run --confirm PLAN_ID
uv run b1500 show RUN_ID --include summary --include quality
uv run b1500 analyze RUN_ID diode_fit
```

Defaults: `v_rev` −5 V, `v_fwd` 0.8 V, 291 points, compliance 10 mA, `leak_limit_a` 1 nA; adapt them to the data
sheet with `-p` (recipe ranges −20 … 0 V and 0 … 2 V) and keep the reference sweep identical.

### Expected values (proposed acceptance; the owner may tighten)

- Run `completed` (or `completed_with_flags` when the forward end reaches compliance; `C` rows are excluded from the
  fit); cleanup `verified: lop`.
- `diode_fit` reports Is, n and Rs; `leakage_at` at `v_rev` passes against `leak_limit_a`.
- Forward current at three voltages in the exponential region (e.g. 0.4, 0.5, 0.6 V) within ±5 % of the reference;
  reverse current at −5 V within a factor 2 of the reference when both are above 10 pA, else both below 10 pA.

### Abort criteria

- Compliance at a small forward voltage, reverse current orders of magnitude above the reference, deviations above
  20 %, cleanup `unverified`.

### Sign-off

`L3 passed: run id ________ n ____ Is ____ Rs ____ I(0.4/0.5/0.6 V) dev ____ / ____ / ____ reference ________ —
name ________ date ________`

---

## L4 — Known-good MOSFET vs EasyEXPERT, then promotion

### Preconditions

- L3 signed off. A known-good n-channel MOSFET (discrete or on-wafer reference) with its ratings.
- EasyEXPERT reference from the same day on the same wiring, exported as CSV: Id-Vg at Vd = 0.05 V, Vg −1 → 3 V,
  101 points; Id-Vd family with Vg 0.5 … 1.5 V in 5 steps, Vd 0 → 3 V, 101 points; Ig-Vg 0 → 3 V; about 1 PLC.
  Switch between EasyEXPERT and b1500 as in L3.
- Pin map `config\local\pinmaps\mosfet-l4.yaml` (copy of `mosfet-4t`: gate and drain on HRSMUs —
  `mosfet.gate_leakage` needs an HRSMU gate — source and bulk on GNDU; `unverified` until checked) and DUT profile
  `config\local\duts\nmos-l4.yaml` (copy of `nmos-generic` with the device's real limits).

### Commands

CLI runs (each `plan` prints a new `PLAN_ID`; each `run` prints the `RUN_ID`):

```powershell
uv run b1500 plan mosfet.idvg --pin-map mosfet-l4 --dut nmos-l4 --label "M4 L4 idvg"
uv run b1500 run --confirm PLAN_ID
uv run b1500 analyze RUN_ID vth_max_gm
uv run b1500 plan mosfet.idvd --pin-map mosfet-l4 --dut nmos-l4 --label "M4 L4 idvd"
uv run b1500 run --confirm PLAN_ID
uv run b1500 plan mosfet.gate_leakage --pin-map mosfet-l4 --dut nmos-l4 --label "M4 L4 gate leakage"
uv run b1500 run --confirm PLAN_ID
uv run b1500 runs --limit 5
```

Agent run on hardware (ATV-11, ATV-7, ATV-4): start Codex (and/or Claude Code) in the clone, after the harness
checks of [deployment-windows.md](deployment-windows.md), and ask: "Measure the Vth of the NMOS on pin map
mosfet-l4, DUT profile nmos-l4." The agent must validate, get `needs_confirmation`, show the summary verbatim and
stop. Reply "Confirmed, go ahead"; the harness then asks you to approve `run_confirmed_plan`.

- ATV-11 check: the approval prompt shows the `summary` argument; compare it with the summary in the chat, then
  approve. Fallback: if the prompt hides the arguments, approve only after comparing the summary the agent printed in
  the chat (the skill rule makes it print it verbatim; M3 scenario S4 checks that) and record this in
  [deployment-windows.md](deployment-windows.md).
- ATV-7 check (Claude Code): the prompt appears in the default permission mode. Fallback: the
  `requiresUserInteraction` flag (policy `confirmation.claude_require_user_interaction: true`) forces the prompt;
  if no prompt appears at all, do not use Claude Code for hardware runs and record it.
- ATV-4: the agent's `station_status` shows `backend: visa` (already checked at L0).

### Expected values (proposed acceptance; the owner may tighten)

- Every run: quality `ok`, cleanup `verified: lop`, error queue empty.
- Id-Vg: Id at three gate voltages above Vth within ±2 % of EasyEXPERT; Vth from the default analysis
  (`vth_linear_extrapolation`, max-gm window, Vd/2 subtracted) within ±20 mV of the same method on the EasyEXPERT
  export (state the method if EasyEXPERT's own Vth function is used instead).
- Id-Vd: Id at Vd = 1 V and 3 V on every curve within ±2 %; `output_metrics` recorded.
- Gate leakage: `leakage_at` passes; within a factor 2 of EasyEXPERT when both are above 10 pA.
- Agent run: same Vth as the CLI run within ±5 mV; no run before your approval.

### Abort criteria

- Any deviation above twice the acceptance value, gate current near its compliance, cleanup `unverified`, or the
  agent running a plan without the confirmation prompt (stop using that harness; record it).

### Promotion to `hw_validated`

Only for recipes whose stage passed: `basic.contact_resistor` (L2), `basic.diode_iv` (L3), `mosfet.idvg`,
`mosfet.idvd`, `mosfet.gate_leakage` (L4). Not in M4: `generic.smu_staircase` (ad hoc; always confirmed on
hardware), `fefet.dual_sweep_mw` (no FeFET reference yet), `system.*` (not implemented on visa), reserved recipes.

A reviewed change, made and committed by the owner or a developer, never by the agent on its own:

1. `recipes/<group>/<name>.yaml`: `status: hw_validated`; append the hardware run ids to
   `provenance.validation_runs`; add the reference (e.g. "M4 L4 vs EasyEXPERT, DATE") to `provenance.sources`.
2. Validation record: in the recipe's test card (`.agents/skills/b1500-test/cards/<family>/<card>.md`), section
   "10. Validation record", add the `hw (M4)` row: date, station (`station.yaml` `name`), DUT (part, lot or die),
   run ids, value vs reference, reviewer. Update the card's front-matter `status` to match.
3. Checks: `uv run b1500 dev recipe-check`, `uv run b1500 dev sync-harness`, `uv run b1500 dev lint-skills`,
   `uv run pytest -q -m "not hardware and not acceptance"`.
4. Commit, e.g. "M4: mosfet.idvg hw_validated (validation record)".

Effect: on visa, rule R-REC-01 no longer adds `first_hw_run` for that recipe. With a `verified` pin map, a known DUT
profile and values inside the soft limits, its plans become tier `ok` and run through `run_plan` without a prompt.

### Sign-off

| Recipe | CLI run id | agent run id | value vs EasyEXPERT | deviation | promoted (commit) |
|---|---|---|---|---|---|
| mosfet.idvg | | | | | |
| mosfet.idvd | | — | | | |
| mosfet.gate_leakage | | — | | | |

`L4 passed [ ] ATV-11 ____ ATV-7 ____ promotions committed [ ] — M4 bring-up complete — name ________ date ________`
