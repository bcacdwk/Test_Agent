"""Switch unit of the simulator: the digital I/O control mode and the 16440A selector outputs (blueprint v2 4.1).

``SwitchUnit`` is a mixin of ``SimInstrument``. WP6.1 simulates the two queries the bring-up probe reads, on the
persistent state (``state.selector_mode``, ``state.selector_ports``): ``ERMOD?`` (PG PDF 420-421, printed 4-102 to
4-103: the sum of the enabled control modes, 0 at power-on) and ``ERSSP? port`` (PG PDF 434, printed 4-116: 0 all
open, 1 SMU, 2 PGU, 3 PGU open; port 0-3, anything else error 120). Power-on, ``*RST`` and a device clear set the
mode to 0 and every port to 0 (ATV-18 assumption, TODO(verify) at L7). ``ERSSP?`` answers whatever the control
mode is (the manual names no execution condition for the query). The setting commands (``ERMOD``, ``ERSSP``), the
routing they cause in the circuit and the SCUU/ASU/RSU paths arrive with the switch work package (WP9.2); until
then the state keeps its power-on values unless a test seeds it.
"""

from __future__ import annotations

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.units.base import handles

SELECTOR_PORTS = range(4)
"""``ERSSP`` ports: 0/1 = first selector output 1/2, 2/3 = second selector output 1/2 (PG PDF 433)."""


class SwitchUnit:
    """Selector FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    def _reset_switch_state(self) -> None:
        """Digital I/O control mode general purpose (0) and every selector output open (power-on, ``*RST``)."""
        self.state.selector_mode = 0
        self.state.selector_ports.clear()

    @handles("ERMOD?")
    def _cmd_ermod_q(self, cmd: flex.Command) -> str:
        """``ERMOD?``: the sum of the enabled digital I/O control modes (PG PDF 421)."""
        flex.arity(cmd, 0, 0)
        return str(self.state.selector_mode)

    @handles("ERSSP?")
    def _cmd_erssp_q(self, cmd: flex.Command) -> str:
        """``ERSSP? port``: the connection status of one selector output, 0-3 (PG PDF 434)."""
        flex.arity(cmd, 1, 1)
        port = flex.integer(cmd.args[0])
        if port not in SELECTOR_PORTS:
            raise flex.FlexError(flex.ERR_PARAMETER, f"ERSSP? port {port}")
        return str(self.state.selector_ports.get(port, 0))
