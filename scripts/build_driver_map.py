"""Build `references/driver-map/flex-driver-map.yaml` from the legacy v0.2 fake MCP sources.

The legacy package `src/b1500_test_agent/mcp/` (282 atoms, 97 flows) is read from the git tag
`archive/v0.2-fake-mcp` by default (or from a working-tree directory with `--source-dir`) and parsed with
`ast` only; the legacy modules are never imported. Every A/B/C atom's FLEX basis is the second argument of
its `_fake_response` call (C atoms pass it through `_c_response`, whose third argument is forwarded as that
second argument); D atoms take theirs from the `_SPECS` catalog. Each atom is mapped onto the new
`B1500Driver` methods / `driver/flex/` builders of blueprint §2.3, or marked `unmapped`. Manual pages of
commands that the summary lists only in its grouped index come from `GROUPED_PAGES` (read from the Programming
Guide by WP1.3; the same pages are cited in the builder docstrings of `driver/flex/`).

Usage (from the repo root):
    uv run python scripts/build_driver_map.py            # regenerate the YAML
    uv run python scripts/build_driver_map.py --check    # verify counts, coverage and that the file is current
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REF = "archive/v0.2-fake-mcp"
LEGACY_PACKAGE = "src/b1500_test_agent/mcp"
COMMAND_SUMMARY = "references/manuals/structured/b1500a-command-summary.yaml"
DEFAULT_OUTPUT = "references/driver-map/flex-driver-map.yaml"
SCHEMA_VERSION = 1

ATOM_CLASSES = ("A", "B", "C", "D")
EXPECTED_ATOMS = {"A": 82, "B": 59, "C": 99, "D": 42}
EXPECTED_ATOM_TOTAL = 282
# Registration order of the legacy server (`server.py`): A, B, C atoms/flows, then AB, D, CD.
FLOW_CLASSES = ("A", "B", "C", "AB", "D", "CD")
EXPECTED_FLOWS = {"A": 20, "B": 16, "C": 31, "AB": 19, "D": 7, "CD": 4}
EXPECTED_FLOW_TOTAL = 97

UNMAPPED = "unmapped"
PRIORITIES = ("m1", "m2", "later")
PRIORITY_SCALE = {
    "m1": "M1 vertical path (status -> validate -> staircase Id-Vg -> archive -> Vth), safe_shutdown cleanup "
    "and system.* self-test/self-cal; the B1500Driver methods of blueprint section 2.3; v2 additions mapped since "
    "(CM and *LRN? by WP5.6, the read-only probe queries ERMOD?, ERSSP?, SPST?, CORRST?, ADJ? by WP6.1, the SMU "
    "sampling MM 10 with MCC, ML, MT, MSC, MV, MI and the time stamps TSC/TSR by WP7.4, the sweep sources DI, WI, "
    "WSV, WSI, WNX and MM 16 by WP7.2, MM 1 spot and the ASU commands SAP, SAR, SAL by WP7.1, the MFCMU commands, "
    "MM 17-26 and the SCUU's SSP/SSL by WP8.1, the correction set-up queries CORRL?/DCORR? by WP8.2, the HV-SPGU "
    "PG/ALWG commands by WP9.1, the 16440A selector settings ERMOD/ERSSP by WP9.2, the SMU pulsed modes MM 3, 4, 5, "
    "27, 28 with PT, PV, PI, PWV, PWI, MCPT, MCPNT, MCPNX, MCPWS, MCPWNX by WP7.3)",
    "m2": "M2 SMU recipe pack (six cards, stepped and double sweeps, M2 analysis methods) and the rest of the "
    "simulator's FLEX subset v1 (AV, BC, NUB?, TSC)",
    "later": "reserved: not_implemented recipes and M4+ (pulse, sampling, search, CMU/QSCV, WGFMU, SPGU, HV/HC "
    "units and expanders, ASU/SCUU, selectors, EasyEXPERT, timestamps, program memory, ...)",
}

# --- Target vocabulary (blueprint section 2.3) -------------------------------------------------------------
DRIVER_METHODS = (
    "identify", "modules", "errors", "status_byte", "output_state", "abort", "zero", "disconnect", "reset",
    "self_test", "self_calibrate", "set_format", "set_integration", "set_range", "enable", "force_v", "force_i",
    "staircase_v", "staircase", "execute_and_read", "wait_complete", "auto_calibration", "set_auto_calibration",
    "selector_control_mode", "selector_state", "pulse_output_active", "correction_enabled",
    "phase_compensation_result",
    "set_time_stamp", "reset_timer", "sampling_setup", "sampling_update",
    "spot_setup", "asu_paths", "asu_1pa_auto", "set_asu_path", "set_asu_1pa_auto", "set_asu_indicator",
    "set_impedance_model", "apply_cmu_signal", "set_cmu_range", "set_cmu_integration", "set_cmu_monitor", "spot_c",
    "cv_sweep", "cf_sweep", "ac_level_sweep", "pulsed_spot_c", "pulsed_cv_sweep", "ct_sampling",
    "set_phase_compensation_mode", "set_correction_frequencies", "measure_correction", "set_correction_standard",
    "set_correction_data", "set_correction", "scuu_route", "set_scuu_indicator", "correction_frequencies",
    "correction_standard",
    "configure_spgu", "apply_pulse_setup", "start_pulses", "stop_pulses", "measure_pulse_load",
    "set_selector_control", "route_selector",
    "pulsed_setup", "pulsed_update",
)  # fmt: skip
COMMAND_BUILDERS = (
    "cn", "cl", "dz", "fmt", "mm", "cmm", "aad", "ait", "ri", "rv", "wt", "wm", "dv", "wv", "cm", "lrn_q",
    "di", "wi", "wsv", "wsi", "wnx",
    "erssp_q", "corrst_q", "adj_q", "tsc", "tsr", "mcc", "ml", "mt", "msc", "mv", "mi", "sap", "sar", "sal",
    "imp", "fc", "acv", "dcv", "rc", "act", "lmn", "wdcv", "wtdcv", "wmdcv", "wfc", "wtfc", "wmfc", "wacv", "wtacv",
    "wmacv", "pdcv", "ptdcv", "pwdcv", "mdcv", "mtdcv", "adj", "corrl", "clcorr", "corr_q", "dcorr", "corrdt",
    "corrst", "ssp", "ssl", "corrl_q", "dcorr_q",
    "sim", "spm", "spt", "spv", "spper", "sprm", "ser", "spupd", "odsw", "stgp", "corrser_q", "alw", "als",
    "ermod", "erssp",
    "XE", "AB", "IDN_Q", "UNT_Q", "ERRX_Q", "STB_Q", "OPC_Q", "LOP_Q", "RST", "TST_Q", "CAL_Q", "ERMOD_Q", "SPST_Q",
    "SRP", "SPP",
    "pt", "pv", "pi", "pwv", "pwi", "mcpt", "mcpnt", "mcpnx", "mcpws", "mcpwnx",
)  # fmt: skip
DRIVER_TARGETS = tuple(f"B1500Driver.{m}" for m in DRIVER_METHODS) + tuple(f"flex.{b}" for b in COMMAND_BUILDERS)


@dataclass(frozen=True)
class CommandTarget:
    """Where a FLEX mnemonic lives in the new driver: a `B1500Driver` method and/or a `driver/flex/` builder
    (`flex.<name>`, re-exported by `driver/flex/__init__.py`)."""

    method: str | None
    builder: str | None
    note: str | None = None

    @property
    def primary(self) -> str:
        """The method if one sends the command, else the builder."""
        return f"B1500Driver.{self.method}" if self.method else f"flex.{self.builder}"


# FLEX mnemonic -> new driver target. Every mnemonic not listed here is `unmapped`.
COMMAND_TARGETS: dict[str, CommandTarget] = {
    "*IDN?": CommandTarget("identify", "IDN_Q"),
    "UNT?": CommandTarget("modules", "UNT_Q"),
    "ERRX?": CommandTarget("errors", "ERRX_Q"),
    "*STB?": CommandTarget("status_byte", "STB_Q", "bit 3 = interlock open"),
    "LOP?": CommandTarget(
        "output_state",
        "LOP_Q",
        "ATV-1: cleanup verification; per PG Table 4-26 code 00 = output switch OFF, one code per slot (SMU/MFCMU); "
        "*LRN? 0 is the fallback only for SPGU/WGFMU subchannels",
    ),
    "AB": CommandTarget("abort", "AB", "sent alone"),
    "DZ": CommandTarget("zero", "dz"),
    "CL": CommandTarget("disconnect", "cl"),
    "*RST": CommandTarget("reset", "RST", "sent alone"),
    "*TST?": CommandTarget("self_test", "TST_Q"),
    "*CAL?": CommandTarget("self_calibrate", "CAL_Q"),
    "FMT": CommandTarget("set_format", "fmt", "FMT 1 and 5 only"),
    "AAD": CommandTarget("set_integration", "aad"),
    "AIT": CommandTarget("set_integration", "ait"),
    "RI": CommandTarget("set_range", "ri"),
    "RV": CommandTarget("set_range", "rv"),
    "CN": CommandTarget("enable", "cn"),
    "DV": CommandTarget("force_v", "dv", "OutputGuard-checked"),
    "DI": CommandTarget("force_i", "di", "OutputGuard-checked (current level vs |I|, Vcomp vs |V|); bias_i and "
                        "step_i roles (WP7.2), kind smu_spot bias_i roles (WP7.1)"),
    "MM": CommandTarget("staircase", "mm", "staircase sends MM 2 (staircase) and MM 16 (multi-channel sweep, "
                        "WP7.2), sampling_setup MM 10, spot_setup MM 1 (WP7.1), the MFCMU setups MM 17-26 (WP8.1), "
                        "pulsed_setup MM 3/4/5/27/28 (WP7.3) (MM_MODE_TARGETS); every other mode is unmapped"),
    "CMM": CommandTarget("staircase", "cmm", "sent inside the staircase, sampling and spot setups"),
    "WV": CommandTarget("staircase", "wv", "OutputGuard-checked voltage primary sweep"),
    "WI": CommandTarget("staircase", "wi", "OutputGuard-checked current primary sweep, lin/log single/double "
                        "(WP7.2)"),
    "WSV": CommandTarget("staircase", "wsv", "synchronous voltage source after WV, MM 2; sync_v roles (WP7.2)"),
    "WSI": CommandTarget("staircase", "wsi", "synchronous current source after WI, MM 2; sync_i roles (WP7.2)"),
    "WNX": CommandTarget("staircase", "wnx", "multi-channel sweep sources N = 2-10 after WV/WI, MM 16; the "
                         "second and later sweep roles of a recipe (WP7.2); MM 28 staircase sources N = 1-10 in "
                         "pulsed_setup (WP7.3)"),
    "WT": CommandTarget("staircase", "wt"),
    "WM": CommandTarget("staircase", "wm"),
    "XE": CommandTarget("execute_and_read", "XE"),
    "*OPC?": CommandTarget("wait_complete", "OPC_Q"),
    "CM": CommandTarget("set_auto_calibration", "cm", "R-CAL-02 (WP5.6): asynchronous runs send CM 0 and the "
                        "cleanup restores the state read by *LRN? 31"),
    "*LRN?": CommandTarget("auto_calibration", "lrn_q", "type 31 (CM state) before every run's pre-execute rules "
                           "(R-CAL-01/02); type 0 stays the ATV-1 fallback for SPGU/WGFMU outputs; types 62/63 = "
                           "ASU paths and 1 pA auto ranging (asu_paths, asu_1pa_auto; WP7.1)"),
    "ERMOD?": CommandTarget("selector_control_mode", "ERMOD_Q", "read-only probe (WP6.1); snapshots and the cleanup "
                            "verification read it before ERSSP? (WP9.2)"),
    "ERSSP?": CommandTarget("selector_state", "erssp_q", "read-only probe per declared selector port, only with "
                            "the 16440A control mode on (WP6.1); route read-back, pre-execute R-ROUTE-01 and cleanup "
                            "step 8 per declared port (WP9.2)"),
    "ERMOD": CommandTarget("set_selector_control", "ermod", "ERMOD 1 before every selector route and in cleanup "
                           "step 5 (ATV-18: power-on/*RST leave it off; WP9.2)"),
    "ERSSP": CommandTarget("route_selector", "erssp", "OutputGuard.check_route (16440A route open|smu|pgu|pgu_open; "
                           "PGU open on CH 1 only); apply_routes per phase, rest_switch in cleanup step 5 (WP9.2)"),
    "SPST?": CommandTarget("pulse_output_active", "SPST_Q", "read-only probe (WP6.1); cleanup step 2 (SPP when 1) "
                           "and verification, SpguOps.wait_pulses_stopped polling (WP9.1)"),
    "SIM": CommandTarget("configure_spgu", "sim", "HV-SPGU PG (0) or ALWG (1) mode, first write of every SPGU setup"),
    "SPRM": CommandTarget("configure_spgu", "sprm", "count (1) or duration (2) only; free run (0) is never built"),
    "SPPER": CommandTarget("configure_spgu", "spper", "PG mode"),
    "SER": CommandTarget("configure_spgu", "ser", "per channel in every setup; set_pulse_load changes it through "
                         "OutputGuard.check_pulse (the open-load level rises as SER falls)"),
    "SPM": CommandTarget("configure_spgu", "spm", "two-level (1/2) or three-level (3) pulses; DC (0) is not used"),
    "SPT": CommandTarget("configure_spgu", "spt", "per pulse source"),
    "SPV": CommandTarget("configure_spgu", "spv", "per pulse source; OutputGuard.check_pulse on the open-load level"),
    "ODSW": CommandTarget("configure_spgu", "odsw", "written in every setup (disabled unless the program enables it)"),
    "STGP": CommandTarget("configure_spgu", "stgp", "written in every setup"),
    "ALW": CommandTarget("configure_spgu", "alw", "ALWG pattern data block per channel (Table 2-4)"),
    "ALS": CommandTarget("configure_spgu", "als", "ALWG sequence data block (Table 2-5)"),
    "SPUPD": CommandTarget("apply_pulse_setup", "spupd", "only channels configured by this driver"),
    "SRP": CommandTarget("start_pulses", "SRP", "re-checks every applied channel against the guard"),
    "SPP": CommandTarget("stop_pulses", "SPP", "never gated; cleanup step 2"),
    "CORRSER?": CommandTarget("measure_pulse_load", "corrser_q", "mode 0 only (the guard checks every SER change)"),
    "CORRST?": CommandTarget("correction_enabled", "corrst_q", "read-only probe per installed MFCMU (WP6.1); "
                             "R-CORR-01 pre-execute: M8"),
    "ADJ?": CommandTarget("phase_compensation_result", "adj_q", "mode 0 last result (WP6.1); mode 1 measures the "
                          "compensation: measure_phase_compensation (WP8.1)"),
    "TSC": CommandTarget("set_time_stamp", "tsc", "kind smu_sampling (WP7.4): time stamps before every datum"),
    "TSR": CommandTarget("reset_timer", "tsr", "once before the first sampling trigger (immediate form only)"),
    "MCC": CommandTarget("sampling_setup", "mcc", "clears sampling sources left by an earlier program"),
    "ML": CommandTarget("sampling_setup", "ml"),
    "MT": CommandTarget("sampling_setup", "mt", "also sampling_update between the blocks of a long run"),
    "MSC": CommandTarget("sampling_setup", "msc",
                         "always MSC 2,2: automatic abort (breakdown), bias after a normal end"),
    "MV": CommandTarget("sampling_setup", "mv", "OutputGuard-checked (base and bias)"),
    "MI": CommandTarget("sampling_setup", "mi", "OutputGuard-checked (base and bias)"),
    "SAP": CommandTarget("set_asu_path", "sap", "OutputGuard.check_route (ASU route smu|cmu); CN and CL return the "
                         "path to the SMU side; read back by *LRN? 62 (WP7.1)"),
    "SAR": CommandTarget("set_asu_1pa_auto", "sar", "ranging only; read back by *LRN? 63 (WP7.1)"),
    "SAL": CommandTarget("set_asu_indicator", "sal", "ASU indicator; no output change (WP7.1)"),
    "IMP": CommandTarget("set_impedance_model", "imp", "Table 4-16; run-table modes 10, 11, 100, 101, 200, 201"),
    "FC": CommandTarget("apply_cmu_signal", "fc", "OutputGuard.check_ac; also set_cmu_frequency"),
    "ACV": CommandTarget("apply_cmu_signal", "acv", "OutputGuard.check_ac; also set_cmu_ac, zero_cmu (cleanup)"),
    "DCV": CommandTarget("apply_cmu_signal", "dcv", "OutputGuard.check_ac; MFCMU +-25 V only; also set_cmu_dc, "
                         "zero_cmu (cleanup step 4)"),
    "RC": CommandTarget("set_cmu_range", "rc"),
    "ACT": CommandTarget("set_cmu_integration", "act"),
    "LMN": CommandTarget("set_cmu_monitor", "lmn"),
    "WDCV": CommandTarget("cv_sweep", "wdcv", "OutputGuard.check_ac at both ends; MFCMU form only"),
    "WTDCV": CommandTarget("cv_sweep", "wtdcv"),
    "WMDCV": CommandTarget("cv_sweep", "wmdcv", "also pulsed_cv_sweep"),
    "WFC": CommandTarget("cf_sweep", "wfc", "OutputGuard.check_ac at both ends"),
    "WTFC": CommandTarget("cf_sweep", "wtfc"),
    "WMFC": CommandTarget("cf_sweep", "wmfc"),
    "WACV": CommandTarget("ac_level_sweep", "wacv", "OutputGuard.check_ac at both ends"),
    "WTACV": CommandTarget("ac_level_sweep", "wtacv"),
    "WMACV": CommandTarget("ac_level_sweep", "wmacv"),
    "PDCV": CommandTarget("pulsed_spot_c", "pdcv", "OutputGuard.check_ac at base and pulse"),
    "PTDCV": CommandTarget("pulsed_spot_c", "ptdcv", "also pulsed_cv_sweep"),
    "PWDCV": CommandTarget("pulsed_cv_sweep", "pwdcv", "OutputGuard.check_ac at base, start and stop"),
    "MDCV": CommandTarget("ct_sampling", "mdcv", "OutputGuard.check_ac at base, bias and post"),
    "MTDCV": CommandTarget("ct_sampling", "mtdcv"),
    "ADJ": CommandTarget("set_phase_compensation_mode", "adj", "initializes the MFCMU"),
    "CORRL": CommandTarget("set_correction_frequencies", "corrl"),
    "CLCORR": CommandTarget("set_correction_frequencies", "clcorr"),
    "CORR?": CommandTarget("measure_correction", "corr_q", "OutputGuard.check_ac at every listed frequency"),
    "DCORR": CommandTarget("set_correction_standard", "dcorr"),
    "CORRL?": CommandTarget("correction_frequencies", "corrl_q", "read back by the correction recipes before any "
                            "rewrite, which would clear the other corrections (WP8.2)"),
    "DCORR?": CommandTarget("correction_standard", "dcorr_q", "standards read back by the correction recipes (WP8.2)"),
    "CORRDT": CommandTarget("set_correction_data", "corrdt"),
    "CORRST": CommandTarget("set_correction", "corrst"),
    "SSP": CommandTarget("scuu_route", "ssp", "OutputGuard.check_route per output; resets the SMUs (ATV-27); path "
                         "read back with *LRN? 81 (no SSP? exists)"),
    "SSL": CommandTarget("set_scuu_indicator", "ssl"),
    # SMU pulsed measurements (WP7.3, kind smu_pulsed)
    "PT": CommandTarget("pulsed_setup", "pt", "MM 3/4/5 hold, width, period (always sent); OutputGuard.check_pulse"),
    "PV": CommandTarget("pulsed_setup", "pv", "OutputGuard.check at base and pulse + check_pulse; also pulsed_update "
                        "(host list of pulse levels)"),
    "PI": CommandTarget("pulsed_setup", "pi", "current pulse (driver only; no pulse_i role function); check at its "
                        "Vcomp"),
    "PWV": CommandTarget("pulsed_setup", "pwv", "MM 4 pulsed sweep, linear only (error 226); guard at base/start/stop"),
    "PWI": CommandTarget("pulsed_setup", "pwi", "MM 4 current pulsed sweep (driver only)"),
    "MCPT": CommandTarget("pulsed_setup", "mcpt", "MM 27/28 hold, period, Mdelay 0 (automatic), average"),
    "MCPNT": CommandTarget("pulsed_setup", "mcpnt", "per pulse channel; delay 0 and one width on HR/MP/HPSMU"),
    "MCPNX": CommandTarget("pulsed_setup", "mcpnx", "MM 27/28 pulsed bias source N; also pulsed_update"),
    "MCPWS": CommandTarget("pulsed_setup", "mcpws", "MM 28 sweep mode and steps"),
    "MCPWNX": CommandTarget("pulsed_setup", "mcpwnx", "MM 28 pulsed sweep source N"),
}
MM_MODE_TARGETS: dict[int, str] = {1: "B1500Driver.spot_setup", 2: "B1500Driver.staircase",
                                   10: "B1500Driver.sampling_setup", 16: "B1500Driver.staircase",
                                   17: "B1500Driver.spot_c", 18: "B1500Driver.cv_sweep",
                                   19: "B1500Driver.pulsed_spot_c", 20: "B1500Driver.pulsed_cv_sweep",
                                   22: "B1500Driver.cf_sweep", 23: "B1500Driver.ac_level_sweep",
                                   26: "B1500Driver.ct_sampling", 3: "B1500Driver.pulsed_setup",
                                   4: "B1500Driver.pulsed_setup", 5: "B1500Driver.pulsed_setup",
                                   27: "B1500Driver.pulsed_setup", 28: "B1500Driver.pulsed_setup"}
"""``MM <mode>`` entries of the legacy atoms: the driver method that sends each mapped mode (others unmapped)."""
# Mapped commands are all m1; these unmapped ones are m2; everything else is `later`.
M2_COMMANDS = frozenset({"AV", "BC", "NUB?", "TSC"})

# FLEX commands named in the legacy basis but absent from the command summary YAML (never edit
# references/manuals/**; the citation is recorded here instead).
EXTRA_COMMANDS: dict[str, dict[str, Any]] = {
    "HSS": {"pdf_pages": [438], "printed_pages": ["4-120"], "name": "High-speed spot standard (HSS mode)"},
}

# Manual pages of mapped commands that the command summary lists only in its grouped index, read from the
# Programming Guide (Ed. 15) by WP1.3: mnemonic -> (PDF pages, printed pages). Chapter 4: PDF = printed 4-N + 318.
GROUPED_PAGES: dict[str, tuple[list[int], list[str]]] = {
    "AAD": ([351], ["4-33"]),
    "CORRST?": ([388], ["4-70"]),
    "ERMOD?": ([420, 421], ["4-102 to 4-103"]),
    "ERSSP?": ([434], ["4-116"]),
    "ERMOD": ([419, 420], ["4-101 to 4-102"]),
    "ERSSP": ([433], ["4-115"]),
    "SPST?": ([513, 514], ["4-195 to 4-196"]),
    "SIM": ([508], ["4-190"]),
    "SPRM": ([512, 513], ["4-194 to 4-195"]),
    "SPPER": ([512], ["4-194"]),
    "SER": ([507], ["4-189"]),
    "SPM": ([510, 511], ["4-192 to 4-193"]),
    "SPT": ([514, 515], ["4-196 to 4-197"]),
    "SPV": ([516, 517], ["4-198 to 4-199"]),
    "ODSW": ([478, 479], ["4-160 to 4-161"]),
    "STGP": ([523, 524], ["4-205 to 4-206"]),
    "ALW": ([361, 362], ["4-43 to 4-44"]),
    "ALS": ([360, 361], ["4-42 to 4-43"]),
    "SPUPD": ([515, 516], ["4-197 to 4-198"]),
    "SRP": ([518], ["4-200"]),
    "SPP": ([511], ["4-193"]),
    "CORRSER?": ([385, 386], ["4-67 to 4-68"]),
    "CM": ([379], ["4-61"]),
    "AIT": ([356, 357, 358, 359], ["4-38 to 4-41"]),
    "CMM": ([380], ["4-62"]),
    "LOP?": ([446, 447], ["4-128 to 4-129"]),
    "RI": ([501], ["4-183"]),
    "SAL": ([505], ["4-187"]),
    "SAP": ([505, 506], ["4-187 to 4-188"]),
    "SAR": ([506], ["4-188"]),
    "RV": ([503, 504], ["4-185 to 4-186"]),
    "WM": ([552, 553], ["4-234 to 4-235"]),
    "WT": ([564, 565], ["4-246 to 4-247"]),
    "WV": ([568, 569], ["4-250 to 4-251"]),
    "MCC": ([461], ["4-143"]),
    "MI": ([468, 469], ["4-150 to 4-151"]),
    "ML": ([469, 470], ["4-151 to 4-152"]),
    "MSC": ([472, 473], ["4-154 to 4-155"]),
    "MT": ([474, 475, 476], ["4-156 to 4-158"]),
    "MV": ([477, 478], ["4-159 to 4-160"]),
    "WI": ([551, 552], ["4-233 to 4-234"]),
    "WSV": ([561, 562, 563], ["4-243 to 4-245"]),
    "WSI": ([560, 561], ["4-242 to 4-243"]),
    "WNX": ([556, 557, 558, 559], ["4-238 to 4-241"]),
    # MFCMU and SCUU (WP8.1)
    "IMP": ([441], ["4-123"]),
    "FC": ([435], ["4-117"]),
    "ACV": ([354, 355], ["4-36 to 4-37"]),
    "DCV": ([390, 391], ["4-72 to 4-73"]),
    "RC": ([500], ["4-182"]),
    "ACT": ([354], ["4-36"]),
    "LMN": ([445, 446], ["4-127 to 4-128"]),
    "WDCV": ([549, 550], ["4-231 to 4-232"]),
    "WTDCV": ([566, 567], ["4-248 to 4-249"]),
    "WMDCV": ([554, 555], ["4-236 to 4-237"]),
    "WFC": ([550, 551], ["4-232 to 4-233"]),
    "WTFC": ([567, 568], ["4-249 to 4-250"]),
    "WMFC": ([555, 556], ["4-237 to 4-238"]),
    "WACV": ([547], ["4-229"]),
    "WTACV": ([565, 566], ["4-247 to 4-248"]),
    "WMACV": ([553, 554], ["4-235 to 4-236"]),
    "PDCV": ([484, 485], ["4-166 to 4-167"]),
    "PTDCV": ([487, 488], ["4-169 to 4-170"]),
    "PWDCV": ([489, 490], ["4-171 to 4-172"]),
    "MDCV": ([467, 468], ["4-149 to 4-150"]),
    "MTDCV": ([476, 477], ["4-158 to 4-159"]),
    "CORRL": ([384, 385], ["4-66 to 4-67"]),
    "CLCORR": ([379], ["4-61"]),
    "DCORR": ([389], ["4-71"]),
    "CORRL?": ([385], ["4-67"]),
    "DCORR?": ([389, 390], ["4-71 to 4-72"]),
    "CORRDT": ([383, 384], ["4-65 to 4-66"]),
    "SSP": ([519, 520, 521], ["4-201 to 4-203"]),
    "SSL": ([519], ["4-201"]),
    # SMU pulsed (WP7.3)
    "PT": ([486, 487], ["4-168 to 4-169"]),
    "PV": ([488, 489], ["4-170 to 4-171"]),
    "PI": ([485, 486], ["4-167 to 4-168"]),
    "PWV": ([492, 493], ["4-174 to 4-175"]),
    "PWI": ([490, 491], ["4-172 to 4-173"]),
    "MCPT": ([464, 465], ["4-146 to 4-147"]),
    "MCPNT": ([461, 462], ["4-143 to 4-144"]),
    "MCPNX": ([462, 463], ["4-144 to 4-145"]),
    "MCPWS": ([465], ["4-147"]),
    "MCPWNX": ([465, 466, 467], ["4-147 to 4-149"]),
}
CHAPTER_4_PDF_OFFSET = 318


def _printed_to_pdf(printed: list[str]) -> list[int]:
    """Expand printed chapter-4 pages (`4-38` or `4-38 to 4-41`) to PDF page numbers."""
    pages: list[int] = []
    for item in printed:
        ends = [int(part.strip().split("-", 1)[1]) for part in item.split(" to ")]
        pages.extend(range(ends[0] + CHAPTER_4_PDF_OFFSET, ends[-1] + CHAPTER_4_PDF_OFFSET + 1))
    return pages


# Non-FLEX basis tokens of the legacy atoms (host-side operations and placeholders).
HOST_TOKENS: dict[str, str | None] = {
    "output data buffer read": "B1500Driver.execute_and_read",
    "session.close": None,
    "SMU IV wrapper": None,
    "HCSMU IV wrapper": None,
    "UHC expander IV wrapper": None,
    "HVMC expander IV wrapper": None,
    "UHV expander IV wrapper": None,
}
HOST_PRIORITY = {"output data buffer read": "m1", "session.close": "m1"}

# Legacy basis lists plain `MM` for these atoms; the mode is implied by the atom
# (Programming Guide Table 4-28, PDF 471-472 / printed 4-153 to 4-154).
MM_MODE_HINTS = {
    "C_atom_smu_execute_pulsed_spot": 3,
    "C_atom_smu_execute_pulsed_sweep": 4,
    "C_atom_smu_execute_sampling": 10,
}

# Legacy prefix wildcards -> the grouped_command_index category they abbreviate.
WILDCARD_GROUPS = {
    "BD*": "Quasi-pulsed Spot",
    "LS*": "Linear Search",
    "BS*": "Binary Search",
    "DSMPL*": "Signal Monitor",
}

# Any of these words in an atom id puts the atom's function out of the M1/M2 scope.
LATER_SCOPES = frozenset({
    "wgfmu", "easyexpert", "spgu", "cmu", "qscv", "hvsmu", "hcsmu", "uhcu", "hvmcu", "uhvu", "scuu",
    "selector", "dio",
})  # fmt: skip

# Hand decisions where the automatic rule (priority = latest of the atom's commands) would mislead.
ATOM_OVERRIDES: dict[str, dict[str, str]] = {
    "A_atom_flex_disconnect": {
        "priority": "m1",
        "note": "successor: Transport.close via Session (sections 2.2, 2.4); B1500Driver.disconnect is CL",
    },
    "A_atom_flex_get_status": {
        "priority": "m1",
        "note": "successor: Session.snapshot (IDN, UNT, ERRX, STB, outputs); *LRN? 31 read by the executor "
        "(auto-calibration, R-CAL-01/02)",
    },
    "A_atom_flex_query_settings": {"note": "*LRN? is the ATV-1 fallback for output verification (M4 L1)"},
    "A_atom_flex_query_compliance_status": {
        "priority": "m1",
        "note": "per-point compliance comes from FMT status codes C/T; LIM? not planned",
    },
    "A_atom_flex_read_error_queue": {"priority": "m1", "note": "ERRX? only"},
    "B_atom_safety_b1500_preflight": {
        "priority": "m1",
        "note": "successor: rules pre_execute phase + Session.snapshot; interlock from STB bit 3 (ATV-10)",
    },
    "B_atom_safety_b1500_check_interlock": {"note": "interlock state is read from STB bit 3 (status_byte, ATV-10)"},
    "B_atom_output_b1500_confirm_zero": {"note": "output-off verification uses LOP? (output_state, ATV-1)"},
    "B_atom_output_b1500_zero_all": {
        "note": "successor: Transaction cleanup AB -> DZ -> CL -> verify and the safe_shutdown tool"
    },
    "C_atom_smu_set_measurement_mode": {"note": "staircase sends MM 2 and MM 16 (WP7.2), sampling_setup MM 10 "
                                        "(WP7.4), spot_setup MM 1 (WP7.1), pulsed_setup MM 3/4/5/27/28 (WP7.3); "
                                        "other modes later"},
    "C_atom_smu_configure_integration": {"priority": "m1", "note": "AV (averaging) is m2"},
    "C_atom_smu_set_measurement_ranging": {"priority": "m1", "note": "RM (auto-ranging limit) is later"},
    "C_atom_smu_configure_staircase_sweep": {
        "priority": "m1",
        "note": "WV or WI primary, lin/log single/double; WSV/WSI synchronous and WNX multi-channel sources "
        "(WP7.2)",
    },
}

# D atoms are hardware-free analysis stubs: never mapped to the driver; successor in the new layers
# (blueprint sections 2.6-2.8, 5.1) and the milestone that delivers it.
D_SUCCESSORS: dict[str, tuple[str | None, str]] = {
    "D_atom_ingest_request_build_expectation": ("catalog planner: PlanRecord.estimate", "m1"),
    "D_atom_ingest_smu_build_dataset": ("kind.to_table + analysis.load_run", "m1"),
    "D_atom_ingest_easyexpert_build_dataset": (None, "later"),
    "D_atom_ingest_cmu_build_dataset": (None, "later"),
    "D_atom_ingest_wgfmu_build_series": (None, "later"),
    "D_atom_qualify_dataset_classify_status": ("analysis.assess_quality (per-column status)", "m1"),
    "D_atom_qualify_dataset_check_completeness": ("analysis.assess_quality", "m1"),
    "D_atom_qualify_iv_check_compliance": ("analysis.assess_quality (C/T status codes)", "m1"),
    "D_atom_qualify_iv_check_resolution": ("analysis.assess_quality (noise)", "m2"),
    "D_atom_qualify_run_check_context": ("run manifest: rules reports, IDN/UNT?, cleanup report", "m1"),
    "D_atom_qualify_dataset_grade_trust": ("RunData.trusted + QualityReport verdict", "m1"),
    "D_atom_qualify_iv_check_source_tracking": (None, "later"),
    "D_atom_qualify_dataset_check_continuity": (None, "later"),
    "D_atom_qualify_cv_check_correction": (None, "later"),
    "D_atom_qualify_timeseries_check_events": (None, "later"),
    "D_atom_shape_dataset_split_segments": ("segment fwd/rev option of the Vth extractors", "m2"),
    "D_atom_shape_dataset_stack_family": ("smu_stepped table (Id-Vd family)", "m2"),
    "D_atom_shape_dataset_normalize_geometry": (None, "later"),
    "D_atom_derive_curve_compute_derivative": ("analysis.gm", "m1"),
    "D_atom_derive_curve_interpolate": (None, "later"),
    "D_atom_derive_curve_fit_linear": ("inside analysis.vth_linear_extrapolation", "m1"),
    "D_atom_derive_dataset_summarize_columns": (None, "later"),
    "D_atom_derive_timeseries_summarize_windows": (None, "later"),
    "D_atom_extract_leakage_current": ("analysis.leakage_at", "m2"),
    "D_atom_extract_transfer_vth": ("analysis.vth_linear_extrapolation (M2: vth_constant_current, vth_max_gm)", "m1"),
    "D_atom_extract_transfer_gm_max": ("analysis.gm_max", "m2"),
    "D_atom_extract_transfer_ss": ("analysis.subthreshold_swing", "m2"),
    "D_atom_extract_transfer_on_off": ("analysis.ion_ioff", "m2"),
    "D_atom_extract_transfer_voltage_shift": ("analysis.memory_window", "m2"),
    "D_atom_extract_output_ron": ("analysis.output_metrics", "m2"),
    "D_atom_extract_leakage_breakdown_voltage": (None, "later"),
    "D_atom_extract_cv_cox": (None, "later"),
    "D_atom_extract_cv_vfb": (None, "later"),
    "D_atom_assess_value_check_limits": (None, "later"),
    "D_atom_assess_dataset_check_envelope": (None, "later"),
    "D_atom_assess_dataset_compare_reference": (None, "later"),
    "D_atom_archive_run_build_manifest": ("archive.store (manifest.json)", "m1"),
    "D_atom_archive_run_write_bundle": ("archive.store (run folder)", "m1"),
    "D_atom_archive_run_load_bundle": ("analysis.load_run", "m1"),
    "D_atom_render_dataset_build_plot_spec": ("analysis.plot_iv", "m2"),
    "D_atom_render_dataset_build_table": ("data.csv + get_run rows", "m1"),
    "D_atom_render_run_build_report": (None, "later"),
}


class DriverMapError(RuntimeError):
    """Raised when the legacy sources or the manual summary do not match the expected shape."""


# --- Legacy sources ------------------------------------------------------------------------------------------
def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        raise DriverMapError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve_commit(ref: str) -> str:
    """Return the commit hash a ref points to (raises DriverMapError if it does not exist)."""
    return _git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def load_legacy_sources(ref: str = DEFAULT_REF, source_dir: Path | None = None) -> dict[str, str]:
    """Return {file name: source text} for the legacy `*_atoms.py`, `*_flows.py` and `common.py` modules."""

    def wanted(name: str) -> bool:
        return name.endswith(("_atoms.py", "_flows.py")) or name == "common.py"

    if source_dir is not None:
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(source_dir.iterdir()) if wanted(p.name)}
    names = [Path(line).name for line in _git("ls-tree", "--name-only", f"{ref}:{LEGACY_PACKAGE}").splitlines()]
    return {name: _git("show", f"{ref}:{LEGACY_PACKAGE}/{name}") for name in sorted(names) if wanted(name)}


def _registered_names(tree: ast.Module, list_name: str) -> list[str]:
    """Names in the module-level `<list_name> = [...]` registration list (plain or annotated assignment)."""
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        target = node.target if isinstance(node, ast.AnnAssign) else target
        if isinstance(target, ast.Name) and target.id == list_name and isinstance(node.value, ast.List):
            return [elt.id for elt in node.value.elts if isinstance(elt, ast.Name)]
    raise DriverMapError(f"registration list {list_name} not found")


def _function_defs(tree: ast.Module, prefix: str) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith(prefix)}


def _check_fake_response_signature(tree: ast.Module) -> None:
    """Assert `common._fake_response(atom, flex_basis, **payload)`: its 2nd argument is the FLEX basis."""
    func = _function_defs(tree, "_fake_response").get("_fake_response")
    if func is None or [a.arg for a in func.args.args][:2] != ["atom", "flex_basis"]:
        raise DriverMapError("common.py: _fake_response(atom, flex_basis, ...) not found")


def _check_c_response_forwarding(tree: ast.Module) -> None:
    """Assert `_c_response(atom, object_name, basis, ...)` forwards `basis` as `_fake_response`'s 2nd argument."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_c_response":
            params = [a.arg for a in node.args.args]
            calls = [
                c for c in ast.walk(node) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_fake_response"
            ]
            if (
                params[:3] == ["atom", "object_name", "basis"]
                and len(calls) == 1
                and isinstance(calls[0].args[1], ast.Name)
                and calls[0].args[1].id == "basis"
            ):
                return
            raise DriverMapError("_c_response no longer forwards basis as _fake_response's second argument")
    raise DriverMapError("_c_response not found in c_atoms.py")


def _abc_basis(func: ast.FunctionDef) -> list[str]:
    """The literal FLEX basis list of the single `_fake_response`/`_c_response` call in an A/B/C atom."""
    calls = [
        c
        for c in ast.walk(func)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in ("_fake_response", "_c_response")
    ]
    if len(calls) != 1:
        raise DriverMapError(f"{func.name}: expected one _fake_response/_c_response call, found {len(calls)}")
    call = calls[0]
    if ast.literal_eval(call.args[0]) != func.name:
        raise DriverMapError(f"{func.name}: response names a different atom")
    basis = ast.literal_eval(call.args[1] if call.func.id == "_fake_response" else call.args[2])
    if not isinstance(basis, list) or not all(isinstance(t, str) for t in basis):
        raise DriverMapError(f"{func.name}: basis is not a list of strings")
    return basis


def _d_specs(tree: ast.Module) -> dict[str, dict[str, Any]]:
    """{D atom id: {basis, legacy_priority}} from the `_SPECS` catalog of d_atoms.py."""
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_SPECS":
            specs: dict[str, dict[str, Any]] = {}
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                if not (isinstance(value, ast.Call) and getattr(value.func, "id", "") == "_s"):
                    raise DriverMapError("_SPECS entry is not an _s(...) call")
                basis = next((kw.value for kw in value.keywords if kw.arg == "basis"), None)
                specs[ast.literal_eval(key)] = {
                    "basis": list(ast.literal_eval(basis)) if basis is not None else [],
                    "legacy_priority": ast.literal_eval(value.args[3]),
                }
            return specs
    raise DriverMapError("_SPECS not found in d_atoms.py")


def extract_legacy(sources: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (atoms, flows) from the legacy sources, in registration order, with consistency checks."""
    if "common.py" not in sources:
        raise DriverMapError("legacy module common.py missing")
    _check_fake_response_signature(ast.parse(sources["common.py"], filename="common.py"))
    atoms: list[dict[str, Any]] = []
    for cls in ATOM_CLASSES:
        module = f"{cls.lower()}_atoms.py"
        if module not in sources:
            raise DriverMapError(f"legacy module {module} missing")
        tree = ast.parse(sources[module], filename=module)
        names = _registered_names(tree, f"{cls}_ATOM_FUNCTIONS")
        defs = _function_defs(tree, f"{cls}_atom_")
        if sorted(names) != sorted(defs) or len(set(names)) != len(names):
            raise DriverMapError(f"{module}: {cls}_ATOM_FUNCTIONS does not match the {cls}_atom_* definitions")
        if cls == "C":
            _check_c_response_forwarding(tree)
        specs = _d_specs(tree) if cls == "D" else {}
        if cls == "D" and sorted(specs) != sorted(names):
            raise DriverMapError("d_atoms.py: _SPECS keys do not match D_atom_* definitions")
        for name in names:
            if cls == "D":
                atoms.append({"id": name, "class": cls, **specs[name]})
            else:
                atoms.append({"id": name, "class": cls, "basis": _abc_basis(defs[name])})
    flows: list[dict[str, Any]] = []
    for cls in FLOW_CLASSES:
        module = f"{cls.lower()}_flows.py"
        if module not in sources:
            raise DriverMapError(f"legacy module {module} missing")
        tree = ast.parse(sources[module], filename=module)
        names = _registered_names(tree, f"{cls}_FLOW_FUNCTIONS")
        defs = _function_defs(tree, f"{cls}_flow_")
        if sorted(names) != sorted(defs) or len(set(names)) != len(names):
            raise DriverMapError(f"{module}: {cls}_FLOW_FUNCTIONS does not match the {cls}_flow_* definitions")
        flows.extend({"id": name, "class": cls} for name in names)
    return atoms, flows


# --- Manual command summary -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandSummary:
    """The manual's command vocabulary: every `commands[].command` record plus every grouped-index name."""

    order: list[str]  # every mnemonic, first-seen order (detailed records first)
    detailed: dict[str, dict[str, Any]]  # mnemonic -> detailed record
    groups: dict[str, list[str]]  # grouped_command_index category -> mnemonics

    @property
    def vocabulary(self) -> set[str]:
        return set(self.order) | set(EXTRA_COMMANDS)

    @property
    def groups_flat(self) -> set[str]:
        return {name for names in self.groups.values() for name in names}


def load_command_summary(path: Path | None = None) -> CommandSummary:
    """Load `b1500a-command-summary.yaml` (read-only; references/manuals/** is never modified)."""
    path = path or REPO_ROOT / COMMAND_SUMMARY
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    detailed = {rec["command"]: rec for rec in data["commands"]}
    order = list(detailed)
    groups: dict[str, list[str]] = {}
    for group in data.get("grouped_command_index", []):
        groups.setdefault(group["category"], []).extend(group["commands"])
        order.extend(c for c in group["commands"] if c not in order)
    return CommandSummary(order, detailed, groups)


# --- Mapping -----------------------------------------------------------------------------------------------
def _priority_max(values: list[str]) -> str:
    return max(values, key=PRIORITIES.index) if values else "later"


def classify_token(token: str, summary: CommandSummary) -> tuple[str, list[str]]:
    """Classify one legacy basis token -> (kind, normalized FLEX entries).

    kind is `flex`, `wgfmu`, `easyexpert` or `host`. FLEX entries are mnemonics; `MM<n>` becomes `MM <n>`
    and prefix wildcards such as `BD*` expand to the mnemonics with that prefix in their manual group
    (WILDCARD_GROUPS), so `LS*` does not pick up the program-memory query `LST?`.
    """
    if token.startswith("WGFMU_"):
        return "wgfmu", []
    if token.startswith((":", "[", "EasyEXPERT ")):
        return "easyexpert", []
    if token in HOST_TOKENS:
        return "host", []
    if token.startswith("MM") and token[2:].isdigit():
        return "flex", [f"MM {int(token[2:])}"]
    if token.endswith("*") and not token.startswith("*"):
        group = summary.groups.get(WILDCARD_GROUPS.get(token, ""), [])
        expanded = [m for m in group if m.startswith(token[:-1])]
        if not expanded:
            raise DriverMapError(f"wildcard {token!r} has no WILDCARD_GROUPS entry or matches no mnemonic")
        return "flex", expanded
    if token in summary.vocabulary:
        return "flex", [token]
    raise DriverMapError(f"unknown basis token {token!r}; add it to the manual vocabulary or HOST_TOKENS")


def _mnemonic(entry: str) -> str:
    return entry.split(" ", 1)[0]


def _flex_target(entry: str) -> str | None:
    """New driver target of one normalized FLEX entry, or None if unmapped."""
    mnemonic = _mnemonic(entry)
    if mnemonic == "MM" and " " in entry:
        return MM_MODE_TARGETS.get(int(entry.split(" ", 1)[1]))
    target = COMMAND_TARGETS.get(mnemonic)
    return target.primary if target else None


def _flex_priority(entry: str) -> str:
    """m1 if mapped, m2 for the M2_COMMANDS, else later (`MM <n>` of an unmapped mode is later)."""
    if _flex_target(entry):
        return "m1"
    return "m2" if _mnemonic(entry) in M2_COMMANDS else "later"


def map_atom(atom: dict[str, Any], summary: CommandSummary) -> dict[str, Any]:
    """Build one map entry (id, class, basis, flex, target, unmapped_flex, priority, note, ...)."""
    atom_id, cls, basis = atom["id"], atom["class"], atom["basis"]
    entry: dict[str, Any] = {"id": atom_id, "class": cls, "basis": basis}
    if cls == "D":
        successor, priority = D_SUCCESSORS[atom_id]
        entry.update(flex=[], target=UNMAPPED, priority=priority, legacy_priority=atom["legacy_priority"])
        if successor:
            entry["successor"] = successor
        return entry
    flex: list[str] = []
    targets: list[str] = []
    unmapped_flex: list[str] = []
    priorities: list[str] = []
    for token in basis:
        kind, entries = classify_token(token, summary)
        if kind == "flex":
            if entries == ["MM"] and atom_id in MM_MODE_HINTS:
                entries = [f"MM {MM_MODE_HINTS[atom_id]}"]
            for item in entries:
                if item in flex:
                    continue
                flex.append(item)
                target = _flex_target(item)
                if target is None:
                    unmapped_flex.append(item)
                elif target not in targets:
                    targets.append(target)
                priorities.append(_flex_priority(item))
        elif kind == "host":
            host_target = HOST_TOKENS[token]
            if host_target and host_target not in targets:
                targets.append(host_target)
            priorities.append(HOST_PRIORITY.get(token, "later"))
        else:
            priorities.append("later")
    priority = _priority_max(priorities)
    if LATER_SCOPES.intersection(atom_id.split("_")):
        priority = "later"
    override = ATOM_OVERRIDES.get(atom_id, {})
    priority = override.get("priority", priority)
    entry.update(flex=flex, target=targets or UNMAPPED)
    if targets and unmapped_flex:
        entry["unmapped_flex"] = unmapped_flex
    entry["priority"] = priority
    if "note" in override:
        entry["note"] = override["note"]
    return entry


def map_commands(summary: CommandSummary, atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per manual mnemonic (plus EXTRA_COMMANDS): target, builder, priority, legacy atoms using it."""
    users: dict[str, list[str]] = {}
    for atom in atoms:
        for item in atom["flex"]:
            users.setdefault(_mnemonic(item), [])
            if atom["id"] not in users[_mnemonic(item)]:
                users[_mnemonic(item)].append(atom["id"])
    entries: list[dict[str, Any]] = []
    for mnemonic in [*summary.order, *EXTRA_COMMANDS]:
        target = COMMAND_TARGETS.get(mnemonic)
        entry: dict[str, Any] = {"command": mnemonic}
        if mnemonic in EXTRA_COMMANDS:
            entry["source"] = "extra"
            entry["pdf_pages"] = EXTRA_COMMANDS[mnemonic]["pdf_pages"]
            entry["printed_pages"] = EXTRA_COMMANDS[mnemonic]["printed_pages"]
        elif mnemonic in summary.detailed:
            entry["source"] = "detailed"
            entry["pdf_pages"] = list(summary.detailed[mnemonic].get("pdf_pages") or [])
            entry["printed_pages"] = list(summary.detailed[mnemonic].get("printed_pages") or [])
        else:
            entry["source"] = "grouped"
            if mnemonic in GROUPED_PAGES:
                entry["pdf_pages"], entry["printed_pages"] = (list(x) for x in GROUPED_PAGES[mnemonic])
        entry["target"] = target.primary if target else UNMAPPED
        if target and target.builder:
            entry["builder"] = f"flex.{target.builder}"
        entry["priority"] = _flex_priority(mnemonic)
        entry["atoms"] = users.get(mnemonic, [])
        if target and target.note:
            entry["note"] = target.note
        entries.append(entry)
    return entries


def build_map(
    sources: dict[str, str], *, source_ref: str, commit: str | None, summary_path: Path | None = None
) -> dict[str, Any]:
    """Build the complete driver-map document (a plain dict, YAML-ready)."""
    raw_atoms, flows = extract_legacy(sources)
    ids = {a["id"] for a in raw_atoms}
    d_ids = {a["id"] for a in raw_atoms if a["class"] == "D"}
    if set(D_SUCCESSORS) != d_ids:
        raise DriverMapError(f"D_SUCCESSORS keys differ from the D atoms: {sorted(set(D_SUCCESSORS) ^ d_ids)}")
    stale = sorted((set(ATOM_OVERRIDES) | set(MM_MODE_HINTS)) - ids)
    if stale:
        raise DriverMapError(f"ATOM_OVERRIDES/MM_MODE_HINTS name unknown atoms: {stale}")
    summary = load_command_summary(summary_path)
    bad_pages = {m: pages for m, pages in GROUPED_PAGES.items() if _printed_to_pdf(pages[1]) != pages[0]}
    if bad_pages or not set(GROUPED_PAGES) <= set(summary.groups_flat) - set(summary.detailed):
        raise DriverMapError(f"GROUPED_PAGES: inconsistent pages {bad_pages} or not a grouped-only command")
    atoms = [map_atom(a, summary) for a in raw_atoms]
    commands = map_commands(summary, atoms)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "source": {"ref": source_ref, "commit": commit, "package": LEGACY_PACKAGE, "command_summary": COMMAND_SUMMARY},
        "priority_scale": PRIORITY_SCALE,
        "counts": _counts(atoms, flows, commands),
        "driver_targets": list(DRIVER_TARGETS),
        "atoms": atoms,
        "flows": flows,
        "commands": commands,
    }
    problems = check_map(doc, summary_path)
    if problems:
        raise DriverMapError("driver map failed its checks:\n  " + "\n  ".join(problems))
    return doc


# --- Checks (also used by tests on the committed YAML, without git) ------------------------------------------
def _counts(atoms: list[dict[str, Any]], flows: list[dict[str, Any]], commands: list[dict[str, Any]]) -> dict:
    atom_counts = Counter(a["class"] for a in atoms)
    flow_counts = Counter(f["class"] for f in flows)
    return {
        "atoms": {**{c: atom_counts[c] for c in ATOM_CLASSES}, "total": len(atoms)},
        "atoms_by_priority": {p: sum(a["priority"] == p for a in atoms) for p in PRIORITIES},
        "atoms_unmapped": sum(a["target"] == UNMAPPED for a in atoms),
        "flows": {**{c: flow_counts[c] for c in FLOW_CLASSES}, "total": len(flows)},
        "commands": len(commands),
        "commands_mapped": sum(c["target"] != UNMAPPED for c in commands),
    }


def check_map(doc: dict[str, Any], summary_path: Path | None = None) -> list[str]:
    """Return a list of problems (empty = ok): counts, flows, targets, priorities and manual command coverage."""
    problems: list[str] = []
    atoms, flows, commands = doc["atoms"], doc["flows"], doc["commands"]
    ids = [a["id"] for a in atoms]
    counts = Counter(a["class"] for a in atoms)
    if dict(counts) != EXPECTED_ATOMS or len(atoms) != EXPECTED_ATOM_TOTAL:
        problems.append(f"atom counts {dict(counts)} (total {len(atoms)}) != {EXPECTED_ATOMS} ({EXPECTED_ATOM_TOTAL})")
    if len(set(ids)) != len(ids):
        problems.append("duplicate atom ids")
    for atom in atoms:
        if not atom["id"].startswith(f"{atom['class']}_atom_"):
            problems.append(f"{atom['id']}: class {atom['class']} does not match the id")
        targets = atom["target"]
        if targets != UNMAPPED and not (isinstance(targets, list) and targets and set(targets) <= set(DRIVER_TARGETS)):
            problems.append(f"{atom['id']}: target {targets!r} is not a list of driver targets or {UNMAPPED!r}")
        if atom["priority"] not in PRIORITIES:
            problems.append(f"{atom['id']}: priority {atom['priority']!r} not in {PRIORITIES}")
        if atom["class"] == "D" and (atom["flex"] or targets != UNMAPPED):
            problems.append(f"{atom['id']}: D atoms are hardware-free and must stay unmapped")
    flow_ids = [f["id"] for f in flows]
    flow_counts = Counter(f["class"] for f in flows)
    if len(flows) != EXPECTED_FLOW_TOTAL or len(set(flow_ids)) != len(flow_ids) or dict(flow_counts) != EXPECTED_FLOWS:
        problems.append(
            f"flows: {len(set(flow_ids))} unique of {len(flows)}, by class {dict(flow_counts)}; "
            f"expected {EXPECTED_FLOW_TOTAL} {EXPECTED_FLOWS}"
        )
    for flow in flows:
        if not flow["id"].startswith(f"{flow['class']}_flow_"):
            problems.append(f"{flow['id']}: class {flow['class']} does not match the id")
    by_command = {c["command"]: c for c in commands}
    if len(by_command) != len(commands):
        problems.append("duplicate command entries")
    for mnemonic in load_command_summary(summary_path).order:
        entry = by_command.get(mnemonic)
        if entry is None:
            problems.append(f"manual command {mnemonic!r} missing from the map")
        elif entry["target"] != UNMAPPED and entry["target"] not in DRIVER_TARGETS:
            problems.append(f"manual command {mnemonic!r}: target {entry['target']!r} is not a driver target")
        elif entry["priority"] not in PRIORITIES:
            problems.append(f"manual command {mnemonic!r}: priority {entry['priority']!r} not in {PRIORITIES}")
    for atom in atoms:
        for item in atom["flex"]:
            if _mnemonic(item) not in by_command:
                problems.append(f"{atom['id']}: FLEX {item!r} missing from commands")
    for entry in commands:
        if entry["target"] != UNMAPPED and not entry.get("pdf_pages"):
            problems.append(f"mapped command {entry['command']!r} has no manual pages")
    if doc.get("counts") != _counts(atoms, flows, commands):
        problems.append("counts block does not match the entries")
    return problems


# --- Rendering ---------------------------------------------------------------------------------------------
HEADER = """\
# GENERATED by scripts/build_driver_map.py from the legacy sources named under `source:`; do not edit.
# Frozen v0.2 fake-MCP taxonomy (282 atoms, 97 flows) mapped onto the new B1500Driver (blueprint section 2.3)
# and coverage of every command in references/manuals/structured/b1500a-command-summary.yaml.
# Field meanings and the priority scale: README.md next to this file. Never auto-loaded by agents.
"""


def _flow(value: Any) -> str:
    return yaml.safe_dump(value, default_flow_style=True, sort_keys=False, width=1_000_000, allow_unicode=False).strip()


def render_yaml(doc: dict[str, Any]) -> str:
    """Deterministic YAML text: block layout for the header keys, one flow-style line per atom/flow/command."""
    lines = [HEADER.rstrip("\n")]
    for key in ("schema_version", "source", "priority_scale", "counts"):
        block = yaml.safe_dump({key: doc[key]}, sort_keys=False, width=110, allow_unicode=False)
        lines.append(block.rstrip("\n"))
    lines.append("driver_targets: " + _flow(doc["driver_targets"]))
    for key in ("atoms", "flows", "commands"):
        lines.append(f"{key}:")
        lines.extend(f"- {_flow(item)}" for item in doc[key])
    text = "\n".join(lines) + "\n"
    if yaml.safe_load(text) != doc:
        raise DriverMapError("rendered YAML does not round-trip")
    return text


# --- CLI -------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Build or check the driver map; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ref", default=DEFAULT_REF, help=f"git ref with the legacy sources (default {DEFAULT_REF})")
    parser.add_argument(
        "--source-dir",
        type=Path,
        help=f"read the legacy package from this directory instead (e.g. a working tree's {LEGACY_PACKAGE})",
    )
    parser.add_argument("--output", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT, help="YAML file to write/check")
    parser.add_argument("--check", action="store_true", help="do not write; fail if the file is missing or stale")
    args = parser.parse_args(argv)
    try:
        if args.source_dir is not None:
            sources, ref, commit = load_legacy_sources(source_dir=args.source_dir), "working-tree", None
        else:
            sources, ref, commit = load_legacy_sources(ref=args.ref), args.ref, resolve_commit(args.ref)
        doc = build_map(sources, source_ref=ref, commit=commit)
        text = render_yaml(doc)
    except DriverMapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    counts = doc["counts"]
    print(
        f"atoms {counts['atoms']}; flows {counts['flows']['total']}; commands {counts['commands']} "
        f"({counts['commands_mapped']} mapped); atoms by priority {counts['atoms_by_priority']}"
    )
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else None
        if current != text:
            print(f"error: {args.output} is missing or stale; run scripts/build_driver_map.py", file=sys.stderr)
            return 1
        print(f"ok: {args.output} is current")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
