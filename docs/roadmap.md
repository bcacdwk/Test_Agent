# Roadmap

Milestones of the re-architecture. v1 (M0–M4, plan tag `plan-v1`) was built on branch `rearch/v1` and merged into
`main`; v2 (M5–M12, [blueprint](design/blueprint.md) §10) is built on branch `rearch/v2`, one commit per work package
(WP). The log with acceptance results and handoff notes is [`docs/design/progress.md`](design/progress.md), which is
the source of truth for status. This page is updated at milestone boundaries.

| Milestone | Goal | Status |
|---|---|---|
| M0 Re-baseline | Plan promoted, legacy archived and pruned, tooling, docs | **done** (2026-11-17) |
| M1 Runnable skeleton | One vertical path on the simulator: status → validate → staircase Id-Vg → archive → Vth | **done** (2026-11-18) |
| M2 Skill system | Six SMU test cards with recipes that run on the simulator; knowledge files; debug skill | **done** (2026-11-18) |
| M3 Harness acceptance | Ten scenarios on Codex and Claude Code against the simulator | **done** (2026-11-18; [reports](acceptance/)) |
| M4 Hardware bring-up | Checklists for the Windows lab PC and staged hardware validation | planned (docs only; execution later with the owner) |
| M5 Foundations | v2 plan, package split, models/config v2, guard + rules v2, per-transaction VISA + visa-loop, async runs, archive v2, manual corpus, device models v2, skills v2 structure | **done** (2026-11-18) |
| M6 Lab-ready core | Read-only probe, station proposal and config adoption, visa completeness, bring-up skill, hardware suite, Windows readiness, acceptance v2 | in progress (6.1 done) |
| M7 SMU complete | Spot/Kelvin/ASU, sweeps v2, pulsed, sampling + TDDB, search + BDV, stress-measure, compact models | planned |
| M8 MFCMU, SCUU, GNDU | CMU driver + simulator, corrections, C-V core and variants, QSCV, Dit, GNDU budget | planned |
| M9 HV-SPGU + 16440A | SPGU driver + simulator, selector routes, pulse kind, program/read, kinetics, endurance, retention | planned |
| M10 WGFMU | Library protocol + simulator, DLL binding, driver + phase, waveform kind, noise, FeCap PUND, fast BTI | planned |
| M11 Integration and closure | Async/debug completeness, coverage ledger closure, full safety + visa-loop, docs, final acceptance S1–S18 | planned |
| M12 Hardware session | Owner at the lab PC: staged bring-up S0–L10, validation records, then per-module developer WPs | owner (outside the v2 goal) |

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
| 2.6 Knowledge 01–07 | Device physics, instrument, wiring, ferroelectrics/oxides, reliability, extraction, HSPICE (reserved) |
| 2.7 Debug skill | `b1500-debug` with eight runbooks and the deck's three cases |

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
- [`docs/deployment-windows.md`](deployment-windows.md) (written, WP4.2): lab PC setup (Python + uv, VISA + GPIB
  adapter, `git clone`, `uv sync --frozen`, `config/local/`, `b1500 doctor --probe`, `b1500 harness init`),
  residual risks in plain words, facts to collect.

## v2 (M5–M12)

v2 keeps v1's kernel shape (recipe → kind → guarded driver → transaction with verified cleanup → archive →
analysis, behind the same 10 MCP tools) and fills it to the whole station: SMU, MFCMU (+SCUU), HV-SPGU with two
16440A selectors, WGFMU (+RSU) and GNDU, each implemented, simulated, tested, carded and given a bring-up stage
(68 recipes, 14 kinds, 33 cards). Order: M5 → M6 → (M7 ∥ M8 ∥ M9 ∥ WGFMU 10.1–10.5) → (10.6 ∥ 10.7) → 10.8 → M11;
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

## M6 — Lab-ready core (in progress)

| WP | Result |
|---|---|
| 6.1 Probe + bootstrap | `b1500 doctor --probe` (read-only FLEX probe: VISA library and resources, identity, inventory vs station, errors, status byte, outputs, selectors, SPGU, MFCMU corrections; raw answers to `work/bringup/`), `b1500 bringup propose-station`, the human-only `b1500 config init` and `b1500 config adopt`; guard hook and the owner-authorized OD-5 harness permission change set |
| 6.3 Bring-up skill | Stage files S0, L0-L4, L10 of skill `b1500-bringup` (machine-readable checks), `b1500 bringup status\|capture\|record` (drafts only from hardware runs; simulator runs refused), `validation/hw/` with the review flow and the `hw_validated` promotion rule in `b1500 dev recipe-check`, `docs/hardware-bringup.md` as a one-page overview, acceptance S17 graders with ideal/violating fixtures |
