"""The stress-measure recipes on backend visa through the real ``VisaTransport`` (WP7.6; per-recipe AC ``tests/visa_loop
-k <recipe>``; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``).

Each recipe runs a shortened card request (``STRESS_CASES``) through
``B1500Service`` as on the lab PC: ``validate_plan`` asks for ``first_hw_run`` and ``destructive``, the confirmed run
completes with its cleanup verified by ``LOP?`` (and the ``LOP?`` positive control right after ``CN``), the bus opened,
locked, unlocked and closed once around the whole composite run (reads and instrument-timed hold blocks), the data
read in several VISA chunks, and the same ``data.csv`` bytes as the simulator backend produces for the same request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from tests.visa_loop.helpers import VisaWorld, bus_events
from tests.visa_loop.test_sampling_visa import run_to_end, sim_data

CHUNK = 256
SHORT = {"stress_time": 30.0, "reads_per_decade": 1}
BASE = {"pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
STRESS_CASES: list[dict[str, Any]] = [
    {"recipe_id": "reliability.bti_sms", "scenario": "nmos_bti", "reads": 6, "holds": 5,
     "request": {"params": {"vg_stress": 2.0, **SHORT, "recovery_time": 10.0}, **BASE}},
    {"recipe_id": "igzo.bias_stress", "scenario": "igzo_transient", "reads": 12, "holds": 11,
     "request": {"params": {"vg_stress": 3.0, "stress_time": 30.0}, **BASE}},
    {"recipe_id": "reliability.hci", "scenario": "nmos_bti", "reads": 4, "holds": 3, "chunk": 16,
     "request": {"params": {"vg_stress": 1.2, "vd_stress": 2.5, **SHORT}, **BASE}},
    {"recipe_id": "reliability.silc", "scenario": "nmos_bti", "reads": 6, "holds": 7, "chunk": 16,
     "request": {"params": {"vg_stress": 2.8, "stress_time": 100.0, "reads_per_decade": 2}, **BASE}},
]
"""Card requests shortened to 30 s of stress (the BTI one with a recovery; IGZO keeps its 4 reads per decade from
0.1 s: the stretched-exponential fit needs 8 reads; SILC 100 s at 2 per decade: its exponent needs 3 reads with a
2 % change). The spot-read recipes use 16-byte VISA chunks (a spot block is one element per channel)."""


@pytest.mark.parametrize("case", STRESS_CASES, ids=[c["recipe_id"] for c in STRESS_CASES])
def test_stress_recipe_runs_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                  tmp_path: Path) -> None:
    bus = world.bus(case["scenario"], chunk_size=case.get("chunk", CHUNK))
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert sorted(validation.confirm_reasons) == ["destructive", "first_hw_run"]
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False) and (result.run_id or "").startswith("H")
    assert result.cleanup_verified == "lop"
    assert bus_events(world.run_events(result.run_id or "")) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.max_chunks > 1 and bus.stats.signed_errx > 0
    bus.instrument.assert_safe()

    sent = [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"]
    # v2 cleanup on the lab mainframe (SPGU in slot 1): SPST? (no SPP: inactive), DZ, CL, drain, LOP? + SPST? verify
    assert sent[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"] and "MT" in sent and "SPP" not in sent
    cn = sent.index("CN")
    assert sent.index("TSC") < cn  # time stamps off before the outputs: the read parsers expect none
    control = sent.index("LOP?", cn)
    assert sent[cn + 1:control] == ["ERRX?"] and not {"DV", "WV", "XE"} & set(sent[:control])
    assert sent.count("XE") >= case["reads"] + case["holds"]
    folder = world.run_dir(result.run_id or "")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["positive_control"]["ok"] is True
    assert (manifest["kind_result"]["reads_done"], manifest["kind_result"]["holds_done"]) == (case["reads"],
                                                                                             case["holds"])
    assert {a.outcome for a in result.analyses} == {"ok"}

    assert (folder / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")
