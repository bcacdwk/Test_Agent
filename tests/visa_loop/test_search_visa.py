"""The SMU search recipes on backend visa through the real ``VisaTransport`` (WP7.5; per-recipe AC ``tests/visa_loop
-k <recipe>``; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``).

Each recipe runs its request (``SEARCH_CASES``: the card example of ``mosfet.vth_search``, the breakdown recipes with
the ramp ends a human would choose) through ``B1500Service`` as on the lab PC: ``validate_plan`` asks for
``first_hw_run`` (plus ``destructive`` and the envelope reasons of the breakdown recipes), the confirmed run completes
with its cleanup verified by ``LOP?`` (and the ``LOP?`` positive control right after ``CN``), the bus opened, locked,
unlocked and closed once, the search setup sent before the one ``XE`` in the PG example order, the result read in
several VISA chunks, and the same ``data.csv`` bytes as the simulator backend produces for the same request. The
local station records the RSU "From SMU" inputs as the scenario cables them (none), as bring-up L8 does: with them
unknown, R-RSU-01 blocks the 30 V BDV ramp on visa (WP21.13).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from tests.visa_loop.helpers import VisaWorld, assert_selectors_restored, bus_events, without_switch_traffic
from tests.visa_loop.test_sampling_visa import run_to_end, sim_data

pytestmark = pytest.mark.smu

SEARCH_CASES: list[dict[str, Any]] = [
    {"recipe_id": "mosfet.vth_search", "scenario": "nmos_basic", "chunk": 8, "mode": 15,
     "reasons": ["first_hw_run"], "setup": ["MM", "BSM", "BSVM", "BST", "BGI", "BSV"],
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}},
    {"recipe_id": "basic.breakdown_search", "scenario": "diode_basic", "chunk": 8, "mode": 14,
     "reasons": ["destructive", "dut_envelope", "first_hw_run", "soft_limit"],
     "setup": ["MM", "LSM", "LSVM", "LSTM", "LGI", "LSV"],
     "request": {"params": {"v_stop": -20.0}, "pin_map": "diode-2t", "dut_profile": "diode-generic"}},
    {"recipe_id": "dielectric.bdv", "scenario": "dielectric_thick", "chunk": 8, "mode": 9,
     "reasons": ["destructive", "first_hw_run", "soft_limit"], "setup": ["MM", "BDT", "BDM", "BDV"],
     "request": {"params": {"v_stop": 30.0}, "pin_map": "mosfet-4t", "dut_profile": "dielectric-thick"}},
]
"""The search recipes with their scenarios; 8-byte VISA chunks keep the chunked read path exercised (a search returns
one or two elements)."""


@pytest.mark.parametrize("case", SEARCH_CASES, ids=[c["recipe_id"] for c in SEARCH_CASES])
def test_search_recipe_runs_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                  tmp_path: Path) -> None:
    world.record_rsu_inputs(case["scenario"])
    bus = world.bus(case["scenario"], chunk_size=case["chunk"])
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert sorted(validation.confirm_reasons) == case["reasons"]
    assert result.ok and result.outcome in ("completed", "completed_with_flags"), result.message
    assert (result.backend, result.simulated) == ("visa", False) and (result.run_id or "").startswith("H")
    assert result.cleanup_verified == "lop"
    assert bus_events(world.run_events(result.run_id or "")) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.max_chunks > 1
    bus.instrument.assert_safe()

    sent = without_switch_traffic(bus.instrument.command_log)
    assert_selectors_restored(bus.instrument.command_log)
    assert sent[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    cn = sent.index("CN")
    control = sent.index("LOP?", cn)
    sources = {"DV", "LSV", "BSV", "BDV", "XE"}
    assert sent[cn + 1:control] == ["ERRX?"] and not sources & set(sent[:control])
    xe = sent.index("XE")
    setup = [m for m in sent[control:xe] if m in set(case["setup"])]
    assert setup == case["setup"]  # the search setup in the PG example order, before the one trigger
    assert sent.count("XE") == 1
    folder = world.run_dir(result.run_id or "")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["positive_control"]["ok"] is True
    assert manifest["kind_result"]["measurement_mode"] == case["mode"] and manifest["kind_result"]["found"] is True
    assert {a.outcome for a in result.analyses} == {"ok"}

    assert (folder / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")
