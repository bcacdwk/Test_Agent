"""The WP10.6 recipes on backend visa (per-recipe AC ``tests/visa_loop -k <recipe>``; blueprint v2 7.1 visa-loop, 8.1
``visa_loop/``): ``fecap.pund`` and ``fefet.fast_program_read`` (kind ``wgfmu_waveform``, one WGFMU execution) and
``fecap.endurance_pund`` (kind ``pulse_read``, WGFMU path: one execution per step, cycling bursts and PUND reads) run
through the real ``VisaTransport`` and the real ``WgfmuDll`` over the fake ABI as on the lab PC: ``first_hw_run`` and
``unverified_topology`` confirmed, cleanup verified on the hardware path (``LOP?`` and a complete WGFMU safe state),
the library only while the FLEX exclusive lock was released (ATV-14), every WGFMU channel disconnected and idle, the
RSUs back on their rest path, and the table equal to the simulator backend's for the same request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.analysis import load_run
from tests.visa_loop.helpers import VisaWorld, without_switch_traffic
from tests.visa_loop.test_wgfmu_waveform_visa import lock_state, run_on_visa, sim_table

pytestmark = pytest.mark.wgfmu

_ = lock_state  # the fixture, imported for pytest

FECAP = {"pin_map": "fecap-wgfmu", "dut_profile": "fecap-generic"}
REASONS = {"first_hw_run", "unverified_pin_map", "unverified_topology"}
"""Both example pin maps are unverified (unlike mosfet-wgfmu, they match no committed lab wiring)."""
CASES: list[dict[str, Any]] = [
    {"recipe_id": "fecap.pund", "scenario": "fecap_basic", "request": {"params": {}, **FECAP}, "rows": 800,
     "executions": 1, "reasons": REASONS},
    {"recipe_id": "fefet.fast_program_read", "scenario": "fefet_lab",
     "request": {"params": {}, "pin_map": "fefet-wgfmu", "dut_profile": "fefet-lab"}, "rows": 3 * 47,
     "executions": 1, "reasons": REASONS},
    {"recipe_id": "fecap.endurance_pund", "scenario": "fecap_basic",
     "request": {"params": {"cycles": 1000, "reads_per_decade": 1}, **FECAP}, "rows": 4 * 800, "executions": 7,
     "reasons": REASONS},
]
"""The card example requests (the endurance run shortened to 10^3 cycles: PUND reads at 1, 10, 100, 1000 cycles and
three cycling bursts between them)."""


@pytest.mark.parametrize("case", CASES, ids=[c["recipe_id"] for c in CASES])
def test_pund_and_fast_program_read_run_on_backend_visa(case: dict[str, Any], world: VisaWorld, tmp_path: Path,
                                                        lock_state: list[tuple[str, bool]]) -> None:
    bus, result = run_on_visa(world, case, lock_state)
    sent = without_switch_traffic(bus.instrument.command_log)
    assert sent[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"] and "CN" not in sent  # WGFMU only
    names = [name for name, _ in lock_state]
    assert names.count("WGFMU_execute") == case["executions"]
    assert names.count("WGFMU_openSession") == 2  # the pre-execute read and the one phase of the run
    visa = load_run(result.run_id or "", data_root=world.data).table
    assert len(visa) == case["rows"]
    assert visa.equals(sim_table(case, tmp_path / "sim"))  # same values as the simulator backend
