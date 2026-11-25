"""Bulk repeats of the simulated WGFMU (``transport/sim/wgfmu_bulk.py``; WP10.6, blueprint v2 4.2 "WGFMU engine"): a
long unmeasured repeat entry (bipolar cycling) is stepped in aggregated chunks with the devices' bulk-cycle hook, so
10^6 cycles count exactly, agree with the exact stepping, cost milliseconds and leave the integrals of later points
right; entries that measure, or are not aligned on every channel, are stepped exactly. Also the PUND and program/read
builders run on ``SimWgfmu`` with their values where the program says (``point_layout``)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.catalog import ferro_waveforms as fw
from b1500_test_agent.catalog import waveforms as wf
from b1500_test_agent.catalog.fast_bti import SenseTiming
from b1500_test_agent.transport.sim import wgfmu_bulk
from b1500_test_agent.transport.sim.wgfmu_engine import ChannelProgram, Entry, PatternSpec, layout
from tests.sim import wgfmu_examples as ex

pytestmark = pytest.mark.wgfmu

FECAP = {"area_um2": 1e4, "p_init": -0.8, "wake_frac": 0.15, "wake_cycles": 100.0, "fatigue_cycles": 1e5,
         "fatigue_exp": 0.5}
CYCLE = fw.burst_vectors((3.0, 1e-6), (-3.0, 1e-6), 1e-5, fw.PulseShape(lead=1e-7, trail=1e-7))


def fecap_station(**params: Any) -> ex.Station:
    sc = ex.scenario({"c": {"model": "fecap", "params": {**FECAP, **params}}}, {"c": {"top": 101, "bottom": "GNDU"}})
    return ex.station(sc)


def cycle_and_pund(st: ex.Station, count: int, *, measure: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """``count`` bipolar cycles, then a PUND sampled on the same channel (current measured on the forcing channel)."""
    s = st.sim
    s.open_session(ex.ADDRESS)
    s.initialize()
    s.set_operation_mode(101, "fastiv")
    s.set_measure_mode(101, "current")
    s.set_measure_current_range(101, "10ma")
    s.connect(101)
    s.create_pattern("cyc", 0.0)
    s.add_vectors("cyc", [dt for dt, _ in CYCLE], [v for _, v in CYCLE])
    timing = fw.PundTiming(amplitude=3.0, rise=1e-6, delay=1e-6, interval=1e-8)
    vectors, _ = fw.pund_vectors(timing)
    s.create_pattern("pund", 0.0)
    s.add_vectors("pund", [dt for dt, _ in vectors], [v for _, v in vectors])
    if measure:
        for event in fw.pund_events("pund", timing):
            s.set_measure_event("pund", event.event, event.t, event.points, event.interval, event.average, False)
    s.add_sequence(101, "cyc", float(count))
    s.add_sequence(101, "pund", 1.0)
    s.execute()
    s.wait_until_completed()
    if not measure:
        return np.zeros(0), np.zeros(0)
    size, _ = s.measure_value_size(101)
    return s.measure_values(101, 0, size)


def pr_of(values: np.ndarray, area_um2: float = 1e4, dt: float = 1e-8) -> float:
    """Pr (uC/cm^2) of a 4 x 200 point PUND record on the forcing channel: (Q_P - Q_U) / 2A."""
    p, u = values[:200].sum() * dt, values[200:400].sum() * dt
    return (p - u) / (2 * area_um2 * 1e-8) * 1e6


def device(st: ex.Station) -> Any:
    return st.flex.instrument.circuit.devices["c"]


def scale(n: float) -> float:
    return (1 - 0.15 * math.exp(-n / 100)) / (1 + math.sqrt(n / 1e5))


def test_a_million_cycles_count_exactly_and_fatigue_the_film() -> None:
    st = fecap_station()
    _, values = cycle_and_pund(st, 1_000_000)
    dev = device(st)
    assert dev.cycles == pytest.approx(1_000_000 + 1.0, abs=1e-6)  # the cycles, then the PUND's P and N switching
    assert pr_of(values) == pytest.approx(20.0 * scale(1_000_000), rel=0.01)


def test_bulk_agrees_with_exact_stepping(monkeypatch: pytest.MonkeyPatch) -> None:
    bulk = fecap_station()
    _, fast = cycle_and_pund(bulk, 3000)
    monkeypatch.setattr(wgfmu_bulk, "MIN_REPEATS", 10**9)
    exact = fecap_station()
    _, slow = cycle_and_pund(exact, 3000)
    assert device(bulk).cycles == device(exact).cycles == pytest.approx(3001.0)
    assert device(bulk).p == pytest.approx(device(exact).p, rel=1e-9)
    assert np.allclose(fast, slow, rtol=1e-9, atol=1e-12)


def test_a_non_ferroelectric_load_is_unchanged_by_bulk_stepping() -> None:
    st = ex.station(ex.resistor(1e4, 101, "GNDU"))
    _, values = cycle_and_pund(st, 200_000)
    level = np.asarray([v for _, v in fw.pund_vectors(fw.PundTiming(amplitude=3.0, rise=1e-6, delay=1e-6,
                                                                       interval=1e-8))[0]])
    assert len(values) == 800 and np.max(np.abs(values)) == pytest.approx(3.0 / 1e4, rel=0.02)
    assert np.max(np.abs(level)) == 3.0


def program(entries: list[tuple[str, int]], *, points: bool = False) -> ChannelProgram:
    specs = {"cyc": PatternSpec(v0=0.0, dts=[wf.ticks(dt) for dt, _ in CYCLE], volts=[v for _, v in CYCLE])}
    if points:
        from b1500_test_agent.transport.sim.wgfmu_engine import MeasureSpec

        specs["cyc"].measures.append(MeasureSpec("m", 10, 1, 1, 1, False))
    lays = {name: layout(name, spec) for name, spec in specs.items()}
    return ChannelProgram(101, "fastiv", "current", "10ma", "5v", True,
                          [Entry(lays[name], count, 0) for name, count in entries])


def test_bulk_windows_need_aligned_unmeasured_repeats() -> None:
    plain = program([("cyc", 1000)])
    window = wgfmu_bulk.window_at({101: plain}, 0.0)
    assert window is not None and (window.start, window.period, window.count) == (0, 1000, 1000)
    assert wgfmu_bulk.window_at({101: program([("cyc", 10)])}, 0.0) is None  # too few repeats
    assert wgfmu_bulk.window_at({101: program([("cyc", 1000)], points=True)}, 0.0) is None  # it measures
    other = program([("cyc", 999)])
    assert wgfmu_bulk.window_at({101: plain, 102: other}, 0.0) is None  # not aligned
    assert wgfmu_bulk.chunks(130) == [3] * 43 + [1] and sum(wgfmu_bulk.chunks(10**6)) == 10**6
    assert len(wgfmu_bulk.chunks(10**6)) <= wgfmu_bulk.CHUNKS


# -- the builders on SimWgfmu ---------------------------------------------------------------------------------------


def load(st: ex.Station, built: wf.BuiltWaveform) -> None:
    program_ = built.program
    s = st.sim
    s.open_session(ex.ADDRESS)
    s.initialize()
    for ch, setup in program_.channels.items():
        s.set_operation_mode(ch, setup.mode)
        s.set_force_voltage_range(ch, setup.force_range)
        if setup.measure == "current":
            s.set_measure_mode(ch, "current")
            s.set_measure_current_range(ch, setup.current_range or "1ma")
    for name, pattern in program_.patterns.items():
        s.create_pattern(name, pattern.v0)
        s.add_vectors(name, [dt for dt, _ in pattern.vectors], [v for _, v in pattern.vectors])
    for event in program_.events:
        s.set_measure_event(event.pattern, event.event, event.t, event.points, event.interval,
                            event.average, event.raw)  # type: ignore[union-attr]
    for ch, items in program_.sequences.items():
        for name, count in items:
            s.add_sequence(ch, name, count)
        s.connect(ch)
    s.execute()
    s.wait_until_completed()


def test_pund_builder_runs_with_the_programmed_layout() -> None:
    sc = ex.scenario({"c": {"model": "fecap", "params": {"area_um2": 2500.0}}}, {"c": {"top": 101, "bottom": 102}})
    st = ex.station(sc)
    timing = fw.PundTiming(amplitude=3.0, rise=1e-5, delay=1e-5, interval=1e-7)
    built = fw.pund(wf.WgRole(role="top", channel=101), [wf.WgRole(role="bottom", channel=102, measure="I")], timing)
    load(st, built)
    t, i = st.sim.measure_values(102, 0, st.sim.measure_value_size(102)[0])
    expected = wf.point_layout(built.program, 102)
    assert len(t) == len(expected) == 800
    assert np.allclose(t, expected.start_s + expected.average_s / 2, atol=1e-12)
    q_p, q_u = -i[:200].sum() * 1e-7, -i[200:400].sum() * 1e-7  # the bottom sees the opposite current
    assert (q_p - q_u) / (2 * 2500e-8) * 1e6 == pytest.approx(20.0, rel=0.01)


def test_program_read_builder_runs_with_the_programmed_layout() -> None:
    params = {"polarity": "n", "vth0": 0.6, "k_v": 0.5, "vc_v": 2.8, "delta_v": 0.45, "p_init": -1.0,
              "tau0_s": 1e-9, "va_v": 8.0}
    sc = ex.scenario({"f": {"model": "fefet", "params": params}},
                     {"f": {"gate": 101, "drain": 102, "source": "GNDU", "bulk": "GNDU"}})
    st = ex.station(sc)
    timing = SenseTiming(edge=1e-7, width=1e-6, settle=5e-7)
    built = fw.program_read(wf.WgRole(role="gate", channel=101),
                            [fw.ReadChannel(role=wf.WgRole(role="drain", channel=102, measure="I",
                                                           current_range="100ua"), read_level=0.05)],
                            sweep=[0.2, 0.6, 1.0, 1.4], ops=[fw.ProgramOp(name="erase", level=-4.0, width=1e-6),
                                                             fw.ProgramOp(name="program", level=4.0, width=1e-6)],
                            shape=fw.PulseShape(lead=1e-7, trail=1e-7), period=1e-5, count=1, timing=timing,
                            cycles=2)
    load(st, built)
    t, i = st.sim.measure_values(102, 0, st.sim.measure_value_size(102)[0])
    expected = wf.point_layout(built.program, 102)
    assert len(t) == len(expected) == 4 + 2 * 8
    assert np.allclose(t, expected.start_s + expected.average_s / 2, atol=1e-12)
    erase, program_ = i[4:8], i[8:12]
    assert np.all(program_ > erase)  # the programmed (low-Vth) state conducts more at every read level
