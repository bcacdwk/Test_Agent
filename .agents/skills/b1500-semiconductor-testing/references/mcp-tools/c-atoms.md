# C Atom MCP Tools

C atoms are reusable measurement/source/configuration/execution/data-read primitives. They sit above
A-class readback/session atoms and B-class safety/state-control atoms, but below future ergonomic C flows.

```text
C_atom_<object>_<action>
```

Objects: `smu`, `wgfmu`, `spgu`, `cmu`, `hvsmu`, `hcsmu`, `uhcu`, `hvmcu`, `uhvu`, `easyexpert`.

All C atoms in this server are fake discovery surfaces only. They return `fake: true` and
`hardware_touched: false`; they do not execute real hardware or EasyEXPERT operations.

## C Class Atom Tools — smu

| Tool | Meaning | Basis |
|---|---|---|
| `C_atom_smu_set_measurement_mode` | Set SMU measurement mode and channels. | `MM` |
| `C_atom_smu_set_measurement_operation` | Set per-channel source/measure operation. | `CMM` |
| `C_atom_smu_configure_integration` | Configure ADC, integration, averaging, and optional delay. | `AAD`, `AIT`, `AV`, `PAD` |
| `C_atom_smu_set_measurement_ranging` | Configure current/voltage measurement ranging. | `RI`, `RV`, `RM` |
| `C_atom_smu_force_voltage` | Force DC voltage with compliance, polarity, and explicit `irange`. | `DV` |
| `C_atom_smu_force_current` | Force DC current with compliance and polarity. | `DI` |
| `C_atom_smu_measure_high_speed_spot` | Measure high-speed spot I/V/IV with timestamp option. | `TI`, `TV`, `TIV`, `TT*` |
| `C_atom_smu_configure_staircase_sweep` | Configure primary staircase sweep (linear/log + compliance polarity). | `WV`, `WI` |
| `C_atom_smu_configure_sweep_timing` | Configure sweep timing (hold/delay/step/trigger/measure delays). | `WT` |
| `C_atom_smu_execute` | Trigger the configured measurement. | `XE` |
| `C_atom_smu_read_measurement_data` | Measurement-specific output-buffer decode wrapper. | output data buffer read |
| `C_atom_smu_configure_pulse_timing` | Configure SMU pulse timing. | `PT` |
| `C_atom_smu_configure_pulsed_spot_source` | Configure pulsed spot voltage/current source. | `PV`, `PI` |
| `C_atom_smu_configure_sweep_abort` | Configure sweep abort/post-output behavior. | `WM` |
| `C_atom_smu_configure_synchronous_sweep_source` | Configure synchronous sweep source. | `WSV`, `WSI` |
| `C_atom_smu_configure_pulsed_sweep` | Configure pulsed sweep. | `PWV`, `PWI` |
| `C_atom_smu_execute_pulsed_spot` | Execute configured pulsed spot mode. | `MM`, `XE` |
| `C_atom_smu_execute_pulsed_sweep` | Execute configured pulsed sweep mode. | `MM`, `XE` |
| `C_atom_smu_configure_sampling` | Configure SMU sampling setup. | `MCC`, `ML`, `MT`, `MSC`, `MI`, `MV`, `MSP` |
| `C_atom_smu_execute_sampling` | Execute configured sampling mode. | `MM`, `XE` |
| `C_atom_smu_configure_multi_sweep` | Configure multi-channel sweep. | `WNX` |
| `C_atom_smu_configure_multi_pulsed` | Configure multi-channel pulsed spot/sweep. | `MCPT`, `MCP*` |
| `C_atom_smu_configure_quasi_pulse` | Configure quasi-pulse source settings. | `BD*` |
| `C_atom_smu_configure_search` | Configure linear/binary search measurement. | `LS*`, `BS*` |
| `C_atom_smu_configure_signal_monitor` | Configure signal-monitor acquisition. | `DSMPL*` |
| `C_atom_smu_force_timer_start_voltage` | Source voltage using timer-start variant. | `TDV` |
| `C_atom_smu_force_timer_start_current` | Source current using timer-start variant. | `TDI` |
| `C_atom_smu_configure_qscv` | Configure quasi-static CV (MM 13) source/timing/measurement. | `QSV`, `QST`, `QSM`, `QSL`, `QSO`, `QSC`, `QSR` |
| `C_atom_smu_execute_qscv` | Execute quasi-static CV. | `MM13`, `XE` |
| `C_atom_smu_configure_staircase_sweep_pulsed_bias` | Configure staircase sweep with pulsed bias (MM 5). | `WV`/`WI`, `PT`, `PV`/`PI` |
| `C_atom_smu_set_parallel_measurement` | Enable parallel A/D conversion and select channels. | `PAD`, `PCH` |
| `C_atom_smu_configure_trigger_io` | Configure trigger input/output ports for sync. | `TGP`, `TGPC`, `TGSI`, `TGSO`, `TGXO`, `TGMO` |
| `C_atom_smu_set_trigger_mode` | Set per-channel trigger function (start/step). | `TM` |
| `C_atom_smu_configure_high_speed_spot` | Select standard high-speed spot measurement. | `HSS` |

## C Class Atom Tools — wgfmu

| Tool | Meaning | Basis |
|---|---|---|
| `C_atom_wgfmu_set_operation_mode` | Set WGFMU channel operation mode (DC/FASTIV/PG/SMU constants). | `WGFMU_setOperationMode` |
| `C_atom_wgfmu_configure_force_measure_ranges` | Configure force voltage + measure current ranges (constants). | `WGFMU_setForceVoltageRange`, `WGFMU_setMeasureCurrentRange` |
| `C_atom_wgfmu_set_measure_mode` | Set measurement mode (voltage/current). | `WGFMU_setMeasureMode` |
| `C_atom_wgfmu_set_measure_voltage_range` | Set voltage measurement range (5V/10V). | `WGFMU_setMeasureVoltageRange` |
| `C_atom_wgfmu_set_measure_enabled` | Enable/disable measurement per channel. | `WGFMU_setMeasureEnabled` |
| `C_atom_wgfmu_set_trigger_out_mode` | Set trigger output mode + polarity (prereq for trigger event). | `WGFMU_setTriggerOutMode` |
| `C_atom_wgfmu_create_pattern` | Create a waveform pattern (unique name; 2048-vector limit). | `WGFMU_createPattern` |
| `C_atom_wgfmu_add_vectors` | Append waveform vectors (dTime 10 ns-10995 s, +/-10 V). | `WGFMU_addVector(s)` |
| `C_atom_wgfmu_add_sequence` | Assign pattern to channel sequence (loop up to ~1e12). | `WGFMU_addSequence` |
| `C_atom_wgfmu_set_measure_event` | Define measurement event (points/interval/average/rdata). | `WGFMU_setMeasureEvent` |
| `C_atom_wgfmu_update` | Apply waveform setup / initial output. | `WGFMU_update` |
| `C_atom_wgfmu_execute` | Execute configured WGFMU sequence. | `WGFMU_execute` |
| `C_atom_wgfmu_read_measurement_values` | Read WGFMU measurement arrays. | measure value APIs |
| `C_atom_wgfmu_set_vectors` | Set absolute-time vectors. | `WGFMU_setVector(s)` |
| `C_atom_wgfmu_transform_pattern` | Merge/multiply/offset patterns. | pattern transform APIs |
| `C_atom_wgfmu_set_range_event` | Define current range-change event (constants + spacing). | `WGFMU_setRangeEvent` |
| `C_atom_wgfmu_set_trigger_event` | Define trigger output event (with duration). | `WGFMU_setTriggerOutEvent` |
| `C_atom_wgfmu_configure_force_measure_delay` | Configure force/measure delay (+/-50 ns, 625 ps res). | `WGFMU_setForceDelay`, `WGFMU_setMeasureDelay` |
| `C_atom_wgfmu_read_force_values` | Read force waveform values. | force value APIs |
| `C_atom_wgfmu_dc_force_measure` | DC force and measure convenience atom. | `WGFMU_dcforceVoltage`, `WGFMU_dcmeasureValue` |
| `C_atom_wgfmu_dc_measure_value` | Single-point DC measurement (non-averaged). | `WGFMU_dcmeasureValue` |
| `C_atom_wgfmu_dc_measure_averaged` | Averaged DC measurement (points/interval). | `WGFMU_dcmeasureAveragedValue` |
| `C_atom_wgfmu_read_measurement_values_partial` | Read event-specific partial measurement data. | measure value APIs |
| `C_atom_wgfmu_configure_alwg_cycle` | Configure an ALWG-style pattern cycle. | pattern + sequence APIs |

## C Class Atom Tools — spgu

| Tool | Meaning | Basis |
|---|---|---|
| `C_atom_spgu_set_operation_mode` | Set PG/ALWG operation mode. | `SIM` |
| `C_atom_spgu_set_load_impedance` | Set DUT load impedance (affects output voltage). | `SER` |
| `C_atom_spgu_configure_pg_pulse` | Configure PG pulse mode/edges/delay/source/3-level voltage. | `SPM`, `SPPER`, `SPT`, `SPV`, `SPRM` |
| `C_atom_spgu_update_output` | Apply SPGU settings. | `SPUPD` |
| `C_atom_spgu_start_output` | Start SPGU pulse output (free-run or N pulses). | `SRP` |
| `C_atom_spgu_stop_output` | Stop normal SPGU pulse output. | `SPP` |
| `C_atom_spgu_create_alwg_pattern` | Define ALWG pattern data (levels + channel). | `ALW` |
| `C_atom_spgu_add_alwg_sequence` | Assign ALWG pattern sequence (with loop control). | `ALS` |
| `C_atom_spgu_configure_sampling_pulse` | Configure SPGU pulse for SMU sampling (MM 10). | `MSP` |
| `C_atom_spgu_set_trigger_output` | Configure trigger output (port/type/polarity). | `STGP` |

## C Class Atom Tools — cmu

| Tool | Meaning | Basis |
|---|---|---|
| `C_atom_cmu_set_impedance_model` | Set impedance model (with channel). | `IMP` |
| `C_atom_cmu_configure_signal` | Configure frequency, AC level, DC bias (with channel + limits). | `FC`, `ACV`, `DCV` |
| `C_atom_cmu_set_ranging_integration` | Configure CMU range and integration (with channel + fixed range). | `RC`, `ACT` |
| `C_atom_cmu_set_monitor_output` | Enable actual AC level / DC bias monitor output. | `LMN` |
| `C_atom_cmu_read_measurement_data` | CMU-specific output-buffer decode wrapper. | output data buffer read |
| `C_atom_cmu_configure_cv_dc_sweep` | Configure DC-bias C-V sweep (MM 18). | `WDCV`, `WTDCV`, `WMDCV` |
| `C_atom_cmu_execute` | Trigger configured CMU measurement. | `XE` |
| `C_atom_cmu_measure_high_speed_spot` | Measure high-speed spot C/impedance. | `TC`, `TTC`, `TMACV`, `TMDCV` |
| `C_atom_cmu_execute_spot_c` | Execute normal Spot C. | `MM17`, `XE` |
| `C_atom_cmu_execute_cv_dc_sweep` | Execute DC-bias C-V sweep. | `MM18`, `XE` |
| `C_atom_cmu_configure_cf_sweep` | Configure C-f sweep (MM 22). | `WFC`, `WTFC`, `WMFC` |
| `C_atom_cmu_execute_cf_sweep` | Execute C-f sweep. | `MM22`, `XE` |
| `C_atom_cmu_configure_ac_level_sweep` | Configure AC-level sweep (MM 23). | `WACV`, `WTACV`, `WMACV` |
| `C_atom_cmu_execute_ac_level_sweep` | Execute AC-level sweep. | `MM23`, `XE` |
| `C_atom_cmu_configure_pulsed_spot_c` | Configure pulsed Spot C (MM 19). | `PTDCV`, `PDCV` |
| `C_atom_cmu_execute_pulsed_spot_c` | Execute pulsed Spot C. | `MM19`, `XE` |
| `C_atom_cmu_configure_pulsed_cv_sweep` | Configure pulsed C-V sweep (MM 20). | `PWDCV`, `PTDCV` |
| `C_atom_cmu_execute_pulsed_cv_sweep` | Execute pulsed C-V sweep. | `MM20`, `XE` |
| `C_atom_cmu_configure_ct_sampling` | Configure capacitance-time sampling (MM 26). | `MDCV`, `MTDCV` |
| `C_atom_cmu_execute_ct_sampling` | Execute capacitance-time sampling. | `MM26`, `XE` |
| `C_atom_cmu_measure_timer_start_ac_voltage` | Timer-start AC-level CMU measurement helper. | `TACV` |
| `C_atom_cmu_measure_timer_start_dc_voltage` | Timer-start DC-bias CMU measurement helper. | `TDCV` |

## C Class Atom Tools — high power wrappers

These are object-specific schema/validation wrappers over SMU-family primitives. They are not separate
low-level command paths.

| Tool | Meaning | Basis |
|---|---|---|
| `C_atom_hvsmu_set_operation_mode` | Set HVSMU operation mode. | `HVSMUOP` |
| `C_atom_hvsmu_execute_iv` | Execute HVSMU IV wrapper. | `HVSMUOP`, SMU IV wrapper |
| `C_atom_hcsmu_execute_iv` | Execute HCSMU IV wrapper. | HCSMU IV wrapper |
| `C_atom_uhcu_execute_iv` | Execute UHC expander IV wrapper. | UHC expander IV wrapper |
| `C_atom_hvmcu_execute_iv` | Execute HVMC expander IV wrapper. | HVMC expander IV wrapper |
| `C_atom_uhvu_execute_iv` | Execute UHV expander IV wrapper. | UHV expander IV wrapper |

## C Class Atom Tools — easyexpert

| Tool | Meaning | Basis |
|---|---|---|
| `C_atom_easyexpert_run_selected_test` | Execute selected EasyEXPERT setup/application test. | `:BENCh:SELected:RUN` |
| `C_atom_easyexpert_run_quick_test_sequence` | Execute quick-test sequence. | `:QUICKTest:RUN` |
| `C_atom_easyexpert_repeat_run_selected_test` | Repeat selected EasyEXPERT test. | `:BENCh:COUNt`, run |

## Rejected / Reclassified Boundaries

These were intentionally not implemented as C atoms:

- EasyEXPERT result fetch and generic FLEX output-buffer read remain A atoms.
- `CN`, `CL`, `DZ`, `RZ`, `WZ?`, reset/init/abort/self-test/calibration/diagnostic commands remain B atoms.
- Selector, DIO, ASU/SCUU, correction, calibration, and routing state changes remain B atoms.
- WGFMU session/connect/disconnect/abort/init/status/error/warning/logging remain A/B atoms.
- SPGU status/query-only commands remain A atoms (incl. `SER?`, `STGP?`, `SOPC?`, `SOVC?`, `ALW?`, `ALS?`).
- SPGU compensation (`SOPC`/`SOVC`) and series correction (`CORRSER?`) are B correction atoms; SPGU load impedance (`SER`) is a C source-config atom.
- MFCMU correction readbacks (`CORRST?`, `CORRL?`, `CORRDT?`, `DCORR?`) are A; the write/measure forms (`CORRL`, `DCORR`, `CORRDT`, `CORRSER?`) are B correction atoms.
- GNDU standalone C atoms remain rejected for now.
