# D Atom Candidates - Opus55b

Date: 2026-11-17

Status: independent candidate proposal only. Do not implement from this file
without cross review and an arbitration document.

Inputs read: `AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/roadmap.md`,
`.agents/skills/b1500-semiconductor-testing/` (SKILL, `instrument-interaction-tools.md`,
all `mcp-tools/*.md`), `.agents/skills/b1500-debug-workflow/SKILL.md`,
`tmp/atom_taxonomy_opus.md`, `tmp/c_atom_arbitration.md`,
`tmp/c_flow_design_arbitration.md`, `tmp/ab_flow_design_arbitration.md`,
`tmp/flow_taxonomy_proposal_{opus48,gpt55}.md`, the C cross reviews,
`src/b1500_test_agent/mcp/{common,fake_data,a_atoms,c_atoms,c_flows,ab_flows,server}.py`,
`src/b1500_test_agent/schemas/*`, `src/b1500_test_agent/analysis/*` (+ `AGENTS.md`),
`src/b1500_test_agent/instruments/b1500/{AGENTS.md,parser_ascii.py}`, and
`references/` (devices, recipes, station, policies, debug, hspice, physics,
instruments, `manuals/structured/*`).

---

## 1. Meaning of D

### 1.1 Settled meaning

**D = the deterministic post-acquisition analysis tool family.** (The user set
this mid-task. It also matches the evidence I found independently.)

A D atom takes data that A or C already acquired, plus explicitly declared
context. It turns that input into typed, unit-carrying, status-qualified,
provenance-linked analysis products: canonical traces, quality findings, masks,
derived parameters, manifests, and figure, table or report artifacts. D atoms
are the MCP face of `src/b1500_test_agent/analysis/` (today only
`extract_threshold_voltage`, `plot_measurement`, `summarize_quality` and
`write_report` placeholders) and of a pure payload decoder that `parser_ascii.py`
already promises (`parse_fmt1` TODO).

Repo evidence that this is the open slot:

- `docs/architecture.md` layer 5: "Analysis: deterministic extraction,
  plotting, quality scoring, and report generation." It is the only
  architecture layer with no MCP family.
- `docs/roadmap.md` Phase 2: "Data persistence for raw traces, parsed traces,
  and metadata", "Basic IV plotting and parameter extraction", and "Quality
  checks based on status codes and compliance hits".
- `AGENTS.md`: audits must record "raw data, parsed data, and assumptions".
  The analysis `AGENTS.md` also asks to separate raw, derived, assumptions
  and recommendations, inspect status codes, and exclude or flag compliance,
  overvoltage, oscillation and invalid points before fitting.
- `c-flows.md`: "A read limit is not a completeness check; the future
  acquisition layer must verify expected point counts and status codes before
  accepting data", and "Empty arrays remain empty and do not certify data
  quality."
- `ab_flow_design_arbitration.md` rejects "Result classification / device
  analysis" as "Future analysis/C/ABC, not AB".
- SKILL workflow steps 7-8 ask the agent to interpret status codes and data
  quality before extraction, then report measured, derived, assumptions and
  warnings separately. The debug skill's step 3 covers measurement data:
  status codes, noise, discontinuities, drift, leakage and compliance hits.
- README names the first SMU target as "connection, preflight, spot IV,
  staircase IV, and **gate leakage checks**". The leakage verdict is an
  analysis product.

### 1.2 Alternatives considered (record only)

| Interpretation | Why not chosen |
|---|---|
| D = Device/DUT (profiles, pin maps, device experiments) | Device experiments (Id-Vg, FeFET, PUND, endurance) are assigned to recipes and ABC. Pin-map and limit validation belongs to B preflight and policy. |
| D = Diagnostics/Debug | B already has a `diagnostic` category, and debug triage is skill-level. The data-side debug checks fall inside the D `qualify` stage below. |
| D = Decision/closed loop (Phase 4 adaptive envelopes) | Actuation must stay behind ABC and human approval. D may only emit advisory text. |
| D = Peripheral hardware (prober/chuck/thermal) | That would be a new transport, so a new A/B interface, not a no-hardware class. |
| D = Extraction only, or Persistence only | Each is a subset. Extraction without decode and qualify violates the analysis rules. Persistence without decode cannot record "parsed data". |

### 1.3 Class invariants after adding D

| Class | Touches | Changes instrument/DUT state | Typical side effect |
|---|---|---|---|
| A | Interface session (FLEX / WGFMU lib / EasyEXPERT remote) | No DUT output change; software context only | Opens/closes sessions, consumes queues and buffers |
| B | Instrument safety/state | Yes (zero, reset, route, correct) | State change |
| C | Measurement surface | Yes (source, execute, read measurement data) | Biases DUT, drains measurement buffer |
| **D** | **Nothing on the bench: in-memory payloads and local files only** | **Never** | Pure computation; the `archive`/`render` stages write under the configured data root |

### 1.4 Boundary against A and C (core of this proposal)

Raw buffer reads, result fetch, counts, completion checks and session framing
stay in A/C. D starts only after the bytes or arrays are already in memory,
or on disk as an archived artifact. Seven rules make the line testable:

1. **Session rule.** If an operation needs a VISA/GPIB session, a WGFMU
   library session, an EasyEXPERT remote connection, a channel handle, or
   issues any command, query or API call, it is A or C. It is never D. D atom
   signatures contain no address, session, timeout or channel-handle
   parameters.
2. **Acquisition rule.** A/C own every read that moves data off the
   instrument: `NUB?` / `BC` / output-buffer reads, measurement-specific SMU
   and CMU buffer reads, WGFMU `getMeasureValue(s)` / `getForceValue(s)`,
   EasyEXPERT `:RESult:FETch?`, and WGFMU `exportAscii`. D never re-reads,
   retries, polls or waits.
3. **Framing rule.** A owns transport framing and format selection: `FMT`,
   `TSC`/`TSR`, `:RESult:FORMat`, terminators, item counting, and stripping
   the SCPI definite-length block header (`A_atom_easyexpert_fetch_result`
   already carries this note). D receives the payload with framing removed,
   plus a *declared* decode context. If A captured the byte count, D records
   it as an integrity check only.
4. **Decode-semantics rule.** D owns the canonical *content* decoder. It
   turns tokens into status class, channel, data type, value and unit, and
   applies IMP-model column semantics, overflow sentinels and the status-code
   dictionary.
   - C read atoms keep ownership of *what and when* to read in a measurement
     context (MM, channels, `max_items`). They may still return convenience
     `rows`, but only by calling the same pure decoder library, and they
     must also return the raw payload.
   - One parser implementation, two entry points. The C read atom takes a
     live session and is never called on archived data. The D decode atom
     takes a payload and is never called on a live session.
   - Reason not to leave decode only inside C: the A generic buffer read and
     the EasyEXPERT fetch return raw content with no C context, and the
     audit rule requires re-decoding archived raw data offline.
5. **Evidence rule.** D consumes A/B/C result envelopes (and flow envelopes)
   as evidence. The caller passes them explicitly. D never calls A/B/C to
   fill a gap. Missing evidence produces `evidence_missing` findings and caps
   the verdict (see §6).
6. **No-action rule.** D never changes instrument state, never gates or
   approves a B action, and never returns callable C parameters as an
   instruction. Recommendations are advisory text in `recommendations[]`.
   Any actuation belongs to recipes/ABC with stop conditions and approval.
7. **Inline-sample rule.** Structured samples that C returns inline
   (`C_atom_smu_measure_high_speed_spot.sample`, WGFMU DC `measurement`) are
   adopted as already-decoded C output (`payload_kind: c_inline_sample`).
   D does not reinterpret them as raw.

Concrete placement of the operations that sit closest to the line:

| Operation | Owner | Existing tool | D relation |
|---|---|---|---|
| Select `FMT`, timestamp on/off, reset timestamp | A | `A_atom_flex_set_data_format`, `A_atom_flex_configure_timestamp`, `A_atom_flex_reset_timestamp` | Consumes declared or verified FMT and the TSR anchor as `DecodeContext` (`fmt_source: declared\|verified`). |
| Buffer count / clear | A | `A_atom_flex_query_buffer_count`, `A_atom_flex_clear_output_buffer` | Uses before/after counts as completeness evidence. |
| Generic output-buffer read | A | `A_atom_flex_read_output_buffer` (`items`) | Decodes captured `items` offline. |
| Measurement-specific SMU/CMU read | C | `C_atom_smu_read_measurement_data`, `C_atom_cmu_read_measurement_data` | Decodes the raw payload. The C atom may embed the D decoder library for convenience rows only. |
| WGFMU measured/force arrays | C | `C_atom_wgfmu_read_measurement_values(_partial)`, `C_atom_wgfmu_read_force_values` | Assembles time series. |
| WGFMU event info, measure times, interpolated force | A | `A_atom_wgfmu_get_measure_event_info`, `..._get_measure_times`, `..._get_interpolated_force_value` | Consumes as segmentation and time-alignment evidence. |
| WGFMU run status / event completion | A | `A_atom_wgfmu_get_status`, `..._get_channel_status`, `..._is_event_completed`, `..._get_measure_value_size` | Maps the captured status to data readability. `RUNNING_ILLEGAL`/`IDLE` mean unreadable. `ABORT_COMPLETED` means partial. |
| WGFMU `exportAscii` | A | `A_atom_wgfmu_export_ascii` | No D parser: this is setup data, and the CSV columns are unresolved (Fig. 4-1 OCR garbled). |
| EasyEXPERT result format, fetch, block-header strip | A | `A_atom_easyexpert_set_result_format`, `A_atom_easyexpert_fetch_result` | Parses TEXT/XTR content. |
| EasyEXPERT export files already on disk (CSV/tab/XSLT) | D | none | Offline file ingest only; no remote call. |
| Error queue reads, `EMG?` message lookup | A | `A_atom_flex_read_error_queue`, `A_atom_flex_lookup_error`, WGFMU/EasyEXPERT error reads | Maps already-captured codes to *data-validity impact* (260, -15, 1000, 3050, 3051). No message lookup. |
| Status byte, compliance readback | A | `A_atom_flex_read_status_byte`, `A_atom_flex_query_compliance_status` | Cross-checks per-point `C`/`T` statuses against `LIM?`/`LOP?` evidence. |
| CMU correction readbacks / actions | A / B | `A_atom_flex_query_cmu_correction_*`, `B_atom_correction_cmu_*` | Checks whether the recorded correction covers the measured frequencies, for data trust only. Never decides whether to correct. |
| Execute / run | C | `C_atom_*_execute*`, `C_atom_easyexpert_run_*` | Never. |
| C flow synthetic outputs | C | `C_flow_*` `outputs.data` | Adopts them with sticky `synthetic: true` taint. |
| Pin map, device profile, station profile | references/config (outer layer loads) | none | Explicit typed inputs only. D never reads private station files implicitly. |

### 1.5 What D atoms must never do

- Touch hardware, sessions or remote software. `hardware_touched` is
  invariantly `false`. D never calls any A/B/C atom or flow.
- Execute, poll, wait, retry, or drain any instrument queue or buffer.
- Mutate or overwrite raw data. Masks and derived columns are new objects
  with lineage. Raw tokens are preserved byte-exact with SHA-256.
- Silently drop, clip, smooth or interpolate measured points.
- Guess missing context: FMT mode, IMP model, channel/terminal map, units,
  sweep geometry, device geometry, method criteria. Missing context returns
  `context_missing`.
- Present synthetic or fake-derived numbers as measurement results, or issue
  an `accept` verdict on synthetic inputs.
- Claim instrument safety, approve a recipe or measurement, or satisfy a B
  preflight.
- Evaluate arbitrary user expressions or code. This is the data-plane twin
  of "no raw FLEX".
- Use an LLM for numbers. Narrative stays outside the tool.
- Write outside the configured data root, overwrite existing artifacts, or
  embed private station content (store the profile name plus a hash).

---

## 2. Naming Pattern

```text
D_atom_<stage>_<subject>_<action>
```

This has the same three-slot shape as `B_atom_<risk_category>_<target>_<action>`.
The first token is the axis that matters most for safe use: the **pipeline
stage**, which fixes what the atom may and may not produce or write. The
response also carries the same values as structured fields (`stage`,
`subject`), so tooling never parses names.

**Stage** (closed, ordered):

| Stage | Meaning | Side effect |
|---|---|---|
| `decode` | Captured payload into a canonical, status-annotated trace. | None (pure). |
| `qualify` | Expectations, checks and verdicts. Never alters values. | None (pure). |
| `shape` | Terminal mapping, setpoints, masks, segments, normalization. Always produces new views with lineage. | None (pure). |
| `derive` | Derived traces and extracted parameters with an explicit method. | None (pure). |
| `archive` | Manifest, write-once bundle, load, integrity verification. Authoritative and immutable. | Local FS write (`write_bundle` only). |
| `render` | Tables, figures, reports. Regenerable views. | Local FS write. |

**Subject** (closed, 8 tokens in three groups):

- Payload sources (decode only): `flex`, `wgfmu`, `easyexpert`. These are
  deliberately the same tokens as the A interfaces: D decodes what came
  through interface X. There are no per-module decode subjects; SMU and CMU
  semantics enter through `DecodeContext`.
- Canonical data objects: `trace` (one acquisition's typed table) and `run`
  (traces, evidence and provenance for one acquisition context).
- Analysis domains: `iv` (SMU DC/pulsed IV), `cv` (MFCMU and QSCV
  capacitance), `timeseries` (SMU sampling, C-t, WGFMU events). SPGU is
  source-only, so it has no D subject.

**Allowed stage × subject matrix** (prevents cross-product growth):

| Stage | Allowed subjects |
|---|---|
| decode | flex, wgfmu, easyexpert |
| qualify | run, trace, iv, cv (timeseries reserved) |
| shape | trace |
| derive | iv, cv, timeseries |
| archive | run |
| render | trace, run |

**Action verbs** (closed): `parse`, `assemble`, `build`, `check`, `grade`,
`map`, `align`, `apply`, `split`, `normalize`, `compute`, `extract`, `fit`,
`compare`, `convert`, `summarize`, `write`, `load`, `verify`, `export`, `plot`.
A new verb needs arbitration, like a new B category.

Rules:

- No device names in atom names (no `mosfet`, `fefet`). Device conventions
  arrive as typed inputs from device profiles or recipes.
- No measurement-family names in atom names (`sweep`, `pulse`). Geometry
  arrives through `DataExpectation`. This keeps D orthogonal to the C flow
  families.

---

## 3. Candidate D Atom Catalog

36 candidates: decode 5, qualify 10, shape 5, derive 9, archive 4, render 3.

Priorities:

- **P0 (13):** the minimum that makes one SMU spot/staircase IV acquisition
  decodable, trustworthy-or-rejected, mapped, masked and auditable,
  including the README's gate-leakage check.
- **P1 (15):** IV extraction, plotting/export, re-processing, and the WGFMU
  decode schema.
- **P2 (8):** binary formats, CMU/CV, time-series and report generation.

`stub` marks items whose module stays a stub per `AGENTS.md`: schema only,
real computation blocked until validation. "Det." means deterministic given
inputs and method version. `Yes*` means deterministic content but with an
FS side effect, or a wall-clock value that the caller can inject.

### 3.1 Shared typed models (future `schemas/d_atom.py`, Pydantic, `extra="forbid"`)

| Model | Key fields |
|---|---|
| `RawPayload` | `interface` (flex\|wgfmu\|easyexpert), `payload_kind` (ascii\|binary_b64\|arrays\|c_inline_sample\|export_file), `content` or `artifact_ref`, `sha256`, `byte_count`, `captured_by` (A/C atom name), `captured_at`, `synthetic` |
| `DecodeContext` | `fmt_mode` (Literal of documented modes), `fmt_source` (declared\|verified), `source_data_output`, `timestamp_enabled`, `tsr_anchor`, `mm_mode`, `channels`, `imp_model`, `measure_mode` per WGFMU channel, `rdata` (AVERAGED\|RAW) |
| `CanonicalTrace` | `trace_id` (content hash), `columns[]` {name, quantity, unit, channel, terminal?, role: measured\|source\|setpoint\|time\|derived}, column arrays, `status[]` {raw, cls}, `segments[]`, `lineage`, `synthetic` |
| `DataExpectation` | expected columns/units, expected point count per channel/segment, setpoint vector, timestamp availability, data-volume estimate, `basis` |
| `Finding` / `QualityReport` | `check`, `check_outcome` (pass\|fail\|inconclusive\|not_applicable), `severity`, `counts`, `indices`, `evidence_refs`, `basis` |
| `Mask` | `mask_id`, `trace_id`, excluded indices with reason per index, `policy` |
| `DerivedQuantity` | `name`, `value`/array, `unit`, `method` {name, version, params}, `window`, fit statistics, `derived_from_flagged_points`, `inputs` (trace_id, mask_id) |
| `Verdict` | `verdict` (accept\|accept_with_flags\|needs_review\|reject\|synthetic_only), `blocking`, `reasons`, `evidence_missing`, `usable_for[]` |
| `RunManifest` | run_id, timestamps, request, tool chain, module inventory snapshot ref, station profile name+hash, raw hashes, decoder/method versions, assumptions, approvals ref |

### 3.2 `decode` (5)

| Atom | Purpose | Inputs → Outputs (sketch) | Source basis | Det. | Pri. |
|---|---|---|---|---|---|
| `D_atom_decode_flex_parse_ascii` | Decode a captured FLEX ASCII output-buffer payload into a canonical trace. Preserves the raw status char, channel code, data type and raw token. Overflow sentinels become null + `overflow`. CMU columns are resolved by IMP model. | `RawPayload`, `DecodeContext` → `CanonicalTrace`, `unparsed_tokens[]`, `framing_findings` | PG ASCII format PDF 44-54 (status 48-52, channel 53, type 54); `FMT` PDF 435-436; IMP Table 4-16 PDF 346; timestamp caveats PDF 537-538; `parser_ascii.py` TODO | Yes | P0 |
| `D_atom_decode_flex_parse_binary` | Decode FMT 3/4 (4-byte) and 8-byte binary payloads, including range bytes (enables `check_resolution` on auto-ranged data). | `RawPayload`(binary_b64), `DecodeContext` → `CanonicalTrace` + per-point range | PG binary PDF 55-74, range table PDF 69-70, parse example PDF 310-315 | Yes | P2 (driver AGENTS: ASCII first) |
| `D_atom_decode_wgfmu_assemble_series` | Assemble WGFMU (time, value) arrays per channel into a time-series trace. Segments by measurement event (cycle/loop/count/index/length). Applies the averaged-timestamp midpoint convention. | arrays + event table + measure mode + `rdata` + captured WGFMU status → `CanonicalTrace`(timeseries) | WGFMU API `getMeasureValue(s)` PDF 116-118; `getMeasureEvent*` PDF 109-113; `setMeasureEvent` PDF 130-131; RAW count PDF 151 | Yes | P1 stub (WGFMU) |
| `D_atom_decode_easyexpert_parse_result` | Parse a framing-stripped `:RESult:FETch?` payload (TEXT or XTR). Keeps Device ID, Count, setup and test names as metadata. | `RawPayload`, `result_format` → `CanonicalTrace[]`, `metadata` | EasyEXPERT PDF 436-438; `easyexpert-export-formats.yaml` (remote TEXT/XTR) | Yes | P1 |
| `D_atom_decode_easyexpert_parse_export` | Parse EasyEXPERT export files already on disk: CSV/tab text export, and XSLT groups 3/4/5 dispatched by first-column component label. | `artifact_ref`, `export_kind`, orientation, delimiter → `CanonicalTrace[]`, `metadata`, `setup` | EasyEXPERT PDF 164-168, 497-506 | Yes | P2 |

### 3.3 `qualify` (10)

| Atom | Purpose | Inputs → Outputs (sketch) | Source basis | Det. | Pri. |
|---|---|---|---|---|---|
| `D_atom_qualify_run_build_expectation` | Before or after a run, compute the data contract a C request should produce: columns, units, point counts, setpoints, timestamp availability, and data volume (WGFMU RAW/AVERAGED vs ~4M/channel typical). Advisory only, never a block. | typed C request (`schemas/c_flow.py` models) + `DecodeContext` → `DataExpectation`, advisory findings | MM map + required-before-XE PDF 90-132, 570-571; TSC exclusions (FMT3/4, HS spot, MM9/14/15) PDF 537; WGFMU budget formulas PDF 130-131, 151 | Yes | P0 |
| `D_atom_qualify_trace_check_status` | Classify per-point instrument status with a versioned code table: normal, compliance_self, compliance_other, overflow, oscillation, search_*, cmu_*, source_step_marker, unknown. Unknown is never normal. | `CanonicalTrace`, `status_table_version` → `QualityReport` (counts and indices by class) | PG PDF 48-52; analysis `AGENTS.md` "inspect status codes" | Yes | P0 |
| `D_atom_qualify_trace_check_completeness` | Compare received data against the `DataExpectation`. Checks point count per channel/segment, `max_items` truncation, NaN/sentinel runs, duplicate or non-monotonic index/time, and timestamp wrap. | `CanonicalTrace`, `DataExpectation`, buffer-count evidence → `QualityReport` (expected vs received, missing ranges) | `c-flows.md` "read limit is not a completeness check"; `NUB?` semantics PDF 44, 477; TSR wrap guidance PDF 538 | Yes | P0 |
| `D_atom_qualify_trace_check_limits` | Value-based checks: compliance proximity (the only compliance signal when FMT has no header), range full-scale proximity, and excursions beyond declared device/station envelopes. Excursions are reported as `needs_review`, never as approval. | trace, compliance {value, unit, polarity}, range settings, declared envelopes, margin params → `QualityReport` | `LIM`/`LOP?` semantics; `devices/*.example.yaml` safe_limits; `_SYSTEM_LIMITS`; AGENTS large current/high voltage approval | Yes | P0 |
| `D_atom_qualify_trace_check_resolution` | Flag points at or below the effective measurement floor for module/range/integration (HRSMU 10 pA, 1 pA with ASU; MPSMU 1 nA). Reports `range_unknown` when ASCII data is auto-ranged. | trace, module type, range info (per point or declared), integration → `QualityReport` (below-floor indices, effective floor) | PG Table 4-3 PDF 336-337; `_SMU_RANGE_HINTS`; WGFMU noise table PDF 25 | Yes | P1 |
| `D_atom_qualify_trace_check_continuity` | Detect discontinuities, spikes and range-change steps for debug triage. Report-only, no auto-mask. | trace, thresholds (declared) → `QualityReport` | debug skill triage step 3; `references/debug/README.md` | Yes | P2 |
| `D_atom_qualify_iv_check_leakage` | Gate/terminal leakage screen: max \|I\| over a declared bias window per polarity vs a declared threshold. Below-floor results are `pass_at_floor`, not a measured value. Output is evidence for `leakage_check_passed`. | mapped trace, terminal, bias window, threshold (A or A/area), resolution report → `QualityReport` + leakage summary | README "gate leakage checks"; `recipes/mosfet/cgd_cv` preconditions; AGENTS (CV waits for leakage validation); `mosfet.example.yaml` quality_checks | Yes | P0 |
| `D_atom_qualify_cv_check_correction` | Data-trust check for capacitance: whether recorded correction (A readback evidence and compensation record) is enabled, covers every measured frequency, and is within a declared age. Never triggers correction. | CV trace, `CORRST?`/`CORRL?` evidence, compensation record, max age → `QualityReport` | `approval-policy` capacitance_without_correction; `station/compensation/latest.example.yaml`; A `query_cmu_correction_*` | Yes | P2 stub (CMU) |
| `D_atom_qualify_run_check_context` | Turn captured run evidence into data-validity findings. See the evidence list after this table. | C/A/B envelopes, WGFMU status, error lists → findings[] | README buffer note; `b1500a-error-codes.yaml` 260; `b1530a-wgfmu-error-codes.yaml` -15/1000/3050/3051 and status codes | Yes | P0 |
| `D_atom_qualify_run_grade_verdict` | Deterministically reduce reports and findings to one `Verdict` under a declared policy. Synthetic input forces `synthetic_only`. Missing evidence caps the verdict at `needs_review`. | reports[], findings[], `VerdictPolicy` → `Verdict` | analysis `AGENTS.md`; AGENTS audit rules | Yes | P0 |

Evidence that `D_atom_qualify_run_check_context` turns into findings:

- C `execution_state` and `contract_gaps`.
- Errors captured during the run: 260 buffer full, WGFMU -15 result out of
  date, 1000, 3050, 3051.
- Status byte, and WGFMU `ABORT_COMPLETED` / `RUNNING_ILLEGAL` / `IDLE`.
- `format_declared_not_verified`.
- Upstream `synthetic`.
- `LIM?` vs per-point `C` mismatch.

### 3.4 `shape` (5)

| Atom | Purpose | Inputs → Outputs (sketch) | Source basis | Det. | Pri. |
|---|---|---|---|---|---|
| `D_atom_shape_trace_map_terminals` | Relabel channel columns to DUT terminal quantities (`V_gate`, `I_drain`) with a declared sign convention. Incomplete pin maps raise `pin_map_incomplete`, which blocks `derive`. | trace, pin map (station pin-map schema), sign convention → trace view + unmapped findings | `station/pin-maps/*.example.yaml`; AGENTS (incomplete pin map needs approval) | Yes | P0 |
| `D_atom_shape_trace_align_setpoints` | Attach programmed setpoints (linear/log, VAR2 list) from the `DataExpectation`. If source data was output, compare reported vs programmed within tolerance. | trace, `DataExpectation`, tolerance → trace view + mismatch findings | `WV/WI` sweep geometry; FMT source-data option PDF 435-436 | Yes | P0 |
| `D_atom_shape_trace_apply_mask` | Build an exclusion mask from reports and a declared policy (status classes, explicit ranges with reasons). Raw data is untouched; masked view plus `Mask`. | trace, reports[], `MaskPolicy` → `Mask`, masked view | analysis `AGENTS.md` "exclude or flag ... before fitting" | Yes | P0 |
| `D_atom_shape_trace_split_segments` | Split forward/reverse sweeps, VAR2 families, repeats and WGFMU events into identified segments. | trace, rule (direction change\|var2\|repeat\|event table) → segmented view | WGFMU event fields PDF 109-113; sweep geometry | Yes | P1 |
| `D_atom_shape_trace_normalize_geometry` | Add width- or area-normalized derived columns (A/m, A/m², F/m²). Geometry must be declared. | trace, geometry {W, L, area, units} → trace view with derived columns | analysis rules (units in results) | Yes | P1 |

### 3.5 `derive` (9)

Methods are standard device-analysis conventions, not manual content. The
WGFMU structured reference explicitly notes the manual gives no Vth
algorithm. Every derive output carries `method {name, version, params}`, a
window, fit statistics and `derived_from_flagged_points`. All derive atoms
refuse to run if `pin_map_incomplete`, the verdict is `reject`, or a
required criterion is undeclared.

| Atom | Purpose | Inputs → Outputs (sketch) | Source basis | Det. | Pri. |
|---|---|---|---|---|---|
| `D_atom_derive_iv_compute_derivative` | Derivative trace (gm, gds, d log\|I\|/dV) with a declared numeric method and window. Refuses non-monotonic x unless segmented. | masked trace, y/x, method → derived trace | analysis rules (method reporting) | Yes | P1 |
| `D_atom_derive_iv_extract_vth` | Vth by `max_gm_linear_extrapolation` or `constant_current` (criterion is mandatory and may be W/L-scaled). Polarity n/p is explicit. | masked transfer segment, method, criterion, polarity, Vds → `DerivedQuantity` (V) + gm_max point and fit window | `devices/mosfet.example.yaml` vth_methods; `analysis/extraction.py` placeholder | Yes | P1 (first P1) |
| `D_atom_derive_iv_extract_ss` | Subthreshold swing (V/decade) over an auto-selected (declared rule) or explicit current window, with minimum decades. | masked transfer segment, window rule → `DerivedQuantity` + window, R² | analysis `AGENTS.md` (SS) | Yes | P1 |
| `D_atom_derive_iv_extract_on_off` | Ion, Ioff and ratio at declared bias points. Ioff at floor yields `ratio_lower_bound`. | masked trace, bias points, resolution report → `DerivedQuantity[]` | device profiles; resolution check | Yes | P1 |
| `D_atom_derive_iv_fit_linear` | Linear fit (optionally through origin) giving slope, intercept, R², residuals, and resistance or conductance. Used for resistors, ohmic leakage and contact checks. | masked trace, x/y, window → `DerivedQuantity[]` | basic electrical laws (`references/physics/README.md`) | Yes | P1 |
| `D_atom_derive_iv_compare_shift` | Signed voltage shift between two segments or traces at a declared current criterion or per-trace Vth. Recipes use it for hysteresis, memory window or BTI shift. D does not interpret the physics. | reference/test segments, criterion → `DerivedQuantity` (V) | `mosfet.example.yaml` hysteresis; `fefet` recipe analysis (memory window, vth_shift) | Yes | P1 |
| `D_atom_derive_cv_convert_model` | Convert impedance representations (Cp-G, Cp-D, Cs-Rs, Z-θ, Y-θ with rad/deg) using the measured frequency. | CV trace with IMP model, frequency → converted trace | IMP Table 4-16 PDF 346 | Yes | P2 stub (CMU) |
| `D_atom_derive_cv_extract_cox_vfb` | Cox and Vfb with declared method, area and dielectric inputs. Blocked unless `check_correction` and the leakage screen pass. | qualified CV trace, area, method → `DerivedQuantity[]` | analysis `AGENTS.md` (Cox, Vfb); AGENTS CV gating | Yes | P2 stub (CMU) |
| `D_atom_derive_timeseries_summarize_windows` | Per-window or per-event mean, std, min/max and slope (drift) for SMU sampling, C-t and WGFMU events. | time-series trace, windows or event segments → per-window stats | WGFMU event model PDF 130-131; sampling MM10 | Yes | P2 stub (WGFMU/sampling) |

### 3.6 `archive` (4)

| Atom | Purpose | Inputs → Outputs (sketch) | Source basis | Det. | Pri. |
|---|---|---|---|---|---|
| `D_atom_archive_run_build_manifest` | Assemble the audit manifest. See the content list after this table. | refs + envelopes + injectable `created_at` → `RunManifest`, manifest hash | AGENTS audit rule; `data/README.md` | Yes* | P0 |
| `D_atom_archive_run_write_bundle` | Write-once bundle to `data/raw/<run_id>/` (raw payloads byte-exact) and `data/processed/<run_id>/` (canonical traces, reports, verdict, derived, manifest). Content-addressed, no overwrite, refuses paths outside the data root. Synthetic runs are segregated or refused (see Q3). Fake mode returns `planned_paths`, `written: false`. | manifest, artifacts, data root → written files + SHA-256 | roadmap Phase 2 persistence; `data/README.md`; `.gitignore` | Yes* | P0 |
| `D_atom_archive_run_load_bundle` | Read-only load of a bundle by `run_id`, with hash verification of every artifact. | run_id or manifest ref → manifest + artifact refs + hash status | reproducibility | Yes | P1 |
| `D_atom_archive_run_verify_integrity` | Re-hash raw data, re-decode it with the recorded decoder version, and diff against the stored canonical trace (reproducibility proof). | loaded bundle → `reproducible`, diffs | AGENTS audit; analysis plotting rule "reproducible" | Yes | P1 |

`D_atom_archive_run_build_manifest` records:

- Run id and request.
- Tool chain (`atoms_called` / `flows_called`).
- Module inventory snapshot ref (from `A_atom_flex_list_modules`).
- Station profile name plus hash.
- FMT/timestamp context and source.
- Raw payload hashes.
- Decoder, status-table and method versions.
- Findings, verdict, assumptions and approval refs.

### 3.7 `render` (3)

| Atom | Purpose | Inputs → Outputs (sketch) | Source basis | Det. | Pri. |
|---|---|---|---|---|---|
| `D_atom_render_trace_export_table` | Export a trace (optionally with mask and derived columns) to CSV/JSON with a unit header and a metadata sidecar. | trace(s), format → file refs + sidecar | `data/processed`, `scripts/README.md` "Dataset export" | Yes | P1 |
| `D_atom_render_trace_plot_figure` | Raw-first figure with \|I\| semilog for multi-decade data and masked points marked. Writes a metadata sidecar (data hashes, library versions). Fake mode returns a plot spec only. | trace(s), plot spec → figure ref + sidecar | analysis plotting rules; EasyEXPERT Display Setup mapping | Yes (library-pinned) | P1 |
| `D_atom_render_run_write_report` | Template Markdown report with separate sections for raw data, derived values, assumptions, warnings and advisory recommendations. Narrative stays with the agent. | manifest, verdict, reports, derived → Markdown ref | analysis `AGENTS.md`; SKILL step 8; `analysis/reporting.py` placeholder | Yes | P2 |

---

## 4. Intentionally Not Added

| Candidate | Reason |
|---|---|
| Any D read/fetch/count/wait atom (buffer read, `:RESult:FETch?`, `getMeasureValues`, `NUB?`, OPC) | A/C own acquisition (§1.4 rules 1-2). |
| SCPI block-header stripping / terminator handling in D | A transport framing (rule 3). D only records the A-captured byte count as an integrity check. |
| `D_atom_decode_wgfmu_parse_setup_export` (`exportAscii` CSV) | `exportAscii` is A and produces setup, not measurement data. Its columns are unresolved (Fig. 4-1 OCR garbled). Revisit after image extraction. |
| D error-message lookup tool | Duplicates `A_atom_flex_lookup_error` and the structured tables. D only maps captured codes to data-validity impact inside `check_context`. |
| Status-code, channel-code and data-type dictionary as tools | Expose as a versioned MCP resource (e.g. `b1500://data-codes`) next to the existing `b1500://capabilities` / `b1500://safety-policy`, not as a tool. |
| Per-module decode atoms (`decode_smu`, `decode_cmu`) | Decode follows transport format. Module semantics are `DecodeContext` (IMP model, data-type codes). Avoids duplicating C's object axis. |
| Device-experiment atoms (memory window, PUND, endurance, retention, BTI recovery, Id-Vg experiment) | Recipes/ABC per `c_flow_design_arbitration.md`. D supplies generic primitives (`extract_vth`, `compare_shift`, `summarize_windows`). |
| Ferroelectric charge integration / P-E loops, mobility, Rsd/TLM, doping profile, Dit, HSPICE fit | Device-physics heavy and need validated WGFMU/CV paths plus geometry. HSPICE stays optional and external (`references/hspice/README.md`). Defer to a later D wave. |
| Generic "evaluate expression / fit arbitrary model / run script" | Data-plane equivalent of raw FLEX. Not allowed by default. |
| Smoothing/filter/resample atoms that replace values | Alters measured data. Derivative methods declare their own windows; any future filter must be a derived trace. |
| LLM interpretation atom | Analysis `AGENTS.md`: deterministic numbers, LLM narrative only. |
| "Suggest next measurement parameters" atom returning C inputs | Phase 4 closed loop needs ABC stop conditions and approval. D emits advisory text only. |
| Delete/overwrite/edit archived data | Violates immutability and audit. |
| EasyEXPERT Data Display / read-out-function automation | Workflow templates recommend exporting data instead of driving GUI analysis. |
| SPGU D atoms | SPGU is source-only. Its readbacks are A and it produces no measurement data. |
| LIMS/database upload | Out of scope. Archive is local. |

---

## 5. Forward Hooks (not designed in full)

### 5.1 D flows

D flows call only D atoms, serially, keeping the same-class rule of A/B/C
flows. They can run on archived data with no instrument at all. Suggested
shape: `D_flow_<operation>_<domain>_<subject>`, with operation in
{ingest, qualify, screen, extract, archive, reprocess, report}.

- `D_flow_ingest_flex_trace`: `decode_flex_parse_ascii` → `shape_trace_map_terminals` → `shape_trace_align_setpoints`
- `D_flow_qualify_iv_trace`: `check_status` → `check_completeness` → `check_limits` → (`check_resolution`) → `run_check_context` → `run_grade_verdict` → `shape_trace_apply_mask`
- `D_flow_screen_iv_leakage`: status/limits/resolution → `qualify_iv_check_leakage` → `run_grade_verdict`
- `D_flow_extract_iv_transfer`: requires a verdict of `accept` or `accept_with_flags`, then derivative → vth → ss → on_off
- `D_flow_archive_run_bundle`: `build_manifest` → `write_bundle` → `load_bundle` → `verify_integrity`
- `D_flow_reprocess_run_bundle`: load → verify → decode → qualify → diff against stored

### 5.2 CD flows

A CD flow composes exactly one existing `C_flow_*` with D flows and narrow D
atoms. It uses four phases, `expect (D) → measure (C) → interpret (D) → record (D)`,
mirroring AB's observe/act/verify bracket. Its envelope adds
`flow_class: "CD"`, `phases`, `flows_called`, `child_results`, the C
`execution_state`, and a `data_state` of
no_data|synthetic|decoded|qualified|rejected|extracted|archived.

Examples:

- `CD_flow_sweep_smu_staircase` (qualified IV)
- `CD_flow_sweep_smu_leakage` (gate leakage screen; feeds CV gating)
- `CD_flow_sweep_smu_transfer` (Vth/SS/on-off)

For naming, the first token should be the wrapped C family, so every CD flow
anchors to one C flow. The flow round can still choose intent-first.

Rules the atom set already supports:

- If the C state is `configuration_only`, `awaiting_completion` or `failed`,
  the interpret phase is skipped and recorded as `data_state: no_data`.
  D never grades empty data.
- CD calls no A/B. Its `check_context` therefore reports `evidence_missing`
  (error queue, FMT verification, inventory), and the verdict is capped at
  `needs_review`. Full trust needs the future ABC transaction that supplies
  A evidence.
- EasyEXPERT data (fetch is A) and WGFMU event metadata (A) cannot be
  completed in pure CD. They are reserved for the outer transaction.
- CMU CD flows run with the result always capped at `needs_review` until
  `check_correction` and the leakage screen have real inputs.

### 5.3 Contract gaps in existing atoms that CD will surface

Report these as `contract_gaps`, as C flows do:

1. `C_atom_smu_read_measurement_data` and `C_atom_cmu_read_measurement_data`
   return `rows` only. They lack `raw_payload`, `raw_sha256` and the decode
   context (`fmt_mode`, `mm_mode`, channels, `imp_model`). Without these the
   AGENTS "raw data" audit rule cannot be met.
2. `RunOptions.format_hint` is a free string (`"FMT1"`). It should be a typed
   literal recorded as `fmt_source: declared`.
3. `C_atom_wgfmu_read_measurement_values` returns `values` without time
   arrays and without event structure.
4. The C flow runner (`c_flows._compose`) stops on any result whose
   `fake is not True`, and `_failed()` treats `passed: False` or a
   `status` of failed/error as atom failure. CD runners need D-specific
   handling (see §6).

---

## 6. Contract Notes

**Envelope.** D atoms extend the existing `_fake_response` keys (`atom`,
`fake`, `hardware_touched`, `basis`) the way `_c_response` does:

```text
atom, class: "D", stage, subject, fake, hardware_touched: false,
synthetic, computed, deterministic, ok, basis[], parameters{}, result{},
findings[], warnings[], assumptions[], recommendations[] (advisory),
required_context[], evidence_missing[], method{name,version,params},
lineage{output_id, parents[], producer, created_at},
side_effects{hardware: "none", filesystem_writes: [...]}, warning
```

- `required_context` is the D analogue of C's `required_preconditions`:
  upstream evidence the caller must pass (for example "raw payload from
  `C_atom_smu_read_measurement_data`", "FMT declaration from
  `A_flow_prepare_flex_output_buffer`"). It is a list, never a call.

**Fake markers and synthetic taint.**

- In the first wave every D atom returns `fake: true`, `computed: false`, and
  null or empty results. It never returns a fabricated `accept` or a numeric
  Vth, just as C flows never fabricate curves.
- D is the first class whose real implementation needs no hardware. Once a
  pure atom is implemented and fixture-tested it returns `fake: false` while
  `hardware_touched` stays `false`. That is why `synthetic` is separate from
  `fake`. Any input with `fake: true` or `synthetic: true` makes every
  downstream D output `synthetic: true` (sticky). The verdict becomes
  `synthetic_only` and the bundle is segregated. CD runners must check
  `hardware_touched is False` and propagate `synthetic`, rather than
  reusing the C rule that stops on non-fake results.

**Field semantics.**

- `ok` means only "the atom executed without tool error".
- Data outcomes use `check_outcome`, `verdict` and `findings`.
- D responses must not use `passed`, `result_code`, or `status` set to
  failed/error/timeout/aborted to express data outcomes. The existing
  `_failed()` logic would misread a legitimately failed leakage screen as a
  broken atom.

**Units.**

- Canonical values are SI with explicit unit strings from a closed set:
  V, A, F, S, Ohm, H, s, Hz, rad, deg, `1`, A/m, A/m², F/m², V/decade.
- Data-type codes (V, I, F, Z, Y, C, L, R, P, D, Q, X, T) map to units.
  Phase rad/deg follows the IMP model (10/20 vs 11/21).
- No unit is ever inferred from magnitude.
- Timestamps are `time_base: instrument_relative` unless a TSR anchor is
  supplied.

**Status codes and compliance.**

- Every point keeps its raw status character, plus `cls` from a versioned
  table, plus `status_table_version`.
- Unknown codes map to `unknown`, and `unknown` is excluded by the default
  fitting mask.
- Compliance flags survive masking: masks exclude points but never erase
  flags.
- Derived quantities report `derived_from_flagged_points`.
- Where no header is present (FMT 2-style), status is `absent`, and
  `check_limits` becomes mandatory for any non-`needs_review` verdict.

**Context failures.** Missing required context returns `ok: true` with
`check_outcome: inconclusive` and `evidence_missing`, or `ok: false` with
`error.type: context_missing` when decoding is impossible. Never a guess.

**Input hygiene and size.**

- Request models are `extra="forbid"` and `allow_inf_nan=False`. Raw payload
  strings may legitimately contain overflow sentinels, which the decoder
  handles.
- Large arrays (WGFMU up to ~4M points/channel) travel as `artifact_ref`
  (path under the data root plus SHA-256), not inline JSON. Inline input is
  bounded (on the order of 1e5 points).

**Provenance.**

- `output_id` is a content hash of the canonical output.
- `parents` lists input ids. The producer is atom + version + method version.
- `created_at` is injectable for reproducibility.
- Station content is referenced by name plus hash only.

**Repo inconsistencies D must not paper over.** These are resolvable by
manual reading, not user decisions.

1. `parser_ascii.py` `MeasurementStatus` (V = overvoltage/unstable,
   D = invalid, L = interval too short) conflicts with
   `b1500a-command-parameters.md` (V = overflow, D/G/S = search-related,
   W/U listed). The meaning of `W`/`E` as sweep source-step markers vs
   "warning" is unverified. The status table must be reconciled against
   PG PDF 48-52 before any non-fake verdict.
2. The structured FMT table labels FMT 5 as 8-byte binary. The driver
   `AGENTS.md` and `A_atom_flex_set_data_format` treat {1, 5, 11, 15, 21, 25}
   as the ASCII-with-header set. Verify on PDF 435-436 before
   `parse_ascii` / `parse_binary` claim FMT 5.
3. The exact overflow sentinel value and the extended-format (FMT 11/21)
   field widths are still marked uncertain in the structured reference.

---

## 7. Open Questions for the User

1. **Real vs fake first wave.** D atoms can be truly implemented without
   hardware. Should the first registered wave be fake stubs for surface
   consistency (my recommendation, with real P0 pure functions following
   once fixture-tested), or real deterministic implementations from day one?
2. **Persistence from MCP tools.** Is it acceptable for
   `D_atom_archive_run_write_bundle` and the `render` atoms to write files
   under `data/` from an MCP call? If so, which bundle format: JSON + CSV
   (simple), or Parquet/HDF5 (large WGFMU data)? If not, the archive stage
   becomes manifest-only, and writing moves to an outer persistence service.
3. **Synthetic data archiving.** Should synthetic (fake-derived) runs be
   archived at all, in a segregated `data/synthetic/` path, or refused
   outright?
4. **Default exclusion policy.** Which status classes are excluded from
   fitting by default? In particular, should `compliance_other` (`T`, valid
   data while another channel limited) be kept or excluded? This is a lab
   convention that the manual does not settle.
5. **Extraction criteria defaults.** Should Vth, SS and leakage criteria
   (constant-current level per W/L, leakage threshold, compliance-proximity
   margin) have repo-wide defaults, or must they always come from a device
   profile or recipe? My recommendation is no defaults; undeclared criteria
   fail.
6. **Offline import scope.** Do you have existing EasyEXPERT exports or
   legacy data you want ingested early? If yes, raise
   `D_atom_decode_easyexpert_parse_export` from P2 to P1.
