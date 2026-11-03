"""Typed requests for fake C-flow composition, not hardware safety approval."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[float, Field(gt=0)]
Nonnegative = Annotated[float, Field(ge=0)]
Channel = Annotated[int, Field(gt=0)]
Count = Annotated[int, Field(ge=1, le=100_000)]


class FlowModel(BaseModel):
    """Reject unknown fields and non-finite values before composition."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class RunOptions(FlowModel):
    """Bound execution/read requests; fake completion is never physical completion."""

    timeout_s: Positive = 60.0
    collect: bool = True
    max_items: Count = 100
    format_hint: str = "FMT1"


class Integration(FlowModel):
    """SMU integration parameters accepted by the current atom."""

    adc: Literal["high_resolution", "high_speed"] = "high_resolution"
    integration_time: str = "medium"
    averaging_count: Count = 1
    post_adc_delay_s: Nonnegative = 0.0


class Ranging(FlowModel):
    """SMU measurement ranging; module limits still require station validation."""

    measure_function: Literal["current", "voltage"] = "current"
    range_mode: Literal["auto", "fixed", "limited_auto"] = "auto"
    range_value: Nonnegative = 0.0
    module_type: Literal["MPSMU", "HRSMU"] = "MPSMU"


class SmuSetup(FlowModel):
    """Shared SMU acquisition settings."""

    channel: Channel = 1
    integration: Integration = Field(default_factory=Integration)
    ranging: Ranging = Field(default_factory=Ranging)
    run: RunOptions = Field(default_factory=RunOptions)


class SmuSpot(SmuSetup):
    """One SMU source; compliance units depend on the selected source quantity."""

    source: Literal["voltage", "current"] = "voltage"
    level: float = 0.0
    compliance: Positive = Field(default=0.001, description="A for voltage source; V for current.")
    comp_polarity: Literal["auto", "positive", "negative"] = "auto"
    source_range_mode: str = "auto"
    irange: Nonnegative = 0.0


class SmuHighSpeed(SmuSpot):
    """High-speed spot reads use TI/TV/TIV without MM or XE."""

    integration: Integration = Field(default_factory=lambda: Integration(adc="high_speed"))
    measure_type: Literal["current", "voltage", "iv"] = "iv"
    timestamp: bool = True

    @model_validator(mode="after")
    def check_adc(self) -> "SmuHighSpeed":
        if self.integration.adc != "high_speed":
            raise ValueError("High-speed spot requires the high_speed ADC.")
        return self


class SweepTiming(FlowModel):
    """Timing forwarded to the SMU WT wrapper."""

    hold_s: Nonnegative = 0.0
    delay_s: Nonnegative = 0.0
    step_delay_s: Nonnegative = 0.0
    trigger_delay_s: Nonnegative = 0.0
    measure_delay_s: Nonnegative = 0.0


class SmuSweep(SmuSetup):
    """A primary staircase trajectory and its compliance."""

    source: Literal["voltage", "current"] = "voltage"
    start: float = 0.0
    stop: float = 1.0
    steps: Annotated[int, Field(ge=2, le=100_000)] = 11
    compliance: Positive = Field(default=0.001, description="A for voltage source; V for current.")
    sweep_type: Literal["linear", "log_positive", "log_negative"] = "linear"
    comp_polarity: Literal["auto", "positive", "negative"] = "auto"
    timing: SweepTiming = Field(default_factory=SweepTiming)
    abort_mode: str = "continue"
    post_output: str = "hold"

    @model_validator(mode="after")
    def check_log(self) -> "SmuSweep":
        if self.sweep_type == "log_positive" and min(self.start, self.stop) <= 0:
            raise ValueError("Positive logarithmic sweeps require positive endpoints.")
        if self.sweep_type == "log_negative" and max(self.start, self.stop) >= 0:
            raise ValueError("Negative logarithmic sweeps require negative endpoints.")
        return self


class SynchronousSweep(SmuSweep):
    """Secondary trajectory; its missing compliance is reported as an atom gap."""

    secondary_channel: Channel = 2
    secondary_source: Literal["voltage", "current"] = "voltage"
    secondary_start: float = 0.0
    secondary_stop: float = 1.0

    @model_validator(mode="after")
    def distinct_channels(self) -> "SynchronousSweep":
        if self.channel == self.secondary_channel:
            raise ValueError("Primary and secondary channels must differ.")
        return self


class MultiSweep(SmuSweep):
    """Multi-channel WNX composition with explicit participating channels."""

    channels: list[Channel] = Field(default_factory=lambda: [1, 2], min_length=2, max_length=10)

    @model_validator(mode="after")
    def check_channels(self) -> "MultiSweep":
        if len(set(self.channels)) != len(self.channels) or self.channel not in self.channels:
            raise ValueError("Channels must be unique and include the primary channel.")
        return self


class Qscv(SmuSetup):
    """SMU charge-integration sweep; correction/leakage are external prerequisites."""

    start_v: float = 0.0
    stop_v: float = 1.0
    steps: Annotated[int, Field(ge=2, le=100_000)] = 11
    integration_leak_s: Nonnegative = 0.0
    measurement_volt_v: Positive = 0.1


class PulseTiming(FlowModel):
    """Basic pulse geometry, independent of module-specific timing validation."""

    delay_s: Nonnegative = 0.0
    width_s: Positive = 1e-6
    period_s: Positive = 1e-3

    @model_validator(mode="after")
    def fits_period(self) -> "PulseTiming":
        if self.delay_s + self.width_s > self.period_s:
            raise ValueError("Pulse delay plus width exceeds the period.")
        return self


class SmuPulse(SmuSetup):
    """Parameterized single-channel pulse."""

    source: Literal["voltage", "current"] = "voltage"
    base: float = 0.0
    pulse: float = 1.0
    compliance: Positive = Field(default=0.001, description="A for voltage source; V for current.")
    timing: PulseTiming = Field(default_factory=PulseTiming)


class SmuPulseSweep(SmuSetup):
    """Current PWV/PWI surface; omitted compliance/base are explicit gaps."""

    source: Literal["voltage", "current"] = "voltage"
    start: float = 0.0
    stop: float = 1.0
    steps: Annotated[int, Field(ge=2, le=100_000)] = 11
    timing: PulseTiming = Field(default_factory=PulseTiming)


class PulsedBias(SmuPulseSweep):
    """Staircase sweep with a separate pulsed bias channel."""

    bias_channel: Channel = 2
    bias_base: float = 0.0
    bias_pulse: float = 1.0

    @model_validator(mode="after")
    def distinct_channels(self) -> "PulsedBias":
        if self.channel == self.bias_channel:
            raise ValueError("Sweep and pulsed-bias channels must differ.")
        return self


class MultiPulse(FlowModel):
    """MCP configuration surface; per-channel sourcing is not yet represented."""

    channels: list[Channel] = Field(default_factory=lambda: [1, 2], min_length=2, max_length=10)
    mode: Literal["pulsed_spot", "pulsed_sweep"] = "pulsed_spot"
    pulse_width_s: Positive = 1e-6
    run: RunOptions = Field(default_factory=RunOptions)

    @model_validator(mode="after")
    def unique_channels(self) -> "MultiPulse":
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("Channels must be unique.")
        return self


class QuasiPulse(SmuSetup):
    """Available BD configuration fields."""

    base_v: float = 0.0
    peak_v: float = 1.0
    width_s: Positive = 1e-6


class SmuSampling(SmuSetup):
    """Sampling timing; MI/MV source details remain an atom contract gap."""

    channels: list[Channel] = Field(default_factory=lambda: [1], min_length=1, max_length=10)
    interval_s: Positive = 1e-3
    samples: Count = 100
    mode: Literal["linear", "log"] = "linear"
    hold_base_s: Nonnegative = 0.0
    post_output: Literal["base", "bias", "start"] = "base"

    @model_validator(mode="after")
    def check_channels(self) -> "SmuSampling":
        if len(set(self.channels)) != len(self.channels) or self.channel not in self.channels:
            raise ValueError("Channels must be unique and include the source channel.")
        return self


class SpguSampling(SmuSampling):
    """SMU sampling with SPGU pulse bias on the same FLEX transport."""

    spgu_channel: Channel = 3
    base_v: float = 0.0
    pulse_v: float = 1.0
    width_s: Positive = 1e-6

    @model_validator(mode="after")
    def distinct_spgu(self) -> "SpguSampling":
        if self.spgu_channel in self.channels:
            raise ValueError("SPGU channel must differ from SMU channels.")
        return self


class SignalMonitor(SmuSetup):
    """Only the settings represented by the DSMPL configuration atom."""

    channels: list[Channel] = Field(default_factory=lambda: [1], min_length=1, max_length=10)
    interval_s: Positive = 1e-6
    samples: Count = 100

    @model_validator(mode="after")
    def check_channels(self) -> "SignalMonitor":
        if len(set(self.channels)) != len(self.channels) or self.channel not in self.channels:
            raise ValueError("Channels must be unique and include the primary channel.")
        return self


class Search(SmuSetup):
    """Current LS/BS surface; full search source/sense contract is still absent."""

    search_type: Literal["linear", "binary"] = "linear"
    target: float = 0.0
    limit: Positive = 1.0


class CmuSetup(FlowModel):
    """MFCMU setup; these fields do not certify correction or leakage readiness."""

    channel: Channel = 7
    model: str = "Cp-G"
    frequency_hz: Positive = 1e6
    ac_level_v: Positive = 0.03
    dc_bias_v: float = 0.0
    range_mode: str = "auto"
    range_value: Nonnegative = 0.0
    integration_time: str = "medium"
    monitor: bool = True
    run: RunOptions = Field(default_factory=RunOptions)


class CmuSweep(CmuSetup):
    """CMU sweep endpoints are Hz for cf and V for cv/ac_level."""

    start: float
    stop: float
    steps: Annotated[int, Field(ge=2, le=100_000)] = 21
    hold_s: Nonnegative = 0.0
    delay_s: Nonnegative = 0.0
    step_delay_s: Nonnegative = 0.0
    measure_delay_s: Nonnegative = 0.0
    abort_mode: str = "continue"


class CmuPulse(CmuSetup):
    """CMU pulsed spot or pulsed sweep geometry."""

    base_v: float = 0.0
    bias_v: float = 1.0
    width_s: Positive = 1e-6
    period_s: Positive = 1e-3

    @model_validator(mode="after")
    def fits_period(self) -> "CmuPulse":
        if self.width_s > self.period_s:
            raise ValueError("Pulse width exceeds period.")
        return self


class CmuPulseSweep(CmuSetup):
    """Pulsed CMU DC bias trajectory."""

    start_v: float = -1.0
    stop_v: float = 1.0
    steps: Annotated[int, Field(ge=2, le=100_000)] = 21
    width_s: Positive = 1e-6
    period_s: Positive = 1e-3

    @model_validator(mode="after")
    def fits_period(self) -> "CmuPulseSweep":
        if self.width_s > self.period_s:
            raise ValueError("Pulse width exceeds period.")
        return self


class CmuSampling(CmuSetup):
    """CMU capacitance-time acquisition."""

    interval_s: Positive = 1e-3
    samples: Count = 100


class WgfmuDc(FlowModel):
    """DC force/measure followed by optional averaged readback."""

    channel_id: Channel = 501
    voltage_v: float = 0.0
    force_range: str = "auto"
    measure_range: str = "10mA"
    averaged: bool = False
    averaging_count: Count = 16
    points: Annotated[int, Field(ge=1, le=65535)] = 16
    interval_ticks: Annotated[int, Field(ge=1, le=65535)] = 1


class Vector(FlowModel):
    """One incremental WGFMU vector."""

    delta_time_s: Annotated[float, Field(ge=1e-8, le=10995.11627775)]
    voltage_v: float


class MeasureEvent(FlowModel):
    """One measurement event within a WGFMU pattern."""

    event: str = Field(default="meas", min_length=1)
    time_s: Nonnegative = 0.0
    points: Count = 1
    interval_s: Annotated[float, Field(ge=1e-8, le=1.34217728)] = 1e-7
    average_s: Annotated[float, Field(ge=0, le=0.020971512)] = 0.0
    rdata: Literal["averaged", "raw"] = "averaged"

    @model_validator(mode="after")
    def average_fits(self) -> "MeasureEvent":
        if self.average_s > self.interval_s:
            raise ValueError("Averaging duration exceeds the sample interval.")
        return self


class WaveformChannel(FlowModel):
    """One bounded waveform/measurement sequence per declared WGFMU channel."""

    channel_id: Channel = 501
    pattern: str = Field(default="pulse", min_length=1)
    initial_voltage_v: float = 0.0
    force_range: str = "auto"
    measure_range: str = "10mA"
    measure_mode: Literal["current", "voltage"] = "current"
    voltage_range: Literal["5V", "10V"] = "10V"
    vectors: list[Vector] = Field(min_length=1, max_length=2048)
    events: list[MeasureEvent] = Field(min_length=1, max_length=128)
    repeat_count: Count = 1

    @model_validator(mode="after")
    def events_fit(self) -> "WaveformChannel":
        duration = sum(v.delta_time_s for v in self.vectors)
        if len({e.event for e in self.events}) != len(self.events):
            raise ValueError("Measurement event names must be unique per pattern.")
        for e in self.events:
            end = e.time_s + (e.points - 1) * e.interval_s + (e.average_s or 1e-8)
            if end > duration + 1e-15:
                raise ValueError("Measurement event extends beyond the pattern.")
        return self


class WgfmuWaveform(FlowModel):
    """Define all channels first, then update and execute once."""

    channels: list[WaveformChannel] = Field(min_length=1, max_length=10)
    run: RunOptions = Field(default_factory=RunOptions)

    @model_validator(mode="after")
    def unique_channels_patterns(self) -> "WgfmuWaveform":
        if len({c.channel_id for c in self.channels}) != len(self.channels):
            raise ValueError("WGFMU channels must be unique.")
        if len({c.pattern for c in self.channels}) != len(self.channels):
            raise ValueError("WGFMU pattern names must be unique across channels.")
        return self


class SpguPulse(FlowModel):
    """Bounded SPGU pulse train; no implicit free-run mode."""

    channel: Channel = 1
    load_ohm: Positive = 50.0
    pulse_mode: Literal["two_level", "three_level"] = "two_level"
    source_number: Annotated[int, Field(ge=1, le=3)] = 1
    timing: PulseTiming = Field(default_factory=PulseTiming)
    leading_s: Positive = 2e-8
    trailing_s: Positive = 2e-8
    base_v: float = 0.0
    peak_v: float = 1.0
    peak2_v: float = 0.0
    count: Count = 1
    timeout_s: Positive = 60.0

    @model_validator(mode="after")
    def source_fits_mode(self) -> "SpguPulse":
        if self.pulse_mode == "two_level" and self.source_number == 3:
            raise ValueError("Source 3 requires three-level mode.")
        return self


class SpguWaveform(FlowModel):
    """Bounded SPGU ALWG pattern and sequence."""

    channel: Channel = 1
    load_ohm: Positive = 50.0
    pattern: str = Field(default="alwg", min_length=1)
    initial_voltage_v: float = 0.0
    period_s: Positive = 1e-6
    levels_v: list[float] = Field(min_length=1, max_length=2048)
    repeat_count: Count = 1
    loop_start: Annotated[int, Field(ge=0)] = 0
    loop_count: Count = 1
    count: Count = 1
    timeout_s: Positive = 60.0


class RemoteRun(FlowModel):
    """Execute already selected software context; selection/fetch stay A-class."""

    timeout_s: Positive = 300.0


class RemoteRepeat(RemoteRun):
    """Bound the remote repeat count without a Python execution loop."""

    repeat_count: Count = 1


class RemoteSequence(RemoteRun):
    """Name of an existing Quick Test sequence."""

    sequence_name: str = Field(default="quick_test", min_length=1)
