"""Switch operations: 16440A SMU/PGU selector state over the digital I/O port and the ASU of an SMU (blueprint v2
2.5).

``SwitchOps`` is a mixin of ``B1500Driver``. WP6.1 adds the queries the bring-up probe and the cleanup verification
read (``ERMOD?``, ``ERSSP?``); WP7.1 the ASU: the guarded path change ``set_asu_path`` (``SAP``, checked by
``OutputGuard.check_route``: a path change connects or disconnects the SMU output at the DUT), the 1 pA auto-range
switch ``set_asu_1pa_auto`` (``SAR``) and the indicator ``set_asu_indicator`` (``SAL``), which change no output, and
the read-backs ``asu_paths``/``asu_1pa_auto`` (``*LRN? 62``/``63``). The selector ``route`` (``ERMOD 1`` +
``ERSSP``) arrives with WP9.2 and the SCUU (``SSP``) with WP8.1. Queries need no guard.
"""

from __future__ import annotations

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.discovery import parse_asu_1pa, parse_asu_paths, parse_ermod, parse_erssp
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.routing import Route, SwitchState


class SwitchOps(DriverBase):
    """Selector queries (A group of the switch family) and the ASU operations."""

    def selector_control_mode(self) -> int:
        """``ERMOD?`` -> the sum of the enabled digital I/O control modes (PG PDF 420-421); bit value
        ``flex.ERMOD_SELECTOR`` (1) = 16440A selector control. 0 after power-on and ``*RST`` (ATV-18)."""
        return parse_ermod(self._query(flex.ERMOD_Q))

    def selector_state(self, port: int) -> SwitchState:
        """``ERSSP? port`` -> the state of one selector output (``open``, ``smu``, ``pgu``, ``pgu_open``; PG PDF
        434); ports 0/1 = first selector output 1/2, 2/3 = second selector output 1/2."""
        return parse_erssp(self._query(flex.erssp_q(port)))

    # -- ASU -------------------------------------------------------------------------------------------------------

    def asu_paths(self) -> dict[int, SwitchState]:
        """``*LRN? 62`` -> ``{smu channel: "smu" | "cmu"}`` for every SMU with an ASU (PG PDF 451); empty when the
        mainframe reports none."""
        return parse_asu_paths(self._query(flex.lrn_q(flex.LRN_ASU_PATH)))

    def asu_1pa_auto(self) -> dict[int, bool]:
        """``*LRN? 63`` -> ``{smu channel: 1 pA auto ranging enabled}`` for every SMU with an ASU (PG PDF 451)."""
        return parse_asu_1pa(self._query(flex.lrn_q(flex.LRN_ASU_1PA)))

    def set_asu_path(self, route: Route, ch: int) -> None:
        """Guarded ``SAP ch,path`` (PG PDF 505-506): ``route`` is the ASU output in state ``smu`` (path 0) or ``cmu``
        (path 1, the AUX input), ``ch`` the SMU channel the ASU belongs to (``SwitchPort.index``). The guard admits
        a route of the plan or the switch's ``rest`` state (``OutputGuard.check_route``).

        Raises:
            ValueError: If the route's state is not an ASU path.
        """
        path = flex.ASU_PATH_CODES.get(route.state)
        if path is None:
            raise ValueError(f"route {route}: an ASU has no state {route.state!r} (paths: smu, cmu)")
        self._require_guard("set_asu_path", ch).check_route(route)
        self._write(flex.sap(ch, path))

    def set_asu_1pa_auto(self, ch: int, enabled: bool) -> None:
        """``SAR ch,0|1``: enable or disable the 1 pA range for auto ranging (PG PDF 506). Ranging only: no guard."""
        self._write(flex.sar(ch, flex.SAR_ENABLE_1PA if enabled else flex.SAR_DISABLE_1PA))

    def set_asu_indicator(self, ch: int, on: bool) -> None:
        """``SAL ch,0|1``: ASU connection status indicator off/on (PG PDF 505). No output change: no guard."""
        self._write(flex.sal(ch, 1 if on else 0))
