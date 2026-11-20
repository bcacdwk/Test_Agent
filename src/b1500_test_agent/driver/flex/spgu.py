"""HV-SPGU FLEX builders and constants: operation mode, PG pulse setup, load, output control, pulse switch, trigger,
terminal-voltage measurement and the ALWG pattern/sequence data (blueprint v2 2.5).

Builders check only the syntax domain of the manual (parameter ranges); the module spec (resolutions, the
width/leading/period relations, open-load levels), the envelope and the policy are checked by ``driver/modules.py``,
``driver/guard.py`` and ``rules/``. Like ``cn`` (never a bare ``CN``), two builders accept less than the manual
allows, on purpose: ``sprm`` never builds the free-run mode 0 (blueprint v2 R-PULSE-01: an SPGU output is always
bounded by a count or a duration), and ``corrser_q`` exists for both modes but ``SpguOps`` sends only mode 0 (measure,
never set ``SER`` itself: the guard checks every load change).

``alw``/``als`` return the command header and the binary block that must follow it on the bus (``(header,
block)``): ALWG pattern data (PG PDF 150, printed 2-62, Table 2-4) and sequence data (PG PDF 151, printed 2-63,
Table 2-5), big endian, levels in 1 uV counts (two's complement; +-40 V, 1 mV resolution), incremental times in
1 ns counts (10 ns to 671.08863 ms, 10 ns resolution) with the pulse-switch state in the top bit.

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages, chapter 4 printed 4-N =
PDF N + 318).
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from typing import Final

from b1500_test_agent.driver.flex.core import MAX_CHANNELS_MM, _channel, _channels, _choice, _int, _num
from b1500_test_agent.models.spgu import AlwgPattern

# -- Constants ---------------------------------------------------------------------------------------------------

SPST_Q = "SPST?"
"""Waveform output state of the SPGU (PG PDF 513-514, printed 4-195 to 4-196): 0 = pulse output or ALWG sequence
output inactive, 1 = active. One answer for the mainframe, no channel parameter; the output stays active while a
channel performs a pulse or ALWG output (PG PDF 142, printed 2-54). A query: it changes no setting."""

SPST_STATES = frozenset({0, 1})
"""The ``SPST?`` answers (PDF 513-514)."""

SRP = "SRP"
"""Start the SPGU outputs (PG PDF 518, printed 4-200): every channel set up by ``SPUPD`` starts, in channel order,
the pulse and waveform outputs simultaneously; ``SPST?`` then reads 1 until a stop condition (PG PDF 142)."""

SPP = "SPP"
"""Stop every SPGU channel output and trigger output simultaneously (PG PDF 511, printed 4-193); the outputs go to the
base level (PG mode) or the waveform's initial level (ALWG). It does not stop a DC bias output."""

SIM_PG = 0
"""``SIM`` mode 0: PG (pulse generator) mode, the initial setting (PG PDF 508; Table 2-12, PDF 179)."""

SIM_ALWG = 1
"""``SIM`` mode 1: ALWG (arbitrary linear waveform generator) mode (PG PDF 508)."""

SPM_MODES: Final[dict[int, str]] = {
    0: "DC voltage output",
    1: "2-level pulse output using pulse signal source 1",
    2: "2-level pulse output using pulse signal source 2",
    3: "3-level pulse output using pulse signal sources 1 and 2",
}
"""``SPM`` channel output modes (PG PDF 510-511, printed 4-192 to 4-193)."""

SPRM_COUNT = 1
"""``SPRM`` mode 1: output ``condition`` pulses (PG mode) or sequences (ALWG mode), 1 to 1,000,000 (PG PDF 512-513)."""

SPRM_DURATION = 2
"""``SPRM`` mode 2: output for ``condition`` seconds, 1E-6 to 31,556,926 s, 10 ns resolution (PG PDF 512-513)."""

SPRM_MAX_COUNT = 1_000_000
"""Largest ``SPRM 1`` count (PG PDF 513)."""

SPRM_DURATION_S = (1e-6, 31_556_926.0)
"""``SPRM 2`` duration range in seconds (PG PDF 513)."""

SPGU_LEVEL_V = 40.0
"""``SPV`` base/peak and ALWG level range +-40 V, 1 mV resolution (PG PDF 516; Table 2-4, PDF 150)."""

SER_LOAD_OHM = (0.1, 1e6)
"""``SER`` load impedance range in Ohm, initial 50 Ohm (PG PDF 507)."""

CORRSER_MEASURE_ONLY = 0
"""``CORRSER?`` mode 0: measure the terminal voltage and return the load, without setting ``SER`` (PG PDF 386)."""

ALWG_MAX_PATTERNS = 512
"""Patterns per channel and pattern cycles per sequence: 1 to 512 (PG PDF 150-151, Tables 2-4 and 2-5)."""

ALWG_MAX_VECTORS = 1024
"""Total vectors of one channel's pattern data: at most ``1024 - patterns`` (PG PDF 150, Table 2-4)."""

ALWG_MAX_REPEAT = 1_048_576
"""Repeat count of one pattern cycle: 1 to 1,048,576 (PG PDF 151, Table 2-5)."""

ALWG_DT_NS = (10, 671_088_630)
"""Incremental vector time in 1 ns counts: 10 ns to (2^26 - 1) x 10 ns, 10 ns resolution (PG PDF 150)."""

# -- Syntax helpers ----------------------------------------------------------------------------------------------


def _real(value: float, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if not low <= value <= high:
        raise ValueError(f"{name} must be {low:g} to {high:g}, got {value!r}")
    return float(value)


def _level_counts(value: float, name: str) -> int:
    """A level in 1 uV counts, on the 1 mV resolution, within +-40 V (Table 2-4, PDF 150)."""
    level = _real(value, -SPGU_LEVEL_V, SPGU_LEVEL_V, name)
    millivolts = round(level * 1e3)
    if abs(level * 1e3 - millivolts) > 1e-6:
        raise ValueError(f"{name} {value!r} V is not on the 1 mV resolution")
    return millivolts * 1000


def _time_counts(value: float, name: str) -> int:
    """An incremental vector time in 1 ns counts: 10 ns to 671.08863 ms on the 10 ns grid (Table 2-4, PDF 150)."""
    low, high = ALWG_DT_NS
    seconds = _real(value, low * 1e-9, high * 1e-9 * (1 + 1e-12), name)
    tens = round(seconds * 1e8)
    if abs(seconds * 1e8 - tens) > 1e-6 or not low <= tens * 10 <= high:
        raise ValueError(f"{name} {value!r} s is not a multiple of 10 ns within 10 ns to 671.08863 ms")
    return tens * 10


# -- Builders ------------------------------------------------------------------------------------------------------


def sim(mode: int) -> str:
    """``SIM mode``: SPGU operation mode of every SPGU of the mainframe, 0 = PG (``SIM_PG``), 1 = ALWG (``SIM_ALWG``)
    (PG PDF 508, printed 4-190). It also makes the SPGU channels whose output switch is on output 0 V."""
    return f"SIM {_choice(mode, (SIM_PG, SIM_ALWG), 'SIM mode')}"


def spm(ch: int, mode: int) -> str:
    """``SPM chnum,mode``: output mode of an SPGU channel (PG PDF 510-511, printed 4-192 to 4-193; ``SPM_MODES``):
    0 DC, 1/2 two-level pulse from source 1/2, 3 three-level pulse from sources 1 and 2. PG mode only (``SIM 0``)."""
    return f"SPM {_channel(ch)},{_choice(mode, tuple(SPM_MODES), 'SPM mode')}"


def spt(ch: int, src: int, delay: float, width: float, leading: float, trailing: float | None = None) -> str:
    """``SPT chnum,src,delay,width,leading[,trailing]``: pulse timing of one pulse source (PG PDF 514-515, printed
    4-196 to 4-197; Figure 2-31, PDF 145): src 1 or 2; delay 0 to period - 20 ns; width 10 ns to period - 10 ns;
    leading/trailing 8 ns to 0.4 s (the leading time also serves as trailing time when omitted). The period
    relations and the 2.5 ns/2 ns resolutions are module-spec checks (``SPGU_SPEC``). PG mode only."""
    parts = [str(_channel(ch)), str(_choice(src, (1, 2), "SPT src")),
             _num(_real(delay, 0.0, 10.0 - 2e-8, "SPT delay")), _num(_real(width, 1e-8, 10.0 - 1e-8, "SPT width")),
             _num(_real(leading, 8e-9, 0.4, "SPT leading"))]
    if trailing is not None:
        parts.append(_num(_real(trailing, 8e-9, 0.4, "SPT trailing")))
    return "SPT " + ",".join(parts)


def spv(ch: int, src: int, base: float, peak: float | None = None) -> str:
    """``SPV chnum,src,base[,peak]``: levels of one signal source (PG PDF 516-517, printed 4-198 to 4-199): src 0 DC
    bias, 1/2 pulse source; base and peak -40 to 40 V, 1 mV resolution (the base serves as peak when omitted; a DC
    source has no peak). PG mode only. The level actually reaching the DUT depends on ``SER`` (``ser``)."""
    _choice(src, (0, 1, 2), "SPV src")
    parts = [str(_channel(ch)), str(src), _num(_real(base, -SPGU_LEVEL_V, SPGU_LEVEL_V, "SPV base"))]
    if peak is not None:
        if src == 0:
            raise ValueError("SPV: a DC bias source (src 0) has no peak level")
        parts.append(_num(_real(peak, -SPGU_LEVEL_V, SPGU_LEVEL_V, "SPV peak")))
    return "SPV " + ",".join(parts)


def spper(period: float) -> str:
    """``SPPER period``: pulse period of every SPGU channel, 2E-8 to 10 s, 10 ns resolution, initial 1 us (PG PDF 512,
    printed 4-194)."""
    return f"SPPER {_num(_real(period, 2e-8, 10.0, 'SPPER period'))}"


def sprm(mode: int, condition: float) -> str:
    """``SPRM mode,condition``: output operation mode of every SPGU channel (PG PDF 512-513, printed 4-194 to 4-195):
    1 = count (``condition`` pulses or ALWG sequences, 1 to 1,000,000), 2 = duration (``condition`` seconds, 1E-6 to
    31,556,926). Mode 0 (free run until ``SPP``; the initial setting after ``*RST``, PDF 179) is never built."""
    if _choice(mode, (SPRM_COUNT, SPRM_DURATION), "SPRM mode (free run 0 is never built)") == SPRM_COUNT:
        if isinstance(condition, bool) or not isinstance(condition, int) or not 1 <= condition <= SPRM_MAX_COUNT:
            raise ValueError(f"SPRM count must be an integer 1 to {SPRM_MAX_COUNT}, got {condition!r}")
        return f"SPRM {mode},{condition}"
    low, high = SPRM_DURATION_S
    return f"SPRM {mode},{_num(_real(condition, low, high, 'SPRM duration'))}"


def ser(ch: int, load: float) -> str:
    """``SER chnum,loadZ``: load impedance of an SPGU channel, 0.1 Ohm to 1 MOhm, initial 50 Ohm (PG PDF 507, printed
    4-189); the output level is adjusted to it, so an open load sees ``|V| (SER + 50) / SER``."""
    low, high = SER_LOAD_OHM
    return f"SER {_channel(ch)},{_num(_real(load, low, high, 'SER load'))}"


def spupd(chs: Sequence[int]) -> str:
    """``SPUPD chnum[,chnum...]``: apply the setup of up to ten SPGU channels (PG PDF 515-516, printed 4-197 to
    4-198): the channels output their base level (PG mode) or the waveform's initial level (ALWG) until ``SRP``."""
    return "SPUPD " + ",".join(str(ch) for ch in _channels(chs, limit=MAX_CHANNELS_MM, required=True))


def odsw(ch: int, state: int, normal: int | None = None, delay: float | None = None,
         width: float | None = None) -> str:
    """``ODSW chnum,state[,normal[,delay,width]]``: pulse switch of an SPGU channel (PG PDF 478-479, printed 4-160 to
    4-161): state 0 disabled (initial) or 1 enabled; normal 0 normally open (initial) or 1 normally closed; PG mode
    only: delay 0 to period - 100 ns and width 100 ns to period - delay (10 ns resolution), given together."""
    parts = [str(_channel(ch)), str(_choice(state, (0, 1), "ODSW state"))]
    if normal is None:
        if delay is not None or width is not None:
            raise ValueError("ODSW: delay and width need the normal state")
        return "ODSW " + ",".join(parts)
    parts.append(str(_choice(normal, (0, 1), "ODSW normal")))
    if (delay is None) != (width is None):
        raise ValueError("ODSW: delay and width are given together")
    if delay is not None and width is not None:
        parts += [_num(_real(delay, 0.0, 10.0 - 1e-7, "ODSW delay")), _num(_real(width, 1e-7, 10.0, "ODSW width"))]
    return "ODSW " + ",".join(parts)


def stgp(ch: int, state: int) -> str:
    """``STGP chnum,state``: trigger output of the SPGU module that holds the channel (PG PDF 523-524, printed 4-205
    to 4-206): 0 off (initial), 1 with every pulse (PG) or sequence start (ALWG), 2 at ALWG pattern changes, 3 at
    every ALWG pattern start."""
    return f"STGP {_channel(ch)},{_choice(state, (0, 1, 2, 3), 'STGP state')}"


def corrser_q(ch: int, mode: int, delay: float, interval: float, count: int) -> str:
    """``CORRSER? chnum,mode,delay,interval,count``: measure the terminal voltage of one SPGU channel during the first
    pulse and return ``loadZ,voltage`` (PG PDF 385-386, printed 4-67 to 4-68): mode 0 measures only
    (``CORRSER_MEASURE_ONLY``), 1 also sets ``SER`` to the result; delay 0 to period - 5 us (10 ns), interval 5 us to
    1 ms (20 ns), count 1 to 65535; the period must exceed delay + interval x count. Active outputs stop; afterwards
    every SPGU channel outputs its base (initial) level."""
    _choice(mode, (0, 1), "CORRSER? mode")
    if _int(count, "CORRSER? count") < 1 or count > 65535:
        raise ValueError(f"CORRSER? count must be 1 to 65535, got {count}")
    return (f"CORRSER? {_channel(ch)},{mode},{_num(_real(delay, 0.0, 10.0 - 5e-6, 'CORRSER? delay'))},"
            f"{_num(_real(interval, 5e-6, 1e-3, 'CORRSER? interval'))},{count}")


def alw(ch: int, patterns: Sequence[AlwgPattern]) -> tuple[str, bytes]:
    """``ALW chnum,length`` + the pattern data block of one SPGU channel (PG PDF 361-362, printed 4-43 to 4-44; data
    format PDF 150, printed 2-62, Table 2-4): header (module type 0, revision 0, number of patterns, 16 zero bytes),
    then per pattern the number of vectors (2 bytes) and the initial level (4 bytes), then 8 bytes per vector: level
    (1 uV counts) and switch state (top bit, 1 = closed) with the incremental time (1 ns counts). 1 to 512 patterns,
    at most ``1024 - patterns`` vectors in total. ALWG mode only (``SIM 1``). Returns ``(header, block)``."""
    count = len(patterns)
    if not 1 <= count <= ALWG_MAX_PATTERNS:
        raise ValueError(f"ALW: 1 to {ALWG_MAX_PATTERNS} patterns, got {count}")
    vectors = sum(len(p.vectors) for p in patterns)
    if vectors > ALWG_MAX_VECTORS - count:
        raise ValueError(f"ALW: {vectors} vectors exceed 1024 - {count} patterns = {ALWG_MAX_VECTORS - count}")
    chunks = [struct.pack(">BBH16x", 0, 0, count)]
    for index, pattern in enumerate(patterns, start=1):
        chunks.append(struct.pack(">Hi", len(pattern.vectors),
                                  _level_counts(pattern.initial_v, f"ALW pattern {index} initial level")))
        for number, vector in enumerate(pattern.vectors, start=1):
            where = f"ALW pattern {index} vector {number}"
            word = (0x8000_0000 if vector.switch_closed else 0) | _time_counts(vector.dt_s, f"{where} time")
            chunks.append(struct.pack(">iI", _level_counts(vector.v, f"{where} level"), word))
    block = b"".join(chunks)
    return f"ALW {_channel(ch)},{len(block)}", block


def als(cycles: Sequence[tuple[int, int]]) -> tuple[str, bytes]:
    """``ALS length`` + the ALWG sequence data block shared by every SPGU channel (PG PDF 360-361, printed 4-42 to
    4-43; data format PDF 151, printed 2-63, Table 2-5): header (module type 0, revision 0, number of pattern cycles,
    16 zero bytes), then per cycle the pattern number (2 bytes, 1-based) and the repeat count (4 bytes, 1 to
    1,048,576). 1 to 512 cycles. ALWG mode only (``SIM 1``). Returns ``(header, block)``."""
    if not 1 <= len(cycles) <= ALWG_MAX_PATTERNS:
        raise ValueError(f"ALS: 1 to {ALWG_MAX_PATTERNS} pattern cycles, got {len(cycles)}")
    chunks = [struct.pack(">BBH16x", 0, 0, len(cycles))]
    for number, repeat in cycles:
        if not 1 <= _int(number, "ALS pattern number") <= ALWG_MAX_PATTERNS:
            raise ValueError(f"ALS: pattern number must be 1 to {ALWG_MAX_PATTERNS}, got {number}")
        if not 1 <= _int(repeat, "ALS repeat count") <= ALWG_MAX_REPEAT:
            raise ValueError(f"ALS: repeat count must be 1 to {ALWG_MAX_REPEAT}, got {repeat}")
        chunks.append(struct.pack(">HI", number, repeat))
    block = b"".join(chunks)
    return f"ALS {len(block)}", block
