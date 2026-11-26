"""Child output is UTF-8 on every OS (CI fix from 06c2dbe: on Windows the fake ``claude doctor``'s ``›`` arrived as
``�`` because the fake, run with ``-I -S``, wrote in the console code page).

The harness CLIs (Node, Rust) write UTF-8 to a pipe whatever the code page, so every place that captures a child's
text decodes UTF-8 (``errors="replace"``), and the fakes write UTF-8 bytes. These tests inject non-ASCII lines and run
on every OS: a decoder left on the locale code page fails them on Windows, a fake that writes the code page fails the
byte check everywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from b1500_test_agent.devtools import harness_versions, update
from b1500_test_agent.devtools.acceptance import infra

FAKE = Path(__file__).with_name("fake_tools.py")
LINE = "settings.json › permissions.allow — naïve “quote” … ✓ 测试"
CHILD = [sys.executable, "-I", "-S", "-c",
         ("import sys; sys.stdout.buffer.write(sys.argv[1].encode('utf-8') + b'\\n'); "
          "sys.stderr.buffer.write(('err ' + sys.argv[1]).encode('utf-8') + b'\\n')"), LINE]


def _ctx(tmp_path: Path) -> update.UpdateContext:
    return update.UpdateContext(repo=tmp_path, environ=dict(os.environ), windows=os.name == "nt", home=tmp_path,
                                interactive=False, ask=lambda _q: False, say=lambda _s: None)


def test_update_context_decodes_child_output_as_utf8(tmp_path: Path) -> None:
    out = _ctx(tmp_path).run(CHILD)
    assert out.ok and LINE in out.stdout and f"err {LINE}" in out.stderr and "\ufffd" not in out.text


def test_version_runner_decodes_child_output_as_utf8() -> None:
    code, text = harness_versions.run_text(CHILD)
    assert code == 0 and LINE in text and "\ufffd" not in text


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_fake_tools_write_utf8_bytes(tmp_path: Path, stream: str) -> None:
    world, log = tmp_path / "world.json", tmp_path / "calls.jsonl"
    world.write_text(json.dumps({"claude": {"doctor": "invalid", "repo": "/clone"}}), encoding="utf-8")
    env = {**os.environ, "FAKE_TOOLS_WORLD": str(world), "FAKE_TOOLS_LOG": str(log)}
    args = ["claude", "doctor"] if stream == "stdout" else ["claude", "install", "9.9.9"]
    if stream == "stderr":
        world.write_text(json.dumps({"claude": {"install": "fail"}}), encoding="utf-8")
    result = subprocess.run([sys.executable, "-I", "-S", str(FAKE), *args], env=env, capture_output=True,
                            timeout=60, check=False)
    raw = result.stdout if stream == "stdout" else result.stderr
    text = raw.decode("utf-8")  # strict: a code-page byte would raise here
    if stream == "stdout":
        assert "/clone/.claude/settings.json › permissions.allow" in text
        assert "›".encode() in raw
    else:
        assert "Installation failed — could not download “claude” ✗" in text and "—".encode() in raw


def test_infra_watcher_reads_utf8_lines(tmp_path: Path) -> None:
    out, err = tmp_path / "out.jsonl", tmp_path / "err.txt"
    out.write_bytes(json.dumps({"type": "agent_message", "text": LINE}, ensure_ascii=False).encode("utf-8") + b"\n")
    err.write_bytes(f"ERROR codex: request timed out › {LINE}\n".encode())
    event = infra.InfraWatcher("codex", out, err, turn=1).poll(final=True)
    assert event is not None and event.kind == "network" and LINE in event.line
