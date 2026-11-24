"""The ``pulse_read`` recipes on backend visa through the real ``VisaTransport`` (WP9.4; per-recipe AC
``tests/visa_loop -k <recipe>``; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``).

The lab PC's path with the visa-loop resource manager standing in for the VISA library: the station profile records the
selector wiring (bring-up L7), every plan needs ``first_hw_run`` besides the unverified topology/pin map (and
``adhoc_recipe`` for the generic recipe); the confirmed run routes the gate to the SMU for the reference read, to the
PGU for each erase/program output and back to the SMU for each read, then to rest, every route read back; the cleanup
verifies with ``LOP?`` + ``SPST?`` + ``ERSSP?`` per port, and ``data.csv`` is byte-identical to the simulator
backend's. The SMU pulse source (test-only ``generic.smu_pulse_read``) runs the same way without the SPGU."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.catalog.registry import RecipeRegistry
from tests.integration.helpers import make_world
from tests.sim.pulse_read_helpers import AT_REST, recipes_with_fixture
from tests.sim.selector_helpers import recorded_station
from tests.visa_loop.helpers import (
    REPO_ROOT,
    VisaWorld,
    assert_selectors_restored,
    bus_events,
    ok_commands,
    without_switch_traffic,
)
from tests.visa_loop.test_sampling_visa import run_to_end

pytestmark = pytest.mark.spgu

REQUEST = {"pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
PULSE_READ_CASES: list[dict[str, Any]] = [
    {"recipe_id": "fefet.pulse_write_read", "scenario": "fefet_lab", "request": {"params": {}, **REQUEST},
     "reasons": ["first_hw_run", "unverified_pin_map", "unverified_topology"], "pgu": 2, "reads": 3},
    {"recipe_id": "spgu.program_smu_read", "scenario": "fefet_lab", "request": {"params": {"cycles": 1}, **REQUEST},
     "reasons": ["adhoc_recipe", "first_hw_run", "unverified_pin_map", "unverified_topology"], "pgu": 2, "reads": 3},
    {"recipe_id": "generic.smu_pulse_read", "scenario": "fefet_lab", "request": {"params": {}, **REQUEST},
     "reasons": ["adhoc_recipe", "draft_recipe", "unverified_pin_map", "unverified_topology"], "pgu": 0, "reads": 3},
]
"""The card example requests (the generic recipe on one cycle) and the SMU pulse source request (a test-only draft
recipe: ``draft_recipe`` instead of ``first_hw_run``)."""


def sim_data(case: dict[str, Any], tmp_path: Path) -> bytes:
    """``data.csv`` of the same request on backend sim (fixture recipes included)."""
    world = make_world(tmp_path)
    world.recipes = recipes_with_fixture(tmp_path)
    world.use_scenario(case["scenario"])
    service = world.service()
    try:
        _, result = run_to_end(service, case)
    finally:
        service.close()
    assert result.ok and result.backend == "sim", result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    return (folder / DATA_FILE).read_bytes()


@pytest.mark.parametrize("case", PULSE_READ_CASES, ids=[c["recipe_id"] for c in PULSE_READ_CASES])
def test_pulse_read_recipe_runs_confirmed_on_backend_visa(case: dict[str, Any], world: VisaWorld,
                                                          tmp_path: Path) -> None:
    world.write_local("station.yaml", recorded_station())
    bus = world.bus(case["scenario"], chunk_size=16)
    registry = RecipeRegistry.load(recipes_with_fixture(tmp_path / "recipes-root"), repo_root=REPO_ROOT)
    service = world.service(bus, registry=registry)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert sorted(validation.confirm_reasons) == case["reasons"]
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated, result.cleanup_verified) == ("visa", False, "lop")
    assert (result.run_id or "").startswith("H")
    assert bus_events(world.run_events(result.run_id or "")) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    log = bus.instrument.command_log
    sent = ok_commands(log)
    cn = next(i for i, c in enumerate(sent) if c.startswith("CN"))
    assert sent.index("ERSSP 0,1") < cn and sent[sent.index("ERSSP 0,1") + 1] == "ERSSP? 0"
    assert sent.count("ERSSP 0,2") == case["pgu"] and sent.count("SRP") == case["pgu"]
    for start in [i for i, c in enumerate(sent) if c == "SRP"]:
        back = sent.index("ERSSP 0,1", start)  # each output ends before the gate returns to the SMU for its read
        assert "XE" not in sent[start:back]
    assert "SPP" not in sent and sent.count("ERSSP 0,0") >= 1
    assert without_switch_traffic(log)[-5:] == ["DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    assert_selectors_restored(log)
    folder = world.run_dir(result.run_id or "")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    facts = manifest["kind_result"]
    assert manifest["cleanup"]["verified"] == "lop" and facts["reads_done"] == case["reads"]
    assert manifest["cleanup"]["positive_control"]["ok"] is True
    assert {t: s for t, s in manifest["cleanup"]["switches_after"].items() if t.startswith("SEL")} == AT_REST
    assert facts["routes"].endswith("end rest SEL1.OUT1->open")
    assert all(session.closed for session in bus.sessions) and bus.lock_is_free()
    bus.instrument.assert_safe()
    assert (folder / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")
