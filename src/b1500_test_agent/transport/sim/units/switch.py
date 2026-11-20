"""Switch unit of the simulator: the digital I/O control mode, the 16440A selector outputs and the ASU (blueprint v2
4.1).

``SwitchUnit`` is a mixin of ``SimInstrument``. WP6.1 simulates the two queries the bring-up probe reads, on the
persistent state (``state.selector_mode``, ``state.selector_ports``): ``ERMOD?`` (PG PDF 420-421, printed 4-102 to
4-103: the sum of the enabled control modes, 0 at power-on) and ``ERSSP? port`` (PG PDF 434, printed 4-116: 0 all
open, 1 SMU, 2 PGU, 3 PGU open; port 0-3, anything else error 120). Power-on, ``*RST`` and a device clear set the
mode to 0 and every port to 0 (ATV-18 assumption, TODO(verify) at L7). ``ERSSP?`` answers whatever the control
mode is (the manual names no execution condition for the query). The selector setting commands (``ERMOD``,
``ERSSP``) and the routing they cause arrive with WP9.2, the SCUU with WP8.1 and the RSU with M10.

ASU (WP7.1; PG p505-506 (4-187 to 4-188), *LRN? p451 (4-133), initial settings PDF 180): an SMU whose scenario slot
declares ``asu: true`` accepts ``SAP chnum,path`` (0 SMU side, 1 AUX input), ``SAR chnum,mode`` (0 enables the 1 pA
range for auto ranging, 1 disables it) and ``SAL chnum,mode`` (indicator 0 off, 1 on) and answers ``*LRN? 62``
(``SAP<ch>,<path>`` items) and ``*LRN? 63`` (``SAR<ch>,<mode>`` items), one item per ASU, ``;``-separated (an empty
answer without ASUs). On an SMU without an ASU these commands are error 151 (TODO(verify) the code at bring-up L2).
``SAP`` path 1 disconnects the SMU from the DUT (its terminal floats, it carries no current; the output keeps its
setting); ``CN`` and ``CL`` of the SMU return the path to the SMU side (PG p505). ``SAP`` is ignored while an output
is in the high-voltage state (the manual: not effective when the high-voltage indicator is lit; unreachable under
the 42 V ceiling). Power-on, ``*RST`` and a device clear restore the initial settings (SMU side, 1 pA auto ranging
disabled, indicator on). The state is persistent (``state.asu_*``).
"""

from __future__ import annotations

from collections.abc import Iterable

from b1500_test_agent.models.station import channel_slot
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.units.base import handles

SELECTOR_PORTS = range(4)
"""``ERSSP`` ports: 0/1 = first selector output 1/2, 2/3 = second selector output 1/2 (PG PDF 433)."""


class SwitchUnit:
    """Selector FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    def _reset_switch_state(self) -> None:
        """Digital I/O control mode general purpose (0), every selector output open and every ASU at its initial
        settings (power-on, ``*RST``)."""
        self.state.selector_mode = 0
        self.state.selector_ports.clear()
        self.state.asu_paths.clear()
        self.state.asu_1pa_auto.clear()
        self.state.asu_indicator.clear()

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

    # -- ASU -----------------------------------------------------------------------------------------------------------

    def _has_asu(self, channel: int) -> bool:
        """True when the scenario slot of SMU ``channel`` declares an ASU (``SimSlot.asu``)."""
        slot = self._slots().get(channel_slot(channel))
        return bool(slot is not None and slot.asu)

    def _asu_on_aux(self, channel: int) -> bool:
        """True when the ASU of ``channel`` connects its output to the AUX input (``SAP`` path 1)."""
        return self.state.asu_paths.get(channel, 0) == 1

    def _asu_to_smu_side(self, channels: Iterable[int]) -> None:
        """``CN``/``CL`` of these channels: their ASU outputs return to the SMU side (PG p505 (4-187))."""
        for channel in channels:
            self.state.asu_paths.pop(channel, None)

    def _asu_channel(self, arg: str) -> int:
        channel = self._smu(arg)
        if not self._has_asu(channel):
            raise flex.FlexError(flex.ERR_NOT_ALLOWED, f"no ASU on channel {channel}")
        return channel

    @handles("SAP")
    def _cmd_sap(self, cmd: flex.Command) -> None:
        """``SAP chnum,path``: ASU path 0 SMU side, 1 AUX input (PG PDF 505-506)."""
        flex.arity(cmd, 2, 2)
        channel = self._asu_channel(cmd.args[0])
        path = flex.integer(cmd.args[1])
        if path not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"SAP path {path}")
        if self._high_voltage(self._on_levels()):
            return  # not effective while the high-voltage indicator is lit (PG PDF 505)
        if path == 0:
            self.state.asu_paths.pop(channel, None)
        else:
            self.state.asu_paths[channel] = path

    @handles("SAR")
    def _cmd_sar(self, cmd: flex.Command) -> None:
        """``SAR chnum,mode``: 0 enables, 1 disables the 1 pA range for auto ranging (PG PDF 506)."""
        flex.arity(cmd, 2, 2)
        channel = self._asu_channel(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"SAR mode {mode}")
        self.state.asu_1pa_auto[channel] = mode == 0

    @handles("SAL")
    def _cmd_sal(self, cmd: flex.Command) -> None:
        """``SAL chnum,mode``: ASU indicator 0 off, 1 on (PG PDF 505)."""
        flex.arity(cmd, 2, 2)
        channel = self._asu_channel(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"SAL mode {mode}")
        self.state.asu_indicator[channel] = mode == 1

    def _lrn_asu(self, kind: int) -> str:
        """``*LRN? 62`` (``SAP`` paths) or ``*LRN? 63`` (``SAR`` modes) of every SMU with an ASU (PG PDF 451)."""
        asus = sorted(ch for ch in self.installed_channels() if self._is_smu(ch) and self._has_asu(ch))
        if kind == 62:
            return ";".join(f"SAP{ch},{self.state.asu_paths.get(ch, 0)}" for ch in asus)
        return ";".join(f"SAR{ch},{0 if self.state.asu_1pa_auto.get(ch, False) else 1}" for ch in asus)
