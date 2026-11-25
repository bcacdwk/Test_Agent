"""Harness of the global safety matrix (WP11.3; blueprint v2 2.6 global invariant v2, 4.3 faults, 8.1 ``safety/``).

One **body** per family path of every registered kind: the committed recipe's plan, compiled by the real planner
against the committed config (the station profile with the selector wiring recorded at bring-up L7,
``selector_helpers.recorded_station``), runs through the real kind (``kind.acquire``) inside ONE transaction on the
noiseless committed scenario (``timing: instant``). The session declares every switch of that station (selectors,
RSUs, SCUU, ASUs), so cleanup steps 5 and 8 run in every case, and its bus carries both links with spies:

- ``FlexHook`` sits under the FLEX audit layer, ``LibrarySpy`` under the WGFMU audit layer; both report every bus action
  to one ``Tracker`` (``before``/``after``), which fires the **positions** of the run once each:

  ========== ==========================================================================================================
  configure  the body's first bus action is next (FLEX write/query or library call)
  route      right after the first route reached its link (``ERSSP``/``SSP``/``SAP`` write, RSU ``connect``)
  pulse_on   right after the first pulse or AC output started (``SRP``; ``ACV`` above 0 V rms; an ``XE`` in a pulsed
             measurement mode ``MM`` 3, 4, 5, 19, 20, 27, 28; the WGFMU sequencer's ``execute``)
  execute    the first measurement trigger is next (``XE``, ``SRP``, ``*TST?``/``*CAL?``, ``CORR?``, ``ADJ? ch,1``;
             library ``execute``, ``dc_force_voltage``, ``self_test``, ``self_calibration``)
  readback   the first data read is next (FLEX ``read``; library ``measure_value_size``, ``measure_values``,
             ``dc_measure_value``)
  checkpoint inside the first ``tx.checkpoint`` (a segment boundary; ``tx.check_abort`` calls are counted too)
  cleanup    the body is stopped at its ``stop_at`` position with its outputs live (``StopBody``) and the fault acts
             from the first bus action of the exit on (WGFMU phase exit, then the transaction cleanup)
  ========== ==========================================================================================================

- **faults**: every simulator fault kind (``models.sim.FAULT_KINDS``: the v1 union and the blueprint v2 4.3 additions),
  a recoverable second form of the six whose main form cannot be recovered from (``RECOVERABLE_FORMS``), a Ctrl-C
  (``keyboard_interrupt``), a buggy body asking for more than its envelope allows (``envelope_violation``) and a
  cancel request from another process (``abort_request``; every run carries a ``RunControl`` watching the abort
  file). ``fault_injection`` gives each one concrete form; faults that name "the next" command or library call
  (``errx``, ``timeout``, ``cmu_correction_lost``, ``wgfmu_error``, ``wgfmu_hang``) are armed for the next action on
  their link, so they always act at the position.
- ``assert_global_invariant_v2``: blueprint v2 2.6 (module docstring of ``test_global_matrix``).
"""

from __future__ import annotations

import atexit
import functools
import shutil
import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from b1500_test_agent.catalog.kinds import default_kinds
from b1500_test_agent.catalog.planner import Planner
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.driver.ops.switch import scuu_plan, selector_port
from b1500_test_agent.driver.wgfmu import WgfmuDriver
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.plan import CompiledEnvelope, PlanRecord, PlanRequest
from b1500_test_agent.models.routing import Route, SwitchSpec
from b1500_test_agent.models.sim import (
    FAULT_KINDS,
    AbortIgnored,
    BreakdownAt,
    BusLockedFault,
    CleanupFailure,
    CmuCorrectionLost,
    CmuOverload,
    ComplianceAt,
    Disconnect,
    ErrxFault,
    GarbageData,
    IdnOverride,
    IgnoreDz,
    InterlockOpen,
    ModulesOverride,
    Oscillation,
    RunInterrupt,
    SelectorStuck,
    SimFault,
    Slow,
    SpguLoadMismatch,
    SpguNoStop,
    TimeoutFault,
    WgfmuDisconnectFails,
    WgfmuDllMissing,
    WgfmuErrorFault,
    WgfmuHang,
)
from b1500_test_agent.models.station import Settings, SimScenario
from b1500_test_agent.rules import RulesEngine
from b1500_test_agent.session import Session, Transaction
from b1500_test_agent.session.abort import AbortWatch
from b1500_test_agent.session.runner import RunControl
from b1500_test_agent.transport.audit import AuditingTransport, MemoryAuditSink
from b1500_test_agent.transport.base import Bus
from b1500_test_agent.transport.sim import SimTransport, sim_state_file
from b1500_test_agent.transport.sim.state import CommandRecord
from b1500_test_agent.transport.sim.wgfmu import SimWgfmu
from b1500_test_agent.transport.wgfmu import api
from b1500_test_agent.transport.wgfmu.audit import AuditingWgfmu
from tests.safety.helpers import PLAN_ID, MemoryRun, assert_cleanup_order, assert_within_envelope
from tests.safety.test_cmu_matrix import CMU_SOURCES, assert_cmu_within_envelope
from tests.safety.wgfmu_helpers import assert_lock_windows, relocked_after_library
from tests.sim.helpers import REPO_ROOT, load_scenario, noiseless
from tests.sim.pulse_read_helpers import recipes_with_fixture
from tests.sim.selector_helpers import recorded_station, selector_states
from tests.sim.spgu_pulse_helpers import repo_bundle
from tests.unit.rules_factory import T0

KINDS = tuple(default_kinds())
"""Every registered kind (blueprint v2 2.7: 14)."""

POSITIONS = ("configure", "route", "pulse_on", "execute", "readback", "checkpoint", "cleanup")
"""Blueprint v2 8.1 ``safety/`` positions (module docstring)."""

INJECTED = ("keyboard_interrupt", "envelope_violation", "abort_request")
"""Faults that are not simulator faults: a Ctrl-C (SIGINT), a buggy body asking for a level beyond its envelope, and a
cancel request (``safe_shutdown`` or ``b1500 shutdown`` from any process writes ``abort.json``; the run honours it at
its next boundary, blueprint v2 2.6)."""

RECOVERABLE_FORMS = ("cleanup_failure/once", "spgu_no_stop/once", "wgfmu_disconnect_fails/once", "bus_locked/once",
                     "abort_ignored/once", "selector_stuck/open")
"""Second forms of faults whose main form cannot be recovered from: DZ/CL time out once, one ``SPP`` is ignored, one
``disconnect`` fails, one bus-lock request is refused, one ``AB`` is ignored, a selector output welded open. The
cleanup's retry (device clear, second attempt, WGFMU initialize) must verify the safe state after each of them."""

FAULTS = (*FAULT_KINDS, *RECOVERABLE_FORMS, *INJECTED)
"""Every simulator fault kind (blueprint v2 4.3 and the v1 union), the recoverable forms and the injected faults."""


def base_fault(fault: str) -> str:
    """The fault kind of a fault or of one of its forms (``cleanup_failure/once`` -> ``cleanup_failure``)."""
    return fault.split("/", 1)[0]


PULSED_MODES = frozenset({3, 4, 5, 19, 20, 27, 28})
"""``MM`` modes whose ``XE`` starts pulsed outputs: SMU pulsed spot/sweep/bias (3, 4, 5), multi-channel pulsed (27,
28), MFCMU pulsed spot/sweep (19, 20)."""

ROUTE_WRITES = frozenset({"ERSSP", "SSP", "SAP"})
FLEX_TRIGGERS = frozenset({"XE", "SRP"})
QUERY_TRIGGERS = frozenset({"*TST?", "*CAL?", "CORR?"})
"""Queries that run a measurement: self-test, self-calibration, an MFCMU correction measurement (``CORR?``); and
``ADJ? ch,1`` (phase compensation measured; mode 0 only reads the last result)."""
LIBRARY_TRIGGERS = frozenset({"execute", "dc_force_voltage", "self_test", "self_calibration"})
LIBRARY_READS = frozenset({"measure_value_size", "measure_values", "dc_measure_value"})
LIBRARY_LEVELS = frozenset({"create_pattern", "add_vectors", "dc_force_voltage"})


class StopBody(BaseException):
    """Stops a body at its ``stop_at`` position with its outputs live (position ``cleanup``): a ``BaseException`` so
    that no kind's ``except Exception`` handler can swallow it."""


# -- bodies -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Body:
    """One family path of a kind: ``recipe`` on ``scenario`` with ``request`` (pin map, DUT profile, params).

    ``positions``: the positions a clean run reaches (``test_each_body_reaches_exactly_its_positions`` checks them).
    ``features``: what the body does (``FEATURES``); the fault table reads them. ``stop_at``: where the ``cleanup``
    case stops the body. ``fixture``: a test-only recipe (``tests/fixtures/recipes``)."""

    name: str
    kind: str
    recipe: str
    scenario: str
    request: dict[str, Any]
    positions: frozenset[str]
    features: frozenset[str]
    stop_at: str
    fixture: bool = False


FEATURES = {
    "xe": "triggers FLEX measurements (XE)",
    "smu_data": "reads SMU measurement data over FLEX",
    "flex_data": "reads measurement data over FLEX (SMU or MFCMU blocks)",
    "cmu": "drives the MFCMU",
    "spgu": "starts HV-SPGU outputs",
    "wgfmu": "opens a WGFMU library session",
    "mm10_dielectric": "samples (MM 10) a dielectric device",
    "boundary": "reaches a segment boundary that honours a cancel request (tx.checkpoint or tx.check_abort)",
}

_ALL = frozenset(POSITIONS)


def _positions(*missing: str) -> frozenset[str]:
    return _ALL - set(missing)


FECAP = {"pin_map": "fecap-wgfmu", "dut_profile": "fecap-generic"}
FEFET_SEL = {"pin_map": "fefet-sel", "dut_profile": "fefet-lab"}
MOSFET_4T = {"pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}

BODIES: tuple[Body, ...] = (
    Body("spot", "smu_spot", "generic.smu_spot", "resistor_100k",
         {"pin_map": "resistor-2t", "dut_profile": "resistor-generic", "params": {}},
         _positions("route", "pulse_on"), frozenset({"xe", "smu_data", "flex_data", "boundary"}), "readback"),
    Body("staircase", "smu_staircase", "mosfet.idvg", "nmos_basic", {**MOSFET_4T, "params": {}},
         _positions("route", "pulse_on", "checkpoint"), frozenset({"xe", "smu_data", "flex_data"}), "readback"),
    Body("stepped", "smu_stepped", "mosfet.idvd", "nmos_basic", {**MOSFET_4T, "params": {}},
         _positions("route", "pulse_on"), frozenset({"xe", "smu_data", "flex_data", "boundary"}), "readback"),
    Body("pulsed", "smu_pulsed", "mosfet.idvg_pulsed", "nmos_selfheat",
         {"pin_map": "mosfet-4t", "dut_profile": "nmos-pulsed", "params": {"vd": 3.0}},
         _positions("route"), frozenset({"xe", "smu_data", "flex_data", "boundary"}), "readback"),
    Body("sampling", "smu_sampling", "reliability.tddb_cvs", "dielectric_tddb",
         {"pin_map": "mosfet-4t", "dut_profile": "dielectric-generic",
          "params": {"v_stress": 5.5, "duration": 60.0}},
         _positions("route", "pulse_on"), frozenset({"xe", "smu_data", "flex_data", "mm10_dielectric", "boundary"}),
         "readback"),
    Body("search", "smu_search", "mosfet.vth_search", "nmos_basic", {**MOSFET_4T, "params": {}},
         _positions("route", "pulse_on", "checkpoint"), frozenset({"xe", "smu_data", "flex_data"}), "readback"),
    Body("qscv", "smu_qscv", "moscap.qscv", "moscap_dit",
         {"pin_map": "moscap-scuu", "dut_profile": "moscap-generic", "params": {}},
         _positions("pulse_on", "checkpoint"), frozenset({"xe", "smu_data", "flex_data"}), "readback"),
    Body("cmu_measure", "cmu_measure", "moscap.cv_multi_freq", "moscap_dit",
         {"pin_map": "moscap-scuu", "dut_profile": "moscap-generic",
          "params": {"points": 11, "freqs_hz": [1e5, 1e6]}},
         _ALL, frozenset({"xe", "flex_data", "cmu", "boundary"}), "readback"),
    Body("cmu_correction", "cmu_correction", "cmu.correction_open", "moscap_dit",
         {"pin_map": "moscap-scuu", "params": {}},
         _positions("readback", "checkpoint"), frozenset({"cmu"}), "execute"),
    Body("spgu_train", "spgu_pulse", "spgu.pulse_train", "fefet_lab", {**FEFET_SEL, "params": {}},
         _positions("readback"), frozenset({"spgu", "boundary"}), "pulse_on"),
    Body("charge_pumping", "spgu_pulse", "mosfet.charge_pumping", "nmos_cv",
         {"pin_map": "mosfet-cp", "dut_profile": "nmos-cv", "params": {"frequency": [1e5]}},
         _ALL, frozenset({"xe", "smu_data", "flex_data", "spgu", "boundary"}), "readback"),
    Body("selector_check", "spgu_pulse", "system.selector_check", "lab_station",
         {"pin_map": "fefet-sel", "params": {"dwell_s": 0.0}},
         _positions("pulse_on", "execute", "readback"), frozenset({"boundary"}), "route"),
    Body("stress_smu", "stress_measure", "reliability.bti_sms", "nmos_bti",
         {**MOSFET_4T, "params": {"vg_stress": 2.0, "stress_time": 30.0, "reads_per_decade": 1,
                                  "recovery_time": 10.0}},
         _positions("route", "pulse_on"), frozenset({"xe", "smu_data", "flex_data", "mm10_dielectric", "boundary"}),
         "readback"),
    Body("stress_wgfmu", "stress_measure", "wgfmu.fast_bti", "nmos_bti",
         {"pin_map": "mosfet-wgfmu-body", "dut_profile": "nmos-wgfmu",
          "params": {"vg_stress": 2.0, "stress_time": 0.01, "vb": -0.5}},
         _ALL, frozenset({"xe", "smu_data", "flex_data", "wgfmu", "boundary"}), "readback"),
    Body("pulse_read_spgu", "pulse_read", "fefet.pulse_write_read", "fefet_lab", {**FEFET_SEL, "params": {}},
         _ALL, frozenset({"xe", "smu_data", "flex_data", "spgu", "boundary"}), "readback"),
    Body("pulse_read_smu", "pulse_read", "generic.smu_pulse_read", "fefet_lab", {**FEFET_SEL, "params": {}},
         _ALL, frozenset({"xe", "smu_data", "flex_data", "boundary"}), "readback", fixture=True),
    Body("pulse_read_wgfmu", "pulse_read", "fecap.endurance_pund", "fecap_basic",
         {**FECAP, "params": {"cycles": 100, "reads_per_decade": 1}},
         _ALL, frozenset({"wgfmu", "boundary"}), "readback"),
    Body("waveform", "wgfmu_waveform", "wgfmu.pulsed_iv", "nmos_wgfmu",
         {"pin_map": "mosfet-wgfmu-body", "dut_profile": "nmos-wgfmu", "params": {"vg_points": 4, "vb": -0.5}},
         _ALL, frozenset({"wgfmu", "boundary"}), "readback"),
    Body("waveform_dc", "wgfmu_waveform", "wgfmu.dc_spot", "resistor_100k",
         {"pin_map": "resistor-wgfmu", "dut_profile": "resistor-generic", "params": {}},
         _positions("pulse_on"), frozenset({"wgfmu", "boundary"}), "readback"),
    Body("system", "system", "system.self_test", "nmos_basic", {"pin_map": "mosfet-4t", "params": {}},
         _positions("route", "pulse_on", "readback", "checkpoint"), frozenset(), "execute"),
    Body("system_wgfmu", "system", "system.wgfmu_self_test", "nmos_bti", {"pin_map": "mosfet-wgfmu", "params": {}},
         _positions("route", "pulse_on", "readback", "checkpoint"), frozenset({"wgfmu"}), "execute"),
)
"""The bodies (module docstring); their positions and features are checked against a clean run."""

BODY = {body.name: body for body in BODIES}


@functools.cache
def _work_dir() -> Path:
    """A per-process scratch folder for the compiled plans' configuration copies (never ``config/local``), removed
    when the process ends."""
    path = Path(tempfile.mkdtemp(prefix="b1500-global-matrix-"))
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


@functools.cache
def registry() -> RecipeRegistry:
    """The committed recipes plus the test-only ``generic.smu_pulse_read``."""
    return RecipeRegistry.load(recipes_with_fixture(_work_dir() / "registry"), repo_root=REPO_ROOT)


@functools.cache
def bundle_of(scenario: str) -> ConfigBundle:
    """The committed configuration on ``scenario`` with the selector wiring recorded (bring-up L7)."""
    return repo_bundle(_work_dir() / f"cfg-{scenario}", scenario, station=recorded_station())


@functools.cache
def plan_of(name: str) -> PlanRecord:
    """The body's plan, compiled once per process (not stored)."""
    body = BODY[name]
    cfg = bundle_of(body.scenario)
    req = PlanRequest.model_validate({"recipe_id": body.recipe, **body.request})
    plan = Planner(registry(), clock=lambda: T0).plan(req, cfg, RulesEngine(cfg, clock=lambda: T0))
    blocks = {f.rule_id for f in plan.rules.findings if f.severity == "block"}
    assert blocks <= {"R-CORR-01"}, f"{name}: {plan.summary}"  # correction records live in the data dir, not here
    return plan


def scenario_of(name: str) -> SimScenario:
    """The body's scenario, noiseless, with virtual time only."""
    scenario = noiseless(load_scenario(BODY[name].scenario))
    return scenario.model_copy(update={"timing": "instant"})


# -- positions --------------------------------------------------------------------------------------------------------


@dataclass
class Tracker:
    """Fires the positions of one run (module docstring) and the armed fault actions.

    ``target``/``inject``: the position under test and what happens there. ``stop_at``: the body's stop position
    (only when ``target`` is ``cleanup``). ``reached``: every position the run passed. ``pending``: deferred
    injections for the next action of a link (``flex``/``wgfmu``)."""

    target: str | None = None
    inject: Callable[[], None] | None = None
    stop_at: str | None = None
    phase: str = "setup"
    reached: list[str] = field(default_factory=list)
    pending: dict[str, Callable[[str, str], None]] = field(default_factory=dict)
    boundaries: int = 0
    """``tx.checkpoint``/``tx.check_abort`` calls of the body."""
    mode: int | None = None
    data_modes: set[int | None] = field(default_factory=set)
    """The ``MM`` mode in force at each FLEX data read of the body (``None`` = none set)."""

    def arm(self, link: str, action: Callable[[str, str], None]) -> None:
        self.pending[link] = action

    def _hit(self, position: str) -> None:
        if position in self.reached:
            return
        self.reached.append(position)
        if self.target == "cleanup":
            if position == self.stop_at and self.phase == "body":
                self.phase = "stopped"
                raise StopBody(f"stopped at {position}")
            if position == "cleanup" and self.inject is not None:
                self.inject()
        elif position == self.target and self.inject is not None:
            self.inject()

    def before(self, link: str, op: str, name: str, line: str) -> None:
        """A bus action is next: ``op`` = ``write``/``query``/``read``/``device_clear``/... or ``call`` (library)."""
        deferred = self.pending.pop(link, None)
        if deferred is not None:
            deferred(op, line if link == "flex" else name)
        if self.phase == "stopped":
            self.phase = "cleanup"
            self._hit("cleanup")
            return
        if self.phase != "body":
            return
        self._hit("configure")
        if (link == "flex" and ((op == "write" and name in FLEX_TRIGGERS) or (op == "query" and name in QUERY_TRIGGERS))
                or (link == "flex" and op == "query" and name == "ADJ?" and line.replace(" ", "").endswith(",1"))
                or (link == "wgfmu" and name in LIBRARY_TRIGGERS)):
            self._hit("execute")
        if link == "flex" and op == "read":
            self.data_modes.add(self.mode)
        if (link == "flex" and op == "read") or (link == "wgfmu" and name in LIBRARY_READS):
            self._hit("readback")

    def after(self, link: str, op: str, name: str, line: str) -> None:
        """A bus action returned."""
        if self.phase != "body":
            return
        if link == "flex" and op == "write":
            args = line.split(" ", 1)[1].split(",") if " " in line else []
            if name == "MM" and args:
                self.mode = int(args[0])
            if name in ROUTE_WRITES:
                self._hit("route")
            if name == "SRP" or (name == "ACV" and len(args) > 1 and float(args[1]) > 0) or (
                    name == "XE" and self.mode in PULSED_MODES):
                self._hit("pulse_on")
        elif link == "wgfmu":
            if name == "connect":
                self._hit("route")
            if name == "execute":
                self._hit("pulse_on")

    def checkpoint(self) -> None:
        if self.phase == "body":
            self.boundaries += 1
            self._hit("checkpoint")

    def check_abort(self) -> None:
        if self.phase == "body":
            self.boundaries += 1


def _mnemonic(line: str) -> str:
    return line.strip().split(" ", 1)[0].upper()


class FlexHook:
    """FLEX transport wrapper under the audit layer that reports every action to the tracker; records
    ``(command, exclusive lock held)`` at every write."""

    def __init__(self, inner: SimTransport, tracker: Tracker) -> None:
        self.inner = inner
        self.tracker = tracker
        self.writes: list[tuple[str, bool]] = []

    @property
    def backend(self) -> str:
        return self.inner.backend

    @property
    def resource(self) -> str:
        return self.inner.resource

    def open(self) -> None:
        self.inner.open()

    def close(self) -> None:
        self.inner.close()

    def lock(self) -> None:
        self.inner.lock()

    def unlock(self) -> None:
        self.inner.unlock()

    def write(self, cmd: str) -> None:
        name = _mnemonic(cmd)
        self.tracker.before("flex", "write", name, cmd)
        self.writes.append((cmd, self.inner.locked))
        self.inner.write(cmd)
        self.tracker.after("flex", "write", name, cmd)

    def write_block(self, cmd: str, data: bytes) -> None:
        name = _mnemonic(cmd)
        self.tracker.before("flex", "write", name, cmd)
        self.inner.write_block(cmd, data)
        self.tracker.after("flex", "write", name, cmd)

    def read(self, *, timeout_s: float | None = None) -> str:
        self.tracker.before("flex", "read", "", "")
        return self.inner.read(timeout_s=timeout_s)

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:
        name = _mnemonic(cmd)
        self.tracker.before("flex", "query", name, cmd)
        answer = self.inner.query(cmd, timeout_s=timeout_s)
        self.tracker.after("flex", "query", name, cmd)
        return answer

    def serial_poll(self) -> int:
        self.tracker.before("flex", "serial_poll", "", "")
        return self.inner.serial_poll()

    def device_clear(self) -> None:
        self.tracker.before("flex", "device_clear", "", "")
        self.inner.device_clear()

    def wait(self, seconds: float) -> None:
        self.inner.wait(seconds)


class LibrarySpy:
    """Proxy of the simulated WGFMU library under its audit layer: records every call with its arguments and reports
    it to the tracker."""

    def __init__(self, inner: SimWgfmu, tracker: Tracker) -> None:
        self.inner = inner
        self.tracker = tracker
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.inner, name)
        if not callable(target) or name.startswith("_"):
            return target

        def call(*args: Any) -> Any:
            self.tracker.before("wgfmu", "call", name, name)
            self.calls.append((name, args))
            result = target(*args)
            self.tracker.after("wgfmu", "call", name, name)
            return result

        return call


@dataclass
class GlobalHarness:
    """One session on the body's scenario with both links spied (module docstring)."""

    body: Body
    plan: PlanRecord
    session: Session
    sim: SimTransport
    flex: FlexHook
    spy: LibrarySpy
    tracker: Tracker
    daily: MemoryAuditSink
    state_dir: Path
    run: MemoryRun = field(default_factory=MemoryRun)
    tx: Transaction | None = None
    started: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def log(self) -> list[CommandRecord]:
        return self.sim.instrument.command_log

    def events(self) -> list[AuditEvent]:
        return self.run.audit.events

    def transaction(self) -> Transaction:
        """The run's transaction with a synchronous ``RunControl`` that watches the abort file (as every run does)."""
        watch = AbortWatch(self.session.abort_file, run_id=self.run.run_id, since=self.started)
        control = RunControl(run_id=self.run.run_id, mode="sync", abort=watch)
        return self.session.transaction(intent=f"global matrix {self.body.name}", envelope=self.plan.envelope,
                                        run=self.run, plan_id=PLAN_ID, control=control)

    def execute(self) -> BaseException | None:
        """Run the body in one transaction; returns what left the ``with`` block (``None`` = nothing)."""
        kind = default_kinds()[self.body.kind]
        try:
            with self.transaction() as tx:
                self.tx = tx
                checkpoint = tx.checkpoint

                def tracked(*args: Any, **kwargs: Any) -> None:
                    self.tracker.checkpoint()
                    checkpoint(*args, **kwargs)

                tx.checkpoint = tracked  # type: ignore[method-assign]
                check_abort = tx.check_abort

                def tracked_abort() -> None:
                    self.tracker.check_abort()
                    check_abort()

                tx.check_abort = tracked_abort  # type: ignore[method-assign]
                self.tracker.phase = "body"
                try:
                    kind.acquire(tx, self.plan)
                finally:
                    if self.tracker.phase == "body":
                        self.tracker.phase = "done"
        except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt and StopBody are cases
            return exc
        return None


def make_harness(state_dir: Path, name: str, tracker: Tracker | None = None) -> GlobalHarness:
    body = BODY[name]
    plan = plan_of(name)
    tracker = tracker or Tracker()
    scenario = scenario_of(name)
    sim = SimTransport(scenario, state_file=sim_state_file(state_dir, scenario.name))
    hook = FlexHook(sim, tracker)
    daily = MemoryAuditSink()
    spy = LibrarySpy(SimWgfmu(sim.instrument, flex_locked=lambda: sim.locked), tracker)
    bus = Bus(flex=AuditingTransport(hook, daily),  # type: ignore[arg-type]
              wgfmu=AuditingWgfmu(spy, daily, backend="sim"))  # type: ignore[arg-type]
    settings = Settings.model_validate({"sim": {"scenario": scenario.name}})
    switches = bundle_of(body.scenario).station.switches
    session = Session(settings, lambda: bus, daily, state_dir=state_dir, switches=switches)
    return GlobalHarness(body=body, plan=plan, session=session, sim=sim, flex=hook, spy=spy, tracker=tracker,
                         daily=daily, state_dir=state_dir)


# -- faults -----------------------------------------------------------------------------------------------------------


def smu_channels(envelope: CompiledEnvelope) -> list[int]:
    """The SMU channels of an envelope (slot channels 1-10 with a voltage limit and no MFCMU/pulse function)."""
    return sorted(ch for ch, env in envelope.channels.items()
                  if ch <= 10 and env.ac is None and env.function not in ("pgu", "wgfmu", "cmu_high", "cmu_low"))


def wgfmu_channels(envelope: CompiledEnvelope) -> list[int]:
    return sorted(ch for ch, env in envelope.channels.items() if env.function == "wgfmu")


def buggy_level(h: GlobalHarness) -> None:
    """A buggy body asks for more than its envelope allows, on its own source family: an AC level beyond the
    MFCMU's ``max_vrms``; on the HV-SPGU ``SER`` 1 Ohm (the open-load level grows far beyond the pulse envelope) once
    a pulse program is configured, before that the gate's selector output to the PGU of the other port (a route the
    plan does not hold); 1 V above an SMU's ``max_abs_v``; 1 V above a WGFMU channel's limit; any SMU level for a
    body without sources. The guard refuses before any write (``EnvelopeViolation``)."""
    assert h.tx is not None
    env = h.plan.envelope
    smus = smu_channels(env)
    cmus = [ch for ch, e in env.channels.items() if e.ac is not None]
    pgus = [ch for ch, e in env.channels.items() if e.function == "pgu"]
    wgfmus = wgfmu_channels(env)
    driver = h.tx.driver
    if cmus:
        limit = env.channels[cmus[0]].ac
        assert limit is not None
        driver.set_cmu_ac(cmus[0], limit.max_vrms * 2 + 0.01)
    elif pgus:
        program = driver.spgu_program
        if program is not None and pgus[0] in program.channels:
            driver.set_pulse_load(pgus[0], 1.0)
        else:
            h.tx.apply_routes([Route(switch="SEL1", output="OUT2", state="pgu")], phase="buggy")
    elif smus:
        limit_v = env.channels[smus[0]].max_abs_v or 1.0
        driver.force_v(smus[0], limit_v + 1.0, icomp=1e-6)
    elif wgfmus:
        link = h.tx.wgfmu_link
        wg = link.driver if link.driver is not None else WgfmuDriver(h.session.bus.wgfmu, driver.guard)  # type: ignore[arg-type]
        wg.force_dc(wgfmus[0], (env.channels[wgfmus[0]].max_abs_v or 1.0) + 1.0)
    else:  # a body without any source (system.*): a level on any SMU channel is outside the empty allowlist
        driver.force_v(1, 1.0, icomp=1e-6)
    raise AssertionError("the guard let a level beyond the envelope through")


def precomputed_violation(h: GlobalHarness) -> EnvelopeViolation:
    """The ``EnvelopeViolation`` ``buggy_level`` raises (computed outside any bus action)."""
    try:
        buggy_level(h)
    except EnvelopeViolation as exc:
        return exc
    raise AssertionError("no envelope violation")


def _sim(h: GlobalHarness, fault: SimFault) -> None:
    h.sim.inject(fault)


def _next_flex(h: GlobalHarness, make: Callable[[str, str], SimFault]) -> None:
    """Arm ``make(op, line)`` for the next FLEX action (``op`` write/query/read/...)."""
    h.tracker.arm("flex", lambda op, line: h.sim.inject(make(op, line)))


def _next_call(h: GlobalHarness, make: Callable[[str], SimFault]) -> None:
    h.tracker.arm("wgfmu", lambda _op, name: h.sim.inject(make(name)))


def _timeout(op: str, line: str) -> SimFault:
    if op == "read":
        return TimeoutFault(on="read")
    name = _mnemonic(line) if line else "XE"
    if op == "query":
        return TimeoutFault(on=f"query:{name}")
    return TimeoutFault(on=name if op == "write" else "read")


def _errx(_op: str, line: str) -> SimFault:
    return ErrxFault(after_cmd=_mnemonic(line) if line else "ERRX?", code=100)


def _correction_lost(_op: str, line: str) -> SimFault:
    return CmuCorrectionLost(after_cmd=_mnemonic(line) if line else "ERRX?")


def _modules_without_spgu_and_wgfmu(h: GlobalHarness) -> SimFault:
    """The mainframe answers with its SMUs and MFCMU only: the HV-SPGU and the WGFMU vanish from ``UNT?``."""
    slots = [s for s in h.sim.scenario.slots if s.model not in ("B1525A", "B1530A")]
    return ModulesOverride(slots=slots)


def fault_injection(fault: str, h: GlobalHarness) -> Callable[[], None]:
    """What injecting ``fault`` does at the position (module docstring)."""
    channels = smu_channels(h.plan.envelope) or [1]
    makers: dict[str, Callable[[], None]] = {
        "compliance_at": lambda: _sim(h, ComplianceAt(step=0, ch=channels[0])),
        "errx": lambda: _next_flex(h, _errx),
        "timeout": lambda: _next_flex(h, _timeout),
        "garbage_data": lambda: _sim(h, GarbageData(at_step=0)),
        "interlock_open": lambda: _sim(h, InterlockOpen()),
        "disconnect": lambda: _sim(h, Disconnect(after_writes=0)),
        "oscillation": lambda: _sim(h, Oscillation()),
        "idn_override": lambda: _sim(h, IdnOverride(idn="Keysight Technologies,B1500A,0,A.99.99.9999.9999")),
        "modules_override": lambda: _sim(h, _modules_without_spgu_and_wgfmu(h)),
        "ignore_dz": lambda: _sim(h, IgnoreDz()),
        "cleanup_failure": lambda: _sim(h, CleanupFailure()),
        "slow": lambda: _sim(h, Slow(factor=1e4)),
        "run_interrupt": lambda: _sim(h, RunInterrupt(segment=0)),
        "bus_locked": lambda: _sim(h, BusLockedFault()),
        "abort_ignored": lambda: _sim(h, AbortIgnored()),
        "breakdown_at": lambda: _sim(h, BreakdownAt(t_s=0.0)),
        "cmu_correction_lost": lambda: _next_flex(h, _correction_lost),
        "cmu_overload": lambda: _sim(h, CmuOverload(at_step=0, condition="excess_current")),
        "spgu_no_stop": lambda: _sim(h, SpguNoStop()),
        "spgu_load_mismatch": lambda: _sim(h, SpguLoadMismatch(load_ohm=50.0)),
        "wgfmu_error": lambda: _next_call(h, lambda fn: WgfmuErrorFault(fn=fn, code=api.COMMUNICATION_ERROR)),
        "wgfmu_hang": lambda: _next_call(h, lambda fn: WgfmuHang(fn=fn)),
        "wgfmu_disconnect_fails": lambda: _sim(h, WgfmuDisconnectFails()),
        "wgfmu_dll_missing": lambda: _sim(h, WgfmuDllMissing()),
        "selector_stuck": lambda: _sim(h, SelectorStuck(port=0, state="pgu")),
        "cleanup_failure/once": lambda: _sim(h, CleanupFailure(count=1)),
        "spgu_no_stop/once": lambda: _sim(h, SpguNoStop(spp_ignored=1)),
        "wgfmu_disconnect_fails/once": lambda: _sim(h, WgfmuDisconnectFails(count=1)),
        "bus_locked/once": lambda: _sim(h, BusLockedFault(count=1)),
        "abort_ignored/once": lambda: _sim(h, AbortIgnored(count=1)),
        "selector_stuck/open": lambda: _sim(h, SelectorStuck(port=0, state="open")),
        "keyboard_interrupt": _raise(KeyboardInterrupt),
        "envelope_violation": lambda: buggy_level(h),
        "abort_request": lambda: h.session.abort_file.request("global matrix cancel", adapter="mcp",
                                                              run_id=h.run.run_id),
    }
    return makers[fault]


def _raise(exc: type[BaseException]) -> Callable[[], None]:
    def action() -> None:
        raise exc

    return action


def run_row(state_dir: Path, name: str, fault: str, position: str) -> tuple[GlobalHarness, BaseException | None]:
    """One matrix row: the body ``name`` with ``fault`` injected at ``position``; returns the harness and what left
    the transaction (``None`` = nothing)."""
    body = BODY[name]
    tracker = Tracker(target=position, stop_at=body.stop_at if position == "cleanup" else None)
    h = make_harness(state_dir, name, tracker)
    tracker.inject = fault_injection(fault, h)
    return h, h.execute()


# -- applicability ----------------------------------------------------------------------------------------------------

FAULT_NEEDS: dict[str, tuple[str, str]] = {
    "compliance_at": ("smu_data", ("marks an SMU reading as compliance in a FLEX data block; the body reads no SMU "
                                   "data over FLEX (an MFCMU, WGFMU or self-test result has no compliance status)")),
    "garbage_data": ("flex_data", ("corrupts a FLEX measurement data block; the body reads none (its data come from "
                                   "the WGFMU library or a query answer)")),
    "oscillation": ("flex_data", "marks FLEX readings as oscillating (status X); the body reads no FLEX data"),
    "run_interrupt": ("xe", ("interrupts the read of an XE measurement; the body triggers none (the same Ctrl-C at "
                             "every position is the keyboard_interrupt row)")),
    "abort_ignored": ("xe", ("makes AB ineffective; AB is sent only for a pending XE measurement and the body "
                             "triggers none")),
    "breakdown_at": ("mm10_dielectric", ("breaks a dielectric down at an MM 10 sampled point; the body samples no "
                                         "dielectric device")),
    "cmu_correction_lost": ("cmu", "clears the MFCMU corrections; the body does not drive the MFCMU"),
    "cmu_overload": ("cmu", "overloads an MFCMU measurement; the body does not drive the MFCMU"),
    "spgu_no_stop": ("spgu", "keeps an HV-SPGU output running; the body starts none"),
    "spgu_load_mismatch": ("spgu", "changes the HV-SPGU load; the body starts no HV-SPGU output"),
    "wgfmu_error": ("wgfmu", "fails a WGFMU library call; the body and its cleanup make none (no library session)"),
    "wgfmu_hang": ("wgfmu", "hangs a WGFMU library call; the body and its cleanup make none"),
    "wgfmu_disconnect_fails": ("wgfmu", "sticks an RSU relay; the body connects no WGFMU channel"),
    "wgfmu_dll_missing": ("wgfmu", "removes the WGFMU library; the body opens no library session"),
    "abort_request": ("boundary", ("is honoured at a segment boundary (tx.checkpoint, tx.check_abort); the body "
                                   "passes none, so the request waits for the next run's transaction")),
    "bus_locked": ("wgfmu", ("refuses a bus-lock request; a body without a WGFMU phase requests the lock only once, "
                             "at the transaction's entry (tests/safety/test_bus_locked.py), so no request is left "
                             "to refuse")),
}
"""Faults that act only on what a body does: fault -> (body feature, why it is inapplicable without it). Every other
fault applies to every body (FLEX link, cleanup and the declared switches are part of every transaction)."""

NO_LATER_MEASUREMENT = frozenset({"compliance_at", "garbage_data", "oscillation", "breakdown_at", "cmu_overload",
                                  "run_interrupt", "abort_request"})
"""Faults that act on a later measurement step or segment boundary: at position ``cleanup`` the body is over and
none follows."""

POSITION_REASONS = {
    "route": "the body switches no selector, SCUU, ASU or RSU path",
    "pulse_on": "the body starts no pulse or AC output",
    "execute": "the body sends no measurement trigger",
    "readback": "the body reads no data block (its result comes in a query answer or none)",
    "checkpoint": "the body runs as one segment without a checkpoint (R-RUN-02 caps a synchronous segment)",
}


def applies(fault: str, body: Body, position: str) -> str | None:
    """``None`` when the row runs, else the reason it is genuinely inapplicable."""
    if position not in body.positions:
        return f"{body.name}: {POSITION_REASONS[position]}"
    need = FAULT_NEEDS.get(base_fault(fault))
    if need is not None and need[0] not in body.features:
        return f"{body.name}: {fault} {need[1]}"
    if position == "cleanup" and base_fault(fault) in NO_LATER_MEASUREMENT:
        return (f"{body.name}: {fault} acts on a later measurement step or boundary and none follows once the body "
                "stopped")
    return None


def rows() -> Iterator[tuple[str, str, str]]:
    """Every running row ``(body, fault, position)``."""
    for body in BODIES:
        for fault in FAULTS:
            for position in POSITIONS:
                if applies(fault, body, position) is None:
                    yield body.name, fault, position


def cells() -> dict[tuple[str, str, str], list[str] | str]:
    """Every (kind, fault, position): the bodies that run it, or the reasons none can."""
    table: dict[tuple[str, str, str], list[str] | str] = {}
    for kind in KINDS:
        bodies = [b for b in BODIES if b.kind == kind]
        for fault in FAULTS:
            for position in POSITIONS:
                running = [b.name for b in bodies if applies(fault, b, position) is None]
                reasons = " | ".join(str(applies(fault, b, position)) for b in bodies)
                table[(kind, fault, position)] = running or reasons
    return table


# -- expected outcomes ------------------------------------------------------------------------------------------------

ALWAYS_LATCH = {
    "disconnect": "the link is gone, so nothing can verify (or restore) the safe state",
    "cleanup_failure": "DZ and CL never reach the instrument in either cleanup attempt",
    "selector_stuck": ("SEL1.OUT1 stays on the PGU path, and every session declares SEL1, so its rest state never "
                       "reads back"),
}
"""Faults after which the fault latch must be set, wherever they strike."""

NEVER_LATCH = frozenset({
    "compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "oscillation", "idn_override", "slow",
    "run_interrupt", "abort_ignored", "breakdown_at", "cmu_correction_lost", "cmu_overload", "spgu_load_mismatch",
    "wgfmu_error", "wgfmu_hang", "wgfmu_dll_missing", "keyboard_interrupt", "envelope_violation", "abort_request",
    *RECOVERABLE_FORMS,
})  # fmt: skip
"""Faults the cleanup must recover from (abort, device clear, retry, WGFMU initialize) with the safe state verified:
latching after them would stop the station for nothing."""

VERIFICATION_BLOCKERS = frozenset({"disconnect", "cleanup_failure", "bus_locked"})
"""Faults that keep the cleanup from verifying even when the outputs happen to be safe (no link, no DZ/CL, no FLEX
relock after the WGFMU phase): the latch is then the conservative answer. Any other latch needs a real unsafe state
(an output left on, a selector off rest, a WGFMU channel connected, an HV-SPGU output running)."""

CMU_MODES = frozenset(range(17, 27))
"""MFCMU measurement modes (``MM`` 17-26); every other data read is an SMU measurement."""


def observed_features(h: GlobalHarness) -> set[str]:
    """What a finished run did, in ``FEATURES`` terms (``Body.features`` must equal this for a clean run)."""
    ok = [r for r in h.log if r.outcome == "ok"]
    features: set[str] = set()
    if any(r.mnemonic == "XE" for r in ok):
        features.add("xe")
    if h.tracker.data_modes:
        features.add("flex_data")
    if any(mode not in CMU_MODES for mode in h.tracker.data_modes):
        features.add("smu_data")
    if any(e.ac is not None for e in h.plan.envelope.channels.values()):
        features.add("cmu")
    if h.sim.instrument.spgu_runs:
        features.add("spgu")
    if h.spy.calls:
        features.add("wgfmu")
    dielectric = any(m.model == "dielectric" for m in h.sim.scenario.models.values())
    if dielectric and any(r.mnemonic == "MM" and r.args[:1] == ["10"] for r in ok):
        features.add("mm10_dielectric")
    if h.tracker.boundaries:
        features.add("boundary")
    return features


# -- invariant --------------------------------------------------------------------------------------------------------


def _route_writes(plan: PlanRecord, switches: Sequence[SwitchSpec]) -> set[str]:
    """Every route write the plan may send: its routes and every declared output's rest state (ERSSP per selector
    port, SSP per SCUU phase, SAP per ASU)."""
    by_id = {s.id: s for s in switches}
    allowed: set[str] = set()
    phases = [list(routes) for routes in plan.routes_by_phase.values()]
    phases.append(list(plan.envelope.routes))
    rest = [Route(switch=s.id, output=o, state=s.rest) for s in switches for o in s.ports]
    for routes in [*phases, rest]:
        for route in routes:
            switch = by_id.get(route.switch)
            if switch is None:
                continue
            if switch.kind == "selector_16440a" and route.state in flex.ERSSP_CODES:
                allowed.add(flex.erssp(selector_port(switch, route.output), flex.ERSSP_CODES[route.state]))
            elif switch.kind == "asu" and route.state in flex.ASU_PATH_CODES:
                allowed.add(flex.sap(switch.ports[route.output].index, flex.ASU_PATH_CODES[route.state]))
        for switch in (s for s in switches if s.kind == "scuu"):
            command = _scuu_command(switch, [r for r in routes if r.switch == switch.id])
            if command is not None:
                allowed.add(command)
    return {" ".join(w.split()) for w in allowed}


def _scuu_command(switch: SwitchSpec, routes: list[Route]) -> str | None:
    """The ``SSP`` that sets ``routes`` on SCUU ``switch`` (``None``: no route of it, or no ``SSP`` path gives them)."""
    if not routes:
        return None
    try:
        cmu, path, _ = scuu_plan(switch, routes)
    except ValueError:
        return None
    return flex.ssp(cmu, path)


def assert_global_invariant_v2(h: GlobalHarness, tx: Transaction | None) -> None:
    """Blueprint v2 2.6, for one transaction of the matrix:

    - spies on both links: no SMU source, MFCMU source/frequency, route write, HV-SPGU output or WGFMU level/connect
      outside the plan's compiled envelope ever reached a transport (dropped records included);
    - the WGFMU library ran only while the FLEX exclusive lock was released;
    - the cleanup ran its steps in blueprint order, the lock and the in-flight marker are gone, every raw block read
      was handed to the run;
    - either the fault latch is set with ``cleanup_unverified`` audited (and the cleanup report says so), or every
      SMU is at 0 V and off (``DZ``/``CL`` after the last source), the MFCMU at DC 0 V / AC 0 V rms and off, the
      HV-SPGU stopped (``SPST?`` 0), every WGFMU channel disconnected and idle with the library session closed and the
      FLEX link locked again, every selector port open and every switched SCUU at its rest path or open.
    """
    log = h.log
    env = h.plan.envelope
    instrument = h.sim.instrument
    # 1. spies: nothing outside the envelope reached either link
    smu_records = [r for r in log if not (r.mnemonic in CMU_SOURCES or r.mnemonic == "SSP")]
    assert_within_envelope(smu_records, env)
    assert_cmu_within_envelope(log, env)
    allowed_routes = _route_writes(h.plan, h.session.switches)
    for record in log:
        if record.mnemonic in ROUTE_WRITES:
            assert " ".join(record.command.split()) in allowed_routes, f"route outside the plan: {record.command}"
    pulse_limits = [e.pulse.max_abs_v_dut for e in env.channels.values() if e.pulse is not None]
    for run in instrument.spgu_runs:
        assert pulse_limits, f"an HV-SPGU output without a pulse envelope: {run}"
        for record in run.channels.values():
            assert record.open_load_v <= max(pulse_limits) * (1 + 1e-12), run
            assert record.delivered_v <= record.open_load_v * (1 + 1e-12), run
        assert run.end_s is not None, f"a free-running HV-SPGU output: {run}"
    wg_limits = {ch: env.channels[ch].max_abs_v for ch in wgfmu_channels(env)}
    for name, args in h.spy.calls:
        if name in ("connect", "dc_force_voltage"):
            assert int(args[0]) in wg_limits, f"library {name} on a channel outside the plan: {args}"
        if name in LIBRARY_LEVELS:
            levels = ([float(args[1])] if name != "add_vectors" else [float(v) for v in args[2]])
            limit = max((v for v in wg_limits.values() if v is not None), default=0.0)
            assert all(abs(v) <= limit + 1e-12 for v in levels), f"library {name} beyond the envelope: {args}"
    events = h.events()
    assert_lock_windows(events)
    # 2. cleanup, lock, marker, raw data
    assert_cleanup_order(events)
    assert [e.ev for e in events].count("lock_released") == 1
    assert h.session.lock.holder() is None and not h.session.lock.is_held(), "instrument lock still held"
    assert not (h.state_dir / "inflight.json").exists(), "in-flight marker left behind"
    reads = [e.resp for e in events if e.ev == "read" and e.error is None]
    assert reads == h.run.raw, "a raw block read from the instrument was not handed to the run"
    # 3. safe, or latched with cleanup_unverified
    assert tx is not None and tx.cleanup is not None, "the transaction never reached its cleanup"
    latched = h.session.fault_latch.get() is not None
    assert latched == tx.cleanup.latched_fault == (tx.cleanup.verified == "unverified"), tx.cleanup
    if latched:
        assert any(e.ev == "cleanup_unverified" for e in events)
        return
    assert tx.cleanup.verified == "sim_state", tx.cleanup
    instrument.assert_safe()  # SMU/MFCMU outputs off at 0 V, no measurement pending, SPGU stopped, WGFMU idle+closed
    reached = [r for r in log if r.source and r.mnemonic != "SSP" and r.outcome != "dropped"]
    if reached:
        after = {r.mnemonic for r in log if r.seq > reached[-1].seq and r.outcome == "ok"}
        assert {"DZ", "CL"} <= after, f"DZ/CL missing after the last source command: {sorted(after)}"
    assert all(status == 0 for status in selector_states(h.sim).values()), selector_states(h.sim)
    if any(r.mnemonic == "SSP" and r.outcome == "ok" for r in log):  # an SCUU was switched: back at rest
        for switch in (s for s in h.session.switches if s.kind == "scuu"):
            rest = [Route(switch=switch.id, output=o, state=switch.rest) for o in switch.ports]
            cmu, path, _ = scuu_plan(switch, rest)
            # its rest path, or both outputs open (no entry: power-on, *RST, device clear; SwitchSpec.at_rest)
            assert instrument.state.scuu_paths.get(cmu) in (path, None), f"{switch.id} not at rest"
    if h.spy.calls:
        assert relocked_after_library(events), "the FLEX link was not locked again after the library session"
    cleanup_writes = [locked for cmd, locked in h.flex.writes if cmd in ("DZ", "CL")]
    assert cleanup_writes and all(cleanup_writes), "a cleanup DZ/CL went out without the exclusive lock"
