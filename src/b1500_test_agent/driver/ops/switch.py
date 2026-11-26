"""Switch operations: 16440A SMU/PGU selector state over the digital I/O port, the ASU of an SMU and the SCUU paths
(blueprint v2 2.5, 2.6).

``SwitchOps`` is a mixin of ``B1500Driver``. WP6.1 adds the queries the bring-up probe and the cleanup verification
read (``ERMOD?``, ``ERSSP?``); WP7.1 the ASU: the guarded path change ``set_asu_path`` (``SAP``, checked by
``OutputGuard.check_route``: a path change connects or disconnects the SMU output at the DUT), the 1 pA auto-range
switch ``set_asu_1pa_auto`` (``SAR``) and the indicator ``set_asu_indicator`` (``SAL``), which change no output, and
the read-backs ``asu_paths``/``asu_1pa_auto`` (``*LRN? 62``/``63``); WP8.1 the SCUU as a switch kind: the guarded
``scuu_route`` (``SSP``, every route checked by ``OutputGuard.check_route``), the path read back through ``*LRN? 81``
(the manual has no ``SSP?``) and the indicator ``SSL``. Queries need no guard.

WP9.2 adds the selector routes and the switch-wide operations the transaction uses:

- ``set_selector_control`` (``ERMOD 1``, the 16440A control mode ``ERSSP`` needs; a mode setting, no output change)
  and the guarded ``route_selector`` (``ERSSP port,status``);
- ``apply_routes(routes, switches)``: one phase of routes over any declared switches (selector, SCUU, ASU): every
  route (an SCUU's implied opens included) passes ``OutputGuard.check_route`` before the first byte is written, then
  ``ERMOD 1`` once, one ``ERSSP`` per selector output, one ``SSP`` per SCUU, one ``SAP`` per ASU output. RSU routes
  belong to the WGFMU library (``WgfmuDriver``) and are refused here;
- ``switch_states(switches)``: the read-back of every declared output (``ERSSP?`` while the control mode is on,
  ``*LRN? 81``, ``*LRN? 62``); outputs that cannot be read (control mode off, unit not answering, RSU) are left out;
- ``rest_switch(switch)``: return one declared switch to its ``rest`` state with a guard that admits nothing but
  rest states (cleanup step 5, any transaction, with or without a plan): a selector always gets ``ERMOD 1`` and
  ``ERSSP port,rest`` on every declared port; an SCUU or ASU is read first and switched only when an output is
  connected to a non-rest input (an SCUU whose outputs are both open, its power-on state, is left as it is: no
  ``SSP`` path opens both, and making the rest path would switch its SMUs on, ``SwitchSpec.at_rest``); one that
  does not answer its read-back is not installed (nothing to restore).

SCUU facts (PG p520 (4-202), p37 (1-17)): one ``SSP chnum,path`` sets both outputs at once (``flex.SSP_PATHS``:
1 Force1 only, 2 Force2 only, 3 both SMUs, 4 CMUH/CMUL), ``chnum`` being the MFCMU; output 1 (CMUH/Force1) is fed by
the SMU in slot ``cmu_slot - 1``, output 2 (CMUL/Force2) by ``cmu_slot - 2`` (``models.station.scuu_side``). Making
a connection switches that unit's output on; switching an output from SMU to MFCMU sets the SMU to 0 V, 100 V range,
20 mA compliance, series resistor off; back to SMU: 0 V, 20 V range, 100 uA (ATV-27, the manual's text). Every
``SSP`` is therefore an output change and goes through the guard. Use ``SSP`` instead of ``CN`` for the SCUU's modules
(error 323, PG p583 (5-11)).

Selector facts (PG p433-434 (4-115, 4-116), p154 (2-66)): ``ERSSP`` needs ``ERMOD 1``; port 0/1 = first selector
output 1/2, 2/3 = second selector output 1/2; PGU open only on CH 1 (ports 0, 2); the SMU input carries Force only.
Power-on and a device clear leave the control mode off and every output open (ATV-18: designed around, every route
and every cleanup sends ``ERMOD 1`` first and verifies with ``ERSSP?``; TODO(verify) at bring-up L7). No tool sends
``*RST`` (only kind ``system`` may, and does not), so its effect is moot (v2.1 plan §4.6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.cmu_data import parse_lrn_channel_items, parse_scuu_path
from b1500_test_agent.driver.discovery import parse_asu_1pa, parse_asu_paths, parse_ermod, parse_erssp
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.plan import CompiledEnvelope
from b1500_test_agent.models.routing import SELECTOR_KIND, Route, SwitchSpec, SwitchState
from b1500_test_agent.models.station import channel_canonical, scuu_side


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


def scuu_plan(switch: SwitchSpec, routes: Sequence[Route]) -> tuple[int, int, list[Route]]:
    """``(MFCMU channel, SSP path, every route the path sets)`` for ``routes`` on SCUU ``switch``: the named outputs
    plus an ``open`` route for each declared output the routes do not name.

    Raises:
        ValueError: If a route names another switch or an undeclared output, an output twice, or a state pair no
            ``SSP`` path gives.
        DriverError: If the SCUU's wiring is incomplete (``scuu_geometry``).
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
    return cmu, path, [*routes, *implicit]


def rest_guard(switches: Sequence[SwitchSpec]) -> OutputGuard:
    """A guard that admits no source and no route but the ``rest`` state of ``switches`` (cleanup step 5, which runs
    in every transaction, also without a plan envelope)."""
    return OutputGuard(CompiledEnvelope(channels={}), switches=switches)


def selector_port(switch: SwitchSpec, output: str) -> int:
    """The ``ERSSP`` port of a declared selector output.

    Raises:
        ValueError: If ``switch`` is not a 16440A selector or has no output ``output``.
    """
    if switch.kind != SELECTOR_KIND or output not in switch.ports:
        raise ValueError(f"{switch.id}.{output} is not a declared 16440A selector output")
    return switch.ports[output].index


def _presence(switch: SwitchSpec) -> str:
    """How the station records ``switch`` (audit detail of a unit that does not answer its read-back)."""
    if switch.present is True:
        return "recorded present: check config/local/station.yaml against the hardware"
    return "presence unknown" if switch.present is None else "recorded absent"


def _scuu_states(path: int | None) -> tuple[SwitchState, SwitchState]:
    """(output 1, output 2) of an ``SSP`` path; ``None`` (both open, the power-on state) -> ("open", "open")."""
    return ("open", "open") if path is None else flex.SSP_PATHS[path]


class SwitchOps(DriverBase):
    """Selector control and routes, the ASU operations and the guarded SCUU path of ``B1500Driver``."""

    def selector_control_mode(self) -> int:
        """``ERMOD?`` -> the sum of the enabled digital I/O control modes (PG PDF 420-421); bit value
        ``flex.ERMOD_SELECTOR`` (1) = 16440A selector control. 0 after power-on and ``*RST`` (ATV-18)."""
        return parse_ermod(self._query(flex.ERMOD_Q))

    def selector_state(self, port: int) -> SwitchState:
        """``ERSSP? port`` -> the state of one selector output (``open``, ``smu``, ``pgu``, ``pgu_open``; PG
        PDF 434); ports 0/1 = first selector output 1/2, 2/3 = second selector output 1/2."""
        return parse_erssp(self._query(flex.erssp_q(port)))

    def set_selector_control(self) -> None:
        """``ERMOD 1``: enable the 16440A selector control mode of the digital I/O port (PG PDF 419-420), which
        ``ERSSP`` needs. Other enabled modes stay on (``ERMOD?`` answers the sum). A mode setting, no output change:
        no guard."""
        self._write(flex.ermod(flex.ERMOD_SELECTOR))

    def route_selector(self, route: Route, switch: SwitchSpec, *, guard: OutputGuard | None = None) -> None:
        """Guarded ``ERSSP port,status`` for one declared selector output (PG PDF 433); the control mode must be on
        (``set_selector_control``). ``guard`` replaces the driver's guard (the cleanup's rest-only guard).

        Raises:
            ValueError: If ``route`` is not an output of ``switch``, a selector, or a selector state.
            EnvelopeViolation: If the guard refuses the route (nothing is sent).
        """
        if route.switch != switch.id:
            raise ValueError(f"route {route} is not a route of {switch.id}")
        port = selector_port(switch, route.output)
        code = flex.ERSSP_CODES.get(route.state)
        if code is None:
            raise ValueError(f"route {route}: a 16440A selector has no state {route.state!r}")
        command = flex.erssp(port, code)  # syntax first (PGU open only on CH 1), then the guard
        (guard or self._require_guard("route_selector", port)).check_route(route)
        self._write(command)

    # -- routes over every switch kind --------------------------------------------------------------------------------

    def apply_routes(self, routes: Sequence[Route], switches: Mapping[str, SwitchSpec]) -> list[str]:
        """Apply one phase of routes (module docstring): every route is checked by the guard before the first write,
        then ``ERMOD 1`` (once, with selector routes), ``ERSSP`` per selector output, one ``SSP`` per SCUU (its other
        declared outputs are opened, so a phase names every output it needs), ``SAP`` per ASU output. Returns the
        targets switched (``SEL1.OUT1`` ...), in order. No settle wait (the caller waits).

        Raises:
            ValueError: If a route names an undeclared switch or output, an RSU (WGFMU library), or one output twice.
            EnvelopeViolation: If the guard refuses any route (nothing is sent).
            DriverError: If an SCUU's wiring is incomplete (``scuu_geometry``).
        """
        seen: set[str] = set()
        for route in routes:
            switch = switches.get(route.switch)
            if switch is None or route.output not in switch.ports:
                raise ValueError(f"route {route}: {route.switch}.{route.output} is not a declared switch output")
            if switch.kind == "rsu":
                raise ValueError(f"route {route}: an RSU is switched through the WGFMU library (connect/disconnect), "
                                 "not by FLEX")
            if route.target in seen:
                raise ValueError(f"route {route}: output {route.target} is named twice in one phase")
            seen.add(route.target)
        guard = self._require_guard("apply_routes", 0)
        checked = [r for r in routes if switches[r.switch].kind != "scuu"]
        for switch_id in dict.fromkeys(r.switch for r in routes if switches[r.switch].kind == "scuu"):
            checked.extend(scuu_plan(switches[switch_id], [r for r in routes if r.switch == switch_id])[2])
        for route in checked:  # the SCUUs' implied opens too: refuse the whole phase before anything is written
            guard.check_route(route)
            if switches[route.switch].kind == SELECTOR_KIND:
                flex.erssp(selector_port(switches[route.switch], route.output), flex.ERSSP_CODES[route.state])
        done: list[str] = []
        selector_routes = [r for r in routes if switches[r.switch].kind == SELECTOR_KIND]
        if selector_routes:
            self.set_selector_control()
            for route in selector_routes:
                self.route_selector(route, switches[route.switch])
                done.append(route.target)
        for switch_id in dict.fromkeys(r.switch for r in routes if switches[r.switch].kind == "scuu"):
            own = [r for r in routes if r.switch == switch_id]
            self.scuu_route(switches[switch_id], own)
            done.extend(r.target for r in own)
        for route in (r for r in routes if switches[r.switch].kind == "asu"):
            self.set_asu_path(route, switches[route.switch].ports[route.output].index)
            done.append(route.target)
        return done

    def switch_states(self, switches: Sequence[SwitchSpec], *, control_on: bool | None = None) \
            -> dict[str, SwitchState]:
        """The state of every declared output that can be read (module docstring), keyed ``"<switch>.<output>"``:
        selectors by ``ERSSP?`` (only while ``ERMOD?`` shows the 16440A control mode: the manual defines no answer
        otherwise), SCUUs from ``*LRN? 81`` (both outputs ``open`` when it reports path 0; nothing when the SCUU does
        not answer or its wiring is incomplete), ASUs from ``*LRN? 62`` (nothing for an SMU without an ASU). RSU
        states come from the WGFMU library and are not read here. Queries only; ``control_on`` = the selector
        control mode when the caller already knows it (``None``: ``ERMOD?`` is read).

        Raises:
            FlexParseError: If an answer does not match the manual's format.
        """
        states: dict[str, SwitchState] = {}
        selectors = [s for s in switches if s.kind == SELECTOR_KIND]
        if control_on is None and selectors:
            control_on = bool(self.selector_control_mode() & flex.ERMOD_SELECTOR)
        if selectors and control_on:
            for switch in selectors:
                for output, port in sorted(switch.ports.items(), key=lambda item: item[1].index):
                    states[f"{switch.id}.{output}"] = self.selector_state(port.index)
        scuus = [s for s in switches if s.kind == "scuu"]
        if scuus:
            items = parse_lrn_channel_items(self._query(flex.lrn_q(flex.LRN_SCUU_PATH)), flex.LRN_SCUU_ITEM)
            for switch in scuus:
                try:
                    cmu, sides = scuu_geometry(switch)
                except DriverError:
                    continue
                if channel_canonical(cmu) not in items:
                    continue
                pair = _scuu_states(self.scuu_path(cmu))
                states.update({f"{switch.id}.{output}": pair[side] for output, side in sides.items()})
        asus = [s for s in switches if s.kind == "asu"]
        if asus:
            paths = self.asu_paths()
            for switch in asus:
                for output, port in switch.ports.items():
                    if port.index in paths:
                        states[f"{switch.id}.{output}"] = paths[port.index]
        return states

    def rest_switch(self, switch: SwitchSpec) -> str:
        """Return ``switch`` to its ``rest`` state (cleanup step 5; module docstring) through a rest-only guard;
        returns what was done (audit detail). RSUs are left to the WGFMU library cleanup (step 3). An SCUU or ASU that
        does not answer its read-back is not installed: nothing to restore (an ASU also returns to its SMU side with
        every ``CL``, PG p505 (4-187)).

        Raises:
            DriverError: If an SCUU's wiring is incomplete (``scuu_geometry``).
            EnvelopeViolation: Never for a valid ``SwitchSpec`` (rest states always pass the rest-only guard).
        """
        guard = rest_guard([switch])
        rests = [Route(switch=switch.id, output=output, state=switch.rest) for output in switch.ports]
        if switch.kind == SELECTOR_KIND:
            self.set_selector_control()
            for route in sorted(rests, key=lambda r: switch.ports[r.output].index):
                self.route_selector(route, switch, guard=guard)
            ports = ", ".join(str(switch.ports[r.output].index) for r in rests)
            return f"{switch.id}: {flex.ermod(flex.ERMOD_SELECTOR)}; ports {ports} -> {switch.rest}"
        if switch.kind == "scuu":
            return self._rest_scuu(switch, rests, guard)
        if switch.kind == "asu":
            return self._rest_asu(switch, rests, guard)
        return f"{switch.id}: RSU, returned by the WGFMU library cleanup"

    def _rest_scuu(self, switch: SwitchSpec, rests: list[Route], guard: OutputGuard) -> str:
        cmu, sides = scuu_geometry(switch)
        items = parse_lrn_channel_items(self._query(flex.lrn_q(flex.LRN_SCUU_PATH)), flex.LRN_SCUU_ITEM)
        if channel_canonical(cmu) not in items:
            return (f"{switch.id}: no SCUU answers on MFCMU {cmu} ({_presence(switch)}); not installed, nothing to "
                    "restore")
        pair = _scuu_states(self.scuu_path(cmu))
        if all(switch.at_rest(output, pair[side]) for output, side in sides.items()):
            return f"{switch.id}: at rest ({', '.join(f'{o} {pair[k]}' for o, k in sorted(sides.items()))})"
        path = self.scuu_route(switch, rests, guard=guard)
        return f"{switch.id}: {flex.ssp(cmu, path)!r} -> {switch.rest}"

    def _rest_asu(self, switch: SwitchSpec, rests: list[Route], guard: OutputGuard) -> str:
        paths = self.asu_paths()
        done: list[str] = []
        for route in rests:
            ch = switch.ports[route.output].index
            if ch not in paths:
                done.append(f"{route.output}: no ASU answers on SMU {ch} ({_presence(switch)}); not installed")
            elif paths[ch] != switch.rest:
                self.set_asu_path(route, ch, guard=guard)
                done.append(f"{route.output}: {flex.sap(ch, flex.ASU_PATH_CODES[switch.rest])!r} -> {switch.rest}")
            else:
                done.append(f"{route.output}: at rest")
        return f"{switch.id}: " + "; ".join(done)

    # -- ASU -------------------------------------------------------------------------------------------------------

    def asu_paths(self) -> dict[int, SwitchState]:
        """``*LRN? 62`` -> ``{smu channel: "smu" | "cmu"}`` for every SMU with an ASU (PG PDF 451); empty when the
        mainframe reports none."""
        return parse_asu_paths(self._query(flex.lrn_q(flex.LRN_ASU_PATH)))

    def asu_1pa_auto(self) -> dict[int, bool]:
        """``*LRN? 63`` -> ``{smu channel: 1 pA auto ranging enabled}`` for every SMU with an ASU (PG PDF 451)."""
        return parse_asu_1pa(self._query(flex.lrn_q(flex.LRN_ASU_1PA)))

    def set_asu_path(self, route: Route, ch: int, *, guard: OutputGuard | None = None) -> None:
        """Guarded ``SAP ch,path`` (PG PDF 505-506): ``route`` is the ASU output in state ``smu`` (path 0) or ``cmu``
        (path 1, the AUX input), ``ch`` the SMU channel the ASU belongs to (``SwitchPort.index``). The guard admits
        a route of the plan or the switch's ``rest`` state (``OutputGuard.check_route``); ``guard`` replaces the
        driver's guard (the cleanup's rest-only guard).

        Raises:
            ValueError: If the route's state is not an ASU path.
        """
        path = flex.ASU_PATH_CODES.get(route.state)
        if path is None:
            raise ValueError(f"route {route}: an ASU has no state {route.state!r} (paths: smu, cmu)")
        (guard or self._require_guard("set_asu_path", ch)).check_route(route)
        self._write(flex.sap(ch, path))

    def set_asu_1pa_auto(self, ch: int, enabled: bool) -> None:
        """``SAR ch,0|1``: enable or disable the 1 pA range for auto ranging (PG PDF 506). Ranging only: no guard."""
        self._write(flex.sar(ch, flex.SAR_ENABLE_1PA if enabled else flex.SAR_DISABLE_1PA))

    def set_asu_indicator(self, ch: int, on: bool) -> None:
        """``SAL ch,0|1``: ASU connection status indicator off/on (PG PDF 505). No output change: no guard."""
        self._write(flex.sal(ch, 1 if on else 0))

    # -- SCUU -------------------------------------------------------------------------------------------------------

    def scuu_route(self, switch: SwitchSpec, routes: Sequence[Route], *, guard: OutputGuard | None = None) -> int:
        """Guarded ``SSP cmu,path`` (PG PDF 519-521): ``routes`` give the state of the SCUU's declared outputs (an
        output not named is opened). Every route, the implied opens included, passes ``OutputGuard.check_route`` (a
        route of the plan or the switch's rest state) before the command is written; ``guard`` replaces the driver's
        guard (the cleanup's rest-only guard). Returns the path sent.

        Raises:
            ValueError: If a route names another switch or an undeclared output, an output twice, or a state pair no
                ``SSP`` path gives.
            DriverError: If the SCUU's wiring is incomplete (``scuu_geometry``).
            EnvelopeViolation: If the guard refuses a route (nothing is sent).
        """
        cmu, path, every = scuu_plan(switch, routes)
        checker = guard or self._require_guard("scuu_route", cmu)
        for route in every:
            checker.check_route(route)
        self._write(flex.ssp(cmu, path))
        return path

    def scuu_path(self, cmu: int) -> int | None:
        """``*LRN? 81`` -> the SSP path (1-4) of the SCUU on MFCMU ``cmu``, ``None`` when its outputs are open (the
        power-on state) or no SCUU answers (PG PDF 452). A query."""
        return parse_scuu_path(self._query(flex.lrn_q(flex.LRN_SCUU_PATH)), cmu)

    def set_scuu_indicator(self, cmu: int, on: bool) -> None:
        """``SSL cmu,1|0``: the SCUU connection status LED on (initial) or off (PG PDF 519). No output change."""
        self._write(flex.ssl(cmu, on))
