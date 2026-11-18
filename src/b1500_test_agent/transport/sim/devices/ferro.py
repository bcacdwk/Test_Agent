"""Ferroelectric device models (blueprint 4.2): ``fefet`` (EKV MOSFET with a hysteretic, persisted polarization)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

from b1500_test_agent.models.sim import FefetParams
from b1500_test_agent.transport.sim.devices.base import DeviceState, Voltages
from b1500_test_agent.transport.sim.devices.mosfet import MosfetEkv


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


