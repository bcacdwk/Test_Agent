"""Shared measurement blocks of the composite kinds (blueprint v2 2.7 ``catalog/blocks.py``; decision table row 5:
composite kinds are Python code built from these blocks, never a step language in the recipes).

Every block talks only to the transaction's guarded driver: source levels pass the ``OutputGuard`` before the first
byte is written, command texts come from ``driver/flex/`` through the driver (this module holds no FLEX literal), and
every block drains ``ERRX?`` before it triggers, so an instrument error aborts before ``XE``. Blocks never clean up:
the transaction's cleanup (``AB`` -> ``DZ`` -> ``CL`` -> verify) runs on any exit.

- v1 blocks, shared since WP2.1 and re-exported here so that composite kinds take every block from one module:
  ``configure_staircase`` (a complete staircase setup up to ``XE``, ``CN`` included), ``staircase_rows`` (table rows of
  one sweep block), ``force_bias`` (one ``DV``/``DI``) and ``drain_or_raise`` (the ``ERRX?`` gate).
- ``RouteStep``/``route_steps``/``apply_routes``: the switch routes a plan applies. ``route_steps`` resolves the
  roles bound through a switch target (``BoundChannel.via``) at compile time; ``apply_routes`` sets them through the
  guarded driver (``OutputGuard.check_route``). Implemented for the switch kinds that have a driver path: the ASU
  (``SAP``, WP7.1). A 16440A selector, SCUU or RSU route is refused at compile time (``CompileError``) until its
  family adds the driver path (selector: WP9.2, SCUU: WP8.1, RSU: WP10.x); an empty list does nothing.
- ``open_outputs``: the one-time setup of a composite run: time stamps off (``TSC 0``: the read parsers expect no time
  elements), ADC (``AAD``/``AIT``), output switches on (``CN``), ``ERRX?`` drain and, on hardware, the ``LOP?``
  positive control.
- ``set_levels``: every output of a phase to its level (``force_bias`` each); with the levels of the phase before
  (``previous``) the outputs whose |level| falls are set before those whose |level| rises (``ordered``), so a phase
  change never passes through a bias combination above both phases (an HCI drain leaves its stress level before the
  gate rises to its read level).
- ``staircase_read``/``spot_read``/``spot_once``/``read``: one read with the outputs already on: the read levels of
  the constant outputs, the sweep (``MM 2``) or spot (``MM 1``) setup, ranging (``RI``), ``ERRX?`` drain, ``XE`` and
  the data read(s) (``tx.check_abort`` after every spot ``XE``, so a cancel acts within one spot measurement);
  ``read_blocks`` turns a read's blocks into table rows (``staircase_rows`` / ``SmuSpotKind.rows_of``).
- ``Monitor``/``hold_chunks``/``hold_bias``: hold DC levels for a time, timed by the instrument itself. A hold is a
  chain of sampling measurements (``MM 10``, one sample each) of at most ``SEGMENT_S`` (25 s) per block: the outputs
  stay at their DC levels (``DV`` before the trigger; ``MSC`` never touches DC outputs) and the measured roles are
  sampled once at the end of each block (the stress-current monitor), with the automatic abort on compliance,
  overflow or oscillation (``MSC 2``). Each block is one segment between two checkpoints (R-RUN-02, blueprint v2
  2.6): the caller's ``on_block`` callback records its rows and calls ``tx.checkpoint`` (progress, ``partial.csv``,
  cancel via ``safe_shutdown``). The instrument's timer runs the hold, so the simulator ages its devices in virtual
  time exactly as long as the hardware would hold the stress; a block that reports compliance (a broken gate, a
  short) ends the hold (``HoldResult.stopped``).

Hold timing (PG p474-476 (4-156) "MT"): a block of programmed length ``L`` is ``MT h_bias,interval,1,0`` with the
single sample ``h_bias`` after the trigger; the sample's measurement lasts ``period = min(interval, channels x
measurement time)`` (the instrument shortens the averaging to keep the interval, PG p475 (4-157)), so the block holds
the outputs for ``h_bias + period``. ``h_bias = L - period`` rounded to the 10 ms grid keeps the hold at ``L`` (exactly
for 1 PLC and longer integration). The duration estimate and every time axis use ``h_bias + period``; on hardware
the host round trips between blocks (a few ms each) add unrecorded stress: TODO(verify) at bring-up stage L9 with
the time stamps of a long run.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from b1500_test_agent.catalog.kinds.smu_spot import SmuSpotKind, SpotProgram
from b1500_test_agent.catalog.kinds.smu_staircase import (
    READ_TIMEOUT_MARGIN_S,
    BiasOutput,
    MeasureColumn,
    StaircaseProgram,
    configure_staircase,
    drain_or_raise,
    force_bias,
    measurement_time_s,
    staircase_rows,
)
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import RawBlock, SamplingSetup
from b1500_test_agent.driver.sampling import parse_sampling
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel, Integration
from b1500_test_agent.models.plan import ChannelBinding
from b1500_test_agent.models.routing import Route, SwitchKind
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

__all__ = [
    "HOLD_GRID_S",
    "MONITOR_INTERVAL_S",
    "SEGMENT_S",
    "STOP_STATUSES",
    "HoldResult",
    "Monitor",
    "RouteStep",
    "apply_routes",
    "configure_staircase",
    "drain_or_raise",
    "flagged_statuses",
    "force_bias",
    "hold_bias",
    "hold_chunks",
    "open_outputs",
    "ordered",
    "read",
    "read_blocks",
    "route_steps",
    "set_levels",
    "spot_once",
    "spot_read",
    "staircase_read",
    "staircase_rows",
]

SEGMENT_S = 25.0
"""Longest hold block (s): with the per-block allowance it keeps every checkpoint within the default
``policy.run_limits.segment_max_s`` (30 s) of R-RUN-02 (the ``smu_sampling`` chain uses the same 25 s)."""

HOLD_GRID_S = flex.MT_HOLD_RESOLUTION_S
"""Resolution of a hold block's length and of ``MT h_bias`` (10 ms, PG p475 (4-157))."""

MONITOR_INTERVAL_S = 0.02
"""``MT`` interval of a hold block (one sample): the longest time its monitor sample may take; longer integrations are
shortened to it by the instrument (PG p475 (4-157))."""

HOLD_OVERHEAD_S = 0.5
"""Allowance per hold block for the trigger, the data transfer and the checkpoint in the duration estimate."""

STOP_STATUSES = frozenset("CTVX")
"""Status letters after which a composite run stops: compliance (``C``, another channel ``T``), overflow or invalid
data (``V``), oscillation (``X``)."""

ASU_KIND: SwitchKind = "asu"
DRIVER_ROUTE_KINDS: frozenset[str] = frozenset({ASU_KIND})
"""Switch kinds with a driver path for ``apply_routes`` (the ASU's ``SAP``, WP7.1)."""


# -- routes ----------------------------------------------------------------------------------------------------------


class RouteStep(StrictModel):
    """One route a plan applies: the route, its switch kind and the port index the driver addresses (``SAP``: the
    SMU channel the ASU belongs to)."""

    route: Route
    switch_kind: SwitchKind
    index: int = Field(ge=0)


def route_steps(binding: ChannelBinding, station: StationProfile, *, kind_id: str) -> list[RouteStep]:
    """The routes of the roles bound through a switch target, resolved for ``apply_routes`` (compile time, pure).

    A role whose switch is undeclared or whose wiring is unknown is skipped (R-PIN-01 blocks the plan).

    Raises:
        CompileError: For a switch kind without a driver path (16440A selector, SCUU, RSU).
    """
    steps: list[RouteStep] = []
    for bound in binding.roles.values():
        if bound.via is None or bound.channel is None:
            continue
        switch = station.switch(bound.via.switch)
        if switch is None or bound.via.output not in switch.ports:
            continue
        if switch.kind not in DRIVER_ROUTE_KINDS:
            raise CompileError(f"{kind_id}: role {bound.role} reaches its terminal through {switch.id} "
                               f"({switch.kind}); this kind routes only ASU paths (the {switch.kind} route has no "
                               "driver path yet): wire the terminal directly")
        step = RouteStep(route=bound.via, switch_kind=switch.kind, index=switch.ports[bound.via.output].index)
        if step not in steps:
            steps.append(step)
    return steps


def apply_routes(tx: Transaction, steps: Sequence[RouteStep]) -> None:
    """Set every route through the guarded driver, in order (``OutputGuard.check_route`` admits the plan's routes and
    each switch's rest state); nothing for an empty list. Call before ``CN``: an ASU path change connects or
    disconnects the SMU output at the DUT.

    Raises:
        ValueError: For a switch kind without a driver path (``route_steps`` refuses those at compile time).
    """
    for step in steps:
        if step.switch_kind != ASU_KIND:
            raise ValueError(f"route {step.route}: no driver path for a {step.switch_kind} route")
        tx.driver.set_asu_path(step.route, step.index)
    if steps:
        tx.mark("routes set: " + ", ".join(str(s.route) for s in steps))


# -- outputs ---------------------------------------------------------------------------------------------------------


def open_outputs(tx: Transaction, integration: Integration, measure: Sequence[MeasureColumn],
                 enable: Sequence[Channel]) -> None:
    """The one-time setup of a composite run: ``TSC 0``, ``AAD``/``AIT`` of the measured channels, ``CN``, ``ERRX?``
    drain (interlock or any error aborts) and, on hardware, the ``LOP?`` positive control. Levels follow
    (``set_levels`` or a read)."""
    driver = tx.driver
    driver.set_time_stamp(False)
    driver.apply_integration(integration, [m.channel for m in measure])
    driver.enable(list(enable))
    drain_or_raise(tx, "enabling the outputs")
    tx.mark("outputs enabled")
    tx.lop_positive_control(list(enable))


Levels = Mapping[int, float]
"""Programmed DC level per channel (V for voltage outputs) at the end of a phase."""


def _norm(channel: int) -> int:
    return channel * 100 + 1 if 1 <= channel <= 10 else channel


def ordered(outputs: Sequence[BiasOutput], previous: Levels | None) -> list[BiasOutput]:
    """``outputs`` with those whose |level| falls (or stays) before those whose |level| rises against ``previous``
    (stable within each group; unchanged order without ``previous``)."""
    if not previous:
        return list(outputs)
    before = {_norm(ch): level for ch, level in previous.items()}

    def rises(output: BiasOutput) -> bool:
        return abs(output.level) > abs(before.get(_norm(output.channel), 0.0))

    return [o for o in outputs if not rises(o)] + [o for o in outputs if rises(o)]


def set_levels(tx: Transaction, outputs: Sequence[BiasOutput], previous: Levels | None = None) -> None:
    """Every output of a phase to its level (``force_bias``: guarded ``DV``/``DI``), in ``ordered`` order."""
    for output in ordered(outputs, previous):
        force_bias(tx, output)


def flagged_statuses(blocks: Sequence[RawBlock]) -> list[str]:
    """The ``STOP_STATUSES`` letters reported by any element of ``blocks`` (sorted, distinct)."""
    return sorted({str(p.status.value) for b in blocks for p in b.points if str(p.status.value) in STOP_STATUSES})


# -- reads -----------------------------------------------------------------------------------------------------------


def staircase_read(tx: Transaction, program: StaircaseProgram, timeout_s: float,
                   previous: Levels | None = None) -> RawBlock:
    """One staircase sweep with the outputs already on: ``FMT`` of the program, the constant outputs at their read
    levels (``set_levels`` after ``previous``), the sweep setup (``MM``/``CMM``/``WV``/``WT``/``WM``), ``RI`` per
    ranged role, ``ERRX?`` drain, ``XE`` and one read of ``steps x width`` elements."""
    driver = tx.driver
    driver.set_format(*program.data_format)
    set_levels(tx, program.biases, previous)
    driver.staircase(program.sweep)
    for ranged in program.ranges:
        driver.set_range(ranged.channel, "I", ranged.code)
    drain_or_raise(tx, "the read setup")
    return driver.execute_and_read(expected_points=program.steps * program.width, timeout_s=timeout_s)


def spot_once(tx: Transaction, measure: Sequence[MeasureColumn], timeout_s: float) -> RawBlock:
    """One spot measurement of the set-up ``MM 1`` channels: ``XE``, one read of one element per channel, then
    ``tx.check_abort`` (a cancel acts within one spot measurement)."""
    block = tx.driver.execute_and_read(expected_points=len(measure), timeout_s=timeout_s)
    tx.check_abort()
    return block


def spot_read(tx: Transaction, program: SpotProgram, previous: Levels | None = None) -> list[RawBlock]:
    """One spot read with the outputs already on: ``FMT`` of the program, the constant outputs at their read levels
    (``set_levels`` after ``previous``), ``MM 1``/``CMM``, ``RI`` per ranged role, ``ERRX?`` drain, then
    ``program.samples`` x ``spot_once`` (a range survey is not a read: the caller refuses it)."""
    driver = tx.driver
    driver.set_format(*program.data_format)
    set_levels(tx, program.outputs, previous)
    driver.spot_setup([m.channel for m in program.measure], {m.channel: 1 if m.quantity == "I" else 2
                                                             for m in program.measure})
    for ranged in program.ranges:
        driver.set_range(ranged.channel, "I", ranged.code)
    drain_or_raise(tx, "the read setup")
    timeout = 2.0 * program.row_estimate_s + READ_TIMEOUT_MARGIN_S
    return [spot_once(tx, program.measure, timeout) for _ in range(program.samples)]


ReadKind = Literal["staircase", "spot"]


class ReadSpec(StrictModel):
    """What one read measures: a staircase sweep (``staircase``) or ``samples`` spot measurements (``spot``)."""

    kind: ReadKind
    staircase: StaircaseProgram | None = None
    spot: SpotProgram | None = None
    timeout_s: float = Field(gt=0)
    """Read timeout of a staircase sweep (``2 x estimate + 10 s``); spot reads derive theirs per measurement."""

    @property
    def measure(self) -> list[MeasureColumn]:
        program = self.staircase if self.kind == "staircase" else self.spot
        assert program is not None
        return list(program.measure)

    @property
    def blocks(self) -> int:
        """Data blocks one read returns (one sweep, or one block per spot sample)."""
        if self.kind == "staircase":
            return 1
        assert self.spot is not None
        return self.spot.samples

    @property
    def outputs(self) -> list[BiasOutput]:
        """The constant outputs the read sets (bias and grounded SMUs; a spot read's former sweep role too)."""
        if self.kind == "staircase":
            assert self.staircase is not None
            return list(self.staircase.biases)
        assert self.spot is not None
        return list(self.spot.outputs)

    def levels_after(self) -> dict[int, float]:
        """The programmed levels when the read ends: its constant outputs and, for a sweep, the sweep source back at
        its start value (``WM 2,1``)."""
        levels = {o.channel: o.level for o in self.outputs}
        if self.kind == "staircase":
            assert self.staircase is not None
            levels[self.staircase.sweep.channel] = self.staircase.sweep.start
        return levels


def read(tx: Transaction, spec: ReadSpec, previous: Levels | None = None) -> list[RawBlock]:
    """One read (``staircase_read`` or ``spot_read``) after the phase that left ``previous``; returns its data blocks
    in order."""
    if spec.kind == "staircase":
        assert spec.staircase is not None
        return [staircase_read(tx, spec.staircase, spec.timeout_s, previous)]
    assert spec.spot is not None
    return spot_read(tx, spec.spot, previous)


def read_blocks(spec: ReadSpec, blocks: Sequence[RawBlock], *, first_step: int) -> list[dict[str, object]]:
    """Table rows of one read's blocks, ``step`` from ``first_step`` (``staircase_rows`` / ``SpotProgram.rows_of``).

    Raises:
        ValueError: If the blocks do not hold the programmed elements.
    """
    if spec.kind == "staircase":
        assert spec.staircase is not None
        if len(blocks) != 1:
            raise ValueError(f"a staircase read is one block, got {len(blocks)}")
        return staircase_rows(spec.staircase, blocks[0], first_step=first_step)
    assert spec.spot is not None
    rows = SmuSpotKind.rows_of(spec.spot, list(blocks))
    for offset, row in enumerate(rows):
        row["step"] = first_step + offset
    return rows


# -- holds -----------------------------------------------------------------------------------------------------------


class Monitor(StrictModel):
    """The monitor sample of a hold block: the measured channels (``MM 10`` order), the ``MT`` interval and the
    expected measurement time ``period`` of the sample (module docstring)."""

    measure: list[MeasureColumn] = Field(min_length=1, max_length=flex.MAX_CHANNELS_MM)
    interval: float = MONITOR_INTERVAL_S
    period: float = Field(gt=0)

    @classmethod
    def of(cls, measure: Sequence[MeasureColumn], integration: Integration) -> Monitor:
        """The monitor of ``measure`` at ``integration`` (``period`` = min(interval, channels x measurement time))."""
        period = min(MONITOR_INTERVAL_S, len(measure) * measurement_time_s(integration))
        return cls(measure=list(measure), period=round(period, 9))

    @property
    def width(self) -> int:
        """Elements of one sample with ``FMT 1,1`` and no time stamps: the sampling index plus one per channel."""
        return 1 + len(self.measure)

    def setup(self, h_bias: float) -> SamplingSetup:
        """The ``MM 10`` setup of one block: linear, ``MT h_bias,interval,1,0``, automatic abort, no sampling sources
        (the DC outputs hold the levels)."""
        return SamplingSetup(mode=flex.LINEAR_SAMPLING, h_bias=h_bias, interval=self.interval, number=1, h_base=0.0,
                             abort=True, post="bias", sources=(), measure=tuple(m.channel for m in self.measure),
                             operation={m.channel: (1 if m.quantity == "I" else 2) for m in self.measure})

    def timeout_s(self, h_bias: float) -> float:
        """Read timeout of one block: ``2 x (h_bias + period + allowance) + 10 s``."""
        return 2.0 * (h_bias + self.period + HOLD_OVERHEAD_S) + READ_TIMEOUT_MARGIN_S

    def values(self, block: RawBlock) -> list[tuple[MeasureColumn, float, str]]:
        """``(column, value, status)`` of the block's sample, in ``MM`` order.

        Raises:
            FlexParseError: If the block is not one sample of the monitored channels.
            ValueError: If it holds no complete sample.
        """
        data = parse_sampling(block.points, [m.channel for m in self.measure])
        if len(data.samples) != 1:
            raise ValueError(f"a hold block holds one sample, got {len(data.samples)}")
        sample = data.samples[0]
        return [(column, element.value, str(element.status.value))
                for column, element in zip(self.measure, sample.values, strict=True)]


def _grid(value: float) -> float:
    return round(round(value / HOLD_GRID_S) * HOLD_GRID_S, 2)


def hold_chunks(seconds: float, period: float) -> list[float]:
    """``MT h_bias`` of the blocks that hold for ``seconds`` (module docstring): ``SEGMENT_S`` blocks and a shorter
    last one, each ``h_bias = length - period`` on the 10 ms grid (at least 0).

    Raises:
        ValueError: If ``seconds`` is not a positive multiple of the 10 ms grid.
    """
    if not (math.isfinite(seconds) and seconds > 0) or abs(seconds / HOLD_GRID_S - round(seconds / HOLD_GRID_S)) > 1e-6:
        raise ValueError(f"a hold lasts a positive multiple of {HOLD_GRID_S} s, got {seconds!r}")
    count = max(1, math.ceil(seconds / SEGMENT_S - 1e-9))
    lengths = [SEGMENT_S] * (count - 1) + [_grid(seconds - (count - 1) * SEGMENT_S)]
    return [max(0.0, _grid(length - period)) for length in lengths]


@dataclass
class HoldResult:
    """What ``hold_bias`` did: the blocks read in order and whether a block ended the hold early (``reason``)."""

    blocks: list[RawBlock] = field(default_factory=list)
    stopped: bool = False
    reason: str = ""


def hold_bias(tx: Transaction, outputs: Sequence[BiasOutput], seconds: float, monitor: Monitor, *,
              on_block: Callable[[int, float, RawBlock], None], label: str = "hold",
              previous: Levels | None = None) -> HoldResult:
    """Hold ``outputs`` at their levels for ``seconds`` (module docstring): ``set_levels`` (after ``previous``),
    ``FMT 1,1``, the first block's ``MM 10`` setup, then per block (``MT`` again when its length changes) ``ERRX?``
    drain, ``XE``, one read and ``on_block(index, h_bias, block)`` (the caller records the rows and calls
    ``tx.checkpoint``, which may raise ``RunCancelled``). A block whose sample reports a ``STOP_STATUSES`` letter ends
    the hold."""
    driver = tx.driver
    set_levels(tx, outputs, previous)
    driver.set_format(1, 1)
    result = HoldResult()
    previous: float | None = None
    for index, h_bias in enumerate(hold_chunks(seconds, monitor.period)):
        if previous is None:  # the setup is built only when it is sent: once, and when the block length changes
            driver.sampling_setup(monitor.setup(h_bias))
        elif h_bias != previous:
            driver.sampling_update(monitor.setup(h_bias), timing=True, sources=False)
        previous = h_bias
        drain_or_raise(tx, f"{label} block {index + 1}")
        block = driver.execute_and_read(expected_points=monitor.width, timeout_s=monitor.timeout_s(h_bias))
        result.blocks.append(block)
        on_block(index, h_bias, block)
        flagged = flagged_statuses([block])
        if flagged:
            result.stopped = True
            result.reason = f"{label} block {index + 1} reported status {','.join(flagged)}"
            break
    return result
