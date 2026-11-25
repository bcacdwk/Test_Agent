"""WGFMU library warnings in a run (WP10.8; blueprint v2 1.2 "error/warning queues", the orchestrator's decision on the
closure): every WGFMU run reads the library's warning summary after its readback (``WgfmuDriver.warnings``, WG p119
(4-49)); the run's ``kind_result`` carries ``wgfmu_warnings`` (count) and ``wgfmu_warning_text`` (the lines), the
audit keeps the ``WGFMU_getWarningSummary`` call with its lines, and a warning never stops or flags a run (the library
defaults stay: warnings reported at level normal, none turned into an error; WG p133 (4-63), p138 (4-68) Table 4-4).
The three WGFMU paths are covered: kind ``wgfmu_waveform`` (sequencer and DC mode), the WGFMU source of ``pulse_read``
and the WGFMU path of ``stress_measure``."""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from tests.integration.helpers import World
from tests.visa_loop.test_sampling_visa import run_to_end

pytestmark = pytest.mark.wgfmu

MOSFET = {"pin_map": "mosfet-wgfmu", "dut_profile": "nmos-wgfmu"}
PULSED = {"recipe_id": "wgfmu.pulsed_iv", "scenario": "nmos_wgfmu", "request": {"params": {}, **MOSFET}}
DC_SPOT = {"recipe_id": "wgfmu.dc_spot", "scenario": "resistor_100k",
           "request": {"params": {}, "pin_map": "resistor-wgfmu", "dut_profile": "resistor-generic"}}
ENDURANCE = {"recipe_id": "fecap.endurance_pund", "scenario": "fecap_basic",
             "request": {"params": {"cycles": 1000, "reads_per_decade": 1}, "pin_map": "fecap-wgfmu",
                         "dut_profile": "fecap-generic"}}
FAST_BTI = {"recipe_id": "wgfmu.fast_bti", "scenario": "nmos_bti",
            "request": {"params": {"vg_stress": 2.0, "stress_time": 10.0}, **MOSFET}}
NOTE = "simulated warning for the test"


def _run(world: World, case: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    world.use_scenario(case["scenario"])
    service = world.service()
    _validation, result = run_to_end(service, case)
    assert result.ok and result.outcome == "completed", result.message
    return result, load_run(result.run_id or "", data_root=world.data).manifest.kind_result


def _summary_reads(world: World, run_id: str) -> list[Any]:
    return [e for e in world.audit_events()
            if e.ev == "wgfmu_call" and e.cmd == "WGFMU_getWarningSummary" and e.run == run_id]


@pytest.fixture
def warn_at_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every sequencer start adds one normal warning to the simulated library's summary."""
    original = SimWgfmu.execute

    def execute(self: SimWgfmu) -> None:
        original(self)
        self._warn("execute", "normal", NOTE)

    monkeypatch.setattr(SimWgfmu, "execute", execute)


@pytest.mark.parametrize("case", [PULSED, DC_SPOT, ENDURANCE, FAST_BTI], ids=lambda c: c["recipe_id"])
def test_a_clean_run_reads_the_summary_and_reports_no_warning(world: World, case: dict[str, Any]) -> None:
    result, facts = _run(world, case)
    assert facts["wgfmu_warnings"] == 0 and "wgfmu_warning_text" not in facts
    reads = _summary_reads(world, result.run_id or "")
    assert reads and all(e.resp == "0 warning(s)" and e.data["rc"] == 0 for e in reads)


def test_a_warning_is_reported_in_kind_result_and_audit_and_never_stops_the_run(world: World,
                                                                              warn_at_execute: None) -> None:
    result, facts = _run(world, PULSED)
    assert result.outcome == "completed" and result.cleanup_verified == "sim_state"  # not flagged, not failed
    assert facts["wgfmu_warnings"] == 1 and facts["wgfmu_warning_text"] == f"[normal] execute: {NOTE}"
    (read,) = _summary_reads(world, result.run_id or "")
    assert read.resp == f"1 warning(s): [normal] execute: {NOTE}"


def test_every_execution_of_a_multi_run_recipe_reports_its_warnings(world: World, warn_at_execute: None) -> None:
    """``pulse_read`` loads one program per step (each load clears the library setup and its warnings), so the run's
    count is one warning per execution; the text keeps the distinct lines."""
    result, facts = _run(world, ENDURANCE)
    assert facts["wgfmu_warnings"] == facts["executions"] > 1
    assert facts["wgfmu_warning_text"] == f"[normal] execute: {NOTE}"
    assert len(_summary_reads(world, result.run_id or "")) == facts["executions"]


def test_the_stress_path_counts_the_warnings_of_every_execution(world: World, warn_at_execute: None) -> None:
    _result, facts = _run(world, FAST_BTI)
    assert facts["wgfmu_warnings"] == facts["runs_done"] >= 1
