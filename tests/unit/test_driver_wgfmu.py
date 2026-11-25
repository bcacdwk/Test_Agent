"""``WgfmuDriver`` (blueprint v2 2.5; WP10.3) over a recording fake of the ``WgfmuApi`` protocol, plus
``OutputGuard.check_sequence``: every operation that can put a level on the DUT is checked before its first library
call (a vector outside the envelope raises before ``add_vectors``: spy), the call order of ``load``/``run``, the
status poll with abort checks, chunked readback, the RSU route and states, and the safe state that runs every step.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.driver.errors import DriverStateError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.wgfmu import (
    POLL_S,
    RUN_MARGIN_S,
    WARNING_TEXT_CHARS,
    WgfmuDriver,
    WgfmuRunFailed,
    WgfmuRunTimeout,
    find_rsu,
    rsu_rest_path,
    rsu_targets,
    warning_facts,
)
from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import ChannelSetup, WaveformProgram
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import READBACK_CHUNK, WgfmuApi, WgfmuError
from tests.safety.wgfmu_helpers import BOTTOM, ENVELOPE, TOP, program
from tests.unit.rules_factory_v2 import RSU201, lab_station, wave, wg_limits

pytestmark = pytest.mark.wgfmu

SETUP_CALLS = ("set_operation_mode", "set_force_voltage_range", "set_measure_mode", "set_measure_current_range",
               "set_measure_voltage_range", "set_measure_enabled")


class FakeApi:
    """Records every ``WgfmuApi`` call; ``statuses`` are returned by ``status`` in turn (the last one repeats);
    ``values`` = measured values per channel; ``fail`` = method -> exception raised (once) by that method."""

    def __init__(self, *, statuses: Sequence[tuple[int, float, float]] = ((api.STATUS_COMPLETED, 4e-5, 4e-5),),
                 values: dict[int, int] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.statuses = list(statuses)
        self.values = values if values is not None else {TOP: 4000, BOTTOM: 4000}
        self.fail: dict[str, BaseException] = {}
        self.warning_lines: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name not in api.API_METHODS:
            raise AttributeError(name)

        def call(*args: Any) -> Any:
            self.calls.append((name, args))
            exc = self.fail.pop(name, None)
            if exc is not None:
                raise exc
            return self._answer(name, args)

        return call

    def _answer(self, name: str, args: tuple[Any, ...]) -> Any:
        if name == "status":
            return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if name == "measure_value_size":
            n = self.values.get(args[0], 0)
            return n, n
        if name == "measure_values":
            _, offset, size = args
            t = np.arange(offset, offset + size, dtype=float) * 1e-8
            return t, np.full(size, float(args[0]))
        if name == "channel_ids":
            return [TOP, BOTTOM]
        if name == "dc_measure_value":
            return 1.5e-4
        if name == "warnings":
            return list(self.warning_lines)
        return None

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def make(envelope: CompiledEnvelope = ENVELOPE, *, guard: bool = True, **kwargs: Any) \
        -> tuple[WgfmuDriver, FakeApi, list[float]]:
    fake = FakeApi(**kwargs)
    waits: list[float] = []
    g = OutputGuard(envelope, switches=lab_station().switches) if guard else None
    return WgfmuDriver(fake, g, wait=waits.append), fake, waits  # type: ignore[arg-type]


def test_the_fake_has_the_protocol_shape() -> None:
    assert set(api.API_METHODS) == {n for n in dir(WgfmuApi) if not n.startswith("_")}


# -- configure -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("setup", "calls"), [
    (ChannelSetup(mode="fastiv", force_range="5v", measure="current", current_range="1ma"),
     ["set_operation_mode", "set_force_voltage_range", "set_measure_mode", "set_measure_current_range",
      "set_measure_enabled"]),
    (ChannelSetup(mode="pg", force_range="3v", measure="voltage", voltage_range="5v", measure_enabled=False),
     ["set_operation_mode", "set_force_voltage_range", "set_measure_mode", "set_measure_voltage_range",
      "set_measure_enabled"]),
    (ChannelSetup(mode="dc", measure="current", current_range="10ua"),
     ["set_operation_mode", "set_force_voltage_range", "set_measure_mode", "set_measure_current_range"]),
    (ChannelSetup(mode="smu"), ["set_operation_mode", "set_force_voltage_range"]),
])
def test_configure_sends_the_settings_of_its_mode(setup: ChannelSetup, calls: list[str]) -> None:
    wg, fake, _ = make()
    wg.configure(TOP, setup)
    assert fake.names() == calls and all(args[0] == TOP for _, args in fake.calls)


def test_configure_refuses_a_channel_outside_the_allowlist_and_without_a_guard() -> None:
    wg, fake, _ = make()
    with pytest.raises(EnvelopeViolation) as caught:
        wg.configure(302, ChannelSetup(mode="fastiv"))
    assert caught.value.reason == "channel_not_allowed" and fake.calls == []
    wg, fake, _ = make(guard=False)
    with pytest.raises(EnvelopeViolation) as caught:
        wg.configure(TOP, ChannelSetup(mode="fastiv"))
    assert caught.value.reason == "no_guard" and fake.calls == []


# -- load: the AC spy ------------------------------------------------------------------------------------------------


def test_load_sends_the_program_in_order_after_every_check() -> None:
    wg, fake, _ = make()
    prog = program()
    wg.load(prog)
    names = fake.names()
    assert names[0] == "clear"
    first_pattern = names.index("create_pattern")
    assert set(names[1:first_pattern]) <= set(SETUP_CALLS)
    assert [args for name, args in fake.calls if name == "create_pattern"] == [("drive", 0.0), ("sense", 0.0)]
    vectors = [args for name, args in fake.calls if name == "add_vectors"]
    assert vectors[0] == ("drive", [1e-6] * 4, [3.0, 0.0, 3.0, 0.0])
    assert names.index("set_measure_event") > names.index("add_vectors")
    assert [args for name, args in fake.calls if name == "add_sequence"] == [(TOP, "drive", 10), (BOTTOM, "sense", 10)]
    assert wg.program == prog


def outside(data: dict[str, Any]) -> None:
    data["patterns"]["drive"]["vectors"][2] = [1e-6, 3.5]  # one vector above the channel's 3 V


@pytest.mark.parametrize(("mutate", "reason"), [
    (outside, "level_exceeds_envelope"),
    (lambda d: d["patterns"]["drive"].update(v0=-3.2), "level_exceeds_envelope"),
    (lambda d: d["patterns"]["drive"]["vectors"].__setitem__(0, [1.5e-8, 0.5]), "off_grid"),
    (lambda d: d["patterns"]["drive"].update(vectors=[[1e-8, 0.1]] * 2049), "vectors_exceed_envelope"),
    (lambda d: d["sequences"].update({"201": [["drive", 30_000]]}), "time_exceeds_envelope"),
    (lambda d: d["events"][0].update(points=400, interval=1e-8) or d["sequences"].update({"201": [["drive", 20_000]]}),
     "time_exceeds_envelope"),
    (lambda d: d["channels"].update({"302": {"mode": "fastiv"}}), "channel_not_allowed"),
])
def test_a_program_outside_the_envelope_raises_before_any_library_call(mutate: Callable[[dict[str, Any]], None],
                                                                     reason: str) -> None:
    """The AC: a vector (or anything else) outside the envelope raises before ``add_vectors`` (spy on the API)."""
    data = wave()
    mutate(data)
    wg, fake, _ = make()
    with pytest.raises(EnvelopeViolation) as caught:
        wg.load(WaveformProgram.model_validate(data))
    assert caught.value.reason == reason
    assert fake.calls == [] and wg.program is None  # not even clear: the earlier setup is untouched


def test_points_beyond_the_envelope_are_refused() -> None:
    env = ENVELOPE.model_copy(update={"waveform": {TOP: wg_limits(max_points=3999, total_time_s=1e-3),
                                                   BOTTOM: wg_limits(total_time_s=1e-3)}})
    wg, fake, _ = make(env)
    with pytest.raises(EnvelopeViolation) as caught:
        wg.load(program())
    assert caught.value.reason == "points_exceed_envelope" and caught.value.level == 4000 and fake.calls == []


def test_a_pattern_no_channel_outputs_is_not_sent() -> None:
    data = wave()
    data["patterns"]["spare"] = {"v0": 9.0, "vectors": [[1e-6, 9.0]]}  # outside every envelope, but never output
    data["events"].append({"kind": "measure", "pattern": "spare", "event": "x", "t": 0.0, "points": 1,
                           "interval": 1e-8})
    wg, fake, _ = make()
    wg.load(WaveformProgram.model_validate(data))
    assert all("spare" not in args for _, args in fake.calls)


# -- connect, DC -----------------------------------------------------------------------------------------------------


def test_connect_checks_the_rsu_route_first() -> None:
    wg, fake, _ = make()
    with pytest.raises(DriverStateError):
        wg.connect(TOP)  # mode unknown: configure first
    wg.configure(TOP, ChannelSetup(mode="fastiv"))
    fake.calls.clear()
    wg.connect(TOP)
    assert fake.names() == ["connect"] and wg.connected == {TOP}
    assert wg.rsu_states() == {"RSU201.OUT": "wgfmu"}

    env = ENVELOPE.model_copy(update={"routes": frozenset()})
    wg, fake, _ = make(env)
    wg.configure(TOP, ChannelSetup(mode="fastiv"))
    fake.calls.clear()
    with pytest.raises(EnvelopeViolation) as caught:
        wg.connect(TOP)
    assert caught.value.reason == "route_not_allowed" and fake.calls == [] and wg.connected == frozenset()


def test_smu_mode_needs_the_smu_route_and_an_rsu_must_be_declared() -> None:
    wg, _, _ = make()
    wg.configure(TOP, ChannelSetup(mode="smu"))
    assert wg.rsu_route(TOP) == Route(switch="RSU201", output="OUT", state="smu")
    with pytest.raises(EnvelopeViolation):
        wg.connect(TOP)  # the plan allows RSU201 -> wgfmu only
    no_rsu = WgfmuDriver(FakeApi(), OutputGuard(ENVELOPE), switches=())  # type: ignore[arg-type]
    no_rsu.configure(TOP, ChannelSetup(mode="fastiv"))
    with pytest.raises(EnvelopeViolation) as caught:
        no_rsu.connect(TOP)
    assert "no RSU" in str(caught.value)


def test_a_failed_connect_still_counts_for_the_safe_state() -> None:
    wg, fake, _ = make()
    wg.configure(TOP, ChannelSetup(mode="fastiv"))
    fake.fail["connect"] = WgfmuError(3001, "connect: firmware error 3001: RSU is not connected.", function="connect")
    with pytest.raises(WgfmuError):
        wg.connect(TOP)
    assert wg.connected == {TOP} and wg.rsu_states() == {}
    report = wg.safe_state()
    assert report.ok and ("disconnect 201", True, "") in report.steps and wg.connected == frozenset()


def test_a_dc_program_level_outside_the_envelope_raises_before_any_library_call() -> None:
    """WP10.4: ``WaveformProgram.dc`` levels (builder ``dc_spot``) are checked with the whole program."""
    data = wave()
    data["channels"]["201"] = {"mode": "dc", "measure": "current", "current_range": "1ma"}
    data["sequences"].pop("201")
    data["dc"] = {"201": [0.5, 3.2]}
    wg, fake, _ = make()
    with pytest.raises(EnvelopeViolation) as caught:
        wg.load(WaveformProgram.model_validate(data))
    assert caught.value.reason == "level_exceeds_envelope" and caught.value.level == 3.2 and fake.calls == []
    data["dc"] = {"201": [0.5, -2.9]}
    wg.load(WaveformProgram.model_validate(data))
    assert "dc_force_voltage" not in fake.names()  # load configures; the kind forces each step through force_dc


def test_dc_levels_pass_the_guard() -> None:
    wg, fake, _ = make()
    wg.force_dc(TOP, -2.5)
    assert fake.calls == [("dc_force_voltage", (TOP, -2.5))] and wg.measure_dc(TOP) == 1.5e-4
    with pytest.raises(EnvelopeViolation) as caught:
        wg.force_dc(TOP, 3.01)
    assert caught.value.reason == "level_exceeds_envelope" and len(fake.calls) == 2


# -- run ---------------------------------------------------------------------------------------------------------------


def test_run_updates_connects_executes_polls_and_reads_in_chunks() -> None:
    statuses = [(api.STATUS_RUNNING, 0.0, 4.0), (api.STATUS_RUNNING, 1.0, 4.0), (api.STATUS_RUNNING, 3.5, 4.0),
                (api.STATUS_COMPLETED, 4.0, 4.0)]
    wg, fake, waits = make(statuses=statuses, values={TOP: 250_000, BOTTOM: 0})
    wg.load(program())
    fake.calls.clear()
    checks: list[str] = []
    polls: list[tuple[float, float]] = []
    block = wg.run(check_abort=lambda: checks.append("x"), on_poll=lambda e, t: polls.append((e, t)))
    names = fake.names()
    assert names[:4] == ["update", "connect", "connect", "execute"]
    assert names.count("status") == 4 and polls[-1] == (4.0, 4.0)
    assert waits == [POLL_S, POLL_S, 0.5] and max(waits) <= 1.0  # never more than 1 s between abort checks
    reads = [args for name, args in fake.calls if name == "measure_values"]
    assert reads == [(TOP, 0, READBACK_CHUNK), (TOP, READBACK_CHUNK, READBACK_CHUNK), (TOP, 2 * READBACK_CHUNK, 50_000)]
    assert len(checks) == 4 + 3  # before every poll and every chunk
    assert block.status == "completed" and block.polls == 4 and set(block.traces) == {TOP, BOTTOM}
    trace = block.traces[TOP]
    assert len(trace) == 250_000 and trace.quantity == "V" and trace.time_s[-1] == pytest.approx(249_999e-8)
    assert block.traces[BOTTOM].quantity == "I" and len(block.traces[BOTTOM]) == 0
    assert names[-1] == "warnings" and block.warnings == ()  # WP10.8: the summary read after the readback


def test_run_reports_the_library_warnings_and_never_fails_on_them() -> None:
    """WP10.8 (blueprint v2 1.2 "error/warning queues"): the warning summary read after the run comes back in the
    block; an unreadable summary is one warning line, never an error of a completed run."""
    wg, fake, _ = make()
    wg.load(program())
    fake.warning_lines = ["[severe] set_measure_event: event 'm' overwrites 1 overlapping measurement event(s)"]
    block = wg.run()
    assert block.status == "completed" and block.warnings == tuple(fake.warning_lines)
    fake.fail["warnings"] = WgfmuError(api.COMMUNICATION_ERROR, "warnings: hung", function="warnings")
    block = wg.run()
    assert block.status == "completed" and len(block.warnings) == 1
    assert block.warnings[0].startswith("warning summary not read: ") and "hung" in block.warnings[0]
    assert all(name != "set_warning_level" and name != "treat_warnings_as_errors" for name in fake.names())


def test_warning_facts_count_and_text() -> None:
    assert warning_facts([]) == {"wgfmu_warnings": 0}
    facts = warning_facts(["[normal] a", "[normal] a", "[severe] b"])
    assert facts == {"wgfmu_warnings": 3, "wgfmu_warning_text": "[normal] a | [severe] b"}
    long = warning_facts(["x" * 500])
    text = str(long["wgfmu_warning_text"])
    assert len(text) == WARNING_TEXT_CHARS and text.endswith("...")


def test_run_checks_every_route_before_its_first_call() -> None:
    env = ENVELOPE.model_copy(update={"routes": frozenset({RSU201})})
    wg, fake, _ = make(env)
    wg.load(program())
    fake.calls.clear()
    with pytest.raises(EnvelopeViolation):
        wg.run()
    assert fake.calls == []


@pytest.mark.parametrize("status", [api.STATUS_ABORTED, api.STATUS_ABORT_COMPLETED, api.STATUS_RUNNING_ILLEGAL,
                                    api.STATUS_IDLE])
def test_a_run_that_does_not_complete_fails(status: int) -> None:
    wg, fake, _ = make(statuses=[(status, 1e-6, 4e-5)])
    wg.load(program())
    with pytest.raises(WgfmuRunFailed) as caught:
        wg.run()
    assert caught.value.status == api.STATUS_NAMES[status] and "measure_values" not in fake.names()


def test_a_sequencer_that_never_ends_times_out() -> None:
    wg, _, waits = make(statuses=[(api.STATUS_RUNNING, 0.0, 2.0)])
    wg.load(program())
    with pytest.raises(WgfmuRunTimeout):
        wg.run()
    assert math.fsum(waits) == pytest.approx(2.0 * 1.2 + RUN_MARGIN_S + 1.0, abs=1.0)


def test_an_abort_request_stops_the_poll() -> None:
    class Cancelled(Exception):
        pass

    wg, fake, _ = make(statuses=[(api.STATUS_RUNNING, 0.0, 10.0)])
    wg.load(program())
    count = [0]

    def check() -> None:
        count[0] += 1
        if count[0] == 3:
            raise Cancelled

    with pytest.raises(Cancelled):
        wg.run(check_abort=check)
    assert fake.names().count("status") == 2


def test_run_without_a_program_refuses() -> None:
    wg, _, _ = make()
    with pytest.raises(DriverStateError):
        wg.run()


def test_incomplete_data_fails_the_read() -> None:
    wg, fake, _ = make()
    fake.values = {TOP: 10}
    fake.measure_value_size = lambda ch: (5, 10)  # type: ignore[method-assign]
    with pytest.raises(WgfmuRunFailed):
        wg.read(TOP)


# -- safe state --------------------------------------------------------------------------------------------------------


def test_the_safe_state_runs_every_step_and_hands_back_an_interrupt() -> None:
    wg, fake, _ = make()
    wg.load(program())
    wg.configure(TOP, ChannelSetup(mode="fastiv"))
    wg.configure(BOTTOM, ChannelSetup(mode="fastiv"))
    wg.connect(TOP)
    wg.connect(BOTTOM)
    fake.calls.clear()
    fake.fail["abort"] = WgfmuError(api.COMMUNICATION_ERROR, "abort: hung", function="abort")
    fake.fail["initialize"] = KeyboardInterrupt()
    report = wg.safe_state()
    assert fake.names() == ["abort", "initialize", "disconnect", "disconnect"]
    assert not report.ok and isinstance(report.deferred, KeyboardInterrupt)
    assert [name for name, ok, _ in report.steps if not ok] == ["abort", "initialize"]
    assert report.disconnected == (TOP, BOTTOM) and wg.connected == frozenset()
    assert wg.rsu_states() == {"RSU201.OUT": "open", "RSU202.OUT": "open"}
    assert "abort FAILED" in report.detail


def test_a_stuck_relay_keeps_the_channel_connected_and_unknown() -> None:
    wg, fake, _ = make()
    wg.configure(TOP, ChannelSetup(mode="fastiv"))
    wg.connect(TOP)
    fake.fail["disconnect"] = WgfmuError(api.UNIDENTIFIED_ERROR, "disconnect: relay", function="disconnect")
    report = wg.safe_state(channels=[BOTTOM])
    assert not report.ok and report.disconnected == (BOTTOM,) and wg.connected == {TOP}
    assert wg.rsu_states() == {"RSU202.OUT": "open"}  # 201 unknown: left out
    with pytest.raises(DriverStateError):
        wg.connect(TOP)  # initialize reset every channel: configure again first


def test_rsu_helpers() -> None:
    switches = lab_station().switches
    rsu = find_rsu(switches, TOP)
    assert rsu is not None and rsu[0].id == "RSU201" and rsu[1] == "OUT" and rsu_rest_path(rsu[0]) == "open"
    assert find_rsu(switches, 301) is None
    assert dict(rsu_targets(switches, [TOP, BOTTOM, 301])) == {TOP: "RSU201.OUT", BOTTOM: "RSU202.OUT"}
    absent = [s.model_copy(update={"present": False}) for s in switches]
    assert find_rsu(absent, TOP) is None


# -- OutputGuard.check_sequence ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("ch", "time_s", "points", "reason"), [
    (TOP, 1e-3 * 1.001, 10, "time_exceeds_envelope"),
    (TOP, 1e-4, 4_000_001, "points_exceed_envelope"),
    (TOP, math.inf, 1, "non_finite"),
    (TOP, 1e-4, 1.5, "non_finite"),
    (TOP, -1.0, 1, "invalid_waveform"),
    (3, 1e-4, 1, "no_waveform_envelope"),
    (302, 1e-4, 1, "channel_not_allowed"),
])
def test_check_sequence_refusals(ch: int, time_s: float, points: Any, reason: str) -> None:
    guard = OutputGuard(ENVELOPE)
    with pytest.raises(EnvelopeViolation) as caught:
        guard.check_sequence(ch, time_s=time_s, points=points)
    assert caught.value.reason == reason


def test_check_sequence_admits_the_envelope_itself_and_the_guard_lists_its_switches() -> None:
    guard = OutputGuard(ENVELOPE, switches=lab_station().switches)
    guard.check_sequence(TOP, time_s=1e-3, points=4_000_000)
    assert {s.id for s in guard.switches} >= {"RSU201", "RSU202", "SEL1"}
    assert OutputGuard(ENVELOPE).switches == ()
