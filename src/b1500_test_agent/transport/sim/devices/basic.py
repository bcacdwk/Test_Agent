"""Basic device models (blueprint 4.2): ``open`` (probe not landed), ``resistor``/``short``, ``diode`` and the
``capacitor`` reference standard (v2)."""

from __future__ import annotations

import math
from collections.abc import Mapping

from b1500_test_agent.models.sim import CapacitorParams, DiodeParams, ResistorParams, ShortParams
from b1500_test_agent.transport.sim.devices.base import (
    BOLTZMANN_OVER_Q,
    DeviceState,
    Voltages,
    check_frequency,
    check_state_keys,
    exp_lin,
    parallel_capacitance,
    state_number,
    two_terminal,
)


class OpenDevice:
    """``open``: no connection at all (probe not landed); only noise is measured."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = "open"
        self.params: object = None

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        return {terminal: 0.0 for terminal in v}


class ResistorDevice:
    """``resistor``/``short``: ``I_a = (V_a - V_b) / R``, ``I_b = -I_a``; zero if either terminal floats.

    ``R`` is what the channels see: for a ``resistor`` its ``r_ohm`` plus the force-path ``lead_ohm`` of every
    terminal without a landed Sense line (``ResistorParams.seen_ohm``, four-wire sensing), for a ``short`` its
    ``r_ohm``."""

    def __init__(self, name: str, model: str, params: ResistorParams | ShortParams) -> None:
        self.name = name
        self.model = model
        self.params = params
        self.r_ohm = params.seen_ohm() if isinstance(params, ResistorParams) else params.r_ohm

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




class CapacitorDevice:
    """``capacitor``: ``c_f`` in parallel with ``g_s``, in series with ``esr_ohm`` (``CapacitorParams``).

    DC current ``(V_a - V_b)/(esr + 1/g_s)`` (zero without ``g_s``); ``advance`` adds the displacement current
    ``c_f·ΔV/dt`` of the voltage change since the last applied voltage (the persisted state ``v``; the ESR time
    constant is neglected). Small signal: ``Y = 1/(esr + 1/(g_s + jω·c_f))``, the truth a corrected CMU
    measurement must reproduce (blueprint 4.2 ``fixture`` + ``capacitor``). A floating terminal keeps the charge.
    """

    terminals = ("a", "b")

    def __init__(self, name: str, params: CapacitorParams) -> None:
        self.name = name
        self.model = "capacitor"
        self.params = params
        self.v = 0.0

    def _dc(self, dv: float) -> float:
        g = self.params.g_s
        return 0.0 if g == 0.0 else dv / (self.params.esr_ohm + 1.0 / g)

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "a", "b")
        current = 0.0 if dv is None else self._dc(dv)
        return {"a": current, "b": -current}

    def commit(self, v: Voltages) -> None:
        dv = two_terminal(v, "a", "b")
        if dv is not None:
            self.v = dv

    def advance(self, dt: float, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "a", "b")
        if dv is None:
            return {"a": 0.0, "b": 0.0}
        current = self._dc(dv) + (self.params.c_f * (dv - self.v) / dt if dt > 0.0 else 0.0)
        self.v = dv
        return {"a": current, "b": -current}

    def admittance(self, v: float, f: float) -> complex:
        omega = 2.0 * math.pi * check_frequency(f)
        y = complex(self.params.g_s, omega * self.params.c_f)
        return 1.0 / (self.params.esr_ohm + 1.0 / y)

    def capacitance(self, v: float, f: float) -> float:
        return parallel_capacitance(self.admittance(v, f), f)

    def export_state(self) -> DeviceState:
        return {"v": self.v}

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.v = 0.0
            return
        check_state_keys(data, {"v"}, f"capacitor {self.name}")
        self.v = state_number(data, "v", f"capacitor {self.name}")
