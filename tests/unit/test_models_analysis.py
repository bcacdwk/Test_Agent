"""Salvaged value, trust, method and provenance models (blueprint 2.1, 2.6, 2.8)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.analysis import (
    Criterion,
    DerivativeMethod,
    MethodRecord,
    Provenance,
    Quantity,
    QuantityRange,
    TrustPolicy,
    VthSpec,
)

# -- Quantity -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "unit", "kind"),
    [
        (-1.0, "V", float),  # vg_start
        (101, None, int),  # vg_points keeps its int type
        (True, None, bool),
        ("medium", None, str),  # enum choice
        ([0.0, 0.5, 1.0], "V", list),  # float_list
    ],
)
def test_quantity_holds_every_resolved_param_type(value: object, unit: str | None, kind: type) -> None:
    q = Quantity(value=value, unit=unit)  # type: ignore[arg-type]
    assert type(q.value) is kind
    assert Quantity.model_validate_json(q.model_dump_json()) == q


@pytest.mark.parametrize(
    "data",
    [
        {"value": "medium", "unit": "V"},  # a string has no unit
        {"value": True, "unit": "1"},
        {"value": 1.0, "unit": "volt"},  # closed vocabulary
        {"value": [0.1], "bound": "upper"},  # bounds are numeric scalars
        {"value": "x", "bound": "lower"},
        {"value": float("inf"), "unit": "A"},
        {"value": 1.0, "unit": "A", "note": "extra"},
    ],
)
def test_quantity_rejects_inconsistent_values(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Quantity.model_validate(data)


def test_quantity_as_float() -> None:
    assert Quantity(value=3, unit="V").as_float() == 3.0
    assert Quantity(value=1e-13, unit="A", bound="upper").is_number
    for value in ("medium", True, [1.0]):
        q = Quantity(value=value)  # type: ignore[arg-type]
        assert not q.is_number
        with pytest.raises(TypeError):
            q.as_float()


def test_quantity_range() -> None:
    window = QuantityRange(low=0.2, high=0.8, unit="V")
    assert window.contains(0.2) and window.contains(0.8) and not window.contains(0.81)
    for low, high in ((1.0, 1.0), (1.0, 0.0)):
        with pytest.raises(ValidationError):
            QuantityRange(low=low, high=high, unit="V")


# -- TrustPolicy ----------------------------------------------------------------------------------------------------


def test_trust_policy_defaults_match_recipe_quality_block() -> None:
    policy = TrustPolicy()
    assert policy.limited == ["C", "T"]
    assert policy.untrusted == ["V", "X", "F", "D", "G", "S", "U"]
    assert policy.classify("N") == "ok"
    assert {policy.classify(c) for c in "CT"} == {"limited"}
    assert {policy.classify(c) for c in "VXFDGSU"} == {"untrusted"}


@pytest.mark.parametrize("status", ["", "W", "E", "Z", "n", "NN", "?"])
def test_trust_policy_unknown_status_is_untrusted(status: str) -> None:
    assert TrustPolicy().classify(status) == "untrusted"


def test_trust_policy_may_be_stricter() -> None:
    strict = TrustPolicy(limited=[], untrusted=["C", "T", "V", "X", "F", "D", "G", "S", "U"])
    assert strict.classify("C") == "untrusted"


@pytest.mark.parametrize(
    ("limited", "untrusted"),
    [
        (["C", "T"], ["V", "X", "F", "D", "G", "S"]),  # U unclassified
        (["C", "T", "X"], ["V", "X", "F", "D", "G", "S", "U"]),  # X in both
        (["C", "T", "N"], ["V", "X", "F", "D", "G", "S", "U"]),  # N is always ok
        (["C", "C", "T"], ["V", "X", "F", "D", "G", "S", "U"]),
        (["C", "T", "V"], ["X", "F", "D", "G", "S", "U"]),  # V is never usable data
        (["C", "T", "L"], ["V", "X", "F", "D", "G", "S", "U"]),  # not a Table 1-10 letter
    ],
)
def test_trust_policy_must_partition_the_status_letters(limited: list[str], untrusted: list[str]) -> None:
    with pytest.raises(ValidationError):
        TrustPolicy.model_validate({"limited": limited, "untrusted": untrusted})


# -- Method specs ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "ok"),
    [
        ({"name": "central_difference"}, True),
        ({"name": "savitzky_golay", "window_points": 7, "polyorder": 2}, True),
        ({"name": "savitzky_golay", "window_points": 7}, False),
        ({"name": "savitzky_golay", "window_points": 6, "polyorder": 2}, False),
        ({"name": "savitzky_golay", "window_points": 3, "polyorder": 3}, False),
        ({"name": "central_difference", "window_points": 5}, False),
    ],
)
def test_derivative_method(data: dict[str, object], ok: bool) -> None:
    if ok:
        DerivativeMethod.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            DerivativeMethod.model_validate(data)


@pytest.mark.parametrize(
    ("data", "ok"),
    [
        ({"method": "vth_linear_extrapolation"}, True),
        ({"method": "vth_max_gm"}, True),
        ({"method": "vth_constant_current", "i_crit_a": 1e-7}, True),
        ({"method": "vth_constant_current", "i_crit_a": 1e-7, "w_over_l": 10.0}, True),
        ({"method": "vth_constant_current"}, False),
        ({"method": "vth_constant_current", "i_crit_a": -1e-7}, False),
        ({"method": "vth_max_gm", "i_crit_a": 1e-7}, False),
        ({"method": "vth_linear_extrapolation", "w_over_l": 10.0}, False),
        ({"method": "linear_extrapolation"}, False),
    ],
)
def test_vth_spec(data: dict[str, object], ok: bool) -> None:
    if ok:
        VthSpec.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            VthSpec.model_validate(data)


def test_method_record() -> None:
    record = MethodRecord(
        name="vth_linear_extrapolation", version="1", params={"window": "max_gm", "subtract_half_vd": True}
    )
    assert record.script is None
    assert MethodRecord.model_validate_json(record.model_dump_json()) == record
    MethodRecord(name="adhoc_fit", version="1", script="work/S20261117T063012Z-7f3a/fit.py")
    for bad in ({"name": "Vth", "version": "1"}, {"name": "vth", "version": ""}):
        with pytest.raises(ValidationError):
            MethodRecord.model_validate(bad)


def test_provenance_matches_recipe_example() -> None:
    prov = Provenance.model_validate(
        {"sources": ["deck slide 6", "Programming Guide WV/FMT pages"], "validation_runs": []}
    )
    assert prov.validation_runs == []
    assert Provenance().sources == []
    Provenance(validation_runs=["S20261117T063012Z-7f3a", "H20270102T090000Z-00ff"])
    for bad in (
        {"validation_runs": ["R20261117T063012Z-7f3a"]},
        {"validation_runs": ["S20261117T063012Z-7F3A"]},
        {"validation_runs": ["S2026-11-17T06:30:12Z-7f3a"]},
        {"sources": [""]},
    ):
        with pytest.raises(ValidationError):
            Provenance.model_validate(bad)


# -- Criterion ------------------------------------------------------------------------------------------------------


def test_criterion_checks_values_in_its_unit() -> None:
    within = Criterion(
        quantity="vth",
        comparator="within",
        limit=Quantity(value=0.3, unit="V"),
        limit_high=Quantity(value=0.7, unit="V"),
    )
    assert within.check(0.5, "V") and within.check(0.7, "V") and not within.check(0.71, "V")
    with pytest.raises(ValueError):
        within.check(0.5, "A")
    leak = Criterion(quantity="leakage_current", comparator="le", limit=Quantity(value=1e-9, unit="A"))
    assert leak.check(5e-10, "A") and not leak.check(2e-9, "A")
    ss = Criterion(quantity="ss", comparator="ge", limit=Quantity(value=60, unit="mV/dec"))
    assert ss.check(75.0, "mV/dec")


@pytest.mark.parametrize(
    "data",
    [
        {"comparator": "within", "limit": {"value": 0.3, "unit": "V"}},
        {"comparator": "within", "limit": {"value": 0.3, "unit": "V"}, "limit_high": {"value": 1e-3, "unit": "A"}},
        {"comparator": "within", "limit": {"value": 0.7, "unit": "V"}, "limit_high": {"value": 0.3, "unit": "V"}},
        {"comparator": "le", "limit": {"value": 0.3, "unit": "V"}, "limit_high": {"value": 0.7, "unit": "V"}},
        {"comparator": "le", "limit": {"value": 0.3}},  # unitless limit
        {"comparator": "le", "limit": {"value": "high", "unit": None}},
        {"comparator": "le", "limit": {"value": 1e-9, "unit": "A", "bound": "upper"}},
    ],
)
def test_criterion_rejects_inconsistent_limits(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Criterion.model_validate({"quantity": "vth", **data})
