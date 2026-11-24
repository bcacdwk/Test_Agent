"""The SMU pulsed recipes on backend visa through the real ``VisaTransport`` (WP7.3; per-recipe AC ``tests/visa_loop
-k <recipe>``; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``).

Each recipe runs its card request (``PULSED_CASES``) through ``B1500Service`` as on the lab PC: ``validate_plan`` asks
for ``first_hw_run`` (and ``adhoc_recipe`` for the generic one), the confirmed run completes with its cleanup verified
by ``LOP?`` (and the ``LOP?`` positive control right after ``CN``), the bus opened, locked, unlocked and closed once,
the pulsed setup sent before ``XE`` (``AIT 2`` and the mode's timing and source commands), the data read in several
VISA chunks, and the same ``data.csv`` bytes as the simulator backend produces for the same request.
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

MOSFET = {"pin_map": "mosfet-4t", "dut_profile": "nmos-pulsed"}
RESISTOR = {"pin_map": "resistor-2t", "dut_profile": "resistor-pulsed"}
PULSED_CASES: list[dict[str, Any]] = [
    {"recipe_id": "mosfet.idvg_pulsed", "scenario": "nmos_selfheat", "chunk": 64, "triggers": 1,
     "setup": ["AIT", "MM", "CMM", "PT", "PWV", "WM"], "request": {"params": {"vd": 3.0}, **MOSFET}},
    {"recipe_id": "mosfet.idvd_pulsed", "scenario": "nmos_selfheat", "chunk": 64, "triggers": 5,
     "setup": ["AIT", "MM", "CMM", "PT", "WV", "PV", "WM"], "request": {"params": {}, **MOSFET}},
    {"recipe_id": "basic.pulsed_spot", "scenario": "resistor_100k", "chunk": 8, "triggers": 4,
     "setup": ["AIT", "MM", "CMM", "PT", "PV"], "request": {"params": {}, **RESISTOR}},
    {"recipe_id": "generic.smu_multi_pulsed", "scenario": "resistor_100k", "chunk": 64, "triggers": 1,
     "setup": ["AIT", "MCPT", "MCPNT", "MCPWS", "MCPWNX", "MM", "CMM", "WM"], "request": {"params": {}, **RESISTOR}},
]
"""The card example requests (``mosfet.idvg_pulsed`` at the card's ``vd`` 3 V) on their scenarios; the spot recipe
reads one element per trigger, so it uses 8-byte VISA chunks to keep the chunked path exercised."""


@pytest.mark.parametrize("case", PULSED_CASES, ids=[c["recipe_id"] for c in PULSED_CASES])
def test_pulsed_recipe_runs_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                  tmp_path: Path) -> None:
    bus = world.bus(case["scenario"], chunk_size=case["chunk"])
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    expected = {"first_hw_run"} | ({"adhoc_recipe"} if case["recipe_id"].startswith("generic.") else set())
    assert set(validation.confirm_reasons) == expected
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False) and (result.run_id or "").startswith("H")
    assert result.cleanup_verified == "lop"
    assert bus_events(world.run_events(result.run_id or "")) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.max_chunks > 1
    bus.instrument.assert_safe()

    sent = without_switch_traffic(bus.instrument.command_log)
    # v2 cleanup on the lab mainframe: SPST?, DZ, CL, drain, LOP? + SPST? verify; the declared selectors' rest and
    # verify traffic (WP9.2) is checked by assert_selectors_restored
    assert_selectors_restored(bus.instrument.command_log)
    assert sent[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    cn = sent.index("CN")
    control = sent.index("LOP?", cn)
    assert sent[cn + 1:control] == ["ERRX?"] and not {"DV", "PV", "PWV", "MCPNX", "XE"} & set(sent[:control])
    first_xe = sent.index("XE")
    setup = [m for m in sent[control:first_xe] if m in set(case["setup"])]
    assert setup == case["setup"]  # the pulsed setup in the PG example order, before the first trigger
    assert sent.count("XE") == case["triggers"]
    folder = world.run_dir(result.run_id or "")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["positive_control"]["ok"] is True
    assert manifest["kind_result"]["triggers_done"] == case["triggers"]
    assert {a.outcome for a in result.analyses} <= {"ok"}

    assert (folder / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")
