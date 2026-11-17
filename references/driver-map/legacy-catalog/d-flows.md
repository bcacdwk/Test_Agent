# D Flow MCP Tools

D flows are fake, deterministic, hardware-free compositions of `D_atom_*` tools over
evidence the caller already holds (a C flow envelope). They call only D atoms from a
fixed catalog, serially and in catalog order, and add only ordering, skip bookkeeping,
product-reference passing, label aggregation and taint checks. They never compute
numbers, fingerprints, trust or verdicts, never call A/B/C atoms or flows or other D
flows, never touch hardware and never write files.

```text
D_flow_<operation>_<domain>_<subject>
```

Operations (closed): `qualify` (trust-graded dataset), `screen` (one verdict label per
declared criterion set), `analyze` (extraction products, never a verdict), `archive`
(manifest plus write-once bundle plan). Domains are data kinds: `iv`, `cv`,
`timeseries`, `run`. Responses carry `category` (the operation), `domain` and
`subject`, so never parse names. Seven tools are registered.

**Phase status (user decision U1):** every child atom is a placeholder stub, so the
best reachable `analysis_state` is `not_computed`, `analysis_completed` is always false,
and no number, `pass` verdict or trust above `synthetic_only` can appear. Contract:
`tmp/d_flow_design_arbitration.md`; typed models live in
`src/b1500_test_agent/schemas/d_flow.py`.

## Execution and Response Contract

Each tool takes one required `request` (Pydantic, `extra="forbid"`, no non-finite
values); there is no omitted-request default. Validators run before the first atom
call, so a violation is a `ValidationError` at the MCP boundary with no envelope and
zero atom calls:

- evidence must be an admitted C flow envelope whose designated read record is
  `received` or `empty`; pending, configuration-only, failed or data-less evidence is
  rejected;
- `declared_origin` may lower the evidence origin but never exceed it;
- criteria, methods, roles and `criteria_source` are mandatory where the flow needs
  them (U4: no repo defaults); units are exact; method aliases such as
  `linear_extrapolation` are rejected (G13);
- the leakage terminal is the role of exactly one channel, and that channel is measured
  by the C request. Its programmed voltage decides the check: the swept channel is
  evaluated along the sweep `[min, max]`, a held-bias channel of
  `C_flow_sweep_smu_staircase_biased` at its held `level` (bias points equal it, a
  window contains it; the swept trajectory never stands in for it), a spot at its level.
  Every leakage limit must be below that channel's programmed compliance (CD11). D and
  CD share this validator (`check_leakage_against_request`);
- transfer on/off biases lie inside the gate sweep (no extrapolation);
- `include_table` needs at least one dataset, view or derived placeholder ref among the
  archived envelopes;
- no request field uses a banned key.

**Evidence and the designated record.** `evidence = {source, c_flow_envelope,
upstream_evidence (<= 16), declared_origin}`. `source` is `smu` (iv), `cmu` (cv) or
`wgfmu` (timeseries). The designated record is the single read-phase record of the
source's catalog read atom (`C_atom_smu_read_measurement_data`,
`C_atom_cmu_read_measurement_data`, `C_atom_wgfmu_read_measurement_values`) with
status `ok`; D reads only that record and never `outputs.data` (which can list
configuration records). Its element count gives the handoff `received` (>= 1) or
`empty` (0, the fake norm `rows: []`; the flow warns "Empty synthetic data is not
evidence of quality."). Admitted C kinds per domain:

| Domain | Admitted `C_flow_<kind>` evidence |
|---|---|
| `iv` | `spot_smu_iv`, `sweep_smu_staircase`, `sweep_smu_staircase_biased`, `pulse_smu_spot` |
| `cv` | `spot_cmu_impedance`, `sweep_cmu_cv`, `sweep_cmu_cf`, `sweep_cmu_ac_level`, `pulse_cmu_spot`, `pulse_cmu_cv` |
| `timeseries` | `waveform_wgfmu_acquire` (single channel only; several reads are ambiguous) |

Caller-passed A/B envelopes in `upstream_evidence` are forwarded to
`D_atom_qualify_run_check_context`, recorded as `evidence_unverified` and never lift a
trust cap (M6).

**Role coverage.** Standalone D flows run the CD role-coverage check (shared
`measured_channels` / `unmapped_channels`) but do not reject: a measured channel with no
declared role adds the flow-level finding `{source_atom: null, check: "pin_map",
severity: "warning", code: "pin_map_incomplete", count, channels, member?}` and caps
`outputs.trust_level` at `needs_review` (missing context, atom arbitration #14). The cap
only lowers a graded label; it never invents one. An incomplete pin map needs human
review (`AGENTS.md`). CD still rejects it before any child call.

**Response envelope.**

```text
flow, flow_class: "D", category, domain, subject, purpose, fake, hardware_touched,
deterministic: true, ok, partial, destructive: false, consumptive: false,
analysis_state, analysis_completed: false, data_origin, synthetic,
atoms_called, atom_results[{phase (= D stage), atom, inputs, timestamp (UTC), optional,
  reason, status: ok|error|skipped, result, error?, member? (output flow)}],
inputs (request echo; evidence summarized as {source, c_flow, execution_state,
  handoff_state, designated_record, element_count, upstream_evidence[names], declared_origin}),
outputs{products{name: ProductRef}, check_outcomes[{atom, check_outcome}], trust_level,
  verdict, verdict_scope, + flow fields}, findings[{source_atom, check, severity, code, ...}],
warnings, assumptions, evidence_missing, required_inputs, contract_gaps,
provenance{flow_version, schema_version, status_table_version, upstream[]},
side_effects{hardware: "none", filesystem_writes: [], artifact_written: false},
cleanup{owner: "none", performed: false}, error{type, message, at} (only when ok=false)
```

- Atom record `inputs` hold scalars and ProductRefs only; envelopes are echoed by name
  and designated index, never re-embedded. Child payloads are retained unchanged.
- **`ok: false`** only for a child `ok: false`, an exception or non-dict result, an
  unexpected marker (a child that is not `fake: true` and `hardware_touched: false`)
  or a taint violation. Data outcomes (`fail` on instrument data, `untrusted`,
  `not_extractable`, `inconclusive`) and C-style keys such as `passed: false` keep
  `ok: true`.
- **`partial`** when a required step was skipped or failed. Optional skips
  (`expectation_supplied`, `not_requested`) do not count; failure skips use
  `earlier_failure` or `taint_violation`.
- **`analysis_state`**: worst over called children (`rejected_input` > `not_computed` >
  `not_extractable` > `inconclusive` > `complete`); `rejected_input` whenever `ok` is false.
- **`error.type`**: the atom set (`rejected_input`, `context_missing`, `unit_mismatch`,
  `size_limit`, `internal_error`) plus `taint_violation` and `unexpected_marker`;
  `error.at` names the atom.
- **Taint.** `data_origin` is the weakest of the C evidence (`fake: true` or
  `outputs.synthetic: true` is synthetic), upstream evidence, `declared_origin` and
  every child. A child reporting `pass`/`fail`, `trusted`/`trusted_with_flags` (as
  `verdict`, `trust_level` or `check_outcome`) on synthetic or fixture data, or a
  stronger origin than the evidence, is a `taint_violation`: `ok: false`, later steps
  skipped, the tainted label is not propagated (`verdict: null`), the child is retained.
- **Stop on failure.** The first failure stops later atoms; earlier records keep their
  timestamps and unchanged payloads. There are no retries, loops over measurements or
  parallel calls. Cleanup is not a D concern (`owner: "none"`, `performed: false`).

## Shared Chains

Chains are code helpers, not tools. `[ ]` marks a conditional step.

- **`Q_IV`:** `D_atom_ingest_request_build_expectation` [skipped `expectation_supplied`
  when `request.expectation` is given] -> `D_atom_ingest_smu_build_dataset` ->
  `D_atom_qualify_dataset_classify_status` -> `D_atom_qualify_dataset_check_completeness`
  -> `D_atom_qualify_iv_check_compliance` -> `D_atom_qualify_iv_check_resolution` ->
  [`D_atom_qualify_iv_check_source_tracking`, P1 opt-in via `source_tracking_tolerance`,
  otherwise skipped `not_requested`] -> `D_atom_qualify_run_check_context` ->
  `D_atom_qualify_dataset_grade_trust`.
- **`Q_CV`:** build_expectation -> `D_atom_ingest_cmu_build_dataset` -> classify_status ->
  check_completeness -> `D_atom_qualify_cv_check_correction` -> check_context -> grade_trust.
- **`Q_TS`:** build_expectation -> `D_atom_ingest_wgfmu_build_series` -> check_completeness
  -> `D_atom_qualify_timeseries_check_events` -> check_context -> grade_trust (no status
  classification: WGFMU has no per-point status).

Programmed compliance per channel (A for voltage sources, V for current sources,
including biased-staircase bias channels) and single-channel ranging are echoed from
the typed C request into the compliance and resolution checks; `near_ratio` comes from
the versioned U3 `trust_policy`, which is passed explicitly to `grade_trust`.

## D Flow Tools

| Flow | Pri | Request | Ordered Atom Sequence | Key Outputs |
|---|---|---|---|---|
| `D_flow_qualify_iv_dataset` | P0 | `DQualifyIv` | `Q_IV` | products `expectation`, `dataset`, `trust_summary`; `trust_level`; `check_outcomes` |
| `D_flow_screen_iv_leakage` | P0 | `DScreenIvLeakage` | `Q_IV` -> `D_atom_extract_leakage_current` -> `D_atom_assess_value_check_limits` | above + `leakage`, `verdict` products; `results`, `verdict`, `verdict_scope`, `criteria_echo`, `evidence_citation` |
| `D_flow_archive_run_bundle` | P0 | `DArchiveRun` | `D_atom_archive_run_build_manifest` -> [`D_atom_render_dataset_build_table` if `include_table`] -> `D_atom_archive_run_write_bundle` | `archive{manifest_ref, bundle_plan_ref, planned_paths, artifact_written: false, write_refusal}` |
| `D_flow_analyze_iv_transfer` | P1 | `DAnalyzeIvTransfer` | `Q_IV` -> [`D_atom_shape_dataset_split_segments`] -> [`D_atom_extract_transfer_gm_max`] -> [`D_atom_extract_transfer_vth`] -> [`D_atom_extract_transfer_ss`] -> [`D_atom_extract_transfer_on_off`] -> [`D_atom_extract_transfer_voltage_shift`] | one ExtractionResult ref per selected parameter, `segments` view, `selected_parameters`; no verdict |
| `D_flow_analyze_iv_output` | P2 | `DAnalyzeIvOutput` | per member (2..16, serial): `Q_IV`; then `D_atom_shape_dataset_stack_family` -> `D_atom_extract_output_ron` | `members[i].dataset`/`trust_summary`, `family` view, `ron`; no verdict |
| `D_flow_qualify_cv_dataset` | P2 | `DQualifyCv` | `Q_CV` | as qualify; CMU real use blocked (`AGENTS.md`) |
| `D_flow_qualify_timeseries_dataset` | P2 | `DQualifyTimeseries` | `Q_TS` | as qualify; real input blocked by gap G4 |

Transfer steps run iff their parameter is selected and always in the order above,
regardless of request order; `split_segments` runs iff `segments` is declared.
Unselected steps are recorded `skipped`, `optional: true`, reason `not_requested`.
`voltage_shift` uses the segment view; the other extractions use the dataset.

## Conditional Steps and Input Details

| Request | Input contract |
|---|---|
| `DQualifyIv` | `evidence` (smu), `channel_roles` (1-20, unique channels; declared, never inferred), optional `expectation` (ProductRef), `trust_policy` (U3 default, versioned and echoed), optional `source_tracking_tolerance` (V or A). |
| `DScreenIvLeakage` | `DQualifyIv` + `leakage{terminal, bias_points_v, window_v, criteria (1-32, leakage parameters in A), criteria_source}`. At least one of `bias_points_v`/`window_v`; the terminal is the role of exactly one measured channel; that channel must be voltage-sourced (swept, spot or held bias) and every limit below its compliance (CD11). |
| `DAnalyzeIvTransfer` | `DQualifyIv` + `transfer{gate_terminal, drain_terminal, polarity, vds (V), parameters (subset of gm_max, vth, ss, on_off, voltage_shift), derivative, vth, ss, on_off, segments, shift_at_current (A), criteria_source}`. `gm_max` and `max_gm_linear_extrapolation` need `derivative`; `constant_current` needs `icc`; `voltage_shift` needs `segments` and `shift_at_current`; specs for unselected parameters are rejected. Evidence must be a voltage sweep. |
| `DAnalyzeIvOutput` | `members[{evidence, outer_value}]` (2-16, one unit V or A, distinct values, swept voltage evidence), `channel_roles`, `trust_policy`, `outer_parameter` (terminal-style name such as `vgs`, needed by `stack_family`), `drain_terminal`, `ron_window` (V), `criteria_source`. |
| `DQualifyCv` | `evidence` (cmu), `channel_roles`, `expectation`, `trust_policy`, `imp_model` (Table 4-16 Literal; must equal the C request `model`), `sweep_kind` (`spot`, `voltage`, `frequency`, `ac_level`; must match the C kind). |
| `DQualifyTimeseries` | `evidence` (wgfmu), `channel_roles`, `expectation`, `trust_policy`, `measure_mode`, `event_plan` (1-256). |
| `DArchiveRun` | `envelopes` (1-`MAX_ARCHIVE_ENVELOPES` = 20, each naming a tool; more is a `ValidationError`, never truncated), `intent` (1-500 chars), optional `station{name, sha256}`, optional `created_at`, `include_table` (P1, default false; needs a dataset, view or derived ref). No path fields and no `persist` flag. |

## Archive (U2)

`D_flow_archive_run_bundle` passes every envelope (at most `MAX_ARCHIVE_ENVELOPES` = 20 =
one C flow + three CD D children + 16 upstream envelopes, so the largest CD run always
fits) and the placeholder ProductRefs they carry (atom `outputs.product`, flow `outputs.products`, deduplicated, at most 64) to
`build_manifest`. With `include_table`, the dataset/view/derived refs feed
`render_dataset_build_table`, and the table ref joins the bundle plan. `write_bundle`
returns `planned_paths` relative to the configured data root, `artifact_written:
false` and `write_refusal: [fake_mode, synthetic_origin]` on synthetic evidence. No
file is written and `D_atom_archive_run_load_bundle` is never called.

## Evidence Citation (U5)

`D_flow_screen_iv_leakage` returns `evidence_citation{eligible, blockers[],
external_requirements}`: a label, never a gate. It is eligible only with instrument
origin, computed analysis, trust at least `trusted_with_flags`, verdict `pass` and a
manifest; human approval is always listed as external. On synthetic stubs the blockers
are `synthetic_origin`, `analysis_not_computed` and `manifest_absent` (a standalone D
flow has no manifest).

## Reserved / Not Registered

- `D_flow_analyze_cv_capacitance`: Cox/Vfb atoms are P2 and gated on correction.
- `D_flow_render_run_report`: no first-wave consumer (D6); render atoms stay directly callable.
- `D_flow_replay_run_bundle`: offline replay deferred (U6).
- EasyEXPERT evidence (G5) and A-collected buffers are reserved evidence sources.

## Known Gaps

- DF2/M6: caller-passed A/B evidence stays `evidence_unverified`; no evidence binding yet.
- DF3/G1: C read records have no raw hash or parser-contract echo; the designated
  record locator is index-based.
- DF7: U2 asks for JSON+CSV; the CSV appears in planned paths only with `include_table`.
- Multi-channel WGFMU acquisitions have one read per channel, so
  `D_flow_qualify_timeseries_dataset` rejects every multi-channel WGFMU envelope as
  ambiguous (`c_ambiguous_read_records`) until per-channel selection is designed (G4).
  Accepted while WGFMU stays stub-gated (`AGENTS.md`); resolve before real WGFMU input.
- SMU QSCV as a `cv` source and SMU sampling as a `timeseries` source have no ingest
  design (DF5) and are not admitted.

## Sources and Implementation

- `tmp/d_flow_design_arbitration.md`: catalog, request and response contract.
- `tmp/d_atom_arbitration.md` sections 9 and 11: U1-U6 and amendments M1-M7.
- `src/b1500_test_agent/mcp/d_flows.py`: runner, chains and tools.
- `src/b1500_test_agent/schemas/d_flow.py`: typed requests, evidence and handoff helpers.
- `tests/test_d_flows.py`: discovery, order, chaining, taint, validation, archive, hygiene.
