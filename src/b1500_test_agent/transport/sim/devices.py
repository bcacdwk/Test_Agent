"""Device models of the simulator and the wiring that connects them to channels (blueprint 3).

In v1 every driven terminal is voltage-forced (a channel with its output switch on, or the GNDU at 0 V), so each
terminal current is an explicit function of the terminal voltages; there is no nodal solve. A terminal wired to a
channel whose output switch is off, wired to nothing, or not listed in the wiring is floating (``None``).

Sign convention: currents flow from the instrument into the device terminal (an SMU forcing +V into a resistor
to ground measures a positive current). Truth parameters are exposed (``Device.params``) so tests can compare
extractions with the model; ``DiodeDevice.current`` and ``FefetDevice.loop_truth`` give model truth directly.

Models: ``open``, ``resistor``/``short``, ``mosfet_ekv`` (M1); ``diode``, ``fefet`` and ``mosfet_damaged`` (M2).
A device with internal state (``StatefulDevice``: the FeFET polarization) computes its currents for a trial voltage
set without changing that state; the instrument ``commit``s the voltages actually applied (each measurement step
and every DC output change), and the state is persisted in ``SimPersistentState.devices`` (``Circuit.export_state``
/ ``import_state``), so it survives transactions and processes.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from b1500_test_agent.models.sim import (
    DiodeParams,
    FefetParams,
    MosfetDamagedParams,
    MosfetEkvParams,
    ResistorParams,
    ShortParams,
    device_params,
)
from b1500_test_agent.models.station import PinTarget, SimDeviceModel, SimScenario

BOLTZMANN_OVER_Q = 8.617333262e-5
"""k/q in V/K (thermal voltage U_T = k·T/q)."""

EXP_LIMIT = 80.0
"""Exponent above which the diode exponentials continue linearly (no overflow at any SMU voltage; far beyond any
current a compliance allows)."""

Voltages = Mapping[str, float | None]
"""Terminal name → voltage (V), ``None`` = floating."""

DeviceState = dict[str, float | int | bool | str]
"""Persisted internal state of one device (JSON scalars, stored in ``SimPersistentState.devices``)."""


class Device(Protocol):
    """A two- or multi-terminal device."""

    name: str
    model: str
    params: object

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        """Current (A) into each terminal for terminal voltages ``v``; floating terminals carry no current."""
        ...


@runtime_checkable
class StatefulDevice(Protocol):
    """A device whose currents depend on its voltage history (FeFET polarization).

    ``terminal_currents`` evaluates a trial voltage set as if it were applied now, without changing the state;
    ``commit`` applies a voltage set for real.
    """

    name: str

    def terminal_currents(self, v: Voltages) -> dict[str, float]: ...

    def commit(self, v: Voltages) -> None:
        """Update the internal state for the voltages ``v`` that were actually applied."""
        ...

    def export_state(self) -> DeviceState:
        """The internal state as JSON scalars."""
        ...

    def import_state(self, data: Mapping[str, object] | None) -> None:
        """Restore the state (``None``: the initial state). Raises ``ValueError`` for malformed data."""
        ...


def _softplus(x: float) -> float:
    """ln(1 + e^x) without overflow."""
    return x + math.log1p(math.exp(-x)) if x > 0 else math.log1p(math.exp(x))


def _exp_lin(x: float) -> tuple[float, float]:
    """``exp(x)`` and its derivative, continued linearly above ``EXP_LIMIT`` (monotonic, never overflows)."""
    if x <= EXP_LIMIT:
        value = math.exp(x)
        return value, value
    edge = math.exp(EXP_LIMIT)
    return edge * (1.0 + x - EXP_LIMIT), edge


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
        e, de = _exp_lin(vj / self.n_ut)
        current = p.is_a * (e - 1.0) + p.leak_s * vj
        slope = p.is_a * de / self.n_ut + p.leak_s
        if p.bv_v is not None:
            b, db = _exp_lin(-(vj + p.bv_v) / p.bv_width_v)
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
        i_f = _softplus((vp - vs) / (2 * ut)) ** 2
        i_r = _softplus((vp - vd) / (2 * ut)) ** 2
        ispec = 2 * n * p.beta * ut * ut
        v_source = min(vs, vd)
        vov = 2 * n * ut * _softplus((vg - vt - n * v_source) / (2 * n * ut))
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


class FefetDevice(MosfetEkv):
    """``fefet``: ``mosfet_ekv`` with ``Vth = vth0 - k_v·P`` and a hysteretic, persisted polarization ``P``.

    ``P`` (normalised, [-1, 1]) is driven by the gate-source voltage ``V`` (a simplification of the voltage across
    the ferroelectric). On every applied ``V`` it is clamped into the band between the ascending branch
    ``P_up(V) = tanh((V - vc_v)/delta_v)`` and the descending branch ``P_down(V) = tanh((V + vc_v)/delta_v)``: a
    rate-independent play operator, so an ascending sweep follows ``max(P, P_up(V))``, a descending one
    ``min(P, P_down(V))``, and a voltage inside the band (e.g. 0 V) retains the state. A floating gate or source
    leaves ``P`` unchanged. The currents of a trial voltage set use the polarization that voltage would leave
    behind (the step's gate voltage acts before the measurement), without committing it.
    """

    def __init__(self, name: str, params: FefetParams) -> None:
        super().__init__(name, params)
        self.model = "fefet"
        self.params: FefetParams = params
        self.p = params.p_init

    # -- polarization -------------------------------------------------------------------------------------------------

    def p_up(self, v: float) -> float:
        """Ascending branch ``tanh((v - vc)/delta)``."""
        return math.tanh((v - self.params.vc_v) / self.params.delta_v)

    def p_down(self, v: float) -> float:
        """Descending branch ``tanh((v + vc)/delta)``."""
        return math.tanh((v + self.params.vc_v) / self.params.delta_v)

    def polarization_after(self, v: float, p: float | None = None) -> float:
        """Polarization after applying gate-source voltage ``v`` to state ``p`` (default: the current state)."""
        start = self.p if p is None else p
        return min(max(start, self.p_up(v)), self.p_down(v))

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

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        drive = self._drive(v)
        p = self.p if drive is None else self.polarization_after(drive)
        return self._currents(v, vth=self.vth_at(p))

    def commit(self, v: Voltages) -> None:
        drive = self._drive(v)
        if drive is not None:
            self.p = self.polarization_after(drive)

    def export_state(self) -> DeviceState:
        return {"p": self.p}

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.p = self.params.p_init
            return
        if set(data) != {"p"}:
            raise ValueError(f"FeFET {self.name}: state must hold exactly 'p', got {sorted(data)}")
        p = data["p"]
        if isinstance(p, bool) or not isinstance(p, int | float) or not math.isfinite(p) or not -1.0 <= p <= 1.0:
            raise ValueError(f"FeFET {self.name}: polarization {p!r} is not a number in [-1, 1]")
        self.p = float(p)

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
            return max(p0, self.p_up(v)) if ascending else min(p0, self.p_down(v))

        p_turn = self.polarization_after(v_stop, forward(v_stop))

        def reverse(v: float) -> float:
            return min(p_turn, self.p_down(v)) if ascending else max(p_turn, self.p_up(v))

        vth_fwd = self._crossing(forward)
        vth_rev = self._crossing(reverse)
        return {"vth_fwd": vth_fwd, "vth_rev": vth_rev, "memory_window": vth_fwd - vth_rev,
                "p_fwd": forward(vth_fwd), "p_rev": reverse(vth_rev)}


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


def build_device(name: str, spec: SimDeviceModel) -> Device:
    """The device object of scenario entry ``spec`` (params validated against ``models.sim.DEVICE_PARAMS``)."""
    params = device_params(spec.model, dict(spec.params))
    if spec.model == "open":
        return OpenDevice(name)
    if spec.model in ("resistor", "short"):
        assert isinstance(params, ResistorParams | ShortParams)
        return ResistorDevice(name, spec.model, params)
    if spec.model == "fefet":
        assert isinstance(params, FefetParams)
        return FefetDevice(name, params)
    if spec.model == "mosfet_damaged":
        assert isinstance(params, MosfetDamagedParams)
        return DamagedMosfet(name, params)
    if spec.model == "mosfet_ekv":
        assert isinstance(params, MosfetEkvParams)
        return MosfetEkv(name, params)
    if spec.model == "diode":
        assert isinstance(params, DiodeParams)
        return DiodeDevice(name, params)
    raise ValueError(f"No simulator implementation for device model {spec.model!r}.")  # pragma: no cover


def canonical_channel(channel: int) -> int:
    """Canonical channel number: ``101``..``1001`` (subchannel 1) map to ``1``..``10`` (PG Table 4-1, PDF 334);
    subchannel 2 keeps its three/four-digit number."""
    return channel // 100 if channel > 10 and channel % 100 == 1 else channel


class Circuit:
    """All devices of a scenario and their physical wiring (independent of the agent's pin map)."""

    def __init__(self, scenario: SimScenario) -> None:
        self.devices: dict[str, Device] = {name: build_device(name, spec) for name, spec in scenario.models.items()}
        self.wiring: dict[str, dict[str, PinTarget]] = {
            device: {t: canonical_channel(c) if isinstance(c, int) else c for t, c in terminals.items()}
            for device, terminals in scenario.wiring.items()
        }
        self.stateful: dict[str, StatefulDevice] = {
            name: device for name, device in self.devices.items() if isinstance(device, StatefulDevice)
        }

    @property
    def has_state(self) -> bool:
        """True when a device has internal state (then the instrument commits applied voltages)."""
        return bool(self.stateful)

    def _voltages(self, name: str, levels: Mapping[int, float]) -> dict[str, float | None]:
        voltages: dict[str, float | None] = {}
        for terminal, target in self.wiring.get(name, {}).items():
            if target == "GNDU":
                voltages[terminal] = 0.0
            elif isinstance(target, int):
                voltages[terminal] = levels.get(target)
            else:
                voltages[terminal] = None
        return voltages

    def channel_currents(self, levels: Mapping[int, float]) -> dict[int, float]:
        """Current (A) delivered by each channel in ``levels`` (canonical channel → forced voltage, for the channels
        whose output switch is on). Terminals on other channels float; GNDU terminals are at 0 V. Device state is
        not changed (see ``commit``)."""
        currents = {channel: 0.0 for channel in levels}
        for name, device in self.devices.items():
            wiring = self.wiring.get(name, {})
            for terminal, current in device.terminal_currents(self._voltages(name, levels)).items():
                target = wiring.get(terminal)
                if isinstance(target, int) and target in currents:
                    currents[target] += current
        return currents

    def commit(self, levels: Mapping[int, float]) -> None:
        """Apply ``levels`` (the voltages actually forced) to every stateful device."""
        for name, device in self.stateful.items():
            device.commit(self._voltages(name, levels))

    def export_state(self) -> dict[str, DeviceState]:
        """Internal state of every stateful device (for ``SimPersistentState.devices``)."""
        return {name: device.export_state() for name, device in self.stateful.items()}

    def import_state(self, states: Mapping[str, Mapping[str, object]]) -> None:
        """Restore the stateful devices from ``states``; a device without an entry returns to its initial state and
        entries of other devices are ignored. Raises ``ValueError`` for malformed state."""
        for name, device in self.stateful.items():
            device.import_state(states.get(name))
