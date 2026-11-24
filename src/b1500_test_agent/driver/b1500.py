"""``B1500Driver``: the internal "atom" API over a ``Transport`` (blueprint 2.5; legacy map in
``references/driver-map/flex-driver-map.yaml``).

A facade over one operations mixin per instrument family (``driver/ops/``): ``CoreOps`` (queries, state, data
format, ``CN``, ``XE`` + read, on ``DriverBase``), ``SmuOps`` (integration, ranging, guarded ``DV``/``DI`` and the
staircase sweeps ``WV``/``WI``/``WSV``/``WSI``/``WNX``), ``CmuOps`` (MFCMU signal, MM 17-26 setups, phase
compensation, data correction, cleanup zeroing; WP8.1), ``SpguOps`` (guarded HV-SPGU PG/ALWG setup, start, stop,
polling and load measurement; WP9.1) and ``SwitchOps`` (selector state, ASU, guarded SCUU path); the selector work
package adds its guarded operations to the same mixin. Every command comes from
``driver/flex/`` and is written alone (one command per write, never ``;``-joined). Source operations refuse without
an ``OutputGuard`` and check every channel and value against it before the first byte is written. The driver
orchestrates nothing else: cleanup order (``AB`` -> ``DZ`` -> ``CL`` -> ``ERRX?`` drain -> verify) belongs to
``session/transaction.py``.
``SamplingOps`` (WP7.4) adds time stamps, guarded ``MV``/``MI`` and the ``MM 10`` sampling setup; ``PulsedOps``
(WP7.3) the guarded SMU pulsed setups ``MM 3/4/5/27/28`` (``PT``, ``PV``/``PI``, ``PWV``/``PWI``, ``MCP*``);
``SearchOps`` (WP7.5) the guarded search and quasi-pulsed setups ``MM 14/15/9`` (``LS*``/``LG*``, ``BS*``/``BG*``,
``BDV``/``BDT``/``BDM``).

``StaircaseSetup``, ``SweepSource``, ``RawBlock``, the ADC code tables and the MFCMU setup models are re-exported
here, so callers import the driver API from one module.
"""

from __future__ import annotations

from b1500_test_agent.driver.ops.cmu import (
    PHASE_COMPENSATION_TIMEOUT_S,
    AcLevelSweepSetup,
    CfSweepSetup,
    CmuBlock,
    CmuOps,
    CmuSignal,
    CmuSweepTiming,
    CtSamplingSetup,
    CvSweepSetup,
    PulsedCvSweepSetup,
    PulsedSpotCSetup,
)
from b1500_test_agent.driver.ops.core import CoreOps, RawBlock
from b1500_test_agent.driver.ops.pulsed import PulsedOps, PulsedSetup, PulseSource
from b1500_test_agent.driver.ops.sampling import SamplingOps, SamplingSetup, SamplingSource
from b1500_test_agent.driver.ops.search import (
    QuasiPulseSetup,
    SearchMonitor,
    SearchOps,
    SearchSetup,
    SearchSource,
    SyncSource,
)
from b1500_test_agent.driver.ops.smu import ADC_MODE_CODES, ADC_TYPE_CODES, SmuOps, StaircaseSetup, SweepSource
from b1500_test_agent.driver.ops.spgu import SpguOps
from b1500_test_agent.driver.ops.switch import SwitchOps

__all__ = [
    "ADC_MODE_CODES", "ADC_TYPE_CODES", "PHASE_COMPENSATION_TIMEOUT_S", "AcLevelSweepSetup", "B1500Driver",
    "CfSweepSetup", "CmuBlock", "CmuSignal", "CmuSweepTiming", "CtSamplingSetup", "CvSweepSetup", "PulseSource",
    "PulsedCvSweepSetup", "PulsedSetup", "PulsedSpotCSetup", "QuasiPulseSetup", "RawBlock", "SamplingSetup",
    "SamplingSource", "SearchMonitor", "SearchSetup", "SearchSource", "StaircaseSetup", "SweepSource", "SyncSource",
]


class B1500Driver(CoreOps, SmuOps, SamplingOps, PulsedOps, SearchOps, CmuOps, SpguOps, SwitchOps):
    """FLEX driver of one B1500A. ``guard`` is required for every source operation (blueprint 2.5)."""
