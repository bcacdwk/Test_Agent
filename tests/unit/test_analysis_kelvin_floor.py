"""``kelvin_resistance`` and ``zero_floor`` (WP7.1, blueprint v2 2.10) on analytic tables with known truth: the
four-wire line fit (R, offset voltage, r2), its open/short/in_range classification and trust rules, and the zero
check's offset and floor per role and range label, through the registry as ``analyze_run`` calls them."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis.dataset import RunData, with_trust
from b1500_test_agent.analysis.floor import label_full_scale, zero_floor
from b1500_test_agent.analysis.registry import run_method
from b1500_test_agent.analysis.resistor import kelvin_resistance
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import iv_table, manifest, run_of
from tests.unit.helpers import assert_roundtrip

CURRENTS = np.repeat([-0.01, -0.005, 0.005, 0.01], 4)


def four_wire(voltage: np.ndarray, *, status: list[str] | None = None, currents: np.ndarray = CURRENTS) -> RunData:
    table = iv_table({"a_I": currents}, {"a_V": voltage}, status={"a_V": status} if status else None)
    return run_of(table, "resistor.kelvin_4w", kind="smu_spot")


def test_kelvin_recovers_r_and_the_offset_voltage() -> None:
    rng = np.random.default_rng(3)
    v = 1.25 * CURRENTS + 30e-6 + 1e-7 * rng.standard_normal(CURRENTS.size)  # R 1.25 Ohm, 30 uV thermal EMF
    r, offset, r2 = kelvin_resistance(four_wire(v))
    assert (r.quantity, r.unit, r.classification, r.bound, r.method) == (
        "resistance", "Ohm", "in_range", "exact", "kelvin_resistance")
    assert r.value == pytest.approx(1.25, rel=1e-4) and r.points_used == 16
    assert offset.quantity == "offset_voltage" and offset.value == pytest.approx(30e-6, abs=1e-7)
    assert r2.value > 0.99999 and r.fit["points_per_current"] == 4 and r.fit["residual_v"] < 2e-7
    assert r.window is not None and (r.window.low, r.window.high) == (-0.01, 0.01)
    assert_roundtrip(r)


def test_kelvin_voltage_compliance_is_an_open_landing() -> None:
    v = np.array([-1.0, -1.0])
    status = ["C", "N"]
    r = kelvin_resistance(four_wire(v, status=status, currents=np.array([-0.01, -0.005])))[0]
    assert (r.classification, r.bound, r.points_used) == ("open", "lower", 1)
    assert r.value == pytest.approx(100.0) and "open" in r.warnings[0]


def test_kelvin_noise_dominated_signal_is_a_short() -> None:
    rng = np.random.default_rng(5)
    v = 1e-6 * rng.standard_normal(CURRENTS.size)  # nothing but noise: R of a few micro-ohm at most
    r = kelvin_resistance(four_wire(v))[0]
    assert (r.classification, r.bound) == ("short", "upper") and r.value < 1e-2


def test_kelvin_failures_and_refusals() -> None:
    negative = kelvin_resistance(four_wire(-1.0 * CURRENTS))[0]
    assert negative.outcome == "failed" and "sense lines" in (negative.error or "")
    single = kelvin_resistance(four_wire(np.full(4, 0.01), currents=np.full(4, 0.01)))[0]
    assert single.outcome == "failed" and "two" in (single.error or "")
    status = ["N"] * 15 + ["X"]
    refused = kelvin_resistance(four_wire(1.0 * CURRENTS, status=status))[0]
    assert refused.outcome == "refused"
    forced = kelvin_resistance(four_wire(1.0 * CURRENTS, status=status), force=True)[0]
    assert forced.outcome == "ok" and forced.forced_on_untrusted and forced.value == pytest.approx(1.0)


def test_kelvin_needs_a_current_and_a_voltage_column() -> None:
    table = iv_table({"a_V": np.linspace(-0.1, 0.1, 5)}, {"a_I": np.linspace(-1e-6, 1e-6, 5)})
    with pytest.raises(InvalidInputError, match="forced-current"):
        kelvin_resistance(run_of(table, "generic.smu_spot", kind="smu_spot"))


def test_kelvin_runs_through_the_registry_on_spot_runs_only() -> None:
    results = run_method("kelvin_resistance", four_wire(2.0 * CURRENTS))
    assert isinstance(results, list) and results[0].value == pytest.approx(2.0)
    staircase = run_of(iv_table({"a_I": CURRENTS}, {"a_V": CURRENTS}), "resistor.kelvin_4w")
    with pytest.raises(InvalidInputError, match="does not apply"):
        run_method("kelvin_resistance", staircase)


# -- zero_floor ------------------------------------------------------------------------------------------------------


def zero_run(columns: dict[str, np.ndarray], ranges: dict[str, list[str]],
             status: dict[str, list[str]] | None = None) -> RunData:
    n = len(next(iter(columns.values())))
    data: dict[str, object] = {"step": np.arange(n)}
    data.update({f"{role}_range": labels for role, labels in ranges.items()})
    for role, values in columns.items():
        data[f"{role}_I"] = values
        data[f"{role}_I_status"] = (status or {}).get(role, ["N"] * n)
    return RunData(manifest(recipe_id="system.zero_check", kind="smu_spot"), with_trust(pd.DataFrame(data)))


def test_floor_and_offset_per_role_and_range() -> None:
    rng = np.random.default_rng(11)
    hr = np.concatenate([2e-15 + 1e-13 * rng.standard_normal(200), 5e-13 * rng.standard_normal(200)])
    mp = 1e-11 * rng.standard_normal(400)
    run = zero_run({"smu3": hr, "smu5": mp},
                   {"smu3": ["10pA"] * 200 + ["1nA"] * 200, "smu5": ["1nA"] * 400})
    found = {r.quantity: r for r in zero_floor(run)}
    assert set(found) == {"smu3_floor", "smu5_floor"}  # one compact result per role
    floor = found["smu3_floor"]
    assert floor.value == pytest.approx(1e-13, rel=0.15) and floor.unit == "A"  # the lowest range (10 pA)
    assert set(floor.fit) == {"10pA", "1nA", "offset", "max_abs_offset"} and floor.points_used == 400
    assert floor.fit["1nA"] == pytest.approx(5e-13, rel=0.15)
    assert abs(floor.fit["offset"] - 2e-15) < 3e-14 and floor.fit["max_abs_offset"] >= abs(floor.fit["offset"])
    assert "Lowest range 10pA; 2 range group(s) of 200 readings" in floor.warnings[-1]
    assert found["smu5_floor"].value == pytest.approx(1e-11, rel=0.15) and found["smu5_floor"].points_used == 400
    assert floor.classification is None and len(f"{floor.value!r}") <= 8  # three significant digits


def test_floor_limits_classify() -> None:
    run = zero_run({"smu3": np.array([1e-13, -1e-13] * 5)}, {"smu3": ["10pA"] * 10})
    [floor] = zero_floor(run, max_floor_a=1e-12, max_offset_a=1e-15)
    assert floor.classification == "pass"
    assert zero_floor(run, max_floor_a=1e-14)[0].classification == "fail"
    shifted = zero_run({"smu3": np.array([1e-13, -1e-13] * 5) + 1e-12}, {"smu3": ["10pA"] * 10})
    assert zero_floor(shifted, max_offset_a=1e-13)[0].classification == "fail"


def test_floor_without_range_column_is_auto_and_needs_three_points() -> None:
    run = zero_run({"smu3": np.array([1e-13, -1e-13, 2e-13])}, {})
    floor = zero_floor(run)[0]
    assert floor.outcome == "ok" and "Lowest range auto" in floor.warnings[-1]
    short = zero_floor(zero_run({"smu3": np.array([1e-13, -1e-13])}, {"smu3": ["10pA", "10pA"]}))[0]
    assert short.outcome == "failed" and "fewer than 3" in (short.error or "")


def test_floor_compliance_is_excluded_and_warned_untrusted_refused() -> None:
    values = np.array([1e-13, -1e-13, 2e-13, 1e-4])
    limited = zero_floor(zero_run({"smu3": values}, {"smu3": ["10pA"] * 4}, {"smu3": ["N", "N", "N", "C"]}))[0]
    assert limited.outcome == "ok" and any("not open" in w for w in limited.warnings)
    assert limited.points_used == 3
    refused = zero_floor(zero_run({"smu3": values}, {"smu3": ["10pA"] * 4}, {"smu3": ["N", "N", "N", "V"]}))[0]
    assert refused.outcome == "refused"


@pytest.mark.parametrize(("label", "full_scale"), [("10pA", 1e-11), ("1pA+", 1e-12), ("100mA", 0.1), ("1A", 1.0),
                                                   ("auto", float("inf"))])
def test_label_full_scale(label: str, full_scale: float) -> None:
    assert label_full_scale(label) == pytest.approx(full_scale)
