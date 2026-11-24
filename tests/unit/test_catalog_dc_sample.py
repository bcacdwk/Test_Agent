"""Builder ``dc_sample`` (``catalog/waveforms.py``; blueprint v2 2.7.1, WP10.5) and its recipes ``wgfmu.rtn`` and
``wgfmu.lfn`` compiled by kind ``wgfmu_waveform``: the constant-bias pattern (edge, settle, sampling span, edge back,
long holds split below the library's vector limit), one measurement event per measuring channel on the 10 ns grid,
the channels' common timing, the role's force-range override (the lab's 5 V range), the data layout and programmed
levels, the compiled envelope, limits, routes and estimate, determinism and the refusals."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.kinds.wgfmu_waveform import WAVEFORM_BUILDERS, WgfmuWaveformKind, stored
from b1500_test_agent.catalog.planner import bind_roles, resolve_params
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.models.plan import PlanRecord
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import MeasureEvent, on_grid
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import example_station, pin_map_exact

pytestmark = pytest.mark.wgfmu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
STATION = example_station()
KIND = WgfmuWaveformKind()
MOSFET = pin_map_exact("mosfet-wgfmu", {"gate": "RSU201.OUT", "drain": "RSU202.OUT", "source": "GNDU"})
GATE = wf.WgRole(role="gate", channel=201)
GATE_V = wf.WgRole(role="gate", channel=201, measure="V", force_range="5v")
DRAIN = wf.WgRole(role="drain", channel=202, measure="I", current_range="100ua")
TIMING: dict[str, Any] = {"points": 1000, "interval": 1e-6, "average": 1e-6, "edge": 1e-7, "settle": 1e-4}


def sample(channels: list[tuple[wf.WgRole, float]] | None = None, **changes: Any) -> wf.BuiltWaveform:
    return wf.dc_sample(channels if channels is not None else [(GATE, 1.0), (DRAIN, 0.1)], **{**TIMING, **changes})


def compile_recipe(recipe_id: str, **values: Any) -> Any:
    rec = REGISTRY.get(recipe_id)
    binding = bind_roles(rec, MOSFET, STATION, MOSFET.name)
    return KIND.compile(rec, resolve_params(rec, values)[0], binding, STATION)


# -- the builder -----------------------------------------------------------------------------------------------------


def test_dc_sample_is_a_registered_builder() -> None:
    assert "dc_sample" in wf.BUILDERS and "dc_sample" in WAVEFORM_BUILDERS


def test_every_channel_ramps_holds_and_returns_on_the_grid() -> None:
    program = sample().program
    assert program.builder == "dc_sample" and set(program.sequences) == {201, 202}
    span = 1e-6 * 999 + 1e-6  # interval x (points - 1) + average
    for name, level in (("gate", 1.0), ("drain", 0.1)):
        pattern = program.patterns[name]
        assert pattern.v0 == 0.0 and pattern.levels() == [0.0, level, level, 0.0]
        assert pattern.vectors[0][0] == pytest.approx(1e-7) and pattern.vectors[-1][0] == pytest.approx(1e-7)
        assert pattern.vectors[1][0] == pytest.approx(1e-4 + span, rel=1e-12)
        assert all(on_grid(dt, wf.TICK_S) for dt, _ in pattern.vectors)
    assert program.sequences == {201: [("gate", 1.0)], 202: [("drain", 1.0)]}
    assert program.total_time_s() == pytest.approx(2e-7 + 1e-4 + span, rel=1e-12)


def test_one_event_per_measuring_channel_starts_after_edge_and_settle() -> None:
    program = sample([(GATE_V, 1.0), (DRAIN, 0.1)]).program
    events = program.events
    assert [e.pattern for e in events] == ["gate", "drain"] and all(isinstance(e, MeasureEvent) for e in events)
    for event in events:
        assert isinstance(event, MeasureEvent)
        assert (event.event, event.points, event.raw) == ("sample", 1000, False)
        assert event.t == pytest.approx(1e-7 + 1e-4) and event.interval == pytest.approx(1e-6)
        assert event.average == pytest.approx(1e-6)
        assert event.end_s <= program.patterns[event.pattern].duration_s + 1e-15  # inside its pattern
    only_drain = sample()
    assert [e.pattern for e in only_drain.program.events] == ["drain"]  # the gate is not measured
    assert only_drain.program.points(201) == 0 and only_drain.program.points(202) == 1000


def test_channel_setups_keep_the_lab_layout() -> None:
    program = sample([(GATE_V, 1.0), (DRAIN, 0.1)]).program
    gate, drain = program.channels[201], program.channels[202]
    assert (gate.mode, gate.force_range, gate.measure, gate.voltage_range) == ("fastiv", "5v", "voltage", "5v")
    assert (drain.mode, drain.force_range, drain.measure, drain.current_range) == ("fastiv", "3v", "current", "100ua")
    fixed = sample([(GATE_V, 1.0), (DRAIN.model_copy(update={"force_range": "5v"}), 0.1)]).program
    assert fixed.channels[202].force_range == "5v"


def test_a_named_force_range_must_hold_the_levels() -> None:
    with pytest.raises(CompileError, match="do not fit its force range 3v"):
        sample([(GATE.model_copy(update={"force_range": "3v"}), 4.0), (DRAIN, 0.1)])
    with pytest.raises(CompileError, match="do not fit its force range 10v"):
        sample([(GATE.model_copy(update={"force_range": "10v"}), -1.0), (DRAIN, 0.1)])


def test_no_averaging_takes_single_samples_and_ends_ten_ns_after_the_last_point() -> None:
    program = sample(average=0.0).program
    event = program.events[0]
    assert isinstance(event, MeasureEvent) and event.average == 0.0 and not event.raw
    assert program.patterns["drain"].vectors[1][0] == pytest.approx(1e-4 + 999e-6 + 1e-8, rel=1e-12)


def test_a_long_hold_is_split_below_the_vector_limit() -> None:
    program = sample(points=40_000, interval=1.0, average=1e-3, settle=1.0).program
    holds = program.patterns["drain"].vectors[1:-1]
    assert len(holds) == 5 and all(dt <= wf.HOLD_VECTOR_MAX_S for dt, _ in holds)  # 40,001.001 s in 5 equal parts
    assert {v for _, v in holds} == {0.1}
    assert math.fsum(dt for dt, _ in holds) == pytest.approx(1.0 + 39_999.0 + 1e-3, rel=1e-12)
    assert all(on_grid(dt, wf.TICK_S) for dt, _ in holds)


def test_layout_and_programmed_levels_follow_the_event() -> None:
    program = sample([(GATE_V, 1.0), (DRAIN, 0.1)]).program
    layout = wf.point_layout(program, 202)
    assert len(layout) == 1000 and set(layout.event) == {"sample"} and set(layout.range) == {"100ua"}
    np.testing.assert_allclose(layout.start_s, 1e-7 + 1e-4 + np.arange(1000) * 1e-6, rtol=0, atol=1e-15)
    times = layout.start_s + layout.average_s / 2
    assert np.all(wf.program_levels(program, 201, times) == 1.0)
    assert np.all(wf.program_levels(program, 202, times) == 0.1)
    assert wf.program_levels(program, 201, np.asarray([0.0, 5e-8]))[1] == pytest.approx(0.5)  # on the ramp


def test_dc_sample_is_deterministic() -> None:
    assert sample().program.model_dump() == sample().program.model_dump()


@pytest.mark.parametrize(("changes", "message"), [
    ({"points": 0}, "points must be a positive integer"),
    ({"points": 2.5}, "points must be a positive integer"),
    ({"interval": 4e-9}, "interval"),
    ({"edge": 0.0}, "edge"),
    ({"settle": -1.0}, "settle"),
    ({"average": float("nan")}, "average"),
])  # fmt: skip
def test_unusable_inputs_are_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        sample(**changes)


def test_without_channels_or_measurement_there_is_no_program() -> None:
    with pytest.raises(CompileError, match="at least one WGFMU channel"):
        sample([])
    with pytest.raises(CompileError, match="no role measures"):
        sample([(GATE, 1.0)])


# -- the recipes through the kind ------------------------------------------------------------------------------------


def test_rtn_recipe_compiles_to_one_drain_record() -> None:
    out = compile_recipe("wgfmu.rtn")
    program, waveform, sources = stored(PlanRecord.model_construct(plan_id="P-TESTTESTTE", program=out.program))
    assert program.builder == "dc_sample" and program.rows == 400_000 and [r.role for r in program.measuring] == [
        "drain"]
    assert sources.pulses == {} and waveform.points(202) == 400_000 and waveform.points(201) == 0
    assert waveform.channels[201].force_range == waveform.channels[202].force_range == "5v"
    assert waveform.channels[202].current_range == "100ua"
    gate, drain = out.envelope.channels[201], out.envelope.channels[202]
    assert (gate.max_abs_v, drain.max_abs_v) == (1.0, 0.1) and gate.max_abs_i is None and gate.pulse is None
    limits = out.envelope.waveform[202]
    assert (limits.max_vectors, limits.max_points) == (3, 400_000)
    assert limits.total_time_s == pytest.approx(2e-6 + 1e-2 + 4.0, rel=1e-9)
    rsu = [Route(switch="RSU201", output="OUT", state="wgfmu"), Route(switch="RSU202", output="OUT", state="wgfmu")]
    assert out.envelope.routes == frozenset(rsu) and out.routes_by_phase["waveform"] == rsu
    assert out.estimate.points == 400_000 and out.estimate.duration_s == pytest.approx(
        0.5 + 4.010002 + 1.0 + 400_000 * 2e-6, rel=1e-6)
    assert out.flex_preview == []  # WGFMU only: no FLEX writes


def test_lfn_recipe_reproduces_the_lab_layout() -> None:
    out = compile_recipe("wgfmu.lfn")
    program, waveform, _ = stored(PlanRecord.model_construct(plan_id="P-TESTTESTTE", program=out.program))
    assert [(r.role, r.channel, r.measure) for r in program.roles] == [("gate", 201, "V"), ("drain", 202, "I")]
    gate, drain = waveform.channels[201], waveform.channels[202]
    assert (gate.mode, gate.force_range, gate.measure) == ("fastiv", "5v", "voltage")
    assert (drain.mode, drain.force_range, drain.measure, drain.current_range) == ("fastiv", "5v", "current", "100ua")
    events = [e for e in waveform.events if isinstance(e, MeasureEvent)]
    assert [(e.pattern, e.points, e.interval, e.average) for e in events] == [
        ("gate", 504_000, 1e-7, 1e-7), ("drain", 504_000, 1e-7, 1e-7)]
    assert program.rows == 504_000 and waveform.points(201) == waveform.points(202) == 504_000


def test_recipe_parameters_reach_the_builder() -> None:
    out = compile_recipe("wgfmu.rtn", vg=0.8, vd=0.05, irange="10ua", points=5000, interval=2e-6, average=1e-6,
                         settle=0.0, edge=1e-5)
    _, waveform, _ = stored(PlanRecord.model_construct(plan_id="P-TESTTESTTE", program=out.program))
    event = waveform.events[0]
    assert isinstance(event, MeasureEvent) and (event.points, event.interval, event.average) == (5000, 2e-6, 1e-6)
    assert event.t == pytest.approx(1e-5) and waveform.patterns["gate"].levels()[1] == 0.8
    assert waveform.channels[202].current_range == "10ua" and waveform.patterns["drain"].levels()[1] == 0.05
