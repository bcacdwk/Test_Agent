"""SMU operations: A/D converter, ranging, guarded DC force and staircase sweep setup (blueprint 2.5).

``SmuOps`` is a mixin of ``B1500Driver``. Source operations (``force_v``, ``staircase_v``) refuse without an
``OutputGuard`` and check every channel and value against it before the first byte is written; command texts come
from ``driver/flex/smu.py`` and ``driver/flex/core.py`` (``MM``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel, Integration, SweepTiming

ADC_TYPE_CODES: dict[str, int] = {"high_speed": 0, "high_resolution": 1}
"""``Integration.adc`` -> ``AAD``/``AIT`` type (PG PDF 351, 356)."""

ADC_MODE_CODES: dict[str, int] = {"auto": 0, "manual": 1, "plc": 2}
"""``Integration.mode`` -> ``AIT`` mode (PG PDF 357)."""

CmmMode = Annotated[int, Field(ge=0, le=4)]


class StaircaseSetup(StrictModel):
    """One staircase voltage sweep (``MM 2``, ``CMM``, ``WV``, ``WT``, ``WM``; PG PDF 470, 380, 568-569, 564-565,
    552-553).

    ``channel`` sweeps from ``start`` to ``stop`` (V) in ``points`` steps with current compliance ``icomp`` (A,
    non-zero; polarity follows the output) on voltage output range code ``vrange`` (Table 4-4; 0 = auto).
    ``measure`` lists the measurement channels in measurement order (data order in each step). ``operation`` sets
    ``CMM`` for some of them (0 compliance side, 1 current, 2 voltage, 3 force side, 4 synchronous I/V); unlisted
    channels keep their mode. ``auto_abort`` enables ``WM`` abort (stop on compliance, overflow or oscillation; data
    after the abort read ``199.999E+99``) and ``post`` chooses the output after a normal end.
    """

    channel: Channel
    start: float
    stop: float
    points: int = Field(ge=1, le=10001)
    icomp: float
    vrange: int = 0
    sweep: Literal["linear", "log"] = "linear"
    double: bool = False
    measure: tuple[Channel, ...] = Field(min_length=1, max_length=flex.MAX_CHANNELS_MM)
    operation: dict[Channel, CmmMode] = Field(default_factory=dict)
    timing: SweepTiming = Field(default_factory=SweepTiming)
    auto_abort: bool = True
    post: Literal["start", "stop"] = "start"

    @model_validator(mode="after")
    def _consistent(self) -> StaircaseSetup:
        if self.icomp == 0:
            raise ValueError("icomp must be non-zero.")
        if self.vrange not in flex.V_RANGE_CODES:
            raise ValueError(f"vrange {self.vrange} is not a PG Table 4-4 voltage output ranging code.")
        if len(set(self.measure)) != len(self.measure):
            raise ValueError("A measurement channel is listed twice.")
        if not set(self.operation) <= set(self.measure):
            raise ValueError("operation names a channel that is not measured.")
        if self.sweep == "log" and (self.start == 0 or self.stop == 0 or (self.start > 0) != (self.stop > 0)):
            raise ValueError("A log sweep needs non-zero start and stop of the same polarity.")
        return self

    @property
    def wv_mode(self) -> int:
        """``WV`` mode: 1 linear, 2 log, 3 linear double, 4 log double."""
        return (1 if self.sweep == "linear" else 2) + (2 if self.double else 0)



class SmuOps(DriverBase):
    """SMU operations of ``B1500Driver``: integration, ranging, guarded ``DV`` and staircase ``WV`` setup."""

    def set_integration(self, adc: int, mode: int, n: float, *, chs: Sequence[int] = ()) -> None:
        """``AAD ch,adc`` for each of ``chs``, then ``AIT adc,mode,n`` (PG PDF 351, 356-359)."""
        cmds = [flex.aad(ch, adc) for ch in chs] + [flex.ait(adc, mode, n)]
        for cmd in cmds:
            self._write(cmd)

    def apply_integration(self, integration: Integration, chs: Sequence[int]) -> None:
        """``set_integration`` from an ``Integration`` model (ADC type, mode and N)."""
        self.set_integration(ADC_TYPE_CODES[integration.adc], ADC_MODE_CODES[integration.mode], integration.n, chs=chs)

    def set_range(self, ch: int, quantity: Literal["I", "V"], code: int) -> None:
        """``RI``/``RV`` measurement ranging (PG PDF 501, 503); codes via ``driver.modules.ranging_code``."""
        if quantity == "I":
            self._write(flex.ri(ch, code))
        elif quantity == "V":
            self._write(flex.rv(ch, code))
        else:
            raise ValueError(f"quantity must be 'I' or 'V', got {quantity!r}")

    def force_v(self, ch: int, v: float, *, icomp: float, rng: int = 0) -> None:
        """Guarded ``DV ch,rng,v,icomp`` (PG PDF 396)."""
        self._require_guard("force_v", ch).check(ch, "V", v, icomp)
        self._write(flex.dv(ch, rng, v, icomp))

    def staircase_v(self, setup: StaircaseSetup) -> None:
        """Guarded staircase voltage sweep setup: ``MM 2,<measure>``, ``CMM`` per ``operation``, ``WV``, ``WT``,
        ``WM`` (PG PDF 470, 380, 568-569, 564-565, 552-553). Both sweep end points are checked before anything is
        written; ``XE`` is sent by ``execute_and_read``."""
        guard = self._require_guard("staircase_v", setup.channel)
        guard.check(setup.channel, "V", setup.start, setup.icomp)
        guard.check(setup.channel, "V", setup.stop, setup.icomp)
        timing = setup.timing
        cmds = [
            flex.mm(2, setup.measure),
            *(flex.cmm(ch, op) for ch, op in setup.operation.items()),
            flex.wv(setup.channel, setup.wv_mode, setup.vrange, setup.start, setup.stop, setup.points, setup.icomp),
            flex.wt(
                timing.hold_s, timing.delay_s, timing.step_delay_s, timing.trigger_delay_s, timing.measure_delay_s
            ),
            flex.wm(2 if setup.auto_abort else 1, 1 if setup.post == "start" else 2),
        ]
        for cmd in cmds:
            self._write(cmd)
