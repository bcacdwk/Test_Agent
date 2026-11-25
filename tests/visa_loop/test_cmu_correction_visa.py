"""The four MFCMU correction recipes on backend visa through the real ``VisaTransport`` (blueprint v2 7.1 visa-loop,
10 per-recipe AC; WP8.2).

Each ``CORRECTION_CASES`` request (card ``cmu-correction`` example, pin map ``capacitor-cmu``, no DUT profile) runs
through ``B1500Service`` exactly as on the lab PC: ``validate_plan`` asks for ``physical_setup`` (the probe state)
plus ``first_hw_run``, ``run_confirmed_plan`` runs it; the visa-loop resource manager forwards the session to the
simulator. Every run completes with the ``LOP?`` positive control on the MFCMU slot and its cleanup verified by
``LOP?``, the bus lives exactly as long as the transaction, the record lands in the correction store with the
instrument's ``*IDN?``, and the 30 s ``ADJ?`` and the ``CORR?`` queries pass the VISA read timeouts the kind sets.
Run in order on one bus (phase, open, short, load), the short run keeps the open correction (``setup kept``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from b1500_test_agent.archive.corrections import CorrectionStore
from tests.visa_loop.helpers import CORRECTION_CASES, REPO_ROOT, VisaWorld, bus_events, run_case

pytestmark = pytest.mark.cmu

CMU = 7
LOAD = {"ls_h": 0.0, "rs_ohm": 100.0}


def with_load_standard(world: VisaWorld) -> None:
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    station["corrections"] = {"CMU1": {"load": LOAD}}
    world.write_local("station.yaml", station)


def manifest(world: VisaWorld, run_id: str) -> dict[str, Any]:
    return json.loads((world.run_dir(run_id) / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CORRECTION_CASES, ids=[c["recipe_id"] for c in CORRECTION_CASES])
def test_correction_recipe_runs_confirmed_on_backend_visa(case: dict[str, Any], world: VisaWorld) -> None:
    with_load_standard(world)
    bus = world.bus(case["scenario"])
    service = world.service(bus)
    validation = service.validate_plan(recipe_id=case["recipe_id"], **case["request"])
    assert validation.backend == "visa" and not validation.simulated
    assert validation.tier == "needs_confirmation"
    assert {"physical_setup", "first_hw_run", "unverified_pin_map"} <= set(validation.confirm_reasons)

    result = run_case(service, case)
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False) and result.run_id.startswith("H")  # type: ignore[union-attr]
    assert result.cleanup_verified == "lop"
    assert bus_events(world.run_events(result.run_id)) == [  # type: ignore[arg-type]
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.opens == bus.stats.closes and bus.lock_is_free()
    cleanup = manifest(world, result.run_id)["cleanup"]  # type: ignore[arg-type]
    control = cleanup["positive_control"]
    assert control["ok"] is True and control["channels"] == [CMU] and control["codes"][str(CMU)] != "00"
    assert set(cleanup["outputs_after"].values()) == {"00"}
    bus.instrument.assert_safe()

    records = CorrectionStore(world.state_dir).records("CMU1")
    assert len(records) == 1 and records[0].run_id == result.run_id
    assert records[0].idn == bus.instrument.scenario.idn and result.artifacts["corrections"].endswith("CMU1.json")
    sent = [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"]
    measured = "ADJ?" if case["recipe_id"] == "cmu.phase_compensation" else "CORR?"
    assert measured in sent and "CORRST?" in sent[:sent.index("CN")]  # the live correction state before the run


def test_the_correction_sequence_on_one_bus_keeps_the_earlier_corrections(world: VisaWorld) -> None:
    with_load_standard(world)
    bus = world.bus("capacitor_100p")
    service = world.service(bus)
    results = [run_case(service, case) for case in CORRECTION_CASES]
    assert [r.outcome for r in results] == ["completed"] * 4, [r.message for r in results]
    setups = [manifest(world, r.run_id)["kind_result"].get("setup") for r in results]  # type: ignore[arg-type]
    assert setups == [None, "rewritten", "kept", "kept"]
    last = manifest(world, results[-1].run_id)["kind_result"]  # type: ignore[arg-type]
    assert (last["after_phase"], last["after_open"], last["after_short"], last["after_load"]) == (True,) * 4
    assert [r.kind for r in CorrectionStore(world.state_dir).records("CMU1")] == ["phase", "open", "short", "load"]
    status = service.station_status(refresh=True)
    assert status.corrections["CMU1"].startswith("fresh: phase")
