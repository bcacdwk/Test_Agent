"""The sampling recipes on backend visa through the real ``VisaTransport`` (WP7.4; per-recipe AC ``tests/visa_loop
-k <recipe>``; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``).

Each recipe runs its card example request through ``B1500Service`` as on the lab PC: ``validate_plan`` asks for
``first_hw_run`` (plus the recipe's own reasons: ``destructive``/``long_run`` for TDDB, ``adhoc_recipe`` for the
generic recipe) and the confirmed run completes with its cleanup verified by ``LOP?`` (and the ``LOP?`` positive
control after ``CN``), the bus opened, locked, unlocked and closed inside the transaction, the data read in several
VISA chunks, and the same ``data.csv`` bytes as the simulator backend produces for the same request. The TDDB case
also runs asynchronously over VISA: one bus session for its chain of ``MM 10`` blocks, aborted at breakdown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.service import B1500Service
from tests.integration.helpers import make_world
from tests.visa_loop.helpers import VisaWorld, bus_events

CHUNK = 256
GENERIC_CONFIG: dict[str, Any] = {
    "pinmaps/generic-sampling-2t.yaml": {"certainty": "verified", "terminals": {"stress": 3, "ground": "GNDU"}},
    "duts/generic-sampling-2t.yaml": {"device_type": "resistor", "terminals": {
        "stress": {"max_abs_v": 2.0, "max_abs_i": 1e-3}, "ground": {"max_abs_v": 0.0, "max_abs_i": 1e-3}}},
}
SAMPLING_CASES: list[dict[str, Any]] = [
    {"recipe_id": "mosfet.id_t_sampling", "scenario": "igzo_transient", "reasons": ["first_hw_run"],
     "request": {"params": {"vd": 0.1, "points": 2001}, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}},
    {"recipe_id": "generic.smu_sampling", "scenario": "resistor_100k", "config": GENERIC_CONFIG,
     "reasons": ["adhoc_recipe", "first_hw_run"],
     "request": {"params": {"bias": 1.0, "points": 501}, "pin_map": "generic-sampling-2t",
                 "dut_profile": "generic-sampling-2t"}},
    {"recipe_id": "reliability.tddb_cvs", "scenario": "dielectric_tddb",
     "reasons": ["destructive", "first_hw_run", "long_run"],
     "request": {"params": {"v_stress": 5.5, "duration": 600.0}, "pin_map": "mosfet-4t",
                 "dut_profile": "dielectric-generic"}},
]
"""The card example requests (the id_t one shortened to 2,001 samples to keep the suite fast)."""


def run_to_end(service: B1500Service, case: dict[str, Any]) -> tuple[Any, RunSummary]:
    validation = service.validate_plan(recipe_id=case["recipe_id"], **case["request"])
    assert validation.ok and validation.plan_id is not None and validation.summary is not None, validation.message
    result = (service.run_plan(validation.plan_id) if validation.tier == "ok"
              else service.run_confirmed_plan(validation.plan_id, summary=validation.summary))
    if result.outcome == "running":
        final = service.follow_run(result.run_id or "")
        assert final is not None
        result = final
    return validation, result


def sim_data(case: dict[str, Any], tmp_path: Path) -> bytes:
    world = make_world(tmp_path)
    world.use_scenario(case["scenario"])
    for rel, data in case.get("config", {}).items():
        world.write_config(rel, data)
    service = world.service()
    try:
        _, result = run_to_end(service, case)
    finally:
        service.close()
    assert result.ok and result.backend == "sim", result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    return (folder / DATA_FILE).read_bytes()


@pytest.mark.parametrize("case", SAMPLING_CASES, ids=[c["recipe_id"] for c in SAMPLING_CASES])
def test_sampling_recipe_runs_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                    tmp_path: Path) -> None:
    for rel, data in case.get("config", {}).items():
        world.write_local(rel, data)
    bus = world.bus(case["scenario"], chunk_size=CHUNK)
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert sorted(validation.confirm_reasons) == case["reasons"]
    assert result.ok and result.outcome in ("completed", "completed_with_flags"), result.message
    assert (result.backend, result.simulated) == ("visa", False) and (result.run_id or "").startswith("H")
    assert result.cleanup_verified == "lop"
    assert bus_events(world.run_events(result.run_id or "")) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.max_chunks > 1 and bus.stats.signed_errx > 0
    bus.instrument.assert_safe()

    sent = [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"]
    assert sent[-3:] == ["CL", "ERRX?", "LOP?"] and "TSR" in sent and "MM" in sent
    cn = sent.index("CN")
    control = sent.index("LOP?", cn)
    assert sent[cn + 1:control] == ["ERRX?"] and not {"DV", "MV", "MI", "XE"} & set(sent[:control])
    folder = world.run_dir(result.run_id or "")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["positive_control"]["ok"] is True
    assert manifest["kind_result"]["time_source"] == "timestamp"
    if case["recipe_id"] == "reliability.tddb_cvs":
        assert manifest["plan"]["mode"] == "async" and manifest["kind_result"]["aborted"] is True
        assert sent.count("XE") == manifest["kind_result"]["blocks_done"] == 5
        (t_bd,) = result.analyses
        assert t_bd.classification == "breakdown"

    assert (folder / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")
