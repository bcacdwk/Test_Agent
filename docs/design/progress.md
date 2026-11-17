# Re-architecture progress log

Plan of record: [`docs/design/blueprint.md`](blueprint.md). Branch: `rearch/v1` (local, no pushes).
One row per work package (WP), appended when its acceptance checks pass and it is committed.
Commit subjects start with `WP<id>`; the `Commit` cell of each row is backfilled with the short hash by the next WP.

Columns: WP · Commit · AC commands and results · Deviations · ATV outcomes.

| WP | Commit | AC commands and results | Deviations | ATV outcomes |
|---|---|---|---|---|
| 0.1 Promote plan | f4598b5 | `test -f docs/design/blueprint.md` → ok; `tail -n +2 docs/design/blueprint.md \| diff - tmp/blueprint_arbitration.md` → no output (identical). pytest/ruff gate: not applicable yet (no code change; legacy suite untouched, tooling arrives in WP0.3) | none | — |
| 0.2 Archive tag | (next WP backfills) | `git cat-file -t archive/v0.2-fake-mcp` → `tag`; `git rev-parse 'archive/v0.2-fake-mcp^{commit}'` → `6bc9f3ea3c8b…` (starts with `6bc9f3e`). Tag is local; owner pushes. pytest/ruff gate: not applicable yet (tooling arrives in WP0.3) | This commit only logs the WP (the deliverable is the tag itself) | — |
