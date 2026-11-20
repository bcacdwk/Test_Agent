"""HV-SPGU over the real ``VisaTransport`` (blueprint v2 7.1 visa-loop, WP9.1): the lwp configuration B program on
the wire (setup, ``SPUPD``, ``SRP``, ``SPST?`` polls with host waits that pass the simulator's virtual time), the
ALWG pattern/sequence blocks as raw writes after their headers, and cleanup step 2 on the hardware path (``SPST?`` ->
``SPP``, verification ``LOP?`` + ``SPST?``; ``spgu_no_stop``: latched unless the retry's ``SPP`` verifies)."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.driver.errors import SpguStillActive
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.sim import SpguNoStop
from b1500_test_agent.models.sources import pulse_envelope
from b1500_test_agent.models.spgu import AlwgChannel, AlwgPattern, AlwgProgram, AlwgVector, SpguProgram
from tests.sim.spgu_helpers import fefet_on_spgu
from tests.unit.test_driver_spgu_ops import LWP_B_SETUP
from tests.unit.test_models_spgu import lwp_config_b
from tests.visa_loop.loop import LoopBus
from tests.visa_loop.test_faults_visa import visa_harness

pytestmark = pytest.mark.spgu


def envelope(program: SpguProgram) -> CompiledEnvelope:
    channels = {}
    for ch, trains in program.trains().items():
        pulse = pulse_envelope(trains, source_ohm=50.0)
        channels[ch] = ChannelEnvelope(role=f"pgu{ch}", max_abs_v=pulse.max_abs_v_dut, max_abs_i=None,
                                       function="pgu", pulse=pulse)
    return CompiledEnvelope(channels=channels)


def run_program(tmp_path: Path, program: SpguProgram, *, fault: SpguNoStop | None = None,
                timeout_s: float = 1.0) -> tuple[object, LoopBus, BaseException | None]:
    bus = LoopBus(tmp_path / "bus", fefet_on_spgu())
    h = visa_harness(tmp_path / "state", bus)
    if fault is not None:
        bus.inject(fault)
    raised: BaseException | None = None
    tx = h.session.transaction(intent="visa spgu", envelope=envelope(program), run=None)
    try:
        with tx:
            tx.driver.enable(sorted(program.channels))
            if isinstance(program, AlwgProgram):
                tx.driver.configure_alwg(program)
            else:
                tx.driver.configure_pulse(program)
            tx.driver.apply_pulse_setup()
            tx.driver.start_pulses()
            tx.driver.wait_pulses_stopped(timeout_s=timeout_s, poll_s=0.01, check=tx.check_abort)
    except BaseException as exc:  # noqa: BLE001 - asserted by the tests
        raised = exc
    assert not h.session.bus_open and bus.lock_is_free()
    return tx, bus, raised


def test_lwp_configuration_b_runs_on_visa_and_the_cleanup_verifies(tmp_path: Path) -> None:
    tx, bus, raised = run_program(tmp_path, lwp_config_b())
    assert raised is None
    ok = [r.command for r in bus.instrument.command_log if r.outcome == "ok"]
    start = ok.index(LWP_B_SETUP[0])
    assert ok[start:start + len(LWP_B_SETUP)] == LWP_B_SETUP
    assert ok[start + len(LWP_B_SETUP):start + len(LWP_B_SETUP) + 2] == ["SPUPD 101,102", "SRP"]
    assert ok[-6:] == ["SPST?", "DZ", "CL", "ERRX?", "LOP?", "SPST?"] and "SPP" not in ok
    assert bus.instrument.clock >= 2e-5  # the polls' host waits let the 2 x 10 us train end
    assert tx.cleanup.verified == "lop" and not tx.cleanup.latched_fault  # type: ignore[attr-defined]
    run = bus.instrument.spgu_runs[-1]
    assert run.end_s == pytest.approx(2e-5) and set(run.channels) == {1, 102}


def test_alwg_blocks_go_out_as_raw_writes(tmp_path: Path) -> None:
    pattern = AlwgPattern(initial_v=0.0, vectors=[AlwgVector(dt_s=1e-6, v=3.0), AlwgVector(dt_s=1e-6, v=0.0),
                                                  AlwgVector(dt_s=8e-6, v=0.0, switch_closed=False)])
    program = AlwgProgram(sequence=[(1, 10)], count=5,
                          channels={101: AlwgChannel(load_ohm=1e6, patterns=[pattern], pulse_switch=True)})
    tx, bus, raised = run_program(tmp_path, program)
    assert raised is None
    log = [(r.mnemonic, r.outcome) for r in bus.instrument.command_log]
    alw, als = log.index(("ALW", "ok")), log.index(("ALS", "ok"))
    assert log[alw + 1] == ("<block>", "ok") and log[als + 1] == ("<block>", "ok")
    assert bus.instrument.spgu_runs[-1].end_s == pytest.approx(5 * 10 * 10e-6)
    assert tx.cleanup.verified == "lop"  # type: ignore[attr-defined]


def test_an_spgu_that_ignores_one_spp_is_stopped_by_the_retry(tmp_path: Path) -> None:
    tx, bus, raised = run_program(tmp_path, lwp_config_b(), fault=SpguNoStop(spp_ignored=1), timeout_s=0.05)
    assert isinstance(raised, SpguStillActive)
    report = tx.cleanup  # type: ignore[attr-defined]
    assert report.verified == "lop" and not report.latched_fault
    assert [(s.attempt, s.step, s.ok) for s in report.steps if s.step in ("spgu_stop", "verify")] == [
        (1, "spgu_stop", True), (1, "verify", False), (2, "spgu_stop", True), (2, "verify", True)]
    assert [r.mnemonic for r in bus.instrument.command_log if r.outcome == "ok"].count("SPP") == 2
    assert not bus.instrument.spgu_output_active()


def test_an_spgu_that_never_stops_latches_the_fault(tmp_path: Path) -> None:
    tx, _bus, raised = run_program(tmp_path, lwp_config_b(), fault=SpguNoStop(), timeout_s=0.05)
    assert isinstance(raised, SpguStillActive)
    report = tx.cleanup  # type: ignore[attr-defined]
    assert report.verified == "unverified" and report.latched_fault
    assert "SPGU output still active" in [s.detail for s in report.steps if s.step == "verify"][-1]
