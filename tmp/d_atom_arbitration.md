# D Atom Arbitration

Date: 2026-11-17

Status: accepted arbitration (cross review and arbitration in one pass) for the first
`D_atom_*` wave of fake, loadable MCP stubs. Planning only; implementation needs a
separate task. Section 9 items were decided by the user on 2026-11-17.

Inputs: `tmp/d_atom_candidates_opus55a.md` (A, 42 atoms), `tmp/d_atom_candidates_opus55b.md`
(B, 36 atoms); precedents `tmp/c_atom_arbitration.md`, `tmp/c_flow_design_arbitration.md`,
`tmp/ab_flow_design_arbitration.md`; code `mcp/{common,fake_data,a_atoms,b_atoms,c_atoms,c_flows,ab_flows}.py`,
`schemas/*`, `analysis/*`, `instruments/b1500/{parser_ascii.py,AGENTS.md}`, `references/manuals/structured/*`,
the guide index, and `../B1500A Programming Guide.pdf` (Edition 15) pages 44-57 and 435-438.

## 1. Scope and Invariants (Decided)

D is the deterministic post-acquisition analysis family. It consumes what A/C already
returned (decoded records, raw-payload reference, parser-contract echo, C request echo, and
A/B/C envelopes passed in explicitly as evidence). It produces typed, unit-carrying,
status-qualified, provenance-linked products. A/C own what the instrument said; D owns what it means.

D atoms never: touch hardware, sessions or remote software (`hardware_touched` is always
`false`); call any A/B/C atom or flow; read, drain or clear buffers or change `FMT`; decode
instrument bytes; authorize, approve or gate safety, or pick the next measurement, retry or
stop; mutate, delete, impute or smooth raw values (masks and derived columns are new objects
with lineage); guess context (FMT, IMP model, pin map, units, criteria); read private
station/config files implicitly (station by name plus hash only); use an LLM for numbers;
evaluate arbitrary expressions or code; use safety words (`validate`, `approve`, `safe`) for data checks.

## 2. Divergence Resolutions (Decided)

| # | Topic | A says | B says | Decision and one-line rationale |
|---|---|---|---|---|
| 1 | Decode ownership | A/C | D owns content decode | **A/C.** No D decode atoms. One kernel parser in `instruments/b1500/` serves A generic read, C measurement reads and A EasyEXPERT fetch. The C arbitration already assigned "parser/buffer plumbing" to A and "measurement-specific decode/read" to C. Current parser notes (`a_atoms.py:296`, `:989`; `c_atoms.py:313`) agree, and a D decoder would be a second entry point to the same parser. Offline re-decode: U6. |
| 2 | Naming | `<stage>_<target>_<action>`, 14 targets | `<stage>_<subject>_<action>`, 8 subjects plus matrix | **`D_atom_<stage>_<subject>_<action>`** with closed stages, closed subjects, an allowed stage x subject matrix and closed verbs. B's matrix stops cross-product growth, and A's curve-kind subjects make extract methods explicit. |
| 3 | Stages | normalize, qualify, derive, extract, assess, record, render | decode, qualify, shape, derive, archive, render | **ingest -> qualify -> shape -> derive -> extract -> assess -> archive -> render.** `decode` is dropped (#1). `ingest` replaces `normalize` because it marks the A/C -> D boundary where origin is fixed and avoids a clash with geometry normalization. `derive` (generic numerics) is split from `extract` (named, trust-gated parameters). `assess` stays separate so data trust is never confused with DUT acceptance. `archive` is preferred over `record` because flow audit records already use that word. |
| 4 | Result field names | top-level `outcome` enum, reused inside `CheckResult` | `check_outcome`, `verdict`, `findings` | **`ok` + `analysis_state` + stage fields `check_outcome` / `trust_level` / `verdict`, plus top-level `findings`.** Bare `outcome` is never used, because the AB envelope already uses `outcome` as a free-text summary (`ab_flows.py:199`) and A overloaded one key at two levels. |
| 5 | `ok` vs data verdicts | data failure is not a failure | same | **`ok:false` only for rejected input or internal error.** A failed leakage screen, `untrusted` or `not_extractable` keeps `ok:true`. These keys are banned at the top level and inside `parameters`: `status`, `passed`, `result_code` (read by `_failed()`, `c_flows.py:53-59`), `rows`, `values`, `sample`, `measurement` (scraped into C `outputs.data`, `c_flows.py:176-188`), and `outcome`. |
| 6 | Synthetic taint | `data_origin`, weakest wins | sticky `synthetic` bool | **`data_origin` in {synthetic, fixture, instrument}, weakest wins, plus a convenience `synthetic` bool.** Origin is derived from evidence: any upstream `fake:true` or `outputs.synthetic:true` makes it synthetic. A caller may lower the origin, never raise it. `replayed` lives in provenance. Synthetic input gives `trust_level` and `verdict` = `synthetic_only`, and fixture verdicts carry `verdict_scope: fixture`. C flows already emit `outputs.synthetic: true`. |
| 7 | Extraction on flagged or untrusted data | `not_extractable`, `allow_untrusted` override | refuse on reject or incomplete pin map | **Fit-mask rows only, and trust must be `trusted` or `trusted_with_flags` with declared criteria.** Otherwise the result is `analysis_state: not_extractable` (`ok:true`) with a reason. No bridging across excluded rows; minimum points are enforced. Floor-limited values become `bound: upper/lower`; they are not dropped. Flagged-but-kept rows are counted in `derived_from_flagged_points`. `allow_untrusted=true` is allowed for debugging: it sets `trust_override`, `assess` then returns `inconclusive`, and it never lifts `synthetic_only`. |
| 8 | File writes | persist (P1) and render may write | write_bundle (P0) and render may write | **Single writer: only `D_atom_archive_run_write_bundle`.** Writes happen in real mode only, under the configured data root (`data/raw`, `data/processed`, `data/reports`, all gitignored). They are content-addressed and write-once: no overwrite or delete, path traversal refused, station stored as name plus hash. Fake mode returns `planned_paths` with `artifact_written:false`. Priority P1, but required before the first real CD run. Policy: U2. |
| 9 | Render scope | plot spec, optional image, report P2 | table, figure with sidecar, report P2 | **Inline deterministic content only:** a plot spec JSON (raw first, linear plus semilog \|I\|, masked/flagged markers, units on axes), a CSV/JSON table with a unit header, and a template Markdown report (P2). No raster images in this wave, no LLM text, no `recommendations` field. Persistence goes through #8. |
| 10 | Expectation | completeness takes the request directly | separate `build_expectation` (P0) | **Separate `D_atom_ingest_request_build_expectation` (P0).** It is pure and can run before or after C. Ingest (programmed setpoints), completeness and a future CD "expect" phase all reuse it. |
| 11 | Run evidence | spread over several checks | `check_context` (P0) | **Keep `D_atom_qualify_run_check_context` (P0)**, the one place where `execution_state`, contract gaps, error codes, WGFMU status, FMT verification and upstream taint affect trust. |
| 12 | Terminal map, setpoints, mask, integrity | inside normalize/classify | separate P0 shape atoms | **Folded.** Channel roles and programmed setpoints are ingest inputs. The fit mask is a `grade_trust` output. Structural integrity is ingest schema validation plus completeness. Fewer P0 atoms, same guarantees. |
| 13 | Leakage | extract plus assess | qualify screen | **`extract_leakage_current` + `assess_value_check_limits`**, because data trust and DUT acceptance must stay separate. |
| 14 | Unknown or missing status | caps trust at `trusted_with_flags` | missing evidence caps at `needs_review` | **Unknown codes are excluded and cap trust at `needs_review`.** For `status_unavailable` (FMT 2/12/22, high-speed `sample`, EasyEXPERT vectors), trust is capped at `needs_review`, or at `trusted_with_flags` if the value-based compliance check ran. |
| 15 | First wave | open question | open question | **Fake stubs.** Pydantic-validated inputs, input echo, `analysis_state: not_computed`, null/empty outputs. No fabricated numbers, no `pass` (task framing; same as the A/B/C flows). Promotion to real computation: U1. |
| 16 | Dataset passing | inline cap, `dataset_ref` later | `artifact_ref` | **Inline, capped at the C `Count` bound of 100,000 points.** `dataset_ref` is a reserved name, not implemented, held for WGFMU-scale data. |
| 17 | Code dictionaries | status table as YAML | MCP resource | **Verified versioned YAML plus resource `b1500://data-codes`**, next to `b1500://capabilities`. It is a resource, not a tool. |
| 18 | P0 set | 10 | 13 | **11** (section 5). The first SMU spot/staircase and gate-leakage data path with audit. `check_resolution` is promoted to P0 because HRSMU leakage readings near the range floor must be reported as bounds. |

## 3. Factual Verdicts

These were checked against PG Edition 15. In the PDF, printed 1-24 is PDF 44 and printed
4-118 is PDF 436, so the guide index's page arithmetic (`+19`, `+317`) is off by one.

**(a) Status codes: both repo sources are wrong; the PDF governs.**

| Source (PG Ed. 15) | Content |
|---|---|
| Table 1-10, printed 1-33, PDF 53 (letter status, FMT 1/5/11/15) | `N` normal; `T` other channel at compliance; `C` this channel at compliance; `V` over range or sweep aborted by auto-stop/power compliance, data = `199.999E+99`; `X` oscillation or source not settled; `F` SMU force saturation; `G` search target not found / quasi-pulsed detection time over; `S` search stopped / quasi-pulsed slew or compliance; `U` CMU NULL-loop unbalance; `D` CMU IV-amplifier saturation |
| Table 1-7, PDF 52 | Source-data status: `W` first or intermediate sweep step, `E` last step |
| Tables 1-8/1-9, PDF 52 (FMT 21/25, summed-bit `EEE`) | SMU: 1 ADC overflow, 2 oscillation/force saturation, 4 other compliance, 8 this compliance, 16 search not found, 32 search stopped, 64 invalid data, 128 end of data. CMU: 1 ADC overflow, 2 NULL unbalance, 4 IV-amp saturation, 64 invalid, 128 EOD |
| Table 1-6, PDF 50; Table 1-11, PDF 54 | Layouts: `ABC`+12 digits (FMT 1/5), `ABC`+13 (11/15), `EEEFG`+13 (21/25), no header (2/12/22). Channel `Z` = extraneous/invalid data. Severity N<G<S<T<C<V<X (quasi-pulsed: N<T<C<V<X<G or S) |

- **`parser_ascii.py`:** `V` is not "overvoltage/unstable", `D` is not "invalid", and `L` is not a B1500 code. `F`/`G`/`S`/`U`/`W`/`E` and EEE are missing.
- **`b1500a-command-parameters.md`:** `W`, `U` and `D` are wrong; `F` and `E` are missing; `V` and `X` are incomplete; there are no EEE tables. The guide index row for PDF 44-54 repeats these errors.
- Classification therefore needs the module type (SMU/CMU) and MM (search or quasi-pulsed vs other), both taken from the contract echo.

**(b) FMT 5 is ASCII, not 8-byte binary.**

- **Table 4-24 (printed 4-119, PDF 437):** 1 = ASCII 12 digits with header `<CR/LF^EOI>`; 2 = same, no header; 3/4 = 4-byte binary (`<CR/LF^EOI>` / `<^EOI>`); **5 = ASCII 12 digits with header, terminator `,`**; 11/15 = 13-digit ASCII with header; 12 = 13 digits, no header; **13/14 = 8-byte binary**; 21/25 = 13 digits with EEE header (4155/4156 compatible); 22 = no header.
- **PDF 57 (printed 1-37):** "8 bytes binary ... enter the FMT13 or FMT14 command".
- `A_atom_flex_set_data_format`'s `{1,5,11,15,21,25}` and the driver `AGENTS.md` line "FMT 1 or FMT 5" are **correct**. The structured FMT row 5, the "extended timestamp" gloss for modes 11-25, and guide-index lines 64/160/319 are **wrong**.

Neither verdict leads to a code edit here; both are gaps G10-G12.

## 4. Naming

`D_atom_<stage>_<subject>_<action>`. Responses also carry `stage` and `subject` fields, so
tools never parse names. Adding a stage, subject or verb requires arbitration.

| Stage (ordered) | Meaning | Side effect |
|---|---|---|
| `ingest` | A/C records or C request -> canonical D objects. Fixes units, roles and `data_origin`. | none |
| `qualify` | Data trust: status classes, checks, context, trust grade and fit mask. Never alters values. | none |
| `shape` | Lossless views: segments, families, geometry-normalized columns. | none |
| `derive` | Generic numerics on masked rows with a declared method. | none |
| `extract` | Named device parameters with method, window, bounds and trust gate. | none |
| `assess` | Compare values with declared criteria and return a verdict. Never an action. | none |
| `archive` | Manifest, write-once bundle, verified load. | `write_bundle` only (real mode) |
| `render` | Deterministic plot spec, table and report content, returned inline. | none |

| Stage | Allowed subjects |
|---|---|
| ingest | `request`, `smu`, `cmu`, `wgfmu`, `easyexpert` (C object tokens; no `spgu`, because SPGU is source-only) |
| qualify | `dataset`, `run`, `iv`, `cv`, `timeseries` |
| shape | `dataset` |
| derive | `curve`, `dataset`, `timeseries` |
| extract | `leakage`, `transfer`, `output`, `cv` (characteristic-curve kinds, not device names) |
| assess | `value`, `dataset` |
| archive | `run` |
| render | `dataset`, `run` |

**Verbs (closed):** `build_*`, `classify_status`, `check_*`, `grade_trust`, `split_segments`,
`stack_family`, `normalize_geometry`, `compute_derivative`, `interpolate`, `fit_linear`,
`summarize_*`, `compare_reference`, `write_bundle`, `load_bundle`. `extract` actions are
parameter nouns. There are no device names (`mosfet`, `fefet`) or measurement-family names
(`sweep`, `pulse`) in D atom names.

## 5. Final D Atom Catalog (42)

**Shared models** (new `schemas/analysis.py`, `extra="forbid"`, `allow_inf_nan=False`):
`ParserContractEcho`, `AcquisitionEvidence`, `DataExpectation`, `AnalysisDataset` (columns
carry `role` and `origin`: measured, programmed, derived or reported; point status is
`{code, encoding: letter|numeric|none, class}`), `TrustPolicy`, `CheckReport`, `TrustSummary`,
`Quantity{value, unit, bound: exact|upper|lower}`, `ExtractionResult`, `Criterion`, `Verdict`, `RunManifest`.

**Units:** a closed set (V, A, s, Hz, F, S, Ohm, H, rad, deg, 1, A/m, A/m^2, F/m^2, V/dec; SS
is also given in mV/dec). Units are never inferred from magnitude; a mismatch gives `rejected_input`.

**Columns:** Det. Y = deterministic given the inputs and the algorithm, method and table
versions. Module: SMU = real priority; "gen" = module-agnostic, used on SMU data first; CMU and
WGFMU = stub-only (schema only, real use blocked per `AGENTS.md`); EE = EasyEXPERT.

| Atom | Purpose | Inputs -> outputs (sketch) | Pri | Det. | Module |
|---|---|---|---|---|---|
| `D_atom_ingest_request_build_expectation` | Data contract implied by a C request: columns, units, points per channel/segment, programmed setpoints, timestamp availability, expected status encoding | C flow `inputs` (typed `schemas/c_flow.py`), contract echo -> `DataExpectation` | P0 | Y | SMU; CMU/WGFMU fields stub |
| `D_atom_ingest_smu_build_dataset` | C SMU records (rows, high-speed `sample`) -> dataset: SI units, channel -> terminal roles, programmed setpoints when FMT mode=0, verbatim point status | records, `raw_ref{sha256,bytes}`, contract echo, expectation, `channel_roles` -> dataset, `unmapped_elements`, findings (`pin_map_incomplete`, `format_declared_not_verified`) | P0 | Y | SMU |
| `D_atom_ingest_easyexpert_build_dataset` | A-parsed EasyEXPERT vectors -> dataset. Device ID -> target, Count -> iteration; EasyEXPERT analysis values marked `origin: reported` | vectors, metadata, evidence -> dataset, `reported_parameters` | P1 | Y | EE (after gap G5) |
| `D_atom_ingest_cmu_build_dataset` | IMP-model primary/secondary columns (rad vs deg), LMN monitor columns, sweep variable (V or Hz) | records, IMP, LMN, sweep kind -> dataset | P2 | Y | CMU stub |
| `D_atom_ingest_wgfmu_build_series` | Per-channel (time, value) arrays -> timeseries with event segments, using averaged-midpoint and RAW grouping semantics | arrays, measure mode, `rdata`, event table -> dataset | P2 | Y | WGFMU stub |
| `D_atom_qualify_dataset_classify_status` | Verified versioned table (letter, EEE, W/E, channel `Z`, `199.999E+99`) -> per-point class by module and MM; counts; unknown codes | dataset, `status_table_version` -> classes, counts | P0 | Y | SMU; CMU classes stub |
| `D_atom_qualify_dataset_check_completeness` | Expected vs received points; read-limit truncation; NaN/sentinel runs; duplicate or non-monotonic index/time; timestamp wrap; likely cause (`V` auto-abort, error 260, WGFMU 3050) | dataset, expectation, buffer-count/error evidence -> `CheckReport` | P0 | Y | gen |
| `D_atom_qualify_iv_check_compliance` | `C`/`T` hits, onset bias, hit fraction, near-compliance by value ratio (the only signal for header-less formats), `LIM?`/`LOP?` cross-check | dataset, compliance per channel, `near_ratio`, readback -> `CheckReport` | P0 | Y | SMU |
| `D_atom_qualify_iv_check_resolution` | Floor per module/range/ASU/integration (Table 4-3); full-scale proximity; floor-limited points become bounds; `range_unknown` for auto-ranged ASCII | dataset, module type, ranging -> `CheckReport` | P0 | Y | SMU |
| `D_atom_qualify_run_check_context` | Upstream evidence -> findings: `execution_state`, `contract_gaps`, error codes, status byte, WGFMU status, FMT verification, upstream synthetic | A/B/C envelopes -> findings, `evidence_missing` | P0 | Y | gen (WGFMU inputs stub) |
| `D_atom_qualify_dataset_grade_trust` | Reduce reports and findings under `TrustPolicy` -> `trust_level` (trusted, trusted_with_flags, needs_review, untrusted, synthetic_only), `fit_mask`, reasons, `missing_checks` | reports, findings, policy -> `TrustSummary` | P0 | Y | gen |
| `D_atom_qualify_iv_check_source_tracking` | Measured source data (FMT mode != 0) vs programmed setpoints; `inconclusive` if absent | dataset, tolerance -> `CheckReport` | P1 | Y | SMU |
| `D_atom_qualify_dataset_check_continuity` | Spikes, steps, range-change glitches; report-only, never masks | dataset, x/y, declared thresholds -> `CheckReport` | P2 | Y | gen |
| `D_atom_qualify_cv_check_correction` | Correction enabled, covering every measured frequency, within declared age; caps capacitance trust | dataset, `CORRST?`/`CORRL?` evidence, compensation record -> `CheckReport` | P2 | Y | CMU stub |
| `D_atom_qualify_timeseries_check_events` | Events vs plan, 10 ns grid, channel status readable (`RUNNING_ILLEGAL`/`IDLE` = unreadable), errors 3050/3051 | dataset, event plan, status/errors -> `CheckReport` | P2 | Y | WGFMU stub |
| `D_atom_shape_dataset_split_segments` | Forward/reverse, VAR2, repeat or event segments; values untouched | dataset, rule -> segmented view | P1 | Y | gen |
| `D_atom_shape_dataset_stack_family` | Stack same-schema datasets by an outer parameter (for example Id-Vd per Vgs) | datasets, parameter -> family view | P1 | Y | gen |
| `D_atom_shape_dataset_normalize_geometry` | W- or area-normalized derived columns (A/m, A/m^2, F/m^2) | dataset, declared geometry -> view | P2 | Y | gen |
| `D_atom_derive_curve_compute_derivative` | dy/dx on masked rows (central difference or declared Savitzky-Golay window); no bridging over excluded rows | dataset, x, y, method -> derived column, edge flags | P1 | Y | gen |
| `D_atom_derive_curve_interpolate` | `y_at_x`, `x_at_y` (first crossing with direction), resample; linear or log-y; no extrapolation by default | dataset, mode, targets -> `Quantity[]` with bound | P1 | Y | gen |
| `D_atom_derive_curve_fit_linear` | Least squares over a declared window: slope, intercept, x-intercept, r^2, residual RMS, n | dataset, x, y, window -> fit record | P1 | Y | gen |
| `D_atom_derive_dataset_summarize_columns` | mean/std/median/min/max/n per column or segment on masked rows (repeat noise) | dataset, columns, group_by -> stats with units | P1 | Y | gen |
| `D_atom_derive_timeseries_summarize_windows` | Per-window or per-event stats and drift slope | dataset, windows or events -> stats | P2 | Y | SMU sampling; WGFMU stub |
| `D_atom_extract_leakage_current` | \|I\| at declared bias points (interpolated inside the data only) and max \|I\| over a window; reported as an upper bound at the floor | dataset, trust, terminal, bias points/window -> `ExtractionResult` | P0 | Y | SMU |
| `D_atom_extract_transfer_vth` | Vth by `constant_current` (Icc, optional W/L) or `max_gm_linear_extrapolation`; explicit n/p polarity and Vds | dataset, trust, method, criterion -> Vth, window, gm_max point | P1 | Y | SMU |
| `D_atom_extract_transfer_gm_max` | gm_max (S) and Vg at gm_max | dataset, trust, derivative method -> `ExtractionResult` | P1 | Y | SMU |
| `D_atom_extract_transfer_ss` | Minimum dVg/dlog10\|Id\| over a declared current window; floor-aware | dataset, trust, window, min decades -> SS | P1 | Y | SMU |
| `D_atom_extract_transfer_on_off` | Ion and Ioff at declared biases, ratio with bound propagation | dataset, trust, `vg_on`, `vg_off` -> Ion, Ioff, ratio | P1 | Y | SMU |
| `D_atom_extract_transfer_voltage_shift` | Signed V shift between two segments or datasets at a declared current (hysteresis; recipes reuse it for memory window or BTI) | segments, criterion -> dV, per-branch V | P1 | Y | SMU |
| `D_atom_extract_output_ron` | Ron = 1/slope near Vds=0, per Vgs segment | family, window -> Ron per segment | P2 | Y | SMU |
| `D_atom_extract_leakage_breakdown_voltage` | First V where \|I\| >= threshold (or compliance onset); `not_reached` otherwise. Post hoc only; breakdown runs need approval | dataset, threshold, direction -> V_bd | P2 | Y | SMU |
| `D_atom_extract_cv_cox` | Cox from a declared accumulation plateau; requires the correction check to pass | dataset, window -> Cox | P2 | Y | CMU stub |
| `D_atom_extract_cv_vfb` | Vfb by a declared method with explicit physical assumptions | dataset, method, assumptions -> Vfb | P2 | Y | CMU stub |
| `D_atom_assess_value_check_limits` | Extracted quantities vs declared criteria; exact unit match; bound-aware; `inconclusive` on `not_extractable` or override input | results, criteria -> `verdict`, `verdict_scope` | P0 | Y | gen |
| `D_atom_assess_dataset_check_envelope` | Post-hoc audit of observed extrema vs a declared envelope; `escalate:true`; not a safety gate | dataset, envelope -> per-quantity result | P1 | Y | gen |
| `D_atom_assess_dataset_compare_reference` | Deltas vs a reference (prior run or EasyEXPERT-reported values) within a declared tolerance | dataset or results, reference -> deltas, verdict | P2 | Y | gen |
| `D_atom_archive_run_build_manifest` | Audit manifest, returned and not written: intent, request, tool chain, inventory ref, station name+hash, contract, raw hashes, checks, trust, extractions, verdicts, assumptions, versions | envelopes and refs, injectable `created_at` -> `RunManifest`, hash | P0 | Y (except `created_at`) | gen |
| `D_atom_archive_run_write_bundle` | The single writer: write-once, content-addressed bundle under the data root (#8) | manifest, artifacts, root -> paths, sha256 | P1 | Y (FS write) | gen |
| `D_atom_archive_run_load_bundle` | Read-only load with hash verification of every artifact (for replay) | run_id or manifest ref -> manifest, artifacts, `hash_ok` | P1 | Y | gen |
| `D_atom_render_dataset_build_plot_spec` | Plot spec JSON: raw first, linear and semilog, masked/flagged markers, segments, units | dataset, axes, mask -> spec | P1 | Y | gen |
| `D_atom_render_dataset_build_table` | CSV/JSON text with a unit header and a metadata block | dataset(s), format -> text | P1 | Y | gen |
| `D_atom_render_run_build_report` | Template Markdown: measured, derived, assumptions, warnings and verdict sections; no LLM text | manifest, results, specs -> Markdown | P2 | Y | gen |

| Stage | Count | P0 | P1 | P2 |
|---|---:|---:|---:|---:|
| ingest | 5 | 2 | 1 | 2 |
| qualify | 10 | 6 | 1 | 3 |
| shape | 3 | 0 | 2 | 1 |
| derive | 5 | 0 | 4 | 1 |
| extract | 10 | 1 | 5 | 4 |
| assess | 3 | 1 | 1 | 1 |
| archive | 3 | 1 | 2 | 0 |
| render | 3 | 0 | 2 | 1 |
| **Total** | **42** | **11** | **18** | **13** |

The P0 path is: build_expectation -> ingest_smu -> classify_status -> completeness ->
compliance -> resolution -> check_context -> grade_trust -> extract_leakage_current ->
check_limits -> build_manifest.

## 6. Response Envelope (Decided)

A `_d_response()` helper is built over `_fake_response()`, the same way `_c_response()` is:

```text
atom, class: "D", stage, subject, fake, hardware_touched: false, basis[], warning (fake banner),
ok, analysis_state, deterministic: true,
parameters{scalar inputs, ids/refs; never full datasets}, outputs{stage-specific},
findings[{check, severity, code, count|indices, basis, manual_note?}], warnings[], assumptions[],
method{name, version, params} | null, data_origin, synthetic,
provenance{upstream[], input_fingerprints[], output_fingerprint, algorithm_version,
           status_table_version, schema_version, replayed, computed_at (excluded from hashes)},
required_inputs[]  (D analogue of C required_preconditions; names upstream A/C evidence; never called),
evidence_missing[], side_effects{hardware: "none", filesystem_writes: [], artifact_written: false},
error{type, message}  (only when ok=false)
```

- **`analysis_state`:** `not_computed` (fake stub), `complete`, `inconclusive` (evidence missing; `ok:true`), `not_extractable` (extract only; `ok:true`), `rejected_input` (`ok:false`).
- **`error.type`:** `rejected_input`, `context_missing` (a required input such as criteria, IMP or FMT is absent), `unit_mismatch`, `size_limit`, `internal_error`. Missing *evidence* (for example an error queue that was not captured) is never an error: it lowers trust and is listed in `evidence_missing`.
- **Stage outputs:** qualify checks give `outputs.check_outcome` (pass, flag, fail, inconclusive, not_applicable); grade gives `outputs.trust_level`; extract gives `outputs.results[]` (`ExtractionResult`); assess gives `outputs.verdict` (pass, fail, inconclusive, synthetic_only) plus `verdict_scope` (instrument or fixture).
- The banned keys from #5 apply at the top level and inside `parameters`. Invalid points are `null` plus a class, never NaN.
- **Future CD runners:** accept D children by `hardware_touched is False`, not by the C runner's `fake is True` rule (`c_flows.py:121-123`). Treat only `ok:false` as failure. Run D only when the C `execution_state` is `simulated_complete` (or a future real completion). Propagate `data_origin`. Never retry or adapt the measurement based on a D verdict.

## 7. Intentionally Not Added

| Candidate | Reason |
|---|---|
| D decode atoms (FLEX ASCII/binary, EasyEXPERT block/XTR), SCPI block stripping | A/C parser plumbing (#1) |
| Any D read, fetch, count, wait or poll | A/C acquisition |
| WGFMU `exportAscii` parser | Setup data owned by A; Fig. 4-1 columns unresolved |
| Error-message lookup or code dictionaries as tools | `A_atom_flex_lookup_error` exists; dictionaries are a resource (#17) |
| Standalone fingerprint atom | Capture-time hashes belong to A/C (G1). Other hashes are internal provenance and part of `build_manifest`. |
| Separate terminal-map, setpoint-align, apply-mask or integrity atoms | Folded into ingest and `grade_trust` (#12) |
| Elementwise transform, integration, CV impedance-model conversion | No P0/P1 consumer. Plot specs handle log scales; revisit with PUND or CMU. |
| WGFMU programmed-force recomputation, memory-budget preflight | C readback and `A_atom_wgfmu_get_interpolated_force_value` are the truth; preflight is C schema/policy |
| Offline CMU open/short/load math | Correction is instrument-side (B) |
| Smoothing, filtering, outlier deletion, imputation | These hide data problems; derivative windows are declared inside the method |
| Per-module (`hrsmu`/`mpsmu`) or per-family (`sweep`/`pulse`) duplicates | These are parameters |
| PUND, endurance, retention, NBTI/RTN, wake-up, FeFET memory window vs cycles, mobility, Rsd/TLM, Dit, doping, HSPICE fitting | Device experiments for recipes/ABC, composed from generic atoms |
| EasyEXPERT auto-analysis or read-out emulation | Use reported values with `compare_reference` |
| Arbitrary expression, model or script evaluation | Data-plane equivalent of raw FLEX |
| Next-measurement suggestion, adaptive planning, retry; `recommendations[]` | Phase 4 ABC with approval; narrative stays with the agent |
| Safety, interlock or approval in D; LLM narrative; delete or overwrite of archives; LIMS upload; SPGU D atoms; standalone unit conversion | Out of D scope, or unsafe |

## 8. Known Gaps

| # | Gap | Owner |
|---|---|---|
| G1 | `C_atom_smu/cmu_read_measurement_data` return `rows: []` inside `parameters` with no raw payload, `raw_sha256`/byte count, contract echo (FMT, output mode, TSC, MM, channels, IMP), or per-element status/channel/type tokens | C |
| G2 | `RunOptions.format_hint: str = "FMT1"` is a free string. It should be a typed Literal over the Table 4-24 modes plus output mode, with `fmt_source: declared/verified` | C schema |
| G3 | High-speed spot `sample`, WGFMU DC and CMU spot `measurement` lack status and channel | C |
| G4 | `C_atom_wgfmu_read_measurement_values(_partial)` returns `values` without the `time` array (API PDF 116-118), measure mode, `rdata`, event structure or channel status | C (WGFMU stub) |
| G5 | `A_atom_easyexpert_fetch_result` returns `result: None`. It needs parsed vectors, metadata and a raw block hash. `A_atom_flex_read_output_buffer` `items` are untyped | A |
| G6 | C flow `outputs.data` keeps only rows/values/sample/measurement and would drop G1-G4 fields | C flow |
| G7 | The `_compose()` non-fake stop rule and `_failed()` key semantics need a D-aware CD runner (section 6) | CD round |
| G8 | `A_atom_flex_set_data_format` should echo the verified mode meaning (ASCII or binary, digits, header, status encoding, terminator) | A |
| G9 | `schemas/result.py` `MeasurementResult.status` and the `analysis/*.py` stubs returning `{"status": ...}` conflict with the D key rules. D uses new `schemas/analysis.py` | analysis |
| G10 | Fix `parser_ascii.py` `MeasurementStatus` against Tables 1-7 to 1-10; add EEE decoding, `Z` and the sentinel; `parse_fmt1` is still a TODO | kernel |
| G11 | Fix the `b1500a-command-parameters.md` FMT and status tables. Add Tables 1-6, 1-8 and 1-9 and a versioned `b1500a-data-codes.yaml` | references |
| G12 | Guide index: FMT 5 rows (lines 64, 160, 319), the status row (line 63) and the page offsets are off by one | references |
| G13 | `mosfet.example.yaml` calls the method `linear_extrapolation` (D name `max_gm_linear_extrapolation`), and `leakage_threshold` is a check name with no value | references |
| G14 | Binary FMT 3/4/13/14 parsing is not implemented (P2, A/C). The WGFMU `exportAscii` columns are unresolved | A/C |
| G15 | Observed outside D scope: the `fake_data.py` header says the inventory "mirrors the user's real station", which may conflict with the `AGENTS.md` private-default rule | review |

## 9. User Decisions (decided by the user 2026-11-17)

U1 overrides the recommendation: all D atoms stay fake placeholder stubs in this
phase; no promotion to real computation is planned. U2-U6 adopt the recommended
defaults below as decided policy.

| # | Decision | Recommended default (U1: overridden, see above; U2-U6: adopted) |
|---|---|---|
| U1 | When may pure D atoms be promoted from fake stubs to real computation (`fake:false`, still `hardware_touched:false`)? | Per atom, P0 first, after tests on committed small anonymized fixtures (`data_origin: fixture`). |
| U2 | May MCP calls write files (`write_bundle`)? In which format? Should synthetic runs be archived? | Real mode only, under `data/` (gitignored), JSON+CSV, write-once. Synthetic-origin bundles are refused (planned paths only). Fixture bundles are written only to a test temp dir. |
| U3 | Default fit-exclusion policy and near-compliance ratio | Exclude `C`, `T`, `V`, `X`, `F`, `U`, `D`, EEE 1/2/4/8/64 and unknown codes. Exclude `G`/`S` outside search modes. `W`/`E` are source status, not exclusions. Flag (do not exclude) at a ratio of 0.95. |
| U4 | Extraction and acceptance criteria (Vth method/Icc, SS window, Ion/Ioff biases, leakage threshold): repo defaults or mandatory? | Mandatory, from the device profile, recipe or caller; no repo-wide numeric defaults; undeclared gives `context_missing`. |
| U5 | May future ABC flows cite D verdicts as precondition evidence (for example `leakage_check_passed` before CV)? | Yes, as evidence only: `data_origin: instrument`, trust at least `trusted_with_flags`, `verdict: pass`, manifest present, plus the human approval `AGENTS.md` requires. D never gates. |
| U6 | Offline scope: ingest EasyEXPERT export files or legacy data, or re-decode archived raw payloads? | Defer (P2). If wanted, export ingest becomes a D ingest atom (read-only, under the data root), and re-decode a hardware-free A-side parser atom. |

## 10. Forward Hooks (not designed here)

- **D flows:** `D_flow_<operation>_<domain>_<subject>` (both proposals agree; provisional). D-only and replayable. Operations: ingest, qualify, screen, analyze, archive, replay.
- **CD flows:** whether the first token is the intent (A) or the wrapped C family (B) is deferred to the CD-flow round.
- **Already supported:** the CD bracket expect (`build_expectation`) -> measure (C) -> interpret (ingest/qualify/extract/assess) -> archive; skipping D with a reason for `configuration_only`, `awaiting_completion` or `failed` C states; CMU and WGFMU variants reserved behind their stub atoms.

## 11. Amendments from D/CD flow arbitration (2026-11-17)

Source: `tmp/d_flow_design_arbitration.md` and `tmp/cd_flow_design_arbitration.md`. Sections 1-10
above are left unedited; where they conflict with this section, this section governs. U1-U6 are
unchanged: every D atom remains a fake placeholder stub, and nothing here plans real computation.

| # | Amends | Change |
|---|---|---|
| M1 | §2 #15, §5 shared models, §6 envelope | **Placeholder products (DG1).** New shared model `ProductRef{ref_kind: "placeholder", product_type, product_id, producer, analysis_state: "not_computed", data_origin, synthetic, content: null, upstream[]}`. `product_type` is closed: expectation, dataset, check_report, trust_summary, view, derived, extraction_result, verdict, manifest, bundle_plan, plot_spec, table, report. `product_id = placeholder:<producer>:<first 16 hex of SHA-256 of the canonical validated inputs>`, never a timestamp. A validator enforces placeholder implies `content is None`. Every stub returns its primary product as `outputs.product` instead of null. Product-typed inputs accept a `ProductRef`: (R1) a `not_computed` input gives `not_computed`, `ok:true`; (R2) a missing required product gives `context_missing`; (R3) a `product_type` mismatch gives `rejected_input`; (R4) origin propagates weakest-wins and is never raised. Chain heads (`build_expectation`, `ingest_*`) take evidence and emit the first placeholder. Inline product models stay defined but are unreachable under U1. |
| M2 | §2 #6 and #15 | **Stub labels.** Stubs derive `data_origin` from input refs and evidence markers. Under synthetic origin, `grade_trust` returns `trust_level: synthetic_only` and `assess_*` returns `verdict: synthetic_only` with `verdict_scope: null`; otherwise both are null. Qualify checks return `check_outcome: null`; extract atoms return `results: []` plus the product ref. These are provenance labels, not computation. No stub may emit `pass`, `fail`, `trusted` or `trusted_with_flags`. |
| M3 | §5 catalog, counts and P0 path | **`D_atom_archive_run_write_bundle` stub moves P1 -> P0**, because `D_flow_archive_run_bundle` (P0) calls it on every run and every CD archive phase calls that flow. New counts: P0 12, P1 17, P2 13 (archive row: P0 2, P1 1). The P0 path ends `... -> check_limits -> build_manifest -> write_bundle`. `D_atom_archive_run_load_bundle` stays P1: its consumer is the reserved replay flow (U6), and it is not a post-write step. |
| M4 | §2 #8, §6 | **write_bundle refusal codes.** Outputs add `write_refusal: list[fake_mode \| synthetic_origin \| fixture_requires_test_root]`. `planned_paths` are relative to the configured data root, and there are no path inputs. In this phase every call returns `[fake_mode, synthetic_origin]` and `artifact_written: false`. |
| M5 | §6 "Future CD runners" | **Phase rule (U1):** D and CD runners accept D children only when `hardware_touched is False` and `fake is True`; `fake: false` is an unexpected marker. D runs only on the C flow's designated read record with handoff `received` or `empty` (CD doc section 6), not on `execution_state` alone, because `outputs.data` can list configuration records (`c_flows.py:176-188`). |
| M6 | §5 `D_atom_qualify_run_check_context` | **Caller-passed A/B envelopes** are recorded with finding `evidence_unverified` and never lift a trust cap until evidence binding exists (a run or session id, in-process ABC passing, or a server evidence registry). |
| M7 | §10 forward hooks | **Resolved.** D flows are `D_flow_<operation>_<domain>_<subject>` with the data-kind domain (`iv`, `cv`, `timeseries`, `run`). CD flows mirror D names, and the C flow is chosen by a closed per-flow `acquisition.kind`. The CD fourth phase is `archive`, not `record`. The hook for skipping D on `configuration_only`, `awaiting_completion` or `failed` C states stands. |

## 12. Gap fixes applied (2026-11-17)

Closes G10, G11 (except the separate `b1500a-data-codes.yaml`) and G12. Every item was checked against `B1500A Programming Guide.pdf` Ed. 15, one page at a time (`pdftotext -f N -l N`) and against the printed footer on each page. Sections 1-11 are unchanged; the PDF numbers in section 3 are physical pages and were confirmed.

| Gap | Fix | PDF evidence |
|---|---|---|
| G10 status codes | `parser_ascii.py`: `MeasurementStatus` = N/T/C/V/X/F/G/S/U/D (`L` removed; `V` = over range or sweep aborted; `D` = CMU IV amplifier saturation). Added `SourceDataStatus` W/E, `SmuStatus`/`CmuStatus` `IntFlag` EEE decoding (`decode_eee_status` rejects CMU 8/16/32 and out-of-range values), `INVALID_DATA_VALUE = 199.999e99`, channel `Z`, data type `z`, both severity orders, and a `DATA_FORMATS` table (encoding, terminator, status field, digits, header length). New `tests/test_parser_ascii.py`. `parse_fmt1` is still a TODO | Tables 1-6 to 1-12, PDF 50-55; severity PDF 51 |
| G11 structured tables | `b1500a-command-parameters.md`: FMT section rebuilt from Table 4-24 (FMT 5 = ASCII 12 digits, header, comma terminator); status section rebuilt from Tables 1-6 to 1-10, with EEE tables. Data type table fixed: `R` = phase (rad), `X` = sampling index, plus `G` codes v/i/f/z. `b1500a-command-summary.yaml` FMT record: syntax is `FMT format[,mode]`, and FMT 13/14 are 8-byte binary | Table 4-24 PDF 437; PDF 57; Table 1-12 PDF 55 |
| G12 guide index | FMT rows (old lines 64/160/196/314/319) and status rows (old 63/195/320) corrected. The 8-byte format is an integer count with range, status and channel fields, not IEEE 754 (Figure 1-3) | PDF 68 |
| G12 page offset | The physical-page formulas are `N + 20/88/180/318/572` (index had `+19/87/179/317/571`). **The offset was not uniform.** About 85% of index page pairs were 1 low, Chapter 2 rows 2-24 to 2-44 were already right, `SSL` was 2 low, and Chapter 5 was listed as ending at 5-46/PDF 617; it really ends at 5-44/PDF 616, and 617 is the back cover. So every PDF number was recomputed from its printed page (printed pages checked against the Contents, PDF 7-20). The header now states the physical-page convention. All 101 command rows were content-checked on their page | Footers on PDF 22-616 |
| Same offset elsewhere | `b1500a-command-summary.yaml` (84 `pdf_pages`, all 42 records content-checked), `b1500a-error-codes.yaml` (62 `pdf_page` values from each code's position in the PDF; code 130 was already right, and its printed page was fixed to 5-3), `b1500a-initial-settings.md` (Table 2-13 = PDF 180), structured `README.md` convention note, and the `c_atoms.py` `HSS` docstring | Same |

**Where this section's evidence differs from sections 3 and 8:**

- (a) The off-by-one was not uniform (see above), so a blanket +1 would have broken 36 index rows.
- (b) The index error quick reference had invented code ranges (for example 9001-9999 SPGU) and was rebuilt.
- (c) The 8-byte IEEE 754 claim and the data type errors were also wrong; section 3 did not list them.

The WGFMU and EasyEXPERT indexes already use physical pages; their offsets match the footers. EasyEXPERT has about 20 scattered ±1 row inconsistencies between PDF and printed columns (for example SPGU Control 238-239 vs 2-65), which were left unfixed. The guide index's Status Byte rows still say bit 0 is unused and bit 3 is "buffer not empty"; this is noted in the index's Revision 3 and was not re-verified here.
