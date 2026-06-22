# Instrument Interaction MCP Tools

This reference documents the fake-but-loadable B1500A MCP tools that do not perform real SMU/WGFMU/SPGU/CMU measurements. These tools define the first MCP surface for connection, status, safety, calibration, and generic instrument control.

All current tools return `fake: true` and `hardware_touched: false`. They are for Cursor/Codex MCP discovery and workflow design only.

Primary sources:

- `B1500A Programming Guide.pdf`, chapter 1 "Programming Basics":
  - Getting Started, especially reset, query response, self-test, self-calibration, diagnostics, channel enable/disable, error reading, timestamp data, status byte, and programming tips.
- `B1500A Programming Guide.pdf`, chapter 4 "Command Reference":
  - Command reference entries for the FLEX commands listed below.
- `B1500A_Intelligent_Test_System_Design.md`:
  - Sections 3.3, 5.3, 6.2, 6.5, 6.7, and 10.

## Tool Map

| MCP tool | Meaning | FLEX / guide basis | Notes |
| --- | --- | --- | --- |
| `connect_b1500` | Future session open, identity query, and module discovery. | `*IDN?`, `UNT?`; Programming Basics "Getting Started"; design doc connection tools. | Fake only. Real implementation must open VISA, set terminators, query identity, discover modules, and create a locked session. |
| `disconnect_b1500` | Future safe disconnect. | `DZ`, `CL`; Programming Basics "To Force 0 V" and "To Disable Source/Measurement Channels". | Real implementation should best-effort zero and disable before closing VISA. |
| `identify_b1500` | Query instrument identity. | `*IDN?`; Programming Basics "To Read Query Response". | Query responses must be read immediately because query response buffer is separate from measurement buffer. |
| `list_installed_modules` | Discover installed module inventory and channel mapping. | `UNT?`; design doc channel numbering section. | Critical before any recipe chooses SMU/WGFMU/SPGU/CMU channels. |
| `get_instrument_status` | Summarize module inventory, status byte, error queue, and safety state. | `UNT?`, `ERRX?`, `*STB?`, `*LRN?`; status byte and error sections. | Should be the first tool used in most workflows. |
| `query_current_settings` | Read current instrument settings. | `*LRN?`; design doc resource `instrument://settings`. | Useful before changing state or after a failed run. |
| `read_error_queue` | Read pending instrument errors. | `ERR?`, `ERRX?`; Programming Basics "To Read Error Code/Message"; Error Messages chapter. | Real implementation should preserve codes/messages in run metadata. |
| `read_status_byte` | Read and decode the GPIB status byte. | Status Byte section; common `*STB?` style query. | Use to diagnose operation state and pending messages. |
| `wait_operation_complete` | Wait for operation completion. | `*OPC?`; Programming Tips "To Confirm the Command Completion". | Use after long operations; do not block indefinitely. |
| `reset_instrument` | Reset to initial settings. | `*RST`; Programming Basics "To Reset the Keysight B1500". | `*RST` must not be combined with other commands in one command string. |
| `initialize_instrument` | Initialize instrument state without treating it as a full reset. | `IN`; design doc system command table. | Should be a dedicated tool, not exposed through raw FLEX. |
| `abort_operation` | Abort the active operation. | `AB`; Command Reference. | `AB` must not be combined with other commands; follow with safe cleanup and error readback. |
| `run_self_test` | Run self-test and return result code. | `*TST?`; Programming Basics "To Perform Self-Test". | Usually run after connect or during diagnostics. |
| `run_self_calibration` | Run self-calibration and return result code. | `*CAL?`; Programming Basics "To Perform Self-Calibration". | Real calibration may take minutes and should be recorded. |
| `run_diagnostics` | Run a diagnostics item. | `DIAG? item`; Programming Basics "To Perform Diagnostics". | Item mapping must be extracted from Command Reference before real use. |
| `set_auto_calibration` | Set auto calibration policy for long jobs. | `CM`; Programming Tips "To Disable the Auto Calibration". | Long unattended runs must make this policy explicit. |
| `set_data_format` | Select output data format. | `FMT mode[, output]`; Data Output Format section. | Initial parser work should prefer ASCII status-header formats such as `FMT 1` or `FMT 5`. |
| `configure_timestamp` | Enable or disable timestamp data. | `TSC mode`; Programming Basics "To Read Time Stamp Data". | Timestamp policy affects parsing and metadata. |
| `reset_timestamp` | Reset timestamp timer. | `TSR`; time data section. | Should be called before time-sensitive acquisitions. |
| `read_timestamp` | Read current timestamp. | `TSQ`; time data section. | Useful for diagnostics and run metadata. |
| `enable_channels` | Enable selected channels. | `CN ch1[,ch2,...]`; Programming Basics "To Enable Source/Measurement Channels". | Real implementation must validate module installation and channel role first. |
| `disable_channels` | Disable selected or all channels. | `CL [ch1,ch2,...]`; Programming Basics "To Disable Source/Measurement Channels". | Empty channel list means all channels. |
| `zero_outputs` | Force selected or all outputs to 0 V. | `DZ [ch]`; Programming Basics "To Force 0 V". | Prefer before disable or disconnect. |
| `zero_all_outputs` | Emergency-style safe cleanup for all channels. | `DZ`, `CL`. | Real implementation should be callable during errors and session cleanup. |
| `confirm_zero_outputs` | Confirm all outputs are within the zero threshold. | `WZ? [timeout]`; Command Reference entry around output-zero confirmation. | Useful before allowing physical contact or re-cabling. |
| `check_interlock_status` | Check high-voltage interlock planning state. | Design doc notes `INTLKVTH?`; User/Configuration guide safety guidance. | Real implementation must verify exact command semantics before use. |
| `run_preflight_checks` | Aggregate fake readiness checks before any recipe. | Combines `UNT?`, error/status queries, station profile, pin map, and policy checks. | This should become the standard gate before measurement tools. |

## Implementation Notes

- Do not add a default `send_raw_flex_command` tool.
- If an expert raw command path is added later, it must be disabled by default, approval-gated, and audited.
- Every real tool should return structured metadata: command basis, parameters, status, warnings, and cleanup result.
- Query responses and measurement data buffers are different. Real tools must consume query responses promptly and not assume measurement data is available after errors.
