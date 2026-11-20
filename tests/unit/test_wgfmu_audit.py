"""``AuditingWgfmu`` (blueprint v2 2.4 ``transport/wgfmu/audit.py``): every library call is one ``wgfmu_call`` event
with the C function, the scalar arguments, vector counts and the return code; failures keep their codes and are
re-raised unchanged; ``bind`` stamps run, transaction and intent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from b1500_test_agent.models.audit import LIBRARY_EVENTS, AuditEvent
from b1500_test_agent.transport.audit import MemoryAuditSink
from b1500_test_agent.transport.wgfmu.api import API_METHODS, C_FUNCTIONS, WgfmuError
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu

pytestmark = pytest.mark.wgfmu


class Recorder:
    """A ``WgfmuApi`` stand-in returning fixed results and recording the calls it receives."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail: dict[str, WgfmuError] = {}

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name not in API_METHODS:
            raise AttributeError(name)
        results = {"channel_ids": [201, 202], "status": (10002, 0.5, 2.0), "channel_status": (10000, 2.0, 2.0),
                   "measure_value_size": (40, 100), "measure_values": (np.zeros(3), np.ones(3)),
                   "dc_measure_value": 1.25e-6, "self_test": 0, "self_calibration": 4, "errors": ["a", "b"]}

        def call(*args: Any) -> Any:
            self.calls.append((name, args))
            if name in self.fail:
                raise self.fail[name]
            return results.get(name)

        return call


CALLS: list[tuple[str, tuple[Any, ...], dict[str, Any], str | None]] = [
    ("open_session", ("GPIB0::17::INSTR",), {"address": "GPIB0::17::INSTR"}, None),
    ("close_session", (), {}, None),
    ("initialize", (), {}, None),
    ("clear", (), {}, None),
    ("set_timeout", (120.0,), {"s": 120.0}, None),
    ("channel_ids", (), {}, "201,202"),
    ("set_operation_mode", (201, "fastiv"), {"ch": 201, "mode": "fastiv"}, None),
    ("set_force_voltage_range", (201, "5v"), {"ch": 201, "rng": "5v"}, None),
    ("set_measure_mode", (202, "current"), {"ch": 202, "mode": "current"}, None),
    ("set_measure_current_range", (202, "1ma"), {"ch": 202, "rng": "1ma"}, None),
    ("set_measure_voltage_range", (201, "10v"), {"ch": 201, "rng": "10v"}, None),
    ("set_measure_enabled", (201, False), {"ch": 201, "on": False}, None),
    ("create_pattern", ("p", 0.5), {"pattern": "p", "v0": 0.5}, None),
    ("add_vectors", ("p", np.full(1825, 1e-7), np.zeros(1825)), {"pattern": "p", "n_dt": 1825, "n_v": 1825}, None),
    ("set_measure_event", ("p", "e", 0.0, np.int64(504000), 1e-7, 0.0, True),
     {"pattern": "p", "event": "e", "t": 0.0, "points": 504000, "interval": 1e-7, "average": 0.0, "raw": True}, None),
    ("set_range_event", ("p", "r", 1e-6, "10ua"), {"pattern": "p", "event": "r", "t": 1e-6, "rng": "10ua"}, None),
    ("add_sequence", (201, "p", 1e6), {"ch": 201, "pattern": "p", "count": 1e6}, None),
    ("update", (), {}, None),
    ("connect", (201,), {"ch": 201}, None),
    ("disconnect", (201,), {"ch": 201}, None),
    ("execute", (), {}, None),
    ("wait_until_completed", (), {}, None),
    ("abort", (), {}, None),
    ("status", (), {}, "10002,0.5,2"),
    ("channel_status", (202,), {"ch": 202}, "10000,2,2"),
    ("measure_value_size", (202,), {"ch": 202}, "40/100"),
    ("measure_values", (202, 0, 100000), {"ch": 202, "offset": 0, "size": 100000}, "n=3"),
    ("dc_force_voltage", (201, 0.1), {"ch": 201, "v": 0.1}, None),
    ("dc_measure_value", (201,), {"ch": 201}, "1.25e-06"),
    ("self_test", (), {}, "0"),
    ("self_calibration", (), {}, "4"),
    ("errors", (), {}, "2 error(s)"),
]


def test_every_method_is_covered_here() -> None:
    assert [c[0] for c in CALLS] == list(API_METHODS)


@pytest.mark.parametrize(("fn", "args", "data", "resp"), CALLS, ids=[c[0] for c in CALLS])
def test_each_call_is_one_event(fn: str, args: tuple[Any, ...], data: dict[str, Any], resp: str | None) -> None:
    inner, sink = Recorder(), MemoryAuditSink()
    wrapped = AuditingWgfmu(inner, sink, backend="sim")
    getattr(wrapped, fn)(*args)
    assert [c[0] for c in inner.calls] == [fn]
    (event,) = sink.events
    assert event.ev == "wgfmu_call" and event.ev in LIBRARY_EVENTS and event.backend == "sim"
    assert event.cmd == C_FUNCTIONS[fn][0] and event.resp == resp and event.error is None
    assert event.data == {"fn": fn, **data, "rc": 0}
    assert all(not isinstance(v, np.generic) for v in event.data.values())
    line = AuditEvent.from_json_line(event.to_json_line())
    assert line.data == event.data


def test_failures_keep_their_codes_and_are_reraised_unchanged() -> None:
    inner, sink = Recorder(), MemoryAuditSink()
    error = WgfmuError(3050, "firmware error 3050: Measurement data memory overflow error.", function="execute")
    inner.fail["execute"] = error
    inner.fail["add_vectors"] = WgfmuError(-10, "add_vectors: -10 pattern not found", function="add_vectors")
    wrapped = AuditingWgfmu(inner, sink, backend="visa")
    with pytest.raises(WgfmuError) as info:
        wrapped.execute()
    assert info.value is error
    with pytest.raises(WgfmuError):
        wrapped.add_vectors("x", [1e-6], [0.0])
    fw, lib = sink.events
    assert fw.data == {"fn": "execute", "rc": -6, "code": 3050} and "3050" in (fw.error or "")
    assert lib.data == {"fn": "add_vectors", "pattern": "x", "n_dt": 1, "n_v": 1, "rc": -10}
    assert fw.backend == "visa"


def test_bind_stamps_run_transaction_and_intent() -> None:
    inner, sink = Recorder(), MemoryAuditSink()
    wrapped = AuditingWgfmu(inner, sink, backend="sim")
    with wrapped.bind(run="S1", tx="T1", intent="wgfmu phase"):
        wrapped.execute()
        with wrapped.bind(intent="readback"):
            wrapped.measure_values(201, 0, 10)
    wrapped.abort()
    stamps = [(e.run, e.tx, e.intent) for e in sink.events]
    assert stamps == [("S1", "T1", "wgfmu phase"), ("S1", "T1", "readback"), (None, None, None)]
    assert [e.seq for e in sink.events] == [0, 1, 2]
