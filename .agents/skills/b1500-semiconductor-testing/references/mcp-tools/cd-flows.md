# CD Flow MCP Tools

CD flows are fake measure-then-interpret compositions: exactly one C flow invocation
produces the whole dataset, the D flow with the same name interprets that flow's
designated data record unmodified, and the archive D flow records the attempt. They
never call A/B tools or C atoms directly, never retry or adapt the measurement based on
a D product, perform no cleanup and write no files.

```text
CD_flow_<operation>_<domain>_<subject>
```

`CD_flow_X` exists only if `D_flow_X` exists; `archive`, `render` and `replay` never get
CD names. The C flow is chosen by the closed, required `acquisition.kind`
(`c_flow = "C_flow_" + kind`), echoed as `c_flow` and in `flows_called`. Four tools are
registered.

**Phase status (user decisions U1, U7, U8):** every D child is a placeholder stub and
CD stays fake-only: real ABC transactions must run C -> outer safe state -> D -> archive.
The biased staircase C flow (U8) anchors `CD_flow_analyze_iv_transfer`. Contract:
`tmp/cd_flow_design_arbitration.md`; typed models live in
`src/b1500_test_agent/schemas/cd_flow.py`.

## Phases

1. **expect:** `D_atom_ingest_request_build_expectation` from the typed C request, before
   measuring. An `ok: false` here stops the CD: nothing is measured, nothing archived.
2. **measure:** `C_flow_<kind>`, called exactly once (even when it fails).
3. **interpret:** the matching `D_flow_*`, only when the C flow reached
   `simulated_complete` and its designated read record is `received` or `empty`. The
   expectation ProductRef is handed over, so the D flow records its own build_expectation
   as optional-skipped (`expectation_supplied`). Then the P1 opt-in
   `D_atom_assess_dataset_check_envelope` when `envelope` is declared (escalates, never gates).
4. **archive:** `D_flow_archive_run_bundle` whenever measure was attempted, with the
   expect, measure and interpret envelopes plus upstream evidence (planned paths only).

## CD Flow Tools

| CD flow | Pri | `acquisition.kind` (closed) | Interpret D flow | Request |
|---|---|---|---|---|
| `CD_flow_qualify_iv_dataset` | P0 | `spot_smu_iv`, `sweep_smu_staircase`, `pulse_smu_spot` | `D_flow_qualify_iv_dataset` | `CdQualifyIv` |
| `CD_flow_screen_iv_leakage` | P0 | `spot_smu_iv`, `sweep_smu_staircase` | `D_flow_screen_iv_leakage` | `CdScreenIvLeakage` |
| `CD_flow_analyze_iv_transfer` | P1 | `sweep_smu_staircase_biased` | `D_flow_analyze_iv_transfer` | `CdAnalyzeIvTransfer` |
| `CD_flow_qualify_cv_dataset` | P2 | `spot_cmu_impedance`, `sweep_cmu_cv`, `sweep_cmu_cf`, `sweep_cmu_ac_level`, `pulse_cmu_spot`, `pulse_cmu_cv` | `D_flow_qualify_cv_dataset` | `CdQualifyCv` |

Ordered calls for `CD_flow_screen_iv_leakage` with `kind = sweep_smu_staircase`:

1. `D_atom_ingest_request_build_expectation`
2. `C_flow_sweep_smu_staircase` -> `C_atom_smu_configure_integration`,
   `C_atom_smu_set_measurement_ranging`, `C_atom_smu_set_measurement_mode`,
   `C_atom_smu_configure_sweep_timing`, `C_atom_smu_configure_sweep_abort`,
   `C_atom_smu_configure_staircase_sweep`, `C_atom_smu_execute`,
   `C_atom_smu_read_measurement_data`
3. `D_flow_screen_iv_leakage` -> `Q_IV` steps 2-8 (step 1 optional-skipped),
   `D_atom_extract_leakage_current`, `D_atom_assess_value_check_limits`
4. `D_flow_archive_run_bundle` -> `D_atom_archive_run_build_manifest`,
   `D_atom_archive_run_write_bundle` (planned paths only)

With `kind = spot_smu_iv`, step 2 replaces timing, abort and staircase with
`C_atom_smu_force_voltage` (6 atoms). `atoms_called` lists direct and nested atoms in
execution order.

## C Execution States and the Handoff

The designated data record is the single read-phase record of the kind's catalog read
atom (`C_atom_smu_read_measurement_data` or `C_atom_cmu_read_measurement_data`) with
status `ok`. `handoff = {state, source_atom, child_index, atom_index, element_count,
reason}`; a content hash waits for G1. `outputs.data` is never used.

| C child result | `handoff.state` | interpret | archive | CD `ok` | `partial` | skip reason |
|---|---|---|---|---|---|---|
| `simulated_complete`, designated read >= 1 element | `received` | runs | runs | from children | from children | - |
| `simulated_complete`, designated read 0 elements (fake norm) | `empty` | runs, warning "Empty synthetic data is not evidence of quality." | runs | from children | from children | - |
| `simulated_complete`, designated record missing | `no_data` | skipped | runs | true | true | `c_no_data_record` |
| `configuration_only` | `no_data` | skipped; C gaps copied to `contract_gaps` | runs | true | true | `c_configuration_only` |
| `awaiting_completion` | `pending` | skipped; hand-off warning copied | runs | true | true | `c_awaiting_completion` |
| `failed` (`ok: false`), exception or non-dict | `no_data` | skipped | runs | false | true | `c_failed` |
| `fake` not true or `hardware_touched` not false | `no_data` | stopped | stopped | false | true | `c_unexpected_marker` |

Admitted kinds cannot reach the guarded rows with valid requests; tests reach them by
monkeypatching. A configuration record whose parameters are named `measurement` (the
high-speed spot configure atom) never counts as data. `execution_state` is the C
child's, `failed` when the C flow raised, or `not_run` when expect failed.

## Request Contract

`acquisition` is a discriminated union (published as `oneOf` with a `const` kind per
branch): `{kind: Literal, request: <typed C request>}`, required, with no default kind
or request. Shared fields: `channel_roles` (required), `upstream_evidence` (<= 16,
caller-held A/B envelopes), `trust_policy` (U3 default, echoed), `envelope` (P1 opt-in
audit limits plus `criteria_source`), `intent_note`, `station{name, sha256}`. Per flow:
`leakage` (screen, the D `LeakageSpec`), `transfer` (analyze, the D `TransferSpec`),
`imp_model` (cv; must equal `acquisition.request.model`, CG2).

Validators run before any child call (`ValidationError`, zero calls):

- `request.run.collect` is true; `run.max_items >= expected points x measured channels`
  (1 for spot and pulsed spot, `steps` for sweeps; the biased staircase counts its
  listed measured channels);
- every measured channel has exactly one role, and roles name only measured channels
  (transfer: roles may also name the swept and bias channels of the biased staircase);
- every `upstream_evidence` envelope names its tool (`flow` or `atom`), because the
  archive phase records envelopes by name;
- screen: voltage source, `ranging.measure_function == "current"`, `leakage.terminal`
  is the role of `request.channel`, bias points inside `[min(start, stop), max(start,
  stop)]` (staircase) or equal to the spot `level`, criteria in A with every limit below
  `compliance` (CD11: at or above compliance the reading clamps). The bias-point and
  CD11 rules are the D validator (`check_leakage_against_request`), called with
  `request.channel`;
- transfer: voltage-swept gate whose role is `gate_terminal`; `drain_terminal` is the
  role of exactly one voltage-biased channel that is measured with
  `measure_function == "current"`; `vds` equals that bias level; on/off gate biases lie
  inside the sweep;
- cv: frequency and AC-level sweep endpoints are positive; the typed C request
  (`CmuPositiveSweep`) rejects them, so CD needs no own check;
- criteria, methods and `criteria_source` are required (U4); no method aliases.

## Response and Failure Contract

```text
flow, flow_class: "CD", category, domain, subject, purpose, c_flow, d_flow,
fake (AND of children), hardware_touched (OR), ok, partial, destructive (= C), consumptive (= C),
phases{expect[], measure[], interpret[], archive[]} (child indices, names, status),
flows_called, atoms_called (direct + nested, ordered),
child_results[{phase, name, kind: c_flow|d_flow|d_atom, inputs, input_refs, timestamp,
  optional, reason, status, result, error?}],
execution_state (= C or not_run), measurement_completed: false, simulation_completed (= C),
handoff{...}, analysis_state (D aggregate or not_run), analysis_completed: false,
data_origin, synthetic, inputs (request dump),
outputs{products{}, trust_level, verdict, verdict_scope, evidence_citation{eligible,
  blockers[], external_requirements}, escalations[], archive{manifest_ref, planned_paths,
  artifact_written: false, write_refusal[]}},
required_preconditions, contract_gaps, findings, warnings (prefixed by child), assumptions,
evidence_missing, side_effects{hardware: "none", filesystem_writes: [], artifact_written: false},
cleanup (C block + analysis_side_effects: "none"),
audit{phase_order, child_count, skipped_children, skip_reasons, consumptive_children},
error{type, message, at} (only when ok=false)
```

- **`ok`** means the composition did not fail; `partial` is read separately (unlike AB's
  `ok = not partial`). Stub norm on a completed read: `ok: true`, `partial: false`,
  `analysis_state: not_computed`, `trust_level` and (screen) `verdict` `synthetic_only`,
  `evidence_citation.eligible: false` with blockers `synthetic_origin` and
  `analysis_not_computed`.
- **Records once.** The C envelope is kept once, in the measure child. The D child gets
  it by reference (`input_refs`), D atoms echo only summaries, and the archive child
  echoes envelopes by name.
- **Failure by phase:** expect fails -> stop, nothing measured, no archive; measure fails
  -> interpret skipped (`c_failed`), archive runs, `ok: false`; interpret fails or taint
  violation -> remaining interpret skipped, archive runs, `ok: false`; archive fails ->
  `ok: false`, `partial: true`; unexpected marker anywhere -> stop everything (the archive
  is recorded as skipped). Error types: `c_failed` for the measure phase, the child's
  error type for D children, `taint_violation`, `unexpected_marker`, `internal_error`.
- **Taint.** CD checks every D child against synthetic evidence: a `pass`/`fail`,
  `trusted`/`trusted_with_flags` label or a stronger origin is a `taint_violation`;
  `verdict` and `trust_level` become null, the child is retained, a finding records the
  violation and the archive still runs. Caller-passed A/B evidence is forwarded to the
  D flow's `check_context`, marked `evidence_unverified`, and can never raise trust or
  origin.
- **A/B are reported, never called.** `required_preconditions` is the C child's list
  plus D children's `required_inputs` that name A/B tools.
- **Cleanup.** CD performs none and is not a cleanup boundary; it copies the C
  `cleanup` block (`owner: outer_ABC_transaction`, `performed: false`). Failure cleanup
  must be installed by the outer transaction before CD is called.
- **Archive.** Always planned when measure was attempted; `write_refusal: [fake_mode,
  synthetic_origin]`, relative `planned_paths`, no files. Every envelope is recorded:
  the CD children (expect atom, C flow, D flow, optional envelope atom) then all
  upstream evidence. The archive cap `MAX_ARCHIVE_ENVELOPES` = 20 is derived from the
  CD maximums (1 C flow + 3 D children + 16 upstream), so nothing is ever dropped.

## Boundary vs Recipes/ABC

A composition is a CD flow only if one C flow invocation produces the whole dataset,
the C kind passes the uniform-handoff rule, the product is a catalog D analysis whose
device-dependent values are declared with a `SourceRef`, no decision depends on the D
result, and no A/B action is needed between measure and interpret. Id-Vd families
(Ron), hysteresis double sweeps, FeFET programs, PUND, endurance, retention, BTI,
breakdown, leakage-then-CV and EasyEXPERT analysis stay in recipes/ABC. CD and D never
read `references/devices` or `references/recipes`; ABC resolves them and passes values
plus their `SourceRef`.

## Reserved / Not Registered

- `CD_flow_qualify_timeseries_dataset`: WGFMU reads have no time axis (G4); the D flow
  `D_flow_qualify_timeseries_dataset` stays registered.
- High-speed SMU spot (inline status-less sample, G3) and CMU C-t (ingest undesigned)
  kinds are held.

## Known Gaps

- The expect-phase expectation is built from the typed C request only, with no origin
  evidence, so it defaults to `synthetic` and (weakest wins) would taint a future real
  run. Acceptable while CD is fake-only (U7); resolve before any real-mode CD or ABC use
  of these helpers.
- Other CD gaps (for example CG4, the index-based handoff locator, and CG5, unverifiable
  caller evidence) are listed in `tmp/cd_flow_design_arbitration.md` section 11.

## Sources and Implementation

- `tmp/cd_flow_design_arbitration.md`: phases, handoff table, request and response contract, U7/U8.
- `src/b1500_test_agent/mcp/cd_flows.py`: phase runner and tools.
- `src/b1500_test_agent/schemas/cd_flow.py`: discriminated acquisitions and validators.
- `tests/test_cd_flows.py`: discovery, boundary, order, states, expect, taint, validators, archive, hygiene.
