"""The WP9.5 ``pulse_read`` recipes on backend visa through the real ``VisaTransport`` (per-recipe AC ``tests/visa_loop
-k <recipe>``; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``): ``fefet.switching_kinetics`` (a small grid with
wake-up pre-cycles), ``fefet.endurance`` (1,000 cycles: three-level cycling bursts between log checkpoints) and
``fefet.retention`` (MM 10 holds between the reads), each with the station's selector wiring recorded (bring-up L7).

Every plan needs ``first_hw_run`` besides the unverified topology/pin map; the confirmed run routes the gate to the
PGU for every pulse operation or burst and back to the SMU for every read, then to rest, each route read back; the
cleanup verifies with ``LOP?`` + ``SPST?`` + ``ERSSP?`` per port, and ``data.csv`` is byte-identical to the simulator
backend's (the same plan and scenario)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from tests.integration.helpers import make_world
from tests.sim.pulse_read_helpers import AT_REST
from tests.sim.selector_helpers import recorded_station
from tests.visa_loop.helpers import (
    VisaWorld,
    assert_selectors_restored,
    bus_events,
    ok_commands,
    without_switch_traffic,
)
from tests.visa_loop.test_sampling_visa import run_to_end

pytestmark = pytest.mark.spgu

REQUEST = {"pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
REASONS = ["first_hw_run", "unverified_pin_map", "unverified_topology"]
NVM_CASES: list[dict[str, Any]] = [
    {"recipe_id": "fefet.switching_kinetics", "scenario": "fefet_lab",
     "request": {"params": {"amplitudes": [3.6, 4.4], "widths": [1e-8, 1e-7, 1e-6, 1e-5], "precycles": 100},
                 **REQUEST},
     "reasons": REASONS, "srp": 1 + 16, "reads": 17, "mm10": 0},
    {"recipe_id": "fefet.endurance", "scenario": "fefet_lab",
     "request": {"params": {"cycles": 1000, "reads_per_decade": 1, "cycle_period": 1e-4}, **REQUEST},
     "reasons": REASONS, "srp": 3 + 8, "reads": 9, "mm10": 0},
    {"recipe_id": "fefet.retention", "scenario": "fefet_lab",
     "request": {"params": {"retention_time": 100.0}, **REQUEST},
     "reasons": REASONS, "srp": 2, "reads": 15, "mm10": 14},
]
"""Small versions of the card examples (fewer points, cycles and seconds; the visa path is the same)."""


def sim_data(case: dict[str, Any], tmp_path: Path) -> bytes:
    """``data.csv`` of the same request on backend sim."""
    world = make_world(tmp_path)
    world.use_scenario(case["scenario"])
    service = world.service()
    try:
        _, result = run_to_end(service, case)
    finally:
        service.close()
    assert result.ok and result.backend == "sim", result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    return (folder / DATA_FILE).read_bytes()


@pytest.mark.parametrize("case", NVM_CASES, ids=[c["recipe_id"] for c in NVM_CASES])
def test_nvm_schedule_recipe_runs_confirmed_on_backend_visa(case: dict[str, Any], world: VisaWorld,
                                                            tmp_path: Path) -> None:
    world.write_local("station.yaml", recorded_station())
    bus = world.bus(case["scenario"], chunk_size=16)
    service = world.service(bus)
    validation, result = run_to_end(service, case)
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "needs_confirmation")
    assert sorted(validation.confirm_reasons) == case["reasons"]
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated, result.cleanup_verified) == ("visa", False, "lop")
    assert bus_events(world.run_events(result.run_id or "")) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    log = bus.instrument.command_log
    sent = ok_commands(log)
    cn = next(i for i, c in enumerate(sent) if c.startswith("CN"))
    assert sent.index("ERSSP 0,1") < cn and sent[sent.index("ERSSP 0,1") + 1] == "ERSSP? 0"
    assert sent.count("SRP") == case["srp"] and sent.count("ERSSP 0,2") == case["srp"]
    for start in [i for i, c in enumerate(sent) if c == "SRP"]:
        back = sent.index("ERSSP 0,1", start)  # every output ends before the gate returns to the SMU
        assert "XE" not in sent[start:back]
    assert sum(1 for c in sent if c.startswith("MM 10,")) == case["mm10"]
    assert "SPP" not in sent and without_switch_traffic(log)[-5:] == ["DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    assert_selectors_restored(log)
    folder = world.run_dir(result.run_id or "")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    facts = manifest["kind_result"]
    assert manifest["cleanup"]["verified"] == "lop" and facts["reads_done"] == case["reads"]
    assert {t: s for t, s in manifest["cleanup"]["switches_after"].items() if t.startswith("SEL")} == AT_REST
    assert facts["routes"].endswith("end rest SEL1.OUT1->open")
    assert all(session.closed for session in bus.sessions) and bus.lock_is_free()
    bus.instrument.assert_safe()
    assert (folder / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")
