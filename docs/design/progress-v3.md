# v3 progress log

Plan: [plan-v3.md](plan-v3.md) (§4 work packages, §9 decisions); ids: [register.md](register.md); the v1, v2 and
v2.1 log is [progress.md](progress.md) (frozen). On `main` in the main checkout, one commit per work package
(`WP30.n <short title>`, the message says why and carries the detail), pushed after each commit.

One compact row per work package (at most ~1,000 characters): WP · commit · AC → result · deviations/handoffs. The
next work package backfills the previous row's commit cell "(next WP backfills)". Until WP30.20 every row states
"acceptance: none — offline evidence: …".

| WP | Commit | AC → result | Deviations / handoffs |
|---|---|---|---|
| 30.1 Plan of record and resolvable history | (next WP backfills) | `uv run pytest -q tests/adapters/test_design_register.py` → 9 passed (each mutation fails its test: dropped row, unknown step, bad status or source, broken link, scratch path + unknown id in a tracked file); `uv run b1500 dev gen-index --check` → up to date; `uv run b1500 dev lint-skills` → clean; both plans verbatim (`tail -n +7 … \| diff -` empty). Gate: pytest 11,534 passed, 5 skipped (`-n 4`, 718 s), wall_clock 14, rehearsal 5; ruff, recipe-check, gen-index, coverage, sync-harness `--check`, tool-budget (10 tools, 1,630 tokens), manual status, doctor (0 fail), driver-map `--check` green. Acceptance: none — offline evidence: the register test | 105 register rows, only OD21-10 open. AGENTS.md and CLAUDE.md still name `blueprint.md` the plan of record (agent text: WP30.20, D30-18). WP30.20 records the OD30/D30 outcomes; a new id needs a row (test). |
