"""In-process FLEX simulator behind the Transport protocol (blueprint 3).

``SimTransport`` adapts ``SimInstrument`` (the FLEX state machine) to ``Transport``; ``sim_state_file`` names the
persistent state file ``<state_dir>/sim/<scenario>.state.json``. Fault schemas: ``models/sim.py``.
"""

from b1500_test_agent.transport.sim.instrument import (
    SimInstrument,
    SimSafetyError,
    SimTransport,
    SimulatedInterrupt,
)
from b1500_test_agent.transport.sim.state import sim_state_file

__all__ = ["SimInstrument", "SimSafetyError", "SimTransport", "SimulatedInterrupt", "sim_state_file"]
