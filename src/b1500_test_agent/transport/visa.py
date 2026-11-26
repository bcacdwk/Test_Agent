"""``VisaTransport``: the real B1500A over VISA, opened per transaction (blueprint v2 2.4, 7.1; ATV-2, ATV-13).

This is the ONLY module that imports ``pyvisa`` (import-layering lint), and it does so lazily in ``open()`` so the
rest of the package and the simulator never load it. Library: ``VisaSettings.library`` or, when empty, the vendor
stack ``@ivi`` (never ``@py``/``@sim`` by default). Terminations: write ``\\n``, read ``\\n``; a trailing ``\\r``
of the response is stripped (ATV-2: confirmed at hardware bring-up, settable in ``config/local/settings.yaml``).
Responses are decoded as latin-1, so any byte sequence is a string and raw data can be archived losslessly.

Lifecycle (blueprint v2 2.4, decision 7): the session calls ``open`` (VISA session, no lock) -> ``lock``
(``lock_excl`` when ``exclusive_lock``, waiting up to ``lock_timeout_ms`` for another client) -> I/O -> ``unlock``
-> ``close`` for every transaction and status snapshot, so the MCP server holds nothing between calls and the CLI
can probe the instrument; ``visa.session: process`` (ATV-13 fallback) keeps the session open and only locks per
transaction. ``list_resources`` loads the library and lists the resources without opening one (the first lines of
``b1500 doctor --probe``). A lock held by another client, or I/O refused because another session holds the lock, raises
``BusLocked`` (result ``instrument_busy``, nothing sent); a timeout raises ``TransportTimeout``, after which the
transaction's cleanup sends a device clear (as in v1). The resource manager is injectable (``rm_factory``: called
with the library string, returns an object with ``open_resource``/``close``); the visa-loop tests
(``tests/visa_loop/``) run this class unchanged against the simulator that way.

TODO(verify)[L0.P4, L1.A4] ATV-13 (blueprint 7.6 item 1): open + lock + unlock + close per transaction stays
below 100 ms over GPIB (``bus_*`` audit events carry ``dur_ms``); fallback ``visa.session: process``.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from b1500_test_agent.models.station import VisaSettings
from b1500_test_agent.transport.base import BusLocked, TransportClosed, TransportError, TransportTimeout

DEFAULT_LIBRARY = "@ivi"
"""PyVISA backend used when ``VisaSettings.library`` is empty: the installed vendor VISA (Keysight IO or NI)."""

RESOURCE_METHODS = ("write", "read", "read_stb", "clear", "lock_excl", "unlock", "close")
"""What an opened resource must offer (a pyvisa message-based resource, or the visa-loop test resource)."""

RmFactory = Callable[[str], Any]
"""Builds the resource manager for a VISA library string (default: PyVISA's resource manager class)."""

INSTRUMENT_QUERY = "?*::INSTR"
"""``list_resources`` pattern: every instrument resource the VISA library knows (VPP-4.3 resource expression)."""


@dataclass(frozen=True)
class VisaListing:
    """What ``VisaTransport.list_resources`` found: the library string used, the library file the resource manager
    reports (``None`` when it does not say) and the instrument resources it lists."""

    library: str
    library_path: str | None
    resources: tuple[str, ...]


def _pyvisa() -> tuple[Any, Any]:
    """``(pyvisa, pyvisa.constants)``, imported on first use."""
    try:
        import pyvisa
        from pyvisa import constants
    except ImportError as exc:  # pragma: no cover - pyvisa is a runtime dependency
        raise TransportError(f"pyvisa is not installed: {exc}") from exc
    return pyvisa, constants


def visa_status_codes() -> dict[str, int]:
    """The VISA completion codes this transport interprets (``pyvisa.constants.StatusCode``, VISA VPP-4.3):
    ``timeout`` (VI_ERROR_TMO), ``resource_locked`` (VI_ERROR_RSRC_LOCKED), ``connection_lost``
    (VI_ERROR_CONN_LOST), ``session_not_locked`` (VI_ERROR_SESN_NLOCKED), ``resource_not_found``
    (VI_ERROR_RSRC_NFOUND). The visa-loop test resource raises exactly these codes."""
    _, constants = _pyvisa()
    status = constants.StatusCode
    return {
        "timeout": int(status.error_timeout),
        "resource_locked": int(status.error_resource_locked),
        "connection_lost": int(status.error_connection_lost),
        "session_not_locked": int(status.error_session_not_locked),
        "resource_not_found": int(status.error_resource_not_found),
    }


class VisaTransport:
    """Message-based VISA session to one resource (``GPIB0::17::INSTR`` by default), opened per transaction."""

    backend: Literal["visa"] = "visa"

    def __init__(self, cfg: VisaSettings, *, rm_factory: RmFactory | None = None) -> None:
        self.cfg = cfg
        self.resource = cfg.resource
        self.library = cfg.library or DEFAULT_LIBRARY
        self._rm_factory = rm_factory
        self._rm: Any = None
        self._inst: Any = None
        self._codes: dict[str, int] = {}
        self.locked = False
        """True while this session holds the exclusive VISA lock."""

    @property
    def is_open(self) -> bool:
        """True while the VISA session is open."""
        return self._inst is not None

    # -- helpers ------------------------------------------------------------------------------------------------------

    def _require_open(self) -> Any:
        if self._inst is None:
            raise TransportClosed(f"VISA session to {self.resource} is not open.")
        return self._inst

    def _translate(self, exc: BaseException, action: str) -> TransportError:
        code = getattr(exc, "error_code", None)
        if code is not None and code == self._codes.get("timeout"):
            return TransportTimeout(f"{action} on {self.resource} timed out: {exc}")
        if code is not None and code == self._codes.get("resource_locked"):
            return BusLocked(f"{action} on {self.resource} refused: another VISA client (EasyEXPERT or a second "
                             f"program) holds the instrument's lock: {exc}")
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
        """Open the VISA session without a lock (``lock()`` takes it); idempotent."""
        if self._inst is not None:
            return
        pyvisa, constants = _pyvisa()
        self._codes = visa_status_codes()
        factory: RmFactory = self._rm_factory or pyvisa.ResourceManager
        try:
            rm = factory(self.library)
        except Exception as exc:
            raise TransportError(f"Cannot load VISA library {self.library!r}: {type(exc).__name__}: {exc}") from exc
        try:
            inst = rm.open_resource(self.resource, access_mode=constants.AccessModes.no_lock)
            missing = [name for name in RESOURCE_METHODS if not hasattr(inst, name)]
            if missing:
                raise TypeError(f"{self.resource} is not a message-based instrument resource (no {missing})")
            inst.write_termination = self.cfg.write_termination
            inst.read_termination = self.cfg.read_termination
            inst.timeout = self.cfg.timeout_ms
            inst.encoding = "latin-1"
        except Exception as exc:
            with contextlib.suppress(Exception):  # best-effort cleanup of a failed open
                rm.close()
            raise self._translate(exc, "open") from exc
        self._rm, self._inst = rm, inst
        self.locked = False

    def list_resources(self, query: str = INSTRUMENT_QUERY) -> VisaListing:
        """Load the VISA library and list its instrument resources without opening any (``b1500 doctor --probe``,
        blueprint v2 7.1). The resource manager is closed again before returning.

        Raises:
            TransportError: If the library cannot be loaded or listing fails.
        """
        pyvisa, _ = _pyvisa()
        self._codes = self._codes or visa_status_codes()
        factory: RmFactory = self._rm_factory or pyvisa.ResourceManager
        try:
            rm = factory(self.library)
        except Exception as exc:
            raise TransportError(f"Cannot load VISA library {self.library!r}: {type(exc).__name__}: {exc}") from exc
        try:
            found = tuple(str(name) for name in rm.list_resources(query))
        except Exception as exc:
            code = getattr(exc, "error_code", None)
            if code is not None and code == self._codes.get("resource_not_found"):
                found = ()  # VISA reports "no resource found" as an error; pyvisa itself returns ()
            else:
                raise TransportError(f"Listing VISA resources with {self.library!r} failed: "
                                     f"{type(exc).__name__}: {exc}") from exc
        finally:
            with contextlib.suppress(Exception):  # closing must never raise
                rm.close()
        path = getattr(getattr(rm, "visalib", None), "library_path", None)
        return VisaListing(library=self.library, library_path=None if path is None else str(path), resources=found)

    def close(self) -> None:
        """Unlock (if locked) and close the session and its resource manager; never raises."""
        inst, rm = self._inst, self._rm
        locked = self.locked
        self._inst = self._rm = None
        self.locked = False
        if inst is not None and locked:
            with contextlib.suppress(Exception):  # closing the session releases its lock anyway
                inst.unlock()
        for item in (inst, rm):
            if item is None:
                continue
            with contextlib.suppress(Exception):  # closing must never raise
                item.close()

    def lock(self) -> None:
        """``lock_excl`` (only with ``exclusive_lock``), waiting up to ``lock_timeout_ms``; ``BusLocked`` when another
        client keeps the lock. Idempotent while locked."""
        inst = self._require_open()
        if not self.cfg.exclusive_lock or self.locked:
            return
        try:
            inst.lock_excl(timeout=self.cfg.lock_timeout_ms)
        except Exception as exc:
            code = getattr(exc, "error_code", None)
            if code is not None and code in (self._codes.get("timeout"), self._codes.get("resource_locked")):
                raise BusLocked(f"{self.resource}: the exclusive VISA lock was not obtained within "
                                f"{self.cfg.lock_timeout_ms} ms; another client (EasyEXPERT or a second program) "
                                f"holds the instrument; nothing was sent") from exc
            raise self._translate(exc, "lock") from exc
        self.locked = True

    def unlock(self) -> None:
        """Release the exclusive lock (no-op when not locked)."""
        inst = self._inst
        if inst is None or not self.locked:
            return
        self.locked = False
        try:
            inst.unlock()
        except Exception as exc:
            raise self._translate(exc, "unlock") from exc

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

    def write_block(self, cmd: str, data: bytes) -> None:
        """``cmd`` with the write termination, then ``data`` as raw bytes (``write_raw``; PG PDF 360-361 ``ALS``,
        361-362 ``ALW``: "send the data just after the command"). TODO(verify)[L7.A4] (blueprint 7.6 items 3, 9)
        that the B1500 takes the block as the message after the terminated header; fallback: one ``write_raw`` of
        header + LF + block."""
        inst = self._require_open()
        writer = getattr(inst, "write_raw", None)
        if not callable(writer):
            raise TransportError(f"write_block {cmd!r}: the VISA resource {self.resource} has no write_raw")
        self._io(f"write {cmd!r}", inst.write, cmd)
        self._io(f"write block of {len(data)} bytes after {cmd!r}", writer, bytes(data))

    def wait(self, seconds: float) -> None:
        """Host wait between polls (``HostClock``): a sleep; a resource manager that simulates the instrument (the
        visa-loop tests' ``rm_factory``) may provide ``host_wait(seconds)`` to let its virtual time pass instead."""
        waiter = getattr(self._rm, "host_wait", None)
        if callable(waiter):
            waiter(seconds)
        else:
            time.sleep(seconds)
