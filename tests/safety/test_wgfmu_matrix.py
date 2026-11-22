"""WGFMU fault matrix with the global invariant v2, WGFMU part (blueprint v2 2.6, 4.3, 8.1 ``safety/``; WP10.3).

The body (``wgfmu_helpers.body``) biases SMU3 over FLEX, then runs a two-channel waveform program in the transaction's
WGFMU phase (load, run with status polls, chunked readback) on the lab mainframe; both links are spied. Faults
{``wgfmu_error``, ``wgfmu_hang``, ``wgfmu_disconnect_fails`` (always / once), ``wgfmu_dll_missing``, Ctrl-C, a buggy
level outside the envelope} x positions {session open, load, run (sequencer running), readback, phase cleanup}. Every
case asserts the invariant (``assert_wgfmu_invariant``): no level outside the envelope reached the library or FLEX,
the library ran only with the FLEX exclusive lock released, and afterwards every WGFMU channel is disconnected and
idle, the library session closed and the FLEX link locked again (cleanup DZ/CL under the lock), or the fault latch
is set with ``cleanup_unverified``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.driver.wgfmu import WgfmuDriver, WgfmuSafeStateFailed
from b1500_test_agent.models.sim import SimFault, WgfmuDisconnectFails, WgfmuDllMissing, WgfmuErrorFault, WgfmuHang
from b1500_test_agent.session import Transaction
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import WgfmuError
from tests.safety.wgfmu_helpers import TOP, WgHarness, assert_wgfmu_invariant, body, make_wg_harness

pytestmark = pytest.mark.wgfmu

MOMENTS = {"open": "before:open_session", "load": "before:create_pattern", "run": "after:execute",
           "readback": "before:measure_value_size", "cleanup": "before:abort"}
"""Position -> spy moment: entering the phase, loading, the sequencer just started, before the data are read, the
first call of the phase exit's step 3 (the channels are still connected then)."""
POSITIONS = tuple(MOMENTS)


@dataclass(frozen=True)
class Case:
    inject: Callable[[WgHarness], None]
    raises: type[BaseException] | None = None
    latched: bool = False


def sim(fault: SimFault) -> Callable[[WgHarness], None]:
    return lambda h: h.sim.inject(fault)


def interrupt(_h: WgHarness) -> None:
    raise KeyboardInterrupt


def too_high(h: WgHarness) -> None:
    """A buggy body asks the WGFMU for 5 V on a 3 V channel: the guard refuses before the library."""
    assert h.tx is not None
    link = h.tx.wgfmu_link
    wg = link.driver if link.driver is not None else WgfmuDriver(h.session.bus.wgfmu, h.tx.driver.guard)  # type: ignore[arg-type]
    wg.force_dc(TOP, 5.0)


E, SSF, KI, EV = WgfmuError, WgfmuSafeStateFailed, KeyboardInterrupt, EnvelopeViolation
STUCK, STUCK_ONCE = WgfmuDisconnectFails(), WgfmuDisconnectFails(count=1)

INJECTIONS: dict[tuple[str, str], Case] = {
    # the library refuses one call: the phase exit's step 3 confirms the safe state (or the cleanup's does)
    ("wgfmu_error", "open"): Case(sim(WgfmuErrorFault(fn="open_session", code=api.COMMUNICATION_ERROR)), E),
    ("wgfmu_error", "load"): Case(sim(WgfmuErrorFault(fn="add_vectors", code=api.PARAMETER_OUT_OF_RANGE)), E),
    ("wgfmu_error", "run"): Case(sim(WgfmuErrorFault(fn="status", code=3050)), E),
    ("wgfmu_error", "readback"): Case(sim(WgfmuErrorFault(fn="measure_values", code=3015)), E),
    ("wgfmu_error", "cleanup"): Case(sim(WgfmuErrorFault(fn="disconnect", code=3001)), SSF),
    # a call hangs for the session timeout (execute: the sequencer never completes until abort/initialize)
    ("wgfmu_hang", "open"): Case(sim(WgfmuHang(fn="initialize")), E),
    ("wgfmu_hang", "load"): Case(sim(WgfmuHang(fn="execute")), E),
    ("wgfmu_hang", "run"): Case(sim(WgfmuHang(fn="status")), E),
    ("wgfmu_hang", "readback"): Case(sim(WgfmuHang(fn="measure_value_size")), E),
    ("wgfmu_hang", "cleanup"): Case(sim(WgfmuHang(fn="abort")), SSF),
    # a stuck RSU relay: the safe state cannot be reached -> latched
    ("wgfmu_disconnect_fails", "open"): Case(sim(STUCK), SSF, latched=True),
    ("wgfmu_disconnect_fails", "load"): Case(sim(STUCK), SSF, latched=True),
    ("wgfmu_disconnect_fails", "run"): Case(sim(STUCK), SSF, latched=True),
    ("wgfmu_disconnect_fails", "readback"): Case(sim(STUCK), SSF, latched=True),
    ("wgfmu_disconnect_fails", "cleanup"): Case(sim(STUCK), SSF, latched=True),
    # the relay opens on the cleanup's retry: verified
    ("wgfmu_disconnect_fails_once", "open"): Case(sim(STUCK_ONCE), SSF),
    ("wgfmu_disconnect_fails_once", "load"): Case(sim(STUCK_ONCE), SSF),
    ("wgfmu_disconnect_fails_once", "run"): Case(sim(STUCK_ONCE), SSF),
    ("wgfmu_disconnect_fails_once", "readback"): Case(sim(STUCK_ONCE), SSF),
    ("wgfmu_disconnect_fails_once", "cleanup"): Case(sim(STUCK_ONCE), SSF),
    # the library cannot be loaded any more: only a new session fails
    ("wgfmu_dll_missing", "open"): Case(sim(WgfmuDllMissing()), E),
    ("wgfmu_dll_missing", "load"): Case(sim(WgfmuDllMissing())),
    ("wgfmu_dll_missing", "run"): Case(sim(WgfmuDllMissing())),
    ("wgfmu_dll_missing", "readback"): Case(sim(WgfmuDllMissing())),
    ("wgfmu_dll_missing", "cleanup"): Case(sim(WgfmuDllMissing())),
    # Ctrl-C: the phase exit completes step 3 first (an interrupt inside step 3 is handed back after it)
    ("keyboard_interrupt", "open"): Case(interrupt, KI),
    ("keyboard_interrupt", "load"): Case(interrupt, KI),
    ("keyboard_interrupt", "run"): Case(interrupt, KI),
    ("keyboard_interrupt", "readback"): Case(interrupt, KI),
    ("keyboard_interrupt", "cleanup"): Case(interrupt, KI),
    # a buggy level outside the envelope: refused before the library (inside step 3 it fails that step)
    ("envelope_violation", "open"): Case(too_high, EV),
    ("envelope_violation", "load"): Case(too_high, EV),
    ("envelope_violation", "run"): Case(too_high, EV),
    ("envelope_violation", "readback"): Case(too_high, EV),
    ("envelope_violation", "cleanup"): Case(too_high, SSF),
}
FAULTS = sorted({fault for fault, _ in INJECTIONS})


def test_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}
    assert {"wgfmu_error", "wgfmu_hang", "wgfmu_disconnect_fails", "wgfmu_dll_missing"} <= set(FAULTS)


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_wgfmu_fault_matrix(fault: str, position: str, tmp_path: Path) -> None:
    case = INJECTIONS[(fault, position)]
    h = make_wg_harness(tmp_path)
    h.spy.actions[MOMENTS[position]] = lambda: case.inject(h)
    raised: BaseException | None = None
    tx: Transaction | None = None
    try:
        with h.transaction() as tx:
            h.tx = tx
            body(tx, h)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    assert tx is not None and tx.cleanup is not None
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_wgfmu_invariant(h, tx)
    if not case.latched:
        assert tx.cleanup.verified == "sim_state" and not tx.wgfmu_link.pending
    if case.raises is EV:
        assert "dc_force_voltage" not in h.spy.names()  # refused before the library


def test_a_clean_run_confirms_the_safe_state_at_the_phase_exit() -> None:
    import tempfile

    h = make_wg_harness(Path(tempfile.mkdtemp()))
    with h.transaction() as tx:
        block = body(tx, h)
    assert block is not None and block.status == "completed"
    assert_wgfmu_invariant(h, tx)
    assert tx.cleanup is not None and [s.step for s in tx.cleanup.steps] == [
        "spgu_stop", "zero", "routes", "disconnect", "drain_errors", "verify"]
