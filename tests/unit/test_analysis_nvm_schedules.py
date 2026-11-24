"""``switching_kinetics_fit``, ``endurance_summary``/``endurance_curve`` and ``retention_fit`` on synthetic pulse_read
tables with known truth (WP9.5, blueprint v2 2.10 ``nvm.py``), and the NLS core ``nls.fit_nls``: parameter recovery
(fixed and free alpha), ISPP step response, wake-up/fatigue/cycles to failure, log-time slopes and extrapolation,
refused reads, unusable calls and the registry entries."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import (
    ANALYSIS_METHODS,
    endurance_curve,
    endurance_summary,
    retention_fit,
    run_method,
    switching_kinetics_fit,
)
from b1500_test_agent.analysis.dataset import RunData, with_trust
from b1500_test_agent.analysis.nls import fit_nls, switched_fraction
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult
from tests.unit.analysis_helpers import run_of, subthreshold_id

VG = np.round(np.linspace(-0.5, 1.8, 47), 9)
V0 = 0.3
"""``subthreshold_id`` reaches 100 nA at v0: the constant-current Vth of an unshifted read."""

TAU0, VA, ALPHA, BETA = 1e-9, 8.0, 2.0, 0.8
AMPLITUDES = [3.2, 3.6, 4.0, 4.4, 4.8]
WIDTHS = [1e-8, 2e-8, 5e-8, 1e-7, 2e-7, 5e-7, 1e-6, 2e-6, 5e-6, 1e-5, 1e-4]


def found(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def tau(v: float, tau0: float = TAU0, va: float = VA, alpha: float = ALPHA) -> float:
    return tau0 * math.exp((va / abs(v)) ** alpha)


def window(v: float) -> float:
    """Switched window of amplitude ``v`` at saturation (V; grows with the amplitude, a minor-loop limit)."""
    return -0.9 * math.tanh((v - 2.6) / 0.6)


def table_of(reads: Sequence[tuple[int, str, float, float | None]], *, status: dict[tuple[int, str], str] | None = None
             ) -> pd.DataFrame:
    """A pulse_read table: per read ``(cycle, phase, vth, t_s)`` an Id-Vg sweep of ``subthreshold_id`` shifted to
    ``vth``; ``status`` sets the drain status of a read's first five points."""
    rows: list[dict[str, Any]] = []
    timed = any(t is not None for *_, t in reads)
    for cycle, phase, vth, t_s in reads:
        letter = (status or {}).get((cycle, phase), "N")
        currents = subthreshold_id(VG - (vth - V0), v0=V0)
        for index, (vg, current) in enumerate(zip(VG, currents, strict=True)):
            row: dict[str, Any] = {"cycle": cycle, "phase": phase, "gate_read_V": vg, "drain_I": current,
                                   "drain_I_status": letter if index < 5 else "N", "drain_V": 0.05}
            if timed:
                row = {"t_s": t_s if t_s is not None else math.nan, **row}
            rows.append(row)
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    return with_trust(table)


def run_with(table: pd.DataFrame, recipe_id: str, program: dict[str, Any]) -> RunData:
    run = run_of(table, recipe_id, kind="pulse_read")
    plan = run.manifest.plan.model_copy(update={"program": program})
    return RunData(run.manifest.model_copy(update={"plan": plan}), table)


def kinetics_run(*, mode: str = "reset", amplitudes: Sequence[float] = AMPLITUDES, widths: Sequence[float] = WIDTHS,
                 reset_vth: float = 1.0, model: Callable[[float, float], float] | None = None,
                 status: dict[tuple[int, str], str] | None = None) -> RunData:
    """A grid run: reset to ``reset_vth``, one program pulse per point (amplitude-major), Vth by the NLS model (or
    ``model(level, width)``); ISPP: one reset per width row, the amplitudes cumulatively (``model`` gives the row's
    cumulative Vth)."""
    if mode == "reset":
        pairs = [(row, a, w) for row, a in enumerate(amplitudes) for w in widths]
    else:
        pairs = [(row, a, w) for row, w in enumerate(widths) for a in amplitudes]
    grid = [{"cycle": i, "op": f"g{i}", "level": a, "width": w, "row": row} for i, (row, a, w) in enumerate(pairs, 1)]
    reads: list[tuple[int, str, float, float | None]] = [(0, "read", reset_vth, None)]
    seen_rows: set[int] = set()
    for point in grid:
        if mode == "reset" or point["row"] not in seen_rows:
            reads.append((point["cycle"], "erase", reset_vth, None))
            seen_rows.add(point["row"])
        level, width = point["level"], point["width"]
        vth = model(level, width) if model else reset_vth + window(level) * float(
            switched_fraction(np.array([width]), np.array([tau(level)]), BETA)[0])
        reads.append((point["cycle"], "program", vth, None))
    program = {"schedule": "grid", "grid_mode": mode, "sequence": ["erase", "program"], "grid": grid}
    return run_with(table_of(reads, status=status), "fefet.switching_kinetics", program)


# -- NLS core --------------------------------------------------------------------------------------------------------


def grid_points(beta: float = BETA) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    levels, widths, y = [], [], []
    for a in AMPLITUDES:
        for w in WIDTHS:
            levels.append(a)
            widths.append(w)
            y.append(1.0 + window(a) * (1.0 - math.exp(-((w / tau(a)) ** beta))))
    return np.array(levels), np.array(widths), np.array(y)


def test_nls_recovers_the_switching_law_with_a_fixed_alpha() -> None:
    fit = fit_nls(*grid_points())
    assert not isinstance(fit, str)
    assert fit.tau0 == pytest.approx(TAU0, rel=1e-3) and fit.va == pytest.approx(VA, rel=1e-4)
    assert fit.beta == pytest.approx(BETA, rel=1e-4) and fit.alpha == ALPHA and fit.alpha_se == 0.0
    assert fit.v0 == pytest.approx(1.0, abs=1e-6) and fit.rms < 1e-6 and fit.r2 > 0.999999
    assert fit.per_level[4.0][0] == pytest.approx(tau(4.0), rel=1e-3)
    assert fit.per_level[4.0][1] == pytest.approx(window(4.0), rel=1e-4)


def test_nls_fits_alpha_when_asked() -> None:
    fit = fit_nls(*grid_points(1.0), alpha=None)
    assert not isinstance(fit, str)
    assert fit.alpha == pytest.approx(ALPHA, rel=1e-2) and fit.tau0 == pytest.approx(TAU0, rel=0.05)
    assert fit.beta == pytest.approx(1.0, rel=1e-3) and fit.alpha_se > 0


def test_nls_with_noise_stays_within_the_fidelity_band() -> None:
    levels, widths, y = grid_points()
    noisy = y + np.random.default_rng(5).normal(0.0, 2e-3, y.size)
    fit = fit_nls(levels, widths, noisy)
    assert not isinstance(fit, str)
    assert fit.tau0 == pytest.approx(TAU0, rel=0.2) and fit.beta == pytest.approx(BETA, rel=0.2)
    assert fit.rms == pytest.approx(2e-3, rel=0.3) and 0 < fit.tau0_rel_se < 0.2


@pytest.mark.parametrize(("levels", "message"), [([4.0], "the fit needs 2"), ([3.6, 4.0], "points for")])
def test_nls_refuses_too_little_data(levels: list[float], message: str) -> None:
    widths = [1e-8, 1e-7, 1e-6] if len(levels) == 2 else WIDTHS
    pts = [(a, w) for a in levels for w in widths]
    y = [1.0 + window(a) * (1 - math.exp(-w / tau(a))) for a, w in pts]
    result = fit_nls(np.array([a for a, _ in pts]), np.array([w for _, w in pts]), np.array(y))
    assert isinstance(result, str) and message in result


def test_nls_warns_about_amplitudes_that_never_switch_inside_the_widths() -> None:
    levels, widths, y = grid_points()
    keep = widths <= 1e-6
    fit = fit_nls(np.append(levels[keep], [2.5] * 4), np.append(widths[keep], [1e-8, 1e-7, 1e-6, 1e-5]),
                  np.append(y[keep], [1.0] * 4))
    assert not isinstance(fit, str) and any("2.5 V" in w and "weakly" in w for w in fit.warnings)


# -- switching_kinetics_fit ------------------------------------------------------------------------------------------


def test_kinetics_fit_on_a_reset_grid_recovers_tau0_beta_va() -> None:
    results = found(switching_kinetics_fit(kinetics_run()))
    assert list(results) == ["tau0", "beta", "va", "vth_reset"]
    tau0, beta, va = results["tau0"], results["beta"], results["va"]
    assert tau0.value == pytest.approx(TAU0, rel=0.02) and tau0.unit == "s" and tau0.derived
    assert beta.value == pytest.approx(BETA, rel=0.01) and va.value == pytest.approx(VA, rel=0.01)
    assert tau0.points_used == 55 and tau0.window is not None and tau0.window.low == 1e-8
    assert tau0.fit["alpha"] == 2.0 and tau0.fit["tau@4V"] == pytest.approx(tau(4.0), rel=0.03)
    assert tau0.fit["window@4V"] == pytest.approx(window(4.0), abs=2e-3)
    assert results["vth_reset"].value == pytest.approx(1.0, abs=2e-3) and results["vth_reset"].fit["reads"] == 55
    assert tau0.method_record.params["grid_mode"] == "reset" and tau0.method_record.params["x"] == "gate_read_V"


def test_kinetics_fit_frees_alpha_as_an_option() -> None:
    results = found(run_method("switching_kinetics_fit", kinetics_run(), {"alpha": None}))  # type: ignore[arg-type]
    assert list(results) == ["tau0", "beta", "va", "alpha", "vth_reset"]
    assert results["alpha"].value == pytest.approx(ALPHA, rel=0.05)


def test_ispp_gives_v50_and_the_step_slope() -> None:
    def cumulative(level: float, width: float) -> float:  # dVth grows linearly from 3 V to 4 V by 1 V/V, then flat
        return 1.0 - min(max(level - 3.0, 0.0), 1.0)

    amps = [3.0, 3.25, 3.5, 3.75, 4.0, 4.5]
    results = found(switching_kinetics_fit(kinetics_run(mode="ispp", amplitudes=amps, widths=[1e-7, 1e-6],
                                                        model=cumulative)))
    assert list(results) == ["v50", "ispp_slope", "vth_reset"]
    assert results["v50"].value == pytest.approx(3.5, abs=0.01) and results["v50"].fit["rows"] == 2
    assert results["ispp_slope"].value == pytest.approx(1.0, abs=0.02) and results["ispp_slope"].unit == "1"
    assert any("need grid_mode reset" in w for w in results["v50"].warnings)


def test_untrusted_grid_reads_drop_out_and_the_fit_still_runs() -> None:
    results = found(switching_kinetics_fit(kinetics_run(status={(12, "program"): "X", (13, "program"): "X"})))
    assert results["tau0"].points_used == 53 and results["tau0"].value == pytest.approx(TAU0, rel=0.02)
    assert sum("left out" in w for w in results["tau0"].warnings) == 2


def test_kinetics_needs_a_grid_run() -> None:
    run = run_with(table_of([(0, "read", 1.0, None), (1, "program", 0.5, None)]), "fefet.endurance",
                   {"schedule": "cycles"})
    with pytest.raises(InvalidInputError, match="not a pulse_read run of schedule grid"):
        switching_kinetics_fit(run)


# -- endurance -------------------------------------------------------------------------------------------------------


def endurance_run(mw: Callable[[int], float], checkpoints: Sequence[int], *,
                  status: dict[tuple[int, str], str] | None = None) -> RunData:
    reads: list[tuple[int, str, float, float | None]] = [(0, "read", 1.0, None)]
    for n in checkpoints:
        reads += [(n, "erase", 0.6 + mw(n) / 2, None), (n, "program", 0.6 - mw(n) / 2, None)]
    program = {"schedule": "cycles", "cycle_reads": "log", "sequence": ["erase", "program"],
               "checkpoints": list(checkpoints)}
    return run_with(table_of(reads, status=status), "fefet.endurance", program)


def wake_fatigue(n: int) -> float:
    return (1.0 - 0.1 * math.exp(-n / 100.0)) / (1.0 + n / 1e5)


CHECKPOINTS = [1, 2, 5, 10, 22, 46, 100, 215, 464, 1000, 2154, 4642, 10000, 21544, 46416, 100000, 215443, 464159,
               1000000]


def test_endurance_summary_reports_wake_up_fatigue_and_failure() -> None:
    results = found(endurance_summary(endurance_run(wake_fatigue, CHECKPOINTS)))
    assert list(results) == ["memory_window_initial", "memory_window_max", "memory_window_final", "wake_up",
                             "fatigue", "cycles_to_failure"]
    peak = max(CHECKPOINTS, key=wake_fatigue)
    assert results["memory_window_initial"].value == pytest.approx(wake_fatigue(1), abs=2e-3)
    assert results["memory_window_max"].fit["cycles_at_max"] == peak
    assert results["memory_window_final"].value == pytest.approx(wake_fatigue(10**6), abs=2e-3)
    assert results["wake_up"].value == pytest.approx(wake_fatigue(peak) / wake_fatigue(1) - 1, abs=3e-3)
    assert results["fatigue"].value == pytest.approx(1 - wake_fatigue(10**6) / wake_fatigue(peak), abs=3e-3)
    failure = results["cycles_to_failure"]
    assert failure.bound == "exact" and failure.value == pytest.approx(1e5, rel=0.25)
    curve = endurance_curve(endurance_run(wake_fatigue, CHECKPOINTS))
    assert [c.cycles for c in curve] == CHECKPOINTS and curve[0].window == pytest.approx(wake_fatigue(1), abs=2e-3)


def test_a_window_that_never_fails_gives_a_lower_bound() -> None:
    results = found(endurance_summary(endurance_run(lambda n: 1.0, [1, 10, 100])))
    failure = results["cycles_to_failure"]
    assert failure.bound == "lower" and failure.value == 100 and "lower bound" in failure.warnings[-1]
    assert results["wake_up"].value == pytest.approx(0.0, abs=2e-3)


def test_an_absolute_failure_criterion_is_an_option() -> None:
    results = found(endurance_summary(endurance_run(lambda n: 1.0 - 0.1 * math.log10(n), [1, 10, 100, 1000]),
                                      mw_fail=0.85))
    assert results["cycles_to_failure"].value == pytest.approx(10 ** 1.5, rel=0.02)
    assert results["cycles_to_failure"].fit["criterion_v"] == 0.85


def test_endurance_with_one_checkpoint_has_no_trend() -> None:
    results = found(endurance_summary(endurance_run(lambda n: 1.0, [1])))
    assert results["memory_window_final"].value == pytest.approx(1.0, abs=2e-3)
    assert results["wake_up"].outcome == "failed" and "one checkpoint" in str(results["wake_up"].error)


def test_endurance_needs_checkpoint_reads() -> None:
    run = run_with(table_of([(1, "erase", 1.0, None), (1, "program", 0.0, None)]), "fefet.pulse_write_read",
                   {"schedule": "cycles"})
    with pytest.raises(InvalidInputError, match="checkpoint reads"):
        endurance_summary(run)


# -- retention -------------------------------------------------------------------------------------------------------

TIMES = [1.0, 2.15, 4.64, 10.0, 21.54, 46.42, 100.0, 215.44, 464.16, 1000.0]


def retention_run(slope_p: float, slope_e: float, *, times: Sequence[float] = TIMES,
                  status: dict[tuple[int, str], str] | None = None) -> RunData:
    reads: list[tuple[int, str, float, float | None]] = [(0, "read", 1.0, None)]
    reads += [(k, "program", 0.1 + slope_p * math.log10(t), t) for k, t in enumerate(times, 1)]
    reads += [(k, "erase", 1.1 + slope_e * math.log10(t), t) for k, t in enumerate(times, 1)]
    program = {"schedule": "retention", "sequence": ["program", "erase"], "read_times": list(times)}
    return run_with(table_of(reads, status=status), "fefet.retention", program)


def test_retention_fit_gives_slopes_extrapolation_and_retention_time() -> None:
    results = found(retention_fit(retention_run(0.015, -0.02)))
    assert list(results) == ["retention_slope_program", "retention_slope_erase", "memory_window_slope",
                             "memory_window_at_target", "retention_time"]
    assert results["retention_slope_program"].value == pytest.approx(0.015, abs=2e-4)
    assert results["retention_slope_erase"].value == pytest.approx(-0.02, abs=2e-4)
    assert results["retention_slope_erase"].unit == "V/dec"
    mw = results["memory_window_slope"]
    assert mw.value == pytest.approx(-0.035, abs=3e-4) and mw.fit["mw_1s"] == pytest.approx(1.0, abs=2e-3)
    target = results["memory_window_at_target"]
    assert target.value == pytest.approx(1.0 - 0.035 * math.log10(3.15576e8), abs=5e-3)
    assert any("extrapolated" in w for w in target.warnings)
    t_fail = results["retention_time"]
    assert t_fail.value == pytest.approx(10 ** (0.5 / 0.035), rel=0.1) and t_fail.unit == "s"


def test_a_window_that_does_not_decay_is_a_lower_bound_at_the_target() -> None:
    results = found(retention_fit(retention_run(0.0, 0.0), target_time_s=1e6))
    t_fail = results["retention_time"]
    assert t_fail.bound == "lower" and t_fail.value == 1e6


def test_t_min_and_refused_reads_shape_the_fit() -> None:
    run = retention_run(0.015, -0.02, status={(3, "program"): "X"})
    results = found(retention_fit(run, t_min=4.0))
    assert results["retention_slope_program"].points_used == 7  # t >= 4 s: 8 reads, one refused
    assert results["retention_slope_erase"].points_used == 8 and results["memory_window_slope"].points_used == 14


def test_a_single_state_has_no_window() -> None:
    reads: list[tuple[int, str, float, float | None]] = [(k, "program", 0.1 + 0.01 * math.log10(t), t)
                                                         for k, t in enumerate(TIMES, 1)]
    program = {"schedule": "retention", "sequence": ["program"], "read_times": TIMES}
    results = found(retention_fit(run_with(table_of(reads), "fefet.retention", program)))
    assert list(results) == ["retention_slope_program"]


def test_retention_needs_a_retention_run() -> None:
    with pytest.raises(InvalidInputError, match="schedule retention"):
        retention_fit(endurance_run(lambda n: 1.0, [1, 10]))


# -- registry --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "recipe"), [("switching_kinetics_fit", "fefet.switching_kinetics"),
                                                ("endurance_summary", "fefet.endurance"),
                                                ("retention_fit", "fefet.retention")])
def test_the_methods_are_registered_for_their_recipes(method: str, recipe: str) -> None:
    entry = ANALYSIS_METHODS[method]
    assert entry.status == "implemented" and entry.families == ("nvm",) and entry.kinds == ("pulse_read",)
    assert recipe in entry.recipes and entry.milestone == "M9"
