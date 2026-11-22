"""A C-V-shaped stand-in for the capacitance kinds of WP8.3 (test only; WP8.2 AC: "test R-CORR-01 through the rules
with a plan shaped like ``cmu_measure``").

``CvStubKind`` registers under the kind id ``cmu_measure`` in a test registry (``stub_registry``) next to the real
kinds; its recipe ``test.cv_stub`` (written into a temporary recipe folder, never into ``recipes/``) has the MFCMU
roles ``a``/``b`` of the pin map ``capacitor-cmu``, a frequency list in Hz (so R-CORR-01 checks the coverage), the
AC level and a DC bias. ``acquire`` measures a spot ``Cp`` (MM 17, ``IMP 100``) at every listed frequency through
the guarded driver and returns them in ``kind_result`` (``cp_<Hz>``); no table. It exists only to exercise the
correction gate (plan and pre-execute) and the corrected reading of the 100 pF standard end to end.

``spot_cp`` reads the same value outside any plan (a test transaction with its own envelope; no R-CORR-01), for the
uncorrected baseline.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import JsonValue

from b1500_test_agent.catalog.kinds import default_kinds
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError, RawAcquisition
from b1500_test_agent.driver.b1500 import CmuSignal
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, JsonScalar
from b1500_test_agent.models.plan import (
    AcEnvelope,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
)
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.station import StationProfile

if TYPE_CHECKING:
    from b1500_test_agent.driver.b1500 import B1500Driver
    from b1500_test_agent.session.transaction import Transaction

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB_ID = "test.cv_stub"
STUB_RECIPE = """\
id: test.cv_stub
version: 1
title: C-V-shaped stub for the correction tests (MM 17 spot Cp at a frequency list)
family: cmu
kind: cmu_measure
status: sim_validated
card: null
device_types: []
roles:
  a: {function: cmu_high, module_types: [MFCMU]}
  b: {function: cmu_low, module_types: [MFCMU]}
params:
  freqs_hz: {type: float_list, unit: Hz, default: [1.0e+5, 1.0e+6], range: [1.0e+3, 5.0e+6]}
  ac_vrms: {unit: V, default: 0.03, range: [0.01, 0.25]}
  dc_v: {unit: V, default: 0.0, range: [-5.0, 5.0]}
quality: {}
provenance: {sources: [tests/integration/cmu_stub.py], validation_runs: []}
"""
STUB_REQUEST = {"recipe_id": STUB_ID, "pin_map": "capacitor-cmu", "dut_profile": "capacitor-100p"}


def cp_at(driver: B1500Driver, ch: int, freq_hz: float, ac_vrms: float, dc_v: float = 0.0) -> float:
    """One guarded spot ``Cp`` (F) of MFCMU ``ch`` (the channel must be on and the format set)."""
    driver.apply_cmu_signal(ch, CmuSignal(freq_hz=freq_hz, ac_vrms=ac_vrms, dc_v=dc_v))
    driver.spot_c(ch)
    block = driver.measure_cmu(driver.cmu_layout(17), steps=1, timeout_s=10.0)
    return block.readings[0].table_values()["Cp"][0]


class CvStubKind:
    """The ``cmu_measure`` stand-in (see the module docstring)."""

    kind_id = "cmu_measure"
    implemented_on: frozenset[Backend] = frozenset({"sim", "visa"})

    def compile(self, recipe: Recipe, params: dict[str, Quantity], binding: ChannelBinding,
                station: StationProfile) -> CompiledKindPlan:
        freqs = sorted(float(f) for f in params["freqs_hz"].value)  # type: ignore[union-attr]
        ac, dc = float(params["ac_vrms"].value), float(params["dc_v"].value)  # type: ignore[arg-type]
        bound = binding.roles.get("a")
        if bound is None or bound.channel is None:
            return CompiledKindPlan(envelope=CompiledEnvelope(channels={}), estimate=Estimate(points=0, duration_s=0),
                                    program={"channel": None})
        ch = bound.channel
        envelope = CompiledEnvelope(channels={ch: ChannelEnvelope(
            role="a", max_abs_v=abs(dc), max_abs_i=1e-3, function="cmu_high", v_start=dc, v_stop=dc,
            ac=AcEnvelope(max_vrms=ac, max_dc_v=abs(dc), f_min_hz=freqs[0], f_max_hz=freqs[-1]))})
        program: dict[str, JsonValue] = {"channel": ch, "freqs_hz": list(freqs), "ac_vrms": ac, "dc_v": dc}
        return CompiledKindPlan(envelope=envelope, estimate=Estimate(points=len(freqs), duration_s=0.1 * len(freqs)),
                                flex_preview=["MM 17,7"], program=program)

    def acquire(self, tx: Transaction, plan: PlanRecord) -> RawAcquisition:
        program = plan.program
        ch = program.get("channel")
        if not isinstance(ch, int):
            raise CompileError("no channel")
        driver = tx.driver
        driver.set_format(1, 1)
        driver.enable([ch])
        tx.lop_positive_control([ch])
        driver.set_impedance_model(100)
        result: dict[str, JsonScalar] = {}
        for freq in program["freqs_hz"]:  # type: ignore[union-attr]
            result[f"cp_{int(float(freq))}"] = cp_at(driver, ch, float(freq), float(program["ac_vrms"]),  # type: ignore[arg-type]
                                                      float(program["dc_v"]))  # type: ignore[arg-type]
        return RawAcquisition(kind_result=result)

    def to_table(self, raw: RawAcquisition, plan: PlanRecord) -> None:
        return None


def stub_recipes(tmp_path: Path) -> Path:
    """A copy of ``recipes/`` with ``test/cv_stub.yaml`` added."""
    root = tmp_path / "recipes"
    shutil.copytree(REPO_ROOT / "recipes", root)
    (root / "test").mkdir()
    (root / "test" / "cv_stub.yaml").write_text(STUB_RECIPE, encoding="utf-8")
    return root


def stub_registry(recipes: Path) -> RecipeRegistry:
    """The default kinds plus ``CvStubKind`` over ``recipes``."""
    return RecipeRegistry.load(recipes, {**default_kinds(), "cmu_measure": CvStubKind()}, repo_root=REPO_ROOT)
