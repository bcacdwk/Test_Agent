"""WGFMU test harness (WP10.3): a simulator session whose bus carries both links with spies, a lab-layout DUT on the
WGFMU channels and an SMU, the plan envelope, waveform programs and the global invariant v2 (WGFMU part).

- Scenario ``wg_resistors``: lab mainframe (SPGU 1, WGFMU 2, HRSMU 3-4, MPSMU 5-6, MFCMU 7); ``r_wg`` 10 kOhm between
  WGFMU channels 201 and 202 (201 drives, 202 holds 0 V and measures current), ``r_smu`` 100 kOhm from SMU3 to the
  GNDU (a FLEX bias inside the WGFMU phase, as WG Ex. 10 combines an SMU with the WGFMU).
- Station: the example station with both RSUs and SEL1 verified (``rules_factory_v2.lab_station``).
- Envelope: 201/202 WGFMU roles (3 V, waveform limits), SMU3 bias (1 V, 1 mA), RSU routes to ``wgfmu``.
- ``SpyWgfmu`` sits between the audit wrapper and the simulated library: it records every call with its arguments
  (vector values included) and fires test actions before or after a named call (``before:add_vectors``,
  ``after:execute`` ...). The FLEX side keeps ``HookTransport`` and records whether the link held its exclusive lock
  at every write.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from b1500_test_agent.driver.wgfmu import WgfmuBlock
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.sources import WaveformProgram
from b1500_test_agent.models.station import Settings, SimScenario
from b1500_test_agent.session import Session, Transaction
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import Bus, state_hooks
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu
from tests.safety.helpers import PLAN_ID, HookTransport, MemoryRun, assert_cleanup_order, assert_within_envelope
from tests.unit.rules_factory_v2 import RSU201, RSU202, lab_station, wave, wg_limits

TOP, BOTTOM, SMU = 201, 202, 3
LAB_SLOTS = [{"slot": 1, "model": "B1525A"}, {"slot": 2, "model": "B1530A"}, {"slot": 3, "model": "B1517A"},
             {"slot": 4, "model": "B1517A"}, {"slot": 5, "model": "B1511B"}, {"slot": 6, "model": "B1511B"},
             {"slot": 7, "model": "B1520A"}]
R_WG_OHM = 1e4
R_SMU_OHM = 1e5

ENVELOPE = CompiledEnvelope(
    channels={
        TOP: ChannelEnvelope(role="top", max_abs_v=3.0, max_abs_i=None, function="wgfmu"),
        BOTTOM: ChannelEnvelope(role="bottom", max_abs_v=3.0, max_abs_i=None, function="wgfmu"),
        SMU: ChannelEnvelope(role="bias", max_abs_v=1.0, max_abs_i=1e-3, function="bias_v", v_start=0.5, v_stop=0.5),
    },
    routes=frozenset({RSU201, RSU202}),
    waveform={TOP: wg_limits(total_time_s=1e-3), BOTTOM: wg_limits(total_time_s=1e-3)},
)
FLEX_ENVELOPE = CompiledEnvelope(channels={SMU: ENVELOPE.channels[SMU]})
"""The FLEX part of the envelope (the source-record invariant of ``safety/helpers`` reads SMU commands only)."""


def wg_scenario(**extra: Any) -> SimScenario:
    """The ``wg_resistors`` scenario (module docstring), noiseless, instant timing."""
    return SimScenario.model_validate({
        "name": "wg_resistors", "idn": "Keysight Technologies,B1500A,0,A.06.02.2023.0401", "slots": LAB_SLOTS,
        "wiring": {"r_wg": {"a": TOP, "b": BOTTOM}, "r_smu": {"a": SMU, "b": "GNDU"}},
        "models": {"r_wg": {"model": "resistor", "params": {"r_ohm": R_WG_OHM}},
                   "r_smu": {"model": "resistor", "params": {"r_ohm": R_SMU_OHM}}},
        "noise": {"floor_a": {}, "rel": 0.0, "seed": 7}, **extra,
    })


def program(**changes: Any) -> WaveformProgram:
    """The two-channel program of ``rules_factory_v2.wave`` (201: 3 V triangle pair, voltage measured; 202: 0 V,
    current measured; 400 points per pattern, 10 sequences: 40 us, 4,000 values per channel)."""
    return WaveformProgram.model_validate(wave(**changes))


class SpyWgfmu:
    """Proxy of the simulated library (module docstring); ``inner`` = the ``SimWgfmu`` (``unwrap`` reaches it)."""

    def __init__(self, inner: SimWgfmu) -> None:
        self.inner = inner
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.actions: dict[str, Callable[[], None]] = {}

    def fire(self, moment: str) -> None:
        action = self.actions.pop(moment, None)
        if action is not None:
            action()

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.inner, name)
        if not callable(target) or name.startswith("_"):
            return target

        def call(*args: Any) -> Any:
            self.fire(f"before:{name}")
            self.calls.append((name, args))
            result = target(*args)
            self.fire(f"after:{name}")
            return result

        return call

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class WgHook(HookTransport):
    """``HookTransport`` that records ``(command, exclusive lock held)`` at every write."""

    def __init__(self, inner: SimTransport) -> None:
        super().__init__(inner)
        self.writes: list[tuple[str, bool]] = []

    def write(self, cmd: str) -> None:
        self.writes.append((cmd, self.inner.locked))
        super().write(cmd)


@dataclass
class WgHarness:
    """One simulator session with both links spied (module docstring)."""

    session: Session
    sim: SimTransport
    hook: WgHook
    spy: SpyWgfmu
    daily: MemoryAuditSink
    state_dir: Path
    run: MemoryRun = field(default_factory=MemoryRun)
    tx: Transaction | None = None

    @property
    def library(self) -> SimWgfmu:
        return self.spy.inner

    def transaction(self, *, envelope: CompiledEnvelope | None = ENVELOPE, run: bool = True,
                    intent: str = "safety wgfmu", **kwargs: Any) -> Transaction:
        return self.session.transaction(intent=intent, envelope=envelope, run=self.run if run else None,
                                        plan_id=PLAN_ID, **kwargs)

    def events(self, *, run: bool = True) -> list[AuditEvent]:
        return self.run.audit.events if run else self.daily.events


def make_wg_harness(state_dir: Path, scenario: SimScenario | None = None, *, wgfmu: bool = True,
                    settings: dict[str, Any] | None = None) -> WgHarness:
    """A harness over ``wg_scenario()`` (or ``scenario``); ``wgfmu=False`` builds a bus without a library (the
    ``wgfmu_dll_missing`` fault active from the start); ``settings`` are extra ``settings.yaml`` fields."""
    scenario = scenario or wg_scenario()
    sim = SimTransport(scenario, state_file=sim_state_file(state_dir, scenario.name))
    hook = WgHook(sim)
    daily = MemoryAuditSink()
    spy = SpyWgfmu(SimWgfmu(sim.instrument, flex_locked=lambda: sim.locked))
    bus = Bus(flex=AuditingTransport(hook, daily), wgfmu=AuditingWgfmu(spy, daily, backend="sim") if wgfmu else None)
    cfg = Settings.model_validate({"sim": {"scenario": scenario.name}, **(settings or {})})
    session = Session(cfg, lambda: bus, daily, state_dir=state_dir, switches=lab_station().switches)
    return WgHarness(session=session, sim=sim, hook=hook, spy=spy, daily=daily, state_dir=state_dir)


def body(tx: Transaction, h: WgHarness, prog: WaveformProgram | None = None, *, bias: bool = True,
         leave_connected: bool = False, flex_io: bool = True) -> WgfmuBlock | None:
    """The WGFMU body: (FLEX) SMU3 on at 0.5 V, then the phase: load, run, read; with ``leave_connected`` the body
    connects both channels and returns before running (the phase exit must disconnect them)."""
    if bias:
        tx.driver.enable([SMU])
        tx.driver.force_v(SMU, 0.5, icomp=1e-3)
    with tx.wgfmu_phase(flex_io=flex_io) as wg:
        wg.load(prog or program())
        if leave_connected:
            wg.connect(TOP)
            wg.connect(BOTTOM)
            return None
        return wg.run(check_abort=tx.check_abort)


# -- invariant --------------------------------------------------------------------------------------------------------


def library_levels(spy: SpyWgfmu) -> list[float]:
    """Every level that reached the simulated library: pattern ``v0``, vector levels, DC levels."""
    levels: list[float] = []
    for name, args in spy.calls:
        if name == "create_pattern":
            levels.append(float(args[1]))
        elif name == "add_vectors":
            levels.extend(float(v) for v in args[2])
        elif name == "dc_force_voltage":
            levels.append(float(args[1]))
    return levels


def assert_lock_windows(events: list[AuditEvent]) -> None:
    """Library calls ran only while the FLEX exclusive lock was released, and every release inside the transaction was
    followed by a successful relock before the transaction's final unlock (or the link was closed and reopened)."""
    locked = False
    for event in events:
        if event.ev == "bus_lock" and event.error is None:
            locked = True
        elif event.ev in ("bus_unlock", "bus_close"):
            locked = False
        elif event.ev == "wgfmu_call":
            assert not locked, f"library call {event.cmd} while the FLEX link held its exclusive lock"


def relocked_after_library(events: list[AuditEvent]) -> bool:
    """True when a successful ``bus_lock`` follows the last library call (the FLEX link was locked again)."""
    last = max((i for i, e in enumerate(events) if e.ev == "wgfmu_call"), default=None)
    if last is None:
        return True
    return any(e.ev == "bus_lock" and e.error is None for e in events[last + 1:])


def assert_wgfmu_invariant(h: WgHarness, tx: Transaction, *, run: bool = True) -> None:
    """Global invariant v2, WGFMU part (blueprint v2 2.6): nothing outside the envelope reached either link; the
    library ran only with the FLEX lock released; afterwards every WGFMU channel is disconnected and idle, the library
    session is closed and the FLEX link was locked again, or the fault latch is set with ``cleanup_unverified``. The
    cleanup ran in order; lock and in-flight marker are gone."""
    limit = max(env.max_abs_v for ch, env in ENVELOPE.channels.items() if ch in (TOP, BOTTOM))
    assert all(abs(v) <= limit for v in library_levels(h.spy)), "a WGFMU level outside the envelope reached the library"
    assert {args[0] for name, args in h.spy.calls if name == "connect"} <= {TOP, BOTTOM}
    assert_within_envelope(h.sim.instrument.command_log, FLEX_ENVELOPE)
    events = h.events(run=run)
    assert_lock_windows(events)
    assert_cleanup_order(events)
    latched = h.session.fault_latch.get() is not None
    assert tx.cleanup is not None and latched == tx.cleanup.latched_fault
    if latched:
        assert any(e.ev == "cleanup_unverified" for e in events)
    else:
        instrument = h.sim.instrument
        instrument.assert_safe()  # includes: no WGFMU channel connected or running, no library session open
        assert all(not s.connected and not s.running for s in instrument.state.wgfmu.values())
        assert h.library.session is None
        assert relocked_after_library(events), "the FLEX link was not locked again after the library session"
        cleanup_writes = [locked for cmd, locked in h.hook.writes if cmd in ("DZ", "CL")]
        assert cleanup_writes and all(cleanup_writes), "a cleanup DZ/CL went out without the exclusive lock"
    assert h.session.lock.holder() is None and not (h.state_dir / "inflight.json").exists()


# -- child-process target (multiprocessing spawn) ----------------------------------------------------------------------


def crash_inside_wgfmu_phase(state_dir: str, ready: Any) -> None:
    """Enter a transaction and its WGFMU phase, connect both channels and start a long sequencer run, persist the
    simulator state and die without any cleanup: the in-flight marker, the connected RSUs and the running sequencer
    stay behind (the library session dies with the process)."""
    h = make_wg_harness(Path(state_dir))
    tx = h.transaction(run=False, intent="crashing wgfmu body")
    tx.__enter__()
    phase = tx.wgfmu_phase()
    wg = phase.__enter__()
    long = program(sequences={"201": [["drive", 20]], "202": [["sense", 20]]})
    wg.load(long)
    wg.api.update()
    wg.connect(TOP)
    wg.connect(BOTTOM)
    wg.api.execute()
    hooks = state_hooks(h.session.transport)
    assert hooks is not None
    hooks.save_state()
    ready.set()
    os._exit(5)
