"""``diode_fit`` on analytic diode curves (WP2.2): n, Is and Rs from the forward branch, the automatic fit window
(noise and shunt leakage from the reverse branch), compliance exclusion and the trust rules."""

from __future__ import annotations

import math

import numpy as np
import pytest

from b1500_test_agent.analysis.diode import BOLTZMANN_OVER_Q, diode_fit
from tests.unit.analysis_helpers import iv_table, run_of

IS, N, RS, LEAK = 2e-14, 1.08, 15.0, 1e-11
UT = BOLTZMANN_OVER_Q * 300.0


def diode_current(v: np.ndarray, *, i_s: float = IS, n: float = N, rs: float = RS, leak: float = LEAK) -> np.ndarray:
    """Exact anode current at bias ``v`` (Newton on Vj + rs I(Vj) = v)."""
    out = []
    for target in v:
        vj = min(target, 0.75)
        for _ in range(200):
            i = i_s * math.expm1(vj / (n * UT)) + leak * vj
            di = i_s * math.exp(vj / (n * UT)) / (n * UT) + leak
            step = (vj + rs * i - target) / (1 + rs * di)
            vj -= step
            if abs(step) < 1e-15:
                break
        out.append(i_s * math.expm1(vj / (n * UT)) + leak * vj)
    return np.array(out)


def diode_run(v: np.ndarray, current: np.ndarray, status: list[str] | None = None):
    table = iv_table({"anode_V": v}, {"anode_I": current}, status={"anode_I": status} if status else None)
    return run_of(table, "basic.diode_iv")


V = np.linspace(-5.0, 0.8, 291)


def test_n_is_and_rs_are_recovered() -> None:
    n, i_s, rs = diode_fit(diode_run(V, diode_current(V)))
    assert [r.quantity for r in (n, i_s, rs)] == ["n", "is", "rs"]
    assert [r.unit for r in (n, i_s, rs)] == ["1", "A", "Ohm"]
    assert n.value == pytest.approx(N, rel=2e-3)
    assert i_s.value == pytest.approx(IS, rel=0.03)
    assert rs.value == pytest.approx(RS, rel=0.01)
    assert n.window is not None and n.window.low > 0.25 and n.fit["r2"] > 0.9999
    assert n.points_used >= 20 and "outside_window" in n.points_excluded


def test_without_series_resistance_or_reverse_branch() -> None:
    forward = np.linspace(0.05, 0.6, 56)
    n, i_s, rs = diode_fit(diode_run(forward, diode_current(forward, rs=0.0, leak=0.0)))
    assert n.value == pytest.approx(N, rel=1e-4) and i_s.value == pytest.approx(IS, rel=1e-3)
    assert abs(rs.value) < 1.0 and any("Rs" in w for w in rs.warnings)  # no I*Rs drop to resolve Rs
    assert n.fit["i_low"] >= 1e-9  # default window edge without a reverse branch


def test_compliance_points_are_excluded() -> None:
    current = diode_current(V)
    status = ["N"] * V.size
    status[-1], current[-1] = "C", 3e-3  # the last point clamped at the compliance
    n, _, rs = diode_fit(diode_run(V, current, status))
    assert n.points_excluded["C"] == 1 and n.value == pytest.approx(N, rel=2e-3) and rs.value == pytest.approx(
        RS, rel=0.03)


def test_untrusted_and_noise_refuse_and_too_few_points_fail() -> None:
    status = ["N"] * V.size
    status[10] = "X"
    [refused] = diode_fit(diode_run(V, diode_current(V), status))
    assert refused.outcome == "refused" and refused.quantity == "n"
    assert all(r.outcome == "ok" and r.forced_on_untrusted for r in diode_fit(diode_run(V, diode_current(V), status),
                                                                             force=True))
    rng = np.random.default_rng(2)
    [noise] = diode_fit(diode_run(V, 1e-12 * rng.standard_normal(V.size)))
    assert noise.outcome == "refused" and "noise-dominated" in noise.error
    reverse_only = np.linspace(-5.0, 0.2, 53)
    [failed] = diode_fit(diode_run(reverse_only, diode_current(reverse_only)))
    assert failed.outcome == "failed" and "forward point" in failed.error
