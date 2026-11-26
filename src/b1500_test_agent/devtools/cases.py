"""``b1500 dev cases list|check|reproduce`` (v2.1 plan §3 items 2, 5 and 6): the review tooling of the debug cases of
skill ``b1500-debug`` and the runner of their simulator reproductions (schema and expression grammar:
``devtools/skills/cases.py``).

A reproduction always runs on the simulator, whatever the station: on a temporary copy of the committed ``config/``
(``config/local/`` is never read) with an override folder that selects ``backend: sim`` and the scenario of each step,
and on a data folder of its own: ``work/cases/<case>/<UTC stamp>/data`` for ``reproduce`` (kept, with ``report.json``
beside it), a temporary folder for ``list`` and ``check --reproduce``. A lab's run archive never sees a simulated run,
and the lab facts of a case never change (v2.1 D-6). Every run id is an ``S...`` id; every report says SIMULATED.

Steps run in order through ``B1500Service`` exactly as an agent's plans would: ``validate_plan``, then ``run_plan``
(tier ``ok``) or ``run_confirmed_plan`` with the plan's own summary (tier ``needs_confirmation``: the runner stands in
for the human's consent, simulator only); a ``blocked`` plan is not run. ``corrections: true`` first runs the
policy-required MFCMU corrections with the step's pin map. Afterwards the case's ``expect`` (symptom signature) and
``discriminator.expect`` expressions are evaluated over the steps; each reports pass, fail or error and the step
values it read, which is what a case quotes in its section "Simulator reproduction (SIMULATED)".
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import Field

from b1500_test_agent.analysis.dataset import load_run, status_column
from b1500_test_agent.analysis.errors import RunFormatError, RunNotFoundError
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.skills.cards import example_frequencies
from b1500_test_agent.devtools.skills.cases import (
    CASES_DIR,
    Case,
    ExpectationError,
    Reproduction,
    ReproStep,
    StepAccess,
    check_cases,
    evaluate_expectation,
)
from b1500_test_agent.devtools.skills.common import DEBUG_SKILL, RUNBOOKS_DIR, Lint, LintProblem
from b1500_test_agent.devtools.sync_harness import SOURCE_DIR
from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_DATA_DIR, Paths, find_repo_root
from b1500_test_agent.rules.builtin.cmu import CORRECTION_RECIPES
from b1500_test_agent.service import B1500Service

Verdict = Literal["pass", "fail", "error"]
REPORT_FILE = "report.json"


# == Reports ==========================================================================================================


class StepRecord(StrictModel):
    """What one reproduction step did (``S...`` runs only)."""

    id: str
    scenario: str
    recipe: str
    pin_map: str
    tier: str | None = None
    plan_id: str | None = None
    blocked_by: list[str] = Field(default_factory=list)
    confirm_reasons: list[str] = Field(default_factory=list)
    run_id: str | None = None
    outcome: str | None = None
    error_code: str | None = None
    quality_verdict: str | None = None
    message: str = ""
    corrections: list[str] = Field(default_factory=list)
    """Run ids of the correction runs made first (``corrections: true``)."""


class ExpectationRecord(StrictModel):
    """One evaluated expression: verdict, the step values it read and, for ``error``, why."""

    text: str
    verdict: Verdict
    terms: list[str] = Field(default_factory=list)
    error: str | None = None


class ReproductionReport(StrictModel):
    """One reproduction of one case; ``ok`` iff every step ran as planned and every expectation passed."""

    case: str
    ok: bool
    simulated: Literal[True] = True
    backend: Literal["sim"] = "sim"
    started_at: str
    commit: str
    data_dir: str | None = None
    """The run archive of this reproduction (``None``: a temporary folder, removed afterwards)."""
    steps: list[StepRecord] = Field(default_factory=list)
    expect: list[ExpectationRecord] = Field(default_factory=list)
    discriminator_check: str = ""
    discriminator: list[ExpectationRecord] = Field(default_factory=list)
    error: str | None = None


class CaseRow(StrictModel):
    """One case in ``b1500 dev cases list``."""

    id: str
    title: str
    status: str
    reviewed_by: str | None
    runbook: str
    origin: str
    backend: str
    runs: int
    reproduction: Literal["pass", "fail", "none", "not run"]
    open_questions: int


class CasesReport(StrictModel):
    """``b1500 dev cases list|check``: the cases, the case lint problems and (with reproduction) the reports."""

    ok: bool
    cases: list[CaseRow] = Field(default_factory=list)
    problems: list[LintProblem] = Field(default_factory=list)
    reproductions: list[ReproductionReport] = Field(default_factory=list)


class CaseRefused(LookupError):
    """``reproduce`` refuses a case: no valid case file of that id, no reproduction, or case lint problems."""


# == Loading ==========================================================================================================


def load_cases(root: Path | None = None) -> tuple[list[Case], list[LintProblem]]:
    """The valid cases under ``root`` (default: this clone) and the case lint problems (template and cases)."""
    root = Path(root).resolve() if root is not None else find_repo_root()
    lint = Lint(root, root / "recipes", root / "config")
    debug_dir = root / SOURCE_DIR / DEBUG_SKILL
    registry = RecipeRegistry.load(lint.recipes_dir, repo_root=root)
    runbooks = sorted(p.stem for p in (debug_dir / RUNBOOKS_DIR).glob("*.md"))
    cases = check_cases(lint, debug_dir, registry, runbooks)
    problems = sorted(lint.problems, key=lambda p: (p.file, p.line or 0, p.code, p.message))
    return cases, problems


# == Running ==========================================================================================================


class StepFailed(Exception):
    """A step could not run as declared (a correction run failed, the service refused a request unexpectedly)."""


@dataclass
class StepView:
    """The values of one executed step that the expectation grammar reads (``StepAccess``)."""

    record: StepRecord
    table: pd.DataFrame | None = None
    snr: dict[str, float] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    analyses: list[ExtractionResult] = field(default_factory=list)
    kind_result: dict[str, Any] = field(default_factory=dict)

    def attribute(self, name: str) -> Any:
        return getattr(self.record, name)

    def call(self, method: str, args: tuple[Any, ...]) -> Any:
        if self.record.run_id is None:
            raise ExpectationError(f"step {self.record.id} has no run (tier {self.record.tier}: "
                                   f"{self.record.message or 'not run'})")
        if method == "count":
            return self.status_counts.get(str(args[0]), 0)
        if method in ("status", "value", "value_at"):
            table = self._table(str(args[0]), *([str(args[1])] if method == "value_at" else []))
            row = self._nearest(table, str(args[1]), args[2]) if method == "value_at" else args[1]
            if not isinstance(row, int) or isinstance(row, bool) or not -len(table) <= row < len(table):
                raise ExpectationError(f"step {self.record.id}: row {row!r} outside 0..{len(table) - 1}")
            if method == "status":
                return str(table[status_column(str(args[0]))].iloc[row])
            return float(table[str(args[0])].iloc[row])
        if method == "snr":
            if str(args[0]) not in self.snr:
                raise ExpectationError(f"step {self.record.id}: no SNR for {args[0]!r} (known: "
                                       f"{', '.join(sorted(self.snr)) or 'none'})")
            return self.snr[str(args[0])]
        if method in ("result", "classification"):
            *named, quantity = (str(a) for a in args)
            found = [a for a in self.analyses if a.quantity == quantity and (not named or a.method == named[0])]
            label = ".".join([*named, quantity])
            if len(found) != 1:
                methods = ", ".join(sorted({a.method for a in found})) or "none"
                raise ExpectationError(f"step {self.record.id}: {len(found)} analysis results {label} (methods: "
                                       f"{methods}); exactly one is needed (name the method)")
            result = found[0]
            if result.outcome != "ok":
                raise ExpectationError(f"step {self.record.id}: {result.method}.{quantity} {result.outcome}: "
                                       f"{result.error}")
            return result.value if method == "result" else result.classification
        if method == "kind":
            if str(args[0]) not in self.kind_result:
                raise ExpectationError(f"step {self.record.id}: kind_result has no {args[0]!r}")
            return self.kind_result[str(args[0])]
        raise ExpectationError(f"unknown step method {method!r}")  # the grammar refuses it first

    def _table(self, *columns: str) -> pd.DataFrame:
        """The run table, which must have ``columns``."""
        table = self.table
        missing = [c for c in columns if table is None or c not in table.columns]
        if table is None or missing:
            known = [c for c in (table.columns if table is not None else []) if not c.endswith("_status")]
            raise ExpectationError(f"step {self.record.id}: no column {', '.join(map(repr, missing))} (has "
                                   f"{', '.join(known) or 'no run table'})")
        return table

    def _nearest(self, table: pd.DataFrame, x_column: str, x: Any) -> int:
        """Index of the row whose ``x_column`` is nearest to ``x``."""
        if isinstance(x, bool) or not isinstance(x, int | float):
            raise ExpectationError(f"step {self.record.id}: value_at needs a number for {x_column}, got {x!r}")
        distance = (pd.to_numeric(table[x_column], errors="coerce") - float(x)).abs().to_numpy(dtype=float)
        if np.isnan(distance).all():
            raise ExpectationError(f"step {self.record.id}: column {x_column!r} has no numbers")
        return int(np.nanargmin(distance))  # a position (the first of equally near rows)


class _World:
    """The temporary configuration and the data folder of one reproduction."""

    def __init__(self, root: Path, scratch: Path, data_dir: Path, repro: Reproduction) -> None:
        self.repo = scratch / "repo"
        source = root / "config"
        shutil.copytree(source, self.repo / "config",
                        ignore=lambda folder, names: ["local"] if Path(folder) == source else [])
        self.override = scratch / "override"
        self.override.mkdir()
        self.data_dir = data_dir
        for alias, spec in repro.scenarios.items():
            base = yaml.safe_load((self.repo / "config" / "sim" / "scenarios" / f"{spec.base}.yaml")
                                  .read_text(encoding="utf-8"))
            base["description"] = f"case reproduction alias {alias} of {spec.base}: {base.get('description', '')}"
            if spec.faults:
                base["faults"] = alias
                self._write(f"sim/faults/{alias}.yaml", {
                    "description": f"faults of the case reproduction alias {alias}",
                    "faults": [f.model_dump(mode="json") for f in spec.faults]})
            self._write(f"sim/scenarios/{alias}.yaml", base)
        self.env = {ENV_CONFIG_DIR: str(self.override), ENV_DATA_DIR: str(self.data_dir)}

    def _write(self, rel: str, data: Any) -> None:
        path = self.override / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def use(self, scenario: str) -> None:
        """Select ``scenario`` (backend ``sim``) for the next service call."""
        self._write("settings.yaml", {"backend": "sim", "sim": {"scenario": scenario}})

    def paths(self) -> Paths:
        return Paths.from_env(self.env, repo_root=self.repo)


def run_reproduction(case_id: str, repro: Reproduction, *, root: Path, registry: RecipeRegistry,
                     data_dir: Path | None = None) -> ReproductionReport:
    """Run ``repro`` (module docstring) and evaluate its expectations. ``data_dir`` keeps the run archive (``None``:
    a temporary folder, removed afterwards)."""
    started = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    views: dict[str, StepView] = {}
    error: str | None = None
    with tempfile.TemporaryDirectory(prefix="b1500-case-", ignore_cleanup_errors=True) as tmp:
        scratch = Path(tmp)
        try:
            world = _World(root, scratch, data_dir if data_dir is not None else scratch / "data", repro)
        except (OSError, yaml.YAMLError) as exc:  # a missing alias base (the case lint names it first)
            world, error = None, f"cannot prepare the temporary configuration: {exc}"
        if world is not None:
            world.use(repro.scenario)
            service = B1500Service(paths=world.paths(), environ=world.env, registry=registry)
            try:
                backend = service.config.get().backend
                if backend != "sim":  # defence in depth: the temporary config selects the simulator
                    raise StepFailed(f"refused: the reproduction configuration selects backend {backend}, not sim")
                for step in repro.steps:
                    scenario = repro.scenario_of(step)
                    world.use(scenario)
                    views[step.id] = _run_step(service, registry, step, scenario, world.data_dir)
            except StepFailed as exc:
                error = str(exc)
            except InvalidConfigError as exc:  # an invalid configuration (a scenario alias that does not validate)
                error = f"invalid configuration: {exc}"
            finally:
                service.close()
    expect: list[ExpectationRecord] = []
    discriminator: list[ExpectationRecord] = []
    if error is None:
        access: dict[str, StepAccess] = dict(views)
        parsed_expect, parsed_discriminator = repro.parsed()
        expect = [_evaluate(text, tree, access) for text, tree in parsed_expect]
        discriminator = [_evaluate(text, tree, access) for text, tree in parsed_discriminator]
    ok = error is None and all(e.verdict == "pass" for e in (*expect, *discriminator))
    return ReproductionReport(case=case_id, ok=ok, started_at=started, commit=repo_commit(root),
                              data_dir=data_dir.as_posix() if data_dir is not None else None,
                              steps=[v.record for v in views.values()], expect=expect,
                              discriminator_check=repro.discriminator.check, discriminator=discriminator, error=error)


def _run_step(service: B1500Service, registry: RecipeRegistry, step: ReproStep, scenario: str,
              data_dir: Path) -> StepView:
    fields: dict[str, Any] = {"id": step.id, "scenario": scenario, "recipe": step.recipe, "pin_map": step.pin_map}
    if step.corrections:
        fields["corrections"] = _corrections(service, registry, step)
    plan = service.validate_plan(recipe_id=step.recipe, params=dict(step.params) or None, pin_map=step.pin_map,
                                 dut_profile=step.dut_profile)
    fields.update(tier=plan.tier, plan_id=plan.plan_id, message=plan.message, error_code=plan.error_code,
                  blocked_by=sorted({f.rule_id for f in plan.findings if f.severity == "block"}),
                  confirm_reasons=list(plan.confirm_reasons))
    view = StepView(record=StepRecord(**fields))
    if plan.plan_id is None or plan.tier not in ("ok", "needs_confirmation"):
        return view
    if plan.tier == "ok":
        run = service.run_plan(plan.plan_id, dut_instance=scenario)
    else:
        if plan.summary is None:
            raise StepFailed(f"step {step.id}: plan {plan.plan_id} needs confirmation but has no summary")
        run = service.run_confirmed_plan(plan.plan_id, summary=plan.summary, dut_instance=scenario)
    if run.outcome == "running" and run.run_id is not None:
        run = service.follow_run(run.run_id) or run
    fields.update(run_id=run.run_id, outcome=run.outcome, message=run.message, error_code=run.error_code,
                  quality_verdict=run.quality_verdict)
    view.status_counts = dict(run.status_counts)
    view.analyses = list(run.analyses)
    if run.run_id is not None:
        note = _fill(view, service, run.run_id, step, data_dir)
        fields["message"] = f"{run.message} ({note})".strip() if note else run.message
    view.record = StepRecord(**fields)
    return view


def _corrections(service: B1500Service, registry: RecipeRegistry, step: ReproStep) -> list[str]:
    """Run the policy-required correction recipes with ``step.pin_map`` (over the step's frequencies when the default
    correction list lacks one), each confirmed with its own summary; their run ids."""
    freqs = example_frequencies(registry, step.recipe, dict(step.params))
    runs: list[str] = []
    for kind in service.config.get().policy.corrections.require:
        params = {"freqs_hz": freqs} if freqs is not None and kind != "phase" else None
        plan = service.validate_plan(recipe_id=CORRECTION_RECIPES[kind], params=params, pin_map=step.pin_map)
        if plan.tier != "needs_confirmation" or plan.plan_id is None or plan.summary is None:
            raise StepFailed(f"step {step.id}: correction {kind} with pin map {step.pin_map} validated to tier "
                             f"{plan.tier}: {plan.message}")
        run = service.run_confirmed_plan(plan.plan_id, summary=plan.summary)
        if not run.ok or run.run_id is None:
            raise StepFailed(f"step {step.id}: correction {kind} {run.outcome}: {run.message}")
        runs.append(run.run_id)
    return runs


def _fill(view: StepView, service: B1500Service, run_id: str, step: ReproStep, data_dir: Path) -> str | None:
    """Read the run's quality report, extra analyses, table and ``kind_result`` into ``view``; a note for the
    step's message when the run has no table (a run refused before measuring), else ``None``."""
    detail = service.get_run(run_id, include=["quality"])
    if detail.quality is not None:
        view.snr = dict(detail.quality.snr)
    for request in step.analyze:
        result = service.analyze_run(run_id, request.method, dict(request.options) or None)
        if not result.ok and not result.results:
            raise StepFailed(f"step {step.id}: analyze_run {request.method} {result.status}: {result.message}")
        view.analyses += result.results
    try:
        data = load_run(run_id, data_root=data_dir)
    except (RunNotFoundError, RunFormatError) as exc:  # a refused run has no table: the view then has none
        return f"no run table: {exc}"
    view.table = data.table
    view.kind_result = dict(data.manifest.kind_result)
    return None


def _evaluate(text: str, tree: ast.Expression, views: dict[str, StepAccess]) -> ExpectationRecord:
    terms: list[str] = []
    try:
        value = evaluate_expectation(tree, views, terms)
    except ExpectationError as exc:
        return ExpectationRecord(text=text, verdict="error", terms=terms, error=str(exc))
    if not isinstance(value, bool):
        return ExpectationRecord(text=text, verdict="error", terms=terms,
                                 error=f"the expression gives {value!r}, not True or False")
    return ExpectationRecord(text=text, verdict="pass" if value else "fail", terms=terms)


def repo_commit(root: Path) -> str:
    """Short commit of ``root`` with ``-dirty`` for a modified tree (``unknown`` without git): what a case quotes."""
    try:
        result = subprocess.run(["git", "-C", str(root), "describe", "--always", "--dirty", "--exclude=*"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                                check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


# == Commands =========================================================================================================


def reproduce(case_id: str, *, root: Path | None = None, out: Path | None = None,
              now: datetime | None = None) -> ReproductionReport:
    """``b1500 dev cases reproduce <case>``: run the case's reproduction into ``out`` (default
    ``work/cases/<case>/<UTC stamp>/``: ``data/`` holds the runs, ``report.json`` the report). Raises
    ``CaseRefused`` for an unknown case, one without a reproduction or one with case lint problems,
    ``FileExistsError`` when ``out`` exists and is not empty."""
    root = Path(root).resolve() if root is not None else find_repo_root()
    cases, problems = load_cases(root)
    case = next((c for c in cases if c.id == case_id), None)
    if case is None:
        known = ", ".join(c.id for c in cases) or "none"
        raise CaseRefused(f"no valid case {case_id!r} under {SOURCE_DIR}/{DEBUG_SKILL}/{CASES_DIR}/ (valid: {known}; "
                          "`uv run b1500 dev cases check` lists the problems)")
    if case.front.reproduction is None:
        raise CaseRefused(f"case {case_id} has no reproduction (reproduction: null)")
    own = _problems_of(case_id, problems)
    if own:
        raise CaseRefused(f"case {case_id} has {len(own)} lint problem(s), first: {own[0].message} (`uv run b1500 "
                          "dev cases check` lists them)")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = (out if out is not None else root / "work" / "cases" / case_id / stamp).resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"{target.as_posix()} exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)
    registry = RecipeRegistry.load(root / "recipes", repo_root=root)
    report = run_reproduction(case_id, case.front.reproduction, root=root, registry=registry,
                              data_dir=target / "data")
    (target / REPORT_FILE).write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


def cases_report(root: Path | None = None, *, reproduce_all: bool = False) -> CasesReport:
    """``b1500 dev cases list`` and ``check``: every case with its status, runbook and open questions, the case lint
    problems and, with ``reproduce_all``, every reproduction (temporary data folders)."""
    root = Path(root).resolve() if root is not None else find_repo_root()
    cases, problems = load_cases(root)
    registry = RecipeRegistry.load(root / "recipes", repo_root=root) if reproduce_all else None
    rows: list[CaseRow] = []
    reports: list[ReproductionReport] = []
    for case in cases:
        front = case.front
        verdict: Literal["pass", "fail", "none", "not run"] = "none" if front.reproduction is None else "not run"
        if front.reproduction is not None and registry is not None and not _problems_of(front.id, problems):
            result = run_reproduction(front.id, front.reproduction, root=root, registry=registry)
            reports.append(result)
            verdict = "pass" if result.ok else "fail"
        rows.append(CaseRow(id=front.id, title=front.title, status=front.status, reviewed_by=front.reviewed_by,
                            runbook=front.runbook, origin=front.origin, backend=front.backend, runs=len(front.runs),
                            reproduction=verdict, open_questions=front.open_questions))
    ok = not problems and all(r.ok for r in reports)
    return CasesReport(ok=ok, cases=rows, problems=problems, reproductions=reports)


def _problems_of(case_id: str, problems: list[LintProblem]) -> list[LintProblem]:
    """The lint problems of the case file ``<case_id>.md`` (a case with problems is not reproduced)."""
    return [p for p in problems if Path(p.file).name == f"{case_id}.md"]


# == Formatting =======================================================================================================


def format_cases(report: CasesReport, *, verbose: bool = False) -> str:
    """Human-readable ``list``/``check`` output: one line per case, the problems, failed expectations."""
    open_total = sum(r.open_questions for r in report.cases)
    lines = [(f"cases: {'ok' if report.ok else 'NOT OK'} ({len(report.cases)} cases, {open_total} open questions for "
              f"the owner, {len(report.problems)} problem(s))")]
    for row in report.cases:
        review = f"reviewed by {row.reviewed_by}" if row.status == "reviewed" else row.status
        simulated = " (SIMULATED)" if row.reproduction in ("pass", "fail") else ""
        lines.append(f"  {row.id}: {review}, {row.origin}; runbook {row.runbook}; backend {row.backend}, {row.runs} "
                     f"lab run(s); reproduction {row.reproduction}{simulated}; {row.open_questions} open question(s)")
    for problem in report.problems:
        where = f"{problem.file}:{problem.line}" if problem.line else problem.file
        lines.append(f"  {where}: [{problem.code}] {problem.message}")
    for result in report.reproductions:
        if verbose or not result.ok:
            lines.append(format_reproduction(result, indent="  "))
    return "\n".join(lines)


def format_reproduction(report: ReproductionReport, *, indent: str = "") -> str:
    """Human-readable reproduction report: steps with run ids, expectations with the values read."""
    where = report.data_dir or "temporary data folder (removed)"
    lines = [(f"{indent}case {report.case}: reproduction {'PASS' if report.ok else 'FAIL'} [SIMULATED] (backend sim, "
              f"commit {report.commit}, {report.started_at}; runs in {where})")]
    for step in report.steps:
        corr = f" after corrections {', '.join(step.corrections)}" if step.corrections else ""
        blocked = f" blocked by {', '.join(step.blocked_by)}" if step.blocked_by else ""
        lines.append(f"{indent}  step {step.id}: {step.recipe} on {step.scenario} ({step.pin_map}){corr}: tier "
                     f"{step.tier}{blocked}; run {step.run_id or '-'} {step.outcome or 'not run'}"
                     f"{f' ({step.error_code})' if step.error_code else ''}")
    if report.error:
        lines.append(f"{indent}  error: {report.error}")
    for title, records in (("symptom", report.expect), (f"discriminator ({report.discriminator_check})",
                                                       report.discriminator)):
        if records:
            lines.append(f"{indent}  {title}:")
        for record in records:
            lines.append(f"{indent}    [{record.verdict}] {record.text}")
            lines += [f"{indent}      {term}" for term in record.terms]
            if record.error:
                lines.append(f"{indent}      error: {record.error}")
    return "\n".join(lines)


def report_json(report: ReproductionReport | CasesReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2)
