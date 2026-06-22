# Keysight EasyEXPERT Software Manual Index

## Source

| Field | Value |
|---|---|
| PDF path | `Keysight EasyEXPERT Software.pdf` (relative to workspace root) |
| Full path | `/Users/shy/Library/CloudStorage/OneDrive-个人/Files/05 Manuals/Keysight/1500A/Keysight EasyEXPERT Software.pdf` |
| Manual title | Keysight EasyEXPERT Software User's Guide |
| Volumes | **Volume 1** (B1540-90000) and **Volume 2** (B1540-90020) bound into one PDF |
| Edition | Edition 5, December 2020 |
| Copyright | © Keysight Technologies 2013–2020 |
| Publisher | Keysight Technologies Japan K.K., Hachioji, Tokyo |
| Total PDF pages | **700** |
| Page numbering | Each chapter uses `chapter-page` notation (e.g., `1-4`, `2-10`, `A-3`). Title pages are unnumbered. |

### PDF-to-Printed Page Offset Table

Each chapter's printed page can be converted to its PDF page using the offset below.

| Chapter | Offset | Formula | Example |
|---|---|---|---|
| 1 – Main GUI | +16 | PDF = printed\_page + 16 | 1-4 → PDF 20 |
| 2 – Classic Test Definition | +174 | PDF = printed\_page + 174 | 2-4 → PDF 178 |
| 3 – Application Test Definition | +248 | PDF = printed\_page + 248 | 3-5 → PDF 253 |
| 4 – Function Details | +294 | PDF = printed\_page + 294 | 4-3 → PDF 297 |
| 5 – Built-in Programming Tool | +370 | PDF = printed\_page + 370 | 5-3 → PDF 373 |
| 6 – Remote Control Interface | +414 | PDF = printed\_page + 414 | 6-3 → PDF 417 |
| 7 – Using EasyEXPERT on External PC | +444 | PDF = printed\_page + 444 | 7-3 → PDF 447 |
| 8 – Utilities | +466 | PDF = printed\_page + 466 | 8-4 → PDF 470 |
| 9 – Application Library | +506 | PDF = printed\_page + 506 | 9-3 → PDF 509 |
| 10 – If You Have a Problem | +566 | PDF = printed\_page + 566 | 10-3 → PDF 569 |
| 11 – Error Message | +592 | PDF = printed\_page + 592 | 11-3 → PDF 595 |
| A – Appendix | +692 | PDF = printed\_page + 692 | A-3 → PDF 695 |

**Notes:**
- The PDF page marker `-- N of 700 --` appears at the *end* of PDF page N in the extracted text. Content between `-- N --` and `-- N+1 --` belongs to PDF page N+1.
- Volume 1 occupies PDF pages 1–400. Volume 2 occupies PDF pages 401–700.
- Frontmatter for Vol 1 is PDF 1–16; for Vol 2 is PDF 401–414.
- Each chapter has an unnumbered title page followed by a page printed as `N-2` (the "page 1" is the title page).

---

## How To Use This Index

1. **Find a topic** → look up the *Content To Page Map* table below; find the section and note the PDF page range.
2. **Convert printed page** → use the offset table above. For example, to find printed page `4-20`, compute `20 + 294 = PDF 314`.
3. **Load specific pages** → when using the PDF Read tool, convert the PDF page to approximate line numbers using `line ≈ PDF_page × 33.5` (rough average for this OCR'd text).
4. **Keyword search** → use the *Keywords / UI Concepts* column or the *High-Value Lookup Shortcuts* section to locate domain-specific terms.
5. **Cross-volume references** → the manual frequently references sections across volumes (e.g., Chapter 1 references Chapter 9). Both volumes are in this single PDF.

---

## Content To Page Map

### Volume 1 — Frontmatter (PDF 1–16)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Title page (Volume 1) | 1 | — | Title, volume identification | EasyEXPERT, User's Guide, Vol. 1 | |
| Notices & Copyright | 2 | — | Copyright, part number B1540-90000, edition history, warranty, conformity declaration | Edition 5, Dec 2020 | |
| Measurement Resources table | 3 | — | Lists all supported measurement modules (HPSMU, MPSMU, MCSMU, MFCMU, HRSMU, HVSPGU, HVSMU, HVMCU, HCSMU, UHCU, UHVU) and which B1500 series models support each | SMU types, module names, B1500A/B1505A/B1506A/B1507A support matrix | Critical for understanding channel/resource terminology |
| EasyEXPERT overview diagram | 4 | — | Shows EasyEXPERT architecture: on-instrument vs external PC, data server, print server, LAN/GPIB topology | Online/offline modes, LAN, GPIB, data server, clean room/office topology | B1500 cannot be controlled via LAN directly |
| In This Manual (chapter list) | 5 | — | Lists all 11 chapters + Appendix across both volumes, with brief one-line descriptions | Vol 1 = Ch 1–5, Vol 2 = Ch 6–11 + App A | |
| Table of Contents | 7–16 | — | Detailed TOC for Volume 1 chapters 1–5 | All section headings with printed page numbers | |

### Chapter 1 — Main GUI (PDF 17–174, Printed 1-1 to 1-158)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 1 title & overview | 17–19 | 1-1 to 1-3 | Chapter introduction, list of all Ch1 sections, cross-references to other chapters for common tasks (test setup, calibration, data display, switching matrix) | Touch screen operation tip (font size 14 recommended) | Notes about double-precision floating point change in rev A.06.20 |
| Start EasyEXPERT | 20–22 | 1-4 to 1-6 | The Start EasyEXPERT window: launch button, File/Options/User Level menus, Execution Mode dialog, Auto Start, EasyEXPERT Database operations (Backup/Restore/Move) | Start EasyEXPERT, Auto Start, database backup/restore/move, Execution Mode | Database backup is workspace-level; required time depends on DB size |
| Execution Mode dialog box | 21 | 1-5 | Online vs Offline mode selection, VISA interface ID, GPIB address, model selection (B1500A, B1505A, etc.) | Online, Offline, VISA, GPIB address, @ANALYZER function | @ANALYZER returns model string for use in app test definitions |
| User Level Setting | 23–25 | 1-7 to 1-9 | Three user levels (Administrator/Engineer/Operator) with progressively restricted functions; password management, user account configuration per Windows account | Administrator, Engineer, Operator, password protection, function restriction | No password = all users treated as Administrator |
| Workspace Configurator | 26–31 | 1-10 to 1-15 | Workspace creation, selection, management (one or multiple workspaces). Workspace stores test setups, results, calibration data. Each workspace can be opened/closed/selected. | Workspace, My Favorite groups, test record storage | Workspace is the fundamental organizational unit for all EasyEXPERT data |
| Main Screen GUI | 32–48 | 1-16 to 1-32 | Comprehensive reference for the main screen: menu bar (File, Test, Run, Tools, Options, Help), Application Test/Classic Test/Tracer Test/Quick Test tabs, Single/Append/Repeat buttons, Device ID field, My Favorite preset groups, Library area, Channel Definition, Test Parameters area | Main Screen, File menu (Import/Export Test Setup/Result), Run menu (Single/Append/Repeat/Stop), Test modes, My Favorite, preset group, Library, Channel Definition, Device ID, Save Last Data, Running Status, Count | Export formats: xtr (test result), xts (test setup), xpg (preset group). My Favorite groups are preset groups that store test setups. |
| Run Options | 50 | 1-34 | Auto Record and Auto Export settings for measurement data, Multi Display option, configurable auto-record behavior | Auto Record, Auto Export, Multi Display, data record functions | Controls whether measurement results are automatically saved/exported |
| Data Display Manager | 52 | 1-36 | Manage open Data Display windows: list, close, select, multi-display coordination | Data Display Manager | |
| Test Result Editor | 53 | 1-37 | Assign flags or remarks to test record entries | Flag, Remarks, test record annotation | |
| Test Results Data Filter | 53–54 | 1-37 to 1-38 | Filter test results list by date range, test name, device ID, flags | Data Filter, date range, test name filter | |
| Export in My Format | 55 | 1-39 | Custom XSLT-based export of test records; references XSLT filter files | Export in My Format, XSLT filter, custom export | See Ch 8 for XSLT filter file details |
| Test Results Data Folder Export | 55–56 | 1-39 to 1-40 | Export test results as files to a specified folder, with format options | Folder Export, batch export | |
| Test Results Data Auto Export | 57–58 | 1-41 to 1-42 | Automatic export of test results after measurement to text file, with configurable format and destination | Auto Export, text file export, automatic data saving | |
| Test Result Manager | 59 | 1-43 | Manage stored test results: import, delete, recycle, view properties | Test Result Manager, import/delete/recycle results | |
| Preference | 60–64 | 1-44 to 1-48 | Default settings for main screen GUI, Data Display, Test Definition window. Includes graph defaults, list defaults, color schemes, font sizes. | Preference, default settings, graph defaults | Global preference settings affecting all test modes |
| Global Variables | 65–66 | 1-49 to 1-50 | Define variables shared across test definitions within a workspace; numeric/string types; persist across measurements | Global Variables, workspace-scope variables | Useful for wafer-level parameters or shared constants |
| Application Test mode GUI | 67–69 | 1-51 to 1-53 | Application test mode main screen: Library area showing application test definitions organized by categories, Test Parameters area for entering measurement conditions, Extended Setup button | Application Test, Library, test categories (BJT, CMOS, etc.), Test Parameters, Extended Setup | |
| Tracer Test mode GUI | 70–81 | 1-54 to 1-65 | Tracer test mode (real-time I-V curve tracer): channel setup, sweep setup, graph setup tool, option tool, replay traces, select reference/tracking traces, color/thickness/data format settings | Tracer Test, real-time curve tracing, sweep mode, graph setup, replay, reference traces, tracking traces | B1500A DC/Pulse, B1505A DC/Pulse supported |
| Oscilloscope View | 82–87 | 1-66 to 1-71 | Real-time oscilloscope-like waveform display during tracer test: time-domain view of voltage/current waveforms, zoom, cursors, data export | Oscilloscope View, real-time waveform, time-domain display | Only available for supported modules |
| Arithmetic Operation Area | 88 | 1-72 | Define mathematical expressions for real-time calculation during tracer test; expressions use measurement data variables | Arithmetic Operation, real-time math expressions | |
| Quick Test mode GUI | 89–90 | 1-73 to 1-74 | Sequential execution of multiple test setups: test list with execution enable/disable, data save enable/disable, ordering, repeat counts | Quick Test, sequential test execution, test list, batch testing | |
| Repeat Measurement Setup | 91–99 | 1-75 to 1-83 | Repeat measurement dialog: Run Control tab (stop conditions, counter), Procedures tabs (Start/Before/After/Final/Abort procedures as .exe files), Options tab (thermo-trigger with N1265A), response XML format for prober control | Repeat Measurement, stop conditions, procedure hooks (.exe), prober control XML response, thermo-trigger, N1265A temperature control | Key integration point: procedures are external .exe files that return XML responses; enables wafer prober automation |
| Organize Preset Group | 100–101 | 1-84 to 1-85 | Manage preset groups: select, organize, lock/unlock, copy between groups | Organize Preset Group, lock/unlock | |
| Calibration | 102–107 | 1-86 to 1-91 | Three calibration functions: (1) Module Self Calibration (enable/disable auto-cal at boot/periodic), (2) SMU Zero Cancel (offset current measurement per range per module, integration time setting), (3) CMU Calibration (phase compensation, open/short/load correction, advanced frequency options, reference standard values) | Module Self Calibration, SMU Zero Cancel, CMU Calibration, phase compensation, open correction, short correction, load correction, four-terminal pair, offset current, integration time | Phase compensation + open correction are the minimum for CMU. Correction data saved per workspace. Default frequencies: 1k–5MHz (23 points). |
| Configuration — Main Frame | 108–109 | 1-92 to 1-93 | System information: model ID, line frequency (50/60 Hz), EasyEXPERT revision, firmware revision, host ID; main frame diagnosis | Configuration, Main Frame, diagnosis, model ID, firmware revision, line frequency | |
| Configuration — Modules | 109–110 | 1-93 to 1-94 | Module self-test: slot configuration list (slot, module type, name, status, SCUU connection, notes); Start Self Test, Recover Module, Status LED control. Module name table (GNDU+ADC, SMU types with naming convention) | Modules, self-test, slot number, module type, SCUU, module name convention (SMU\<N\>:HP/MP/HR/HC/MC/HV etc.) | Module naming convention is critical for channel identification in MCP tools |
| Configuration — ASU | 111 | 1-95 | Atto Sense and Switch Unit configuration: ASU serial number, ASU mode (Auto/1pA/10pA/100pA range), SMU association | ASU, atto sense, range selection | |
| Configuration — Switching Matrix | 111–113 | 1-95 to 1-97 | Switching matrix (B2200A/B2201A/E5250A) GPIB address, input port assignment to measurement resources, hardware profile, Extended Configuration | Switching Matrix, B2200A, B2201A, E5250A, input ports, GPIB | Not available for B1505A standalone |
| Configuration — SMU/PG Selector | 113 | 1-97 | N1258A/B SMU/PG Selector: enables shared use of SPGU and SMU through a switching unit | SMU/PG Selector, N1258A, shared SPGU/SMU | |
| Configuration — Module Selector | 114 | 1-98 | N1261A Module Selector: assigns modules to connectors, enables flexible module-to-DUT routing | Module Selector, N1261A, module-to-connector mapping | |
| Configuration — Dual HCSMU | 115 | 1-99 | Combines two HCSMU modules for dual high-current source operation | Dual HCSMU, high current combination | |
| Configuration — UHC Expander/Fixture | 116–118 | 1-100 to 1-102 | N1265A Ultra High Current Expander/Fixture: HCSMU assignment, current range (500A standard / 1500A option), fixture selection, bias-T options | UHC, N1265A, ultra high current, 500A/1500A, fixture, bias-T | |
| Configuration — HVSMU Current Expander | 119–120 | 1-103 to 1-104 | N1266A HVSMU Current Expander: combines HVSMU with MCSMU for high-voltage medium-current capability | HVSMU Current Expander, N1266A, HVMCU | |
| Configuration — UHV Expander | 121 | 1-105 | N1268A Ultra High Voltage Expander: extends voltage range for ultra-high-voltage measurements | UHV Expander, N1268A, ultra high voltage | |
| Configuration — Device Capacitance Selector | 122–123 | 1-106 to 1-107 | For B1505A/B1506A/B1507A: device capacitance selector setup, MFCMU/HVSMU/SMU input assignment, calibration (open/short correction), auto detection | Device Capacitance Selector, B1505A/B1506A, N1272A, N1274A, open/short correction | |
| Configuration — Gate Charge Adapter | 124–125 | 1-108 to 1-109 | For B1505A/B1506A: gate charge measurement adapter setup (N1259A/N1265A/N1274A/N1275A), MCSMU gate/HVSMU/UHCU input assignment, open/short calibration | Gate Charge, Qg measurement, N1259A, N1274A, N1275A | |
| Configuration — SMU Output Setting Limits | 126 | 1-110 | B1505A only: upper limits for voltage (200V–10kV) and current (1A–1500A) output and compliance values | SMU Output Setting Limits, safety limits | Safety feature for high-power measurements |
| Configuration — Event Log | 126 | 1-110 | View event log: date/time, message, process ID, user, host | Event Log | |
| Configuration — Extended Configuration | 126–128 | 1-110 to 1-112 | Switching matrix hardware profile, CMU compensation modes (No Compensation, Select path, User Compensation Data File), cable length settings for E5250A | Extended Configuration, CMU Compensation, hardware profile, cable compensation | |
| Switching Matrix Operation Panel | 129–130 | 1-113 to 1-114 | Manual switching matrix control: input-output cross-point matrix, apply/read switch setup, open all, preset list management, export to My Favorite | Switching Matrix Operation Panel, cross-point, switch setup preset | Not available for B1505A |
| Standby Channel Definition | 131 | 1-115 | Define standby channels that maintain output between measurements; select channels and standby mode | Standby Channel, standby mode, bias hold between measurements | |
| Data Display — overview | 132–133 | 1-116 to 1-117 | Introduces Data Display window: opened by measurement or Data Display button; shows X-Y graph, list data, parameters; up to 50 display layers (20 if ≤1GB RAM) | Data Display, display layers, X-Y graph, list display, parameters | Key data analysis and visualization interface |
| Data Display GUI | 134–144 | 1-118 to 1-128 | Comprehensive Data Display GUI reference: Setup Name, X-Y Graph Plot, Parameters, List Display, pin/close layers, File menu (Close/Save Image/Print/Export to Excel), Edit menu (Copy Image/List/Parameters, Setup/Analysis/Preference), View menu (Graph/List/Parameters/Legend/Line Info/Append), Zoom menu (Auto Scale/Run Time Auto Scale), Axis menu (direction/scale/polarity), Marker menu (enable/interpolation/skip/go to max-min), Cursor menu, Line menu (normal/gradient/tangent/regression/fix with X/Y intercepts), Text menu (up to 20 texts), Pointer menu (up to 30 pointers), Window menu (tile/stack/overlay) | Graph, List, Parameters, Save Image (BMP/EMF/GIF/PNG), Print, Export to Excel, Copy Image/List/Parameters as CSV, Auto Scale, Run Time Auto Scale, Marker, Cursor, Line (normal/gradient/tangent/regression/fix), Text, Pointer, tile/stack/overlay windows | Export to Excel supports Excel 2003/2007/2010; graph image formats: BMP, EMF, GIF, PNG |
| Display Setup | 144–145 | 1-128 to 1-129 | Configure graph axis assignments: X/Y1/Y2 variable selection, axis name, scale (linear/log), range, data variable mapping | Display Setup, axis assignment, X/Y1/Y2, scale type, variable mapping | |
| Analysis Setup | 145–147 | 1-129 to 1-131 | Marker-based and line-based analysis: define analysis functions using built-in read-out functions (marker position, cursor, line intercepts/gradients), auto-analysis expressions | Analysis Setup, analysis functions, read-out functions, marker analysis, line analysis, auto-analysis | |
| Graph Preference | 147–149 | 1-131 to 1-133 | Graph display preferences: grid, color scheme, line style, marker style, trace display order, legend format | Graph Preference, grid, colors, line style | |
| List Display Preference | 150 | 1-134 | List display settings: column order, number format, decimal places | List Display Preference | |
| Tool Bar | 150–152 | 1-134 to 1-136 | Toolbar buttons reference: shortcut buttons for all Data Display functions (graph/list/parameters visibility, zoom, marker, cursor, lines, text, pointers, auto-scale, axis swap) | Toolbar, shortcut buttons | |
| Data Status | 153 | 1-137 | Data status indicators in the Data Display | Data Status | |
| Setup Summary | 153 | 1-137 | Displays summary of test setup used for the current measurement data | Setup Summary | |
| Miscellaneous Operations | 154–160 | 1-138 to 1-144 | Additional Data Display operations: drag-drop scaling, mouse wheel zoom, right-click context menus, keyboard shortcuts, graph scale change operations, multi-layer data overlay | Drag-drop, mouse wheel zoom, right-click menus, keyboard shortcuts, multi-layer overlay | |
| Preview | 161–163 | 1-145 to 1-147 | Preview window for test result data export: graph and list preview before export, preview settings | Preview, export preview | |
| Preview Settings | 163 | 1-147 | Configure preview display options | Preview Settings | |
| Text File Export Settings | 164–168 | 1-148 to 1-152 | Detailed text file export configuration: measurement data section (CSV/tab-delimited, by-row/by-column orientation), identification section (test time, device ID, count, flags, remarks), setup data section (test parameters, DUT parameters, analysis setup). Defines all record items and tag information (Tables 1-14 through 1-18). Save Type actions: Save with measurement data / Do not save / Save as separate file. Miscellaneous tab: delimiter (CSV/Text/Formatted Text), quotation (Single/Double/None). | Text File Export, CSV, tab-delimited, measurement data, identification data, setup data, tag information, Auto Export, record items, RecordTime, TestTarget, IterationIndex, Save Type, delimiter, By Row/By Column orientation | Critical for understanding export data format. Tag information labels: TestParameter, DutParameter, AnalysisSetup. |
| Excel Data Export Settings | 169–174 | 1-153 to 1-158 | Excel export configuration: Measurement Data tab (record items: tag info, data names, units, size, data values with segment selection), Identification tab (same fields as text export), Setup data section (TestParameter, DutParameter, AnalysisSetup), Worksheet tab (Target Sheet: List/Customized List for Auto Export, List/Graph for Manual Export). Tables 1-19 through 1-24. | Excel Data Export, Microsoft Excel, List worksheet, Graph worksheet, Customized List, Auto Export on Measurement, Manual Export on Data Display, Measurement Data tab, Identification tab, Worksheet tab | Supports Excel 2003/2007/2010; opens Results > Export Options > Excel Export dialog |

### Chapter 2 — Classic Test Definition (PDF 175–248, Printed 2-1 to 2-74)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 2 title & overview | 175–177 | 2-1 to 2-3 | Lists all classic test types and setup windows; cross-references to Ch 1 and Ch 4 | Classic Test, test modes overview | GNDU rule: Mode=COMMON, Function=CONST, don't use I Name |
| I/V Sweep | 178–182 | 2-4 to 2-8 | I/V sweep test setup: Setup Name, Channel Setup (select SMUs, set Mode V/I/COMMON, Function VAR1/VAR2/VAR1'/CONST), Measurement Setup (sweep direction/linear-log/start/stop/step/compliance/hold/delay, VAR2 and VAR1' parameters) | I/V Sweep, Channel Setup, Measurement Setup, VAR1, VAR2, VAR1', Mode (V/I/COMMON), Function (CONST), sweep direction, compliance, hold time, delay time | Core measurement setup; referenced by Ch 4 for functional details |
| Multi Channel I/V Sweep | 183–187 | 2-9 to 2-13 | Multiple simultaneous sweeps: up to 8 VAR1 channels, each with independent start/stop/step, common compliance. Channel Setup and Measurement Setup specific to multi-channel. | Multi Channel I/V Sweep, multiple VAR1, simultaneous sweep | |
| I/V List Sweep | 188–195 | 2-14 to 2-21 | Sweep with user-defined voltage/current list: Channel Setup, Measurement Setup, Define vector data dialog (create/edit/import/export sweep point lists) | I/V List Sweep, vector data, custom sweep points, import/export list | Define vector data dialog is shared with application test parameters |
| I/V-t Sampling | 196–200 | 2-22 to 2-26 | Time-domain sampling measurement: Channel Setup (source channels, monitor channels), Measurement Setup (linear/log sampling, interval, number of samples, hold time, base hold time, output sequence) | I/V-t Sampling, time-domain, sampling interval, linear/log sampling, hold time, base hold time, output sequence (SEQUENTIAL/SIMULTANEOUS) | Interval < 2ms requires high-speed ADC for all channels |
| C-V Sweep | 201–204 | 2-27 to 2-30 | Capacitance-voltage sweep: Channel Setup (CMU + DC bias SMU), Measurement Setup (frequency, AC level, impedance model Cp-G/Cs-Rs/Cp-D/Cs-D/Z-θ/Y-θ/R-X, DC bias sweep) | C-V Sweep, MFCMU, capacitance measurement, impedance model, Cp-G, Cs-Rs, frequency, AC level, DC bias | Requires MFCMU module |
| SPGU Pulse Setup Window | 205 | 2-31 | Pulse generator setup for SPGU: pulse mode, base/peak voltage, width, period, leading/trailing edge, count | SPGU Pulse Setup, pulse parameters, base/peak voltage, width, period | |
| Switching Matrix Control | 207 | 2-33 | Classic test switching matrix setup: define switch connections per measurement channel | Switching Matrix Control, per-test switch setup | |
| Direct Control | 209–216 | 2-35 to 2-42 | Low-level instrument control: Channel Setup, Measurement Setup, Advanced Setup (wait time, filter, series resistor, after-measurement output), Command Setup (send/receive GPIB commands to B1500 or external instruments) | Direct Control, GPIB commands, Advanced Setup, raw instrument control | For advanced users needing commands not covered by other test modes |
| compenReZ / compenImZ / compenReY / compenImY | 217–220 | 2-43 to 2-46 | Compensation data variables: real/imaginary parts of impedance (Z) and admittance (Y) for CMU error correction | compenReZ, compenImZ, compenReY, compenImY, compensation variables | Used in Direct Control for CMU compensation |
| Function Setup | 221 | 2-47 | Define user functions (mathematical expressions) applied to measurement data; expressions use built-in functions and measurement variables | Function Setup, user functions, mathematical expressions | Functions are evaluated after each measurement point |
| Auto Analysis Setup | 222–224 | 2-48 to 2-50 | Define automatic analysis expressions executed after measurement: analysis functions using marker, cursor, line read-out functions; parameter extraction (e.g., Vth, gm_max) | Auto Analysis, parameter extraction, Vth, gm_max, automatic post-measurement analysis | |
| Display Setup | 225–226 | 2-51 to 2-52 | Configure graph axes and data mapping for classic test result display: X/Y axis variable assignment, scale, name | Display Setup (Classic Test), graph axis configuration | |
| SMU Range Setup Window | 227–228 | 2-53 to 2-54 | Set SMU measurement/output ranging mode: Auto, Limited Auto, Fixed; range selection per channel | SMU Range Setup, auto ranging, limited auto, fixed range | |
| ADC and Integration Time Setup Window | 229–230 | 2-55 to 2-56 | Configure A/D converter settings: High Speed ADC (HS-ADC) or High Resolution ADC (HR-ADC), integration time mode (AUTO/MANUAL/PLC), factor | ADC, Integration Time, HS-ADC, HR-ADC, AUTO/MANUAL/PLC mode, factor | |
| Pulse Setup Window | 231–232 | 2-57 to 2-58 | SMU pulse output configuration: period, width, base value, pulse timing diagram | Pulse Setup, SMU pulse, period, width, base value | Only one pulse SMU per test |
| Advanced Setup Window | 233–234 | 2-59 to 2-60 | Advanced I/V sweep settings: wait time control (state/factor), after-measurement settings (output value), channel settings (filter, series resistor) | Advanced Setup, wait time control, after-measurement output, filter, series resistor | |
| Range Setup Window | 235 | 2-61 | CMU measurement range selection | Range Setup, CMU range | |
| Advanced Setup Window for C-V Sweep | 237 | 2-63 | C-V specific advanced settings: integration time for CMU, delay time, oscillator level | C-V Advanced Setup, CMU integration time | |
| SPGU Control | 238–239 | 2-65 to 2-66 | SPGU control classic test: pulse generator channel setup, trigger control, advanced setup | SPGU Control, pulse generator classic test | |
| Load Z Setup Window | 240 | 2-67 | Impedance load setup for SPGU output: load impedance value | Load Z, SPGU load impedance | |
| Pulse Switch Setup Window | 241 | 2-68 | SMU/PG selector pulse switch configuration | Pulse Switch, SMU/PG selector | |
| SPGU ALWG Setup Window | 242 | 2-69 | Arbitrary Linear Waveform Generator setup: waveform sequence definition | SPGU ALWG, arbitrary waveform | |
| Define ALWG Waveform Window | 243–248 | 2-70 to 2-74 | Waveform definition editor: sequence table (repeat count, pattern assignment per channel), Waveform Pattern Editor (graphic/tabular mode for creating voltage/time patterns), pattern import/export | ALWG Waveform, pattern editor, graphic/tabular mode, waveform pattern, import/export pattern | |

### Chapter 3 — Application Test Definition (PDF 249–294, Printed 3-1 to 3-46)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 3 title & overview | 249–250 | 3-1 to 3-2 | Overview of application test definition framework: Test Specification + Test Contents + Test Output structure | Application Test Definition | |
| Test Definition Window | 251–252 | 3-3 to 3-4 | Main window for creating/editing application test definitions: three-tab structure (Test Specification, Test Contents, Test Output), element diagram showing variable flow | Test Definition Window, three-tab structure | Core application test authoring interface |
| Test Specification | 253–261 | 3-5 to 3-13 | Define test metadata and parameters: category, test name, icon, description; Device Parameters (numeric, name/default/description); Test Parameters (Numeric/Module/String/Vector/ALWaveform types, layout position, Extended Setup, typical values, resource type selection with full SMU type list, dimension definition, symbols). Resource types include: SMU, HPSMU, HCSMU, DHCSMU, HVSMU, HRSMU, MPSMU, MCSMU, HRSMU/ASU, GNDU, SPGU, HVSPGU, WGFMU, RSWGFMU, MFCMU, MFCMU/SCUU, SWM IN, SWM AUX IN, SWM SMU IN, UHCU500, UHCU1500, UHVU, HVMCU, NONE. | Test Specification, device parameters, test parameters, parameter types (Numeric/Module/String/Vector/ALWaveform), resource type, typical values, parameter layout, Symbols (numeric-symbol assignment), Assign Output Channels (for ALWaveform) | Module type parameter selects specific measurement resources; NONE adds dummy NONx:NC channels (ignored during measurement, error if assigned to VAR1) |
| — Define Layout (sub-section of Test Specification) | 258–261 | 3-10 to 3-13 | Visual layout editor for test parameter entry fields on the main screen: grid-based positioning with X/Y/Width/TabIndex controls, Align/Distribute/Centralize/Tab Order menus, Properties window (DrawGrid, GridSize, SnapToGrid, Size, Align, Width, X, Y). Select/Move entry fields by drag-drop or property editing. | Define Layout, parameter layout editor, grid, TabIndex, Properties, Align/Distribute/Centralize menus | Layout defines how test parameters appear on the Application Test main screen |
| Test Output | 262–263 | 3-14 to 3-15 | Define analysis parameters (output variables) and display setup for application test results; Analysis Parameter Definition sub-section for naming output variables | Test Output, analysis parameters, output variables, Analysis Parameter Definition | |
| Test Contents | 264–271 | 3-16 to 3-23 | Core test flow programming: visual script editor with program components (Application Test, Classic Test, My Favorite, Analysis, Assign, Display Data, GPIB I/O, Message, Data Store, Command Execution); flow control statements (BLOCK, IF, FOR, LOOP, EXIT); variable assignment; component execution order | Test Contents, script editor, program components, flow control, BLOCK, IF/ELSE IF/ELSE, FOR/NEXT, LOOP/EXIT LOOP | This is the scripting engine for complex multi-step measurements |
| — Defining/Editing Test Contents | 265–268 | 3-17 to 3-20 | Inserting/editing/deleting program components, setting execution flow, connecting components | Defining/Editing Test Contents | |
| — Debugging Test Contents | 269 | 3-21 | Debug tools: step execution, breakpoints, variable inspection during test development | Debug, step execution, breakpoints | |
| — Variable Inspector | 270 | 3-22 | View and inspect variable values during test execution | Variable Inspector | |
| — External Variable Setup | 271 | 3-23 | Pass variables between test definitions; external variable import/export | External Variable Setup | |
| Local Variable Definition | 272–273 | 3-24 to 3-25 | Define local variables within an application test: variable name, type, initial value | Local Variable Definition | |
| Program Component | 274–275 | 3-26 to 3-27 | Reference for each program component type that can be inserted into Test Contents | Program Component | |
| Auto Analysis | 275–277 | 3-27 to 3-29 | Automatic analysis component in test flow: execute analysis expressions after measurement sub-step | Auto Analysis (application test component) | |
| Data Display Control | 278–279 | 3-30 to 3-31 | Control Data Display window from within test flow: open/close/clear display layers | Data Display Control | |
| Display Data Setup | 279–280 | 3-31 to 3-32 | Configure which data variables appear in the Data Display for application test | Display Data Setup | |
| GPIB I/O | 281–285 | 3-33 to 3-37 | GPIB instrument control from test flow: send commands, read responses, address configuration; enables control of external instruments (LCR meter, pulse generator, DVM, prober) | GPIB I/O, external instrument control, LCR meter, pulse generator, DVM | |
| Message | 286 | 3-38 | Display user messages during test execution; supports OK/Cancel response | Message, user prompt during test | |
| Data Store Control | 287 | 3-39 | Control data storage behavior: enable/disable recording, specify data variables to store | Data Store Control | |
| Command Execution | 288–294 | 3-40 to 3-46 | Execute B1500 FLEX commands directly from test flow: command parameters (numeric/vector/string input, numeric/vector/string output), format field definition, setup examples. Sub-sections: Using Command Execution (3-42), Command Parameters, Defining Input/Output Parameters, Defining Format Field (3-45), Setup Example (3-46). | Command Execution, FLEX commands, direct B1500 control, parameter types, format field | Advanced: allows any B1500 command from within application test |

### Chapter 4 — Function Details (PDF 295–370, Printed 4-1 to 4-76)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 4 title & overview | 295–296 | 4-1 to 4-2 | Overview of all function details covered in this chapter | Function Details | |
| I/V Sweep Measurement | 297–306 | 4-3 to 4-12 | Detailed functional explanation of I/V sweep: available modules (SMU+SPGU), output range auto-selection, Basic Sweep (VAR1 single/double, linear/log staircase, setup parameters), Subordinate Sweep (VAR2 secondary sweep, only linear single), Synchronous Sweep (VAR1' offset+ratio, tracks VAR1), Pulsed Sweep (pulse output with single pulse SMU) | I/V Sweep function, VAR1/VAR2/VAR1', single/double sweep, linear/log staircase, synchronous sweep (offset/ratio), pulsed sweep, output range | Sweep steps: 1–10001 (or 1–2500 for B2900). Compliance and power compliance settings. |
| Multi Channel I/V Sweep Measurement | 307 | 4-13 | Multiple channels sweeping simultaneously: all channels use VAR1, synchronized step points | Multi Channel I/V Sweep function | |
| I/V-t Sampling Measurement | 308–313 | 4-14 to 4-19 | Detailed sampling measurement function: operation summary with timing diagram, source output sequence (SEQUENTIAL/SIMULTANEOUS), hold time, base hold time, interval, number of samples, linear/log sampling modes, time data and index, source output sequence and time origin, sampling completion behavior | I/V-t Sampling function, timing diagram, sampling interval, linear/log modes (LOG10/25/50/100/250/500), time origin, base value, source value | For interval < 2ms: linear only, HS-ADC required, parallel measurement. Log sampling holds only data plottable at equal log spacing. |
| C-V Sweep Measurement | 314–319 | 4-20 to 4-25 | C-V sweep function details: available modules (MFCMU + DC bias SMU), setup parameters (frequency 1kHz–5MHz, AC level 10–250mV, impedance measurement models Cp-G/Cs-Rs/Cp-D/Cs-D/Z-θ/Y-θ/R-X), four-terminal pair configuration, DC bias sweep setup | C-V Sweep function, MFCMU, frequency range, AC level, impedance models, four-terminal pair | |
| Error Correction (C-V) | 320–321 | 4-26 to 4-27 | CMU error correction theory: open/short/load correction formulas, phase compensation, correction data interpolation | Error Correction, open/short/load correction, phase compensation, correction formulas | |
| SPGU Module | 322–331 | 4-28 to 4-37 | SPGU functional details: PG Operation Mode (pulse output with timing diagrams, output impedance, trigger modes, multi-channel synchronization) and ALWG Operation Mode (arbitrary linear waveform sequences) | SPGU, PG mode, ALWG mode, pulse timing, trigger modes, multi-channel sync, arbitrary waveform | |
| Sweep Abort Function | 332 | 4-38 | What happens when sweep is aborted: partial data retained, output zeroed | Sweep Abort, partial data | |
| Standby Function | 333–335 | 4-39 to 4-41 | Standby channels maintain output between measurements: standby channel definition, standby state behavior, output sequence, how to use | Standby Function, inter-measurement bias, standby channels, standby state | |
| Bias Hold Function | 336–337 | 4-42 to 4-43 | Hold bias between sweep measurements: keeps last output value as bias for next measurement | Bias Hold, inter-sweep bias hold | |
| Current Offset Cancel | 338–339 | 4-44 to 4-45 | Zero cancel for low-current measurements: offset measurement per range, automatic subtraction | Current Offset Cancel, zero cancel, low-current accuracy | |
| SMU CMU Unify Unit (SCUU) | 340–341 | 4-46 to 4-47 | SCUU function: combines SMU and CMU signal paths through single connector; enables I/V and C-V on same DUT terminal without reconnection | SCUU, SMU CMU Unify Unit, combined I/V and C-V path | |
| Atto Sense and Switch Unit (ASU) | 342–343 | 4-48 to 4-49 | ASU function: extends SMU current range down to 1pA; automatic range switching; dedicated SMU pairing | ASU, atto-ampere sensing, 1pA range, ultra-low current | |
| SMU/PG Selector | 344 | 4-50 | N1258A/B selector function: switches between SMU and SPGU output to same DUT terminal | SMU/PG Selector function | |
| Module Selector | 345 | 4-51 | N1261A module selector function: flexible module-to-output routing | Module Selector function | |
| Ultra High Current Expander/Fixture | 346–347 | 4-52 to 4-53 | N1265A UHC function: extends current capability to 500A/1500A; fixture modes; bias-T for C-V during high-current | UHC, N1265A, 500A/1500A, bias-T | |
| HVSMU Current Expander | 348 | 4-54 | N1266A function: combines HVSMU + MCSMU for high-voltage medium-current measurements (HVMCU) | HVSMU Current Expander, N1266A, HVMCU | |
| Ultra High Voltage Expander | 349 | 4-55 | N1268A function: extends voltage capability for ultra-high-voltage measurements (UHVU) | UHV, N1268A, UHVU | |
| SMU Ranging Mode | 350–353 | 4-56 to 4-59 | Detailed ranging mode explanation: Auto Ranging (automatic range selection), Limited Auto Ranging (constrained auto), Fixed Range (user-specified), Compliance Range, Enhanced Auto Ranging for current measurement | SMU Ranging, Auto/Limited Auto/Fixed/Compliance Range, Enhanced Auto Ranging | |
| SMU Compliance | 354–356 | 4-60 to 4-62 | Compliance function: polarity and output area diagram, power compliance, how to set compliance for voltage/current source modes | SMU Compliance, polarity, output area, power compliance | |
| SMU Pulse | 357–358 | 4-63 to 4-64 | SMU pulse output details: pulse setup parameters (period, width, base, peak), timing diagram, pulse measurement timing | SMU Pulse, pulse parameters, timing diagram | |
| SMU Measurement Time | 359–365 | 4-66 to 4-72 | Integration time details: HS-ADC (AUTO mode with averaging samples, MANUAL mode), HR-ADC (AUTO with averaging, PLC mode with power-line-cycle integration); overhead time; source output time; wait time control (state/factor); multiple measurement channels timing | Integration Time, HS-ADC, HR-ADC, AUTO/MANUAL/PLC, averaging samples, overhead time, wait time, source output time | Critical for measurement optimization. Wait time factor: 0–100 multiplicative factor on internal wait time. |
| SMU Filter | 366 | 4-72 | Output filter function: reduces output noise at cost of slower settling; ON/OFF setting | SMU Filter, output noise, settling time | |
| SMU Series Resistor | 367 | 4-73 | Built-in series resistor: protects DUT from damage during breakdown measurements; available resistor values | SMU Series Resistor, DUT protection, breakdown measurement | |
| Interlock Function | 368 | 4-74 | Safety interlock: prevents high-voltage output when interlock connector is open | Interlock, safety, high-voltage protection | |
| Auto Power Off Function | 369–370 | 4-75 to 4-76 | Automatic power-off for unattended operation: configurable timer | Auto Power Off | |

### Chapter 5 — Built-in Programming Tool (PDF 371–399, Printed 5-1 to 5-28)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 5 title & overview | 371–372 | 5-1 to 5-2 | Overview of built-in programming capabilities used in Classic Test functions and Application Test definitions | Built-in Programming Tool | |
| Variables and Expressions | 373–377 | 5-3 to 5-7 | Variable naming rules (A-Z, a-z, _, 0-9, @; case sensitive), expression syntax (constants q/k/e, literals with SI prefix symbols, operators +/-/*/÷/^/mod, comparison operators, logical NOT/AND/OR/XOR), string expressions, vector expressions | Variables, expressions, constants (q, k, ε), SI prefixes, operators, string/vector types | Variable names case-sensitive; @-prefix variables are system variables |
| Built-in Functions | 378–389 | 5-8 to 5-19 | Complete reference of built-in mathematical functions: ABS, ATN, COS, EXP, INT, LGT, LN, LOG, MAX, MIN, PI, RND, SGN, SIN, SQR, TAN, and more; string functions (ASC, CHR, LEN, LEFT, RIGHT, MID, STR, VAL, FORMAT); vector functions (DIM, REDIM, GETDATA, SETDATA); system functions (@ANALYZER, @ERROR, @CHANNEL, etc.) | Built-in functions, math functions, string functions, vector functions, system variables (@ANALYZER, @ERROR, @CHANNEL) | |
| Read-out Functions | 390–393 | 5-20 to 5-23 | Functions for reading analysis tool values: marker functions (MARKER_X, MARKER_Y, etc.), cursor functions (CURSOR_X, CURSOR_Y), line functions (LINE_GRADIENT, LINE_XINTERCEPT, LINE_YINTERCEPT), two-line display functions | Read-out functions, MARKER_X/Y, CURSOR_X/Y, LINE_GRADIENT, LINE_XINTERCEPT, LINE_YINTERCEPT | Used in Auto Analysis and Function Setup for parameter extraction |
| Script Program Statements | 394–398 | 5-24 to 5-28 | Flow control statements for Application Test: ASSIGN, BLOCK/END BLOCK, COMMENT, END, ERROR, FOR/NEXT/EXIT FOR, IF/ELSE IF/ELSE/END IF, LOOP/END LOOP/EXIT LOOP. Includes two complete application test examples (Vth_gmMax and NandFlash IV-Write-IV) with line-by-line explanations. | Script statements, ASSIGN, BLOCK, FOR/NEXT, IF/ELSE, LOOP, program examples, Vth_gmMax, NandFlash IV-Write-IV | Examples show realistic multi-step measurement flows with getNumericData/getVectorData |

### Volume 2 — Frontmatter (PDF 401–414)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Title page (Volume 2) | 401 | — | Title, volume identification | Vol. 2, B1540-90020 | |
| Notices & Copyright | 402 | — | Same as Vol 1, part number B1540-90020 | | |
| Measurement Resources table | 405 | — | Same resource table as Vol 1 | | |
| In This Manual (chapter list) | 407 | — | Lists chapters 6–11 + Appendix A | | |
| Table of Contents (Vol 2) | 409–414 | — | Detailed TOC for chapters 6–11 + Appendix | | |

### Chapter 6 — Remote Control Interface (PDF 415–444, Printed 6-1 to 6-30)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 6 title & overview | 415–416 | 6-1 to 6-2 | Overview of EasyEXPERT remote control interface via LAN socket (port 5025); VISA/SICL library usage; sample program location at `<program folder>\Agilent\B1500\EasyEXPERT\Samples\Remote Control` | Remote Control, LAN socket, port 5025, VISA, SICL, sample programs | Socket services on port 5025; all commands terminated with newline |
| Introduction | 417 | 6-3 | Remote control use cases: control EasyEXPERT from external computer (Controller A) via LAN, control from B1500 itself, control EasyEXPERT on Controller B from Controller A or from itself. Architecture diagram (Figure 6-1). | Remote architecture, Controller A/B, LAN control | |
| Supported Operations | 418 | 6-4 | Subsystem command overview with Figure 6-2 operation flow diagram: open workspace → set test setup → execute measurement → get results → close workspace. Lists: WORKspace, BENCh, RESult, CALibration, STANDby, SYSTem subsystems. | Subsystem commands, operation flow, :WORK:OPEN, :BENC:PRES:SET:SEL, :BENC:APP:SEL, :BENC:SEL:RUN, :RES:FET, :WORK:CLOS | To start remote control, workspace selection screen must be displayed by EasyEXPERT |
| Preparation for Communication | 419 | 6-5 | Prerequisites: confirm Windows firewall, prepare VISA/SICL library (IO Libraries Suite), connect via LAN, establish socket connection. Only one EasyEXPERT can be connected. Use Connection Expert to find and connect. | Preparation, VISA/SICL, IO Libraries Suite, Connection Expert, LAN connection | Critical setup step for MCP remote-control tools; only ONE concurrent socket connection allowed |
| Checking Windows Firewall Setting | 420 | 6-6 | Step-by-step procedure to allow EasyEXPERT through Windows Firewall: Control Panel > System and Security > Allow a program through Windows Firewall; add EasyEXPERT.exe if not listed. | Windows Firewall, allow program, EasyEXPERT.exe path | Required for LAN remote control to function |
| Notational Convention and Command Summary | 421–425 | 6-7 to 6-11 | SCPI-like command syntax: notational conventions (Table 6-1: uppercase=required, lowercase=optional, vertical bar=alternatives, square brackets=optional). Data types: NR1/NR2/NR3/NRf/Bool/SPD/CPD/SRD/CRD/AARD/Block. Command summary table (Table 6-2) listing all commands with descriptions. | Command notation, SCPI-like syntax, data types (NRf, SPD, SRD, CRD, AARD, Block), Table 6-1, Table 6-2 | |
| Common Commands (*CLS, *IDN?, *OPC?) | 426 | 6-12 | Standard IEEE 488.2 common commands: *CLS (clear status), *IDN? (identification query), *OPC? (operation complete query) | *CLS, *IDN?, *OPC? | |
| BENCh Subsystem | 427–432 | 6-13 to 6-18 | Test execution commands: APPlication:CATalog?/SELect, COUNt/COUNt:RESet, LOAD[:SETup] (Block data), PRESet:CATalog?/OPEN/NAME?/SETup:CATalog?/SETup:SELect, SELected:ABORt/NAME/NUMBer/RUN[:SINGle]/STRing, TAG | BENCh subsystem, APPlication, PRESet, RUN, ABORt, LOAD (Block data), TAG, COUNt | Primary command set for automating measurements; LOAD accepts XTS/XTR block data |
| CALibration Subsystem | 433–435 | 6-19 to 6-21 | Offset current cancel commands: :CALibration[:SMU]:ZERO:FULLrange, ZERO:MEASure[:CURRent], ZERO:OFF:ALL, ZERO[:ON], ZERO[:ON]:ALL, ZERO:PLC, ZERO:STATe? | CALibration, ZERO cancel, offset current, FULLrange, PLC | |
| RESult Subsystem | 436–438 | 6-22 to 6-24 | Result retrieval commands: :RESult:FETch[:LATest]?, FETch[:LATest]:SIBLings?, FORMat (CSV/XML/XMLSS), FORMat:ESCape, RECycle:ALL, RECycle[:LATest] | RESult, FETch, FORMat (CSV/XML/XMLSS), RECycle, ESCape | Key for automated data retrieval; format determines response structure |
| STANDby Subsystem | 439 | 6-25 | Standby state control: :STANDby:STATe ON/OFF | STANDby, standby remote control | |
| SYSTem Subsystem | 440 | 6-26 | Error checking: :SYSTem:ERRor[:NEXT]? | SYSTem, ERRor query | |
| WORKspace Subsystem | 441–442 | 6-27 to 6-28 | Workspace management commands: :WORKspace:CATalog?, CLOSe, OPEN "name", [:SELected]:NAME?, STATe? | WORKspace, open/close workspace, CATalog, STATe | |
| Error Messages (Ch 6) | 443–444 | 6-29 to 6-30 | Remote control error codes: 0 (No Error), 101 (EasyEXPERT Error), 201 (Remote Control Error with detailed message list) | Remote error codes, error 0/101/201 | |

### Chapter 7 — Using EasyEXPERT on External PC (PDF 445–465, Printed 7-1 to 7-21)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 7 title & overview | 445–446 | 7-1 to 7-2 | Overview of running EasyEXPERT on external PC | External PC, offline/online operation | |
| System Requirements | 447–449 | 7-3 to 7-5 | Minimum requirements: Windows Vista/7/8.1/10, .NET Framework 3.5 SP1, IO Libraries Suite 16.2+, GPIB interface, XGA display, 2GB RAM, 1GB C: + 30GB storage | System Requirements, .NET Framework, IO Libraries, GPIB interface | |
| To Install / Before Starting / To Start | 450–452 | 7-6 to 7-8 | Installation procedure, pre-start checklist, launching EasyEXPERT on PC | Installation, launch procedure | |
| To Change Execution Mode | 453 | 7-9 | Switch between online/offline modes, GPIB settings | Execution Mode change | |
| Using 4155B/4156B/4155C/4156C | 454–456 | 7-10 to 7-12 | Compatibility notes for legacy instruments: supported tests, firmware requirements, differences in channel setup, sweep parameters | 4155/4156 compatibility, legacy instrument support | Setup conversion procedure for reusing B1500A test setups |
| Using E5260A/E5262A/E5263A/E5270B | 457–458 | 7-13 to 7-14 | E5260/E5270 series support: available classic tests (I/V Sweep, Multi Ch, I/V List, Switching Matrix), unsupported features (sampling, direct control, CMU, SPGU), calibration/configuration differences | E5260/E5270 compatibility, unavailable features | |
| Using B2900 | 459–465 | 7-15 to 7-21 | B2900 series support: multi-unit connection via N1294A trigger cable, GPIB setup, detailed differences for each test type (I/V Sweep, I/V List, I/V-t Sampling, Tracer Test) including parameter limits | B2900, multi-unit, N1294A trigger cable, parameter differences | Up to 4 B2900 units; many parameter ranges differ from B1500A |

### Chapter 8 — Utilities (PDF 466–506, Printed 8-1 to 8-40)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 8 title & overview | 467–469 | 8-2 to 8-4 | System requirements for utilities, overview of programs | Utilities overview | |
| License Management Tool | 470–471 | 8-4 to 8-5 | Install/verify licenses for EasyEXPERT Extension (B1500A-SWS, etc.), view host ID | License Management, B1500A-SWS | |
| Setup File Converter | 472–473 | 8-6 to 8-7 | Convert 4155/4156 setup files (MES/DAT) to EasyEXPERT format (XTS); supports B1500A and legacy target formats | Setup File Converter, MES→XTS, DAT→XTS, 4155/4156 migration | |
| MDM File Converter | 474–475 | 8-8 to 8-9 | Convert EasyEXPERT test result files (xtr/ztr) to IC-CAP model data manager files (mdm); supports I/V Sweep, Multi Ch I/V Sweep, C-V Sweep classic test results only | MDM File Converter, xtr→mdm, ztr→mdm, IC-CAP | Application test results not supported |
| Utility Programs overview | 476 | 8-10 | Lists all utility programs: User Account Management Tool, Offline Configuration Tool, Software Configuration Tool, Prober Control, SetupFileConverter.exe, MdmFileConverter.exe, sleep.exe, XSLT filters | Utility Programs | |
| User Account Management Tool | 476 | 8-10 | Manage Windows user accounts and their EasyEXPERT user level assignments from external PC environment | User Account Management, user level assignment | Only for external PC environments |
| Offline Configuration Tool | 477 | 8-11 | Configure module/slot assignment for offline mode operation on external PC; allows test setup creation without instrument connection | Offline Configuration, module/slot assignment | Enables offline test design |
| Software Configuration Tool | 478 | 8-12 | Configure EasyEXPERT software settings and options | Software Configuration | |
| Prober Control | 479–489 | 8-13 to 8-24 | Wafer prober integration: prober control utility for Cascade Microtech Summit/PA series and Vector Semiconductor VX series; command-line interface, configuration, procedure integration with Repeat Measurement. Covers supported probers, command-line parameters, wafer map configuration, die stepping procedures, integration with EasyEXPERT Repeat Measurement procedure hooks. | Prober Control, wafer prober, Cascade Microtech Summit/PA, Vector Semiconductor VX, wafer stepping, die indexing, command-line interface, wafer map | Integrates with Repeat Measurement procedures (Ch 1); key for wafer-level automation MCP tools |
| SetupFileConverter.exe | 490–492 | 8-24 to 8-27 | Command-line version of setup file converter for batch processing | SetupFileConverter.exe, command-line, batch conversion | |
| MdmFileConverter.exe | 493–495 | 8-27 to 8-30 | Command-line version of MDM file converter | MdmFileConverter.exe, command-line | |
| sleep.exe | 496 | 8-30 | Sleep utility for scripting delays | sleep.exe | |
| XSLT Export Filters | 497–506 | 8-31 to 8-40 | 15 XSLT filter files in 5 groups for custom test record export: (1) meas data only, (2) meas+index, (3) meas+metadata, (4) meas+index+metadata, (5) all data. Formats: CSV, tab-separated, XML Spread Sheet. Detailed export format tables with examples. Complete export data component reference (TestSetup, ClassicTest, TestParameter, DutParameter, MetaData, AnalysisSetup, Dimension, DataName, DataValue). | XSLT, export filters, CSV, tab-separated, XML Spread Sheet, export components, TestSetup, DataName, DataValue | Critical for understanding EasyEXPERT data export structure |

### Chapter 9 — Application Library (PDF 507–566, Printed 9-1 to 9-60)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 9 title & overview | 507–508 | 9-1 to 9-2 | Overview of built-in application test library and QSCV accuracy information | Application Library | |
| Application Test Definitions — table | 509–531 | 9-3 to 9-25 | Comprehensive table (Table 9-1) of all furnished application tests organized by category: BJT, CMOS, Discrete, GenericTest, MCSMU_IV, Memory (including NVM with FERAM/ReRAM/PCRAM tests), MixedSignal, NanoTech, Organic, PwrDevice, Reliability, Sample, Solar Cell, SPGU_PLSDIV, Structure, TFT, Utility, WGFMU, WGFMU Utility, Thyristor, GateCharge. For each test: name, supported instrument, required equipment/quantity. | Application test categories, BJT, CMOS, Discrete, Memory (FERAM/ReRAM/PCRAM), PwrDevice, Reliability, Solar Cell, TFT, Thyristor, GateCharge, test-to-resource mapping | Most comprehensive list of B1500A measurement capabilities |
| QSCV Maximum Measurement Value | 532–536 | 9-25 to 9-29 | QSCV measurement limits: tables of maximum measurable capacitance values by measurement range, output range, and operating mode (Normal vs 4155C/4156C compatible) | QSCV, maximum capacitance, measurement range limits | |
| QSCV Measurement Accuracy | 536–566 | 9-29 to 9-60 | Extensive accuracy analysis with ~30 calculation example figures: reading accuracy (%) and offset accuracy (F) vs measurement voltage for various conditions (measurement range 1pA–1μA, output range 2V/20V/200V, integration time, DUT resistance, guard capacitance). Separate figures for MPSMU, HRSMU, HPSMU, ASU+SMU configurations. | QSCV accuracy, reading accuracy, offset accuracy, integration time effect, DUT resistance effect, guard capacitance effect | Very detailed technical reference; mostly accuracy charts |

### Chapter 10 — If You Have a Problem (PDF 567–592, Printed 10-1 to 10-26)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 10 title & overview | 567–568 | 10-1 to 10-2 | Troubleshooting overview; directs to self-test and error messages | Troubleshooting | |
| When You Operate B1500 | 569–571 | 10-3 to 10-5 | Operational problems: power-on trouble, SCUU/ASU/N1265A/N1266A/N1268A not detected, GPIB devices not detected, simplifying connections (triaxial vs Kelvin triaxial cables) | Power-on, device detection, GPIB detection, Kelvin connection, triaxial cables | USB0 connection check procedure for GPIB devices |
| When You Perform Measurement | 571–577 | 10-6 to 10-11 | Measurement problems: measurement takes too long, noise, voltage measurement error, SMU oscillation (high-frequency/negative-resistance devices), thermal drift, DUT damage prevention, post-measurement device damage, unexpected sampling data, MFCMU unbalance | Noise, oscillation, thermal drift, DUT protection, sampling data issues, MFCMU unbalance | Solutions include: pulse mode for high current, series resistor for breakdown, FILTER OFF for fast sampling |
| Notice for Migrating from 4155/4156 | 578–579 | 10-12 to 10-13 | Integration time comparison tables between B1500A/E5270B and 4155/4156 for different current measurement ranges | 4155/4156 migration, integration time comparison | |
| Before Shipping to Service Center | 580–581 | 10-14 to 10-15 | Pre-service checklist: make backup, check module slots, check ASU/SMU combination, collect equipment | Service preparation, backup procedure | |
| Data Backup and Recovery | 582–585 | 10-16 to 10-19 | Detailed backup/restore procedures: EasyEXPERT database folders (D:\Agilent\EasyEXPERT\1), database backup wizard, restore wizard, other data backup (setup files, XSLT filters), database move | Database backup, D:\Agilent\EasyEXPERT\1, backup wizard, restore wizard | Database is on D: drive; C: drive is for programs |
| Updating EasyEXPERT | 586 | 10-20 | Software update procedure | EasyEXPERT update | |
| Performing a Clean Install | 587 | 10-21 | Complete reinstallation procedure: uninstall, delete program folder, reinstall, restore database | Clean install, reinstallation | |
| B1500 System Recovery | 588–592 | 10-22 to 10-26 | Factory system recovery: preparation (note computer name, user accounts, make backup), recovery procedure for Windows 10/7 based B1500, database initialization, database restore | System Recovery, factory restore, Windows recovery, database initialization | Recovery overwrites C: drive only; D: drive (database) preserved |

### Chapter 11 — Error Message (PDF 593–692, Printed 11-1 to 11-100)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Chapter 11 title & overview | 593–594 | 11-1 to 11-2 | Error code listing overview; path conventions for different Windows versions | Error Messages, error codes | |
| Keysight EasyEXPERT Operation Error | 595–645 | 11-3 to 11-53 | ~250 error codes (100001–109xxx) with descriptions and solutions: configuration errors, parameter validation errors, measurement execution errors, sweep/sampling errors, CMU errors, SPGU errors, switching matrix errors, data export errors, application test errors | Operation errors, error 100001–109xxx, parameter validation, execution errors | Largest error section; covers all EasyEXPERT GUI-level errors |
| Keysight FLEX Execution Error | 646–673 | 11-54 to 11-81 | FLEX (measurement firmware) execution errors: low-level hardware communication errors, module errors, timing errors, range errors, compliance errors | FLEX errors, firmware errors, hardware communication | |
| Keysight B1500 Self-test/Calibration Error | 674–688 | 11-82 to 11-96 | Self-test and calibration error codes: module test failures, calibration data errors | Self-test errors, calibration errors | |
| Setup File Converter Execution Error | 689 | 11-97 | Errors from 4155/4156 setup file conversion | Setup converter errors | |
| MDM File Converter Execution Error | 690–692 | 11-98 to 11-100 | Errors from MDM (IC-CAP) file conversion: unsupported data types, invalid values, unknown parameters | MDM converter errors | |

### Appendix A (PDF 693–700, Printed A-1 to A-6)

| Section / Topic | PDF Page(s) | Printed Page(s) | What This Section Actually Covers | Keywords / UI Concepts / Measurement Concepts | Notes / Cautions |
|---|---|---|---|---|---|
| Appendix title & overview | 693–694 | A-1 to A-2 | Overview of appendix content | | |
| EasyEXPERT Measurement Capabilities vs Instruments | 695–696 | A-3 to A-4 | Comprehensive support matrix table: Classic Tests (I/V Sweep, Multi-ch, List Sweep, Sampling, C-V, SPGU, Direct Control), Application Test, Tracer Test, Quick Test, Oscilloscope View, External Instrument Drivers (LCR, Pulse Gen, DVM), Prober Control — across B1500A, B1505A, E5270B/E5260A, B2900, 4155/4156. Shows first-supported revision for each. Firmware requirements listed. | Capability matrix, instrument support, revision history, firmware requirements | Very useful reference for understanding which features apply to which instruments |
| EasyEXPERT File Summary | 697–698 | A-5 to A-6 | File extension reference: .gtr (compressed trace record), .xdb (database backup), .xpg (My Favorite group), .xtd (test definition), .xtr (test results), .xts (test setup), .xws (workspace), .ztr (compressed test results) — with how to create and read each | File extensions, .gtr, .xdb, .xpg, .xtd, .xtr, .xts, .xws, .ztr | Essential reference for file management and data interchange |
| Back cover | 699–700 | — | Copyright, part number, website | | |

---

## Page To Content Map

### Volume 1 (PDF 1–400)

| PDF Page(s) | Printed Page(s) | Section / Topic | What is explained there | Keywords / UI Concepts |
|---|---|---|---|---|
| 1 | — | Title page Vol 1 | Title, volume ID | EasyEXPERT Vol. 1 |
| 2 | — | Notices/Copyright | Legal, part number B1540-90000, edition history (Ed 1 Jun 2013 → Ed 5 Dec 2020) | Copyright, editions |
| 3 | — | Measurement Resources | Module compatibility table: HPSMU/MPSMU/MCSMU/MFCMU/HRSMU/HVSPGU/HVSMU/HVMCU/HCSMU/UHCU/UHVU across B1500A/B1505A/B1506A/B1507A | Module types, instrument models |
| 4 | — | EasyEXPERT overview | Architecture diagram: B1500 ↔ EasyEXPERT ↔ external PC, data/print servers, LAN/GPIB | System architecture |
| 5 | — | In This Manual | Chapter listing: Vol 1 = Ch 1–5, Vol 2 = Ch 6–11+App | Chapter guide |
| 6 | — | Blank/spacer | — | — |
| 7–16 | — | Table of Contents | Detailed TOC for Vol 1 with section-level printed page references | TOC |
| 17 | 1-1 (title) | Ch 1 title: Main GUI | Chapter title page | Main GUI |
| 18–19 | 1-2 to 1-3 | Ch 1 overview | Chapter intro, section list, cross-references, touch-screen note, double-precision note | |
| 20–22 | 1-4 to 1-6 | Start EasyEXPERT | Launch, Execution Mode (Online/Offline), Auto Start, Database operations (Backup/Restore/Move), @ANALYZER function | Start, Execution Mode, database |
| 23–25 | 1-7 to 1-9 | User Level Setting | Admin/Engineer/Operator levels, password, user account assignment | User levels, password |
| 26–31 | 1-10 to 1-15 | Workspace Configurator | Create/select/manage workspaces | Workspace |
| 32–48 | 1-16 to 1-32 | Main Screen GUI | Complete main screen reference: menus, tabs, buttons, Library, My Favorite, Channel Definition, Device ID | Main Screen, menus, Library, My Favorite |
| 49 | 1-33 | Main Screen (cont.) | Test record list area, import/export operations | Test records |
| 50–51 | 1-34 to 1-35 | Run Options | Auto Record, Auto Export, Multi Display settings | Run Options |
| 52 | 1-36 | Data Display Manager | Manage open Data Display windows | Data Display Manager |
| 53–54 | 1-37 to 1-38 | Test Result Editor & Filter | Flag/remarks assignment, filter by date/name/ID/flag | Test Result, Filter |
| 55 | 1-39 | Export in My Format | XSLT-based custom export of test records | Export, XSLT |
| 55–56 | 1-39 to 1-40 | Test Results Data Folder Export | Export test results as files to folder | Folder Export |
| 57–58 | 1-41 to 1-42 | Test Results Data Auto Export | Automatic export after measurement to text file | Auto Export |
| 59 | 1-43 | Test Result Manager | Import/delete/recycle results | Test Result Manager |
| 60–64 | 1-44 to 1-48 | Preference | Default settings for GUI, graph, list | Preference |
| 65–66 | 1-49 to 1-50 | Global Variables | Workspace-scope shared variables | Global Variables |
| 67–69 | 1-51 to 1-53 | Application Test mode | App test main screen GUI: Library categories, test parameters, Extended Setup | Application Test |
| 70–81 | 1-54 to 1-65 | Tracer Test mode | Real-time curve tracer: channel/sweep setup, graph/option tools, replay, reference/tracking traces, color/thickness | Tracer Test |
| 82–87 | 1-66 to 1-71 | Oscilloscope View | Time-domain waveform display during tracer test | Oscilloscope View |
| 88 | 1-72 | Arithmetic Operation | Real-time math expressions in tracer test | Arithmetic Operation |
| 89–90 | 1-73 to 1-74 | Quick Test mode | Sequential batch test execution | Quick Test |
| 91–99 | 1-75 to 1-83 | Repeat Measurement Setup | Repeat dialog: stop conditions, procedures (.exe hooks), prober control XML, thermo-trigger (N1265A) | Repeat, prober control, thermo-trigger |
| 100–101 | 1-84 to 1-85 | Organize Preset Group | Manage preset groups | Preset Group |
| 102–107 | 1-86 to 1-91 | Calibration | Module Self Cal, SMU Zero Cancel, CMU Calibration (phase/open/short/load, advanced frequency options) | Calibration, zero cancel, CMU correction |
| 108–110 | 1-92 to 1-94 | Configuration: Main Frame + Modules | Main Frame diagnosis (model ID, firmware, line frequency), Modules self-test (slot list, module names, SCUU, Status LED, Recover) | Configuration, self-test, module naming |
| 111–113 | 1-95 to 1-97 | Configuration: ASU + Switching Matrix + SMU/PG Selector | ASU mode, B2200A/B2201A/E5250A GPIB/port assignment, N1258A/B selector | ASU, Switching Matrix, N1258A |
| 114–118 | 1-98 to 1-102 | Configuration: Module Selector + Dual HCSMU + UHC Expander | N1261A module routing, dual HCSMU, N1265A (500A/1500A, fixture, bias-T) | N1261A, N1265A, UHC |
| 119–125 | 1-103 to 1-109 | Configuration: HVSMU Expander + UHV + Device Cap + Gate Charge | N1266A HVMCU, N1268A UHVU, N1272A/N1274A device cap selector, N1259A/N1275A gate charge adapter | Expanders, Device Cap, Gate Charge |
| 126–128 | 1-110 to 1-112 | Configuration: SMU Output Limits + Event Log + Extended Config | Safety limits (B1505A), event log, switching matrix hardware profile, CMU compensation modes, cable length | SMU limits, Event Log, Extended Config |
| 129–130 | 1-113 to 1-114 | Switching Matrix Panel | Manual cross-point switch control | Switching Matrix |
| 131 | 1-115 | Standby Channel Definition | Define bias-holding channels | Standby Channel |
| 132–133 | 1-116 to 1-117 | Data Display overview | Introduction, display layers (up to 50), X-Y graph + list + parameters | Data Display overview |
| 134–144 | 1-118 to 1-128 | Data Display GUI (menus/operations) | File (Save Image/Print/Export), Edit (Copy), View, Zoom (Auto Scale), Axis, Marker, Cursor, Line (normal/gradient/tangent/regression/fix), Text, Pointer, Window (tile/stack/overlay) | Data Display GUI, all menus |
| 144–147 | 1-128 to 1-131 | Display Setup + Analysis Setup | Axis variable mapping (X/Y1/Y2), scale; marker/cursor/line-based analysis expressions, auto-analysis | Display Setup, Analysis Setup |
| 147–152 | 1-131 to 1-136 | Graph Preference + List Preference + Toolbar | Grid, colors, line style, legend; column order, number format; toolbar button reference | Preferences, Toolbar |
| 153–160 | 1-137 to 1-144 | Data Status + Setup Summary + Miscellaneous Ops | Status indicators, setup summary, drag-drop scaling, mouse wheel zoom, right-click menus, keyboard shortcuts, multi-layer overlay | Data Status, Miscellaneous |
| 161–163 | 1-145 to 1-147 | Preview | Export preview window | Preview |
| 164–168 | 1-148 to 1-152 | Text File Export Settings | CSV/tab/formatted-text export config: Measurement Data (by-row/by-column, Tables 1-14/1-15), Identification (Tables 1-16/1-17), Setup data (Table 1-18), Miscellaneous (delimiter, quotation, file extension) | Text export, CSV, delimiter |
| 169–174 | 1-153 to 1-158 | Excel Data Export Settings | Measurement Data tab (Table 1-19: tag info, data names/units/size/values, segment selection), Identification tab (Table 1-22/1-23), Setup data (Table 1-24), Worksheet tab (List/Graph/Customized List targets) | Excel export, worksheets |
| 175 | 2-1 (title) | Ch 2 title: Classic Test Definition | Chapter title page | Classic Test |
| 176–177 | 2-2 to 2-3 | Ch 2 overview | Section list, GNDU usage rule | |
| 178–182 | 2-4 to 2-8 | I/V Sweep setup | Channel Setup + Measurement Setup GUI reference for I/V Sweep | I/V Sweep |
| 183–187 | 2-9 to 2-13 | Multi Channel I/V Sweep setup | Multi-channel sweep GUI | Multi Ch I/V Sweep |
| 188–195 | 2-14 to 2-21 | I/V List Sweep setup | List sweep GUI + vector data editor | I/V List Sweep |
| 196–200 | 2-22 to 2-26 | I/V-t Sampling setup | Time-domain sampling GUI | I/V-t Sampling |
| 201–204 | 2-27 to 2-30 | C-V Sweep setup | Capacitance sweep GUI | C-V Sweep |
| 205–206 | 2-31 to 2-32 | SPGU Pulse Setup | Pulse parameter setup window | SPGU Pulse |
| 207–208 | 2-33 to 2-34 | Switching Matrix Control | Per-test switch setup | Switching Matrix |
| 209–220 | 2-35 to 2-46 | Direct Control + compensation | Low-level command setup, compensation variables (compenReZ/ImZ/ReY/ImY) | Direct Control |
| 221 | 2-47 | Function Setup | User-defined math functions | Function Setup |
| 222–224 | 2-48 to 2-50 | Auto Analysis Setup | Post-measurement analysis expressions | Auto Analysis |
| 225–226 | 2-51 to 2-52 | Display Setup (Classic) | Graph axis configuration | Display Setup |
| 227–228 | 2-53 to 2-54 | SMU Range Setup | Ranging mode selection | SMU Range |
| 229–230 | 2-55 to 2-56 | ADC / Integration Time Setup | ADC type + integration time config | ADC, Integration Time |
| 231–232 | 2-57 to 2-58 | Pulse Setup | SMU pulse parameters | Pulse Setup |
| 233–234 | 2-59 to 2-60 | Advanced Setup | Wait time, after-measurement, filter, series resistor | Advanced Setup |
| 235–236 | 2-61 to 2-62 | Range Setup (CMU) | CMU measurement range | CMU Range |
| 237–238 | 2-63 to 2-64 | Advanced Setup (C-V) | C-V specific advanced settings | C-V Advanced |
| 239–240 | 2-65 to 2-66 | SPGU Control | SPGU classic test + advanced | SPGU Control |
| 241 | 2-67 | Load Z Setup | SPGU load impedance | Load Z |
| 242 | 2-68 | Pulse Switch Setup | SMU/PG selector | Pulse Switch |
| 243–248 | 2-69 to 2-74 | SPGU ALWG + Waveform Editor | Arbitrary waveform definition, pattern editor (graphic/tabular) | ALWG, waveform pattern |
| 249 | 3-1 (title) | Ch 3 title: Application Test Definition | Chapter title page | Application Test Definition |
| 250–252 | 3-2 to 3-4 | Ch 3 overview + Test Definition Window | Three-tab structure (Specification/Contents/Output), element diagram | Test Definition Window |
| 253–257 | 3-5 to 3-9 | Test Specification (before Define Layout) | Device/test parameters, types, resource types (full SMU list including WGFMU/RSWGFMU), vector dimensions, Symbols, Assign Output Channels | Test Specification |
| 258–261 | 3-10 to 3-13 | Define Layout (sub-section of Test Specification) | Grid-based layout editor for parameter entry fields: Properties (X/Y/Width/TabIndex), Align/Distribute/Centralize/Tab Order menus | Define Layout |
| 262–263 | 3-14 to 3-15 | Test Output + Analysis Parameter Definition | Analysis parameters (output variables), display setup for app test results | Test Output |
| 264–271 | 3-16 to 3-23 | Test Contents (parent section) | Script editor overview (3-16), Defining/Editing (3-17–3-20), Debugging (3-21), Variable Inspector (3-22), External Variable Setup (3-23) | Test Contents, scripting |
| 272–273 | 3-24 to 3-25 | Local Variable Definition | Variable name, type, initial value definition | Local Variables |
| 274–277 | 3-26 to 3-29 | Program Component + Auto Analysis | Component types reference, auto analysis component in app test flow | Program Component, Auto Analysis |
| 278–280 | 3-30 to 3-32 | Data Display Control + Display Data Setup | Open/close/clear display layers, configure data variable display | Display Control, Display Data |
| 281–285 | 3-33 to 3-37 | GPIB I/O | External instrument control from test flow (LCR, pulse gen, DVM, prober) | GPIB I/O |
| 286–287 | 3-38 to 3-39 | Message + Data Store Control | User prompts (OK/Cancel), data storage enable/disable | Message, Data Store |
| 288–294 | 3-40 to 3-46 | Command Execution | Direct FLEX command execution from app test: Using Command Execution (3-42), Command Parameters, Input/Output Parameter definition, Format Field (3-45), Setup Example (3-46) | Command Execution, FLEX |
| 295–296 | 4-1 to 4-2 | Ch 4 title + overview: Function Details | Chapter title page + section list | Function Details |
| 297–306 | 4-3 to 4-12 | I/V Sweep function details | VAR1/VAR2/VAR1' sweep mechanics, timing, parameters; Basic/Subordinate/Synchronous/Pulsed sweep | I/V Sweep function |
| 307 | 4-13 | Multi Ch I/V Sweep function | Simultaneous multi-channel sweep | Multi Ch sweep function |
| 308–313 | 4-14 to 4-19 | I/V-t Sampling function details | Timing diagrams, sampling mechanics, log/linear modes | Sampling function |
| 314–321 | 4-20 to 4-27 | C-V Sweep + Error Correction | CMU measurement theory, impedance models, four-terminal pair, correction formulas | C-V function, error correction |
| 322–331 | 4-28 to 4-37 | SPGU Module details | PG mode + ALWG mode functional description | SPGU function |
| 332–335 | 4-38 to 4-41 | Sweep Abort + Standby Function | Abort behavior, standby channel mechanics | Abort, Standby |
| 336–339 | 4-42 to 4-45 | Bias Hold + Current Offset Cancel | Inter-sweep bias, zero cancel procedure | Bias Hold, Offset Cancel |
| 340–345 | 4-46 to 4-51 | SCUU + ASU + Selectors | Combined I/V + C-V path, ultra-low current, module routing | SCUU, ASU, Selectors |
| 346–349 | 4-52 to 4-55 | UHC + HVSMU + UHV Expanders | High-current/high-voltage extension units | Expanders |
| 350–356 | 4-56 to 4-62 | SMU Ranging + Compliance | Ranging modes, compliance polarity/power, output area | Ranging, Compliance |
| 357–358 | 4-63 to 4-64 | SMU Pulse details | Pulse timing, parameters | SMU Pulse |
| 359–365 | 4-66 to 4-72 | SMU Measurement Time | Integration time (HS/HR ADC, AUTO/MANUAL/PLC), overhead, wait time, multi-channel timing | Integration Time |
| 366–370 | 4-72 to 4-76 | Filter + Series Resistor + Interlock + Auto Power Off | Output filter, DUT protection, safety interlock, auto power off | Filter, Series Resistor, Interlock |
| 371 | 5-1 (title) | Ch 5 title: Built-in Programming Tool | Chapter title page | Programming Tool |
| 372 | 5-2 | Ch 5 overview | Section list | |
| 373–377 | 5-3 to 5-7 | Variables and Expressions | Naming rules, constants (q, k, ε), literals with SI prefixes, operators, string/vector expressions | Variables, Expressions |
| 378–389 | 5-8 to 5-19 | Built-in Functions | Complete math/string/vector/system function reference | Built-in Functions |
| 390–393 | 5-20 to 5-23 | Read-out Functions | Marker/cursor/line read-out for analysis | Read-out Functions |
| 394–398 | 5-24 to 5-28 | Script Program Statements | Flow control (ASSIGN, BLOCK, FOR, IF, LOOP) + 2 complete examples | Script Statements |
| 399–400 | — | Vol 1 end matter | Copyright, back cover | |

### Volume 2 (PDF 401–700)

| PDF Page(s) | Printed Page(s) | Section / Topic | What is explained there | Keywords / UI Concepts |
|---|---|---|---|---|
| 401–414 | — | Vol 2 frontmatter | Title, notices, resource table, TOC for Ch 6–11 + App A | Vol. 2 frontmatter |
| 415 | 6-1 (title) | Ch 6 title: Remote Control Interface | Chapter title page | Remote Control |
| 416 | 6-2 | Ch 6 overview | Section list, path conventions for program folder, sample programs note, socket services note (port 5025) | Socket, port 5025 |
| 417 | 6-3 | Introduction | Remote control use cases, architecture diagram (Figure 6-1): Controller A/B, LAN, GPIB topology | LAN control, VISA/SICL |
| 418 | 6-4 | Supported Operations | Operation flow diagram (Figure 6-2): open workspace → setup → run → fetch → close; lists all subsystems | Operation flow, subsystem list |
| 419 | 6-5 | Preparation for Communication | Prerequisites: firewall, VISA/SICL (IO Libraries Suite), LAN connection, socket connection; only one EasyEXPERT per connection; Connection Expert usage | Preparation, IO Libraries, Connection Expert |
| 420 | 6-6 | Checking Windows Firewall Setting | Step-by-step: Control Panel → allow EasyEXPERT.exe through firewall | Windows Firewall, allow program |
| 421–425 | 6-7 to 6-11 | Notational Convention + Command Summary | Table 6-1 (notation), Table 6-2 (all commands): data types NR1/NR2/NR3/NRf/Bool/SPD/CPD/SRD/CRD/AARD/Block | Command summary, SCPI-like syntax |
| 426 | 6-12 | Common commands | *CLS, *IDN?, *OPC? | IEEE 488.2 |
| 427–432 | 6-13 to 6-18 | BENCh subsystem | Test execution: APPlication (CATalog?/SELect), COUNt, LOAD[:SETup] Block, PRESet (CATalog?/OPEN/NAME?/SETup), SELected (ABORt/NAME/NUMBer/RUN/STRing), TAG | BENCh commands |
| 433–435 | 6-19 to 6-21 | CALibration subsystem | Offset current cancel: ZERO:FULLrange/MEASure/OFF:ALL/ON/PLC/STATe? | CAL, ZERO cancel |
| 436–438 | 6-22 to 6-24 | RESult subsystem | Result fetch: FETch[:LATest]?/SIBLings?, FORMat (CSV/XML/XMLSS), ESCape, RECycle | RESult, FETch |
| 439 | 6-25 | STANDby subsystem | STATe ON/OFF | STANDby |
| 440 | 6-26 | SYSTem subsystem | ERRor[:NEXT]? | SYSTem, ERRor |
| 441–442 | 6-27 to 6-28 | WORKspace subsystem | CATalog?, CLOSe, OPEN, NAME?, STATe? | WORKspace |
| 443–444 | 6-29 to 6-30 | Remote error messages | Error codes 0 (No Error), 101 (EasyEXPERT Error), 201 (Remote Control Error) | Remote errors |
| 445 | 7-1 (title) | Ch 7 title: EasyEXPERT on External PC | Chapter title page | External PC |
| 446–449 | 7-2 to 7-5 | System requirements | Windows, .NET, IO Libraries, GPIB | Requirements |
| 450–453 | 7-6 to 7-9 | Install / start / execution mode | Installation and launch procedures | Installation |
| 454–465 | 7-10 to 7-21 | 4155/4156, E5260/E5270, B2900 differences | Per-instrument compatibility details and parameter differences | Instrument compatibility |
| 466–467 | 8-1 to 8-2 (title) | Ch 8 title + overview | Utilities chapter introduction | Utilities |
| 468–475 | 8-3 to 8-9 | License / Setup Converter / MDM Converter | License management, 4155→XTS conversion, xtr→mdm conversion | License, Converters |
| 476–478 | 8-10 to 8-12 | Utility Programs (management tools) | User Account Management (8-10), Offline Configuration (8-11), Software Configuration (8-12) | Account, Offline Config, Software Config |
| 479–489 | 8-13 to 8-24 | Prober Control | Wafer prober utility: Cascade Microtech Summit/PA, Vector Semiconductor VX; command-line, wafer map, die stepping, Repeat Measurement integration | Prober Control, wafer automation |
| 490–495 | 8-24 to 8-30 | SetupFileConverter.exe + MdmFileConverter.exe + sleep.exe | Command-line converters: 4155/4156 MES/DAT→XTS with options (/4155, /4156, /HP, /S), xtr/ztr→mdm conversion (/o, /d, /l, /s, /t options), sleep utility for scripting delays | SetupFileConverter, MdmFileConverter, sleep.exe |
| 496–506 | 8-31 to 8-40 | XSLT Export Filters | 15 filter files in 5 groups, export format tables, component reference | XSLT, export format |
| 507 | 9-1 (title) | Ch 9 title: Application Library | Chapter title page | Application Library |
| 508–531 | 9-2 to 9-25 | Application Test Definitions table | All furnished app tests by category with resource requirements | App test catalog |
| 532–566 | 9-25 to 9-60 | QSCV accuracy | Maximum measurement values + ~30 accuracy calculation figures | QSCV accuracy |
| 567 | 10-1 (title) | Ch 10 title: If You Have a Problem | Chapter title page | Troubleshooting |
| 568–571 | 10-2 to 10-5 | Operating B1500 | Power-on, device detection, connection simplification | Operations troubleshoot |
| 571–577 | 10-6 to 10-11 | Measurement problems | Timing, noise, oscillation, thermal drift, DUT damage, sampling issues, MFCMU unbalance | Measurement troubleshoot |
| 578–579 | 10-12 to 10-13 | 4155/4156 migration | Integration time comparison tables | Migration |
| 580–585 | 10-14 to 10-19 | Service prep + data backup/recovery | Pre-service checklist, backup wizard, restore wizard, database folder paths | Backup, Recovery |
| 586–587 | 10-20 to 10-21 | Update / clean install | Software update and reinstallation procedures | Update, Clean install |
| 588–592 | 10-22 to 10-26 | System Recovery | Factory restore (Win10/Win7), database init/restore | System Recovery |
| 593 | 11-1 (title) | Ch 11 title: Error Message | Chapter title page | Error Messages |
| 594 | 11-2 | Ch 11 overview | Error category listing, path conventions | |
| 595–645 | 11-3 to 11-53 | EasyEXPERT Operation Errors | ~250 error codes 100001–109xxx with descriptions/solutions | Operation errors |
| 646–673 | 11-54 to 11-81 | FLEX Execution Errors | Firmware-level errors | FLEX errors |
| 674–688 | 11-82 to 11-96 | Self-test/Calibration Errors | Module test + calibration errors | Self-test errors |
| 689–692 | 11-97 to 11-100 | Converter Errors | Setup file + MDM converter errors | Converter errors |
| 693 | A-1 (title) | Appendix A title | Title page | Appendix |
| 694 | A-2 | App A overview | Section list | |
| 695–696 | A-3 to A-4 | Capabilities vs Instruments | Support matrix: all test types × all instruments, first-supported revision | Capability matrix |
| 697–698 | A-5 to A-6 | File Summary | File extension reference (.gtr/.xdb/.xpg/.xtd/.xtr/.xts/.xws/.ztr) | File types |
| 699–700 | — | Back cover | Copyright, part number B1540-90020 | |

---

## High-Value Lookup Shortcuts

### EasyEXPERT Workflow and Project/Data Model

| Concept | Where to find | PDF Page(s) |
|---|---|---|
| Workspace: creation, selection, management | Ch 1: Workspace Configurator | 26–31 |
| My Favorite (Preset Groups): save/recall/organize test setups | Ch 1: Main Screen GUI (My Favorite section) | 44–48 |
| Organize Preset Group dialog | Ch 1: Organize Preset Group | 100–101 |
| Test record lifecycle (create → record → export → manage) | Ch 1: Run Options + Test Result Manager | 50–51, 59 |
| EasyEXPERT Database (backup/restore/move) | Ch 1: Start EasyEXPERT | 20–22 |
| Database folder paths and backup procedures | Ch 10: Data Backup and Recovery | 582–585 |
| File extensions (.xtr, .xts, .xtd, .xpg, .xdb, .xws, .ztr, .gtr) | App A: File Summary | 697–698 |
| EasyEXPERT on External PC (online/offline modes) | Ch 7 | 445–465 |
| Global Variables (workspace-scope shared data) | Ch 1: Global Variables | 65–66 |

### Application Tests and Measurement Templates

| Concept | Where to find | PDF Page(s) |
|---|---|---|
| Application Test mode main screen (Library, parameters) | Ch 1: Application Test | 67–69 |
| Application test definition authoring (three-tab structure) | Ch 3: Test Definition Window | 251–252 |
| Test Specification (parameters, types, resource assignment) | Ch 3: Test Specification | 253–261 |
| Resource type list (SMU/HPSMU/MFCMU/SPGU/WGFMU/UHCU/etc.) | Ch 3: Test Specification | 255–256 |
| Define Layout (parameter entry field positioning) | Ch 3: Define Layout | 258–261 |
| Test Contents scripting (flow control, components) | Ch 3: Test Contents | 264–271 |
| Test Output (analysis parameters) | Ch 3: Test Output | 262–263 |
| GPIB I/O (external instrument control in app test) | Ch 3: GPIB I/O | 281–285 |
| Command Execution (FLEX commands in app test) | Ch 3: Command Execution | 288–294 |
| Script statements (BLOCK, IF, FOR, LOOP, ASSIGN) | Ch 5: Script Program Statements | 394–398 |
| Complete app test examples (Vth_gmMax, NandFlash) | Ch 5: Script examples | 396–398 |
| All furnished application tests (Table 9-1) | Ch 9: Application Test Definitions | 509–531 |
| Application test categories (BJT, CMOS, Memory, PwrDevice, etc.) | Ch 9: Application Test Definitions | 509–531 |
| Built-in functions reference | Ch 5: Built-in Functions | 378–389 |

### B1500A Connection/Setup Concepts

| Concept | Where to find | PDF Page(s) |
|---|---|---|
| Measurement resources table (SMU types, module models) | Frontmatter Vol 1 | 3 |
| Module naming convention (SMU\<N\>:HP/MP/HR/HC/MC/HV/B290X/B291X) | Ch 1: Configuration – Modules | 109–110 |
| Channel Setup (Mode V/I/COMMON, Function VAR1/VAR2/CONST) | Ch 2: I/V Sweep – Channel Setup | 178–179 |
| Switching Matrix (B2200A/B2201A/E5250A) configuration | Ch 1: Configuration – Switching Matrix | 111–113 |
| Switching Matrix Operation Panel (manual cross-point control) | Ch 1: Switching Matrix Operation Panel | 129–130 |
| SCUU (SMU CMU Unify Unit) | Ch 4: SMU CMU Unify Unit | 340–341 |
| ASU (Atto Sense and Switch Unit) | Ch 4: Atto Sense and Switch Unit | 342–343 |
| UHC/HVSMU/UHV Expanders (N1265A/N1266A/N1268A) | Ch 4: Expander sections | 346–349 |
| Kelvin connection vs triaxial cable simplification | Ch 10: To Simplify the Connections | 571 |
| GPIB address and VISA interface setup | Ch 1: Execution Mode dialog | 21 |
| Multi-B2900 connection with N1294A trigger cable | Ch 7: Using B2900 | 459–465 |
| Instrument capability matrix (which tests on which models) | App A: Capabilities vs Instruments | 695–696 |

### Data Display, Graphing, Export, and Analysis

| Concept | Where to find | PDF Page(s) |
|---|---|---|
| Data Display window overview and GUI | Ch 1: Data Display | 132–160 |
| Graph menus (Zoom, Axis, Marker, Cursor, Line, Text, Pointer) | Ch 1: Data Display GUI | 134–144 |
| Display Setup (axis variable assignment) | Ch 1: Display Setup | 144–145 |
| Analysis Setup (marker/cursor/line read-out expressions) | Ch 1: Analysis Setup | 145–147 |
| Auto Analysis (post-measurement parameter extraction) | Ch 2: Auto Analysis Setup | 222–224 |
| Function Setup (user-defined math functions) | Ch 2: Function Setup | 221 |
| Read-out functions (MARKER_X/Y, LINE_GRADIENT, etc.) | Ch 5: Read-out Functions | 390–393 |
| Graph Preference and List Display Preference | Ch 1: Graph/List Preference | 147–150 |
| Text File Export Settings (CSV/tab config) | Ch 1: Text File Export settings | 164–168 |
| Excel Data Export Settings | Ch 1: Excel Data Export settings | 169–174 |
| Export in My Format (XSLT-based custom export) | Ch 1: Export in My Format | 55 |
| XSLT filter files (5 groups, 15 files, format tables) | Ch 8: XSLT | 497–506 |
| Export data components (TestSetup, DataName, DataValue, etc.) | Ch 8: XSLT tables 8-12 and 8-13 | 503–506 |
| Preview window | Ch 1: Preview | 161–163 |
| Copy Image/List/Parameters to clipboard | Ch 1: Data Display Edit menu | 137 |
| Save Image (BMP/EMF/GIF/PNG) | Ch 1: Data Display File menu | 135 |
| RESult:FETch command (remote data retrieval) | Ch 6: RESult Subsystem | 436–438 |
| MDM file conversion (xtr→mdm for IC-CAP) | Ch 8: MDM File Converter | 474–475 |

### Calibration/Compensation and Self-Test Workflows

| Concept | Where to find | PDF Page(s) |
|---|---|---|
| Module Self Calibration (enable/disable auto-cal) | Ch 1: Calibration | 102 |
| SMU Zero Cancel (offset current measurement per range) | Ch 1: Calibration – SMU Zero Cancel | 103 |
| CMU Calibration (phase compensation + open/short/load correction) | Ch 1: Calibration – CMU Calibration | 104–107 |
| CMU Advanced Options (frequency selection, reference standards) | Ch 1: Advanced Options for CMU Cal | 106–107 |
| Error Correction theory (formulas, interpolation) | Ch 4: Error Correction | 320–321 |
| Current Offset Cancel function details | Ch 4: Current Offset Cancel | 338–339 |
| Self-test via Configuration Modules tab | Ch 1: Configuration – Modules | 109–110 |
| Main Frame diagnosis | Ch 1: Configuration – Main Frame | 108–109 |
| Device Capacitance Selector calibration | Ch 1: Configuration – Device Cap Selector | 122–123 |
| Gate Charge Adapter calibration | Ch 1: Configuration – Gate Charge Adapter | 124–125 |
| Self-test/Calibration error codes | Ch 11: B1500 Self-test/Calibration Error | 674–688 |
| Remote calibration commands | Ch 6: CALibration Subsystem | 433–435 |

### Remote/Control/Software Integration

| Concept | Where to find | PDF Page(s) |
|---|---|---|
| Remote Control Interface overview (LAN, port 5025) | Ch 6: Introduction | 417 |
| Remote control preparation (VISA/SICL, IO Libraries, Connection Expert) | Ch 6: Preparation for Communication | 419 |
| Windows Firewall configuration for remote control | Ch 6: Checking Windows Firewall Setting | 420 |
| Remote operation flow diagram (open → setup → run → fetch → close) | Ch 6: Supported Operations (Figure 6-2) | 418 |
| All remote commands summary (Table 6-2) | Ch 6: Notational Convention and Command Summary | 421–425 |
| Sample programs location | Ch 6: NOTE on sample programs | 416 |
| BENCh:RUN (trigger measurement remotely) | Ch 6: BENCh Subsystem | 427–432 |
| BENCh:LOAD (load test setup as Block data) | Ch 6: BENCh Subsystem | 427–432 |
| RESult:FETch (get results in CSV/XML/XMLSS) | Ch 6: RESult Subsystem | 436–438 |
| Repeat Measurement procedure hooks (.exe integration) | Ch 1: Repeat Measurement Setup | 91–99 |
| Prober Control utility (wafer automation) | Ch 8: Prober Control | 479–489 |
| GPIB I/O from application test | Ch 3: GPIB I/O | 281–285 |
| Command Execution (FLEX commands from app test) | Ch 3: Command Execution | 288–294 |
| Direct Control (low-level GPIB in classic test) | Ch 2: Direct Control | 209–216 |
| External instrument drivers (LCR, pulse gen, DVM) | App A: Capabilities matrix | 695–696 |
| Remote error messages | Ch 6: Error Messages | 443–444 |
| All error codes | Ch 11 | 593–692 |

### Terminology to Mirror in MCP Tools and Skills

| EasyEXPERT Term | Meaning | Where defined |
|---|---|---|
| Workspace | Top-level container for test setups, results, calibration data | Ch 1 (p. 26–31) |
| My Favorite / Preset Group | Named collection of saved test setups | Ch 1 (p. 44–48) |
| Classic Test | Predefined measurement template (I/V Sweep, C-V, etc.) | Ch 2 |
| Application Test | User-defined composite test with scripted flow | Ch 3 |
| Tracer Test | Real-time interactive curve tracing mode | Ch 1 (p. 70–81) |
| Quick Test | Sequential batch execution of multiple setups | Ch 1 (p. 89–90) |
| Test Definition Window | Three-tab (Specification/Contents/Output) authoring interface for app tests | Ch 3 (p. 251–252) |
| Test Specification | First tab: defines parameters, resource types, layout | Ch 3 (p. 253–261) |
| Test Contents | Second tab: visual script editor with flow control | Ch 3 (p. 264–271) |
| Test Output | Third tab: defines analysis parameters (output variables) | Ch 3 (p. 262–263) |
| VAR1 / VAR2 / VAR1' | Primary sweep / subordinate sweep / synchronous sweep source functions | Ch 2 (p. 178), Ch 4 (p. 297) |
| CONST | Constant output channel function | Ch 2 (p. 178) |
| Channel Definition | Assignment of measurement resources to roles | Ch 1 (p. 32–48), Ch 2 |
| Compliance | Current/voltage limit protecting DUT during measurement | Ch 4 (p. 354–356) |
| Power Compliance | Power limit (V × I) protecting DUT | Ch 4 (p. 355) |
| Integration Time | ADC averaging duration (AUTO/MANUAL/PLC modes) | Ch 4 (p. 359–365) |
| Hold Time / Delay Time | Settling times before measurement | Ch 4 (p. 297–306) |
| Auto Record / Auto Export | Automatic data saving after measurement | Ch 1 (p. 50) |
| Data Display | Measurement result visualization and analysis window | Ch 1 (p. 132–160) |
| Marker / Cursor / Line | Analysis tools on graph (point tracking / free position / regression/tangent) | Ch 1 (p. 140–141) |
| Auto Analysis | Automatic parameter extraction after measurement | Ch 2 (p. 222–224) |
| Read-out Function | Functions returning marker/cursor/line values | Ch 5 (p. 390–393) |
| SCUU | SMU CMU Unify Unit (combined I/V + C-V path) | Ch 4 (p. 340–341) |
| ASU | Atto Sense and Switch Unit (ultra-low current) | Ch 4 (p. 342–343) |
| MFCMU / CMU | Multi Frequency Capacitance Measurement Unit | Ch 2 (p. 201), Ch 4 (p. 314) |
| SPGU / HVSPGU | (High Voltage) Semiconductor Pulse Generator Unit | Ch 2 (p. 205), Ch 4 (p. 322) |
| ALWG | Arbitrary Linear Waveform Generator mode of SPGU | Ch 2 (p. 242–248), Ch 4 (p. 330) |
| WGFMU / RSWGFMU | Waveform Generator/Fast Measurement Unit (and Remote Sense variant) | Ch 3 (p. 255–256, resource type list) |
| Zero Cancel | Offset current cancellation for low-current accuracy | Ch 1 (p. 103), Ch 4 (p. 338) |
| Phase Compensation | CMU phase error correction | Ch 1 (p. 104) |
| Standby / Bias Hold | Inter-measurement output maintenance | Ch 4 (p. 333–337) |
| Device ID | User-assigned identifier string per test record | Ch 1 (p. 44) |
| Test Record | Stored measurement result with metadata | Ch 1 (p. 53–59) |
| Module Self Calibration | Instrument self-calibration (auto at boot/periodic) | Ch 1 (p. 102) |
| FLEX | B1500A internal measurement firmware command language | Ch 3 (p. 288–294) |
| Command Execution | App test component for sending FLEX commands directly | Ch 3 (p. 288–294) |
| Program Component | Insertable building block in Test Contents (Classic Test, GPIB I/O, Message, etc.) | Ch 3 (p. 274–275) |
| Execution Mode | Online (instrument connected) vs Offline (no instrument) | Ch 1 (p. 21) |
| @ANALYZER | System function returning current instrument model string | Ch 1 (p. 22) |
| Socket Service (port 5025) | LAN-based remote control interface for EasyEXPERT | Ch 6 (p. 416–419) |
| BENCh / RESult / WORKspace | Primary remote command subsystems for automation | Ch 6 (p. 421–442) |
| Connection Expert | IO Libraries tool for discovering/connecting to EasyEXPERT | Ch 6 (p. 419) |
| Export components | Structured labels in XSLT/text/Excel export (SetupTitle, DataName, DataValue, etc.) | Ch 8 (p. 503–506) |
| xtr / ztr / xts / xtd / xpg / xdb / xws / gtr | EasyEXPERT file types | App A (p. 697–698) |

---

## Gaps / Ambiguities

1. **OCR quality**: The PDF text extraction is generally clean, but some mathematical expressions (especially inequality signs, Greek letters, and subscripts/superscripts in formulas) may be garbled. Formulas in Ch 4 (measurement time, error correction) and Ch 5 (expression syntax) should be verified against the original PDF images if precision is needed.

2. **Figure and diagram content**: All figures are described by their captions in the extracted text, but actual diagram content (timing diagrams, architecture diagrams, screenshot images) is not available in the text extraction. Key diagrams to verify visually:
   - Figure 4-1: SMU Output Function and Sweep Output (PDF 297)
   - Figure 4-9: I/V-t Sampling Operation Summary (PDF 308)
   - Figure 1-3: Repeat Measurement Execution Flow (PDF 91)
   - Figure 6-1: Remote Control architecture (PDF 417)
   - Figure 6-2: Operations Supported by Remote Control Interface (PDF 418–419)

3. **Table formatting**: Complex multi-column tables (especially Table 9-1 Application Tests, Table A-1 Capabilities) lost their column alignment in OCR. The content is present but row/column association may need visual verification.

4. **QSCV accuracy figures (PDF 532–566)**: These ~30 pages are almost entirely accuracy calculation charts with minimal text. The chart data (reading accuracy % and offset accuracy F vs measurement voltage) can only be read from the original PDF images.

5. **Error code completeness**: The ~250 operation error codes (Ch 11, PDF 595–645) were sampled but not individually enumerated in this index. A future pass could extract a complete error code → description mapping.

6. **Ch 1 Data Display section (PDF 132–160)**: This is the most GUI-dense section. Some toolbar button descriptions and right-click menu items may be summarized rather than individually captured. The Data Display is the primary post-measurement analysis interface and warrants detailed inspection for MCP tool design.

7. **Page range estimation for sub-sections**: Some sub-section boundaries within a chapter are estimated based on printed page numbers in the TOC and verified spot-checks. Where a sub-section spans only 1–2 pages, the boundary may be off by 1 page. Ch 3 and Ch 6 page numbers were re-verified against actual PDF page markers during the second-pass revision.

8. **Vol 2 Chapter 8 Prober Control (PDF 479–489)**: This section is important for wafer automation integration but was only sampled. The command-line interface, supported prober models, wafer map configuration, and procedure XML format should be extracted in detail for MCP prober control tools.

9. **Application Test Definition examples in Ch 5 (PDF 396–398)**: Two complete working examples (Vth_gmMax and NandFlash IV-Write-IV) are provided with line-by-line explanations. These are high-value references for understanding real app test flows but are only summarized here.

10. **Missing from this PDF**: The B1500A Programming Guide (GPIB command reference for direct B1500A control via SCPI commands) is a separate document. This PDF covers only the EasyEXPERT GUI software and its remote control interface, not the full GPIB/FLEX command set.

11. **Ch 8 Utility sub-section page boundaries (PDF 476–478)**: The User Account Management, Offline Configuration, and Software Configuration tools each occupy approximately 1 page. Exact boundaries between these three tools (printed 8-10, 8-11, 8-12) were derived from the TOC but not individually spot-checked against PDF content.

12. **Ch 3 Auto Analysis / Program Component boundary**: The TOC places Auto Analysis at 3-27 and Program Component also starts near 3-26. These sections are small (1–2 pages each) and may overlap on the same page. The ranges in this index use the TOC-derived start pages but end pages are estimated.

---

## Revision Notes

### Revision 2 — 2026-06-22

**Context**: Second-pass revision comparing existing index against the source PDF (`Keysight EasyEXPERT Software.pdf`, 700 pages). Multi-pass audit verifying page offsets against actual `-- N of 700 --` markers in the OCR'd text.

**Major corrections made:**

1. **Chapter 3 systematic page number errors (CRITICAL FIX)**: All entries from "Define Layout" onwards had incorrect PDF page numbers (consistently +4 too high). Root cause: the original indexer placed "Define Layout" sequentially after "Test Specification" at PDF 262 instead of computing from the verified offset formula (3-10 + 248 = PDF 258). This cascaded to all subsequent Ch 3 rows. All entries corrected using offset +248 verified against actual page markers.

2. **Chapter 6 missing sections**: "Preparation for Communication" (PDF 419, printed 6-5) and "Checking Windows Firewall Setting" (PDF 420, printed 6-6) were completely absent. These are critical for understanding remote control setup. Added as new rows.

3. **Chapter 6 page number errors**: "Notational Convention and Command Summary" was listed at PDF 419–423 (should be 421–425). "Common Commands" at 424 (should be 426). "BENCh Subsystem" at 425–431 (should be 427–432). "CALibration" at 432–435 (should be 433–435). Root cause: the two missing sections (Preparation + Firewall) caused a -2 offset cascade.

4. **Text/Excel Export boundary error**: Text File Export was listed as PDF 164–170 and Excel as 171–174. Verified from page markers that Excel Data Export section heading first appears on PDF 169 (printed 1-153), matching the TOC entry. Corrected to: Text = 164–168, Excel = 169–174.

5. **Chapter 3 range header**: Changed "PDF 249–293" to "PDF 249–294" (last page is printed 3-46 → 46+248=294).

**Structural improvements:**

- Split overly broad Page-To-Content Map ranges: Configuration (108–128) split into 5 rows; Data Display (132–160) split into 5 rows; Export (55–58) split into 3 rows; Ch 8 Utility Programs split into 3 rows.
- Ch 3 Test Contents restructured to show parent/child hierarchy using "—" prefix for sub-sections.
- Ch 6 entries expanded with actual SCPI command paths and operational details.
- Ch 8 expanded with User Account Management, Offline Configuration, Software Configuration as separate entries.

**Content enhancements:**

- Added 12 new terms to Terminology table (Test Definition Window, Test Specification, Test Contents, Test Output, WGFMU/RSWGFMU, Command Execution, Program Component, Execution Mode, @ANALYZER, Socket Service, BENCh/RESult/WORKspace, Connection Expert, Export components).
- Updated Application Tests lookup table with corrected page references and 5 new entries.
- Updated Remote Control lookup table with 4 new entries (Preparation, Firewall, Operation Flow, LOAD command).
- Enhanced Ch 3 Test Specification description with full resource type list (verified from PDF page 255–256).
- Enhanced Ch 1 Excel/Text Export descriptions with table numbers and detailed sub-section content.

**Verification method:**
- Offset formulas verified by reading actual PDF `-- N of 700 --` page markers and checking printed page headers (e.g., "3-10" confirmed on page after `-- 257 of 700 --` marker = PDF 258).
- Verified Ch 3 offset (+248): multiple pages confirmed (3-8→256, 3-9→257, 3-10→258).
- Verified Ch 6 offset (+414): multiple pages confirmed (6-3→417, 6-4→418, 6-5→419, 6-6→420, 6-7→421).
- Text/Excel boundary verified by reading content on PDF pages 168–171.

**What still needs future extraction:**

1. Complete error code table extraction (Ch 11, ~250 operation errors + FLEX errors).
2. Detailed Prober Control command-line parameters and XML response format (Ch 8, PDF 479–489).
3. Complete Table 9-1 application test catalog with per-test resource requirements.
4. XSLT filter file reference names table (Table 8-11) and export component definitions (Tables 8-12, 8-13) — partially captured but could be expanded.
5. Ch 5 complete app test examples (Vth_gmMax, NandFlash) transcribed with line-by-line flow.
6. Detailed BENCh subsystem command parameters and usage examples for MCP tool implementation.
7. Repeat Measurement procedure XML response format (Ch 1, PDF 91–99) for prober integration.
