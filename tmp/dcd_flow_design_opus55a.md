# D Flow and CD Flow Design Proposal (opus55a)

Date: 2026-11-17

Status: independent proposal for arbitration. Planning only; no code. Binding inputs:
`AGENTS.md` and `tmp/d_atom_arbitration.md` (the D atom contract), with the user's
settlement of its section 9 applied:

| Item | Settled | Effect on this design |
|---|---|---|
| U1 | **Departs from the recommendation:** D atoms stay fake placeholder stubs in this phase. | Every D/CD flow is `fake: true` and returns `analysis_state: not_computed` at best. No real computation and no per-atom promotion path are planned. Flow contracts are written so they do not depend on whether an atom computes. |
| U2 | Writes only in real mode, under `data/`, JSON+CSV, write-once. Synthetic bundles are refused (planned paths only). Fixture bundles go only to a test temp dir. | No D/CD flow writes a file in this phase. The archive phase returns `planned_paths` and `artifact_written: false`. |
| U3 | Default fit-exclusion policy and near-compliance ratio 0.95. | Flows default `trust_policy` to that versioned policy and echo it. This is a data-trust policy, not a device criterion. |
| U4 | Extraction and acceptance criteria are mandatory, with no repo defaults. | Required schema fields. A missing criterion is rejected before the first child call, so in CD before any measurement. |
| U5 | ABC may cite D verdicts as evidence only (instrument origin, trust at least `trusted_with_flags`, `pass`, manifest, human approval). | Flows expose `evidence_citation` with the blockers that apply. It is a label, never a gate. In this phase it is always ineligible. |
| U6 | Offline ingest and re-decode deferred (P2). | No replay or import flow is registered. |

Read: `tmp/d_atom_arbitration.md`, both D atom candidates (forward hooks), the A/B/C/AB
flow arbitrations, both flow taxonomy proposals, `mcp-tools/{c-flows,ab-flows,c-atoms}.md`,
`mcp/{common,c_flows,ab_flows,c_atoms,server}.py`, `schemas/c_flow.py`,
`tests/test_c_flows.py`, `references/recipes/**`, and `references/devices/**`.

## 0. Summary

- **D flows:** `D_flow_<operation>_<domain>_<subject>`. They call D atoms only. There are
  9 registered tools (3 P0, 2 P1, 4 P2) and 2 reserved names.
- **CD flows:** `CD_flow_<operation>_<domain>_<subject>`. The name is the same as the D
  flow it interprets with, and the flow means "measure once with C, then that D flow". There
  are 4 registered tools (2 P0, 2 P2 stub-gated) and 1 reserved name.
- A CD flow calls exactly one `C_flow_*`, picked from a closed per-flow set by a
  discriminator. It also calls its D flow, the archive D flow and narrow D atoms. It never
  calls A or B. A/B envelopes can be passed in as evidence only.
- Phases are `expect` (D atom), then `measure` (C flow), then `interpret` (D flow), then
  `archive` (D flow).
- D runs only after a C state of `simulated_complete` with at least one data-bearing read
  record. The state names are those in `c_flows.py`.
- Measurement and parameter extraction that is not tied to one device stays in CD. Id-Vg,
  Id-Vd families, FeFET, PUND, endurance, retention, breakdown and CV-after-leakage go to
  recipes/ABC. They fail at least one clause of the admission test in section 4.

## 1. Scope and Invariants

D flows inherit every D atom invariant (arbitration section 1). Flows add only ordering,
skipping, aggregation and taint bookkeeping. A flow never computes numbers, fingerprints
or trust: those belong to atoms, and in this phase the atoms are stubs.

- Same-class rule. D flows call only `D_atom_*`. They do not call D flows, which follows
  the A/B/C flow precedent. Shared step builders are code helpers, not tools.
- Cross-family rule. CD flows compose flows, as AB does: one C flow, one interpreting D
  flow, the archive D flow, and narrow D atoms. They never call C atoms directly, so the C
  gap, state and read gating logic in `_compose` is reused, not duplicated.
- There are no loops over measurements, retries, adaptive branches, or measurement
  choices based on D output. Bounded serial loops exist only over already supplied datasets
  (`D_flow_analyze_iv_output`).
- Everything is fake. `hardware_touched` is false everywhere. `measurement_completed` and
  `analysis_completed` are false everywhere in this phase.

## 2. Naming Taxonomy

### 2.1 D flows: `D_flow_<operation>_<domain>_<subject>`

This follows the arbitration's provisional hook. The first token names the product the
flow returns, not a stage, because every flow spans several stages.

| Operation (closed) | Product | Uses acceptance criteria? |
|---|---|---|
| `qualify` | Trust-graded dataset: checks, `trust_level`, fit mask | No |
| `screen` | One verdict per declared criterion set; extraction is limited to the screened quantity | **Mandatory** |
| `analyze` | Named parameters (`ExtractionResult[]`) | Optional. When present, an assess step is added and the verdict is a secondary product. |
| `archive` | Run manifest plus write-once bundle plan | No |
| `render` | Inline plot spec, table and report text | No |
| `replay` | Reserved (U6). Re-analysis of a loaded bundle. | n/a |

| Domain (closed) | Meaning | Why not the C object |
|---|---|---|
| `iv` | Current/voltage records (SMU spot, staircase, high-speed and pulsed spot; EasyEXPERT IV vectors) | SMU and EasyEXPERT data share IV checks |
| `cv` | Impedance/capacitance records (CMU; SMU QSCV reserved) | QSCV is an SMU flow but CV data |
| `timeseries` | Time-indexed records (WGFMU; SMU sampling reserved) | SMU sampling is an SMU flow but time data |
| `run` | Run-level objects (manifest, bundle, report) | Not tied to any data domain |

The domains reuse the D atom `qualify` subjects (`iv`, `cv`, `timeseries`, `run`), so no new
token families are introduced. Checks depend on the kind of data, not on the instrument
that produced it.

| Operation x domain | Allowed subjects |
|---|---|
| `qualify` x `iv`, `cv`, `timeseries` | `dataset` |
| `screen` x `iv` | `leakage` |
| `analyze` x `iv` | `transfer`, `hysteresis`, `output` |
| `analyze` x `cv` | `capacitance` (reserved) |
| `archive` x `run` | `bundle` |
| `render` x `run` | `report` |
| `replay` x `run` | `bundle` (reserved) |

Names contain no device words (`mosfet`, `fefet`), no measurement-family words (`sweep`,
`pulse`), no module words (`hrsmu`), and no safety words (`validate`, `approve`, `safe`).
Variants are request discriminators: ingest source (`smu` or `easyexpert`), the extraction
subset, and the Vth method.

### 2.2 CD flows: `CD_flow_<operation>_<domain>_<subject>`

Rule: `CD_flow_X` exists only if `D_flow_X` exists. The operation must be `qualify`,
`screen` or `analyze`, and the domain must be `iv`, `cv` or `timeseries`. The C flow is
chosen by the closed discriminator `acquisition.kind`. Its values are the C flow
`<family>_<object>_<subject>` tokens (for example `sweep_smu_staircase` gives
`C_flow_sweep_smu_staircase`), so the mapping is mechanical and the C object still appears
in the response (`c_flow`) and in `flows_called`.

The arbitration deferred the "intent-first vs C-family-first" choice to this round.
Reasons for this choice:

1. **Intent-first matches AB**, the other cross-family layer. The flow taxonomy's standing
   rule is that each layer's first token sits one step higher than the layer below.
2. **No C x D cross product.** C-family-first would need `CD_flow_spot_smu_leakage`
   and `CD_flow_sweep_smu_leakage`, plus a new name for each C flow wrapped later. Both C and D
   arbitrations made measurement family a parameter wherever the composition is otherwise
   the same.
3. **The domain is more accurate than the object.** An object token breaks for QSCV (an SMU
   flow, CV data) and for SMU sampling (an SMU flow, time data).
4. **The name pairing documents the composition.** `CD_flow_screen_iv_leakage` is "measure,
   then `D_flow_screen_iv_leakage`". Tool lists separate the two by prefix and by the
   required request (`acquisition` versus `evidence`).

Rejected alternatives:

- `CD_flow_<c_family>_<object>_<subject>` (candidate B): cross product, and the intent is
  hidden.
- `CD_flow_<intent>_<object>_<subject>` (candidate A): fails for QSCV and SMU sampling.
- Four-token names: these break the three-token shape that every existing family uses.

## 3. Composition Rules

### 3.1 Who may call what

| Caller | May call | Must not call |
|---|---|---|
| `D_flow_*` | `D_atom_*` from its fixed catalog, serially | A/B/C anything, D flows, CD flows |
| `CD_flow_*` | Exactly one `C_flow_*` from its allowed set; one interpreting `D_flow_*`; `D_flow_archive_run_bundle`; narrow D atoms (`D_atom_ingest_request_build_expectation`, P1 `D_atom_assess_dataset_check_envelope`) | `A_*`, `B_*`, `C_atom_*`, other CD flows, a second C flow, any retry |

A/B dependencies are **reported, never called**:

- The C child's `required_preconditions` are copied up.
- Each D child's `required_inputs` are copied up as well. These name the A evidence that a
  pure CD flow cannot produce, for example FMT verification through
  `A_flow_prepare_flex_output_buffer`, error drains through `A_flow_drain_flex_errors`, and
  inventory.

A caller (an ABC transaction or the agent) may pass A/B envelopes it already holds as
`upstream_evidence`. The CD flow forwards them to `D_atom_qualify_run_check_context`.
Without them, check_context lists the evidence as missing, so trust cannot exceed
`needs_review` and U5 citation is blocked. This is intended: citable verdicts need the
full ABC evidence chain.

### 3.2 C execution states in CD (the interpret gate)

The interpret phase runs only when all of the following hold for the C child envelope:

- `ok is True`
- `fake is True` and `hardware_touched is False`
- `execution_state == "simulated_complete"` and `simulation_completed is True`
- `len(outputs.data) >= 1`: at least one data-bearing read or sample record exists. Empty
  `rows: []` counts as received-but-empty, which completeness reports. A read that never
  happened counts as missing.

| C child state | Interpret | Archive | CD `ok` | CD `partial` | Skip reason |
|---|---|---|---|---|---|
| `simulated_complete` with a data record | runs | runs | from children | from children | none |
| `simulated_complete` with no data record (for example a remote flow; excluded by allowed sets, but guarded) | skipped | runs | true | true | `c_no_data_record` |
| `configuration_only` (`contract_gaps` non-empty) | skipped | runs | true | true | `c_configuration_only`; C gaps copied to `contract_gaps` |
| `awaiting_completion` | skipped | runs | true | true | `c_awaiting_completion`; hand-off warning copied |
| `failed` (or C flow raised) | skipped | runs | **false** | true | `c_failed` |
| `fake` not true or `hardware_touched` true | skipped | **skipped** | **false** | true | `c_unexpected_marker`; stop everything |

The archive phase runs whenever the measure phase was invoked, because every attempted
instrument transaction needs a manifest (`AGENTS.md` audit rule). The one exception is an
unexpected hardware marker: then nothing after it runs, and the envelope itself is the
audit.

### 3.3 D children in D and CD runners

- **Acceptance.** Per arbitration section 6, a D child is accepted only if
  `hardware_touched is False`. Under U1, `fake is True` is also required in this phase. A
  `fake: false` D result would claim computation the user ruled out, so it is treated as
  an unexpected marker and stops the flow. This is stricter than section 6 and compatible
  with it.
- **Failure** means only `ok is False`, an exception, or a non-dict result. The C
  `_failed()` scraping of `passed`, `status` and `result_code` is never applied to D
  results (gap G7). `check_outcome: fail`, `trust_level: untrusted`, `not_extractable`,
  `inconclusive` and `verdict: fail` all keep `ok: true`.
- **Trust gating stays inside atoms** (arbitration #7). Flows always call extract and
  assess after `grade_trust`, unless an earlier step failed, and record the atom's
  `not_extractable` or `inconclusive` result. Flows never re-implement the gate.
- **The expectation is built once.** The CD expect phase builds it from the typed C child
  request before measuring and hands it to the D flow. The D flow records its own
  `build_expectation` step as skipped with `expectation_supplied` (an optional skip). The
  expectation is advisory: its findings never change or skip the measurement. An `ok:false`
  from it is a composition failure: the CD stops before measuring. That is not a D verdict
  gating C.
- **Evidence passing.** CD hands the D flow the full C child envelope, and D ingest reads
  the data-bearing `atom_results[i].result` named by `outputs.data[].atom`. It never reads
  the trimmed `outputs.data`, so G6 does not block CD. G1 still lowers trust.

## 4. Boundary: CD Flows Versus Recipes/ABC

**CD admission test.** A measure-and-analyze composition is a CD flow only if all of the
following hold:

1. Exactly one invocation of an existing C flow produces the whole dataset. No outer
   parameter loop, no multi-run family, and no program-then-read sequence.
2. That C flow can reach `simulated_complete` with data in the current catalog (no contract
   gaps). Verdict-producing (`screen`) CD flows also need status-bearing data, so the
   status-less high-speed spot is excluded from the screen.
3. The analysis is a D curve-kind analysis (the extract subjects `leakage`, `transfer`,
   `output`, `cv`). Every device-dependent value is declared in the request.
4. No decision depends on the D result: no stop condition, retry, next point or
   escalation action.
5. No A/B action is needed between measure and interpret, such as selector switching,
   correction or routing.

| Candidate | Fails clause | Home |
|---|---|---|
| Id-Vg Vth/SS/gm/on-off | 1 and 2: gate sweep plus a separate drain bias. No executable C flow sources two channels (the synchronous and multi-channel flows are configuration-only). C arbitration also names it a device experiment. | Recipe/ABC: C flows + `D_flow_analyze_iv_transfer` |
| Id-Vd family, Ron | 1: outer Vgs loop | Recipe/ABC + `D_flow_analyze_iv_output` |
| Hysteresis (double sweep) | 2: `SmuSweep.sweep_type` has no double modes | Reserved `CD_flow_analyze_iv_hysteresis` until C closes the gap |
| FeFET write/read, memory window, PUND, endurance, retention, BTI | 1, 4 and 5 | Recipes/ABC (C arbitration) |
| Breakdown voltage | 4: needs stop conditions and approval; destructive | Recipe/ABC with human approval |
| CV/QSCV after leakage gating | 5 and U5: correction plus leakage evidence plus approval | ABC. Only the stub `CD_flow_qualify_cv_dataset` exists. |
| EasyEXPERT test plus analysis | 5: result fetch is A | ABC: C remote flow, A fetch, `D_flow_qualify_iv_dataset(source=easyexpert)` |
| SPGU-only flows | No acquisition | n/a |

**How criteria come in (U4).** Each criterion is a typed `Criterion`: quantity,
comparator, a `Quantity` with an exact unit, and bound handling. Method specs are typed
unions, for example `VthMethod = constant_current{icc_a, w_m?, l_m?} |
max_gm_linear_extrapolation{derivative}`. Every block carries `criteria_source{kind:
device_profile|recipe|caller, name, version}`. These fields are required; nothing defaults.

Flows never read `references/devices` or `references/recipes`. The agent or ABC resolves
the profile and passes values plus their source. Flows do not alias method names, so
`linear_extrapolation` from `mosfet.example.yaml` is rejected. G13 must be fixed in the
references before ABC can source from them.

The trust policy default (U3) is allowed because it is a versioned data-trust policy, not
a device criterion.

## 5. Catalog

**Priority rule.** A flow's priority is the lowest priority among the atoms it needs, and a
flow is registered only when all of those atoms are registered. One exception, requested
here: `D_atom_archive_run_write_bundle` and `D_atom_archive_run_load_bundle` stubs move
into the P0 stub wave. The P0 CD archive phase needs them, and the arbitration says
write_bundle is required before the first real CD run. Under U1 they are trivial stubs.

### 5.1 Shared qualify chains (step builders, not tools)

**`Q_IV` (all P0):**

1. `D_atom_ingest_request_build_expectation` (optional skip: `expectation_supplied`, or
   `no_c_request` for EasyEXPERT)
2. `D_atom_ingest_smu_build_dataset` (with `source=easyexpert`:
   `D_atom_ingest_easyexpert_build_dataset`, P1, after G5)
3. `D_atom_qualify_dataset_classify_status`
4. `D_atom_qualify_dataset_check_completeness`
5. `D_atom_qualify_iv_check_compliance`
6. `D_atom_qualify_iv_check_resolution`
7. `D_atom_qualify_run_check_context`
8. `D_atom_qualify_dataset_grade_trust`

**`Q_CV` (P2 stub-gated):** build_expectation, then `D_atom_ingest_cmu_build_dataset`,
classify_status, check_completeness, `D_atom_qualify_cv_check_correction`, check_context,
grade_trust.

**`Q_TS` (P2 stub-gated):** build_expectation, then `D_atom_ingest_wgfmu_build_series`,
check_completeness, `D_atom_qualify_timeseries_check_events`, check_context, grade_trust.
There is no `classify_status` step, because WGFMU has no per-point status; channel status
is checked in check_events.

### 5.2 D flows

| Flow | Pri | Request | Ordered atoms (`[ ]` = conditional) | Product (`outputs`) | Gate/gap status |
|---|---|---|---|---|---|
| `D_flow_qualify_iv_dataset` | P0 | `DQualifyIv` | `Q_IV` | `dataset` (null in stub phase), `trust_level`, `fit_mask`, per-check `check_outcome`, `evidence_missing` | SMU real priority; EasyEXPERT variant needs G5 |
| `D_flow_screen_iv_leakage` | P0 | `DScreenIvLeakage` | `Q_IV` -> `D_atom_extract_leakage_current` -> `D_atom_assess_value_check_limits` | above + `results[]`, `verdict`, `verdict_scope`, `criteria_echo`, `evidence_citation` | Data half of the AGENTS leakage validation |
| `D_flow_archive_run_bundle` | P0 (with stub promotion) | `DArchiveRun` | `D_atom_archive_run_build_manifest` -> [`D_atom_archive_run_write_bundle`, if `persist`] -> [`D_atom_archive_run_load_bundle`, only if `artifact_written`] | `manifest_ref`, `planned_paths`, `artifact_written: false`, `write_refusal` (`fake_mode` / `synthetic_origin`), `hash_ok: null` | U2: never writes in this phase |
| `D_flow_analyze_iv_transfer` | P1 | `DAnalyzeIvTransfer` | `Q_IV` -> [`D_atom_extract_transfer_gm_max`] -> [`D_atom_extract_transfer_vth`] -> [`D_atom_extract_transfer_ss`] -> [`D_atom_extract_transfer_on_off`] -> [`D_atom_assess_value_check_limits`, if acceptance] | `results[]` per selected parameter; optional verdict | D-only; for recipes/ABC (no CD) |
| `D_flow_analyze_iv_hysteresis` | P1 | `DAnalyzeIvHysteresis` | `Q_IV` -> `D_atom_shape_dataset_split_segments` -> `D_atom_extract_transfer_voltage_shift` -> [assess] | signed dV, per-branch V | Data from recipes/EasyEXPERT until C supports double sweep |
| `D_flow_analyze_iv_output` | P2 | `DAnalyzeIvOutput` | `Q_IV` per member (2..16, serial) -> `D_atom_shape_dataset_stack_family` -> `D_atom_extract_output_ron` -> [assess] | Ron per outer-parameter segment | Loop is over supplied datasets, never measurements |
| `D_flow_render_run_report` | P2 | `DRenderRun` | `D_atom_render_dataset_build_plot_spec` -> `D_atom_render_dataset_build_table` -> `D_atom_render_run_build_report` | inline spec, table text, Markdown | No files, no LLM text |
| `D_flow_qualify_cv_dataset` | P2 stub-gated | `DQualifyCv` | `Q_CV` | as for qualify | CMU real use blocked (correction, SCUU, leakage) |
| `D_flow_qualify_timeseries_dataset` | P2 stub-gated | `DQualifyTimeseries` | `Q_TS` | as for qualify | WGFMU stub; G4 time array missing |

Reserved, not registered: `D_flow_replay_run_bundle` (U6; nothing is archivable while
everything is synthetic) and `D_flow_analyze_cv_capacitance` (Cox/Vfb, CMU P2 atoms
gated on correction).

### 5.3 CD flows

| Flow | Pri | Request | Phases and ordered children | `acquisition.kind` (closed) |
|---|---|---|---|---|
| `CD_flow_qualify_iv_dataset` | P0 | `CdQualifyIv` | expect: `D_atom_ingest_request_build_expectation` -> measure: `C_flow_<kind>` -> interpret: `D_flow_qualify_iv_dataset` -> [P1: `D_atom_assess_dataset_check_envelope`, if `envelope`] -> archive: `D_flow_archive_run_bundle` | `spot_smu_iv`, `spot_smu_high_speed`, `sweep_smu_staircase`, `pulse_smu_spot` |
| `CD_flow_screen_iv_leakage` | P0 | `CdScreenIvLeakage` | expect -> measure: `C_flow_<kind>` -> interpret: `D_flow_screen_iv_leakage` -> [P1 envelope audit] -> archive: `D_flow_archive_run_bundle` | `spot_smu_iv`, `sweep_smu_staircase` (status-bearing only) |
| `CD_flow_qualify_cv_dataset` | P2 stub-gated | `CdQualifyCv` | expect -> measure -> interpret: `D_flow_qualify_cv_dataset` -> archive | `spot_cmu_impedance`, `spot_cmu_high_speed`, `sweep_cmu_cv`, `sweep_cmu_cf`, `sweep_cmu_ac_level`, `pulse_cmu_spot`, `pulse_cmu_cv`, `sampling_cmu_ct` |
| `CD_flow_qualify_timeseries_dataset` | P2 stub-gated | `CdQualifyTimeseries` | expect -> measure -> interpret: `D_flow_qualify_timeseries_dataset` -> archive | `waveform_wgfmu_acquire` |

Reserved:

- `CD_flow_analyze_iv_hysteresis`: needs a double-sweep staircase in C.
- QSCV (`sweep_smu_qscv`) in the CV kind set: SMU ingest of charge data is not designed.
- SMU sampling in the timeseries kind set: the C sampling gap must close first.

Example nested `atoms_called` for `CD_flow_screen_iv_leakage` with
`kind=sweep_smu_staircase`:

1. `D_atom_ingest_request_build_expectation`
2. The 8 staircase C atoms
3. D atoms 2-10 of `Q_IV` plus extract/assess (step 1 is skipped as `expectation_supplied`)
4. `D_atom_archive_run_build_manifest`
5. `D_atom_archive_run_write_bundle` (stub planned paths; load_bundle skipped as
   `nothing_written`)

### 5.4 Request type sketches

These would go in new `schemas/d_flow.py` and `schemas/cd_flow.py`, using `extra=forbid`
and `allow_inf_nan=False`. They reuse `schemas/c_flow.py` and the planned
`schemas/analysis.py`.

```text
IvEvidence: source: smu|easyexpert; c_flow_envelope: dict|None; easyexpert_vectors|None;
  upstream_evidence: list[envelope] (<=16); declared_origin: synthetic|fixture|instrument|None
  validators: smu source => C envelope with execution_state=simulated_complete,
  simulation_completed, >=1 outputs.data record; otherwise rejected before any call.
  declared_origin may only lower the origin derived from the evidence. Instrument origin needs an
  upstream envelope with fake:false, which is unreachable in this phase.
DQualifyIv: evidence; channel_roles: dict[Channel, TerminalRole] (required); module_types
  (required unless derivable from the C request echo); expectation: DataExpectation|None;
  trust_policy: TrustPolicyRef = U3 default (versioned); near_compliance_ratio = 0.95 (U3)
DScreenIvLeakage(DQualifyIv): leakage: {terminal: TerminalRole; bias_points_v | window_v
  (at least one); limit: Criterion(abs_current, le, Quantity[A]); criteria_source} (required)
DAnalyzeIvTransfer(DQualifyIv): gate_role, drain_role, polarity n|p, vds_v (declared, echoed;
  a mismatch with programmed setpoints is a finding, never corrected); extract: set of
  {vth, gm_max, ss, on_off} (min 1); vth: VthMethod|None; gm: DerivativeMethod|None;
  ss: {i_low_a, i_high_a, min_decades}|None; on_off: {vg_on_v, vg_off_v}|None;
  acceptance: list[Criterion] = []; criteria_source. Validator: every selected parameter
  has its spec; units match exactly.
DAnalyzeIvHysteresis(DQualifyIv): segment_rule (declared); at_current: Quantity[A]; role;
  acceptance = []
DAnalyzeIvOutput: members: list[{evidence, outer_value: Quantity}] (2..16); shared roles and
  policy; vds_window; drain_role; acceptance = []
DArchiveRun: envelopes: list[dict] (1..8); intent: str (1..500); station: {name, sha256}|None;
  persist: bool = True; data_root: Literal["data"]; created_at: datetime|None
DRenderRun: analysis_envelope; manifest_ref|None; axes (declared); table_format csv|json

CD acquisition children: {kind: Literal[...], request: <C request model>}, one class per
  kind (for example SweepSmuStaircaseAcq.request: SmuSweep); discriminator "kind".
CdQualifyIv: acquisition (required, no default kind); channel_roles (required, must cover
  the C channel); upstream_evidence = []; trust_policy and near ratio (U3); envelope:
  DeclaredEnvelope|None (P1); archive: {persist = True, intent: str|None}
  validators: run.collect is True (except high-speed); run.max_items >= lower bound of
  expected points (1 for spot, steps for staircase; the exact count is a completeness
  finding).
CdScreenIvLeakage(CdQualifyIv): kind restricted to spot_smu_iv|sweep_smu_staircase;
  leakage required; validators: source == voltage; ranging.measure_function == current;
  leakage.terminal == channel_roles[request.channel]; staircase bias points inside
  [min, max] of the sweep (no extrapolation); spot bias points == [level];
  limit.unit == "A" and limit.value < compliance (otherwise the verdict cannot be
  resolved and the measurement would be futile).
```

Request fields are named `acquisition` and `evidence`, never `measurement`, `sample`,
`rows` or `values` (the banned keys).

## 6. Response and Failure Contract

### 6.1 D flow envelope

This is the A/C flow envelope plus D fields. `outcome`, `status`, `passed`,
`result_code`, `rows`, `values`, `sample` and `measurement` are banned at the top level and
at the top level of `outputs` and `inputs`.

```text
flow, flow_class: "D", category (= operation), domain, subject, fake: true,
hardware_touched: false, deterministic: true, ok, partial, destructive: false,
consumptive: false, analysis_state, analysis_completed: false, data_origin, synthetic,
atoms_called, atom_results[{phase (= D stage), atom, inputs (scalars), input_refs,
  timestamp (UTC), status: ok|error|skipped, reason, optional, result | error}],
inputs (request echo; evidence summarized as {source, c_flow, execution_state,
  data_record_count, upstream_count}, never re-embedded), outputs{...},
findings (child findings tagged with source atom), warnings, assumptions,
required_inputs, evidence_missing, contract_gaps (blocking gaps only),
side_effects{hardware: "none", filesystem_writes: [], artifact_written: false},
cleanup{owner: "none", performed: false, note: "No hardware state; write_bundle is
  write-once and never rolled back"}, purpose, error{type, message, at} (only when ok=false)
```

### 6.2 CD flow envelope

The C flow envelope plus the AB phase structure plus D fields:

```text
flow, flow_class: "CD", category, domain, subject, c_flow, fake, hardware_touched,
ok, partial, destructive (= C child), consumptive (= C child),
phases{expect[], measure[], interpret[], archive[]}, flows_called, atoms_called
  (direct + nested, AB style), child_results[{phase, name, kind: c_flow|d_flow|d_atom,
  inputs, input_refs, timestamp, status, reason, optional, result}],
execution_state (= C child), measurement_completed: false, simulation_completed (= C),
analysis_state, analysis_completed: false, data_origin, synthetic,
inputs (request dump), outputs{acquisition{c_flow, execution_state, data_record_count},
  trust_level, verdict, verdict_scope, results[], evidence_citation{eligible, blockers[]},
  archive{manifest_ref, planned_paths, artifact_written: false, write_refusal}},
required_preconditions (C list + unmet D required_inputs), contract_gaps (C gaps),
findings, warnings (child warnings prefixed with source), assumptions, evidence_missing,
side_effects, cleanup (C child's block verbatim + note, see 6.6),
audit{phase_order: [expect, measure, interpret, archive], child_count, skipped_children,
  skip_reasons, consumptive_children}, purpose, error (only when ok=false)
```

The phase is named `archive`, not `record`: the arbitration avoided `record` because flow
audit records already use that word.

### 6.3 `ok`, `partial`, `analysis_state`, verdict

- **`ok: false`** only for:
  - a child `ok:false`, a child exception, or a non-dict result;
  - an unexpected marker;
  - a taint-invariant violation (6.4);
  - C child failure.

  Data outcomes never set `ok: false`. CD keeps C/D semantics (`ok` is independent of
  `partial`) and does **not** copy AB's `ok = not partial`. Copying it would mark every
  pending or configuration-only measurement and every stub analysis "not ok", which
  contradicts arbitration #5 and the C contract.
- **`partial: true`** when:
  - a required step was skipped or failed;
  - a child is partial; or
  - (CD) the C state is not `simulated_complete`.

  Skips flagged `optional: true` do not count. They come from a closed set of reasons:
  `expectation_supplied`, `no_c_request`, `not_requested`, `persist_disabled`,
  `nothing_written`.

  The full closed skip-reason set is those five plus: `earlier_failure`, `c_failed`,
  `c_configuration_only`, `c_awaiting_completion`, `c_no_data_record`,
  `c_unexpected_marker`.
- **`analysis_state`** (flow aggregate, worst wins): `rejected_input` > `not_run` (CD
  interpret skipped) > `not_computed` > `not_extractable` > `inconclusive` > `complete`.
  Under U1 the best reachable state is `not_computed`. `analysis_completed` is true only
  for `complete`, which is unreachable in this phase.
- **`verdict`** is the child assess verdict, after the taint clamp in 6.4. Without
  acceptance it is `null`. `verdict_scope` is `instrument` or `fixture` only when the
  verdict is `pass` or `fail`; otherwise it is `null`.

### 6.4 Synthetic taint

- `data_origin` is the weakest of: the C child (any `fake:true` or
  `outputs.synthetic:true` means `synthetic`), upstream evidence, `declared_origin` (which
  can only lower it), and the `data_origin` of each D child.
- **Taint clamp.** If `data_origin` is not `instrument`, the flow reports
  `verdict = synthetic_only` (synthetic) or keeps the fixture scope. It also reports
  `trust_level = synthetic_only` for synthetic data. This is label bookkeeping from
  arbitration #6, not computation.
- If a D child itself returns `pass` or `fail`, or `trust_level` of `trusted` or
  `trusted_with_flags`, on synthetic data, it has violated the D contract. The flow then
  sets `ok:false` and `error.type: internal_error`, retains the child result, and still
  reports the clamped verdict.
- **Invariant tested on every flow:** no `"pass"` value appears anywhere in the response
  tree when `data_origin == "synthetic"` or `analysis_state != "complete"`. A fixture
  `pass` is possible only with `verdict_scope: fixture`, and only once analysis is
  complete, which cannot happen under U1. Fake C data therefore never yields a pass
  verdict, at either the D or the CD level.
- `evidence_citation.eligible` is computed from the U5 conditions:
  - origin is `instrument`;
  - trust is at least `trusted_with_flags`;
  - verdict is `pass`;
  - a manifest is present (CD archive phase; standalone D flows report
    `manifest_absent`).

  Human approval is always listed as an external requirement. In this phase `eligible`
  is always false, with blockers such as `synthetic_origin` and `analysis_not_computed`.
  Neither D nor CD acts on this field.

### 6.5 Stop-on-failure and audit retention

- Typed request validation runs before the first child call. This includes required
  criteria, unit match, pending or empty evidence, `collect`, `max_items`, resolvable
  limits and channel-role coverage. A violation raises a validation error at the MCP
  boundary with no envelope and no child call. This follows the C-flow precedent: typed
  schemas are kept, and there is no evidence to retain.
- **D flows:** the first failure stops later atoms (`earlier_failure`). Every earlier
  record, with its timestamp and unchanged child payload, is kept.
- **CD flows:**

  | Failure point | What happens |
  |---|---|
  | `expect` fails | Stop. Nothing is measured and there is no archive. |
  | `measure` fails | Skip interpret; run archive. |
  | `interpret` fails | Skip the remaining interpret steps; run archive. |
  | `archive` fails | Report `ok:false`, `partial:true`. |
  | Unexpected marker anywhere | Stop everything. |

  In all cases the C flow is called at most once, never retried, and never re-run because
  of a D result.
- `consumptive` evidence: the consumed C read payload is kept intact inside the measure
  child record. The D flow receives it by `input_refs`
  (`phases.measure[0].result`), not by copy.

### 6.6 Cleanup responsibility

- **D flows** have no hardware state. `cleanup.owner` is `none`. In a future real mode a
  failed write_bundle leaves `partial_artifacts`, which are reported and never deleted
  (write-once, no delete).
- **CD flows** copy the C child's `cleanup` block verbatim (`owner:
  outer_ABC_transaction`, `performed: false`). CD is **not** a cleanup boundary.

  The D phases run after the C flow's last step and before the outer transaction's normal
  cleanup. The D phases are pure, bounded and have no I/O, but they still extend the
  post-measurement hold. ABC transactions for stress-sensitive DUTs can compose
  `C_flow` -> (B/AB cleanup) -> `D_flow` instead. See open question Q1.
- Failure cleanup must be installed by the outer transaction before CD is called. This is
  the existing C rule.

### 6.7 Archiving (writes)

A CD flow writes nothing itself. Only `D_atom_archive_run_write_bundle`, reached through
`D_flow_archive_run_bundle`, is a writer.

- **Default.** CD requests default to `persist: true`, so future real runs archive by
  default, as the AGENTS audit rule requires.
- **In this phase** every run is fake and synthetic. The write is refused, and the result
  carries `planned_paths` (relative to `data/`, no absolute or private paths),
  `artifact_written: false` and `write_refusal`. load_bundle is skipped as
  `nothing_written`.
- **The manifest** is built once, by the outermost composition. D analysis flows do not
  build manifests. A standalone D user calls `D_flow_archive_run_bundle` with the
  envelopes.

## 7. Intentionally Not Added

| Candidate | Reason |
|---|---|
| CD over Id-Vg/transfer, Id-Vd/output, FeFET, PUND, endurance, retention, BTI, breakdown, CV-after-leakage | Fails the admission test (section 4); recipes/ABC call C flows + D flows |
| CD over configuration-only C flows (synchronous, multi-channel, pulse sweep, pulsed bias, multi pulse, quasi, sampling, signal monitor, search) | D would always be skipped. Reserved until C gaps close. |
| CD over SPGU or EasyEXPERT remote flows | No acquisition data / fetch is A |
| CD flows with loops, repeats, multiple C flows, adaptive branches or retries; CD calling CD | Recipe/ABC territory; bounded single transaction only |
| CD calling C atoms directly, or any A/B tool | Duplicates C gating; A/B are reported or passed in as evidence only |
| D flows calling D flows | Same-class precedent; step builders give reuse |
| `D_flow_ingest_*` | Too thin (two atoms); ingest without qualify produces untrusted data with no grade |
| One flow per check or per parameter; per-module or per-family names | These are parameters (C and D arbitrations) |
| `D_flow_replay_run_bundle`, export/legacy import flows | U6 deferred; nothing archivable in this phase |
| Statistics/repeatability flow | No consumer: repeats are outer loops, and EasyEXPERT repeat data is blocked by G5 |
| Envelope-audit or compliance "screen" flows | Envelope audit is an assess atom (optional P1 CD step), not a screen and never a gate |
| Render inside CD | Keeps CD output bounded; the agent calls `D_flow_render_run_report` |
| `recommendations`, next-measurement hints, LLM narrative, `outcome` text field | D scope and banned keys |

## 8. Known Gaps

| # | Gap | Owner |
|---|---|---|
| DG1 | **Stub chaining.** Under U1, ingest returns `dataset: null`, so the next atom, which needs a dataset, would return `rejected_input` and every D flow would stop at step 3. Requested amendment to the D atom contract: product inputs accept `inline \| null` plus a mandatory `upstream: list[ProductRef{producer, analysis_state, output_fingerprint\|null}]`. A null input with an upstream ref in state `not_computed` returns `not_computed` (`ok:true`). A null input without an upstream ref returns `context_missing`. Fallback if rejected: flows skip downstream steps with `upstream_not_computed`, but then every flow is always partial. | D atom arbitration |
| DG2 | No executable two-channel C composition (sweep plus independent bias with per-channel compliance), which blocks any measured transfer analysis | C (synchronous / multi-channel gaps) |
| DG3 | `SmuSweep.sweep_type` lacks double-sweep modes, which blocks `CD_flow_analyze_iv_hysteresis` | C schema |
| DG4 | G1/G2/G3/G6 carried over: no raw ref or contract echo, free-string `format_hint`, status-less samples. CD avoids G6 by passing `atom_results`, but trust stays capped. | C |
| DG5 | Evidence binding: there is no run or session id in A/C envelopes, so check_context cannot prove that passed-in A/B evidence brackets the C run. Unbound evidence must count as missing. | A/C + D check_context |
| DG6 | write_bundle/load_bundle stub priority moves P1 -> P0 | D atom wave plan |
| DG7 | New runners needed: `_d_compose` (atoms; `ok:false`-only failure; accept on `hardware_touched` False and `fake` True) and `_cd_compose` (flows; phases; interpret gate). `_compose`/`_failed` and the AB helpers are not reusable as-is (G7). | implementation |
| DG8 | CV/timeseries D and CD flows wait for their P2 stub atoms; SMU QSCV ingest is undesigned | D atoms |
| DG9 | G13: recipe/device vocabulary (`linear_extrapolation`, `leakage_threshold` with no value) must be fixed before ABC can source criteria from them | references |
| DG10 | Reference docs `mcp-tools/{d-atoms,d-flows,cd-flows}.md`, README index, `register_d_flows`/`register_cd_flows` in `server.py`, and the capabilities resource listing | implementation |
| DG11 | EasyEXPERT source variant blocked by G5 (`fetch_result` returns `result: None`) | A |

## 9. Validation and Test Plan (for the implementation task)

1. **Discovery.** All registered D/CD flows are discoverable through FastMCP with typed
   request schemas. Names match the closed-vocabulary regex. A CD name implies an existing
   D name. The reference tables match the registered names. Legacy registrations and
   `tests/test_c_flows.py` are unchanged.
2. **Composition boundaries.**
   - D flows call only `D_atom_*` in the catalog order.
   - CD direct children are exactly one allowed `C_flow_*`, the matching D flow,
     `D_flow_archive_run_bundle` and allowed narrow D atoms.
   - No `A_*`, `B_*` or `C_atom_*` appear as direct children.
   - The C flow is called once even when it is patched to fail.
3. **Envelope.**
   - Required keys are present.
   - Banned keys are absent at the top level and in `inputs`, `outputs` and `parameters`.
   - `json.dumps(allow_nan=False)` succeeds.
   - Timestamps are present on every record.
   - Child payloads are unchanged (identity or equality against a direct atom call).
4. **Taint.**
   - Recursively walk every response: no `"pass"` value anywhere.
   - All CD runs return `data_origin: synthetic` and `verdict: synthetic_only`.
   - `declared_origin: instrument` on fake evidence still yields `synthetic`.
   - `evidence_citation.eligible` is false and lists blockers.
   - A patched D child that returns `pass` on synthetic data gives `ok:false` /
     `internal_error` with the verdict clamped.
5. **Criteria (U4).** Each case must raise a validation error, and a spy must record
   **zero** child calls, C included:
   - missing leakage criteria, Vth method or channel roles;
   - a unit mismatch;
   - an aliased method name;
   - a bias point outside the sweep;
   - a limit at or above compliance;
   - `collect=false`;
   - `max_items` below `steps`;
   - pending, configuration-only or data-less evidence passed to a D flow.
6. **CD state handling.** Patch the C flow to return each state from the 3.2 table, plus
   an exception and an unexpected marker. Check the interpret skip reasons, whether
   archive runs, the `ok`/`partial` values, and that C gaps and warnings are copied.
7. **D failure semantics.**
   - A D child with `ok:false` stops later atoms, keeps earlier evidence, lets CD archive
     still run, and gives `ok:false`.
   - A D child carrying `passed: False`, `status: "failed"` or `check_outcome: fail` but
     `ok: true` keeps the flow `ok:true` (G7 regression).
   - A D child with `fake:false` stops the flow.
8. **Stub chaining (DG1).** A full `Q_IV` run over stubs gives `analysis_state:
   not_computed` with no `rejected_input`.
9. **Expectation hand-off.** The expect phase runs before measure. The D flow's own
   build_expectation is recorded as an optional skip (`expectation_supplied`), and its
   findings never alter the C child inputs.
10. **Archive (U2).** Monitor the filesystem (`tmp_path` and a patched write) and confirm:
    - no files are written;
    - `artifact_written` is false and `write_refusal` is set;
    - `planned_paths` are relative to `data/` with no absolute or user paths;
    - load_bundle is skipped as `nothing_written`;
    - with `persist=false`, write_bundle is skipped as `persist_disabled`.
11. **Bounds.** The inline evidence cap is 100,000 points. The member loop in
    `D_flow_analyze_iv_output` is limited to 2..16 serial iterations with no
    measurement calls.

## 10. Open Questions for the User

U1-U6 are settled and not repeated. Naming (section 2.2) and the DG1 amendment are for
arbitration, not for the user.

| # | Question | Recommended default |
|---|---|---|
| Q1 | When real execution exists, may an ABC transaction use a CD flow? D runs after measurement but before the outer cleanup, so outputs stay at their post-measurement state for the bounded, I/O-free D phase. Or must real transactions always run C, then B/AB cleanup, then D, which makes CD a fake/offline convenience only? | Allowed. Each recipe declares `analysis_before_cleanup: allowed\|forbidden`, and stress-sensitive DUTs (FeFET, thin oxides) must use the C -> cleanup -> D order. |
| Q2 | May callers pass already-captured A/B envelopes into CD/D flows as `upstream_evidence`, so that verdicts can reach `trusted_with_flags` outside a full ABC run? Or should evidence-grade trust be reachable only when ABC itself produced the evidence? | Accept passthrough as evidence only. Evidence not bound to the C run (DG5) counts as missing, so trust stays capped until binding exists. |
