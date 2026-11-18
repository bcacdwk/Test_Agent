"""HV-SPGU FLEX builders and constants (blueprint v2 2.5).

WP6.1 adds the read-only output-state query the bring-up probe needs (``SPST?``); the pulse setup and output
commands (``SIM``, ``SPM``, ``SPT``, ``SPV``, ``SPPER``, ``SPRM``, ``SER``, ``SPUPD``, ``SRP``, ``SPP`` ...) arrive
with the SPGU work package (WP9.1).

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages, chapter 4 printed 4-N =
PDF N + 318).
"""

from __future__ import annotations

SPST_Q = "SPST?"
"""Waveform output state of the SPGU (PG PDF 513-514, printed 4-195 to 4-196): 0 = pulse output or ALWG sequence
output inactive, 1 = active. One answer for the mainframe, no channel parameter; the output stays active while a
channel performs a pulse or ALWG output (PG PDF 142, printed 2-54). A query: it changes no setting."""

SPST_STATES = frozenset({0, 1})
"""The ``SPST?`` answers (PDF 513-514)."""
