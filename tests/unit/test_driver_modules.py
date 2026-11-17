"""Module spec table (driver/modules.py) against the manual tables, the R-LIM-01 check and range-code mapping."""

from __future__ import annotations

import pytest

from b1500_test_agent.driver import commands
from b1500_test_agent.driver.modules import (
    I_RANGE_FULL_SCALE,
    MODULE_SPECS,
    V_RANGE_FULL_SCALE,
    module_spec,
    range_full_scale,
    ranging_code,
    violations,
)
from b1500_test_agent.models.measurement import Ranging
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL, SMU_TYPES


def test_every_smu_type_and_the_gndu_have_a_spec() -> None:
    assert set(MODULE_SPECS) == set(SMU_TYPES) | {"GNDU"}
    for model, module_type in MODULE_TYPE_BY_MODEL.items():
        if module_type in SMU_TYPES:
            spec = module_spec(model)
            assert spec.module_type == module_type and model in spec.models
    assert module_spec("HRSMU") is module_spec("B1517A")
    for unknown in ("B1520A", "MFCMU", "WGFMU", "B1530A", "B1525A", "XYZ"):
        with pytest.raises(KeyError):
            module_spec(unknown)


@pytest.mark.parametrize(
    ("name", "max_v", "max_i", "power_w", "slots"),
    [
        ("HPSMU", 200, 1.0, 20, 2),  # UG PDF 60
        ("MPSMU", 100, 0.1, 2, 1),  # UG PDF 63
        ("HRSMU", 100, 0.1, 2, 1),  # UG PDF 69
        ("MCSMU", 30, 0.1, 3, 1),  # UG PDF 67 (DC)
        ("HCSMU", 40, 1.0, 40, 2),  # PG Table 4-9 (DC), Pcomp max 40 W (PDF 569)
        ("HVSMU", 3000, 0.008, 12, 2),  # PG Table 4-12
        ("GNDU", 0, 4.2, 0, 1),  # UG PDF 58
    ],
)
def test_headline_limits(name: str, max_v: float, max_i: float, power_w: float, slots: int) -> None:
    spec = MODULE_SPECS[name]
    assert (spec.max_abs_v, spec.max_abs_i, spec.slots) == (max_v, max_i, slots)
    assert spec.max_power_w == pytest.approx(power_w)
    assert max(v for v, _ in spec.v_source_envelope) == max_v
    assert max(i for _, i in spec.v_source_envelope) == max_i


def test_envelopes_are_monotonic_staircases() -> None:
    for spec in MODULE_SPECS.values():
        for envelope in (spec.v_source_envelope, spec.i_source_envelope):
            levels = [a for a, _ in envelope]
            others = [b for _, b in envelope]
            assert levels == sorted(levels) and others == sorted(others, reverse=True), spec.module_type


@pytest.mark.parametrize(
    ("name", "v", "i", "ok"),
    [
        ("HRSMU", 20, 0.1, True),  # PG Table 4-7: up to 20 V at 100 mA
        ("HRSMU", 20.5, 0.1, False),
        ("HRSMU", 40, 0.05, True),
        ("HRSMU", 40, 0.051, False),
        ("HRSMU", 100, 0.02, True),
        ("HRSMU", -100, -0.02, True),
        ("HRSMU", 100.1, 1e-6, False),
        ("MPSMU", 3.0, 0.02, True),  # the S4 scenario's 20 mA at 3 V is inside the module
        ("MPSMU", 0.0, 0.11, False),
        ("HPSMU", 20, 1.0, True),
        ("HPSMU", 100, 0.125, True),
        ("HPSMU", 150, 0.06, False),
        ("HPSMU", 200, 0.05, True),
        ("MCSMU", 30, 0.1, True),
        ("MCSMU", 31, 0.01, False),
        ("HCSMU", 40, 1.0, True),
        ("HCSMU", 10, 1.5, False),
        ("HVSMU", 1500, 0.008, True),
        ("HVSMU", 2000, 0.008, False),
        ("HVSMU", 3000, 0.004, True),
        ("GNDU", 0, 4.2, True),
        ("GNDU", 0, 4.3, False),
        ("GNDU", 0.1, 0.0, False),
    ],
)
def test_violations_voltage_source(name: str, v: float, i: float, ok: bool) -> None:
    found = violations(MODULE_SPECS[name], v, i)
    assert (found == []) == ok, found
    if not ok:
        assert all(msg.startswith(f"{name}:") for msg in found)


def test_violations_current_source_and_non_finite_values() -> None:
    hr = MODULE_SPECS["HRSMU"]
    assert violations(hr, 100, 0.02, source="I") == []  # PG Table 4-6: 20 mA with Vcomp 100 V
    assert violations(hr, 40, 0.05, source="I") == []
    assert violations(hr, 41, 0.05, source="I") != []
    assert violations(hr, float("nan"), 0.0) != []
    assert violations(hr, 1.0, float("inf")) != []


def test_range_tables_match_the_manual_codes() -> None:
    assert V_RANGE_FULL_SCALE[20] == V_RANGE_FULL_SCALE[11] == 2.0
    assert V_RANGE_FULL_SCALE[2000] == V_RANGE_FULL_SCALE[15] == 200.0
    assert I_RANGE_FULL_SCALE[8] == 1e-12 and I_RANGE_FULL_SCALE[14] == 1e-6 and I_RANGE_FULL_SCALE[19] == 0.1
    assert set(V_RANGE_FULL_SCALE) == commands.V_RANGE_CODES - {0}
    assert set(I_RANGE_FULL_SCALE) == commands.I_RANGE_CODES - {0}
    for spec in MODULE_SPECS.values():
        for rng in spec.v_ranges:
            assert rng.code in commands.V_RANGE_CODES
        for rng in spec.i_ranges:
            assert rng.code in commands.I_RANGE_CODES


@pytest.mark.parametrize(
    ("name", "quantity", "codes"),
    [
        ("HRSMU", "I", [8, *range(9, 20)]),
        ("MPSMU", "I", [8, 9, 10, *range(11, 20)]),
        ("HPSMU", "I", list(range(11, 21))),
        ("MCSMU", "I", list(range(15, 21))),
        ("HCSMU", "I", [*range(15, 21), 22]),
        ("HVSMU", "I", list(range(11, 19))),
        ("HRSMU", "V", [5, 20, 50, 200, 400, 1000]),
        ("HPSMU", "V", [20, 200, 400, 1000, 2000]),
        ("MCSMU", "V", [2, 20, 200, 400]),
        ("HVSMU", "V", [2000, 5000, 15000, 30000]),
    ],
)
def test_module_range_codes_follow_tables_4_2_to_4_5(name: str, quantity: str, codes: list[int]) -> None:
    spec = MODULE_SPECS[name]
    ranges = spec.v_ranges if quantity == "V" else spec.i_ranges
    assert [r.code for r in ranges] == codes


def test_ranging_code_mapping() -> None:
    hr, mp, mc = MODULE_SPECS["HRSMU"], MODULE_SPECS["MPSMU"], MODULE_SPECS["MCSMU"]
    assert ranging_code(hr, Ranging()) == 0
    assert ranging_code(hr, Ranging(quantity="I", mode="limited_auto", range_value=1e-9)) == 11
    assert ranging_code(hr, Ranging(quantity="I", mode="fixed", range_value=1e-11)) == -9
    assert ranging_code(hr, Ranging(quantity="I", mode="fixed", range_value=1e-12), asu=True) == -8
    assert ranging_code(hr, Ranging(quantity="V", mode="fixed", range_value=2.0)) == -20
    assert ranging_code(mp, Ranging(quantity="I", mode="fixed", range_value=0.1)) == -19
    with pytest.raises(ValueError, match="ASU"):
        ranging_code(hr, Ranging(quantity="I", mode="fixed", range_value=1e-12))
    with pytest.raises(ValueError, match="ASU"):
        ranging_code(mp, Ranging(quantity="I", mode="fixed", range_value=1e-11))
    with pytest.raises(ValueError, match="pulse only"):
        ranging_code(mc, Ranging(quantity="I", mode="fixed", range_value=1.0))
    with pytest.raises(ValueError, match="no 0.3 V range"):
        ranging_code(hr, Ranging(quantity="V", mode="fixed", range_value=0.3))
    with pytest.raises(ValueError):
        ranging_code(MODULE_SPECS["GNDU"], Ranging(quantity="I", mode="fixed", range_value=1e-3))


def test_range_lookup_helpers() -> None:
    assert range_full_scale("V", -12) == 20.0
    assert range_full_scale("I", 18) == 0.01
    with pytest.raises(KeyError):
        range_full_scale("I", 0)
    hr = MODULE_SPECS["HRSMU"]
    assert hr.range_for("V", 12) is not None and hr.range_for("V", -200) == hr.range_for("V", 12)
    assert hr.range_for("V", 2000) is None and hr.range_for("I", 20) is None


def test_capability_flags() -> None:
    assert {n for n, s in MODULE_SPECS.items() if s.high_resolution_adc} == {"HPSMU", "MPSMU", "HRSMU"}
    assert {n for n, s in MODULE_SPECS.items() if 4 in s.cmm_modes} == {"MCSMU", "HCSMU", "HVSMU"}
    assert all(spec.sources and spec.envelope_source for spec in MODULE_SPECS.values())
