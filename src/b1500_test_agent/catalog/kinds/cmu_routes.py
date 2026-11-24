"""The MFCMU measurement path of a plan (WP8.3): the two MFCMU roles (``cmu_high``/``cmu_low``) wired directly to the
MFCMU sides (pin-map targets ``7H``/``7L``) or through an SCUU (targets ``SCUU1.OUT1``/``SCUU1.OUT2``; blueprint
v2 2.7 "SCUU route to CMU and back"), shared by the kinds ``cmu_measure`` and ``cmu_correction``.

SCUU facts (PG p520 (4-202) "SSP", Table 4-30; PG p37 (1-17)): the MFCMU and the two SMUs in the slots below it reach
the DUT only through the SCUU outputs; one ``SSP chnum,path`` sets both outputs (path 4 = CMUH/CMUL, path 3 = both
SMUs), switches the connected units' outputs on and is used instead of ``CN`` for the SCUU's modules (``CN`` of them
is error 323, PG p583 (5-11)). A route to the MFCMU therefore names both outputs (``cmu``); the plan returns them to
the switch's ``rest`` state in its own last phase (``rest``), and the transaction cleanup (step 5) restores and
verifies the rest state on every exit (WP9.2). The MFCMU of an SCUU is never in the ``CN`` list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from b1500_test_agent.catalog.schema import CompileError
from b1500_test_agent.driver import flex
from b1500_test_agent.models.plan import ChannelBinding
from b1500_test_agent.models.recipe import CMU_SIDES, Recipe
from b1500_test_agent.models.routing import Route, SwitchState
from b1500_test_agent.models.station import StationProfile, scuu_side

MEASURE_PHASE: Final = "measure"
REST_PHASE: Final = "rest"


@dataclass(frozen=True)
class CmuPath:
    """How the MFCMU reaches the DUT: directly (no routes) or through SCUU ``switch`` (``routes`` to the MFCMU, the
    ``rest`` routes back, the ``SSP`` paths of both and the SMU channels the SCUU feeds, which no role may switch on
    with ``CN``)."""

    switch: str | None = None
    routes: list[Route] = field(default_factory=list)
    rest: list[Route] = field(default_factory=list)
    ssp_measure: int | None = None
    ssp_rest: int | None = None
    scuu_modules: frozenset[int] = frozenset()

    @property
    def via_scuu(self) -> bool:
        return self.switch is not None

    @property
    def routes_by_phase(self) -> dict[str, list[Route]]:
        """``{measure: routes, rest: rest}`` (empty without an SCUU)."""
        return {MEASURE_PHASE: list(self.routes), REST_PHASE: list(self.rest)} if self.via_scuu else {}

    def preview(self, cmu: int, phase: str) -> list[str]:
        """The ``SSP`` line of ``phase`` (FLEX preview), nothing without an SCUU."""
        if not self.via_scuu:
            return []
        path = self.ssp_measure if phase == MEASURE_PHASE else self.ssp_rest
        return [flex.ssp(cmu, int(path))] if path is not None else []


def _ssp_path(state: SwitchState) -> int | None:
    """The ``SSP`` path that connects both SCUU outputs to ``state`` (``cmu`` 4, ``smu`` 3)."""
    return next((path for path, pair in flex.SSP_PATHS.items() if pair == (state, state)), None)


def mfcmu_path(recipe: Recipe, binding: ChannelBinding, station: StationProfile, *, kind_id: str) -> CmuPath:
    """The MFCMU path of the bound MFCMU roles (module docstring). Roles bound without a route use the MFCMU sides
    directly; an unbound role or an undeclared switch is left to R-PIN-01.

    Raises:
        CompileError: If only one MFCMU role goes through a switch, the roles use different switches, the switch is
            not an SCUU, both roles use one output, or an output's MFCMU side does not fit its role.
    """
    roles = {name: binding.roles.get(name) for name, spec in recipe.roles.items() if spec.function in CMU_SIDES}
    routed = {name: b.via for name, b in roles.items() if b is not None and b.via is not None}
    if not routed:
        return CmuPath()
    if len(routed) != len(roles):
        raise CompileError(f"{kind_id}: the MFCMU roles {sorted(roles)} reach the DUT either both directly or both "
                           f"through one SCUU; {sorted(routed)} use a switch, the others do not")
    switches = {route.switch for route in routed.values()}
    switch = station.switch(next(iter(switches))) if len(switches) == 1 else None
    if len(switches) != 1:
        raise CompileError(f"{kind_id}: the MFCMU roles use different switches {sorted(switches)}; one SCUU serves "
                           "one MFCMU")
    if switch is None:
        return CmuPath()  # undeclared switch: R-PIN-01 blocks the plan
    if switch.kind != "scuu":
        raise CompileError(f"{kind_id}: the MFCMU reaches the DUT only directly or through an SCUU, not through "
                           f"{switch.id} ({switch.kind})")
    outputs = [route.output for route in routed.values()]
    if len(set(outputs)) != len(outputs):
        raise CompileError(f"{kind_id}: both MFCMU roles use {switch.id}.{outputs[0]}")
    cmus = {port.inputs.get("cmu") for port in switch.ports.values()}
    cmu = next(iter(cmus)) if len(cmus) == 1 else None
    for name, route in routed.items():
        port = switch.ports.get(route.output)
        side = scuu_side(cmu, port.index) if cmu is not None and port is not None else None
        wanted = CMU_SIDES[recipe.roles[name].function]
        if side is not None and side != wanted:
            raise CompileError(f"{kind_id}: role {name} ({recipe.roles[name].function}) needs the MFCMU {wanted} "
                               f"side, but {switch.id}.{route.output} is the SCUU's {side} output")
    routes = sorted({Route(switch=switch.id, output=output, state="cmu") for output in switch.ports},
                    key=Route.sort_key)
    rest = sorted({Route(switch=switch.id, output=output, state=switch.rest) for output in switch.ports},
                  key=Route.sort_key)
    feeds = frozenset(int(port.inputs["smu"]) for port in switch.ports.values()  # type: ignore[arg-type]
                      if port.inputs.get("smu") is not None)
    return CmuPath(switch=switch.id, routes=routes, rest=rest, ssp_measure=_ssp_path("cmu"),
                   ssp_rest=_ssp_path(switch.rest), scuu_modules=feeds | ({int(cmu)} if cmu is not None else set()))
