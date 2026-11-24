"""SMU search operations (``MM 14`` linear search, ``MM 15`` binary search, ``MM 9`` quasi-pulsed spot): the setup
models and their guarded writes (blueprint v2 2.5, 2.7 kind ``smu_search``; WP7.5).

``SearchOps`` is a mixin of ``B1500Driver``. ``search_setup`` checks every source before the first byte is written:
the search source with ``OutputGuard.check`` at its start and its stop value against its compliance (every value it
can force lies between them), the synchronous source at ``polarity x start + offset`` and ``polarity x stop +
offset``. ``quasi_pulse_setup`` checks the quasi-pulse source at start and stop the same way. Command texts come from
``driver/flex/search.py`` and ``driver/flex/core.py``; ``XE`` and the data read are ``CoreOps.execute_and_read`` (the
data: ``driver/search.py``).

Setup order (PG examples Table 3-10 p217, 3-11 p220, 3-12 p223; the order of setting commands before ``XE`` is free
except that the synchronous source follows its search source, which clears it):

- MM 14: ``MM 14``, ``LSM``, ``LSVM 1``, ``LSTM``, ``LGI``/``LGV``, ``LSV``/``LSI``, ``LSSV``/``LSSI``;
- MM 15: ``MM 15``, ``BSM``, ``BSVM 1``, ``BST``, ``BGI``/``BGV``, ``BSV``/``BSI``, ``BSSV``/``BSSI``;
- MM 9: ``MM 9,ch``, ``BDT``, ``BDM``, ``BDV``.

The monitor measures its compliance side: current (``LGI``/``BGI``) on a voltage-forcing channel, voltage
(``LGV``/``BGV``) on a current-forcing one (error 279, PG p582); the kind knows which channel forces what.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel

Forced = Literal["V", "I"]
SearchMode = Literal[14, 15]

BINARY_MAX_POINTS = flex.BINARY_MAX_REPEAT + 3
"""Most measurements of one binary search counted by the estimate: the start (and stop) value, then at most 16 output
changes (the repeat limit; a limit search ends when the change falls below the output resolution, about as many)."""


def _norm(channel: int) -> int:
    return channel * 100 + 1 if channel <= 10 else channel


class SearchSource(StrictModel):
    """The search source (``LSV``/``LSI``, ``BSV``/``BSI``): ``source`` ``V`` (volts, Icomp ``comp`` in A) or ``I``
    (amperes, Vcomp ``comp`` in V) from ``start`` towards ``stop``; ``range`` its output ranging code (0 auto)."""

    channel: Channel
    source: Forced = "V"
    start: float
    stop: float
    comp: float
    range: int = 0

    @model_validator(mode="after")
    def _consistent(self) -> SearchSource:
        if self.start == self.stop:
            raise ValueError("start and stop must be different (error 276).")
        if self.comp == 0:
            raise ValueError("comp must be non-zero.")
        codes = flex.V_RANGE_CODES if self.source == "V" else flex.I_OUTPUT_RANGE_CODES
        if self.range not in codes:
            raise ValueError(f"range {self.range} is not an output ranging code of a {self.source} source.")
        return self

    def levels(self) -> list[float]:
        """``[start, stop]``: every value the source can force lies between them."""
        return [self.start, self.stop]


class SyncSource(StrictModel):
    """The synchronous source (``LSSV``/``LSSI``, ``BSSV``/``BSSI``): ``polarity x search output + offset`` in the
    search source's output mode and range, compliance ``comp``."""

    channel: Channel
    polarity: Literal[1, -1] = 1
    offset: float = 0.0
    comp: float

    @model_validator(mode="after")
    def _consistent(self) -> SyncSource:
        if self.comp == 0:
            raise ValueError("comp must be non-zero.")
        return self

    def value(self, search: float) -> float:
        """Its output when the search source forces ``search``."""
        return self.polarity * search + self.offset

    def levels(self, source: SearchSource) -> list[float]:
        """Its outputs at the search source's start and stop."""
        return [self.value(source.start), self.value(source.stop)]


class SearchMonitor(StrictModel):
    """The search monitor (``LGI``/``LGV``, ``BGI``/``BGV``): ``quantity`` it measures (its compliance side),
    ``target`` (A or V), ``range`` its measurement ranging code (0 auto: the minimum range covering the target)."""

    channel: Channel
    quantity: Forced
    target: float
    range: int = 0

    @model_validator(mode="after")
    def _consistent(self) -> SearchMonitor:
        codes = flex.I_RANGE_CODES if self.quantity == "I" else flex.V_RANGE_CODES
        if self.range not in codes:
            raise ValueError(f"range {self.range} is not a {self.quantity} measurement ranging code.")
        return self


class SearchSetup(StrictModel):
    """One linear (``mode`` 14) or binary (``mode`` 15) search (module docstring for the command order).

    Linear: ``step`` (from start towards stop, at most 1001 steps) and ``judge`` (``above``: the first step with a
    reading ``>= target``; ``below``: ``<= target``; default from the target's sign, i.e. ``|reading| >= |target|``
    for a target of either polarity). Binary: exactly one of ``limit`` (stop at ``target +/- limit``) and ``repeats``
    (1-16 output changes); ``control`` normal (start, stop, then halving from stop) or cautious (start, start +/- D/2,
    then halving; never forces the stop value first). ``hold``/``delay``: ``LSTM``/``BST``; ``auto_abort``/``post``:
    ``LSM``/``BSM`` (an abort forces the start values); ``sense``: ``LSVM``/``BSVM`` 1 (``Data_sense`` returned).
    """

    mode: SearchMode
    source: SearchSource
    monitor: SearchMonitor
    sync: SyncSource | None = None
    step: float | None = None
    judge: Literal["above", "below"] | None = None
    limit: float | None = Field(default=None, gt=0)
    repeats: int | None = Field(default=None, ge=1, le=flex.BINARY_MAX_REPEAT)
    control: Literal["normal", "cautious"] = "cautious"
    hold: float = Field(default=0.0, ge=0)
    delay: float = Field(default=0.0, ge=0)
    auto_abort: bool = True
    post: Literal["start", "stop", "last"] = "start"
    sense: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> SearchSetup:
        if self.mode == flex.LINEAR_SEARCH_MODE:
            if self.step is None:
                raise ValueError("a linear search needs its step.")
            if self.limit is not None or self.repeats is not None:
                raise ValueError("limit/repeats belong to the binary search.")
        else:
            if self.step is not None or self.judge is not None:
                raise ValueError("step and judge belong to the linear search.")
            if (self.limit is None) == (self.repeats is None):
                raise ValueError("a binary search needs exactly one of limit and repeats.")
        if self.sync is not None and _norm(self.sync.channel) == _norm(self.source.channel):
            raise ValueError("the synchronous source must be another channel than the search source (error 278).")
        return self

    @property
    def linear_judge(self) -> Literal["above", "below"]:
        """The ``LGI``/``LGV`` judgement: ``judge``, else ``above`` for a target >= 0, ``below`` for a negative one."""
        if self.judge is not None:
            return self.judge
        return "above" if self.monitor.target >= 0 else "below"

    @property
    def points(self) -> int:
        """Most measurements of the search: the linear steps, or ``BINARY_MAX_POINTS`` (repeats + 2 in repeat mode)."""
        if self.mode == flex.LINEAR_SEARCH_MODE:
            assert self.step is not None
            return math.floor(abs(self.source.stop - self.source.start) / abs(self.step) + 1e-9) + 1
        if self.repeats is not None:
            return self.repeats + 2
        return BINARY_MAX_POINTS

    def source_commands(self) -> list[str]:
        """The search source command and, after it, the synchronous source command."""
        src = self.source
        if self.mode == flex.LINEAR_SEARCH_MODE:
            assert self.step is not None
            build = flex.lsv if src.source == "V" else flex.lsi
            lines = [build(src.channel, src.range, src.start, src.stop, self.step, src.comp)]
            sync = flex.lssv if src.source == "V" else flex.lssi
        else:
            build_b = flex.bsv if src.source == "V" else flex.bsi
            lines = [build_b(src.channel, src.range, src.start, src.stop, src.comp)]
            sync = flex.bssv if src.source == "V" else flex.bssi
        if self.sync is not None:
            lines.append(sync(self.sync.channel, self.sync.polarity, self.sync.offset, self.sync.comp))
        return lines

    def commands(self) -> list[str]:
        """Every setup command in sending order (module docstring); ``XE`` is not part of the setup."""
        mon = self.monitor
        if self.mode == flex.LINEAR_SEARCH_MODE:
            monitor = flex.lgi if mon.quantity == "I" else flex.lgv
            head = [flex.mm(self.mode, []), flex.lsm(self.auto_abort, self.post), flex.lsvm(self.sense),
                    flex.lstm(self.hold, self.delay), monitor(mon.channel, self.linear_judge, mon.range, mon.target)]
        else:
            binary = flex.bgi if mon.quantity == "I" else flex.bgv
            mode, condition = ((flex.BINARY_LIMIT_MODE, self.limit) if self.limit is not None
                               else (flex.BINARY_REPEAT_MODE, self.repeats))
            assert condition is not None
            head = [flex.mm(self.mode, []), flex.bsm(self.control, self.auto_abort, self.post), flex.bsvm(self.sense),
                    flex.bst(self.hold, self.delay), binary(mon.channel, mode, condition, mon.range, mon.target)]
        return head + self.source_commands()


class QuasiPulseSetup(StrictModel):
    """One quasi-pulsed spot measurement (``MM 9``): the ``BDV`` source on ``channel`` from ``start`` towards ``stop``
    (``|stop - start| >= 10 V``) with compliance ``icomp``; ``hold``/``delay`` (``BDT``), the settling detection
    ``interval`` and the measured quantity ``measure`` (``BDM``) on ``measure_channel`` (``None``: the source)."""

    channel: Channel
    start: float = 0.0
    stop: float
    icomp: float
    range: int = 0
    hold: float = Field(default=0.0, ge=0)
    delay: float = Field(default=0.0, ge=0)
    interval: Literal["short", "long"] = "short"
    measure: Forced = "V"
    measure_channel: Channel | None = None

    @model_validator(mode="after")
    def _consistent(self) -> QuasiPulseSetup:
        if abs(self.stop - self.start) < flex.BDV_MIN_SPAN_V - 1e-12:
            raise ValueError(f"|stop - start| must be {flex.BDV_MIN_SPAN_V:g} V or more (PG p107).")
        if self.icomp == 0:
            raise ValueError("icomp must be non-zero.")
        if self.range not in flex.V_RANGE_CODES:
            raise ValueError(f"range {self.range} is not a voltage output ranging code.")
        return self

    @property
    def measured_channel(self) -> int:
        """The channel that measures (``MM 9,ch``)."""
        return self.measure_channel if self.measure_channel is not None else self.channel

    def levels(self) -> list[float]:
        """``[start, stop]``."""
        return [self.start, self.stop]

    def commands(self) -> list[str]:
        """``MM 9,ch``, ``BDT``, ``BDM``, ``BDV`` (module docstring)."""
        return [flex.mm(flex.QUASI_PULSED_SPOT_MODE, [self.measured_channel]), flex.bdt(self.hold, self.delay),
                flex.bdm(self.interval, self.measure),
                flex.bdv(self.channel, self.range, self.start, self.stop, self.icomp)]


class SearchOps(DriverBase):
    """Search operations of ``B1500Driver``: guarded ``MM 14/15`` and ``MM 9`` setups."""

    def search_setup(self, setup: SearchSetup) -> None:
        """Guarded linear/binary search setup (``SearchSetup.commands``): the search source at start and stop, the
        synchronous source at its two corresponding values, before anything is written. ``XE`` is sent by
        ``execute_and_read``."""
        src = setup.source
        guard = self._require_guard("search_setup", src.channel)
        for level in src.levels():
            guard.check(src.channel, src.source, level, src.comp)
        if setup.sync is not None:
            sync_guard = self._require_guard("search_setup", setup.sync.channel)
            for level in setup.sync.levels(src):
                sync_guard.check(setup.sync.channel, src.source, level, setup.sync.comp)
        for cmd in setup.commands():
            self._write(cmd)

    def quasi_pulse_setup(self, setup: QuasiPulseSetup) -> None:
        """Guarded quasi-pulsed spot setup (``QuasiPulseSetup.commands``): the source at start and stop against its
        compliance before anything is written; the measurement channel must be in the plan too."""
        guard = self._require_guard("quasi_pulse_setup", setup.channel)
        for level in setup.levels():
            guard.check(setup.channel, "V", level, setup.icomp)
        guard.check_channel(setup.measured_channel)
        for cmd in setup.commands():
            self._write(cmd)


__all__ = ["BINARY_MAX_POINTS", "QuasiPulseSetup", "SearchMonitor", "SearchOps", "SearchSetup", "SearchSource",
           "SyncSource"]
