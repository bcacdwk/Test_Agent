"""Simulator golden blocks of the MFCMU (blueprint v2 4.1 "new golden fixtures (CMU data ...) transcribed from
manual tables with pages"; WP8.1): the simulator, set up as the Programming Guide's example programs set up the
instrument (PDF 252-284), returns blocks with the same element layout, status/data-type headers, sweep source
values and sampling indexes as the result tables transcribed in ``tests/fixtures/flex/fmt1_cmu_*.txt``, and the
driver parses both the same way."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from b1500_test_agent.driver.cmu_data import CmuLayout, parse_cmu_blocks
from b1500_test_agent.driver.parser import parse_data
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import load_scenario, noiseless, run
from tests.unit.flex_fixtures import FlexFixture, all_fixtures

pytestmark = pytest.mark.cmu

CMU = 7
FIXTURES = [f for f in all_fixtures("fmt1") if f.name.startswith("fmt1_cmu_")]


def layout_of(fixture: FlexFixture) -> CmuLayout:
    line = next(line for line in fixture.path.read_text(encoding="utf-8").splitlines() if line.startswith("# cmu:"))
    return CmuLayout(**json.loads(line.split(":", 1)[1]))


def setup_commands(layout: CmuLayout, blocks: int) -> list[str]:
    """The example program's setup for ``layout`` with ``blocks`` steps or samples (MFCMU in slot 7)."""
    fmt_mode = 1 if layout.source or layout.index else 0
    common = [f"CN {CMU}", f"FMT 1,{fmt_mode}", f"TSC {int(layout.timestamp)}", f"IMP {layout.imp}",
              f"LMN {int(layout.monitor)}", f"FC {CMU},1000000", f"ACV {CMU},0.03"]
    per_mode = {
        17: [f"DCV {CMU},-5"],
        18: ["WMDCV 2,1", "WTDCV 0,0,0", f"WDCV {CMU},1,-5,5,{blocks}"],
        19: ["PTDCV 0,0.01", f"PDCV {CMU},0,5"],
        20: ["WMDCV 2,1", "PTDCV 0,0.01,0.02", f"PWDCV {CMU},1,0,-5,5,{blocks}"],
        22: ["WMFC 2,1", "WTFC 0,0,0", f"WFC {CMU},1,500000,5000000,{blocks}", f"DCV {CMU},5"],
        23: ["WMACV 2,1", "WTACV 0,0,0", f"WACV {CMU},1,0.01,0.1,{blocks}", f"DCV {CMU},5"],
        26: [f"MTDCV 0.1,0.05,{blocks},0", f"MDCV {CMU},0,5,0"],
    }[layout.mode]
    return [*common, *per_mode, f"MM {layout.mode},{CMU}", "XE"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_simulator_reproduces_the_manual_block_layout(make_sim: Callable[..., SimTransport],
                                                      fixture: FlexFixture) -> None:
    layout = layout_of(fixture)
    blocks = len(fixture.points) // layout.width
    sim = make_sim(noiseless(load_scenario("capacitor_100p")))
    run(sim, *setup_commands(layout, blocks))
    text = sim.read(timeout_s=60)
    produced = parse_data(text, 1)
    assert len(produced) == len(fixture.points)
    for got, want in zip(produced, fixture.points, strict=True):
        assert (got.status.value, got.data_type) == (want.status, want.data_type)  # same header (channel: slot)
        assert got.channel == "G"
    sources = [p for p in produced if p.is_source]
    assert [p.value for p in sources] == pytest.approx([float(p.data) for p in fixture.points if p.status in "WE"])
    if layout.has_index:
        assert [p.value for p in produced if p.data_type == "X"] == [
            float(p.data) for p in fixture.points if p.data_type == "X"]
        times = [p.value for p in produced if p.data_type == "T"]
        manual = [float(p.data) for p in fixture.points if p.data_type == "T"]
        assert times == pytest.approx(manual, abs=5e-3)  # h_bias + (index - 1) x interval; the manual adds ~2 ms
    readings = parse_cmu_blocks(produced, layout)
    assert len(readings) == blocks and all(r.status == "N" for r in readings)
    for reading in readings:  # 100 pF + 0.3 pF uncorrected (+ the 50 nH lead resonance near 5 MHz)
        assert reading.table_values()["Cp"][0] == pytest.approx(100.3e-12, rel=0.01)
