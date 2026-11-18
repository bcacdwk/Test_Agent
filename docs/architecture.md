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
| L6 MCP / CLI | Ten MCP tools and the `b1500` CLI over `B1500Service` | `service.py`, `adapters/{mcp_server,cli}.py` (WP1.8) |
| L7 Skills + rules | Rule engine and tiers; human-owned limits; entry and debug skills | `rules/`, `config/*.example.yaml` → `config/local/`, `.agents/skills/` with the generated `.claude/skills/` copy (rules M1; skills M2: entry skill + card template WP2.4, six test cards + reserved slots WP2.5, knowledge 01–07 WP2.6, `b1500-debug` WP2.7) |
| L8 Agent | Codex CLI and Claude Code | `AGENTS.md`, `CLAUDE.md`, harness wiring: `config/harness/` templates → generated `.codex/config.toml` / `.mcp.json`, committed `.codex/rules/b1500.rules`, `.claude/settings.json`, `scripts/hooks/b1500_guard.py` (WP1.9) |

## Dependency direction

```text
adapters → service → {catalog, rules, archive, analysis} → session → driver → transport
models: shared leaf, imported by every layer, imports none of them
```

Enforced by tests (M1): an import-layering test over the package; `analysis` never imports `session`, `driver` or
`transport`; only `adapters/mcp_server.py` imports `fastmcp` (developer tools in `devtools/` are exempt); only
`transport/visa.py` imports `pyvisa`; only `driver/flex/` contains FLEX mnemonics in string literals (the simulator,
the instrument side, is exempt); only kind `system` calls the `*RST` builder; no source file exceeds 1,000 lines
(`tests/unit/test_layout.py`); `driver/ops/` is imported only by the `B1500Driver` facade and the simulator units
only by their dispatcher. Hardware access or FLEX text added to a recipe, a tool or an analysis function therefore
fails a test.

## Module map (`src/b1500_test_agent/`)

| Module | Content | Status |
|---|---|---|
| `models/` | Pydantic models: common envelope, station, policy, plan, recipe, run, analysis, measurement | all present (M0 salvage + WP1.1); later M1 WPs extend them |
| `config.py`, `paths.py`, `errors.py` | Config loading and resolution, repo-relative default paths, error types | done (WP1.1; `b1500 config check`) |
| `transport/` | `Transport` protocol, `AuditingTransport`, `VisaTransport`, `make_transport` (never selects visa implicitly) | done (WP1.2; audit event model `models/audit.py`) |
| `transport/sim/` | Deterministic FLEX state machine: `instrument.py` (dispatcher: clock, persisted state, command log, measurement lifecycle, `SimTransport`) over `units/` (`core`, `smu`; handlers registered by mnemonic), `flex.py` (syntax, error codes), `format.py` (output formatter), `devices/` (`basic`, `mosfet`, `ferro`, `circuit`), `faults.py`, `state.py` | done for the v1 subset and open/resistor/short/`mosfet_ekv` (WP1.2; schemas `models/sim.py`); `diode`, `fefet` (persisted polarization), `mosfet_damaged` and scenarios `diode_basic`, `resistor_100k`, `fefet_basic`, `open_drain_noisy`, `gd_short` (WP2.1) |
| `driver/` | `flex/` builders (`core`, `smu`; the only FLEX literals), `b1500.py` facade `B1500Driver(CoreOps, SmuOps)` over the `ops/` mixins, `guard.py` `OutputGuard`, `parser.py`, `discovery.py`, `errors.py`, `modules.py` | done for the staircase path (WP1.3: FMT 1/5 parser, discovery, `OutputGuard`, module specs; WP5.2: per-family split) |
| `session/` | `InstrumentLock` (OS file lock), `Session`, `Transaction` (cleanup `AB → DZ → CL → verify`), `FaultLatch` | done (WP1.6; inflight recovery, daily audit sink, `RunHandle` protocol for the archive) |
| `rules/` | Rule registry and engine, built-in rules (`builtin/`: `core`, `limits`, `run`, `cmu`, imported in table order), tiers, hard-limit code ceiling, `plan_summary` | done (WP1.4; rule table in [safety-model.md](safety-model.md)) |
| `catalog/` | Recipe schema and registry, planner, executor, measurement kinds (`smu_staircase`, `smu_stepped`, `system`, `unimplemented`) | done (WP1.7; recipes `mosfet.idvg`, `generic.smu_staircase`, `system.*` sim-validated, 13 reserved slots; `b1500 dev recipe-check`; WP2.1: `smu_stepped` host loop; WP2.2: `basic.contact_resistor`, `basic.diode_iv`, `mosfet.idvd`, `mosfet.gate_leakage`, `fefet.dual_sweep_mw` sim-validated) |
| `archive/` | Run folders, manifest, `audit.jsonl`, `index.jsonl`, sha256 of every file | done (WP1.7; raw blocks kept on failure, append-only notes) |
| `analysis/` | `load_run`, `assess_quality`, extraction methods, plots, `ANALYSIS_METHODS` registry | done (WP1.5: `quality_report`, `vth_linear_extrapolation`; WP2.2: `vth_constant_current`, `vth_max_gm`, `subthreshold_swing`, `gm_max`, `ion_ioff`, `output_metrics`, `resistance`, `diode_fit`, `leakage_at`, `memory_window`, `plot_iv` (PNGs stored under the run's `plots/` by the archive)) |
| `service.py` | `B1500Service`: one method per MCP tool; reloads changed config, audits every call, never raises to adapters | done (WP1.8; result models in `models/results.py`, responses ≤2k tokens, human-only `B1500Admin` for `fault clear`/`lock status`) |
| `adapters/` | `mcp_server.py` (10 tools), `cli/` (`b1500`, `b1500-mcp`: `core.py` root app and operator commands, `dev.py` the `dev` group) | done (WP1.8: 10 tools at 1,474 tokens, `requiresUserInteraction` on `run_confirmed_plan`; all §5.3 operator commands, `fault clear`, `lock status`, `doctor`, `mcp`; WP1.9: `harness init --codex\|--claude [--check]`, `dev mcp-smoke`) |
| `devtools/` | `budget.py` (tool-schema token counter), `doctor.py`, `sim_console.py`, `harness.py`, `mcp_smoke.py`, sync-harness, lint-skills (`skills/`: `layout`, `cards`, `params`, `links`, `budgets`, `markdown`, `common`, `lint`), recipe-check, acceptance runner | `budget.py` (M0), `recipe_check.py` (WP1.7), `doctor.py` (non-probe) + `sim_console.py` (WP1.8), `harness.py` (render/check harness configs, doctor harness check) + `mcp_smoke.py` (WP1.9); sync-harness, lint-skills WP2.3; acceptance runner WP3.1 |

Outside the package: `recipes/` (registry source YAML), `config/` (examples, sim scenarios and faults, harness
templates), `.agents/skills/` (canonical skills) with a generated copy in `.claude/skills/`, `references/manuals/`
(structured manual extracts), `references/driver-map/` (legacy taxonomy mapped onto the driver; read only for
driver work), `scripts/`, `tests/` (`unit`, `sim`, `safety`, `integration`, `adapters`, `skills`, `acceptance`,
`hardware`).

## Adding a module family (v2: CMU, SPGU, switches, ...)

The code is split per instrument family (blueprint §9), so a family's work packages touch their own files:

1. `driver/flex/<family>.py`: pure builders and constants, each docstring citing `PG p<pdf> (<printed>)`;
   re-export them in `driver/flex/__init__.py` (`__all__`) and add the module to `FAMILY_MODULES` in
   `tests/unit/test_driver_flex.py`; golden strings under `tests/fixtures/flex/<family>/`.
2. `driver/ops/<family>.py`: a `DriverBase` mixin whose source-like methods pass the `OutputGuard` first; add it to
   the bases of `B1500Driver` in `driver/b1500.py`.
3. `transport/sim/units/<family>.py`: a mixin with `@handles("<MNEMONIC>")` handlers and a settings reset; add it to
   the bases of `SimInstrument`, call its reset from `_reset_settings` and add the mnemonics to `flex.SUPPORTED`
   (`tests/sim/test_units.py` checks one handler per mnemonic). New device physics go to
   `transport/sim/devices/<model>.py` and `devices/circuit.py` (`build_device`).
4. `rules/builtin/<family>.py`, imported in `rules/builtin/__init__.py` at its place in the rule table (import order
   = registration order = finding order).
5. The kind (`catalog/kinds/`), recipes, the card folder, knowledge and the bring-up stage.

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
from the templates in `config/harness/` (WP1.9); only examples, `.claude/settings.json`, the Codex rules and the
guard hook are committed. Both configs start the same entry point (`uv run --frozen --project <clone> b1500-mcp`);
`run_confirmed_plan` always asks the human (Codex `prompt`, Claude Code `ask`), `run_plan` and `safe_shutdown`
never do.
