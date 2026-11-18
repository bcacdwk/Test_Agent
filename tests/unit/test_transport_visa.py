"""``VisaTransport`` conformance against pyvisa-sim (blueprint 2.2; ATV-2 terminations; v2 2.4 lifecycle).

This module never imports ``pyvisa`` itself (the import lint scans tests too): the simulated VISA library is
selected through ``VisaSettings.library = "<yaml>@sim"``. pyvisa-sim does not implement serial poll, device clear
or locking, so those calls surface as ``TransportError`` here; on the vendor ``@ivi`` stack they are real. The full
behaviour (locking across processes, timeouts, device clear, chunked reads, every recipe) runs against the
simulator in ``tests/visa_loop/``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from b1500_test_agent.models.station import VisaSettings
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import Transport, TransportClosed, TransportError, TransportTimeout
from b1500_test_agent.transport.visa import DEFAULT_LIBRARY, VisaTransport
from tests.unit.helpers import REPO_ROOT

SIM_YAML = REPO_ROOT / "tests" / "fixtures" / "pyvisa_sim" / "b1500.yaml"
IDN = "Keysight Technologies,B1500A,0,A.06.01.2024.0101"


def settings(**overrides: object) -> VisaSettings:
    return VisaSettings(**{"resource": "GPIB0::17::INSTR", "library": f"{SIM_YAML}@sim", "timeout_ms": 200,
                           **overrides})


@pytest.fixture
def visa() -> VisaTransport:
    transport = VisaTransport(settings())
    transport.open()
    yield transport
    transport.close()


def test_defaults_select_the_vendor_ivi_stack_without_loading_pyvisa() -> None:
    transport = VisaTransport(VisaSettings())
    assert transport.library == DEFAULT_LIBRARY == "@ivi"
    assert transport.backend == "visa" and transport.resource == "GPIB0::17::INSTR"
    assert isinstance(transport, Transport)


def test_importing_the_transport_layer_does_not_import_pyvisa() -> None:
    code = ("import sys; import b1500_test_agent.transport.visa, b1500_test_agent.transport.factory, "
            "b1500_test_agent.transport.sim, b1500_test_agent.transport.audit; "
            "sys.exit(1 if 'pyvisa' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_query_strips_the_carriage_return(visa: VisaTransport) -> None:
    """Write ``\\n``, read up to ``\\n``, strip the ``\\r`` of CR/LF (ATV-2)."""
    assert visa.query("*IDN?") == IDN
    assert visa.query("UNT?").count(";") == 9


def test_write_then_read(visa: VisaTransport) -> None:
    visa.write("CN 1")
    visa.write("*OPC?")
    assert visa.read() == "1"
    visa.write("ERRX?")
    assert visa.read(timeout_s=1.0) == '0,"No Error."'


def test_read_with_nothing_pending_times_out(visa: VisaTransport) -> None:
    with pytest.raises(TransportTimeout):
        visa.read(timeout_s=0.05)
    assert visa._inst.timeout == 200  # the per-call timeout was restored
    assert visa.query("*OPC?") == "1"  # the session is still usable


def test_open_is_idempotent_and_close_is_final(visa: VisaTransport) -> None:
    visa.open()
    visa.close()
    visa.close()
    for action in (lambda: visa.write("CN 1"), visa.read, visa.serial_poll, visa.device_clear,
                   lambda: visa.query("*IDN?")):
        with pytest.raises(TransportClosed):
            action()


def test_backend_limitations_surface_as_transport_errors(visa: VisaTransport) -> None:
    with pytest.raises(TransportError, match="not supported"):
        visa.serial_poll()
    with pytest.raises(TransportError, match="not supported"):
        visa.device_clear()


@pytest.mark.parametrize("exclusive_lock", [True, False])
def test_open_never_locks_and_lock_follows_the_exclusive_lock_option(exclusive_lock: bool) -> None:
    """Blueprint v2 2.4: open (no lock) -> lock_excl only with ``exclusive_lock``; pyvisa-sim has no locking, so a
    lock request is an unsupported operation there (and leaves the session usable), while ``exclusive_lock: false``
    never asks for one."""
    transport = VisaTransport(settings(exclusive_lock=exclusive_lock))
    transport.open()
    assert not transport.locked and transport.query("*OPC?") == "1"
    if exclusive_lock:
        with pytest.raises(TransportError, match="not supported"):
            transport.lock()
        assert not transport.locked
    else:
        transport.lock()
        assert not transport.locked
    transport.unlock()  # nothing held: nothing to release
    assert transport.query("*OPC?") == "1"
    transport.close()
    assert not transport.is_open


def test_open_failures_are_transport_errors() -> None:
    with pytest.raises(TransportError, match="message-based"):
        VisaTransport(settings(resource="FOO::BAR")).open()
    with pytest.raises(TransportError):
        VisaTransport(settings(library=f"{SIM_YAML.with_name('missing.yaml')}@sim")).open()


def test_auditing_wrapper_records_visa_io() -> None:
    sink = MemoryAuditSink()
    transport = AuditingTransport(VisaTransport(settings()), sink)
    transport.open()
    assert transport.query("*IDN?") == IDN
    with pytest.raises(TransportTimeout):
        transport.read(timeout_s=0.05)
    transport.close()
    assert [(e.ev, e.backend, e.error is None) for e in sink.events] == [
        ("bus_open", "visa", True), ("query", "visa", True), ("read", "visa", False), ("bus_close", "visa", True)]
    assert sink.events[1].resp == IDN
