"""Running runs of an ``Executor`` (blueprint v2 2.6): which run holds the instrument now (this process's
asynchronous run or any process's run seen through its in-flight marker and the held instrument lock), stopping this
process's run (the MCP server's shutdown hook, the CLI's Ctrl-C, ``Executor.close``), following it in the foreground
(CLI) and archiving the run of a process that died inside its transaction (``Session.on_recovery``).

``RunningRuns`` is a mixin of ``Executor`` (``catalog/executor.py``); it uses the executor's ``config``, ``runner``,
``adapter``, ``session``, ``registry`` and ``_assumptions``. File reads and archive writes only: nothing
here talks to the instrument.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from b1500_test_agent.analysis.dataset import MANIFEST_FILE
from b1500_test_agent.archive.audit import read_audit
from b1500_test_agent.archive.runfiles import read_progress
from b1500_test_agent.archive.store import RunStore, process_software_version
from b1500_test_agent.catalog.planner import PlanError, PlanStore
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.errors import B1500Error, InvalidConfigError
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.plan import PlanRecord, RunProgress
from b1500_test_agent.models.run import Adapter, CleanupReport, ClientInfo, RunManifest, RunSummary
from b1500_test_agent.session import InflightMarker, RunJob

if TYPE_CHECKING:
    from b1500_test_agent.catalog.registry import RecipeRegistry
    from b1500_test_agent.config import ConfigLoader
    from b1500_test_agent.session import Runner, Session

CANCEL_MARGIN_S = 30.0
"""Allowance for a cancelled run's cleanup and archive, beyond one segment (``segment_max_s``)."""
DEFAULT_SEGMENT_S = 30.0
"""``policy.run_limits.segment_max_s`` default, used while the configuration cannot be read."""


@dataclass(frozen=True)
class ActiveRun:
    """The run holding the instrument now: an asynchronous run of this process (``job``) or a run of another process
    seen through its in-flight marker and the held instrument lock (``progress`` from its ``progress.json``, ``plan``
    from the plan store)."""

    run_id: str
    plan_id: str | None
    recipe_id: str | None
    mode: str
    adapter: str | None
    pid: int | None
    started_at: datetime | None
    progress: RunProgress | None
    plan: PlanRecord | None = None
    dut_instance: str | None = None
    confirmed_via: str | None = None
    job: RunJob | None = None

    def describe(self) -> str:
        """``run <id> (<done>/<total>)``, ``run <id> (starting)`` or ``run <id> (synchronous)``."""
        if self.progress is not None:
            return f"run {self.run_id} ({self.progress.done}/{self.progress.total})"
        return f"run {self.run_id} ({'starting' if self.mode == 'async' else 'synchronous'})"



class RunningRuns:
    """Running-run helpers of ``Executor`` (see the module docstring); the executor provides ``session``,
    ``registry`` and ``_assumptions``."""

    config: ConfigLoader
    runner: Runner
    adapter: Adapter
    session: Callable[[ConfigBundle], Session]
    registry: Callable[..., RecipeRegistry]
    _assumptions: Callable[[ConfigBundle, PlanRecord], list[str]]

    def _job_run(self, job: RunJob, bundle: ConfigBundle | None = None) -> ActiveRun:
        plan = None
        if bundle is not None:
            try:
                plan = PlanStore(bundle.paths.state_dir).load(job.plan_id)
            except PlanError:
                plan = None
        return ActiveRun(run_id=job.run_id, plan_id=job.plan_id, recipe_id=job.recipe_id, mode=job.mode,
                         adapter=job.adapter, pid=os.getpid(), started_at=job.started_at, progress=job.progress,
                         plan=plan, dut_instance=job.dut_instance, confirmed_via=job.confirmed_via, job=job)

    def active_run(self, bundle: ConfigBundle, *, include_local: bool = True,
                   include_foreign: bool = True) -> ActiveRun | None:
        """The run holding the instrument now (file reads only, no instrument I/O): this process's asynchronous run
        (``include_local``) or a run of any process seen through its in-flight marker and the held lock
        (``include_foreign``; its plan and progress come from the plan store and its ``progress.json``)."""
        job = self.runner.active() if include_local else None
        if job is not None:
            return self._job_run(job, bundle)
        if not include_foreign:
            return None
        marker = self.session(bundle).running_marker()
        if marker is None or marker.run is None:
            return None
        job = self.runner.last()
        if include_local is False and job is not None and job.run_id == marker.run and not job.done:
            return None
        progress: RunProgress | None = None
        plan: PlanRecord | None = None
        try:
            progress = read_progress(RunStore(bundle.paths.runs_dir).open(marker.run, unfinished=True).path)
        except B1500Error:
            progress = None
        if marker.plan_id is not None:
            try:
                plan = PlanStore(bundle.paths.state_dir).load(marker.plan_id)
            except PlanError:
                plan = None
        return ActiveRun(run_id=marker.run, plan_id=marker.plan_id, recipe_id=plan.recipe_id if plan else None,
                         mode=plan.mode if plan else "sync", adapter=marker.adapter, pid=marker.pid,
                         started_at=marker.since, progress=progress, plan=plan)

    def stop_runs(self, reason: str, *, adapter: Adapter | None = None, wait_s: float | None = None) -> bool:
        """Ask this process's asynchronous run to stop (abort file) and wait up to ``wait_s`` (default: one segment
        plus ``CANCEL_MARGIN_S``) for its verified cleanup and archive; True when no run of this process is left.
        Used by the MCP server's shutdown hook and the CLI's Ctrl-C; ``safe_shutdown`` does the same for any
        process's run."""
        job = self.runner.active()
        if job is None:
            return True
        abort = job.control.abort.file  # the run's own state directory, whatever the configuration says now
        request = abort.request(reason, adapter=adapter or self.adapter, run_id=job.run_id)
        segment_s = DEFAULT_SEGMENT_S
        try:
            bundle = self.config.get()
            segment_s = bundle.policy.run_limits.segment_max_s
            self.session(bundle).audit.emit(AuditEvent.now(
                "abort_requested", bundle.backend, run=job.run_id, data={
                    "request": request.id, "reason": request.reason, "target": job.run_id, "by": request.adapter}))
        except (InvalidConfigError, OSError):
            pass  # the request itself is written; only its audit line is missing
        finished = job.wait(segment_s + CANCEL_MARGIN_S if wait_s is None else wait_s)
        if finished:
            abort.withdraw(request.id)  # no-op when the run consumed it
        return finished

    def follow(self, run_id: str, *, on_progress: Callable[[RunProgress], None] | None = None,
               poll_s: float = 0.5) -> RunSummary | None:
        """Wait for this process's asynchronous run ``run_id`` and return its final summary (``None`` when it is not
        a run of this process); ``on_progress`` sees every new progress record. A ``KeyboardInterrupt`` raised
        while waiting propagates (the caller asks the run to stop and follows again)."""
        job = self.runner.last()
        if job is None or job.run_id != run_id:
            return None
        seen: RunProgress | None = None
        while not job.wait(poll_s):
            progress = job.progress
            if on_progress is not None and progress is not None and progress != seen:
                seen = progress
                on_progress(progress)
        if on_progress is not None and job.progress is not None and job.progress != seen:
            on_progress(job.progress)
        if isinstance(job.result, RunSummary):
            return job.result
        error = job.error
        backend = "sim" if run_id.startswith("S") else "visa"
        return RunSummary(ok=False, status="error", backend=backend, simulated=backend == "sim", outcome="aborted",
                          error_code="internal", run_id=run_id, plan_id=job.plan_id,
                          message=f"run {run_id} ended with {type(error).__name__ if error else 'no result'}: "
                                  f"{error}")

    def _finalize_orphan(self, bundle: ConfigBundle, marker: InflightMarker, report: CleanupReport) -> None:
        """``Session.on_recovery``: archive the run of a process that died inside its transaction (in-flight marker
        recovered) as ``aborted``, with the recovery cleanup as its cleanup report. Runs that are already finalized,
        unknown or whose plan is gone are left as they are. A run the human had confirmed keeps that record: its own
        ``tier_check`` audit event says ``confirmed``, and the executor runs a confirmed plan only when the echoed
        summary equals the plan's, so the manifest gets ``confirmed_summary`` = the plan summary (WP7.7: a harness
        that kills the MCP server mid-run otherwise lost the consent record)."""
        if marker.run is None:
            return
        store = RunStore(bundle.paths.runs_dir)
        try:
            folder = store.open(marker.run, unfinished=True)
        except B1500Error:
            return
        if (folder.path / MANIFEST_FILE).is_file() or marker.plan_id is None:
            return
        try:
            plan = PlanStore(bundle.paths.state_dir).load(marker.plan_id)
        except PlanError:
            return
        registry = self.registry(bundle)
        status = registry.get(plan.recipe_id).status if plan.recipe_id in registry.ids() else "draft"
        progress = None
        try:
            progress = read_progress(folder.path)
            if progress is not None and progress.state == "running":
                folder.write_progress(progress.model_copy(update={"state": "failed", "eta_s": 0.0,
                                                                  "updated_at": datetime.now(UTC)}))
        except B1500Error:
            progress = None
        at = f" at {progress.done}/{progress.total}" if progress is not None else ""
        message = (f"the process running this run (pid {marker.pid}, {marker.adapter or 'unknown adapter'}) ended "
                   f"without finalizing it{at}; the in-flight recovery of the next transaction ran the cleanup "
                   f"({report.verified}); rows acquired so far, if any, are in partial.csv")
        started = marker.since or datetime.now(UTC)
        confirmed = any(e.data and e.data.get("confirmed") is True and e.data.get("plan_id") == plan.plan_id
                        for e in read_audit(folder.path, events=["tier_check"]))
        manifest = RunManifest(
            run_id=marker.run, plan=plan, plan_hash=plan.plan_hash, recipe_id=plan.recipe_id,
            recipe_version=plan.recipe_version, recipe_sha=plan.recipe_sha, recipe_status=status,
            backend=bundle.backend, simulated=bundle.backend == "sim", hashes=dict(plan.hashes), config_files=[],
            rules=[plan.rules], tier=plan.tier, client=ClientInfo(adapter=marker.adapter or "cli"),
            confirmed_summary=plan.summary if confirmed else None,
            confirmed_via=None if not confirmed else (
                "run_confirmed_plan" if marker.adapter == "mcp" else "cli --confirm"),
            software_version=process_software_version(), started_at=started, finished_at=datetime.now(UTC),
            outcome="aborted", error_code="internal", message=message, cleanup=report,
            assumptions=[*self._assumptions(bundle, plan), ("finalized by the in-flight recovery of a later "
                         "transaction (the run's own process ended without finalizing it)")],
        )
        folder.audit.emit(AuditEvent.now("run_status", bundle.backend, run=marker.run, data={
            "outcome": "aborted", "error_code": "internal", "cleanup": report.verified, "recovered": True}))
        folder.finalize(manifest)
