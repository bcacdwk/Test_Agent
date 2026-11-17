# Re-architecture progress log

Plan of record: [`docs/design/blueprint.md`](blueprint.md). Branch: `rearch/v1` (local, no pushes).
One row per work package (WP), appended when its acceptance checks pass and it is committed.
Commit subjects start with `WP<id>`; the `Commit` cell of each row is backfilled with the short hash by the next WP.

Columns: WP · Commit · AC commands and results · Deviations · ATV outcomes.

| WP | Commit | AC commands and results | Deviations | ATV outcomes |
|---|---|---|---|---|
| 0.1 Promote plan | (next WP backfills) | `test -f docs/design/blueprint.md` → ok; `tail -n +2 docs/design/blueprint.md \| diff - tmp/blueprint_arbitration.md` → no output (identical). pytest/ruff gate: not applicable yet (no code change; legacy suite untouched, tooling arrives in WP0.3) | none | — |
