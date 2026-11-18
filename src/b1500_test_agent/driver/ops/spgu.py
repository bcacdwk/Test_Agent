"""HV-SPGU operations (blueprint v2 2.5).

``SpguOps`` is a mixin of ``B1500Driver``. WP6.1 adds the output-state query (``SPST?``) that the bring-up probe and
the cleanup verification read; the guarded pulse setup and output (``configure_pulse``/``start`` through
``OutputGuard.check_pulse``, ``stop`` = ``SPP``) arrive with the SPGU work package (WP9.1). Queries need no guard.
"""

from __future__ import annotations

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.discovery import parse_spst
from b1500_test_agent.driver.ops.core import DriverBase


class SpguOps(DriverBase):
    """SPGU queries (A group of the SPGU family)."""

    def pulse_output_active(self) -> bool:
        """``SPST?`` -> ``True`` while an SPGU pulse or ALWG sequence output is active (PG PDF 513-514; ATV-19)."""
        return parse_spst(self._query(flex.SPST_Q))
