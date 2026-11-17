# D Atom MCP Tools

D atoms are the deterministic post-acquisition analysis family. They consume evidence that A/C tools
already returned (C flow envelopes with a designated read record, A/B envelopes passed in explicitly)
and produce typed, unit-carrying, provenance-linked products. A/C own what the instrument said; D owns
what it means. D atoms sit beside A/B/C atoms; D and CD flows compose them.

```text
D_atom_<stage>_<subject>_<action>
```

**Phase status (user decision U1):** every D atom is a fake placeholder stub. It validates typed inputs,
echoes them, propagates data origin and returns a content-free product reference. No number is
computed, no `pass` verdict or trust grade is produced, and no file is written. All D atoms return
`fake: true` and `hardware_touched: false`. Contract: `tmp/d_atom_arbitration.md` (sections 9 and 11
govern); typed models live in `src/b1500_test_agent/schemas/d_atom.py`.

## Naming Vocabulary (closed)

| Stage (ordered) | Meaning | Allowed subjects |
|---|---|---|
| `ingest` | A/C evidence or C request -> canonical D objects; fixes units, roles, `data_origin` | `request`, `smu`, `cmu`, `wgfmu`, `easyexpert` |
| `qualify` | Data trust: status classes, checks, context, trust grade, fit mask; never alters values | `dataset`, `run`, `iv`, `cv`, `timeseries` |
| `shape` | Lossless views: segments, families, geometry-normalized columns | `dataset` |
| `derive` | Generic numerics on masked rows with a declared method | `curve`, `dataset`, `timeseries` |
| `extract` | Named parameters with method, window, bounds and trust gate | `leakage`, `transfer`, `output`, `cv` |
| `assess` | Compare values with declared criteria; a verdict label, never an action | `value`, `dataset` |
| `archive` | Manifest, write-once bundle plan, verified load | `run` |
| `render` | Deterministic plot spec, table and report content, returned inline | `dataset`, `run` |

Verbs: `build_*`, `classify_status`, `check_*`, `grade_trust`, `split_segments`, `stack_family`,
`normalize_geometry`, `compute_derivative`, `interpolate`, `fit_linear`, `summarize_*`,
`compare_reference`, `write_bundle`, `load_bundle`. Extract actions are parameter nouns. No device
names (`mosfet`, `fefet`), measurement families (`sweep`, `pulse`) or safety words (`validate`,
`approve`, `safe`) appear in D names. Responses carry `stage` and `subject`, so never parse names.

## Response Envelope

```text
atom, fake: true, hardware_touched: false, basis[], class: "D", stage, subject, warning,
ok, analysis_state, deterministic: true, parameters{scalars, product ids, evidence summaries},
outputs{product: ProductRef, stage fields}, findings[], warnings[], assumptions[], method|null,
data_origin, synthetic, provenance{upstream, input_fingerprints, output_fingerprint,
algorithm_version, status_table_version, schema_version, replayed, computed_at},
required_inputs[], evidence_missing[], side_effects{hardware: "none", filesystem_writes: [],
artifact_written: false}, error{type, message} (only when ok is false)
```

- `ok: false` means a tool error only (`analysis_state: rejected_input`). Error types:
  `rejected_input`, `context_missing`, `unit_mismatch`, `size_limit`, `internal_error`.
  Missing *evidence* is never an error: it is listed in `evidence_missing`.
- Data verdicts live in stage fields: qualify `check_outcome`, grade `trust_level`, extract
  `results[]`, assess `verdict` plus `verdict_scope`, plus top-level `findings`.
- Banned keys anywhere in D results: `status`, `passed`, `result_code`, `rows`, `values`, `sample`,
  `measurement`, `outcome` (the C runner reads these as failures or measurement data). Evidence is
  echoed as a banned-key-free summary with a SHA-256 fingerprint.
- `required_inputs` names upstream A/C evidence (for example `C_atom_smu_read_measurement_data`);
  D never calls those tools.

## Placeholder Products and Chaining (amendment M1)

Every stub returns its primary product as `outputs.product`:

```text
ProductRef{ref_kind: "placeholder", product_type, product_id, producer,
           analysis_state: "not_computed", data_origin, synthetic, content: null, upstream[]}
product_id = placeholder:<producer>:<first 16 hex of SHA-256 of the canonical validated inputs>
```

- `product_type` is closed: `expectation`, `dataset`, `check_report`, `trust_summary`, `view`,
  `derived`, `extraction_result`, `verdict`, `manifest`, `bundle_plan`, `plot_spec`, `table`, `report`.
- Ids are deterministic: wall-clock fields (`timestamp`, `computed_at`) are excluded from hashes.
  A validator rejects any placeholder with non-null `content`.
- **R1** a placeholder input yields the atom's own placeholder (`not_computed`, `ok: true`).
  **R2** a missing required product gives `context_missing`. **R3** a wrong `product_type` (or a
  wrong producer where the contract names one) gives `rejected_input`. **R4** `data_origin`
  propagates weakest-wins (`synthetic` < `fixture` < `instrument`); `declared_origin` may lower it,
  never raise it. Unmarked evidence counts as synthetic.
- Chain heads (`build_expectation`, `ingest_*`) take evidence, not refs. A C flow envelope must
  name its `designated_record` (the single read record); D never guesses which record holds data.

## Synthetic Labelling (amendment M2)

Under synthetic origin, `grade_trust` returns `trust_level: synthetic_only` and the assess atoms return
`verdict: synthetic_only` with `verdict_scope: null`; otherwise both are null. Qualify checks return
`check_outcome: null`; extract atoms return `results: []`. No stub emits `pass`, `fail`, `trusted` or
`trusted_with_flags`. These are provenance labels, not computation.

## D Class Atom Tools — ingest

| Tool | Meaning | Pri | Module | Product |
|---|---|---|---|---|
| `D_atom_ingest_request_build_expectation` | Data contract implied by a typed C request (`C_flow_<acquisition_kind>` schema). | P0 | SMU; CMU/WGFMU stub | `expectation` |
| `D_atom_ingest_smu_build_dataset` | Designated C SMU read record -> dataset with SI units, declared channel roles, verbatim status. | P0 | SMU | `dataset` |
| `D_atom_ingest_easyexpert_build_dataset` | A-parsed EasyEXPERT vectors -> dataset; analysis values marked reported (gap G5). | P1 | EasyEXPERT | `dataset` |
| `D_atom_ingest_cmu_build_dataset` | IMP-model (Table 4-16) primary/secondary columns and sweep variable. | P2 | CMU stub | `dataset` |
| `D_atom_ingest_wgfmu_build_series` | Per-channel arrays -> timeseries with event segments (blocked by gap G4). | P2 | WGFMU stub | `dataset` |

## D Class Atom Tools — qualify

| Tool | Meaning | Pri | Module | Product |
|---|---|---|---|---|
| `D_atom_qualify_dataset_classify_status` | Per-point status class by module and MM (letter, EEE, W/E, `Z`, sentinel). | P0 | SMU; CMU stub | `check_report` |
| `D_atom_qualify_dataset_check_completeness` | Expected vs received points, truncation, sentinel runs, monotonic index. | P0 | gen | `check_report` |
| `D_atom_qualify_iv_check_compliance` | `C`/`T` hits, onset, near-compliance by value ratio (U3 default 0.95). | P0 | SMU | `check_report` |
| `D_atom_qualify_iv_check_resolution` | Range-floor proximity; floor-limited points become bounds (Table 4-3). | P0 | SMU | `check_report` |
| `D_atom_qualify_run_check_context` | Upstream run evidence -> findings; caller A/B envelopes are `evidence_unverified` (M6). | P0 | gen | `check_report` |
| `D_atom_qualify_dataset_grade_trust` | Reports + versioned U3 `TrustPolicy` -> trust summary and fit mask. | P0 | gen | `trust_summary` |
| `D_atom_qualify_iv_check_source_tracking` | Measured source data vs programmed setpoints (declared tolerance). | P1 | SMU | `check_report` |
| `D_atom_qualify_dataset_check_continuity` | Spikes, steps, range-change glitches; report-only. | P2 | gen | `check_report` |
| `D_atom_qualify_cv_check_correction` | Correction enabled and covering every measured frequency. | P2 | CMU stub | `check_report` |
| `D_atom_qualify_timeseries_check_events` | Events vs plan, 10 ns grid, readable channel status. | P2 | WGFMU stub | `check_report` |

## D Class Atom Tools — shape and derive

| Tool | Meaning | Pri | Module | Product |
|---|---|---|---|---|
| `D_atom_shape_dataset_split_segments` | Forward/reverse, VAR2, repeat or event segments; values untouched. | P1 | gen | `view` |
| `D_atom_shape_dataset_stack_family` | Stack 2..16 datasets (each with its trust summary) by an outer parameter. | P1 | gen | `view` |
| `D_atom_shape_dataset_normalize_geometry` | W- or area-normalized derived columns (A/m, A/m^2, F/m^2). | P2 | gen | `view` |
| `D_atom_derive_curve_compute_derivative` | dy/dx on masked rows by a declared method; no bridging. | P1 | gen | `derived` |
| `D_atom_derive_curve_interpolate` | `y_at_x`, `x_at_y` (first crossing with direction), resample; no extrapolation by default. | P1 | gen | `derived` |
| `D_atom_derive_curve_fit_linear` | Least squares over a declared window. | P1 | gen | `derived` |
| `D_atom_derive_dataset_summarize_columns` | mean/std/median/min/max/n per column or segment. | P1 | gen | `derived` |
| `D_atom_derive_timeseries_summarize_windows` | Per-window or per-event statistics and drift slope. | P2 | SMU sampling; WGFMU stub | `derived` |

## D Class Atom Tools — extract

Extraction is trust-gated (only `trusted`/`trusted_with_flags` data would be extracted; otherwise
`not_extractable`). Methods, windows and biases are mandatory (U4): undeclared gives `context_missing`.
`allow_untrusted` only records `trust_override` and never lifts `synthetic_only`.

| Tool | Meaning | Pri | Module | Product |
|---|---|---|---|---|
| `D_atom_extract_leakage_current` | \|I\| at declared bias points and max \|I\| over a window; floor gives an upper bound. | P0 | SMU | `extraction_result` |
| `D_atom_extract_transfer_vth` | Vth by `constant_current` or `max_gm_linear_extrapolation` (alias `linear_extrapolation` rejected). | P1 | SMU | `extraction_result` |
| `D_atom_extract_transfer_gm_max` | gm_max (S) and Vg at gm_max. | P1 | SMU | `extraction_result` |
| `D_atom_extract_transfer_ss` | Minimum dVg/dlog10\|Id\| over a declared current window. | P1 | SMU | `extraction_result` |
| `D_atom_extract_transfer_on_off` | Ion, Ioff and ratio at declared gate biases. | P1 | SMU | `extraction_result` |
| `D_atom_extract_transfer_voltage_shift` | Signed V shift between two segments or datasets at a declared current. | P1 | SMU | `extraction_result` |
| `D_atom_extract_output_ron` | Ron = 1/slope near Vds = 0 per family segment. | P2 | SMU | `extraction_result` |
| `D_atom_extract_leakage_breakdown_voltage` | First V where \|I\| >= threshold; post hoc only. | P2 | SMU | `extraction_result` |
| `D_atom_extract_cv_cox` | Cox from a declared accumulation plateau; needs the correction report. | P2 | CMU stub | `extraction_result` |
| `D_atom_extract_cv_vfb` | Vfb by a declared method with explicit physical assumptions. | P2 | CMU stub | `extraction_result` |

## D Class Atom Tools — assess, archive and render

| Tool | Meaning | Pri | Module | Product |
|---|---|---|---|---|
| `D_atom_assess_value_check_limits` | Extracted quantities vs declared criteria + `criteria_source` (exact units). | P0 | gen | `verdict` |
| `D_atom_assess_dataset_check_envelope` | Post-hoc audit of extrema vs a declared envelope; escalates, never gates. | P1 | gen | `verdict` |
| `D_atom_assess_dataset_compare_reference` | Deltas vs a prior run or reported values within declared tolerance. | P2 | gen | `verdict` |
| `D_atom_archive_run_build_manifest` | Audit manifest returned inline; station by name + hash only; injectable `created_at`. Takes at most `MAX_ARCHIVE_ENVELOPES` (20) envelopes; more is `rejected_input`, never truncated. | P0 | gen | `manifest` |
| `D_atom_archive_run_write_bundle` | The single D writer: plans a write-once, content-addressed bundle; no path inputs. | P0 | gen | `bundle_plan` |
| `D_atom_archive_run_load_bundle` | Read-only load with hash verification (replay, U6); nothing is read in this phase. | P1 | gen | `manifest` |
| `D_atom_render_dataset_build_plot_spec` | Plot spec JSON: raw first, linear and semilog \|I\|, masked/flagged markers. | P1 | gen | `plot_spec` |
| `D_atom_render_dataset_build_table` | CSV/JSON table text with a unit header. | P1 | gen | `table` |
| `D_atom_render_run_build_report` | Template Markdown report; no LLM text, no recommendations. | P2 | gen | `report` |

P0 path (12): `build_expectation` -> `ingest_smu_build_dataset` -> `classify_status` -> `check_completeness`
-> `check_compliance` -> `check_resolution` -> `check_context` -> `grade_trust` ->
`extract_leakage_current` -> `check_limits` -> `build_manifest` -> `write_bundle`.

## Archive Writes (U2, amendment M4)

`D_atom_archive_run_write_bundle` returns `planned_paths` relative to the configured data root
(`processed/d-bundle-<hash>/manifest.json`, tables/plot specs under `processed/`, reports under
`reports/`), `artifact_written: false` and `write_refusal`. Every call refuses with `fake_mode`; the
origin adds `synthetic_origin` (synthetic) or `fixture_requires_test_root` (fixture). On the evidence
every current flow supplies, the result is `[fake_mode, synthetic_origin]`. No file is ever written.

## Boundary vs A/B/C

- D never touches hardware, sessions or remote software, never imports A/B/C tool modules or the
  hardware transport, and never calls any A/B/C atom or flow.
- Decoding instrument bytes, buffer reads, FMT changes and EasyEXPERT fetches stay A/C (C owns the
  measurement-specific read; the kernel parser lives in `instruments/b1500/`).
- D never authorizes, approves or gates safety, never picks the next measurement, retry or stop, and
  never mutates, imputes or smooths raw values.
- Status/data-code dictionaries are a planned resource (`b1500://data-codes`), not tools.
- Future D/CD runners accept D children only when `hardware_touched is False` and `fake is True`
  (U1 phase rule), treat only `ok: false` as failure, and pass `outputs.product` to the next step.
