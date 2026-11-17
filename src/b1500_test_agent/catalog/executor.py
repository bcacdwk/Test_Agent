"""``Executor``: validate → plan id → run, with the tier and summary checks of blueprint 2.6 and 4.3.

``Executor.plan(req)`` resolves, binds, compiles, evaluates the plan-phase rules and stores the frozen plan
(``catalog/planner.py``). ``Executor.run(plan_id, confirmed_summary=..., dut_instance=..., client=...)`` follows the
blueprint 2.6 docstring:

1. load the plan (unknown, or content not hashing to its id → ``unknown_plan``; past its TTL → ``plan_expired``;
   recipe, config hashes or backend changed → ``plan_stale``);
2. effective status ``not_implemented`` → refuse;
3. re-run the plan-phase rules, never trusting the stored tier: ``blocked`` → ``blocked_by_rules``;
   ``needs_confirmation`` without a summary → ``confirmation_required``; a summary that differs from the fresh
   ``plan_summary`` → ``summary_mismatch`` (the fresh summary is returned). Steps 1-3 do ZERO transport I/O (they
   read only plan, config, recipe and state files);
4. ``Session.transaction`` (fault-latch check, lock, inflight marker, recovery, baseline drain), a live snapshot and
   the ``pre_execute`` rules under the lock (``blocked`` → refuse; no source command is ever sent);
5. ``kind.acquire`` through the guarded driver; every raw read lands in ``raw/block-NNN.txt`` before parsing;
6. after the transaction's cleanup: table (``data.csv``), ``quality.json``, the recipe's default analyses
   (``analysis/<method>-<n>.json``), then the manifest (written once) and the index line.

``run`` never raises to adapters (except a ``KeyboardInterrupt``/``SystemExit``, re-raised after the run folder is
finalized as ``aborted``); every outcome is a ``RunSummary``. The run folder is created right before the
transaction so that the lock, the snapshot and the cleanup I/O are in the run's ``audit.jsonl``; when the
transaction is refused before anything was recorded (instrument busy, fault latched) the empty folder is removed.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from b1500_test_agent.analysis.dataset import DATA_FILE, MANIFEST_FILE, RunData, with_trust
from b1500_test_agent.analysis.quality import assess_quality
from b1500_test_agent.analysis.registry import run_method
from b1500_test_agent.archive.audit import RUN_AUDIT_FILE
from b1500_test_agent.archive.store import QUALITY_FILE, RunFolder, RunStore, analysis_payload, software_version
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
from b1500_test_agent.catalog.schema import RawAcquisition
from b1500_test_agent.config import ConfigBundle, ConfigLoader
from b1500_test_agent.errors import B1500Error, InvalidConfigError
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport
from b1500_test_agent.models.audit import AuditEvent, AuditEventName
from b1500_test_agent.models.common import Backend, ErrorCode, ResultStatus
from b1500_test_agent.models.plan import PlanRecord, PlanRequest, RuleFinding, RulesReport
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.run import Adapter, CleanupReport, ClientInfo, RunManifest, RunOutcome, RunSummary
from b1500_test_agent.models.station import LiveState
from b1500_test_agent.rules import CalibrationState, RulesEngine, with_rules
from b1500_test_agent.session import (
    CleanupUnverified,
    FaultLatched,
    InstrumentBusy,
    Session,
    Transaction,
    state_audit_sink,
)
from b1500_test_agent.transport.audit import AuditSink
from b1500_test_agent.transport.base import Transport
from b1500_test_agent.transport.factory import make_transport

TransportFactory = Callable[[ConfigBundle, AuditSink], Transport]
SELF_CAL_RECIPE = "system.self_cal"
DUT_INSTANCE_MAX = 200
_PLAN_ID = re.compile(r"^P-[A-Z2-7]{10}$")


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


@dataclass
class _RunState:
    live: LiveState | None = None
    pre_report: RulesReport | None = None
    raw: RawAcquisition | None = None
    error: BaseException | None = None
    refused: bool = False


def _flags(findings: list[RuleFinding], severity: str) -> str:
    return "; ".join(f"{f.rule_id} {f.message}" for f in findings if f.severity == severity)


class Executor:
    """Plans and runs recipes for one process (blueprint 2.6). ``config`` is re-read on every call (digest cache).

    ``registry`` defaults to ``recipes/`` of the configured repository and is reloaded when a recipe file changes;
    ``transport_factory`` replaces ``make_transport`` (tests); ``clock`` stamps plans and run ids.
    """

    def __init__(self, config: ConfigLoader, *, registry: RecipeRegistry | None = None, adapter: Adapter = "cli",
                 clock: Callable[[], datetime] | None = None, transport_factory: TransportFactory | None = None,
                 lock_timeout_s: float = 5.0) -> None:
        self.config = config
        self.adapter: Adapter = adapter
        self.lock_timeout_s = lock_timeout_s
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._transport_factory = transport_factory
        self._session: Session | None = None
        self._session_key: str | None = None

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
        ], sort_keys=True)
        if self._session is None or key != self._session_key:
            if self._session is not None:
                self._session.close()
            sink = state_audit_sink(state_dir)
            custom = self._transport_factory

            def factory() -> Transport:
                if custom is not None:
                    return custom(bundle, sink)
                return make_transport(bundle.settings, sink, scenario=bundle.sim_scenario, faults=bundle.sim_faults,
                                      state_dir=state_dir)

            self._session = Session(bundle.settings, factory, sink, state_dir=state_dir, adapter=self.adapter)
            self._session_key = key
        return self._session

    def close(self) -> None:
        """Close the session's transport (a later call opens it again)."""
        if self._session is not None:
            self._session.close()

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
        registry = self.registry(bundle)
        session = self.session(bundle)
        fault, unrecovered = self._fault_state(session)
        plan = Planner(registry, clock=self._clock).plan(req, bundle, self._engine(bundle), live=live, fault=fault,
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
        plan, _, _ = self._load_checked(plan_id, bundle)
        return self._fresh(plan, bundle)[0]

    def _load_checked(self, plan_id: str, bundle: ConfigBundle) -> tuple[PlanRecord, Recipe, MeasurementKind | None]:
        """Step 1: load, expiry, staleness (file reads only)."""
        plan = PlanStore(bundle.paths.state_dir).load(plan_id)
        now = self._clock()
        ttl_end = plan.created_at + timedelta(hours=bundle.policy.plans.ttl_h)
        if now >= min(plan.expires_at, ttl_end):
            raise PlanExpiredError(f"plan {plan_id} expired at {min(plan.expires_at, ttl_end).isoformat()}; "
                                   "validate the request again")
        registry = self.registry(bundle)
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
        return plan, recipe, registry.kinds.get(recipe.kind)

    def _fresh(self, plan: PlanRecord, bundle: ConfigBundle) -> tuple[PlanRecord, RulesReport]:
        """Step 3: the plan-phase rules again (never the stored tier), with the current fault/inflight state."""
        session = self.session(bundle)
        fault, unrecovered = self._fault_state(session)
        planner = Planner(self.registry(bundle), clock=self._clock)
        ctx = planner.context(plan, bundle, fault=fault, inflight_unrecovered=unrecovered)
        report = self._engine(bundle).evaluate(ctx, "plan")
        return with_rules(plan, report), report

    def _check(self, plan_id: str, bundle: ConfigBundle, confirmed_summary: str | None) -> _Checked:
        """Steps 1-3 (zero transport I/O); raises ``_Refusal``."""
        try:
            plan, recipe, kind = self._load_checked(plan_id, bundle)
        except PlanError as exc:
            next_steps = ["validate the request again with validate_plan"]
            raise _Refusal("refused", exc.code, "refused", str(exc), next_steps) from None
        registry = self.registry(bundle)
        if kind is None or registry.effective_status(recipe.id, bundle.backend) == "not_implemented":
            raise _Refusal("not_implemented", "not_implemented", "not_implemented",
                           f"recipe {recipe.id} (kind {recipe.kind}) is not implemented on backend {bundle.backend}",
                           ["list validated alternatives with list_recipes; never improvise instrument code"])
        fresh, report = self._fresh(plan, bundle)
        if report.tier == "blocked":
            raise _Refusal("blocked", "blocked_by_rules", "refused",
                           f"plan {plan_id} is blocked: {_flags(report.findings, 'block')}",
                           [("explain the blocking rules and offer an in-envelope alternative; only a human edits "
                            "config/local/")], summary=fresh.summary)
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
        return _Checked(plan=fresh, recipe=recipe, kind=kind, report=report)

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

    def _execute(self, checked: _Checked, bundle: ConfigBundle, *, confirmed_summary: str | None,
                 dut_instance: str | None, client: ClientInfo, started: datetime) -> RunSummary:
        plan, kind = checked.plan, checked.kind
        session = self.session(bundle)
        store = RunStore(bundle.paths.runs_dir)
        folder = store.create(bundle.backend, now=self._clock())
        calibration = self._calibration(bundle)
        planner = Planner(self.registry(bundle), clock=self._clock)
        state = _RunState()
        tx = session.transaction(intent=f"run {plan.recipe_id} ({plan.plan_id})", envelope=plan.envelope,
                                 run=folder, lock_timeout_s=self.lock_timeout_s, plan_id=plan.plan_id)
        t0 = time.monotonic()
        try:
            with tx:
                self._emit(folder, tx, "tier_check", {
                    "plan_id": plan.plan_id, "tier": checked.report.tier,
                    "confirm_reasons": ", ".join(checked.report.confirm_reasons),
                    "confirmed": confirmed_summary is not None})
                state.live = tx.snapshot()
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
                    state.raw = kind.acquire(tx, plan)
        except (InstrumentBusy, FaultLatched) as exc:
            if folder.is_empty():
                folder.discard()
                status: ResultStatus = "busy" if isinstance(exc, InstrumentBusy) else "fault"
                next_steps = (["retry later; another process holds the instrument"] if status == "busy"
                              else ["call safe_shutdown and load skill b1500-debug; only a human clears the fault"])
                return self._summary(bundle, plan.plan_id, ok=False, status=status, outcome="refused",
                                     error_code=exc.code, message=str(exc), next_steps=next_steps)
            state.error = exc
        except BaseException as exc:  # noqa: BLE001 - recorded in the run; interrupts re-raised after finalize
            state.error = exc
        transaction_s = time.monotonic() - t0
        cleanup = tx.cleanup
        if isinstance(state.error, CleanupUnverified):
            cleanup = state.error.report
        summary = self._finish(checked, bundle, folder, state, cleanup, confirmed_summary=confirmed_summary,
                               dut_instance=dut_instance, client=client, started=started, transaction_s=transaction_s)
        if state.error is not None and not isinstance(state.error, Exception):
            raise state.error
        return summary

    @staticmethod
    def _emit(folder: RunFolder, tx: Transaction, ev: AuditEventName, data: dict[str, Any]) -> None:
        folder.audit.emit(AuditEvent.now(ev, tx.driver.transport.backend, run=folder.run_id, tx=tx.tx_id,
                                         intent=tx.intent, data=data))

    # -- step 6 -----------------------------------------------------------------------------------------------------

    def _finish(self, checked: _Checked, bundle: ConfigBundle, folder: RunFolder, state: _RunState,
                cleanup: CleanupReport | None, *, confirmed_summary: str | None, dut_instance: str | None,
                client: ClientInfo, started: datetime, transaction_s: float) -> RunSummary:
        plan, recipe, kind = checked.plan, checked.recipe, checked.kind
        backend = bundle.backend
        reports = [checked.report] + ([state.pre_report] if state.pre_report is not None else [])
        manifest = RunManifest(
            run_id=folder.run_id, plan=plan, plan_hash=plan.plan_hash, recipe_id=recipe.id,
            recipe_version=recipe.version, recipe_sha=recipe.sha256,
            recipe_status=self.registry(bundle).effective_status(recipe.id, backend), backend=backend,
            simulated=backend == "sim",
            identity=state.live.identity if state.live else None,
            inventory=state.live.inventory if state.live else None,
            hashes=dict(plan.hashes), config_files=list(bundle.files.values()), rules=reports, tier=plan.tier,
            confirmed_summary=confirmed_summary.strip() if confirmed_summary is not None else None,
            confirmed_via=None if confirmed_summary is None else (
                "run_confirmed_plan" if client.adapter == "mcp" else "cli --confirm"),
            client=client, software_version=software_version(), dut_instance=dut_instance, started_at=started,
            outcome="completed", cleanup=cleanup, assumptions=self._assumptions(bundle, plan),
        )
        error_code: ErrorCode | None = None
        message = ""
        quality: QualityReport | None = None
        analyses: list[ExtractionResult] = []
        flags: list[str] = []
        artifacts: dict[str, str] = {}
        outcome: RunOutcome
        if state.error is not None:
            exc = state.error
            outcome = "aborted" if not isinstance(exc, Exception) else (
                "refused" if isinstance(exc, FaultLatched) else "failed")
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
                if table is not None:
                    quality, analyses, flags = self._analyse(folder, table, manifest, recipe, artifacts)
            except Exception as exc:  # noqa: BLE001 - the raw data stay archived; the run is failed
                outcome, error_code = "failed", _error_code(exc)
                message = f"processing the acquired data failed: {type(exc).__name__}: {exc}"
        if outcome == "completed":
            if cleanup is not None and cleanup.errors:
                flags.append("instrument errors drained at cleanup: "
                             + ", ".join(f"{e.code} {e.message}".strip() for e in cleanup.errors))
            if flags:
                outcome = "completed_with_flags"
                message = "; ".join(flags)
        if state.raw is not None:
            manifest = manifest.model_copy(update={"kind_result": dict(state.raw.kind_result)})
        counts = dict(quality.counts) if quality is not None else {}
        quality_findings = (self._engine(bundle).quality(counts, recipe=recipe,
                                                         recipe_source=self.registry(bundle).source(recipe.id))
                            if quality is not None else [])
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
        paths = bundle.paths
        artifacts = {"run_dir": paths.display(folder.path),
                     "manifest": paths.display(folder.path / MANIFEST_FILE),
                     "audit": paths.display(folder.path / RUN_AUDIT_FILE),
                     **{name: paths.display(folder.path / rel) for name, rel in artifacts.items()},
                     **{rel: paths.display(folder.path / rel) for rel in folder.raw_files}}
        ok = outcome in ("completed", "completed_with_flags")
        latched = cleanup is not None and cleanup.latched_fault
        status: ResultStatus = "ok" if ok else (
            "fault" if latched or error_code == "fault_latched" else ("blocked" if state.refused else "error"))
        return RunSummary(
            ok=ok, status=status, backend=backend, simulated=backend == "sim", message=final.message,
            error_code=None if ok else error_code, next_steps=self._next_steps(outcome, latched, quality),
            run_id=folder.run_id, plan_id=plan.plan_id, outcome=outcome, status_counts=counts,
            quality_verdict=quality.verdict if quality else None, analyses=analyses,
            cleanup_verified=cleanup.verified if cleanup else None, artifacts=artifacts,
            summary=plan.summary if confirmed_summary is not None else None,
        )

    def _analyse(self, folder: RunFolder, table: Any, manifest: RunManifest, recipe: Recipe,
                 artifacts: dict[str, str]) -> tuple[QualityReport, list[ExtractionResult], list[str]]:
        """Write ``data.csv`` and ``quality.json`` and run the recipe's default analyses."""
        tidy = with_trust(table, recipe.quality)
        folder.write_table(tidy)
        artifacts["data"] = DATA_FILE
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
            rel = folder.add_analysis(spec.method, analysis_payload(spec.method, spec.options, out,
                                                                    source="analysis_defaults"))
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
        if plan.kind == "smu_staircase":
            out.append("sweep with automatic abort on compliance/overflow/oscillation (WM 2,1); duration estimate "
                       "assumes 50 Hz line frequency")
        return out

    @staticmethod
    def _next_steps(outcome: RunOutcome, latched: bool, quality: QualityReport | None) -> list[str]:
        if latched:
            return ["the fault latch is set: call safe_shutdown and load skill b1500-debug; only a human clears it"]
        if outcome == "completed":
            return ["get_run for the data; analyze_run for further extractions"]
        if outcome == "completed_with_flags":
            steps = ["check the quality report before using any extracted value"]
            if quality is not None and quality.verdict == "untrusted":
                steps.append("never report values extracted from untrusted data; see skill b1500-debug")
            return steps
        if outcome == "refused":
            return ["read the blocking findings; only a human changes config/local/"]
        return ["get_run for the audit excerpt; load skill b1500-debug"]


def _is_plan_id(value: str | None) -> bool:
    return isinstance(value, str) and _PLAN_ID.match(value) is not None


def _error_code(exc: BaseException) -> ErrorCode:
    """The result error code of an exception raised during a run (``internal`` for anything unexpected, including
    an ``EnvelopeViolation``, which means a kind tried to leave its own compiled envelope)."""
    return exc.code if isinstance(exc, B1500Error) else "internal"
