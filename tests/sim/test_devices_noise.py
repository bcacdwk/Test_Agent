"""``noise`` device truth (blueprint 4.2, WP5.9): 1/f slope γ ±0.1 (Welch PSD), RTN τc/τe ±20 % from ≥ 200
transitions and ΔI/I ±10 % (two-level detection), white rms per range, determinism and state continuity."""

from __future__ import annotations

import math

import numpy as np
import pytest

from b1500_test_agent.models.sim import NoiseParams
from b1500_test_agent.transport.sim.devices.noise import NoiseSource
from tests.sim.device_fits import dwell_times, linfit, welch_psd


def source(**extra: float | str) -> NoiseSource:
    return NoiseSource("n", NoiseParams.model_validate({"attach": "dut", "terminal": "drain", "seed": 4, **extra}))


@pytest.mark.parametrize("gamma", [0.8, 1.0, 1.3])
def test_flicker_slope_and_level(gamma: float) -> None:
    noise = source(flicker_k=1e-8, flicker_gamma=gamma)
    i_dc, dt, n = 1e-6, 1e-4, 2 ** 18
    x = noise.sample(i_dc, dt, n) - i_dc
    f, psd = welch_psd(x, dt, 4096)
    band = (f > 20 * f[1]) & (f < 0.1 / dt)
    slope, intercept = linfit(np.log10(f[band]), np.log10(psd[band]))
    assert -slope == pytest.approx(gamma, abs=0.1)
    # level: S_I(f) = K·I²/f^γ, checked at 10 Hz from the fitted line
    level = 10 ** (intercept + slope * 1.0)
    assert level == pytest.approx(float(noise.psd_truth(10.0, i_dc)), rel=0.25)


def test_rtn_dwell_times_and_amplitude() -> None:
    noise = source(rtn_tau_c_s=2e-3, rtn_tau_e_s=5e-4, rtn_delta_rel=0.04, white_frac=1e-4)
    i_dc, dt, n = 1e-6, 1e-5, 2 ** 18
    x = noise.sample(i_dc, dt, n, range_a=1e-5)  # white rms 1 nA on the 10 µA range
    threshold = 0.5 * (x.max() + x.min())
    high = x > threshold  # trap empty: full current
    empty_runs, captured_runs = dwell_times(high, dt)
    assert min(len(empty_runs), len(captured_runs)) >= 200
    assert float(np.mean(empty_runs)) == pytest.approx(2e-3, rel=0.20)  # τc: time until capture
    assert float(np.mean(captured_runs)) == pytest.approx(5e-4, rel=0.20)  # τe: time until emission
    delta = (np.mean(x[high]) - np.mean(x[~high])) / np.mean(x[high])
    assert delta == pytest.approx(0.04, rel=0.10)
    assert float(np.mean(~high)) == pytest.approx(5e-4 / 2.5e-3, rel=0.15)  # occupancy τe/(τc + τe)
    truth = noise.truth()
    assert (truth["tau_c_s"], truth["tau_e_s"], truth["delta_rel"]) == (2e-3, 5e-4, 0.04)


def test_rtn_lorentzian_psd_matches_the_truth() -> None:
    noise = source(rtn_tau_c_s=1e-3, rtn_tau_e_s=1e-3, rtn_delta_rel=0.05)
    i_dc, dt, n = 1e-6, 2e-5, 2 ** 19
    x = noise.sample(i_dc, dt, n)
    f, psd = welch_psd(x, dt, 8192)
    for f0 in (20.0, 200.0, 2000.0):  # plateau, corner (1/(2π·0.5 ms) ≈ 318 Hz) and the 1/f² tail
        k = int(np.argmin(np.abs(f - f0)))
        window = psd[max(k - 3, 1):k + 4].mean()
        assert window == pytest.approx(float(noise.psd_truth(f[k], i_dc)), rel=0.25)


def test_white_noise_is_per_range() -> None:
    noise = source(white_frac=2e-3)
    for range_a in (1e-6, 1e-4):
        x = noise.sample(0.0, 1e-6, 50_000, range_a=range_a)
        assert float(np.std(x)) == pytest.approx(2e-3 * range_a, rel=0.03)
    assert np.all(noise.sample(1e-9, 1e-6, 100) == 1e-9)  # no range given: no white noise


def test_series_are_deterministic_and_continue_the_trap_state() -> None:
    params = {"rtn_tau_c_s": 1e-3, "rtn_tau_e_s": 1e-3, "rtn_delta_rel": 0.1, "flicker_k": 1e-9}
    a, b = source(**params), source(**params)
    first = a.sample(1e-6, 1e-5, 1000)
    assert np.array_equal(first, b.sample(1e-6, 1e-5, 1000))  # same seed, name and call counter
    assert not np.array_equal(a.sample(1e-6, 1e-5, 1000), first)  # the next acquisition is a new realisation
    state = a.export_state()
    assert state["calls"] == 2 and isinstance(state["occupied"], bool)
    c = source(**params)
    c.import_state(state)
    assert np.array_equal(c.sample(1e-6, 1e-5, 500), a.sample(1e-6, 1e-5, 500))  # restored: same next acquisition
    other_name = NoiseSource("other", NoiseParams(attach="dut", terminal="drain", seed=4, **params))
    assert not np.array_equal(other_name.sample(1e-6, 1e-5, 1000), source(**params).sample(1e-6, 1e-5, 1000))
    # the first sample of an acquisition reflects the persisted occupancy
    d = source(rtn_tau_c_s=1.0, rtn_tau_e_s=1.0, rtn_delta_rel=0.5)
    d.import_state({"occupied": True, "calls": 0})
    assert d.sample(1.0, 1e-6, 10)[0] == pytest.approx(0.5)


def test_noise_validation_and_protocol() -> None:
    with pytest.raises(ValueError, match="given together"):
        NoiseParams(attach="dut", terminal="drain", rtn_tau_c_s=1e-3)
    with pytest.raises(ValueError, match="rtn_delta_rel needs"):
        NoiseParams(attach="dut", terminal="drain", rtn_delta_rel=0.1)
    noise = source()
    assert noise.terminal_currents({"x": 1.0}) == {}
    noise.commit({"x": 1.0})
    assert noise.export_state() == {"occupied": False, "calls": 0}
    with pytest.raises(ValueError, match="calls"):
        noise.import_state({"occupied": False, "calls": -1})
    with pytest.raises(ValueError, match="dt > 0"):
        noise.sample(1e-6, 0.0, 10)
    assert math.isclose(float(source(flicker_k=1e-8).psd_truth(1.0, 1e-6)), 1e-8 * 1e-12)
