"""Scripted stand-in for a harness, used by the acceptance self-tests (no Codex or Claude Code needed).

The runner launches it instead of ``codex``/``claude`` (tests patch ``harnesses.turn_argv``). It performs the
actions of one turn of an agent script (``tests/fixtures/transcripts/selftest/*.yaml``) for real, through an
in-process ``B1500Service`` with the runner's environment (so the server audit, plans, runs and simulator log are
genuine), and prints a transcript in the harness's real format (shapes as in the recorded transcripts of
``tests/fixtures/transcripts/``). For Codex it also appends code-mode tool calls to a rollout file under
``$CODEX_HOME/sessions/``.

Actions: ``call`` (MCP tool + ``args``, ``save`` the result as a variable), ``shell`` (reported, not executed),
``cli`` (a ``b1500`` command line, e.g. ``bringup status``, run in-process for real with ``B1500_HOME`` = the cwd
and reported as the shell command ``uv run b1500 …`` with its output and exit code; the bring-up helpers are
CLI-only),
``write`` (file relative to the cwd; ``denied: true`` = reported as refused, not written), ``edit_config`` (append to
a file of ``$B1500_CONFIG_DIR``), ``sim_raw`` (one line straight into the simulator, bypassing the audited
transport), ``wait_run`` (poll ``get_run`` of a run every 0.2 s, each poll a reported call, until it no longer
runs; ``timeout`` seconds), ``forge`` (evidence of a recipe that does not exist yet, written by ``forge.py`` with the
real models and shown as the tool call it stands for: ``plan``, ``run``, ``finish``, ``analyze``, ``call``,
``selector``), ``sleep`` (seconds), ``say`` (agent message; the last one is the final answer). Each turn reports a
small fixed token usage (Codex ``turn.completed``, Claude ``result``), so the runner's and the report's usage sums are
exercised.
``{{var.key}}`` placeholders use saved results, ``$FAKE_AGENT_VARS`` (JSON; strings the tests build at run time)
and ``prompt`` (the user's turn as the runner rendered it: ``{{prompt.text}}``, and the first plan and run id it
names, ``{{prompt.plan_id}}``/``{{prompt.run_id}}``, as an agent would read them from the request).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from b1500_test_agent.service import B1500Service

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)(?:\.([A-Za-z0-9_]+))?\s*\}\}")
_PLAN_ID = re.compile(r"\bP-[A-Z0-9]{6,}\b")
_RUN_ID = re.compile(r"\b[SH]\d{8}T\d{6}Z-[0-9a-f]{4}\b")


def _render(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def sub(match: re.Match[str]) -> str:
            item = variables[match.group(1)]
            return str(item[match.group(2)] if match.group(2) else item)

        return _PLACEHOLDER.sub(sub, value)
    if isinstance(value, dict):
        return {k: _render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, variables) for v in value]
    return value


def _window(result: dict[str, Any]) -> str | None:
    window = result.get("window") or {}
    return f"{window['low']:.2f}..{window['high']:.2f} {window['unit']}" if window else None


def _flatten(result: dict[str, Any]) -> dict[str, Any]:
    """A saved result plus convenience fields of the first extraction result (``value``, ``window``) and of every
    extraction by quantity (``<quantity>``, ``<quantity>_window``, e.g. ``vth_fwd``)."""
    out = dict(result)
    first = (result.get("results") or [None])[0]
    if isinstance(first, dict) and first.get("value") is not None:
        out["value"] = f"{first['value']:.4g}"
        if _window(first):
            out["window"] = _window(first)
    for item in [*(result.get("results") or []), *(result.get("analyses") or [])]:
        if isinstance(item, dict) and item.get("value") is not None and item.get("quantity"):
            out.setdefault(item["quantity"], f"{item['value']:.4g}")
            if _window(item):
                out.setdefault(f"{item['quantity']}_window", _window(item))
    counts = result.get("status_counts")
    if isinstance(counts, dict):
        out["counts"] = ", ".join(f"{k}={v}" for k, v in counts.items())
    return out


class Emitter:
    """Prints harness events in Codex ``exec --json`` or Claude ``stream-json`` shape."""

    def __init__(self, harness: str, session_id: str, cwd: Path, rollout: Path | None) -> None:
        self.harness, self.session_id, self.cwd, self.rollout = harness, session_id, cwd, rollout
        self.n = 0
        self.last_text = ""

    def out(self, record: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def code(self, script: str) -> None:
        if self.rollout is None:
            return
        self.rollout.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        record = {"timestamp": ts, "type": "response_item",
                  "payload": {"type": "custom_tool_call", "status": "completed", "call_id": f"call_{self.n}",
                              "name": "exec", "input": script}}
        with self.rollout.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def start(self, turn: int) -> None:
        if self.harness == "codex":
            self.out({"type": "thread.started", "thread_id": self.session_id})
            self.out({"type": "turn.started"})
            if self.rollout is not None:
                self.rollout.parent.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                with self.rollout.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"timestamp": ts, "type": "turn_context", "payload": {
                        "approval_policy": "never", "sandbox_policy": {"type": "workspace-write"},
                        "model": "fake", "effort": "low"}}) + "\n")
        else:
            self.out({"type": "system", "subtype": "init", "cwd": str(self.cwd), "session_id": self.session_id,
                      "tools": ["Bash", "Write", "mcp__b1500__station_status"], "model": "fake",
                      "permissionMode": "default", "mcp_servers": [{"name": "b1500", "status": "connected"}]})

    def _claude_use(self, name: str, data: dict[str, Any], result: str, *, denied: bool = False) -> None:
        self.n += 1
        use_id = f"toolu_{self.n:04d}"
        self.out({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": use_id, "name": name, "input": data}]}, "parent_tool_use_id": None,
            "session_id": self.session_id})
        if denied:
            self.out({"type": "system", "subtype": "permission_denied", "tool_name": name, "tool_use_id": use_id,
                      "message": "Claude requested permissions, but you haven't granted it yet."})
        record: dict[str, Any] = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": use_id, "content": result, "is_error": denied}]},
            "parent_tool_use_id": None, "session_id": self.session_id}
        if denied:
            record["tool_result_meta"] = [{"id": use_id, "permission_decision": {"decision": "reject"}}]
        self.out(record)

    def call(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        text = json.dumps(result)
        if self.harness == "codex":
            self.n += 1
            self.code(f"text(await tools.mcp__b1500__{tool}({json.dumps(args)}));\n")
            self.out({"type": "item.completed", "item": {
                "id": f"item_{self.n}", "type": "mcp_tool_call", "server": "b1500", "tool": tool, "arguments": args,
                "result": {"content": [{"type": "text", "text": text}], "structured_content": result},
                "error": None, "status": "completed"}})
        else:
            self._claude_use(f"mcp__b1500__{tool}", args, text)

    def shell(self, command: str, output: str = "", exit_code: int = 0) -> None:
        if self.harness == "codex":
            self.n += 1
            self.code(f"text(await tools.exec_command({{cmd:{json.dumps(command)}}}));\n")
            self.out({"type": "item.completed", "item": {
                "id": f"item_{self.n}", "type": "command_execution", "command": f"/bin/zsh -lc {command!r}",
                "aggregated_output": output, "exit_code": exit_code,
                "status": "completed" if exit_code == 0 else "failed"}})
        else:
            self._claude_use("Bash", {"command": command, "description": "scripted"}, output)

    def write(self, path: Path, content: str, *, denied: bool) -> None:
        if self.harness == "codex":
            self.n += 1
            patch = f"*** Begin Patch\n*** Add File: {path.as_posix()}\n+{content}\n*** End Patch"
            self.code(f"text(await tools.apply_patch({json.dumps(patch)}));\n")
            self.out({"type": "item.completed", "item": {
                "id": f"item_{self.n}", "type": "file_change", "changes": [{"path": str(path), "kind": "add"}],
                "status": "declined" if denied else "completed"}})
        else:
            self._claude_use("Write", {"file_path": str(path), "content": content}, "denied" if denied else "ok",
                             denied=denied)

    def say(self, text: str) -> None:
        self.last_text = text
        if self.harness == "codex":
            self.n += 1
            self.out({"type": "item.completed", "item": {"id": f"item_{self.n}", "type": "agent_message",
                                                         "text": text}})
        else:
            self.out({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": text}]}, "parent_tool_use_id": None, "session_id": self.session_id})

    def finish(self) -> None:
        if self.harness == "codex":
            self.out({"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 1000,
                                                          "output_tokens": 30, "reasoning_output_tokens": 5}})
        else:
            self.out({"type": "result", "subtype": "success", "is_error": False, "result": self.last_text,
                      "session_id": self.session_id, "total_cost_usd": 0.01,
                      "usage": {"input_tokens": 10, "cache_creation_input_tokens": 190,
                                "cache_read_input_tokens": 1000, "output_tokens": 30,
                                "output_tokens_details": {"thinking_tokens": 5}},
                      "modelUsage": {"fake": {"costUSD": 0.01}}})


def _sim_raw(line: str) -> None:
    """Write one line straight into the simulator (unaudited), as an agent's own script would."""
    from b1500_test_agent.config import ConfigLoader
    from b1500_test_agent.transport.sim.instrument import SimTransport
    from b1500_test_agent.transport.sim.state import sim_state_file

    bundle = ConfigLoader().get()
    assert bundle.sim_scenario is not None
    transport = SimTransport(bundle.sim_scenario, state_file=sim_state_file(bundle.paths.state_dir,
                                                                            bundle.settings.sim.scenario))
    transport.open()
    transport.load_state()
    transport.write(line)
    transport.save_state()
    transport.close()


def _wait_run(service: B1500Service, emit: Emitter, run_id: str, timeout: float) -> None:
    """Poll ``get_run`` until the run no longer runs (an agent following an asynchronous run)."""
    deadline = time.monotonic() + timeout
    while True:
        args = {"run_id": run_id, "include": ["progress"]}
        result = service.get_run(**args).model_dump(mode="json")
        emit.call("get_run", args, result)
        state = (result.get("progress") or {}).get("state")
        if state != "running" or time.monotonic() > deadline:
            return
        time.sleep(0.2)


FORGED_TOOLS = {"plan": "validate_plan", "run": None, "analyze": "analyze_run", "call": None}
"""Forge kinds shown as a tool call in the transcript (``run``/``call`` name their tool); ``finish`` and ``selector``
happen in the server without a call."""


def _forge(action: dict[str, Any], emit: Emitter) -> dict[str, Any]:
    """One ``forge`` action (``forge.py``): write the evidence, then show the call it stands for."""
    from forge import Forger  # tests/acceptance/forge.py, next to this script

    kind = action["forge"]
    spec = {k: v for k, v in action.items() if k not in ("forge", "save")}
    result = getattr(Forger(), kind)(spec)
    if kind in FORGED_TOOLS:
        tool = FORGED_TOOLS[kind] or spec.get("tool", "run_plan")
        if kind == "plan":
            args = {"recipe_id": spec["recipe_id"], "pin_map": spec["pin_map"], "dut_profile": spec.get("dut_profile"),
                    "params": {k: (v[0] if isinstance(v, list) else v) for k, v in (spec.get("params") or {}).items()}}
        elif kind == "run":
            args = {"plan_id": spec["plan_id"], **({"summary": spec["summary"]} if "summary" in spec else {})}
        elif kind == "analyze":
            args = {"run_id": spec["run_id"], "method": result["method"]}
        else:
            args = spec.get("args") or {}
        emit.call(tool, args, result)
    return result


def _cli(command: str) -> tuple[str, int]:
    """Run one ``b1500`` command line in-process (the repository = the cwd, as for a harness launched there)."""
    import shlex

    from typer.testing import CliRunner

    from b1500_test_agent.adapters.cli import app

    result = CliRunner().invoke(app, shlex.split(command), env={"B1500_HOME": str(Path.cwd())})
    return result.output, result.exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", required=True)
    parser.add_argument("--turn", type=int, required=True)
    parser.add_argument("--resume", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--prompt", default="")
    ns = parser.parse_args()
    script = yaml.safe_load(Path(ns.script).read_text(encoding="utf-8"))
    actions = script["turns"].get(ns.turn) or script["turns"].get(str(ns.turn)) or []
    state_file = Path(ns.script).with_suffix(".state.json")
    variables: dict[str, Any] = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {}
    variables.update(json.loads(os.environ.get("FAKE_AGENT_VARS", "{}")))
    plan_id, run_id = _PLAN_ID.search(ns.prompt), _RUN_ID.search(ns.prompt)
    variables["prompt"] = {"text": ns.prompt, "plan_id": plan_id.group() if plan_id else "",
                           "run_id": run_id.group() if run_id else ""}
    session_id = ns.resume if ns.resume != "new" else str(uuid.uuid4())
    cwd = Path.cwd()
    rollout = None
    if ns.harness == "codex" and os.environ.get("CODEX_HOME"):
        sessions = Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "11" / "18"
        rollout = sessions / f"rollout-fake-{session_id}.jsonl"
    emit = Emitter(ns.harness, session_id, cwd, rollout)
    emit.start(ns.turn)
    os.environ["B1500_HOME"] = str(cwd)  # the repository the harness was launched in, as the real server's clone
    service = B1500Service(adapter="mcp")
    try:
        for raw in actions:
            action = _render(raw, variables)
            if "call" in action:
                result = getattr(service, action["call"])(**action.get("args", {})).model_dump(mode="json")
                emit.call(action["call"], action.get("args", {}), result)
                if action.get("save"):
                    variables[action["save"]] = _flatten(result)
            elif "shell" in action:
                emit.shell(action["shell"])
            elif "cli" in action:
                output, code = _cli(action["cli"])
                emit.shell(f"uv run b1500 {action['cli']}", output, code)
                if action.get("expect_exit") is not None and code != int(action["expect_exit"]):
                    raise SystemExit(f"fake agent: b1500 {action['cli']} exited {code}: {output}")
            elif "write" in action:
                spec = action["write"]
                path = cwd / spec["path"]
                if not spec.get("denied"):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(spec["content"], encoding="utf-8")
                emit.write(path, spec["content"], denied=bool(spec.get("denied")))
            elif "edit_config" in action:
                spec = action["edit_config"]
                target = Path(os.environ["B1500_CONFIG_DIR"]) / spec["path"]
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(spec["append"])
            elif "sim_raw" in action:
                _sim_raw(action["sim_raw"])
            elif "wait_run" in action:
                _wait_run(service, emit, str(action["wait_run"]), float(action.get("timeout", 60)))
            elif "forge" in action:
                result = _forge(action, emit)
                if action.get("save"):
                    variables[action["save"]] = _flatten(result)
            elif "sleep" in action:
                time.sleep(float(action["sleep"]))
            elif "say" in action:
                emit.say(action["say"])
    finally:
        service.close()
    emit.finish()
    state_file.write_text(json.dumps(variables), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
