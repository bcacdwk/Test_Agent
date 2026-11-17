# D Atom Candidates - Opus 5.5 (a)

Date: 2026-11-17
Status: candidate proposal only. No code, no reference docs, no renames.
Scope: `D_atom_*` catalog, naming, boundaries, contract notes, and forward hooks for
`D_flow_*` / `CD_flow_*`. Settled by the user: **D = the analysis tool family
(deterministic post-acquisition analysis tools).**

Inputs read: `AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/roadmap.md`,
`docs/manual-extraction.md`, `src/b1500_test_agent/analysis/AGENTS.md`,
`src/b1500_test_agent/instruments/b1500/AGENTS.md`, `instrument-interaction-tools.md`,
all `mcp-tools/*.md`, `tmp/c_atom_arbitration.md`, `tmp/c_flow_design_arbitration.md`,
`tmp/ab_flow_design_arbitration.md`, `tmp/atom_taxonomy_opus.md`,
`tmp/flow_taxonomy_proposal_*.md`, `mcp/{common,fake_data,server,a_atoms,a_flows,c_atoms,c_flows}.py`,
`schemas/*.py`, `analysis/*.py`, `instruments/b1500/{parser_ascii,calibration,safety}.py`,
`references/{devices,recipes,station,policies,instruments}/*`, and
`references/manuals/structured/*` (command parameters, error codes, WGFMU API/timing/
examples/error codes, EasyEXPERT export formats/workflow templates). No other
`tmp/d_*` file was read.

---

## 1. Meaning of D

### 1.1 Decision (fixed by the user) and repo evidence

D is the **deterministic post-acquisition analysis family**: tools that take data
the A/C layers already acquired and turn it into trusted, unit-carrying, auditable
analysis results. D adds no instrument action.

This matches the repo's unclaimed layer and deferred work:

- `docs/architecture.md` layer 5, *Analysis: deterministic extraction, plotting,
  quality scoring, and report generation*, is the only architecture layer with no MCP
  family yet. `src/b1500_test_agent/analysis/` (`extraction.py`, `quality.py`,
  `plotting.py`, `reporting.py`) consists only of `not_implemented` stubs.
- `docs/roadmap.md` Phase 2 lists "data persistence for raw/parsed traces and metadata,
  basic IV plotting and parameter extraction, quality checks based on status codes and
  compliance hits".
- The driver transaction template (`instruments/b1500/AGENTS.md`) has steps 8 "read
  and parse data" (A/C) and 9 "persist raw and parsed outputs" (D), plus the analysis
  rules in `analysis/AGENTS.md`.
- `tmp/ab_flow_design_arbitration.md` rejected "Result classification / device
  analysis" as "future analysis/C/ABC, not AB". `c-flows.md` states that "the future
  acquisition layer must verify expected point counts and status codes before
  accepting data". No current tool does this.
- The pairing reads well: **AB = control plane** (observe/act), **CD = data plane**
  (measure/interpret), and ABCD covers the full transaction later.

### 1.2 Alternatives considered (record only)

| Interpretation | Why not chosen |
|---|---|
| DUT/Device (pin map, device envelope, approval) | Overlaps B preflight/policy and recipe/ABC experiment logic. |
| Diagnostics/Debug | B already has `diagnostic`. Data-side triage (status codes, discontinuities) fits D `qualify`. |
| Decision/closed loop (adaptive envelopes, stop conditions) | Roadmap Phase 4. It would widen agent autonomy. D may emit verdicts but never chooses actions. |
| Driver/transport | Sits below every class and is not an MCP family. |

### 1.3 Boundary against A, B and C

The guiding rule: **A/C own what the instrument said. D owns what it means.**
Every raw buffer read, result fetch and byte/text decode stays in A/C. D starts from
in-memory records that A/C have already returned.

| Concern | Owner | D's relationship |
|---|---|---|
| FLEX output-buffer count/read (`NUB?`, buffer read), `BC` | A (`A_atom_flex_query_buffer_count`, `A_atom_flex_read_output_buffer`, `A_flow_collect_flex_output_buffer`) | Consumes the returned records only. Never reads, drains or clears. |
| Parser contract setup (`FMT`, `TSC`/`TSR`, `:RESult:FORMat`) | A (`A_atom_flex_set_data_format`, `A_flow_prepare_flex_output_buffer`, `A_atom_easyexpert_set_result_format`) | Receives a *declared* contract echo as input. Never infers the format from data and never changes it. |
| Byte/text decoding: FMT ASCII/binary element tokenizing, SCPI definite-length block stripping, EasyEXPERT TEXT/XTR and export-file parsing | A/C parser plumbing, backed by the kernel parser library (`instruments/b1500/parser_ascii.py`) | **Not D.** D receives `DecodedElement` records (status code, channel, type code, value, raw token). |
| Measurement-specific read and decode (element order by MM, source-data/timestamp interleaving, grouping elements into steps) | C (`C_atom_smu_read_measurement_data`, `C_atom_cmu_read_measurement_data`, `C_atom_wgfmu_read_measurement_values[_partial]`, inline `sample`/`measurement` of spot atoms) | C returns element/row records in output order. D maps them into analysis columns, units, roles and origins. |
| EasyEXPERT result fetch | A (`A_atom_easyexpert_fetch_result`, `A_flow_collect_easyexpert_result`) | D normalizes already-parsed vectors and metadata. EasyEXPERT's own analysis outputs stay labeled "reported", never "D-extracted". |
| WGFMU `exportAscii` (setup CSV), progress/event/status queries | A | D may consume event-table evidence. It never queries. |
| Compliance readback (`LIM?`/`LOP?`), error queues, WGFMU status codes | A (readback) | D uses these as evidence inside `qualify` checks. |
| Compliance setting (`LIM`), interlock, zero/disable, correction state changes | B | D's envelope check is post-hoc audit evidence. It never authorizes, approves or gates hardware. |
| Measurement execution and configuration | C | D runs only on data from a completed C result (`simulated_complete` or real completion). |
| Status-code meaning | Shared reference table | A/C emit the status code verbatim. D applies the code-to-class mapping and the masking *policy* ("inspect status codes before trusting data"). |

**D atoms must never:**

1. Touch hardware, open sessions, or call any `A_*`, `B_*` or `C_*` atom or flow (fake or real).
2. Read, drain or clear any instrument buffer or queue, or change FMT/result format.
3. Decode raw instrument bytes. That belongs to A/C parser plumbing.
4. Authorize, approve or gate safety. They never decide or trigger the next
   measurement, retry, stop or adaptation.
5. Delete, overwrite, smooth away, impute or silently drop raw values. D masks and
   flags only, and every derived value is a new column with `origin: derived`.
6. Extrapolate beyond the data unless the caller sets an explicit flag, which is
   then reported.
7. Read private station data implicitly. Station, device and recipe data enter only
   as explicit inputs or `.example.yaml` references.
8. Use LLM output for any number. Narrative is outside D.
9. Use safety vocabulary (`validate`, `approve`, `safe`) for data checks. D uses
   `qualify` / `assess` so that data trust is never confused with safety validation.

### 1.4 Repo inconsistencies D depends on (must be resolved before real D)

1. **Two conflicting status-code vocabularies.** `instruments/b1500/parser_ascii.py`
   defines `N,C,T,V,X,D,L` with `D=INVALID` and `L=INTERVAL_TOO_SHORT`.
   `references/manuals/structured/b1500a-command-parameters.md` lists
   `N,T,C,W,X,U,V,G,D,S` with `D`/`G`/`S` = search-related and `U`/`W` = "verify exact
   page". `classify_status` needs one versioned table verified against Programming
   Guide PDF 48-52, covering letter codes and any numeric status encoding used by the
   extended formats. Until then, unknown codes are excluded and trust cannot be
   `trusted`.
2. **FMT 5 meaning conflicts.** The structured table and the guide index call FMT 5
   "8-byte binary". `A_atom_flex_set_data_format` treats `{1,5,11,15,21,25}` as the
   recommended header formats, and the driver `AGENTS.md` says "prefer ASCII FMT 1 or
   FMT 5". This is A's to fix (PDF 435-436), but D's contract echo must carry the
   verified meaning.
3. **C read atoms lack fields D needs.**
   - `C_atom_smu_read_measurement_data` and `C_atom_cmu_read_measurement_data` return
     `rows: []` with no raw payload reference, no parser-contract echo and no
     per-element status.
   - The high-speed `sample` has no status code.
   - `C_atom_wgfmu_read_measurement_values` returns `values` without the `time` array
     that `WGFMU_getMeasureValues` provides.
   - `C_flow` `outputs.data` keeps only `rows/values/sample/measurement`.

   These are C contract gaps and prerequisites for CD flows. D does not paper over
   them: missing status means `status_unavailable`.

---

## 2. Naming pattern

```text
D_atom_<stage>_<target>_<action>
```

This mirrors B's three-token `category_target_action`. For D, the first token is the
property an agent most needs to know before relying on the output: **which kind of
trust transformation the tool performs.** Canonical pipeline order (not alphabetical):
`normalize -> qualify -> derive -> extract -> assess -> record -> render`.

**Stage (closed, 7):**

| Stage | Meaning | Mutation rule |
|---|---|---|
| `normalize` | Turn A/C records into a canonical analysis dataset (SI units, columns, terminal roles, origins, segments). | Lossless. No value changes. |
| `qualify` | Decide data trustworthiness (status codes, completeness, compliance, floor, continuity, correction provenance). | Produces masks and flags only. |
| `derive` | Generic, device-agnostic numeric transforms (derivative, interpolation, fit, statistics). | New columns or scalars with `origin: derived` and the method. |
| `extract` | Named device parameters with a declared method (Vth, gm, SS, leakage, ...). | Scalar results with method, window, assumptions and bound. |
| `assess` | Compare values to declared criteria and return a verdict. | Verdict only. Never an action. |
| `record` | Provenance: fingerprints, run manifest, persistence/load of analysis artifacts. | Local artifact side effect only (real mode). |
| `render` | Deterministic presentation: plot specs and template reports. | Local artifact side effect only (real mode). |

**Target (closed, 14):**

- Module objects, reusing C tokens (`normalize` only): `smu`, `cmu`, `wgfmu`, `easyexpert`.
- Generic data subjects: `dataset`, `curve`, `value`, `payload`, `run`.
- Data domains (source-independent, so FLEX-derived and EasyEXPERT-derived IV data
  share atoms): `iv`, `cv`, `waveform`.
- Characteristic-curve kinds (`extract` only): `transfer` (Id-Vg), `output` (Id-Vd),
  `leakage` (two-terminal I-V). `cv` is reused for C-V.

There is no `spgu` target, because SPGU flows are source-only and produce no
measurement data. SPGU-biased SMU sampling data is SMU data.

**Action rules:**

- `qualify` actions are `classify_status`, `check_<aspect>` or `summarize_trust`.
- `extract` actions are parameter nouns (`vth`, `gm_max`, `ss`, `on_off`,
  `hysteresis`, `ron`, `current`, `breakdown_voltage`, `cox`, `vfb`).
- `assess` actions are `check_limits`, `check_envelope` or `compare_reference`.
- `record` actions are `fingerprint`, `manifest`, `persist` or `load`.
- `render` actions are `plot` or `report`.
- `normalize` actions are `dataset`, `result`, `events`, `split_branches` or `stack`.
- `derive` actions are `transform`, `derivative`, `interpolate`, `fit_linear`,
  `statistics`, `integrate` or `programmed_force`.

Rejected naming alternatives:

- `D_atom_<object>_<action>` (C-like) would duplicate module-agnostic tools
  (fingerprint, derivative, completeness) per module.
- `D_atom_<interface>_<action>` (A-like) is only meaningful for decoding, which D
  does not own.

---

## 3. Candidate D atom catalog

### 3.1 Shared typed objects (Pydantic sketch; proposed `schemas/analysis.py`)

| Model | Key fields |
|---|---|
| `DecodedElement` *(produced by A/C, consumed by D)* | `index`, `status_code: str \| None`, `status_encoding: letter\|numeric\|none`, `channel: int \| None`, `type_code`, `value: float \| None`, `raw_token`, `step: int \| None`, `role_hint: measured\|source\|timestamp` |
| `ParserContractEcho` | `fmt_mode`, `output_mode`, `timestamp_enabled`, `measurement_mode (MM \| None)`, `channels_in_order`, `imp_model \| None`, `evidence_ref` (A flow/atom record) |
| `AcquisitionEvidence` | `source_tool`, `measurement_family`, `object`, `contract: ParserContractEcho \| None`, `elements \| rows \| samples \| arrays`, `request` (C flow `inputs` dump), `raw_ref {sha256, length} \| None`, `data_origin: synthetic\|fixture\|replay\|instrument` |
| `Column` | `name`, `quantity`, `unit`, `channel`, `terminal`, `role: independent\|dependent\|time\|index\|parameter`, `origin: measured\|programmed\|derived\|reported` |
| `AnalysisDataset` | `dataset_id` (content hash), `family`, `object`, `columns`, `rows`, `point_status` (per row and column: raw code plus class), `segments [{name, rows, parameter}]`, `data_origin`, `provenance` |
| `StatusPolicy` | `exclude: set[StatusClass]`, `suspect: set[StatusClass]`, `near_compliance_ratio` |
| `StatusClass` | `normal`, `this_channel_compliance`, `other_channel_compliance`, `overflow`, `oscillation`, `search_status`, `instrument_condition`, `invalid_sentinel`, `status_unavailable`, `unknown` |
| `CheckResult` | `check`, `outcome: pass\|flag\|fail\|indeterminate`, `flagged_rows`, `reasons`, `metrics` |
| `TrustSummary` | `level: trusted\|trusted_with_flags\|untrusted\|indeterminate`, `fit_mask`, `reasons`, `missing_checks` |
| `Quantity` | `value`, `unit`, `bound: exact\|upper\|lower` |
| `ExtractionResult` | `parameter`, `quantity`, `outcome: extracted\|not_extractable`, `method {name, version, params}`, `window`, `n_used`, `n_excluded`, `assumptions`, `reason` |
| `Criterion` / `Verdict` | `parameter`, `op: le\|ge\|within\|abs_le`, `limit: Quantity`, `source: recipe\|device\|caller`; `outcome: pass\|fail\|indeterminate`, `verdict_scope: synthetic\|instrument` |
| `RunManifest` | `run_id`, `data_origin`, `intent` (C flow and atom names plus inputs), `inventory_ref`, `station_ref` (name and hash only), `parser_contract`, `raw_fingerprint`, `dataset_fingerprints`, `status_summary`, `checks`, `trust`, `extractions`, `verdicts`, `assumptions`, `warnings`, `versions`, `fake` markers |

### 3.2 Catalog

Det. = deterministic (same inputs and algorithm version give identical outputs,
excluding the computation timestamp). Priority: SMU IV first. CMU items are
**P2-gated** (real use is blocked until correction, SCUU and leakage flows exist).
WGFMU items are **P2-stub** (until B1530A extraction is validated).

#### normalize (6)

| Atom | Purpose | Inputs (sketch) | Outputs (sketch) | Basis | Det. | Pri |
|---|---|---|---|---|---|---|
| `D_atom_normalize_smu_dataset` | Map SMU records (spot/sweep/pulse/sampling/search; high-speed `sample`) into an `AnalysisDataset` with SI units, terminal roles, step index and timestamps. Insert programmed source values as `origin: programmed` when FMT did not output source data. | `evidence: AcquisitionEvidence`, `channel_roles: dict[int, terminal] \| None`, `request: dict` | `dataset`, `unmapped_elements`, `warnings` | MM map PDF 90-132; data type codes PDF 54; TSC caveats PDF 537-538 (no timestamps for high-speed/MM9/MM14-15); `analysis/AGENTS.md` (separate measured/derived/assumptions); pin-map example | Yes | **P0** |
| `D_atom_normalize_easyexpert_result` | Map parsed EasyEXPERT vectors and metadata into an `AnalysisDataset`. Device ID becomes `TestTarget` and Count becomes `IterationIndex`. EasyEXPERT analysis outputs are kept as `origin: reported`. | `vectors [{name, unit, values, dim1, dim2}]`, `metadata`, `data_origin` | `dataset`, `reported_parameters` | `easyexpert-export-formats.yaml` (RESult:FETch PDF 436-438; text export PDF 164-168; XSLT PDF 497-506) | Yes | P1 |
| `D_atom_normalize_dataset_split_branches` | Segment a dataset into forward/reverse branches or repeats. Values are unchanged. | `dataset`, `independent_column`, `rule: direction_change\|row_ranges\|repeat_count` | `dataset` with `segments` | Generic. Prerequisite for hysteresis. | Yes | P1 |
| `D_atom_normalize_dataset_stack` | Stack several datasets (same columns and units) into a family keyed by an outer parameter, for example one Id-Vd per Vgs from separate C runs. | `datasets[]`, `parameter {name, unit, values[]}` | family `dataset` | `recipes/mosfet/idvd.example.yaml` (`vgs_values`) | Yes | P1 |
| `D_atom_normalize_cmu_dataset` | Map CMU records into primary/secondary quantities per IMP model (explicit rad vs deg), LMN monitor columns (measured AC level and DC bias), and sweep variable (V or Hz). | `evidence`, `imp_model`, `lmn_enabled`, `sweep_kind: spot\|cv\|cf\|ac_level\|ct\|pulsed` | `dataset` | IMP Table 4-16 PDF 346; MM 17-26; MFCMU audit (LMN) | Yes | P2-gated |
| `D_atom_normalize_wgfmu_events` | Split per-channel (time, value) arrays into measurement-event segments. Applies averaged reported-time semantics and RAW sub-sample grouping. Also covers DC-mode samples. | `arrays {channel: {time[], value[]}}`, `measure_mode`, `event_plan[]` (from C request or `A_atom_wgfmu_get_measure_event_info` evidence) | `dataset` with per-event segments | `getMeasureValues` PDF 116-118; `setMeasureEvent` PDF 130-131; averaged midpoint PDF 131; RAW count `points*(1+int(avg/5ns))` PDF 151 | Yes | P2-stub |

#### qualify (10)

| Atom | Purpose | Inputs (sketch) | Outputs (sketch) | Basis | Det. | Pri |
|---|---|---|---|---|---|---|
| `D_atom_qualify_dataset_classify_status` | Map each point's verbatim status code to a `StatusClass` using a versioned table. Build `fit_mask` from policy. | `dataset`, `status_table_version`, `policy: StatusPolicy` (default exclude: compliance both kinds, overflow, oscillation, invalid sentinel, unknown) | per-point classes, `fit_mask`, counts by class, `unknown_codes`, policy echo | ASCII status PDF 48-52; `parser_ascii.py`; `analysis/AGENTS.md` ("exclude or flag compliance-limited, overvoltage, oscillation, invalid points before fitting") | Yes | **P0** |
| `D_atom_qualify_dataset_check_integrity` | Structural checks: units present and from the closed list, finite values or flagged nulls, row/column shape, independent variable monotonic per segment, `data_origin` present. | `dataset` | `CheckResult` | `analysis/AGENTS.md` ("always carry units") | Yes | **P0** |
| `D_atom_qualify_dataset_check_completeness` | Compare expected and actual points, and classify the likely cause (read-limit truncation, sweep auto-abort, missing channel, WGFMU memory overflow). | `dataset`, `request` or `expected_rows`, `max_items_used`, optional error evidence (A error queue / WGFMU errors) | `CheckResult` with `expected`, `actual`, `missing_steps`, `cause` | `c-flows.md` ("a read limit is not a completeness check"); auto-abort PDF 134-135; WGFMU error 3050 PDF 158 | Yes | **P0** |
| `D_atom_qualify_iv_check_compliance` | Report compliance-hit rows, first-hit bias (onset), hit fraction and near-compliance rows (measured value within a ratio of the programmed compliance). Classify as `none\|onset\|dominant`. | `dataset`, `compliance {channel: Quantity, polarity}` (from request), optional `A_atom_flex_query_compliance_status` evidence, `near_ratio` | `CheckResult` | Status `C`/`T`; `LIM?`/`LOP?` readback; `SmuSpot`/`SmuSweep` compliance fields | Yes | **P0** |
| `D_atom_qualify_dataset_summarize_trust` | Aggregate check results into one trust level and a combined fit mask. A missing required check gives `indeterminate`, never `trusted`. | `checks[]`, `classify_output`, `required_checks` (domain default) | `TrustSummary` | SKILL step 7 ("interpret status codes and data quality before extracting") | Yes | **P0** |
| `D_atom_qualify_iv_check_range_floor` | Flag points at or below the declared measurement floor for the module and ranging used, so those values become upper bounds. | `dataset`, `module_type per channel` (MPSMU/HRSMU, ASU flag), `ranging` (from request), `floor_override` | `CheckResult` (`floor_limited` rows) | Table 4-3 PDF 336-337; `_SMU_RANGE_HINTS`; `safety_limits.example.yaml` `min_current_range` | Yes | P1 |
| `D_atom_qualify_iv_check_source_tracking` | Compare the measured force-side quantity with the programmed source to detect a compliance-limited or unsettled source. Returns `indeterminate` if no measured source column exists. | `dataset`, `tolerance` | `CheckResult` | CMM/FMT source-data output; `C_atom_smu_force_*` fields | Yes | P1 |
| `D_atom_qualify_curve_check_continuity` | Robust detection of spikes, steps and unexpected non-monotonic segments (possible range-change glitch or contact loss). Flags only. | `dataset`, `x`, `y`, `expectation: increasing\|decreasing\|none`, `threshold (k*MAD on delta log\|y\|)` | `CheckResult` | Debug skill triage step 3; `references/debug/README.md` | Yes | P1 |
| `D_atom_qualify_cv_check_correction_provenance` | Check that phase/open/short/load records cover every measured frequency and are fresh. If not, cap trust as `untrusted_capacitance`. | `dataset` (frequencies), `correction_records` (shape of `station/compensation/latest.example.yaml`), optional `CORRST?`/`CORRL?` evidence, `max_age` | `CheckResult` | `approval-policy.example.yaml` (`capacitance_without_correction`); MFCMU audit L6; `calibration.py` TODO | Yes | P2-gated |
| `D_atom_qualify_waveform_check_events` | Per-event checks: count matches the plan, time grid follows the 10 ns resolution, channel status was readable (COMPLETED vs RUNNING_ILLEGAL/IDLE), no memory/FIFO overflow. | `dataset`, `event_plan`, `channel_status_codes`, `error_evidence` | `CheckResult` | WGFMU status 10000-10006 and errors 3050/3051 (`b1530a-wgfmu-error-codes.yaml`); timing doc | Yes | P2-stub |

#### derive (7)

| Atom | Purpose | Inputs (sketch) | Outputs (sketch) | Basis | Det. | Pri |
|---|---|---|---|---|---|---|
| `D_atom_derive_curve_transform` | Elementwise transform from a closed op list: `abs`, `negate`, `log10_abs`, `scale`, `ratio` (V/I to R), `product` (V*I to P). Computes the output unit. | `dataset`, `op`, `columns`, `factor: Quantity \| None` | new column (`origin: derived`) | `analysis/AGENTS.md` (semilog views) | Yes | P1 |
| `D_atom_derive_curve_derivative` | dy/dx on masked rows (no bridging over excluded rows) with a declared method (`central_difference\|savitzky_golay(window, order)`). Supports log-x. | `dataset`, `x`, `y`, `method`, `fit_mask` | derivative column (for example gm in S), edge flags | Textbook numeric method (non-manual) | Yes | P1 |
| `D_atom_derive_curve_interpolate` | `y_at_x`, `x_at_y` (first crossing with direction) or `resample` onto a common grid. Linear or log-y. `extrapolate=False` by default. | `dataset`, `mode`, `targets[]`, `method` | values with `bound`, or a resampled dataset | Generic | Yes | P1 |
| `D_atom_derive_curve_fit_linear` | Least-squares line over a declared window (x range, rows, or auto window around max slope +/- n). Optional log10 y. | `dataset`, `x`, `y`, `window`, `y_transform` | slope, intercept, x-intercept, r^2, residual RMS, n, window echo | Generic | Yes | P1 |
| `D_atom_derive_dataset_statistics` | Per-column or per-segment summary on masked rows: mean, std, median, min, max, count. Repeat noise at the same bias. | `dataset`, `columns`, `group_by: segment\|none` | stats table with units | Generic; spot repeat / noise floor | Yes | P1 |
| `D_atom_derive_curve_integrate` | Trapezoidal integral of y dx (for example I dt to Q). Refuses gaps by default. | `dataset`, `x`, `y`, `allow_gaps` | cumulative column and total | Generic | Yes | P2 |
| `D_atom_derive_waveform_programmed_force` | Compute the *programmed* WGFMU force voltage at each sample time from C request vectors and sequence loops (`origin: programmed`). This is the offline counterpart of `A_atom_wgfmu_get_interpolated_force_value`, which remains the instrument-side truth. | `dataset`, `vectors[]`, `sequence {pattern, loops}` | programmed-V column | `getInterpolatedForceValue` PDF 107-108; Example 9 `writeResults3` | Yes | P2-stub |

#### extract (10)

All extract atoms take `dataset`, `trust: TrustSummary` (or `fit_mask`) and method
parameters, and return `ExtractionResult`. They return `not_extractable` (not a
failure) when the trust level is insufficient, the window has too few points, the
window contains compliance hits, or the floor dominates. `allow_untrusted=True`
overrides this but tags the result.

| Atom | Purpose | Method inputs | Outputs | Basis | Det. | Pri |
|---|---|---|---|---|---|---|
| `D_atom_extract_leakage_current` | Leakage \|I\| at declared bias points (interpolated only inside the data) and max \|I\| over a window. Reported as an upper bound when floor-limited. | `v`, `i`, `at_bias[]`, `window`, `floor` | per-bias `Quantity`, `max_abs` | README (gate leakage checks are a first SMU target); `AGENTS.md` (CMU waits for leakage validation); `mosfet.example.yaml` `leakage_threshold` | Yes | **P0** |
| `D_atom_extract_transfer_vth` | Vth by `constant_current` (Icc, optional W/L scaling) or `max_gm_extrapolation` (ELR, optional -Vds/2), with n/p polarity. | `vg`, `id`, `method`, `icc`, `w_over_l`, `vds`, `polarity` | Vth (V), window, gm_max point, assumptions | `devices/mosfet.example.yaml` `vth_methods`; `analysis/AGENTS.md`; WGFMU examples note that the manual does not define Vth math, so provenance is "textbook, non-manual" | Yes | P1 |
| `D_atom_extract_transfer_gm_max` | gm_max (S) and Vg at gm_max via `derive_curve_derivative`. | `vg`, `id`, `derivative_method` | gm_max, Vg@gm_max | `analysis/AGENTS.md` (gm) | Yes | P1 |
| `D_atom_extract_transfer_ss` | Minimum dVg/dlog10\|Id\| over a declared current-decade window. Floor-aware. | `vg`, `id`, `current_window`, `min_points` | SS (mV/dec, also V/dec), window | `analysis/AGENTS.md` (SS) | Yes | P1 |
| `D_atom_extract_transfer_on_off` | Ion at Vg_on, Ioff at Vg_off (or min \|Id\| in window), and the on/off ratio with bound propagation. | `vg`, `id`, `vg_on`, `vg_off \| window` | Ion, Ioff, ratio (unitless "1") | Common transfer metrics | Yes | P1 |
| `D_atom_extract_transfer_hysteresis` | Delta-V between forward and reverse branches at a constant current (requires `split_branches`). | `branches`, `icc` | delta-V (V), per-branch V | `mosfet.example.yaml` `hysteresis`; FeFET `memory_window` is a recipe-level application | Yes | P2 |
| `D_atom_extract_output_ron` | Ron = 1 / slope of a linear fit near Vds = 0, per Vgs segment. | `vd`, `id`, `window`, `segments` | Ron (Ohm) per segment | Common output metric | Yes | P2 |
| `D_atom_extract_leakage_breakdown_voltage` | First V where \|I\| >= threshold (or compliance onset) in a declared direction. Returns `not_reached` if none. | `v`, `i`, `threshold`, `direction` | V_bd or not_reached | Breakdown/destructive tests need recipe-level approval (`safety_limits.example.yaml`) | Yes | P2 |
| `D_atom_extract_cv_cox` | Cox from an accumulation plateau in a declared window. Requires `correction_provenance` to pass. | `v`, `c`, `window` | Cox (F) | `analysis/AGENTS.md` (Cox); approval policy | Yes | P2-gated |
| `D_atom_extract_cv_vfb` | Vfb by a declared method with explicit physical assumptions (oxide permittivity, doping). Requires `correction_provenance` to pass. | `v`, `c`, `method`, `assumptions` | Vfb (V) | `analysis/AGENTS.md` (Vfb) | Yes | P2-gated |

#### assess (3)

| Atom | Purpose | Inputs (sketch) | Outputs (sketch) | Basis | Det. | Pri |
|---|---|---|---|---|---|---|
| `D_atom_assess_value_check_limits` | Compare extracted quantities with declared criteria. Units must match exactly. Inputs that are not extracted or have insufficient trust give `indeterminate`. | `values: ExtractionResult[] \| Quantity[]`, `criteria: Criterion[]`, `trust`, `data_origin` | `Verdict[]`, overall verdict, `verdict_scope` | Device/recipe YAML (`safe_limits`, `quality_checks`); needed for the P0 leakage check | Yes | **P0** |
| `D_atom_assess_dataset_check_envelope` | Post-hoc audit that observed programmed and measured extrema stayed inside a declared station/device envelope. Exceedance sets `escalate: true` for the outer layer. Explicitly **not** a safety gate. | `dataset`, `envelope {quantity: Quantity}` | per-quantity within/exceeded, `escalate` | `AGENTS.md` (auditable runs); `station-profile.example.yaml` limits | Yes | P1 |
| `D_atom_assess_dataset_compare_reference` | Align and compare against a reference dataset or parameter set (prior run, EasyEXPERT-reported values, future simulation). Returns deltas and a drift verdict within a declared tolerance. | `dataset \| results`, `reference`, `tolerance` | deltas, verdict | `references/hspice/README.md` (measured vs simulated); EasyEXPERT "Vth gmMax" app output | Yes | P2 |

#### record (4)

| Atom | Purpose | Inputs (sketch) | Outputs (sketch) | Basis | Det. | Pri |
|---|---|---|---|---|---|---|
| `D_atom_record_payload_fingerprint` | SHA-256 over a raw payload (as A/C returned it) or canonical JSON (sorted keys, fixed float repr, timestamps excluded). Ties parsed data to raw data. | `payload: str \| object`, `canonicalization_version` | `sha256`, `byte_length`, `canonicalization` | `AGENTS.md` (record raw and parsed data) | Yes | **P0** |
| `D_atom_record_run_manifest` | Assemble the audit manifest. The manifest is returned, not written. | Upstream C/A audit records, `raw_ref`, dataset fingerprints, checks, trust, extractions, verdicts, assumptions, station/device/recipe refs (name and hash) | `RunManifest` | `AGENTS.md` (command intent, parameters, timestamps, inventory, status codes, raw/parsed data, assumptions) | Yes (except creation time) | **P0** |
| `D_atom_record_dataset_persist` | Write raw, processed and manifest artifacts content-addressed under an explicit data root (`raw/`, `processed/`, `reports/`). Refuses to overwrite. Fake mode returns planned paths only. | `manifest`, `raw_payload`, `datasets`, `figures`, `data_root`, `overwrite=False` | paths, `artifact_written` | `data/README.md`; roadmap Phase 2 | Yes (paths) | P1 |
| `D_atom_record_dataset_load` | Load a persisted dataset or manifest by id and verify its fingerprint, for offline re-analysis without hardware. | `dataset_id \| manifest_ref`, `data_root` | `dataset`, `manifest`, `fingerprint_ok` | Same | Yes | P1 |

#### render (2)

| Atom | Purpose | Inputs (sketch) | Outputs (sketch) | Basis | Det. | Pri |
|---|---|---|---|---|---|---|
| `D_atom_render_curve_plot` | Deterministic plot spec (linear and/or semilog-y). Excluded and flagged points are drawn with distinct markers, segments are colored, and axes carry units. Figure metadata is saved next to any image in real mode. | `dataset`, `x`, `y[]`, `scales`, `mask/flags` | plot spec JSON, optional image path, `artifact_written` | `analysis/AGENTS.md` (plot raw before extraction; semilog; save figure metadata) | Yes (spec) | P1 |
| `D_atom_render_run_report` | Markdown report from a fixed template, with separate sections for measured values, derived parameters, assumptions, warnings and verdicts. No LLM text. | `manifest`, `plots`, `results` | Markdown text, optional path | `analysis/AGENTS.md`; SKILL step 8; roadmap Phase 4 | Yes | P2 |

### 3.3 Counts

| Stage | Atoms | P0 | P1 | P2 (incl. gated/stub) |
|---|---:|---:|---:|---:|
| normalize | 6 | 1 | 3 | 2 |
| qualify | 10 | 5 | 3 | 2 |
| derive | 7 | 0 | 5 | 2 |
| extract | 10 | 1 | 4 | 5 |
| assess | 3 | 1 | 1 | 1 |
| record | 4 | 2 | 2 | 0 |
| render | 2 | 0 | 1 | 1 |
| **Total** | **42** | **10** | **19** | **13** |

The P0 set forms the first end-to-end SMU data path:
normalize SMU -> classify status -> integrity -> completeness -> compliance -> trust ->
leakage current -> check limits -> fingerprint -> manifest.
It covers spot/staircase IV and gate-leakage screening with full audit.

---

## 4. Intentionally not added

| Candidate | Reason |
|---|---|
| `D_atom_decode_flex_ascii`, `D_atom_decode_flex_binary`, `D_atom_decode_easyexpert_block`, `D_atom_decode_easyexpert_export` | Byte/text decoding is A/C parser plumbing that depends on the session's parser contract. If offline re-decoding of persisted raw payloads is ever needed, it should be a hardware-free A-side parser atom that shares the kernel parser, not D. |
| Any D buffer/queue read, fetch, wait or status query | A/C I/O. D consumes their returned records as evidence. |
| WGFMU `exportAscii` setup-CSV parser | A-owned artifact. Columns are unresolved (Figure 4-1 OCR is garbled). |
| WGFMU memory-budget pre-flight calculator | Pre-measurement request validation (C schema/policy). D reuses the formula only for post-hoc completeness. |
| Standalone smoothing/filtering, outlier deletion, imputation | These would hide data problems. Smoothing exists only inside `derive_curve_derivative` with a declared window, never overwriting data. |
| Per-module duplicates (`hrsmu`/`mpsmu` qualify atoms) | Module type is a parameter. |
| Offline CMU open/short/load correction math | The instrument applies correction (`CORRST`, B). The EasyEXPERT template advises against reimplementing it without raw constants. |
| PUND, endurance trend, retention fit, NBTI/RTN, wake-up, FeFET memory-window-vs-cycles | Device experiment analyses with non-manual provenance. They belong to recipes/ABC, composed from generic derive/extract atoms. |
| Mobility (uFE, ueff) | Needs trusted Cox plus geometry metadata. Defer until CV is trusted and recipes declare geometry. |
| Emulating EasyEXPERT Auto Analysis / read-out functions (marker, cursor, line) | Use EasyEXPERT's reported values as `origin: reported` and compare via `assess_dataset_compare_reference`. D methods stay transparent. |
| Adaptive planning (next sweep range, stop conditions, retry) | Phase 4 / ABC decision layer. D returns verdicts only. |
| Safety/interlock/limit enforcement | B. `assess_dataset_check_envelope` is audit evidence only. |
| HSPICE netlist generation or fitting | Future, external, optional (`references/hspice/README.md`). |
| LLM narrative in reports | `analysis/AGENTS.md` restricts LLM output to narrative outside deterministic tools. |
| Standalone unit-conversion atom | Part of `normalize`. Arbitrary conversion invites silent unit errors. |

---

## 5. Forward hooks (not designed in full)

**D flows**: `D_flow_<operation>_<domain>_<subject>`. They call only D atoms, are
pure, and can run on replayed data.

- `ingest`: normalize -> fingerprint (for example `D_flow_ingest_smu_iv`,
  `D_flow_ingest_easyexpert_result`).
- `qualify`: classify -> integrity -> completeness -> domain checks -> summarize trust
  (for example `D_flow_qualify_iv_dataset`).
- `analyze`: derive plus extract bundles (for example `D_flow_analyze_iv_transfer` =
  derivative, Vth, gm_max, SS, on/off; `D_flow_analyze_iv_leakage` = leakage +
  check limits).
- `report`: plot -> manifest -> optional persist/report.
- `replay`: load -> verify fingerprint -> re-run qualify/analyze with the current
  algorithm version.

**CD flows**: `CD_flow_<intent>_<object>_<subject>`. Intent comes first, as in AB.
Phases are `measure` (C) -> `ingest` -> `qualify` -> `analyze` -> `record`.

- `acquire`: C flow plus ingest, qualify and record, producing a trusted dataset.
  Example: `CD_flow_acquire_smu_staircase`.
- `screen`: C flow plus extract and assess, producing a verdict. Example:
  `CD_flow_screen_smu_leakage`. This is the data half of the leakage validation that
  `AGENTS.md` requires before CV.
- `characterize`: C flow plus full parameter extraction. Example:
  `CD_flow_characterize_smu_transfer`.
- CMU variants are reserved and gated on `qualify_cv_check_correction_provenance`.
  WGFMU variants are reserved.

Rules the atom set already supports:

- D runs only after C reports `simulated_complete` or real completion. For
  `configuration_only`, `awaiting_completion` and `failed`, D steps are skipped with
  a reason.
- `analyze` runs only on `trusted` or `trusted_with_flags` data, unless the caller
  opts in and the results are tagged.
- A CD flow never retries or adapts the measurement based on a D verdict.
- External A/B preconditions are reported (C-flow style) and never called.
- On synthetic C output, `verdict_scope = synthetic`. A fake CD flow must never emit
  an instrument-scope `pass` for a DUT.

Prerequisite: the C read contract gaps in section 1.4 (raw ref, contract echo,
per-element status, WGFMU time array, and C flow `outputs` keeping these fields).

---

## 6. Contract notes

- **Envelope.** Built on the existing `_fake_response(atom, basis, **payload)`:
  `atom`, `fake`, `hardware_touched: false` (structurally always false for D, even when
  real), `basis` (manual pages, reference files, method names), `class: "D"`,
  `category` (stage), `target`, `ok`, `outcome`, `parameters` (input echo), `outputs`,
  `units`, `flags`, `warnings`, `assumptions`, `method {name, version, params}`,
  `provenance`, `required_inputs` (D's analog of C's `required_preconditions`; names
  the upstream A/C evidence needed), `side_effects {destructive: false,
  consumptive: false, artifact_written}`, `deterministic: true`.
- **`outcome`, not `status`.** `status` is overloaded with measurement status codes
  and with C-flow failure detection (`_failed` checks `status in {failed, error,
  ...}`). D uses:
  - `outcome: ok | not_extractable | indeterminate | rejected_input` for the atom result;
  - `status_code` / `status_class` for point status.

  `not_extractable` and `indeterminate` are valid analysis results, not failures.
  Contract violations return `ok: false, outcome: rejected_input, error {type,
  message}` instead of raising.
- **Fake markers and data origin.**
  - `data_origin` (`synthetic < fixture < replay < instrument`) propagates as the
    weakest input origin, so synthetic data taints every downstream result and
    manifest.
  - Empty synthetic arrays stay empty: completeness fails, trust is
    `untrusted`/`indeterminate`, and extraction is `not_extractable`. Nothing is
    fabricated.
  - `fake: true` in the first wave means "stub computation" (see Q1).
- **Units.**
  - Canonical SI plus a closed unit list: V, A, s, Hz, F, S, Ohm, H, rad, deg, "1".
  - Phase units follow the IMP mode explicitly (10/20 = rad, 11/21 = deg).
  - SS is reported in mV/dec together with V/dec.
  - Every scalar is a `Quantity` with `bound`.
  - There is no implicit conversion, and a unit mismatch rejects the input.
- **Status codes and compliance.**
  - Status codes are kept verbatim per point together with the table version.
  - Unknown codes go to `unknown` and are excluded by default; trust is then at most
    `trusted_with_flags`.
  - `C` (this channel) and `T` (other channel, so bias conditions are suspect) are
    excluded from fits by default but always plotted with markers.
  - Manual-defined invalid-data sentinels become null with `invalid_sentinel`.
    The exact sentinel values must be taken from PDF 48-54.
  - Search codes are meaningful only for MM14/15.
  - Missing status (high-speed `sample`, EasyEXPERT vectors) gives
    `status_unavailable`, and trust is at most `trusted_with_flags`.
- **Provenance and audit.**
  - Every output carries `provenance {data_origin, upstream [tool names and audit
    record refs], input_fingerprints, output_fingerprint, algorithm_version,
    schema_version, computed_utc}`.
  - Fingerprints exclude `computed_utc`.
  - The manifest references the station by name and hash only. No private station
    content is embedded unless the user supplies it.
- **Size.** Inline datasets are capped (aligned with C `Count` <= 100,000 elements).
  A `dataset_ref` handle is reserved for larger WGFMU-scale data (see Q2).
- **Purity.** No global state, no implicit reads of `config/` or
  `references/station/`, and no network. Only `record_persist` and the `render`
  stage may write, and only under an explicit data root in real mode.
- **Code placement (indicative).**
  - `mcp/d_atoms.py` plus `schemas/analysis.py` (new files).
  - Logic lives in `analysis/{quality,extraction,plotting,reporting}.py` plus a new
    provenance module.
  - The status table becomes a structured reference YAML once verified (section 1.4).

---

## 7. Open questions for the user

1. **Fake or real first wave?** D touches no hardware. Should the first wave be fake
   stubs (consistent with A/B/C, empty outputs), or real deterministic
   implementations validated on small anonymized fixtures (still `hardware_touched:
   false`, with `data_origin` marking the fixture)?
2. **Dataset passing and persistence.** Inline-only with a size cap, or a local
   content-addressed store with `dataset_ref` handles? Atom-by-atom MCP calls would
   otherwise shuttle whole datasets through agent context. Relatedly, may D write
   under `data/` in real mode?
3. **Lab conventions for extraction defaults.**
   - Vth method and constant-current criterion (absolute Icc or Icc*W/L).
   - SS current window.
   - Ion/Ioff bias points.

   Should these have defaults, or be mandatory inputs?
4. **Default status/compliance mask policy.** Exclude `T` (other-channel compliance)
   from fits by default? Which near-compliance ratio (proposed placeholder 0.95)?
5. **Verdict ownership and use.** Where do acceptance criteria live (device profile,
   recipe, or per call)? May future ABC flows consume D verdicts as gating evidence,
   for example leakage screening before CV, given that D itself never gates?
6. **Offline re-decode.** Is re-decoding persisted raw FLEX/EasyEXPERT payloads
   needed at all? If so, confirm it should be added as a hardware-free A-side parser
   atom rather than in D.
