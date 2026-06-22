"""AB-class fake MCP workflow tools.

AB flows compose existing A_flow/B_flow tools plus narrow A/B atoms into
operator-facing observe -> act -> verify workflows. They remain fake and
orchestration-only: no real hardware I/O is performed here.
"""

from collections.abc import Callable

from fastmcp import FastMCP

from .a_atoms import (
    A_atom_easyexpert_wait_opc,
    A_atom_flex_identify,
    A_atom_flex_list_modules,
    A_atom_flex_query_settings,
)
from .a_flows import (
    A_flow_discover_easyexpert_remote,
    A_flow_discover_flex_session,
    A_flow_discover_wgfmu_session,
    A_flow_drain_easyexpert_errors,
    A_flow_drain_flex_errors,
    A_flow_drain_wgfmu_errors,
    A_flow_collect_flex_output_buffer,
    A_flow_prepare_flex_output_buffer,
    A_flow_prepare_wgfmu_logging,
    A_flow_select_easyexpert_workspace,
    A_flow_snapshot_easyexpert_context,
    A_flow_snapshot_flex_status,
    A_flow_snapshot_wgfmu_diagnostics,
    A_flow_teardown_easyexpert_workspace,
    A_flow_teardown_flex_session,
    A_flow_teardown_wgfmu_session,
)
from .b_atoms import B_atom_output_easyexpert_set_standby
from .b_flows import (
    B_flow_baseline_b1500_known_state,
    B_flow_baseline_smu_housekeeping,
    B_flow_baseline_wgfmu_known_state,
    B_flow_correction_cmu_open_short_load,
    B_flow_correction_cmu_phase_compensation,
    B_flow_correction_easyexpert_zero_cancel,
    B_flow_correction_qscv_offset_cancel,
    B_flow_emergency_b1500_abort_zero,
    B_flow_emergency_easyexpert_abort_standby,
    B_flow_emergency_wgfmu_abort_disconnect,
    B_flow_maintenance_b1500_self_test_calibration,
    B_flow_maintenance_wgfmu_self_test_calibration,
    B_flow_preflight_b1500_gate,
    B_flow_preparation_asu_low_current_path,
    B_flow_preparation_scuu_signal_path,
    B_flow_safe_state_b1500_zero_disable,
)

ChildCallable = Callable[..., dict]


def _call_step(
    phases: dict[str, list[dict]],
    child_results: list[dict],
    phase: str,
    command: ChildCallable,
    /,
    **inputs: object,
) -> dict:
    """Call one child flow/atom and record the exact orchestration step."""
    result = command(**inputs)
    record = {
        "phase": phase,
        "name": command.__name__,
        "inputs": dict(inputs),
        "status": "ok",
        "result": result,
    }
    phases[phase].append(record)
    child_results.append(record)
    return result


def _skip_step(
    phases: dict[str, list[dict]],
    child_results: list[dict],
    phase: str,
    name: str,
    reason: str,
    *,
    optional: bool,
    **inputs: object,
) -> None:
    """Record an intentionally skipped child command."""
    record = {
        "phase": phase,
        "name": name,
        "inputs": dict(inputs),
        "status": "skipped",
        "reason": reason,
        "optional": optional,
        "result": None,
    }
    phases[phase].append(record)
    child_results.append(record)


def _flow_names(child_results: list[dict]) -> list[str]:
    """Return invoked child flow names in AB execution order."""
    return [
        record["name"]
        for record in child_results
        if record["status"] == "ok" and str(record["name"]).startswith(("A_flow_", "B_flow_"))
    ]


def _atom_names(child_results: list[dict]) -> list[str]:
    """Return direct and nested atom names in AB execution order."""
    names: list[str] = []
    for record in child_results:
        if record["status"] != "ok":
            continue
        name = str(record["name"])
        result = record["result"]
        if name.startswith(("A_atom_", "B_atom_")):
            atom_name = result.get("atom", name) if isinstance(result, dict) else name
            names.append(str(atom_name))
        elif isinstance(result, dict):
            names.extend(str(atom) for atom in result.get("atoms_called", []) or [])
    return names


def _truthy_child_flag(child_results: list[dict], flag: str) -> bool:
    """Aggregate boolean flags from called child result envelopes."""
    for record in child_results:
        result = record.get("result")
        if record.get("status") == "ok" and isinstance(result, dict) and bool(result.get(flag)):
            return True
    return False


def _collect_child_warnings(child_results: list[dict]) -> list[str]:
    """Flatten child warnings while preserving source names."""
    warnings: list[str] = []
    for record in child_results:
        result = record.get("result")
        if record.get("status") == "ok" and isinstance(result, dict):
            for warning in result.get("warnings", []) or []:
                warnings.append(f"{record['name']}: {warning}")
    return warnings


def _child_failed(child_results: list[dict]) -> bool:
    """Treat child ok=False as a failed AB phase."""
    for record in child_results:
        result = record.get("result")
        if record.get("status") == "ok" and isinstance(result, dict) and result.get("ok") is False:
            return True
    return False


def _required_skip(child_results: list[dict]) -> bool:
    """Return whether a required child command was skipped."""
    return any(
        record.get("status") == "skipped" and not bool(record.get("optional"))
        for record in child_results
    )


def _ack_missing_warning(flow: str, ack_label: str) -> str:
    """Describe an AB-level acknowledgement gate."""
    return f"{flow}: {ack_label}=False; required non-emergency act phase was skipped."


def _ab_response(
    flow: str,
    category: str,
    scope: str,
    outcome: str,
    phases: dict[str, list[dict]],
    child_results: list[dict],
    inputs: dict,
    outputs: dict | None = None,
    warnings: list[str] | None = None,
    *,
    operator_ack_required: bool = False,
    operator_ack_received: bool = False,
    fixture_sensitive: bool = False,
) -> dict:
    """Build the standard fake AB_flow response envelope."""
    all_warnings = list(warnings or []) + _collect_child_warnings(child_results)
    partial = (
        _required_skip(child_results)
        or _child_failed(child_results)
        or _truthy_child_flag(child_results, "partial")
    )
    return {
        "flow": flow,
        "flow_class": "AB",
        "category": category,
        "scope": scope,
        "outcome": outcome,
        "fake": True,
        "hardware_touched": False,
        "ok": not partial,
        "partial": partial,
        "destructive": _truthy_child_flag(child_results, "destructive"),
        "consumptive": _truthy_child_flag(child_results, "consumptive"),
        "fixture_sensitive": fixture_sensitive or _truthy_child_flag(child_results, "fixture_sensitive"),
        "operator_ack_required": operator_ack_required,
        "operator_ack_received": operator_ack_received,
        "phases": phases,
        "flows_called": _flow_names(child_results),
        "atoms_called": _atom_names(child_results),
        "child_results": child_results,
        "inputs": inputs,
        "outputs": dict(outputs or {}),
        "warnings": all_warnings,
        "audit": {
            "phase_order": ["observe", "act", "verify"],
            "child_count": len(child_results),
            "skipped_children": [
                record["name"] for record in child_results if record["status"] == "skipped"
            ],
            "consumptive_children": [
                record["name"]
                for record in child_results
                if record["status"] == "ok"
                and isinstance(record["result"], dict)
                and record["result"].get("consumptive")
            ],
        },
    }


def _new_phases() -> dict[str, list[dict]]:
    """Create an ordered AB phase container."""
    return {"observe": [], "act": [], "verify": []}


def AB_flow_startup_flex_safe_session(
    gpib_address: int = 17,
    gpib_board: int = 0,
    timeout_ms: int = 600_000,
    include_timestamp: bool = False,
    device_type: str = "unknown",
    pin_map_known: bool = False,
) -> dict:
    """Start a safe direct FLEX/B1500A session with preflight verification."""
    phases = _new_phases()
    child_results: list[dict] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_discover_flex_session,
        gpib_address=gpib_address,
        gpib_board=gpib_board,
        timeout_ms=timeout_ms,
    )
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_preflight_b1500_gate,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        "AB_flow_startup_flex_safe_session",
        "startup",
        "flex_session",
        "Direct FLEX session discovered, preflighted, and re-snapshotted.",
        phases,
        child_results,
        {
            "gpib_address": gpib_address,
            "gpib_board": gpib_board,
            "timeout_ms": timeout_ms,
            "include_timestamp": include_timestamp,
            "device_type": device_type,
            "pin_map_known": pin_map_known,
        },
    )


def AB_flow_startup_wgfmu_baseline_session(
    address: str = "GPIB0::17::INSTR",
    timeout_s: float = 100.0,
    set_warning_policy: bool = False,
    warnings_as_errors: bool = False,
) -> dict:
    """Open a WGFMU session, baseline it, and capture diagnostics."""
    phases = _new_phases()
    child_results: list[dict] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_discover_wgfmu_session,
        address=address,
        timeout_s=timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_baseline_wgfmu_known_state,
        set_warning_policy=set_warning_policy,
        warnings_as_errors=warnings_as_errors,
    )
    _call_step(phases, child_results, "verify", A_flow_snapshot_wgfmu_diagnostics)
    return _ab_response(
        "AB_flow_startup_wgfmu_baseline_session",
        "startup",
        "wgfmu_session",
        "WGFMU session discovered, initialized to baseline, and checked.",
        phases,
        child_results,
        {
            "address": address,
            "timeout_s": timeout_s,
            "set_warning_policy": set_warning_policy,
            "warnings_as_errors": warnings_as_errors,
        },
    )


def AB_flow_startup_easyexpert_workspace_standby(
    workspace: str = "default",
    timeout_s: float = 60.0,
    standby_enabled: bool = True,
) -> dict:
    """Open an EasyEXPERT workspace and set verified standby context."""
    phases = _new_phases()
    child_results: list[dict] = []
    _call_step(phases, child_results, "observe", A_flow_discover_easyexpert_remote)
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_select_easyexpert_workspace,
        workspace=workspace,
        timeout_s=timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_atom_output_easyexpert_set_standby,
        enabled=standby_enabled,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_atom_easyexpert_wait_opc,
        timeout_s=timeout_s,
    )
    _call_step(phases, child_results, "verify", A_flow_snapshot_easyexpert_context)
    return _ab_response(
        "AB_flow_startup_easyexpert_workspace_standby",
        "startup",
        "easyexpert_workspace",
        "EasyEXPERT remote workspace opened and placed in standby.",
        phases,
        child_results,
        {
            "workspace": workspace,
            "timeout_s": timeout_s,
            "standby_enabled": standby_enabled,
        },
    )


def AB_flow_shutdown_flex_safe_session(
    collect_existing_output: bool = False,
    collect_timeout_s: float = 60.0,
    max_items: int = 100,
    read_when_empty: bool = False,
    include_timestamp: bool = False,
    channels: str = "",
    confirm_timeout_s: float = 5.0,
    read_remaining_output: bool = False,
) -> dict:
    """Collect optional FLEX data, safe-state outputs, drain errors, and close."""
    phases = _new_phases()
    child_results: list[dict] = []
    if collect_existing_output:
        _call_step(
            phases,
            child_results,
            "observe",
            A_flow_collect_flex_output_buffer,
            timeout_s=collect_timeout_s,
            max_items=max_items,
            read_when_empty=read_when_empty,
        )
    else:
        _skip_step(
            phases,
            child_results,
            "observe",
            "A_flow_collect_flex_output_buffer",
            "collect_existing_output=False",
            optional=True,
            timeout_s=collect_timeout_s,
            max_items=max_items,
            read_when_empty=read_when_empty,
        )
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_safe_state_b1500_zero_disable,
        channels=channels,
        confirm_timeout_s=confirm_timeout_s,
    )
    _call_step(phases, child_results, "verify", A_flow_drain_flex_errors)
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_teardown_flex_session,
        read_remaining_output=read_remaining_output,
        max_items=max_items,
    )
    return _ab_response(
        "AB_flow_shutdown_flex_safe_session",
        "shutdown",
        "flex_session",
        "FLEX outputs safe-stated, errors drained, and direct session closed.",
        phases,
        child_results,
        {
            "collect_existing_output": collect_existing_output,
            "collect_timeout_s": collect_timeout_s,
            "max_items": max_items,
            "read_when_empty": read_when_empty,
            "include_timestamp": include_timestamp,
            "channels": channels,
            "confirm_timeout_s": confirm_timeout_s,
            "read_remaining_output": read_remaining_output,
        },
    )


def AB_flow_shutdown_wgfmu_safe_session(
    channel_ids: str = "501,502",
    max_errors: int = 20,
    export_setup: bool = False,
    file_name: str = "wgfmu_setup.csv",
    close_log: bool = True,
) -> dict:
    """Abort/disconnect WGFMU channels, drain errors, and close session/log."""
    phases = _new_phases()
    child_results: list[dict] = []
    _call_step(phases, child_results, "observe", A_flow_snapshot_wgfmu_diagnostics)
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_emergency_wgfmu_abort_disconnect,
        channel_ids=channel_ids,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_wgfmu_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_teardown_wgfmu_session,
        export_setup=export_setup,
        file_name=file_name,
        close_log=close_log,
    )
    return _ab_response(
        "AB_flow_shutdown_wgfmu_safe_session",
        "shutdown",
        "wgfmu_session",
        "WGFMU sequencer aborted, outputs disconnected, errors drained, and session closed.",
        phases,
        child_results,
        {
            "channel_ids": channel_ids,
            "max_errors": max_errors,
            "export_setup": export_setup,
            "file_name": file_name,
            "close_log": close_log,
        },
    )


def AB_flow_shutdown_easyexpert_workspace_standby(
    standby_enabled: bool = True,
    timeout_s: float = 60.0,
    max_errors: int = 20,
    force_clear: bool = False,
    ignore_no_workspace: bool = True,
) -> dict:
    """Abort EasyEXPERT activity, standby, drain errors, and close workspace."""
    phases = _new_phases()
    child_results: list[dict] = []
    _call_step(phases, child_results, "observe", A_flow_snapshot_easyexpert_context)
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_emergency_easyexpert_abort_standby,
        standby_enabled=standby_enabled,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_atom_easyexpert_wait_opc,
        timeout_s=timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_easyexpert_errors,
        max_errors=max_errors,
        force_clear=force_clear,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_teardown_easyexpert_workspace,
        timeout_s=timeout_s,
        ignore_no_workspace=ignore_no_workspace,
    )
    return _ab_response(
        "AB_flow_shutdown_easyexpert_workspace_standby",
        "shutdown",
        "easyexpert_workspace",
        "EasyEXPERT activity aborted, standby verified, errors drained, and workspace closed.",
        phases,
        child_results,
        {
            "standby_enabled": standby_enabled,
            "timeout_s": timeout_s,
            "max_errors": max_errors,
            "force_clear": force_clear,
            "ignore_no_workspace": ignore_no_workspace,
        },
    )


def AB_flow_recovery_flex_emergency_zero(
    include_pre_snapshot: bool = True,
    include_timestamp: bool = False,
    confirm_timeout_s: float = 5.0,
    max_errors: int = 20,
) -> dict:
    """Emergency direct B1500A abort/zero with error drain and post snapshot."""
    phases = _new_phases()
    child_results: list[dict] = []
    if include_pre_snapshot:
        _call_step(
            phases,
            child_results,
            "observe",
            A_flow_snapshot_flex_status,
            include_timestamp=include_timestamp,
        )
    else:
        _skip_step(
            phases,
            child_results,
            "observe",
            "A_flow_snapshot_flex_status",
            "include_pre_snapshot=False; emergency act may proceed first",
            optional=True,
            include_timestamp=include_timestamp,
        )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_emergency_b1500_abort_zero,
        confirm_timeout_s=confirm_timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        "AB_flow_recovery_flex_emergency_zero",
        "recovery",
        "flex_session",
        "Direct B1500A emergency zero completed with drained-error and status evidence.",
        phases,
        child_results,
        {
            "include_pre_snapshot": include_pre_snapshot,
            "include_timestamp": include_timestamp,
            "confirm_timeout_s": confirm_timeout_s,
            "max_errors": max_errors,
        },
    )


def AB_flow_recovery_flex_reset_rediscover(
    include_timestamp: bool = False,
    confirm_timeout_s: float = 5.0,
    initialize: bool = False,
    set_auto_calibration: bool = False,
    auto_calibration_enabled: bool = False,
    operator_ack: bool = False,
    max_errors: int = 20,
) -> dict:
    """Reset direct B1500A state, rediscover identity/settings, and verify."""
    flow = "AB_flow_recovery_flex_reset_rediscover"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    if operator_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_baseline_b1500_known_state,
            confirm_timeout_s=confirm_timeout_s,
            initialize=initialize,
            set_auto_calibration=set_auto_calibration,
            auto_calibration_enabled=auto_calibration_enabled,
            operator_ack=operator_ack,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "operator_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_baseline_b1500_known_state",
            "operator_ack=False",
            optional=False,
            confirm_timeout_s=confirm_timeout_s,
            initialize=initialize,
            set_auto_calibration=set_auto_calibration,
            auto_calibration_enabled=auto_calibration_enabled,
            operator_ack=operator_ack,
        )
    _call_step(phases, child_results, "verify", A_atom_flex_identify)
    _call_step(phases, child_results, "verify", A_atom_flex_list_modules)
    _call_step(phases, child_results, "verify", A_atom_flex_query_settings)
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        flow,
        "recovery",
        "flex_session",
        "Direct B1500A baseline reset was gated, then identity/settings/status were captured.",
        phases,
        child_results,
        {
            "include_timestamp": include_timestamp,
            "confirm_timeout_s": confirm_timeout_s,
            "initialize": initialize,
            "set_auto_calibration": set_auto_calibration,
            "auto_calibration_enabled": auto_calibration_enabled,
            "operator_ack": operator_ack,
            "max_errors": max_errors,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=operator_ack,
    )


def AB_flow_recovery_wgfmu_abort_disconnect(
    include_pre_snapshot: bool = True,
    channel_ids: str = "501,502",
    max_errors: int = 20,
) -> dict:
    """Recover a stuck WGFMU sequencer without closing the session."""
    phases = _new_phases()
    child_results: list[dict] = []
    if include_pre_snapshot:
        _call_step(phases, child_results, "observe", A_flow_snapshot_wgfmu_diagnostics)
    else:
        _skip_step(
            phases,
            child_results,
            "observe",
            "A_flow_snapshot_wgfmu_diagnostics",
            "include_pre_snapshot=False; emergency act may proceed first",
            optional=True,
        )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_emergency_wgfmu_abort_disconnect,
        channel_ids=channel_ids,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_wgfmu_errors,
        max_errors=max_errors,
    )
    _call_step(phases, child_results, "verify", A_flow_snapshot_wgfmu_diagnostics)
    return _ab_response(
        "AB_flow_recovery_wgfmu_abort_disconnect",
        "recovery",
        "wgfmu_session",
        "WGFMU sequencer aborted/disconnected with diagnostics preserved.",
        phases,
        child_results,
        {
            "include_pre_snapshot": include_pre_snapshot,
            "channel_ids": channel_ids,
            "max_errors": max_errors,
        },
    )


def AB_flow_recovery_easyexpert_abort_standby(
    include_pre_snapshot: bool = True,
    standby_enabled: bool = True,
    timeout_s: float = 60.0,
    max_errors: int = 20,
    force_clear: bool = False,
) -> dict:
    """Recover EasyEXPERT by aborting, setting standby, draining, and snapshotting."""
    phases = _new_phases()
    child_results: list[dict] = []
    if include_pre_snapshot:
        _call_step(phases, child_results, "observe", A_flow_snapshot_easyexpert_context)
    else:
        _skip_step(
            phases,
            child_results,
            "observe",
            "A_flow_snapshot_easyexpert_context",
            "include_pre_snapshot=False; emergency act may proceed first",
            optional=True,
        )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_emergency_easyexpert_abort_standby,
        standby_enabled=standby_enabled,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_atom_easyexpert_wait_opc,
        timeout_s=timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_easyexpert_errors,
        max_errors=max_errors,
        force_clear=force_clear,
    )
    _call_step(phases, child_results, "verify", A_flow_snapshot_easyexpert_context)
    return _ab_response(
        "AB_flow_recovery_easyexpert_abort_standby",
        "recovery",
        "easyexpert_workspace",
        "EasyEXPERT abort/standby recovery completed with error/context evidence.",
        phases,
        child_results,
        {
            "include_pre_snapshot": include_pre_snapshot,
            "standby_enabled": standby_enabled,
            "timeout_s": timeout_s,
            "max_errors": max_errors,
            "force_clear": force_clear,
        },
    )


def AB_flow_maintenance_flex_self_test_calibration(
    include_timestamp: bool = False,
    confirm_timeout_s: float = 5.0,
    run_self_calibration: bool = False,
    repeat_self_test_after_calibration: bool = True,
    force_calibration_after_self_test_failure: bool = False,
    operator_ack: bool = False,
    max_errors: int = 20,
) -> dict:
    """Run gated B1500A self-test/calibration with pre/post evidence."""
    flow = "AB_flow_maintenance_flex_self_test_calibration"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    if operator_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_maintenance_b1500_self_test_calibration,
            confirm_timeout_s=confirm_timeout_s,
            run_self_calibration=run_self_calibration,
            repeat_self_test_after_calibration=repeat_self_test_after_calibration,
            force_calibration_after_self_test_failure=force_calibration_after_self_test_failure,
            operator_ack=operator_ack,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "operator_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_maintenance_b1500_self_test_calibration",
            "operator_ack=False",
            optional=False,
            confirm_timeout_s=confirm_timeout_s,
            run_self_calibration=run_self_calibration,
            repeat_self_test_after_calibration=repeat_self_test_after_calibration,
            force_calibration_after_self_test_failure=force_calibration_after_self_test_failure,
            operator_ack=operator_ack,
        )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        flow,
        "maintenance",
        "flex_session",
        "B1500A maintenance self-test/calibration was gated and post-checked.",
        phases,
        child_results,
        {
            "include_timestamp": include_timestamp,
            "confirm_timeout_s": confirm_timeout_s,
            "run_self_calibration": run_self_calibration,
            "repeat_self_test_after_calibration": repeat_self_test_after_calibration,
            "force_calibration_after_self_test_failure": force_calibration_after_self_test_failure,
            "operator_ack": operator_ack,
            "max_errors": max_errors,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=operator_ack,
    )


def AB_flow_maintenance_wgfmu_self_test_calibration(
    address: str = "GPIB0::17::INSTR",
    timeout_s: float = 100.0,
    log_file_name: str = "wgfmu.log",
    warning_level: str = "NORMAL",
    set_warning_policy: bool = False,
    warnings_as_errors: bool = False,
    initialize: bool = False,
    run_self_calibration: bool = False,
    repeat_self_test_after_calibration: bool = True,
    force_calibration_after_self_test_failure: bool = False,
    operator_ack: bool = False,
) -> dict:
    """Run gated WGFMU self-test/calibration with session/log evidence."""
    flow = "AB_flow_maintenance_wgfmu_self_test_calibration"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_discover_wgfmu_session,
        address=address,
        timeout_s=timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_prepare_wgfmu_logging,
        timeout_s=timeout_s,
        file_name=log_file_name,
        warning_level=warning_level,
    )
    _call_step(phases, child_results, "observe", A_flow_snapshot_wgfmu_diagnostics)
    if operator_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_maintenance_wgfmu_self_test_calibration,
            set_warning_policy=set_warning_policy,
            warnings_as_errors=warnings_as_errors,
            initialize=initialize,
            run_self_calibration=run_self_calibration,
            repeat_self_test_after_calibration=repeat_self_test_after_calibration,
            force_calibration_after_self_test_failure=force_calibration_after_self_test_failure,
            operator_ack=operator_ack,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "operator_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_maintenance_wgfmu_self_test_calibration",
            "operator_ack=False",
            optional=False,
            set_warning_policy=set_warning_policy,
            warnings_as_errors=warnings_as_errors,
            initialize=initialize,
            run_self_calibration=run_self_calibration,
            repeat_self_test_after_calibration=repeat_self_test_after_calibration,
            force_calibration_after_self_test_failure=force_calibration_after_self_test_failure,
            operator_ack=operator_ack,
        )
    _call_step(phases, child_results, "verify", A_flow_snapshot_wgfmu_diagnostics)
    return _ab_response(
        flow,
        "maintenance",
        "wgfmu_session",
        "WGFMU maintenance self-test/calibration was gated and diagnostically checked.",
        phases,
        child_results,
        {
            "address": address,
            "timeout_s": timeout_s,
            "log_file_name": log_file_name,
            "warning_level": warning_level,
            "set_warning_policy": set_warning_policy,
            "warnings_as_errors": warnings_as_errors,
            "initialize": initialize,
            "run_self_calibration": run_self_calibration,
            "repeat_self_test_after_calibration": repeat_self_test_after_calibration,
            "force_calibration_after_self_test_failure": force_calibration_after_self_test_failure,
            "operator_ack": operator_ack,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=operator_ack,
    )


def AB_flow_preparation_flex_nonmeasurement_baseline(
    include_timestamp: bool = False,
    device_type: str = "unknown",
    pin_map_known: bool = False,
    set_auto_calibration: bool = False,
    auto_calibration_enabled: bool = False,
    set_adc_zero: bool = False,
    adc_zero_enabled: bool = False,
    filter_channels: str = "",
    filter_enabled: bool = False,
    series_resistor_channels: str = "",
    series_resistor_enabled: bool = False,
    format_mode: int = 1,
    output_mode: int = 1,
    timestamp_enabled: bool = True,
    reset_timestamp: bool = False,
    allow_clear_buffer: bool = False,
    timeout_s: float = 60.0,
) -> dict:
    """Prepare FLEX non-measurement baseline for later C-class work."""
    phases = _new_phases()
    child_results: list[dict] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_preflight_b1500_gate,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_baseline_smu_housekeeping,
        set_auto_calibration=set_auto_calibration,
        auto_calibration_enabled=auto_calibration_enabled,
        set_adc_zero=set_adc_zero,
        adc_zero_enabled=adc_zero_enabled,
        filter_channels=filter_channels,
        filter_enabled=filter_enabled,
        series_resistor_channels=series_resistor_channels,
        series_resistor_enabled=series_resistor_enabled,
    )
    _call_step(
        phases,
        child_results,
        "act",
        A_flow_prepare_flex_output_buffer,
        format_mode=format_mode,
        output_mode=output_mode,
        timestamp_enabled=timestamp_enabled,
        reset_timestamp=reset_timestamp,
        allow_clear_buffer=allow_clear_buffer,
        timeout_s=timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        "AB_flow_preparation_flex_nonmeasurement_baseline",
        "preparation",
        "flex_session",
        "FLEX preflight, SMU housekeeping, and output-buffer baseline completed.",
        phases,
        child_results,
        {
            "include_timestamp": include_timestamp,
            "device_type": device_type,
            "pin_map_known": pin_map_known,
            "set_auto_calibration": set_auto_calibration,
            "auto_calibration_enabled": auto_calibration_enabled,
            "set_adc_zero": set_adc_zero,
            "adc_zero_enabled": adc_zero_enabled,
            "filter_channels": filter_channels,
            "filter_enabled": filter_enabled,
            "series_resistor_channels": series_resistor_channels,
            "series_resistor_enabled": series_resistor_enabled,
            "format_mode": format_mode,
            "output_mode": output_mode,
            "timestamp_enabled": timestamp_enabled,
            "reset_timestamp": reset_timestamp,
            "allow_clear_buffer": allow_clear_buffer,
            "timeout_s": timeout_s,
        },
    )


def AB_flow_preparation_asu_low_current_path(
    gpib_address: int = 17,
    gpib_board: int = 0,
    timeout_ms: int = 600_000,
    device_type: str = "unknown",
    pin_map_known: bool = False,
    channel: int = 1,
    path: str = "SMU",
    channels: str = "",
    confirm_timeout_s: float = 5.0,
    fixture_ack: bool = False,
    set_1pa_range: bool = False,
    range_1pa_enabled: bool = False,
    set_indicator: bool = False,
    indicator_enabled: bool = True,
    set_smu_filter: bool = False,
    smu_filter_enabled: bool = False,
    max_errors: int = 20,
    include_timestamp: bool = False,
) -> dict:
    """Prepare ASU low-current path with discovery, preflight, and evidence."""
    flow = "AB_flow_preparation_asu_low_current_path"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_discover_flex_session,
        gpib_address=gpib_address,
        gpib_board=gpib_board,
        timeout_ms=timeout_ms,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_preflight_b1500_gate,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    if fixture_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_preparation_asu_low_current_path,
            channel=channel,
            path=path,
            channels=channels,
            confirm_timeout_s=confirm_timeout_s,
            fixture_ack=fixture_ack,
            set_1pa_range=set_1pa_range,
            range_1pa_enabled=range_1pa_enabled,
            set_indicator=set_indicator,
            indicator_enabled=indicator_enabled,
            set_smu_filter=set_smu_filter,
            smu_filter_enabled=smu_filter_enabled,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "fixture_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_preparation_asu_low_current_path",
            "fixture_ack=False",
            optional=False,
            channel=channel,
            path=path,
            channels=channels,
            confirm_timeout_s=confirm_timeout_s,
            fixture_ack=fixture_ack,
            set_1pa_range=set_1pa_range,
            range_1pa_enabled=range_1pa_enabled,
            set_indicator=set_indicator,
            indicator_enabled=indicator_enabled,
            set_smu_filter=set_smu_filter,
            smu_filter_enabled=smu_filter_enabled,
        )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        flow,
        "preparation",
        "asu_low_current_path",
        "ASU low-current route preparation was gated and verified.",
        phases,
        child_results,
        {
            "gpib_address": gpib_address,
            "gpib_board": gpib_board,
            "timeout_ms": timeout_ms,
            "device_type": device_type,
            "pin_map_known": pin_map_known,
            "channel": channel,
            "path": path,
            "channels": channels,
            "confirm_timeout_s": confirm_timeout_s,
            "fixture_ack": fixture_ack,
            "set_1pa_range": set_1pa_range,
            "range_1pa_enabled": range_1pa_enabled,
            "set_indicator": set_indicator,
            "indicator_enabled": indicator_enabled,
            "set_smu_filter": set_smu_filter,
            "smu_filter_enabled": smu_filter_enabled,
            "max_errors": max_errors,
            "include_timestamp": include_timestamp,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=fixture_ack,
        fixture_sensitive=True,
    )


def AB_flow_preparation_scuu_signal_path(
    gpib_address: int = 17,
    gpib_board: int = 0,
    timeout_ms: int = 600_000,
    device_type: str = "unknown",
    pin_map_known: bool = False,
    channel: int = 1,
    path_mode: str = "open",
    channels: str = "",
    confirm_timeout_s: float = 5.0,
    fixture_ack: bool = False,
    set_indicator: bool = False,
    indicator_enabled: bool = True,
    max_errors: int = 20,
    include_timestamp: bool = False,
) -> dict:
    """Prepare SCUU signal path with discovery, preflight, and evidence."""
    flow = "AB_flow_preparation_scuu_signal_path"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_discover_flex_session,
        gpib_address=gpib_address,
        gpib_board=gpib_board,
        timeout_ms=timeout_ms,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_preflight_b1500_gate,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    if fixture_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_preparation_scuu_signal_path,
            channel=channel,
            path_mode=path_mode,
            channels=channels,
            confirm_timeout_s=confirm_timeout_s,
            fixture_ack=fixture_ack,
            set_indicator=set_indicator,
            indicator_enabled=indicator_enabled,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "fixture_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_preparation_scuu_signal_path",
            "fixture_ack=False",
            optional=False,
            channel=channel,
            path_mode=path_mode,
            channels=channels,
            confirm_timeout_s=confirm_timeout_s,
            fixture_ack=fixture_ack,
            set_indicator=set_indicator,
            indicator_enabled=indicator_enabled,
        )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        flow,
        "preparation",
        "scuu_signal_path",
        "SCUU signal path preparation was gated and verified.",
        phases,
        child_results,
        {
            "gpib_address": gpib_address,
            "gpib_board": gpib_board,
            "timeout_ms": timeout_ms,
            "device_type": device_type,
            "pin_map_known": pin_map_known,
            "channel": channel,
            "path_mode": path_mode,
            "channels": channels,
            "confirm_timeout_s": confirm_timeout_s,
            "fixture_ack": fixture_ack,
            "set_indicator": set_indicator,
            "indicator_enabled": indicator_enabled,
            "max_errors": max_errors,
            "include_timestamp": include_timestamp,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=fixture_ack,
        fixture_sensitive=True,
    )


def AB_flow_correction_cmu_open_short_load(
    include_timestamp: bool = False,
    device_type: str = "unknown",
    pin_map_known: bool = False,
    channel: int = 1,
    correction_types: str = "OPEN,SHOR,LOAD",
    confirm_timeout_s: float = 5.0,
    clear_existing: bool = False,
    fixture_condition_ack: bool = False,
    max_errors: int = 20,
) -> dict:
    """Run gated CMU open/short/load correction with pre/post evidence."""
    flow = "AB_flow_correction_cmu_open_short_load"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_preflight_b1500_gate,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    if fixture_condition_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_correction_cmu_open_short_load,
            channel=channel,
            correction_types=correction_types,
            confirm_timeout_s=confirm_timeout_s,
            clear_existing=clear_existing,
            fixture_condition_ack=fixture_condition_ack,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "fixture_condition_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_correction_cmu_open_short_load",
            "fixture_condition_ack=False",
            optional=False,
            channel=channel,
            correction_types=correction_types,
            confirm_timeout_s=confirm_timeout_s,
            clear_existing=clear_existing,
            fixture_condition_ack=fixture_condition_ack,
        )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        flow,
        "correction",
        "cmu_open_short_load",
        "CMU open/short/load correction was gated and verified.",
        phases,
        child_results,
        {
            "include_timestamp": include_timestamp,
            "device_type": device_type,
            "pin_map_known": pin_map_known,
            "channel": channel,
            "correction_types": correction_types,
            "confirm_timeout_s": confirm_timeout_s,
            "clear_existing": clear_existing,
            "fixture_condition_ack": fixture_condition_ack,
            "max_errors": max_errors,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=fixture_condition_ack,
        fixture_sensitive=True,
    )


def AB_flow_correction_cmu_phase_compensation(
    include_timestamp: bool = False,
    device_type: str = "unknown",
    pin_map_known: bool = False,
    channel: int = 1,
    mode: str = "auto",
    confirm_timeout_s: float = 5.0,
    fixture_condition_ack: bool = False,
    max_errors: int = 20,
) -> dict:
    """Run gated MFCMU phase compensation with pre/post evidence."""
    flow = "AB_flow_correction_cmu_phase_compensation"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_preflight_b1500_gate,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    if fixture_condition_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_correction_cmu_phase_compensation,
            channel=channel,
            mode=mode,
            confirm_timeout_s=confirm_timeout_s,
            fixture_condition_ack=fixture_condition_ack,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "fixture_condition_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_correction_cmu_phase_compensation",
            "fixture_condition_ack=False",
            optional=False,
            channel=channel,
            mode=mode,
            confirm_timeout_s=confirm_timeout_s,
            fixture_condition_ack=fixture_condition_ack,
        )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        flow,
        "correction",
        "cmu_phase_compensation",
        "CMU phase compensation was gated and verified.",
        phases,
        child_results,
        {
            "include_timestamp": include_timestamp,
            "device_type": device_type,
            "pin_map_known": pin_map_known,
            "channel": channel,
            "mode": mode,
            "confirm_timeout_s": confirm_timeout_s,
            "fixture_condition_ack": fixture_condition_ack,
            "max_errors": max_errors,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=fixture_condition_ack,
        fixture_sensitive=True,
    )


def AB_flow_correction_qscv_offset_cancel(
    include_timestamp: bool = False,
    device_type: str = "unknown",
    pin_map_known: bool = False,
    channel: int = 1,
    confirm_timeout_s: float = 5.0,
    fixture_condition_ack: bool = False,
    max_errors: int = 20,
) -> dict:
    """Run gated QSCV offset cancel precursor without measurement execution."""
    flow = "AB_flow_correction_qscv_offset_cancel"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    _call_step(
        phases,
        child_results,
        "observe",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    _call_step(
        phases,
        child_results,
        "act",
        B_flow_preflight_b1500_gate,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    if fixture_condition_ack:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_correction_qscv_offset_cancel,
            channel=channel,
            confirm_timeout_s=confirm_timeout_s,
            fixture_condition_ack=fixture_condition_ack,
        )
    else:
        warnings.append(_ack_missing_warning(flow, "fixture_condition_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_correction_qscv_offset_cancel",
            "fixture_condition_ack=False",
            optional=False,
            channel=channel,
            confirm_timeout_s=confirm_timeout_s,
            fixture_condition_ack=fixture_condition_ack,
        )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_flex_errors,
        max_errors=max_errors,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_snapshot_flex_status,
        include_timestamp=include_timestamp,
    )
    return _ab_response(
        flow,
        "correction",
        "qscv_offset_cancel",
        "QSCV offset cancel was gated and verified without running QSCV measurement.",
        phases,
        child_results,
        {
            "include_timestamp": include_timestamp,
            "device_type": device_type,
            "pin_map_known": pin_map_known,
            "channel": channel,
            "confirm_timeout_s": confirm_timeout_s,
            "fixture_condition_ack": fixture_condition_ack,
            "max_errors": max_errors,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=fixture_condition_ack,
        fixture_sensitive=True,
    )


def AB_flow_correction_easyexpert_zero_cancel(
    channel: str = "all",
    disable_before_measure: bool = False,
    measure_zero_cancel: bool = False,
    fixture_condition_ack: bool = False,
    operator_ack: bool = False,
    timeout_s: float = 60.0,
    max_errors: int = 20,
    force_clear: bool = False,
) -> dict:
    """Run gated EasyEXPERT zero-cancel correction with context/error evidence."""
    flow = "AB_flow_correction_easyexpert_zero_cancel"
    phases = _new_phases()
    child_results: list[dict] = []
    warnings: list[str] = []
    fixture_required = measure_zero_cancel
    ack_received = operator_ack and (fixture_condition_ack or not fixture_required)
    _call_step(phases, child_results, "observe", A_flow_snapshot_easyexpert_context)
    if ack_received:
        _call_step(
            phases,
            child_results,
            "act",
            B_flow_correction_easyexpert_zero_cancel,
            channel=channel,
            disable_before_measure=disable_before_measure,
            measure_zero_cancel=measure_zero_cancel,
            fixture_condition_ack=fixture_condition_ack,
            operator_ack=operator_ack,
        )
    else:
        if not operator_ack:
            warnings.append(_ack_missing_warning(flow, "operator_ack"))
        if fixture_required and not fixture_condition_ack:
            warnings.append(_ack_missing_warning(flow, "fixture_condition_ack"))
        _skip_step(
            phases,
            child_results,
            "act",
            "B_flow_correction_easyexpert_zero_cancel",
            "required acknowledgement missing",
            optional=False,
            channel=channel,
            disable_before_measure=disable_before_measure,
            measure_zero_cancel=measure_zero_cancel,
            fixture_condition_ack=fixture_condition_ack,
            operator_ack=operator_ack,
        )
    _call_step(
        phases,
        child_results,
        "verify",
        A_atom_easyexpert_wait_opc,
        timeout_s=timeout_s,
    )
    _call_step(
        phases,
        child_results,
        "verify",
        A_flow_drain_easyexpert_errors,
        max_errors=max_errors,
        force_clear=force_clear,
    )
    _call_step(phases, child_results, "verify", A_flow_snapshot_easyexpert_context)
    return _ab_response(
        flow,
        "correction",
        "easyexpert_zero_cancel",
        "EasyEXPERT zero-cancel state/correction was gated and verified.",
        phases,
        child_results,
        {
            "channel": channel,
            "disable_before_measure": disable_before_measure,
            "measure_zero_cancel": measure_zero_cancel,
            "fixture_condition_ack": fixture_condition_ack,
            "operator_ack": operator_ack,
            "timeout_s": timeout_s,
            "max_errors": max_errors,
            "force_clear": force_clear,
        },
        warnings=warnings,
        operator_ack_required=True,
        operator_ack_received=ack_received,
        fixture_sensitive=fixture_required,
    )


AB_FLOW_FUNCTIONS = [
    AB_flow_startup_flex_safe_session,
    AB_flow_startup_wgfmu_baseline_session,
    AB_flow_startup_easyexpert_workspace_standby,
    AB_flow_shutdown_flex_safe_session,
    AB_flow_shutdown_wgfmu_safe_session,
    AB_flow_shutdown_easyexpert_workspace_standby,
    AB_flow_recovery_flex_emergency_zero,
    AB_flow_recovery_flex_reset_rediscover,
    AB_flow_recovery_wgfmu_abort_disconnect,
    AB_flow_recovery_easyexpert_abort_standby,
    AB_flow_maintenance_flex_self_test_calibration,
    AB_flow_maintenance_wgfmu_self_test_calibration,
    AB_flow_preparation_flex_nonmeasurement_baseline,
    AB_flow_preparation_asu_low_current_path,
    AB_flow_preparation_scuu_signal_path,
    AB_flow_correction_cmu_open_short_load,
    AB_flow_correction_cmu_phase_compensation,
    AB_flow_correction_qscv_offset_cancel,
    AB_flow_correction_easyexpert_zero_cancel,
]


def register_ab_flows(mcp: FastMCP) -> None:
    """Register all AB_flow_* tools on a FastMCP instance."""
    for tool in AB_FLOW_FUNCTIONS:
        mcp.tool(tool)
