"""MFCMU FLEX builders and constants (blueprint v2 2.5): measurement parameter, signal, ranging, A/D converter,
monitor output, the sweep/pulse/sampling sources of measurement modes 18-26, phase compensation and the
open/short/load data correction.

Part of ``driver/flex/``, the only package that spells FLEX mnemonics in string literals; see ``core.py`` for the
conventions (one command per string, syntax-domain checks only, page citations). The measurement modes themselves
(``MM 17`` ... ``MM 26``) are built by ``core.mm``. A few builders accept less than the manual allows, on purpose:
the DC bias commands (``DCV``, ``WDCV``, ``PDCV``, ``PWDCV``, ``MDCV``) take the MFCMU's own +-25 V only, because a
bias above 25 V comes from an SMU behind the SCUU and is out of scope (blueprint v2 1.2, MFCMU row); ``WDCV``
therefore never carries the SMU-only compliance parameter. Module capabilities, envelopes and policy are checked by
``driver/modules.py`` (``CMU_SPEC``), ``driver/guard.py`` (``check_ac``) and ``rules/`` (R-CMU-01, R-CORR-01).

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages, chapter 4 printed 4-N =
PDF N + 318). Parameter tables: Table 4-16 measurement parameters (PDF 347), Table 4-17 fixed ranges, Table 4-18
frequencies (PDF 348).
"""

from __future__ import annotations

import math
from typing import Final

from b1500_test_agent.driver.flex.core import _channel, _choice, _int, _num
from b1500_test_agent.models.station import CorrectionFunction

# -- Parameter domains -------------------------------------------------------------------------------------------

IMP_MODES: Final[dict[int, tuple[str, str]]] = {
    1: ("R", "X"), 2: ("G", "B"), 10: ("Z", "theta_rad"), 11: ("Z", "theta_deg"), 20: ("Y", "theta_rad"),
    21: ("Y", "theta_deg"), 100: ("Cp", "G"), 101: ("Cp", "D"), 102: ("Cp", "Q"), 103: ("Cp", "Rp"),
    200: ("Cs", "Rs"), 201: ("Cs", "D"), 202: ("Cs", "Q"), 300: ("Lp", "G"), 301: ("Lp", "D"), 302: ("Lp", "Q"),
    303: ("Lp", "Rp"), 400: ("Ls", "Rs"), 401: ("Ls", "D"), 402: ("Ls", "Q"),
}  # fmt: skip
"""``IMP`` measurement modes and their (primary, secondary) parameters (Table 4-16, PDF 347); initial 100 (Cp-G)."""

IMP_INITIAL = 100
"""``IMP`` initial setting: Cp-G (PG PDF 441; Table 2-13, PDF 180)."""

CMU_FREQ_HZ: Final = (1.0e3, 5.0e6)
"""MFCMU output signal frequency span for ``FC``, ``WFC`` and ``CORRL`` (Table 4-18, PDF 348): 1 kHz to 5 MHz."""

CMU_MAX_AC_V = 0.25
"""Largest oscillator level of ``ACV``/``WACV``: 250 mV (PG PDF 354-355, 547)."""

CMU_MAX_DC_V = 25.0
"""Largest DC bias of the MFCMU itself (``DCV``, ``WDCV``, ``PDCV``, ``PWDCV``, ``MDCV``; PG PDF 390-391)."""

CMU_MAX_STEPS = 1001
"""Largest number of steps of the MFCMU sweeps ``WDCV``, ``WFC``, ``WACV``, ``PWDCV`` (PG PDF 547-550, 490)."""

RC_MODES: Final[dict[int, str]] = {0: "auto", 2: "fixed"}
"""``RC`` ranging modes (PG PDF 500): 0 auto ranging (initial setting), 2 fixed range."""

RC_RANGES_OHM: Final = (50.0, 100.0, 300.0, 1e3, 3e3, 1e4, 3e4, 1e5, 3e5)
"""Fixed MFCMU measurement ranges (Table 4-17, PDF 348): the ``range`` value selects the largest one not above it;
10 k/30 kOhm exist only up to 2 MHz, 100 k/300 kOhm only up to 200 kHz."""

ACT_N_LIMITS: Final[dict[int, tuple[int, int]]] = {0: (1, 1023), 2: (1, 100)}
"""``ACT`` N per averaging mode (PG PDF 354): mode 0 (auto, initial) 1-1023 (initial N 2), mode 2 (power-line
cycles) 1-100."""

ADJ_MODES: Final[dict[int, str]] = {0: "auto", 1: "manual", 2: "load_adaptive"}
"""``ADJ`` phase compensation modes (PG PDF 355): 0 auto (initial setting), 1 manual (``ADJ?`` measures the data),
2 load adaptive (compensated before every measurement)."""

ADJ_MANUAL = 1
"""``ADJ`` mode that lets ``ADJ? chnum,1`` measure the phase compensation data (PG PDF 355; error 680 otherwise)."""

ADJ_READ_LAST = 0
"""``ADJ?`` mode 0: return the result of the last phase compensation without measuring (PG PDF 355-356)."""

ADJ_MEASURE = 1
"""``ADJ?`` mode 1: measure the phase compensation data (about 30 s, terminals open; PG PDF 355-356)."""

ADJ_RESULTS: Final[dict[int, str]] = {
    0: "phase compensation measurement was normally completed",
    1: "phase compensation measurement failed",
    2: "phase compensation measurement was aborted",
    3: "phase compensation measurement has not been performed",
}
"""``ADJ?`` answers (PG PDF 356, printed 4-38)."""

CORRECTION_CODES: Final[dict[CorrectionFunction, int]] = {"open": 1, "short": 2, "load": 3}
"""``CORRST``/``CORRST?``/``CORR?``/``DCORR`` correction mode: 1 open, 2 short, 3 load (PG PDF 388, printed 4-70)."""

CORR_RESULTS: Final[dict[int, str]] = {
    0: "correction data measurement completed successfully",
    1: "correction data measurement failed",
    2: "correction data measurement aborted",
}
"""``CORR?`` answers (PG PDF 383, printed 4-65)."""

DCORR_MODES: Final[dict[CorrectionFunction, int]] = {"open": 100, "short": 400, "load": 400}
"""``DCORR`` reference-value mode per standard (PG PDF 389): 100 Cp-G (open standard: Cp in F, G in S), 400 Ls-Rs
(short or load standard: Ls in H, Rs in Ohm)."""

CLCORR_MODES: Final[dict[int, str]] = {1: "clear", 2: "default_frequencies"}
"""``CLCORR`` options (PG PDF 379): 1 clears the frequency list, 2 also loads ``CLCORR_DEFAULT_FREQS_HZ``."""

CLCORR_DEFAULT_FREQS_HZ: Final = (
    1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6, 1.2e6, 1.5e6, 2e6, 2.5e6, 2.7e6, 3e6, 3.2e6, 3.5e6, 3.7e6,
    4e6, 4.2e6, 4.5e6, 5e6,
)  # fmt: skip
"""The default correction frequencies ``CLCORR chnum,2`` sets (PG PDF 379, printed 4-61)."""

SWEEP_MODES: Final[dict[int, str]] = {1: "linear", 2: "log", 3: "linear_double", 4: "log_double"}
"""Sweep modes of ``WDCV``, ``WFC``, ``WACV`` (PG PDF 547-550): single stair start-stop, double stair
start-stop-start; ``PWDCV`` takes the linear ones (1, 3) only (PDF 490)."""

LRN_ADJ_MODE = 90
"""``*LRN? 90``: the MFCMU phase compensation mode, ``ADJ chnum,mode`` (PG PDF 452, printed 4-134)."""

LRN_ADJ_ITEM = "ADJ"
"""The item name of the ``*LRN? 90`` answer (PG PDF 452)."""

PTDCV_MIN_WIDTH_S = 8e-3
"""Shortest ``PTDCV`` pulse width (PG PDF 488): 8 ms above 200 kHz; 10 ms above 10 kHz and 50 ms up to 10 kHz are
frequency-dependent limits checked at the measurement (error 284)."""


def _real(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _within(value: float, low: float, high: float, name: str, unit: str) -> float:
    number = _real(value, name)
    if not low <= number <= high:
        raise ValueError(f"{name} must be {low:g} to {high:g} {unit}, got {value!r}")
    return number


def _dc(value: float, name: str) -> float:
    number = _real(value, name)
    if abs(number) > CMU_MAX_DC_V:
        raise ValueError(f"{name} must be within +-{CMU_MAX_DC_V:g} V (MFCMU), got {value!r}")
    return number


def _steps(steps: int, name: str) -> int:
    if not 1 <= _int(steps, name) <= CMU_MAX_STEPS:
        raise ValueError(f"{name} must be 1 to {CMU_MAX_STEPS}, got {steps}")
    return steps


def _log_ok(mode: int, start: float, stop: float, what: str) -> None:
    if mode in (2, 4) and (start == 0 or stop == 0 or (start > 0) != (stop > 0)):
        raise ValueError(f"a log {what} sweep needs non-zero start and stop of the same polarity")


def _timing(mnemonic: str, values: list[float], highs: list[float]) -> str:
    """``<mnemonic> hold,delay[,Sdelay[,Tdelay[,Mdelay]]]`` with optional parameters sent up to the last non-zero."""
    names = ["hold", "delay", "Sdelay", "Tdelay", "Mdelay"]
    for name, value, high in zip(names, values, highs, strict=True):
        if isinstance(value, bool) or not math.isfinite(float(value)) or not 0 <= float(value) <= high:
            raise ValueError(f"{mnemonic} {name} must be 0 to {high:g} s, got {value!r}")
    last = max(i for i, value in enumerate(values) if i < 2 or float(value) != 0)
    return f"{mnemonic} " + ",".join(_num(value) for value in values[: last + 1])


def _abort_post(mnemonic: str, abort: int, post: int) -> str:
    abort = _choice(abort, (1, 2), f"{mnemonic} abort")
    return f"{mnemonic} {abort},{_choice(post, (1, 2), f'{mnemonic} post')}"


def _corr(corr: CorrectionFunction, what: str) -> int:
    if corr not in CORRECTION_CODES:
        raise ValueError(f"{what} correction must be one of {sorted(CORRECTION_CODES)}, got {corr!r}")
    return CORRECTION_CODES[corr]


# -- Measurement parameter, signal, ranging, A/D converter, monitor -----------------------------------------------


def imp(mode: int) -> str:
    """``IMP mode``: the parameter pair the MFCMU returns (PG PDF 441, printed 4-123; Table 4-16, PDF 347), e.g. 100
    Cp-G (initial setting), 10/11 Z-theta in radian/degree, 200 Cs-Rs. Effective for MM 17-26 and ``TC``/``TTC``."""
    return f"IMP {_choice(mode, tuple(IMP_MODES), 'IMP mode')}"


def fc(ch: int, freq_hz: float) -> str:
    """``FC chnum,freq``: MFCMU output signal frequency (PG PDF 435, printed 4-117), 1 kHz to 5 MHz (Table 4-18,
    PDF 348). The channel must be enabled by ``CN`` (or connected by ``SSP``)."""
    low, high = CMU_FREQ_HZ
    return f"FC {_channel(ch)},{_num(_within(freq_hz, low, high, 'FC freq', 'Hz'))}"


def acv(ch: int, vrms: float) -> str:
    """``ACV chnum,voltage``: oscillator level (V rms) of the MFCMU output and start of the AC output (PG
    PDF 354-355, printed 4-36 to 4-37): 0 (initial setting) to 0.25 V, 1 mV step. The channel must be enabled."""
    return f"ACV {_channel(ch)},{_num(_within(vrms, 0.0, CMU_MAX_AC_V, 'ACV voltage', 'V'))}"


def dcv(ch: int, v: float) -> str:
    """``DCV chnum,voltage``: DC bias from the MFCMU (PG PDF 390-391, printed 4-72 to 4-73): 0 (initial) to +-25 V,
    1 mV resolution (the +-100 V SCUU form is out of scope). The channel must be enabled."""
    return f"DCV {_channel(ch)},{_num(_dc(v, 'DCV voltage'))}"


def rc(ch: int, mode: int, rng: int | None = None) -> str:
    """``RC chnum,mode[,range]``: MFCMU measurement ranging (PG PDF 500, printed 4-182): mode 0 auto ranging (initial
    setting, no range), 2 fixed with ``range`` an integer >= 0 that selects a Table 4-17 range (PDF 348). Cleared by
    ``CL``, ``CA``, ``IN``, ``*TST?``, ``*RST`` and a device clear."""
    _choice(mode, tuple(RC_MODES), "RC mode")
    if mode == 0:
        if rng is not None:
            raise ValueError("RC auto ranging (mode 0) takes no range")
        return f"RC {_channel(ch)},0"
    if rng is None or _int(rng, "RC range") < 0:
        raise ValueError(f"RC fixed ranging (mode 2) needs a range >= 0, got {rng!r}")
    return f"RC {_channel(ch)},2,{rng}"


def act(mode: int, n: int) -> str:
    """``ACT mode,N``: MFCMU A/D converter averaging (PG PDF 354, printed 4-36): mode 0 auto (samples = N x initial
    averaging; N 1-1023, initial 2) or 2 power-line cycles (time = N / line frequency; N 1-100)."""
    _choice(mode, tuple(ACT_N_LIMITS), "ACT mode")
    low, high = ACT_N_LIMITS[mode]
    if not low <= _int(n, "ACT N") <= high:
        raise ValueError(f"ACT N for mode {mode} must be {low} to {high}, got {n}")
    return f"ACT {mode},{n}"


def lmn(mode: int) -> str:
    """``LMN mode``: 1 adds the monitored oscillator level and DC bias (``Osc_level``, ``Dc_bias``) after each MFCMU
    parameter pair, 0 (initial) does not (PG PDF 445-446, printed 4-127 to 4-128); effective for MM 17, 18, 22, 23
    (data layout PDF 47-48)."""
    return f"LMN {_choice(mode, (0, 1), 'LMN mode')}"


# -- Sweep, pulse and sampling sources ----------------------------------------------------------------------------


def wdcv(ch: int, mode: int, start: float, stop: float, steps: int) -> str:
    """``WDCV chnum,mode,start,stop,step``: DC bias sweep of the C-V (DC bias) sweep, MM 18 (PG PDF 549-550, printed
    4-231 to 4-232): mode 1-4 (``SWEEP_MODES``), start/stop within +-25 V (log: same polarity, non-zero), 1 to 1001
    steps. The SMU-only compliance parameter is never sent (the MFCMU refuses it)."""
    _choice(mode, tuple(SWEEP_MODES), "WDCV mode")
    first, last = _dc(start, "WDCV start"), _dc(stop, "WDCV stop")
    _log_ok(mode, first, last, "DC bias")
    return f"WDCV {_channel(ch)},{mode},{_num(first)},{_num(last)},{_steps(steps, 'WDCV step')}"


def wtdcv(hold_s: float, delay_s: float, step_delay_s: float = 0.0, trigger_delay_s: float = 0.0,
          measure_delay_s: float = 0.0) -> str:
    """``WTDCV hold,delay[,Sdelay[,Tdelay[,Mdelay]]]``: C-V (DC bias) sweep timing in seconds (PG PDF 566-567,
    printed 4-248 to 4-249): hold 0-655.35, delay 0-65.535, Sdelay 0-1, Tdelay 0 to delay, Mdelay 0-65.535."""
    return _timing("WTDCV", [hold_s, delay_s, step_delay_s, trigger_delay_s, measure_delay_s],
                   [655.35, 65.535, 1.0, float(delay_s), 65.535])


def wmdcv(abort: int, post: int) -> str:
    """``WMDCV abort,post``: automatic abort (1 off, initial; 2 on: stop on NULL loop unbalance, IV amplifier
    saturation or ADC overflow, then the start value) and the DC bias after a normal end (1 start, 2 stop) of MM 18 and
    MM 20 (PG PDF 554-555, printed 4-236 to 4-237)."""
    return _abort_post("WMDCV", abort, post)


def wfc(ch: int, mode: int, start_hz: float, stop_hz: float, steps: int) -> str:
    """``WFC chnum,mode,start,stop,step``: frequency sweep of the C-f sweep, MM 22 (PG PDF 550-551, printed 4-232 to
    4-233): mode 1-4, 1 kHz to 5 MHz, 1 to 1001 steps."""
    _choice(mode, tuple(SWEEP_MODES), "WFC mode")
    low, high = CMU_FREQ_HZ
    first = _within(start_hz, low, high, "WFC start", "Hz")
    last = _within(stop_hz, low, high, "WFC stop", "Hz")
    return f"WFC {_channel(ch)},{mode},{_num(first)},{_num(last)},{_steps(steps, 'WFC step')}"


def wtfc(hold_s: float, delay_s: float, step_delay_s: float = 0.0, trigger_delay_s: float = 0.0,
         measure_delay_s: float = 0.0) -> str:
    """``WTFC hold,delay[,Sdelay[,Tdelay[,Mdelay]]]``: C-f sweep timing in seconds (PG PDF 567-568, printed 4-249
    to 4-250): hold 0-655.35, delay 0-655.35, Sdelay 0-1, Tdelay 0 to delay (at most 65.535), Mdelay 0-65.535."""
    return _timing("WTFC", [hold_s, delay_s, step_delay_s, trigger_delay_s, measure_delay_s],
                   [655.35, 655.35, 1.0, min(float(delay_s), 65.535), 65.535])


def wmfc(abort: int, post: int) -> str:
    """``WMFC abort,post``: automatic abort and the frequency after a normal end (1 start, 2 stop) of MM 22 (PG
    PDF 555-556, printed 4-237 to 4-238)."""
    return _abort_post("WMFC", abort, post)


def wacv(ch: int, mode: int, start_vrms: float, stop_vrms: float, steps: int) -> str:
    """``WACV chnum,mode,start,stop,step``: AC level sweep of the C-V (AC level) sweep, MM 23 (PG PDF 547, printed
    4-229): mode 1-4, 0 to 0.25 V rms (log: non-zero), 1 to 1001 steps."""
    _choice(mode, tuple(SWEEP_MODES), "WACV mode")
    first = _within(start_vrms, 0.0, CMU_MAX_AC_V, "WACV start", "V")
    last = _within(stop_vrms, 0.0, CMU_MAX_AC_V, "WACV stop", "V")
    _log_ok(mode, first, last, "AC level")
    return f"WACV {_channel(ch)},{mode},{_num(first)},{_num(last)},{_steps(steps, 'WACV step')}"


def wtacv(hold_s: float, delay_s: float, step_delay_s: float = 0.0, trigger_delay_s: float = 0.0,
          measure_delay_s: float = 0.0) -> str:
    """``WTACV hold,delay[,Sdelay[,Tdelay[,Mdelay]]]``: C-V (AC level) sweep timing in seconds (PG PDF 565-566,
    printed 4-247 to 4-248): hold 0-655.35, delay 0-655.35, Sdelay 0-1, Tdelay 0 to delay (at most 65.535), Mdelay
    0-65.535."""
    return _timing("WTACV", [hold_s, delay_s, step_delay_s, trigger_delay_s, measure_delay_s],
                   [655.35, 655.35, 1.0, min(float(delay_s), 65.535), 65.535])


def wmacv(abort: int, post: int) -> str:
    """``WMACV abort,post``: automatic abort and the AC level after a normal end (1 start, 2 stop) of MM 23 (PG
    PDF 553-554, printed 4-235 to 4-236)."""
    return _abort_post("WMACV", abort, post)


def pdcv(ch: int, base: float, pulse: float) -> str:
    """``PDCV chnum,base,pulse``: pulsed DC bias of the pulsed spot C measurement, MM 19 (PG PDF 484-485, printed
    4-166 to 4-167): base and pulse within +-25 V (MFCMU)."""
    return f"PDCV {_channel(ch)},{_num(_dc(base, 'PDCV base'))},{_num(_dc(pulse, 'PDCV pulse'))}"


def ptdcv(hold_s: float, width_s: float, period_s: float = 0.0, trigger_delay_s: float = 0.0) -> str:
    """``PTDCV hold,width,period[,Tdelay]``: pulse timing of MM 19/20 in seconds (PG PDF 487-488, printed 4-169 to
    4-170): hold 0-655.35, width 8 ms-655.35 s, period 0 (automatic: width + 2 ms up to 100 ms, else width + 10 ms)
    or 10 ms-655.35 s and at least width + 2 ms (width <= 100 ms) or width + 10 ms, Tdelay 0 to width. The period is
    always sent (the pulsed sweep CV form requires it)."""
    hold = _within(hold_s, 0.0, 655.35, "PTDCV hold", "s")
    width = _within(width_s, PTDCV_MIN_WIDTH_S, 655.35, "PTDCV width", "s")
    period = _real(period_s, "PTDCV period")
    if period != 0:
        gap = 2e-3 if width <= 0.1 else 10e-3
        if not (10e-3 <= period <= 655.35 and period >= width + gap - 1e-12):
            raise ValueError(f"PTDCV period must be 0 or 10 ms to 655.35 s and >= width + {gap * 1e3:g} ms, "
                             f"got {period_s!r}")
    tdelay = _within(trigger_delay_s, 0.0, width, "PTDCV Tdelay", "s")
    parts = [hold, width, period] + ([tdelay] if tdelay else [])
    return "PTDCV " + ",".join(_num(value) for value in parts)


def pwdcv(ch: int, mode: int, base: float, start: float, stop: float, steps: int) -> str:
    """``PWDCV chnum,mode,base,start,stop,step``: pulsed DC bias sweep of the pulsed sweep CV, MM 20 (PG
    PDF 489-490, printed 4-171 to 4-172): mode 1 linear single or 3 linear double (error 283 otherwise), base/start/stop
    within +-25 V (MFCMU), 1 to 1001 steps."""
    _choice(mode, (1, 3), "PWDCV mode")
    values = [_dc(base, "PWDCV base"), _dc(start, "PWDCV start"), _dc(stop, "PWDCV stop")]
    return f"PWDCV {_channel(ch)},{mode},{','.join(_num(v) for v in values)},{_steps(steps, 'PWDCV step')}"


def mdcv(ch: int, base: float, bias: float, post: float | None = None) -> str:
    """``MDCV chnum,base,bias[,post]``: DC bias source of the C-t sampling, MM 26 (PG PDF 467-468, printed 4-149 to
    4-150): base, bias and post within +-25 V (MFCMU); without ``post`` the previous post value stays."""
    values = [_dc(base, "MDCV base"), _dc(bias, "MDCV bias")] + ([] if post is None else [_dc(post, "MDCV post")])
    return f"MDCV {_channel(ch)},{','.join(_num(v) for v in values)}"


def mtdcv(hold_bias_s: float, interval_s: float, number: int, hold_base_s: float = 0.0) -> str:
    """``MTDCV h_bias,interval,number[,h_base]``: C-t sampling timing (PG PDF 476-477, printed 4-158 to 4-159):
    h_bias 0-655.35 s (bias output to the first sample), interval 8 ms-655.35 s (initial 10 ms), number 1-10001
    (initial 1000), h_base 0-655.35 s (base output before the bias)."""
    h_bias = _within(hold_bias_s, 0.0, 655.35, "MTDCV h_bias", "s")
    interval = _within(interval_s, 0.008, 655.35, "MTDCV interval", "s")
    if not 1 <= _int(number, "MTDCV number") <= 10001:
        raise ValueError(f"MTDCV number must be 1 to 10001, got {number}")
    h_base = _within(hold_base_s, 0.0, 655.35, "MTDCV h_base", "s")
    parts = [_num(h_bias), _num(interval), str(number)] + ([_num(h_base)] if h_base else [])
    return "MTDCV " + ",".join(parts)


# -- Phase compensation and data correction -----------------------------------------------------------------------


def adj(ch: int, mode: int) -> str:
    """``ADJ chnum,mode``: MFCMU phase compensation mode, 0 auto (initial), 1 manual, 2 load adaptive (PG PDF 355,
    printed 4-37; ``ADJ_MODES``). The command initializes the MFCMU."""
    return f"ADJ {_channel(ch)},{_choice(mode, tuple(ADJ_MODES), 'ADJ mode')}"


def adj_q(ch: int, mode: int) -> str:
    """``ADJ? chnum,mode``: MFCMU phase compensation (PG PDF 355-356, printed 4-37 to 4-38); answers 0-3
    (``ADJ_RESULTS``). Mode 1 (``ADJ_MEASURE``) measures the compensation data (about 30 s, terminals open at the
    device end, needs ``ADJ chnum,1`` first, resets the MFCMU); mode 0 (``ADJ_READ_LAST``) only returns the last
    result. The manual defaults an omitted mode to 1, so the mode is always written. TODO(verify) at bring-up L0/L6
    that mode 0 changes no output (PDF 355 says the command resets the MFCMU)."""
    return f"ADJ? {_channel(ch)},{_choice(mode, (0, 1), 'ADJ? mode')}"


def corrl(ch: int, freq_hz: float) -> str:
    """``CORRL chnum,freq``: add a frequency to the correction frequency list (PG PDF 384-385, printed 4-66 to
    4-67): 1 kHz to 5 MHz. Also turns the correction functions off and clears the correction data."""
    low, high = CMU_FREQ_HZ
    return f"CORRL {_channel(ch)},{_num(_within(freq_hz, low, high, 'CORRL freq', 'Hz'))}"


def corrl_q(ch: int, index: int | None = None) -> str:
    """``CORRL? chnum[,index]``: the number of frequencies in the correction frequency list, or (``index``, 1 = first)
    the frequency stored at that position (PG PDF 385, printed 4-67; the example ``CORRL? 9,4`` after ``CLCORR 9,2``
    answers 10000). A query: the list, the data and the functions stay as they are."""
    if index is None:
        return f"CORRL? {_channel(ch)}"
    if _int(index, "CORRL? index") < 1:
        raise ValueError(f"CORRL? index starts at 1, got {index}")
    return f"CORRL? {_channel(ch)},{index}"


def clcorr(ch: int, mode: int) -> str:
    """``CLCORR chnum,mode``: turn the correction functions off, clear the correction data and the frequency list;
    mode 2 then loads the default frequencies (PG PDF 379, printed 4-61; ``CLCORR_DEFAULT_FREQS_HZ``)."""
    return f"CLCORR {_channel(ch)},{_choice(mode, tuple(CLCORR_MODES), 'CLCORR mode')}"


def corr_q(ch: int, corr: CorrectionFunction) -> str:
    """``CORR? chnum,corr``: measure the open (1), short (2) or load (3) correction data at every listed frequency
    with the ``ACV`` level and answer 0 completed, 1 failed, 2 aborted (PG PDF 382-383, printed 4-64 to 4-65). The
    standard must be connected (or the terminals opened/shorted at the device end) by the human first."""
    return f"CORR? {_channel(ch)},{_corr(corr, 'CORR?')}"


def dcorr(ch: int, corr: CorrectionFunction, mode: int, primary: float, secondary: float) -> str:
    """``DCORR chnum,corr,mode,primary,secondary``: reference value of the open (mode 100: Cp in F, G in S), short
    or load standard (mode 400: Ls in H, Rs in Ohm) (PG PDF 389, printed 4-71; ``DCORR_MODES``). Turns the
    correction functions off and clears the correction data."""
    code = _corr(corr, "DCORR")
    if _int(mode, "DCORR mode") != DCORR_MODES[corr]:
        raise ValueError(f"DCORR mode for the {corr} standard is {DCORR_MODES[corr]}, got {mode}")
    return f"DCORR {_channel(ch)},{code},{mode},{_num(_real(primary, 'DCORR primary'))}," \
           f"{_num(_real(secondary, 'DCORR secondary'))}"


def dcorr_q(ch: int, corr: CorrectionFunction) -> str:
    """``DCORR? chnum,corr``: the reference value of the open (1), short (2) or load (3) standard, answered as
    ``mode,primary,secondary`` (PG PDF 389-390, printed 4-71 to 4-72; the example answers ``400,0.00001,49.8765`` after
    ``DCORR 9,3,400,0.00001,49.8765``). A query: unlike ``DCORR`` it clears no correction data."""
    return f"DCORR? {_channel(ch)},{_corr(corr, 'DCORR?')}"


def corrdt(ch: int, freq_hz: float, open_g: float, open_b: float, short_r: float, short_x: float, load_r: float,
           load_x: float) -> str:
    """``CORRDT chnum,freq,open_r,open_i,short_r,short_i,load_r,load_i``: set the correction data of one frequency
    directly (PG PDF 383-384, printed 4-65 to 4-66): open as G, B (S), short and load as R, X (Ohm). ``CORR?``
    replaces the data later."""
    low, high = CMU_FREQ_HZ
    freq = _within(freq_hz, low, high, "CORRDT freq", "Hz")
    values = [_real(v, name) for v, name in ((open_g, "open_r"), (open_b, "open_i"), (short_r, "short_r"),
                                              (short_x, "short_i"), (load_r, "load_r"), (load_x, "load_i"))]
    return f"CORRDT {_channel(ch)},{_num(freq)}," + ",".join(_num(v) for v in values)


def corrdt_q(ch: int, index: int) -> str:
    """``CORRDT? chnum,index``: the correction data stored for the ``index``-th frequency of the correction list (1 =
    first), answered as ``freq,open_r,open_i,short_r,short_i,load_r,load_i`` (open as G, B in S; short and load as
    R, X in Ohm; PG PDF 384, printed 4-66, example ``CORRDT? 9,1``). A query: the data and functions stay as they
    are."""
    if _int(index, "CORRDT? index") < 1:
        raise ValueError(f"CORRDT? index starts at 1, got {index}")
    return f"CORRDT? {_channel(ch)},{index}"


def corrst(ch: int, corr: CorrectionFunction, on: bool) -> str:
    """``CORRST chnum,corr,state``: switch the open (1), short (2) or load (3) correction function ON (1) or OFF (0)
    (PG PDF 387-388, printed 4-69 to 4-70). ON needs the correction data measured by ``CORR?`` first (error 685).
    ``*RST`` or a power cycle turns the functions off."""
    if not isinstance(on, bool):
        raise TypeError(f"CORRST state must be a bool, got {on!r}")
    return f"CORRST {_channel(ch)},{_corr(corr, 'CORRST')},{1 if on else 0}"


def corrst_q(ch: int, corr: CorrectionFunction) -> str:
    """``CORRST? chnum,corr``: whether the MFCMU open (1), short (2) or load (3) correction function is ON (answer
    1) or OFF (0) (PG PDF 388, printed 4-70). ``*RST`` or a power cycle turns the functions off. A query."""
    return f"CORRST? {_channel(ch)},{_corr(corr, 'CORRST?')}"
