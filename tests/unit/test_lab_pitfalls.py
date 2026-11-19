"""The lab-code pitfalls of blueprint v2 1.1 that the kernel designs out, at unit level (WP6.2).

- status codes discarded (``IV_sweep.m:125`` keeps the number from its first sign on): ``parse_fmt1`` keeps one
  status letter per element and the table a ``_status`` column. Here; end to end in
  ``tests/visa_loop/test_lab_idvg.py``.
- ``+0,`` vs ``0,`` (the lab checks ``startsWith(response, '+0,')``): ``parse_errx`` reads both as no error.
  ``tests/unit/test_driver_discovery.py`` (WP5.5); on the wire ``tests/visa_loop/test_lab_idvg.py``.
- ``*RST`` hides the prior state: never sent outside kind ``system`` (``tests/unit/test_lint_rst.py``); no
  committed recipe preview holds it (here).
- no ``CL`` after the SPGU (``test_SPGU.m:122``): every transaction cleanup sends a bare ``CL`` (every channel, SPGU
  included). Here.
- 100 mA compliance on a sub-uA device: recipe ranges cap the compliances (1 mA default).
  ``tests/integration/test_lab_idvg_sequence.py``.

Multi-channel ``TSC`` parsing and real-time streaming belong to the sampling kind (WP7.4, ATV-30).
"""

from __future__ import annotations

import json

from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.parser import MeasurementStatus, SourceDataStatus, parse_fmt1
from b1500_test_agent.session import run_cleanup
from tests.integration.test_plan_goldens import CASES, fixture_path
from tests.unit.test_session import LOP_OFF, NO_ERROR, HwSpy, Recorder

LAB_SHAPED_ELEMENTS = (
    "NDI+1.36350E-08", "NCI+1.95000E-12", "WCV+0.33333E+00",   # step 39: drain I, gate I, gate source value
    "CDI+1.00000E-03", "TCI+2.05000E-12", "WCV+0.40000E+00",   # step 40: the drain reached its compliance
    "VDI+199.999E+99", "VCI+199.999E+99", "WCV+0.46667E+00",   # step 41: after the automatic abort
)
LAB_SHAPED_BLOCK = ",".join(LAB_SHAPED_ELEMENTS)
"""Three steps of a lab-shaped Id-Vg block in FMT 1 (MM 2 drain = D, gate = C; mode 1 adds the source value)."""


def lab_parser(element: str) -> float:
    """``IV_sweep.m:125-126``: the value from the first ``+`` or ``-`` on; the status is lost."""
    return float(element[min(i for i in (element.find("+"), element.find("-")) if i >= 0):])


def test_every_element_keeps_its_status_letter() -> None:
    points = parse_fmt1(LAB_SHAPED_BLOCK + "\r\n")
    assert [p.status for p in points] == [
        MeasurementStatus("N"), MeasurementStatus("N"), SourceDataStatus("W"),
        MeasurementStatus("C"), MeasurementStatus("T"), SourceDataStatus("W"),
        MeasurementStatus("V"), MeasurementStatus("V"), SourceDataStatus("W")]
    assert points[3].value == 1e-3 and points[6].invalid
    # the lab parser returns the same numbers and nothing else: the compliance step looks like a 1 mA reading
    assert [lab_parser(e) for e in LAB_SHAPED_ELEMENTS] == [p.value for p in points]


def test_no_recipe_preview_resets_the_instrument() -> None:
    """``*RST`` reaches the bus only through kind ``system`` (lint), and no committed v1 recipe sends it."""
    for case in CASES:
        preview = json.loads(fixture_path(case["recipe_id"]).read_text(encoding="utf-8"))["flex_preview"]
        assert "*RST" not in preview, case["recipe_id"]


def test_every_cleanup_ends_with_a_bare_cl() -> None:
    """``CL`` without channels disconnects every module, SPGU channels included (the lab's SPGU script never sends
    one); the kernel sends it on every exit, then verifies with ``LOP?``."""
    spy = HwSpy(answers={"ERRX?": NO_ERROR, "LOP?": LOP_OFF})
    report = run_cleanup(B1500Driver(spy), always_abort=False, emit=Recorder()).report
    assert "CL" in spy.sent and spy.sent[spy.sent.index("CL") + 1:] == ["ERRX?", "LOP?"]
    assert report.verified == "lop"
