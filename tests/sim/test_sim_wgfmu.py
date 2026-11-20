"""``SimWgfmu`` behaviour (blueprint v2 2.4, 4.2 "WGFMU engine", 4.3 faults; WP10.1): limits and error codes, RAW vs
AVERAGED data, sequences and gaps, ranges, PG mode, noise, memory, the shared clock and circuit with the FLEX side,
the RSU path, persistence across processes, the FLEX bus lock and the WGFMU faults."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from b1500_test_agent.models.sim import (
    WgfmuDisconnectFails,
    WgfmuDllMissing,
    WgfmuErrorFault,
    WgfmuHang,
)
from b1500_test_agent.models.sources import MeasureEvent
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim import wgfmu as sim_wgfmu
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from b1500_test_agent.transport.sim.wgfmu_engine import MeasureSpec
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.sim import wgfmu_examples as ex
from tests.sim.helpers import values

pytestmark = pytest.mark.wgfmu

ADDR = ex.ADDRESS


def online(sim: SimWgfmu, *chans: int, mode: str = "fastiv", current: tuple[int, ...] = ()) -> None:
    sim.open_session(ADDR)
    sim.initialize()
    for ch in chans:
        sim.set_operation_mode(ch, mode)
        if ch in current:
            sim.set_measure_mode(ch, "current")
        sim.connect(ch)


def flat(sim: SimWgfmu, name: str, v: float, length: float) -> None:
    sim.create_pattern(name, v)
    sim.add_vectors(name, [length], [v])


def code_of(call) -> int:
    with pytest.raises(WgfmuError) as info:
        call()
    return info.value.wgfmu_code


# -- highest-limit (firmware) errors 3050, 3304-3316 -----------------------------------------------------------------


def _setup_3304(s: SimWgfmu) -> None:
    s.create_pattern("p", 0.0)
    s.add_vectors("p", [1e-8] * 2049, [0.0] * 2049)
    s.add_sequence(101, "p", 1)


def _setup_3305(s: SimWgfmu) -> None:
    flat(s, "p", 0.0, 1e-6)
    for _ in range(513):
        s.add_sequence(101, "p", 1)


def _setup_3306(s: SimWgfmu) -> None:
    s.create_pattern("p", 0.0)
    s.add_sequence(101, "p", 1)


def _setup_3309(s: SimWgfmu) -> None:
    flat(s, "p", 0.0, 1e-6)
    s.add_sequence(101, "p", 1_099_511_627_777)


def _setup_3310(s: SimWgfmu) -> None:
    flat(s, "p", 4.0, 1e-6)
    s.add_sequence(101, "p", 1)
    s.set_force_voltage_range(101, "3v")


def _setup_3311(s: SimWgfmu) -> None:
    s.create_pattern("p", 0.0)
    s.add_vectors("p", [11000.0], [0.0])
    s.add_sequence(101, "p", 1)


def _event_setup(t: float, points: int, interval: float, average: float, length: float = 1e-3):
    def setup(s: SimWgfmu) -> None:
        flat(s, "p", 0.0, length)
        s.set_measure_event("p", "e", t, points, interval, average, False)
        s.add_sequence(101, "p", 1)
    return setup


def _setup_3314(s: SimWgfmu) -> None:
    flat(s, "p", 0.0, 1e-5)
    s.set_range_event("p", "r", 1e-6, "1ua")  # voltage measurement mode: no range events
    s.add_sequence(101, "p", 1)


FIRMWARE_CASES = {
    3304: _setup_3304, 3305: _setup_3305, 3306: _setup_3306, 3309: _setup_3309, 3310: _setup_3310,
    3311: _setup_3311, 3312: _event_setup(0.0, 2, 1.5, 0.0, length=2.0), 3313: _event_setup(0.0, 200, 1e-5, 0.0),
    3314: _setup_3314, 3315: _event_setup(0.0, 2, 0.05, 0.03, length=0.1), 3316: _event_setup(0.0, 10, 1e-6, 2e-6),
}  # fmt: skip


@pytest.mark.parametrize("code", sorted(FIRMWARE_CASES))
def test_setup_limits_are_firmware_errors_at_execute_and_update(code: int) -> None:
    st = ex.station()
    s = st.sim
    s.open_session(ADDR)
    s.set_operation_mode(101, "fastiv")
    s.connect(101)
    FIRMWARE_CASES[code](s)
    with pytest.raises(WgfmuError) as info:
        s.execute()
    err = info.value
    assert err.wgfmu_code == code and err.rc == -6 and err.code == "instrument_error" and err.function == "execute"
    assert f"firmware error {code}:" in err.text and s.errors() == [err.text]
    assert code_of(s.update) == code
    assert s.status()[0] == 10006  # no run started
    s.initialize()
    s.close_session()
    st.flex.instrument.assert_safe()


@pytest.mark.parametrize("code", [3307, 3308, 3050, 3001, -5])
def test_any_code_comes_from_the_wgfmu_error_fault(code: int) -> None:
    st = ex.station(ex.scenario())
    st.flex.inject(WgfmuErrorFault(fn="execute", code=code))
    s = st.sim
    online(s, 101)
    flat(s, "p", 0.0, 1e-6)
    s.add_sequence(101, "p", 1)
    with pytest.raises(WgfmuError) as info:
        s.execute()
    assert info.value.wgfmu_code == code and info.value.rc == (code if code < 0 else -6)
    assert "simulated wgfmu_error" in info.value.text
    assert s.status()[0] == 10006
    s.execute()  # one-shot
    s.wait_until_completed()
    assert s.status()[0] == 10000


def test_memory_overflow_3050_at_four_million_values() -> None:
    st = ex.station(ex.resistor(1e4, 101, "GNDU"))
    s = st.sim
    online(s, 101, current=(101,))
    flat(s, "p", 0.5, 0.05)
    s.set_measure_event("p", "fits", 0.0, 800_000, 6e-8, 2e-8, True)  # RAW: 5 values a point -> 4,000,000
    s.add_sequence(101, "p", 1)
    s.execute()
    s.wait_until_completed()
    assert s.measure_value_size(101) == (4_000_000, 4_000_000)
    flat(s, "q", 0.5, 0.05)
    s.set_measure_event("q", "over", 0.0, 800_001, 6e-8, 2e-8, True)
    s.add_sequence(102, "q", 1)
    s.set_operation_mode(102, "fastiv")
    s.connect(102)
    s.execute()
    with pytest.raises(WgfmuError) as info:
        s.wait_until_completed()
    assert info.value.wgfmu_code == 3050 and "values from index 4000000 are lost" in info.value.text
    assert s.measure_value_size(102) == (4_000_000, 4_000_005)
    assert code_of(lambda: s.measure_values(102, 4_000_000, 5)) == 3050
    t, v = s.measure_values(102, 3_999_995, 100)  # channel 102 measures its output voltage
    assert len(t) == 5 and np.allclose(v, 0.5)


def test_reading_during_the_run_frees_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sim_wgfmu, "_MEMORY", 1000)
    st = ex.station(ex.resistor(1e4, 101, "GNDU"))
    s = st.sim
    online(s, 101)
    flat(s, "p", 0.2, 3e-3)
    s.set_measure_event("p", "e", 0.0, 3000, 1e-6, 0.0, False)
    s.add_sequence(101, "p", 1)
    s.poll_quantum_s = 5e-4  # 500 values per poll, read at once: never more than 1000 stored
    s.execute()
    read = 0
    while read < 3000:
        measured, _ = s.measure_value_size(101)
        if measured > read:
            t, _ = s.measure_values(101, read, measured - read)
            read += len(t)
    assert read == 3000
    s.poll_quantum_s = None
    s.execute()  # the same run without reading: overflow
    with pytest.raises(WgfmuError) as info:
        s.wait_until_completed()
    assert info.value.wgfmu_code == 3050


def test_runtime_errors_3051_and_3052_stop_the_stored_data() -> None:
    st = ex.station(ex.resistor(1e3, 101, "GNDU"))
    s = st.sim
    online(s, 101, current=(101,))
    flat(s, "p", 0.1, 1e-4)
    s.set_measure_event("p", "a", 0.0, 1, 1e-8, 1e-8, False)
    s.set_measure_event("p", "b", 5e-8, 10, 2e-8, 0.0, False)  # the averaging changes 50 ns after "a" starts
    s.add_sequence(101, "p", 1)
    s.execute()
    with pytest.raises(WgfmuError) as info:
        s.wait_until_completed()
    assert info.value.wgfmu_code == 3051
    assert s.measure_value_size(101) == (1, 11)
    s.clear()
    flat(s, "q", 0.1, 1e-4)
    for k, rng in enumerate(("1ma", "100ua", "1ma")):
        s.set_range_event("q", f"r{k}", 1e-5 + k * 1e-6, rng)
    s.add_sequence(101, "q", 1)
    s.execute()
    assert code_of(s.wait_until_completed) == 3052


# -- lowest-limit and context errors ---------------------------------------------------------------------------------


def test_lowest_limits_fail_at_the_call_and_add_nothing() -> None:
    s = ex.station().sim
    assert code_of(lambda: s.create_pattern("", 0.0)) == -2
    s.create_pattern("p", 0.0)
    assert code_of(lambda: s.create_pattern("p", 0.0)) == -12
    assert code_of(lambda: s.create_pattern("q", 10.5)) == -1
    assert code_of(lambda: s.add_vectors("nope", [1e-6], [0.0])) == -10
    assert code_of(lambda: s.add_vectors("p", [1e-6, 4e-9], [0.0, 1.0])) == -1  # 4 ns rounds to 0
    assert code_of(lambda: s.add_vectors("p", [1e-6], [11.0])) == -1
    assert code_of(lambda: s.add_vectors("p", [1e-6, 1e-6], [0.0])) == -1
    assert s._patterns["p"].dts == []
    s.add_vectors("p", [7.2e-8], [1.0])  # 72 ns rounds to 70 ns (WG p82 (4-12))
    assert s._patterns["p"].dts == [7]
    assert code_of(lambda: s.set_measure_event("p", "", 0.0, 1, 1e-8, 0.0, False)) == -2
    assert code_of(lambda: s.set_measure_event("p", "e", 0.0, 0, 1e-8, 0.0, False)) == -1
    assert code_of(lambda: s.set_measure_event("p", "e", 0.0, 1, 0.0, 0.0, False)) == -1
    assert code_of(lambda: s.set_measure_event("p", "e", 0.0, 1, 1e-8, -1e-8, False)) == -1
    assert code_of(lambda: s.set_range_event("p", "r", 0.0, "2ma")) == -1
    assert code_of(lambda: s.add_sequence(105, "p", 1)) == -9
    assert code_of(lambda: s.add_sequence(101, "p", 0.4)) == -1
    s.add_sequence(101, "p", 7.2)
    assert s._sequences[101] == [("p", 7)]
    assert all(e.startswith(("create_pattern", "add_vectors", "set_", "add_sequence")) for e in s.errors())


def test_context_errors_online_functions_and_channels() -> None:
    s = ex.station().sim
    for call in (s.initialize, s.execute, s.update, lambda: s.connect(101), lambda: s.set_timeout(10.0),
                 lambda: s.set_operation_mode(101, "fastiv"), s.channel_ids, s.status):
        assert code_of(call) == -3  # no session
    s.open_session(ADDR)
    assert code_of(lambda: s.open_session("GPIB0::18::INSTR")) == -3
    assert code_of(lambda: s.set_timeout(0.5)) == -1
    assert s.channel_ids() == [101, 102]
    assert code_of(lambda: s.connect(201)) == -9  # slot 2 holds an SMU
    assert code_of(lambda: s.set_operation_mode(101, "current")) == -1  # Example 3 line 18
    assert code_of(s.wait_until_completed) == -13
    assert code_of(lambda: s.measure_values(101, 0, 1)) == -3
    s.set_operation_mode(101, "dc")
    assert code_of(lambda: s.set_measure_enabled(101, False)) == -4
    s.set_operation_mode(101, "fastiv")
    s.connect(101)
    assert code_of(lambda: s.dc_force_voltage(101, 1.0)) == -4
    assert code_of(s.execute) == 3201  # a connected Fast IV channel without a sequence


def test_pg_mode_refuses_10v_ranges_and_current_measurement() -> None:
    s = ex.station().sim
    online(s, 101, mode="pg")
    flat(s, "p", 0.0, 1e-6)
    s.add_sequence(101, "p", 1)
    s.set_force_voltage_range(101, "10v")
    assert code_of(s.execute) == 3302
    s.set_force_voltage_range(101, "5v")
    s.set_measure_mode(101, "current")
    assert code_of(s.update) == 3303


def test_dc_mode_force_range_limit_3301() -> None:
    s = ex.station(ex.resistor(1e4, 101, "GNDU")).sim
    online(s, 101, mode="dc")
    s.set_force_voltage_range(101, "3v")
    assert code_of(lambda: s.dc_force_voltage(101, 3.5)) == 3301
    s.set_force_voltage_range(101, "-10v")
    s.dc_force_voltage(101, -8.0)
    s.set_measure_mode(101, "current")
    assert s.dc_measure_value(101) == pytest.approx(-8e-4)
    s.set_measure_mode(101, "voltage")
    assert s.dc_measure_value(101) == pytest.approx(-5.0)  # current mode set the 5 V voltage range (Table 4-7)
    s.set_measure_voltage_range(101, "10v")
    assert s.dc_measure_value(101) == pytest.approx(-8.0)


# -- data: RAW vs AVERAGED, times, sequences ------------------------------------------------------------------------


@pytest.mark.parametrize(("average", "raw", "per_point"), [(0.0, False, 1), (2e-8, False, 1), (0.0, True, 1),
                                                           (2e-8, True, 5), (1e-7, True, 21)])
def test_raw_vs_averaged_sizes_and_times(average: float, raw: bool, per_point: int) -> None:
    st = ex.station(ex.resistor(1e3, 101, "GNDU"))
    s = st.sim
    online(s, 101, current=(101,))
    s.create_pattern("ramp", 0.0)
    s.add_vectors("ramp", [1e-5], [1.0])
    s.set_measure_event("ramp", "e", 1e-6, 10, 2e-7, average, raw)
    s.add_sequence(101, "ramp", 2)
    s.execute()
    s.wait_until_completed()
    total = 2 * 10 * per_point
    assert s.measure_value_size(101) == (total, total)
    model = MeasureEvent(pattern="ramp", event="e", t=1e-6, points=10, interval=2e-7, average=average, raw=raw)
    assert model.data_points == 10 * per_point == MeasureSpec("e", 100, 10, 20, round(average / 1e-8), raw).values
    t, v = s.measure_values(101, 0, total)
    if raw:
        starts = 1e-6 + 2e-7 * np.arange(10)
        expected_t = (starts[:, None] + 5e-9 * np.arange(per_point)[None, :]).ravel()
    else:
        expected_t = 1e-6 + 2e-7 * np.arange(10) + average / 2
    assert np.allclose(t[: 10 * per_point], expected_t, atol=1e-15)
    assert np.allclose(t[10 * per_point:], expected_t + 1e-5, atol=1e-14)
    assert np.allclose(v, (t % 1e-5) / 1e-5 / 1e3, atol=1e-12)  # ramp 0 -> 1 V into 1 kOhm, at each time


def test_sequences_in_series_have_the_50ns_gap() -> None:
    s = ex.station().sim
    online(s, 101)
    s.create_pattern("a", 0.0)
    s.add_vectors("a", [1e-6], [1.0])
    s.create_pattern("b", -1.0)
    s.add_vectors("b", [1e-6], [-1.0])
    s.add_sequence(101, "a", 2)
    s.add_sequence(101, "b", 1)
    s.execute()
    s.wait_until_completed()
    assert s.channel_status(101)[2] == pytest.approx(3e-6 + 5e-8, abs=1e-15)
    levels = s.force_levels(101, [1e-6, 1.5e-6, 2e-6 + 5e-9, 2e-6 + 2e-8, 2e-6 + 5e-8, 3.05e-6, 4e-6])
    assert levels == pytest.approx([0.0, 0.5, 1.0, -1.0, -1.0, -1.0, -1.0])
    assert st_level(s, 101) == -1.0  # the channel keeps the last voltage


def st_level(s: SimWgfmu, ch: int) -> float:
    return s._inst.state.wgfmu[ch].voltage


def test_range_events_change_the_saturation_of_current_readings() -> None:
    s = ex.station(ex.resistor(1e3, 101, "GNDU")).sim
    online(s, 101, current=(101,))
    flat(s, "p", 0.5, 2e-5)  # 500 uA into 1 kOhm
    s.set_measure_event("p", "before", 1e-6, 5, 1e-6, 0.0, False)
    s.set_range_event("p", "low", 8e-6, "100ua")
    s.set_measure_event("p", "after", 1e-5, 5, 1e-6, 0.0, False)
    s.add_sequence(101, "p", 2)
    s.execute()
    s.wait_until_completed()
    _, v = s.measure_values(101, 0, 20)
    assert np.allclose(v[:5], 5e-4) and np.allclose(v[5:], 1e-4)  # the range stays 100 uA in the second repeat
    s.set_range_event("p", "inside", 1.5e-6, "1ma")
    s.set_measure_event("p", "before", 1e-6, 5, 1e-6, 8e-7, False)
    assert code_of(s.execute) == 3314  # range change inside an averaging window


def test_pg_mode_divides_the_output_by_50_ohm_and_the_load() -> None:
    s = ex.station(ex.resistor(50.0, 101, "GNDU")).sim
    online(s, 101, 102, mode="pg")
    flat(s, "p", 2.0, 1e-6)
    s.set_measure_event("p", "v", 0.0, 3, 1e-7, 0.0, False)
    s.add_sequence(101, "p", 1)
    s.add_sequence(102, "p", 1)  # channel 102 drives an open load
    s.execute()
    s.wait_until_completed()
    assert np.allclose(s.measure_values(101, 0, 3)[1], 1.0, atol=1e-9)
    assert np.allclose(s.measure_values(102, 0, 3)[1], 2.0)


def test_averaging_noise_falls_as_one_over_sqrt_n() -> None:
    sc = ex.scenario({"r": {"model": "resistor", "params": {"r_ohm": 1e4}}}, {"r": {"a": 101, "b": "GNDU"}},
                     noise={"floor_a": {"WGFMU": 1e-6}, "rel": 0.0, "seed": 5})
    s = ex.station(sc).sim
    online(s, 101, current=(101,))
    flat(s, "p", 0.5, 0.1)
    s.set_measure_event("p", "n2", 0.0, 20_000, 1e-6, 1e-8, False)        # 2 samples of 5 ns
    s.set_measure_event("p", "n128", 0.03, 20_000, 1e-6, 6.4e-7, False)   # 128 samples
    s.add_sequence(101, "p", 1)
    s.execute()
    s.wait_until_completed()
    _, v = s.measure_values(101, 0, 40_000)
    ratio = np.std(v[:20_000]) / np.std(v[20_000:])
    assert ratio == pytest.approx(8.0, rel=0.10)
    assert np.std(v[:20_000]) == pytest.approx(1e-6 / np.sqrt(2), rel=0.05)
    assert np.mean(v) == pytest.approx(5e-5, rel=1e-3)


def test_abort_keeps_the_level_and_stops_the_data() -> None:
    s = ex.station(ex.resistor(1e3, 101, "GNDU")).sim
    online(s, 101)
    s.create_pattern("ramp", 0.0)
    s.add_vectors("ramp", [1.0], [1.0])
    s.set_measure_event("ramp", "e", 0.0, 100, 1e-2, 0.0, False)
    s.add_sequence(101, "ramp", 1)
    s.poll_quantum_s = 0.25
    s.execute()
    assert s.status()[:2] == (10002, pytest.approx(0.25))
    s.abort()
    assert s.status() == (10003, pytest.approx(0.25), pytest.approx(1.0))
    assert st_level(s, 101) == pytest.approx(0.25)
    measured, total = s.measure_value_size(101)
    assert (measured, total) == (25, 100)
    assert np.allclose(s.measure_values(101, 0, 100)[1], np.arange(25) * 1e-2)


def test_update_during_a_run_is_illegal_and_after_a_run_deletes_the_data() -> None:
    s = ex.station().sim
    online(s, 101)
    flat(s, "p", 0.3, 1.0)
    s.set_measure_event("p", "e", 0.0, 10, 1e-2, 0.0, False)
    s.add_sequence(101, "p", 1)
    s.poll_quantum_s = 0.5
    s.execute()
    s.update()
    assert s.channel_status(101)[0] == 10005
    assert code_of(lambda: s.measure_values(101, 0, 1)) == -15
    s.execute()  # restarts
    s.wait_until_completed()
    assert len(s.measure_values(101, 0, 10)[0]) == 10
    s.update()
    assert code_of(lambda: s.measure_values(101, 0, 1)) == -15


def test_dynamic_device_ferroelectric_switching_current() -> None:
    """FeCap PUND through the WGFMU: the P pulse moves 2 Pr x A more charge than the U pulse (§4.2 engine)."""
    sc = ex.scenario({"c": {"model": "fecap", "params": {"area_um2": 1e4, "p_init": -0.8}}},
                     {"c": {"top": 101, "bottom": "GNDU"}})
    st = ex.station(sc)
    s = st.sim
    online(s, 101, current=(101,))
    s.create_pattern("pu", 0.0)
    s.add_vectors("pu", [1e-6, 1e-6, 1e-6, 1e-6, 1e-6, 1e-6], [3.0, 0.0, 0.0, 3.0, 0.0, 0.0])
    s.set_measure_event("pu", "i", 0.0, 600, 1e-8, 1e-8, False)
    s.add_sequence(101, "pu", 1)
    s.set_measure_current_range(101, "10ma")
    s.execute()
    s.wait_until_completed()
    _, i = s.measure_values(101, 0, 600)
    q_p, q_u = i[:100].sum() * 1e-8, i[300:400].sum() * 1e-8
    pr_a = 20e-6 * 1e4 * 1e-8  # Pr (uC/cm2) x area (cm2), C
    assert q_p - q_u == pytest.approx(2 * pr_a, rel=0.05)
    assert st.flex.instrument.state.devices["c"]["p"] == pytest.approx(0.8)


def test_lwp_shaped_table_run_with_504000_points() -> None:
    """The lab's Fast IV run (blueprint v2 1.1): 1,825-vector patterns, one 504,000-point event at 100 ns, ch1 V and
    ch2 I, read back in 100,000-value chunks."""
    st = ex.station(ex.resistor(1e4, 101, 102))
    s = st.sim
    s.open_session(ADDR)
    s.initialize()
    for ch in (101, 102):
        s.set_operation_mode(ch, "fastiv")
        s.set_force_voltage_range(ch, "5v")
    s.set_measure_mode(102, "current")
    s.set_measure_current_range(102, "1ma")
    levels = np.round(np.linspace(0.1, 1.0, 1825), 4)
    s.create_pattern("ch1", 0.0)
    s.add_vectors("ch1", [3e-5] * 1825, levels)
    s.create_pattern("ch2", 0.0)
    s.add_vectors("ch2", [3e-5] * 1825, [0.0] * 1825)
    s.set_measure_event("ch2", "m", 1e-6, 504_000, 1e-7, 0.0, False)
    s.add_sequence(101, "ch1", 1)
    s.add_sequence(102, "ch2", 1)
    s.connect(101)
    s.connect(102)
    s.execute()
    s.wait_until_completed()
    chunks = [s.measure_values(102, off, 100_000) for off in range(0, 504_000, 100_000)]
    t = np.concatenate([c[0] for c in chunks])
    v = np.concatenate([c[1] for c in chunks])
    assert len(v) == 504_000 and t[-1] == pytest.approx(1e-6 + 503_999e-7)
    expected = -s.force_levels(101, t) / 1e4
    assert np.allclose(v, expected, atol=1e-15)
    s.initialize()
    s.close_session()
    st.flex.instrument.assert_safe()


# -- shared instrument: clock, circuit, RSU, persistence, lock ------------------------------------------------------


def test_smu_and_wgfmu_share_the_clock_and_the_dut() -> None:
    st = ex.station(ex.resistor(1e3, 101, 201))
    s = st.sim
    online(s, 101)
    s.create_pattern("ramp", 0.0)
    s.add_vectors("ramp", [1.0], [1.0])
    s.add_sequence(101, "ramp", 1)
    s.poll_quantum_s = 0.5
    st.flex_run("CN 201", "DV 201,0,0,1E-2")
    s.execute()
    s.status()  # the host waited half a second
    st.flex_run("MM 1,201", "XE")
    assert values(st.flex.read()) == pytest.approx([-0.5e-3], rel=1e-6)  # the SMU sinks the WGFMU's 0.5 V
    s.wait_until_completed()
    st.flex_run("XE")
    assert values(st.flex.read()) == pytest.approx([-1e-3], rel=1e-6)  # the channel keeps its last 1 V
    s.initialize()
    st.flex_run("XE")
    assert values(st.flex.read()) == pytest.approx([0.0], abs=1e-15)  # RSU on its SMU path: the WGFMU is gone


def test_rsu_smu_path_passes_the_cabled_smu() -> None:
    sc = ex.scenario({"r": {"model": "resistor", "params": {"r_ohm": 1e3}}}, {"r": {"a": 101, "b": "GNDU"}},
                     rsu_smu={101: 201})
    st = ex.station(sc)
    s = st.sim
    assert s.rsu_path(101) == "smu"
    st.flex_run("CN 201", "DV 201,0,2,1E-2", "MM 1,201", "XE")
    assert values(st.flex.read()) == pytest.approx([2e-3], rel=1e-6)  # through the RSU's "From SMU" input
    online(s, 101, mode="dc")
    s.dc_force_voltage(101, 0.5)
    assert s.rsu_path(101) == "wgfmu"
    st.flex_run("XE")
    assert values(st.flex.read()) == pytest.approx([0.0], abs=1e-15)  # the RSU switched to the WGFMU
    s.set_measure_mode(101, "current")
    assert s.dc_measure_value(101) == pytest.approx(0.5e-3)
    s.disconnect(101)
    st.flex_run("XE")
    assert values(st.flex.read()) == pytest.approx([2e-3], rel=1e-6)


def test_hardware_state_persists_across_processes(tmp_path: Path) -> None:
    state_file = tmp_path / "sim" / "wg.state.json"
    sc = ex.resistor(1e3, 101, 201)
    first = ex.station(sc, state_file=state_file)
    online(first.sim, 101, mode="dc")
    first.sim.dc_force_voltage(101, 1.0)
    flat(first.sim, "p", 0.2, 10.0)
    first.sim.add_sequence(102, "p", 1)
    first.sim.set_operation_mode(102, "fastiv")
    first.sim.connect(102)
    first.sim.execute()
    first.flex.save_state()
    second = SimTransport(sc, state_file=state_file)  # another process, no library loaded
    second.open()
    reasons = second.instrument.unsafe_reasons()
    assert "WGFMU channel 101: connected (dc mode, 1.0 V)" in reasons
    assert "WGFMU channel 102: sequencer running" in reasons
    second.write("CN 201")
    second.write("DV 201,0,0,1E-2")
    second.write("MM 1,201")
    second.write("XE")
    assert values(second.read()) == pytest.approx([-1e-3], rel=1e-6)  # the persisted WGFMU level drives the DUT
    lib = SimWgfmu(second.instrument)
    lib.open_session(ADDR)
    assert lib.channel_status(102)[0] == 10002  # a sequencer another process started
    lib.abort()
    lib.initialize()
    lib.close_session()
    second.write("CL")
    second.save_state()
    first.flex.load_state()
    assert first.sim._run is not None and first.sim._run.finished  # the other process stopped it
    first.sim.close_session()
    first.flex.instrument.assert_safe()


def test_online_calls_need_the_flex_exclusive_lock_released() -> None:
    from b1500_test_agent.models.station import Settings
    from b1500_test_agent.transport.audit import MemoryAuditSink
    from b1500_test_agent.transport.factory import make_bus

    sc = ex.scenario().model_copy(update={"name": "nmos_basic"})
    sink = MemoryAuditSink()
    bus = make_bus(Settings(), sink, scenario=sc)
    assert bus.wgfmu is not None and bus.wgfmu.inner._inst is bus.flex.inner.instrument
    bus.flex.open()
    bus.flex.lock()
    with pytest.raises(WgfmuError) as info:
        bus.wgfmu.open_session(bus.flex.resource)
    assert info.value.rc == -5 and info.value.code == "transport_error"
    bus.flex.unlock()
    bus.wgfmu.open_session(bus.flex.resource)
    assert bus.wgfmu.channel_ids() == [101, 102]
    bus.flex.lock()
    assert code_of(bus.wgfmu.initialize) == -5
    bus.flex.unlock()
    bus.wgfmu.close_session()
    bus.flex.close()
    calls = [(e.data["fn"], e.data["rc"]) for e in sink.events if e.ev == "wgfmu_call"]
    assert calls == [("open_session", -5), ("open_session", 0), ("channel_ids", 0), ("initialize", -5),
                     ("close_session", 0)]


# -- faults ----------------------------------------------------------------------------------------------------------


def test_wgfmu_hang_on_wait_blocks_for_the_timeout_and_the_run_never_completes() -> None:
    st = ex.station(ex.scenario())
    st.flex.inject(WgfmuHang(fn="wait_until_completed"))
    s = st.sim
    online(s, 101)
    s.set_timeout(5.0)
    flat(s, "p", 0.4, 1e-3)
    s.add_sequence(101, "p", 1)
    s.execute()
    t0 = st.flex.instrument.clock
    with pytest.raises(WgfmuError) as info:
        s.wait_until_completed()
    assert info.value.rc == -5 and info.value.code == "transport_error"
    assert st.flex.instrument.clock - t0 == pytest.approx(5.0)
    assert s.status()[0] == 10002  # still running long after its 1 ms
    assert code_of(s.wait_until_completed) == -5  # no answer again
    s.abort()
    assert s.status()[0] == 10003
    s.initialize()
    s.close_session()
    st.flex.instrument.assert_safe()


def test_wgfmu_hang_on_execute_starts_a_hung_sequencer() -> None:
    st = ex.station(ex.scenario())
    st.flex.inject(WgfmuHang(fn="execute"))
    s = st.sim
    online(s, 101)
    flat(s, "p", 0.4, 1e-3)
    s.add_sequence(101, "p", 1)
    with pytest.raises(WgfmuError):
        s.execute()
    assert "WGFMU channel 101: sequencer running" in st.flex.instrument.unsafe_reasons()
    s.abort()
    s.initialize()
    s.close_session()
    st.flex.instrument.assert_safe()


def test_wgfmu_disconnect_fails_keeps_the_rsu_connected() -> None:
    st = ex.station(ex.scenario())
    st.flex.inject(WgfmuDisconnectFails(channels=[101], count=None))
    s = st.sim
    online(s, 101, 102, mode="dc")
    s.update()  # applies the DC mode
    with pytest.raises(WgfmuError):
        s.disconnect(101)
    s.disconnect(102)
    s.initialize()
    s.close_session()
    assert st.flex.instrument.unsafe_reasons() == ["WGFMU channel 101: connected (dc mode, 0.0 V)"]
    st.flex.clear_faults()
    s.open_session(ADDR)
    s.disconnect(101)
    s.close_session()
    st.flex.instrument.assert_safe()


def test_wgfmu_dll_missing() -> None:
    from b1500_test_agent.models.station import Settings
    from b1500_test_agent.transport.audit import MemoryAuditSink
    from b1500_test_agent.transport.factory import make_bus

    sc = ex.scenario().model_copy(update={"name": "nmos_basic"})
    assert make_bus(Settings(), MemoryAuditSink(), scenario=sc, faults=[WgfmuDllMissing()]).wgfmu is None
    st = ex.station(sc)
    st.flex.inject(WgfmuDllMissing())
    assert code_of(lambda: st.sim.open_session(ADDR)) == -7


def test_self_test_resets_the_wgfmu_and_closes_the_smus() -> None:
    st = ex.station(ex.resistor(1e3, 101, 201))
    s = st.sim
    online(s, 101, mode="dc")
    s.dc_force_voltage(101, 1.0)
    st.flex_run("CN 201", "DV 201,0,1")
    assert s.self_test() == 0
    assert s.self_calibration() == 0
    s.close_session()
    st.flex.instrument.assert_safe()


def test_open_session_warns_about_a_non_empty_instrument_error_queue() -> None:
    st = ex.station()
    st.flex.write("XX")  # unknown command: error 100 queued
    st.sim.open_session(ADDR)
    assert st.sim.warnings() == [("normal", "open_session: the instrument error queue is not empty (1 error(s))")]


def test_a_waveform_program_loads_with_the_models_counts_and_times() -> None:
    """WP5.4's ``WaveformProgram`` (``models/sources.py``) and the simulator agree on data sizes and output time."""
    from b1500_test_agent.models.sources import WaveformProgram

    program = WaveformProgram.model_validate({
        "builder": "table",
        "channels": {201: {"mode": "fastiv", "force_range": "5v", "measure": "voltage"},
                     202: {"mode": "fastiv", "measure": "current", "current_range": "1ma"}},
        "patterns": {"gate": {"v0": 0.0, "vectors": [[1e-7, 2.0], [9e-7, 2.0], [1e-7, 0.0], [9e-7, 0.0]]},
                     "drain": {"v0": 0.1, "vectors": [[2e-6, 0.1]]},
                     "rest": {"v0": 0.0, "vectors": [[5e-7, 0.0]]}},
        "events": [{"kind": "measure", "pattern": "drain", "event": "id", "t": 2e-7, "points": 8, "interval": 1e-7,
                    "average": 5e-8},
                   {"kind": "measure", "pattern": "drain", "event": "raw", "t": 1.2e-6, "points": 3,
                    "interval": 2e-7, "average": 2e-8, "raw": True},
                   {"kind": "range", "pattern": "drain", "event": "r", "t": 1.1e-6, "range": "100ua"}],
        "sequences": {201: [["gate", 5], ["rest", 1]], 202: [["drain", 5], ["rest", 1]]},
    })
    sc = ex.scenario(slots=[{"slot": 2, "model": "B1530A"}, {"slot": 3, "model": "B1517A"}])
    st = ex.station(sc)
    s = st.wg
    s.open_session(ADDR)
    s.initialize()
    for ch, setup in program.channels.items():
        s.set_operation_mode(ch, setup.mode)
        s.set_force_voltage_range(ch, setup.force_range)
        s.set_measure_mode(ch, setup.measure)
        if setup.current_range:
            s.set_measure_current_range(ch, setup.current_range)
    for name, pattern in program.patterns.items():
        s.create_pattern(name, pattern.v0)
        s.add_vectors(name, [dt for dt, _ in pattern.vectors], [v for _, v in pattern.vectors])
    for event in program.events:
        if event.kind == "measure":
            s.set_measure_event(event.pattern, event.event, event.t, event.points, event.interval, event.average,
                                event.raw)
        else:
            s.set_range_event(event.pattern, event.event, event.t, event.range)
    for ch, items in program.sequences.items():
        for name, count in items:
            s.add_sequence(ch, name, count)
        s.connect(ch)
    s.execute()
    s.wait_until_completed()
    for ch in program.channels:
        assert s.measure_value_size(ch)[1] == program.points(ch)
        assert s.channel_status(ch)[2] == pytest.approx(program.sequence_time_s(ch), abs=1e-15)
    assert program.points(202) == 5 * (8 + 3 * 5)
    s.initialize()
    s.close_session()
    st.flex.instrument.assert_safe()


@pytest.mark.parametrize("rsu_smu", [{201: 101}, {101: 102}, {102: 1}])
def test_rsu_smu_must_map_a_wgfmu_channel_to_an_smu(rsu_smu: dict[int, int]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="rsu_smu"):
        ex.scenario(rsu_smu=rsu_smu)  # slot 1 WGFMU, slot 2 HRSMU: 201 is an SMU, 102 -> 1 is a WGFMU slot
