# EasyEXPERT Workflow Templates

Source PDF: `../Keysight EasyEXPERT Software.pdf`  
Source index: `../keysight-easyexpert-software-index.md`

This file extracts reusable workflow shapes for MCP/skill design. It is not a GUI tutorial; it maps EasyEXPERT concepts to automatable primitives.

## Project / Data Model

| EasyEXPERT concept | Manual location | Structured meaning | Future MCP / skill concept | Notes |
|---|---:|---|---|---|
| Workspace | PDF 26-31, printed 1-10 to 1-15 | Top-level container for test setups, test records/results, and calibration data. | `workspace.open`, `workspace.list`, `workspace.close`, `workspace.backup` | Remote API mirrors part of this through WORKspace subsystem (PDF 441-442). |
| Preset Group / My Favorite | PDF 44-48, 100-101 | Named collection of saved test setups. | `preset_group.open`, `preset_group.list_setups`, `setup.select` | BENCh PRESet commands operate on these. |
| Test setup | PDF 32-48, 178-248 | Named setup instance for Classic/Application/Tracer/Quick test. | `setup.load`, `setup.save`, `setup.export`, `setup.import` | Setup name is recorded in result metadata. |
| Test record | PDF 53-59, 164-174 | Stored measurement result with metadata, flags, remarks, device ID, count. | `result.fetch`, `result.export`, `result.annotate`, `result.recycle` | Export schemas map Device ID to `TestTarget` and count to `IterationIndex`. |
| Device ID | PDF 44, 91-99, 480-488 | User/device label attached to result records; prober procedures can auto-fill it. | `device_id.set`, `wafer.current_site_id` | BENCh TAG sets Device ID remotely. |
| Count | PDF 32-48, 91-99, 427-431 | Measurement counter and repeat stop condition. | `run.count`, `repeat.limit` | BENCh COUNt sets/queries it. |

## GUI / Classic Test Setup Workflow

| Step | Manual location | Inputs | Output / state change | MCP implication |
|---|---:|---|---|---|
| Start EasyEXPERT and choose execution mode | PDF 20-22, printed 1-4 to 1-6 | Online/offline, VISA interface ID, GPIB address, model | EasyEXPERT process ready; model available via `@ANALYZER` | MCP should expose model/session state before allowing setup execution. |
| Open workspace | PDF 26-31; remote PDF 441-442 | Workspace name | Active workspace | Remote WORKspace subsystem can mirror this. |
| Select test mode | PDF 32-48 | Application, Classic, Tracer, Quick | Main screen changes active mode | MCP should distinguish setup templates from execution mode. |
| Define Classic Channel Setup | PDF 178-182, 183-204 | Unit, V Name, I Name, Mode, Function (VAR1/VAR2/VAR1'/CONST), Time/Index names | Channel/resource graph for measurement | Strong candidate for schema validation before instrument execution. |
| Define Measurement Setup | PDF 180-182 and mode-specific pages | Sweep start/stop/step, compliance, range, ADC/integration, hold/delay | Concrete measurement plan | Map to typed `classic_iv_sweep`, `cv_sweep`, `sampling` recipe inputs. |
| Configure Function/Auto Analysis/Display | PDF 221-226 | Expressions, read-out functions, graph variables | Derived functions and output display | Skill can generate expressions but should verify syntax against Ch 5. |
| Save to My Favorite | PDF 44-48, 100-101 | Setup name, preset group | Reusable setup in preset group | Required for remote PRESet:SETup:SELect workflows. |

## Application Test Definition Workflow

| Step | Manual location | Inputs | Output / state change | MCP implication |
|---|---:|---|---|---|
| Open Test Definition Window | PDF 251-252, printed 3-3 to 3-4 | Existing or new application definition | Three-tab authoring surface | MCP should model application tests as composite flows, not single primitive measurements. |
| Test Specification | PDF 253-261 | Category/name/icon/description; device parameters; test parameters | Parameter schema and resource requirements | Resource type list includes SMU/HPSMU/HCSMU/DHCSMU/HVSMU/HRSMU/MPSMU/MCSMU/HRSMU-ASU/GNDU/SPGU/HVSPGU/WGFMU/RSWGFMU/MFCMU/MFCMU-SCUU/SWM/UHCU/UHVU/HVMCU/NONE. |
| Define Layout | PDF 258-261 | X/Y/Width/TabIndex, grid, align/distribute | Main-screen parameter entry UI | MCP can ignore GUI layout except when generating EasyEXPERT-compatible definitions. |
| Test Output | PDF 262-263 | Analysis parameter definitions and display setup | Output variable names | MCP recipe should name outputs explicitly. |
| Test Contents | PDF 264-271 | Program components, flow control, local/external variables | Executable composite test flow | Use as basis for skill template generation. |
| GPIB I/O component | PDF 281-285 | Address, commands, readback | External instrument interaction | Potentially unsafe; MCP should require explicit driver boundary. |
| Command Execution component | PDF 288-294 | FLEX command, parameter definitions, format field | Direct B1500 command execution from application test | Prefer direct B1500 programming guide for low-level command validation. |

## Execution Workflows

| Workflow | Manual location | Sequence | Stop/abort behavior | MCP implication |
|---|---:|---|---|---|
| Single/Append/Repeat from GUI | PDF 32-50, 91-99 | Select setup -> set Device ID/Count -> Single/Append/Repeat | Abort button, repeat stop by count or procedure status | MCP should keep run state and support cancellation. |
| Quick Test | PDF 89-90 | Ordered list of setups with enable/save flags and repeat counts | Sequential batch execution | Useful abstraction for wafer-site multi-test recipes. |
| Repeat Measurement with procedures | PDF 91-99; prober pages 479-489 | Start procedure -> before measurement -> measurement -> after measurement -> final/abort | Procedure XML `<Break>` True stops repeat | Prober integration uses this hook model. |
| Remote single execution | PDF 418, 427-438 | `WORK:OPEN` -> `PRES:OPEN`/`APP:SEL` -> set params -> `RUN` -> `*OPC?` -> `RES:FET?` -> `WORK:CLOS` | `ABORt`, error queue via `SYST:ERR?` | Remote control mirrors only a subset of GUI setup/editing. |

## Data Display / Graphing / Analysis

| Concept | Manual location | Inputs | Outputs | MCP implication |
|---|---:|---|---|---|
| Data Display window | PDF 132-160 | Measurement result record, display layers | Graph/list/parameters view | Prefer exporting data rather than automating GUI graph interactions. |
| Display Setup | PDF 144-145 | X/Y1/Y2 variable mapping, scale, range | Graph axis mapping | MCP plotting skill can mirror this schema. |
| Analysis Setup | PDF 145-147 | Marker/cursor/line functions | Analysis parameters | Auto-analysis extraction recipes should use read-out functions. |
| Marker/Cursor/Line tools | PDF 134-144; Ch 5 PDF 390-393 | Marker/cursor positions, tangent/regression/fix lines | Values read by read-out functions | Useful for Vth/gm extraction recipes but requires exact expression syntax. |
| Preview | PDF 161-163 | Graph title/axis/line style | Print-oriented preview | Low priority for MCP unless generating reports. |

## Export / Parser Workflows

| Export path | Manual location | Recommended MCP parser behavior |
|---|---:|---|
| Text File Export | PDF 164-168 | Parse CSV/tab with optional tags and row/column orientation. Preserve Device ID/Count/Flags/Remarks metadata. |
| Excel Export | PDF 169-174 | Prefer list/customized-list worksheets; graph sheet is visual only. |
| XSLT My Format | PDF 497-506 | Use group 4 or group 5 for machine ingest; dispatch rows by first-column labels (`SetupTitle`, `DataName`, `DataValue`, etc.). |
| Remote `RESult:FETch` | PDF 436-438 | Strip SCPI definite-length block header; parse TEXT or XTR according to `RESult:FORMat`. |

## Calibration / Compensation Workflow

| Concept | Manual location | Inputs | Output | MCP implication |
|---|---:|---|---|---|
| Module Self Calibration | PDF 102 | Enable/disable auto-cal; boot/periodic behavior | Calibration state | Expose as instrument maintenance action, not routine recipe step. |
| SMU Zero Cancel | PDF 103; remote PDF 433-435 | SMU identifiers, integration PLC, full-range option | Offset current cancel data | Remote CALibration subsystem can automate this. |
| CMU Calibration | PDF 104-107 | Phase compensation, open/short/load correction, frequency options | Correction data per workspace | Requires physical open/short/load setup; MCP should prompt for fixtures. |
| Error correction theory | PDF 320-321 | Open/short/load correction data | Corrected C-V values | Avoid reimplementing unless measurement raw data and correction constants are available. |

## Term Mapping for MCP/Skills

| EasyEXPERT term | MCP/skill concept | Key refs |
|---|---|---|
| Workspace | Project/session namespace | PDF 26-31, 441-442 |
| My Favorite / Preset Group | Saved setup collection | PDF 44-48, 427-432 |
| Classic Test | Built-in primitive measurement template | Ch 2 PDF 175-248 |
| Application Test | Composite scripted recipe | Ch 3 PDF 249-294 |
| Test Specification | Parameter/resource schema | PDF 253-261 |
| Test Contents | Flow graph/script | PDF 264-271 |
| Command Execution | Low-level FLEX escape hatch | PDF 288-294 |
| Data Display | Result visualization/analysis | PDF 132-160 |
| Export in My Format | XSLT-based structured export | PDF 55, 497-506 |
| Repeat Measurement procedure | External executable hook | PDF 91-99, 479-489 |
