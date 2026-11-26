# Architecture

The B1500A is treated as a safety-gated measurement kernel, not as a command endpoint. A typed Python core owns
every decision (what may run, with which limits, how it is cleaned up and recorded); the MCP server and the CLI are
thin adapters over one service facade; agents reach the instrument only through them. The authoritative design is
[`docs/design/blueprint.md`](design/blueprint.md) (v2: §2 architecture and interfaces, §9 hygiene); this page is
the overview of the code as built. Work-package tags (WP5.5, ...) in the tables say which work package built or
changed a part; their acceptance results and handoff notes are in [`progress.md`](design/progress.md), the
milestones in the [roadmap](roadmap.md). Nothing has run on hardware yet (M12).

## Layers (owner deck L1–L8)

| Layer | Responsibility | Code / files |
|---|---|---|
| L1 Physical safety | Interlock, shield box, triax/Guard/Kelvin wiring, switches, per-channel compliance, the 42 V / 100 mA code ceiling | `config/station.example.yaml` (interlock, topology, switches, correction standards), rule `R-IL-01`, bring-up stage S0 (`.agents/skills/b1500-bringup/stages/s0-physical.md`) |
| L2 GPIB / VISA and the WGFMU library | Byte transport per transaction and the WGFMU instrument library; every I/O and library call audited | `transport/` (`base`, `audit`, `visa`, `factory`, `readonly`), `transport/wgfmu/` (`WgfmuApi`, the ctypes binding `WgfmuDll`), `transport/sim/` simulator of the whole station (FLEX and library) |
| L3 Driver | FLEX builders (the only FLEX text), guarded `B1500Driver` with per-family mixins, `WgfmuDriver`, `OutputGuard`, parsers, discovery, error decoding, module specs | `driver/` (`flex/`, `ops/`, `b1500.py`, `wgfmu.py`, `guard.py`, `parser.py`, `cmu_data.py`, `discovery.py`, `errors.py`, `modules.py`) |
| L4 Measurement transaction | Lock, transaction with guaranteed cleanup, fault latch; recipes, kinds, planner, executor; run archive | `session/`, `catalog/`, `recipes/`, `archive/` (M1) |
| L5 Analysis | Quality classification, extraction (Vth, SS, gm, ...), plots | `analysis/` (M1–M2) |
| L6 MCP / CLI | Ten MCP tools and the `b1500` CLI over `B1500Service`; the CLI-only bring-up helpers and manual queries | `service/`, `adapters/mcp_server.py`, `adapters/cli/` (WP1.8; package split WP5.6), `bringup.py` (WP6.1, WP6.3) |
| L7 Skills + rules | Rule engine and tiers; human-owned limits; entry, debug and bring-up skills | `rules/`, `config/*.example.yaml` → `config/local/`, `.agents/skills/` with the generated `.claude/skills/` copy (rules M1; skills M2: entry skill + card template WP2.4, six test cards + reserved slots WP2.5, knowledge 01–07 WP2.6, `b1500-debug` WP2.7; v2 WP5.10: cards in family folders `cards/<family>/` with the generated index `cards/README.md`, family router, `b1500-bringup` skeleton; bring-up stage files S0, L0-L4, L10 WP6.3 and L5-L9 by the module closures 7.7, 8.6, 9.6, 10.8, with their runbooks) |
| L8 Agent | Codex CLI and Claude Code | `AGENTS.md`, `CLAUDE.md`, harness wiring: `config/harness/` templates → generated `.codex/config.toml` / `.mcp.json`, committed `.codex/rules/b1500.rules`, `.claude/settings.json`, `scripts/hooks/b1500_guard.py` (WP1.9) |

## Dependency direction

```text
adapters → {bringup →} service → {catalog, rules, archive, analysis, manuals} → session → driver → transport
models: shared leaf, imported by every layer, imports none of them
manuals: imports only models and paths; bringup: imports only service and models
```

Enforced by tests: an import-layering test over the package (`tests/unit/test_import_layering.py`); `analysis` never
imports `session`, `driver` or `transport`; only `adapters/mcp_server.py` imports `fastmcp` (developer tools in
`devtools/` are exempt); only `transport/visa.py` imports `pyvisa` and only `transport/wgfmu/dll.py` imports `ctypes`
and loads `wgfmu.dll`; `WGFMU_` symbols appear only in `transport/wgfmu/` and the simulator's library
(`transport/sim/wgfmu.py`; `tests/unit/test_lint_wgfmu_symbols.py`); only `driver/flex/` contains FLEX mnemonics in string literals (the simulator, the
instrument side, is exempt); only kind `system` calls the `*RST` builder; no source file exceeds 1,000 lines
(`tests/unit/test_layout.py`); `driver/ops/` is imported only by the `B1500Driver` facade and the simulator units
only by their dispatcher; every text-mode open, read, write and subprocess names its encoding and Windows-only
modules are imported lazily (`tests/unit/test_lint_encoding.py`, `tests/adapters/test_windows_readiness.py`).
Hardware access, library calls or FLEX text added to a recipe, a tool or an analysis function therefore fail a
test.

## Module map (`src/b1500_test_agent/`)

| Module | Content | Status |
|---|---|---|
| `models/` | Pydantic models: common envelope, station, routing (switches, routes), policy, plan, recipe, run, analysis, measurement | all present (M0 salvage + WP1.1); v2 models WP5.3 (switches/routes, pulse/AC/waveform envelopes, `RunProgress`, correction records, `file` parameters); `sources.py` (pulse trains, WGFMU `WaveformProgram`, the `SourcePlan` kinds store in `plan.program["sources"]`) and live switch/correction/WGFMU fields WP5.4 |
| `config.py`, `paths.py`, `errors.py` | Config loading and resolution, repo-relative default paths, error types | done (WP1.1; `b1500 config check`); WP6.1: `init_local`/`adopt` = the human-only `b1500 config init [--visa]` (copy missing core examples, never overwrite) and `config adopt FILE --as KIND` (schema, diff, `.bak`, copy) |
| `transport/` | `Transport` protocol (+ `lock`/`unlock`), `Bus` (`flex`, `wgfmu`), `AuditingTransport` (I/O and `bus_*` lifecycle events), `VisaTransport` (opened per transaction: open → `lock_excl` → … → unlock → close; injectable resource manager), `make_bus` (never selects visa implicitly), `readonly.py` `ReadOnlyTransport` (lets only single queries through; probe, proposal and status snapshot), `VisaTransport.list_resources` | done (WP1.2; audit event model `models/audit.py`); v2 bus lifecycle, `BusLocked`, `visa.session: transaction\|process` (WP5.5); `wgfmu/` `WgfmuApi` protocol, `WgfmuError`, constants and limits (`api.py`), `AuditingWgfmu` (`wgfmu_call` events), `Bus.wgfmu` set on sim (WP10.1); `wgfmu/dll.py` `WgfmuDll` (the only `ctypes` module: `WinDLL` loaded at the first call after a pure-Python PE probe, argtypes from the generated `C_SIGNATURES` (`scripts/gen_wgfmu_signatures.py`, API extract + manual prototypes), ASCII strings, numpy buffers, 100,000-value chunked readback, rc → `WgfmuError` with the library's error string), `WgfmuDll.locate(settings) -> DllProbe` (x64/x86, file version, exports; never raises), `Bus.wgfmu` on visa (WP10.2); the library's warning queue in the protocol (`set_warning_level`, `warning_level`, `treat_warnings_as_errors`, `warnings`; WP10.8); nested `AGENTS.md` |
| `transport/sim/` | Deterministic FLEX state machine: `instrument.py` (dispatcher: clock, persisted state, command log, measurement lifecycle, `SimTransport`) over `units/` (`core`, `smu`, `sampling`, `cmu` + `cmu_engine`, `spgu`, `switch`; handlers registered by mnemonic; WP6.1 adds the probe's state queries `ERMOD?`, `ERSSP?`, `SPST?`, `CORRST?`, `ADJ? ch,0` on persisted state; WP8.1 the MFCMU: MM 17-26 with `MM`/`XE` dispatch by mode, fixture parasitics, phase compensation and persisted open/short/load corrections, and the SCUU `SSP`/`SSL` with routing of the MFCMU sides), `flex.py` (syntax, error codes), `format.py` (output formatter), `devices/` (`base`, `kinetics`, `basic`, `mosfet`, `moscap`, `fixture`, `dielectric`, `ferro`, `noise`, `circuit`), `faults.py`, `state.py` | done for the v1 subset and open/resistor/short/`mosfet_ekv` (WP1.2; schemas `models/sim.py`); `diode`, `fefet` (persisted polarization), `mosfet_damaged` and scenarios `diode_basic`, `resistor_100k`, `fefet_basic`, `open_drain_noisy`, `gd_short` (WP2.1); v2 device models `mosfet` (self-heating, BTI, HCI, IGZO drift, split C-V), `moscap`, `capacitor`, `fixture`, `dielectric`, `fecap`, `noise` and FeFET kinetics/retention/endurance with `advance(dt, v)` and truth accessors (WP5.9; schemas `models/sim_devices.py`); scenario `lab_nmos_2025` fitted to the lab's Id-Vg curve `tests/fixtures/lab/idvg_real.csv` (WP6.2); HV-SPGU unit (`units/spgu.py` + `units/spgu_output.py`: PG/ALWG setup and errors, `SPST?` state machine in virtual time, free run after `*RST`, SER divider, ALWG blocks, pulses driving the FeFET kinetics; `advance`/`receive_block`; faults `spgu_no_stop`, `spgu_load_mismatch`; WP9.1); WGFMU library `wgfmu.py` `SimWgfmu` on the same instrument (patterns, events, sequences, modes, ranges, RSU path, memory, firmware errors) with `wgfmu_engine.py` (`DrivenCircuit`, piecewise-linear output, RAW/AVERAGED data, dynamic devices), `wgfmu_checks.py` and `wgfmu_extras.py` (WP10.1), `wgfmu_bulk.py` (long unmeasured repeats such as bipolar cycling in aggregated chunks with the devices' cycle counters; WP10.6); SMU readings during an SPGU train are time averages plus the MOSFET charge-pumping current (`PumpedDevice`, `Circuit.pumped_currents`), scenario `nmos_cv` (WP9.3); scenarios `nmos_wgfmu` (transistor on WGFMU 201/202, the RSUs' SMU inputs cabled to SMU4/SMU3 for DC references), `nmos_rtn` (+ 1/f and telegraph noise), a WGFMU resistor in `resistor_100k`; an RSU without a recorded library state is on its SMU path (WP10.4) |
| `driver/` | `flex/` builders (`core`, `smu`, `cmu`, `spgu`, `switch`; the only FLEX literals), `b1500.py` facade `B1500Driver(CoreOps, SmuOps, CmuOps, SpguOps, SwitchOps)` over the `ops/` mixins, `guard.py` `OutputGuard`, `parser.py`, `cmu_data.py` (MFCMU data blocks: impedance pairs per `IMP` model, monitors, CMU status), `discovery.py`, `errors.py`, `modules.py` | done for the staircase path (WP1.3: FMT 1/5 parser, discovery, `OutputGuard`, module specs; WP5.2: per-family split; WP5.4: `OutputGuard` v2 `check_pulse`/`check_ac`/`check_route`/`check_waveform`, spec rows HV-SPGU, SMU pulse, WGFMU, MFCMU, SCUU, ASU; WP6.1: read-only family queries for the probe; WP8.1: the MFCMU builders, guarded `CmuOps` (signal, MM 17-26 setups, phase compensation, data correction, cleanup zeroing), `cmu_data.py` parser, guarded SCUU `SSP`; WP8.6: `CORRDT?` correction-data read-back (`correction_data_list`, the correction runs' plausibility values); WP9.1: SPGU builders incl. ALWG blocks, guarded `SpguOps`, `SPGU_SPEC.program_problems`, programs in `models/spgu.py`; WP7.5: `flex/search.py` (`LS*`/`LG*`, `BS*`/`BG*`, `BDV`/`BDT`/`BDM`), guarded `SearchOps`, `driver/search.py` search data; WP10.3: `wgfmu.py` `WgfmuDriver` over `WgfmuApi`: configure, load (whole program checked first: `check_waveform` per pattern, `check_sequence` per channel), RSU connect via `check_route`, run with polls ≤ 1 s and chunked readback, `safe_state`; RSU states from the library; WP10.8: the warning summary read after every run into `kind_result.wgfmu_warnings`) |
| `session/` | `InstrumentLock` (OS file lock), `Session` (opens, locks, unlocks and closes the bus per transaction and status snapshot, so no process holds the instrument between calls), `Transaction` (cleanup `AB → SPP (SPGU, if SPST? 1) → DCV/ACV 0 (driven MFCMUs) + DZ → routes to rest (declared selectors, SCUU, ASU; `routes.py`) → CL → verify (outputs + switch read-back)`, then `restore`; `apply_routes(phase)`: guarded, settle wait, read-back verified; `checkpoint`/`check_abort`; `suspend_auto_calibration`; `lop_positive_control`: hardware `LOP?` after `CN`, the evidence behind `verified: lop`), `FaultLatch`, `abort.py` (`AbortFile` `<state_dir>/abort.json`, `AbortWatch`, `RunCancelled`), `runner.py` (`RunControl`: progress, partial rows, abort polling at checkpoints; `Runner`/`RunJob`: the non-daemon worker thread of an asynchronous run) | done (WP1.6; inflight recovery, daily audit sink, `RunHandle` protocol for the archive); per-transaction bus (WP5.5); async runs, abort file, run control, recovery hook `Session.on_recovery` (WP5.6); `LOP?` positive control (WP6.2); cleanup step 2 SPGU stop + `SPST?` verification (WP9.1); `wgfmu_live.py`: the WGFMU library probe in visa snapshots, the channel ids in the pre-execute snapshot of a WGFMU plan (FLEX lock released meanwhile, R-WG-01), `Session.check_wgfmu_session` (FLEX closed; `doctor --probe --wgfmu-session`) (WP10.2); routes per phase, cleanup steps 5/8 and `switch_states` snapshots, `Session(switches=)` from the station (WP9.2); `wgfmu_phase.py`: `tx.wgfmu_phase()` (FLEX unlock, or close with `wgfmu.flex_during_phase: close` (ATV-14 fallback), library session, `initialize`, guarded `WgfmuDriver`; the exit always runs step 3 and relocks), cleanup step 3 (WGFMU abort → initialize → disconnect → close → relock; after an unconfirmed phase, in `safe_shutdown` and recovery with a WGFMU), RSU states in the pre-execute snapshot (WP10.3) |
| `rules/` | Rule registry and engine, built-in rules (`builtin/`: `core`, `limits`, `run`, `pulse`, `route`, `cmu`, imported in table order), tiers, hard-limit code ceiling, `plan_summary`, correction-record source protocol | done (WP1.4; v2 rules and summary WP5.4; rule table in [safety-model.md](safety-model.md)) |
| `catalog/` | Recipe schema and registry, planner (sets `mode` sync/async from the estimate), executor (sync runs on the calling thread, async runs on a worker), `running.py` (the run holding the instrument, `stop_runs`, `follow`, orphan finalization), the 14 measurement kinds (`smu_spot`, `smu_staircase`, `smu_stepped`, `smu_pulsed`, `smu_sampling`, `smu_search`, `smu_qscv`, `cmu_measure`, `cmu_correction`, `spgu_pulse`, `wgfmu_waveform`, `stress_measure`, `pulse_read`, `system`; registry `default_kinds()` in `catalog/kinds/__init__.py`), `waveforms.py` (pure WGFMU waveform builders, the lab CSV layout, the data layout of a run; WP10.4), `fast_bti.py` (the builder `fast_bti`; WP10.7), `ferro_waveforms.py` (the builders `pund` and `program_read` and the pattern pieces of the WGFMU `pulse_read` path; WP10.6), `files.py` (`file` parameters; `ParamFiles` hands a kind the verified bytes at compile), `corrections.py` (correction-store wiring: live `CORRST?` read before MFCMU plans, records after correction runs; WP8.2) | done (WP1.7; recipes `mosfet.idvg`, `generic.smu_staircase`, `system.*` sim-validated, 13 reserved slots; `b1500 dev recipe-check`; WP2.1: `smu_stepped` host loop; WP2.2: `basic.contact_resistor`, `basic.diode_iv`, `mosfet.idvd`, `mosfet.gate_leakage`, `fefet.dual_sweep_mw` sim-validated; WP5.6: async runs, checkpoints in `smu_stepped`, R-CAL-02 `CM 0` + restore, correction store wired into the planner; WP7.4: `smu_sampling` (MM 10, block chains), `generic.smu_sampling`, `mosfet.id_t_sampling`, `reliability.tddb_cvs`; WP7.1: `smu_spot` (MM 1, DV/DI, host list, range survey), `system.zero_check`, `generic.smu_spot`, `resistor.kelvin_4w`, ASU option of `mosfet.gate_leakage`; WP7.6: `catalog/blocks.py` (shared guarded blocks: routes, reads, instrument-timed holds) and the composite `stress_measure` (stress -> reads at log/list times -> recovery reads), `reliability.bti_sms`, `igzo.bias_stress`, `reliability.hci`, `reliability.silc`; WP8.2: `cmu_correction` with `cmu.phase_compensation`, `cmu.correction_open/short/load`; WP7.3: `smu_pulsed` (MM 3/4/5/27/28, host list of pulse levels), `mosfet.idvg_pulsed`, `mosfet.idvd_pulsed`, `basic.pulsed_spot`, `generic.smu_multi_pulsed`; WP7.5: `smu_search` (MM 14/15 linear/binary search, MM 9 quasi-pulsed spot), `mosfet.vth_search`, `basic.breakdown_search`, `dielectric.bdv`); WP9.3: `spgu_pulse` pulse modes `pg`/`alwg` with SMU readings during a train (`kinds/spgu_train.py`, block `blocks.spgu_burst`), `spgu.pulse_train`, `spgu.alwg_sequence`, `mosfet.charge_pumping`; the planner binds against `ConfigBundle.planning_station` (simulator: null selector inputs from the scenario cabling); WP9.4: the composite `pulse_read` (route -> HV-SPGU or SMU pulse source -> route back -> SMU read per operation and cycle; `kinds/pulse_sources.py`, block `blocks.smu_pulse_burst`; a read role on the pulsed pad names it with `RoleSpec.terminal`), `fefet.pulse_write_read`, `spgu.program_smu_read`; `validate_plan` `resolved.routes` per phase; WP9.5: `pulse_read` schedules (`kinds/pulse_schedules.py`: endurance checkpoints with three-level SPGU cycling bursts, amplitude x width grid / ISPP, retention reads with MM 10 holds, pre-cycles), `fefet.switching_kinetics`, `fefet.endurance`, `fefet.retention`; WP8.3: `cmu_measure` (MM 17 spot, MM 18 C-V single/double, host frequency loop, SCUU route to the MFCMU and back; `kinds/cmu_routes.py`) with `cmu.spot`, `moscap.cv`, `mosfet.cgc_cv`, `mosfet.cgd_cv`; corrections through an SCUU; WP8.4: the C-V variants in `kinds/cmu_variants.py`: pulsed spot C / pulsed C-V MM 19/20, C-f MM 22, C-V (AC level) MM 23, C-t MM 26 with chained blocks, with `moscap.pulsed_cv`, `moscap.cf`, `moscap.ct`, `moscap.cv_ac_level`, `fecap.cv_butterfly`; WP8.5: `smu_qscv` (MM 13 quasi-static C-V with leakage compensation and the `QSZ` offset; SMU roles through an SCUU's SMU path, `SSP` instead of `CN`) with `moscap.qscv`, and `moscap.cv_multi_freq`; WP10.4: `wgfmu_waveform` (one `WaveformProgram` per run in the transaction's WGFMU phase, optional SMU bias around it, DC mode for `dc_spot`, raw readback `raw/wgfmu-<ch>-000.npz`, `program.json`, tables above 200,000 rows as `data.npz`), `wgfmu.pulsed_iv` (reserved id implemented), `wgfmu.fast_iv`, `wgfmu.pulse_train`, `wgfmu.custom_waveform` (lab CSV files from `recipes/waveforms/` or `work/waveforms/`), `wgfmu.dc_spot`; WP10.5: builder `dc_sample` (constant bias, one long event; role setting `force_range`), `wgfmu.rtn`, `wgfmu.lfn` (the lab's LFN layout); WP10.7: the WGFMU path of `stress_measure` (`kinds/stress_wgfmu.py`: the `fast_bti` builder of `catalog/fast_bti.py`, the schedule in WGFMU executions of at most 25 s, an SMU bias inside the phase), `wgfmu.fast_bti` (reserved id implemented), `system.wgfmu_self_test`, `system.wgfmu_self_cal` (kind `system` through the WGFMU library); WP10.6: the WGFMU path of `pulse_read` (`kinds/pulse_wgfmu.py`: the WGFMU source with bipolar cycling bursts, staircase and PUND reads, one execution per step; switching reads in `pulse_schedules.py`), builders `pund`, `program_read`, `fecap.pund` (reserved id implemented), `fecap.endurance_pund`, `fefet.fast_program_read`; WP11.2: the 14 kinds only, each on sim and visa (the declared-only `UnimplementedKind`, `recipes/reserved/` and the reserved status are gone; `RecipeRegistry.runnable` + R-REC-01 block a kind without a code path on the backend), a WGFMU role's sequencer `mode` (`fastiv`, `pg`; `wgfmu.pulse_train` `gate_mode`)) |
| `archive/` | Run folders, manifest, `audit.jsonl`, `index.jsonl`, sha256 of every file; MFCMU correction store | done (WP1.7; raw blocks kept on failure, append-only notes; WP5.7: `data.npz` + `preview.csv` above 200,000 rows, `program.json`, `progress.json`/`partial.csv` writers for async runs, `raw/wgfmu-<ch>-<n>.npz`, `corrections.py` store + freshness query) |
| `analysis/` | `load_run`, `assess_quality`, extraction methods, plots, `ANALYSIS_METHODS` registry | done (WP1.5: `quality_report`, `vth_linear_extrapolation`; WP2.2: `vth_constant_current`, `vth_max_gm`, `subthreshold_swing`, `gm_max`, `ion_ioff`, `output_metrics`, `resistance`, `diode_fit`, `leakage_at`, `memory_window`, `plot_iv` (PNGs stored under the run's `plots/` by the archive); WP5.7: run-table contract v2 in `dataset.py` (optional columns, CSV or npz), method family tags, `plot_timeseries`; WP7.4: `sampling_summary`, `time_to_breakdown`, `weibull_fit`; WP7.6: `stress.py` with `bti_power_law`, `degradation_vs_time`, `silc`); WP9.3: `charge_pumping` (`charge_pumping.py`; WP8.3: `cv.py` with `cv_cox`, `cv_flatband`, `cv_doping_profile`, `cv_vth`, `cv_hysteresis`, `impedance_convert`, `plot_cv`; geometry from `RunManifest.dut_geometry`; WP9.4: `nvm.py` with `memory_window_pulse`; WP9.5: `switching_kinetics_fit` (NLS core `nls.py`), `endurance_summary`, `endurance_curve`, `retention_fit`; WP8.4: `cv_variants.py` with `cf_dispersion`, `ct_recovery`, `cv_ac_dependence`, `cv_butterfly`, `cv_pulsed_vs_dc`); WP7.7: `model.py` (`compact_model_fit`, `model_compare`, `export_spice_netlist`; `spice.py` writes the `.lib`/`.sp` files the archive stores under the run's `analysis/`); WP8.5: `qscv.py` (QSCV runs for `cv_cox`/`plot_cv`) and `dit.py` (`dit_high_low` two-run, `dit_conductance`); WP10.5: `noise.py` (`it_statistics`, `psd_welch`, `rtn_levels`, `plot_psd`) with the Welch PSD and model fit in `spectrum.py`; WP10.6: `pund.py` (`pund_polarization`, `plot_pund`) |
| `manuals/` | Manual corpus: `catalog` (catalog/synonyms, manuals folder, PDF location), `build` (pypdfium2 → `references/manuals/corpus/`), `search` (BM25 `search`, `page`, `toc`, `status`; structured-extract fallback) | done (WP5.8; CLI-only `b1500 manual …`, `doctor` checks, citation lint `devtools/skills/citations.py`; [manuals.md](manuals.md)) |
| `bringup.py` | Lab bring-up helpers (imports only `service` and `models`; archive and parsers through `service/evidence.py`): `propose_station` (read-only `*IDN?`/`UNT?` → `work/bringup/station.proposed.yaml` fitted to the live inventory, diff vs the local station file), `bringup_status` (stages and records), `capture` (anonymized golden fixtures of hardware runs and probes), `record` (draft `ValidationRecord` from hardware runs only; schema `models/validation.py`) | WP6.1, WP6.3 (`validation/hw/` + promotion rule in `dev recipe-check`) |
| `service/` | `B1500Service`: one method per MCP tool; reloads changed config, audits every call, never raises to adapters. `core` (tool methods, plumbing, `list_recipes`, `validate_plan`), `status` (`station_status`), `runs` (`list_runs`, `get_run`, `analyze_run`, `annotate_run`), `shutdown` (`safe_shutdown`, `B1500Admin`), `probe` (the read-only bring-up probe and inventory reading behind `B1500Admin.probe`/`read_inventory`), `common` | done (WP1.8; result models in `models/results.py`, responses ≤2k tokens, human-only `B1500Admin` for `fault clear`/`lock status`); package split, running runs (`busy`, progress, partial data, cancel from any process), `follow_run`/`stop_runs` (WP5.6); `service/probe.py` (WP6.1) |
| `adapters/` | `mcp_server.py` (10 tools; shutdown hook on stdin EOF, SIGTERM and exit), `cli/` (`b1500`, `b1500-mcp`: `core.py` root app and operator commands (an async `run` stays in the foreground, Ctrl-C cancels), `dev.py` the `dev` group, `manual.py` the CLI-only `manual` group, `config.py` the CLI-only `config` group (`check`, human-only `init`/`adopt`), `bringup.py` the CLI-only `bringup` group), `streams.py` (stdout/stderr never fail on a legacy Windows code page: `backslashreplace` when not UTF-8, WP6.5) | done (WP1.8: 10 tools at 1,474 tokens, `requiresUserInteraction` on `run_confirmed_plan`; all §5.3 operator commands, `fault clear`, `lock status`, `doctor`, `mcp`; WP1.9: `harness init --codex\|--claude [--check]`, `dev mcp-smoke`; WP5.6: async additions at 1,584 tokens, `dev mcp-smoke --async`; WP6.1: `doctor --probe`, `b1500 bringup propose-station`, `config init`/`adopt`) |
| `devtools/` | `budget.py` (tool-schema token counter), `doctor.py`, `sim_console.py`, `harness.py`, `harness_versions.py`, `update.py`, `harness_qualify.py`, `mcp_smoke.py`, `coverage.py`, sync-harness, lint-skills (`skills/`: `layout`, `cards`, `params`, `links`, `budgets`, `markdown`, `common`, `citations`, `stages`, `commands`, `index`, `lint`), gen-index, recipe-check, acceptance runner | `budget.py` (M0), `recipe_check.py` (WP1.7), `doctor.py` (installation checks; the probe is `service/probe.py` since WP6.1; WP11.4: the `local config` check of the human-recorded facts: switch wiring and presence, DUT `pulse`/`ac` envelopes, local pin maps and DUT profiles) + `sim_console.py` (WP1.8), `harness.py` (render/check harness configs, doctor harness check) + `mcp_smoke.py` (WP1.9); sync-harness, lint-skills WP2.3; acceptance runner WP3.1; lint v2 + `gen-index` WP5.10; `coverage.py` (`b1500 dev coverage`: the generated `docs/coverage.md`, module → kinds → recipes → cards → rules → simulator → stage → ledger counts, the in-scope modes, every gap a problem) WP11.2; `harness_versions.py` (`config/harness/validated.yaml`, installed version and install method, the one installer per harness) + `update.py` (`b1500 update`: the operator's pull, sync, wiring, validated harness versions, free checks and verdict) + `doctor` line `harness versions` WP21.1; `harness_qualify.py` (`b1500 dev harness qualify`: the maintainer's T0-T3 ladder, candidate install and restore, bump, report, `--windows`, `--pin`) + acceptance `infra.py` (stop at the first login/API/network event), `contract.py` + `vocabulary.py` (the implicit `harness contract` grader) WP21.2 |

Outside the package: `recipes/` (registry source YAML), `config/` (examples, sim scenarios and faults, harness
templates), `.agents/skills/` (canonical skills) with a generated copy in `.claude/skills/`, `references/manuals/`
(manual catalog, committed page corpus, structured manual extracts), `references/driver-map/` (legacy taxonomy
mapped onto the driver: the coverage ledger, every entry mapped or out of scope with a reason since WP11.2; read only
for driver work; its counts feed `docs/coverage.md`), `validation/hw/` (reviewed hardware validation records, the only
evidence for `hw_validated`; empty until M12), `scripts/` (driver map, WGFMU signature table), `tests/` (`unit`,
`sim`, `safety` (the global fault matrix), `integration`, `visa_loop` (the real `VisaTransport` over a fake VISA
resource manager that forwards to the simulator), `wgfmu_abi` (`WgfmuDll` against a ctypes-shaped fake of the
library), `adapters`, `skills`, `acceptance`, `hardware` (lab PC only, `B1500_HW=1`)).

## Adding a module family

The code is split per instrument family (blueprint v2 §9), so a family's work touches its own files plus a few
append-only registries. The M7–M10 module work packages (SMU, MFCMU + SCUU, HV-SPGU + 16440A, WGFMU + RSU) each
followed these steps; the tests named below fail until a step is done, and `uv run b1500 dev coverage --check` lists
whatever is still missing for the module. A new family is a plan-of-record change first (blueprint §1.2 scope, §3
catalogue rows, §7.4 stage): the steps implement a decided scope, they do not decide it.

1. **Station model.** The module type in `models/station.py` (`ModuleType`, `MODULE_TYPE_BY_MODEL` for its `UNT?`
   model numbers, `MODULE_FAMILY` when it measures), a switch accessory in `models/routing.py` (`SwitchKind`,
   `SWITCH_STATES`, `SWITCH_INPUTS` and the station validation of its inputs); a recipe family in `models/recipe.py`
   (`RecipeFamily`; new role functions in `RoleFunction`); its points limit in `models/policy.py` (`PointLimits`)
   and soft bands in the policy (`config/policy.example.yaml`), never above the code ceiling.
2. **Module spec.** A spec row in `driver/modules.py` (voltage, current, timing, levels; each citing its manual page)
   that R-LIM-01 and the guard read; discovery of the module in `driver/discovery.py` (`UNT?`, `LOP?` codes) and its
   error codes in `driver/errors.py`.
3. **FLEX builders.** `driver/flex/<family>.py`: pure builders and constants, each docstring citing `PG p<pdf>
   (<printed>)` (citation lint); re-export them in `driver/flex/__init__.py` (`__all__`), add the module to
   `FAMILY_MODULES` in `tests/unit/test_driver_flex.py`; golden strings under `tests/fixtures/flex/<family>/`.
4. **Driver mixin.** `driver/ops/<family>.py`: a `DriverBase` mixin whose source-like methods pass the
   `OutputGuard` first (a new kind of output gets its own guard check in `driver/guard.py`, as `check_pulse`,
   `check_ac`, `check_route` and `check_waveform` did); add it to the bases of `B1500Driver` in `driver/b1500.py`.
   Read-only state queries the probe and the cleanup need go here too.
5. **Simulator.** `transport/sim/units/<family>.py`: a mixin with `@handles("<MNEMONIC>")` handlers (and
   `@learns(<type>)` for its `*LRN?` groups) and a settings reset; add it to the bases of `SimInstrument`, call its
   reset from `_reset_settings`, add the mnemonics to `flex.SUPPORTED` (`tests/sim/test_units.py`: one handler per
   mnemonic) and its unsafe states to `SimInstrument.unsafe_reasons` (the simulator's cleanup verification). A family
   with its own `MM` modes joins the `MM`/`XE` dispatch by mode in `units/cmu.py`. Device physics go to
   `transport/sim/devices/<model>.py` and `devices/circuit.py` (`build_device`), each against its blueprint §4.2
   fidelity target; faults to `models.sim.FAULT_KINDS` and `transport/sim/faults.py`; a scenario
   `config/sim/scenarios/<device>_<feature>.yaml`.
6. **A module reached through a vendor library** (as the WGFMU): a Pythonic protocol in `transport/<family>/api.py`
   (`WgfmuApi`), an audited wrapper (`AuditingWgfmu`), the simulator's implementation on the same instrument
   (`transport/sim/wgfmu.py`), the binding (`transport/wgfmu/dll.py` is the only `ctypes` module:
   `tests/unit/test_lint_ctypes.py`, `tests/adapters/test_windows_readiness.py`), a field of `Bus` set by
   `make_bus`, a transaction phase that owns the library session (`session/wgfmu_phase.py`: FLEX lock released,
   relocked at its exit), a `doctor` check of the installed library and fake-ABI tests (`tests/wgfmu_abi/`).
7. **Transaction, recovery and probe.** The family's stop and zero step and its verification in the cleanup
   (`session/transaction.py`, `run_cleanup`; blueprint v2 2.6 order: abort, SPGU stop, WGFMU safe state, zero,
   switches to rest, disconnect, verify), also run by `safe_shutdown` and the in-flight recovery on every mainframe
   that has the module; the `LiveState` fields its rules read (`models/station.py`, filled by the snapshot); its
   read-only checks in the probe (`service/probe.py`, queries only) and, when it holds state the human records,
   in `b1500 doctor` (`devtools/doctor.py`).
8. **Rules.** `rules/builtin/<family>.py`, imported in `rules/builtin/__init__.py` at its place in the rule table
   (import order = registration order = finding order), thresholds only from the policy, the DUT profile or the
   module spec; the rule row in [safety-model.md](safety-model.md) and in `MODULE_RULES` of `devtools/coverage.py`.
   New confirmation reasons go to `ConfirmReason` (`models/common.py`) and the plan summary (`rules/tiers.py`).
9. **Kind and recipes.** A kind in `catalog/kinds/<family>_<shape>.py` registered in `default_kinds()`
   (`catalog/kinds/__init__.py`), with its compiled envelope, routes per phase, source plan, estimate and
   checkpoints (long kinds: `tx.checkpoint` per segment, `tx.check_abort` at least once a second); recipes in
   `recipes/<prefix>/<name>.yaml` (`uv run b1500 dev recipe-check`); analyses registered in `ANALYSIS_METHODS`
   (`analysis/registry.py`) with their family tags. A recipe is `sim_validated` only when its integration test
   against model truth passes (`tests/integration`).
10. **Skills.** A card folder `.agents/skills/b1500-test/cards/<family>/` (frontmatter v2, the ten sections, an
    example plan per card that lint validates on its scenario), then `uv run b1500 dev gen-index`; a family row in
    the entry skill's router; a knowledge file (≤ 300 lines); runbooks in `b1500-debug` and a row of its symptom
    router; the family's bring-up stage file (`.agents/skills/b1500-bringup/stages/`, its `TODO(verify)` line naming
    the blueprint §7.6 items it settles; a new stage also needs `models/validation.py` `STAGES` and an `hw_l<n>`
    marker); then `uv run b1500 dev sync-harness` and `uv run b1500 dev lint-skills`.
11. **Coverage and examples.** The module row in `MODULES` and its modes in `MODES` (`devtools/coverage.py`), the
    legacy ledger rows mapped or out of scope with a reason (`scripts/build_driver_map.py`, `LEDGER_FAMILIES`,
    `--check`), `uv run b1500 dev coverage --write`; the module in `config/station.example.yaml` (unproven wiring
    `null`, `certainty: unverified`), example pin maps and DUT profiles with the `pulse`/`ac` envelopes its terminals
    need (`b1500 doctor` reports a pin-map terminal without one).
12. **Safety and visa-loop rows** (WP11.3): a body per family path of each new kind in
    `tests/safety/global_matrix.py` (`BODIES`; the matrix test fails while a registered kind has none or a
    fault/position cell has neither a running body nor a written reason), and a `..._on_backend_visa...` run test
    parametrized over each new recipe's case (`tests/visa_loop/cases.py` collects them; the registry coverage test
    fails for a recipe without one); a pytest marker `<family>` in `pyproject.toml` on the family's test files; the
    acceptance scenarios that exercise it carry `tags: [<family>]`.

## A measurement, end to end

1. **Plan.** `validate_plan` resolves the recipe and parameters, binds roles to channels through the pin map,
   compiles the envelope, estimate and exact FLEX preview, evaluates plan-phase rules, and stores a frozen
   `PlanRecord` whose id is derived from its hash. It returns the tier and a canonical one-line summary. No source
   command is sent.
2. **Run.** `run_plan` / `run_confirmed_plan` reload the plan, re-check tier and summary without any I/O, then open
   a transaction: fault-latch check, lock, in-flight marker, live-state rules, guarded acquisition. A plan longer
   than `run_limits.max_sync_run_s` runs asynchronously: the call returns `running` as soon as the transaction holds
   the instrument, a worker thread runs the kind, which reports progress (`progress.json`, `partial.csv`) at its
   checkpoints, and `safe_shutdown` from any process stops it at the next checkpoint (abort file).
3. **Cleanup.** Whatever happens (including exceptions, interrupts and a cancel) the transaction aborts if needed,
   stops an active SPGU output, brings the WGFMU to its safe state, zeroes, returns every declared switch to rest,
   disconnects, drains errors and verifies the outputs are off and the switches at rest (`LOP?` with its positive
   control on hardware); if that cannot be verified, the fault latch is set and every further sourcing path refuses
   until a human clears it after a verified `safe_shutdown`.
4. **Archive and analyze.** Raw blocks are stored even on failure; the parsed table, quality report and default
   analyses are written to the run folder, which only the server writes.

## Files and locations

Everything lives in the repository clone (owner decision D1): `.venv/` (uv), `data/runs/` and `data/state/`
(server-written archive, plans, locks, fault latch, simulator state, MFCMU correction records), `config/local/` (live
configuration, edited by a human only) and `work/` (agent scratch for ad-hoc analysis and ad-hoc waveform CSVs in
`work/waveforms/`). All four are gitignored. Configuration resolves `B1500_CONFIG_DIR` (tests and the M3 runner only)
→ `config/local/<file>` → `config/<file>.example.yaml`; the visa backend never falls back to examples. The lab PC
runs the same clone.

## Configuration (v2, WP5.3)

`b1500 config check` validates every file below (schema errors, R-CFG-01 and the cross-file checks) and exits 0 only
when the configuration is valid. The committed examples are lab-shaped (blueprint v2 §1.1, §7.3): they mirror the
inventory the lab's own `UNT?` snapshot recorded and leave every unproven wiring fact `null`/`unverified`.

| File | Model | Content |
|---|---|---|
| `settings.yaml` | `models.station.Settings` | backend (`sim`/`visa`), sim scenario, VISA resource, `wgfmu.library` (empty = the library's 64-bit `System32\wgfmu.dll`), paths |
| `station.yaml` | `models.station.StationProfile` | modules per slot (lab example: SPGU1 1, WGFMU1 2, SMU3/SMU4 HRSMU, SMU5/SMU6 MPSMU, CMU1 7), interlock, topology (shield, Guard, Kelvin, cables), `switches`, `corrections` |
| `policy.yaml` | `models.policy.Policy` | hard/soft limits, interlock threshold, per-family `run_limits` (`max_points.{smu,cmu,wgfmu}`; an integer still works and caps all), `pulse` and `cmu` soft bands, required `corrections` and their age, plan TTL, quality classes |
| `pinmaps/<name>.yaml` | `models.station.PinMap` | DUT terminal → channel, `GNDU`, MFCMU side (`7H`/`7L`) or switch output (`SEL1.OUT1`); `certainty` |
| `duts/<name>.yaml` | `models.policy.DutProfile` | per terminal: max \|V\|, max \|I\|, `impedance` (`unknown`/`high_z`/`resistive`), `min_series_ohm`, `pulse` and `ac` envelopes; `geometry` (analysis only) |
| `sim/scenarios/<name>.yaml` | `models.station.SimScenario` | simulated mainframe (lab layout), DUT wiring (channel, `GNDU`, MFCMU side `7H`/`7L` or 16440A output `SELPORT0`-`3`; `scuu: [7]` puts an SCUU on the MFCMU in slot 7, whose sides then are the SCUU outputs; `selectors: {0: {smu: 3, pgu: 101}}` cables the selector inputs, WP9.2) and device truth |

- **Switches** (`models/routing.py`): `SwitchSpec{id, kind (selector_16440a, scuu, asu, rsu), present (true/false/
  null = unknown), certainty, ports: {output → {index, inputs: {smu|pgu|cmu|wgfmu → channel or null}}}, rest}`. The
  station validates each input against the module type that can feed it, unique ERSSP ports (0-3) across the two
  selectors, RSU index = its WGFMU channel, SCUU/ASU index = its SMU, `pgu_open` only on selector CH 1 (ports 0, 2)
  and a `rest` state every output can take. A pin-map switch target that names an undeclared switch or output is
  `invalid_config`; channel and MFCMU-side targets without a fitting module only warn (R-PIN-01 blocks the plans).
- **Binding**: a role reaches a switch output through the route `(switch, output, state = its resource)`; the planner
  binds it to the channel recorded on that input (none while `null`). Only kinds that set the route
  (`envelope.routes`) can use such a terminal; the v1 SMU kinds cannot (R-PIN-01).
- **Corrections**: `station.yaml#corrections.<MFCMU alias>.load` holds only the static load-standard reference
  (`DCORR`); correction records (`CorrectionRecord`: kind, frequencies, run, time, IDN, pin-map and station sha256,
  `CORRST?` state) are server state under `data/state/corrections/<alias>.json` (`archive/corrections.py`:
  `records_for`, `freshness`).
- **`file` parameters**: a recipe parameter of type `file` names a CSV in `recipes/waveforms/` (committed library,
  `tier ok` possible) or `work/waveforms/` (ad-hoc, always `adhoc_recipe`); at most 1 MiB; the planner stores its
  sha256 in the plan (so the plan hash follows the content) and every run re-checks it (`plan_stale` otherwise).

## Agent integration

`AGENTS.md` is the canonical agent instruction file (Codex reads it directly; Claude Code reads `CLAUDE.md`, which
imports it). Nested `AGENTS.md`/`CLAUDE.md` pairs in `driver/`, `analysis/` and `transport/wgfmu/` hold
layer-specific rules. The three skills (`b1500-test` with the test cards and knowledge files, `b1500-debug` with the
runbooks, `b1500-bringup` with the stage files) are canonical in `.agents/skills/` (Codex) and copied to
`.claude/skills/` by `b1500 dev sync-harness` with a drift test; the always-loaded text (both instruction files and
the three skill descriptions) stays within 2,500 tokens. Harness configuration (`.codex/config.toml`, `.mcp.json`) is generated per machine by `b1500 harness init`
from the templates in `config/harness/` (WP1.9); only examples, `.claude/settings.json`, the Codex rules and the
guard hook are committed. Both configs start the same entry point (`uv run --frozen --project <clone> b1500-mcp`);
`run_confirmed_plan` always asks the human (Codex `prompt`, Claude Code `ask`), `run_plan` and `safe_shutdown`
never do. The read-only `b1500 manual …` and `b1500 bringup …` commands run without a prompt; the configuration
bootstrap (`b1500 config init|adopt`) is denied to agents (owner decision OD-5,
[deployment-windows.md](deployment-windows.md) §"Harness permissions").
