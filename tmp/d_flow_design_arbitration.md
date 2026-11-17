# D Flow Design Arbitration

Date: 2026-11-17

Status: accepted arbitration (cross review and arbitration in one pass) for the first
`D_flow_*` wave of fake, loadable MCP tools. Planning only; implementation is a separate task.
Binding: `AGENTS.md` and `tmp/d_atom_arbitration.md` (U1-U6 decided) as amended by its section 11.
CD-side decisions and the open U7/U8 are in `tmp/cd_flow_design_arbitration.md`.

Inputs: `tmp/dcd_flow_design_opus55a.md` (A: 9 D flows + 2 reserved), `tmp/dcd_flow_design_opus55b.md`
(B: 7 D flows); precedents `tmp/{c_flow,ab_flow,b_flow}_design_arbitration.md`; code
`mcp/{common,c_flows,ab_flows}.py`, `schemas/c_flow.py`, `tests/test_c_flows.py`; `references/{recipes,devices}/`.

## 1. Scope and Invariants (Decided)

D flows are deterministic, hardware-free, replayable compositions of `D_atom_*` over evidence the
caller already holds. They inherit every D atom invariant (atom arbitration section 1). A flow adds
only ordering, skip bookkeeping, product-reference passing, label aggregation and taint checks; it
never computes numbers, data fingerprints, trust or verdicts. Under U1 every D flow runs over
placeholder stubs: `fake: true`, best reachable `analysis_state` is `not_computed`,
`analysis_completed` is always false, and no number, `pass` or trust above `synthetic_only` can
appear. Text about `complete` or `not_extractable` outcomes defines contract semantics only.

## 2. Composition Boundary (Decided)

| Caller | May call | Must not call |
|---|---|---|
| `D_flow_*` | `D_atom_*` from its fixed catalog, serially, in catalog order | A/B/C atoms or flows, D flows, CD flows, any caller-named atom |

- **Same-class rule (verified):** C flows import only `c_atoms` (`c_flows.py:11`); only the cross-family layer calls flows (AB imports A/B flows plus narrow atoms, `ab_flows.py:12-55`). Shared D chains are code helpers (`_q_iv_steps()`), like `_smu_setup()`.
- No loops over measurements; the only loop is serial over supplied members (`D_flow_analyze_iv_output`, 2..16).
- Trust gates live in atoms (atom #7): flows always call extract after `grade_trust` and record the atom's `not_extractable`.
- Verdict-bearing flows re-run the full qualify chain from ingest and never accept a caller-supplied `TrustSummary` or trust label.
- A flow stops only on child `ok:false`, exception, non-dict result, `hardware_touched` not `False`, `fake` not `True` (U1 phase rule) or a taint violation. Data outcomes never stop it.
- Files are written only by `D_atom_archive_run_write_bundle` inside `D_flow_archive_run_bundle`; under U2 nothing is written this phase.

## 3. Divergence Resolutions

| # | Topic | A | B | Decision and one-line rationale |
|---|---|---|---|---|
| D1 | Domain axis | data kind `iv/cv/timeseries/run` | source `smu/cmu/wgfmu/run` | **Data kind.** Source and kind are many-to-many (SMU gives IV, QSCV CV and sampling time series; CMU gives CV and C-t; WGFMU gives time series and DC IV; EasyEXPERT gives any), so a source axis multiplies every screen/analyze name per source, the cross product earlier arbitrations turned into parameters. The status table comes from the contract echo's module type (atom section 3a), not the name. |
| D2 | Qualify subject | `dataset` | data kind (`iv`) | **`dataset`.** Follows from D1 and matches the atom subject. |
| D3 | Hysteresis | own P1 flow | optional `voltage_shift` in transfer | **Folded into `D_flow_analyze_iv_transfer`.** Same chain plus `split_segments`; `extract_transfer_voltage_shift` is a transfer-subject atom; variants are parameters. |
| D4 | Derivative step | inside extract atoms | optional `derive_curve_compute_derivative` | **Inside extract atoms.** The binding catalog gives gm_max and Vth a declared derivative method; a separate step could compute a second, different gm. |
| D5 | Verdict in `analyze` | optional acceptance adds assess | never | **Never.** The operation names the guaranteed product: `screen` gives verdicts (U4 criteria mandatory), `analyze` gives parameters. Verdicts on parameters use the assess atom or a future screen flow. |
| D6 | Render flow | P2 registered | reserved | **Reserved.** No first-wave consumer, report atom is P2, envelope bloat; render atoms stay directly callable. |
| D7 | Archive flow | P0: manifest -> write -> [load] | P1: manifest -> [table] -> write -> [load] | **P0: `build_manifest` -> `write_bundle`.** write_bundle stub moves to P0 (amendment M3). load_bundle stays P1: its catalog purpose is replay (U6), not post-write checking. The CSV table step joins at P1 (U2 JSON+CSV). |
| D8 | Archive inputs | `data_root` Literal, `persist` flag | no path fields | **No path fields, no `persist` flag.** U2 fixes the root; a caller who only wants an inline manifest calls `build_manifest` directly. |
| D9 | Stub chaining (A DG1, B CG3) | null input + upstream refs | `ProductRef` | **Placeholder `ProductRef`** (section 8, amendment M1). Stubs never return null products. |
| D10 | Who sets `synthetic_only` | flow clamp | flow sets labels (B T3) | **Atoms set labels** (atom #6 is an atom rule; flows never compute trust). The flow aggregates and treats a stronger child label as `taint_violation`. |
| D11 | Later-priority optional steps | not addressed | P1 `source_tracking` in P0 chain | **Additive wave rule:** a flow registers at the priority of its required atoms; later optional steps join in their atom's wave as default-off request fields and never reorder required steps. |
| D12 | Envelope keys | `category`; trust/verdict in `outputs` | `operation`; top-level trust/verdict | **`category` (= operation), `domain`, `subject`** as in A/C envelopes; trust and verdict live in `outputs` as in the atom envelope. |
| D13 | Evidence input | C envelope or EasyEXPERT vectors | `AcquisitionEvidence` records | **A C flow envelope only, this wave,** with handoff `received` or `empty` (CD doc section 6). EasyEXPERT (G5) and A-collected buffers are reserved sources. |

## 4. Naming

`D_flow_<operation>_<domain>_<subject>`. Responses carry `category`, `domain` and `subject`, so tools
never parse names. Adding a token or matrix cell requires arbitration.

| Operation (closed) | Guaranteed product | Criteria |
|---|---|---|
| `qualify` | Trust-graded dataset with fit mask (placeholder refs this phase) | None; versioned U3 trust policy only |
| `screen` | One verdict per declared criterion set | Mandatory (U4) |
| `analyze` | `ExtractionResult` products, no verdict | Method specs mandatory (U4) |
| `archive` | Run manifest plus write-once bundle plan | None |
| reserved: `render`, `replay` | Not registered | n/a |

| Operation | `iv` | `cv` | `timeseries` | `run` |
|---|---|---|---|---|
| qualify | `dataset` | `dataset` | `dataset` | - |
| screen | `leakage` | - | - | - |
| analyze | `transfer`, `output` | reserved `capacitance` | - | - |
| archive | - | - | - | `bundle` (reserved: `render`/`report`, `replay`/`bundle`) |

No device, measurement-family, module or safety words. Variants are request fields:
`evidence.source`, the transfer parameter set, the Vth method and the segment rule.

## 5. Catalog

Shared chains are code helpers, not tools; `[ ]` marks a conditional step.

- **`Q_IV` (P0):** 1 `D_atom_ingest_request_build_expectation` [optional skip `expectation_supplied`] -> 2 `D_atom_ingest_smu_build_dataset` -> 3 `D_atom_qualify_dataset_classify_status` -> 4 `D_atom_qualify_dataset_check_completeness` -> 5 `D_atom_qualify_iv_check_compliance` -> 6 `D_atom_qualify_iv_check_resolution` -> 7 `D_atom_qualify_run_check_context` -> 8 `D_atom_qualify_dataset_grade_trust`. P1 extension: [`D_atom_qualify_iv_check_source_tracking`] between 6 and 7 when `source_tracking_tolerance` is declared.
- **`Q_CV` (P2):** build_expectation -> `D_atom_ingest_cmu_build_dataset` -> classify_status -> check_completeness -> `D_atom_qualify_cv_check_correction` -> check_context -> grade_trust.
- **`Q_TS` (P2):** build_expectation -> `D_atom_ingest_wgfmu_build_series` -> check_completeness -> `D_atom_qualify_timeseries_check_events` -> check_context -> grade_trust. No classify_status: WGFMU has no per-point status.

| Flow | Pri | Ordered atoms | Request | Key outputs |
|---|---|---|---|---|
| `D_flow_qualify_iv_dataset` | P0 | `Q_IV` | `DQualifyIv` | products `expectation`, `dataset`, `trust_summary`; `trust_level`; `check_outcomes` |
| `D_flow_screen_iv_leakage` | P0 | `Q_IV` -> `D_atom_extract_leakage_current` -> `D_atom_assess_value_check_limits` | `DScreenIvLeakage` | above + `results`, `verdict`, `verdict_scope`, `criteria_echo`, `evidence_citation` |
| `D_flow_archive_run_bundle` | P0 | `D_atom_archive_run_build_manifest` -> [P1: `D_atom_render_dataset_build_table` if `include_table`] -> `D_atom_archive_run_write_bundle` | `DArchiveRun` | `manifest` ref, `planned_paths`, `artifact_written: false`, `write_refusal` |
| `D_flow_analyze_iv_transfer` | P1 | `Q_IV` -> [`D_atom_shape_dataset_split_segments`] -> [`D_atom_extract_transfer_gm_max`] -> [`D_atom_extract_transfer_vth`] -> [`D_atom_extract_transfer_ss`] -> [`D_atom_extract_transfer_on_off`] -> [`D_atom_extract_transfer_voltage_shift`] | `DAnalyzeIvTransfer` | one `ExtractionResult` ref per selected parameter |
| `D_flow_analyze_iv_output` | P2 | per member (2..16, serial): `Q_IV`; then `D_atom_shape_dataset_stack_family` -> `D_atom_extract_output_ron` | `DAnalyzeIvOutput` | family view ref, Ron refs per outer-parameter segment |
| `D_flow_qualify_cv_dataset` | P2 | `Q_CV` | `DQualifyCv` | as qualify; CMU real use blocked (`AGENTS.md`) |
| `D_flow_qualify_timeseries_dataset` | P2 | `Q_TS` | `DQualifyTimeseries` | as qualify; real input blocked by G4 |

Registered: **7** (P0 3, P1 1, P2 3). Reserved, not registered: `D_flow_analyze_cv_capacitance`
(Cox/Vfb atoms P2, gated on correction), `D_flow_render_run_report` (D6), `D_flow_replay_run_bundle`
(U6). Transfer steps run iff their parameter is selected; `split_segments` runs iff `segments` is
declared. Unselected steps are recorded `skipped`, `optional: true`, reason `not_requested`.

## 6. Request Contract

New `schemas/d_flow.py` on the `FlowModel` base (`extra="forbid"`, `allow_inf_nan=False`,
`validate_default=True`), reusing `schemas/c_flow.py` and the planned `schemas/analysis.py`. Each tool
takes one required `request`; there is no omitted-request default.

```text
SourceRef   {kind: device_profile|recipe|caller, name, sha256: str|None}
ChannelRole {channel: Channel, terminal: str}          # declared, never inferred; channels unique
Evidence    {source: Literal per domain (iv: smu; cv: cmu; timeseries: wgfmu), c_flow_envelope: dict,
             upstream_evidence: list[dict] (<=16, unverified), declared_origin: synthetic|fixture|instrument|None}
DQualifyIv  {evidence, channel_roles: list[ChannelRole] (min 1), expectation: ProductRef|None,
             trust_policy: TrustPolicyRef = U3 default (versioned, echoed)}
DScreenIvLeakage   = DQualifyIv + leakage {terminal, bias_points_v: list[float], window_v: (lo, hi)|None,
             criteria: list[Criterion] (min 1, unit A), criteria_source: SourceRef}
DAnalyzeIvTransfer = DQualifyIv + transfer {gate_terminal, drain_terminal, polarity: n|p, vds: Quantity[V],
             parameters: set{gm_max, vth, ss, on_off, voltage_shift} (min 1), derivative|None, vth: VthSpec|None,
             ss|None, on_off|None, segments: SegmentRule|None, shift_at_current: Quantity[A]|None, criteria_source}
DAnalyzeIvOutput   {members: list[{evidence, outer_value: Quantity}] (2..16), channel_roles, trust_policy,
             drain_terminal, ron_window: QuantityRange[V], criteria_source}
DQualifyCv  = Evidence(cmu) + roles + imp_model (typed Literal, Table 4-16) + sweep_kind: voltage|frequency|ac_level
DQualifyTimeseries = Evidence(wgfmu) + roles + measure_mode: voltage|current + event_plan (min 1)
DArchiveRun {envelopes: list[dict] (1..8), intent: str (1..500), station: {name, sha256}|None,
             created_at: datetime|None, include_table: bool = False (P1)}         # no path fields
```

Validators run before the first atom call; a violation is a `ValidationError` at the MCP boundary
with no envelope and zero atom calls (C precedent):

- each selected transfer parameter has its spec; `derivative` for `gm_max` or `max_gm_linear_extrapolation`; `icc` for `constant_current`; `voltage_shift` needs `segments` and `shift_at_current`;
- at least one of `bias_points_v`/`window_v`; bias points inside `[min, max]` of the C sweep or equal to the spot `level`; exact units; no method aliases (`linear_extrapolation` rejected, G13);
- evidence handoff `received` or `empty` (pending, configuration-only, failed or data-less evidence is rejected); `declared_origin` cannot exceed the evidence origin;
- no request field uses a banned key (`measurement`, `sample`, `rows`, `values`, `status`, `passed`, `result_code`, `outcome`).

## 7. Response Contract

Built by `_d_flow_response()`, a sibling of `_flow_response()` in `common.py`:

```text
flow, flow_class: "D", category, domain, subject, purpose, fake: true, hardware_touched: false,
deterministic: true, ok, partial, destructive: false, consumptive: false,
analysis_state, analysis_completed: false, data_origin, synthetic,
atoms_called, atom_results[{phase (= D stage), atom, inputs (scalars + ProductRefs, never datasets),
  timestamp (UTC), status: ok|error|skipped, optional, reason, result | error}],
inputs (request echo; evidence summarized as {source, c_flow, execution_state, handoff_state, element_count}),
outputs{products{name: ProductRef}, check_outcomes, trust_level, verdict, verdict_scope,
  evidence_citation{eligible, blockers[]} (screen), archive{...} (archive)},
findings[{source_atom, check, severity, code, ...}], warnings, assumptions, evidence_missing, required_inputs,
contract_gaps, provenance{flow_version, schema_version, status_table_version, upstream[]},
side_effects{hardware: "none", filesystem_writes: [], artifact_written: false},
cleanup{owner: "none", performed: false}, error{type, message, at}   (only when ok=false)
```

- **`ok:false`** only for a child `ok:false`, exception or non-dict result, an unexpected marker or a taint violation. Data outcomes (`fail`, `untrusted`, `not_extractable`, `inconclusive`) keep `ok:true`; AB's `ok = not partial` (`ab_flows.py:202`) is not copied.
- **`partial`** when a required step was skipped or failed. Optional skips (`expectation_supplied`, `not_requested`) do not count; other reasons are `earlier_failure` and `taint_violation`.
- **`analysis_state`**, worst wins: `rejected_input` > `not_computed` > `not_extractable` > `inconclusive` > `complete`. Stub norm: `ok:true`, `partial:false`, `not_computed`.
- **`error.type`:** the atom set (`rejected_input`, `context_missing`, `unit_mismatch`, `size_limit`, `internal_error`) plus flow-level `taint_violation` and `unexpected_marker`.
- **Banned keys** (atom #5) are absent at the envelope top level and the top level of `inputs`/`outputs`; child payloads are retained unchanged.
- **Taint:** `data_origin` is the weakest of the C evidence (`fake:true` or `outputs.synthetic:true` means synthetic), upstream evidence, `declared_origin` and every D child. A child reporting `pass`/`fail`, `trusted`/`trusted_with_flags` or a stronger origin under synthetic or fixture origin is a `taint_violation`: `ok:false`, later steps skipped, `verdict: null`, child retained.
- **`evidence_citation`** is a U5 label, never a gate: eligible only with instrument origin, trust at least `trusted_with_flags`, `verdict: pass` and a manifest (standalone D flows add blocker `manifest_absent`); human approval is always listed as external. Always false now.
- **Stop-on-failure:** the first failure stops later atoms (`earlier_failure`); earlier records keep their timestamps and unchanged payloads.

## 8. DG1 Resolution: Placeholder Products (atom amendments M1-M2)

Atom #15 stubs return null outputs, so step 3 of every chain would reject a null dataset and no flow
could run end to end. Decided contract:

- Every stub returns its single primary product as `outputs.product: ProductRef` `{ref_kind: "placeholder", product_type, product_id, producer, analysis_state: "not_computed", data_origin, synthetic, content: null, upstream: [product_id]}`.
- `product_type` is closed: `expectation`, `dataset`, `check_report`, `trust_summary`, `view`, `derived`, `extraction_result`, `verdict`, `manifest`, `bundle_plan`, `plot_spec`, `table`, `report`.
- `product_id` = `placeholder:<producer>:<first 16 hex of SHA-256 of the canonical validated inputs>`: deterministic, never a timestamp. A validator enforces `ref_kind == "placeholder"` implies `content is None`, so no number can ride on a placeholder.
- **R1:** a `not_computed` placeholder input yields the atom's own placeholder, `analysis_state: not_computed`, `ok:true`. **R2:** a missing required product gives `ok:false`, `context_missing`. **R3:** a `product_type` mismatch gives `ok:false`, `rejected_input`, which makes miswiring testable. **R4:** origin propagates weakest-wins and is never raised. **R5:** labels follow M2 (`synthetic_only` or null, never a pass).
- Chain heads (`build_expectation`, ingest atoms) take evidence, not refs, and emit the first placeholder. Flows pass `result.outputs.product` into the next step and never fabricate refs.
- A's fallback (skip downstream with `upstream_not_computed`) is rejected: every flow would be permanently partial and nothing past ingest would be testable.

## 9. Known Gaps

| # | Gap | Owner |
|---|---|---|
| DF1 | Runner `_d_compose`: D atoms only, `ok:false`-only failure, accept on `hardware_touched is False` and (U1) `fake is True`, ProductRef passing. `_compose`/`_failed` are C-bound (`getattr(c_atoms, ...)`, execute/read gating; G7) | implementation |
| DF2 | Evidence binding: no run or session id in A/C envelopes, so caller-passed A/B evidence stays `evidence_unverified` and cannot lift trust caps (M6) | A/C + check_context |
| DF3 | Carried G1/G2/G3/G6: no raw ref or contract echo, free-string `format_hint`, status-less inline samples | C |
| DF4 | EasyEXPERT source needs G5; the async path (A collects the buffer after `awaiting_completion`) needs typed A buffer items | A |
| DF5 | SMU QSCV as a `cv` source and SMU sampling as a `timeseries` source have no ingest design | D atoms |
| DF6 | G13: `linear_extrapolation` and the valueless `leakage_threshold` in `mosfet.example.yaml` | references |
| DF7 | U2 asks for JSON+CSV; the CSV artifact needs `render_dataset_build_table` (P1), so P0 planned paths list the manifest only | D atom waves |
| DF8 | Real-mode read-back verification after `write_bundle` is unspecified (out of phase) | D atoms |
| DF9 | `mcp-tools/d-flows.md`, README index, `register_d_flows`, capabilities key `D_flows` | implementation |

## 10. Validation Plan (`tests/test_d_flows.py`, hardware-free)

1. **Discovery:** 7 tools via FastMCP with typed `request`; names match the regex and matrix; reference docs list every name; legacy registrations and `tests/test_c_flows.py` unchanged.
2. **Boundary and order:** spies on A/B/C modules see zero calls; table-driven exact `atoms_called`, including optional on/off variants.
3. **Stub chaining:** `Q_IV`, screen, transfer (all parameters), output (2 members) and archive run end to end with `ok:true`, `partial:false`, `not_computed`, no `rejected_input`; product ids identical across runs.
4. **Wiring (R3):** a stub patched to emit the wrong `product_type` gives `rejected_input` at the next step; earlier records retained; later steps `earlier_failure`.
5. **Taint:** origin synthetic; `trust_level`/`verdict` `synthetic_only`; no `verdict` or `check_outcome` equal to `pass` and no trusted level anywhere in D-produced subtrees; `declared_origin: instrument` on fake evidence stays synthetic; injected pass, trusted, raised-origin or `fake:false` children give `ok:false`.
6. **`ok` vs data:** patched `not_extractable`/`inconclusive`/`fail`/`untrusted` keep `ok:true`; a child with `passed: False` or `status: "failed"` but `ok:true` keeps `ok:true` (G7 regression).
7. **Criteria (U4):** missing criteria, method, roles or `SourceRef`, unit mismatch, aliases, out-of-range bias, pending or data-less evidence: `ValidationError`, zero atom calls; no criterion or method field has a default.
8. **Archive (U2):** filesystem monitor on `tmp_path`: no files, `artifact_written: false`, `write_refusal: [fake_mode, synthetic_origin]`, relative planned paths, `load_bundle` never called.
9. **Hygiene:** banned keys absent; `json.dumps(allow_nan=False)`; evidence summarized, not re-embedded; O(1) growth per step on a 100,000-point request; UTC timestamps on every record; identical envelopes apart from timestamps and `computed_at`.

## 11. User Decisions (none new; U7/U8 decided 2026-11-17, see CD arbitration)

None new for D flows. Every D divergence above is an arbitration-level design choice, and U1-U6 are
decided. The two open policy choices, U7 (real-mode ordering of D analysis vs outer cleanup) and U8
(a new C anchor for transfer curves), are in `tmp/cd_flow_design_arbitration.md`. Neither changes
this D catalog: U8 would only enable a CD wrapper over the existing `D_flow_analyze_iv_transfer`.

## Amendment 2026-11-17: review follow-ups

- **Archive cap:** `MAX_ARCHIVE_ENVELOPES` = `CD_ARCHIVED_C_FLOWS` (1) + `CD_ARCHIVED_D_CHILDREN` (3: expect atom, interpreting D flow, optional envelope atom) + `MAX_UPSTREAM_EVIDENCE` (16) = 20, replacing 8 in section 6 for `DArchiveRun` and `D_atom_archive_run_build_manifest`. A direct call above it is a `ValidationError` (flow) or `rejected_input` (atom); nothing is truncated.
- **Leakage channel:** `leakage.terminal` must be the role of exactly one measured channel. A held-bias channel of the biased staircase is checked at its held level, the swept channel along the sweep, a spot at its level; every limit must be below that channel's compliance (CD11, now also enforced in D). D and CD share `check_leakage_against_request(spec, c_request, channel)`.
- **Role coverage:** standalone D flows run the CD check (shared `measured_channels`/`unmapped_channels`) and, instead of rejecting, add flow-level finding `pin_map_incomplete` (`source_atom: null`, `check: pin_map`) and cap `outputs.trust_level` at `needs_review` (atom arbitration #14). The cap lowers a graded label only and never invents one (U1).
- **Archive table:** `include_table` without a dataset, view or derived ref is a request `ValidationError` before `build_manifest` runs.
- **Known gap:** `D_flow_qualify_timeseries_dataset` rejects every multi-channel WGFMU envelope as ambiguous; accepted while WGFMU is stub-gated (G4).
