"""Built-in rules of the pulse and waveform sources (blueprint v2 2.8 rows R-PULSE-01, R-PULSE-02, R-PULSE-03,
R-SPGU-01, R-WG-01, R-WG-02, in table order).

A **pulse channel** is an envelope channel whose role applies pulses (``pulse_v`` on an SMU, ``pgu`` on an HV-SPGU)
or that carries a pulse envelope (a WGFMU pulse builder). The rules read two things the kind compiles: the channel's
``PulseEnvelope`` (what ``OutputGuard.check_pulse`` enforces: open-load level at the DUT, width span, duty, pulses
and on-time per start, short-circuit current) and the ``SourcePlan`` in ``plan.program["sources"]`` (the nominal
pulse trains and the WGFMU waveform program, ``models/sources.py``). Module facts come from ``driver/modules.py``
(``SPGU_SPEC``, ``SMU_PULSE_SPECS``, ``WGFMU_SPEC``), DUT facts from the DUT profile's terminal ``pulse`` envelope and
``impedance``, soft bands from ``policy.pulse``.

SPGU arithmetic (R-SPGU-01, decision 9): the HV-SPGU is a 50 Ohm source without compliance whose level is adjusted
to the declared load ``SER`` (recipe ``load_ohm``), so an open load sees ``|V| (SER + 50) / SER`` (2x at 50 Ohm);
a short behind the terminal's ``min_series_ohm`` draws ``V_open / (50 + min_series_ohm)``. That current must stay
within the hard compliance limit unless the human declared the terminal ``high_z``; then it is an accepted residual
that the plan summary shows as ``Isc<=X A residual``.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator
from dataclasses import dataclass

from b1500_test_agent.driver.modules import SMU_PULSE_SPECS, SPEC_SYMBOL, SPGU_SPEC, WGFMU_SPEC, SpecProblem
from b1500_test_agent.models.plan import BoundChannel, ChannelEnvelope
from b1500_test_agent.models.sources import (
    MeasureEvent,
    PulseTrain,
    RangeEvent,
    WaveformProgram,
    on_grid,
    short_circuit_current,
    total_on_time_s,
    total_pulses,
)
from b1500_test_agent.models.station import SMU_TYPES, ModuleSlot
from b1500_test_agent.rules.builtin.common import (
    PULSE_FUNCTIONS,
    channel_envelope,
    dut_terminal,
    envelope_items,
    hard_limit_a,
    hard_limit_v,
    norm_channel,
    role_function,
    scalar,
    source_plan_of,
    who,
)
from b1500_test_agent.rules.engine import Finding, RuleContext, RuleEnv, block, confirm, info, rule

_TOL = 1e-12
"""Absolute slack (s) for 'ends within its pattern' comparisons of floating-point sums."""


@dataclass(frozen=True)
class PulseChannel:
    """One pulse channel of the plan: channel, envelope entry, role, role function and module."""

    channel: int
    entry: ChannelEnvelope
    role: str
    function: str | None
    module: ModuleSlot | None

    @property
    def name(self) -> str:
        return who(self.entry, self.channel)

    @property
    def source_ohm(self) -> float | None:
        """Output resistance of a level-adjusted source (HV-SPGU), else ``None``."""
        return SPGU_SPEC.output_ohm if self.module is not None and self.module.type == "HVSPGU" else None


def pulse_channels(ctx: RuleContext) -> list[PulseChannel]:
    """Envelope channels with a pulse role or a pulse envelope, in channel order."""
    found = []
    for channel, entry in envelope_items(ctx):
        function = role_function(ctx, entry.role, entry)
        if function in PULSE_FUNCTIONS or entry.pulse is not None:
            found.append(PulseChannel(channel, entry, entry.role, function,
                                      ctx.station.module_for_channel(channel)))
    return found


def _train_src(env: RuleEnv, channel: int, index: int, field: str | None = None) -> str:
    return env.plan(f"program.sources.pulses.{channel}[{index}]" + (f".{field}" if field else ""))


# -- R-PULSE-01 ------------------------------------------------------------------------------------------------------


@rule("R-PULSE-01", {"plan"})
def pulse_module_spec(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Every pulse channel has a pulse envelope and compiled pulse trains; every train lies inside its module's
    spec (HV-SPGU: levels, period, width, delay, transitions, resolutions, width >= leading / 0.8, period >= delay +
    width + trailing / 0.8, count or duration bounded, ``SER`` range; SMU: the ``PT`` width/period table; WGFMU: the
    10 ns grid) and inside the channel's pulse envelope (else the guard would refuse it at run time). Trains on a
    channel that is not a pulse channel, and a source plan that does not validate, block. Free run cannot be
    expressed (a train has a count or a duration)."""
    sources, problem = source_plan_of(ctx)
    if problem is not None:
        yield block(f"the kind's source plan does not validate ({problem})", source=env.plan("program.sources"),
                    observed=None, limit="a valid source plan")
        return
    channels = pulse_channels(ctx)
    known = {norm_channel(pc.channel) for pc in channels}
    for channel in sorted(sources.pulses):
        if norm_channel(channel) not in known:
            yield block(f"pulse trains on channel {channel}, which is not a pulse channel of the plan",
                        source=env.plan(f"program.sources.pulses.{channel}"), observed=channel,
                        limit=", ".join(str(pc.channel) for pc in channels) or None)
    for pc in channels:
        if pc.entry.pulse is None:
            yield block(f"{pc.name}: a pulse role without a pulse envelope (the guard would refuse every pulse)",
                        subject=pc.role, source=env.plan(f"envelope.channels.{pc.channel}.pulse"), observed=None,
                        limit="a pulse envelope")
            continue
        trains = sources.trains(pc.channel)
        if not trains:
            yield block(f"{pc.name}: no pulse train is compiled for this channel", subject=pc.role,
                        source=env.plan("program.sources.pulses"), observed=None, limit="a pulse train")
            continue
        for index, train in enumerate(trains):
            problems, source = _module_problems(env, pc, train)
            for found in problems:
                yield block(f"{pc.name}, train {index}: {found.message}", subject=pc.role, source=source,
                            observed=scalar(found.observed), limit=scalar(found.limit))
            yield from _envelope_admits(env, pc, index, train)


def _module_problems(env: RuleEnv, pc: PulseChannel, train: PulseTrain) -> tuple[list[SpecProblem], str]:
    module_type = pc.module.type if pc.module is not None else None
    if module_type == "HVSPGU":
        return SPGU_SPEC.train_problems(train), env.code(f"{SPEC_SYMBOL}.SPGU_SPEC")
    if module_type == "WGFMU":
        return WGFMU_SPEC.train_problems(train), env.code(f"{SPEC_SYMBOL}.WGFMU_SPEC")
    if module_type in SMU_TYPES and pc.function == "pulse_v":
        spec = SMU_PULSE_SPECS[module_type]
        return spec.train_problems(train), env.code(f"{SPEC_SYMBOL}.SMU_PULSE_SPECS[{module_type}] ({spec.source})")
    what = module_type or "no module"
    return ([SpecProblem(f"{what} cannot apply {pc.function or 'pulse'} trains", what, "HVSPGU, SMU pulse_v or WGFMU")],
            env.code(f"{SPEC_SYMBOL}"))


def _envelope_admits(env: RuleEnv, pc: PulseChannel, index: int, train: PulseTrain) -> Iterator[Finding]:
    pulse = pc.entry.pulse
    assert pulse is not None
    v_dut = train.open_load_v(source_ohm=pc.source_ohm)
    checks = (
        ("open-load level", v_dut, v_dut <= min(pulse.max_abs_v_dut, pc.entry.max_abs_v),
         min(pulse.max_abs_v_dut, pc.entry.max_abs_v), "max_abs_v_dut"),
        ("width", train.width_s, pulse.min_width_s <= train.width_s <= pulse.max_width_s,
         f"{pulse.min_width_s:g}..{pulse.max_width_s:g}", "max_width_s"),
        ("duty", train.duty, train.duty <= pulse.max_duty, pulse.max_duty, "max_duty"),
        ("pulses per start", train.pulses, train.pulses <= pulse.max_count, pulse.max_count, "max_count"),
        ("on-time per start", train.on_time_s, train.on_time_s <= pulse.max_on_time_s, pulse.max_on_time_s,
         "max_on_time_s"),
    )
    for label, observed, inside, limit, field in checks:
        if not inside:
            yield block(f"{pc.name}, train {index}: {label} {observed:g} is outside the compiled pulse envelope "
                        f"({limit}); the guard would refuse it", subject=pc.role,
                        source=env.plan(f"envelope.channels.{pc.channel}.pulse.{field}"), observed=observed,
                        limit=scalar(limit))


# -- R-PULSE-02 ------------------------------------------------------------------------------------------------------


@rule("R-PULSE-02", {"plan"})
def pulse_dut_envelope(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """A pulse channel's DUT terminal declares a ``pulse`` envelope (missing -> block: a human adds it, never
    invented); the open-load level at the DUT, the width, the duty and the pulses over the whole plan outside it
    need confirmation (``dut_envelope``). A missing DUT profile or terminal is R-DUT-01's block."""
    dut = ctx.dut
    if dut is None:
        return
    sources, _ = source_plan_of(ctx)
    for pc in pulse_channels(ctx):
        terminal, limits = dut_terminal(ctx, pc.role)
        if limits is None:
            continue
        if limits.pulse is None:
            yield block(f"{terminal} ({pc.name}): DUT {dut.name} declares no pulse envelope for this terminal; a "
                        "human adds one (never invent it)", subject=terminal,
                        source=env.dut(dut.name, f"terminals.{terminal}.pulse"), observed=None,
                        limit="a pulse envelope")
            continue
        pulse = pc.entry.pulse
        if pulse is None:
            continue
        trains = sources.trains(pc.channel)
        count = total_pulses(trains) if trains else pulse.max_count
        allowed = limits.pulse
        for label, unit, value, limit, field in (
            ("pulse level at the DUT", " V", pulse.max_abs_v_dut, allowed.max_abs_v, "max_abs_v"),
            ("pulse width", " s", pulse.max_width_s, allowed.max_width_s, "max_width_s"),
            ("duty", "", pulse.max_duty, allowed.max_duty, "max_duty"),
            ("pulses per run", "", count, allowed.max_count, "max_count"),
        ):
            if value > limit:
                yield confirm("dut_envelope", f"{terminal} ({pc.name}): {label} {value:g}{unit} is outside DUT "
                              f"{dut.name}'s pulse envelope {limit:g}{unit}", subject=terminal,
                              source=env.dut(dut.name, f"terminals.{terminal}.pulse.{field}"), observed=value,
                              limit=limit)


# -- R-PULSE-03 ------------------------------------------------------------------------------------------------------


@rule("R-PULSE-03", {"plan"})
def pulse_soft_bands(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """Above a ``policy.pulse`` soft band needs confirmation (``soft_pulse``): the open-load level at the DUT
    (``soft_abs_v``), the pulses over the whole plan (``soft_count``), the total time at the pulse level
    (``soft_on_time_s``) and the duty cycle (``max_duty``)."""
    soft = ctx.policy.pulse
    sources, _ = source_plan_of(ctx)
    for pc in pulse_channels(ctx):
        pulse = pc.entry.pulse
        if pulse is None:
            continue
        trains = sources.trains(pc.channel)
        count = total_pulses(trains) if trains else pulse.max_count
        on_time = total_on_time_s(trains) if trains else pulse.max_on_time_s
        for label, unit, value, limit, field in (
            ("pulse level at the DUT", " V", pulse.max_abs_v_dut, soft.soft_abs_v, "soft_abs_v"),
            ("pulses per run", "", count, soft.soft_count, "soft_count"),
            ("time at the pulse level", " s", on_time, soft.soft_on_time_s, "soft_on_time_s"),
            ("duty", "", pulse.max_duty, soft.max_duty, "max_duty"),
        ):
            if value > limit:
                yield confirm("soft_pulse", f"{pc.name}: {label} {value:g}{unit} is above the soft band "
                              f"{limit:g}{unit}", subject=pc.role, source=env.policy(f"pulse.{field}"),
                              observed=value, limit=limit)


# -- R-SPGU-01 -------------------------------------------------------------------------------------------------------


@rule("R-SPGU-01", {"plan"})
def spgu_load_and_short_circuit(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """For every HV-SPGU channel: each train sets ``SER`` to the recipe's ``load_ohm``; the open-load voltage at
    the DUT ``max |V| (SER + 50) / SER`` stays within the module's 40 V, the hard |V| limit and the DUT terminal's
    pulse ``max_abs_v``; a ``high_z`` terminal needs ``SER`` >= 1 kOhm; the short-circuit current ``V_open / (50 +
    min_series_ohm)`` (0 Ohm unless the terminal is ``resistive``) stays within the hard compliance limit unless the
    terminal is ``high_z``. The short-circuit bound of every channel is recorded as an info finding (``limit`` None
    = an accepted ``high_z`` residual), which the plan summary shows."""
    sources, _ = source_plan_of(ctx)
    hard_v, hard_v_source = hard_limit_v(ctx, env)
    hard_a, hard_a_source = hard_limit_a(ctx, env)
    for pc in pulse_channels(ctx):
        if pc.module is None or pc.module.type != "HVSPGU":
            continue
        trains = sources.trains(pc.channel)
        if not trains:
            continue
        for index, train in enumerate(trains):
            if train.load_ohm is None:
                yield block(f"{pc.name}, train {index}: no SER load (recipe load_ohm); the SPGU would level to its "
                            "initial 50 Ohm and put 2x the set voltage on a high-impedance DUT", subject=pc.role,
                            source=_train_src(env, pc.channel, index, "load_ohm"), observed=None, limit="load_ohm")
        v_open = max(SPGU_SPEC.open_load_v(t.max_abs_set_v, t.load_ohm) for t in trains)
        terminal, limits = dut_terminal(ctx, pc.role)
        dut_name = ctx.dut.name if ctx.dut is not None else ""
        spec_source = env.code(f"{SPEC_SYMBOL}.SPGU_SPEC.max_open_v (UG p76 (2-36))")
        for limit, source, what in ((SPGU_SPEC.max_open_v, spec_source, "the HV-SPGU's open-load maximum"),
                                    (hard_v, hard_v_source, "the hard |V| limit")):
            if v_open > limit:
                yield block(f"{pc.name}: open-load {v_open:g} V at the DUT exceeds {what} {limit:g} V",
                            subject=pc.role, source=source, observed=v_open, limit=limit)
        if limits is not None and limits.pulse is not None and v_open > limits.pulse.max_abs_v:
            yield block(f"{pc.name}: open-load {v_open:g} V exceeds terminal {terminal}'s pulse limit "
                        f"{limits.pulse.max_abs_v:g} V (SER divider: |V| (SER + 50) / SER)", subject=terminal,
                        source=env.dut(dut_name, f"terminals.{terminal}.pulse.max_abs_v"), observed=v_open,
                        limit=limits.pulse.max_abs_v)
        impedance = limits.impedance if limits is not None else "unknown"
        min_load = min(t.load_ohm if t.load_ohm is not None else SPGU_SPEC.initial_load_ohm for t in trains)
        if impedance == "high_z" and min_load < SPGU_SPEC.high_z_min_load_ohm:
            yield block(f"{pc.name}: terminal {terminal} is high_z but SER is {min_load:g} Ohm; an open load would "
                        f"see up to {SPGU_SPEC.open_load_v(1.0, min_load):g}x the set level (use load_ohm >= "
                        f"{SPGU_SPEC.high_z_min_load_ohm:g} Ohm)", subject=pc.role,
                        source=env.code(f"{SPEC_SYMBOL}.SPGU_SPEC.high_z_min_load_ohm"), observed=min_load,
                        limit=SPGU_SPEC.high_z_min_load_ohm)
        series = (limits.min_series_ohm or 0.0) if limits is not None and impedance == "resistive" else 0.0
        isc = short_circuit_current(v_open, source_ohm=SPGU_SPEC.output_ohm, series_ohm=series)
        if impedance == "high_z":
            yield info(f"{pc.name}: a short at terminal {terminal} would draw up to {isc:g} A; accepted residual "
                       "(the terminal is declared high_z)", subject=pc.role,
                       source=env.dut(dut_name, f"terminals.{terminal}.impedance"), observed=isc, limit=None)
        elif isc > hard_a:
            yield block(f"{pc.name}: a short behind {series:g} Ohm at terminal {terminal} ({impedance}) would draw "
                        f"{isc:g} A = {v_open:g} V / (50 + {series:g}) Ohm, above {hard_a:g} A; a human declares the "
                        "terminal's min_series_ohm or high_z", subject=pc.role, source=hard_a_source, observed=isc,
                        limit=hard_a)
        else:
            yield info(f"{pc.name}: a short at terminal {terminal} would draw at most {isc:g} A", subject=pc.role,
                       source=hard_a_source, observed=isc, limit=hard_a)


# -- R-WG-01 ---------------------------------------------------------------------------------------------------------


def _wgfmu_roles(ctx: RuleContext) -> list[tuple[str, BoundChannel | None]]:
    return [(name, ctx.plan.binding.roles.get(name)) for name, spec in sorted(ctx.recipe.roles.items())
            if spec.function == "wgfmu"]


@rule("R-WG-01", {"plan", "pre_execute"})
def wgfmu_access(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """WGFMU roles reach the DUT through their RSU (pin-map target ``RSU<ch>.OUT``, state ``wgfmu``); on visa the
    instrument library is loadable (64-bit ``wgfmu.dll``, ``DllProbe.loadable``); the bound channels are among the
    library's ``WGFMU_getChannelIds``. The live parts are required before execution and checked at validation when a
    snapshot carries them."""
    roles = _wgfmu_roles(ctx)
    if not roles:
        return
    pin_map = ctx.plan.binding.pin_map
    for name, bound in roles:
        if bound is None:
            continue
        via = bound.via
        switch = ctx.station.switch(via.switch) if via is not None else None
        if via is None or switch is None or switch.kind != "rsu" or via.state != "wgfmu":
            yield block(f"role {name}: a WGFMU channel reaches the DUT only through its RSU (pin map target "
                        "RSU<channel>.OUT)", subject=name, source=env.pin_map(pin_map, f"terminals.{bound.terminal}"),
                        observed=str(via) if via is not None else bound.channel, limit="an RSU route to wgfmu")
    pre = env.phase == "pre_execute"
    live = ctx.live
    if live is None:
        if pre:
            yield block("no live snapshot: the WGFMU library and channels cannot be checked",
                        source=env.live("snapshot"), observed=None, limit="a live snapshot")
        return
    if ctx.backend == "visa":
        probe = live.wgfmu_library
        if probe is None:
            if pre:
                yield block("the WGFMU instrument library was not probed", source=env.live("wgfmu_library"),
                            observed=None, limit="a loadable x64 library")
        elif not probe.loadable:
            hint = ("a 32-bit wgfmu.dll cannot load into 64-bit Python: install the WGFMU instrument library "
                    ">= A.03.00" if probe.machine == "x86" else probe.message or "see b1500 doctor")
            yield block(f"WGFMU library {probe.path or '(not found)'} is not loadable: {hint}",
                        source=env.live("wgfmu_library"), observed=probe.machine or probe.path,
                        limit="a loadable x64 library")
    channels = live.wgfmu_channels
    if channels is None:
        if pre:
            yield block("the WGFMU channel ids were not read (WGFMU_getChannelIds)", source=env.live("wgfmu_channels"),
                        observed=None, limit="the bound channels")
        return
    available = {norm_channel(c) for c in channels}
    for name, bound in roles:
        if bound is not None and bound.channel is not None and norm_channel(bound.channel) not in available:
            yield block(f"role {name}: WGFMU channel {bound.channel} is not among the library's channels",
                        subject=name, source=env.live("wgfmu_channels"), observed=bound.channel,
                        limit=", ".join(str(c) for c in sorted(channels)) or None)


# -- R-WG-02 ---------------------------------------------------------------------------------------------------------


@rule("R-WG-02", {"plan"})
def wgfmu_waveform_limits(ctx: RuleContext, env: RuleEnv) -> Iterator[Finding]:
    """The WGFMU waveform program lies inside the module and the plan: every WGFMU role's channel has a setup and a
    waveform envelope and the program drives no other channel; mode and ranges fit (PG: 3 V/5 V ranges, current
    measurement only in Fast IV/DC; errors 3302/3303); at most 2,048 vectors per pattern (3307) and 512 sequences per
    channel (3305), no empty pattern (3306), sequence counts 1..1,099,511,627,776 (3309); vector times 10 ns ..
    10995.11627775 s on the 10 ns grid (3311); every level inside the channel's force range (3310) and envelope;
    measure events inside their pattern on the grid with interval 10 ns..1.34217728 s (3312), average 0 or 10 ns..
    0.020971512 s (3315) and not above the interval (3316); range events only with Fast IV current measurement,
    outside averaging windows and, three or more in a pattern, more than 2 us apart (WG p128 (4-58)); stored values
    per channel within ``policy.run_limits.max_points.wgfmu`` and about 4,000,000 (WG p125 (4-55)); the program
    within the channel's ``WaveformLimits`` (vectors, values, time, 10 ns grid)."""
    sources, problem = source_plan_of(ctx)
    if problem is not None:
        return  # R-PULSE-01 reports an invalid source plan
    roles = {norm_channel(b.channel): (name, b.channel) for name, b in _wgfmu_roles(ctx)
             if b is not None and b.channel is not None}
    program = sources.waveform
    if not roles and program is None:
        return
    src = env.plan("program.sources.waveform")
    if program is None:
        yield block("WGFMU roles but no waveform program", source=src, observed=None, limit="a waveform program")
        return
    yield from _wg_channels(ctx, env, program, roles)
    spec_src = env.code(f"{SPEC_SYMBOL}.WGFMU_SPEC")
    yield from _wg_setups(program, spec_src)
    yield from _wg_patterns(ctx, env, program, spec_src)
    yield from _wg_sequences(program, spec_src)
    yield from _wg_events(program, spec_src)
    yield from _wg_points_and_envelope(ctx, env, program, spec_src)


def _wg_channels(ctx: RuleContext, env: RuleEnv, program: WaveformProgram,
                 roles: dict[int, tuple[str, int]]) -> Iterator[Finding]:
    programmed = {norm_channel(ch) for ch in program.channels}
    limits = {norm_channel(ch) for ch in ctx.plan.envelope.waveform}
    for key, (name, ch) in sorted(roles.items()):
        if key not in programmed:
            yield block(f"role {name} (channel {ch}) has no setup in the waveform program", subject=name,
                        source=env.plan("program.sources.waveform.channels"), observed=ch, limit="a channel setup")
        if key not in limits:
            yield block(f"role {name} (channel {ch}) has no waveform envelope (the guard would refuse every vector)",
                        subject=name, source=env.plan("envelope.waveform"), observed=ch, limit="waveform limits")
    for ch in sorted(program.channels):
        if norm_channel(ch) not in roles:
            yield block(f"the waveform program drives channel {ch}, which no WGFMU role of the plan binds",
                        source=env.plan("program.sources.waveform.channels"), observed=ch,
                        limit=", ".join(str(c) for c in sorted(c for _, c in roles.values())) or None)


def _wg_setups(program: WaveformProgram, source: str) -> Iterator[Finding]:
    spec = WGFMU_SPEC
    for ch, setup in sorted(program.channels.items()):
        if setup.mode == "pg" and setup.force_range not in spec.pg_force_ranges:
            yield block(f"channel {ch}: the {setup.force_range} range is not available in PG mode (error 3302)",
                        source=source, observed=setup.force_range, limit=", ".join(sorted(spec.pg_force_ranges)))
        if setup.measure == "current":
            if setup.mode not in spec.current_modes:
                yield block(f"channel {ch}: current measurement needs Fast IV or DC mode, not {setup.mode} "
                            "(error 3303)", source=source, observed=setup.mode, limit="fastiv, dc")
            if setup.current_range is None:
                yield block(f"channel {ch}: current measurement without a current range", source=source,
                            observed=None, limit=", ".join(spec.current_ranges))


def _wg_patterns(ctx: RuleContext, env: RuleEnv, program: WaveformProgram, source: str) -> Iterator[Finding]:
    spec = WGFMU_SPEC
    low, high = spec.vector_dt_s
    for name, pattern in program.patterns.items():
        count = len(pattern.vectors)
        if count > spec.max_vectors:
            yield block(f"pattern {name}: {count} vectors exceed {spec.max_vectors} (error 3307)", source=source,
                        observed=count, limit=spec.max_vectors)
        bad = [i for i, (dt, _) in enumerate(pattern.vectors) if not (low <= dt <= high and on_grid(dt, spec.grid_s))]
        if bad:
            first = pattern.vectors[bad[0]][0]
            yield block(f"pattern {name}: {len(bad)} of {count} vector times are not {low:g}..{high:g} s on the 10 ns "
                        f"grid (first: vector {bad[0]}, {first:g} s; error 3311)", source=source, observed=first,
                        limit=spec.grid_s)
    for ch in sorted(program.sequences):
        setup = program.channels[ch]
        bottom, top = spec.range_bounds(setup.mode, setup.force_range)
        levels = program.levels(ch)
        outside = [v for v in levels if not bottom <= v <= top]
        if outside:
            yield block(f"channel {ch}: level {outside[0]:g} V is outside the {setup.force_range} range "
                        f"{bottom:g}..{top:g} V in {setup.mode} mode ({len(outside)} levels; error 3310)",
                        source=source, observed=outside[0], limit=f"{bottom:g}..{top:g}")
        entry = channel_envelope(ctx, ch)
        peak = max((abs(v) for v in levels), default=0.0)
        if entry is not None and peak > entry.max_abs_v:
            yield block(f"channel {ch}: waveform level {peak:g} V exceeds the channel envelope {entry.max_abs_v:g} V "
                        "(the guard would refuse it)", subject=entry.role,
                        source=env.plan(f"envelope.channels.{ch}.max_abs_v"), observed=peak, limit=entry.max_abs_v)


def _wg_sequences(program: WaveformProgram, source: str) -> Iterator[Finding]:
    spec = WGFMU_SPEC
    low, high = spec.sequence_count
    for ch, items in sorted(program.sequences.items()):
        if len(items) > spec.max_sequences:
            yield block(f"channel {ch}: {len(items)} sequences exceed {spec.max_sequences} (error 3305)",
                        source=source, observed=len(items), limit=spec.max_sequences)
        for name, count in items:
            if not low <= round(count) <= high:
                yield block(f"channel {ch}: sequence count {count:g} of pattern {name} is outside 1..{high:g} "
                            "(error 3309)", source=source, observed=count, limit=f"1..{high:g}")
            if not program.patterns[name].vectors:
                yield block(f"channel {ch}: pattern {name} has no vectors (error 3306)", source=source,
                            observed=name, limit="at least one vector")


def _wg_events(program: WaveformProgram, source: str) -> Iterator[Finding]:
    spec = WGFMU_SPEC
    for event in program.events:
        duration = program.patterns[event.pattern].duration_s
        label = f"event {event.event} on pattern {event.pattern}"
        if not on_grid(event.t, spec.grid_s):
            yield block(f"{label}: time {event.t:g} s is not on the 10 ns grid", source=source, observed=event.t,
                        limit=spec.grid_s)
        if isinstance(event, MeasureEvent):
            yield from _measure_event(event, label, duration, source)
        else:
            yield from _range_event(program, event, label, duration, source)
    for name in program.patterns:
        times = sorted(e.t for e in program.range_events(name))
        if len(times) >= 3:
            close = [b - a for a, b in itertools.pairwise(times) if b - a <= spec.range_event_spacing_s]
            if close:
                yield block(f"pattern {name}: {len(times)} range events with adjacent ones {close[0]:g} s apart; "
                            "three or more need more than 2 us between them (WG p128 (4-58))", source=source,
                            observed=close[0], limit=spec.range_event_spacing_s)


def _measure_event(event: MeasureEvent, label: str, duration: float, source: str) -> Iterator[Finding]:
    spec = WGFMU_SPEC
    low, high = spec.interval_s
    if not (low <= event.interval <= high and on_grid(event.interval, spec.grid_s)):
        yield block(f"{label}: interval {event.interval:g} s is not {low:g}..{high:g} s on the 10 ns grid "
                    "(error 3312)", source=source, observed=event.interval, limit=f"{low:g}..{high:g}")
    a_low, a_high = spec.average_s
    if event.average != 0 and not (a_low <= event.average <= a_high and on_grid(event.average, spec.grid_s)):
        yield block(f"{label}: average {event.average:g} s is neither 0 nor {a_low:g}..{a_high:g} s on the 10 ns grid "
                    "(error 3315)", source=source, observed=event.average, limit=f"0 or {a_low:g}..{a_high:g}")
    if event.average > event.interval:
        yield block(f"{label}: average {event.average:g} s exceeds the interval {event.interval:g} s (error 3316)",
                    source=source, observed=event.average, limit=event.interval)
    if event.end_s > duration + _TOL:
        yield block(f"{label}: ends at {event.end_s:g} s, after its pattern's {duration:g} s", source=source,
                    observed=event.end_s, limit=duration)


def _range_event(program: WaveformProgram, event: RangeEvent, label: str, duration: float,
                 source: str) -> Iterator[Finding]:
    if event.t > duration + _TOL:
        yield block(f"{label}: time {event.t:g} s lies after its pattern's {duration:g} s", source=source,
                    observed=event.t, limit=duration)
    for ch, items in sorted(program.sequences.items()):
        if any(name == event.pattern for name, _ in items):
            setup = program.channels[ch]
            if setup.mode != "fastiv" or setup.measure != "current":
                yield block(f"{label}: range events need Fast IV current measurement; channel {ch} is "
                            f"{setup.mode}/{setup.measure} (WG p128 (4-58))", source=source,
                            observed=f"{setup.mode}/{setup.measure}", limit="fastiv/current")
    for measure in program.measure_events(event.pattern):
        if measure.average <= 0 or not measure.t <= event.t < measure.end_s:
            continue
        k = math.floor((event.t - measure.t) / measure.interval + 1e-9)
        start = measure.t + k * measure.interval
        if k < measure.points and start - _TOL <= event.t < start + measure.average - _TOL:
            yield block(f"{label}: at {event.t:g} s it falls inside an averaging window of event {measure.event} "
                        "(range events must lie outside averaging; WG p128 (4-58))", source=source,
                        observed=event.t, limit=f"outside {start:g}..{start + measure.average:g} s")


def _wg_points_and_envelope(ctx: RuleContext, env: RuleEnv, program: WaveformProgram,
                            spec_source: str) -> Iterator[Finding]:
    spec = WGFMU_SPEC
    policy_points = ctx.policy.run_limits.max_points.wgfmu
    if policy_points <= spec.max_points:
        max_points, points_source = policy_points, env.policy("run_limits.max_points.wgfmu")
    else:
        max_points, points_source = spec.max_points, spec_source
    waveform = {norm_channel(ch): limits for ch, limits in ctx.plan.envelope.waveform.items()}
    for ch in sorted(program.sequences):
        points = program.points(ch)
        if points > max_points:
            yield block(f"channel {ch}: {points} stored values exceed {max_points} per channel (read back in chunks "
                        "or reduce points/RAW data)", source=points_source, observed=points, limit=max_points)
        limits = waveform.get(norm_channel(ch))
        if limits is None:
            continue
        where = env.plan(f"envelope.waveform.{ch}")
        vectors = max((len(program.patterns[n].vectors) for n in program.channel_patterns(ch)), default=0)
        total = program.sequence_time_s(ch)
        for label, value, limit in (("vectors per pattern", vectors, limits.max_vectors),
                                    ("stored values", points, limits.max_points),
                                    ("output time (s)", total, limits.total_time_s)):
            if value > limit + (_TOL if isinstance(limit, float) else 0):
                yield block(f"channel {ch}: {label} {value:g} exceed the compiled waveform envelope {limit:g} (the "
                            "guard would refuse it)", source=where, observed=value, limit=limit)
        if not math.isclose(limits.grid_s, spec.grid_s, rel_tol=1e-12):
            yield block(f"channel {ch}: the waveform envelope's grid {limits.grid_s:g} s is not the WGFMU's 10 ns",
                        source=where, observed=limits.grid_s, limit=spec.grid_s)
