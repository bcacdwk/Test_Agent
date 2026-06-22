# Flow Taxonomy Proposal - Opus48

Date: 2026-06-22
Status: proposal only. No code, no production docs, no renames, no flow catalog.
Scope: a **classification taxonomy** for `A_flow_*`, `B_flow_*`, and `AB_flow_*`
names and families. Concrete flow catalogs are intentionally deferred. C_flow /
ABC_flow are addressed only for forward-compatibility.

Source of truth for atom names: `src/b1500_test_agent/mcp/server.py` plus
`.agents/skills/.../references/instrument-interaction-tools.md`. The three
`tmp/*_flow_arbitration.md` drafts are treated as *intent input only*; their exact
names are outdated (see Diagnosis).

---

## Diagnosis Of Old Flow Drafts

The accepted drafts (`a_flow_arbitration.md`, `b_flow_arbitration.md`,
`ab_flow_arbitration.md`) captured the right **compositions** but are stale on two
independent axes at once.

### Defect 1 — they reference a dead atom-naming scheme

The drafts were written against an older atom vocabulary that no longer exists in
`server.py`. The middle/target tokens have since been overhauled (per
`atom_taxonomy_proposal_opus48.md`, partially adopted):

| Draft atom (dead) | Current atom (live in server.py) |
|---|---|
| `A_atom_connect_b1500` | `A_atom_flex_connect` |
| `A_atom_list_installed_modules` | `A_atom_flex_list_modules` |
| `A_atom_get_instrument_status` | `A_atom_flex_get_status` |
| `A_atom_wait_operation_complete` | `A_atom_flex_wait_opc` |
| `A_atom_easyexpert_identify_remote_host` | `A_atom_easyexpert_identify` |
| `B_atom_abort_operation` | `B_atom_safety_b1500_abort` |
| `B_atom_zero_all_outputs` | `B_atom_output_b1500_zero_all` |
| `B_atom_reset_instrument` | `B_atom_lifecycle_b1500_reset` |
| `B_atom_run_preflight_checks` | `B_atom_safety_b1500_preflight` |
| `B_atom_set_asu_path` | `B_atom_routing_asu_set_path` |

So every old flow's atom sequence needs re-pointing before it can be trusted. This
is mechanical, but it means the drafts cannot be lifted verbatim.

### Defect 2 — the flow *names* have no closed classification axis

The draft flow names are free-form verb phrases chosen per-flow:

- A: `discover`, `snapshot`, `drain`, `collect`, `fetch`, `prepare`, `configure`,
  `record`, `close`, `open`, `select`, `teardown`, `browse` — 13 different lead
  verbs, several of them synonyms (`collect`/`fetch`, `close`/`record`/`teardown`,
  `prepare`/`configure`).
- B: `emergency_abort_and_zero`, `zero_disable`, `reset_initialize`,
  `run_preflight_gate`, `self_test_calibrate`, `configure_baseline`, `prepare_path`,
  `perform_phase_compensation` — names enumerate the atom steps, so the name grows
  with the recipe instead of naming the *intent*.
- AB: `start`, `emergency_recover`, `safe_shutdown`, `reset_rediscover`,
  `maintenance`, `prepare`, `configure`, `open`, `close` — closest to clean, but
  still mixes endpoint position (`start_b1500` vs `open_wgfmu` vs
  `easyexpert_abort_recover`) and lacks a fixed slot order.

### Three structural problems to fix

1. **No fixed token order.** Some names are `verb_endpoint_object`
   (`A_flow_discover_b1500_session`), some are `endpoint_verb_object`
   (`B_flow_easyexpert_abort_to_standby`). Sorting a tool list is therefore
   meaningless.
2. **Names describe steps, not goals.** `reset_initialize`, `abort_and_zero`,
   `self_test_calibrate` leak the atom sequence into the name; add a step and the
   name must change.
3. **No declared primary axis per layer.** The drafts never said *what question the
   first token answers*. That is the actual deliverable here.

### What the drafts got right (keep these)

- A flows are **single-transport** (the drafts explicitly reject cross-transport
  `A_flow_full_system_discovery`). Interface is a real, hard boundary.
- B flows are **state-change brackets**, almost always wrapped in a safe-output
  pre/post (`zero -> act -> confirm`).
- AB flows follow **observe (A) -> act (B) -> verify (A)** and are the user-facing
  layer.
- Priorities (P0/P1/P2) were already assigned sensibly and are reused below.

---

## Candidate Taxonomy Axes

Five axes are available for the first (classifying) token. None is best for all
three layers; the central finding is that **the right primary axis climbs the
abstraction ladder as the layer composes more**.

### Axis A — Interface / domain (`flex`, `wgfmu`, `easyexpert`; or target `smu`/`asu`/`cmu`)
- **What it answers:** *which transport/endpoint?*
- **A_flow fit:** strong but insufficient alone — A flows are transport-bound, but a
  single transport hosts many distinct operations (discover vs snapshot vs collect).
- **B_flow fit:** weak as primary — most B work is one transport (`flex`/`b1500`);
  it hides risk, exactly the failure the atom taxonomy fixed.
- **AB_flow fit:** weak as primary — too low-level for the user-facing layer.
- **Verdict:** excellent **second** token everywhere; poor **first** token anywhere.

### Axis B — Operation semantics (`discover`, `snapshot`, `collect`, `prepare`, `select`, `teardown`)
- **What it answers:** *what kind of read/session operation?*
- **A_flow fit:** **best primary** — it is the value a flow adds over raw atoms, and
  it repeats across all three interfaces.
- **B_flow fit:** partial — B's "operations" are inseparable from risk, so this
  collapses into Axis C.
- **AB_flow fit:** too granular; AB users think in goals, not operations.
- **Verdict:** primary axis for **A_flow**.

### Axis C — Risk / safety (`safety`, `output`, `lifecycle`, `diagnostic`, `calibration`, `routing`, `correction`, `policy`)
- **What it answers:** *how dangerous, and what is touched?*
- This is the **atom-level** B axis (8 categories). Reusing it verbatim at the flow
  level is the main trap (see Anti-Patterns): a flow is a *bracket* that usually
  spans several atom risk categories, so single-category assignment is impossible and
  the cross product (8 categories x targets x verbs) explodes.
- **Verdict:** must be **condensed** into ~5 risk-bracket *intents* for B_flow; never
  used raw at the flow layer.

### Axis D — Lifecycle / stage (`entry` -> `setup` -> `operate` -> `maintain` -> `teardown`)
- **What it answers:** *where in the session/instrument lifecycle?*
- **Fit:** an excellent **ordering principle** that shapes each category set (it is
  why B's brackets line up gate -> restore -> condition -> maintain -> secure), but a
  poor naming token itself — "stage" is too abstract to disambiguate two flows in the
  same stage.
- **Verdict:** use to **order and sanity-check** category sets; do not put in names.

### Axis E — User-intent / workflow (`startup`, `shutdown`, `recovery`, `maintenance`, `preparation`)
- **What it answers:** *what operator goal is being accomplished?*
- **A_flow fit:** too high — a single A flow rarely completes a goal.
- **B_flow fit:** too high — B alone cannot certify a workflow (no A verification).
- **AB_flow fit:** **best primary** — AB is exactly "a complete, verified operator
  workflow."
- **Verdict:** primary axis for **AB_flow**.

### Summary: one shared shape, three primary vocabularies

```
{CLASS}_flow_{PRIMARY}_{ENDPOINT}_{subject}
```

| Layer | PRIMARY axis (first token) | ENDPOINT (second token) | Why this axis |
|---|---|---|---|
| `A_flow` | operation semantics | interface (`flex`/`wgfmu`/`easyexpert`) | flows add operation value; A is transport-bound |
| `B_flow` | risk-bracket intent (condensed) | target (`b1500`/`smu`/`asu`/`scuu`/`cmu`/`qscv`/`wgfmu`/`easyexpert`) | lead with risk; brackets span atom categories |
| `AB_flow` | workflow intent | endpoint (`flex`/`wgfmu`/`easyexpert`) | AB is the user-facing complete workflow |

The **endpoint token is the constant**; only the **primary axis changes**, rising
operation -> risk-bracket -> workflow as composition deepens. `subject` is a short
disambiguating noun. This is the "shared pattern" the brief asked for, with a
per-layer first-token vocabulary.

---

## Recommended A_flow Taxonomy

### Naming pattern

```
A_flow_{operation}_{interface}_{subject}
operation in { discover, snapshot, collect, prepare, select, teardown }   (+ drain*)
interface in { flex, wgfmu, easyexpert }      # reuse atom interface token; b1500 -> flex
subject     = short noun (session, status, errors, output_buffer, result, workspace, ...)
```

Hybrid, **operation-first with a mandatory interface token**. This directly answers
Q1: not pure interface, not pure semantics — a hybrid where the *operation leads* and
the *interface is always present*.

### Categories (closed set of 6, + 1 optional)

| Operation | Meaning | Lifecycle stage |
|---|---|---|
| `discover` | first contact + enumerate: open/identify/inventory and catalog browsing | entry |
| `snapshot` | non-destructive health/status/diagnostics readback of an open session | operate (observe) |
| `collect` | harvest already-produced results/buffers; never starts a measurement | operate (read-out) |
| `prepare` | stateful but non-DUT session setup: format, timestamp, buffer, SRQ, logging | setup |
| `select` | software-context selection: workspace open, app/preset selection | setup (context) |
| `teardown` | A-only session close / disconnect-context capture (never "safe shutdown") | teardown |
| `drain`* | error-queue read + annotate (+optional clear) — *optional split from `snapshot`* | operate (observe) |

`drain` is the one judgment call: it is a `snapshot` that **mutates** (clears) the
error queue. Recommend keeping it separate **only** because its audit/idempotency
rules differ; otherwise fold into `snapshot` with a `clear_after_read` flag.

### Why

- **It is the flow's value-add.** Atoms are already interface-first; a flow earns its
  name by saying *what coherent read it performs*. Operation-first makes that legible.
- **It matches the drafts' instinct** (they already led with `discover`/`snapshot`/…)
  while collapsing 13 ad-hoc verbs into 6 closed ones.
- **Interface stays mandatory and second**, so the transport-boundedness that A cares
  about (separate failure modes) is preserved and visible, and a sorted list still
  clusters by intent first (how users pick: "I want to discover" -> choose transport).
- **Survives module growth**: new FLEX modules ride inside `flex` + `subject`; no new
  top-level bucket (same lesson as the atom taxonomy).

### Priorities

- **P0:** `discover` (all three interfaces), `snapshot` (flex, wgfmu), `collect`
  (flex output buffer, easyexpert result), `drain` (flex errors).
- **P1:** `prepare` (buffer/polling/logging), `select` (easyexpert workspace/app/preset
  context), `teardown` (flex disconnect-context, wgfmu close).
- **P2:** `discover` catalog convenience subsets (e.g. preset browsing) that duplicate
  a richer `discover` flow.

### Examples only (not a catalog)

```
A_flow_discover_flex_session
A_flow_snapshot_flex_status
A_flow_drain_flex_errors
A_flow_collect_flex_output_buffer
A_flow_discover_wgfmu_session
A_flow_collect_easyexpert_result
A_flow_select_easyexpert_workspace
A_flow_teardown_wgfmu_session
```

---

## Recommended B_flow Taxonomy

### Naming pattern

```
B_flow_{intent}_{target}_{subject}
intent in { secure, gate, restore, maintain, condition }
target in { b1500, smu, asu, scuu, cmu, qscv, wgfmu, easyexpert }   # atom target token
subject = short noun (outputs, emergency, preflight, known_state, self_test_cal,
                      low_current_path, correction, standby, ...)
```

This answers Q2: **neither the 8 atom risk categories verbatim, nor raw lifecycle
stages.** Instead, a small set of **risk-bracket intent verbs** that *are* lifecycle-
ordered and safety-forward.

### Categories (closed set of 5)

| Intent | Meaning (a *bracket*, not one atom) | Condenses atom categories | Lifecycle |
|---|---|---|---|
| `secure` | reach a safe output/standby state (abort+zero+confirm; zero+disable; abort->standby) | `safety`(abort) + `output` | teardown / emergency |
| `gate` | verify readiness before allowing change (preflight + interlock); never energizes | `safety` | pre-flight |
| `restore` | establish a known/default state (reset, initialize, baseline housekeeping, warning policy) | `lifecycle` + `output`(filter/ssr) + `policy` | setup |
| `maintain` | instrument-health bracket (self-test + self-cal, pre/post) | `diagnostic` + `calibration` | maintain |
| `condition` | signal-path & fixture-dependent setup (ASU/SCUU routing, CMU correction/phase, QSCV offset, EEX zero-cancel), always inside a safe-output bracket | `routing` + `correction` + `calibration`(fixture) | setup (measurement-prep) |

This is MECE over all 15 accepted draft B flows (secure 3, gate 1, restore 3,
maintain 2, condition 6).

### Why

- **Avoids the explosion (Q2's real concern).** The 8 atom categories x 8 targets x
  many verbs is unmanageable and, worse, *wrong*: a flow like emergency-abort-and-zero
  spans `safety`+`output`+`lifecycle`. Collapsing to 5 *intents* gives each flow one
  honest home.
- **Still safety-forward.** `secure` and `gate` are the two safety-critical families
  and they sort/cluster first — the same "risk is the first thing you read" property
  the atom-B taxonomy prized, lifted to the flow layer.
- **Names the goal, not the steps.** `B_flow_restore_b1500_known_state` does not
  change when an `initialize` atom is added to the recipe; the old
  `reset_initialize_b1500_state` would.
- **No redundancy with atoms.** The fine-grained risk lives on the atoms; the flow
  layer carries the coarser bracket intent.

### Priorities

- **P0:** `secure` (emergency abort+zero; zero+disable; easyexpert abort->standby),
  `gate` (b1500 preflight), `restore` (b1500 reset/init; wgfmu baseline).
- **P1:** `maintain` (b1500 / wgfmu self-test+cal), `condition` (asu / scuu / cmu /
  qscv / easyexpert zero-cancel).
- **P2:** thin housekeeping-only `restore` variants (e.g. SMU filter/SSR baseline)
  that are rarely invoked standalone.

### Examples only

```
B_flow_secure_b1500_emergency        # abort -> zero_all -> confirm
B_flow_secure_b1500_outputs          # zero -> disable -> confirm
B_flow_gate_b1500_preflight
B_flow_restore_b1500_known_state     # reset -> (optional) initialize
B_flow_maintain_b1500_self_test_cal
B_flow_condition_asu_low_current_path
B_flow_condition_cmu_correction
B_flow_secure_easyexpert_standby
```

---

## Recommended AB_flow Taxonomy

### Naming pattern

```
AB_flow_{workflow}_{endpoint}_{subject}
workflow in { startup, shutdown, recovery, maintenance, preparation }
endpoint in { flex, wgfmu, easyexpert }     # the transport/session the workflow governs
subject  = short noun (safe_session, baseline, self_test_cal, low_current_path,
                      cmu_correction, polling, ...)
```

This answers Q3 affirmatively: **classify by workflow intent, not by atom
categories.** AB flows are the most user-facing layer and the most complex
compositions, so the first token should be the operator's *goal*.

### Categories (closed set of 5)

| Workflow | Operator goal | Typical shape (observe -> act -> verify) |
|---|---|---|
| `startup` | cold/unknown -> safe, ready, verified session | A.discover -> B.gate/restore -> A.snapshot |
| `shutdown` | running -> safely down, with record | A.collect (opt) -> B.secure -> A.teardown |
| `recovery` | error/abort/unknown -> safe + verified | (B.secure first) -> A.drain -> A.snapshot |
| `maintenance` | auditable self-test/self-cal with pre/post evidence | A.snapshot -> B.maintain -> A.snapshot |
| `preparation` | non-measurement setup, verified (baseline, polling, path, correction) | A.snapshot -> B.gate -> B.restore/condition -> A.snapshot |

**Recommendation on Q3's `correction`:** fold it into `preparation` (correction is a
kind of measurement-prep) with `subject = *_correction`, rather than making it a 6th
top-level workflow. This keeps the set at 5 and prevents `preparation`/`correction`
overlap. Flagged as an open question below.

### Why

- **Matches how operators reason** ("start the bench", "shut it down safely",
  "recover from a fault", "run maintenance", "prep a path") — not "compose A and B".
- **Stable under recipe change.** Adding a verification step to a startup flow does
  not rename it; the old `start_b1500_safe_session` already hints at this and we make
  it the rule.
- **The endpoint token keeps multi-transport flows honest.** Each workflow is named
  per endpoint (`flex`/`wgfmu`/`easyexpert`); a full-bench orchestration is the
  *application's* job (calling several AB flows), not one mega-flow — consistent with
  the drafts' rejection of cross-transport flows.
- **Climbs one rung above B.** B's `secure` is the *action bracket*; AB's `recovery`/
  `shutdown` are the *goals* that use it. Same word-family, higher abstraction.

### Priorities

- **P0:** `startup` (flex safe session; wgfmu baseline; easyexpert workspace),
  `recovery` (flex emergency; easyexpert abort), `shutdown` (flex safe shutdown).
- **P1:** `maintenance` (flex / wgfmu self-test+cal), `preparation` (baseline,
  asu/scuu path, cmu correction, qscv offset — all verified).
- **P2:** `preparation` of status/SRQ polling behind a safety gate.

### Examples only

```
AB_flow_startup_flex_safe_session
AB_flow_recovery_flex_emergency
AB_flow_shutdown_flex_safe_session
AB_flow_maintenance_flex_self_test_cal
AB_flow_preparation_asu_low_current_path
AB_flow_startup_wgfmu_baseline
AB_flow_recovery_easyexpert_abort
AB_flow_preparation_cmu_correction
```

### Forward compatibility: C_flow and ABC_flow (Q7, not designed here)

Apply the same shape; climb the ladder one more rung; keep the endpoint token.

- **C_flow** = measurement recipes (IV/CV/pulse/spot/sweep/stress). Primary axis =
  **measurement semantics**, module/interface second:
  `C_flow_{measurement_kind}_{interface_or_module}_{subject}`, e.g.
  `C_flow_sweep_flex_id_vg`, `C_flow_pulse_wgfmu_stress`, `C_flow_cv_cmu_sweep`.
  Do **not** reuse A/B's primary axes for C.
- **ABC_flow** = full end-to-end experiments (startup -> prepare -> measure -> collect
  -> shutdown). Primary axis = **experiment intent**, device/endpoint second:
  `ABC_flow_{experiment_intent}_{device_or_endpoint}_{subject}`, e.g.
  `ABC_flow_characterize_mosfet_id_vg`, `ABC_flow_qualify_cap_cv`.
- **Standing rule:** each new layer's first token is one abstraction step higher than
  the layer below (operation -> risk-bracket -> workflow -> measurement -> experiment);
  the endpoint/target token is invariant; never let a higher layer enumerate the cross
  product of the layer below (ABC must not be "every C x every AB").

---

## Migration Guidance From Old Drafts

Two migrations are required and should be done together: **(1)** re-point atom
references to current `server.py` names (Defect 1), and **(2)** re-file flow names
into the closed taxonomy (Defect 2). Migrate **by family**, not flow-by-flow.

### A_flow family map

| Old draft family | New `operation` | Note |
|---|---|---|
| `discover_*_session`, `discover_easyexpert_remote` | `discover` | + `discover_*_catalogs`, `browse_presets` fold in (P2) |
| `snapshot_*_status`, `snapshot_wgfmu_diagnostics` | `snapshot` | |
| `drain_*_errors` | `drain` (or `snapshot`) | keep separate only for clear-semantics |
| `collect_*_output_buffer`, `fetch_easyexpert_latest_result` | `collect` | unify `collect`/`fetch` -> `collect` |
| `prepare_*_buffer`, `configure_*_polling`, `prepare_wgfmu_logging` | `prepare` | unify `prepare`/`configure` -> `prepare` |
| `open_*_workspace_context`, `select_*_application/preset_context` | `select` | |
| `record_*_disconnect_context`, `close_wgfmu_session`, `teardown_*_workspace` | `teardown` | unify `record`/`close`/`teardown` -> `teardown` |

### B_flow family map

| Old draft family | New `intent` |
|---|---|
| `emergency_abort_and_zero_outputs`, `zero_disable_*_outputs`, `easyexpert_abort_to_standby` | `secure` |
| `run_*_preflight_gate` | `gate` |
| `reset_initialize_*_state`, `prepare_wgfmu_safe_baseline`, `configure_smu_baseline_state` | `restore` |
| `self_test_calibrate_*` | `maintain` |
| `prepare_asu/scuu_path`, `prepare_cmu_correction`, `perform_cmu_phase_compensation`, `perform_qscv_offset_cancel`, `easyexpert_zero_cancel_bracket` | `condition` |

### AB_flow family map

| Old draft family | New `workflow` |
|---|---|
| `start_*_safe_session`, `open_wgfmu_safe_baseline`, `open_easyexpert_workspace_*` | `startup` |
| `safe_shutdown_*`, `close_wgfmu_session_safely`, `easyexpert_workspace_safe_teardown` | `shutdown` |
| `emergency_recover_*`, `reset_rediscover_*_state`, `easyexpert_abort_recover_remote` | `recovery` |
| `maintenance_*_self_test_calibration` | `maintenance` |
| `prepare_*_verified`, `configure_*_polling_with_safety_gate`, `*_correction_verified`, `*_offset_cancel_verified` | `preparation` |

### Migration rules

- Re-file by **intent**, then rename to `{primary}_{endpoint}_{subject}` with a fixed
  token order; drop step-listing names (`abort_and_zero` -> `secure_*_emergency`).
- Re-point every atom reference to the current name (Defect 1 table) in the same
  change; flows that name nonexistent atoms are not migratable as-is.
- Preserve the drafts' P0/P1/P2 and their composition decisions; only the *labels*
  change.
- Keep `reset_rediscover` as `recovery` (it returns from an unknown state), not
  `startup`; the distinguishing question is "are we recovering, or starting clean?"

---

## Anti-Patterns / Rejected Categories

These are rejected to prevent combinatorial explosion or axis-mixing (Q6).

1. **Reusing the 8 atom risk categories as B_flow categories.** A flow spans several;
   forces false assignment and an 8 x target x verb cross product. -> use 5 condensed
   intents.
2. **Interface-first as the *primary* token for any flow layer.** It buries the intent
   (the reason a flow exists) and duplicates the atom axis. Interface is the *second*
   token. (Pure interface-first A_flow is the specific rejected form of Q1.)
3. **Cross-transport / "full system" flows** (`*_full_system_discovery`,
   full-bench startup/shutdown as one flow). Separate transports = separate failure
   modes; this is the application layer's job. (Confirmed by all three drafts.)
4. **Per-module top-level categories** (`AB_flow_smu_*`, `AB_flow_cmu_*` as the first
   token). Module is a *target/subject*, never a category — repeats the WGFMU-as-peer
   mistake from the atom taxonomy at the flow layer.
5. **Step-listing names** (`reset_initialize`, `abort_and_zero`,
   `self_test_calibrate`, `open_initialize_self_test`). The name must track the *goal*,
   not the recipe, or it churns on every step edit.
6. **A measurement/`run` category inside A/B/AB.** Measurement is C. Admitting it here
   destroys the A/B/AB safety boundary that the whole arbitration rests on.
7. **Over-splitting AB workflow intents** (separate `correction`, `conditioning`,
   `baseline`, `polling`, `calibration`). Collapse into `preparation` + `subject`;
   keep `startup`/`shutdown`/`recovery`/`maintenance`/`preparation` only.
8. **Direction-split `output`/`secure`** (`arm` vs `safe`) at the flow layer. Fuzzy at
   the edges (`recover_zeroed`, path switches); express energize-direction as response
   metadata, not a category — same call the atom taxonomy made.
9. **A unique verb per flow.** 13 synonymous lead verbs (collect/fetch, close/record/
   teardown, prepare/configure) defeat classification. Each layer's first token is a
   **closed vocabulary**.

---

## Open Questions For Parent/User

1. **A_flow `drain` vs `snapshot`.** Keep `drain` as its own operation (clearer
   audit/clear semantics), or fold into `snapshot` with a `clear_after_read` flag?
   Recommendation: keep separate, low cost.
2. **Endpoint token for the native path.** Atoms are inconsistent: A uses `flex`
   (`A_atom_flex_*`) but B uses `b1500` (`B_atom_*_b1500_*`). Mirror that split at the
   flow layer (A_flow/AB_flow -> `flex`, B_flow -> `b1500`), or unify on one word for
   all flows? Recommendation: mirror the atom layer for least surprise; revisit if it
   confuses users.
3. **AB `correction` as its own workflow?** Recommendation: fold into `preparation`.
   Override if the correction family (CMU/QSCV/zero-cancel) grows large enough to merit
   a top-level `correction` workflow.
4. **B_flow `restore` wording.** `restore` (recommended) vs `baseline` vs `reset`.
   `restore` reads as "to a known/default state"; confirm it will not be confused with
   the `B_atom_output_b1500_recover_zeroed` (RZ) atom, which lives under `secure`.
5. **`select` vs `discover` boundary in A_flow.** Catalog *browsing* is `discover`;
   context *selection* (workspace open, app/preset select) is `select`. Confirm the
   line, since EasyEXPERT workspace-open sits near it.
6. **Token count.** The pattern is 4 tokens (`class_flow_primary_endpoint_subject`).
   Accept the length for legibility, or drop `subject` when the
   `primary+endpoint` pair is already unique?
7. **Structured intent metadata.** Should each flow response carry machine-readable
   `flow_class`, `primary_intent`, `endpoint`, and `risk_tier` fields (independent of
   the name) so tooling can gate without string-parsing names? Recommended regardless
   of the naming outcome (mirrors the atom proposal's `risk_tier` suggestion).
8. **C_flow / ABC_flow primary axes** are sketched (measurement-semantics /
   experiment-intent) but not decided; confirm when C atoms exist.
