"""MOSFET device models (blueprint 4.2): ``mosfet_ekv`` (EKV long-channel interpolation) and ``mosfet_damaged``
(gate-drain short, open drain or leaky gate)."""

from __future__ import annotations

import math

from b1500_test_agent.models.sim import MosfetDamagedParams, MosfetEkvParams
from b1500_test_agent.transport.sim.devices.base import BOLTZMANN_OVER_Q, Voltages, softplus


class MosfetEkv:
    """``mosfet_ekv``: EKV long-channel interpolation with mobility degradation, CLM, Rs and gate leakage.

    For an n-channel device with voltages referred to the bulk (p-channel: all voltages and currents mirrored):

    - ``U_T = k·T/q``, pinch-off ``V_P = (V_G - V_T0)/n``, specific current ``I_spec = 2·n·β·U_T²``;
    - forward/reverse ``i_f,r = ln²(1 + exp((V_P - V_S,D)/(2·U_T)))`` — exponential in weak inversion, giving a
      subthreshold swing ``n·U_T·ln10``, and the square law ``(β/2n)(V_G - V_T0 - n·V_S)²`` in strong inversion;
    - ``I_DS = I_spec·(i_f - i_r)·(1 + λ|V_DS|)/(1 + θ·V_ov)`` with the smooth overdrive
      ``V_ov = 2nU_T·ln(1 + exp((V_G - V_T0 - n·V_S)/(2nU_T)))``, so gm peaks and then falls;
    - ``rs_ohm`` in series with source and drain (solved self-consistently by bisection);
    - gate leakage ``g/2·(V_G - V_S) + g/2·(V_G - V_D)``.

    A floating gate, drain or source switches the device off (all currents zero); a floating bulk follows the
    source. ``vth`` arguments override ``vth0`` (terminal polarity); the FeFET uses that for its polarization.
    """

    terminals = ("gate", "drain", "source", "bulk")

    def __init__(self, name: str, params: MosfetEkvParams) -> None:
        self.name = name
        self.model = "mosfet_ekv"
        self.params = params
        self.sign = 1.0 if params.polarity == "n" else -1.0
        self.ut = BOLTZMANN_OVER_Q * params.temperature_k

    @property
    def subthreshold_swing(self) -> float:
        """Ideal subthreshold swing n·U_T·ln10 (V/decade) — the truth the SS extraction should recover."""
        return self.params.slope_factor * self.ut * math.log(10.0)

    def _intrinsic(self, vg: float, vd: float, vs: float, vth: float | None = None) -> float:
        """Channel current D→S (A) of the n-type core, voltages already mirrored and referred to the bulk."""
        p = self.params
        n, ut = p.slope_factor, self.ut
        vt = (p.vth0 if vth is None else vth) * self.sign
        vp = (vg - vt) / n
        i_f = softplus((vp - vs) / (2 * ut)) ** 2
        i_r = softplus((vp - vd) / (2 * ut)) ** 2
        ispec = 2 * n * p.beta * ut * ut
        v_source = min(vs, vd)
        vov = 2 * n * ut * softplus((vg - vt - n * v_source) / (2 * n * ut))
        return ispec * (i_f - i_r) * (1 + p.lambda_ * abs(vd - vs)) / (1 + p.theta * vov)

    def channel_current(self, vg: float, vd: float, vs: float = 0.0, vb: float = 0.0, *,
                        vth: float | None = None) -> float:
        """Drain-to-source channel current (A, positive into the drain of a conducting n-channel device) at the
        given terminal voltages, including the series resistances (no gate leakage)."""
        s = self.sign
        g, d, src = s * (vg - vb), s * (vd - vb), s * (vs - vb)
        i0 = self._intrinsic(g, d, src, vth)
        rs = self.params.rs_ohm
        if rs == 0.0 or i0 == 0.0:
            return s * i0
        lo, hi = (0.0, i0) if i0 > 0 else (i0, 0.0)
        for _ in range(200):  # residual f(I) = I - I_int(V_S + I·Rs, V_D - I·Rs) is increasing in I
            mid = 0.5 * (lo + hi)
            if mid - self._intrinsic(g, d - mid * rs, src + mid * rs, vth) > 0:
                hi = mid
            else:
                lo = mid
            if hi - lo <= 1e-15 + 1e-12 * abs(mid):
                break
        return s * 0.5 * (lo + hi)

    def _currents(self, v: Voltages, *, vth: float | None = None, gate_leak_s: float | None = None
                  ) -> dict[str, float]:
        vg, vd, vs, vb = v.get("gate"), v.get("drain"), v.get("source"), v.get("bulk")
        zero = {"gate": 0.0, "drain": 0.0, "source": 0.0, "bulk": 0.0}
        if vg is None or vd is None or vs is None:
            return zero
        if vb is None:
            vb = vs
        ids = self.channel_current(vg, vd, vs, vb, vth=vth)
        half = 0.5 * (self.params.gate_leak_s if gate_leak_s is None else gate_leak_s)
        igs, igd = half * (vg - vs), half * (vg - vd)
        return {"gate": igs + igd, "drain": ids - igd, "source": -ids - igs, "bulk": 0.0}

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        return self._currents(v)


class DamagedMosfet(MosfetEkv):
    """``mosfet_damaged``: a ``mosfet_ekv`` with a gate-drain short, an open drain or a leaky gate
    (``MosfetDamagedParams``)."""

    def __init__(self, name: str, params: MosfetDamagedParams) -> None:
        super().__init__(name, params)
        self.model = "mosfet_damaged"
        self.params: MosfetDamagedParams = params

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        p = self.params
        if p.damage == "open_drain":
            vg, vs = v.get("gate"), v.get("source")
            if vg is None or vs is None:
                return {"gate": 0.0, "drain": 0.0, "source": 0.0, "bulk": 0.0}
            igs = 0.5 * p.gate_leak_s * (vg - vs)
            return {"gate": igs, "drain": 0.0, "source": -igs, "bulk": 0.0}
        leak = p.gate_leak_s + (p.leak_s if p.damage == "leaky_gate" else 0.0)
        out = self._currents(v, gate_leak_s=leak)
        vg, vd = v.get("gate"), v.get("drain")
        if p.damage == "gate_drain_short" and vg is not None and vd is not None:
            short = (vg - vd) / p.short_r_ohm
            out["gate"] += short
            out["drain"] -= short
        return out


