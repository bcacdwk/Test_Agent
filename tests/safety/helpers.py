"""Harness for the safety suite: a simulator session with an injection hook, an in-memory run, the test-local
acquisition body and the global-invariant check (blueprint 3, 8.1).

Measurement kinds arrive in WP1.7, so ``acquire`` is a small staircase body written against the guarded driver:
``FMT 1,1``, ``CN 1,3``, drain bias, (hook ``configure``), staircase on the gate, ``XE`` (hook ``after_xe``), read
(hook ``during_read``). Everything runs in temporary directories; nothing touches ``config/local/`` or hardware.

The module-level ``hold_lock`` and ``crash_inside_transaction`` functions are child-process targets for the
two-process tests (``multiprocessing`` spawn context, so they must be importable).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from b1500_test_agent.driver import commands
from b1500_test_agent.driver.b1500 import RawBlock, StaircaseSetup
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.run import LockHolder
from b1500_test_agent.models.station import Settings, SimScenario
from b1500_test_agent.session import InstrumentLock, Session, Transaction
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import state_hooks
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from b1500_test_agent.transport.sim.state import CommandRecord
from tests.sim.helpers import load_scenario, noiseless

RUN_ID = "S20261117T063012Z-7f3a"
PLAN_ID = "P-ABCDEFGHIJ"
GATE, DRAIN = 1, 3
ENVELOPE = CompiledEnvelope(channels={
    GATE: ChannelEnvelope(role="gate", max_abs_v=2.0, max_abs_i=1e-4),
    DRAIN: ChannelEnvelope(role="drain", max_abs_v=0.5, max_abs_i=1e-3),
})
SWEEP = StaircaseSetup(channel=GATE, start=0.0, stop=1.5, points=11, icomp=1e-5, measure=(DRAIN,))
WIDTH = 2
"""Elements per step with ``FMT 1,1``: the drain current and the gate source value."""

CLEANUP_ORDER = ("device_clear", "abort", "zero", "disconnect", "drain_errors", "verify")


class HookTransport:
    """Transport wrapper under the audit layer that runs test actions at the injection moments.

    ``after_xe`` fires right after the ``XE`` write returned, ``during_read`` at the start of every ``read`` (data
    reads only; queries use ``query``); ``raise_next`` (armed for the cleanup moment) is raised once by the next
    transport call of any kind.
    """

    def __init__(self, inner: SimTransport) -> None:
        self.inner = inner
        self.actions: dict[str, Callable[[], None]] = {}
        self.raise_next: BaseException | None = None

    @property
    def backend(self) -> str:
        return self.inner.backend

    @property
    def resource(self) -> str:
        return self.inner.resource

    def fire(self, moment: str) -> None:
        action = self.actions.pop(moment, None)
        if action is not None:
            action()

    def _armed(self) -> None:
        exc, self.raise_next = self.raise_next, None
        if exc is not None:
            raise exc

    def open(self) -> None:
        self.inner.open()

    def close(self) -> None:
        self.inner.close()

    def write(self, cmd: str) -> None:
        self._armed()
        self.inner.write(cmd)
        if cmd == commands.XE:
            self.fire("after_xe")

    def read(self, *, timeout_s: float | None = None) -> str:
        self._armed()
        self.fire("during_read")
        return self.inner.read(timeout_s=timeout_s)

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        self._armed()
        return self.inner.query(cmd, timeout_s=timeout_s)

    def serial_poll(self) -> int:
        self._armed()
        return self.inner.serial_poll()

    def device_clear(self) -> None:
        self._armed()
        self.inner.device_clear()


@dataclass
class MemoryRun:
    """``RunHandle`` test double: the run's audit sink in memory and the raw blocks in a list."""

    run_id: str = RUN_ID
    audit: MemoryAuditSink = field(default_factory=MemoryAuditSink)
    raw: list[str] = field(default_factory=list)

    def save_raw(self, raw: str) -> str:
        self.raw.append(raw)
        return f"raw/block-{len(self.raw) - 1:03d}.txt"


@dataclass
class Harness:
    """One simulator session in ``state_dir`` with its hook, sinks and run."""

    session: Session
    sim: SimTransport
    hook: HookTransport
    daily: MemoryAuditSink
    run: MemoryRun
    state_dir: Path
    tx: Transaction | None = None

    def transaction(self, *, envelope: CompiledEnvelope | None = ENVELOPE, run: bool = True,
                    intent: str = "safety staircase", **kwargs: Any) -> Transaction:
        return self.session.transaction(intent=intent, envelope=envelope, run=self.run if run else None,
                                        plan_id=PLAN_ID, **kwargs)

    def at(self, moment: str, action: Callable[[], None]) -> None:
        """Run ``action`` at ``moment`` (``configure``, ``after_xe``, ``during_read``, ``cleanup``)."""
        self.hook.actions[moment] = action

    def events(self, *, run: bool = True) -> list[AuditEvent]:
        return self.run.audit.events if run else self.daily.events

    @property
    def log(self) -> list[CommandRecord]:
        return self.sim.instrument.command_log


def make_harness(state_dir: Path, scenario: SimScenario | None = None, *, adapter: str = "cli") -> Harness:
    """A harness over the noiseless ``nmos_basic`` scenario (gate = SMU1, drain = SMU3) unless ``scenario`` is given."""
    scenario = scenario or noiseless(load_scenario("nmos_basic"))
    sim = SimTransport(scenario, state_file=sim_state_file(state_dir, scenario.name))
    hook = HookTransport(sim)
    daily = MemoryAuditSink()
    settings = Settings.model_validate({"sim": {"scenario": scenario.name}})
    session = Session(settings, lambda: AuditingTransport(hook, daily), daily, state_dir=state_dir,
                      adapter=adapter)  # type: ignore[arg-type]
    return Harness(session=session, sim=sim, hook=hook, daily=daily, run=MemoryRun(), state_dir=state_dir)


def acquire(tx: Transaction, hook: HookTransport) -> RawBlock:
    """The test-local acquisition body: configure a staircase through the guarded driver, ``XE``, read."""
    driver = tx.driver
    driver.set_format(1, 1)
    driver.enable([GATE, DRAIN])
    driver.force_v(DRAIN, 0.1, icomp=1e-3)
    hook.fire("configure")
    driver.staircase_v(SWEEP)
    tx.mark("configured")
    block = driver.execute_and_read(expected_points=SWEEP.points * WIDTH, timeout_s=5.0)
    tx.mark("read")
    return block


# -- invariant checks -------------------------------------------------------------------------------------------------


def source_levels(record: CommandRecord) -> tuple[int, list[float], float | None]:
    """Channel, forced levels and compliance of a ``DV``/``WV`` record (PG PDF 396, 568)."""
    args = record.args
    channel = int(args[0])
    if record.mnemonic == "DV":
        return channel, [float(args[2])], float(args[3]) if len(args) > 3 else None
    return channel, [float(args[3]), float(args[4])], float(args[6]) if len(args) > 6 else None


def assert_within_envelope(log: list[CommandRecord], envelope: CompiledEnvelope = ENVELOPE) -> None:
    """No source command outside ``envelope`` ever reached the transport (every record, dropped ones included)."""
    for record in log:
        if not record.source:
            continue
        channel, levels, compliance = source_levels(record)
        channel = channel // 100 if channel > 10 else channel
        env = envelope.channels.get(channel)
        assert env is not None, f"source command on a channel outside the allowlist: {record.command}"
        assert all(abs(level) <= env.max_abs_v for level in levels), f"level outside the envelope: {record.command}"
        assert compliance is not None and 0 < abs(compliance) <= env.max_abs_i, f"bad compliance: {record.command}"


def cleanup_sequence(events: list[AuditEvent]) -> list[tuple[int, str]]:
    return [(int(e.data["attempt"]), str(e.data["step"])) for e in events  # type: ignore[index, arg-type]
            if e.ev == "cleanup_step"]


def assert_cleanup_order(events: list[AuditEvent]) -> None:
    """Every attempt of the (single) cleanup runs its steps in blueprint order and includes DZ, CL, drain, verify."""
    sequence = cleanup_sequence(events)
    assert sequence, "no cleanup steps audited"
    attempts = sorted({attempt for attempt, _ in sequence})
    assert attempts in ([1], [1, 2])
    for attempt in attempts:
        steps = [step for a, step in sequence if a == attempt]
        indices = [CLEANUP_ORDER.index(step) for step in steps]
        assert indices == sorted(indices) and len(set(indices)) == len(indices), steps
        assert {"zero", "disconnect", "drain_errors", "verify"} <= set(steps), steps
        assert ("device_clear" in steps) == (attempt == 2), steps
    assert [a for a, _ in sequence] == sorted(a for a, _ in sequence), "attempts interleave"


def assert_global_invariant(h: Harness, *, run: bool = True) -> None:
    """Blueprint 3: if any source command reached the instrument, DZ and CL executed after the last one and the
    simulator is safe, or the fault latch is set with ``cleanup_unverified`` audited. Plus: nothing outside the
    envelope reached the transport, the lock is free, the inflight marker is gone, the cleanup is audited in order
    and every raw block read was handed to the run."""
    log = h.log
    assert_within_envelope(log)
    events = h.events(run=run)
    latched = h.session.fault_latch.get() is not None and any(e.ev == "cleanup_unverified" for e in events)
    reached = [r for r in log if r.source and r.outcome != "dropped"]
    if reached and not latched:
        last = reached[-1].seq
        after = {r.mnemonic for r in log if r.seq > last and r.outcome == "ok"}
        assert {"DZ", "CL"} <= after, f"DZ/CL missing after the last source command: {sorted(after)}"
        h.sim.instrument.assert_safe()
    assert h.session.lock.holder() is None and not h.session.lock.is_held(), "instrument lock still held"
    assert not (h.state_dir / "inflight.json").exists(), "inflight marker left behind"
    assert_cleanup_order(events)
    assert [e.ev for e in events].count("lock_released") == 1
    if run:
        reads = [e.resp for e in events if e.ev == "read" and e.error is None]
        assert reads == h.run.raw, "a raw block read from the instrument was not handed to the run"
        assert sum(e.ev == "data_block" for e in events) == len(h.run.raw)


# -- child-process targets (multiprocessing spawn) --------------------------------------------------------------------


def hold_lock(state_dir: str, resource: str, ready: Any, release: Any, crash: bool) -> None:
    """Hold the instrument lock as an ``mcp`` adapter for plan ``PLAN_ID``; signal ``ready``; then either wait for
    ``release`` or die without releasing (``crash``)."""
    from datetime import UTC, datetime

    holder = LockHolder(pid=os.getpid(), host="child-host", adapter="mcp", plan_id=PLAN_ID, since=datetime.now(UTC))
    with InstrumentLock(Path(state_dir), resource).acquire(holder, timeout_s=10.0):
        ready.set()
        if crash:
            os._exit(3)
        release.wait(30.0)


def crash_inside_transaction(state_dir: str, ready: Any) -> None:
    """Enter a transaction, switch outputs on (gate 1.2 V, drain 0.1 V), persist the simulator state and die without
    any cleanup: the inflight marker and the live outputs stay behind."""
    h = make_harness(Path(state_dir))
    tx = h.transaction(run=False, intent="crashing body")
    tx.__enter__()
    tx.driver.enable([GATE, DRAIN])
    tx.driver.force_v(DRAIN, 0.1, icomp=1e-3)
    tx.driver.force_v(GATE, 1.2, icomp=1e-5)
    hooks = state_hooks(h.session.transport)
    assert hooks is not None
    hooks.save_state()
    ready.set()
    os._exit(4)
