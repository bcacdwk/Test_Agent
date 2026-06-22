# SPGU / Selector / ER* A-B Atom Gap Audit — Opus46

Date: 2026-06-22  
Auditor: opus-4.6-max  
Status: gap analysis only — do not implement from this file without a separate task.

Inputs:
- `src/b1500_test_agent/mcp/a_atoms.py` (53 A atoms: 18 flex, 16 wgfmu, 19 easyexpert)
- `src/b1500_test_agent/mcp/b_atoms.py` (36 B atoms)
- `.agents/skills/.../references/mcp-tools/a-atoms.md`, `b-atoms.md`
- `references/manuals/structured/b1500a-command-summary.yaml` (grouped command index)
- `references/manuals/structured/b1500a-command-parameters.md`
- `references/manuals/structured/b1500a-initial-settings.md`
- `references/manuals/b1500a-programming-guide-index.md`
- `tmp/c_atom_arbitration.md`
- `Keysight 16440A SMUPulse Generator Selector.pdf`

---

## Current Coverage Summary

### A Atoms (53 total)

| Interface   | Count | Covers                                                     |
|-------------|------:|--------------------------------------------------------------|
| `flex`      |    18 | connection, identity, module list, status, error queue, status byte, OPC, data format, timestamp, output buffer, SRQ |
| `wgfmu`     |    16 | session, channel IDs, status, clear, logging, error/warning, export, event completion |
| `easyexpert`|    19 | identity, status, error, OPC, workspaces, result format/fetch, app/preset catalog, device tag, repeat count, setup params |

**Zero A atoms exist for:** SPGU query/status, selector/DIO query, expander query, HVSMU query.

### B Atoms (36 total)

| Category     | Count | Targets                                   |
|--------------|------:|-------------------------------------------|
| lifecycle    |     4 | b1500 reset/init, wgfmu init/abort        |
| safety       |     4 | b1500 abort/interlock/preflight, easyexpert abort |
| output       |    11 | b1500 channels/zero, smu filter/resistor, wgfmu connect/disconnect, easyexpert standby |
| diagnostic   |     3 | b1500 self-test/diag, wgfmu self-test     |
| calibration  |     7 | b1500/smu/wgfmu cal, easyexpert zero-cancel |
| routing      |     5 | asu path/1pA/indicator, scuu path/indicator |
| correction   |     6 | cmu correction set/measure/phase/clear, qscv offset |
| policy       |     2 | auto-cal, wgfmu warn-as-error             |

**Zero B atoms exist for:** SPGU channel enable/disable, SPGU pulse switch, 16440A selector routing, DIO mode/output, module selector mode, any expander routing/diagnostic/calibration.

### Command Groups with No A or B Representation

From `b1500a-command-summary.yaml` grouped command index:

| Group                                     | Commands (set + query) | Current A/B |
|-------------------------------------------|----------------------:|-------------|
| SPGU Control                              | 15                    | **none**    |
| SPGU Pulse Setup                          |  8                    | **none**    |
| SPGU ALWG Setup                           |  4                    | **none**    |
| Output Comparison (SOPC/SOVC)             |  4                    | **none**    |
| Digital I/O and Selectors                 | 19                    | **none**    |
| N1265A UHC Expander/Fixture               | 17                    | **none**    |
| N1266A HVSMU Current Expander             |  8                    | **none**    |
| N1268A UHV Expander                       |  2                    | **none**    |
| N1272A/B1506A/B1507A Selector/Adapter     | 11                    | **none**    |
| HVSMU Control                             |  2 (excl VAR)         | **none**    |

---

## Missing A Atom Candidates

Classification rule: A atoms are read-only status/query commands. They do not change DUT output state, routing, or instrument operating mode. Query forms of set commands (`CMD?`) are A when the set form is B or C.

### SPGU Status / Query Commands

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why A | Priority |
|---|---|---|---|---|---|---|
| 1 | `A_atom_flex_query_spgu_status` | `SPST?` | Query SPGU channel execution status (running, idle, etc.) | PDF 515 / 4-198 | Pure status readback; does not alter output or execution state | **P0** |
| 2 | `A_atom_flex_query_spgu_operation_mode` | `SIM?` | Query SPGU operation mode (PG vs ALWG) | PDF 508 / 4-191 | Read-only query of current mode | P1 |
| 3 | `A_atom_flex_query_spgu_channel_mode` | `SPRM?` | Query SPGU per-channel output operation mode (free run, etc.) | PDF 515 / 4-198 | Read-only query | P1 |
| 4 | `A_atom_flex_query_spgu_pulse_mode` | `SPM?` | Query SPGU per-channel pulse output mode (2-level, 3-level, etc.) | PDF 512 / 4-195 | Read-only query | P1 |
| 5 | `A_atom_flex_query_spgu_pulse_period` | `SPPER?` | Query SPGU pulse period | PDF 514 / 4-197 | Read-only query | P1 |
| 6 | `A_atom_flex_query_spgu_pulse_timing` | `SPT?` | Query SPGU pulse timing (delay, width, leading, trailing) | PDF 515 / 4-198 | Read-only query | P1 |
| 7 | `A_atom_flex_query_spgu_pulse_voltage` | `SPV?` | Query SPGU pulse voltage (base, peak per source) | PDF 515-516 / 4-198-199 | Read-only query | P1 |
| 8 | `A_atom_flex_query_spgu_pulse_switch` | `ODSW?` | Query SPGU pulse switch state (enabled/disabled, timing) | PDF 478 / 4-161 | Read-only query of switch state | **P0** |
| 9 | `A_atom_flex_query_spgu_trigger_output` | `STGP?` | Query SPGU trigger output configuration | PDF 522 / 4-205 | Read-only query | P2 |
| 10 | `A_atom_flex_query_spgu_load_impedance` | `SER?` | Query SPGU DUT load impedance setting | PDF 507 / 4-190 | Read-only query | P1 |
| 11 | `A_atom_flex_query_spgu_open_comp` | `SOPC?` | Query SPGU open compensation status | PDF 510 / 4-193 | Read-only query of compensation enable/data | P2 |
| 12 | `A_atom_flex_query_spgu_short_comp` | `SOVC?` | Query SPGU short compensation status | PDF 511 / 4-194 | Read-only query of compensation enable/data | P2 |
| 13 | `A_atom_flex_query_spgu_alwg_pattern` | `ALW?` | Query ALWG waveform pattern data | PDF 356 / 4-39 | Read-only query of configured pattern | P2 |
| 14 | `A_atom_flex_query_spgu_alwg_sequence` | `ALS?` | Query ALWG sequence assignment | PDF 356 / 4-39 | Read-only query of configured sequence | P2 |
| 15 | `A_atom_flex_query_spgu_series_correction` | `CORRSER?` | Measure/query SPGU output path series resistance | PDF 384 / 4-67 | Query/measurement for calibration data (but see note¹) | P2 |

¹ `CORRSER?` performs an actual measurement to return resistance. It could also be classified as B (correction), analogous to `B_atom_correction_cmu_measure_data` / `CORR?`. See **Unclear** section.

### Selector / DIO / Module Selector Query Commands

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why A | Priority |
|---|---|---|---|---|---|---|
| 16 | `A_atom_flex_query_selector_status` | `ERS?` | Query module selector connection/status | PDF 431 / 4-114 | Read-only status; no path change | **P0** |
| 17 | `A_atom_flex_query_selector_mode` | `ERMOD?` | Query module selector DIO mode setting | PDF 427 / 4-110 | Read-only mode query | **P0** |
| 18 | `A_atom_flex_query_smu_pg_selector` | `ERSSP?` | Query 16440A SMU/PG selector path state (SMU on / PGU on / open / PGU open) | PDF 432 / 4-115 | Read-only path status for 16440A selector | **P0** |

### Expander Query Commands

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why A | Priority |
|---|---|---|---|---|---|---|
| 19 | `A_atom_flex_query_uhc_operation` | `ERPFUHCA?` | Query N1265A UHC fixture operation status | PDF 417 / 4-100 | Read-only status query | P2 |
| 20 | `A_atom_flex_query_uhc_max_current` | `ERPFUHCMAX?` | Query N1265A UHC max current capability | PDF 422 / 4-105 | Read-only capability query | P2 |
| 21 | `A_atom_flex_query_uhc_temperature` | `ERPFTEMP?` | Query N1265A fixture temperature | PDF 428 / 4-111 | Read-only sensor readback | P2 |
| 22 | `A_atom_flex_query_hvmc_operation` | `ERHVCA?` | Query N1266A HVMC expander operation status | PDF 406 / 4-89 | Read-only status query | P2 |
| 23 | `A_atom_flex_query_uhv_operation` | `ERUHVA?` | Query N1268A UHV expander operation status | PDF 433 / 4-116 | Read-only status query | P2 |
| 24 | `A_atom_flex_query_hvsmu_operation_mode` | `HVSMUOP?` | Query HVSMU operation mode | PDF 438 / 4-121 | Read-only mode readback | P2 |

### B1274A Adapter Query Commands (B1505A/B1506A specific)

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why A | Priority |
|---|---|---|---|---|---|---|
| 25 | `A_atom_flex_query_adapter_path` | `ERHPA?` | Query B1274A adapter input path state | PDF 403 / 4-86 | Read-only | P3 |
| 26 | `A_atom_flex_query_adapter_indicator` | `ERHPL?` | Query B1274A adapter LED state | PDF 408 / 4-91 | Read-only | P3 |
| 27 | `A_atom_flex_query_adapter_status` | `ERHPS?` | Query B1274A adapter connection status | PDF 410 / 4-93 | Read-only | P3 |
| 28 | `A_atom_flex_query_adapter_port` | `ERHPP?` | Query B1274A adapter port state | PDF 409 / 4-92 | Read-only | P3 |

### N1272A/B1506A Selector Query Commands

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why A | Priority |
|---|---|---|---|---|---|---|
| 29 | `A_atom_flex_query_n1272_input` | `ERCMAA?` | Query N1272A selector input setting | PDF 399 / 4-82 | Read-only | P3 |
| 30 | `A_atom_flex_query_n1272_guard_relay` | `ERCMAGRD?` | Query N1272A guard relay state | PDF 400 / 4-83 | Read-only | P3 |
| 31 | `A_atom_flex_query_n1272_io_relay` | `ERCMAIO?` | Query N1272A I/O relay state | PDF 401 / 4-84 | Read-only | P3 |

**Total missing A candidates: 31** (6 P0, 8 P1, 12 P2, 5 P3)

---

## Missing B Atom Candidates

Classification rule: B atoms change instrument state (output switches, path routing, diagnostic/calibration operations, mode settings that affect safety or routing) but do not configure measurement parameters or execute measurement/source operations.

### SPGU Output / Channel Control

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 1 | `B_atom_output_spgu_enable_channels` | `CNX` | Enable SPGU channel output switches | PDF 380 / 4-63 | Directly analogous to `B_atom_output_b1500_enable_channels` (CN); output switch state change | **P0** |
| 2 | `B_atom_output_spgu_set_pulse_switch` | `ODSW` | Set SPGU pulse switch state (enable/disable, timing) — controls whether pulse reaches DUT via semiconductor relay | PDF 478 / 4-161 | Output path state control; the pulse switch is a physical relay that connects/disconnects SPGU output | **P0** |

### 16440A SMU/PG Selector Path Routing

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 3 | `B_atom_routing_selector_set_smu_pg` | `ERSSP` | Switch 16440A selector channel to SMU-on / PGU-on / all-open / PGU-open state | PDF 431-432 / 4-114-115 | Physical relay path switching between SMU and PGU/SPGU at DUT; safety-critical for stress/measure workflows | **P0** |
| 4 | `B_atom_routing_selector_set_mode` | `ERMOD` | Set module selector DIO operation mode (normal DIO, N1258A selector, N1265A UHC, N1268A UHV, etc.) | PDF 426-427 / 4-109-110 | Configures DIO port routing purpose; must precede selector/expander control | **P0** |

### Digital I/O Port Control

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 5 | `B_atom_routing_dio_set_mode` | `ERM` | Set DIO port bit direction (input vs output) | PDF 425 / 4-108 | Configures hardware I/O direction; wrong setting can affect external relay control | P1 |
| 6 | `B_atom_routing_dio_set_output` | `ERC` | Set DIO output data bits for external relay or trigger control | PDF 398 / 4-81 | Drives external relay/trigger hardware state | P1 |

### Expander Routing / State Control

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 7 | `B_atom_routing_uhc_set_operation` | `ERPFUHCA` | Set N1265A UHC fixture operation (channel assignment, operating mode) | PDF 417-418 / 4-100-101 | Expander path/mode state change; requires ERMOD 4 | P2 |
| 8 | `B_atom_routing_hvmc_set_operation` | `ERHVCA` | Set N1266A HVMC expander operation (enable/disable HVSMU+MCSMU combination) | PDF 406 / 4-89 | Expander state change | P2 |
| 9 | `B_atom_routing_uhv_set_operation` | `ERUHVA` | Set N1268A UHV expander operation | PDF 433 / 4-116 | Expander state change; requires ERMOD 16 | P2 |
| 10 | `B_atom_routing_adapter_set_path` | `ERHPA` | Set B1274A adapter input path | PDF 403 / 4-86 | Physical relay path switching | P3 |
| 11 | `B_atom_routing_adapter_set_indicator` | `ERHPL` | Set B1274A adapter LED indicator | PDF 408 / 4-91 | Indicator state change (analogous to ASU/SCUU indicator B atoms) | P3 |

### N1272A/B1506A Selector Routing

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 12 | `B_atom_routing_n1272_set_input` | `ERCMAA` | Set N1272A/B1506A module selector input path | PDF 399 / 4-82 | Physical selector path routing | P3 |
| 13 | `B_atom_routing_n1272_set_guard_relay` | `ERCMAGRD` | Set N1272A guard relay | PDF 400 / 4-83 | Guard path relay state | P3 |
| 14 | `B_atom_routing_n1272_set_io_relay` | `ERCMAIO` | Set N1272A I/O relay | PDF 401 / 4-84 | I/O relay state | P3 |
| 15 | `B_atom_routing_n1272_set_force_guard` | `ERCMAPFGD` | Set N1272A preamp force-guard-disable | PDF 402 / 4-85 | Guard path configuration | P3 |

### Expander Diagnostic / Calibration

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 16 | `B_atom_diagnostic_uhc_self_test` | `ERPFUHCTST?` | Run N1265A UHC fixture self-test | PDF 422-423 / 4-105-106 | Diagnostic operation; analogous to `B_atom_diagnostic_b1500_self_test` | P2 |
| 17 | `B_atom_calibration_uhc_self_calibration` | `ERPFUHCCAL?` | Run N1265A UHC fixture self-calibration | PDF 419 / 4-102 | Calibration operation; analogous to `B_atom_calibration_b1500_self_calibration` | P2 |
| 18 | `B_atom_diagnostic_hvmc_self_test` | `ERHVCTST?` | Run N1266A HVMC expander self-test | PDF 407 / 4-90 | Diagnostic operation | P2 |

### SPGU Correction / Compensation (B vs C ambiguity — see notes)

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 19 | `B_atom_correction_spgu_set_open_comp` | `SOPC` | Enable/disable SPGU open compensation | PDF 509-510 / 4-192-193 | Correction state, analogous to `B_atom_correction_cmu_set_correction`; see Note² | P1 |
| 20 | `B_atom_correction_spgu_set_short_comp` | `SOVC` | Enable/disable SPGU short compensation | PDF 510-511 / 4-193-194 | Correction state, analogous to CMU correction pattern; see Note² | P1 |

² The C atom arbitration placed SOPC/SOVC as C/rejected. However, the boundary rules state "CMU correction, phase comp, QSCV offset → B." SOPC/SOVC are structurally identical to CORRST (enable/disable correction). This audit recommends B_atom_correction for consistency. If the arbitration decision stands, move these to "Keep As C."

### N1265A Fixture Advanced Control (partially mapped)

| # | Proposed Atom | Source Cmd(s) | Meaning | Source Pages | Why B | Priority |
|---|---|---|---|---|---|---|
| 21 | `B_atom_routing_uhc_set_guard_mode` | `ERPFGA` | Set N1265A guard mode | PDF 423-424 / 4-106-107 | Guard path configuration | P3 |
| 22 | `B_atom_routing_uhc_set_data_acquisition` | `ERPFDA` | Set N1265A data acquisition settings | PDF 414-415 / 4-97-98 | Fixture configuration | P3 |
| 23 | `B_atom_routing_uhc_set_display` | `ERPFDP` | Set N1265A display | PDF 415-416 / 4-98-99 | Fixture display/indicator | P3 |

**Total missing B candidates: 23** (4 P0, 4 P1, 7 P2, 8 P3)

---

## Keep As C / Do Not Add To A-B

These commands are measurement/source/execution operations and should remain in C per `c_atom_arbitration.md`:

| Command(s) | Atom Assigned in C Arbitration | Reason Stays C |
|---|---|---|
| `SIM` (set mode) | `C_atom_spgu_set_operation_mode` | Configures SPGU for pulse execution; operation mode is a C-class source parameter |
| `SPM`, `SPPER`, `SPT`, `SPV` (pulse setup) | `C_atom_spgu_configure_pg_pulse` | Source/pulse configuration parameters |
| `SPRM` (channel output mode) | `C_atom_spgu_configure_pg_pulse` | Output mode is tied to execution behavior |
| `SPUPD` (apply settings) | `C_atom_spgu_update_output` | Applies source setup — commits configuration to hardware |
| `SRP` (start output) | `C_atom_spgu_start_output` | Source execution trigger |
| `SPP` (stop output) | `C_atom_spgu_stop_output` | Source execution stop (normal flow; see Note³) |
| `ALW`, `ALS` (ALWG setup) | Future SPGU P2 | Waveform/sequence definition is source config |
| `SER` (set load impedance) | C SPGU config | Source output parameter affecting voltage calculation |
| `STGP` (set trigger output) | C trigger config | Trigger output tied to execution timing |
| `HVSMUOP` (set HVSMU mode) | `C_atom_hvsmu_set_operation_mode` | Operation mode for high-power source config |
| `ERHVPV` (HVSMU expander force voltage) | C high-power source | Direct force voltage through expander |
| Various `ERPFGA`, `ERPFGP`, `ERPFGR`, `ERPFDS` set commands | Future C/B per detail | N1265A fixture force/measure configuration; needs page-level review |

³ `SPP` is classified as C for normal stop. If a safety/emergency abort variant is needed for SPGU, consider a separate `B_atom_safety_spgu_stop_output` with the same `SPP` command but different pre/post-condition handling. Currently the C arbitration treats it as normal stop only.

---

## Unclear / Needs Manual Verification

| Item | Command(s) | Question | Recommendation |
|---|---|---|---|
| CORRSER? classification | `CORRSER?` | This performs an active measurement (series resistance). Is it A (query) or B (correction measurement)? Analogous to `CORR?` which is B. | Likely **B_atom_correction_spgu_measure_series**. Read PDF 384 to confirm if it modifies state. |
| SOPC/SOVC classification | `SOPC`, `SOVC` | C arbitration puts them as C; boundary rules put correction in B. Structurally identical to CORRST. | Recommend **B** for consistency. Flag for arbitration override if C is intended. |
| SPP dual-use (normal vs safety) | `SPP` | Could be both C (normal stop) and B (safety abort). The current B abort (`AB`) covers general abort but not SPGU-specific stop. | Keep as C per arbitration. Add B variant only if SPGU-specific emergency stop pattern is needed. |
| ERHPE, ERHPR exact function | `ERHPE`, `ERHPE?`, `ERHPR`, `ERHPR?` | B1274A adapter commands; exact function not confirmed from current extracted data. | Read PDF 404-405 (ERHPE) and PDF 409-410 (ERHPR) for exact semantics before creating atoms. |
| ERHVP, ERHVS exact function | `ERHVP`, `ERHVP?`, `ERHVS`, `ERHVS?` | N1266A expander commands; exact function needs command page reading. | Read PDF 408-409 (ERHVP) and PDF 412 (ERHVS). Likely routing/configuration B atoms. |
| ERPFQG, ERHPQG function | `ERPFQG`, `ERPFQG?`, `ERHPQG`, `ERHPQG?` | N1265A/B1274A guard-related; exact function unclear. | Read PDF 424-425 (ERPFQG) and PDF 405-406 (ERHPQG). |
| N1265A ERPFDS, ERPFGP, ERPFGR | `ERPFDS`, `ERPFGP`, `ERPFGR` + `?` variants | N1265A fixture configuration; could be B routing or C measurement config. | Read respective command pages. |
| `*LRN?` type coverage for SPGU/selector | `*LRN? type` | Does `*LRN?` with specific type values return SPGU or selector settings? If so, existing A_atom_flex_query_settings may already partially cover some query needs. | Read PDF 446-452 to check type parameter coverage for SPGU/selector. |
| CL for SPGU | `CL` | Existing `B_atom_output_b1500_disable_channels` uses CL. Does CL also disable SPGU channels? If so, no separate B atom needed for SPGU disable. | Verify CL module scope includes SPGU. Command page (PDF 377) lists SPGU in scope. Likely covered. |

---

## Recommended First Patch Set

Priority P0 atoms to add first — these are required for any SPGU or selector workflow:

### Batch 1: Selector Core (4 atoms)

| Atom | Type | Source | Rationale |
|---|---|---|---|
| `A_atom_flex_query_selector_status` | A | `ERS?` | Must verify selector state before/after switching |
| `A_atom_flex_query_selector_mode` | A | `ERMOD?` | Must verify DIO mode is set for selector before issuing ERSSP |
| `A_atom_flex_query_smu_pg_selector` | A | `ERSSP?` | Must verify which path (SMU/PGU) is active |
| `B_atom_routing_selector_set_smu_pg` | B | `ERSSP` | Core path switching for 16440A; required for any SMU↔SPGU workflow |

### Batch 2: Selector Mode + SPGU Output (3 atoms)

| Atom | Type | Source | Rationale |
|---|---|---|---|
| `B_atom_routing_selector_set_mode` | B | `ERMOD` | Must set DIO to selector mode before any ERSSP commands |
| `B_atom_output_spgu_enable_channels` | B | `CNX` | SPGU channel enable; required before any SPGU output |
| `A_atom_flex_query_spgu_status` | A | `SPST?` | Essential status readback for SPGU execution monitoring |

### Batch 3: SPGU Pulse Switch (2 atoms)

| Atom | Type | Source | Rationale |
|---|---|---|---|
| `B_atom_output_spgu_set_pulse_switch` | B | `ODSW` | Controls semiconductor relay for SPGU pulse output path |
| `A_atom_flex_query_spgu_pulse_switch` | A | `ODSW?` | Read back pulse switch state for verification |

### Total first patch: 9 atoms (5 A + 4 B)

Implementation notes:
- All proposed atoms follow the existing fake-response pattern in `a_atoms.py` / `b_atoms.py`.
- All A atoms should be added to `A_ATOM_FUNCTIONS` list and registered in `register_a_atoms`.
- All B atoms should be added to `B_ATOM_FUNCTIONS` list and registered in `register_b_atoms`.
- SPGU-related A atoms use `flex` interface since they are GPIB/FLEX commands (not WGFMU library or EasyEXPERT remote).
- Page references use the formula `PDF page = printed 4-N + 317`. Some page numbers in this table are approximate (±1 page) because ER* command pages were not individually verified against PDF content.

---

## Summary Counts

| Category | Count |
|---|---:|
| Missing A atom candidates | 31 |
| Missing B atom candidates | 23 |
| Keep as C (confirmed) | 12+ commands |
| Unclear / needs verification | 8 items |
| Recommended first patch | 9 atoms (5A + 4B) |

### Top Additions by Impact

1. **`B_atom_routing_selector_set_smu_pg`** — Without this, no SMU↔SPGU switching workflow is possible.
2. **`B_atom_output_spgu_enable_channels`** — Without CNX as a B atom, SPGU output cannot be enabled in the A/B/C framework.
3. **`B_atom_routing_selector_set_mode`** — Required precondition for selector control.
4. **`A_atom_flex_query_spgu_status`** — Essential for monitoring SPGU execution state.
5. **`A_atom_flex_query_smu_pg_selector`** — Essential for verifying selector state in stress/measure workflows.
