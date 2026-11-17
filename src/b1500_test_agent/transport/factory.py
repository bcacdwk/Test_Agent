"""``make_transport``: the one place that turns settings into a transport (blueprint 2.2).

Only ``settings.backend == "visa"`` selects ``VisaTransport``; the default, and anything else, is the simulator,
which needs the scenario (``ConfigBundle.sim_scenario``) and optionally its fault profile
(``ConfigBundle.sim_faults``) and the state directory (``ConfigBundle.paths.state_dir``) for the shared state file.
The result is always wrapped in ``AuditingTransport`` so every I/O is audited.

Typical call (session/service, WP1.6/WP1.8)::

    make_transport(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
                   state_dir=bundle.paths.state_dir)
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from b1500_test_agent.models.sim import SimFault, SimFaultProfile
from b1500_test_agent.models.station import Settings, SimScenario
from b1500_test_agent.transport.audit import AuditingTransport, AuditSink
from b1500_test_agent.transport.base import TransportError


def make_transport(settings: Settings, sink: AuditSink, *, scenario: SimScenario | None = None,
                   faults: SimFaultProfile | Iterable[SimFault] | None = None, state_dir: Path | None = None,
                   timeout_s: float | None = None) -> AuditingTransport:
    """An audited transport for ``settings.backend``; never selects visa implicitly.

    ``sim``: ``scenario`` is required and must be the one ``settings.sim.scenario`` names; ``faults`` are active
    from the start; with ``state_dir`` the persistent state lives in ``<state_dir>/sim/<scenario>.state.json``.
    ``visa``: ``settings.visa`` configures the session; the sim-only arguments must be omitted.
    """
    if settings.backend == "visa":
        if scenario is not None or faults is not None:
            raise TransportError("Backend visa does not take a sim scenario or faults.")
        from b1500_test_agent.transport.visa import VisaTransport  # pyvisa itself loads only in open()

        return AuditingTransport(VisaTransport(settings.visa), sink)
    if settings.backend != "sim":  # pragma: no cover - Backend is a closed Literal
        raise TransportError(f"Unknown backend {settings.backend!r}.")
    if scenario is None:
        raise TransportError("Backend sim needs the scenario (ConfigBundle.sim_scenario).")
    if scenario.name != settings.sim.scenario:
        raise TransportError(f"Scenario {scenario.name!r} is not the configured {settings.sim.scenario!r}.")
    from b1500_test_agent.transport.sim import SimTransport, sim_state_file

    active = list(faults.faults if isinstance(faults, SimFaultProfile) else faults or ())
    state_file = None if state_dir is None else sim_state_file(state_dir, scenario.name)
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return AuditingTransport(SimTransport(scenario, state_file=state_file, faults=active, **kwargs), sink)
