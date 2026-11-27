# Design: plans, logs and ids

The plans this repository was built from, the work-package logs and the register of every plan id. They record why
the code is the way it is; they are frozen rationale, not a description of today. What exists now is described in
[../architecture.md](../architecture.md) and [../safety-model.md](../safety-model.md); status and milestones are in
[../roadmap.md](../roadmap.md).

| File | What | State |
|---|---|---|
| [plan-v3.md](plan-v3.md) | v3 plan: correctness before M12, a truthful module layout, docs a newcomer can follow (WP30.1–30.20) | plan of record while v3 runs |
| [progress-v3.md](progress-v3.md) | v3 work-package log, one compact row per WP | appended per WP |
| [register.md](register.md) | Every plan id (owner decisions, decisions, assumptions to verify) with its status and source; namespaces; legend of the provenance tags in code comments | kept current (test) |
| [plan-v2.1.md](plan-v2.1.md) | v2.1 plan: operator `update` and maintainer `qualify`, debug cases, step-by-step bring-up (WP21.x) | frozen (v2.1 closed at `8e0992d`) |
| [blueprint.md](blueprint.md) | v2 plan of record: whole instrument, lab-ready (M5–M12, WP5.1–11.5) | frozen at the v2 close (`0397f18`) |
| [progress.md](progress.md) | Work-package log of v1, v2 and v2.1 with acceptance results and handoff notes | frozen after v2.1 |
| v1 plan | M0–M4 plan: `git show plan-v1:docs/design/blueprint.md` (tag `plan-v1`) | frozen |
| v0.2 design | The retired 379-tool fake-MCP design: tag `archive/v0.2-fake-mcp` | archived |

## Reading them

- An id (`OD-n`, `OD21-n`, `D-n`, `KD-n`, `ATV-n`, `OD30-n`, `D30-n`, v1 `D1`–`D3`): its row in
  [register.md](register.md), which also tells apart the same-looking ids that are not plan ids (deployment steps
  `D1`–`D12`, bring-up steps, rules, scenarios).
- A provenance tag in a code comment or an older doc (`WP7.3`, `blueprint v2 §4.2`, `v2.1 plan §2.1`): the legend in
  [register.md](register.md).
- Paths under `tmp/` named in the plans and logs (briefs, research reports, repros, executor notes) were maintainer
  scratch: gitignored, never in the repository. What they settled is in the plans and logs; each v3 repro becomes a
  committed regression test in the work package that fixes it.

## Conventions (from v3 on)

- Ids `WP30.n`, `OD30-n`, `D30-n`; one commit per work package, subject `WP30.n <short title>`, the message says
  why (the detail lives there).
- One row per work package in [progress-v3.md](progress-v3.md), at most ~1,000 characters:
  `WP · commit · AC → result · deviations/handoffs`; the next work package backfills the commit cell
  "(next WP backfills)".
- Every id cited outside `docs/design/` has a register row, and no tracked file outside `docs/design/` points into
  `tmp/` (`tests/adapters/test_design_register.py`).
- New code and current docs carry no work-package or plan-section tags; existing tags stay and resolve through the
  legend.
