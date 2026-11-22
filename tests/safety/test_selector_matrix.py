"""Selector route fault matrix with the global invariant v2 (blueprint v2 2.6, 4.3 ``selector_stuck``, 8.1
``safety/``; WP9.2 AC "selectors at rest after every fault position", "``selector_stuck`` -> ``cleanup_unverified``").

Two test-local bodies run inside a transaction on ``fefet_lab`` (the FeFET gate on SEL1.OUT1, port 0) with the station
selectors SEL1/SEL2 declared (``tests/sim/selector_helpers.SELECTORS``):

- **route-only** (kind ``spgu_pulse`` ``route_only``, the selector check): SEL1.OUT1 through SMU on, PGU on, PGU open
  and back to open, each through ``Transaction.apply_routes`` (guarded, settle time, read-back) with a host-wait dwell;
- **program/read**: SEL1.OUT1 -> PGU, a guarded SPGU train on 101 (polled to its end), SEL1.OUT1 -> SMU, the guarded
  SMU levels of the read, the gate route back to open.

Faults {``selector_stuck`` on PGU (the relay will not leave the PGU path) and open (it will not close), ``disconnect``,
``cleanup_failure`` (once / always), ``timeout`` on ``ERSSP?``, Ctrl-C, a buggy unplanned route} x positions {before
the first route, right after a route write, during the dwell, during the cleanup (the body leaves SEL1.OUT1 on PGU)}.
Every case asserts the invariant: no ``ERSSP`` outside the plan's routes or a rest state ever reached the instrument,
the cleanup ran its steps in order with ``routes`` in every attempt, the lock and the marker are gone, and either the
simulator is safe with every selector port open (``cleanup.switches_after`` all open) or the fault latch is set with
``cleanup_unverified`` audited.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import StressMeasureKind
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.errors import RouteNotVerified
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope, PlanRequest
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sim import CleanupFailure, Disconnect, SelectorStuck, SimFault, TimeoutFault
from b1500_test_agent.models.sources import pulse_envelope
from b1500_test_agent.models.spgu import SpguChannel, SpguPulseProgram, SpguSource
from b1500_test_agent.session import CleanupUnverified, Transaction
from b1500_test_agent.transport.base import TransportError, TransportTimeout
from tests.safety.helpers import Harness, HookTransport, assert_cleanup_order, make_harness
from tests.sim.helpers import load_scenario, noiseless
from tests.sim.selector_helpers import DRAIN_SMU, GATE_SMU, PGU, SELECTORS, recorded_station, selector_states
from tests.unit.rules_factory import T0, bundle, dut, engine, pin_map, station

pytestmark = pytest.mark.spgu

REPO_ROOT = Path(__file__).resolve().parents[2]

CHECK = [Route(switch="SEL1", output="OUT1", state=s) for s in ("smu", "pgu", "pgu_open", "open")]
TO_PGU, TO_SMU, TO_OPEN = CHECK[1], CHECK[0], CHECK[3]
TRAIN = SpguPulseProgram(period_s=1e-4, count=10, channels={
    PGU: SpguChannel(load_ohm=1e6, sources={1: SpguSource(width_s=1e-5, base_v=0.0, peak_v=4.5)})})
PULSE = pulse_envelope(TRAIN.trains()[PGU], source_ohm=50.0)
ROUTE_ENVELOPE = CompiledEnvelope(channels={}, routes=frozenset(CHECK[:3]))
READ_ENVELOPE = CompiledEnvelope(channels={
    PGU: ChannelEnvelope(role="gate", max_abs_v=PULSE.max_abs_v_dut, max_abs_i=None, function="pgu", pulse=PULSE),
    GATE_SMU: ChannelEnvelope(role="gate", max_abs_v=1.0, max_abs_i=1e-4),
    DRAIN_SMU: ChannelEnvelope(role="drain", max_abs_v=0.2, max_abs_i=1e-3),
}, routes=frozenset({TO_PGU, TO_SMU}))
ALLOWED = {(0, 0), (1, 0), (2, 0), (3, 0), (0, 1), (0, 2), (0, 3)}
"""(port, status) every ``ERSSP`` may carry: the planned SEL1.OUT1 routes and every port's rest state (open)."""


class RouteHook(HookTransport):
    """Fires ``after_route`` right after the first non-rest ``ERSSP`` write and ``during_dwell`` at the first host
    wait after it (the selector settle time / the dwell)."""

    routed = False

    def write(self, cmd: str) -> None:
        super().write(cmd)
        if cmd.startswith("ERSSP") and not cmd.endswith(",0") and not self.routed:
            self.routed = True
            self.fire("after_route")

    def wait(self, seconds: float) -> None:
        if self.routed:
            self.fire("during_dwell")
        super().wait(seconds)


def selector_harness(state_dir: Path) -> Harness:
    return make_harness(state_dir, noiseless(load_scenario("fefet_lab")), hook_type=RouteHook, switches=SELECTORS)


def route_only(tx: Transaction, h: Harness, *, leave_switched: bool = False) -> None:
    """The selector check of SEL1.OUT1 (module docstring); ``leave_switched`` stops on PGU."""
    h.hook.fire("configure")
    for route in CHECK[:2] if leave_switched else CHECK:
        tx.apply_routes([route], phase=f"check-{route.state}")
        tx.driver.host_wait(0.05)
        tx.checkpoint(CHECK.index(route) + 1, len(CHECK), "route")


def program_read(tx: Transaction, h: Harness, *, leave_switched: bool = False) -> None:
    """Program through the PGU path, read through the SMU path (module docstring); ``leave_switched`` stops after
    the program with the gate still on PGU."""
    driver: B1500Driver = tx.driver
    h.hook.fire("configure")
    tx.apply_routes([TO_PGU], phase="program")
    driver.enable([PGU])
    driver.configure_pulse(TRAIN)
    driver.apply_pulse_setup()
    driver.start_pulses()
    driver.wait_pulses_stopped(timeout_s=0.1, poll_s=0.001, check=tx.check_abort)
    if leave_switched:
        return
    tx.apply_routes([TO_SMU], phase="read")  # the selector parts the pad from the idle SPGU output (0 V base)
    driver.enable([GATE_SMU, DRAIN_SMU])
    driver.force_v(GATE_SMU, 0.8, icomp=1e-4)
    driver.force_v(DRAIN_SMU, 0.1, icomp=1e-3)
    tx.apply_routes([TO_OPEN], phase="rest")


BODIES: dict[str, tuple[Callable[..., None], CompiledEnvelope]] = {
    "route_only": (route_only, ROUTE_ENVELOPE), "program_read": (program_read, READ_ENVELOPE),
}


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


def unplanned_route(h: Harness) -> None:
    """A buggy body switches SEL1.OUT2 to the PGU: not a route of the plan."""
    assert h.tx is not None
    h.tx.apply_routes([Route(switch="SEL1", output="OUT2", state="pgu")], phase="bug")


C, R, D, X = "configure", "after_route", "during_dwell", "cleanup"
POSITIONS = (C, R, D, X)
STUCK_PGU, STUCK_OPEN = SelectorStuck(port=0, state="pgu"), SelectorStuck(port=0, state="open")

INJECTIONS: dict[tuple[str, str], Case] = {
    # the relay will not leave the PGU path: the read-back refuses the next route; nothing returns it -> latched
    ("selector_stuck_pgu", C): Case(C, sim(STUCK_PGU), raises=RouteNotVerified, latched=True),
    ("selector_stuck_pgu", R): Case(R, sim(STUCK_PGU), raises=RouteNotVerified, latched=True),
    ("selector_stuck_pgu", D): Case(D, sim(STUCK_PGU), raises=RouteNotVerified, latched=True),
    ("selector_stuck_pgu", X): Case(X, sim(STUCK_PGU), raises=CleanupUnverified, latched=True),
    # the relay will not close: the route is refused by its read-back, the output stays at rest -> verified
    ("selector_stuck_open", C): Case(C, sim(STUCK_OPEN), raises=RouteNotVerified),
    ("selector_stuck_open", R): Case(R, sim(STUCK_OPEN), raises=RouteNotVerified),
    ("selector_stuck_open", D): Case(D, sim(STUCK_OPEN), raises=RouteNotVerified),
    ("selector_stuck_open", X): Case(X, sim(STUCK_OPEN)),
    # the link drops: nothing reaches the instrument any more -> latched
    ("disconnect", C): Case(C, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", R): Case(R, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", D): Case(D, sim(Disconnect(after_writes=0)), raises=TransportError, latched=True),
    ("disconnect", X): Case(X, sim(Disconnect(after_writes=1)), raises=CleanupUnverified, latched=True),
    # DZ/CL time out once (the retry verifies) or always (latched)
    ("cleanup_failure", C): Case(C, sim(CleanupFailure(count=1))),
    ("cleanup_failure", R): Case(R, sim(CleanupFailure(count=2))),
    ("cleanup_failure", D): Case(D, sim(CleanupFailure()), raises=CleanupUnverified, latched=True),
    ("cleanup_failure", X): Case(X, sim(CleanupFailure(count=1))),
    # the read-back never answers: the route fails; the cleanup's device clear and retry verify
    ("timeout", C): Case(C, sim(TimeoutFault(on="query:ERSSP?")), raises=TransportTimeout),
    ("timeout", R): Case(R, sim(TimeoutFault(on="query:ERSSP?")), raises=TransportTimeout),
    ("timeout", D): Case(D, sim(TimeoutFault(on="query:ERSSP?")), raises=TransportTimeout),
    ("timeout", X): Case(X, sim(TimeoutFault(on="query:ERSSP?"))),
    # Ctrl-C while switched
    ("keyboard_interrupt", C): Case(C, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", R): Case(R, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", D): Case(D, interrupt, raises=KeyboardInterrupt),
    ("keyboard_interrupt", X): Case(X, lambda h: setattr(h.hook, "raise_next", KeyboardInterrupt()),
                                    raises=KeyboardInterrupt),
    # a buggy body routes outside the plan: refused before the write
    ("envelope_violation", C): Case(C, unplanned_route, raises=EnvelopeViolation),
    ("envelope_violation", R): Case(R, unplanned_route, raises=EnvelopeViolation),
    ("envelope_violation", D): Case(D, unplanned_route, raises=EnvelopeViolation),
    ("envelope_violation", X): Case(X, unplanned_route, raises=EnvelopeViolation),
}
FAULTS = sorted({fault for fault, _ in INJECTIONS})


def test_matrix_is_complete() -> None:
    assert set(INJECTIONS) == {(f, p) for f in FAULTS for p in POSITIONS}


def assert_selector_invariant(h: Harness, tx: Transaction) -> None:
    """Global invariant v2, selector part (module docstring)."""
    for record in h.log:
        if record.mnemonic == "ERSSP":  # every record, dropped ones included: nothing unplanned reached the link
            port, status = (int(a) for a in record.args)
            assert (port, status) in ALLOWED, record.command
    events = h.events()
    assert_cleanup_order(events)
    sequence = [(e.data["attempt"], e.data["step"]) for e in events if e.ev == "cleanup_step" and e.data]
    for attempt in {a for a, _ in sequence}:
        assert (attempt, "routes") in sequence  # the station declares selectors: step 5 in every attempt
    assert tx.cleanup is not None
    latched = h.session.fault_latch.get() is not None
    assert latched == tx.cleanup.latched_fault
    if latched:
        assert any(e.ev == "cleanup_unverified" for e in events)
    else:
        h.sim.instrument.assert_safe()
        assert selector_states(h.sim) == {0: 0, 1: 0, 2: 0, 3: 0}, "a selector port is not at rest"
        assert set(tx.cleanup.switches_after.values()) == {"open"} and len(tx.cleanup.switches_after) == 4
    assert h.session.lock.holder() is None and not (h.state_dir / "inflight.json").exists()


@pytest.mark.parametrize("body_name", sorted(BODIES))
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("fault", FAULTS)
def test_spgu_pulse_selector_fault_matrix(fault: str, position: str, body_name: str, tmp_path: Path) -> None:
    case = INJECTIONS[(fault, position)]
    body, envelope = BODIES[body_name]
    h = selector_harness(tmp_path)
    if case.moment != X:
        h.at(case.moment, lambda: case.inject(h))
    raised: BaseException | None = None
    tx: Transaction | None = None
    try:
        with h.transaction(envelope=envelope, intent=f"safety selector {body_name}") as tx:
            h.tx = tx
            body(tx, h, leave_switched=case.moment == X)
            if case.moment == X:
                case.inject(h)
    except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt is one of the cases
        raised = exc
    assert tx is not None and tx.cleanup is not None
    assert (None if raised is None else type(raised)) is case.raises, f"expected {case.raises}, got {raised!r}"
    assert tx.cleanup.latched_fault == case.latched
    assert_selector_invariant(h, tx)
    if not case.latched:
        assert tx.cleanup.verified == "sim_state"


def test_spgu_pulse_program_read_body_programs_through_pgu_and_reads_through_smu(tmp_path: Path) -> None:
    """Without a fault: the 4.5 V train reached the gate through the PGU path (the FeFET switched), the SMU read went
    through the SMU path, and the cleanup left every port open."""
    h = selector_harness(tmp_path)
    with h.transaction(envelope=READ_ENVELOPE, intent="safety selector") as tx:
        program_read(tx, h)
    assert_selector_invariant(h, tx)
    assert h.sim.instrument.circuit.devices["dut"].p > 0.9  # type: ignore[attr-defined]
    run = h.sim.instrument.spgu_runs[-1]
    assert run.channels[1].delivered_v == pytest.approx(4.5 * (1e6 + 50) / 1e6)  # the gate is an open load
    writes = [r.command for r in h.log if r.outcome == "ok" and r.mnemonic == "ERSSP"]
    assert writes[:3] == ["ERSSP 0,2", "ERSSP 0,1", "ERSSP 0,0"]  # program, read, rest, then the cleanup's rests


# -- composite kinds route through the selector (catalog/blocks.apply_routes, WP9.2) --------------------------------


def test_stress_measure_routes_its_gate_through_the_selector_and_back_to_rest(tmp_path: Path) -> None:
    """``reliability.bti_sms`` with the FeFET gate on SEL1.OUT1 (recorded wiring: SMU3 on its SMU input): the plan
    carries the ``setup`` route, the real kind applies it through ``Transaction.apply_routes`` before ``CN``, every
    read and hold reaches the gate through the selector, and the cleanup returns SEL1.OUT1 to open (verified)."""
    registry = RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)
    cfg = bundle(station_profile=station(switches=recorded_station()["switches"]),
                 pin_maps=[pin_map(gate="SEL1.OUT1", drain=DRAIN_SMU)], duts=[dut()])
    req = PlanRequest.model_validate({
        "recipe_id": "reliability.bti_sms", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic",
        "params": {"vg_stress": 2.0, "stress_time": 30.0, "reads_per_decade": 1, "recovery_time": 10.0}})
    plan = Planner(registry, clock=lambda: T0).plan(req, cfg, engine(cfg))
    assert plan.tier == "needs_confirmation", plan.rules.findings  # destructive (+ the plan stays routed)
    assert plan.routes_by_phase == {"setup": [TO_SMU]} and plan.binding.roles["gate"].channel == GATE_SMU
    assert plan.flex_preview[:2] == ["ERMOD 1", "ERSSP 0,1"]
    h = selector_harness(tmp_path)
    with h.transaction(envelope=plan.envelope, intent="stress through SEL1") as tx:
        raw = StressMeasureKind().acquire(tx, plan)
    assert raw.ok, raw.message
    sent = [r.command for r in h.log if r.outcome == "ok"]
    assert sent.index("ERSSP 0,1") < sent.index("CN 3,4")  # routed before the outputs switch on
    gate_reads = [float(r.args[2]) for r in h.log if r.mnemonic == "DV" and r.args[0] == str(GATE_SMU)]
    assert gate_reads and max(gate_reads) == pytest.approx(2.0)  # the stress level reached SMU3 (behind SEL1)
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"
    assert tx.cleanup.switches_after["SEL1.OUT1"] == "open" and selector_states(h.sim)[0] == 0
