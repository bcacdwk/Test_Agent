"""Noise analysis (``analysis/noise.py``, ``analysis/spectrum.py``; blueprint v2 2.10, WP10.5) against analytic data
with known truth, generated here (no simulator): the Welch PSD normalization (white noise, a sine), log bins, the PSD
fit (exact on model spectra; gamma of synthetic 1/f^gamma records; the Lorentzian of a telegraph signal only when it
is there), ``rtn_levels`` on a two-state Markov signal (tau_c, tau_e, dI/I, hysteresis, level tracking under a slow
drift, polarity, refusals and failures), ``it_statistics`` on a line plus noise, record selection (events,
windows, non-uniform sampling), ``psd_welch`` results and units, and ``plot_psd``."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import noise as nz
from b1500_test_agent.analysis import spectrum as sp
from b1500_test_agent.analysis.dataset import RunData, with_trust
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS, methods_for, run_method
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import manifest

I0 = 1.0e-5


def flicker(n: int, dt: float, gamma: float, k_abs: float, rng: np.random.Generator) -> np.ndarray:
    """Gaussian series with one-sided PSD ``k_abs / f^gamma`` (spectral shaping of white noise)."""
    spectrum = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, dt)
    gain = np.zeros_like(f)
    gain[1:] = np.sqrt(k_abs / f[1:] ** gamma / (2.0 * dt))
    return np.fft.irfft(spectrum * gain, n)


def telegraph(n: int, dt: float, tau_c: float, tau_e: float, rng: np.random.Generator) -> np.ndarray:
    """Occupancy (0/1) of a two-state Markov trap sampled every ``dt`` (empty first: dwell mean tau_c)."""
    times, state, t = [], 0, 0.0
    while t < n * dt:
        t += rng.exponential(tau_c if state == 0 else tau_e)
        times.append(t)
        state ^= 1
    flips = np.searchsorted(np.asarray(times), np.arange(n) * dt, side="right")
    return (flips % 2).astype(float)


def run_data(values: np.ndarray, dt: float, *, column: str = "drain_I", status: Any = "N", t: np.ndarray | None = None,
             event: Any = None, recipe_id: str = "wgfmu.rtn") -> RunData:
    n = len(values)
    data: dict[str, Any] = {"step": np.arange(n), "t_s": (np.arange(n) + 0.5) * dt if t is None else t}
    if event is not None:
        data["event"] = event
    data.update({column: values, f"{column}_status": status})
    return RunData(manifest(recipe_id=recipe_id, kind="wgfmu_waveform"), with_trust(pd.DataFrame(data)))


def by_quantity(results: list[Any]) -> dict[str, Any]:
    return {r.quantity: r for r in results}


def rtn_record(seed: int = 1, n: int = 200_000, dt: float = 1e-5, *, delta: float = 0.05, white: float = 2e-3,
               drift: float = 0.0, sign: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    occ = telegraph(n, dt, 1e-3, 5e-4, rng)
    base = I0 * (1.0 + drift * np.linspace(0.0, 1.0, n))
    return sign * (base * (1.0 - delta * occ) + rng.normal(0.0, white * I0, n))


# -- Welch PSD -------------------------------------------------------------------------------------------------------


@pytest.mark.wgfmu
def test_white_noise_psd_is_two_sigma_squared_dt() -> None:
    rng = np.random.default_rng(0)
    dt, sigma = 1e-6, 3e-9
    f, s, nper = sp.welch_psd(rng.normal(0.0, sigma, 2**18), dt, segments=16)
    assert nper == 2 * 2**18 // 17 and f[0] == 0.0 and f[-1] == pytest.approx(0.5 / dt, rel=1e-4)
    assert np.mean(s[5:-5]) == pytest.approx(2 * sigma**2 * dt, rel=0.02)


def test_a_sine_puts_its_power_into_its_bin() -> None:
    dt, n, amp, f0 = 1e-4, 2**16, 2e-6, 125.0
    t = np.arange(n) * dt
    f, s, _ = sp.welch_psd(amp * np.sin(2 * np.pi * f0 * t), dt, segments=4)
    power = float(np.sum(s) * (f[1] - f[0]))  # integral of the one-sided PSD = variance
    assert power == pytest.approx(amp**2 / 2, rel=0.02) and f[int(np.argmax(s))] == pytest.approx(f0, rel=0.02)


def test_welch_refuses_too_short_segments() -> None:
    with pytest.raises(ValueError, match="points per segment"):
        sp.welch_psd(np.zeros(40), 1e-6, segments=8)


def test_log_bins_average_and_place_by_geometric_mean() -> None:
    f = np.arange(0.0, 1001.0)
    fb, sb, counts = sp.log_bins(f, 2.0 * np.ones_like(f), 10.0, 1000.0, per_decade=2)
    assert len(fb) == 4 and np.all(sb == 2.0) and int(counts.sum()) == 991
    assert fb[0] == pytest.approx(math.exp(np.mean(np.log(np.arange(10.0, 32.0)))), rel=1e-9)


# -- PSD fit ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["power", "power_lorentzian"])
def test_the_fit_recovers_an_exact_model_spectrum(model: str) -> None:
    f = np.geomspace(1.0, 1e5, 50)
    truth = sp.PsdFit(model=model, a=3e-16, gamma=1.15, b=2e-15 if model != "power" else 0.0, fc=300.0, w=1e-21,
                      gamma_se=0.0, rms_log=0.0, bic=0.0, bins=50)  # type: ignore[arg-type]
    fit = sp.fit_psd(f, truth.evaluate(f), np.ones_like(f), model=model)  # type: ignore[arg-type]
    assert fit.model == model and fit.gamma == pytest.approx(1.15, abs=1e-4) and fit.a == pytest.approx(3e-16, rel=1e-3)
    assert fit.w == pytest.approx(1e-21, rel=1e-2) and fit.rms_log < 1e-4
    if model == "power_lorentzian":
        assert fit.fc == pytest.approx(300.0, rel=1e-3) and fit.b == pytest.approx(2e-15, rel=1e-3)


@pytest.mark.parametrize("gamma", [0.7, 1.0, 1.3])
def test_gamma_of_synthetic_one_over_f_records(gamma: float) -> None:
    rng = np.random.default_rng(int(gamma * 10))
    dt = 1e-5
    x = I0 + flicker(200_000, dt, gamma, 1e-5 * I0**2, rng) + rng.normal(0.0, 1e-9, 200_000)
    found = by_quantity(nz.psd_welch(run_data(x, dt)))
    assert found["gamma"].value == pytest.approx(gamma, abs=0.05) and found["gamma"].classification == "power"
    assert found["flicker_norm_1hz"].value == pytest.approx(1e-5, rel=0.3)
    assert found["gamma"].fit["gamma_se"] < 0.05 and "corner_frequency" not in found


def test_auto_adds_the_lorentzian_of_a_telegraph_signal() -> None:
    rng = np.random.default_rng(5)
    dt, n = 1e-7, 504_000
    occ = telegraph(n, dt, 1e-3, 5e-4, rng)
    x = I0 * (1.0 - 0.05 * occ) + flicker(n, dt, 1.0, 1e-5 * I0**2, rng)
    auto = by_quantity(nz.psd_welch(run_data(x, dt, recipe_id="wgfmu.lfn")))
    assert auto["gamma"].classification == "power_lorentzian" and auto["gamma"].value == pytest.approx(1.0, abs=0.1)
    corner = (1 / 1e-3 + 1 / 5e-4) / (2 * math.pi)
    assert auto["corner_frequency"].value == pytest.approx(corner, rel=0.35) and auto["corner_frequency"].unit == "Hz"
    single = by_quantity(nz.psd_welch(run_data(x, dt, recipe_id="wgfmu.lfn"), model="power"))
    assert single["gamma"].value > 1.2  # one power law through a Lorentzian is too steep


@pytest.mark.wgfmu
def test_psd_results_units_reference_frequency_and_input_referred_noise() -> None:
    rng = np.random.default_rng(3)
    dt = 1e-5
    x = I0 + flicker(100_000, dt, 1.0, 1e-5 * I0**2, rng)
    found = by_quantity(nz.psd_welch(run_data(x, dt), gm_s=1e-4, f_ref=100.0))
    assert [r for r in found] == ["gamma", "flicker_norm_1hz", "psd_at_f_ref", "norm_psd_at_f_ref",
                                  "input_noise_at_f_ref"]
    assert found["psd_at_f_ref"].unit == "A^2/Hz" and found["norm_psd_at_f_ref"].unit == "1/Hz"
    assert found["psd_at_f_ref"].value == pytest.approx(1e-5 * I0**2 / 100.0, rel=0.3)
    assert found["input_noise_at_f_ref"].unit == "V^2/Hz"
    assert found["input_noise_at_f_ref"].value == pytest.approx(found["psd_at_f_ref"].value / 1e-8, rel=1e-5)
    default = by_quantity(nz.psd_welch(run_data(x, dt)))
    assert default["psd_at_f_ref"].fit["f_ref_hz"] == 100.0  # lowest power of ten inside 3 f_res (~13.5 Hz)..10 kHz
    voltage = by_quantity(nz.psd_welch(run_data(x * 1e5, dt, column="gate_V")))
    assert voltage["psd_at_f_ref"].unit == "V^2/Hz"
    with pytest.raises(InvalidInputError, match="gm_s"):
        nz.psd_welch(run_data(x * 1e5, dt, column="gate_V"), gm_s=1e-4)


def test_a_window_without_bins_fails_as_a_result() -> None:
    x = I0 + np.random.default_rng(1).normal(0.0, 1e-9, 10_000)
    found = nz.psd_welch(run_data(x, 1e-5), f_min=4e4, f_max=4.5e4)
    assert all(r.outcome == "failed" and "no PSD fit" in (r.error or "") for r in found)


# -- rtn_levels ------------------------------------------------------------------------------------------------------


@pytest.mark.wgfmu
def test_rtn_levels_recovers_the_trap() -> None:
    found = by_quantity(nz.rtn_levels(run_data(rtn_record(), 1e-5)))
    assert found["tau_c"].value == pytest.approx(1e-3, rel=0.1) and found["tau_e"].value == pytest.approx(5e-4, rel=0.1)
    assert found["delta_i_rel"].value == pytest.approx(0.05, rel=0.02)
    assert found["delta_i"].value == pytest.approx(0.05 * I0, rel=0.02) and found["delta_i"].unit == "A"
    fit = found["tau_c"].fit
    assert fit["transitions"] > 1000 and fit["occupancy"] == pytest.approx(1 / 3, abs=0.03)
    assert 0.85 < fit["cv"] < 1.15 and fit["tau_fit_s"] == pytest.approx(1e-3, rel=0.15)
    assert fit["se"] == pytest.approx(found["tau_c"].value / math.sqrt(fit["n"]), rel=1e-6)
    assert fit["separation"] > 10 and not found["tau_c"].warnings


def test_level_tracking_follows_a_slow_drift() -> None:
    x = rtn_record(drift=0.2)  # 20 % drift over the record: far more than the 5 % step
    tracked = by_quantity(nz.rtn_levels(run_data(x, 1e-5)))
    assert tracked["tau_c"].value == pytest.approx(1e-3, rel=0.1)
    assert tracked["delta_i_rel"].value == pytest.approx(0.05, rel=0.15)
    fixed = by_quantity(nz.rtn_levels(run_data(x, 1e-5), baseline_s=0.0))  # global levels only
    assert fixed["tau_c"].outcome != "ok" or abs(fixed["tau_c"].value - 1e-3) > 0.1e-3


def test_a_p_channel_record_and_the_occupied_option() -> None:
    negative = by_quantity(nz.rtn_levels(run_data(rtn_record(sign=-1.0), 1e-5)))
    assert negative["tau_c"].value == pytest.approx(1e-3, rel=0.1)  # still the dwell at the larger |I|
    swapped = by_quantity(nz.rtn_levels(run_data(rtn_record(), 1e-5), occupied="high"))
    assert swapped["tau_c"].value == pytest.approx(5e-4, rel=0.1)
    assert swapped["delta_i_rel"].value == pytest.approx(0.05 / 0.95, rel=0.03)  # relative to the low level


@pytest.mark.wgfmu
def test_rtn_warnings_short_records_and_coarse_sampling() -> None:
    short = by_quantity(nz.rtn_levels(run_data(rtn_record(n=8000), 1e-5)))
    assert short["tau_c"].outcome == "ok" and any("transitions" in w for w in short["tau_c"].warnings)
    coarse = by_quantity(nz.rtn_levels(run_data(rtn_record(n=40_000, dt=1e-4), 1e-4)))
    assert any("sampling intervals" in w for w in coarse["tau_e"].warnings)


def test_no_two_levels_is_a_failure_not_a_guess() -> None:
    rng = np.random.default_rng(2)
    x = I0 + rng.normal(0.0, 0.01 * I0, 50_000)
    found = nz.rtn_levels(run_data(x, 1e-5))
    assert [r.quantity for r in found] == ["tau_c", "tau_e", "delta_i", "delta_i_rel"]
    assert all(r.outcome == "failed" and "two-level" in (r.error or "") for r in found)


def test_smoothing_rescues_a_noisy_telegraph() -> None:
    noisy = rtn_record(white=0.02)
    plain = by_quantity(nz.rtn_levels(run_data(noisy, 1e-5)))
    smoothed = by_quantity(nz.rtn_levels(run_data(noisy, 1e-5), smooth=5))
    assert smoothed["tau_c"].value == pytest.approx(1e-3, rel=0.15)
    assert smoothed["tau_c"].fit["separation"] > plain["tau_c"].fit.get("separation", 0.0)


# -- it_statistics ---------------------------------------------------------------------------------------------------


def test_it_statistics_of_a_line_plus_noise() -> None:
    n, dt = 100_000, 1e-6
    rng = np.random.default_rng(4)
    t = (np.arange(n) + 0.5) * dt
    x = I0 * (1.0 + 0.1 * t / (n * dt)) + rng.normal(0.0, 1e-8, n)
    found = by_quantity(nz.it_statistics(run_data(x, dt)))
    assert found["mean"].value == pytest.approx(1.05 * I0, rel=1e-3) and found["mean"].unit == "A"
    assert found["drift_rel"].value == pytest.approx(0.1 / 1.05, rel=0.01)
    assert found["std"].fit["white_estimate"] == pytest.approx(1e-8, rel=0.02)
    assert found["noise_rel"].value == pytest.approx(found["std"].value / found["mean"].value, rel=1e-6)
    assert found["sample_interval"].value == pytest.approx(dt) and found["sample_interval"].fit["jitter_rel"] < 1e-6
    assert not found["std"].warnings  # a uniform spread of a line is not bimodal (bimodality 5/9 exactly)
    rtn = by_quantity(nz.it_statistics(run_data(rtn_record(), 1e-5)))
    assert rtn["std"].fit["bimodality"] > 5 / 9 and any("rtn_levels" in w for w in rtn["std"].warnings)


# -- the record ------------------------------------------------------------------------------------------------------


def test_untrusted_points_refuse_unless_forced() -> None:
    x = rtn_record(n=50_000)
    status = np.where(np.arange(50_000) == 30_000, "V", "N")
    refused = nz.rtn_levels(run_data(x, 1e-5, status=status))
    assert all(r.outcome == "refused" and "untrusted" in (r.error or "") for r in refused)
    forced = by_quantity(nz.rtn_levels(run_data(x, 1e-5, status=status), force=True))
    assert forced["tau_c"].outcome == "ok" and forced["tau_c"].forced_on_untrusted
    assert forced["tau_c"].points_used == 30_000  # the longest stretch: the removed point splits the record
    assert forced["tau_c"].points_excluded.get("non_uniform") == 19_999


def test_events_windows_and_gaps_select_the_record() -> None:
    x = rtn_record(n=60_000)
    events = np.where(np.arange(60_000) < 20_000, "E1", "E2")
    picked = by_quantity(nz.it_statistics(run_data(x, 1e-5, event=events)))
    assert picked["mean"].points_used == 40_000 and any("event 'E2'" in w for w in picked["mean"].warnings)
    named = by_quantity(nz.it_statistics(run_data(x, 1e-5, event=events), event="E1"))
    assert named["mean"].points_used == 20_000
    window = by_quantity(nz.it_statistics(run_data(x, 1e-5), t_min=0.1, t_max=0.2))
    assert window["mean"].points_used == 10_000 and window["mean"].points_excluded["outside_window"] == 50_000
    with pytest.raises(InvalidInputError, match="no event 'E9'"):
        nz.it_statistics(run_data(x, 1e-5, event=events), event="E9")
    t = (np.arange(60_000) + 0.5) * 1e-5
    t[30_000:] += 0.5  # a gap: two stretches
    gapped = by_quantity(nz.it_statistics(run_data(x, 1e-5, t=t)))
    assert gapped["mean"].points_used == 30_000 and any("longest uniformly" in w for w in gapped["mean"].warnings)


def test_records_need_time_and_enough_points() -> None:
    data = RunData(manifest(recipe_id="wgfmu.rtn", kind="wgfmu_waveform"), with_trust(pd.DataFrame(
        {"step": np.arange(10), "drain_I": np.ones(10), "drain_I_status": "N"})))
    with pytest.raises(InvalidInputError, match="no t_s column"):
        nz.rtn_levels(data)
    short = nz.psd_welch(run_data(np.ones(20), 1e-6))
    assert all(r.outcome == "failed" and "at least 64" in (r.error or "") for r in short)


# -- registry and plot -----------------------------------------------------------------------------------------------


@pytest.mark.wgfmu
def test_the_methods_are_registered_for_noise_records() -> None:
    for name in ("it_statistics", "psd_welch", "rtn_levels", "plot_psd"):
        method = ANALYSIS_METHODS[name]
        assert method.milestone == "M10" and set(method.families) == {"smu", "wgfmu"}
        for recipe_id, kind in (("wgfmu.rtn", "wgfmu_waveform"), ("wgfmu.lfn", "wgfmu_waveform"),
                                ("generic.smu_sampling", "smu_sampling")):
            assert method.applies_to(recipe_id, kind)
        assert not method.applies_to("mosfet.idvg", "smu_staircase")
    assert {"psd_welch", "rtn_levels"} <= {m.name for m in methods_for("wgfmu")}
    assert "hysteresis" in ANALYSIS_METHODS["rtn_levels"].options and "gm_s" in ANALYSIS_METHODS["psd_welch"].options


@pytest.mark.wgfmu
def test_plot_psd_renders_and_never_refuses() -> None:
    x = rtn_record(n=100_000)
    plots = run_method("plot_psd", run_data(x, 1e-5))
    assert [p.name for p in plots.plots] == ["psd"] and plots.plots[0].png[:4] == b"\x89PNG"  # type: ignore[union-attr]
    status = np.where(np.arange(100_000) == 10, "V", "N")
    noted = run_method("plot_psd", run_data(x, 1e-5, status=status))
    assert any("untrusted" in w for w in noted.warnings)  # type: ignore[union-attr]
    empty = run_method("plot_psd", run_data(np.ones(10), 1e-5))
    assert any("no PSD" in w for w in empty.warnings)  # type: ignore[union-attr]
