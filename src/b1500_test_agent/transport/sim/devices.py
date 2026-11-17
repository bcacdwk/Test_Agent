"""Device models of the simulator and the wiring that connects them to channels (blueprint 3).

In v1 every driven terminal is voltage-forced (a channel with its output switch on, or the GNDU at 0 V), so each
terminal current is an explicit function of the terminal voltages; there is no nodal solve. A terminal wired to a
channel whose output switch is off, wired to nothing, or not listed in the wiring is floating (``None``).

Sign convention: currents flow from the instrument into the device terminal (an SMU forcing +V into a resistor
to ground measures a positive current). Truth parameters are exposed (``Device.params``) so tests can compare
extractions with the model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Protocol

from b1500_test_agent.models.sim import MosfetEkvParams, ResistorParams, ShortParams, device_params
from b1500_test_agent.models.station import PinTarget, SimDeviceModel, SimScenario

BOLTZMANN_OVER_Q = 8.617333262e-5
"""k/q in V/K (thermal voltage U_T = k·T/q)."""

Voltages = Mapping[str, float | None]
"""Terminal name → voltage (V), ``None`` = floating."""


class Device(Protocol):
    """A two- or multi-terminal device."""

    name: str
    model: str
    params: object

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        """Current (A) into each terminal for terminal voltages ``v``; floating terminals carry no current."""
        ...


def _softplus(x: float) -> float:
    """ln(1 + e^x) without overflow."""
    return x + math.log1p(math.exp(-x)) if x > 0 else math.log1p(math.exp(x))


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
    source.
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

    def _intrinsic(self, vg: float, vd: float, vs: float) -> float:
        """Channel current D→S (A) of the n-type core, voltages already mirrored and referred to the bulk."""
        p = self.params
        n, ut = p.slope_factor, self.ut
        vp = (vg - p.vth0 * self.sign) / n
        i_f = _softplus((vp - vs) / (2 * ut)) ** 2
        i_r = _softplus((vp - vd) / (2 * ut)) ** 2
        ispec = 2 * n * p.beta * ut * ut
        v_source = min(vs, vd)
        vov = 2 * n * ut * _softplus((vg - p.vth0 * self.sign - n * v_source) / (2 * n * ut))
        return ispec * (i_f - i_r) * (1 + p.lambda_ * abs(vd - vs)) / (1 + p.theta * vov)

    def channel_current(self, vg: float, vd: float, vs: float = 0.0, vb: float = 0.0) -> float:
        """Drain-to-source channel current (A, positive into the drain of a conducting n-channel device) at the
        given terminal voltages, including the series resistances (no gate leakage)."""
        s = self.sign
        g, d, src = s * (vg - vb), s * (vd - vb), s * (vs - vb)
        i0 = self._intrinsic(g, d, src)
        rs = self.params.rs_ohm
        if rs == 0.0 or i0 == 0.0:
            return s * i0
        lo, hi = (0.0, i0) if i0 > 0 else (i0, 0.0)
        for _ in range(200):  # residual f(I) = I - I_int(V_S + I·Rs, V_D - I·Rs) is increasing in I
            mid = 0.5 * (lo + hi)
            if mid - self._intrinsic(g, d - mid * rs, src + mid * rs) > 0:
                hi = mid
            else:
                lo = mid
            if hi - lo <= 1e-15 + 1e-12 * abs(mid):
                break
        return s * 0.5 * (lo + hi)

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        vg, vd, vs, vb = v.get("gate"), v.get("drain"), v.get("source"), v.get("bulk")
        zero = {"gate": 0.0, "drain": 0.0, "source": 0.0, "bulk": 0.0}
        if vg is None or vd is None or vs is None:
            return zero
        if vb is None:
            vb = vs
        ids = self.channel_current(vg, vd, vs, vb)
        half = 0.5 * self.params.gate_leak_s
        igs, igd = half * (vg - vs), half * (vg - vd)
        return {"gate": igs + igd, "drain": ids - igd, "source": -ids - igs, "bulk": 0.0}


def build_device(name: str, spec: SimDeviceModel) -> Device:
    """The device object of scenario entry ``spec`` (params validated against ``models.sim.DEVICE_PARAMS``)."""
    params = device_params(spec.model, dict(spec.params))
    if spec.model == "open":
        return OpenDevice(name)
    if spec.model in ("resistor", "short"):
        assert isinstance(params, ResistorParams | ShortParams)
        return ResistorDevice(name, spec.model, params)
    if spec.model == "mosfet_ekv":
        assert isinstance(params, MosfetEkvParams)
        return MosfetEkv(name, params)
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

    def channel_currents(self, levels: Mapping[int, float]) -> dict[int, float]:
        """Current (A) delivered by each channel in ``levels`` (canonical channel → forced voltage, for the channels
        whose output switch is on). Terminals on other channels float; GNDU terminals are at 0 V."""
        currents = {channel: 0.0 for channel in levels}
        for name, device in self.devices.items():
            wiring = self.wiring.get(name, {})
            voltages: dict[str, float | None] = {}
            for terminal, target in wiring.items():
                if target == "GNDU":
                    voltages[terminal] = 0.0
                elif isinstance(target, int):
                    voltages[terminal] = levels.get(target)
                else:
                    voltages[terminal] = None
            for terminal, current in device.terminal_currents(voltages).items():
                target = wiring.get(terminal)
                if isinstance(target, int) and target in currents:
                    currents[target] += current
        return currents
