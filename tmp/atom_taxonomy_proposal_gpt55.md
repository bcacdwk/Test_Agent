# Atom Taxonomy Proposal - GPT55

## Diagnosis Of Current Taxonomy

The current pattern is:

`{A|B}_atom_{subsystem}_{action}`

with `subsystem` values:

- `b1500`
- `wgfmu`
- `easyexpert`

This is compact and easy to sort, but it has a conceptual problem: the taxonomy level called `subsystem` is not actually one kind of thing.

- `b1500` is a direct instrument/mainframe interface.
- `wgfmu` is a module and module-library interface inside the B1500A/B1530A ecosystem.
- `easyexpert` is a software remote API sitting above instrument control.

That means the current name shape mechanically mirrors source manuals and APIs more than the scientific or operational structure of the system. The issue will get worse when future B1500 modules are added: SMU, WGFMU, SPGU, and CMU should not all become peers of `b1500` if `b1500` means the mainframe/direct instrument interface. External systems such as a prober or HSPICE also do not fit cleanly into a flat `subsystem` list.

A and B atoms also optimize for different reader questions:

- A atoms are mostly about session, identity, discovery, status, errors, buffers, result readout, and software context. They should be easy to scan in the Cursor MCP tool list by "what kind of observation/context operation is this?"
- B atoms are about state change, safety, reset, calibration, channel enablement, path switching, correction, abort, and standby. They should make risk and safety semantics obvious before the reader has to parse the target.

The current endpoint-first taxonomy works against both goals. It groups all direct B1500 tools together, but it hides the A semantic domain and delays the B risk domain until the final action words.

## Candidate Taxonomies Compared

### 1. Current `subsystem` Taxonomy

Naming pattern:

`{A|B}_atom_{subsystem}_{action}`

Examples:

- `A_atom_b1500_connect`
- `A_atom_wgfmu_open_session`
- `A_atom_easyexpert_list_workspaces`
- `B_atom_b1500_zero_all_outputs`
- `B_atom_wgfmu_abort`
- `B_atom_easyexpert_set_standby`

Pros:

- Very compact.
- Sorts well by current implementation/source interface.
- Easy to type when the user already knows whether they want direct B1500, WGFMU library, or EasyEXPERT.
- Minimal migration cost because this is the current surface.

Cons:

- Treats `b1500`, `wgfmu`, and `easyexpert` as peers even though they are different conceptual layers.
- Makes WGFMU look like a top-level instrument category rather than a B1500 module/library endpoint.
- Makes EasyEXPERT look like another hardware subsystem, even though it is a software/remote API.
- For B atoms, the safety/risk meaning is hidden after the endpoint.
- Scales poorly when SMU, WGFMU, SPGU, and CMU must coexist as B1500 modules while prober and HSPICE enter as external station/EDA endpoints.

Future scalability:

Acceptable for a short fake-tool discovery phase, but brittle for a durable taxonomy. Adding `smu`, `spgu`, `cmu`, `prober`, and `hspice` at the same level would produce a flat source-list rather than a clear control model.

### 2. Two-Level Interface Taxonomy: `hardware` / `software`

Naming pattern:

`{A|B}_atom_{interface_layer}_{target}_{action}`

Examples:

- `A_atom_hardware_b1500_connect`
- `A_atom_hardware_wgfmu_open_session`
- `A_atom_software_easyexpert_identify`
- `B_atom_hardware_b1500_zero_all_outputs`
- `B_atom_software_easyexpert_abort_measurement`

Pros:

- Correctly separates EasyEXPERT from hardware.
- Easy for new users to understand at a high level.
- Creates room for future software endpoints such as HSPICE.

Cons:

- `hardware` is too broad for B1500 mainframe, modules, accessories, buffers, and fixture paths.
- WGFMU still appears as a peer target unless an additional hierarchy is introduced.
- B atom risk semantics are still not obvious early in the name.
- A atoms are not easier to scan by task; `session`, `status`, `error`, `catalog`, and `context` are hidden behind the broad interface layer.

Future scalability:

Better than the current flat subsystem taxonomy for software endpoints, but not precise enough for B1500 module families or station hardware. It would likely need another refactor once prober, SPGU, CMU, and HSPICE are added.

### 3. Hardware-Layer Taxonomy

Naming pattern:

`{A|B}_atom_{physical_or_control_layer}_{target}_{action}`

Possible layer values:

- `instrument`
- `module`
- `accessory`
- `fixture`
- `buffer`
- `remote`
- `software`

Examples:

- `A_atom_instrument_b1500_connect`
- `A_atom_module_wgfmu_open_session`
- `A_atom_remote_easyexpert_identify`
- `B_atom_instrument_b1500_reset`
- `B_atom_module_wgfmu_abort`
- `B_atom_accessory_asu_set_path`
- `B_atom_module_cmu_measure_correction`

Pros:

- Makes WGFMU a module rather than a B1500 peer.
- Gives ASU, SCUU, and future accessories a natural place.
- Reflects real station topology better than the current `subsystem` label.

Cons:

- A atoms are not only hardware-layer operations. They include result format, timestamp, output buffer, logs, catalog discovery, EasyEXPERT workspace context, and parameter metadata.
- B atoms still need risk semantics. `B_atom_module_wgfmu_abort` is conceptually correct, but `abort` is the important safety word and appears late.
- Some targets have multiple identities: WGFMU is a module, a library API, and a waveform execution engine. Choosing only one physical layer may obscure the control path.
- `buffer` is not a physical peer of `instrument` or `module`.

Future scalability:

Good for station topology, weaker for operation semantics. Useful as a target hierarchy, but not ideal as the primary MCP tool-list grouping.

### 4. Operation-Semantics Taxonomy

Naming pattern:

`{A|B}_atom_{operation_domain}_{target}_{action}`

Possible A operation domains:

- `session`
- `identity`
- `status`
- `error`
- `buffer`
- `catalog`
- `context`
- `result`
- `log`

Possible B operation domains:

- `safety`
- `reset`
- `maintenance`
- `calibration`
- `output`
- `channel`
- `path`
- `correction`
- `abort`
- `standby`

Examples:

- `A_atom_session_b1500_connect`
- `A_atom_status_b1500_read_byte`
- `A_atom_error_wgfmu_read_summary`
- `A_atom_catalog_easyexpert_list_workspaces`
- `B_atom_abort_b1500_abort`
- `B_atom_output_b1500_zero_all_outputs`
- `B_atom_path_asu_set_path`
- `B_atom_correction_cmu_measure_correction`

Pros:

- A atoms become easy to scan by user intent in Cursor: `A_atom_error_*`, `A_atom_status_*`, `A_atom_catalog_*`, etc.
- B atoms make the kind of risky state change visible early.
- Works naturally with A/B/AB flow boundaries: observe/context with A, act/change with B, verify with A.
- Avoids making WGFMU a top-level taxonomy category if the target layer is hierarchical.

Cons:

- Needs a controlled domain vocabulary; otherwise similar atoms may drift between `status`, `context`, `policy`, and `calibration`.
- Names are longer than the current endpoint-first names.
- Searching by endpoint requires typing or filtering the second target segment, not the first segment after `A_atom`/`B_atom`.

Future scalability:

Strong if paired with a hierarchical target vocabulary. C atoms and flows can use their own semantic scheme without forcing A and B to share one taxonomy.

### 5. Recommended Hybrid: Domain-First, Hierarchical Target Second

Naming pattern:

For A:

`A_atom_{a_domain}_{target}_{action}`

For B:

`B_atom_{risk_domain}_{target}_{action}`

Where the target is hierarchical and descriptive:

- `b1500_direct` for the direct mainframe/GPIB/VISA interface.
- `b1500_wgfmu` for the WGFMU/B1530A module-library endpoint.
- `b1500_smu`, `b1500_spgu`, and `b1500_cmu` for future module-specific atoms.
- `b1500_asu` and `b1500_scuu` for accessories/path-control endpoints.
- `easyexpert_remote` for EasyEXPERT remote software API.
- Future external targets could be `station_prober` and `eda_hspice`.

Examples:

- `A_atom_session_b1500_direct_connect`
- `A_atom_session_b1500_wgfmu_open`
- `A_atom_catalog_easyexpert_remote_list_workspaces`
- `B_atom_safety_b1500_direct_check_interlock`
- `B_atom_output_b1500_direct_zero_all_outputs`
- `B_atom_emergency_b1500_wgfmu_abort`
- `B_atom_calibration_easyexpert_remote_zero_cancel_on`

Pros:

- Preserves scanability by putting the most important class-specific question first.
- A names answer: "what kind of context/observation operation is this?"
- B names answer: "what kind of risk/state-control operation is this?"
- WGFMU no longer appears at the same conceptual level as B1500; it becomes `b1500_wgfmu`.
- EasyEXPERT is explicitly remote software via `easyexpert_remote`.
- Future modules and external tools fit without flattening everything into one peer list.

Cons:

- It is a real rename if adopted.
- Some names become longer.
- Existing flow arbitration documents and any client references would need coordinated updates.
- The vocabulary must be governed to prevent over-fragmentation.

Future scalability:

Best of the compared options. It separates class-specific operation semantics from target hierarchy, which lets A atoms, B atoms, future C atoms, and flows each optimize for their own reader intent while sharing a consistent target vocabulary.

## Recommended Taxonomy

### A Atoms

#### Naming pattern

`A_atom_{a_domain}_{target}_{action}`

The first category is an A-specific operation domain. The target comes second and uses a hierarchy rather than a flat source-manual label.

Recommended target vocabulary for current A atoms:

- `b1500_direct`: direct B1500A mainframe/GPIB/VISA endpoint.
- `b1500_wgfmu`: WGFMU/B1530A module-library endpoint inside the B1500 ecosystem.
- `easyexpert_remote`: EasyEXPERT software remote API.

#### Subcategories

Recommended A subcategories:

- `session`: open/close/connect/disconnect and transport-session settings.
- `identity`: identity of an endpoint.
- `status`: status, settings snapshot, OPC, status byte, SRQ/status configuration, timestamp readback.
- `error`: error and warning queues, summaries, and lookups.
- `buffer`: B1500 measurement output buffer operations that do not start measurement.
- `format`: parser-facing data/result format configuration.
- `catalog`: inventory and discoverable lists: modules, channels, workspaces, app tests, preset groups, preset setups.
- `context`: software/setup context selection and metadata that does not execute measurement or change DUT output.
- `result`: non-executing result fetch/readback.
- `log`: logging and offline diagnostic export.

The A taxonomy should tolerate harmless software-context mutation because the current A/B boundary is not "read-only"; it is "does not change DUT output, safety-critical state, calibration state, or measurement execution."

#### Examples mapping existing A atoms

| Existing atom | Proposed taxonomy name |
|---|---|
| `A_atom_b1500_connect` | `A_atom_session_b1500_direct_connect` |
| `A_atom_b1500_disconnect` | `A_atom_session_b1500_direct_disconnect` |
| `A_atom_b1500_identify` | `A_atom_identity_b1500_direct_identify` |
| `A_atom_b1500_list_modules` | `A_atom_catalog_b1500_direct_list_modules` |
| `A_atom_b1500_get_status` | `A_atom_status_b1500_direct_get` |
| `A_atom_b1500_query_settings` | `A_atom_status_b1500_direct_query_settings` |
| `A_atom_b1500_read_error_queue` | `A_atom_error_b1500_direct_read_queue` |
| `A_atom_b1500_lookup_error` | `A_atom_error_b1500_direct_lookup` |
| `A_atom_b1500_read_status_byte` | `A_atom_status_b1500_direct_read_byte` |
| `A_atom_b1500_wait_opc` | `A_atom_status_b1500_direct_wait_opc` |
| `A_atom_b1500_set_data_format` | `A_atom_format_b1500_direct_set_data_format` |
| `A_atom_b1500_configure_timestamp` | `A_atom_status_b1500_direct_configure_timestamp` |
| `A_atom_b1500_reset_timestamp` | `A_atom_status_b1500_direct_reset_timestamp` |
| `A_atom_b1500_read_timestamp` | `A_atom_status_b1500_direct_read_timestamp` |
| `A_atom_b1500_clear_output_buffer` | `A_atom_buffer_b1500_direct_clear_output` |
| `A_atom_b1500_query_buffer_count` | `A_atom_buffer_b1500_direct_query_count` |
| `A_atom_b1500_read_output_buffer` | `A_atom_buffer_b1500_direct_read_output` |
| `A_atom_b1500_configure_srq` | `A_atom_status_b1500_direct_configure_srq` |
| `A_atom_wgfmu_open_session` | `A_atom_session_b1500_wgfmu_open` |
| `A_atom_wgfmu_close_session` | `A_atom_session_b1500_wgfmu_close` |
| `A_atom_wgfmu_set_timeout` | `A_atom_session_b1500_wgfmu_set_timeout` |
| `A_atom_wgfmu_get_channel_ids` | `A_atom_catalog_b1500_wgfmu_get_channel_ids` |
| `A_atom_wgfmu_get_status` | `A_atom_status_b1500_wgfmu_get` |
| `A_atom_wgfmu_get_channel_status` | `A_atom_status_b1500_wgfmu_get_channel_status` |
| `A_atom_wgfmu_clear` | `A_atom_context_b1500_wgfmu_clear_setup` |
| `A_atom_wgfmu_open_log` | `A_atom_log_b1500_wgfmu_open` |
| `A_atom_wgfmu_close_log` | `A_atom_log_b1500_wgfmu_close` |
| `A_atom_wgfmu_read_error` | `A_atom_error_b1500_wgfmu_read` |
| `A_atom_wgfmu_read_error_summary` | `A_atom_error_b1500_wgfmu_read_summary` |
| `A_atom_wgfmu_set_warning_level` | `A_atom_error_b1500_wgfmu_set_warning_level` |
| `A_atom_wgfmu_read_warning_summary` | `A_atom_error_b1500_wgfmu_read_warning_summary` |
| `A_atom_wgfmu_export_ascii` | `A_atom_log_b1500_wgfmu_export_ascii` |
| `A_atom_wgfmu_get_completed_event_count` | `A_atom_status_b1500_wgfmu_get_completed_event_count` |
| `A_atom_wgfmu_is_event_completed` | `A_atom_status_b1500_wgfmu_is_event_completed` |
| `A_atom_easyexpert_identify` | `A_atom_identity_easyexpert_remote_identify` |
| `A_atom_easyexpert_clear_status` | `A_atom_error_easyexpert_remote_clear_status` |
| `A_atom_easyexpert_wait_opc` | `A_atom_status_easyexpert_remote_wait_opc` |
| `A_atom_easyexpert_read_system_error` | `A_atom_error_easyexpert_remote_read_system_error` |
| `A_atom_easyexpert_list_workspaces` | `A_atom_catalog_easyexpert_remote_list_workspaces` |
| `A_atom_easyexpert_open_workspace` | `A_atom_context_easyexpert_remote_open_workspace` |
| `A_atom_easyexpert_close_workspace` | `A_atom_context_easyexpert_remote_close_workspace` |
| `A_atom_easyexpert_get_workspace_state` | `A_atom_status_easyexpert_remote_get_workspace_state` |
| `A_atom_easyexpert_get_workspace_name` | `A_atom_context_easyexpert_remote_get_workspace_name` |
| `A_atom_easyexpert_set_result_format` | `A_atom_format_easyexpert_remote_set_result_format` |
| `A_atom_easyexpert_fetch_result` | `A_atom_result_easyexpert_remote_fetch_latest` |
| `A_atom_easyexpert_list_app_tests` | `A_atom_catalog_easyexpert_remote_list_app_tests` |
| `A_atom_easyexpert_select_app_test` | `A_atom_context_easyexpert_remote_select_app_test` |
| `A_atom_easyexpert_list_preset_groups` | `A_atom_catalog_easyexpert_remote_list_preset_groups` |
| `A_atom_easyexpert_select_preset_group` | `A_atom_context_easyexpert_remote_select_preset_group` |
| `A_atom_easyexpert_list_preset_setups` | `A_atom_catalog_easyexpert_remote_list_preset_setups` |
| `A_atom_easyexpert_select_preset_setup` | `A_atom_context_easyexpert_remote_select_preset_setup` |
| `A_atom_easyexpert_get_selected_name` | `A_atom_context_easyexpert_remote_get_selected_name` |
| `A_atom_easyexpert_set_device_tag` | `A_atom_context_easyexpert_remote_set_device_tag` |
| `A_atom_easyexpert_get_device_tag` | `A_atom_context_easyexpert_remote_get_device_tag` |
| `A_atom_easyexpert_set_repeat_count` | `A_atom_context_easyexpert_remote_set_repeat_count` |
| `A_atom_easyexpert_get_repeat_count` | `A_atom_context_easyexpert_remote_get_repeat_count` |
| `A_atom_easyexpert_reset_repeat_count` | `A_atom_context_easyexpert_remote_reset_repeat_count` |
| `A_atom_easyexpert_set_app_test_param` | `A_atom_context_easyexpert_remote_set_app_test_param` |
| `A_atom_easyexpert_set_app_test_string` | `A_atom_context_easyexpert_remote_set_app_test_string` |
| `A_atom_easyexpert_load_setup` | `A_atom_context_easyexpert_remote_load_setup` |

#### Why this is better

This A taxonomy makes the Cursor MCP list easier to scan by task:

- Need connection/session tools: search `A_atom_session_`.
- Need errors: search `A_atom_error_`.
- Need discoverable catalogs: search `A_atom_catalog_`.
- Need EasyEXPERT context selection: search `A_atom_context_easyexpert_remote_`.
- Need WGFMU progress/status: search `A_atom_status_b1500_wgfmu_`.

It also fixes the conceptual hierarchy without burying practical endpoint names. WGFMU still remains findable, but as `b1500_wgfmu`, not as a top-level peer of `b1500`. EasyEXPERT is explicitly `easyexpert_remote`, so readers do not mistake it for a hardware subsystem.

### B Atoms

#### Naming pattern

`B_atom_{risk_domain}_{target}_{action}`

The first category is a B-specific risk or state-control domain. The target comes second and may be more specific than the A target because B operations often act on a module, path accessory, calibration subsystem, or output state.

Recommended target vocabulary for current B atoms:

- `b1500_direct`: direct B1500A mainframe/GPIB/VISA endpoint.
- `b1500_smu`: SMU-specific B1500 state.
- `b1500_asu`: ASU path/accessory state.
- `b1500_scuu`: SCUU path/accessory state.
- `b1500_cmu`: CMU correction and phase-compensation state.
- `b1500_wgfmu`: WGFMU/B1530A module-library endpoint inside the B1500 ecosystem.
- `easyexpert_remote`: EasyEXPERT software remote API.

#### Subcategories

Recommended B subcategories:

- `emergency`: abort/stop operations where immediate recovery or operator intent is safety-critical.
- `safety`: interlock, preflight, and confirmation gates.
- `reset`: reset, initialize, recover known-state operations.
- `maintenance`: self-test and diagnostics that may be long-running or operationally disruptive.
- `calibration`: self-calibration, zero cancellation, ADC zero, phase/calibration acts.
- `policy`: warning-as-error, auto-calibration policy, and similar state-control policies.
- `output`: channel enable/disable, zeroing, output standby, and output connection state.
- `channel`: channel conditioning that is not direct output enablement, such as SMU filter or series resistor.
- `path`: fixture/accessory path switching and path indicators.
- `correction`: CMU correction data, phase compensation, QSCV offset cancellation.

`emergency`, `safety`, and `output` should be used conservatively. If an operation can leave bias, source state, or fixture routing in a risky condition, prefer a risk-obvious category over a neutral target category.

#### Examples mapping existing B atoms

| Existing atom | Proposed taxonomy name |
|---|---|
| `B_atom_b1500_reset` | `B_atom_reset_b1500_direct_reset` |
| `B_atom_b1500_initialize` | `B_atom_reset_b1500_direct_initialize` |
| `B_atom_b1500_abort` | `B_atom_emergency_b1500_direct_abort` |
| `B_atom_b1500_self_test` | `B_atom_maintenance_b1500_direct_self_test` |
| `B_atom_b1500_self_calibration` | `B_atom_calibration_b1500_direct_self_calibrate` |
| `B_atom_b1500_diagnostics` | `B_atom_maintenance_b1500_direct_diagnostics` |
| `B_atom_b1500_set_auto_calibration` | `B_atom_policy_b1500_direct_set_auto_calibration` |
| `B_atom_b1500_enable_channels` | `B_atom_output_b1500_direct_enable_channels` |
| `B_atom_b1500_disable_channels` | `B_atom_output_b1500_direct_disable_channels` |
| `B_atom_b1500_zero_outputs` | `B_atom_output_b1500_direct_zero_outputs` |
| `B_atom_b1500_zero_all_outputs` | `B_atom_output_b1500_direct_zero_all_outputs` |
| `B_atom_b1500_confirm_zero` | `B_atom_safety_b1500_direct_confirm_zero` |
| `B_atom_b1500_check_interlock` | `B_atom_safety_b1500_direct_check_interlock` |
| `B_atom_b1500_preflight` | `B_atom_safety_b1500_direct_preflight` |
| `B_atom_b1500_recover_zeroed` | `B_atom_reset_b1500_direct_recover_zeroed` |
| `B_atom_b1500_set_smu_filter` | `B_atom_channel_b1500_smu_set_filter` |
| `B_atom_b1500_set_series_resistor` | `B_atom_channel_b1500_smu_set_series_resistor` |
| `B_atom_b1500_set_adc_zero` | `B_atom_calibration_b1500_smu_set_adc_zero` |
| `B_atom_b1500_set_asu_path` | `B_atom_path_b1500_asu_set_path` |
| `B_atom_b1500_set_asu_1pa_range` | `B_atom_channel_b1500_asu_set_1pa_range` |
| `B_atom_b1500_set_asu_indicator` | `B_atom_path_b1500_asu_set_indicator` |
| `B_atom_b1500_set_scuu_path` | `B_atom_path_b1500_scuu_set_path` |
| `B_atom_b1500_set_scuu_indicator` | `B_atom_path_b1500_scuu_set_indicator` |
| `B_atom_b1500_set_cmu_correction` | `B_atom_correction_b1500_cmu_set_correction` |
| `B_atom_b1500_measure_cmu_correction` | `B_atom_correction_b1500_cmu_measure_correction` |
| `B_atom_b1500_set_cmu_phase_mode` | `B_atom_correction_b1500_cmu_set_phase_mode` |
| `B_atom_b1500_perform_cmu_phase_comp` | `B_atom_correction_b1500_cmu_perform_phase_comp` |
| `B_atom_b1500_clear_cmu_correction` | `B_atom_correction_b1500_cmu_clear_correction` |
| `B_atom_b1500_qscv_offset_cancel` | `B_atom_correction_b1500_cmu_qscv_offset_cancel` |
| `B_atom_wgfmu_initialize` | `B_atom_reset_b1500_wgfmu_initialize` |
| `B_atom_wgfmu_self_calibration` | `B_atom_calibration_b1500_wgfmu_self_calibrate` |
| `B_atom_wgfmu_self_test` | `B_atom_maintenance_b1500_wgfmu_self_test` |
| `B_atom_wgfmu_treat_warnings_as_errors` | `B_atom_policy_b1500_wgfmu_treat_warnings_as_errors` |
| `B_atom_wgfmu_connect` | `B_atom_output_b1500_wgfmu_connect_channel` |
| `B_atom_wgfmu_disconnect` | `B_atom_output_b1500_wgfmu_disconnect_channel` |
| `B_atom_wgfmu_abort` | `B_atom_emergency_b1500_wgfmu_abort` |
| `B_atom_easyexpert_abort_measurement` | `B_atom_emergency_easyexpert_remote_abort_measurement` |
| `B_atom_easyexpert_set_standby` | `B_atom_output_easyexpert_remote_set_standby` |
| `B_atom_easyexpert_zero_cancel_on` | `B_atom_calibration_easyexpert_remote_zero_cancel_on` |
| `B_atom_easyexpert_zero_cancel_off` | `B_atom_calibration_easyexpert_remote_zero_cancel_off` |
| `B_atom_easyexpert_measure_zero_cancel` | `B_atom_calibration_easyexpert_remote_measure_zero_cancel` |
| `B_atom_easyexpert_query_zero_cancel_state` | `B_atom_calibration_easyexpert_remote_query_zero_cancel_state` |

#### Why this is better

This B taxonomy makes risk visible before implementation source. In a sorted Cursor MCP list, the user sees:

- `B_atom_emergency_*`
- `B_atom_safety_*`
- `B_atom_output_*`
- `B_atom_path_*`
- `B_atom_correction_*`
- `B_atom_calibration_*`

That is closer to how B atoms should be reviewed and invoked. A user should notice that `B_atom_emergency_b1500_wgfmu_abort` is a stop/abort primitive before they notice that it comes from the WGFMU library. Similarly, `B_atom_path_b1500_asu_set_path` foregrounds path switching as the risky operation, while still preserving the target hierarchy.

The target vocabulary also prevents WGFMU from being a peer of B1500. It is consistently `b1500_wgfmu`, while EasyEXPERT is consistently `easyexpert_remote`.

## Migration Impact

What would change:

- The primary grouping token after `A_atom` or `B_atom` would change from endpoint/source to operation semantics.
- WGFMU names would change from `*_atom_wgfmu_*` to `*_atom_*_b1500_wgfmu_*`.
- Direct B1500 names would become `*_atom_*_b1500_direct_*`.
- EasyEXPERT names would become `*_atom_*_easyexpert_remote_*`.
- B atoms would be regrouped by safety/risk category rather than by source API.
- Existing A/B/AB flow arbitration references would need coordinated update if these names are adopted.

What should stay stable:

- Keep the `A_atom`, `B_atom`, and future `C_atom` class prefixes.
- Keep the A/B semantic boundary: A for session/observation/context/result readout without DUT output/safety-critical state changes; B for safety/state-control/calibration/path/output operations.
- Keep response schema stability: `fake`, `hardware_touched`, `basis`, audit payloads, warnings/cautions.
- Keep source-basis traceability in tool descriptions and documentation, even if source manuals no longer drive the top-level taxonomy.
- Keep flow names semantic rather than source-manual-shaped.
- Do not expose legacy unprefixed aliases.

Suggested migration approach if renaming is later approved:

1. Decide the target vocabulary first: `b1500_direct`, `b1500_wgfmu`, `easyexpert_remote`, and future reserved names.
2. Freeze A/B domain vocabularies before editing tool definitions.
3. Update atom definitions and MCP reference docs in one mechanical pass.
4. Update A/B/AB flow arbitration docs and any flow implementation references in the same branch.
5. If external clients already depend on the current fake surface, provide a short compatibility table in documentation rather than adding runtime aliases by default.

Because the current server is explicitly fake-but-loadable and still in taxonomy design, a clean rename is preferable to carrying long-lived aliases, provided no released client contract exists yet.

## Open Questions

- Should EasyEXPERT application-test and preset selection remain A-class? The current arbitration treats selection as software context only. If later evidence shows selection arms measurement, changes hidden bias state, or modifies safety-relevant setup, those atoms should move to B `context`/`output`/`safety` domains or become AB/C-bound operations.
- Should `A_atom_easyexpert_clear_status` remain A? It clears remote error/status state, which is non-DUT-output but destructive to diagnostics. It may require an explicit `allow_clear_status` parameter in real implementation.
- Should `A_atom_b1500_clear_output_buffer` remain A? It does not change DUT output, but it can destroy unread measurement data. The A classification is acceptable only if real flows preserve audit payloads and require explicit `allow_clear_buffer`.
- Should `B_atom_b1500_zero_all_outputs` be `output` or `emergency`? I recommend `output` for the atom because it can be used in normal shutdown, and reserve `emergency` for abort/stop primitives or emergency flows. The flow name can still be emergency-specific.
- Should `B_atom_wgfmu_abort` be followed by a zero/disconnect primitive? The current note says channels keep output voltage at abort. That makes the atom emergency-class but not sufficient as a complete emergency recovery flow.
- Should target names include the vendor/model (`b1530a_wgfmu`) instead of role (`b1500_wgfmu`)? I recommend role/hierarchy for tool scanning, with model details retained in docstrings and `basis`.
- Should future C atoms use the same domain-first shape? Probably yes, but not the same domain list. C should likely use measurement technique first, for example `C_atom_iv_b1500_smu_spot`, `C_atom_cv_b1500_cmu_sweep`, `C_atom_pulse_b1500_wgfmu_execute`, or `C_atom_easyexpert_remote_run_app_test`.
- How should future external systems be named? A likely target vocabulary is `station_prober` for prober automation and `eda_hspice` for simulation integration, but those should be decided when their atom classes are designed.
