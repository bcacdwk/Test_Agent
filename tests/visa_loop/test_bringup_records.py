"""``b1500 bringup status | capture | record`` on backend visa (blueprint v2 7.1, 7.2, 7.4; WP6.3).

The runs are real ``VisaTransport`` runs over the visa-loop resource manager (run ids ``H…``, backend visa), so the
record and capture paths see exactly what the lab PC will see; the drafts go to the temporary world's
``work/bringup/``. Reviewed records are simulated by copying a draft into the temporary world's ``validation/hw/``
(never the repository's). The AC "``bringup record`` refuses ``S…`` runs" is
``test_record_refuses_simulator_runs_before_reading_anything`` (plus the CLI test on backend sim in
``tests/adapters/test_cli_bringup.py``).
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from b1500_test_agent import bringup
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.models.validation import STAGE_FILES_DIR, ValidationRecord, recipe_definition_sha256
from b1500_test_agent.service import B1500Admin, B1500Service
from tests.unit.flex_fixtures import load_fixture
from tests.visa_loop.helpers import MEASUREMENT_CASES, REPO_ROOT, VisaWorld, run_case

CONTACT = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "basic.contact_resistor")
MULTI = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "generic.smu_multi_sweep")  # L2 too (WP7.2)
SPOT = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "generic.smu_spot")  # L2 too (WP7.1)
ZERO = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "system.zero_check")
SIM_RUN = "S20261118T092102Z-2de7"


@pytest.fixture
def stages(world: VisaWorld) -> VisaWorld:
    """The world with the committed stage files (bring-up reads them from the repository root)."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    return world


def _hardware_run(world: VisaWorld, service: B1500Service) -> str:
    result = run_case(service, CONTACT)
    assert result.ok and result.run_id is not None and result.run_id.startswith("H"), result.message
    return result.run_id


def _resistance(world: VisaWorld, run_id: str) -> float:
    payload = json.loads(next((world.run_dir(run_id) / "analysis").glob("resistance-*.json")).read_text("utf-8"))
    return next(r["value"] for r in payload["results"] if r["quantity"] == "resistance")


def test_record_drafts_a_recipe_record_from_hardware_runs(stages: VisaWorld) -> None:
    world = stages
    service = world.service(world.bus(CONTACT["scenario"]))
    run_id = _hardware_run(world, service)
    measured = _resistance(world, run_id)
    draft = bringup.record(service, "L2", [run_id], references=[f"r_dmm@{run_id}={measured * 1.005}"],
                           operator="owner", dut_instance="R100k-A")
    assert draft.ok and not draft.simulated and draft.path is not None, draft.message
    assert draft.path.startswith("work/bringup/records/L2-basic.contact_resistor-") and ":" not in draft.path
    text = (world.root / draft.path).read_text(encoding="utf-8")
    assert text.startswith("# DRAFT hardware validation record")
    record = ValidationRecord.model_validate(yaml.safe_load(text))
    assert record == draft.record
    recipe = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT).get("basic.contact_resistor")
    assert (record.recipe_id, record.recipe_version, record.recipe_sha256) == (
        "basic.contact_resistor", recipe.version, recipe_definition_sha256(recipe))
    assert record.runs == [run_id] and record.backend == "visa" and record.reviewer == "" and not record.reviewed
    assert record.evidence[0].recipe_file_sha256 == recipe.sha256 and record.evidence[0].cleanup == "lop"
    assert record.station.idn.startswith("Keysight Technologies,B1500A") and record.dut.instance == "R100k-A"
    by_check = {m.check: m for m in record.measurements if m.check}
    assert by_check["r_dmm"].value == measured and by_check["r_dmm"].passed is True
    assert by_check["r_dmm"].tolerance == "+-1 % vs DMM" and by_check["r_dmm"].unit == "Ohm"
    assert by_check["cleanup"].passed is True and by_check["linearity"].passed is None
    assert record.result == "pass" and record.operator == "owner"
    assert any(m.quantity.startswith("noise_") for m in record.measurements if m.check is None)
    assert any("validation/hw/basic.contact_resistor.yaml" in step for step in draft.next_steps)

    failing = bringup.record(service, "L2", [run_id], references=[f"r_dmm={measured * 1.05}"])
    assert failing.ok and failing.record is not None and failing.record.result == "fail"


def test_status_follows_drafts_and_reviewed_records(stages: VisaWorld) -> None:
    world = stages
    service = world.service(world.bus(CONTACT["scenario"]))
    status = bringup.bringup_status(service)
    assert status.ok and not status.simulated and status.next_stage == "S0"
    states = {s.stage: s.state for s in status.stages}
    assert states["S0"] == "open" and states["L5"] == "no_stage_file" and states["L10"] == "open"
    run_id = _hardware_run(world, service)
    draft = bringup.record(service, "L2", [run_id], references=[f"r_dmm={_resistance(world, run_id)}"])
    assert draft.ok and draft.record is not None
    l2 = next(s for s in bringup.bringup_status(service).stages if s.stage == "L2")
    # L2 signs off four recipe records: contact check, multi-channel sweep (WP7.2), spot and four-wire (WP7.1)
    assert [r.recipe_id for r in l2.records] == ["basic.contact_resistor", "generic.smu_multi_sweep",
                                                 "generic.smu_spot", "resistor.kelvin_4w"]
    assert l2.state == "in_progress" and l2.records[0].state == "draft" and l2.records[0].path == draft.path
    assert [r.state for r in l2.records[1:]] == ["missing", "missing", "missing"]
    multi = run_case(service, MULTI)  # the stage's second recipe record (generic.smu_multi_sweep)
    assert multi.ok and multi.run_id is not None and multi.run_id.startswith("H"), multi.message
    analysis = service.analyze_run(multi.run_id, "resistance", {"x": "a_V", "y": "a_I"})  # stage L2 agent step 5
    assert analysis.ok, analysis.message
    multi_draft = bringup.record(service, "L2", [multi.run_id], references=["multi_r=1e5"])
    assert multi_draft.ok and multi_draft.record is not None, multi_draft.message
    spot = run_case(service, SPOT)  # the third (generic.smu_spot; default analysis resistance)
    assert spot.ok and spot.run_id is not None and spot.run_id.startswith("H"), spot.message
    spot_draft = bringup.record(service, "L2", [spot.run_id], references=["r_spot=1e5"])
    assert spot_draft.ok and spot_draft.record is not None, spot_draft.message
    assert spot_draft.record.recipe_id == "generic.smu_spot" and spot_draft.record.result == "pass"
    l2 = next(s for s in bringup.bringup_status(service).stages if s.stage == "L2")
    assert l2.state == "in_progress" and [r.state for r in l2.records] == ["draft", "draft", "draft", "missing"]
    (world.root / "validation" / "hw").mkdir(parents=True)
    for item in (draft.record, multi_draft.record, spot_draft.record):
        reviewed = item.model_copy(update={"reviewer": "owner", "reviewed_on": date(2026, 12, 2)})
        target = world.root / "validation" / "hw" / reviewed.file_name()
        target.write_text(yaml.safe_dump(reviewed.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    after = bringup.bringup_status(service)
    l2 = next(s for s in after.stages if s.stage == "L2")
    assert after.reviewed == ["validation/hw/basic.contact_resistor.yaml", "validation/hw/generic.smu_multi_sweep.yaml",
                              "validation/hw/generic.smu_spot.yaml"]
    assert [r.state for r in l2.records] == ["reviewed", "reviewed", "reviewed", "missing"]
    assert l2.state == "in_progress"  # signed only when the four-wire record is reviewed too
    assert after.next_stage == "S0"  # the stages before L2 are still open
    (world.root / "validation" / "hw" / "stage-s0.yaml").write_text("stage: S0\nreviewer: x\n", encoding="utf-8")
    noted = bringup.bringup_status(service)
    assert any("stage-s0.yaml" in note for note in noted.notes)


def test_record_refuses_simulator_runs_before_reading_anything(stages: VisaWorld) -> None:
    world = stages
    service = world.service(world.bus(CONTACT["scenario"]))
    run_id = _hardware_run(world, service)
    result = bringup.record(service, "L2", [run_id, SIM_RUN])
    assert not result.ok and result.status == "refused" and result.error_code == "invalid_input"
    assert SIM_RUN in result.message and "simulator run" in result.message and result.record is None
    assert not (world.root / "work" / "bringup" / "records").exists()
    calls = [e.data for e in world.daily_events() if e.ev == "tool_call" and e.data and
             e.data.get("tool") == "bringup_record"]
    assert calls and calls[-1]["status"] == "refused"


@pytest.mark.parametrize("damage, message", [
    ("missing", "not found"),
    ("data", "files changed since the run (data.csv)"),
    ("backend", "does not validate as a run manifest"),
    ("recipe", "changed since run"),
])  # fmt: skip
def test_record_refuses_runs_that_are_not_trustworthy_hardware_evidence(stages: VisaWorld, tmp_path: Path,
                                                                         damage: str, message: str) -> None:
    world = stages
    service = world.service(world.bus(CONTACT["scenario"]))
    run_id = _hardware_run(world, service)
    folder = world.run_dir(run_id)
    if damage == "missing":
        run_id = run_id[:-4] + "ffff"
    elif damage == "data":
        (folder / "data.csv").write_text("step\n0\n", encoding="utf-8")
    elif damage == "backend":
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        manifest.update(backend="sim", simulated=True)
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        recipes = tmp_path / "recipes"
        shutil.copytree(REPO_ROOT / "recipes", recipes)
        path = recipes / "basic" / "contact_resistor.yaml"
        path.write_text("# edited after the run\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
        service = world.service(world.bus(CONTACT["scenario"]),
                                registry=RecipeRegistry.load(recipes, repo_root=REPO_ROOT))
    result = bringup.record(service, "L2", [run_id])
    assert not result.ok and result.status == "refused" and message in result.message, result.message
    assert not (world.root / "work" / "bringup" / "records").exists()


def test_record_rules_for_recipe_and_stage_records(stages: VisaWorld) -> None:
    world = stages
    service = world.service(world.bus(CONTACT["scenario"]))
    run_id = _hardware_run(world, service)
    assert "does not run mosfet.idvg" in bringup.record(service, "L2", [run_id], recipe_id="mosfet.idvg").message
    assert "no check(s) ['vth']" in bringup.record(service, "L2", [run_id], references=["vth=0.4"]).message
    assert "not CHECK=VALUE" in bringup.record(service, "L2", [run_id], references=["r_dmm"]).message
    assert "unknown stage" in bringup.record(service, "L11", [run_id]).message
    assert "has no stage file yet" in bringup.record(service, "L5", [run_id]).message
    assert "does not run basic.contact_resistor" in bringup.record(service, "L1", [run_id],
                                                                   recipe_id="basic.contact_resistor").message


def test_l1_stage_and_recipe_records_from_a_zero_check_run(stages: VisaWorld) -> None:
    """WP7.1: L1 runs ``system.zero_check``; its hardware run drafts the stage record (cleanup, one floor per SMU)
    and, asked for, the recipe record of ``system.zero_check``."""
    world = stages
    zero = world.service(world.bus(ZERO["scenario"]))
    result = run_case(zero, ZERO)
    assert result.ok and result.run_id is not None and result.run_id.startswith("H"), result.message
    stage = bringup.record(zero, "L1", [result.run_id])  # the zero-check runs of L1 form the stage record
    assert stage.ok and stage.record is not None and stage.record.recipe_id is None
    assert stage.record.key == "stage-l1" and stage.path is not None and "L1-stage-" in stage.path
    checks = {m.check: m for m in stage.record.measurements if m.check}
    assert checks["cleanup_lop"].passed is True
    floors = {slot: checks[f"floor_smu{slot}"] for slot in (3, 4, 5, 6)}
    assert all(m.value is not None and m.method.startswith("zero_floor") for m in floors.values())
    assert floors[3].value < 1e-12 and floors[5].value < 1e-10  # HRSMU / MPSMU sanity bounds of the stage
    assert checks["shutdown_drill"].observed == "not measured in the given runs"
    assert stage.record.result == "pass"  # the judged check (cleanup) passed; observations are the reviewer's
    recipe = bringup.record(zero, "L1", [result.run_id], recipe_id="system.zero_check")
    assert recipe.ok and recipe.record is not None and recipe.record.key == "system.zero_check"
    assert {m.quantity for m in recipe.record.measurements} >= {"smu3_floor", "smu6_floor"}


def test_probe_record_and_capture_on_hardware(stages: VisaWorld) -> None:
    world = stages
    bus = world.bus("lab_station")
    service = world.service(bus)
    report = B1500Admin(service).probe()
    assert report.ok and report.record is not None
    record = bringup.record(service, "L0", probe="latest", operator="owner")
    assert record.ok and record.record is not None and record.record.probe == report.record
    checks = {m.check: m for m in record.record.measurements if m.check}
    assert checks["identity"].passed is True and checks["identity"].observed.startswith("PASS: ")
    assert checks["inventory"].passed is True and record.record.runs == [] and record.record.result == "pass"

    capture = bringup.capture(service, ["probe"])
    assert capture.ok and capture.folder == "work/bringup/fixtures", capture.message
    kinds = {item.kind for item in capture.written}
    assert {"idn", "unt", "errx", "stb", "lop", "lrn", "ermod", "spst", "corrst", "adj"} <= kinds
    for item in capture.written:
        fixture = load_fixture(world.root / item.path)  # the tests/fixtures/flex convention holds
        assert "hardware capture of probe record" in fixture.source and item.parsed
        if fixture.kind == "idn":  # the lab's IDN answers serial 0 already: nothing to anonymize
            assert fixture.body == "Agilent Technologies,B1500A,0,A.06.02.2023.0401" and not fixture.notes


def test_capture_of_a_hardware_run_writes_data_and_query_fixtures(stages: VisaWorld) -> None:
    world = stages
    service = world.service(world.bus(CONTACT["scenario"]))
    run_id = _hardware_run(world, service)
    capture = bringup.capture(service, [run_id])
    assert capture.ok and not capture.skipped, capture.message
    data = [item for item in capture.written if item.kind == "fmt1"]
    assert len(data) == 1 and data[0].path == f"work/bringup/fixtures/{run_id}/fmt1_01.txt"
    fixture = load_fixture(world.root / data[0].path)
    assert fixture.terminator == "crlf" and len(fixture.points) == 42  # 21 steps x (I, source V)
    assert fixture.command.startswith("FMT 1,1; ") and fixture.command.endswith("XE")
    assert fixture.body == (world.run_dir(run_id) / "raw" / "block-000.txt").read_text("latin-1").rstrip("\r\n")
    errx = [item for item in capture.written if item.kind == "errx"]
    assert len(errx) == 1  # identical answers are written once
    (idn,) = [load_fixture(world.root / item.path) for item in capture.written if item.kind == "idn"]
    assert any(e.resp and "SIM0000001" in e.resp for e in world.run_events(run_id))
    assert idn.body.split(",")[2] == "0" and idn.expect["serial"] == "0" and "SIM0000001" not in idn.body
    assert any("anonymized" in note for note in idn.notes)
    refused = bringup.capture(service, [SIM_RUN])
    assert not refused.ok and refused.status == "refused" and "simulator" in refused.message
