# C Atom Arbitration

Date: 2026-06-22

Inputs:

- `tmp/c_atom_candidates_opus46.md`
- `tmp/c_atom_candidates_gpt55.md`
- `tmp/c_atom_cross_review_opus_on_gpt.md`
- `tmp/c_atom_cross_review_gpt_on_opus.md`

Status: planning/arbitration only. Do not implement from this file without a separate implementation task.

## Arbitration Principle

Use an object/unit-centered taxonomy as requested:

- `C_atom_smu_*`
- `C_atom_wgfmu_*`
- `C_atom_spgu_*`
- `C_atom_cmu_*`
- `C_atom_hvsmu_*`
- `C_atom_hcsmu_*`
- `C_atom_uhcu_*`
- `C_atom_hvmcu_*`
- `C_atom_uhvu_*`
- `C_atom_easyexpert_*`

Do not expose one atom per manual command when the command is usually just a parameter of a coherent measurement primitive. Conversely, do not over-bundle execute + wait + data-read into one atom when asynchronous execution and polling matter.

Recommended model:

- **C atoms**: reusable measurement/source/configuration/execution/data-read primitives.
- **Future C flows**: convenience recipes such as spot IV, staircase IV, C-V sweep, WGFMU pulse run, etc.

## Boundary Rules

| Stays A | Stays B | C |
|---|---|---|
| Sessions, identity, module discovery, status/error queues, parser/buffer plumbing, result fetch from existing EasyEXPERT result | Reset/init/abort, channel enable/disable/zero, interlock, self-test/calibration, path switching, CMU correction, phase comp, QSCV offset, ASU/SCUU | Source/force, measurement context, ranging/integration, measurement-mode setup, waveform/pulse definition, execute, measurement-specific data read |

Important decisions:

- `AIT`, `AAD`, `AV`, `RI`, `RV`, `RM`, `CMM` are C because they directly shape measurement quality/outcome.
- `FMT`, `TSC`, `TSR`, `BC`, `NUB?`, generic output-buffer read stay A.
- `CORR?`, `CORRST`, `ADJ`, `ADJ?`, `QSZ` stay B despite looking measurement-like, because they are correction/calibration-state operations.
- `EasyEXPERT RUN` is C-like software-mediated execution. `EasyEXPERT RESult:FETch` remains A.
- GNDU is topology/reference, not a C atom category for now.

## P0 MVP C Atoms

These should be considered the first C implementation wave.

### SMU P0

| Atom | Role |
|---|---|
| `C_atom_smu_set_measurement_mode` | Set `MM` measurement mode and channels. |
| `C_atom_smu_set_measurement_operation` | Set per-channel `CMM` operation when needed. |
| `C_atom_smu_configure_integration` | Configure ADC/integration/averaging (`AAD`, `AIT`, `AV`, optional `PAD`). |
| `C_atom_smu_set_measurement_ranging` | Configure SMU current/voltage measurement ranges (`RI`, `RV`, `RM`). |
| `C_atom_smu_force_voltage` | Force DC voltage (`DV`). |
| `C_atom_smu_force_current` | Force DC current (`DI`). |
| `C_atom_smu_measure_high_speed_spot` | High-speed spot I/V/IV with type/timestamp parameters (`TI`, `TV`, `TIV`, optional `TT*`). |
| `C_atom_smu_configure_staircase_sweep` | Configure primary staircase sweep (`WV`/`WI`) without executing. |
| `C_atom_smu_configure_sweep_timing` | Configure sweep timing (`WT`). |
| `C_atom_smu_execute` | Trigger current configured measurement (`XE`) without forcing data-read bundling. |
| `C_atom_smu_read_measurement_data` | Measurement-specific decode/read wrapper over existing A buffer primitives. |
| `C_atom_smu_configure_pulse_timing` | Configure SMU pulse timing (`PT`). |
| `C_atom_smu_configure_pulsed_spot_source` | Configure pulsed spot source (`PV`/`PI`) after `PT`. |

### WGFMU P0

| Atom | Role |
|---|---|
| `C_atom_wgfmu_set_operation_mode` | Set channel operation mode. |
| `C_atom_wgfmu_configure_force_measure_ranges` | Configure force/measure modes and ranges. |
| `C_atom_wgfmu_create_pattern` | Create waveform pattern. |
| `C_atom_wgfmu_add_vectors` | Append/add waveform vectors. |
| `C_atom_wgfmu_add_sequence` | Assign patterns to channel sequences. |
| `C_atom_wgfmu_set_measure_event` | Define measurement events. |
| `C_atom_wgfmu_update` | Apply waveform setup / output initial voltage. P0 despite C/B ambiguity because it is required before execute. |
| `C_atom_wgfmu_execute` | Execute WGFMU sequence. |
| `C_atom_wgfmu_read_measurement_values` | Read WGFMU measurement arrays. |

### CMU P0

| Atom | Role |
|---|---|
| `C_atom_cmu_set_impedance_model` | Set impedance model (`IMP`). |
| `C_atom_cmu_configure_signal` | Configure frequency, AC level, DC bias (`FC`, `ACV`, `DCV`). |
| `C_atom_cmu_set_ranging_integration` | Configure CMU range/integration (`RC`, `ACT`). |
| `C_atom_cmu_configure_cv_dc_sweep` | Configure DC-bias C-V sweep (`WDCV`, timing/abort parameters). |
| `C_atom_cmu_execute` | Trigger configured CMU measurement (`XE`) without bundling data read. |

## P1 C Atoms

### SMU P1

| Atom | Role |
|---|---|
| `C_atom_smu_configure_sweep_abort` | Configure sweep abort/post-output (`WM`). |
| `C_atom_smu_configure_synchronous_sweep_source` | Configure synchronous sweep sources (`WSV`, `WSI`). |
| `C_atom_smu_configure_pulsed_sweep` | Configure pulsed sweep (`PWV`, `PWI`). |
| `C_atom_smu_execute_pulsed_spot` | Execute pulsed spot mode. |
| `C_atom_smu_execute_pulsed_sweep` | Execute pulsed sweep mode. |
| `C_atom_smu_configure_sampling` | Configure sampling (`MCC`, `ML`, `MT`, `MSC`, `MI`, `MV`, `MSP`). |
| `C_atom_smu_execute_sampling` | Execute sampling mode. |
| `C_atom_smu_configure_multi_sweep` | Configure multi-channel sweep (`WNX`). |
| `C_atom_smu_configure_multi_pulsed` | Configure multi-channel pulsed spot/sweep (`MCPT`, `MCP*`). |

### WGFMU P1

| Atom | Role |
|---|---|
| `C_atom_wgfmu_set_vectors` | Absolute-time vector set/update. |
| `C_atom_wgfmu_transform_pattern` | Merge/multiply/offset patterns. |
| `C_atom_wgfmu_set_range_event` | Define range-change event. |
| `C_atom_wgfmu_set_trigger_event` | Define trigger output event. |
| `C_atom_wgfmu_configure_force_measure_delay` | Configure force/measurement delay. |
| `C_atom_wgfmu_read_force_values` | Measurement-adjacent force waveform readback/correlation. |
| `C_atom_wgfmu_dc_force_measure` | DC force + measure convenience atom. |
| `C_atom_wgfmu_dc_measure_averaged` | Averaged DC measurement. |

### SPGU P1

| Atom | Role |
|---|---|
| `C_atom_spgu_set_operation_mode` | Set PG/ALWG operation mode (`SIM`). |
| `C_atom_spgu_configure_pg_pulse` | Configure pulse mode/period/timing/voltage/load (`SPM`, `SPPER`, `SPT`, `SPV`, `SPRM`). |
| `C_atom_spgu_update_output` | Apply SPGU settings (`SPUPD`). |
| `C_atom_spgu_start_output` | Start SPGU pulse output (`SRP`). |
| `C_atom_spgu_stop_output` | Stop SPGU pulse output (`SPP`) if treated as normal pulse-run stop, not safety abort. |

### CMU P1

| Atom | Role |
|---|---|
| `C_atom_cmu_measure_high_speed_spot` | Spot C/impedance high-speed measurement (`TC`, optional `TTC`, `TMACV`, `TMDCV`). |
| `C_atom_cmu_execute_spot_c` | Execute normal Spot C (`MM17`, `XE`). |
| `C_atom_cmu_execute_cv_dc_sweep` | Execute DC-bias C-V sweep (`MM18`, `XE`). |
| `C_atom_cmu_configure_cf_sweep` | Configure C-f sweep (`WFC`, timing/abort parameters). |
| `C_atom_cmu_execute_cf_sweep` | Execute C-f sweep (`MM22`, `XE`). |

### High-Power / Software P1

| Atom | Role |
|---|---|
| `C_atom_hvsmu_set_operation_mode` | HVSMU operation mode (`HVSMUOP`). |
| `C_atom_easyexpert_run_selected_test` | Execute selected EasyEXPERT setup/application test. |

## P2 / Later C Atoms

| Category | Atoms / Concepts |
|---|---|
| SMU advanced | quasi-pulse (`BD*`), linear/binary search (`LS*`, `BS*`), signal monitor (`DSMPL*`), timer-start source variants (`TDI`, `TDV`). |
| WGFMU advanced | event-specific partial read, full ALWG-cycle composites, detailed force-read interpolation. |
| SPGU advanced | ALWG pattern/sequence, trigger output, status/query readbacks (status likely A). |
| CMU advanced | AC-level sweep, pulsed Spot C, pulsed CV sweep, C-t sampling, timer-start CMU helpers (`TACV`, `TDCV`). |
| High-power wrappers | `C_atom_hvsmu_execute_iv`, `C_atom_hcsmu_execute_iv`, `C_atom_uhcu_execute_iv`, `C_atom_hvmcu_execute_iv`, `C_atom_uhvu_execute_iv` as schema/validation wrappers over SMU-family primitives, not separate low-level command paths. |
| EasyEXPERT advanced | quick-test sequence / repeat run as future C_flow or C_atom depending on remote API behavior. |

## Rejected / Reclassified

| Candidate | Decision |
|---|---|
| `C_atom_easyexpert_fetch_result` | A, not C. Result fetch already exists as A. |
| Generic FLEX output-buffer read | A, not C. C-specific decode wrappers may call A primitives. |
| `CN`, `CL`, `DZ`, `RZ`, `WZ?` | B output/safety. |
| `AB`, `*RST`, `IN`, `*TST?`, `*CAL?`, `DIAG?` | B lifecycle/diagnostic/calibration. |
| `SAP`, `SAR`, `SSP`, selector/routing/DIO path setup | B routing/state-control. |
| `CORR?`, `CORRST`, `ADJ`, `ADJ?`, `QSZ` | B correction/calibration, not C. |
| WGFMU session/connect/disconnect/abort/init/error/warning/status | A/B as already implemented. |
| SPGU status/query-only commands | A unless inseparable from execution wrapper. |
| HVSMU/HCSMU `execute_*` duplicates | Do not duplicate low-level SMU command atoms; use resource-specific schemas/flows when validation differs. |
| GNDU C atoms | Reject for now; GNDU is reference/topology, not independently controllable measurement/source unit. |

## Major Ambiguities

1. `WGFMU_update` is C in this arbitration because it applies source setup / initial output and is required before execute, but it has B-like output-state risk.
2. Generic execute/data-read split: first implementation should keep execute and data read separate for async/polling, but future ergonomic C_flow may combine them.
3. CMU setup granularity: split into impedance model / signal / ranging-integration instead of one huge atom.
4. EasyEXPERT `RUN` is C-like but software-mediated; it should remain clearly separate from direct hardware C atoms.
5. High-power expander categories are validation wrappers over SMU semantics until their command pages are extracted in detail.
