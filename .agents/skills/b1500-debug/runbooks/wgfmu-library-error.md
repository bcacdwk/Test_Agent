---
id: wgfmu-library-error
title: WGFMU instrument library or session error (instrument_error, transport_error, 30xx/33xx codes)
maturity: seed
sources: [blueprint v2 0 decision 6 (x64 library since A.03.00, Keysight release notes 9018-80226), blueprint v2 2.4 (WgfmuApi, WgfmuError), 2.6 (WGFMU phase, cleanup step 3), 2.8 (R-WG-01, R-WG-02), WG p152 (4-82) "Operation Error", WG p153 (4-83) "3301", WG p97 (4-27) "getError", WG p19 (1-7) "RSU"]
---

# WGFMU instrument library or session error

## Symptom

- A WGFMU run (`wgfmu.*`, kind `wgfmu_waveform`) ends `failed` with `instrument_error` or `transport_error` and a
  message naming a library function and a code (`WgfmuError ... 3001 ...`, `... 3310 ...`, rc -5).
- `validate_plan` blocked by R-WG-01: library not loadable (32-bit `wgfmu.dll`, not found), channels not among the
  library's channel ids, a WGFMU role not on its RSU.
- `station_status`: the WGFMU library line is not loadable; a run left `cleanup_unverified` after a WGFMU phase.
- A completed run with `kind_result.wgfmu_warnings` > 0: the library's warning summary (`wgfmu_warning_text`; WG
  p138 (4-68) Table 4-4: severe = an event overwrote another or a measurement call hit a non-Fast-IV/PG channel,
  normal = no such channel, a short buffer, the instrument error queue not empty). A warning never stops a run.

## Likely causes

1. Library / session (visa): the x64 library missing or 32-bit (the x64 DLL ships since A.03.00, Keysight release
   notes 9018-80226 via blueprint v2 0 decision 6; the lab PC's installed version is recorded at bring-up,
   `TODO(verify)[L0.A2]`); another program (EasyEXPERT) holds the session; the FLEX link still held the exclusive
   lock (the transaction releases it; ATV-14).
2. 3000/3001: wrong channel number, or the RSU of that channel not cabled to the WGFMU (WG p152 (4-82)).
3. 33xx setup errors at execute: a level outside the force range (3301/3310), current measurement in PG mode
   (3303), vector, sequence or waveform data too large (3304, 3305, 3307), waveform data empty (3306)
   (WG p153 (4-83)). R-WG-02 blocks these at validation; seeing one at run time means the library and the rules
   disagree (record it).
4. 3015/3050-3052 run-time errors: data corrupted, memory overflow (runbook `wgfmu-memory-budget`), averaging or
   range changes too close together.
5. A hung call (session timeout): the cleanup aborted and initialized the module.

## First safe checks

1. `get_run(run_id, include=[summary, audit])`: the failing library call (`wgfmu_call` events: function, rc,
   error text; `WGFMU_getWarningSummary` keeps the warnings), the phase checkpoints (`wgfmu_phase`,
   `wgfmu_phase_end`) and whether the cleanup verified. A severe warning: report no value from that run.
2. `station_status`: WGFMU library probe (path, x64, version), fault latch, active run, RSU states.
3. On visa: `uv run b1500 doctor` (library check) and, with the human's go, `uv run b1500 doctor --probe
   --wgfmu-session` (read-only: open, channel ids, status, close).
4. Re-validate the same request: a rule finding now (R-WG-01/02) names the cause without touching the instrument.

## Physical checks to ask the human

- Is the RSU of each channel cabled to its WGFMU channel (201 -> RSU201) and mounted near the probes?
- Is EasyEXPERT closed (File > Exit, "Start EasyEXPERT" left shown)? Is the WGFMU library installed (version)?
- Front panel: is the WGFMU module listed; any error LED?

## Do not

- Load `wgfmu.dll` yourself (ctypes or any script), call library functions or send FLEX around the tools.
- Install, copy or replace the library; edit `settings.wgfmu.library` or any `config/local` file.
- Shorten a waveform, drop events or change ranges to "make the error go away" without a new validated plan.

## Stop and call safe_shutdown

- The cleanup is unverified or the fault latch is set (runbook `cleanup-failed-fault`).
- A 3001 (RSU) or 3000 (module) error, or the same run-time error twice: hand over to the human.
