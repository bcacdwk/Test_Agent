"""Switch unit of the simulator: the digital I/O control mode, the 16440A selector outputs, the ASU and the SCUU
(blueprint v2 4.1, 4.2 "Switches").

``SwitchUnit`` is a mixin of ``SimInstrument``. WP6.1 simulates the two selector queries the bring-up probe reads, on
the persistent state (``state.selector_mode``, ``state.selector_ports``): ``ERMOD?`` (PG PDF 420-421, printed 4-102 to
4-103: the sum of the enabled control modes, 0 at power-on) and ``ERSSP? port`` (PG PDF 434, printed 4-116: 0 all
open, 1 SMU, 2 PGU, 3 PGU open; port 0-3, anything else error 120). Power-on, ``*RST`` and a device clear set the
mode to 0 and every port to 0 (ATV-18 assumption, TODO(verify) at L7). ``ERSSP?`` answers whatever the control
mode is (the manual names no execution condition for the query). The selector setting commands (``ERMOD``,
``ERSSP``) and the routing they cause arrive with WP9.2 and the RSU with M10; until then the selector state keeps
its power-on values unless a test seeds it.

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

SCUU (WP8.1; present on the MFCMU slots of ``scenario.scuu``): ``SSP chnum,path`` (PG PDF 519-521, Table 4-30;
``chnum`` the MFCMU, error 671 for any other channel or without an SCUU) connects output 1 (CMUH/Force1) and output 2
(CMUL/Force2) as path 1 SMU/open, 2 open/SMU, 3 SMU/SMU, 4 MFCMU/MFCMU (``state.scuu_paths``; missing = open, the
power-on and ``*RST`` state). Side effects per output (PG p520 (4-202), p37 (1-17); ATV-27): a connection made switches
the unit's output ON (the ``CN`` condition if it was off); SMU -> MFCMU sets that SMU to 0 V, 100 V range, 20 mA
compliance; MFCMU -> SMU sets it to 0 V, 20 V range, 100 uA, output ON. ``SSL chnum,mode`` keeps the LED setting
(``state.scuu_indicators``). ``*LRN? 80``/``81`` answer ``SSL``/``SSP`` items per SCUU (path 0 = open; TODO(verify)
at L6). Which DUT terminals each output reaches is ``CmuEngine._route_sides``.
"""

from __future__ import annotations

from collections.abc import Iterable

from b1500_test_agent.models.station import channel_slot
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.state import ChannelState
from b1500_test_agent.transport.sim.units.base import CMU_TYPES, DEFAULT_ICOMP, handles, learns
from b1500_test_agent.transport.sim.units.cmu_engine import SSP_SIDES

SELECTOR_PORTS = range(4)
"""``ERSSP`` ports: 0/1 = first selector output 1/2, 2/3 = second selector output 1/2 (PG PDF 433)."""

SCUU_TO_CMU = {"voltage": 0.0, "vrange": 14, "icomp": 0.02}
"""An SMU whose SCUU output switches to the MFCMU: 0 V, 100 V range (code 14), 20 mA compliance (PG PDF 520)."""

SCUU_TO_SMU = {"voltage": 0.0, "vrange": 12, "icomp": 1e-4}
"""An SMU whose SCUU output switches back from the MFCMU: 0 V, 20 V range (code 12), 100 uA compliance (PG PDF 520)."""


class SwitchUnit:
    """Selector, ASU and SCUU FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    def _reset_switch_state(self) -> None:
        """Digital I/O control mode general purpose (0), every selector output open, every ASU at its initial settings
        and every SCUU open with its indicator enabled (power-on, ``*RST``; PG Table 2-13, PDF 180)."""
        self.state.selector_mode = 0
        self.state.selector_ports.clear()
        self.state.asu_paths.clear()
        self.state.asu_1pa_auto.clear()
        self.state.asu_indicator.clear()
        self.state.scuu_paths.clear()
        self.state.scuu_indicators.clear()

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

    @learns(62, 63)
    def _lrn_asu(self, kind: int) -> str:
        """``*LRN? 62`` (``SAP`` paths) or ``*LRN? 63`` (``SAR`` modes) of every SMU with an ASU (PG PDF 451)."""
        asus = sorted(ch for ch in self.installed_channels() if self._is_smu(ch) and self._has_asu(ch))
        if kind == 62:
            return ";".join(f"SAP{ch},{self.state.asu_paths.get(ch, 0)}" for ch in asus)
        return ";".join(f"SAR{ch},{0 if self.state.asu_1pa_auto.get(ch, False) else 1}" for ch in asus)

    # -- SCUU -----------------------------------------------------------------------------------------------------

    def _scuu_cmu(self, arg: str) -> int:
        """The MFCMU channel of an ``SSP``/``SSL`` command; error 671 unless it is an MFCMU with an SCUU."""
        number = flex.integer(arg)
        channel = number // 100 if number > 10 and number % 100 == 1 else number
        if not (3 <= channel <= 10 and self._module_type(channel) in CMU_TYPES and self._scuu_on(channel)):
            raise flex.FlexError(flex.ERR_SSP_CHANNEL, f"channel {number}")
        self.state.channels.setdefault(channel, ChannelState())
        return channel

    def _scuu_connect(self, cmu: int, path: int) -> None:
        """Make SCUU path ``path`` on MFCMU ``cmu`` with its side effects (module docstring)."""
        old = SSP_SIDES.get(self.state.scuu_paths.get(cmu, 0), ("open", "open"))
        new = SSP_SIDES[path]
        for k, (before, after) in enumerate(zip(old, new, strict=True)):
            smu = cmu - (k + 1)
            state = self.state.channels.setdefault(smu, ChannelState())
            if self.faults.stuck(smu):
                continue
            if after == "smu" and before == "cmu":
                self.state.channels[smu] = ChannelState(output_on=True, **SCUU_TO_SMU)
            elif after == "smu" and not state.output_on:
                self.state.channels[smu] = ChannelState(output_on=True, voltage=0.0, icomp=DEFAULT_ICOMP)
            elif after == "cmu" and before == "smu":
                for name, value in SCUU_TO_CMU.items():
                    setattr(state, name, value)
        if "cmu" in new and not self.state.channels[cmu].output_on:
            self.state.channels[cmu] = ChannelState(output_on=True)
        self.state.scuu_paths[cmu] = path

    @handles("SSP")
    def _cmd_ssp(self, cmd: flex.Command) -> None:
        """``SSP chnum,path``: the SCUU connection path 1-4 (PG PDF 519-521)."""
        flex.arity(cmd, 2, 2)
        cmu = self._scuu_cmu(cmd.args[0])
        path = flex.integer(cmd.args[1])
        if path not in SSP_SIDES:
            raise flex.FlexError(flex.ERR_PARAMETER, f"SSP path {path}")
        self._scuu_connect(cmu, path)

    @handles("SSL")
    def _cmd_ssl(self, cmd: flex.Command) -> None:
        """``SSL chnum,mode``: SCUU indicator 0 off / 1 on (PG PDF 519)."""
        flex.arity(cmd, 2, 2)
        cmu = self._scuu_cmu(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"SSL mode {mode}")
        self.state.scuu_indicators[cmu] = mode == 1

    @learns(80, 81)
    def _lrn_scuu(self, kind: int) -> str:
        """``*LRN? 80`` ``SSL chnum,mode`` and ``81`` ``SSP chnum,path`` per SCUU (PG PDF 452; path 0 = open)."""
        cmus = [c for c in self._cmu_slots() if self._scuu_on(c)]
        if kind == 80:
            return ";".join(f"SSL{c},{1 if self.state.scuu_indicators.get(c, True) else 0}" for c in cmus)
        return ";".join(f"SSP{c},{self.state.scuu_paths.get(c, 0)}" for c in cmus)
