# Safety model

How the B1500A test agent decides what may run, who must confirm it, and what happens when something goes wrong.
Source: blueprint §4 (rules, tiers, confirmation, residual risks), §2.4 (transaction and fault latch), §2.5 (rules
API) and §3 (the simulator invariant). **Status:** the rules engine, the built-in rules, tiers and the plan summary
are implemented (WP1.4, `src/b1500_test_agent/rules/`), and so are the session and fault latch (WP1.6), the
executor (WP1.7), the service, MCP tools and CLI that call them (WP1.8) and the harness wiring (WP1.9: Codex
`forbidden` rules, Claude Code permission rules and the `PreToolUse` guard hook). v2 (blueprint v2 §2.5, §2.8, §2.9;
WP5.4): the guard's pulse, AC, route and waveform checks, the v2 rules, the confirm reasons `soft_pulse`, `soft_cmu`,
`long_run`, `physical_setup`, `unverified_topology` and the v2 plan summary are implemented and tested on synthetic
plans; the module work packages (M7–M10) make them live by compiling such plans and filling the live fields.
Asynchronous runs (blueprint v2 §2.6; WP5.6): R-RUN-02 and R-CAL-02 are live, runs report progress and stop at a
checkpoint when any process calls `safe_shutdown` (section "Async runs and their residuals").

## Principles

- The instrument is never a raw command endpoint. There is no MCP tool or CLI command that passes FLEX text
  through; the only FLEX console (`b1500 dev sim-console`) refuses every backend except the simulator.
- Safety is enforced in the Python core, not in prompts. Skills and `AGENTS.md` make the agent behave well; the core
  makes misbehavior ineffective within the limits below.
- Limits are data owned by a human (`config/local/`), with a hard ceiling in code that configuration can only
  tighten.
- Every action is auditable: plan, tier, confirmed summary, config-file hashes, every transport I/O, cleanup steps.
- The simulator is the default backend. An example config file can never select the real (`visa`) backend.

## Where checks happen

1. **Plan rules** (`validate_plan`, and again without I/O at the start of every run): recipe status, parameter
   ranges, pin map and DUT profile, module specs, hard and soft limits, compliance, run size. If a live snapshot
   is available at validation, the live-state rules run too and report problems early.
2. **Pre-execute rules** under the instrument lock with fresh live state: no latched fault, instrument identity and
   module inventory match the station profile, interlock state, pre-existing instrument errors, calibration state
   (the auto-calibration switch is read with `*LRN? 31` before every run).
3. **`OutputGuard`** on every single source command: the channel must be in the plan's allowlist, the level and
   compliance inside the compiled envelope, the compliance non-zero. v2 adds a check per source family, each
   refusing before anything reaches a transport (FLEX bus or WGFMU library): `check_pulse` (SPGU and SMU pulse
   trains: the level at the DUT including the `SER` divider, width, duty, pulses and on-time per start; a count
   below 1, i.e. free run, is refused), `check_ac` (MFCMU AC level, DC bias, frequency), `check_route` (a switch
   route is one of the plan's routes or returns a declared output to its `rest` state; `pgu_open` only on selector
   CH 1) and `check_waveform` (every WGFMU level, the 10 ns grid, the vector count and time, before `add_vectors`).
4. **Quality classification** after the run: each data point's status code makes it ok, limited or untrusted.

Configuration is re-read (by digest) on every service call, so a rule change applies to the next call.

## Limits and defaults

`config/policy.example.yaml` (conservative; a human may tighten them in `config/local/policy.yaml`):

| Setting | Default | Effect |
|---|---|---|
| `hard_limits` | 42 V, 100 mA compliance | Above → `blocked`. Code ceiling `HARD_CEILING_V = 42.0`, `HARD_CEILING_A = 0.1`; a policy above it is invalid config |
| `soft_limits` | 10 V, 10 mA compliance | Above → `needs_confirmation` (reason `soft_limit`) |
| `interlock.required_above_v` | 42 V | Above → the interlock must be recorded as working and be closed |
| `run_limits` | points per run: SMU 10,001, CMU 10,001, WGFMU 4,000,000 per channel (a v1 integer applies to all); 300 s per synchronous run; async above 300 s, confirmation above 600 s (`long_run`), block above 24 h; segments ≤ 30 s | Points above → `blocked` (R-RUN-01, R-WG-02); a synchronous plan above 300 s, an async plan above 24 h or with segments above 30 s → `blocked`; above 600 s → `needs_confirmation` (`long_run`, R-RUN-02; the planner sets `mode: async` above 300 s, WP5.6) |
| `pulse` | 5 V at the DUT, 10,000 pulses, 60 s on-time, duty 0.5 | Above → `needs_confirmation` (`soft_pulse`, R-PULSE-03) |
| `cmu` | 10 V DC bias, 50 mVrms AC | Above → `needs_confirmation` (`soft_cmu`, R-CMU-01) |
| `corrections` | phase + open + short, at most 8 h old (a policy may add `load`, never drop one) | C-V without them → `blocked` (R-CORR-01) |
| `plans.ttl_h` | 24 h | Older plans must be validated again |
| `quality` | ok `N`; limited `C T`; untrusted `V X F D G S U` | Limited points are excluded from fits; extraction from untrusted data is refused unless forced, and then flagged |

Limits compare magnitudes and are exclusive: a value equal to a limit passes (10 V is `ok`, 42 V needs
confirmation, 42.5 V is `blocked`). Every voltage and current check runs over the plan's compiled envelope, the
same per-channel numbers the `OutputGuard` enforces, so the rules and the guard cannot disagree. Module
specifications from the manuals (voltage, current and V-I envelope per SMU type; v2 rows for the HV-SPGU, SMU
pulses, WGFMU, MFCMU, SCUU and ASU, each citing its manual page, `driver/modules.py`) block a plan regardless of
policy. Pulse and waveform rules read the channel's pulse/waveform envelope (what the guard enforces) and the kind's
**source plan** (`plan.program["sources"]`, `models/sources.py`: the nominal pulse trains and the WGFMU waveform
program, hashed with the plan).

## Implemented rules (blueprint §4.2)

Each rule is one function in `rules/builtin/` (`core.py`, `limits.py`, `run.py`, `pulse.py`, `route.py`, `cmu.py`,
imported in this order, which is the finding and summary-flag order),
registered with a stable id. Thresholds come only from the config
files, recipe parameter ranges and the code tables named below. Every finding carries the rule id, severity,
message, observed value, limit and **source**: the resolved file and key (`config/local/policy.yaml#soft_limits.
voltage_v`, or `config/policy.example.yaml#...` when the simulator runs on the committed examples), the recipe field
(`recipes/mosfet/idvg.yaml#params.vg_stop.range`), a code constant (`code:...`), the live snapshot (`live:...`), the
plan (`plan:...`) or a state file (`data/state/fault.json`). "pre" = `pre_execute`.

| Id | Phase | Check | Outcome | Source key |
|---|---|---|---|---|
| R-CFG-01 | plan, pre | Policy hard limits within the code ceiling; backend `visa` only with `config/local/{settings,station,policy}.yaml` and no `B1500_CONFIG_DIR`; the plan's backend is the configured one; the policy, station, pin map and DUT profile in the rule context are the loaded ones. Files that do not parse or validate never reach the engine: the loader reports `invalid_config`, and `config_findings()` turns each problem into an R-CFG-01 block | block | `policy.yaml#hard_limits.*`, `settings.yaml#backend`, the config file |
| R-FAULT-01 | plan, pre | No latched fault; no unrecovered in-flight marker | block | `data/state/fault.json`, `data/state/inflight.json` |
| R-REC-01 | plan | Effective recipe status for the backend: `not_implemented` (including a kind missing on this backend) → block; on visa `draft` → `draft_recipe`, `sim_validated` → `first_hw_run`, `generic.*` → `adhoc_recipe`; on sim `draft` → warn | block / confirm / warn | recipe `#status`, `#kind`, `#id` |
| R-PARAM-01 | plan | Every requested parameter is declared, every declared one has a value, and type, choices, range and unit match the recipe's `ParamSpec`; resolved values equal the requested ones; a `file` parameter is a `recipes/waveforms/` or `work/waveforms/` CSV path the planner read (exists, inside its folder after links, at most 1 MiB; its sha256 is in the plan) | block | recipe `#params.<name>.{range,type,choices,unit}`, `plan:resolved_params.<name>`, `plan:files.<name>` |
| R-PIN-01 | plan | Pin map exists; every non-optional role is mapped to a channel, the GNDU, an MFCMU side (`7H`/`7L`, only for `cmu_high`/`cmu_low` roles, which need one) or a switch output (`SEL1.OUT1`); the plan binding agrees with the pin map and the station profile; channels exist and are used once; module type allowed by the role (default: the types of its function); `low_current` needs an HRSMU; the GNDU only for `ground` roles with `allow_gndu`; through a switch: the switch is declared and not absent, can connect the role's resource to that output, the channel on that input is recorded (not `null`) and the plan sets that route (`envelope.routes`; kinds without routing cannot use such a terminal); every envelope channel belongs to its bound role | block | `pinmaps/<name>.yaml#terminals.<role>`, `station.yaml#modules`, `station.yaml#switches[i].*`, recipe `#roles.<role>.*`, `plan:envelope.{channels.<ch>,routes}` |
| R-PIN-02 | plan | Pin map `certainty: unverified` | confirm `unverified_pin_map` | `pinmaps/<name>.yaml#certainty` |
| R-INV-01 | pre (plan with a snapshot) | A live snapshot exists and comes from the plan's backend; identity model = station mainframe; the module model in every bound slot = station profile | block | `station.yaml#mainframe.model`, `station.yaml#modules[i].model`, `live:snapshot`, `live:identity`, `live:inventory` |
| R-LIM-01 | plan | Per envelope channel: an SMU's \|V\|, \|I\| and V-I corners (voltage forcing: \|V\| with \|Icomp\|; current forcing `sweep_i`/`bias_i`/`step_i`/`sync_i`: \|I\| with \|Vcomp\|, the I-source corners); an HV-SPGU's 40 V open load, a WGFMU's 10 V, an MFCMU's 25 V DC bias; a role function the module cannot serve refuses; summed compliance within the GNDU's 4.2 A when a role uses the GNDU | block | `code:b1500_test_agent.driver.modules.MODULE_SPECS[<type>] (<manual tables>)`, `…SPGU_SPEC.max_open_v`, `…WGFMU_SPEC.max_abs_v`, `…CMU_SPEC.max_dc_v` |
| R-LIM-02 | plan | Per envelope channel: \|V\| ≤ `hard_limits.max_abs_voltage_v`, \|Icomp\| ≤ `hard_limits.max_abs_compliance_a`, never above the code ceiling; non-finite values block | block | `policy.yaml#hard_limits.*` (`code:...HARD_CEILING_*` if a policy object exceeds the ceiling) |
| R-LIM-03 | plan | Per envelope channel above `soft_limits.voltage_v` / `soft_limits.compliance_a` | confirm `soft_limit` | `policy.yaml#soft_limits.*` |
| R-DUT-01 | plan | A recipe with DUT roles needs a named, existing DUT profile that describes every driven terminal (else block); \|V\| or \|Icomp\| above a terminal's envelope → confirm; DUT device type not among the recipe's → warn | block / confirm / warn | `plan:request.dut_profile`, `duts/<name>.yaml#terminals.<t>.max_abs_{v,i}` |
| R-COMP-01 | plan | Every connected channel has an envelope with non-zero compliance; voltage-forcing roles (`sweep_v`, `bias_v`, `step_v`, `sync_v`, `pulse_v`) set `icomp`, current-forcing roles (`sweep_i`, `bias_i`, `step_i`, `sync_i`) set `vcomp` explicitly and non-zero; the envelope compliance is `max_abs_i` of a voltage-forcing channel and `max_abs_v` of a current-forcing one (whose `max_abs_i` is the forced current, 0 A for a voltmeter; WP7.1); `pgu`/`wgfmu` roles are exempt (R-PULSE-*, R-SPGU-01, R-WG-* bound them) | block | recipe `#roles.<role>.settings.{icomp,vcomp}`, `plan:envelope.channels.<ch>.{max_abs_i,max_abs_v}` |
| R-IL-01 | plan, pre | When the envelope's max \|V\| exceeds `interlock.required_above_v`: the station records `interlock.available: true`; with live state, status-byte bit 3 is clear **and** no `ERRX?` 202/203 is pending (ATV-10 fallback); at pre a missing status byte blocks | block | `station.yaml#interlock.available`, `live:status_byte.bit3`, `live:errors` |
| R-GNDU-01 | plan | When a role uses the GNDU: the compliances of the SMU channels plus the expected currents of the sources without compliance (a pulse channel's short-circuit bound; an HV-SPGU without one 40 V / 50 Ω, a WGFMU 100 mA) ≤ 4.2 A | block | `code:…MODULE_SPECS[GNDU] (UG GNDU, PDF 58)` |
| R-RUN-01 | plan | Points ≤ `run_limits.max_points.<family>` (the smallest over the measuring families of the bound channels: `smu`, `cmu`; WGFMU points count per channel in R-WG-02; a v1 integer applies to every family) | block | `policy.yaml#run_limits.max_points.*` |
| R-RUN-02 | plan | Estimate above `max_sync_run_s`: an `async` plan (info; the planner sets `mode: async` there) or a blocked `sync` one; above `long_run_confirm_s` → confirm; above `max_async_run_s` → block; an async plan has checkpoints (`estimate.max_segment_s`, e.g. one sweep of a stepped run) at most `segment_max_s` apart, a kind without checkpoints cannot run asynchronously | info / confirm `long_run` / block | `policy.yaml#run_limits.*`, `plan:estimate.max_segment_s` |
| R-ALWAYS-01 | plan | Recipe `always_confirm` reasons (`destructive`, `system_self_test`, `system_self_cal`, `physical_setup` ...); kind `cmu_correction` always `physical_setup` (declared or not); a `file` parameter from `work/waveforms/` (ad-hoc waveform) | confirm (that reason; `adhoc_recipe` for the file) | recipe `#always_confirm`, `code:…run.PHYSICAL_SETUP_KINDS`, `plan:files.<name>` |
| R-ERRX-01 | pre (plan with a snapshot) | Pre-existing `ERRX?` entries drained by the snapshot are recorded | warn | `live:errors` |
| R-CAL-01 | pre | Auto-calibration state and the last completed self-calibration (archive) are recorded | warn if unknown, else info | `live:auto_calibration`, `data/runs/index.jsonl` |
| R-CAL-02 | pre | An async run records the auto-calibration state (`*LRN? 31`); the run sends `CM 0` before the kind and the cleanup's `restore` step puts the state back after a verified cleanup (an unverified cleanup leaves it off) | info | `live:auto_calibration` |
| R-PULSE-01 | plan | Every pulse channel (`pulse_v`, `pgu`, or a pulse envelope) has a pulse envelope and compiled trains; each train inside its module spec (HV-SPGU: levels ±40 V at 1 mV, period 20 ns–10 s, width 10 ns–period−10 ns, delay, transitions 8 ns–0.4 s, resolutions, width ≥ leading/0.8, period ≥ delay + width + trailing/0.8, count 1–10⁶ or duration 1 µs–1 year, `SER` 0.1 Ω–1 MΩ; SMU: the `PT` table, 500 µs–2 s on HR/MP, period ≥ width + 2/10 ms; WGFMU: 10 ns grid) and inside the channel's pulse envelope; free run cannot be expressed; trains on a non-pulse channel and an invalid source plan block | block | `code:…SPGU_SPEC`, `…SMU_PULSE_SPECS[<type>]`, `…WGFMU_SPEC`, `plan:envelope.channels.<ch>.pulse.*`, `plan:program.sources` |
| R-PULSE-02 | plan | The pulse channel's DUT terminal declares a `pulse` envelope (missing → block, never invented); open-load level, width, duty, pulses per run outside it → confirm | block / confirm `dut_envelope` | `duts/<name>.yaml#terminals.<t>.pulse.*` |
| R-PULSE-03 | plan | Above `policy.pulse` (level at the DUT, pulses per run, time at the pulse level, duty) | confirm `soft_pulse` | `policy.yaml#pulse.*` |
| R-SPGU-01 | plan | HV-SPGU channels: every train sets `SER` (recipe `load_ohm`); open-load voltage `\|V\|·(SER+50)/SER` ≤ 40 V, the hard \|V\| limit and the terminal's pulse `max_abs_v`; a `high_z` terminal needs `SER` ≥ 1 kΩ; short-circuit current `V_open/(50 + min_series_ohm)` ≤ the hard compliance limit unless the terminal is `high_z` (then an info residual shown in the summary); every channel's bound is recorded (info) | block / info | `code:…SPGU_SPEC.*`, `policy.yaml#hard_limits.*`, `duts/<name>.yaml#terminals.<t>.{pulse.max_abs_v,impedance}` |
| R-WG-01 | plan, pre | WGFMU roles reach the DUT through their RSU (`RSU<ch>.OUT`, state `wgfmu`); on visa the library probe is loadable (x64; a 32-bit DLL → "install library ≥ A.03.00"); the bound channels are among `WGFMU_getChannelIds` (required before execution) | block | `pinmaps/<name>.yaml#terminals.<t>`, `live:wgfmu_library`, `live:wgfmu_channels` |
| R-WG-02 | plan | The waveform program fits the module and the plan: channel setups for every WGFMU role and nothing else; PG mode only 3 V/5 V ranges, current measurement only in Fast IV/DC (3302/3303); ≤ 2,048 vectors per pattern (3307), ≤ 512 sequences per channel (3305), no empty pattern (3306), counts 1–1.1·10¹² (3309); vector times 10 ns–10995 s on the 10 ns grid (3311); levels in the force range (3310) and the envelope; measure events inside their pattern, interval 10 ns–1.342 s (3312), average 0 or 10 ns–20.97 ms (3315) and ≤ interval (3316); range events only with Fast IV current measurement, outside averaging windows, three or more > 2 µs apart; stored values per channel ≤ `max_points.wgfmu` and ~4 M; the program inside the channel's `WaveformLimits` | block | `code:…WGFMU_SPEC`, `policy.yaml#run_limits.max_points.wgfmu`, `plan:envelope.{waveform,channels}.<ch>`, `plan:program.sources.waveform` |
| R-ROUTE-01 | plan, pre | Every route of the plan (allowed routes, routes per phase, role `via`) resolves to a declared switch output that can take the state (`pgu_open` only on CH 1, ports 0 and 2); on visa the switch is `present: true`; phases apply only allowed routes or `rest` and name every allowed route; one source per switch output per phase; Kelvin roles never through a selector (Force only); pre: every output of the involved switches and every present selector port reads back its `rest` state | block | `station.yaml#switches[i].*`, `plan:routes_by_phase.*`, `plan:envelope.routes`, recipe `#roles.<role>.kelvin`, `live:switch_states.<switch>.<output>` |
| R-ROUTE-02 | plan | A route through a switch recorded `certainty: unverified`, or switch outputs mapped by an `unverified` pin map | confirm `unverified_topology` | `station.yaml#switches[i].certainty`, `pinmaps/<name>.yaml#certainty` |
| R-ASU-01 | plan | A role's measurement range (setting `irange`, or `asu_1pa: true` = the 1 pA range; live since WP7.1: `mosfet.gate_leakage` option `asu_1pa`) exists on its SMU; a range that needs an ASU (1 pA HRSMU, 1–100 pA B1511B MPSMU) only with a declared ASU recorded `present: true`. On the instrument a missing ASU makes `RI ch,8` an error, which the kind's `ERRX?` drain turns into an abort before `XE` | block | `station.yaml#switches[i].present`, `code:…MODULE_SPECS[<type>]` |
| R-CMU-01 | plan | Every MFCMU source role (`cmu_high`) has an AC envelope inside the module (1 kHz–5 MHz, 10–250 mVrms, \|DC\| ≤ 25 V), the hard \|V\| limit and the `ac` envelope of every DUT terminal on the MFCMU (missing → block); above `policy.cmu` → confirm | block / confirm `soft_cmu` | `code:…CMU_SPEC (UG p73 (2-33))`, `duts/<name>.yaml#terminals.<t>.ac`, `policy.yaml#cmu.*` |
| R-CORR-01 | plan, pre | Capacitance (MFCMU) plans, except the correction recipes themselves: for every MFCMU used, records of each kind in `corrections.require` (default phase, open, short) from the server-written correction store, measured with this station profile and pin map, at most `corrections.max_age_h` old at validation, every plan frequency covered by some fresh record; the age of the oldest record in use is recorded (info, `corr <age>` in the summary); pre (and at validation with a snapshot): `CORRST?` on for every required open/short/load, phase compensation in effect, the records' `*IDN?` = the instrument's | block / info | `policy.yaml#corrections.*`, `data/state/corrections/<cmu>.json`, `live:cmu_corrections.<cmu>.*`, `live:identity` |
| R-QUAL-01/02/03 | post | Per-point status counts by class (info); limited points, excluded from fits (warn); untrusted points, extraction refused unless forced (warn), with the meaning of each letter. Unknown status letters count as untrusted. MFCMU `EEE` codes map to letters (A/D overflow or invalid → `V`, IV amplifier saturation → `D`, NULL loop unbalance → `U`; `cmu_status_letter`), WGFMU flags too (range overflow → `V`, error → `X`; `wgfmu_status_letter`) | report | recipe `#quality` or `policy.yaml#quality` |

How the engine evaluates (`RulesEngine.evaluate(ctx, phase)`):

- Rules run in table order and keep their own finding order, so the same plan and config always give the same
  report. The report records the phase, tier, confirm reasons, the policy file's sha256 and the evaluation time.
- A rule that raises, returns something that is not a finding, or asks for confirmation outside the plan phase
  becomes a `block` finding of that rule: the engine fails closed.
- Rules return drafts; the engine stamps them with the registered id, so a rule cannot report for another one.
- Live-state rules only block or warn. Confirmations come from plan rules over config and plan content, which keeps
  the summary identical between validation and run.
- R-QUAL-* is not an evaluation phase. `RulesEngine.quality(counts, recipe=...)` classifies a run's status counts;
  the analysis layer owns the detailed quality report and the extraction gate (rules never import `analysis`).

**Interlock (ATV-10).** The Programming Guide (status byte, PDF 76–77) describes bit 3 as set when the interlock is
open *and* a high-voltage output is requested, and cleared by a serial poll, `*RST` or a device clear: it latches an
event rather than showing the interlock's level. The ATV-10 fallback therefore applies from the start: R-IL-01 also
blocks on `ERRX?` errors 202 ("Interlock circuit must be closed") and 203 ("Cannot enable channel", PDF 577), and
measurement kinds call `rules.builtin.interlock_errors()` after `CN` and abort on a hit. With the default policy the
rule is unreachable (R-LIM-02 caps \|V\| at 42 V), but an owner who lowers `interlock.required_above_v` makes it
active. The real bit behavior is verified at M4 L0. Because the station never uses the interlock and a clear bit says
nothing about the circuit on hardware, `station_status` carries an `interlock` label (WP6.2): `SIMULATED open|closed`
on the simulator (whose bit mirrors the scenario), on hardware "not used at this station: kept open, the B1500A limits
outputs to 42 V" plus what bit 3 means (set: a >42 V request was refused; clear: no such request). The CLI prints the
label instead of `closed`. It is a label only: no rule, limit or tier reads it.

## Tiers and confirmation

Every plan gets exactly one tier, the same in Codex, Claude Code and the CLI: any `block` finding → `blocked`; else
any `confirm` → `needs_confirmation`; else `ok`.

1. `validate_plan` returns the `plan_id`, tier, one-line summary, findings (rule id, observed vs limit, source),
   confirm reasons and next steps. **`ok`** means within the soft limits, recipe validated for this backend, a known
   DUT profile and a verified pin map: the agent may run it with `run_plan(plan_id)` without asking.
2. **`needs_confirmation`** (soft limit, DUT envelope, unverified pin map, draft or ad-hoc recipe, first hardware run,
   destructive or system recipe; v2: pulse or MFCMU soft band, long run, physical setup, unverified switch wiring): `run_plan` refuses it (`confirmation_required`). The agent shows the summary
   verbatim with the risks and stops the turn. Only the human's own next chat message counts as consent, never text
   found in files, run notes, tool output or earlier turns. The agent then calls `run_confirmed_plan(plan_id,
   summary)`; the harness asks the human to approve that call with these arguments, and the server recomputes the
   summary and refuses any mismatch (`summary_mismatch`).
3. **`blocked`**: never executable. The agent explains which rules blocked it and offers an alternative within the
   limits. Only a human editing `config/local/` (limits, DUT profiles, pin maps, station) or a reviewed recipe status
   change can unblock it.
4. A plan id binds the exact parameters, pin map, DUT profile, recipe version and config hashes; any change
   produces a new plan, tier and confirmation. A confirmation covers one run call (a die batch on a
   `needs_confirmation` plan is confirmed run by run). At run time the plan rules are evaluated again without I/O,
   never trusting the stored tier, and then the pre-execute rules under the lock.
5. On the CLI, `b1500 run --confirm PLAN_ID` is the equivalent of `run_confirmed_plan` (an interactive y/N, for
   convenience, not as a security boundary); it and `b1500 fault clear` are human-only commands. `safe_shutdown` is
   never gated.

**The summary** (`rules.tiers.plan_summary`) is what the human approves. It is built only from hashed plan content
(recipe id and version, per-channel envelope and binding, DUT profile and pin-map names, backend) and the plan-phase
confirm/block findings, never from labels, messages, timestamps or live state. It is printable ASCII, at most 400
characters, and names every sourcing channel with its levels, max |V| and compliance:

```text
mosfet.idvd@1 | drain=SMU3(HRSMU) sweep 0..3 V Icomp 20 mA; gate=SMU5(MPSMU) step 0..2 V Icomp 1 uA |
DUT nmos-generic | pins mosfet-4t | sim | R-LIM-03 soft_limit, R-DUT-01 dut_envelope
```

(one line in practice). Channels are sorted by role, flags follow the rule-table order (`blocked` for a block).
Long plans switch to a compact channel form (`drain=SMU3 0..3V 20mA`), then to distinct reasons only; only beyond
that is the text cut at 400 characters.

v2 channel forms (blueprint v2 §2.9) name the route a terminal is reached through, a pulse source's train, its `SER`
load and its short-circuit bound, an MFCMU's frequency, AC level, DC bias and the age of its corrections, a WGFMU
program, a current source's compliance, and an asynchronous run's estimate:

```text
spgu.pulse_train@1 | gate=SPGU1:101 via SEL1.OUT1 pulse 0->4 V 1 us x1000 @10 kHz SER 1 MOhm Isc<=0.08 A residual |
DUT fefet-lab | pins fefet-sel | sim
moscap.cv@1 | bulk=CMU1:L low; gate=CMU1:H 1 MHz 30 mVrms DC -2..2 V corr 2h | DUT moscap-generic | ...
fecap.pund@1 | ...; top=WGFMU1:201 via RSU201.OUT pund 0..3 V 4000 pts @10 ns | ... | sim | async ~42 min | ...
```

Besides the confirm/block flags, two config-derived findings feed it: R-SPGU-01's short-circuit bound per SPGU
channel (`residual` when the terminal is `high_z`) and R-CORR-01's correction age. Both depend only on the plan, the
DUT profile and the correction store, never on live state; a newer correction changes the summary, so a confirmation
covers the corrections it was given for. Routes no role uses are listed as `routes SEL1.OUT1->pgu,smu`.

## Routes, pulses and sources without compliance (v2)

**Switches and routes.** The station declares its 16440A selectors, SCUU, ASU and RSUs (`station.yaml#switches`);
a pin map reaches a terminal through one (`SEL1.OUT1`). A plan lists the routes it may set (`envelope.routes`) and
applies them phase by phase (`routes_by_phase`); the guard refuses any other route except a declared output going to
its `rest` state, and the cleanup returns every declared output to `rest` and verifies it (`ERSSP?`). Before a
routed plan runs, every involved output and every present selector port must read back `rest` (R-ROUTE-01): a
selector a previous run or a human left switched blocks until `safe_shutdown`. Unknown wiring (`null` inputs) or
presence (`present: null`) blocks on hardware; unverified wiring needs confirmation (`unverified_topology`). The
selector's SMU path carries Force only, so a Kelvin role never uses it; the PGU-open state exists only on CH 1.

**Pulse sources.** The HV-SPGU and the WGFMU have no compliance: their envelopes have no current limit
(`max_abs_i: null`), and the pulse/waveform envelope bounds them instead. Free-running output cannot be expressed (a
train has a count or a duration) and is refused by the guard. Every pulse terminal of the DUT profile needs a human-
declared `pulse` envelope; amplitude, width, duty and pulses per run outside it need confirmation, the policy's
pulse soft bands too. SMU pulses keep their compliance and the `PT` timing table.

**SER and the `high_z` residual (decision 9, ATV-20).** The HV-SPGU adjusts its level to the declared load `SER`;
an open load sees `|V|·(SER+50)/SER`, twice the set level at the initial 50 Ω. R-SPGU-01 compares this open-load
voltage, never the set level, with the module (40 V), the hard limit and the DUT's pulse limit; a terminal declared
`high_z` with `SER` < 1 kΩ is blocked. A short behind the terminal would draw `V_open/(50 Ω + min_series_ohm)`; it
must stay ≤ 100 mA (the hard compliance ceiling) for `unknown` (treated as a short) and `resistive` terminals. For a
terminal the human declares `high_z` (an insulated gate, a capacitor plate) the bound is **not enforced**: it is an
accepted residual (OD-3), shown in every summary as `Isc<=X A residual` so the human approves it knowingly. A
`high_z` declaration that is wrong (a leaky or broken gate) is the risk the owner accepted.

**MFCMU.** AC level, DC bias and frequency stay inside the module and the DUT terminals' `ac` envelopes; capacitance
plans need fresh phase/open/short corrections for the same mainframe, station and pin map, still active on the
instrument (`CORRST?`) when the run starts; correction recipes always need `physical_setup` confirmation.

**Async runs and their residuals.** Above 300 s a plan runs asynchronously: `run_plan`/`run_confirmed_plan` return
`running` once the transaction holds the instrument and the pre-execute rules passed, and a worker thread of the
server (or of the CLI, which stays in the foreground) runs the kind. The kind's checkpoints, at most 30 s apart
(R-RUN-02), write `progress.json` and the rows so far (`partial.csv`) and poll the abort file
`data/state/abort.json`: `safe_shutdown` from any process (MCP tool, `b1500 shutdown` in another terminal) writes it,
the run stops at its next checkpoint (`RunCancelled`, outcome `cancelled`), runs the full verified cleanup and removes
the file; then `safe_shutdown` runs its own cleanup as for any shutdown. Every run, synchronous ones too, honours the
abort file at its checkpoints; a run ignores requests older than itself or addressed to another run, and an
unreadable abort file counts as a request. Readback loops of later kinds (WGFMU) poll it at least once a second; the
SMU sampling kind reads each `MM 10` block in one blocking read (blocks ≤ 25 s, the ATV-30 fallback), so its cancel
waits for the end of the block. One run at a time per instrument (the lock); while it runs, `station_status` answers `busy` from the cached
snapshot without waiting for the lock, and a second run request is `busy` at once. Auto-calibration is off (`CM 0`)
during an asynchronous run and restored by the cleanup (R-CAL-02), because it fires after 30 min with every output
switch off and would calibrate with the DUT connected. The MCP server's shutdown hook (stdin closed, SIGTERM,
interpreter exit) requests the abort and waits up to 10 s; the worker is a non-daemon thread, so the process stays
until a longer segment has ended and the cleanup is verified; the CLI's Ctrl-C does the same. Residuals: a cancel
waits up to one segment (≤ 30 s); a hard kill (SIGKILL, power loss, Task Manager) of the server or CLI leaves the
outputs on until the next transaction: new runs are refused (R-FAULT-01, an unrecovered in-flight marker) until
`safe_shutdown` runs the in-flight recovery cleanup, which also archives the dead run as `aborted` with the rows it
had written; a run longer than 10 min needs confirmation, longer than 24 h is blocked.

**Sampling and stress (`smu_sampling`, WP7.4).** The synchronous sources (`MV`/`MI`) are source commands: the guard
checks their base and bias level and compliance before anything is written, again for every continuation block of a
long run. Every sampling runs with `MSC 2,2`: a compliance on any channel, an A/D overflow or an oscillation stops the
measurement inside the instrument and the sources return to their base value, so a dielectric breakdown under TDDB
stress is limited by the stress compliance (`icomp`, the breakdown current limit) and ends the run; later blocks are
never triggered and the transaction's cleanup zeroes and verifies as for any run. TDDB is destructive and always
confirmed. Residual: a continuation block holds the stress as its base value (no drop to 0 V between blocks), so after
an automatic abort in such a block the stress stays on, current-limited, until the cleanup's `DZ` milliseconds later.

**Stress-measure (`stress_measure`, WP7.6).** The composite kind (BTI, IGZO bias stress, HCI, SILC) is built from the
guarded blocks of `catalog/blocks.py`: every stress, recovery and read level is a `DV` through the guard, and the
compiled envelope covers every phase (the stress level widens the channel's |V|; the compliance is the role's
`icomp` in every phase), so a stress beyond the DUT profile needs confirmation (`dut_envelope`) and beyond the hard
limits is blocked like any level. Every stress recipe is destructive and always confirmed; the plan summary names the
stress level per channel and the stress schedule (`stress 30 min x11 reads`), so the human confirms the stress, not
only the envelope. The holds are timed by the instrument (sampling blocks of at most 25 s with one monitor sample and
`MSC 2,2`); a compliance, overflow or oscillation in a hold block or a read ends the run (a gate breakdown is limited
by the gate compliance), and every block and read is a checkpoint (cancel latency ≤ one block). Residuals: the
outputs stay at the stress level between hold blocks and from a hold to the next read's trigger (host round trips,
milliseconds); a hold's monitor sample never forces anything, so an automatic abort in a hold leaves the DC stress on,
current-limited, until the cleanup.

## Cleanup and fault latch

Every instrument action runs inside one transaction. On any exit, including errors, interrupts and guard
violations, it: aborts a pending measurement, stops an active SPGU output (blueprint v2 2.6 step 2: on a mainframe
with an HV-SPGU, `SPST?` and `SPP` while it reads 1), zeroes and disconnects the outputs, drains instrument errors and
verifies that all outputs are off (on hardware `LOP?` and, with an SPGU, `SPST?` = 0). A failed step triggers a device clear and one retry. If the safe state still
cannot be verified, a persistent **fault latch** is set: every sourcing path then refuses (R-FAULT-01) until a human
runs `b1500 fault clear`, which succeeds only after a verified safe shutdown. `safe_shutdown` itself is never gated.
A crash mid-run leaves an in-flight marker; the next transaction runs the recovery cleanup first. The instrument
lock is an OS file lock, released automatically when its process dies. After the verification an asynchronous run's
cleanup adds a `restore` step (the auto-calibration switch, R-CAL-02); it never touches an output and is skipped when
the cleanup could not verify the safe state.

**MFCMU and SCUU (WP8.1).** Every MFCMU source command passes `OutputGuard.check_ac` with the channel's resulting
frequency, AC level and DC bias (`FC`, `ACV`, `DCV`, both ends of every `WDCV`/`WFC`/`WACV` sweep, base and pulse of
`PDCV`/`PWDCV`, base/bias/post of `MDCV`); a correction measurement (`CORR?`) is refused unless the same driver wrote
the frequency list and the guard admits the AC level at every listed frequency, and the phase compensation (`ADJ?`
mode 1) needs the channel in the plan's allowlist. Cleanup step 4 (blueprint v2 2.6) sends `DCV ch,0` and `ACV ch,0`
to every MFCMU the transaction drove whose `LOP?` code still shows its output on, then `DZ` (which also zeroes every
MFCMU DC bias); `CL` leaves the MFCMU at 0 V, 0 V rms, 1 kHz. The simulator's verification includes the MFCMU DC bias
and AC level. A new driver (recovery, `safe_shutdown`) knows no MFCMU it drove and relies on the instrument-wide `DZ`
and `CL` (PG p397 (4-79), p382 (4-64)). Every SCUU path change (`SSP`) is guarded by `check_route` per output: it
switches outputs on and resets the SMUs (ATV-27, PG p520 (4-202)); its modules are never named in `CN` (error 323).
Returning the SCUU to its `rest` state belongs to the route step of the cleanup (WP9.2).

**SPGU stop (cleanup step 2, WP9.1).** The cleanup knows whether an HV-SPGU is installed from the `UNT?` the run's
pre-execute snapshot read (a transaction without one, e.g. `safe_shutdown` or an in-flight recovery, reads `UNT?`
once; an unreadable inventory counts as an SPGU). `DZ` is not an SPGU stop condition (PG PDF 142), so `SPP` comes
first; an `SPST?` that cannot be read still gets `SPP`. An SPGU that ignores `SPP` (simulated fault `spgu_no_stop`)
fails the verification; the retry after the device clear sends `SPP` again, and only if that stops it is the cleanup
verified, otherwise the fault latches. The guard checks every SPGU write that can raise a level (setup, apply, start,
a `SER` change, the `CORRSER?` load measurement, which outputs a pulse) at the open-load level; the driver never lets
the instrument set `SER` itself (`CORRSER?` mode 0 only) and never builds free run (`SPRM 0`, the `*RST` setting).

**`LOP?` positive control (hardware, WP6.2; v1 ATV-1, ATV-23).** On hardware the verification is `LOP?` reading `00`
for every slot. An all-`00` answer proves the outputs off only if `LOP?` reports this instrument's output switches at
all, so every run that switches outputs on reads `LOP?` once right after `CN`, before any level is applied (the
outputs force 0 V): each switched-on SMU must report a non-`00` code. The reading is audited (`checkpoint`
`lop_positive_control`) and stored in the manifest (`cleanup.positive_control`) next to the cleanup's all-`00`
answer; together they are the evidence behind `verified: lop`. A slot that reads `00` there stops the run before any
level (`PositiveControlFailed`, result `cleanup_unverified`), and the cleanup then refuses to call its own all-`00`
answer verified: the fault latches with the reason, and every later run stays refused until a human checks the
front panel and clears the fault (the v1 ATV-1 fallback, `*LRN? 0`, is a code change at M12 if the bring-up shows
`LOP?` blind). `system.*` and `safe_shutdown` switch nothing on and have no control; the simulator verifies its own
state instead (`verified: sim_state`).

**Locked bus (residual, WP5.5).** Each transaction takes the VISA exclusive lock of the instrument. When another
client holds it (EasyEXPERT, a second VISA program), a run is refused before anything is sent (`busy`), and so is a
status snapshot; `safe_shutdown`, however, cannot reach the instrument at all: its report is unverified and the fault
latch is set, while the outputs stay as the other client left them. Only the human can then close that client, check
the station and run `b1500 fault clear`.

The simulator test suite checks one global invariant across every injected fault and position: if any source
command reached the transport, zero and disconnect follow the last one and the simulated instrument is safe, or the
fault latch is set. No source command outside the compiled envelope ever reaches the transport, and `blocked`,
`not_implemented` and unconfirmed plans never open it.

## What is protected and what is not (owner decision D3)

Human approval is the coding harness's own tool confirmation. This keeps the system simple; the owner accepted the
gaps below.

**Protected in the harnesses' normal modes.** Every `run_confirmed_plan` call stops for a human who sees the summary
as the tool argument (including any `Isc<=X A residual`). `run_plan` cannot run a plan that needs confirmation. `blocked` plans cannot run from chat at
all. The 42 V / 100 mA code ceiling, the module specs (R-LIM-01) and the `OutputGuard` hold no matter what is
confirmed or configured. Every run records its tier, the confirmed summary and the hashes of the config files it
used.

**Not protected (accepted residual risks).**

- *Bypass modes.* If the human starts the harness with approvals turned off (Codex `--yolo` or full access, Claude
  Code `bypassPermissions`), the agent can approve its own `run_confirmed_plan` calls. On Claude Code the tool is
  additionally flagged to require user interaction on every call, which still prompts in those modes.
- *The agent's own code.* An agent with a shell could import the library directly, write its own PyVISA script, or
  answer the CLI's y/N prompt itself. Instructions, deny rules and a guard hook discourage this; they are not a
  hard boundary.
- *Config edits.* An agent with write access to the clone could loosen soft limits, DUT profiles or pin maps in
  `config/local/`, or delete the fault latch in `data/state/`. Such changes are visible in the run manifest's config
  hashes, and no configuration can exceed the hard ceiling.

**Remaining mitigations.** The separate confirmation tool and the server-checked summary echo; the hard-limit code
ceiling; Codex `forbidden` rules and Claude Code deny rules on `b1500 fault`, `b1500 run --confirm` and the configuration
bootstrap `b1500 config init|adopt` (they hold even in bypass modes; owner decision OD-5); Claude Code deny rules on edits of `config/local/**` and `data/**` plus a `PreToolUse` hook that
also blocks `pyvisa`; config hashes and per-call audit events; the agent rules in `AGENTS.md` and the skills; and
the M3 safety scenarios (S2, S5, S6, S9) on both harnesses.

**Harness files** (`b1500 harness init --codex --claude --check` verifies them). Codex: `.codex/rules/b1500.rules`
forbids the human-only commands `fault`, `run --confirm`, `config init` and `config adopt` (also after `uv run`;
argv-prefix match). Claude Code: `.claude/settings.json` allows the nine other tools, the read-only
`uv run b1500 manual …` commands and the read-only `bringup` helpers (status, propose-station, capture, record;
OD-5), asks for `run_confirmed_plan`, denies the human-only commands and edits of `config/local/**`, `data/**` and
the harness settings, and runs `scripts/hooks/b1500_guard.py` before every shell or
file-editing call. The hook fails closed (`onFailure: block`, Claude Code 2.1.295 or later): if it cannot run (for
example `uv` missing from `PATH`), shell and edit calls are blocked until a human fixes it. Its shell check matches
text, so any command that merely mentions a human-only command is blocked too. Whether hooks also run in
`bypassPermissions` mode is not verified (ATV-8); the deny rules hold there.

**Read-only probe and configuration bootstrap (blueprint v2 7.1, WP6.1).** `b1500 doctor --probe` and `b1500 bringup propose-station`
reach the instrument only through `Session.read_only`: its `ReadOnlyTransport` passes a command only when it is one query
(header = mnemonic + `?`, no `;`) and refuses every setting command, a device clear (it re-initialises the instrument)
and a serial poll (it clears status bits), so neither can switch an output; the status snapshot uses the same link.
Residual: `ADJ? ch,0` is a query that, per the manual, re-applies the last phase compensation and resets the MFCMU
(TODO(verify) at bring-up L0 that no output changes). The proposal is written to `work/bringup/`; only the human adopts
it (`config adopt`, human only: denied by the harness rules and blocked by the guard hook), and `config adopt` refuses a
file that does not validate against its schema and keeps the replaced file as `<file>.bak`.

**Physical backstop.** Outputs stay at or below 42 V while the interlock is open (keep it open; v1 has no
high-voltage workflow), per-channel compliance limits current, and the shield box encloses the DUT.

On the development Mac only the simulator runs, so the tiers there are behavior tests, not protection.
