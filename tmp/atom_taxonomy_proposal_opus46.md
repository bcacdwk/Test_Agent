# Atom Taxonomy Proposal — Opus 4.6

Date: 2026-06-22

## Diagnosis Of Current Taxonomy

### Current Pattern

`{A|B}_atom_{subsystem}_{action}` where `subsystem` ∈ {`b1500`, `wgfmu`, `easyexpert`}.

### What The Subsystem Field Actually Encodes

The label "subsystem" implies a hardware decomposition: B1500A mainframe, WGFMU module, EasyEXPERT software. But the actual grouping logic follows **communication interface / API boundary**, not hardware hierarchy:

| Subsystem tag | Real meaning | Session/transport | Protocol |
|---|---|---|---|
| `b1500` | Direct GPIB/VISA session to the B1500A mainframe | PyVISA GPIB session | FLEX command language + IEEE 488.2 common commands |
| `wgfmu` | WGFMU instrument library (DLL/shared-lib calls) | `WGFMU_openSession` session object | C-style function API (`WGFMU_*`) |
| `easyexpert` | EasyEXPERT remote control interface | TCP/socket to EasyEXPERT host | SCPI-like remote command set |

Each subsystem has its own session lifecycle, error queue, status model, and failure modes. This is the real reason they are separate — not because they are "three subsystems of B1500A" but because they are **three distinct APIs with independent transports**.

### Core Problem: The Label Misleads

The label `subsystem` suggests a hardware decomposition where B1500A, WGFMU, and EasyEXPERT are architectural peers. They are not:

1. **B1500A** is the mainframe instrument. All commands for SMU, SPGU, CMU, ASU, SCUU, QSCV, and mainframe-level operations go through its GPIB interface.
2. **WGFMU** is a plug-in module *inside* the B1500A. But it has its own instrument library API (bypassing the FLEX command layer), so it requires separate session management.
3. **EasyEXPERT** is a PC software application that controls B1500A remotely. It is a software orchestration layer, not a hardware component.

The current taxonomy mechanically mirrors the three PDF manuals the atoms were extracted from. This is a documentation-artifact taxonomy, not a scientific one.

### Why It Still Mostly Works

Despite the misleading label, the current grouping is *functionally correct* for practical MCP tool use:

- Tools grouped under `b1500` share a common GPIB session precondition.
- Tools grouped under `wgfmu` share a common WGFMU library session precondition.
- Tools grouped under `easyexpert` share a common remote-control session precondition.
- Users scanning the MCP tool list see tools grouped by which session they need open.

### Actual Deficiencies

1. **Semantic asymmetry**: `b1500` and `easyexpert` name the *target* (instrument, software), but `wgfmu` names a *module type*. There is no consistent naming principle.
2. **Scalability concern for B atoms**: The `b1500` bucket already contains 29 B atoms covering mainframe-level safety, SMU config, ASU paths, SCUU paths, CMU correction, and QSCV cancel. As SPGU and additional module atoms are added, this bucket grows large and heterogeneous.
3. **WGFMU parity illusion**: Placing `wgfmu` beside `b1500` makes them look like architectural peers. A newcomer might think WGFMU is a separate instrument.
4. **Future module ambiguity**: If a future module (e.g. SPGU) gets its own library API, does it get a new subsystem? If so, the number of "subsystems" grows unboundedly. If not, where do its atoms go?

---

## Candidate Taxonomies Compared

### Candidate 1: Current `subsystem` Taxonomy (Status Quo)

**Pattern**: `{A|B}_atom_{subsystem}_{action}` — `b1500`, `wgfmu`, `easyexpert`

**Examples**:
- `A_atom_b1500_connect`, `A_atom_wgfmu_open_session`, `A_atom_easyexpert_identify`
- `B_atom_b1500_set_smu_filter`, `B_atom_wgfmu_abort`, `B_atom_easyexpert_set_standby`

| Criterion | Assessment |
|---|---|
| Pros | Already implemented. Groups by session precondition. Familiar. Sorts naturally in MCP lists. Scales to future external interfaces (prober, HSPICE). |
| Cons | "Subsystem" label is misleading. WGFMU appears as peer to B1500A. `b1500` bucket conflates mainframe + SMU + ASU + SCUU + CMU + QSCV. No semantic grouping within interface. |
| Safety clarity (B) | Moderate. B class prefix is clear. Module info is in action name (`set_smu_filter`, `set_asu_path`) but requires reading the full action to know what hardware is affected. |
| Future scalability | Good for new interfaces (prober, HSPICE). Moderate for new modules — they all pile into `b1500` unless they have their own API. |
| Scan-friendliness | Good. Three groups, alphabetically sorted within each. But `b1500` group will be large. |

---

### Candidate 2: Two-Level Interface — `hardware` / `software`

**Pattern**: `{A|B}_atom_{hardware|software}_{action}`

**Examples**:
- `A_atom_hardware_connect`, `A_atom_hardware_wgfmu_open_session`, `A_atom_software_identify`
- `B_atom_hardware_reset`, `B_atom_hardware_wgfmu_initialize`, `B_atom_software_abort_measurement`

| Criterion | Assessment |
|---|---|
| Pros | Philosophically clean. Emphasizes the hardware/software boundary. |
| Cons | **Far too coarse.** `hardware` would contain both B1500A direct and WGFMU library atoms with different session preconditions. Scanning a list of 60+ A atoms under two categories provides almost no navigation value. WGFMU would need a sub-qualifier anyway (e.g. `hardware_wgfmu_*`), making it a 4-level name. Prober is hardware but external — same bucket as B1500A mainframe commands? |
| Safety clarity (B) | Poor. "Hardware" doesn't distinguish mainframe-level safety from module-specific config. |
| Future scalability | Poor. Every new module or external device goes into the same `hardware` bucket. |
| Scan-friendliness | Very poor. Two megabuckets with no internal structure. |

**Verdict**: Reject. Too coarse to be useful.

---

### Candidate 3: Hardware-Layer Taxonomy

**Pattern**: `{A|B}_atom_{layer}_{action}` where `layer` ∈ {`instrument`, `module`, `accessory`, `buffer`, `remote`, ...}

**Examples**:
- `A_atom_instrument_connect`, `A_atom_instrument_identify`, `A_atom_instrument_read_error_queue`
- `A_atom_module_wgfmu_open_session`, `A_atom_module_wgfmu_get_status`
- `A_atom_remote_identify`, `A_atom_remote_list_workspaces`
- `B_atom_instrument_reset`, `B_atom_instrument_abort`
- `B_atom_accessory_set_asu_path`, `B_atom_accessory_set_scuu_path`
- `B_atom_module_wgfmu_initialize`, `B_atom_module_cmu_set_correction`

| Criterion | Assessment |
|---|---|
| Pros | Respects hardware hierarchy. ASU/SCUU/CMU get their own "accessory" or "module" category. WGFMU is correctly a module, not a peer. |
| Cons | **Breaks session grouping.** `instrument` atoms and `accessory` atoms both go through the same GPIB session but are now separated. `module` is ambiguous (WGFMU has its own API, CMU does not). `buffer` is an operation type, not a hardware layer. Names get long: `B_atom_accessory_set_asu_path`. Where do SMU atoms go — `module` or `instrument`? SMU commands are sent to the mainframe but target a specific module slot. |
| Safety clarity (B) | Moderate. "Accessory" hints at path-switching risk. But "instrument_reset" doesn't distinguish from "instrument_enable_channels". |
| Future scalability | Moderate. New modules go under `module`. But distinguishing module-with-own-API (WGFMU) from module-without (SMU, CMU) requires extra convention. |
| Scan-friendliness | Poor. Too many short layer names that don't convey the key session-precondition information. |

**Verdict**: Reject. The hardware hierarchy doesn't map cleanly to API boundaries, and the naming gets awkward.

---

### Candidate 4: Operation-Semantics Taxonomy

**Pattern A**: `A_atom_{semantic}_{action}` where `semantic` ∈ {`session`, `identity`, `status`, `error`, `buffer`, `format`, `timing`, `sync`, `catalog`, `context`, `log`, `progress`, `config`}

**Pattern B**: `B_atom_{semantic}_{action}` where `semantic` ∈ {`safety`, `reset`, `calibration`, `channel`, `path`, `correction`, `policy`}

**Examples**:
- `A_atom_session_connect_b1500`, `A_atom_session_open_wgfmu`, `A_atom_session_open_easyexpert`
- `A_atom_error_read_queue`, `A_atom_error_lookup`, `A_atom_error_read_wgfmu`
- `A_atom_catalog_list_workspaces`, `A_atom_catalog_list_app_tests`
- `B_atom_safety_abort`, `B_atom_safety_zero_all_outputs`, `B_atom_safety_check_interlock`
- `B_atom_channel_enable`, `B_atom_channel_disable`
- `B_atom_path_set_asu`, `B_atom_path_set_scuu`
- `B_atom_correction_set_cmu`, `B_atom_correction_measure_cmu`

| Criterion | Assessment |
|---|---|
| Pros | Groups by user intent. `B_atom_safety_*` makes risk obvious. `A_atom_error_*` groups all error-related atoms together. Very readable for newcomers. |
| Cons | **Fatal flaw: naming collisions.** All three interfaces have `connect/open`, `identify`, `error`, `status`, and `wait_opc` operations. You must append a transport qualifier (e.g. `_b1500`, `_wgfmu`) to disambiguate, making it a 4-level name with the qualifier at the end instead of the middle. Scanning the MCP list, `A_atom_session_*` shows a mix of B1500 direct, WGFMU library, and EasyEXPERT remote tools — tools with completely different preconditions and failure modes. This is dangerous for an AI agent that must know which session is required before calling a tool. |
| Safety clarity (B) | Excellent for core safety. `B_atom_safety_*` is immediately obvious. But module-specific B atoms (`calibration_*`, `correction_*`) lose interface context. |
| Future scalability | Semantic categories are stable. But every new interface adds transport-qualifier variants to every semantic bucket. |
| Scan-friendliness | Excellent within one transport. Poor across transports — the MCP list interleaves tools requiring different sessions. |

**Verdict**: Reject as primary taxonomy. The transport-ambiguity problem is fundamental. However, the semantic insight is valuable — see Candidate 5.

---

### Candidate 5: Hybrid — Interface-Primary with Documented Semantic Facets

#### Candidate 5a: Relabeled Status Quo (Minimum Change)

**Pattern**: `{A|B}_atom_{interface}_{action}` — same code, but rename the *concept* from "subsystem" to "interface" in all documentation and mental models.

**Interface definitions** (replacing "subsystem"):

| Interface tag | Meaning | Transport | Session precondition |
|---|---|---|---|
| `b1500` | B1500A mainframe FLEX command interface | GPIB/VISA | `A_atom_b1500_connect` |
| `wgfmu` | WGFMU instrument library interface | DLL session | `A_atom_wgfmu_open_session` |
| `easyexpert` | EasyEXPERT remote control interface | TCP socket | (implicit in EasyEXPERT remote connection) |

Module-specific operations (SMU, ASU, SCUU, CMU, QSCV, SPGU) stay under `b1500` because they are commanded via the B1500A FLEX interface. The module name appears naturally in the action: `set_smu_filter`, `set_asu_path`, `set_cmu_correction`.

**Pros**: Zero code change. Fixes the conceptual confusion through documentation. Correct for the actual API-boundary grouping.

**Cons**: `b1500` bucket remains large and heterogeneous for B atoms. Doesn't help users see at a glance what kind of B atom they're looking at within the b1500 interface.

#### Candidate 5b: Interface-Primary with Semantic Sub-grouping in B atoms

**A atom pattern**: `A_atom_{interface}_{action}` — unchanged from current.

**B atom pattern**: `B_atom_{interface}_{domain}_{action}` — adds a semantic domain field for B atoms only.

B atom domains within `b1500`:
- `safety`: abort, zero_outputs, zero_all_outputs, confirm_zero, check_interlock, preflight
- `reset`: reset, initialize
- `cal`: self_test, self_calibration, diagnostics, set_auto_calibration
- `channel`: enable_channels, disable_channels, recover_zeroed
- `smu`: set_smu_filter, set_series_resistor, set_adc_zero
- `asu`: set_asu_path, set_asu_1pa_range, set_asu_indicator
- `scuu`: set_scuu_path, set_scuu_indicator
- `cmu`: set_cmu_correction, measure_cmu_correction, set_cmu_phase_mode, perform_cmu_phase_comp, clear_cmu_correction
- `qscv`: qscv_offset_cancel

B atom domains within `wgfmu`:
- `safety`: initialize, abort, connect, disconnect
- `cal`: self_calibration, self_test
- `policy`: treat_warnings_as_errors

B atom domains within `easyexpert`:
- `safety`: abort_measurement, set_standby
- `cal`: zero_cancel_on, zero_cancel_off, measure_zero_cancel, query_zero_cancel_state

**Examples**:
- `B_atom_b1500_safety_abort` (was `B_atom_b1500_abort`)
- `B_atom_b1500_safety_zero_all_outputs` (was `B_atom_b1500_zero_all_outputs`)
- `B_atom_b1500_smu_set_filter` (was `B_atom_b1500_set_smu_filter`)
- `B_atom_b1500_asu_set_path` (was `B_atom_b1500_set_asu_path`)
- `B_atom_b1500_cmu_measure_correction` (was `B_atom_b1500_measure_cmu_correction`)
- `B_atom_wgfmu_safety_abort` (was `B_atom_wgfmu_abort`)
- `B_atom_easyexpert_safety_abort_measurement` (was `B_atom_easyexpert_abort_measurement`)

**Pros**: Safety-critical atoms get a `safety` domain that jumps out visually. Module-specific B atoms group under their module name. A atoms stay short and simple.

**Cons**: Adds a 4th naming level for B atoms, making names longer. Inconsistent depth between A (3-level) and B (4-level). Some domains are tiny (qscv has 1 atom).

#### Candidate 5c: Interface-Primary, Reframe WGFMU, Add Semantic Facets as Metadata

**A atom pattern**: `A_atom_{interface}_{action}` — unchanged.
**B atom pattern**: `B_atom_{interface}_{action}` — unchanged.

Changes:
1. Rename the concept from "subsystem" to "interface" in all docs.
2. Add a `domain` metadata tag to each tool's docstring/response for semantic grouping (e.g., `domain: safety`, `domain: smu_config`, `domain: cmu_correction`). This enables future filtering/grouping without changing the MCP tool name.
3. Document that `wgfmu` is a module-level interface (not a mainframe peer) in the naming convention docs.

**Pros**: Zero name change. Clean metadata for future UI filtering. Acknowledges the interface-vs-hardware distinction.

**Cons**: Metadata is invisible in the MCP tool list name.

---

## Recommended Taxonomy

After evaluating all candidates, I recommend **Candidate 5a (relabeled status quo) for A atoms** and a **modified Candidate 5b for B atoms**, with the modification being: use the semantic domain field only where it adds disambiguation value, specifically for the `b1500` interface which has the largest and most heterogeneous B atom set.

### A Atoms — Recommended

#### Naming Pattern

```
A_atom_{interface}_{action}
```

No change from current names. The change is purely conceptual: the middle field is documented as **interface** (= communication API boundary), not **subsystem** (= hardware component).

#### Interface Tags

| Tag | Full Name | Transport | Why Separate |
|---|---|---|---|
| `b1500` | B1500A FLEX command interface | GPIB/VISA session | Direct instrument control via FLEX command language + IEEE 488.2 common commands. All SMU/SPGU/CMU/ASU/SCUU mainframe-level operations go through this interface. |
| `wgfmu` | WGFMU instrument library interface | DLL/shared-lib session | Module with its own C-function API that bypasses the FLEX command layer. Separate session lifecycle, error model, and status queries. |
| `easyexpert` | EasyEXPERT remote control interface | TCP socket | PC software orchestration layer. SCPI-like command set. Controls B1500A indirectly through EasyEXPERT application logic. |

Future interface tags:
- `prober` — wafer prober control interface (separate instrument, separate session)
- `hspice` — HSPICE simulation interface (external software)
- `spgu_lib` — only if SPGU gets its own library API distinct from FLEX commands

#### Why This Is Better Than Alternatives

1. **Session-precondition grouping**: An AI agent scanning the MCP list immediately knows which session it needs. All `A_atom_b1500_*` require a GPIB session. All `A_atom_wgfmu_*` require a WGFMU library session. This is the most operationally important information for correct tool selection.

2. **No naming collisions**: Each interface has its own `connect`/`identify`/`error`/`status` without disambiguation suffixes.

3. **Short names**: Three-level naming keeps tool names scannable in the Cursor MCP tool panel.

4. **WGFMU correctly separated**: WGFMU *is* a separate interface even though it's a module inside B1500A. It has `openSession`/`closeSession`, its own error queue (`getError`/`getErrorSummary`), and its own status model (`getStatus`/`getChannelStatus`). Grouping it under `b1500` would hide these independent lifecycle requirements.

5. **EasyEXPERT correctly separated**: As software remote control, it has fundamentally different failure modes, latency, and capabilities from direct GPIB commands.

#### A Atom Mapping (all 60 atoms — no name changes)

**b1500 interface (18 atoms)**:

| Current Name | Semantic Facet | Stays As-Is |
|---|---|---|
| `A_atom_b1500_connect` | session | ✓ |
| `A_atom_b1500_disconnect` | session | ✓ |
| `A_atom_b1500_identify` | identity | ✓ |
| `A_atom_b1500_list_modules` | identity | ✓ |
| `A_atom_b1500_get_status` | status | ✓ |
| `A_atom_b1500_query_settings` | status | ✓ |
| `A_atom_b1500_read_error_queue` | error | ✓ |
| `A_atom_b1500_lookup_error` | error | ✓ |
| `A_atom_b1500_read_status_byte` | status | ✓ |
| `A_atom_b1500_wait_opc` | sync | ✓ |
| `A_atom_b1500_set_data_format` | format | ✓ |
| `A_atom_b1500_configure_timestamp` | timing | ✓ |
| `A_atom_b1500_reset_timestamp` | timing | ✓ |
| `A_atom_b1500_read_timestamp` | timing | ✓ |
| `A_atom_b1500_clear_output_buffer` | buffer | ✓ |
| `A_atom_b1500_query_buffer_count` | buffer | ✓ |
| `A_atom_b1500_read_output_buffer` | buffer | ✓ |
| `A_atom_b1500_configure_srq` | status | ✓ |

**wgfmu interface (16 atoms)**:

| Current Name | Semantic Facet | Stays As-Is |
|---|---|---|
| `A_atom_wgfmu_open_session` | session | ✓ |
| `A_atom_wgfmu_close_session` | session | ✓ |
| `A_atom_wgfmu_set_timeout` | session | ✓ |
| `A_atom_wgfmu_get_channel_ids` | identity | ✓ |
| `A_atom_wgfmu_get_status` | status | ✓ |
| `A_atom_wgfmu_get_channel_status` | status | ✓ |
| `A_atom_wgfmu_clear` | context | ✓ |
| `A_atom_wgfmu_open_log` | log | ✓ |
| `A_atom_wgfmu_close_log` | log | ✓ |
| `A_atom_wgfmu_read_error` | error | ✓ |
| `A_atom_wgfmu_read_error_summary` | error | ✓ |
| `A_atom_wgfmu_set_warning_level` | policy | ✓ |
| `A_atom_wgfmu_read_warning_summary` | error | ✓ |
| `A_atom_wgfmu_export_ascii` | export | ✓ |
| `A_atom_wgfmu_get_completed_event_count` | progress | ✓ |
| `A_atom_wgfmu_is_event_completed` | progress | ✓ |

**easyexpert interface (26 atoms)**:

| Current Name | Semantic Facet | Stays As-Is |
|---|---|---|
| `A_atom_easyexpert_identify` | identity | ✓ |
| `A_atom_easyexpert_clear_status` | status | ✓ |
| `A_atom_easyexpert_wait_opc` | sync | ✓ |
| `A_atom_easyexpert_read_system_error` | error | ✓ |
| `A_atom_easyexpert_list_workspaces` | catalog | ✓ |
| `A_atom_easyexpert_open_workspace` | session | ✓ |
| `A_atom_easyexpert_close_workspace` | session | ✓ |
| `A_atom_easyexpert_get_workspace_state` | status | ✓ |
| `A_atom_easyexpert_get_workspace_name` | status | ✓ |
| `A_atom_easyexpert_set_result_format` | format | ✓ |
| `A_atom_easyexpert_fetch_result` | buffer | ✓ |
| `A_atom_easyexpert_list_app_tests` | catalog | ✓ |
| `A_atom_easyexpert_select_app_test` | context | ✓ |
| `A_atom_easyexpert_list_preset_groups` | catalog | ✓ |
| `A_atom_easyexpert_select_preset_group` | context | ✓ |
| `A_atom_easyexpert_list_preset_setups` | catalog | ✓ |
| `A_atom_easyexpert_select_preset_setup` | context | ✓ |
| `A_atom_easyexpert_get_selected_name` | context | ✓ |
| `A_atom_easyexpert_set_device_tag` | metadata | ✓ |
| `A_atom_easyexpert_get_device_tag` | metadata | ✓ |
| `A_atom_easyexpert_set_repeat_count` | config | ✓ |
| `A_atom_easyexpert_get_repeat_count` | config | ✓ |
| `A_atom_easyexpert_reset_repeat_count` | config | ✓ |
| `A_atom_easyexpert_set_app_test_param` | config | ✓ |
| `A_atom_easyexpert_set_app_test_string` | config | ✓ |
| `A_atom_easyexpert_load_setup` | config | ✓ |

### B Atoms — Recommended

#### Naming Pattern

```
B_atom_{interface}_{action}
```

No structural change from current names. The key recommendation for B atoms is:

1. **Keep the interface-first grouping** — same justification as A atoms.
2. **Encode module/target in the action name** — this is already the current convention and it works well: `set_smu_filter`, `set_asu_path`, `set_cmu_correction`, `qscv_offset_cancel`.
3. **Add `domain` metadata in docstrings** — categorize each B atom by its operational domain for documentation, filtering, and risk-assessment purposes.

#### Why Not Add a 4th Level for B Atoms

Candidate 5b proposed `B_atom_{interface}_{domain}_{action}`. After analysis, this creates more problems than it solves:

- **Inconsistent depth** between A (3-level) and B (4-level) breaks the pattern.
- **Names become long**: `B_atom_b1500_safety_zero_all_outputs` (42 chars) vs `B_atom_b1500_zero_all_outputs` (29 chars).
- **Tiny domains**: `qscv` would have 1 atom. `reset` would have 2.
- **Module names are already in the action**: `set_smu_filter` contains `smu`, `set_asu_path` contains `asu`. Adding a domain field would create redundancy: `B_atom_b1500_smu_set_smu_filter` or require reshuffling: `B_atom_b1500_smu_set_filter` which loses grep-ability for `smu_filter`.

Instead, use the **action-name convention** to carry both the module target and the operational meaning. This is the current approach and it works.

#### B Atom Domain Classification (Metadata, Not Naming)

For documentation, docstrings, and future MCP metadata tags, classify each B atom into an operational domain:

**Within `b1500` interface:**

| Domain | Atoms | Risk Profile |
|---|---|---|
| `emergency` | `abort`, `zero_all_outputs`, `confirm_zero`, `check_interlock` | Highest — must always work. |
| `lifecycle` | `reset`, `initialize`, `preflight` | High — instrument-wide state change. |
| `channel` | `enable_channels`, `disable_channels`, `zero_outputs`, `recover_zeroed` | High — directly controls DUT-facing outputs. |
| `calibration` | `self_test`, `self_calibration`, `diagnostics`, `set_auto_calibration` | Medium — no DUT risk but takes time and changes calibration state. |
| `smu_config` | `set_smu_filter`, `set_series_resistor`, `set_adc_zero` | Medium — affects measurement path, not output safety. |
| `path_switching` | `set_asu_path`, `set_asu_1pa_range`, `set_asu_indicator`, `set_scuu_path`, `set_scuu_indicator` | High — physical relay switching while DUT may be connected. |
| `cmu_correction` | `set_cmu_correction`, `measure_cmu_correction`, `set_cmu_phase_mode`, `perform_cmu_phase_comp`, `clear_cmu_correction` | Medium — correction data management, requires fixture awareness. |
| `module_cal` | `qscv_offset_cancel` | Medium — measurement-accuracy calibration. |

**Within `wgfmu` interface:**

| Domain | Atoms | Risk Profile |
|---|---|---|
| `emergency` | `abort` | Highest — channels hold voltage at abort moment. |
| `lifecycle` | `initialize` | High — resets all WGFMU channels. |
| `channel` | `connect`, `disconnect` | High — enables/disables channel output through RSU. |
| `calibration` | `self_calibration`, `self_test` | Medium. |
| `policy` | `treat_warnings_as_errors` | Low — software behavior policy. |

**Within `easyexpert` interface:**

| Domain | Atoms | Risk Profile |
|---|---|---|
| `emergency` | `abort_measurement` | High — remote measurement cancel. |
| `standby` | `set_standby` | Medium — bias/standby state. |
| `calibration` | `zero_cancel_on`, `zero_cancel_off`, `measure_zero_cancel`, `query_zero_cancel_state` | Medium — remote zero-cancel management. |

#### B Atom Mapping (all 42 atoms — no name changes)

| Current Name | Interface | Domain | Stays As-Is |
|---|---|---|---|
| `B_atom_b1500_reset` | b1500 | lifecycle | ✓ |
| `B_atom_b1500_initialize` | b1500 | lifecycle | ✓ |
| `B_atom_b1500_abort` | b1500 | emergency | ✓ |
| `B_atom_b1500_self_test` | b1500 | calibration | ✓ |
| `B_atom_b1500_self_calibration` | b1500 | calibration | ✓ |
| `B_atom_b1500_diagnostics` | b1500 | calibration | ✓ |
| `B_atom_b1500_set_auto_calibration` | b1500 | calibration | ✓ |
| `B_atom_b1500_enable_channels` | b1500 | channel | ✓ |
| `B_atom_b1500_disable_channels` | b1500 | channel | ✓ |
| `B_atom_b1500_zero_outputs` | b1500 | channel | ✓ |
| `B_atom_b1500_zero_all_outputs` | b1500 | emergency | ✓ |
| `B_atom_b1500_confirm_zero` | b1500 | emergency | ✓ |
| `B_atom_b1500_check_interlock` | b1500 | emergency | ✓ |
| `B_atom_b1500_preflight` | b1500 | lifecycle | ✓ |
| `B_atom_b1500_recover_zeroed` | b1500 | channel | ✓ |
| `B_atom_b1500_set_smu_filter` | b1500 | smu_config | ✓ |
| `B_atom_b1500_set_series_resistor` | b1500 | smu_config | ✓ |
| `B_atom_b1500_set_adc_zero` | b1500 | smu_config | ✓ |
| `B_atom_b1500_set_asu_path` | b1500 | path_switching | ✓ |
| `B_atom_b1500_set_asu_1pa_range` | b1500 | path_switching | ✓ |
| `B_atom_b1500_set_asu_indicator` | b1500 | path_switching | ✓ |
| `B_atom_b1500_set_scuu_path` | b1500 | path_switching | ✓ |
| `B_atom_b1500_set_scuu_indicator` | b1500 | path_switching | ✓ |
| `B_atom_b1500_set_cmu_correction` | b1500 | cmu_correction | ✓ |
| `B_atom_b1500_measure_cmu_correction` | b1500 | cmu_correction | ✓ |
| `B_atom_b1500_set_cmu_phase_mode` | b1500 | cmu_correction | ✓ |
| `B_atom_b1500_perform_cmu_phase_comp` | b1500 | cmu_correction | ✓ |
| `B_atom_b1500_clear_cmu_correction` | b1500 | cmu_correction | ✓ |
| `B_atom_b1500_qscv_offset_cancel` | b1500 | module_cal | ✓ |
| `B_atom_wgfmu_initialize` | wgfmu | lifecycle | ✓ |
| `B_atom_wgfmu_self_calibration` | wgfmu | calibration | ✓ |
| `B_atom_wgfmu_self_test` | wgfmu | calibration | ✓ |
| `B_atom_wgfmu_treat_warnings_as_errors` | wgfmu | policy | ✓ |
| `B_atom_wgfmu_connect` | wgfmu | channel | ✓ |
| `B_atom_wgfmu_disconnect` | wgfmu | channel | ✓ |
| `B_atom_wgfmu_abort` | wgfmu | emergency | ✓ |
| `B_atom_easyexpert_abort_measurement` | easyexpert | emergency | ✓ |
| `B_atom_easyexpert_set_standby` | easyexpert | standby | ✓ |
| `B_atom_easyexpert_zero_cancel_on` | easyexpert | calibration | ✓ |
| `B_atom_easyexpert_zero_cancel_off` | easyexpert | calibration | ✓ |
| `B_atom_easyexpert_measure_zero_cancel` | easyexpert | calibration | ✓ |
| `B_atom_easyexpert_query_zero_cancel_state` | easyexpert | calibration | ✓ |

### Why WGFMU Is Correctly At Interface Level

The user's concern that WGFMU "should not appear at the same conceptual level as B1500" deserves a direct response.

**In hardware terms**, WGFMU is a module inside B1500A. It is not a peer.

**In API terms**, WGFMU *is* a peer-level interface. Here's why:

| Property | B1500A direct | WGFMU library | EasyEXPERT remote |
|---|---|---|---|
| Session open/close | `PyVISA open` / `close` | `WGFMU_openSession` / `closeSession` | TCP connect |
| Error model | `ERR?` / `ERRX?` / `EMG?` | `WGFMU_getError` / `getErrorSummary` | `:SYSTem:ERRor:NEXT?` |
| Status model | `*STB?` / `*LRN?` | `WGFMU_getStatus` / `getChannelStatus` | `:WORKspace:STATe?` |
| Calibration | `*CAL?` / `*TST?` / `DIAG?` | `WGFMU_doSelfCalibration` / `doSelfTest` | CALibration subsystem |
| Abort | `AB` | `WGFMU_abort` | `:ABORt` |
| Command syntax | FLEX 2-4 char commands | C function calls | SCPI colon-delimited |

Each interface requires independent session management, has independent error propagation, and follows a different protocol grammar. Grouping them together would force every tool consumer to read the docstring to know which session precondition applies.

**The taxonomy groups by API boundary, not hardware hierarchy.** The naming convention doc should state this explicitly to prevent the "WGFMU is a peer of B1500A" misinterpretation.

### Future C Atom Interface Assignment

The interface-primary taxonomy extends naturally to C atoms:

| Future C atom examples | Interface | Rationale |
|---|---|---|
| `C_atom_b1500_spot_iv` | b1500 | Uses TI/TV/TIV FLEX commands over GPIB |
| `C_atom_b1500_sweep_iv` | b1500 | Uses WV/WI/MM/XE FLEX commands |
| `C_atom_b1500_cv_sweep` | b1500 | Uses MFCMU FLEX commands |
| `C_atom_b1500_qscv_measure` | b1500 | Uses QSCV FLEX commands |
| `C_atom_b1500_spgu_pulse` | b1500 | Uses SPGU FLEX commands (unless SPGU gets own API) |
| `C_atom_wgfmu_fastiv` | wgfmu | Uses WGFMU library waveform/execute/getMeasureValue calls |
| `C_atom_wgfmu_pulse_stress` | wgfmu | Uses WGFMU library pattern/sequence/execute calls |
| `C_atom_easyexpert_run_app_test` | easyexpert | Uses `:BENCh:SELected:RUN` remote command |

---

## Migration Impact

### What Changes In Names

**Nothing.** All 102 atom names remain exactly as they are.

### What Changes In Documentation

1. **Rename concept**: All references to "subsystem" in docs, docstrings, naming-convention explanations, and skill references change to "**interface**".

2. **Add interface definition table**: The three-row table (b1500 = FLEX/GPIB, wgfmu = instrument library, easyexpert = remote SCPI) goes into the naming convention section of `server.py` module docstring and `instrument-interaction-tools.md`.

3. **Add domain metadata**: Each B atom docstring gets a `Domain:` line (e.g., `Domain: emergency`, `Domain: channel`, `Domain: calibration`). This is informational metadata, not a naming change.

4. **Add WGFMU clarification**: Documentation explicitly states that WGFMU is a module inside B1500A that has its own API, and is grouped separately because of the API boundary, not because it is an architectural peer to the mainframe.

### What Should Stay Stable

- All `{A|B}_atom_{interface}_{action}` MCP tool names.
- All flow names (`A_flow_*`, `B_flow_*`, `AB_flow_*`).
- The `_fake_response` schema.
- The `basis` field values.
- The A/B classification of every existing atom.

### Estimated Documentation Diff

| File | Change |
|---|---|
| `server.py` module docstring (line 8-12) | Replace "subsystem" with "interface". Add interface definition table. |
| `server.py` section comments (lines 73, 345, 550, 903, 1295, 1396) | Replace "b1500:" etc. labels with interface-qualified labels. |
| `instrument-interaction-tools.md` (lines 5-11) | Replace "subsystem" with "interface". Add interface table. |
| `atom_taxonomy_opus.md` | If kept as reference, annotate with interface-vs-subsystem reframing. |
| B atom docstrings (42 atoms) | Add `Domain: {emergency|lifecycle|channel|calibration|...}` line. |

---

## Open Questions

1. **Should `domain` become a field in `_fake_response`?** Adding `domain: "emergency"` to the response dict would make B atom risk level machine-readable without changing tool names. Cost: minor code change. Benefit: flows and safety gates can filter by domain programmatically.

2. **Should C atoms follow the same interface-primary pattern?** Provisionally yes (see Future C Atom table above). But C atoms will need a secondary qualifier for measurement type (spot, sweep, pulse, CV, etc.). The pattern might become `C_atom_{interface}_{measurement_type}_{action}` — a 4-level name that is justified by the greater complexity of measurement configuration.

3. **What happens if SPGU gets its own library API?** It would become a new interface tag (e.g., `spgu` or `spgu_lib`). This is the same pattern as WGFMU. The taxonomy handles this gracefully.

4. **What happens when prober and HSPICE are added?** They become new interface tags: `prober`, `hspice`. Each has its own session lifecycle, error model, and command set. The pattern works without modification.

5. **Is the `b1500` interface tag the best name?** Alternatives considered:
   - `flex` — accurate (it's the FLEX command language) but obscure to newcomers.
   - `gpib` — too transport-specific; VISA could use USB or LAN.
   - `direct` — too vague.
   - `mainframe` — accurate for hardware hierarchy but wrong for the API concept (the API controls modules too, not just the mainframe).
   - **`b1500` is the best available name.** It's the instrument model that defines the FLEX command language. Every user of this system knows what "B1500A" means. The interface-definition table resolves any ambiguity about scope.

6. **Should A atoms also get semantic facet metadata?** Lower priority than B atoms, but useful for documentation. The semantic facets for A atoms (session, identity, status, error, buffer, format, timing, sync, catalog, context, log, progress, config, metadata, export) are already documented in the mapping tables above.

7. **When `b1500` B atom count exceeds ~40, should we revisit?** The current 29 B atoms under `b1500` are manageable. If SPGU mode atoms, trigger I/O atoms, and DIO atoms are added (estimated 10-15 more), the count approaches 40-45. At that point, revisit whether a 4th-level domain field (Candidate 5b) is warranted for B atoms specifically. The domain metadata added now provides the migration path.
