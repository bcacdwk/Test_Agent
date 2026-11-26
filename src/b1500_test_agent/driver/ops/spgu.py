"""HV-SPGU operations (blueprint v2 2.5): guarded PG and ALWG setup, apply, start, stop, status polling and the
terminal-voltage (load) measurement.

``SpguOps`` is a mixin of ``B1500Driver``; its method names carry the family (``pulse``/``spgu``) because every
family mixin shares the facade's namespace. Every operation that can put a level on an SPGU output passes
``OutputGuard.check_pulse`` for every channel it touches before anything is written, with the channel's guard view
(``models.spgu``: ``program.guard_train(ch)``, whose level is the open-load level ``|V| (SER + 50) / SER``):

- ``configure_pulse(program)`` (PG ``SpguPulseProgram``) and ``configure_alwg(program)`` (``AlwgProgram``), both
  ``configure_spgu``: build every command first (builders refuse values outside the manual's syntax domain), check
  every channel, then write ``SIM``, ``SPRM`` (count or duration, never free run), ``SPPER`` (PG), and per channel
  ``SER``, ``SPM``/``SPT``/``SPV`` (PG) or the ``ALW`` pattern block (ALWG), ``ODSW``, ``STGP``; ALWG ends with the
  ``ALS`` sequence block. Nothing is output yet.
- ``apply_pulse_setup(chs)`` (``SPUPD``): only channels configured by this driver; they output their base level,
  which the configure check covered.
- ``start_pulses()`` (``SRP``): re-checks every applied channel, then starts them.
- ``set_pulse_load(ch, ohm)`` (``SER``): checks the channel with the new load first (a smaller ``SER`` raises the
  open-load level).
- ``measure_pulse_load(ch, ...)`` (``CORRSER?`` mode 0): it outputs the applied channels' first pulse, so it
  re-checks them like ``start_pulses``; it never lets the instrument set ``SER`` itself (mode 1), so every load
  change passes the guard.
- ``stop_pulses()`` (``SPP``) is never gated; ``pulse_output_active()`` (``SPST?``) and ``wait_pulses_stopped(...)``
  (poll ``SPST?`` with host waits between polls and a caller check, e.g. ``tx.check_abort``, at least once a second)
  only read. ATV-19 (``SPST?`` = 1 while running, 0 after the count/duration, PG PDF 142) is
  TODO(verify)[L7.A4, L7.A13]; its fallback is the caller's: after ``wait_pulses_stopped`` raises
  ``SpguStillActive``, send ``SPP`` and let the cleanup verify.

``pulse_setup_commands``/``alwg_setup_commands``/``spgu_preview`` are pure (``spgu_preview`` is a kind's FLEX
preview); ``ALW``/``ALS`` appear there as their command header (the block follows on the bus).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.discovery import LoadMeasurement, parse_corrser, parse_spst
from b1500_test_agent.driver.errors import DriverStateError, SpguStillActive
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.spgu import AlwgProgram, SpguChannel, SpguProgram, SpguPulseProgram

Write = str | tuple[str, bytes]
"""One SPGU setup write: a command, or a command header with its binary block."""

DEFAULT_POLL_S = 0.1
"""Host wait between two ``SPST?`` polls of ``wait_pulses_stopped`` (the lab code polls every 0.1 s, lwp
``SPGU_pulse.m``)."""


def _spm_mode(channel: SpguChannel) -> int:
    """``SPM`` mode of a PG channel: the source number of a two-level pulse, 3 for a three-level pulse."""
    return 3 if channel.levels == "three_level" else next(iter(channel.sources))


def _switch_command(ch: int, channel: SpguChannel) -> str:
    switch = channel.pulse_switch
    if switch is None:
        return flex.odsw(ch, 0)
    return flex.odsw(ch, 1, 1 if switch.normally_closed else 0, switch.delay_s, switch.width_s)


def _run_mode(program: SpguProgram) -> str:
    if program.count is not None:
        return flex.sprm(flex.SPRM_COUNT, program.count)
    return flex.sprm(flex.SPRM_DURATION, float(program.duration_s or 0.0))


class SpguOps(DriverBase):
    """SPGU operations of ``B1500Driver`` (see the module docstring)."""

    _spgu_program: SpguProgram | None = None
    _spgu_applied: frozenset[int] = frozenset()

    # -- pure: the setup writes ---------------------------------------------------------------------------------

    @staticmethod
    def pulse_setup_commands(program: SpguPulseProgram) -> list[str]:
        """The PG setup writes of ``program``, in order: ``SIM 0``, ``SPRM``, ``SPPER``, then per channel (ascending)
        ``SER``, ``SPM``, ``SPT`` + ``SPV`` per source, ``ODSW``, ``STGP``.

        Raises:
            ValueError: If a value is outside the syntax domain of a command.
        """
        lines = [flex.sim(flex.SIM_PG), _run_mode(program), flex.spper(program.period_s)]
        for ch, channel in sorted(program.channels.items()):
            lines += [flex.ser(ch, channel.load_ohm), flex.spm(ch, _spm_mode(channel))]
            for src, source in sorted(channel.sources.items()):
                lines.append(flex.spt(ch, src, source.delay_s, source.width_s, source.lead_s, source.trailing_s))
                lines.append(flex.spv(ch, src, source.base_v, source.peak_v))
            lines += [_switch_command(ch, channel), flex.stgp(ch, 1 if channel.trigger else 0)]
        return lines

    @staticmethod
    def alwg_setup_commands(program: AlwgProgram) -> list[Write]:
        """The ALWG setup writes of ``program``, in order: ``SIM 1``, ``SPRM``, then per channel (ascending) ``SER``,
        ``ODSW``, ``STGP`` and the ``ALW`` pattern block, finally the ``ALS`` sequence block.

        Raises:
            ValueError: If a value is outside the syntax domain of a command or of the ALWG data format.
        """
        lines: list[Write] = [flex.sim(flex.SIM_ALWG), _run_mode(program)]
        for ch, channel in sorted(program.channels.items()):
            lines.append(flex.ser(ch, channel.load_ohm))
            lines.append(flex.odsw(ch, 1, 1 if channel.normally_closed else 0) if channel.pulse_switch
                         else flex.odsw(ch, 0))
            lines.append(flex.stgp(ch, channel.trigger))
            lines.append(flex.alw(ch, channel.patterns))
        lines.append(flex.als(program.sequence))
        return lines

    @classmethod
    def spgu_setup_commands(cls, program: SpguProgram) -> list[Write]:
        """``pulse_setup_commands`` or ``alwg_setup_commands`` by program type."""
        if isinstance(program, SpguPulseProgram):
            return list(cls.pulse_setup_commands(program))
        return cls.alwg_setup_commands(program)

    @classmethod
    def spgu_preview(cls, program: SpguProgram) -> list[str]:
        """The FLEX lines of one output: the setup (block commands as their header), ``SPUPD`` of every channel and
        ``SRP`` (the ``SPST?`` polls and ``SPP`` are queries/cleanup and not listed)."""
        lines = [item if isinstance(item, str) else item[0] for item in cls.spgu_setup_commands(program)]
        return [*lines, flex.spupd(sorted(program.channels)), flex.SRP]

    # -- guarded operations -------------------------------------------------------------------------------------

    @property
    def spgu_program(self) -> SpguProgram | None:
        """The program this driver configured last (``None`` before ``configure``)."""
        return self._spgu_program

    def _check_channels(self, program: SpguProgram, chs: Iterable[int], operation: str) -> None:
        for ch in chs:
            guard = self._require_guard(operation, ch)
            guard.check_channel(ch)
            train = program.guard_train(ch)
            guard.check_pulse(ch, train.base_v, train.peak_v, train.width_s, train.period_s, train.pulses,
                              train.load_ohm)

    def configure_pulse(self, program: SpguPulseProgram) -> None:
        """PG setup of ``program`` (``configure_spgu``)."""
        self.configure_spgu(program)

    def configure_alwg(self, program: AlwgProgram) -> None:
        """ALWG setup of ``program`` (``configure_spgu``)."""
        self.configure_spgu(program)

    def configure_spgu(self, program: SpguProgram) -> None:
        """Check every channel of ``program`` against the guard, then write its setup (module docstring); the
        channels output nothing new until ``apply_pulse_setup``.

        Raises:
            EnvelopeViolation: A channel is outside its pulse envelope (nothing written).
            ValueError: A value is outside a command's syntax domain (nothing written).
        """
        writes = self.spgu_setup_commands(program)
        self._check_channels(program, sorted(program.channels), "SPGU configure")
        self._spgu_program, self._spgu_applied = program, frozenset()
        for item in writes:
            if isinstance(item, str):
                self._write(item)
            else:
                self._write_block(*item)

    def _configured(self, operation: str) -> SpguProgram:
        if self._spgu_program is None:
            raise DriverStateError(f"{operation} refused: no SPGU program was configured by this driver")
        return self._spgu_program

    def apply_pulse_setup(self, chs: Sequence[int] | None = None) -> None:
        """``SPUPD`` of ``chs`` (default: every configured channel): they output their base (ALWG: initial) level.

        Raises:
            DriverStateError: A channel was not configured by this driver (nothing written).
        """
        program = self._configured("apply_pulse_setup")
        channels = sorted(program.channels) if chs is None else list(chs)
        unknown = [ch for ch in channels if ch not in program.channels]
        if unknown:
            raise DriverStateError(f"apply_pulse_setup refused: channel(s) {unknown} were not configured by this "
                                   "driver")
        self._write(flex.spupd(channels))
        self._spgu_applied = self._spgu_applied | frozenset(channels)

    def _applied(self, operation: str) -> tuple[SpguProgram, list[int]]:
        program = self._configured(operation)
        if not self._spgu_applied:
            raise DriverStateError(f"{operation} refused: no SPGU channel was set up (apply_pulse_setup)")
        return program, sorted(self._spgu_applied)

    def start_pulses(self) -> None:
        """``SRP`` after re-checking every applied channel against the guard (pulses or waveforms start).

        Raises:
            DriverStateError: Nothing configured and applied by this driver (nothing written).
            EnvelopeViolation: An applied channel is outside its envelope (nothing written).
        """
        program, applied = self._applied("start_pulses")
        self._check_channels(program, applied, "SPGU start")
        self._write(flex.SRP)

    def stop_pulses(self) -> None:
        """``SPP``: stop every SPGU output (never gated; PG PDF 511)."""
        self._write(flex.SPP)

    def set_pulse_load(self, ch: int, load_ohm: float) -> None:
        """``SER ch,load`` after checking the channel with the new load (the open-load level rises as ``SER``
        falls); the configured program keeps the new load.

        Raises:
            DriverStateError: ``ch`` is not a configured channel. EnvelopeViolation: outside the envelope.
        """
        program = self._configured("set_pulse_load")
        if ch not in program.channels:
            raise DriverStateError(f"set_pulse_load refused: channel {ch} was not configured by this driver")
        channels = dict(program.channels)
        channels[ch] = channels[ch].model_copy(update={"load_ohm": load_ohm})
        updated = type(program).model_validate({**program.model_dump(), "channels": channels})
        command = flex.ser(ch, load_ohm)
        self._check_channels(updated, [ch], "SPGU load")
        self._write(command)
        self._spgu_program = updated

    def measure_pulse_load(self, ch: int, *, delay_s: float, interval_s: float, count: int = 1) -> LoadMeasurement:
        """``CORRSER? ch,0,delay,interval,count``: the load impedance and terminal voltage measured during the first
        pulse (PG PDF 385-386); ``SER`` stays as set (mode 0). It outputs the applied channels' pulses, so they are
        re-checked first; outputs then rest at their base level.

        Raises:
            DriverStateError: ``ch`` is not applied. EnvelopeViolation: outside the envelope.
            FlexParseError: The answer is not ``loadZ,voltage``.
        """
        program, applied = self._applied("measure_pulse_load")
        if ch not in applied:
            raise DriverStateError(f"measure_pulse_load refused: channel {ch} was not set up (apply_pulse_setup)")
        command = flex.corrser_q(ch, flex.CORRSER_MEASURE_ONLY, delay_s, interval_s, count)
        self._check_channels(program, applied, "SPGU load measurement")
        return parse_corrser(self._query(command))

    def pulse_output_active(self) -> bool:
        """``SPST?`` -> ``True`` while an SPGU pulse or ALWG sequence output is active (PG PDF 513-514; ATV-19)."""
        return parse_spst(self._query(flex.SPST_Q))

    def wait_pulses_stopped(self, *, timeout_s: float, poll_s: float = DEFAULT_POLL_S,
                     check: Callable[[], None] | None = None) -> float:
        """Poll ``SPST?`` until it reads 0, with ``host_wait(poll_s)`` between polls and ``check()`` after every wait
        (``tx.check_abort``; keep ``poll_s`` <= 1 s); returns the host time waited.

        Raises:
            SpguStillActive: ``SPST?`` still reads 1 after ``timeout_s`` of waiting (the caller sends ``SPP``).
            ValueError: ``poll_s`` is not positive or ``timeout_s`` is negative.
        """
        if not poll_s > 0 or not timeout_s >= 0:
            raise ValueError(f"wait_stopped needs poll_s > 0 and timeout_s >= 0, got {poll_s!r}, {timeout_s!r}")
        waited = 0.0
        while self.pulse_output_active():
            if waited >= timeout_s:
                raise SpguStillActive(f"SPGU output still active (SPST? 1) after {waited:g} s", waited_s=waited)
            step = min(poll_s, timeout_s - waited)
            self.host_wait(step)
            waited += step
            if check is not None:
                check()
        return waited
