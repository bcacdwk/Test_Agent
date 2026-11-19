"""The ``LOP?`` positive control on backend visa through the real ``VisaTransport`` (blueprint v2 10.2 row 6.2; v1
ATV-1 "LOP? reports per-channel output state usable for cleanup verification", ATV-23).

The passing control is asserted for every measurement recipe in ``test_recipes.py``. Here the instrument's ``LOP?``
never reports an output on (``LoopBus.lop_reads_off``: the ATV-1 failure the control exists for). The run must stop
right after ``CN`` (no level, no trigger), zero and disconnect the outputs, refuse to call that cleanup verified
(``LOP?`` reading ``00`` proves nothing on such an instrument), latch the fault and say why; a later run is refused
until a human clears the fault. The simulated outputs really are off afterwards: only ``LOP?`` is blind.
"""

from __future__ import annotations

import json

from b1500_test_agent.models.run import RunManifest
from tests.visa_loop.helpers import DATA_CASES, VisaWorld, run_case

IDVG = next(c for c in DATA_CASES if c["recipe_id"] == "mosfet.idvg")


def test_a_lop_that_never_shows_an_output_on_stops_the_run_and_latches_the_fault(world: VisaWorld) -> None:
    bus = world.bus(IDVG["scenario"])
    bus.lop_reads_off = True
    service = world.service(bus)
    result = run_case(service, IDVG)
    assert (result.ok, result.status, result.outcome, result.error_code) == (
        False, "fault", "failed", "cleanup_unverified")
    assert result.cleanup_verified == "unverified" and result.run_id is not None
    assert "positive control failed" in result.message and "ATV-1" in result.message

    # nothing after CN but the control, the zeroing and the disconnect: no level, no sweep, no trigger
    sent = [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"]
    cn = sent.index("CN")
    assert sent[cn:cn + 3] == ["CN", "ERRX?", "LOP?"]
    assert not {"DV", "WV", "MM", "XE"} & set(sent)
    assert {"DZ", "CL"} <= set(sent[cn:]) and not [r for r in bus.instrument.command_log if r.source]
    bus.instrument.assert_safe()  # the outputs are off; only the evidence is missing

    manifest = RunManifest.model_validate_json(
        (world.run_dir(result.run_id) / "manifest.json").read_text(encoding="utf-8"))
    cleanup = manifest.cleanup
    assert cleanup is not None and cleanup.latched_fault and cleanup.verified == "unverified"
    control = cleanup.positive_control
    assert control is not None and not control.ok and control.codes == {3: "00", 4: "00"}
    assert control.channels == [4, 3]  # nmos_basic on mosfet-4t: gate SMU4, drain SMU3
    assert set(cleanup.outputs_after.values()) == {"00"}
    events = world.run_events(result.run_id)
    assert any(e.ev == "checkpoint" and e.data and e.data.get("label") == "lop_positive_control"
               and e.data.get("ok") is False and e.error for e in events)
    assert "cleanup_unverified" in [e.ev for e in events]

    status = service.station_status()
    assert status.fault is not None and "positive control failed" in status.fault.reason
    assert "ATV-1" in status.fault.reason

    again = service.validate_plan(recipe_id=IDVG["recipe_id"], **IDVG["request"])  # refused until a human clears it
    assert again.tier == "blocked" and any(f.rule_id == "R-FAULT-01" for f in again.findings)


def test_the_passing_control_is_recorded_once_per_transaction(world: VisaWorld) -> None:
    """A stepped recipe enables its outputs once and reads ``LOP?`` once between ``CN`` and the first level."""
    case = next(c for c in DATA_CASES if c["recipe_id"] == "mosfet.idvd")
    bus = world.bus(case["scenario"])
    service = world.service(bus)
    result = run_case(service, case)
    assert result.ok and result.cleanup_verified == "lop", result.message
    sent = [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"]
    assert sent.count("CN") == 1 and sent.count("XE") > 1
    cn = sent.index("CN")
    assert sent[cn:].count("LOP?") == 2  # the control after CN and the cleanup's verification after CL
    manifest = json.loads((world.run_dir(result.run_id) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup"]["positive_control"]["ok"] is True
