"""The v1 MOSFET extraction on real lab data (blueprint v2 10.2 row 6.2 AC "real-data Vth stable across methods").

The fixture ``tests/fixtures/lab/idvg_real.csv`` is one Id-Vg curve of the lab's transistor (lwp ``test_IdVg.m``:
Vd 0.1 V, gate -2..2 V in 61 steps, 1 PLC): a slow, thin-film-like device (SS about 212 mV/dec, gm peaking at
0.36 uS near Vg 0.7 V, then rolling off through about 77 kOhm of series resistance), off state at the +-2e-13 A
floor. Every method must run on it without refusal (the lab dropped the status codes, so the rows count as ``N``).

Stated spread: the three v1 threshold definitions (linear extrapolation at max gm minus Vd/2, maximum gm change
minus Vd/2, constant current) agree within **0.10 V** (measured 0.086 V: 0.296 / 0.349 / 0.382 V). The constant-
current criterion is **10 nA**: no geometry is recorded for this device (so no W/L scaling), and 10 nA is the drain
current at threshold of this curve (Id at the extrapolated Vth = 15 nA). The recipe default of 100 nA lies 0.39 V
higher, well inside the linear region of this low-gm device: there it measures a different thing (asserted below,
so a change of the default or of the curve cannot slip through), not a spread of the methods.
"""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.analysis import mosfet
from b1500_test_agent.models.analysis import ExtractionResult
from tests.unit.lab_fixtures import real_idvg, real_idvg_run

pytestmark = pytest.mark.smu

VTH_SPREAD_V = 0.10
"""Stated agreement of the three Vth methods on the lab curve (max - min)."""

I_CRIT_A = 1e-8
"""Constant-current criterion for this device (module docstring)."""

EXPECTED = {"vth_linear_extrapolation": 0.3489, "vth_max_gm": 0.3821, "vth_constant_current": 0.2964}
"""Values on the lab curve (V), pinned to 2 mV: a regression guard of the extraction code on real data."""


def single(result: ExtractionResult | list[ExtractionResult]) -> ExtractionResult:
    return result[0] if isinstance(result, list) else result


def vth_by_method() -> dict[str, ExtractionResult]:
    data = real_idvg_run()
    return {
        "vth_linear_extrapolation": single(mosfet.vth_linear_extrapolation(data)),
        "vth_max_gm": single(mosfet.vth_max_gm(data)),
        "vth_constant_current": single(mosfet.vth_constant_current(data, i_crit_a=I_CRIT_A)),
    }


def test_every_vth_method_runs_on_the_real_curve_without_refusal() -> None:
    for name, result in vth_by_method().items():
        assert result.outcome == "ok" and result.value is not None and result.unit == "V", (name, result.error)
        assert not result.forced_on_untrusted and result.derived, name
        assert result.points_used >= 2, name


def test_real_data_vth_is_stable_across_the_three_methods() -> None:
    values = {name: float(result.value) for name, result in vth_by_method().items()}  # type: ignore[arg-type]
    assert max(values.values()) - min(values.values()) <= VTH_SPREAD_V, values
    for name, expected in EXPECTED.items():
        assert values[name] == pytest.approx(expected, abs=2e-3), name


def test_the_constant_current_criterion_sits_at_the_current_at_threshold() -> None:
    """Why 10 nA: the drain current at the extrapolated Vth is 10-20 nA on this curve; the 100 nA default reads
    a gate voltage in the linear region, far above every other definition."""
    table = real_idvg()
    vth = float(vth_by_method()["vth_linear_extrapolation"].value)  # type: ignore[arg-type]
    id_at_vth = float(np.exp(np.interp(vth, table["V_G"], np.log(table["I_D"].clip(lower=1e-15)))))
    assert 1e-8 <= id_at_vth <= 2e-8
    default = single(mosfet.vth_constant_current(real_idvg_run()))
    assert default.outcome == "ok" and float(default.value) > vth + 0.3  # type: ignore[arg-type]


def test_subthreshold_swing_and_gm_max_of_the_real_curve() -> None:
    data = real_idvg_run()
    ss = single(mosfet.subthreshold_swing(data))
    assert ss.outcome == "ok" and ss.unit == "mV/dec" and float(ss.value) == pytest.approx(212.2, abs=1.0)  # type: ignore[arg-type]
    gm = single(mosfet.gm_max(data))
    assert gm.outcome == "ok" and float(gm.value) == pytest.approx(3.558e-7, rel=0.01)  # type: ignore[arg-type]
