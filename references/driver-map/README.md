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
| `legacy-catalog/*.md` | The v0.2 per-family tool catalogs, moved verbatim from the old skill by WP0.4. Their links into the old skill tree only resolve at the archive tag |

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
| `target` | list of `B1500Driver.<method>`s (or a `commands.<builder>` when no method sends the command), or `unmapped` |
| `unmapped_flex` | only on partially mapped atoms: the FLEX entries no driver target covers |
| `priority` | `m1`, `m2` or `later` (scale below) |
| `note` | why a hand decision overrides the automatic rule, or where the capability went instead |
| `legacy_priority`, `successor` | D only: the v0.2 `P0`/`P1`/`P2`, and the new analysis/archive/catalog element that replaces it (§2.6–2.8) |

`flows[]`: `id` and `class` of all 97 legacy flows (A, B, C, AB, D, CD). They are frozen history only. The new
architecture composes measurements as recipes (§2.6), not as flows.

`commands[]`: one line per manual mnemonic. Fields: `source` (`detailed` record, `grouped` index name, or
`extra` = named by a legacy atom but missing from the summary), `pdf_pages`/`printed_pages` (detailed and extra
entries, and grouped entries listed in `GROUPED_PAGES`; every mapped command has pages), `target` (method, else builder, else `unmapped`), `builder`, `priority`, `atoms` (legacy atoms
naming it), `note`.

## Target vocabulary (§2.3)

| FLEX | `B1500Driver` method | `driver/commands.py` builder |
|---|---|---|
| `*IDN?` / `UNT?` / `ERRX?` / `*STB?` / `LOP?` | `identify` / `modules` / `errors` / `status_byte` / `output_state` | `IDN_Q` / `UNT_Q` / `ERRX_Q` / `STB_Q` / `LOP_Q` |
| `AB` / `DZ` / `CL` | `abort` / `zero` / `disconnect` | `AB` / `dz` / `cl` |
| `*RST` / `*TST?` / `*CAL?` | `reset` / `self_test` / `self_calibrate` | `RST` / `TST_Q` / `CAL_Q` (added by WP1.3) |
| `FMT` / `AAD`, `AIT` / `RI`, `RV` / `CN` / `DV` | `set_format` / `set_integration` / `set_range` / `enable` / `force_v` | `fmt` / `aad`, `ait` / `ri`, `rv` / `cn` / `dv` |
| `MM` (mode 2 only), `CMM`, `WV`, `WT`, `WM` | `staircase_v` | `mm`, `cmm`, `wv`, `wt`, `wm` |
| `XE` + output-buffer read | `execute_and_read` | `XE` |
| `*OPC?` | `wait_complete` (added by WP1.3) | `OPC_Q` |

Every other mnemonic is `unmapped`: 255 of the 280 command entries, and 239 of the 282 atoms (all 42 D atoms
among them). Of the 43 mapped atoms, 19 are partial. Some partial atoms share only `XE` with the driver, such
as the CMU, pulsed and sampling execute atoms, because their `MM` mode is not supported.

## Priority scale

| Priority | Meaning | Atoms |
|---|---|---|
| `m1` | M1 vertical path (status → validate → staircase Id-Vg → archive → Vth), `safe_shutdown` cleanup and `system.*` self-test/self-cal. These are the §2.3 driver methods plus the M1 analysis/archive successors of D atoms | 44 |
| `m2` | M2 SMU recipe pack: the six cards, stepped and double sweeps, and the M2 analysis methods. Also the rest of the simulator's FLEX subset v1 (`AV`, `BC`, `NUB?`, `TSC`), plus `DI`/`WI` only if a card needs them | 14 |
| `later` | Reserved, `not_implemented` or M4+: pulse, sampling, search, CMU/QSCV, WGFMU, SPGU, HV/HC units and expanders, ASU/SCUU, selectors and DIO, EasyEXPERT, timestamps, program memory and the like | 224 |

How a priority is set:
1. A mapped FLEX entry counts as `m1`. An unmapped one counts as `m2` if it is in `M2_COMMANDS`, else `later`.
   An `MM <n>` entry with n ≠ 2 is `later`. Host tokens: the output-buffer read and `session.close` are `m1`.
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
  checks them against the chapter-4 formula (PDF = printed 4-N + 318), and `tests/unit/test_driver_commands.py`
  checks that each builder docstring in `driver/commands.py` cites the same PDF pages.
- §2.3 lists no builder constants for `*RST`, `*TST?` and `*CAL?`; WP1.3 added `RST`, `TST_Q` and `CAL_Q` to
  `driver/commands.py` (the only module the FLEX-literal lint allows to hold mnemonics).
- `AAD` → `set_integration` and `CMM` → `staircase_v` are this map's attribution choices; §2.3 leaves them open.
