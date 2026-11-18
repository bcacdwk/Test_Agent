"""Planner v2 (blueprint v2 2.3, decision 21): ``file`` parameters hashed into the plan, re-checked before a run,
and roles bound through switch outputs and MFCMU sides (WP5.3)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.catalog.executor import Executor
from b1500_test_agent.catalog.files import (
    FileRoots,
    ParamFileChanged,
    changed_param_files,
    read_param_file,
    resolve_param_file,
)
from b1500_test_agent.catalog.planner import Planner, PlanStaleError, bind_roles
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompiledKindPlan
from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import ChannelBinding, CompiledEnvelope, Estimate, PlanRecord, PlanRequest
from b1500_test_agent.models.recipe import FILE_PARAM_MAX_BYTES, Recipe
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.station import StationProfile
from b1500_test_agent.paths import ENV_DATA_DIR, Paths
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import CMU, IDVG, T0, bundle, dut, engine, example_station, pin_map, recipe, station

LIBRARY_CSV = "recipes/waveforms/lib.csv"
WORK_CSV = "work/waveforms/adhoc.csv"
TABLE_RECIPE = f"""\
id: test.table
version: 1
title: Waveform table (test recipe)
family: wgfmu
kind: test_table
status: draft
card: null
device_types: []
roles: {{}}
params:
  wave: {{type: file, default: {LIBRARY_CSV}, doc: waveform table}}
quality: {{}}
provenance: {{sources: [test], validation_runs: []}}
"""


class TableKind:
    """A pure stand-in kind: compiles the ``file`` parameter's path into its program (no I/O, no outputs)."""

    kind_id = "test_table"
    implemented_on: frozenset[Backend] = frozenset({"sim"})

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        return CompiledKindPlan(envelope=CompiledEnvelope(channels={}), estimate=Estimate(points=1, duration_s=0.1),
                                flex_preview=["*OPC?"], program={"table": str(params["wave"].value)})

    def acquire(self, tx: Any, plan: PlanRecord) -> Any:  # pragma: no cover - never run here
        raise AssertionError("not executed in these tests")

    def to_table(self, raw: Any, plan: PlanRecord) -> None:  # pragma: no cover
        return None


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    """A recipes folder with ``test.table`` and its library CSV, and a work folder for ad-hoc CSVs."""
    recipes = tmp_path / "recipes"
    (recipes / "test").mkdir(parents=True)
    (recipes / "test" / "table.yaml").write_text(TABLE_RECIPE, encoding="utf-8")
    (recipes / "waveforms").mkdir()
    (recipes / "waveforms" / "lib.csv").write_text("time,level\n0,0\n1e-6,1\n", encoding="utf-8")
    (tmp_path / "work" / "waveforms").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'tmp'\n", encoding="utf-8")
    return {"root": tmp_path, "recipes": recipes, "work": tmp_path / "work"}


def registry(world: dict[str, Path]) -> RecipeRegistry:
    reg = RecipeRegistry.load(world["recipes"], kinds={"test_table": TableKind()}, repo_root=world["root"])
    assert reg.problems() == []
    return reg


def plan(world: dict[str, Path], **params: Any) -> PlanRecord:
    cfg = bundle(pin_maps=[pin_map()], paths=Paths.from_env({}, repo_root=world["root"]))
    req = PlanRequest(recipe_id="test.table", pin_map="mosfet-4t", params=params)
    return Planner(registry(world), clock=lambda: T0).plan(req, cfg, engine(cfg))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -- file parameters -------------------------------------------------------------------------------------------------


def test_library_file_is_hashed_into_the_plan(world: dict[str, Path]) -> None:
    record = plan(world)
    assert record.tier == "ok" and record.program == {"table": LIBRARY_CSV}
    wave = record.files["wave"]
    assert (wave.path, wave.origin, wave.problem) == (LIBRARY_CSV, "library", None)
    assert wave.sha256 == sha("time,level\n0,0\n1e-6,1\n") and wave.size_bytes == 22


def test_plan_hash_changes_with_the_csv_content(world: dict[str, Path]) -> None:
    csv = world["work"] / "waveforms" / "adhoc.csv"
    csv.write_text("time,level\n0,0\n", encoding="utf-8")
    first, again = plan(world, wave=WORK_CSV), plan(world, wave=WORK_CSV)
    assert first.plan_id == again.plan_id  # same content: same plan
    csv.write_text("time,level\n0,0.5\n", encoding="utf-8")
    second = plan(world, wave=WORK_CSV)
    assert second.files["wave"].sha256 != first.files["wave"].sha256
    assert second.plan_hash != first.plan_hash and second.plan_id != first.plan_id
    assert second.request == first.request and second.program == first.program  # only the file content differs


def test_work_file_needs_confirmation_as_adhoc(world: dict[str, Path]) -> None:
    (world["work"] / "waveforms" / "adhoc.csv").write_text("time,level\n0,0\n", encoding="utf-8")
    record = plan(world, wave=WORK_CSV)
    assert record.tier == "needs_confirmation" and record.rules.confirm_reasons == ["adhoc_recipe"]
    [finding] = [f for f in record.rules.findings if f.rule_id == "R-ALWAYS-01"]
    assert finding.observed == WORK_CSV and finding.source == "plan:files.wave"
    assert "R-ALWAYS-01 adhoc_recipe" in record.summary


@pytest.mark.parametrize(("value", "setup", "problem"), [
    (WORK_CSV, None, "does not exist"),
    (WORK_CSV, "big", f"more than {FILE_PARAM_MAX_BYTES}"),
    ("work/waveforms/folder.csv", "dir", "is not a file"),
])
def test_unusable_files_block_the_plan(world: dict[str, Path], value: str, setup: str | None, problem: str) -> None:
    target = world["work"] / "waveforms" / value.split("/")[-1]
    if setup == "big":
        target.write_bytes(b"0," * (FILE_PARAM_MAX_BYTES // 2 + 1))
    elif setup == "dir":
        target.mkdir()
    record = plan(world, wave=value)
    assert record.tier == "blocked" and record.program == {}  # compilation skipped
    assert problem in (record.files["wave"].problem or "")
    assert any(f.rule_id == "R-PARAM-01" and problem in f.message for f in record.rules.findings)


@pytest.mark.parametrize("value", ["work/waveforms/../escape.csv", "/etc/passwd.csv", "config/local/policy.csv",
                                   "work/waveforms/table.txt"])
def test_paths_outside_the_two_folders_are_refused(world: dict[str, Path], value: str) -> None:
    record = plan(world, wave=value)
    assert record.tier == "blocked" and "wave" not in record.files
    assert any(f.rule_id == "R-PARAM-01" and f.source.endswith("params.wave.type") for f in record.rules.findings)


def test_a_link_out_of_the_folder_is_refused(world: dict[str, Path]) -> None:
    outside = world["root"] / "secret.csv"
    outside.write_text("1,2\n", encoding="utf-8")
    try:
        (world["work"] / "waveforms" / "link.csv").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here (Windows without developer mode)")
    record = plan(world, wave="work/waveforms/link.csv")
    assert record.tier == "blocked" and "resolves outside" in (record.files["wave"].problem or "")


def test_changed_files_are_detected_and_reads_reverify(world: dict[str, Path]) -> None:
    roots = FileRoots.of(world["recipes"], world["work"])
    csv = world["work"] / "waveforms" / "adhoc.csv"
    csv.write_text("a\n", encoding="utf-8")
    record = resolve_param_file(WORK_CSV, roots)
    assert read_param_file(record, roots) == b"a\n"
    assert changed_param_files({"wave": record}, roots) == []
    csv.write_text("b\n", encoding="utf-8")
    assert changed_param_files({"wave": record}, roots) == ["wave"]
    with pytest.raises(ParamFileChanged):
        read_param_file(record, roots)
    os.remove(csv)
    assert changed_param_files({"wave": record}, roots) == ["wave"]
    with pytest.raises(ParamFileChanged):
        read_param_file(resolve_param_file(WORK_CSV, roots), roots)  # a record with a problem is never readable


def test_executor_refuses_a_plan_whose_file_changed(world: dict[str, Path], repo: Path, tmp_path: Path) -> None:
    """Steps 1-3 of a run re-check the CSV digest: an edited file makes the stored plan ``plan_stale``."""
    paths = Paths.from_env({ENV_DATA_DIR: str(tmp_path / "data")}, repo_root=repo)
    (paths.work_dir / "waveforms").mkdir(parents=True)
    csv = paths.work_dir / "waveforms" / "adhoc.csv"
    csv.write_text("time,level\n0,0\n", encoding="utf-8")
    reg = RecipeRegistry.load(world["recipes"], kinds={"test_table": TableKind()}, repo_root=world["root"])
    executor = Executor(ConfigLoader(paths), registry=reg, clock=lambda: T0)
    stored = executor.plan(PlanRequest(recipe_id="test.table", pin_map="mosfet-4t", params={"wave": WORK_CSV}))
    assert executor.revalidate(stored.plan_id).plan_id == stored.plan_id
    csv.write_text("time,level\n0,40\n", encoding="utf-8")
    with pytest.raises(PlanStaleError, match=r"file parameter\(s\) wave \(work/waveforms/adhoc.csv\) changed"):
        executor.revalidate(stored.plan_id)


def test_registry_checks_file_defaults(world: dict[str, Path]) -> None:
    (world["recipes"] / "waveforms" / "lib.csv").unlink()
    problems = RecipeRegistry.load(world["recipes"], kinds={"test_table": TableKind()},
                                   repo_root=world["root"]).problems()
    assert problems == [(f"recipes/test/table.yaml: params.wave: default {LIBRARY_CSV} does not exist in the "
                         "waveform library")]


# -- binding through switches and MFCMU sides ------------------------------------------------------------------------

WIRED = station(switches=[{**example_station().switches[0].model_dump(mode="json"),
                           "ports": {"OUT1": {"index": 0, "inputs": {"smu": 5, "pgu": 101}},
                                     "OUT2": {"index": 1, "inputs": {"smu": 6, "pgu": 102}}}}])


def test_switch_targets_bind_through_the_route_of_the_role_resource() -> None:
    smu_roles = bind_roles(recipe(), pin_map(gate="SEL1.OUT1"), WIRED, "fefet-sel").roles
    gate = smu_roles["gate"]
    assert gate.via == Route(switch="SEL1", output="OUT1", state="smu")
    assert (gate.channel, gate.module_type, gate.alias) == (5, "MPSMU", "SMU5")
    pulse = recipe(IDVG, roles={**IDVG["roles"], "gate": {"function": "pgu", "module_types": ["HVSPGU"]}})
    pgu = bind_roles(pulse, pin_map(gate="SEL1.OUT1"), WIRED, "fefet-sel").roles["gate"]
    assert pgu.via == Route(switch="SEL1", output="OUT1", state="pgu")
    assert (pgu.channel, pgu.module_type, pgu.alias) == (101, "HVSPGU", "SPGU1")
    unknown = bind_roles(recipe(), pin_map(gate="SEL1.OUT1"), example_station(), "fefet-sel").roles["gate"]
    assert unknown.via is not None and unknown.channel is None and unknown.module_type is None  # wiring null
    undeclared = bind_roles(recipe(), pin_map(gate="SEL9.OUT1"), WIRED, "x").roles["gate"]
    assert undeclared.via == Route(switch="SEL9", output="OUT1", state="smu") and undeclared.channel is None


def test_cmu_side_targets_bind_to_the_mfcmu_with_its_side() -> None:
    bound = bind_roles(recipe(CMU), pin_map(name="moscap-cmu", gate="7H"), example_station(), "moscap-cmu")
    gate = bound.roles["gate"]
    assert (gate.channel, gate.cmu_side, gate.module_type, gate.alias, gate.via) == (7, "H", "MFCMU", "CMU1", None)


@pytest.mark.parametrize(("profile", "message"), [
    (example_station(), "the smu input of SEL1.OUT1 is unknown (null) in the station profile"),
    (WIRED, "reaches its terminal only through SEL1.OUT1->smu, but the plan sets no such route"),
])
def test_a_v1_kind_cannot_use_a_switch_target(profile: StationProfile, message: str) -> None:
    """``mosfet.idvg`` (kind ``smu_staircase``) on a gate wired through SEL1: blocked by R-PIN-01, never compiled
    into a run that would source SMU5 with the selector in an unknown state."""
    pm = pin_map(gate="SEL1.OUT1")
    cfg = bundle(station_profile=profile, pin_maps=[pm], duts=[dut()])
    reg = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
    req = PlanRequest(recipe_id="mosfet.idvg", pin_map="mosfet-4t", dut_profile="nmos-generic")
    record = Planner(reg, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert record.tier == "blocked" and record.routes_by_phase == {} and record.envelope.routes == frozenset()
    assert any(f.rule_id == "R-PIN-01" and message in f.message for f in record.rules.findings)
