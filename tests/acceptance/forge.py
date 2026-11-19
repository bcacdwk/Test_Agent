"""Forged evidence for the acceptance self-tests of scenarios written ahead of their modules (S3 rewritten, S11-S15).

The fake agent (``fake_agent.py``, action ``forge``) cannot drive recipes that do not exist yet (``moscap.cv``,
``fefet.pulse_write_read``, ``fecap.pund``, ``reliability.bti_sms`` ...), so it writes what the server would: a
``PlanRecord`` in the plan store, a ``RunManifest`` (with ``analysis/*.json``) in the run archive, ``tool_call`` audit
events tagged with the session, and the selector state in the simulator state file; the transcript shows the tool
call with a result shaped like the real one. Every record is built and validated with the real Pydantic models, so
the graders read the same shapes as from a real session. Analysis values may be computed from the simulator truth of
the runner's scenario (``truth``), so the ideal session stays ideal when a module work package replaces the fixture
scenario by the real one.

Kinds (``forge:``): ``plan`` (validate_plan), ``run`` (run_plan/run_confirmed_plan; ``outcome: running`` starts an
asynchronous run), ``finish`` (ends a running run), ``analyze`` (analyze_run), ``call`` (any other tool: audit and
transcript only, e.g. get_run polls, safe_shutdown), ``selector`` (selector port states in the simulator state).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from b1500_test_agent.archive.store import RunFolder, analysis_payload, new_run_id
from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.devtools.acceptance.extraction import call_truth
from b1500_test_agent.devtools.acceptance.specs import Truth
from b1500_test_agent.models.analysis import ExtractionResult, MethodRecord, Quantity, QuantityRange
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.plan import (
    BoundChannel,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
    PlanRequest,
    PulseEnvelope,
    RuleFinding,
    RulesReport,
)
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.run import CleanupReport, CleanupStep, ClientInfo, RunManifest
from b1500_test_agent.paths import Paths
from b1500_test_agent.transport.audit import JsonlAuditSink
from b1500_test_agent.transport.sim.state import SimPersistentState, load_state_file, save_state_file, sim_state_file

ZERO_SHA = "0" * 64
STATUS = {"ok": "ok", "needs_confirmation": "needs_confirmation", "blocked": "blocked"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _route(text: str) -> Route:
    """``SEL1.OUT1:pgu`` -> ``Route``."""
    target, state = text.split(":")
    switch, output = target.split(".")
    return Route(switch=switch, output=output, state=state)  # type: ignore[arg-type]


class _RunView:
    """Just what ``extraction.call_truth`` reads of a run: its plan parameters."""

    def __init__(self, plan: PlanRecord) -> None:
        self.manifest = type("M", (), {"plan": plan, "run_id": "forged"})()


class Forger:
    """Writes forged evidence into the runner's temporary data dir (module docstring)."""

    def __init__(self) -> None:
        self.paths = Paths.from_env()
        self.tag = os.environ.get("B1500_SESSION_TAG")
        self.audit = JsonlAuditSink(self.paths.state_dir / "audit" / "forged.jsonl")
        self.bundle = ConfigLoader().get()

    # -- shared --------------------------------------------------------------------------------------------------

    def _audit(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        data: dict[str, Any] = {"adapter": "mcp", "tool": tool, "args_sha256": _sha(json.dumps(args))[:16],
                                "session_tag": self.tag, "status": result.get("status"),
                                "error_code": result.get("error_code")}
        for key in ("plan_id", "run_id", "recipe_id", "tier", "outcome"):
            value = result.get(key) or args.get(key)
            if isinstance(value, str) and value:
                data[key] = value
        run = data.get("run_id")
        self.audit.emit(AuditEvent.now("tool_call", "sim", intent=f"mcp:{tool}", run=run, data=data))

    def _plan(self, plan_id: str) -> PlanRecord:
        return PlanRecord.model_validate_json((self.paths.state_dir / "plans" / f"{plan_id}.json")
                                              .read_text(encoding="utf-8"))

    def _value(self, spec: dict[str, Any], plan: PlanRecord) -> float:
        """A number, or the simulator truth (``truth``: a ``Truth`` with ``sim_call``) times ``factor``."""
        if "truth" not in spec:
            return float(spec["value"])
        truth = Truth.model_validate(spec["truth"])
        ev = type("E", (), {"sim_scenario": self.bundle.sim_scenario})()
        ev_value = call_truth(ev, truth, _RunView(plan))  # type: ignore[arg-type]
        return ev_value * float(spec.get("factor", 1.0))

    # -- validate_plan -------------------------------------------------------------------------------------------

    def plan(self, spec: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC)
        params = spec.get("params") or {}
        resolved = {name: Quantity(value=v[0], unit=v[1]) if isinstance(v, list) and len(v) == 2
                    and isinstance(v[1], str) else Quantity(value=v) for name, v in params.items()}
        roles, channels = {}, {}
        default = {3: {"role": "main", "max_abs_v": 1.0, "max_abs_i": 1.0e-3, "function": "bias_v"}}
        for channel, item in (spec.get("channels") or default).items():
            ch = int(channel)
            via = _route(item["via"]) if item.get("via") else None
            roles[item["role"]] = BoundChannel(role=item["role"], terminal=item.get("terminal", item["role"]),
                                               channel=ch, cmu_side=item.get("cmu_side"), via=via)
            pulse = PulseEnvelope(**item["pulse"]) if item.get("pulse") else None
            channels[ch] = ChannelEnvelope(role=item["role"], max_abs_v=float(item["max_abs_v"]),
                                           max_abs_i=item.get("max_abs_i"), function=item.get("function"),
                                           pulse=pulse)
        routes_by_phase = {phase: [_route(r) for r in items]
                           for phase, items in (spec.get("routes_by_phase") or {}).items()}
        findings = [RuleFinding(rule_id=f["rule_id"], severity=f["severity"], message=f["message"],
                                reason=f.get("reason"), source=f.get("source", "forged")) for f in spec["findings"]]
        rules = RulesReport.from_findings("plan", findings, policy_digest=ZERO_SHA, evaluated_at=now)
        request = PlanRequest(recipe_id=spec["recipe_id"], params={k: (v[0] if isinstance(v, list) and len(v) == 2
                                                                       and isinstance(v[1], str) else v)
                                                                   for k, v in params.items()},
                              pin_map=spec["pin_map"], dut_profile=spec.get("dut_profile"))
        digest = _sha(json.dumps(spec, sort_keys=True, default=str) + secrets.token_hex(4))
        plan_id = "P-" + "".join("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"[int(digest[i:i + 2], 16) % 32] for i in
                                 range(0, 20, 2))
        plan = PlanRecord(
            plan_id=plan_id, plan_hash=digest, request=request, recipe_id=spec["recipe_id"], recipe_version=1,
            recipe_sha=ZERO_SHA, kind=spec["kind"], resolved_params=resolved,
            binding=ChannelBinding(pin_map=spec["pin_map"], roles=roles),
            envelope=CompiledEnvelope(channels=channels, routes=frozenset(r for rs in routes_by_phase.values()
                                                                          for r in rs)),
            estimate=Estimate(points=int(spec.get("points", 100)), duration_s=float(spec.get("duration_s", 2.0))),
            flex_preview=[], hashes={}, backend="sim", mode=spec.get("mode", "sync"), routes_by_phase=routes_by_phase,
            rules=rules, tier=rules.tier, summary=spec["summary"], created_at=now, expires_at=now + timedelta(hours=24),
        )  # fmt: skip
        path = self.paths.state_dir / "plans" / f"{plan_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        result = {"ok": plan.tier != "blocked", "status": STATUS[plan.tier], "backend": "sim", "simulated": True,
                  "plan_id": plan_id, "recipe_id": plan.recipe_id, "tier": plan.tier, "summary": plan.summary,
                  "findings": [f.model_dump(mode="json") for f in findings],
                  "confirm_reasons": list(rules.confirm_reasons), "mode": plan.mode,
                  "error_code": "blocked_by_rules" if plan.tier == "blocked" else None}
        self._audit("validate_plan", request.model_dump(mode="json"), result)
        return result

    # -- runs ----------------------------------------------------------------------------------------------------

    def run(self, spec: dict[str, Any]) -> dict[str, Any]:
        tool = spec.get("tool", "run_plan")
        plan = self._plan(spec["plan_id"])
        run_id = new_run_id("sim")
        started = datetime.now(UTC)
        args = {"plan_id": plan.plan_id, **({"summary": spec["summary"]} if tool == "run_confirmed_plan" else {})}
        outcome = spec.get("outcome", "completed")
        result = {"ok": True, "status": "ok", "backend": "sim", "simulated": True, "run_id": run_id,
                  "plan_id": plan.plan_id, "outcome": outcome, "started_at": started.isoformat()}
        if outcome == "running":
            result["eta_s"] = plan.estimate.duration_s
        else:
            result["analyses"] = self._manifest(plan, run_id, started, outcome, spec,
                                                confirmed=tool == "run_confirmed_plan")
        self._audit(tool, args, result)
        return result

    def finish(self, spec: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan(spec["plan_id"])
        started = datetime.fromisoformat(spec["started_at"])
        analyses = self._manifest(plan, spec["run_id"], started, spec.get("outcome", "completed"), spec,
                                  confirmed=bool(spec.get("confirmed", True)))
        return {"run_id": spec["run_id"], "outcome": spec.get("outcome", "completed"), "analyses": analyses}

    def _manifest(self, plan: PlanRecord, run_id: str, started: datetime, outcome: str, spec: dict[str, Any], *,
                  confirmed: bool) -> list[dict[str, Any]]:
        """Write the run's manifest and its default analyses (``spec["analyses"]``); returns the analyses."""
        folder = RunFolder(self.paths.runs_dir, run_id)
        folder.path.mkdir(parents=True, exist_ok=True)
        verified = spec.get("cleanup", "sim_state")
        cleanup = CleanupReport(steps=[CleanupStep(step="verify", ok=verified != "unverified")], verified=verified,
                                outputs_after={}, latched_fault=verified == "unverified")
        manifest = RunManifest(
            run_id=run_id, plan=plan, plan_hash=plan.plan_hash, recipe_id=plan.recipe_id, recipe_version=1,
            recipe_sha=ZERO_SHA, recipe_status="sim_validated", backend="sim", simulated=True, hashes={},
            config_files=[], rules=[plan.rules], tier=plan.tier,
            confirmed_summary=plan.summary if confirmed else None,
            confirmed_via="run_confirmed_plan" if confirmed else None,
            client=ClientInfo(adapter="mcp", session_tag=self.tag), software_version="forged", started_at=started,
            finished_at=datetime.now(UTC), outcome=outcome, cleanup=cleanup,
            status_counts=spec.get("status_counts", {"N": 100}),
        )  # fmt: skip
        (folder.path / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return [self._write_analysis(folder, plan, item) for item in spec.get("analyses") or []]

    def _write_analysis(self, folder: RunFolder, plan: PlanRecord, item: dict[str, Any]) -> dict[str, Any]:
        window = item.get("window")
        result = ExtractionResult(
            method=item["method"], quantity=item["quantity"], value=self._value(item, plan), unit=item["unit"],
            method_record=MethodRecord(name=item["method"], version="1"),
            window=QuantityRange(low=window[0], high=window[1], unit=window[2]) if window else None,
            points_used=50, points_excluded={}, fit={}, warnings=[],
        )  # fmt: skip
        folder.add_analysis(item["method"], analysis_payload(item["method"], {}, [result], source="analyze_run"))
        return result.model_dump(mode="json")

    def analyze(self, spec: dict[str, Any]) -> dict[str, Any]:
        manifest = next(self.paths.runs_dir.rglob(f"{spec['run_id']}/manifest.json"))
        plan = RunManifest.model_validate_json(manifest.read_text(encoding="utf-8")).plan
        folder = RunFolder(self.paths.runs_dir, spec["run_id"])
        results = [self._write_analysis(folder, plan, item) for item in spec["results"]]
        out = {"ok": True, "status": "ok", "backend": "sim", "simulated": True, "run_id": spec["run_id"],
               "method": spec["results"][0]["method"], "results": results}
        self._audit("analyze_run", {"run_id": spec["run_id"], "method": out["method"]}, out)
        return out

    def call(self, spec: dict[str, Any]) -> dict[str, Any]:
        result = {"ok": True, "status": "ok", "backend": "sim", "simulated": True, **(spec.get("result") or {})}
        self._audit(spec["tool"], spec.get("args") or {}, result)
        return result

    def selector(self, spec: dict[str, Any]) -> dict[str, Any]:
        scenario = self.bundle.settings.sim.scenario
        path = sim_state_file(self.paths.state_dir, scenario)
        state = load_state_file(path) or SimPersistentState(scenario=scenario)
        state.selector_ports.update({int(k): int(v) for k, v in spec["ports"].items()})
        save_state_file(path, state)
        return {"ports": dict(state.selector_ports)}
