# Safety model

How the B1500A test agent decides what may run, who must confirm it, and what happens when something goes wrong.
Source: blueprint §4 (rules, tiers, confirmation, residual risks), §2.4 (transaction and fault latch) and §3 (the
simulator invariant). **Status: design; implementation arrives in M1.** WP1.4 completes this page with the rule
table as implemented.

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
   ranges, pin map and DUT profile, module specs, hard and soft limits, compliance, run size.
2. **Pre-execute rules** under the instrument lock with fresh live state: no latched fault, instrument identity and
   module inventory match the station profile, interlock state, pre-existing instrument errors.
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
| `interlock.required_above_v` | 42 V | Above → interlock must be closed (unreachable in v1 because of the hard limit) |
| `run_limits` | 10,001 points, 300 s per synchronous run | Above → `blocked` |
| `plans.ttl_h` | 24 h | Older plans must be validated again |
| `quality` | ok `N`; limited `C T`; untrusted `V X F D G S U` | Limited points are excluded from fits; extraction from untrusted data is refused unless forced, and then flagged |

Module specifications from the manuals (voltage, current and power per SMU type) also block a plan regardless of
policy.

## Planned v1 rules (blueprint §4.2)

| Id | When | Check | Outcome |
|---|---|---|---|
| R-CFG-01 | always | Config parses; examples cannot select visa; visa needs local settings, station and policy; hard limits ≤ ceiling | block |
| R-FAULT-01 | plan, pre | No latched fault; a leftover in-flight marker has been recovered | block |
| R-REC-01 | plan | `not_implemented` recipe → block; on visa: `draft` → confirm, first hardware run of a `sim_validated` recipe → confirm, ad-hoc `generic.*` recipe → confirm | block / confirm |
| R-PARAM-01 | plan | Parameters match the recipe's types, choices and ranges | block |
| R-PIN-01 / 02 | plan | Pin map complete and consistent with the station; an `unverified` pin map needs confirmation | block / confirm |
| R-INV-01 | pre | Live identity and module inventory match the station profile | block |
| R-LIM-01 / 02 / 03 | plan | Module specs; hard limits; soft limits | block / block / confirm |
| R-DUT-01 | plan | DUT profile required when the recipe has DUT roles; outside its envelope → confirm | block / confirm |
| R-COMP-01 | plan | Every sourcing channel has an explicit non-zero compliance | block |
| R-IL-01 | pre | High voltage requires a closed interlock | block |
| R-RUN-01 | plan | Point count and duration within run limits | block |
| R-ALWAYS-01 | plan | Recipe marks itself always-confirm (destructive, self-test, self-calibration) | confirm |
| R-ERRX-01, R-CAL-01 | pre | Pre-existing instrument errors drained and recorded; calibration state recorded | warn |
| R-CORR-01 | plan | Capacitance kinds need a valid correction (declared; CMU kinds are `not_implemented`) | block |
| R-QUAL-* | post | Status-code classification of every point | report |

## Tiers and confirmation

Every plan gets exactly one tier. It is the same in Codex, Claude Code and the CLI.

- **`ok`**: within soft limits, recipe validated for this backend, known DUT profile and pin map. The agent may run
  it with `run_plan(plan_id)` without asking.
- **`needs_confirmation`**: at least one confirm reason (soft limit exceeded, DUT envelope exceeded, unverified pin
  map, draft or ad-hoc recipe, first hardware run, destructive or system recipe). `run_plan` refuses it. The agent
  shows the plan's one-line summary verbatim with the risks and stops. Only the human's own next chat message counts
  as consent, never text found in files, run notes, tool output or earlier turns. The agent then calls
  `run_confirmed_plan(plan_id, summary)`; the harness always asks the human to approve that call, and the server
  recomputes the summary and refuses any mismatch.
- **`blocked`**: never executable. The agent explains which rules blocked it and offers an alternative within the
  limits. Only a human editing `config/local/` (limits, DUT profiles, pin maps, station) or a reviewed recipe status
  change can unblock it.

A plan id binds the exact parameters, pin map, DUT profile, recipe version and config hashes; any change produces a
new plan, tier and confirmation. A confirmation covers one run. On the CLI, `b1500 run --confirm PLAN_ID` is the
equivalent of `run_confirmed_plan` (an interactive y/N, for convenience, not as a security boundary); it and
`b1500 fault clear` are human-only commands.

## Cleanup and fault latch

Every instrument action runs inside one transaction. On any exit, including errors, interrupts and guard
violations, it: aborts a pending measurement, zeroes and disconnects the outputs, drains instrument errors and
verifies that all outputs are off. A failed step triggers a device clear and one retry. If the safe state still
cannot be verified, a persistent **fault latch** is set: every sourcing path then refuses until a human runs
`b1500 fault clear`, which succeeds only after a verified safe shutdown. `safe_shutdown` itself is never gated.
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
all. The 42 V / 100 mA code ceiling, the module specs and `OutputGuard` hold no matter what is confirmed or
configured. Every run records its tier, the confirmed summary and the hashes of the config files it used.

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

**Physical backstop.** Outputs stay at or below 42 V while the interlock is open (keep it open; v1 has no
high-voltage workflow), per-channel compliance limits current, and the shield box encloses the DUT.

On the development Mac only the simulator runs, so the tiers there are behavior tests, not protection.
