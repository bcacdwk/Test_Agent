"""Measurement kinds (blueprint 2.6, v2 2.7): ``smu_staircase``, ``smu_stepped``, ``smu_sampling`` and ``smu_spot``
(sim + visa), ``system`` (sim + visa) and the declared ``UnimplementedKind`` ids. ``default_kinds()`` is the mapping
the recipe registry loads against."""

from b1500_test_agent.catalog.kinds.base import MeasurementKind, implemented_on
from b1500_test_agent.catalog.kinds.smu_sampling import SamplingProgram, SmuSamplingKind
from b1500_test_agent.catalog.kinds.smu_spot import SmuSpotKind, SpotProgram
from b1500_test_agent.catalog.kinds.smu_staircase import SmuStaircaseKind, StaircaseProgram
from b1500_test_agent.catalog.kinds.smu_stepped import SmuSteppedKind, SteppedProgram
from b1500_test_agent.catalog.kinds.system import SystemKind
from b1500_test_agent.catalog.kinds.unimplemented import UNIMPLEMENTED_KINDS, UnimplementedKind, unimplemented_kinds


def default_kinds() -> dict[str, MeasurementKind]:
    """Every registered kind by id: the implemented ones plus one ``UnimplementedKind`` per declared id."""
    kinds: dict[str, MeasurementKind] = dict(unimplemented_kinds())
    for kind in (SmuStaircaseKind(), SmuSteppedKind(), SmuSamplingKind(), SystemKind(), SmuSpotKind()):
        kinds[kind.kind_id] = kind
    return kinds


__all__ = [
    "UNIMPLEMENTED_KINDS",
    "MeasurementKind",
    "SamplingProgram",
    "SmuSamplingKind",
    "SmuSpotKind",
    "SmuStaircaseKind",
    "SmuSteppedKind",
    "SpotProgram",
    "StaircaseProgram",
    "SteppedProgram",
    "SystemKind",
    "UnimplementedKind",
    "default_kinds",
    "implemented_on",
]
