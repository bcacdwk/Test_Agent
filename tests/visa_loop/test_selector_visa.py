"""``system.selector_check`` on backend visa through the real ``VisaTransport`` (blueprint v2 10.5 row 9.2, per-recipe
AC ``tests/visa_loop -k <R>``; WP9.2): the lab PC's path with the visa-loop resource manager standing in for the VISA
library. The check needs a human confirmation (``first_hw_run`` until a reviewed record exists, the unverified
selector topology and pin map), switches no output on, steps every declared selector output through its states with
``ERMOD 1`` + ``ERSSP`` and the ``ERSSP?`` read-back, and the cleanup returns every port to open and verifies it with
``LOP?`` plus ``ERSSP?`` per port. A selector of unknown presence is blocked on visa (R-ROUTE-01)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from tests.visa_loop.helpers import (
    REPO_ROOT,
    ROUTE_CASES,
    VisaWorld,
    assert_selectors_restored,
    bus_events,
    run_case,
    without_switch_traffic,
)

pytestmark = pytest.mark.spgu


@pytest.mark.parametrize("case", ROUTE_CASES, ids=[c["recipe_id"] for c in ROUTE_CASES])
def test_route_only_recipe_runs_confirmed_on_backend_visa(case: dict[str, Any], world: VisaWorld) -> None:
    bus = world.bus(case["scenario"])
    service = world.service(bus)
    validation = service.validate_plan(recipe_id=case["recipe_id"], **case["request"])
    assert validation.backend == "visa" and not validation.simulated and validation.tier == "needs_confirmation"
    assert sorted(validation.confirm_reasons) == ["first_hw_run", "unverified_pin_map", "unverified_topology"]
    result = run_case(service, case)
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated, result.cleanup_verified) == ("visa", False, "lop")
    assert result.run_id is not None and result.run_id.startswith("H")
    assert bus_events(world.run_events(result.run_id)) == [
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]

    log = bus.instrument.command_log
    sent = [r.command for r in log if r.outcome == "ok"]
    assert not {"CN", "DV", "SRP", "SPUPD", "XE"} & {c.split(" ")[0] for c in sent}  # no output, no source
    assert not [r for r in log if r.source]
    first = sent.index("ERSSP 0,1")
    assert sent[first - 3:first] == ["LOP?", "SPST?", "ERMOD 1"]  # outputs checked off before the first route
    assert sent[first:first + 3] == ["ERSSP 0,1", "ERSSP? 0", "ERSSP? 1"]  # set, then read back (both SEL1 ports)
    assert without_switch_traffic(log)[-4:] == ["CL", "ERRX?", "LOP?", "SPST?"]
    assert_selectors_restored(log)
    folder = world.run_dir(result.run_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind_result"]["states_verified"] == 14 and manifest["cleanup"]["verified"] == "lop"
    assert {t: s for t, s in manifest["cleanup"]["switches_after"].items() if t.startswith("SEL")} == {
        "SEL1.OUT1": "open", "SEL1.OUT2": "open", "SEL2.OUT1": "open", "SEL2.OUT2": "open"}
    assert bus.stats.signed_errx > 0 and all(session.closed for session in bus.sessions) and bus.lock_is_free()
    bus.instrument.assert_safe()


def test_a_selector_of_unknown_presence_is_blocked_on_visa(world: VisaWorld) -> None:
    station = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    for switch in station["switches"]:
        if switch["id"] == "SEL2":
            switch["present"] = None
    world.write_local("station.yaml", station)
    bus = world.bus("lab_station")
    validation = world.service(bus).validate_plan(**{"recipe_id": "system.selector_check", **ROUTE_CASES[0]["request"]})
    assert validation.tier == "blocked"
    assert any(f.rule_id == "R-ROUTE-01" and "SEL2 is unknown" in f.message for f in validation.findings)
    assert not [r for r in bus.instrument.command_log if r.mnemonic.startswith("ERSSP")]
