"""The ``spgu_pulse`` pulse-mode recipes on backend visa through the real ``VisaTransport`` (WP9.3; per-recipe AC
``tests/visa_loop -k <recipe>``; blueprint v2 7.1 visa-loop, 8.1 ``visa_loop/``).

The lab PC's path with the visa-loop resource manager standing in for the VISA library: the station profile records the
selector wiring (on hardware a ``null`` input blocks the plan, R-PIN-01; bring-up L7 records it), every plan needs
``first_hw_run`` besides the unverified topology/pin map (and ``soft_pulse`` for charge pumping), the confirmed run
routes the gate to the PGU, sets up and starts the SPGU through the guard, polls ``SPST?`` to the end, routes back to
rest, and the cleanup verifies with ``LOP?`` + ``SPST?`` + ``ERSSP?`` per port; charge pumping reads the bulk during
every train and its ``data.csv`` is byte-identical to the simulator backend's."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from tests.sim.selector_helpers import recorded_station
from tests.visa_loop.helpers import (
    VisaWorld,
    assert_selectors_restored,
    bus_events,
    ok_commands,
    without_switch_traffic,
)
from tests.visa_loop.test_sampling_visa import run_to_end, sim_data

pytestmark = pytest.mark.spgu

PULSE_CASES: list[dict[str, Any]] = [
    {"recipe_id": "spgu.pulse_train", "scenario": "fefet_lab",
     "request": {"params": {}, "pin_map": "fefet-sel", "dut_profile": "fefet-lab"},
     "reasons": ["first_hw_run", "unverified_pin_map", "unverified_topology"]},
    {"recipe_id": "spgu.alwg_sequence", "scenario": "fefet_lab",
     "request": {"params": {}, "pin_map": "fefet-sel", "dut_profile": "fefet-lab"},
     "reasons": ["first_hw_run", "unverified_pin_map", "unverified_topology"]},
    {"recipe_id": "mosfet.charge_pumping", "scenario": "nmos_cv",
     "request": {"params": {"frequency": [1e4, 1e5, 1e6]}, "pin_map": "mosfet-cp", "dut_profile": "nmos-cv"},
     "reasons": ["first_hw_run", "soft_pulse", "unverified_pin_map", "unverified_topology"]},
]
"""The card example requests (charge pumping on three frequencies to keep the loop short)."""


@pytest.mark.parametrize("case", PULSE_CASES, ids=[c["recipe_id"] for c in PULSE_CASES])
def test_pulse_recipe_runs_confirmed_on_backend_visa(case: dict[str, Any], world: VisaWorld, tmp_path: Path) -> None:
    station = recorded_station()
    world.write_local("station.yaml", station)
    bus = world.bus(case["scenario"], chunk_size=16)
    service = world.service(bus)
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
    route = sent.index("ERSSP 0,2")
    assert sent[route + 1] == "ERSSP? 0" and route < next(i for i, c in enumerate(sent) if c.startswith("CN"))
    assert sent.index("SRP") < len(sent) - 1 - sent[::-1].index("ERSSP 0,0")
    assert "SPP" not in sent  # every output ended at its count/duration (SPST? 0), nothing to stop at cleanup
    assert without_switch_traffic(log)[-5:] == ["DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    assert_selectors_restored(log)
    folder = world.run_dir(result.run_id or "")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["verified"] == "lop" and manifest["kind_result"]["spp_fallbacks"] == 0
    assert {t: s for t, s in manifest["cleanup"]["switches_after"].items() if t.startswith("SEL")} == {
        "SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open", "SEL2.OUT2": "open"}
    assert all(session.closed for session in bus.sessions) and bus.lock_is_free()
    bus.instrument.assert_safe()
    if case["recipe_id"] == "mosfet.charge_pumping":
        assert sent.count("XE") == 3 and manifest["cleanup"]["positive_control"]["ok"] is True
        assert {a.quantity: a.outcome for a in result.analyses} == {"qcp": "ok", "icp_max": "ok"}
        assert (folder / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")
    else:
        assert "XE" not in sent and not (folder / DATA_FILE).exists()


def test_a_null_selector_input_blocks_the_pulse_plan_on_visa(world: VisaWorld) -> None:
    """The committed lab example leaves the selector inputs null: on hardware the gate's PGU path is unknown, so the
    plan is blocked (R-PIN-01) until the human records it at L7 (the simulator rehearses with its own cabling)."""
    bus = world.bus("fefet_lab")
    validation = world.service(bus).validate_plan(**{"recipe_id": "spgu.pulse_train", **PULSE_CASES[0]["request"]})
    assert validation.tier == "blocked"
    assert any(f.rule_id == "R-PIN-01" and "pgu input of SEL1.OUT1 is unknown (null)" in f.message
               for f in validation.findings)
    assert not [r for r in bus.instrument.command_log if r.mnemonic in ("SRP", "SPUPD", "ERSSP")]
