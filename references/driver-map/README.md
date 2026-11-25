# Driver map: legacy v0.2 taxonomy → new B1500Driver

Frozen history plus a working map for FLEX driver work. The v0.2 fake MCP server exposed 379 tools
(282 atoms, 97 flows; git tag `archive/v0.2-fake-mcp`). The re-architecture (`docs/design/blueprint.md`) replaces
them with a 10-tool server over one `B1500Driver` (§2.3). This folder records what each legacy atom did, which
FLEX commands it named, where that capability now lives, and when it is planned.

This folder is **never auto-loaded**: agent instructions and skills do not point at it. Developers read it on
demand for FLEX driver work (WP1.3 onward).

| File | Content |
|---|---|
| `flex-driver-map.yaml` | GENERATED: 282 atoms, 97 flow names, and one entry per FLEX command of the manual summary. Do not edit by hand |

The v0.2 per-family tool catalogs are no longer in the tree; read them at the tag with
`git show archive/v0.2-fake-mcp:.agents/skills/b1500-semiconductor-testing/references/mcp-tools/<file>.md`.

## Regenerate or check

```bash
uv run python scripts/build_driver_map.py            # rewrite flex-driver-map.yaml
uv run python scripts/build_driver_map.py --check    # exit 1 if counts, coverage or file content are off
uv run python scripts/build_driver_map.py --source-dir <checkout>/src/b1500_test_agent/mcp   # read a working tree
```

The builder reads the legacy package `src/b1500_test_agent/mcp/` from git tag `archive/v0.2-fake-mcp` (by default)
with `git show`, parses it with `ast` and never imports it, so it keeps working after WP0.5 deletes that code.
It fails unless there are exactly 282 atoms (82 A, 59 B, 99 C, 42 D) and 97 flows (20 A, 16 B, 31 C, 19 AB,
7 D, 4 CD), and every command in `references/manuals/structured/b1500a-command-summary.yaml` (each `command:`
record and each `grouped_command_index` name) has an entry. `tests/unit/test_driver_map.py` runs the same
checks on the committed YAML. The rebuild from the tag is skipped when the tag is missing, for example in a
shallow checkout.

Where the data comes from: for A/B/C atoms, the FLEX basis is the second argument of `_fake_response` (C atoms
pass it through `_c_response`). For D atoms it comes from the `_SPECS` catalog. The mapping decisions are tables
at the top of the script: `COMMAND_TARGETS`, `M2_COMMANDS`, `ATOM_OVERRIDES`, `D_SUCCESSORS`, `MM_MODE_HINTS`,
`WILDCARD_GROUPS`, `EXTRA_COMMANDS`, `GROUPED_PAGES` and `HOST_TOKENS`. To change a decision, edit the table and regenerate.

## YAML fields

`atoms[]` (one line per atom, in legacy registration order):

| Field | Meaning |
|---|---|
| `id`, `class` | legacy tool name and class (`A` connection/status, `B` safety/state, `C` measurement, `D` analysis) |
| `basis` | the legacy basis list, verbatim |
| `flex` | normalized FLEX mnemonics from `basis`. `MM13` and `MM` with a known mode become `MM 13`. Prefix wildcards (`BD*`, `LS*`, `BS*`, `DSMPL*`) expand within their manual group. WGFMU library calls, EasyEXPERT SCPI and host operations are not FLEX and are left out. Always empty for D |
| `target` | list of `B1500Driver.<method>`s (or a `flex.<builder>` when no method sends the command), or `unmapped` |
| `unmapped_flex` | only on partially mapped atoms (and on atoms mapped through `ATOM_SUCCESSORS`): the FLEX entries no driver target covers |
| `priority` | `m1`, `m2` or `later` (scale below) |
| `note` | why a hand decision overrides the automatic rule, or where the capability went instead |
| `legacy_priority`, `successor` | D only: the v0.2 `P0`/`P1`/`P2`, and the new analysis/archive/catalog element that replaces it (§2.6–2.8) |

`flows[]`: `id` and `class` of all 97 legacy flows (A, B, C, AB, D, CD). They are frozen history only. The new
architecture composes measurements as recipes (§2.6), not as flows.

`commands[]`: one line per manual mnemonic. Fields: `source` (`detailed` record, `grouped` index name, or
`extra` = named by a legacy atom but missing from the summary), `pdf_pages`/`printed_pages` (detailed and extra
entries, and grouped entries listed in `GROUPED_PAGES`; every mapped command has pages), `target` (method, else builder, else `unmapped`), `builder`, `priority`, `atoms` (legacy atoms
naming it), `note`.

Coverage ledger (blueprint v2 §9, WP7.7): every atom, flow and command also carries `family` (`smu`, `cmu`, `spgu`,
`wgfmu`, `system`) and `scope`: `mapped` (a driver target, a D-atom `successor`, an `ATOM_SUCCESSORS` target, or a
flow `target` list of `recipe:<id>`, `kind:<id>`, `analysis:<method>` or `B1500Driver.<method>`), `out_of_scope`
(with `reason`, from `OUT_OF_SCOPE`) or `open`. Families come from `entry_family` (id words) and, for commands, from
the manual category (`COMMAND_CATEGORY_FAMILY`) with the `COMMAND_FAMILY` overrides. `counts.ledger` holds
mapped/out_of_scope/open per family and entry type; `--check` fails on an `open` entry of a family in
`CLOSED_FAMILIES` (`smu` since WP7.7, `cmu` since WP8.6, `spgu` with the 16440A selector since WP9.6; the module
closure 10.8 adds `wgfmu`, WP11.2 the rest). The `cmu` family holds the MFCMU, SCUU and QSCV entries; the GNDU has no
legacy atom, flow or command (its v2 parts are rule R-GNDU-01 and the simulator's return-current accounting, WP8.5).
CMU out of scope: the high-speed spot C `TC`/`TTC` with its monitors `TMACV`/`TMDCV` and the timer-start outputs
`TACV`/`TDCV` (the MM 17 spot and MM 26 time stamps serve the recipes).

`ATOM_SUCCESSORS` (WP9.6) maps an A/B/C atom whose legacy basis names a command v2 does not send for that purpose
to the driver target that serves it, with the legacy command left in `unmapped_flex` and the reason in `note`:
`B_atom_output_spgu_enable_channels` (`CNX` -> `CN`, `enable`) and `A_atom_flex_query_selector_status` (`ERS?`, the
raw digital I/O bits -> `ERSSP?`, `selector_state`). It applies only when the basis maps to nothing. The SPGU
closure also files the output comparison commands `SOPC`/`SOVC` under `smu` (they serve the HVMCU/UHCU/UHVU
expanders, PG p508-510), with the expander reason; the legacy atoms that named them SPGU open/short compensation
stay `spgu`, out of scope with the same reason. SPGU out of scope: the setup read-back queries (`SIM?`, `SPV?`, ...),
`MSP` (the SPGU as a sampling source) and raw digital I/O (`ERM`, `ERC`, `ERS?`).

## Target vocabulary (§2.3)

| FLEX | `B1500Driver` method | `driver/flex/` builder |
|---|---|---|
| `*IDN?` / `UNT?` / `ERRX?` / `*STB?` / `LOP?` | `identify` / `modules` / `errors` / `status_byte` / `output_state` | `IDN_Q` / `UNT_Q` / `ERRX_Q` / `STB_Q` / `LOP_Q` |
| `AB` / `DZ` / `CL` | `abort` / `zero` / `disconnect` | `AB` / `dz` / `cl` |
| `*RST` / `*TST?` / `*CAL?` | `reset` / `self_test` / `self_calibrate` | `RST` / `TST_Q` / `CAL_Q` (added by WP1.3) |
| `FMT` / `AAD`, `AIT` / `RI`, `RV` / `CN` / `DV` / `DI` | `set_format` / `set_integration` / `set_range` / `enable` / `force_v` / `force_i` | `fmt` / `aad`, `ait` / `ri`, `rv` / `cn` / `dv` / `di` |
| `MM` (modes 2 and 16), `CMM`, `WV`, `WI`, `WSV`, `WSI`, `WNX`, `WT`, `WM` | `staircase` (`staircase_v`: the v1 voltage-primary entry) | `mm`, `cmm`, `wv`, `wi`, `wsv`, `wsi`, `wnx`, `wt`, `wm` |
| `MM 10`, `MCC`, `ML`, `MT`, `MSC`, `MV`, `MI` (sampling; WP7.4) | `sampling_setup` (`MT`, `MV`/`MI` also `sampling_update`) | `mm`, `mcc`, `ml`, `mt`, `msc`, `mv`, `mi` |
| `TSC` / `TSR` (time stamps; WP7.4) | `set_time_stamp` / `reset_timer` | `tsc` / `tsr` |
| `XE` + output-buffer read | `execute_and_read` | `XE` |
| `*OPC?` | `wait_complete` (added by WP1.3) | `OPC_Q` |
| `CM`, `*LRN?`; `ERMOD?`, `ERSSP?`, `SPST?`, `CORRST?`, `ADJ?` | `set_auto_calibration`, `auto_calibration`; the probe queries | WP5.6; WP6.1 |
| MFCMU: `IMP`, `FC`/`ACV`/`DCV`, `RC`, `ACT`, `LMN`, the MM 18-26 sources and timing, `ADJ`, `CORRL`, `CLCORR`, `CORR?`, `DCORR`, `CORRDT`, `CORRST`; `MM` 17-20, 22, 23, 26 (`MM_MODE_TARGETS`); SCUU `SSP`, `SSL` | `CmuOps` (`apply_cmu_signal`, `cv_sweep`, `cf_sweep`, ...), `SwitchOps.scuu_route` | WP8.1 |
| SMU conditioning `FL` / `SSR` / `AZ` / `AV` / `RM`; `WNCC` (WP7.7) | `set_filter` / `set_series_resistor` / `set_adc_zero` / `set_averaging` / `set_range_mode`; `clear_sweep_sources` | `fl` / `ssr` / `az` / `av` / `rm`; `wncc` |
| MFCMU correction data `CORRDT?` (WP8.6; with `CORRL?` for the count) | `correction_data`, `correction_data_list` | `corrdt_q` |

Mapped since: `CM`, `*LRN?` (WP5.6); the probe queries `ERMOD?`, `ERSSP?`, `SPST?`, `CORRST?`, `ADJ?` (WP6.1); the
sampling setup `MM 10`, `MCC`, `ML`, `MT`, `MSC`, `MV`, `MI` and the time stamps `TSC`, `TSR` (WP7.4); `DI`, `WI`,
`WSV`, `WSI`, `WNX` and `MM 16` (WP7.2); the spot setup `MM 1` and the ASU `SAP`, `SAR`, `SAL` (WP7.1); the MFCMU
commands with `MM` 17-20, 22, 23, 26 and the SCUU `SSP`, `SSL` (WP8.1). Every other mnemonic is `unmapped`: 202 of
the 280 command entries, and 204 of the 282 atoms (all 42 D atoms among them). Of the 78 mapped atoms, 10 are
partial. Some partial atoms share only `XE` with the driver, such as the pulsed and QSCV execute atoms, because their
`MM` mode is not supported.

## Priority scale

| Priority | Meaning | Atoms |
|---|---|---|
| `m1` | M1 vertical path (status → validate → staircase Id-Vg → archive → Vth), `safe_shutdown` cleanup and `system.*` self-test/self-cal. These are the §2.3 driver methods plus the M1 analysis/archive successors of D atoms; v2 additions that map (above) count here too | 53 |
| `m2` | M2 SMU recipe pack: the six cards, stepped and double sweeps, and the M2 analysis methods. Also the rest of the simulator's FLEX subset v1 (`AV`, `BC`, `NUB?`, `TSC`) | 12 |
| `later` | Reserved, `not_implemented` or M4+: pulse, sampling, search, CMU/QSCV, WGFMU, SPGU, HV/HC units and expanders, ASU/SCUU, selectors and DIO, EasyEXPERT, timestamps, program memory and the like | 217 |

How a priority is set:
1. A mapped FLEX entry counts as `m1`. An unmapped one counts as `m2` if it is in `M2_COMMANDS`, else `later`.
   An `MM <n>` entry is mapped when `MM_MODE_TARGETS` names the driver method that sends mode n (1, 2, 10, 16 and
   the MFCMU modes 17-20, 22, 23, 26), else `later`. Host tokens: the output-buffer read and `session.close` are `m1`.
   WGFMU and EasyEXPERT tokens are `later`. An atom starts at the latest priority among its entries.
2. If the atom id names a later-scope unit (`wgfmu`, `easyexpert`, `spgu`, `cmu`, `qscv`, `hvsmu`, `hcsmu`,
   `uhcu`, `hvmcu`, `uhvu`, `asu`, `scuu`, `selector`, `dio`), the atom is `later` even if `XE` maps.
3. `ATOM_OVERRIDES` pins `m1` where an atom's core function is M1 and only an auxiliary command comes later
   (for example, `get_status` without `*LRN?`). Each override carries a `note`.
4. D atoms take their priority from `D_SUCCESSORS`.

## Known gaps and handoffs

- `HSS` (high-speed spot standard) is named by `C_atom_smu_configure_high_speed_spot` but is missing from the
  command summary. It is recorded as an `extra` command: Programming Guide PDF page 438, printed 4-120, checked
  with `pdftotext` on 2026-11-17. `references/manuals/**` stays unmodified.
- WP1.3 read the syntax of `AAD`, `AIT`, `CMM`, `LOP?`, `RI`, `RV`, `WM`, `WT` and `WV` (grouped-only in the
  summary) from the PDF with `pdftotext` on 2026-11-17 and recorded their pages in `GROUPED_PAGES`; the builder
  checks them against the chapter-4 formula (PDF = printed 4-N + 318), and `tests/unit/test_driver_flex.py`
  checks that each builder docstring in `driver/flex/` cites the same PDF pages.
- §2.3 lists no builder constants for `*RST`, `*TST?` and `*CAL?`; WP1.3 added `RST`, `TST_Q` and `CAL_Q` (now in
  `driver/flex/core.py`; `driver/flex/` is the only package the FLEX-literal lint allows to hold mnemonics).
- `AAD` → `set_integration` and `CMM` → `staircase_v` are this map's attribution choices; §2.3 leaves them open.
