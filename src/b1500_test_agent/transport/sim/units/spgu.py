"""HV-SPGU unit of the simulator (blueprint v2 4.1, 4.2 "SPGU output").

``SpguUnit`` is a mixin of ``SimInstrument``. WP6.1 simulates the output-state query the bring-up probe and the
cleanup verification read: ``SPST?`` (PG PDF 513-514, printed 4-195 to 4-196) answers 1 while a pulse or ALWG
output is active (``state.spgu_output_active``), else 0; power-on, ``*RST`` and a device clear stop the output. The
pulse setup, the ``SPST?`` state machine of a running pulse train (count/duration) and the delivered level at the
DUT arrive with the SPGU work package (WP9.1); until then the output stays inactive unless a test seeds it.
TODO(verify) at bring-up L0/L7 what the real instrument answers to ``SPST?`` without an SPGU installed (the probe
asks only when ``UNT?`` lists one).
"""

from __future__ import annotations

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.units.base import handles


class SpguUnit:
    """SPGU FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    def _reset_spgu_state(self) -> None:
        """Pulse output stopped (power-on, ``*RST``)."""
        self.state.spgu_output_active = False

    @handles("SPST?")
    def _cmd_spst_q(self, cmd: flex.Command) -> str:
        """``SPST?``: 1 while an SPGU pulse or ALWG sequence output is active, else 0 (PG PDF 513-514)."""
        flex.arity(cmd, 0, 0)
        return "1" if self.state.spgu_output_active else "0"
