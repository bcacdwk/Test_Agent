"""Replays of the WGFMU programming examples of WG chapter 3 (fixture ``tests/fixtures/wgfmu/examples.yaml``) through
the ``WgfmuApi`` protocol on the simulator, line by line as the manual's C code (Python names, the protocol's
literals for the C constants). Each ``exNN`` returns what the example's program would have printed or saved."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.audit import MemoryAuditSink
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "wgfmu" / "examples.yaml"
EXAMPLES: dict[str, Any] = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
ADDRESS = "GPIB0::17::INSTR"


def example(name: str) -> dict[str, Any]:
    """The fixture entry of one example (``params`` and ``expect``)."""
    return EXAMPLES["examples"][name]


def scenario(models: dict[str, Any] | None = None, wiring: dict[str, Any] | None = None, *,
             noise: dict[str, Any] | None = None, slots: list[dict[str, Any]] | None = None,
             **extra: Any) -> SimScenario:
    """The examples' mainframe (WGFMU slot 1, HRSMU slot 2) with the given DUT (noiseless by default)."""
    return SimScenario.model_validate({
        "name": "wgfmu_examples", "idn": "Keysight Technologies,B1500A,0,A.06.02.2023.0401",
        "slots": slots or EXAMPLES["mainframe"], "wiring": wiring or {}, "models": models or {},
        "noise": noise or {"floor_a": {}, "rel": 0.0, "seed": 11}, **extra,
    })


def resistor(r_ohm: float, a: int | str, b: int | str) -> SimScenario:
    return scenario({"r": {"model": "resistor", "params": {"r_ohm": r_ohm}}}, {"r": {"a": a, "b": b}})


@dataclass
class Station:
    """An opened simulated B1500A: the FLEX link and the audited library on the same instrument."""

    flex: SimTransport
    sim: SimWgfmu
    wg: AuditingWgfmu
    sink: MemoryAuditSink = field(default_factory=MemoryAuditSink)

    def flex_run(self, *lines: str) -> None:
        for line in lines:
            self.flex.write(line)


def station(sc: SimScenario | None = None, *, state_file: Path | None = None) -> Station:
    flex = SimTransport(sc or scenario(), state_file=state_file)
    flex.open()
    sim = SimWgfmu(flex.instrument)
    sink = MemoryAuditSink()
    return Station(flex, sim, AuditingWgfmu(sim, sink, backend="sim"), sink)


def pulse_pattern(wg: Any, name: str = "pulse") -> None:
    """Lines 10-14 of Examples 1-5, 10, 11: 0.1 ms rise to 1 V, 0.4 ms hold, 0.1 ms fall, 0.4 ms base."""
    wg.create_pattern(name, 0)
    for dt, v in example("ex01")["params"]["vectors"]:
        wg.add_vectors(name, [dt], [v])


def measure(wg: Any, pattern: str, ev: dict[str, Any]) -> None:
    wg.set_measure_event(pattern, ev["name"], ev["t"], ev["points"], ev["interval"], ev["average"], ev["raw"])


def online_single(wg: Any, ch: int = 101, mode: str = "fastiv") -> None:
    """Lines 18-21 of Example 1: open, initialize, Fast IV, connect."""
    wg.open_session(ADDRESS)
    wg.initialize()
    wg.set_operation_mode(ch, mode)
    wg.connect(ch)


def read_all(wg: Any, ch: int) -> tuple[np.ndarray, np.ndarray]:
    """``writeResults``: every measured value of ``ch`` (time, value), read in 100,000-value chunks."""
    measured, _ = wg.measure_value_size(ch)
    parts = [wg.measure_values(ch, offset, 100_000) for offset in range(0, measured, 100_000)]
    if not parts:
        return np.zeros(0), np.zeros(0)
    return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])


def ex01(st: Station) -> dict[str, Any]:
    p = example("ex01")["params"]
    wg = st.wg
    wg.clear()
    pulse_pattern(wg, p["pattern"])
    wg.add_sequence(p["channel"], p["pattern"], p["count"])
    online_single(wg, p["channel"])
    wg.execute()
    wg.wait_until_completed()
    status = wg.channel_status(p["channel"])
    size = wg.measure_value_size(p["channel"])
    levels = [float(st.sim.force_levels(p["channel"], [t])[0]) for t, _ in example("ex01")["expect"]["levels"]]
    final = st.flex.instrument.state.wgfmu[p["channel"]].voltage
    wg.initialize()
    wg.close_session()
    return {"status": status, "size": size, "levels": levels, "final_level": final}


def ex02(st: Station) -> dict[str, Any]:
    wg = st.wg
    wg.clear()
    pulse_pattern(wg)
    measure(wg, "pulse", example("ex02")["params"]["event"])
    wg.add_sequence(101, "pulse", 10)
    online_single(wg)
    wg.execute()
    wg.wait_until_completed()
    times, values = read_all(wg, 101)
    wg.initialize()
    wg.close_session()
    return {"times": times, "values": values}


def _ex03_offline(wg: Any) -> None:
    wg.clear()
    pulse_pattern(wg)
    for ev in example("ex03")["params"]["events"]:
        measure(wg, "pulse", ev)
    wg.add_sequence(101, "pulse", 10)


def ex03(st: Station) -> dict[str, Any]:
    """``checkError`` throws at the first error (line 18) and the catch block reads one error string."""
    wg = st.wg
    caught: WgfmuError | None = None
    try:
        _ex03_offline(wg)
        wg.open_session(ADDRESS)
        wg.initialize()
        wg.set_operation_mode(101, example("ex03")["params"]["bad_mode"])
        wg.connect(101)  # pragma: no cover - not reached
    except WgfmuError as exc:
        caught = exc
    return {"error": caught, "error_strings": wg.errors(), "warnings": st.sim.warnings()}


def ex04(st: Station) -> dict[str, Any]:
    """``checkError2`` prints the error and continues."""
    wg = st.wg
    errors: list[WgfmuError] = []

    def check(call: Callable[[], object]) -> None:
        try:
            call()
        except WgfmuError as exc:
            errors.append(exc)

    check(wg.clear)
    st.sim.treat_warnings_as_errors(example("ex04")["params"]["treat_level"])
    pulse_pattern(wg)
    for ev in example("ex03")["params"]["events"]:
        check(lambda ev=ev: measure(wg, "pulse", ev))
    check(lambda: wg.add_sequence(101, "pulse", 10))
    online_single(wg)
    check(wg.execute)
    check(wg.wait_until_completed)
    size = wg.measure_value_size(101)
    check(wg.initialize)
    check(wg.close_session)
    return {"errors": errors, "size": size}


def ex05(st: Station) -> dict[str, Any]:
    """Return codes ignored, then the error summary."""
    wg = st.wg

    def ret(call: Callable[[], object]) -> int:
        try:
            call()
        except WgfmuError as exc:
            return exc.rc
        return 0

    _ex03_offline(wg)
    codes = [ret(lambda: wg.open_session(ADDRESS)), ret(wg.initialize),
             ret(lambda: wg.set_operation_mode(101, example("ex03")["params"]["bad_mode"])),
             ret(lambda: wg.connect(101)), ret(wg.execute), ret(wg.wait_until_completed), ret(wg.initialize),
             ret(wg.close_session)]
    return {"codes": codes, "summary": st.sim.error_summary(), "warnings": [w[0] for w in st.sim.warnings()]}


def _ex06_setup(st: Station) -> dict[str, Any]:
    p = example("ex06")["params"]
    pts, iv, avg = p["points"], p["intervals"], p["average"]
    times = [p["time0"]]
    for interval in iv:
        times.append(times[-1] + interval * pts + avg)
    wg = st.wg
    wg.clear()
    wg.create_pattern("v1", p["v1"])
    wg.add_vectors("v1", [times[3]], [p["v1"]])
    wg.create_pattern("v2", p["v2"])
    wg.add_vectors("v2", [times[3]], [p["v2"]])
    for k, name in enumerate(p["events"]):
        wg.set_measure_event("v2", name, times[k], pts, iv[k], avg, False)
    wg.add_sequence(101, "v1", 1)
    wg.add_sequence(102, "v2", 1)
    wg.open_session(ADDRESS)
    wg.initialize()
    wg.set_operation_mode(101, "fastiv")
    wg.set_operation_mode(102, "fastiv")
    wg.set_measure_mode(102, "current")
    wg.connect(101)
    wg.connect(102)
    wg.execute()
    return {"times": times}


def ex06(st: Station) -> dict[str, Any]:
    setup = _ex06_setup(st)
    st.wg.wait_until_completed()
    times, values = read_all(st.wg, 102)
    total = st.wg.channel_status(102)[2]
    st.wg.initialize()
    st.wg.close_session()
    return {**setup, "data_t": times, "data_v": values, "total": total}


def ex07(st: Station) -> dict[str, Any]:
    _ex06_setup(st)
    wg = st.wg
    polls = 0
    while True:
        status, elapsed, total = wg.channel_status(102)
        measured, total_values = wg.measure_value_size(102)
        done_events, total_events = st.sim.completed_measure_event_size(102)
        polls += 1
        if (status == 10000 and elapsed == total and measured == total_values
                and done_events == total_events):
            break
    _, values = read_all(wg, 102)
    wg.initialize()
    wg.close_session()
    return {"status": status, "events": [done_events, total_events], "values": [measured, total_values],
            "polls": polls, "data_v": values}


def ex08(st: Station) -> dict[str, Any]:
    _ex06_setup(st)
    p = example("ex08")["params"]
    wg = st.wg
    polls = 0
    while True:
        wg.channel_status(102)  # the host waits between the checks
        completed, index, size = st.sim.measure_event_completed(102, p["pattern"], p["event"], p["cycle"],
                                                                p["loop"], p["count"])
        polls += 1
        if completed:
            break
    times, values = wg.measure_values(102, index, size)
    wg.initialize()
    wg.close_session()
    return {"completed": completed, "index": index, "size": size, "times": times, "values": values, "polls": polls}


def ex09(st: Station) -> dict[str, Any]:
    p = example("ex09")["params"]
    pol = p["polarity"]
    n_vg = int((p["vg_max"] - p["vg_min"]) / p["vg_step"]) + 1
    vd_len = (p["vg_rise"] + p["vg_step_length"]) * n_vg
    n_vd = int((p["vd_max"] - p["vd_min"]) / p["vd_step"]) + 1
    wg = st.wg
    wg.clear()
    vg = p["vg_min"]
    wg.create_pattern("Vg", vg * pol)
    for i in range(n_vg):
        vg = p["vg_min"] + p["vg_step"] * i
        wg.add_vectors("Vg", [p["vg_rise"]], [vg * pol])
        wg.add_vectors("Vg", [p["vg_step_length"]], [vg * pol])
    wg.add_sequence(p["gate"], "Vg", n_vd)
    vd = p["vd_min"]
    wg.create_pattern("Vd", vd)
    for i in range(n_vd):
        vd = p["vd_min"] + p["vd_step"] * i
        wg.add_vectors("Vd", [p["vd_rise"]], [vd * pol])
        wg.add_vectors("Vd", [vd_len], [vd * pol])
        wg.set_measure_event("Vd", "Id", (p["vd_rise"] + vd_len) * i + p["vg_rise"] + p["vg_step_delay"], n_vg,
                             p["vg_rise"] + p["vg_step_length"], p["vg_step_length"] - p["vg_step_delay"] * 2, False)
    wg.add_sequence(p["drain"], "Vd", 1)
    wg.open_session(ADDRESS)
    wg.initialize()
    wg.set_operation_mode(p["gate"], "fastiv")
    wg.set_operation_mode(p["drain"], "fastiv")
    wg.set_measure_mode(p["drain"], "current")
    wg.connect(p["gate"])
    wg.connect(p["drain"])
    wg.execute()
    wg.wait_until_completed()
    files = []
    for i in range(n_vd):  # writeResults3: interpolated gate voltage, drain current
        t, value = wg.measure_values(p["drain"], n_vg * i, n_vg)
        files.append((st.sim.force_levels(p["gate"], t), st.sim.force_levels(p["drain"], t), value, t))
    totals = (wg.channel_status(p["gate"])[2], wg.channel_status(p["drain"])[2])
    wg.initialize()
    wg.close_session()
    spec = st.sim._patterns  # the library's software setup, for the vector counts
    return {"n_vg": n_vg, "n_vd": n_vd, "files": files, "totals": totals,
            "vectors": (len(spec["Vg"].dts), len(spec["Vd"].dts))}


def ex10(st: Station, *, measure_current: bool = False) -> dict[str, Any]:
    p = example("ex10")["params"]
    wg = st.wg
    wg.clear()
    pulse_pattern(wg)
    measure(wg, "pulse", p["event"])
    wg.add_sequence(101, "pulse", 10)
    wg.open_session(ADDRESS)
    wg.initialize()
    wg.set_operation_mode(101, "fastiv")
    if measure_current:
        wg.set_measure_mode(101, "current")
    st.flex_run(p["flex_before"][0])
    wg.connect(101)
    st.flex_run(p["flex_before"][1])
    wg.execute()
    wg.wait_until_completed()
    times, values = read_all(wg, 101)
    wg.initialize()
    st.flex_run(*p["flex_after"])
    wg.close_session()
    return {"times": times, "values": values}


def ex11(st: Station) -> dict[str, Any]:
    p = example("ex11")["params"]
    wg = st.wg
    wg.clear()
    pulse_pattern(wg)
    measure(wg, "pulse", example("ex10")["params"]["event"])
    wg.add_sequence(101, "pulse", 10)
    wg.open_session(ADDRESS)
    wg.set_timeout(p["timeout_s"])
    st.flex_run(p["flex_reset"])
    wg.initialize()
    wg.set_operation_mode(101, "fastiv")
    st.flex_run(p["flex_enable"])
    wg.connect(101)
    errx = st.flex.query("ERRX?")
    wg.execute()
    wg.wait_until_completed()
    nub = st.flex.query("NUB?")
    size = wg.measure_value_size(101)
    wg.initialize()
    st.flex_run(p["flex_disable"])
    timeout = st.sim.timeout_s
    wg.close_session()
    return {"errx": errx, "nub": nub, "size": size, "timeout": timeout}


def dc(st: Station) -> dict[str, Any]:
    """Table 3-19: DC force and measure."""
    p = example("dc")["params"]
    wg = st.wg
    wg.open_session(ADDRESS)
    wg.initialize()
    wg.set_operation_mode(p["channel"], "dc")
    wg.set_measure_mode(p["channel"], "current")
    wg.set_measure_current_range(p["channel"], "1ma")
    wg.connect(p["channel"])
    wg.dc_force_voltage(p["channel"], p["v"])
    value = wg.dc_measure_value(p["channel"])
    wg.disconnect(p["channel"])
    wg.close_session()
    return {"current": value}
