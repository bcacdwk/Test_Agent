"""Switch routes inside a transaction (blueprint v2 2.6, decision 8; WP9.2): apply and verify one phase of routes,
cleanup step 5 (every declared switch output back to its ``rest`` state) and the switch part of the cleanup
verification (step 8).

Scope (``cleanup_scope``): the station's 16440A selectors, SCUUs and ASUs that are not recorded absent
(``present: false``). RSUs are switched by the WGFMU library and returned by the WGFMU cleanup (step 3); they are not
read here. An SCUU or ASU that does not answer its ``*LRN?`` read-back is not installed, whatever the station
records: nothing can be routed through it, so there is nothing to restore or verify (the detail says so, and a plan
routing through it is blocked by R-ROUTE-01, whose pre-execute check finds its state unreadable). A selector always
answers ``ERSSP?`` once the control mode is on; an unreadable selector output fails the verification.

- **Apply** (``apply_phase``, called by ``Transaction.apply_routes``): the guarded driver applies the phase
  (``B1500Driver.apply_routes``: every route through ``OutputGuard.check_route`` before the first write, ``ERMOD 1``
  first for selectors), the transaction waits the selector settle time (``routing.SELECTOR_SETTLE_S``) after a
  selector change and reads back every switch it touched; an output that does not read the state just set raises
  ``RouteNotVerified`` (the run fails, the cleanup restores and verifies).
- **Restore** (``restore_routes``, step 5, after ``DZ`` and before ``CL``): ``B1500Driver.rest_switch`` per switch
  (selector: ``ERMOD 1`` + ``ERSSP port,rest`` per declared port; SCUU: ``SSP`` to its rest path when an output is
  connected to a non-rest input; ASU: ``SAP ch,0`` when on the AUX side). A failure of one switch does not stop the
  others. ``CL`` follows, so an ``SSP`` that switched SMUs on leaves them off again.
- **Verify** (``verify_routes``, part of step 8; queries only): ``ERMOD?``, then ``ERSSP?`` per declared port (step 5
  switched the control mode on; with it off the outputs are unreadable and the verification fails), ``*LRN? 81``,
  ``*LRN? 62``; every output must read a rest state (``SwitchSpec.at_rest``).

Queries and commands come from the driver; this module holds no FLEX text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.errors import DriverError, RouteNotVerified
from b1500_test_agent.models.routing import SELECTOR_KIND, SELECTOR_SETTLE_S, Route, SwitchSpec, SwitchState

FLEX_SWITCH_KINDS = frozenset({SELECTOR_KIND, "scuu", "asu"})
"""Switch kinds switched by FLEX commands (the RSU is switched by the WGFMU library)."""

UNREADABLE = "unreadable"
NOT_INSTALLED = "not installed"


def cleanup_scope(switches: Sequence[SwitchSpec]) -> list[SwitchSpec]:
    """The declared switches cleanup step 5 restores and step 8 verifies (module docstring)."""
    return [s for s in switches if s.kind in FLEX_SWITCH_KINDS and s.present is not False]


def read_states(driver: B1500Driver, switches: Sequence[SwitchSpec], *, set_control: bool) -> dict[str, SwitchState]:
    """The read-back states of ``switches`` (``B1500Driver.switch_states``); with ``set_control`` the 16440A control
    mode is switched on first when it is off (``ERSSP?`` is defined only with it; a mode setting, no output change)."""
    if not switches:
        return {}
    control_on: bool | None = None
    if set_control and any(s.kind == SELECTOR_KIND for s in switches):
        if not driver.selector_control_mode() & flex.ERMOD_SELECTOR:
            driver.set_selector_control()
        control_on = True
    return driver.switch_states(switches, control_on=control_on)


def apply_phase(driver: B1500Driver, routes: Sequence[Route], switches: Mapping[str, SwitchSpec]) \
        -> dict[str, SwitchState]:
    """Apply ``routes`` (one phase), wait the selector settle time and verify the read-back (module docstring);
    returns the states read.

    Raises:
        ValueError: If a route names an undeclared switch or output, an RSU or one output twice.
        EnvelopeViolation: If the guard refuses a route (nothing of the phase is sent).
        RouteNotVerified: If a touched output does not read the state its route set.
    """
    driver.apply_routes(routes, switches)
    touched = [switches[switch_id] for switch_id in dict.fromkeys(r.switch for r in routes)]
    selectors = any(s.kind == SELECTOR_KIND for s in touched)
    if selectors:
        driver.host_wait(SELECTOR_SETTLE_S)
    states = driver.switch_states(touched, control_on=True if selectors else None)
    wrong = [r for r in routes if states.get(r.target) != r.state]
    if wrong:
        listed = "; ".join(f"{r.target} reads {states.get(r.target) or UNREADABLE}, set {r.state}" for r in wrong)
        raise RouteNotVerified(f"route read-back differs: {listed}",
                               readback={r.target: states.get(r.target) for r in wrong})
    return states


def restore_routes(driver: B1500Driver, switches: Sequence[SwitchSpec]) -> tuple[bool, str]:
    """Cleanup step 5: every switch of ``switches`` back to rest (``B1500Driver.rest_switch``); returns ``(ok,
    detail)``. An ``Exception`` of one switch is recorded and the others still run; an interrupt propagates (the
    cleanup defers it, and the next attempt restores again)."""
    done: list[str] = []
    failed: list[str] = []
    for switch in switches:
        try:
            done.append(driver.rest_switch(switch))
        except Exception as exc:  # noqa: BLE001 - one switch must not stop the others; verification decides
            failed.append(f"{switch.id}: {type(exc).__name__}: {exc}")
    if failed:
        return False, "; ".join([*failed, *done])
    return True, "; ".join(done) or "no switch in scope"


def verify_routes(driver: B1500Driver, switches: Sequence[SwitchSpec]) -> tuple[bool, str, dict[str, str]]:
    """The switch part of cleanup step 8: every declared output of ``switches`` reads a rest state. Returns ``(ok,
    detail, switches_after)``; ``switches_after`` maps each output to what was read (``unreadable``, or ``not
    installed`` for an SCUU/ASU that does not answer). Never raises an ``Exception`` (an unreadable state fails the
    verification)."""
    try:
        states = read_states(driver, switches, set_control=False)  # step 5 sent ERMOD 1; verification only reads
    except DriverError as exc:
        states, error = {}, f"{type(exc).__name__}: {exc}"
    else:
        error = ""
    after: dict[str, str] = {}
    off_rest: list[str] = []
    for switch in switches:
        for output in sorted(switch.ports, key=lambda name: switch.ports[name].index):
            target = f"{switch.id}.{output}"
            state = states.get(target)
            if state is None:
                if not error and switch.kind != SELECTOR_KIND:
                    after[target] = NOT_INSTALLED
                    continue
                after[target] = UNREADABLE
                off_rest.append(f"{target} {UNREADABLE}")
            else:
                after[target] = state
                if not switch.at_rest(output, state):
                    off_rest.append(f"{target} {state} (rest {switch.rest})")
    if off_rest:
        reason = f"; read error {error}" if error else ""
        return False, "switches not at rest: " + ", ".join(off_rest) + reason, after
    return True, "switches at rest: " + ", ".join(f"{t} {s}" for t, s in after.items()), after
