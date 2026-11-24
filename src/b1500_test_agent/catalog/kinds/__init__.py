"""Measurement kinds (blueprint 2.6, v2 2.7): ``smu_staircase``, ``smu_stepped``, ``smu_sampling``, ``smu_spot``,
``smu_pulsed`` and ``smu_search`` (sim + visa; WP7.5), ``cmu_correction`` (sim + visa; WP8.2), ``cmu_measure`` (sim +
visa; WP8.3), the composite ``stress_measure`` (sim + visa; built from ``catalog/blocks.py``, so it is imported after
the kinds those blocks use), ``system`` (sim + visa), ``spgu_pulse`` (sim + visa; its ``route_only`` mode since WP9.2,
the ``pg``/``alwg`` pulse modes since WP9.3), the composite ``pulse_read`` (sim + visa, WP9.4; HV-SPGU and SMU pulse
sources, built from ``catalog/blocks.py`` and ``catalog/kinds/pulse_sources.py``), ``wgfmu_waveform`` (sim + visa;
WP10.4) and the declared ``UnimplementedKind`` ids. ``default_kinds()`` is the mapping the recipe registry loads
against."""

from b1500_test_agent.catalog.kinds.base import MeasurementKind, implemented_on
from b1500_test_agent.catalog.kinds.cmu_correction import CmuCorrectionKind
from b1500_test_agent.catalog.kinds.cmu_measure import CmuMeasureKind, CmuProgram
from b1500_test_agent.catalog.kinds.smu_pulsed import PulsedProgram, SmuPulsedKind
from b1500_test_agent.catalog.kinds.smu_sampling import SamplingProgram, SmuSamplingKind
from b1500_test_agent.catalog.kinds.smu_search import SearchProgram, SmuSearchKind
from b1500_test_agent.catalog.kinds.smu_spot import SmuSpotKind, SpotProgram
from b1500_test_agent.catalog.kinds.smu_staircase import SmuStaircaseKind, StaircaseProgram
from b1500_test_agent.catalog.kinds.smu_stepped import SmuSteppedKind, SteppedProgram
from b1500_test_agent.catalog.kinds.spgu_pulse import SpguPulseKind
from b1500_test_agent.catalog.kinds.system import SystemKind
from b1500_test_agent.catalog.kinds.unimplemented import UNIMPLEMENTED_KINDS, UnimplementedKind, unimplemented_kinds
from b1500_test_agent.catalog.kinds.wgfmu_waveform import WgfmuWaveformKind

from b1500_test_agent.catalog.kinds.stress_measure import StressMeasureKind, StressProgram  # isort: skip  # after smu_*
from b1500_test_agent.catalog.kinds.pulse_read import PulseReadKind, PulseReadProgram  # isort: skip  # after the above


def default_kinds() -> dict[str, MeasurementKind]:
    """Every registered kind by id: the implemented ones plus one ``UnimplementedKind`` per declared id."""
    kinds: dict[str, MeasurementKind] = dict(unimplemented_kinds())
    for kind in (SmuStaircaseKind(), SmuSteppedKind(), SmuSamplingKind(), SystemKind(), SmuSpotKind(),
                 StressMeasureKind(), CmuCorrectionKind(), SpguPulseKind(), SmuPulsedKind(), SmuSearchKind(),
                 CmuMeasureKind(), PulseReadKind(), WgfmuWaveformKind()):
        kinds[kind.kind_id] = kind
    return kinds


__all__ = [
    "UNIMPLEMENTED_KINDS",
    "CmuCorrectionKind",
    "CmuMeasureKind",
    "CmuProgram",
    "MeasurementKind",
    "PulseReadKind",
    "PulseReadProgram",
    "PulsedProgram",
    "SamplingProgram",
    "SearchProgram",
    "SmuPulsedKind",
    "SmuSamplingKind",
    "SmuSearchKind",
    "SmuSpotKind",
    "SmuStaircaseKind",
    "SmuSteppedKind",
    "SpguPulseKind",
    "SpotProgram",
    "StaircaseProgram",
    "SteppedProgram",
    "StressMeasureKind",
    "StressProgram",
    "SystemKind",
    "UnimplementedKind",
    "WgfmuWaveformKind",
    "default_kinds",
    "implemented_on",
]
