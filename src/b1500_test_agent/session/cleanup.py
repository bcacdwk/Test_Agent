"""``run_cleanup``: the cleanup sequence of a transaction, of ``safe_shutdown`` and of the in-flight recovery.

``Transaction.__exit__`` (``session/transaction.py``) runs it for any exit of the body, and ``__enter__`` runs it
first when a stale in-flight marker shows a transaction that never finished; the transaction latches the fault when
the sequence could not verify the safe state (step 7) and then releases (step 8). Steps:
1 ``AB`` if ``XE`` was issued and its read did not complete (sent alone; on timeout device clear, then ``AB``)
1b (v2 step 2, on instruments with an HV-SPGU, WP9.1) ``SPST?`` and ``SPP`` if an SPGU output is active
1c (v2 step 3, WP10.3: after a WGFMU phase whose safe state is unconfirmed; in ``safe_shutdown`` and recovery on a
mainframe with a WGFMU when the library is available) WGFMU ``abort``, ``initialize``, every channel disconnected,
library session closed, FLEX link locked again (``session/wgfmu_phase.py``)
2 ``DZ`` (v2 step 4: first ``DCV ch,0`` and ``ACV ch,0`` on every MFCMU the transaction drove whose ``LOP?`` code
still shows its output switch on, WP8.1) 2b ``routes`` (v2 step 5, WP9.2; on stations that declare switches): every
declared 16440A selector, SCUU and ASU back to its ``rest`` state (``session/routes.py``) 3 ``CL`` 4 ``ERRX?`` drain
5 verify outputs off (``LOP?`` plus ``SPST?`` = 0 with an SPGU on hardware, simulator state on sim, which includes
the MFCMU DC bias and AC level and the SPGU output; on hardware a failed ``LOP?`` positive control makes the
verification fail whatever ``LOP?`` reads) and every declared switch output at rest (``ERSSP?`` per declared port,
``*LRN? 81``/``62``; v2 step 8, ``CleanupReport.switches_after``)
6 on any step error: device clear, retry the sequence once
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.discovery import all_outputs_off
from b1500_test_agent.models.routing import SwitchSpec
from b1500_test_agent.models.run import CleanupReport, CleanupStep, PositiveControl
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL, InstrumentError, ModuleInventory
from b1500_test_agent.session.routes import cleanup_scope, restore_routes, verify_routes
from b1500_test_agent.session.wgfmu_phase import WgfmuLink
from b1500_test_agent.transport.base import TransportTimeout, unwrap

CleanupStepName = Literal["abort", "spgu_stop", "wgfmu", "zero", "routes", "disconnect", "drain_errors", "verify",
                          "device_clear", "restore"]

Emit = Callable[..., None]

_DETAIL_LIMIT = 500


def sim_instrument(transport: object) -> Any | None:
    """The simulated instrument behind ``transport`` (looking through wrappers), or ``None`` on hardware.

    Verification on the simulator reads its state directly (``unsafe_reasons()``/``outputs()``, blueprint 3)."""
    if getattr(transport, "backend", None) != "sim":
        return None
    instrument = getattr(unwrap(transport), "instrument", None)
    if callable(getattr(instrument, "unsafe_reasons", None)) and callable(getattr(instrument, "outputs", None)):
        return instrument
    return None


def _sim_output_text(state: Any) -> str:
    on = "on" if state.output_on else "off"
    if getattr(state, "mode", "V") == "I":
        return f"{on} {state.current:g} A"
    return on if state.voltage == 0 else f"{on} {state.voltage:g} V"


SPGU_MODULE_TYPE = "HVSPGU"
"""Module type whose installation adds cleanup step 2 (``SPP`` when ``SPST?`` reads 1; blueprint v2 2.6)."""


def spgu_installed(inventory: ModuleInventory | None) -> bool | None:
    """Whether ``inventory`` (an ``UNT?`` reading) lists an HV-SPGU; ``None`` when no inventory is known."""
    if inventory is None:
        return None
    return any(MODULE_TYPE_BY_MODEL.get(m.model) == SPGU_MODULE_TYPE for m in inventory.modules)


@dataclass
class CleanupOutcome:
    """A cleanup report plus a ``KeyboardInterrupt``/``SystemExit`` caught while cleaning up (re-raised by the
    caller once everything is released)."""

    report: CleanupReport
    deferred: BaseException | None


def run_cleanup(driver: B1500Driver, *, always_abort: bool, emit: Emit,
                positive: PositiveControl | None = None, spgu: bool | None = None,
                switches: Sequence[SwitchSpec] = (), wgfmu: WgfmuLink | None = None,
                shutdown: bool = False) -> CleanupOutcome:
    """``AB`` (when ``always_abort`` or a measurement is pending) -> SPGU stop -> MFCMU ``DCV 0``/``ACV 0`` (channels
    the driver drove) + ``DZ`` -> switches to rest -> ``CL`` -> ``ERRX?`` drain -> verify; after any failed step a
    device clear and one retry of the whole sequence (blueprint 2.4 steps 1-6, v2 2.6 steps 1, 2, 4-10).

    ``switches``: the station's declared switches; those in ``routes.cleanup_scope`` are returned to rest (step 5,
    ``routes``) and verified (step 8, part of ``verify``; ``CleanupReport.switches_after``).

    ``spgu``: whether an HV-SPGU is installed (``None`` = unknown: ``UNT?`` is read once after the abort step, and an
    unreadable inventory counts as installed). With an SPGU the ``spgu_stop`` step reads ``SPST?`` and sends ``SPP``
    when an output is active (``SPP`` also when ``SPST?`` cannot be read), and the hardware verification also needs
    ``SPST?`` = 0; an SPGU that will not stop (``spgu_no_stop``) is stopped by the retry's ``SPP`` or latches the
    fault.

    ``wgfmu``: the transaction's WGFMU link; step 3 (``wgfmu``) runs when it is ``needed`` (a phase left the safe
    state unconfirmed, or ``shutdown``, i.e. safe shutdown and recovery, on a mainframe with a WGFMU and an available
    library); the verification then also needs the FLEX link relocked and, on hardware, step 3 complete.

    Every step continues after a failure of an earlier one (``CL`` turns outputs off even when ``DZ`` failed) and
    is audited as ``cleanup_step``. The result is verified only when ``DZ``, ``CL`` and the verification all
    succeeded in the last attempt; the caller latches the fault otherwise. ``positive`` is the transaction's
    hardware ``LOP?`` positive control: it is copied into the report, and a failed one fails the verification
    (``LOP?`` reading ``00`` proves nothing then). Never raises: exceptions inside steps, ``BaseException``
    included, are recorded (interrupts are returned as ``deferred``).
    """
    sim = sim_instrument(driver.transport)
    method: Literal["sim_state", "lop"] = "sim_state" if sim is not None else "lop"
    steps: list[CleanupStep] = []
    errors: list[InstrumentError] = []
    outputs: dict[int, str] = {}
    switches_after: dict[str, str] = {}
    deferred: list[BaseException] = []
    scope = cleanup_scope(switches)

    def step(name: CleanupStepName, attempt: int, action: Callable[[], tuple[bool, str]]) -> bool:
        error: str | None = None
        try:
            ok, detail = action()
        except BaseException as exc:  # noqa: BLE001 - cleanup must survive anything; interrupts are deferred
            if not isinstance(exc, Exception):
                deferred.append(exc)
            ok, detail = False, f"{type(exc).__name__}: {exc}"
            error = detail
        record = CleanupStep(step=name, ok=ok, attempt=attempt, detail=detail[:_DETAIL_LIMIT])
        steps.append(record)
        emit("cleanup_step", {"step": name, "ok": ok, "attempt": attempt, "detail": record.detail}, error=error)
        return ok

    def spgu_stop() -> tuple[bool, str]:
        try:
            active = driver.pulse_output_active()
        except Exception as exc:  # noqa: BLE001 - state unknown: stop anyway (SPP is harmless when nothing runs)
            driver.stop_pulses()
            return False, f"{flex.SPST_Q} unreadable ({type(exc).__name__}: {exc}); {flex.SPP} sent anyway"
        if not active:
            return True, f"{flex.SPST_Q} 0: no SPGU output active"
        driver.stop_pulses()
        return True, f"{flex.SPST_Q} 1: {flex.SPP} sent"

    def abort() -> tuple[bool, str]:
        try:
            driver.abort()
        except TransportTimeout as exc:
            driver.device_clear()
            driver.abort()
            return True, f"abort timed out ({exc}); device clear, then abort again"
        return True, "sent alone"

    def zero() -> tuple[bool, str]:
        # v2 step 4 (blueprint 2.6): the MFCMUs this driver drove get DCV 0 and ACV 0 (AC off before the relays
        # open), then DZ zeros every channel. DZ is sent even when the MFCMU zeroing failed; the step then fails.
        cmu_error: Exception | None = None
        zeroed: list[int] = []
        try:
            zeroed = driver.zero_cmu()
        except Exception as exc:  # noqa: BLE001 - recorded after DZ; the retry repeats both
            cmu_error = exc
        driver.zero()
        if cmu_error is not None:
            raise cmu_error
        cmu = f"; MFCMU {', '.join(str(ch) for ch in zeroed)} DC 0 V, AC 0 V" if zeroed else ""
        return True, "all channels" + cmu

    def routes() -> tuple[bool, str]:
        return restore_routes(driver, scope)

    def disconnect() -> tuple[bool, str]:
        driver.disconnect()
        return True, "all channels"

    def drain() -> tuple[bool, str]:
        found = driver.errors(drain=True)
        errors.extend(found)
        for item in found:
            emit("instrument_error", {"code": item.code, "message": item.message, "phase": "cleanup"})
        return True, ", ".join(f"{e.code} {e.message}".strip() for e in found) or "queue empty"

    def verify() -> tuple[bool, str]:
        ok, detail = verify_outputs()
        switches_after.clear()
        if wgfmu is not None:
            switches_after.update(wgfmu.rsu_states())  # what the library accepted (FLEX never reads an RSU)
        if wgfmu is not None and wgfmu_ran:
            w_ok, w_detail = wgfmu.verification(sim=sim is not None)
            ok, detail = ok and w_ok, f"{detail}; {w_detail}"
        if not scope:
            return ok, detail
        routed_ok, routed_detail, after = verify_routes(driver, scope)
        switches_after.update(after)
        return ok and routed_ok, f"{detail}; {routed_detail}"

    def verify_outputs() -> tuple[bool, str]:
        outputs.clear()
        if sim is not None:
            reasons = sim.unsafe_reasons()
            outputs.update({ch: _sim_output_text(state) for ch, state in sorted(sim.outputs().items())})
            return not reasons, "; ".join(reasons) or "simulator state safe"
        states = driver.output_state()
        outputs.update({slot: out.state for slot, out in sorted(states.items())})
        on = {slot: code for slot, code in outputs.items() if states[slot].output_on}
        if on:
            return False, f"outputs on: {on}"
        if spgu and driver.pulse_output_active():
            return False, f"SPGU output still active ({flex.SPST_Q} 1)"
        if positive is not None and not positive.ok:
            return False, (f"all slots report 00, but the LOP? positive control failed ({positive.detail}): 00 does "
                           "not prove the outputs off")
        evidence = "" if positive is None else f"; positive control with the outputs on: {positive.detail}"
        spst = f"; {flex.SPST_Q} 0" if spgu else ""
        return all_outputs_off(states), "all slots report 00" + spst + evidence

    def clear() -> tuple[bool, str]:
        driver.device_clear()
        return True, "before the retry"

    verified = False
    wgfmu_ran = False
    for attempt in (1, 2):
        if attempt == 2:
            step("device_clear", attempt, clear)
        results: dict[str, bool] = {}
        if always_abort or driver.measurement_pending:
            results["abort"] = step("abort", attempt, abort)
        if spgu is None:
            spgu = _read_spgu_installed(driver, deferred)
        if spgu:
            results["spgu_stop"] = step("spgu_stop", attempt, spgu_stop)
        if wgfmu is not None and wgfmu.needed(driver.last_inventory, all_channels=shutdown):
            wgfmu_ran = True
            results["wgfmu"] = step("wgfmu", attempt, wgfmu.cleanup_step)
        results["zero"] = step("zero", attempt, zero)
        if scope:
            results["routes"] = step("routes", attempt, routes)
        results["disconnect"] = step("disconnect", attempt, disconnect)
        results["drain_errors"] = step("drain_errors", attempt, drain)
        results["verify"] = step("verify", attempt, verify)
        verified = results["zero"] and results["disconnect"] and results["verify"]
        if all(results.values()):
            break
    report = CleanupReport(steps=steps, verified=method if verified else "unverified", outputs_after=dict(outputs),
                           latched_fault=False, errors=errors, positive_control=positive,
                           switches_after=dict(switches_after))
    return CleanupOutcome(report=report, deferred=deferred[0] if deferred else None)


def _read_spgu_installed(driver: B1500Driver, deferred: list[BaseException]) -> bool:
    """``UNT?`` once (cleanup without a known inventory); an unreadable answer counts as an installed SPGU, and an
    interrupt is deferred like one inside a cleanup step."""
    try:
        return bool(spgu_installed(driver.modules()))
    except BaseException as exc:  # noqa: BLE001 - the SPGU step then runs and reports what fails
        if not isinstance(exc, Exception):
            deferred.append(exc)
        return True
