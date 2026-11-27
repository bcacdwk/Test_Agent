> **v3 plan of record**, committed verbatim below by WP30.1 on 2026-11-27 (status final; the owner's answers are in
> §8, the decisions taken in the plan in §9). Log: [progress-v3.md](progress-v3.md); ids and their status:
> [register.md](register.md); index of the plans: [README.md](README.md). Paths under `tmp/` that it cites (research
> reports, repros, briefs) were maintainer scratch and are not in the repository; each repro becomes a committed
> regression test in the WP that fixes it.

# v3 plan: correctness before M12, a truthful module layout, docs a newcomer can follow

Arbiter, 2026-11-27, `main` @ `8e0992d` (CI green). Owner answers to §8 and orchestrator amendments applied 2026-11-27 (status: final, approved for execution on the owner's go). Inputs: `tmp/v3_orch/brief_research.md`, `research_{A,B,C}.md`,
the repros in `tmp/v3_orch/repros/` (re-run by me from a scratchpad copy against the repo on the simulator, temp
`B1500_DATA_DIR`/`B1500_CONFIG_DIR`, `-B`; tracked tree unchanged), and the repo itself. Ids in this plan: work
packages `WP30.n`, owner questions `OD30-n`, decisions taken here `D30-n` (no collision with v1 `D1–D3`, v2 `OD-n`,
v2.1 `OD21-n`/`D-n`/`KD-n`, or the bring-up steps `D1–D12`). Agent ids: [A] code/correctness, [B] docs/repo, [C]
change cost/tooling.

## 0. Summary

v3 is **moderate**: the code is in good shape (layering enforced, 94.5 % line coverage, ruff's bug rules clean); the
work is a short list of real fail-open and lifecycle bugs, two latent M12 blockers, three package moves that make
the layout tell the truth, the removal of plan-closure machinery and inventory pins that tax every change, and a
docs tree a newcomer can follow. No rewrite, no new framework, no change to the safety rules, limits, tiers, tool
surface or permission files.

- **Verified (§1):** 11 safety/lifecycle bugs re-run and confirmed (3 fail open: S-1, S-2, S-4), the digest/schema
  coupling reproduced bit-exactly (C:V3), the card-status and test-premise blockers of the first promotion confirmed
  in code (C:V1, V2), the `--affected` base bug confirmed by a dry run (B:F3). One claim downgraded (A:K-7 is
  documented design), two partly (A:A4 import time, C:V5 analysis ids).
- **Shape (§3):** new `fsio.py` (one correct atomic write/append/hash), `session/{inflight,cleanup}.py` (the safety
  core in reviewable files), `bringup/` package (four root modules), `deploy/` package (the operator path: `update`,
  `doctor`, `harness init` and the checks they call; never imports maintainer tooling), `devtools/` maintainer-only;
  one gate command that CI runs; `tests/support/`; docs: `docs/design/` holds every plan and id (register),
  `maintainer.md` and `operator.md` added, architecture as built, roadmap short.
- **WPs (§4):** 20 sequential WPs on `main` in four phases: (1) correctness and M12 readiness 30.1–30.10, then a
  phase-1 checkpoint; (2) maintainability 30.11–30.17; (3) docs 30.18–30.19; (4) one batched agent-text edit,
  closure and the only live acceptance 30.20. Every WP is pushed after its commit (OD30-2).
- **Acceptance (§5):** once, at the end: free checks on both harnesses, S1 on both (1 rep), S15 ★ 3 reps on both.
  ≈ 4.0 USD API-equivalent on Claude Code (4 sessions) and ≈ 3.7 M Codex input tokens (≈ 93 % cached, 4 sessions);
  the full suite would be ≈ 30.7 USD + 34.7 M.
- **Owner answers (§8, 2026-11-27):** OD30-1 = S1 + S15 ★ on both harnesses; OD30-2 = push after every WP (until a
  lab clone exists, then at phase ends); OD30-3 = (b) the registry keeps the recipe lists. Everything else is decided
  in §9 (veto list).

## 1. Verified findings

Status: **confirmed** (re-run or proved from code by me), **partly** (mechanism confirmed, a number or scope not),
**not reproduced** (plausible risk; fixed only where cheap and inside a WP that touches the code anyway). Repros
`r…` = `tmp/v3_orch/repros/hunt_{safety,async}/`.

| Id | Finding | Severity | Status | Evidence (my re-check) |
|---|---|---|---|---|
| A:S-1 | Unwritable fault latch: `_latch` stores the error, `_release` deletes `inflight.json`, next transaction sources with no latch and no recovery | bug, high (fail-open) | confirmed | r2: `fault latch now: None`, `inflight marker present: False`, `tx2 forced 1 V on the gate`; r2b same on the recovery path; r2c service level: re-validate `ok`, DV/WV 2 → 4; `session/transaction.py:675-683, 913-916, 940-945` |
| A:S-2 | `BaseException` in `__exit__` before `run_cleanup` (`_note_exception`/`_emit`) skips cleanup; marker still removed | bug, medium (fail-open, narrow window) | confirmed | r4: `cleanup_step events: 0`, outputs on, `inflight marker: False`, `tx2 admitted; recovery ran: False`; `transaction.py:880-882` unprotected |
| A:S-4 | Marker per state dir, lock per resource: another resource on the same `data/` recovers, finalizes and deletes a live run's marker | bug, high impact, rare trigger | confirmed | r3 (both hunts): B ran a recovery on A's live marker, A archived `aborted` while running, A ended `FileExistsError … manifest.json`; `session/session.py:166-168` vs `session/lock.py:118` |
| A:S-3 | Non-UTF-8 `fault.json`/`inflight.json` raises `UnicodeDecodeError` everywhere, `safe_shutdown` included | bug, medium (fails closed, no way out) | confirmed | r1: six raises incl. `safe_shutdown #1/#2`; `fault.py:111-116`, `transaction.py:168-173` catch `OSError` only |
| A:R-3 | Run finalized only after the transaction released; an interrupt/`OSError` in `_finish` leaves it unfinalized forever | bug, medium | confirmed | r4: manifest absent after a later transaction, `list_runs total: 0`; r7: `progress.json state: running 0/21` |
| A:R-2 | Ctrl-C while `b1500 run` waits for an async start does not cancel the run | bug, medium | confirmed | r2: worker ran 4.5 s after Ctrl-C, outcome `completed`; `catalog/executor.py:480` |
| A:R-5 | Temp name `<name>.tmp-<pid>` shared by threads | bug, medium (Windows) | confirmed, worse | r6: 300/300 concurrent pairs → `FileNotFoundError` (A reported 203); `session/lock.py:83` |
| A:R-1 | `safe_shutdown` in the same server cannot stop a sync run (service lock held for the call) | bug, low-medium | confirmed | r1: 2.33 s, `cancelled_run=None`, `completed` vs another process 0.45 s `cancelled`; r1b `service.close()` blocked 2.31 s |
| A:R-4 | SIGTERM during the stdin-closed wait deadlocks the MCP server (POSIX) | bug, low | confirmed | r5: watchdog after 12 s, main thread at `adapters/mcp_server.py:228 with guard` |
| A:R-6 | `safe_shutdown` writes the abort into the current config's state dir, not the run's | bug, low | confirmed | r8: abort in the new dir, run `completed` |
| A:C-1 | Approved summary can lose its confirm/block flags when even the compact form exceeds 400 chars | bug, latent | confirmed (synthetic) | r5: 10 SPGU channels → `soft_limit` absent; `rules/tiers.py:398` |
| A:K-4 | `OutputGuard` never compares with the 42 V / 100 mA code ceiling | risk (defence in depth) | confirmed, no live hole | r6: guard admitted 100 V / 0.5 A on a hand-made envelope; R-LIM-02 bounds envelopes at validation and run start |
| A:K-1..3 | OneDrive/AV handles outlast the ~0.3 s retry; unlocked cross-process `index`/`notes` appends, note ids from a line count; manifest written in mode `x`, not atomically | risk | not reproduced | `lock.py:87-109`, `archive/store.py:134-137, 277-281, 329`; the lab clone is already documented outside OneDrive (`C:\b1500\test_agent`, `steps.yaml:39`) |
| A:K-5,6,8,10,11 | `fault clear` races a shutdown; unverified recovery drops the crashed run id and auto-cal restore; malformed index line fails later runs; `ConfigLoader` not thread-safe; double Ctrl-C | risk | not reproduced (code read) | as A cites; fixed inside 30.4/30.6/30.7 |
| A:K-7 | `lop_positive_control` returns its first result | — | not a bug | documented: one positive control per transaction proves `LOP?` is a meaningful verification (`transaction.py:716-721`) |
| A:K-9 | Plan TTL outside the plan hash | debt | confirmed, kept | `catalog/planner.py:87`; `data/**` deny rule holds; changing plan-id semantics is not worth the risk |
| C:V3 | Recipe definition digest is a Pydantic dump: a schema change orphans every reviewed record | bug, latent, **M12-critical** | confirmed | reproduced: `mosfet.idvg` `272b81e6d0fc3bf9` → `5804f5268f42ba8c` after adding one defaulted field (`create_model`), file untouched; `models/validation.py:579-584` |
| C:V1 | Card status must equal each recipe's status: partial promotion of a card fails lint | bug, latent (first promotion) | confirmed | `devtools/skills/cards.py:193-195`; 21/34 cards hold ≥ 2 recipes |
| C:V2 | A legitimate promotion breaks 17 tests in 9 files, one a safety test whose premise is `first_hw_run` | bug, latent | partly | mechanism confirmed: `tests/safety/test_refusals_open_no_bus.py:72-73`, `tests/visa_loop/test_recipes.py:79`, tripwire `tests/unit/test_recipe_check_promotion.py:147`; the count is C's E2, not re-run |
| C:V4 = B:F4 | `PLAN_TOTALS` (68/14/33) gates every recipe/kind/card change | debt | confirmed | `devtools/coverage.py:59-66, 446-448` |
| B:F3 | `--affected` takes a qualify report as its base | bug (tooling) | confirmed | dry run today: base `16fff04` (`…2.1.332-qualify.md`) → 0 scenarios; `selection.py:50, 126-133` |
| B:S1 | A partial batch report becomes the base for every scenario | bug (tooling) | partly | by code: `max(date, version)` picks `2.1.328-v21` (6 scenarios) over the full 11-26 report |
| C:V6 | Generated card index in 13 scenarios' `touches` → one recipe selects 16/18 scenarios | cost | confirmed | 13 scenario files list `cards/README.md` |
| C:V5 | `analysis/registry.py` hard-codes 51 recipe ids | debt | partly | `:98-136`; `generic.*` patterns already admit generic recipes; recipe-check names the missing entry |
| C:V7 | `sim_validated` is self-declared; no gate ties it to a model-truth test | risk | confirmed | `docs/architecture.md:128-129` vs no check |
| C:V8 | Inventory pins restate committed data (recipe→card dicts, stage lists, `68 loaded`, §3 lists) | debt | confirmed | e.g. `tests/adapters/test_cli_recipe_check.py:36` |
| C:V9 | `AnalysisMethod.milestone` read by no product code | noise | confirmed | only `analysis/registry.py` + tests |
| C:R3 | Driver-map ledger closed (0 open) but still a 1,733-line generator + 471-line test in the gate | debt | confirmed | `scripts/build_driver_map.py`, `tests/unit/test_driver_map.py` |
| C:V10 | `HarnessName` defined 3×, per-harness facts in scattered dicts | debt | confirmed | `devtools/harness.py:38`, `harness_versions.py:39`, `acceptance/transcripts.py:48` |
| B:F6 = C:V11 | Gate written three ways; AGENTS' gate runs wall-clock tests among workers | risk | confirmed | `AGENTS.md` gate vs `.github/workflows/ci.yml` (wall_clock alone, rehearsal serial, `manual status`, `doctor`) |
| C:V12 | Python bounds twice, no `.python-version` | noise | confirmed | `devtools/doctor.py:99` |
| B:F1 | Ids and the v2.1 plan defined only in gitignored `tmp/` | risk | confirmed | "v2.1 plan" 98× in 86 tracked files, `OD21-` 63×; `stages/l6-cmu.md:127` cites open OD21-10, defined only at `tmp/v2_orch/plan_v21.md:529` |
| B:F2 | Three "D" id namespaces | noise | confirmed | v1 D1–D3, v2.1 D-1…11, steps D1–D12 |
| B:F5 | Hand-kept knowledge index misses two sections | drift | confirmed | no link to `06b…#pund`, `10…#pund-program-read…` |
| B:F7 | Doc tests pin stale prose/one-off sizes | debt | confirmed | `tests/adapters/test_docs_commands.py:311` ("98 wheels", "81 MB" …) |
| B:F8–F10 | `progress.md` 377 KB table; architecture defers to the stale blueprint; status in three places | debt | confirmed | 376,804 bytes; `docs/architecture.md:5-6`; README "Status (2026-11-26)" |
| B:F13 | No release tags; versions read `plan-v1-78-g…` | noise | confirmed | tags: `archive/v0.2-fake-mcp`, `plan-v1` |
| B:F14 | Entry skill description lists v1 examples | noise | confirmed, no action | triggering proven (S11/S13/S18 pass); file at 8,999/9,000 bytes |
| A:A3 = C:R8 | Operator path imports maintainer code | debt/risk | confirmed, wider | `devtools/update.py:52-53` (acceptance.harnesses, mcp_smoke), `doctor.py:51` (budget, sync_harness), `adapters/cli/bringup.py:31-32` (doctor, update.agent_markers) |
| A:A4 | CLI imports everything eagerly | cost | partly | after `import …adapters.cli`: `matplotlib` and `devtools.acceptance.runner` loaded; 0.8 s warm here (A: 2.1 s cold) |
| A:A6 | `catalog/__init__` re-exports `Executor` → 8-module eager cycle; kinds import order hand-kept | debt | confirmed | `catalog/__init__.py:8`; `catalog/kinds/__init__.py` `# isort: skip` |
| A:A7 | `session/transaction.py` 951/1,000 lines: marker + cleanup + lifecycle | debt | confirmed | `wc -l`; the S-1/S-2 fixes would push it over the limit |
| A:A2 | Four bring-up modules (2,573 lines) at the package root with 4 rank + 4 ONLY rows | debt | confirmed | `tests/unit/test_import_layering.py:52-82` |
| A:§1.4 | 13 dead definitions, ~15 duplicated kind helpers, `max_limited_fraction_in_fit` honoured by 1 of 57 methods | debt | accepted from A (scan not re-run) | A §1.4 |
| A:T1,T3 | 33 test modules used as libraries across directories; `_clean_env` copied into 4 conftests, absent from 6 dirs | debt/risk | confirmed (`_clean_env` ×4) | `tests/{unit,integration,adapters,visa_loop}/conftest.py` |

Promises the hunts verified as holding (cleanup order and survival, latch semantics, no vacuous checks, guard
before every write, raising rule = block, OS lock, hash-verified plans, visa never reads examples) are listed in A
§1.1 and are regression targets of every safety WP.

## 2. Principles (they decide future questions)

1. **Fail closed, fix first.** Safety and lifecycle bugs before structure. Every fix lands with its repro as a
   regression test. Rules, limits, tiers, guard, cleanup, latch, audit, the 10 tools and the human-only commands are
   never weakened; tests are never weakened to make something pass (a deleted pin names the check that covers it).
2. **Moderate means earned.** A change must remove a proved defect, a real coupling or a recurring cost. Pure moves
   are separate commits from behaviour changes. No shims, no framework, no rewrite for its own sake.
3. **One fact, one home.** Derive and generate; tests assert rules and invariants, not inventories; a restated fact
   is allowed only where a lint checks both sides (card ↔ recipe).
4. **Everything resolves in the repo.** Plans, decisions and ids live in `docs/design/`; no tracked file points into
   `tmp/`. New ids use version-prefixed namespaces.
5. **Current docs describe the present.** History lives in `docs/design/` and git; new code, comments and docs carry
   no WP or plan-section tags (existing ones stay, explained by the register's legend).
6. **Audience first.** Operator, owner, maintainer/developer and agent each have one entry point (§3.4).
7. **Data for content, reviewed code for behaviour, a fixed safety core.** Recipes, cards, knowledge, steps,
   scenarios, sim scenarios are data; kinds, methods, rules, devices are registered code (explicit tables); the
   safety core is never pluggable. A module is plugged out at run time by the station profile, not by code.
8. **Operator path isolated.** What a lab user runs (`update`, `doctor`, `harness init`, MCP server, CLI) never
   imports maintainer tooling.
9. **Hardware evidence is precious.** Anything that would orphan a reviewed record or block a promotion lands
   before M12.
10. **Acceptance is evidence, not ritual.** Agent-read text changes once per release; live acceptance once, at the
    end, chosen by what changed; offline graders and free checks first; a passed scenario is done.

## 3. Target structure

### 3.1 Code (changes only; everything else stays)

```text
src/b1500_test_agent/
  errors.py, paths.py, config.py       unchanged (config: ConfigLoader lock)
  fsio.py                     NEW rank 1: atomic_write_json (unique mkstemp temp, ~2 s Windows retry), remove_file,
                              append_line (filelock), sha256_file, host_name
  models/                     leaf, unchanged (station.py split deferred until the size test forces it)
  transport/, driver/         unchanged except driver/guard.py (ceiling check)
  session/
    inflight.py               NEW: InflightMarker, read/write, inflight-<resource-slug>.json, legacy marker
    cleanup.py                NEW: run_cleanup, its steps and verification, CleanupOutcome (moved)
    transaction.py            lifecycle only (≤ ~650 lines); lock.py = InstrumentLock + resource_slug only
  catalog/                    __init__ without Executor/Planner re-exports; kinds/_smu_common.py, _wgfmu_common.py
  rules/, archive/, analysis/, manuals/, service/   fixes only (summary flags, atomic/locked archive, lazy plots)
  bringup/                    NEW package from bringup.py, bringup_ledger.py, bringup_verify.py, bringup_steps.py
  deploy/                     NEW (operator path): update, doctor, harness, harness_versions (one HarnessProfile
                              table), mcp_smoke, budget, sync_harness, project-trust checks
  devtools/                   maintainer only: acceptance/, skills/, gate (NEW), coverage, recipe_check,
                              harness_qualify, cases, sim_console
  adapters/                   cli (dev group imported lazily), mcp_server (shutdown hook fixes)
```

Layering after v3 (`tests/unit/test_import_layering.py` is the source): `adapters → {deploy, bringup, devtools} →
service → {catalog, rules, archive, analysis, manuals} → session → driver → transport`; `models`, `errors`, `paths`,
`fsio` are leaves (`fsio` imports only models/errors); `deploy` never imports `devtools` or `adapters`;
`devtools` may import `deploy`; `bringup` ONLY service, models, fsio with the internal chain ledger ← verify ←
steps; fastmcp only in `adapters/mcp_server.py`, `deploy/` and `devtools/` (as today for devtools). Name `deploy`,
not A's `ops`: `driver/ops/` already exists.

### 3.2 Tests

`tests/{unit,integration,safety,sim,visa_loop,adapters,skills,acceptance,wgfmu_abi,hardware,fixtures}` unchanged as
tiers; NEW root `tests/conftest.py` (`_clean_env` once), NEW `tests/support/` (shared helpers; no test imports a
`test_*` module, cross-directory imports only via `tests.support`, a lint test enforces it), NEW `tests/README.md`.
Markers unchanged plus `sim_truth("<recipe id>")`. Inventory pins replaced by derived invariants (30.13); every
safety pin kept (§7). Fast iteration subset: `uv run b1500 dev gate --quick` (unit, sim, safety, wgfmu_abi + checks).

### 3.3 Dev tooling, CI, the gate

One source of truth: `uv run b1500 dev gate` runs exactly today's CI sequence (parallel tests without wall_clock and
rehearsal; wall_clock alone; rehearsal serial; ruff; recipe-check; lint-skills; gen-index/coverage/sync-harness
`--check`; tool-budget; manual status; doctor), every step even after a failure, one PASS/FAIL line each.
`.github/workflows/ci.yml` runs that command (log groups per step); AGENTS, README and `maintainer.md` name it and
nothing else. `uv run b1500 dev regen` refreshes every generated file (gen-index → coverage `--write` →
sync-harness). Kept: recipe-check, lint-skills (its `card_status` rule becomes "lowest of the recipes"), gen-index (+ knowledge
section index), coverage (minus plan totals and ledger counts), sync-harness, tool-budget, mcp-smoke, acceptance
runner + qualify (selection fixed), cases, sim-console. Retired: driver-map builder and its test.

### 3.4 Docs tree and reading order

```text
README.md            what · status (≤ 5 lines → roadmap) · quick start · where to start by audience · docs table
AGENTS.md, CLAUDE.md agent instructions (AGENTS edited once in 30.20; CLAUDE.md unchanged)
docs/
  operator.md        NEW daily use at the lab PC (≤ ~90 lines; deployment Step 12 + end of day moved here)
  deployment-windows.md  one-time lab-PC setup (anchors kept: Harness permissions, Offline wheelhouse, Steps 10/11)
  hardware-bringup.md    M12 bring-up overview (unchanged)
  architecture.md    as built: per package owns · key files · extension point · tests; layering = the test
  safety-model.md    content unchanged; WP/status narration removed
  maintainer.md      NEW gate/regen, generated files, how we work, acceptance/qualify policy, extension cookbook,
                     upkeep (harness, Python, deps, firmware/WGFMU library, manual corpus), harness contract
  manuals.md         unchanged
  roadmap.md         ≤ ~130 lines: milestone table, M12 (test-checked table), v3, next
  coverage.md, open-questions.md   GENERATED, no history lines
  acceptance/        README + dated reports (location and names unchanged)
  design/            README (what is here, frozen plans, id legend) · register.md (every id) · blueprint.md (v2,
                     frozen) · plan-v2.1.md · plan-v3.md · history.md (roadmap result tables) · progress.md (frozen
                     v1–v2.1) · progress-v3.md (compact rows)
tests/README.md, recipes/README.md, config/README.md   NEW signposts (≤ 30–40 lines, pointers only)
```

Reading order — **operator**: README → `operator.md` → (first time) `deployment-windows.md` → `hardware-bringup.md`.
**Owner**: README → `roadmap.md` → `open-questions.md` → `design/register.md` (open decisions). **Maintainer**:
README → `architecture.md` → `safety-model.md` → `maintainer.md` → `tests/README.md` → nested `AGENTS.md` of
driver/analysis/transport-wgfmu → `design/README.md` for why. **Agent**: AGENTS/CLAUDE → skills.

### 3.5 Skills and knowledge

Unchanged layout (the best-curated text in the repo; acceptance-proven). Only: the knowledge README's section list is
generated (`gen-index`), two runbook `sources:` lines follow the moved cleanup/marker code, card `status:` stays (its
lint rule changes). Entry `SKILL.md`, the three skill descriptions, cards, stages and `steps.yaml` are not edited.

### 3.6 Conventions written into `maintainer.md` (and `design/README.md` legend)

v3 ids `WP30.n`/`OD30-n`/`D30-n`; progress rows ≤ ~1,000 chars (`WP · commit · AC → result · deviations/handoffs`),
detail in the commit message ("the message says why"); no WP/plan tags in new code or current docs; every cited id
has a register row (test); code-comment legend: `WPn.m` → progress row, `blueprint v2 §` → `design/blueprint.md`,
unversioned `blueprint §` → v1 plan (`git show plan-v1:docs/design/blueprint.md`; ambiguous in v2-era files),
`v2.1 plan §` → `design/plan-v2.1.md`; existing tags are not swept.

## 4. Work packages

Rules for every WP (v2.1 precedent, D30-1): sequential in the main checkout on `main`; one commit `WP30.n <title>`
whose message says why; row in `docs/design/progress-v3.md` (the next WP backfills the commit); every AC command run
literally; **gate** = the CI step list of `.github/workflows/ci.yml` run locally until 30.16, then
`uv run b1500 dev gate` (iterate with `--quick`, finish with the full gate once); no live harness session except the
free checks named and 30.20; each progress row states "acceptance: none — offline evidence: …". Throw-away clones
for experiments live in the session scratchpad (`git clone`, `uv sync --frozen --offline`), never in the repo. The
orchestrator pushes `main` after each WP's commit and checks CI on both OS before the next push (OD30-2); a Windows
failure is fixed in the next commit (`WP30.n fix`). Once a lab clone exists (deployment D6 done), pushes happen only
at phase ends.
Sizes: S ≤ ½ day, M ≈ 1 day, L > 1 day of agent work (changed lines indicative).

### Phase 1 — correctness and M12 readiness

| WP | Deps | Scope and files | AC (literal) | Tests · docs | Acceptance | Size |
|---|---|---|---|---|---|---|
| **30.1 Plan of record and resolvable history** | owner answers (§8) | `docs/design/plan-v3.md` (this plan + owner answers + header), `plan-v2.1.md` (`tmp/v2_orch/plan_v21.md` verbatim + header), `register.md` (one row per id: v1 D1–D3, ATV-1…12; v2 OD-1…7, ATV-13…32; v2.1 OD21-1…11, KD-1…8, D-1…11, ATV-33…40; v3 OD30/D30 — id · one-line statement from its source · status (open/resolved/settled at step) · defined in; namespace note; code-comment legend §3.6), `design/README.md`, `blueprint.md` header line "frozen at the v2 close; as built: architecture.md", `progress.md` row 129 backfilled (`8e0992d`) + frozen line, `progress-v3.md`, `devtools/skills/questions.py` header → register (regen `docs/open-questions.md`), `config/harness/validated.yaml:1` comment → `plan-v2.1.md`, `.gitignore:29` comment, `scripts/README.md` "Planned scripts" deleted | `uv run pytest -q tests/adapters/test_design_register.py` (every `OD-`, `OD21-`, `OD30-`, `KD-`, `D-n`, `D30-`, `ATV-` id cited in tracked files outside `docs/design/` has a register row; no `tmp/v<n>_orch` path outside `docs/design/`; a fixture with an unknown id fails); `uv run b1500 dev gen-index --check`; `uv run b1500 dev lint-skills`; gate | new test · the files named | none (no agent-read text) | M |
| **30.2 File I/O primitives** | 30.1 | NEW `fsio.py` (§3.1; temp suffix `.tmp` never matches a state glob); `session/lock.py` keeps lock + slug; importers migrated (`archive/{corrections,runfiles,store}.py`, `catalog/planner.py`, `session/{abort,fault,transaction}.py`) and the five sha256 copies (`analysis/dataset.py`, `bringup_verify.py`, `devtools/acceptance/runner.py`, `manuals/catalog.py`, `service/evidence.py`); `archive/store.py`: index/notes appends via `append_line`, note ids not from a line count, manifest published atomically and exclusively; `devtools/doctor.py` WARN when the clone is inside a synced folder (OneDrive, Dropbox, iCloud/CloudStorage); layering row `fsio` | `uv run pytest -q tests/unit/test_fsio.py tests/integration/test_archive_concurrency.py tests/unit/test_import_layering.py`: r6 as a test (300 concurrent `AbortFile.request` pairs, 0 exceptions); `os.replace` raising `PermissionError` for 1 s still succeeds; two processes × 500 notes → 1,000 well-formed lines, unique ids; a crash injected before the manifest publish leaves no manifest and a later finalize succeeds; `uv run b1500 doctor` shows the synced-folder WARN on the Mac clone; gate | tests; Windows branches by platform injection · `deployment-windows.md` clone row (one sentence) | none | M |
| **30.3 Session seam (pure move)** | 30.2 | NEW `session/inflight.py`, `session/cleanup.py` (§3.1); `transaction.py` lifecycle only; importers and `session/__init__` exports updated (no shim modules); `driver/AGENTS.md` file references | `git diff -M --stat HEAD~1` shows moves and import lines only (reviewer confirms no logic line changed); `wc -l src/b1500_test_agent/session/transaction.py` ≤ 650; `uv run pytest -q tests/safety tests/unit/test_session.py`; gate | none new · `driver/AGENTS.md` | none | S |
| **30.4 Fail-closed transaction exit** | 30.3 | `session/{transaction,inflight,fault,session}.py`: `__exit__` defers `BaseException` across note, emit, cleanup and latch, re-raises after; the marker is removed only after a verified cleanup or a durably written latch; a latch-write failure keeps the marker, sets an in-process latch on the `Session` (refuses sourcing) and reports `latched_fault: False` with the error (no false "latch is set" text); `UnicodeDecodeError`/`ValueError` on `fault.json` → latched, on a marker → corrupt (recovery runs); `safe_shutdown`, `fault clear`, `lock status` work with corrupt state files; the crashed run id and pending auto-cal restore survive an unverified recovery (K-6) | `uv run pytest -q tests/safety/test_fail_closed_exit.py` = r1, r2, r2b, r2c, r4 as tests: the next transaction recovers, refuses when unverified, never sources (DV/WV count unchanged); `safe_shutdown` succeeds on a non-UTF-8 `fault.json` and marker; the T6 branches (latch-write failed, unreadable files) covered; `uv run pytest -q tests/safety`; gate | new test · `safety-model.md` latch paragraph (behaviour, no history) | none (runbook `cleanup-failed-fault` stays true) | M |
| **30.5 One in-flight marker per resource** | 30.4 | `session/inflight.py` (`inflight-<lock slug>.json`), `session/session.py`, `catalog/running.py` (`_finalize_orphan` only for its own resource), `service/status.py`, `devtools/doctor.py` (lists every marker); legacy `inflight.json` recovered only by the resource it names, else reported by `station_status`/`doctor`; the fault latch stays station-wide | `uv run pytest -q tests/safety/test_inflight_per_resource.py` = r3 (both hunts): a second resource on the same data dir neither recovers, finalizes nor deletes the live run's marker; legacy-marker tests (named resource recovers, other reports); `station_status` keys unchanged for one resource (test); gate | new test · `safety-model.md`, `architecture.md` one line each | none | M |
| **30.6 Run lifecycle under interrupts** | 30.5 | `catalog/executor.py` (`BaseException` around `wait_started` → abort the job, then re-raise; `_finish` `BaseException`-safe, finalizes aborted/failed, `control.finish` in `finally`; empty run folder discarded on a pre-transaction failure; malformed index lines skipped), `catalog/corrections.py` (`record_run` records `OSError`), `session/runner.py`, `adapters/cli/core.py` (double Ctrl-C, K-11) | `uv run pytest -q tests/integration/test_run_lifecycle_interrupts.py` = r2, r4, r7, K-8: every started run has a manifest and an index line; `progress.json` never left `running`; Ctrl-C during start ends `cancelled` with the worker stopped; a malformed index line fails no later run; `uv run pytest -q tests/integration/test_async_cancel.py tests/safety/test_async_matrix.py tests/safety/test_async_recovery.py`; gate | new test · executor docstring | none (S15 in 30.20) | M |
| **30.7 Shutdown paths** | 30.6 | `service/{shutdown,core}.py` (abort written to the active job's own abort file before the service lock; R-6), `catalog/{executor,running}.py` (sync runs register a `RunControl` the hook can abort; R-1), `adapters/mcp_server.py` (non-blocking hook guard + stopping flag; R-4), `session/fault.py` (`clear` under the instrument lock, compare-and-delete on `set_at`; K-5), `config.py` (`ConfigLoader` lock; K-10) | `uv run pytest -q tests/integration/test_shutdown_paths.py tests/adapters/test_mcp_shutdown_hook.py` = r1, r1b, r5, r8, K-5: same-process `safe_shutdown` cancels a sync run within one checkpoint; the hook aborts a sync run; SIGTERM after stdin EOF exits ≤ wait + 1 s (POSIX; skipped on Windows); the abort lands in the run's state dir after a data-root change; a latch set between shutdown and clear survives; `uv run b1500 dev mcp-smoke --config .mcp.json --async` passes (free); gate | new tests · `safety-model.md` shutdown paragraph | S15 in 30.20 | M |
| **30.8 Consent summary and guard ceiling** | — | `rules/tiers.py` (`plan_summary` shortens channels to `+N ch` before it touches head, mode or flags; flags never cut), `driver/guard.py` (`min(envelope, HARD_CEILING_*)` of `models/policy.py` for the quantities R-LIM-02 bounds) | `uv run pytest -q tests/unit/test_summary_flags.py tests/safety/test_guard_ceiling.py tests/integration/test_plan_goldens.py`: r5 (flags present at 400 chars), r6 (guard refuses 100 V / 0.5 A on a hand-made envelope); every shipped recipe's summary byte-identical (goldens unchanged); gate | new tests · `safety-model.md` one line | none (summaries unchanged) | S |
| **30.9 Schema-independent recipe digest** | — | `models/validation.py` `recipe_definition_sha256` = canonical JSON of the recipe file's parsed YAML mapping minus `DEFINITION_EXCLUDED` (the registry keeps the mapping); callers `devtools/recipe_check.py`, `bringup` record; `validation/hw/README.md` | `uv run pytest -q tests/unit/test_recipe_digest.py tests/unit/test_recipe_check_promotion.py`: E3 as a test (a defaulted field added to `Recipe` leaves every committed recipe's digest unchanged); editing a role/param/quality/analysis key or `version` changes it; status/provenance/card edits do not; `uv run b1500 dev recipe-check`; gate | new test · `validation/hw/README.md` | none | S |
| **30.10 Promotion-ready status and tests** | 30.9 | `devtools/skills/cards.py` `card_status`: card status = lowest status of its recipes (draft < sim_validated < hw_validated; D30-8); visa-loop tests derive tier and `first_hw_run` from the recipe status; `tests/safety/test_refusals_open_no_bus.py` forces a confirmation reason that survives promotion (soft-limit parameter or `always_confirm` fixture) so every runnable recipe keeps its refusal case; recipe-check test clones copy `validation/hw/`; status pins → rule asserts (three statuses; `hw_validated` ⇔ reviewed record); the "no hardware record" tripwire's docstring names its retirement at the first record | throw-away clone: **E2** (card `smu/mosfet-idvg`, four recipes `hw_validated`, synthetic reviewed records built as `tests/unit/test_recipe_check_promotion.py` builds them, `gen-index`/`coverage --write`/`sync-harness`) → `uv run b1500 dev lint-skills`, `uv run b1500 dev recipe-check` clean, `uv run pytest -q -m "not hardware and not acceptance and not wall_clock and not rehearsal" -n auto` fails only the tripwire; **E2a** (only `mosfet.idvg` promoted) → same; the refusal test still runs its unconfirmed-plan case for promoted recipes; in the repo: gate | tests named · `hardware-bringup.md` "a promotion edits the recipe and adds its record" | none | M |
| ~~30.10a Recipe-declared analysis methods~~ (dropped: OD30-3 = b) | 30.10 | C P4: `analysis.allowed` in each recipe (one-off migration script, not committed), methods keep `kinds`/`families`; `models/recipe.py`, `analysis/registry.py`, `catalog/registry.py`, `service/runs.py`, `devtools/skills/cards.py`, ~20 test call sites | committed test: the (recipe × method) applicability matrix equals the pre-migration fixture; `analysis/registry.py` names no recipe id (grep); recipe-check clean; gate | test · cookbook | none | M |

**Checkpoint (end of phase 1):** gate green and CI green on both OS for the last phase-1 push before 30.11. This is
the minimum the lab PC should run at M12.

### Phase 2 — maintainability

| WP | Deps | Scope and files | AC (literal) | Tests · docs | Acceptance | Size |
|---|---|---|---|---|---|---|
| **30.11 Acceptance selection correctness** | phase 1 | `devtools/acceptance/selection.py`: per-scenario base = commit of the newest report of that harness in which the scenario met its threshold (qualify and partial reports count only for scenarios they passed; never passed → always selected); 13 scenario `touches`: `cards/README.md` → `src/b1500_test_agent/devtools/skills/index.py`; test: every `touches` glob and `GLOBAL_TOUCHES` entry matches a tracked file; `docs/acceptance/README.md` §affected | `uv run pytest -q tests/acceptance/test_selection_base.py tests/acceptance/test_scenarios_suite.py`; `uv run b1500 dev acceptance run --harness claude --affected --dry-run` names a base per scenario (S3, S7, S10, S12, S13 from the `-v21` report, never a qualify report); a renamed touched file fails the glob test (fixture); gate | tests · acceptance README | none | S-M |
| **30.12 Retire plan-closure machinery** | 30.11 | `devtools/coverage.py` (drop `PLAN_TOTALS`/`PLAN_NOTES`, the "Against blueprint" line, ledger counts; every real gap check stays), `analysis/registry.py` (drop `milestone`/`Milestone`), delete `scripts/build_driver_map.py` and `tests/unit/test_driver_map.py`, `references/driver-map/README.md` "frozen at the v2.1 close; method names may have changed", `scripts/README.md`, `ci.yml` comment, regen `docs/coverage.md`, the 7 milestone-asserting tests | `git grep -n -e PLAN_TOTALS -e PLAN_NOTES -e milestone -e build_driver_map -- src tests scripts .github` empty; `uv run b1500 dev coverage --check`; `uv run pytest -q tests/integration/test_coverage.py` (a test per real gap class); gate | tests · coverage.md (gen), driver-map README | none | S-M (−2.3 k lines) |
| **30.13 Invariants instead of inventory pins** | 30.12 | delete restated data: `test_catalog_registry.py` recipe→card dict and per-WP status lists, `test_cards.py` `CARDS`/`STAGE_OF`/`RECIPE_STAGES` (keep the S1/S10 example-plan pins), `test_bringup_stages.py` `WRITTEN`/`RECIPES`, the four `test_*_closure.py` §3 lists (behavioural asserts kept), `68`/`14`/`34` literals; add marker `sim_truth("<recipe id>", …)` on the integration tests that compare with model truth + `tests/unit/test_sim_truth_coverage.py` (AST scan: every `sim_validated` recipe is named by a marker); missing truth tests written (> 5 missing → stop and report first) | throw-away clone **E1** (`mosfet.idvg_lowvd` = copy of `mosfet.idvg` on card `smu/mosfet-idvg`, stage L4, registry line if OD30-3 = b) → only `test_every_runnable_recipe_has_a_visa_loop_case`, the refusal-matrix case of `mosfet.idvg_lowvd` and `test_sim_truth_coverage` fail; progress row lists, per deleted assertion, the check that covers it; gate | tests | none | M |
| **30.14 Package layout: `bringup/`, `deploy/`** | 30.13 | `bringup/` from the four root modules (split `bringup.py` at propose/status vs capture/record; ledger lock via `filelock`); `deploy/` = `update`, `doctor`, `harness`, `harness_versions`, `mcp_smoke`, `budget`, `sync_harness` + the trust checks from `devtools/acceptance/harnesses.py`; layering rows (§3.1); importers (~30 src/test files); `GLOBAL_TOUCHES` path; S17 `touches`; `b1500 dev --help` text; nested AGENTS references | `uv run pytest -q tests/unit/test_import_layering.py tests/acceptance/test_s17_bringup.py tests/acceptance/test_scenarios_suite.py tests/adapters/test_update.py`; `uv run pytest -q -m rehearsal`; `uv run b1500 doctor` and `uv run b1500 bringup status` outputs equal to before (saved, diffed, timestamps aside); `git diff -M --stat` moves + imports only; gate | layering test | none (S17 offline graders + rehearsal) | M |
| **30.15 Code hygiene** | 30.14 | lazy matplotlib inside plot functions (`analysis/{plots,noise,pund,cv,qscv}.py`); `adapters/cli` imports the `dev` group's modules in command bodies; `catalog/__init__` drops `Executor`/`Planner` re-exports (17 importers) and the kinds `# isort: skip` order if the fresh-import test passes; the 13 dead definitions deleted; `catalog/kinds/_smu_common.py`, `_wgfmu_common.py` for the duplicated helpers; `max_limited_fraction_in_fit` honoured by every window-fitting method via `Rows.limited_warning` (D30-11) | `uv run pytest -q tests/unit/test_lean_imports.py tests/unit/test_fresh_imports.py` (after `import b1500_test_agent.adapters.cli` and `…adapters.mcp_server` neither `matplotlib` nor `b1500_test_agent.devtools.acceptance` is in `sys.modules`; each package imports alone in a fresh interpreter); `uv run pytest -q tests/integration/test_plan_goldens.py tests/integration/test_data_goldens.py` unchanged or each changed golden justified in the row; A's dead-code scan (`tmp/v3_orch/repros/deadcode.py`, paths fixed) → 0; a limited-fraction test per window method; gate | tests · knowledge text now true | none (warnings only above 5 % limited) | M |
| **30.16 One gate, one regen, harness profile** | 30.15 | `devtools/gate.py` + `b1500 dev gate [--quick]` and `b1500 dev regen` (§3.3); `ci.yml` runs the gate as its check step; test: `ci.yml` calls the gate and repeats no gate step; one `HarnessName` + one `HarnessProfile` table in `deploy/harness_versions.py` (label, executable, install method, package, config template, generated config, permission file, skills dir, instruction file) read where the difference is data (`deploy/{harness,update,doctor}.py`, `devtools/{harness_qualify,acceptance/harnesses,acceptance/transcripts}.py`); `.python-version` = 3.12; doctor reads the Python bounds from `pyproject.toml` | `uv run b1500 dev gate` exit 0 with one PASS line per step; `uv run b1500 dev gate --quick` (time in the row); `uv run b1500 dev regen` twice → `git status` clean after the second; `git grep -n "HarnessName = " -- src` → 1 line; `uv run b1500 dev harness qualify --up-to 0` PASS on both harnesses (free); offline harness/update/qualify/acceptance tests unchanged | tests · (maintainer.md in 30.19) | none (runner exercised live in 30.20) | M |
| **30.17 Test support package** | 30.16 | root `tests/conftest.py`; `tests/support/` (helpers from 33 test modules; `rules_factory` + `rules_factory_v2` → `plans.py`); lint test; `tests/README.md` (folders, markers, gate selections, goldens and how to regenerate them) | `git grep -nE "from tests\.[a-z_]+\.test_" tests` empty; `uv run pytest -q tests/unit/test_test_imports.py`; gate pass count = before + new − deleted (numbers in the row) | lint test · `tests/README.md` | none | M |

### Phase 3 — docs

| WP | Deps | Scope and files | AC (literal) | Tests · docs | Acceptance | Size |
|---|---|---|---|---|---|---|
| **30.18 Status, history, doc tests** | 30.17 | README (status ≤ 5 lines → roadmap; "Where to start" by audience; docs table by audience, `design/` last); `docs/roadmap.md` ≤ ~130 lines (milestone table M0–M12, v2.1, v3; M12 section with its test-checked table; next); M0–M11 and v2.1 result tables moved verbatim to `docs/design/history.md`; doc tests: wheelhouse size literals dropped, `FIRST_SESSION` cut to the D-id order and key commands, roadmap M11-row check dropped, README totals computed from the registry; structural checks kept | `uv run pytest -q tests/adapters/test_docs_v2.py tests/adapters/test_docs_commands.py`; a reworded deployment sentence (scratch edit, reverted) fails nothing; `wc -l docs/roadmap.md` ≤ 130; moved tables identical (diff); `uv run b1500 dev lint-skills`; gate | doc tests · README, roadmap, history | none | S-M |
| **30.19 As-built docs and guides** | 30.18 | `architecture.md` as built (§3.4; ≤ ~26 KB; "authoritative: this page + safety-model; plans in design/ are frozen rationale"); NEW `maintainer.md` (§3.3 gate/regen; generated files: file → generator → check; how we work; acceptance/qualify policy; cookbook per extension — recipe, card, analysis method, rule, kind, sim device, bring-up step, harness — with the files after v3; upkeep: harness release = qualify, Python, deps `uv lock --upgrade` → gate → visa-loop + fake ABI → qualify T1 both → commit, firmware/WGFMU library change = compare `doctor --probe` identity with the reviewed records and repeat the named stages, manual corpus rebuild; "Supporting a coding harness" contract; conventions §3.6); NEW `operator.md`; `recipes/README.md`, `config/README.md`; WP/status narration out of `safety-model.md`, `acceptance/README.md`, `deployment-windows.md`, `manuals.md`, `hardware-bringup.md`; test: no `WP\d+\.\d+` in README and `docs/*.md` except roadmap and generated pages | `uv run pytest -q tests/adapters/test_docs_current.py tests/adapters/test_docs_commands.py tests/adapters/test_docs_v2.py` (new files under the command/path lint); `grep -c "WP[0-9]" docs/architecture.md` → 0; `wc -c docs/architecture.md` ≤ 26000; deployment anchors and Step 10/11 headings unchanged (tests); gate | new test · the docs named | none | M-L (text) |

### Phase 4 — agent-read text, closure, acceptance

| WP | Deps | Scope and files | AC (literal) | Tests · docs | Acceptance | Size |
|---|---|---|---|---|---|---|
| **30.20 Agent text, closure, acceptance** | 30.19 | ONE batched agent-read edit: `AGENTS.md` developer section (history/plans → `docs/design/README.md` + `maintainer.md`; layering line with `deploy`, `bringup`, `fsio`; fastmcp line = the test; gate → `uv run b1500 dev gate`, regen; generated files incl. `docs/open-questions.md` and the knowledge index); `devtools/skills/index.py` generates the knowledge README's section list (restores the two missing sections); runbook `sources:` (`cleanup-failed-fault` + `session/cleanup.py`, `async-run-interrupted` + `session/inflight.py`); `tests/skills/test_agent_instructions.py`; `sync-harness`; CLAUDE.md, entry SKILL.md, cards, stages unchanged; version 3.0.0 (`pyproject.toml`, `__init__.py`, `uv lock --offline`, root entry only); closure: roadmap v3, README status, register OD30/D30 rows, progress; §5 acceptance from the main checkout with a clean `git status`; reports committed; annotated tags `v2` (last commit before WP21.1), `v2.1` (`8e0992d`), `v3`; push | `uv run b1500 dev gate`; `uv run b1500 dev lint-skills` (always-loaded ≤ 2,500 tokens); `uv lock --check --offline`; §5 thresholds met (S1 1/1 or one logged re-run; S15 ★ 3/3); free checks PASS; CI green on both OS for the pushed commit (URL in progress) | tests · AGENTS, knowledge README (gen), 2 runbooks, roadmap, README, register | §5 | S (+ acceptance) |

## 5. Order, parallelism, acceptance budget

```text
30.1 ─► 30.2 fsio ─► 30.3 seam ─► 30.4 fail-closed ─► 30.5 marker/resource ─► 30.6 lifecycle ─► 30.7 shutdown
     ─► 30.8 summary+guard ─► 30.9 digest ─► 30.10 promotion-ready ══ phase-1 checkpoint ══
     ─► 30.11 selection ─► 30.12 retire ─► 30.13 invariants ─► 30.14 bringup/+deploy/ ─► 30.15 hygiene
     ─► 30.16 gate+profile ─► 30.17 tests/support ─► 30.18 status docs ─► 30.19 as-built docs ─► 30.20 close
```

**Why this order.** 30.1 first: the plan, the v2.1 plan and the register are in the repo before any WP cites them.
30.2 before the safety fixes: they write the marker and latch through `fsio`. 30.3 (pure move) before 30.4/30.5:
the fixes then land in small files, reviewable apart from the move, and `transaction.py` cannot cross 1,000 lines.
30.6/30.7 after the marker work (shared executor/running code). 30.8–30.10 are independent; 30.9 before 30.10 (records
built in E2 use the new digest) and both before M12. Phase 2 starts with 30.11 so later moves are caught by the
dead-glob test; 30.12 before 30.13 (E1 must not trip `PLAN_TOTALS`); package moves (30.14) before hygiene (30.15),
the gate (30.16, which names deploy paths) and the test package (30.17, last code change, so moved helpers are final).
Docs after code so they describe the final shape; agent-read text last so acceptance runs once.

**Parallelism:** none (D30-1, v2.1 precedent: one checkout, shared files such as `transaction.py`, `executor.py`,
layering test, `selection.py`). 30.8 and 30.9 could run beside 30.2–30.7 in a worktree, but the gain (~1 day) does
not pay for the merge risk in the safety core.

**Test cost per WP:** the full gate once (≈ 8 min wall on the Mac, A: 478 s on 10 cores); iteration with targeted
files and, from 30.16, `--quick` (≈ 1 min). Throw-away-clone suites only in 30.10 (E2, E2a) and 30.13 (E1).

**Acceptance budget (30.20 only; numbers from the 2026-11-26 full reports, per scenario):**

| Item | Claude Code | Codex | Why |
|---|---|---|---|
| `uv run b1500 dev harness qualify --up-to 0` | free | free | wiring, server start, doctor, offline harness tests |
| `uv run b1500 dev mcp-smoke --async` (each harness config) | free | free | real MCP server over stdio: async run + cancel |
| S1 × 1 (healthy NMOS Vth, full tool flow) | 0.54 USD, ~0.6 min | 0.33 M, ~1.2 min | AGENTS change, runner/harness profile, session-end hook, lean imports, analysis on both harnesses |
| S15 ★ × 3 (BTI started, "stop it now") | 3.50 USD, ~3.7 min | 3.38 M, ~7.1 min | the two harnesses end S15 on different changed paths: Claude Code's SIGTERM → MCP shutdown hook (30.7), Codex's turn-end kill → in-flight marker recovery (30.4–30.6) |
| **Total** | **≈ 4.0 USD, 4 sessions, ~4.3 min** | **≈ 3.7 M input (≈ 93 % cached), 4 sessions, ~8 min** | |
| Contingency | S1 re-run ≤ 0.54 USD | S1 re-run ≤ 0.33 M | functional rule: one logged re-run |
| If the installed harness ≠ `validated.yaml` | qualify T1 ≈ 0.67 USD | qualify T1 ≈ 0.40 M | v2.1 practice |

Not run, with the offline evidence that replaces it: S17 (pure package move; rehearsal test walks all 204 steps
through the CLI, S17 graders offline; Claude Code S17 is an owner-accepted headless limitation), S14 (runner
finalize paths: 30.6 tests + mcp-smoke `--async`), S2/S3/S5/S9 (summaries byte-identical by golden), S11–S13/S18
(kind helper dedupe: FLEX/plan/data goldens and the safety matrix unchanged; no card/knowledge text change), S16
(manual corpus untouched), S4/S6/S7/S8/S10 (no text or behaviour they grade changed). Full suite for comparison:
Claude Code 30.74 USD / 40 min (41 sessions), Codex 34.67 M / 82 min (40 sessions). On any login/API/network event
the batch stops (runner) and the orchestrator waits for the owner.

## 6. Risks

| Risk | Mitigation |
|---|---|
| A safety-core change regresses the cleanup, latch or recovery | pure move (30.3) separate from fixes; one subsystem per WP; repros as tests; global fault matrix (2,405 cases), async matrices, refusal matrix in every gate; the "promises that hold" (A §1.1) checked in each safety WP's review |
| Windows-only behaviour (retry budget, `filelock` appends, unique temps, signal paths) proven only by CI | checkpoint push after phase 1 with Windows CI green before phase 2; platform injection tests; doctor WARN for synced folders |
| A deleted pin carried intent | per deleted assertion the covering check named in the progress row (30.10, 30.13); safety pins untouchable (§7) |
| The sim-truth gate uncovers many recipes without a truth test (scope growth) | > 5 missing → stop and report before writing them |
| Package moves break imports, acceptance globs or the operator path | layering test, dead-glob test (30.11 lands first), saved-output diffs of `doctor`/`bringup status`, offline update/S17 tests |
| Lean imports introduce import-order bugs | fresh-interpreter import test per package |
| CI changes to one gate step hide which step failed | gate prints one line per step, groups on GitHub Actions, runs every step |
| Docs rewrite loses facts | pure moves where possible (history.md), diffs reviewed, structural doc tests kept, sizes bounded |
| Register misstates a decision | statements quoted from their source with file § ; the owner reviews `register.md` once (30.1 row) |
| Agent-visible drift from code WPs (`station_status`, `get_run`, analysis warnings) | output-shape tests in 30.5/30.6/30.15; scripted-agent graders offline; S1 on both harnesses at the end |
| Harness auto-update on the Mac before 30.20 | qualify T1 for the changed harness (budget row) |
| M12 starts mid-v3 | phase 1 is self-contained and pushed at the checkpoint (OD30-2) |
| Final acceptance fails | functional re-run rule; ★ failure → text/code iteration on that scenario only, one re-run, owner informed with cost |

## 7. Must not change; considered and rejected

**Must not change (looks odd or heavy, carries weight):** the safety core and its semantics (cleanup order and
survival, fault latch station-wide, guard before every source write, 42 V / 100 mA ceiling, policy soft ≤ hard ≤
ceiling, tiers and the summary text the human approves, rule registration order, raising rule = block), rule *and*
guard both enforcing limits (R-RSU-01 + guard), exactly 10 MCP tools with their budget, human-only commands and the
permission files and hook (owner decision only), the per-transaction bus and per-resource OS lock, the non-daemon run
worker, `EnvelopeViolation` not a `B1500Error`, simulator independence (no shared code with driver/catalog; keep its
duplicates), the guardrail tests (layering, 1,000-line cap — split, never exempt, FLEX literals, `pyvisa`/`ctypes`/
`WGFMU_` confinement, encodings, Windows paths), `archive → analysis.dataset`, the committed `.claude/skills/` mirror,
AGENTS/CLAUDE/entry SKILL text except the one batched edit, `docs/design/blueprint.md` path and numbering, report
location and naming in `docs/acceptance/`, the deployment anchors cited by code and tests, the roadmap M12 table,
`steps.yaml` ids, knowledge file names and H2 headings, `TODO(owner|verify|cite)` markers and the provenance rule,
`references/manuals/**` read-only and the no-corpus fallback, `validation/hw/` = the only evidence for
`hw_validated`, recipe ids (public interface), `DEFINITION_EXCLUDED` semantics, the qualify ladder and
`validated.yaml` written only by qualify, runtime plug-out via the station profile, the config/recipes/rules split,
explicit registries, `lint-skills` as a whole.

**Considered and rejected:**

| Proposal | From | Why not |
|---|---|---|
| Family subpackages for `catalog/kinds/`; split `models/station.py` now; pre-split every near-cap file | A, C(P11) | ~60–144 importers of churn, no defect; split when a change forces it (only `transaction.py` now) |
| Shared helpers across simulator/driver; re-export shims; DI/plugin framework; asyncio runs; entry-point plugins; auto-discovery; rules/limits in YAML | A, C | weakens the oracle or the reviewed-code guarantee, or indirection without gain |
| Mechanical rewrite or mass strip of WP/blueprint tags in src/tests/skills | A, B, C | ~1,000 edits, ambiguous targets, skill edits cost acceptance; legend + convention instead |
| `pytest-cov` in CI; deleting core tests for time | A | minutes per run for a known number; nothing redundant in the core |
| `ops/` as the operator package name | A | collides with `driver/ops/`; `deploy/` instead |
| Leave operator code in `devtools/` with a sub-rule only | C (Q7 b) | the coupling is wider than one import (doctor → budget/sync_harness, bring-up CLI → doctor/update); a package boundary is clearer than a sub-rule |
| Rename `docs/design/` → `docs/history/`; move/delete old acceptance reports; delete v1 manual indexes/`structured/` | B | path references and tooling for a naming gain; reports are paid evidence; extracts are the tested fallback |
| Docs site generator; Chinese copies of every doc; split `safety-model.md`; generate its rule table | B | machinery or churn beyond "moderate" |
| Entry `SKILL.md` description to v2 scope; edit `l6-cmu.md:127` OD21-10 | B (B10) | trigger text is acceptance-proven at 8,999/9,000 bytes; OD21-10 resolves once `plan-v2.1.md` and the register exist |
| Drop card `status` from 34 cards (C Q2 a) or generate it | C | 34 agent-read edits; "lowest of its recipes", lint-checked, unblocks partial promotion with zero text change |
| `--affected` ignores docstring/comment-only Python changes (C P6b) | C | cyclopts renders CLI help from docstrings (agent-visible); selection is advisory and the owner's judgement rule already covers comment edits |
| Firmware/WGFMU-library drift WARN in code (C Q6 a) | C | no reviewed record exists yet; a documented upkeep step suffices until after M12 |
| CI keeps separate steps + an equality test (C P8) | C | two lists kept in step by a test; CI calling the gate is one list |
| Card byte budgets instead of line budgets | B, C | no content change in v3; revisit when cards change |
| Plan TTL inside the plan hash (A:K-9); routes verification change (A:K-7) | A | plan-id semantics risk vs a deny rule that holds; K-7 is documented design |
| A third harness's full profile/parser interface | C (Q5 b) | not expected; the minimal table + contract section is enough |
| `b1500 dev new-recipe` scaffolder | C | a recipe is a YAML file + two links after v3; the cookbook row suffices |

## 8. Owner questions

**OD30-1 — Live acceptance for v3 (merges A Q-A1, B Q5, C Q4).**
- (a) §5 as planned: free checks on both; S1 × 1 on both; S15 ★ × 3 on Codex. ≈ 0.55 USD (Claude) + ≈ 3.7 M
  Codex tokens.
- (b) Cheaper: as (a) but S15 × 1 (recorded INCOMPLETE by design: a regression check, no ★ threshold claim)
  → Codex ≈ 1.5 M.
- (c) Full S1–S18 on both: ≈ 30.7 USD + ≈ 34.7 M, ~2 h of turns.
- (d) Free checks only (qualify T0, mcp-smoke): 0 tokens; no live proof of the runner/profile and shutdown changes.
- **Owner answer (2026-11-27): (a) with S15 ★ × 3 on BOTH harnesses** (orchestrator amendment: Claude Code ends S15
  through the SIGTERM shutdown hook that 30.7 changes, Codex through the marker recovery that 30.4–30.6 change) →
  ≈ 4.0 USD + ≈ 3.7 M.
- Arbiter's original recommendation (a): every live session covers a code path v3 changed that offline tests cannot drive through a
  real harness (runner + harness profile + session-end hook on both; cancel path once); the rest is covered offline
  (§5). Plan change: (b) edits the §5 table; (c) replaces it and adds ~3 h; (d) drops S1/S15 and states the gap in
  the closure row.

**OD30-2 — When to push `main` (and is M12 expected before v3 closes?).** Each push is a release (`update` pulls
`origin/main`); the lab clone does not exist before deployment D6.
- (a) Push at the phase-1 checkpoint and at 30.20 (Windows CI evidence for the file-I/O and signal changes early;
  the lab PC can run the safety fixes if M12 starts during phase 2/3).
- (b) Push once at 30.20 (v2.1 precedent).
- (c) Push after every WP (per-WP Windows CI; ~20 CI runs × 2 OS).
- **Owner answer (2026-11-27): (c) push after every WP** (v2.1 practice: early Windows CI found five Windows-only
  defects; no lab clone exists yet). Once a lab clone exists, push only at phase ends.
- Arbiter's original recommendation (a). Plan change: (b) removes the checkpoint push (a Windows-only failure then surfaces at the end);
  (c) adds a push line to every WP's AC.

**OD30-3 — Where does analysis applicability live?** Today `analysis/registry.py` lists recipe ids per method
(C:V5; `generic.*` already admits generic recipes; recipe-check names the missing entry).
- (a) Recipes declare their allowed methods (`analysis.allowed`); methods keep only kinds/families. Data-only recipe
  variants; `analysis` stops naming recipes. One-off 68-file migration, equality-tested, before M12 (it changes every
  recipe digest; after M12 it would need the key excluded from the digest). Adds WP30.10a (M).
- (b) Keep the lists in the registry; the cookbook documents the one-line edit per new recipe.
- **Owner answer (2026-11-27): (b)** — the registry keeps the lists; `maintainer.md` documents the one-line edit; no
  WP30.10a.
- Recommendation (b): the gain is one line of Python per new recipe for a maintainer (agents never add recipes, AGENTS
  rule 6), against a 68-file migration of every recipe digest; reversible later. Choose (a) if lab-side recipe
  variants without code edits matter to you.

## 9. Decided here (veto if you disagree)

- **D30-1** Sequential WPs in the main checkout on `main`, no branch/worktree, one commit per WP; log
  `docs/design/progress-v3.md` with compact rows (≤ ~1,000 chars; detail in the commit message); `progress.md` frozen.
- **D30-2** v3 ids `WP30.n`/`OD30-n`/`D30-n`; this plan is committed as `docs/design/plan-v3.md` in 30.1.
- **D30-3** History stays in `docs/design/` (B Q1 a); roadmap result tables move to `design/history.md`.
- **D30-4** Commit the v2.1 plan verbatim as `design/plan-v2.1.md`, plus `register.md` and the id test (B Q2 a;
  B checked it holds no private paths or addresses).
- **D30-5** Code-comment provenance: legend + convention, no sweep (A Q-A4 a, B Q3 a, C P10).
- **D30-6** Operator path moves to package `deploy/` (A Q-A2 a, renamed; C Q7 overruled, §7).
- **D30-7** `bringup/` package (A); its ledger lock uses `filelock`.
- **D30-8** Card status = lowest status of its recipes, lint-checked (C Q2 → variant of b).
- **D30-9** Driver-map builder and test retired; `flex-driver-map.yaml` kept frozen with its README (C Q1 a).
- **D30-10** Recipe digest over the parsed YAML mapping minus `DEFINITION_EXCLUDED` (C P3), before M12.
- **D30-11** `max_limited_fraction_in_fit` honoured by every window fit (A Q-A5); knowledge text unchanged.
- **D30-12** One gate command, CI runs it; `regen` for generated files; `--quick` for iteration (B F6, C P8 modified).
- **D30-13** Minimal harness profile table + "Supporting a coding harness" section; no third harness now (C Q5 a).
- **D30-14** Firmware/WGFMU-library drift: documented upkeep procedure, no code check yet (C Q6 deferred).
- **D30-15** `docs/operator.md` in English, moved from the deployment doc, not copied (B Q4 a).
- **D30-16** Old acceptance reports stay where they are (B Q7 a).
- **D30-17** Annotated tags `v2`, `v2.1`, `v3` and version 3.0.0 at the v3 close (B Q6 a, A:A11).
- **D30-18** Agent-read text: AGENTS.md, knowledge index, two runbook `sources:` — once, in 30.20; CLAUDE.md, entry
  SKILL.md, cards, stages and `steps.yaml` unchanged in v3.
- **D30-19** `--affected`: per-scenario base, index out of `touches`, dead-glob test; no docstring-blind diff.
- **D30-20** Lab clone stays at `C:\b1500\test_agent` (already documented); doctor WARNs inside a synced folder
  (A Q-A3 answered by the existing deployment doc).
- **D30-21** `.python-version` = 3.12; doctor reads Python bounds from `pyproject.toml` (C P9).

- **D30-22** Housekeeping (B F17), by the orchestrator at 30.1: the local `build/` folder (a stale 2026-11-19 copy of
  the package that a plain `grep -r` finds) and `src/b1500_test_agent.egg-info` are untracked, git-ignored and older
  than `pyproject.toml` (checked 2026-11-27): delete exactly those two paths (`rm -rf build
  src/b1500_test_agent.egg-info`). Never `git clean -X`: it would also delete `config/local/`, `data/`, `.venv` and
  `.mcp.json`.
