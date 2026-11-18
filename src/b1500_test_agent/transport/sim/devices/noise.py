"""Attachable current noise (``noise``, blueprint 4.2): white (per-range rms), 1/f^γ and random telegraph noise.

A ``noise`` entry of a scenario attaches to one terminal of another device; sampling units (SMU sampling, WGFMU
events) ask the circuit for the sources on a channel (``Circuit.noise_on``) and draw a current series with
``NoiseSource.sample``. The series is deterministic: its generator is seeded from ``(seed, device name, call
counter)``, and the call counter and the trap occupancy are persisted with the simulator state, so consecutive
acquisitions continue the telegraph signal across transactions and processes.

- White noise: Gaussian, rms ``white_frac`` × the measurement range given by the caller (per-range rms).
- 1/f^γ: Gaussian white noise shaped in the frequency domain so that the one-sided PSD is
  ``flicker_k·I²/f^γ`` (Hooge form; Timmer & König, Astron. Astrophys. 300, 707, 1995, without the random amplitude
  draw); each acquisition is an independent realisation (no correlation below ``1/(n·dt)``).
- RTN: a two-state Markov trap with exponential dwell times (mean ``τc`` empty → captured, ``τe`` captured →
  empty), sampled exactly at the sample instants; the current drops by ``ΔI/I·I`` while the trap is occupied
  (Kirton & Uren, Adv. Phys. 38, 367, 1989). PSD: Lorentzian ``4ΔI²/((τc + τe)((1/τc + 1/τe)² + (2πf)²))``.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Mapping

import numpy as np

from b1500_test_agent.models.sim import NoiseParams
from b1500_test_agent.transport.sim.devices.base import DeviceState, Voltages, check_state_keys, state_flag


class NoiseSource:
    """``noise``: the noise of ``NoiseParams`` attached to ``params.attach``/``params.terminal``.

    It carries no current itself (``terminal_currents`` is empty) and ignores applied voltages. State (persisted):
    ``occupied`` (trap state at the end of the last acquisition) and ``calls`` (acquisitions drawn so far).
    """

    terminals: tuple[str, ...] = ()

    def __init__(self, name: str, params: NoiseParams) -> None:
        self.name = name
        self.model = "noise"
        self.params = params
        self._salt = zlib.crc32(name.encode("utf-8"))
        self.occupied = False
        self.calls = 0

    @property
    def rtn_on(self) -> bool:
        """True when a telegraph trap is modelled."""
        return self.params.rtn_tau_c_s is not None and self.params.rtn_delta_rel > 0.0

    # -- sampling ------------------------------------------------------------------------------------------------------

    def sample(self, i_dc: float | np.ndarray, dt: float, n: int, *, range_a: float | None = None) -> np.ndarray:
        """``n`` current samples (A) at interval ``dt`` (s) around the noiseless current ``i_dc`` (scalar or array of
        ``n``), with white noise of rms ``white_frac·range_a`` (none without ``range_a``). Advances the call counter
        and the trap state."""
        if n < 1 or not (math.isfinite(dt) and dt > 0.0):
            raise ValueError(f"noise {self.name}: need n >= 1 and dt > 0, got n={n}, dt={dt}")
        p = self.params
        rng = np.random.default_rng([p.seed, self._salt, self.calls])
        self.calls += 1
        base = np.broadcast_to(np.asarray(i_dc, dtype=float), (n,)).copy()
        out = base.copy()
        if self.rtn_on:
            occupancy = self._telegraph(rng, dt, n)
            out -= p.rtn_delta_rel * base * occupancy
        if p.flicker_k > 0.0 and n >= 4:
            i_mean = float(np.mean(np.abs(base)))
            if i_mean > 0.0:
                out += self._flicker(rng, dt, n, p.flicker_k * i_mean * i_mean)
        if p.white_frac > 0.0 and range_a is not None and range_a > 0.0:
            out += rng.normal(0.0, p.white_frac * range_a, n)
        return out

    def _telegraph(self, rng: np.random.Generator, dt: float, n: int) -> np.ndarray:
        """Trap occupancy (0/1) at ``t_k = k·dt``, starting from the persisted state; exact Markov dwell times."""
        tau_c, tau_e = self.params.rtn_tau_c_s, self.params.rtn_tau_e_s
        assert tau_c is not None and tau_e is not None
        span = n * dt
        state = self.occupied
        flips: list[np.ndarray] = []
        t_end = 0.0
        batch = max(16, int(2.5 * span / (tau_c + tau_e)) + 16)
        while t_end <= span:
            means = np.empty(batch)
            means[0::2] = tau_e if state else tau_c  # dwell in the current state first
            means[1::2] = tau_c if state else tau_e
            times = t_end + np.cumsum(rng.exponential(1.0, batch) * means)
            flips.append(times)
            t_end = float(times[-1])
        edges = np.concatenate(flips)
        t = np.arange(n) * dt
        count = np.searchsorted(edges, t, side="right")
        occupancy = ((count % 2 == 1) != state).astype(float)
        last = int(np.searchsorted(edges, span, side="right"))
        self.occupied = (last % 2 == 1) != state
        return occupancy

    def _flicker(self, rng: np.random.Generator, dt: float, n: int, k_abs: float) -> np.ndarray:
        """Gaussian series with one-sided PSD ``k_abs/f^γ`` (A²/Hz) by spectral shaping of white noise.

        With unit white noise ``w`` (``E|W_k|² = n``) and ``X_k = W_k·√(S(f_k)/(2·dt))``, the periodogram
        ``(2·dt/n)·|X_k|²`` of ``x = irfft(X)`` has expectation ``S(f_k)``; the DC bin is zero."""
        spectrum = np.fft.rfft(rng.standard_normal(n))
        freqs = np.fft.rfftfreq(n, dt)
        gain = np.zeros_like(freqs)
        gain[1:] = np.sqrt(k_abs / freqs[1:] ** self.params.flicker_gamma / (2.0 * dt))
        return np.fft.irfft(spectrum * gain, n)

    # -- device protocol (no current of its own) -----------------------------------------------------------------------

    def terminal_currents(self, v: Voltages) -> dict[str, float]:
        return {}

    def commit(self, v: Voltages) -> None:
        """Applied voltages do not change the noise state."""

    def export_state(self) -> DeviceState:
        return {"occupied": self.occupied, "calls": self.calls}

    def import_state(self, data: Mapping[str, object] | None) -> None:
        if data is None:
            self.occupied, self.calls = False, 0
            return
        owner = f"noise {self.name}"
        check_state_keys(data, {"occupied", "calls"}, owner)
        calls = data["calls"]
        if isinstance(calls, bool) or not isinstance(calls, int) or calls < 0:
            raise ValueError(f"{owner}: state 'calls' = {calls!r} is not a non-negative integer")
        self.occupied = state_flag(data, "occupied", owner)
        self.calls = calls

    # -- truth ---------------------------------------------------------------------------------------------------------

    def psd_truth(self, f: float | np.ndarray, i_dc: float) -> np.ndarray:
        """One-sided PSD (A²/Hz) of the 1/f and telegraph parts at frequency ``f`` for current ``i_dc`` (the white
        part depends on the sampling: rms² spread over ``1/(2·dt)``)."""
        p = self.params
        freq = np.asarray(f, dtype=float)
        psd = p.flicker_k * i_dc * i_dc / freq ** p.flicker_gamma
        if self.rtn_on:
            tau_c, tau_e = p.rtn_tau_c_s, p.rtn_tau_e_s
            assert tau_c is not None and tau_e is not None
            di = p.rtn_delta_rel * abs(i_dc)
            rate = 1.0 / tau_c + 1.0 / tau_e
            psd = psd + 4.0 * di * di / ((tau_c + tau_e) * (rate * rate + (2.0 * math.pi * freq) ** 2))
        return psd

    def truth(self) -> dict[str, float]:
        """Noise truth: ``gamma``, ``flicker_k``, ``tau_c_s``, ``tau_e_s``, ``delta_rel``, ``white_frac``."""
        p = self.params
        return {"gamma": p.flicker_gamma, "flicker_k": p.flicker_k, "tau_c_s": p.rtn_tau_c_s or 0.0,
                "tau_e_s": p.rtn_tau_e_s or 0.0, "delta_rel": p.rtn_delta_rel, "white_frac": p.white_frac}
