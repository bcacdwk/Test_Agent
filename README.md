# B1500A Test Agent

A safety-gated measurement kernel for the Keysight B1500A Semiconductor Device Analyzer, built to be driven by
coding agents (Codex CLI and Claude Code) without letting them send raw instrument commands.

A typed Python core plans, checks, runs, archives and analyzes measurements. Two thin adapters expose it: an MCP
server with ten outcome-level tools and the `b1500` CLI. Every executable action is a **recipe**. It runs only
through `validate_plan → run_plan` or, when a human must confirm, `run_confirmed_plan`, and the core enforces
limits, tiers, per-command output guards and a guaranteed safe shutdown. An in-process FLEX simulator stands in
for the instrument, so everything is developed and tested without hardware.

> **Status (2026-11-18): M1 runnable skeleton, M2 skill system and M3 harness acceptance done** (S1–S10 pass on
> Codex and Claude Code, [docs/acceptance/](docs/acceptance/)). On the
> simulator, six SMU measurements (contact/resistor check, diode I-V, MOSFET Id-Vg and Id-Vd, gate leakage, FeFET
> dual-sweep memory window) run through the 10-tool MCP server or the `b1500` CLI and are analyzed by their
> extraction methods; these recipes, `generic.smu_staircase` and `system.*` are simulator-validated. Skill
> `b1500-test` routes requests by family to seven test cards (generated index) and seven knowledge files, skill
> `b1500-debug` handles abnormal data, skill `b1500-bringup` (stage skeleton) will guide the hardware bring-up;
> Codex and Claude Code wiring comes from `b1500 harness init`. The read-only hardware probe
> (`b1500 doctor --probe`), the station proposal (`b1500 bringup propose-station`) and the human's configuration
> bootstrap (`b1500 config init|adopt`) run against the simulator and the visa-loop; the lab bring-up itself is the
> owner's hardware session M12 (see [docs/roadmap.md](docs/roadmap.md)); no code path has run against a real
> instrument yet.

## Layers

The eight layers of the owner's design deck and where they live:

```text
L8 Agent           Codex CLI / Claude Code          AGENTS.md, CLAUDE.md, harness config      (M1–M3)
L7 Skills + rules  b1500-test/-debug/-bringup       .agents/skills/  rules/  config/*.example  (M1–M2, M5)
L6 MCP + CLI       10 tools, `b1500` CLI            service/    adapters/{mcp_server,cli}.py   (M1)
L5 Analysis        quality, Vth/SS/gm, plots        analysis/  archive/                        (M1–M2)
L4 Transaction     recipes, plans, lock, cleanup    catalog/  recipes/  session/               (M1)
L3 Driver          FLEX builders, guard, parser     driver/                                    (M1)
L2 GPIB / VISA     VISA or simulator transport      transport/  transport/sim/                 (M1)
L1 Physical safety interlock, shield box, compliance station profile, M4 bring-up checklist    (M4)
```

Dependencies point downward only: `adapters → service → {catalog, rules, archive, analysis} → session → driver →
transport`, with `models` as a shared leaf. Details: [docs/architecture.md](docs/architecture.md); safety design:
[docs/safety-model.md](docs/safety-model.md).

## Quick start (development machine, simulator only)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11–3.13. From the repository root:

```bash
uv sync                                               # creates .venv/ in the clone from uv.lock
uv run pytest -m "not hardware and not acceptance"    # simulator-only test suite
uv run b1500 --help                                   # operator, human-only and developer commands
uv run ruff check
uv run b1500 doctor                                   # installation checks (PASS/WARN/FAIL)
```

Everything stays inside the clone: `.venv/`, `data/` (run archive and state), `config/local/` (human-owned live
configuration) and `work/` (agent scratch) are gitignored. Only `*.example.yaml` configuration is committed.

## Connect a coding agent

Launch the harness from the repository root. The MCP config is machine-specific (it holds the clone's absolute
path), so it is generated, not committed:

```bash
uv run b1500 harness init --codex     # writes .codex/config.toml (Codex loads it for trusted projects)
uv run b1500 harness init --claude    # writes .mcp.json (Claude Code asks once to approve the server)
uv run b1500 harness init --codex --claude --check    # drift and approval wiring check
uv run b1500 dev mcp-smoke --config .mcp.json         # starts the server as configured: 10 tools, backend sim
```

Committed alongside: `.codex/rules/b1500.rules` (Codex `forbidden` rules), `.claude/settings.json` (Claude Code
allow/ask/deny rules and the `scripts/hooks/b1500_guard.py` hook). `run_confirmed_plan` always asks the human
(Codex `prompt`, Claude Code `ask`); `run_plan` and `safe_shutdown` never do.

## How a measurement runs

1. The agent reads `station_status` and the recipe list, then calls `validate_plan` with a recipe, parameters, a
   pin map and a DUT profile.
2. The plan gets a tier: `ok` → `run_plan(plan_id)`; `needs_confirmation` → the agent shows the one-line summary,
   stops, and only after the human agrees calls `run_confirmed_plan(plan_id, summary)`, which the harness puts in
   front of the human; `blocked` → never runs.
3. The run executes inside a locked transaction that always ends with abort, zero, disconnect and a verified safe
   state, and archives raw data, parsed data, the audit log and the manifest under `data/runs/`.
4. `analyze_run` extracts parameters (the card's default method, for example Vth by linear extrapolation) from
   trusted points only.

## Lab PC (planned, M4)

The real station is a Windows PC wired to the B1500A over GPIB that runs the same clone (`git clone`/`git pull`,
`uv sync --frozen`, local config in `config/local/`). Step-by-step instructions will be in
`docs/deployment-windows.md` and the staged hardware bring-up in `docs/hardware-bringup.md` (an overview of the
stage files of skill `b1500-bringup`).

## Documentation

| Document | Content |
|---|---|
| [docs/design/blueprint.md](docs/design/blueprint.md) | Plan of record: interfaces, rules, tools, skills, milestones |
| [docs/design/progress.md](docs/design/progress.md) | Work-package log with acceptance results and handoff notes |
| [docs/architecture.md](docs/architecture.md) | Layers, dependency rules, module map |
| [docs/safety-model.md](docs/safety-model.md) | Rules, tiers, confirmation, cleanup, residual risks |
| [docs/roadmap.md](docs/roadmap.md) | Milestones M0–M4 and their status |
| [docs/manuals.md](docs/manuals.md) | Manual corpus: `b1500 manual search\|page\|toc`, catalog, citations |
| [docs/coverage.md](docs/coverage.md) | GENERATED: per module the kinds, recipes, cards, rules, simulator model, stages, ledger counts; the modes |
| [AGENTS.md](AGENTS.md) | Instructions for coding agents (also loaded by Claude Code via `CLAUDE.md`) |

## Scope

v2 covers the whole station: SMU I-V with the GNDU (spot, sweeps, pulsed, sampling, search), MFCMU C-V/C-f/C-t with
corrections and QSCV, HV-SPGU pulses through the 16440A selectors, WGFMU fast I-V and noise through the RSUs, the
FeFET/FeCap memory and reliability stress-measure flows, and instrument maintenance: 68 recipes in 14 kinds, all
validated on the simulator (hardware validation is the owner's bring-up). Module-by-module coverage (kinds, recipes,
cards, rules, simulator models, bring-up stages, legacy ledger): [docs/coverage.md](docs/coverage.md), generated by
`uv run b1500 dev coverage --write`.

## License

To be decided before publishing.
