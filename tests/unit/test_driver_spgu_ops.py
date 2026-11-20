"""``SpguOps`` (``driver/ops/spgu.py``, WP9.1): the exact setup writes, the guard before every source-like write
(configure, apply, start, load change, load measurement), nothing written on a refusal, ``SPP`` never gated, the
``SPST?`` polling with host waits, and the binary-block and host-wait links."""

from __future__ import annotations

import pytest

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.errors import DriverStateError, FlexParseError, SpguStillActive
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops.spgu import SpguOps
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.sources import pulse_envelope
from b1500_test_agent.models.spgu import AlwgChannel, AlwgPattern, AlwgProgram, AlwgVector, SpguProgram
from tests.unit.driver_helpers import SpyTransport
from tests.unit.test_models_spgu import lwp_config_b, two_level

pytestmark = pytest.mark.spgu


class BlockSpy(SpyTransport):
    """A spy link with binary blocks and host waits."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.blocks: list[tuple[str, bytes]] = []
        self.waits: list[float] = []

    def write_block(self, cmd: str, data: bytes) -> None:
        self.sent.append(cmd)
        self.blocks.append((cmd, data))

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)


def envelope_for(program: SpguProgram, *, max_abs_v: float | None = None) -> CompiledEnvelope:
    channels = {}
    for ch, trains in program.trains().items():
        pulse = pulse_envelope(trains, source_ohm=50.0)
        channels[ch] = ChannelEnvelope(role=f"pgu{ch}", max_abs_v=max_abs_v or pulse.max_abs_v_dut, max_abs_i=None,
                                       function="pgu", pulse=pulse)
    return CompiledEnvelope(channels=channels)


def driver_for(program: SpguProgram, spy: SpyTransport | None = None, **kwargs: float) -> tuple[B1500Driver,
                                                                                               SpyTransport]:
    spy = spy if spy is not None else BlockSpy()
    return B1500Driver(spy, OutputGuard(envelope_for(program, **kwargs))), spy


LWP_B_SETUP = [
    "SIM 0", "SPRM 1,2", "SPPER 1E-05",
    "SER 101,1000000", "SPM 101,3", "SPT 101,1,0,2E-06,1E-07,1E-07", "SPV 101,1,0,3",
    "SPT 101,2,3E-06,2E-06,1E-07,1E-07", "SPV 101,2,0,-3", "ODSW 101,0", "STGP 101,0",
    "SER 102,1000000", "SPM 102,3", "SPT 102,1,0,2E-06,1E-07,1E-07", "SPV 102,1,0,3",
    "SPT 102,2,3E-06,2E-06,1E-07,1E-07", "SPV 102,2,0,-3", "ODSW 102,0", "STGP 102,0",
]  # fmt: skip
"""The kernel's setup writes for lwp ``test_SPGU.m`` configuration B (compared with the lab's sequence in
``tests/integration/test_lab_spgu_sequence.py``)."""


def test_configure_writes_the_setup_in_order() -> None:
    program = lwp_config_b()
    driver, spy = driver_for(program)
    driver.configure_pulse(program)
    assert spy.sent == LWP_B_SETUP
    assert SpguOps.spgu_preview(program) == [*LWP_B_SETUP, "SPUPD 101,102", "SRP"]
    driver.apply_pulse_setup()
    driver.start_pulses()
    assert spy.sent[-2:] == ["SPUPD 101,102", "SRP"]
    assert driver.spgu_program == program


def test_a_program_outside_the_envelope_writes_nothing() -> None:
    allowed = two_level(peak=2.0)
    driver, spy = driver_for(allowed)
    with pytest.raises(EnvelopeViolation) as caught:
        driver.configure_pulse(two_level(peak=4.0))
    assert caught.value.reason == "pulse_level_exceeds_envelope" and spy.sent == []
    with pytest.raises(EnvelopeViolation) as caught:
        driver.configure_pulse(two_level(peak=2.0, count=2000))
    assert caught.value.reason == "count_exceeds_envelope" and spy.sent == []
    with pytest.raises(EnvelopeViolation) as caught:  # the same set level at SER 50 doubles at an open load
        driver.configure_pulse(two_level(peak=2.0, load=50.0))
    assert caught.value.reason == "pulse_level_exceeds_envelope" and caught.value.level == pytest.approx(4.0)
    assert spy.sent == []


def test_no_guard_and_unknown_channels_are_refused() -> None:
    program = two_level()
    spy = BlockSpy()
    with pytest.raises(EnvelopeViolation) as caught:
        B1500Driver(spy).configure_pulse(program)
    assert caught.value.reason == "no_guard" and spy.sent == []
    other = two_level().model_copy(update={"channels": {102: two_level().channels[101]}})
    driver, spy = driver_for(program)
    with pytest.raises(EnvelopeViolation) as caught:
        driver.configure_pulse(other)
    assert caught.value.reason == "channel_not_allowed" and spy.sent == []


def test_syntax_errors_are_raised_before_anything_is_written() -> None:
    program = two_level(load=2e6)  # SER above 1 MOhm: the builder refuses
    driver, spy = driver_for(program)
    with pytest.raises(ValueError, match="SER load"):
        driver.configure_pulse(program)
    assert spy.sent == []


def test_apply_start_and_measure_need_this_drivers_setup() -> None:
    program = two_level()
    driver, spy = driver_for(program)
    with pytest.raises(DriverStateError, match="no SPGU program"):
        driver.apply_pulse_setup()
    with pytest.raises(DriverStateError, match="no SPGU program"):
        driver.start_pulses()
    driver.configure_pulse(program)
    with pytest.raises(DriverStateError, match="no SPGU channel was set up"):
        driver.start_pulses()
    with pytest.raises(DriverStateError, match="not configured"):
        driver.apply_pulse_setup([102])
    count = len(spy.sent)
    with pytest.raises(DriverStateError, match="set up"):
        driver.measure_pulse_load(101, delay_s=1e-7, interval_s=5e-6)
    assert len(spy.sent) == count


def test_start_rechecks_the_guard() -> None:
    program = two_level()
    driver, spy = driver_for(program)
    driver.configure_pulse(program)
    driver.apply_pulse_setup()
    driver.guard = OutputGuard(envelope_for(two_level(peak=1.0)))  # e.g. a guard of another plan
    with pytest.raises(EnvelopeViolation):
        driver.start_pulses()
    assert flex.SRP not in spy.sent


def test_a_smaller_load_is_checked_before_it_is_written() -> None:
    program = two_level(peak=3.0)
    driver, spy = driver_for(two_level(peak=3.0, load=1e5))  # the envelope admits SER down to 100 kOhm
    driver.configure_pulse(program)
    with pytest.raises(EnvelopeViolation) as caught:  # 3 V x (50 + 50) / 50 = 6 V > 4 V
        driver.set_pulse_load(101, 50.0)
    assert caught.value.reason == "pulse_level_exceeds_envelope" and "SER 101,50" not in spy.sent
    driver.set_pulse_load(101, 1e5)
    assert spy.sent[-1] == "SER 101,100000"
    assert driver.spgu_program is not None and driver.spgu_program.channels[101].load_ohm == 1e5
    with pytest.raises(DriverStateError):
        driver.set_pulse_load(102, 1e6)


def test_measure_load_sends_mode_0_and_parses_the_answer() -> None:
    program = two_level()
    spy = BlockSpy(answers={"CORRSER? 101,0,1E-07,5E-06,2": "1.000000E+06,4.000200E+00"})
    driver, _ = driver_for(program, spy)
    driver.configure_pulse(program)
    driver.apply_pulse_setup()
    result = driver.measure_pulse_load(101, delay_s=1e-7, interval_s=5e-6, count=2)
    assert result.load_ohm == 1e6 and result.voltage_v == pytest.approx(4.0002)
    bad = BlockSpy(answers={"CORRSER? 101,0,1E-07,5E-06,1": "garbage"})
    driver, _ = driver_for(program, bad)
    driver.configure_pulse(program)
    driver.apply_pulse_setup()
    with pytest.raises(FlexParseError):
        driver.measure_pulse_load(101, delay_s=1e-7, interval_s=5e-6)


def test_stop_is_never_gated() -> None:
    spy = BlockSpy()
    B1500Driver(spy).stop_pulses()
    assert spy.sent == ["SPP"]


def test_wait_polls_with_host_waits_and_checks() -> None:
    spy = BlockSpy(answers={"SPST?": ["1", "1", "1", "0"]})
    checks: list[int] = []
    waited = B1500Driver(spy).wait_pulses_stopped(timeout_s=1.0, poll_s=0.25, check=lambda: checks.append(1))
    assert waited == pytest.approx(0.75) and spy.waits == [0.25, 0.25, 0.25] and len(checks) == 3
    assert spy.sent == ["SPST?"] * 4


def test_wait_raises_when_the_output_does_not_stop() -> None:
    spy = BlockSpy(answers={"SPST?": "1"})
    with pytest.raises(SpguStillActive) as caught:
        B1500Driver(spy).wait_pulses_stopped(timeout_s=0.3, poll_s=0.2)
    assert caught.value.waited_s == pytest.approx(0.3) and spy.waits == [0.2, pytest.approx(0.1)]
    with pytest.raises(ValueError):
        B1500Driver(spy).wait_pulses_stopped(timeout_s=1.0, poll_s=0.0)


def test_check_can_abort_the_wait() -> None:
    spy = BlockSpy(answers={"SPST?": "1"})

    def cancel() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        B1500Driver(spy).wait_pulses_stopped(timeout_s=10.0, check=cancel)
    assert spy.waits == [0.1]


def alwg_program() -> AlwgProgram:
    pattern = AlwgPattern(initial_v=0.0, vectors=[AlwgVector(dt_s=1e-6, v=2.0), AlwgVector(dt_s=1e-6, v=0.0),
                                                  AlwgVector(dt_s=2e-6, v=0.0, switch_closed=False)])
    return AlwgProgram(sequence=[(1, 5)], count=10,
                       channels={101: AlwgChannel(load_ohm=1e6, patterns=[pattern], pulse_switch=True, trigger=2)})


def test_alwg_setup_sends_the_blocks_after_their_headers() -> None:
    program = alwg_program()
    driver, spy = driver_for(program)
    driver.configure_alwg(program)
    header, block = flex.alw(101, program.channels[101].patterns)
    seq_header, seq_block = flex.als(program.sequence)
    assert spy.sent == ["SIM 1", "SPRM 1,10", "SER 101,1000000", "ODSW 101,1,0", "STGP 101,2", header, seq_header]
    assert spy.blocks == [(header, block), (seq_header, seq_block)]  # type: ignore[attr-defined]
    assert SpguOps.spgu_preview(program)[-4:] == [header, seq_header, "SPUPD 101", "SRP"]


def test_a_link_without_blocks_refuses_the_alwg_setup() -> None:
    program = alwg_program()
    driver, spy = driver_for(program, SpyTransport())
    with pytest.raises(DriverStateError, match="binary data block"):
        driver.configure_alwg(program)
    assert all(not cmd.startswith("ALW") for cmd in spy.sent)


def test_host_wait_without_a_link_clock_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("b1500_test_agent.driver.ops.core.time.sleep", slept.append)
    B1500Driver(SpyTransport()).host_wait(0.05)
    assert slept == [0.05]
    with pytest.raises(ValueError):
        B1500Driver(SpyTransport()).host_wait(-1.0)


def test_modules_keeps_the_last_inventory() -> None:
    spy = SpyTransport(answers={"UNT?": "B1525A,0;" + ";".join(["0,0"] * 9)})
    driver = B1500Driver(spy)
    assert driver.last_inventory is None
    inventory = driver.modules()
    assert driver.last_inventory is inventory and inventory.model_in_slot(1) == "B1525A"
