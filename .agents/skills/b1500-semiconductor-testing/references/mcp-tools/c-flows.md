# C Flow MCP Tools

C flows are fake, orchestration-only measurement tools. They compose current
`C_atom_*` functions serially and preserve each child payload. They never call
A/B atoms or flows, perform real hardware I/O, or establish instrument safety.

```text
C_flow_<measurement_family>_<object>_<subject>
```

Families: `spot`, `sweep`, `pulse`, `waveform`, `sampling`, `search`, `remote`.
Thirty tools are registered. Device experiments and complete safe transactions
belong to future ABC flows/recipes.

## Execution and Response Contract

Inputs use Pydantic request models from `schemas/c_flow.py`, exposed as nested
MCP `request` schemas. Omit optional requests for synthetic example defaults;
WGFMU and SPGU waveform requests require explicit waveform content. Unknown
fields, non-finite values, invalid counts and basic inconsistent geometry are
rejected before any atom is called. These checks are structural, not a station
policy, hardware timing certification, or an approval mechanism.

The response retains the A/B flow conventions: `flow`, `flow_class: "C"`,
`category`, `object`, `subject`, `fake`, `hardware_touched`, `ok`, `partial`,
`destructive`, `consumptive`, `atoms_called`, `atom_results`, `inputs`, `outputs`,
`warnings`, and `purpose`. Audit records include phase, UTC timestamp, inputs,
status and the unchanged child result (or exception). Failed attempted calls are
included in `atoms_called`; skipped calls are excluded.

Additional fields:

- `execution_state`: `simulated_complete`, `configuration_only`,
  `awaiting_completion`, or `failed`.
- `simulation_completed`: synchronous fake execution completed and no later step failed.
- `measurement_completed`: always false; no physical measurement has occurred.
- `required_preconditions`: external readiness requirements and atom dependencies;
  this is a requirements list, not evidence that prerequisites passed.
- `contract_gaps`: missing fields/semantics in the current atom interfaces.
- `cleanup`: outer ABC transaction responsibility; `performed` is always false.

`ok` means composition did not fail; it does not mean hardware or prerequisites
are ready. `partial` is true for configuration gaps, pending execution or failure.
`destructive` describes configuration/source side effects the composition would
have on real hardware. `consumptive` marks attempted FLEX measurement-buffer
reads; WGFMU library-array reads are not labeled destructive buffer drains.
`outputs.data` contains only returned synthetic samples/arrays, never fabricated
sweep curves. Empty arrays remain empty and do not certify data quality.

The first atom exception, explicit failure or unexpected non-fake result stops
later work. Earlier evidence is retained and later steps are recorded as skipped.
A fake execution result with `status: fake_complete` (or an immediate synthetic
spot sample) permits subsequent C-specific reads. A started/unknown result skips
reads and requires outer completion checking. There are no sleeps, polling loops,
parallel instrument calls, implicit retries, raw commands or hidden A/B calls.

## Shared Setup Sequences

The tables below spell out exact atom names. Repeated names correspond to serial
per-channel or per-vector/event calls. `execute/read skipped` means the catalog
records those intended steps but does not invoke them while contract gaps remain.

- SMU setup: `C_atom_smu_configure_integration`, followed by
  `C_atom_smu_set_measurement_ranging` for each measurement channel.
- CMU setup: `C_atom_cmu_set_impedance_model` ->
  `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` ->
  `C_atom_cmu_set_monitor_output`. CMU-specific execute atoms contain their MM/XE
  intent; no SMU MM atom is used to configure a CMU.
- `run.collect=False` omits buffered C reads. Immediate high-speed/DC samples are
  integral to their measurement atoms. `run.max_items` bounds requested readout;
  it does not guarantee all requested measurement points were collected.
- SMU `source=current` replaces `C_atom_smu_force_voltage` with
  `C_atom_smu_force_current`. Compliance is in A for voltage forcing and V for
  current forcing. Device-specific measurement functions/ranges are explicit.

## Spot Tools

| Flow | Request | Ordered Atom Sequence | Purpose / Completion |
|---|---|---|---|
| `C_flow_spot_smu_iv` | `SmuSpot` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_force_voltage` -> `C_atom_smu_execute` -> `C_atom_smu_read_measurement_data` | Single-channel voltage/current source and normal spot acquisition. `simulated_complete`. |
| `C_flow_spot_smu_high_speed` | `SmuHighSpeed` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_configure_high_speed_spot` -> `C_atom_smu_force_voltage` -> `C_atom_smu_measure_high_speed_spot` | High-speed spot with an inline synthetic sample. `simulated_complete`. |
| `C_flow_spot_wgfmu_dc` | `WgfmuDc` | `C_atom_wgfmu_set_operation_mode` -> `C_atom_wgfmu_configure_force_measure_ranges` -> `C_atom_wgfmu_set_measure_mode` -> `C_atom_wgfmu_dc_force_measure` | DC force/measure with optional averaging. `simulated_complete`. |
| `C_flow_spot_cmu_impedance` | `CmuSetup` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_execute_spot_c` -> `C_atom_cmu_read_measurement_data` | Normal spot capacitance/impedance with optional monitor columns. `simulated_complete`. |
| `C_flow_spot_cmu_high_speed` | `CmuSetup` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_measure_high_speed_spot` | High-speed CMU spot with inline synthetic data. `simulated_complete`. |

## Sweep Tools

| Flow | Request | Ordered Atom Sequence | Purpose / Completion |
|---|---|---|---|
| `C_flow_sweep_smu_staircase` | `SmuSweep` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_sweep_timing` -> `C_atom_smu_configure_sweep_abort` -> `C_atom_smu_configure_staircase_sweep` -> `C_atom_smu_execute` -> `C_atom_smu_read_measurement_data` | Primary staircase IV sweep. `simulated_complete`. |
| `C_flow_sweep_smu_synchronous` | `SynchronousSweep` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_sweep_timing` -> `C_atom_smu_configure_sweep_abort` -> `C_atom_smu_configure_staircase_sweep` -> `C_atom_smu_configure_synchronous_sweep_source` -> `C_atom_smu_execute` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | Primary and synchronous source trajectories. `configuration_only`. Synchronous source atom omits independent compliance and source range. |
| `C_flow_sweep_smu_multi_channel` | `MultiSweep` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_sweep_timing` -> `C_atom_smu_configure_sweep_abort` -> `C_atom_smu_configure_staircase_sweep` -> `C_atom_smu_configure_multi_sweep` -> `C_atom_smu_execute` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | Multi-channel sweep configuration. `configuration_only`. WNX atom omits per-channel trajectories, ranges and compliance. |
| `C_flow_sweep_smu_qscv` | `Qscv` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_qscv` -> `C_atom_smu_execute_qscv` -> `C_atom_smu_read_measurement_data` | SMU quasi-static capacitance sweep after external correction/leakage validation. `simulated_complete`. |
| `C_flow_sweep_cmu_cv` | `CmuSweep` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_configure_cv_dc_sweep` -> `C_atom_cmu_execute_cv_dc_sweep` -> `C_atom_cmu_read_measurement_data` | CMU cv sweep with mode-specific timing. `simulated_complete`. |
| `C_flow_sweep_cmu_cf` | `CmuSweep` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_configure_cf_sweep` -> `C_atom_cmu_execute_cf_sweep` -> `C_atom_cmu_read_measurement_data` | CMU cf sweep with mode-specific timing. `simulated_complete`. |
| `C_flow_sweep_cmu_ac_level` | `CmuSweep` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_configure_ac_level_sweep` -> `C_atom_cmu_execute_ac_level_sweep` -> `C_atom_cmu_read_measurement_data` | CMU ac_level sweep with mode-specific timing. `simulated_complete`. |

## Pulse Tools

| Flow | Request | Ordered Atom Sequence | Purpose / Completion |
|---|---|---|---|
| `C_flow_pulse_smu_spot` | `SmuPulse` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_pulse_timing` -> `C_atom_smu_configure_pulsed_spot_source` -> `C_atom_smu_execute_pulsed_spot` -> `C_atom_smu_read_measurement_data` | Single-channel parameterized pulsed spot measurement. `simulated_complete`. |
| `C_flow_pulse_smu_sweep` | `SmuPulseSweep` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_pulse_timing` -> `C_atom_smu_configure_pulsed_sweep` -> `C_atom_smu_execute_pulsed_sweep` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | Parameterized pulsed sweep configuration. `configuration_only`. PWV/PWI atom omits base level, compliance and source range. |
| `C_flow_pulse_smu_staircase_pulsed_bias` | `PulsedBias` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_pulse_timing` -> `C_atom_smu_configure_staircase_sweep_pulsed_bias` -> `C_atom_smu_execute` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | Staircase sweep with a distinct pulsed bias channel. `configuration_only`. Combined sweep/bias atom omits independent channel compliance. |
| `C_flow_pulse_smu_multi_channel` | `MultiPulse` | `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_multi_pulsed` -> `C_atom_smu_execute` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | Multi-channel pulsed spot/sweep configuration. `configuration_only`. MCP atom omits per-channel source/base/pulse/compliance settings. |
| `C_flow_pulse_smu_quasi` | `QuasiPulse` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_quasi_pulse` -> `C_atom_smu_execute` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | Quasi-pulsed spot configuration. `configuration_only`. BD atom omits compliance and complete measurement configuration. |
| `C_flow_pulse_spgu_train` | `SpguPulse` | `C_atom_spgu_set_operation_mode` -> `C_atom_spgu_set_load_impedance` -> `C_atom_spgu_configure_pg_pulse` -> `C_atom_spgu_update_output` -> `C_atom_spgu_start_output` | Start a bounded pulse train; source-only, no acquisition. `awaiting_completion`. |
| `C_flow_pulse_cmu_spot` | `CmuPulse` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_configure_pulsed_spot_c` -> `C_atom_cmu_execute_pulsed_spot_c` -> `C_atom_cmu_read_measurement_data` | Pulsed spot capacitance/impedance. `simulated_complete`. |
| `C_flow_pulse_cmu_cv` | `CmuPulseSweep` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_configure_pulsed_cv_sweep` -> `C_atom_cmu_execute_pulsed_cv_sweep` -> `C_atom_cmu_read_measurement_data` | Pulsed capacitance-voltage sweep. `simulated_complete`. |

## Waveform Tools

| Flow | Request | Ordered Atom Sequence | Purpose / Completion |
|---|---|---|---|
| `C_flow_waveform_wgfmu_acquire` | `WgfmuWaveform` | `C_atom_wgfmu_set_operation_mode` -> `C_atom_wgfmu_configure_force_measure_ranges` -> `C_atom_wgfmu_set_measure_mode` -> `C_atom_wgfmu_set_measure_enabled` -> `C_atom_wgfmu_create_pattern` -> `C_atom_wgfmu_add_vectors` -> `C_atom_wgfmu_set_measure_event` -> `C_atom_wgfmu_add_sequence` -> `C_atom_wgfmu_update` -> `C_atom_wgfmu_execute` -> `C_atom_wgfmu_read_measurement_values` | Bounded multi-channel waveform and measurement-event acquisition. `simulated_complete`. |
| `C_flow_waveform_spgu_sequence` | `SpguWaveform` | `C_atom_spgu_set_operation_mode` -> `C_atom_spgu_set_load_impedance` -> `C_atom_spgu_create_alwg_pattern` -> `C_atom_spgu_add_alwg_sequence` -> `C_atom_spgu_update_output` -> `C_atom_spgu_start_output` | Start a bounded ALWG sequence; source-only. `awaiting_completion`. |

## Sampling Tools

| Flow | Request | Ordered Atom Sequence | Purpose / Completion |
|---|---|---|---|
| `C_flow_sampling_smu_iv_time` | `SmuSampling` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_sampling` -> `C_atom_smu_execute_sampling` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | SMU time-sampling configuration. `configuration_only`. Sampling atom omits explicit MI/MV base, bias and compliance settings. |
| `C_flow_sampling_smu_signal_monitor` | `SignalMonitor` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_configure_signal_monitor` | Signal-monitor acquisition configuration only. `configuration_only`. DSMPL atom lacks a dedicated execution/completion contract; no MM is invented. |
| `C_flow_sampling_smu_spgu_bias` | `SpguSampling` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_sampling` -> `C_atom_spgu_configure_sampling_pulse` -> `C_atom_smu_execute_sampling` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | SMU sampling with SPGU pulse bias. `configuration_only`. Sampling atom omits explicit MI/MV base, bias and compliance settings. |
| `C_flow_sampling_cmu_ct` | `CmuSampling` | `C_atom_cmu_set_impedance_model` -> `C_atom_cmu_configure_signal` -> `C_atom_cmu_set_ranging_integration` -> `C_atom_cmu_set_monitor_output` -> `C_atom_cmu_configure_ct_sampling` -> `C_atom_cmu_execute_ct_sampling` -> `C_atom_cmu_read_measurement_data` | Capacitance-time sampling at declared DC bias. `simulated_complete`. |

## Search Tools

| Flow | Request | Ordered Atom Sequence | Purpose / Completion |
|---|---|---|---|
| `C_flow_search_smu_target` | `Search` | `C_atom_smu_configure_integration` -> `C_atom_smu_set_measurement_ranging` -> `C_atom_smu_set_measurement_mode` -> `C_atom_smu_configure_search` -> `C_atom_smu_execute` (skipped) -> `C_atom_smu_read_measurement_data` (skipped) | Instrument linear/binary target-search configuration. `configuration_only`. Search atom omits source/sense functions, start, step, tolerance and compliance. |

## Remote Tools

| Flow | Request | Ordered Atom Sequence | Purpose / Completion |
|---|---|---|---|
| `C_flow_remote_easyexpert_selected_test` | `RemoteRun` | `C_atom_easyexpert_run_selected_test` | Execute the selected remote test. `simulated_complete`. |
| `C_flow_remote_easyexpert_repeat` | `RemoteRepeat` | `C_atom_easyexpert_repeat_run_selected_test` | Repeat the selected remote test. `simulated_complete`. |
| `C_flow_remote_easyexpert_quick_sequence` | `RemoteSequence` | `C_atom_easyexpert_run_quick_test_sequence` | Run an existing remote Quick Test sequence. `simulated_complete`. |

## Conditional Steps and Input Details

| Request / Flow group | Input contract and variants |
|---|---|
| `SmuSpot`, `SmuHighSpeed` | Channel, voltage/current source, level, compliance, compliance polarity, source range, integration/ranging; high-speed adds measurement type and timestamp. High-speed requires the high-speed ADC and uses HSS then TI/TV/TIV, never MM/XE. |
| `SmuSweep` | Channel, source, start/stop/steps, compliance, linear/positive-log/negative-log, polarity, WT timing, abort/post-output and run/read options. |
| `SynchronousSweep`, `MultiSweep` | Primary sweep plus secondary channel/trajectory or unique channel list containing the primary. Independent secondary/per-channel source contracts are missing. |
| `Qscv` | Channel, voltage endpoints, steps, leakage integration time and measurement voltage; external QSZ/correction/leakage prerequisites remain required. |
| `SmuPulse` | Source, base/pulse levels, compliance, delay/width/period; PT is always before PV/PI. |
| `SmuPulseSweep`, `PulsedBias` | Pulse timing and sweep endpoints; bias variant adds a distinct bias channel and base/pulse levels. The current atoms omit required compliance details. |
| `MultiPulse`, `QuasiPulse` | MM27/28 selected by pulsed spot/sweep mode, or MM9 with BD geometry. Execution is skipped for incomplete source contracts. |
| `SmuSampling`, `SpguSampling` | Unique measurement channels including source channel, interval/count, linear/log mode, base hold and post-output. SPGU variant adds a distinct SPGU channel and pulse geometry after sampling setup. No selector switching is performed. |
| `SignalMonitor` | Unique channels, integration/ranging, interval and sample count. No undocumented MM mode or generic XE is invented for DSMPL. |
| `Search` | Linear/binary, target and limit; MM14/MM15 respectively. Missing source/sense/start/step/tolerance/compliance remain explicit. |
| `CmuSetup` | Channel, impedance model, frequency, AC amplitude, DC bias, range/integration and monitor selection; CMU high-speed uses timestamped direct spot. |
| `CmuSweep` | Shared CMU setup plus endpoints (Hz for cf, V otherwise), points and CMU-specific timing/abort. Frequency and AC-amplitude endpoints must be positive. |
| `CmuPulse`, `CmuPulseSweep`, `CmuSampling` | Shared CMU setup plus pulse base/bias or sweep endpoints and pulse width/period, or sampling interval/count. CMU commands remain PTDCV/PDCV/PWDCV/MDCV/MTDCV, not SMU timing commands. |
| `WgfmuDc` | Channel, voltage, force/current ranges. `averaged=True` appends `C_atom_wgfmu_dc_measure_averaged` after the immediate force/measure. DC mode does not call waveform measurement-enable or create patterns. |
| `WgfmuWaveform` | Explicit unique channels/patterns, incremental vectors, measurement events and bounded repeats. For voltage measurement, `C_atom_wgfmu_set_measure_voltage_range` follows measure-mode selection. Each vector calls add_vectors(count=1); each event calls set_measure_event. All channel sequences are defined before one update and one execute; reads fan out serially per channel. Pattern-name collisions with earlier session state require external context validation. |
| `SpguPulse` | Load, two/three-level mode, source number, period/delay/width/edges, base/peaks and finite count. Free-run count=0 is rejected by this flow. |
| `SpguWaveform` | Explicit ALWG levels, pattern name, initial level, period, repeat/loop fields and finite output count. Updates and starts output without calling PG configuration or stopping immediately. |
| `RemoteRun`, `RemoteRepeat`, `RemoteSequence` | Timeout and, respectively, bounded repeat count or existing sequence name. These are deliberately thin execution adapters; repetition is one atom invocation, not a Python loop. |

## External Readiness and Cleanup

Before real use, an outer transaction must verify identity/inventory, channel
roles, DUT pin map, source and compliance envelopes, interlock, required human
approval, enabled outputs and installed cleanup. FLEX data consumers additionally
require parser/timestamp/buffer preparation. A read limit is not a completeness
check; the future acquisition layer must verify expected point counts and status
codes before accepting data.

WGFMU requires external protection (no output current limiter), validated ranges,
timing, event spacing, memory budget, and session pattern context. Structural
request validation does not replace these checks. SPGU requires verified load,
compensation, selector routing and trigger topology. ALWG update currently inherits
a PG-specific prerequisite label from the existing update atom; the flow preserves
that limitation rather than adding an inappropriate PG configuration step.

CMU and QSCV remain fake compositions: correction freshness, SCUU/topology and
leakage validation must be implemented before real execution. No C flow performs
correction or claims a fixture is ready. EasyEXPERT requires an already selected,
approved software context; wait/error checks and result fetch remain A-class.

Normal SPGU completion/stop is handed to the outer layer. All real failures must
reach an endpoint-appropriate safe state (abort, zero/disable, disconnect or
standby) and verify it. `cleanup.performed=false` is intentional; a pure C flow
must never advertise itself as a complete safe shutdown transaction.

## Reserved / Not Duplicated

- High-power flows: current HVSMU/HCSMU/UHCU/HVMCU/UHVU wrapper atoms lack explicit
  mode/points/completion/read contracts. Keep existing atoms until meaningful
  spot/sweep/pulse compositions can be specified; no generic high-power category.
- Timer-start helpers, waveform transforms, trigger events and partial event reads
  remain atoms. They do not each require a same-name flow wrapper.
- Id-Vg/Id-Vd, FeFET program/read, PUND, endurance and retention belong to device
  recipes/ABC workflows with their own limits and stop conditions.
- Full transaction approval, safety validation, persistence and recovery are outer
  layer responsibilities, not inferred from a fake flow result.

## Sources and Implementation

- `tmp/c_flow_design_arbitration.md`: taxonomy, accepted catalog and gap decisions.
- `src/b1500_test_agent/mcp/c_flows.py`: serial composition and failure handling.
- `src/b1500_test_agent/schemas/c_flow.py`: typed request contracts.
- `references/manuals/structured/b1500a-command-parameters.md`: existing MM/XE table.
- `tests/test_c_flows.py`: ordering, boundaries, failure/read gating and MCP discovery.

No new hardware command semantics are claimed by this catalog. Exact command
syntax and safety behavior still need manual and hardware validation before
replacing any fake atom with a real transport operation.
