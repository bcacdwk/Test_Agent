"""``VisaTransport``: the real B1500A over VISA (blueprint 2.2, 7; ATV-2).

This is the ONLY module that imports ``pyvisa`` (import-layering lint), and it does so lazily in ``open()`` so the
rest of the package and the simulator never load it. Library: ``VisaSettings.library`` or, when empty, the vendor
stack ``@ivi`` (never ``@py``/``@sim`` by default). Terminations: write ``\\n``, read ``\\n``; a trailing ``\\r``
of the response is stripped (ATV-2: confirmed at hardware bring-up, settable in ``config/local/settings.yaml``).
Responses are decoded as latin-1, so any byte sequence is a string and raw data can be archived losslessly.
"""

from __future__ import annotations

import contextlib
from typing import Any, Literal

from b1500_test_agent.models.station import VisaSettings
from b1500_test_agent.transport.base import TransportClosed, TransportError, TransportTimeout

DEFAULT_LIBRARY = "@ivi"
"""PyVISA backend used when ``VisaSettings.library`` is empty: the installed vendor VISA (Keysight IO or NI)."""


class VisaTransport:
    """Message-based VISA session to one resource (``GPIB0::17::INSTR`` by default)."""

    backend: Literal["visa"] = "visa"

    def __init__(self, cfg: VisaSettings) -> None:
        self.cfg = cfg
        self.resource = cfg.resource
        self.library = cfg.library or DEFAULT_LIBRARY
        self._rm: Any = None
        self._inst: Any = None
        self._timeout_code: int | None = None

    # -- helpers ------------------------------------------------------------------------------------------------------

    def _require_open(self) -> Any:
        if self._inst is None:
            raise TransportClosed(f"VISA session to {self.resource} is not open.")
        return self._inst

    def _translate(self, exc: BaseException, action: str) -> TransportError:
        code = getattr(exc, "error_code", None)
        if code is not None and code == self._timeout_code:
            return TransportTimeout(f"{action} on {self.resource} timed out: {exc}")
        if isinstance(exc, NotImplementedError):
            return TransportError(f"{action} is not supported by VISA library {self.library!r}.")
        return TransportError(f"{action} on {self.resource} failed: {type(exc).__name__}: {exc}")

    def _io(self, action: str, fn: Any, *args: Any) -> Any:
        self._require_open()
        try:
            return fn(*args)
        except TransportError:
            raise
        except Exception as exc:  # pyvisa raises VisaIOError, InvalidSession, NotImplementedError, OSError ...
            raise self._translate(exc, action) from exc

    # -- Transport protocol -------------------------------------------------------------------------------------------

    def open(self) -> None:
        if self._inst is not None:
            return
        try:
            import pyvisa
            from pyvisa import constants
        except ImportError as exc:  # pragma: no cover - pyvisa is a runtime dependency
            raise TransportError(f"pyvisa is not installed: {exc}") from exc
        self._timeout_code = int(constants.StatusCode.error_timeout)
        try:
            rm = pyvisa.ResourceManager(self.library)
        except Exception as exc:
            raise TransportError(f"Cannot load VISA library {self.library!r}: {type(exc).__name__}: {exc}") from exc
        access = constants.AccessModes.exclusive_lock if self.cfg.exclusive_lock else constants.AccessModes.no_lock
        try:
            inst = rm.open_resource(self.resource, access_mode=access)
            if not all(hasattr(inst, name) for name in ("write", "read", "read_stb", "clear")):
                raise TypeError(f"{self.resource} is not a message-based instrument resource")
            inst.write_termination = self.cfg.write_termination
            inst.read_termination = self.cfg.read_termination
            inst.timeout = self.cfg.timeout_ms
            inst.encoding = "latin-1"
        except Exception as exc:
            with contextlib.suppress(Exception):  # best-effort cleanup of a failed open
                rm.close()
            raise self._translate(exc, "open") from exc
        self._rm, self._inst = rm, inst

    def close(self) -> None:
        inst, rm = self._inst, self._rm
        self._inst = self._rm = None
        for item in (inst, rm):
            if item is None:
                continue
            with contextlib.suppress(Exception):  # closing must never raise
                item.close()

    def write(self, cmd: str) -> None:
        self._io(f"write {cmd!r}", self._require_open().write, cmd)

    def read(self, *, timeout_s: float | None = None) -> str:
        inst = self._require_open()
        if timeout_s is None:
            text = self._io("read", inst.read)
        else:
            previous = inst.timeout
            inst.timeout = max(1, round(timeout_s * 1000.0))
            try:
                text = self._io("read", inst.read)
            finally:
                inst.timeout = previous
        return str(text).rstrip("\r\n")

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        self.write(cmd)
        return self.read(timeout_s=timeout_s)

    def serial_poll(self) -> int:
        return int(self._io("serial poll", self._require_open().read_stb))

    def device_clear(self) -> None:
        self._io("device clear", self._require_open().clear)
