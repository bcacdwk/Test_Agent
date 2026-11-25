"""The MFCMU correction data query ``CORRDT?`` (WP8.6, CMU closure; PG p384 (4-66)): builder, parser, simulator,
driver and the ``cmu_correction`` read-back that turns the data just measured into the plausibility values of the
human's physical state (``open_cp_f``, ``short_rs_ohm`` ... in ``kind_result``)."""

from __future__ import annotations

import math

import pytest

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.cmu_data import CorrectionData, parse_correction_data
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import load_scenario, noiseless
from tests.unit.test_cmu_correction import plan

pytestmark = pytest.mark.cmu

CMU = 7


def sim() -> SimTransport:
    transport = SimTransport(noiseless(load_scenario("capacitor_100p")), state_file=None)
    transport.open()
    return transport


def test_builder_and_parser_follow_the_manual() -> None:
    assert flex.corrdt_q(9, 1) == "CORRDT? 9,1"  # PG p384 (4-66) example
    with pytest.raises(ValueError, match="starts at 1"):
        flex.corrdt_q(9, 0)
    data = parse_correction_data("1000000,1E-9,1.885E-6,0.5,0.314,0,0")
    assert data == CorrectionData(1e6, 1e-9, 1.885e-6, 0.5, 0.314, 0.0, 0.0)
    assert data.open_cp_f == pytest.approx(0.3e-12, rel=1e-3) and data.short_ls_h == pytest.approx(50e-9, rel=1e-3)
    for bad in ("1000000,1,2,3", "0,0,0,0,0,0,0", "1e6,x,0,0,0,0,0", "1e6,nan,0,0,0,0,0"):
        with pytest.raises(FlexParseError):
            parse_correction_data(bad)


def test_the_simulator_answers_the_data_corrdt_set_and_refuses_an_index_outside_the_list() -> None:
    transport = sim()
    transport.write("CLCORR 7,1")
    transport.write("CORRDT 7,100000,0,6.283185E-7,0.5,0.0314159,100,0")
    answer = transport.query("CORRDT? 7,1")
    data = parse_correction_data(answer)
    assert data.freq_hz == 1e5 and data.open_cp_f == pytest.approx(1e-12, rel=1e-5)
    assert (data.short_r, data.short_x, data.load_r, data.load_x) == pytest.approx((0.5, 0.0314159, 100.0, 0.0))
    transport.write("CORRDT? 7,2")  # one frequency listed
    assert transport.query("ERRX?").startswith("120")


def test_the_driver_reads_the_whole_list_and_nothing_when_it_is_empty() -> None:
    envelope = CompiledEnvelope(channels={CMU: ChannelEnvelope(
        role="a", max_abs_v=0.0, max_abs_i=1e-3, function="cmu_high",
        ac=AcEnvelope(max_vrms=0.05, max_dc_v=0.0, f_min_hz=1e3, f_max_hz=5e6))})
    transport = sim()
    driver = B1500Driver(transport, OutputGuard(envelope))
    driver.enable([CMU])
    assert driver.correction_data_list(CMU) == ()  # power-on: no list, no CORRDT? asked
    assert [r.command for r in transport.instrument.command_log if r.command.startswith("CORRDT?")] == []
    driver.set_correction_frequencies(CMU, [1e5, 1e6])
    data = driver.correction_data_list(CMU)
    assert [d.freq_hz for d in data] == [1e5, 1e6]
    assert all(d.open_g == d.open_b == d.short_r == d.short_x == 0.0 for d in data)  # never measured: 0 (sim)
    assert driver.correction_data(CMU, 2) == data[1]


def test_a_data_correction_preview_reads_its_data_back_and_the_phase_compensation_does_not() -> None:
    record = plan("cmu.correction_open")
    freqs = record.program["freqs_hz"]
    assert isinstance(freqs, list) and len(freqs) == 23
    tail = record.flex_preview[-(len(freqs) + 1):]
    assert tail == [flex.corrl_q(CMU), *(flex.corrdt_q(CMU, i) for i in range(1, 24))]
    assert not any(line.startswith("CORRDT?") for line in plan("cmu.phase_compensation").flex_preview)


def test_the_open_stray_capacitance_of_a_listed_frequency_is_b_over_omega() -> None:
    data = CorrectionData(2e6, 0.0, 2 * math.pi * 2e6 * 0.3e-12, 0.0, 2 * math.pi * 2e6 * 50e-9, 100.0,
                          2 * math.pi * 2e6 * 1e-9)
    assert (data.open_cp_f, data.short_ls_h, data.load_ls_h) == pytest.approx((0.3e-12, 50e-9, 1e-9))
