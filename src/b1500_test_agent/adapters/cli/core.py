"""Core `b1500` commands (Typer, blueprint 5.3 v1 / 2.9 v2): the operator commands, one per MCP tool, the human-only
commands and installation/configuration/server commands, plus the shared CLI plumbing.

Operator commands map one-to-one to the MCP tools (``TOOL_COMMANDS``; parity test) and print either a short human
summary or, with ``--json``, the service's result model. Exit code 0 when the result is ``ok``, 1 otherwise, 2 for
usage errors.

- ``status`` · ``recipes [ID] [--device T]`` · ``plan RECIPE -p k=v --pin-map X [--dut Y]`` / ``plan --file F`` /
  ``plan --plan-id P`` · ``run PLAN_ID [--dut-instance X]`` · ``run --confirm PLAN_ID`` · ``runs`` ·
  ``show RUN_ID`` · ``analyze RUN_ID METHOD -o k=v`` · ``note RUN_ID TEXT`` · ``shutdown [--reason]``
- human-only: ``fault clear`` (safe shutdown, then clears the latch only when the shutdown verified the safe state)
  and ``lock status``
- ``doctor`` (non-probe checks), ``config check``, ``harness init --codex|--claude [--check]`` (renders
  ``config/harness/`` templates into the gitignored ``.codex/config.toml`` / ``.mcp.json``), ``mcp`` (stdio server,
  same as ``b1500-mcp``)

``run --confirm`` re-validates the plan, prints its summary and asks y/N on an interactive terminal only; without
a TTY it exits non-zero and runs nothing (UX only: the harness tool confirmation is the approval, blueprint 4.3).
The run manifest records ``confirmed_via: cli --confirm``. Tests replace ``make_service``/``is_interactive`` on this
module.
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.devtools import (
    doctor,
    harness,
)
from b1500_test_agent.models.common import ConfigReport, ResultEnvelope
from b1500_test_agent.models.results import (
    AnalysisResult,
    FaultClearResult,
    GetRunSection,
    LockStatus,
    NoteResult,
    PlanValidation,
    RecipeList,
    RunDetail,
    RunList,
    ShutdownResult,
    StationStatus,
)
from b1500_test_agent.models.run import RunSummary
from b1500_test_agent.paths import find_repo_root
from b1500_test_agent.service import DEFAULT_MAX_POINTS, DEFAULT_RUN_LIMIT, B1500Admin, B1500Service

DEFAULT_MCP_APP_SPEC = "b1500_test_agent.adapters.mcp_server:create_server"

TOOL_COMMANDS: dict[str, tuple[str, ...]] = {
    "station_status": ("status",),
    "list_recipes": ("recipes",),
    "validate_plan": ("plan",),
    "run_plan": ("run",),
    "run_confirmed_plan": ("run", "--confirm"),
    "list_runs": ("runs",),
    "get_run": ("show",),
    "analyze_run": ("analyze",),
    "annotate_run": ("note",),
    "safe_shutdown": ("shutdown",),
}
"""MCP tool → the CLI command that calls the same service method (blueprint 5.3 parity)."""

PLAN_FILE_KEYS = frozenset({"recipe_id", "params", "pin_map", "dut_profile", "label"})

app = typer.Typer(
    name="b1500",
    help="B1500A test agent: safety-gated measurement kernel (simulator by default).",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Configuration (config/local/ over committed examples).", no_args_is_help=True)
app.add_typer(config_app, name="config")
fault_app = typer.Typer(help="Fault latch (human only).", no_args_is_help=True)
app.add_typer(fault_app, name="fault")
lock_app = typer.Typer(help="Instrument lock.", no_args_is_help=True)
app.add_typer(lock_app, name="lock")
harness_app = typer.Typer(help="Harness wiring for Codex and Claude Code (blueprint 5.4).", no_args_is_help=True)
app.add_typer(harness_app, name="harness")

JsonOption = Annotated[bool, typer.Option("--json", help="Print the result model as JSON.")]


@app.callback()
def _root() -> None:
    """B1500A test agent: safety-gated measurement kernel (simulator by default)."""


# -- plumbing --------------------------------------------------------------------------------------------------------


def make_service() -> B1500Service:
    """The service of this CLI process (tests replace this factory)."""
    return B1500Service(adapter="cli")


def is_interactive() -> bool:
    """True when a human can answer a prompt on standard input (a TTY)."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def parse_value(text: str) -> Any:
    """A ``k=v`` value: JSON when it parses (numbers, true/false, lists such as [0,0.5]), else the plain string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def parse_pairs(items: list[str] | None, option: str) -> dict[str, Any]:
    """``["a=1", "b=x"]`` → ``{"a": 1, "b": "x"}``; raises ``typer.BadParameter`` on a malformed item."""
    out: dict[str, Any] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise typer.BadParameter(f"expected key=value, got {item!r}", param_hint=option)
        out[key.strip()] = parse_value(value.strip())
    return out


def _flag(result: ResultEnvelope) -> str:
    return "[SIMULATED] " if result.simulated else ""


def _head(result: ResultEnvelope) -> str:
    code = f" ({result.error_code})" if result.error_code else ""
    return f"{_flag(result)}{result.status}{code}: {result.message}".rstrip(": ")


def _next(result: ResultEnvelope) -> list[str]:
    return [f"next: {step}" for step in result.next_steps]


def emit(result: ResultEnvelope, as_json: bool, lines: list[str] | None = None) -> None:
    """Print ``result`` (JSON or the head line, ``lines`` and next steps) and exit 1 unless it is ok."""
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo("\n".join([_head(result), *(lines or []), *_next(result)]))
    if not result.ok:
        raise typer.Exit(code=1)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return "" if value is None else str(value)


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    cells = [[_fmt(v) for v in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(header)]
    out = ["  " + "  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True))]
    out += ["  " + "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in cells]
    return out


# -- operator commands (one per MCP tool) ----------------------------------------------------------------------------


def status_lines(result: StationStatus) -> list[str]:
    lines = [f"backend: {result.backend}" + (" (simulator)" if result.simulated else "")
             + (f"  resource: {result.resource}" if result.resource else "")]
    if result.identity:
        lines.append(f"identity: {result.identity}")
    if result.modules:
        lines.append("modules (profile vs installed):")
        lines += _table(["slot", "expected", "installed", "type", "alias", "match"],
                        [[m.slot, m.expected, m.installed, m.type, m.alias, m.match] for m in result.modules])
    if result.live != "not_read":
        interlock = {None: "unknown", True: "OPEN", False: "closed"}[result.interlock_open]
        errors = ", ".join(f"{e.code} {e.message}".strip() for e in result.instrument_errors) or "none"
        lines.append(f"live ({result.live}): interlock {interlock}; errors {errors}; outputs on "
                     f"{result.outputs_on or 'none'}")
    lines.append(f"fault: {'LATCHED: ' + result.fault.reason if result.fault else 'none'}; inflight marker: "
                 f"{'yes' if result.inflight_marker else 'no'}; lock: "
                 + (f"held by pid {result.lock_holder.pid} ({result.lock_holder.adapter})" if result.lock_holder
                    else "free"))
    if result.config is not None:
        cfg = result.config
        lines.append(f"config: {'valid' if cfg.ok else 'INVALID'}; {cfg.backend_reason}")
        lines += [f"  {f.key}: {f.source} {f.path} sha256:{f.sha256}" for f in cfg.files]
        lines += [f"  problem: {p.file or 'config'}: {p.message}" for p in cfg.problems]
        lines += [f"  warning: {w}" for w in cfg.warnings]
    if result.limits is not None:
        lim = result.limits
        lines.append(f"limits: hard {lim.hard_max_abs_voltage_v:g} V / {lim.hard_max_abs_compliance_a:g} A; soft "
                     f"{lim.soft_voltage_v:g} V / {lim.soft_compliance_a:g} A; max points "
                     f"{', '.join(f'{k} {v}' for k, v in lim.max_points.items())}; sync runs <= "
                     f"{lim.max_sync_run_s:g} s; plans expire after {lim.plan_ttl_h:g} h")
    if result.pin_maps:
        lines.append("pin maps: " + ", ".join(f"{k} ({v})" for k, v in result.pin_maps.items()))
    if result.dut_profiles:
        lines.append("DUT profiles: " + ", ".join(f"{k} ({v})" for k, v in result.dut_profiles.items()))
    return lines


@app.command("status")
def status_command(
    refresh: Annotated[bool, typer.Option("--refresh/--no-refresh", help="Read live state now.")] = True,
    as_json: JsonOption = False,
) -> None:
    """Station status (MCP station_status): backend, IDN, modules, interlock, fault, lock, config, limits."""
    result = make_service().station_status(refresh=refresh)
    emit(result, as_json, status_lines(result))


def recipes_lines(result: RecipeList) -> list[str]:
    if result.recipe is not None:
        r = result.recipe
        lines = [f"{r.id}@{r.version} [{r.status}] {r.title}", (f"kind: {r.kind}; card: {r.card or '-'}; "
                 f"devices: {', '.join(r.device_types) or 'any'}; source: {r.source}")]
        if r.params:
            lines.append("params:")
            lines += _table(["name", "type", "unit", "default", "recommended", "range", "choices"],
                            [[n, p.type, p.unit, p.default, p.recommended, p.range, p.choices]
                             for n, p in r.params.items()])
        if r.roles:
            lines.append("roles: " + "; ".join(f"{n}={s.function}" + (f"({','.join(s.measure)})" if s.measure
                                                                     else "") for n, s in r.roles.items()))
        if r.analysis_defaults:
            lines.append("analysis defaults: " + ", ".join(a.method for a in r.analysis_defaults))
        if r.always_confirm:
            lines.append("always confirm: " + ", ".join(r.always_confirm))
        lines += [f"precondition: {p}" for p in r.preconditions]
        return lines
    return _table(["id", "status", "kind", "title"], [[r.id, r.status, r.kind, r.title] for r in result.recipes])


@app.command("recipes")
def recipes_command(
    recipe_id: Annotated[str | None, typer.Argument(help="Show one recipe in detail.")] = None,
    device: Annotated[str | None, typer.Option("--device", help="Filter by device type, e.g. nmos.")] = None,
    as_json: JsonOption = False,
) -> None:
    """List recipes or show one (MCP list_recipes)."""
    result = make_service().list_recipes(recipe_id=recipe_id, device_type=device)
    emit(result, as_json, recipes_lines(result))


def plan_lines(result: PlanValidation) -> list[str]:
    lines = []
    if result.plan_id:
        lines.append(f"plan_id: {result.plan_id}  tier: {result.tier}")
    if result.summary:
        lines.append(f"summary: {result.summary}")
    if result.resolved is not None:
        res = result.resolved
        lines.append("channels: " + ", ".join(f"{k}={v}" for k, v in res.channels.items())
                     + f"; max |V| {res.max_v:g} V, max |I| {res.max_i:g} A; {res.points} points, ~{res.est_s:g} s")
    for finding in result.findings:
        extra = f" (observed {finding.observed}, limit {finding.limit})" if finding.limit is not None else ""
        lines.append(f"  {finding.severity:<7} {finding.rule_id} {finding.message}{extra} [{finding.source}]")
    if result.expires_at:
        lines.append(f"expires: {result.expires_at.isoformat()}")
    return lines


@app.command("plan")
def plan_command(
    recipe: Annotated[str | None, typer.Argument(help="Recipe id, e.g. mosfet.idvg.")] = None,
    param: Annotated[list[str] | None, typer.Option("-p", "--param", help="Parameter k=v (repeatable).")] = None,
    pin_map: Annotated[str | None, typer.Option("--pin-map", help="Pin map name.")] = None,
    dut: Annotated[str | None, typer.Option("--dut", help="DUT profile name.")] = None,
    label: Annotated[str | None, typer.Option("--label", help="Audit label (not hashed).")] = None,
    file: Annotated[Path | None, typer.Option("--file", help="YAML/JSON plan request file.")] = None,
    plan_id: Annotated[str | None, typer.Option("--plan-id", help="Re-validate a stored plan.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Validate a plan request (MCP validate_plan); prints plan_id, tier and the canonical summary."""
    service = make_service()
    if plan_id is not None:
        if any(v is not None for v in (recipe, param, pin_map, dut, label, file)):
            raise typer.BadParameter("--plan-id re-validates a stored plan and takes no other request input")
        result = service.validate_plan(plan_id=plan_id)
        emit(result, as_json, plan_lines(result))
        return
    request: dict[str, Any] = {}
    if file is not None:
        try:
            loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise typer.BadParameter(f"cannot read {file}: {exc}", param_hint="--file") from exc
        if not isinstance(loaded, dict) or not set(loaded) <= PLAN_FILE_KEYS:
            raise typer.BadParameter(f"a plan file is a mapping with keys {sorted(PLAN_FILE_KEYS)}",
                                     param_hint="--file")
        if not isinstance(loaded.get("params") or {}, dict):
            raise typer.BadParameter("params in a plan file is a mapping", param_hint="--file")
        request = dict(loaded)
    params = dict(request.get("params") or {})
    params.update(parse_pairs(param, "-p"))
    for key, value in (("recipe_id", recipe), ("pin_map", pin_map), ("dut_profile", dut), ("label", label)):
        if value is not None:
            request[key] = value
    if not request.get("recipe_id"):
        raise typer.BadParameter("give a RECIPE, --file or --plan-id")
    result = service.validate_plan(recipe_id=request.get("recipe_id"), params=params or None,
                                   pin_map=request.get("pin_map"), dut_profile=request.get("dut_profile"),
                                   label=request.get("label"))
    emit(result, as_json, plan_lines(result))


def run_lines(result: RunSummary) -> list[str]:
    lines = []
    if result.run_id:
        lines.append(f"run_id: {result.run_id}  plan: {result.plan_id}  outcome: {result.outcome}")
    elif result.plan_id:
        lines.append(f"plan: {result.plan_id}  outcome: {result.outcome}")
    if result.status_counts:
        lines.append("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(result.status_counts.items()))
                     + f"; quality {result.quality_verdict}")
    for analysis in result.analyses:
        value = f"{analysis.value:.4g} {analysis.unit}" if analysis.value is not None else analysis.outcome
        lines.append(f"{analysis.method}: {analysis.quantity} = {value} (derived)")
    if result.cleanup_verified:
        lines.append(f"cleanup: {result.cleanup_verified}")
    if result.summary and not result.ok:
        lines.append(f"summary: {result.summary}")
    if "data" in result.artifacts:
        lines.append(f"data: {result.artifacts['data']}")
    return lines


def _confirm_and_run(service: B1500Service, plan_id: str, dut_instance: str | None, as_json: bool) -> None:
    """``run --confirm``: re-validate, print the summary, ask y/N on a TTY, then ``run_confirmed_plan``."""
    checked = service.validate_plan(plan_id=plan_id)
    if not checked.ok or checked.summary is None:
        emit(checked, as_json, plan_lines(checked))
        return
    say = (lambda text: typer.echo(text, err=True)) if as_json else typer.echo
    say(f"{_flag(checked)}plan {plan_id} (tier {checked.tier}); you are confirming exactly this summary:")
    say(f"  {checked.summary}")
    for finding in checked.findings:
        if finding.severity in ("confirm", "warn"):
            say(f"  {finding.severity}: {finding.rule_id} {finding.message}")
    if not is_interactive():
        refusal = RunSummary(ok=False, status="needs_confirmation", backend=checked.backend,
                             simulated=checked.simulated, error_code="confirmation_required",
                             outcome="confirmation_required", plan_id=checked.plan_id, summary=checked.summary,
                             message="run --confirm needs an interactive terminal (TTY) where the human answers "
                                     "y/N; nothing was run",
                             next_steps=["the human runs this command in their own terminal"])
        emit(refusal, as_json, [])
        return
    if not typer.confirm("Run this plan now?", default=False, err=as_json):
        aborted = RunSummary(ok=False, status="refused", backend=checked.backend, simulated=checked.simulated,
                             error_code="confirmation_required", outcome="confirmation_required",
                             plan_id=checked.plan_id, summary=checked.summary,
                             message="not confirmed by the operator; nothing was run")
        emit(aborted, as_json, [])
        return
    result = service.run_confirmed_plan(plan_id=plan_id, summary=checked.summary, dut_instance=dut_instance)
    emit(result, as_json, run_lines(result))


@app.command("run")
def run_command(
    plan_id: Annotated[str, typer.Argument(help="Plan id from b1500 plan.")],
    confirm: Annotated[bool, typer.Option("--confirm", help="Human confirmation of a needs_confirmation plan "
                                                            "(MCP run_confirmed_plan; interactive y/N).")] = False,
    dut_instance: Annotated[str | None, typer.Option("--dut-instance", help="Die/sample label.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Run a validated plan (MCP run_plan; with --confirm: run_confirmed_plan)."""
    service = make_service()
    if confirm:
        _confirm_and_run(service, plan_id, dut_instance, as_json)
        return
    result = service.run_plan(plan_id=plan_id, dut_instance=dut_instance)
    emit(result, as_json, run_lines(result))


@app.command("runs")
def runs_command(
    recipe: Annotated[str | None, typer.Option("--recipe", help="Recipe id or glob, e.g. 'mosfet.*'.")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Run outcome, e.g. completed.")] = None,
    since: Annotated[str | None, typer.Option("--since", help="ISO date/time of the run start.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="At most this many runs (1-200).")] = DEFAULT_RUN_LIMIT,
    as_json: JsonOption = False,
) -> None:
    """List archived runs, newest first (MCP list_runs)."""
    result: RunList = make_service().list_runs(recipe_id=recipe, status=status, since=since, limit=limit)
    emit(result, as_json, _table(["run_id", "recipe", "outcome", "quality", "dut", "started"],
                                 [[r.run_id, r.recipe_id, r.outcome, r.quality_verdict, r.dut_instance,
                                   r.started_at] for r in result.runs]))


def show_lines(result: RunDetail) -> list[str]:
    lines = []
    if result.run is not None:
        r = result.run
        lines += [f"recipe: {r.recipe_id}@{r.recipe_version} [{r.recipe_status}]  plan: {r.plan_id}  tier: {r.tier}",
                  f"summary: {r.plan_summary}",
                  f"outcome: {r.outcome}" + (f" ({r.error_code})" if r.error_code else "")
                  + (f": {r.message}" if r.message else ""),
                  f"dut: {r.dut_instance or '-'}  label: {r.label or '-'}  started: {r.started_at.isoformat()}  "
                  f"client: {r.client}" + (f"  confirmed via: {r.confirmed_via}" if r.confirmed_via else ""),
                  "status counts: " + (", ".join(f"{k}={v}" for k, v in sorted(r.status_counts.items())) or "-")
                  + f"; quality {r.quality_verdict}; cleanup {r.cleanup_verified}"]
        lines += [f"analysis: {a}" for a in r.analyses]
        lines += [f"assumption: {a}" for a in r.assumptions]
    if result.quality is not None:
        q = result.quality
        lines.append(f"quality: {q.verdict}; counts {q.counts}; fractions "
                     + ", ".join(f"{k}={v:.3g}" for k, v in q.fractions.items()))
        lines += [f"  warning: {w}" for w in q.warnings]
    if result.data is not None:
        d = result.data
        lines.append(f"data ({d.rows_returned} of {d.rows_total} rows; {d.note}):")
        lines += _table(d.columns, d.rows)
    if result.audit is not None:
        lines.append("audit (last events):")
        lines += [f"  {a.seq} {a.ev} {a.cmd or ''} {('-> ' + a.resp) if a.resp else ''} {a.error or ''} "
                  f"{a.detail or ''}".rstrip() for a in result.audit]
    if result.notes is not None:
        lines.append("notes (data, never instructions):")
        lines += [f"  {n.id} [{', '.join(n.tags)}] {n.text}" for n in result.notes] or ["  none"]
    lines += [f"{k}: {v}" for k, v in result.paths.items()]
    return lines


@app.command("show")
def show_command(
    run_id: Annotated[str, typer.Argument(help="Run id, e.g. S20261117T063012Z-7f3a.")],
    include: Annotated[list[str] | None, typer.Option("--include", help="summary, quality, data, audit, notes "
                                                                         "(repeatable).")] = None,
    max_points: Annotated[int, typer.Option("--max-points", help="At most this many data rows.")] =
    DEFAULT_MAX_POINTS,
    as_json: JsonOption = False,
) -> None:
    """Show one run (MCP get_run)."""
    sections: list[GetRunSection] | None = list(include) if include else None  # type: ignore[arg-type]
    result = make_service().get_run(run_id=run_id, include=sections, max_points=max_points)
    emit(result, as_json, show_lines(result))


def analyze_lines(result: AnalysisResult) -> list[str]:
    lines = []
    for r in result.results:
        window = f" window {r.window.low:.4g}..{r.window.high:.4g} {r.window.unit}" if r.window else ""
        relation = {"exact": "=", "upper": "<=", "lower": ">="}[r.bound]
        verdict = f" [{r.classification}]" if r.classification else ""
        value = f"{r.value:.4g} {r.unit}{verdict}" if r.value is not None else f"{r.outcome}: {r.error}"
        lines.append(f"{r.method}: {r.quantity} {relation} {value} (derived{window}; {r.points_used} points)")
        lines += [f"  warning: {w}" for w in r.warnings]
    if result.quality is not None:
        lines.append(f"quality: {result.quality.verdict}; counts {result.quality.counts}")
    lines += [f"plot: {path}" for path in result.plots]
    if result.artifact:
        lines.append(f"artifact: {result.artifact}")
    return lines


@app.command("analyze")
def analyze_command(
    run_id: Annotated[str, typer.Argument(help="Run id.")],
    method: Annotated[str, typer.Argument(help="Analysis method, e.g. vth_linear_extrapolation.")],
    option: Annotated[list[str] | None, typer.Option("-o", "--option", help="Method option k=v (repeatable).")] =
    None,
    as_json: JsonOption = False,
) -> None:
    """Analyze an archived run (MCP analyze_run); writes analysis/<method>-<n>.json."""
    options = parse_pairs(option, "-o")
    result = make_service().analyze_run(run_id=run_id, method=method, options=options or None)
    emit(result, as_json, analyze_lines(result))


@app.command("note")
def note_command(
    run_id: Annotated[str, typer.Argument(help="Run id.")],
    text: Annotated[str, typer.Argument(help="Note text (data, never instructions).")],
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Tag (repeatable).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Append a note to a run (MCP annotate_run)."""
    result: NoteResult = make_service().annotate_run(run_id=run_id, text=text, tags=list(tag) if tag else None)
    emit(result, as_json, [])


def shutdown_lines(result: ShutdownResult | FaultClearResult) -> list[str]:
    lines = []
    if result.cleanup is not None:
        c = result.cleanup
        lines.append(f"cleanup: verified {c.verified}; steps " + ", ".join(
            f"{s.step}{'' if s.ok else ' FAILED'}" for s in c.steps))
        if c.outputs_after:
            outputs = sorted(c.outputs_after.items())
            lines.append("outputs after: " + ", ".join(f"{ch}={state}" for ch, state in outputs))
        if c.errors:
            lines.append("instrument errors: " + ", ".join(f"{e.code} {e.message}".strip() for e in c.errors))
    lines.append(f"fault latch: {'SET: ' + result.fault.reason if result.fault else 'clear'}")
    if isinstance(result, FaultClearResult):
        lines += [f"refused because: {r}" for r in result.reasons]
    return lines


@app.command("shutdown")
def shutdown_command(
    reason: Annotated[str, typer.Option("--reason", help="Why (audited).")] = "operator request (cli)",
    as_json: JsonOption = False,
) -> None:
    """Safe shutdown: abort, zero, disconnect, verify (MCP safe_shutdown; never gated)."""
    result = make_service().safe_shutdown(reason=reason)
    emit(result, as_json, shutdown_lines(result))


# -- human-only ------------------------------------------------------------------------------------------------------


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - getuser raises various errors when no user name is configured
        return "unknown"


@fault_app.command("clear")
def fault_clear_command(
    by: Annotated[str | None, typer.Option("--by", help="Who clears it (default: the login name).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Clear the fault latch (human only): runs a safe shutdown and clears the latch only when it verified that
    every output is off and the error queue is empty."""
    result = B1500Admin(make_service()).fault_clear(by=by or _user())
    emit(result, as_json, shutdown_lines(result) if result.cleanup is not None or result.reasons else [])


@lock_app.command("status")
def lock_status_command(as_json: JsonOption = False) -> None:
    """Who holds the instrument lock; inflight marker and fault latch."""
    result: LockStatus = B1500Admin(make_service()).lock_status()
    emit(result, as_json, [f"resource: {result.resource}"])


# -- installation, configuration, server -----------------------------------------------------------------------------


@app.command("doctor")
def doctor_command(
    probe: Annotated[bool, typer.Option("--probe", help="Read-only hardware probe (M4; refused on sim).")] = False,
    as_json: JsonOption = False,
) -> None:
    """Check the installation and station readiness (PASS/WARN/FAIL); exit 1 on any FAIL."""
    if probe:
        typer.echo(doctor.probe_refusal(), err=True)
        raise typer.Exit(code=2)
    report = doctor.run_doctor()
    typer.echo(report.model_dump_json(indent=2) if as_json else doctor.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


def format_config_report(report: ConfigReport) -> str:
    """Human-readable `b1500 config check` output: verdict, backend reason, files used, paths, problems."""
    lines = [f"config: {'valid' if report.ok else 'INVALID (invalid_config)'}"]
    if report.backend is not None:
        lines.append(f"backend: {report.backend_reason}")
    if report.files:
        lines.append("files used:")
        width = max(len(f.key) for f in report.files)
        lines += [f"  {f.key:<{width}}  {f.source:<8}  {f.path}  sha256:{f.sha256[:12]}" for f in report.files]
    if report.paths:
        lines.append("paths:")
        lines += [f"  {name}: {value}" for name, value in report.paths.items()]
    if report.warnings:
        lines.append("warnings:")
        lines += [f"  - {warning}" for warning in report.warnings]
    if report.problems:
        lines.append("problems:")
        for problem in report.problems:
            where = problem.file or "config"
            if problem.location:
                where += f" [{problem.location}]"
            lines.append(f"  - {where}: {problem.message}")
    return "\n".join(lines)


@config_app.command("check")
def config_check(as_json: JsonOption = False) -> None:
    """Validate the configuration (rule R-CFG-01) and show which file is used for each item and why.

    Exit code 0 when valid, 1 with structured problems (error code invalid_config) otherwise.
    """
    report = ConfigLoader().check()
    typer.echo(report.model_dump_json(indent=2) if as_json else format_config_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@harness_app.command("init")
def harness_init_command(
    codex: Annotated[bool, typer.Option("--codex", help="Render .codex/config.toml (Codex).")] = False,
    claude: Annotated[bool, typer.Option("--claude", help="Render .mcp.json (Claude Code).")] = False,
    check: Annotated[bool, typer.Option("--check", help="Write nothing; fail on drift or wiring problems.")] =
    False,
    examples: Annotated[bool, typer.Option("--examples", help="Also rewrite the committed examples (developers, "
                                                              "after editing config/harness/).")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite a config not written by harness init.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Render the harness MCP configs from config/harness/ with this clone's absolute path and check the committed
    harness files (.claude/settings.json, .codex/rules/b1500.rules, guard hook). Exit 1 on any problem."""
    names: list[harness.HarnessName] = [n for n, on in (("codex", codex), ("claude", claude)) if on]
    if not names:
        raise typer.BadParameter("give --codex, --claude or both")
    if check and (examples or force):
        raise typer.BadParameter("--check writes nothing; drop --examples/--force")
    repo_root = find_repo_root()
    report = harness.check(repo_root, names) if check else harness.init(repo_root, names, force=force,
                                                                         examples=examples)
    typer.echo(report.model_dump_json(indent=2) if as_json else harness.format_report(report))
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("mcp")
def mcp_command() -> None:
    """Serve the ten MCP tools on stdio (same as b1500-mcp)."""
    from b1500_test_agent.adapters import mcp_server  # imported lazily: the CLI never needs fastmcp otherwise

    mcp_server.main()
