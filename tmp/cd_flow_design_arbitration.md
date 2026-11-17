# CD Flow Design Arbitration

Date: 2026-11-17

Status: accepted arbitration (cross review and arbitration in one pass) for the first `CD_flow_*` wave of fake,
loadable MCP tools. Planning only; implementation is a separate task. CD flows compose the fake C runner with D
placeholder stubs (U1), so they are fake-only. U7 and U8 were decided by the user on 2026-11-17
(section 13: both adopt the recommended default).

Inputs: `tmp/dcd_flow_design_opus55{a,b}.md` (A: 4 CD flows + 1 reserved; B: 4 + 2 held); binding `AGENTS.md`,
`tmp/d_atom_arbitration.md` (with section 11), `tmp/d_flow_design_arbitration.md`; precedents
`tmp/{c_flow,ab_flow,b_flow}_design_arbitration.md`, `mcp-tools/{c-flows,ab-flows}.md`; code `mcp/{common,c_flows,ab_flows}.py`,
`schemas/c_flow.py`, `tests/test_c_flows.py`; `references/{recipes,devices}/`. All 30 C flows were run with default requests.

## 1. Scope (Decided)

A CD flow is measure-then-interpret: exactly one C flow invocation produces the whole dataset, one interpreting
D flow consumes that flow's designated data record unmodified, and the archive D flow records the attempt. Phases are
`expect -> measure -> interpret -> archive`. D runs only on a completed C read. `ok` reflects composition errors
only, never a verdict. Synthetic data can never pass; in this phase everything is synthetic and nothing is written.

## 2. Factual Verdicts (checked against code)

| Claim | Verdict | Evidence |
|---|---|---|
| C envelope: `ok = not failed`; `partial = failed or gaps or state != simulated_complete`; `measurement_completed` always false; `outputs.synthetic: true`; cleanup `owner: outer_ABC_transaction`, `performed: false` | Correct (A, B) | `c_flows.py:196-221` |
| `execution_state` precedence: `failed`, then `configuration_only` (gaps), then `simulated_complete`, else `awaiting_completion` (`configuration_only` if nothing executed) | Correct | `c_flows.py:161-168` |
| Completion comes only from an execute-phase result with `status: fake_complete` or an inline `sample`/`measurement`; otherwise reads are skipped | Correct | `c_flows.py:138-146`; `test_pending_execute_skips_read` |
| Default-request states | 18 `simulated_complete` (5 spot, smu staircase, qscv, 3 CMU sweeps, smu and CMU pulsed spot, pulse CMU cv, WGFMU waveform, CMU ct, 3 remote), 10 `configuration_only`, 2 `awaiting_completion` (SPGU) | run of `C_FLOW_FUNCTIONS` |
| Executable SMU flows force and measure one channel (`MM` over `[q.channel]`); every two-channel composition (synchronous, multi_channel, pulsed_bias, multi pulse, spgu_bias) is `configuration_only` (A DG2, B CG1) | Correct | `_smu_setup`, `_sweep_setup` (`c_flows.py:229-288`) |
| No double sweep (A DG3); CMU `model` is a free string (B CG2) | Correct | `SmuSweep.sweep_type`, `CmuSetup.model` |
| Remote EasyEXPERT flows reach `simulated_complete` with no data record (A) | Correct | `outputs.data == []` |
| A's gate `len(outputs.data) >= 1` detects data | **Wrong.** The scrape keys on `rows/values/sample/measurement`; `C_flow_spot_smu_high_speed` lists `C_atom_smu_configure_high_speed_spot` (parameter `measurement: "current_voltage"`) as data | `c_flows.py:176-188` |
| May flows call flows? | Only the cross-family layer: AB calls A/B flows plus narrow atoms; A/B/C flows call only same-class atoms ("Only C atoms are invoked") | `ab_flows.py:12-55`; C arbitration |
| AB sets `ok = not partial` | Correct; CD must not copy it (both agree) | `ab_flows.py:202` |

## 3. Divergence Resolutions

| # | Topic | A | B | Decision and one-line rationale |
|---|---|---|---|---|
| CD1 | Naming | `CD_flow_<operation>_<domain>_<subject>` = D name | `CD_flow_<intent>_<object>_<subject>`, intents `acquire/screen/analyze` | **Mirror the D name.** One pairing rule, no extra intent word (`acquire` is `qualify`), no mixed subjects (B mixes C shapes `staircase/spot/cv` with the D curve kind `leakage`), no tool per anchor. |
| CD2 | C flow selection | closed `acquisition.kind` | one fixed anchor per flow | **Closed per-flow `acquisition.kind`**: a Pydantic discriminated union, required, no default, echoed as `c_flow` and in `flows_called`. The C precedent already lets request fields pick atoms (source picks force_voltage or force_current; search type picks MM 14 or 15). B's rule would need a new subject token just for spot leakage. |
| CD3 | Interpret gate | `ok`, `simulated_complete`, `len(outputs.data) >= 1` | designated anchor record + `handoff.state` | **Designated data record (B).** `outputs.data` is unreliable (section 2) and trimmed (G6). |
| CD4 | Phase 4 name | `archive` | `record` | **`archive`.** Atom #3 already rejected `record` (audit records use the word), and the phase is the archive flow. |
| CD5 | Archive behaviour | always, `persist` default true | opt-in `archive: true`; otherwise manifest atom | **Always planned, no flag.** The archive phase calls `D_flow_archive_run_bundle` whenever measure was attempted. `AGENTS.md` requires every real instrument action to be auditable, so opt-in would create an unrecorded real path. Under U2 the cost now is planned paths only. |
| CD6 | Admitted C kinds | iv 4, screen 2, cv 8, timeseries 1 | staircase P0, spot P1, CMU cv P2 | **Uniform-handoff rule:** admit a kind only if its C flow reaches `simulated_complete` without gaps and its data record is a buffered `C_atom_{smu,cmu}_read_measurement_data` read. High-speed spot (inline status-less sample, G3) and CMU C-t (time-indexed, ingest undesigned) are held. |
| CD7 | Timeseries CD | P2 registered | rejected (G4) | **Reserved.** WGFMU reads are per-channel `values` with no time axis (G4), so the handoff is undefined. The D flow stays registered. |
| CD8 | Unexpected marker | stop everything | manifest only | **Stop everything (A).** No later child call is trustworthy; the envelope is the audit. |
| CD9 | Taint violation in interpret | `ok:false`, clamp | `ok:false`, never archived | **`ok:false`, verdict null, archive still runs** and records the violation. The measurement happened and must stay auditable; nothing is written under U2 anyway. |
| CD10 | Request field name | `acquisition` | `measurement: SmuSweep` | **`acquisition`.** `measurement` is a banned key (atom #5) and a C scraper key. |
| CD11 | Leakage limit vs compliance | require limit < compliance | absent | **Adopt.** At or above compliance the reading clamps, so a fail can never be observed. This is structural, not a station policy. |
| CD12 | Real-mode ordering vs cleanup | allowed; recipe flag `analysis_before_cleanup` | CD fake-only; real C -> B safe-state -> D | **User decision U7**; B recommended. |
| CD13 | Transfer-curve C anchor | recipe/ABC | add to C | **User decision U8**; adding it is recommended. |

## 4. Composition Boundary (Decided)

| Caller | May call | Must not call |
|---|---|---|
| `CD_flow_*` | exactly one `C_flow_<kind>`, once; exactly one interpreting `D_flow_*` with the same name; `D_flow_archive_run_bundle`; narrow D atoms `D_atom_ingest_request_build_expectation` and (P1) `D_atom_assess_dataset_check_envelope` | `A_*`, `B_*`, `C_atom_*`, other CD flows, a second C flow, retries, loops |

- **A/B are reported, never called.** `required_preconditions` is the C child's list plus D children's `required_inputs` that name A/B evidence (for example `A_flow_prepare_flex_output_buffer`, `A_flow_drain_flex_errors`, `B_flow_preflight_b1500_gate`).
- Callers may pass A/B envelopes they hold as `upstream_evidence` (at most 16). They are forwarded to `D_atom_qualify_run_check_context`, recorded as `evidence_unverified`, and never lift a trust cap (amendment M6; both proposals agree).
- No retry, adaptation, extension or repeat based on any D product. The C flow is called at most once, even when it fails.

## 5. Naming

`CD_flow_<operation>_<domain>_<subject>` with operation in {`qualify`, `screen`, `analyze`} and domain
in {`iv`, `cv`, `timeseries`}. `CD_flow_X` exists only if `D_flow_X` exists; `archive`, `render` and
`replay` never get CD names. `acquisition.kind` values are C flow `<family>_<object>_<subject>`
tokens, and `c_flow = "C_flow_" + kind`, so the C object stays visible in the response.

## 6. C Execution States and the Handoff

The designated data record is the single read-phase record of the kind's catalog read atom
(`C_atom_smu_read_measurement_data` or `C_atom_cmu_read_measurement_data`) with status `ok`. The
locator is `{child_index, atom_index, atom, element_count}`; a content hash waits for G1.

| C child result | `handoff.state` | interpret | archive | CD `ok` | `partial` | skip reason |
|---|---|---|---|---|---|---|
| `simulated_complete`, designated read ok, >= 1 element | `received` | runs | runs | from children | from children | - |
| `simulated_complete`, designated read ok, 0 elements (fake norm `rows: []`) | `empty` | runs, warning "empty synthetic data is not evidence of quality" | runs | from children | from children | - |
| `simulated_complete`, designated record missing | `no_data` | skipped | runs | true | true | `c_no_data_record` |
| `configuration_only` | `no_data` | skipped; C gaps copied to `contract_gaps` | runs | true | true | `c_configuration_only` |
| `awaiting_completion` | `pending` | skipped; hand-off warning copied | runs | true | true | `c_awaiting_completion` |
| `failed` (`ok:false`) or the C flow raised | `no_data` | skipped | runs | false | true | `c_failed` |
| `fake` not true or `hardware_touched` not false | - | stopped | stopped | false | true | `c_unexpected_marker` |

Admitted kinds cannot reach rows 3-6 with valid requests. Those rows are guarded and are tested by
monkeypatching, as `test_pending_execute_skips_read` does. `blocked` is reserved for a future anchor with a
blocking handoff gap (WGFMU G4). `execution_state` is the C child's, or `not_run` when expect fails.

- D receives the C child envelope by reference, reads only the designated record and never `outputs.data`. Records are retained once, in the measure child.
- The expect phase builds the expectation from the typed C request before measuring and hands its ProductRef to the D flow, which records its own build_expectation as optional-skipped (`expectation_supplied`). An expect `ok:false` stops the CD before measuring; this is a composition failure, not a D gate, and expectation findings never alter the C request.

## 7. Catalog

Phase skeleton: **expect** `D_atom_ingest_request_build_expectation` -> **measure** `C_flow_<kind>` ->
**interpret** `D_flow_<same name>` -> [P1: `D_atom_assess_dataset_check_envelope` if `envelope`] ->
**archive** `D_flow_archive_run_bundle` (envelopes: expect, measure and interpret children plus upstream evidence).

| CD flow | Pri | `acquisition.kind` (closed) | Interpret D flow | Request |
|---|---|---|---|---|
| `CD_flow_qualify_iv_dataset` | P0 | `spot_smu_iv`, `sweep_smu_staircase`, `pulse_smu_spot` | `D_flow_qualify_iv_dataset` | `CdQualifyIv` |
| `CD_flow_screen_iv_leakage` | P0 | `spot_smu_iv`, `sweep_smu_staircase` | `D_flow_screen_iv_leakage` | `CdScreenIvLeakage` |
| `CD_flow_qualify_cv_dataset` | P2 | `spot_cmu_impedance`, `sweep_cmu_cv`, `sweep_cmu_cf`, `sweep_cmu_ac_level`, `pulse_cmu_spot`, `pulse_cmu_cv` | `D_flow_qualify_cv_dataset` | `CdQualifyCv` |

Registered: **3** (P0 2, P1 0, P2 1). Reserved: `CD_flow_analyze_iv_transfer` (becomes P1 with a new
kind if U8 is adopted) and `CD_flow_qualify_timeseries_dataset` (G4). The CMU flow is fake-only:
real C-V waits for correction, SCUU and leakage validation (`AGENTS.md`).

Ordered calls for `CD_flow_screen_iv_leakage`, `kind = sweep_smu_staircase`:

1. `D_atom_ingest_request_build_expectation`
2. `C_flow_sweep_smu_staircase` -> `C_atom_smu_configure_integration`, `C_atom_smu_set_measurement_ranging`, `C_atom_smu_set_measurement_mode`, `C_atom_smu_configure_sweep_timing`, `C_atom_smu_configure_sweep_abort`, `C_atom_smu_configure_staircase_sweep`, `C_atom_smu_execute`, `C_atom_smu_read_measurement_data`
3. `D_flow_screen_iv_leakage` -> `Q_IV` steps 2-8 (step 1 optional-skipped), `D_atom_extract_leakage_current`, `D_atom_assess_value_check_limits`
4. `D_flow_archive_run_bundle` -> `D_atom_archive_run_build_manifest`, `D_atom_archive_run_write_bundle` (planned paths only)

With `kind = spot_smu_iv`, step 2 replaces timing, abort and staircase with `C_atom_smu_force_voltage` (6 atoms).

## 8. Request Contract

New `schemas/cd_flow.py` on `FlowModel`, reusing `schemas/c_flow.py` and `schemas/d_flow.py`:

```text
Acquisition  one class per kind {kind: Literal["<kind>"], request: <C model>}, discriminator "kind"
             (SmuSpot, SmuSweep, SmuPulse; CmuSetup, CmuSweep, CmuPulse, CmuPulseSweep); no default kind or request
CdBase       {acquisition, channel_roles: list[ChannelRole] (required), upstream_evidence: list[dict] = [] (<=16),
              trust_policy = U3 default (versioned, echoed), envelope: EnvelopeSpec|None (P1),
              intent_note: str|None, station: {name, sha256}|None}
CdQualifyIv       = CdBase (kinds of section 7)
CdScreenIvLeakage = CdBase (spot_smu_iv | sweep_smu_staircase) + leakage: LeakageSpec (required; D doc section 6)
CdQualifyCv       = CdBase (CMU kinds) + imp_model (typed Literal; must equal request.model, CG2)
```

Validators run before any child call (`ValidationError`, zero calls, C precedent):

- `request.run.collect` is true; `run.max_items >= expected points x measured channels` (1 for spot and pulsed spot, `steps` for sweeps; exact count is a completeness finding, CG6);
- every measured channel has exactly one role and roles name only measured channels;
- screen: `source == "voltage"`, `ranging.measure_function == "current"`, `leakage.terminal` is the role of `request.channel`, bias points within `[min(start, stop), max(start, stop)]` (staircase) or equal to `[level]` (spot), criteria in A with limit < `compliance` (CD11);
- criteria and `SourceRef` required (U4), no defaults, no method aliases.

## 9. Response and Failure Contract

```text
flow, flow_class: "CD", category, domain, subject, purpose, c_flow, d_flow, fake (AND of children),
hardware_touched (OR), ok, partial, destructive (= C), consumptive (= C),
phases{expect[], measure[], interpret[], archive[]}, flows_called, atoms_called (direct + nested, ordered),
child_results[{phase, name, kind: c_flow|d_flow|d_atom, inputs, input_refs, timestamp, status, optional, reason, result | error}],
execution_state (= C or not_run), measurement_completed: false, simulation_completed (= C),
handoff{state, source_atom, child_index, atom_index, element_count, reason},
analysis_state (D aggregate, plus not_run), analysis_completed: false, data_origin, synthetic,
inputs (request dump), outputs{products{}, trust_level, verdict, verdict_scope, evidence_citation{eligible, blockers[]},
  escalations[] (P1), archive{manifest_ref, planned_paths, artifact_written: false, write_refusal[]}},
required_preconditions, contract_gaps (C gaps + handoff gaps), findings, warnings (prefixed by child), assumptions,
evidence_missing, side_effects{hardware: "none", filesystem_writes: [], artifact_written: false}, cleanup (C block + analysis_side_effects: "none"),
audit{phase_order: [expect, measure, interpret, archive], child_count, skipped_children, skip_reasons, consumptive_children},
error{type, message, at}   (only when ok=false)
```

- **`ok`** means the composition did not fail (C/D semantics); `partial` is read separately. Banned keys and taint rules are as in the D doc section 7; the stub norm on a completed read is `ok:true`, `partial:false`, `not_computed`, `trust_level` and (screen) `verdict` `synthetic_only`, `evidence_citation.eligible: false` with blockers `synthetic_origin` and `analysis_not_computed`.
- **Failure by phase:** expect fails -> stop, nothing measured, no archive; measure fails -> interpret skipped (`c_failed`), archive runs, `ok:false`; interpret fails or taint violation -> remaining interpret skipped, archive runs, `ok:false`; archive fails -> `ok:false`, `partial:true`; unexpected marker anywhere -> stop everything. Earlier evidence is always retained unchanged with timestamps.
- **Cleanup:** CD performs none and is not a cleanup boundary. It copies the C `cleanup` block (`performed: false`). Failure cleanup must be installed by the outer transaction before CD is called (C rule). A CD result is never a safe-state transaction. Real-mode ordering is U7.
- **Archive:** always planned (CD5). This phase returns `write_refusal: [fake_mode, synthetic_origin]`, relative `planned_paths` and no files.

## 10. Boundary vs Recipes/ABC

A composition is a CD flow only if: (1) one C flow invocation produces the whole dataset, with no
outer loop, sequence, program/read or pre-check-then-measure; (2) that C kind passes the
uniform-handoff rule (CD6); (3) the product is a catalog D curve-kind analysis whose device-dependent
values are declared with a `SourceRef`; (4) no decision depends on the D result; (5) no A/B action
(routing, correction, selector switching, cleanup) is needed between measure and interpret.

| Composition | Home | Fails |
|---|---|---|
| Id-Vg Vth/SS/gm/on-off | reserved `CD_flow_analyze_iv_transfer` if U8; else recipe/ABC + `D_flow_analyze_iv_transfer` | 2 (no two-channel executable anchor) |
| Id-Vd family, Ron | ABC (C x N) + `D_flow_analyze_iv_output` | 1 |
| Hysteresis | `D_flow_analyze_iv_transfer` (`voltage_shift`) on recipe/ABC data | 2 (no double sweep) |
| FeFET write/read, memory window, PUND, endurance, retention, BTI | recipes/ABC | 1, 4, 5 |
| Breakdown | ABC with human approval (destructive) | 4 |
| Leakage screen then CV | ABC (U5 evidence plus approval) | 5 |
| EasyEXPERT run plus analysis | ABC: C remote flow, A fetch, D flow after G5 | 5 |
| SPGU-only or configuration-only C flows | not added: interpret could never run | 2 |

CD and D never read `references/devices` or `references/recipes`. ABC resolves a profile or recipe
and passes values plus their `SourceRef`. Recipes keep device limits, stop conditions and cleanup
(for example `idvg.example.yaml` declares `cleanup: [DZ, CL]` and a drain bias, which no executable
C flow can hold today). G13 must be fixed before criteria are sourced from the example YAMLs.

## 11. Known Gaps

| # | Gap | Owner |
|---|---|---|
| CG1 | No executable anchor that holds a constant bias on another channel while measuring several channels (U8) | C round |
| CG2 | `CmuSetup.model` is a free string; `imp_model` consistency is checked by equality only | C schema |
| CG3 | `outputs.data` scrape counts config parameters named `measurement` as data (high-speed spot); CD avoids it via designated records | C flow |
| CG4 | No stable record id or content hash in C `atom_results` (G1); the handoff locator is index-based | C |
| CG5 | Caller A/B evidence is unverifiable; lifting caps needs in-process ABC passing or a server evidence registry | kernel/ABC |
| CG6 | `max_items` vs expected elements is conservative; exact accounting needs a real `build_expectation` | D/C |
| CG7 | AB `ok = not partial` vs C/D/CD semantics; a future ABC runner must read `partial` separately | ABC |
| CG8 | `_cd_compose` (AB-style phases, kind -> C flow map, handoff gate), `register_cd_flows`, capabilities key `CD_flows`, `mcp-tools/cd-flows.md`, README index | implementation |
| CG9 | WGFMU handoff (G4) blocks timeseries CD; high-speed spot (G3) and CMU C-t kinds held | C/D |

## 12. Validation Plan (`tests/test_cd_flows.py`, hardware-free)

1. **Discovery:** 3 tools with a typed `request` exposing the `kind` discriminator; every CD name has its D name; every kind maps to a name in `C_FLOW_FUNCTIONS`; reference docs list all names.
2. **Boundary:** spies show exactly one call to the selected C flow, even when it is patched to fail or D returns `fail`; no direct C atom, A or B call; direct children are exactly expect atom, C flow, D flow and archive flow (plus the P1 envelope atom).
3. **Order:** table-driven exact nested `atoms_called` per kind (section 7 sequences).
4. **States:** patch the C flow to each section 6 row plus an exception and a marker; check interpret/archive run or skip, `ok`, `partial`, `handoff.state`, skip reasons and copied gaps and warnings. `rows: []` gives `empty`, a warning and interpret runs; a config record keyed `measurement` never counts as data.
5. **Expect:** runs before measure; the D flow's own build_expectation is optional-skipped; a patched expect `ok:false` gives zero C calls.
6. **Taint:** synthetic origin, `synthetic_only` labels, ineligible citation with blockers; an injected D `pass` gives `ok:false`, verdict null, and archive still runs with the violation finding.
7. **Validators:** `collect=False`, `max_items < steps`, role/channel mismatch, current source for leakage, bias outside the sweep or not equal to the spot level, limit >= compliance, missing criteria and a wrong C model for a kind: `ValidationError`, zero child calls.
8. **Archive:** no files under `tmp_path`; `artifact_written: false`; refusal codes; relative planned paths; archive runs for `c_failed`, `c_configuration_only`, `c_awaiting_completion`, not for a marker.
9. **Hygiene:** banned keys absent; `json.dumps(allow_nan=False)`; C records appear once; fake/hardware markers; `cleanup.performed: false`; identical envelopes apart from timestamps.

## 13. User Decisions (decided by the user 2026-11-17)

U7 and U8 adopt the recommended defaults below. U7: real runs are C -> safe-state -> D -> archive and CD
stays a fake/contract composition. U8: add the biased SMU staircase C flow as a C-round amendment, which
unblocks `CD_flow_analyze_iv_transfer` at P1.

Deduplicated against U1-U6; caller-passed evidence, archive default, naming and DG1 are decided above. Two genuine policy choices remain:

| # | Decision | Recommended default |
|---|---|---|
| U7 | Real-mode role of CD: may a real ABC transaction run D analysis (and the archive write) after C returns but before the outer cleanup, so the DUT holds its post-measurement bias for that time? Or must real runs be C -> B/AB safe-state -> D -> archive, with CD staying a fake/contract composition? | **C -> safe-state -> D; CD stays fake-only.** Real ABC transactions reuse CD's handoff helpers in code. D never feeds back into the measurement (atom section 1), so analysis before cleanup gains nothing and only lengthens bias exposure and real-mode file I/O before the safe state. Alternative (A): allow CD in real ABC with a recipe-declared `analysis_before_cleanup: allowed\|forbidden`, forbidden for stress-sensitive DUTs. |
| U8 | Change the C family: add an SMU staircase C flow with declared constant-bias channels (each with its own compliance) and an explicit measured-channel list, for example `C_flow_sweep_smu_staircase_biased` (name to be set in that round)? | **Yes, as a C-round amendment.** It is a measurement primitive (a sweep plus held biases), not a device experiment. It looks composable from existing atoms (`C_atom_smu_force_voltage` with `compliance_a`, multi-channel `C_atom_smu_set_measurement_mode`, per-channel ranging), so it should be executable without new contract gaps; the C round must confirm that. It would unblock `CD_flow_analyze_iv_transfer` (P1) and multi-terminal leakage kinds. Until then, transfer CD stays reserved and Id-Vg stays in recipe/ABC. |

## Amendment 2026-11-17: review follow-ups

- **Archive:** every envelope of a CD run reaches the manifest. The cap `MAX_ARCHIVE_ENVELOPES` = 1 C flow + 3 D children (expect atom, interpreting D flow, optional envelope atom) + 16 upstream = 20 is derived from these CD maximums, so the truncation path (upstream envelopes kept only in `inputs.upstream_evidence`, with a warning and gap) is removed.
- **CD11 and leakage axis:** the bias-point and limit-below-compliance rules are one validator shared with standalone D, called with `request.channel`; behaviour of the section 8 screen validators is unchanged.
- **Roles:** the measured-channel and missing-role logic of section 8 is shared with D; CD still rejects a missing role, standalone D reports `pin_map_incomplete` and caps trust at `needs_review`.
- **CMU endpoints:** positive cf/ac_level endpoints are now checked by the typed C request (`CmuPositiveSweep`, C amendment of the same date); the CD-only `_PositiveSweep` check is removed and CD still rejects before any child call.
- **Known gap:** the expect-phase expectation carries no origin evidence, so it defaults to `synthetic` and would taint a future real run. Accepted because CD is fake-only (U7); resolve before any real-mode CD or ABC use.
