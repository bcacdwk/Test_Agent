"""Declared measurement kinds without an implementation (blueprint 2.6): ``UnimplementedKind``.

They make recipes discoverable through ``list_recipes`` with effective status ``not_implemented`` on every backend,
so the executor refuses them with zero I/O. ``compile`` returns an empty envelope (nothing can ever be sourced);
``acquire`` raises. A kind leaves this list only with a reviewed implementation and its safety tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from b1500_test_agent.catalog.schema import CompiledKindPlan, RawAcquisition
from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, ErrorCode
from b1500_test_agent.models.plan import ChannelBinding, CompiledEnvelope, Estimate, PlanRecord
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.session.transaction import Transaction

UNIMPLEMENTED_KINDS: dict[str, str] = {
    "smu_spot": "SMU spot measurement (MM 1); not needed by the v1 cards",
    "smu_pulsed": "SMU pulsed spot/sweep (MM 3/4); needs the pulse timing extraction",
    "smu_stress_measure": "stress-measure-stress sequences (BTI, HCI); needs async runs and recovery timing",
    "smu_qscv": "quasi-static C-V with SMUs; needs leakage compensation flows",
    "wgfmu_pulsed_iv": "WGFMU fast pulsed I-V; needs the WGFMU instrument library extraction",
    "wgfmu_fast_bti": "WGFMU fast BTI (on-the-fly); needs the WGFMU library and async runs",
    "wgfmu_pulse_sequence": "WGFMU pulse write + read sequences (FeFET endurance/retention, FeCap PUND)",
    "spgu_program_read": "SPGU/HVSPGU program pulse + SMU read through the 16440A selector",
    "cmu_correction": "MFCMU phase compensation and open/short/load correction",
    "cmu_cv": "MFCMU C-V sweep; needs correction, SCUU and leakage validation",
    "hspice_compare": "compare a measured curve with an HSPICE simulation; no instrument action",
}
"""Declared kind ids and what each is waiting for."""


class KindNotImplemented(B1500Error):
    """``acquire`` of an unimplemented kind (never reached: the executor refuses ``not_implemented`` first)."""

    code: ClassVar[ErrorCode] = "not_implemented"


class UnimplementedKind:
    """A declared kind with no backend (``implemented_on`` is empty)."""

    implemented_on: frozenset[Backend] = frozenset()

    def __init__(self, kind_id: str, note: str = "") -> None:
        self.kind_id = kind_id
        self.note = note

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        """An empty envelope and estimate: a plan of this kind can never source anything."""
        return CompiledKindPlan(envelope=CompiledEnvelope(channels={}), estimate=Estimate(points=0, duration_s=0.0))

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        raise KindNotImplemented(f"measurement kind {self.kind_id} is not implemented ({self.note})")

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> None:
        return None


def unimplemented_kinds() -> dict[str, UnimplementedKind]:
    """One ``UnimplementedKind`` per declared kind id."""
    return {kind_id: UnimplementedKind(kind_id, note) for kind_id, note in UNIMPLEMENTED_KINDS.items()}
