"""The read-only bring-up probe and the inventory reading of the service facade (blueprint v2 7.1, 7.4 stage L0).

``probe`` is ``b1500 doctor --probe [--wgfmu-session]``. It never sends ``CN`` or any setting command: every FLEX
command goes through ``Session.read_only``, whose ``ReadOnlyTransport`` refuses anything but single queries, a device
clear and a serial poll; the WGFMU library is only located, read as a file, and (with ``--wgfmu-session``) asked for
its channel ids and status. Lines, in order:

1. ``visa library`` / ``visa resources`` (backend visa): the configured VISA library loads and ``list_resources()``
   lists the configured resource (``INFO`` on the simulator, which needs no VISA library);
2. ``bus``: open + exclusive lock (``visa.exclusive_lock``) under the instrument lock; ``busy`` when another
   process holds the instrument lock or another VISA client (EasyEXPERT) holds the bus, then nothing is sent;
3. ``identity`` (``*IDN?`` names the B1500A; firmware recorded), ``inventory`` (``UNT?`` against the active station
   profile, normally ``config/local/station.yaml``), ``error queue`` (``ERRX?`` drained; ``0,`` and ``+0,`` both mean
   empty), ``status byte`` (``*STB?``), ``outputs`` (``LOP?``: every slot off), ``settings`` (``*LRN? 31``: the
   auto-calibration switch, raw answer recorded), ``selectors`` (``ERMOD?``, then ``ERSSP?`` per declared 16440A
   output when the selector control mode is on), ``spgu`` (``SPST?``, only with an SPGU installed) and one ``cmu
   <alias>`` line per installed MFCMU (``CORRST?`` open/short/load, ``ADJ? ch,0`` = last phase compensation result
   without measuring);
4. ``release``: the bus was unlocked and closed;
5. ``wgfmu library`` (WP10.2): backend visa, a WGFMU installed: the DLL probe of the configured or default
   ``wgfmu.dll`` (path, x64, file version, exports; ``WgfmuDll.probe``, never a load): PASS when this Python can load
   it, FAIL for a 32-bit or incomplete DLL ("install library >= A.03.00") or a missing one, WARN off Windows; INFO on
   the simulator and without a WGFMU;
6. ``wgfmu session`` (``--wgfmu-session`` only; blueprint v2 7.1, ATV-16): with the FLEX link closed, the library's own
   session ``open_session`` -> ``channel_ids`` -> ``status`` -> ``close_session`` under the instrument lock: PASS when
   the channel ids cover the station's WGFMU channels and no sequencer runs;
7. ``fault latch``: no fault is latched.

A transport failure stops the remaining queries (their lines say "not run"); a parse failure fails only its line.
Every exchange is kept raw; ``work/bringup/probe-<UTC>.json`` (no ``:`` in the name) holds the whole report and an
audit event ``probe`` records the verdicts. ``ok`` is false exactly when a line FAILs (CLI exit 1).

``read_inventory`` reads ``*IDN?`` and ``UNT?`` the same read-only way (``b1500 bringup propose-station``).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.discovery import LOP_STATUS_CODES
from b1500_test_agent.driver.errors import DriverError, status_flags
from b1500_test_agent.driver.flex import ADJ_RESULTS, ERMOD_SELECTOR
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.bringup import InventoryReading, ProbeCheck, ProbeExchange, ProbeReport, ProbeStatus
from b1500_test_agent.models.common import ErrorCode, ResultStatus
from b1500_test_agent.models.routing import SwitchState
from b1500_test_agent.models.station import MODULE_TYPE_BY_MODEL, CmuCorrectionLive, DllProbe, ModuleInventory
from b1500_test_agent.service.common import clip
from b1500_test_agent.session import InstrumentBusy, Session
from b1500_test_agent.session.wgfmu_live import SessionCheck
from b1500_test_agent.transport.base import BusLocked, TransportError, unwrap
from b1500_test_agent.transport.readonly import ReadOnlyTransport
from b1500_test_agent.transport.wgfmu.api import COMMUNICATION_ERROR, STATUS_NAMES, STATUS_RUNNING, channel_ids_of

if TYPE_CHECKING:
    from b1500_test_agent.service.core import B1500Service

PROBE_DIR = "bringup"
"""Subdirectory of the work directory for probe records and proposals (``work/bringup/``)."""

SELECTOR_KIND = "selector_16440a"
NEXT_AFTER_PASS = "b1500 bringup propose-station compares the live inventory with config/local/station.yaml"
WGFMU_TYPE = "WGFMU"
INSTALL_LIBRARY = ("the human installs the B1530A WGFMU Instrument Library >= A.03.00 (x64 wgfmu.dll in System32) or "
                   "sets wgfmu.library in config/local/settings.yaml, then b1500 doctor")


def library_status(probe: DllProbe, *, required: bool, windows: bool) -> ProbeStatus:
    """Verdict on a WGFMU DLL probe (``b1500 doctor`` and the probe's ``wgfmu library`` line): PASS when loadable;
    WARN off Windows (the Mac: the simulator's library is used); on Windows a missing DLL FAILs when ``required``
    (backend visa with a WGFMU) and WARNs otherwise; a DLL that is there but cannot load (32-bit, missing exports,
    unreadable, 32-bit Python) always FAILs."""
    if probe.loadable:
        return "PASS"
    if not windows:
        return "WARN"
    if not probe.exists:
        return "FAIL" if required else "WARN"
    return "FAIL"


def utc_stamp(ts: datetime) -> str:
    """Windows-safe UTC file stamp with milliseconds: ``20261118T153012123Z`` (no ``:``)."""
    utc = ts.astimezone(UTC)
    return utc.strftime("%Y%m%dT%H%M%S") + f"{utc.microsecond // 1000:03d}Z"


def bringup_dir(bundle: ConfigBundle) -> Path:
    """``<work_dir>/bringup`` of the active configuration."""
    return bundle.paths.work_dir / PROBE_DIR


class _Probe:
    """Collects the lines and the live readings of one probe run."""

    def __init__(self, bundle: ConfigBundle, report_resource: str) -> None:
        self.bundle = bundle
        self.resource = report_resource
        self.checks: list[ProbeCheck] = []
        self.identity = None
        self.inventory: ModuleInventory | None = None
        self.switch_states: dict[str, SwitchState] | None = None
        self.cmu: dict[str, CmuCorrectionLive] | None = None
        self.wgfmu_library: DllProbe | None = None
        self.wgfmu_channels: list[int] | None = None
        self.link_broken = False
        self.next_steps: list[str] = []
        self.error_code: ErrorCode | None = None

    def add(self, name: str, status: ProbeStatus, detail: str, *, step: str | None = None) -> None:
        self.checks.append(ProbeCheck(name=name, status=status, detail=clip(detail, 600)))
        if step is not None and step not in self.next_steps:
            self.next_steps.append(step)

    def guarded(self, name: str, body: Callable[[], None]) -> None:
        """Run one instrument check; a transport failure stops the remaining ones, a parse failure fails this one."""
        if self.link_broken:
            self.add(name, "FAIL", "not run: an earlier query failed on the link")
            return
        try:
            body()
        except TransportError as exc:
            self.link_broken = True
            self.error_code = self.error_code or "transport_error"
            self.add(name, "FAIL", f"{type(exc).__name__}: {exc}",
                     step="check the GPIB cable, address and terminations (skill b1500-debug, visa-no-connection)")
        except DriverError as exc:
            self.error_code = self.error_code or "instrument_error"
            self.add(name, "FAIL", f"{type(exc).__name__}: {exc}")

    # -- instrument checks ------------------------------------------------------------------------------------------

    def run(self, driver: B1500Driver) -> None:
        self.guarded("identity", lambda: self.identity_check(driver))
        if self.checks and self.checks[-1].status == "FAIL":
            self.link_broken = True  # never send further commands to an instrument that is not a B1500A
            return
        self.guarded("inventory", lambda: self.inventory_check(driver))
        self.guarded("error queue", lambda: self.errors_check(driver))
        self.guarded("status byte", lambda: self.status_check(driver))
        self.guarded("outputs", lambda: self.outputs_check(driver))
        self.guarded("settings", lambda: self.settings_check(driver))
        self.guarded("selectors", lambda: self.selectors_check(driver))
        self.guarded("spgu", lambda: self.spgu_check(driver))
        for slot in self.installed_slots("MFCMU"):
            self.guarded(f"cmu {self.alias(slot)}", lambda slot=slot: self.cmu_check(driver, slot))

    def station_path(self) -> str:
        used = self.bundle.files.get("station")
        return used.path if used is not None else "the station profile"

    def alias(self, slot: int) -> str:
        module = next((m for m in self.bundle.station.modules if m.slot == slot), None)
        return module.alias if module is not None and module.alias else f"slot{slot}"

    def installed_slots(self, module_type: str) -> list[int]:
        if self.inventory is None:
            return []
        return [m.slot for m in self.inventory.modules if MODULE_TYPE_BY_MODEL.get(m.model) == module_type]

    def identity_check(self, driver: B1500Driver) -> None:
        identity = driver.identify()
        self.identity = identity
        if "B1500A" not in identity.model:
            self.error_code = "instrument_error"
            self.add("identity", "FAIL", f"the instrument identifies as {identity.raw!r}, not a B1500A; no further "
                                         "query is sent", step="check visa.resource in config/local/settings.yaml")
            return
        self.add("identity", "PASS", f"{identity.vendor} {identity.model}, firmware {identity.firmware}")

    def inventory_check(self, driver: B1500Driver) -> None:
        inventory = driver.modules()
        self.inventory = inventory
        installed = {m.slot: m.model for m in inventory.modules}
        expected = {m.slot: m.model for m in self.bundle.station.modules}
        listing = ", ".join(f"{slot} {model}" for slot, model in sorted(installed.items())) or "no module"
        differ = [f"slot {slot}: profile {model}, installed {installed.get(slot, 'nothing')}"
                  for slot, model in sorted(expected.items()) if installed.get(slot) != model]
        extra = [f"slot {slot} {model}" for slot, model in sorted(installed.items()) if slot not in expected]
        unknown = [f"slot {slot} {model}" for slot, model in sorted(installed.items())
                   if model not in MODULE_TYPE_BY_MODEL]
        propose = ("run b1500 bringup propose-station, review work/bringup/station.proposed.yaml with the human; "
                   "only the human adopts it into config/local/")
        where = self.station_path()
        if differ:
            self.add("inventory", "FAIL", f"installed modules differ from {where}: {'; '.join(differ)} (rule "
                                          f"R-INV-01 blocks runs on these slots); installed: {listing}", step=propose)
        elif extra or unknown:
            notes = []
            if extra:
                notes.append(f"installed but not in the profile: {', '.join(extra)} (runs cannot use them)")
            if unknown:
                notes.append(f"model unknown to this kernel: {', '.join(unknown)}")
            self.add("inventory", "WARN", f"{where} matches its {len(expected)} modules; {'; '.join(notes)}",
                     step=propose)
        else:
            self.add("inventory", "PASS", f"{len(expected)} modules match {where}: {listing}")

    def errors_check(self, driver: B1500Driver) -> None:
        errors = driver.errors(drain=True)
        if not errors:
            self.add("error queue", "PASS", "empty")
            return
        listed = "; ".join(f"{e.code} {e.message}".strip() for e in errors[:5])
        more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
        self.add("error queue", "WARN", f"drained {len(errors)} earlier error(s): {listed}{more}; they predate the "
                                        "probe (repeat the probe: a second drain must be empty)")

    def status_check(self, driver: B1500Driver) -> None:
        status = driver.status_byte()
        flags = status_flags(status)
        detail = f"value {status.value} ({', '.join(flags) if flags else 'no bit set'})"
        if status.interlock_open:
            detail += "; interlock open: the B1500A limits outputs to 42 V, as v2 expects (no workflow needs more)"
        if "error" in flags:
            self.add("status byte", "WARN", detail + "; the error bit is still set after draining the queue")
        else:
            self.add("status byte", "PASS", detail)

    def outputs_check(self, driver: B1500Driver) -> None:
        outputs = driver.output_state()
        on = {slot: out.state for slot, out in sorted(outputs.items()) if out.output_on}
        if on:
            listed = "; ".join(f"slot {slot} code {code} ({LOP_STATUS_CODES.get(code, 'unknown code')})"
                               for slot, code in on.items())
            self.add("outputs", "FAIL", f"output switch on: {listed}",
                     step="b1500 shutdown (zeroes and disconnects every output, verified), then probe again")
        else:
            self.add("outputs", "PASS", f"all {len(outputs)} slots report output off")

    def settings_check(self, driver: B1500Driver) -> None:
        try:
            on = driver.auto_calibration()
        except DriverError as exc:
            self.add("settings", "WARN", f"settings answer not understood ({exc}); the raw answer is recorded in the "
                                         "probe file for the bring-up L1 check")
            return
        self.add("settings", "INFO", f"auto-calibration {'ON' if on else 'OFF'} (asynchronous runs turn it off and "
                                     "restore it)")

    def selectors_check(self, driver: B1500Driver) -> None:
        selectors = [s for s in self.bundle.station.switches if s.kind == SELECTOR_KIND and s.present is not False]
        if not selectors:
            self.add("selectors", "INFO", f"no 16440A selector declared in {self.station_path()}; not read")
            return
        mode = driver.selector_control_mode()
        if not mode & ERMOD_SELECTOR:
            self.add("selectors", "INFO", f"digital I/O control mode {mode}: 16440A selector control off (power-on "
                                          "and reset state, ATV-18); the outputs are not read because that needs "
                                          "the control mode set, a setting the probe never sends; the first route "
                                          "sets it")
            return
        states: dict[str, SwitchState] = {}
        off_rest = []
        for switch in selectors:
            for output, port in sorted(switch.ports.items(), key=lambda item: item[1].index):
                state = driver.selector_state(port.index)
                states[f"{switch.id}.{output}"] = state
                if state != switch.rest:
                    off_rest.append(f"{switch.id}.{output} {state} (rest {switch.rest})")
        self.switch_states = states
        listed = ", ".join(f"{target} {state}" for target, state in states.items())
        if off_rest:
            self.add("selectors", "WARN", f"control mode {mode}; not at rest: {'; '.join(off_rest)}; the next "
                                          "transaction's cleanup restores declared outputs once routes exist")
        else:
            self.add("selectors", "PASS", f"control mode {mode}; every declared output at rest: {listed}")

    def spgu_check(self, driver: B1500Driver) -> None:
        slots = self.installed_slots("HVSPGU")
        if not slots:
            self.add("spgu", "INFO", "no SPGU installed; not read")
            return
        if driver.pulse_output_active():
            self.add("spgu", "FAIL", f"SPGU in slot {', '.join(map(str, slots))}: a pulse or ALWG output is active",
                     step="stop the SPGU output at the instrument (EasyEXPERT) or power-cycle it, then probe again")
        else:
            self.add("spgu", "PASS", f"SPGU in slot {', '.join(map(str, slots))}: output inactive")

    def cmu_check(self, driver: B1500Driver, slot: int) -> None:
        live = driver.correction_state(slot)  # CORRST? x3, ADJ? slot,0 and *LRN? 90 (the compensation mode)
        result = driver.phase_compensation_result(slot)
        alias = self.alias(slot)
        self.cmu = {**(self.cmu or {}), alias: live}
        states = ", ".join(f"{name} {'on' if on else 'off'}" for name, on in live.corr_state.items())
        detail = (f"slot {slot}: corrections {states}; phase compensation result {result} ({ADJ_RESULTS[result]}), "
                  f"{'in effect' if live.phase else 'not in effect'}")
        if result in (1, 2):
            self.add(f"cmu {alias}", "WARN", detail + "; repeat it at bring-up L6 with the terminals open")
        else:
            self.add(f"cmu {alias}", "INFO", detail + "; corrections are measured at bring-up L6")

    # -- WGFMU library (WP10.2) -------------------------------------------------------------------------------------

    def wgfmu_slots(self) -> list[int]:
        """Slots with a WGFMU: from the inventory when it was read, else from the station profile."""
        if self.inventory is not None:
            return self.installed_slots(WGFMU_TYPE)
        return sorted(m.slot for m in self.bundle.station.modules if m.type == WGFMU_TYPE)

    def library_check(self, session: Session) -> None:
        """The ``wgfmu library`` line (module docstring, line 5)."""
        name = "wgfmu library"
        wanted = bool(self.wgfmu_slots())
        if self.bundle.backend != "visa":
            self.add(name, "INFO", "backend sim: the WGFMU library is simulated (no wgfmu.dll is read); on the lab PC "
                                   "this line reads the DLL: path, x64, file version, exports" if wanted else
                     "backend sim: no WGFMU installed")
            return
        library = session.wgfmu_library()
        self.wgfmu_library = library
        if library is None:
            self.add(name, "FAIL" if wanted else "INFO", "no WGFMU library binding on this bus")
        elif not wanted:
            self.add(name, "INFO", f"no WGFMU installed or in {self.station_path()}; the library is not needed "
                                   f"({library.message})")
        else:
            inner = unwrap(session.bus.wgfmu)
            windows = getattr(inner, "platform", sys.platform) == "win32"
            status = library_status(library, required=True, windows=windows)
            self.add(name, status, library.message, step=None if status == "PASS" else INSTALL_LIBRARY)

    def session_check(self, svc: B1500Service, session: Session, flex_ok: bool) -> None:
        """The ``wgfmu session`` line (module docstring, line 6)."""
        name = "wgfmu session"
        slots = self.wgfmu_slots()
        if not slots:
            self.add(name, "INFO", "no WGFMU installed: no library session opened")
            return
        if not flex_ok:
            self.add(name, "FAIL", "not run: the FLEX part of the probe did not complete")
            return
        if self.wgfmu_library is not None and not self.wgfmu_library.loadable:
            self.add(name, "FAIL", "not opened: the WGFMU library is not loadable (see the wgfmu library line)",
                     step=INSTALL_LIBRARY)
            return
        try:
            result = session.check_wgfmu_session("probe: wgfmu session", lock_timeout_s=svc.lock_timeout_s)
        except InstrumentBusy as exc:
            self.error_code = self.error_code or "instrument_busy"
            self.add(name, "FAIL", f"not opened: {exc}",
                     step="wait until the run or call holding the instrument ends (b1500 lock status)")
            return
        self.wgfmu_channels = result.channels
        status, detail, step = self._session_verdict(result, session.transport.resource)
        self.add(name, status, detail, step=step)

    def _session_verdict(self, result: SessionCheck, resource: str) -> tuple[ProbeStatus, str, str | None]:
        expected = channel_ids_of(sorted(m.slot for m in self.bundle.station.modules if m.type == WGFMU_TYPE))
        if result.error is not None:
            self.error_code = self.error_code or result.error.code
            closing = f"; closing failed too: {result.close_error}" if result.close_error is not None else ""
            step = ("end EasyEXPERT and every other VISA program, then probe again"
                    if result.error.rc == COMMUNICATION_ERROR else
                    "check the WGFMU library install (b1500 doctor) and the RSU cables; bring-up L8 repeats it")
            return "FAIL", f"{result.error}{closing}", step
        channels = result.channels or []
        listed = ", ".join(map(str, channels)) or "none"
        code, elapsed, total = result.status or (0, 0.0, 0.0)
        state = STATUS_NAMES.get(code, f"code {code}")
        missing = sorted(set(expected) - set(channels))
        extra = sorted(set(channels) - set(expected))
        if missing:
            self.error_code = self.error_code or "instrument_error"
            return "FAIL", (f"the library reports channels {listed}; {self.station_path()} declares "
                            f"{', '.join(map(str, missing))} it does not (R-WG-01 blocks runs on them)"), (
                "compare UNT? with the library: a module the mainframe lists but the library does not see "
                "needs EasyEXPERT ended and the RSU connected")
        if code == STATUS_RUNNING:
            self.error_code = self.error_code or "instrument_error"
            return "FAIL", (f"channels {listed}; a WGFMU sequencer is running ({elapsed:.6g} of {total:.6g} s): "
                            "another program left a waveform running"), (
                "b1500 shutdown, or end the other program; then probe again")
        if result.close_error is not None:
            self.error_code = self.error_code or result.close_error.code
            return "FAIL", f"channels {listed}, status {state}; closing the session failed: {result.close_error}", None
        detail = (f"library session to {resource} opened and closed with the FLEX link closed; channels {listed}; "
                  f"status {state}")
        if extra:
            return "WARN", f"{detail}; installed but not in {self.station_path()}: {', '.join(map(str, extra))}", None
        return "PASS", detail, None


def _visa_lines(probe: _Probe, session: Session) -> list[str] | None:
    """``visa library`` and ``visa resources``; returns the listed resources, or ``None`` when the library failed
    (the bus is then not attempted)."""
    resource = session.transport.resource
    lister = getattr(unwrap(session.transport), "list_resources", None)
    if lister is None:
        probe.error_code = "transport_error"
        probe.add("visa library", "FAIL", "the configured transport cannot list VISA resources")
        return None
    try:
        listing = lister()
    except TransportError as exc:
        probe.error_code = "transport_error"
        probe.add("visa library", "FAIL", str(exc),
                  step="install the VISA stack of the GPIB adapter (one vendor only); set visa.library only when two "
                       "stacks are installed")
        return None
    where = f" ({listing.library_path})" if listing.library_path else ""
    probe.add("visa library", "PASS", f"{listing.library}{where} loaded")
    found = list(listing.resources)
    if resource in found:
        probe.add("visa resources", "PASS", f"{resource} listed ({len(found)} resource(s))")
    else:
        shown = ", ".join(found[:8]) or "none"
        probe.add("visa resources", "WARN", f"{resource} is not listed (found: {shown}); the open below decides",
                  step="check the GPIB address (visa.resource), the cable and that EasyEXPERT is ended")
    return found


def probe(svc: B1500Service, bundle: ConfigBundle, *, wgfmu_session: bool = False) -> ProbeReport:
    """The read-only probe (see the module docstring); ``wgfmu_session`` adds the library session check; never
    raises for a failing line."""
    session = svc.executor.session(bundle)
    backend = bundle.backend
    transport = session.transport
    resource = transport.resource
    taken_at = datetime.now(UTC)
    probe_run = _Probe(bundle, resource)
    visa_resources: list[str] | None = None
    fault = session.fault_latch.get()
    if backend == "visa":
        visa_resources = _visa_lines(probe_run, session)
        attempt = visa_resources is not None
    else:
        probe_run.add("visa library", "INFO", f"backend sim: no VISA library is used; the simulator answers as "
                                              f"{resource} (scenario {bundle.settings.sim.scenario})")
        attempt = True
    reader: ReadOnlyTransport | None = None
    if attempt:
        try:
            with session.read_only("probe", lock_timeout_s=svc.lock_timeout_s) as driver:
                reader = driver.transport if isinstance(driver.transport, ReadOnlyTransport) else None
                if backend != "visa":
                    probe_run.add("bus", "PASS", f"opened {resource} (simulator)")
                elif bundle.settings.visa.exclusive_lock:
                    probe_run.add("bus", "PASS", f"opened {resource}; exclusive VISA lock taken")
                else:
                    probe_run.add("bus", "WARN", f"opened {resource} without the exclusive VISA lock "
                                                 "(visa.exclusive_lock: false): another client could interleave")
                probe_run.run(driver)
        except InstrumentBusy as exc:
            probe_run.error_code = "instrument_busy"
            probe_run.add("bus", "FAIL", f"{exc}; nothing was sent",
                          step="wait until the run or call holding the instrument ends (b1500 lock status)")
        except BusLocked as exc:
            probe_run.error_code = "instrument_busy"
            probe_run.add("bus", "FAIL", f"{exc}",
                          step="end EasyEXPERT (File > Exit, leave the Start EasyEXPERT button) and other VISA "
                               "programs, then probe again")
        except TransportError as exc:
            probe_run.error_code = probe_run.error_code or "transport_error"
            if not any(c.name == "bus" for c in probe_run.checks):
                probe_run.add("bus", "FAIL", f"cannot open {resource}: {exc}",
                              step="check the GPIB address, cable and the VISA stack (skill b1500-debug, "
                                   "visa-no-connection)")
            else:
                probe_run.add("release", "FAIL", f"{type(exc).__name__}: {exc}")
        else:
            if session.bus_open:
                probe_run.add("release", "PASS", f"lock released; {resource} kept open (visa.session: process)")
            else:
                probe_run.add("release", "PASS", f"lock released and {resource} closed")
    flex_ok = reader is not None and not probe_run.link_broken and not any(
        c.status == "FAIL" and c.name in ("bus", "release", "identity") for c in probe_run.checks)
    probe_run.library_check(session)
    if wgfmu_session:
        probe_run.session_check(svc, session, flex_ok)
    if fault is not None:
        probe_run.add("fault latch", "FAIL", f"latched since {fault.set_at.isoformat()}: {fault.reason}",
                      step="a human reviews the fault, then runs the fault clear command (human only)")
    else:
        probe_run.add("fault latch", "PASS", "no fault latched")
    return _finish(svc, bundle, session, probe_run, taken_at, reader, visa_resources)


def _finish(svc: B1500Service, bundle: ConfigBundle, session: Session, probe_run: _Probe, taken_at: datetime,
            reader: ReadOnlyTransport | None, visa_resources: list[str] | None) -> ProbeReport:
    checks = probe_run.checks
    counts = {status: sum(c.status == status for c in checks) for status in ("PASS", "WARN", "FAIL", "INFO")}
    failed = counts["FAIL"] > 0
    code: ErrorCode | None = (probe_run.error_code or "instrument_error") if failed else None
    status: ResultStatus = "ok" if not failed else "busy" if code == "instrument_busy" else "error"
    head = "SIMULATED probe" if bundle.backend == "sim" else "probe"
    message = (f"{head} of {probe_run.resource}: {counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail, "
               f"{counts['INFO']} info")
    transcript = [ProbeExchange(cmd=e.cmd, resp=e.resp, error=e.error) for e in (reader.transcript if reader else [])]
    report = ProbeReport(
        ok=not failed, status=status, error_code=code, **svc._envelope(bundle.backend), message=message,
        next_steps=probe_run.next_steps or ([] if failed else [NEXT_AFTER_PASS]),
        resource=probe_run.resource, taken_at=taken_at, checks=checks, identity=probe_run.identity,
        inventory=probe_run.inventory, visa_resources=visa_resources, switch_states=probe_run.switch_states,
        cmu_corrections=probe_run.cmu, wgfmu_library=probe_run.wgfmu_library, wgfmu_channels=probe_run.wgfmu_channels,
        transcript=transcript,
    )
    record = _write_record(bundle, report, taken_at)
    report = report.model_copy(update={"record": record})
    data: dict[str, str | int | bool | float | None] = {"ok": report.ok, "record": record,
                                                        **{f"n_{k.lower()}": v for k, v in counts.items()}}
    data.update({f"check.{c.name}": c.status for c in checks})
    session.audit.emit(AuditEvent.now("probe", bundle.backend, intent="probe", data=data))
    return report


def _write_record(bundle: ConfigBundle, report: ProbeReport, taken_at: datetime) -> str | None:
    """Write the report to ``work/bringup/probe-<UTC>.json``; its repository-relative path, or ``None`` when the
    work directory is not writable (the report says so in its message instead)."""
    folder = bringup_dir(bundle)
    stem = f"probe-{utc_stamp(taken_at)}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{stem}.json"
        index = 2
        while path.exists():
            path = folder / f"{stem}-{index}.json"
            index += 1
        record = bundle.paths.display(path)
        payload = report.model_copy(update={"record": record}).model_dump(mode="json")
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        return None
    return record


def read_inventory(svc: B1500Service, bundle: ConfigBundle) -> InventoryReading:
    """``*IDN?`` and ``UNT?`` through a read-only session (``InstrumentBusy``/``TransportError`` propagate to the
    service's error mapping)."""
    session = svc.executor.session(bundle)
    taken_at = datetime.now(UTC)
    with session.read_only("bringup: propose-station", lock_timeout_s=svc.lock_timeout_s) as driver:
        identity = driver.identify()
        inventory = driver.modules()
    head = "SIMULATED instrument" if bundle.backend == "sim" else "instrument"
    return InventoryReading(ok=True, status="ok", **svc._envelope(bundle.backend),
                            message=f"{head} {identity.model} at {session.transport.resource}: "
                                    f"{len(inventory.modules)} modules",
                            resource=session.transport.resource, taken_at=taken_at, identity=identity,
                            inventory=inventory)
