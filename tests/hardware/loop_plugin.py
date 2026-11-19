"""pytest plugin of the hardware suite's read-only proof: the suite against the visa-loop instead of a B1500A.

``test_readonly.py`` starts a child ``python -m pytest tests/hardware -m hardware -p tests.hardware.loop_plugin`` with
``B1500_HW=1``, ``B1500_HOME`` = a temporary repository whose ``config/local/`` selects backend visa, and the
visa-loop bus named by the environment (``tests/visa_loop/loop.py`` ``ENV_DIR``/``ENV_SCENARIO``/``ENV_CHUNK``). The
only change to the suite is the service factory: the real ``make_bus`` with the visa-loop resource manager injected
(as ``tests/visa_loop/serve.py`` does for the CLI), so the gate, the fixtures, ``B1500Admin.probe``, the session,
``ReadOnlyTransport``, ``AuditingTransport`` and ``VisaTransport`` all run unchanged.

Never load this plugin on the lab PC: the suite would then read the simulator, not the instrument. It refuses to load
without the visa-loop environment, and the terminal summary names the simulated bus.
"""

from __future__ import annotations

import os

import pytest

from b1500_test_agent.service import B1500Service
from tests.hardware import support
from tests.visa_loop.helpers import bus_factory
from tests.visa_loop.loop import ENV_DIR, ENV_SCENARIO, LoopBus

_BUS = pytest.StashKey[LoopBus]()


def pytest_configure(config: pytest.Config) -> None:
    missing = [name for name in (ENV_DIR, ENV_SCENARIO) if not os.environ.get(name)]
    if missing:
        raise pytest.UsageError(f"tests.hardware.loop_plugin needs the visa-loop environment ({', '.join(missing)} "
                                "unset); it is only for test_readonly.py, never for the lab PC")
    bus = LoopBus.from_env()
    config.stash[_BUS] = bus
    support.make_service = lambda: B1500Service(adapter="cli", bus_factory=bus_factory(bus))


def pytest_unconfigure(config: pytest.Config) -> None:
    support.make_service = support.default_service


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    bus = terminalreporter.config.stash.get(_BUS, None)
    if bus is not None:
        terminalreporter.write_line(f"VISA-LOOP REHEARSAL: the hardware suite read the simulator ({bus.scenario.name}"
                                    f" at {bus.resource}) through the real VisaTransport, not a B1500A")
