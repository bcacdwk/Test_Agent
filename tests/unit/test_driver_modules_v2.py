"""v2 module spec rows of ``driver/modules.py`` (blueprint v2 2.5 last bullet): HV-SPGU, SMU pulse, WGFMU, MFCMU,
SCUU, ASU (and the GNDU row kept from v1), each with its manual values and citations, and the per-train checks the
rules use."""

from __future__ import annotations

import pytest

from b1500_test_agent.driver.modules import (
    ASU_SPEC,
    CMU_SPEC,
    MODULE_SPECS,
    SCUU_SPEC,
    SMU_PULSE_SPECS,
    SPGU_SPEC,
    WGFMU_SPEC,
    module_spec,
)
from b1500_test_agent.models.sources import PulseTrain


def spgu_train(**changes: object) -> PulseTrain:
    data: dict[str, object] = {"base_v": 0.0, "peak_v": 4.0, "width_s": 1e-6, "period_s": 1e-4, "count": 1000,
                               "load_ohm": 1e6}
    data.update(changes)
    return PulseTrain.model_validate(data)


def test_spec_values_from_the_manuals() -> None:
    assert (SPGU_SPEC.output_ohm, SPGU_SPEC.max_open_v, SPGU_SPEC.max_matched_v) == (50.0, 40.0, 20.0)
    assert SPGU_SPEC.period_s == (2e-8, 10.0) and SPGU_SPEC.transition_s == (8e-9, 0.4)
    assert SPGU_SPEC.load_ohm == (0.1, 1e6) and SPGU_SPEC.count == (1, 1_000_000)
    assert SMU_PULSE_SPECS["HRSMU"].width_s == (5e-4, 2.0) and SMU_PULSE_SPECS["MPSMU"].period_s == (5e-3, 5.0)
    assert (WGFMU_SPEC.max_vectors, WGFMU_SPEC.max_sequences, WGFMU_SPEC.max_points) == (2048, 512, 4_000_000)
    assert WGFMU_SPEC.grid_s == 1e-8 and WGFMU_SPEC.force_ranges["-10v"] == (-10.0, 0.0)
    assert sorted(WGFMU_SPEC.current_ranges.values()) == [1e-6, 1e-5, 1e-4, 1e-3, 1e-2]
    assert (CMU_SPEC.f_hz, CMU_SPEC.ac_vrms, CMU_SPEC.max_dc_v) == ((1e3, 5e6), (0.01, 0.25), 25.0)
    assert SCUU_SPEC.ssp_resets_smu and ASU_SPEC.lowest_range_a == 1e-12
    assert MODULE_SPECS["GNDU"].max_abs_i == 4.2


def test_module_spec_still_refuses_non_dc_modules() -> None:
    for name in ("MFCMU", "HVSPGU", "WGFMU", "B1525A"):
        with pytest.raises(KeyError):
            module_spec(name)


def test_every_row_cites_the_manual() -> None:
    for text in (*SPGU_SPEC.sources, *WGFMU_SPEC.sources, CMU_SPEC.source, SCUU_SPEC.source, ASU_SPEC.source,
                 *(s.source for s in SMU_PULSE_SPECS.values())):
        assert text.split()[0] in {"PG", "UG", "WG", "WG5"} and " p" in text


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({}, None),
        ({"peak_v": 41.0}, "SPV range"),
        ({"peak_v": 4.0005}, "1 mV"),
        ({"period_s": 1.5e-8, "width_s": 1e-8}, "period"),
        ({"period_s": 1.000005e-4}, "10 ns resolution"),
        ({"width_s": 9.99999e-5}, "period - 10 ns"),
        ({"width_s": 1.001e-6}, "resolution"),
        ({"delay_s": 9.999e-5}, "delay"),
        ({"lead_s": 0.5}, "leading time"),
        ({"trail_s": 3e-9}, "trailing time"),
        ({"lead_s": 9e-9}, "resolution"),
        ({"width_s": 1e-8}, "error 2111"),
        ({"width_s": 9.99e-5, "trail_s": 2e-7}, "error 2112"),
        ({"count": None, "duration_s": 5e7}, "duration"),
        ({"count": None, "duration_s": 1.000000005e-3}, "duration"),
        ({"load_ohm": 0.05}, "SER load"),
    ],
)
def test_spgu_train_problems(changes: dict[str, object], fragment: str | None) -> None:
    problems = SPGU_SPEC.train_problems(spgu_train(**changes))
    if fragment is None:
        assert problems == []
    else:
        assert problems and any(fragment in p.message for p in problems), problems


@pytest.mark.parametrize(
    ("module", "changes", "fragment"),
    [
        ("HRSMU", {}, None),
        ("HRSMU", {"width_s": 4e-4}, "outside"),
        ("HRSMU", {"width_s": 1.05e-3}, "resolution"),
        ("MCSMU", {"width_s": 1e-5}, None),
        ("HRSMU", {"period_s": 6.0, "width_s": 1.0}, "outside"),
        ("HRSMU", {"width_s": 0.2, "period_s": 0.205}, "width + 10 ms"),
        ("HRSMU", {"lead_s": 1e-6}, "transition"),
        ("HRSMU", {"load_ohm": 50.0}, "SER"),
        ("HRSMU", {"delay_s": 2e-3}, "trigger delay"),
    ],
)
def test_smu_pulse_problems(module: str, changes: dict[str, object], fragment: str | None) -> None:
    data: dict[str, object] = {"base_v": 0.0, "peak_v": 1.0, "width_s": 1e-3, "period_s": 1e-2, "count": 10}
    data.update(changes)
    problems = SMU_PULSE_SPECS[module].train_problems(PulseTrain.model_validate(data))
    assert (problems == []) if fragment is None else any(fragment in p.message for p in problems), problems


def test_wgfmu_ranges_by_mode_and_train_grid() -> None:
    assert WGFMU_SPEC.range_bounds("fastiv", "10v") == (0.0, 10.0)
    assert WGFMU_SPEC.range_bounds("pg", "auto") == (-5.0, 5.0)
    assert WGFMU_SPEC.range_bounds("pg", "3v") == (-3.0, 3.0)
    ok = PulseTrain(base_v=0, peak_v=3, width_s=1e-7, period_s=1e-6, count=10)
    assert WGFMU_SPEC.train_problems(ok) == []
    bad = PulseTrain(base_v=0, peak_v=11, width_s=1.5e-8, period_s=1e-6, count=10, load_ohm=50)
    messages = " | ".join(p.message for p in WGFMU_SPEC.train_problems(bad))
    assert "10 V" in messages and "10 ns grid" in messages and "SER" in messages
