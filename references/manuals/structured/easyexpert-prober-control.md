# EasyEXPERT Prober Control Extraction

Source PDF: `../Keysight EasyEXPERT Software.pdf`  
Primary pages: PDF 479-489, printed 8-13 to 8-24. Related Repeat Measurement flow: PDF 91-99, printed 1-75 to 1-83.

## Coverage Note

This file extracts procedure concepts, command-line arguments, response XML shape, and wafer automation implications. It does not fully enumerate every supported prober model/driver file path; those require a visual pass over the original PDF screenshots and utility folders.

## Integration Model

| Concept | Page refs | Extracted structure | MCP/skill implication |
|---|---:|---|---|
| Repeat Measurement procedure hooks | PDF 479-480 / printed 8-14 to 8-15; Ch 1 PDF 91-99 | EasyEXPERT calls external `.exe` procedures at Start, Before Measurement, After Measurement, Abort, Final. Status returned by procedures can stop repeat execution. | Treat wafer automation as an external procedure contract, not as native EasyEXPERT measurement logic. |
| Stop condition | PDF 480 | Repeat stops if `Count >= limit` or if procedure returns status True and the Procedure return condition box is checked. | MCP run loop should track both die count and prober-returned stop flag. |
| Auto Device ID | PDF 480 | Procedure response `device_id` can populate Device ID when Automatically fill in Device ID is checked. | Map prober site coordinate to result metadata. |
| Procedure path and arguments | PDF 480 | Full path to procedure executable plus arguments such as `-a GPIB0::5::INSTR -l C:	emp\prb.log`. | MCP should store prober connection config separately from measurement recipe. |

## `prober_info.ini`

Page refs: PDF 482 / printed 8-17.

| Key | Meaning | Notes |
|---|---|---|
| `[Prober] Address` | GPIB address of prober | Ignored if procedure uses `-a`. OCR example shows `GPIB::5::INSTR`; argument example uses `GPIB0::5::INSTR`. |
| `[Prober] LogMode` | Log creation mode (`True`/`False`) | Set `True` to create log file. |
| `[Prober] LogName` | Full path of log file | Ignored if procedure uses `-l`. |
| `[Target] UseID` | Device ID creation mode (`True`/`False`) | If True, `device_id = prefix:coordinate`; if False, coordinate only. |
| `[Target] SubsiteInfo` | Placeholder | Manual says set always False. |
| `[Target] WaferInfo` | Placeholder | Manual says set always False. |

Example XML response shown near `prober_info.ini`:

```xml
<Response>
  <Break>False</Break>
  <Target>waf1a:4 1</Target>
</Response>
```

## Procedure Executables

| Procedure | EasyEXPERT hook | Page refs | Arguments | Response | Behavior |
|---|---|---:|---|---|---|
| `Start_xxxx.exe` | Start Procedure | PDF 483 / printed 8-18 | `-a GPIB_address`, `-l log_file_name` | XML: `<Break>status</Break><Target>device_id</Target>` | Prompts for Device ID prefix, confirms wafer setup, moves chuck to first probing position, checks prober status, gets X-Y coordinate, chuck up, returns response. |
| `Iterator_xxxx.exe` | After Measurement Procedure | PDF 484 / printed 8-19 | `-a GPIB_address`, `-l log_file_name` | XML response with status and device_id | After each die measurement: chuck down, move to next probing position, check status, get X-Y coordinate, chuck up, return response. |
| `Final_xxxx.exe` | Final Procedure | PDF 485 / printed 8-20 | `-a GPIB_address`, `-l log_file_name` | None | Called after stop condition; sets wafer chuck down. |
| `Subsite_xxxx.exe` | Subsite move via application test / Quick Test | PDF 486-487 / printed 8-21 to 8-22 | `-a GPIB_address`, `-l log_file_name` (but manual recommends using `prober_info.ini` and ignoring arguments for Subsite move setup) | XML response with status and device_id | Moves wafer chuck to next subsite, reads device ID from prober, sets Device ID in result record. |
| `callProberDvr.exe` | Internal execution file used by Subsite move test definition | PDF 488 / printed 8-23 | Input: full path of `Subsite_xxxx.exe` | Outputs: `status` and `device_id` | Sends Subsite procedure to prober specified by `prober_info.ini` and receives response. |

## XML Response Contract

| Element | Meaning | Expected values | Use in EasyEXPERT |
|---|---|---|---|
| `<Break>` | Procedure status / stop flag | `False` means no error/continue; `True` means error or break condition | If Procedure return condition is enabled, `True` stops repeat measurement. |
| `<Target>` | Device/site identifier | Usually `prefix:coordinate`, e.g. `waf1a:3 1` | If auto-fill Device ID is enabled, becomes Device ID in result record. |

## Subsite Workflow

Page refs: PDF 486-489 / printed 8-21 to 8-24.

1. Open the `Subsite move` test setup from Application Test tab > Utility category.
2. Specify `ProberType` (`Cascade`, `Suss`, or `Vector`) or custom driver in `CustomProber`.
3. Save the setup to a preset group (`My Favorite Setup`).
4. Use Quick Test to arrange die measurements and Subsite move setup.
5. Open Repeat Measurement Setup and specify Start/Iterator/Final procedures and stop conditions.
6. Ensure `Subsite move` setup appears after measurements for each sub-die.

## Wafer Automation Implications

| Design question | Extraction result | Recommendation |
|---|---|---|
| Should MCP directly control prober movement? | EasyEXPERT delegates prober actions to external `.exe` procedures and uses XML status/target responses. | Mirror the procedure contract first; implement direct prober drivers only behind an explicit prober MCP boundary. |
| How should results be associated with wafer sites? | Device ID can be auto-filled from `<Target>device_id</Target>`. | Store wafer coordinate/site ID as first-class result metadata. |
| How should subsite loops be modeled? | Manual requires N-1 Subsite move setups for Suss prober when N subsites are defined. | MCP quick-test generator must validate subsite count vs inserted move steps. |
| Where is connection state stored? | `prober_info.ini` carries GPIB address/log config. | Keep prober connection config separate from measurement recipe and include provenance. |

## Uncertainties / Future Extraction

- Exact supported prober driver names and paths were not exhaustively extracted.
- The manual screenshots likely contain additional UI labels not represented in OCR.
- The XML contract appears simple (`Response/Break/Target`), but any error payload beyond `Break=True` was not found in sampled OCR pages.
- A future pass should inspect actual utility folders, if available, for executable names and command-line behavior.
