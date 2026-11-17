"""Fault engine of the simulator: active ``SimFault``s with their counters (blueprint 3).

Schemas live in ``models/sim.py`` (``SimFault``, ``SimFaultProfile``). Faults come from the scenario's fault
profile or from ``SimInstrument.inject()``; counters start when a fault becomes active. Instrument-side faults
(``compliance_at``, ``errx``, ``timeout`` on ``XE``/queries, ``garbage_data``, ``interlock_open``, ``oscillation``,
overrides, ``ignore_dz``, ``slow``) are consulted by ``SimInstrument``; link faults (``timeout`` on ``read``,
``disconnect``, ``cleanup_failure``) by ``SimTransport``. Host-side faults (parser exception, ``KeyboardInterrupt``
between ``XE`` and read, ``EnvelopeViolation``) are injected by monkeypatching in the tests, not here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from b1500_test_agent.models.sim import (
    CleanupFailure,
    ComplianceAt,
    Disconnect,
    ErrxFault,
    GarbageData,
    IdnOverride,
    IgnoreDz,
    InterlockOpen,
    ModulesOverride,
    Oscillation,
    SimFault,
    Slow,
    TimeoutFault,
)
from b1500_test_agent.models.station import SimSlot

GARBAGE_ELEMENT = "N?I+#.#####E-##"
"""Unparsable 15-character element written by ``garbage_data`` (same width as a real FMT 1/5 element)."""


@dataclass
class _Active:
    fault: SimFault
    count: int = 0
    spent: bool = False


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
