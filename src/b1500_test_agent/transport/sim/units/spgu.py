"""HV-SPGU unit of the simulator (blueprint v2 4.1, 4.2 "SPGU output", 4.3 faults ``spgu_no_stop``,
``spgu_load_mismatch``).

``SpguUnit`` is a mixin of ``SimInstrument``. Manual (Programming Guide Ed. 15, physical PDF pages): SPGU module
141-151 (printed 2-53 to 2-63), ``ALS``/``ALW`` 360-362, ``CORRSER?`` 385-386, ``ODSW`` 478-479, ``SER`` 507,
``SIM`` 508, ``SPM`` 510-511, ``SPP`` 511, ``SPPER`` 512, ``SPRM`` 512-513, ``SPST?`` 513-514, ``SPT`` 514-515,
``SPUPD`` 515-516, ``SPV`` 516-517, ``SRP`` 518, ``STGP`` 523-524; initial settings Table 2-12 (179); operation errors
2000-2204 (590-593). Behaviour:

- **Settings** (per process, like the SMU setup; power-on, ``*RST`` and a device clear restore Table 2-12): PG mode,
  period 1 us, output operation mode **free run** (``SPRM 0``: a ``SRP`` without ``SPRM`` runs until ``SPP``),
  two-level pulses from source 1 (delay 0, width 100 ns, transitions 20 ns, base -0.5 V, peak 0.5 V), ``SER`` 50 Ohm,
  pulse switch disabled, trigger off, no ALWG data. Setting commands store; ``SPM``/``SPT``/``SPV`` need ``SIM 0``
  (error 2003), ``ALW``/``ALS`` need ``SIM 1`` (2004); range errors as listed in the manual (2101-2134, 2151-2158).
- **Output**: ``CN`` -> 0 V; ``SPUPD`` (output switch on, else error 200) checks the setup (2111-2114 against the
  period, 2106 three-level sum, 2107 open-load level above 40 V for the ``SER``, ALWG data present 2151/2155) and puts
  the base level (ALWG: the initial level) on the channel; ``SRP`` starts every set-up pulse channel; ``SPP``, the end
  of the count (``count x period``; ALWG ``count`` sequences with the 50 ns setup delays) or duration, a closed output
  switch of every running channel, ``SIM``/``SPRM``/``SPUPD``/``SRP``/``CORRSER?`` stop it (PG PDF 142 lists the
  stop conditions; ``DZ`` and ``AB`` are not among them and do not stop it). ``SPST?`` answers 1 while a run is active.
  Time is the instrument's virtual clock; a run persists across processes as ``spgu_output_active`` +
  ``spgu_remaining_s`` (another process sees its timing, not its levels).
- **Level at the DUT**: ``V_dut = V_set (SER + 50) / SER x R / (R + 50)`` for a load ``R``: solved on the circuit
  (the channel's terminal current at the trial voltage, the other channels at their levels), exactly ``V_set (SER +
  50) / SER`` for an unwired channel (open-load doubling at 50 Ohm), or the ``spgu_load_mismatch`` load. The static
  level of an output-on channel takes part in every circuit evaluation (``SimInstrument._on_levels``: no compliance),
  and a run drives the stateful devices segment by segment in virtual time (``spgu_output.Run``; FeFET switching
  kinetics, retention, wake-up/fatigue of the WP5.9 ``ferro`` model).
- **``CORRSER?``** stops a running output, outputs one period of the set-up channels, answers the load the channel
  sees (``loadZ``, 0.1 Ohm to 1 MOhm) and the voltage it measured at the peak level (``+n.nnnnnnE+nn``; TODO(verify)
  the format at L7), sets ``SER`` with mode 1, and takes ``max(period, delay + interval x count)``; error 2204 below
  1 V.
- **Faults**: ``spgu_no_stop`` keeps the run alive through every stop condition but the ``SPP`` after its
  ``spp_ignored`` ignored ones; ``spgu_load_mismatch`` replaces the load (see above).
- **Spy**: ``spgu_runs`` records every started run (set levels, ``SER``, open-load and delivered maxima per channel)
  for the safety tests' global invariant.

TODO(verify) at bring-up L0/L7 (blueprint 7.6 items 3, 9): what ``SPST?`` answers without an SPGU, the effect of
``DZ`` on a running output, the ``CORRSER?`` number format, and the delivered level into real loads (ATV-20).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from b1500_test_agent.models.measurement import CHANNEL_NUMBERS
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.state import ChannelState
from b1500_test_agent.transport.sim.units.base import FOREVER, SPGU_TYPES, handles
from b1500_test_agent.transport.sim.units.spgu_output import (
    Pattern,
    Piece,
    Run,
    Source,
    alwg_pieces,
    decode_patterns,
    decode_sequence,
    merge,
    pg_pieces,
)

OUTPUT_OHM = 50.0
"""SPGU output impedance (PG PDF 141)."""

MAX_OPEN_V = 40.0
"""Largest open-load output level (PG PDF 141)."""

INITIAL_PERIOD_S = 1e-6
INITIAL_LOAD_OHM = 50.0
CORRSER_MIN_V = 1.0
"""Smallest output level for the terminal-voltage measurement (error 2204; PG PDF 142, 593)."""


@dataclass
class SpguChannelSetup:
    """The stored setup of one SPGU channel (canonical number)."""

    mode: int = 1
    sources: dict[int, Source] = field(default_factory=lambda: {1: Source(), 2: Source()})
    dc: float = 0.0
    ser: float = INITIAL_LOAD_OHM
    switch: tuple[int, int, float, float] = (0, 0, 0.0, 1e-7)
    trigger: int = 0
    patterns: list[Pattern] | None = None
    applied_on: ChannelState | None = None
    """The output state object the last ``SPUPD`` applied the setup to: ``CL``/``CN``, ``*RST`` and loading another
    process's state replace it, so a channel must be set up again before ``SRP`` starts it."""


@dataclass(frozen=True)
class SpguChannelRecord:
    """One channel of a started run (safety spy): largest |set level|, ``SER``, the open-load level that implies and
    the largest |level| delivered to the DUT."""

    max_set_v: float
    ser: float
    open_load_v: float
    delivered_v: float


@dataclass(frozen=True)
class SpguRunRecord:
    """A started SPGU output (safety spy): mode, start, end (``None`` = free run), period/sequence time, channels."""

    seq: int
    mode: str
    start_s: float
    end_s: float | None
    unit_s: float
    channels: dict[int, SpguChannelRecord]


def _within(value: float, low: float, high: float) -> bool:
    return low * (1 - 1e-12) <= value <= high * (1 + 1e-12)


class SpguUnit:
    """SPGU FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    _spgu_active_run: Run | None = None

    # -- settings and state ------------------------------------------------------------------------------------------

    def _reset_spgu_settings(self) -> None:
        """Table 2-12 (PDF 179): PG mode, 1 us period, free run, default sources, SER 50 Ohm, no ALWG data."""
        self._spgu_mode = 0
        self._spgu_period = INITIAL_PERIOD_S
        self._spgu_run_mode = 0
        self._spgu_condition: float | None = None
        self._spgu: dict[int, SpguChannelSetup] = {}
        self._spgu_sequence: list[tuple[int, int]] | None = None
        self._spgu_pending: tuple[str, int | None, int] | None = None

    def _reset_spgu_state(self) -> None:
        """Power-on, ``*RST``, device clear: the output stops (unless ``spgu_no_stop`` holds it)."""
        if self.faults.spgu_stuck() and self.state.spgu_output_active:
            return
        self._spgu_active_run = None
        self.state.spgu_output_active = False
        self.state.spgu_remaining_s = None

    @property
    def spgu_runs(self) -> list[SpguRunRecord]:
        """Every SPGU output started by this instrument object, oldest first (safety spy)."""
        runs = self.__dict__.get("_spgu_runs")
        if runs is None:
            runs = self.__dict__["_spgu_runs"] = []
        return runs

    def _spgu_setup(self, channel: int) -> SpguChannelSetup:
        return self._spgu.setdefault(channel, SpguChannelSetup())

    def _spgu_channel(self, arg: str) -> int:
        """An SPGU channel argument (canonical number): error 121 for a bad number, 2000 without an SPGU there."""
        number = flex.integer(arg)
        if number not in CHANNEL_NUMBERS:
            raise flex.FlexError(flex.ERR_CHANNEL_NUMBER, f"channel {number}")
        channel = canonical_channel(number)
        if self._channel_type(channel) not in SPGU_TYPES:
            raise flex.FlexError(flex.ERR_SPGU_MODULE, f"channel {number}")
        self.state.channels.setdefault(channel, ChannelState())
        return channel

    def _spgu_now(self) -> float:
        now = self._now()
        return self.clock if now == FOREVER else now

    def _spgu_is(self, channel: int) -> bool:
        return self._channel_type(channel) in SPGU_TYPES

    def spgu_output_active(self) -> bool:
        """``SPST?`` as of the current virtual time (the run synchronised first)."""
        self._spgu_sync()
        return self.state.spgu_output_active

    # -- levels at the DUT ------------------------------------------------------------------------------------------

    def _spgu_smu_levels(self) -> dict[int, float]:
        """Programmed levels of the voltage-forcing SMUs (the base of the SPGU load solve; current-forcing SMUs, whose
        voltage follows from the load, are left floating there)."""
        return {ch: st.voltage for ch, st in self.state.channels.items()
                if st.output_on and st.mode == "V" and self._is_smu(ch)}

    def _spgu_wired(self, channel: int) -> bool:
        """True when a DUT terminal reaches ``channel`` now (wired to it, or through a selector output routed to it,
        WP9.2); otherwise the output sees an open load."""
        return self.circuit.wired_to(channel)

    def _spgu_delivered(self, channel: int, v_set: float, ser: float, base: dict[int, float]) -> float:
        """The level at the DUT for set level ``v_set`` (module docstring)."""
        v_open = v_set * (ser + OUTPUT_OHM) / ser
        if v_open == 0.0:
            return 0.0
        load = self.faults.spgu_load(channel)
        if load is not None:
            return v_open * load / (load + OUTPUT_OHM)
        if not self._spgu_wired(channel):
            return v_open

        def excess(v: float) -> float:
            return (v_open - v) / OUTPUT_OHM - self.circuit.channel_currents({**base, channel: v}).get(channel, 0.0)

        lo, hi = sorted((0.0, v_open))
        g_lo, g_hi = excess(lo), excess(hi)
        if g_lo == 0.0 or g_hi == 0.0 or (g_lo > 0) == (g_hi > 0):
            return lo if abs(g_lo) <= abs(g_hi) else hi
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            g_mid = excess(mid)
            if (g_mid > 0) == (g_lo > 0):
                lo, g_lo = mid, g_mid
            else:
                hi = mid
            if hi - lo <= 1e-13 * abs(v_open):
                break
        return 0.5 * (lo + hi)

    def _spgu_connected_idle(self, setup: SpguChannelSetup) -> bool:
        """An enabled, normally open pulse switch leaves an idle output floating."""
        state, normal = setup.switch[0], setup.switch[1]
        return state == 0 or normal == 1

    def _spgu_levels(self) -> dict[int, float]:
        """Static levels at the DUT of the output-on SPGU channels (for ``SimInstrument._on_levels``)."""
        levels: dict[int, float] = {}
        base: dict[int, float] | None = None
        for channel, st in self.state.channels.items():
            if not st.output_on or not self._spgu_is(channel):
                continue
            setup = self._spgu_setup(channel)
            if not self._spgu_connected_idle(setup):
                continue
            if st.voltage == 0.0:
                levels[channel] = 0.0
                continue
            if base is None:
                base = self._spgu_smu_levels()
            levels[channel] = self._spgu_delivered(channel, st.voltage, setup.ser, base)
        return levels

    # -- runs -------------------------------------------------------------------------------------------------------

    def _spgu_current(self) -> Run | None:
        """The active run, reconciled with the persisted state (another process may have started or stopped it)."""
        state = self.state
        if not state.spgu_output_active:
            self._spgu_active_run = None
            return None
        run = self._spgu_active_run
        if run is None or run.seq != state.spgu_run:
            now = self._spgu_now()
            remaining = state.spgu_remaining_s
            run = Run(seq=state.spgu_run, start=now, end=None if remaining is None else now + remaining,
                      applied_until=now, foreign=True)
            self._spgu_active_run = run
        return run

    def _spgu_live(self, run: Run) -> set[int]:
        return {ch for ch in run.channels if self.state.channels.get(ch, ChannelState()).output_on}

    def _spgu_drive(self, run: Run, t0: float, t1: float, live: set[int]) -> None:
        if run.foreign or not self.circuit.dynamic:
            return
        applied, _, _ = self.dc_solution()  # the SMUs as they really drive (compliance, current forcing)
        smu = {ch: v for ch, v in applied.items() if not self._spgu_is(ch)}
        circuit = self.circuit
        counters = {name: dev for name, dev in circuit.stateful.items()
                    if hasattr(dev, "cycles") and callable(getattr(dev, "add_cycles", None))}

        def advance(dt: float, levels: dict[int, float]) -> None:
            circuit.advance(dt, {**smu, **levels})

        def cycles() -> dict[str, float]:
            return {name: float(dev.cycles) for name, dev in counters.items()}  # type: ignore[attr-defined]

        def add_cycles(extra: dict[str, float]) -> None:
            for name, count in extra.items():
                counters[name].add_cycles(count)  # type: ignore[attr-defined]

        run.apply(t0, t1, live, advance, circuit.export_state, cycles, add_cycles)
        self._sync_devices()

    def _spgu_sync(self, now: float | None = None) -> None:
        """Bring the active run up to ``now`` (default: the instrument's present time): drive the devices, end it at
        its count/duration or when every running output switch is off (``spgu_no_stop`` keeps it running)."""
        run = self._spgu_current()
        if run is None:
            return
        now = self._spgu_now() if now is None else now
        live = self._spgu_live(run)
        t_to = now if run.end is None else min(now, run.end)
        if t_to > run.applied_until:
            self._spgu_drive(run, run.applied_until, t_to, live)
            run.applied_until = t_to
        stuck = self.faults.spgu_stuck()
        if not run.foreign and not live and not stuck:
            self._spgu_end()
            return
        if run.end is not None and now >= run.end - (1e-12 + 4e-16 * abs(run.end)):  # float sums of periods
            if not stuck:
                self._spgu_end()
                return
            run.end = None
        self.state.spgu_remaining_s = None if run.end is None else max(0.0, run.end - now)

    def _spgu_end(self) -> None:
        self._spgu_active_run = None
        self.state.spgu_output_active = False
        self.state.spgu_remaining_s = None
        self._commit_dc()

    def _spgu_stop(self, *, spp: bool) -> None:
        """A stop condition: ``SPP`` (``spp``) or another (``SIM``, ``SPRM``, ``SPUPD``, ``SRP``, ``CORRSER?``)."""
        self._spgu_sync()
        if self._spgu_current() is None:
            return
        if self.faults.spgu_spp_ignored() if spp else self.faults.spgu_stuck():
            return
        self._spgu_end()

    def _spgu_static_set_level(self, setup: SpguChannelSetup) -> float:
        """The set level a set-up channel holds between pulses (PG: base, three-level: base1 + base2; DC; ALWG: the
        initial level of the sequence's first pattern)."""
        if self._spgu_mode == 1:
            assert setup.patterns is not None and self._spgu_sequence is not None
            return setup.patterns[self._spgu_sequence[0][0] - 1].initial
        if setup.mode == 0:
            return setup.dc
        used = [1] if setup.mode == 1 else [2] if setup.mode == 2 else [1, 2]
        return math.fsum(setup.sources[s].base for s in used)

    def _spgu_pieces(self, channel: int) -> tuple[list[Piece], float]:
        setup = self._spgu_setup(channel)
        if self._spgu_mode == 0 and setup.mode == 0:  # DC bias: one constant level
            return [Piece(0.0, self._spgu_period, setup.dc, setup.dc)], self._spgu_period
        if self._spgu_mode == 0:
            return pg_pieces(setup.mode, setup.sources, self._spgu_period, setup.switch), self._spgu_period
        assert setup.patterns is not None and self._spgu_sequence is not None
        return alwg_pieces(setup.patterns, self._spgu_sequence, setup.switch[0] == 1, setup.switch[1] == 1)

    def _spgu_build(self, channels: list[int]) -> tuple[float, list[tuple[float, dict[int, float | None]]],
                                                        dict[int, SpguChannelRecord]]:
        """Unit time, delivered segments and spy records of a run (or a ``CORRSER?`` period) of ``channels``."""
        pieces: dict[int, list[Piece]] = {}
        unit = 0.0
        for channel in channels:
            items, length = self._spgu_pieces(channel)
            pieces[channel] = items
            unit = max(unit, length)
        segments = merge(pieces, unit)
        base = self._spgu_smu_levels()
        cache: dict[tuple[int, float], float] = {}
        delivered_max: dict[int, float] = dict.fromkeys(channels, 0.0)
        out: list[tuple[float, dict[int, float | None]]] = []
        for dt, levels in segments:
            row: dict[int, float | None] = {}
            for channel, level in levels.items():
                if level is None:
                    row[channel] = None
                    continue
                key = (channel, level)
                if key not in cache:
                    cache[key] = self._spgu_delivered(channel, level, self._spgu_setup(channel).ser, base)
                row[channel] = cache[key]
                delivered_max[channel] = max(delivered_max[channel], abs(cache[key]))
            out.append((dt, row))
        records = {}
        for channel in channels:
            setup = self._spgu_setup(channel)
            set_max = max((abs(p.v0) for p in pieces[channel]), default=0.0)
            set_max = max(set_max, max((abs(p.v1) for p in pieces[channel]), default=0.0))
            records[channel] = SpguChannelRecord(max_set_v=set_max, ser=setup.ser,
                                                 open_load_v=set_max * (setup.ser + OUTPUT_OHM) / setup.ser,
                                                 delivered_v=delivered_max[channel])
        return unit, out, records

    def _spgu_ready_channels(self) -> list[int]:
        return sorted(ch for ch, setup in self._spgu.items()
                      if setup.applied_on is not None and self.state.channels.get(ch) is setup.applied_on
                      and setup.applied_on.output_on
                      and (self._spgu_mode == 1 or setup.mode != 0))

    def _spgu_end_time(self, now: float, unit: float) -> float | None:
        if self._spgu_run_mode == 0:
            return None
        if self._spgu_run_mode == 2:
            return now + float(self._spgu_condition or 0.0)
        count = int(self._spgu_condition or 1)
        if self._spgu_mode == 0:
            return now + count * unit
        assert self._spgu_sequence is not None
        wrap = self._spgu_sequence[-1][0] != self._spgu_sequence[0][0]
        body = unit - (5e-8 if wrap else 0.0)  # alwg_pieces ends with the wrap-around delay
        return now + count * body + (count - 1) * (unit - body)

    def _spgu_start(self) -> None:
        channels = self._spgu_ready_channels()
        if not channels:
            return
        now = self._spgu_now()
        unit, segments, records = self._spgu_build(channels)
        state = self.state
        state.spgu_run += 1
        end = self._spgu_end_time(now, unit)
        run = Run(seq=state.spgu_run, start=now, end=end, unit=unit, segments=segments, channels=set(channels),
                  applied_until=now)
        self._spgu_active_run = run
        state.spgu_output_active = True
        state.spgu_remaining_s = None if end is None else end - now
        self.spgu_runs.append(SpguRunRecord(seq=run.seq, mode="alwg" if self._spgu_mode else "pg", start_s=now,
                                            end_s=end, unit_s=unit, channels=records))

    # -- setup validation (SPUPD) --------------------------------------------------------------------------------------

    def _spgu_check_open_load(self, setup: SpguChannelSetup, levels: list[float]) -> None:
        extreme = max((abs(v) for v in levels), default=0.0)
        if extreme * (setup.ser + OUTPUT_OHM) / setup.ser > MAX_OPEN_V * (1 + 1e-12):
            raise flex.FlexError(flex.ERR_SPGU_AMPLITUDE, f"{extreme} V at SER {setup.ser} Ohm")

    def _spgu_check_setup(self, channel: int) -> None:
        setup = self._spgu_setup(channel)
        if self._spgu_mode == 1:
            if setup.patterns is None:
                raise flex.FlexError(flex.ERR_ALWG_NO_PATTERN, f"channel {channel}")
            if self._spgu_sequence is None:
                raise flex.FlexError(flex.ERR_ALWG_NO_SEQUENCE)
            if any(n > len(setup.patterns) for n, _ in self._spgu_sequence):
                raise flex.FlexError(flex.ERR_ALWG_INDEX, f"channel {channel} has {len(setup.patterns)} patterns")
            self._spgu_check_open_load(setup, [v for p in setup.patterns
                                               for v in (p.initial, *(level for _, level, _ in p.vectors))])
            return
        if setup.mode == 0:
            self._spgu_check_open_load(setup, [setup.dc])
            return
        period = self._spgu_period
        used = [1] if setup.mode == 1 else [2] if setup.mode == 2 else [1, 2]
        for s in used:
            source = setup.sources[s]
            if source.width > period - 1e-8 * (1 - 1e-9):
                raise flex.FlexError(flex.ERR_SPGU_WIDTH, f"width {source.width} s, period {period} s")
            if source.delay > period - 2e-8 * (1 - 1e-9):
                raise flex.FlexError(flex.ERR_SPGU_DELAY, f"delay {source.delay} s, period {period} s")
            if source.delay + source.width + source.trail / 0.8 > period * (1 + 1e-12):
                raise flex.FlexError(flex.ERR_SPGU_PERIOD_FIT, f"channel {channel} source {s}")
        levels = [0.0]
        for s in used:
            levels = [a + b for a in levels for b in (setup.sources[s].base, setup.sources[s].peak)]
        if setup.mode == 3 and max(abs(v) for v in levels) > MAX_OPEN_V:
            raise flex.FlexError(flex.ERR_SPGU_SUM, f"channel {channel}: {levels}")
        self._spgu_check_open_load(setup, levels)

    # -- handlers ---------------------------------------------------------------------------------------------------

    def _require_mode(self, mode: int) -> None:
        if self._spgu_mode != mode:
            raise flex.FlexError(flex.ERR_SPGU_NOT_PG if mode == 0 else flex.ERR_SPGU_NOT_ALWG)

    @handles("SIM")
    def _cmd_sim(self, cmd: flex.Command) -> None:
        """``SIM mode``: PG (0) or ALWG (1) for every SPGU; output-on SPGU channels go to 0 V (PG PDF 508)."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"SIM {mode}")
        self._spgu_stop(spp=False)
        self._spgu_mode = mode
        for channel, st in self.state.channels.items():
            if self._spgu_is(channel):
                self._spgu_setup(channel).applied_on = None
                if st.output_on and not self.faults.stuck(channel):
                    st.voltage = 0.0
        self._commit_dc()

    @handles("SPM")
    def _cmd_spm(self, cmd: flex.Command) -> None:
        """``SPM chnum,mode``: 0 DC, 1/2 two-level from source 1/2, 3 three-level (PG PDF 510-511)."""
        flex.arity(cmd, 2, 2)
        channel = self._spgu_channel(cmd.args[0])
        self._require_mode(0)
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1, 2, 3):
            raise flex.FlexError(flex.ERR_PARAMETER, f"SPM mode {mode}")
        self._spgu_setup(channel).mode = mode

    @handles("SPT")
    def _cmd_spt(self, cmd: flex.Command) -> None:
        """``SPT chnum,src,delay,width,leading[,trailing]`` (PG PDF 514-515); error 2111 when width < leading/0.8."""
        flex.arity(cmd, 5, 6)
        channel = self._spgu_channel(cmd.args[0])
        self._require_mode(0)
        src = flex.integer(cmd.args[1])
        if src not in (1, 2):
            raise flex.FlexError(flex.ERR_SPGU_SOURCE, f"src {src}")
        delay, width, lead = (flex.number(a) for a in cmd.args[2:5])
        trail = flex.number(cmd.args[5]) if len(cmd.args) > 5 else lead
        if delay < 0 or delay > 10.0:
            raise flex.FlexError(flex.ERR_SPGU_DELAY, f"delay {delay}")
        if not _within(width, 1e-8, 10.0):
            raise flex.FlexError(flex.ERR_SPGU_WIDTH, f"width {width}")
        if not (_within(lead, 8e-9, 0.4) and _within(trail, 8e-9, 0.4)):
            raise flex.FlexError(flex.ERR_SPGU_TRANSITION, f"leading {lead}, trailing {trail}")
        if width < lead / 0.8 * (1 - 1e-12):
            raise flex.FlexError(flex.ERR_SPGU_LEADING, f"width {width} < leading {lead} / 0.8")
        source = self._spgu_setup(channel).sources[src]
        source.delay, source.width, source.lead, source.trail = delay, width, lead, trail

    @handles("SPV")
    def _cmd_spv(self, cmd: flex.Command) -> None:
        """``SPV chnum,src,base[,peak]``: src 0 DC, 1/2 pulse source; +-40 V (error 2105; PG PDF 516-517)."""
        flex.arity(cmd, 3, 4)
        channel = self._spgu_channel(cmd.args[0])
        self._require_mode(0)
        src = flex.integer(cmd.args[1])
        if src not in (0, 1, 2):
            raise flex.FlexError(flex.ERR_SPGU_SOURCE, f"src {src}")
        base = flex.number(cmd.args[2])
        peak = flex.number(cmd.args[3]) if len(cmd.args) > 3 else base
        if abs(base) > MAX_OPEN_V or abs(peak) > MAX_OPEN_V:
            raise flex.FlexError(flex.ERR_SPGU_LEVEL, f"base {base}, peak {peak}")
        setup = self._spgu_setup(channel)
        if src == 0:
            setup.dc = base
        else:
            setup.sources[src].base, setup.sources[src].peak = base, peak

    @handles("SPPER")
    def _cmd_spper(self, cmd: flex.Command) -> None:
        """``SPPER period``: 2E-8 to 10 s (error 2103; PG PDF 512)."""
        flex.arity(cmd, 1, 1)
        period = flex.number(cmd.args[0])
        if not _within(period, 2e-8, 10.0):
            raise flex.FlexError(flex.ERR_SPGU_PERIOD, f"period {period}")
        self._spgu_period = period

    @handles("SPRM")
    def _cmd_sprm(self, cmd: flex.Command) -> None:
        """``SPRM mode[,condition]``: 0 free run, 1 count (error 2104), 2 duration (error 2115); a running output
        stops (PG PDF 512-513, 142)."""
        flex.arity(cmd, 1, 2)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER, f"SPRM {mode}")
        condition: float | None = None
        if mode == 1:
            condition = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
            if not 1 <= condition <= 1_000_000:
                raise flex.FlexError(flex.ERR_SPGU_COUNT, f"count {condition}")
        elif mode == 2:
            condition = flex.number(cmd.args[1]) if len(cmd.args) > 1 else 1e-6
            if not _within(condition, 1e-6, 31_556_926.0):
                raise flex.FlexError(flex.ERR_SPGU_DURATION, f"duration {condition}")
        self._spgu_stop(spp=False)
        self._spgu_run_mode, self._spgu_condition = mode, condition

    @handles("SER")
    def _cmd_ser(self, cmd: flex.Command) -> None:
        """``SER chnum,loadZ``: 0.1 Ohm to 1 MOhm (error 2101; PG PDF 507)."""
        flex.arity(cmd, 2, 2)
        channel = self._spgu_channel(cmd.args[0])
        load = flex.number(cmd.args[1])
        if not _within(load, 0.1, 1e6):
            raise flex.FlexError(flex.ERR_SPGU_LOAD, f"load {load}")
        self._spgu_setup(channel).ser = load
        self._commit_dc()

    @handles("ODSW")
    def _cmd_odsw(self, cmd: flex.Command) -> None:
        """``ODSW chnum,state[,normal[,delay,width]]`` (errors 2121-2123; PG PDF 478-479)."""
        flex.arity(cmd, 2, 5)
        if len(cmd.args) == 4:
            raise flex.FlexError(flex.ERR_TERMINATOR, "ODSW delay and width are given together")
        channel = self._spgu_channel(cmd.args[0])
        state = flex.integer(cmd.args[1])
        normal = flex.integer(cmd.args[2]) if len(cmd.args) > 2 else 0
        if state not in (0, 1) or normal not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"ODSW {state},{normal}")
        delay, width = (flex.number(cmd.args[3]), flex.number(cmd.args[4])) if len(cmd.args) == 5 else (0.0, 1e-7)
        if delay < 0 or delay > max(self._spgu_period - 1e-7, 0.0) * (1 + 1e-12):
            raise flex.FlexError(flex.ERR_SPGU_SWITCH_DELAY, f"delay {delay}")
        if width < 1e-7 * (1 - 1e-12):
            raise flex.FlexError(flex.ERR_SPGU_SWITCH_WIDTH, f"width {width}")
        if len(cmd.args) == 5 and delay + width > self._spgu_period * (1 + 1e-12):
            raise flex.FlexError(flex.ERR_SPGU_SWITCH_FIT, f"delay {delay} + width {width}")
        self._spgu_setup(channel).switch = (state, normal, delay, width)
        self._commit_dc()

    @handles("STGP")
    def _cmd_stgp(self, cmd: flex.Command) -> None:
        """``STGP chnum,state``: trigger output 0-3 (PG PDF 523-524); no effect on the DUT."""
        flex.arity(cmd, 2, 2)
        channel = self._spgu_channel(cmd.args[0])
        state = flex.integer(cmd.args[1])
        if state not in (0, 1, 2, 3):
            raise flex.FlexError(flex.ERR_PARAMETER, f"STGP {state}")
        self._spgu_setup(channel).trigger = state

    @handles("SPUPD")
    def _cmd_spupd(self, cmd: flex.Command) -> None:
        """``SPUPD chnum[,chnum...]``: check and apply the setup; the channels output their base (initial) level; a
        running output stops (and restarts in free run, PG PDF 148) (PG PDF 515-516)."""
        flex.arity(cmd, 1, 10)
        channels = [self._spgu_channel(arg) for arg in cmd.args]
        for channel in channels:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
            self._spgu_check_setup(channel)
        was_running = self._spgu_current() is not None
        self._spgu_stop(spp=False)
        for channel in channels:
            setup = self._spgu_setup(channel)
            setup.applied_on = self.state.channels[channel]
            if not self.faults.stuck(channel):
                self.state.channels[channel].voltage = self._spgu_static_set_level(setup)
        self._commit_dc()
        if was_running and self._spgu_run_mode == 0 and self._spgu_current() is None:
            self._spgu_start()

    @handles("SRP")
    def _cmd_srp(self, cmd: flex.Command) -> None:
        """``SRP``: start every set-up SPGU channel (PG PDF 518); a running output restarts."""
        flex.arity(cmd, 0, 0)
        self._spgu_stop(spp=False)
        if self._spgu_current() is not None:
            return  # held by spgu_no_stop
        if self._spgu_mode == 1 and self._spgu_sequence is None and self._spgu_ready_channels():
            raise flex.FlexError(flex.ERR_ALWG_NO_SEQUENCE)
        self._spgu_start()

    @handles("SPP")
    def _cmd_spp(self, cmd: flex.Command) -> None:
        """``SPP``: stop every SPGU output; the channels return to their base (initial) level (PG PDF 511)."""
        flex.arity(cmd, 0, 0)
        self._spgu_stop(spp=True)

    @handles("SPST?")
    def _cmd_spst_q(self, cmd: flex.Command) -> str:
        """``SPST?``: 1 while an SPGU pulse or ALWG sequence output is active, else 0 (PG PDF 513-514)."""
        flex.arity(cmd, 0, 0)
        return "1" if self.spgu_output_active() else "0"

    @handles("CORRSER?")
    def _cmd_corrser_q(self, cmd: flex.Command) -> str:
        """``CORRSER? chnum,mode,delay,interval,count`` (PG PDF 385-386; module docstring)."""
        flex.arity(cmd, 5, 5)
        channel = self._spgu_channel(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        delay, interval = flex.number(cmd.args[2]), flex.number(cmd.args[3])
        count = flex.integer(cmd.args[4])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"CORRSER? mode {mode}")
        if not self.state.channels[channel].output_on:
            raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        self._spgu_check_setup(channel)
        _pieces, unit = self._spgu_pieces(channel)
        if delay < 0 or delay > unit - 5e-6:
            raise flex.FlexError(flex.ERR_SPGU_ADC_DELAY, f"delay {delay}")
        if not _within(interval, 5e-6, 1e-3):
            raise flex.FlexError(flex.ERR_SPGU_ADC_INTERVAL, f"interval {interval}")
        if not 1 <= count <= 65535:
            raise flex.FlexError(flex.ERR_SPGU_ADC_COUNT, f"count {count}")
        if delay + interval * count > unit * (1 + 1e-12):
            raise flex.FlexError(flex.ERR_SPGU_ADC_FIT, f"{delay} + {interval} x {count} > {unit}")
        setup = self._spgu_setup(channel)
        peak = max((v for p in _pieces for v in (p.v0, p.v1)), key=abs, default=0.0)
        if abs(peak) < CORRSER_MIN_V:
            raise flex.FlexError(flex.ERR_SPGU_LOW_VOLTAGE, f"{peak} V")
        self._spgu_stop(spp=False)
        now = self._spgu_now()
        base = self._spgu_smu_levels()
        voltage = self._spgu_delivered(channel, peak, setup.ser, base)
        load = self.faults.spgu_load(channel)
        if load is None:
            current = self.circuit.channel_currents({**base, channel: voltage}).get(channel, 0.0)
            load = abs(voltage / current) if current != 0.0 else math.inf
        load = min(max(load, 0.1), 1e6)
        others = [ch for ch in self._spgu_ready_channels() if ch != channel]
        unit_s, segments, _records = self._spgu_build([channel, *others])
        burst = Run(seq=-1, start=now, end=now + unit_s, unit=unit_s, segments=segments,
                    channels={channel, *others}, applied_until=now)
        self._spgu_drive(burst, now, now + unit_s, burst.channels)
        self._busy_until = max(self._busy_until, now + max(unit_s, delay + interval * count))
        if mode == 1:
            setup.ser = load
        self._commit_dc()
        return f"{load:.6E},{voltage:.6E}"

    @handles("ALW")
    def _cmd_alw(self, cmd: flex.Command) -> None:
        """``ALW chnum,length``: the pattern data block follows (PG PDF 361-362; Table 2-4, PDF 150)."""
        flex.arity(cmd, 2, 2)
        channel = self._spgu_channel(cmd.args[0])
        self._require_mode(1)
        length = flex.integer(cmd.args[1])
        if length < 20 + 14:
            raise flex.FlexError(flex.ERR_ALWG_PATTERN_SIZE, f"{length} bytes")
        self._spgu_pending = ("ALW", channel, length)

    @handles("ALS")
    def _cmd_als(self, cmd: flex.Command) -> None:
        """``ALS length``: the sequence data block follows (PG PDF 360-361; Table 2-5, PDF 151)."""
        flex.arity(cmd, 1, 1)
        self._require_mode(1)
        length = flex.integer(cmd.args[0])
        if length < 20 + 6:
            raise flex.FlexError(flex.ERR_ALWG_SEQUENCE_SIZE, f"{length} bytes")
        self._spgu_pending = ("ALS", None, length)

    # -- binary blocks ------------------------------------------------------------------------------------------------

    def _spgu_missing_block(self) -> int | None:
        """A command arrived instead of the block an ``ALW``/``ALS`` announced: the error code to queue (2156/2152)."""
        pending, self._spgu_pending = self._spgu_pending, None
        if pending is None:
            return None
        return flex.ERR_ALWG_PATTERN_SIZE if pending[0] == "ALW" else flex.ERR_ALWG_SEQUENCE_SIZE

    def _spgu_block(self, data: bytes) -> None:
        """Take the block announced by the last ``ALW``/``ALS``; ``FlexError`` 120 without one, 2152-2158 for bad
        data."""
        pending, self._spgu_pending = self._spgu_pending, None
        if pending is None:
            raise flex.FlexError(flex.ERR_PARAMETER, "binary block without ALW/ALS")
        kind, channel, length = pending
        if len(data) != length:
            raise flex.FlexError(flex.ERR_ALWG_PATTERN_SIZE if kind == "ALW" else flex.ERR_ALWG_SEQUENCE_SIZE,
                                 f"{len(data)} bytes, {length} announced")
        if kind == "ALW":
            assert channel is not None
            setup = self._spgu_setup(channel)
            setup.patterns, setup.applied_on = decode_patterns(data), None
        else:
            self._spgu_sequence = decode_sequence(data)
