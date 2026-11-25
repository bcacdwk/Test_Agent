"""``memory_window_pulse`` on synthetic program/read tables with known truth (WP9.4, blueprint v2 2.10 ``nvm.py``):
read grouping by cycle and phase, the Vth window per cycle and its spread, spot read currents and their ratio, the
default ``x`` of a ``gate_read`` sweep, a program-only sequence, refusals and unusable calls, and the registry
entry."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import ANALYSIS_METHODS, memory_window_pulse, pulse_reads, run_method
from b1500_test_agent.analysis.dataset import with_trust
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, Quantity
from tests.unit.analysis_helpers import run_of, subthreshold_id

pytestmark = pytest.mark.spgu

VG = np.round(np.linspace(-0.5, 1.8, 47), 9)
V0 = 0.3
"""``subthreshold_id`` reaches its i0 = 100 nA at v0: the constant-current Vth of an unshifted read."""


def found(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def pr_table(cycles: Sequence[tuple[float, float]], *, initial: float | None = 0.4, x: str = "gate_read_V",
             sequence: Sequence[str] = ("erase", "program"), status: dict[tuple[int, str], str] | None = None,
             spot: float | None = None, samples: int = 3) -> pd.DataFrame:
    """A pulse_read table: an optional reference read (cycle 0, phase read, Vth ``initial``), then per cycle
    ``(vth_erase, vth_program)`` one read per operation of ``sequence``; staircase reads of ``subthreshold_id`` shifted
    to that Vth, or (``spot``) ``samples`` spot readings at gate level ``spot``. ``status`` sets the drain status of the
    first five points of read ``(cycle, phase)``."""
    rows: list[dict[str, Any]] = []
    reads: list[tuple[int, str, float]] = [] if initial is None else [(0, "read", initial)]
    for cycle, (erase, program) in enumerate(cycles, start=1):
        reads += [(cycle, name, erase if name == "erase" else program) for name in sequence]
    for cycle, phase, vth in reads:
        letter = (status or {}).get((cycle, phase), "N")
        levels = [spot] * samples if spot is not None else list(VG)
        currents = subthreshold_id(np.array(levels) - (vth - V0), v0=V0)
        for index, (vg, current) in enumerate(zip(levels, currents, strict=True)):
            rows.append({"cycle": cycle, "phase": phase, x: vg, "gate_read_I": 1e-13, "gate_read_I_status": "N",
                         "drain_I": current, "drain_I_status": letter if index < 5 else "N", "drain_V": 0.05})
    table = pd.DataFrame(rows)
    table.insert(0, "step", np.arange(len(table)))
    return with_trust(table)


def pr_run(table: pd.DataFrame, recipe_id: str = "fefet.pulse_write_read", **params: Any) -> Any:
    return run_of(table, recipe_id, kind="pulse_read",
                  params={k: Quantity(value=v, unit="V") for k, v in params.items()})


def test_reads_are_grouped_by_cycle_and_phase_in_acquisition_order() -> None:
    reads = pulse_reads(pr_run(pr_table([(1.0, 0.0), (1.02, 0.01)])), "test")
    assert [(r.cycle, r.state, len(r.rows)) for r in reads] == [
        (0, "initial", 47), (1, "erase", 47), (1, "program", 47), (2, "erase", 47), (2, "program", 47)]


def test_memory_window_is_the_mean_erase_minus_program_threshold() -> None:
    results = found(memory_window_pulse(pr_run(pr_table([(1.0, 0.0), (1.04, 0.02), (1.02, 0.01)]))))
    assert list(results) == ["memory_window", "vth_program", "vth_erase", "vth_initial"]
    mw, prog, erase = results["memory_window"], results["vth_program"], results["vth_erase"]
    assert prog.value == pytest.approx(0.01, abs=2e-3) and erase.value == pytest.approx(1.02, abs=2e-3)
    assert mw.value == pytest.approx(1.01, abs=2e-3) and mw.unit == "V" and mw.derived
    assert mw.fit["cycles"] == 3 and mw.fit["mw_min"] == pytest.approx(1.0, abs=2e-3)
    assert mw.fit["mw_max"] == pytest.approx(1.02, abs=2e-3) and mw.fit["mw_std"] == pytest.approx(0.01, abs=2e-3)
    assert mw.fit["vth_initial"] == pytest.approx(0.4, abs=2e-3) and results["vth_initial"].value == pytest.approx(0.4,
                                                                                                                  abs=2e-3)
    assert erase.fit["reads"] == 3 and erase.fit["first"] == pytest.approx(1.0, abs=2e-3)
    assert mw.method_record.params["quantity"] == "vth" and mw.method_record.params["x"] == "gate_read_V"
    assert not mw.warnings


def test_a_negative_window_is_flagged() -> None:
    mw = found(memory_window_pulse(pr_run(pr_table([(0.0, 1.0)]))))["memory_window"]
    assert mw.value == pytest.approx(-1.0, abs=2e-3) and any("Negative memory window" in w for w in mw.warnings)


def test_linear_extrapolation_gives_the_same_window() -> None:
    table = pr_table([(1.0, 0.0)])
    cc = found(memory_window_pulse(pr_run(table)))["memory_window"].value
    le = found(memory_window_pulse(pr_run(table, vd=0.05), vth_method="linear_extrapolation"))["memory_window"].value
    assert le == pytest.approx(cc, abs=0.01)  # a rigid shift: the method offset cancels in the window


def test_spot_reads_give_read_currents_and_their_ratio() -> None:
    table = pr_table([(1.0, 0.0), (1.0, 0.0)], spot=0.6)
    results = found(memory_window_pulse(pr_run(table, "spgu.program_smu_read")))
    assert list(results) == ["current_ratio", "i_program", "i_erase", "i_initial"]
    i_prog = float(subthreshold_id(np.array([0.6 + V0]), v0=V0)[0])
    i_erase = float(subthreshold_id(np.array([0.6 - 1.0 + V0]), v0=V0)[0])
    assert results["i_program"].value == pytest.approx(i_prog, rel=1e-6)
    assert results["i_erase"].value == pytest.approx(i_erase, rel=1e-6)
    assert results["current_ratio"].value == pytest.approx(i_prog / i_erase, rel=1e-6)
    assert results["current_ratio"].unit == "1" and results["i_program"].unit == "A"


def test_current_on_sweep_reads_uses_the_read_level_parameter() -> None:
    table = pr_table([(1.0, 0.0)])
    results = found(memory_window_pulse(pr_run(table, vg_read=0.6), quantity="current"))
    assert results["i_program"].method_record.params["at_v"] == 0.6
    with pytest.raises(InvalidInputError, match="pass at_v"):
        memory_window_pulse(pr_run(table), quantity="current")


def test_a_program_only_sequence_reports_the_state_without_a_window() -> None:
    table = pr_table([(0.0, 0.3), (0.0, 0.2), (0.0, 0.1)], sequence=("program",))
    results = found(memory_window_pulse(pr_run(table, "spgu.program_smu_read")))
    assert "memory_window" not in results and "vth_erase" not in results
    program = results["vth_program"]
    assert program.fit["first"] == pytest.approx(0.3, abs=2e-3) and program.fit["last"] == pytest.approx(0.1, abs=2e-3)


def test_an_untrusted_read_drops_out_and_all_untrusted_refuses() -> None:
    table = pr_table([(1.0, 0.0), (1.1, 0.1)], status={(2, "erase"): "X"})
    results = found(memory_window_pulse(pr_run(table)))
    assert results["vth_erase"].fit["reads"] == 1 and results["memory_window"].fit["cycles"] == 1
    assert any("erase read of cycle 2 left out" in w for w in results["memory_window"].warnings)
    refused = found(memory_window_pulse(pr_run(pr_table([(1.0, 0.0)], status={(1, "erase"): "X"}))))
    assert refused["vth_erase"].outcome == "refused" and refused["memory_window"].outcome == "failed"
    forced = found(memory_window_pulse(pr_run(pr_table([(1.0, 0.0)], status={(1, "erase"): "X"})), force=True))
    assert forced["memory_window"].outcome == "ok" and forced["memory_window"].forced_on_untrusted


def test_tables_that_are_not_program_read_runs_are_unusable_calls() -> None:
    table = pr_table([(1.0, 0.0)])
    with pytest.raises(InvalidInputError, match="kind pulse_read"):
        memory_window_pulse(pr_run(table.drop(columns=["phase"])))
    with pytest.raises(InvalidInputError, match="no read after a program or erase pulse"):
        memory_window_pulse(pr_run(pr_table([], initial=0.4)))
    with pytest.raises(InvalidInputError, match="no column 'nope_I'"):
        memory_window_pulse(pr_run(table), y="nope_I")


def test_registry_entry_and_applicability() -> None:
    method = ANALYSIS_METHODS["memory_window_pulse"]
    assert method.families == ("nvm",)
    assert method.kinds == ("pulse_read", "wgfmu_waveform")  # WP10.6: fefet.fast_program_read (builder program_read)
    assert method.applies_to("fefet.pulse_write_read", "pulse_read")
    assert method.applies_to("spgu.program_smu_read", "pulse_read")
    assert not method.applies_to("fefet.dual_sweep_mw", "smu_staircase")
    out = run_method("memory_window_pulse", pr_run(pr_table([(1.0, 0.0)])), {"i_crit_a": 1e-7})
    assert isinstance(out, list) and found(out)["memory_window"].value == pytest.approx(1.0, abs=2e-3)
