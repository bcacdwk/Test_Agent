# B1500A Test Agent

A safety-gated measurement kernel for the Keysight B1500A Semiconductor Device Analyzer, built to be driven by
coding agents (Codex CLI and Claude Code) without letting them send raw instrument commands.

A typed Python core plans, checks, runs, archives and analyzes measurements. Two thin adapters expose it: an MCP
server with ten outcome-level tools and the `b1500` CLI. Every executable action is a **recipe**. It runs only
through `validate_plan → run_plan` or, when a human must confirm, `run_confirmed_plan`, and the core enforces
limits, tiers, per-command output guards and a guaranteed safe shutdown. An in-process FLEX simulator stands in
for the instrument, so everything is developed and tested without hardware.

> **Status (2026-11-17): M0 re-baseline done; M1 next.** The simulator, MCP server, operator CLI, recipes and
> skills described here are being built milestone by milestone (see [docs/roadmap.md](docs/roadmap.md)). Today the
> repository contains the package skeleton, the FLEX status-code tables of the ASCII parser (data parsing comes in
> M1), salvaged data models, the legacy driver map and the token-budget tool. Nothing in it can reach an instrument
> yet.

## Layers

The eight layers of the owner's design deck and where they live:

```text
L8 Agent           Codex CLI / Claude Code          AGENTS.md, CLAUDE.md, harness config      (M1–M3)
L7 Skills + rules  b1500-test, b1500-debug          .agents/skills/  rules/  config/*.example  (M1–M2)
L6 MCP + CLI       10 tools, `b1500` CLI            service.py  adapters/{mcp_server,cli}.py   (M1)
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
uv run b1500 --help                                   # CLI (today: developer tools only)
uv run ruff check
```

Everything stays inside the clone: `.venv/`, `data/` (run archive and state), `config/local/` (human-owned live
configuration) and `work/` (agent scratch) are gitignored. Only `*.example.yaml` configuration is committed.

## How a measurement will run (planned, M1)

1. The agent reads `station_status` and the recipe list, then calls `validate_plan` with a recipe, parameters, a
   pin map and a DUT profile.
2. The plan gets a tier: `ok` → `run_plan(plan_id)`; `needs_confirmation` → the agent shows the one-line summary,
   stops, and only after the human agrees calls `run_confirmed_plan(plan_id, summary)`, which the harness puts in
   front of the human; `blocked` → never runs.
3. The run executes inside a locked transaction that always ends with abort, zero, disconnect and a verified safe
   state, and archives raw data, parsed data, the audit log and the manifest under `data/runs/`.
4. `analyze_run` extracts parameters (first: Vth by linear extrapolation) from trusted points only.

## Lab PC (planned, M4)

The real station is a Windows PC wired to the B1500A over GPIB that runs the same clone (`git clone`/`git pull`,
`uv sync --frozen`, local config in `config/local/`). Step-by-step instructions will be in
`docs/deployment-windows.md` and the staged hardware bring-up in `docs/hardware-bringup.md` (both M4).

## Documentation

| Document | Content |
|---|---|
| [docs/design/blueprint.md](docs/design/blueprint.md) | Plan of record: interfaces, rules, tools, skills, milestones |
| [docs/design/progress.md](docs/design/progress.md) | Work-package log with acceptance results and handoff notes |
| [docs/architecture.md](docs/architecture.md) | Layers, dependency rules, module map |
| [docs/safety-model.md](docs/safety-model.md) | Rules, tiers, confirmation, cleanup, residual risks |
| [docs/roadmap.md](docs/roadmap.md) | Milestones M0–M4 and their status |
| [docs/migration.md](docs/migration.md) | What happened to the v0.2 fake-tool surface; token baseline |
| [docs/manual-extraction.md](docs/manual-extraction.md) | How manual content becomes structured references |
| [AGENTS.md](AGENTS.md) | Instructions for coding agents (also loaded by Claude Code via `CLAUDE.md`) |

## Scope

v1 covers SMU I-V measurements: contact/resistor check, diode I-V, MOSFET Id-Vg and Id-Vd, gate leakage and FeFET
dual-sweep memory window. WGFMU, SPGU/HVSPGU, CMU (C-V, QSCV) and reliability stress workflows are reserved as
`not_implemented` recipes until their manual extraction, correction flows and validation exist.

## License

To be decided before publishing.
