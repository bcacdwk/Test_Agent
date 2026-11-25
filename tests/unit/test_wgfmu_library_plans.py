"""Plans that open the WGFMU instrument library without WGFMU roles (WP10.7: ``system.wgfmu_self_test``,
``system.wgfmu_self_cal``): kind ``system`` marks them ``SourcePlan.library``; rule R-WG-01 then needs a loadable
library (visa) and, before execution, a library that lists a WGFMU channel; the executor's pre-execute snapshot
reads the channel ids; ``WgfmuDriver.maintenance`` calls the library's self-test or self-calibration."""

from __future__ import annotations

from functools import partial
from typing import Any

import pytest

from b1500_test_agent.catalog.executor import _uses_wgfmu
from b1500_test_agent.catalog.kinds.system import LIBRARY_OPERATIONS, OPERATIONS, SystemKind
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.driver.wgfmu import WgfmuDriver
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import ChannelBinding
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY, source_plan
from tests.unit.helpers import REPO_ROOT
from tests.unit.rules_factory import context, engine
from tests.unit.rules_factory_v2 import lab_station, live, probe
from tests.unit.test_driver_wgfmu import FakeApi

pytestmark = pytest.mark.wgfmu

REGISTRY = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
LIBRARY = {SOURCE_PLAN_KEY: {"library": True}}


def library_plan(**kw: Any) -> Any:
    return context(program=LIBRARY, station_profile=lab_station(), **kw)


def wg01(build: Any, phase: str = "plan") -> list[tuple[str, Any, Any]]:
    cfg, ctx = build()
    report = engine(cfg).evaluate(ctx, phase)  # type: ignore[arg-type]
    return [(f.severity, f.observed, f.limit) for f in report.findings if f.rule_id == "R-WG-01"]


@pytest.mark.parametrize(("build", "phase", "expect"), [
    (library_plan, "plan", []),
    (partial(library_plan, live=live(wgfmu_channels=[201, 202])), "pre_execute", []),
    (partial(library_plan, live=live(wgfmu_channels=[])), "pre_execute",
     [("block", 0, "at least one channel")]),
    (partial(library_plan, live=live()), "pre_execute", [("block", None, "the bound channels")]),
    (library_plan, "pre_execute", [("block", None, "a live snapshot")]),
    (partial(library_plan, backend="visa", live=live(backend="visa", wgfmu_channels=[201, 202],
                                                     wgfmu_library=probe(machine="x86", loadable=False))),
     "plan", [("block", "x86", "a loadable x64 library")]),
    (partial(library_plan, backend="visa", live=live(backend="visa", wgfmu_channels=[201, 202],
                                                     wgfmu_library=probe())), "pre_execute", []),
    (partial(context, station_profile=lab_station()), "pre_execute", []),  # no library, no WGFMU role: no check
])
def test_r_wg_01_checks_library_plans(build: Any, phase: str, expect: list[tuple[str, Any, Any]]) -> None:
    assert wg01(build, phase) == expect


@pytest.mark.parametrize("operation", sorted(LIBRARY_OPERATIONS))
def test_the_system_kind_marks_library_operations(operation: str) -> None:
    recipe = REGISTRY.get(f"system.{operation}")
    compiled = SystemKind().compile(recipe, {"operation": Quantity(value=operation)},
                                    ChannelBinding(pin_map="any", roles={}), lab_station())
    assert compiled.envelope.channels == {} and compiled.flex_preview == []
    assert source_plan(compiled.program).library is True and compiled.program["operation"] == operation
    assert compiled.estimate.duration_s == OPERATIONS[operation][1]
    flex = SystemKind().compile(REGISTRY.get("system.self_test"), {"operation": Quantity(value="self_test")},
                                ChannelBinding(pin_map="any", roles={}), lab_station())
    assert SOURCE_PLAN_KEY not in flex.program and flex.flex_preview == ["*TST?"]


def test_library_plans_read_the_channel_ids_before_execution() -> None:
    _, ctx = library_plan()
    assert _uses_wgfmu(ctx.plan)
    _, plain = context(station_profile=lab_station())
    assert not _uses_wgfmu(plain.plan)


class Maintenance(FakeApi):
    """``FakeApi`` whose self-test and self-calibration return ``result`` (the slot bitmask)."""

    def __init__(self, result: int) -> None:
        super().__init__()
        self.result = result

    def _answer(self, name: str, args: tuple[Any, ...]) -> Any:
        return self.result if name in ("self_test", "self_calibration") else super()._answer(name, args)


@pytest.mark.parametrize("operation", ["self_test", "self_calibration"])
@pytest.mark.parametrize("result", [0, 2, 1024])
def test_maintenance_calls_the_library_and_reports_its_result(operation: str, result: int) -> None:
    """No guard is needed (no level reaches the DUT); no timeout call (the library raises its own to 600 s)."""
    fake = Maintenance(result)
    driver = WgfmuDriver(fake, None, switches=lab_station().switches)  # type: ignore[arg-type]
    assert driver.maintenance(operation) == result  # type: ignore[arg-type]
    assert [name for name, _ in fake.calls] == [operation]
    with pytest.raises(ValueError, match="self_test or self_calibration"):
        driver.maintenance("initialize")  # type: ignore[arg-type]
