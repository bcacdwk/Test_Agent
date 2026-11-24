"""The capacitance recipes of kind ``cmu_measure`` on backend visa through the real ``VisaTransport`` (blueprint v2
7.1 visa-loop, 10 per-recipe AC; WP8.3; the C-V variants of WP8.4: AC-level, pulsed, C-f, C-t, FeCap butterfly).

Each ``CV_CASES`` request (the card example) runs through ``B1500Service`` exactly as on the lab PC, after the
phase/open/short corrections of its pin map (R-CORR-01; each confirmed with its summary). Every run is
``needs_confirmation`` (``first_hw_run`` + ``unverified_pin_map``), completes with the ``LOP?`` positive control on
the switched-on slots (the MFCMU, and the source SMU of ``mosfet.cgd_cv``), verifies its cleanup with ``LOP?``,
lives in one bus session per transaction, reads its blocks through small VISA chunks, and writes the same
``data.csv`` bytes as the same request on backend sim. Not in ``MEASUREMENT_CASES``/``DATA_CASES``: those run a
request on a fresh instrument, which R-CORR-01 blocks for every capacitance plan. WP8.5: ``moscap_dit`` has an SCUU on
CMU1 (one landing for QSCV and C-V), so its cases use pin map ``moscap-scuu`` with a station profile that records
SCUU1 present (R-ROUTE-01 on hardware): ``SSP 7,4`` connects the MFCMU instead of ``CN`` (error 323), the positive
control covers the MFCMU and the run part starts at that ``SSP``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.models.station import channel_slot
from b1500_test_agent.service import B1500Service
from tests.integration.helpers import REPO_ROOT, make_world
from tests.visa_loop.helpers import SWITCH_LEARN, SWITCH_MNEMONICS, VisaWorld, bus_events, run_case

CHUNK = 64
"""Small VISA chunks: an MFCMU block (about 35 bytes per element) needs several reads."""

CV_CASES: list[dict[str, Any]] = [
    {"recipe_id": "cmu.spot", "scenario": "capacitor_100p", "source": "card cmu-spot",
     "request": {"params": {}, "pin_map": "capacitor-cmu", "dut_profile": "capacitor-100p"}},
    {"recipe_id": "moscap.cv", "scenario": "moscap_basic", "source": "card moscap-cv",
     "request": {"params": {}, "pin_map": "moscap-cmu", "dut_profile": "moscap-generic"}},
    {"recipe_id": "mosfet.cgc_cv", "scenario": "nmos_cv", "source": "card mosfet-split-cv",
     "request": {"params": {}, "pin_map": "mosfet-split-cv", "dut_profile": "nmos-cv"}},
    {"recipe_id": "mosfet.cgd_cv", "scenario": "nmos_cv", "source": "card mosfet-split-cv",
     "request": {"params": {}, "pin_map": "mosfet-split-cv", "dut_profile": "nmos-cv"}},
    {"recipe_id": "moscap.cv_ac_level", "scenario": "moscap_basic", "source": "card moscap-cv",
     "request": {"params": {}, "pin_map": "moscap-cmu", "dut_profile": "moscap-generic"}},
    {"recipe_id": "moscap.pulsed_cv", "scenario": "moscap_basic", "source": "card moscap-cv",
     "request": {"params": {"points": 21}, "pin_map": "moscap-cmu", "dut_profile": "moscap-generic"}},
    {"recipe_id": "moscap.cf", "scenario": "moscap_dit", "source": "card moscap-cf-ct", "scuu": True,
     "request": {"params": {}, "pin_map": "moscap-scuu", "dut_profile": "moscap-generic"},
     "corrections": {"freqs_hz": [1e3, 1778.279, 3162.278, 5623.413, 1e4, 17782.79, 31622.78, 56234.13, 1e5,
                                  177827.9, 316227.8, 562341.3, 1e6]}},
    {"recipe_id": "moscap.ct", "scenario": "moscap_dit", "source": "card moscap-cf-ct", "scuu": True,
     "request": {"params": {"points": 101}, "pin_map": "moscap-scuu", "dut_profile": "moscap-generic"}},
    {"recipe_id": "moscap.cv_multi_freq", "scenario": "moscap_dit", "source": "card moscap-dit", "scuu": True,
     "request": {"params": {"points": 41}, "pin_map": "moscap-scuu",
                 "dut_profile": "moscap-generic"}},
    {"recipe_id": "fecap.cv_butterfly", "scenario": "fecap_basic", "source": "card fecap-pund",
     "request": {"params": {"points": 41}, "pin_map": "fecap-cmu", "dut_profile": "fecap-generic"}},
]
"""The WP8.3 recipes, the WP8.4 C-V variants and WP8.5's multi-frequency C-V with their card example requests (fewer
points or frequencies where the default is long) and scenarios; ``corrections``: parameters of the open/short
corrections (the C-f list); ``scuu``: the landing goes through SCUU1 (recorded present)."""


def scuu_station() -> dict[str, Any]:
    """The station example with SCUU1 recorded present (the human records it at bring-up stage L6)."""
    station = yaml.safe_load((REPO_ROOT / "config/station.example.yaml").read_text(encoding="utf-8"))
    for switch in station["switches"]:
        if switch["id"] == "SCUU1":
            switch["present"] = True
    return station

CORRECTIONS = ("cmu.phase_compensation", "cmu.correction_open", "cmu.correction_short")


def correct(service: B1500Service, pin_map: str, params: dict[str, Any] | None = None) -> None:
    for recipe_id in CORRECTIONS:
        extra = {} if recipe_id == "cmu.phase_compensation" else (params or {})
        result = run_case(service, {"recipe_id": recipe_id, "request": {"params": extra, "pin_map": pin_map}})
        assert result.ok, result.message


def sim_data(case: dict[str, Any], tmp_path: Path) -> bytes:
    """``data.csv`` of the same request (after the same corrections) on backend sim."""
    world = make_world(tmp_path)
    world.use_scenario(case["scenario"])
    service = world.service()
    try:
        correct(service, case["request"]["pin_map"], case.get("corrections"))
        result = run_case(service, case)
    finally:
        service.close()
    assert result.ok and result.backend == "sim", result.message
    folder = next(p for p in world.runs_dir.rglob(str(result.run_id)) if p.is_dir())
    return (folder / DATA_FILE).read_bytes()


@pytest.mark.parametrize("case", CV_CASES, ids=[c["recipe_id"] for c in CV_CASES])
def test_cv_recipe_completes_on_backend_visa_with_cleanup_verified(case: dict[str, Any], world: VisaWorld,
                                                                   tmp_path: Path) -> None:
    scuu = bool(case.get("scuu"))
    if scuu:
        world.write_local("station.yaml", scuu_station())
    bus = world.bus(case["scenario"], chunk_size=CHUNK)
    service = world.service(bus)
    correct(service, case["request"]["pin_map"], case.get("corrections"))
    validation = service.validate_plan(recipe_id=case["recipe_id"], **case["request"])
    assert validation.backend == "visa" and not validation.simulated and validation.tier == "needs_confirmation"
    assert {"first_hw_run", "unverified_pin_map"} <= set(validation.confirm_reasons)
    result = run_case(service, case)
    assert result.ok and result.outcome == "completed", result.message
    assert (result.backend, result.simulated) == ("visa", False) and result.run_id.startswith("H")  # type: ignore[union-attr]
    assert result.cleanup_verified == "lop"
    assert bus_events(world.run_events(result.run_id)) == [  # type: ignore[arg-type]
        "lock_acquired", "bus_open", "bus_lock", "bus_unlock", "bus_close", "lock_released"]
    assert bus.stats.opens == bus.stats.closes and bus.lock_is_free() and bus.stats.max_chunks > 1
    bus.instrument.assert_safe()

    manifest = json.loads((world.run_dir(result.run_id) / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[arg-type]
    cleanup = manifest["cleanup"]
    log = [r for r in bus.instrument.command_log if r.outcome == "ok" and r.mnemonic not in SWITCH_MNEMONICS
           and r.command not in SWITCH_LEARN]
    if scuu:  # the SCUU connects the MFCMU (SSP 7,4); its modules are never in a CN list
        enabled = ["7"]
        start = len(log) - 1 - [r.command for r in log][::-1].index("SSP 7,4")
    else:
        enabled = next(list(r.args) for r in reversed(log) if r.mnemonic == "CN")
        start = len(log) - 1 - [r.mnemonic for r in log][::-1].index("CN")
    control = cleanup["positive_control"]
    assert control["ok"] is True and sorted(control["channels"]) == sorted(int(ch) for ch in enabled)
    assert all(control["codes"][str(channel_slot(int(ch)))] != "00" for ch in enabled)
    assert set(cleanup["outputs_after"].values()) == {"00"} and cleanup["verified"] == "lop"
    sent = [r.mnemonic for r in log]
    run_part = sent[start:]
    assert "XE" in run_part and run_part[-5:] == ["DZ", "CL", "ERRX?", "LOP?", "SPST?"]
    assert "CORRST?" in sent[:start]  # the live correction check before the run

    # same physics, same bytes: the visa path reproduces the simulator path
    assert (world.run_dir(result.run_id) / DATA_FILE).read_bytes() == sim_data(case, tmp_path / "sim")  # type: ignore[arg-type]
