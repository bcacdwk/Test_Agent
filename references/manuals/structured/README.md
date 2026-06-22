# Structured Reference Data

This folder contains structured extraction artifacts derived from Keysight/Agilent B1500A-related manuals. Files are intended for fast lookup and MCP/agent design; they are not replacements for reading exact manual pages before implementing hardware-control code.

## Existing B1500A Programming Guide Files

| File | Format | Purpose | Coverage |
|---|---|---|---|
| `b1500a-command-summary.yaml` | YAML | Command lookup data for agents/tools. Includes 42 detailed records for high-value commands and 42 grouped categories from the Command Summary. | Broad command-name coverage; sampled detailed fields; reviewed 2026-06-22 |
| `b1500a-command-parameters.md` | Markdown tables | Channel numbers, MM modes, required commands before `XE`, FMT modes, status byte, query/data buffers, range concepts, timing parameters. | Practical reference extraction with verified status byte table; not a full numeric range database |
| `b1500a-error-codes.yaml` | YAML | Error code lookup with 62 sampled operation/self-test errors and 6 category coverage notes. | Partial/sampled (~40/150+ operation errors); exact gaps declared |
| `b1500a-initial-settings.md` | Markdown tables | Reset/default state, especially Table 2-13 initial settings. | Table 2-13 fully transcribed from PDF 179; CORRST annotation added; related reset notes included |

## B1530A WGFMU Files

Source PDF: `../../../../B1530A WGFMU.pdf`  
Index: `../b1530a-wgfmu-index.md`  
Manual: Agilent B1530A Waveform Generator/Fast Measurement Unit User's Guide, Edition 5, August 2012

| File | Format | Purpose | Coverage |
|---|---|---|---|
| `b1530a-wgfmu-api-reference.yaml` | YAML | Structured WGFMU API/function/concept/internal-command reference for tooling. | Instrument Library function groups, key parameters, units, limits, page references, and undocumented WGMA?/WGMB?/WGMS? references |
| `b1530a-wgfmu-waveform-timing.md` | Markdown tables | Waveform primitives, timing formulas, sampling/averaging behavior, trigger/sync rules, ALWG limits, and memory budgeting. | Pulse/waveform construction, `setMeasureEvent` behavior, current/voltage minimum timing tables, trigger synchronization, reliability/NVM caveats |
| `b1530a-wgfmu-error-codes.yaml` | YAML | Machine-readable error/status/warning extraction. | Library error codes, warning levels, status codes, operation errors, self-test errors, and calibration errors |
| `b1530a-wgfmu-examples.md` | Markdown tables | Structured programming example index. | Chapter 3 support sections, Examples 1-11, DC measurement flow, SMU/VISA integration notes |

Important WGFMU absence notes:

- The B1530A WGFMU manual does **not** provide explicit FeFET, FeCap, PUND, endurance, retention, wake-up, or switching-kinetics workflows.
- NBTI and RTS are mentioned only as bundled application/sample programs on the software CD; their methodologies are not documented in this manual.
- `exportAscii` CSV columns remain unresolved because the PDF OCR for Figure 4-1 is garbled.

## EasyEXPERT Software Files

Source PDF: `../Keysight EasyEXPERT Software.pdf`  
Index: `../keysight-easyexpert-software-index.md`

| File | Format | Purpose | Coverage |
|---|---|---|---|
| `easyexpert-application-test-catalog.yaml` | YAML/JSON-compatible YAML | Extracted Table 9-1 application-test catalog records with required modules and MCP recipe implications. | Broad catalog coverage from OCR; many rows marked partial due to complex table wrapping |
| `easyexpert-workflow-templates.md` | Markdown tables | Workflow templates for project/data model, classic/app test setup, execution, Data Display, export, calibration, and term mapping. | High-value workflow coverage; not every GUI field |
| `easyexpert-export-formats.yaml` | YAML/JSON-compatible YAML | Text/Excel/XSLT/remote result export structures, schema components, and parser implications. | Strong coverage of Ch 1 export settings and Ch 8 XSLT components |
| `easyexpert-prober-control.md` | Markdown tables | Prober control procedure contract, XML response shape, subsite workflow, wafer automation implications. | Good conceptual extraction; exact driver list/path details still need visual/tool-folder verification |
| `easyexpert-error-codes.yaml` | YAML/JSON-compatible YAML | Structured sampled Ch 11 error code mapping. | Partial/sampled; operation errors broadly covered, FLEX/self-test/converter sections not exhaustive |
| `easyexpert-bench-remote-control.md` | Markdown tables | Remote control architecture, BENCh/WORKspace/RESult/CALibration command concepts, and MCP design guidance. | Strong coverage of Ch 6 remote-control interface |

## Page References

PDF page references follow the PDF page markers shown by text extraction, for example `-- 179 of 617 --` or `-- 510 of 700 --`. Printed page references use the manual's chapter-page numbering such as `2-92`, `6-13`, or `9-5`.

## Extraction Notes

All files intentionally mark partial coverage and uncertainty. Use the exact PDF page references when implementing a driver, data parser, or automation skill that could affect real instruments or measurement results.

## Recommended WGFMU Next Passes

1. Image-based extraction of Figure 4-1 to recover exact `exportAscii` CSV format.
2. Full C/C#/HTBasic prototype extraction into a stricter schema.
3. Companion CD / EasyEXPERT extraction for NBTI and RTS application-test methodology.
4. Derived FeFET/NVM recipe documents built from WGFMU primitives with explicit non-manual provenance.
5. Executable memory-budget calculator for `setMeasureEvent` plans and looped sequences.
6. Investigation of WGMA?/WGMB?/WGMS? internal commands via firmware documentation or reverse engineering.
7. Verification of Example 9 (Id-Vg) nested-loop timing calculation step-by-step for Vth extraction tooling.

## Audit History

| Date | Reviewer | Scope | Key Actions |
|---|---|---|---|
| 2026-06-22 | opus-4.6-max | All 4 WGFMU structured files | 5-pass audit: added missing doSelfCal/Test `size` param, corrected WGMA?/WGMB?/WGMS? page refs from 160→161, added two-level validation and return code concepts, fixed Example 6 writeResults/writeResults2 error, added opus_review metadata to all files |
