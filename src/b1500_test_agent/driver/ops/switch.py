"""Switch operations: 16440A SMU/PGU selector state over the digital I/O port (blueprint v2 2.5).

``SwitchOps`` is a mixin of ``B1500Driver``. WP6.1 adds the queries the bring-up probe and the cleanup verification
read (``ERMOD?``, ``ERSSP?``); the guarded ``route(Route)`` (``ERMOD 1`` + ``ERSSP``, ``SSP``, ``SAP``; checked by
``OutputGuard.check_route``) arrives with the switch work package (WP9.2). Queries need no guard.
"""

from __future__ import annotations

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.discovery import parse_ermod, parse_erssp
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.routing import SwitchState


class SwitchOps(DriverBase):
    """Selector queries (A group of the switch family)."""

    def selector_control_mode(self) -> int:
        """``ERMOD?`` -> the sum of the enabled digital I/O control modes (PG PDF 420-421); bit value
        ``flex.ERMOD_SELECTOR`` (1) = 16440A selector control. 0 after power-on and ``*RST`` (ATV-18)."""
        return parse_ermod(self._query(flex.ERMOD_Q))

    def selector_state(self, port: int) -> SwitchState:
        """``ERSSP? port`` -> the state of one selector output (``open``, ``smu``, ``pgu``, ``pgu_open``; PG PDF
        434); ports 0/1 = first selector output 1/2, 2/3 = second selector output 1/2."""
        return parse_erssp(self._query(flex.erssp_q(port)))
