"""Switch operations: 16440A SMU/PGU selector state over the digital I/O port, the ASU of an SMU and the SCUU paths
(blueprint v2 2.5).

``SwitchOps`` is a mixin of ``B1500Driver``. WP6.1 adds the queries the bring-up probe and the cleanup verification
read (``ERMOD?``, ``ERSSP?``); WP7.1 the ASU: the guarded path change ``set_asu_path`` (``SAP``, checked by
``OutputGuard.check_route``: a path change connects or disconnects the SMU output at the DUT), the 1 pA auto-range
switch ``set_asu_1pa_auto`` (``SAR``) and the indicator ``set_asu_indicator`` (``SAL``), which change no output, and
the read-backs ``asu_paths``/``asu_1pa_auto`` (``*LRN? 62``/``63``); WP8.1 the SCUU as a switch kind: the guarded
``scuu_route`` (``SSP``, every route checked by ``OutputGuard.check_route``), the path read back through ``*LRN? 81``
(the manual has no ``SSP?``) and the indicator ``SSL``. The selector ``route`` (``ERMOD 1`` + ``ERSSP``) arrives with
WP9.2. Queries need no guard.

SCUU facts (PG p520 (4-202), p37 (1-17)): one ``SSP chnum,path`` sets both outputs at once (``flex.SSP_PATHS``:
1 Force1 only, 2 Force2 only, 3 both SMUs, 4 CMUH/CMUL), ``chnum`` being the MFCMU; output 1 (CMUH/Force1) is fed by
the SMU in slot ``cmu_slot - 1``, output 2 (CMUL/Force2) by ``cmu_slot - 2`` (``models.station.scuu_side``). Making
a connection switches that unit's output on; switching an output from SMU to MFCMU sets the SMU to 0 V, 100 V range,
20 mA compliance, series resistor off; back to SMU: 0 V, 20 V range, 100 uA (ATV-27, the manual's text). Every
``SSP`` is therefore an output change and goes through the guard. Use ``SSP`` instead of ``CN`` for the SCUU's modules
(error 323, PG p583 (5-11)).
"""

from __future__ import annotations

from collections.abc import Sequence

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.cmu_data import parse_scuu_path
from b1500_test_agent.driver.discovery import parse_asu_1pa, parse_asu_paths, parse_ermod, parse_erssp
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.routing import Route, SwitchSpec, SwitchState
from b1500_test_agent.models.station import scuu_side


def scuu_geometry(switch: SwitchSpec) -> tuple[int, dict[str, int]]:
    """``(MFCMU channel, {output name: 0 for output 1 / CMUH, 1 for output 2 / CMUL})`` of a declared SCUU.

    Raises:
        DriverError: If the switch is not an SCUU, its MFCMU input is unknown or differs between outputs, or an
            output's SMU is not in slot ``cmu_slot - 1`` or ``cmu_slot - 2``.
    """
    if switch.kind != "scuu":
        raise DriverError(f"{switch.id} is a {switch.kind}, not an SCUU")
    cmus = {port.inputs.get("cmu") for port in switch.ports.values()}
    if None in cmus or len(cmus) != 1:
        raise DriverError(f"{switch.id}: the MFCMU input of every output must be recorded and the same "
                          f"(got {sorted(str(c) for c in cmus)}); record the wiring at bring-up L6")
    cmu = int(next(iter(cmus)))  # type: ignore[arg-type]
    sides: dict[str, int] = {}
    for output, port in switch.ports.items():
        side = scuu_side(cmu, port.index)
        if side is None:
            raise DriverError(f"{switch.id}.{output}: channel {port.index} does not feed an SCUU output of MFCMU {cmu}")
        sides[output] = 0 if side == "H" else 1
    return cmu, sides


def scuu_path(states: tuple[SwitchState, SwitchState]) -> int:
    """The ``SSP`` path for (output 1 state, output 2 state); ``ValueError`` when no path gives that pair (e.g. both
    open, or one output to the MFCMU and the other to an SMU)."""
    for path, pair in flex.SSP_PATHS.items():
        if pair == states:
            return path
    raise ValueError(f"no SSP path connects output 1 to {states[0]!r} and output 2 to {states[1]!r} "
                     f"(paths: {flex.SSP_PATHS})")


class SwitchOps(DriverBase):
    """Selector queries, the ASU operations and the guarded SCUU path of ``B1500Driver``."""

    def selector_control_mode(self) -> int:
        """``ERMOD?`` -> the sum of the enabled digital I/O control modes (PG PDF 420-421); bit value
        ``flex.ERMOD_SELECTOR`` (1) = 16440A selector control. 0 after power-on and ``*RST`` (ATV-18)."""
        return parse_ermod(self._query(flex.ERMOD_Q))

    def selector_state(self, port: int) -> SwitchState:
        """``ERSSP? port`` -> the state of one selector output (``open``, ``smu``, ``pgu``, ``pgu_open``; PG
        PDF 434); ports 0/1 = first selector output 1/2, 2/3 = second selector output 1/2."""
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

    # -- SCUU -------------------------------------------------------------------------------------------------------

    def scuu_route(self, switch: SwitchSpec, routes: Sequence[Route]) -> int:
        """Guarded ``SSP cmu,path`` (PG PDF 519-521): ``routes`` give the state of the SCUU's declared outputs (an
        output not named is opened). Every route, the implied opens included, passes ``OutputGuard.check_route`` (a
        route of the plan or the switch's rest state) before the command is written. Returns the path sent.

        Raises:
            ValueError: If a route names another switch or an undeclared output, an output twice, or a state pair no
                ``SSP`` path gives.
            DriverError: If the SCUU's wiring is incomplete (``scuu_geometry``).
            EnvelopeViolation: If the guard refuses a route (nothing is sent).
        """
        cmu, sides = scuu_geometry(switch)
        states: list[SwitchState] = ["open", "open"]
        seen: set[str] = set()
        for route in routes:
            if route.switch != switch.id or route.output not in sides or route.output in seen:
                raise ValueError(f"route {route} is not one distinct declared output of {switch.id}")
            seen.add(route.output)
            states[sides[route.output]] = route.state
        path = scuu_path((states[0], states[1]))
        implicit = [Route(switch=switch.id, output=output, state="open") for output in sides if output not in seen]
        guard = self._require_guard("scuu_route", cmu)
        for route in [*routes, *implicit]:
            guard.check_route(route)
        self._write(flex.ssp(cmu, path))
        return path

    def scuu_path(self, cmu: int) -> int | None:
        """``*LRN? 81`` -> the SSP path (1-4) of the SCUU on MFCMU ``cmu``, ``None`` when its outputs are open (the
        power-on state) or no SCUU answers (PG PDF 452). A query."""
        return parse_scuu_path(self._query(flex.lrn_q(flex.LRN_SCUU_PATH)), cmu)

    def set_scuu_indicator(self, cmu: int, on: bool) -> None:
        """``SSL cmu,1|0``: the SCUU connection status LED on (initial) or off (PG PDF 519). No output change."""
        self._write(flex.ssl(cmu, on))
