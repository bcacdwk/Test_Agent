"""Gate-oxide / MIM dielectric with leakage and breakdown (``dielectric``, blueprint 4.2).

Pre-breakdown leakage is Fowler-Nordheim tunnelling ``J = A·E²·exp(-B/E)`` (Lenzlinger & Snow, J. Appl. Phys. 40,
278, 1969) plus an ohmic part and stress-induced leakage (SILC) growing with the accumulated damage. Breakdown is
instantaneous at the breakdown voltage ``BDV = E_bd·t_ox`` and time-dependent below it (TDDB): the damage
``D = ∫dt/t_bd(V)`` (Miner's rule) reaches 1 at the Weibull-distributed life ``t_bd(V) = η(V)·W^(1/β)``, with the
E-model scale ``η(V) = η_ref·exp(-γ·(|V| - V_ref))`` (McPherson & Mogul, J. Appl. Phys. 84, 1513, 1998) and ``W``
a unit-exponential draw seeded by ``(seed, site)``, so a constant-voltage stress breaks exactly at ``t_bd(V)``.
After breakdown an ohmic path ``r_bd_ohm`` dominates. ``next_site()`` moves to a fresh device of the same
population (a new Weibull draw), the hook for multi-site TDDB statistics.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping

from b1500_test_agent.models.sim import DielectricParams
from b1500_test_agent.transport.sim.devices.base import (
    EPS0_F_CM,
    UM2_TO_CM2,
    DeviceState,
    Voltages,
    check_frequency,
    check_state_keys,
    parallel_capacitance,
    state_flag,
    state_number,
    two_terminal,
)


class DielectricDevice:
    """``dielectric``: the test structure of ``DielectricParams`` between ``top`` and ``bottom``.

    State (persisted): damage ``damage`` (0..1), ``broken``, Weibull ``site`` and the last applied voltage ``v``
    (for the displacement current through the geometric capacitance). ``commit`` and a trial evaluation break the
    device at or above BDV; only ``advance`` accumulates TDDB damage. Truth: ``bdv``, ``t_bd(v)``, ``eta(v)``,
    ``weibull_w``, ``truth()``.
    """

    terminals = ("top", "bottom")

    def __init__(self, name: str, params: DielectricParams) -> None:
        self.name = name
        self.model = "dielectric"
        self.params = params
        self.area = params.area_um2 * UM2_TO_CM2
        self.tox_cm = params.tox_nm * 1e-7
        self.c_geo = EPS0_F_CM * params.eps_r * self.area / self.tox_cm
        self.damage = 0.0
        self.broken = False
        self.v = 0.0
        self.site = params.site
        self.weibull_w = self._draw(self.site)

    def _draw(self, site: int) -> float:
        u = random.Random(f"dielectric:{self.params.seed}:{site}").random()
        return max(-math.log1p(-u), 1e-300)

    # -- physics -------------------------------------------------------------------------------------------------------

    @property
    def bdv(self) -> float:
        """Instantaneous breakdown voltage magnitude (V): ``ebd_mv_cm·tox``."""
        return self.params.ebd_mv_cm * 1e6 * self.tox_cm

    def eta(self, v: float) -> float:
        """Weibull scale (characteristic life, s) at stress ``|v|``."""
        p = self.params
        return p.tbd_eta_s * math.exp(-p.tbd_gamma_per_v * (abs(v) - p.tbd_v_ref))

    def _rate(self, v: float) -> float:
        """Damage rate ``1/t_bd(v)`` (1/s) of the current site, overflow-safe."""
        p = self.params
        log_rate = p.tbd_gamma_per_v * (abs(v) - p.tbd_v_ref) - math.log(p.tbd_eta_s) \
            - math.log(self.weibull_w) / p.weibull_beta
        return math.exp(min(log_rate, 700.0))

    def t_bd(self, v: float) -> float:
        """Time to breakdown (s) under constant ``|v|`` from the current damage (0 if broken or ``|v| ≥ BDV``)."""
        if self.broken or abs(v) >= self.bdv:
            return 0.0
        return (1.0 - self.damage) / self._rate(v)

    def fn_current(self, v: float) -> float:
        """Fowler-Nordheim current (A) at ``v`` (sign of ``v``)."""
        p = self.params
        e = abs(v) / self.tox_cm
        if e == 0.0 or p.fn_a_a_v2 == 0.0:
            return 0.0
        return math.copysign(p.fn_a_a_v2 * e * e * math.exp(-p.fn_b_v_cm / e) * self.area, v)

    def conduction(self, v: float, *, broken: bool | None = None, damage: float | None = None) -> float:
        """DC current (A) at ``v`` for the current (or the given) breakdown state and damage."""
        p = self.params
        d = self.damage if damage is None else damage
        current = self.fn_current(v) + (p.leak_s + p.silc_s * d) * v
        if self.broken if broken is None else broken:
            current += v / p.r_bd_ohm
        return current

    # -- device protocol -----------------------------------------------------------------------------------------------

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "top", "bottom")
        if dv is None:
            return {"top": 0.0, "bottom": 0.0}
        current = self.conduction(dv, broken=self.broken or abs(dv) >= self.bdv)
        return {"top": current, "bottom": -current}

    def commit(self, v: Voltages) -> None:
        dv = two_terminal(v, "top", "bottom")
        if dv is None:
            return
        if abs(dv) >= self.bdv:
            self.broken, self.damage = True, 1.0
        self.v = dv

    def advance(self, dt: float, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "top", "bottom")
        if dv is None:
            return {"top": 0.0, "bottom": 0.0}
        if not self.broken:
            if abs(dv) >= self.bdv:
                self.broken, self.damage = True, 1.0
            elif dt > 0.0:
                self.damage += dt * self._rate(dv)
                if self.damage >= 1.0:
                    self.broken, self.damage = True, 1.0
        current = self.conduction(dv) + (self.c_geo * (dv - self.v) / dt if dt > 0.0 else 0.0)
        self.v = dv
        return {"top": current, "bottom": -current}

    def admittance(self, v: float, f: float) -> complex:
        """Small-signal admittance: geometric capacitance in parallel with the differential conductance."""
        omega = 2.0 * math.pi * check_frequency(f)
        h = max(1e-6, 1e-6 * abs(v))
        g = (self.conduction(v + h) - self.conduction(v - h)) / (2.0 * h)
        return complex(g, omega * self.c_geo)

    def capacitance(self, v: float, f: float) -> float:
        return parallel_capacitance(self.admittance(v, f), f)

    def break_down(self) -> None:
        """Break down now, whatever the accumulated damage (the ``breakdown_at`` fault of the simulator)."""
        self.broken, self.damage = True, 1.0

    def next_site(self) -> None:
        """Move to a fresh device of the same population: new Weibull draw, no damage, not broken."""
        self.site += 1
        self.weibull_w = self._draw(self.site)
        self.damage, self.broken, self.v = 0.0, False, 0.0

    def export_state(self) -> DeviceState:
        return {"damage": self.damage, "broken": self.broken, "site": self.site, "v": self.v}

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.damage, self.broken, self.v = 0.0, False, 0.0
            self.site = self.params.site
            self.weibull_w = self._draw(self.site)
            return
        owner = f"dielectric {self.name}"
        check_state_keys(data, {"damage", "broken", "site", "v"}, owner)
        site = data["site"]
        if isinstance(site, bool) or not isinstance(site, int) or site < 0:
            raise ValueError(f"{owner}: state 'site' = {site!r} is not a non-negative integer")
        self.damage = state_number(data, "damage", owner, lo=0.0, hi=1.0)
        self.broken = state_flag(data, "broken", owner)
        self.v = state_number(data, "v", owner)
        self.site = site
        self.weibull_w = self._draw(site)

    # -- truth ---------------------------------------------------------------------------------------------------------

    def truth(self) -> dict[str, float]:
        """Breakdown truth of the current site: ``bdv_v``, Weibull ``beta`` and draw ``w``, ``c_geo_f``."""
        return {"bdv_v": self.bdv, "weibull_beta": self.params.weibull_beta, "weibull_w": self.weibull_w,
                "c_geo_f": self.c_geo, "site": float(self.site)}
