"""``station_status`` of the service facade (blueprint 5.1, v2 2.9): configuration, limits, modules vs profile, live
state, fault latch, lock holder, the run holding the instrument and the MFCMU correction freshness (WP8.2).

While a run holds the instrument (an asynchronous run of this process, or any run of another process seen through
its in-flight marker and the held lock) ``station_status`` never waits for the lock: it answers ``busy: run <id>
(<done>/<total>)`` from the last snapshot of this process (``live: cached``) and names the run in ``active_run``.

Interlock label (blueprint v2 10.2 row 6.2; standing decision "interlock never used"): ``interlock_open`` is status
byte bit 3, and its meaning differs by backend. The simulator keeps bit 3 equal to its scenario's interlock state;
the B1500A sets it only when an output or compliance above 42 V was requested with the interlock open and clears it
on a serial poll (PG p76-77 (1-56), ATV-10), so on hardware a clear bit says nothing about the circuit.
``interlock_label`` puts that into words for the agent and the CLI; it changes no behaviour (R-IL-01 and the
42 V / 100 mA code ceiling are unchanged).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from b1500_test_agent.archive.corrections import CorrectionStore
from b1500_test_agent.catalog.corrections import station_mfcmus
from b1500_test_agent.catalog.running import ActiveRun
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.errors import B1500Error, InvalidConfigError
from b1500_test_agent.models.common import ConfigReport, ErrorCode, ResultStatus
from b1500_test_agent.models.results import (
    ActiveRunStatus,
    ConfigFileBrief,
    ConfigStatus,
    LimitsStatus,
    LiveSource,
    ModuleCheck,
    StationStatus,
)
from b1500_test_agent.models.station import CorrectionCheck, CorrectionFreshness, LiveState, StationProfile
from b1500_test_agent.rules.builtin.cmu import CORRECTION_CARD
from b1500_test_agent.service.common import clip, status_for
from b1500_test_agent.session import InstrumentBusy

if TYPE_CHECKING:
    from b1500_test_agent.service.core import B1500Service


def config_status(report: ConfigReport) -> ConfigStatus:
    """The configuration part of ``station_status``."""
    return ConfigStatus(
        ok=report.ok, backend_reason=report.backend_reason,
        files=[ConfigFileBrief(key=f.key, source=f.source, path=f.path, sha256=f.sha256[:12]) for f in report.files],
        problems=list(report.problems), warnings=list(report.warnings),
        digest=report.digest[:12] if report.digest else None,
    )


def status_invalid(svc: B1500Service, exc: InvalidConfigError) -> StationStatus:
    """``station_status`` while the configuration is invalid: the problems, nothing else."""
    report = svc.config.check()
    backend = report.backend or "sim"
    return StationStatus(ok=False, status="error", error_code="invalid_config", **svc._envelope(backend),
                         message=clip(f"configuration invalid: {exc}"), config=config_status(report),
                         next_steps=[("no measurement is possible until a human fixes config/local/ "
                                     "(b1500 config check); never edit it yourself")])


def module_checks(station: StationProfile, live: LiveState | None) -> list[ModuleCheck]:
    """Profile vs installed module per slot (``match`` ``None`` without a live inventory)."""
    inventory = live.inventory if live is not None else None
    checks = []
    for module in station.modules:
        installed = inventory.model_in_slot(module.slot) if inventory is not None else None
        checks.append(ModuleCheck(slot=module.slot, expected=module.model, installed=installed, type=module.type,
                                  alias=module.alias, match=None if inventory is None else installed == module.model))
    if inventory is not None:
        known = {m.slot for m in station.modules}
        checks += [ModuleCheck(slot=m.slot, installed=m.model, match=False)
                   for m in inventory.modules if m.slot not in known]
    return sorted(checks, key=lambda c: c.slot)


def interlock_label(backend: str, station: StationProfile, live: LiveState | None) -> str | None:
    """The ``interlock`` text of ``station_status`` (module docstring); ``None`` without a live status byte."""
    if live is None or live.status_byte is None:
        return None
    bit3 = live.status_byte.interlock_open
    if backend == "sim":
        return ("SIMULATED open (scenario): outputs limited to 42 V" if bit3
                else "SIMULATED closed (scenario)")
    if station.interlock.available:
        use = "wired and tested at stage S0 (station profile)"
    else:
        use = "not used at this station: kept open, the B1500A limits outputs to 42 V (the code ceiling)"
    if bit3:
        return (f"{use}; STB bit 3 SET: an output or compliance above 42 V was requested with the interlock open and "
                "refused (an event, cleared by a serial poll; see errors 202/203)")
    return f"{use}; STB bit 3 clear (it flags only a refused >42 V request, not the circuit state; ATV-10)"


def limits_status(bundle: ConfigBundle) -> LimitsStatus:
    """Policy limits and how they map to tiers (blueprint 4.1, 4.3; run durations v2 2.6)."""
    policy = bundle.policy
    hard, soft, runs = policy.hard_limits, policy.soft_limits, policy.run_limits
    tiers = (f"ok: |V| <= {soft.voltage_v:g} V and |Icomp| <= {soft.compliance_a:g} A, inside the DUT profile, "
             f"validated recipe, verified pin map; needs_confirmation: above soft up to hard limits or another "
             f"confirm reason; blocked: above {hard.max_abs_voltage_v:g} V / {hard.max_abs_compliance_a:g} A, "
             "missing DUT profile or pin map, not_implemented")
    return LimitsStatus(
        hard_max_abs_voltage_v=hard.max_abs_voltage_v, hard_max_abs_compliance_a=hard.max_abs_compliance_a,
        soft_voltage_v=soft.voltage_v, soft_compliance_a=soft.compliance_a,
        interlock_required_above_v=policy.interlock.required_above_v,
        max_points=runs.max_points.model_dump(), max_sync_run_s=runs.max_sync_run_s,
        long_run_confirm_s=runs.long_run_confirm_s, max_async_run_s=runs.max_async_run_s,
        segment_max_s=runs.segment_max_s, plan_ttl_h=policy.plans.ttl_h, tiers=tiers,
    )


def freshness_text(freshness: CorrectionFreshness) -> str:
    """One line per MFCMU for ``station_status.corrections`` (see ``StationStatus.corrections``)."""
    def item(check: CorrectionCheck) -> str:
        aged = f" {check.age_h:.1f} h" if check.age_h is not None else ""
        return f"{check.kind}{aged}" if freshness.fresh else f"{check.kind} {check.state}{aged}"

    if freshness.fresh:
        return "fresh: " + ", ".join(item(c) for c in freshness.checks)
    return "not fresh: " + "; ".join(item(c) for c in freshness.checks)


def correction_status(bundle: ConfigBundle, live: LiveState | None,
                      now: datetime | None = None) -> tuple[dict[str, str], list[str]]:
    """``station_status.corrections`` for every MFCMU of the station profile and the notes for its message (file
    reads only: the store under ``policy.corrections``, records of this station profile and, with a live identity,
    this mainframe)."""
    store = CorrectionStore(bundle.paths.state_dir)
    idn = live.identity.raw.strip() if live is not None and live.identity is not None else None
    found: dict[str, str] = {}
    notes: list[str] = []
    for alias in station_mfcmus(bundle.station):
        try:
            freshness = store.freshness(alias, bundle.policy.corrections, now=now or datetime.now(UTC), idn=idn,
                                        station_sha=bundle.sha256("station"))
        except B1500Error as exc:
            found[alias] = f"unreadable: {exc}"[:200]
            notes.append(f"MFCMU {alias} correction store unreadable")
            continue
        found[alias] = freshness_text(freshness)
        if not freshness.fresh:
            notes.append(f"MFCMU {alias} corrections not fresh (C-V blocked by R-CORR-01; card {CORRECTION_CARD})")
    return found, notes


def active_run_status(active: ActiveRun) -> ActiveRunStatus:
    """``station_status.active_run`` of a running run."""
    progress = active.progress
    return ActiveRunStatus(
        run_id=active.run_id, plan_id=active.plan_id, recipe_id=active.recipe_id,
        mode="async" if active.mode == "async" else "sync", adapter=active.adapter, pid=active.pid,
        started_at=active.started_at, state=progress.state if progress is not None else "running",
        done=progress.done if progress is not None else None, total=progress.total if progress is not None else None,
        phase=progress.phase if progress is not None else "", eta_s=progress.eta_s if progress is not None else None,
    )


def station_status(svc: B1500Service, bundle: ConfigBundle, refresh: bool) -> StationStatus:
    """The ``station_status`` result (see the module docstring)."""
    session = svc.executor.session(bundle)
    active = svc.executor.active_run(bundle)
    live: LiveState | None = None
    source: LiveSource = "not_read"
    live_error: str | None = None
    live_code: ErrorCode | None = None
    if active is not None:
        if session.last_live is not None:  # the run holds the instrument: never wait for its lock
            live, source = session.last_live, "cached"
    elif refresh:
        try:
            live = session.snapshot(refresh=True, lock_timeout_s=svc.lock_timeout_s)
            source = "fresh"
        except InstrumentBusy as exc:
            source, live_error, live_code = "unavailable", str(exc), exc.code
        except B1500Error as exc:
            source, live_error, live_code = "unavailable", f"{type(exc).__name__}: {exc}", exc.code
    elif session.last_live is not None:
        live, source = session.last_live, "cached"
    fault = session.fault_latch.get()
    backend = bundle.backend
    modules = module_checks(bundle.station, live)
    mismatched = [m.slot for m in modules if m.match is False]
    notes: list[str] = []
    if active is not None:
        notes.append(f"busy: {active.describe()}" + (f" phase {active.progress.phase}" if active.progress and
                                                      active.progress.phase else ""))
    if live is not None and live.identity is not None:
        notes.append(f"IDN {live.identity.model} {live.identity.serial}")
    if mismatched:
        notes.append(f"modules differ from the station profile in slots {mismatched} (runs are blocked by R-INV-01)")
    if live is not None and live.interlock_open:
        notes.append("interlock open (outputs limited to 42 V)" if backend == "sim"
                     else "STB bit 3: a >42 V request was refused with the interlock open")
    if live is not None and live.errors:
        notes.append(f"{len(live.errors)} instrument error(s) drained")
    corrections, correction_notes = correction_status(bundle, live, svc.executor.now())
    notes += correction_notes
    library = live.wgfmu_library if live is not None else None
    if library is not None and any(m.type == "WGFMU" for m in bundle.station.modules):  # visa (WP10.2)
        notes.append(f"WGFMU library {library.machine} {library.file_version or ''} loadable".replace("  ", " ")
                     if library.loadable else f"WGFMU library not loadable: {library.message}")
    head = (f"SIMULATED station (scenario {bundle.settings.sim.scenario})" if backend == "sim"
            else f"hardware station {bundle.settings.visa.resource}")
    status: ResultStatus = "ok"
    code: ErrorCode | None = None
    next_steps = ["list_recipes, then validate_plan with a pin map and a DUT profile"]
    if fault is not None:
        status, code = "fault", "fault_latched"
        notes.append(f"FAULT LATCHED: {fault.reason}")
        next_steps = [("do not measure: call safe_shutdown and load skill b1500-debug; only a human clears the "
                      "fault (b1500 fault clear)")]
    elif active is not None:
        status, code = "busy", "instrument_busy"
        next_steps = [(f"get_run({active.run_id}, include=[progress]) follows the run; safe_shutdown cancels it; "
                       "live fields are from the last snapshot")]
    elif live_code is not None:
        status, code = status_for(live_code), live_code
        notes.append(f"live state unavailable: {live_error}")
        next_steps = (["another process holds the instrument; retry later"] if live_code == "instrument_busy"
                      else ["call safe_shutdown and load skill b1500-debug"])
    if mismatched and status == "ok":
        next_steps = ["ask the human to check the installed modules against config/local/station.yaml"]
    return StationStatus(
        ok=status == "ok", status=status, error_code=code, **svc._envelope(backend),
        message=clip(f"{head}: " + ("; ".join(notes) if notes else "no live state read")),
        next_steps=next_steps,
        resource=session.transport.resource,
        sim_scenario=bundle.settings.sim.scenario if backend == "sim" else None,
        identity=live.identity.raw.strip() if live is not None and live.identity is not None else None,
        modules=modules, interlock_open=live.interlock_open if live is not None else None,
        interlock=interlock_label(backend, bundle.station, live),
        instrument_errors=list(live.errors) if live is not None else [],
        outputs_on=sorted(ch for ch, out in live.outputs.items() if out.output_on) if live is not None else [],
        live=source, live_error=clip(live_error, 300) if live_error else None,
        fault=fault, inflight_marker=session.inflight() is not None, lock_holder=session.lock.holder(),
        config=config_status(bundle.report()), limits=limits_status(bundle),
        pin_maps={name: pm.certainty for name, pm in sorted(bundle.pin_maps.items())},
        dut_profiles={name: d.device_type for name, d in sorted(bundle.dut_profiles.items())},
        active_run=active_run_status(active) if active is not None else None, corrections=corrections,
    )
