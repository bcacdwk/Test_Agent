"""The nine v1 runnable recipes on backend visa through the real ``VisaTransport`` (blueprint v2 10.1 row 5.5 AC,
10.2 row 6.2 AC "visa-loop runs ``system.*`` (confirmed)", 7.1 "visa-loop", 8.1 ``visa_loop/``).

Each recipe runs its card example request (the WP5.2 golden requests) through ``B1500Service`` exactly as on the
lab PC: ``config/local/`` selects backend visa, ``validate_plan`` asks for a human confirmation (``first_hw_run``,
expected during bring-up, blueprint 7.2; ``system.*`` also ``system_self_test``/``system_self_cal``) and
``run_confirmed_plan`` runs it. The only stand-in is the VISA library: the visa-loop resource manager forwards the
session to the simulator. Every run must complete, verify its cleanup with ``LOP?`` (the hardware path),
open/lock/unlock/close the bus inside its own transaction and parse the signed ``+0,"No Error."`` answers of the lab
firmware. The seven measurement recipes also read their data in several VISA chunks, produce byte for byte the same
``data.csv`` as the simulator backend does for the same request and carry the ``LOP?`` positive control (the
switched-on SMUs read non-``00`` between ``CN`` and the first level, all slots ``00`` after ``CL``) in their
manifest and audit; ``system.*`` switches no output on and sends exactly its one query.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.models.station import channel_slot
from tests.integration.helpers import make_world
from tests.visa_loop.helpers import (
    DATA_CASES,
    MEASUREMENT_CASES,
    SYSTEM_CASES,
    VisaWorld,
    bus_events,
    run_case,
)

CHUNK = 256
"""Small VISA chunks so that every data block needs several reads (pyvisa's default is 20 kB)."""

SYSTEM_QUERIES = {"system.self_test": "*TST?", "system.self_cal": "*CAL?"}


def sim_run(case: dict[str, Any], tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Run folder and manifest of the same request on backend sim (the v1 path)."""
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
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    return folder, json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def run_on_visa(world: VisaWorld, case: dict[str, Any], **bus_kwargs: Any) -> tuple[Any, Any, Any]:
    """Validate (backend visa, ``needs_confirmation`` with ``first_hw_run``) and run ``case`` confirmed; returns the
    bus, the validation and the run summary after the checks every visa run shares."""
    bus = world.bus(case["scenario"], **bus_kwargs)
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
    # the lab's signed ERRX? answers and the configured library string
    assert bus.stats.signed_errx > 0 and bus.stats.library == "@ivi"
    bus.instrument.assert_safe()
    return bus, validation, result


def test_the_suite_covers_every_v1_runnable_recipe() -> None:
    assert sorted(c["recipe_id"] for c in MEASUREMENT_CASES) == [
        "basic.contact_resistor", "basic.diode_iv", "fefet.dual_sweep_mw", "generic.smu_staircase",
        "mosfet.gate_leakage", "mosfet.idvd", "mosfet.idvg", "system.self_cal", "system.self_test"]
    assert sorted(c["recipe_id"] for c in SYSTEM_CASES) == ["system.self_cal", "system.self_test"]
    assert len(DATA_CASES) == 7


@pytest.mark.parametrize("case", DATA_CASES, ids=[c["recipe_id"] for c in DATA_CASES])
def test_v1_recipe_completes_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                   tmp_path: Path) -> None:
    bus, _, result = run_on_visa(world, case, chunk_size=CHUNK)
    assert bus.stats.max_chunks > 1  # multi-chunk data reads
    sent = [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"]
    assert sent[-3:] == ["CL", "ERRX?", "LOP?"] and "XE" in sent and "DZ" in sent

    # LOP? positive control: read after CN (outputs on at 0 V) and before any level or trigger
    cn = sent.index("CN")
    control_at = sent.index("LOP?", cn)
    assert sent[cn + 1:control_at] == ["ERRX?"]
    assert not {"DV", "WV", "XE"} & set(sent[:control_at])
    folder = world.run_dir(result.run_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    cleanup = manifest["cleanup"]
    control = cleanup["positive_control"]
    enabled = next(r.args for r in bus.instrument.command_log if r.mnemonic == "CN")
    assert control["ok"] is True and control["channels"] == [int(ch) for ch in enabled]
    assert control["codes"] == {str(channel_slot(int(ch))): "01" for ch in enabled}  # forcing 0 V, no compliance
    assert set(cleanup["outputs_after"].values()) == {"00"} and cleanup["verified"] == "lop"
    events = world.run_events(result.run_id)
    # off in the pre-execute snapshot, on (the control) while connected, off again after the cleanup's CL
    all_off = "LOP" + ",".join(["00"] * 10)
    on = "LOP" + ",".join(control["codes"].get(str(slot), "00") for slot in range(1, 11))
    assert [e.resp for e in events if e.ev == "query" and e.cmd == "LOP?"] == [all_off, on, all_off]
    assert any(e.ev == "checkpoint" and e.data and e.data.get("label") == "lop_positive_control"
               and e.data.get("ok") is True for e in events)
    verify = [e for e in events if e.ev == "cleanup_step" and e.data and e.data.get("step") == "verify"]
    assert verify and "positive control with the outputs on" in str(verify[-1].data["detail"])

    # same physics, same bytes: the visa path reproduces the simulator path exactly
    sim_folder, sim_manifest = sim_run(case, tmp_path / "sim")
    assert (folder / DATA_FILE).read_bytes() == (sim_folder / DATA_FILE).read_bytes()
    assert sim_manifest["cleanup"]["positive_control"] is None  # the simulator verifies its own state instead


@pytest.mark.parametrize("case", SYSTEM_CASES, ids=[c["recipe_id"] for c in SYSTEM_CASES])
def test_system_recipe_runs_confirmed_on_backend_visa(case: dict[str, Any], world: VisaWorld,
                                                     tmp_path: Path) -> None:
    """WP6.2 AC: kind ``system`` on visa, confirmed (``first_hw_run`` + its ``always_confirm`` reason), one query,
    no output switched on, cleanup verified with ``LOP?``."""
    recipe_id = case["recipe_id"]
    reason = "system_" + recipe_id.split(".")[1]
    bus, validation, result = run_on_visa(world, case)
    assert sorted(validation.confirm_reasons) == sorted(["first_hw_run", reason])
    assert validation.summary is not None and "| visa |" in validation.summary and "no outputs" in validation.summary
    sent = [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"]
    query = SYSTEM_QUERIES[recipe_id]
    assert sent.count(query) == 1 and sent[-3:] == ["CL", "ERRX?", "LOP?"]
    assert not {"CN", "DV", "WV", "XE", "*RST"} & set(sent)
    assert not [r for r in bus.instrument.command_log if r.source]

    folder = world.run_dir(result.run_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind_result"] == {"operation": recipe_id.split(".")[1], "result": 0, "failed_units": ""}
    assert manifest["confirmed_summary"] == validation.summary and manifest["recipe_status"] == "sim_validated"
    assert manifest["cleanup"]["verified"] == "lop" and manifest["cleanup"]["positive_control"] is None
    assert not (folder / DATA_FILE).exists() and result.quality_verdict is None
    events = world.run_events(result.run_id)
    answers = [e.resp for e in events if e.ev == "query" and e.cmd == query]
    assert answers == ["0"]
    _, sim_manifest = sim_run(case, tmp_path / "sim")
    assert sim_manifest["kind_result"] == manifest["kind_result"]


def test_a_failed_self_test_names_the_slots_on_visa(world: VisaWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero ``*TST?`` result on hardware (e.g. a DUT left connected): the run fails and names the failed units,
    the cleanup still verifies with ``LOP?``."""
    case = next(c for c in SYSTEM_CASES if c["recipe_id"] == "system.self_test")
    bus = world.bus(case["scenario"])
    passing = bus.instrument._selftest

    def failing() -> str:
        passing()  # the modules still end as after CL
        return str(4 + 1024)  # slot 3 module and mainframe failed (PG p541 (4-223) Table 4-32)

    monkeypatch.setattr(bus.instrument, "_selftest", failing)
    service = world.service(bus)
    result = run_case(service, case)
    assert not result.ok and result.outcome == "failed" and result.error_code == "instrument_error"
    assert result.cleanup_verified == "lop"
    manifest = json.loads((world.run_dir(result.run_id) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind_result"]["result"] == 1028
    assert manifest["kind_result"]["failed_units"] == "slot 3, mainframe"


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
