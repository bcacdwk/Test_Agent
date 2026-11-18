"""Basic device models (blueprint 4.2): ``open`` (probe not landed), ``resistor``/``short`` and ``diode``."""

from __future__ import annotations

import math

from b1500_test_agent.models.sim import DiodeParams, ResistorParams, ShortParams
from b1500_test_agent.transport.sim.devices.base import BOLTZMANN_OVER_Q, Voltages, exp_lin


class OpenDevice:
    """``open``: no connection at all (probe not landed); only noise is measured."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = "open"
        self.params: object = None

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        return {terminal: 0.0 for terminal in v}


class ResistorDevice:
    """``resistor``/``short``: ``I_a = (V_a - V_b) / R``, ``I_b = -I_a``; zero if either terminal floats."""

    def __init__(self, name: str, model: str, params: ResistorParams | ShortParams) -> None:
        self.name = name
        self.model = model
        self.params = params
        self.r_ohm = params.r_ohm

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        va, vb = v.get("a"), v.get("b")
        if va is None or vb is None:
            return {"a": 0.0, "b": 0.0}
        current = (va - vb) / self.r_ohm
        return {"a": current, "b": -current}


class DiodeDevice:
    """``diode``: Shockley junction, series resistance, shunt leakage, soft breakdown (``DiodeParams``).

    ``current(v)`` is the anode current at bias ``v`` (anode minus cathode). With ``rs_ohm`` > 0 the junction voltage
    ``Vj`` solves ``Vj + rs·I(Vj) = v``; the left side is strictly increasing, so a safeguarded Newton iteration on a
    bracket always converges. A floating anode or cathode carries no current.
    """

    terminals = ("anode", "cathode")

    def __init__(self, name: str, params: DiodeParams) -> None:
        self.name = name
        self.model = "diode"
        self.params = params
        self.ut = BOLTZMANN_OVER_Q * params.temperature_k
        self.n_ut = params.n * self.ut

    def junction_current(self, vj: float) -> tuple[float, float]:
        """Current (A) through the junction at junction voltage ``vj`` and its derivative dI/dVj (S, > 0)."""
        p = self.params
        e, de = exp_lin(vj / self.n_ut)
        current = p.is_a * (e - 1.0) + p.leak_s * vj
        slope = p.is_a * de / self.n_ut + p.leak_s
        if p.bv_v is not None:
            b, db = exp_lin(-(vj + p.bv_v) / p.bv_width_v)
            current -= p.ibv_a * (b - math.exp(-p.bv_v / p.bv_width_v))
            slope += p.ibv_a * db / p.bv_width_v
        return current, slope

    def current(self, v: float) -> float:
        """Anode current (A) at bias ``v`` (V, anode minus cathode), series resistance included."""
        rs = self.params.rs_ohm
        if rs == 0.0:
            return self.junction_current(v)[0]

        def residual(vj: float) -> tuple[float, float]:
            current, slope = self.junction_current(vj)
            return vj + rs * current - v, 1.0 + rs * slope

        lo, hi = min(0.0, v), max(0.0, v)
        step = 1.0
        while residual(lo)[0] > 0:
            lo -= step
            step *= 2.0
        step = 1.0
        while residual(hi)[0] < 0:
            hi += step
            step *= 2.0
        if v > 0:  # upper bound of Vj: the whole bias over Rs gives I = v/rs
            x = min(hi, self.n_ut * math.log1p(v / (rs * self.params.is_a)))
        else:
            x = lo
        x = min(max(x, lo), hi)
        for _ in range(200):
            g, dg = residual(x)
            if g == 0.0:
                break
            if g > 0:
                hi = x
            else:
                lo = x
            nxt = x - g / dg
            if not lo < nxt < hi:
                nxt = 0.5 * (lo + hi)
            done = abs(nxt - x) <= 1e-15 * max(1.0, abs(x)) or hi - lo <= 1e-15 * max(1.0, abs(x))
            x = nxt
            if done:
                break
        return self.junction_current(x)[0]

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        va, vc = v.get("anode"), v.get("cathode")
        if va is None or vc is None:
            return {"anode": 0.0, "cathode": 0.0}
        current = self.current(va - vc)
        return {"anode": current, "cathode": -current}


