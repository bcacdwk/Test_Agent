"""``Executor``: validate → plan id → run, with the tier and summary checks of blueprint 2.6 and 4.3.

``Executor.plan(req)`` resolves, binds, compiles, evaluates the plan-phase rules and stores the frozen plan
(``catalog/planner.py``). ``Executor.run(plan_id, confirmed_summary=..., dut_instance=..., client=...)`` follows the
blueprint 2.6 docstring:

1. load the plan (unknown, or content not hashing to its id → ``unknown_plan``; past its TTL → ``plan_expired``;
   recipe, config hashes, a ``file`` parameter's CSV or backend changed → ``plan_stale``);
2. effective status ``not_implemented`` → refuse;
3. re-run the plan-phase rules, never trusting the stored tier: ``blocked`` → ``blocked_by_rules``;
   ``needs_confirmation`` without a summary → ``confirmation_required``; a summary that differs from the fresh
   ``plan_summary`` → ``summary_mismatch`` (the fresh summary is returned). Steps 1-3 do ZERO transport I/O (they
   read only plan, config, recipe and state files);
4. ``Session.transaction`` (fault-latch check, lock, bus open + lock (``BusLocked`` -> refused, ``busy``, nothing
   sent), inflight marker, recovery, baseline drain), a live snapshot and the ``pre_execute`` rules under the lock
   (``blocked`` → refuse; no source command is ever sent);
5. ``kind.acquire`` through the guarded driver; every raw read lands in ``raw/block-NNN.txt`` before parsing;
6. after the transaction's cleanup: table (``data.csv`` or ``data.npz``), ``quality.json``, the recipe's default
   analyses (``analysis/<method>-<n>.json``), the MFCMU correction store (``catalog/corrections.py``: a record after a
   successful correction run, records the instrument lost discarded, all cleared after a device clear), then the
   manifest (written once) and the index line.

``run`` never raises to adapters (except a ``KeyboardInterrupt``/``SystemExit``, re-raised after the run folder is
finalized as ``aborted``); every outcome is a ``RunSummary``. The run folder is created right before the
transaction so that the lock, the snapshot and the cleanup I/O are in the run's ``audit.jsonl``; when the
transaction is refused before anything was recorded (instrument busy, fault latched) the empty folder is removed.

Asynchronous runs (blueprint v2 2.6; ``plan.mode == "async"``, set by the planner above
``policy.run_limits.max_sync_run_s``): steps 4-6 run on a non-daemon worker thread (``session.Runner``) and ``run``
returns ``outcome: running`` with the run id and ``eta_s`` as soon as the transaction holds the instrument and the
pre-execute rules passed (a refusal before that is returned as for a synchronous run). The run sends ``CM 0`` before
the kind (R-CAL-02; the cleanup restores the state read by ``*LRN? 31``), records ``progress.json``/``partial.csv`` at
the kind's checkpoints and stops at the next checkpoint when an abort is requested (``safe_shutdown`` from any
process, the MCP server's shutdown hook, the CLI's Ctrl-C): outcome ``cancelled`` after the verified cleanup, the
rows acquired so far in ``partial.csv``. Every run, synchronous too, polls the abort file at its checkpoints. One
run at a time per process (a second request is ``busy`` at once) and per instrument (the lock). A run whose process
died is finalized as ``aborted`` by the transaction that recovers its in-flight marker (``Session.on_recovery``).
The auto-calibration state is read (``*LRN? 31``) before the pre-execute rules of every run (R-CAL-01, R-CAL-02),
and for a plan that uses an MFCMU its correction state (``CORRST?``, ``ADJ?``; R-CORR-01, WP8.2).
"""

from __future__ import annotations

import functools
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from b1500_test_agent.analysis.dataset import MANIFEST_FILE, PREVIEW_FILE, RunData, with_trust
from b1500_test_agent.analysis.plots import PlotSet
from b1500_test_agent.analysis.quality import assess_quality
from b1500_test_agent.analysis.registry import run_method
from b1500_test_agent.archive.audit import RUN_AUDIT_FILE
from b1500_test_agent.archive.corrections import CorrectionStore, records_for
from b1500_test_agent.archive.runfiles import PARTIAL_FILE, PROGRESS_FILE
from b1500_test_agent.archive.store import (
    QUALITY_FILE,
    RunFolder,
    RunStore,
    analysis_payload,
    process_software_version,
)
from b1500_test_agent.catalog.corrections import read_live_corrections, record_run
from b1500_test_agent.catalog.files import FileRoots, changed_param_files
from b1500_test_agent.catalog.kinds import MeasurementKind
from b1500_test_agent.catalog.planner import (
    PlanError,
    PlanExpiredError,
    Planner,
    PlanStaleError,
    PlanStore,
    config_hashes,
)
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.running import ActiveRun, RunningRuns
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.config import ConfigBundle, ConfigLoader
from b1500_test_agent.driver.errors import DriverError
from b1500_test_agent.errors import B1500Error, InvalidConfigError
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport
from b1500_test_agent.models.audit import AuditEvent, AuditEventName
from b1500_test_agent.models.common import Backend, ErrorCode, ResultStatus
from b1500_test_agent.models.plan import PlanRecord, PlanRequest, RuleFinding, RulesReport
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.run import (
    AbortRequest,
    Adapter,
    CleanupReport,
    ClientInfo,
    RunManifest,
    RunOutcome,
    RunSummary,
)
from b1500_test_agent.models.station import LiveState
from b1500_test_agent.rules import CalibrationState, RulesEngine, with_rules
from b1500_test_agent.rules.builtin.cmu import correction_next_steps
from b1500_test_agent.session import (
    AbortWatch,
    CleanupUnverified,
    FaultLatched,
    InstrumentBusy,
    RunCancelled,
    RunControl,
    RunJob,
    Runner,
    RunnerBusy,
    Session,
    Transaction,
    state_audit_sink,
)
from b1500_test_agent.transport.audit import AuditSink
from b1500_test_agent.transport.base import Bus, BusLocked, Transport
from b1500_test_agent.transport.factory import make_bus

BusFactory = Callable[[ConfigBundle, AuditSink], Bus | Transport]
"""Builds the instrument bus of a config bundle (default ``make_bus``; tests inject e.g. the visa-loop)."""
SELF_CAL_RECIPE = "system.self_cal"
DUT_INSTANCE_MAX = 200
START_MARGIN_S = 120.0
"""How long ``run`` waits, beyond the lock timeout, for an asynchronous run to start (recovery, snapshot, rules)."""
_PLAN_ID = re.compile(r"^P-[A-Z2-7]{10}$")

log = logging.getLogger("b1500.executor")


@dataclass
class _Refusal(Exception):
    """A refusal before any instrument I/O (steps 1-3)."""

    status: ResultStatus
    error_code: ErrorCode
    outcome: RunOutcome
    message: str
    next_steps: list[str] = field(default_factory=list)
    summary: str | None = None


@dataclass
class _Checked:
    """Result of steps 1-3: the plan with fresh plan-phase rules, its recipe and kind."""

    plan: PlanRecord
    recipe: Recipe
    kind: MeasurementKind
    report: RulesReport
    registry: RecipeRegistry
    """The registry the checks used; the run's pre-execute rules use it too (one recipe-tree hash per check)."""


@dataclass
class _RunState:
    live: LiveState | None = None
    pre_report: RulesReport | None = None
    raw: RawAcquisition | None = None
    error: BaseException | None = None
    refused: bool = False
    correction_notes: list[str] = field(default_factory=list)
    wgfmu_phases: list[str] = field(default_factory=list)


@dataclass
class _RunContext:
    """Everything one run needs on its (calling or worker) thread."""

    checked: _Checked
    bundle: ConfigBundle
    session: Session
    folder: RunFolder
    control: RunControl
    confirmed_summary: str | None
    dut_instance: str | None
    client: ClientInfo
    started: datetime


def _uses_wgfmu(plan: PlanRecord) -> bool:
    """Whether the plan drives a WGFMU channel (its pre-execute snapshot then reads the library's channel ids)."""
    return plan.envelope is not None and any(ch.function == "wgfmu" for ch in plan.envelope.channels.values())


def _flags(findings: list[RuleFinding], severity: str) -> str:
    return "; ".join(f"{f.rule_id} {f.message}" for f in findings if f.severity == severity)


class Executor(RunningRuns):
    """Plans and runs recipes for one process (blueprint 2.6). ``config`` is re-read on every call (digest cache).

    ``registry`` defaults to ``recipes/`` of the configured repository and is reloaded when a recipe file changes;
    ``bus_factory`` replaces ``make_bus`` (tests: the visa-loop resource manager); ``clock`` stamps plans and run
    ids. ``runner`` holds this process's asynchronous run (one at a time).
    """

    def __init__(self, config: ConfigLoader, *, registry: RecipeRegistry | None = None, adapter: Adapter = "cli",
                 clock: Callable[[], datetime] | None = None, bus_factory: BusFactory | None = None,
                 lock_timeout_s: float = 5.0) -> None:
        self.config = config
        self.adapter: Adapter = adapter
        self.lock_timeout_s = lock_timeout_s
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._bus_factory = bus_factory
        self._session: Session | None = None
        self._session_key: str | None = None
        self.runner = Runner()

    # -- plumbing ---------------------------------------------------------------------------------------------------

    def registry(self, bundle: ConfigBundle | None = None) -> RecipeRegistry:
        """The recipe registry (loaded lazily, reloaded when a recipe file changed)."""
        if self._registry is None:
            paths = (bundle or self.config.get()).paths
            self._registry = RecipeRegistry.load(paths.recipes_dir, repo_root=paths.repo_root)
        else:
            self._registry = self._registry.reload_if_changed()
        return self._registry

    def session(self, bundle: ConfigBundle) -> Session:
        """The session for ``bundle``'s backend, scenario and state directory (rebuilt when they change)."""
        state_dir = bundle.paths.state_dir
        key = json.dumps([
            bundle.settings.model_dump(mode="json"),
            None if bundle.sim_scenario is None else bundle.sim_scenario.model_dump(mode="json"),
            None if bundle.sim_faults is None else bundle.sim_faults.model_dump(mode="json"),
            state_dir.as_posix(),
            [s.model_dump(mode="json") for s in bundle.station.switches],
        ], sort_keys=True)
        if self._session is None or key != self._session_key:
            if self._session is not None and self.runner.active() is None:
                self._session.close()  # a running asynchronous run keeps its own session (and bus) to the end
            sink = state_audit_sink(state_dir)
            custom = self._bus_factory

            def factory() -> Bus | Transport:
                if custom is not None:
                    return custom(bundle, sink)
                return make_bus(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
                                state_dir=state_dir)

            self._session = Session(bundle.settings, factory, sink, state_dir=state_dir, adapter=self.adapter,
                                    switches=bundle.station.switches)
            self._session.on_recovery = functools.partial(self._finalize_orphan, bundle)
            self._session_key = key
        return self._session

    def close(self, *, wait_s: float | None = None) -> None:
        """Stop this process's asynchronous run, if any (abort request, wait ``wait_s``, default one segment plus
        cleanup), then close the session's bus if it is still open (a later call opens it again)."""
        job = self.runner.active()
        if job is not None:
            self.stop_runs("executor closing", wait_s=wait_s)
            if not job.done:
                return  # the worker still owns the session; it releases the bus at the end of its transaction
        if self._session is not None:
            self._session.close()

    def now(self) -> datetime:
        """The executor's clock (plans, run ids, correction records)."""
        return self._clock()

    def _planner(self, bundle: ConfigBundle, registry: RecipeRegistry | None = None) -> Planner:
        """A planner over the registry (``registry``, else the current one) with the server-written MFCMU correction
        store (R-CORR-01)."""
        return Planner(registry if registry is not None else self.registry(bundle), clock=self._clock,
                       corrections=functools.partial(records_for, state_dir=bundle.paths.state_dir))

    def _engine(self, bundle: ConfigBundle) -> RulesEngine:
        return RulesEngine(bundle, clock=self._clock)

    def _fault_state(self, session: Session) -> tuple[Any, bool]:
        """Latched fault and whether a stale inflight marker waits for recovery (file reads only, no I/O)."""
        marker = session.inflight()
        unrecovered = marker is not None and not session.lock.is_held()
        return session.fault_latch.get(), unrecovered

    def _calibration(self, bundle: ConfigBundle) -> CalibrationState:
        entry = RunStore(bundle.paths.runs_dir).latest(SELF_CAL_RECIPE, backend=bundle.backend)
        if entry is None:
            return CalibrationState()
        return CalibrationState(last_self_calibration=datetime.fromisoformat(str(entry["finished_at"])),
                                last_self_calibration_run=str(entry["run_id"]))

    # -- plan -------------------------------------------------------------------------------------------------------

    def plan(self, req: PlanRequest, *, live: LiveState | None = None) -> PlanRecord:
        """Resolve, bind, compile, evaluate the plan-phase rules (with ``live`` if given; no I/O here) and store
        the frozen plan. Raises ``InvalidConfigError``, ``UnknownRecipeError`` or ``InvalidInputError``."""
        bundle = self.config.get()
        session = self.session(bundle)
        fault, unrecovered = self._fault_state(session)
        plan = self._planner(bundle).plan(req, bundle, self._engine(bundle), live=live, fault=fault,
                                          inflight_unrecovered=unrecovered)
        PlanStore(bundle.paths.state_dir).save(plan)
        return plan

    def load_plan(self, plan_id: str) -> PlanRecord:
        """The stored plan, verified against its hash (``UnknownPlanError`` otherwise); rules not re-run."""
        return PlanStore(self.config.get().paths.state_dir).load(plan_id)

    def revalidate(self, plan_id: str) -> PlanRecord:
        """Steps 1 and 3 without a run: the stored plan with fresh plan-phase rules, tier and summary. Raises
        ``PlanError`` (``unknown_plan``, ``plan_expired``, ``plan_stale``) or ``InvalidConfigError``."""
        bundle = self.config.get()
        registry = self.registry(bundle)
        plan, _, _ = self._load_checked(plan_id, bundle, registry)
        return self._fresh(plan, bundle, registry)[0]

    def _load_checked(self, plan_id: str, bundle: ConfigBundle, registry: RecipeRegistry | None = None,
                      ) -> tuple[PlanRecord, Recipe, MeasurementKind | None]:
        """Step 1: load, expiry, staleness (file reads only) against ``registry`` (default: the current one)."""
        plan = PlanStore(bundle.paths.state_dir).load(plan_id)
        now = self._clock()
        ttl_end = plan.created_at + timedelta(hours=bundle.policy.plans.ttl_h)
        if now >= min(plan.expires_at, ttl_end):
            raise PlanExpiredError(f"plan {plan_id} expired at {min(plan.expires_at, ttl_end).isoformat()}; "
                                   "validate the request again")
        registry = registry if registry is not None else self.registry(bundle)
        if plan.backend != bundle.backend:
            raise PlanStaleError(f"plan {plan_id} was validated for backend {plan.backend}, the configured backend "
                                 f"is {bundle.backend}; validate again")
        if plan.recipe_id not in registry.ids():
            raise PlanStaleError(f"recipe {plan.recipe_id} of plan {plan_id} is no longer registered")
        recipe = registry.get(plan.recipe_id)
        if (recipe.version, recipe.sha256) != (plan.recipe_version, plan.recipe_sha):
            raise PlanStaleError(f"recipe {recipe.id} changed since plan {plan_id} was validated (version "
                                 f"{plan.recipe_version} -> {recipe.version}); validate again")
        current = config_hashes(bundle, plan.request.pin_map, plan.request.dut_profile)
        if current != plan.hashes:
            changed = sorted(k for k in set(current) | set(plan.hashes) if current.get(k) != plan.hashes.get(k))
            raise PlanStaleError(f"config changed since plan {plan_id} was validated ({', '.join(changed)}); "
                                 "validate again")
        files = changed_param_files(plan.files, FileRoots.of(registry.root, bundle.paths.work_dir))
        if files:
            names = ", ".join(f"{name} ({plan.files[name].path})" for name in files)
            raise PlanStaleError(f"file parameter(s) {names} changed since plan {plan_id} was validated; validate "
                                 "again")
        return plan, recipe, registry.kinds.get(recipe.kind)

    def _fresh(self, plan: PlanRecord, bundle: ConfigBundle,
               registry: RecipeRegistry | None = None) -> tuple[PlanRecord, RulesReport]:
        """Step 3: the plan-phase rules again (never the stored tier), with the current fault/inflight state."""
        session = self.session(bundle)
        fault, unrecovered = self._fault_state(session)
        ctx = self._planner(bundle, registry).context(plan, bundle, fault=fault, inflight_unrecovered=unrecovered)
        report = self._engine(bundle).evaluate(ctx, "plan")
        return with_rules(plan, report), report

    def _check(self, plan_id: str, bundle: ConfigBundle, confirmed_summary: str | None) -> _Checked:
        """Steps 1-3 (zero transport I/O) against one registry (each ``registry()`` hashes every recipe file to see a
        change); raises ``_Refusal``."""
        registry = self.registry(bundle)
        try:
            plan, recipe, kind = self._load_checked(plan_id, bundle, registry)
        except PlanError as exc:
            next_steps = ["validate the request again with validate_plan"]
            raise _Refusal("refused", exc.code, "refused", str(exc), next_steps) from None
        if kind is None or registry.effective_status(recipe.id, bundle.backend) == "not_implemented":
            raise _Refusal("not_implemented", "not_implemented", "not_implemented",
                           f"recipe {recipe.id} (kind {recipe.kind}) is not implemented on backend {bundle.backend}",
                           ["list validated alternatives with list_recipes; never improvise instrument code"])
        fresh, report = self._fresh(plan, bundle, registry)
        if report.tier == "blocked":
            raise _Refusal("blocked", "blocked_by_rules", "refused",
                           f"plan {plan_id} is blocked: {_flags(report.findings, 'block')}",
                           [("explain the blocking rules and offer an in-envelope alternative; only a human edits "
                            "config/local/"), *correction_next_steps(report.findings)], summary=fresh.summary)
        if confirmed_summary is None:
            if report.tier == "needs_confirmation":
                raise _Refusal("needs_confirmation", "confirmation_required", "confirmation_required",
                               f"plan {plan_id} needs a human confirmation ({', '.join(report.confirm_reasons)})",
                               [("show the summary verbatim with the risks and stop; after the human's own consent "
                                "call run_confirmed_plan with the exact summary")], summary=fresh.summary)
        elif confirmed_summary.strip() != fresh.summary:
            raise _Refusal("refused", "summary_mismatch", "refused",
                           "the confirmed summary differs from the current plan summary",
                           ["show the current summary to the human and ask again"], summary=fresh.summary)
        return _Checked(plan=fresh, recipe=recipe, kind=kind, report=report, registry=registry)

    # -- run --------------------------------------------------------------------------------------------------------

    def run(self, plan_id: str, *, confirmed_summary: str | None, dut_instance: str | None,
            client: ClientInfo) -> RunSummary:
        """confirmed_summary: None from run_plan, the echoed argument from run_confirmed_plan.
        1 load plan (unknown/hash ≠ plan_id → unknown_plan; expired → plan_expired; config hashes changed → plan_stale)
        2 not_implemented → refuse  3 re-run plan-phase rules, never trusting the stored tier: blocked →
          blocked_by_rules; needs_confirmation without summary → confirmation_required; summary ≠ fresh plan_summary →
          summary_mismatch (returns it). Steps 1–3: ZERO transport I/O  4 Session.transaction: pre_execute rules with
          live state (block → refuse, zero source commands)  5 archive.create; kind.acquire  6 raw saved even on
          failure; to_table; quality; analysis_defaults; archive.finalize. Never raises to adapters."""
        started = self._clock()
        try:
            bundle = self.config.get()
        except InvalidConfigError as exc:
            report = self.config.check()
            backend: Backend = report.backend or "sim"
            return RunSummary(ok=False, status="error", backend=backend, simulated=backend == "sim",
                              message=str(exc), error_code="invalid_config", plan_id=None, outcome="refused",
                              next_steps=["ask the human to fix config/local/ (b1500 config check)"])
        if dut_instance is not None and (not dut_instance.isprintable() or len(dut_instance) > DUT_INSTANCE_MAX):
            return self._summary(bundle, plan_id, ok=False, status="refused", outcome="refused",
                                 error_code="invalid_input",
                                 message=f"dut_instance must be printable text of at most {DUT_INSTANCE_MAX} "
                                         "characters")
        try:
            checked = self._check(plan_id, bundle, confirmed_summary)
        except _Refusal as refusal:
            self._audit_refusal(bundle, plan_id, refusal)
            return self._summary(bundle, plan_id, ok=False, status=refusal.status, outcome=refusal.outcome,
                                 error_code=refusal.error_code, message=refusal.message,
                                 next_steps=refusal.next_steps, summary=refusal.summary)
        except Exception as exc:  # noqa: BLE001 - never raise to adapters
            return self._summary(bundle, plan_id, ok=False, status="error", outcome="failed", error_code="internal",
                                 message=f"internal error while checking plan {plan_id}: {type(exc).__name__}: {exc}")
        busy = self.active_run(bundle, include_foreign=False)
        if busy is not None:
            return self._busy_summary(bundle, checked.plan.plan_id, busy)
        try:
            return self._execute(checked, bundle, confirmed_summary=confirmed_summary, dut_instance=dut_instance,
                                 client=client, started=started)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001 - never raise to adapters
            return self._summary(bundle, plan_id, ok=False, status="error", outcome="failed", error_code="internal",
                                 message=f"internal error during run of plan {plan_id}: {type(exc).__name__}: {exc}")

    def _summary(self, bundle: ConfigBundle, plan_id: str | None, **fields: Any) -> RunSummary:
        return RunSummary(backend=bundle.backend, simulated=bundle.backend == "sim",
                          plan_id=plan_id if _is_plan_id(plan_id) else None, **fields)

    def _audit_refusal(self, bundle: ConfigBundle, plan_id: str, refusal: _Refusal) -> None:
        try:
            state_audit_sink(bundle.paths.state_dir).emit(AuditEvent.now("run_status", bundle.backend, data={
                "plan_id": plan_id[:40], "outcome": refusal.outcome, "error_code": refusal.error_code,
            }))
        except OSError:
            pass  # auditing a refusal must not turn it into an error

    def _busy_summary(self, bundle: ConfigBundle, plan_id: str | None, active: ActiveRun) -> RunSummary:
        """``busy: run <id> (<done>/<total>)``: a run holds the instrument; nothing was sent."""
        return self._summary(bundle, plan_id, ok=False, status="busy", outcome="refused", error_code="instrument_busy",
                             message=f"busy: {active.describe()} holds the instrument; nothing was sent",
                             next_steps=[(f"get_run({active.run_id}, include=[progress]) follows it; safe_shutdown "
                                         "cancels it; retry after it ends")])

    def _execute(self, checked: _Checked, bundle: ConfigBundle, *, confirmed_summary: str | None,
                 dut_instance: str | None, client: ClientInfo, started: datetime) -> RunSummary:
        plan = checked.plan
        session = self.session(bundle)
        folder = RunStore(bundle.paths.runs_dir).create(bundle.backend, now=self._clock())
        asynchronous = plan.mode == "async"
        watch = AbortWatch(session.abort_file, run_id=folder.run_id, since=datetime.now(UTC))
        quality = checked.recipe.quality
        control = RunControl(run_id=folder.run_id, mode=plan.mode, abort=watch,
                             progress_sink=folder.write_progress if asynchronous else None,
                             partial_sink=lambda rows: folder.append_partial(rows, quality),
                             estimate_s=plan.estimate.duration_s)
        run = _RunContext(checked=checked, bundle=bundle, session=session, folder=folder, control=control,
                          confirmed_summary=confirmed_summary, dut_instance=dut_instance, client=client,
                          started=started)
        if not asynchronous:
            return self._transact(run, on_started=None)
        job = RunJob(run_id=folder.run_id, plan_id=plan.plan_id, recipe_id=plan.recipe_id, control=control,
                     adapter=client.adapter + (f":{client.session_tag}" if client.session_tag else ""),
                     started_at=started, dut_instance=dut_instance,
                     confirmed_via=None if confirmed_summary is None else (
                         "run_confirmed_plan" if client.adapter == "mcp" else "cli --confirm"))
        try:
            self.runner.start(job, lambda on_started: self._transact(run, on_started=on_started))
        except RunnerBusy as exc:
            folder.discard()
            return self._busy_summary(bundle, plan.plan_id, self._job_run(exc.job, bundle))
        job.wait_started(self.lock_timeout_s + START_MARGIN_S)
        if not job.started.is_set() and job.done:  # refused, busy or failed before the run started
            if isinstance(job.result, RunSummary):
                return job.result
            error = job.error
            if error is not None and not isinstance(error, Exception):
                raise error
            return self._summary(bundle, plan.plan_id, ok=False, status="error", outcome="failed",
                                 error_code="internal", run_id=folder.run_id,
                                 message=f"run {folder.run_id} ended before it started: "
                                         f"{type(error).__name__ if error else 'no result'}: {error}")
        paths = bundle.paths
        return RunSummary(
            ok=True, status="ok", backend=bundle.backend, simulated=bundle.backend == "sim", run_id=folder.run_id,
            plan_id=plan.plan_id, outcome="running", eta_s=round(plan.estimate.duration_s, 3),
            message=(f"run {folder.run_id} is running asynchronously (estimated {plan.estimate.duration_s:.0f} s"
                     + (", SIMULATED" if bundle.backend == "sim" else "") + ")"),
            next_steps=[(f"get_run({folder.run_id}, include=[progress]) follows it (rows so far with data); "
                        "safe_shutdown cancels it with a verified cleanup; station_status answers busy until it ends")],
            artifacts={"run_dir": paths.display(folder.path), "progress": paths.display(folder.path / PROGRESS_FILE),
                       "partial": paths.display(folder.path / PARTIAL_FILE)},
            summary=plan.summary if confirmed_summary is not None else None,
        )

    def _read_auto_calibration(self, folder: RunFolder, tx: Transaction) -> bool | None:
        """The auto-calibration switch (``*LRN? 31``) for R-CAL-01/02; ``None`` (audited) when the answer does not
        parse. Link errors propagate (the run fails with its cleanup)."""
        try:
            return tx.driver.auto_calibration()
        except DriverError as exc:
            self._emit(folder, tx, "checkpoint", {"label": "auto_calibration_unread", "error": str(exc)[:300]})
            return None

    def _transact(self, run: _RunContext, *, on_started: Callable[[], None] | None) -> RunSummary:
        """Steps 4-6 of one run on the calling (synchronous) or worker (asynchronous) thread; ``on_started`` is
        called once the pre-execute rules passed (and, asynchronously, auto-calibration is off)."""
        checked, bundle, session, folder = run.checked, run.bundle, run.session, run.folder
        plan, kind = checked.plan, checked.kind
        calibration = self._calibration(bundle)
        planner = self._planner(bundle, checked.registry)
        state = _RunState()
        tx = session.transaction(intent=f"run {plan.recipe_id} ({plan.plan_id})", envelope=plan.envelope,
                                 run=folder, lock_timeout_s=self.lock_timeout_s, plan_id=plan.plan_id,
                                 control=run.control)
        t0 = time.monotonic()
        try:
            with tx:
                self._emit(folder, tx, "tier_check", {
                    "plan_id": plan.plan_id, "tier": checked.report.tier,
                    "confirm_reasons": ", ".join(checked.report.confirm_reasons),
                    "confirmed": run.confirmed_summary is not None, "mode": plan.mode})
                state.live = tx.snapshot(wgfmu=_uses_wgfmu(plan))
                state.live, changes = read_live_corrections(tx.driver, plan, state.live,
                                                            CorrectionStore(bundle.paths.state_dir))
                if changes.changed:
                    self._emit(folder, tx, "checkpoint", {"label": "corrections_before_run", **changes.audit()})
                    state.correction_notes += changes.notes
                auto = self._read_auto_calibration(folder, tx)
                calibration = calibration.model_copy(update={"auto_calibration": auto})
                ctx = planner.context(plan, bundle, live=state.live, fault=session.fault_latch.get(),
                                      calibration=calibration)
                state.pre_report = self._engine(bundle).evaluate(ctx, "pre_execute")
                self._emit(folder, tx, "rule_report", {
                    "phase": "pre_execute", "tier": state.pre_report.tier,
                    "blocks": _flags(state.pre_report.findings, "block")[:500],
                    "warnings": _flags(state.pre_report.findings, "warn")[:500]})
                if state.pre_report.tier == "blocked":
                    state.refused = True
                else:
                    if plan.mode == "async":
                        tx.suspend_auto_calibration(auto)
                        run.control.begin(total=_checkpoint_total(kind, plan))
                    if on_started is not None:
                        on_started()
                    state.raw = kind.acquire(tx, plan)
        except (InstrumentBusy, FaultLatched) as exc:
            if folder.is_empty():
                folder.discard()
                status: ResultStatus = "busy" if isinstance(exc, InstrumentBusy) else "fault"
                message = str(exc)
                if isinstance(exc, InstrumentBusy):
                    holder = self.active_run(bundle, include_local=False)
                    if holder is not None:
                        message = f"busy: {holder.describe()} holds the instrument; {message}"
                next_steps = ([("retry later; another process holds the instrument (get_run follows its run; "
                               "safe_shutdown cancels it)")] if status == "busy"
                              else ["call safe_shutdown and load skill b1500-debug; only a human clears the fault"])
                return self._summary(bundle, plan.plan_id, ok=False, status=status, outcome="refused",
                                     error_code=exc.code, message=message, next_steps=next_steps)
            state.error = exc
        except BaseException as exc:  # noqa: BLE001 - recorded in the run; interrupts re-raised after finalize
            state.error = exc
        transaction_s = time.monotonic() - t0
        state.wgfmu_phases = tx.wgfmu_phases
        cleanup = tx.cleanup
        if isinstance(state.error, CleanupUnverified):
            cleanup = state.error.report
        if isinstance(state.error, RunCancelled):
            self._cancelled(run, state.error, cleanup)
        summary = self._finish(checked, bundle, folder, state, cleanup, confirmed_summary=run.confirmed_summary,
                               dut_instance=run.dut_instance, client=run.client, started=run.started,
                               transaction_s=transaction_s, control=run.control)
        if state.error is not None and not isinstance(state.error, Exception) and on_started is None:
            raise state.error  # a synchronous run re-raises the interrupt; a worker records it (outcome aborted)
        return summary

    def _cancelled(self, run: _RunContext, exc: RunCancelled, cleanup: CleanupReport | None) -> None:
        """After the verified cleanup of a cancelled run: remove the abort request and audit the cancel."""
        try:
            consumed = run.control.abort.consume()
        except OSError:
            consumed = False
        request: AbortRequest = exc.request
        progress = run.control.latest
        run.folder.audit.emit(AuditEvent.now("run_cancelled", run.bundle.backend, run=run.folder.run_id, data={
            "request": request.id, "reason": request.reason, "by": request.adapter, "pid": request.pid,
            "done": progress.done if progress else None, "total": progress.total if progress else None,
            "cleanup": cleanup.verified if cleanup else None, "consumed": consumed}))

    @staticmethod
    def _emit(folder: RunFolder, tx: Transaction, ev: AuditEventName, data: dict[str, Any]) -> None:
        folder.audit.emit(AuditEvent.now(ev, tx.driver.transport.backend, run=folder.run_id, tx=tx.tx_id,
                                         intent=tx.intent, data=data))

    # -- step 6 -----------------------------------------------------------------------------------------------------

    def _finish(self, checked: _Checked, bundle: ConfigBundle, folder: RunFolder, state: _RunState,
                cleanup: CleanupReport | None, *, confirmed_summary: str | None, dut_instance: str | None,
                client: ClientInfo, started: datetime, transaction_s: float,
                control: RunControl | None = None) -> RunSummary:
        plan, recipe, kind = checked.plan, checked.recipe, checked.kind
        backend = bundle.backend
        registry = self.registry(bundle)  # once per finalize: each call hashes every recipe file to see a change
        reports = [checked.report] + ([state.pre_report] if state.pre_report is not None else [])
        manifest = RunManifest(
            run_id=folder.run_id, plan=plan, plan_hash=plan.plan_hash, recipe_id=recipe.id,
            recipe_version=recipe.version, recipe_sha=recipe.sha256,
            recipe_status=registry.effective_status(recipe.id, backend), backend=backend,
            simulated=backend == "sim",
            identity=state.live.identity if state.live else None,
            inventory=state.live.inventory if state.live else None,
            hashes=dict(plan.hashes), config_files=list(bundle.files.values()), rules=reports, tier=plan.tier,
            confirmed_summary=confirmed_summary.strip() if confirmed_summary is not None else None,
            confirmed_via=None if confirmed_summary is None else (
                "run_confirmed_plan" if client.adapter == "mcp" else "cli --confirm"),
            client=client, software_version=process_software_version(), dut_instance=dut_instance, started_at=started,
            outcome="completed", cleanup=cleanup, assumptions=self._assumptions(bundle, plan) + [
                f"WGFMU phase {i}: GPIB link {how} while the WGFMU library had its own session (ATV-14)"
                for i, how in enumerate(state.wgfmu_phases, 1)],
        )
        error_code: ErrorCode | None = None
        message = ""
        quality: QualityReport | None = None
        analyses: list[ExtractionResult] = []
        flags: list[str] = []
        artifacts: dict[str, str] = {}
        outcome: RunOutcome
        if isinstance(state.error, RunCancelled):
            outcome, error_code = "cancelled", "run_cancelled"
            progress = control.latest if control is not None else None
            at = f" at {progress.done}/{progress.total}" if progress is not None else ""
            verified = cleanup.verified if cleanup is not None else "not run"
            message = (f"cancelled{at} by an abort request ({state.error.request.reason}); cleanup {verified}; the "
                       "rows acquired before the cancel are in partial.csv (partial data, no data.csv)")
        elif state.error is not None:
            exc = state.error
            outcome = "aborted" if not isinstance(exc, Exception) else (
                "refused" if isinstance(exc, FaultLatched | BusLocked) else "failed")
            error_code = _error_code(exc)
            message = f"{type(exc).__name__}: {exc}"
        elif state.refused:
            outcome, error_code = "refused", "blocked_by_rules"
            assert state.pre_report is not None
            message = f"pre-execute rules blocked the run: {_flags(state.pre_report.findings, 'block')}"
        elif state.raw is None or not state.raw.ok:
            outcome, error_code = "failed", "instrument_error"
            message = state.raw.message if state.raw is not None else "no data acquired"
        else:
            outcome = "completed"
            try:
                table = kind.to_table(state.raw, plan)
                if table is not None:  # the default analyses see the kind_result the archived manifest gets
                    analysed = manifest.model_copy(update={"kind_result": dict(state.raw.kind_result)})
                    quality, analyses, flags = self._analyse(folder, table, analysed, recipe, artifacts)
            except Exception as exc:  # noqa: BLE001 - the raw data stay archived; the run is failed
                outcome, error_code = "failed", _error_code(exc)
                message = f"processing the acquired data failed: {type(exc).__name__}: {exc}"
        corrections = record_run(CorrectionStore(bundle.paths.state_dir), plan=plan, raw=state.raw, live=state.live,
                                 cleanup=cleanup, completed=outcome == "completed", run_id=folder.run_id,
                                 now=self._clock(), station=bundle.station)
        if corrections.changed:
            folder.audit.emit(AuditEvent.now("checkpoint", backend, run=folder.run_id,
                                             data={"label": "corrections_after_run", **corrections.audit()}))
        correction_notes = state.correction_notes + corrections.notes
        if outcome == "completed":
            flags.extend(correction_notes)
            if cleanup is not None and cleanup.errors:
                flags.append("instrument errors drained at cleanup: "
                             + ", ".join(f"{e.code} {e.message}".strip() for e in cleanup.errors))
            if flags:
                outcome = "completed_with_flags"
                message = "; ".join(flags)
        elif correction_notes:
            message = "; ".join([message, *correction_notes]) if message else "; ".join(correction_notes)
        if state.raw is not None:
            manifest = manifest.model_copy(update={"kind_result": dict(state.raw.kind_result)})
        counts = dict(quality.counts) if quality is not None else {}
        quality_findings = (self._engine(bundle).quality(counts, recipe=recipe,
                                                         recipe_source=registry.source(recipe.id))
                            if quality is not None else [])
        if control is not None:
            final = {"completed": "completed", "completed_with_flags": "completed", "cancelled": "cancelled"}
            try:
                control.finish(final.get(outcome, "failed"),  # type: ignore[arg-type]
                               warn=lambda what, exc: log.warning("run %s: %s: %s", folder.run_id, what, exc))
            except Exception as exc:  # noqa: BLE001 - the manifest still records the outcome
                log.warning("run %s: final progress not written: %s", folder.run_id, exc)
        folder.audit.emit(AuditEvent.now("run_status", backend, run=folder.run_id, data={
            "outcome": outcome, "error_code": error_code, "verdict": quality.verdict if quality else None,
            "cleanup": cleanup.verified if cleanup else None}))
        finished = self._clock()
        manifest = manifest.model_copy(update={
            "outcome": outcome, "error_code": error_code, "message": message[:2000], "finished_at": finished,
            "status_counts": counts, "quality_verdict": quality.verdict if quality else None,
            "quality_findings": quality_findings,
            "timings": {"transaction_s": round(transaction_s, 6),
                        "total_s": round(max(0.0, (finished - started).total_seconds()), 6)},
        })
        final = folder.finalize(manifest)
        run_dir = bundle.paths.display(folder.path)  # resolved once; files inside are named from it (WP6.5)
        artifacts = {"run_dir": run_dir,
                     "manifest": f"{run_dir}/{MANIFEST_FILE}",
                     "audit": f"{run_dir}/{RUN_AUDIT_FILE}",
                     **{name: f"{run_dir}/{rel}" for name, rel in artifacts.items()},
                     **_raw_artifacts(run_dir, folder.raw_files)}
        if (folder.path / PARTIAL_FILE).is_file() and "data" not in artifacts:
            artifacts["partial"] = f"{run_dir}/{PARTIAL_FILE}"
        if (folder.path / PROGRESS_FILE).is_file():
            artifacts["progress"] = f"{run_dir}/{PROGRESS_FILE}"
        if corrections.path is not None:
            artifacts["corrections"] = bundle.paths.display(corrections.path)
        ok = outcome in ("completed", "completed_with_flags")
        latched = cleanup is not None and cleanup.latched_fault
        blocking = state.pre_report.findings if state.refused and state.pre_report is not None else []
        next_steps = list(dict.fromkeys(self._next_steps(outcome, latched, quality, error_code)
                                        + correction_next_steps(blocking, renew=bool(correction_notes))))
        status: ResultStatus = "ok" if ok else (
            "fault" if latched or error_code == "fault_latched" else
            "busy" if error_code == "instrument_busy" else ("blocked" if state.refused else "error"))
        return RunSummary(
            ok=ok, status=status, backend=backend, simulated=backend == "sim", message=final.message,
            error_code=None if ok else error_code,
            next_steps=next_steps,
            run_id=folder.run_id, plan_id=plan.plan_id, outcome=outcome, status_counts=counts,
            quality_verdict=quality.verdict if quality else None, analyses=analyses,
            cleanup_verified=cleanup.verified if cleanup else None, artifacts=artifacts,
            summary=plan.summary if confirmed_summary is not None else None,
        )

    def _analyse(self, folder: RunFolder, table: Any, manifest: RunManifest, recipe: Recipe,
                 artifacts: dict[str, str]) -> tuple[QualityReport, list[ExtractionResult], list[str]]:
        """Write the run table (``data.csv``, or ``data.npz`` + ``preview.csv``) and ``quality.json`` and run the
        recipe's default analyses."""
        tidy = with_trust(table, recipe.quality)
        artifacts["data"] = folder.write_table(tidy).name
        if (folder.path / PREVIEW_FILE).is_file():
            artifacts["preview"] = PREVIEW_FILE
        data = RunData(manifest=manifest, table=tidy, path=folder.path)
        quality = assess_quality(data, recipe.quality)
        folder.write_quality(quality)
        artifacts["quality"] = QUALITY_FILE
        flags: list[str] = []
        if quality.verdict != "ok":
            flags.append(f"data quality {quality.verdict}")
        results: list[ExtractionResult] = []
        for spec in recipe.analysis_defaults:
            try:
                out = run_method(spec.method, data, spec.options, criteria=recipe.quality)
            except B1500Error as exc:
                rel = folder.add_analysis(spec.method, analysis_payload(spec.method, spec.options, None,
                                                                        source="analysis_defaults", error=str(exc),
                                                                        error_code=exc.code))
                flags.append(f"{spec.method}: {exc}")
                artifacts[rel] = rel
                continue
            plots = folder.add_plots(out) if isinstance(out, PlotSet) else None
            rel = folder.add_analysis(spec.method, analysis_payload(spec.method, spec.options, out,
                                                                    source="analysis_defaults", plots=plots))
            artifacts[rel] = rel
            if isinstance(out, list):
                results.extend(out)
                flags.extend(f"{r.method}: {r.outcome} ({r.error})" for r in out if r.outcome != "ok")
        return quality, results, flags

    @staticmethod
    def _assumptions(bundle: ConfigBundle, plan: PlanRecord) -> list[str]:
        out = []
        if bundle.backend == "sim":
            scenario = bundle.sim_scenario.name if bundle.sim_scenario is not None else "unknown"
            out.append(f"SIMULATED: data come from the simulator scenario {scenario}, not from a device")
        if plan.kind in ("smu_staircase", "smu_stepped"):
            out.append("sweep with automatic abort on compliance/overflow/oscillation (WM 2,1); duration estimate "
                       "assumes 50 Hz line frequency")
        if plan.kind == "smu_stepped":
            out.append("host loop: one sweep per step value in one transaction; the loop stops after a sweep that "
                       "reported compliance/overflow/oscillation (see kind_result)")
        if plan.kind == "smu_sampling":
            out.append("sampling (MM 10) with automatic abort on compliance/overflow/oscillation (MSC 2,2): an "
                       "aborted block ends the run (see kind_result); t_s from the instrument time stamps since the "
                       "bias step; runs over 60 s of sampling are chains of 25 s blocks holding the stress")
        if plan.kind == "smu_pulsed":
            out.append("pulsed measurement (MM 3/4/5/27/28): each value is measured at the end of a pulse with the "
                       "pulsed ADC's time (AIT 2); sweeps abort on compliance/overflow/oscillation (WM 2,1); a host "
                       "list of pulse levels stops after a trigger that reported one (see kind_result)")
        if plan.kind == "smu_search":
            out.append("search measurement (linear or binary search, quasi-pulsed spot): one result found by the "
                       "instrument (the source value at the target, or the voltage at the breakdown detection), not a "
                       "curve; status G = target not found in the range, S = stopped early (see kind_result)")
        if plan.kind == "stress_measure":
            out.append("stress-measure: the stress and recovery holds are timed by the instrument (sampling blocks of "
                       "at most 25 s, one monitor sample each); t_s is the cumulative hold time (the reads interrupt "
                       "it); the run stops after a hold block or read that reported compliance/overflow/oscillation "
                       "(see kind_result)")
        if plan.mode == "async":
            out.append("asynchronous run: progress.json and partial.csv written at the checkpoints; auto-calibration "
                       "off (CM 0) during the run and restored by the cleanup (R-CAL-02)")
        return out

    @staticmethod
    def _next_steps(outcome: RunOutcome, latched: bool, quality: QualityReport | None,
                    error_code: ErrorCode | None = None) -> list[str]:
        if latched:
            return ["the fault latch is set: call safe_shutdown and load skill b1500-debug; only a human clears it"]
        if error_code == "instrument_busy":
            return [("another client holds the instrument bus (EasyEXPERT or a second program); nothing was sent: "
                     "ask the human to close it, then retry")]
        if outcome == "completed":
            return ["get_run for the data; analyze_run for further extractions"]
        if outcome == "completed_with_flags":
            steps = ["check the quality report before using any extracted value"]
            if quality is not None and quality.verdict == "untrusted":
                steps.append("never report values extracted from untrusted data; see skill b1500-debug")
            return steps
        if outcome == "refused":
            return ["read the blocking findings; only a human changes config/local/"]
        if outcome == "cancelled":
            return [("get_run(run_id, include=[progress, data]) shows the rows acquired before the cancel (partial "
                    "data); report them as partial")]
        return ["get_run for the audit excerpt; load skill b1500-debug"]


def _is_plan_id(value: str | None) -> bool:
    return isinstance(value, str) and _PLAN_ID.match(value) is not None


RAW_ARTIFACTS_LISTED = 8
"""Raw measurement files a run result names one by one; a run with more (a spot survey reads one block per spot
point, a long stepped run one per step) names the folder and the count instead, so ``run_plan`` stays within its
token budget (blueprint 5.1)."""


def _raw_artifacts(run_dir: str, raw_files: list[str]) -> dict[str, str]:
    """The raw-block entries of a run's artifacts: each file up to ``RAW_ARTIFACTS_LISTED``, else one ``raw`` entry
    with the folder, the count and the first and last file name."""
    if len(raw_files) <= RAW_ARTIFACTS_LISTED:
        return {rel: f"{run_dir}/{rel}" for rel in raw_files}
    first, last = raw_files[0].rsplit("/", 1)[-1], raw_files[-1].rsplit("/", 1)[-1]
    folder = raw_files[0].rsplit("/", 1)[0]
    return {folder: f"{run_dir}/{folder}/ ({len(raw_files)} files {first} .. {last})"}


def _checkpoint_total(kind: Any, plan: PlanRecord) -> int:
    """The number of checkpoints the kind will report for ``plan`` (``kind.checkpoint_total(plan)``; 0 = unknown)."""
    counter = getattr(kind, "checkpoint_total", None)
    try:
        return int(counter(plan)) if callable(counter) else 0
    except (TypeError, ValueError):
        return 0


def _error_code(exc: BaseException) -> ErrorCode:
    """The result error code of an exception raised during a run (``internal`` for anything unexpected, including
    an ``EnvelopeViolation``, which means a kind tried to leave its own compiled envelope)."""
    return exc.code if isinstance(exc, B1500Error) else "internal"
