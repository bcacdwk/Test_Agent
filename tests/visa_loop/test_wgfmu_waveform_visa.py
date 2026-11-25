"""The ``wgfmu_waveform`` recipes on backend visa (WP10.4; per-recipe AC ``tests/visa_loop -k <recipe>``; blueprint v2
7.1 visa-loop, 8.1 ``visa_loop/``): the real ``VisaTransport`` over the visa-loop resource manager and the real
``WgfmuDll`` over the fake ABI (``LoopWgfmuLibrary``: ``SimWgfmu`` on the loop's instrument; its online calls fail
while any VISA session holds the exclusive lock, as the lab's VISA would).

Each recipe runs its card request (``WAVEFORM_CASES``) through ``B1500Service`` as on the lab PC: ``validate_plan``
asks for ``first_hw_run`` and ``unverified_topology`` (the example RSUs), the confirmed run completes with its
cleanup verified on the hardware path (``LOP?`` and a complete WGFMU safe state), the library ran only while the FLEX
link's exclusive lock was released and the transaction locked again afterwards (ATV-14), every WGFMU channel ends
disconnected and idle, and the table equals the simulator backend's for the same request. The body-bias case also
switches an SMU on over FLEX inside the same transaction (``LOP?`` positive control before its level).
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

MOSFET = {"pin_map": "mosfet-wgfmu", "dut_profile": "nmos-wgfmu"}
WAVEFORM_CASES: list[dict[str, Any]] = [
    {"recipe_id": "wgfmu.pulsed_iv", "scenario": "nmos_wgfmu", "request": {"params": {}, **MOSFET}, "rows": 21},
    {"recipe_id": "wgfmu.fast_iv", "scenario": "nmos_wgfmu", "request": {"params": {}, **MOSFET}, "rows": 200},
    {"recipe_id": "wgfmu.pulse_train", "scenario": "nmos_wgfmu",
     "request": {"params": {"count": 20, "samples": 3}, **MOSFET}, "rows": 60},
    {"recipe_id": "wgfmu.custom_waveform", "scenario": "nmos_rtn", "request": {"params": {}, **MOSFET},
     "rows": 55200},
    {"recipe_id": "wgfmu.dc_spot", "scenario": "resistor_100k",
     "request": {"params": {}, "pin_map": "resistor-wgfmu", "dut_profile": "resistor-generic"}, "rows": 5},
    {"recipe_id": "wgfmu.rtn", "scenario": "nmos_rtn", "request": {"params": {"points": 20000}, **MOSFET},
     "rows": 20000},
    {"recipe_id": "wgfmu.lfn", "scenario": "nmos_rtn", "request": {"params": {"points": 150000}, **MOSFET},
     "rows": 150000},
]
"""The card example requests on their scenarios (the pulse train and the noise records shortened; the LFN record
still reads back in two 100,000-value chunks per channel through the real ``WgfmuDll``; WP10.5)."""
BODY_CASE: dict[str, Any] = {"recipe_id": "wgfmu.pulsed_iv", "scenario": "nmos_wgfmu", "rows": 5,
                             "request": {"params": {"vg_points": 5, "vb": -0.5}, "pin_map": "mosfet-wgfmu-body",
                                         "dut_profile": "nmos-wgfmu"}}


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


def run_on_visa(world: VisaWorld, case: dict[str, Any], lock_state: list[tuple[str, bool]]) -> tuple[Any, Any]:
    bus = world.bus(case["scenario"])
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert set(validation.confirm_reasons) == set(case.get("reasons", {"first_hw_run", "unverified_topology"}))
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False) and (result.run_id or "").startswith("H")
    assert result.cleanup_verified == "lop"
    # ATV-14: the library ran with the FLEX lock released; the transaction locked again and released at the end
    assert lock_state and all(free for _, free in lock_state)
    assert lock_state[0][0] == "WGFMU_openSession" and lock_state[-1][0] == "WGFMU_closeSession"
    events = bus_events(world.run_events(result.run_id or ""))
    assert events[:3] == ["lock_acquired", "bus_open", "bus_lock"] and events[-3:] == ["bus_unlock", "bus_close",
                                                                                       "lock_released"]
    assert events.count("bus_unlock") == events.count("bus_lock") >= 3  # snapshot read, phase, final release
    assert bus.lock_is_free() and all(s.closed for s in bus.sessions)
    bus.sync_in()
    assert all(not s.connected and not s.running for s in bus.instrument.state.wgfmu.values())
    bus.instrument.assert_safe()
    manifest = json.loads((world.run_dir(result.run_id or "") / "manifest.json").read_text(encoding="utf-8"))
    cleanup = manifest["cleanup"]
    assert cleanup["verified"] == "lop" and not cleanup["latched_fault"]
    rsu = {k: v for k, v in cleanup["switches_after"].items() if k.startswith("RSU")}
    assert "RSU201.OUT" in rsu and set(rsu.values()) == {"open"}  # every RSU the run used is back on its rest path
    assert any("WGFMU phase 1: GPIB link unlocked" in a for a in manifest["assumptions"])
    return bus, result


@pytest.mark.parametrize("case", WAVEFORM_CASES, ids=[c["recipe_id"] for c in WAVEFORM_CASES])
def test_waveform_recipe_runs_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                    tmp_path: Path,
                                                                    lock_state: list[tuple[str, bool]]) -> None:
    bus, result = run_on_visa(world, case, lock_state)
    sent = without_switch_traffic(bus.instrument.command_log)
    assert sent[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"] and "CN" not in sent  # WGFMU only
    names = [name for name, _ in lock_state]
    if case["recipe_id"] == "wgfmu.dc_spot":
        assert "WGFMU_dcforceVoltage" in names and "WGFMU_execute" not in names
    else:
        assert "WGFMU_execute" in names and names.count("WGFMU_getMeasureValues") >= 1
    if case["recipe_id"] == "wgfmu.lfn":  # the lab's layout: both channels measure, each read back in two chunks
        assert names.count("WGFMU_getMeasureValues") == 4
    visa = load_run(result.run_id or "", data_root=world.data).table
    assert len(visa) == case["rows"]
    assert visa.equals(sim_table(case, tmp_path / "sim"))  # same values as the simulator backend


def test_an_smu_body_bias_and_the_wgfmu_share_one_transaction_on_visa(world: VisaWorld, tmp_path: Path,
                                                                     lock_state: list[tuple[str, bool]]) -> None:
    bus, result = run_on_visa(world, BODY_CASE, lock_state)
    sent = without_switch_traffic(bus.instrument.command_log)
    cn = sent.index("CN")
    control = sent.index("LOP?", cn)
    assert sent[cn + 1:control] == ["ERRX?"] and "DV" not in sent[:control]  # positive control before the level
    manifest = json.loads((world.run_dir(result.run_id or "") / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["positive_control"]["ok"] is True
    assert any("(flex_io)" in a for a in manifest["assumptions"])  # FLEX stays open, unlocked, for the bias
    assert load_run(result.run_id or "", data_root=world.data).table.equals(sim_table(BODY_CASE, tmp_path / "sim"))
