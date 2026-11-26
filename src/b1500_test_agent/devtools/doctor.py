"""``b1500 doctor``: installation and station-readiness checks without instrument I/O (blueprint 7).

Each check is PASS, INFO, WARN or FAIL; the command exits non-zero when any check FAILs. Checks: Python version and
architecture; ``uv.lock`` in sync with ``pyproject.toml`` (``uv lock --check --offline``); imports of the runtime
dependencies (``pyvisa`` only located, never imported outside ``transport/visa.py``); configuration (rule R-CFG-01:
schemas, active files example vs local, why the backend was chosen); ``config/local`` completeness (``local config``,
blueprint v2 7.1: switch wiring and presence the human has not recorded on a switch a pin map routes through, pulse
and AC envelopes of the DUT terminals sources without compliance and the MFCMU can reach, local pin maps and DUT
profiles on backend visa, the load standard when the policy requires it; ``check_local_config``); ``data/`` writable
and free space; clone path
length (WARN above 80 characters on Windows); stale inflight marker or latched fault; skills mirror
(``.claude/skills/`` = the generated copy of ``.agents/skills/``: FAIL on drift, WARN when there is no skill); harness
files (the committed ``.claude/settings.json``, Codex rules, guard hook and
examples wired as blueprint 5.4 says; each generated ``.codex/config.toml`` / ``.mcp.json`` free of drift, both on
the same ``b1500-mcp`` entry point, ``run_confirmed_plan`` = ``prompt`` / ``ask``; WARN when none is generated yet);
harness versions (v2.1 plan §2.2: each installed ``codex``/``claude`` CLI against ``config/harness/validated.yaml``,
version and install method; WARN "run ``uv run b1500 update``", INFO when no harness CLI is on ``PATH``);
the MCP server starts with exactly the ten tools within the token budget; the manual corpus (blueprint 5.2: PASS
when the committed corpus is current, WARN when stale or missing) and the manual PDFs (optional: PASS when all are
found, INFO when some or all are absent, WARN on an edition mismatch); the WGFMU instrument library (WP10.2: the
configured or default ``System32\\wgfmu.dll`` located and its PE header read without loading it: path, x64, file
version, exports; PASS when this Python can load it, FAIL for a 32-bit or incomplete DLL ("install library >=
A.03.00") and for a missing one when backend visa has a WGFMU, WARN off Windows); ``PYTHONUTF8`` and
``LongPathsEnabled`` (Windows).

The read-only instrument probe (``b1500 doctor --probe``: VISA library and resources, identity, inventory, error
queue, status byte, outputs, selectors, SPGU, MFCMU corrections; never ``CN`` or a setting command) is a service
operation (``service/probe.py``, ``B1500Admin.probe``), not one of these installation checks.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import shutil
import struct
import subprocess
import sys
import uuid
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from b1500_test_agent.config import ConfigBundle, ConfigLoader
from b1500_test_agent.devtools import budget, harness, harness_versions, sync_harness
from b1500_test_agent.devtools.harness_versions import HARNESSES, LABELS, VALIDATED_FILE
from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.manuals import search as manual_search
from b1500_test_agent.manuals.catalog import ManualError, ManualPaths
from b1500_test_agent.models.policy import DutProfile
from b1500_test_agent.models.routing import rsu_smu_inputs
from b1500_test_agent.models.station import PinMap, Settings, StationProfile, cmu_side, switch_target
from b1500_test_agent.paths import Paths
from b1500_test_agent.service import TOOL_NAMES
from b1500_test_agent.session import read_inflight
from b1500_test_agent.session.fault import FaultLatch
from b1500_test_agent.session.lock import InstrumentLock
from b1500_test_agent.transport.audit import NullAuditSink
from b1500_test_agent.transport.wgfmu.dll import WgfmuDll

CheckStatus = Literal["PASS", "INFO", "WARN", "FAIL"]
MCP_SERVER_SPEC = "b1500_test_agent.adapters.mcp_server:create_server"
RUNTIME_MODULES = ("pydantic", "yaml", "numpy", "pandas", "matplotlib", "typer", "filelock", "fastmcp")
BUDGET_TOTAL = 4500
BUDGET_PER_TOOL = 700
WINDOWS_PATH_WARN = 80
MIN_FREE_BYTES = 1 << 30


class DoctorCheck(BaseModel):
    """One check: name, PASS/INFO/WARN/FAIL and what was found (INFO: optional item absent, nothing to fix)."""

    name: str
    status: CheckStatus
    detail: str


class DoctorReport(BaseModel):
    """All checks; ``ok`` is false when any check FAILed."""

    ok: bool
    checks: list[DoctorCheck]


def _check(name: str, status: CheckStatus, detail: str) -> DoctorCheck:
    return DoctorCheck(name=name, status=status, detail=detail)


def check_python() -> DoctorCheck:
    version = sys.version_info
    bits = struct.calcsize("P") * 8
    detail = f"{platform.python_implementation()} {platform.python_version()} {platform.machine()} ({bits}-bit)"
    if not (3, 11) <= version[:2] < (3, 14):
        return _check("python", "FAIL", detail + "; requires >=3.11,<3.14")
    if bits != 64:
        return _check("python", "FAIL", detail + "; a 64-bit interpreter is required")
    return _check("python", "PASS", detail)


def check_uv_lock(repo_root: Path) -> DoctorCheck:
    lock = repo_root / "uv.lock"
    if not lock.is_file():
        return _check("uv.lock", "FAIL", f"{lock.as_posix()} is missing (git pull, then uv sync --frozen)")
    uv = shutil.which("uv")
    if uv is None:
        return _check("uv.lock", "WARN", "uv not found on PATH; cannot check that uv.lock matches pyproject.toml")
    try:
        result = subprocess.run([uv, "lock", "--check", "--offline", "--project", str(repo_root)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return _check("uv.lock", "WARN", f"uv lock --check could not run: {exc}")
    lines = [line.strip() for line in f"{result.stderr}\n{result.stdout}".splitlines() if line.strip()]
    if result.returncode == 0:
        return _check("uv.lock", "PASS", "in sync with pyproject.toml")
    if any("needs to be updated" in line for line in lines):
        return _check("uv.lock", "FAIL", "uv.lock does not match pyproject.toml (git pull, then uv sync --frozen)")
    errors = [line for line in lines if line.lower().startswith("error")] or lines
    return _check("uv.lock", "WARN", f"could not check offline: {errors[0] if errors else result.returncode}")


def check_imports(backend: str | None) -> DoctorCheck:
    missing = []
    for name in RUNTIME_MODULES:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            missing.append(f"{name} ({exc})")
    visa_found = importlib.util.find_spec("pyvisa") is not None  # located only, never imported here
    if missing:
        return _check("imports", "FAIL", "missing: " + ", ".join(missing) + " (uv sync --frozen)")
    if not visa_found:
        status: CheckStatus = "FAIL" if backend == "visa" else "WARN"
        return _check("imports", status, "runtime packages import; pyvisa is not installed (needed for visa)")
    return _check("imports", "PASS", f"{', '.join(RUNTIME_MODULES)} import; pyvisa installed")


def check_config(loader: ConfigLoader) -> tuple[DoctorCheck, ConfigBundle | None]:
    report = loader.check()
    if not report.ok:
        problems = "; ".join(f"{p.file or 'config'}: {p.message}" for p in report.problems[:5])
        return _check("config", "FAIL", f"invalid_config: {problems} (b1500 config check)"), None
    sources: dict[str, list[str]] = {}
    for item in report.files:
        sources.setdefault(item.source, []).append(item.key)
    used = "; ".join(f"{source}: {', '.join(keys)}" for source, keys in sorted(sources.items()))
    detail = f"backend {report.backend_reason}; files {used}"
    status: CheckStatus = "WARN" if report.warnings else "PASS"
    if report.warnings:
        detail += "; warnings: " + "; ".join(report.warnings[:3])
    return _check("config", status, detail), loader.get()


PULSE_MODULES: Final[dict[str, str]] = {"HVSPGU": "SPGU", "WGFMU": "WGFMU"}
"""Module types that source without compliance; a DUT terminal they reach needs a ``pulse`` envelope (R-PULSE-02)."""
INPUT_NEEDS: Final[dict[str, tuple[str, str]]] = {"pgu": ("pulse", "SPGU"), "wgfmu": ("pulse", "WGFMU"),
                                                   "cmu": ("ac", "MFCMU")}
"""Switch input side -> (envelope a terminal behind it needs, source): PGU and WGFMU pulses, the MFCMU's AC signal."""
NEED_RULE: Final[dict[str, str]] = {"pulse": "R-PULSE-02", "ac": "R-CMU-01"}
LIST_MAX = 4


@dataclass(frozen=True)
class TerminalNeed:
    """A pin-map terminal that a source without compliance or the MFCMU can reach, and the envelope it needs."""

    pin_map: str
    terminal: str
    envelope: Literal["pulse", "ac"]
    via: str


def terminal_needs(station: StationProfile, pin_map: PinMap) -> list[TerminalNeed]:
    """The ``pulse``/``ac`` envelopes the DUT terminals of ``pin_map`` need: a terminal wired to an HV-SPGU or WGFMU
    channel, or behind a switch output with a ``pgu``/``wgfmu`` input, needs ``pulse``; one on an MFCMU side or
    channel, or behind an SCUU/ASU output with a ``cmu`` input, needs ``ac``. SMU pulse roles are judged per plan
    (every SMU terminal could carry one)."""
    needs: list[TerminalNeed] = []
    for terminal, target in sorted(pin_map.terminals.items()):
        found: dict[str, str] = {}
        side, ref = cmu_side(target), switch_target(target)
        if side is not None:
            found["ac"] = f"MFCMU {target}"
        elif isinstance(target, int):
            module = station.module_for_channel(target)
            if module is not None and module.type in PULSE_MODULES:
                found["pulse"] = f"{PULSE_MODULES[module.type]} channel {target}"
            elif module is not None and module.type == "MFCMU":
                found["ac"] = f"MFCMU channel {target}"
        elif ref is not None:
            switch = station.switch(ref[0])
            port = switch.ports.get(ref[1]) if switch is not None else None
            for input_side in sorted(port.inputs) if port is not None else ():
                if input_side in INPUT_NEEDS:
                    envelope, source = INPUT_NEEDS[input_side]
                    found.setdefault(envelope, f"{source} via {target}")
        needs += [TerminalNeed(pin_map.name, terminal, envelope, via)  # type: ignore[arg-type]
                  for envelope, via in sorted(found.items())]
    return needs


def fitting_duts(pin_map: PinMap, duts: Mapping[str, DutProfile]) -> list[DutProfile]:
    """DUT profiles that fit the landing: they declare every pin-map terminal that is not on the GNDU."""
    landed = {t for t, target in pin_map.terminals.items() if target not in ("GNDU", None)}
    return [dut for _, dut in sorted(duts.items()) if landed <= set(dut.terminals)]


def switch_gaps(station: StationProfile) -> dict[str, list[str]]:
    """Per switch the facts a human has not recorded yet: ``present: null`` and every ``null`` input
    (``SEL1.OUT1 smu``); a switch declared absent has none."""
    gaps: dict[str, list[str]] = {}
    for switch in station.switches:
        if switch.present is False:
            continue
        items = [f"{switch.id} presence unknown"] if switch.present is None else []
        items += [f"{switch.id}.{output} {side}" for output, port in sorted(switch.ports.items())
                  for side, channel in sorted(port.inputs.items()) if channel is None]
        if items:
            gaps[switch.id] = items
    return gaps


def _listed(items: list[str]) -> str:
    more = f" (+{len(items) - LIST_MAX} more)" if len(items) > LIST_MAX else ""
    return ", ".join(items[:LIST_MAX]) + more


def check_local_config(bundle: ConfigBundle | None) -> DoctorCheck:
    """``config/local`` completeness (blueprint v2 7.1): the facts only the human can record, which the plans that
    need them are blocked without. Read from the active configuration (``config/local/`` on the lab PC, the
    committed examples on the simulator), never from the instrument.

    - **Switch wiring**: a ``null`` input or ``present: null`` on a switch a pin map routes through blocks those
      routes on hardware (R-PIN-01, R-ROUTE-01) until the human records it (stages L6-L8) or deletes a side that is
      not cabled. On the simulator the scenario's cabling stands in for selector and RSU inputs
      (``planning_station``), so there the gaps are listed, never warned about. On hardware an RSU's unknown "From
      SMU" input also blocks every SMU plan above +-25 V or 100 mA (R-RSU-01): a note says so.
    - **DUT envelopes**: every pin-map terminal a source without compliance (HV-SPGU, WGFMU) or the MFCMU can reach
      needs a ``pulse``/``ac`` envelope in a DUT profile that fits the landing (declares every terminal not on the
      GNDU); without one, pulses (R-PULSE-02) or C-V (R-CMU-01) there are blocked. A human declares them; the agent
      never invents one (hard rule 6).
    - **Files** (backend visa): pin maps and DUT profiles come from ``config/local/`` only; none at all blocks every
      plan. ``corrections.<MFCMU>.load`` must be recorded when the policy requires a load correction.

    WARN for any of these gaps, PASS otherwise; INFO when the configuration is invalid (the ``config`` check
    FAILs)."""
    if bundle is None:
        return _check("local config", "INFO", "not checked: the configuration is invalid (see config)")
    visa = bundle.backend == "visa"
    sources = {f.source for f in bundle.files.values()}
    where = "config/local" if sources == {"local"} else (
        "config/local + examples" if "local" in sources else
        "examples (no config/local/: the simulator runs them; b1500 config init creates it on the lab PC)"
        if "override" not in sources else "B1500_CONFIG_DIR (tests)")
    station, pin_maps, duts = bundle.station, bundle.pin_maps, bundle.dut_profiles
    warnings: list[str] = []
    notes: list[str] = [f"{len(pin_maps)} pin maps, {len(duts)} DUT profiles"]
    if visa and not pin_maps:
        warnings.append("no pin map in config/local/pinmaps: every plan with DUT roles is blocked (R-PIN-01); "
                        "adopt the stage's pin maps (b1500 config adopt FILE --as pinmap)")
    if visa and not duts:
        warnings.append("no DUT profile in config/local/duts: every plan with DUT roles is blocked (R-DUT-01); "
                        "adopt or write them (b1500 config adopt FILE --as dut)")
    gaps = switch_gaps(station)
    used: dict[str, set[str]] = {}
    for name, pin_map in sorted(pin_maps.items()):
        for switch_id, _output in pin_map.switch_targets().values():
            used.setdefault(switch_id, set()).add(name)
    blocking = [f"{'/'.join(gaps[sid])} (pin maps {', '.join(sorted(used[sid]))})" for sid in sorted(gaps)
                if sid in used]
    idle = [item for sid in sorted(gaps) if sid not in used for item in gaps[sid]]
    unverified = [s.id for s in station.switches if s.present is not False and s.certainty == "unverified"]
    if blocking and visa:
        warnings.append(f"switch wiring not recorded: {_listed(blocking)}; routes through them stay blocked "
                        "(R-PIN-01, R-ROUTE-01) until the human records each input or deletes a side that is not "
                        "cabled (stages L6-L8)")
    elif blocking:
        notes.append(f"switch wiring not recorded: {_listed(blocking)} (simulator: the scenario's cabling stands "
                     "in for selector inputs; on hardware these routes stay blocked until stages L6-L8 record them)")
    if idle:
        notes.append(f"unrecorded on switches no pin map uses: {_listed(idle)}")
    unknown_rsu = [item.target for item in rsu_smu_inputs(station.switches) if item.channel is None]
    if unknown_rsu and visa:
        notes.append(f"RSU From SMU input unknown ({_listed(unknown_rsu)}): every SMU plan above +-25 V or 100 mA "
                     "stays blocked (R-RSU-01, WG p20 (1-8)) until the human records which SMU feeds each RSU or "
                     "deletes the smu side when none is cabled (stage L8)")
    if unverified:
        notes.append(f"switches unverified (plans through them need confirmation, unverified_topology): "
                     f"{', '.join(unverified)}")
    needs = [need for name, pin_map in sorted(pin_maps.items()) for need in terminal_needs(station, pin_map)]
    missing = []
    for need in needs:
        fits = fitting_duts(pin_maps[need.pin_map], duts)
        if not any(getattr(dut.terminals[need.terminal], need.envelope) is not None for dut in fits):
            missing.append(f"{need.pin_map}.{need.terminal} {need.envelope} ({need.via}; "
                           f"{NEED_RULE[need.envelope]})")
    if missing:
        warnings.append(f"no fitting DUT profile declares the envelope for {_listed(missing)}: pulses or C-V there "
                        "stay blocked until a human adds it to a DUT profile (never invented)")
    elif needs:
        notes.append(f"DUT envelopes: all {len(needs)} pulse/AC terminals of the pin maps covered by a fitting DUT "
                     "profile")
    if "load" in bundle.policy.corrections.require:
        loads = [m.alias for m in station.modules if m.type == "MFCMU"
                 and (station.corrections.get(m.alias) is None or station.corrections[m.alias].load is None)]
        if loads:
            warnings.append(f"policy requires a load correction but the load standard of {', '.join(loads)} is not "
                            "recorded (station.yaml#corrections; R-CORR-01 blocks C-V)")
    detail = f"{where}: " + "; ".join([*warnings, *notes])
    return _check("local config", "WARN" if warnings else "PASS", detail)


def check_data_dir(paths: Paths) -> DoctorCheck:
    root = paths.data_root
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".doctor-{uuid.uuid4().hex[:8]}.tmp"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return _check("data dir", "FAIL", f"{root.as_posix()} is not writable: {exc}")
    free = shutil.disk_usage(root).free
    detail = f"{paths.display(root)} writable, {free / 1e9:.1f} GB free"
    return _check("data dir", "WARN" if free < MIN_FREE_BYTES else "PASS", detail)


def check_path_length(paths: Paths, *, windows: bool) -> DoctorCheck:
    length = len(str(paths.repo_root))
    detail = f"clone path has {length} characters"
    if windows and length > WINDOWS_PATH_WARN:
        return _check("path length", "WARN", detail + f" (> {WINDOWS_PATH_WARN}); prefer a short ASCII path")
    return _check("path length", "PASS", detail + ("" if windows else " (the 80-character limit applies on Windows)"))


def check_state(bundle: ConfigBundle | None, paths: Paths) -> DoctorCheck:
    state_dir = bundle.paths.state_dir if bundle is not None else paths.state_dir
    fault = FaultLatch(state_dir, audit=NullAuditSink(), backend=bundle.backend if bundle else "sim").get()
    if fault is not None:
        return _check("state", "FAIL", f"fault latched since {fault.set_at.isoformat()}: {fault.reason} (a human "
                                       "reviews it, then b1500 fault clear)")
    marker = read_inflight(state_dir / "inflight.json")
    if marker is not None:
        held = False
        if bundle is not None:
            resource = (f"SIM::{bundle.settings.sim.scenario}" if bundle.backend == "sim"
                        else bundle.settings.visa.resource)
            try:
                held = InstrumentLock(state_dir, resource).is_held()
            except ValueError:
                held = False
        if not held:
            return _check("state", "WARN", f"stale inflight marker of {marker.intent!r}: the next transaction "
                                           "recovers it (or run b1500 shutdown)")
        return _check("state", "PASS", f"a transaction is running ({marker.intent})")
    return _check("state", "PASS", "no fault latched, no inflight marker")


def check_skills_mirror(repo_root: Path) -> DoctorCheck:
    """``.claude/skills/`` (Claude Code) is the up-to-date generated copy of ``.agents/skills/`` (blueprint 6.6)."""
    report = sync_harness.check(repo_root)
    fix = "run uv run b1500 dev sync-harness"
    if report.problems:
        return _check("skills mirror", "FAIL", "; ".join(report.problems[:3]))
    if report.drift:
        listed = ", ".join(f"{item.kind} {item.path}" for item in report.drift[:3])
        more = f" (+{len(report.drift) - 3} more)" if len(report.drift) > 3 else ""
        return _check("skills mirror", "FAIL", f"{sync_harness.MIRROR_DIR} drifted from {sync_harness.SOURCE_DIR}: "
                                               f"{listed}{more}; {fix}")
    if not report.skills:
        return _check("skills mirror", "WARN", f"no skill under {sync_harness.SOURCE_DIR} (git pull)")
    return _check("skills mirror", "PASS", f"{sync_harness.MIRROR_DIR} in sync ({report.files} files; "
                                           f"{', '.join(report.skills)})")


def check_harness_files(repo_root: Path) -> DoctorCheck:
    """Committed harness files wired per blueprint 5.4; generated configs free of drift on one entry point."""
    _, problems = harness.committed_problems(repo_root, harness.TARGETS)
    generated = [t for t in harness.TARGETS.values() if (repo_root / t.output).is_file()]
    for target in generated:
        problems += harness.rendered_problems(repo_root, target)
    if problems:
        more = f" (+{len(problems) - 3} more; b1500 harness init --codex --claude --check)" if len(problems) > 3 else ""
        return _check("harness files", "FAIL", "; ".join(problems[:3]) + more)
    modes = {"codex": f"{harness.CONFIRM_TOOL} prompt", "claude": f"{harness.CONFIRM_TOOL} ask"}
    parts = [f"{t.name}: {t.output} ({modes[t.name]})" if t in generated else f"{t.name}: not generated"
             for t in harness.TARGETS.values()]
    launch = harness.expected_launch("<clone>")
    entry = f"{launch.command} {' '.join(launch.args)} -> {harness.ENTRY_POINT_TARGET}"
    detail = "; ".join(parts) + f"; entry point {entry}"
    if not generated:
        return _check("harness files", "WARN", detail + " (run b1500 harness init --codex and/or --claude)")
    return _check("harness files", "PASS", detail)


def check_harness_versions(repo_root: Path, environ: Mapping[str, str], *, lab: bool,
                           which: harness_versions.Which | None = None,
                           run: harness_versions.Runner | None = None) -> DoctorCheck:
    """``harness versions`` (v2.1 plan §2.2): each installed harness CLI against ``config/harness/validated.yaml``.

    PASS when every installed CLI is the validated version, installed the validated way (Codex npm, Claude Code
    native); WARN "run ``uv run b1500 update``" otherwise, and when a newer version runs on a machine that is not the
    lab station (backend sim: the maintainer's Mac on the stable channel) also "or qualify it"; INFO when no harness
    CLI is on ``PATH`` (CI); WARN when the file is missing or invalid. Reads ``--version`` only."""
    try:
        validated = harness_versions.load_validated(repo_root)
    except harness_versions.ValidatedError as exc:
        return _check("harness versions", "WARN", str(exc))
    which = which or harness_versions.default_which(environ)
    run = run or (lambda argv: harness_versions.run_text(argv, environ))
    passed: list[str] = []
    problems: list[str] = []
    newer = False
    for name in HARNESSES:
        want, label = validated.get(name), LABELS[name]
        found = harness_versions.find_installed(name, which=which, run=run)
        if found is None:
            continue
        if found.method != want.install:
            problems.append(f"{label} at {found.executable} is a {found.method} install, the validated one is "
                            f"{want.install}")
        elif found.version is None:
            problems.append(f"{label}: cannot read its version ({found.raw!r})")
        elif found.version != want.version:
            problems.append(f"{label} {found.version} installed, {want.version} validated")
            newer = newer or harness_versions.version_key(found.version) > harness_versions.version_key(want.version)
        else:
            passed.append(f"{label} {found.version} ({found.method})")
    wanted = ", ".join(f"{LABELS[n]} {validated.get(n).version}" for n in HARNESSES)
    if not passed and not problems:
        return _check("harness versions", "INFO", f"no harness CLI on PATH (codex, claude); validated: {wanted} "
                                                  f"({VALIDATED_FILE})")
    if problems:
        hint = "run `uv run b1500 update`" + (
            " or qualify it: `uv run b1500 dev harness qualify`" if newer and not lab else "")
        ok = f"; {', '.join(passed)} = validated" if passed else ""
        return _check("harness versions", "WARN", "; ".join(problems) + ok + f": {hint}")
    return _check("harness versions", "PASS", f"{', '.join(passed)} = {VALIDATED_FILE}")


def check_mcp_server(spec: str = MCP_SERVER_SPEC) -> DoctorCheck:
    try:
        app = budget.load_app(spec)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            report = budget.measure_app(app, label=spec)
    except Exception as exc:  # noqa: BLE001 - any failure to start the server is the finding
        return _check("mcp server", "FAIL", f"server does not start: {type(exc).__name__}: {exc}")
    names = tuple(row.name for row in report.tools)
    largest = max((row.tokens for row in report.tools), default=0)
    detail = f"{len(names)} tools, {report.total_tokens} tokens (largest {largest}; {report.method})"
    if sorted(names) != sorted(TOOL_NAMES):
        return _check("mcp server", "FAIL", detail + f"; expected exactly {list(TOOL_NAMES)}")
    if report.total_tokens > BUDGET_TOTAL or largest > BUDGET_PER_TOOL:
        return _check("mcp server", "FAIL", detail + f"; budget {BUDGET_TOTAL} total, {BUDGET_PER_TOOL} per tool")
    return _check("mcp server", "PASS", detail)


def check_manuals(repo_root: Path, setting: str, environ: Mapping[str, str]) -> list[DoctorCheck]:
    """``manual corpus`` (committed page corpus current?) and ``manual PDFs`` (optional source PDFs present?)."""
    paths = ManualPaths.for_repo(repo_root, setting, environ)
    fix = "uv run b1500 manual build (needs the PDFs)"
    if not paths.catalog.is_file():
        return [_check("manual corpus", "WARN", f"no manual catalog at {paths.display(paths.catalog)} (git pull)"),
                _check("manual PDFs", "INFO", "not checked without a catalog")]
    try:
        status = manual_search.status(paths)
    except ManualError as exc:
        return [_check("manual corpus", "FAIL", str(exc)), _check("manual PDFs", "INFO", "not checked")]
    size = f"{status.corpus_bytes / 1000:.0f} kB"
    corpus = {
        "current": _check("manual corpus", "PASS", f"{status.docs_in_corpus} docs, {status.pages_in_corpus} pages "
                                                   f"({size}) in {status.corpus_dir}; b1500 manual search|page|toc"),
        "stale": _check("manual corpus", "WARN", f"stale: built from another catalog; {fix}"),
        "missing": _check("manual corpus", "WARN", f"missing in {status.corpus_dir}: manual queries answer from the "
                                                   f"structured extracts only (git pull, or {fix})"),
        "invalid": _check("manual corpus", "FAIL", status.message),
    }[status.corpus]
    where = f"{status.manuals_dir} ({status.manuals_dir_source})"
    missing = [d.id for d in status.docs if d.pdf == "missing"]
    mismatch = [d.id for d in status.docs if d.pdf == "mismatch"]
    total = len(status.docs)
    if mismatch:
        pdfs = _check("manual PDFs", "WARN", f"edition mismatch (sha256 differs from the catalog): "
                                             f"{', '.join(mismatch)} in {where}; see b1500 manual status")
    elif not missing:
        pdfs = _check("manual PDFs", "PASS", f"{total}/{total} PDFs in {where}")
    else:
        found = f"{total - len(missing)}/{total} PDFs in {where}" + (
            f" (missing {', '.join(missing)})" if len(missing) < total else "")
        pdfs = _check("manual PDFs", "INFO", f"{found}; optional - the committed corpus answers manual queries, "
                                             "PDFs are needed only for figures and manual build (B1500_MANUALS_DIR)")
    return [corpus, pdfs]


def check_wgfmu_library(bundle: ConfigBundle | None, environ: Mapping[str, str], *, windows: bool) -> DoctorCheck:
    """The WGFMU instrument library (``WgfmuDll.locate``: a file read, never a load); see the module docstring."""
    from b1500_test_agent.service.probe import library_status

    settings = bundle.settings if bundle is not None else Settings()
    platform = "win32" if windows else (sys.platform if sys.platform != "win32" else "linux")
    probe = WgfmuDll.locate(settings, platform=platform, environ=environ)
    wgfmu = bundle is not None and any(m.type == "WGFMU" for m in bundle.station.modules)
    required = wgfmu and bundle is not None and bundle.backend == "visa"
    status = library_status(probe, required=required, windows=windows)
    detail = probe.message
    if status != "PASS" and wgfmu:
        detail += "; WGFMU recipes on backend visa need it (blueprint 7.5 step 2)"
    return _check("wgfmu library", status, detail)


def check_pythonutf8(environ: Mapping[str, str], *, windows: bool) -> DoctorCheck:
    value = environ.get("PYTHONUTF8")
    if value == "1" or sys.flags.utf8_mode:
        return _check("PYTHONUTF8", "PASS", "UTF-8 mode on")
    if windows:
        return _check("PYTHONUTF8", "WARN", "PYTHONUTF8 is not 1 here; the generated harness MCP configs set it")
    return _check("PYTHONUTF8", "PASS", "not set (needed on Windows only; harness MCP configs set it)")


def check_long_paths(*, windows: bool) -> DoctorCheck:
    if not windows:
        return _check("LongPathsEnabled", "PASS", "not applicable on this OS")
    try:
        import winreg  # Windows-only standard library module (absent elsewhere: platform-injected tests)

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem")
        value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
    except ImportError:
        return _check("LongPathsEnabled", "WARN", "cannot read the registry value: winreg is not available here")
    except OSError as exc:
        return _check("LongPathsEnabled", "WARN", f"cannot read the registry value: {exc}")
    if value == 1:
        return _check("LongPathsEnabled", "PASS", "enabled")
    return _check("LongPathsEnabled", "WARN", "disabled; keep the clone path short (run paths must stay < 200 chars)")


def run_doctor(*, environ: Mapping[str, str] | None = None, windows: bool | None = None,
               mcp_check: Callable[[], DoctorCheck] | None = None,
               harness_check: Callable[[], DoctorCheck] | None = None) -> DoctorReport:
    """Run every non-probe check (see the module docstring); never raises for a failing check. Tests replace the
    two checks that start processes (``mcp_check``, ``harness_check``)."""
    env = os.environ if environ is None else environ
    on_windows = sys.platform == "win32" if windows is None else windows
    loader = ConfigLoader(environ=env)
    checks = [check_python()]
    try:
        paths = Paths.from_env(env)
    except InvalidConfigError as exc:
        checks.append(_check("repository", "FAIL", str(exc)))
        return DoctorReport(ok=False, checks=checks)
    config_check, bundle = check_config(loader)
    if bundle is not None:
        paths = bundle.paths
    checks += [
        check_uv_lock(paths.repo_root),
        check_imports(bundle.backend if bundle is not None else None),
        config_check,
        check_local_config(bundle),
        check_data_dir(paths),
        check_path_length(paths, windows=on_windows),
        check_state(bundle, paths),
        check_skills_mirror(paths.repo_root),
        check_harness_files(paths.repo_root),
        harness_check() if harness_check is not None else check_harness_versions(
            paths.repo_root, env, lab=bundle is not None and bundle.backend == "visa"),
        (mcp_check or check_mcp_server)(),
        *check_manuals(paths.repo_root, (bundle.settings if bundle is not None else Settings()).manuals_dir, env),
        check_wgfmu_library(bundle, env, windows=on_windows),
        check_pythonutf8(env, windows=on_windows),
        check_long_paths(windows=on_windows),
    ]
    return DoctorReport(ok=all(c.status != "FAIL" for c in checks), checks=checks)


def format_report(report: DoctorReport) -> str:
    width = max(len(c.name) for c in report.checks)
    lines = [f"{c.status:<4}  {c.name:<{width}}  {c.detail}" for c in report.checks]
    fails = sum(c.status == "FAIL" for c in report.checks)
    warns = sum(c.status == "WARN" for c in report.checks)
    infos = sum(c.status == "INFO" for c in report.checks)
    lines.append(f"doctor: {'ok' if report.ok else 'FAIL'} ({fails} fail, {warns} warn, {infos} info, "
                 f"{len(report.checks)} checks)")
    return "\n".join(lines)
