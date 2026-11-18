"""Anything outside the v1 FLEX subset queues error 100 for ``ERRX?`` and is logged ``unsupported`` (blueprint 3)."""

from __future__ import annotations

import pytest

from b1500_test_agent.transport.sim import flex
from tests.sim.helpers import errx_all, run


@pytest.mark.parametrize(
    "command",
    ["DI 1,0,1E-6,1", "WI 1,1,0,0,1E-6,5,1", "ERR?", "EMG? 100", "TSR", "PV 1,0,0,1", "SSP 1,4", "WSV 2,0,0,1",
     "ACV 7,0.03", "*LRN? 33", "INTLKVTH 0", "IN", "RZ 1", "FOO", "*SRE 32"],
)  # fmt: skip
def test_unsupported_command_queues_error_100_and_is_logged(make_sim, command: str) -> None:
    sim = make_sim()
    sim.write(command)
    [record] = [r for r in sim.instrument.command_log if r.line == command]
    assert record.outcome == "unsupported" and record.error == 100
    assert sim.query("ERRX?") == '100,"Undefined GPIB command."'
    assert sim.query("ERRX?") == '0,"No Error."'


def test_unsupported_command_stops_the_rest_of_its_line(make_sim) -> None:
    sim = make_sim()
    sim.write("CN 1;FOO;CN 3")
    log = [r for r in sim.instrument.command_log if r.line == "CN 1;FOO;CN 3"]
    assert [(r.mnemonic, r.outcome) for r in log] == [("CN", "ok"), ("FOO", "unsupported"), ("CN", "rejected")]
    assert errx_all(sim) == [100]
    outputs = sim.instrument.outputs()
    assert outputs[1].output_on and not outputs[3].output_on


def test_supported_commands_are_exactly_the_v1_subset() -> None:
    """Blueprint 3 table: identity/status, buffer/format, channel, ADC/range, mode/source rows; v2 2.6 adds the
    auto-calibration switch ``CM`` and its read-back ``*LRN?`` (types 0 and 31); v2 7.1 (WP6.1) the family state
    queries of the read-only probe."""
    assert flex.SUPPORTED == {
        "*IDN?", "UNT?", "ERRX?", "*STB?", "*OPC?", "*RST", "LOP?", "*TST?", "*CAL?",
        "FMT", "BC", "NUB?", "TSC",
        "CN", "CL", "DZ", "AB",
        "AAD", "AIT", "AV", "RI", "RV",
        "MM", "CMM", "DV", "WV", "WT", "WM", "XE",
        "CM", "*LRN?",
        "ERMOD?", "ERSSP?", "SPST?", "CORRST?", "ADJ?",
    }  # fmt: skip


def test_lowercase_and_compact_syntax_are_accepted(make_sim) -> None:
    sim = make_sim()
    run(sim, "cn1,3", "DV1,0,0.5,1E-3", " dz ")
    assert sim.instrument.outputs()[1].output_on and sim.instrument.outputs()[1].voltage == 0.0


def test_input_buffer_overflow_is_error_150(make_sim) -> None:
    sim = make_sim()
    sim.write("CN " + ",".join(["1"] * 130))
    assert errx_all(sim) == [150]
    assert not sim.instrument.outputs()[1].output_on
