"""Sampling analyses (WP7.4, blueprint v2 2.10 ``reliability.py``) on analytic data with known truth:
``sampling_summary`` (statistics, stretched-exponential tau and beta), ``time_to_breakdown`` (compliance, jump,
threshold, censored) and the run-list helper ``weibull_fit`` (MLE with censoring, median ranks), including a Weibull
population drawn from the simulator's dielectric model (its seeded sites)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import (
    RunData,
    fit_stretched_exponential,
    run_method,
    sampling_summary,
    time_to_breakdown,
    weibull_fit,
    with_trust,
)
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.sim import DielectricParams
from b1500_test_agent.transport.sim.devices.dielectric import DielectricDevice
from tests.unit.analysis_helpers import manifest

pytestmark = pytest.mark.smu

TAU, BETA, Y0, YINF = 4.0, 0.5, 1.45e-6, 1.27e-6


def sampling_run(t: np.ndarray, y: np.ndarray, *, status: list[str] | None = None, column: str = "drain_I",
                 recipe_id: str = "mosfet.id_t_sampling", run_id: str = "S20261119T100000Z-0a0a",
                 extra: dict[str, np.ndarray] | None = None) -> RunData:
    table = pd.DataFrame({"step": np.arange(t.size), "t_s": t, column: y,
                          f"{column}_status": status or ["N"] * t.size})
    for name, values in (extra or {}).items():
        table[name] = values
        table[f"{name}_status"] = "N"
    return RunData(manifest(run_id, recipe_id=recipe_id, kind="smu_sampling", params={}), with_trust(table))


def relaxation(t: np.ndarray, tau: float = TAU, beta: float = BETA) -> np.ndarray:
    return YINF + (Y0 - YINF) * np.exp(-np.power(t / tau, beta))


def by_quantity(results: list) -> dict:
    return {r.quantity: r for r in results}


# -- sampling_summary ------------------------------------------------------------------------------------------------


def test_statistics_of_a_flat_noisy_record() -> None:
    rng = np.random.default_rng(1)
    t = np.arange(0, 100.0, 0.1)
    y = 1e-6 + rng.normal(0, 1e-9, t.size)
    found = by_quantity(sampling_summary(sampling_run(t, y)))
    assert set(found) == {"initial", "final", "mean", "std", "drift"}
    assert found["mean"].value == pytest.approx(1e-6, rel=1e-3) and found["mean"].unit == "A"
    assert found["std"].value == pytest.approx(1e-9, rel=0.1)
    assert abs(found["drift"].value) < 0.01 and found["drift"].unit == "1"
    assert found["initial"].fit["edge_points"] == 10 and found["initial"].window is not None


@pytest.mark.parametrize(("tau", "beta"), [(4.0, 0.5), (0.8, 0.35), (12.0, 0.8), (3.0, 1.0)])
def test_the_stretched_exponential_fit_recovers_tau_and_beta(tau: float, beta: float) -> None:
    rng = np.random.default_rng(7)
    t = 0.01 + np.arange(10001) * 0.004
    y = relaxation(t, tau, beta) + rng.normal(0, 3e-9, t.size)
    found = by_quantity(sampling_summary(sampling_run(t, y), fit="stretched_exp"))
    assert found["tau"].value == pytest.approx(tau, rel=0.05) and found["tau"].unit == "s"
    assert found["beta"].value == pytest.approx(beta, abs=0.03)
    assert found["y_inf"].value == pytest.approx(YINF, rel=0.01)
    assert found["tau"].fit["r2"] > 0.9 and found["tau"].fit["tau_se"] > 0
    assert found["drift"].value < 0


def test_the_fit_is_exact_on_noiseless_data_and_flags_an_unconstrained_tau() -> None:
    t = np.geomspace(0.01, 100.0, 300)
    p = fit_stretched_exponential(t, relaxation(t, 2.0, 0.6))
    assert p["tau"] == pytest.approx(2.0, rel=1e-4) and p["beta"] == pytest.approx(0.6, abs=1e-4)
    t_short = np.linspace(0.01, 2.0, 400)  # the relaxation has barely started
    found = by_quantity(sampling_summary(sampling_run(t_short, relaxation(t_short, 50.0, 0.9)), fit="stretched_exp"))
    assert any("poorly constrained" in w for w in found["tau"].warnings)
    with pytest.raises(ValueError):
        fit_stretched_exponential(np.array([0.0, 1.0]), np.array([1.0, 2.0]))


def test_window_and_limited_points() -> None:
    t = np.arange(0, 10.0, 0.01)
    y = relaxation(t)
    status = ["N"] * t.size
    status[5] = "C"
    found = by_quantity(sampling_summary(sampling_run(t, y, status=status), t_min=1.0, t_max=5.0))
    mean = found["mean"]
    assert mean.points_used == 401 and mean.window is not None and (mean.window.low, mean.window.high) == (1.0, 5.0)
    assert mean.points_excluded["outside_window"] == t.size - 401 - 1 and mean.points_excluded["C"] == 1


def test_untrusted_points_refuse_unless_forced() -> None:
    t = np.arange(0, 1.0, 0.01)
    status = ["N"] * t.size
    status[10] = "X"
    run = sampling_run(t, relaxation(t), status=status)
    refused = sampling_summary(run)
    assert {r.outcome for r in refused} == {"refused"} and "untrusted" in (refused[0].error or "")
    forced = by_quantity(sampling_summary(run, force=True))
    assert forced["mean"].outcome == "ok" and forced["mean"].forced_on_untrusted


def test_column_choice_and_errors() -> None:
    t = np.arange(0, 1.0, 0.1)
    two = sampling_run(t, t * 0 + 1e-6, extra={"gate_I": t * 0 + 1e-12})
    with pytest.raises(InvalidInputError, match="several currents"):
        sampling_summary(two)
    assert sampling_summary(two, y="gate_I")[2].value == pytest.approx(1e-12)
    with pytest.raises(InvalidInputError, match="not a measured column"):
        sampling_summary(two, y="nope_I")
    no_time = RunData(two.manifest, two.table.drop(columns=["t_s"]))
    with pytest.raises(InvalidInputError, match="no t_s column"):
        sampling_summary(no_time)
    few = sampling_summary(sampling_run(np.array([0.0]), np.array([1e-6])))
    assert {r.outcome for r in few} == {"failed"}
    zero = by_quantity(sampling_summary(sampling_run(t, t * 0.0)))
    assert zero["drift"].outcome == "failed"


def test_registered_for_the_sampling_recipes() -> None:
    method = ANALYSIS_METHODS["sampling_summary"]
    assert method.applies_to("mosfet.id_t_sampling", "smu_sampling")
    assert method.applies_to("generic.smu_sampling", "smu_sampling")
    assert not method.applies_to("mosfet.idvg", "smu_staircase")
    assert set(method.families) == {"smu", "reliability"}
    t = np.arange(0, 10.0, 0.01)
    out = run_method("sampling_summary", sampling_run(t, relaxation(t)), {"fit": "stretched_exp"})
    assert isinstance(out, list) and {r.quantity for r in out} >= {"tau", "beta"}


# -- time_to_breakdown -----------------------------------------------------------------------------------------------


def tddb_run(currents: list[float], status: list[str] | None = None, *, dt: float = 1.0,
             run_id: str = "S20261119T100000Z-0b0b") -> RunData:
    t = np.arange(len(currents)) * dt
    return sampling_run(t, np.asarray(currents), status=status, column="gate_I", recipe_id="reliability.tddb_cvs",
                        run_id=run_id)


def test_breakdown_by_compliance() -> None:
    currents = [2.0e-6 + 1e-9 * k for k in range(50)] + [1e-3]
    result = time_to_breakdown(tddb_run(currents, ["N"] * 50 + ["C"]))
    assert result.outcome == "ok" and result.value == 50.0 and result.unit == "s"
    assert result.classification == "breakdown" and result.bound == "exact"
    assert result.fit["criterion"] == 1.0 and result.fit["t_prev_s"] == 49.0 and result.fit["resolution_s"] == 1.0
    assert result.fit["i_before_bd_a"] == pytest.approx(2.049e-6) and result.fit["i_at_bd_a"] == 1e-3


def test_breakdown_by_a_current_jump_and_by_threshold() -> None:
    currents = [1e-9] * 20 + [5e-8] + [5e-8] * 5
    jump = time_to_breakdown(tddb_run(currents))
    assert jump.value == 20.0 and jump.fit["criterion"] == 2.0
    assert jump.points_excluded == {"after_breakdown": 5}
    threshold = time_to_breakdown(tddb_run([1e-9 * (1.1 ** k) for k in range(60)]), i_bd_a=1e-7)
    assert threshold.fit["criterion"] == 3.0 and 1e-9 * 1.1 ** threshold.value >= 1e-7
    smooth = time_to_breakdown(tddb_run([1e-9 * (1.1 ** k) for k in range(60)]))
    assert smooth.classification == "no_breakdown"  # a steady rise is not a jump


def test_no_breakdown_is_a_censored_lower_bound() -> None:
    result = time_to_breakdown(tddb_run([2e-6] * 100))
    assert result.outcome == "ok" and result.value == 99.0 and result.bound == "lower"
    assert result.classification == "no_breakdown" and "right-censored" in result.warnings[0]


def test_breakdown_at_the_first_sample_is_flagged() -> None:
    result = time_to_breakdown(tddb_run([1e-3, 1e-3], ["C", "C"]))
    assert result.value == 0.0 and any("before the stress" in w for w in result.warnings)


def test_untrusted_points_before_the_breakdown_refuse() -> None:
    status = ["N"] * 10 + ["X"] + ["N"] * 5 + ["C"]
    run = tddb_run([2e-6] * 16 + [1e-3], status)
    refused = time_to_breakdown(run)
    assert refused.outcome == "refused" and "untrusted" in (refused.error or "")
    forced = time_to_breakdown(run, force=True)
    assert forced.value == 16.0 and forced.forced_on_untrusted
    after = time_to_breakdown(tddb_run([2e-6] * 5 + [1e-3, 1e-3], ["N"] * 5 + ["C", "V"]))
    assert after.outcome == "ok" and after.value == 5.0  # untrusted data after the breakdown do not matter


def test_time_to_breakdown_applies_to_tddb_only_by_recipe_pattern() -> None:
    method = ANALYSIS_METHODS["time_to_breakdown"]
    assert method.applies_to("reliability.tddb_cvs", "smu_sampling")
    assert not method.applies_to("mosfet.idvd", "smu_stepped")


# -- weibull_fit -----------------------------------------------------------------------------------------------------


def weibull_sample(beta: float, eta: float, n: int, seed: int) -> np.ndarray:
    u = np.random.default_rng(seed).random(n)
    return eta * np.power(-np.log1p(-u), 1.0 / beta)


def test_mle_recovers_a_weibull_population() -> None:
    times = weibull_sample(1.5, 1000.0, 400, seed=3)
    beta, eta = weibull_fit(times_s=times)
    assert beta.quantity == "weibull_beta" and beta.value == pytest.approx(1.5, rel=0.08)
    assert eta.quantity == "weibull_eta" and eta.unit == "s" and eta.value == pytest.approx(1000.0, rel=0.06)
    assert beta.fit["n"] == 400 and beta.fit["failures"] == 400 and 0 < beta.fit["beta_se"] < 0.2


def test_right_censoring_is_part_of_the_likelihood() -> None:
    times = weibull_sample(2.0, 500.0, 300, seed=5)
    stop = 450.0
    censored = times > stop
    observed = np.minimum(times, stop)
    beta, eta = weibull_fit(times_s=observed, censored=censored.tolist())
    assert beta.fit["censored"] == censored.sum() > 50
    assert beta.value == pytest.approx(2.0, rel=0.12) and eta.value == pytest.approx(500.0, rel=0.08)
    _, naive_eta = weibull_fit(times_s=observed[~censored])
    assert naive_eta.value < eta.value  # leaving the survivors out underestimates the life


def test_median_ranks_on_complete_data_and_refusal_with_censoring() -> None:
    times = weibull_sample(1.2, 50.0, 200, seed=11)
    beta, eta = weibull_fit(times_s=times, method="rank")
    assert beta.value == pytest.approx(1.2, rel=0.12) and eta.value == pytest.approx(50.0, rel=0.1)
    assert beta.fit["r2"] > 0.95
    refused = weibull_fit(times_s=[1.0, 2.0, 3.0], censored=[False, False, True], method="rank")
    assert {r.outcome for r in refused} == {"refused"}


def test_weibull_needs_two_failures_and_valid_input() -> None:
    assert {r.outcome for r in weibull_fit(times_s=[5.0, 7.0], censored=[False, True])} == {"failed"}
    with pytest.raises(InvalidInputError):
        weibull_fit()
    with pytest.raises(InvalidInputError):
        weibull_fit(times_s=[1.0, -1.0])
    with pytest.raises(InvalidInputError):
        weibull_fit(times_s=[1.0, 2.0], censored=[False])


def test_weibull_over_runs_uses_time_to_breakdown_and_censors_survivors() -> None:
    runs = [tddb_run([2e-6] * k + [1e-3], ["N"] * k + ["C"], run_id=f"S20261119T1000{k:02d}Z-0c0c")
            for k in (5, 12, 30, 44)]
    runs.append(tddb_run([2e-6] * 60, run_id="S20261119T100099Z-0c0c"))  # survived 59 s
    bad = tddb_run([2e-6] * 3 + [1e-3], ["N", "X", "N", "C"], run_id="S20261119T100098Z-0c0c")
    beta, eta = weibull_fit([*runs, bad])
    assert beta.fit["n"] == 5 and beta.fit["failures"] == 4 and beta.fit["censored"] == 1
    assert any("S20261119T100098Z-0c0c left out" in w for w in beta.warnings)
    assert beta.method_record.params["runs"][-1] == "S20261119T100098Z-0c0c"
    assert eta.value > 0 and beta.value > 0


def test_the_simulated_population_has_the_model_weibull_shape() -> None:
    """The dielectric model's sites (seeded unit-exponential draws, ``next_site``) form the Weibull population of
    blueprint 4.2: their lives at a fixed stress recover the model's beta."""
    device = DielectricDevice("dut", DielectricParams(seed=2, weibull_beta=1.5))
    lives = []
    for _ in range(300):
        lives.append(device.t_bd(5.5))
        device.next_site()
    beta, eta = weibull_fit(times_s=lives)
    assert beta.value == pytest.approx(1.5, rel=0.1)
    assert eta.value == pytest.approx(device.eta(5.5), rel=0.1)
    assert math.isfinite(beta.fit["loglik"])
