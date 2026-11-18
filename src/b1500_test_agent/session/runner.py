"""Run control and asynchronous runs (blueprint v2 2.6, decision 10).

``RunControl`` is what a running run consults at its checkpoints. ``Transaction.checkpoint(done, total, phase, rows)``
hands it every segment boundary (each segment lasts at most ``policy.run_limits.segment_max_s``, R-RUN-02):

- an asynchronous run (``mode == "async"``) records its progress there: ``progress.json`` (``RunProgress``: done/total
  checkpoint units, phase, elapsed and estimated remaining wall time, the newest measured values) and the rows
  acquired so far appended to ``partial.csv``. Writes are throttled to one per ``progress_interval_s`` of wall time
  (rows are buffered meanwhile) and always flushed before a cancel and at the end, so a 4 h simulated run on
  ``timing: instant`` costs a handful of writes and a real run, whose segments take seconds, writes at every
  checkpoint. A failed progress write never stops the measurement (it is audited);
- every run, synchronous or not, polls the abort file there (``AbortWatch``; ``session/abort.py``) and raises
  ``RunCancelled``, so ``safe_shutdown`` from any process stops it within one segment, with the transaction's
  verified cleanup;
- a synchronous run keeps its rows in memory and writes them to ``partial.csv`` only when it does not complete
  (cancelled, failed, interrupted), so a completed synchronous run folder is exactly the v1 one.

``Runner`` keeps the one asynchronous run of a process on a non-daemon worker thread (``RunJob``): the caller gets
control back once the run has started (``RunJob.started``: lock taken, pre-execute rules passed) or finished
(refused, busy, failed before starting); the interpreter waits for the worker at exit, so a started run always
completes its cleanup unless the process is killed (then the next transaction's in-flight recovery does it). One
active run per instrument across processes is the instrument lock's job; ``Runner`` refuses a second run of the same
process at once (``busy``) instead of letting it wait for the lock.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd

from b1500_test_agent.models.plan import RunProgress
from b1500_test_agent.session.abort import AbortWatch

RunMode = Literal["sync", "async"]
ProgressState = Literal["running", "completed", "cancelled", "failed"]
Rows = pd.DataFrame | Sequence[Mapping[str, object]]
"""Rows of the run table (``analysis/dataset.py`` columns) acquired in one segment."""
RowsSource = Rows | Callable[[], Rows | None] | None
"""Rows, or a callable that builds them (called only when the run records progress)."""
Warn = Callable[[str, BaseException], None]

PROGRESS_INTERVAL_S = 0.5
"""Least wall time between two progress writes (rows are buffered in between; flushed at a cancel and the end)."""
LAST_VALUES_MAX = 8
"""Most columns ``RunProgress.last_values`` shows."""
_NOT_VALUES = frozenset({"step", "trust"})

log = logging.getLogger("b1500.runner")


def _as_frame(rows: Rows) -> pd.DataFrame:
    return rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))


def last_values(frame: pd.DataFrame) -> dict[str, float]:
    """The newest finite numeric values of ``frame`` by column (``step``, ``trust`` and status columns left out)."""
    if frame.empty:
        return {}
    values: dict[str, float] = {}
    for column, value in frame.iloc[-1].items():
        name = str(column)
        if name in _NOT_VALUES or name.endswith("_status") or isinstance(value, bool):
            continue
        if isinstance(value, int | float) and math.isfinite(float(value)):
            values[name] = float(value)
        if len(values) >= LAST_VALUES_MAX:
            break
    return values


class RunControl:
    """Checkpoint state of one run (see the module docstring).

    ``progress_sink`` writes a ``RunProgress`` (``RunFolder.write_progress``) and ``partial_sink`` appends rows
    (``RunFolder.append_partial`` with the recipe's trust policy); both are used only when ``mode == "async"``.
    ``estimate_s`` is the plan's duration estimate (the ETA before the first checkpoint).
    """

    def __init__(self, *, run_id: str, mode: RunMode, abort: AbortWatch,
                 progress_sink: Callable[[RunProgress], object] | None = None,
                 partial_sink: Callable[[pd.DataFrame], object] | None = None, estimate_s: float | None = None,
                 progress_interval_s: float = PROGRESS_INTERVAL_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.run_id = run_id
        self.mode: RunMode = mode
        self.abort = abort
        self.estimate_s = estimate_s
        self.progress_interval_s = progress_interval_s
        self._progress_sink = progress_sink
        self._partial_sink = partial_sink
        self._clock = clock
        self._t0 = clock()
        self._written_at: float | None = None
        self._buffer: list[pd.DataFrame] = []
        self._values: dict[str, float] = {}
        self.latest: RunProgress | None = None
        """The newest progress (read by other threads: ``station_status``, ``get_run`` of this process)."""
        self.checkpoints = 0
        self.write_failures = 0

    @property
    def records_progress(self) -> bool:
        """True for an asynchronous run with a progress sink (writes ``progress.json``/``partial.csv``)."""
        return self.mode == "async" and self._progress_sink is not None

    @property
    def collects_rows(self) -> bool:
        """True when segment rows are kept for ``partial.csv`` (a partial sink is set)."""
        return self._partial_sink is not None

    @property
    def elapsed_s(self) -> float:
        return max(0.0, self._clock() - self._t0)

    def _eta(self, done: int, total: int) -> float | None:
        if total and done >= total:
            return 0.0
        if done > 0 and total:
            return round(self.elapsed_s / done * (total - done), 3)
        return None if self.estimate_s is None else round(self.estimate_s, 3)

    def _progress(self, state: ProgressState, done: int, total: int, phase: str) -> RunProgress:
        total = max(total, done)
        eta = 0.0 if state != "running" else self._eta(done, total)
        return RunProgress(state=state, done=done, total=total, phase=phase[:80], elapsed_s=round(self.elapsed_s, 3),
                           eta_s=eta, last_values=dict(self._values), updated_at=datetime.now(UTC))

    def begin(self, total: int, phase: str = "start") -> None:
        """Record the start (``0/total``) of the run (written at once for an asynchronous run)."""
        self.latest = self._progress("running", 0, total, phase)
        if self.records_progress:
            self._write(force=True, warn=None)

    def checkpoint(self, done: int, total: int, phase: str = "", rows: RowsSource = None, *,
                   warn: Warn | None = None) -> None:
        """A segment ended: keep its rows, record progress (asynchronous runs), then raise ``RunCancelled`` if an
        abort applies.

        Raises:
            RunCancelled: When an abort request applies (progress and rows are flushed first).
        """
        self.checkpoints += 1
        if self.collects_rows:
            try:
                built = rows() if callable(rows) else rows
                if built is not None:
                    frame = _as_frame(built)
                    if not frame.empty:
                        self._buffer.append(frame)
                        self._values = last_values(frame)
            except Exception as exc:  # noqa: BLE001 - rows are a view; the measurement goes on
                self.write_failures += 1
                if warn is not None:
                    warn("partial rows could not be built", exc)
        self.latest = self._progress("running", done, total, phase)
        request = self.abort.pending()
        if self.records_progress:
            self._write(force=request is not None, warn=warn)
        elif request is not None:
            self._flush_rows(warn)
        self.abort.check()

    def check_abort(self) -> None:
        """Raise ``RunCancelled`` when an abort applies (readback loops call this at least once a second)."""
        self.abort.check()

    def finish(self, state: ProgressState, *, warn: Warn | None = None) -> RunProgress | None:
        """End of the run: an asynchronous run flushes its rows and writes the final progress; a synchronous run that
        did not complete writes the rows it kept. Returns the final progress (``None`` before any checkpoint of a
        synchronous run)."""
        last = self.latest
        if last is not None or self.records_progress:
            done, total, phase = (last.done, last.total, last.phase) if last is not None else (0, 0, "")
            self.latest = self._progress(state, done, total, phase)
        if self.records_progress:
            self._write(force=True, warn=warn)
        elif state != "completed":
            self._flush_rows(warn)
        else:
            self._buffer = []
        return self.latest

    def _flush_rows(self, warn: Warn | None) -> None:
        if not self._buffer or self._partial_sink is None:
            return
        chunk = pd.concat(self._buffer, ignore_index=True) if len(self._buffer) > 1 else self._buffer[0]
        self._buffer = []
        try:
            self._partial_sink(chunk)
        except Exception as exc:  # noqa: BLE001 - audited; the measurement goes on
            self.write_failures += 1
            if warn is not None:
                warn("partial.csv append failed", exc)

    def _write(self, *, force: bool, warn: Warn | None) -> None:
        now = self._clock()
        if not force and self._written_at is not None and now - self._written_at < self.progress_interval_s:
            return
        self._written_at = now
        self._flush_rows(warn)
        if self.latest is not None and self._progress_sink is not None:
            try:
                self._progress_sink(self.latest)
            except Exception as exc:  # noqa: BLE001 - audited; the measurement goes on
                self.write_failures += 1
                if warn is not None:
                    warn("progress.json write failed", exc)


# -- asynchronous runs -------------------------------------------------------------------------------------------------


class RunnerBusy(RuntimeError):
    """This process already runs an asynchronous run (``job`` is the active one)."""

    def __init__(self, job: RunJob) -> None:
        self.job = job
        super().__init__(f"run {job.run_id} is still running")


@dataclass(eq=False)
class RunJob:
    """One asynchronous run on its worker thread (see the module docstring)."""

    run_id: str
    plan_id: str
    recipe_id: str
    control: RunControl
    adapter: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    mode: RunMode = "async"
    dut_instance: str | None = None
    confirmed_via: str | None = None
    started: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    thread: threading.Thread | None = None

    @property
    def progress(self) -> RunProgress | None:
        return self.control.latest

    @property
    def done(self) -> bool:
        return self.finished.is_set()

    def wait_started(self, timeout_s: float | None) -> bool:
        """Block until the run has started or finished (``timeout_s`` ``None`` = no limit); True when one did."""
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while not (self.started.is_set() or self.finished.is_set()):
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            self.started.wait(0.05 if remaining is None else min(0.05, remaining))
        return True

    def wait(self, timeout_s: float | None) -> bool:
        """Block until the worker has finished (cleanup and archive included); True when it has."""
        return self.finished.wait(timeout_s)

    def describe(self) -> str:
        """``run <id> (<done>/<total>)`` or ``run <id> (starting)``."""
        progress = self.progress
        if progress is None:
            return f"run {self.run_id} (starting)"
        return f"run {self.run_id} ({progress.done}/{progress.total})"


class Runner:
    """The asynchronous run of one process (at most one at a time)."""

    def __init__(self) -> None:
        self._job: RunJob | None = None
        self._lock = threading.Lock()

    def active(self) -> RunJob | None:
        """The run whose worker has not finished yet, if any."""
        job = self._job
        return job if job is not None and not job.finished.is_set() else None

    def last(self) -> RunJob | None:
        """The most recent run of this process (finished or not)."""
        return self._job

    def start(self, job: RunJob, body: Callable[[Callable[[], None]], Any]) -> RunJob:
        """Run ``body(started)`` on a new non-daemon worker thread; ``body`` calls ``started()`` once the run is
        under way and returns the run's result (kept in ``job.result``). Raises ``RunnerBusy`` when a run is active.
        """
        with self._lock:
            active = self.active()
            if active is not None:
                raise RunnerBusy(active)

            def target() -> None:
                try:
                    job.result = body(job.started.set)
                except BaseException as exc:  # noqa: BLE001 - kept on the job; the run folder records it
                    job.error = exc
                    log.error("run %s ended with %s: %s", job.run_id, type(exc).__name__, exc)
                finally:
                    job.finished.set()

            job.thread = threading.Thread(target=target, name=f"b1500-run-{job.run_id}", daemon=False)
            self._job = job
            job.thread.start()
        return job
