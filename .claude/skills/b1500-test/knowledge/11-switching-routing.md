---
domain: 11-switching-routing
maturity: seed
sources:
  - blueprint v2 0 (decision 8), 0.1 (ERSSP facts), 2.3 (routing models), 2.6 (cleanup steps 5 and 8), 2.8 (R-ROUTE)
  - "B1530A WGFMU User's Guide Ed. 8 (WG) p16, p19-20: RSU paths and the From SMU input limit (R-RSU-01, v2.1 WP21.13)"
  - "B1500 Programming Guide Ed. 15 (PG), PDF pages cited inline"
  - "16440A SMU/Pulse Generator Selector User's Guide Ed. 6 (SEL), PDF pages cited inline"
  - lwp/matlab_B1500/lib/SPGU_pulse.m (ERMOD 1, ERSSP 0..3 to PGU and back to SMU)
  - src/b1500_test_agent/models/routing.py, session/routes.py, driver/ops/switch.py (v2 WP9.2)
  - skill b1500-bringup stages/l7-spgu-selector.md (wiring record, WP9.6)
last_reviewed: null
---
<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->

# Switching and routing (knowledge domain 11)

How a DUT terminal reaches an instrument resource through a switch accessory, how the kernel switches it, and why
every run ends with every switch at rest. The human cables and records the switches; the agent only plans routes
through declared outputs and never claims a wiring it cannot read back.

## Contents

- [Switches in the station profile](#switches-in-the-station-profile)
- [Routes and phases](#routes-and-phases)
- [The 16440A selector](#the-16440a-selector)
- [SCUU and ASU paths](#scuu-and-asu-paths)
- [RSU of the WGFMU](#rsu-of-the-wgfmu)
- [Guard and rules](#guard-and-rules)
- [Cleanup and verification](#cleanup-and-verification)
- [Selector check and recording the wiring](#selector-check-and-recording-the-wiring)
- [Simulator behaviour](#simulator-behaviour)
- [Troubleshooting routes](#troubleshooting-routes)

## Switches in the station profile

- `config/local/station.yaml#switches` lists each accessory: `id` (`SEL1`), `kind` (`selector_16440a`, `scuu`, `asu`,
  `rsu`), `present` (`true`, `false`, `null` = unknown), `certainty` (`verified` only after a human checked the
  wiring), `ports` (DUT-side output name -> hardware index and the channel on each input side) and `rest` (the state
  the cleanup restores).
- Index: a selector output's `ERSSP` port (0-3); an SCUU or ASU output's SMU channel; an RSU's WGFMU channel.
- Inputs: `{smu: 3, pgu: 101}` = SMU3 Force on the SMU input, SPGU channel 101 on the PGU input; `null` = wiring
  not recorded. The lab example keeps both selector inputs `null` until bring-up stage L7.
- A pin map reaches a terminal through a switch with the target `"<id>.<output>"` (`gate: SEL1.OUT1` in
  `fefet-sel`); a role bound there needs the route `SEL1.OUT1 -> smu|pgu` for its resource.
- States per kind: selector `open smu pgu pgu_open`; SCUU `open smu cmu` per output; ASU `smu cmu` (`cmu` = the AUX
  input); RSU `open smu wgfmu`.

## Routes and phases

- A route is one switch output in one state (`SEL1.OUT1->pgu`). A plan carries the routes it may set
  (`envelope.routes`) and the routes it applies per phase (`routes_by_phase`, e.g. `program: [SEL1.OUT1->pgu]`,
  `read: [SEL1.OUT1->smu]`); `validate_plan` shows them in `resolved` and the summary (`routes SEL1.OUT1->pgu,smu`).
- A kind applies one phase at a time (`Transaction.apply_routes`): every route of the phase passes the guard before
  the first byte is written, then `ERMOD 1` + `ERSSP` (selector), one `SSP` per SCUU, `SAP` per ASU; the transaction
  waits the relay settle time and reads every touched output back. A wrong read-back stops the run
  (`RouteNotVerified`); the cleanup then restores everything.
- One terminal takes one source per phase: two non-rest states of one output in one phase are blocked.
- Kinds that route their roles: the composite `stress_measure` (ASU and selector paths, one `setup` phase) and
  `spgu_pulse` (`route_only`: the selector check; `pg`/`alwg`: phase `pulse` to PGU, phase `rest` back, see
  [09](09-pulse-spgu-selector.md#running-a-train)). Kinds that do not route (the v1 SMU kinds, `smu_spot`) cannot use
  a pin map with switch targets: R-PIN-01 blocks the plan instead of mis-sourcing it.

## The 16440A selector

- Two selectors at most (the second one is the expander, chained by the control cable): ports 0/1 = output 1/2 of
  the first, 2/3 = output 1/2 of the second (PG p433 (4-115) "ERSSP"). The B1500A drives them through the digital
  I/O port and the 16445A adapter (SEL p30 (24) "16445A").
- `ERSSP port,status` needs the 16440A control mode `ERMOD 1` (PG p419 (4-101) "ERMOD"); status 0 all open (initial
  setting), 1 SMU on, 2 PGU on, 3 PGU open; `ERSSP? port` answers the same codes (PG p434 (4-116) "connection
  state"). `ERMOD?` answers the sum of the enabled modes (PG p421 (4-103) "sum of mode values").
- PGU open exists only on CH 1 of each selector (ports 0, 2): the PGU mechanical relay stays closed and a durable
  semiconductor relay opens, for frequent PGU open/connect switching (PG p154 (2-66) "semiconductor relay";
  SEL p10 (4) "PGU open"). `pgu_open` on port 1 or 3 is refused by the builder, the guard and R-ROUTE-01.
- The SMU input carries Force only; Sense must stay open (PG p154 (2-66) "Sense terminal must be open"). A Kelvin
  role never goes through a selector: R-ROUTE-01 blocks it.
- Ratings: SMU input 200 V / 1 A, PGU input 40 V / 0.4 A peak to peak into 50 Ohm (SEL p27 (21) "Maximum Voltage");
  residual resistance 0.2 Ohm (SMU path) and 3.4 Ohm (PGU path), leakage below 100 fA at 100 V (SEL p29 (23)
  "Residual resistance"). The kernel's 42 V / 100 mA ceiling stays far below.
- Power-on and `*RST`: control mode off and every output open is the assumption (ATV-18). The kernel never relies
  on it: every route and every cleanup sends `ERMOD 1` and reads `ERSSP?` back. `TODO(verify)` at L7.
- The manual gives no switching time; the kernel waits 10 ms after a selector change (relays break before make)
  `TODO(verify)` at L7.
- Lab code (`lwp` `SPGU_pulse.m`): `ERMOD 1`, all four ports `ERSSP p,2` before the pulses, `ERSSP p,1` after. The
  kernel does the same per declared output, through the guard, verified, and returns to `rest` (open) afterwards.
  `IV_sweep.m` sends `ERSSP p,0` (all open), not "to SMU".

## SCUU and ASU paths

- SCUU: one `SSP cmu,path` sets both outputs (1 Force1 only, 2 Force2 only, 3 both SMUs, 4 CMUH/CMUL; PG p520 (4-202)
  "SSP"); output 1 is fed by the SMU in slot `cmu - 1`, output 2 by `cmu - 2`. Making a connection switches that
  unit's output on, and SMU <-> CMU changes reset the SMU (ATV-27), so every `SSP` is a guarded route. There is no
  `SSP?`: `*LRN? 81` reads the path back. Both outputs open (power-on) counts as rest: no `SSP` path sets it, it
  connects nothing, and the cleanup does not switch SMUs on just to reach the rest path.
- ASU: `SAP ch,0` = SMU side (initial; `CN` and `CL` return it there), `SAP ch,1` = AUX input (PG p505 (4-187)
  "SAP"); read back with `*LRN? 62`. An ASU always rests on its SMU side. Its 1 pA range is a ranging matter
  (R-ASU-01), not a route.
- An SCUU or ASU that does not answer its `*LRN?` read-back is not installed: nothing to restore, and a plan routing
  through it is blocked (its state is unreadable before the run).

## RSU of the WGFMU

- The B1531A remote-sense and switch unit sits near the probes, one per WGFMU channel (station `switches` kind `rsu`,
  `RSU201`/`RSU202`, `ports.OUT: {index: 201, inputs: {wgfmu: 201, smu: <SMU or null>}}`). Normally it connects its
  From SMU input to the output; while its channel outputs or measures, the WGFMU (WG p19 (1-7)). The output takes
  +-10 V from the WGFMU and +-25 V from the SMU (WG p20 (1-8)).
- The WGFMU instrument library switches it (`connect` enables the channel and its RSU, WG p85 (4-15); `disconnect`
  gives the output back to the SMU path), never FLEX; FLEX snapshots do not read it, and the library cannot read the
  relay back, so a state is what the library accepted. Before execute the transaction disconnects every declared RSU
  channel (a refused disconnect leaves the output unread: R-ROUTE-01 blocks); during the run each channel's RSU is
  on `wgfmu` (`smu` in SMU mode); cleanup step 3 (blueprint v2 2.6) aborts, initializes and disconnects every
  channel and closes the session.
- An SMU through an RSU (the DC reference of fast I-V, the SMU bias of a combined recipe) needs that SMU's Force
  cable on the From SMU input, recorded as `inputs.smu` (ATV-32); recabling only with the DUT lifted. The V Monitor
  (BNC) shows the WGFMU output to a high-impedance scope and is grounded while the RSU is on its SMU path.
- The From SMU input takes at most +-25 V, or the RSU is damaged (WG p20 (1-8)), and the SMU path 100 mA (WG p16
  (1-4) "SMU mode"), in every RSU state. So the SMU recorded there (SMU4/SMU3 in the lab layout after L8) stays
  within +-25 V and 100 mA in every plan, whatever the pin map calls it (`mosfet-4t` on an RSU landing drives SMU4
  and SMU3 through the RSUs): R-RSU-01 blocks more, the guard refuses it. Work above 25 V (BDV, TDDB, SILC,
  breakdown search) needs an SMU no RSU is cabled to; ask the human for that landing, never invent one.
- Firmware code 3001 "RSU is not connected": wrong channel number or no RSU on that channel (WG p152 (4-82)).
  Symptoms and checks: runbook `wgfmu-rsu-route` (skill `b1500-debug`); the stage check is bring-up L8.

## Guard and rules

- `OutputGuard.check_route`: a route of the plan or a declared output returning to its switch's `rest` state;
  `pgu_open` only on CH 1. A violation sends nothing (`EnvelopeViolation`).
- R-PIN-01: a role's switch target is declared, not absent, can connect the role's resource, its input wiring is
  recorded (not `null`), and the route is in `envelope.routes`.
- R-ROUTE-01 (plan): every route resolves (declared switch and output, a state it can take); on hardware the switch
  is recorded `present: true`; phases apply only allowed or rest routes and use every allowed one; one source per
  terminal per phase; no Kelvin role through a selector. Pre-execute: every output of the involved switches and every
  declared selector port reads a rest state (`ERSSP?` after `ERMOD 1`, `*LRN? 81/62`), else blocked ("run
  safe_shutdown").
- R-ROUTE-02: any route through an `unverified` switch, or a switch target in an `unverified` pin map, needs
  confirmation (`unverified_topology`).
- R-RSU-01: an SMU recorded on an RSU's From SMU input above +-25 V or 100 mA is blocked; so is an RSU route to
  `smu` whose input is `null`; on hardware, while any RSU input is `null`, every SMU plan above those limits is
  blocked (it may be the SMU cabled there) until the human records the wiring at L8 (the SMU channel, or the `smu`
  side deleted when nothing is cabled). The guard refuses the same levels per command (`rsu_input_exceeded`).

## Cleanup and verification

- Every transaction ends with the v2 cleanup: `AB` -> `SPP` -> MFCMU `DCV 0`/`ACV 0` + `DZ` -> **routes to rest**
  (`ERMOD 1` + `ERSSP port,rest` per declared selector port; `SSP` to the rest path when an SCUU output is on a
  non-rest input; `SAP ch,0` when an ASU is on AUX) -> `CL` -> `ERRX?` drain -> verify (outputs off and **every
  declared output reads a rest state**: `ERSSP?` per port, `*LRN? 81`, `*LRN? 62`). The manifest's
  `cleanup.switches_after` lists what was read; `safe_shutdown` runs the same list.
- A switch that will not return (stuck relay, lost control: sim fault `selector_stuck`) fails the verification after
  the retry: the fault latches (`cleanup_unverified`). Only a human clears it, after looking at the hardware.
- `station_status` shows each declared output as its state (at rest) or `off rest: <state> (rest <rest>)`; a selector
  whose control mode is off reads `not read` (the status snapshot sends no setting).

## Selector check and recording the wiring

- `system.selector_check` (card `spgu/selector-check`, stage L7): every declared selector output on its own through
  SMU on, PGU on, PGU open (CH 1) and back to rest, each state read back and held `dwell_s` while the human listens
  to the relays and watches the front-panel LEDs (SEL p12 (6) "LEDs"). No output is on: `LOP?` and `SPST?` are
  checked first, the envelope has no channel.
- It needs no recorded inputs, so it is how the human maps the wiring at L7: which SMU and SPGU channel feed each
  selector input, which pad each output reaches. Until they are recorded, plans through a selector input stay
  blocked on hardware (R-PIN-01; ATV-28).
- Recording (stage L7): the human gives the wiring in chat; the agent runs `uv run b1500 bringup propose-station`,
  writes the inputs into `work/bringup/station.proposed.yaml` (`switches[].ports.OUTn.inputs: {smu: <ch>, pgu:
  <ch>}`), shows the diff and stops; only the human adopts it into `config/local/station.yaml`. The selectors stay
  `certainty: unverified` (every routed plan confirms `unverified_topology`) until the human has seen pulses on the
  right pad at L7 and marks them `verified` in a second adoption. The agent never writes `config/local/`.
- The 16440A is driven only by `ERMOD 1` + `ERSSP` and read by `ERSSP?`; the raw digital I/O commands (`ERM`, `ERC`,
  `ERS?`) are out of scope (blueprint v2 1.2).

## Simulator behaviour

- Scenarios describe the cabling (`selectors: {0: {smu: 3, pgu: 101}}`) and wire a pad to an output
  (`gate: SELPORT0`); `fefet_lab` puts the FeFET gate on port 0 (SEL1.OUT1), `lab_station` cables both selectors
  with nothing on their outputs.
- A pad on a selector output sees the channel its state connects (SMU level and current, or the SPGU's static and
  pulse levels); open, PGU open, an uncabled input or a relay within its 10 ms settle time leave it floating, so an
  SMU on the wrong path reads its noise floor.
- `ERSSP` without `ERMOD 1`, a bad port or status, or PGU open on CH 2 queue error 120 (simulator convention: the
  manual names the condition but no code).
- Plans bind against the station profile with one simulator-only addition: a selector input recorded `null` takes the
  scenario's cabling of that port (`ConfigBundle.planning_station`), so the lab example rehearses routed plans
  (still `unverified_topology`); an RSU's `null` From SMU input takes the scenario's `rsu_smu` (`nmos_wgfmu`,
  `nmos_bti`: SMU4 -> RSU201, SMU3 -> RSU202), so there SMU4/SMU3 stay within +-25 V (R-RSU-01). On hardware a `null`
  input blocks (R-PIN-01, R-RSU-01) until the human records it.

## Troubleshooting routes

| symptom | likely cause | first safe check |
|---|---|---|
| plan blocked "is pgu, not its rest state" | an earlier run or a human left a selector switched | `safe_shutdown`, then `station_status` |
| run failed `RouteNotVerified` | stuck relay, control cable, adapter power | `safe_shutdown`; `system.selector_check`; ask the human to look at the LEDs |
| fault latched, `switches_after` not open | selector will not return to rest | keep the fault; skill `b1500-debug` (`cleanup-failed-fault`) |
| SMU read through a selector at the noise floor | route on PGU or open, wrong port wired | `station_status` switches; the pin map's switch target; selector check |
| plan blocked "input ... not recorded" | selector input wiring `null` | bring-up L7 (selector check, human records wiring) |
| plan blocked R-RSU-01 "From SMU input" | an SMU on an RSU input above 25 V, or the RSU input `null` (hardware) | stay within 25 V, or the human's landing on an SMU no RSU is cabled to; L8 records the RSU inputs |
