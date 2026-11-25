"""Stress-measure analysis on synthetic tables with known truth (WP7.6, blueprint v2 2.10): ``bti_power_law``,
``degradation_vs_time`` and ``silc`` (analysis/stress.py): the read grouping, the power law, the stretched exponential,
the recovery, the SILC threshold and q_inj, refusals and unusable calls."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import ANALYSIS_METHODS, bti_power_law, degradation_vs_time, silc, stress_reads
from b1500_test_agent.analysis.dataset import with_trust
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, Quantity
from tests.unit.analysis_helpers import linear_region_id, run_of, subthreshold_id

pytestmark = pytest.mark.smu

VG = np.round(np.linspace(-0.2, 1.5, 35), 9)
V0 = 0.3  # subthreshold_id crosses its i0 = 100 nA at v0: the constant-current Vth of an unshifted read


def found(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def stress_table(stress: Sequence[tuple[float, float]], recovery: Sequence[tuple[float, float]] = (), *,
                 status: dict[int, str] | None = None, monitor_a: float = 1e-11,
                 curve: Callable[[np.ndarray], np.ndarray] | None = None) -> pd.DataFrame:
    """A stress-measure table: the reference read (t 0, shift 0), then per stress read ``(t, dVth)`` one hold row
    (phase stress, gate at 2 V) and an Id-Vg read whose curve is shifted by dVth; recovery reads ``(t_rec, dVth)``
    after recovery hold rows (gate at 0 V). ``status`` sets the drain status of read ``cycle`` (all its points)."""
    rows: list[dict[str, Any]] = []
    t_stress = stress[-1][0] if stress else 0.0
    plan = [(0.0, 0.0, "reference"), *((t, s, "stress") for t, s in stress),
            *((t_stress + t, s, "recovery") for t, s in recovery)]
    for cycle, (t, shift, kind) in enumerate(plan):
        if kind != "reference":
            level = 2.0 if kind == "stress" else 0.0
            rows.append({"t_s": t, "cycle": cycle, "phase": kind, "gate_V": level, "drain_V": 0.0,
                         "gate_I": monitor_a, "gate_I_status": "N", "drain_I": 0.0, "drain_I_status": "N"})
        letter = (status or {}).get(cycle, "N")
        currents = subthreshold_id(VG - shift, v0=V0) if curve is None else curve(VG - shift)
        for vg, current in zip(VG, currents, strict=True):
            rows.append({"t_s": t, "cycle": cycle, "phase": "read", "gate_V": vg, "drain_V": 0.05, "gate_I": 1e-13,
                         "gate_I_status": "N", "drain_I": current, "drain_I_status": letter})
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    return with_trust(table)


def bti_run(table: pd.DataFrame, recipe_id: str = "reliability.bti_sms") -> Any:
    return run_of(table, recipe_id, kind="stress_measure", params={"vd": Quantity(value=0.05, unit="V")})


def power(a: float, n: float, times: Sequence[float]) -> list[tuple[float, float]]:
    return [(t, a * t**n) for t in times]


TIMES = [1.0, 2.15, 4.64, 10.0, 21.54, 46.42, 100.0, 215.44, 464.16, 1000.0]


# -- reads -----------------------------------------------------------------------------------------------------------


def test_reads_are_grouped_by_cycle_and_classified_by_their_hold_rows() -> None:
    d = bti_run(stress_table(power(0.02, 0.2, [1.0, 10.0]), [(1.0, 0.03), (10.0, 0.02)]))
    reads = stress_reads(d, "test")
    assert [(r.cycle, r.kind, r.t_s, len(r.rows)) for r in reads] == [
        (0, "reference", 0.0, 35), (1, "stress", 1.0, 35), (2, "stress", 10.0, 35), (3, "recovery", 11.0, 35),
        (4, "recovery", 20.0, 35)]


def test_a_table_without_the_stress_measure_columns_is_an_unusable_call() -> None:
    table = stress_table(power(0.02, 0.2, TIMES)).drop(columns=["cycle"])
    with pytest.raises(InvalidInputError, match="kind stress_measure"):
        bti_power_law(bti_run(table))


# -- bti_power_law ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sign", [1.0, -1.0], ids=["pbti", "nbti"])
def test_bti_power_law_recovers_n_and_a(sign: float) -> None:
    shifts = [(t, sign * s) for t, s in power(0.02, 0.2, TIMES)]
    out = found(bti_power_law(bti_run(stress_table(shifts))))
    assert out["n"].value == pytest.approx(0.2, abs=1e-4) and out["a"].value == pytest.approx(0.02, rel=1e-3)
    assert out["dvth"].value == pytest.approx(sign * 0.02 * 1000.0**0.2, rel=1e-3)
    assert out["n"].derived and out["n"].points_used == 10 and out["n"].fit["r2"] > 0.9999
    assert out["n"].fit["vth0_v"] == pytest.approx(V0, abs=1e-4)  # log interpolation of the saturating curve
    assert "recovery" not in out


def test_bti_recovery_fraction_and_rate() -> None:
    end = 0.02 * 1000.0**0.2
    recovery = [(t, end * (1.0 - 0.1 * math.log10(t))) for t in (1.0, 10.0, 100.0, 1000.0)]
    out = found(bti_power_law(bti_run(stress_table(power(0.02, 0.2, TIMES), recovery))))
    assert out["recovery"].value == pytest.approx(0.3, abs=1e-4)
    assert out["recovery_rate"].value == pytest.approx(0.1, abs=1e-4)
    assert out["n"].value == pytest.approx(0.2, abs=1e-4)  # the recovery reads never enter the stress fit


def test_bti_reads_below_min_change_are_left_out_of_the_fit() -> None:
    small = bti_run(stress_table(power(0.0002, 0.2, TIMES)))  # 0.2 mV at 1 s, 0.8 mV at 1000 s
    out = found(bti_power_law(small))
    assert out["n"].outcome == "failed" and "at least 0.001" in (out["n"].error or "")
    assert out["dvth"].outcome == "ok"  # the shift itself is still reported
    tuned = found(bti_power_law(small, min_change=1e-4))
    assert tuned["n"].value == pytest.approx(0.2, abs=0.01) and tuned["n"].points_used == 10


def test_an_untrusted_read_drops_out_and_an_untrusted_reference_refuses() -> None:
    out = found(bti_power_law(bti_run(stress_table(power(0.02, 0.2, TIMES), status={3: "X"}))))
    assert out["n"].value == pytest.approx(0.2, abs=1e-4) and out["n"].points_used == 9
    assert any("t_s = 4.64 s left out" in w for w in out["n"].warnings)
    refused = found(bti_power_law(bti_run(stress_table(power(0.02, 0.2, TIMES), status={0: "X"}))))
    assert {r.outcome for r in refused.values()} == {"refused"}
    table = stress_table(power(0.02, 0.2, TIMES))
    table.loc[table.index[table["cycle"] == 0][-1], "drain_I_status"] = "X"  # one untrusted point, far from Vth
    forced = found(bti_power_law(bti_run(with_trust(table.drop(columns=["trust"]))), force=True))
    assert forced["n"].value == pytest.approx(0.2, abs=1e-4) and forced["n"].forced_on_untrusted


def test_a_limited_read_point_never_enters_the_threshold() -> None:
    table = stress_table(power(0.02, 0.2, TIMES))
    last = table.index[table["cycle"] == 10][-1]  # the top of the last read (far above the 100 nA crossing)
    table.loc[last, "drain_I_status"] = "C"
    out = found(bti_power_law(bti_run(with_trust(table.drop(columns=["trust"])))))
    assert out["n"].value == pytest.approx(0.2, abs=1e-4)


def test_linear_extrapolation_gives_the_same_shift() -> None:
    """Linear-region curves (``linear_region_id``: exactly linear above Vth + Vd): the max-gm tangent intercept shifts
    with the curve, so the extrapolated Vth recovers the power law too."""
    table = stress_table(power(0.02, 0.2, TIMES), curve=lambda vg: linear_region_id(vg, vth=0.42))
    out = found(bti_power_law(bti_run(table), vth_method="linear_extrapolation"))
    assert out["n"].value == pytest.approx(0.2, abs=2e-3) and out["n"].fit["vth0_v"] == pytest.approx(0.42, abs=1e-6)


# -- degradation_vs_time ---------------------------------------------------------------------------------------------


def spot_table(values: Sequence[tuple[float, float]], *, samples: int = 3, noise: float = 0.0) -> pd.DataFrame:
    """Spot reads of ``drain_I`` at gate 1.5 V: the reference ``values[0]`` at t 0, then ``(t, Id)`` per read, each
    read ``samples`` rows (with a deterministic +-noise pattern), one hold row before every later read."""
    rows: list[dict[str, Any]] = []
    for cycle, (t, current) in enumerate(values):
        if cycle:
            rows.append({"t_s": t, "cycle": cycle, "phase": "stress", "gate_V": 1.2, "drain_V": 2.5,
                         "drain_I": 4e-4, "drain_I_status": "N"})
        for k in range(samples):
            rows.append({"t_s": t, "cycle": cycle, "phase": "read", "gate_V": 1.5, "drain_V": 0.05,
                         "drain_I": current * (1.0 + noise * (k - (samples - 1) / 2)), "drain_I_status": "N"})
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    return with_trust(table)


def test_hci_power_law_of_the_relative_drain_current() -> None:
    i0 = 8e-5
    values = [(0.0, i0), *((t, i0 * (1.0 - 6.6e-3 * t**0.45)) for t in TIMES)]
    out = found(degradation_vs_time(run_of(spot_table(values, noise=1e-5), "reliability.hci", kind="stress_measure"),
                                    quantity="id", y="drain_I"))
    assert out["m"].value == pytest.approx(0.45, abs=1e-3) and out["b"].value == pytest.approx(-6.6e-3, rel=1e-2)
    assert out["delta"].value == pytest.approx(-6.6e-3 * 1000.0**0.45, rel=1e-3) and out["delta"].unit == "1"


def test_a_sweep_read_needs_at_v_for_a_current() -> None:
    d = bti_run(stress_table(power(0.02, 0.2, TIMES)))
    with pytest.raises(InvalidInputError, match="at_v"):
        degradation_vs_time(d, quantity="id")
    out = found(degradation_vs_time(d, quantity="id", at_v=0.5))
    assert out["delta"].value is not None and out["delta"].value < 0  # Vth up: Id at 0.5 V down


def test_stretched_exponential_of_the_threshold_shift() -> None:
    shifts = [(t, 0.15 * (1.0 - math.exp(-((t / 4.0) ** 0.5)))) for t in log_grid(0.1, 300.0, 4)]
    out = found(degradation_vs_time(bti_run(stress_table(shifts), "igzo.bias_stress"), quantity="vth",
                                    fit="stretched_exp"))
    assert out["tau"].value == pytest.approx(4.0, rel=0.02) and out["beta"].value == pytest.approx(0.5, abs=0.01)
    assert out["delta_inf"].value == pytest.approx(0.15, rel=0.01) and out["delta_inf"].unit == "V"
    few = found(degradation_vs_time(bti_run(stress_table(shifts[:5]), "igzo.bias_stress"), quantity="vth",
                                    fit="stretched_exp"))
    assert few["tau"].outcome == "failed" and "8 points" in (few["tau"].error or "")


def log_grid(first: float, last: float, per_decade: int) -> list[float]:
    out, k = [], 0
    while (t := round(first * 10 ** (k / per_decade), 2)) < last:
        out.append(t)
        k += 1
    return [*out, last]


# -- silc ------------------------------------------------------------------------------------------------------------


def silc_table(i0: float, ratios: Sequence[tuple[float, float]], *, stress_a: float = 5e-11) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    plan = [(0.0, 0.0), *ratios]
    for cycle, (t, ratio) in enumerate(plan):
        if cycle:
            rows.append({"t_s": t, "cycle": cycle, "phase": "stress", "gate_V": 2.8, "gate_I": stress_a,
                         "gate_I_status": "N"})
        for k in range(5):
            rows.append({"t_s": t, "cycle": cycle, "phase": "read", "gate_V": 1.5,
                         "gate_I": i0 * (1.0 + ratio) * (1.0 + 1e-3 * (k - 2)), "gate_I_status": "N"})
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    return with_trust(table)


def test_silc_ratio_exponent_and_injected_charge() -> None:
    ratios = [(t, 0.01 * t**0.5) for t in TIMES]
    d = run_of(silc_table(1.5e-11, ratios), "reliability.silc", kind="stress_measure",
               params={"v_sense": Quantity(value=1.5, unit="V")})
    out = found(silc(d))
    assert out["ig0"].value == pytest.approx(1.5e-11, rel=1e-6) and out["ig0"].unit == "A"
    assert out["silc_ratio"].value == pytest.approx(0.01 * 1000.0**0.5, rel=1e-6)
    assert out["silc_exponent"].value == pytest.approx(0.5, abs=1e-3)
    assert out["silc_exponent"].points_used == 8  # the 1 s and 2.15 s reads (1 %, 1.5 %) are below 2 %
    assert out["q_inj"].value == pytest.approx(5e-11 * 1000.0, rel=1e-6) and out["q_inj"].unit == "C"
    assert out["ig0"].fit["v_sense_v"] == 1.5


def test_registry_entries() -> None:
    for name in ("bti_power_law", "degradation_vs_time", "silc"):
        method = ANALYSIS_METHODS[name]
        assert method.families == ("reliability",) and method.kinds == (
            "stress_measure",) and method.milestone == "M7"
    assert ANALYSIS_METHODS["bti_power_law"].applies_to("reliability.bti_sms", "stress_measure")
    assert ANALYSIS_METHODS["degradation_vs_time"].applies_to("igzo.bias_stress", "stress_measure")
    assert ANALYSIS_METHODS["silc"].applies_to("reliability.silc", "stress_measure")
    assert not ANALYSIS_METHODS["silc"].applies_to("mosfet.idvg", "smu_staircase")
