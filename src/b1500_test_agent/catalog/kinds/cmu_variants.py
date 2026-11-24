"""The C-V variants of kind ``cmu_measure`` (blueprint v2 2.7 MM 19/20/22/23/26; WP8.4): pulsed spot C and pulsed
C-V, the C-f sweep, the C-V (AC level) sweep and C-t sampling. ``cmu_measure.py`` owns the program, the envelope, the
transaction frame and the table; this module parses each variant's role settings, builds its FLEX preview lines and
measures one frequency of it through the guarded driver (``B1500Driver`` MFCMU operations, WP8.1).

Settings of the ``cmu_high`` role per ``measurement`` (a literal role setting; ``$param`` references elsewhere):

- ``pulsed`` (MM 20, or MM 19 when ``points`` is 1): ``base`` (V, held between pulses), ``start``, ``stop``,
  ``points``, ``mode`` (``single``/``double``, linear only, PG p489 (4-171)), ``hold``, ``width`` and ``period`` (s;
  ``PTDCV hold,width,period`` on the 10 ms / 0.1 ms / 0.1 ms grid, period 0 = automatic ``width + 2 ms``, ``+ 10
  ms`` above 100 ms). The width must be at least 50 ms up to 10 kHz, 10 ms up to 200 kHz, 8 ms above (PG p488
  (4-170); error 284 otherwise). MM 19 needs ``stop`` = ``start`` (the one pulse level). Each point is measured
  during its pulse; the DC bias returns to ``base`` between pulses and after the sweep.
- ``cf`` (MM 22): the frequency list ``freqs`` IS the sweep: equally spaced in linear or logarithmic steps (the
  ``WFC`` grid from its first to its last element, each listed frequency within half the MFCMU setting resolution
  of the grid point, PG p348 Table 4-18), so the correction rule R-CORR-01 sees every frequency of the sweep (the
  correction recipes are run over that same list); ``dc``, ``mode``, ``hold``, ``delay`` (``WTFC``).
- ``acv`` (MM 23): ``ac`` is the start level and ``ac_stop`` the stop level (V rms), ``points``, ``sweep``
  (``linear``/``log``), ``mode``, ``dc``, ``hold``, ``delay`` (``WTACV``); one sweep per listed frequency.
- ``ct`` (MM 26): ``base`` (V, held ``hold_base`` s), ``dc`` (the bias, V), ``interval`` (s, 8 ms to 655.35 s on the
  1 ms grid, at least one MFCMU measurement time), ``points``, ``hold_bias`` (s from the bias step to the first
  sample, 10 ms grid); one transient per listed frequency, time stamps on (``TSC 1``, ``TSR`` before each
  transient). A transient whose sampling lasts at most ``CT_SINGLE_BLOCK_MAX_S`` is one ``MM 26`` block; a longer
  one is a chain of blocks of at most ``CT_SEGMENT_S`` each (R-RUN-02 segments): the first with the step
  (``MDCV ch,base,bias,bias``), then continuation blocks that hold the bias (``MDCV ch,bias,bias,bias``,
  ``h_base`` 0, the first sample one interval, rounded up to 10 ms, after their trigger); the time stamps run on
  through the chain (one ``TSR``), so ``t_s`` is exact across block boundaries (the same scheme as ``smu_sampling``,
  WP7.4). The post value is always the bias: the kind returns the MFCMU to 0 V at the end.

Each sweep (MM 20, 22, 23) has the automatic abort on (``WMDCV``/``WMFC``/``WMACV 2,1``: NULL loop unbalance, IV
amplifier saturation or overflow stop the sweep; the source returns to its start or base value). Every source value
passes ``OutputGuard.check_ac`` in the driver before anything is written.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from b1500_test_agent.catalog.kinds.smu_staircase import READ_TIMEOUT_MARGIN_S, drain_or_raise
from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import (
    AcLevelSweepSetup,
    CfSweepSetup,
    CmuBlock,
    CmuSweepTiming,
    CtSamplingSetup,
    PulsedCvSweepSetup,
    PulsedSpotCSetup,
)
from b1500_test_agent.models.common import StrictModel

if TYPE_CHECKING:
    from b1500_test_agent.catalog.kinds.cmu_measure import CmuProgram
    from b1500_test_agent.session.transaction import Transaction

Sweep = Literal["linear", "log"]
VARIANTS: Final = frozenset({"pulsed", "cf", "acv", "ct"})
"""``measurement`` values handled here (``spot`` and ``cv`` stay in ``cmu_measure.py``)."""

PULSE_GAP_S: Final = (2e-3, 10e-3)
"""Least ``period - width`` of ``PTDCV`` for widths up to and above ``PULSE_LONG_WIDTH_S`` (PG p488 (4-170))."""

PULSE_LONG_WIDTH_S: Final = 0.1

PULSE_GRID_S: Final = 1e-4
"""Resolution of the ``PTDCV`` width and period (0.1 ms; the hold has 10 ms, ``CT_HOLD_GRID_S``; PG p487 (4-169))."""

CT_SINGLE_BLOCK_MAX_S: Final = 60.0
"""A C-t transient whose sampling (``hold_bias + (points - 1) x interval``) lasts at most this long is one block."""

CT_SEGMENT_S: Final = 25.0
"""Longest sampling span of one block of a chained C-t transient (with ``FREQ_OVERHEAD_S`` within the default
``policy.run_limits.segment_max_s`` of 30 s)."""

CT_HOLD_GRID_S: Final = 0.01
"""Resolution of ``MTDCV h_bias``/``h_base`` (PG p476 (4-158))."""

CT_INTERVAL_GRID_S: Final = 0.001
"""Resolution of ``MTDCV interval`` (8 ms to 655.35 s; PG p476 (4-158))."""

CT_MIN_INTERVAL_S: Final = 0.008

CT_BLOCK_OVERHEAD_S: Final = 0.5
"""Allowance per C-t block for the setup, the trigger and the data transfer (estimate and read timeout)."""
CT_MAX_POINTS: Final = 10001
"""``MTDCV number`` limit per block (PG p477 (4-159)); the run total is bounded by R-RUN-01 (``max_points.cmu``)."""


class CtBlock(StrictModel):
    """One ``MM 26`` block of a C-t transient: ``number`` samples, ``h_bias_s`` from the trigger's bias step (or, in
    a continuation block, from its trigger) to the first sample, ``h_base_s`` of base level first; ``continuation``
    blocks hold the bias (no step)."""

    number: int = Field(ge=1, le=CT_MAX_POINTS)
    h_bias_s: float = Field(ge=0.0, le=655.35)
    h_base_s: float = Field(default=0.0, ge=0.0, le=655.35)
    continuation: bool = False


# -- small helpers -----------------------------------------------------------------------------------------------------


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise CompileError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _count(value: object, what: str, low: int, high: int) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CompileError(f"{what} must be an integer {low}..{high}, got {value!r}")
    return value


def _choice(value: object, choices: tuple[str, ...], what: str) -> str:
    if value not in choices:
        raise CompileError(f"{what} must be one of {list(choices)}, got {value!r}")
    return str(value)


def _on_grid(value: float, step: float) -> bool:
    return abs(value / step - round(value / step)) < 1e-6


def pulse_min_width_s(freq_hz: float) -> float:
    """Shortest ``PTDCV`` width at MFCMU frequency ``freq_hz``: 50 ms up to 10 kHz, 10 ms up to 200 kHz, else 8 ms
    (PG p488 (4-170))."""
    return 0.05 if freq_hz <= 1e4 else 0.01 if freq_hz <= 2e5 else flex.PTDCV_MIN_WIDTH_S


def pulse_period_s(width_s: float, period_s: float) -> float:
    """The pulse period in effect: ``period_s``, or for 0 the automatic ``width + 2 ms`` (``+ 10 ms`` above 100 ms)."""
    if period_s:
        return period_s
    return width_s + PULSE_GAP_S[0 if width_s <= PULSE_LONG_WIDTH_S else 1]


def frequency_resolution_hz(freq_hz: float) -> float:
    """MFCMU frequency setting resolution (PG p348 (4-30) Table 4-18): 1 mHz below 10 kHz, 10 mHz below 100 kHz,
    0.1 Hz below 1 MHz, 1 Hz up to 5 MHz."""
    return 1e-3 if freq_hz < 1e4 else 1e-2 if freq_hz < 1e5 else 0.1 if freq_hz < 1e6 else 1.0


def sweep_values(start: float, stop: float, points: int, sweep: Sweep) -> list[float]:
    """The ``points`` values of a single linear or logarithmic stair from ``start`` to ``stop``."""
    if points == 1:
        return [start]
    if sweep == "linear":
        return [start + (stop - start) * k / (points - 1) for k in range(points)]
    return [start * (stop / start) ** (k / (points - 1)) for k in range(points)]


def frequency_sweep(freqs: list[float], what: str) -> Sweep:
    """``linear`` or ``log``: the ``WFC`` stair the listed frequencies lie on (module docstring).

    Raises:
        CompileError: With fewer than two frequencies or when the list is on neither stair.
    """
    if len(freqs) < 2:
        raise CompileError(f"{what}: a C-f sweep needs at least two frequencies (first = start, last = stop)")
    for sweep in ("log", "linear"):
        grid = sweep_values(freqs[0], freqs[-1], len(freqs), sweep)  # type: ignore[arg-type]
        if all(abs(f - g) <= 0.5 * frequency_resolution_hz(g) + 1e-9 * g for f, g in zip(freqs, grid, strict=True)):
            return sweep  # type: ignore[return-value]
    raise CompileError(f"{what}: the C-f sweep frequencies must be equally spaced (linear) or equally spaced in "
                       f"log (one WFC stair from {freqs[0]:g} to {freqs[-1]:g} Hz, each value rounded to the MFCMU "
                       "setting resolution); list e.g. f1 * (f2/f1)**(k/(n-1)) for k = 0..n-1")


def ct_blocks(interval: float, points: int, h_bias: float, h_base: float) -> list[CtBlock]:
    """Split a C-t transient into ``MM 26`` blocks (module docstring)."""
    span = h_bias + (points - 1) * interval
    if span <= CT_SINGLE_BLOCK_MAX_S:
        return [CtBlock(number=points, h_bias_s=h_bias, h_base_s=h_base)]
    per = max(1, int(CT_SEGMENT_S // interval))
    first = max(1, min(per, int((CT_SEGMENT_S - h_bias) // interval) + 1))
    blocks = [CtBlock(number=min(first, points), h_bias_s=h_bias, h_base_s=h_base)]
    left = points - blocks[0].number
    h_next = round(math.ceil(interval / CT_HOLD_GRID_S - 1e-9) * CT_HOLD_GRID_S, 2)
    while left > 0:
        number = min(per, left)
        blocks.append(CtBlock(number=number, h_bias_s=h_next, continuation=True))
        left -= number
    return blocks


def block_span_s(program: CmuProgram, block: CtBlock) -> float:
    """Nominal time from a C-t block's trigger to the end of its last sample."""
    return block.h_base_s + block.h_bias_s + (block.number - 1) * program.interval_s + program.point_s


# -- settings ----------------------------------------------------------------------------------------------------------


def variant_fields(measurement: str, get: Callable[[str, object], object], high: str, freqs: list[float],
                   point_s: float) -> dict[str, object]:
    """``CmuProgram`` fields of one variant from the ``cmu_high`` role's settings (``get(key, default)``; module
    docstring)."""
    hold = _number(get("hold", 0.0), f"{high}.hold")
    if measurement == "pulsed":
        return _pulsed_fields(get, high, freqs, hold)
    if measurement == "cf":
        double = _choice(get("mode", "single"), ("single", "double"), f"{high}.mode") == "double"
        return {"dc_v": _number(get("dc", 0.0), f"{high}.dc"), "points": len(freqs), "double": double,
                "step_spacing": frequency_sweep(freqs, f"{high}.freqs"), "hold_s": hold,
                "delay_s": _number(get("delay", 0.0), f"{high}.delay")}
    if measurement == "acv":
        sweep = _choice(get("sweep", "linear"), ("linear", "log"), f"{high}.sweep")
        start = _number(get("ac"), f"{high}.ac")
        stop = _number(get("ac_stop"), f"{high}.ac_stop")
        if sweep == "log" and (start == 0 or stop == 0):
            raise CompileError(f"{high}: a log AC level sweep needs non-zero start and stop levels")
        double = _choice(get("mode", "single"), ("single", "double"), f"{high}.mode") == "double"
        return {"ac_stop": stop, "step_spacing": sweep, "double": double, "hold_s": hold,
                "points": _count(get("points"), f"{high}.points", 1, flex.CMU_MAX_STEPS),
                "dc_v": _number(get("dc", 0.0), f"{high}.dc"), "delay_s": _number(get("delay", 0.0), f"{high}.delay")}
    if measurement == "ct":
        return _ct_fields(get, high, hold, point_s)
    raise CompileError(f"{high}.measurement must be one of spot, cv, {', '.join(sorted(VARIANTS))}; got "
                       f"{measurement!r}")


def _pulsed_fields(get: Callable[[str, object], object], high: str, freqs: list[float],
                   hold: float) -> dict[str, object]:
    width = _number(get("width"), f"{high}.width")
    period = _number(get("period", 0.0), f"{high}.period")
    for name, value, grid in (("hold", hold, CT_HOLD_GRID_S), ("width", width, PULSE_GRID_S),
                              ("period", period, PULSE_GRID_S)):
        if not _on_grid(value, grid):
            raise CompileError(f"{high}.{name} {value!r} s is off the PTDCV resolution ({grid * 1e3:g} ms)")
    shortest = max(pulse_min_width_s(f) for f in freqs)
    if width < shortest - 1e-12:
        raise CompileError(f"{high}.width {width:g} s is below the {shortest * 1e3:g} ms the MFCMU needs at "
                           f"{min(freqs):g} Hz (PTDCV: 50 ms up to 10 kHz, 10 ms up to 200 kHz, else 8 ms)")
    gap = PULSE_GAP_S[0 if width <= PULSE_LONG_WIDTH_S else 1]
    if period and period < width + gap - 1e-12:
        raise CompileError(f"{high}.period {period:g} s must be 0 (automatic) or at least width + {gap * 1e3:g} ms")
    double = _choice(get("mode", "single"), ("single", "double"), f"{high}.mode") == "double"
    start, stop = _number(get("start"), f"{high}.start"), _number(get("stop"), f"{high}.stop")
    points = _count(get("points"), f"{high}.points", 1, flex.CMU_MAX_STEPS)
    if points == 1 and (double or stop != start):
        raise CompileError(f"{high}: one point is the pulsed spot C (MM 19) at one pulse level: single mode with "
                           f"stop = start, got {start:g}..{stop:g} V ({'double' if double else 'single'})")
    return {"base_v": _number(get("base"), f"{high}.base"), "start": start, "stop": stop, "points": points,
            "double": double, "hold_s": hold, "width_s": width, "period_s": period}


def _ct_fields(get: Callable[[str, object], object], high: str, hold_base: float, point_s: float) -> dict[str, object]:
    interval = _number(get("interval"), f"{high}.interval")
    if not CT_MIN_INTERVAL_S <= interval <= 655.35 or not _on_grid(interval, CT_INTERVAL_GRID_S):
        raise CompileError(f"{high}.interval must be 8 ms to 655.35 s on the 1 ms grid (MTDCV), got {interval!r}")
    if interval < point_s - 1e-12:
        raise CompileError(f"{high}.interval {interval * 1e3:g} ms is shorter than one MFCMU measurement "
                           f"({point_s * 1e3:g} ms with this integration): use a longer interval or integration short")
    h_bias = _number(get("hold_bias", 0.0), f"{high}.hold_bias")
    for name, value in (("hold_bias", h_bias), ("hold", hold_base)):
        if not 0.0 <= value <= 655.35 or not _on_grid(value, CT_HOLD_GRID_S):
            raise CompileError(f"{high}.{name} must be 0 to 655.35 s in 10 ms steps (MTDCV), got {value!r}")
    points = _count(get("points"), f"{high}.points", 1, CT_MAX_POINTS)
    return {"base_v": _number(get("base"), f"{high}.base"), "dc_v": _number(get("dc"), f"{high}.dc"),
            "interval_s": interval, "hold_s": hold_base,
            "ct_blocks": [b.model_dump() for b in ct_blocks(interval, points, h_bias, hold_base)]}


def check_variant(program: CmuProgram) -> None:
    """Build every driver setup and preview line of a variant program once (the driver's and the builders' domain
    checks: levels, timing, steps).

    Raises:
        ValueError: From the first setup or builder that refuses a value.
    """
    for freq in program.loop_freqs:
        if program.mode == "pulsed":
            pulsed_setup(program, freq)
        elif program.mode == "cf":
            cf_setup(program)
        elif program.mode == "acv":
            acv_setup(program, freq)
        else:
            for block in program.ct_blocks:
                ct_setup(program, freq, block)
        variant_preview(program, freq)


# -- the driver setups -------------------------------------------------------------------------------------------------


def pulsed_setup(program: CmuProgram, freq: float) -> PulsedSpotCSetup | PulsedCvSweepSetup:
    """The MM 19 (one point) or MM 20 setup of a pulsed program at ``freq``."""
    common = {"channel": program.channel, "base": program.base_v, "freq_hz": freq, "ac_vrms": program.ac_vrms,
              "hold_s": program.hold_s, "width_s": program.width_s, "period_s": program.period_s}
    if program.points == 1:
        return PulsedSpotCSetup(**common, pulse=program.start)
    return PulsedCvSweepSetup(**common, start=program.start, stop=program.stop, points=program.points,
                              double=program.double, auto_abort=True)


def cf_setup(program: CmuProgram) -> CfSweepSetup:
    """The MM 22 setup: one ``WFC`` stair over the listed frequencies."""
    return CfSweepSetup(channel=program.channel, points=program.points, sweep=program.step_spacing,
                        double=program.double, timing=CmuSweepTiming(hold_s=program.hold_s, delay_s=program.delay_s),
                        auto_abort=True, post="start", start_hz=program.freqs_hz[0], stop_hz=program.freqs_hz[-1],
                        ac_vrms=program.ac_vrms, dc_v=program.dc_v)


def acv_setup(program: CmuProgram, freq: float) -> AcLevelSweepSetup:
    """The MM 23 setup at ``freq``."""
    return AcLevelSweepSetup(channel=program.channel, points=program.points, sweep=program.step_spacing,
                             double=program.double, timing=CmuSweepTiming(hold_s=program.hold_s,
                                                                          delay_s=program.delay_s),
                             auto_abort=True, post="start", start_vrms=program.ac_vrms, stop_vrms=program.ac_stop,
                             freq_hz=freq, dc_v=program.dc_v)


def ct_setup(program: CmuProgram, freq: float, block: CtBlock) -> CtSamplingSetup:
    """The MM 26 setup of one block at ``freq`` (a continuation block holds the bias)."""
    base = program.dc_v if block.continuation else program.base_v
    return CtSamplingSetup(channel=program.channel, base=base, bias=program.dc_v, post=program.dc_v, freq_hz=freq,
                           ac_vrms=program.ac_vrms, hold_bias_s=block.h_bias_s, interval_s=program.interval_s,
                           number=block.number, hold_base_s=block.h_base_s)


# -- preview -----------------------------------------------------------------------------------------------------------


def variant_preview(program: CmuProgram, freq: float) -> list[str]:
    """The FLEX lines one frequency of a variant sends (as the driver's operations write them)."""
    ch = program.channel
    if program.mode == "pulsed":
        setup = pulsed_setup(program, freq)
        lines = [flex.mm(setup.mode, [ch]), flex.fc(ch, freq), flex.acv(ch, program.ac_vrms)]
        if isinstance(setup, PulsedSpotCSetup):
            return [*lines, flex.ptdcv(setup.hold_s, setup.width_s, setup.period_s),
                    flex.pdcv(ch, setup.base, setup.pulse), flex.XE]
        return [*lines, flex.wmdcv(2, 1), flex.ptdcv(setup.hold_s, setup.width_s, setup.period_s),
                flex.pwdcv(ch, 3 if setup.double else 1, setup.base, setup.start, setup.stop, setup.points), flex.XE]
    if program.mode == "cf":
        cf = cf_setup(program)
        return [flex.mm(22, [ch]), flex.fc(ch, cf.start_hz), flex.acv(ch, cf.ac_vrms), flex.dcv(ch, cf.dc_v),
                flex.wtfc(*cf.timing.values()), flex.wmfc(2, 1),
                flex.wfc(ch, cf.sweep_mode, cf.start_hz, cf.stop_hz, cf.points), flex.XE]
    if program.mode == "acv":
        acv = acv_setup(program, freq)
        return [flex.mm(23, [ch]), flex.fc(ch, freq), flex.dcv(ch, acv.dc_v), flex.wtacv(*acv.timing.values()),
                flex.wmacv(2, 1), flex.wacv(ch, acv.sweep_mode, acv.start_vrms, acv.stop_vrms, acv.points), flex.XE]
    lines = [flex.tsr()]
    for block in program.ct_blocks:
        ct = ct_setup(program, freq, block)
        lines += [flex.mm(26, [ch]), flex.fc(ch, freq), flex.acv(ch, ct.ac_vrms),
                  flex.mtdcv(ct.hold_bias_s, ct.interval_s, ct.number, ct.hold_base_s),
                  flex.mdcv(ch, ct.base, ct.bias, ct.post), flex.XE]
    return lines


# -- measurement -------------------------------------------------------------------------------------------------------


def measure_sweep_variant(tx: Transaction, program: CmuProgram, freq: float) -> CmuBlock:
    """One pulsed, C-f or AC-level measurement at ``freq``: guarded setup, ``ERRX?`` drain, ``XE`` and one read."""
    driver = tx.driver
    if program.mode == "pulsed":
        setup = pulsed_setup(program, freq)
        if isinstance(setup, PulsedSpotCSetup):
            driver.pulsed_spot_c(setup)
        else:
            driver.pulsed_cv_sweep(setup)
        mode, steps = setup.mode, (1 if isinstance(setup, PulsedSpotCSetup) else setup.steps)
    elif program.mode == "cf":
        cf = cf_setup(program)
        driver.cf_sweep(cf)
        mode, steps = 22, cf.steps
    else:
        acv = acv_setup(program, freq)
        driver.ac_level_sweep(acv)
        mode, steps = 23, acv.steps
    drain_or_raise(tx, f"the {program.mode} setup at {freq:g} Hz")
    block = driver.measure_cmu(driver.cmu_layout(mode), steps=steps, timeout_s=program.timeout_s())
    tx.check_abort()
    return block


def measure_ct_block(tx: Transaction, program: CmuProgram, freq: float, index: int) -> CmuBlock:
    """Block ``index`` of the C-t transient at ``freq`` (``TSR`` before the first: the time stamps of the chain count
    from it); an error of the previous block stops the chain at the ``ERRX?`` drain."""
    driver = tx.driver
    block = program.ct_blocks[index]
    if index == 0:
        driver.reset_timer()
    driver.ct_sampling(ct_setup(program, freq, block))
    drain_or_raise(tx, f"C-t block {index + 1} at {freq:g} Hz")
    timeout = 2.0 * (block_span_s(program, block) + CT_BLOCK_OVERHEAD_S) + READ_TIMEOUT_MARGIN_S
    measured = driver.measure_cmu(driver.cmu_layout(26, timestamp=True), steps=block.number, timeout_s=timeout)
    tx.check_abort()
    return measured
