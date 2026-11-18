@AGENTS.md

## Claude Code specifics

- Skills `b1500-test`, `b1500-debug` and `b1500-bringup` load from `.claude/skills/`, a generated copy of
  `.agents/skills/` (`uv run b1500 dev sync-harness`); edit only the source. Invoke `b1500-test` before the first
  `mcp__b1500__*` call.
- `.claude/settings.json` (committed) allows nine `mcp__b1500__*` tools, keeps `run_confirmed_plan` on `ask` and
  denies `b1500 fault`, `b1500 run --confirm` and edits of `config/local/**`, `data/**` and harness settings; the
  `PreToolUse` hook `scripts/hooks/b1500_guard.py` backs it. Never loosen these rules, the hook or the permission mode.
- The `ask` prompt on `run_confirmed_plan` is not consent: show the summary in chat and stop the turn first.
- `.mcp.json` is machine-specific: generate it with `uv run b1500 harness init --claude`; never commit it.
- Nested `CLAUDE.md` files in `src/b1500_test_agent/{driver,analysis}/` load when you work there.
