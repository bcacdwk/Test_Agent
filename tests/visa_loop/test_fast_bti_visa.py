"""``wgfmu.fast_bti`` and the WGFMU library self-test/cal on backend visa (WP10.7; per-recipe AC ``tests/visa_loop -k
<recipe>``): the real ``VisaTransport`` over the visa-loop resource manager and the real ``WgfmuDll`` over the fake
ABI (``LoopWgfmuLibrary``; its online calls fail while a VISA session holds the exclusive lock, as the lab's VISA
would).

- Fast BTI (scenario ``nmos_bti``, pin map ``mosfet-wgfmu``): ``destructive`` + ``first_hw_run`` +
  ``unverified_topology``; every WGFMU execution runs with the FLEX lock released and the transaction locks again;
  the cleanup is verified on the hardware path (``LOP?`` and a complete WGFMU safe state), every WGFMU channel ends
  disconnected and idle, the RSUs back on their rest path; the table equals the simulator backend's.
- With the SMU body bias (``mosfet-wgfmu-body``, WG Ex. 10/11): ``CN``, the ``LOP?`` positive control and the level
  are sent inside the WGFMU phase (FLEX open without the lock, ``flex_io``), one ``XE`` of the bulk SMU between two
  WGFMU executions: FLEX and library calls interleave in one run.
- ``system.wgfmu_self_test``/``system.wgfmu_self_cal``: confirmed (``first_hw_run`` + the system reason), the
  library's self-test/self-calibration with the lock released, no output switched on, cleanup ``lop``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis import load_run
from tests.integration.helpers import make_world
from tests.visa_loop.helpers import VisaWorld, bus_events, without_switch_traffic
from tests.visa_loop.loop import LoopWgfmuLibrary
from tests.visa_loop.test_sampling_visa import run_to_end

pytestmark = pytest.mark.wgfmu

FAST = {"recipe_id": "wgfmu.fast_bti", "scenario": "nmos_bti",
        "request": {"params": {"vg_stress": 2.0, "stress_time": 10.0}, "pin_map": "mosfet-wgfmu",
                    "dut_profile": "nmos-wgfmu"}}
BODY = {**FAST, "request": {**FAST["request"], "pin_map": "mosfet-wgfmu-body",
                            "params": {"vg_stress": 2.0, "stress_time": 10.0, "vb": -0.5}}}
SYSTEM = [{"recipe_id": r, "scenario": "nmos_bti", "request": {"pin_map": "mosfet-wgfmu"}}
          for r in ("system.wgfmu_self_test", "system.wgfmu_self_cal")]


@pytest.fixture
def lock_state(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """``(C function, exclusive VISA lock free)`` at each library call."""
    seen: list[tuple[str, bool]] = []
    original = LoopWgfmuLibrary.dispatch

    def dispatch(self: LoopWgfmuLibrary, name: str, args: tuple[Any, ...]) -> int:
        seen.append((name, self.bus.lock_is_free()))
        return original(self, name, args)

    monkeypatch.setattr(LoopWgfmuLibrary, "dispatch", dispatch)
    return seen


def sim_table(case: dict[str, Any], tmp_path: Path) -> Any:
    world = make_world(tmp_path)
    world.use_scenario(case["scenario"])
    service = world.service()
    try:
        _, result = run_to_end(service, case)
    finally:
        service.close()
    assert result.ok and result.backend == "sim", result.message
    return load_run(result.run_id or "", data_root=world.data).table


def run_on_visa(world: VisaWorld, case: dict[str, Any], lock_state: list[tuple[str, bool]],
                reasons: set[str]) -> tuple[Any, Any, dict[str, Any]]:
    bus = world.bus(case["scenario"])
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert set(validation.confirm_reasons) == reasons
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False) and (result.run_id or "").startswith("H")
    assert result.cleanup_verified == "lop"
    assert lock_state and all(free for _, free in lock_state)  # ATV-14: the library only with the lock released
    assert lock_state[-1][0] == "WGFMU_closeSession"
    events = bus_events(world.run_events(result.run_id or ""))
    assert events[:3] == ["lock_acquired", "bus_open", "bus_lock"] and events[-3:] == ["bus_unlock", "bus_close",
                                                                                       "lock_released"]
    assert events.count("bus_unlock") == events.count("bus_lock")
    assert bus.lock_is_free() and all(s.closed for s in bus.sessions)
    bus.sync_in()
    assert all(not s.connected and not s.running for s in bus.instrument.state.wgfmu.values())
    bus.instrument.assert_safe()
    manifest = json.loads((world.run_dir(result.run_id or "") / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["verified"] == "lop" and not manifest["cleanup"]["latched_fault"]
    return bus, result, manifest


def test_fast_bti_runs_on_backend_visa_with_cleanup_verified(world: VisaWorld, tmp_path: Path,
                                                            lock_state: list[tuple[str, bool]]) -> None:
    bus, result, manifest = run_on_visa(world, FAST, lock_state,
                                        {"destructive", "first_hw_run", "unverified_topology"})
    names = [name for name, _ in lock_state]
    runs = manifest["kind_result"]["runs_done"]
    assert names.count("WGFMU_execute") == runs >= 2 and names.count("WGFMU_update") == runs
    assert names.count("WGFMU_openSession") == 2  # the pre-execute channel read and the one phase of every run
    sent = without_switch_traffic(bus.instrument.command_log)
    assert "CN" not in sent and sent[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    rsu = {k: v for k, v in manifest["cleanup"]["switches_after"].items() if k.startswith("RSU")}
    assert set(rsu) == {"RSU201.OUT", "RSU202.OUT"} and set(rsu.values()) == {"open"}
    visa = load_run(result.run_id or "", data_root=world.data).table
    assert len(visa) == 14 * 17 + 13  # the reference and 13 reads (1 ms .. 10 s, 3 per decade), 13 holds
    assert visa.equals(sim_table(FAST, tmp_path / "sim"))


def test_an_smu_bias_and_the_wgfmu_interleave_in_one_run_on_visa(world: VisaWorld, tmp_path: Path,
                                                                lock_state: list[tuple[str, bool]]) -> None:
    bus, result, manifest = run_on_visa(world, BODY, lock_state,
                                        {"destructive", "first_hw_run", "unverified_topology"})
    sent = without_switch_traffic(bus.instrument.command_log)
    cn = sent.index("CN")
    control = sent.index("LOP?", cn)
    assert sent[cn + 1:control] == ["ERRX?"] and "DV" not in sent[:control]  # positive control before the level
    assert manifest["cleanup"]["positive_control"]["ok"] is True
    assert any("(flex_io)" in a for a in manifest["assumptions"])
    runs = manifest["kind_result"]["runs_done"]
    assert sent.count("XE") == runs - 1 == manifest["kind_result"]["bulk_I_reads"]
    order = [e for e in world.run_events(result.run_id or "")
             if e.ev == "wgfmu_call" or (e.ev in ("write", "query") and e.cmd in ("CN 5", "XE"))]
    labels = [str((e.data or {}).get("fn")) if e.ev == "wgfmu_call" else str(e.cmd) for e in order]
    executes = [i for i, label in enumerate(labels) if label == "execute"]
    xes = [i for i, label in enumerate(labels) if label == "XE"]
    assert labels.index("initialize") < labels.index("CN 5") < executes[0]
    assert all(executes[k] < xes[k] < executes[k + 1] for k in range(len(xes)))  # FLEX between library runs
    assert load_run(result.run_id or "", data_root=world.data).table.equals(sim_table(BODY, tmp_path / "sim"))


@pytest.mark.parametrize("case", SYSTEM, ids=[c["recipe_id"] for c in SYSTEM])
def test_wgfmu_system_recipe_runs_confirmed_on_backend_visa(case: dict[str, Any], world: VisaWorld,
                                                           lock_state: list[tuple[str, bool]]) -> None:
    reason = "system_" + case["recipe_id"].split(".")[1].replace("wgfmu_", "")
    bus, _, manifest = run_on_visa(world, case, lock_state, {"first_hw_run", reason})
    call = "WGFMU_doSelfTest" if case["recipe_id"].endswith("self_test") else "WGFMU_doSelfCalibration"
    names = [name for name, _ in lock_state]
    assert names.count(call) == 1 and names.index("WGFMU_initialize") < names.index(call)
    assert manifest["kind_result"] == {"operation": case["recipe_id"].split(".")[1], "result": 0,
                                       "failed_units": "", "via": "WGFMU instrument library"}
    sent = without_switch_traffic(bus.instrument.command_log)
    assert "CN" not in sent and "*TST?" not in sent and "*CAL?" not in sent
    assert manifest["cleanup"]["positive_control"] is None
