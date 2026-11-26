"""Bring-up stage L8 records from hardware-shaped runs (WP10.8; blueprint v2 7.4 L8, 7.2): every L8 recipe runs on
backend visa through the real ``VisaTransport`` and the real ``WgfmuDll`` over the fake ABI (visa-loop, run ids
``H...``), and ``bringup record L8`` drafts its recipe record. Every machine-readable check the stage file names for
that recipe finds its value in the run (kind_result fact, analysis quantity or cleanup) - none is "not measured" -,
the cleanup checks pass (``LOP?`` and the complete WGFMU safe state), the WGFMU self-test/cal results are 0, I(R)
through the RSU passes against the 100 kOhm reference within the stage's 3 %, and the pulsed Id-Vg is compared with a
DC Id-Vg through the RSU SMU inputs (``pulsed_vs_dc``, the agent's own analysis). The stage record takes the
``--wgfmu-session`` probe line and leaves the audit and oscilloscope observations to the human."""

from __future__ import annotations

import shutil
from typing import Any

import pytest

from b1500_test_agent import bringup
from b1500_test_agent.models.validation import STAGE_FILES_DIR, ValidationRecord
from b1500_test_agent.service import B1500Admin, B1500Service
from tests.visa_loop.helpers import REPO_ROOT, VisaWorld
from tests.visa_loop.test_sampling_visa import run_to_end

pytestmark = pytest.mark.wgfmu

NOT_MEASURED = "not measured in the given runs"
MOSFET = {"pin_map": "mosfet-wgfmu", "dut_profile": "nmos-wgfmu"}
L8_CASES: list[dict[str, Any]] = [
    {"recipe_id": "system.wgfmu_self_test", "scenario": "nmos_wgfmu", "request": {"pin_map": "mosfet-wgfmu"}},
    {"recipe_id": "system.wgfmu_self_cal", "scenario": "nmos_wgfmu", "request": {"pin_map": "mosfet-wgfmu"}},
    {"recipe_id": "wgfmu.dc_spot", "scenario": "resistor_100k",
     "request": {"params": {}, "pin_map": "resistor-wgfmu", "dut_profile": "resistor-generic"},
     "references": ["r_wgfmu=1e5"]},
    {"recipe_id": "wgfmu.pulsed_iv", "scenario": "nmos_wgfmu", "request": {"params": {}, **MOSFET}},
    {"recipe_id": "wgfmu.fast_iv", "scenario": "nmos_wgfmu", "request": {"params": {}, **MOSFET}},
    {"recipe_id": "wgfmu.pulse_train", "scenario": "nmos_wgfmu",
     "request": {"params": {"count": 20, "samples": 3}, **MOSFET}},
    {"recipe_id": "wgfmu.custom_waveform", "scenario": "nmos_rtn", "request": {"params": {}, **MOSFET}},
    {"recipe_id": "wgfmu.rtn", "scenario": "nmos_rtn", "request": {"params": {"points": 20000}, **MOSFET}},
    {"recipe_id": "wgfmu.lfn", "scenario": "nmos_rtn", "request": {"params": {"points": 150000}, **MOSFET}},
    {"recipe_id": "fecap.pund", "scenario": "fecap_basic",
     "request": {"params": {}, "pin_map": "fecap-wgfmu", "dut_profile": "fecap-generic"}},
    {"recipe_id": "fefet.fast_program_read", "scenario": "fefet_lab",
     "request": {"params": {}, "pin_map": "fefet-wgfmu", "dut_profile": "fefet-lab"},
     "references": ["fast_mw=0.9"]},
]
"""Every recipe of stage L8 with the card example on its scenario (the pulse train and the noise records shortened as in
the visa-loop waveform suite; the system recipes on the WGFMU MOSFET landing, whose terminals the human lifts)."""
DC_REFERENCE = {"recipe_id": "mosfet.idvg", "scenario": "nmos_wgfmu",
                "request": {"pin_map": "mosfet-4t", "dut_profile": "nmos-wgfmu",
                            "params": {"vd": 1.0, "vg_start": 0.0, "vg_stop": 2.0, "vg_points": 21,
                                       "icomp_drain": 1e-3}}}
"""Agent step 4: the DC Id-Vg of the same landing through the RSUs' SMU inputs (``mosfet-4t``; ATV-32), the gate
levels and drain bias of the pulsed plan."""


@pytest.fixture
def l8(world: VisaWorld) -> VisaWorld:
    """The world with the committed stage files (bring-up reads them from the repository root)."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    return world


def _hardware_run(world: VisaWorld, case: dict[str, Any]) -> tuple[B1500Service, str]:
    service = world.service(world.bus(case["scenario"]))
    _validation, result = run_to_end(service, case)
    assert result.ok and result.outcome == "completed", result.message
    assert result.backend == "visa" and (result.run_id or "").startswith("H") and result.cleanup_verified == "lop"
    return service, result.run_id or ""


def _measured(record: ValidationRecord, check_id: str) -> Any:
    return next(m for m in record.measurements if m.check == check_id)


def test_l8_covers_exactly_these_recipes() -> None:
    _path, front, problem = bringup.load_stage(REPO_ROOT, "L8")
    assert front is not None, problem
    assert [c["recipe_id"] for c in L8_CASES] == front.recipes


@pytest.mark.parametrize("case", L8_CASES, ids=[c["recipe_id"] for c in L8_CASES])
def test_every_l8_check_of_a_recipe_finds_its_value_in_a_hardware_run(case: dict[str, Any], l8: VisaWorld) -> None:
    if case["recipe_id"] == "wgfmu.pulsed_iv":
        _service, dc_run = _hardware_run(l8, DC_REFERENCE)
    service, run_id = _hardware_run(l8, case)
    if case["recipe_id"] == "wgfmu.pulsed_iv":  # agent step 4: the agent's own comparison with the DC reference
        compared = service.analyze_run(run_id, "pulsed_vs_dc", {"reference_run": dc_run})
        assert compared.ok, compared.message
    _path, front, _problem = bringup.load_stage(l8.root, "L8")
    assert front is not None
    draft = bringup.record(service, "L8", [run_id], references=case.get("references", []), operator="owner")
    assert draft.ok and draft.record is not None, draft.message
    record = draft.record
    assert record.recipe_id == case["recipe_id"] and record.runs == [run_id] and record.reviewer == ""
    assert record.backend == "visa" and record.stage == "L8"
    checks = front.checks_for(case["recipe_id"])
    assert checks
    for check in checks:
        found = _measured(record, check.id)
        assert found.observed != NOT_MEASURED, (check.id, found)
        if check.quantity == "cleanup":
            assert found.passed is True, (check.id, found.observed)
        elif check.tolerance is not None:
            assert found.passed is True, (check.id, found.value, found.reference)
    assert record.result == "pass", [(m.check, m.passed) for m in record.measurements if m.check]
    if case["recipe_id"] == "wgfmu.dc_spot":  # I(R) through the RSU: the 100 kOhm standard within 3 %
        assert _measured(record, "r_wgfmu").value == pytest.approx(1e5, rel=0.03)
    if case["recipe_id"] == "wgfmu.pulsed_iv":  # 1 % duty: pulsed = DC (the stage's "explained" case)
        assert _measured(record, "pulsed_vs_dc").value == pytest.approx(1.0, abs=0.02)
    if case["recipe_id"] == "wgfmu.custom_waveform":  # the committed lwp sample: 2 x 55,200 event values
        assert _measured(record, "lwp_values").value == 110400
    if case["recipe_id"].startswith("system."):
        assert _measured(record, case["recipe_id"].removeprefix("system.") + "_result").value == 0


def test_the_stage_record_takes_the_session_probe_and_leaves_the_observations_open(l8: VisaWorld) -> None:
    """Agent step 1 (``doctor --probe --wgfmu-session``) and runs of two L8 recipes make the stage record (runs of
    several recipes, ``--recipe`` omitted): the probe's WGFMU session line passes; the audit and oscilloscope checks
    are the human's (not measured in the draft)."""
    service, dc_spot_run = _hardware_run(l8, L8_CASES[2])
    report = B1500Admin(service).probe(wgfmu_session=True)
    assert report.ok and report.record is not None, report.message
    self_test = {**L8_CASES[0], "scenario": "resistor_100k", "request": {"pin_map": "resistor-wgfmu"}}
    _service, self_test_run = _hardware_run(l8, self_test)
    draft = bringup.record(service, "L8", [dc_spot_run, self_test_run], probe="latest", operator="owner")
    assert draft.ok and draft.record is not None, draft.message
    record = draft.record
    assert record.recipe_id is None and record.runs == [dc_spot_run, self_test_run]
    session = _measured(record, "session_probe")
    assert session.passed is True and session.observed.startswith("PASS"), session
    human = ("lock_cycle", "rsu_vmonitor", "pg_level", "no_fw_errors", "smu_bias_held", "pund_rate")
    assert {m.check: m.observed for m in record.measurements if m.check in human} == {c: NOT_MEASURED for c in human}
