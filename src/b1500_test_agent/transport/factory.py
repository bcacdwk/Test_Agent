"""``make_bus``: the one place that turns settings into the instrument bus (blueprint v2 2.4; replaces v1's
``make_transport``).

Only ``settings.backend == "visa"`` selects ``VisaTransport``; the default, and anything else, is the simulator,
which needs the scenario (``ConfigBundle.sim_scenario``) and optionally its fault profile
(``ConfigBundle.sim_faults``) and the state directory (``ConfigBundle.paths.state_dir``) for the shared state file.
The FLEX link is always wrapped in ``AuditingTransport`` so every I/O and every bus lifecycle call is audited.
``Bus.wgfmu`` is the WGFMU instrument library wrapped in ``AuditingWgfmu`` (``wgfmu_call`` events in the same sink):
on the simulator ``SimWgfmu`` on the same simulated instrument (WP10.1; ``None`` while a ``wgfmu_dll_missing`` fault
is active from the start); on visa ``None`` until the DLL binding (WP10.2). Nothing is opened here: the session
opens and closes the bus per transaction and per status snapshot.

Typical call (``catalog/executor.py``)::

    make_bus(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
             state_dir=bundle.paths.state_dir)
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from b1500_test_agent.models.sim import SimFault, SimFaultProfile
from b1500_test_agent.models.station import Settings, SimScenario
from b1500_test_agent.transport.audit import AuditingTransport, AuditSink
from b1500_test_agent.transport.base import Bus, TransportError
from b1500_test_agent.transport.visa import RmFactory
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu


def make_bus(settings: Settings, sink: AuditSink, *, scenario: SimScenario | None = None,
             faults: SimFaultProfile | Iterable[SimFault] | None = None, state_dir: Path | None = None,
             timeout_s: float | None = None, rm_factory: RmFactory | None = None) -> Bus:
    """The audited bus for ``settings.backend``; never selects visa implicitly.

    ``sim``: ``scenario`` is required and must be the one ``settings.sim.scenario`` names; ``faults`` are active
    from the start; with ``state_dir`` the persistent state lives in ``<state_dir>/sim/<scenario>.state.json``;
    ``timeout_s`` is the simulator's default read timeout. ``Bus.wgfmu`` is the simulated WGFMU library on the same
    instrument; its online calls fail while the FLEX link holds the exclusive lock.
    ``visa``: ``settings.visa`` configures the session; ``rm_factory`` replaces PyVISA's resource manager (visa-loop
    tests only); the sim-only arguments must be omitted.
    """
    if settings.backend == "visa":
        if scenario is not None or faults is not None:
            raise TransportError("Backend visa does not take a sim scenario or faults.")
        from b1500_test_agent.transport.visa import VisaTransport  # pyvisa itself loads only in open()

        return Bus(flex=AuditingTransport(VisaTransport(settings.visa, rm_factory=rm_factory), sink))
    if settings.backend != "sim":  # pragma: no cover - Backend is a closed Literal
        raise TransportError(f"Unknown backend {settings.backend!r}.")
    if rm_factory is not None:
        raise TransportError("Backend sim does not take a VISA resource manager.")
    if scenario is None:
        raise TransportError("Backend sim needs the scenario (ConfigBundle.sim_scenario).")
    if scenario.name != settings.sim.scenario:
        raise TransportError(f"Scenario {scenario.name!r} is not the configured {settings.sim.scenario!r}.")
    from b1500_test_agent.transport.sim import SimTransport, sim_state_file
    from b1500_test_agent.transport.sim.wgfmu import SimWgfmu

    active = list(faults.faults if isinstance(faults, SimFaultProfile) else faults or ())
    state_file = None if state_dir is None else sim_state_file(state_dir, scenario.name)
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    sim = SimTransport(scenario, state_file=state_file, faults=active, **kwargs)
    wgfmu = None
    if not sim.instrument.faults.wgfmu_dll_missing():
        wgfmu = AuditingWgfmu(SimWgfmu(sim.instrument, flex_locked=lambda: sim.locked), sink, backend="sim")
    return Bus(flex=AuditingTransport(sim, sink), wgfmu=wgfmu)
