"""``B1500Driver``: the internal "atom" API over a ``Transport`` (blueprint 2.5; legacy map in
``references/driver-map/flex-driver-map.yaml``).

A facade over one operations mixin per instrument family (``driver/ops/``): ``CoreOps`` (queries, state, data
format, ``CN``, ``XE`` + read, on ``DriverBase``) and ``SmuOps`` (integration, ranging, guarded ``DV`` and staircase
``WV``); later work packages add ``CmuOps``, ``SpguOps`` and ``SwitchOps``. Every command comes from
``driver/flex/`` and is written alone (one command per write, never ``;``-joined). Source operations refuse without
an ``OutputGuard`` and check every channel and value against it before the first byte is written. The driver
orchestrates nothing else: cleanup order (``AB`` -> ``DZ`` -> ``CL`` -> ``ERRX?`` drain -> verify) belongs to
``session/transaction.py``.

``StaircaseSetup``, ``RawBlock`` and the ADC code tables are re-exported here, so callers import the driver API from
one module.
"""

from __future__ import annotations

from b1500_test_agent.driver.ops.core import CoreOps, RawBlock
from b1500_test_agent.driver.ops.smu import ADC_MODE_CODES, ADC_TYPE_CODES, SmuOps, StaircaseSetup

__all__ = ["ADC_MODE_CODES", "ADC_TYPE_CODES", "B1500Driver", "RawBlock", "StaircaseSetup"]


class B1500Driver(CoreOps, SmuOps):
    """FLEX driver of one B1500A. ``guard`` is required for every source operation (blueprint 2.5)."""
