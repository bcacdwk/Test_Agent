"""SMU sampling operations (``MM 10``): time stamps, guarded synchronous sources and the sampling setup (blueprint v2
2.5, 2.7 kind ``smu_sampling``).

``SamplingOps`` is a mixin of ``B1500Driver``. ``sampling_setup`` and ``sampling_update`` check every synchronous
source (``MV``: base and bias against Icomp; ``MI``: base and bias against Vcomp) with the ``OutputGuard`` before the
first byte is written; time stamps (``TSC``/``TSR``), timing and abort settings are not source commands. Command texts
come from ``driver/flex/sampling.py`` and ``driver/flex/core.py`` (``MM``, ``TSC``, ``TSR``). ``XE`` and the data read
are ``CoreOps.execute_and_read``; ``driver/sampling.py`` parses the blocks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.driver.ops.smu import CmmMode
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel


def _canonical(channel: int) -> int:
    return channel * 100 + 1 if 1 <= channel <= 10 else channel


class SamplingSource(StrictModel):
    """One synchronous sampling source: ``MV`` (``quantity`` ``V``: volts, Icomp in A) or ``MI`` (``I``: amperes,
    Vcomp in V). It forces ``base`` from the trigger and ``bias`` after ``h_base`` (PG PDF 468-469, 477-478);
    ``range`` is the output ranging code (Table 4-4 / 4-5; 0 = auto)."""

    channel: Channel
    quantity: Literal["V", "I"]
    base: float
    bias: float
    compliance: float
    range: int = 0

    @model_validator(mode="after")
    def _consistent(self) -> SamplingSource:
        if self.quantity == "V" and self.compliance == 0:
            raise ValueError("an MV source needs a non-zero Icomp.")
        if self.quantity == "I" and self.base * self.bias < 0:
            raise ValueError("MI base and bias must have the same polarity.")
        codes = flex.V_RANGE_CODES if self.quantity == "V" else flex.I_RANGE_CODES
        if self.range not in codes:
            raise ValueError(f"range {self.range} is not an output ranging code for {self.quantity}.")
        return self

    def command(self) -> str:
        """The ``MV``/``MI`` command of this source."""
        build = flex.mv if self.quantity == "V" else flex.mi
        return build(self.channel, self.range, self.base, self.bias, self.compliance)


class SamplingSetup(StrictModel):
    """One sampling measurement (``ML``, ``MT``, ``MSC``, ``MV``/``MI``, ``MM 10``, ``CMM``; PG PDF 469-478, 380).

    ``mode`` is the ``ML`` code (1 linear, 2-7 log); ``h_bias``/``interval``/``number``/``h_base`` the ``MT``
    timing; ``abort`` enables the automatic abort and ``post`` sets the sources' output after a normal end
    (``MSC``); ``sources`` the synchronous sources; ``measure`` the measurement channels in order and ``operation``
    their ``CMM`` modes (unlisted channels keep theirs)."""

    mode: int = flex.LINEAR_SAMPLING
    h_bias: float = 0.0
    interval: float
    number: int = Field(ge=1, le=flex.MT_MAX_NUMBER)
    h_base: float = 0.0
    abort: bool = True
    post: Literal["base", "bias"] = "bias"
    sources: tuple[SamplingSource, ...] = ()
    measure: tuple[Channel, ...] = Field(min_length=1, max_length=flex.MAX_CHANNELS_MM)
    operation: dict[Channel, CmmMode] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> SamplingSetup:
        if self.mode != flex.LINEAR_SAMPLING and self.mode not in flex.LOG_SAMPLING_DENSITY:
            raise ValueError(f"mode {self.mode} is not an ML sampling mode.")
        if len({_canonical(ch) for ch in self.measure}) != len(self.measure):
            raise ValueError("A measurement channel is listed twice.")
        if len({_canonical(s.channel) for s in self.sources}) != len(self.sources):
            raise ValueError("A channel has two sampling sources.")
        if not set(self.operation) <= set(self.measure):
            raise ValueError("operation names a channel that is not measured.")
        return self


class SamplingOps(DriverBase):
    """Sampling operations of ``B1500Driver``: time stamps, guarded ``MV``/``MI``, ``MM 10`` setup."""

    def set_time_stamp(self, on: bool) -> None:
        """``TSC 1|0``: time stamp before every measurement datum (PG PDF 538-539). Not a source command."""
        self._write(flex.tsc(on))

    def reset_timer(self) -> None:
        """``TSR``: clear the timer count now (Time = 0; PG PDF 539-540). Not a source command."""
        self._write(flex.tsr())

    def _check_sources(self, operation: str, sources: tuple[SamplingSource, ...]) -> None:
        """Every base and bias level of every source against the guard, before anything is written."""
        for source in sources:
            guard = self._require_guard(operation, source.channel)
            guard.check(source.channel, source.quantity, source.base, source.compliance)
            guard.check(source.channel, source.quantity, source.bias, source.compliance)

    def sampling_setup(self, setup: SamplingSetup) -> None:
        """Guarded sampling setup: ``MCC`` (clears sources left by an earlier program), ``ML``, ``MT``, ``MSC``,
        ``MV``/``MI`` per source, ``MM 10,<measure>``, ``CMM`` per ``operation`` (PG PDF 461, 469-478, 470, 380).
        Every source level is checked first; ``XE`` is sent by ``execute_and_read``."""
        self._check_sources("sampling_setup", setup.sources)
        cmds = [
            flex.mcc(),
            flex.ml(setup.mode),
            flex.mt(setup.h_bias, setup.interval, setup.number, setup.h_base),
            flex.msc(setup.abort, setup.post),
            *(source.command() for source in setup.sources),
            flex.mm(flex.SAMPLING_MODE, setup.measure),
            *(flex.cmm(ch, op) for ch, op in setup.operation.items()),
        ]
        for cmd in cmds:
            self._write(cmd)

    def sampling_update(self, setup: SamplingSetup, *, timing: bool, sources: bool) -> None:
        """Re-program a set-up sampling measurement between two triggers: ``MT`` (``timing``) and the ``MV``/``MI``
        sources (``sources``; guard-checked first). The mode, abort and measurement channels stay as set up."""
        if sources:
            self._check_sources("sampling_update", setup.sources)
        cmds = [flex.mt(setup.h_bias, setup.interval, setup.number, setup.h_base)] if timing else []
        if sources:
            cmds += [source.command() for source in setup.sources]
        for cmd in cmds:
            self._write(cmd)
