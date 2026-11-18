"""Per-command output guard (blueprint 2.3, 4.1 layer 3).

``B1500Driver`` calls ``OutputGuard.check`` before it writes any source command (``DV``, ``WV``; later ``DI``/``WI``)
and ``OutputGuard.check_channel`` before ``CN``. A violation raises ``EnvelopeViolation`` and nothing is written. The
envelope is the plan's ``CompiledEnvelope``: the channel allowlist with the largest |V| and |I| (level or
compliance) each channel may see. Values are compared exactly; there is no tolerance and no bypass.
"""

from __future__ import annotations

import math
from typing import Literal

from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope

ViolationReason = Literal[
    "no_guard", "channel_not_allowed", "non_finite", "level_exceeds_envelope", "zero_compliance",
    "compliance_exceeds_envelope",
]  # fmt: skip


class EnvelopeViolation(RuntimeError):
    """A source command would leave the plan's compiled envelope (or no guard is installed); nothing was sent.

    Attributes mirror the refused request so that the transaction can audit an ``envelope_violation`` event.
    """

    def __init__(
        self,
        reason: ViolationReason,
        message: str,
        *,
        channel: int | None = None,
        quantity: str | None = None,
        level: float | None = None,
        compliance: float | None = None,
        limit: float | None = None,
    ) -> None:
        super().__init__(message)
        self.reason: ViolationReason = reason
        self.channel = channel
        self.quantity = quantity
        self.level = level
        self.compliance = compliance
        self.limit = limit


def _normalize(channel: int) -> int:
    """PG Table 4-1: channel ``n`` (1-10) and ``n*100+1`` address the same subchannel."""
    return channel * 100 + 1 if 1 <= channel <= 10 else channel


class OutputGuard:
    """Checked before ANY source command (DV/DI/WV/WI/...) is written: channel in plan allowlist, |level| <= envelope,
    compliance non-zero and <= envelope. Raises EnvelopeViolation; nothing is sent."""

    def __init__(self, envelope: CompiledEnvelope) -> None:
        self.envelope = envelope
        self._channels: dict[int, ChannelEnvelope] = {_normalize(ch): env for ch, env in envelope.channels.items()}

    def channel_envelope(self, ch: int) -> ChannelEnvelope:
        """The envelope of ``ch`` (``1`` and ``101`` are the same channel).

        Raises:
            EnvelopeViolation: ``channel_not_allowed`` when the channel is not in the plan allowlist.
        """
        env = self._channels.get(_normalize(ch)) if isinstance(ch, int) and not isinstance(ch, bool) else None
        if env is None:
            allowed = sorted(self.envelope.channels)
            raise EnvelopeViolation(
                "channel_not_allowed", f"channel {ch!r} is not in the plan allowlist {allowed}", channel=ch
            )
        return env

    def check_channel(self, ch: int) -> None:
        """Refuse a channel outside the plan allowlist (used before ``CN``)."""
        self.channel_envelope(ch)

    def check(self, ch: int, quantity: Literal["V", "I"], level: float, compliance: float) -> None:
        """Refuse a source setting outside the envelope.

        ``quantity`` is what the channel forces: ``"V"`` (``level`` in V, ``compliance`` in A) or ``"I"`` (``level``
        in A, ``compliance`` in V). For a sweep, call once per end point.

        Raises:
            EnvelopeViolation: channel not allowed, non-finite value, |level| above the envelope, zero compliance,
                or |compliance| above the envelope.
            ValueError: If ``quantity`` is neither ``"V"`` nor ``"I"``.
        """
        if quantity not in ("V", "I"):
            raise ValueError(f"quantity must be 'V' or 'I', got {quantity!r}")
        details = {"channel": ch, "quantity": quantity, "level": level, "compliance": compliance}
        env = self.channel_envelope(ch)
        if env.max_abs_i is None:
            raise EnvelopeViolation("channel_not_allowed", f"channel {ch} ({env.role}, {env.function}) is a source "
                                    "without compliance; SMU source commands are not allowed on it", **details)
        if not (math.isfinite(level) and math.isfinite(compliance)):
            raise EnvelopeViolation("non_finite", f"channel {ch}: level and compliance must be finite", **details)
        level_limit, comp_limit = (env.max_abs_v, env.max_abs_i) if quantity == "V" else (env.max_abs_i, env.max_abs_v)
        level_unit, comp_unit = ("V", "A") if quantity == "V" else ("A", "V")
        if abs(level) > level_limit:
            raise EnvelopeViolation(
                "level_exceeds_envelope",
                f"channel {ch}: |{quantity}| {abs(level):g} {level_unit} exceeds the envelope {level_limit:g} "
                f"{level_unit}",
                limit=level_limit,
                **details,
            )
        if compliance == 0:
            raise EnvelopeViolation("zero_compliance", f"channel {ch}: compliance must be non-zero", **details)
        if abs(compliance) > comp_limit:
            raise EnvelopeViolation(
                "compliance_exceeds_envelope",
                f"channel {ch}: |compliance| {abs(compliance):g} {comp_unit} exceeds the envelope {comp_limit:g} "
                f"{comp_unit}",
                limit=comp_limit,
                **details,
            )
