# Flow Taxonomy Proposal - GPT55

Status: proposal only. No production code or formal documentation was modified.

Scope: naming and classification principles for future `A_flow_*`, `B_flow_*`, and `AB_flow_*` tools. This document intentionally does not define a final flow catalog.

## Diagnosis Of Old Flow Drafts

The old A/B/AB flow arbitration drafts captured useful workflow boundaries, but their names and examples are now out of sync with the accepted atom taxonomy.

- The old drafts use older atom names such as `A_atom_connect_b1500`, `A_atom_identify_b1500`, and `B_atom_zero_all_outputs`. Current A atoms are `A_atom_{interface}_{action}` with `flex`, `wgfmu`, and `easyexpert`; current B atoms are `B_atom_{risk_or_operation}_{target}_{action}`.
- The old A draft already discovered an important rule: pure A flows should not merge the direct FLEX, WGFMU library, and EasyEXPERT remote paths into a single "full discovery" flow because they have separate sessions, failure modes, and readback semantics.
- The old B draft was strongest when it described operator intent, such as emergency abort/zero, preflight gating, known-state reset, path preparation, or correction. It was weaker when names mirrored individual B atom categories too directly.
- The old AB draft had the most durable core pattern: observe with A, act with B, verify/log with A. Its accepted flows are best understood as startup, shutdown, recovery, maintenance, preparation, and correction workflows, not as a mechanical blend of A and B atom category names.
- Several old names ended with generic qualifiers such as `verified` or `safe`. Those are useful return-schema guarantees or policy claims, but they should not become broad top-level taxonomy buckets unless the actual workflow intent is clear.

The main migration task is therefore conceptual, not just mechanical. Keep the accepted boundaries, replace outdated endpoint words with current interface/target words, and classify flows by why the user would run them.

## Candidate Taxonomy Axes

### Interface/domain axis

Pattern idea: classify flows by `flex`, `wgfmu`, `easyexpert`, or future interfaces.

- Best fit: A flows, because A work is strongly session/interface-shaped.
- Strength: prevents accidental cross-transport "discover everything" flows.
- Weakness: too low-level for B and AB. A user does not usually choose an emergency or maintenance flow by first thinking "which atom interface category is this?"

Use this axis as a required second token for A flows, not as the only taxonomy.

### Operation semantics axis

Pattern idea: classify by actions like `discover`, `snapshot`, `drain`, `collect`, `prepare`, `select`, `teardown`.

- Best fit: A flows and some B preparation flows.
- Strength: makes shared patterns visible across interfaces.
- Weakness: can fragment too far if every verb becomes a category.

Use a controlled verb set. Prefer a few durable intents over one-off verbs.

### Risk/safety axis

Pattern idea: classify by safety, output, routing, calibration, correction, policy, and similar B atom risk categories.

- Best fit: B atoms and safety-critical portions of B flows.
- Strength: puts danger and operator intent near the front.
- Weakness: pure B flows often compose multiple B atom categories, for example output plus safety plus lifecycle. Mirroring atom categories can create too many flow families.

Use risk words for B flow families only when they describe the whole flow, such as `emergency`, `safe_state`, or `preflight`.

### Lifecycle/stage axis

Pattern idea: classify by stages such as startup, shutdown, recovery, maintenance, preparation.

- Best fit: AB flows, because AB flows are operator workflows around a session or instrument state.
- Strength: maps naturally to observe-act-verify phases and user-facing runbooks.
- Weakness: too broad for pure A utility flows and too abstract for low-level B state-control flows.

Use this as the primary AB axis. Use it selectively for B when the flow really changes known state.

### User-intent/workflow axis

Pattern idea: classify by the user's reason for invoking the flow: recover from emergency, start a safe session, collect buffered results, prepare a path, perform correction.

- Best fit: all flow classes, but especially AB.
- Strength: avoids copying atom taxonomies and keeps names stable even if atom internals change.
- Weakness: needs discipline. Names such as `do_setup`, `full_check`, or `safe_everything` sound intent-based but are too broad.

This should be the governing principle: flow names should answer "what outcome is this workflow trying to produce?"

## Recommended A_flow Taxonomy

### Naming pattern

Use a hybrid, with operation intent first and A interface second:

```text
A_flow_{intent}_{interface}_{scope}
```

Allowed current `interface` values should match the A atom interface axis:

- `flex`
- `wgfmu`
- `easyexpert`

The first token after `A_flow_` should be a controlled A intent, not an arbitrary verb. Recommended current intent families:

- `discover`
- `snapshot`
- `drain`
- `collect`
- `fetch`
- `prepare`
- `configure`
- `select`
- `teardown`

### Categories

P0 candidate A categories:

- `discover`: establish non-destructive identity, session, inventory, and context.
- `snapshot`: capture status, settings, progress, and diagnostic readbacks without clearing or changing output state.
- `drain`: read and annotate error/warning queues when the operation intentionally consumes queue state.
- `collect` / `fetch`: retrieve already-produced output-buffer or EasyEXPERT result data without starting a measurement.

P1 candidate A categories:

- `prepare`: configure parser-facing or logging context, such as output format, timestamp behavior, or WGFMU logs. Require explicit flags for destructive actions like clearing unread buffers.
- `configure`: set status/SRQ/polling behavior. Keep separate from `prepare` when the flow changes how clients observe later operations.
- `select`: select EasyEXPERT software context, such as app test or preset setup, without executing measurement.
- `teardown`: close A-only sessions or workspace context while recording final readbacks.

P2 candidate A categories:

- Narrow browsing or convenience subsets that duplicate a richer P0/P1 category, such as preset-only catalog browsing.
- Optional readback helpers that become useful after missing A atoms exist, such as reversible SRQ mask handling.

### Why

A flows should not be pure interface-first because flow users usually ask for an outcome: discover, snapshot, drain, collect, fetch, select, or teardown. But the interface must still be explicit because `flex`, `wgfmu`, and `easyexpert` are different sessions with different failure modes.

The recommended pattern keeps shared behavior visible while preventing broad cross-interface flows. For example, `discover` can be a shared family, but `A_flow_discover_flex_session`, `A_flow_discover_wgfmu_session`, and `A_flow_discover_easyexpert_remote` remain separate.

### Examples only (not full catalog)

- `A_flow_discover_flex_session`
- `A_flow_snapshot_flex_status`
- `A_flow_drain_flex_errors`
- `A_flow_collect_flex_output_buffer`
- `A_flow_discover_wgfmu_session`
- `A_flow_snapshot_wgfmu_diagnostics`
- `A_flow_prepare_wgfmu_logging`
- `A_flow_discover_easyexpert_remote`
- `A_flow_select_easyexpert_application_context`
- `A_flow_fetch_easyexpert_latest_result`

## Recommended B_flow Taxonomy

### Naming pattern

Use a small operator-intent family first, followed by target and outcome:

```text
B_flow_{family}_{target}_{outcome}
```

The `family` should not be a direct copy of every B atom category. A B flow may compose `safety`, `output`, `lifecycle`, `routing`, `correction`, and `policy` atoms, so the flow family should describe the overall operator intent.

Recommended current B flow families:

- `emergency`
- `safe_state`
- `preflight`
- `baseline`
- `maintenance`
- `preparation`
- `correction`

Use current B atom targets where they matter:

- `b1500`
- `smu`
- `asu`
- `scuu`
- `cmu`
- `qscv`
- `wgfmu`
- `easyexpert`

### Categories

P0 candidate B categories:

- `emergency`: immediate stop/recover actions where the system may already be in an unsafe or unknown state.
- `safe_state`: zero, disable, standby, or otherwise place outputs into a non-measurement safe state.
- `preflight`: safety gates that must be explicit user-visible actions, not hidden conveniences.
- `baseline`: reset/initialize/known-state setup when it is needed before other work and does not claim A verification.

P1 candidate B categories:

- `maintenance`: self-test, self-calibration, diagnostics, and long-running health operations.
- `preparation`: controlled state preparation such as SMU baseline settings, ASU/SCUU paths, WGFMU warning policy, or EasyEXPERT standby/zero-cancel setup.
- `correction`: fixture-dependent correction and compensation work, including CMU open/short/load, phase compensation, QSCV offset cancel, and EasyEXPERT zero-cancel.

P2 candidate B categories:

- Reversible policy or convenience flows that need more query/restore atoms before they deserve P0/P1 status.
- Narrow target-specific wrappers that duplicate a broader P1 preparation or correction family.

### Why

B flow taxonomy should be risk-aware without exploding into all B atom categories. The current B atom category list is correct for atoms, but it is too granular for flow families. A useful B flow name should tell the operator whether they are invoking an emergency response, a safe-state transition, a preflight gate, a baseline reset, maintenance, preparation, or correction.

This also avoids the misleading pattern where `output`, `routing`, `calibration`, and `policy` each become top-level flow families even when a real flow composes several of them.

### Examples only

- `B_flow_emergency_b1500_abort_zero`
- `B_flow_safe_state_b1500_zero_disable`
- `B_flow_preflight_b1500_gate`
- `B_flow_baseline_b1500_reset_initialize`
- `B_flow_maintenance_b1500_self_test_calibration`
- `B_flow_preparation_smu_baseline`
- `B_flow_preparation_asu_low_current_path`
- `B_flow_preparation_scuu_path`
- `B_flow_correction_cmu_open_short_load`
- `B_flow_correction_qscv_offset_cancel`
- `B_flow_safe_state_easyexpert_abort_standby`

## Recommended AB_flow Taxonomy

### Naming pattern

Use workflow intent first, then endpoint/scope, then outcome:

```text
AB_flow_{workflow_intent}_{scope}_{outcome}
```

Recommended current AB workflow-intent families:

- `startup`
- `shutdown`
- `recovery`
- `maintenance`
- `preparation`
- `correction`
- `configuration`

AB names should not mirror A or B atom categories. AB flows are user-visible workflows that combine phases:

- observe/discover with A
- act/change state with B
- verify/log with A

### Categories

P0 candidate AB categories:

- `startup`: establish a safe, observed session or endpoint baseline before future measurement work.
- `shutdown`: collect/preserve readbacks as needed, transition outputs/state safely, and close context.
- `recovery`: emergency or fault response where B action may need to run before full A observation.

P1 candidate AB categories:

- `maintenance`: self-test, calibration, and diagnostics with pre/post evidence.
- `preparation`: prepare non-measurement state, parser context, routing, workspace context, or WGFMU baseline with verification.
- `correction`: fixture-dependent correction/compensation workflows with preflight and post-readback evidence.

P2 candidate AB categories:

- `configuration`: optional client-observation setup such as polling/SRQ behavior.
- Cross-endpoint orchestration helpers that only sequence multiple focused AB flows and do not add new safety semantics.

### Why

AB flows are the most complex and should be classified by workflow intent rather than atom taxonomy. Their value is not that they contain A and B pieces; their value is that they package an auditable procedure with a clear user reason.

For example, `AB_flow_recovery_b1500_emergency_zero` is easier to reason about than a name that tries to encode `A_snapshot + B_output + A_error + A_snapshot`. The internal phase structure should appear in documentation and return payloads, not in the name.

### Examples only

- `AB_flow_startup_flex_safe_session`
- `AB_flow_recovery_b1500_emergency_zero`
- `AB_flow_shutdown_flex_safe_session`
- `AB_flow_recovery_b1500_reset_rediscover`
- `AB_flow_maintenance_b1500_self_test_calibration`
- `AB_flow_preparation_b1500_nonmeasurement_baseline`
- `AB_flow_preparation_asu_low_current_path`
- `AB_flow_correction_cmu_open_short_load`
- `AB_flow_startup_wgfmu_safe_baseline`
- `AB_flow_recovery_easyexpert_abort_standby`
- `AB_flow_shutdown_easyexpert_workspace`

## Migration Guidance From Old Drafts

For A flows:

- Replace old `b1500` naming with `flex` when the flow is about the direct B1500A FLEX/GPIB/VISA interface.
- Keep `wgfmu` for WGFMU library/session flows.
- Keep `easyexpert` for EasyEXPERT remote flows unless a later atom rename shortens it.
- Preserve the old intent when it is already good: `discover`, `snapshot`, `drain`, `collect`, `fetch`, `select`, `teardown`.
- Move old `browse_*` flows to P2 unless they add behavior not covered by a richer catalog/discovery flow.

Conceptual mapping:

- Old `A_flow_discover_b1500_session` family -> `discover` + `flex`.
- Old `A_flow_snapshot_b1500_status` family -> `snapshot` + `flex`.
- Old `A_flow_drain_b1500_errors` family -> `drain` + `flex`.
- Old `A_flow_collect_b1500_output_buffer` family -> `collect` + `flex`.
- Old EasyEXPERT workspace/catalog/select flows -> `discover`, `select`, or `teardown` + `easyexpert`.

For B flows:

- Map emergency abort/zero flows to `emergency`.
- Map zero/disable/standby flows to `safe_state`.
- Map preflight/interlock gates to `preflight`.
- Map reset/initialize and WGFMU baseline flows to `baseline` when they establish known state.
- Map self-test/calibration/diagnostic flows to `maintenance`.
- Map SMU settings, ASU/SCUU paths, warning policy, and similar setup flows to `preparation`.
- Map CMU/QSCV/EasyEXPERT zero-cancel and fixture-dependent compensation flows to `correction`.

For AB flows:

- Old safe-session entry flows -> `startup`.
- Old emergency recovery and abort/recover flows -> `recovery`.
- Old safe shutdown and workspace teardown flows -> `shutdown`.
- Old self-test/calibration brackets -> `maintenance`.
- Old non-measurement baseline and path setup flows -> `preparation`.
- Old CMU/QSCV/zero-cancel verified flows -> `correction`.
- Old polling/SRQ verified flow -> P2 `configuration`, unless later safety requirements make it a startup/preparation prerequisite.

Migration should update exact atom references only after the flow taxonomy is accepted. This proposal is only about naming families and conceptual placement.

## Anti-Patterns / Rejected Categories

Reject `full_system`, `full_station`, or `everything` as flow families.

- They hide transport boundaries and encourage flows that span FLEX, WGFMU, and EasyEXPERT failure modes without a clear reason.

Reject `safe` as a standalone category.

- Safety is a property to prove with gates, return payloads, and verification. Names should say what the flow does: `emergency`, `safe_state`, `preflight`, `startup`, `shutdown`, or `recovery`.

Reject direct mirroring of all B atom categories as B flow families.

- `safety`, `output`, `lifecycle`, `diagnostic`, `calibration`, `routing`, `correction`, and `policy` are useful atom categories, but B flows often compose several of them. Copying all eight into flow taxonomy creates unnecessary categories.

Reject `lifecycle` as a top-level AB family.

- It is too broad. Use `startup`, `shutdown`, `recovery`, `maintenance`, or `preparation`.

Reject `diagnostic` as a broad flow family.

- For A, diagnostics are usually `snapshot` or `drain`. For B/AB, diagnostics are usually `maintenance` unless they are part of recovery.

Reject `calibration` as one undifferentiated flow family.

- Instrument self-calibration, EasyEXPERT zero-cancel, CMU open/short/load correction, and QSCV offset cancel have different fixture and risk semantics. Use `maintenance` for instrument health and `correction` for fixture-dependent compensation.

Reject target-only flow names.

- Names such as `AB_flow_b1500_setup` or `B_flow_cmu_prepare` do not explain operator intent and will invite combinatorial expansion by target.

Reject measurement-like A/B/AB categories before C exists.

- `measure`, `run`, `sweep`, `iv`, `cv`, `pulse`, and `app_test_run` belong to future C/ABC design, not current A/B/AB non-measurement flows.

## Future C_flow And ABC_flow Naming Rules

Future `C_flow_*` should likely be measurement-intent first:

```text
C_flow_{measurement_family}_{interface_or_target}_{recipe_scope}
```

Candidate measurement families might include `iv`, `cv`, `pulse`, `qscv`, `sampling`, or `easyexpert_app`, but they should be decided when C atoms exist. C names should not inherit A's `discover/snapshot` categories or B's safety/risk categories as their primary axis.

Future `ABC_flow_*` should likely be experiment/workflow-intent first:

```text
ABC_flow_{experiment_intent}_{measurement_family}_{scope}
```

An ABC flow should describe a complete runbook-level outcome: observe context, gate safety, prepare state, execute measurement, collect results, verify final state, and recover/shutdown on failure. It should not encode every A/B/C phase in the name.

Likely rules:

- Keep A/B/C class prefixes meaningful, but do not force future flow names to copy atom categories.
- Use measurement family for C because measurement technique is the user's primary intent.
- Use workflow intent for ABC because it is a whole experiment procedure.
- Keep interface/target as a second or third token only when it changes execution semantics.
- Do not create `ABC_flow_full_system_*` unless the station-level safety model and failure handling are explicit.

## Open Questions For Parent/User

- Should A flow names use `A_flow_discover_flex_session` as recommended here, or should they match A atom sorting more closely as `A_flow_flex_discover_session`? I recommend intent-first for flows, but interface-first is defensible if Cursor tool-list grouping by session is more important.
- Should `easyexpert` remain fully spelled in flow names, matching current atoms, or should a future short token such as `eex` be reserved only if atoms are renamed too?
- Should `safe_state` be accepted as a B flow family token, or should it be split into `zero`, `disable`, and `standby` outcomes under a broader `safety` family? I recommend `safe_state` to avoid too many categories.
- Should `configuration` remain P2 for AB flows, or does SRQ/polling setup become P1 once query/restore atoms exist?
- Should EasyEXPERT zero-cancel be treated as `correction` consistently, even though current atoms categorize it as `calibration`? I recommend `correction` at the flow level because the workflow resembles compensation/cancel bracketing more than instrument health maintenance.
