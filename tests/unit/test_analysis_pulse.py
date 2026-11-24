"""Pulsed I-V analyses (``analysis/pulse.py``, WP7.3) on analytic tables with known truth, and the registry's two-run
methods (``options.reference_run``): ``pulsed_vs_dc`` (difference, ratio, largest relative difference; bias mismatch,
untrusted rows, families) and ``pulse_plateau`` (time-resolved pulses with edge trimming, one row per pulse)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis.dataset import RunData, with_trust
from b1500_test_agent.analysis.pulse import pulse_plateau, pulsed_vs_dc
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS, REFERENCE_OPTION, run_method
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import idvg_table, manifest, write_run

pytestmark = pytest.mark.smu

PULSED_ID = "S20261122T010000Z-0a01"
DC_ID = "S20261122T005900Z-0a02"
VG = np.linspace(0.0, 3.0, 31)
COLD = 1e-4 * np.clip(VG - 0.5, 0.0, None) ** 2  # isothermal current
HOT = COLD * (1.0 - 0.05 * VG)  # DC loses up to 15 % at 3 V (self-heating grows with power)


def run(table: pd.DataFrame, run_id: str, recipe_id: str, kind: str, drain_v: float = 1.0) -> RunData:
    table = table.drop(columns=["trust"]).assign(drain_V=drain_v)
    return RunData(manifest(run_id, recipe_id=recipe_id, kind=kind), with_trust(table))


def pulsed(current: np.ndarray = COLD, **kw: object) -> RunData:
    return run(idvg_table(VG, current, **kw), PULSED_ID, "mosfet.idvg_pulsed", "smu_pulsed")


def dc(current: np.ndarray = HOT, vg: np.ndarray = VG, drain_v: float = 1.0) -> RunData:
    return run(idvg_table(vg, current), DC_ID, "mosfet.idvg", "smu_staircase", drain_v)


def test_pulsed_minus_dc_at_the_highest_current() -> None:
    results = {r.quantity: r for r in pulsed_vs_dc(pulsed(), reference=dc())}
    delta = results["pulsed_minus_dc"]
    assert delta.value == pytest.approx(COLD[-1] - HOT[-1]) and delta.unit == "A" and delta.fit["v"] == 3.0
    assert results["pulsed_over_dc"].value == pytest.approx(1 / 0.85)
    worst = results["max_rel_difference"]
    assert worst.value == pytest.approx(0.15 / 0.85) and worst.fit["v_at_max"] == 3.0
    assert delta.window is not None and (delta.window.low, delta.window.high) == (0.0, 3.0)
    at = {r.quantity: r for r in pulsed_vs_dc(pulsed(), reference=dc(), v=2.0)}
    assert at["pulsed_minus_dc"].value == pytest.approx(1e-4 * 2.25 * 0.1)


def test_the_reference_is_interpolated_on_its_own_grid() -> None:
    fine = np.linspace(0.0, 3.0, 301)
    ref = dc(1e-4 * np.clip(fine - 0.5, 0.0, None) ** 2 * (1.0 - 0.05 * fine), fine)
    delta = next(r for r in pulsed_vs_dc(pulsed(), reference=ref) if r.quantity == "pulsed_minus_dc")
    assert delta.value == pytest.approx(COLD[-1] - HOT[-1], rel=1e-9)


def test_other_bias_conditions_fail_and_untrusted_rows_refuse() -> None:
    results = pulsed_vs_dc(pulsed(), reference=dc(drain_v=0.05))
    assert {r.outcome for r in results} == {"failed"} and "drain_V 1 vs 0.05" in (results[0].error or "")
    status = ["N"] * 31
    status[10] = "X"
    refused = pulsed_vs_dc(pulsed(drain_status=status), reference=dc())
    assert {r.outcome for r in refused} == {"refused"}
    forced = pulsed_vs_dc(pulsed(drain_status=status), reference=dc(), force=True)
    assert all(r.forced_on_untrusted for r in forced)
    no_drain = RunData(dc().manifest, dc().table.drop(columns=["drain_I", "drain_I_status"]))
    with pytest.raises(InvalidInputError, match="reference run"):
        pulsed_vs_dc(pulsed(), reference=no_drain)


def test_a_family_compares_one_curve() -> None:
    vd = np.tile(np.linspace(0.0, 3.0, 11), 2)
    vg = np.repeat([1.0, 2.0], 11)
    current = 1e-4 * vd * vg

    def family(scale: float, run_id: str, kind: str) -> RunData:
        table = pd.DataFrame({"step": np.arange(22), "drain_V": vd, "gate_V": vg, "drain_I": current * scale,
                              "drain_I_status": ["N"] * 22})
        return RunData(manifest(run_id, recipe_id="mosfet.idvd_pulsed" if kind == "smu_pulsed" else "mosfet.idvd",
                                kind=kind), with_trust(table))

    results = {r.quantity: r for r in pulsed_vs_dc(family(1.0, PULSED_ID, "smu_pulsed"),
                                                   reference=family(0.9, DC_ID, "smu_stepped"))}
    delta = results["pulsed_minus_dc"]
    assert delta.fit["curve"] == 2.0 and delta.value == pytest.approx(0.1 * 1e-4 * 3.0 * 2.0)
    low = {r.quantity: r for r in pulsed_vs_dc(family(1.0, PULSED_ID, "smu_pulsed"),
                                               reference=family(0.9, DC_ID, "smu_stepped"), curve=1.0)}
    assert low["pulsed_minus_dc"].value == pytest.approx(0.1 * 1e-4 * 3.0)


def test_pulse_plateau_of_a_time_resolved_train() -> None:
    """Three 1 V/2 V/3 V pulses of 10 samples on a 0 V base; the current settles after two samples (edge 0.2 drops
    them) to 1 mA per volt."""
    rows: list[dict[str, float | str]] = [{"t_s": k * 1e-6, "gate_V": 0.0, "gate_I": 0.0} for k in range(5)]
    t = 5e-6
    for level in (1.0, 2.0, 3.0):
        for k in range(10):
            current = level * 1e-3 * (0.5 if k < 2 else 1.0)
            rows.append({"t_s": t, "gate_V": level, "gate_I": current})
            t += 1e-6
        for _ in range(5):
            rows.append({"t_s": t, "gate_V": 0.0, "gate_I": 0.0})
            t += 1e-6
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    table["gate_I_status"] = "N"
    data = RunData(manifest(recipe_id="generic.smu_multi_pulsed", kind="smu_pulsed"), with_trust(table))
    top = pulse_plateau(data)
    assert top.quantity == "plateau_current" and top.value == pytest.approx(3e-3)
    assert top.fit["pulses"] == 3 and top.fit["level_v"] == 3.0 and top.fit["samples"] == 6
    assert top.window is not None and top.fit["plateau_s"] == pytest.approx(5e-6)
    assert pulse_plateau(data, pulse=0).value == pytest.approx(1e-3)
    assert pulse_plateau(data, v=1.5).value == pytest.approx(1.5e-3)
    assert pulse_plateau(data, v=4.0).outcome == "failed"


def test_pulse_plateau_splits_wgfmu_trains_by_cycle() -> None:
    """WP10.4: a WGFMU pulse train samples only the flat tops, so consecutive pulses touch (same level, one event
    name): the ``cycle`` column (pattern repeat) separates them; a pulsed sweep has one row per cycle."""
    rows = []
    for cycle, current in enumerate((1e-4, 2e-4, 3e-4)):
        for k in range(5):
            rows.append({"t_s": cycle * 1e-4 + k * 1e-6, "cycle": cycle, "event": "pulse", "gate_V": 2.0,
                         "drain_I": current * (0.5 if k == 0 else 1.0)})
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    table["drain_I_status"] = "N"
    data = RunData(manifest(recipe_id="wgfmu.pulse_train", kind="wgfmu_waveform"), with_trust(table))
    last = pulse_plateau(data, x="gate_V", y="drain_I")
    assert last.fit["pulses"] == 3 and last.value == pytest.approx(3e-4) and last.fit["samples"] == 3
    assert pulse_plateau(data, x="gate_V", y="drain_I", pulse=0).value == pytest.approx(1e-4)
    sweep = pd.DataFrame({"step": np.arange(3), "t_s": [1e-5, 1e-3, 2e-3], "cycle": [0, 1, 2],
                          "event": ["plateau"] * 3, "gate_V": [0.5, 1.0, 1.5], "drain_I": [1e-6, 2e-5, 6e-5],
                          "drain_I_status": ["N"] * 3})
    data = RunData(manifest(recipe_id="wgfmu.pulsed_iv", kind="wgfmu_waveform"), with_trust(sweep))
    result = pulse_plateau(data, x="gate_V", y="drain_I")
    assert result.fit["pulses"] == 3 and result.fit["level_v"] == 1.5 and result.value == pytest.approx(6e-5)
    assert pulse_plateau(data, x="gate_V", y="drain_I", v=0.75).value == pytest.approx(1.05e-5)


def test_pulse_plateau_of_one_reading_per_pulse() -> None:
    data = pulsed()
    result = pulse_plateau(data, x="gate_V", y="drain_I", v=2.0)
    assert result.value == pytest.approx(1e-4 * 2.25) and result.fit["samples"] == 1
    assert pulse_plateau(data, x="gate_V", y="drain_I").fit["level_v"] == 3.0


def test_registry_two_run_methods_take_the_reference_run_option(tmp_path: Path) -> None:
    method = ANALYSIS_METHODS["pulsed_vs_dc"]
    assert method.two_run and method.options[0] == REFERENCE_OPTION and "reference" not in method.options
    assert not ANALYSIS_METHODS["pulse_plateau"].two_run
    loaded: list[str] = []

    def loader(run_id: str) -> RunData:
        loaded.append(run_id)
        return dc()

    out = run_method("pulsed_vs_dc", pulsed(), {REFERENCE_OPTION: DC_ID}, load_reference=loader)
    assert loaded == [DC_ID] and {r.outcome for r in out} == {"ok"}  # type: ignore[union-attr]
    with pytest.raises(InvalidInputError, match="reference_run"):
        run_method("pulsed_vs_dc", pulsed(), {}, load_reference=loader)
    with pytest.raises(InvalidInputError, match="another run"):
        run_method("pulsed_vs_dc", pulsed(), {REFERENCE_OPTION: PULSED_ID}, load_reference=loader)
    # without a loader the reference comes from the data root of the run itself
    root = tmp_path / "data"
    write_run(root, dc().table, dc().manifest)
    folder = write_run(root, pulsed().table, pulsed().manifest)
    on_disk = RunData(pulsed().manifest, pulsed().table, path=folder)
    out = run_method("pulsed_vs_dc", on_disk, {REFERENCE_OPTION: DC_ID})
    assert {r.outcome for r in out} == {"ok"}  # type: ignore[union-attr]
    with pytest.raises(InvalidInputError):
        run_method("pulse_plateau", pulsed(), {REFERENCE_OPTION: DC_ID})
