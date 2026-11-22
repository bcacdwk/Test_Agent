"""SMU pulsed driver operations (``driver/ops/pulsed.py``; blueprint v2 2.5, WP7.3): the ``PulsedSetup`` model accepts
exactly the manual's mode shapes, writes the command sequences of the PG examples, and every pulse and staircase
source passes ``OutputGuard.check``/``check_pulse`` before anything is written (no guard, a level, a compliance, a
width, a duty or a pulse count outside the compiled envelope: nothing is sent)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.driver.b1500 import B1500Driver, PulsedSetup, PulseSource, SweepSource
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope, PulseEnvelope
from tests.unit.driver_helpers import SpyTransport

GATE, DRAIN = 4, 3
PULSE = PulseEnvelope(max_abs_v_dut=3.0, min_width_s=1e-3, max_width_s=1e-3, max_duty=0.1, max_count=61,
                      max_on_time_s=0.061, max_short_circuit_a=0.0)
ENVELOPE = CompiledEnvelope(channels={
    GATE: ChannelEnvelope(role="gate", max_abs_v=3.0, max_abs_i=1e-4, function="pulse_v", pulse=PULSE),
    DRAIN: ChannelEnvelope(role="drain", max_abs_v=3.0, max_abs_i=1e-3, function="bias_v"),
})


def gate_sweep(**changes: object) -> PulseSource:
    return PulseSource(channel=GATE, base=0.0, start=0.0, stop=3.0, comp=1e-4, width=1e-3).model_copy(update=changes)


def mm4(**changes: object) -> PulsedSetup:
    data: dict[str, object] = {"mode": 4, "measure": (DRAIN,), "operation": {DRAIN: 1}, "period": 0.02,
                               "meas_time": 2e-4, "pulses": (gate_sweep(),), "points": 61}
    data.update(changes)
    return PulsedSetup.model_validate(data)


def driver(guard: bool = True) -> tuple[B1500Driver, SpyTransport]:
    spy = SpyTransport()
    return B1500Driver(spy, OutputGuard(ENVELOPE) if guard else None), spy


def test_mm4_writes_the_pulsed_sweep_sequence() -> None:
    drv, spy = driver()
    drv.pulsed_setup(mm4())
    assert spy.sent == ["AIT 2,3,0.0002", "MM 4,3", "CMM 3,1", "PT 0,0.001,0.02", "PWV 4,1,0,0,0,3,61,0.0001",
                        "WM 2,1"]
    assert mm4().format_mode == 1 and mm4().returned_source == GATE and mm4().pulses_per_trigger == 61


def test_mm5_mm3_mm27_mm28_sequences() -> None:
    bias = PulseSource(channel=GATE, base=0.0, peak=2.0, comp=1e-4, width=1e-3)
    stair = SweepSource(channel=DRAIN, source="V", start=0.0, stop=3.0, comp=1e-3)
    mm5 = PulsedSetup(mode=5, measure=(DRAIN,), operation={DRAIN: 1}, period=0.02, meas_time=2e-4, pulses=(bias,),
                      staircase=stair, points=31)
    assert mm5.commands() == ["AIT 2,3,0.0002", "MM 5,3", "CMM 3,1", "PT 0,0.001,0.02", "WV 3,1,0,0,3,31,0.001",
                              "PV 4,0,0,2,0.0001", "WM 2,1"]
    assert mm5.returned_source == DRAIN and mm5.pulses_per_trigger == 31
    mm3 = PulsedSetup(mode=3, measure=(GATE,), operation={GATE: 1}, period=0.02, meas_time=2e-4, pulses=(bias,))
    assert mm3.commands() == ["AIT 2,3,0.0002", "MM 3,4", "CMM 4,1", "PT 0,0.001,0.02", "PV 4,0,0,2,0.0001"]
    assert mm3.format_mode == 0 and mm3.pulses_per_trigger == 1
    drain_pulse = PulseSource(channel=DRAIN, base=0.0, peak=1.0, comp=1e-3, width=1e-3)
    mm27 = PulsedSetup(mode=27, measure=(DRAIN, GATE), operation={DRAIN: 1, GATE: 1}, period=0.02, meas_time=2e-4,
                       pulses=(bias, drain_pulse), average=4)
    assert mm27.commands() == ["AIT 2,3,0.0002", "MCPT 0,0.02,0,4", "MCPNT 4,0,0.001", "MCPNT 3,0,0.001",
                               "MCPNX 1,4,1,0,0,2,0.0001", "MCPNX 2,3,1,0,0,1,0.001", "MM 27,3,4", "CMM 3,1",
                               "CMM 4,1"]
    assert mm27.pulses_per_trigger == 4
    mm28 = PulsedSetup(mode=28, measure=(DRAIN,), operation={DRAIN: 1}, period=0.02, meas_time=2e-4,
                       pulses=(gate_sweep(),), wnx=(SweepSource(channel=5, source="V", start=0, stop=1, comp=1e-3),),
                       points=11)
    assert mm28.commands()[-5:] == ["MCPWNX 1,4,1,0,0,0,3,0.0001", "WNX 2,5,1,0,0,1,0.001", "MM 28,3", "CMM 3,1",
                                    "WM 2,1"]
    assert mm28.format_mode == 1 and mm28.source_number(5) == 2


@pytest.mark.parametrize(("changes", "match"), [
    ({"measure": (DRAIN, GATE)}, "one pulse source and one measurement channel"),
    ({"sweep": "log", "pulses": (gate_sweep(start=0.1),)}, "linearly only"),
    ({"pulses": (PulseSource(channel=GATE, peak=1.0, comp=1e-4, width=1e-3),)}, "pulsed sweep"),
    ({"meas_time": 2e-3}, "inside the pulse width"),
    ({"average": 2}, "mode 27/28"),
    ({"staircase": SweepSource(channel=5, source="V", start=0, stop=1, comp=1e-3)}, "mode 5"),
    ({"sync": SweepSource(channel=5, source="I", start=0, stop=1e-6, comp=1)}, "output mode"),
])
def test_setup_refuses_shapes_the_manual_does_not_have(changes: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        mm4(**changes)


def test_pulse_source_shapes() -> None:
    with pytest.raises(ValidationError, match="either peak"):
        PulseSource(channel=GATE, comp=1e-4, width=1e-3)
    with pytest.raises(ValidationError, match="one polarity"):
        PulseSource(channel=GATE, source="I", base=-1e-6, peak=1e-6, comp=1.0, width=1e-3)
    bias = PulseSource(channel=GATE, base=0.0, peak=-2.0, comp=1e-4, width=1e-3)
    assert bias.extreme == -2.0 and bias.with_peak(1.0).peak == 1.0
    with pytest.raises(ValueError):
        gate_sweep().with_peak(1.0)


def test_pulsed_sources_refuse_without_a_guard() -> None:
    drv, spy = driver(guard=False)
    with pytest.raises(EnvelopeViolation) as info:
        drv.pulsed_setup(mm4())
    assert info.value.reason == "no_guard" and spy.sent == []


@pytest.mark.parametrize(("setup", "reason"), [
    (mm4(pulses=(gate_sweep(stop=3.5),)), "level_exceeds_envelope"),
    (mm4(pulses=(gate_sweep(comp=1e-3),)), "compliance_exceeds_envelope"),
    (mm4(pulses=(gate_sweep(width=2e-3),), meas_time=2e-4), "pulse_width_outside_envelope"),
    (mm4(period=0.005), "duty_exceeds_envelope"),
    (mm4(points=62), "count_exceeds_envelope"),
    (mm4(pulses=(gate_sweep(channel=5),)), "channel_not_allowed"),
])
def test_every_pulse_parameter_passes_the_guard_before_any_write(setup: PulsedSetup, reason: str) -> None:
    drv, spy = driver()
    with pytest.raises(EnvelopeViolation) as info:
        drv.pulsed_setup(setup)
    assert info.value.reason == reason and spy.sent == []


def test_staircase_sources_and_updates_are_guarded() -> None:
    drv, spy = driver()
    bias = PulseSource(channel=GATE, base=0.0, peak=2.0, comp=1e-4, width=1e-3)
    too_high = SweepSource(channel=DRAIN, source="V", start=0.0, stop=3.5, comp=1e-3)
    mm5 = PulsedSetup(mode=5, measure=(DRAIN,), operation={DRAIN: 1}, period=0.02, meas_time=2e-4, pulses=(bias,),
                      staircase=too_high, points=31)
    with pytest.raises(EnvelopeViolation) as info:
        drv.pulsed_setup(mm5)
    assert info.value.reason == "level_exceeds_envelope" and spy.sent == []
    ok = mm5.model_copy(update={"staircase": too_high.model_copy(update={"stop": 3.0})})
    drv.pulsed_setup(ok)
    spy.sent.clear()
    drv.pulsed_update(ok.model_copy(update={"pulses": (bias.with_peak(3.0),)}))
    assert spy.sent == ["PV 4,0,0,3,0.0001"]
    with pytest.raises(EnvelopeViolation):
        drv.pulsed_update(ok.model_copy(update={"pulses": (bias.with_peak(3.1),)}))
    assert spy.sent == ["PV 4,0,0,3,0.0001"]
