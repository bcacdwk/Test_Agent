"""Every long-run family under the asynchronous run machinery (blueprint v2 2.6, 7.4 stage L9, 8.1 ``safety/`` "async";
WP11.1).

1. Cancel at a boundary, one async plan per long-run recipe of every family and kind (the L9 recipes plus the long
   plans of the sampling, spot, C-t, RTN/LFN, pulse-train and program/read recipes): an abort request seen at the
   first checkpoint cancels there; the global invariant v2 holds on every bus - SMU outputs off, the HV-SPGU stopped,
   every 16440A output at rest, every WGFMU channel disconnected and idle with the library session closed, the MFCMU
   at DC 0 and AC off, all by the simulator's own reading (``SimInstrument.unsafe_reasons``) of the persisted state -
   plus auto-calibration restored (R-CAL-02), no lock, in-flight marker or abort request left, the rows labelled
   PARTIAL and refused by ``analyze_run``.
2. The Codex-style kill (WP7.7 finding: codex-cli 0.170.0 ends the MCP server at every headless turn end without its
   shutdown hook), per bus family (SMU stress, HV-SPGU endurance through the selector, WGFMU endurance PUND through the
   RSUs): ``b1500-mcp`` started the confirmed run and is killed (SIGKILL / TerminateProcess) after its first
   checkpoint. The next process sees the in-flight marker, refuses new runs with zero instrument I/O (R-FAULT-01),
   and ``safe_shutdown`` runs the recovery cleanup: every bus safe and verified, auto-calibration restored from the
   marker, the run archived ``aborted`` with its consent record and partial rows.

Scenarios are copies of the committed ones with ``auto_calibration: true`` (so the restore is visible) and, for the
kill drills, ``timing: scaled(f)`` (the run lasts long enough to be killed mid-way).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.session import InstrumentLock, read_inflight
from b1500_test_agent.transport.sim import SimInstrument
from b1500_test_agent.transport.sim.state import load_state_file, sim_state_file
from tests.integration.async_helpers import (
    manifest_of,
    partial_rows,
    progress_of,
    run_events,
    wait_for,
)
from tests.integration.helpers import REPO_ROOT, World, make_world
from tests.integration.test_async_cancel import abort_at

BIN = Path(sys.executable).parent
MCP = shutil.which("b1500-mcp", path=str(BIN))
needs_server = pytest.mark.skipif(MCP is None, reason="console scripts not installed")
SUFFIX = "_l9"
"""Name suffix of the scenario copies (the simulator state file is named after the scenario)."""


@dataclass(frozen=True)
class LongRun:
    """One asynchronous plan: ``bus`` names the families its kind drives (for the ids and the bus checks)."""

    recipe_id: str
    scenario: str
    pin_map: str
    dut_profile: str | None
    params: dict[str, Any] = field(default_factory=dict)
    bus: str = "smu"
    corrections: bool = False

    @property
    def id(self) -> str:
        return f"{self.recipe_id}-{self.bus}"


LONG_RUNS = [
    # SMU stress / TDDB (L9) and the long SMU plans of L1/L5
    LongRun("reliability.bti_sms", "nmos_bti", "mosfet-4t", "nmos-generic", {"vg_stress": 2.0, "stress_time": 1800.0}),
    LongRun("igzo.bias_stress", "igzo_transient", "mosfet-4t", "nmos-generic", {"vg_stress": 3.0}),
    LongRun("reliability.hci", "nmos_bti", "mosfet-4t", "nmos-generic", {"vg_stress": 1.2, "vd_stress": 2.5}),
    LongRun("reliability.silc", "nmos_bti", "mosfet-4t", "nmos-generic", {"vg_stress": 3.0}),
    LongRun("reliability.tddb_cvs", "dielectric_tddb", "mosfet-4t", "dielectric-generic",
            {"v_stress": 5.5, "duration": 600}),
    LongRun("mosfet.id_t_sampling", "igzo_transient", "mosfet-4t", "nmos-generic", {"vd": 0.1, "interval": 0.05}),
    LongRun("system.zero_check", "lab_station", "open-smus", "open-circuit", {"samples": 1000, "integration": "long"}),
    # HV-SPGU + 16440A (L9 endurance/retention; long trains and program/read of L7)
    LongRun("fefet.endurance", "fefet_lab", "fefet-sel", "fefet-lab", bus="spgu"),
    LongRun("fefet.retention", "fefet_lab", "fefet-sel", "fefet-lab", bus="spgu"),
    LongRun("spgu.pulse_train", "fefet_lab", "fefet-sel", "fefet-lab",
            {"bound": "duration", "duration": 900.0, "period": 1.0, "width": 1e-3}, bus="spgu"),
    LongRun("spgu.program_smu_read", "fefet_lab", "fefet-sel", "fefet-lab",
            {"cycles": 100, "samples": 20, "integration": "long"}, bus="spgu"),
    # WGFMU + RSU (L9 fast BTI and endurance PUND; long RTN/LFN records of L8)
    LongRun("wgfmu.fast_bti", "nmos_bti", "mosfet-wgfmu", "nmos-wgfmu", {"vg_stress": 2.0, "stress_time": 600.0},
            bus="wgfmu"),
    LongRun("fecap.endurance_pund", "fecap_basic", "fecap-wgfmu", "fecap-generic", bus="wgfmu"),
    LongRun("wgfmu.rtn", "nmos_rtn", "mosfet-wgfmu", "nmos-wgfmu", {"points": 4000000, "interval": 1e-4}, bus="wgfmu"),
    LongRun("wgfmu.lfn", "nmos_rtn", "mosfet-wgfmu", "nmos-wgfmu",
            {"points": 4000000, "interval": 1e-4, "average": 1e-4}, bus="wgfmu"),
    # MFCMU (C-t of L6; corrections first)
    LongRun("moscap.ct", "moscap_dit", "moscap-scuu", "moscap-generic", {"points": 10001, "interval_s": 0.05},
            bus="cmu", corrections=True),
]
"""One async plan per long-run recipe (every L9 recipe with a checkpointed long plan; ``dielectric.bdv`` and
``basic.breakdown_search`` are single-segment ramps, never asynchronous)."""

KILL_DRILLS = [run for run in LONG_RUNS if run.recipe_id in ("reliability.bti_sms", "fefet.endurance",
                                                                "fecap.endurance_pund")]
"""The L9 kill-and-recover drill per bus family (stage ``recovery_drill``, ``recovery_drill_spgu``,
``recovery_drill_wgfmu``)."""
CORRECTIONS = ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short")
RESIDUAL_SIGNS = {"smu": ("output switch on",), "spgu": ("output switch on", "selector port", "SPGU output"),
                  "wgfmu": ("WGFMU channel",)}
"""What a killed run of each bus family leaves behind (the simulator saves its state at checkpoints)."""


@pytest.fixture
def world(tmp_path: Path) -> Any:
    w = make_world(tmp_path)
    yield w
    for service in w.services:
        service.close()


def l9_scenario(world: World, base: str, *, timing: str = "instant") -> str:
    """A copy of committed scenario ``base`` with auto-calibration on and ``timing``, selected in the settings."""
    data = yaml.safe_load((REPO_ROOT / "config/sim/scenarios" / f"{base}.yaml").read_text(encoding="utf-8"))
    data.update({"timing": timing, "auto_calibration": True})
    name = base + SUFFIX
    world.write_config(f"sim/scenarios/{name}.yaml", data)
    settings = yaml.safe_load((REPO_ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"))
    settings["sim"]["scenario"] = name
    world.write_config("settings.yaml", settings)
    return name


def every_bus_problem(world: World, base: str) -> list[str]:
    """Why the persisted simulator state is not safe on some bus (empty when safe): the simulator's own reading (SMU,
    MFCMU, SPGU, WGFMU channels and session, pending measurement), every 16440A port at rest (open), auto-calibration
    back on."""
    name = base + SUFFIX
    state = load_state_file(sim_state_file(world.state_dir, name))
    assert state is not None
    data = yaml.safe_load((REPO_ROOT / "config/sim/scenarios" / f"{base}.yaml").read_text(encoding="utf-8"))
    instrument = SimInstrument(SimScenario.model_validate({**data, "name": name}))
    instrument.import_state(state)
    problems = list(instrument.unsafe_reasons())
    problems += [f"selector port {port}: status {status}" for port, status in state.selector_ports.items() if status]
    if not state.auto_calibration:
        problems.append("auto-calibration still off (CM 0)")
    return problems


def assert_long_run_invariant(world: World, run_id: str, base: str) -> Any:
    """The global invariant v2 after an asynchronous run (blueprint v2 2.6): finalized with a verified cleanup, every
    bus safe (``every_bus_problem``), DZ after the last level command and CL after the last source command (the SCUU
    ``SSP`` back to rest is step 5, between DZ and CL), no in-flight marker, abort request or lock sidecar left, the
    progress record final."""
    manifest = manifest_of(world, run_id)
    assert manifest is not None and manifest.cleanup is not None, "the run was not finalized"
    assert manifest.cleanup.verified == "sim_state" and not manifest.cleanup.latched_fault, manifest.cleanup
    assert every_bus_problem(world, base) == []
    log = [r for r in world.sim_log(base + SUFFIX) if r.outcome != "dropped"]
    sources = [r for r in log if r.source]
    levels = [r for r in sources if r.mnemonic != "SSP"]
    if levels:
        assert "DZ" in {r.mnemonic for r in log if r.seq > levels[-1].seq and r.outcome == "ok"}
    if sources:
        assert "CL" in {r.mnemonic for r in log if r.seq > sources[-1].seq and r.outcome == "ok"}
    assert not (world.state_dir / "inflight.json").exists() and not (world.state_dir / "abort.json").exists()
    locks = world.state_dir / "locks"
    assert not locks.is_dir() or not any(p.suffix == ".json" for p in locks.iterdir()), "lock sidecar left behind"
    progress = progress_of(world, run_id)
    assert progress is not None and progress.state != "running", progress
    return manifest


def validated(world: World, run: LongRun) -> Any:
    service = world.service(adapter="mcp")
    if run.corrections:
        for recipe in CORRECTIONS:  # the test stands in for the human who lifted and landed the probes
            plan = service.validate_plan(recipe_id=recipe, pin_map=run.pin_map)
            assert plan.tier == "needs_confirmation", plan.message
            assert service.run_confirmed_plan(plan.plan_id or "", plan.summary or "").ok
    plan = service.validate_plan(recipe_id=run.recipe_id, params=run.params or None, pin_map=run.pin_map,
                                 dut_profile=run.dut_profile)
    assert plan.ok and plan.tier in ("ok", "needs_confirmation"), plan.message
    assert plan.resolved is not None and plan.resolved.mode == "async", plan.resolved
    return service, plan


@pytest.mark.parametrize("run", LONG_RUNS, ids=[r.id for r in LONG_RUNS])
def test_async_long_run_cancels_at_its_first_boundary_with_every_bus_safe(run: LongRun, world: World,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    l9_scenario(world, run.scenario)
    service, plan = validated(world, run)
    abort_at(monkeypatch, world, 1, reason="L9 cancel drill")
    started = (service.run_confirmed_plan(plan.plan_id or "", plan.summary or "") if plan.tier == "needs_confirmation"
               else service.run_plan(plan.plan_id or ""))
    assert started.outcome == "running", started.message
    final = service.follow_run(started.run_id or "")
    assert final is not None, started
    assert (final.outcome, final.error_code, final.cleanup_verified) == ("cancelled", "run_cancelled", "sim_state"), \
        final.message
    run_id = final.run_id or ""
    progress = progress_of(world, run_id)
    assert progress is not None and (progress.state, progress.done) == ("cancelled", 1), progress
    manifest = assert_long_run_invariant(world, run_id, run.scenario)
    assert manifest.cleanup is not None and "L9 cancel drill" in manifest.message
    restore = [s for s in manifest.cleanup.steps if s.step == "restore"]
    assert len(restore) == 1 and restore[0].ok and "restored to on" in restore[0].detail, manifest.cleanup.steps
    if run.bus == "wgfmu":
        assert all(state == "open" for target, state in manifest.cleanup.switches_after.items()
                   if target.startswith("RSU")), manifest.cleanup.switches_after
    if run.bus == "spgu":
        assert manifest.cleanup.switches_after.get("SEL1.OUT1") == "open", manifest.cleanup.switches_after
    detail = service.get_run(run_id, include=["summary", "progress", "data"])
    assert detail.run is not None and detail.run.outcome == "cancelled" and detail.run.cleanup_verified == "sim_state"
    refused = service.analyze_run(run_id, "quality_report")
    assert not refused.ok and refused.status == "refused", refused.message
    if partial_rows(world, run_id):  # a pulse train without reads archives no table at all
        assert detail.data is not None and "PARTIAL" in detail.data.note and "partial" in refused.message


# -- the Codex-style kill of the MCP server (no shutdown hook) ---------------------------------------------------------


def child_env(world: World) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("B1500_")}
    return {**env, "PYTHONUTF8": "1", **world.env()}


def start_in_server(world: World, plan: Any) -> tuple[subprocess.Popen[str], str]:
    """Start ``b1500-mcp`` on stdio and call ``run_confirmed_plan`` with the plan's exact summary (the harness after
    the human's consent); returns the server process and the run id."""
    child = subprocess.Popen([MCP or "b1500-mcp"], env=child_env(world), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8", cwd=str(world.root))
    assert child.stdin is not None and child.stdout is not None
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "codex-like", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "run_confirmed_plan", "arguments": {"plan_id": plan.plan_id, "summary": plan.summary}}},
    ]
    for message in messages:
        child.stdin.write(json.dumps(message) + "\n")
        child.stdin.flush()
    replies = [json.loads(child.stdout.readline()) for _ in range(2)]
    started = json.loads(replies[1]["result"]["content"][0]["text"])
    assert started["outcome"] == "running", started
    return child, started["run_id"]


@needs_server
@pytest.mark.parametrize("run", KILL_DRILLS, ids=[r.id for r in KILL_DRILLS])
def test_codex_style_kill_of_the_mcp_server_is_recovered_with_every_bus_safe(run: LongRun, world: World) -> None:
    name = l9_scenario(world, run.scenario, timing="scaled(0.05)")
    _, plan = validated(world, run)
    assert plan.tier == "needs_confirmation" and "long_run" in plan.confirm_reasons
    child, run_id = start_in_server(world, plan)
    try:
        wait_for(lambda: (p := progress_of(world, run_id)) is not None and p.done >= 1, timeout_s=60)
    finally:
        child.kill()  # SIGKILL / TerminateProcess: no shutdown hook, no cleanup, no finalize (codex-cli 0.170.0)
        child.wait(30)
    wait_for(lambda: InstrumentLock(world.state_dir, f"SIM::{name}").holder() is None, timeout_s=30)
    marker = read_inflight(world.state_dir / "inflight.json")
    assert marker is not None and marker.run == run_id and marker.adapter == "mcp"
    assert marker.auto_calibration_before == "on"  # recorded before CM 0 went out
    assert manifest_of(world, run_id) is None
    residual = every_bus_problem(world, run.scenario)  # blueprint v2 2.6 residual: left on until the recovery
    assert "auto-calibration still off (CM 0)" in residual
    assert any(text in problem for problem in residual for text in RESIDUAL_SIGNS[run.bus]), residual
    # the next turn's server process: the marker blocks new runs with zero instrument I/O until the recovery
    after = world.service(adapter="mcp")
    status = after.station_status(refresh=False)
    assert status.inflight_marker and status.active_run is None
    log_before = len(load_state_file(sim_state_file(world.state_dir, name)).command_log)  # type: ignore[union-attr]
    refused = after.run_confirmed_plan(plan.plan_id or "", plan.summary or "")
    assert refused.outcome == "refused" and "in-flight marker" in refused.message, refused.message
    assert len(load_state_file(sim_state_file(world.state_dir, name)).command_log) == log_before  # type: ignore[union-attr]
    stopped = after.safe_shutdown("harness killed the server mid-run")
    assert stopped.ok and stopped.cleanup is not None and stopped.cleanup.verified == "sim_state", stopped.message
    assert stopped.message.startswith("cleanup verified (sim_state)")
    recovered = [e for e in run_events(world, run_id) if e.ev == "run_status" and e.data and e.data.get("recovered")]
    assert recovered, "the orphaned run was not finalized by the recovery"
    manifest = manifest_of(world, run_id)
    assert manifest is not None and manifest.outcome == "aborted" and manifest.cleanup is not None
    assert manifest.cleanup.verified == "sim_state" and "in-flight recovery" in manifest.message
    assert manifest.confirmed_summary == plan.summary and manifest.confirmed_via == "run_confirmed_plan"
    restore = [s for s in manifest.cleanup.steps if s.step == "restore"]
    assert len(restore) == 1 and restore[0].ok and "recovery of the crashed run" in restore[0].detail
    assert_long_run_invariant(world, run_id, run.scenario)
    progress = progress_of(world, run_id)
    assert progress is not None and progress.state == "failed" and progress.done >= 1
    detail = after.get_run(run_id, include=["summary", "data"])
    assert detail.run is not None and detail.run.outcome == "aborted"
    if partial_rows(world, run_id):
        assert detail.data is not None and "PARTIAL" in detail.data.note
    assert not (world.state_dir / "inflight.json").exists() and not (world.state_dir / "abort.json").exists()
    status = after.station_status(refresh=False)
    assert not status.inflight_marker and status.lock_holder is None and status.active_run is None
