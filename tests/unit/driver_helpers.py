"""Test doubles for driver tests: a spy transport that records every command and answers from scripts.

It satisfies the ``Transport`` protocol of blueprint 2.2 structurally, so driver tests need neither
``transport/`` nor the simulator.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping

from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope


class SpyTransport:
    """Records writes and queries in ``sent`` (bus order) and ``log`` (with the operation); answers queries from
    ``answers`` (per command, consumed in order; a plain string is reused forever) and reads from ``reads``.
    An ``Exception`` instance in either script is raised instead of answered."""

    backend = "sim"
    resource = "SPY::unit"

    def __init__(
        self,
        answers: Mapping[str, str | Iterable[str | Exception]] | None = None,
        reads: Iterable[str | Exception] = (),
        stb: int = 0,
    ) -> None:
        self.sent: list[str] = []
        self.log: list[tuple[str, str]] = []
        self.timeouts: list[float | None] = []
        self._fixed: dict[str, str] = {}
        self._queued: dict[str, deque[str | Exception]] = defaultdict(deque)
        for cmd, answer in (answers or {}).items():
            if isinstance(answer, str):
                self._fixed[cmd] = answer
            else:
                self._queued[cmd].extend(answer)
        self._reads: deque[str | Exception] = deque(reads)
        self.stb = stb
        self.closed = False

    def open(self) -> None:
        self.log.append(("open", ""))

    def close(self) -> None:
        self.closed = True
        self.log.append(("close", ""))

    def write(self, cmd: str) -> None:
        self.sent.append(cmd)
        self.log.append(("write", cmd))

    def read(self, *, timeout_s: float | None = None) -> str:
        self.log.append(("read", ""))
        self.timeouts.append(timeout_s)
        item = self._reads.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        self.sent.append(cmd)
        self.log.append(("query", cmd))
        self.timeouts.append(timeout_s)
        if self._queued.get(cmd):
            item = self._queued[cmd].popleft()
        elif cmd in self._fixed:
            item = self._fixed[cmd]
        else:
            raise AssertionError(f"SpyTransport has no answer for {cmd!r}")
        if isinstance(item, Exception):
            raise item
        return item

    def serial_poll(self) -> int:
        self.log.append(("poll", ""))
        return self.stb

    def device_clear(self) -> None:
        self.log.append(("device_clear", ""))


class ReadTimeout(Exception):
    """Stand-in for ``TransportTimeout`` (the driver never catches transport errors)."""


def envelope(**channels: tuple[float, float]) -> CompiledEnvelope:
    """``envelope(ch1=(3.0, 1e-3))`` -> allowlist {1: max |V| 3 V, max |I| 1 mA}; keys are ``ch<number>``."""
    return CompiledEnvelope(
        channels={
            int(name.removeprefix("ch")): ChannelEnvelope(role=name, max_abs_v=v, max_abs_i=i)
            for name, (v, i) in channels.items()
        }
    )
