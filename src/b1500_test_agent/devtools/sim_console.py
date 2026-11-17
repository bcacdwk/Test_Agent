"""``b1500 dev sim-console``: a raw FLEX console for the SIMULATOR only (developer tool, blueprint 5.3, 9.0 point 3).

It refuses any backend other than ``sim`` before a transport is created, and checks the transport's backend again
before the first command. The console runs inside one instrument transaction without an envelope: the instrument
lock is held, the simulator state is loaded and saved, every line is audited (intent ``sim-console``) to the daily
audit file, and leaving the console runs the normal cleanup (abort, zero, disconnect, verify). It is never exposed
as an MCP tool and there is no hardware equivalent.

Input: one FLEX line per prompt; a line containing ``?`` is sent as a query and its answer printed, any other line
is written. Console commands start with ``:``: ``:read`` (read one response, e.g. after a measurement),
``:poll`` (serial poll), ``:help``, ``:quit`` (or end of input).
"""

from __future__ import annotations

from collections.abc import Callable

from b1500_test_agent.errors import B1500Error
from b1500_test_agent.service import B1500Service

HELP = ("raw FLEX console (simulator only). A line with '?' is a query, any other line is written. "
        ":read reads one response, :poll reads the status byte, :quit leaves (cleanup: abort, zero, disconnect, "
        "verify).")
PROMPT = "flex> "


class SimConsoleRefused(RuntimeError):
    """The console refuses to start (non-sim backend or invalid configuration)."""


def run_console(service: B1500Service, read_line: Callable[[str], str | None], write: Callable[[str], None]) -> int:
    """Run the console until ``:quit`` or end of input; returns the number of lines sent to the simulator.

    Raises ``SimConsoleRefused`` when the configured backend is not ``sim``.
    """
    try:
        bundle = service.config.get()
    except B1500Error as exc:
        raise SimConsoleRefused(f"configuration invalid: {exc}") from exc
    if bundle.backend != "sim":
        raise SimConsoleRefused(f"sim-console works only with the simulator; the configured backend is "
                                f"{bundle.backend} (raw FLEX on hardware is never offered)")
    session = service.executor.session(bundle)
    if session.transport.backend != "sim":  # second, independent check on the actual transport
        raise SimConsoleRefused("the session transport is not the simulator; refusing")
    sent = 0
    write(HELP)
    with session.transaction(intent="sim-console", envelope=None, run=None,
                             lock_timeout_s=service.lock_timeout_s) as tx:
        transport = tx.driver.transport
        while True:
            line = read_line(PROMPT)
            if line is None:
                break
            text = line.strip()
            if not text:
                continue
            if text in (":quit", ":q", ":exit"):
                break
            try:
                if text == ":help":
                    write(HELP)
                elif text == ":read":
                    write(transport.read())
                elif text == ":poll":
                    write(str(transport.serial_poll()))
                elif text.startswith(":"):
                    write(f"unknown console command {text!r} (:help)")
                elif "?" in text:
                    write(transport.query(text))
                    sent += 1
                else:
                    transport.write(text)
                    sent += 1
                    write("ok")
            except B1500Error as exc:
                write(f"error: {type(exc).__name__}: {exc}")
    cleanup = tx.cleanup
    if cleanup is not None:
        write(f"cleanup: {cleanup.verified}" + (" (fault latched)" if cleanup.latched_fault else ""))
    return sent
