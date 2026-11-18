"""Time laws and hysteresis operators shared by the stateful device models (blueprint 4.2).

Every law advances a state variable by a time step ``dt`` from its present value using the *effective time*: the
time the law would have needed to reach that value under the present stress. Constant stress therefore reproduces
the closed-form law exactly however it is split into steps, and a change of stress continues from the reached value
(the usual equivalent-time treatment of BTI, HCI, NLS switching and bias-stress drift; e.g. Kaczer et al., IRPS
2008; Tagantsev et al., Phys. Rev. B 66, 214109, 2002).
"""

from __future__ import annotations

import math

_STRETCHED_DONE = 7.0
"""``ln((t/τ)^β)`` above which ``exp(-(t/τ)^β)`` is taken as 0 (it is below 1e-480)."""


def play(x: float, lo: float, hi: float) -> float:
    """Play (backlash) operator: ``x`` clamped into the band ``[lo, hi]`` (``lo ≤ hi``); inside it ``x`` is kept."""
    return min(max(x, lo), hi)


def sigmoid(x: float) -> float:
    """Logistic function ``1/(1 + e^-x)`` without overflow."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def stretched_remaining(t: float, tau: float, beta: float) -> float:
    """``exp(-(t/τ)^β)`` (1 at ``t = 0``, 0 for ``τ = 0`` or ``t → ∞``), overflow-safe."""
    if t <= 0.0:
        return 1.0
    if tau <= 0.0:
        return 0.0
    if math.isinf(tau):
        return 1.0
    z = beta * math.log(t / tau)
    return 0.0 if z > _STRETCHED_DONE else math.exp(-math.exp(z))


def stretched_step(x: float, target: float, origin: float, dt: float, tau: float, beta: float) -> float:
    """Advance ``x`` by ``dt`` along ``x(t) = target + (origin - target)·exp(-(t/τ)^β)``.

    The effective time of ``x`` on that curve is ``τ·(-ln u)^(1/β)`` with the remaining fraction
    ``u = (target - x)/(target - origin)``; ``x`` at or past ``target`` jumps to ``target``, ``x`` on the far side of
    ``origin`` starts at ``t = 0``. ``τ = ∞`` (no switching) keeps ``x``.
    """
    span = target - origin
    if dt <= 0.0 or span == 0.0 or math.isinf(tau):
        return x
    u = (target - x) / span
    if u <= 0.0:
        return target
    if u >= 1.0:
        return target - (target - x) * stretched_remaining(dt, tau, beta)
    t_eq = tau * (-math.log(u)) ** (1.0 / beta)
    return target - span * stretched_remaining(t_eq + dt, tau, beta)


def power_law_step(x: float, rate: float, exponent: float, dt: float) -> float:
    """Advance ``x`` by ``dt`` along ``x(t) = rate·t^exponent`` (``rate`` ≥ 0, ``0 < exponent ≤ 1``).

    The effective time is ``(x/rate)^(1/exponent)``; ``x`` never decreases (a lower stress continues slowly from the
    reached value). ``rate = 0`` keeps ``x``.
    """
    if dt <= 0.0 or rate <= 0.0:
        return x
    t_eq = (max(x, 0.0) / rate) ** (1.0 / exponent)
    return max(x, rate * (t_eq + dt) ** exponent)


def log_decay(x0: float, t: float, rate: float, t0: float) -> float:
    """``x0·max(0, 1 - rate·log10(1 + t/t0))``: logarithmic relaxation (retention loss, BTI recovery)."""
    if t <= 0.0 or rate <= 0.0:
        return x0
    return x0 * max(0.0, 1.0 - rate * math.log10(1.0 + t / t0))


def endurance_scale(cycles: float, wake_frac: float, wake_cycles: float, fatigue_cycles: float,
                    fatigue_exp: float) -> float:
    """Switchable-polarization factor after ``cycles`` bipolar cycles: wake-up
    ``1 - wake_frac·exp(-N/wake_cycles)`` times fatigue ``1/(1 + (N/fatigue_cycles)^fatigue_exp)`` (1 when
    ``fatigue_cycles`` is 0)."""
    wake = 1.0 - wake_frac * math.exp(-cycles / wake_cycles)
    fatigue = 1.0 if fatigue_cycles <= 0.0 else 1.0 / (1.0 + (max(cycles, 0.0) / fatigue_cycles) ** fatigue_exp)
    return wake * fatigue
