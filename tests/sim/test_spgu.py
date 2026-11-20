"""Simulated HV-SPGU (``transport/sim/units/spgu.py``, WP9.1; blueprint v2 4.2 "SPGU output": open-load doubling
exact, delivered V +-1 %, count/duration exact; ``SPST?`` state machine, ATV-19; free run after ``*RST``; faults
``spgu_no_stop`` and ``spgu_load_mismatch`` of 4.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from b1500_test_agent.models.sim import SpguLoadMismatch, SpguNoStop
from b1500_test_agent.transport.sim import flex as simflex
from b1500_test_agent.transport.sim.state import load_state_file
from b1500_test_agent.transport.sim.units.spgu_output import decode_patterns, decode_sequence
from tests.sim.spgu_helpers import errors_of, open_sim, resistor_load, send, spgu_scenario, two_level_setup

pytestmark = pytest.mark.spgu

ALWG_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "flex" / "spgu" / "alwg_blocks.yaml"


def spst(sim) -> str:
    return sim.query("SPST?")


# -- SPST? state machine (PG PDF 142, 513-514; ATV-19) ------------------------------------------------------------


def test_count_mode_runs_exactly_count_periods() -> None:
    sim = open_sim()
    two_level_setup(sim, run="SPRM 1,3", period=1e-5)
    assert spst(sim) == "0"  # set up, not started
    send(sim, "SRP")
    assert spst(sim) == "1"
    sim.wait(3e-5 - 1e-9)
    assert spst(sim) == "1"
    sim.wait(1e-9)
    assert spst(sim) == "0"  # 3 x 10 us, exactly
    run = sim.instrument.spgu_runs[-1]
    assert run.end_s == pytest.approx(3e-5) and run.unit_s == 1e-5 and run.mode == "pg"


def test_duration_mode_ends_at_the_duration() -> None:
    sim = open_sim()
    two_level_setup(sim, run="SPRM 2,0.00125", period=1e-3, width=1e-4)
    send(sim, "SRP")
    sim.wait(0.00125 - 1e-9)
    assert spst(sim) == "1"
    sim.wait(2e-9)
    assert spst(sim) == "0"


def test_free_run_after_rst_until_spp() -> None:
    """``*RST`` restores free run (Table 2-12, PDF 179): ``SRP`` without ``SPRM`` never stops by itself."""
    sim = open_sim()
    send(sim, "*RST", "CN 101", "SPUPD 101", "SRP")
    sim.wait(3600.0)
    assert spst(sim) == "1"
    assert "SPGU output active (SPST? 1)" in sim.instrument.unsafe_reasons()
    assert sim.instrument.spgu_runs[-1].end_s is None
    assert sim.instrument.outputs()[1].voltage == -0.5  # initial pulse source: base -0.5 V, peak 0.5 V
    send(sim, "SPP")
    assert spst(sim) == "0"


@pytest.mark.parametrize(("stop", "stops"), [
    ("SPP", True), ("SPRM 1,5", True), ("SIM 1", True), ("CL 101", True), ("CL", True), ("SRP", False),
    ("DZ", False), ("AB", False),
])
def test_stop_conditions(stop: str, stops: bool) -> None:
    """PG PDF 142: SPP, the count/duration, an output switch OFF and an SPRM change stop the output (SIM and SRP set
    the output up again); DZ and AB are not stop conditions."""
    sim = open_sim()
    two_level_setup(sim, run="SPRM 2,10")
    send(sim, "SRP")
    sim.wait(1.0)
    send(sim, stop)
    assert spst(sim) == ("0" if stops else "1")


def test_dz_zeroes_the_static_level_but_not_a_running_output() -> None:
    sim = open_sim()
    two_level_setup(sim, base=-1.0, run="SPRM 2,1")
    assert sim.instrument.outputs()[1].voltage == -1.0  # SPUPD applies the base level
    send(sim, "SRP", "DZ")
    assert spst(sim) == "1" and sim.instrument.outputs()[1].voltage == 0.0


def test_device_clear_and_rst_stop_the_output() -> None:
    sim = open_sim()
    two_level_setup(sim, run="SPRM 2,10")
    send(sim, "SRP")
    sim.device_clear()
    assert spst(sim) == "0"
    two_level_setup(sim, run="SPRM 2,10")
    send(sim, "SRP", "*RST")
    assert spst(sim) == "0"


def test_a_run_continues_in_another_process(tmp_path: Path) -> None:
    path = tmp_path / "spgu.state.json"
    first = open_sim(state_file=path)
    two_level_setup(first, run="SPRM 2,10")
    send(first, "SRP")
    first.wait(4.0)
    assert spst(first) == "1"
    first.save_state()
    stored = load_state_file(path)
    assert stored is not None and stored.spgu_output_active and stored.spgu_remaining_s == pytest.approx(6.0)
    second = open_sim(state_file=path)
    second.wait(5.9)
    assert spst(second) == "1"  # the other process's run: timing known, levels not
    second.wait(0.2)
    assert spst(second) == "0"
    second.save_state()
    third = open_sim(state_file=path)
    assert spst(third) == "0"


# -- levels at the DUT (blueprint v2 4.2: open-load doubling exact, delivered V +-1 %) -----------------------------


@pytest.mark.parametrize("ser", [50.0, 1e6, 1000.0, 0.1])
def test_open_load_level_is_exact(ser: float) -> None:
    sim = open_sim()
    peak = 3.0 if ser >= 50 else 0.05
    two_level_setup(sim, peak=peak, ser=ser)
    send(sim, "SRP")
    record = sim.instrument.spgu_runs[-1].channels[1]
    assert record.delivered_v == peak * (ser + 50) / ser and record.open_load_v == record.delivered_v
    if ser == 50.0:
        assert record.delivered_v == 2 * peak  # open-load doubling, exact


@pytest.mark.parametrize(("r_dut", "ser"), [(50.0, 50.0), (1000.0, 1000.0), (1000.0, 50.0), (50.0, 1e6),
                                            (1e5, 1e5), (10.0, 10.0)])
def test_delivered_level_follows_the_ser_divider(r_dut: float, ser: float) -> None:
    sim = open_sim(resistor_load(r_dut))
    two_level_setup(sim, peak=2.0, ser=ser)
    send(sim, "SRP")
    expected = 2.0 * (ser + 50) / ser * r_dut / (r_dut + 50)
    delivered = sim.instrument.spgu_runs[-1].channels[1].delivered_v
    assert delivered == pytest.approx(expected, rel=1e-9)
    if ser == r_dut:
        assert delivered == pytest.approx(2.0, rel=0.01)  # the matched load gets the set level (ATV-20)


def test_static_base_level_drives_the_load() -> None:
    sim = open_sim(resistor_load(1000.0))
    two_level_setup(sim, base=1.0, peak=2.0, ser=1000.0)
    lop = sim.query("LOP?")
    assert lop.startswith("LOP00")  # Table 4-26 has no SPGU code
    levels = sim.instrument._on_levels()
    assert levels[1] == pytest.approx(1.0, rel=1e-9)


def test_load_mismatch_changes_the_delivered_level_and_corrser_reads_it() -> None:
    sim = open_sim(resistor_load(1e5))
    sim.inject(SpguLoadMismatch(channel=101, load_ohm=50.0))
    two_level_setup(sim, peak=4.0, ser=1e6)
    send(sim, "SRP")
    record = sim.instrument.spgu_runs[-1].channels[1]
    assert record.delivered_v == pytest.approx(4.0 * (1e6 + 50) / 1e6 * 50 / 100)
    assert record.delivered_v < record.open_load_v  # never above what the guard checked
    sim.wait(1.0)
    load, voltage = (float(x) for x in sim.query("CORRSER? 101,0,1E-07,5E-06,1").split(","))
    assert load == pytest.approx(50.0) and voltage == pytest.approx(record.delivered_v)


def test_corrser_measures_the_load_and_mode_1_sets_ser() -> None:
    sim = open_sim(resistor_load(470.0))
    two_level_setup(sim, peak=2.0, ser=50.0)
    load, voltage = (float(x) for x in sim.query("CORRSER? 101,0,2E-07,5E-06,1").split(","))
    assert load == pytest.approx(470.0, rel=1e-6) and voltage == pytest.approx(2.0 * 2 * 470 / 520, rel=1e-6)
    assert spst(sim) == "0" and errors_of(sim) == []
    load, voltage = (float(x) for x in sim.query("CORRSER? 101,1,2E-07,5E-06,1").split(","))
    send(sim, "SPUPD 101", "SRP")
    assert sim.instrument.spgu_runs[-1].channels[1].delivered_v == pytest.approx(2.0, rel=1e-6)  # SER = 470 now
    open_load = open_sim()
    two_level_setup(open_load, peak=2.0)
    assert float(open_load.query("CORRSER? 101,0,0,5E-06,1").split(",")[0]) == 1e6  # open: the SER maximum


# -- errors (PG PDF 590-593) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("commands", "code"), [
    (["SIM 1", "SPM 101,1"], 2003),
    (["SIM 1", "SPT 101,1,0,1E-6,2E-8"], 2003),
    (["SIM 0", "ALW 101,42"], 2004),
    (["SIM 0", "ALS 32"], 2004),
    (["SER 101,0.05"], 2101),
    (["SER 101,2000000"], 2101),
    (["SPPER 11"], 2103),
    (["SPRM 1,0"], 2104),
    (["SPRM 1,1000001"], 2104),
    (["SPRM 2,1E-7"], 2115),
    (["SPV 101,1,0,41"], 2105),
    (["SPT 101,1,0,1E-6,2E-9"], 2108),
    (["SPT 101,1,0,1E-6,1E-6"], 2111),
    (["SPT 101,3,0,1E-6,2E-8"], 2002),
    (["SPT 101,1,0,5E-9,2E-9"], 2114),
    (["SPM 103,1"], 121),
    (["SPM 3,1"], 2000),
    (["SPM 201,1"], 2000),
    (["CN 101", "SPPER 1E-6", "SPT 101,1,0,9.9E-7,2E-8", "SPUPD 101"], 2112),
    (["SPUPD 101"], 200),
    (["CN 101", "SER 101,50", "SPV 101,1,0,25", "SPUPD 101"], 2107),
    (["CN 101", "SPM 101,3", "SPV 101,1,0,25", "SPV 101,2,0,25", "SPT 101,2,5E-7,1E-7,2E-8", "SPPER 1E-5",
      "SER 101,1E6", "SPUPD 101"], 2106),
    (["ODSW 101,1,0,9.95E-7,1E-7"], 2122),
    (["ODSW 101,1,0,0,5E-8"], 2123),
    (["SPPER 1E-6", "ODSW 101,1,0,5E-7,6E-7"], 2121),
    (["CN 101", "SPUPD 101", "CORRSER? 101,0,1E-6,5E-6,1"], 2132),
    (["CN 101", "SPPER 1E-5", "SPUPD 101", "CORRSER? 101,0,0,1E-7,1"], 2133),
    (["CN 101", "SPPER 1E-5", "SPUPD 101", "CORRSER? 101,0,0,5E-6,0"], 2134),
    (["CN 101", "SPPER 1E-5", "SPUPD 101", "CORRSER? 101,0,0,5E-6,3"], 2131),
    (["CN 101", "SPPER 1E-5", "SPV 101,1,0,0.5", "SPUPD 101", "CORRSER? 101,0,0,5E-6,1"], 2204),
    (["CN 101", "SIM 1", "SPUPD 101"], 2155),
])
def test_errors_follow_the_manual(commands: list[str], code: int) -> None:
    sim = open_sim()
    for command in commands:
        sim.write(command)
    assert code in errors_of(sim)
    assert spst(sim) == "0"


# -- ALWG (PG PDF 147-151, 360-362) -----------------------------------------------------------------------------------

ALWG = yaml.safe_load(ALWG_FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", [c for c in ALWG["patterns"] if "hex" in c], ids=lambda c: c["name"])
def test_pattern_blocks_decode_as_table_2_4(case: dict) -> None:
    patterns = decode_patterns(bytes.fromhex("".join(case["hex"].split())))
    assert [(p.initial, list(p.vectors)) for p in patterns] == [
        (pytest.approx(p["initial_v"]), [(pytest.approx(dt), pytest.approx(v), closed) for dt, v, closed in
                                         p["vectors"]]) for p in case["patterns"]]


def test_sequence_block_decodes_as_table_2_5() -> None:
    case = ALWG["sequences"][0]
    assert decode_sequence(bytes.fromhex("".join(case["hex"].split()))) == [tuple(c) for c in case["cycles"]]


def alwg_blocks() -> tuple[bytes, bytes]:
    case = ALWG["patterns"][0]  # 1 us ramp 0 -> 1 V (switch closed), 1 us ramp -> 0 V (open): 2 us per pattern
    pattern = bytes.fromhex("".join(case["hex"].split()))
    sequence = bytes.fromhex("0000000100000000000000000000000000000000" + "000100000003")  # pattern 1 x 3
    return pattern, sequence


def test_alwg_output_runs_count_sequences() -> None:
    sim = open_sim()
    pattern, sequence = alwg_blocks()
    send(sim, "CN 101", "SIM 1", "SPRM 1,4", "SER 101,1E6", "ODSW 101,1,0")
    sim.write_block(f"ALW 101,{len(pattern)}", pattern)
    sim.write_block(f"ALS {len(sequence)}", sequence)
    send(sim, "SPUPD 101", "SRP")
    assert errors_of(sim) == []
    run = sim.instrument.spgu_runs[-1]
    assert run.mode == "alwg" and run.unit_s == pytest.approx(6e-6) and run.end_s == pytest.approx(24e-6)
    assert run.channels[1].delivered_v == pytest.approx(0.875 * (1e6 + 50) / 1e6)  # last ramp step's mid level
    sim.wait(24e-6 - 1e-9)
    assert spst(sim) == "1"
    sim.wait(2e-9)
    assert spst(sim) == "0"
    assert [r.mnemonic for r in sim.instrument.command_log].count("<block>") == 2


def test_alwg_setup_delay_between_patterns_of_different_numbers() -> None:
    sim = open_sim()
    one = bytes.fromhex("0000000200000000000000000000000000000000" + "000100000000" + "000f4240800003e8"
                        + "000100000000" + "00000000800003e8")  # two 1 us patterns
    sequence = bytes.fromhex("0000000200000000000000000000000000000000" + "000100000002" + "000200000001")
    send(sim, "CN 101", "SIM 1", "SPRM 1,2", "SER 101,1E6")
    sim.write_block(f"ALW 101,{len(one)}", one)
    sim.write_block(f"ALS {len(sequence)}", sequence)
    send(sim, "SPUPD 101", "SRP")
    run = sim.instrument.spgu_runs[-1]
    # 2 x 1 us + 50 ns + 1 us per sequence; two sequences with the 50 ns change back in between
    assert run.unit_s == pytest.approx(3.1e-6) and run.end_s == pytest.approx(2 * 3.05e-6 + 5e-8)


@pytest.mark.parametrize(("block", "code"), [
    ("0000000100000000000000000000000000000000" + "000100000000" + "000f42408000000f", 2157),  # 15 ns
    ("0000000100000000000000000000000000000000" + "000100000000" + "0262600080000064", 2158),  # 40.0128 V
    ("0000000100000000000000000000000000000000" + "000100000000" + "000f4241800003e8", 2158),  # not on 1 mV

    ("0000000100000000000000000000000000000000" + "000200000000" + "000f4240800003e8", 2156),  # 2 vectors announced
])
def test_bad_pattern_data_is_refused(block: str, code: int) -> None:
    sim = open_sim()
    data = bytes.fromhex(block)
    send(sim, "SIM 1")
    sim.write_block(f"ALW 101,{len(data)}", data)
    assert errors_of(sim) == [code]


def test_block_problems() -> None:
    sim = open_sim()
    pattern, sequence = alwg_blocks()
    send(sim, "SIM 1", f"ALW 101,{len(pattern)}")
    sim.write("CN 101")  # a command where the block should come
    assert errors_of(sim) == [2156]
    sim.instrument.receive_block(pattern)  # a block nobody announced
    assert errors_of(sim) == [simflex.ERR_PARAMETER]
    sim.write_block(f"ALS {len(sequence) + 6}", sequence)  # announced size differs
    assert errors_of(sim) == [2152]
    bad = bytes.fromhex("0000000100000000000000000000000000000000" + "000500000003")
    sim.write_block(f"ALW 101,{len(pattern)}", pattern)
    sim.write_block(f"ALS {len(bad)}", bad)
    send(sim, "CN 101")
    sim.write("SPUPD 101")
    assert errors_of(sim) == [2153]  # pattern 5 of 1
    sim.write("ALW 101,20")  # a header too short for any pattern: refused, so the block after it is a stray one
    sim.instrument.receive_block(bytes(20))
    assert errors_of(sim) == [2156, simflex.ERR_PARAMETER]
    fresh = open_sim()
    send(fresh, "CN 101", "SIM 1")
    fresh.write_block(f"ALW 101,{len(pattern)}", pattern)
    fresh.write("SPUPD 101")
    assert errors_of(fresh) == [2151]  # no sequence data


# -- faults (blueprint v2 4.3) ---------------------------------------------------------------------------------------


def test_spgu_no_stop_ignores_everything_but_the_spp_after_the_ignored_ones() -> None:
    sim = open_sim()
    sim.inject(SpguNoStop(spp_ignored=1))
    two_level_setup(sim, run="SPRM 1,3")
    send(sim, "SRP")
    sim.wait(1.0)
    assert spst(sim) == "1"  # the count ended long ago
    send(sim, "CL", "*RST")
    sim.device_clear()
    assert spst(sim) == "1"
    send(sim, "SPP")
    assert spst(sim) == "1"  # the first SPP is ignored
    send(sim, "SPP")
    assert spst(sim) == "0"
    two_level_setup(sim, run="SPRM 1,3")
    send(sim, "SRP")
    sim.wait(1.0)
    assert spst(sim) == "0"  # the fault has ended


def test_spgu_no_stop_without_a_count_never_stops() -> None:
    sim = open_sim()
    sim.inject(SpguNoStop())
    two_level_setup(sim, run="SPRM 1,1")
    send(sim, "SRP")
    for _ in range(5):
        send(sim, "SPP")
    sim.device_clear()
    assert spst(sim) == "1"
    sim.clear_faults()
    send(sim, "SPP")
    assert spst(sim) == "0"


def test_scenario_without_spgu_refuses_spgu_commands() -> None:
    sim = open_sim(spgu_scenario(slots=[{"slot": 3, "model": "B1517A"}]))
    sim.write("SER 101,50")
    assert errors_of(sim) == [2000]
    assert spst(sim) == "0"


def test_a_channel_switched_off_and_on_needs_spupd_again() -> None:
    sim = open_sim()
    two_level_setup(sim, run="SPRM 2,1")
    send(sim, "CL 101", "CN 101", "SRP")
    assert spst(sim) == "0" and sim.instrument.spgu_runs == []  # nothing set up on the new output state
    send(sim, "SPUPD 101", "SRP")
    assert spst(sim) == "1"


def test_a_dc_channel_holds_its_level_and_does_not_run() -> None:
    sim = open_sim(resistor_load(1000.0))
    send(sim, "CN 101", "SIM 0", "SER 101,1000", "SPM 101,0", "SPV 101,0,1.5", "SPUPD 101", "SRP")
    assert spst(sim) == "0" and sim.instrument.outputs()[1].voltage == 1.5
    assert sim.instrument._on_levels()[1] == pytest.approx(1.5, rel=1e-9)  # matched load: the set level
    send(sim, "SPPER 1E-5")
    load, voltage = (float(x) for x in sim.query("CORRSER? 101,0,0,5E-06,1").split(","))
    assert load == pytest.approx(1000.0, rel=1e-6) and voltage == pytest.approx(1.5, rel=1e-6)
