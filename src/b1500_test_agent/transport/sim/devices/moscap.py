"""MOS capacitor (``moscap``) and the 1-D MOS electrostatics shared with the ``mosfet`` gate capacitances
(blueprint 4.2).

Physics (Nicollian & Brews, *MOS Physics and Technology*, Wiley 1982, ch. 2, 5, 8; Sze & Ng, *Physics of Semiconductor
Devices*, 3rd ed., ch. 4), in the p-substrate frame (an n substrate is mirrored: voltages, charges and potentials
change sign, capacitances do not):

- semiconductor charge from the exact 1-D Poisson solution, ``Qs(ψ) = -sgn(ψ)·√(2qNεsU_T)·F(ψ)`` with
  ``F² = (e^-x + x - 1) + (ni/N)²(e^x - x - 1)``, ``x = ψ/U_T``; the majority (depletion/accumulation) part keeps the
  first bracket, the minority (inversion) charge is the difference;
- gate equation ``Vg = Vfb0 + ψ - (Qs + Qit + Qbt)/Cox`` with ``Vfb0 = φms - Qf/Cox``; interface traps with a U-shaped
  ``Dit(E)`` around midgap (neutral level at midgap) give the DC stretch-out ``Qit`` and the small-signal continuum
  admittance ``Gp/ω = qDit·ln(1 + ω²τ²)/(2ωτ)``, ``Cit = qDit·atan(ωτ)/(ωτ)`` with ``τ = 1/(σ·v_th·(ps + w·ns))``;
  the traps exist only inside the band gap (``|E - Ei| <= Eg/2``, silicon 1.12 eV: beyond a band edge, e.g. in deep
  depletion, ``Qit`` saturates and ``Dit`` is 0), and their exchange with the minority band responds only as far as
  the minority carriers follow the signal (``w``: the inversion-charge weight below; 0 while the minority charge is
  below equilibrium), so fast near-edge traps add no capacitance to an HF curve in inversion (Nicollian & Brews
  ch. 5: the minority-carrier capture path is in series with the inversion layer's generation response);
- the inversion charge follows the AC signal with weight ``1/(1 + (f/f_inv)²)`` (LF ↔ HF C-V) and forms with time
  constant ``tau_inv_s`` (a stored minority charge below equilibrium = deep depletion; C-t recovery);
- border traps (C-V hysteresis) are a play operator on the gate bias; series ``rs_ohm`` and oxide leakage
  ``leak_s`` complete the admittance ``Y = 1/(Rs + 1/(A·Y_mos))``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

from b1500_test_agent.models.sim import MoscapParams
from b1500_test_agent.transport.sim.devices.base import (
    BOLTZMANN_OVER_Q,
    EPS0_F_CM,
    Q_E,
    UM2_TO_CM2,
    DeviceState,
    Voltages,
    check_frequency,
    check_state_keys,
    parallel_capacitance,
    state_number,
    two_terminal,
)
from b1500_test_agent.transport.sim.devices.kinetics import play, sigmoid

_EXP_CAP = 600.0
"""Exponent above which ``_exp`` continues linearly (monotonic, finite; only deep-depletion brackets get there)."""

GAP_HALF_EV = 0.56
"""Half the silicon band gap (1.12 eV at 300 K, Sze & Ng table 1.1): interface traps lie within ``|E - Ei| <= 0.56``
eV of midgap (the model's neutral level)."""

CONTINUUM_PEAK_WT = 1.9803
"""``ωτ`` at the maximum of the continuum ``Gp/ω = qDit·ln(1 + ω²τ²)/(2ωτ)`` (root of ``2x² = (1 + x²) ln(1 + x²)``;
the peak value is ``0.4024·qDit``; Nicollian & Brews eq. 5.36)."""


def _exp(x: float) -> float:
    if x <= _EXP_CAP:
        return math.exp(x)
    return math.exp(_EXP_CAP) * (1.0 + x - _EXP_CAP)


class MosElectrostatics:
    """1-D electrostatics of a uniformly doped substrate (acceptors ``nsub``) under an oxide of ``cox`` (F/cm²).

    Charges in C/cm², potentials in V, capacitances in F/cm². ``dit_*`` describe the interface-trap density
    ``Dit(e) = dit_mid + dit_edge·(cosh(e/dit_width) - 1)`` (cm⁻²eV⁻¹, ``e`` = energy from midgap in eV).
    """

    def __init__(self, *, cox: float, nsub: float, eps_s_rel: float, ni: float, temperature_k: float,
                 dit_mid: float = 0.0, dit_edge: float = 0.0, dit_width: float = 0.1, sigma_cm2: float = 1.0e-16,
                 v_thermal: float = 1.0e7) -> None:
        self.cox = cox
        self.na = nsub
        self.ni = ni
        self.eps_s = EPS0_F_CM * eps_s_rel
        self.ut = BOLTZMANN_OVER_Q * temperature_k
        self.ratio = (ni / nsub) ** 2
        self.phi_b = self.ut * math.log(nsub / ni)
        self.qn = math.sqrt(2.0 * Q_E * nsub * self.eps_s * self.ut)
        self.c0 = math.sqrt(Q_E * nsub * self.eps_s / self.ut)
        self.dit_mid, self.dit_edge, self.dit_width = dit_mid, dit_edge, dit_width
        self.sigma, self.v_thermal = sigma_cm2, v_thermal

    @property
    def debye_length_cm(self) -> float:
        """Extrinsic Debye length ``εs/C0`` (cm)."""
        return self.eps_s / self.c0

    @property
    def vth_offset(self) -> float:
        """``2φB + √(2qNεs·2φB)/Cox``: threshold minus flatband voltage (strong inversion onset)."""
        return 2.0 * self.phi_b + math.sqrt(2.0 * Q_E * self.na * self.eps_s * 2.0 * self.phi_b) / self.cox

    # -- semiconductor charge ------------------------------------------------------------------------------------------

    def _terms(self, psi: float) -> tuple[float, float, float, float, float]:
        """``x``, majority bracket ``A``, minority bracket ``B`` and their derivatives d/dx."""
        x = psi / self.ut
        a = math.expm1(-x) + x if x > -_EXP_CAP else _exp(-x) + x - 1.0
        da = -math.expm1(-x) if x > -_EXP_CAP else 1.0 - _exp(-x)
        ex = _exp(x)
        b = self.ratio * (ex - x - 1.0) if x > 1e-3 else self.ratio * (math.expm1(x) - x)
        db = self.ratio * (ex - 1.0)
        return x, max(a, 0.0), max(b, 0.0), da, db

    def q_bulk(self, psi: float) -> float:
        """Majority-carrier (accumulation or depletion) charge (C/cm², signed: negative in depletion)."""
        _, a, _, _, _ = self._terms(psi)
        return -math.copysign(1.0, psi) * self.qn * math.sqrt(a) if psi != 0.0 else 0.0

    def q_inv_eq(self, psi: float) -> float:
        """Equilibrium minority (inversion) charge magnitude (C/cm², ≥ 0); 0 for ``ψ ≤ 0``."""
        if psi <= 0.0:
            return 0.0
        _, a, b, _, _ = self._terms(psi)
        return self.qn * b / (math.sqrt(a + b) + math.sqrt(a)) if b > 0.0 else 0.0

    def c_bulk(self, psi: float) -> float:
        """``-dQ_bulk/dψ`` (F/cm²): the majority-carrier (depletion/accumulation) capacitance."""
        x, a, _, da, _ = self._terms(psi)
        if abs(x) < 1e-6 or a <= 0.0:
            return self.c0
        return self.qn * abs(da) / (2.0 * self.ut * math.sqrt(a))

    def c_inv_eq(self, psi: float) -> float:
        """``dQ_inv,eq/dψ`` (F/cm²): the equilibrium inversion capacitance (0 for ``ψ ≤ 0``)."""
        x, a, b, da, db = self._terms(psi)
        if x < 1e-6 or b <= 0.0:
            return 0.0
        sa, sab = math.sqrt(a), math.sqrt(a + b)
        return self.qn / (2.0 * self.ut) * (db / sab - da * b / (sa * sab * (sa + sab)))

    # -- interface traps -----------------------------------------------------------------------------------------------

    def dit(self, e: float) -> float:
        """Interface-trap density (cm⁻²eV⁻¹) at energy ``e`` (eV) from midgap; 0 outside the band gap
        (``GAP_HALF_EV``)."""
        if abs(e) > GAP_HALF_EV:
            return 0.0
        return self.dit_mid + self.dit_edge * (math.cosh(e / self.dit_width) - 1.0)

    def surface_energy(self, psi: float) -> float:
        """Fermi level relative to midgap at the surface, ``ψ - φB`` (eV)."""
        return psi - self.phi_b

    def q_it(self, psi: float) -> float:
        """Interface-trap charge (C/cm²): ``-q·∫₀^e Dit``, ``e = ψ - φB`` (traps filled up to the Fermi level),
        constant beyond a band edge (no traps outside the gap)."""
        if self.dit_mid == 0.0 and self.dit_edge == 0.0:
            return 0.0
        e, w = min(max(self.surface_energy(psi), -GAP_HALF_EV), GAP_HALF_EV), self.dit_width
        return -Q_E * (self.dit_mid * e + self.dit_edge * (w * math.sinh(e / w) - e))

    def c_it_lf(self, psi: float) -> float:
        """Low-frequency interface-trap capacitance ``q·Dit(e)`` (F/cm²)."""
        return Q_E * self.dit(self.surface_energy(psi))

    def tau_it(self, psi: float, minority: float = 1.0) -> float:
        """Interface-trap time constant ``1/(σ·v_th·(ps + minority·ns))`` at the surface (s); ``minority`` (0..1) is
        the share of the minority-band exchange that follows the signal (1: quasi-static, DC)."""
        x = psi / self.ut
        ps = self.na * _exp(-x)
        ns = self.ni * self.ni / self.na * _exp(x)
        return 1.0 / (self.sigma * self.v_thermal * (ps + minority * ns))

    def y_it(self, psi: float, omega: float, minority: float = 1.0) -> complex:
        """Continuum interface-trap admittance ``Gp + jω·Cit`` (S/cm²; Nicollian & Brews eq. 5.36) with the time
        constant ``tau_it(psi, minority)``."""
        c_lf = self.c_it_lf(psi)
        if c_lf == 0.0:
            return 0j
        tau = self.tau_it(psi, minority)
        wt = omega * tau
        return complex(c_lf * math.log1p(wt * wt) / (2.0 * tau), c_lf * math.atan(wt) / tau)

    # -- gate equation -------------------------------------------------------------------------------------------------

    def minority(self, psi: float, q_inv_cap: float | None) -> tuple[float, bool]:
        """Inversion charge magnitude used at ``ψ`` and whether it is the equilibrium value (``q_inv_cap``: the
        stored minority charge, ``None`` = equilibrium)."""
        q_eq = self.q_inv_eq(psi)
        if q_inv_cap is None or q_eq <= q_inv_cap:
            return q_eq, True
        return q_inv_cap, False

    def solve(self, drive: float, q_extra: float = 0.0, q_inv_cap: float | None = None) -> float:
        """Surface potential ``ψ`` (V) for ``drive = Vg - Vfb0`` (V), extra oxide charge ``q_extra`` (C/cm², e.g. border
        traps) and stored minority charge ``q_inv_cap`` (``None``: equilibrium). The residual is strictly increasing in
        ``ψ``, so a bracketed Newton iteration converges to the unique root."""

        def residual(psi: float) -> tuple[float, float]:
            q_min, eq = self.minority(psi, q_inv_cap)
            qs = self.q_bulk(psi) - q_min
            value = psi - (qs + self.q_it(psi) + q_extra) / self.cox - drive
            slope = 1.0 + (self.c_bulk(psi) + (self.c_inv_eq(psi) if eq else 0.0) + self.c_it_lf(psi)) / self.cox
            return value, slope

        lo, hi = -0.5, 1.0
        while residual(lo)[0] > 0.0:
            lo *= 2.0
        while residual(hi)[0] < 0.0:
            hi *= 2.0
        psi = 0.0 if lo < 0.0 < hi else 0.5 * (lo + hi)
        for _ in range(200):
            g, dg = residual(psi)
            if g == 0.0:
                return psi
            if g > 0.0:
                hi = psi
            else:
                lo = psi
            nxt = psi - g / dg if math.isfinite(dg) and dg > 0.0 else 0.5 * (lo + hi)
            if not lo < nxt < hi:
                nxt = 0.5 * (lo + hi)
            if abs(nxt - psi) <= 1e-13 or hi - lo <= 1e-13:
                return nxt
            psi = nxt
        return psi

    def semiconductor_admittance(self, psi: float, omega: float, *, minority_eq: bool, w_inv: float) -> complex:
        """Small-signal admittance (S/cm²) of the semiconductor at ``ψ``: majority response, the AC-following part
        ``w_inv`` of the inversion response (only while the minority charge is at equilibrium) and interface traps
        (their minority-band exchange weighted the same way)."""
        follow = w_inv if minority_eq else 0.0
        c_s = self.c_bulk(psi) + follow * self.c_inv_eq(psi)
        return complex(0.0, omega * c_s) + self.y_it(psi, omega, follow)


class MoscapDevice:
    """``moscap``: the MOS capacitor of ``MoscapParams`` between ``gate`` and ``bulk`` (blueprint 4.2).

    State (persisted): border-trap occupancy ``s_bt`` (0..1, ``Vfb`` shift ``s_bt·hysteresis_v``), stored minority
    charge ``q_inv`` (C/cm²), gate charge ``q_gate`` (C) and voltage ``v`` at the last application. ``commit`` sets the
    equilibrium minority charge; ``advance`` lets it relax with ``tau_inv_s`` and returns the displacement current.
    The DC current is the oxide leakage only. Truth: ``cox``, ``vfb()``, ``nsub``, ``dit_at``, ``hysteresis_truth``,
    ``truth()``.
    """

    terminals = ("gate", "bulk")

    def __init__(self, name: str, params: MoscapParams) -> None:
        self.name = name
        self.model = "moscap"
        self.params = params
        p = params
        self.sign = 1.0 if p.substrate == "p" else -1.0
        self.area = p.area_um2 * UM2_TO_CM2
        self.cox_area = EPS0_F_CM * p.eps_ox / (p.tox_nm * 1e-7)
        self.es = MosElectrostatics(cox=self.cox_area, nsub=p.nsub_cm3, eps_s_rel=p.eps_s, ni=p.ni_cm3,
                                    temperature_k=p.temperature_k, dit_mid=p.dit_cm2_ev, dit_edge=p.dit_edge_cm2_ev,
                                    dit_width=p.dit_width_ev, sigma_cm2=p.dit_sigma_cm2, v_thermal=p.v_thermal_cm_s)
        self.phi_ms_p = self.sign * p.phi_ms_v
        self.vfb0_p = self.sign * (p.phi_ms_v - Q_E * p.qf_cm2 / self.cox_area)
        self.reset()

    def reset(self) -> None:
        """Initial state: border traps empty, equilibrium at 0 V."""
        self.s_bt = 0.0
        self.v = 0.0
        self.q_inv = self.es.q_inv_eq(self.surface_potential(0.0))
        self.q_gate = self.gate_charge(0.0)

    # -- electrostatics ------------------------------------------------------------------------------------------------

    def _q_bt(self, s_bt: float) -> float:
        return -self.cox_area * self.params.hysteresis_v * s_bt

    def _band(self, v: float) -> tuple[float, float]:
        """Border-trap play band ``[lo, hi]`` at gate bias ``v`` (charging beyond ``+vc``, emptying beyond ``-vc``)."""
        p = self.params
        vp = self.sign * v
        return (sigmoid((vp - p.hysteresis_vc_v) / p.hysteresis_width_v),
                sigmoid((vp + p.hysteresis_vc_v) / p.hysteresis_width_v))

    def border_traps_after(self, v: float, s_bt: float | None = None) -> float:
        """Border-trap occupancy after applying ``v`` to state ``s_bt`` (default: the current state)."""
        return play(self.s_bt if s_bt is None else s_bt, *self._band(v))

    def surface_potential(self, v: float, *, q_inv: float | None = None, s_bt: float | None = None) -> float:
        """Surface potential (V, p-substrate frame) at gate bias ``v`` with stored minority charge ``q_inv``
        (``None``: equilibrium) and border-trap state ``s_bt`` (default: current)."""
        s = self.s_bt if s_bt is None else s_bt
        return self.es.solve(self.sign * v - self.vfb0_p, self._q_bt(s), q_inv)

    def gate_charge(self, v: float, *, q_inv: float | None = None, s_bt: float | None = None) -> float:
        """Gate charge (C) at bias ``v`` (``q_inv`` ``None``: quasi-static equilibrium, the QSCV charge)."""
        psi = self.surface_potential(v, q_inv=q_inv, s_bt=s_bt)
        return self.sign * self.cox_area * (self.sign * v - self.phi_ms_p - psi) * self.area

    def charge(self, v: float) -> float:
        """Quasi-static (equilibrium) gate charge (C) at ``v`` for the current border-trap state; ``dQ/dV`` is the LF
        (QSCV) capacitance."""
        return self.gate_charge(v)

    # -- small signal --------------------------------------------------------------------------------------------------

    def _admittance(self, v: float, f: float, q_inv: float | None, s_bt: float) -> complex:
        p = self.params
        omega = 2.0 * math.pi * check_frequency(f)
        psi = self.surface_potential(v, q_inv=q_inv, s_bt=s_bt)
        _, minority_eq = self.es.minority(psi, q_inv)
        w_inv = 1.0 / (1.0 + (f / p.f_inv_hz) ** 2)
        y_s = self.es.semiconductor_admittance(psi, omega, minority_eq=minority_eq, w_inv=w_inv)
        y_ox = complex(p.leak_s / self.area, omega * self.cox_area)
        y_mos = self.area / (1.0 / y_ox + 1.0 / y_s)
        return 1.0 / (p.rs_ohm + 1.0 / y_mos)

    def admittance(self, v: float, f: float) -> complex:
        """Small-signal admittance (S) gate-bulk at bias ``v`` and frequency ``f`` for the present state (stored
        minority charge and border traps)."""
        return self._admittance(v, f, self.q_inv, self.s_bt)

    def capacitance(self, v: float, f: float) -> float:
        return parallel_capacitance(self.admittance(v, f), f)

    def equilibrium_capacitance(self, v: float, f: float) -> float:
        """Truth: parallel capacitance after a quasi-static application of ``v`` (border traps as now)."""
        return parallel_capacitance(self._admittance(v, f, None, self.s_bt), f)

    def deep_depletion_capacitance(self, v: float, f: float) -> float:
        """Truth: parallel capacitance at ``v`` with no inversion charge formed (a step from accumulation, t = 0)."""
        return parallel_capacitance(self._admittance(v, f, 0.0, self.s_bt), f)

    def transient_capacitance(self, v: float, f: float, t: float, q_start: float = 0.0) -> float:
        """Truth: parallel capacitance ``t`` seconds after a step to ``v`` from a stored minority charge ``q_start``
        (C/cm²; 0 after accumulation): the inversion charge relaxes to equilibrium with ``tau_inv_s`` (C-t recovery,
        a pulsed C-V point; border traps as now)."""
        q_eq = self.es.q_inv_eq(self.surface_potential(v))
        q_inv = q_eq if q_start >= q_eq else q_eq - (q_eq - q_start) * math.exp(-t / self.params.tau_inv_s)
        return parallel_capacitance(self._admittance(v, f, q_inv, self.s_bt), f)

    # -- device protocol -----------------------------------------------------------------------------------------------

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "gate", "bulk")
        current = 0.0 if dv is None else self.params.leak_s * dv
        return {"gate": current, "bulk": -current}

    def commit(self, v: Voltages) -> None:
        dv = two_terminal(v, "gate", "bulk")
        if dv is None:
            return
        self.s_bt = self.border_traps_after(dv)
        self.q_inv = self.es.q_inv_eq(self.surface_potential(dv))
        self.q_gate = self.gate_charge(dv, q_inv=self.q_inv)
        self.v = dv

    def advance(self, dt: float, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "gate", "bulk")
        if dv is None:
            return {"gate": 0.0, "bulk": 0.0}
        self.s_bt = self.border_traps_after(dv)
        q_eq = self.es.q_inv_eq(self.surface_potential(dv))
        if self.q_inv >= q_eq:
            self.q_inv = q_eq  # excess minority carriers recombine or drain into the substrate quickly
        elif dt > 0.0:
            self.q_inv = q_eq - (q_eq - self.q_inv) * math.exp(-dt / self.params.tau_inv_s)
        q_new = self.gate_charge(dv, q_inv=self.q_inv)
        current = self.params.leak_s * dv + ((q_new - self.q_gate) / dt if dt > 0.0 else 0.0)
        self.q_gate, self.v = q_new, dv
        return {"gate": current, "bulk": -current}

    def export_state(self) -> DeviceState:
        return {"s_bt": self.s_bt, "q_inv": self.q_inv, "q_gate": self.q_gate, "v": self.v}

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.reset()
            return
        owner = f"moscap {self.name}"
        check_state_keys(data, {"s_bt", "q_inv", "q_gate", "v"}, owner)
        self.s_bt = state_number(data, "s_bt", owner, lo=0.0, hi=1.0)
        self.q_inv = state_number(data, "q_inv", owner, lo=0.0)
        self.q_gate = state_number(data, "q_gate", owner)
        self.v = state_number(data, "v", owner)

    # -- truth ---------------------------------------------------------------------------------------------------------

    @property
    def cox(self) -> float:
        """Oxide capacitance (F)."""
        return self.cox_area * self.area

    @property
    def flatband_capacitance(self) -> float:
        """HF capacitance at flatband (F): ``Cox`` in series with ``εs/L_D``."""
        return self.area * self.cox_area * self.es.c0 / (self.cox_area + self.es.c0)

    def vfb(self, s_bt: float | None = None) -> float:
        """Flatband voltage (V): the gate bias with ``ψ = 0``, including fixed charge, the interface-trap charge at
        flatband and the border-trap state ``s_bt`` (default: current)."""
        s = self.s_bt if s_bt is None else s_bt
        vp = self.vfb0_p - (self.es.q_it(0.0) + self._q_bt(s)) / self.cox_area
        return self.sign * vp

    def dit_at(self, v: float) -> float:
        """Interface-trap density (cm⁻²eV⁻¹) at the surface Fermi level for the equilibrium gate bias ``v``."""
        return self.es.dit(self.es.surface_energy(self.surface_potential(v)))

    def interface_trap_truth(self, v: float, f: float | None = None) -> dict[str, float]:
        """Truth of a conductance (C-f) measurement at the equilibrium gate bias ``v`` (current border-trap state):
        surface potential ``psi_v`` and trap energy ``e_minus_ei_ev`` (``ψ - φB``; both in the p-substrate frame),
        ``dit_cm2_ev`` there and the trap time constant ``tau_s`` (minority exchange weighted as at frequency ``f``;
        quasi-static without ``f``), with the frequency of the continuum ``Gp/ω`` peak, ``f_peak_hz = 1.98/(2π τ)``."""
        psi = self.surface_potential(v)
        minority = 1.0 if f is None else 1.0 / (1.0 + (f / self.params.f_inv_hz) ** 2)
        tau = self.es.tau_it(psi, minority)
        return {"psi_v": psi, "e_minus_ei_ev": self.es.surface_energy(psi),
                "dit_cm2_ev": self.es.dit(self.es.surface_energy(psi)), "tau_s": tau,
                "f_peak_hz": CONTINUUM_PEAK_WT / (2.0 * math.pi * tau)}

    def hysteresis_truth(self, v_start: float, v_stop: float) -> dict[str, float]:
        """Flatband voltages of a quasi-static double sweep ``v_start → v_stop → v_start`` from the current state,
        without changing the device: ``vfb_fwd``, ``vfb_rev`` and ``hysteresis = vfb_rev - vfb_fwd``."""
        s0 = self.border_traps_after(v_start)
        ascending = v_stop >= v_start

        def forward(v: float) -> float:
            lo, hi = self._band(v)
            return max(s0, lo) if (ascending == (self.sign > 0)) else min(s0, hi)

        s_turn = self.border_traps_after(v_stop, forward(v_stop))

        def reverse(v: float) -> float:
            lo, hi = self._band(v)
            return min(s_turn, hi) if (ascending == (self.sign > 0)) else max(s_turn, lo)

        vfb_fwd = self._flatband_crossing(forward, v_start, v_stop)
        vfb_rev = self._flatband_crossing(reverse, v_start, v_stop)
        return {"vfb_fwd": vfb_fwd, "vfb_rev": vfb_rev, "hysteresis": vfb_rev - vfb_fwd}

    def _flatband_crossing(self, s_of_v: Callable[[float], float], v_a: float, v_b: float) -> float:
        """Gate bias ``V`` with ``V = vfb(s(V))`` along a sweep branch (bisection)."""
        lo, hi = min(v_a, v_b) - 20.0, max(v_a, v_b) + 20.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if mid - self.vfb(s_of_v(mid)) > 0:
                hi = mid
            else:
                lo = mid
            if hi - lo < 1e-12:
                break
        return 0.5 * (lo + hi)

    def truth(self) -> dict[str, float]:
        """Values the §4.2 fidelity targets are checked against (current border-trap state)."""
        return {"cox_f": self.cox, "vfb_v": self.vfb(), "nsub_cm3": self.params.nsub_cm3, "phi_b_v": self.es.phi_b,
                "c_fb_f": self.flatband_capacitance, "dit_mid_cm2_ev": self.params.dit_cm2_ev,
                "hysteresis_v": self.params.hysteresis_v, "area_cm2": self.area}
