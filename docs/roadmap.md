# Roadmap

Milestones of the re-architecture. v1 (M0–M4, plan tag `plan-v1`) was built on branch `rearch/v1` and merged into
`main`; v2 (M5–M12, [blueprint](design/blueprint.md) §10) was built on branch `rearch/v2`, one commit per work package
(WP), and fast-forwarded into `main`; v2.1 (section below) was built on `main` directly. The log with acceptance
results and handoff notes is [`docs/design/progress.md`](design/progress.md), which is the source of truth for status.
This page is updated at milestone boundaries.

| Milestone | Goal | Status |
|---|---|---|
| M0 Re-baseline | Plan promoted, legacy archived and pruned, tooling, docs | **done** (2026-11-17) |
| M1 Runnable skeleton | One vertical path on the simulator: status → validate → staircase Id-Vg → archive → Vth | **done** (2026-11-18) |
| M2 Skill system | Six SMU test cards with recipes that run on the simulator; knowledge files; debug skill | **done** (2026-11-18) |
| M3 Harness acceptance | Ten scenarios on Codex and Claude Code against the simulator | **done** (2026-11-18; [reports](acceptance/)) |
| M4 Hardware bring-up | Checklists for the Windows lab PC and staged hardware validation | **done as documents** (2026-11-18); v2 turned them into the bring-up stage files, executed in M12 |
| M5 Foundations | v2 plan, package split, models/config v2, guard + rules v2, per-transaction VISA + visa-loop, async runs, archive v2, manual corpus, device models v2, skills v2 structure | **done** (2026-11-18) |
| M6 Lab-ready core | Read-only probe, station proposal and config adoption, visa completeness, bring-up skill, hardware suite, Windows readiness, acceptance v2 | **done** (2026-11-19) |
| M7 SMU complete | Spot/Kelvin/ASU, sweeps v2, pulsed, sampling + TDDB, search + BDV, stress-measure, compact models | **done** (2026-11-24) |
| M8 MFCMU, SCUU, GNDU | CMU driver + simulator, corrections, C-V core and variants, QSCV, Dit, GNDU budget | **done** (2026-11-25) |
| M9 HV-SPGU + 16440A | SPGU driver + simulator, selector routes, pulse kind, program/read, kinetics, endurance, retention | **done** (2026-11-25) |
| M10 WGFMU | Library protocol + simulator, DLL binding, driver + phase, waveform kind, noise, FeCap PUND, fast BTI | **done** (2026-11-26) |
| M11 Integration and closure | Async/debug completeness, coverage ledger closure, full safety + visa-loop, docs and plug-in-and-go closure, final acceptance S1–S18 | **done** (2026-11-26; S1–S18 PASS on both harnesses, [reports](acceptance/)) |
| M12 Hardware session | Owner at the lab PC: staged bring-up S0–L10, validation records, then per-module developer WPs | owner (outside the v2 goal; section M12 below) |
| v2.1 Update, debug cases, step-by-step bring-up | Operator `update` and maintainer `qualify`, infra stop, debug cases with simulator reproductions, the bring-up step sequence and ledger, knowledge provenance, RSU input limit | **done** (2026-11-27; acceptance: Codex 6/6, Claude Code 5/6 with S17 an owner-accepted headless limitation; section v2.1 below) |

## M0 — Re-baseline (done)

| WP | Result |
|---|---|
| 0.1 Promote plan | `docs/design/blueprint.md` is the plan of record |
| 0.2 Archive tag | Annotated tag `archive/v0.2-fake-mcp` on `6bc9f3e` keeps the 379-tool v0.2 design (local; the owner pushes it) |
| 0.3 Tooling | uv project and lock, `b1500` CLI skeleton, tool-schema token counter, legacy baseline (104,691 tokens) |
| 0.4 Driver map | Legacy atom/flow taxonomy mapped onto the planned `B1500Driver` in `references/driver-map/` |
| 0.5 Prune + salvage | Legacy fake MCP surface, schemas, mock and skills removed; parser moved to `driver/`; models salvaged |
| 0.6 Docs | README, `AGENTS.md`/`CLAUDE.md` (root and nested), architecture, safety model, roadmap, migration |

## M1 — Runnable skeleton (simulator, one vertical path; done)

Order: 1.1 → (1.2 ∥ 1.3 ∥ 1.4 ∥ 1.5) → 1.6 → 1.7 → 1.8 → 1.9. Result: `b1500 plan mosfet.idvg …` → `run` →
`analyze … vth_linear_extrapolation` gives Vth within ±100 mV of the simulated device on the simulator, through the
CLI or the 10-tool MCP server (1,474 schema tokens, down from 104,691 for the 379 v0.2 tools); both harness configs
start the same server (`b1500 dev mcp-smoke`).

| WP | Result |
|---|---|
| 1.1 Models + config | Shared models, config resolution, repo-relative paths, migrated example configs, sim scenario `nmos_basic` |
| 1.2 Transport + simulator core | Transport protocol, audit, VISA transport, in-process FLEX simulator with first device models and faults |
| 1.3 Driver | FLEX builders with manual page citations, `B1500Driver`, `OutputGuard`, FMT 1/5 parser, discovery, module specs |
| 1.4 Rules + tiers | All v1 rules, hard-limit code ceiling, tiers, canonical plan summary; completes [safety-model.md](safety-model.md) |
| 1.5 Analysis core | Run loading, quality classification, `gm`, Vth by linear extrapolation |
| 1.6 Session + transaction | Instrument lock, transaction with verified cleanup, fault latch, recovery; full fault matrix |
| 1.7 Catalog + executor + archive | Recipe registry (`mosfet.idvg`, `generic.smu_staircase`, `system.*`, reserved), executor, run archive |
| 1.8 Service + adapters | `B1500Service`, 10-tool MCP server, operator CLI, `doctor`, token budget after-value |
| 1.9 Harness wiring | `b1500 harness init` (templates in `config/harness/`), Codex rules, `.claude/settings.json` + guard hook, `b1500 dev mcp-smoke`, placeholder skill, CI workflow (macOS + Windows) |

## M2 — Skill system and recipe pack (done)

Order: (2.1 → 2.2) ∥ 2.3 → 2.4 → (2.5 ∥ 2.6 ∥ 2.7). Result: six SMU recipes are simulator-validated against model
truth, each with a test card whose example plan `b1500 dev lint-skills` validates on its simulator scenario; the
entry skill `b1500-test` (card index, tiers, report template), seven knowledge files and the `b1500-debug` skill
(eight runbooks) are canonical in `.agents/skills/` and copied to `.claude/skills/` by `b1500 dev sync-harness`.

| WP | Result |
|---|---|
| 2.1 Sim models + kinds | Diode, FeFET and damaged-device models; double sweep; stepped sweep kind; more scenarios |
| 2.2 Recipes + analysis | Five more recipes and the remaining extraction methods, each validated against model truth |
| 2.3 Skill tooling | `b1500 dev sync-harness` (Claude Code copy + drift check), `b1500 dev lint-skills` |
| 2.4 Entry skill | `b1500-test` skill, card template, final `AGENTS.md`/`CLAUDE.md`, generated `.claude/skills/` |
| 2.5 Six cards | Contact/resistor check, diode I-V, MOSFET Id-Vg, MOSFET Id-Vd, gate leakage, FeFET dual-sweep memory window, each with a simulator validation record; reserved slots with their preconditions |
| 2.6 Knowledge 01–07 | Device physics, instrument, wiring, ferroelectrics/oxides, reliability, extraction, HSPICE (reserved; v2 WP7.7: compact models) |
| 2.7 Debug skill | `b1500-debug` with eight runbooks and three illustrative cases from the owner's deck (not lab history; v2.1: `example-*`) |

## M3 — Harness acceptance (done)

Scenario framework (isolated config and data dirs, human emulation, graders), scenarios S1–S10 (Vth measurement,
over-limit refusal, reserved pulse request, confirmation flow, consent forgery and config edit, raw-command request,
noisy data, unknown pins, injected instructions in notes, FeFET memory window), then baseline runs and skill-text
iteration until safety scenarios pass 3/3 and functional scenarios pass on both Codex and Claude Code.

## M4 — Hardware bring-up (checklists)

- [`docs/hardware-bringup.md`](hardware-bringup.md) (written, WP4.1): staged bring-up with sign-off lines: physical
  checks, read-only probing, 0 V open circuit, known resistors, known diode, known-good MOSFET compared with
  EasyEXPERT; recipes are promoted to `hw_validated` only with a validation record. Since WP6.3 a one-page
  overview: the stage files of skill `b1500-bringup` hold the procedure.
- [`docs/deployment-windows.md`](deployment-windows.md) (written, WP4.2; v2 by WP6.5 with the first-session script, the WGFMU library, manuals and an offline wheelhouse): lab PC setup (Python + uv, VISA + GPIB
  adapter, `git clone`, `uv sync --frozen`, `config/local/`, `b1500 doctor --probe`, `b1500 harness init`),
  residual risks in plain words, facts to collect.

## v2 (M5–M12)

v2 keeps v1's kernel shape (recipe → kind → guarded driver → transaction with verified cleanup → archive →
analysis, behind the same 10 MCP tools) and fills it to the whole station: SMU, MFCMU (+SCUU), HV-SPGU with two
16440A selectors, WGFMU (+RSU) and GNDU, each implemented, simulated, tested, carded and given a bring-up stage
(68 recipes, 14 kinds, 34 cards: WP10.6 split one FeCap card in two). Order: M5 → M6 → (M7 ∥ M8 ∥ M9 ∥ WGFMU 10.1–10.5) → (10.6 ∥ 10.7) → 10.8 → M11;
M12 is the owner's hardware session. Only the hardware-bound items of blueprint §7.6 wait for M12.

## M5 — Foundations (done)

Order: 5.1 → 5.2 → 5.3 → (5.4 ∥ 5.5 ∥ 5.7) → 5.6; 5.8 ∥ 5.9 from 5.2; 5.10 after 5.8. Result: no behaviour change
for the v1 recipes (golden FLEX previews and `data.csv` byte-identical) on a lab-shaped configuration; the kernel
now carries the v2 concepts (switches and routes, pulse/AC/waveform envelopes, async runs, correction store), opens
the bus per transaction (CLI and MCP server coexist), runs every v1 measurement recipe through the real
`VisaTransport` against the simulator (visa-loop), searches the 2,315 manual pages offline and routes three skills.
Gate at the end of M5: 3,157 tests (`-n auto`), 10 MCP tools / 1,584 schema tokens, always-loaded text
1,705 / 2,500 tokens.

| WP | Result |
|---|---|
| 5.1 Promote plan | `docs/design/blueprint.md` = v2 plan of record; tag `plan-v1`; progress v2 section; roadmap M5–M12 |
| 5.2 Package split | `driver/flex/` + `driver/ops/`, simulator units, `sim/devices/`, `rules/builtin/`, `adapters/cli/`, skill lint split; FLEX/`*RST`/file-size lints; golden previews of the 9 v1 recipes; `pytest-xdist` |
| 5.3 Models + config v2 | Switches and routes, pin-map switch targets, DUT impedance/pulse/AC/geometry, policy v2, `file` params, lab-shaped station example (`certainty: unverified`), migrated pin maps and scenarios |
| 5.4 Guard + rules v2 | `OutputGuard` pulse/AC/route/waveform checks, the rules of blueprint §2.8 on synthetic plans, new confirm reasons, plan summary v2, SER arithmetic |
| 5.5 Bus lifecycle + visa-loop | Per-transaction VISA (open → lock → … → unlock → close), `make_bus`, injectable resource manager, `tests/visa_loop/` with every v1 measurement recipe, `+0,` ERRX parsing, `bus_locked` fault |
| 5.6 Async runs | `run_plan` returns `running` for long plans; progress via `get_run`, cancel via `safe_shutdown` from any process, MCP shutdown hook, auto-calibration off during async runs and restored |
| 5.7 Archive + data contract | npz above 200k rows + `preview.csv`, manifest coverage of new files, CMU correction store, family tags in the analysis registry |
| 5.8 Manual corpus | `b1500 manual search`, `page`, `toc`, `status`, `build`: 16 documents, 2,315 pages, BM25 with CJK bigrams, committed corpus |
| 5.9 Device models v2 | MOS-C, fixture/capacitor, dielectric/TDDB, FeFET kinetics and FeCap, noise/RTN, MOSFET self-heating/BTI/HCI/C-V, IGZO transient, each against its §4.2 fidelity target |
| 5.10 Skills v2 structure | Cards in family folders with a generated index, `b1500-bringup` skeleton, lint v2, three skills mirrored for Claude Code; acceptance S1, S4, S5 on both harnesses |

## M6 — Lab-ready core (done)

Result: plug-in-and-go for the v1 scope. A read-only probe and a station proposal from the live inventory, the
human-only configuration bootstrap, every v1 recipe and the `system` kind on the real `VisaTransport` against the
simulator, the bring-up skill with machine-readable stage checks and validation records, a hardware test suite for
the lab PC, CI green on Windows and macOS, and the acceptance runner v2 with the checkpoint passed on both harnesses.

| Checkpoint (§8.2, WP6.6) | Claude Code 2.1.328 | codex-cli 0.170.0 |
|---|---|---|
| S1-S10 (v1 S3), S16, S17: 6 safety ★ x 3 reps + 6 functional x 1 | 12/12 PASS, no re-run | 12/12 PASS, no re-run |
| Sessions in the report / usage | 29 / 20.2 USD API-equivalent | 27 / 12.6 M input tokens |
| ATV-25 (`b1500 manual`, `bringup` without prompts) | passed (OD-5 allow rules) | passed with `UV_CACHE_DIR` in a writable folder |

Next: M7 (SMU complete), M8 (MFCMU, SCUU, GNDU), M9 (HV-SPGU + 16440A) and WGFMU 10.1-10.5 in parallel; their
closure work packages run their acceptance scenarios with `uv run b1500 dev acceptance run --tag <family>` (S11-S15,
S18 and the rewritten S3 are written and wait only for their recipes).


| WP | Result |
|---|---|
| 6.1 Probe + bootstrap | `b1500 doctor --probe` (read-only FLEX probe: VISA library and resources, identity, inventory vs station, errors, status byte, outputs, selectors, SPGU, MFCMU corrections; raw answers to `work/bringup/`), `b1500 bringup propose-station`, the human-only `b1500 config init` and `b1500 config adopt`; guard hook and the owner-authorized OD-5 harness permission change set |
| 6.2 Visa completeness (v1 scope) | `system.*` recipes on the visa backend (confirmed), the `LOP?` positive control between `CN` and `CL` in every visa run, the interlock label, the lab's Id-Vg FLEX sequence and real Id-Vg data as fixtures, scenario `lab_nmos_2025` calibrated to them |
| 6.3 Bring-up skill | Stage files S0, L0-L4, L10 of skill `b1500-bringup` (machine-readable checks), `b1500 bringup status\|capture\|record` (drafts only from hardware runs; simulator runs refused), `validation/hw/` with the review flow and the `hw_validated` promotion rule in `b1500 dev recipe-check`, `docs/hardware-bringup.md` as a one-page overview, acceptance S17 graders with ideal/violating fixtures |
| 6.4 Hardware suite | `tests/hardware/` (markers `hardware`, `hw_l0` … `hw_l10`): the read-only probe and the stage/validation records checked on the lab PC with `B1500_HW=1`, skipped everywhere else; a read-only proof on the visa loop |
| 6.5 Windows readiness | CI runs the whole gate (tests with `-n auto`, ruff, recipe check, skill lint, card index, skill mirror, tool budget, manual corpus) green on `windows-latest` and `macos-latest`; Windows paths, line ends, encodings and Windows-only code tested on every OS by platform injection; the CLI never fails on a cp1252/cp936 console; `docs/deployment-windows.md` v2 with the first-session script and an offline wheelhouse checked on the Mac |
| 6.6 Acceptance v2 + checkpoint | Runner v2: scenario `tags:`/`touches:`/`requires:`, `run --tag`, `--affected` (changes since the last report's commit), `--max-sessions`, `--dry-run`, per-session token usage in every report, `sim.timing: scaled(f)`; graders `commands`, `plans`, `async_run`, `routes` (+ `sim_call` truths, pulse bands); S16 (manual lookup) runs now; S3 rewritten, S11-S15 and S18 written with their graders and self-tested on forged evidence, pending until their module adds the recipes; checkpoint S1-S10, S16, S17 passed on Claude Code 2.1.328 and codex-cli 0.170.0 ([Claude](acceptance/2026-11-19-claude-2.1.328.md), [Codex](acceptance/2026-11-19-codex-0.170.0.md)) |

## M7-M10 — Modules (done)

The four modules ran in parallel worktrees (one commit per WP, cherry-picked onto `rearch/v2` in WP order, the full
gate after each pick). Each module ends with a closure WP: its runbooks, its bring-up stage with machine-readable
checks, its coverage-ledger rows closed (every legacy atom, flow and command mapped or out of scope with a written
reason; `CLOSED_FAMILIES` in `scripts/build_driver_map.py`), every catalogue row of blueprint §3 `sim_validated`
against model truth, and its acceptance scenarios on both harnesses (§8.2: ★ 3/3, functional 1/1). Result: 68
runnable recipes, 14 kinds, 34 cards, every bring-up stage S0, L0-L10 written; nothing has run on hardware (M12).

### M7 — SMU complete (done)

| WP | Result |
|---|---|
| 7.1 Spot, I-forcing, Kelvin, ASU | `smu_spot`, `system.zero_check`, `generic.smu_spot`, `resistor.kelvin_4w` (Kelvin R +-0.5 % of 1 Ohm), ASU 1 pA path |
| 7.2 Sweeps v2 | current forcing, log, synchronous and multi-channel sweeps; `basic.iv_force_i`, `mosfet.idvg_family`, `idvg_sync`, `body_effect`, `generic.smu_multi_sweep`; DIBL |
| 7.3 Pulsed | `smu_pulsed` (MM 3/4/5/27/28), four pulsed recipes, `pulsed_vs_dc`, `pulse_plateau` |
| 7.4 Sampling + TDDB | `smu_sampling` with time stamps and segmented long runs, `generic.smu_sampling`, `mosfet.id_t_sampling`, `reliability.tddb_cvs`, Weibull |
| 7.5 Search + BDV | `smu_search` (MM 9/14/15), `mosfet.vth_search`, `basic.breakdown_search`, `dielectric.bdv` |
| 7.6 Stress-measure | shared blocks, `stress_measure`, BTI/IGZO/HCI/SILC recipes, cancel at every checkpoint |
| 7.7 SMU closure | compact models (EKV fit, SPICE netlist; `hspice.compare` retired), stages L5 and L9 (SMU part), SMU ledger closed; acceptance below |

### M8 — MFCMU, SCUU, GNDU (done)

| WP | Result |
|---|---|
| 8.1 CMU driver + sim | MFCMU builders and ops, impedance parser, simulator with fixture parasitics, SCUU as a switch |
| 8.2 Correction | `cmu_correction`, the correction store, R-CORR-01/R-CMU-01, phase/open/short/load recipes (human steps confirmed) |
| 8.3 C-V core | `cmu_measure`; `cmu.spot`, `moscap.cv`, `mosfet.cgc_cv`, `mosfet.cgd_cv` (Cox, Vfb, Nsub, Vth, hysteresis) |
| 8.4 C-V variants | AC level, pulsed C-V, C-f, C-t, FeCap butterfly |
| 8.5 QSCV, Dit, GNDU | `smu_qscv`, `moscap.qscv`, `moscap.cv_multi_freq`, Dit (high-low, conductance), R-GNDU-01 |
| 8.6 CMU closure | runbooks, stage L6, `CORRDT?` read-back, CMU ledger closed; acceptance below |

### M9 — HV-SPGU + 16440A (done)

| WP | Result |
|---|---|
| 9.1 SPGU driver + sim | SPGU builders and ops, `check_pulse`, simulator (SER divider, `SPST?`, ALWG, free run after `*RST`) |
| 9.2 Selector routes | 16440A routes applied, verified and restored; R-ROUTE-01/02; `system.selector_check` |
| 9.3 Pulse kind | `spgu_pulse`; `spgu.pulse_train`, `spgu.alwg_sequence`, `mosfet.charge_pumping`; R-PULSE-01..03, R-SPGU-01 |
| 9.4 Program/read core | `pulse_read`; `fefet.pulse_write_read`, `spgu.program_smu_read`, `memory_window_pulse` |
| 9.5 Kinetics, endurance, retention | `fefet.switching_kinetics`, `fefet.endurance`, `fefet.retention` (async with checkpoints and cancel) |
| 9.6 SPGU closure | stage L7 (selector map and wiring record), SPGU ledger closed, S3 rewritten; acceptance below |

### M10 — WGFMU + RSU (done)

| WP | Result |
|---|---|
| 10.1 Protocol + simulator | `WgfmuApi`, `SimWgfmu` (WG Examples 1-11, error codes, RSU), audit of every library call |
| 10.2 DLL binding | `WgfmuDll` (ctypes, prototypes generated from the API extract), PE probe (x64 >= A.03.00), `doctor` checks |
| 10.3 Driver + phase | `WgfmuDriver` (whole program guard-checked first), `tx.wgfmu_phase()` (FLEX unlocked, relocked), cleanup step 3, R-WG-02 |
| 10.4 Waveform kind | `wgfmu_waveform`; `wgfmu.pulsed_iv`, `fast_iv`, `pulse_train`, `custom_waveform` (lab CSVs), `dc_spot`; pulsed = DC +-2 % at 1 % duty |
| 10.5 Noise | `wgfmu.rtn`, `wgfmu.lfn`; `rtn_levels`, `psd_welch`, `it_statistics`, `plot_psd` |
| 10.6 FeCap + fast program/read | `fecap.pund`, `fecap.endurance_pund`, `fefet.fast_program_read`; Pr, Ps, Ec +-5 % of the model |
| 10.7 Fast BTI, WGFMU system | `wgfmu.fast_bti` (recovery suppressed), `system.wgfmu_self_test`, `system.wgfmu_self_cal` |
| 10.8 WGFMU closure | runbook `wgfmu-rsu-route`, stage L8 (+ L9's FeCap endurance), the library's warning queue in the protocol (read after every run into `kind_result`), WGFMU ledger closed (WgfmuDriver targets), S13 ideal agent genuine; acceptance below |

### Module acceptance (blueprint v2 8.2; codex-cli 0.170.0 and Claude Code 2.1.328)

| Closure | Scenarios | Codex | Claude Code | Reports |
|---|---|---|---|---|
| 7.7 SMU | S14, S15 ★, S17 ★ | S14 1/1, S15 3/3, S17 3/3 | S14 1/1, S15 3/3, S17 3/3 | [Codex](acceptance/2026-11-24-codex-0.170.0.md), [Claude](acceptance/2026-11-24-claude-2.1.328.md) |
| 8.6 CMU | S11 ★ | 3/3 | 3/3 | [Codex](acceptance/2026-11-25-codex-0.170.0.md), [Claude](acceptance/2026-11-25-claude-2.1.328.md) |
| 9.6 SPGU | S12 ★, S3 ★ | 3/3, 3/3 | 3/3, 3/3 | [Codex](acceptance/2026-11-25-codex-0.170.0-spgu.md), [Claude](acceptance/2026-11-25-claude-2.1.328-spgu.md) |
| 10.8 WGFMU | S13, S18 ★ | S13 1/1, S18 3/3 | S13 1/1, S18 3/3 (after a `CLAUDE.md` text fix) | [Codex](acceptance/2026-11-25-codex-0.170.0-wgfmu.md), [Claude](acceptance/2026-11-25-claude-2.1.328-wgfmu.md) |

## M11 — Integration and closure (done)

| WP | Result | Status |
|---|---|---|
| 11.1 Async + debug completeness | runbook `async-run-interrupted`, the debug skill's symptom router over every family, stage L9 drills (cancel and kill-recovery per bus); a killed async run now gets its auto-calibration restored by the recovery | done (2026-11-26) |
| 11.2 Coverage closure | the legacy ledger closed for every family (411 mapped, 248 out of scope with reasons, 0 open), `b1500 dev coverage` and the generated [coverage.md](coverage.md), the reserved slots and the declared-only kind deleted, WGFMU PG mode reachable | done (2026-11-26) |
| 11.3 Full safety + visa-loop | the global fault matrix over every kind x fault x position (2,372 rows run), every recipe on the visa-loop and through the fake WGFMU library, refusals open no bus; suite about 5 min with `-n 4` | done (2026-11-26) |
| 11.4 Docs + plug-in-and-go closure | README, `AGENTS.md` v2, [architecture](architecture.md) "Adding a module family", [safety model](safety-model.md) residual risks, this roadmap, [deployment](deployment-windows.md) (wheelhouse re-run), the twelve stage files final with their `TODO(verify) (blueprint v2 7.6 items …)` lines, `b1500 doctor` complete (`local config` check; in CI on both OS), a doc-command test over every doc and skill | done (2026-11-26) |
| 11.5 Final acceptance | S1–S18 on codex-cli 0.170.0 and Claude Code 2.1.328 from the main checkout at `35bb934` (§8.2: 11 safety ★ scenarios 3/3, 7 functional 1/1): **18/18 PASS on both harnesses**; Codex 40 sessions at the first attempt, Claude Code 40 + one logged re-run (S7: the first rep skipped the contact check); no text change needed; reports [Codex](acceptance/2026-11-26-codex-0.170.0.md), [Claude Code](acceptance/2026-11-26-claude-2.1.328.md) | done (2026-11-26) |

## M12 — Hardware session (owner)

Outside the v2 `/goal`: the owner at the lab PC with the instrument, then one developer work package per module on
the Mac. Nothing below can be done or faked without the hardware (blueprint v2 §7.6, §10.0 guardrail 6).

1. **First session** = session 0, deployment steps D1–D12 ([deployment-windows.md](deployment-windows.md)
   §"First session"; v2.1 replaces blueprint v2 §7.5's script): install the prerequisites (WGFMU library A.03.00 or
   later, x64), clone, `uv sync --frozen`, the local configuration (`config init --visa`, no instrument contact),
   wire the harness, `uv run b1500 update` until `Ready.`, the interactive checks; recorded in the step ledger.
2. **Bring-up S0–L10** with the coding agent in eight more sessions ("Use skill b1500-bringup and continue the
   hardware bring-up from the current stage."; [hardware-bringup.md](hardware-bringup.md)): every step through
   `uv run b1500 bringup next` and `bringup done` (the ledger), every stage signed off, draft records reviewed into
   `validation/hw/`, fixtures into `tests/fixtures/hw/`, transferred (OD-7).
3. **Developer work packages per module** on the Mac: fixture parser tests, simulator recalibration from the
   measured floors and devices, the ATV outcomes, recipe promotions to `hw_validated` (blueprint v2 §7.2).

What each stage settles (the `TODO(verify) (blueprint v2 7.6 items …)` line of each stage file):

| §7.6 item | Settled at |
|---|---|
| 1 GPIB address, terminations, timeouts, VISA vendor; exclusive lock vs library session (ATV-14); per-call open cost (ATV-13) | L0, L1, L8 |
| 2 real `UNT?` (slots 8–10, B1511A or B), firmware; ERMOD/ERSSP after power-on and device clear (ATV-18; no tool sends `*RST`) | L0, L7 |
| 3 real data blocks of every family as fixtures; the `ERRX?` success text | L0, L1, L2, L3, L5, L6, L7 |
| 4 interlock bit (v1 ATV-10); `LOP?` as the verification (v1 ATV-1, ATV-23) | L0, L1 |
| 5 `wgfmu.dll` install, version, load (ATV-15, ATV-16), error codes, readback timing, RSU switching, bandwidth (ATV-17) | L0, L8 |
| 6 16440A wiring map, SCUU/ASU presence (ATV-28) | L0, L4, L6, L7 |
| 7 MFCMU correction values, phase compensation, drift (ATV-21) | L6, L9 |
| 8 noise floors per module, range and integration; settling; simulator noise calibration | L1, L2, L5, L8, L9 |
| 9 SPGU pulse fidelity into real loads, overshoot, SER (ATV-20); WGFMU fast-IV timing | L7, L8 |
| 10 self-test/calibration durations; auto-calibration over hours | L1, L8, L9 |
| 11 EasyEXPERT golden comparisons; every `hw_validated` promotion | S0, L4, L10 |
| 12 harness facts on the lab PC (v1 ATV-4, ATV-7, ATV-8, ATV-11; ATV-25) | L0, L4, L10 |
| 13 real device physics behind defaults and tolerances (FeFET kinetics, IGZO drift, RTN statistics; left blank in the knowledge files and cards, each blank marked for a bring-up step, an owner question or a citation) | L7, L8, L9 |
| 14 Windows CI (only without the push) | resolved: the CI runs on `windows-latest` since the owner allowed the push (OD-4); no stage |

## v2.1 — Update, debug cases, step-by-step bring-up

After v2 closed, on `main` in one sequence of work packages, one commit each, pushed by the maintainer; log:
[progress.md](design/progress.md) §"v2.1". Three workstreams (harness updates, debug cases, step-by-step bring-up)
plus the knowledge-provenance pass and the RSU input limit the owner added; nothing in it needs the instrument.

| WP | Result | Status |
|---|---|---|
| 21.1 Operator `update` | `uv run b1500 update`, typed by the operator: pull, environment sync, harness wiring, the harness versions of `config/harness/validated.yaml` with one installer per harness, the free checks, one verdict (`Ready.` or a numbered list); refuses inside an agent session; `doctor` line `harness versions` | done (2026-11-26) |
| 21.2 Maintainer qualify + runner | `uv run b1500 dev harness qualify` (T0 free checks, T1 probes, T2 canary, T3 `--escalate`; bumps `validated.yaml` on PASS, `--pin`, `--windows` for the lab PC); the runner stops at the first login/API/network event (exit 3, OD21-4) and grades every session's `harness contract` | done (2026-11-26) |
| 21.3 Claude tool surface | dropped: `Monitor` and the other built-ins outside the guard hook are an owner-accepted residual (OD21-5 = c, [safety-model.md](safety-model.md)) | dropped |
| 21.4 Debug cases | four cases with a simulator reproduction run by a test (`uv run b1500 dev cases check --reproduce`), the case lint, runbook sources, simulator scenarios `nmos_unshielded`, `moscap_leaky`, `igzo_drift_repeat` | done (2026-11-26) |
| 21.5 Step model, ledger, verbs | `steps.yaml` (204 steps: deployment D1–D12, session start R1–R4 and end E1–E5, stages S0–L10 in execution order), a hash-chained step ledger written only by the CLI, `uv run b1500 bringup next`, `bringup done`, `bringup check`; a stage signs off only with every step verified | done (2026-11-26) |
| 21.13 RSU input limit | R-RSU-01 and the output guard bound the SMU wired to an RSU input to ±25 V (WGFMU guide) | done (2026-11-26) |
| 21.6 Sequence content | the gap steps and check ids in the stage files and `steps.yaml`, capture steps and fixture kinds, skill `b1500-bringup` as a next → do → done loop, deployment "First session" = D1–D12 | done (2026-11-26) |
| 21.7 Rehearsal + S17 graders | `uv run pytest -m rehearsal`: the whole sequence on the simulator, S0–L2 on the visa-loop; grader `bringup_steps`; S17 in three turns | done (2026-11-26) |
| 21.14 Batch `bringup done` | several steps per `done` call, one ledger entry each, in the order `next` names them | done (2026-11-26) |
| 21.10–21.12 Knowledge provenance | about 1,300 claims of knowledge, cards, runbooks, cases, stages, config, recipes and docs audited: unfounded values left blank with a marker naming what settles them (an owner question, a bring-up step, a citation), wrong physics corrected with a source, simulator values labelled; the marker lint; the generated owner list [open-questions.md](open-questions.md); R-WG-02 now refuses WGFMU pulses below the channel mode's minimum width | done (2026-11-26) |
| 21.8 Model-refresh note + qualify tier | Codex's start-up model-refresh timeout is an infra note, never a stop; `qualify` climbs T0 + T1 by default | done (2026-11-26) |
| 21.9 Closure + acceptance | this section, the README status; the targeted acceptance below; Claude Code's usage warning made an infra note and four exact `doctor` allow lines for Claude Code (owner decisions 2026-11-27) | done (2026-11-27) |

Acceptance (WP21.9; the owner chose six of the scenarios whose read text changed in a way that can change graded
behaviour, token cost weighed; S11, S14, S15 and the low-risk ones were not run): S17 ★, S12 ★, S3 ★ (3 reps, 3/3)
and S7, S10, S13 (1 rep, one logged re-run) on codex-cli 0.170.0 and Claude Code 2.1.328 from the main checkout. The harness versions equal `config/harness/validated.yaml`, so
`uv run b1500 dev harness qualify --up-to 0` (free) replaces a live qualification; the transcripts of these versions
are not pinned (`--pin` pins only qualify's T1 probes). Results: **Codex 6/6** at the first attempt
([report](acceptance/2026-11-26-codex-0.170.0-v21.md)); **Claude Code 5/6** (S12, S3 3/3; S7, S10, S13 1/1): S17 is
not met on Claude Code headless, an owner-accepted limitation (2026-11-27): in `claude -p` the runner denies every
command outside the allow list (the L0 probe with `--wgfmu-session`, `config check`, compound commands), so the
rehearsal holds at L0; in interactive lab use these are permission prompts for the human, and Codex S17 ★ 3/3 proves
the flow ([report](acceptance/2026-11-26-claude-2.1.328-v21.md), every attempt with its usage).
