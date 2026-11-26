"""``memory_window`` on an analytic double sweep (WP2.2): MW = Vth_fwd - Vth_rev with each Vth method, the sign
convention, per-branch Ion/Ioff, branch refusals and the double-sweep requirement."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.analysis import RunData
from b1500_test_agent.analysis.fefet import memory_window
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from tests.unit.analysis_helpers import ekv_like_id, idvg_table, manifest, subthreshold_id
from tests.unit.helpers import assert_roundtrip

UP = np.linspace(-4.0, 4.0, 161)
VTH_FWD, VTH_REV = 1.1, 0.1


def loop(fwd: np.ndarray, rev: np.ndarray, *, status: list[str] | None = None) -> RunData:
    """Double sweep -4 -> 4 -> -4 V: ``fwd`` on the way up, ``rev`` (given on the ascending grid) on the way down."""
    vg = np.concatenate([UP, UP[::-1]])
    current = np.concatenate([fwd, rev[::-1]])
    table = idvg_table(vg, current, drain_status=status, segment=["fwd"] * UP.size + ["rev"] * UP.size)
    return RunData(manifest(recipe_id="fefet.dual_sweep_mw", params={"vd": Quantity(value=0.05, unit="V")}), table)


def test_memory_window_by_constant_current() -> None:
    data = loop(subthreshold_id(UP, v0=VTH_FWD), subthreshold_id(UP, v0=VTH_REV))
    results = memory_window(data)
    names = [r.quantity for r in results]
    assert names == ["memory_window", "vth_fwd", "vth_rev", "ion_fwd", "ioff_fwd", "ion_rev", "ioff_rev"]
    mw, fwd, rev = results[:3]
    assert mw.value == pytest.approx(VTH_FWD - VTH_REV, abs=2e-3) and mw.value > 0
    assert fwd.value == pytest.approx(VTH_FWD, abs=2e-3) and rev.value == pytest.approx(VTH_REV, abs=2e-3)
    assert mw.fit == {"vth_fwd": fwd.value, "vth_rev": rev.value}
    assert all(r.method == "memory_window" and r.outcome == "ok" for r in results)
    assert mw.method_record.params["vth_method"] == "vth_constant_current"
    assert fwd.method_record.params == {"branch_method": "vth_constant_current", "segment": "fwd"}
    ion_fwd = results[3]
    assert ion_fwd.fit["v"] == 4.0 and ion_fwd.fit["on_off_ratio"] > 1e6 and results[4].fit["v"] == -4.0
    for r in results:
        assert_roundtrip(r)


@pytest.mark.parametrize("method", ["vth_linear_extrapolation", "vth_max_gm"])
def test_memory_window_by_the_other_vth_methods(method: str) -> None:
    data = loop(ekv_like_id(UP, vth=VTH_FWD), ekv_like_id(UP, vth=VTH_REV))
    mw, fwd, _rev = memory_window(data, vth_method=method)[:3]
    assert mw.value == pytest.approx(VTH_FWD - VTH_REV, abs=5e-3)  # method offsets cancel
    assert fwd.method_record.params["branch_method"] == method and fwd.fit["vd"] == 0.05


def test_a_clockwise_loop_gives_a_negative_window_with_a_warning() -> None:
    mw = memory_window(loop(subthreshold_id(UP, v0=VTH_REV), subthreshold_id(UP, v0=VTH_FWD)))[0]
    assert mw.value == pytest.approx(VTH_REV - VTH_FWD, abs=2e-3)
    assert any("Negative memory window" in w for w in mw.warnings)


def test_the_negative_window_warning_names_sweep_direction_and_trapping_not_the_channel_type() -> None:
    """v2.1 WP21.10 (knowledge audit 04:69): the sign of a ferroelectric MW follows the sweep direction, not the
    channel type (after the positive excursion the polarization lowers Vth of n- and p-channel FeFETs alike), so the
    warning must not send the reader to the device polarity."""
    mw = memory_window(loop(subthreshold_id(UP, v0=VTH_REV), subthreshold_id(UP, v0=VTH_FWD)))[0]
    (warning,) = [w for w in mw.warnings if "Negative memory window" in w]
    assert "sweep direction" in warning and "downward-first" in warning and "charge trapping" in warning
    assert "n- and p-channel" in warning and "device polarity" not in warning


def test_a_refused_branch_refuses_the_window() -> None:
    status = ["N"] * (2 * UP.size)
    status[UP.size + 20] = "X"  # in the reverse branch
    results = memory_window(loop(subthreshold_id(UP, v0=VTH_FWD), subthreshold_id(UP, v0=VTH_REV), status=status))
    assert [r.quantity for r in results] == ["memory_window", "vth_fwd", "vth_rev"]
    assert results[0].outcome == "refused" and results[1].outcome == "ok" and results[2].outcome == "refused"
    forced = memory_window(loop(subthreshold_id(UP, v0=VTH_FWD), subthreshold_id(UP, v0=VTH_REV), status=status),
                           force=True)
    assert forced[0].outcome == "ok" and forced[0].forced_on_untrusted


def test_a_single_sweep_is_an_input_error() -> None:
    data = RunData(manifest(recipe_id="fefet.dual_sweep_mw"), idvg_table(UP, subthreshold_id(UP)))
    with pytest.raises(InvalidInputError, match="double sweep"):
        memory_window(data)
