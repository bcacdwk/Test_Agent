"""The RSU "From SMU" input limit on backend visa through the real ``VisaTransport`` (WP21.13; WG p20 (1-8) "Or the
RSU will be damaged" above +-25 V at the From SMU input; WG p16 (1-4) "Maximum current: 100 mA").

- The lab example station (RSU inputs ``smu: null`` until bring-up L8): any SMU plan above +-25 V is blocked by
  R-RSU-01 (the unknown input may carry that SMU); within the limit the usual confirmations apply. Nothing reaches
  the instrument.
- Recorded wiring (SMU3 on RSU202, nothing on RSU201): only SMU3 stays bounded; SMU4 may use the kernel's limits
  again (with the usual confirmations); a plan within the input runs to a verified cleanup (``LOP?``).
- The ``OutputGuard`` over ``VisaTransport``: a body beyond the input (a wide envelope) writes nothing beyond it, the
  cleanup verifies and the global invariant holds.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.station import Settings, StationProfile
from b1500_test_agent.session import Session
from b1500_test_agent.transport.audit import MemoryAuditSink
from b1500_test_agent.transport.factory import make_bus
from tests.safety.helpers import DRAIN, GATE, Harness, MemoryRun, assert_global_invariant
from tests.visa_loop.helpers import REPO_ROOT, VisaWorld
from tests.visa_loop.loop import LoopBus

pytestmark = pytest.mark.wgfmu

SWEEP = {"recipe_id": "generic.smu_staircase", "pin_map": "generic-3t", "dut_profile": "generic-3t"}
"""``generic.smu_staircase`` (range +-42 V) on the visa world's test pin map ``generic-3t``: sweep SMU3, bias SMU4."""


def station(**rsu_inputs: dict[str, Any]) -> dict[str, Any]:
    """``config/station.example.yaml`` with the ``inputs`` of the named RSUs replaced."""
    data = yaml.safe_load((REPO_ROOT / "config" / "station.example.yaml").read_text(encoding="utf-8"))
    for switch in data["switches"]:
        if switch["id"] in rsu_inputs:
            switch["ports"]["OUT"]["inputs"] = rsu_inputs[switch["id"]]
    return data


RECORDED = station(RSU201={"wgfmu": 201}, RSU202={"wgfmu": 202, "smu": 3})
"""Bring-up L8 recorded: SMU3 on RSU202's From SMU input, nothing cabled to RSU201's (its ``smu`` side deleted)."""


def rsu_findings(validation: Any) -> list[Any]:
    return [f for f in validation.findings if f.rule_id == "R-RSU-01"]


def no_source_sent(bus: LoopBus) -> bool:
    return not [r for r in bus.instrument.command_log if r.source]


def test_an_unknown_from_smu_input_blocks_smus_above_25_v(world: VisaWorld) -> None:
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    validation = service.validate_plan(**SWEEP, params={"start": 0.0, "stop": 30.0})
    assert (validation.backend, validation.simulated, validation.tier) == ("visa", False, "blocked")
    [finding] = rsu_findings(validation)
    assert (finding.observed, finding.limit) == (30.0, 25.0)
    assert finding.source == "config/local/station.yaml#switches[2].ports.OUT.inputs.smu"
    assert "RSU201.OUT, RSU202.OUT" in finding.message and "inputs.smu: null" in finding.message
    within = service.validate_plan(**SWEEP, params={"start": 0.0, "stop": 20.0})
    assert within.tier == "needs_confirmation" and not rsu_findings(within)
    assert no_source_sent(bus)


def test_recording_the_wiring_bounds_only_the_cabled_smu(world: VisaWorld) -> None:
    world.write_local("station.yaml", RECORDED)
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    swept = service.validate_plan(**SWEEP, params={"start": 0.0, "stop": 30.0})  # SMU3: RSU202's input
    assert swept.tier == "blocked"
    [finding] = rsu_findings(swept)
    assert finding.source == "code:b1500_test_agent.driver.modules.WGFMU_SPEC.smu_mode_max_v (WG p20 (1-8))"
    assert "From SMU input of RSU202.OUT" in finding.message
    biased = service.validate_plan(**SWEEP, params={"stop": 1.0, "bias_v": 30.0})  # SMU4: on no RSU
    assert biased.tier == "needs_confirmation" and not rsu_findings(biased)
    assert "soft_limit" in biased.confirm_reasons
    assert no_source_sent(bus)


def test_a_plan_within_the_input_runs_on_visa(world: VisaWorld) -> None:
    world.write_local("station.yaml", RECORDED)
    bus = world.bus("nmos_basic")
    service = world.service(bus)
    validation = service.validate_plan(**SWEEP, params={"start": 0.0, "stop": 1.0, "points": 11})
    assert validation.tier == "needs_confirmation" and not rsu_findings(validation)
    result = service.run_confirmed_plan(validation.plan_id or "", summary=validation.summary or "")
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated, result.cleanup_verified) == ("visa", False, "lop")
    bus.instrument.assert_safe()


WIDE = CompiledEnvelope(channels={
    GATE: ChannelEnvelope(role="gate", max_abs_v=2.0, max_abs_i=1e-4),
    DRAIN: ChannelEnvelope(role="drain", max_abs_v=40.0, max_abs_i=1e-3),
})
"""A stale or buggy plan's envelope: 40 V on SMU3 (R-RSU-01 blocks such a plan; the guard must stop it alone)."""


def test_the_guard_stops_a_body_beyond_the_input_over_visa(tmp_path: Path, world: VisaWorld) -> None:
    bus = world.bus("nmos_basic")
    settings = Settings.model_validate({"backend": "visa", "visa": {"timeout_ms": 1000, "lock_timeout_ms": 200}})
    daily = MemoryAuditSink()
    rsus = [s for s in StationProfile.model_validate(RECORDED).switches if s.kind == "rsu"]
    session = Session(settings, lambda: make_bus(settings, daily, rm_factory=bus.manager), daily,
                      state_dir=tmp_path / "state", switches=rsus)
    h = Harness(session=session, sim=SimpleNamespace(instrument=bus.instrument),  # type: ignore[arg-type]
                hook=None, daily=daily, run=MemoryRun(), state_dir=tmp_path / "state")  # type: ignore[arg-type]
    with pytest.raises(EnvelopeViolation) as caught, h.transaction(envelope=WIDE) as tx:
        tx.driver.enable([GATE, DRAIN])
        tx.driver.force_v(DRAIN, -25.0, icomp=1e-3)  # at the limit: written
        tx.driver.force_v(DRAIN, -25.5, icomp=1e-3)
    assert caught.value.reason == "rsu_input_exceeded" and caught.value.channel == DRAIN
    assert_global_invariant(h, envelope=WIDE)
    assert [r.command for r in bus.instrument.command_log if r.source] == ["DV 3,0,-25,0.001"]
    assert tx.cleanup is not None and tx.cleanup.verified == "lop"
    assert any(e.ev == "envelope_violation" and (e.data or {}).get("reason") == "rsu_input_exceeded"
               for e in h.events())
    session.close()
    assert bus.lock_is_free()
