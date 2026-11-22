"""The WGFMU phase of a transaction and cleanup step 3 (blueprint v2 0 #7, 2.6; WP10.3).

The WGFMU instrument library opens its own VISA session to the B1500A, which cannot work while the transaction's FLEX
link holds the exclusive lock (ATV-14; the simulated library refuses online calls then, as the lab's VISA would).
``WgfmuLink`` is the WGFMU side of one transaction: the library (``Bus.wgfmu``), whether its session is open, how
the FLEX link was released for it and whether the WGFMU safe state is confirmed.

**Phase** (``Transaction.wgfmu_phase()`` -> ``WgfmuPhase``): ``with tx.wgfmu_phase() as wg:`` releases the FLEX link
(``unlock``; with ``settings.wgfmu.flex_during_phase: close`` the link is closed instead, the ATV-14 fallback, unless
the kind asks ``flex_io=True`` because it sends FLEX commands inside the phase: then it stays open without the lock,
recorded as ``flex: unlocked (flex_io)``), opens the library session (``open_session(resource)``), ``initialize``\\ s
every WGFMU channel and yields the guarded ``WgfmuDriver``. FLEX commands inside the phase stay allowed (SMU bias, WG
Ex. 10) while the link is open. The exit ALWAYS runs step 3 below (body success, exception, interrupt): the safe
state, the session closed, the FLEX link locked again. A failed step 3 raises ``WgfmuSafeStateFailed`` (or the
interrupt it caught) when the body succeeded; the body's own exception is never replaced. The whole phase is
audited in the transaction's sink (library calls ``wgfmu_call``, checkpoints ``wgfmu_phase`` and
``wgfmu_phase_end``).

**Step 3** (``WgfmuLink.safe_state_step``): ``abort`` -> ``initialize`` -> ``disconnect`` each connected channel
(``WgfmuDriver.safe_state``) -> ``close_session`` -> relock (or reopen and lock) the FLEX link. Every part runs
whatever failed before it. The transaction cleanup (``run_cleanup``, between the SPGU stop and ``DZ``) runs it again
when a phase left the safe state unconfirmed (``pending``: a failed disconnect, close or relock), opening a new
library session with the FLEX lock released and disconnecting every channel the library lists; and in
``safe_shutdown`` and the in-flight recovery, on a mainframe with a WGFMU, whenever the library is available (on visa:
the DLL probe says loadable), since a crashed or foreign session may have left a channel connected.

Verification (step 8): the FLEX link must be locked again; on hardware step 3 must also have succeeded completely
(every channel disconnected, the session closed): the library cannot read the RSU relays back, so its acceptance of
every call is the evidence. On the simulator the simulated state is checked as well (connected or running channels,
an open session). The RSU states the library accepted go into ``LiveState.switch_states`` (the pre-execute read,
``read_live``) and ``CleanupReport.switches_after``.

**Pre-execute read** (``read_live``, used by ``Transaction.snapshot(wgfmu=True)``): FLEX lock released ->
``open_session`` -> ``channel_ids`` -> ``disconnect`` the channel of every declared RSU (its rest path; the library
has no query of the relay, so a disconnect it accepts is the reading: a stuck relay or a missing RSU, firmware 3001,
leaves the output unread and R-ROUTE-01 blocks) -> ``close_session`` -> relock. A relock refused by another client
propagates (``BusLocked``).

Hardware facts, TODO(verify) at bring-up L8: releasing the exclusive lock is enough for the library's session and the
relock is clean (ATV-14; else switch ``flex_during_phase`` to ``close``); ``initialize`` resets the WGFMU only and
leaves an SMU bias alone (ATV-17; the simulator models it so; the phase initializes at its entry, before the kind
applies any bias inside the phase); a ``disconnect`` the library accepts means the RSU relay opened.
"""

from __future__ import annotations

import contextlib
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Literal

from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.driver.wgfmu import (
    WgfmuDriver,
    WgfmuSafeStateFailed,
    find_rsu,
    rsu_rest_path,
)
from b1500_test_agent.models.routing import SwitchState
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL, ModuleInventory
from b1500_test_agent.session.wgfmu_live import bound, read_channels
from b1500_test_agent.transport.wgfmu.api import LIBRARY_ERROR, WgfmuApi, WgfmuError, error_text

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

FlexRelease = Literal["unlock", "close"]
"""How the FLEX link makes room for the library session: exclusive lock released, or link closed (ATV-14 fallback)."""

WGFMU_MODULE_TYPE = "WGFMU"
_DETAIL_LIMIT = 500


def wgfmu_installed(inventory: ModuleInventory | None) -> bool | None:
    """Whether ``inventory`` (an ``UNT?`` reading) lists a WGFMU; ``None`` when no inventory is known."""
    if inventory is None:
        return None
    return any(MODULE_TYPE_BY_MODEL.get(m.model) == WGFMU_MODULE_TYPE for m in inventory.modules)


@dataclass(frozen=True)
class StepOutcome:
    """One run of step 3: ``ok`` = every part succeeded; ``detail`` for the audit; ``deferred`` = an interrupt caught
    meanwhile (re-raised by the caller once its cleanup is complete)."""

    ok: bool
    detail: str
    deferred: BaseException | None = None


@dataclass(frozen=True)
class LiveRead:
    """The pre-execute read: the library's channel ids (``None`` = unread) and the RSU states it accepted."""

    channels: list[int] | None
    rsu_states: dict[str, SwitchState] = field(default_factory=dict)


class WgfmuLink:
    """The WGFMU side of one transaction (module docstring). Created lazily by the transaction."""

    def __init__(self, tx: Transaction) -> None:
        self._tx = tx
        session = tx._session
        self.api: WgfmuApi | None = session.bus.wgfmu
        self.resource = session.transport.resource
        self.session_open = False
        self.released: FlexRelease | None = None
        self.pending = False
        """A phase ran and its safe state is not confirmed yet (cleanup step 3 must run)."""
        self.active = False
        self.driver: WgfmuDriver | None = None
        self.last: StepOutcome | None = None
        self.phases: list[str] = []
        """One entry per phase: how the FLEX link was released (``unlocked``, ``closed``, ``unlocked (flex_io)``)."""

    # -- plumbing ------------------------------------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """A library exists on this bus and, on visa, its DLL probe says loadable (no load happens here)."""
        if self.api is None:
            return False
        probe = self._tx._session.wgfmu_library()
        return probe is None or probe.loadable

    def bind(self) -> contextlib.AbstractContextManager[None]:
        """Audit the library calls of the block in the transaction's sink with its run, transaction and intent."""
        tx = self._tx
        assert self.api is not None
        return bound(self.api, tx._sink, run=tx.run_id, tx=tx.tx_id, intent=tx.intent)

    def host_wait(self, seconds: float) -> None:
        """Host time between status polls: the FLEX link's clock while it is open (simulator: virtual time; VISA:
        sleep); with the link closed a real sleep on visa and nothing on the simulator (its library's polls move the
        virtual clock)."""
        tx = self._tx
        if self.released != "close":
            tx.driver.host_wait(seconds)
        elif tx._session.backend == "visa":
            time.sleep(seconds)

    def release_flex(self, how: FlexRelease) -> None:
        """Unlock (or close) the FLEX link for the library; no-op when already released."""
        if self.released is not None:
            return
        session = self._tx._session
        if how == "close":
            session._bus_close()
        else:
            session.transport.unlock()
        self.released = how

    def restore_flex(self) -> None:
        """Lock the FLEX link again (reopen and lock it after ``close``); raises ``BusLocked`` when another client took
        the bus meanwhile (the link then stays released and the cleanup tries again)."""
        how = self.released
        if how is None:
            return
        session = self._tx._session
        if how == "close":
            session._bus_begin()
        else:
            session.transport.lock()
        self.released = None

    def _driver(self, guard: OutputGuard | None) -> WgfmuDriver:
        assert self.api is not None
        if self.driver is None:
            self.driver = WgfmuDriver(self.api, guard, switches=self._tx._session.switches, wait=self.host_wait)
        return self.driver

    def rsu_states(self) -> dict[str, SwitchState]:
        """The RSU states the library accepted in this transaction (``WgfmuDriver.rsu_states``)."""
        return {} if self.driver is None else self.driver.rsu_states()

    # -- step 3 --------------------------------------------------------------------------------------------------------

    def needed(self, inventory: ModuleInventory | None, *, all_channels: bool) -> bool:
        """Whether cleanup step 3 runs: a phase left something open or unconfirmed, or (``all_channels``: shutdown,
        recovery) the mainframe has a WGFMU and the library is available. ``inventory`` is the cleanup driver's
        ``UNT?`` reading, else the session's last snapshot; an unknown inventory counts as a WGFMU."""
        if self.pending or self.session_open or self.released is not None:
            return True
        if not all_channels:
            return False
        if inventory is None:
            live = self._tx._session.last_live
            inventory = live.inventory if live is not None else None
        return wgfmu_installed(inventory) is not False and self.available

    def safe_state_step(self, *, all_channels: bool) -> StepOutcome:
        """Step 3 (module docstring). ``all_channels``: open a session if none is open and disconnect every channel
        the library lists (cleanup); else only what this transaction's phase connected (phase exit). Never raises;
        sets ``pending`` from the result."""
        parts: list[str] = []
        failures: list[str] = []
        deferred: list[BaseException] = []

        def attempt(name: str, action: object) -> bool:
            try:
                action()  # type: ignore[operator]
            except BaseException as exc:  # noqa: BLE001 - every part runs; interrupts are handed back
                if not isinstance(exc, Exception):
                    deferred.append(exc)
                failures.append(f"{name} FAILED ({type(exc).__name__}: {exc})")
                return False
            parts.append(name)
            return True

        api = self.api
        if api is None:
            failures.append("no WGFMU instrument library on this bus")
        else:
            with self.bind():
                # the cleanup needs the library: FLEX lock released (also for a session a failed close left open)
                released = all_channels and attempt("flex released", lambda: self.release_flex("unlock"))
                if released and not self.session_open and attempt("open_session",
                                                                  lambda: api.open_session(self.resource)):
                    self.session_open = True
                if self.session_open:
                    channels: list[int] = []
                    if all_channels:
                        attempt("channel_ids", lambda: channels.extend(api.channel_ids()))
                    report = self._driver(None).safe_state(channels)
                    if report.deferred is not None:
                        deferred.append(report.deferred)
                    for name, ok, detail in report.steps:
                        if ok:
                            parts.append(name)
                        else:
                            failures.append(f"{name} FAILED ({detail})")
                    if attempt("close_session", api.close_session):
                        self.session_open = False
        if self.released is not None:
            attempt("flex relocked", self.restore_flex)
        ok = not failures and not self.session_open and self.released is None
        self.pending = not ok
        detail = "; ".join([*failures, ", ".join(parts)]) if failures else ", ".join(parts) or "nothing to do"
        outcome = StepOutcome(ok=ok, detail=detail[:_DETAIL_LIMIT], deferred=deferred[0] if deferred else None)
        self.last = outcome
        return outcome

    def cleanup_step(self) -> tuple[bool, str]:
        """``run_cleanup``'s step 3 (``all_channels``): ``(ok, detail)``; an interrupt it caught is re-raised so that
        the cleanup defers it like one inside any other step."""
        outcome = self.safe_state_step(all_channels=True)
        if outcome.deferred is not None:
            raise outcome.deferred
        return outcome.ok, outcome.detail

    def verification(self, *, sim: bool) -> tuple[bool, str]:
        """The WGFMU part of step 8 after step 3 ran: the FLEX link locked again and (hardware) step 3 complete."""
        if self.released is not None:
            return False, "the FLEX link is not locked again after the WGFMU session"
        rsu = self.rsu_states()
        listed = ", ".join(f"{t} {s}" for t, s in sorted(rsu.items()))
        if sim:
            return True, "WGFMU: FLEX relocked" + (f"; RSU {listed}" if listed else "")
        last = self.last
        if last is None or not last.ok or self.session_open:
            return False, f"WGFMU safe state not confirmed ({last.detail if last else 'step 3 did not run'})"
        return True, "WGFMU: every channel disconnected, session closed, FLEX relocked" + (
            f"; RSU {listed}" if listed else "")

    # -- pre-execute read ----------------------------------------------------------------------------------------------

    def read_live(self) -> LiveRead:
        """The pre-execute read (module docstring); ``channels`` is ``None`` (audited checkpoint
        ``wgfmu_channels_unread``) without an available library or when the library fails."""
        tx = self._tx
        probe = tx._session.wgfmu_library()
        if self.api is None or (probe is not None and not probe.loadable):
            reason = "no WGFMU instrument library on this bus" if self.api is None else (probe.message if probe
                                                                                         else "")
            tx._emit("checkpoint", {"label": "wgfmu_channels_unread"}, error=reason[:_DETAIL_LIMIT])
            return LiveRead(channels=None)
        api = self.api
        transport = tx._session.transport
        transport.unlock()
        states: dict[str, SwitchState] = {}
        try:
            with self.bind():
                channels = read_channels(api, self.resource, then=lambda ids: states.update(self._read_rsus(api, ids)))
                return LiveRead(channels=channels, rsu_states=states)
        except WgfmuError as exc:
            tx._emit("checkpoint", {"label": "wgfmu_channels_unread"}, error=str(exc)[:_DETAIL_LIMIT])
            return LiveRead(channels=None)
        finally:
            transport.lock()

    def _read_rsus(self, api: WgfmuApi, channels: list[int]) -> dict[str, SwitchState]:
        states: dict[str, SwitchState] = {}
        for ch in channels:
            rsu = find_rsu(self._tx._session.switches, ch)
            if rsu is None:
                continue
            target = f"{rsu[0].id}.{rsu[1]}"
            try:
                api.disconnect(ch)
            except WgfmuError as exc:
                self._tx._emit("checkpoint", {"label": "rsu_unread", "target": target}, error=str(exc)[:_DETAIL_LIMIT])
                continue
            states[target] = rsu_rest_path(rsu[0])
        return states


class WgfmuPhase:
    """``with tx.wgfmu_phase() as wg:`` (module docstring). Single use."""

    def __init__(self, link: WgfmuLink, guard: OutputGuard | None, *, how: FlexRelease, flex_io: bool) -> None:
        self.link = link
        self.guard = guard
        self.how: FlexRelease = "unlock" if flex_io else how
        self.flex_io = flex_io
        self._stack = ExitStack()

    def __enter__(self) -> WgfmuDriver:
        link = self.link
        tx = link._tx
        if link.active:
            raise RuntimeError("a WGFMU phase is already open in this transaction")
        api = link.api
        if api is None or not link.available:
            reason = "no WGFMU instrument library on this bus" if api is None else "the WGFMU library is not loadable"
            raise WgfmuError(LIBRARY_ERROR, error_text(LIBRARY_ERROR, reason), function="open_session")
        label = {"unlock": "unlocked", "close": "closed"}[self.how] + (" (flex_io)" if self.flex_io and
                                                                        self.how == "unlock" else "")
        link.phases.append(label)
        link.active = True
        link.pending = True
        tx._emit("checkpoint", {"label": "wgfmu_phase", "flex": label})
        try:
            self._stack.enter_context(link.bind())
            link.release_flex(self.how)
            api.open_session(link.resource)
            link.session_open = True
            api.initialize()
            link.driver = None
            return link._driver(self.guard)
        except BaseException as exc:
            self.__exit__(type(exc), exc, exc.__traceback__)
            raise

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        link = self.link
        if not link.active:
            return False
        try:
            outcome = link.safe_state_step(all_channels=False)
        finally:
            link.active = False
            self._stack.close()
        link._tx._emit("checkpoint", {"label": "wgfmu_phase_end", "ok": outcome.ok, "detail": outcome.detail},
                       error=None if outcome.ok else outcome.detail)
        if exc is None:
            if outcome.deferred is not None:
                raise outcome.deferred
            if not outcome.ok:
                raise WgfmuSafeStateFailed(f"WGFMU phase exit: safe state not confirmed: {outcome.detail}")
        return False
