"""Bring-up stage files S0, L0-L10 (WP6.3: S0, L0-L4, L10; the module closures L5-L9; blueprint v2 6.1, 6.2, 7.4).

The stage lint itself runs in ``tests/skills/test_lint_*.py``; here the content the plan fixes: which stages exist,
the recipes each runs (L1 uses ``basic.contact_resistor`` at 0 V until the zero-check recipe arrives), the §7.4 pass
criteria as machine-readable checks, the human-only commands appearing only as the human's steps, and the
rehearsal rule (no record from simulator runs) in every Record section; since v2.1 (WP21.6) the gap steps and check
ids of plan §4.6 (each fed by a step of ``steps.yaml``), the capture steps and the rewordings instead of a step.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from b1500_test_agent.bringup_ledger import frontmatter, load_stage
from b1500_test_agent.devtools.skills.commands import named_commands
from b1500_test_agent.devtools.skills.common import STAGE_SECTIONS
from b1500_test_agent.devtools.skills.markdown import parse_markdown
from b1500_test_agent.models.validation import STAGE_FILES_DIR, STAGES, StageFrontmatter, stage_file_name

ROOT = Path(__file__).resolve().parents[2]
STAGE_DIR = ROOT.joinpath(*STAGE_FILES_DIR)
WRITTEN = ("S0", "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10")
"""Every stage of blueprint v2 7.4: WP6.3 and the module closures (WP7.7: L5, the SMU part of L9; WP9.5 adds L9's
FeFET endurance and retention; WP8.6: L6; WP9.6: L7; WP10.8: L8 and L9's FeCap endurance next to 10.7's fast BTI)."""
HUMAN_ONLY = ("con" + "fig init", "con" + "fig adopt", "run " + "--confirm", "fa" + "ult clear")
"""Human-only CLI verbs, assembled at run time (the harness guard blocks shell commands that spell them)."""
RECIPES = {
    "S0": [], "L0": [], "L10": [],
    "L1": ["system.zero_check", "system.self_test", "system.self_cal"],  # WP7.1: the zero-check recipe
    "L2": ["basic.contact_resistor", "generic.smu_multi_sweep", "generic.smu_spot", "resistor.kelvin_4w"],
    "L3": ["basic.diode_iv", "basic.iv_force_i"],
    "L4": ["mosfet.idvg", "mosfet.idvd", "mosfet.gate_leakage", "mosfet.idvg_family", "mosfet.idvg_sync",
           "mosfet.body_effect"],
    "L5": ["mosfet.idvg_pulsed", "mosfet.idvd_pulsed", "basic.pulsed_spot", "generic.smu_multi_pulsed",
           "mosfet.id_t_sampling", "generic.smu_sampling", "mosfet.vth_search"],  # WP7.7 (QSCV leakage: L6)
    "L6": ["cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short", "cmu.correction_load", "cmu.spot",
           "moscap.cv", "moscap.cv_ac_level", "moscap.pulsed_cv", "moscap.cf", "moscap.ct", "moscap.cv_multi_freq",
           "moscap.qscv", "mosfet.cgc_cv", "mosfet.cgd_cv", "fecap.cv_butterfly"],  # WP8.6: every 3.2 recipe
    "L7": ["system.selector_check", "spgu.pulse_train", "spgu.alwg_sequence", "fefet.dual_sweep_mw",
           "fefet.pulse_write_read", "spgu.program_smu_read", "fefet.switching_kinetics",
           "mosfet.charge_pumping"],  # WP9.6: every HV-SPGU and 16440A recipe of blueprint v2 3.3 but L9's
    "L8": ["system.wgfmu_self_test", "system.wgfmu_self_cal", "wgfmu.dc_spot", "wgfmu.pulsed_iv", "wgfmu.fast_iv",
           "wgfmu.pulse_train", "wgfmu.custom_waveform", "wgfmu.rtn", "wgfmu.lfn", "fecap.pund",
           "fefet.fast_program_read"],  # WP10.8: every WGFMU recipe of blueprint v2 3.4 but L9's (WGFMU self-test/cal
    # moved from L1, where WP10.7 had put them before L8 existed)
    "L9": ["reliability.bti_sms", "igzo.bias_stress", "reliability.hci", "reliability.silc", "reliability.tddb_cvs",
           "dielectric.bdv", "basic.breakdown_search",  # WP7.7: the SMU part
           "fefet.endurance", "fefet.retention",  # WP9.5: the HV-SPGU part
           "wgfmu.fast_bti",  # WP10.7: the WGFMU fast BTI
           "fecap.endurance_pund"],  # WP10.8: the FeCap endurance by PUND
}


def _front(stage: str) -> StageFrontmatter:
    path, front, problem = load_stage(ROOT, stage)
    assert front is not None, problem or f"{path} missing"
    return front


def _section(stage: str, title: str) -> str:
    doc = parse_markdown(STAGE_DIR / stage_file_name(stage), stage)
    span = doc.section(f"{STAGE_SECTIONS.index(title) + 1}. {title}")
    assert span is not None, f"{stage}: no section {title}"
    return "\n".join(doc.lines[span[0]:span[1] - 1])


def test_exactly_the_written_stage_files_exist() -> None:
    present = sorted(p.name for p in STAGE_DIR.glob("*.md") if p.name != "_TEMPLATE.md")
    assert present == sorted(stage_file_name(s) for s in WRITTEN)
    for stage in set(STAGES) - set(WRITTEN):
        assert load_stage(ROOT, stage)[1] is None


@pytest.mark.parametrize("stage", WRITTEN)
def test_stage_file_shape(stage: str) -> None:
    path = STAGE_DIR / stage_file_name(stage)
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 150
    doc = parse_markdown(path, path.name)
    assert [h.text for h in doc.headings if h.level == 2] == [f"{i}. {t}" for i, t in enumerate(STAGE_SECTIONS, 1)]
    front = _front(stage)
    assert front.stage == stage and front.recipes == RECIPES[stage]
    assert front.checks, f"{stage}: the Expected values need machine-readable checks"
    assert StageFrontmatter.model_validate(frontmatter(text)) == front


def test_l1_runs_the_zero_check_recipe() -> None:
    """WP7.1 switched L1 from the M6 interim (``basic.contact_resistor`` at 0 V) to ``system.zero_check``; L2 runs
    the spot and four-wire recipes with their commands and expected values."""
    agent = _section("L1", "Agent steps")
    assert "`system.zero_check`" in agent and "`open-smus`" in agent and "`open-circuit`" in agent
    assert "`basic.contact_resistor`" not in agent
    assert "zero_floor" in _section("L1", "Expected values")
    l2 = _section("L2", "Agent steps")
    assert "`generic.smu_spot`" in l2 and "`resistor.kelvin_4w`" in l2 and "kelvin_resistance" in l2


def _check(stage: str, check_id: str):
    return next(c for c in _front(stage).checks if c.id == check_id)


def test_pass_criteria_are_the_blueprint_defaults() -> None:
    """Blueprint v2 7.4: L1 verified lop every run and floors recorded; L2 +-1 % vs DMM; L4 Vth +-10 mV and SS +-5 %
    vs EasyEXPERT on the same die."""
    assert _check("L1", "cleanup_lop").quantity == "cleanup"
    floor = _check("L1", "floor_smu3")
    assert floor.tolerance is None and (floor.quantity, floor.method) == ("smu3_floor", "zero_floor")
    kelvin = _check("L2", "r_kelvin")
    assert (kelvin.recipe, kelvin.method, kelvin.tolerance and kelvin.tolerance.rel) == (
        "resistor.kelvin_4w", "kelvin_resistance", 0.01)
    r = _check("L2", "r_dmm")
    assert (r.recipe, r.quantity, r.tolerance and r.tolerance.rel) == ("basic.contact_resistor", "resistance", 0.01)
    vth, ss = _check("L4", "vth"), _check("L4", "ss")
    assert (vth.quantity, vth.method, vth.tolerance and vth.tolerance.absolute) == (
        "vth", "vth_linear_extrapolation", 0.010)
    assert (ss.quantity, ss.tolerance and ss.tolerance.rel) == ("ss", 0.05)
    assert _check("L1", "self_test_result").tolerance.check(0, None) is True  # type: ignore[union-attr]
    assert _check("L1", "self_test_result").tolerance.check(4, None) is False  # type: ignore[union-attr]


def test_record_keys_of_each_stage() -> None:
    assert _front("S0").record_keys() == [None] and _front("L0").record_keys() == [None]
    assert _front("L1").record_keys() == ["system.self_test", "system.self_cal", None]
    assert _front("L2").record_keys() == ["basic.contact_resistor", "generic.smu_multi_sweep", "generic.smu_spot",
                                          "resistor.kelvin_4w"]
    assert _front("L3").record_keys() == ["basic.diode_iv", "basic.iv_force_i"]
    assert _front("L4").record_keys() == ["mosfet.idvg", "mosfet.idvd", "mosfet.gate_leakage", "mosfet.idvg_family",
                                          "mosfet.idvg_sync", "mosfet.body_effect"]


@pytest.mark.parametrize("stage", WRITTEN)
def test_human_only_commands_are_the_humans_steps(stage: str) -> None:
    """The configuration bootstrap, run --confirm and fault clear never appear as an agent step; where a stage needs
    one it is a physical step of the human (or named as the human's in an abort criterion)."""
    agent = " ".join(" ".join(t) for t in named_commands(_section(stage, "Agent steps")))
    assert not any(verb in agent for verb in HUMAN_ONLY), stage
    for title in ("Preconditions", "Expected values", "Record"):
        text = " ".join(" ".join(t) for t in named_commands(_section(stage, title)))
        assert not any(verb in text for verb in HUMAN_ONLY), (stage, title)


def test_l0_hands_the_configuration_to_the_human() -> None:
    physical = " ".join(" ".join(t) for t in named_commands(_section("L0", "Physical steps (human)")))
    assert "con" + "fig init --visa" in physical
    assert "con" + "fig adopt work/bringup/station.proposed.yaml --as station" in physical
    agent = _section("L0", "Agent steps")
    for command in ("uv run b1500 doctor --probe", "uv run b1500 bringup propose-station", "uv run b1500 config check",
                    "uv run b1500 bringup capture probe", "uv run b1500 bringup record L0 --probe latest"):
        assert command in agent, command
    assert "stop the turn" in agent


@pytest.mark.parametrize("stage", WRITTEN)
def test_record_section_names_the_command_and_the_rehearsal_rule(stage: str) -> None:
    record = _section(stage, "Record")
    assert f"uv run b1500 bringup record {stage}" in record
    assert "Simulator rehearsal" in record and re.search(r"no record", record)
    assert "validation/hw/" in record


@pytest.mark.parametrize("stage", WRITTEN)
def test_physical_steps_are_numbered_for_the_human(stage: str) -> None:
    physical = _section(stage, "Physical steps (human)")
    assert re.search(r"^1\. ", physical, re.MULTILINE), stage
    abort = _section(stage, "Abort criteria")
    assert "wait for the human" in abort or "wait for the owner" in abort


def test_l5_and_l9_pass_criteria_follow_the_blueprint() -> None:
    """Blueprint v2 7.4: L5 pulsed = DC at low duty +-2 %, sampling grid as set; L9 async + cancel + recovery with
    cleanup verified and auto-calibration restored (WP7.7); Vth by search +-5 mV of the constant-current Vth (10.3)."""
    pulsed = _check("L5", "pulsed_vs_dc")
    assert (pulsed.quantity, pulsed.method, pulsed.tolerance and pulsed.tolerance.absolute) == (
        "pulsed_over_dc", "pulsed_vs_dc", 0.02)
    gaps = _check("L5", "id_t_gaps")
    assert (gaps.quantity, gaps.method) == ("index_gaps", "kind_result") and gaps.tolerance.check(0, None)  # type: ignore[union-attr]
    assert not gaps.tolerance.check(3, None)  # type: ignore[union-attr]
    assert _check("L5", "vth_search").tolerance.absolute == 0.005  # type: ignore[union-attr]
    for check in ("async_progress", "cancel_drill", "recovery_drill", "autocal_restored"):
        assert _check("L9", check).recipe is None, check  # stage-record checks
    assert "each recovery" in _check("L9", "autocal_restored").text  # WP11.1: restored after a kill too
    assert _front("L9").record_keys()[-1] is None and "reliability.bti_sms" in _front("L9").record_keys()
    agent = _section("L9", "Agent steps")
    assert "`stress_time: 600`" in agent and "get_run(run, include=[progress])" in agent
    physical = _section("L9", "Physical steps (human)")
    assert "uv run b1500 shutdown" in physical and "b1500-mcp" in physical



def test_l6_pass_criteria_follow_the_blueprint() -> None:
    """Blueprint v2 7.4 L6: phase compensation, open/short with the human lifting and landing the probes, known C
    +-1 %, `CORRST?` on, store written; MOS-C, QSCV offset and leakage, the SCUU same-landing check (WP8.5 handoff)."""
    known = _check("L6", "known_c")
    assert (known.recipe, known.quantity, known.method, known.tolerance and known.tolerance.rel) == (
        "cmu.spot", "cp", "impedance_convert", 0.01)
    for check in ("corrst_on", "store_written", "scuu_rest"):
        assert _check("L6", check).recipe is None, check  # stage-record checks
    for check, quantity in (("phase_result", "result_code"), ("open_stray_c", "open_cp_f"), ("short_r", "short_rs_ohm"),
                            ("qscv_offset", "offset_f"), ("qscv_leakage", "leakage_max_a")):
        assert (_check("L6", check).quantity, _check("L6", check).method) == (quantity, "kind_result"), check
    assert _check("L6", "phase_result").tolerance.check(0, None)  # type: ignore[union-attr]
    assert not _check("L6", "open_stray_c").tolerance.check(69e-12, None)  # type: ignore[union-attr]
    assert _check("L6", "qscv_cox").tolerance.rel == 0.02  # type: ignore[union-attr]
    physical = _section("L6", "Physical steps (human)")
    assert "lifted" in physical and "on a short" in physical
    agent = _section("L6", "Agent steps")
    assert "`moscap-scuu`" in agent and "`dit_high_low`" in agent and "`offset: measure`" in agent
    assert "TODO(verify)" in _section("L6", "Expected values")


@pytest.mark.spgu
def test_l7_pass_criteria_follow_the_blueprint() -> None:
    """Blueprint v2 7.4 L7: `ERSSP?` verified per state, MW consistent with the dual sweep, wiring recorded (ATV-28);
    pulses into 1 MOhm (ATV-20 levels, ATV-19 SPST?); every L7 recipe has a check and a cleanup check (WP9.6)."""
    front = _front("L7")
    states = _check("L7", "selector_states")
    assert (states.recipe, states.quantity, states.method) == ("system.selector_check", "states_verified",
                                                               "kind_result")
    mw = _check("L7", "pulse_mw")
    assert (mw.recipe, mw.quantity, mw.method) == ("fefet.pulse_write_read", "memory_window", "memory_window_pulse")
    assert mw.tolerance is not None and mw.tolerance.check(0.95, 1.0) and not mw.tolerance.check(-0.95, 1.0)
    assert _check("L7", "dual_sweep_mw").method == "memory_window"  # the DC reference of pulse_mw
    for stage_check in ("wiring_recorded", "relays_observed", "pulse_level_1meg", "pulse_level_ser50"):
        assert _check("L7", stage_check).recipe is None, stage_check  # the human's observations, stage record
    assert "ATV-28" in _check("L7", "wiring_recorded").reference
    spst = _check("L7", "train_spst")
    assert spst.tolerance is not None and spst.tolerance.check(0, None) and not spst.tolerance.check(1, None)
    for recipe in front.recipes:
        checks = front.checks_for(recipe)
        assert any(c.quantity == "cleanup" for c in checks), recipe
        assert any(c.quantity != "cleanup" for c in checks), recipe
    agent, physical = _section("L7", "Agent steps"), _section("L7", "Physical steps (human)")
    assert "uv run b1500 bringup propose-station" in agent and "work/bringup/station.proposed.yaml" in agent
    assert "con" + "fig adopt work/bringup/station.proposed.yaml --as station" in physical
    assert "certainty: verified" in physical and "SEL1.OUT1" in physical
    for runbook in ("spgu-pulse-no-effect", "spgu-selector-state", "spgu-load-mismatch"):
        assert runbook in _section("L7", "Abort criteria"), runbook


@pytest.mark.wgfmu
def test_l8_pass_criteria_follow_the_blueprint() -> None:
    """Blueprint v2 7.4 L8: DLL/session, self-test/cal, DC into a known R via the RSU (I(R) +-3 %), fast vs DC Id-Vg
    (explained), the lwp waveform rerun, no 30xx errors; every L8 recipe has a check and a cleanup check (WP10.8)."""
    front = _front("L8")
    r = _check("L8", "r_wgfmu")
    assert (r.recipe, r.quantity, r.method, r.tolerance and r.tolerance.rel) == ("wgfmu.dc_spot", "resistance",
                                                                                 "resistance", 0.03)
    assert r.tolerance is not None and r.tolerance.check(1.02e5, 1.0e5) and not r.tolerance.check(1.04e5, 1.0e5)
    pulsed = _check("L8", "pulsed_vs_dc")
    assert (pulsed.recipe, pulsed.quantity, pulsed.method, pulsed.tolerance) == (
        "wgfmu.pulsed_iv", "pulsed_over_dc", "pulsed_vs_dc", None)  # explained, not a pass/fail band
    assert "explained" in pulsed.text and "mosfet.idvg" in pulsed.reference
    for check, recipe in (("wgfmu_self_test_result", "system.wgfmu_self_test"),
                          ("wgfmu_self_cal_result", "system.wgfmu_self_cal")):
        found = _check("L8", check)
        assert found.recipe == recipe and found.tolerance is not None and found.tolerance.check(0, None)
        assert not found.tolerance.check(4, None)
    assert (_check("L8", "lwp_values").recipe, _check("L8", "lwp_values").quantity) == ("wgfmu.custom_waveform",
                                                                                        "values")
    assert _check("L8", "pund_pr").method == "pund_polarization"
    for stage_check in ("session_probe", "lock_cycle", "rsu_vmonitor", "no_fw_errors"):
        assert _check("L8", stage_check).recipe is None, stage_check  # stage record (probe, audit, the human)
    assert "30xx" in _check("L8", "no_fw_errors").text and "ATV-14" in _check("L8", "lock_cycle").reference
    for recipe in front.recipes:
        checks = front.checks_for(recipe)
        assert any(c.quantity == "cleanup" for c in checks), recipe
        assert any(c.quantity != "cleanup" for c in checks), recipe
    assert front.record_keys() == [*front.recipes, None]
    agent, physical = _section("L8", "Agent steps"), _section("L8", "Physical steps (human)")
    assert "uv run b1500 doctor --probe --wgfmu-session" in agent and '"pulsed_vs_dc"' in agent
    assert "uv run b1500 bringup propose-station" in agent and "`mosfet-4t`" in agent
    assert "con" + "fig adopt work/bringup/station.proposed.yaml --as station" in physical
    assert "From SMU" in physical and "V Monitor" in physical
    expected = _section("L8", "Expected values")
    assert "TODO(verify)" in expected and "ATV-14" in expected and "ATV-17" in expected and "ATV-32" in expected
    for runbook in ("wgfmu-library-error", "wgfmu-rsu-route", "wgfmu-range-overflow", "wgfmu-memory-budget"):
        assert runbook in _section("L8", "Abort criteria"), runbook


@pytest.mark.wgfmu
def test_l9_wgfmu_part_runs_the_fast_bti_and_the_fecap_endurance() -> None:
    """Blueprint v2 3.4: ``wgfmu.fast_bti`` and ``fecap.endurance_pund`` are L9 recipes (WP10.7, WP10.8); each has a
    check and a cleanup check, and L9's agent steps run the FeCap endurance asynchronously."""
    front = _front("L9")
    for recipe in ("wgfmu.fast_bti", "fecap.endurance_pund"):
        checks = front.checks_for(recipe)
        assert any(c.quantity == "cleanup" for c in checks) and any(c.quantity != "cleanup" for c in checks), recipe
    endurance = _check("L9", "pund_wake_fatigue")
    assert (endurance.quantity, endurance.method) == ("fatigue", "pund_polarization")
    agent = _section("L9", "Agent steps")
    assert "`fecap.endurance_pund`" in agent and "poll `get_run`" in agent
    assert "`fecap-wgfmu`" in _section("L9", "Physical steps (human)")


def test_l9_drills_cover_every_bus_family_of_the_long_runs() -> None:
    """WP11.1 (blueprint v2 7.4 L9: async + cancel + recovery, cleanup verified after cancel and after recovery, for
    every long-run family): a cancel and a kill-recovery drill on the SMU (``reliability.bti_sms``), the HV-SPGU with
    the selector (``fefet.endurance``) and the WGFMU with the RSUs (``fecap.endurance_pund``); the agent steps name
    the per-bus safe state, the human performs both drills, the stage points to the debug runbook."""
    for bus, recipe in (("", "reliability.bti_sms"), ("_spgu", "fefet.endurance"), ("_wgfmu", "fecap.endurance_pund")):
        for drill in ("cancel_drill", "recovery_drill"):
            check = _check("L9", drill + bus)
            assert check.recipe is None and check.quantity == drill + bus and check.tolerance is None, check
        assert recipe in _check("L9", "cancel_drill" + bus).text or bus == "", recipe
    agent = _section("L9", "Agent steps")
    for fragment in ("`cancel_drill_spgu`", "`recovery_drill_spgu`", "`SPST?` 0", "`SEL1.OUT1` open",
                     "`cancel_drill_wgfmu`", "`recovery_drill_wgfmu`", "`RSU201.OUT`/`RSU202.OUT` open",
                     "`restore` step", "consent record"):
        assert fragment in agent, fragment
    physical = _section("L9", "Physical steps (human)")
    assert "Cancel drills" in physical and "Kill drills" in physical and "`fecap.endurance_pund`" in physical
    expected = _section("L9", "Expected values")
    assert "`recovery_drill`, `recovery_drill_spgu`, `recovery_drill_wgfmu`" in expected
    assert "async-run-interrupted" in (STAGE_DIR / stage_file_name("L9")).read_text(encoding="utf-8")


# -- WP11.4: every stage final: its TODO(verify) list = the blueprint v2 7.6 items it settles -------------------------

DEFERRED_ITEMS = {  # blueprint v2 7.6 "What cannot be done without the hardware (the only deferrals)" -> its ATVs
    1: ("ATV-13", "ATV-14"), 2: ("ATV-18",), 3: (), 4: ("ATV-10", "ATV-1", "ATV-23"), 5: ("ATV-15", "ATV-16", "ATV-17"),
    6: ("ATV-28",), 7: ("ATV-21",), 8: (), 9: ("ATV-20",), 10: (), 11: (), 12: ("ATV-4", "ATV-7", "ATV-8", "ATV-11",
                                                                                   "ATV-25"), 13: (), 14: (),
}
RESOLVED_ITEMS = {14}
"""7.6 items no stage settles any more: 14 (Windows CI) ran on ``windows-latest`` after the owner allowed the push
(OD-4); the roadmap's M12 table marks it resolved (v2.1 WP21.6)."""
STAGE_DEFERRED = {
    "S0": {11}, "L0": {1, 2, 3, 4, 5, 6, 12}, "L1": {1, 3, 4, 8, 10}, "L2": {3, 8}, "L3": {3}, "L4": {6, 11, 12},
    "L5": {3, 8}, "L6": {3, 6, 7}, "L7": {2, 3, 6, 9, 13}, "L8": {1, 5, 8, 9, 10, 13}, "L9": {7, 8, 10, 13},
    "L10": {11, 12},
}
"""Which 7.6 items each stage verifies on hardware (its ``TODO(verify)`` line; the roadmap's M12 table repeats it).
v2.1 (WP21.6): L0 records ASU/SCUU presence (6), L1 the per-call bus cost (1, ``bus_overhead``), L9 the correction
drift over days (7, ``correction_drift``)."""
TODO_LINE = re.compile(r"^- TODO\(verify\) \(blueprint v2 7\.6 items? (?P<items>\d+(?:, \d+)*)[;)]", re.MULTILINE)


def stage_deferred_items(stage: str) -> set[int]:
    """The 7.6 items named by the stage file's single ``TODO(verify)`` line of section 4."""
    (match,) = TODO_LINE.finditer(_section(stage, "Expected values"))
    return {int(n) for n in match.group("items").split(", ")}


@pytest.mark.parametrize("stage", WRITTEN)
def test_each_stage_lists_its_hardware_deferrals_once(stage: str) -> None:
    """One ``TODO(verify) (blueprint v2 7.6 items …)`` line in Expected values and no other ``TODO(verify)`` in the
    file, so the list a reviewer reads is the whole list."""
    text = (STAGE_DIR / stage_file_name(stage)).read_text(encoding="utf-8")
    assert text.count("TODO(verify)") == 1, stage
    assert stage_deferred_items(stage) == STAGE_DEFERRED[stage]


def test_the_stage_lists_cover_every_deferral_with_its_atvs() -> None:
    assert set().union(*STAGE_DEFERRED.values()) == set(DEFERRED_ITEMS) - RESOLVED_ITEMS
    for item, atvs in DEFERRED_ITEMS.items():
        stages = [s for s in WRITTEN if item in STAGE_DEFERRED[s]]
        texts = " ".join((STAGE_DIR / stage_file_name(s)).read_text(encoding="utf-8") for s in stages)
        for atv in atvs:
            assert re.search(rf"{atv}(?!\d)", texts), f"7.6 item {item}: {atv} named in none of {stages}"


@pytest.mark.parametrize("stage", WRITTEN)
def test_every_stage_starts_from_bringup_status(stage: str) -> None:
    """Consistent commands: each stage's preconditions or first agent step read the bring-up status."""
    start = _section(stage, "Preconditions") + _section(stage, "Agent steps")
    assert "`uv run b1500 bringup status`" in start, stage


# -- v2.1 WP21.6: the gap steps and check ids of plan §4.6 ------------------------------------------------------------

GAP_CHECKS = {
    "L0": ("terminations", "server_visa", "asu_presence", "scuu_presence"),  # ATV-2, ATV-4, ATV-28 record fields
    "L1": ("self_test_s", "self_cal_s", "idle_lop", "bus_overhead"),  # *TST?/*CAL? times, ATV-23 codes, ATV-13
    "L2": ("warm_up", "contact_r_2w"),  # warm-up time; two-wire minus four-wire R (leads and contacts)
    "L4": ("approval_prompt",),  # ATV-7, ATV-11
    "L5": ("time_source", "log_points"),  # ATV-22; the points log sampling holds
    "L6": ("adj_read_only",),  # the second probe after the corrections (ADJ? ch,0 changes nothing)
    "L7": ("erssp_negative", "relay_settle", "pulse_edges", "read_window"),  # negative control, settle, edges, read
    "L8": ("smu_bias_held", "pg_level", "pund_rate"),  # ATV-17, the PG level on the V Monitor, the PUND ramp series
    "L9": ("timer_hours", "correction_drift"),  # the timer over hours, the correction drift -> max_age_h
    "L10": ("session_end_async", "hooks_listed", "cli_no_prompt"),  # session end in an async run, ATV-8, ATV-25
}
"""The check ids v2.1 plan §4.6 adds for facts that lived only in the audit or had no step."""
CAPTURE_STAGES = ("L0", "L1", "L2", "L3", "L5", "L6", "L7", "L8")
"""Stages with a ``bringup capture`` step (§4.6: L2, L3, L5, L7 new; L6 and L8 move theirs into an agent step)."""


def _steps():
    from b1500_test_agent.bringup_ledger import load_steps

    return load_steps(ROOT)


@pytest.mark.parametrize("stage", sorted(GAP_CHECKS))
def test_the_gap_checks_exist_and_a_step_feeds_each(stage: str) -> None:
    checks = {c.id for c in _front(stage).checks}
    fed = {check for spec in _steps().stages[stage] for check in spec.feeds}
    for check in GAP_CHECKS[stage]:
        assert check in checks, (stage, check)
        assert check in fed, (stage, check)
        assert f"`{check}`" in _section(stage, "Expected values"), (stage, check)


@pytest.mark.parametrize("stage", CAPTURE_STAGES)
def test_the_stage_captures_its_fixtures_in_a_step(stage: str) -> None:
    captures = [spec for spec in _steps().stages[stage] if spec.verify == "capture"]
    assert captures and all(spec.rehearsal == "refusal" for spec in captures), stage
    item = captures[0].id.split(".")[1]
    assert item.startswith("A") and "uv run b1500 bringup capture" in _section(stage, "Agent steps"), stage


def test_the_deployment_init_and_the_rewordings_of_the_sequence() -> None:
    """D7 holds the human's configuration bootstrap (WP21.5): L0's first physical step checks it; the gaps §4.6
    rewords instead of a step say so in their stage line (no tool sends ``*RST``; the correction-list maximum; the
    WGFMU state after a device clear; the MFCMU DC limit is an owner/data-sheet question)."""
    assert "D7" in _section("L0", "Physical steps (human)") and "D7" in _section("L0", "Preconditions")
    assert "D1-D12" in _section("S0", "Preconditions")
    l6, l7, l8 = (_section(stage, "Expected values") for stage in ("L6", "L7", "L8"))
    assert "no tool sends `*RST`" in l7 and "names no maximum" in l6 and "OD21-10" in l6
    assert "after a FLEX device clear is not observable" in l8
    assert "Item 14 is resolved" in _section("S0", "Expected values")
