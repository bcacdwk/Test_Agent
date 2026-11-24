"""Search analyses (``analysis/pulse.py``: ``vth_search_value``, ``breakdown_voltage``; WP7.5) on synthetic one-row
search tables with the kind's ``kind_result``: found / not found / stopped, linear vs quasi-pulsed status semantics,
lower bounds, refusals and ``force``, the registry entries."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from b1500_test_agent.analysis import ANALYSIS_METHODS, RunData
from b1500_test_agent.analysis.pulse import breakdown_voltage, vth_search_value
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import manifest

pytestmark = pytest.mark.smu


def run(row: dict[str, Any], result: dict[str, Any], recipe_id: str = "mosfet.vth_search") -> RunData:
    data = manifest(recipe_id=recipe_id).model_copy(update={"kind_result": result})
    return RunData(data, pd.DataFrame([{"step": 0, **row, "trust": "ok"}]))


VTH_RESULT = {"measurement_mode": 15, "search": "binary", "result_column": "gate_V", "monitor_column": "drain_I",
              "target": 1e-7}
LINEAR = {"measurement_mode": 14, "search": "linear", "result_column": "anode_V", "monitor_column": "anode_I",
          "target": -1e-6, "start": 0.0, "stop": -20.0, "step": -0.1}
QUASI = {"measurement_mode": 9, "search": "quasi_pulsed", "result_column": "gate_V", "monitor_column": "gate_V",
         "start": 0.0, "stop": 30.0, "icomp": 1e-3}


def vth_row(status: str = "N", sense: str = "N", i: float = 1.004e-7) -> dict[str, Any]:
    return {"gate_V": 0.4123, "gate_V_status": status, "drain_I": i, "drain_I_status": sense, "drain_V": 0.05}


def test_vth_search_value_reads_the_found_gate_voltage() -> None:
    result = vth_search_value(run(vth_row(), VTH_RESULT))
    assert (result.outcome, result.quantity, result.unit, result.value) == ("ok", "vth", "V", 0.4123)
    assert result.derived and result.points_used == 1
    assert result.fit["target"] == 1e-7 and result.fit["rel_error"] == pytest.approx(0.004)


def test_vth_search_value_not_found_fails_and_stopped_refuses() -> None:
    failed = vth_search_value(run(vth_row("G"), VTH_RESULT))
    assert failed.outcome == "failed" and "status G" in (failed.error or "") and failed.value is None
    refused = vth_search_value(run(vth_row("S", "C"), VTH_RESULT))
    assert refused.outcome == "refused" and "automatic abort" in (refused.error or "")
    forced = vth_search_value(run(vth_row("S", "C"), VTH_RESULT), force=True)
    assert forced.outcome == "ok" and forced.forced_on_untrusted and forced.warnings
    untrusted = vth_search_value(run(vth_row("N", "X"), VTH_RESULT))
    assert untrusted.outcome == "refused"
    limited = vth_search_value(run(vth_row("N", "C"), VTH_RESULT))
    assert limited.outcome == "ok" and any("limited" in w for w in limited.warnings)


def test_vth_search_value_defaults_and_bad_tables() -> None:
    no_result = vth_search_value(run(vth_row(), {}))  # gate_V / drain_I by default
    assert no_result.value == 0.4123 and "target" not in no_result.fit
    with pytest.raises(InvalidInputError, match="no search column"):
        vth_search_value(run(vth_row(), VTH_RESULT), y="bulk_I")
    two = RunData(manifest().model_copy(update={"kind_result": VTH_RESULT}),
                  pd.DataFrame([{"step": i, **vth_row(), "trust": "ok"} for i in range(2)]))
    with pytest.raises(InvalidInputError, match="one result row"):
        vth_search_value(two)


@pytest.mark.parametrize(("status", "sense", "outcome", "bound", "classification"), [
    ("N", "N", "ok", "exact", "breakdown"),
    ("N", "C", "ok", "exact", "breakdown"),  # the breakdown step reads the compliance
    ("S", "C", "ok", "exact", "breakdown"),  # stopped by the compliance at the breakdown step (warning)
    ("G", "N", "ok", "lower", "no_breakdown"),
    ("S", "T", "refused", "exact", None),
])
def test_breakdown_voltage_of_a_linear_search(status: str, sense: str, outcome: str, bound: str,
                                              classification: str | None) -> None:
    row = {"anode_V": -12.0, "anode_V_status": status, "anode_I": -1.0015e-6, "anode_I_status": sense}
    result = breakdown_voltage(run(row, LINEAR, "basic.breakdown_search"))
    assert (result.outcome, result.bound, result.classification) == (outcome, bound, classification)
    if outcome == "ok":
        assert result.value == -12.0 and result.fit["magnitude_v"] == 12.0 and result.fit["step_v"] == 0.1
        assert result.window is not None and (result.window.low, result.window.high) == (-12.0, -11.9)
        assert bool(result.warnings) is (status != "N")


@pytest.mark.parametrize(("status", "outcome", "bound", "hint"), [
    ("C", "ok", "exact", None),
    ("N", "ok", "lower", None),
    ("S", "refused", "exact", "method linear"),
    ("G", "refused", "exact", "long detection interval"),
    ("X", "refused", "exact", "untrusted"),
])
def test_breakdown_voltage_of_a_quasi_pulse(status: str, outcome: str, bound: str, hint: str | None) -> None:
    result = breakdown_voltage(run({"gate_V": 24.0, "gate_V_status": status}, QUASI, "dielectric.bdv"))
    assert (result.outcome, result.bound) == (outcome, bound)
    if outcome == "ok":
        assert result.value == 24.0 and result.window is None and result.fit["icomp"] == 1e-3
    else:
        assert hint in (result.error or "")
        assert breakdown_voltage(run({"gate_V": 24.0, "gate_V_status": status}, QUASI, "dielectric.bdv"),
                                 force=True).forced_on_untrusted


def test_a_quasi_pulse_that_measured_current_has_no_bdv() -> None:
    result = breakdown_voltage(run({"gate_I": 1e-3, "gate_I_status": "C"},
                                   {**QUASI, "result_column": "gate_I", "monitor_column": "gate_I"}, "dielectric.bdv"))
    assert result.outcome == "failed" and "voltage" in (result.error or "")


def test_registry_entries() -> None:
    vth, bdv = ANALYSIS_METHODS["vth_search_value"], ANALYSIS_METHODS["breakdown_voltage"]
    assert vth.kinds == ("smu_search",) and "mosfet.vth_search" in vth.recipes and vth.families == ("smu",)
    assert {"basic.breakdown_search", "dielectric.bdv"} <= set(bdv.recipes) and bdv.families == ("reliability",)
    assert vth.milestone == bdv.milestone == "M7" and not vth.two_run
