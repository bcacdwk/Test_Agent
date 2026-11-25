"""Bring-up stage L7 records from hardware-shaped runs (WP9.6; blueprint v2 7.4 L7, 7.2): every L7 recipe runs on
backend visa through the real ``VisaTransport`` (visa-loop, run ids ``H...``) with the selector wiring recorded, and
``bringup record L7`` drafts its recipe record. Every machine-readable check the stage file names for that recipe
finds its value in the run (kind_result fact, analysis quantity or cleanup) - none is "not measured" - the cleanup
checks pass, ``spp_fallbacks`` is 0 (ATV-19 on the simulator) and the pulse memory window passes against a dual-sweep
reference within the stage tolerance. The stage record of the human's observations (relays, wiring, scope levels)
stays undecided until the human fills it in."""

from __future__ import annotations

import shutil
from typing import Any

import pytest

from b1500_test_agent import bringup
from b1500_test_agent.models.validation import STAGE_FILES_DIR, ValidationRecord
from tests.sim.selector_helpers import recorded_station
from tests.visa_loop.helpers import REPO_ROOT, VisaWorld
from tests.visa_loop.test_sampling_visa import run_to_end

pytestmark = pytest.mark.spgu

NOT_MEASURED = "not measured in the given runs"
FEFET = {"pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
L7_CASES: list[dict[str, Any]] = [
    {"recipe_id": "system.selector_check", "scenario": "fefet_lab",
     "request": {"params": {"dwell_s": 0.0}, "pin_map": "fefet-sel"}},
    {"recipe_id": "spgu.pulse_train", "scenario": "fefet_lab", "request": {"params": {}, **FEFET}},
    {"recipe_id": "spgu.alwg_sequence", "scenario": "fefet_lab", "request": {"params": {}, **FEFET}},
    {"recipe_id": "fefet.dual_sweep_mw", "scenario": "fefet_basic",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "fefet-generic"}},
    {"recipe_id": "fefet.pulse_write_read", "scenario": "fefet_lab", "request": {"params": {}, **FEFET}},
    {"recipe_id": "spgu.program_smu_read", "scenario": "fefet_lab", "request": {"params": {"cycles": 1}, **FEFET}},
    {"recipe_id": "fefet.switching_kinetics", "scenario": "fefet_lab",
     "request": {"params": {"amplitudes": [3.6, 4.4], "widths": [1e-8, 1e-7, 1e-6, 1e-5], "precycles": 100},
                 **FEFET}},
    {"recipe_id": "mosfet.charge_pumping", "scenario": "nmos_cv",
     "request": {"params": {"frequency": [1e4, 1e5, 1e6]}, "pin_map": "mosfet-cp", "dut_profile": "nmos-cv"}},
]
"""Every recipe of stage L7 with the card example (smaller grids where the visa-loop suite uses them; the DC loop on
the card's direct-gate landing; the selector check on the FeFET landing, whose four selector ports are cabled like
``lab_station``'s, with no dwell: the human needs it only on hardware)."""


@pytest.fixture
def l7(world: VisaWorld) -> VisaWorld:
    """The world with the committed stage files and the selector wiring recorded (stage L7 physical step 2)."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    world.write_local("station.yaml", recorded_station())
    return world


def _hardware_run(world: VisaWorld, case: dict[str, Any]) -> tuple[Any, str]:
    service = world.service(world.bus(case["scenario"], chunk_size=16))
    _validation, result = run_to_end(service, case)
    assert result.ok and result.outcome == "completed", result.message
    assert result.backend == "visa" and (result.run_id or "").startswith("H")
    return service, result.run_id or ""


def _measured(record: ValidationRecord, check_id: str) -> Any:
    return next(m for m in record.measurements if m.check == check_id)


def test_l7_covers_exactly_these_recipes() -> None:
    _path, front, problem = bringup.load_stage(REPO_ROOT, "L7")
    assert front is not None, problem
    assert [c["recipe_id"] for c in L7_CASES] == front.recipes


@pytest.mark.parametrize("case", L7_CASES, ids=[c["recipe_id"] for c in L7_CASES])
def test_every_l7_check_of_a_recipe_finds_its_value_in_a_hardware_run(case: dict[str, Any], l7: VisaWorld) -> None:
    service, run_id = _hardware_run(l7, case)
    _path, front, _problem = bringup.load_stage(l7.root, "L7")
    assert front is not None
    references: list[str] = []
    if case["recipe_id"] == "fefet.pulse_write_read":
        references = ["pulse_mw=1.0"]  # the DC loop of fefet_lab: about 1 V (stage reference = dual_sweep_mw)
    draft = bringup.record(service, "L7", [run_id], references=references, operator="owner")
    assert draft.ok and draft.record is not None, draft.message
    record = draft.record
    assert record.recipe_id == case["recipe_id"] and record.runs == [run_id] and record.reviewer == ""
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
    if case["recipe_id"] == "fefet.pulse_write_read":
        assert _measured(record, "pulse_routes").observed.endswith("end rest SEL1.OUT1->open")
        assert _measured(record, "pulse_mw").reference == 1.0
    if case["recipe_id"] == "system.selector_check":
        assert _measured(record, "selector_states").value == 14  # 4 states on CH 1 outputs, 3 on CH 2, 2 selectors


def test_the_stage_record_keeps_the_humans_observations_open(l7: VisaWorld) -> None:
    """Runs of two recipes make the stage record: its checks are the human's (relays, wiring, scope levels), so the
    draft names them unmeasured and leaves the result to the reviewer."""
    service, selector_run = _hardware_run(l7, L7_CASES[0])
    _service, pulse_run = _hardware_run(l7, L7_CASES[1])
    draft = bringup.record(service, "L7", [selector_run, pulse_run], operator="owner")
    assert draft.ok and draft.record is not None, draft.message
    record = draft.record
    assert record.recipe_id is None and record.runs == [selector_run, pulse_run]
    human = ("relays_observed", "wiring_recorded", "pulse_level_1meg", "pulse_level_ser50")
    assert {m.check: m.observed for m in record.measurements if m.check} == {c: NOT_MEASURED for c in human}
    assert record.result == ""
