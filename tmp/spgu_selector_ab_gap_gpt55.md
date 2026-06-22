# SPGU / Selector / ER* A-B Atom Gap Audit - GPT55

## Current Coverage Summary

Current A/B coverage is broad for generic FLEX session/status, generic channel output safety, ASU/SCUU routing, CMU correction, WGFMU lifecycle/status/output, and EasyEXPERT remote context. It does not yet expose dedicated SPGU/HVSPGU query/readback atoms, SPGU output-switch/pulse-switch atoms, or selector/ER* routing atoms.

Relevant existing coverage:

| Area | Current atom coverage | Gap |
|---|---|---|
| FLEX status/readback | `A_atom_flex_get_status`, `A_atom_flex_query_settings`, `A_atom_flex_read_status_byte`, `A_atom_flex_read_error_queue`, `A_atom_flex_wait_opc` | No SPGU-specific status/setup readback such as `SPST?`, `SIM?`, `SPM?`, `ODSW?`, `ERSSP?`, `ERS?`. |
| Generic output safety | `B_atom_output_b1500_enable_channels`, `B_atom_output_b1500_disable_channels`, `B_atom_output_b1500_zero_outputs`, `B_atom_output_b1500_zero_all`, `B_atom_output_b1500_confirm_zero` | `CNX` is specifically documented for SPGU enable; current `CN`-based atom is not SPGU-aware. |
| Existing routing | `B_atom_routing_asu_*`, `B_atom_routing_scuu_*` | No `ERMOD`, `ERSSP`, `ERM`/`ERC`, module selector, or expander routing/state atoms. |
| SPGU C arbitration | `tmp/c_atom_arbitration.md` assigns SPGU pulse setup/execution to C and status/query-only commands to A | A/B surface still missing the A readbacks and B routing/output preconditions needed by SPGU C atoms. |

Primary sources used:

- B1500A Programming Guide index: SPGU module PDF 140-152, Module Selector PDF 152-153, External Relay Control Output PDF 153, SMU/PG Selector PDF 154, expander sections PDF 155-158, DIO PDF 159-161, command reference summary PDF 320-332.
- Structured command summary: SPGU Control/Pulse/ALWG groups PDF 327 / printed 4-10; Digital I/O and Selectors PDF 328-330 / printed 4-11 to 4-13; expander groups PDF 329-330 / printed 4-12 to 4-13.
- Initial settings: SPGU defaults PDF 178 / printed 2-91; mainframe/DIO defaults PDF 179 / printed 2-92.
- Error codes: `ERMOD 4/8/16` prerequisites for N1265A/N1266A/N1268A at PDF 586 / printed 5-15; SPGU error family PDF 589-592 / printed 5-18 to 5-21.

## Missing A Atom Candidates

| proposed atom | source command(s) | meaning | source pages/refs | why A | priority |
|---|---|---|---|---|---|
| `A_atom_flex_query_spgu_status` | `SPST?` | Read SPGU channel/output status without changing pulse setup or output state. | Command summary SPGU Control PDF 327 / 4-10; SPGU module overview PDF 140-152. | Query-only status/readback; needed before/after SPGU C execution and for diagnostics. | P0 |
| `A_atom_flex_query_spgu_setup` | `SIM?`, `SPRM?`, `SPM?`, `SPPER?`, `SPT?`, `SPV?` | Composite readback of SPGU PG/ALWG mode, run mode, pulse mode, period, timing, and voltage setup. | Command summary SPGU Control/Pulse Setup PDF 327 / 4-10; SPGU defaults PDF 178 / 2-91. | Readback of source configuration; the setters are C, but query-only verification belongs in A. | P0 |
| `A_atom_flex_query_spgu_pulse_switch` | `ODSW?` | Read SPGU pulse switch enable/contact/timing state. | Command summary SPGU Control PDF 327 / 4-10; initial setting pulse switch disable/normally open PDF 178 / 2-91. | Query-only path/switch state readback. | P0 |
| `A_atom_flex_query_spgu_load_impedance` | `SER?` | Read DUT load impedance setting used by SPGU voltage/load calculations. | Command summary SPGU Control PDF 327 / 4-10; initial load impedance 50 ohm PDF 178 / 2-91. | Query-only state verification; setter classification is unclear but readback is A. | P1 |
| `A_atom_flex_query_spgu_trigger_output` | `STGP?` | Read SPGU trigger-output configuration. | Command summary SPGU Control PDF 327 / 4-10; initial trigger output disabled PDF 178 / 2-91. | Query-only external trigger/readback; no DUT output state change. | P1 |
| `A_atom_flex_query_spgu_output_comparison` | `SOPC?`, `SOVC?` | Read SPGU output comparison / compensation setup. | Output Comparison command group PDF 324 / 4-7; SPGU Control references PDF 327 / 4-10. | Query-only readback for correction/comparison state; setters should not be A. | P2 |
| `A_atom_flex_query_spgu_alwg_setup` | `ALW?`, `ALS?` | Read SPGU ALWG waveform/sequence setup metadata. | SPGU ALWG Setup command group PDF 327 / 4-10; SPGU module overview PDF 140-152. | Readback/debug of waveform setup; ALWG definition/execution remains C. | P2 |
| `A_atom_flex_query_selector_status` | `ERS?` | Read module selector status. | Module Selector overview PDF 152-153; Digital I/O and Selectors group PDF 328-330 / 4-11 to 4-13. | Status query for routing hardware; no state change. | P0 |
| `A_atom_flex_query_selector_mode` | `ERMOD?`, `ERSSP?` | Read DIO/module-selector control mode and 16440A SMU/PG selector path. | SMU/PG Selector overview PDF 154; Digital I/O and Selectors group PDF 328-330 / 4-11 to 4-13. | Query-only verification of routing state; needed before pulse/source C atoms. | P0 |
| `A_atom_flex_query_expander_routing_status` | `ERHPA?`, `ERHPL?`, `ERHPS?`, `ERHPP?`, `ERHPE?`, `ERHPR?`, `ERPFUHCA?`, `ERPFGA?`, `ERPFDA?`, `ERPFDP?`, `ERPFDS?`, `ERPFGP?`, `ERPFGR?`, `ERHVCA?`, `ERHVP?`, `ERHVS?`, `ERUHVA?`, `ERCMAA?`, `ERCMAGRD?`, `ERCMAIO?`, `ERPFQG?`, `ERHPQG?` | Composite readback of selector/adapter/expander routing and gate/path state. | Digital I/O and Selectors PDF 328-330; N1265A group PDF 329; N1266A/N1268A/N1272A groups PDF 330. | Query forms are readback/status. Keep broad at first because exact command-page semantics are not yet extracted. | P1 |
| `A_atom_flex_query_expander_health` | `ERPFUHCMAX?`, `ERPFTEMP?` | Read N1265A/UHC expander maximum-current or temperature telemetry/status. | N1265A UHC expander group PDF 329 / 4-12. | Query-only status/telemetry. | P2 |

## Missing B Atom Candidates

| proposed atom | source command(s) | meaning | source pages/refs | why B | priority |
|---|---|---|---|---|---|
| `B_atom_output_spgu_enable_channels` | `CNX` | Enable/connect SPGU output channel switches. | `CNX` detailed record PDF 380 / 4-63; command summary notes CNX for SPGU. | Output switch state changes hardware path; current generic `CN` atom is not SPGU-specific. | P0 |
| `B_atom_output_spgu_disable_channels` | `CL` | Disable/disconnect SPGU channels, ideally with SPGU validation and safe-readback. | `CL` PDF 377 / 4-60; structured record scope includes SPGU. | Output switch state control. Existing generic `CL` may be acceptable, but SPGU-specific schema is missing. | P1 |
| `B_atom_routing_spgu_set_pulse_switch` | `ODSW` | Set SPGU pulse switch enable/contact/timing state. | SPGU Control group PDF 327 / 4-10; initial pulse switch state PDF 178 / 2-91. | Switch/path state change, not pulse waveform definition. | P0 |
| `B_atom_policy_spgu_set_load_impedance` | `SER` | Set SPGU DUT load impedance used for output capability/correction. | SPGU Control group PDF 327 / 4-10; initial load impedance 50 ohm PDF 178 / 2-91; SPGU voltage/load errors PDF 590-592. | State affects allowed output voltage and safety checks; not a measurement execution. | P1 |
| `B_atom_output_spgu_set_trigger_output` | `STGP` | Configure SPGU trigger-output state. | SPGU Control group PDF 327 / 4-10; trigger function overview PDF 162-174. | External trigger output can affect connected hardware; infrastructure state-control, not pulse source data. | P1 |
| `B_atom_correction_spgu_measure_load_impedance` | `CORRSER?` | Perform SPGU load impedance / series correction measurement. | SPGU Control group PDF 327 / 4-10; error 2204 notes `CORRSER?` failure PDF 592 / 5-21. | Query syntax but action performs correction/fixture measurement; analogous to CMU correction B atoms. | P2 |
| `B_atom_routing_selector_set_mode` | `ERMOD` | Set DIO/module selector control mode, including selector and expander modes. | Module Selector PDF 152-153; SMU/PG Selector PDF 154; expander prerequisites error codes require `ERMOD 4/8/16` PDF 586 / 5-15. | Routing/control-mode state; prerequisite for ER* path commands. | P0 |
| `B_atom_routing_selector_set_smu_pg_path` | `ERSSP` | Switch 16440A SMU/Pulse Generator Selector path between SMU and PGU/SPGU. | SMU/PG Selector PDF 154; Digital I/O and Selectors group PDF 328-330 / 4-11 to 4-13. | Physical selector routing; should be explicit B precondition for SPGU/SMU C atoms. | P0 |
| `B_atom_routing_dio_set_mode` | `ERM` | Configure B1500 DIO bit direction/control mode for relay/selector use. | External Relay Control Output PDF 153; Digital I/O Port PDF 159-161; Digital I/O and Selectors group PDF 328-330. | DIO infrastructure state can drive external relays/selectors. | P0 |
| `B_atom_output_dio_set_relay_bits` | `ERC` | Drive external relay control output bits. | External Relay Control Output PDF 153; Digital I/O Port PDF 159-161; command group PDF 328-330. | Directly changes external relay outputs; output/state-control atom. | P0 |
| `B_atom_routing_uhcu_set_path` | `ERPFUHCA`, `ERPFGA`, `ERPFDA`, `ERPFDP`, `ERPFDS`, `ERPFGP`, `ERPFGR` | Configure N1265A/UHC fixture/expander path, gate, discharge, protection, and range-related routing. | N1265A UHC Expander/Fixture PDF 155-157; command group PDF 329 / 4-12; `ERMOD 4` error code PDF 586 / 5-15. | High-current fixture routing and state control. | P1 |
| `B_atom_diagnostic_uhcu_self_test` | `ERPFUHCTST?` | Run/query N1265A UHC expander self-test. | N1265A group PDF 329 / 4-12; UHC overview PDF 155-157. | Diagnostic action even though command is query-form. | P1 |
| `B_atom_calibration_uhcu_self_calibration` | `ERPFUHCCAL?` | Run/query N1265A UHC expander calibration. | N1265A group PDF 329 / 4-12; UHC overview PDF 155-157. | Calibration action; B by existing taxonomy. | P1 |
| `B_atom_routing_hvmcu_set_path` | `ERHVCA`, `ERHVP`, `ERHVS`, `ERHVPV` | Configure N1266A HVSMU current expander path/source/voltage protection state. | N1266A overview PDF 157; command group PDF 330 / 4-13; `ERMOD 8` error code PDF 586 / 5-15. | High-voltage/current expander routing/state. | P1 |
| `B_atom_diagnostic_hvmcu_self_test` | `ERHVCTST?` | Run/query N1266A HVSMU current expander self-test. | N1266A group PDF 330 / 4-13. | Diagnostic action. | P1 |
| `B_atom_routing_uhvu_set_path` | `ERUHVA` | Configure N1268A ultra-high-voltage expander path/state. | N1268A overview PDF 158; command group PDF 330 / 4-13; `ERMOD 16` error code PDF 586 / 5-15. | Ultra-high-voltage routing/state. | P1 |
| `B_atom_routing_selector_adapter_set_path` | `ERHPA`, `ERHPL`, `ERHPS`, `ERHPP`, `ERHPE`, `ERHPR`, `ERCMAA`, `ERCMAGRD`, `ERCMAIO`, `ERCMAPFGD`, `ERPFQG`, `ERHPQG` | Configure B1274A/N1272A/B1506A/B1507A selector/adapter paths and guards. | Digital I/O and Selectors PDF 328-330; N1272A/B1506A/B1507A group PDF 330 / 4-13. | Physical routing/guard/adapter state; needs exact command-page extraction before implementation. | P2 |

## Keep As C / Do Not Add To A-B

These commands are measurement/source/execution primitives or waveform definitions and should stay C, with A/B atoms used only as preconditions or readback:

| command(s) | keep as | reason |
|---|---|---|
| `SIM`, `SPRM`, `SPM`, `SPPER`, `SPT`, `SPV` | C | Configure SPGU PG/ALWG mode, run mode, pulse mode, timing, and voltages. Query forms can be A readbacks. |
| `SPUPD`, `SRP`, `SPP` | C | Apply/start/stop SPGU pulse output. `SPP` may look safety-like, but normal pulse-run stop belongs with SPGU execution; emergency stop remains `AB`/`DZ`/`CL`. |
| `ALW`, `ALS` | C | Define ALWG waveform/pattern/sequence data. Query forms can be A debug/readback. |
| `PT`, `PV`, `PI`, `PWV`, `PWI`, `MCPT`, `MCPNT`, `MCPNX`, `MCPWS`, `MCPWNX` | C | SMU pulse/multi-channel pulse source setup affects measurement waveform and data. |
| `MM`, `XE`, `TI`, `TV`, `TIV`, `TC`, `TTC`, `TTI`, `TTIV`, `TTV` | C | Measurement mode, execution, and measurement-specific data output. |
| `DSMPLSETUP`, `DSMPLARM`, `DSMPLFLUSH` | C | Signal-monitor setup associated with multi-channel pulsed measurement modes. |
| `HVSMUOP` | C | HVSMU operation mode affects source/measurement behavior; query form `HVSMUOP?` could be A if exposed separately. |
| `ERHVPV` | Likely B or C wrapper-dependent | Listed with N1266A expander controls; if it sets a protective path/voltage precondition, keep B; if it defines source voltage, wrap under high-power C. Needs page read. |

## Unclear / Needs Manual Verification

- The source PDFs were not present under the workspace during this audit, so command-specific details beyond the structured index were not re-read. ER* page references are group-level and should be verified against Programming Guide PDF pages 397-434 / printed 4-80 to 4-117 before implementation.
- Exact `ERS?` response semantics need manual extraction: it is clearly selector status, but the fields and whether it covers 16440A, N1258A, and/or expander state should be confirmed.
- `SER` is best treated as B policy/output-safety state in the first pass because it changes SPGU load assumptions and output limits. It could be folded into a C SPGU pulse configuration wrapper later, but a standalone B atom is useful for safe preflight/readback.
- Query-suffixed commands that perform work, especially `CORRSER?`, `ERPFUHCTST?`, `ERPFUHCCAL?`, and `ERHVCTST?`, should not be classified as A merely because they return data. They are B diagnostic/calibration/correction actions.
- `ERHVPV` needs command-page verification to decide whether it is routing/protection state (B) or high-power source configuration (C).
- Existing generic `B_atom_output_b1500_disable_channels`, `B_atom_output_b1500_zero_outputs`, and `B_atom_output_b1500_confirm_zero` may already be acceptable for SPGU cleanup, but their schemas/docs should explicitly mention SPGU/HVSPGU if used that way.

## Recommended First Patch Set

Add these first because they unblock safe SPGU/HVSPGU C atoms and selector path preflights:

1. `A_atom_flex_query_spgu_status` for `SPST?`.
2. `A_atom_flex_query_spgu_setup` for `SIM?`, `SPRM?`, `SPM?`, `SPPER?`, `SPT?`, `SPV?`.
3. `A_atom_flex_query_spgu_pulse_switch` for `ODSW?`.
4. `A_atom_flex_query_selector_status` for `ERS?`.
5. `A_atom_flex_query_selector_mode` for `ERMOD?` and `ERSSP?`.
6. `B_atom_output_spgu_enable_channels` for `CNX`.
7. `B_atom_routing_spgu_set_pulse_switch` for `ODSW`.
8. `B_atom_routing_selector_set_mode` for `ERMOD`.
9. `B_atom_routing_selector_set_smu_pg_path` for `ERSSP`.
10. `B_atom_routing_dio_set_mode` and `B_atom_output_dio_set_relay_bits` for `ERM`/`ERC`.

Candidate counts in this audit:

- Missing A atom candidates: 11.
- Missing B atom candidates: 17.
- First patch set: 10 high-value additions, with ER* expander composites deferred until individual command pages are extracted.
