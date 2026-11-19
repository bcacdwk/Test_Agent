"""``B1500Driver``: the internal "atom" API over a ``Transport`` (blueprint 2.5; legacy map in
``references/driver-map/flex-driver-map.yaml``).

A facade over one operations mixin per instrument family (``driver/ops/``): ``CoreOps`` (queries, state, data
format, ``CN``, ``XE`` + read, on ``DriverBase``), ``SmuOps`` (integration, ranging, guarded ``DV`` and staircase
``WV``), ``CmuOps`` (correction state), ``SpguOps`` (output state) and ``SwitchOps`` (selector state); the CMU, SPGU
and switch work packages add their guarded operations to the same mixins. Every command comes from
``driver/flex/`` and is written alone (one command per write, never ``;``-joined). Source operations refuse without
an ``OutputGuard`` and check every channel and value against it before the first byte is written. The driver
orchestrates nothing else: cleanup order (``AB`` -> ``DZ`` -> ``CL`` -> ``ERRX?`` drain -> verify) belongs to
``session/transaction.py``.
``SamplingOps`` (WP7.4) adds time stamps, guarded ``MV``/``MI`` and the ``MM 10`` sampling setup.

``StaircaseSetup``, ``RawBlock`` and the ADC code tables are re-exported here, so callers import the driver API from
one module.
"""

from __future__ import annotations

from b1500_test_agent.driver.ops.cmu import CmuOps
from b1500_test_agent.driver.ops.core import CoreOps, RawBlock
from b1500_test_agent.driver.ops.sampling import SamplingOps, SamplingSetup, SamplingSource
from b1500_test_agent.driver.ops.smu import ADC_MODE_CODES, ADC_TYPE_CODES, SmuOps, StaircaseSetup
from b1500_test_agent.driver.ops.spgu import SpguOps
from b1500_test_agent.driver.ops.switch import SwitchOps

__all__ = ["ADC_MODE_CODES", "ADC_TYPE_CODES", "B1500Driver", "RawBlock", "SamplingSetup", "SamplingSource",
           "StaircaseSetup"]


class B1500Driver(CoreOps, SmuOps, SamplingOps, CmuOps, SpguOps, SwitchOps):
    """FLEX driver of one B1500A. ``guard`` is required for every source operation (blueprint 2.5)."""
