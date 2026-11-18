"""Ferroelectric device models (blueprint 4.2): ``fefet`` (EKV MOSFET with a hysteretic, persisted polarization; v2
adds NLS pulse switching, retention and wake-up/fatigue) and ``fecap`` (ferroelectric capacitor, Preisach-lite
polarization plus a linear dielectric)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

from b1500_test_agent.models.sim import FecapParams, FefetParams
from b1500_test_agent.models.sim_devices import EnduranceParams
from b1500_test_agent.transport.sim.devices.base import (
    EPS0_F_CM,
    UM2_TO_CM2,
    DeviceState,
    Voltages,
    check_frequency,
    state_number,
    two_terminal,
)
from b1500_test_agent.transport.sim.devices.kinetics import (
    endurance_scale,
    log_decay,
    play,
    stretched_remaining,
    stretched_step,
)
from b1500_test_agent.transport.sim.devices.mosfet import MosfetEkv


class _Endurance:
    """Bipolar-cycle bookkeeping shared by FeFET and FeCap: a change of the polarization's sign class (``P < 0``
    versus ``P ≥ 0``) is half a cycle, so a program/erase pair is one cycle even when a step lands exactly on 0.

    The device sets ``endurance`` (its ``EnduranceParams``) before using the mixin."""

    name: str
    p: float
    cycles: float
    endurance: EnduranceParams

    @property
    def endurance_on(self) -> bool:
        """True when wake-up or fatigue is modelled (then the cycle count is part of the state)."""
        return self.endurance.wake_frac > 0.0 or self.endurance.fatigue_cycles > 0.0

    @property
    def scale(self) -> float:
        """Switchable-polarization factor ``s(N)`` of the current cycle count (1 without endurance effects)."""
        return self.endurance_truth(self.cycles) if self.endurance_on else 1.0

    def endurance_truth(self, cycles: float) -> float:
        """Truth: ``s(N)`` after ``cycles`` bipolar cycles (wake-up × fatigue)."""
        e = self.endurance
        return endurance_scale(cycles, e.wake_frac, e.wake_cycles, e.fatigue_cycles, e.fatigue_exp)

    def _count(self, p_new: float) -> None:
        if self.endurance_on and (self.p < 0.0) != (p_new < 0.0):
            self.cycles += 0.5

    def add_cycles(self, count: float) -> None:
        """Apply ``count`` full program/erase cycles in bulk (an endurance stress phase), ending in the current
        polarity: the polarization is rescaled to the new switchable window. No effect without wake-up/fatigue."""
        if not self.endurance_on or count <= 0:
            return
        old = self.scale
        self.cycles += count
        self.p *= self.scale / old


class FefetDevice(_Endurance, MosfetEkv):
    """``fefet``: ``mosfet_ekv`` with ``Vth = vth0 - k_v·P`` and a hysteretic, persisted polarization ``P``.

    ``P`` (normalised, [-1, 1]) is driven by the gate-source voltage ``V`` (a simplification of the voltage across
    the ferroelectric). On every applied ``V`` it is clamped into the band between the ascending branch
    ``P_up(V) = tanh((V - vc_v)/delta_v)`` and the descending branch ``P_down(V) = tanh((V + vc_v)/delta_v)``: a
    rate-independent play operator, so an ascending sweep follows ``max(P, P_up(V))``, a descending one
    ``min(P, P_down(V))``, and a voltage inside the band (e.g. 0 V) retains the state. A floating gate or source
    leaves ``P`` unchanged. The currents of a trial voltage set use the polarization that voltage would leave
    behind (the step's gate voltage acts before the measurement), without committing it.

    v2 (``FerroKineticsParams``): ``commit`` stays the quasi-static (DC) application above; ``advance(dt, v)`` moves
    ``P`` towards that DC target with nucleation-limited switching, the switched fraction after a pulse of width
    ``w`` being ``1 - exp(-(w/τ(V))^beta_sw)``, ``τ(V) = tau0_s·exp((va_v/|V|)^alpha)`` (effective time from the
    opposite saturation, so a pulse from the saturated state is exact). Between switching events ``P`` relaxes as
    ``P_w·(1 - retention_rate·log10(1 + t/retention_t0_s))``. Wake-up/fatigue scale both branches by ``s(N)``.
    State keys: ``p``; ``p_w``, ``t_ret`` with retention; ``cycles`` with wake-up/fatigue (v1 files hold ``p`` only).
    """

    def __init__(self, name: str, params: FefetParams) -> None:
        super().__init__(name, params)
        self.model = "fefet"
        self.params: FefetParams = params
        self.endurance = params
        self.cycles = 0.0
        self.p = params.p_init * self.scale
        self.p_w = self.p
        self.t_ret = 0.0

    @property
    def retention_on(self) -> bool:
        """True when retention loss is modelled (then ``p_w`` and ``t_ret`` are part of the state)."""
        return self.params.retention_rate > 0.0

    # -- polarization -------------------------------------------------------------------------------------------------

    def p_up(self, v: float) -> float:
        """Ascending branch ``tanh((v - vc)/delta)`` (pristine scale)."""
        return math.tanh((v - self.params.vc_v) / self.params.delta_v)

    def p_down(self, v: float) -> float:
        """Descending branch ``tanh((v + vc)/delta)`` (pristine scale)."""
        return math.tanh((v + self.params.vc_v) / self.params.delta_v)

    def band(self, v: float) -> tuple[float, float]:
        """DC band ``[s·P_up(v), s·P_down(v)]`` at the current endurance scale ``s``."""
        s = self.scale
        if s == 1.0:
            return self.p_up(v), self.p_down(v)
        return s * self.p_up(v), s * self.p_down(v)

    def polarization_after(self, v: float, p: float | None = None) -> float:
        """Polarization after a quasi-static (DC) application of gate-source voltage ``v`` to state ``p`` (default:
        the current state)."""
        start = self.p if p is None else p
        lo, hi = self.band(v)
        return min(max(start, lo), hi)

    def vth_at(self, p: float) -> float:
        """Threshold voltage (V, terminal polarity) at polarization ``p``: ``vth0 - k_v·p``."""
        return self.params.vth0 - self.params.k_v * p

    @property
    def vth(self) -> float:
        """Threshold voltage of the current state."""
        return self.vth_at(self.p)

    @staticmethod
    def _drive(v: Voltages) -> float | None:
        vg, vs = v.get("gate"), v.get("source")
        return None if vg is None or vs is None else vg - vs

    def tau(self, v: float) -> float:
        """NLS switching time ``τ(V) = tau0·exp((va/|V|)^alpha)`` (s; ``inf`` at 0 V)."""
        p = self.params
        if v == 0.0:
            return math.inf
        z = (p.va_v / abs(v)) ** p.alpha
        return math.inf if z > 700.0 else p.tau0_s * math.exp(z)

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        drive = self._drive(v)
        p = self.p if drive is None else self.polarization_after(drive)
        return self._currents(v, vth=self.vth_at(p))

    def instant_currents(self, v: Voltages) -> dict[str, float]:
        """Currents with the present polarization (a read that switches nothing, e.g. right after a pulse)."""
        return self._currents(v, vth=self.vth)

    def _switch_to(self, p_new: float) -> None:
        self._count(p_new)
        self.p = p_new
        self.p_w, self.t_ret = p_new, 0.0

    def commit(self, v: Voltages) -> None:
        drive = self._drive(v)
        if drive is None:
            return
        p_new = self.polarization_after(drive)
        if p_new != self.p:
            self._switch_to(p_new)

    def advance(self, dt: float, v: Voltages) -> dict[str, float]:
        drive = self._drive(v)
        switched = False
        if drive is not None and dt > 0.0:
            target = self.polarization_after(drive)
            if target != self.p:
                origin = -self.scale if target > self.p else self.scale
                p_new = stretched_step(self.p, target, origin, dt, self.tau(drive), self.params.beta_sw)
                if p_new != self.p:
                    self._switch_to(p_new)
                    switched = True
        if not switched and self.retention_on and dt > 0.0:
            self.t_ret += dt
            self.p = log_decay(self.p_w, self.t_ret, self.params.retention_rate, self.params.retention_t0_s)
        return self._currents(v, vth=self.vth)

    def add_cycles(self, count: float) -> None:
        super().add_cycles(count)
        self.p_w, self.t_ret = self.p, 0.0

    def _state_keys(self) -> set[str]:
        keys = {"p"}
        if self.retention_on:
            keys |= {"p_w", "t_ret"}
        if self.endurance_on:
            keys.add("cycles")
        return keys

    def export_state(self) -> DeviceState:
        state: DeviceState = {"p": self.p}
        if self.retention_on:
            state.update(p_w=self.p_w, t_ret=self.t_ret)
        if self.endurance_on:
            state["cycles"] = self.cycles
        return state

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.cycles = 0.0
            self.p = self.params.p_init * self.scale
            self.p_w, self.t_ret = self.p, 0.0
            return
        keys = self._state_keys()
        if set(data) != keys:
            names = ", ".join(repr(k) for k in sorted(keys))
            raise ValueError(f"FeFET {self.name}: state must hold exactly {names}, got {sorted(data)}")
        p = data["p"]
        if isinstance(p, bool) or not isinstance(p, int | float) or not math.isfinite(p) or not -1.0 <= p <= 1.0:
            raise ValueError(f"FeFET {self.name}: polarization {p!r} is not a number in [-1, 1]")
        owner = f"FeFET {self.name}"
        self.cycles = state_number(data, "cycles", owner, lo=0.0) if self.endurance_on else 0.0
        self.p = float(p)
        if self.retention_on:
            self.p_w = state_number(data, "p_w", owner, lo=-1.0, hi=1.0)
            self.t_ret = state_number(data, "t_ret", owner, lo=0.0)
        else:
            self.p_w, self.t_ret = self.p, 0.0

    # -- truth ------------------------------------------------------------------------------------------------------

    def _crossing(self, path_p: Callable[[float], float]) -> float:
        """Gate voltage ``V`` with ``V = vth_at(path_p(V))`` (unique: the difference is strictly increasing)."""
        lo, hi = -100.0, 100.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if mid - self.vth_at(path_p(mid)) > 0:
                hi = mid
            else:
                lo = mid
            if hi - lo < 1e-12:
                break
        return 0.5 * (lo + hi)

    def loop_truth(self, v_start: float, v_stop: float, *, p: float | None = None) -> dict[str, float]:
        """Model truth of a double sweep ``v_start → v_stop → v_start`` (gate-source voltage) from state ``p``
        (default: the current state), without changing the device.

        ``vth_fwd``/``vth_rev``: threshold voltage at which the gate voltage crosses the threshold on the first and
        second branch (the polarization along a monotonic branch is ``max(P0, P_up(V))`` ascending and
        ``min(P0, P_down(V))`` descending); ``memory_window`` = ``vth_fwd - vth_rev`` (positive for the
        counter-clockwise ferroelectric loop of an n-channel FeFET swept upwards first); ``p_fwd``/``p_rev``: the
        polarization at those crossings. Both thresholds are the model ``Vth = vth0 - k_v·P`` (an extraction adds
        its own method offset, e.g. ``(n - 1)·Vd/2`` for linear extrapolation, which cancels in the window).
        """
        p0 = self.polarization_after(v_start, self.p if p is None else p)
        ascending = v_stop >= v_start

        def forward(v: float) -> float:
            lo, hi = self.band(v)
            return max(p0, lo) if ascending else min(p0, hi)

        p_turn = self.polarization_after(v_stop, forward(v_stop))

        def reverse(v: float) -> float:
            lo, hi = self.band(v)
            return min(p_turn, hi) if ascending else max(p_turn, lo)

        vth_fwd = self._crossing(forward)
        vth_rev = self._crossing(reverse)
        return {"vth_fwd": vth_fwd, "vth_rev": vth_rev, "memory_window": vth_fwd - vth_rev,
                "p_fwd": forward(vth_fwd), "p_rev": reverse(vth_rev)}

    def switched_fraction(self, width: float, v: float) -> float:
        """Truth: NLS switched fraction ``1 - exp(-(w/τ(V))^beta_sw)`` of one pulse of width ``width`` at ``v``."""
        return 1.0 - stretched_remaining(width, self.tau(v), self.params.beta_sw)

    def pulse_truth(self, v: float, width: float, p: float | None = None) -> float:
        """Truth: polarization after one gate pulse ``v`` of width ``width`` from state ``p`` (default: current),
        without changing the device."""
        start = self.p if p is None else p
        target = self.polarization_after(v, start)
        if target == start:
            return start
        origin = -self.scale if target > start else self.scale
        return stretched_step(start, target, origin, width, self.tau(v), self.params.beta_sw)

    def memory_window_truth(self, v_program: float, v_erase: float, width: float) -> float:
        """Truth: ``Vth(erased) - Vth(programmed)`` (V) for one program pulse from the erased saturation and one erase
        pulse from the programmed saturation, both of width ``width``."""
        s = self.scale
        return self.params.k_v * (self.pulse_truth(v_program, width, -s) - self.pulse_truth(v_erase, width, s))

    def retention_truth(self, p_written: float, t: float) -> float:
        """Truth: polarization ``t`` seconds after writing ``p_written`` (no disturbing bias)."""
        return log_decay(p_written, t, self.params.retention_rate, self.params.retention_t0_s)

    def retention_slope(self, p_written: float) -> float:
        """Truth: ``dVth/dlog10(t)`` (V/decade) of a state written to ``p_written``, for ``t ≫ retention_t0_s``."""
        return self.params.k_v * p_written * self.params.retention_rate


class FecapDevice(_Endurance):
    """``fecap``: ferroelectric capacitor of ``FecapParams`` between ``top`` and ``bottom`` (blueprint 4.2).

    Preisach-lite polarization: the Preisach model restricted to hysterons on the line ``α - β = 2Ec`` with the
    density of Miller's tanh branches, i.e. a play operator between ``s·P+(V)`` and ``s·P-(V)`` (minor loops are
    flat; rate independent). ``p`` is the polarization as a fraction of ``Ps``. ``advance`` returns
    ``I = A·Ps·Δp/dt + C·ΔV/dt + leak_s·V`` (exact for a linear ramp between the applied voltages, the shape a
    WGFMU/SPGU sweep samples). State: ``p``, last voltage ``v``, direction ``dir`` of the last voltage change (selects
    the branch of the reversible C-V response), ``cycles`` with wake-up/fatigue. Truth: ``pund_truth``,
    ``butterfly_truth``, ``params``.
    """

    terminals = ("top", "bottom")

    def __init__(self, name: str, params: FecapParams) -> None:
        self.name = name
        self.model = "fecap"
        self.params = params
        self.endurance = params
        self.area = params.area_um2 * UM2_TO_CM2
        t_cm = params.thickness_nm * 1e-7
        self.vc = params.ec_mv_cm * 1e6 * t_cm
        r = params.pr_uc_cm2 / params.ps_uc_cm2
        self.delta_v = self.vc / math.log((1.0 + r) / (1.0 - r))
        self.ps_c = params.ps_uc_cm2 * 1e-6 * self.area
        self.c_lin = EPS0_F_CM * params.eps_r * self.area / t_cm
        self.cycles = 0.0
        self.p = params.p_init * self.scale
        self.v = 0.0
        self.dir = 1.0

    # -- polarization ----------------------------------------------------------------------------------------------

    def p_up(self, v: float) -> float:
        """Ascending branch ``tanh((V - Vc)/2δ)`` (fraction of Ps, pristine)."""
        return math.tanh((v - self.vc) / (2.0 * self.delta_v))

    def p_down(self, v: float) -> float:
        """Descending branch ``tanh((V + Vc)/2δ)`` (fraction of Ps, pristine)."""
        return math.tanh((v + self.vc) / (2.0 * self.delta_v))

    def band(self, v: float) -> tuple[float, float]:
        s = self.scale
        return s * self.p_up(v), s * self.p_down(v)

    def polarization_after(self, v: float, p: float | None = None) -> float:
        """Polarization (fraction of Ps) after applying ``v`` to state ``p`` (default: current)."""
        return play(self.p if p is None else p, *self.band(v))

    @property
    def polarization_uc_cm2(self) -> float:
        """Current polarization (µC/cm²)."""
        return self.p * self.params.ps_uc_cm2

    def _apply(self, dv: float) -> float:
        """Apply ``dv``: update polarization, direction and voltage; return the polarization change (fraction)."""
        p_new = self.polarization_after(dv)
        if dv != self.v:
            self.dir = 1.0 if dv > self.v else -1.0
        delta = p_new - self.p
        if delta != 0.0:
            self._count(p_new)
            self.p = p_new
        self.v = dv
        return delta

    # -- device protocol -------------------------------------------------------------------------------------------

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "top", "bottom")
        current = 0.0 if dv is None else self.params.leak_s * dv
        return {"top": current, "bottom": -current}

    def commit(self, v: Voltages) -> None:
        dv = two_terminal(v, "top", "bottom")
        if dv is not None:
            self._apply(dv)

    def advance(self, dt: float, v: Voltages) -> dict[str, float]:
        dv = two_terminal(v, "top", "bottom")
        if dv is None:
            return {"top": 0.0, "bottom": 0.0}
        v_old = self.v
        delta = self._apply(dv)
        current = self.params.leak_s * dv
        if dt > 0.0:
            current += (self.ps_c * delta + self.c_lin * (dv - v_old)) / dt
        return {"top": current, "bottom": -current}

    def capacitance(self, v: float, f: float) -> float:
        """Small-signal capacitance at ``v``: ``C_lin`` plus ``k_rev·A·Ps·s·dP±/dV`` of the branch in the direction of
        the last voltage change (C-V butterfly)."""
        check_frequency(f)
        branch_v = v - self.vc if self.dir > 0 else v + self.vc
        slope = 1.0 / (2.0 * self.delta_v * math.cosh(branch_v / (2.0 * self.delta_v)) ** 2)
        return self.c_lin + self.params.k_rev * self.ps_c * self.scale * slope

    def admittance(self, v: float, f: float) -> complex:
        return complex(self.params.leak_s, 2.0 * math.pi * f * self.capacitance(v, f))

    def export_state(self) -> DeviceState:
        state: DeviceState = {"p": self.p, "v": self.v, "dir": self.dir}
        if self.endurance_on:
            state["cycles"] = self.cycles
        return state

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.cycles = 0.0
            self.p, self.v, self.dir = self.params.p_init * self.scale, 0.0, 1.0
            return
        owner = f"FeCap {self.name}"
        keys = {"p", "v", "dir"} | ({"cycles"} if self.endurance_on else set())
        if set(data) != keys:
            raise ValueError(f"{owner}: state must hold exactly {sorted(keys)}, got {sorted(data)}")
        self.cycles = state_number(data, "cycles", owner, lo=0.0) if self.endurance_on else 0.0
        self.p = state_number(data, "p", owner, lo=-1.0, hi=1.0)
        self.v = state_number(data, "v", owner)
        direction = state_number(data, "dir", owner, lo=-1.0, hi=1.0)
        if direction not in (-1.0, 1.0):
            raise ValueError(f"{owner}: state 'dir' must be -1 or 1, got {direction!r}")
        self.dir = direction

    # -- truth -----------------------------------------------------------------------------------------------------

    def pund_truth(self, v_max: float) -> dict[str, float]:
        """Truth of a PUND sequence with amplitude ``v_max`` (> 0) at the current endurance scale.

        ``pr_uc_cm2``: half the switched polarization ``(P - U)/2`` between the remanent states left by ``±v_max``;
        ``ps_uc_cm2``: the polarization at ``+v_max`` reached from the negative remanent state; ``ec_mv_cm``/``vc_v``:
        the coercive field/voltage (peak of the switching current, ``P+`` crossing zero)."""
        s = self.scale
        neg = self.polarization_after(0.0, self.polarization_after(-v_max, s))
        pos = self.polarization_after(0.0, self.polarization_after(v_max, -s))
        top = self.polarization_after(v_max, neg)
        ps = self.params.ps_uc_cm2
        return {"pr_uc_cm2": 0.5 * (pos - neg) * ps, "ps_uc_cm2": top * ps, "ec_mv_cm": self.params.ec_mv_cm,
                "vc_v": self.vc}

    def butterfly_truth(self) -> dict[str, float]:
        """Truth: the C-V butterfly peaks at ``+Vc`` (ascending sweep) and ``-Vc`` (descending sweep)."""
        return {"v_peak_up": self.vc, "v_peak_down": -self.vc}
