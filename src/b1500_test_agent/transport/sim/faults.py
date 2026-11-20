"""Fault engine of the simulator: active ``SimFault``s with their counters (blueprint 3, v2 4.3).

Schemas live in ``models/sim.py`` (``SimFault``, ``SimFaultProfile``). Faults come from the scenario's fault
profile or from ``SimInstrument.inject()``; counters start when a fault becomes active. Instrument-side faults
(``compliance_at``, ``errx``, ``timeout`` on ``XE``/queries, ``garbage_data``, ``interlock_open``, ``oscillation``,
overrides, ``ignore_dz``, ``slow``, ``abort_ignored``, ``cmu_correction_lost``, ``cmu_overload``, ``spgu_no_stop``,
``spgu_load_mismatch``) are consulted by
``SimInstrument``; link faults (``timeout``
on ``read``, ``disconnect``, ``cleanup_failure``, ``bus_locked``, ``run_interrupt``) by ``SimTransport`` (and by the
visa-loop test resource, which puts the real ``VisaTransport`` on the same instrument). ``run_interrupt`` is counted
by the instrument (one ``XE`` = one measurement) and raised by the link at the read of that measurement. Other
host-side faults (parser exception, ``EnvelopeViolation``) are injected by monkeypatching in the tests, not here.
``breakdown_at`` (WP7.4) is consulted by the sampling engine (``units/sampling.py``) at every sampled point.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from b1500_test_agent.models.sim import (
    AbortIgnored,
    BreakdownAt,
    BusLockedFault,
    CleanupFailure,
    CmuCorrectionLost,
    CmuOverload,
    ComplianceAt,
    Disconnect,
    ErrxFault,
    GarbageData,
    IdnOverride,
    IgnoreDz,
    InterlockOpen,
    ModulesOverride,
    Oscillation,
    RunInterrupt,
    SimFault,
    Slow,
    SpguLoadMismatch,
    SpguNoStop,
    TimeoutFault,
)
from b1500_test_agent.models.station import SimSlot


def _canonical(channel: int) -> int:
    """``101``..``1001`` -> ``1``..``10`` (PG Table 4-1); other numbers unchanged."""
    return channel // 100 if channel > 10 and channel % 100 == 1 else channel


GARBAGE_ELEMENT = "N?I+#.#####E-##"
"""Unparsable 15-character element written by ``garbage_data`` (same width as a real FMT 1/5 element)."""


@dataclass
class _Active:
    fault: SimFault
    count: int = 0
    spent: bool = False
    origin: float | None = None
    """Instrument time of the first sampled point after activation (``breakdown_at``)."""


class FaultEngine:
    """The active faults and their counters."""

    def __init__(self, faults: Iterable[SimFault] = ()) -> None:
        self._active: list[_Active] = []
        for fault in faults:
            self.add(fault)

    # -- management ---------------------------------------------------------------------------------------------------

    def add(self, fault: SimFault) -> None:
        """Activate ``fault`` (its counters start now)."""
        self._active.append(_Active(fault))

    def clear(self) -> None:
        """Deactivate every fault."""
        self._active.clear()

    @property
    def faults(self) -> list[SimFault]:
        """Active faults, in activation order (spent one-shot faults included)."""
        return [a.fault for a in self._active]

    def _of(self, kind: type) -> list[_Active]:
        return [a for a in self._active if isinstance(a.fault, kind) and not a.spent]

    def _nth(self, items: list[_Active]) -> bool:
        """Count one occurrence on each of ``items`` (one-shot ``nth`` faults); True if one of them fires now."""
        fired = False
        for item in items:
            item.count += 1
            if item.count == item.fault.nth:  # type: ignore[union-attr]
                item.spent = True
                fired = True
        return fired

    # -- instrument side ----------------------------------------------------------------------------------------------

    def errors_after(self, mnemonic: str) -> list[int]:
        """Error codes to queue after an execution of ``mnemonic`` (``errx`` faults)."""
        codes = []
        for item in self._of(ErrxFault):
            fault = item.fault
            assert isinstance(fault, ErrxFault)
            if fault.after_cmd == mnemonic:
                item.count += 1
                if item.count == fault.nth:
                    item.spent = True
                    codes.append(fault.code)
        return codes

    def command_hangs(self, mnemonic: str) -> bool:
        """Count one execution of ``mnemonic``; True if it never completes (``timeout`` on that mnemonic)."""
        return self._nth([a for a in self._of(TimeoutFault) if a.fault.on == mnemonic])  # type: ignore[union-attr]

    def query_hangs(self, mnemonic: str) -> bool:
        """Count one execution of query ``mnemonic``; True if it never answers (``timeout`` on ``query:<m>``)."""
        target = f"query:{mnemonic}"
        return self._nth([a for a in self._of(TimeoutFault) if a.fault.on == target])  # type: ignore[union-attr]

    def compliance_channels(self, step: int) -> set[int]:
        """Channels forced into compliance at ``step`` (``compliance_at``)."""
        return {a.fault.ch for a in self._of(ComplianceAt) if a.fault.step == step}  # type: ignore[union-attr]

    def garbage_at(self, step: int) -> bool:
        """True if the data of ``step`` is garbled (``garbage_data``)."""
        return any(a.fault.at_step == step for a in self._of(GarbageData))  # type: ignore[union-attr]

    def interlock_opens_now(self) -> bool:
        """True while an ``interlock_open`` fault without ``at_step`` is active."""
        return any(a.fault.at_step is None for a in self._of(InterlockOpen))  # type: ignore[union-attr]

    def interlock_opens_at(self, step: int) -> bool:
        """True if an ``interlock_open`` fault opens the interlock when a measurement reaches ``step``."""
        return any(a.fault.at_step == step for a in self._of(InterlockOpen))  # type: ignore[union-attr]

    def oscillating(self, step: int) -> bool:
        """True if the measured channels oscillate at ``step`` (``oscillation``)."""
        for item in self._of(Oscillation):
            steps = item.fault.steps  # type: ignore[union-attr]
            if steps is None or step in steps:
                return True
        return False

    def idn(self) -> str | None:
        """The overriding ``*IDN?`` answer (latest ``idn_override``), if any."""
        items = self._of(IdnOverride)
        return items[-1].fault.idn if items else None  # type: ignore[union-attr]

    def modules(self) -> list[SimSlot] | None:
        """The overriding module list (latest ``modules_override``), if any."""
        items = self._of(ModulesOverride)
        return list(items[-1].fault.slots) if items else None  # type: ignore[union-attr]

    def stuck(self, channel: int) -> bool:
        """True if ``channel`` ignores zeroing (``ignore_dz``)."""
        for item in self._of(IgnoreDz):
            channels = item.fault.channels  # type: ignore[union-attr]
            if channels is None or channel in channels:
                return True
        return False

    def abort_ignored(self) -> bool:
        """Count one ``AB`` execution; True if it has no effect (``abort_ignored``: executions ``nth`` ..
        ``nth + count - 1``, or every one from ``nth`` on when ``count`` is null)."""
        ignored = False
        for item in self._of(AbortIgnored):
            fault = item.fault
            assert isinstance(fault, AbortIgnored)
            item.count += 1
            if item.count < fault.nth:
                continue
            ignored = True
            if fault.count is not None and item.count >= fault.nth + fault.count - 1:
                item.spent = True
        return ignored

    def interrupts_measurement(self) -> bool:
        """Count one ``XE`` trigger; True if the host is interrupted while this measurement runs (``run_interrupt``
        whose ``segment`` is this 0-based trigger index; one-shot)."""
        fired = False
        for item in self._of(RunInterrupt):
            fault = item.fault
            assert isinstance(fault, RunInterrupt)
            if item.count == fault.segment:
                item.spent = True
                fired = True
            item.count += 1
        return fired

    def breakdowns_due(self, t: float) -> list[str | None]:
        """Devices a ``breakdown_at`` fault breaks down at sampled time ``t`` (instrument clock, s): the ``device`` of
        every fault whose delay has elapsed since its first sampled point (``None`` = every dielectric device).
        One-shot; the first call after activation starts the fault's clock."""
        due: list[str | None] = []
        for item in self._of(BreakdownAt):
            fault = item.fault
            assert isinstance(fault, BreakdownAt)
            if item.origin is None:
                item.origin = t
            if t - item.origin >= fault.t_s - 1e-12:
                item.spent = True
                due.append(fault.device)
        return due

    def cmu_correction_lost_after(self, mnemonic: str) -> bool:
        """Count one execution of ``mnemonic``; True if the MFCMUs lose their corrections now
        (``cmu_correction_lost``, one-shot)."""
        return self._nth([a for a in self._of(CmuCorrectionLost)
                          if a.fault.after_cmd == mnemonic])  # type: ignore[union-attr]

    def cmu_overload_at(self, step: int) -> str | None:
        """The ``cmu_overload`` condition at MFCMU measurement step ``step`` (``None`` without one)."""
        for item in self._of(CmuOverload):
            fault = item.fault
            assert isinstance(fault, CmuOverload)
            if fault.at_step == step:
                return fault.condition
        return None

    def spgu_stuck(self) -> bool:
        """True while a ``spgu_no_stop`` fault holds: the SPGU output ignores every stop condition but ``SPP``."""
        return bool(self._of(SpguNoStop))

    def spgu_spp_ignored(self) -> bool:
        """Count one ``SPP``; True if it has no effect (``spgu_no_stop``: the first ``spp_ignored`` ones, or all). The
        first ``SPP`` after those ends the fault."""
        ignored = False
        for item in self._of(SpguNoStop):
            fault = item.fault
            assert isinstance(fault, SpguNoStop)
            item.count += 1
            if fault.spp_ignored is not None and item.count > fault.spp_ignored:
                item.spent = True
            else:
                ignored = True
        return ignored

    def spgu_load(self, channel: int) -> float | None:
        """The load (Ohm) a ``spgu_load_mismatch`` fault puts on SPGU ``channel`` (canonical number), if any."""
        for item in reversed(self._of(SpguLoadMismatch)):
            fault = item.fault
            assert isinstance(fault, SpguLoadMismatch)
            if fault.channel is None or _canonical(fault.channel) == channel:
                return fault.load_ohm
        return None

    def slow_factor(self) -> float:
        """Product of the active ``slow`` factors (1.0 without one)."""
        factor = 1.0
        for item in self._of(Slow):
            factor *= item.fault.factor  # type: ignore[union-attr]
        return factor

    # -- link side ----------------------------------------------------------------------------------------------------

    def read_times_out(self) -> bool:
        """Count one read call; True if it times out (``timeout`` on ``read``)."""
        return self._nth([a for a in self._of(TimeoutFault) if a.fault.on == "read"])  # type: ignore[union-attr]

    def link_down(self) -> bool:
        """True once a ``disconnect`` fault has let its ``after_writes`` writes through."""
        return any(a.count >= a.fault.after_writes for a in self._of(Disconnect))  # type: ignore[union-attr]

    def count_write(self) -> None:
        """Count one write that reached the instrument (``disconnect`` counters)."""
        for item in self._of(Disconnect):
            item.count += 1

    def zeroing_times_out(self) -> bool:
        """Count one ``DZ``/``CL`` write; True if it times out (``cleanup_failure``)."""
        fired = False
        for item in self._of(CleanupFailure):
            fault = item.fault
            assert isinstance(fault, CleanupFailure)
            item.count += 1
            if fault.count is not None and item.count >= fault.count:
                item.spent = True
            fired = True
        return fired

    def lock_refused(self) -> bool:
        """Count one bus-lock request; True if another client holds the lock now (``bus_locked``: requests
        ``nth`` .. ``nth + count - 1``, or every request from ``nth`` on when ``count`` is null)."""
        refused = False
        for item in self._of(BusLockedFault):
            fault = item.fault
            assert isinstance(fault, BusLockedFault)
            item.count += 1
            if item.count < fault.nth:
                continue
            refused = True
            if fault.count is not None and item.count >= fault.nth + fault.count - 1:
                item.spent = True
        return refused
