"""File primitives (``fsio``): an atomic JSON write uses a temporary file of its own (two threads of one process once
shared ``<name>.tmp-<pid>``, and the loser of each ``AbortFile.request`` pair got ``FileNotFoundError``), named so
that no state glob matches it; Windows sharing violations are retried for ``RETRY_BUDGET_S`` and POSIX permission
errors are not (the platform is injected); exclusive publication refuses an existing file on both branches and an
interrupt before it leaves no file; locked line appends; file digests; the host name."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import filelock
import pytest

from b1500_test_agent import fsio
from b1500_test_agent.session import AbortFile


class FakeClock:
    """Stand-in for ``fsio.time``: ``sleep`` advances ``monotonic`` at once and is recorded."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(fsio, "time", fake)
    return fake


def windows(monkeypatch: pytest.MonkeyPatch, flag: bool = True) -> None:
    """Inject the platform branch of ``fsio``."""
    monkeypatch.setattr(fsio, "_WINDOWS", flag)


def denied_while(condition: Callable[[], bool], real: Callable[..., Any], calls: list[str]) -> Callable[..., Any]:
    """A replacement for an ``os`` call that raises ``PermissionError`` while ``condition()`` holds (a sharing
    violation: another process has the file open), then does the real call."""

    def call(*args: Any, **kwargs: Any) -> Any:
        calls.append(str(args[0]))
        if condition():
            raise PermissionError(errno.EACCES, "The process cannot access the file (sharing violation)", args[0])
        return real(*args, **kwargs)

    return call


def windows_rename(real_replace: Callable[..., Any]) -> Callable[..., Any]:
    """``os.rename`` with Windows semantics on any platform: an existing target is never replaced."""

    def rename(src: Any, dst: Any) -> None:
        if os.path.lexists(dst):
            raise FileExistsError(errno.EEXIST, "Cannot create a file when that file already exists", str(dst))
        real_replace(src, dst)

    return rename


def entries(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# -- atomic_write_json -----------------------------------------------------------------------------------------------


def test_two_threads_requesting_an_abort_at_once_never_fail(tmp_path: Path) -> None:
    """The MCP shutdown hook and a ``safe_shutdown`` tool thread write ``abort.json`` at the same moment: 300 pairs,
    no exception (the shared temporary name made every pair fail one writer), the last request is readable and no
    temporary file is left."""
    abort = AbortFile(tmp_path)
    errors: Counter[str] = Counter()
    barrier = threading.Barrier(2)
    written: list[str] = []

    def writer(tag: str) -> None:
        for _ in range(300):
            barrier.wait()
            try:
                written.append(abort.request(tag, adapter="mcp").id)
            except Exception as exc:  # noqa: BLE001 - every failure is counted
                errors[type(exc).__name__] += 1

    threads = [threading.Thread(target=writer, args=(tag,)) for tag in ("hook", "tool")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == Counter()
    assert len(written) == 600
    final = abort.read()
    assert final is not None and final.id in written and final.reason in ("hook", "tool")
    assert entries(tmp_path) == ["abort.json"]


def test_many_threads_writing_one_file_leave_a_whole_file(tmp_path: Path) -> None:
    target = tmp_path / "state" / "inflight.json"
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        for i in range(50):
            try:
                fsio.atomic_write_json(target, {"writer": n, "i": i, "pad": "x" * 2000})
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["i"] == 49 and len(record["pad"]) == 2000
    assert entries(target.parent) == ["inflight.json"]


def test_the_temporary_file_matches_no_state_glob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """While the new content waits for ``os.replace``, its file is ``.<name>.<random>.tmp`` in the target's folder:
    neither ``*.json`` nor ``inflight-*`` (the globs readers of the state folder use) sees it."""
    target = tmp_path / "inflight-sim-nmos_basic.json"
    seen: dict[str, Any] = {}
    real = os.replace

    def spy(src: Any, dst: Any) -> None:
        seen["tmp"] = Path(src)
        seen["json"] = sorted(p.name for p in tmp_path.glob("*.json"))
        seen["inflight"] = sorted(p.name for p in tmp_path.glob("inflight-*"))
        real(src, dst)

    fsio.atomic_write_json(target, {"run": 1})
    monkeypatch.setattr(os, "replace", spy)
    fsio.atomic_write_json(target, {"run": 2})
    tmp = seen["tmp"]
    assert tmp.parent == tmp_path and fsio.is_temp_name(tmp.name)
    assert tmp.name.startswith(".inflight-sim-nmos_basic.json.") and tmp.name.endswith(".tmp")
    assert seen["json"] == seen["inflight"] == ["inflight-sim-nmos_basic.json"]
    assert json.loads(target.read_text(encoding="utf-8")) == {"run": 2}


def test_json_bytes_and_parent_folders(tmp_path: Path) -> None:
    data = {"reason": "µ outputs off", "n": [1, 2.5, None], "nested": {"a": True}}
    target = tmp_path / "a" / "b" / "fault.json"
    fsio.atomic_write_json(target, data)
    assert target.read_bytes() == (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    assert b"\r\n" not in target.read_bytes()


def test_windows_retries_a_sharing_violation_that_lasts_one_second(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """``os.replace`` raising ``PermissionError`` for 1 s (an antivirus scanner or sync client holding the target)
    still succeeds within the retry budget (real time)."""
    windows(monkeypatch)
    target = tmp_path / "fault.json"
    fsio.atomic_write_json(target, {"v": "old"})
    start = time.monotonic()
    calls: list[str] = []
    monkeypatch.setattr(os, "replace", denied_while(lambda: time.monotonic() - start < 1.0, os.replace, calls))
    fsio.atomic_write_json(target, {"v": "new"})
    elapsed = time.monotonic() - start
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": "new"}
    assert 1.0 <= elapsed < fsio.RETRY_BUDGET_S + 1.0 and len(calls) > 2
    assert entries(tmp_path) == ["fault.json"]


def test_windows_gives_up_after_the_retry_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                 clock: FakeClock) -> None:
    windows(monkeypatch)
    target = tmp_path / "fault.json"
    fsio.atomic_write_json(target, {"v": "old"})
    calls: list[str] = []
    monkeypatch.setattr(os, "replace", denied_while(lambda: True, os.replace, calls))
    start = clock.now
    with pytest.raises(PermissionError):
        fsio.atomic_write_json(target, {"v": "new"})
    assert clock.now - start == pytest.approx(fsio.RETRY_BUDGET_S)
    assert clock.sleeps[0] == pytest.approx(0.01) and max(clock.sleeps) == pytest.approx(0.2)
    assert len(calls) == len(clock.sleeps) + 1
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": "old"}
    assert entries(tmp_path) == ["fault.json"]  # the temporary file is removed


def test_posix_raises_a_permission_error_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                 clock: FakeClock) -> None:
    windows(monkeypatch, False)
    calls: list[str] = []
    monkeypatch.setattr(os, "replace", denied_while(lambda: True, os.replace, calls))
    with pytest.raises(PermissionError):
        fsio.atomic_write_json(tmp_path / "fault.json", {"v": 1})
    assert len(calls) == 1 and clock.sleeps == []
    assert entries(tmp_path) == []


def test_an_interrupt_before_the_replace_keeps_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "abort.json"
    fsio.atomic_write_json(target, {"v": "old"})

    def interrupted(src: Any, dst: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        fsio.atomic_write_json(target, {"v": "new"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": "old"}
    assert entries(tmp_path) == ["abort.json"]


# -- exclusive publication -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["posix", "windows"])
def test_exclusive_write_publishes_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock,
                                        platform: str) -> None:
    """POSIX publishes with ``os.link``, Windows with ``os.rename`` (retried on a sharing violation); both refuse a
    target that exists and leave it unchanged."""
    if platform == "windows":
        windows(monkeypatch)
        failures = [2]

        def busy() -> bool:
            failures[0] -= 1
            return failures[0] >= 0

        calls: list[str] = []
        monkeypatch.setattr(os, "rename", denied_while(busy, windows_rename(os.replace), calls))
    else:
        windows(monkeypatch, False)
    target = tmp_path / "manifest.json"
    fsio.atomic_write_json(target, {"run": 1}, exclusive=True)
    if platform == "windows":
        assert len(clock.sleeps) == 2  # two sharing violations, then the rename
    with pytest.raises(FileExistsError):
        fsio.atomic_write_json(target, {"run": 2}, exclusive=True)
    assert json.loads(target.read_text(encoding="utf-8")) == {"run": 1}
    assert entries(tmp_path) == ["manifest.json"]
    if platform == "posix":
        assert target.stat().st_nlink == 1  # the temporary name is gone


def test_exclusive_write_without_hard_links_still_refuses_an_existing_file(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """A file system without hard links (``os.link`` fails, e.g. FAT or a network share): the file is still
    published whole with ``os.replace`` after an existence check."""
    windows(monkeypatch, False)

    def no_links(src: Any, dst: Any) -> None:
        raise OSError(errno.EPERM, "Operation not permitted", str(src))

    monkeypatch.setattr(os, "link", no_links)
    target = tmp_path / "manifest.json"
    fsio.atomic_write_json(target, {"run": 1}, exclusive=True)
    with pytest.raises(FileExistsError):
        fsio.atomic_write_json(target, {"run": 2}, exclusive=True)
    assert json.loads(target.read_text(encoding="utf-8")) == {"run": 1}
    assert entries(tmp_path) == ["manifest.json"]


@pytest.mark.parametrize("platform", ["posix", "windows"])
def test_an_interrupt_before_the_exclusive_publish_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                  platform: str) -> None:
    windows(monkeypatch, platform == "windows")

    def interrupted(src: Any, dst: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "rename" if platform == "windows" else "link", interrupted)
    target = tmp_path / "manifest.json"
    with pytest.raises(KeyboardInterrupt):
        fsio.atomic_write_json(target, {"run": 1}, exclusive=True)
    assert entries(tmp_path) == []
    monkeypatch.undo()
    fsio.atomic_write_json(target, {"run": 1}, exclusive=True)
    assert json.loads(target.read_text(encoding="utf-8")) == {"run": 1}


# -- remove_file -----------------------------------------------------------------------------------------------------


def test_remove_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
    target = tmp_path / "abort.json"
    fsio.remove_file(target)  # missing: nothing to do
    target.write_text("{}", encoding="utf-8")
    fsio.remove_file(target)
    assert not target.exists()

    real_unlink = Path.unlink
    calls: list[str] = []
    failures = [3]

    def busy() -> bool:
        failures[0] -= 1
        return failures[0] >= 0

    target.write_text("{}", encoding="utf-8")
    windows(monkeypatch)
    monkeypatch.setattr(Path, "unlink", denied_while(busy, real_unlink, calls))
    fsio.remove_file(target)
    assert not target.exists() and len(calls) == 4 and len(clock.sleeps) == 3

    target.write_text("{}", encoding="utf-8")
    windows(monkeypatch, False)
    calls.clear()
    failures[0] = 1
    with pytest.raises(PermissionError):
        fsio.remove_file(target)
    assert target.exists() and len(calls) == 1


# -- append_line -----------------------------------------------------------------------------------------------------


def test_append_line_appends_utf8_lines(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "index.jsonl"
    assert fsio.append_line(path, '{"run_id":"a"}') == '{"run_id":"a"}'
    assert fsio.append_line(path, lambda: '{"run_id":"µ"}') == '{"run_id":"µ"}'
    assert path.read_bytes() == '{"run_id":"a"}\n{"run_id":"µ"}\n'.encode()


def test_the_line_is_computed_while_the_lock_is_held(tmp_path: Path) -> None:
    path = tmp_path / "notes.jsonl"
    lock_path = tmp_path / "custom.lock"
    held: list[bool] = []

    def line() -> str:
        probe = filelock.FileLock(lock_path, fallback_to_soft=False)
        try:
            probe.acquire(timeout=0)
        except filelock.Timeout:
            held.append(True)
        else:
            probe.release()
            held.append(False)
        return "x"

    fsio.append_line(path, line, lock_path=lock_path)
    assert held == [True]


def test_append_line_waits_for_the_lock_and_times_out(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    path.write_text("first\n", encoding="utf-8")
    holder = filelock.FileLock(tmp_path / "index.jsonl.lock", fallback_to_soft=False)  # the default lock file
    with holder, pytest.raises(filelock.Timeout) as caught:
        fsio.append_line(path, "second", timeout_s=0.05)
    assert isinstance(caught.value, OSError)
    assert path.read_text(encoding="utf-8") == "first\n"
    fsio.append_line(path, "second")
    assert path.read_text(encoding="utf-8") == "first\nsecond\n"


@pytest.mark.parametrize("text", ["two\nlines", "carriage\rreturn", "trailing\n"])
def test_append_line_writes_exactly_one_line(tmp_path: Path, text: str) -> None:
    path = tmp_path / "notes.jsonl"
    with pytest.raises(ValueError, match="line break"):
        fsio.append_line(path, text)
    with pytest.raises(ValueError, match="line break"):
        fsio.append_line(path, lambda: text)
    assert not path.exists()


def test_append_line_closes_a_torn_last_line(tmp_path: Path) -> None:
    """A writer killed mid-line left no final newline: the new line starts on a line of its own, so it stays well
    formed; the torn line stays torn (readers skip it)."""
    path = tmp_path / "index.jsonl"
    path.write_bytes(b'{"run_id":"a"}\n{"run_id":"tor')
    fsio.append_line(path, '{"run_id":"b"}')
    assert path.read_bytes().splitlines() == [b'{"run_id":"a"}', b'{"run_id":"tor', b'{"run_id":"b"}']
    fsio.append_line(path, '{"run_id":"c"}')
    assert path.read_bytes().endswith(b'{"run_id":"b"}\n{"run_id":"c"}\n')


def test_append_line_from_many_threads(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        for i in range(100):
            try:
                fsio.append_line(path, json.dumps({"writer": n, "i": i, "pad": "y" * 500}))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 800
    for n in range(8):
        assert [r["i"] for r in records if r["writer"] == n] == list(range(100))


# -- sha256_file, host_name, is_temp_name ----------------------------------------------------------------------------


@pytest.mark.parametrize("size", [0, 1, (3 << 20) + 5])
def test_sha256_file(tmp_path: Path, size: int) -> None:
    data = os.urandom(size)
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    assert fsio.sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_host_name(monkeypatch: pytest.MonkeyPatch) -> None:
    assert fsio.host_name()

    def broken() -> str:
        raise OSError("no host name")

    monkeypatch.setattr(fsio.socket, "gethostname", broken)
    assert fsio.host_name() == "unknown"
    monkeypatch.setattr(fsio.socket, "gethostname", lambda: "")
    assert fsio.host_name() == "unknown"


@pytest.mark.parametrize(("name", "temp"), [(".fault.json.k2j3h4ab.tmp", True), (".progress.json.x.tmp", True),
                                            ("fault.json", False), ("data.tmp", False), (".append.lock", False),
                                            ("index.jsonl.lock", False)])
def test_is_temp_name(name: str, temp: bool) -> None:
    assert fsio.is_temp_name(name) is temp
