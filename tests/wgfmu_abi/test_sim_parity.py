"""The WG programming examples through the C binding (blueprint v2 7.1 "WGFMU fake-ABI", 8.1; WP10.2).

Each replay of WG chapter 3 (``tests/sim/wgfmu_examples.py``: Examples 1-11, the DC guide, Table 4-15) runs twice on
identical simulated stations: once on ``SimWgfmu`` directly (as WP10.1 tested it) and once through the real
``WgfmuDll`` over the ctypes-shaped fake library backed by the same kind of ``SimWgfmu``. Every value, status tuple,
data array and error (code, return code, text, function) must be identical: the binding adds the C marshalling,
chunked readback and error-string handling and nothing else.

One difference is by design: an argument no C function can take (Examples 3 and 5 pass the literal ``"current"`` as an
operation mode) is refused by the binding with the code the library would return, and its text is queued for
``errors()``, but it never reaches the library, so the library's internal error summary (Example 5, a simulator extra)
does not list it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.sim import wgfmu_examples as ex
from tests.wgfmu_abi.conftest import make_binding

pytestmark = pytest.mark.wgfmu


def _mosfet() -> SimScenario:
    p = ex.example("ex09")["params"]
    return ex.scenario({"m": {"model": "mosfet_ekv", "params": {"polarity": "p", "vth0": -1.5, "beta": 2.0e-5}}},
                       {"m": {"gate": p["gate"], "drain": p["drain"], "source": "GNDU", "bulk": "GNDU"}})


def _resistor(name: str, a: int | str, b: int | str) -> Callable[[], SimScenario]:
    return lambda: ex.resistor(ex.example(name)["params"]["r_ohm"], a, b)


def _dc() -> SimScenario:
    p = ex.example("dc")["params"]
    return ex.resistor(p["r_ohm"], p["channel"], "GNDU")


def _ex10_current(st: ex.Station) -> dict[str, Any]:
    return ex.ex10(st, measure_current=True)


CASES: list[tuple[str, Callable[[ex.Station], dict[str, Any]], Callable[[], SimScenario | None]]] = [
    ("ex01", ex.ex01, lambda: None), ("ex02", ex.ex02, lambda: None), ("ex03", ex.ex03, lambda: None),
    ("ex04", ex.ex04, lambda: None), ("ex05", ex.ex05, lambda: None),
    ("ex06", ex.ex06, _resistor("ex06", 101, 102)), ("ex07", ex.ex07, _resistor("ex06", 101, 102)),
    ("ex08", ex.ex08, _resistor("ex06", 101, 102)), ("ex09", ex.ex09, _mosfet),
    ("ex10", ex.ex10, _resistor("ex10", 101, 201)), ("ex10-current", _ex10_current, _resistor("ex10", 101, 201)),
    ("ex11", ex.ex11, lambda: None), ("dc", ex.dc, _dc),
]


def same(a: Any, b: Any, where: str = "result") -> None:
    """Assert ``a`` and ``b`` are identical (arrays element by element, errors by their codes and text)."""
    if isinstance(a, WgfmuError):
        assert isinstance(b, WgfmuError), where
        assert (a.wgfmu_code, a.rc, a.text, a.function, str(a)) == (b.wgfmu_code, b.rc, b.text, b.function,
                                                                    str(b)), where
    elif isinstance(a, np.ndarray):
        assert isinstance(b, np.ndarray) and a.shape == b.shape and np.array_equal(a, b), where
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), where
        for key in a:
            same(a[key], b[key], f"{where}.{key}")
    elif isinstance(a, list | tuple):
        assert type(a) is type(b) and len(a) == len(b), where
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            same(x, y, f"{where}[{index}]")
    else:
        assert a == b, (where, a, b)


@pytest.mark.parametrize(("name", "replay", "scenario"), CASES, ids=[c[0] for c in CASES])
def test_example_through_the_binding_equals_the_simulator(dll_path: str, name: str, replay, scenario) -> None:
    direct = ex.station(scenario())
    expected = replay(direct)
    binding = make_binding(dll_path, scenario())
    got = replay(binding.st)
    if name == "ex05":  # the refused literal is not in the library's own summary (module docstring)
        refused, rest = expected["summary"].splitlines()
        assert refused.startswith("set_operation_mode: -1") and got["summary"] == rest
        expected, got = ({k: v for k, v in r.items() if k != "summary"} for r in (expected, got))
    same(expected, got, name)
    assert binding.dll.loaded and binding.lib.calls  # it really went through the C functions
    direct_calls = [(e.cmd, e.data, _message(e.error)) for e in direct.sink.events if e.ev == "wgfmu_call"]
    via_calls = [(e.cmd, e.data, _message(e.error)) for e in binding.st.wg.sink.events if e.ev == "wgfmu_call"]
    assert via_calls == direct_calls  # the same protocol calls with the same arguments, return codes and errors
    # the same instrument state afterwards (Example 3 leaves its session open by design, on both)
    assert binding.st.flex.instrument.unsafe_reasons() == direct.flex.instrument.unsafe_reasons()


def _message(error: str | None) -> str | None:
    """An audited error without its exception class (a refusal is an ``ArgumentRefused``, a ``WgfmuError``)."""
    return None if error is None else error.split(": ", 1)[1]
