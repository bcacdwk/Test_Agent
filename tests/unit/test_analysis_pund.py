"""``pund_polarization`` and ``plot_pund`` (``analysis/pund.py``; WP10.6) against analytic PUND data with known truth:
a Miller-tanh play-operator film (Pr, Ps at the peak field, Vc) plus a linear dielectric, sampled as window means of
the current like the WGFMU (one point per interval), measured on either electrode (sign), with leakage, with a flat
top; endurance series (wake-up, fatigue, cycles to failure); and the refusals (missing geometry, untrusted samples
and ``force``, a table without PUND events) and the registry entries."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import ANALYSIS_METHODS, RunData, run_method, with_trust
from b1500_test_agent.analysis.plots import PlotSet
from b1500_test_agent.analysis.pund import plot_pund, pund_polarization
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.policy import DutGeometry
from b1500_test_agent.models.recipe import QualityCriteria
from tests.unit.analysis_helpers import manifest

pytestmark = pytest.mark.wgfmu

CRITERIA = QualityCriteria(limited=["C", "T"], untrusted=["V", "X", "F", "D", "G", "S", "U"])
AREA_UM2, T_NM = 2500.0, 10.0
AREA_CM2 = AREA_UM2 * 1e-8
GEOMETRY = DutGeometry(area_um2=AREA_UM2, tox_nm=T_NM)
PR, PS, VC = 20.0, 25.0, 1.0          # uC/cm^2, uC/cm^2 (asymptote), V
C_LIN = 66.4e-12                      # F
DELTA = VC / math.log((1 + PR / PS) / (1 - PR / PS))


class Film:
    """Play operator between the Miller branches ``s Ps tanh((V -+ Vc) / 2 delta)`` (fraction of Ps)."""

    def __init__(self, scale: float = 1.0, p: float = 0.0) -> None:
        self.scale = scale
        self.p = p

    def apply(self, v: float) -> float:
        lo = self.scale * math.tanh((v - VC) / (2 * DELTA))
        hi = self.scale * math.tanh((v + VC) / (2 * DELTA))
        self.p = min(max(self.p, lo), hi)
        return self.p


def truth_ps(v_max: float, scale: float = 1.0) -> float:
    return scale * PS * math.tanh((v_max - VC) / (2 * DELTA))


def pund_rows(*, v_max: float = 3.0, rise: float = 1e-5, top: float = 0.0, dt: float = 1e-7, scale: float = 1.0,
              sign: float = -1.0, leak_s: float = 0.0, cycle: int | None = None,
              film: Film | None = None) -> list[dict[str, object]]:
    """Samples of a PUND (preset, P, U, N, D) as window means of the current, ``sign`` -1: measured on the bottom."""
    film = film or Film(scale)
    sub = 20
    rows: list[dict[str, object]] = []
    for name, level in (("preset", -v_max), ("P", v_max), ("U", v_max), ("N", -v_max), ("D", -v_max)):
        span = 2 * rise + top
        n = round(span / dt)
        q_prev = PS * 1e-6 * AREA_CM2 * film.p
        v_prev = 0.0
        for k in range(n):
            charge = 0.0
            for j in range(1, sub + 1):
                t = (k + j / sub) * dt
                v = level * min(t / rise, 1.0, max(0.0, (span - t) / rise))
                q = PS * 1e-6 * AREA_CM2 * film.apply(v) + C_LIN * v
                charge += q - q_prev - C_LIN * v_prev + leak_s * v * dt / sub
                q_prev, v_prev = q - C_LIN * v, v
                q_prev = PS * 1e-6 * AREA_CM2 * film.p
            t_mid = (k + 0.5) * dt
            v_mid = level * min(t_mid / rise, 1.0, max(0.0, (span - t_mid) / rise))
            if name != "preset":
                row: dict[str, object] = {"t_s": t_mid, "event": name, "top_V": v_mid, "bottom_V": 0.0,
                                          "bottom_I": sign * charge / dt, "bottom_I_status": "N"}
                if cycle is not None:
                    row["cycle"] = cycle
                rows.append(row)
        film.apply(0.0)
    return rows


def run_data(rows: list[dict[str, object]], *, geometry: DutGeometry | None = GEOMETRY,
             recipe_id: str = "fecap.pund", kind: str = "wgfmu_waveform") -> RunData:
    table = pd.DataFrame(rows)
    table.insert(0, "step", range(len(table)))
    m = manifest("S20261125T000000Z-aaaa", recipe_id=recipe_id, kind=kind, params={})
    return RunData(manifest=m.model_copy(update={"dut_geometry": geometry}), table=with_trust(table, CRITERIA))


def by(results: list) -> dict:
    return {r.quantity: r for r in results}


def test_pr_ps_ec_of_one_pund_match_the_truth() -> None:
    found = by(pund_polarization(run_data(pund_rows())))
    assert found["pr"].value == pytest.approx(PR, rel=1e-3) and found["pr"].unit == "uC/cm^2"
    assert found["ps"].value == pytest.approx(truth_ps(3.0), rel=1e-3)
    assert found["vc"].value == pytest.approx(VC, rel=0.01) and found["ec"].value == pytest.approx(1.0, rel=0.01)
    assert found["v_imprint"].value == pytest.approx(0.0, abs=0.01)
    assert found["c_lin"].value == pytest.approx(C_LIN, rel=1e-3)
    assert found["q_switch"].value == pytest.approx(2 * PR * 1e-6 * AREA_CM2, rel=1e-3)
    assert found["pr"].derived and found["pr"].window is not None and found["pr"].window.unit == "V"
    assert found["pr"].fit["pr_pos"] == pytest.approx(found["pr"].fit["pr_neg"], rel=1e-3)


@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_the_measured_electrode_does_not_change_the_result(sign: float) -> None:
    found = by(pund_polarization(run_data(pund_rows(sign=sign))))
    assert found["pr"].value == pytest.approx(PR, rel=1e-3) and found["c_lin"].value > 0


def test_a_flat_top_and_a_smaller_amplitude() -> None:
    found = by(pund_polarization(run_data(pund_rows(v_max=2.5, top=5e-6))))
    assert found["pr"].value == pytest.approx(PR * math.tanh(1.5 / (2 * DELTA)) / math.tanh(1.5 / (2 * DELTA)),
                                              rel=1e-3)
    assert found["ps"].value == pytest.approx(truth_ps(2.5), rel=2e-3)
    assert found["vc"].value == pytest.approx(VC, rel=0.01)


def test_leakage_cancels_in_p_minus_u() -> None:
    found = by(pund_polarization(run_data(pund_rows(leak_s=1e-7))))
    assert found["pr"].value == pytest.approx(PR, rel=2e-3)


def test_without_geometry_pr_ps_and_ec_are_refused_naming_the_fields() -> None:
    found = by(pund_polarization(run_data(pund_rows(), geometry=None)))
    assert found["pr"].outcome == "refused" and "geometry.area_um2" in str(found["pr"].error)
    assert found["ec"].outcome == "refused" and "geometry.tox_nm" in str(found["ec"].error)
    assert found["vc"].value == pytest.approx(VC, rel=0.01) and found["q_switch"].outcome == "ok"
    over = by(pund_polarization(run_data(pund_rows(), geometry=None), area_um2=AREA_UM2, thickness_nm=T_NM))
    assert over["pr"].value == pytest.approx(PR, rel=1e-3) and over["ec"].value == pytest.approx(1.0, rel=0.01)


def test_untrusted_samples_refuse_the_read_unless_forced() -> None:
    rows = pund_rows()
    rows[50]["bottom_I_status"] = "V"
    refused = by(pund_polarization(run_data(rows)))
    assert refused["pr"].outcome == "refused" and "status V" in str(refused["pr"].error)
    forced = by(pund_polarization(run_data(rows), force=True))
    assert forced["pr"].outcome == "ok" and forced["pr"].forced_on_untrusted


def test_endurance_reads_give_wake_up_fatigue_and_cycles_to_failure() -> None:
    def scale(n: float) -> float:
        return (1 - 0.15 * math.exp(-n / 100)) / (1 + (n / 1e6) ** 0.5)

    cycles = [1, 10, 100, 1000, 10_000, 100_000, 1_000_000, 10_000_000]
    rows: list[dict[str, object]] = []
    for n in cycles:
        film = Film(scale(n), p=-scale(n) * PR / PS)
        rows += pund_rows(cycle=n, film=film, scale=scale(n))
    found = by(pund_polarization(run_data(rows, recipe_id="fecap.endurance_pund", kind="pulse_read")))
    pr = {n: PR * scale(n) for n in cycles}
    assert found["pr"].value == pytest.approx(pr[cycles[-1]], rel=2e-3) and found["pr"].fit["cycle"] == cycles[-1]
    assert found["pr_initial"].value == pytest.approx(pr[1], rel=2e-3)
    top = max(pr.values())
    assert found["pr_max"].value == pytest.approx(top, rel=2e-3)
    assert found["wake_up"].value == pytest.approx(top / pr[1] - 1, abs=0.005)
    assert found["fatigue"].value == pytest.approx(1 - pr[cycles[-1]] / top, abs=0.005)
    assert 1e5 < found["cycles_to_failure"].value < 1e7 and found["cycles_to_failure"].bound == "exact"


def test_a_series_that_never_fails_gives_a_lower_bound() -> None:
    rows = [r for n in (1, 10, 100) for r in pund_rows(cycle=n)]
    found = by(pund_polarization(run_data(rows, recipe_id="fecap.endurance_pund", kind="pulse_read")))
    assert found["cycles_to_failure"].bound == "lower" and found["cycles_to_failure"].value == 100


def test_unusable_calls() -> None:
    table = run_data(pund_rows())
    with pytest.raises(InvalidInputError, match="c_window"):
        pund_polarization(table, c_window=(0.6, 0.5))
    plain = run_data([{**r, "event": "x"} for r in pund_rows()])
    with pytest.raises(InvalidInputError, match="a PUND read has"):
        pund_polarization(plain)


def test_plot_pund_writes_the_figures(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rows = [r for n in (1, 10) for r in pund_rows(cycle=n)]
    paths = plot_pund(run_data(rows, recipe_id="fecap.endurance_pund", kind="pulse_read"), out_dir=tmp_path)
    assert [p.name for p in paths] == ["pund-current.png", "pund-loop.png", "pund-endurance.png"]
    assert all(p.read_bytes().startswith(b"\x89PNG") for p in paths)
    rendered = run_method("plot_pund", run_data(pund_rows()))
    assert isinstance(rendered, PlotSet) and [p.name for p in rendered.plots] == ["pund-current", "pund-loop"]


def test_registry_entries() -> None:
    for name in ("pund_polarization", "plot_pund"):
        method = ANALYSIS_METHODS[name]
        assert method.families == ("nvm",) and method.applies_to("fecap.pund", "wgfmu_waveform")
        assert method.applies_to("fecap.endurance_pund", "pulse_read")
    assert ANALYSIS_METHODS["memory_window_pulse"].applies_to("fefet.fast_program_read", "wgfmu_waveform")
    assert np.isfinite(by(run_method("pund_polarization", run_data(pund_rows())))["pr"].value)  # type: ignore[arg-type]
