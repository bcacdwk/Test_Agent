# Migration from v0.2 (fake 379-tool MCP server) to v1

v0.2 exposed 379 MCP tools (282 atoms that mirrored single FLEX commands and 97 flows composed from them), all
returning synthetic data; the driver underneath was stubs. v1 replaces that with a typed core, one guarded driver,
a recipe registry, and a 10-tool MCP server plus CLI over one service facade (see [architecture](architecture.md)).
The plan of record is [`docs/design/blueprint.md`](design/blueprint.md) (§1 for this table).

The v0.2 state is preserved by the annotated tag `archive/v0.2-fake-mcp` on commit `6bc9f3e`. Every removed file
stays recoverable from it (see [Recovering removed files](#recovering-removed-files)).

## Baseline

Tool-schema budget of the legacy server, measured once in WP0.3 (2026-11-17) with the blueprint §5.2 counter
(`uv run b1500 dev tool-budget --app b1500_test_agent.mcp.server:mcp`).

Method: the FastMCP app is built in-process and its tools are listed through the in-memory client; per tool, the
fields `name, description, inputSchema, outputSchema, annotations` are serialized as compact JSON and counted with
`tiktoken` `o200k_base`; the total is the sum over tools. Environment: fastmcp 4.2.0, tiktoken 0.14.0,
CPython 3.12.7. The legacy server's `instructions` string is not part of the tool schemas and is listed separately.

| Metric | v0.2 legacy (measured) | v1 target (blueprint §5.1–5.2) |
|---|---|---|
| Tools | **379** (282 atoms, 97 flows) | 10 (hard cap 20) |
| Tool-schema tokens, `o200k_base` | **104,691** | target ≤ 3,500; test cap 4,500 |
| Cross-check `ceil(chars / 4)` | 104,902 | — |
| Serialized characters | 419,029 | — |
| Largest tool | 3,678 (`CD_flow_analyze_iv_transfer`) | ≤ 700 per tool |
| Mean / median per tool | 276 / 115 | — |
| Server `instructions` | 1,304 chars (287 tokens) | ≤ 400 chars |

Per family (tools / tokens): A atoms 82 / 7,229 · B atoms 59 / 5,817 · C atoms 99 / 13,032 · D atoms 42 / 34,543 ·
A flows 20 / 2,512 · B flows 16 / 1,794 · C flows 31 / 14,636 · AB flows 19 / 2,978 · D flows 7 / 8,875 ·
CD flows 4 / 13,275.

### Reproducing the baseline

WP0.5 removed the legacy server from the working tree. The tag `archive/v0.2-fake-mcp` holds its sources but
predates the counter and `uv.lock`. Commit `a5325d6` (WP0.3 on `rearch/v1`) has all three: the legacy server, the
counter and the locked environment. Measure it in a temporary worktree so the main clone stays untouched:

```bash
git worktree add --detach "${TMPDIR:-/tmp}/b1500-baseline" a5325d6
cd "${TMPDIR:-/tmp}/b1500-baseline"
uv sync --frozen
uv run b1500 dev tool-budget --app b1500_test_agent.mcp.server:mcp
cd - && git worktree remove --force "${TMPDIR:-/tmp}/b1500-baseline"
```

Re-checked in WP0.6 (2026-11-17): 379 tools, 104,691 tokens, identical to the table. If `a5325d6` is ever lost (for
example after a squash merge), overlay the tag's legacy package on a worktree of a later commit, which keeps that
commit's counter and lock:

```bash
git worktree add --detach "${TMPDIR:-/tmp}/b1500-baseline" HEAD
cd "${TMPDIR:-/tmp}/b1500-baseline"
git checkout archive/v0.2-fake-mcp -- src/b1500_test_agent
uv sync --frozen
uv run b1500 dev tool-budget --app b1500_test_agent.mcp.server:mcp
```

This gave the same 104,691 tokens on `c1b1caa` (fastmcp 4.2.0); a later lock with another fastmcp version may
shift the count slightly. Remove the worktree afterwards as above.

The after-value (10-tool v1 server, same counter, `uv run b1500 dev tool-budget`) is recorded when WP1.8 lands.

## Path-by-path migration (blueprint §1)

Package paths are relative to `src/b1500_test_agent/`. "Pending" rows name the work package that finishes the move;
until then the v0.2 file stays in place as source material.

| v0.2 path | Action | v1 target | Status |
|---|---|---|---|
| `mcp/*` (21 files, 379 tools) | remove | `adapters/mcp_server.py` (10 tools); taxonomy extracted first | taxonomy WP0.4, removed WP0.5; server WP1.8 |
| `schemas/c_flow.py` | salvage, remove | `Integration`, `Ranging`, `SweepTiming`, `BiasChannel` → `models/measurement.py` (trimmed, no fake fields) | done WP0.5 |
| `schemas/d_atom.py`, `schemas/d_flow.py` | salvage, remove | `Quantity`, `QuantityRange`, `TrustPolicy`, `DerivativeMethod`, `VthSpec`, `MethodRecord`, `Provenance`, `Criterion` → `models/analysis.py` | done WP0.5 |
| `schemas/cd_flow.py`, `schemas/{measurement,policy,recipe,result,station}.py` | remove, rewrite | `models/*` | removed WP0.5; rewritten WP1.1 |
| `instruments/b1500/parser_ascii.py` | move, finish | `driver/parser.py` with `parse_fmt1`/`parse_fmt5` | moved WP0.5; finish WP1.3 |
| `instruments/b1500/{transport,session,safety,state_machine,discovery,calibration,flex_commands}.py` | rewrite | `transport/`, `session/`, `rules/`, `driver/` | removed WP0.5; WP1.2–1.6 |
| `instruments/b1500/{modules,switching,recipes}/*` | remove | `recipes/reserved/*.yaml` (`not_implemented`) | removed WP0.5; WP1.7 |
| `instruments/b1500/AGENTS.md`, `analysis/AGENTS.md` | move, trim (≤30 lines) | `driver/AGENTS.md`, `analysis/AGENTS.md`, each with a one-line `CLAUDE.md` (`@AGENTS.md`) | done WP0.5 + WP0.6 |
| `analysis/*.py`, `cli.py` | rewrite | `analysis/`, `adapters/cli.py` | removed WP0.5; CLI skeleton WP0.3; WP1.5, WP1.8 |
| `tests/test_parser_ascii.py` | keep, fix import | `tests/unit/test_parser.py` | done WP0.5 |
| `tests/test_{c_flows,cd_flows,d_atoms,d_flows,skeleton}.py`, `tests/mock_b1500.py` | remove | new suites; the simulator replaces the mock | removed WP0.5; simulator WP1.2 |
| v0.2 testing skill (`.agents/skills/<name>/**`, name listed by the tag) | rewrite | `.agents/skills/b1500-test/`; its `references/mcp-tools/*.md` → `references/driver-map/legacy-catalog/` | catalogs moved WP0.4; removed WP0.5; WP2.4 |
| `.agents/skills/b1500-debug-workflow/**` | rewrite | `.agents/skills/b1500-debug/` | removed WP0.5; WP2.7 |
| `config/default.example.yaml`, `references/station/{station-profile,cable-topology}.example.yaml` | merge | `config/settings.example.yaml` (transport, paths) + `config/station.example.yaml` (inventory, topology, corrections) | done WP1.1 |
| `config/safety_limits.example.yaml`, `references/policies/*` | merge | `config/policy.example.yaml` | done WP1.1 |
| `references/station/pin-maps/*`, `references/station/compensation/*`, `references/devices/*` | move | `config/pinmaps/`, `config/station.example.yaml#corrections`, `config/duts/` | done WP1.1 |
| `references/recipes/**` | rewrite to the recipe schema | `recipes/` (Id-Vg/Id-Vd values reused; FeFET write-read, flash, CGD C-V → `recipes/reserved/`) | pending WP1.7, WP2.2 |
| `references/{instruments,physics,hspice,debug}/` READMEs | fold | knowledge files 01/02/05/07 and skill `b1500-debug` | pending WP2.6, WP2.7 |
| `references/manuals/**`, `scripts/extract_manuals.py` | keep | unchanged | kept |
| `tmp/*` (42 tracked design notes) | remove; `tmp/` gitignored | kept by the tag; the plan was promoted to `docs/design/blueprint.md` first | done WP0.1, WP0.5 |
| `data/**` (tracked), `requirements.txt` | remove (untrack) | `data/` is the gitignored runtime dir; `pyproject.toml` + `uv.lock` are the single dependency source | done WP0.3, WP0.5 |
| `README.md`, `AGENTS.md`, `docs/*.md` | rewrite | blueprint §6.7; `docs/contributing.md` folded into the `AGENTS.md` developer section; `docs/manual-extraction.md` kept | done WP0.6 |
| `.codex/config.example.toml` | rewrite | generated configs from `b1500 harness init` (blueprint §5.4) | pending WP1.9 |
| `pyproject.toml` | fix | `requires-python >=3.11` (the parser uses `StrEnum`); scripts `b1500`, `b1500-mcp` | done WP0.3 |

## Where the v0.2 concepts went

- **Atoms** (one tool per FLEX command) are now internal `B1500Driver` methods and `driver/commands.py` builders,
  never MCP tools. The mapping of every atom and manual command is `references/driver-map/flex-driver-map.yaml`.
- **Flows** (fixed atom sequences) are now **recipes**: YAML in `recipes/`, executed by a measurement kind through
  `validate_plan` and `run_plan`/`run_confirmed_plan`, with the safety checks in the core instead of the tool layer.
- **D atoms/flows** (analysis placeholders) are now `analysis/` functions and the `analyze_run` tool; their
  successors are listed per atom in the driver map.
- **Tool catalogs** of v0.2 are frozen in `references/driver-map/legacy-catalog/`; they are history, not runtime
  material, and are never loaded by agents.
- **The mock instrument** is replaced by an in-process FLEX simulator behind the same transport interface as VISA.
- The owner deck's tool sketch maps as follows: `iv_sweep`, `spot`, `multi_channel_iv`, `pulsed_sweep`, `sampling`
  → recipes via validate and run; `connect`/`disconnect` → implicit in `station_status` and transactions;
  `zero_all_outputs` → `safe_shutdown`; `self_test`/`self_calibration` → `system.*` recipes; `force_voltage` is
  intentionally absent (no unattended bias hold); `analyze_iv_data`/`analyze_cv_data` → `analyze_run`.

## Recovering removed files

```bash
git show archive/v0.2-fake-mcp:<path>                                 # print one v0.2 file
git ls-tree -r --name-only archive/v0.2-fake-mcp -- <dir>             # list a removed directory
git ls-tree -d --name-only archive/v0.2-fake-mcp .agents/skills/      # the two v0.2 skill folders
mkdir -p <empty dir> && git archive archive/v0.2-fake-mcp <dir> | tar -x -C <empty dir>   # extract a tree to read
```

The tag is created locally; a fresh clone has it only after the owner pushed it (`git fetch origin tag
archive/v0.2-fake-mcp`). Recovered files are reference material: do not copy legacy tools, flows or the fake
response layer back into the package.
