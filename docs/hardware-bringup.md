# Hardware bring-up (overview)

The staged first contact with the real B1500A on the lab PC (blueprint v2 7.4, 7.5; v2.1 plan §4), after
[deployment-windows.md](deployment-windows.md). This page is the overview; the procedure itself lives in one place,
the stage files of skill `b1500-bringup` (`.agents/skills/b1500-bringup/stages/`), which the agent follows with the
owner and the owner can read directly, put in execution order by its step sequence `steps.yaml`.

## Stages

Strictly in order; a stage starts only after the previous one is signed off. Nothing has run on hardware yet.

| Stage | Goal | Stage file | Records |
|---|---|---|---|
| S0 | interlock, shield box, cables, EasyEXPERT records, GPIB 17, EasyEXPERT exited | [s0-physical](../.agents/skills/b1500-bringup/stages/s0-physical.md) | `stage-s0` |
| L0 | read-only probe, station proposal (ASU/SCUU presence), configuration adopted by the human | [l0-probe-config](../.agents/skills/b1500-bringup/stages/l0-probe-config.md) | `stage-l0` |
| L1 | zero check (0 V per SMU, floor per range), cleanup verified, mid-run stop, CLI and MCP coexist, self-test/cal (FLEX) | [l1-smu-zero](../.agents/skills/b1500-bringup/stages/l1-smu-zero.md) | `stage-l1`, `system.zero_check`, `system.self_test`, `system.self_cal` |
| L2 | known resistors against a DMM (sweep, multi-channel, spot), 1 Ohm four-wire and two-wire | [l2-resistors](../.agents/skills/b1500-bringup/stages/l2-resistors.md) | `basic.contact_resistor`, `generic.smu_multi_sweep`, `generic.smu_spot`, `resistor.kelvin_4w` |
| L3 | known diode, voltage and current forcing | [l3-diode](../.agents/skills/b1500-bringup/stages/l3-diode.md) | `basic.diode_iv`, `basic.iv_force_i` |
| L4 | known-good MOSFET against EasyEXPERT, the approval prompt | [l4-mosfet](../.agents/skills/b1500-bringup/stages/l4-mosfet.md) | `mosfet.idvg`, `mosfet.idvd`, `mosfet.gate_leakage`, `mosfet.idvg_family`, `mosfet.idvg_sync`, `mosfet.body_effect` |
| L5 | SMU advanced: pulsed vs DC, sampling time grid and log sampling, Vth by search | [l5-smu-advanced](../.agents/skills/b1500-bringup/stages/l5-smu-advanced.md) | `mosfet.idvg_pulsed`, `mosfet.idvd_pulsed`, `basic.pulsed_spot`, `generic.smu_multi_pulsed`, `mosfet.id_t_sampling`, `generic.smu_sampling`, `mosfet.vth_search` |
| L6 | CMU: phase compensation and open/short (the human lifts and lands), known capacitor, MOS-C C-V and variants, QSCV and Dit (SCUU same landing), split C-V, FeCap butterfly | [l6-cmu](../.agents/skills/b1500-bringup/stages/l6-cmu.md) | `stage-l6`, `cmu.phase_compensation`, `cmu.correction_open`, `cmu.correction_short`, `cmu.correction_load`, `cmu.spot`, `moscap.cv`, `moscap.cv_ac_level`, `moscap.pulsed_cv`, `moscap.cf`, `moscap.ct`, `moscap.cv_multi_freq`, `moscap.qscv`, `mosfet.cgc_cv`, `mosfet.cgd_cv`, `fecap.cv_butterfly` |
| L7 | 16440A selector check, wiring record and `ERSSP?` negative control, SPGU pulses into 1 MOhm (scope), FeFET read window and program/read, switching kinetics, charge pumping | [l7-spgu-selector](../.agents/skills/b1500-bringup/stages/l7-spgu-selector.md) | `stage-l7`, `system.selector_check`, `spgu.pulse_train`, `spgu.alwg_sequence`, `fefet.dual_sweep_mw`, `fefet.pulse_write_read`, `spgu.program_smu_read`, `fefet.switching_kinetics`, `mosfet.charge_pumping` |
| L8 | WGFMU + RSU: library session, library self-test/cal, DC into 100 kOhm through the RSU (+-3 %), pulsed vs DC Id-Vg, fast ramp and pulse train, the lab's waveform files, RTN/LFN, the SMU bias across `initialize` (ATV-17), FeCap PUND, fast FeFET program/read | [l8-wgfmu](../.agents/skills/b1500-bringup/stages/l8-wgfmu.md) | `stage-l8`, `system.wgfmu_self_test`, `system.wgfmu_self_cal`, `wgfmu.dc_spot`, `wgfmu.pulsed_iv`, `wgfmu.fast_iv`, `wgfmu.pulse_train`, `wgfmu.custom_waveform`, `wgfmu.rtn`, `wgfmu.lfn`, `fecap.pund`, `fefet.fast_program_read` |
| L9 | long runs: async runs, cancel and kill-recovery drills per bus, stress and breakdown recipes, FeFET endurance and retention, fast BTI, FeCap endurance, the timer over hours, the correction drift | [l9-long-runs](../.agents/skills/b1500-bringup/stages/l9-long-runs.md) | `stage-l9`, `reliability.bti_sms`, `igzo.bias_stress`, `reliability.hci`, `reliability.silc`, `reliability.tddb_cvs`, `dielectric.bdv`, `basic.breakdown_search`, `fefet.endurance`, `fefet.retention`, `wgfmu.fast_bti`, `fecap.endurance_pund` |
| L10 | session end during an async run, acceptance prompts on hardware, records reviewed and transferred | [l10-harness-handoff](../.agents/skills/b1500-bringup/stages/l10-harness-handoff.md) | `stage-l10` |

Six sections each: Preconditions, Physical steps (human), Agent steps, Expected values (checks, tolerances and one
`TODO(verify)` line: the §7.6 items the stage settles, the [roadmap](roadmap.md)'s M12 table), Abort criteria, Record.

## Steps, ledger and sessions

`steps.yaml` lists every numbered item of the stage files in execution order (who, how it is verified, the checks it
feeds), plus the deployment steps D1-D12 and each session's start (R1-R4) and end (E1-E5). Three verbs walk it:
`uv run b1500 bringup next` (read-only: the next step, its expected values, the exact `done` line, the abort route, the
`batch` one call can record), `uv run b1500 bringup done STEP [STEP ...]` (verifies each step now and appends pass or
fail, one entry per step, to the step ledger `data\state\bringup\` that only it writes; a failure ends the call; human
steps carry the owner's own words) and `uv run b1500 bringup check --all` (re-verifies the ledger; exit 1 on a gap).
Signed = every step passed and the records reviewed (`uv run b1500 bringup status` shows `steps a/b` per stage). Nine
sessions, each opened by R1-R4 and closed by E1-E5: 0 deployment (D1-D12); 1 S0, L0; 2 L1-L3; 3 L4, L5; 4 L6; 5 L7; 6
L8; 7 L9 (a full day, the harness kept open); 8 L10 with the review and the transfer (real durations: the ledger).
`uv run b1500 bringup capture H... probe` writes anonymized golden fixtures (the `tests/fixtures/flex/` format, the
`*IDN?` serial replaced by 0; also the ASU/SCUU `*LRN?` answers, `CORRL?`/`DCORR?`/`CORRDT?` and the WGFMU library's
strings); `uv run b1500 bringup record L2 --run H... --reference r_dmm=99870 --operator NAME` drafts a record (with the
audit's timings and the stage's steps) from hardware runs only; the owner reviews both
([validation/hw/README.md](../validation/hw/README.md); `uv run b1500 dev recipe-check`).

## Who does what

- **The owner** does every physical step (cabling, probes, EasyEXPERT, external meters, power cycles) and runs the
  human-only commands in their own PowerShell window: `uv run b1500 config init --visa` (D7),
  `uv run b1500 config adopt work/bringup/station.proposed.yaml --as station` (and `--as pinmap|dut` for the
  agent's proposals), `uv run b1500 run --confirm PLAN_ID` (L1 drill) and `uv run b1500 fault clear --by NAME`.
- **The agent** probes read-only (`uv run b1500 doctor --probe`), proposes configuration
  (`uv run b1500 bringup propose-station`, files under `work/bringup/`), runs validated plans after the owner's
  consent in chat, records the steps, captures fixtures and drafts records. It never writes `config/local/` or
  `validation/hw/`. Start it with: "Use skill b1500-bringup and continue the hardware bring-up from the current stage."

## CLI and harness coexist

Every `b1500` call opens the VISA session with its exclusive lock and closes it before it returns (blueprint v2 2.4),
so an idle Codex or Claude Code session holds nothing and `uv run b1500 status` works in another window; a program that
keeps the instrument (EasyEXPERT, another VISA tool) makes a call answer `busy`. L0 and L1 check this.

## If cleanup fails

A run reports cleanup `unverified`, or `uv run b1500 status` shows a latched fault: check the front panel and the
DUT, run `uv run b1500 lock status`, then `uv run b1500 shutdown --reason "WHY"`. When the shutdown reports a
verified cleanup and an empty error queue, the owner clears the latch (`uv run b1500 fault clear --by NAME`). Never
delete files under `data\state\` by hand. Last resort, when no software reaches the instrument: switch it off.

## Rehearsal on the simulator

The same steps run on the simulator (`lab_station`: acceptance scenario S17; the whole sequence: tests marked
`rehearsal`) on a separate ledger that never signs a stage: every value SIMULATED, nothing drafted or captured.

## Hardware tests (end of each session, step E2)

`tests/hardware/` only reads: the probe and every record (`H...` runs, unchanged files, digests, cleanups, reviewer,
steps). `$env:B1500_HW = "1"; uv run pytest -m hardware -rs` (one stage: `-m "hardware and hw_l1"`); without
`B1500_HW=1` and backend visa every test skips and the summary says `HARDWARE SUITE NOT RUN`: not a pass.
