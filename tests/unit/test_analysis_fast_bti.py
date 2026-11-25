"""``fast_bti_shift`` (analysis/stress.py; WP10.7) on synthetic fast-BTI tables with known truth: coarse 50 mV sense
staircases of a smooth EKV-like curve rigidly shifted by dVth = A t^n; the local cubic crossing recovers every shift
(where linear interpolation of log Id would be biased), the reference-curve method for spot reads, ``auto``, the read
duration facts and warning, recovery, refusals and unusable calls."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import ANALYSIS_METHODS, fast_bti_shift
from b1500_test_agent.analysis.dataset import RunData, with_trust
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult
from tests.unit.analysis_helpers import ekv_like_id, manifest

pytestmark = pytest.mark.wgfmu

VG = np.round(np.linspace(0.2, 1.0, 17), 9)
A, N = 0.02, 0.2
TIMES = [1e-3 * 10 ** (k / 3) for k in range(16)]
READ_S = 1.88e-5


def curve(vg: np.ndarray) -> np.ndarray:
    return ekv_like_id(vg, vth=0.45, vd=0.1, beta=2e-3)


def found(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def fast_table(stress: Sequence[tuple[float, float]], recovery: Sequence[tuple[float, float]] = (), *,
               spot: float | None = None, status: dict[int, str] | None = None) -> pd.DataFrame:
    """The WGFMU fast-BTI table: reference staircase, then per read one hold row (drain current at 0 V) and the read
    (staircase, or the one level ``spot``) of the curve shifted by dVth."""
    rows: list[dict[str, Any]] = []
    t_stress = stress[-1][0] if stress else 0.0
    plan = [(0.0, 0.0, "reference"), *((t, s, "stress") for t, s in stress),
            *((t_stress + t, s, "recovery") for t, s in recovery)]
    for cycle, (t, shift, kind) in enumerate(plan):
        if kind != "reference":
            rows.append({"t_s": t, "cycle": cycle, "phase": kind, "gate_V": 2.0 if kind == "stress" else 0.0,
                         "drain_V": 0.0, "drain_I": 1e-12, "drain_I_status": "N"})
        levels = VG if spot is None or kind == "reference" else np.array([spot])
        letter = (status or {}).get(cycle, "N")
        for vg, current in zip(levels, curve(levels - shift), strict=True):
            rows.append({"t_s": t, "cycle": cycle, "phase": "read", "gate_V": float(vg), "drain_V": 0.1,
                         "drain_I": float(current), "drain_I_status": letter})
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    return with_trust(table)


def run(table: pd.DataFrame, read_s: float | None = READ_S) -> RunData:
    data = RunData(manifest(recipe_id="wgfmu.fast_bti", kind="stress_measure"), table)
    if read_s is not None:
        data.manifest.kind_result["read_s"] = read_s
    return data


def power(times: Sequence[float]) -> list[tuple[float, float]]:
    return [(t, A * t ** N) for t in times]


def test_registered_for_the_fast_bti_recipe() -> None:
    method = ANALYSIS_METHODS["fast_bti_shift"]
    assert method.status == "implemented" and method.milestone == "M10" and "reliability" in method.families
    assert method.applies_to("wgfmu.fast_bti", "stress_measure")
    assert {"vth_method", "i_crit_a", "w_over_l", "x", "y", "t_min", "t_max", "min_change", "force"} <= set(
        method.options)


def test_the_local_cubic_crossing_recovers_every_shift_of_a_coarse_staircase() -> None:
    results = found(fast_bti_shift(run(fast_table(power(TIMES)))))
    assert results["n"].method_record.params["vth_method"] == "constant_current"
    assert results["n"].value == pytest.approx(N, abs=0.005)
    assert results["a"].value == pytest.approx(A, rel=0.02)
    assert results["dvth"].value == pytest.approx(A * TIMES[-1] ** N, rel=0.005)
    assert results["n"].fit["read_s"] == READ_S and results["n"].fit["read_fraction"] == pytest.approx(READ_S / 1e-3)
    assert results["n"].warnings == [] and results["dvth"].derived


def test_spot_reads_map_onto_the_reference_curve() -> None:
    results = found(fast_bti_shift(run(fast_table(power(TIMES), spot=0.5))))
    assert results["n"].method_record.params["vth_method"] == "reference_curve"
    assert results["n"].value == pytest.approx(N, abs=0.005)
    assert results["dvth"].value == pytest.approx(A * TIMES[-1] ** N, rel=0.005)


def test_the_reference_curve_also_works_for_staircase_reads() -> None:
    results = found(fast_bti_shift(run(fast_table(power(TIMES))), vth_method="reference_curve"))
    assert results["dvth"].value == pytest.approx(A * TIMES[-1] ** N, rel=0.01)


def test_recovery_reads_give_the_recovered_fraction() -> None:
    end = A * TIMES[-1] ** N
    recovery = [(t, end * (1 - 0.1 * np.log10(1 + t))) for t in (1e-3, 1e-2, 0.1, 1.0, 10.0)]
    results = found(fast_bti_shift(run(fast_table(power(TIMES), recovery))))
    assert results["recovery"].value == pytest.approx(0.1 * np.log10(11.0), abs=0.005)
    assert results["recovery_rate"].outcome == "ok"


def test_slow_reads_and_unknown_read_times_are_warned() -> None:
    slow = found(fast_bti_shift(run(fast_table(power(TIMES)), read_s=1e-3)))
    assert any("early reads may include recovery" in w for w in slow["dvth"].warnings)
    unknown = found(fast_bti_shift(run(fast_table(power(TIMES)), read_s=None)))
    assert any("does not record how long each read took" in w for w in unknown["n"].warnings)
    assert "read_s" not in unknown["n"].fit


def test_an_untrusted_reference_read_refuses_unless_forced() -> None:
    """Two saturated points (V) at the top of the reference read: refused; forced, the trusted points serve."""
    table = fast_table(power(TIMES))
    top = (table["cycle"] == 0) & (table["phase"] == "read") & (table["gate_V"] >= 0.95)
    table.loc[top, "drain_I_status"] = "V"
    table = with_trust(table.drop(columns=["trust"]))
    refused = found(fast_bti_shift(run(table)))
    assert refused["n"].outcome == "refused" and refused["dvth"].value is None
    forced = found(fast_bti_shift(run(table), force=True))
    assert forced["n"].outcome == "ok" and forced["n"].forced_on_untrusted


def test_a_criterion_outside_the_reads_fails_with_a_reason() -> None:
    results = found(fast_bti_shift(run(fast_table(power(TIMES))), i_crit_a=1.0))
    assert results["n"].outcome in ("failed", "refused") and "outside" in (results["n"].error or "")


def test_noise_at_the_low_end_does_not_cut_the_curve() -> None:
    """The noise floor at the low end (here alternating 1-2 nA) ends the monotonic stretch there, not at the top."""
    table = fast_table(power(TIMES))
    low = (table["phase"] == "read") & (table["gate_V"] < 0.27)
    table.loc[low, "drain_I"] = np.where(table.loc[low, "step"] % 2 == 0, 2e-9, 1e-9)
    results = found(fast_bti_shift(run(table)))
    assert results["n"].value == pytest.approx(N, abs=0.005) and results["n"].warnings == []


def test_unusable_calls_raise() -> None:
    with pytest.raises(InvalidInputError, match="not a measured column"):
        fast_bti_shift(run(fast_table(power(TIMES))), y="gate_I")
    plain = fast_table(power(TIMES)).drop(columns=["cycle"])
    with pytest.raises(InvalidInputError, match="stress-measure"):
        fast_bti_shift(run(plain))
