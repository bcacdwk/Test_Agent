# Roadmap

Milestones of the re-architecture (blueprint §9). Each work package (WP) is one commit on branch `rearch/v1`; the
log with acceptance results and handoff notes is [`docs/design/progress.md`](design/progress.md), which is the
source of truth for status. This page is updated at milestone boundaries.

| Milestone | Goal | Status |
|---|---|---|
| M0 Re-baseline | Plan promoted, legacy archived and pruned, tooling, docs | **done** (2026-11-17) |
| M1 Runnable skeleton | One vertical path on the simulator: status → validate → staircase Id-Vg → archive → Vth | **done** (2026-11-18) |
| M2 Skill system | Six SMU test cards with recipes that run on the simulator; knowledge files; debug skill | next |
| M3 Harness acceptance | Ten scenarios on Codex and Claude Code against the simulator | planned |
| M4 Hardware bring-up | Checklists for the Windows lab PC and staged hardware validation | planned (docs only; execution later with the owner) |

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

## M2 — Skill system and recipe pack

| WP | Deliverable |
|---|---|
| 2.1 Sim models + kinds | Diode, FeFET and damaged-device models; double sweep; stepped sweep kind; more scenarios |
| 2.2 Recipes + analysis | Five more recipes and the remaining extraction methods, each validated against model truth |
| 2.3 Skill tooling | `b1500 dev sync-harness` (Claude Code copy + drift check), `b1500 dev lint-skills` |
| 2.4 Entry skill | `b1500-test` skill, card template, final `AGENTS.md`/`CLAUDE.md`, generated `.claude/skills/` |
| 2.5 Six cards | Contact/resistor check, diode I-V, MOSFET Id-Vg, MOSFET Id-Vd, gate leakage, FeFET dual-sweep memory window |
| 2.6 Knowledge 01–07 | Device physics, instrument, wiring, ferroelectrics/oxides, reliability, extraction, HSPICE (reserved) |
| 2.7 Debug skill | `b1500-debug` with eight runbooks and the deck's three cases |

## M3 — Harness acceptance

Scenario framework (isolated config and data dirs, human emulation, graders), scenarios S1–S10 (Vth measurement,
over-limit refusal, reserved pulse request, confirmation flow, consent forgery and config edit, raw-command request,
noisy data, unknown pins, injected instructions in notes, FeFET memory window), then baseline runs and skill-text
iteration until safety scenarios pass 3/3 and functional scenarios pass on both Codex and Claude Code.

## M4 — Hardware bring-up (checklists)

- `docs/hardware-bringup.md`: staged bring-up with sign-off lines: physical checks, read-only probing, 0 V open
  circuit, known resistors, known diode, known-good MOSFET compared with EasyEXPERT; recipes are promoted to
  `hw_validated` only with a validation record.
- `docs/deployment-windows.md`: lab PC setup (Python + uv, VISA + GPIB adapter, `git clone`, `uv sync --frozen`,
  `config/local/`, `b1500 doctor --probe`, `b1500 harness init`), residual risks in plain words, facts to collect.

## Later (reserved, not scheduled)

WGFMU pulsed I-V and fast BTI; SPGU/HVSPGU program + SMU read with the 16440A selector; FeFET pulse write/read,
endurance and retention; FeCap PUND; BTI, HCI and TDDB stress-measure; CMU correction, C-V and QSCV; HSPICE compare.
Each is registered as a `not_implemented` recipe and needs manual extraction, correction/leakage flows and
validation before it can run.
