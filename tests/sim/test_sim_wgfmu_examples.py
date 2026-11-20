"""``SimWgfmu`` against the shapes of WG Examples 1-11, the DC guide and Table 4-15 (blueprint v2 8.1; AC of WP10.1:
"example shapes reproduce event counts/timings; RAW vs AVERAGED sizes"). Fixture: ``tests/fixtures/wgfmu/
examples.yaml``; replays: ``tests/sim/wgfmu_examples.py``."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.models.audit import AuditEvent
from tests.sim import wgfmu_examples as ex

pytestmark = pytest.mark.wgfmu


def expect(name: str) -> dict:
    return ex.example(name)["expect"]


def test_example_1_pulse_output_shape() -> None:
    out = ex.ex01(ex.station())
    e = expect("ex01")
    assert out["status"] == (10000, pytest.approx(e["total_time_s"]), pytest.approx(e["total_time_s"]))
    assert out["size"] == (e["values"], e["values"])
    assert out["levels"] == pytest.approx([v for _, v in e["levels"]], abs=1e-12)
    assert out["final_level"] == e["final_level"]


def test_example_2_sampling_counts_and_times() -> None:
    st = ex.station()
    out = ex.ex02(st)
    e = expect("ex02")
    assert len(out["times"]) == len(out["values"]) == e["values"]
    for index, t in e["times_s"]:
        assert out["times"][index] == pytest.approx(t, abs=1e-15)
    for index, v in e["voltages"]:
        assert out["values"][index] == pytest.approx(v, abs=1e-12)
    # every repeat is identical (no delay between repeats of one sequence)
    assert np.allclose(out["values"].reshape(10, 100), out["values"][:100])
    assert np.allclose(np.diff(out["times"]), 1e-5)
    st.flex.instrument.assert_safe()


def test_audit_records_every_library_call_of_example_2() -> None:
    st = ex.station()
    ex.ex02(st)
    events = [e for e in st.sink.events if e.ev == "wgfmu_call"]
    assert [e.data["fn"] for e in events][:6] == ["clear", "create_pattern", "add_vectors", "add_vectors",
                                                  "add_vectors", "add_vectors"]
    add = events[2]
    assert add.cmd == "WGFMU_addVectors" and add.data == {"fn": "add_vectors", "pattern": "pulse", "n_dt": 1,
                                                          "n_v": 1, "rc": 0}
    meas = next(e for e in events if e.data["fn"] == "set_measure_event")
    assert meas.data["points"] == 100 and meas.data["interval"] == 1e-5 and meas.data["raw"] is False
    reads = [e for e in events if e.data["fn"] == "measure_values"]
    assert reads and reads[0].resp == "n=1000"
    for event in events:  # the JSONL line keeps the payload (ts and dur_ms are rounded in the line)
        back = AuditEvent.from_json_line(event.to_json_line())
        assert (back.ev, back.cmd, back.resp, back.data, back.error) == (event.ev, event.cmd, event.resp,
                                                                         event.data, event.error)


def test_example_3_overwrite_warning_and_bad_mode_error() -> None:
    st = ex.station()
    out = ex.ex03(st)
    e = expect("ex03")
    assert out["error"] is not None and out["error"].wgfmu_code == e["error_code"] == out["error"].rc
    assert out["error"].function == "set_operation_mode"
    assert len(out["error_strings"]) == 1 and e["error_text_contains"] in out["error_strings"][0]
    assert [w[0] for w in out["warnings"]] == [e["overwrite_warning"]]
    assert st.sim._patterns["pulse"].measures[0].points == 100  # line 12 overwrote line 11
    failed = [x for x in st.sink.events if x.error]
    assert len(failed) == 1 and failed[0].data["rc"] == -1 and failed[0].cmd == "WGFMU_setOperationMode"


def test_example_4_severe_warning_treated_as_error() -> None:
    out = ex.ex04(ex.station())
    e = expect("ex04")
    assert [err.wgfmu_code for err in out["errors"]] == [e["error_code"]]
    assert "warning treated as error" in out["errors"][0].text
    assert out["size"] == (e["values"], e["values"])
    assert e["values"] == e["kept_event_points"] * 10


def test_example_5_error_summary() -> None:
    out = ex.ex05(ex.station())
    e = expect("ex05")
    assert [c for c in out["codes"] if c] == e["summary_codes"]
    lines = out["summary"].splitlines()
    assert len(lines) == 2 and "-1 WGFMU_PARAMETER_OUT_OF_RANGE_ERROR" in lines[0]
    assert "-13 WGFMU_SEQUENCER_NOT_RUNNING_ERROR" in lines[1]
    assert out["warnings"] == e["warnings"]


def test_example_6_three_rates_two_channels() -> None:
    e, p = expect("ex06"), ex.example("ex06")["params"]
    out = ex.ex06(ex.station(ex.resistor(p["r_ohm"], 101, 102)))
    assert len(out["data_v"]) == e["values"] == 3 * p["points"]
    assert out["total"] == pytest.approx(e["total_time_s"], abs=1e-12)
    assert out["times"][3] == pytest.approx(e["total_time_s"], abs=1e-12)
    firsts = [out["data_t"][k * p["points"]] for k in range(3)]
    assert firsts == pytest.approx(e["event_first_times_s"], abs=1e-12)
    for k, interval in enumerate(p["intervals"]):
        block = out["data_t"][k * p["points"]:(k + 1) * p["points"]]
        assert np.allclose(np.diff(block), interval, rtol=0, atol=1e-12)
    assert np.allclose(out["data_v"], e["current_a"], rtol=1e-12)


def test_example_7_polling_reaches_completion() -> None:
    p = ex.example("ex06")["params"]
    out = ex.ex07(ex.station(ex.resistor(p["r_ohm"], 101, 102)))
    e = expect("ex07")
    assert out["status"] == e["final_status"] and out["events"] == e["events"] and out["values"] == e["values"]
    assert 2 <= out["polls"] <= 200  # about 1 % of the 3.6 s run per poll
    assert len(out["data_v"]) == e["values"][0]


def test_example_8_event_specific_partial_read() -> None:
    p = ex.example("ex06")["params"]
    out = ex.ex08(ex.station(ex.resistor(p["r_ohm"], 101, 102)))
    e = expect("ex08")
    assert out["completed"] is e["completed"] and out["index"] == e["index"] and out["size"] == e["size"]
    assert out["times"][0] == pytest.approx(e["first_time_s"], abs=1e-12)
    assert np.allclose(np.diff(out["times"]), 1e-5, atol=1e-12)
    assert out["polls"] > 1  # the 100 kHz event completes before the 1 MHz one, well before the run ends


def test_example_9_id_vg_shape() -> None:
    p, e = ex.example("ex09")["params"], expect("ex09")
    sc = ex.scenario({"m": {"model": "mosfet_ekv", "params": {"polarity": "p", "vth0": -1.5, "beta": 2.0e-5}}},
                     {"m": {"gate": p["gate"], "drain": p["drain"], "source": "GNDU", "bulk": "GNDU"}})
    out = ex.ex09(ex.station(sc))
    assert (out["n_vg"], out["n_vd"]) == (e["vg_steps"], e["vd_steps"])
    assert out["vectors"] == (e["gate_vectors"], e["drain_vectors"])
    assert out["totals"] == pytest.approx((e["gate_total_s"], e["drain_total_s"]), abs=1e-12)
    assert sum(len(f[2]) for f in out["files"]) == e["values"]
    assert all(len(f[2]) == e["per_file"] for f in out["files"])
    first_t = out["files"][0][3]
    assert first_t[0] == pytest.approx(e["first_event_time_s"], abs=1e-12)
    assert np.allclose(np.diff(first_t), e["interval_s"], atol=1e-12)
    _, vd0_drain, vd0_current, _ = out["files"][0]
    assert np.all(vd0_drain == 0.0) and np.allclose(vd0_current, 0.0, atol=1e-15)
    gate, drain, current, _ = out["files"][1]  # Vd = -2 V: the sampled window lies on each gate plateau
    assert np.allclose(drain, -2.0)
    assert gate[0] == pytest.approx(-2.0) and gate[-1] == pytest.approx(-3.0)
    assert np.all(current < 0) and np.all(np.diff(current) < 0)  # p-channel: more negative Id as |Vg| grows


def test_example_10_smu_bias_and_wgfmu_on_one_dut() -> None:
    p, e = ex.example("ex10")["params"], expect("ex10")
    st = ex.station(ex.resistor(p["r_ohm"], 101, 201))
    out = ex.ex10(st)
    assert len(out["values"]) == e["values"]
    st.flex.instrument.assert_safe()
    st2 = ex.station(ex.resistor(p["r_ohm"], 101, 201))
    current = ex.ex10(st2, measure_current=True)  # the same run measuring the WGFMU current: I = (V(t) - 3 V) / R
    t = current["times"] % 1e-3
    expected_v = np.interp(t, [0, 1e-4, 5e-4, 6e-4, 1e-3], [0, 1, 1, 0, 0])
    assert np.allclose(current["values"], (expected_v - p["smu_v"]) / p["r_ohm"], atol=1e-12)
    st2.flex.instrument.assert_safe()


def test_example_11_flex_and_library_sessions_together() -> None:
    e = expect("ex11")
    st = ex.station()
    out = ex.ex11(st)
    assert out["timeout"] == e["timeout_s"] and out["errx"].split(",")[0] == e["errx"]
    assert out["size"] == (e["values"], e["values"]) and out["nub"] == "0"
    st.flex.instrument.assert_safe()


def test_dc_measurement_guide() -> None:
    p, e = ex.example("dc")["params"], expect("dc")
    out = ex.dc(ex.station(ex.resistor(p["r_ohm"], p["channel"], "GNDU")))
    assert out["current"] == pytest.approx(e["current_a"], rel=1e-12)


def test_table_4_15_status_counts() -> None:
    p, e = ex.example("status_table_4_15")["params"], expect("status_table_4_15")
    st = ex.station()
    wg, sim = st.wg, st.sim
    for k, (length, count, events, points) in enumerate(p["sequences"]):
        name = f"seq{k}"
        wg.create_pattern(name, 0.0)
        wg.add_vectors(name, [length], [0.0])
        spacing = length / events
        for j in range(events):
            wg.set_measure_event(name, f"e{j}", j * spacing, points, 2e-8, 0.0, False)
        wg.add_sequence(101, name, count)
    ex.online_single(wg)
    sim.poll_quantum_s = 0.0
    wg.execute()
    status, elapsed, total = wg.channel_status(101)
    assert status == 10002 and elapsed == 0.0 and total == pytest.approx(e["total_time_s"], abs=1e-15)
    assert sim.completed_measure_event_size(101) == (0, e["total_events"])
    assert wg.measure_value_size(101) == (0, e["total_points"])
    st.flex.instrument.clock += e["at_time_s"]
    status, elapsed, _ = wg.channel_status(101)
    assert status == 10002 and elapsed == pytest.approx(e["at_time_s"], abs=1e-15)
    assert sim.completed_measure_event_size(101) == (e["completed_events"], e["total_events"])
    assert wg.measure_value_size(101) == (e["completed_points"], e["total_points"])
    wg.wait_until_completed()
    assert wg.channel_status(101) == (10000, pytest.approx(e["total_time_s"]), pytest.approx(e["total_time_s"]))
