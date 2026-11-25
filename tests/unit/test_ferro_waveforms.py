"""WGFMU builders ``pund`` and ``program_read`` and the pattern pieces of the WGFMU ``pulse_read`` path
(``catalog/ferro_waveforms.py``; WP10.6; blueprint v2 2.7.1): vector counts and levels, the 10 ns grid, event layout
(points, interval, averaging, offsets), pulse trains, determinism and the refusals."""

from __future__ import annotations

import pytest

from b1500_test_agent.catalog import ferro_waveforms as fw
from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.fast_bti import SenseTiming
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.models.sources import MeasureEvent

pytestmark = pytest.mark.wgfmu

TOP = wf.WgRole(role="top", channel=201)
BOTTOM = wf.WgRole(role="bottom", channel=202, measure="I")
GATE = wf.WgRole(role="gate", channel=201)
DRAIN = wf.WgRole(role="drain", channel=202, measure="I", current_range="100ua")
PUND = fw.PundTiming(amplitude=3.0, rise=1e-5, top=0.0, delay=1e-5, interval=1e-7)
SHAPE = fw.PulseShape(base=0.0, lead=1e-7, trail=1e-7)
TIMING = SenseTiming(edge=1e-7, width=1e-6, settle=5e-7)


def ticks(seconds: float) -> int:
    return wf.ticks(seconds)


# -- pieces ----------------------------------------------------------------------------------------------------------


def test_op_vectors_are_one_period_back_to_the_base() -> None:
    vectors = fw.op_vectors(4.0, 1e-6, 1e-5, fw.PulseShape(base=0.5, lead=1e-7, trail=2e-7))
    assert [(ticks(dt), v) for dt, v in vectors] == [(10, 4.0), (100, 4.0), (20, 0.5), (870, 0.5)]
    assert fw.duration_ticks(vectors) == 1000
    with pytest.raises(CompileError, match="must exceed lead \\+ width \\+ trail"):
        fw.op_vectors(4.0, 1e-6, 1.2e-6, SHAPE)


def test_burst_vectors_put_the_second_pulse_half_a_period_later() -> None:
    vectors = fw.burst_vectors((3.0, 1e-5), (-3.0, 1e-5), 1e-4, fw.PulseShape(lead=1e-6, trail=1e-6))
    levels = [v for _, v in vectors]
    assert levels == [3.0, 3.0, 0.0, 0.0, -3.0, -3.0, 0.0, 0.0]
    assert fw.duration_ticks(vectors[:4]) == fw.duration_ticks(vectors[4:]) == 5000
    with pytest.raises(CompileError, match="cycle period must be at least"):
        fw.burst_vectors((3.0, 1e-5), (-3.0, 1e-5), 2e-5, fw.PulseShape(lead=1e-6, trail=1e-6))


def test_read_vectors_and_event_follow_the_sense_staircase() -> None:
    vectors = fw.read_vectors([0.0, 0.5, 1.0], 0.0, TIMING)
    assert [(ticks(dt), v) for dt, v in vectors] == [(10, 0.0), (100, 0.0), (10, 0.5), (100, 0.5), (10, 1.0),
                                                      (100, 1.0), (10, 0.0)]
    event = fw.read_event("gate_cycle", "erase", 3e-6, 3, TIMING)
    assert (ticks(event.t), event.points, ticks(event.interval), ticks(event.average)) == (300 + 10 + 50, 3, 110, 50)
    with pytest.raises(CompileError, match="no averaging window"):
        fw.read_event("p", "e", 0.0, 3, SenseTiming(edge=1e-7, width=5e-7, settle=5e-7))


def test_hold_vectors_split_long_holds() -> None:
    assert len(fw.hold_vectors(0.2, 25_000.0)) == 3 and fw.duration_ticks(fw.hold_vectors(0.2, 25_000.0)) == \
        ticks(25_000.0)


# -- pund ------------------------------------------------------------------------------------------------------------


def test_pund_program_layout() -> None:
    built = fw.pund(TOP, [BOTTOM], PUND)
    program = built.program
    top = program.patterns["top"]
    assert top.v0 == 0.0 and [v for _, v in top.vectors] == [-3.0, 0.0, 0.0] + [3.0, 0.0, 0.0] * 2 + \
        [-3.0, 0.0, 0.0] * 2
    assert fw.duration_ticks(top.vectors) == 5 * 3000 == fw.duration_ticks(program.patterns["bottom"].vectors)
    events = [e for e in program.events if isinstance(e, MeasureEvent)]
    assert [(e.pattern, e.event, ticks(e.t), e.points, ticks(e.interval), ticks(e.average)) for e in events] == [
        ("bottom", name, 3000 * k, 200, 10, 10) for k, name in enumerate(fw.PUND_EVENTS, 1)]
    assert program.points(202) == 800 and program.points(201) == 0
    assert program.channels[201].force_range == "3v" and program.channels[202].current_range == "1ma"
    positive, negative = built.pulses[201]
    assert (positive.peak_v, positive.count, negative.peak_v, negative.count) == (3.0, 2, -3.0, 3)
    assert positive.width_s == pytest.approx(1e-5) and positive.period_s == pytest.approx(3e-5)
    assert fw.pund(TOP, [BOTTOM], PUND) == built  # deterministic


def test_pund_without_preset_and_with_a_flat_top() -> None:
    timing = PUND.model_copy(update={"preset": False, "top": 5e-6})
    built = fw.pund(TOP, [BOTTOM], timing)
    assert built.program.patterns["top"].vectors[0] == (pytest.approx(1e-5), 3.0)
    assert [e.points for e in built.program.events] == [250] * 4
    assert built.pulses[201][1].count == 2 and fw.pund_seconds(timing) == pytest.approx(4 * 3.5e-5)


@pytest.mark.parametrize(("change", "message"), [
    ({"interval": 3e-7}, "not a whole number of sampling intervals"),
    ({"interval": 1e-5}, "gives 2 points"),
    ({"amplitude": 12.0}, "exceeds the WGFMU's 10 V"),
])
def test_pund_refusals(change: dict[str, float], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        fw.pund(TOP, [BOTTOM], PUND.model_copy(update=change))


def test_pund_needs_a_measuring_role() -> None:
    with pytest.raises(CompileError, match="no role measures"):
        fw.pund(TOP, [wf.WgRole(role="bottom", channel=202)], PUND)


# -- program_read ----------------------------------------------------------------------------------------------------


def build(**kw: object) -> wf.BuiltWaveform:
    args: dict[str, object] = {
        "sweep": [0.0, 0.5, 1.0], "ops": [fw.ProgramOp(name="erase", level=-4.0, width=1e-6),
                                         fw.ProgramOp(name="program", level=4.0, width=1e-6)],
        "shape": SHAPE, "period": 1e-5, "count": 1, "timing": TIMING, "cycles": 3, "initial_read": True}
    args.update(kw)
    return fw.program_read(GATE, [fw.ReadChannel(role=DRAIN, read_level=0.05)], **args)  # type: ignore[arg-type]


def test_program_read_in_one_execution() -> None:
    built = build()
    program = built.program
    assert program.sequences[201] == [("gate_ref", 1.0), ("gate_cycle", 3.0)]
    assert program.sequences[202] == [("drain_ref", 1.0), ("drain_cycle", 3.0)]
    gate = program.patterns["gate_cycle"]
    drain = program.patterns["drain_cycle"]
    assert fw.duration_ticks(gate.vectors) == fw.duration_ticks(drain.vectors) == 2 * (1000 + 3 * 110 + 10)
    assert [v for _, v in gate.vectors][:4] == [-4.0, -4.0, 0.0, 0.0]  # the erase pulse, back to the base
    assert {v for _, v in drain.vectors} == {0.0, 0.05}
    events = {(e.pattern, e.event): e for e in program.events}
    assert set(events) == {("drain_ref", "read"), ("drain_cycle", "erase"), ("drain_cycle", "program")}
    assert ticks(events[("drain_cycle", "erase")].t) == 1000 + 10 + 50
    assert ticks(events[("drain_cycle", "program")].t) == 1340 + 1000 + 10 + 50
    assert program.points(202) == 3 + 3 * 6
    assert built.cycle_by == "op" and built.phases == {"read": "read", "erase": "erase", "program": "program"}
    trains = built.pulses[201]
    assert sorted(t.peak_v for t in trains) == [-4.0, 4.0] and all(t.repeat == 3 for t in trains)


def test_program_read_points_lay_out_cycle_and_phase() -> None:
    built = build()
    layout = wf.point_layout(built.program, 202)
    assert list(layout.event[:3]) == ["read"] * 3 and list(layout.event[3:9]) == ["erase"] * 3 + ["program"] * 3
    assert list(layout.repeat[-6:]) == [2] * 6


def test_program_read_ramps_from_and_to_zero_with_a_non_zero_rest() -> None:
    built = fw.program_read(GATE, [fw.ReadChannel(role=DRAIN, read_level=0.05, pulse_level=0.1)], sweep=[0.0, 1.0],
                            ops=[fw.ProgramOp(name="program", level=4.0, width=1e-6)], shape=SHAPE, period=1e-5,
                            count=2, timing=TIMING, cycles=1, initial_read=False)
    program = built.program
    assert [n for n, _ in program.sequences[202]] == ["drain_lead", "drain_cycle", "drain_tail"]
    assert program.patterns["drain_lead"].vectors == [(pytest.approx(1e-7), 0.1)]
    assert program.patterns["drain_tail"].v0 == 0.1 and program.patterns["drain_tail"].vectors[-1][1] == 0.0
    assert [v for _, v in program.patterns["gate_cycle"].vectors][:8] == [4.0, 4.0, 0.0, 0.0] * 2  # count 2


@pytest.mark.parametrize(("kw", "message"), [
    ({"ops": []}, "at least one operation"),
    ({"ops": [fw.ProgramOp(name="program", level=4.0, width=1e-6)] * 2}, "each operation appears once"),
    ({"sweep": []}, "at least one gate level"),
    ({"cycles": 0}, "cycles must be a positive integer"),
    ({"period": 1e-6}, "must exceed lead"),
])
def test_program_read_refusals(kw: dict[str, object], message: str) -> None:
    with pytest.raises(CompileError, match=message):
        build(**kw)


def test_both_builders_are_registered() -> None:
    assert {"pund", "program_read"} <= set(wf.BUILDERS)
