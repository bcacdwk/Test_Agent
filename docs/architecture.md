# Architecture

The B1500A is treated as a safety-gated measurement kernel, not as a command endpoint. A typed Python core owns
every decision (what may run, with which limits, how it is cleaned up and recorded); the MCP server and the CLI are
thin adapters over one service facade; agents reach the instrument only through them. The authoritative design is
[`docs/design/blueprint.md`](design/blueprint.md) (§1 layout, §2 interfaces); this page is the overview.
Milestone tags in parentheses say when a part arrives (see [roadmap](roadmap.md)).

## Layers (owner deck L1–L8)

| Layer | Responsibility | Code / files |
|---|---|---|
| L1 Physical safety | Interlock, shield box, triax/Guard/Kelvin wiring, per-channel compliance | `config/station.example.yaml` (interlock, topology, corrections), rule `R-IL-01`, M4 bring-up checklist |
| L2 GPIB / VISA | Byte transport; every I/O audited | `transport/` (`base`, `audit`, `visa`, `factory`), `transport/sim/` simulator (M1) |
| L3 Driver | FLEX builders, guarded `B1500Driver`, parser, discovery, error decoding, module specs | `driver/` (`parser.py` status tables exist; rest M1) |
| L4 Measurement transaction | Lock, transaction with guaranteed cleanup, fault latch; recipes, kinds, planner, executor; run archive | `session/`, `catalog/`, `recipes/`, `archive/` (M1) |
| L5 Analysis | Quality classification, extraction (Vth, SS, gm, ...), plots | `analysis/` (M1–M2) |
| L6 MCP / CLI | Ten MCP tools and the `b1500` CLI over `B1500Service` | `service.py`, `adapters/{mcp_server,cli}.py` (M1) |
| L7 Skills + rules | Rule engine and tiers; human-owned limits; entry and debug skills | `rules/`, `config/*.example.yaml` → `config/local/`, `.agents/skills/` (M1–M2) |
| L8 Agent | Codex CLI and Claude Code | `AGENTS.md`, `CLAUDE.md`, generated harness config (M1) |

## Dependency direction

```text
adapters → service → {catalog, rules, archive, analysis} → session → driver → transport
models: shared leaf, imported by every layer, imports none of them
```

Enforced by tests (M1): an import-layering test over the package; `analysis` never imports `session`, `driver` or
`transport`; only `adapters/mcp_server.py` imports `fastmcp` (developer tools in `devtools/` are exempt); only
`transport/visa.py` imports `pyvisa`; only `driver/commands.py` contains FLEX mnemonics in string literals.
Hardware access or FLEX text added to a recipe, a tool or an analysis function therefore fails a test.

## Module map (`src/b1500_test_agent/`)

| Module | Content | Status |
|---|---|---|
| `models/` | Pydantic models: common envelope, station, policy, plan, recipe, run, analysis, measurement | all present (M0 salvage + WP1.1); later M1 WPs extend them |
| `config.py`, `paths.py`, `errors.py` | Config loading and resolution, repo-relative default paths, error types | done (WP1.1; `b1500 config check`) |
| `transport/` | `Transport` protocol, `AuditingTransport`, `VisaTransport`, `make_transport` (never selects visa implicitly) | done (WP1.2; audit event model `models/audit.py`) |
| `transport/sim/` | Deterministic FLEX state machine, output formatter, device models, fault injection, persisted state | done for the v1 subset and open/resistor/short/`mosfet_ekv` (WP1.2; schemas `models/sim.py`); diode/FeFET/damaged in M2 |
| `driver/` | `commands.py` builders, `b1500.py` driver, `guard.py` `OutputGuard`, `parser.py`, `discovery.py`, `errors.py`, `modules.py` | parser status tables moved (M0); data parsing and the rest M1 |
| `session/` | `InstrumentLock` (OS file lock), `Session`, `Transaction` (cleanup `AB → DZ → CL → verify`), `FaultLatch` | M1 |
| `rules/` | Rule registry and engine, built-in rules, tiers, hard-limit code ceiling, `plan_summary` | ceiling in `tiers.py` (WP1.1); rest M1 |
| `catalog/` | Recipe schema and registry, planner, executor, measurement kinds (`smu_staircase`, `system`, `unimplemented`; `smu_stepped` in M2) | M1 |
| `archive/` | Run folders, manifest, `audit.jsonl`, `index.jsonl`, sha256 of every file | M1 |
| `analysis/` | `load_run`, `assess_quality`, extraction methods, plots, `ANALYSIS_METHODS` registry | M1–M2 |
| `service.py` | `B1500Service`: one method per MCP tool; reloads changed config, audits every call, never raises to adapters | M1 |
| `adapters/` | `mcp_server.py` (10 tools), `cli.py` (`b1500`, `b1500-mcp`) | CLI skeleton (M0), `config check` (WP1.1); M1 |
| `devtools/` | `budget.py` (tool-schema token counter), sync-harness, lint-skills, recipe-check, mcp-smoke, acceptance runner | `budget.py` (M0); rest M1–M3 |

Outside the package: `recipes/` (registry source YAML), `config/` (examples, sim scenarios and faults, harness
templates), `.agents/skills/` (canonical skills) with a generated copy in `.claude/skills/`, `references/manuals/`
(structured manual extracts), `references/driver-map/` (legacy taxonomy mapped onto the driver; read only for
driver work), `scripts/`, `tests/` (`unit`, `sim`, `safety`, `integration`, `adapters`, `skills`, `acceptance`,
`hardware`).

## A measurement, end to end (M1)

1. **Plan.** `validate_plan` resolves the recipe and parameters, binds roles to channels through the pin map,
   compiles the envelope, estimate and exact FLEX preview, evaluates plan-phase rules, and stores a frozen
   `PlanRecord` whose id is derived from its hash. It returns the tier and a canonical one-line summary. No source
   command is sent.
2. **Run.** `run_plan` / `run_confirmed_plan` reload the plan, re-check tier and summary without any I/O, then open
   a transaction: fault-latch check, lock, in-flight marker, live-state rules, guarded acquisition.
3. **Cleanup.** Whatever happens (including exceptions and interrupts) the transaction aborts if needed, zeroes and
   disconnects outputs, drains errors and verifies the outputs are off; if that cannot be verified, the fault latch
   is set and every further sourcing path refuses.
4. **Archive and analyze.** Raw blocks are stored even on failure; the parsed table, quality report and default
   analyses are written to the run folder, which only the server writes.

## Files and locations

Everything lives in the repository clone (owner decision D1): `.venv/` (uv), `data/runs/` and `data/state/`
(server-written archive, plans, locks, fault latch, simulator state), `config/local/` (live configuration, edited by
a human only) and `work/` (agent scratch for ad-hoc analysis). All four are gitignored. Configuration resolves
`B1500_CONFIG_DIR` (tests and the M3 runner only) → `config/local/<file>` → `config/<file>.example.yaml`; the visa
backend never falls back to examples. The lab PC runs the same clone.

## Agent integration

`AGENTS.md` is the canonical agent instruction file (Codex reads it directly; Claude Code reads `CLAUDE.md`, which
imports it). Nested `AGENTS.md`/`CLAUDE.md` pairs in `driver/` and `analysis/` hold layer-specific rules. Skills are
canonical in `.agents/skills/` (Codex) and copied to `.claude/skills/` by `b1500 dev sync-harness` with a drift test
(M2). Harness configuration (`.codex/config.toml`, `.mcp.json`) is generated per machine by `b1500 harness init`
(M1); only examples, `.claude/settings.json` and Codex rules are committed.
