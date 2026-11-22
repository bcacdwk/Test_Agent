"""Per-command output guard (blueprint v1 2.3, 4.1 layer 3; v2 2.5).

Every source-like driver call passes the guard before anything is written; a violation raises
``EnvelopeViolation`` and nothing is sent. The envelope is the plan's ``CompiledEnvelope``: the channel allowlist
with the largest |V| and |I| each channel may see, plus the pulse, AC and waveform sub-envelopes and the allowed
switch routes. Values are compared exactly; there is no tolerance and no bypass.

- ``check(ch, "V"|"I", level, compliance)`` (v1): SMU ``force_*``, sweeps, pulsed, sampling, search and QSCV
  sources; ``check_channel`` before ``CN``.
- ``check_pulse``: HV-SPGU ``configure_pulse``/ALWG/start and SMU pulse trains. The level at the DUT is the
  open-load level (``models.sources.open_load_voltage``: ``|V| (SER + 50) / SER`` on a 50 Ohm SPGU), never the set
  level; a count below 1 (free run) is refused.
- ``check_ac``: MFCMU ``set_ac``/``set_dc``/sweeps (AC level, DC bias, frequency).
- ``check_route``: every switch route (``ERSSP``, ``SSP``, ``SAP``, RSU connect): a route of the plan
  (``envelope.routes``), or a declared switch output going to its ``rest`` state.
- ``check_waveform``: every WGFMU pattern before ``add_vectors`` (every level, the 10 ns grid, vector count, time);
  also a WGFMU DC level (no vectors, the level as ``v0``).
- ``check_sequence``: a WGFMU channel's whole output sequence before ``add_sequence`` (total output time with every
  repeat, stored values): the counts a single pattern cannot show (``driver/wgfmu.py``, WP10.3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from b1500_test_agent.driver.modules import SPGU_SPEC
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope, PulseEnvelope, WaveformLimits
from b1500_test_agent.models.routing import Route, SwitchSpec
from b1500_test_agent.models.sources import on_grid, open_load_voltage

ViolationReason = Literal[
    "no_guard", "channel_not_allowed", "non_finite", "level_exceeds_envelope", "zero_compliance",
    "compliance_exceeds_envelope",
    "no_pulse_envelope", "free_run", "invalid_pulse", "pulse_level_exceeds_envelope", "pulse_width_outside_envelope",
    "duty_exceeds_envelope", "count_exceeds_envelope", "on_time_exceeds_envelope",
    "no_ac_envelope", "ac_exceeds_envelope", "dc_exceeds_envelope", "frequency_outside_envelope",
    "route_not_allowed",
    "no_waveform_envelope", "invalid_waveform", "vectors_exceed_envelope", "off_grid", "time_exceeds_envelope",
    "points_exceed_envelope",
]  # fmt: skip


class EnvelopeViolation(RuntimeError):
    """A source command would leave the plan's compiled envelope (or no guard is installed); nothing was sent.

    Attributes mirror the refused request so that the transaction can audit an ``envelope_violation`` event.
    """

    def __init__(
        self,
        reason: ViolationReason,
        message: str,
        *,
        channel: int | None = None,
        quantity: str | None = None,
        level: float | None = None,
        compliance: float | None = None,
        limit: float | None = None,
    ) -> None:
        super().__init__(message)
        self.reason: ViolationReason = reason
        self.channel = channel
        self.quantity = quantity
        self.level = level
        self.compliance = compliance
        self.limit = limit


def _normalize(channel: int) -> int:
    """PG Table 4-1: channel ``n`` (1-10) and ``n*100+1`` address the same subchannel."""
    return channel * 100 + 1 if 1 <= channel <= 10 else channel


def _finite(*values: float | None) -> bool:
    return all(v is None or (isinstance(v, int | float) and math.isfinite(v)) for v in values)


class OutputGuard:
    """Checked before ANY source-like command is written (DV/DI/WV/WI/..., SPGU pulses, MFCMU AC/DC, switch routes,
    WGFMU vectors): channel in the plan allowlist and every level inside its compiled envelope. Raises
    EnvelopeViolation; nothing is sent.

    ``switches``: the station's declared switches (their ``rest`` states may always be restored); without them only
    the plan's own routes pass ``check_route``.
    """

    def __init__(self, envelope: CompiledEnvelope, *, switches: Sequence[SwitchSpec] = ()) -> None:
        self.envelope = envelope
        self._channels: dict[int, ChannelEnvelope] = {_normalize(ch): env for ch, env in envelope.channels.items()}
        self._waveform: dict[int, WaveformLimits] = {_normalize(ch): w for ch, w in envelope.waveform.items()}
        self._switches: dict[str, SwitchSpec] = {s.id: s for s in switches}

    @property
    def switches(self) -> tuple[SwitchSpec, ...]:
        """The station's declared switches this guard knows (the WGFMU driver finds each channel's RSU here)."""
        return tuple(self._switches.values())

    def channel_envelope(self, ch: int) -> ChannelEnvelope:
        """The envelope of ``ch`` (``1`` and ``101`` are the same channel).

        Raises:
            EnvelopeViolation: ``channel_not_allowed`` when the channel is not in the plan allowlist.
        """
        env = self._channels.get(_normalize(ch)) if isinstance(ch, int) and not isinstance(ch, bool) else None
        if env is None:
            allowed = sorted(self.envelope.channels)
            raise EnvelopeViolation(
                "channel_not_allowed", f"channel {ch!r} is not in the plan allowlist {allowed}", channel=ch
            )
        return env

    def check_channel(self, ch: int) -> None:
        """Refuse a channel outside the plan allowlist (used before ``CN``)."""
        self.channel_envelope(ch)

    def check(self, ch: int, quantity: Literal["V", "I"], level: float, compliance: float) -> None:
        """Refuse a source setting outside the envelope.

        ``quantity`` is what the channel forces: ``"V"`` (``level`` in V, ``compliance`` in A) or ``"I"`` (``level``
        in A, ``compliance`` in V). For a sweep, call once per end point.

        Raises:
            EnvelopeViolation: channel not allowed, non-finite value, |level| above the envelope, zero compliance,
                or |compliance| above the envelope.
            ValueError: If ``quantity`` is neither ``"V"`` nor ``"I"``.
        """
        if quantity not in ("V", "I"):
            raise ValueError(f"quantity must be 'V' or 'I', got {quantity!r}")
        details = {"channel": ch, "quantity": quantity, "level": level, "compliance": compliance}
        env = self.channel_envelope(ch)
        if env.max_abs_i is None:
            raise EnvelopeViolation("channel_not_allowed", f"channel {ch} ({env.role}, {env.function}) is a source "
                                    "without compliance; SMU source commands are not allowed on it", **details)
        if not (math.isfinite(level) and math.isfinite(compliance)):
            raise EnvelopeViolation("non_finite", f"channel {ch}: level and compliance must be finite", **details)
        level_limit, comp_limit = (env.max_abs_v, env.max_abs_i) if quantity == "V" else (env.max_abs_i, env.max_abs_v)
        level_unit, comp_unit = ("V", "A") if quantity == "V" else ("A", "V")
        if abs(level) > level_limit:
            raise EnvelopeViolation(
                "level_exceeds_envelope",
                f"channel {ch}: |{quantity}| {abs(level):g} {level_unit} exceeds the envelope {level_limit:g} "
                f"{level_unit}",
                limit=level_limit,
                **details,
            )
        if compliance == 0:
            raise EnvelopeViolation("zero_compliance", f"channel {ch}: compliance must be non-zero", **details)
        if abs(compliance) > comp_limit:
            raise EnvelopeViolation(
                "compliance_exceeds_envelope",
                f"channel {ch}: |compliance| {abs(compliance):g} {comp_unit} exceeds the envelope {comp_limit:g} "
                f"{comp_unit}",
                limit=comp_limit,
                **details,
            )

    # -- v2: pulses ------------------------------------------------------------------------------------------------

    def check_pulse(self, ch: int, base_v: float, peak_v: float, width_s: float, period_s: float, count: int,
                    load_ohm: float | None) -> None:
        """Refuse a pulse train (one start) outside the channel's pulse envelope.

        ``load_ohm`` is the HV-SPGU ``SER`` (required on a ``pgu`` channel, ``None`` elsewhere): the level checked is
        the open-load level at the DUT, ``max(|base|, |peak|) (SER + 50) / SER`` (2x at 50 Ohm); for an SMU pulse it
        is the set level. ``count`` is the number of pulses of this start; a count below 1 (free run) is refused.
        Width within ``[min_width_s, max_width_s]``, ``width / period <= max_duty``, ``count <= max_count`` and
        ``count x width <= max_on_time_s``.

        Raises:
            EnvelopeViolation: see ``ViolationReason`` (``no_pulse_envelope``, ``free_run``, ``invalid_pulse``,
                ``pulse_level_exceeds_envelope``, ``pulse_width_outside_envelope``, ``duty_exceeds_envelope``,
                ``count_exceeds_envelope``, ``on_time_exceeds_envelope``, ``non_finite``).
        """
        env = self.channel_envelope(ch)
        pulse = self._pulse(ch, env)
        if not _finite(base_v, peak_v, width_s, period_s, load_ohm):
            raise EnvelopeViolation("non_finite", f"channel {ch}: pulse values must be finite", channel=ch,
                                    quantity="pulse")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise EnvelopeViolation("free_run", f"channel {ch}: pulse count {count!r} is not a positive integer "
                                    "(free-running output is never allowed)", channel=ch, quantity="count")
        if not 0 < width_s < period_s:
            raise EnvelopeViolation("invalid_pulse", f"channel {ch}: width {width_s:g} s must be positive and "
                                    f"shorter than the period {period_s:g} s", channel=ch, quantity="width")
        is_pgu = env.function == "pgu"
        if is_pgu and (load_ohm is None or load_ohm <= 0):
            raise EnvelopeViolation("invalid_pulse", f"channel {ch}: an SPGU pulse needs its positive SER load "
                                    f"(got {load_ohm!r})", channel=ch, quantity="load_ohm")
        if not is_pgu and load_ohm is not None:
            raise EnvelopeViolation("invalid_pulse", f"channel {ch} ({env.function}) has no SER load setting",
                                    channel=ch, quantity="load_ohm")
        v_dut = open_load_voltage(max(abs(base_v), abs(peak_v)), load_ohm=load_ohm,
                                  source_ohm=SPGU_SPEC.output_ohm if is_pgu else None)
        limit_v = min(pulse.max_abs_v_dut, env.max_abs_v)
        if v_dut > limit_v:
            raise EnvelopeViolation("pulse_level_exceeds_envelope", f"channel {ch}: {v_dut:g} V at the DUT (open "
                                    f"load) exceeds the pulse envelope {limit_v:g} V", channel=ch,
                                    quantity="V_dut", level=v_dut, limit=limit_v)
        if not pulse.min_width_s <= width_s <= pulse.max_width_s:
            raise EnvelopeViolation("pulse_width_outside_envelope", f"channel {ch}: width {width_s:g} s is outside "
                                    f"{pulse.min_width_s:g}..{pulse.max_width_s:g} s", channel=ch,
                                    quantity="width", level=width_s, limit=pulse.max_width_s)
        duty = width_s / period_s
        if duty > pulse.max_duty:
            raise EnvelopeViolation("duty_exceeds_envelope", f"channel {ch}: duty {duty:g} exceeds "
                                    f"{pulse.max_duty:g}", channel=ch, quantity="duty", level=duty,
                                    limit=pulse.max_duty)
        if count > pulse.max_count:
            raise EnvelopeViolation("count_exceeds_envelope", f"channel {ch}: {count} pulses exceed "
                                    f"{pulse.max_count}", channel=ch, quantity="count", level=count,
                                    limit=pulse.max_count)
        on_time = count * width_s
        if on_time > pulse.max_on_time_s:
            raise EnvelopeViolation("on_time_exceeds_envelope", f"channel {ch}: {on_time:g} s at the pulse level "
                                    f"exceeds {pulse.max_on_time_s:g} s", channel=ch, quantity="on_time",
                                    level=on_time, limit=pulse.max_on_time_s)

    @staticmethod
    def _pulse(ch: int, env: ChannelEnvelope) -> PulseEnvelope:
        if env.pulse is None:
            raise EnvelopeViolation("no_pulse_envelope", f"channel {ch} ({env.role}) has no pulse envelope",
                                    channel=ch, quantity="pulse")
        return env.pulse

    # -- v2: MFCMU AC/DC -------------------------------------------------------------------------------------------

    def check_ac(self, ch: int, ac_vrms: float, dc_v: float, freq_hz: float) -> None:
        """Refuse an MFCMU setting outside the channel's AC envelope: ``0 <= ac_vrms <= max_vrms``,
        ``|dc_v| <= max_dc_v`` (and the channel's |V|), ``f_min_hz <= freq_hz <= f_max_hz``.

        Raises:
            EnvelopeViolation: ``no_ac_envelope``, ``non_finite``, ``ac_exceeds_envelope``, ``dc_exceeds_envelope``
                or ``frequency_outside_envelope``.
        """
        env = self.channel_envelope(ch)
        ac = env.ac
        if ac is None:
            raise EnvelopeViolation("no_ac_envelope", f"channel {ch} ({env.role}) has no AC envelope", channel=ch,
                                    quantity="ac")
        if not _finite(ac_vrms, dc_v, freq_hz):
            raise EnvelopeViolation("non_finite", f"channel {ch}: AC, DC and frequency must be finite", channel=ch,
                                    quantity="ac")
        if not 0 <= ac_vrms <= ac.max_vrms:
            raise EnvelopeViolation("ac_exceeds_envelope", f"channel {ch}: AC {ac_vrms:g} Vrms is outside "
                                    f"0..{ac.max_vrms:g} Vrms", channel=ch, quantity="vrms", level=ac_vrms,
                                    limit=ac.max_vrms)
        dc_limit = min(ac.max_dc_v, env.max_abs_v)
        if abs(dc_v) > dc_limit:
            raise EnvelopeViolation("dc_exceeds_envelope", f"channel {ch}: DC bias |{dc_v:g}| V exceeds "
                                    f"{dc_limit:g} V", channel=ch, quantity="V", level=dc_v, limit=dc_limit)
        if not ac.f_min_hz <= freq_hz <= ac.f_max_hz:
            raise EnvelopeViolation("frequency_outside_envelope", f"channel {ch}: {freq_hz:g} Hz is outside "
                                    f"{ac.f_min_hz:g}..{ac.f_max_hz:g} Hz", channel=ch, quantity="freq",
                                    level=freq_hz, limit=ac.f_max_hz)

    # -- v2: switch routes -----------------------------------------------------------------------------------------

    def check_route(self, route: Route) -> None:
        """Refuse a switch route that is neither one of the plan's routes (``envelope.routes``) nor a declared
        output returning to its switch's ``rest`` state; a declared switch must also be able to take the state on
        that output (``pgu_open`` only on selector CH 1).

        Raises:
            EnvelopeViolation: ``route_not_allowed``.
        """
        switch = self._switches.get(route.switch)
        if switch is not None and not switch.allows(route.output, route.state):
            raise EnvelopeViolation("route_not_allowed", f"route {route}: {switch.id} cannot take that state on "
                                    f"{route.output}", quantity="route")
        if route in self.envelope.routes:
            return
        if switch is not None and route.output in switch.ports and route.state == switch.rest:
            return
        raise EnvelopeViolation("route_not_allowed", f"route {route} is neither a route of the plan nor the rest "
                                "state of a declared switch", quantity="route")

    # -- v2: WGFMU waveforms ---------------------------------------------------------------------------------------

    def check_waveform(self, ch: int, dt: Sequence[float], v: Sequence[float], *, v0: float | None = None) -> None:
        """Refuse a WGFMU pattern for channel ``ch`` outside its envelope: every level (``v0`` too) within the
        channel's |V|, every vector time a positive multiple of the grid, at most ``max_vectors`` vectors and at most
        ``total_time_s`` in total.

        Raises:
            EnvelopeViolation: ``no_waveform_envelope``, ``invalid_waveform``, ``non_finite``,
                ``level_exceeds_envelope``, ``off_grid``, ``vectors_exceed_envelope`` or ``time_exceeds_envelope``.
        """
        env = self.channel_envelope(ch)
        limits = self._waveform.get(_normalize(ch))
        if limits is None:
            raise EnvelopeViolation("no_waveform_envelope", f"channel {ch} ({env.role}) has no waveform envelope",
                                    channel=ch, quantity="waveform")
        times, levels = list(dt), list(v)
        if len(times) != len(levels):
            raise EnvelopeViolation("invalid_waveform", f"channel {ch}: {len(times)} times for {len(levels)} levels",
                                    channel=ch, quantity="vectors")
        if len(times) > limits.max_vectors:
            raise EnvelopeViolation("vectors_exceed_envelope", f"channel {ch}: {len(times)} vectors exceed "
                                    f"{limits.max_vectors}", channel=ch, quantity="vectors", level=len(times),
                                    limit=limits.max_vectors)
        if not _finite(v0, *times, *levels):
            raise EnvelopeViolation("non_finite", f"channel {ch}: waveform values must be finite", channel=ch,
                                    quantity="waveform")
        for index, level in enumerate(([v0] if v0 is not None else []) + levels):
            if abs(level) > env.max_abs_v:
                raise EnvelopeViolation("level_exceeds_envelope", f"channel {ch}: level {level:g} V (vector "
                                        f"{index}) exceeds the envelope {env.max_abs_v:g} V", channel=ch,
                                        quantity="V", level=level, limit=env.max_abs_v)
        for index, step in enumerate(times):
            if step < limits.grid_s or not on_grid(step, limits.grid_s):
                raise EnvelopeViolation("off_grid", f"channel {ch}: vector {index} time {step:g} s is not a positive "
                                        f"multiple of {limits.grid_s:g} s", channel=ch, quantity="dt", level=step,
                                        limit=limits.grid_s)
        total = math.fsum(times)
        if total > limits.total_time_s:
            raise EnvelopeViolation("time_exceeds_envelope", f"channel {ch}: {total:g} s exceeds "
                                    f"{limits.total_time_s:g} s", channel=ch, quantity="time", level=total,
                                    limit=limits.total_time_s)

    def check_sequence(self, ch: int, *, time_s: float, points: int) -> None:
        """Refuse a WGFMU channel's whole output sequence outside its waveform envelope: ``time_s`` (every pattern
        times its repeat count, plus the gaps between sequences) at most ``total_time_s`` and ``points`` (the values
        the channel stores over the run) at most ``max_points``. ``check_waveform`` bounds each pattern; repeats can
        only be bounded here (blueprint v2 2.5 "counts").

        Raises:
            EnvelopeViolation: ``channel_not_allowed``, ``no_waveform_envelope``, ``non_finite``,
                ``invalid_waveform`` (negative values), ``time_exceeds_envelope`` or ``points_exceed_envelope``.
        """
        env = self.channel_envelope(ch)
        limits = self._waveform.get(_normalize(ch))
        if limits is None:
            raise EnvelopeViolation("no_waveform_envelope", f"channel {ch} ({env.role}) has no waveform envelope",
                                    channel=ch, quantity="waveform")
        if not _finite(time_s) or isinstance(points, bool) or not isinstance(points, int):
            raise EnvelopeViolation("non_finite", f"channel {ch}: sequence time and points must be finite numbers",
                                    channel=ch, quantity="sequence")
        if time_s < 0 or points < 0:
            raise EnvelopeViolation("invalid_waveform", f"channel {ch}: negative sequence time or points",
                                    channel=ch, quantity="sequence")
        if time_s > limits.total_time_s * (1 + 1e-12):
            raise EnvelopeViolation("time_exceeds_envelope", f"channel {ch}: the sequence outputs {time_s:g} s, more "
                                    f"than {limits.total_time_s:g} s", channel=ch, quantity="time", level=time_s,
                                    limit=limits.total_time_s)
        if points > limits.max_points:
            raise EnvelopeViolation("points_exceed_envelope", f"channel {ch}: the sequence stores {points} values, "
                                    f"more than {limits.max_points}", channel=ch, quantity="points", level=points,
                                    limit=limits.max_points)
