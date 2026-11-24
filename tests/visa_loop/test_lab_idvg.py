"""The lab's Id-Vg measurement on backend visa (blueprint v2 10.2 row 6.2; 1.1 lab pitfalls; 4.4 ``lab_nmos_2025``).

``mosfet.idvg`` with the lab script's measurement (``tests/integration/test_lab_idvg_sequence.py``
``LAB_IDVG_REQUEST``: pin map ``mosfet-3t-lab``, -2..2 V in 61 steps, Vd 0.1 V) runs through ``B1500Service`` and the
real ``VisaTransport`` against the calibrated lab transistor. On the wire the kernel's flow differs from the lab
script exactly as ``FLOW_DIFFERENCES`` documents: no ``*RST``, no selector commands, ``FMT 1,1`` once, the setup
writes are the preview, the ``LOP?`` positive control sits between ``CN`` and the first level, and the cleanup is
verified. The lab pitfalls the parser designs out are checked on this path too: the lab firmware's signed
``+0,"No Error."`` answers are read as "no error", and the status letter of every element is kept (a compliance shows
as ``C`` with the aborted steps ``V`` and the run flagged), where the lab parser keeps only the number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis.dataset import DATA_FILE
from b1500_test_agent.models.sim import ComplianceAt
from tests.integration.helpers import make_world
from tests.integration.test_lab_idvg_sequence import FLOW_DIFFERENCES, LAB_IDVG_REQUEST, kernel_preview
from tests.visa_loop.helpers import VisaWorld, assert_selectors_restored, without_switch_traffic

pytestmark = pytest.mark.smu

SCENARIO = "lab_nmos_2025"


def run_lab_idvg(world: VisaWorld, **params: object) -> tuple[Any, Any]:
    bus = world.bus(SCENARIO)
    service = world.service(bus)
    request = {**LAB_IDVG_REQUEST, "params": {**LAB_IDVG_REQUEST["params"], **params}}
    validation = service.validate_plan(**request)
    assert validation.ok and validation.tier == "needs_confirmation", validation.message
    assert sorted(validation.confirm_reasons) == ["dut_envelope", "first_hw_run", "unverified_pin_map"]
    return bus, service.run_confirmed_plan(validation.plan_id, summary=validation.summary)


def matlab_value(element: str) -> float:
    """How the lab parser reads one element (IV_sweep.m:125-126): the number from its first sign on."""
    return float(element[min(i for i in (element.find("+"), element.find("-")) if i >= 0):])


def test_the_lab_measurement_runs_on_visa_with_the_documented_flow(world: VisaWorld, tmp_path: Path) -> None:
    bus, result = run_lab_idvg(world)
    assert result.ok and result.outcome == "completed" and result.cleanup_verified == "lop", result.message
    # the declared selectors' rest/verify traffic of the snapshot and cleanup (WP9.2) is checked on its own; the rest
    # is the documented flow
    assert_selectors_restored(bus.instrument.command_log)
    sent = [r.command for r in bus.instrument.command_log if r.outcome == "ok"
            and r.mnemonic in without_switch_traffic([r])]
    mnemonics = [c.split(" ")[0] for c in sent]

    # what the lab script sends and the kernel deliberately does not (FLOW_DIFFERENCES)
    assert not {"*RST", "ERSSP", "ERMOD", "*OPC?", "RI"} & set(mnemonics)
    assert {"*RST", "ERSSP", "*OPC?"} <= set(FLOW_DIFFERENCES)
    # the setup writes are exactly the preview, in order, once
    preview = kernel_preview(make_world(tmp_path / "plan"))
    writes = [c for c in sent if not c.split(" ")[0].endswith("?")]
    first = writes.index(preview[0])
    assert writes[first:first + len(preview)] == preview and mnemonics.count("FMT") == 1
    assert writes[first + len(preview):] == ["DZ", "CL"]  # then only the cleanup
    # queries: the pre-execute snapshot, the drains, the positive control, the cleanup's verification
    queries = [c for c in sent if c.split(" ")[0].endswith("?")]
    cn = mnemonics.index("CN")
    assert {"*IDN?", "UNT?", "*STB?", "*LRN? 31"} <= set(queries)
    assert mnemonics[cn:cn + 3] == ["CN", "ERRX?", "LOP?"]
    assert mnemonics[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"]  # v2 cleanup: SPGU stopped, verified

    manifest = json.loads((world.run_dir(result.run_id) / "manifest.json").read_text(encoding="utf-8"))
    control = manifest["cleanup"]["positive_control"]
    assert control["ok"] is True and control["channels"] == [3, 4, 5]
    assert control["codes"] == {"3": "01", "4": "01", "5": "01"}
    # ERRX?: the lab firmware's signed answers are "no error" (blueprint v2 1.1: '+0,' vs '0,')
    events = world.run_events(result.run_id)
    answers = [e.resp for e in events if e.ev == "query" and e.cmd == "ERRX?"]
    assert answers and all(a is not None and a.startswith('+0,"') for a in answers)
    assert not [e for e in events if e.ev == "instrument_error"] and manifest["cleanup"]["errors"] == []

    # the same physics as the simulator backend, byte for byte
    sim_world = make_world(tmp_path / "sim")
    sim_world.use_scenario(SCENARIO)
    service = sim_world.service()
    try:
        validation = service.validate_plan(**LAB_IDVG_REQUEST)
        sim_result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    finally:
        service.close()
    sim_data = next(sim_world.runs_dir.rglob(f"{sim_result.run_id}/{DATA_FILE}")).read_bytes()
    assert (world.run_dir(result.run_id) / DATA_FILE).read_bytes() == sim_data


def test_status_letters_survive_where_the_lab_parser_drops_them(world: VisaWorld) -> None:
    """A drain compliance at step 50: the raw block carries ``C`` (and ``V`` after the automatic abort), the table
    keeps them, the run is flagged; the lab parser would have returned plain numbers for the same block."""
    bus = world.bus(SCENARIO)
    bus.inject(ComplianceAt(step=50, ch=4))
    service = world.service(bus)
    validation = service.validate_plan(**LAB_IDVG_REQUEST)
    result = service.run_confirmed_plan(validation.plan_id, summary=validation.summary)
    assert result.outcome == "completed_with_flags" and result.quality_verdict == "untrusted", result.message
    assert result.status_counts["C"] == 1 and result.status_counts["V"] > 0
    assert result.cleanup_verified == "lop"

    folder = world.run_dir(result.run_id)
    raw = (folder / "raw" / "block-000.txt").read_text(encoding="latin-1").strip()
    elements = raw.split(",")
    assert len(elements) == 61 * 3
    letters = {element[0] for element in elements}
    assert {"N", "C", "V"} <= letters
    compliance = next(e for e in elements if e.startswith("C"))
    assert re.fullmatch(r"C[A-J]I[-+][\d.]+E[-+]\d\d", compliance)
    assert isinstance(matlab_value(compliance), float)  # the lab parser: a plain number, the flag is gone

    table = (folder / DATA_FILE).read_text(encoding="utf-8").splitlines()
    header = table[0].split(",")
    status = [row.split(",")[header.index("drain_I_status")] for row in table[1:]]
    assert status[50] == "C" and set(status[51:]) == {"V"} and set(status[:50]) == {"N"}
