# D Flow and CD Flow Design Proposal (opus55b)

Date: 2026-11-17

Status: design proposal for arbitration. Planning only, no implementation code.

Binding inputs: `tmp/d_atom_arbitration.md` (D atom names, stages, envelope, taint, `ok`
semantics, P0 set). Precedents: `tmp/c_flow_design_arbitration.md`,
`tmp/ab_flow_design_arbitration.md`, `tmp/b_flow_design_arbitration.md`,
`tmp/a_flow_arbitration.md`, `tmp/flow_taxonomy_proposal_{opus48,gpt55}.md`, forward hooks
in `tmp/d_atom_candidates_opus55{a,b}.md`. Code: `mcp/{common,c_atoms,c_flows,ab_flows,server}.py`,
`schemas/c_flow.py`, `tests/test_c_flows.py`. References: `mcp-tools/{c-flows,ab-flows,c-atoms}.md`,
`references/recipes/*`, `references/devices/*`.

**Settled user decisions (no longer provisional):**

- **U1 (departs from the arbitration's recommendation):** D atoms stay fake placeholder stubs in
  this phase. This proposal plans no real computation and no per-atom migration.
- **U2-U6:** the arbitration's recommended defaults apply. Archive writes happen in real mode
  only, under `data/`, write-once, and synthetic bundles are refused. The default fit-exclusion
  policy and 0.95 near-compliance flag apply. Criteria are mandatory with no repo defaults.
  D verdicts may serve as ABC evidence only (instrument origin, trust at least
  `trusted_with_flags`, `pass`, manifest, plus human approval). Offline ingest and re-decode are deferred.

Consequence of U1 for flows: every D and CD flow in this proposal is a composition over stubs.
`analysis_state` is always `not_computed` (or `not_run` when D is skipped), and
`analysis_completed` is always `false`. No number, trust grade above `synthetic_only`, or `pass`
can appear. Text that describes non-stub outcomes only defines contract semantics, so the
envelope is complete and testable. Nothing in this phase can reach those outcomes.

---

## 0. Summary

| Item | Proposal |
|---|---|
| D flow name | `D_flow_<operation>_<domain>_<subject>` |
| CD flow name | `CD_flow_<intent>_<object>_<subject>` (intent first, as in AB) |
| D flows | 7 registered (P0 2, P1 2, P2 3) |
| CD flows | 4 registered (P0 2, P1 1, P2 1). 2 analyze names are reserved, not registered. |
| D composition | D atoms only, flat (no nested D flows). This is the same-class rule of A/B/C flows. |
| CD composition | Exactly one anchored `C_flow_*` + at most one interpret `D_flow_*` + narrow D atoms (+ optional `D_flow_archive_run_bundle`). No C atoms, A or B. |
| CD phases | `expect` (D) -> `measure` (C) -> `interpret` (D) -> `record` (D). This mirrors AB observe/act/verify. |
| Interpret gate | Interpret runs only on a successful anchored data record after C `simulated_complete`. Configuration-only, pending, failed or handoff-blocked states skip D, and record still runs. |
| Fake-mode verdict | Always `synthetic_only` or `null`. A child that claims more is a `taint_violation`, which gives `ok:false`. |

---

## 1. Scope and Invariants

**D flows** are deterministic, hardware-free compositions of D atoms over evidence the caller
already holds (C or A envelopes, records, and declared context). They are replayable by
construction and also serve a future ABC after A-side collection.

**CD flows** are measure-then-interpret compositions. They run one C measurement composition
and hand its data record, unmodified, to one D interpretation. They are the cross-family layer
for C+D, just as AB is for A+B.

Neither layer ever:

- calls A/B atoms or flows. Session, preflight, interlock, correction, routing, buffer prep,
  waits, error drains and cleanup are reported as `required_preconditions`, never invoked.
- retries, adapts, extends or repeats a measurement based on a D product (verdict, trust or
  completeness).
- approves or gates safety. A failed expect phase is a fail-fast composition rule like Pydantic
  request validation, not an approval, and a passing one grants nothing.
- supplies default criteria, methods, terminal roles, IMP models or units (U4).
- reads station, device or recipe files. Criteria arrive as typed inputs with a `SourceRef`
  (name plus optional hash).
- writes files except through `D_atom_archive_run_write_bundle` inside
  `D_flow_archive_run_bundle` (binding #8, U2). In this phase that atom never writes.
- calls raw FLEX, evaluates expressions, or produces narrative text.

---

## 2. Naming Taxonomy

### 2.1 D flows: `D_flow_<operation>_<domain>_<subject>`

| Axis | Closed vocabulary | Meaning and justification |
|---|---|---|
| operation | `qualify`, `screen`, `analyze`, `archive` (reserved: `replay`, `render`) | **The product the flow guarantees:** a trust-graded dataset, a verdict against declared criteria, a parameter set without a verdict, or an audit bundle. Stage names (`ingest`, `extract`, `assess`) are not reused because a flow spans stages. A standalone `ingest` flow is rejected: it would hand out unqualified data. |
| domain | `smu`, `cmu`, `wgfmu`, `run` (reserved: `easyexpert`) | **The data source.** It fixes the ingest atom, the status table and the module-specific qualify checks. It equals the D ingest subject and the C object token, so the endpoint token is invariant across C, D and CD (taxonomy standing rule). `run` is source-agnostic audit. |
| subject | `iv`, `cv`, `timeseries`, `leakage`, `transfer`, `output`, `bundle` | **The data kind** for `qualify` (`iv`, `cv`, `timeseries`, matching the D qualify subjects), the curve kind for `screen` and `analyze` (`leakage`, `transfer`, `output`, `cv`, matching the D extract subjects), and `bundle` for `archive`. There are no device names and no measurement-family names (binding §4). |

Allowed matrix (adding a cell requires arbitration):

| operation | smu | cmu | wgfmu | run |
|---|---|---|---|---|
| qualify | `iv` | `cv` | `timeseries` | - |
| screen | `leakage` | - | - | - |
| analyze | `transfer`, `output` | (reserved `cv`) | - | - |
| archive | - | - | - | `bundle` |

### 2.2 CD flows: `CD_flow_<intent>_<object>_<subject>`

| Axis | Closed vocabulary | Meaning and justification |
|---|---|---|
| intent | `acquire`, `screen`, `analyze` | **The user outcome.** It sits one abstraction step above the C measurement family, following the AB precedent (category first) and the taxonomy rule. Each intent maps 1:1 to the interpret D operation: `acquire` -> `qualify`, `screen` -> `screen`, `analyze` -> `analyze`. `acquire` is preferred over `qualify` because the product includes the instrument-facing half. |
| object | `smu`, `cmu` (reserved: `wgfmu`) | **The C object token** of the anchored C flow, which is invariant. `spgu` is excluded because it is source-only. `easyexpert` is excluded because its data arrives by A fetch, which CD cannot call. High-power objects are excluded because they have no C flows. |
| subject | `acquire`: `staircase`, `spot`, `cv`. `screen`: `leakage`. `analyze` (reserved): `transfer`, `cv`. | **What the product is named by.** For `acquire` it is the measured shape, and each token maps to exactly one anchor C flow. For `screen` and `analyze` it is the D curve kind, with one fixed catalog anchor per flow, echoed as `c_flow`. |

Every CD flow has exactly one fixed anchor C flow and exactly one interpret D flow, and both are
catalog constants. A second anchor for the same intent and subject needs a new subject token
by arbitration. It must never be a caller-selected discriminator.

Rejected alternatives:

- **C-family first** (`CD_flow_sweep_smu_leakage`). This collides for CMU: `sweep_cmu_cv`
  could be acquire or analyze. It also drops the intent, and it invites one CD flow per C flow,
  which is the cross product the taxonomy forbids.
- **Four tokens** (`CD_flow_<intent>_<family>_<object>_<subject>`). It is unambiguous but
  breaks the three-token pattern every family uses.
- **A `measurement` discriminator union** inside one CD request. It makes tool semantics
  depend on input, produces `oneOf` MCP schemas, and widens the test matrix.

---

## 3. Composition Rules

### 3.1 D flows

1. D flows call only `D_atom_*`, serially, in a fixed catalog order. Atom names never come from
   the caller. Optional steps run only when a typed request field asks for them. Bounded
   repeats apply only to per-member loops (at most 16 datasets).
2. There are no nested D flows. Shared chains are code helpers (for example `_qualify_smu_steps()`),
   just as C flows share `_smu_setup()`.
3. **Verdict-bearing flows are self-contained from ingest.** `screen` and `analyze` always
   re-run the full qualify chain. They never accept a caller-supplied `TrustSummary`, because a
   caller (or an LLM) could fabricate `trusted`.
4. **Trust gates live in the atoms, not in the flow.** The flow always calls extract after grade,
   and the extract atom returns `not_extractable` itself (binding #7). The flow stops only on
   `ok:false`, an exception, `hardware_touched` not `False`, or a taint violation. Data outcomes
   never stop a flow.
5. **Stub chaining (needed because of U1).** Each step passes upstream products as
   `ProductRef{producer, output_fingerprint|null, analysis_state}`. A stub that receives a
   `not_computed` ref returns `not_computed`, not `rejected_input` (gap CG3).

### 3.2 CD flows

1. **The measure phase calls exactly one anchored C flow, exactly once.** CD never calls C atoms
   directly, because that would make CD a measurement designer and bypass `_compose`
   completion and gap semantics. It never calls a second C flow and never loops.
2. **The interpret phase calls exactly one D flow** (the operation mapped from the intent),
   plus optionally `D_atom_assess_dataset_check_envelope` when the request declares an `envelope`.
3. **Narrow D atoms** (the AB "narrow atom" precedent): `D_atom_ingest_request_build_expectation`
   in `expect`, and `D_atom_archive_run_build_manifest` in `record`. When `archive: true`, the
   record phase calls `D_flow_archive_run_bundle` instead, which contains the manifest step.
4. **A and B are reported, never called** (C and AB precedent). The caller may pass prior A/B
   envelopes (for example from `AB_flow_startup_flex_safe_session`,
   `A_flow_prepare_flex_output_buffer` or `AB_flow_correction_cmu_open_short_load`) as
   `evidence`. `D_atom_qualify_run_check_context` consumes them. Missing evidence goes into
   `evidence_missing` and caps trust. Caller-passed evidence is marked unverified (CG4).
5. **The expect phase runs before measure.** It builds the data contract from the typed C request
   (pre-registration: the expectation is fixed before data exists). If it returns `ok:false`
   (for example `context_missing`), CD does not run C.
6. **Handoff source.** CD takes data from the anchor's designated data record inside the C
   child's `atom_results` (SMU and CMU: the `read`-phase `C_atom_{smu,cmu}_read_measurement_data`
   record). It does not use `outputs.data`, which drops fields (G6). CD bypasses G6 by design.
   G1 still applies (no raw hash, contract echo or status tokens).
7. **Single-copy retention.** Measurement records are retained once, in the C child. D child
   inputs reference them by `{child_index, atom, sha256, count}` and never copy them. This keeps
   100,000-point envelopes bounded and audit-complete.

### 3.3 C execution states (the interpret gate)

The rule is that D analysis never runs on missing or pending data. **Missing** means there is
no successful anchored data record. **Empty** means the read succeeded and returned zero
elements, which is the fake norm (`rows: []`). D does run on empty data, because empty is a
completeness finding, not missing data.

| C child result | `handoff.state` | interpret | record | CD `ok` | `partial` |
|---|---|---|---|---|---|
| `simulated_complete`, data record ok, non-empty | `received` | run | manifest (+ archive if requested) | true | false |
| `simulated_complete`, data record ok, empty | `empty` | run. A real completeness check must flag 0 received; stubs return `not_computed`. Warning: empty synthetic data is not evidence of quality. | yes | true | false |
| `simulated_complete`, anchor has a blocking handoff gap (none in the registered set; for example WGFMU G4) | `blocked` | skipped, reason lists the gap | yes | true | true |
| `configuration_only` (C `contract_gaps`) | `no_data` | skipped, reason = C gaps | yes | true | true |
| `awaiting_completion` | `pending` | skipped. Completion check and read belong to outer A/ABC, which may later call the D flow directly with the collected records. | yes | true | true |
| `failed` (C `ok:false`) | `no_data` | skipped | yes. The manifest preserves the failure, and archive is allowed in real mode (U2) for audit. | false | true |
| exception, unexpected non-fake C, or `hardware_touched` not `False` | `no_data` | stopped | manifest only, never archive | false | true |

`run.collect=False` is rejected at request validation because it is structurally incompatible
with every CD intent. CD never waits, polls, reads buffers or retries.

---

## 4. Boundary: CD Flows vs Recipes/ABC

A composition is a CD flow only if **all** of these hold. Otherwise it belongs in a recipe or ABC.

1. **One measurement.** It runs one C flow invocation, with no sequences (stress/read,
   program/read, pre-check then measure), no loops over bias conditions or sites, and no
   cycling or time series of runs.
2. **Curve-kind product.** It returns a qualified dataset, a named-quantity verdict, or a
   parameter set built only from catalog D atoms.
3. **Device-agnostic.** There are no device names. Device semantics enter only as declared
   `ChannelRole` terminals and criteria with a `SourceRef`. The same flow serves a MOSFET gate,
   a MOS capacitor dielectric or a FeFET gate.
4. **No actuation decisions.** It has no stop conditions beyond C's own abort and compliance,
   no next-measurement choice, and no gating of later instrument work on a D verdict.
5. **No A/B work.** Session, approval, safety, routing, correction and cleanup stay outside.

| Composition | Placement | Why |
|---|---|---|
| Staircase IV + trust grade | CD `acquire_smu_staircase` | One run, generic product |
| Terminal leakage over a sweep + declared limit | CD `screen_smu_leakage` | One run, generic quantity; it is the data half of the AGENTS-required leakage validation |
| Single transfer curve + Vth/gm/SS/on-off | CD `analyze_smu_transfer` (reserved; no C anchor, CG1) | Generic once a biased-staircase C anchor exists |
| Id-Vg recipe (device limits, Vds choice, polarity, pre-leakage check, approval, cleanup) | recipe/ABC | Device envelope, precondition chain, approval |
| Id-Vd family (one sweep per Vgs) and Ron | ABC (C xN) + `D_flow_analyze_smu_output` | Several measurements |
| Leakage screen -> CV | ABC | Precondition chain (U5 evidence + approval) |
| FeFET write/read, memory window, PUND, endurance, retention, BTI, breakdown | recipe/ABC | Sequences, stress, destructive, device-specific |

**How criteria are passed (U4, decided).** Each criterion, method, window or bias point is a
required typed field with no default (`Criterion`, `VthSpec`, `LeakageSpec` and others) plus
`criteria_source: SourceRef{kind: device|recipe|caller, name, sha256?}`. A missing field fails
Pydantic validation before the first call. The recipe or ABC layer loads the device profile or
recipe and passes values. D and CD never read the YAML. `references/devices/mosfet.example.yaml`
cannot feed these specs yet (G13).

---

## 5. Catalog

### 5.1 Shared D qualify chain (`QSMU`)

`D_atom_ingest_request_build_expectation` (recorded as optional-skipped when `expectation` is
supplied, for example by the CD expect phase) -> `D_atom_ingest_smu_build_dataset` ->
`D_atom_qualify_dataset_classify_status` -> `D_atom_qualify_dataset_check_completeness` ->
`D_atom_qualify_iv_check_compliance` -> `D_atom_qualify_iv_check_resolution` -> optional
`D_atom_qualify_iv_check_source_tracking` (only when `source_tracking` tolerance is declared) ->
`D_atom_qualify_run_check_context` -> `D_atom_qualify_dataset_grade_trust`.

This is the binding P0 path without its tail.

### 5.2 D flows (7)

| Flow | Pri | Ordered atom sequence | Request | Outputs | Status |
|---|---|---|---|---|---|
| `D_flow_qualify_smu_iv` | P0 | `QSMU` | `DQualifySmuIv` | `dataset_ref`, `TrustSummary` (trust level, fit-mask ref, reasons, missing checks), check reports, findings | stub composition |
| `D_flow_screen_smu_leakage` | P0 | `QSMU` -> `D_atom_extract_leakage_current` -> `D_atom_assess_value_check_limits` | `DScreenSmuLeakage` | above + leakage `ExtractionResult[]` (bound-aware), `verdict`, `verdict_scope` | stub composition |
| `D_flow_analyze_smu_transfer` | P1 | `QSMU` -> opt `D_atom_shape_dataset_split_segments` -> opt `D_atom_derive_curve_compute_derivative` -> opt `D_atom_extract_transfer_vth` -> opt `D_atom_extract_transfer_gm_max` -> opt `D_atom_extract_transfer_ss` -> opt `D_atom_extract_transfer_on_off` -> opt `D_atom_extract_transfer_voltage_shift` | `DAnalyzeSmuTransfer` | `ExtractionResult[]`, no verdict | stub composition; offline or ABC use; no CD anchor yet |
| `D_flow_archive_run_bundle` | P1 | `D_atom_archive_run_build_manifest` -> opt `D_atom_render_dataset_build_table` -> `D_atom_archive_run_write_bundle` -> `D_atom_archive_run_load_bundle` (optional-skipped unless `artifact_written`) | `DArchiveRunBundle` | `RunManifest`, hash, `planned_paths`, `artifact_written`, `hash_ok` | never writes this phase (synthetic refused, U2) |
| `D_flow_analyze_smu_output` | P2 | per member (2-16): `QSMU` -> `D_atom_shape_dataset_stack_family` -> `D_atom_extract_output_ron` | `DAnalyzeSmuOutput` | family view ref, Ron per segment | stub composition; members come from separate C runs (ABC) |
| `D_flow_qualify_cmu_cv` | P2 | `D_atom_ingest_request_build_expectation` -> `D_atom_ingest_cmu_build_dataset` -> `D_atom_qualify_dataset_classify_status` -> `D_atom_qualify_dataset_check_completeness` -> `D_atom_qualify_cv_check_correction` -> `D_atom_qualify_run_check_context` -> `D_atom_qualify_dataset_grade_trust` | `DQualifyCmuCv` | `dataset_ref`, `TrustSummary` (the CMU policy caps trust at `needs_review`) | CMU stub-gated (AGENTS) |
| `D_flow_qualify_wgfmu_timeseries` | P2 | `D_atom_ingest_request_build_expectation` -> `D_atom_ingest_wgfmu_build_series` -> `D_atom_qualify_dataset_check_completeness` -> `D_atom_qualify_timeseries_check_events` -> `D_atom_qualify_run_check_context` -> `D_atom_qualify_dataset_grade_trust` | `DQualifyWgfmuTimeseries` | `dataset_ref`, `TrustSummary` | WGFMU stub-gated; real input needs time arrays (G4) |

WGFMU skips `classify_status` because it has no per-point status codes. Channel status is
handled by `check_events`.

### 5.3 CD flows (4)

All four use the same phase skeleton:

1. **expect:** `D_atom_ingest_request_build_expectation`
2. **measure:** the anchor C flow
3. **interpret:** the D flow, then optionally `D_atom_assess_dataset_check_envelope`
4. **record:** `D_atom_archive_run_build_manifest`, or `D_flow_archive_run_bundle` when `archive: true`

| Flow | Pri | Anchor (measure) | Interpret D flow | Request | Key outputs | Status |
|---|---|---|---|---|---|---|
| `CD_flow_acquire_smu_staircase` | P0 | `C_flow_sweep_smu_staircase` | `D_flow_qualify_smu_iv` | `CdAcquireSmuStaircase` | `handoff`, `dataset_ref`, trust, findings, manifest | executable fake (C `simulated_complete`); trust `synthetic_only` |
| `CD_flow_screen_smu_leakage` | P0 | `C_flow_sweep_smu_staircase` | `D_flow_screen_smu_leakage` | `CdScreenSmuLeakage` | above + leakage results, `verdict` (`synthetic_only`), `verdict_scope` | executable fake. Covers the full binding P0 atom path. |
| `CD_flow_acquire_smu_spot` | P1 | `C_flow_spot_smu_iv` | `D_flow_qualify_smu_iv` | `CdAcquireSmuSpot` | as acquire | executable fake |
| `CD_flow_acquire_cmu_cv` | P2 | `C_flow_sweep_cmu_cv` | `D_flow_qualify_cmu_cv` | `CdAcquireCmuCv` | as acquire; CMU trust cap | fake only. Real C-V is blocked until correction, SCUU and leakage validation exist (AGENTS). Preconditions list CMU correction evidence and a U5-qualifying leakage verdict, which no fake run can provide. |

Reserved names, not registered: `CD_flow_analyze_smu_transfer` (anchor gap CG1) and
`CD_flow_analyze_cmu_cv` (correction gate; see §7).

### 5.4 Request sketches

These would live in `schemas/d_flow.py` and `schemas/cd_flow.py`, both on a `FlowModel` base
with `extra="forbid"` and `allow_inf_nan=False`. They reuse the binding shared models from
`schemas/analysis.py`.

```text
ChannelRole       {channel: Channel, terminal: TerminalName}            # declared; never inferred
SourceRef         {kind: device|recipe|caller, name: str, sha256: str|None}
EvidenceEnvelope  {envelope: dict (must carry flow|atom, fake, hardware_touched), note: str|None}  # max 16
DAcquisitionInput {acquisition: AcquisitionEvidence,   # records <= 100_000 (binding #16)
                   expectation: DataExpectation|None,  # None -> built from acquisition.request
                   channel_roles: list[ChannelRole] (min 1, required),
                   policy: TrustPolicy|None,           # None -> decided U3 default, echoed with version
                   evidence: list[EvidenceEnvelope] = [],
                   source_tracking: Quantity|None}     # enables the optional P1 check
DQualifySmuIv       = DAcquisitionInput
DScreenSmuLeakage   = DAcquisitionInput + leakage: LeakageSpec (required)
LeakageSpec         {terminal, bias_points: list[Quantity] = [], window: QuantityRange|None,
                     criteria: list[Criterion] (min 1), criteria_source: SourceRef}
                     # validator: at least one of bias_points/window; units V for bias, A for limits
DAnalyzeSmuTransfer = DAcquisitionInput + transfer: TransferSpec (required)
TransferSpec        {x_terminal, y_terminal, polarity: n|p, bias: Quantity,   # all required
                     parameters: set[vth|gm_max|ss|on_off|voltage_shift] (min 1),
                     derivative: DerivativeSpec|None, vth: VthSpec|None, ss: SsSpec|None,
                     on_off: OnOffSpec|None, segments: SegmentRule|None, criteria_source: SourceRef}
                     # validators: each requested parameter has its spec; derivative required for gm_max
                     # or vth.method == max_gm_linear_extrapolation; voltage_shift requires segments
VthSpec             {method: constant_current|max_gm_linear_extrapolation, icc: Quantity|None,
                     w_over_l: float|None}             # icc required for constant_current
DAnalyzeSmuOutput   {members: list[DAcquisitionInput] (2..16), outer_parameter {name, unit, values}
                     (len == members), ron_window: QuantityRange, criteria_source: SourceRef}
DQualifyCmuCv       = DAcquisitionInput + imp_model (typed Literal over the Table 4-16 IMP models, required),
                     monitor_columns: bool, sweep_kind: voltage|frequency|ac_level
DQualifyWgfmuTimeseries = DAcquisitionInput + measure_mode: voltage|current, event_plan: list[EventPlan] (min 1)
DArchiveRunBundle   {run_envelopes: list[dict] (min 1), dataset_ref: ProductRef|None, station: StationRef|None,
                     created_at: datetime|None, include_table: bool = True}   # no path fields at all

CdBase              {channel_roles (required), policy: TrustPolicy|None, evidence = [],
                     envelope: EnvelopeSpec|None, archive: bool = False, station: StationRef|None}
EnvelopeSpec        {limits: list[Criterion] (min 1), source: SourceRef}   # post-hoc audit, not a gate
CdAcquireSmuStaircase = CdBase + measurement: SmuSweep (required, no omitted-request default)
CdScreenSmuLeakage    = CdAcquireSmuStaircase + leakage: LeakageSpec (required)
CdAcquireSmuSpot      = CdBase + measurement: SmuSpot (required)
CdAcquireCmuCv        = CdBase + measurement: CmuSweep (required) + imp_model (required; CG2)
```

The CD structural validators run before any call. They are not a station policy:

- `measurement.run.collect` must be true.
- `run.max_items >= steps x measured channels` (conservative; exact accounting is CG7).
- Every role channel must be a measured channel, and the measured channel must have a role.
- `screen` additionally requires `source == voltage` and `ranging.measure_function == current`.
  `leakage.terminal` must be the role of `measurement.channel`, and bias points and window must
  lie within `[min(start, stop), max(start, stop)]` (D never extrapolates).

D and CD tools take a single required `request` parameter, as C flows do. There is no
omitted-request default, because roles and criteria have none.

---

## 6. Response and Failure Contract

### 6.1 D flow envelope

This extends the A/B/C flow envelope and is built by `_d_flow_response` in the style of `_compose`:

```text
flow, flow_class: "D", operation, domain, subject, purpose,
fake, hardware_touched: false, ok, partial, destructive: false, consumptive: false, deterministic: true,
atoms_called[], atom_results[{atom, stage, inputs (refs, never datasets), timestamp,
                              status: ok|error|skipped, optional, reason, result | error}],
inputs (scalar echo; record arrays replaced by {sha256, count, source_ref}), outputs{product refs},
analysis_state, analysis_completed: false, composition_completed,
data_origin, synthetic, trust_level, verdict, verdict_scope,
findings[{source_atom, check, severity, code, ...}], assumptions[], evidence_missing[],
required_inputs[], contract_gaps[],
provenance{flow_version, input_fingerprints[], upstream[], method_versions{atom: method},
           status_table_version, schema_version},
side_effects{hardware: "none", filesystem_writes: [], artifact_written: false, planned_paths: []},
warnings[], error{type, message} (only when ok=false)
```

### 6.2 CD flow envelope

This combines AB phases and child results with the C completion fields and the D analysis fields:

```text
flow, flow_class: "CD", intent, object, subject, purpose, c_flow, d_flow,
fake (AND of children), hardware_touched (OR of children), ok, partial,
destructive, consumptive (both from the C child; D children are always false),
phases{expect[], measure[], interpret[], record[]}, flows_called[], atoms_called[] (nested, ordered),
child_results[], inputs, outputs{handoff, dataset_ref, trust, results, verdict, envelope_audit, manifest},
execution_state, measurement_completed: false, simulation_completed (from C),
handoff{state: received|empty|blocked|no_data|pending, source_atom, child_index, element_count, reason},
analysis_state (+ "not_run"), analysis_completed: false,
data_origin, synthetic, trust_level, verdict, verdict_scope, escalations[],
findings[], evidence_missing[], required_preconditions[] (C union + D required_inputs that need A/B evidence),
contract_gaps[] (C gaps + handoff gaps G1/G3 + CD gaps),
cleanup{owner: "outer_ABC_transaction", performed: false, required: <C text>, analysis_side_effects: "none"},
side_effects{hardware: "fake_only", filesystem_writes: [], artifact_written: false, planned_paths: []},
warnings[], audit{phase_order, child_count, skipped_children, consumptive_children, retained_data_children},
error{type, message} (only when ok=false)
```

**Banned top-level keys** (extending binding #5 to D and CD flow envelopes): `status`,
`passed`, `result_code`, `outcome`, `rows`, `values`, `sample`, `measurement`. This keeps C-style
`_failed()` and output scrapers from misreading a D product. AB's free-text `outcome` is
therefore not carried over; `purpose` and `phases` replace it. Per-record `status`
(`ok|error|skipped`) inside `atom_results` and `child_results` keeps its existing audit meaning.

### 6.3 `ok`, `partial` and verdict

| Condition | ok | partial | analysis_state | verdict |
|---|---|---|---|---|
| Request schema invalid (missing criteria or roles, bad units, `collect=False`) | raises `ValidationError` before any call | - | - | - |
| A D child returns `ok:false` (`rejected_input`, `context_missing`, `unit_mismatch`, `size_limit`, `internal_error`) | false | true | `rejected_input` | null |
| C `failed`, exception, or unexpected non-fake child | false | true | `not_run` | null |
| Taint violation (§6.4) | false | true | child's state | null |
| C `configuration_only` or `awaiting_completion`, or handoff `blocked` | true | true | `not_run` | null |
| Interpret ran over stubs (the only reachable success in this phase) | true | false | `not_computed` | `synthetic_only` if an assess step ran, else null |
| Contract only (unreachable under U1): data fail, untrusted, `not_extractable`, inconclusive | true | false | `complete`, `not_extractable` or `inconclusive` | `fail`, `inconclusive` or `synthetic_only` |

`ok` means the composition did not fail (C and binding semantics). It never means good data or
an approved DUT. `partial` means a required step was skipped or failed, or C did not reach
`simulated_complete`. Optional-skipped steps (supplied expectation, unrequested extractions,
nothing written to load) do not set `partial`. `analysis_completed` and `measurement_completed`
are always false.

Two notes for a future ABC runner. AB sets `ok = not partial`; ABC must read `partial`
separately (CG8). An `escalate:true` envelope-audit finding is surfaced in `escalations[]` and
warnings but never changes `ok`.

### 6.4 Synthetic taint

- **T1.** The flow's `data_origin` is the weakest of: C child origin (`fake:true` or
  `outputs.synthetic:true` means synthetic), caller-declared origin, evidence envelopes, and D
  children's reported origins. A caller may lower the origin, never raise it.
- **T2.** No verifiable upstream envelope means `synthetic`, with finding `origin_unverified`. A
  standalone D flow cannot claim instrument origin from bare records.
- **T3.** The flow, not the stub, sets the provenance label: under synthetic origin,
  `trust_level` and `verdict` are `synthetic_only` when grade or assess ran. For fixture origin,
  `verdict_scope` is `fixture`. This is a label derived from evidence, not computation, so it is
  consistent with U1.
- **T4.** A child that reports `pass`, `trusted` or `trusted_with_flags`, or a stronger origin
  than the flow's, under synthetic or fixture origin is a `taint_violation`. The result is
  `ok:false`, later D steps stop, the verdict is null, the finding is retained, and nothing is
  archived. This is the analogue of the C runner's unexpected non-fake stop.
- **T5.** D children are accepted by `hardware_touched is False` (binding §6). Because U1 keeps D
  stubs fake in this phase, a D child with `fake:false` is additionally treated as unexpected
  (stop, `ok:false`). This guard is phase-specific.
- **T6.** U5 needs instrument origin and `pass`, so no CD output in this phase can serve as
  `leakage_check_passed` evidence. The CMU precondition chain is therefore unsatisfiable in
  fake mode, which is intended.

### 6.5 Stop-on-failure, audit retention and cleanup

- **Validation first.** Requests are validated before the first call. The first failure stops
  later work in its phase and all later phases, except that **record still runs** whenever
  measure was attempted (pure, inline manifest), as AB's verify does. Skipped children are
  recorded with a reason. Earlier evidence and child payloads are kept unchanged, with
  timestamps.
- **Phase-specific rules.** If expect fails, measure, interpret and record are skipped (nothing
  touched; the envelope is the audit). If interpret fails, the remaining interpret steps are
  skipped and record runs. If record fails, the result is `ok:false` and earlier evidence is
  kept.
- **Cleanup.** CD performs none. It copies the C `cleanup` block (`performed: false`) and adds
  `analysis_side_effects: "none"`. D creates no instrument or session state, and the record
  phase is audit, not cleanup. A CD result must never be presented as a safe-state transaction.
  In any future real use, interpret and record run after C returns and before outer cleanup.
  That bias-time ordering is OQ1.
- **Archive.** A CD flow may archive, but only through `D_flow_archive_run_bundle`, opt-in with
  `archive: true` (default false), under U2: real mode only, configured `data/` root, no path
  inputs, write-once and content-addressed. Synthetic bundles are refused and return
  `planned_paths` only. Fixture bundles go to a test temp directory. Instrument-reported
  failures are archivable for audit. Runner-contract violations (unexpected hardware, taint)
  are never archived. In this phase every CD run is synthetic, so `artifact_written` is always
  false.

---

## 7. Intentionally Not Added

| Candidate | Reason |
|---|---|
| `D_flow_ingest_*` | Unqualified data product. Ingest lives inside qualify. |
| `D_flow_replay_run_bundle` | Under U1, re-running stubs is meaningless (no algorithm versions to regress), and offline re-decode is deferred (U6). The `replay` operation name is reserved. |
| `D_flow_render_run_report` | Thin, and the report atom is P2. Render atoms are called directly. `render` is reserved. |
| `D_flow_qualify_easyexpert_*` | Blocked by G5 (A fetch returns `result: None`), and CD cannot call A. `easyexpert` is a reserved domain. |
| `D_flow_analyze_cmu_cv`, `CD_flow_analyze_cmu_cv` | Cox and Vfb need a passing correction check, and real C-V is blocked by AGENTS. No first-wave consumer. |
| `CD_flow_analyze_smu_transfer` | No C anchor holds a constant bias on a second channel while measuring it (CG1). The name is reserved. |
| CD over configuration-only anchors (synchronous, multi_channel, pulse sweep, pulsed bias, multi pulse, quasi, sampling, signal monitor, search) | Interpret could never run, so the flow would duplicate the C flow plus a manifest. Rule: **a CD anchor must be able to reach interpret in fake mode.** |
| `CD_flow_acquire_wgfmu_waveform` | Same rule. The WGFMU handoff is blocked by G4 (no time array or event structure). The `wgfmu` object is reserved. |
| CD over SPGU, EasyEXPERT remote, high-power | Source-only, A-side fetch, or no C flows. |
| `acquire` for high_speed, pulsed_spot, qscv, CMU spot/ct/pulsed | No first-wave consumer. G3 applies to inline samples, and QSCV is blocked by AGENTS. Add by arbitration with one subject token per anchor. |
| Breakdown screen | Destructive and needs approval. The atom is usable post hoc. Belongs in ABC. |
| Multi-anchor CD, CD calling C atoms, D flows calling D flows, caller-selected anchors | Break one-anchor auditability and the same-class rule. |
| "Measure until trusted", retry, adaptive range | D never drives C (binding §1). |
| Candidate B's `data_state` enum | Replaced by `handoff.state` + `analysis_state`, which do not overlap. |

---

## 8. Known Gaps (new; G1-G15 from the binding doc still apply)

| # | Gap | Owner |
|---|---|---|
| CG1 | `C_flow_sweep_smu_staircase` measures only the swept channel (`MM 2` with one channel) and forces no other channel. No executable C flow can produce a transfer curve, and multi-terminal leakage relies on the outer layer to hold the other terminals. Needed: a staircase with declared constant-bias channels and a multi-channel measurement list. | C round (OQ3) |
| CG2 | `CmuSetup.model: str` is a free string. D needs a typed IMP model (Table 4-16) to resolve columns. CD cannot check consistency between `measurement.model` and `imp_model`. | C schema |
| CG3 | D stubs must accept `ProductRef` placeholders with `analysis_state: not_computed` and return `not_computed`. Otherwise no D flow can chain in this phase. | D atom implementation |
| CG4 | Caller-passed A/B evidence envelopes are unauthenticated JSON (an LLM could fabricate them). Record them as `evidence_unverified`; they can never lift trust caps. Lifting needs in-process ABC passing or a server-side evidence registry. | kernel/ABC (OQ2) |
| CG5 | The C `atom_results` records have no stable record id. CD references by child index, atom name and canonical-JSON sha256. This complements G1 (`raw_sha256`). | C |
| CG6 | Bias-time and cleanup ordering: interpret and record run before outer cleanup. | ABC design (OQ1) |
| CG7 | `run.max_items` versus expected elements: the CD check is conservative (steps x channels). Exact element accounting depends on FMT, output mode and timestamps (`build_expectation`, a stub), so truncation is undetectable in this phase. | D/C |
| CG8 | AB sets `ok = not partial`, while C, D and CD treat `ok` as "composition not failed". A future ABC runner must choose one. Recommended: the C/D semantics, with `partial` read separately. | ABC |
| CG9 | Reference and registration work: `mcp-tools/d-flows.md`, `cd-flows.md`, README index, server docstring naming lines, capabilities keys `D_flows` and `CD_flows`. This depends on the D atom stubs existing first. | implementation |

---

## 9. Validation and Test Plan

Proposed files: `tests/test_d_flows.py` and `tests/test_cd_flows.py`. All tests are fake and
hardware-free.

1. **Discovery.** All 7 D and 4 CD tools are registered through FastMCP with a typed `request`
   schema. Names match the closed-vocabulary regexes and the allowed matrix. Capabilities list
   `D_flows` and `CD_flows`. Reference docs contain every registered name. Existing
   registrations and counts are unchanged.
2. **Boundary.** Spies on the A, B and C atom modules and on the A/B flows must see zero calls
   from D flows. CD calls exactly one C flow (the catalog anchor), exactly once, and no C atoms
   directly (C atoms appear only nested in the C child), and no A or B.
3. **Order.** Table-driven exact `atoms_called` for every flow, including optional-step on/off
   variants.
4. **Fake markers.** `fake` is true and `hardware_touched` is false everywhere.
   `analysis_completed`, `measurement_completed` and `artifact_written` are false, and
   `filesystem_writes` is empty, including with `archive: true`. `cleanup.performed` is false.
   `json.dumps(allow_nan=False)` succeeds.
5. **Taint.** No CD or D output ever has `verdict == "pass"` or a trusted level. `data_origin` is
   synthetic. Injected tainted children (`pass` or `trusted` under synthetic, a raised origin,
   or a D `fake:false`) give `taint_violation` and `ok:false`, later steps skipped, and no
   archive. A caller-declared `instrument` origin with fake evidence gives synthetic.
6. **Interpret gate.** Monkeypatch the anchor to return each execution state and verify §3.3
   row by row: interpret skipped or run, record always runs after measure, and `ok`, `partial`
   and `handoff.state` as listed. Empty `rows` gives handoff `empty`, interpret runs, and a
   warning is emitted.
7. **Failure injection.** Exceptions or `ok:false` in expect, the C flow, the D flow, the
   manifest and the bundle write. Earlier evidence is kept, later steps are skipped with
   reasons, and the C child payload is unchanged.
8. **`ok` versus data.** D children returning `not_extractable`, `inconclusive`, `fail` or
   `untrusted` (monkeypatched) keep `ok:true`.
9. **Mandatory criteria.** A missing criterion, method, role or `SourceRef` raises before any
   call (a spy sees zero calls). Schema introspection shows no default on any criterion or
   method field.
10. **Validators.** Rejected cases: bias points outside the sweep range, current source for a
    leakage screen, role and channel mismatch, `collect=False`, `max_items < steps`, and unit
    mismatch.
11. **Envelope hygiene.** Banned top-level keys are absent. Records appear once (in the C
    child) and D inputs carry references. Envelope size grows by O(1) with an extra D step for a
    100,000-point request.
12. **No retry.** The anchor call count is 1 regardless of any injected D verdict.
13. **Determinism.** The same request gives identical envelopes apart from timestamps and
    `computed_at`.

---

## 10. Implementation Footprint (for a later task)

- `schemas/d_flow.py` and `schemas/cd_flow.py`, both over `schemas/analysis.py` (binding models).
- `mcp/d_flows.py` (`_d_compose`, `D_FLOW_FUNCTIONS`, `register_d_flows`) and `mcp/cd_flows.py`
  (`_cd_compose` with AB-style `_call_step`/`_skip_step` phases, `CD_FLOW_FUNCTIONS`,
  `register_cd_flows`).
- `server.py` registration and docstring naming lines; capabilities keys.
- Reference docs under `.agents/skills/b1500-semiconductor-testing/references/mcp-tools/`.
- Order: the D atom stubs (with CG3), then D flows, then CD flows.

---

## 11. Open Questions for the User

These are deduplicated against U1-U6, which are all decided.

1. **OQ1: real-mode role of CD.** In a real transaction, CD would interpret and record before
   the outer cleanup, which extends DUT bias time by D latency. Should CD remain a fake,
   planning and contract composition, with real ABC transactions running
   `C_flow` -> B safe-state -> `D_flow` directly and reusing CD's handoff rules? Or should CD be
   allowed to wrap real execution with an explicit bias-time budget? **Recommended:** the former.
2. **OQ2: caller-supplied A/B evidence.** Should CD and D accept prior A/B envelopes passed in by
   the caller, given they can be fabricated? **Recommended:** accept them as
   `evidence_unverified`, recorded in the manifest but never able to lift trust caps, until an
   in-process ABC or a server evidence registry exists (CG4).
3. **OQ3: C-round addition for transfer curves.** Should the C catalog gain a generic staircase
   with declared constant-bias channels and multi-channel measurement? That would unblock
   `CD_flow_analyze_smu_transfer`, the core SMU IV analysis. The alternative is to leave
   transfer-curve measurement entirely to recipes/ABC. **Recommended:** add it to C. It is a
   measurement primitive (sweep plus held biases), not a device experiment.
