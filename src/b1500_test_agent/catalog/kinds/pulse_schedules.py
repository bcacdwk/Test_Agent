"""Schedules of kind ``pulse_read`` (blueprint v2 2.7 "per cycle/amplitude x width grid/retention schedule"; 3.3 rows
``fefet.pulse_write_read``, ``fefet.switching_kinetics``, ``fefet.endurance``, ``fefet.retention``): which pulse
operations a plan runs, in which order, and where its reads, cycling bursts and retention holds go. Pure (no I/O):
the kind compiles the operations this module requests (``Schedule.op_requests``) and runs the steps it lists
(``build_steps``). Recipe parameters are read by name; every bound below is a compile error, never a silent clip.

**Schedules** (parameter ``schedule``):

- ``cycles`` (WP9.4): the ``sequence`` (``erase_program``, ``program_erase``, ``program``, ``erase``) repeated
  ``cycles`` times, a read after every operation. ``cycle_reads`` (WP9.5, endurance) chooses where the reads go:
  ``every`` (default: every cycle, ``cycles`` at most ``MAX_CYCLES``), ``log`` (checkpoints at log-spaced cumulative
  cycle counts ``round(10^(k/reads_per_decade))`` below ``cycles``, then ``cycles``) or ``list`` (the cumulative
  counts ``read_cycles``, then ``cycles`` when later). At a checkpoint ``c`` the sequence runs once with its reads (that
  is cycle ``c``); the ``c - c_prev - 1`` cycles before it run as **bipolar cycling bursts** of the HV-SPGU (one
  period = the sequence's first operation's pulse, then the other operation's pulse half a ``cycle_period`` later;
  bursts of at most ``MAX_COUNT`` periods each, so ``cycles`` reaches ``MAX_STRESS_CYCLES``). Endurance needs a
  two-operation sequence.
- ``grid`` (switching kinetics): ``amplitudes`` (V) x ``widths`` (s) of the sequence's second operation (the grid
  operation, e.g. ``program`` for ``erase_program``) after a reset by its first operation at the role's settings.
  ``grid_mode`` ``reset`` (default): per point (amplitude-major, both lists in the given order) reset, optional reset
  read (``reset_read``, default true), one grid pulse, read; ``ispp`` (incremental step pulse programming): per width
  one reset (and reset read), then the amplitudes in order (strictly increasing magnitude) cumulatively, a read after
  each. The grid points are stored with the program (``GridPoint``: ``cycle`` = the point's index from 1, level,
  width); the reads of a point carry its index as ``cycle``.
- ``retention``: each operation of the sequence writes its state once; reads follow at ``read_times`` after the write
  (``first_read`` x 10^(k/reads_per_decade) below ``retention_time``, then ``retention_time``; on the 10 ms grid),
  the read SMUs holding their pulse levels in instrument-timed ``MM 10`` hold blocks between reads
  (``blocks.hold_bias``: the simulator ages the device in virtual time exactly as long as the hardware would). Read
  ``k`` of a state carries ``cycle`` = k and ``t_s`` = its time after the write (the cumulative hold time; the reads
  interrupt that clock).

``precycles`` (any schedule, default 0): bipolar cycling bursts before the first read (wake-up of a pristine film).
At most ``MAX_READS`` reads per plan.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Final, Literal, Protocol

from pydantic import Field

from b1500_test_agent.catalog.blocks import Monitor, hold_chunks
from b1500_test_agent.catalog.kinds.pulse_sources import MAX_COUNT, OpName, OpRequest, other_op, setting_op
from b1500_test_agent.catalog.kinds.stress_measure import log_times
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.recipe import RoleSpec

__all__ = [
    "CYCLE_READS",
    "GRID_MODES",
    "MAX_CYCLES",
    "MAX_READS",
    "MAX_STRESS_CYCLES",
    "SCHEDULES",
    "SEQUENCES",
    "GridPoint",
    "ReadStep",
    "Schedule",
    "build_steps",
    "burst_counts",
    "cycling_key",
    "log_cycles",
    "parse_schedule",
]

SCHEDULES: Final = ("cycles", "grid", "retention")
CYCLE_READS: Final = ("every", "log", "list")
GRID_MODES: Final = ("reset", "ispp")

SEQUENCES: Final[dict[str, tuple[OpName, ...]]] = {
    "erase_program": ("erase", "program"), "program_erase": ("program", "erase"),
    "program": ("program",), "erase": ("erase",),
}  # fmt: skip
"""The operations of one cycle (each followed by a read), the writes of a retention plan, or a grid's reset and grid
operation."""

MAX_CYCLES: Final = 200
"""Most cycles of a plan that reads every cycle (at most 401 reads)."""

MAX_STRESS_CYCLES: Final = 1_000_000_000
"""Most cycles of an endurance plan (``cycle_reads`` log or list): bursts of at most ``MAX_COUNT`` periods each (the
HV-SPGU's ``SPRM 1`` count limit); the duration bound (R-RUN-02, ``max_async_run_s``) limits it further."""

MAX_READS: Final = 401
"""Most reads of one plan (reference read included)."""

MAX_GRID_POINTS: Final = 200
MAX_LIST: Final = 50
"""Most values of ``amplitudes``, ``widths`` or ``read_cycles``."""

MAX_READS_PER_DECADE: Final = 20
MIN_READ_S: Final = 0.02
"""Shortest retention read time (s): one hold block of the monitor interval."""

SCHEDULE_PARAM, SEQUENCE_PARAM, CYCLES_PARAM = "schedule", "sequence", "cycles"
CYCLE_READS_PARAM, READS_PER_DECADE_PARAM, READ_CYCLES_PARAM = "cycle_reads", "reads_per_decade", "read_cycles"
CYCLE_PERIOD_PARAM, PRECYCLES_PARAM = "cycle_period", "precycles"
AMPLITUDES_PARAM, WIDTHS_PARAM, GRID_MODE_PARAM, RESET_READ_PARAM = "amplitudes", "widths", "grid_mode", "reset_read"
RETENTION_TIME_PARAM, FIRST_READ_PARAM = "retention_time", "first_read"
INITIAL_READ_PARAM, SETTLE_PARAM = "initial_read", "settle"

CYCLING_PHASE: Final = "cycling"
"""Phase name of the cycling bursts (``routes_by_phase``, checkpoints, route log)."""

RETENTION_PHASE: Final = "retention"
"""Checkpoint phase of a retention hold block."""


# -- parameter helpers -----------------------------------------------------------------------------------------------


def _value(params: Mapping[str, Quantity], name: str, default: Any = None) -> Any:
    quantity = params.get(name)
    return default if quantity is None else quantity.value


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _integer(value: object, what: str, low: int, high: int) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CompileError(f"{what} must be an integer {low} to {high}, got {value!r}")
    return value


def _choice(params: Mapping[str, Quantity], name: str, choices: Sequence[str], default: str) -> str:
    value = _value(params, name, default)
    if value not in choices:
        raise CompileError(f"{name} must be one of {list(choices)}, got {value!r}")
    return str(value)


def _numbers(params: Mapping[str, Quantity], name: str) -> list[float]:
    raw = _value(params, name)
    if not isinstance(raw, list) or not raw:
        raise CompileError(f"parameter {name} (a non-empty list) is required by this schedule")
    if len(raw) > MAX_LIST:
        raise CompileError(f"{name} lists {len(raw)} values; at most {MAX_LIST}")
    return [_number(v, f"{name}[{i}]") for i, v in enumerate(raw)]


def log_cycles(total: int, per_decade: int) -> list[int]:
    """Checkpoint cycle counts ``round(10^(k/per_decade))`` below ``total`` (distinct, increasing), then ``total``."""
    counts: list[int] = []
    k = 0
    while True:
        c = round(10.0 ** (k / per_decade))
        if c >= total:
            break
        if not counts or c > counts[-1]:
            counts.append(c)
        k += 1
    return [*counts, total]


def burst_counts(cycles: int) -> list[int]:
    """``cycles`` bipolar cycles as bursts of at most ``MAX_COUNT`` periods (empty for 0)."""
    full, rest = divmod(max(cycles, 0), MAX_COUNT)
    return [MAX_COUNT] * full + ([rest] if rest else [])


def cycling_key(count: int) -> str:
    """Key of the cycling burst of ``count`` periods in the compiled ``ops``."""
    return f"{CYCLING_PHASE}_{count}"


# -- the schedule ----------------------------------------------------------------------------------------------------


class GridPoint(StrictModel):
    """One point of the switching-kinetics grid: its index ``cycle`` (from 1; the reads of the point carry it), the
    grid operation's ``op`` key, ``level`` (V, peak set level) and ``width`` (s), and its ``row`` (ISPP: the width row;
    reset: the amplitude index)."""

    cycle: int = Field(ge=1)
    op: str
    level: float
    width: float = Field(gt=0)
    row: int = Field(ge=0)


@dataclass
class Schedule:
    """A parsed schedule (module docstring): what ``parse_schedule`` read; ``op_requests`` lists the operations the
    plan runs, in the order they are compiled and stored."""

    kind: Literal["cycles", "grid", "retention"]
    sequence: list[OpName]
    cycles: int = 1
    cycle_reads: Literal["every", "log", "list"] = "every"
    checkpoints: list[int] = field(default_factory=list)
    cycle_period: float | None = None
    grid: list[GridPoint] = field(default_factory=list)
    grid_mode: Literal["reset", "ispp"] = "reset"
    reset_read: bool = True
    read_times: list[float] = field(default_factory=list)
    precycles: int = 0
    initial_read: bool = True

    @property
    def grid_op(self) -> OpName | None:
        """The grid operation (the sequence's second): ``None`` outside the grid schedule."""
        return self.sequence[1] if self.kind == "grid" else None

    def bursts(self) -> list[int]:
        """Every cycling burst of the plan in run order (pre-cycling, then the gaps before the checkpoints)."""
        out = burst_counts(self.precycles)
        previous = 0
        for checkpoint in self.checkpoints:
            out += burst_counts(checkpoint - previous - 1)
            previous = checkpoint
        return out

    def reads(self) -> int:
        """Reads of the plan (reference read included)."""
        first = 1 if self.initial_read else 0
        if self.kind == "cycles":
            per = self.checkpoints if self.cycle_reads != "every" else range(self.cycles)
            return first + len(per) * len(self.sequence)
        if self.kind == "grid":
            resets = len(self.grid) if self.grid_mode == "reset" else len({p.row for p in self.grid})
            return first + len(self.grid) + (resets if self.reset_read else 0)
        return first + len(self.sequence) * len(self.read_times)

    def op_requests(self, role: str, spec: RoleSpec, params: dict[str, Quantity]) -> list[OpRequest]:
        """The operations the plan runs (``OpRequest``s, stored in this order): the sequence's operations from the
        role's settings (``program`` before ``erase``), the grid points, then one cycling burst per distinct count.

        Raises:
            CompileError: If a setting the schedule needs is missing (``pulse_sources.setting_op``).
        """
        uses: dict[OpName, int] = {}
        if self.kind == "cycles":
            per = len(self.checkpoints) if self.cycle_reads != "every" else self.cycles
            uses = {name: per for name in self.sequence}
        elif self.kind == "grid":
            reset = self.sequence[0]
            uses = {reset: len(self.grid) if self.grid_mode == "reset" else len({p.row for p in self.grid})}
        else:
            uses = {name: 1 for name in self.sequence}
        out = [setting_op(role, spec, params, name, runs=uses[name]) for name in ("program", "erase") if name in uses]
        out += [OpRequest(key=p.op, name=self.sequence[1], level=p.level, width=p.width) for p in self.grid]
        counts: dict[int, int] = {}
        for count in self.bursts():
            counts[count] = counts.get(count, 0) + 1
        if counts:
            first = self.sequence[0]
            a = setting_op(role, spec, params, first)
            b = setting_op(role, spec, params, other_op(first))
            out += [OpRequest(key=cycling_key(count), name=first, level=a.level, width=a.width, runs=runs,
                              count=count, period=self.cycle_period, then=(b.level, b.width))
                    for count, runs in counts.items()]
        return out


def _sequence(params: Mapping[str, Quantity]) -> list[OpName]:
    return list(SEQUENCES[_choice(params, SEQUENCE_PARAM, list(SEQUENCES), "erase_program")])


def _cycle_period(params: Mapping[str, Quantity], why: str) -> float:
    value = _value(params, CYCLE_PERIOD_PARAM)
    if value is None:
        raise CompileError(f"parameter {CYCLE_PERIOD_PARAM} (s, the period of one bipolar cycle) is required for "
                           f"{why}")
    period = _number(value, CYCLE_PERIOD_PARAM)
    if period <= 0:
        raise CompileError(f"{CYCLE_PERIOD_PARAM} must be positive, got {period:g}")
    return period


def _per_decade(params: Mapping[str, Quantity]) -> int:
    return _integer(_value(params, READS_PER_DECADE_PARAM, 3), READS_PER_DECADE_PARAM, 1, MAX_READS_PER_DECADE)


def parse_schedule(params: dict[str, Quantity], *, source: str) -> Schedule:
    """The schedule a plan's parameters ask for (module docstring); ``source`` is the pulse source family (cycling
    bursts need the HV-SPGU, ``spgu``).

    Raises:
        CompileError: For an unknown schedule or choice, a bound exceeded, a schedule that needs a two-operation
            sequence, cycling with another source, or too many reads.
    """
    kind = _choice(params, SCHEDULE_PARAM, SCHEDULES, "cycles")
    sequence = _sequence(params)
    initial = _value(params, INITIAL_READ_PARAM, True)
    if not isinstance(initial, bool):
        raise CompileError(f"{INITIAL_READ_PARAM} must be a bool, got {initial!r}")
    precycles = _integer(_value(params, PRECYCLES_PARAM, 0), PRECYCLES_PARAM, 0, MAX_STRESS_CYCLES)
    out = Schedule(kind=kind, sequence=sequence, precycles=precycles, initial_read=initial)  # type: ignore[arg-type]
    cycles = _value(params, CYCLES_PARAM, 1)
    if kind != "cycles" and cycles not in (1, 1.0):
        raise CompileError(f"{CYCLES_PARAM} applies to schedule cycles only (schedule {kind} got {cycles!r})")
    if kind == "cycles":
        _cycles(out, params, cycles)
    elif kind == "grid":
        _grid(out, params)
    else:
        _retention(out, params)
    needs_cycling = bool(out.bursts())
    if needs_cycling:
        out.cycle_period = _cycle_period(params, "the bipolar cycling bursts (endurance gaps, precycles)")
        if source != "spgu":
            raise CompileError("bipolar cycling bursts (endurance gaps between checkpoints, precycles) need the "
                               "HV-SPGU source (a pgu pulse role); an SMU pulses once per trigger")
    reads = out.reads()
    if reads > MAX_READS:
        raise CompileError(f"the plan has {reads} reads, more than {MAX_READS}; use fewer cycles, checkpoints, grid "
                           "points or reads per decade")
    return out


def _cycles(out: Schedule, params: dict[str, Quantity], cycles: object) -> None:
    out.cycle_reads = _choice(params, CYCLE_READS_PARAM, CYCLE_READS, "every")  # type: ignore[assignment]
    if out.cycle_reads == "every":
        out.cycles = _integer(cycles, CYCLES_PARAM, 1, MAX_CYCLES)
        return
    out.cycles = _integer(cycles, CYCLES_PARAM, 1, MAX_STRESS_CYCLES)
    if len(out.sequence) != 2:
        raise CompileError(f"{CYCLE_READS_PARAM} {out.cycle_reads} (endurance) cycles program and erase: it needs a "
                           f"two-operation sequence (erase_program or program_erase), got {'_'.join(out.sequence)}")
    if out.cycle_reads == "log":
        out.checkpoints = log_cycles(out.cycles, _per_decade(params))
        return
    listed = _numbers(params, READ_CYCLES_PARAM)
    counts = [_integer(v, f"{READ_CYCLES_PARAM}[{i}]", 1, out.cycles) for i, v in enumerate(listed)]
    if any(b <= a for a, b in pairwise(counts)):
        raise CompileError(f"{READ_CYCLES_PARAM} must increase strictly, got {listed}")
    out.checkpoints = counts if counts[-1] == out.cycles else [*counts, out.cycles]


def _grid(out: Schedule, params: dict[str, Quantity]) -> None:
    if len(out.sequence) != 2:
        raise CompileError("schedule grid resets with the sequence's first operation and pulses the grid with the "
                           f"second: it needs erase_program or program_erase, got {'_'.join(out.sequence)}")
    amplitudes = _numbers(params, AMPLITUDES_PARAM)
    widths = _numbers(params, WIDTHS_PARAM)
    if any(w <= 0 for w in widths):
        raise CompileError(f"{WIDTHS_PARAM} must be positive, got {widths}")
    if any(a == 0 for a in amplitudes):
        raise CompileError(f"{AMPLITUDES_PARAM} must not contain 0 V, got {amplitudes}")
    if len(amplitudes) * len(widths) > MAX_GRID_POINTS:
        raise CompileError(f"{len(amplitudes)} amplitudes x {len(widths)} widths exceed {MAX_GRID_POINTS} grid points")
    out.grid_mode = _choice(params, GRID_MODE_PARAM, GRID_MODES, "reset")  # type: ignore[assignment]
    reset_read = _value(params, RESET_READ_PARAM, True)
    if not isinstance(reset_read, bool):
        raise CompileError(f"{RESET_READ_PARAM} must be a bool, got {reset_read!r}")
    out.reset_read = reset_read
    if out.grid_mode == "reset":
        pairs = [(row, a, w) for row, a in enumerate(amplitudes) for w in widths]
    else:
        if any(abs(b) <= abs(a) or (a > 0) != (b > 0) for a, b in pairwise(amplitudes)):
            raise CompileError(f"{GRID_MODE_PARAM} ispp steps the amplitude up: {AMPLITUDES_PARAM} must have one sign "
                               f"and strictly increasing magnitude, got {amplitudes}")
        pairs = [(row, a, w) for row, w in enumerate(widths) for a in amplitudes]
    out.grid = [GridPoint(cycle=i, op=f"g{i}", level=a, width=w, row=row) for i, (row, a, w) in enumerate(pairs, 1)]


def _retention(out: Schedule, params: dict[str, Quantity]) -> None:
    settle = _number(_value(params, SETTLE_PARAM, 0.0), SETTLE_PARAM)
    if settle != 0:
        raise CompileError(f"schedule retention times its reads from the write ({FIRST_READ_PARAM}); {SETTLE_PARAM} "
                           f"must be 0, got {settle:g}")
    raw = _value(params, RETENTION_TIME_PARAM)
    if raw is None:
        raise CompileError(f"parameter {RETENTION_TIME_PARAM} (s, the last read after each write) is required")
    total = _number(raw, RETENTION_TIME_PARAM)
    first = _number(_value(params, FIRST_READ_PARAM, 1.0), FIRST_READ_PARAM)
    if first < MIN_READ_S or total < first:
        raise CompileError(f"{FIRST_READ_PARAM} must be at least {MIN_READ_S:g} s and at most {RETENTION_TIME_PARAM} "
                           f"({total:g} s), got {first:g}")
    out.read_times = log_times(first, total, _per_decade(params))  # on the 10 ms hold grid


# -- steps -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadStep:
    """One checkpoint step of the run: a read, a pulse operation (``op`` = its ops key), a cycling burst or a retention
    hold (``seconds``); its table ``cycle``; its ``phase`` (reads and pulses: ``read`` for the reference read, else the
    operation; bursts ``cycling``; holds ``retention``); its checkpoint units ``chunks``; a retention read's ``t_s``."""

    index: int
    action: Literal["read", "pulse", "burst", "hold"]
    cycle: int
    phase: str
    chunks: int = 1
    op: str = ""
    seconds: float = 0.0
    t_s: float | None = None


class ScheduledProgram(Protocol):
    """What ``build_steps`` reads of a compiled ``pulse_read`` program."""

    schedule: str
    sequence: list[OpName]
    cycles: int
    cycle_reads: str
    checkpoints: list[int]
    grid: list[GridPoint]
    grid_mode: str
    reset_read: bool
    read_times: list[float]
    precycles: int
    initial_read: bool
    monitor: Monitor | None

    @property
    def settle_chunks(self) -> int: ...

    def op_chunks(self, key: str) -> int: ...


def build_steps(p: ScheduledProgram) -> list[ReadStep]:
    """Every checkpoint step of ``p`` in run order (module docstring)."""
    out: list[ReadStep] = []

    def add(action: str, cycle: int, phase: str, **kw: Any) -> None:
        out.append(ReadStep(len(out), action, cycle, phase, **kw))  # type: ignore[arg-type]

    def pulse(key: str, cycle: int, phase: str) -> None:
        add("pulse", cycle, phase, op=key, chunks=p.op_chunks(key) + p.settle_chunks)

    def bursts(count: int, cycle: int) -> None:
        for n in burst_counts(count):
            add("burst", cycle, CYCLING_PHASE, op=cycling_key(n), chunks=p.op_chunks(cycling_key(n)))

    bursts(p.precycles, 0)
    if p.initial_read:
        add("read", 0, "read")
    if p.schedule == "cycles":
        _cycle_steps(p, pulse, bursts, add)
    elif p.schedule == "grid":
        reset, grid_op = p.sequence[0], p.sequence[1]
        row = None
        for point in p.grid:
            if p.grid_mode == "reset" or point.row != row:
                pulse(reset, point.cycle, reset)
                if p.reset_read:
                    add("read", point.cycle, reset)
                row = point.row
            pulse(point.op, point.cycle, grid_op)
            add("read", point.cycle, grid_op)
    else:
        assert p.monitor is not None
        for name in p.sequence:
            pulse(name, 0, name)
            previous = 0.0
            for k, t in enumerate(p.read_times, 1):
                seconds = round(t - previous, 2)
                add("hold", k, RETENTION_PHASE, seconds=seconds, chunks=len(hold_chunks(seconds, p.monitor.period)))
                add("read", k, name, t_s=t)
                previous = t
    return out


def _cycle_steps(p: ScheduledProgram, pulse: Callable[[str, int, str], None], bursts: Callable[[int, int], None],
                 add: Callable[..., None]) -> None:
    if p.cycle_reads == "every":
        for cycle in range(1, p.cycles + 1):
            for name in p.sequence:
                pulse(name, cycle, name)
                add("read", cycle, name)
        return
    previous = 0
    for checkpoint in p.checkpoints:
        bursts(checkpoint - previous - 1, checkpoint)
        for name in p.sequence:
            pulse(name, checkpoint, name)
            add("read", checkpoint, name)
        previous = checkpoint
