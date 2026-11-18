"""Switch FLEX builders and constants: the 16440A SMU/PGU selector over the digital I/O port (blueprint v2 2.5).

WP6.1 adds the read-only queries the bring-up probe needs (``ERMOD?``, ``ERSSP?``); the setting commands
(``ERMOD``, ``ERSSP``) and the SCUU/ASU paths (``SSP``, ``SAP``, ``SAR``, ``SSL``, ``SAL``) arrive with the switch
work package (WP9.2). Builders check only the syntax domain of the manual.

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages, chapter 4 printed 4-N =
PDF N + 318).
"""

from __future__ import annotations

from typing import Final

from b1500_test_agent.driver.flex.core import _int
from b1500_test_agent.models.routing import SELECTOR_PORTS, SwitchState

ERMOD_Q = "ERMOD?"
"""Control mode of the digital I/O port (PG PDF 420-421, printed 4-102 to 4-103): the sum of the enabled mode values,
0 = general purpose (initial setting), 1 = 16440A SMU/PGU selector, 2 = N1258A/N1259A, 4 = N1265A, 8 = N1266A,
16 = N1268A, 32 = N1272A. A query: it changes no setting."""

ERMOD_SELECTOR = 1
"""The ``ERMOD?`` mode value (bit) of the 16440A selector control mode; ``ERSSP`` needs it (PG PDF 433)."""

ERMOD_MAX = 63
"""Largest ``ERMOD?`` answer: every control mode of PDF 421 enabled (1 + 2 + 4 + 8 + 16 + 32)."""

ERSSP_STATES: Final[dict[int, SwitchState]] = {0: "open", 1: "smu", 2: "pgu", 3: "pgu_open"}
"""``ERSSP``/``ERSSP?`` connection status (PG PDF 433-434, printed 4-115 to 4-116): 0 all open (initial setting),
1 SMU on, 2 PGU on, 3 PGU open (the semiconductor relay on the PGU path open)."""


def erssp_q(port: int) -> str:
    """``ERSSP? port``: the connection status of one 16440A selector output (PG PDF 434, printed 4-116); port 0/1 =
    output 1/2 of the first selector, 2/3 = output 1/2 of the second (PDF 433). Answers 0-3 (``ERSSP_STATES``).
    A query: it changes no setting. TODO(verify) at bring-up L7 (ATV-18) whether it answers before ``ERMOD 1``."""
    if _int(port, "ERSSP? port") not in SELECTOR_PORTS:
        raise ValueError(f"ERSSP? port must be 0 to 3, got {port}")
    return f"ERSSP? {port}"
