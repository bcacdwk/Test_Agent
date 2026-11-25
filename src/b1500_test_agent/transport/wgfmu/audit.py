"""``AuditingWgfmu``: every WGFMU instrument-library call becomes one audit event (blueprint v2 2.4).

The wrapper implements ``WgfmuApi`` over any implementation (``SimWgfmu``, the ctypes ``WgfmuDll``) and records one
``AuditEvent`` with ``ev: wgfmu_call`` per call, in the same sink as the FLEX link's events:

- ``cmd``: the C function behind the method (``C_FUNCTIONS``, e.g. ``WGFMU_addVectors``);
- ``data``: ``fn`` (the Python method), every scalar argument by name (``ch``, ``pattern``, ``t``, ``points`` ...),
  the length of every vector argument (``n_dt``, ``n_v``) instead of its values, and the return code ``rc`` (0, or
  the library code of a failure; firmware failures also carry ``code``, e.g. 3050);
- ``resp``: a short rendering of the result (a status tuple, a measured value, ``n=100000`` for a readback, the
  warning summary's lines: the audit keeps every warning the kernel reads);
- ``error``: the exception text of a failed call (the exception is re-raised unchanged), ``dur_ms`` the duration.

``bind(run=, tx=, intent=)`` stamps the run, transaction and intent on the events inside the block, as
``AuditingTransport.bind`` does for the FLEX link (the transaction's WGFMU phase binds both, WP10.3).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import TypeVar

import numpy as np

from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.common import Backend, JsonScalar
from b1500_test_agent.models.sources import WgfmuCurrentRange, WgfmuForceRange, WgfmuMode, WgfmuVoltageRange
from b1500_test_agent.transport.audit import AuditContext, AuditSink
from b1500_test_agent.transport.wgfmu.api import (
    C_FUNCTIONS,
    NO_ERROR,
    WgfmuApi,
    WgfmuError,
    WgfmuMeasureMode,
    WgfmuWarningLevel,
)

T = TypeVar("T")


def _scalar(value: object) -> JsonScalar:
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        return float(value)
    return str(value)


class AuditingWgfmu:
    """Wraps a ``WgfmuApi``; every call is recorded in ``sink`` as a ``wgfmu_call`` event (see the module
    docstring). ``inner`` is the wrapped implementation (tests and the simulator's extras reach it there)."""

    def __init__(self, inner: WgfmuApi, sink: AuditSink, *, backend: Backend) -> None:
        self.inner = inner
        self.sink = sink
        self.backend: Backend = backend
        self.context = AuditContext()

    @contextmanager
    def bind(self, *, run: str | None = None, tx: str | None = None, intent: str | None = None) -> Iterator[None]:
        """Stamp ``run``/``tx``/``intent`` (those given) on events inside the block, then restore the context."""
        previous = self.context
        updates = {k: v for k, v in (("run", run), ("tx", tx), ("intent", intent)) if v is not None}
        self.context = replace(previous, **updates)
        try:
            yield
        finally:
            self.context = previous

    def _call(self, fn: str, args: dict[str, object], action: Callable[[], T],
              render: Callable[[T], str | None] = lambda _: None, vectors: dict[str, Sequence[float]] | None = None,
              ) -> T:
        data: dict[str, JsonScalar] = {"fn": fn, **{k: _scalar(v) for k, v in args.items()}}
        for name, values in (vectors or {}).items():
            data[f"n_{name}"] = len(values)
        start = time.perf_counter()
        try:
            result = action()
        except BaseException as exc:
            if isinstance(exc, WgfmuError):
                data["rc"] = exc.rc
                if exc.wgfmu_code != exc.rc:
                    data["code"] = exc.wgfmu_code
            self._emit(fn, None, data, start, error=f"{type(exc).__name__}: {exc}")
            raise
        data["rc"] = NO_ERROR
        self._emit(fn, render(result), data, start)
        return result

    def _emit(self, fn: str, resp: str | None, data: dict[str, JsonScalar], start: float,
              error: str | None = None) -> None:
        ctx = self.context
        self.sink.emit(AuditEvent.now("wgfmu_call", self.backend, run=ctx.run, tx=ctx.tx, intent=ctx.intent,
                                      cmd=C_FUNCTIONS[fn][0], resp=resp, dur_ms=(time.perf_counter() - start) * 1e3,
                                      error=error, data=data))

    # -- session -------------------------------------------------------------------------------------------------------

    def open_session(self, address: str) -> None:
        self._call("open_session", {"address": address}, lambda: self.inner.open_session(address))

    def close_session(self) -> None:
        self._call("close_session", {}, self.inner.close_session)

    def initialize(self) -> None:
        self._call("initialize", {}, self.inner.initialize)

    def clear(self) -> None:
        self._call("clear", {}, self.inner.clear)

    def set_timeout(self, s: float) -> None:
        self._call("set_timeout", {"s": s}, lambda: self.inner.set_timeout(s))

    def channel_ids(self) -> list[int]:
        return self._call("channel_ids", {}, self.inner.channel_ids, lambda ids: ",".join(str(c) for c in ids))

    # -- channel setup -------------------------------------------------------------------------------------------------

    def set_operation_mode(self, ch: int, mode: WgfmuMode) -> None:
        self._call("set_operation_mode", {"ch": ch, "mode": mode}, lambda: self.inner.set_operation_mode(ch, mode))

    def set_force_voltage_range(self, ch: int, rng: WgfmuForceRange) -> None:
        self._call("set_force_voltage_range", {"ch": ch, "rng": rng},
                   lambda: self.inner.set_force_voltage_range(ch, rng))

    def set_measure_mode(self, ch: int, mode: WgfmuMeasureMode) -> None:
        self._call("set_measure_mode", {"ch": ch, "mode": mode}, lambda: self.inner.set_measure_mode(ch, mode))

    def set_measure_current_range(self, ch: int, rng: WgfmuCurrentRange) -> None:
        self._call("set_measure_current_range", {"ch": ch, "rng": rng},
                   lambda: self.inner.set_measure_current_range(ch, rng))

    def set_measure_voltage_range(self, ch: int, rng: WgfmuVoltageRange) -> None:
        self._call("set_measure_voltage_range", {"ch": ch, "rng": rng},
                   lambda: self.inner.set_measure_voltage_range(ch, rng))

    def set_measure_enabled(self, ch: int, on: bool) -> None:
        self._call("set_measure_enabled", {"ch": ch, "on": on}, lambda: self.inner.set_measure_enabled(ch, on))

    # -- waveform setup ------------------------------------------------------------------------------------------------

    def create_pattern(self, name: str, v0: float) -> None:
        self._call("create_pattern", {"pattern": name, "v0": v0}, lambda: self.inner.create_pattern(name, v0))

    def add_vectors(self, name: str, dt: Sequence[float], v: Sequence[float]) -> None:
        self._call("add_vectors", {"pattern": name}, lambda: self.inner.add_vectors(name, dt, v),
                   vectors={"dt": dt, "v": v})

    def set_measure_event(self, pattern: str, event: str, t: float, points: int, interval: float, average: float,
                          raw: bool) -> None:
        self._call("set_measure_event", {"pattern": pattern, "event": event, "t": t, "points": points,
                                         "interval": interval, "average": average, "raw": raw},
                   lambda: self.inner.set_measure_event(pattern, event, t, points, interval, average, raw))

    def set_range_event(self, pattern: str, event: str, t: float, rng: WgfmuCurrentRange) -> None:
        self._call("set_range_event", {"pattern": pattern, "event": event, "t": t, "rng": rng},
                   lambda: self.inner.set_range_event(pattern, event, t, rng))

    def add_sequence(self, ch: int, pattern: str, count: float) -> None:
        self._call("add_sequence", {"ch": ch, "pattern": pattern, "count": count},
                   lambda: self.inner.add_sequence(ch, pattern, count))

    # -- execution -----------------------------------------------------------------------------------------------------

    def update(self) -> None:
        self._call("update", {}, self.inner.update)

    def connect(self, ch: int) -> None:
        self._call("connect", {"ch": ch}, lambda: self.inner.connect(ch))

    def disconnect(self, ch: int) -> None:
        self._call("disconnect", {"ch": ch}, lambda: self.inner.disconnect(ch))

    def execute(self) -> None:
        self._call("execute", {}, self.inner.execute)

    def wait_until_completed(self) -> None:
        self._call("wait_until_completed", {}, self.inner.wait_until_completed)

    def abort(self) -> None:
        self._call("abort", {}, self.inner.abort)

    def status(self) -> tuple[int, float, float]:
        return self._call("status", {}, self.inner.status, _render_status)

    def channel_status(self, ch: int) -> tuple[int, float, float]:
        return self._call("channel_status", {"ch": ch}, lambda: self.inner.channel_status(ch), _render_status)

    def measure_value_size(self, ch: int) -> tuple[int, int]:
        return self._call("measure_value_size", {"ch": ch}, lambda: self.inner.measure_value_size(ch),
                          lambda size: f"{size[0]}/{size[1]}")

    def measure_values(self, ch: int, offset: int, size: int) -> tuple[np.ndarray, np.ndarray]:
        return self._call("measure_values", {"ch": ch, "offset": offset, "size": size},
                          lambda: self.inner.measure_values(ch, offset, size), lambda data: f"n={len(data[0])}")

    # -- DC, maintenance, errors ---------------------------------------------------------------------------------------

    def dc_force_voltage(self, ch: int, v: float) -> None:
        self._call("dc_force_voltage", {"ch": ch, "v": v}, lambda: self.inner.dc_force_voltage(ch, v))

    def dc_measure_value(self, ch: int) -> float:
        return self._call("dc_measure_value", {"ch": ch}, lambda: self.inner.dc_measure_value(ch), lambda x: f"{x:.6g}")

    def self_test(self) -> int:
        return self._call("self_test", {}, self.inner.self_test, str)

    def self_calibration(self) -> int:
        return self._call("self_calibration", {}, self.inner.self_calibration, str)

    def errors(self) -> list[str]:
        return self._call("errors", {}, self.inner.errors, lambda found: f"{len(found)} error(s)")

    def set_warning_level(self, level: WgfmuWarningLevel) -> None:
        self._call("set_warning_level", {"level": level}, lambda: self.inner.set_warning_level(level))

    def warning_level(self) -> WgfmuWarningLevel:
        return self._call("warning_level", {}, self.inner.warning_level, str)

    def treat_warnings_as_errors(self, level: WgfmuWarningLevel) -> None:
        self._call("treat_warnings_as_errors", {"level": level}, lambda: self.inner.treat_warnings_as_errors(level))

    def warnings(self) -> list[str]:
        return self._call("warnings", {}, self.inner.warnings, _render_warnings)


WARNINGS_RESP_CHARS = 600
"""Longest rendering of a warning summary in one audit event (the run's ``kind_result`` keeps the lines too)."""


def _render_warnings(found: list[str]) -> str:
    text = f"{len(found)} warning(s)" + (": " + " | ".join(found) if found else "")
    return text if len(text) <= WARNINGS_RESP_CHARS else text[:WARNINGS_RESP_CHARS - 3] + "..."


def _render_status(result: tuple[int, float, float]) -> str:
    status, elapsed, total = result
    return f"{status},{elapsed:.9g},{total:.9g}"
