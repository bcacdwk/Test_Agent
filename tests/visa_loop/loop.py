"""visa-loop: a fake VISA layer whose instrument sessions forward to ``SimInstrument`` (blueprint v2 7.1, 8.1).

The REAL ``VisaTransport`` runs on top of it: ``make_bus(settings, sink, rm_factory=bus.manager)`` hands the transport
a ``LoopManager`` in place of PyVISA's resource manager, and ``open_resource`` returns a ``LoopResource`` with the
attributes and methods of a pyvisa message-based resource that the transport uses (``write_termination``,
``read_termination``, ``timeout`` in ms, ``encoding``, ``chunk_size``; ``write``, ``read``, ``read_stb``, ``clear``,
``lock_excl``, ``unlock``, ``close``). Errors are ``LoopVisaError`` with the VISA completion code in ``error_code``
(the codes come from ``transport.visa.visa_status_codes()``, so they are pyvisa's own); nothing here imports pyvisa
(import lint) and nothing opens a real VISA resource.

What the wire does here:

- terminations: ``write`` appends the write termination and the instrument takes the line up to LF; answers go on
  the wire exactly as the simulator frames them (query answers and FMT 1 data end in CR/LF, FMT 5 data in a comma +
  EOI); ``read`` stops at the last character of the read termination or at the end of the message (EOI) and strips
  the read termination, so with ``\\n`` the transport still sees (and strips) the ``\\r`` of CR/LF (ATV-2);
- chunked reads: one VISA read returns at most ``chunk_size`` bytes and ``read`` loops like pyvisa does
  (``LoopStats.chunks``/``max_chunks``);
- timeouts: the resource ``timeout`` (ms) is the simulator's virtual wait; an answer not ready in time is
  VI_ERROR_TMO (``TransportTimeout`` in the transport, which the transaction's cleanup answers with a device clear);
  ``DZ``/``CL`` writes under the ``cleanup_failure`` fault time out; ``timeout`` on ``read`` as in ``SimTransport``;
- device clear: ``clear`` initialises the instrument (simulator) and discards a partly read message;
- exclusive lock: ``lock_excl(timeout)`` takes the cross-process file lock ``<dir>/<resource>.visa-lock`` (other
  ``LoopBus`` objects, other processes and ``LoopBus.foreign_lock()`` contend for it); not obtained in time ->
  VI_ERROR_TMO; I/O from a session without the lock while another session holds it -> VI_ERROR_RSRC_LOCKED; the
  simulated ``bus_locked`` fault refuses ``lock_excl`` requests the same way (one request per ``lock_excl``);
- link faults: ``disconnect`` -> VI_ERROR_CONN_LOST for every later call (dropped writes logged);
- binary blocks: ``write_raw(data)`` hands the bytes to the instrument as the data block of the ``ALW``/``ALS`` header
  written before it (WP9.1);
- host waits: ``LoopManager.host_wait(seconds)`` lets the simulator's virtual time pass (``VisaTransport.wait`` uses it
  instead of sleeping, so polling an SPGU output runs at simulation speed);
- shared instrument: the persistent state lives in ``<dir>/<resource>.state.json``; a session loads it when it opens
  or locks (if another process saved since) and saves it when it unlocks or closes (if this process changed it), so
  several processes share one instrument as they share the real one;
- ``signed_errx`` (default on): ``ERRX?`` answers carry a ``+`` sign (``+0,"No Error."``), as the lab's firmware
  does according to the lab code (``lwp/matlab_B1500/lib/*.m`` tests ``startsWith(response, '+0,')``); the simulator
  itself answers the Programming Guide form ``0,"No Error."`` (PG PDF 432);
- ``lop_reads_off`` (default off, test switch): every ``LOP?`` answer reports all slots ``00`` whatever the output
  switches do, i.e. an instrument whose ``LOP?`` cannot verify the cleanup (the v1 ATV-1 failure that the
  transaction's ``LOP?`` positive control must catch).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import filelock

from b1500_test_agent.models.sim import SimFault
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.session.lock import resource_slug
from b1500_test_agent.transport.base import TransportTimeout
from b1500_test_agent.transport.sim import SimInstrument
from b1500_test_agent.transport.sim import flex as simflex
from b1500_test_agent.transport.sim.instrument import SimulatedInterrupt
from b1500_test_agent.transport.sim.state import load_state_file, save_state_file
from b1500_test_agent.transport.visa import visa_status_codes

DEFAULT_RESOURCE = "GPIB0::17::INSTR"
DEFAULT_CHUNK_SIZE = 20 * 1024
"""pyvisa's default ``chunk_size`` (bytes per VISA read)."""

ENV_DIR = "B1500_VISA_LOOP_DIR"
ENV_SCENARIO = "B1500_VISA_LOOP_SCENARIO"
ENV_CHUNK = "B1500_VISA_LOOP_CHUNK"
"""Environment of the child processes of the two-process tests (``serve.py``); test-only names."""

_ERRX_ANSWER = re.compile(r'^\d+,"')
_LOP_ANSWER = re.compile(r"^LOP ?\d\d(,\d\d){9}\r?\n?$")
LOP_ALL_OFF = "LOP" + ",".join(["00"] * 10)


@cache
def codes() -> dict[str, int]:
    """The VISA completion codes (pyvisa's, through ``visa_status_codes``)."""
    return visa_status_codes()


class LoopVisaError(Exception):
    """Stand-in for pyvisa's ``VisaIOError``: ``error_code`` is the VISA completion code named ``name``."""

    def __init__(self, name: str, detail: str) -> None:
        super().__init__(f"{name}: {detail}")
        self.name = name
        self.error_code = codes()[name]


@dataclass
class LoopStats:
    """What the sessions of one ``LoopBus`` did (assertions and the ATV-13 measurement)."""

    opens: int = 0
    closes: int = 0
    locks: int = 0
    unlocks: int = 0
    lock_refusals: int = 0
    reads: int = 0
    chunks: int = 0
    max_chunks: int = 0
    clears: int = 0
    loads: int = 0
    saves: int = 0
    signed_errx: int = 0
    library: str | None = None


def _mnemonic(part: str) -> str:
    try:
        return simflex.parse_command(part).mnemonic
    except simflex.FlexError:
        return ""


class LoopBus:
    """One simulated GPIB bus with a B1500A at ``resource``, shared through ``directory`` by every ``LoopBus`` (in
    any process) built on the same directory. ``manager`` is the ``rm_factory`` of ``make_bus``/``VisaTransport``."""

    def __init__(self, directory: Path, scenario: SimScenario, *, faults: Iterable[SimFault] = (),
                 resource: str = DEFAULT_RESOURCE, chunk_size: int = DEFAULT_CHUNK_SIZE,
                 signed_errx: bool = True) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.scenario = scenario
        self.resource = resource
        self.chunk_size = chunk_size
        self.signed_errx = signed_errx
        self.lop_reads_off = False
        self.instrument = SimInstrument(scenario, faults=faults)
        slug = resource_slug(resource)
        self.state_file = self.directory / f"{slug}.state.json"
        self.lock_file = self.directory / f"{slug}.visa-lock"
        self.stats = LoopStats()
        self.time_scale = scenario.time_scale
        self.sessions: list[LoopResource] = []
        self._stamp: tuple[int, int, int] | None = None
        self._dirty = False

    # -- construction from the environment (child processes) ----------------------------------------------------------

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LoopBus:
        """The bus a child process of the two-process tests uses (``ENV_DIR``, ``ENV_SCENARIO``, ``ENV_CHUNK``)."""
        from tests.sim.helpers import load_scenario

        env = os.environ if environ is None else environ
        chunk = int(env.get(ENV_CHUNK) or DEFAULT_CHUNK_SIZE)
        return cls(Path(env[ENV_DIR]), load_scenario(env[ENV_SCENARIO]), chunk_size=chunk)

    def env(self) -> dict[str, str]:
        """The environment entries that make ``from_env`` rebuild this bus in another process."""
        return {ENV_DIR: str(self.directory), ENV_SCENARIO: self.scenario.name, ENV_CHUNK: str(self.chunk_size)}

    # -- the resource-manager factory ----------------------------------------------------------------------------------

    def manager(self, library: str) -> LoopManager:
        """``rm_factory`` for ``VisaTransport``: called with the configured VISA library string."""
        self.stats.library = library
        return LoopManager(self)

    def inject(self, fault: SimFault) -> None:
        self.instrument.inject(fault)

    def clear_faults(self) -> None:
        self.instrument.clear_faults()

    # -- shared instrument state ------------------------------------------------------------------------------------

    def _file_stamp(self) -> tuple[int, int, int] | None:
        try:
            st = self.state_file.stat()
        except FileNotFoundError:
            return None
        return st.st_ino, st.st_mtime_ns, st.st_size

    def sync_in(self) -> None:
        """Load the shared state when another bus object (another process) saved it since this one last did."""
        stamp = self._file_stamp()
        if stamp is None or stamp == self._stamp:
            return
        state = load_state_file(self.state_file)
        if state is not None:
            self.instrument.import_state(state)
            self.stats.loads += 1
        self._stamp, self._dirty = stamp, False

    def sync_out(self) -> None:
        """Save the state when a session of this bus changed it."""
        if not self._dirty:
            return
        save_state_file(self.state_file, self.instrument.export_state())
        self._stamp, self._dirty = self._file_stamp(), False
        self.stats.saves += 1

    def touch(self) -> None:
        self._dirty = True

    def wait(self, start_clock: float) -> None:
        """Sleep the scaled virtual time since ``start_clock`` (``timing: scaled`` scenarios only)."""
        if self.time_scale > 0:
            time.sleep(max(0.0, self.instrument.clock - start_clock) * self.time_scale)

    # -- the exclusive VISA lock ---------------------------------------------------------------------------------------

    def visa_lock(self) -> filelock.BaseFileLock:
        """A fresh lock object on the bus lock file: its own file handle, so it contends like another VISA session
        (also inside one process); not bound to a thread (a VISA lock belongs to its session)."""
        return filelock.FileLock(self.lock_file, thread_local=False)

    def lock_is_free(self) -> bool:
        """True when no session (of any process) holds the exclusive VISA lock."""
        probe = self.visa_lock()
        try:
            probe.acquire(timeout=0)
        except filelock.Timeout:
            return False
        probe.release()
        return True

    @contextmanager
    def foreign_lock(self, timeout_s: float = 5.0) -> Iterator[None]:
        """Hold the exclusive VISA lock as another client would (EasyEXPERT, a second program) for the block."""
        lock = self.visa_lock()
        lock.acquire(timeout=timeout_s)
        try:
            yield
        finally:
            lock.release()

    def quirks(self, message: str) -> str:
        """The answer as the lab firmware sends it (``signed_errx``: ``+`` before an ``ERRX?`` code; ``lop_reads_off``:
        an all-``00`` ``LOP?`` answer)."""
        if self.signed_errx and _ERRX_ANSWER.match(message):
            self.stats.signed_errx += 1
            return "+" + message
        if self.lop_reads_off and _LOP_ANSWER.match(message):
            return LOP_ALL_OFF + message[len(message.rstrip("\r\n")):]
        return message


class LoopManager:
    """Stands in for PyVISA's resource manager (the parts ``VisaTransport`` and the bring-up probe use)."""

    def __init__(self, bus: LoopBus) -> None:
        self.bus = bus
        self.closed = False

    def list_resources(self, query: str = "?*::INSTR") -> tuple[str, ...]:
        return (self.bus.resource,)

    def open_resource(self, resource_name: str, access_mode: Any = 0, open_timeout: Any = 0,
                      **_: Any) -> LoopResource:
        """A new VISA session; ``access_mode`` 1 (exclusive lock) locks at open, waiting ``open_timeout`` ms."""
        if self.closed:
            raise LoopVisaError("connection_lost", "the resource manager is closed")
        if resource_name != self.bus.resource:
            raise LoopVisaError("resource_not_found", f"no instrument at {resource_name}")
        session = LoopResource(self.bus, resource_name)
        self.bus.sessions.append(session)
        self.bus.stats.opens += 1
        self.bus.sync_in()
        if int(access_mode) == 1:
            session.lock_excl(timeout=float(open_timeout or 0))
        return session

    def close(self) -> None:
        self.closed = True

    def host_wait(self, seconds: float) -> None:
        """The host waits ``seconds`` (``VisaTransport.wait``): virtual time passes on the bus's instrument."""
        instrument = self.bus.instrument
        start = instrument.clock
        instrument.advance(seconds)
        self.bus.touch()
        self.bus.wait(start)


class LoopResource:
    """One VISA session to the simulated instrument (see the module docstring for the modelled behaviour)."""

    def __init__(self, bus: LoopBus, resource_name: str) -> None:
        self.bus = bus
        self.resource_name = resource_name
        self.write_termination = "\r\n"  # pyvisa defaults; VisaTransport sets its own
        self.read_termination: str | None = None
        self.timeout: float = 2000.0
        self.encoding = "ascii"
        self.chunk_size = bus.chunk_size
        self.closed = False
        self._lock: filelock.BaseFileLock | None = None
        self._pending = bytearray()

    @property
    def holds_lock(self) -> bool:
        return self._lock is not None

    def _enter(self, action: str, line: str | None = None) -> None:
        """Common checks of every bus operation: open session, no foreign lock, link up."""
        if self.closed:
            raise LoopVisaError("connection_lost", f"{action} on a closed session")
        if not self.holds_lock and not self.bus.lock_is_free():
            raise LoopVisaError("resource_locked", f"{action}: the resource is locked by another session")
        if self.bus.instrument.faults.link_down():
            if line is not None:
                self.bus.instrument.record_dropped(line)
            raise LoopVisaError("connection_lost", f"{action}: link lost (simulated disconnect)")
        self.bus.touch()

    # -- message-based I/O ------------------------------------------------------------------------------------------

    def write(self, message: str) -> int:
        wire = (message + self.write_termination).encode(self.encoding)
        line = wire.decode(self.encoding)
        line = line.removesuffix("\n")  # the B1500 takes the line up to LF (or EOI)
        self._enter(f"write {message!r}", line)
        faults = self.bus.instrument.faults
        zeroing = any(_mnemonic(part) in simflex.ZEROING_COMMANDS for part in simflex.split_line(line))
        if zeroing and faults.zeroing_times_out():
            self.bus.instrument.record_dropped(line)
            raise LoopVisaError("timeout", f"write {message!r} timed out (simulated cleanup failure)")
        self.bus.instrument.handle(line)
        faults.count_write()
        return len(wire)

    def write_raw(self, message: bytes) -> int:
        """The data block after an ``ALW``/``ALS`` header (no termination added)."""
        self._enter(f"write_raw of {len(message)} bytes", "<block>")
        self.bus.instrument.receive_block(bytes(message))
        self.bus.instrument.faults.count_write()
        return len(message)

    def read(self) -> str:
        self._enter("read")
        instrument = self.bus.instrument
        timeout_s = float(self.timeout) / 1000.0
        start = instrument.clock
        if not self._pending and instrument.take_interrupt():
            raise SimulatedInterrupt("host interrupted while reading a measurement (simulated run_interrupt)")
        try:
            if not self._pending:
                if instrument.faults.read_times_out():
                    instrument.clock += timeout_s
                    raise LoopVisaError("timeout", "read timed out (simulated)")
                try:
                    message = instrument.read_message(timeout_s)
                except TransportTimeout as exc:
                    raise LoopVisaError("timeout", str(exc)) from None
                self._pending = bytearray(self.bus.quirks(message).encode(self.encoding))
            return self._read_chunks()
        finally:
            self.bus.wait(start)

    def _read_chunks(self) -> str:
        """VISA reads of at most ``chunk_size`` bytes until the termination character or the end of the message."""
        term = self.read_termination[-1].encode(self.encoding) if self.read_termination else None
        out = bytearray()
        chunks = 0
        while True:
            chunk = bytes(self._pending[: self.chunk_size])
            if term is not None and term in chunk:
                chunk = chunk[: chunk.index(term) + 1]
            del self._pending[: len(chunk)]
            out += chunk
            chunks += 1
            if (term is not None and chunk.endswith(term)) or not self._pending:
                break
        stats = self.bus.stats
        stats.reads += 1
        stats.chunks += chunks
        stats.max_chunks = max(stats.max_chunks, chunks)
        text = out.decode(self.encoding)
        if self.read_termination and text.endswith(self.read_termination):
            text = text[: -len(self.read_termination)]
        return text

    def read_stb(self) -> int:
        self._enter("serial poll")
        start = self.bus.instrument.clock
        value = self.bus.instrument.serial_poll()
        self.bus.wait(start)
        return value

    def clear(self) -> None:
        self._enter("device clear")
        self.bus.instrument.device_clear()
        self._pending.clear()
        self.bus.stats.clears += 1

    # -- locking and closing ----------------------------------------------------------------------------------------

    def lock_excl(self, timeout: float | str = "default") -> None:
        if self.closed:
            raise LoopVisaError("connection_lost", "lock on a closed session")
        if self._lock is not None:
            return
        if self.bus.instrument.faults.lock_refused():
            self.bus.stats.lock_refusals += 1
            raise LoopVisaError("timeout", "exclusive lock not obtained: another client holds it (simulated "
                                           "bus_locked fault)")
        wait_ms = float(self.timeout) if timeout == "default" else float(timeout)
        lock = self.bus.visa_lock()
        try:
            lock.acquire(timeout=max(0.0, wait_ms / 1000.0))
        except filelock.Timeout:
            self.bus.stats.lock_refusals += 1
            raise LoopVisaError("timeout", f"exclusive lock not obtained within {wait_ms:g} ms") from None
        self._lock = lock
        self.bus.stats.locks += 1
        self.bus.sync_in()

    def unlock(self) -> None:
        if self._lock is None:
            raise LoopVisaError("session_not_locked", "unlock without a lock")
        self.bus.sync_out()
        lock, self._lock = self._lock, None
        lock.release()
        self.bus.stats.unlocks += 1

    def close(self) -> None:
        if self.closed:
            return
        self.bus.sync_out()
        if self._lock is not None:  # closing a VISA session releases its lock
            lock, self._lock = self._lock, None
            lock.release()
        self.closed = True
        self._pending.clear()
        self.bus.stats.closes += 1
