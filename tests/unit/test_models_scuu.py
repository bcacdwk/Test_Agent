"""SCUU geometry in the station profile, MFCMU-side wiring targets of simulator scenarios and the CMU fault schemas
(``models/station.py``, ``models/sim.py``; WP8.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from b1500_test_agent.models.sim import CmuCorrectionLost, CmuOverload, parse_fault
from b1500_test_agent.models.station import SimScenario, StationProfile, scuu_side

pytestmark = pytest.mark.cmu

ROOT = Path(__file__).resolve().parents[2]


def station_data() -> dict[str, Any]:
    data = yaml.safe_load((ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    data["switches"] = [s for s in data["switches"] if s["kind"] == "scuu"]
    return data


def with_scuu(**changes: Any) -> dict[str, Any]:
    data = station_data()
    data["switches"][0].update(changes)
    return data


def test_the_example_scuu_follows_table_4_30() -> None:
    station = StationProfile.model_validate(station_data())
    [scuu] = station.switches
    assert {o: p.index for o, p in scuu.ports.items()} == {"OUT1": 6, "OUT2": 5} and scuu.rest == "smu"
    assert (scuu_side(7, 6), scuu_side(7, 5), scuu_side(7, 4), scuu_side(701, 6)) == ("H", "L", None, "H")


@pytest.mark.parametrize(("changes", "match"), [
    ({"rest": "open"}, "cannot be returned to open"),
    ({"ports": {"OUT1": {"index": 4, "inputs": {"smu": 4, "cmu": 7}}}}, "slot 6"),
    ({"ports": {"OUT1": {"index": 6, "inputs": {"smu": 6, "cmu": 7}},
                "OUT2": {"index": 6, "inputs": {"smu": 6, "cmu": 7}}}}, "used twice"),
    ({"ports": {"OUT1": {"index": 6, "inputs": {"smu": 6, "cmu": 7}},
                "OUT2": {"index": 5, "inputs": {"smu": 5, "cmu": 3}}}}, "input cmu"),
])
def test_scuu_geometry_is_validated(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        StationProfile.model_validate(with_scuu(**changes))


def test_an_scuu_with_unknown_mfcmu_wiring_still_validates() -> None:
    ports = {"OUT1": {"index": 6, "inputs": {"smu": 6, "cmu": None}}}
    StationProfile.model_validate(with_scuu(ports=ports))


def scenario(wiring: dict[str, Any], **extra: Any) -> SimScenario:
    return SimScenario.model_validate({
        "name": "t", "idn": "x", "slots": [{"slot": 5, "model": "B1511B"}, {"slot": 6, "model": "B1511B"},
                                          {"slot": 7, "model": "B1520A"}],
        "wiring": {"c": wiring}, "models": {"c": {"model": "capacitor", "params": {"c_f": 1e-10}}}, **extra})


def test_scenarios_wire_terminals_to_mfcmu_sides() -> None:
    assert scenario({"a": "7H", "b": "7L"}).wiring["c"] == {"a": "7H", "b": "7L"}
    assert scenario({"a": "7H", "b": "7L"}, scuu=[7]).scuu == [7]
    with pytest.raises(ValidationError):
        scenario({"a": "7X", "b": "7L"})
    with pytest.raises(ValidationError, match="holds no MFCMU"):
        scenario({"a": "5H", "b": "7L"})
    with pytest.raises(ValidationError, match="feeds the SCUU"):
        scenario({"a": 5, "b": "7L"}, scuu=[7])


def test_cmu_fault_schemas() -> None:
    assert parse_fault({"kind": "cmu_correction_lost", "after_cmd": "*RST"}) == CmuCorrectionLost(after_cmd="*RST")
    assert parse_fault({"kind": "cmu_overload", "at_step": 3}).condition == "saturation"  # type: ignore[union-attr]
    for bad in ({"kind": "cmu_overload", "at_step": 0, "condition": "smoke"},
                {"kind": "cmu_correction_lost", "after_cmd": "xe"}):
        with pytest.raises(ValidationError):
            parse_fault(bad)
    assert CmuOverload(at_step=0, condition="excess_current").kind == "cmu_overload"
