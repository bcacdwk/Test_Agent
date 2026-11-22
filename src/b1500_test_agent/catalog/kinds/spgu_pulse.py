"""``spgu_pulse``: HV-SPGU pulse kind (blueprint v2 2.7): pulse trains and arbitrary linear waveforms on HV-SPGU
channels, the 16440A selector routes around them, and optional SMU readings during a train. WP9.2 built its
``route_only`` mode (the selector check, ``system.selector_check``); WP9.3 the pulse modes ``pg`` (2-/3-level pulses
bounded by a count or a duration) and ``alwg`` (arbitrary linear waveform generator), with SMU spot readings during
the train (charge pumping): ``catalog/kinds/spgu_train.py`` (recipes ``spgu.pulse_train``, ``spgu.alwg_sequence``,
``mosfet.charge_pumping``).

The recipe chooses the mode with its single-choice enum parameter ``mode`` (``SPGU_PULSE_MODES`` lists the modes this
kind compiles; any other value is a ``CompileError``, so a recipe can only name an existing mode).

**route_only** (no roles, no source: the compiled envelope has no channel, so the transaction's ``OutputGuard``
refuses every source, ``CN`` included, and admits only the routes listed here or a switch's rest state). Every
declared 16440A selector output (station ``switches`` of kind ``selector_16440a`` not recorded absent, in station
order, outputs by ``ERSSP`` port) is stepped on its own, the others resting: SMU on, PGU on, PGU open (CH 1 only,
ports 0 and 2, PG p154 (2-66); parameter ``pgu_open``), all open (when ``open`` is not the rest state), then back to
its ``rest`` state. One phase per step (``check-NN`` in ``routes_by_phase``, one route each, so no output is driven
by two inputs in a phase; R-ROUTE-01). Every step goes through ``Transaction.apply_routes``: guarded ``ERMOD 1`` +
``ERSSP port,status``, the relay settle time, the ``ERSSP?`` read-back (a mismatch stops the run:
``RouteNotVerified``), then the output is held ``dwell_s`` (the human at the station listens to the relays and sees
the front-panel LEDs, bring-up stage L7) and a checkpoint is recorded. Before the first route ``LOP?`` must report
every output switch off and, with an HV-SPGU installed, ``SPST?`` no active pulse output: a route-only check never
connects a live source. The transaction's cleanup returns every declared output to rest and verifies it (blueprint
v2 2.6 steps 5 and 8). The pre-execute rule R-ROUTE-01 has already read every declared port at rest. The FLEX
preview lists the writes (``ERMOD 1``, ``ERSSP port,status`` per step), as every kind's preview does.

No measurement data (``to_table`` returns ``None``); ``kind_result`` names the outputs checked, the states verified
and the sequence; the audit holds each phase with its read-back (checkpoint ``routes``). Works without recorded
selector inputs (nothing is sourced), which is how the human records the wiring at L7 (ATV-28).

**pg / alwg**: see ``spgu_train`` (roles, settings, points, routes ``pulse``/``rest``, the guarded burst block
``blocks.spgu_burst``, the table of the readings during the trains).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pandas as pd

from b1500_test_agent.catalog.kinds.spgu_train import (
    PULSE_MODES,
    PULSE_ROUTE,
    acquire_train,
    compile_train,
    stored_program,
    train_table,
)
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend
from b1500_test_agent.models.plan import ChannelBinding, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.routing import SELECTOR_KIND, SELECTOR_SETTLE_S, Route, SwitchSpec, SwitchState
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL, StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

MODE_PARAM: Final = "mode"
PGU_OPEN_PARAM: Final = "pgu_open"
DWELL_PARAM: Final = "dwell_s"

ROUTE_ONLY: Final = "route_only"
SPGU_PULSE_MODES: Final = (ROUTE_ONLY, *PULSE_MODES)
"""Modes this kind compiles: ``route_only`` (WP9.2), ``pg`` and ``alwg`` (WP9.3)."""

CHECK_ORDER: Final[tuple[SwitchState, ...]] = ("smu", "pgu", "pgu_open", "open")
"""The states a selector check steps an output through before it returns to rest."""

STEP_OVERHEAD_S: Final = 0.05
"""Estimated bus time of one check step (``ERMOD 1``, ``ERSSP``, the ``ERSSP?`` read-backs, audit)."""

ROUTE_ONLY_ROUTES: Final = frozenset({f"{SELECTOR_KIND}:{state}" for state in ("smu", "pgu", "pgu_open")})
"""Card ``routes`` a route-only recipe may name (``switch_routes``; the skill lint reads it)."""


def selectors_of(station: StationProfile) -> list[SwitchSpec]:
    """The declared 16440A selectors a check steps (not recorded absent), in station order."""
    return [s for s in station.switches if s.kind == SELECTOR_KIND and s.present is not False]


def check_sequence(switch: SwitchSpec, output: str, *, pgu_open: bool) -> list[SwitchState]:
    """The states one output steps through: ``CHECK_ORDER`` without its rest state and states it cannot take (or
    ``pgu_open`` when not wanted), then its rest state."""
    states = [state for state in CHECK_ORDER if state != switch.rest and switch.allows(output, state)
              and (pgu_open or state != "pgu_open")]
    return [*states, switch.rest]


def _value(params: dict[str, Quantity], name: str) -> object:
    quantity = params.get(name)
    return None if quantity is None else quantity.value


def _has_spgu(station: StationProfile) -> bool:
    """True when the station lists an HV-SPGU (the check then reads ``SPST?`` first)."""
    return any(MODULE_TYPE_BY_MODEL.get(m.model) == "HVSPGU" for m in station.modules)


class SpguPulseKind:
    """HV-SPGU pulse kind: the ``route_only`` selector check and the ``pg``/``alwg`` pulse modes (module docstring)."""

    kind_id = "spgu_pulse"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    # -- compile ----------------------------------------------------------------------------------------------------

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        mode = _value(params, MODE_PARAM)
        if mode not in SPGU_PULSE_MODES:
            raise CompileError(f"{self.kind_id}: {MODE_PARAM} must be one of {list(SPGU_PULSE_MODES)}, got {mode!r}")
        if mode != ROUTE_ONLY:
            return compile_train(self.kind_id, str(mode), recipe, params, binding, station)
        return self._compile_route_only(recipe, params, station)

    def _compile_route_only(self, recipe: Recipe, params: dict[str, Quantity],
                            station: StationProfile) -> CompiledKindPlan:
        if recipe.roles:
            raise CompileError(f"{self.kind_id} {ROUTE_ONLY}: no DUT roles (nothing is sourced); {recipe.id} declares "
                               f"{sorted(recipe.roles)}")
        pgu_open = _value(params, PGU_OPEN_PARAM)
        dwell = _value(params, DWELL_PARAM)
        if not isinstance(pgu_open, bool):
            raise CompileError(f"{PGU_OPEN_PARAM} must be a bool, got {pgu_open!r}")
        if isinstance(dwell, bool) or not isinstance(dwell, int | float) or not 0.0 <= dwell <= 60.0:
            raise CompileError(f"{DWELL_PARAM} must be a number of seconds from 0 to 60, got {dwell!r}")
        selectors = selectors_of(station)
        if not selectors:
            raise CompileError("the station declares no 16440A selector (switches of kind selector_16440a, not "
                               "present: false); a human records them in config/local/station.yaml (bring-up L7)")
        steps: list[dict[str, object]] = []
        preview: list[str] = []  # writes only, as every kind's preview (the LOP?/SPST?/ERSSP? queries are not listed)
        allowed: set[Route] = set()
        phases: dict[str, list[Route]] = {}
        sequence: list[str] = []
        for switch in selectors:
            for output, port in sorted(switch.ports.items(), key=lambda item: item[1].index):
                states = check_sequence(switch, output, pgu_open=pgu_open)
                sequence.append(f"{switch.id}.{output} {','.join(states)}")
                for state in states:
                    route = Route(switch=switch.id, output=output, state=state)
                    phase = f"check-{len(steps) + 1:02d}"
                    phases[phase] = [route]
                    if state != switch.rest:
                        allowed.add(route)
                    steps.append({"phase": phase, "switch": switch.id, "output": output, "port": port.index,
                                  "state": state})
                    preview += [flex.ermod(flex.ERMOD_SELECTOR), flex.erssp(port.index, flex.ERSSP_CODES[state])]
        segment = SELECTOR_SETTLE_S + float(dwell) + STEP_OVERHEAD_S
        program: dict[str, object] = {
            "mode": ROUTE_ONLY, "dwell_s": float(dwell), "pgu_open": pgu_open, "spgu": _has_spgu(station),
            "steps": steps, "sequence": "; ".join(sequence),
        }
        return CompiledKindPlan(
            envelope=CompiledEnvelope(channels={}, routes=frozenset(allowed)),
            estimate=Estimate(points=0, duration_s=len(steps) * segment, max_segment_s=segment),
            flex_preview=preview, program=program, routes_by_phase=phases)  # type: ignore[arg-type]

    def checkpoint_total(self, plan: PlanRecord) -> int:
        """One checkpoint per check step (route-only); one per ``WAIT_SEGMENT_S`` of output time and point (pulse
        modes)."""
        if plan.program.get("mode") in PULSE_MODES:
            return sum(stored_program(plan)[0].chunks)
        steps = plan.program.get("steps")
        return len(steps) if isinstance(steps, list) else 0

    @staticmethod
    def switch_routes(recipe: Recipe) -> frozenset[str]:
        """The ``<switch kind>:<state>`` routes a recipe of this kind can set besides its roles' (card lint): the
        selector check's states (no roles), or the PGU path of a pgu role through a selector."""
        if not recipe.roles:
            return ROUTE_ONLY_ROUTES
        return frozenset({PULSE_ROUTE}) if any(r.function == "pgu" for r in recipe.roles.values()) else frozenset()

    # -- acquire ----------------------------------------------------------------------------------------------------

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        program = plan.program
        if program.get("mode") in PULSE_MODES:
            return acquire_train(tx, plan)
        if program.get("mode") != ROUTE_ONLY:
            raise CompileError(f"plan {plan.plan_id} has no {self.kind_id} mode this kind runs")
        steps = program.get("steps")
        dwell = program.get("dwell_s")
        if not isinstance(steps, list) or not steps or not isinstance(dwell, int | float):
            raise CompileError(f"plan {plan.plan_id} has no {ROUTE_ONLY} steps")
        self._require_outputs_off(tx, spgu=bool(program.get("spgu")))
        verified: list[str] = []
        for index, step in enumerate(steps):
            assert isinstance(step, dict)
            route = Route.model_validate({"switch": step["switch"], "output": step["output"], "state": step["state"]})
            phase = str(step["phase"])
            if plan.routes_by_phase.get(phase) != [route]:
                raise CompileError(f"plan {plan.plan_id}: step {phase} is not the plan's route for that phase")
            states = tx.apply_routes([route], phase=phase)
            verified.append(f"{route.target}={states[route.target]}")
            if dwell:
                tx.driver.host_wait(float(dwell))
            tx.checkpoint(index + 1, len(steps), "route")
        outputs = len({entry.split("=", 1)[0] for entry in verified})
        return RawAcquisition(kind_result={
            "mode": ROUTE_ONLY, "outputs_checked": outputs, "states_verified": len(verified),
            "sequence": str(program.get("sequence", "")),
        }, message=f"{outputs} selector outputs stepped through {len(verified)} states, each read back")

    @staticmethod
    def _require_outputs_off(tx: Transaction, *, spgu: bool) -> None:
        """``LOP?`` all off and, with an SPGU, ``SPST?`` 0, before the first route (module docstring).

        Raises:
            DriverError: If an output switch is on or an SPGU output is active.
        """
        on = {slot: out.state for slot, out in sorted(tx.driver.output_state().items()) if out.output_on}
        if on:
            raise DriverError(f"route-only check refused: output switches on in slots {on}; run safe_shutdown first")
        if spgu and tx.driver.pulse_output_active():
            raise DriverError("route-only check refused: an SPGU pulse output is active; run safe_shutdown first")
        tx.mark("outputs off before the selector check")

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> pd.DataFrame | None:
        """``None`` for the selector check and for pulse trains without SMU roles; else one row per SMU reading
        during a train (``spgu_train``).

        Raises:
            ValueError: If the blocks are not whole points of the programmed readings.
        """
        if plan.program.get("mode") not in PULSE_MODES:
            return None
        program, _ = stored_program(plan)
        if program.spot is None:
            return None
        if not raw.blocks:
            raise ValueError(f"{self.kind_id}: no SMU reading was acquired")
        return pd.DataFrame(train_table(program, raw.blocks))
