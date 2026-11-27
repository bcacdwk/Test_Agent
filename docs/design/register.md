# Design register

Every plan id that code, tests, skills and docs cite resolves here: one row per id with a one-line statement condensed
from its source, its status today and where it is defined. Owner decisions still waiting are the rows with status
`open`; the facts only the owner knows (device, film, station, lab practice) are listed in
[../open-questions.md](../open-questions.md). `tests/adapters/test_design_register.py` keeps the register complete:
every `OD-`, `OD21-`, `OD30-`, `KD-`, `D-n`, `D30-` and `ATV-` id cited in a tracked file outside `docs/design/` has a
row, every id a committed plan defines has a row, and no tracked file outside `docs/design/` points into the
gitignored maintainer scratch under `tmp/`.

Status: **open** (undecided or unverified) · **resolved** (decided; or verified, or its fallback applied; the cell
says which and where) · **settled at** `<steps>` (hardware-bound: the simulator side and the fallback are built, the
named bring-up steps of [`steps.yaml`](../../.agents/skills/b1500-bringup/steps.yaml) settle it on the instrument, so
it stays open until then; `D<n>` = deployment step, `S0`/`L<n>` = stage, `L<n>.A<k>`/`.P<k>` = step) · **dropped**.

## Namespaces

| Plan | Ids | Defined in |
|---|---|---|
| v1 (2026-11-17, M0–M4) | owner decisions `D1`–`D3`; assumptions to verify `ATV-1`…`ATV-12` | v1 plan: `git show plan-v1:docs/design/blueprint.md` (tag `plan-v1`), §10 and §9.7 |
| v2 (2026-11-18, M5–M12) | owner decisions `OD-1`…`OD-7`; `ATV-13`…`ATV-32` (v1 ATV ids kept) | [blueprint.md](blueprint.md) §12, §11 |
| v2.1 (2026-11-26) | owner decisions `OD21-1`…`OD21-11`; decisions `D-1`…`D-11` and `KD-1`…`KD-8`; `ATV-33`…`ATV-40` | [plan-v2.1.md](plan-v2.1.md) §9, §10, §12, §8 |
| v3 (2026-11-27) | owner decisions `OD30-n`; decisions `D30-n`; work packages `WP30.n` | [plan-v3.md](plan-v3.md) §8, §9, §4 |

Same-looking ids that are not plan ids: the deployment steps `D1`–`D12` and the bring-up steps (`S0.P7`, `L0.A2`, …)
in `steps.yaml` (in v1-era text "owner decision D1–D3" means the v1 decisions, everywhere else `D<n>` is a deployment
step); rule ids `R-…` (`src/b1500_test_agent/rules/`); acceptance scenarios `S1`–`S18`
(`tests/acceptance/scenarios/`); qualify tiers `T0`–`T3` ([plan-v2.1.md](plan-v2.1.md) §2.3); "§7.6 item n"
(hardware facts, [blueprint.md](blueprint.md) §7.6); "decision n" in v1/v2-era text (row n of that plan's §0 decision
table); milestones `M0`–`M12` ([../roadmap.md](../roadmap.md)); finding ids `A:…`, `B:…`, `C:…` and repro ids `r…`
(local to [plan-v3.md](plan-v3.md) §1).

## Code-comment legend

Comments, docstrings and older docs carry provenance tags; they are not swept (plan-v3 D30-5). How to resolve them:

| Tag | Where it points |
|---|---|
| `WPn.m` | the row of that work package in [progress.md](progress.md) (v1, v2, v2.1) or [progress-v3.md](progress-v3.md) (`WP30.n`); its commit subject starts with `WPn.m` |
| `blueprint v2 §x`, `blueprint v2 x.y` | [blueprint.md](blueprint.md) §x |
| `blueprint §x` without a version | the v1 plan (`git show plan-v1:docs/design/blueprint.md`) in v1-era files; in v2-era files it is ambiguous: check both |
| `v2.1 plan §x` | [plan-v2.1.md](plan-v2.1.md) §x |
| an id of the tables below | its row here |

New code and current docs carry no WP or plan-section tags (plan-v3 §2 principle 5); history stays in `docs/design/`.

## v1 (plan v1, owner decisions 2026-11-17)

| Id | Statement | Status | Defined in |
|---|---|---|---|
| D1 | Repo-relative everything: `.venv/`, `data/{runs,state}/`, `config/local/`, `work/` in the clone, gitignored; only `*.example.yaml` committed | resolved (owner, 2026-11-17) | plan-v1 §10 |
| D2 | Simple lab PC: the runtime runs from its `git clone`, no admin install; managed harness config only an optional hardening note | resolved (owner, 2026-11-17) | plan-v1 §10 |
| D3 | Harness tool confirmation only (`run_confirmed_plan`); bypass-mode self-approval, own-code paths and config edits are accepted residual risks | resolved (owner, 2026-11-17) | plan-v1 §10 |
| ATV-1 | `LOP?` reports the per-channel output state, usable for cleanup verification | settled at L1.A4 — per the manual on the simulator (WP1.2); verify path spy-tested (WP1.6); positive control built (WP6.2) | plan-v1 §9.7 |
| ATV-2 | GPIB address 17; write `\n`, read `\n`/EOI | settled at L0.P1, L0.A2, L0.A3, L0.P4 — settings fields (WP1.1); the lab's code uses address 17 | plan-v1 §9.7 |
| ATV-3 | EasyEXPERT must be stopped or released for external FLEX control | settled at S0.P7, L3.P3, L4.P3 — confirmed by the manuals (WP4.1, blueprint v2 §11) | plan-v1 §9.7 |
| ATV-4 | Codex MCP servers run outside the Windows sandbox and can open VISA | settled at L0.A6, L0.P4, L1.P4, L10.P3 | plan-v1 §9.7 |
| ATV-5 | Claude `-p` treats `ask`-rule tools as denied unless allowed; stream-json schema for MCP; `codex exec` loads the trusted project's `.codex/` layers | resolved — fallback: the runner answers the prompt (WP3.1); held on codex-cli 0.170.0 and Claude Code 2.1.328 (WP11.5) | plan-v1 §9.7 |
| ATV-6 | Codex per-tool `approval_mode = "prompt"` asks for `run_confirmed_plan`, `approve` tools do not; the exec override lets the call through | resolved — exec part holds (WP3.1, WP3.3); interactive prompt not checkable headless, fallback in force (S4 graded from the call arguments) | plan-v1 §9.7 |
| ATV-7 | Claude `ask` on `run_confirmed_plan` prompts in default, `acceptEdits` and `auto` modes; `allow` on the other nine tools does not | settled at D11, L4.P4, L10.P3 — headless evidence passes (WP3.3); `requiresUserInteraction` stays on | plan-v1 §9.7 |
| ATV-8 | Claude `PreToolUse` hooks also run in `bypassPermissions` mode | settled at D11, L10.P3 — not verified; accepted residual (D3), the deny rules hold | plan-v1 §9.7 |
| ATV-9 | Codex rules (experimental) keep their semantics across versions | resolved — `codex execpolicy check` forbids the human-only commands (WP3.3); re-checked per version by `update` and qualify T0 | plan-v1 §9.7 |
| ATV-10 | STB bit 3 tracks the interlock state continuously | settled at L0.A2 — the manual describes a latched event; fallback applied: R-IL-01 = STB bit 3 + `ERRX?` 202/203 (WP1.4, WP11.1) | plan-v1 §9.7 |
| ATV-11 | Both harnesses' confirmation prompts show the MCP tool arguments (the `summary`) to the human | settled at D11, L4.P4, L10.P3 — fallback in force: the agent prints the summary verbatim before it stops (S4) | plan-v1 §9.7 |
| ATV-12 | FastMCP emits tool `_meta` in `tools/list`; Claude `-p` denies a flagged tool even with `--allowedTools` | resolved — both hold (WP1.8, WP3.1): the flag is on by default and off in the runner's config | plan-v1 §9.7 |

## v2 (blueprint, 2026-11-18)

| Id | Statement | Status | Defined in |
|---|---|---|---|
| OD-1 | Commit the manual page text (~0.65 MB gz) to the repository; PDFs never | resolved — yes (owner, 2026-11-18): corpus under `references/manuals/corpus/` | blueprint.md §12 |
| OD-2 | Lab facts, not blockers: 16440A wiring, SCUU/ASU presence, slots 8–10, B1511A or B, WGFMU library version, the bring-up DUT set | settled at L0, L7 — example config holds the lab-code evidence as `certainty: unverified`; `bringup propose-station` + the human's adoption | blueprint.md §12 |
| OD-3 | Limits sign-off: pulse and CMU soft limits, correction age, async confirm/block thresholds, destructive recipes on visa with `destructive` confirmation | resolved — accepted as listed (owner, 2026-11-18) | blueprint.md §12 |
| OD-4 | The executor may push `rearch/v2` (never `main`, never tags) for Windows CI evidence; `gh` on the Mac | resolved — yes (owner, 2026-11-18) | blueprint.md §12 |
| OD-5 | Harness permission change set: deny/forbid `config init` and `config adopt`; allow the read-only `manual` and `bringup status`, `propose-station`, `capture`, `record` commands | resolved — yes (owner, 2026-11-18); applied once by the orchestrator at WP6.1 | blueprint.md §12 |
| OD-6 | Running an external SPICE simulator (HSPICE licence or ngspice install) | resolved — default: not in v2; `export_spice_netlist` writes the files, `model_compare` evaluates in Python (WP7.7) | blueprint.md §12 |
| OD-7 | Transfer of validation records and fixtures from the lab PC | resolved — default: branch `lab/bringup-<date>` pushed, else a OneDrive copy (`deployment-windows.md`, step "Transfer (OD-7)") | blueprint.md §12 |
| ATV-13 | Per-transaction VISA open/close over GPIB is fast (< 100 ms) and stable | settled at L0.P4, L1.A4, L1.P4 — visa loop: median 0.93 ms per transaction (WP5.5) | blueprint.md §11 |
| ATV-14 | Releasing the pyvisa exclusive lock lets the WGFMU library's own session work; the relock is clean | settled at L8.A2, L8.A10 — visa-loop pass (WP10.3, WP11.3) | blueprint.md §11 |
| ATV-15 | The lab PC has WGFMU library ≥ A.03.00 whose x64 DLL loads via `ctypes.WinDLL`; signatures match the API extract | settled at D3, D12, L0.A2, L0.A7 — fake ABI passes (WP10.2) | blueprint.md §11 |
| ATV-16 | Opening a WGFMU session, reading the channel ids and closing it change no output (probe-safe) | settled at L0.A2, L8.A1 — simulator and visa loop pass (WP10.2) | blueprint.md §11 |
| ATV-17 | The library's initialize resets the WGFMU only (an SMU bias survives it) | settled at L8.A7 — simulator pass (WP10.3, WP10.7) | blueprint.md §11 |
| ATV-18 | `*RST` and power-on leave ERSSP all open and need `ERMOD 1` before `ERSSP` | settled at L7.A2, L7.A11 — designed around: `ERMOD 1` before every route, `ERSSP?` verify (WP9.2) | blueprint.md §11 |
| ATV-19 | `SPST?` = 1 while running, 0 after count or duration | settled at L7.A4, L7.A13 — simulator per the manual; fallback built (`SPP`, cleanup verify; WP9.1, WP9.3) | blueprint.md §11 |
| ATV-20 | SER auto-levelling delivers the set V into the declared load (≈ 2× into an open load at 50 Ω) | settled at L7.A4 — R-SPGU-01 and the guard keep the 2× worst case (WP5.4, WP9.1) | blueprint.md §11 |
| ATV-21 | CMU corrections persist until `*RST` or power-off; `CORRST?` reflects them | settled at L6.A2, L7.A12, L9.A12 — manual semantics simulated; live `CORRST?`/`ADJ?` check before every capacitance run (WP8.1, WP8.2) | blueprint.md §11 |
| ATV-22 | CMU `FMT 1` blocks and `TSC` timestamps parse with the v2 parser (the lab used FMT 21) | settled at L5.A3, L5.A8, L5.A9, L6.A8, L9.A11 — parser and simulator cross-checked; flagged `time_source` fallback (WP7.4, WP8.1, WP8.4) | blueprint.md §11 |
| ATV-23 | Idle WGFMU, SPGU and CMU slots read `00` in `LOP?` | settled at L1.A4 — positive control visa-loop tested (WP6.2) | blueprint.md §11 |
| ATV-24 | FastMCP stdio serves tool calls while a worker thread runs | resolved — holds (WP5.6, `dev mcp-smoke --async`); the detached-worker fallback is not needed | blueprint.md §11 |
| ATV-25 | Codex `workspace-write` runs the `manual` and `bringup` commands without prompts; Claude Code does with the OD-5 allow rules | settled at L10.P3 — passed on the Mac (WP6.6; Codex with `UV_CACHE_DIR` in a writable folder); the lab PC's sandbox at L10 | blueprint.md §11 |
| ATV-26 | GitHub Actions `windows-latest` passes | resolved — passed (WP6.5, WP11.4); CI runs on both OS | blueprint.md §11 |
| ATV-27 | An SCUU `SSP` to the CMU resets the SMU | settled at L6 — confirmed by the manual text and simulated (WP8.1); checked on hardware only if an SCUU is present | blueprint.md §11 |
| ATV-28 | The human can record the 16440A input/output wiring at L7 | settled at L0.P2, L4.A4, L6.A6, L7.A3, L7.P2, L7.P4 — fallback built: null selector inputs stay blocked on visa (R-PIN-01) | blueprint.md §11 |
| ATV-29 | The three skill descriptions fit Codex's 2 % listing and Claude's 1,536-character cap | resolved — pass: both harnesses list all three untruncated (WP5.10) | blueprint.md §11 |
| ATV-30 | MM 10 data can be read in blocks while the instrument samples | settled at L5.A3 — fallback by design: progress per MM 10 block (WP7.4) | blueprint.md §11 |
| ATV-31 | Line frequency 50 Hz | settled at L6.A6 — policy `line_hz` (WP8.5); stage L0 compares it with the S0 reading | blueprint.md §11 |
| ATV-32 | The RSU SMU mode passes the SMU path (combined SMU + WGFMU recipes) | settled at L8.P1, L8.A4, L9.P6, L9.A9 — simulator pass (WP10.7); fallback: separate SMU wiring | blueprint.md §11 |

## v2.1 (plan v2.1, 2026-11-26)

| Id | Statement | Status | Defined in |
|---|---|---|---|
| OD21-1 | Harness upgrades redesigned: operator `uv run b1500 update` installs the versions in `validated.yaml`; maintainer `uv run b1500 dev harness qualify` bumps it | resolved (owner, 2026-11-26) | plan-v2.1.md §9 |
| OD21-2 | Harness auto-update held on the lab PC (Claude Code updater off, npm Codex does not update itself); stable channel on the Mac | resolved (owner, 2026-11-26) | plan-v2.1.md §9 |
| OD21-3 | On the lab PC only `dev harness qualify --windows` (T0 + T1 + S16), at deployment and once per bump | resolved — (a) (owner, 2026-11-26) | plan-v2.1.md §9 |
| OD21-4 | Strict stop at the first login, API or network event, reconnect notices included | resolved — (a) (owner, 2026-11-26); the Codex model-refresh notice is a note (§11) | plan-v2.1.md §9 |
| OD21-5 | No `.claude/settings.json` change for built-in tools; `Monitor` and the other unguarded built-ins are an owner-accepted residual | resolved — (c) (owner, 2026-11-26); WP21.3 dropped | plan-v2.1.md §9 |
| OD21-6 | Verbs `bringup next`, `done`, `check` plus three Claude Code allow lines, applied once by the orchestrator | resolved — (a) (owner, 2026-11-26); applied at WP21.5 | plan-v2.1.md §9 |
| OD21-7 | The agent records the owner's own chat words; the owner signs the stage record | resolved — (a) (owner, 2026-11-26) | plan-v2.1.md §9 |
| OD21-8 | The nine owner bring-up sessions as planned | resolved (owner, 2026-11-26) | plan-v2.1.md §9 |
| OD21-9 | Targeted acceptance for v2.1 | resolved — (a) (owner, 2026-11-26) | plan-v2.1.md §9 |
| OD21-10 | Not blocking: the debug cases' owner questions, the deck's remaining debug entries, the B1530A Fast-IV short-circuit current, the MFCMU DC current limit | open — the case questions are in `docs/open-questions.md`; stage L6 cites the MFCMU limit | plan-v2.1.md §9 |
| OD21-11 | When to push `main` (every push is a release: `update` pulls `origin/main`) | resolved — pushed after every WP for Windows CI while no lab clone exists (v2.1 practice; v3: OD30-2) | plan-v2.1.md §9 |
| D-1 | No new branch: WPs run sequentially in the main checkout on `main`, one commit per WP; acceptance from that checkout with a clean `git status` | resolved (owner, 2026-11-26) | plan-v2.1.md §10 |
| D-2 | Operator command `uv run b1500 update` (top level, human-run); maintainer command `uv run b1500 dev harness qualify` (dev group) | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-3 | `config/harness/validated.yaml` is the committed truth of harness versions; machine-local state only for the Windows qualification note and the bring-up ledger | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-4 | One `steps.yaml` for the whole bring-up sequence; stage files keep the prose and their 150-line budget | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-5 | Marker syntax `TODO(verify)[<step ids>]` for hardware facts, `TODO(cite)` for literature values; the lint enforces both | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-6 | Debug cases keep the lab facts apart from the simulator reproduction (own section, run ids labelled SIMULATED); the test is the authority | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-7 | The guard hook blocks agent writes that set `status: reviewed` in a debug case (tightening, no settings change) | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-8 | All live harness sessions happen once, in WP21.9, after every text change | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-9 | Transcript pins for qualified versions come from `qualify --pin`; the 0.167.1/2.1.326 pins stay as regression fixtures | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-10 | `acceptance run` uses the infra watcher by default (`--no-infra-stop` only for offline tests) | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| D-11 | One install method per harness on both OS: Claude Code native build (`claude install <version>`), Codex from npm (`@openai/codex@<version>`) | resolved (plan, 2026-11-26) | plan-v2.1.md §10 |
| KD-1 | Blank markers: `TODO(owner)` (a fact only the owner knows), `TODO(verify)[<step ids>]` (a hardware step gives it), `TODO(cite)` (needs a checked source) | resolved (orchestrator, 2026-11-26; WP21.10–21.12) | plan-v2.1.md §12 |
| KD-2 | One owner question list, `docs/open-questions.md`, generated by `gen-index` from every `TODO(owner)` marker and the debug cases' open questions | resolved (orchestrator, 2026-11-26; WP21.12) | plan-v2.1.md §12 |
| KD-3 | A value marked `TODO(owner)`, `TODO(verify)`, `TODO(cite)` or "unknown" is blank: the agent says so, asks or names the bring-up step, never fills it | resolved (orchestrator, 2026-11-26; WP21.10–21.12) | plan-v2.1.md §12 |
| KD-4 | Simulator values appear in text only labelled "simulator example (scenario X), not a real-device value"; "lab" profiles carry none | resolved (orchestrator, 2026-11-26; WP21.10–21.12) | plan-v2.1.md §12 |
| KD-5 | Debug cases reframed as examples: `origin: illustrative` or `observed`, `example-*` ids, open questions cut to the genuine unknowns | resolved (orchestrator, 2026-11-26; WP21.11) | plan-v2.1.md §12 |
| KD-6 | Audit X rows: wrong physics and contradictions corrected with a source or deleted; a wrong value in code fixed with a test (tightening only) | resolved (orchestrator, 2026-11-26; WP21.10–21.12) | plan-v2.1.md §12 |
| KD-7 | Audit K rows: functional defaults stay, worded as example defaults; provisional bring-up criteria marked and listed for the owner | resolved (orchestrator, 2026-11-26; WP21.10–21.12) | plan-v2.1.md §12 |
| KD-8 | The `TODO(verify)` hygiene of WP21.8 is absorbed into WP21.10–21.12; its lint lands in WP21.12 | resolved (orchestrator, 2026-11-26) | plan-v2.1.md §12 |
| ATV-33 | The runner launches `claude.exe` and the npm `codex.cmd` shim from Python on native Windows; prompts on stdin; `taskkill /T` ends the tree | settled at D10 — injection tests pass (WP21.2) | plan-v2.1.md §8 |
| ATV-34 | `claude doctor` names a malformed or dropped entry of the project `.claude/settings.json` without starting a session | resolved — holds (WP21.1, Claude Code 2.1.328) | plan-v2.1.md §8 |
| ATV-35 | (dropped with WP21.3; the final plan states no assumption) | dropped | plan-v2.1.md §8 |
| ATV-36 | Infra-error shapes can be pinned without spending (logged-out runs; retry and rate-limit shapes) | resolved — holds; pinned in `tests/fixtures/transcripts/infra/` (WP21.2) | plan-v2.1.md §8 |
| ATV-37 | `igzo_transient` drifts across back-to-back `mosfet.idvg` runs | resolved — failed; fallback scenario `igzo_drift_repeat` applied (WP21.4) | plan-v2.1.md §8 |
| ATV-38 | Codex passes the harness process environment (`B1500_CONFIG_DIR`, `B1500_DATA_DIR`) to its shell commands on Windows as on macOS | settled at D10 — the qualify T1 smoke probe's shell step checks it | plan-v2.1.md §8 |
| ATV-39 | `claude install <version>` and `npm install -g @openai/codex@<version>` install exactly that version, also a lower one, on macOS and Windows | settled at D4, D10 — fakes pass (WP21.1) | plan-v2.1.md §8 |
| ATV-40 | Codex sets a recognisable variable in its shells on Windows (`CODEX_SANDBOX*` on macOS) | settled at D10 — the interactive-terminal requirement is the independent second condition | plan-v2.1.md §8 |

## v3 (plan v3, 2026-11-27)

| Id | Statement | Status | Defined in |
|---|---|---|---|
| OD30-1 | Live acceptance for v3 | resolved — (a) with S15 ★ × 3 on both harnesses (owner, 2026-11-27): free checks, S1 × 1 and S15 ★ × 3 on both, in WP30.20 | plan-v3.md §8 |
| OD30-2 | When to push `main` | resolved — (c) after every WP (owner, 2026-11-27); once a lab clone exists, only at phase ends | plan-v3.md §8 |
| OD30-3 | Where analysis applicability lives | resolved — (b) the registry keeps the recipe lists, a documented one-line edit per new recipe; no WP30.10a (owner, 2026-11-27) | plan-v3.md §8 |
| D30-1 | Sequential WPs in the main checkout on `main`, one commit per WP; compact rows in `progress-v3.md`; `progress.md` frozen | resolved (plan, 2026-11-27) | plan-v3.md §9 |
| D30-2 | v3 ids `WP30.n`, `OD30-n`, `D30-n`; the plan committed as `docs/design/plan-v3.md` in WP30.1 | resolved (plan, 2026-11-27); done in WP30.1 | plan-v3.md §9 |
| D30-3 | History stays in `docs/design/`; the roadmap's result tables move to `design/history.md` | resolved (plan, 2026-11-27); WP30.18 | plan-v3.md §9 |
| D30-4 | Commit the v2.1 plan verbatim as `design/plan-v2.1.md`, plus this register and its id test | resolved (plan, 2026-11-27); done in WP30.1 | plan-v3.md §9 |
| D30-5 | Code-comment provenance: a legend and a convention, no sweep | resolved (plan, 2026-11-27); legend above | plan-v3.md §9 |
| D30-6 | The operator path moves to package `deploy/` | resolved (plan, 2026-11-27); WP30.14 | plan-v3.md §9 |
| D30-7 | A `bringup/` package; its ledger lock uses `filelock` | resolved (plan, 2026-11-27); WP30.14 | plan-v3.md §9 |
| D30-8 | Card status = the lowest status of its recipes, lint-checked | resolved (plan, 2026-11-27); WP30.10 | plan-v3.md §9 |
| D30-9 | Driver-map builder and its test retired; `flex-driver-map.yaml` kept frozen with its README | resolved (plan, 2026-11-27); WP30.12 | plan-v3.md §9 |
| D30-10 | Recipe digest over the parsed YAML mapping minus `DEFINITION_EXCLUDED`, before M12 | resolved (plan, 2026-11-27); WP30.9 | plan-v3.md §9 |
| D30-11 | `max_limited_fraction_in_fit` honoured by every window fit; knowledge text unchanged | resolved (plan, 2026-11-27); WP30.15 | plan-v3.md §9 |
| D30-12 | One gate command that CI runs; `regen` for generated files; `--quick` for iteration | resolved (plan, 2026-11-27); WP30.16 | plan-v3.md §9 |
| D30-13 | A minimal harness profile table and a "Supporting a coding harness" section; no third harness now | resolved (plan, 2026-11-27); WP30.16, WP30.19 | plan-v3.md §9 |
| D30-14 | Firmware and WGFMU-library drift: a documented upkeep procedure, no code check yet | resolved (plan, 2026-11-27); WP30.19 | plan-v3.md §9 |
| D30-15 | `docs/operator.md` in English, moved from the deployment doc, not copied | resolved (plan, 2026-11-27); WP30.19 | plan-v3.md §9 |
| D30-16 | Old acceptance reports stay where they are | resolved (plan, 2026-11-27) | plan-v3.md §9 |
| D30-17 | Annotated tags `v2`, `v2.1`, `v3` and version 3.0.0 at the v3 close | resolved (plan, 2026-11-27); WP30.20 | plan-v3.md §9 |
| D30-18 | Agent-read text (AGENTS.md, knowledge index, two runbook `sources:`) edited once, in WP30.20; CLAUDE.md, entry SKILL.md, cards, stages, `steps.yaml` unchanged | resolved (plan, 2026-11-27); WP30.20 | plan-v3.md §9 |
| D30-19 | `--affected`: a per-scenario base, the card index out of `touches`, a dead-glob test; no docstring-blind diff | resolved (plan, 2026-11-27); WP30.11 | plan-v3.md §9 |
| D30-20 | The lab clone stays at `C:\b1500\test_agent`; `doctor` WARNs inside a synced folder | resolved (plan, 2026-11-27); WP30.2 | plan-v3.md §9 |
| D30-21 | `.python-version` = 3.12; `doctor` reads the Python bounds from `pyproject.toml` | resolved (plan, 2026-11-27); WP30.16 | plan-v3.md §9 |
| D30-22 | Housekeeping: delete the untracked, git-ignored `build/` and `src/b1500_test_agent.egg-info` (never `git clean -X`) | resolved — done by the orchestrator before WP30.1 | plan-v3.md §9 |
