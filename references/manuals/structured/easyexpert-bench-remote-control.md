# EasyEXPERT BENCh / Remote Control Extraction

Source PDF: `../Keysight EasyEXPERT Software.pdf`  
Primary pages: PDF 415-444, printed 6-1 to 6-30. External PC context: PDF 445-465, printed 7-1 to 7-21.

## Coverage Note

This file focuses on whether and how MCP tools should mirror EasyEXPERT behavior. It extracts the remote control operation model, BENCh subsystem, related subsystems, and limitations. It does not replace the B1500A Programming Guide for direct FLEX/SCPI instrument control.

## Architecture and Preconditions

| Concept | Page refs | Extracted detail | MCP implication |
|---|---:|---|---|
| Socket service | PDF 416 | Keysight instruments standardize socket services on port 5025; commands and query responses are newline-terminated. | MCP remote connector must use newline-terminated commands and robust response reads. |
| VISA/SICL | PDF 417 | Interface usable from VISA/SICL library via LAN socket service. | Can be wrapped by generic socket or VISA client. |
| Controllers | PDF 417 | Controller A can control EasyEXPERT on B1500 or another PC; Controller B may run EasyEXPERT and control B1500 via GPIB. | Distinguish EasyEXPERT host from B1500 instrument. |
| Start condition | PDF 418 | To start remote control, workspace selection screen must be displayed by EasyEXPERT. | MCP cannot assume remote availability just because socket connects. |
| Only one connection | PDF 419 | Only one EasyEXPERT can be connected. | Implement session lock / single-client guard. |
| Firewall | PDF 420 | EasyEXPERT must be allowed through Windows Firewall. | Connection failures may be OS/firewall issues, not instrument failures. |

## Operation Flow

Page refs: PDF 418-419 / printed 6-4 to 6-5.

| Phase | Representative command | Meaning | Notes |
|---|---|---|---|
| Open workspace | `:WORK:OPEN` | Open named workspace | Confirm completion with `*OPC?` for open/close operations. |
| Select setup | `:BENC:PRES:SET:SEL` or `:BENC:APP:SEL` | Select preset-group setup or application test definition | Classic setup selection is primarily via My Favorite/Preset Group. |
| Set app numeric parameter | `:BENC:SEL:NUMB` | Set numeric application-test parameter | Only application test parameter edit is exposed by remote API. |
| Set app string/resource parameter | `:BENC:SEL:STR` | Set string parameter, including resource names such as `SMU1:HP` | No direct remote editor for arbitrary classic-test fields. |
| Execute | `:BENC:SEL:RUN` | Start single measurement | Use `*OPC?` to wait for completion. |
| Fetch result | `:RES:FET` | Fetch latest result as block data | Format controlled by `:RES:FORMat TEXT|XTR`. |
| Close workspace | `:WORK:CLOS` | Close active workspace | Confirm with `*OPC?`. |

## Command Syntax Types

Page refs: PDF 421-425.

| Type | Meaning | Parser note |
|---|---|---|
| `NR1`, `NR2`, `NR3`, `NRf` | Numeric formats | Use decimal/exponent parser for `NRf`. |
| `Bool` | `0|OFF|1|ON` | Query returns numeric 0/1 in many cases. |
| `SPD` / `SRD` | String program/query data | Strings are quoted. |
| `CPD` / `CRD` | Character program/query data | Query returns short form. |
| `AARD` | Arbitrary ASCII response | Implied terminator. |
| `Block` | Definite-length arbitrary binary data | Required for `LOAD` and `FETch`; strip `#<n><len>` header. |

## BENCh Subsystem

Page refs: PDF 427-432 / printed 6-13 to 6-18.

| Command | Purpose | Parameters / response | MCP design note |
|---|---|---|---|
| `[:BENCh]:APPlication:CATalog?` | Return all application test definitions regardless of Category selection. | Response: quoted SRD list. | Use for dynamic recipe discovery. |
| `[:BENCh]:APPlication:SELect "name"` | Open application test definition. | `name` is SPD. | Use exact EasyEXPERT app definition names. |
| `[:BENCh]:COUNt count` / `:COUNt?` | Set/query Count field. | `count` NR1. | Count maps to result `IterationIndex`. |
| `[:BENCh]:COUNt:RESet` | Clear Count field. | No parameter. | Useful before repeat/batch automation. |
| `[:BENCh]:LOAD[:SETup] setup` | Load setup information from XTS/XTR data. | `setup` is Block data; if XTR has multiple setup entries, only first loads. | Good bridge from file-based setup library to remote session; requires block encoding. |
| `[:BENCh]:PRESet:CATalog?` | Return catalog of preset groups (My Favorite). | SRD list. | Top-level saved setup groups. |
| `[:BENCh]:PRESet:OPEN "name"` | Open preset group. | `name` SPD. | Required before selecting a saved setup. |
| `[:BENCh]:PRESet:SETup:CATalog?` | Return setups in current preset group. | SRD list. | Use to list runnable saved setups. |
| `[:BENCh]:PRESet:SETup:SELect "name"` | Open setup in current preset group. | `name` SPD. | Primary path for classic test remote execution. |
| `[:BENCh][:SELected]:ABORt` | Abort measurement in progress. | No parameter. | Implement cancellation. |
| `[:BENCh][:SELected]:NAME "name"` / `:NAME?` | Set/query Setup Name field. | SPD/SRD. | For result labeling, not necessarily for saving. |
| `[:BENCh][:SELected]:NUMBer "param", value` | Set/query numeric parameter of opened application test. | Param name SPD, value NRf. | Only works for application-test parameters. |
| `[:BENCh][:SELected]:STRing "param", "value"` | Set/query string parameter of opened application test. | Param/value SPD. | Used for resource strings like `SMU1:HP`. |
| `[:BENCh][:SELected]:RUN[:SINGle]` | Start single measurement. | No parameter; wait with `*OPC?`. | Central execution primitive. |
| `[:BENCh]:TAG "deviceid"` / `:TAG?` | Set/query Device ID field. | SPD/SRD. | Connect to sample/wafer site metadata. |

## Related Subsystems

| Subsystem | Page refs | Commands | MCP implication |
|---|---:|---|---|
| WORKspace | PDF 441-442 | `CATalog?`, `CLOSe`, `OPEN`, `NAME?`, `STATe?` | Session/project boundary. |
| RESult | PDF 436-438 | `FETch?`, `FETch:SIBLings?`, `FORMat TEXT|XTR`, `FORMat:ESCape`, `RECycle` | Result retrieval/deletion; supports application-test sibling results. |
| CALibration | PDF 433-435 | SMU zero cancel `FULLrange`, `MEASure`, `OFF:ALL`, `ON`, `ON:ALL`, `PLC`, `STATe?` | Automatable offset-current cancel workflow. |
| STANDby | PDF 439 | `STATe 0|OFF|1|ON` | Bias/standby control. |
| SYSTem | PDF 440 | `ERRor:NEXT?` | FIFO error queue; empty response `+0,"No error"`. |
| Common | PDF 426 | `*CLS`, `*IDN?`, `*OPC?` | Clear errors, identify host/revision, wait for pending operations. |

## Remote Error Model

Page refs: PDF 443-444.

| Code | Message pattern | Meaning | Recovery idea |
|---:|---|---|---|
| 0 | `No Error` | No remote error | Continue. |
| 101 | `EasyEXPERT Error;Message ID:code / message` | Underlying EasyEXPERT operation error | Look up Ch 11 code and message. |
| 201 | `Remote Control Error;message` | Remote control library / workflow error | Fix selected workspace/setup/test/result state. |

Common 201 messages include: application test definition does not exist, preset group does not exist, parameter not numeric, parameter does not exist, test is being executed, no test result, SMU not found, zero cancel unsupported, working setup empty, working setup not an Application Test, workspace does not exist/already open/not ready/no workspace.

## Should MCP Mirror EasyEXPERT?

| Candidate MCP behavior | Mirror EasyEXPERT? | Rationale |
|---|---|---|
| Workspace/preset/test selection | Yes | Remote API directly exposes these concepts. |
| Application-test parameter setting | Yes | Remote API supports numeric/string parameter edits. |
| Classic-test full setup editing | Partially | Remote API selects saved classic setups but does not expose all GUI fields. Use file setup (`XTS`) or B1500 direct programming for generated setups. |
| Result fetch/export | Yes | Remote result fetch and Ch 1/8 exports are central integration points. |
| Low-level instrument control | Avoid via EasyEXPERT remote unless needed | Use B1500A Programming Guide for direct command implementation; EasyEXPERT Command Execution is an escape hatch inside application tests. |
| Prober movement | Mirror procedure contract first | EasyEXPERT uses external executables and XML responses; direct prober control should be separate. |
