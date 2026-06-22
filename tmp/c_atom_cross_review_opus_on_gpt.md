# Opus Review of GPT C Atom Candidates

Reviewer: Opus 4.6 Max  
Date: 2026-06-22  
GPT file: `tmp/c_atom_candidates_gpt55.md` (64 candidates, 19 P0)  
Opus file: `tmp/c_atom_candidates_opus46.md` (105 candidates, 31 P0)

---

## Agreement Summary

GPT and Opus agree on:

1. **Scope/exclusion boundaries** — identical classification of CN/CL/DZ/RZ, abort, reset, calibration, correction, routing, FMT/TSC/BC/NUB, status queries as A/B. No disputes.
2. **Object/unit-centered naming** — both use `smu`, `wgfmu`, `spgu`, `cmu`, `hvsmu`, `hcsmu`, `uhcu`, `easyexpert`.
3. **GNDU rejection** — both reject GNDU as a C category for the same reason (passive reference, no controllable source/measure).
4. **Core SMU P0 set** — `force_voltage`, `force_current`, high-speed spot, measurement mode, sweep configuration, pulse timing, and execute are P0 in both lists.
5. **Core WGFMU P0 set** — `create_pattern`, `add_vector(s)`, `add_sequence`, `set_measure_event`, `execute`, and `read_measurement_values` are P0 in both.
6. **CMU as P0 setup** — both include impedance model + frequency + AC/DC bias configuration at P0.
7. **EasyEXPERT classification** — both flag `run_selected_test` as C-like but clearly separate from hardware atoms.
8. **Ambiguity about WGFMU `update`** — both note C/B boundary tension.
9. **Trigger infrastructure** — both defer generic trigger port configuration (TGP/TGPC/etc.) out of C.

---

## GPT Items To Adopt Into Final List

| GPT Atom | Why Adopt | Adoption Notes |
|---|---|---|
| `C_atom_smu_execute_spot` (wraps DV/DI + MM1 + XE) | Useful as a **convenience C_flow or composite atom** for the common case. Most users will want "force + measure spot" as one operation. | Adopt as **P0 composite** but clarify it is built atop lower atoms (DV, MM, XE, read). Label it "composite C_atom" or promote to C_flow layer. |
| `C_atom_smu_execute_staircase_sweep` (separate from configure) | Clean separation of configure vs execute for sweeps. My list has `configure_sweep_voltage` + generic `execute_measurement` but no sweep-specific execute. GPT's pairing makes the data-return contract clearer. | Adopt the **configure + execute pairing pattern** for sweep/pulsed/sampling/search. The execute atom bundles XE + data decode. More user-friendly than raw `execute_measurement` + `read_measurement_data`. |
| `C_atom_smu_configure_adc_and_ranges` (bundled AIT+AAD+AV+RI+RV+RM+PAD) | Reduces atom count for a frequently co-configured set. Users rarely change AAD without also touching AIT and ranges. | Adopt **concept** of grouping, but recommend **two atoms** not one: (a) `configure_adc_integration` (AAD+AIT+AV+PAD) and (b) `configure_measurement_ranging` (RI+RV+RM). These are separable concerns (ADC quality vs range selection). |
| `C_atom_wgfmu_configure_force_measure_ranges` (bundled 5 set* functions) | For WGFMU, mode/range configuration is typically done together before pattern execution. One bundled atom is pragmatic. | Adopt. WGFMU mode/range changes are always done as a group. Reduces boilerplate in common path. Keep individual setters available as parameters within the bundled atom's schema. |
| `C_atom_wgfmu_transform_pattern` (merge/multiply/offset as one) | Pattern transform operations share the same "create derived pattern" intent. Combining avoids 3 nearly-identical atoms. | Adopt. Use a `transform_type` parameter to select merge/multiply/offset. |
| `C_atom_wgfmu_dc_force_measure` (combined force+measure) | For WGFMU DC mode, force and measure are logically a single operation. My list splits them (dc_force_voltage + dc_measure_value) which requires two round-trips for a common pattern. | Adopt as the **primary DC atom**. Keep individual `dc_force_voltage` only if there is a use case for force-without-measure (rare). |
| `C_atom_hvmcu_execute_high_voltage_medium_current_iv` | I missed HVMCU (N1266A) as a distinct category. It has unique dual-resource constraints. | Adopt as P2. Valid expander category. |
| `C_atom_uhvu_execute_ultra_high_voltage_iv` | I missed UHVU (N1268A) as distinct category. | Adopt as P2. Valid expander category. |
| `C_atom_easyexpert_run_quick_test_sequence` | I didn't consider Quick Test batch execution. It is a real remote-control use case. | Adopt as P2 flow candidate. |

---

## GPT Items To Reject Or Downgrade

| GPT Atom | Issue | Recommendation |
|---|---|---|
| `C_atom_smu_execute_spot` as **atom** | Wrapping DV+MM+XE+read into one atom is a **flow**, not an atom. Atoms should be the smallest reusable unit. If a user needs to force voltage and then measure multiple channels with different integration settings between them, this wrapper is too rigid. | **Rename to `C_flow_smu_spot_measurement`** or keep as composite/convenience. Not a true atom. |
| `C_atom_smu_execute_staircase_sweep` bundling XE+data-read | Same flow concern — bundling execute and data decode hides the async/polling pattern needed for long sweeps. | Keep execute separate from data decode. The execute atom returns completion status; data read is a second step. This matches real GPIB workflow (XE → *OPC? → NUB? → read). |
| `C_atom_smu_set_measurement_context` combining MM+CMM | `MM` and `CMM` have different semantics. `MM` selects mode+channels globally; `CMM` sets per-channel measurement behavior (compliance side, force side, etc.). Bundling them hides that `CMM` is optional and per-channel. | **Split**: keep `C_atom_smu_set_measurement_mode` (MM) and `C_atom_smu_set_measurement_operation` (CMM) separate. |
| `C_atom_smu_configure_multichannel_sweep_pulse` (single atom for MM16+MM27+MM28) | Too broad — MM16 (multi-ch sweep), MM27 (multi-ch pulsed spot), and MM28 (multi-ch pulsed sweep) have different command sets and parameter schemas. Combining into one atom creates a Swiss-army-knife with complex conditional logic. | **Split into at least two**: `configure_multi_sweep` (WNX for MM16) and `configure_multi_pulsed` (MCPT/MCPNT/MCPNX/MCPWS/MCPWNX for MM27/28). |
| `C_atom_smu_execute_multichannel_sweep_pulse` (single execute for MM16/27/28) | Same breadth problem — these modes produce different data shapes. | Split to match the configure atoms. |
| `C_atom_hvsmu_execute_high_voltage_iv` | This is not a new atom — it's the same `DV`/`WV`/`TI`/`MM`/`XE` commands with different range validation. | **Reject as separate atom**. Use schema constraints on `C_atom_smu_*` instead. Add `resource_type` validation to existing SMU atoms. Only `C_atom_hvsmu_set_operation_mode` (HVSMUOP) is genuinely distinct. |
| `C_atom_hcsmu_execute_high_current_iv` | Same — no new commands, just range constraints. | **Reject as separate atom**. Same commands as SMU, different range validation. |
| `C_atom_uhcu_execute_ultra_high_current_iv` | Marginal — the measurement commands are still DI/WI/TI with special ranges. The expander config (ERPF*) is B. | **Keep as P2** only because the dual-channel V-control pattern is operationally distinct enough to warrant its own validation schema. |
| `C_atom_cmu_execute_ct_sampling` without separate configure | GPT combines configure+execute for C-t sampling into one atom. This is inconsistent with the configure/execute split used for other CMU modes. | **Split** into `configure_ct_sampling` + use generic execute (shared XE). |
| `C_atom_spgu_execute_pulse_output` combining SRP+SPUPD+SPP | These have different semantics: SPUPD applies settings, SRP starts, SPP stops. Combining "start" and "stop" into one atom is confusing. | **Split into three**: `update_output` (SPUPD), `start_output` (SRP), `stop_output` (SPP). |

---

## GPT Missing Items

| Missing from GPT | Impact | Priority |
|---|---|---|
| `C_atom_smu_configure_sweep_timing` (WT) as separate atom | GPT bundles WT inside `configure_staircase_sweep`. But WT is reused by MM5 (sweep+pulsed bias) and other sweep modes. It should be independently configurable. | P0 — essential reusable timing atom |
| `C_atom_smu_configure_sweep_abort` (WM) as callable atom | GPT embeds WM in configure_staircase_sweep. But WM applies across modes and has important safety implications (auto-abort behavior). | P1 — should be independently settable |
| Individual timestamped spot atoms (TTI, TTV, TTIV) | GPT lumps into `measure_high_speed_spot` with a "timestamped flag". But TTI/TTV/TTIV return different data shapes than TI/TV/TIV (extra timestamp element). | P1 — keep as flag within spot atom (GPT approach OK), but document data shape difference |
| Timer-start force atoms (TDI, TDV, TACV, TDCV) | GPT omits these entirely. They combine source output + timer reset in one command — useful for precise timing experiments. | P2 — acceptable omission for MVP |
| `C_atom_smu_configure_pulse_voltage` / `_current` (PV/PI) as separate from timing | GPT has `configure_pulsed_spot_source` which bundles PV+PI+PT. But PT is shared across MM3/4/5; PV is specific to MM3/5. Different reuse patterns. | P0 — PT should be separate from PV/PI |
| `C_atom_cmu_set_impedance_model` (IMP alone) | GPT bundles IMP+FC+ACV+DCV+RC+ACT+LMN into one massive `configure_impedance_measurement`. This is too coarse — IMP/FC/ACV/DCV are independently useful and commonly changed between measurements without reconfiguring everything. | P0 — split into at minimum: IMP, FC+ACV+DCV (signal config), RC+ACT (ranging/integration) |
| `C_atom_cmu_configure_ac_sweep` (WACV/WTACV/WMACV) separate atom | GPT has it at P2. I agree on priority but it's absent from GPT's P1 list while C-f sweep is P1. These should be at same priority. | P2 — minor |
| WGFMU individual setters: `set_force_voltage_range`, `set_measure_current_range` | GPT bundles all into one atom. Individual atoms are useful when only one parameter changes (e.g., range autoranging during stress-measure cycling). | P1 — keep available as parameters within bundled atom, OR keep individuals at P1 alongside the bundle |
| `C_atom_smu_configure_signal_monitor` (DSMPL*) | GPT mentions it in notes ("P2 add-on") but doesn't include it as a formal candidate. | P2 — should be formally listed |
| `C_atom_spgu_set_load_impedance` (SPRM) as separate | GPT embeds in `configure_pg_pulse`. SPRM is independently important (affects voltage calibration). | P1 — separate or clearly documented parameter |
| `C_atom_cmu_spot_measure_c` (TC alone) and `_ts` (TTC) | GPT combines into `measure_high_speed_spot_c` with TMACV/TMDCV/TC/TTC. But TC is the direct analog of SMU's TI — a simple fast measurement. | P1 — fine to combine with flag, but name it clearly |

---

## Priority Differences

| Atom | GPT Priority | Opus Priority | Verdict |
|---|---|---|---|
| `C_atom_smu_execute_spot` (composite) | P0 | Not in Opus (would be P0 if added as flow) | **P0 as flow/composite** — too useful to omit |
| `C_atom_smu_configure_pulsed_spot_source` | P0 (GPT) | P0 for PT, P0 for PV (separate) | Agree P0 for components |
| `C_atom_smu_execute_pulsed_spot` | P1 (GPT) | P0-adjacent (via execute_measurement) | **P1 acceptable** — basic spot+sweep is enough for MVP |
| `C_atom_smu_configure_sampling` | P1 (both) | Agree | P1 |
| `C_atom_smu_configure_search` | P2 (both) | Agree | P2 |
| `C_atom_wgfmu_update_initial_voltage` | P1 (GPT) | P0 (Opus, as `update`) | **P0** — required before execute; can't skip it. GPT's P1 is wrong. |
| `C_atom_wgfmu_set_range_event` | P1 (both) | Agree | P1 |
| `C_atom_wgfmu_dc_force_measure` | P1 (both) | P1 (Opus split: force P1, measure P1) | Adopt GPT's combined at P1 |
| `C_atom_cmu_configure_impedance_measurement` (bundled) | P0 (GPT) | P0 (Opus, split into 4-5 atoms) | **P0 for the concept; split the atom** |
| `C_atom_cmu_measure_high_speed_spot_c` | P1 (GPT) | P1 (Opus) | Agree |
| `C_atom_cmu_configure_cv_dc_sweep` | P1 (GPT) | P0 (Opus) | **P0** — CV sweep is the most common CMU use case. GPT undervalues it. |
| `C_atom_easyexpert_run_selected_test` | P1 (both) | Agree | P1 |
| `C_atom_spgu_*` (all) | P1-P2 (GPT) | P1-P2 (Opus) | Agree |
| `C_atom_hvsmu_configure_output_mode` | P1 (GPT) | P1 (Opus) | Agree |

---

## Naming / Classification Recommendations

| GPT Name | Issue | Recommended Name |
|---|---|---|
| `C_atom_smu_set_measurement_context` | "context" is vague; in B1500 terms this is `MM` mode selection | `C_atom_smu_set_measurement_mode` |
| `C_atom_smu_configure_adc_and_ranges` | Too broad; conflates ADC quality settings with range selection | Split: `C_atom_smu_configure_integration` + `C_atom_smu_set_measurement_ranging` |
| `C_atom_smu_measure_high_speed_spot` | "measure" is correct but inconsistent with TI/TV/TIV naming in manuals. `spot_measure_i/v/iv` is more specific | `C_atom_smu_spot_measure` with `type` parameter (I/V/IV) — acceptable simplification over 3 atoms |
| `C_atom_smu_configure_multichannel_sweep_pulse` | Too broad name for 3 different modes | Split: `C_atom_smu_configure_multi_sweep` + `C_atom_smu_configure_multi_pulsed` |
| `C_atom_wgfmu_add_vectors` | Combines addVector + setVector which have different semantics (incremental vs absolute time) | `C_atom_wgfmu_add_vectors` (addVector/addVectors only) + `C_atom_wgfmu_set_vectors` (setVector/setVectors) — OR keep combined with `time_mode` param |
| `C_atom_wgfmu_execute_sequence` | "sequence" is accurate but could confuse with addSequence | `C_atom_wgfmu_execute` (matches API name `WGFMU_execute`) |
| `C_atom_cmu_configure_impedance_measurement` | Too coarse — bundles 7 commands | Split: `C_atom_cmu_set_impedance_model` + `C_atom_cmu_configure_signal` + `C_atom_cmu_set_ranging_integration` |
| `C_atom_cmu_execute_ct_sampling` | Inconsistent (configure+execute in one, unlike other CMU atoms) | Split: `C_atom_cmu_configure_ct_sampling` (MDCV+MTDCV) + shared XE |
| `C_atom_spgu_execute_pulse_output` | Combines start+update+stop into one | Split: `C_atom_spgu_update_output` + `C_atom_spgu_start_output` + `C_atom_spgu_stop_output` |
| `C_atom_hvsmu_execute_high_voltage_iv` | Not a real new atom; same DV/WV commands | Reject; use schema validation on existing `C_atom_smu_*` |

---

## Recommended Final Arbitration Notes

### 1. Granularity sweet spot

GPT's 64-candidate list is better for **user-facing ergonomics** (fewer atoms to learn, clearer workflow). Opus's 105-candidate list is better for **reusability and composability** (each atom does exactly one thing). 

**Recommendation**: Adopt a **two-tier model**:
- **Layer 1 (atoms)**: ~70-80 fine-grained primitives (closer to Opus's granularity for SMU source/configure, WGFMU pattern/event, CMU setup)
- **Layer 2 (composite C_atoms or C_flows)**: ~15-20 convenience wrappers (GPT's execute_spot, execute_staircase_sweep, dc_force_measure patterns)

### 2. Configure + Execute pairing

GPT's `configure_X` + `execute_X` pairing is a good pattern for sweep/pulsed/sampling modes. Adopt it. But the `execute_X` atom should NOT bundle data-read — that should remain separate to support async/polling workflows.

### 3. ADC/integration as C not B

Both lists agree. The final list should clearly state: AIT, AAD, AV are C because they are meaningless without measurement context and directly affect measurement outcome.

### 4. WGFMU `update` is P0

GPT rates it P1. This is incorrect — `update` is required between setup and execute. Without it, patterns aren't loaded to hardware. Must be P0.

### 5. CMU bundling

GPT's single `configure_impedance_measurement` is too coarse. IMP, FC, ACV, DCV change independently across measurements (e.g., frequency sweep changes only FC; DC-bias sweep changes only WDCV). Split into 2-3 setup atoms.

### 6. High-power resources

GPT is correct to include HVMCU and UHVU categories (Opus missed these). But GPT is wrong to make `execute_high_voltage_iv` a separate implementation — it should be a schema/validation wrapper over existing SMU atoms, not a new command pathway.

### 7. Final candidate count recommendation

| Category | Recommended Final Atom Count | Notes |
|---|---|---|
| SMU atoms | ~25 | GPT's 16 are too few (bundled); Opus's 33 are slightly over-split |
| SMU composites/flows | ~5 | execute_spot, execute_sweep (with data), etc. |
| WGFMU atoms | ~18 | Bundle ranges, keep pattern/vector/event individual |
| WGFMU composites | ~2 | dc_force_measure, full ALWG cycle |
| SPGU | ~10 | Keep start/stop/update separate from configure |
| CMU atoms | ~12 | Split configure into 2-3 setup atoms per mode |
| CMU composites | ~3 | spot_c_measurement, cv_sweep_measurement |
| HVSMU | 1 | Only HVSMUOP is genuinely new |
| Expanders (UHCU/UHVU/HVMCU) | 3-4 | Schema wrappers |
| EasyEXPERT | 2-3 | run + fetch at minimum |
| **Total** | **~80-85** | Between GPT's 64 and Opus's 105 |

### 8. Biggest risk in GPT's list

GPT's `execute_*` atoms that bundle XE + data decode create a **testing/mocking problem**: in the fake MCP server, you must simulate the full measurement pipeline within one atom call. Separating execute from data-read is safer for the test harness architecture.

### 9. Biggest risk in Opus's list

Opus's 105 atoms create **cognitive load** for the LLM agent that must select and sequence them. The measurement layer shouldn't require 8-10 atom calls for a basic IV curve. Composite/convenience atoms address this.
