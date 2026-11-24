"""Kind ``wgfmu_waveform`` (``catalog/kinds/wgfmu_waveform.py``; blueprint v2 2.7, WP10.4): builder selection, the
compiled envelope (WGFMU channels without compliance, the gate's pulse envelope, ``WaveformLimits`` equal to the
program, RSU routes and phases), SMU bias roles, optional roles, the ``SourcePlan``, estimate and checkpoints, the
``file`` parameters read through ``ParamFiles`` (sha256 re-verified), the table of a run and the refusals."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.files import FileRoots, ParamFileChanged, ParamFiles, resolve_param_file
from b1500_test_agent.catalog.kinds.wgfmu_waveform import (
    CHECKPOINT_S,
    WaveformAcquisition,
    WgfmuWaveformKind,
    stored,
    waveform_table,
)
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver.wgfmu import WgfmuTrace
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import source_plan
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station, pin_map_exact, recipe

pytestmark = pytest.mark.wgfmu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = WgfmuWaveformKind()
MOSFET = pin_map_exact("mosfet-wgfmu", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU"})
BODY = pin_map_exact("mosfet-wgfmu-body", {**MOSFET.terminals, "bulk": 5})
RESISTOR = pin_map_exact("resistor-wgfmu", {"a": "RSU201.OUT", "b": "GNDU"})
RSU201 = Route(switch="RSU201", output="OUT", state="wgfmu")
RSU202 = Route(switch="RSU202", output="OUT", state="wgfmu")


def compile_recipe(rec: Recipe | str, pm: Any = MOSFET, files: ParamFiles | None = None, **values: Any):
    rec = REGISTRY.get(rec) if isinstance(rec, str) else rec
    binding = bind_roles(rec, pm, STATION, pm.name)
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, STATION, files=files)


def plan_of(compiled: Any) -> PlanRecord:
    return PlanRecord.model_construct(plan_id="P-TESTTESTTE", program=compiled.program)


def variant(recipe_id: str, **changes: Any) -> Recipe:
    data = REGISTRY.get(recipe_id).model_dump(mode="json", exclude={"sha256"}, by_alias=True)
    data.update(copy.deepcopy(changes))
    return recipe(data)


def library_files(tmp_path: Path | None = None, **override: bytes) -> tuple[ParamFiles, dict[str, Any]]:
    """The custom-waveform defaults as ``ParamFiles`` (library files; ``override`` swaps contents via work/)."""
    work = (tmp_path or Path("/nonexistent")) / "work"
    roots = FileRoots.of(REPO_ROOT / "recipes", work)
    values: dict[str, Any] = {}
    for name, data in override.items():
        target = work / "waveforms" / f"{name}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        values[name] = f"work/waveforms/{name}.csv"
    rec = REGISTRY.get("wgfmu.custom_waveform")
    params = resolve_params(rec, values)[0]
    records = {n: resolve_param_file(str(params[n].value), roots) for n in ("gate_wave", "drain_wave", "events")}
    return ParamFiles(records, roots), values


# -- compile ---------------------------------------------------------------------------------------------------------


def test_pulsed_iv_envelope_limits_routes_and_source_plan() -> None:
    compiled = compile_recipe("wgfmu.pulsed_iv")
    gate, drain = compiled.envelope.channels[201], compiled.envelope.channels[202]
    assert (gate.function, gate.max_abs_i, gate.max_abs_v) == ("wgfmu", None, 2.0)
    assert (drain.function, drain.max_abs_i, drain.max_abs_v, drain.pulse) == ("wgfmu", None, 1.0, None)
    assert gate.pulse is not None
    assert (gate.pulse.max_abs_v_dut, gate.pulse.max_count, gate.pulse.max_width_s) == (2.0, 1, pytest.approx(1e-5))
    assert gate.pulse.max_duty == pytest.approx(0.01) and gate.pulse.max_short_circuit_a == pytest.approx(0.1)
    sources = source_plan(compiled.program)
    program = sources.waveform
    assert program is not None and program.builder == "pulsed_iv"
    for ch in (201, 202):
        limits = compiled.envelope.waveform[ch]
        assert limits.max_points == program.points(ch) and limits.total_time_s == program.sequence_time_s(ch)
        assert limits.max_vectors == wf.max_vectors(program, ch) and limits.grid_s == 1e-8
    assert sum(t.total_pulses for t in sources.trains(201)) == 21
    assert compiled.envelope.routes == frozenset({RSU201, RSU202})
    assert compiled.routes_by_phase == {"waveform": [RSU201, RSU202], "rest": [
        Route(switch="RSU201", output="OUT", state="open"), Route(switch="RSU202", output="OUT", state="open")]}
    assert compiled.flex_preview == []
    assert compiled.estimate.points == 21
    assert compiled.estimate.duration_s == pytest.approx(0.5 + program.total_time_s() + program.total_time_s()
                                                         + 21 * 2e-6)
    stored_program, waveform, _ = stored(plan_of(compiled))
    assert (stored_program.builder, stored_program.cycle_by, stored_program.rows) == ("pulsed_iv", "point", 21)
    assert [r.role for r in stored_program.roles] == ["gate", "drain"] and waveform == program


def test_the_kind_program_is_deterministic() -> None:
    first, second = compile_recipe("wgfmu.pulse_train"), compile_recipe("wgfmu.pulse_train")
    assert first.program == second.program and first.envelope == second.envelope


def test_an_smu_body_bias_is_held_around_the_waveform() -> None:
    compiled = compile_recipe("wgfmu.pulsed_iv", BODY, vb=-0.5)
    bulk = compiled.envelope.channels[5]
    assert (bulk.function, bulk.max_abs_v, bulk.max_abs_i, bulk.v_start) == ("bias_v", 0.5, 1e-4, -0.5)
    assert compiled.flex_preview == ["CN 5", "DV 5,0,-0.5,0.0001"]
    program, _, _ = stored(plan_of(compiled))
    assert [(b.role, b.channel, b.level) for b in program.biases] == [("bulk", 5, -0.5)]


def test_an_optional_wgfmu_role_the_pin_map_does_not_land_is_left_out() -> None:
    compiled = compile_recipe("wgfmu.dc_spot", RESISTOR)
    assert set(compiled.envelope.channels) == {201} and compiled.envelope.routes == frozenset({RSU201})
    program, waveform, _ = stored(plan_of(compiled))
    assert waveform.dc == {201: [-0.1, -0.05, 0.0, 0.05, 0.1]} and program.rows == 5
    assert compiled.estimate.points == 5 and KIND.checkpoint_total(plan_of(compiled)) == 5
    both = pin_map_exact("two", {**RESISTOR.terminals, "c": "RSU202.OUT"})
    compiled = compile_recipe("wgfmu.dc_spot", both, samples=3)
    assert set(compiled.envelope.channels) == {201, 202} and compiled.estimate.points == 15


def test_an_unbound_wgfmu_role_compiles_an_empty_envelope_for_r_pin_01() -> None:
    compiled = compile_recipe("wgfmu.pulsed_iv", pin_map_exact("half", {"gate": "RSU201.OUT", "source": "GNDU"}))
    assert compiled.envelope.channels == {} and compiled.estimate.points == 0
    assert compiled.envelope.routes == frozenset({RSU201}) and compiled.program == {}


def test_a_wgfmu_channel_named_directly_compiles_without_a_route_for_r_wg_01() -> None:
    compiled = compile_recipe("wgfmu.pulsed_iv", pin_map_exact("direct", {"gate": 201, "drain": 202,
                                                                         "source": "GNDU"}))
    assert set(compiled.envelope.channels) == {201, 202} and compiled.envelope.routes == frozenset()
    assert compiled.routes_by_phase == {}


def test_checkpoints_follow_the_sequencer_time() -> None:
    compiled = compile_recipe("wgfmu.pulse_train", count=100000, period=2e-4)
    program, waveform, _ = stored(plan_of(compiled))
    assert waveform.total_time_s() == pytest.approx(20.0, rel=1e-3)
    assert program.chunks == 3 and KIND.checkpoint_total(plan_of(compiled)) == 4
    assert compiled.estimate.max_segment_s == pytest.approx(CHECKPOINT_S + 0.5)


@pytest.mark.parametrize(("change", "match"), [
    ({"params": {"builder": {"type": "enum", "choices": ["warp"], "default": "warp"}}}, "builder must be one of"),
    ({"roles": {"gate": {"function": "pulse_v", "module_types": ["HRSMU"]}}}, "cannot execute role"),
    ({"roles": {"source": {"function": "ground", "allow_gndu": True}}}, "has no wgfmu role"),
])  # fmt: skip
def test_requests_the_kind_cannot_express(change: dict[str, Any], match: str) -> None:
    data = REGISTRY.get("wgfmu.pulsed_iv").model_dump(mode="json", exclude={"sha256"}, by_alias=True)
    for key, value in change.items():
        data[key] = {**data[key], **value} if key == "params" else value
    with pytest.raises(CompileError, match=match):
        compile_recipe(recipe(data))


def test_a_wgfmu_channel_measures_one_quantity() -> None:
    rec = variant("wgfmu.pulsed_iv", roles={**REGISTRY.get("wgfmu.pulsed_iv").model_dump(mode="json")["roles"],
                                            "drain": {"function": "wgfmu", "measure": ["I", "V"],
                                                      "settings": {"v": "$vd"}}})
    with pytest.raises(CompileError, match="one quantity"):
        compile_recipe(rec)


# -- file parameters -------------------------------------------------------------------------------------------------


def test_the_table_builder_reads_its_files_through_param_files() -> None:
    files, _ = library_files()
    compiled = compile_recipe("wgfmu.custom_waveform", files=files)
    program = source_plan(compiled.program).waveform
    assert program is not None and program.builder == "table"
    assert len(program.patterns["gate"].vectors) == 199 and program.points(201) == program.points(202) == 55200
    assert program.channels[202].current_range == "100ua" and program.channels[201].measure == "voltage"
    with pytest.raises(CompileError, match="read through the planner"):
        compile_recipe("wgfmu.custom_waveform")


def test_a_file_changed_after_hashing_is_refused(tmp_path: Path) -> None:
    files, values = library_files(tmp_path, events=b"0,10,1e-6,0,0,0\n")
    compile_recipe("wgfmu.custom_waveform", files=files, **values)
    (tmp_path / "work/waveforms/events.csv").write_bytes(b"0,20,1e-6,0,0,0\n")
    with pytest.raises(ParamFileChanged, match="changed since the plan was validated"):
        compile_recipe("wgfmu.custom_waveform", files=files, **values)
    assert files.records["events"].sha256 == hashlib.sha256(b"0,10,1e-6,0,0,0\n").hexdigest()
    with pytest.raises(ParamFileChanged, match="no file parameter"):
        files.read("nope")


# -- table -----------------------------------------------------------------------------------------------------------


def run_traces(compiled: Any, current: float = 1e-4, *, shift: float = 0.0) -> dict[int, WgfmuTrace]:
    _, waveform, _ = stored(plan_of(compiled))
    traces = {}
    for ch in sorted(waveform.sequences):
        layout = wf.point_layout(waveform, ch)
        if not len(layout):
            continue
        times = layout.start_s + layout.average_s / 2 + shift
        quantity = "I" if waveform.channels[ch].measure == "current" else "V"
        traces[ch] = WgfmuTrace(channel=ch, quantity=quantity, time_s=times, value=np.full(len(times), current))
    return traces


def test_pulsed_table_columns_programmed_levels_and_overflow_status() -> None:
    compiled = compile_recipe("wgfmu.pulsed_iv", vg_points=3, irange="100ua")
    program, waveform, _ = stored(plan_of(compiled))
    table = waveform_table(program, waveform, run_traces(compiled, current=1e-4))
    assert list(table.columns) == ["step", "t_s", "cycle", "event", "drain_range", "gate_V", "drain_V", "drain_I",
                                   "drain_I_status"]
    assert list(table["gate_V"]) == [0.0, 1.0, 2.0] and set(table["drain_V"]) == {1.0}
    assert list(table["cycle"]) == [0, 1, 2] and set(table["event"]) == {"plateau"}
    assert set(table["drain_I_status"]) == {"V"}  # 100 uA on the 100 uA range: saturated
    table = waveform_table(program, waveform, run_traces(compiled, current=5e-5))
    assert set(table["drain_I_status"]) == {"N"} and set(table["drain_range"]) == {"100ua"}


def test_fast_iv_table_has_segments_and_body_bias_columns() -> None:
    rec = variant("wgfmu.fast_iv")
    compiled = compile_recipe(rec, ramp=1e-6, interval=1e-7)
    program, waveform, _ = stored(plan_of(compiled))
    table = waveform_table(program, waveform, run_traces(compiled))
    assert list(table["segment"]) == ["fwd"] * 10 + ["rev"] * 10
    assert table["gate_V"].iloc[0] == pytest.approx(0.1) and table["gate_V"].iloc[-1] == pytest.approx(0.1)
    body = compile_recipe("wgfmu.pulsed_iv", BODY, vg_points=2, vb=-0.5)
    program, waveform, _ = stored(plan_of(body))
    assert list(waveform_table(program, waveform, run_traces(body))["bulk_V"]) == [-0.5, -0.5]


def test_readings_that_do_not_match_the_program_are_refused() -> None:
    compiled = compile_recipe("wgfmu.pulsed_iv", vg_points=3)
    program, waveform, _ = stored(plan_of(compiled))
    with pytest.raises(ValueError, match="no readback of channel 202"):
        waveform_table(program, waveform, {})
    short = {202: WgfmuTrace(202, "I", np.zeros(2), np.zeros(2))}
    with pytest.raises(ValueError, match="returned 2 values"):
        waveform_table(program, waveform, short)
    with pytest.raises(ValueError, match="outside the program's measurement windows"):
        waveform_table(program, waveform, run_traces(compiled, shift=1e-3))
    assert KIND.to_table(WaveformAcquisition(traces=run_traces(compiled)), plan_of(compiled)) is not None


def test_two_measuring_channels_share_their_time_stamps() -> None:
    files, _ = library_files()
    compiled = compile_recipe("wgfmu.custom_waveform", files=files)
    program, waveform, _ = stored(plan_of(compiled))
    traces = run_traces(compiled)
    table = waveform_table(program, waveform, traces)
    assert list(table.columns) == ["step", "t_s", "event", "drain_range", "gate_V", "gate_V_status", "drain_V",
                                   "drain_I", "drain_I_status"]
    assert len(table) == 55200 and "cycle" not in table.columns
    skewed = {**traces, 201: WgfmuTrace(201, "V", traces[201].time_s + 2e-8, traces[201].value)}
    with pytest.raises(ValueError, match="different times"):
        waveform_table(program, waveform, skewed)


def test_dc_rows_must_be_complete() -> None:
    compiled = compile_recipe("wgfmu.dc_spot", RESISTOR)
    with pytest.raises(ValueError, match="0 DC readings, 5 planned"):
        KIND.to_table(WaveformAcquisition(), plan_of(compiled))
