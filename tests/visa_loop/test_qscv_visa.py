"""``moscap.qscv`` (kind ``smu_qscv``, MM 13) on backend visa through the real ``VisaTransport`` (blueprint v2 7.1
visa-loop, 10 per-recipe AC; WP8.5).

The card example (pin map ``moscap-scuu`` on ``moscap_dit``, a station profile that records SCUU1 present, as the
human does at stage L6) and its offset measurement run through ``B1500Service`` exactly as on the lab PC: every plan is
``needs_confirmation`` (``first_hw_run``, ``unverified_pin_map``, ``unverified_topology``; the offset run also
``physical_setup``), ``SSP 7,3`` switches the two SMUs on (never ``CN``), the ``LOP?`` positive control covers both,
the cleanup verifies with ``LOP?`` and the SCUU read-back, one bus session per transaction, the data block comes in
small VISA chunks, and ``data.csv`` holds the same bytes as the same request on backend sim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.models.station import channel_slot
from tests.integration.helpers import make_world
from tests.visa_loop.helpers import SWITCH_LEARN, SWITCH_MNEMONICS, VisaWorld, bus_events, run_case
from tests.visa_loop.test_cv_visa import scuu_station

CHUNK = 64
CASE: dict[str, Any] = {"recipe_id": "moscap.qscv", "scenario": "moscap_dit", "source": "card moscap-dit",
                        "request": {"params": {}, "pin_map": "moscap-scuu", "dut_profile": "moscap-generic"}}


def sim_data(tmp_path: Path) -> bytes:
    world = make_world(tmp_path)
    world.use_scenario(CASE["scenario"])
    service = world.service()
    try:
        result = run_case(service, CASE)
    finally:
        service.close()
    assert result.ok and result.backend == "sim", result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    return (folder / DATA_FILE).read_bytes()


@pytest.mark.parametrize("recipe_id", ["moscap.qscv"])  # so that ``-k moscap.qscv`` selects it
def test_qscv_completes_on_backend_visa_with_cleanup_verified(recipe_id: str, world: VisaWorld, tmp_path: Path) -> None:
    world.write_local("station.yaml", scuu_station())
    bus = world.bus(CASE["scenario"], chunk_size=CHUNK)
    service = world.service(bus)
    validation = service.validate_plan(recipe_id=CASE["recipe_id"], **CASE["request"])
    assert validation.backend == "visa" and not validation.simulated and validation.tier == "needs_confirmation"
    assert {"first_hw_run", "unverified_pin_map", "unverified_topology"} <= set(validation.confirm_reasons)
    result = run_case(service, CASE)
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False) and result.run_id.startswith("H")  # type: ignore[union-attr]
    assert result.cleanup_verified == "lop"
    assert bus_events(world.run_events(result.run_id)) == [  # type: ignore[arg-type]
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.opens == bus.stats.closes and bus.lock_is_free() and bus.stats.max_chunks > 1
    bus.instrument.assert_safe()

    manifest = json.loads((world.run_dir(result.run_id) / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[arg-type]
    cleanup = manifest["cleanup"]
    control = cleanup["positive_control"]
    assert control["ok"] is True and sorted(control["channels"]) == [5, 6]
    assert all(control["codes"][str(channel_slot(ch))] != "00" for ch in (5, 6))
    assert set(cleanup["outputs_after"].values()) == {"00"} and cleanup["verified"] == "lop"
    assert (cleanup["switches_after"]["SCUU1.OUT1"], cleanup["switches_after"]["SCUU1.OUT2"]) == ("smu", "smu")
    log = [r for r in bus.instrument.command_log if r.outcome == "ok" and r.mnemonic not in SWITCH_MNEMONICS
           and r.command not in SWITCH_LEARN]
    commands = [r.command for r in log]
    start = commands.index("SSP 7,3")
    run_part = [r.mnemonic for r in log][start:]
    assert run_part[:5] == ["SSP", "ERRX?", "LOP?", "DV", "MM"] and "XE" in run_part
    assert run_part[-5:] == ["DZ", "CL", "ERRX?", "LOP?", "SPST?"] and "CN" not in run_part
    assert (world.run_dir(result.run_id) / DATA_FILE).read_bytes() == sim_data(tmp_path / "sim")  # type: ignore[arg-type]


@pytest.mark.parametrize("recipe_id", ["moscap.qscv"])
def test_qscv_offset_measurement_on_backend_visa(recipe_id: str, world: VisaWorld) -> None:
    world.write_local("station.yaml", scuu_station())
    bus = world.bus(CASE["scenario"], chunk_size=CHUNK)
    service = world.service(bus)
    case = {**CASE, "request": {**CASE["request"], "params": {"offset": "measure"}}}
    validation = service.validate_plan(recipe_id=case["recipe_id"], **case["request"])
    assert "physical_setup" in validation.confirm_reasons
    result = run_case(service, case)
    assert result.ok and result.outcome == "completed" and result.cleanup_verified == "lop", result.message
    commands = [r.command for r in bus.instrument.command_log if r.outcome == "ok"]
    assert "QSZ 2" in commands and "XE" not in commands[commands.index("QSZ 2"):]
    assert bus.instrument.state.qscv_offsets  # stored in the instrument for a later offset: cancel
    bus.instrument.assert_safe()
