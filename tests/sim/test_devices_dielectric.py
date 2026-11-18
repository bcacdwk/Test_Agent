"""``dielectric`` device truth (blueprint 4.2, WP5.9): FN + ohmic leakage, seeded Weibull TDDB (t_bd within one
sample interval, Weibull shape/scale over sites, E-model acceleration), post-breakdown ohmic path, BDV ±2 %, SILC
and state."""

from __future__ import annotations

import math

import numpy as np
import pytest

from b1500_test_agent.models.sim import DielectricParams
from b1500_test_agent.transport.sim.devices.dielectric import DielectricDevice
from tests.sim.device_fits import EPS0_F_CM, linfit


def oxide(**extra: float) -> DielectricDevice:
    return DielectricDevice("ox", DielectricParams.model_validate({"seed": 11, **extra}))


def bias(v: float) -> dict[str, float | None]:
    return {"top": v, "bottom": 0.0}


def test_fowler_nordheim_and_ohmic_leakage() -> None:
    device = oxide(leak_s=1e-12)
    area, tox = 1e4 * 1e-8, 5e-7
    for v in (2.0, 3.5, -4.0, 5.0):
        e = abs(v) / tox
        fn = math.copysign(1.25e-6 * e * e * math.exp(-2.5e8 / e) * area, v)
        assert device.terminal_currents(bias(v))["top"] == pytest.approx(fn + 1e-12 * v, rel=1e-12)
    # FN plot: ln(J/E²) is linear in 1/E with slope -B
    fields = np.linspace(8e6, 11e6, 20)
    j = np.array([device.fn_current(e * tox) / area for e in fields])
    slope, _ = linfit(1 / fields, np.log(j / fields ** 2))
    assert slope == pytest.approx(-2.5e8, rel=1e-9)
    assert device.terminal_currents({"top": 1.0, "bottom": None}) == {"top": 0.0, "bottom": 0.0}


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_constant_voltage_stress_breaks_within_one_sample_interval(seed: int) -> None:
    device = oxide(seed=seed, tbd_eta_s=10.0, tbd_v_ref=5.5)
    v, interval = 5.5, 0.05
    t_bd = device.t_bd(v)
    assert t_bd == pytest.approx(10.0 * device.weibull_w ** (1 / 1.5), rel=1e-12)
    pre = device.conduction(v)
    times, currents = [], []
    t = 0.0
    while t < 3 * t_bd + 1.0:
        t += interval
        times.append(t)
        currents.append(device.advance(interval, bias(v))["top"])
    k = next(i for i, i_meas in enumerate(currents) if i_meas > 10 * pre)  # the jump
    assert times[k] - interval < t_bd <= times[k] + 1e-12
    assert currents[k] == pytest.approx(pre + v / 1e3, rel=1e-6)  # post-breakdown ohmic path
    assert device.broken and device.damage == 1.0 and device.t_bd(v) == 0.0


def test_weibull_statistics_over_sites_and_e_model_acceleration() -> None:
    device = oxide(seed=5, weibull_beta=1.8, tbd_eta_s=100.0, tbd_v_ref=5.0, tbd_gamma_per_v=8.0)
    lives = []
    for _ in range(400):
        lives.append(device.t_bd(5.0))
        assert device.t_bd(4.5) / device.t_bd(5.0) == pytest.approx(math.exp(8.0 * 0.5), rel=1e-9)
        device.next_site()
    t = np.sort(np.array(lives))
    n = len(t)
    f = (np.arange(1, n + 1) - 0.3) / (n + 0.4)  # Bernard's median ranks
    beta, intercept = linfit(np.log(t), np.log(-np.log(1 - f)))
    assert beta == pytest.approx(1.8, abs=0.15)
    assert math.exp(-intercept / beta) == pytest.approx(device.eta(5.0), rel=0.15)
    # deterministic: the same seed and site draw the same life in a new object
    assert oxide(seed=5, weibull_beta=1.8, tbd_eta_s=100.0, site=3).weibull_w == pytest.approx(
        DielectricDevice("x", DielectricParams(seed=5, weibull_beta=1.8, tbd_eta_s=100.0, site=3)).weibull_w)


@pytest.mark.parametrize("step", [0.02, 0.1])
def test_ramped_breakdown_voltage_within_two_percent(step: float) -> None:
    device = oxide(tox_nm=6.0, ebd_mv_cm=11.0, tbd_v_ref=6.5, tbd_eta_s=100.0)
    truth = device.bdv
    assert truth == pytest.approx(6.6)
    voltages = np.arange(step, 9.0, step)
    found = None
    for v in voltages:  # fast staircase: 1 ms per step, TDDB damage negligible
        current = device.advance(1e-3, bias(float(v)))["top"]
        if current > 1e-3:
            found = float(v)
            break
    assert found is not None and found == pytest.approx(truth, rel=0.02) and found - step < truth <= found + 1e-9
    # a quasi-static (commit) staircase breaks at the same step; a trial evaluation already sees the broken device
    fresh = oxide(tox_nm=6.0, ebd_mv_cm=11.0, tbd_v_ref=6.5, tbd_eta_s=100.0)
    assert fresh.terminal_currents(bias(7.0))["top"] == pytest.approx(fresh.conduction(7.0, broken=True))
    assert not fresh.broken
    fresh.commit(bias(6.7))
    assert fresh.broken


def test_silc_grows_with_damage_and_displacement_current() -> None:
    device = oxide(silc_s=1e-9, tbd_eta_s=1e6)
    before = device.conduction(3.0)
    device.advance(1e5, bias(5.0))  # η(5 V) = 1e6 s  # partial damage at the reference voltage
    damage = device.damage
    assert 0.0 < damage < 1.0 and not device.broken
    assert device.conduction(3.0) - before == pytest.approx(1e-9 * damage * 3.0, rel=1e-9)
    c_geo = EPS0_F_CM * 3.9 * 1e-4 / 5e-7
    assert device.truth()["c_geo_f"] == pytest.approx(c_geo)
    i = device.advance(1e-3, bias(5.1))["top"]
    assert i - device.conduction(5.1) == pytest.approx(c_geo * 0.1 / 1e-3, rel=1e-9)
    assert device.capacitance(0.0, 1e5) == pytest.approx(c_geo, rel=1e-9)


def test_state_round_trip_next_site_and_validation() -> None:
    device = oxide(tbd_eta_s=1.0)
    device.advance(0.1, bias(4.0))
    device.next_site()
    device.advance(0.2, bias(4.5))
    state = device.export_state()
    assert set(state) == {"damage", "broken", "site", "v"} and state["site"] == 1
    clone = oxide(tbd_eta_s=1.0)
    clone.import_state(state)
    assert clone.export_state() == state and clone.weibull_w == device.weibull_w
    clone.import_state(None)
    assert clone.site == 0 and not clone.broken and clone.weibull_w == oxide(tbd_eta_s=1.0).weibull_w
    with pytest.raises(ValueError, match="site"):
        clone.import_state({**state, "site": -1})
    with pytest.raises(ValueError, match="broken"):
        clone.import_state({**state, "broken": 1})
    with pytest.raises(ValueError, match="damage"):
        clone.import_state({**state, "damage": 1.5})
