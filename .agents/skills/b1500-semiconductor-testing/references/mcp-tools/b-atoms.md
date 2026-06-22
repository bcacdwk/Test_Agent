# B Atom MCP Tools

B atoms are safety/state-control tools categorized by risk or operation type.

```text
B_atom_<risk_category>_<target>_<action>
```

Categories: `safety`, `output`, `lifecycle`, `diagnostic`, `calibration`, `routing`, `correction`, `policy`.
Targets: `b1500`, `smu`, `asu`, `scuu`, `cmu`, `qscv`, `wgfmu`, `easyexpert`.

## B Class Atom Tools — safety

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_safety_b1500_abort` | Abort active B1500A operation. | `AB` | Follow with cleanup and error readback in real flow. |
| `B_atom_safety_b1500_check_interlock` | Check high-voltage interlock state. | `INTLKVTH?` / safety docs | Exact command semantics need real validation. |
| `B_atom_safety_b1500_set_interlock_threshold` | Set high-voltage interlock allowable-voltage threshold. | `INTLKVTH` | Write side of interlock check; set to the +/-42 V station envelope. |
| `B_atom_safety_b1500_preflight` | Aggregate readiness and safety checks. | `UNT?`, `ERRX?`, `*STB?`, `*LRN?`, interlock check | Standard gate before measurement atoms. |
| `B_atom_safety_easyexpert_abort_measurement` | Abort selected EasyEXPERT measurement. | `[:BENCh][:SELected]:ABORt` | Remote safety/cancel atom. |

## B Class Atom Tools — output

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_output_b1500_enable_channels` | Enable output/measurement channels. | `CN` | State-changing; validate channel map first. |
| `B_atom_output_b1500_disable_channels` | Disable channels. | `CL` | Empty input means all. |
| `B_atom_output_b1500_zero_outputs` | Force selected/all outputs to 0 V. | `DZ` | Safety cleanup primitive. |
| `B_atom_output_b1500_zero_all` | Force 0 V and disable all channels. | `DZ`, `CL` | Emergency-style cleanup atom. |
| `B_atom_output_b1500_confirm_zero` | Confirm output is near zero. | `WZ?` | Useful before contact/re-cabling. |
| `B_atom_output_b1500_recover_zeroed` | Restore settings saved by `DZ`. | `RZ` | Requires prior `DZ`; otherwise B1500A can report an error. |
| `B_atom_output_spgu_enable_channels` | Enable SPGU output channels. | `CNX` | SPGU/HVSPGU output switch state change. |
| `B_atom_output_smu_set_filter` | Set SMU filter state. | `FL` | Initial setting is off. |
| `B_atom_output_smu_set_series_resistor` | Set SMU series resistor state. | `SSR` | Initial setting is off; paired with FL. |
| `B_atom_output_smu_set_compliance_limit` | Set SMU compliance polarity/limit. | `LIM` | Restricts compliance side; prevents bipolar compliance search for HRSMU leakage. |
| `B_atom_output_smu_set_output_switch_type` | Set SMU output switch type (normal/trigger-sync). | `OSX`, `OS` | `OS` obsolete; `OSX` adds external-trigger synchronized output. |
| `B_atom_output_dio_set_relay_bits` | Drive external relay control output bits. | `ERC` | Can affect external relay/trigger hardware. |
| `B_atom_output_wgfmu_connect` | Enable WGFMU channel and connected RSU. | `WGFMU_connect` | B-class: enables channel output through RSU. |
| `B_atom_output_wgfmu_disconnect` | Disable WGFMU channel and connected RSU. | `WGFMU_disconnect` | B-class: disables channel output. |
| `B_atom_output_easyexpert_set_standby` | Set EasyEXPERT standby state. | `:STANDby:STATe` | Bias/standby state control. |

## B Class Atom Tools — lifecycle

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_lifecycle_b1500_reset` | Reset B1500A to initial settings. | `*RST` | Must not be concatenated with other commands. |
| `B_atom_lifecycle_b1500_initialize` | Initialize instrument state. | `IN` | Dedicated safety/state-control atom. |
| `B_atom_lifecycle_wgfmu_initialize` | Reset all WGFMU channels. | `WGFMU_initialize` | WGFMU state-control atom. |
| `B_atom_lifecycle_wgfmu_abort` | Stop WGFMU sequencer on all channels. | `WGFMU_abort` | B-class: abort/safety primitive. Channels keep output voltage at moment of abort. |
| `B_atom_lifecycle_wgfmu_abort_channel` | Stop WGFMU sequencer on one channel. | `WGFMU_abortChannel` | Per-channel abort; others keep running. Channel keeps output voltage. |

## B Class Atom Tools — diagnostic

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_diagnostic_b1500_self_test` | Run B1500A self-test. | `*TST?` | Safety/diagnostic atom. |
| `B_atom_diagnostic_b1500_diagnostics` | Run diagnostics item. | `DIAG?` | Item map needs further extraction. |
| `B_atom_diagnostic_wgfmu_self_test` | Run WGFMU/mainframe self-test. | `WGFMU_doSelfTest` | Returns bitmask-style pass/fail result in real API. |

## B Class Atom Tools — calibration

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_calibration_b1500_self_calibration` | Run B1500A self-calibration. | `*CAL?` | Record in metadata. |
| `B_atom_calibration_smu_set_adc_zero` | Set SMU ADC zero function. | `AZ` | Initial setting is off. |
| `B_atom_calibration_wgfmu_self_calibration` | Run WGFMU/mainframe self-calibration. | `WGFMU_doSelfCalibration` | Timeout may be raised to 600 s. |
| `B_atom_calibration_easyexpert_zero_cancel_on` | Enable EasyEXPERT SMU zero cancel. | CALibration `ON` / `ON:ALL` | Calibration state atom. |
| `B_atom_calibration_easyexpert_zero_cancel_off` | Disable EasyEXPERT SMU zero cancel. | CALibration `OFF:ALL` | Calibration state atom. |
| `B_atom_calibration_easyexpert_measure_zero_cancel` | Measure EasyEXPERT SMU zero-cancel data. | CALibration `MEASure` | Zero-cancel calibration workflow. |
| `B_atom_calibration_easyexpert_query_zero_cancel_state` | Query EasyEXPERT zero-cancel state. | CALibration `STATe?` | Readback for calibration state. |

## B Class Atom Tools — routing

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_routing_asu_set_path` | Switch ASU path. | `SAP` | Requires ASU topology and DUT safety validation. |
| `B_atom_routing_asu_set_1pa_range` | Enable/disable ASU 1 pA auto-ranging. | `SAR` | Needed for atto/pA-class current workflows. |
| `B_atom_routing_asu_set_indicator` | Set ASU indicator state. | `SAL` | UI/fixture state indicator atom. |
| `B_atom_routing_scuu_set_path` | Switch SCUU path between open/SMU/CMU modes. | `SSP` | Use `SSP` rather than `CN` for SCUU modules. |
| `B_atom_routing_scuu_set_indicator` | Set SCUU indicator state. | `SSL` | UI/fixture state indicator atom. |
| `B_atom_routing_spgu_set_pulse_switch` | Set SPGU pulse output switch (with delay/width). | `ODSW` | Physical pulse relay path to DUT; own timing envelope. |
| `B_atom_routing_selector_set_mode` | Set module selector / DIO operation mode. | `ERMOD` | Prerequisite for selector and expander ER* routing. |
| `B_atom_routing_selector_set_smu_pg_path` | Switch 16440A SMU/PG selector path. | `ERSSP` | Physical relay path between SMU and PG/SPGU. |
| `B_atom_routing_dio_set_mode` | Set DIO bit direction/mode. | `ERM` | Infrastructure state for relay/selector control. |

## B Class Atom Tools — correction

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_correction_cmu_set_correction` | Enable/disable CMU open/short/load correction. | `CORRST`, `CORRST?` | `OPEN`/`SHOR`/`LOAD` are type labels, not standalone commands. |
| `B_atom_correction_cmu_measure_data` | Measure CMU open/short/load correction data. | `CORR?` | Real implementation must require correct fixture condition. |
| `B_atom_correction_cmu_set_phase_mode` | Select MFCMU phase compensation mode. | `ADJ` | Often prerequisite for `ADJ?`. |
| `B_atom_correction_cmu_perform_phase_comp` | Perform MFCMU phase compensation. | `ADJ?` | Manual notes open measurement terminals and ~30 s operation. |
| `B_atom_correction_cmu_clear` | Clear CMU correction data. | `CLCORR` | Correction state reset atom. |
| `B_atom_correction_cmu_add_frequency` | Add a frequency to the MFCMU correction set. | `CORRL` | Register all test frequencies (1 kHz-1 MHz) before `CORR?`. |
| `B_atom_correction_cmu_set_load_standard` | Set MFCMU load-correction reference values. | `DCORR` | Required for load correction accuracy. |
| `B_atom_correction_cmu_set_correction_data` | Set MFCMU correction data directly. | `CORRDT` | Restore saved correction without remeasuring. |
| `B_atom_correction_cmu_measure_series_resistance` | Measure SCUU/MFCMU cable series resistance. | `CORRSER?` | Active measurement; SCUU cable compensation. |
| `B_atom_correction_qscv_offset_cancel` | Perform QSCV offset/zero cancellation. | `QSZ` | Needed before QSCV recipes. |
| `B_atom_correction_spgu_set_open_comp` | Enable/disable SPGU open compensation. | `SOPC`, `SOPC?` | Output correction state; readback is A-class. |
| `B_atom_correction_spgu_set_short_comp` | Enable/disable SPGU short (voltage) compensation. | `SOVC`, `SOVC?` | Output correction state; readback is A-class. |
| `B_atom_correction_spgu_measure_series` | Measure SPGU output-path series resistance. | `CORRSER?` | Active correction measurement (shared command with CMU/SCUU variant). |

## B Class Atom Tools — policy

| Tool | Meaning | Basis | Notes |
|---|---|---|---|
| `B_atom_policy_b1500_set_auto_calibration` | Set auto-calibration policy. | `CM` | Important for long batch runs. |
| `B_atom_policy_wgfmu_treat_warnings_as_errors` | Set WGFMU warning-as-error policy. | `WGFMU_treatWarningsAsErrors` | Converts selected warning behavior into stricter failure mode. |


## Implementation Notes

- Do not add a default `send_raw_flex_command` tool.
- If an expert raw command path is added later, it must be disabled by default, approval-gated, and audited.
- Query responses and measurement data buffers are different. Real tools must consume query responses promptly and not assume measurement data is available after errors.
- A/B atom names are intentionally stable MCP surface names. Do not expose legacy unprefixed aliases unless a migration layer is explicitly requested.

