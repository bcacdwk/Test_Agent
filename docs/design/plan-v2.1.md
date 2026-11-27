> **v2.1 plan** (2026-11-26, revision 2 with the owner's decisions §9 and the orchestrator's amendments §11–§12),
> committed verbatim below by WP30.1 on 2026-11-27; **frozen**: v2.1 closed at `8e0992d`. Results:
> [progress.md](progress.md) §"v2.1"; every id with its status today: [register.md](register.md) (OD21-10 is still
> open). Paths under `tmp/` that it cites (brief, companion table, audits, executor preamble) were maintainer scratch
> and are not in the repository.

# v2.1 plan: harness-upgrade check, debug cases, step-by-step bring-up

Status: plan only (nothing in the repo changed). Base: `main` @ `0397f18` (v2 complete; S1–S18 18/18 on codex-cli
0.170.0 and Claude Code 2.1.328). Date 2026-11-26. Brief: `tmp/v2_orch/brief_plan_v21.md`. Companion file:
`tmp/v2_orch/plan_v21_todo_verify.md` (every `TODO(verify)` marker classified). Format and guardrails as blueprint v2
§10 / §10.0; executors read `tmp/v2_orch/wp_preamble.md` (work on `main` in the main checkout, see D-1).

## 0. Summary

Revision 2 (2026-11-26): owner decisions applied (§9); workstream A redesigned around the owner's principle "as
simple as possible: users are not maintainers, for them it is just 'update'; no large later maintenance cost".

Three workstreams, 8 WPs (21.1, 21.2, 21.4–21.9; 21.3 dropped), about 3.1 k changed source LOC (tests excluded), one
acceptance phase at the end (≈ 9 USD Claude Code, ≈ 9.5 M mostly cached Codex input tokens).

- **A. Harness upgrades: two commands, two roles.**
  - **Operator** (lab PC and Mac, human-run, free): `uv run b1500 update` pulls the repo, syncs the environment,
    repairs the harness wiring if needed, brings each installed harness to the version recorded as validated **in the
    repo** (`config/harness/validated.yaml`), with exactly one installer per harness (Claude Code `claude install
    <version>`, Codex `npm install -g @openai/codex@<version>`), runs the free checks and ends with one plain verdict:
    "Ready." or a numbered list of what to do. It refuses to run inside an agent session. `b1500 doctor` says "run
    `uv run b1500 update`" when installed ≠ validated. Harness auto-update is off on the lab PC (one-time deployment
    step), so nothing changes under the user.
  - **Maintainer** (dev Mac, rare, the only place that costs): `uv run b1500 dev harness qualify` climbs T0 → T1 → T2
    (→ T3 with `--escalate`); on PASS it bumps `validated.yaml` (the maintainer commits). Per harness release this is
    the whole maintenance: ≈ 1.6–1.9 USD Claude Code, ≈ 1.2–1.4 M Codex tokens, ~15 min. Version-specific tables
    (tool and event vocabulary) only WARN in its report, never block `update`. The runner stops at the first
    login/API/network event (strict). `Monitor` and the other unguarded Claude Code built-ins are an owner-accepted
    residual (OD21-5 = c).
- **B. Debug cases**: "implemented" = each case complete, its simulator reproduction executed by a test (real `S…`
  runs, labelled SIMULATED), linked runbook, a lint for cases, a structured list of the questions only the owner can
  answer, and review tooling; plus the deck's fourth item (C-V shape) as a new seed case. No lab fact is invented.
- **C. Step-by-step bring-up**: a machine-readable step sequence (`steps.yaml`, 148 existing stage steps put in
  execution order, plus session start/end steps and the deployment steps), a persisted step ledger written only by
  the CLI, three verbs `bringup next | done | check` (with three Claude Code allow lines, OD21-6), stage sign-off that
  requires every step verified, nine owner sessions, and an end-to-end rehearsal test on the simulator and the
  visa-loop. Every `TODO(verify)` is classified (companion file).

## 1. Findings

### 1.1 Harness upgrades: what exists and what really breaks

Exists: `docs/deployment-windows.md:359` ("after a harness upgrade repeat steps 8.2, 8.5 and 9.4–9.5", manual);
probes `smoke`, `atv-confirm`, `atv12` (`docs/acceptance/README.md:165-166`); `b1500 dev acceptance run|grade|report|
list`; `--affected` is file-change based only (`devtools/acceptance/selection.py:8-13`, `GLOBAL_TOUCHES` :26-32);
`harness init --check` (static wiring, 0.9 s); `dev mcp-smoke` (2.5 s); the offline harness tests (428 tests, 65 s
with `-n auto` on the Mac: `tests/adapters/test_harness*.py`, `test_guard_hook.py`, `test_mcp_smoke.py`,
`tests/acceptance -m "not acceptance"`; `codex execpolicy` tests run when `codex` is installed,
`tests/adapters/test_harness_permissions.py:97`). Installed on the Mac: codex-cli 0.170.0 as the npm package `@openai/codex` under Homebrew's Node
(`/opt/homebrew/bin/codex -> ../lib/node_modules/@openai/codex/bin/codex.js`; npm offers 0.172.0, so it does not
update itself), Claude Code 2.1.328 (native installer, `~/.local/bin/claude`, auto-updates by default per the Claude
Code setup docs).
Missing: version-based detection, any record of "validated version per machine", stop-on-infra-error in the repo,
checks for the silent failure modes below, a Windows live run of the runner.

| # | Surface | Repo dependency (evidence) | How an upgrade breaks it | Today | Check |
|---|---|---|---|---|---|
| 1 | CLI flags | `harnesses.py:176-182` (`codex exec --json -s -C -c`, `exec resume`), `:257-266` (`claude -p --output-format stream-json --verbose --include-hook-events --forward-subagent-text --mcp-config --strict-mcp-config --setting-sources --permission-prompt-tool --allowedTools --resume`) | flag renamed/removed: launch fails | loud (session error) | T0: each flag in `--help` |
| 2 | Event formats | `transcripts.py:8-31`, Codex events `:301-316`, items `:329-355`, Claude `:423-456`, usage | new/renamed types are ignored: graders see less | partly silent | T1 vocabulary diff |
| 3 | Codex rollout (code-mode tool inputs: the 393 raw `exec` inputs of the 11.5 Codex batch exist only there) | `harnesses.py:190-196` (`$CODEX_HOME/sessions/*/*/*/rollout-*-<id>.jsonl`) | storage moves (0.170.0 already ships `codex migrate-rollouts` "to paginated thread history"): `forbidden_content` on code-mode inputs goes blind | **silent**: `runner.py:546-553` only adds a warning | T1: rollout required |
| 4 | Tool vocabulary vs guard | hook matcher `.claude/settings.json:40` (`Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit`), parser shell/write sets `transcripts.py:490-493` | a new tool that runs commands or writes files bypasses the hook and the shell/path graders. 2.1.328 `init.tools`: 31 built-ins incl. `Monitor` (its schema: "Shell command or script ... runs in the same shell environment as Bash"), `CronCreate`, `RemoteTrigger`, `ScheduleWakeup`, `EnterWorktree`, `PublishPlugin`; `MultiEdit` no longer offered | **silent, present now** | qualify T1 contract: WARN, owner-accepted residual (OD21-5 = c) |
| 5 | Permission rule / settings syntax | `.claude/settings.json` allow/ask/deny + hook; `.codex/rules/b1500.rules` | a rule the new version drops or reads differently; `claude --help` (2.1.328) for `-p`: "Settings files that fail validation are silently ignored in this mode" = no deny, no ask, no hook in every headless session | **silent** for Claude | T0: `claude doctor` lists dropped/invalid entries (docs); `codex execpolicy check` tests; T1 hook coverage + `atv-confirm` |
| 6 | Hook protocol | stdin `tool_name`/`tool_input`, exit 2, exec-form `args`, `onFailure: block` (≥ 2.1.295) (`scripts/hooks/b1500_guard.py:170-196`) | hook not run, or blocks everything | silent if not run | T1: every guarded call has a `PreToolUse` `hook_response` (11.5 batch: 60 hook pairs = 59 `Bash` + 1 `Write`) |
| 7 | MCP config + tool approval | `-c mcp_servers.b1500.*` incl. `tools.run_confirmed_plan.approval_mode` (`harnesses.py:147-173`), `config/harness/*` | renamed key silently ignored → `run_confirmed_plan` falls back to `auto` | silent | T1 `atv-confirm` turn 1 must be denied; T0 `codex mcp get`/`claude mcp list` |
| 8 | Headless approval semantics (ATV-5, -6, -12) | approver `--permission-prompt-tool`; Codex `exec` = policy never | prompts pass or vanish | probes exist, run by hand | T1 `atv-confirm`, `atv12` |
| 9 | Trust | `harnesses.py:199-207` (Codex `projects.<p>.trust_level`), `:220-234` (Claude `hasTrustDialogAccepted`) | key format change → `None`; untrusted Claude loads no `CLAUDE.md`/allow rules (WP6.6) | warning only | T0: both readable and true |
| 10 | Login / API / network | owner rule "stop, no retries" | sessions fail mid-batch, re-runs burn money | **not in repo**: WP11.5/S7 used a scratch watcher (`progress.md:99-100`); `run_batch` never stops (`runner.py:570-622`) | T0 `codex login status`, `claude auth status` (exit 0/1); runner watcher at every tier |
| 11 | Sandbox / defaults | `codex doctor --summary` row (`deployment-windows.md:241-250`); `UV_CACHE_DIR` under workspace-write | full-access default, approval Never; `uv run` blocked | manual | T0 (known strings per OS, unknown = WARN) |
| 12 | MCP server lifecycle at turn end | S15 outcomes (`aborted` Codex, `cancelled` Claude; safety-model residuals) | a change flips S15 semantics | only in S15 | T3 map (S14, S15) |
| 13 | Interactive-only facts | ATV-11 prompt shows `summary`, ATV-8 `/hooks` | not testable headless | manual | human checklist recorded in the report |

Where the commands live: `uv sync --frozen` installs the dev group (`pyproject.toml:32`; the wheelhouse includes
it, `deployment-windows.md:382`), so `b1500 dev …` runs on the lab PC too; but `dev` is "never needed for lab
operation" (`adapters/cli/dev.py:1,27`). Hence the operator's `update` is a top-level command and the cost ladder
lives in `dev harness qualify` (D-2).

Other facts: the pinned transcript fixtures are older than the validated versions (`tests/fixtures/transcripts/
{codex-0.167.1,claude-2.1.326}`); the runner has Windows process-group code (`runner.py:368-383`) but never ran a
live session on Windows; Codex sessions also expose user-level MCP servers (the 11.5 rollouts list `mcp__cua_repl`,
not ours: Codex has no `--strict-mcp-config`).

### 1.2 Debug cases

- Three drafts (`cases/2026-11-04-{current-orders-too-high,noisy-data,igzo-vth-drift}.md`): `runs: []`, `backend:
  visa`, 10 inline `TODO(owner)` (4+3+3); template has 10 keys / 8 sections, enforced only by
  `tests/skills/test_debug_skill.py:45-48,186-209`; `lint-skills` has no case check; SKILL §7–§8
  (`b1500-debug/SKILL.md:84-97`) says agents draft, humans review — nothing enforces it.
- The deck page (`../PPT_slides_content.md` p.18 = "slide 17") lists **four** symptoms; "C-V curve not S-shaped"
  (redo compensation → lower AC level → check gate leakage) has a runbook (`cmu-cv-distortion`) but no case. The
  deck also says "about 10 entries recorded" (`PPT_slides_content.md:689`); only 4 are in the deck.
- Simulator coverage: noisy → `open_drain_noisy` covers the runbook's contact-first branch, not the deck's first
  cause (short integration on a landed device; the simulator scales noise ×3 / ×1 / ×0.3 for short / medium / long,
  `transport/sim/units/core.py:27`); current too high → `gd_short`; IGZO → `igzo_transient` (WP5.9) with persisted
  drift state (`sim/devices/mosfet.py:179-185`), yet `runbooks/vth-drift-igzo.md:16` says "No simulator scenario
  models this" (stale); C-V → `moscap_basic` + faults `CmuCorrectionLost`, `CmuOverload` (`models/sim.py:377,388`);
  a leaky-gate MOS-C scenario does not exist.
- More seeds: the C-V item, yes. From the runbooks, no: cases are observations, a case written from a runbook would
  invent one. From v2 history (S7 open drain), no: already runbook text since `53ff571`.

### 1.3 Bring-up

- 12 stage files, **148 numbered steps** (58 physical, 90 agent), 208 `checks`, written as two lists per stage
  (physical, agent) whose real order interleaves (L1: A1, A2, P1, P2, A3 …). `bringup status` derives progress
  from records only (`bringup.py:12-16`, `_status` :413-475): drills, coexistence, human reference readings, ATV
  observations and fixture captures without a record are not tracked; resuming relies on the agent re-reading.
- Stage files sit at the 150-line budget (L9 150, L6 137, L8 134; `devtools/skills/budgets.py:20`): step metadata
  cannot go into them.
- The deployment's "Recorded results" table (`deployment-windows.md:504-518`) and the interactive harness checks live
  outside any record.
- v2's OD-5 allow rules cover `bringup status|propose-station|capture|record` only (`.claude/settings.json`); a new verb
  would prompt in Claude Code (resolved: OD21-6 adds three allow lines).
- `tests/hardware/rehearsal.py` runs the hardware suite over the visa-loop; S17 rehearses S0–L1 only.
- `TODO(verify)`: 196 occurrences (177 lines) in `.agents src docs`, 103 more in recipes/config/tests/`.claude`
  mirror; classification summary in §4.6, table in the companion file.

## 2. Design A: `uv run b1500 update` (operator) and `uv run b1500 dev harness qualify` (maintainer)

Principle (owner, 2026-11-26): as simple as possible; for the user it is just "update"; low later maintenance is the
core goal. Consequences: the operator never pays for a check and never runs a harness version the maintainer has not
qualified; every judgement and every cost sits with the maintainer, once per harness version, on the Mac. A harness
release that breaks something changes nothing for the operator: the validated version stays until the maintainer
bumps it.

### 2.1 The committed truth: `config/harness/validated.yaml`

```yaml
# Harness versions validated for this repository. Written only by `uv run b1500 dev harness qualify` (maintainer
# commits it); `uv run b1500 update` installs exactly these versions.
codex:  {version: 0.170.0, install: npm,    validated: 2026-11-26, report: docs/acceptance/2026-11-26-codex-0.170.0.md}
claude: {version: 2.1.328, install: native, validated: 2026-11-26, report: docs/acceptance/2026-11-26-claude-2.1.328.md}
```

Seeded in 21.1 from the S1–S18 full-suite reports of 2026-11-26 (the currently installed versions are already
validated). `selection.GLOBAL_TOUCHES` narrows `config/harness/**` to the two templates, so a version bump does not
make every scenario "affected". Model and loader in `devtools/harness_versions.py` (also: installed version, install
method from the executable path, the one installer command per harness).

### 2.2 Operator: `uv run b1500 update`

| Step | What it does | When it cannot (plain message, nothing half-done) |
|---|---|---|
| 1 guard | refuses inside an agent session (any harness marker in the environment: Claude Code shells carry `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `AI_AGENT`; Codex sandboxed shells `CODEX_SANDBOX*`, ATV-40) and without an interactive terminal; `--check` (read-only: no network, no install, no write) runs anywhere | "Run `uv run b1500 update` yourself in a terminal window, not through the agent." |
| 2 repo | on the default branch with a clean tracked tree: `git pull --ff-only` | dirty tracked files → names them, "nothing was changed; ask the maintainer"; another branch (e.g. `lab/bringup-…` after a records transfer) → "`git switch main`, then run update again"; diverged or no network → says so and stops |
| 3 environment | `uv sync --frozen`, then re-runs itself from the pulled code (`--continue`), so a change to `update` takes effect in the same call | offline wheelhouse (`UV_OFFLINE=1`) and `uv.lock` changed → "a new wheelhouse is needed" (deployment § Offline wheelhouse) |
| 4 wiring | `harness init --check` per generated config; on drift `harness init --codex`/`--claude`, check again | still drifting → the file and the fix |
| 5 versions | each installed harness vs `validated.yaml`; different → "Install Codex 0.170.0 now? [y/N]" → `npm install -g @openai/codex@0.170.0` / `claude install 2.1.328`; version read again | another install method found → the one-time switch command; harness not installed → skipped (Claude Code is optional; first install is deployment step D4) |
| 6 hold (lab station: `config/local` backend visa) | Claude Code auto-update off: `DISABLE_AUTOUPDATER=1` in the environment or the user settings' `env` (never `DISABLE_UPDATES`, which also blocks `claude install`); npm-installed Codex does not update itself (the Mac still has 0.170.0 while npm offers 0.172.0) | missing → the one line to add (a note, not a block) |
| 7 free checks | logged in (`codex login status`, `claude auth status`: exit 0/1); no bypass default in the user config (`~/.codex/config.toml` `sandbox_mode = "danger-full-access"` or `approval_policy = "never"`, profiles included; Claude Code `permissions.defaultMode: "bypassPermissions"`); `claude doctor` reports no invalid or dropped entry of `.claude/settings.json` (ATV-34); `codex execpolicy check` forbids the 8 human-only commands; the project is trusted by each harness; `dev mcp-smoke` per generated config (server starts, 10 tools); `b1500 doctor` without FAIL | each failure → one numbered action ("run `codex login`", "start `codex` in the clone once and accept the trust question", …) |
| 8 verdict | "Ready." (exit 0) or "Not ready. Do this: 1. … 2. …" (exit 1) | — |

Fail-safe rule: output `update` cannot read (a changed `claude doctor` wording, an unknown sandbox key) becomes a note,
never a block; the same versions passed the maintainer's checks first. `b1500 doctor` gains `harness versions`: PASS
when installed = validated; WARN "run `uv run b1500 update`"; when the installed version is newer on a non-lab
machine (the maintainer's Mac on the stable channel) the WARN adds "or qualify it: `uv run b1500 dev harness
qualify`"; INFO without a harness (CI). On the lab PC, `update` adds one note when the installed (= validated) version
has no local Windows qualification yet (`data/state/harness/windows.json`, §2.3): "maintainer: run `uv run b1500 dev
harness qualify --windows` once".

### 2.3 Maintainer: `uv run b1500 dev harness qualify`

```
uv run b1500 dev harness qualify [--harness codex|claude] [--candidate VERSION|latest] [--up-to 0|1|2]
                                 [--escalate [--max-sessions N]] [--windows] [--pin] [--json]
```

- Qualifies the installed version, or first installs `--candidate` with the same installer and guard as `update`
  (installing needs a human terminal; qualifying an installed version runs anywhere, like `acceptance run`).
- PASS up to T2: report `docs/acceptance/<date>-<harness>-<version>-qualify.md`, `validated.yaml` bumped, with
  `--pin` the sanitized T1 transcripts as `tests/fixtures/transcripts/<harness>-<version>/`; the maintainer commits;
  operators get the version with their next `update`.
- FAIL: a candidate is replaced by the validated version again; the report names the failed check, its surface and
  the T3 set (§2.6); `validated.yaml` is unchanged.
- `--windows` (lab PC, OD21-3 = a): T0 + T1 + S16, no bump; writes `data/state/harness/windows.json` and a report in
  `work/harness/` (travels with the v2 OD-7 transfer). Run at deployment (D10) and once after each bump arrives.

| Tier | Content | Cost (2026-11-26 reports; T1 est.) | Wall (Mac) | Stop rule |
|---|---|---|---|---|
| T0 | the operator checks of §2.2 step 7 + every runner flag in `--help` (derived from the argv builders in `harnesses.py`, no hand list) + the offline harness tests (428, as §1.1) | free | ~1.5 min | any FAIL |
| T1 | probes `smoke` (with a shell call `uv run b1500 bringup status` that must print `[SIMULATED]`: the runner's temp config reached the agent's shell), `atv-confirm` (2 turns), `atv12` (Claude Code); harness contract §2.5 | est. Claude 0.3–0.6 USD, Codex 0.2–0.4 M input (from S6 r2/r3, S16, S18 sessions) | est. 2–4 min | FAIL or infra event |
| T2 | canary S4 + S5 r1 + S16, 1 rep, no re-run (a ★ 1-rep is a detector, not a §8.2 verdict) | Claude 0.74 M input, 1.26 USD; Codex 1.02 M input (0.90 M cached) | Claude 1.9 min, Codex 4.0 min of turns | FAIL or infra event |
| T3 (`--escalate`) | the set mapped to the failed or at-risk surface (§2.6), §8.2 reps | §2.6 | §2.6 | infra event |

T0–T2 per harness: Claude ≈ 1.6–1.9 USD, ~6 min; Codex ≈ 1.2–1.4 M input tokens, ~9 min.

### 2.4 Stop at the first infra event (owner rule, OD21-4 = a; in the runner, so also `acceptance run`)

`devtools/acceptance/infra.py`: a watcher per turn tails the turn's stdout/stderr as they grow: Codex `turn.failed`,
any `error` event including `Reconnecting… n/m` and the HTTPS-fallback notice, stderr auth/HTTP 401/403/429/5xx/DNS/
connection lines; Claude Code `result` with `is_error` or an error subtype, API-retry events, a `rate_limit_event`
whose status is not allowed, auth errors on stderr. First hit: kill the turn's process tree, mark the session
`infra_stopped`, stop the batch (no next session, no re-run), report the raw line, exit 3. Generic by construction
(any failed completion stops), so it needs no per-release table. Pinned on real transcripts (the 84 informational
`rate_limit_event`s of the 11.5 Claude batch must not trigger) and forged ones.

### 2.5 Harness contract (qualify T1; also a grader `harness_contract`)

- **Structural, FAIL**: every guarded tool call has a `PreToolUse` `hook_response` (11.5 batch: 60 = 59 `Bash` +
  1 `Write`); Codex rollout file found (today only a warning, `runner.py:546-553`); session id, usage and completion
  event present; Claude Code `permissionMode` `default`, b1500 server `connected`, the three skills listed.
- **Table-based, WARN only** (would need hand updates per release): tool names and event/item types outside the
  known vocabulary of the 11.5 batch; shell/write-capable built-ins outside the hook matcher (`Monitor`, the
  schedule/remote tools) are listed as the owner-accepted residual (OD21-5 = c, `docs/safety-model.md`).
- Never part of `update`.

### 2.6 Escalation map (§8.2 reps; turn time from the 2026-11-26 reports)

| Surface failed or at risk | Scenarios | Claude Code | Codex |
|---|---|---|---|
| event format / vocabulary only | none: fix the parser, `acceptance grade` the T1/T2 artifacts | 0 | 0 |
| approval / permission prompt | S4, S11 ★, S12 ★, S15 ★ (10 sessions) | 14.71 USD, 13.8 min | 20.0 M, 32.1 min |
| hook / deny / shell / sandbox | S5 ★, S6 ★, S16, S17 ★, S18 ★ (13) | 7.93 USD, 12.3 min | 8.7 M, 27.9 min |
| server lifecycle / async | S14, S15 ★ (4) | 4.78 USD, 5.3 min | 4.4 M, 9.8 min |
| instruction loading (trust, CLAUDE.md, skills) | refusals S2, S3, S5, S6, S8, S9, S18 ★ (21) | 4.88 USD, 11.0 min | 3.7 M, 22.1 min |
| several / unclear | all ★ (33) | 25.33 USD, 32.6 min | 30.6 M, 69.6 min |
| full suite | S1–S18 (40 + re-runs) | 30.13–30.74 USD, 39–40 min | 34.7 M, 82.4 min |

### 2.7 What stays to maintain

Per harness release, operator side: nothing. Maintainer side: when they want the new version, one `qualify` (≈ 15 min,
the cost above) and one commit; vocabulary tables get extended only when a WARN is worth it. Rare: an installer
command changes (one constant in `harness_versions.py`). The two operator-visible moving parts are `validated.yaml`
and the `doctor` line.

### 2.8 Docs

`deployment-windows.md`: Step 1.6 = one install method per harness + auto-update off (lab PC) + Node.js LTS for npm;
Step 12 "Update" = `uv run b1500 update` only; Steps 8/9 interactive checks stay human. `docs/acceptance/README.md`:
the maintainer's qualify, ladder, costs. `safety-model.md`: the `Monitor`/built-in residual (OD21-5 = c) and the
interactive-only facts. README docs table.

## 3. Design B: debug cases

"Implemented" for each case (3 existing + `2026-11-04-cv-shape-abnormal` from the deck):

1. **Structure**: template v2 = the 10 keys + `reproduction:` (scenario, recipe, pin map, DUT profile, params,
   `expect` symptom signature, `discriminator`: the runbook check that separates the causes and its expected
   result) + `open_questions:` count; sections = the 8 + "Simulator reproduction (SIMULATED)" + "Open questions for
   the owner" (numbered; replaces the inline `TODO(owner)` markers, so nothing is lost and lint can count them).
2. **Reproduction**, real simulator runs, never written into the lab sections (`backend: visa`, `runs: []` stay as
   the deck's facts):
   | Case | Scenario + recipe | Symptom signature | Discriminator (runbook order) |
   |---|---|---|---|
   | current too high | `gd_short`, `mosfet.idvg` | gate compliance `C` at the first step, drain current ≥ 10³× `nmos_basic` | contact check gate-drain `short`; same plan on `nmos_basic` normal ("measure another device") |
   | noisy data | new `nmos_unshielded` (landed device, raised floor), `mosfet.gate_leakage` or subthreshold Id-Vg | SNR < 10 at `integration: short` | SNR ≥ 10 at `long` (deck step 1); `open_drain_noisy` + contact check for the runbook's first branch |
   | IGZO Vth drift | `igzo_transient`, 3 × `mosfet.idvg` back to back | monotonic Vth shift above the fit uncertainty | narrower gate range, then fewer points: smaller shift (deck steps 2–3). WP start verifies the persisted drift; else scenario `igzo_drift_repeat` (recovery τ ≫ run gap) |
   | C-V not S-shaped (new) | `moscap_basic` + fault `cmu_correction_lost`; `moscap.cv_ac_level`; new `moscap_leaky` | R-CORR-01 block / offset; `ac_limit` below the AC level; D > 1 | redo corrections → default AC level → gate leakage first (deck order) |
   Temperature, humidity, Guard and grounding causes have no simulator model: the case says so.
   The case text quotes the numbers and run ids of one reproduction made in the WP (labelled SIMULATED, date,
   commit, "local data dir, regenerate with `uv run b1500 dev cases reproduce <id>`"); the test is the authority.
3. **Links**: `runbook:` resolves; each runbook's `sources` names its case; `vth-drift-igzo.md:16` corrected;
   `cmu-cv-distortion` sources gain the deck item; SKILL §8 lists four seed cases.
4. **Lint** (`devtools/skills/cases.py`, in `lint-skills`): keys and sections; `status: draft` ⇒ `reviewed_by:
   null`; `status: reviewed` ⇒ `reviewed_by` set and zero open questions; scenario, recipe, pin map, DUT exist;
   no inline `TODO(owner)` outside "Open questions".
5. **Test**: `tests/integration/test_debug_cases.py` runs every `reproduction:` through `B1500Service` on temp dirs
   and asserts signature and discriminator (deterministic seeds).
6. **Review tooling**: `uv run b1500 dev cases list` (status, runbook, reproduction verdict, open questions per
   case) and `uv run b1500 dev cases check [--reproduce]`; the guard hook blocks a file write that sets `status:
   reviewed` under `b1500-debug/cases/` (tightening; the human edits the file and commits). SKILL §7 gains the
   three review steps (answer questions, set status + name, `lint-skills`).
7. **Owner questions** (the exact list, each case's "Open questions" section):
   - current too high: typical magnitude seen; device type and terminal; integration/range/error queue at the time;
     typical open-circuit current of the station (number for the runbook's floor check); was it resolved, how.
   - noisy data: current level; module (MPSMU or HRSMU); integration setting; whether "contact check before the
     deck's steps" is the lab's order; resolution.
   - IGZO drift: size and direction of the shift; sweep range; time between runs; recommended rest time and maximum
     gate range (card recommendation); light on the sample as a cause (`vth-drift-igzo.md:21`); resolution.
   - C-V shape: which device/frequency/AC level; which of the three causes it was; resolution.
   - Deck: the other ~6 of "about 10 entries" (`PPT_slides_content.md:689`): where are they?

## 4. Design C: step-by-step bring-up

### 4.1 Step model, ledger, verbs (simplest form that guarantees "every step done and verified")

Options weighed: better docs only (cannot show a skipped drill or observation: no guarantee); records only, as
today (blind to the ~60 steps without a record); a ledger the agent writes as a file under `work/` (forgeable,
unverified); **chosen**: a ledger written only by CLI verbs that verify the evidence at write time and again at
`check`, with sign-off depending on it. It adds one file of step metadata and three verbs, no new concept in the
kernel.

- **`.agents/skills/b1500-bringup/steps.yaml`** (one file; stage files keep the prose and stay ≤ 150 lines): per
  stage the steps in **execution order**, each `{id: L1.A4, who: agent|human|both, verify: <kind>, recipes: [...],
  feeds: [check ids], on_fail: [runbook ids], reconfirm: bool, rehearsal: run_sim|refusal|human_done|skip, items:
  [§7.6 n], atv: [...]}`. Groups beyond the stages: `D1–D12` (deployment = First session lines 2–8 incl. `harness
  verify`), `R1–R4` (session start), `E1–E5` (session end). Lint (`devtools/skills/stages.py`): every numbered stage
  item has exactly one entry and vice versa, recipes ⊆ stage `recipes`, `feeds` ⊆ stage `checks`, every check is fed
  by at least one step, runbooks exist. Model `StepSpec` in `models/validation.py` (additive).
- **Ledger** `data/state/bringup/ledger-<backend>.jsonl`, written only by the CLI (Claude's `Edit(data/**)` deny
  covers it; a Codex hand edit breaks the hash chain; the simulator ledger is a different file and can never sign a
  hardware stage). Entry: seq, step, ts, backend,
  station digest, actor (`agent`, `human_via_agent`), evidence (runs, probe file, drafts, fixtures, config file
  sha256, observation key=value, the human's quote and name, references), verdict + reason, `prev_sha256` (a
  hash chain, 5 lines of code, makes hand edits visible to `check`).
- **Verbs** (`adapters/cli/bringup.py`, logic in a new `bringup_steps.py` beside `bringup.py`, 824 lines):
  `uv run b1500 bringup next [--json]` (read-only: next step with stage, id, who, the stage file's text, expected
  values, pass/fail rule, the exact `bringup done` line to record it, abort route; after a break the R steps and the
  steps with `reconfirm: true` first), `uv run b1500 bringup done STEP [--run ID…] [--probe latest] [--draft PATH…]
  [--fixtures DIR] [--observe K=V…] [--reference CHECK=VALUE…] [--human "QUOTE" --by NAME]` (verifies now, appends
  pass or fail, prints the next step), `uv run b1500 bringup check [STAGE|--all]` (re-verifies every entry against
  current files; exit 1 on a gap). `bringup status` shows `steps a/b` per stage; **signed** = all steps pass + the
  reviewed stage record. `bringup record STAGE` (stage record) embeds the ledger's step list (`ValidationRecord.
  steps`, additive, schema version 2), so the reviewer signs the step list and it travels with the v2 OD-7 transfer.
- **Verification per kind** (machine unless marked): `run` (run exists, backend = ledger backend, recipe in the
  step, outcome, cleanup `verified: lop`, positive control, quality not `untrusted`; on visa `H…`), `probe` (newest
  probe file, no FAIL, backend), `config` (human adopted: `config check` valid, file present, equals the proposal
  after normalisation), `proposal` (schema-valid file under `work/bringup/`), `record` (draft exists, stage/recipe
  match, result pass), `capture` (fixture files exist for the run), `observation` (required keys present),
  `hw_suite` (JUnit summary file of `pytest -m hardware`: no fail, nothing skipped by the gate), `confirm` (human:
  quote + name; the only kind without machine evidence, signed with the stage record), `review` (reviewed record in
  `validation/hw/`, reviewer set).
- Physical steps stay the human's; the agent records the human's own words (OD21-7). Failure: `done` records `fail`
  with the reason; `next` stays on the step and prints the stage's abort criterion: `safe_shutdown(reason)`, skill
  `b1500-debug` with the step's `on_fail` runbooks, wait for the human (latched fault: human `fault clear`).
- SKILL.md §3 "Working a stage" becomes: `bringup next` → do it → `bringup done` → repeat; stage files unchanged
  except gaps (§4.6).

### 4.2 Worked example: stage L1 in execution order

| # | Step | Who | Exact action | Expected reading / pass | Recorded (`bringup done`) | Fail route |
|---|---|---|---|---|---|---|
| 1 | L1.A1 | agent | `uv run b1500 bringup status`; `station_status` | next = L1; no fault, lock holder or run | station snapshot | `cleanup-failed-fault` |
| 2 | L1.A2 | agent | write `open-smus` pin map + `open-circuit` DUT proposals to `work/bringup/` (rehearsal: YAML in chat) | schema-valid, slots = station SMUs | proposal paths | — |
| 3 | L1.P1 | human | DUT disconnected, production cabling, shield closed, interlock open | human confirms | quote + name (reconfirm after a break) | stop |
| 4 | L1.P2 | human | `uv run b1500 config adopt FILE --as pinmap` / `--as dut` | `config check` lists both, `unverified` | config sha256 | — |
| 5 | L1.A3 | agent | `validate_plan system.self_test` → summary, stop, consent → `run_confirmed_plan`; same for `system.self_cal` | `kind_result.result` 0 | 2 run ids → `self_test_result`, `self_cal_result` | `errx-codes` |
| 6 | L1.A4 | agent | zero check `system.zero_check` (`open-smus`, `open-circuit`), consent, run; `analyze_run zero_floor` | all `N`, cleanup `lop`, positive control, floors < sanity | run id → `cleanup_lop`, `floor_smu3..6`, `lop_positive_control` | `cleanup-failed-fault`, `current-too-high` |
| 7 | L1.A5 | agent | same, `{integration: long, samples: 50}` (async, poll `get_run`) | floors ≈ 1/3 | run id | `async-run-interrupted` |
| 8 | L1.A6 + L1.P3 | both | human: `uv run b1500 run --confirm PLAN_ID`, Ctrl+C; then `uv run b1500 shutdown --reason "L1 drill"` in a 2nd window | `aborted`/`cancelled`, audit `AB DZ CL ERRX? LOP?`, lock free, no fault | 2 run ids + `lock status` observation → `shutdown_drill` | `cleanup-failed-fault` |
| 9 | L1.A7 + L1.P4 | both | human: `uv run b1500 status`, `uv run b1500 lock status` while the agent idles | answers each time | observation `coexistence=pass` | `visa-no-connection` |
| 10 | L1.A8 | agent | short zero check, `uv run b1500 bringup capture H…` | ten MM 1 FMT 1 blocks | fixture dir | — |
| 11 | L1.R | agent → human | `bringup record L1 --run …` (+ `--recipe` ×3); human reviews into `validation/hw/` | drafts pass; reviewer set | draft paths; then `review` | — |

Resume: `bringup next` after a break lists R1–R4 (`uv run b1500 doctor`, `station_status` clean, no running run,
EasyEXPERT exited) and re-asks L1.P1 before step 5 onward.

### 4.3 Owner sessions (durations are rough estimates; real ones are a §7.6 item 10 outcome)

| Session | Steps | Content | Est. |
|---|---|---|---|
| 0 | D1–D12 | lab PC install, clone, harness wiring, `uv run b1500 update` ("Ready."), `dev harness qualify --windows` (T0 + T1 + S16) and the interactive checks | 2–3 h (+ lab IT) |
| 1 | R, S0, L0, E | physical prerequisites, read-only probe, station proposal and adoption | 2 h |
| 2 | R, L1–L3, E | zero, drills, coexistence, resistors (DMM), diode | 3 h |
| 3 | R, L4–L5, E | MOSFET vs EasyEXPERT, pulsed, sampling, search | 3–4 h |
| 4 | R, L6, E | CMU corrections (human lifts/lands), C-V family | 3–4 h |
| 5 | R, L7, E | selector map, SPGU into 1 MΩ (scope), FeFET | 3–4 h |
| 6 | R, L8, E | WGFMU session, self-test/cal, RSU DC, fast IV, waveforms, noise, PUND | 4 h |
| 7 | R, L9, E | async runs, cancel/kill drills per bus, endurance/retention (interactive harness kept open) | 1 day |
| 8 | R, L10, E | prompts on hardware, review, hardware suite, transfer (v2 OD-7) | 2 h |

The non-stage groups (same fields as every step; `who` in brackets):

- **D** (session 0; = First session lines 2–8 of `deployment-windows.md`): D1 Git, uv, Python 3.12 [human];
  D2 VISA stack + GPIB driver [lab IT]; D3 WGFMU library ≥ A.03.00 x64 [lab IT]; D4 harness CLIs by the one method each
  (Node.js LTS + `npm install -g @openai/codex`; Claude Code native `irm https://claude.ai/install.ps1 | iex`), signed
  in, Claude Code auto-update off (`DISABLE_AUTOUPDATER=1`, OD21-2) [human]; D5 `setx PYTHONUTF8 1` [human]; D6 clone + manuals folder [human]; D7 `uv sync
  --frozen`, `uv run b1500 manual status`, `uv run b1500 doctor` (no FAIL) [agent or human; verify: doctor JSON];
  D8 `uv run b1500 harness init --codex [--claude]` [human]; D9 start each harness in the clone once and accept the
  trust question [human; observation]; D10 `uv run b1500 update` → "Ready." (installs the validated versions, runs
  the free checks), then the maintainer's `uv run b1500 dev harness qualify --windows` (OD21-3) [human; verify: the
  verdict and `data/state/harness/windows.json`]; D11 interactive checks (deployment 8.5, 9.4–9.5: approval prompt shows the
  summary, `/hooks` lists the guard) [human; observation]; D12 "Recorded results" values (versions, library path,
  install route) [human; observation].
- **R** (start of every session): R1 `uv run b1500 doctor` (no FAIL; `harness versions` PASS, else `uv run b1500 update` first);
  R2 `station_status` clean (no fault, lock holder or running run); R3 human: EasyEXPERT exited, the day's interlock
  test (UG daily), shield box, DUT state as the ledger expects; R4 `uv run b1500 bringup next` (lists the steps to
  reconfirm).
- **E** (end of every session): E1 `safe_shutdown("end of session")`, `station_status` clean; E2 human:
  `$env:B1500_HW = "1"; uv run pytest -m "hardware and hw_<stage>" -rs --junitxml work\bringup\hw-<UTC>.xml` for the
  stages touched (verify: the JUnit file, nothing skipped by the gate); E3 `uv run b1500 bringup check`; E4 human:
  back up `data\runs` and `config\local`; E5 human: review the drafts of finished stages, transfer (v2 OD-7).

### 4.4 Rehearsal (a test, no hardware data)

`tests/integration/test_bringup_sequence.py` walks D (rehearsable parts), R, S0–L10, E on the simulator with a
scripted human: the physical step "land the 100 kΩ resistor" switches the temp config's `settings.sim.scenario`
(`resistor_100k`, `diode_basic`, `lab_nmos_2025`, `moscap_basic`, `capacitor_100p`, `fefet_lab`, `nmos_wgfmu`,
`fecap_basic`, `nmos_bti` …; missing scenarios found in the WP are added), plans go through `B1500Service` with
consent as in the integration tests, `record`/`capture` steps assert the refusal of `S…` runs (`rehearsal:
refusal`), and at the end `bringup check --all` passes on the sim ledger while `bringup status` never says
`signed` (it says `rehearsed`). Variants: visa-loop for S0–L2 (`H…` runs, drafts and fixtures in `tmp_path` only;
assert nothing outside it changed), failure routing (fault `cleanup_failure` at L1.A4 → `fail`, `next` stays and
names `cleanup-failed-fault`; after the scripted `fault clear` the retry passes), resume (new process, clock + 1 day
→ R steps and reconfirm list), tamper (an edited ledger line → `check` exit 1). Runtime target ≤ 3 min, marker
`rehearsal` run serially in CI.

### 4.5 S17 and the skill

S17's flow changes (the agent now uses `bringup next/done`), so its graders gain `bringup_steps` (ledger entries
in order, human steps only after the human's turn, no `done` of a human step before the human said so); nothing is
loosened. S17 ★ re-runs on both harnesses.

### 4.6 Classification of the `TODO(verify)` markers

Full table: `tmp/v2_orch/plan_v21_todo_verify.md` (196 occurrences on 177 lines in `.agents src docs`; appendix: 40
in `recipes config tests`; the `.claude/` mirror follows `.agents`).

| Class | Occ. | What happens (WP) |
|---|---|---|
| H hardware-bound (§7.6) | 70 | keep; append the resolving step ids `TODO(verify)[L1.A4]` (substring unchanged, so `tests/skills/test_bringup_stages.py:346` "one per stage file" still holds); the step's `items:`/`atv:` carry the link (21.8). Today the resolving step captures the evidence for 13, partly for 45, not at all for 12 |
| C closable now | 30 | 5 C-man close with the cited page (e.g. `kn/02:67` → PG p67 (1-47) Table 1-14 + PG p334 (4-16); `kn/01:63` → EX p317 (4-23)); 3 C-code reworded as code facts (unreachable paths); 1 C-doc reworded; 21 C-lit become `TODO(cite)` unless a checked source is already named (they are literature values, not hardware) (21.8) |
| S duplicates | 32 | reduced to the canonical marker with a pointer (21.8) |
| D convention / history | 64 | unchanged (49 are `progress.md` history) |

By resolving stage (H): S0 1, L0 7, L1 2, L2 3, L3 1, L4 2, L5 5, L6 18, L7 11, L8 12, L9 7, L10 1.

Gaps the sequence must close (21.6): **new steps or check ids** — two-wire minus four-wire R at L2 (station
contact/lead resistance), ASU presence recorded (L0.P2 or L4), 16440A relay settle by scope and an `ERSSP?`
negative control (L7), log-mode sampling run + capture (L5), sampling time stamps over hours (L9), ATV-17
(SMU bias held across `initialize`, L8), FeFET read-disturb window (L7), PUND ramp-rate series (L8), a second probe
after the corrections for `ADJ? ch,0` (L6), CMU correction drift over a day → `max_age_h` (L6 start/L9 end), how each
harness ends the server during an async run (L10, with L9's drill); **check ids/record fields for facts now only in
the audit** (ATV-2/4/13 timings at L0, `*TST?`/`*CAL?` and library self-test durations, idle `LOP?` codes, L2
warm-up, approval-prompt facts ATV-7/8/11/25, L5 `time_source`, CMU and WGFMU timings, pulse edges/overshoot, PG level
on the V Monitor); **capture**: `bringup capture` steps at L2, L3, L5, L7 and fixture kinds for `*LRN? 62/63/81/90`,
`CORRDT?`, `DCORR?`, `CORRL?` and the WGFMU library strings (`service/evidence.py:111-125`). **Reword instead of a
step** (no safe or possible measurement): `CORRSER?` format (no kind sends it; mark unused), `*RST` parts of ATV-18
(no tool sends `*RST`: power-on + device clear only), WGFMU state after FLEX device clear (conservative simulator
assumption), the instrument's correction-list maximum (PG p384 (4-66) gives none; keep 64). **Owner/data-sheet
facts** (OD21-10): WGFMU Fast-IV short-circuit current for R-GNDU-01 (not in the corpus), MFCMU DC current limit if
the manual corpus has none.

## 5. Work packages (v2 §10 format; on `main`, D-1)

Definition of done, gate, progress row and commit rules as v2 §10 / the preamble; progress gets a "v2.1" section.
`Deps` are the logical dependencies; execution is the single sequence of §6.
Every AC command is run literally. Live harness sessions only in 21.9 (D-8); the free live checks `uv run b1500 update
--check` and `uv run b1500 dev harness qualify --up-to 0` run in their WPs.

| WP | Deps | Scope and files | AC | Tests · docs | Acceptance | Size |
|---|---|---|---|---|---|---|
| **21.1 Operator `b1500 update`** (A) | — | `config/harness/validated.yaml` (seeded: codex 0.170.0, claude 2.1.328, the 2026-11-26 full-suite reports); `devtools/harness_versions.py` (model, installed version, install method from the path, the two installer commands); `devtools/update.py` (§2.2 steps 1–8, `--check`, `--continue`); `adapters/cli/core.py` (top-level `update`; `harness` group unchanged); `devtools/doctor.py` (`harness versions` line); `selection.py` (`GLOBAL_TOUCHES`: the two templates instead of `config/harness/**`) | `uv run b1500 update --check` on the Mac: verdict matches the state (Ready while installed = validated); `uv run b1500 update` from the executor's own agent shell prints the refusal and changes nothing (live proof of the guard, no download); fake `git`/`uv`/`npm`/`claude`/`codex` executables on `PATH` cover every row of §2.2 (clean pull, dirty tree, other branch, diverged, offline, wheelhouse + `uv.lock`, drift repaired, install yes/no, foreign install method, not logged in, bypass default, execpolicy allows, unreadable output → note); Windows paths and the PowerShell environment by platform injection; `uv run b1500 doctor` shows the line; `uv run pytest -q tests/adapters/test_docs_commands.py` | `test_update.py`, `test_harness_versions.py`, doctor tests · `deployment-windows.md` Step 1.6 (one install method per harness, auto-update off on the lab PC, Node.js LTS), Step 12 = `update`, Recorded results; README | none (no installer is run: guardrail 7) | M (~500) |
| **21.2 Maintainer qualify + runner** (A) | 21.1 | `devtools/acceptance/infra.py` (§2.4) + `runner.py` (watcher per turn, batch stop, exit 3, rollout missing = error); `graders.py` (+ `harness_contract`, §2.5); `devtools/harness_qualify.py` (ladder, candidate install via `harness_versions`, restore on FAIL, bump, report, `--windows`, `--pin`) + `adapters/cli/dev.py` (`dev harness qualify`); vocabulary baseline of the 11.5 batch; `harnesses.py` (prompt on stdin for `.cmd` shims, ATV-33); probe `smoke.yaml` (+ shell step); `docs/safety-model.md` residual (OD21-5 = c) | `uv run pytest -q tests/acceptance -m "not acceptance"`; forged transcripts per infra pattern stop a fake-harness batch after that session, no re-run; the 84 `rate_limit_event`s do not; structural contract checks FAIL on forged gaps, vocabulary drift and `Monitor` only WARN; `uv run b1500 dev harness qualify --up-to 0` PASS on both harnesses (free); fake-harness tests for bump, restore on FAIL, `--windows` record; free regression on real data: `uv run b1500 dev acceptance grade` of the local WP11.5 batches (`<tmp>/b1500-acceptance/20261125T204845Z-codex-0.170.0`, `…/20261125T221153Z-claude-2.1.328`, if still present) leaves every existing verdict unchanged, `harness_contract` adds WARNs only; ATV-36 shapes from a logged-out run (empty `CLAUDE_CONFIG_DIR`/`CODEX_HOME`, no API call) | `test_infra_stop.py`, `test_harness_contract.py`, `test_harness_qualify.py`, Windows argv by injection · `docs/acceptance/README.md` (maintainer section), `safety-model.md` | qualify T1–T2 live in 21.9 | M (~700) |
| ~~21.3 Claude tool surface~~ | — | dropped (OD21-5 = c): no `.claude/settings.json` change for built-in tools; the residual is documented in 21.2 | — | — | — | — |
| **21.4 Debug cases** (B) | — | case template v2; 3 cases completed + `2026-11-04-cv-shape-abnormal.md`; runbooks `vth-drift-igzo` (line 16), `cmu-cv-distortion`, `current-too-high`, `noisy-data` (sources → cases); `SKILL.md` §7–§8 (97/100 lines: rewrite within budget); scenarios `nmos_unshielded`, `moscap_leaky` (+ `igzo_drift_repeat` only if ATV-37 fails); `devtools/skills/cases.py` in `lint-skills`; `devtools/cases.py` + `uv run b1500 dev cases list\|check\|reproduce`; hook: block agent writes of `status: reviewed` in `b1500-debug/cases/` | `uv run b1500 dev lint-skills` (4 cases, 0 inline `TODO(owner)`); `uv run b1500 dev cases check --reproduce` exit 0; `uv run pytest -q tests/integration/test_debug_cases.py tests/skills/test_debug_skill.py tests/adapters/test_guard_hook.py`; new scenarios meet their stated truth; `sync-harness --check` | `test_debug_cases.py`, case lint tests · SKILL §7–§8, `docs/coverage.md` regenerated if counts change | S7 (1 rep, both) in 21.9 (noisy-data runbook/case touched); S15 not (it uses the router/§1–§6, unchanged; say so) | M (~450 + text) |
| **21.5 Step model, ledger, verbs** (C) | — | `models/validation.py` (`StepSpec`, `LedgerEntry`, `ValidationRecord.steps`, record schema 2); new `bringup_steps.py` (steps.yaml loader, ledger with hash chain, verifiers per kind, next/done/check; layering rank = `bringup`); `bringup.py` (status `steps a/b`, `signed` rule, stage record embeds steps); `adapters/cli/bringup.py` (`next`, `done`, `check`); the three Claude Code allow lines of OD21-6 in `.claude/settings.json` (applied once by the orchestrator, as v2's OD-5 at WP6.1) + `devtools/harness.py` `CLAUDE_ALLOW_COMMANDS` + `deployment-windows.md` §Harness permissions; `.agents/skills/b1500-bringup/steps.yaml` for S0–L10 + D/R/E (148 stage steps in execution order); steps lint in `devtools/skills/stages.py`; `tests/unit/test_import_layering.py` | `uv run b1500 dev lint-skills` (every numbered item ↔ one step, recipes/feeds/runbooks resolve, every check fed); `uv run b1500 bringup next` on the sim prints D1; unit tests per verifier (pass, fail, wrong backend, `S…` on visa, changed run file, tampered chain); `bringup status` unchanged for v2 records (schema 1 still loads) | `test_bringup_steps.py`, `test_cli_bringup.py`, `test_harness_permissions.py` (the three lines; `uv run b1500 harness init --claude --check` ok), `tests/hardware/test_records.py` (schema-2 stage records need complete steps) · `validation/hw/README.md` | none | L (~900) |
| **21.6 Bring-up sequence content** (C) | 21.5 + companion file | gap steps and check ids of §4.6 in stage files (≤ 150 lines each; trim repetition, no budget raise) and `steps.yaml`; capture steps L2/L3/L5/L7; fixture kinds in `service/evidence.py`; `b1500-bringup/SKILL.md` §2–§4 (next → do → done loop; ≤ 120 lines); `docs/hardware-bringup.md` (sessions §4.3, verbs); `deployment-windows.md` First session = D1–D12, Recorded results → ledger observations; `docs/roadmap.md` M12 table (item 14 row resolved) | `uv run b1500 dev lint-skills`; `uv run pytest -q tests/skills/test_bringup_stages.py tests/adapters/test_docs_commands.py tests/adapters/test_docs_v2.py`; `uv run b1500 bringup capture` of a visa-loop run writes the new fixture kinds (test) | capture-kind tests · the docs named | S17 in 21.9 | M (~250 + text) |
| **21.7 Rehearsal test + S17 graders** (C) | 21.6 | `tests/integration/test_bringup_sequence.py` (+ helpers), `tests/visa_loop/test_bringup_sequence_visa.py`, missing stage-DUT scenarios found while walking; `devtools/acceptance/bringup_graders.py` (`bringup_steps`), `S17` yaml (+grader), ideal/violating fixtures; marker `rehearsal` (`pyproject.toml`), CI step | `uv run pytest -q -m rehearsal` (sim walk, visa-loop S0–L2, failure routing, resume, tamper) ≤ 3 min; `uv run pytest -q tests/acceptance -m "not acceptance"` (new grader passes ideal, fails violating) | as listed · `docs/acceptance/README.md` (S17 criteria) | S17 ★ both in 21.9 | M (~150 src, ~700 tests) |
| **21.8 `TODO(verify)` hygiene** (C) | 21.6 | per companion table: C closed with citations/code refs, C-lit → `TODO(cite)`, S reduced to canonical, H suffixed with step ids; lint rule `todo_verify` (every live marker in `.agents src docs` outside the D allowlist names steps that exist in `steps.yaml`); roadmap M12 table checked against `steps.yaml` `items:` | `uv run b1500 dev lint-skills` (marker rule); `grep -rn "TODO(verify)" .agents src docs` = H rows + D rows only (counts in progress); `uv run pytest -q tests/skills tests/adapters/test_docs_v2.py` | lint tests · knowledge, safety-model, roadmap | none (text outside skills' behaviour; knowledge edits are wording only) | S (~100 + text) |
| **21.9 Closure + acceptance phase** | 21.8 | full gate; acceptance from the main checkout with a clean `git status`, serially, infra watcher on: `uv run b1500 dev harness qualify --pin` (T0–T2, both harnesses; bumps `validated.yaml` only if the installed version changed meanwhile), `uv run b1500 dev acceptance run --harness codex\|claude --scenario S17` (★ 3), `--scenario S7` (1); reports with usage; roadmap "v2.1" section; progress rows; then the single push of `main` (OD21-11 = a), whose CI run is the Windows evidence | gate green; §8.2 thresholds on every run scenario; qualify T0–T2 PASS with reports in `docs/acceptance/`; pinned fixtures for the qualified versions; CI green on both OS for the pushed commit (URL in progress) | — · roadmap, README status, `docs/acceptance/` reports | as listed (§6) | S |

## 6. Order and acceptance budget

One sequence in the main checkout on `main` (D-1): no branch, no worktree, no cherry-pick; each WP starts from the
previous WP's green commit.

```
21.1 update ─► 21.2 qualify + runner ─► 21.4 debug cases ─► 21.5 step model + verbs ─► 21.6 sequence content
     ─► 21.7 rehearsal + S17 grader ─► 21.8 TODO(verify) hygiene ─► 21.9 closure + acceptance
```

Why this order: 21.2 builds on 21.1's `validated.yaml` and installers; the infra stop and the contract grader exist
before any live session; 21.4 is independent and puts the S7-relevant text (noisy-data case, runbook sources) early;
21.5 introduces the verbs and `steps.yaml` with its lint in one commit (the three Claude Code allow lines of OD21-6
are applied by the orchestrator in the same WP, as v2's OD-5 at WP6.1), so no commit has an unlinted step file; 21.6
needs the verbs; 21.7's rehearsal walks the final `steps.yaml` and its S17 grader sees the final skill text; 21.8 only
rewrites markers and adds a lint, after the step ids exist. Every text change S7 and S17 depend on lands before 21.9,
so each scenario runs once. Critical path is the sequence itself (C ≈ 60 % of the work).

**Acceptance budget (21.9, OD21-9 = a; 2026-11-26 per-session numbers; T1 estimated):**

| Item | Claude Code | Codex |
|---|---|---|
| `dev harness qualify` T1 + T2 (S4, S5 r1, S16) | ≈ 1.6–1.9 USD, ~6 min | ≈ 1.2–1.4 M input, ~9 min |
| S17 ★ × 3 | 6.59 USD, 8.7 min | 7.55 M, 17.4 min |
| S7 × 1 | 0.71 USD, 1.3 min | 0.60 M, 2.5 min |
| **Total** | **≈ 8.9–9.2 USD, ~16 min of turns** | **≈ 9.4–9.6 M input (≈ 93 % cached), ~29 min** |

Why not more: the runner and `harness.py` are in `GLOBAL_TOUCHES` and 21.5 changes `.claude/settings.json`, so
`--affected` will select all 18 scenarios; the runner changes are exercised by every session above and proven offline
(forged and real transcripts, the free re-grade of the WP11.5 batches); the skill changes reach only S7 and S17; the
three allow lines are read-only bring-up/CLI-ledger commands, exercised by S17 (and S16 in T2). Not in this budget:
the lab PC's `qualify --windows` at deployment D10 (≈ 0.5–0.8 USD + ≈ 0.4–0.6 M tokens, M12). On any
login/API/network event the batch stops (21.2) and the orchestrator waits for the owner.

## 7. Risks

| Risk | Mitigation |
|---|---|
| `update` meets a state it does not expect (dirty tree, lab branch, offline, wheelhouse) | it changes nothing and names the one action; every row of §2.2 is a test with fake executables |
| An installer fails midway or the installed version still differs | verdict "Not ready" with the installer's message; the harness is never left on an unqualified version silently (doctor WARN at every session start) |
| An agent runs `update` and downloads binaries | environment markers + interactive-terminal requirement (two independent conditions); ATV-40 for Codex markers on Windows |
| Pulling `main` on the lab PC deploys half-done work | `main` is pushed once, after 21.9 (OD21-11) |
| Infra watcher misclassifies | generic rule (any failed completion stops), pinned on real and forged transcripts; strict (OD21-4); raw line in the report |
| Vocabulary tables go stale | WARN only, in the maintainer's report; never in `update` |
| Claude Code settings silently ignored in `-p` after an upgrade | `claude doctor` in T0 (operator and maintainer), T1 hook coverage + `atv-confirm` |
| `Monitor` (and other built-ins) run commands outside the guard hook | owner-accepted residual (OD21-5 = c), WARN in every qualify report, stated in `safety-model.md` |
| Runner never ran live on Windows (`.cmd` shims, quoting, kill, env propagation) | stdin prompts, platform-injected tests, the smoke shell step first; ATV-33/38; only `qualify --windows` runs there |
| A live check on the lab PC reaches the instrument | runner config forces `backend: sim` (`runner.py:175-228`), the smoke shell step proves the env reached the agent's shell, no measurement scenario on the lab PC (OD21-3 = a) |
| Ledger fatigue (≈ 170 `done` calls over nine sessions) or skipped recording | `next` prints the exact `done` line; the agent records, the human only answers; `signed` requires complete steps |
| `steps.yaml` drifts from the stage prose | lint both ways (21.5); `next` prints the prose from the stage file |
| Stage files exceed 150 lines with the gap steps | trim repetition, move detail to knowledge; no budget raise without the owner |
| S17 behaviour changes with the new loop | grader extended, ideal/violating fixtures first; text iterations only; one S17 re-run ≈ 2.2 USD / 2.5 M |
| IGZO drift not reproducible across runs | ATV-37 fallback scenario |

## 8. Assumptions to verify (new ids from 33)

| Id | Assumption | Where | Fallback |
|---|---|---|---|
| ATV-33 | The runner launches `claude.exe` and the npm `codex.cmd` shim from Python on native Windows; prompts on stdin (`codex exec -` reads stdin per its `--help`; `claude -p` reads stdin) avoid cmd.exe quoting; `taskkill /T` ends the tree | 21.2 (injection), D10 | `qualify --windows` limited to T0 + human checks; T1 for that version only on the Mac |
| ATV-34 | `claude doctor` names a malformed or dropped entry of the project `.claude/settings.json` without starting a session | 21.1 (temp project with a bad rule) | unreadable output is a note (operator); qualify's T1 coverage + `atv-confirm` are the live proof |
| ATV-36 | Infra-error shapes can be pinned without spending: a logged-out run (empty `CLAUDE_CONFIG_DIR` / `CODEX_HOME`) shows the auth failures; retry and rate-limit shapes from the docs and the 11.5 batch | 21.2 | any non-success completion stops (strict, generic) |
| ATV-37 | `igzo_transient` drifts across back-to-back `mosfet.idvg` runs | 21.4 start | scenario `igzo_drift_repeat` (recovery τ ≫ run gap) |
| ATV-38 | Codex passes the harness process env (`B1500_CONFIG_DIR`, `B1500_DATA_DIR`) to its shell commands on Windows as on macOS | D10 (T1 smoke shell step) | runner sets them through Codex's `shell_environment_policy` override (`-c`) |
| ATV-39 | `claude install <version>` installs that exact version, also a lower one, on macOS and Windows; `npm install -g @openai/codex@<version>` likewise (documented for the native installer; Windows parity not documented) | 21.1 (fakes), D4/D10 (real, human) | Windows: the documented PowerShell installer with the version argument, printed by `update` |
| ATV-40 | Codex sets a recognisable variable in its shells on Windows (`CODEX_SANDBOX*` on macOS) | D10 | the interactive-terminal requirement alone (agent shells have no TTY) |

(ATV-35 dropped with WP21.3.)

## 9. Owner decisions (resolved 2026-11-26 unless marked open)

1. **OD21-1 → resolved: redesign.** Operator `uv run b1500 update` installs exactly the versions in the committed
   `validated.yaml` with one installer per harness; the maintainer's `uv run b1500 dev harness qualify` carries the
   cost ladder and bumps the file (§2).
2. **OD21-2 → resolved: hold on the lab PC** (Claude Code `DISABLE_AUTOUPDATER=1`, one-time deployment step D4;
   npm-installed Codex does not update itself), **stable channel on the Mac** (`autoUpdatesChannel: "stable"`; a newer
   version shows as a `doctor` WARN pointing to `qualify`).
3. **OD21-3 → resolved: (a).** On the lab PC only `dev harness qualify --windows` (T0 + T1 + S16), at deployment and
   once per bump; no measurement scenario there.
4. **OD21-4 → resolved: (a)** strict stop, including reconnect notices.
5. **OD21-5 → resolved: (c).** No `.claude/settings.json` change for built-in tools; `Monitor` and the other
   unguarded built-ins are an owner-accepted residual in `docs/safety-model.md`; `harness_contract` WARNs. WP21.3
   dropped; no S5/S6/S18 re-runs.
6. **OD21-6 → resolved: (a)** `bringup next|done|check` + the three Claude Code allow lines `Bash(uv run b1500 bringup
   next*)`, `Bash(uv run b1500 bringup done*)`, `Bash(uv run b1500 bringup check*)`, applied once by the orchestrator
   in WP21.5 (as v2's OD-5) and asserted by `devtools/harness.py` + `test_harness_permissions.py`.
7. **OD21-7 → resolved: (a)** the agent records the owner's own chat words; the owner signs the stage record.
8. **OD21-8 → resolved:** the nine sessions of §4.3 as they are.
9. **OD21-9 → resolved: (a)** targeted acceptance (§6).
10. **OD21-10 → open, not blocking:** the debug-case questions of §3 item 7; the ~6 deck entries not in the deck;
    the B1530A Fast-IV short-circuit current (data sheet); the MFCMU DC current limit if the corpus has none.
11. **OD21-11 → open: pushing `main`.** All work is on `main` (D-1) and `update` on the lab PC pulls `origin/main`, so
    every push is a release. (a) push once, at the end of 21.9, after the gate and the acceptance phase (that run
    is also the Windows CI evidence); (b) push after every WP (CI per WP, but the lab PC could pull half-done work).
    **Recommend (a).** Also confirm for deployment: Node.js LTS on the lab PC (npm is the one Codex install method).

## 10. Decided here (veto if you disagree)

- **D-1** (owner, 2026-11-26) No new branch: all WPs run sequentially in the main checkout on `main`, no worktrees,
  no cherry-picks, one commit per WP (`WP21.n …`); progress gets a "v2.1" section; acceptance in 21.9 from the same
  checkout with a clean `git status`.
- **D-2** Operator command `uv run b1500 update` (top level, human-run); maintainer command `uv run b1500 dev harness
  qualify` (dev group).
- **D-3** `config/harness/validated.yaml` is the committed truth of harness versions; machine-local state only for
  the Windows qualification note and the bring-up ledger (`data/state/`, written only by the CLI, never committed).
- **D-4** One `steps.yaml` for the whole sequence; stage files keep the prose and their 150-line budget.
- **D-5** Marker syntax: `TODO(verify)[<step ids>]` for hardware facts (the substring stays, existing tests hold),
  `TODO(cite)` for literature values that need a checked citation; lint enforces both.
- **D-6** Debug cases keep the lab facts (deck: `backend: visa`, `runs: []`) apart from the simulator reproduction
  (own section, run ids labelled SIMULATED with date and commit); the test is the authority.
- **D-7** The guard hook blocks agent writes that set `status: reviewed` in a case (tightening; no settings change).
- **D-8** All live harness sessions happen once, in 21.9, after every text change.
- **D-9** Transcript pins for qualified versions come from `qualify --pin`; the old 0.167.1/2.1.326 pins stay as
  regression fixtures.
- **D-10** `acceptance run` uses the infra watcher by default (`--no-infra-stop` exists only for offline tests).
- **D-11** Exactly one install method per harness on both OSes: Claude Code native build (`claude install
  <version>`), Codex npm (`@openai/codex@<version>`; the Mac's Codex already is the npm package under Homebrew's
  Node: `/opt/homebrew/bin/codex -> ../lib/node_modules/@openai/codex/bin/codex.js`). Anything else gets a plain
  message.

## 11. Orchestrator amendments (2026-11-26, after the owner's later decisions; they win over §5/§6)

- **Token cost (owner: "reduce Claude and Codex conversation turns in the tests, they cost many tokens")**:
  - 21.7: S17 gains no turn. Consolidate its 4 turns into fewer where every existing grader still applies (never drop
    or loosen a grader); the new `bringup_steps` grader works on the turns that remain. Keep §8.2 reps (★ 3).
  - 21.8: `dev harness qualify` defaults to `--up-to 1` (probes); T2 canaries run only with `--up-to 2` or when T1
    ends with a WARN on a structural surface. T1 uses as few sessions/turns as the checks allow (merge probes where
    the checks survive).
  - 21.9: no live qualify T1/T2 when the installed versions equal `validated.yaml` (T0 only, free; `--pin` from the
    S17 transcripts if possible, else skip pinning and say so); S17 ★ on both harnesses; S7 only if 21.4 changed text
    the S7 agent reads (noisy-data runbook body, contact-check card, b1500-debug SKILL §1–§6) — `sources:` metadata
    or case files alone do not count; say which.
- **Codex startup notice (owner, OD21-4 refined)**: "failed to refresh available models: request timed out" is a NOTE
  in the report, never a stop; every other error event still stops (21.8 implements it, with a pinned fixture test).

## 12. Knowledge provenance (owner 2026-11-26) and the RSU limit — new WPs (orchestrator; they win over §5/§6)

Owner rule (verbatim intent): unfounded or placeholder numbers in skill/knowledge text mislead; an explicit blank that
the agent reports is better than a plausible guess. Not a purge: only unfounded values go. The owner's deck is
illustrative only, never evidence; `../lwp/` (real lab code and data) and the manual corpus are evidence. Audits
(read-only, at `d839847`): `tmp/v2_orch/kaudit_{physics,instrument,cards,config}.md` (≈ 1,300 claims; S/P/L/X/K).

Decisions (orchestrator):
- **KD-1 markers**: `TODO(owner)` = a fact only the owner knows (device, film, process, station, lab practice);
  `TODO(verify)[<step ids>]` = a hardware measurement gives it (bring-up step); `TODO(cite)` = a literature value that
  needs a checked source. An `L` blank names what is unknown and how to get it, in one short line.
- **KD-2 one owner question list**: `docs/open-questions.md`, generated (by `uv run b1500 dev gen-index`, `--check` in
  the gate) from every `TODO(owner)` marker, grouped by topic, each with its file link and the exact question. The
  debug cases' open questions feed it too.
- **KD-3 agent behaviour**: skill text (b1500-test SKILL.md within budget, knowledge README, b1500-debug SKILL): a
  value marked TODO(owner|verify|cite) or "unknown" is blank — say so, ask the human or name the bring-up step; never
  fill it from general knowledge or from the simulator. Autonomous re-measure only inside ranges that have a source
  or that the human gave; unsourced device ranges (FeFET program/read/sweep levels, stress levels, IGZO time scales)
  need the human's values first.
- **KD-4 simulator values**: allowed in text only where labelled "simulator example (scenario X), not a real-device
  value". Example DUT profiles keep values the simulator tests need, with that label; anything presented as "lab" or
  "real/typical device" carries no simulator value (blank + TODO(owner)); tests take expectations from the sim
  scenario truth, never from a "lab" profile.
- **KD-5 debug cases**: the audit's preferred reframing (`kaudit_cards.md` §5): `origin: illustrative|observed`,
  `backend: none` for illustrative, ids/files `example-*`, "Example:" titles, no past-tense lab history, open questions
  reduced to "has the lab seen this?" plus the genuine unknowns; lint/template/test/SKILL/runbook links follow.
- **KD-6 X rows**: wrong physics and contradictions are corrected with a source or deleted; fake-precise numbers go.
  If an X reveals a wrong value in CODE (rules, analysis, guard), fix the code with a test (tightening only; never
  loosen a safety rule).
- **KD-7 K rows**: functional defaults stay; text that presents them as device recommendations is reworded ("example
  default, set it per device"); bring-up tolerances that a step needs stay as "provisional criterion (basis: … | none
  — owner confirms before signing)" and appear in the owner list; safety limits and owner decisions are untouched.
- **KD-8**: WP21.8 (TODO(verify) hygiene, companion table) is absorbed into 21.10–21.12 (same files, one pass); its
  lint (`todo_verify` + the new markers) lands in 21.12.

New WPs (all on `main`, sequential; DoD/gate/progress as before):
- **21.13 RSU From-SMU limit (safety, first after 21.5)**: WG p20 "Maximum input voltage to the From SMU terminal is
  ±25 V"; `driver/modules.py` `smu_mode_max_v` is defined but unused; RSU state `smu` is routable
  (`models/routing.py`). Add the core rule (route family) + OutputGuard runtime check + validate-time block for any
  SMU role whose route passes an RSU in state `smu` with |V| > 25 V (and current above `smu_mode_max_a`), tests
  (sim + visa-loop), knowledge/card text, safety-model. No acceptance scenario (offline proof), unless a ★ grader
  covers it.
- **21.10 Knowledge files**: `.agents/skills/b1500-test/knowledge/**` per `kaudit_physics.md` + `kaudit_instrument.md`
  (+ companion TODO(verify) rows of those files), KD-1..KD-7; README marker convention.
- **21.11 Cards, skills, runbooks, cases, stages**: per `kaudit_cards.md` (+ companion rows), KD-3, KD-5; S7/S17
  relevant text noted for 21.9.
- **21.12 Config, recipes, analysis, docs + lints + owner list**: per `kaudit_config.md` (+ companion rows), KD-2
  generator, marker lint (KD-8), contact-check doc vs code (`kaudit_instrument` item 1).
- Order: 21.5 → 21.13 → 21.6 → 21.7 → 21.10 → 21.11 → 21.12 → 21.9. Audit line numbers are at `d839847`; match by
  the quoted text, not the line.
- 21.9 acceptance: S17 ★, S7, plus every scenario whose read text changed in a way that plausibly changes graded
  behaviour (list them with the reason; cards' expected-value tables and recommended ranges count; citations and
  wording-only changes do not). Budget is reported to the owner before the runs.
