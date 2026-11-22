"""A ctypes-shaped stand-in for ``wgfmu.dll`` (blueprint v2 7.1 "WGFMU fake-ABI", 8.1 ``wgfmu_abi/``).

``FakeWgfmuLibrary`` looks to ``WgfmuDll`` like the object ``ctypes.WinDLL(path)`` returns: one attribute per
exported C function (``AttributeError`` for any other name, as ctypes raises for a missing export), each with
settable ``argtypes``/``restype``. A call is checked the way ctypes marshals it: the binding must have set
``argtypes`` and ``restype`` first, the argument count must match, and every argument must pass its argtype's
``from_param`` (a ``str`` for a ``c_char_p``, a float for a ``c_int``, a ``double*`` where an ``int*`` belongs all
fail as they would in ctypes). Outputs are written through the pointers, ``byref`` objects and string buffers the
binding passed, with C semantics: return code, out-parameters, an error-string queue read with
``WGFMU_getErrorSize``/``WGFMU_getError``.

Behaviour comes from a ``WgfmuApi`` backend, normally a ``SimWgfmu`` (so the WG examples, the faults and the
simulated instrument stay what WP10.1 built): integer codes are decoded back to the protocol's literals, a
``WgfmuError`` of the backend becomes its return code and its text stays in the backend's error queue, which the
error functions read. ``fail(name, rc, text)`` forces failures; ``crash(name, exc)`` makes a call raise like an access
violation. Nothing here imports ``ctypes`` (lint ``tests/unit/test_lint_ctypes.py``): the ctypes objects arrive from
the binding and are used through their own methods.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np

from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuApi, WgfmuError
from b1500_test_agent.transport.wgfmu.dll import C_SIGNATURES


def _reverse(table: dict[Any, int]) -> dict[int, Any]:
    return {code: literal for literal, code in table.items()}


OPERATION_MODES = _reverse(api.OPERATION_MODES)
FORCE_RANGES = _reverse(api.FORCE_VOLTAGE_RANGES)
MEASURE_MODES = _reverse(api.MEASURE_MODES)
CURRENT_RANGES = _reverse(api.MEASURE_CURRENT_RANGES)
VOLTAGE_RANGES = _reverse(api.MEASURE_VOLTAGE_RANGES)
ENABLED = _reverse(api.MEASURE_ENABLED)
EVENT_DATA = _reverse(api.MEASURE_EVENT_DATA)


class Unknown(Exception):
    """A code the backend's protocol has no literal for."""


def _decode(table: dict[int, Any], code: object, what: str) -> Any:
    if code not in table:
        raise Unknown(f"{what} code {code!r}")
    return table[code]


def _target(arg: Any) -> Any:
    """The ctypes object behind a ``byref(...)`` argument (or the argument itself)."""
    return getattr(arg, "_obj", arg)


def store(arg: Any, value: Any) -> None:
    """Write ``value`` through an out-parameter (``byref(c_int)``, ``pointer(c_double)`` ...)."""
    obj = _target(arg)
    if hasattr(obj, "contents"):
        obj.contents.value = value
    else:
        obj.value = value


def load(arg: Any) -> Any:
    """Read the value an in/out parameter points at."""
    obj = _target(arg)
    return obj.contents.value if hasattr(obj, "contents") else obj.value


def array(pointer: Any, n: int) -> np.ndarray:
    """A numpy view of ``n`` elements at a ctypes pointer (writes go to the caller's buffer)."""
    return np.ctypeslib.as_array(pointer, shape=(n,))


def write_string(buffer: Any, text: str, size: int) -> int:
    """Store at most ``size`` characters of ``text`` in a ``create_string_buffer`` buffer; returns how many."""
    data = text.encode("ascii", errors="replace")[:max(0, min(size, len(buffer) - 1))]
    buffer.value = data
    return len(data)


@dataclass(frozen=True)
class Call:
    """One C call as the binding made it (``args`` are the marshalled objects; ``requested`` the in-value of
    ``WGFMU_getMeasureValues``'s in/out ``length``, which the call overwrites with the count read)."""

    name: str
    args: tuple[Any, ...]
    requested: int | None = None


class FakeFunction:
    """One exported C function (see the module docstring)."""

    def __init__(self, library: FakeWgfmuLibrary, name: str) -> None:
        self.library = library
        self.__name__ = name
        self.argtypes: list[Any] | None = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> int:
        name = self.__name__
        if self.argtypes is None or self.restype is None:
            raise AssertionError(f"{name} called before the binding set argtypes and restype")
        if len(args) != len(self.argtypes):
            raise TypeError(f"{name}: this function takes {len(self.argtypes)} arguments ({len(args)} given)")
        for index, (kind, arg) in enumerate(zip(self.argtypes, args, strict=True)):
            try:
                kind.from_param(arg)
            except Exception as exc:  # noqa: BLE001 - ctypes reports this as ArgumentError
                raise TypeError(f"{name}: argument {index + 1}: {type(exc).__name__}: {exc}") from None
        return self.library.dispatch(name, args)


class FakeWgfmuLibrary:
    """``ctypes.WinDLL``-shaped library over ``backend`` (see the module docstring). ``exports`` defaults to every
    function of the binding's table."""

    def __init__(self, backend: WgfmuApi, *, exports: Iterable[str] | None = None, path: str = "wgfmu.dll") -> None:
        self.backend = backend
        self.path = path
        self.exports = frozenset(C_SIGNATURES if exports is None else exports)
        self.calls: list[Call] = []
        self.pending: deque[str] = deque()
        self.forced: dict[str, dict[int, tuple[int, str]]] = {}
        self.counts: Counter[str] = Counter()
        self.crashes: dict[str, BaseException] = {}
        self._functions: dict[str, FakeFunction] = {}
        self._ids: list[int] | None = None
        self._impl: dict[str, Callable[..., None]] = {
            name: getattr(self, f"_{name[len('WGFMU_'):]}") for name in C_SIGNATURES}

    def __getattr__(self, name: str) -> FakeFunction:
        if name.startswith("_") or name not in self.__dict__.get("exports", ()):
            raise AttributeError(f"function '{name}' not found")
        functions = self.__dict__["_functions"]
        if name not in functions:
            functions[name] = FakeFunction(self, name)
        return functions[name]

    # -- test controls -------------------------------------------------------------------------------------------------

    def fail(self, name: str, rc: int, text: str, *, nth: int = 1, times: int = 1) -> None:
        """Calls ``nth`` to ``nth + times - 1`` from now of C function ``name`` return ``rc`` and queue ``text``
        (the backend is not called; ``nth=1`` = the next call)."""
        planned = self.forced.setdefault(name, {})
        for k in range(times):
            planned[self.counts[name] + nth + k] = (rc, text)

    def crash(self, name: str, exc: BaseException) -> None:
        """The next call of ``name`` raises ``exc`` (an access violation surfaces as ``OSError`` in ctypes)."""
        self.crashes[name] = exc

    def names(self) -> list[str]:
        """The C functions called so far, in order."""
        return [c.name for c in self.calls]

    # -- dispatch ------------------------------------------------------------------------------------------------------

    def dispatch(self, name: str, args: tuple[Any, ...]) -> int:
        requested = int(load(args[2])) if name == "WGFMU_getMeasureValues" else None
        self.calls.append(Call(name, args, requested))
        self.counts[name] += 1
        if name in self.crashes:
            raise self.crashes.pop(name)
        forced = self.forced.get(name, {}).pop(self.counts[name], None)
        if forced is not None:
            rc, text = forced
            self._queue(text)
            return rc
        try:
            self._impl[name](*args)
        except WgfmuError as exc:  # the backend queued its text
            return exc.rc
        except Unknown as exc:
            self._queue(f"{name}: {api.error_text(api.PARAMETER_OUT_OF_RANGE, str(exc))}")
            return api.PARAMETER_OUT_OF_RANGE
        return api.NO_ERROR

    def _queue(self, text: str) -> None:
        self._fill()
        if text:
            self.pending.append(text)

    def _fill(self) -> None:
        if not self.pending:
            self.pending.extend(self.backend.errors())

    # -- the C functions -----------------------------------------------------------------------------------------------

    def _openSession(self, address: bytes) -> None:
        self.backend.open_session(address.decode("ascii"))

    def _closeSession(self) -> None:
        self.backend.close_session()

    def _initialize(self) -> None:
        self.backend.initialize()

    def _clear(self) -> None:
        self.backend.clear()

    def _setTimeout(self, timeout: float) -> None:
        self.backend.set_timeout(timeout)

    def _getChannelIdSize(self, size: Any) -> None:
        self._ids = self.backend.channel_ids()
        store(size, len(self._ids))

    def _getChannelIds(self, result: Any, size: Any) -> None:
        ids = self._ids if self._ids is not None else self.backend.channel_ids()
        self._ids = None
        n = max(0, min(int(load(size)), len(ids)))
        array(result, n)[:] = ids[:n]
        store(size, n)

    def _setOperationMode(self, ch: int, mode: int) -> None:
        self.backend.set_operation_mode(ch, _decode(OPERATION_MODES, mode, "operation mode"))

    def _setForceVoltageRange(self, ch: int, rng: int) -> None:
        self.backend.set_force_voltage_range(ch, _decode(FORCE_RANGES, rng, "force range"))

    def _setMeasureMode(self, ch: int, mode: int) -> None:
        self.backend.set_measure_mode(ch, _decode(MEASURE_MODES, mode, "measure mode"))

    def _setMeasureCurrentRange(self, ch: int, rng: int) -> None:
        self.backend.set_measure_current_range(ch, _decode(CURRENT_RANGES, rng, "current range"))

    def _setMeasureVoltageRange(self, ch: int, rng: int) -> None:
        self.backend.set_measure_voltage_range(ch, _decode(VOLTAGE_RANGES, rng, "voltage range"))

    def _setMeasureEnabled(self, ch: int, status: int) -> None:
        self.backend.set_measure_enabled(ch, _decode(ENABLED, status, "measure enabled"))

    def _createPattern(self, pattern: bytes, init_v: float) -> None:
        self.backend.create_pattern(pattern.decode("ascii"), init_v)

    def _addVectors(self, pattern: bytes, d_time: Any, voltage: Any, size: int) -> None:
        self.backend.add_vectors(pattern.decode("ascii"), array(d_time, size).copy(), array(voltage, size).copy())

    def _setMeasureEvent(self, pattern: bytes, event: bytes, time: float, points: int, interval: float,
                         average: float, rdata: int) -> None:
        self.backend.set_measure_event(pattern.decode("ascii"), event.decode("ascii"), time, points, interval,
                                       average, _decode(EVENT_DATA, rdata, "data output mode"))

    def _setRangeEvent(self, pattern: bytes, event: bytes, time: float, rng: int) -> None:
        self.backend.set_range_event(pattern.decode("ascii"), event.decode("ascii"), time,
                                     _decode(CURRENT_RANGES, rng, "current range"))

    def _addSequence(self, ch: int, pattern: bytes, count: float) -> None:
        self.backend.add_sequence(ch, pattern.decode("ascii"), count)

    def _update(self) -> None:
        self.backend.update()

    def _connect(self, ch: int) -> None:
        self.backend.connect(ch)

    def _disconnect(self, ch: int) -> None:
        self.backend.disconnect(ch)

    def _execute(self) -> None:
        self.backend.execute()

    def _waitUntilCompleted(self) -> None:
        self.backend.wait_until_completed()

    def _abort(self) -> None:
        self.backend.abort()

    def _getStatus(self, status: Any, elapsed: Any, total: Any) -> None:
        code, t_elapsed, t_total = self.backend.status()
        store(status, code)
        store(elapsed, t_elapsed)
        store(total, t_total)

    def _getChannelStatus(self, ch: int, status: Any, elapsed: Any, total: Any) -> None:
        code, t_elapsed, t_total = self.backend.channel_status(ch)
        store(status, code)
        store(elapsed, t_elapsed)
        store(total, t_total)

    def _getMeasureValueSize(self, ch: int, complete: Any, total: Any) -> None:
        measured, values = self.backend.measure_value_size(ch)
        store(complete, measured)
        store(total, values)

    def _getMeasureValues(self, ch: int, index: int, length: Any, time: Any, value: Any) -> None:
        times, values = self.backend.measure_values(ch, index, int(load(length)))
        n = len(times)
        array(time, n)[:] = times
        array(value, n)[:] = values
        store(length, n)

    def _dcforceVoltage(self, ch: int, voltage: float) -> None:
        self.backend.dc_force_voltage(ch, voltage)

    def _dcmeasureValue(self, ch: int, value: Any) -> None:
        store(value, self.backend.dc_measure_value(ch))

    def _maintenance(self, run: Callable[[], int], result: Any, detail: Any, size: Any) -> None:
        outcome = run()
        text = "PASS" if outcome == 0 else f"FAIL (slot bitmask {outcome})"
        store(size, write_string(detail, text, int(load(size))))
        store(result, outcome)

    def _doSelfTest(self, result: Any, detail: Any, size: Any) -> None:
        self._maintenance(self.backend.self_test, result, detail, size)

    def _doSelfCalibration(self, result: Any, detail: Any, size: Any) -> None:
        self._maintenance(self.backend.self_calibration, result, detail, size)

    def _getErrorSize(self, size: Any) -> None:
        self._fill()
        store(size, len(self.pending[0]) if self.pending else 0)

    def _getError(self, result: Any, size: Any) -> None:
        wanted = int(load(size))
        if wanted <= 0:
            raise WgfmuError(api.PARAMETER_OUT_OF_RANGE, "getError: size must be positive", function="errors")
        self._fill()
        text = self.pending.popleft() if self.pending else ""
        store(size, write_string(result, text, wanted))
