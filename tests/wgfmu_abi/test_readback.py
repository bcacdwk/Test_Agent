"""Chunked readback of the WGFMU binding (blueprint v2 2.4 "readback in 100,000-point chunks [E: lwp]", 7.1; WP10.2):
``measure_values`` reads at most ``READBACK_CHUNK`` values per ``WGFMU_getMeasureValues`` call into preallocated
numpy buffers, as ``lwp/1530/LFN_noise_meas.cpp`` does for its 504,000-point event, and returns what one simulator
call returns: a short chunk ends the read, the end of the data inside a chunk is not an error."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.api import READBACK_CHUNK, WgfmuError
from tests.wgfmu_abi.conftest import Binding

pytestmark = pytest.mark.wgfmu

ADDRESS = "GPIB0::17::INSTR"
LWP_POINTS = 504_000
"""Values of the lab's single measure event at 100 ns (blueprint v2 1.1)."""


def sampled_run(binding: Binding, points: int, interval: float = 1e-7) -> None:
    """One Fast IV voltage-measuring channel (101) holding 0.5 V while one event samples ``points`` values."""
    wg = binding.st.wg  # audited binding
    wg.clear()
    wg.create_pattern("hold", 0.5)
    wg.add_vectors("hold", [points * interval + 1e-6], [0.5])
    wg.set_measure_event("hold", "sample", 0.0, points, interval, 0.0, False)
    wg.add_sequence(101, "hold", 1)
    wg.open_session(ADDRESS)
    wg.set_operation_mode(101, "fastiv")
    wg.set_measure_mode(101, "voltage")
    wg.connect(101)
    wg.execute()
    wg.wait_until_completed()


def chunk_calls(binding: Binding) -> list[tuple[int, int]]:
    """``(offset, requested length)`` of every ``WGFMU_getMeasureValues`` call (the length as passed in)."""
    return [(c.args[1], c.requested) for c in binding.lib.calls if c.name == "WGFMU_getMeasureValues"]


def test_the_lab_sized_event_is_read_in_100000_value_chunks(binding: Binding) -> None:
    sampled_run(binding, LWP_POINTS)
    assert binding.dll.measure_value_size(101) == (LWP_POINTS, LWP_POINTS)
    times, values = binding.st.wg.measure_values(101, 0, LWP_POINTS)
    assert READBACK_CHUNK == 100_000
    assert chunk_calls(binding) == [(k * 100_000, 100_000) for k in range(5)] + [(500_000, 4_000)]
    direct_t, direct_v = binding.st.sim.measure_values(101, 0, LWP_POINTS)  # the simulator's own one-call read
    assert np.array_equal(times, direct_t) and np.array_equal(values, direct_v)
    assert len(times) == LWP_POINTS and np.allclose(np.diff(times), 1e-7) and np.allclose(values, 0.5)
    assert times.dtype == values.dtype == np.float64 and times.flags.owndata and times.flags.c_contiguous
    event = binding.st.wg.sink.events[-1]  # one audited protocol call, whatever the chunks
    assert event.cmd == "WGFMU_getMeasureValues" and event.resp == f"n={LWP_POINTS}"


def test_a_read_from_an_offset_reads_the_rest(binding: Binding) -> None:
    sampled_run(binding, 250_000)
    times, _ = binding.dll.measure_values(101, 30_000, 220_000)
    assert chunk_calls(binding) == [(30_000, 100_000), (130_000, 100_000), (230_000, 20_000)]
    assert len(times) == 220_000 and times[0] == pytest.approx(30_000 * 1e-7)


def test_asking_for_more_than_there_is_stops_at_the_short_chunk(binding: Binding) -> None:
    sampled_run(binding, 150_000)
    times, _ = binding.dll.measure_values(101, 0, 600_000)
    assert len(times) == 150_000
    assert [length for _, length in chunk_calls(binding)] == [100_000, 100_000]  # the second came back short
    assert binding.dll.errors() == []


def test_data_ending_on_a_chunk_boundary_is_not_an_error(binding: Binding) -> None:
    sampled_run(binding, 200_000)
    times, values = binding.dll.measure_values(101, 0, 300_000)
    assert len(times) == len(values) == 200_000
    assert chunk_calls(binding) == [(0, 100_000), (100_000, 100_000), (200_000, 100_000)]
    assert binding.dll.errors() == []  # the third chunk's "offset at the end" string is not a failure of the read


def test_values_not_measured_yet_end_the_read(binding: Binding) -> None:
    sampled_run(binding, 250_000)
    binding.lib.fail("WGFMU_getMeasureValues", api.RESULT_NOT_READY, "measure_values: -14 not measured yet", nth=2)
    times, _ = binding.dll.measure_values(101, 0, 250_000)
    assert len(times) == 100_000 and binding.dll.errors() == []


def test_a_failing_first_chunk_raises(binding: Binding) -> None:
    sampled_run(binding, 250_000)
    binding.lib.fail("WGFMU_getMeasureValues", api.RESULT_NOT_READY, "measure_values: -14 not measured yet")
    with pytest.raises(WgfmuError) as caught:
        binding.dll.measure_values(101, 0, 250_000)
    assert caught.value.rc == api.RESULT_NOT_READY and caught.value.function == "measure_values"


def test_any_other_failure_of_a_later_chunk_raises(binding: Binding) -> None:
    sampled_run(binding, 250_000)
    binding.lib.fail("WGFMU_getMeasureValues", api.FW_ERROR, "measure_values: firmware error 3015", nth=2)
    with pytest.raises(WgfmuError) as caught:
        binding.dll.measure_values(101, 0, 250_000)
    assert (caught.value.wgfmu_code, caught.value.rc) == (3015, api.FW_ERROR)
    assert binding.dll.errors() == ["measure_values: firmware error 3015"]


def test_a_memory_overflow_of_the_simulator_reaches_the_caller(binding: Binding) -> None:
    """More than about 4,000,000 values stored and not read: the values after that are lost and reading them is
    firmware error 3050 (WG p125 (4-55)), through the binding with its code."""
    wg = binding.st.wg
    wg.clear()
    for name in ("a", "b"):
        wg.create_pattern(name, 0.5)
        wg.add_vectors(name, [2_100_000 * 1e-8 + 1e-6], [0.5])
        wg.set_measure_event(name, "sample", 0.0, 2_100_000, 1e-8, 0.0, False)
        wg.add_sequence(101, name, 1)
    wg.open_session(ADDRESS)
    wg.set_operation_mode(101, "fastiv")
    wg.connect(101)
    wg.execute()
    with pytest.raises(WgfmuError) as caught:  # the next call that observes the run reports it
        wg.wait_until_completed()
    assert (caught.value.wgfmu_code, caught.value.rc, caught.value.function) == (3050, api.FW_ERROR,
                                                                                 "wait_until_completed")
    with pytest.raises(WgfmuError) as lost:
        binding.dll.measure_values(101, 4_100_000, 100_000)
    assert lost.value.wgfmu_code == 3050 and "lost" in lost.value.text
    times, _ = binding.dll.measure_values(101, 0, 200_000)  # what was stored is still read in chunks
    assert len(times) == 200_000
