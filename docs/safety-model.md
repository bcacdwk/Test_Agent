# Safety model

How the B1500A test agent decides what may run, who must confirm it, and what happens when something goes wrong.
Source: blueprint §4 (rules, tiers, confirmation, residual risks), §2.4 (transaction and fault latch), §2.5 (rules
API) and §3 (the simulator invariant). **Status:** the rules engine, the built-in rules, tiers and the plan summary
are implemented (WP1.4, `src/b1500_test_agent/rules/`), and so are the session and fault latch (WP1.6), the
executor (WP1.7), the service, MCP tools and CLI that call them (WP1.8) and the harness wiring (WP1.9: Codex
`forbidden` rules, Claude Code permission rules and the `PreToolUse` guard hook).

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
   module inventory match the station profile, interlock state, pre-existing instrument errors, calibration state.
3. **`OutputGuard`** on every single source command: the channel must be in the plan's allowlist, the level and
   compliance inside the compiled envelope, the compliance non-zero. A violation raises before anything is sent.
4. **Quality classification** after the run: each data point's status code makes it ok, limited or untrusted.

Configuration is re-read (by digest) on every service call, so a rule change applies to the next call.

## Limits and defaults

`config/policy.example.yaml` (conservative; a human may tighten them in `config/local/policy.yaml`):

| Setting | Default | Effect |
|---|---|---|
| `hard_limits` | 42 V, 100 mA compliance | Above → `blocked`. Code ceiling `HARD_CEILING_V = 42.0`, `HARD_CEILING_A = 0.1`; a policy above it is invalid config |
| `soft_limits` | 10 V, 10 mA compliance | Above → `needs_confirmation` (reason `soft_limit`) |
| `interlock.required_above_v` | 42 V | Above → the interlock must be recorded as working and be closed |
| `run_limits` | 10,001 points, 300 s per synchronous run | Above → `blocked` |
| `plans.ttl_h` | 24 h | Older plans must be validated again |
| `quality` | ok `N`; limited `C T`; untrusted `V X F D G S U` | Limited points are excluded from fits; extraction from untrusted data is refused unless forced, and then flagged |

Limits compare magnitudes and are exclusive: a value equal to a limit passes (10 V is `ok`, 42 V needs
confirmation, 42.5 V is `blocked`). Every voltage and current check runs over the plan's compiled envelope, the
same per-channel numbers the `OutputGuard` enforces, so the rules and the guard cannot disagree. Module
specifications from the manuals (voltage, current and V-I envelope per SMU type, `driver/modules.py`) block a plan
regardless of policy.

## Implemented rules (blueprint §4.2)

Each rule is one function in `rules/builtin/` (`core.py`, `limits.py`, `run.py`, `cmu.py`, imported in table order),
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
| R-PARAM-01 | plan | Every requested parameter is declared, every declared one has a value, and type, choices, range and unit match the recipe's `ParamSpec`; resolved values equal the requested ones | block | recipe `#params.<name>.{range,type,choices,unit}`, `plan:resolved_params.<name>` |
| R-PIN-01 | plan | Pin map exists; every non-optional role is mapped to a channel or the GNDU; the plan binding agrees with the pin map and the station profile; channels exist and are used once; module type allowed by the role (default: any SMU); `low_current` needs an HRSMU; the GNDU only for `ground` roles with `allow_gndu`; every envelope channel belongs to its bound role | block | `pinmaps/<name>.yaml#terminals.<role>`, `station.yaml#modules`, recipe `#roles.<role>.*`, `plan:envelope.channels.<ch>` |
| R-PIN-02 | plan | Pin map `certainty: unverified` | confirm `unverified_pin_map` | `pinmaps/<name>.yaml#certainty` |
| R-INV-01 | pre (plan with a snapshot) | A live snapshot exists and comes from the plan's backend; identity model = station mainframe; the module model in every bound slot = station profile | block | `station.yaml#mainframe.model`, `station.yaml#modules[i].model`, `live:snapshot`, `live:identity`, `live:inventory` |
| R-LIM-01 | plan | Per envelope channel: \|V\|, \|Icomp\| and the V-I envelope of its module (`module_spec()` + `violations()`); modules without a DC spec (MFCMU, SPGU, WGFMU) refuse; summed compliance within the GNDU's 4.2 A when a role uses the GNDU | block | `code:b1500_test_agent.driver.modules.MODULE_SPECS[<type>] (<manual tables>)` |
| R-LIM-02 | plan | Per envelope channel: \|V\| ≤ `hard_limits.max_abs_voltage_v`, \|Icomp\| ≤ `hard_limits.max_abs_compliance_a`, never above the code ceiling; non-finite values block | block | `policy.yaml#hard_limits.*` (`code:...HARD_CEILING_*` if a policy object exceeds the ceiling) |
| R-LIM-03 | plan | Per envelope channel above `soft_limits.voltage_v` / `soft_limits.compliance_a` | confirm `soft_limit` | `policy.yaml#soft_limits.*` |
| R-DUT-01 | plan | A recipe with DUT roles needs a named, existing DUT profile that describes every driven terminal (else block); \|V\| or \|Icomp\| above a terminal's envelope → confirm; DUT device type not among the recipe's → warn | block / confirm / warn | `plan:request.dut_profile`, `duts/<name>.yaml#terminals.<t>.max_abs_{v,i}` |
| R-COMP-01 | plan | Every connected channel has an envelope with non-zero compliance; sourcing roles (`sweep_v`, `bias_v`, `step_v`) set `icomp` explicitly and non-zero | block | recipe `#roles.<role>.settings.icomp`, `plan:envelope.channels.<ch>.max_abs_i` |
| R-IL-01 | plan, pre | When the envelope's max \|V\| exceeds `interlock.required_above_v`: the station records `interlock.available: true`; with live state, status-byte bit 3 is clear **and** no `ERRX?` 202/203 is pending (ATV-10 fallback); at pre a missing status byte blocks | block | `station.yaml#interlock.available`, `live:status_byte.bit3`, `live:errors` |
| R-RUN-01 | plan | Points ≤ `run_limits.max_points`; estimated duration ≤ `run_limits.max_sync_run_s` | block | `policy.yaml#run_limits.*` |
| R-ALWAYS-01 | plan | Recipe `always_confirm` reasons (`destructive`, `system_self_test`, `system_self_cal`) | confirm (that reason) | recipe `#always_confirm` |
| R-ERRX-01 | pre (plan with a snapshot) | Pre-existing `ERRX?` entries drained by the snapshot are recorded | warn | `live:errors` |
| R-CAL-01 | pre | Auto-calibration state and the last completed self-calibration (archive) are recorded | warn if unknown, else info | `live:auto_calibration`, `data/runs/index.jsonl` |
| R-CORR-01 | plan | Capacitance (MFCMU) plans: phase compensation, open and short corrections performed, open/short frequency ranges cover every frequency parameter (declared; CMU kinds are `not_implemented` in v1) | block | `station.yaml#corrections.cmu.*` |
| R-QUAL-01/02/03 | post | Per-point status counts by class (info); limited points, excluded from fits (warn); untrusted points, extraction refused unless forced (warn). Unknown status letters count as untrusted | report | recipe `#quality` or `policy.yaml#quality` |

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
active. The real bit behavior is verified at M4 L0.

## Tiers and confirmation

Every plan gets exactly one tier, the same in Codex, Claude Code and the CLI: any `block` finding → `blocked`; else
any `confirm` → `needs_confirmation`; else `ok`.

1. `validate_plan` returns the `plan_id`, tier, one-line summary, findings (rule id, observed vs limit, source),
   confirm reasons and next steps. **`ok`** means within the soft limits, recipe validated for this backend, a known
   DUT profile and a verified pin map: the agent may run it with `run_plan(plan_id)` without asking.
2. **`needs_confirmation`** (soft limit, DUT envelope, unverified pin map, draft or ad-hoc recipe, first hardware run,
   destructive or system recipe): `run_plan` refuses it (`confirmation_required`). The agent shows the summary
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
mosfet.idvd@1 | drain=SMU3(HRSMU) sweep 0..3 V Icomp 20 mA; gate=SMU1(MPSMU) step 0..2 V Icomp 1 uA |
DUT nmos-generic | pins mosfet-4t | sim | R-LIM-03 soft_limit, R-DUT-01 dut_envelope
```

(one line in practice). Channels are sorted by role, flags follow the rule-table order (`blocked` for a block).
Long plans switch to a compact channel form (`drain=SMU3 0..3V 20mA`), then to distinct reasons only; only beyond
that is the text cut at 400 characters.

## Cleanup and fault latch

Every instrument action runs inside one transaction. On any exit, including errors, interrupts and guard
violations, it: aborts a pending measurement, zeroes and disconnects the outputs, drains instrument errors and
verifies that all outputs are off. A failed step triggers a device clear and one retry. If the safe state still
cannot be verified, a persistent **fault latch** is set: every sourcing path then refuses (R-FAULT-01) until a human
runs `b1500 fault clear`, which succeeds only after a verified safe shutdown. `safe_shutdown` itself is never gated.
A crash mid-run leaves an in-flight marker; the next transaction runs the recovery cleanup first. The instrument
lock is an OS file lock, released automatically when its process dies.

The simulator test suite checks one global invariant across every injected fault and position: if any source
command reached the transport, zero and disconnect follow the last one and the simulated instrument is safe, or the
fault latch is set. No source command outside the compiled envelope ever reaches the transport, and `blocked`,
`not_implemented` and unconfirmed plans never open it.

## What is protected and what is not (owner decision D3)

Human approval is the coding harness's own tool confirmation. This keeps the system simple; the owner accepted the
gaps below.

**Protected in the harnesses' normal modes.** Every `run_confirmed_plan` call stops for a human who sees the summary
as the tool argument. `run_plan` cannot run a plan that needs confirmation. `blocked` plans cannot run from chat at
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
ceiling; Codex `forbidden` rules and Claude Code deny rules on `b1500 fault` and `b1500 run --confirm` (they hold
even in bypass modes); Claude Code deny rules on edits of `config/local/**` and `data/**` plus a `PreToolUse` hook that
also blocks `pyvisa`; config hashes and per-call audit events; the agent rules in `AGENTS.md` and the skills; and
the M3 safety scenarios (S2, S5, S6, S9) on both harnesses.

**Harness files** (`b1500 harness init --codex --claude --check` verifies them). Codex: `.codex/rules/b1500.rules`
forbids the two human-only commands (also after `uv run`; argv-prefix match). Claude Code: `.claude/settings.json`
allows the nine other tools, asks for `run_confirmed_plan`, denies the two human-only commands and edits of
`config/local/**`, `data/**` and the harness settings, and runs `scripts/hooks/b1500_guard.py` before every shell or
file-editing call. The hook fails closed (`onFailure: block`, Claude Code 2.1.295 or later): if it cannot run (for
example `uv` missing from `PATH`), shell and edit calls are blocked until a human fixes it. Its shell check matches
text, so any command that merely mentions a human-only command is blocked too. Whether hooks also run in
`bypassPermissions` mode is not verified (ATV-8); the deny rules hold there.

**Physical backstop.** Outputs stay at or below 42 V while the interlock is open (keep it open; v1 has no
high-voltage workflow), per-channel compliance limits current, and the shield box encloses the DUT.

On the development Mac only the simulator runs, so the tiers there are behavior tests, not protection.
