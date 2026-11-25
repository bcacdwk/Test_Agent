# Hardware bring-up (overview)

The staged first contact with the real B1500A on the lab PC (blueprint v2 7.4, 7.5). This page is the overview;
the procedure itself lives in one place, the stage files of skill `b1500-bringup`
(`.agents/skills/b1500-bringup/stages/`), which the coding agent follows with the owner and which the owner can
read directly. The lab PC is prepared with [deployment-windows.md](deployment-windows.md) first.

## Stages

Strictly in order; a stage starts only after the previous one is signed off. Nothing has run on hardware yet.

| Stage | Goal | Stage file | Records |
|---|---|---|---|
| S0 | interlock, shield box, cables, EasyEXPERT records, GPIB 17, EasyEXPERT exited | [s0-physical](../.agents/skills/b1500-bringup/stages/s0-physical.md) | `stage-s0` |
| L0 | read-only probe, station proposal, configuration adopted by the human | [l0-probe-config](../.agents/skills/b1500-bringup/stages/l0-probe-config.md) | `stage-l0` |
| L1 | zero check (0 V per SMU, floor per range), cleanup verified, mid-run stop, CLI and MCP coexist, self-test/cal (FLEX) | [l1-smu-zero](../.agents/skills/b1500-bringup/stages/l1-smu-zero.md) | `stage-l1`, `system.zero_check`, `system.self_test`, `system.self_cal` |
| L2 | known resistors against a DMM (sweep and spot), 1 Ohm four-wire | [l2-resistors](../.agents/skills/b1500-bringup/stages/l2-resistors.md) | `basic.contact_resistor`, `generic.smu_spot`, `resistor.kelvin_4w` |
| L3 | known diode | [l3-diode](../.agents/skills/b1500-bringup/stages/l3-diode.md) | `basic.diode_iv` |
| L4 | known-good MOSFET against EasyEXPERT | [l4-mosfet](../.agents/skills/b1500-bringup/stages/l4-mosfet.md) | `mosfet.idvg`, `mosfet.idvd`, `mosfet.gate_leakage` |
| L5 | SMU advanced: pulsed vs DC, sampling time grid, Vth by search | [l5-smu-advanced](../.agents/skills/b1500-bringup/stages/l5-smu-advanced.md) | `mosfet.idvg_pulsed`, `mosfet.idvd_pulsed`, `basic.pulsed_spot`, `generic.smu_multi_pulsed`, `mosfet.id_t_sampling`, `generic.smu_sampling`, `mosfet.vth_search` |
| L6 | CMU: phase compensation and open/short (the human lifts and lands), known capacitor, MOS-C C-V and variants, QSCV and Dit (SCUU same landing), split C-V, FeCap butterfly | [l6-cmu](../.agents/skills/b1500-bringup/stages/l6-cmu.md) | `stage-l6`, `cmu.phase_compensation`, `cmu.correction_open`, `cmu.correction_short`, `cmu.correction_load`, `cmu.spot`, `moscap.cv`, `moscap.cv_ac_level`, `moscap.pulsed_cv`, `moscap.cf`, `moscap.ct`, `moscap.cv_multi_freq`, `moscap.qscv`, `mosfet.cgc_cv`, `mosfet.cgd_cv`, `fecap.cv_butterfly` |
| L7 | 16440A selector check and wiring record, SPGU pulses into 1 MOhm (scope), FeFET program/read against the dual sweep, switching kinetics, charge pumping | [l7-spgu-selector](../.agents/skills/b1500-bringup/stages/l7-spgu-selector.md) | `stage-l7`, `system.selector_check`, `spgu.pulse_train`, `spgu.alwg_sequence`, `fefet.dual_sweep_mw`, `fefet.pulse_write_read`, `spgu.program_smu_read`, `fefet.switching_kinetics`, `mosfet.charge_pumping` |
| L8 | WGFMU + RSU: library session, library self-test/cal, DC into 100 kOhm through the RSU (+-3 %), pulsed vs DC Id-Vg, fast ramp and pulse train, the lab's waveform files, RTN/LFN, FeCap PUND, fast FeFET program/read | [l8-wgfmu](../.agents/skills/b1500-bringup/stages/l8-wgfmu.md) | `stage-l8`, `system.wgfmu_self_test`, `system.wgfmu_self_cal`, `wgfmu.dc_spot`, `wgfmu.pulsed_iv`, `wgfmu.fast_iv`, `wgfmu.pulse_train`, `wgfmu.custom_waveform`, `wgfmu.rtn`, `wgfmu.lfn`, `fecap.pund`, `fefet.fast_program_read` |
| L9 | long runs: async runs, cancel and kill-recovery drills per bus (SMU, SPGU, WGFMU), stress and breakdown recipes, FeFET endurance and retention, WGFMU fast BTI, FeCap endurance by PUND | [l9-long-runs](../.agents/skills/b1500-bringup/stages/l9-long-runs.md) | `stage-l9`, `reliability.bti_sms`, `igzo.bias_stress`, `reliability.hci`, `reliability.silc`, `reliability.tddb_cvs`, `dielectric.bdv`, `basic.breakdown_search`, `fefet.endurance`, `fefet.retention`, `wgfmu.fast_bti`, `fecap.endurance_pund` |
| L10 | acceptance prompts on hardware, records reviewed and transferred | [l10-harness-handoff](../.agents/skills/b1500-bringup/stages/l10-harness-handoff.md) | `stage-l10` |

Each stage file has the same six sections: Preconditions, Physical steps (human), Agent steps, Expected values
(with machine-readable checks and tolerances), Abort criteria, Record.

## Who does what

- **The owner** does every physical step (cabling, probes, EasyEXPERT, external meters) and runs the human-only
  commands in their own PowerShell window: `uv run b1500 config init --visa`,
  `uv run b1500 config adopt work/bringup/station.proposed.yaml --as station` (and `--as pinmap|dut` for the
  agent's proposals), `uv run b1500 run --confirm PLAN_ID` (L1 drill) and `uv run b1500 fault clear --by NAME`.
- **The agent** probes read-only (`uv run b1500 doctor --probe`), proposes configuration
  (`uv run b1500 bringup propose-station`, files under `work/bringup/`), runs validated plans after the owner's
  consent in chat, captures fixtures and drafts records. It never writes `config/local/` or `validation/hw/`.
- Start the agent with: "Use skill b1500-bringup and continue the hardware bring-up from the current stage."

## Progress, fixtures and records

- `uv run b1500 bringup status`: every stage with the records it needs, reviewed or drafted, and the next stage.
- `uv run b1500 bringup capture H... probe`: anonymized golden fixtures (the `tests/fixtures/flex/` format, the
  `*IDN?` serial replaced by 0) of hardware runs and the newest probe record in `work/bringup/fixtures/`.
- `uv run b1500 bringup record L2 --run H... --reference r_dmm=99870 --operator NAME`: a draft validation record
  in `work/bringup/records/` from hardware runs only; simulator runs (`S...`) and a simulator station are refused.
- The owner reviews drafts and fixtures, moves them to `validation/hw/` and `tests/fixtures/hw/` and transfers
  them (OD-7); [validation/hw/README.md](../validation/hw/README.md) describes the review and the promotion rule
  that `uv run b1500 dev recipe-check` enforces.

## CLI and harness coexist

Every `b1500` call opens the VISA session with its exclusive lock and closes it before it returns (blueprint v2 2.4),
so an idle Codex or Claude Code session holds nothing and `uv run b1500 status` works in another window; a program that
keeps the instrument (EasyEXPERT, another VISA tool) makes a call answer `busy`. L0 and L1 check this.

## If cleanup fails

A run reports cleanup `unverified`, or `uv run b1500 status` shows a latched fault: check the front panel and the
DUT, run `uv run b1500 lock status`, then `uv run b1500 shutdown --reason "WHY"`. When the shutdown reports a
verified cleanup and an empty error queue, the owner clears the latch (`uv run b1500 fault clear --by NAME`; it
runs another verified shutdown first). Never delete files under `data\state\` by hand. Last resort, when the
software cannot reach the instrument and an output may still be on: switch the B1500A off.

## Rehearsal on the simulator

The same stages run against the simulator scenario `lab_station` (acceptance scenario S17): every value is SIMULATED,
the physical steps may be answered with "done", and no record, fixture or `validation/hw/` file comes from it.

## Hardware tests (end of day)

`tests/hardware/` only reads (blueprint v2 decision 24): stage L0 re-runs the read-only probe (B1500A identity, `UNT?`
= `config/local/station.yaml`, error queue drained, `LOP?` all off, selector outputs at rest, `SPST?` = 0, MFCMU
corrections readable, queries only) and each stage checks its records in `validation/hw/` and `work/bringup/records/`
(schema, `H...` runs present in `data/runs` on visa with unchanged files, current recipe digest, `LOP?`-verified
cleanups and passing positive controls behind every passing record, a reviewer on every `validation/hw/` record).
On the lab PC after the review (7.5 step 10): `$env:B1500_HW = "1"; uv run pytest -m hardware -rs`; one stage:
`uv run pytest -m "hardware and hw_l1" -rs`. Without `B1500_HW=1` and backend visa every test skips and the summary
says `HARDWARE SUITE NOT RUN`: nothing was checked, which is not a pass.
