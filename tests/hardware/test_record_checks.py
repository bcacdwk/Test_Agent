"""The record checks of the hardware suite on hardware-shaped runs (CI; blueprint v2 7.1, 7.2, 7.4; WP6.4).

The runs are real ``VisaTransport`` runs over the visa-loop: run ids ``H...``, backend visa, cleanups verified with
``LOP?`` behind WP6.2's positive control, so the checks read what they read on the lab PC. The check logic is
exercised with ``RecordView`` objects built here (independent of the schema's class layout). The WP6.3 binding
(``RecordSchema``) and the hardware record tests themselves (a child pytest run over the visa-loop on records that
``b1500 bringup record`` drafted and a temporary ``validation/hw/`` holds as reviewed) need WP6.3's schema and record
writer; they skip with that reason in a clone without them.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import types
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.analysis.dataset import find_run
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.run import RunManifest
from b1500_test_agent.service import B1500Admin, B1500Service
from tests.hardware.records import (
    SCHEMA_MODULE,
    RecordFile,
    RecordInvalid,
    RecordSchema,
    RecordView,
    RunArchive,
    check_file,
    load_schema,
    read_record,
    record_files,
    record_problems,
    required_steps,
    stage_of,
    stray_files,
)
from tests.hardware.rehearsal import REPO_ROOT, run_on_loop
from tests.hardware.support import STAGE_IDS
from tests.sim.helpers import load_scenario
from tests.visa_loop.helpers import MEASUREMENT_CASES, VisaWorld, make_visa_world, run_case
from tests.visa_loop.loop import LoopBus

IDVG = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "mosfet.idvg")
SELF_TEST = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "system.self_test")
CONTACT = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "basic.contact_resistor")
SIM_RUN = "S20261119T080000Z-0a1b"
MISSING_RUN = "H20261119T080000Z-0a1b"
RECIPES: dict[str, Recipe] = {}


def recipes() -> dict[str, Recipe]:
    if not RECIPES:
        registry = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
        RECIPES.update({recipe_id: registry.get(recipe_id) for recipe_id in registry.ids()})
    return RECIPES


def digest(recipe: Recipe) -> str:
    """Stand-in for the schema's digest function: the check compares whatever digest the schema defines."""
    return recipe.sha256


@dataclass
class Station:
    world: VisaWorld
    idvg: str
    """H run of mosfet.idvg: measured, positive control passed, cleanup verified with LOP?."""
    self_test: str
    """H run of system.self_test: no output switched on, so no positive control."""
    probe_ok: str
    probe_fail: str
    """Probe records (repository-relative): a passing probe and one that found an output on."""
    blind: RunArchive
    blind_run: str
    """A run whose LOP? never showed the outputs on: positive control failed, cleanup unverified, fault latched."""

    @property
    def archive(self) -> RunArchive:
        return RunArchive(self.world.data)


@pytest.fixture(scope="module")
def station(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Station]:
    root = tmp_path_factory.mktemp("station")
    world = make_visa_world(root / "main")
    blind_world = make_visa_world(root / "blind")
    try:
        service = world.service(world.bus(IDVG["scenario"]))
        idvg = run_case(service, IDVG)
        self_test = run_case(service, SELF_TEST)
        assert idvg.ok and self_test.ok and idvg.run_id and self_test.run_id, (idvg.message, self_test.message)
        lab = LoopBus(root / "labbus", load_scenario("lab_station"))
        prober = B1500Admin(world.service(lab))
        ok = prober.probe()
        lab.instrument.state.channels[3] = lab.instrument.state.channels[3].model_copy(update={"output_on": True})
        failing = prober.probe()
        lab.instrument.state.channels[3] = lab.instrument.state.channels[3].model_copy(update={"output_on": False})
        assert ok.ok and not failing.ok and ok.record and failing.record
        bus = blind_world.bus(IDVG["scenario"])
        bus.lop_reads_off = True
        blind = run_case(blind_world.service(bus), IDVG)
        assert blind.cleanup_verified == "unverified" and blind.run_id
        yield Station(world, idvg.run_id, self_test.run_id, ok.record, failing.record, RunArchive(blind_world.data),
                      blind.run_id)
    finally:
        world.close()
        blind_world.close()


def committed(name: str = "mosfet.idvg.yaml") -> RecordFile:
    return RecordFile(REPO_ROOT / "validation" / "hw" / name, "validation", f"validation/hw/{name}")


def draft(name: str = "L4-mosfet.idvg.yaml") -> RecordFile:
    return RecordFile(REPO_ROOT / "work" / "bringup" / "records" / name, "draft", f"work/bringup/records/{name}")


def recipe_record(station: Station, **changes: object) -> RecordView:
    recipe = recipes()["mosfet.idvg"]
    view = RecordView(stage="L4", recipe_id=recipe.id, recipe_sha256=digest(recipe), runs=(station.idvg,),
                      result="pass", reviewer="A. Reviewer", evidence={station.idvg: recipe.sha256})
    return replace(view, **changes)  # type: ignore[arg-type]


def problems(view: RecordView, file: RecordFile, archive: RunArchive, root: Path = REPO_ROOT) -> list[str]:
    return record_problems(view, file, archive=archive, recipes=recipes(), digest=digest, repo_root=root)


# -- recipe records ----------------------------------------------------------------------------------------------------


def test_a_reviewed_recipe_record_of_hardware_runs_holds(station: Station) -> None:
    assert problems(recipe_record(station), committed(), station.archive) == []
    assert problems(recipe_record(station, reviewer=""), draft(), station.archive) == []


def test_a_committed_record_needs_a_reviewer_and_the_schema_review(station: Station) -> None:
    found = problems(recipe_record(station, reviewer="", review_problems=("reviewer is empty: x", "result is fail")),
                     committed(), station.archive)
    assert found == [("reviewer is empty: a record in validation/hw/ is a reviewed record (drafts stay in "
                     "work/bringup/records/)"), "result is fail"]


def test_runs_must_be_archived_hardware_runs_of_the_recipe(station: Station) -> None:
    view = recipe_record(station, runs=(station.idvg, SIM_RUN, MISSING_RUN, station.self_test))
    found = problems(view, draft(), station.archive)
    assert any(f"run {SIM_RUN}: not a hardware run" in p for p in found)
    assert any(f"run {MISSING_RUN}: not in" in p and "runs" in p for p in found)
    assert any(f"run {station.self_test}: a run of system.self_test, not of the record's recipe mosfet.idvg" in p
               for p in found)
    assert len(found) == 3, found


def test_a_recipe_record_lists_its_runs_and_pins_the_current_recipe(station: Station) -> None:
    found = problems(recipe_record(station, runs=(), recipe_sha256="0" * 64), draft(), station.archive)
    assert found[0] == "a recipe record lists the hardware runs (H...) it rests on; it lists none"
    assert found[1].startswith("recipe mosfet.idvg changed since the record: recipe_sha256 000000000000...")
    assert problems(recipe_record(station, recipe_id="mosfet.nothing"), draft(), station.archive) == [
        "recipe mosfet.nothing is not in recipes/",
        f"run {station.idvg}: a run of mosfet.idvg, not of the record's recipe mosfet.nothing"]


def test_the_recorded_recipe_file_digest_must_be_the_manifest_s(station: Station) -> None:
    found = problems(recipe_record(station, evidence={station.idvg: "f" * 64}), draft(), station.archive)
    assert found == [(f"run {station.idvg}: the record copied recipe file sha256 ffffffffffff..., the manifest says "
                     f"{recipes()['mosfet.idvg'].sha256[:12]}...")]


def copy_archive(station: Station, tmp_path: Path) -> tuple[RunArchive, Path]:
    """A copy of the station's run archive (to edit) and the copied folder of the Id-Vg run; the archive object reads
    each run once, so edit the folder before the first check."""
    shutil.copytree(station.world.data / "runs", tmp_path / "data" / "runs")
    return RunArchive(tmp_path / "data"), find_run(station.idvg, data_root=tmp_path / "data")


def test_a_run_whose_files_changed_is_no_evidence(station: Station, tmp_path: Path) -> None:
    archive, folder = copy_archive(station, tmp_path)
    assert archive.changed_files(archive.get(station.idvg)) == []  # file digests are computed on every call
    with (folder / "data.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("\n")
    (folder / "quality.json").unlink()
    found = problems(recipe_record(station), draft(), archive)
    assert found == [f"run {station.idvg}: files differ from the sha256 in its manifest: data.csv, quality.json"]


def test_a_passing_record_needs_verified_cleanups_and_passing_positive_controls(station: Station) -> None:
    view = recipe_record(station, runs=(station.blind_run,), evidence={})
    found = problems(view, draft(), station.blind)
    assert any("cleanup verified 'unverified', fault latched True" in p for p in found), found
    assert any("the LOP? positive control failed" in p for p in found), found
    assert problems(replace(view, result="fail"), draft(), station.blind) == []  # a failing draft says so itself


# -- stage records -----------------------------------------------------------------------------------------------------


def stage_record(stage: str, *runs: str, **changes: object) -> RecordView:
    view = RecordView(stage=stage, recipe_id=None, recipe_sha256=None, runs=runs, result="pass", reviewer="")
    return replace(view, **changes)  # type: ignore[arg-type]


def test_the_l1_stage_record_rests_on_a_passing_positive_control(station: Station, tmp_path: Path) -> None:
    file = draft("L1-stage.yaml")
    assert problems(stage_record("L1", station.idvg, station.self_test), file, station.archive) == []
    found = problems(stage_record("L1", station.self_test), file, station.archive)
    assert len(found) == 1 and found[0].startswith("stage L1 record: no run with a passing LOP? positive control")
    assert problems(stage_record("L2", station.self_test), file, station.archive) == []  # only L1 needs it
    archive, folder = copy_archive(station, tmp_path)  # a measured run without a control (cannot happen on visa)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["cleanup"]["positive_control"] = None
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert RunManifest.model_validate(manifest).status_counts
    found = problems(stage_record("L1", station.idvg), file, archive)
    assert found[0].startswith("stage L1 record: no run with a passing LOP? positive control")
    assert found[1:] == [f"run {station.idvg}: measured values but took no LOP? positive control"]


def test_a_schema_2_stage_record_that_claims_pass_lists_every_step(station: Station) -> None:
    """Check 7 (v2.1 plan §4.1, WP21.5): the step list embedded in a passing schema-2 stage record covers every step
    of the stage (``required_steps`` of the committed ``steps.yaml``: record, review and after-record steps left
    out); schema-1 records and recipe records carry no such duty."""
    required = required_steps(REPO_ROOT)
    assert required["S0"][:3] == ("S0.A1", "S0.A2", "S0.P1") and "S0.A5" not in required["S0"]
    assert "S0.A6" not in required["S0"] and "S0.R" not in required["S0"] and len(required["S0"]) == 12
    assert "L10.P6" not in required["L10"] and "L10.A5" not in required["L10"] and "L10.P5" in required["L10"]
    file = draft("S0-stage.yaml")
    complete = replace(stage_record("S0"), schema_version=2, steps=dict.fromkeys(required["S0"], "pass"))
    assert record_problems(complete, file, archive=station.archive, recipes=recipes(), digest=digest,
                           repo_root=REPO_ROOT, stage_steps=required) == []
    gaps = dict(complete.steps, **{"S0.P5": "fail"})
    del gaps["S0.A4"]
    found = record_problems(replace(complete, steps=gaps), file, archive=station.archive, recipes=recipes(),
                            digest=digest, repo_root=REPO_ROOT, stage_steps=required)
    assert len(found) == 1 and found[0].startswith("a schema-2 stage record that claims pass lists every step of "
                                                   "stage S0 as passed; 2 not: S0.P5, S0.A4")
    for exempt in (replace(complete, steps=gaps, schema_version=1), replace(complete, steps=gaps, result=""),
                   replace(recipe_record(station), schema_version=2, steps={})):
        assert record_problems(exempt, file, archive=station.archive, recipes=recipes(), digest=digest,
                               repo_root=REPO_ROOT, stage_steps=required) == []


def test_a_probe_record_must_be_a_passing_visa_probe(station: Station, tmp_path: Path) -> None:
    root = station.world.root
    assert problems(stage_record("L0", probe=station.probe_ok), draft("L0.yaml"), station.archive, root) == []
    assert problems(stage_record("L0", probe="work/bringup/probe-none.json"), draft("L0.yaml"), station.archive,
                    root) == ["probe record work/bringup/probe-none.json not found"]
    with pytest.warns(UserWarning, match="no longer in the work directory"):
        assert problems(stage_record("L0", probe="work/bringup/probe-none.json", reviewer="A. Reviewer"),
                        committed("stage-l0.yaml"), station.archive, root) == []
    failed = problems(stage_record("L0", probe=station.probe_fail), draft("L0.yaml"), station.archive, root)
    assert failed == [f"probe record {station.probe_fail}: failing lines (outputs) in a record that claims pass"]
    assert problems(stage_record("L0", probe=station.probe_fail, result="fail"), draft("L0.yaml"), station.archive,
                    root) == []
    sim = ProbeReport.model_validate_json((root / station.probe_ok).read_text(encoding="utf-8"))
    path = tmp_path / "probe-sim.json"
    path.write_text(sim.model_copy(update={"backend": "sim", "simulated": True}).model_dump_json(), encoding="utf-8")
    found = problems(stage_record("L0", probe=str(path)), draft("L0.yaml"), station.archive, root)
    assert len(found) == 1 and "backend sim, not visa (a simulator probe is never evidence)" in found[0]
    path.write_text("{}", encoding="utf-8")
    assert "is not a probe report" in problems(stage_record("L0", probe=str(path)), draft("L0.yaml"),
                                               station.archive, root)[0]


# -- files -------------------------------------------------------------------------------------------------------------


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_record_files_are_found_in_validation_hw_and_the_drafts(tmp_path: Path) -> None:
    repo, work = tmp_path / "repo", tmp_path / "repo" / "work"
    write(repo / "validation" / "hw" / "README.md", "# review flow\n")
    write(repo / "validation" / "hw" / "mosfet.idvg.yaml", "stage: L4\n")
    write(repo / "validation" / "hw" / "stage-l1.yml", "stage: L1\n")
    (repo / "validation" / "hw" / "old").mkdir()
    write(work / "bringup" / "records" / "_TEMPLATE.yaml", "stage: ''\n")
    write(work / "bringup" / "records" / "L1-stage-20261119.yaml", "stage: L1\n")
    write(work / "bringup" / "records" / "broken.yaml", "stage: [L1\n")
    files = record_files(repo, work)
    assert [(f.shown, f.location, f.committed) for f in files] == [
        ("validation/hw/mosfet.idvg.yaml", "validation", True),
        ("work/bringup/records/L1-stage-20261119.yaml", "draft", False),
        ("work/bringup/records/broken.yaml", "draft", False)]
    assert [stage_of(f.path) for f in files] == ["L4", "L1", None]
    assert stray_files(repo) == ["validation/hw/old", "validation/hw/stage-l1.yml"]
    assert record_files(tmp_path / "empty", tmp_path / "empty") == [] and stray_files(tmp_path / "empty") == []


def test_record_files_parse_strictly(tmp_path: Path) -> None:
    with pytest.raises(RecordInvalid, match="duplicate key"):
        read_record(write(tmp_path / "dup.yaml", "stage: L1\nstage: L2\n"))
    with pytest.raises(RecordInvalid, match="a record is a YAML mapping, not list"):
        read_record(write(tmp_path / "list.yaml", "- stage: L1\n"))
    with pytest.raises(RecordInvalid, match="cannot read it as YAML"):
        read_record(write(tmp_path / "bad.yaml", "stage: [L1\n"))
    assert stage_of(write(tmp_path / "nostage.yaml", "recipe_id: x\n")) is None


def test_without_the_schema_every_record_fails_with_the_reason(tmp_path: Path) -> None:
    file = RecordFile(write(tmp_path / "L1.yaml", "stage: L1\n"), "draft", "work/bringup/records/L1.yaml")
    assert check_file(file, None, archive=RunArchive(tmp_path), recipes={}, repo_root=tmp_path) == [
        f"work/bringup/records/L1.yaml: the record schema ({SCHEMA_MODULE}, WP6.3) is not installed: update the clone"]


def test_the_schema_binding_needs_the_three_names() -> None:
    with pytest.raises(ImportError, match="lacks ValidationRecord, recipe_definition_sha256, reviewed_record_problems"):
        RecordSchema(types.ModuleType("empty"))


# -- with WP6.3's schema and record writer -----------------------------------------------------------------------------


@pytest.fixture
def wp63() -> types.ModuleType:
    """WP6.3's schema module; skips in a clone without it."""
    module = pytest.importorskip(SCHEMA_MODULE, reason="WP6.3's record schema is not installed in this clone")
    from b1500_test_agent import bringup

    if not hasattr(bringup, "record"):
        pytest.skip("WP6.3's b1500 bringup record is not installed in this clone")
    return module


def with_stage_files(world: VisaWorld) -> VisaWorld:
    """``b1500 bringup record`` reads the stage files from the repository root."""
    stages = (".agents", "skills", "b1500-bringup", "stages")
    shutil.copytree(REPO_ROOT.joinpath(*stages), world.root.joinpath(*stages))
    return world


def drafted_l2(world: VisaWorld, service: B1500Service) -> tuple[str, Path]:
    """A ``basic.contact_resistor`` run and its stage L2 draft (``b1500 bringup record L2 --run H... --reference
    r_dmm@H...=<DMM value>``, the DMM 0.5 % off): the run id and the draft's path."""
    from b1500_test_agent import bringup

    run_id = run_case(service, CONTACT).run_id
    assert run_id is not None
    payload = json.loads(next((world.run_dir(run_id) / "analysis").glob("resistance-*.json")).read_text("utf-8"))
    measured = next(r["value"] for r in payload["results"] if r["quantity"] == "resistance")
    drafted = bringup.record(service, "L2", [run_id], references=[f"r_dmm@{run_id}={measured * 1.005}"],
                             operator="owner")
    assert drafted.ok and drafted.path and drafted.record and drafted.record.result == "pass", drafted.message
    return run_id, world.root / drafted.path


def review(draft_path: Path, folder: Path) -> Path:
    """The human's review: fill reviewer and date and move the record to ``validation/hw/<key>.yaml``."""
    data = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    data.update({"reviewer": "A. Reviewer", "reviewed_on": dt.date(2026, 11, 19).isoformat()})
    key = data["recipe_id"] or f"stage-{data['stage'].lower()}"
    return write(folder / f"{key}.yaml", yaml.safe_dump(data, sort_keys=False))


def test_the_binding_reads_wp63_records(wp63: types.ModuleType, tmp_path: Path) -> None:
    schema = load_schema()
    assert isinstance(schema, RecordSchema) and tuple(wp63.STAGE_ORDER) == STAGE_IDS
    recipe = recipes()["basic.contact_resistor"]
    assert schema.recipe_sha256(recipe) == wp63.recipe_definition_sha256(recipe) != recipe.sha256
    world = with_stage_files(make_visa_world(tmp_path / "w"))
    try:
        service = world.service(world.bus(CONTACT["scenario"]))
        run_id, path = drafted_l2(world, service)
        shown = path.relative_to(world.root).as_posix()
        file = RecordFile(path, "draft", shown)
        view = schema.view(read_record(path), file)
        assert (view.stage, view.recipe_id, view.runs, view.reviewer, view.result) == (
            "L2", "basic.contact_resistor", (run_id,), "", "pass")
        assert view.recipe_sha256 == schema.recipe_sha256(recipe) and view.evidence == {run_id: recipe.sha256}
        assert view.schema_version == 2 and view.steps == {}  # v2.1 drafts: schema 2 (no ledger in this world)
        archive = RunArchive(world.data)
        assert check_file(file, schema, archive=archive, recipes=recipes(), repo_root=world.root) == []
        reviewed = review(path, world.root / "validation" / "hw")
        file = RecordFile(reviewed, "validation", "validation/hw/basic.contact_resistor.yaml")
        assert check_file(file, schema, archive=archive, recipes=recipes(), repo_root=world.root) == []
        misnamed = RecordFile(reviewed.rename(reviewed.with_name("contact.yaml")), "validation",
                              "validation/hw/contact.yaml")
        assert check_file(misnamed, schema, archive=archive, recipes=recipes(), repo_root=world.root) == [
            ("validation/hw/contact.yaml: a recipe record of basic.contact_resistor is named "
            "basic.contact_resistor.yaml, not contact.yaml")]
        data = read_record(misnamed.path)
        data["runs"] = [SIM_RUN]
        with pytest.raises(RecordInvalid, match="simulator runs are never recorded"):
            schema.view(data, misnamed)
    finally:
        world.close()


def test_the_hardware_record_tests_pass_and_fail_on_the_visa_loop(wp63: types.ModuleType, tmp_path: Path) -> None:
    """The hardware record tests in a child pytest run, as on the lab PC, on records ``b1500 bringup record`` drafted
    from visa-loop runs and a temporary ``validation/hw/`` holds as reviewed."""
    world = with_stage_files(make_visa_world(tmp_path / "w"))
    try:
        bus = world.bus(CONTACT["scenario"])
        service = world.service(bus)
        run_id, path = drafted_l2(world, service)
        review(path, world.root / "validation" / "hw")
        run = run_on_loop(world, bus, tmp_path, "tests/hardware/test_records.py")
        assert run.returncode == 0, run.output[-4000:]
        assert run.with_status("passed") == ["test_records.py::test_every_record_file_belongs_to_a_stage",
                                             "test_records.py::test_stage_records[L2]"], run.outcomes
        assert len(run.with_status("skipped")) == len(STAGE_IDS) - 1
        folder = world.run_dir(run_id)
        (folder / "data.csv").write_text("edited\n", encoding="utf-8")  # evidence edited after the run
        (world.root / "validation" / "hw" / "notes.txt").write_text("x\n", encoding="utf-8")
        run = run_on_loop(world, bus, tmp_path, "tests/hardware/test_records.py")
        assert run.returncode == 1
        assert run.with_status("failed") == ["test_records.py::test_every_record_file_belongs_to_a_stage",
                                             "test_records.py::test_stage_records[L2]"], run.outcomes
        message = run.outcomes["test_records.py::test_stage_records[L2]"].message
        assert "2 problem(s) in the stage L2 records" in message and "files differ" in message
        assert "validation/hw/notes.txt: not a *.yaml record" in run.outcomes[
            "test_records.py::test_every_record_file_belongs_to_a_stage"].message
    finally:
        world.close()
