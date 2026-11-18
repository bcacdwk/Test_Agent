"""MFCMU FLEX builders and constants (blueprint v2 2.5).

WP6.1 adds the read-only queries the bring-up probe needs: ``CORRST?`` (data-correction switches) and ``ADJ? ch,0``
(the result of the last phase compensation, without measuring). The measurement and correction commands (``IMP``,
``FC``, ``ACV``, ``DCV``, ``ADJ``, ``CORRL``, ``CORR?``, ``CORRST`` ...) arrive with the CMU work packages (M8).

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages, chapter 4 printed 4-N =
PDF N + 318).
"""

from __future__ import annotations

from typing import Final

from b1500_test_agent.driver.flex.core import _channel, _choice
from b1500_test_agent.models.station import CorrectionFunction

CORRECTION_CODES: Final[dict[CorrectionFunction, int]] = {"open": 1, "short": 2, "load": 3}
"""``CORRST``/``CORRST?`` correction mode: 1 open, 2 short, 3 load (PG PDF 388, printed 4-70)."""

ADJ_READ_LAST = 0
"""``ADJ?`` mode 0: return the result of the last phase compensation without measuring (PG PDF 355-356)."""

ADJ_RESULTS: Final[dict[int, str]] = {
    0: "phase compensation measurement was normally completed",
    1: "phase compensation measurement failed",
    2: "phase compensation measurement was aborted",
    3: "phase compensation measurement has not been performed",
}
"""``ADJ?`` answers (PG PDF 356, printed 4-38)."""


def corrst_q(ch: int, corr: CorrectionFunction) -> str:
    """``CORRST? chnum,corr``: whether the MFCMU open (1), short (2) or load (3) correction function is ON (answer
    1) or OFF (0) (PG PDF 388, printed 4-70). ``*RST`` or a power cycle turns the functions off. A query."""
    if corr not in CORRECTION_CODES:
        raise ValueError(f"CORRST? correction must be one of {sorted(CORRECTION_CODES)}, got {corr!r}")
    return f"CORRST? {_channel(ch)},{CORRECTION_CODES[corr]}"


def adj_q(ch: int, mode: int) -> str:
    """``ADJ? chnum,mode``: MFCMU phase compensation (PG PDF 355-356, printed 4-37 to 4-38); answers 0-3
    (``ADJ_RESULTS``). Mode 1 measures the compensation data (about 30 s, terminals open at the device end, resets
    the MFCMU); mode 0 (``ADJ_READ_LAST``) only returns the last result. The manual defaults an omitted mode to 1, so
    the mode is always written. TODO(verify) at bring-up L0/L6 that mode 0 changes no output (PDF 355 says the
    command resets the MFCMU)."""
    return f"ADJ? {_channel(ch)},{_choice(mode, (0, 1), 'ADJ? mode')}"
