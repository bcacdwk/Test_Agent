"""C-only fake measurement compositions; real execution requires an outer transaction."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from fastmcp import FastMCP

from b1500_test_agent.schemas import c_flow as schema

from . import c_atoms


@dataclass
class _Step:
    """One fixed catalog step; atom names are never supplied by the caller."""

    atom: str
    inputs: dict
    phase: str = "configure"


def _step(atom: str, phase: str = "configure", **inputs: object) -> _Step:
    return _Step("C_atom_" + atom, dict(inputs), phase)


_BASE_PRECONDITIONS = [
    "Outer transaction: connected session and verified module/channel map.",
    "Outer transaction: DUT/pin map, voltage/current/compliance limits and interlock validated.",
    "Outer transaction: required human approval and output/routing readiness established.",
    "Outer transaction: cleanup installed before any source/update/signal operation.",
]

_GAPS = {
    "synchronous": "Synchronous source atom omits independent compliance and source range.",
    "multi_channel_sweep": "WNX atom omits per-channel trajectories, ranges and compliance.",
    "pulse_sweep": "PWV/PWI atom omits base level, compliance and source range.",
    "pulsed_bias": "Combined sweep/bias atom omits independent channel compliance.",
    "multi_channel_pulse": "MCP atom omits per-channel source/base/pulse/compliance settings.",
    "quasi": "BD atom omits compliance and complete measurement configuration.",
    "sampling": "Sampling atom omits explicit MI/MV base, bias and compliance settings.",
    "monitor": "DSMPL atom lacks a dedicated execution/completion contract; no MM is invented.",
    "search": "Search atom omits source/sense functions, start, step, tolerance and compliance.",
}


def _payload(result: dict) -> dict:
    """Current C atoms store operation fields inside parameters."""
    parameters = result.get("parameters", {})
    return {**result, **parameters} if isinstance(parameters, dict) else result


def _failed(result: dict) -> bool:
    payload = _payload(result)
    return (
        any(result.get(key) is False or payload.get(key) is False for key in ("ok", "passed"))
        or payload.get("result_code", 0) not in (0, "0")
        or payload.get("status") in {"failed", "error", "timeout", "aborted"}
    )


def _compose(
    name: str,
    request: schema.FlowModel,
    steps: list[_Step],
    purpose: str,
    *,
    gaps: list[str] | None = None,
) -> dict:
    """Run fake atoms serially, retaining failures and skipping dependent work."""
    _, _, category, object_name, subject = name.split("_", 4)
    records: list[dict] = []
    warnings = [
        "Fake composition only; no hardware measurement or safety validation was performed."
    ]
    prerequisites = list(_BASE_PRECONDITIONS)
    gaps = list(gaps or [])
    if object_name in {"smu", "cmu"}:
        prerequisites.append("Outer A layer: parser format, timestamp and output buffer prepared.")
    if object_name == "cmu" or subject == "qscv":
        prerequisites.append(
            "Fresh correction, validated SCUU/topology and leakage checks required."
        )
    if object_name == "wgfmu":
        prerequisites.append("WGFMU ranges/timing/memory and external DUT protection validated.")
        warnings.append(
            "WGFMU has no output current compliance; fake schemas do not certify safety."
        )
    if object_name == "spgu" or subject == "spgu_bias":
        prerequisites.append(
            "SPGU load, compensation, selector path and trigger topology validated."
        )
    if object_name == "easyexpert":
        prerequisites.append("Outer A layer: selected workspace/test and remote context verified.")
    failed = False
    completed = False
    ran = False
    unexpected_hardware = False
    all_fake = True
    for step in steps:
        reason = None
        if failed:
            reason = "Earlier atom failed; outer transaction must handle recovery."
        elif gaps and step.phase in {"execute", "read"}:
            reason = "Execution/read blocked by incomplete atom contracts."
        elif step.phase == "read" and not completed:
            reason = "Completion unverified; outer A/ABC layer must wait/query before readout."
        record = {
            "atom": step.atom,
            "phase": step.phase,
            "inputs": step.inputs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if reason:
            records.append({**record, "status": "skipped", "reason": reason, "result": None})
            continue
        try:
            result = getattr(c_atoms, step.atom)(**step.inputs)
            if not isinstance(result, dict):
                raise TypeError("C atoms must return a dictionary.")
            unsafe_result = (
                result.get("fake") is not True or result.get("hardware_touched") is not False
            )
            unexpected_hardware |= result.get("hardware_touched") is True
            all_fake &= result.get("fake") is True
            failed = unsafe_result or _failed(result)
            records.append({**record, "status": "error" if failed else "ok", "result": result})
            if unsafe_result:
                warnings.append(
                    "Unexpected non-fake atom result; stopped. This runner cannot control hardware."
                )
            elif failed:
                warnings.append(f"{step.atom} reported failure; later work was skipped.")
            payload = _payload(result)
            for dependency in result.get("required_preconditions", []):
                if dependency not in prerequisites:
                    prerequisites.append(dependency)
            if step.phase == "execute":
                ran = True
                completed = not failed and (
                    payload.get("status") == "fake_complete"
                    or (
                        payload.get("status") is None
                        and any(key in payload for key in ("sample", "measurement"))
                    )
                )
        # Atom adapters may raise different exception types; retain the audit at this boundary.
        except Exception as exc:  # noqa: BLE001
            failed = True
            records.append(
                {
                    **record,
                    "status": "error",
                    "result": None,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            warnings.append(f"{step.atom} raised {type(exc).__name__}; later work was skipped.")
    called = [r["atom"] for r in records if r["status"] != "skipped"]
    prerequisites = [p for p in prerequisites if p not in called or not p.startswith("C_atom_")]
    if failed:
        state = "failed"
    elif gaps:
        state = "configuration_only"
    elif completed:
        state = "simulated_complete"
    else:
        state = "awaiting_completion" if ran else "configuration_only"
    warnings.extend(gaps)
    if state == "awaiting_completion":
        warnings.append(
            "Started/unknown completion is not completion; hand off to the outer A/ABC layer."
        )
    if object_name == "easyexpert":
        warnings.append("Result fetch remains A-class; no result data is collected by this flow.")
    outputs = [
        {
            "atom": r["atom"],
            "data": {
                key: value
                for key, value in _payload(r["result"]).items()
                if key in {"rows", "values", "sample", "measurement"}
            },
        }
        for r in records
        if r["status"] == "ok"
        and any(key in _payload(r["result"]) for key in ("rows", "values", "sample", "measurement"))
    ]
    return {
        "flow": name,
        "flow_class": "C",
        "category": category,
        "object": object_name,
        "subject": subject,
        "fake": all_fake and not unexpected_hardware,
        "hardware_touched": unexpected_hardware,
        "ok": not failed,
        "partial": failed or bool(gaps) or state != "simulated_complete",
        "destructive": bool(called),
        "consumptive": any(
            r["status"] != "skipped"
            and r["atom"]
            in {"C_atom_smu_read_measurement_data", "C_atom_cmu_read_measurement_data"}
            for r in records
        ),
        "execution_state": state,
        "measurement_completed": False,
        "simulation_completed": completed and not failed,
        "atoms_called": called,
        "atom_results": records,
        "inputs": request.model_dump(),
        "outputs": {"data": outputs, "synthetic": True},
        "warnings": warnings,
        "purpose": purpose,
        "required_preconditions": prerequisites,
        "contract_gaps": gaps,
        "cleanup": {
            "owner": "outer_ABC_transaction",
            "performed": False,
            "required": "Abort/zero/disable or endpoint-specific standby/disconnect; verify safety.",
        },
    }


def _channels(channels: list[int]) -> str:
    return ",".join(map(str, channels))


def _smu_setup(q: schema.SmuSetup, channels: list[int] | None = None) -> list[_Step]:
    return [_step("smu_configure_integration", **q.integration.model_dump())] + [
        _step("smu_set_measurement_ranging", channel=ch, **q.ranging.model_dump())
        for ch in (channels or [q.channel])
    ]


def _smu_read(q: schema.SmuSetup) -> list[_Step]:
    return (
        [
            _step(
                "smu_read_measurement_data",
                "read",
                max_items=q.run.max_items,
                format_hint=q.run.format_hint,
            )
        ]
        if q.run.collect
        else []
    )


def _force(q: schema.SmuSpot) -> _Step:
    shared = {
        "channel": q.channel,
        "range_mode": q.source_range_mode,
        "comp_polarity": q.comp_polarity,
    }
    if q.source == "voltage":
        return _step(
            "smu_force_voltage",
            voltage_v=q.level,
            compliance_a=q.compliance,
            irange=q.irange,
            **shared,
        )
    return _step("smu_force_current", current_a=q.level, compliance_v=q.compliance, **shared)


def _sweep_setup(
    q: schema.SmuSweep, mode: int = 2, channels: list[int] | None = None
) -> list[_Step]:
    return _smu_setup(q, channels) + [
        _step("smu_set_measurement_mode", mode=mode, channels=_channels(channels or [q.channel])),
        _step("smu_configure_sweep_timing", **q.timing.model_dump()),
        _step("smu_configure_sweep_abort", abort_mode=q.abort_mode, post_output=q.post_output),
        _step(
            "smu_configure_staircase_sweep",
            **q.model_dump(
                include={
                    "channel",
                    "source",
                    "start",
                    "stop",
                    "steps",
                    "compliance",
                    "sweep_type",
                    "comp_polarity",
                }
            ),
        ),
    ]


def _smu_execute_read(q: schema.SmuSetup, operation: str, atom: str = "smu_execute") -> list[_Step]:
    args = {"timeout_s": q.run.timeout_s}
    if atom == "smu_execute":
        args["operation"] = operation
    return [_step(atom, "execute", **args)] + _smu_read(q)


def C_flow_spot_smu_iv(request: schema.SmuSpot | None = None) -> dict:
    """Compose MM1, source with compliance, execute and fake decoded readout."""
    q = schema.SmuSpot.model_validate(request or {})
    steps = _smu_setup(q) + [
        _step("smu_set_measurement_mode", mode=1, channels=str(q.channel)),
        _force(q),
    ]
    return _compose(
        "C_flow_spot_smu_iv",
        q,
        steps + _smu_execute_read(q, "spot_iv"),
        "Single-channel voltage/current source and normal spot acquisition.",
    )


def C_flow_spot_smu_high_speed(request: schema.SmuHighSpeed | None = None) -> dict:
    """Compose high-speed source/read without MM or XE."""
    q = schema.SmuHighSpeed.model_validate(request or {})
    measurement = {"current": "current", "voltage": "voltage", "iv": "current_voltage"}[
        q.measure_type
    ]
    steps = _smu_setup(q) + [
        _step("smu_configure_high_speed_spot", measurement=measurement),
        _force(q),
        _step(
            "smu_measure_high_speed_spot",
            "execute",
            channel=q.channel,
            measure_type=q.measure_type,
            timestamp=q.timestamp,
        ),
    ]
    return _compose(
        "C_flow_spot_smu_high_speed", q, steps, "High-speed spot with an inline synthetic sample."
    )


def C_flow_spot_wgfmu_dc(request: schema.WgfmuDc | None = None) -> dict:
    """Compose DC-mode force/measure and optional averaged readback."""
    q = schema.WgfmuDc.model_validate(request or {})
    steps = [
        _step("wgfmu_set_operation_mode", channel_id=q.channel_id, mode="dc"),
        _step(
            "wgfmu_configure_force_measure_ranges",
            channel_id=q.channel_id,
            force_range=q.force_range,
            measure_range=q.measure_range,
        ),
        _step("wgfmu_set_measure_mode", channel_id=q.channel_id, mode="current"),
        _step(
            "wgfmu_dc_force_measure",
            "execute",
            channel_id=q.channel_id,
            voltage_v=q.voltage_v,
            measure_range=q.measure_range,
        ),
    ]
    if q.averaged:
        steps.append(
            _step(
                "wgfmu_dc_measure_averaged",
                "read",
                channel_id=q.channel_id,
                averaging_count=q.averaging_count,
                points=q.points,
                interval_ticks=q.interval_ticks,
            )
        )
    return _compose("C_flow_spot_wgfmu_dc", q, steps, "DC force/measure with optional averaging.")


def C_flow_sweep_smu_staircase(request: schema.SmuSweep | None = None) -> dict:
    """Compose primary staircase source, timing, execute and fake readout."""
    q = schema.SmuSweep.model_validate(request or {})
    return _compose(
        "C_flow_sweep_smu_staircase",
        q,
        _sweep_setup(q) + _smu_execute_read(q, "staircase"),
        "Primary staircase IV sweep.",
    )


def C_flow_sweep_smu_synchronous(request: schema.SynchronousSweep | None = None) -> dict:
    """Compose paired trajectories; block execution until secondary compliance exists."""
    q = schema.SynchronousSweep.model_validate(request or {})
    steps = _sweep_setup(q, channels=[q.channel, q.secondary_channel]) + [
        _step(
            "smu_configure_synchronous_sweep_source",
            channel=q.secondary_channel,
            source=q.secondary_source,
            start=q.secondary_start,
            stop=q.secondary_stop,
        )
    ]
    return _compose(
        "C_flow_sweep_smu_synchronous",
        q,
        steps + _smu_execute_read(q, "synchronous"),
        "Primary and synchronous source trajectories.",
        gaps=[_GAPS["synchronous"]],
    )


def C_flow_sweep_smu_multi_channel(request: schema.MultiSweep | None = None) -> dict:
    """Compose MM16/WNX configuration and expose missing per-channel source contracts."""
    q = schema.MultiSweep.model_validate(request or {})
    steps = _sweep_setup(q, mode=16, channels=q.channels) + [
        _step(
            "smu_configure_multi_sweep",
            channels=_channels(q.channels),
            primary_channel=q.channel,
            steps=q.steps,
        )
    ]
    return _compose(
        "C_flow_sweep_smu_multi_channel",
        q,
        steps + _smu_execute_read(q, "multi_sweep"),
        "Multi-channel sweep configuration.",
        gaps=[_GAPS["multi_channel_sweep"]],
    )


def C_flow_sweep_smu_qscv(request: schema.Qscv | None = None) -> dict:
    """Compose SMU QSCV; correction/leakage approval remains external."""
    q = schema.Qscv.model_validate(request or {})
    steps = _smu_setup(q) + [
        _step("smu_set_measurement_mode", mode=13, channels=str(q.channel)),
        _step("smu_configure_qscv", **q.model_dump(exclude={"integration", "ranging", "run"})),
    ]
    return _compose(
        "C_flow_sweep_smu_qscv",
        q,
        steps + _smu_execute_read(q, "qscv", "smu_execute_qscv"),
        "SMU quasi-static capacitance sweep after external correction/leakage validation.",
    )


def C_flow_pulse_smu_spot(request: schema.SmuPulse | None = None) -> dict:
    """Compose PT before PV/PI, then fake pulsed-spot execution and readout."""
    q = schema.SmuPulse.model_validate(request or {})
    steps = _smu_setup(q) + [
        _step("smu_set_measurement_mode", mode=3, channels=str(q.channel)),
        _step("smu_configure_pulse_timing", **q.timing.model_dump()),
        _step(
            "smu_configure_pulsed_spot_source",
            **q.model_dump(include={"channel", "source", "base", "pulse", "compliance"}),
        ),
    ]
    return _compose(
        "C_flow_pulse_smu_spot",
        q,
        steps + _smu_execute_read(q, "pulsed_spot", "smu_execute_pulsed_spot"),
        "Single-channel parameterized pulsed spot measurement.",
    )


def C_flow_pulse_smu_sweep(request: schema.SmuPulseSweep | None = None) -> dict:
    """Compose PT/PWV/PWI; block execution for missing base/compliance fields."""
    q = schema.SmuPulseSweep.model_validate(request or {})
    steps = _smu_setup(q) + [
        _step("smu_set_measurement_mode", mode=4, channels=str(q.channel)),
        _step("smu_configure_pulse_timing", **q.timing.model_dump()),
        _step(
            "smu_configure_pulsed_sweep",
            **q.model_dump(include={"channel", "source", "start", "stop", "steps"}),
        ),
    ]
    return _compose(
        "C_flow_pulse_smu_sweep",
        q,
        steps + _smu_execute_read(q, "pulsed_sweep", "smu_execute_pulsed_sweep"),
        "Parameterized pulsed sweep configuration.",
        gaps=[_GAPS["pulse_sweep"]],
    )


def C_flow_pulse_smu_staircase_pulsed_bias(request: schema.PulsedBias | None = None) -> dict:
    """Compose MM5 and pulsed bias; expose missing independent channel compliance."""
    q = schema.PulsedBias.model_validate(request or {})
    steps = _smu_setup(q, [q.channel, q.bias_channel]) + [
        _step("smu_set_measurement_mode", mode=5, channels=_channels([q.channel, q.bias_channel])),
        _step("smu_configure_pulse_timing", **q.timing.model_dump()),
        _step(
            "smu_configure_staircase_sweep_pulsed_bias",
            sweep_channel=q.channel,
            bias_channel=q.bias_channel,
            sweep_source=q.source,
            start=q.start,
            stop=q.stop,
            steps=q.steps,
            bias_base=q.bias_base,
            bias_pulse=q.bias_pulse,
        ),
    ]
    return _compose(
        "C_flow_pulse_smu_staircase_pulsed_bias",
        q,
        steps + _smu_execute_read(q, "staircase_pulsed_bias"),
        "Staircase sweep with a distinct pulsed bias channel.",
        gaps=[_GAPS["pulsed_bias"]],
    )


def C_flow_pulse_smu_multi_channel(request: schema.MultiPulse | None = None) -> dict:
    """Compose MM27/28 and MCP setup; keep incomplete per-channel sourcing explicit."""
    q = schema.MultiPulse.model_validate(request or {})
    steps = [
        _step(
            "smu_set_measurement_mode",
            mode=27 if q.mode == "pulsed_spot" else 28,
            channels=_channels(q.channels),
        ),
        _step(
            "smu_configure_multi_pulsed",
            channels=_channels(q.channels),
            mode=q.mode,
            pulse_width_s=q.pulse_width_s,
        ),
        _step("smu_execute", "execute", operation="multi_" + q.mode, timeout_s=q.run.timeout_s),
    ]
    if q.run.collect:
        steps.append(
            _step(
                "smu_read_measurement_data",
                "read",
                max_items=q.run.max_items,
                format_hint=q.run.format_hint,
            )
        )
    return _compose(
        "C_flow_pulse_smu_multi_channel",
        q,
        steps,
        "Multi-channel pulsed spot/sweep configuration.",
        gaps=[_GAPS["multi_channel_pulse"]],
    )


def C_flow_pulse_smu_quasi(request: schema.QuasiPulse | None = None) -> dict:
    """Compose MM9/BD geometry; block incomplete source execution."""
    q = schema.QuasiPulse.model_validate(request or {})
    steps = _smu_setup(q) + [
        _step("smu_set_measurement_mode", mode=9, channels=str(q.channel)),
        _step(
            "smu_configure_quasi_pulse",
            channel=q.channel,
            base_v=q.base_v,
            peak_v=q.peak_v,
            width_s=q.width_s,
        ),
    ]
    return _compose(
        "C_flow_pulse_smu_quasi",
        q,
        steps + _smu_execute_read(q, "quasi_pulse"),
        "Quasi-pulsed spot configuration.",
        gaps=[_GAPS["quasi"]],
    )


def _sampling_setup(q: schema.SmuSampling) -> list[_Step]:
    return _smu_setup(q, q.channels) + [
        _step("smu_set_measurement_mode", mode=10, channels=_channels(q.channels)),
        _step(
            "smu_configure_sampling",
            channels=_channels(q.channels),
            source_channel=q.channel,
            interval_s=q.interval_s,
            samples=q.samples,
            mode=q.mode,
            hold_base_s=q.hold_base_s,
            post_output=q.post_output,
        ),
    ]


def C_flow_sampling_smu_iv_time(request: schema.SmuSampling | None = None) -> dict:
    """Compose time-sampling setup; explicit MI/MV source settings are still missing."""
    q = schema.SmuSampling.model_validate(request or {})
    return _compose(
        "C_flow_sampling_smu_iv_time",
        q,
        _sampling_setup(q) + _smu_execute_read(q, "sampling", "smu_execute_sampling"),
        "SMU time-sampling configuration.",
        gaps=[_GAPS["sampling"]],
    )


def C_flow_sampling_smu_signal_monitor(request: schema.SignalMonitor | None = None) -> dict:
    """Compose DSMPL acquisition settings without inventing a mode or execute atom."""
    q = schema.SignalMonitor.model_validate(request or {})
    steps = _smu_setup(q, q.channels) + [
        _step(
            "smu_configure_signal_monitor",
            channels=_channels(q.channels),
            interval_s=q.interval_s,
            samples=q.samples,
        )
    ]
    return _compose(
        "C_flow_sampling_smu_signal_monitor",
        q,
        steps,
        "Signal-monitor acquisition configuration only.",
        gaps=[_GAPS["monitor"]],
    )


def C_flow_sampling_smu_spgu_bias(request: schema.SpguSampling | None = None) -> dict:
    """Compose SMU sampling plus SPGU bias on FLEX; routing remains external."""
    q = schema.SpguSampling.model_validate(request or {})
    steps = _sampling_setup(q) + [
        _step(
            "spgu_configure_sampling_pulse",
            channel=q.spgu_channel,
            base_v=q.base_v,
            pulse_v=q.pulse_v,
            width_s=q.width_s,
        )
    ]
    return _compose(
        "C_flow_sampling_smu_spgu_bias",
        q,
        steps + _smu_execute_read(q, "spgu_sampling", "smu_execute_sampling"),
        "SMU sampling with SPGU pulse bias.",
        gaps=[_GAPS["sampling"]],
    )


def C_flow_search_smu_target(request: schema.Search | None = None) -> dict:
    """Compose linear/binary search setup and report missing search-source contracts."""
    q = schema.Search.model_validate(request or {})
    steps = _smu_setup(q) + [
        _step(
            "smu_set_measurement_mode",
            mode=14 if q.search_type == "linear" else 15,
            channels=str(q.channel),
        ),
        _step(
            "smu_configure_search",
            channel=q.channel,
            search_type=q.search_type,
            target=q.target,
            limit=q.limit,
        ),
    ]
    return _compose(
        "C_flow_search_smu_target",
        q,
        steps + _smu_execute_read(q, q.search_type + "_search"),
        "Instrument linear/binary target-search configuration.",
        gaps=[_GAPS["search"]],
    )


def _cmu_setup(q: schema.CmuSetup) -> list[_Step]:
    return [
        _step("cmu_set_impedance_model", model=q.model, channel=q.channel),
        _step(
            "cmu_configure_signal",
            channel=q.channel,
            frequency_hz=q.frequency_hz,
            ac_level_v=q.ac_level_v,
            dc_bias_v=q.dc_bias_v,
        ),
        _step(
            "cmu_set_ranging_integration",
            channel=q.channel,
            range_mode=q.range_mode,
            integration_time=q.integration_time,
            range_value=q.range_value,
        ),
        _step("cmu_set_monitor_output", channel=q.channel, enabled=q.monitor),
    ]


def _cmu_tail(q: schema.CmuSetup, execute: str) -> list[_Step]:
    steps = [_step("cmu_execute_" + execute, "execute", timeout_s=q.run.timeout_s)]
    if q.run.collect:
        steps.append(
            _step(
                "cmu_read_measurement_data",
                "read",
                max_items=q.run.max_items,
                format_hint=q.run.format_hint,
            )
        )
    return steps


def C_flow_spot_cmu_impedance(request: schema.CmuSetup | None = None) -> dict:
    """Compose IMP/signal/ranging/monitor and normal spot-C execution/readout."""
    q = schema.CmuSetup.model_validate(request or {})
    return _compose(
        "C_flow_spot_cmu_impedance",
        q,
        _cmu_setup(q) + _cmu_tail(q, "spot_c"),
        "Normal spot capacitance/impedance with optional monitor columns.",
    )


def C_flow_spot_cmu_high_speed(request: schema.CmuSetup | None = None) -> dict:
    """Compose direct TC/TTC spot readout without MM/XE."""
    q = schema.CmuSetup.model_validate(request or {})
    steps = _cmu_setup(q) + [
        _step("cmu_measure_high_speed_spot", "execute", channel=q.channel, timestamp=True)
    ]
    return _compose(
        "C_flow_spot_cmu_high_speed", q, steps, "High-speed CMU spot with inline synthetic data."
    )


def _cmu_sweep(q: schema.CmuSweep, subject: str) -> dict:
    configure, execute = {
        "cv": ("cv_dc_sweep", "cv_dc_sweep"),
        "cf": ("cf_sweep", "cf_sweep"),
        "ac_level": ("ac_level_sweep", "ac_level_sweep"),
    }[subject]
    if subject in {"cf", "ac_level"} and min(q.start, q.stop) <= 0:
        raise ValueError("Frequency and AC amplitude sweep endpoints must be positive.")
    args = q.model_dump(
        include={"steps", "hold_s", "delay_s", "step_delay_s", "measure_delay_s", "abort_mode"}
    )
    unit = "hz" if subject == "cf" else "v"
    args.update({"start_" + unit: q.start, "stop_" + unit: q.stop})
    steps = _cmu_setup(q) + [_step("cmu_configure_" + configure, **args)] + _cmu_tail(q, execute)
    return _compose(
        "C_flow_sweep_cmu_" + subject,
        q,
        steps,
        "CMU " + subject + " sweep with mode-specific timing.",
    )


def C_flow_sweep_cmu_cv(request: schema.CmuSweep | None = None) -> dict:
    """Compose DC-bias C-V sweep using CMU-specific timing and abort settings."""
    return _cmu_sweep(schema.CmuSweep.model_validate(request or {"start": -1.0, "stop": 1.0}), "cv")


def C_flow_sweep_cmu_cf(request: schema.CmuSweep | None = None) -> dict:
    """Compose frequency sweep with endpoints in Hz."""
    return _cmu_sweep(schema.CmuSweep.model_validate(request or {"start": 1e3, "stop": 1e6}), "cf")


def C_flow_sweep_cmu_ac_level(request: schema.CmuSweep | None = None) -> dict:
    """Compose AC-level sweep with endpoints in V."""
    return _cmu_sweep(
        schema.CmuSweep.model_validate(request or {"start": 0.01, "stop": 0.1}), "ac_level"
    )


def C_flow_pulse_cmu_spot(request: schema.CmuPulse | None = None) -> dict:
    """Compose CMU-specific PTDCV/PDCV pulsed spot acquisition."""
    q = schema.CmuPulse.model_validate(request or {})
    steps = (
        _cmu_setup(q)
        + [
            _step(
                "cmu_configure_pulsed_spot_c",
                pulse_base_v=q.base_v,
                pulse_bias_v=q.bias_v,
                pulse_width_s=q.width_s,
                pulse_period_s=q.period_s,
            )
        ]
        + _cmu_tail(q, "pulsed_spot_c")
    )
    return _compose("C_flow_pulse_cmu_spot", q, steps, "Pulsed spot capacitance/impedance.")


def C_flow_pulse_cmu_cv(request: schema.CmuPulseSweep | None = None) -> dict:
    """Compose CMU-specific pulsed DC-bias sweep and fake readout."""
    q = schema.CmuPulseSweep.model_validate(request or {})
    steps = (
        _cmu_setup(q)
        + [
            _step(
                "cmu_configure_pulsed_cv_sweep",
                start_v=q.start_v,
                stop_v=q.stop_v,
                steps=q.steps,
                pulse_width_s=q.width_s,
                pulse_period_s=q.period_s,
            )
        ]
        + _cmu_tail(q, "pulsed_cv_sweep")
    )
    return _compose("C_flow_pulse_cmu_cv", q, steps, "Pulsed capacitance-voltage sweep.")


def C_flow_sampling_cmu_ct(request: schema.CmuSampling | None = None) -> dict:
    """Compose MDCV/MTDCV capacitance-time sampling and fake readout."""
    q = schema.CmuSampling.model_validate(request or {})
    steps = (
        _cmu_setup(q)
        + [
            _step(
                "cmu_configure_ct_sampling",
                interval_s=q.interval_s,
                samples=q.samples,
                dc_bias_v=q.dc_bias_v,
            )
        ]
        + _cmu_tail(q, "ct_sampling")
    )
    return _compose(
        "C_flow_sampling_cmu_ct", q, steps, "Capacitance-time sampling at declared DC bias."
    )


def C_flow_waveform_wgfmu_acquire(request: schema.WgfmuWaveform) -> dict:
    """Build all channel patterns/events, update once, execute once, then collect."""
    q = schema.WgfmuWaveform.model_validate(request)
    steps = []
    for ch in q.channels:
        steps.extend(
            [
                _step("wgfmu_set_operation_mode", channel_id=ch.channel_id, mode="fast_iv"),
                _step(
                    "wgfmu_configure_force_measure_ranges",
                    channel_id=ch.channel_id,
                    force_range=ch.force_range,
                    measure_range=ch.measure_range,
                ),
                _step("wgfmu_set_measure_mode", channel_id=ch.channel_id, mode=ch.measure_mode),
            ]
        )
        if ch.measure_mode == "voltage":
            steps.append(
                _step(
                    "wgfmu_set_measure_voltage_range",
                    channel_id=ch.channel_id,
                    range_v=ch.voltage_range,
                )
            )
        steps.extend(
            [
                _step("wgfmu_set_measure_enabled", channel_id=ch.channel_id, enabled=True),
                _step(
                    "wgfmu_create_pattern",
                    pattern=ch.pattern,
                    initial_voltage_v=ch.initial_voltage_v,
                    initial_time_s=0.0,
                ),
            ]
        )
        steps.extend(
            _step("wgfmu_add_vectors", pattern=ch.pattern, count=1, **v.model_dump())
            for v in ch.vectors
        )
        steps.extend(
            _step(
                "wgfmu_set_measure_event",
                channel_id=ch.channel_id,
                pattern=ch.pattern,
                **e.model_dump(),
            )
            for e in ch.events
        )
        steps.append(
            _step(
                "wgfmu_add_sequence",
                channel_id=ch.channel_id,
                pattern=ch.pattern,
                repeat_count=ch.repeat_count,
            )
        )
    steps.extend(
        [_step("wgfmu_update"), _step("wgfmu_execute", "execute", timeout_s=q.run.timeout_s)]
    )
    if q.run.collect:
        steps.extend(
            _step(
                "wgfmu_read_measurement_values",
                "read",
                channel_id=ch.channel_id,
                max_points=q.run.max_items,
            )
            for ch in q.channels
        )
    return _compose(
        "C_flow_waveform_wgfmu_acquire",
        q,
        steps,
        "Bounded multi-channel waveform and measurement-event acquisition.",
    )


def C_flow_pulse_spgu_train(request: schema.SpguPulse | None = None) -> dict:
    """Configure and start a finite SPGU train; completion belongs to the outer layer."""
    q = schema.SpguPulse.model_validate(request or {})
    steps = [
        _step("spgu_set_operation_mode", channel=q.channel, mode="PG"),
        _step("spgu_set_load_impedance", channel=q.channel, load_ohm=q.load_ohm),
        _step(
            "spgu_configure_pg_pulse",
            **q.model_dump(
                include={
                    "channel",
                    "pulse_mode",
                    "source_number",
                    "leading_s",
                    "trailing_s",
                    "base_v",
                    "peak_v",
                    "peak2_v",
                }
            ),
            **q.timing.model_dump(),
        ),
        _step("spgu_update_output", channel=q.channel),
        _step(
            "spgu_start_output", "execute", channel=q.channel, count=q.count, timeout_s=q.timeout_s
        ),
    ]
    return _compose(
        "C_flow_pulse_spgu_train",
        q,
        steps,
        "Start a bounded pulse train; source-only, no acquisition.",
    )


def C_flow_waveform_spgu_sequence(request: schema.SpguWaveform) -> dict:
    """Define ALWG levels/sequence and start bounded output without premature stop."""
    q = schema.SpguWaveform.model_validate(request)
    steps = [
        _step("spgu_set_operation_mode", channel=q.channel, mode="ALWG"),
        _step("spgu_set_load_impedance", channel=q.channel, load_ohm=q.load_ohm),
        _step(
            "spgu_create_alwg_pattern",
            **q.model_dump(
                include={"channel", "pattern", "initial_voltage_v", "period_s", "levels_v"}
            ),
        ),
        _step(
            "spgu_add_alwg_sequence",
            **q.model_dump(
                include={"channel", "pattern", "repeat_count", "loop_start", "loop_count"}
            ),
        ),
        _step("spgu_update_output", channel=q.channel),
        _step(
            "spgu_start_output", "execute", channel=q.channel, count=q.count, timeout_s=q.timeout_s
        ),
    ]
    return _compose(
        "C_flow_waveform_spgu_sequence", q, steps, "Start a bounded ALWG sequence; source-only."
    )


def C_flow_remote_easyexpert_selected_test(request: schema.RemoteRun | None = None) -> dict:
    """Execute already selected EasyEXPERT context; selection and fetch stay A."""
    q = schema.RemoteRun.model_validate(request or {})
    return _compose(
        "C_flow_remote_easyexpert_selected_test",
        q,
        [_step("easyexpert_run_selected_test", "execute", **q.model_dump())],
        "Execute the selected remote test.",
    )


def C_flow_remote_easyexpert_repeat(request: schema.RemoteRepeat | None = None) -> dict:
    """Invoke the bounded repeat atom once; do not loop or fetch results implicitly."""
    q = schema.RemoteRepeat.model_validate(request or {})
    return _compose(
        "C_flow_remote_easyexpert_repeat",
        q,
        [_step("easyexpert_repeat_run_selected_test", "execute", **q.model_dump())],
        "Repeat the selected remote test.",
    )


def C_flow_remote_easyexpert_quick_sequence(request: schema.RemoteSequence | None = None) -> dict:
    """Execute an existing Quick Test sequence without editing software context."""
    q = schema.RemoteSequence.model_validate(request or {})
    return _compose(
        "C_flow_remote_easyexpert_quick_sequence",
        q,
        [_step("easyexpert_run_quick_test_sequence", "execute", **q.model_dump())],
        "Run an existing remote Quick Test sequence.",
    )


C_FLOW_FUNCTIONS: list[Callable[..., dict]] = [
    C_flow_spot_smu_iv,
    C_flow_spot_smu_high_speed,
    C_flow_spot_wgfmu_dc,
    C_flow_spot_cmu_impedance,
    C_flow_spot_cmu_high_speed,
    C_flow_sweep_smu_staircase,
    C_flow_sweep_smu_synchronous,
    C_flow_sweep_smu_multi_channel,
    C_flow_sweep_smu_qscv,
    C_flow_sweep_cmu_cv,
    C_flow_sweep_cmu_cf,
    C_flow_sweep_cmu_ac_level,
    C_flow_pulse_smu_spot,
    C_flow_pulse_smu_sweep,
    C_flow_pulse_smu_staircase_pulsed_bias,
    C_flow_pulse_smu_multi_channel,
    C_flow_pulse_smu_quasi,
    C_flow_pulse_spgu_train,
    C_flow_pulse_cmu_spot,
    C_flow_pulse_cmu_cv,
    C_flow_waveform_wgfmu_acquire,
    C_flow_waveform_spgu_sequence,
    C_flow_sampling_smu_iv_time,
    C_flow_sampling_smu_signal_monitor,
    C_flow_sampling_smu_spgu_bias,
    C_flow_sampling_cmu_ct,
    C_flow_search_smu_target,
    C_flow_remote_easyexpert_selected_test,
    C_flow_remote_easyexpert_repeat,
    C_flow_remote_easyexpert_quick_sequence,
]


def register_c_flows(mcp: FastMCP) -> None:
    """Register all C_flow_* tools with typed request schemas."""
    for tool in C_FLOW_FUNCTIONS:
        mcp.tool(tool)
