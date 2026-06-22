# C Atom Candidates - Opus46

## Scope and Exclusions

### What counts as C_atom

C atoms are **measurement/source/execution** atoms: operations that directly:
- Force voltage, current, pulse, or waveform onto a DUT
- Configure measurement mode, ranging, integration, or ADC type that is inseparable from a measurement outcome
- Define sweep/source/measurement events and timing
- Execute measurement triggers
- Read/retrieve measurement-specific data from output buffers or WGFMU data memory

### What remains A/B

| Layer | Stays in | Examples |
|---|---|---|
| Connection/session/discovery | A_atom | `*IDN?`, `UNT?`, `WGFMU_openSession`, `WGFMU_getChannelIds` |
| Error/status/SRQ readback | A_atom | `ERR?`, `ERRX?`, `*STB?`, `NUB?`, `WGFMU_getError` |
| Data format/parser config | A_atom | `FMT`, `TSC`, `TSR`, `BC` |
| Output buffer read (generic) | A_atom | `A_atom_flex_read_output_buffer` |
| Channel enable/disable | B_atom | `CN`, `CL`, `DZ`, `RZ`, `WGFMU_connect/disconnect` |
| Reset/initialize/abort | B_atom | `*RST`, `IN`, `AB`, `WGFMU_abort`, `WGFMU_initialize` |
| Safety/interlock | B_atom | `INTLKVTH`, `WZ?` |
| Self-test/calibration | B_atom | `*TST?`, `*CAL?`, `WGFMU_doSelfCalibration` |
| ASU/SCUU path routing | B_atom | `SAP`, `SAR`, `SSP` |
| CMU correction (open/short/load) | B_atom | `CORRST`, `CORR?`, `ADJ`, `ADJ?`, `CLCORR` |
| QSCV offset cancel | B_atom | `QSZ` |
| Filter/series resistor | B_atom | `FL`, `SSR` |
| Auto-calibration policy | B_atom | `CM` |
| EasyEXPERT workspace/selection | A_atom | `:WORKspace:OPEN`, `:BENCh:APPlication:SELect` |
| EasyEXPERT abort | B_atom | `:ABORt` |

### Boundary principle

If a command *only* changes instrument topology, safety state, or software context without producing measurement data or sourcing to DUT, it is A/B. If it forces energy to DUT or produces measurement data, it is C.

---

## Object / Unit Categories

| Category | Prefix | Rationale | Primary Hardware |
|---|---|---|---|
| `smu` | `C_atom_smu_*` | General SMU IV source/measure — covers MPSMU, HPSMU, MCSMU, HRSMU. First priority. | B1510A, B1511A/B, B1514A, B1517A |
| `wgfmu` | `C_atom_wgfmu_*` | Arbitrary waveform + fast IV — unique API surface (instrument library, not GPIB direct). | B1530A + B1531A RSU |
| `spgu` | `C_atom_spgu_*` | Pulse generator unit — PG/ALWG pulse sourcing. | B1525A |
| `cmu` | `C_atom_cmu_*` | MFCMU impedance/capacitance measurement. | B1520A |
| `hvsmu` | `C_atom_hvsmu_*` | High-voltage SMU operations distinct from standard SMU. | B1513A/B/C |
| `hcsmu` | `C_atom_hcsmu_*` | High-current SMU operations distinct from standard SMU. | B1512A |
| `uhcu` | `C_atom_uhcu_*` | Ultra-high-current unit (N1265A expander). | N1265A + MCSMU/HCSMU pair |
| `gndu` | — | **Not proposed as C_atom category** — see Rejected section. | GNDU (internal) |
| `easyexpert` | `C_atom_easyexpert_*` | Software-mediated test execution. | EasyEXPERT remote |

---

## Candidate C_atom Table

### Category: SMU (`C_atom_smu_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_smu_force_voltage` | Force DC voltage on SMU channel | `DV` | chnum, vrange, voltage, Icomp, comp_polarity, irange | Immediate voltage output to DUT | CN (B_atom), channel enabled | PDF 395 / 4-78 | P0 | Core source primitive; interlock required if >threshold |
| `C_atom_smu_force_current` | Force DC current on SMU channel | `DI` | chnum, irange, current, Vcomp | Immediate current output to DUT | CN (B_atom), channel enabled | PDF 390 / 4-73 | P0 | Compliance must be set |
| `C_atom_smu_spot_measure_i` | High-speed spot current measurement (no MM/XE) | `TI` | chnum, range | Single current value | CN, DV or DI active | PDF 534 / 4-217 | P0 | Fastest single-point I measurement |
| `C_atom_smu_spot_measure_v` | High-speed spot voltage measurement (no MM/XE) | `TV` | chnum, range | Single voltage value | CN, DV or DI active | PDF 544 / 4-227 | P0 | Fastest single-point V measurement |
| `C_atom_smu_spot_measure_iv` | High-speed spot I+V measurement | `TIV` | chnum, irange, vrange | Current + voltage pair | CN, DV or DI active | PDF 534 / 4-217 | P0 | Combined I+V in one command |
| `C_atom_smu_spot_measure_i_ts` | Timestamped high-speed spot current | `TTI` | chnum, range | Current + timestamp | CN, DV/DI, TSC enabled | PDF 534-544 | P1 | Needs TSC on |
| `C_atom_smu_spot_measure_v_ts` | Timestamped high-speed spot voltage | `TTV` | chnum, range | Voltage + timestamp | CN, DV/DI, TSC enabled | PDF 544 | P1 | Needs TSC on |
| `C_atom_smu_spot_measure_iv_ts` | Timestamped high-speed spot I+V | `TTIV` | chnum, irange, vrange | I + V + timestamp | CN, DV/DI, TSC enabled | PDF 534 | P1 | Combined timestamped |
| `C_atom_smu_timer_force_voltage` | Start timer and force voltage | `TDV` | chnum, vrange, voltage, Icomp, comp_polarity | Resets timer + forces voltage | CN | PDF 525-527 / 4-208 | P2 | Timer-start + source combined |
| `C_atom_smu_timer_force_current` | Start timer and force current | `TDI` | chnum, irange, current, Vcomp | Resets timer + forces current | CN | PDF 525-527 / 4-208 | P2 | Timer-start + source combined |
| `C_atom_smu_set_measurement_mode` | Select measurement mode and channels | `MM` | mode (1-28), chnum list | Configures mode for XE | CN | PDF 469 / 4-152 | P0 | Central mode selector |
| `C_atom_smu_set_integration_time` | Set SMU ADC integration time | `AIT` | type (high-speed/high-res/pulse), mode, N | Integration time config | — | PDF 322, 349-374 | P0 | Directly affects measurement quality |
| `C_atom_smu_set_adc_type` | Select A/D converter type | `AAD` | chnum, adc_type | ADC selection | — | PDF 349 / 4-32 | P1 | High-speed vs high-resolution ADC |
| `C_atom_smu_set_averaging` | Set measurement averaging count | `AV` | number, mode | Averaging config | — | PDF 322 | P1 | Trades speed for noise |
| `C_atom_smu_set_measurement_ranging` | Set current/voltage measurement range | `RI`, `RV`, `RM` | chnum, range | Range config | — | PDF 500, 503 / 4-183, 4-185 | P0 | Auto/fixed/limited-auto |
| `C_atom_smu_set_measurement_operation` | Set measurement operation mode | `CMM` | chnum, mode (compliance/I/V/force) | Measurement channel behavior | — | PDF 379 / 4-62 | P1 | Controls what is measured on each channel |
| `C_atom_smu_configure_sweep_voltage` | Configure staircase sweep voltage source | `WV` | chnum, mode (lin/log/lin2/log2), vrange, start, stop, steps, Icomp | Sweep source definition | — | PDF 567-568 / 4-250 | P0 | MM2/MM16 prerequisite |
| `C_atom_smu_configure_sweep_current` | Configure staircase sweep current source | `WI` | chnum, mode, irange, start, stop, steps, Vcomp | Sweep source definition | — | PDF 550-551 / 4-233 | P1 | MM2/MM16 with current sweep |
| `C_atom_smu_configure_sweep_timing` | Set sweep hold/delay/step-delay | `WT` | hold, delay, sdelay, tdelay | Timing between sweep steps | — | PDF 563-564 / 4-246 | P0 | Affects sweep quality and speed |
| `C_atom_smu_configure_sweep_abort` | Set sweep auto-abort and post-output mode | `WM` | abort_mode, post_output | Abort/output behavior | — | PDF 551-553 | P1 | Safety behavior during compliance |
| `C_atom_smu_configure_sync_sweep_voltage` | Configure synchronous sweep voltage | `WSV` | chnum, mode, vrange, start, stop, Icomp | Synchronous source tracks primary | — | PDF 560-562 / 4-243 | P2 | Secondary sweep source |
| `C_atom_smu_configure_sync_sweep_current` | Configure synchronous sweep current | `WSI` | chnum, mode, irange, start, stop, Vcomp | Synchronous source tracks primary | — | PDF 559-560 / 4-242 | P2 | Secondary sweep source |
| `C_atom_smu_configure_multi_sweep` | Configure additional multi-channel sweep source | `WNX` | chnum, mode, range, start, stop, comp | Multi-ch sweep source | WV/WI configured | PDF 556-558 | P1 | MM16 prerequisite |
| `C_atom_smu_configure_pulse_timing` | Set pulse hold/width/period | `PT` | hold, width, period, tdelay | Pulse timing definition | — | PDF 485 / 4-168 | P0 | MM3/MM4/MM5 prerequisite |
| `C_atom_smu_configure_pulse_voltage` | Set pulse voltage source | `PV` | chnum, vrange, base, peak, Icomp | Pulse source definition | PT configured | PDF 487 / 4-170 | P0 | MM3/MM5 prerequisite |
| `C_atom_smu_configure_pulse_current` | Set pulse current source | `PI` | chnum, irange, base, peak, Vcomp | Pulse source definition | PT configured | PDF 484 / 4-167 | P2 | Pulse current source |
| `C_atom_smu_configure_pulsed_sweep_voltage` | Set pulsed sweep voltage source | `PWV` | chnum, mode, vrange, base, start, stop, steps, Icomp | Pulsed sweep definition | PT configured | PDF 490-491 / 4-174 | P1 | MM4 prerequisite |
| `C_atom_smu_configure_pulsed_sweep_current` | Set pulsed sweep current source | `PWI` | chnum, mode, irange, base, start, stop, steps, Vcomp | Pulsed sweep definition | PT configured | PDF 489-490 / 4-172 | P2 | MM4 with current |
| `C_atom_smu_configure_sampling` | Configure sampling measurement | `MCC`, `ML`, `MT`, `MSC`, `MI`/`MV`, `MSP` | channels, mode(lin/log), interval, points, sources, post | Sampling measurement setup | — | PDF 460-476 | P1 | MM10 full setup (multiple commands) |
| `C_atom_smu_configure_quasi_pulse` | Configure quasi-pulsed spot | `BDV`, `BDT`, `BDM` | chnum, vrange, voltage, hold, detection_mode | Quasi-pulse definition | — | PDF 363-374 | P2 | MM9 prerequisite |
| `C_atom_smu_configure_linear_search` | Configure linear search measurement | `LSV`/`LSI`, `LGV`/`LGI`, `LSTM`, `LSM`, `LSVM` | search_source, monitor, timing, abort, output_mode | Linear search definition | — | PDF 442-460 | P2 | MM14 prerequisite |
| `C_atom_smu_configure_binary_search` | Configure binary search measurement | `BSV`/`BSI`, `BGV`/`BGI`, `BST`, `BSM`, `BSVM` | search_source, monitor, step, abort, output_mode | Binary search definition | — | PDF 363-374 | P2 | MM15 prerequisite |
| `C_atom_smu_configure_qscv` | Configure quasi-static CV measurement | `QSV`, `QST`, `QSM`, `QSL`, `QSO`, `QSC`, `QSR` | voltage, timing, abort, leakage, offset, capacitance_formula, range | QSCV measurement definition | QSZ (B_atom) done | PDF 493-499 | P2 | MM13 prerequisite; complex setup |
| `C_atom_smu_configure_multi_pulsed_spot` | Configure multi-channel pulsed spot | `MCPT`, `MCPNT`, `MCPNX` | timing, channels, voltage/current | Multi-ch pulsed spot definition | — | PDF 460-477 | P2 | MM27 prerequisite |
| `C_atom_smu_configure_multi_pulsed_sweep` | Configure multi-channel pulsed sweep | `MCPT`, `MCPNT`, `MCPWS`, `MCPWNX` | timing, channels, sweep, source | Multi-ch pulsed sweep definition | — | PDF 460-477 | P2 | MM28 prerequisite |
| `C_atom_smu_configure_parallel_adc` | Enable parallel A/D conversion | `PAD` | mode | Parallel ADC on/off | — | PDF 480 / 4-163 | P2 | Speed optimization for multi-ch |
| `C_atom_smu_configure_high_speed_spot` | Configure high-speed spot mode | `HSS` | chnum, mode | High-speed spot configuration | — | PDF 437 / 4-120 | P2 | Rarely needed explicitly |
| `C_atom_smu_execute_measurement` | Trigger measurement execution | `XE` | (none — operates on current MM setup) | Measurement data placed in output buffer | MM configured, sources set, CN done | PDF 569-571 / 4-252 | P0 | Universal measurement trigger |
| `C_atom_smu_read_measurement_data` | Read measurement data from output buffer | Output buffer read (GPIB read after XE) | format depends on FMT | Parsed IV/sweep/sampling data | XE completed, NUB? checked | PDF 44-74 (data format) | P0 | Critical data retrieval |
| `C_atom_smu_configure_signal_monitor` | Configure signal monitor for multi-ch pulsed | `DSMPLSETUP`, `DSMPLARM`, `DSMPLFLUSH` | setup, arm, flush | Signal monitor data | HVSMU/HCSMU/MCSMU in MM27/28 | PDF 392-395 / 4-75 | P2 | Niche: monitors V/I during multi-ch pulsed |

### Category: WGFMU (`C_atom_wgfmu_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_wgfmu_create_pattern` | Create named waveform pattern | `WGFMU_createPattern` | pattern_name, initV | Pattern object created | WGFMU session open (A_atom) | PDF 94 / 4-18 | P0 | Offline operation; no hardware needed |
| `C_atom_wgfmu_add_vector` | Append voltage/time point to pattern | `WGFMU_addVector` / `addVectors` | pattern, dTime, voltage | Pattern extended | Pattern exists | PDF 88-89 / 4-12 | P0 | dTime incremental, 10 ns resolution |
| `C_atom_wgfmu_set_vector` | Set absolute-time point in pattern | `WGFMU_setVector` / `setVectors` | pattern, time, voltage | Pattern modified | Pattern exists | PDF 137-138 / 4-61 | P1 | Replaces existing at same time |
| `C_atom_wgfmu_merge_pattern` | Create merged pattern (time or voltage axis) | `WGFMU_createMergedPattern` | new_name, pattern1, pattern2, direction | New pattern | Both source patterns exist | PDF 91-92 / 4-15 | P1 | AXIS_TIME or AXIS_VOLTAGE |
| `C_atom_wgfmu_multiply_pattern` | Create scaled/reversed pattern | `WGFMU_createMultipliedPattern` | new_name, origin, factorT, factorV | New pattern | Source pattern exists | PDF 92-93 / 4-16 | P2 | Negative factorT reverses time |
| `C_atom_wgfmu_offset_pattern` | Create offset pattern | `WGFMU_createOffsetPattern` | new_name, origin, offsetT, offsetV | New pattern | Source pattern exists | PDF 93-94 / 4-17 | P2 | Positive offsetT inserts initial vector |
| `C_atom_wgfmu_add_sequence` | Assign pattern+count to channel sequence | `WGFMU_addSequence` / `addSequences` | chanId, pattern, count | Sequence built | Pattern exists | PDF 85-87 / 4-9 | P0 | 50 ns inter-sequence delay |
| `C_atom_wgfmu_set_measure_event` | Define sampling measurement within pattern | `WGFMU_setMeasureEvent` | pattern, event_name, time, points, interval, average, rdata | Measure event attached | Pattern exists | PDF 130-131 / 4-54 | P0 | Key function; defines what is measured |
| `C_atom_wgfmu_set_range_event` | Define mid-waveform range change | `WGFMU_setRangeEvent` | pattern, event_name, time, range | Range event attached | Pattern exists, Fast IV mode | PDF 133-134 / 4-57 | P1 | ≥2 µs between 3+ consecutive |
| `C_atom_wgfmu_set_trigger_event` | Define trigger output event in pattern | `WGFMU_setTriggerOutEvent` | pattern, event_name, time, duration | Trigger event attached | Pattern exists, trigger mode=EVENT | PDF 135-136 / 4-59 | P2 | Synchronization with external |
| `C_atom_wgfmu_set_operation_mode` | Set channel operation mode | `WGFMU_setOperationMode` | chanId, mode (DC/FastIV/PG/SMU) | Mode configured | WGFMU session open | PDF 119, 133, 145 | P0 | Determines force/measure capabilities |
| `C_atom_wgfmu_set_force_voltage_range` | Set voltage output range | `WGFMU_setForceVoltageRange` | chanId, range (AUTO/3V/5V/±10V) | Range configured | — | PDF 107, 128, 146 | P0 | PG mode limited to 3V/5V |
| `C_atom_wgfmu_set_measure_mode` | Set voltage or current measurement | `WGFMU_setMeasureMode` | chanId, mode (VOLTAGE/CURRENT) | Mode configured | Fast IV or DC mode | PDF 114, 131-132, 147 | P0 | Current mode forces 5V range |
| `C_atom_wgfmu_set_measure_current_range` | Set current measurement range | `WGFMU_setMeasureCurrentRange` | chanId, range (1µA–10mA) | Range configured | Current mode | PDF 108, 129, 148 | P0 | Not effective in voltage mode |
| `C_atom_wgfmu_set_measure_voltage_range` | Set voltage measurement range | `WGFMU_setMeasureVoltageRange` | chanId, range (5V/10V) | Range configured | Voltage mode | PDF 118, 132, 147 | P1 | Not effective in current mode |
| `C_atom_wgfmu_set_force_delay` | Set source channel timing delay | `WGFMU_setForceDelay` | chanId, delay (±50ns, 625ps res) | Delay configured | — | PDF 105, 128 | P2 | Cable/path compensation |
| `C_atom_wgfmu_set_measure_delay` | Set measurement channel timing delay | `WGFMU_setMeasureDelay` | chanId, delay (±50ns, 625ps res) | Delay configured | — | PDF 108-109, 129 | P2 | Cable/path compensation |
| `C_atom_wgfmu_set_measure_enabled` | Enable/disable measurement on channel | `WGFMU_setMeasureEnabled` | chanId, status (ENABLE/DISABLE) | Meas enable/disable | Not DC mode | PDF 126, 130, 149 | P1 | Suppress measurement on force-only ch |
| `C_atom_wgfmu_set_trigger_out_mode` | Set trigger output mode/polarity | `WGFMU_setTriggerOutMode` | chanId, mode, polarity | Trigger configured | — | PDF 124, 136, 149 | P2 | Needed before setTriggerOutEvent |
| `C_atom_wgfmu_update` | Apply setup and output initial voltage | `WGFMU_update` / `updateChannel` | (chanId for updateChannel) | Setup applied to hardware | Session open, connected (B_atom) | PDF 140 / 4-64 | P0 | Performs deferred validation |
| `C_atom_wgfmu_execute` | Run sequencer on all enabled channels | `WGFMU_execute` | (none) | Starts waveform output + measurement | Sequences built, connected | PDF 99 / 4-23 | P0 | Core execution trigger |
| `C_atom_wgfmu_wait_completed` | Block until all channels complete | `WGFMU_waitUntilCompleted` | (none) | Completion status | execute called | PDF 141 / 4-65 | P0 | Data ready after return |
| `C_atom_wgfmu_get_measure_values` | Read measurement data (time + V/I) | `WGFMU_getMeasureValues` / `getMeasureValue` / `getMeasureValueSize` | chanId, index, size | time[], value[] arrays | Execute completed or partial | PDF 116-118 / 4-40 | P0 | Primary data retrieval |
| `C_atom_wgfmu_get_force_values` | Read applied force data (time + V) | `WGFMU_getForceValues` / `getInterpolatedForceValue` | chanId, index/time | time[], voltage[] or interpolated V | Sequence defined | PDF 105-108 / 4-29 | P1 | Correlate measured with forced |
| `C_atom_wgfmu_dc_force_voltage` | DC immediate voltage output | `WGFMU_dcforceVoltage` | chanId, voltage | Immediate DC output | DC mode, connected | PDF 95, 76 / 4-19, 3-30 | P1 | Simple DC without patterns |
| `C_atom_wgfmu_dc_measure_value` | DC single-point measurement | `WGFMU_dcmeasureValue` | chanId | Single V or I value | DC mode, connected | PDF 96, 76 / 4-20, 3-30 | P1 | Simple DC measurement |
| `C_atom_wgfmu_dc_measure_averaged` | DC averaged measurement | `WGFMU_dcmeasureAveragedValue` | chanId, points (1-65535), interval (×5ns) | Averaged V or I value | DC mode, connected | PDF 95-96, 76 | P1 | Better noise performance |

### Category: SPGU (`C_atom_spgu_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_spgu_set_operation_mode` | Set SPGU operation mode (PG/ALWG) | `SIM` | chnum, mode (PG/ALWG) | Mode configured | CNX (B_atom) | PDF 504-521 | P1 | PG for standard pulses, ALWG for arbitrary |
| `C_atom_spgu_configure_pulse_period` | Set pulse repetition period | `SPPER` | chnum, period | Period configured | SIM set | PDF 510-511 | P1 | All channels share period |
| `C_atom_spgu_configure_pulse_timing` | Set pulse rise/fall/width timing | `SPT` | chnum, leading_edge, trailing_edge | Timing configured | SPPER set | PDF 513-514 | P1 | Per-channel timing |
| `C_atom_spgu_configure_pulse_voltage` | Set pulse voltage levels | `SPV` | chnum, pulse_number, base, peak | Voltage levels set | — | PDF 515-516 | P1 | 2-level or 3-level pulses |
| `C_atom_spgu_configure_pulse_mask` | Set pulse mask (enable pulse segments) | `SPM` | chnum, mask_pattern | Mask configured | — | PDF 511 | P2 | Controls which sub-pulses are active |
| `C_atom_spgu_set_load_impedance` | Set SPGU load impedance mode | `SPRM` | chnum, mode | Load mode configured | — | PDF 512 | P1 | Affects output voltage calibration |
| `C_atom_spgu_update_output` | Apply SPGU settings (load to hardware) | `SPUPD` | (none) | Settings applied | Pulse configured | PDF 514-515 | P1 | Required before start |
| `C_atom_spgu_start_output` | Start SPGU pulse output | `SRP` | (none) | Pulse output running | SPUPD done, CNX | PDF 513 | P1 | Pulses begin |
| `C_atom_spgu_stop_output` | Stop SPGU pulse output | `SPP` | (none) | Pulse output stopped | SRP running | PDF 511 | P1 | Pulses stop |
| `C_atom_spgu_query_status` | Query SPGU output status | `SPST?` | (none) | Running/stopped status | — | PDF 513 | P2 | Status readback |
| `C_atom_spgu_set_trigger_output` | Configure SPGU trigger output | `STGP` | mode, polarity | Trigger configured | — | PDF 521 | P2 | External sync |
| `C_atom_spgu_configure_alwg_waveform` | Load ALWG arbitrary waveform data | `ALW` | chnum, data | Waveform loaded | SIM=ALWG | PDF 327 (grouped) | P2 | Complex arbitrary waveforms |
| `C_atom_spgu_configure_alwg_sequence` | Set ALWG sequence control | `ALS` | chnum, sequence_data | Sequence configured | SIM=ALWG | PDF 327 (grouped) | P2 | ALWG execution control |
| `C_atom_spgu_set_output_switch` | Set SPGU pulse output switch mode | `ODSW` | chnum, mode | Switch configured | — | PDF 478-479 | P2 | Open-drain/normal output select |

### Category: CMU/MFCMU (`C_atom_cmu_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_cmu_set_impedance_model` | Select impedance measurement parameter | `IMP` | chnum, mode (Cp-G, Cp-D, Cs-Rs, Z-θ, etc.) | Model configured | — | PDF 440 / 4-123 | P0 | Determines output data interpretation |
| `C_atom_cmu_set_frequency` | Set AC signal frequency | `FC` | chnum, frequency | Frequency configured | — | PDF 434 / 4-117 | P0 | 1 kHz to 5 MHz |
| `C_atom_cmu_set_ac_level` | Set AC oscillator level | `ACV` | chnum, voltage | AC level configured | — | PDF 353 / 4-36 | P0 | Test signal amplitude |
| `C_atom_cmu_set_dc_bias` | Set DC bias voltage | `DCV` | chnum, voltage, Icomp | DC bias applied | CN | PDF 389 / 4-72 | P0 | Bias for CV measurements |
| `C_atom_cmu_set_integration_time` | Set CMU ADC integration time | `ACT` | chnum, mode, N | Integration configured | — | PDF 353 / 4-36 | P1 | Measurement speed/accuracy tradeoff |
| `C_atom_cmu_set_ranging` | Set CMU measurement range | `RC` | chnum, range | Range configured | — | PDF 499 / 4-182 | P1 | Auto/fixed impedance range |
| `C_atom_cmu_set_monitor_output` | Enable/disable OSC/DC monitor data | `LMN` | chnum, mode | Monitor data on/off | — | PDF 444 / 4-127 | P2 | Extra data elements in output |
| `C_atom_cmu_spot_measure_c` | High-speed spot capacitance (no MM/XE) | `TC` | chnum | Single C measurement | CN, IMP, FC, ACV, DCV set | PDF 521-545 | P1 | Fast single-point C |
| `C_atom_cmu_spot_measure_c_ts` | Timestamped high-speed spot C | `TTC` | chnum | C + timestamp | CN, IMP, FC, ACV, DCV, TSC | PDF 521-545 | P2 | Timestamped variant |
| `C_atom_cmu_timer_set_ac` | Start timer and set AC level | `TACV` | chnum, voltage | Timer reset + AC applied | CN | PDF 523 / 4-206 | P2 | Timer-start + CMU output |
| `C_atom_cmu_timer_set_dc` | Start timer and set DC bias | `TDCV` | chnum, voltage, Icomp | Timer reset + DC applied | CN | PDF 524 / 4-207 | P2 | Timer-start + CMU output |
| `C_atom_cmu_hs_measure_acv` | High-speed spot with AC level set | `TMACV` | chnum, voltage | Sets AC + measures | CN, IMP, FC, DCV | PDF 537 | P2 | Combined set+measure |
| `C_atom_cmu_hs_measure_dcv` | High-speed spot with DC bias set | `TMDCV` | chnum, voltage, Icomp | Sets DC + measures | CN, IMP, FC, ACV | PDF 537 | P2 | Combined set+measure |
| `C_atom_cmu_configure_dc_sweep` | Configure CV (DC bias) sweep | `WDCV`, `WTDCV`, `WMDCV` | chnum, mode, range, start, stop, steps, timing, abort | DC sweep definition | IMP, FC, ACV set | PDF 548, 565, 553 | P0 | MM18 prerequisite |
| `C_atom_cmu_configure_freq_sweep` | Configure C-f sweep | `WFC`, `WTFC`, `WMFC` | chnum, mode, start, stop, steps, timing, abort | Frequency sweep definition | IMP, DCV, ACV set | PDF 549, 566, 554 | P1 | MM22 prerequisite |
| `C_atom_cmu_configure_ac_sweep` | Configure CV (AC level) sweep | `WACV`, `WTACV`, `WMACV` | chnum, mode, start, stop, steps, timing, abort | AC sweep definition | IMP, FC, DCV set | PDF 546, 564, 553 | P2 | MM23 prerequisite |
| `C_atom_cmu_configure_pulsed_dc_bias` | Configure pulsed DC bias for CMU | `PTDCV`, `PDCV` | chnum, timing, base, peak | Pulsed DC definition | IMP, FC, ACV set | PDF 486, 483 | P2 | MM19/MM20 prerequisite |
| `C_atom_cmu_configure_pulsed_dc_sweep` | Configure pulsed sweep DC bias for CMU | `PTDCV`, `PWDCV`, `WTDCV`, `WMDCV` | chnum, timing, mode, start, stop, steps, base | Pulsed sweep definition | IMP, FC, ACV set | PDF 486, 488, 565, 553 | P2 | MM20 prerequisite |
| `C_atom_cmu_configure_sampling` | Configure C-t sampling | `MDCV`, `MTDCV` | chnum, dc_bias, interval, points, hold | Sampling definition | IMP, FC, ACV set | PDF 466, 475 | P2 | MM26 prerequisite |

### Category: HVSMU (`C_atom_hvsmu_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_hvsmu_set_operation_mode` | Set HVSMU operation mode | `HVSMUOP` | chnum, mode | Mode configured | Interlock closed | PDF 437-438 / 4-120 | P1 | Normal/high-voltage/high-current modes |
| `C_atom_hvsmu_force_voltage` | Force high voltage (uses DV with HV ranges) | `DV` (HV ranges) | chnum, vrange (up to 3kV), voltage, Icomp | HV output to DUT | CN, interlock closed | PDF 395, 338-339 | P1 | Interlock-critical; same DV command, HV ranges |
| `C_atom_hvsmu_force_current` | Force current in HV context | `DI` (HC ranges) | chnum, irange, current, Vcomp | Current output | CN, interlock closed | PDF 390, 338-339 | P2 | Same DI, HV context |

### Category: HCSMU (`C_atom_hcsmu_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_hcsmu_force_voltage` | Force voltage from high-current SMU | `DV` (HC context) | chnum, vrange, voltage, Icomp (up to 20A) | Voltage output | CN, interlock for HV range | PDF 395, 338-339 | P2 | Same DV, high-current compliance |
| `C_atom_hcsmu_force_current` | Force high current | `DI` (HC ranges up to 40A) | chnum, irange (up to 23/24), current, Vcomp | HC output to DUT | CN | PDF 390, 336-337 | P2 | Dual HCSMU can combine |

### Category: UHCU (`C_atom_uhcu_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_uhcu_force_current` | Force ultra-high current (up to 2000A) | `DI` via N1265A (ranges 26/28) | chnum, irange (500A/2000A), current, Vcomp | UHC output | ERMOD 4 set (B_atom), CN, fixture ready | PDF 155-157, 336-337 | P2 | Requires N1265A fixture + calibration |
| `C_atom_uhcu_sweep_current` | Sweep ultra-high current | `WI` via N1265A | chnum, mode, irange, start, stop, steps, Vcomp | UHC sweep | ERMOD 4, CN, fixture | PDF 155-157 | P2 | Niche high-power characterization |

### Category: EasyEXPERT (`C_atom_easyexpert_*`)

| Candidate Atom Name | Meaning / Measurement Role | Source Commands / APIs | Key Parameters | Output / Data Returned | Required A/B Preconditions | Source Index/PDF Pages | Priority | Notes / Risks |
|---|---|---|---|---|---|---|---|---|
| `C_atom_easyexpert_run_selected_test` | Execute currently selected test setup | `:BENCh[:SELected]:RUN` | (operates on selected setup) | Measurement executed; result in workspace | Workspace open, test selected (A_atoms), standby set (B_atom) | EasyEXPERT PDF 418, 427-438 | P1 | Software-mediated; not low-level hardware atom |
| `C_atom_easyexpert_run_single` | Execute single measurement | `:BENCh[:SELected]:RUN:SING` | (none) | Single result recorded | Setup selected | EasyEXPERT PDF 427-431 | P1 | Convenience variant |
| `C_atom_easyexpert_run_append` | Execute and append result | `:BENCh[:SELected]:RUN:APP` | (none) | Appended result | Setup selected | EasyEXPERT PDF 427-431 | P2 | Multi-run accumulation |
| `C_atom_easyexpert_run_repeat` | Execute repeated measurement | `:BENCh[:SELected]:RUN:REP` | count set via A_atom | Repeated results | Setup selected, count set | EasyEXPERT PDF 427-431 | P2 | Batch execution |
| `C_atom_easyexpert_fetch_result` | Fetch measurement result data | `:RESult:FETch[:LATest]?` | format (TEXT/XTR) | Measurement data block | Run completed | EasyEXPERT PDF 436-438 | P1 | Parser must handle SCPI block header |

---

## High-Priority MVP C_atoms

These P0 candidates form the minimum viable measurement surface for initial implementation:

### SMU P0 (12 atoms)
1. **`C_atom_smu_force_voltage`** — Force DC voltage (DV)
2. **`C_atom_smu_force_current`** — Force DC current (DI)
3. **`C_atom_smu_spot_measure_i`** — High-speed spot I (TI)
4. **`C_atom_smu_spot_measure_v`** — High-speed spot V (TV)
5. **`C_atom_smu_spot_measure_iv`** — High-speed spot I+V (TIV)
6. **`C_atom_smu_set_measurement_mode`** — Configure measurement mode (MM)
7. **`C_atom_smu_set_integration_time`** — Set integration time (AIT)
8. **`C_atom_smu_set_measurement_ranging`** — Set I/V ranging (RI, RV, RM)
9. **`C_atom_smu_configure_sweep_voltage`** — Configure voltage sweep (WV)
10. **`C_atom_smu_configure_sweep_timing`** — Set sweep timing (WT)
11. **`C_atom_smu_configure_pulse_timing`** — Set pulse timing (PT)
12. **`C_atom_smu_configure_pulse_voltage`** — Set pulse voltage (PV)
13. **`C_atom_smu_execute_measurement`** — Execute measurement (XE)
14. **`C_atom_smu_read_measurement_data`** — Read data from output buffer

### WGFMU P0 (10 atoms)
1. **`C_atom_wgfmu_create_pattern`** — Create waveform pattern
2. **`C_atom_wgfmu_add_vector`** — Add vector to pattern
3. **`C_atom_wgfmu_add_sequence`** — Assign pattern to channel
4. **`C_atom_wgfmu_set_measure_event`** — Define measurement event
5. **`C_atom_wgfmu_set_operation_mode`** — Set Fast IV/PG/DC mode
6. **`C_atom_wgfmu_set_force_voltage_range`** — Set output range
7. **`C_atom_wgfmu_set_measure_mode`** — Set V/I measurement
8. **`C_atom_wgfmu_set_measure_current_range`** — Set I range
9. **`C_atom_wgfmu_update`** — Apply setup to hardware
10. **`C_atom_wgfmu_execute`** — Run sequencer
11. **`C_atom_wgfmu_wait_completed`** — Wait for completion
12. **`C_atom_wgfmu_get_measure_values`** — Read measurement data

### CMU P0 (5 atoms)
1. **`C_atom_cmu_set_impedance_model`** — Select Cp-D/Cs-Rs/etc.
2. **`C_atom_cmu_set_frequency`** — Set AC frequency
3. **`C_atom_cmu_set_ac_level`** — Set oscillator level
4. **`C_atom_cmu_set_dc_bias`** — Set DC bias
5. **`C_atom_cmu_configure_dc_sweep`** — Configure CV sweep

*(CMU execution uses `C_atom_smu_set_measurement_mode` with MM17/18 and `C_atom_smu_execute_measurement` for XE)*

**Total P0: ~31 atoms** (14 SMU + 12 WGFMU + 5 CMU)

---

## Rejected / Deferred

| Command/Concept | Reason for Rejection / Deferral | Classification |
|---|---|---|
| `CN` / `CL` / `CNX` | Channel enable/disable is output-state control, not measurement. | B_atom (already exists) |
| `DZ` / `RZ` | Zero-and-store is safety/state, not measurement. | B_atom (already exists) |
| `AB` | Abort is safety/emergency. | B_atom (already exists) |
| `*RST` / `IN` | Reset/initialize is lifecycle. | B_atom (already exists) |
| `SAP` / `SAR` / `SSP` / `SSL` | Path routing is topology control. | B_atom (already exists) |
| `FL` / `SSR` | Filter/series-resistor are conditioning, not measurement. | B_atom (already exists) |
| `CORRST` / `CORR?` / `ADJ` / `ADJ?` | CMU correction is calibration, not measurement execution. | B_atom (already exists) |
| `QSZ` | QSCV offset cancel is calibration/correction precursor. | B_atom (already exists) |
| `FMT` / `BC` / `TSC` / `TSR` | Data format and buffer management are parser/session configuration. | A_atom (already exists) |
| `NUB?` / `*OPC?` / `ERR?` / `ERRX?` | Status/error readback is discovery. | A_atom (already exists) |
| `WGFMU_connect` / `WGFMU_disconnect` | Channel connect/disconnect is output state control. | B_atom (already exists) |
| `WGFMU_abort` / `WGFMU_initialize` | Abort/init is lifecycle/safety. | B_atom (already exists) |
| `WGFMU_clear` | Software setup clear is session management. | A_atom (already exists) |
| `WGFMU_doSelfCalibration` / `doSelfTest` | Diagnostic/calibration. | B_atom (already exists) |
| `WGFMU_exportAscii` | Debug/validation export is readback utility. | A_atom (already exists) |
| `ERMOD` / `ERSSP` | Module selector/routing is topology. | B_atom |
| `ERM` / `ERC` | Digital I/O for relay control is infrastructure. | B_atom |
| `TGP` / `TGPC` / `TGSI` / `TGSO` / `TGXO` / `TGMO` | Trigger port configuration is infrastructure/timing. | B_atom or borderline C — deferred |
| `PAX` / `WSX` / `TM` | Trigger wait/mode is timing infrastructure. | B_atom |
| `SCR` / `END` / `DO` / `RU` / `LST?` / `VAR` | Program memory is execution infrastructure. | A/B_atom |
| `GNDU` (entire unit) | No meaningful C_atom — see below. | Not a C category |
| `PA` (pause) | Timing control, not measurement. | B_atom |
| `SOPC` / `SOVC` | SPGU output compensation is correction. | B_atom |
| `CORRSER?` | Series correction measurement is calibration. | B_atom |
| `ACH` | Channel remapping is infrastructure. | A_atom |

### Why GNDU is not a C_atom category

The GNDU (Ground Unit) is a passive reference ground terminal. It:
- Has no programmable force/measure commands of its own
- Cannot be swept, pulsed, or configured to measure
- Appears as channel code 'V' in output data only as a reference
- Its only role is topology/reference (connecting DUT terminal to instrument ground)

GNDU connections are handled implicitly through channel topology (B_atom domain). No C_atom surface is needed.

---

## Ambiguities / Questions

| # | Item | Question | Proposed Resolution |
|---|---|---|---|
| 1 | `AIT`/`AAD`/`AV` classification | Are integration time, ADC type, and averaging "measurement configuration" (C) or "instrument setup" (B)? | **C_atom** — these directly determine measurement outcome quality and are meaningless without an associated measurement. They are inseparable from the measurement layer. |
| 2 | Trigger configuration (`TGP`/`TGPC`/`TGXO` etc.) | Is trigger I/O port configuration C (measurement timing) or B (infrastructure)? | **Deferred** — trigger configuration is borderline. It enables synchronization but doesn't force/measure. Keep as B or create a separate trigger-infrastructure category if needed. |
| 3 | `WM` (sweep abort mode) | Is abort-mode configuration C or B? | **C_atom** — it's inseparable from sweep behavior; without it, sweep default behavior may cause compliance-abort that loses data. |
| 4 | SPGU `SRP`/`SPP` vs B_atom abort | Start/stop pulse output is active sourcing (C), but `WGFMU_abort` is B. Why different? | SPGU start/stop are **intended operational commands** (start a pulse train, stop when done). WGFMU abort is an **emergency/abnormal stop**. The distinction is intentional operation vs. emergency recovery. |
| 5 | `C_atom_smu_read_measurement_data` | Should data reading be a separate atom or part of execute? | **Separate** — in real implementation, data may be read incrementally (partial reads, multiple buffer reads). Separating execute from read enables polling and streaming patterns. |
| 6 | WGFMU `update` vs `execute` | `update` applies setup and outputs initial voltage — is that C or B? | **C_atom** — `update` forces a voltage (the pattern's initial voltage) onto the DUT. This is an active output operation. |
| 7 | EasyEXPERT `RUN` granularity | Should there be one `run` atom or separate `run_single`/`run_append`/`run_repeat`? | **Both** — provide a generic `run_selected_test` and convenience variants. The generic atom can take a mode parameter. |
| 8 | `CMM` classification | Is "measurement operation mode" (compliance-side vs force-side measurement) C or B? | **C_atom** — it determines what physical quantity is measured on a channel. Without it, you may measure the wrong thing. |
| 9 | `DSMPLSETUP`/`DSMPLARM`/`DSMPLFLUSH` | Signal monitor commands for MM27/28 — are these C or A (monitoring)? | **C_atom** (P2) — they configure and arm a measurement capture that produces data. The "flush" retrieves that data. |
| 10 | Shared `XE` across SMU and CMU | Both SMU sweeps and CMU sweeps use `XE`. Should it be `C_atom_smu_execute_measurement` only, or also `C_atom_cmu_execute_measurement`? | **Single shared atom** — `C_atom_smu_execute_measurement` serves all MM modes including CMU. The `MM` command already selects the mode. Adding a CMU-specific execute would be redundant. |
| 11 | WGFMU pattern operations: offline vs online | Pattern creation/manipulation is offline (no hardware needed). Should these still be C? | **Yes, C_atom** — they define what will be forced/measured. They are the "measurement definition" layer, analogous to `WV`/`WI` for sweeps. Without them, no WGFMU measurement can occur. |
| 12 | High-speed spot (`TI`/`TV`) vs `HSS` command | `HSS` configures high-speed spot mode. Is it needed as separate atom? | **P2 separate** — `HSS` is a rarely-needed explicit configuration. Most use cases just call `TI`/`TV` directly. |

---

## Summary Statistics

| Category | P0 | P1 | P2 | Total |
|---|---:|---:|---:|---:|
| SMU | 14 | 7 | 12 | 33 |
| WGFMU | 12 | 8 | 7 | 27 |
| SPGU | 0 | 7 | 7 | 14 |
| CMU | 5 | 5 | 9 | 19 |
| HVSMU | 0 | 2 | 1 | 3 |
| HCSMU | 0 | 0 | 2 | 2 |
| UHCU | 0 | 0 | 2 | 2 |
| EasyEXPERT | 0 | 3 | 2 | 5 |
| **Total** | **31** | **32** | **42** | **105** |
