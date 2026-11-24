"""SMU quasi-static C-V operations (``MM 13``): the setup model and its guarded writes, and the capacitance offset
measurement (blueprint v2 2.5, 2.7 kind ``smu_qscv``; WP8.5).

``QscvOps`` is a mixin of ``B1500Driver``. ``qscv_setup`` checks the sweep source with ``OutputGuard.check`` at its
start and stop value against its compliance (every value it forces, ``V_N +/- cvoltage/2`` included, lies between
them, because start and stop are never measured and ``cvoltage`` is at most the step) and the measurement channel
against the plan's allowlist before the first byte is written. Command texts come from ``driver/flex/qscv.py`` and
``driver/flex/core.py``; ``XE`` and the data read are ``CoreOps.execute_and_read`` (the data: ``driver/qscv.py``).

Setup order (PG Table 3-17, p242-243 (3-62 to 3-63)): ``MM 13,ch``, ``QSC``, ``QSO 0`` (normal mode only: QSO needs
``QSC 0``), ``QSL``, ``QSM``, ``QSR``, ``QST``, ``QSV``, then ``QSZ`` (``MM 13`` must precede it, error 243). The
smart operation (``QSO 1``) lets a dedicated SMU force a current of the instrument's choosing; no kind enables it
(the guard could bound only its voltage compliance), so the setup always switches it off.

``measure_qscv_offset`` sends ``QSZ 2`` after the setup: the instrument measures the capacitance offset of the path
with the measurement terminals open at the device end (the human lifts the probes first; the plan carries the
``physical_setup`` confirmation) and returns one ``C`` datum; ``QSZ 1`` in a later setup subtracts it.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.ops.core import DriverBase, RawBlock
from b1500_test_agent.driver.parser import parse_data
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel

OffsetMode = Literal["off", "cancel", "measure"]

OFFSET_QSZ: dict[str, int] = {"off": flex.QSZ_OFF, "cancel": flex.QSZ_ON, "measure": flex.QSZ_OFF}
"""The ``QSZ`` mode of the setup per offset handling: an offset measurement run sets the cancel off and then sends
``QSZ 2`` itself (``measure_qscv_offset``)."""


def _norm(channel: int) -> int:
    return channel * 100 + 1 if channel <= 10 else channel


class QscvSource(StrictModel):
    """The ``QSV`` sweep source on ``channel``: from ``start`` to ``stop`` in steps of ``step`` volts (a magnitude;
    its sign follows start -> stop; ``|stop - start|`` a whole number of steps), capacitance measurement voltage
    ``cvoltage`` (default = the step; at most the step), compliance ``icomp`` (A), output ranging ``range`` (Table
    4-4, 0 auto) and ``double`` (start -> stop -> start)."""

    channel: Channel
    start: float
    stop: float
    step: float = Field(gt=0)
    cvoltage: float | None = Field(default=None, gt=0)
    icomp: float
    range: int = 0
    double: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> QscvSource:
        if self.start == self.stop:
            raise ValueError("start and stop must be different.")
        if self.icomp == 0:
            raise ValueError("icomp must be non-zero.")
        if self.range not in flex.V_RANGE_CODES:
            raise ValueError(f"range {self.range} is not a voltage output ranging code.")
        ratio = abs(self.stop - self.start) / self.step
        if abs(ratio - round(ratio)) > 1e-6 * max(1.0, ratio):
            raise ValueError(f"|stop - start| = {abs(self.stop - self.start):g} V is not a whole number of "
                             f"{self.step:g} V steps.")
        if not 1 <= self.steps <= flex.QSCV_MAX_STEPS:
            raise ValueError(f"{self.steps} measured steps; QSV takes 1 to {flex.QSCV_MAX_STEPS} "
                             "(|stop - start| / step - 1).")
        if self.cvoltage is not None and self.cvoltage > self.step * (1 + 1e-9):
            raise ValueError(f"cvoltage {self.cvoltage:g} V exceeds the step {self.step:g} V (PG p498: the "
                             "instrument would reduce it).")
        if self.cvoltage is not None and self.cvoltage > flex.QSCV_MAX_CVOLTAGE_V:
            raise ValueError(f"cvoltage must be at most {flex.QSCV_MAX_CVOLTAGE_V:g} V.")
        return self

    @property
    def steps(self) -> int:
        """The ``QSV`` step count: ``|stop - start| / step - 1`` (start and stop are not measured)."""
        return round(abs(self.stop - self.start) / self.step) - 1

    @property
    def direction(self) -> float:
        """+1 for a rising sweep, -1 for a falling one."""
        return 1.0 if self.stop > self.start else -1.0

    @property
    def measuring_voltage(self) -> float:
        """The capacitance measurement voltage actually used (``cvoltage``, default the step)."""
        return self.cvoltage if self.cvoltage is not None else self.step

    @property
    def contiguous(self) -> bool:
        """True when ``|step| = cvoltage``: consecutive transitions join (delay2 0, V0/IL0 reused; PG p116)."""
        return math.isclose(self.measuring_voltage, self.step, rel_tol=1e-9)

    def step_voltages(self) -> list[float]:
        """The measured step voltages in measurement order (start and stop excluded; back again when double)."""
        forward = [self.start + self.direction * self.step * k for k in range(1, self.steps + 1)]
        return forward + forward[::-1] if self.double else forward

    def levels(self) -> list[float]:
        """``[start, stop]``: every value the source forces lies between them."""
        return [self.start, self.stop]


class QscvSetup(StrictModel):
    """One quasi-static C-V measurement (module docstring for the command order).

    ``measure_channel``: the ``MM 13`` channel (``None``: the source measures). ``cinteg``/``linteg``: integration
    times of the capacitance and leakage measurements (s); ``hold``, ``delay1``, ``delay2`` (``QST``). ``leakage_data``
    / ``compensation``: ``QSL``. ``operation``: ``QSC`` normal or 4155C/4156C ``compatible``. ``range_code``: ``QSR``
    -9 (10 pA) .. -14 (1 uA). ``auto_abort``/``post``: ``QSM``. ``offset``: ``off`` (``QSZ 0``), ``cancel`` (``QSZ 1``:
    subtract the offset measured earlier) or ``measure`` (``QSZ 0``; the run sends ``QSZ 2`` instead of ``XE``).
    """

    source: QscvSource
    measure_channel: Channel | None = None
    cinteg: float = Field(default=0.1, gt=0)
    linteg: float = Field(default=0.1, gt=0)
    hold: float = Field(default=0.0, ge=0)
    delay1: float = Field(default=0.0, ge=0)
    delay2: float = Field(default=0.0, ge=0)
    leakage_data: bool = True
    compensation: bool = True
    operation: Literal["normal", "compatible"] = "normal"
    range_code: int = -11
    auto_abort: bool = True
    post: Literal["start", "stop"] = "start"
    offset: OffsetMode = "off"

    @model_validator(mode="after")
    def _consistent(self) -> QscvSetup:
        if self.range_code not in flex.QSCV_RANGE_CODES:
            raise ValueError(f"range_code must be one of {sorted(flex.QSCV_RANGE_CODES)} (QSR, error 241).")
        return self

    @property
    def measured_channel(self) -> int:
        """The channel that measures (``MM 13,ch``)."""
        return self.measure_channel if self.measure_channel is not None else self.source.channel

    @property
    def points(self) -> int:
        """Measured steps (both directions of a double sweep)."""
        return len(self.source.step_voltages())

    @property
    def elements_per_step(self) -> int:
        """Data elements per step with ``FMT 1,1``: ``[DataL,] DataC, Source_data``."""
        return 3 if self.leakage_data else 2

    @property
    def range_a(self) -> float:
        """Full scale of the ``QSR`` range (A)."""
        return flex.QSCV_RANGE_CODES[self.range_code]

    def step_time_s(self, first: bool) -> float:
        """Nominal time of one measured step (s): delay1, the leakage before the transition (unless the transitions
        join after the first step), the transition (cinteg), the leakage after it and delay2 (0 when they join)."""
        joined = self.source.contiguous and not first
        before = 0.0 if joined else self.linteg
        after = self.linteg if (self.compensation or self.leakage_data) else 0.0
        before = before if (self.compensation or self.leakage_data) else 0.0
        delay2 = 0.0 if self.source.contiguous else self.delay2
        return self.delay1 + before + self.cinteg + after + delay2

    def duration_s(self) -> float:
        """Nominal duration of the sweep from ``XE``: hold plus every step."""
        return self.hold + sum(self.step_time_s(k == 0) for k in range(self.points))

    def offset_duration_s(self) -> float:
        """Nominal duration of the ``QSZ 2`` offset measurement (one step without hold)."""
        return self.step_time_s(True)

    def commands(self) -> list[str]:
        """Every setup command in sending order (module docstring); ``XE``/``QSZ 2`` are not part of the setup."""
        src = self.source
        lines = [flex.mm(flex.QSCV_MODE, [self.measured_channel]), flex.qsc(self.operation)]
        if self.operation == "normal":
            lines.append(flex.qso(False))
        lines += [flex.qsl(self.leakage_data, self.compensation), flex.qsm(self.auto_abort, self.post),
                  flex.qsr(self.range_code), flex.qst(self.cinteg, self.linteg, self.hold, self.delay1, self.delay2),
                  flex.qsv(src.channel, "double" if src.double else "single", src.range, src.start, src.stop,
                           src.measuring_voltage, src.steps, src.icomp),
                  flex.qsz(OFFSET_QSZ[self.offset])]
        return lines


class QscvOps(DriverBase):
    """Quasi-static C-V operations of ``B1500Driver``: the guarded ``MM 13`` setup and the offset measurement."""

    def qscv_setup(self, setup: QscvSetup) -> None:
        """Guarded QSCV setup (``QscvSetup.commands``): the sweep source at start and stop against its compliance and
        the measurement channel in the plan, before anything is written. ``XE`` is sent by ``execute_and_read``."""
        src = setup.source
        guard = self._require_guard("qscv_setup", src.channel)
        for level in src.levels():
            guard.check(src.channel, "V", level, src.icomp)
        if _norm(setup.measured_channel) != _norm(src.channel):
            guard.check_channel(setup.measured_channel)
        for cmd in setup.commands():
            self._write(cmd)

    def measure_qscv_offset(self, *, timeout_s: float) -> RawBlock:
        """``QSZ 2``: measure the capacitance offset of the QSCV path (terminals open at the device end) and read the
        one datum it returns (PG p499-500 (4-181 to 4-182); the setup must be complete). Like ``XE``, the instrument is
        busy until the datum is read; a failed read leaves the measurement pending, so the cleanup sends ``AB``.

        Raises:
            FlexParseError: If the response is malformed (``raw`` holds the text).
        """
        if not (isinstance(timeout_s, int | float) and math.isfinite(timeout_s) and timeout_s > 0):
            raise ValueError(f"timeout_s must be a positive number of seconds, got {timeout_s!r}")
        command = flex.qsz(flex.QSZ_MEASURE)
        fmt, _mode = self._format
        self._require_idle(command)
        self._measurement_pending = True  # set before writing: a failed write may still have started it
        self.transport.write(command)
        started_at = datetime.now(UTC)
        started = time.monotonic()
        raw = self.transport.read(timeout_s=timeout_s)
        duration = time.monotonic() - started
        self._measurement_pending = False
        try:
            points = parse_data(raw, fmt)
        except FlexParseError as exc:
            raise FlexParseError(str(exc), raw=raw) from exc
        return RawBlock(raw=raw, points=tuple(points), fmt=fmt, expected_points=1, xe_at=started_at,
                        read_at=datetime.now(UTC), duration_s=duration)


__all__ = ["OFFSET_QSZ", "OffsetMode", "QscvOps", "QscvSetup", "QscvSource"]
