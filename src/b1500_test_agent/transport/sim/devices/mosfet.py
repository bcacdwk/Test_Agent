"""MOSFET device models (blueprint 4.2): ``mosfet_ekv`` (EKV long-channel interpolation), ``mosfet_damaged``
(gate-drain short, open drain or leaky gate) and the v2 ``mosfet`` (``mosfet_ekv`` + self-heating, BTI, HCI, IGZO
bias-stress drift and gate capacitances for split C-V)."""

from __future__ import annotations

import cmath
import math
from collections.abc import Collection, Mapping

from b1500_test_agent.models.sim import MosfetDamagedParams, MosfetEkvParams, MosfetParams
from b1500_test_agent.transport.sim.devices.base import (
    BOLTZMANN_OVER_Q,
    EPS0_F_CM,
    Q_E,
    DeviceState,
    PeriodicDrive,
    Voltages,
    check_frequency,
    check_state_keys,
    softplus,
    state_flag,
    state_number,
)
from b1500_test_agent.transport.sim.devices.kinetics import (
    log_decay,
    power_law_step,
    stretched_remaining,
    stretched_step,
)
from b1500_test_agent.transport.sim.devices.moscap import MosElectrostatics

MAX_SELF_HEATING_K = 500.0
"""Upper bound of the self-heating temperature rise (K): a thermal runaway is clamped here."""

HCI_MAX_DEGRADATION = 0.95
"""Largest fractional loss of β by hot-carrier degradation."""

CP_THERMAL_VELOCITY_CM_S = 1.0e7
"""Carrier thermal velocity in the charge-pumping emission levels (cm/s; Groeseneken et al. 1984)."""

SILICON_GAP_EV = 1.12
"""Silicon band gap (eV): each emission level lies within half of it from midgap."""


class MosfetEkv:
    """``mosfet_ekv``: EKV long-channel interpolation with mobility degradation, CLM, Rs and gate leakage.

    For an n-channel device with voltages referred to the bulk (p-channel: all voltages and currents mirrored):

    - ``U_T = k·T/q``, pinch-off ``V_P = (V_G - V_T0)/n``, specific current ``I_spec = 2·n·β·U_T²``;
    - forward/reverse ``i_f,r = ln²(1 + exp((V_P - V_S,D)/(2·U_T)))`` — exponential in weak inversion, giving a
      subthreshold swing ``n·U_T·ln10``, and the square law ``(β/2n)(V_G - V_T0 - n·V_S)²`` in strong inversion;
    - ``I_DS = I_spec·(i_f - i_r)·(1 + λ|V_DS|)/(1 + θ·V_ov)`` with the smooth overdrive
      ``V_ov = 2nU_T·ln(1 + exp((V_G - V_T0 - n·V_S)/(2nU_T)))``, so gm peaks and then falls;
    - ``rs_ohm`` in series with source and drain (solved self-consistently by bisection);
    - gate leakage ``g/2·(V_G - V_S) + g/2·(V_G - V_D)``;
    - drain-induced barrier lowering: ``V_T0`` falls by ``dibl·|V_DS|`` (internal voltages, after the series
      resistances), so a constant-current threshold moves by ``-dibl`` volts per volt of drain bias.

    A floating gate, drain or source switches the device off (all currents zero); a floating bulk follows the
    source. ``vth`` arguments override ``vth0`` (terminal polarity); the FeFET uses that for its polarization, the v2
    ``mosfet`` also overrides ``beta`` and ``U_T`` (temperature, degradation).
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

    def _intrinsic(self, vg: float, vd: float, vs: float, vth: float | None = None, beta: float | None = None,
                   ut: float | None = None) -> float:
        """Channel current D→S (A) of the n-type core, voltages already mirrored and referred to the bulk."""
        p = self.params
        n, ut = p.slope_factor, (self.ut if ut is None else ut)
        vt = (p.vth0 if vth is None else vth) * self.sign - p.dibl * abs(vd - vs)
        vp = (vg - vt) / n
        i_f = softplus((vp - vs) / (2 * ut)) ** 2
        i_r = softplus((vp - vd) / (2 * ut)) ** 2
        ispec = 2 * n * (p.beta if beta is None else beta) * ut * ut
        v_source = min(vs, vd)
        vov = 2 * n * ut * softplus((vg - vt - n * v_source) / (2 * n * ut))
        return ispec * (i_f - i_r) * (1 + p.lambda_ * abs(vd - vs)) / (1 + p.theta * vov)

    def channel_current(self, vg: float, vd: float, vs: float = 0.0, vb: float = 0.0, *,
                        vth: float | None = None, beta: float | None = None, ut: float | None = None) -> float:
        """Drain-to-source channel current (A, positive into the drain of a conducting n-channel device) at the
        given terminal voltages, including the series resistances (no gate leakage)."""
        s = self.sign
        g, d, src = s * (vg - vb), s * (vd - vb), s * (vs - vb)
        i0 = self._intrinsic(g, d, src, vth, beta, ut)
        rs = self.params.rs_ohm
        if rs == 0.0 or i0 == 0.0:
            return s * i0
        lo, hi = (0.0, i0) if i0 > 0 else (i0, 0.0)
        for _ in range(200):  # residual f(I) = I - I_int(V_S + I·Rs, V_D - I·Rs) is increasing in I
            mid = 0.5 * (lo + hi)
            if mid - self._intrinsic(g, d - mid * rs, src + mid * rs, vth, beta, ut) > 0:
                hi = mid
            else:
                lo = mid
            if hi - lo <= 1e-15 + 1e-12 * abs(mid):
                break
        return s * 0.5 * (lo + hi)

    def _currents(self, v: Voltages, *, vth: float | None = None, gate_leak_s: float | None = None,
                  beta: float | None = None, ut: float | None = None) -> dict[str, float]:
        vg, vd, vs, vb = v.get("gate"), v.get("drain"), v.get("source"), v.get("bulk")
        zero = {"gate": 0.0, "drain": 0.0, "source": 0.0, "bulk": 0.0}
        if vg is None or vd is None or vs is None:
            return zero
        if vb is None:
            vb = vs
        ids = self.channel_current(vg, vd, vs, vb, vth=vth, beta=beta, ut=ut)
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




class Mosfet(MosfetEkv):
    """``mosfet`` (v2): ``mosfet_ekv`` plus the dynamics of ``MosfetDynamicsParams`` (blueprint 4.2).

    Effective parameters at temperature rise ``ΔT`` (terminal polarity, ``s`` = +1 n / -1 p):
    ``Vth = vth0 + s·(ΔV_BTI + ΔV_IGZO) - s·vth_tc·ΔT``, ``β = beta·(1 - D_HCI)·(T/T0)^-mobility_t_exp``,
    ``U_T = k(T0 + ΔT)/q``.

    - ``terminal_currents`` (DC trial) and ``commit`` are quasi-static: self-heating at its steady state
      ``ΔT = Rth·|Id·Vds|`` (solved self-consistently, Rth·P → Vth/mobility shift), no ageing.
    - ``advance(dt, v)`` ages the device under ``v`` (BTI power law with log recovery, HCI power law, IGZO stretched
      exponential; effective-time laws of ``kinetics``) and relaxes ``ΔT`` towards the new steady state with
      ``tau_th_s``; it returns the currents at the end of the interval (a pulse shorter than ``tau_th_s`` stays cold).
    - ``gate_admittance(v, f, low)``: split C-V from the 1-D MOS electrostatics of the gate stack (``moscap``) with the
      flatband voltage implied by ``vth0``; the channel responds as a distributed RC line driven from source and
      drain, overlaps ``cov_f_per_m·W`` per edge. Evaluated with the source at bulk potential (no body bias).
    - ``pumped_currents(v, drives)`` (WP9.3): the charge-pumping current of a gate pulse train (``PeriodicDrive``),
      ``charge_pumping_truth`` its model value (see ``charge_pumping_current``).

    State (persisted): ``dt_k``, ``bti_dv``, ``bti_dv0``, ``bti_t_rec``, ``bti_recovering``, ``hci_d``, ``igzo_dv``,
    ``igzo_ref``, ``igzo_recovering``. Truth: ``vth``, ``selfheat_truth``, ``pulsed_truth``, ``bti_truth``,
    ``bti_recovery_truth``, ``hci_truth``, ``igzo_truth``, ``cv_truth``, ``charge_pumping_truth``, ``truth()``.
    """

    STATE_KEYS = frozenset({"dt_k", "bti_dv", "bti_dv0", "bti_t_rec", "bti_recovering", "hci_d", "igzo_dv",
                            "igzo_ref", "igzo_recovering"})

    def __init__(self, name: str, params: MosfetParams) -> None:
        super().__init__(name, params)
        self.model = "mosfet"
        self.params: MosfetParams = params
        self.t0 = params.temperature_k
        self.cv: MosElectrostatics | None = None
        if params.w_um is not None and params.l_um is not None and params.tox_nm is not None:
            cox = EPS0_F_CM * params.eps_ox / (params.tox_nm * 1e-7)
            self.cv = MosElectrostatics(cox=cox, nsub=params.nsub_cm3, eps_s_rel=11.7, ni=params.ni_cm3,
                                        temperature_k=params.temperature_k)
            self.wl_cm2 = params.w_um * params.l_um * 1e-8
            self.c_overlap = params.cov_f_per_m * params.w_um * 1e-6
            self.vfb_p = self.sign * params.vth0 - self.cv.vth_offset
        self.reset()

    def reset(self) -> None:
        """Fresh, cold device."""
        self.dt_k = 0.0
        self.bti_dv, self.bti_dv0, self.bti_t_rec, self.bti_recovering = 0.0, 0.0, 0.0, False
        self.hci_d = 0.0
        self.igzo_dv, self.igzo_ref, self.igzo_recovering = 0.0, 0.0, False

    # -- effective parameters ------------------------------------------------------------------------------------------

    def vth_at(self, dt_k: float) -> float:
        """Threshold voltage (terminal polarity) at temperature rise ``dt_k`` with the present degradation."""
        p = self.params
        return p.vth0 + self.sign * (self.bti_dv + self.igzo_dv - p.vth_tc_v_per_k * dt_k)

    def beta_at(self, dt_k: float) -> float:
        """``β`` at temperature rise ``dt_k`` with the present hot-carrier degradation."""
        p = self.params
        return p.beta * (1.0 - self.hci_d) * ((self.t0 + dt_k) / self.t0) ** (-p.mobility_t_exp)

    @property
    def vth(self) -> float:
        """Threshold voltage of the present state (temperature and degradation)."""
        return self.vth_at(self.dt_k)

    def currents_at(self, v: Voltages, dt_k: float) -> dict[str, float]:
        """Terminal currents at temperature rise ``dt_k`` (present degradation)."""
        return self._currents(v, vth=self.vth_at(dt_k), beta=self.beta_at(dt_k),
                              ut=BOLTZMANN_OVER_Q * (self.t0 + dt_k))

    def steady_dt(self, v: Voltages) -> float:
        """Steady self-heating ``ΔT = Rth·|Id·Vds|`` (K) at ``v``, solved self-consistently (0 when floating)."""
        rth = self.params.rth_k_per_w
        vg, vd, vs = v.get("gate"), v.get("drain"), v.get("source")
        if rth == 0.0 or vg is None or vd is None or vs is None:
            return 0.0
        vb = v.get("bulk")
        vb = vs if vb is None else vb

        def heat(dt_k: float) -> float:
            ids = self.channel_current(vg, vd, vs, vb, vth=self.vth_at(dt_k), beta=self.beta_at(dt_k),
                                       ut=BOLTZMANN_OVER_Q * (self.t0 + dt_k))
            return min(rth * abs(ids * (vd - vs)), MAX_SELF_HEATING_K)

        t = heat(0.0)
        for _ in range(60):
            nxt = heat(t)
            if abs(nxt - t) <= 1e-10 * max(1.0, t):
                return nxt
            t = nxt
        lo, hi = 0.0, MAX_SELF_HEATING_K  # no contraction (near runaway): bisection on t - heat(t)
        for _ in range(100):
            mid = 0.5 * (lo + hi)
            if mid - heat(mid) > 0.0:
                hi = mid
            else:
                lo = mid
        return 0.5 * (lo + hi)

    # -- ageing --------------------------------------------------------------------------------------------------------

    def _age(self, dt: float, vgs: float | None, vds: float | None) -> None:
        """Advance BTI, HCI and IGZO drift by ``dt`` under mirrored gate/drain biases (``None``: floating)."""
        p = self.params
        if p.bti_a > 0.0:
            if vgs is not None and vgs > p.bti_v_min:
                self.bti_dv = power_law_step(self.bti_dv, p.bti_a * vgs ** p.bti_gamma, p.bti_n, dt)
                self.bti_recovering = False
            else:
                if not self.bti_recovering:
                    self.bti_recovering, self.bti_dv0, self.bti_t_rec = True, self.bti_dv, 0.0
                self.bti_t_rec += dt
                self.bti_dv = log_decay(self.bti_dv0, self.bti_t_rec, p.bti_recovery, p.bti_recovery_t0_s)
        if p.hci_b > 0.0 and vgs is not None and vds is not None and vds > 0.0 \
                and vgs > self.sign * self.vth_at(self.dt_k):
            rate = p.hci_b * (vds / p.hci_vd_ref_v) ** p.hci_vd_exp
            self.hci_d = min(power_law_step(self.hci_d, rate, p.hci_m, dt), HCI_MAX_DEGRADATION)
        if p.igzo_dvth_per_v != 0.0:
            target = 0.0 if vgs is None else p.igzo_dvth_per_v * vgs
            x = self.igzo_dv
            if target != 0.0 and (x == 0.0 or (target * x > 0.0 and abs(target) >= abs(x))):
                self.igzo_dv = stretched_step(x, target, 0.0, dt, p.igzo_tau_s, p.igzo_beta)
                self.igzo_recovering = False
            else:
                if not self.igzo_recovering:
                    self.igzo_recovering, self.igzo_ref = True, x
                tau = p.igzo_tau_s if p.igzo_recovery_tau_s is None else p.igzo_recovery_tau_s
                self.igzo_dv = stretched_step(x, target, self.igzo_ref, dt, tau, p.igzo_beta)

    # -- device protocol -----------------------------------------------------------------------------------------------

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        return self.currents_at(v, self.steady_dt(v))

    def instant_currents(self, v: Voltages) -> dict[str, float]:
        """Currents at the present temperature and degradation (a fast read that changes nothing)."""
        return self.currents_at(v, self.dt_k)

    def commit(self, v: Voltages) -> None:
        self.dt_k = self.steady_dt(v)

    def advance(self, dt: float, v: Voltages) -> dict[str, float]:
        vg, vd, vs = v.get("gate"), v.get("drain"), v.get("source")
        vgs = None if vg is None or vs is None else self.sign * (vg - vs)
        vds = None if vd is None or vs is None else self.sign * (vd - vs)
        if dt > 0.0:
            self._age(dt, vgs, vds)
        steady = self.steady_dt(v)
        tau = self.params.tau_th_s
        if tau > 0.0 and dt >= 0.0:
            self.dt_k = steady + (self.dt_k - steady) * math.exp(-dt / tau)
        else:
            self.dt_k = steady
        return self.currents_at(v, self.dt_k)

    def export_state(self) -> DeviceState:
        return {"dt_k": self.dt_k, "bti_dv": self.bti_dv, "bti_dv0": self.bti_dv0, "bti_t_rec": self.bti_t_rec,
                "bti_recovering": self.bti_recovering, "hci_d": self.hci_d, "igzo_dv": self.igzo_dv,
                "igzo_ref": self.igzo_ref, "igzo_recovering": self.igzo_recovering}

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.reset()
            return
        owner = f"mosfet {self.name}"
        check_state_keys(data, set(self.STATE_KEYS), owner)
        self.dt_k = state_number(data, "dt_k", owner, lo=0.0, hi=MAX_SELF_HEATING_K)
        self.bti_dv = state_number(data, "bti_dv", owner, lo=0.0)
        self.bti_dv0 = state_number(data, "bti_dv0", owner, lo=0.0)
        self.bti_t_rec = state_number(data, "bti_t_rec", owner, lo=0.0)
        self.bti_recovering = state_flag(data, "bti_recovering", owner)
        self.hci_d = state_number(data, "hci_d", owner, lo=0.0, hi=HCI_MAX_DEGRADATION)
        self.igzo_dv = state_number(data, "igzo_dv", owner)
        self.igzo_ref = state_number(data, "igzo_ref", owner)
        self.igzo_recovering = state_flag(data, "igzo_recovering", owner)

    # -- gate capacitances ---------------------------------------------------------------------------------------------

    def _require_cv(self) -> MosElectrostatics:
        if self.cv is None:
            raise ValueError(f"mosfet {self.name}: gate capacitances need w_um, l_um and tox_nm")
        return self.cv

    def gate_admittance(self, v: Voltages, f: float, low: Collection[str]) -> complex:
        """Small-signal admittance (S) from the gate to the terminals ``low`` (subset of source, drain, bulk) with
        every other terminal AC-grounded, at the DC biases ``v`` (gate-bulk sets the electrostatics, gate-source the
        channel resistance) and frequency ``f``."""
        es = self._require_cv()
        unknown = set(low) - {"source", "drain", "bulk"}
        if unknown:
            raise ValueError(f"mosfet {self.name}: no AC terminal(s) {sorted(unknown)}")
        omega = 2.0 * math.pi * check_frequency(f)
        vg = v.get("gate")
        if vg is None:
            return 0j
        vs = v.get("source")
        vs = 0.0 if vs is None else vs
        vb = v.get("bulk")
        vb = vs if vb is None else vb
        psi = es.solve(self.sign * (vg - vb) - self.vfb_p)
        c_b, c_i = es.c_bulk(psi), es.c_inv_eq(psi)
        denom = es.cox + c_b + c_i
        cgc = self.wl_cm2 * es.cox * c_i / denom
        cgb = self.wl_cm2 * es.cox * c_b / denom
        y_channel = 1j * omega * cgc
        delta = 1e-4
        gds = (self.channel_current(vg, vs + delta, vs, vb, vth=self.vth, beta=self.beta_at(self.dt_k))
               - self.channel_current(vg, vs - delta, vs, vb, vth=self.vth, beta=self.beta_at(self.dt_k))) / (2 * delta)
        if gds > 0.0 and cgc > 0.0:
            x = cmath.sqrt(1j * omega * cgc / gds) / 2.0
            if abs(x) > 1e-6:
                y_channel *= cmath.tanh(x) / x
        else:
            y_channel = 0j
        y = 0j
        for terminal in low:
            if terminal == "bulk":
                y += 1j * omega * cgb
            else:
                y += 0.5 * y_channel + 1j * omega * self.c_overlap
        return y

    def gate_capacitance(self, v: Voltages, f: float, low: Collection[str]) -> float:
        """Parallel capacitance ``Im(Y)/ω`` (F) of ``gate_admittance``."""
        return self.gate_admittance(v, f, low).imag / (2.0 * math.pi * f)

    def split_cv(self, vg: float, f: float) -> dict[str, float]:
        """Split C-V at gate bias ``vg`` (source, drain, bulk at 0 V): ``cgc`` (gate to source+drain) and ``cgb``."""
        v = {"gate": vg, "drain": 0.0, "source": 0.0, "bulk": 0.0}
        return {"cgc": self.gate_capacitance(v, f, ("source", "drain")),
                "cgb": self.gate_capacitance(v, f, ("bulk",))}

    # -- charge pumping ------------------------------------------------------------------------------------------------

    def charge_pumping_current(self, drive: PeriodicDrive, *, vb: float = 0.0, vsb: float = 0.0) -> dict[str, float]:
        """Charge-pumping current of a gate pulse train ``drive`` (Groeseneken et al., IEEE TED 31, 42, 1984), with the
        bulk at ``vb`` and the source/drain ``vsb`` above it (terminal polarity; reverse bias raises the threshold by
        ``n·Vsb``, the EKV pinch-off). In the n-channel frame (p-channel mirrored), with ``ΔVA`` the pulse amplitude:

        - each edge sweeps the surface between flatband ``Vfb`` and threshold ``Vth`` in ``t_em = t_edge·|Vth -
          Vfb|/ΔVA``; trapped electrons (holes) whose emission time ``exp(|E|/U_T)/(σ·v_th·n_i)`` is shorter
          re-emit, so only traps within ``U_T·ln(1/(σ·v_th·n_i·t_em))`` (at most half the gap) of midgap on each
          side recombine: ``ΔE = E_fall + E_rise``;
        - ``Icp = q·f·A·Dit·ΔE·F_acc·F_inv`` with the smooth steps ``F_acc = 1/(1 + exp((V_low - Vfb)/δ))`` (the base
          reaches accumulation) and ``F_inv = 1/(1 + exp((Vth - V_high)/δ))`` (the top reaches inversion), ``δ =
          cp_edge_v``.

        Returns ``icp_a`` (the magnitude), ``delta_e_ev``, ``vfb_v``/``vth_v`` (terminal polarity) and the two step
        factors; ``icp_a`` is 0 without interface traps or geometry.
        """
        p = self.params
        es = self.cv
        s = self.sign
        if es is None or p.dit_cm2_ev == 0.0 or drive.freq_hz <= 0.0:
            return {"icp_a": 0.0, "delta_e_ev": 0.0, "vfb_v": math.nan, "vth_v": math.nan, "f_acc": 0.0, "f_inv": 0.0}
        lo, hi = sorted((s * (drive.low_v - vb), s * (drive.high_v - vb)))
        vth = s * self.vth + p.slope_factor * max(s * vsb, 0.0)
        vfb = s * self.vth - es.vth_offset
        amplitude = hi - lo
        rate = CP_THERMAL_VELOCITY_CM_S * es.ni * p.cp_sigma_cm2
        energy = 0.0
        if amplitude > 0.0:
            for edge in (drive.fall_s, drive.rise_s):
                t_em = max(edge, 1e-15) * abs(vth - vfb) / amplitude
                energy += min(max(self.ut * math.log(1.0 / (rate * t_em)), 0.0), 0.5 * SILICON_GAP_EV)
        f_acc = 1.0 / (1.0 + math.exp(min((lo - vfb) / p.cp_edge_v, 700.0)))
        f_inv = 1.0 / (1.0 + math.exp(min((vth - hi) / p.cp_edge_v, 700.0)))
        icp = Q_E * drive.freq_hz * self.wl_cm2 * p.dit_cm2_ev * energy * f_acc * f_inv
        return {"icp_a": icp, "delta_e_ev": energy, "vfb_v": s * vfb, "vth_v": s * vth, "f_acc": f_acc,
                "f_inv": f_inv}

    def pumped_currents(self, v: Voltages, drives: Mapping[str, PeriodicDrive]) -> dict[str, float]:
        """The charge-pumping current while the gate is driven by ``drives["gate"]``: recombination needs majority
        carriers from the bulk and minority carriers from the source or drain, so a floating bulk or floating source
        and drain carry none. Into the bulk ``+Icp`` (n-channel: holes from the substrate; the bulk SMU reads a
        positive current), out of the connected source/drain terminals ``Icp`` shared equally (p-channel mirrored)."""
        drive = drives.get("gate")
        vb = v.get("bulk")
        ends = [t for t in ("source", "drain") if v.get(t) is not None]
        if drive is None or vb is None or not ends:
            return {}
        reverse = min(self.sign * (float(v[t]) - vb) for t in ends)  # type: ignore[arg-type]
        icp = self.charge_pumping_current(drive, vb=vb, vsb=self.sign * reverse)["icp_a"]
        if icp == 0.0:
            return {}
        out = {"bulk": self.sign * icp}
        for terminal in ends:
            out[terminal] = -self.sign * icp / len(ends)
        return out

    def charge_pumping_truth(self, low_v: float, high_v: float, freq_hz: float, rise_s: float, fall_s: float, *,
                             vsb: float = 0.0) -> dict[str, float]:
        """Model truth of a gate pulse train ``low_v -> high_v`` (gate-bulk, V) at ``freq_hz`` with the given edges:
        ``icp_a``, ``qcp_c = Icp/f`` (charge per cycle), ``delta_e_ev``, ``nit_cm2 = Dit·ΔE`` (traps per cm² in the
        window), ``dit_cm2_ev``, ``area_cm2`` (W·L), ``vfb_v``, ``vth_v`` (``charge_pumping_current``)."""
        drive = PeriodicDrive(low_v=low_v, high_v=high_v, freq_hz=freq_hz, rise_s=rise_s, fall_s=fall_s)
        out = self.charge_pumping_current(drive, vsb=vsb)
        area = self.wl_cm2 if self.cv is not None else 0.0
        return {"icp_a": out["icp_a"], "qcp_c": out["icp_a"] / freq_hz, "delta_e_ev": out["delta_e_ev"],
                "nit_cm2": self.params.dit_cm2_ev * out["delta_e_ev"], "dit_cm2_ev": self.params.dit_cm2_ev,
                "area_cm2": area, "vfb_v": out["vfb_v"], "vth_v": out["vth_v"]}

    # -- truth ---------------------------------------------------------------------------------------------------------

    def selfheat_truth(self, v: Voltages) -> dict[str, float]:
        """Steady temperature rise and drain currents at ``v``: ``id_dc`` (self-heated) and ``id_cold`` (isothermal,
        the limit of a pulse much shorter than ``tau_th_s``)."""
        steady = self.steady_dt(v)
        return {"delta_t_k": steady, "id_dc": self.currents_at(v, steady)["drain"],
                "id_cold": self.currents_at(v, 0.0)["drain"]}

    def pulsed_truth(self, v: Voltages, width: float) -> float:
        """Drain current at the end of a pulse ``v`` of ``width`` seconds applied to the cold device (the thermal
        response of the steady rise, ``ΔT(t) = ΔT_ss·(1 - exp(-t/τ_th))``)."""
        steady = self.steady_dt(v)
        tau = self.params.tau_th_s
        rise = steady if tau == 0.0 else steady * -math.expm1(-width / tau)
        return self.currents_at(v, rise)["drain"]

    def bti_truth(self, v_stress: float, t: float) -> float:
        """BTI threshold-magnitude shift ``A·V^γ·t^n`` (V) after ``t`` seconds of gate overdrive ``v_stress``."""
        p = self.params
        return p.bti_a * abs(v_stress) ** p.bti_gamma * t ** p.bti_n

    def bti_recovery_truth(self, dv0: float, t: float) -> float:
        """Remaining BTI shift ``t`` seconds after the end of a stress that left ``dv0``."""
        return log_decay(dv0, t, self.params.bti_recovery, self.params.bti_recovery_t0_s)

    def hci_truth(self, vds: float, t: float) -> float:
        """Hot-carrier degradation ``|ΔId/Id0| = B·(|Vds|/Vref)^k·t^m`` after ``t`` seconds of drain stress."""
        p = self.params
        return min(p.hci_b * (abs(vds) / p.hci_vd_ref_v) ** p.hci_vd_exp * t ** p.hci_m, HCI_MAX_DEGRADATION)

    def igzo_truth(self, v_stress: float, t: float) -> float:
        """IGZO bias-stress shift ``ΔV∞·(1 - exp(-(t/τ)^β))`` (V) with ``ΔV∞ = igzo_dvth_per_v·v_stress``."""
        p = self.params
        return p.igzo_dvth_per_v * v_stress * (1.0 - stretched_remaining(t, p.igzo_tau_s, p.igzo_beta))

    def cv_truth(self) -> dict[str, float]:
        """Split C-V truth: ``cox_wl_f`` (the Cgc plateau), ``c_overlap_f`` (both overlaps, the Cgc floor),
        ``vfb_v`` and ``vth_v``."""
        es = self._require_cv()
        return {"cox_wl_f": es.cox * self.wl_cm2, "c_overlap_f": 2.0 * self.c_overlap, "vfb_v": self.sign * self.vfb_p,
                "vth_v": self.params.vth0}

    def truth(self) -> dict[str, float]:
        """Ageing and self-heating parameters the §4.2 fidelity targets are checked against."""
        p = self.params
        return {"vth0": p.vth0, "rth_k_per_w": p.rth_k_per_w, "tau_th_s": p.tau_th_s, "bti_a": p.bti_a,
                "bti_gamma": p.bti_gamma, "bti_n": p.bti_n, "hci_b": p.hci_b, "hci_m": p.hci_m,
                "igzo_tau_s": p.igzo_tau_s, "igzo_beta": p.igzo_beta, "igzo_dvth_per_v": p.igzo_dvth_per_v,
                "dit_cm2_ev": p.dit_cm2_ev}
