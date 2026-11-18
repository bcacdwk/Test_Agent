"""The seven v1 measurement recipes on backend visa through the real ``VisaTransport`` (blueprint v2 10.1 row 5.5 AC,
7.1 "visa-loop", 8.1 ``visa_loop/``).

Each recipe runs its card example request (the WP5.2 golden requests) through ``B1500Service`` exactly as on the
lab PC: ``config/local/`` selects backend visa, ``validate_plan`` asks for a human confirmation (``first_hw_run``,
expected during bring-up, blueprint 7.2) and ``run_confirmed_plan`` runs it. The only stand-in is the VISA library:
the visa-loop resource manager forwards the session to the simulator. Every run must complete, verify its cleanup
with ``LOP?`` (the hardware path), open/lock/unlock/close the bus inside its own transaction, read its data in
several VISA chunks, parse the signed ``+0,"No Error."`` answers of the lab firmware, and produce byte for byte the
same ``data.csv`` as the simulator backend does for the same request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from tests.integration.helpers import make_world
from tests.visa_loop.helpers import MEASUREMENT_CASES, VisaWorld, bus_events, run_case

CHUNK = 256
"""Small VISA chunks so that every data block needs several reads (pyvisa's default is 20 kB)."""


def sim_data(case: dict[str, Any], tmp_path: Path) -> bytes:
    """``data.csv`` of the same request on backend sim (the v1 path)."""
    world = make_world(tmp_path)
    world.use_scenario(case["scenario"])
    for rel, data in case.get("config", {}).items():
        world.write_config(rel, data)
    service = world.service()
    try:
        result = run_case(service, case)
    finally:
        service.close()
    assert result.ok and result.backend == "sim", result.message
    return next(world.runs_dir.rglob(f"{result.run_id}/{DATA_FILE}")).read_bytes()


def test_the_suite_covers_exactly_the_seven_v1_measurement_recipes() -> None:
    assert sorted(c["recipe_id"] for c in MEASUREMENT_CASES) == [
        "basic.contact_resistor", "basic.diode_iv", "fefet.dual_sweep_mw", "generic.smu_staircase",
        "mosfet.gate_leakage", "mosfet.idvd", "mosfet.idvg"]


@pytest.mark.parametrize("case", MEASUREMENT_CASES, ids=[c["recipe_id"] for c in MEASUREMENT_CASES])
def test_v1_recipe_completes_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                   tmp_path: Path) -> None:
    bus = world.bus(case["scenario"], chunk_size=CHUNK)
    service = world.service(bus)
    validation = service.validate_plan(recipe_id=case["recipe_id"], **case["request"])
    assert validation.backend == "visa" and not validation.simulated
    assert validation.tier == "needs_confirmation" and "first_hw_run" in validation.confirm_reasons

    result = run_case(service, case)
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False)
    assert result.run_id is not None and result.run_id.startswith("H")
    assert result.cleanup_verified == "lop"  # verified with LOP? on the hardware path, not the simulator state

    # the bus lived exactly as long as the transaction: opened and locked after the instrument lock, released before
    assert bus_events(world.run_events(result.run_id)) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.opens == bus.stats.closes and bus.stats.locks == bus.stats.unlocks >= 1
    assert all(session.closed for session in bus.sessions) and bus.lock_is_free()
    assert service.executor.session(service.config.get()).bus_open is False

    # the wire: multi-chunk data reads, the lab's signed ERRX? answers, the configured library string
    assert bus.stats.max_chunks > 1 and bus.stats.signed_errx > 0
    assert bus.stats.library == "@ivi"
    instrument = bus.instrument
    instrument.assert_safe()
    sent = [r.mnemonic for r in instrument.command_log if r.outcome == "ok"]
    assert sent[-3:] == ["CL", "ERRX?", "LOP?"] and "XE" in sent and "DZ" in sent

    # same physics, same bytes: the visa path reproduces the simulator path exactly
    visa_data = (world.run_dir(result.run_id) / DATA_FILE).read_bytes()
    assert visa_data == sim_data(case, tmp_path / "sim")


def test_a_second_run_and_a_status_reuse_nothing_from_the_first_session(world: VisaWorld) -> None:
    """Every call opens its own VISA session: two runs and two status snapshots = four sessions, all closed."""
    case = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "mosfet.idvg")
    bus = world.bus(case["scenario"])
    service = world.service(bus)
    assert service.station_status().ok
    for _ in range(2):
        assert run_case(service, case).ok
    assert service.station_status().ok
    assert bus.stats.opens == bus.stats.closes == 4 and bus.stats.locks == bus.stats.unlocks == 4
    assert len(bus.sessions) == 4 and all(s.closed for s in bus.sessions) and bus.lock_is_free()
