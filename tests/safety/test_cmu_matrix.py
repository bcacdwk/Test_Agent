"""MFCMU safety matrix with the global invariant v2 (blueprint v2 2.6, 4.3, 8.1 ``safety/``; WP8.1).

The body is an MFCMU C-V acquisition written against the guarded driver (kinds arrive with WP8.2/8.3): ``FMT 1,1``,
``CN 7``, the signal (``FC``/``ACV``/``DCV``), hook ``configure``, the ``MM 18`` sweep setup, ``XE`` (hook
``after_xe``), the read (hook ``during_read``) parsed into ``CmuReading``s. Faults {``cmu_overload`` excess current /
saturation, ``cmu_correction_lost``, ``timeout``, ``garbage_data``, ``disconnect``, ``ignore_dz`` on the MFCMU,
``cleanup_failure``, KeyboardInterrupt, ``EnvelopeViolation``} x positions {configure, after XE, during read, during
cleanup}. Global invariant v2 (MFCMU part): after any exit the MFCMU is at DC 0 V, AC 0 V rms and ``CL`` (with every
SMU at 0 V and ``CL``), or the fault latch is set with ``cleanup_unverified``; no MFCMU source command outside the
compiled envelope (channel, frequency, AC level, DC bias) ever reached the transport; the cleanup runs in order and
zeroes the MFCMU (``DCV 0``, ``ACV 0``) before ``DZ``/``CL``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops.cmu import CmuBlock, CmuSignal, CvSweepSetup
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.sim import (
    CleanupFailure,
    CmuCorrectionLost,
    CmuOverload,
    Disconnect,
    GarbageData,
    IgnoreDz,
    SimFault,
    TimeoutFault,
)
from b1500_test_agent.session import CleanupUnverified, Transaction
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from b1500_test_agent.transport.sim.state import CommandRecord
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order, make_harness
from tests.sim.helpers import load_scenario, noiseless

pytestmark = pytest.mark.cmu

CMU = 7
AC = AcEnvelope(max_vrms=0.05, max_dc_v=2.0, f_min_hz=1e4, f_max_hz=1e6)
ENVELOPE = CompiledEnvelope(channels={CMU: ChannelEnvelope(role="a", max_abs_v=2.0, max_abs_i=1e-3,
                                                           function="cmu_high", ac=AC)})
SWEEP = CvSweepSetup(channel=CMU, start=-1.0, stop=1.0, points=11, freq_hz=1e5, ac_vrms=0.03)
POSITIONS = ("configure", "after_xe", "during_read", "during_cleanup")
FAULTS = ("cmu_excess_current", "cmu_saturation", "cmu_correction_lost", "timeout", "garbage_data", "disconnect",
          "ignore_dz", "cleanup_failure", "keyboard_interrupt", "envelope_violation")
C, A, R, X = "configure", "after_xe", "during_read", "cleanup"


def harness(tmp_path: Path) -> Harness:
    return make_harness(tmp_path, noiseless(load_scenario("capacitor_100p")))


def acquire_cmu(tx: Transaction, hook: HookTransport) -> CmuBlock:
    """The test-local MFCMU body: signal, C-V sweep setup through the guarded driver, ``XE``, read."""
    driver = tx.driver
    driver.set_format(1, 1)
    driver.enable([CMU])
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03, dc_v=0.5))
    hook.fire("configure")
    driver.cv_sweep(SWEEP)
    tx.mark("configured")
    block = driver.measure_cmu(driver.cmu_layout(18), steps=SWEEP.steps, timeout_s=5.0)
    tx.mark("read")
    return block


CMU_SOURCES = {"ACV", "DCV", "WDCV", "WACV", "PDCV", "PWDCV", "MDCV"}


def assert_cmu_within_envelope(log: list[CommandRecord], envelope: CompiledEnvelope = ENVELOPE) -> None:
    """No MFCMU source or frequency outside ``envelope`` reached the transport (dropped records included)."""
    for record in log:
        if record.mnemonic not in CMU_SOURCES | {"FC", "WFC"}:
            continue
        channel = int(record.args[0])
        env = envelope.channels.get(channel)
        assert env is not None and env.ac is not None, f"MFCMU command outside the allowlist: {record.command}"
        values = [float(a) for a in record.args[1:]]
        if record.mnemonic in ("WDCV", "WFC", "WACV"):
            values = values[1:3]  # start, stop
        elif record.mnemonic == "PWDCV":
            values = values[1:4]  # base, start, stop
        if record.mnemonic in ("FC", "WFC"):
            assert all(env.ac.f_min_hz <= v <= env.ac.f_max_hz for v in values), record.command
        elif record.mnemonic in ("ACV", "WACV"):
            assert all(0 <= v <= env.ac.max_vrms for v in values), record.command
        else:
            assert all(abs(v) <= env.ac.max_dc_v for v in values), record.command


def assert_cmu_invariant(h: Harness) -> None:
    """The global invariant v2 for an MFCMU transaction (module docstring)."""
    log = h.log
    assert_cmu_within_envelope(log)
    assert not [r for r in log if r.mnemonic in ("DV", "WV")], "an SMU source command in an MFCMU-only body"
    events = h.events()
    latched = h.session.fault_latch.get() is not None and any(e.ev == "cleanup_unverified" for e in events)
    reached = [r for r in log if r.source and r.outcome != "dropped"]
    if reached and not latched:
        last = reached[-1].seq
        after = {r.mnemonic for r in log if r.seq > last and r.outcome == "ok"}
        assert {"DZ", "CL"} <= after, f"DZ/CL missing after the last source command: {sorted(after)}"
        h.sim.instrument.assert_safe()  # every channel off at 0 V; the MFCMU also at AC 0 V rms
    assert h.session.lock.holder() is None and not h.session.lock.is_held()
    assert not (h.state_dir / "inflight.json").exists()
    assert_cleanup_order(events)
    assert [e.ev for e in events].count("lock_released") == 1
    reads = [e.resp for e in events if e.ev == "read" and e.error is None]
    assert reads == h.run.raw, "a raw block read from the instrument was not handed to the run"


@dataclass(frozen=True)
class Case:
    moment: str
    inject: Callable[[Harness], None]
    raises: type[BaseException] | None = None
    latched: bool = False


def sim(fault: SimFault) -> Callable[[Harness], None]:
    return lambda h: h.sim.inject(fault)


def interrupt(_h: Harness) -> None:
    raise KeyboardInterrupt


def arm_interrupt(h: Harness) -> None:
    h.hook.raise_next = KeyboardInterrupt()


def buggy_ac(h: Harness) -> None:
    """A buggy kind asks for 0.2 V rms (envelope 0.05): the guard refuses before writing."""
    assert h.tx is not None
    h.tx.driver.set_cmu_ac(CMU, 0.2)


def arm_violation(h: Harness) -> None:
    try:
        OutputGuard(ENVELOPE).check_ac(CMU, 0.2, 0.0, 1e5)
    except EnvelopeViolation as exc:
        h.hook.raise_next = exc


INJECTIONS: dict[tuple[str, str], Case] = {
    # excess current at the first / middle / last step: error 320, the MFCMU output switched off, the rest dummy data
    ("cmu_excess_current", "configure"): Case(C, sim(CmuOverload(at_step=0, condition="excess_current"))),
    ("cmu_excess_current", "after_xe"): Case(C, sim(CmuOverload(at_step=5, condition="excess_current"))),
    ("cmu_excess_current", "during_read"): Case(C, sim(CmuOverload(at_step=10, condition="excess_current"))),
    ("cmu_excess_current", "during_cleanup"): Case(X, sim(CmuOverload(at_step=0, condition="excess_current"))),
    # IV amplifier saturation: status D, the automatic abort fills the rest and returns the bias to the start
    ("cmu_saturation", "configure"): Case(C, sim(CmuOverload(at_step=0))),
    ("cmu_saturation", "after_xe"): Case(C, sim(CmuOverload(at_step=5, condition="unbalance"))),
    ("cmu_saturation", "during_read"): Case(C, sim(CmuOverload(at_step=10))),
    ("cmu_saturation", "during_cleanup"): Case(X, sim(CmuOverload(at_step=0))),
    # the module forgets its corrections after a setup command, the trigger, a query of the cleanup, CL
    ("cmu_correction_lost", "configure"): Case(C, sim(CmuCorrectionLost(after_cmd="WDCV"))),
    ("cmu_correction_lost", "after_xe"): Case(C, sim(CmuCorrectionLost(after_cmd="XE"))),
    ("cmu_correction_lost", "during_read"): Case(R, sim(CmuCorrectionLost(after_cmd="LOP?"))),
    ("cmu_correction_lost", "during_cleanup"): Case(X, sim(CmuCorrectionLost(after_cmd="CL"))),
    # WDCV hangs (later commands held), XE never completes, the read times out, DZ hangs (retry after clear)
    ("timeout", "configure"): Case(C, sim(TimeoutFault(on="WDCV")), raises=TransportTimeout),
    ("timeout", "after_xe"): Case(C, sim(TimeoutFault(on="XE")), raises=TransportTimeout),
    ("timeout", "during_read"): Case(C, sim(TimeoutFault(on="read")), raises=TransportTimeout),
    ("timeout", "during_cleanup"): Case(X, sim(TimeoutFault(on="DZ"))),
    ("garbage_data", "configure"): Case(C, sim(GarbageData(at_step=0)), raises=FlexParseError),
    ("garbage_data", "after_xe"): Case(C, sim(GarbageData(at_step=5)), raises=FlexParseError),
    ("garbage_data", "during_read"): Case(C, sim(GarbageData(at_step=10)), raises=FlexParseError),
    ("garbage_data", "during_cleanup"): Case(X, sim(GarbageData(at_step=0))),
    ("disconnect", "configure"): Case(C, sim(Disconnect(after_writes=1)), raises=TransportError, latched=True),
    ("disconnect", "after_xe"): Case(A, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", "during_read"): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", "during_cleanup"): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified,
                                           latched=True),
    # a stuck MFCMU output: the verification fails and latches
    ("ignore_dz", "configure"): Case(C, sim(IgnoreDz(channels=[CMU])), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "after_xe"): Case(A, sim(IgnoreDz(channels=[CMU])), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_read"): Case(R, sim(IgnoreDz(channels=[CMU])), raises=CleanupUnverified, latched=True),
    ("ignore_dz", "during_cleanup"): Case(X, sim(IgnoreDz(channels=[CMU])), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "configure"): Case(C, sim(CleanupFailure(count=1))),
    ("cleanup_failure", "after_xe"): Case(A, sim(CleanupFailure(count=2))),
    ("cleanup_failure", "during_read"): Case(R, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", "during_cleanup"): Case(X, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("keyboard_interrupt", "configure"): Case(C, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", "after_xe"): Case(A, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_read"): Case(R, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", "during_cleanup"): Case(X, arm_interrupt, raises=KeyboardInterrupt),
    ("envelope_violation", "configure"): Case(C, buggy_ac, raises=EnvelopeViolation),
    ("envelope_violation", "after_xe"): Case(A, buggy_ac, raises=EnvelopeViolation),
    ("envelope_violation", "during_read"): Case(R, buggy_ac, raises=EnvelopeViolation),
    ("envelope_violation", "during_cleanup"): Case(X, arm_violation),
}


def test_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_cmu_fault_matrix(fault: str, position: str, tmp_path: Path) -> None:
    case = INJECTIONS[(fault, position)]
    h = harness(tmp_path)
    if case.moment != X:
        h.at(case.moment, lambda: case.inject(h))
    raised: BaseException | None = None
    try:
        with h.transaction(envelope=ENVELOPE, intent="safety mfcmu") as tx:
            h.tx = tx
            acquire_cmu(tx, h.hook)
            if case.moment == X:
                case.inject(h)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc

    assert_cmu_invariant(h)
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup is not None
    assert (h.session.fault_latch.get() is not None) == case.latched
    assert (tx.cleanup.verified == "unverified") == case.latched
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"
        assert all(state == "off" for state in tx.cleanup.outputs_after.values())
    if fault == "cmu_excess_current" and position != "during_cleanup":
        assert 320 in [e.code for e in tx.cleanup.errors]  # drained into the cleanup report
    if fault == "cmu_correction_lost":
        state = h.sim.instrument.state
        assert state.cmu_corrections == {} and state.cmu_phase_results == {}
        assert all(not p.freqs and not p.data and not p.standards for p in state.cmu.values())


def test_cleanup_zeroes_the_mfcmu_before_dz_and_cl(tmp_path: Path) -> None:
    h = harness(tmp_path)
    with h.transaction(envelope=ENVELOPE, intent="safety mfcmu") as tx:
        acquire_cmu(tx, h.hook)
    commands = [r.command for r in h.log]
    tail = commands[commands.index("LOP?"):]
    assert tail[:5] == ["LOP?", f"DCV {CMU},0", f"ACV {CMU},0", "DZ", "CL"]
    zero = next(s for s in tx.cleanup.steps if s.step == "zero")  # type: ignore[union-attr]
    assert zero.ok and "MFCMU 7 DC 0 V, AC 0 V" in zero.detail
    assert_cmu_invariant(h)


def test_an_mfcmu_left_on_by_another_process_is_made_safe_by_safe_shutdown(tmp_path: Path) -> None:
    """A new driver knows no MFCMU it drove; the instrument-wide ``DZ`` and ``CL`` still leave the MFCMU at DC 0 V,
    AC 0 V rms and off (PG p397 (4-79), p382 (4-64)), and the verification covers the AC level."""
    h = harness(tmp_path)
    with h.transaction(envelope=ENVELOPE, intent="leave it on") as tx:
        tx.driver.enable([CMU])
        tx.driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03, dc_v=1.0))
        state = h.sim.instrument.export_state()
    h.sim.instrument.import_state(state)  # as if the transaction had died with the MFCMU on (state persisted)
    h.sim.save_state()
    assert h.sim.instrument.unsafe_reasons()
    report = h.session.safe_shutdown(reason="operator")
    assert report.verified == "sim_state"
    h.sim.instrument.assert_safe()
