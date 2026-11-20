"""The WGFMU instrument-library link (blueprint v2 2.4): the ``WgfmuApi`` protocol and ``WgfmuError``
(``api``), the auditing wrapper ``AuditingWgfmu`` (``audit``) and, from WP10.2, the ctypes binding ``WgfmuDll``
(``dll``, the only module that loads ``wgfmu.dll``). The simulator implementation is
``transport.sim.wgfmu.SimWgfmu``. Library symbols (``WGFMU_*`` names) appear only in this package and in the
simulator module (lint ``tests/unit/test_lint_wgfmu_symbols.py``)."""

from b1500_test_agent.transport.wgfmu.api import WgfmuApi, WgfmuError
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu

__all__ = ["AuditingWgfmu", "WgfmuApi", "WgfmuError"]
