"""Fake ``git``, ``uv``, ``npm``, ``claude`` and ``codex`` for ``tests/adapters/test_update.py`` (v2.1 plan §2.2 AC:
fake executables on PATH cover every row of ``b1500 update``; no real installer, network or harness ever runs).

The tests put a tiny wrapper per tool on ``PATH`` (``tool`` with a ``#!/bin/sh`` line, ``tool.cmd`` on Windows) that
runs ``python fake_tools.py <tool> <args...>``. State lives in the JSON file ``$FAKE_TOOLS_WORLD``; every call is
appended to ``$FAKE_TOOLS_LOG`` (one JSON list ``[tool, *args]`` per line), so a test can assert that nothing was
pulled, synced or installed. Installers change the world (the next ``--version`` reads the new version). Output is
written as UTF-8 bytes, as the real Node and Rust CLIs write to a pipe: the fakes run with ``-I -S``, where Python's
own stdout would use the Windows code page (the CI failure of 06c2dbe).

World keys (all optional): ``git`` {branch, default, dirty, head, new_head, pull: ok|uptodate|diverged|offline|
error, lock_changed, behind}; ``uv`` {sync: ok|fail, check: ok|differs, continue_exit}; ``npm`` {install: ok|fail,
latest}; ``codex`` {version, login: bool, execpolicy: forbid|allow|garbage, version_text, help_drop: [flags]};
``claude`` {version, login: bool, doctor: clean|invalid|garbage, install: ok|fail|stays, repo, latest, help_drop}.
``--help`` prints the flags the real CLIs document (codex-cli 0.170.0 ``exec`` / ``exec resume``, Claude Code
2.1.328), minus ``help_drop`` (``dev harness qualify`` T0, ``tests/adapters/test_harness_qualify.py``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _world() -> tuple[Path, dict[str, Any]]:
    path = Path(os.environ["FAKE_TOOLS_WORLD"])
    return path, json.loads(path.read_text(encoding="utf-8"))


def _say(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    stream.flush()
    stream.buffer.write((text + "\n").encode("utf-8"))
    stream.buffer.flush()


CODEX_EXEC_HELP = ("-c, --config <key=value>", "--enable <FEATURE>", "-i, --image <FILE>", "-m, --model <MODEL>",
                   "-p, --profile <CONFIG_PROFILE_V2>", "-s, --sandbox <SANDBOX_MODE>", "-C, --cd <DIR>",
                   "--skip-git-repo-check", "--ephemeral", "--json", "-o, --output-last-message <FILE>")
CODEX_RESUME_HELP = ("-c, --config <key=value>", "--last", "--all", "-m, --model <MODEL>", "--json")
CLAUDE_HELP = ("-p, --print", "--output-format <format>", "--verbose", "--include-hook-events",
               "--forward-subagent-text", "--mcp-config <configs...>", "--strict-mcp-config",
               "--setting-sources <sources>", "--allowedTools, --allowed-tools <tools...>",
               "-r, --resume [value]", "--permission-prompts <target>  (the SDK host or --permission-prompt-tool)")


def _help(title: str, flags: tuple[str, ...], drop: list[str]) -> int:
    _say(f"{title}\n\nOptions:")
    for line in flags:
        if not set(drop) & set(line.replace(",", " ").split()):
            _say(f"  {line}")
    return 0


def git(world: dict[str, Any], args: list[str]) -> int:
    state = world.setdefault("git", {})
    if args[:1] == ["-C"]:
        args = args[2:]
    head = state.get("head", "a" * 40)
    match args:
        case ["rev-parse", "--abbrev-ref", "HEAD"]:
            _say(state.get("branch", "main"))
        case ["symbolic-ref", *_]:
            _say(f"origin/{state.get('default', 'main')}")
        case ["status", *_]:
            for name in state.get("dirty", []):
                _say(f" M {name}")
        case ["rev-parse", "HEAD"]:
            _say(head)
        case ["rev-list", "--left-right", "--count", *_]:
            _say(f"0\t{state.get('behind', 0)}")
        case ["rev-list", "--count", _]:
            _say("3")
        case ["diff", "--name-only", *_]:
            _say("src/b1500_test_agent/devtools/update.py")
            if state.get("lock_changed"):
                _say("uv.lock")
        case ["pull", "--ff-only"]:
            mode = state.get("pull", "uptodate")
            if mode == "diverged":
                _say("hint: Diverging branches can't be fast-forwarded\nfatal: Not possible to fast-forward, "
                     "aborting.", err=True)
                return 128
            if mode == "offline":
                _say("fatal: unable to access 'https://example.invalid/x.git/': Could not resolve host: "
                     "example.invalid", err=True)
                return 1
            if mode == "error":
                _say("fatal: something unexpected", err=True)
                return 1
            if mode == "ok":
                state["head"] = state.get("new_head", "b" * 40)
                _say("Fast-forward")
            else:
                _say("Already up to date.")
        case _:
            _say(f"fake git: unsupported {args}", err=True)
            return 2
    return 0


def uv(world: dict[str, Any], args: list[str]) -> int:
    state = world.setdefault("uv", {})
    if args[:1] == ["sync"] and "--check" in args:
        if state.get("check", "ok") == "ok":
            _say("Would make no changes", err=True)
            return 0
        _say("Would install 1 package", err=True)
        return 1
    if args[:1] == ["sync"]:
        if state.get("sync", "ok") == "ok":
            _say("Audited 95 packages in 10ms", err=True)
            return 0
        _say("error: failed to remove file `.venv/Scripts/b1500.exe`: Access is denied. (os error 5)", err=True)
        return 2
    if args[:1] == ["run"] and args[-2:] == ["update", "--continue"]:
        _say("fake continuation of b1500 update")
        return int(state.get("continue_exit", 0))
    _say(f"fake uv: unsupported {args}", err=True)
    return 2


def npm(world: dict[str, Any], args: list[str]) -> int:
    state = world.setdefault("npm", {})
    if args[:2] == ["install", "-g"] and args[2].startswith("@openai/codex@"):
        if state.get("install", "ok") != "ok":
            _say("npm error code EACCES", err=True)
            return 1
        version = args[2].rsplit("@", 1)[1]
        world.setdefault("codex", {})["version"] = state.get("latest", "0.172.0") if version == "latest" else version
        _say("changed 1 package in 2s")
        return 0
    _say(f"fake npm: unsupported {args}", err=True)
    return 2


def codex(world: dict[str, Any], args: list[str]) -> int:
    state = world.setdefault("codex", {})
    if args == ["--version"]:
        _say(state.get("version_text") or f"codex-cli {state.get('version', '0.170.0')}")
        return 0
    if args == ["exec", "--help"]:
        return _help("Run Codex non-interactively", CODEX_EXEC_HELP, state.get("help_drop", []))
    if args == ["exec", "resume", "--help"]:
        return _help("Resume a previous session by id", CODEX_RESUME_HELP, state.get("help_drop", []))
    if args == ["login", "status"]:
        if state.get("login", True):
            _say("Logged in using ChatGPT")
            return 0
        _say("Not logged in")
        return 1
    if args[:3] == ["execpolicy", "check", "--rules"]:
        mode = state.get("execpolicy", "forbid")
        if mode == "garbage":
            _say("error: unknown subcommand 'execpolicy'")
            return 0
        if mode == "allow":
            _say('{"matchedRules":[]}')
            return 0
        _say(json.dumps({"matchedRules": [{"prefixRuleMatch": {"matchedPrefix": args[4:], "decision": "forbidden"}}],
                         "decision": "forbidden"}))
        return 0
    _say(f"fake codex: unsupported {args}", err=True)
    return 2


DOCTOR_HEAD = ("Claude Code doctor\n\nRunning: native ({version})\nPlatform: test\nConfig install method: native\n"
               "Auto-updates: enabled\n")
DOCTOR_TAIL = "\nNo installation issues found.\n"


def claude(world: dict[str, Any], args: list[str]) -> int:
    state = world.setdefault("claude", {})
    version = state.get("version", "2.1.328")
    if args == ["--version"]:
        _say(f"{version} (Claude Code)")
        return 0
    if args[:1] == ["install"]:
        mode = state.get("install", "ok")
        if mode == "fail":
            _say("Installation failed — could not download “claude” ✗", err=True)
            return 1
        if mode == "ok":
            state["version"] = state.get("latest", "2.1.330") if args[1] == "latest" else args[1]
        _say(f"Claude Code successfully installed! Version: {state.get('version', version)}")
        return 0
    if args == ["--help"]:
        return _help("Usage: claude [options] [command] [prompt]", CLAUDE_HELP, state.get("help_drop", []))
    if args[:2] == ["auth", "status"]:
        return 0 if state.get("login", True) else 1
    if args == ["doctor"]:
        mode = state.get("doctor", "clean")
        if mode == "garbage":
            _say("Error: Raw mode is not supported on the current process.stdin")
            return 0
        text = DOCTOR_HEAD.format(version=version)
        if mode == "invalid":
            repo = state["repo"]
            text += ("\nInvalid settings\n"
                     f"- {repo}/.claude/settings.json › permissions.allow: Invalid permission rule \"Bash(x\" was "
                     "skipped: Malformed Tool(content) rule.\n"
                     "- /home/someone/.claude/settings.json › model: Expected string, but received number\n"
                     "  Suggested fix: use a model name\n")
        _say(text + DOCTOR_TAIL)
        return 0
    _say(f"fake claude: unsupported {args}", err=True)
    return 2


TOOLS = {"git": git, "uv": uv, "npm": npm, "codex": codex, "claude": claude}


def main() -> int:
    tool, args = sys.argv[1], sys.argv[2:]
    with Path(os.environ["FAKE_TOOLS_LOG"]).open("a", encoding="utf-8") as log:
        log.write(json.dumps([tool, *args]) + "\n")
    path, world = _world()
    code = TOOLS[tool](world, args)
    path.write_text(json.dumps(world), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
