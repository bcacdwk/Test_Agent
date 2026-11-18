"""Child-process entry of the visa-loop two-process tests (blueprint v2 7.1 "Per-transaction VISA; CLI + MCP
coexist").

``python -m tests.visa_loop.serve mcp`` serves the ten MCP tools on stdio, exactly as ``b1500-mcp`` does, and
``python -m tests.visa_loop.serve cli ARGS...`` runs the ``b1500`` CLI with ``ARGS``; both on backend visa from
``$B1500_HOME/config/local/`` with the data in ``$B1500_DATA_DIR``. The only difference from the console scripts is
the injected bus factory: ``make_bus`` with the visa-loop resource manager of the bus that the environment names
(``loop.ENV_DIR``/``ENV_SCENARIO``/``ENV_CHUNK``), so the real ``VisaTransport`` runs in both processes against one
simulated instrument. Run from the repository root (``tests`` is imported from the working directory).
"""

from __future__ import annotations

import logging
import sys

from b1500_test_agent.adapters import cli as cli_package
from b1500_test_agent.adapters.cli import core as cli_core
from b1500_test_agent.adapters.mcp_server import create_server
from b1500_test_agent.service import B1500Service
from tests.visa_loop.helpers import bus_factory
from tests.visa_loop.loop import LoopBus

USAGE = "usage: python -m tests.visa_loop.serve mcp | cli ARGS..."


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("mcp", "cli"):
        raise SystemExit(USAGE)
    factory = bus_factory(LoopBus.from_env())
    if argv[0] == "mcp":
        logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
        service = B1500Service(adapter="mcp", bus_factory=factory)
        try:
            create_server(service).run(transport="stdio", show_banner=False)
        finally:
            service.close()
        return 0
    cli_core.make_service = lambda: B1500Service(adapter="cli", bus_factory=factory)
    cli_package.app(prog_name="b1500", args=argv[1:])  # exits through SystemExit with the CLI's code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
