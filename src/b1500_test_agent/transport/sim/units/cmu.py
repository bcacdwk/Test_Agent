"""MFCMU unit of the simulator (blueprint v2 4.1, 4.2 "fixture + capacitor").

``CmuUnit`` is a mixin of ``SimInstrument``. WP6.1 simulates the correction-state queries the bring-up probe reads,
on the persistent state:

- ``CORRST? chnum,corr`` (PG PDF 388, printed 4-70): 1 when the open (1), short (2) or load (3) correction function
  of the MFCMU is ON (``state.cmu_corrections[channel][corr]``), else 0; ``*RST`` and power-on turn every function
  off;
- ``ADJ? chnum,0`` (PG PDF 355-356, printed 4-37 to 4-38): the result of the last phase compensation
  (``state.cmu_phase_results[channel]``; 3 = not performed until one ran), kept over ``*RST`` because only a power
  cycle clears the compensation data. Mode 1 (an omitted mode means 1) measures the phase compensation: that, the
  ``ADJ``/``CORRST``/``CORR?`` commands, the measurements and the fixture parasitics (``devices/fixture.py``) arrive
  with the CMU work packages (M8) and answer error 100 (``unsupported``) until then.

The channel must be an installed MFCMU (errors 121/153/151 otherwise, as for every channel argument).
"""

from __future__ import annotations

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.units.base import CMU_TYPES, Unsupported, handles

CORRECTION_MODES = (1, 2, 3)
"""``CORRST`` correction modes: 1 open, 2 short, 3 load (PG PDF 388)."""

PHASE_NOT_PERFORMED = 3
"""``ADJ?`` result when no phase compensation measurement has been performed (PG PDF 356)."""


class CmuUnit:
    """MFCMU FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    def _reset_cmu_state(self) -> None:
        """Every data-correction function OFF (``*RST``, power-on; PG PDF 388); phase compensation data are kept."""
        self.state.cmu_corrections.clear()

    @handles("CORRST?")
    def _cmd_corrst_q(self, cmd: flex.Command) -> str:
        """``CORRST? chnum,corr``: 1 when the correction function is ON, else 0 (PG PDF 388)."""
        flex.arity(cmd, 2, 2)
        channel = self._channel(cmd.args[0], kinds=CMU_TYPES)
        corr = flex.integer(cmd.args[1])
        if corr not in CORRECTION_MODES:
            raise flex.FlexError(flex.ERR_PARAMETER, f"CORRST? correction mode {corr}")
        return "1" if self.state.cmu_corrections.get(channel, {}).get(corr, False) else "0"

    @handles("ADJ?")
    def _cmd_adj_q(self, cmd: flex.Command) -> str:
        """``ADJ? chnum[,mode]``: mode 0 returns the last phase compensation result (PG PDF 355-356)."""
        flex.arity(cmd, 1, 2)
        channel = self._channel(cmd.args[0], kinds=CMU_TYPES)
        mode = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"ADJ? mode {mode}")
        if mode == 1:
            raise Unsupported("ADJ? mode 1 (phase compensation measurement) is not simulated yet (CMU work package)")
        return str(self.state.cmu_phase_results.get(channel, PHASE_NOT_PERFORMED))
