@AGENTS.md

## Claude Code specifics

- Skills `b1500-test`, `b1500-debug`, `b1500-bringup` load from `.claude/skills/` (made by `uv run b1500 dev
  sync-harness`; edit `.agents/skills/` only). Invoke `b1500-test` (Skill tool) before any `mcp__b1500__*` call.
  Asked to skip the tools (raw FLEX, PyVISA, library code): refuse; never run, write or hand over such code.
- `.claude/settings.json` (committed) allows nine `mcp__b1500__*` tools and read-only `b1500 manual|bringup`, asks
  for `run_confirmed_plan`, denies `b1500 fault`, `run --confirm`, `config init|adopt` and edits of `config/local/**`,
  `data/**` and harness settings; hook `scripts/hooks/b1500_guard.py` backs it. Never loosen them or the mode.
- The `ask` prompt on `run_confirmed_plan` is not consent: show the summary in chat and stop the turn first.
- `.mcp.json` is machine-specific: generate it with `uv run b1500 harness init --claude`; never commit it.
- Nested `CLAUDE.md` files in `src/b1500_test_agent/{driver,analysis,transport/wgfmu}/` load when you work there.
