# GPT Review of Opus C Atom Candidates

## Agreement Summary

Opus's scope boundary is mostly correct: C_atoms are source/measurement/execution; A remains session/discovery/status/parser/context; B remains safety, lifecycle, routing, correction, calibration, and output enable/disable. I agree with Opus on excluding `CN/CL/DZ/RZ`, `AB/*RST/IN`, `SAP/SSP/SAR`, `CORR?/ADJ?`, `FMT/BC/TSC/TSR`, generic errors/status, WGFMU session/connect/abort/init, and GNDU as a standalone C category.

The strongest parts of Opus's list are its exhaustive SMU command coverage, explicit high-speed spot split (`TI/TV/TIV/TTI/TTV/TTIV`), explicit SMU sweep/pulse subcommands, WGFMU API completeness, and inclusion of niche but real P2 candidates such as quasi-pulse, signal monitor, timer-start source commands, and `HSS`.

Main arbitration issue: Opus's 105-candidate list is useful as a command coverage map, but too granular for the final MCP atom surface. Many entries should become parameters or sub-operations inside larger object-centered atoms.

## Opus Items To Adopt Into Final List

- Adopt `C_atom_smu_configure_quasi_pulse` as a P2 SMU candidate. My list only covered pulsed spot/sweep and did not explicitly include MM9 (`BDV/BDT/BDM`).
- Adopt `C_atom_smu_configure_signal_monitor` as P2, probably under `smu` or `smu_monitor`, for `DSMPLSETUP/DSMPLARM/DSMPLFLUSH` in MM27/MM28. It is measurement capture, not ordinary status.
- Adopt timer-start source variants as P2 parameters or submodes: SMU `TDI/TDV` and CMU `TACV/TDCV`. They should not be P0 standalone atoms, but source+timer semantics are real and useful for transient workflows.
- Adopt Opus's explicit note that `HSS` may be a P2 high-speed spot configuration. It should be folded into `C_atom_smu_measure_high_speed_spot` options unless real use proves it needs a separate atom.
- Adopt Opus's split of WGFMU `addVector` vs `setVector` only at schema level. Final atom can stay `C_atom_wgfmu_add_vectors` with `time_mode: incremental|absolute`, but Opus correctly reminds us both APIs exist.
- Adopt Opus's `C_atom_wgfmu_get_force_values` concept as A or C-adjacent validation output. It is useful to correlate measured data with forced waveform, but should not be P1 C unless final design treats measurement-specific readbacks as C.
- Adopt the stronger CMU primitive detail from Opus (`IMP`, `FC`, `ACV`, `DCV`, `ACT`, `RC`, `LMN`) into the schema for `C_atom_cmu_configure_impedance_measurement`.
- Adopt EasyEXPERT run modes (`single`, `append`, `repeat`) as a `run_mode` parameter of `C_atom_easyexpert_run_selected_test`; do not create separate atoms.

## Opus Items To Reject Or Downgrade

- Reject `C_atom_easyexpert_fetch_result` as C. Existing boundary says result format/fetch is A (`A_atom_easyexpert_fetch_result`); `RESult:FETch` is data retrieval from EasyEXPERT, not measurement execution.
- Downgrade `C_atom_smu_read_measurement_data`. Generic FLEX output-buffer read is A. Final C execute wrappers may return decoded data, but the reusable generic read atom should remain A.
- Downgrade `C_atom_smu_execute_measurement` if kept as a top-level generic atom. It is useful internally, but user requested object/unit-centered candidates; final surface should prefer `C_atom_smu_execute_spot`, `C_atom_smu_execute_staircase_sweep`, `C_atom_cmu_execute_cv_dc_sweep`, etc.
- Downgrade individual SMU setup atoms such as `C_atom_smu_set_integration_time`, `C_atom_smu_set_adc_type`, `C_atom_smu_set_averaging`, `C_atom_smu_set_measurement_ranging`, and `C_atom_smu_set_measurement_operation` into `C_atom_smu_configure_adc_and_ranges` plus `C_atom_smu_set_measurement_context`.
- Downgrade individual sweep atoms (`configure_sweep_voltage/current/timing/abort/sync/multi`) into `C_atom_smu_configure_staircase_sweep`, `C_atom_smu_configure_synchronous_sweep_source`, and `C_atom_smu_configure_multichannel_sweep_pulse` schemas.
- Downgrade individual pulse atoms (`configure_pulse_voltage/current`, `configure_pulsed_sweep_voltage/current`) into source-mode parameters of `C_atom_smu_configure_pulsed_spot_source` and `C_atom_smu_configure_pulsed_sweep`.
- Downgrade WGFMU individual range/mode atoms (`set_force_voltage_range`, `set_measure_mode`, `set_measure_current_range`, `set_measure_voltage_range`, `set_measure_enabled`) into one `C_atom_wgfmu_configure_force_measure_ranges`.
- Downgrade WGFMU `wait_completed` to A/control-flow or an option of `C_atom_wgfmu_execute_sequence`. Waiting does not define or execute a new measurement by itself.
- Downgrade SPGU `query_status` to A. It is plain status readback (`SPST?`), not C.
- Downgrade SPGU `stop_output` carefully. Intended stop of a pulse train is operational, but it is closer to B/output state than measurement. Keep only if SPGU command semantics distinguish normal programmed stop from safety abort.
- Downgrade SPGU `set_output_switch` (`ODSW`) to B/output/routing unless command-page review proves it directly defines pulse waveform generation rather than output path/state.
- Downgrade CMU individual `set_impedance_model`, `set_frequency`, `set_ac_level`, `set_dc_bias`, `set_integration_time`, `set_ranging`, and `set_monitor_output` into `C_atom_cmu_configure_impedance_measurement`.
- Downgrade CMU timer/high-speed helper variants (`TACV/TDCV/TMACV/TMDCV`) into options on `C_atom_cmu_measure_high_speed_spot_c`, not standalone atoms initially.
- Downgrade `C_atom_hvsmu_force_voltage/current`, `C_atom_hcsmu_force_voltage/current`, and `C_atom_uhcu_force_current/sweep_current` to resource-specialized schemas/wrappers unless final implementation needs separate safety envelopes. They reuse SMU commands and should not duplicate core SMU atoms blindly.

## Opus Missing Items

- Opus lacks explicit CMU execute atoms by measurement object/mode. Final list should include `C_atom_cmu_execute_spot_c`, `C_atom_cmu_execute_cv_dc_sweep`, `C_atom_cmu_execute_cf_sweep`, and optionally pulsed CV/C-t execute variants. Relying on generic `C_atom_smu_execute_measurement` weakens object-centered classification.
- Opus lacks explicit `hvmcu` and `uhvu` categories/candidates. N1266A HVMCU and N1268A UHVU are high-risk expander measurement surfaces; even if implemented as schemas over SMU commands, they need arbitration notes and B preconditions.
- Opus lacks `C_atom_easyexpert_run_quick_test_sequence` or equivalent batch/Quick Test classification. This can stay P2 or flow-level, but should be mentioned.
- Opus lacks `C_atom_spgu_execute_alwg_output` as a separate ALWG execution concept. It has ALWG configure atoms but mostly frames execution through update/start pulse output.
- Opus lacks my explicit `C_atom_smu_execute_spot`, `C_atom_smu_execute_staircase_sweep`, `C_atom_smu_execute_sampling`, `C_atom_smu_execute_search`, and `C_atom_smu_execute_qscv` mode-specific wrappers. These are better final MCP boundaries than generic `XE`.
- Opus lacks explicit final-rule emphasis that selector/path requirements for SPGU/HVSPGU (`ERSSP`, module selector, pulse switch) are B preconditions, never hidden inside C atoms.

## Priority Differences

- Opus promotes too many low-level configuration commands to P0. Final MVP should be smaller: SMU `DV/DI`, high-speed spot, spot, staircase sweep configure/execute, measurement context, ADC/range setup; WGFMU pattern/vector/sequence/measure-event/execute/read; and maybe CMU impedance setup only.
- Opus marks WGFMU `update` and `wait_completed` P0. I would make `update` P1/ambiguous and make `wait_completed` an execute option or A/control-flow helper.
- Opus makes CMU primitive setup P0 but has no CMU execute P0/P1. Final arbitration should prioritize at least one executable CMU measurement path over many separate CMU setters.
- Opus makes EasyEXPERT fetch P1 C. It should be A, while EasyEXPERT `run_selected_test` remains P1 C-like.
- Opus puts SMU timestamped high-speed spot as P1 separate atoms. I would keep timestamped mode as a parameter of `C_atom_smu_measure_high_speed_spot`; separate atoms are not needed.
- Opus lists SPGU as all P1/P2 with no P0. I agree: SPGU should not displace SMU/WGFMU MVP unless NVM/PCRAM pulse workflows are the immediate target.

## Naming / Classification Recommendations

- Prefer final names that describe measurement intent, not one command per atom: `configure_staircase_sweep` over `configure_sweep_voltage`; `measure_high_speed_spot` over six `spot_measure_*` variants.
- Keep object/unit prefix strict: CMU execution should use `C_atom_cmu_*`, even if the final low-level trigger is `XE`; high-power expander wrappers should use `hvsmu/hcsmu/uhcu/hvmcu/uhvu` only when validation differs materially.
- Use parameters for source mode (`voltage|current`), measure type (`i|v|iv`), timestamped output, sweep kind, and EasyEXPERT run mode.
- Keep parser and data transport A-class by default. C atoms may return decoded measurement data as a convenience, but the underlying generic output-buffer and EasyEXPERT result fetch primitives should remain A.
- Treat `CMM`, `WM`, `MSC`, `MSP`, `WMDCV/WMFC/WMACV` as C only when included in a measurement configuration schema. Do not expose them as standalone safety/config atoms unless necessary.
- Treat WGFMU pattern functions as C despite being offline because they define the waveform and measurement event surface. Treat WGFMU setup readbacks as A unless included in validation output.

## Recommended Final Arbitration Notes

- Final list should combine GPT's coarser MCP-safe boundaries with Opus's command completeness. Use Opus's 105 items as a coverage checklist, not as final public tool count.
- Add from Opus: quasi-pulse, DSMPL signal monitor, timer-start source/CMU commands, HSS option, and explicit WGFMU force-value correlation readback.
- Remove or reclassify from Opus: EasyEXPERT result fetch, SPGU status query, generic SMU read buffer, WGFMU wait as C, and most one-command setter atoms.
- Prefer final count closer to 70-80 candidates if adding Opus's useful omissions, not 105. The extra value is coverage of niche modes; the risk is an over-fragmented MCP surface.
- For first implementation, keep P0 small and SMU-first. Implement broad schemas with strict A/B preconditions rather than many command-thin atoms.
- Document that high-voltage/high-current/expander C candidates are wrapper schemas over SMU commands with mandatory B preflight, fixture acknowledgement, routing setup, and interlock validation.
