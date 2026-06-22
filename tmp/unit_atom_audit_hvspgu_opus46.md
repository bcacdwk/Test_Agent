# Unit Atom Audit — B1525A HV-SPGU

Date: 2026-06-22
Auditor: opus-4.6-max
Status: gap analysis only — do not modify production code or formal docs from this file.

Inputs:
- `src/b1500_test_agent/mcp/a_atoms.py` (53 A atoms)
- `src/b1500_test_agent/mcp/b_atoms.py` (44 B atoms)
- `src/b1500_test_agent/mcp/c_atoms.py` (65 C atoms)
- `.agents/skills/.../references/mcp-tools/{a,b,c}-atoms.md`
- `references/manuals/structured/b1500a-command-summary.yaml`
- `references/manuals/structured/b1500a-initial-settings.md`
- `references/manuals/b1500a-programming-guide-index.md`
- `tmp/c_atom_arbitration.md`
- `tmp/spgu_selector_ab_gap_opus46.md`, `tmp/spgu_selector_ab_gap_gpt55.md`

User actual-system constraints:
- Two high-speed pulse voltage source channels (B1525A).
- Measured max external voltage ±40 V.
- Pulse/NVM/FeFET-style write/read workflows.
- 16440A SMU-Pulse Generator Selector present for SMU↔SPGU switching.

---

## Current Coverage Summary

### A atoms covering SPGU/selector (5 atoms)

| Atom | Basis | Status |
|---|---|---|
| `A_atom_flex_query_spgu_status` | `SPST?` | Implemented |
| `A_atom_flex_query_spgu_setup` | `SIM?`, `SPRM?`, `SPM?`, `SPPER?`, `SPT?`, `SPV?` | Implemented |
| `A_atom_flex_query_spgu_pulse_switch` | `ODSW?` | Implemented |
| `A_atom_flex_query_selector_status` | `ERS?` | Implemented |
| `A_atom_flex_query_selector_mode` | `ERMOD?`, `ERSSP?` | Implemented |

### B atoms covering SPGU/selector (6 atoms)

| Atom | Basis | Status |
|---|---|---|
| `B_atom_output_spgu_enable_channels` | `CNX` | Implemented |
| `B_atom_routing_spgu_set_pulse_switch` | `ODSW` | Implemented |
| `B_atom_routing_selector_set_mode` | `ERMOD` | Implemented |
| `B_atom_routing_selector_set_smu_pg_path` | `ERSSP` | Implemented |
| `B_atom_routing_dio_set_mode` | `ERM` | Implemented |
| `B_atom_output_dio_set_relay_bits` | `ERC` | Implemented |

### C atoms covering SPGU (8 atoms)

| Atom | Basis | Status |
|---|---|---|
| `C_atom_spgu_set_operation_mode` | `SIM` | Implemented |
| `C_atom_spgu_configure_pg_pulse` | `SPM`, `SPPER`, `SPT`, `SPV`, `SPRM` | Implemented — schema gaps (see below) |
| `C_atom_spgu_update_output` | `SPUPD` | Implemented |
| `C_atom_spgu_start_output` | `SRP` | Implemented |
| `C_atom_spgu_stop_output` | `SPP` | Implemented |
| `C_atom_spgu_create_alwg_pattern` | `ALW` | Implemented |
| `C_atom_spgu_add_alwg_sequence` | `ALS` | Implemented |
| `C_atom_spgu_set_trigger_output` | `STGP` | Implemented — schema gaps (see below) |

### SPGU command coverage matrix

Source: command summary YAML groups SPGU Control (15 cmds), SPGU Pulse Setup (8 cmds), SPGU ALWG (4 cmds), Output Comparison (4 cmds). Total: 31 command entries.

| Command | Query | Set/exec | A atom | B atom | C atom | Gap? |
|---|---|---|---|---|---|---|
| `SPST?` | ✓ | — | ✓ query_spgu_status | — | — | — |
| `SIM` / `SIM?` | ✓ | ✓ | ✓ (in query_spgu_setup) | — | ✓ set_operation_mode | — |
| `SPRM` / `SPRM?` | ✓ | ✓ | ✓ (in query_spgu_setup) | — | ✓ (in configure_pg_pulse) | — |
| `SPM` / `SPM?` | ✓ | ✓ | ✓ (in query_spgu_setup) | — | ✓ (in configure_pg_pulse) | — |
| `SPPER` / `SPPER?` | ✓ | ✓ | ✓ (in query_spgu_setup) | — | ✓ (in configure_pg_pulse) | — |
| `SPT` / `SPT?` | ✓ | ✓ | ✓ (in query_spgu_setup) | — | ✓ (in configure_pg_pulse) | **Schema** |
| `SPV` / `SPV?` | ✓ | ✓ | ✓ (in query_spgu_setup) | — | ✓ (in configure_pg_pulse) | **Schema** |
| `SPUPD` | — | ✓ | — | — | ✓ update_output | — |
| `SRP` | — | ✓ | — | — | ✓ start_output | — |
| `SPP` | — | ✓ | — | — | ✓ stop_output | — |
| `ODSW` / `ODSW?` | ✓ | ✓ | ✓ query_spgu_pulse_switch | ✓ routing_spgu_set_pulse_switch | — | — |
| `SER` / `SER?` | ✓ | ✓ | **MISSING** | **MISSING** | **MISSING** | **Missing** |
| `CORRSER?` | ✓ | (measures) | **MISSING** | **MISSING** | — | **Missing** |
| `SOPC` / `SOPC?` | ✓ | ✓ | **MISSING** | **MISSING** | — | **Missing** |
| `SOVC` / `SOVC?` | ✓ | ✓ | **MISSING** | **MISSING** | — | **Missing** |
| `STGP` / `STGP?` | ✓ | ✓ | **MISSING** | — | ✓ set_trigger_output | **Schema + A missing** |
| `ALW` / `ALW?` | ✓ | ✓ | **MISSING** | — | ✓ create_alwg_pattern | **A missing** |
| `ALS` / `ALS?` | ✓ | ✓ | **MISSING** | — | ✓ add_alwg_sequence | **A missing** |
| `CNX` | — | ✓ | — | ✓ output_spgu_enable_channels | — | — |
| `ERMOD` / `ERMOD?` | ✓ | ✓ | ✓ query_selector_mode | ✓ routing_selector_set_mode | — | — |
| `ERSSP` / `ERSSP?` | ✓ | ✓ | ✓ (in query_selector_mode) | ✓ routing_selector_set_smu_pg_path | — | — |
| `ERS?` | ✓ | — | ✓ query_selector_status | — | — | — |
| `ERM` | — | ✓ | — | ✓ routing_dio_set_mode | — | — |
| `ERC` | — | ✓ | — | ✓ output_dio_set_relay_bits | — | — |
| `MSP` | — | ✓ | — | — | **MISSING** | **Missing C** |

---

## Confident Missing A_atoms

| # | Proposed Atom | Basis | Meaning | Priority | Notes |
|---|---|---|---|---|---|
| A1 | `A_atom_flex_query_spgu_load_impedance` | `SER?` | Read SPGU DUT load impedance setting (initial: 50 Ω). Affects output voltage capability and SOPC/SOVC compensation calculations. | P1 | Essential for verifying load config before pulse; query-only. |
| A2 | `A_atom_flex_query_spgu_trigger_output` | `STGP?` | Read SPGU trigger-output configuration (port, enable, mode). | P1 | Query-only; the setter `STGP` is already a C atom but has no readback. |
| A3 | `A_atom_flex_query_spgu_open_comp` | `SOPC?` | Read SPGU open compensation enable/disable state. | P2 | Query-only readback of correction state. |
| A4 | `A_atom_flex_query_spgu_short_comp` | `SOVC?` | Read SPGU short (voltage) compensation enable/disable state. | P2 | Query-only readback of correction state. |
| A5 | `A_atom_flex_query_spgu_alwg_pattern` | `ALW?` | Read ALWG waveform pattern definition for verification/debug. | P2 | Query-only; setter `ALW` is C. |
| A6 | `A_atom_flex_query_spgu_alwg_sequence` | `ALS?` | Read ALWG channel/sequence assignment for verification/debug. | P2 | Query-only; setter `ALS` is C. |

**Count: 6 missing A atoms** (2 P1, 4 P2)

---

## Confident Missing B_atoms

| # | Proposed Atom | Basis | Meaning | Category | Priority | Notes |
|---|---|---|---|---|---|---|
| B1 | `B_atom_correction_spgu_set_open_comp` | `SOPC` | Enable/disable SPGU open compensation. | correction | P1 | Structurally identical to `B_atom_correction_cmu_set_correction` / `CORRST`. The C arbitration boundary rules place correction in B. |
| B2 | `B_atom_correction_spgu_set_short_comp` | `SOVC` | Enable/disable SPGU short (voltage) compensation. | correction | P1 | Same structural pattern as SOPC. |
| B3 | `B_atom_correction_spgu_measure_series` | `CORRSER?` | Perform SPGU load impedance / series resistance correction measurement. Returns measured series resistance. | correction | P1 | Performs active measurement like `CORR?` → B. Appears in SPGU example workflow (PDF 284-290). |

**Count: 3 missing B atoms** (3 P1)

---

## Confident Missing C_atoms

| # | Proposed Atom | Basis | Meaning | Priority | Notes |
|---|---|---|---|---|---|
| C1 | `C_atom_spgu_set_load_impedance` | `SER` | Set SPGU DUT load impedance (50 Ω or 1 MΩ; affects output voltage limits and compensation). | P1 | Appears in SPGU example workflow. Boundary: could be B policy, but `SER` directly affects source output calculation (like `IMP` for CMU → C). Recommend C with B readback query. |
| C2 | `C_atom_spgu_configure_sampling_pulse` | `MSP` | Configure SPGU pulse output for use within SMU sampling measurement (MM10). | P2 | Used when SPGU provides pulse bias during sampling; no C atom exists. Initial setting: cleared. |
| C3 | `C_atom_spgu_configure_open_comp` | `SOPC` | Enable/disable open compensation with data values. | **ARBITRATE** | Alternative to B1 above if placed in C. Recommend B per correction boundary rule. |
| C4 | `C_atom_spgu_configure_short_comp` | `SOVC` | Enable/disable short compensation with data values. | **ARBITRATE** | Alternative to B2 above if placed in C. Recommend B per correction boundary rule. |

**Confident missing (excluding arbitration items): 2** (C1 P1, C2 P2)
Items C3/C4 are alternatives to B1/B2 — only one classification should be used.

---

## Parameter / Schema Gaps In Existing Atoms

### C_atom_spgu_configure_pg_pulse — 5 gaps

| # | Gap | Detail | Impact |
|---|---|---|---|
| S1 | Missing `leading_s` / `trailing_s` parameters | `SPT` command has 4 timing params: delay, width, leading edge, trailing edge. Current atom only exposes `period_s`, `width_s`. Initial: leading 20 ns, trailing 20 ns. | Cannot configure SPGU rise/fall time. Critical for NVM/FeFET pulse shaping. |
| S2 | Missing `delay_s` parameter | `SPT` per-source delay parameter. Current atom omits it entirely (initial: 0 s). | Cannot stagger pulse timing between channels. |
| S3 | Missing `source_number` parameter | `SPM`, `SPT`, `SPV` accept a source number (1 or 2 for 2-level; 1, 2, or 3 for 3-level). Current atom has no source selector. | Cannot configure 3-level pulse mode with different voltage/timing per source. |
| S4 | Missing 3-level pulse voltage support | Only `base_v` + `peak_v` exposed. 3-level mode needs `base_v`, `peak1_v`, `peak2_v` (via SPV with source_number 1, 2, 3). | 3-level pulses are undercovered — needed for FeFET write waveforms. |
| S5 | Missing explicit `channel_mode` → SPM mode parameter | SPM sets output mode: 2-level, 3-level, or ALWG. Atom has `pulse_mode: str = "two_level"` but no validation or enum. | Agent may pass invalid mode string without schema enforcement. |

### C_atom_spgu_set_trigger_output — 2 gaps

| # | Gap | Detail | Impact |
|---|---|---|---|
| S6 | Missing trigger port/mode parameters | `STGP` has port ID, trigger type, polarity/edge parameters. Atom only has `enabled: bool`. | Cannot configure which trigger port or edge type. |
| S7 | Missing per-channel trigger binding | `STGP` can bind trigger output to specific channel execution events. Not represented. | Cannot use trigger-per-channel workflows (e.g., SPGU ch1 → trigger out → SMU measure). |

### C_atom_spgu_start_output — 1 gap

| # | Gap | Detail | Impact |
|---|---|---|---|
| S8 | Missing pulse count parameter | `SRP` can accept a count for limited-run pulse output (vs free-run). Atom doesn't expose count. | Cannot run N-pulse sequences without free-run/manual-stop. |

### C_atom_spgu_create_alwg_pattern — 2 gaps

| # | Gap | Detail | Impact |
|---|---|---|---|
| S9 | Missing pattern data array parameter | `ALW` accepts pattern data (voltage level array per time slot). Atom only has `initial_voltage_v` and `period_s`. | Cannot define actual ALWG waveform data. |
| S10 | Missing channel binding | `ALW` binds pattern to a channel. Atom has no channel parameter. | Cannot specify which channel gets the ALWG pattern. |

### C_atom_spgu_add_alwg_sequence — 1 gap

| # | Gap | Detail | Impact |
|---|---|---|---|
| S11 | Missing loop/count control detail | `ALS` has sequence step, loop start, loop count fields. Atom has minimal `repeat_count`. | Cannot build complex multi-loop ALWG sequences. |

### C_atom_spgu_stop_output — 1 gap

| # | Gap | Detail | Impact |
|---|---|---|---|
| S12 | No distinction between normal stop and safety stop | `SPP` is a normal run stop (C). Emergency abort is `AB` (B). But there's no SPGU-specific safety-stop atom that includes post-stop readback/cleanup. | In a real NVM/FeFET workflow, agent may confuse `SPP` (C: normal stop) with emergency abort (B: `AB` + `DZ` + readback). The C atom caution note is present but schema doesn't enforce the distinction. |

### A_atom_flex_query_spgu_setup — 1 gap

| # | Gap | Detail | Impact |
|---|---|---|---|
| S13 | Missing `SER?` in composite readback | The composite setup readback covers `SIM?`, `SPRM?`, `SPM?`, `SPPER?`, `SPT?`, `SPV?` but omits `SER?` (load impedance). | Setup verification misses a key parameter that affects output voltage capability. |

### _SPGU_PRE precondition list — 2 gaps

| # | Gap | Detail | Impact |
|---|---|---|---|
| S14 | Missing `B_atom_routing_selector_set_mode` in `_SPGU_PRE` | Current `_SPGU_PRE` = `[A_atom_flex_connect, A_atom_flex_query_selector_mode, B_atom_output_spgu_enable_channels]`. For 16440A setups, ERMOD must be set before ERSSP. | Agent may skip selector mode configuration, causing error 603 "module selector DIO mode not set." |
| S15 | Missing `B_atom_routing_selector_set_smu_pg_path` in `_SPGU_PRE` | The 16440A path switch (`ERSSP`) is not listed as a precondition. | Agent may attempt SPGU output while selector is still routing to SMU. |

**Total schema gaps: 15**

---

## 16440A Selector / Routing Preconditions

The 16440A SMU-Pulse Generator Selector is present in the user's system. The following A/B atoms are implemented and form the routing prerequisite chain for any SPGU workflow:

### Implemented selector atoms (correct)

| Atom | Role in SPGU workflow |
|---|---|
| `B_atom_routing_selector_set_mode` (`ERMOD`) | Set DIO mode to normal/selector mode. Must be called before ERSSP. |
| `B_atom_routing_selector_set_smu_pg_path` (`ERSSP`) | Switch 16440A path: SMU-on → PGU-on for SPGU access. |
| `A_atom_flex_query_selector_mode` (`ERMOD?`, `ERSSP?`) | Verify current path before/after switching. |
| `A_atom_flex_query_selector_status` (`ERS?`) | Check selector connection/detection. |

### Required workflow sequence for SPGU via 16440A

```
1. A_atom_flex_connect
2. A_atom_flex_list_modules              -- discover B1525A in slot
3. A_atom_flex_query_selector_status     -- verify 16440A detected
4. B_atom_routing_selector_set_mode      -- ERMOD 0 (normal DIO)
5. A_atom_flex_query_selector_mode       -- verify ERMOD?
6. B_atom_output_b1500_zero_outputs      -- DZ on relevant channels (safety)
7. B_atom_routing_selector_set_smu_pg_path -- ERSSP ch, PGU-on
8. A_atom_flex_query_selector_mode       -- verify ERSSP? shows PGU-on
9. B_atom_output_spgu_enable_channels    -- CNX ch
10. B_atom_routing_spgu_set_pulse_switch  -- ODSW enable
11. [C_atom_spgu_* setup/execute]
12. C_atom_spgu_stop_output              -- SPP
13. B_atom_routing_spgu_set_pulse_switch  -- ODSW disable
14. B_atom_output_b1500_disable_channels -- CL or zero
15. B_atom_routing_selector_set_smu_pg_path -- ERSSP ch, SMU-on (restore)
```

### Gap: `_SPGU_PRE` does not encode this sequence

The `_SPGU_PRE` constant in `c_atoms.py` is:
```python
_SPGU_PRE = [
    "A_atom_flex_connect",
    "A_atom_flex_query_selector_mode",
    "B_atom_output_spgu_enable_channels",
]
```

Missing from `_SPGU_PRE`:
- `B_atom_routing_selector_set_mode` (ERMOD)
- `B_atom_routing_selector_set_smu_pg_path` (ERSSP)
- `B_atom_routing_spgu_set_pulse_switch` (ODSW)
- `B_atom_safety_b1500_preflight` (general readiness)

Recommendation: expand `_SPGU_PRE` or add a separate `_SPGU_SELECTOR_PRE` for 16440A-equipped systems.

---

## Actual-System Limits To Encode

| # | Limit | Source | Current coverage | Recommendation |
|---|---|---|---|---|
| L1 | Max external voltage ±40 V | User actual measurement | No voltage validation in any SPGU C atom schema. `C_atom_spgu_configure_pg_pulse` accepts arbitrary `base_v` / `peak_v`. | Add `max_voltage_v: float = 40.0` to SPGU C atom schemas or a preflight limit check. |
| L2 | Two pulse channels only | B1525A spec: 2 high-speed pulse voltage source channels | No channel count validation. `channel: int` parameter accepts any integer. | Add channel range validation (typically ch = slot-based, e.g., 1-2 for a single B1525A). |
| L3 | Load impedance affects voltage range | B1525A spec: 50 Ω vs 1 MΩ load changes output capability. With 50 Ω, max output is lower due to voltage divider. | `SER` / `SER?` not implemented. No load-aware voltage limit. | Implement C1 (`C_atom_spgu_set_load_impedance`) and tie load to voltage limit validation. |
| L4 | Pulse timing constraints | B1525A: min width ≈ 50 ns (HV-SPGU), min period depends on mode. Leading/trailing edge min = 8 ns (SPGU) or 20 ns (initial). | No timing validation in `C_atom_spgu_configure_pg_pulse`. | Add timing limit fields or a validation layer. |
| L5 | Interlock applicability for HVSPGU | B1525A is listed as HV-capable. If voltage exceeds interlock threshold, interlock must be closed. | `_SPGU_PRE` does not include `B_atom_safety_b1500_check_interlock`. | Add interlock check to SPGU preconditions when configured voltage > interlock threshold. |
| L6 | ODSW pulse switch timing constraints | Initial: delay 0 s, width 100 ns. The pulse switch has its own timing envelope separate from the SPGU pulse timing. | `B_atom_routing_spgu_set_pulse_switch` has `enabled` + `contact` but no timing parameters (delay, width). | Add `delay_s` and `width_s` parameters to `B_atom_routing_spgu_set_pulse_switch`. |

---

## Keep As Existing / No New Atom Needed

| Item | Current classification | Why no change needed |
|---|---|---|
| `SPST?` readback | A (`A_atom_flex_query_spgu_status`) | Correctly A: pure status query. |
| `SIM?/SPRM?/SPM?/SPPER?/SPT?/SPV?` composite readback | A (`A_atom_flex_query_spgu_setup`) | Correctly A: query-only. Schema gap S13 flagged but classification is correct. |
| `ODSW?` readback | A (`A_atom_flex_query_spgu_pulse_switch`) | Correctly A: query-only. |
| `ERS?`, `ERMOD?`, `ERSSP?` readback | A (query_selector_status, query_selector_mode) | Correctly A. |
| `CNX` channel enable | B (`B_atom_output_spgu_enable_channels`) | Correctly B: output switch state change. |
| `ODSW` set | B (`B_atom_routing_spgu_set_pulse_switch`) | Correctly B: relay/switch state. Schema gap L6 flagged. |
| `ERMOD` set mode | B (`B_atom_routing_selector_set_mode`) | Correctly B: DIO control mode. |
| `ERSSP` set path | B (`B_atom_routing_selector_set_smu_pg_path`) | Correctly B: physical relay. |
| `ERM` / `ERC` DIO | B (routing_dio_set_mode, output_dio_set_relay_bits) | Correctly B: hardware I/O control. |
| `SIM` set mode | C (`C_atom_spgu_set_operation_mode`) | Correctly C: source operation config. |
| `SPM/SPPER/SPT/SPV/SPRM` config | C (`C_atom_spgu_configure_pg_pulse`) | Correctly C: source pulse config. Schema gaps exist. |
| `SPUPD` | C (`C_atom_spgu_update_output`) | Correctly C: applies source config. |
| `SRP` | C (`C_atom_spgu_start_output`) | Correctly C: source execution start. |
| `SPP` normal stop | C (`C_atom_spgu_stop_output`) | Correctly C: normal run stop. Safety stop remains B (`AB`). |
| `ALW` / `ALS` | C (create_alwg_pattern, add_alwg_sequence) | Correctly C: waveform/sequence definition. |
| `STGP` | C (`C_atom_spgu_set_trigger_output`) | Correctly C: trigger tied to execution. Schema gaps exist. |
| Generic `B_atom_output_b1500_disable_channels` (`CL`) | B | CL scope includes SPGU per command page. No dedicated SPGU-disable B atom needed — existing CL atom suffices. |
| Generic `B_atom_output_b1500_zero_outputs` (`DZ`) | B | DZ applies to SPGU channels. Usable for SPGU cleanup. |
| Generic `B_atom_safety_b1500_abort` (`AB`) | B | AB covers SPGU emergency stop. No SPGU-specific B abort needed. |

---

## Uncertain Items Requiring Parent/User Arbitration

| # | Item | Question | Options | Recommendation |
|---|---|---|---|---|
| U1 | `SER` classification: B policy vs C source config | SER sets DUT load impedance which directly affects SPGU voltage output behavior and correction calculations. CMU analogue: `IMP` (impedance model) is C. Correction analogue: `CORRST` enable/disable is B. | **Option A:** C — source config like IMP. **Option B:** B — policy/safety because it changes output voltage limits. | **C** — it's a source parameter that shapes pulse output behavior, like IMP for CMU. Add A readback `SER?`. |
| U2 | `SOPC` / `SOVC` classification: B correction vs C config | C arbitration boundary rules: "CMU correction → B." These are structurally identical to CORRST. But the C arbitration initially placed Output Comparison as C/rejected. | **Option A:** B correction — consistent with CORRST/CORR?. **Option B:** C — source calibration config. | **B** — correction/compensation state control is B by existing convention. |
| U3 | `SPP` dual-use: C normal stop vs B safety | Current: C only. Emergency stop uses generic `AB`. Question: should there be a dedicated `B_atom_safety_spgu_emergency_stop` that wraps SPP + DZ + ODSW disable + error readback? | **Option A:** Keep single C atom, rely on generic B atoms for safety. **Option B:** Add dedicated B safety-stop with post-cleanup. | **A** — generic B atoms (`AB`, `DZ`, `CL`) cover emergency stop. Document the sequence in C atom caution text. |
| U4 | `CORRSER?` classification: B correction measurement vs A query | CORRSER? performs an active measurement (measures series resistance) and returns data. Query form but action-oriented like `CORR?` (CMU). | **Option A:** B correction — analogous to `B_atom_correction_cmu_measure_data`. **Option B:** A query with measurement side-effect. | **B** — performs correction measurement, analogous to `CORR?`. |
| U5 | `STGP` partial B-classification | STGP configures trigger output which can affect external hardware timing. It is currently C. Should part of STGP config be B (routing/output state)? | **Option A:** Keep all C. **Option B:** Split into B (port/enable) and C (trigger-to-execution binding). | **A** — keep as C. STGP is tied to pulse execution, not standalone output state like ODSW. |
| U6 | `_SPGU_PRE` expansion | Should `_SPGU_PRE` include 16440A selector B atoms? Or should there be separate `_SPGU_SELECTOR_PRE`? | **Option A:** Expand `_SPGU_PRE` directly. **Option B:** Add `_SPGU_SELECTOR_PRE` overlay for 16440A. | **B** — separate `_SPGU_SELECTOR_PRE` because not all systems have 16440A. Keep `_SPGU_PRE` as the base precondition list. |
| U7 | Composite A readback: split or keep composite | `A_atom_flex_query_spgu_setup` bundles 6 query commands. Is this too coarse? Individual atoms would be more granular but create 6 extra atoms. | **Option A:** Keep composite. **Option B:** Split into individual query atoms. | **A** — keep composite for now. It matches the NVM workflow pattern of "verify everything before pulse." Add `SER?` to it (S13). |

---

## Recommended Patch Set

### Priority 1 — Missing atoms (unblocks real SPGU calibration/correction workflows)

| # | Action | Atom | Basis | Classification |
|---|---|---|---|---|
| P1 | **Add** | `A_atom_flex_query_spgu_load_impedance` | `SER?` | A |
| P2 | **Add** | `A_atom_flex_query_spgu_trigger_output` | `STGP?` | A |
| P3 | **Add** | `B_atom_correction_spgu_set_open_comp` | `SOPC` | B correction |
| P4 | **Add** | `B_atom_correction_spgu_set_short_comp` | `SOVC` | B correction |
| P5 | **Add** | `B_atom_correction_spgu_measure_series` | `CORRSER?` | B correction |
| P6 | **Add** | `C_atom_spgu_set_load_impedance` | `SER` | C |

### Priority 2 — Schema fixes in existing atoms (critical for pulse shaping)

| # | Action | Atom | Fix |
|---|---|---|---|
| P7 | **Fix schema** | `C_atom_spgu_configure_pg_pulse` | Add parameters: `delay_s`, `leading_s`, `trailing_s`, `source_number`. Refactor `base_v`/`peak_v` to support 3-level mode (source 1/2/3 voltages). |
| P8 | **Fix schema** | `C_atom_spgu_set_trigger_output` | Add parameters: `port`, `trigger_type`, `polarity`. Replace bare `enabled: bool`. |
| P9 | **Fix schema** | `C_atom_spgu_start_output` | Add parameter: `count` for limited-run pulse output. |
| P10 | **Fix schema** | `B_atom_routing_spgu_set_pulse_switch` | Add parameters: `delay_s`, `width_s` for ODSW timing. |
| P11 | **Fix schema** | `A_atom_flex_query_spgu_setup` | Add `SER?` to the composite readback basis list. |

### Priority 3 — Precondition and limit encoding

| # | Action | Target | Fix |
|---|---|---|---|
| P12 | **Add precondition list** | `_SPGU_SELECTOR_PRE` (new) | `[B_atom_routing_selector_set_mode, B_atom_routing_selector_set_smu_pg_path]` |
| P13 | **Expand** | `_SPGU_PRE` | Add `B_atom_safety_b1500_preflight` and `B_atom_routing_spgu_set_pulse_switch`. |
| P14 | **Add validation note** | SPGU C atoms | Encode ±40 V user limit as a configurable `max_voltage_v` parameter or caution field. |
| P15 | **Add conditional** | SPGU C atoms | Add interlock check (`B_atom_safety_b1500_check_interlock`) when voltage > interlock threshold. |

### Priority 4 — Deferred additions

| # | Action | Atom | Basis | Notes |
|---|---|---|---|---|
| P16 | **Add** | `A_atom_flex_query_spgu_open_comp` | `SOPC?` | Readback for P3. |
| P17 | **Add** | `A_atom_flex_query_spgu_short_comp` | `SOVC?` | Readback for P4. |
| P18 | **Add** | `A_atom_flex_query_spgu_alwg_pattern` | `ALW?` | Debug/verification for ALWG workflows. |
| P19 | **Add** | `A_atom_flex_query_spgu_alwg_sequence` | `ALS?` | Debug/verification for ALWG workflows. |
| P20 | **Add** | `C_atom_spgu_configure_sampling_pulse` | `MSP` | SPGU-in-sampling workflow. |
| P21 | **Fix schema** | `C_atom_spgu_create_alwg_pattern` | Add pattern data array, channel binding (S9, S10). |
| P22 | **Fix schema** | `C_atom_spgu_add_alwg_sequence` | Add loop/step control detail (S11). |

---

## Summary Counts

| Category | Count |
|---|---:|
| Current SPGU/selector A atoms | 5 |
| Current SPGU/selector B atoms | 6 |
| Current SPGU C atoms | 8 |
| **Confident missing A atoms** | **6** |
| **Confident missing B atoms** | **3** |
| **Confident missing C atoms** | **2** |
| **Schema gaps in existing atoms** | **15** |
| Uncertain items for arbitration | 7 |
| Total recommended patches | 22 |
| P1 (missing atoms) | 6 |
| P2 (schema fixes) | 5 |
| P3 (preconditions/limits) | 4 |
| P4 (deferred) | 7 |

### Top 5 Recommended Additions by Impact

1. **`C_atom_spgu_configure_pg_pulse` schema fix (P7)** — Without `leading_s`/`trailing_s`/`source_number`, SPGU pulse shaping for NVM/FeFET is crippled. This is the single highest-impact fix.
2. **`C_atom_spgu_set_load_impedance` (P6)** — SER is used in every SPGU programming example and affects output voltage calculation.
3. **`B_atom_correction_spgu_set_open_comp` + `set_short_comp` (P3, P4)** — SOPC/SOVC appear in the reference SPGU workflow. Without them, output compensation cannot be configured.
4. **`_SPGU_PRE` / `_SPGU_SELECTOR_PRE` expansion (P12, P13)** — Current precondition chain is incomplete for 16440A-equipped systems.
5. **`C_atom_spgu_set_trigger_output` schema fix (P8)** — Trigger port/mode is essential for synchronized SPGU+SMU NVM read workflows.
