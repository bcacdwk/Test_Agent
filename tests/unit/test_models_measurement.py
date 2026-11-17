"""Salvaged SMU setup models: FLEX parameter domains from the Programming Guide Ed. 15 (see module docstring)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.measurement import (
    CHANNEL_NUMBERS,
    BiasChannel,
    Integration,
    Ranging,
    SweepTiming,
)


def test_channel_numbers_match_table_4_1() -> None:
    assert len(CHANNEL_NUMBERS) == 30
    assert {1, 10, 101, 102, 1001, 1002} <= CHANNEL_NUMBERS
    assert CHANNEL_NUMBERS.isdisjoint({0, 11, 100, 103, 1003})


@pytest.mark.parametrize("channel", [1, 7, 10, 101, 302, 1002])
def test_bias_channel_accepts_table_4_1_channels(channel: int) -> None:
    assert BiasChannel(channel=channel, level=0.1, compliance=1e-3).channel == channel


@pytest.mark.parametrize("channel", [0, -1, 11, 100, 103, 1003])
def test_bias_channel_rejects_other_channels(channel: int) -> None:
    with pytest.raises(ValidationError):
        BiasChannel(channel=channel, level=0.1, compliance=1e-3)


def test_bias_channel_never_defaults_level_or_compliance() -> None:
    with pytest.raises(ValidationError):
        BiasChannel(channel=1, level=0.1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BiasChannel(channel=1, compliance=1e-3)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("kwargs", "ok"),
    [
        ({"compliance": 0.0}, False),  # 0 A/V compliance is not allowed (DV/DI)
        ({"compliance": -1e-3}, False),  # auto polarity takes the magnitude only
        ({"compliance": -1e-3, "compliance_polarity": "manual"}, True),
        ({"compliance": 1e-3, "output_range": -1.0}, False),
        ({"compliance": 1e-3, "level": float("nan")}, False),
        ({"compliance": 1e-3, "level": -2.0, "source": "I"}, True),
    ],
)
def test_bias_channel_compliance_rules(kwargs: dict[str, object], ok: bool) -> None:
    data = {"channel": 2, "level": 1.0, **kwargs}
    if ok:
        BiasChannel.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            BiasChannel.model_validate(data)


def test_integration_defaults_are_instrument_initial_settings() -> None:
    assert Integration().model_dump() == {"adc": "high_speed", "mode": "auto", "n": 1}


@pytest.mark.parametrize(
    ("adc", "mode", "n_max"),
    [
        ("high_speed", "auto", 1023),
        ("high_speed", "manual", 1023),
        ("high_speed", "plc", 100),
        ("high_resolution", "auto", 127),
        ("high_resolution", "manual", 127),
        ("high_resolution", "plc", 100),
    ],
)
def test_integration_n_bounds_follow_table_4_21(adc: str, mode: str, n_max: int) -> None:
    assert Integration(adc=adc, mode=mode, n=n_max).n == n_max  # type: ignore[arg-type]
    for bad in (0, n_max + 1):
        with pytest.raises(ValidationError):
            Integration(adc=adc, mode=mode, n=bad)  # type: ignore[arg-type]


def test_integration_rejects_unmodelled_settings() -> None:
    with pytest.raises(ValidationError):
        Integration(adc="pulsed")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Integration(mode="time")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "ok"),
    [
        ({}, True),
        ({"mode": "fixed", "range_value": 1e-9}, True),
        ({"mode": "limited_auto", "range_value": 1e-6}, True),
        ({"quantity": "V", "mode": "fixed", "range_value": 2.0}, True),
        ({"mode": "auto", "range_value": 1e-9}, False),
        ({"mode": "fixed"}, False),
        ({"mode": "limited_auto", "range_value": 0.0}, False),
        ({"quantity": "R"}, False),
    ],
)
def test_ranging_value_matches_mode(kwargs: dict[str, object], ok: bool) -> None:
    if ok:
        Ranging.model_validate(kwargs)
    else:
        with pytest.raises(ValidationError):
            Ranging.model_validate(kwargs)


def test_sweep_timing_follows_wt_domains() -> None:
    assert SweepTiming().model_dump() == dict.fromkeys(
        ("hold_s", "delay_s", "step_delay_s", "trigger_delay_s", "measure_delay_s"), 0.0
    )
    SweepTiming(hold_s=655.35, delay_s=65.535, step_delay_s=1.0, trigger_delay_s=65.535, measure_delay_s=65.535)
    for bad in (
        {"hold_s": 655.36},
        {"delay_s": 65.6},
        {"step_delay_s": 1.1},
        {"measure_delay_s": 70.0},
        {"hold_s": -0.01},
        {"delay_s": 0.1, "trigger_delay_s": 0.2},  # Tdelay is 0 to delay
    ):
        with pytest.raises(ValidationError):
            SweepTiming.model_validate(bad)


def test_models_are_strict_and_immutable() -> None:
    with pytest.raises(ValidationError):
        SweepTiming.model_validate({"hold_s": 0.1, "fake": True})
    timing = SweepTiming(hold_s=0.1)
    with pytest.raises(ValidationError):
        timing.hold_s = 1.0  # type: ignore[misc]


def test_json_round_trip_is_lossless() -> None:
    models = [
        Integration(adc="high_resolution", mode="plc", n=16),
        Ranging(mode="limited_auto", range_value=1e-8),
        SweepTiming(hold_s=0.5, delay_s=0.01, trigger_delay_s=0.005),
        BiasChannel(channel=3, level=0.05, compliance=1e-2, compliance_range=1e-3),
    ]
    for model in models:
        assert type(model).model_validate_json(model.model_dump_json()) == model
