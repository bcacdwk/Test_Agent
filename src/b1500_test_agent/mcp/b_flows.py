"""B-class fake MCP flow tools."""

from fastmcp import FastMCP

from .b_atoms import (
    B_atom_calibration_b1500_self_calibration,
    B_atom_calibration_easyexpert_measure_zero_cancel,
    B_atom_calibration_easyexpert_query_zero_cancel_state,
    B_atom_calibration_easyexpert_zero_cancel_off,
    B_atom_calibration_easyexpert_zero_cancel_on,
    B_atom_calibration_smu_set_adc_zero,
    B_atom_calibration_wgfmu_self_calibration,
    B_atom_correction_cmu_clear,
    B_atom_correction_cmu_measure_data,
    B_atom_correction_cmu_perform_phase_comp,
    B_atom_correction_cmu_set_correction,
    B_atom_correction_cmu_set_phase_mode,
    B_atom_correction_qscv_offset_cancel,
    B_atom_diagnostic_b1500_self_test,
    B_atom_diagnostic_wgfmu_self_test,
    B_atom_lifecycle_b1500_initialize,
    B_atom_lifecycle_b1500_reset,
    B_atom_lifecycle_wgfmu_abort,
    B_atom_lifecycle_wgfmu_initialize,
    B_atom_output_b1500_confirm_zero,
    B_atom_output_b1500_disable_channels,
    B_atom_output_b1500_zero_all,
    B_atom_output_b1500_zero_outputs,
    B_atom_output_easyexpert_set_standby,
    B_atom_output_smu_set_filter,
    B_atom_output_smu_set_series_resistor,
    B_atom_output_wgfmu_disconnect,
    B_atom_policy_b1500_set_auto_calibration,
    B_atom_policy_wgfmu_treat_warnings_as_errors,
    B_atom_routing_asu_set_1pa_range,
    B_atom_routing_asu_set_indicator,
    B_atom_routing_asu_set_path,
    B_atom_routing_scuu_set_indicator,
    B_atom_routing_scuu_set_path,
    B_atom_safety_b1500_abort,
    B_atom_safety_b1500_check_interlock,
    B_atom_safety_b1500_preflight,
    B_atom_safety_easyexpert_abort_measurement,
)
from .common import _atom_skip, _atom_step, _parse_channels


# ---------------------------------------------------------------------------
# B class — flows: ordered, reusable compositions of B_atom_* subcommands
#
# Each B_flow_* orchestrates only B_atom_* tools into one safety/state-control
# operation. The flows stay fake: they call local atom functions in series,
# preserve every returned payload, and never touch real hardware.
# ---------------------------------------------------------------------------


def _skip_atom(records: list[dict], atom: object, reason: str, **inputs: object) -> None:
    """Record a skipped B atom by function object."""
    _atom_skip(records, getattr(atom, "__name__", str(atom)), reason, **inputs)


def _b_flow_response(
    flow: str,
    category: str,
    target: str,
    subject: str,
    atom_results: list[dict],
    purpose: str,
    *,
    destructive: bool,
    fixture_sensitive: bool,
    operator_ack_required: bool,
    ok: bool = True,
    partial: bool = False,
    warnings: list[str] | None = None,
    inputs: dict | None = None,
    outputs: dict | None = None,
) -> dict:
    """Build the standard fake B_flow response envelope."""
    return {
        "flow": flow,
        "flow_class": "B",
        "category": category,
        "target": target,
        "subject": subject,
        "fake": True,
        "hardware_touched": False,
        "ok": ok,
        "partial": partial,
        "destructive": destructive,
        "fixture_sensitive": fixture_sensitive,
        "operator_ack_required": operator_ack_required,
        "atoms_called": [record["atom"] for record in atom_results if record["status"] == "ok"],
        "atom_results": atom_results,
        "inputs": dict(inputs or {}),
        "outputs": dict(outputs or {}),
        "warnings": list(warnings or []),
        "purpose": purpose,
    }


def _atom_ok(result: dict) -> bool:
    """Interpret common fake atom pass/fail fields without rewriting payloads."""
    if result.get("passed") is False:
        return False
    if "result_code" in result and result.get("result_code") not in {0, "0"}:
        return False
    return True


def _zero_confirmed(result: dict) -> bool:
    """Return whether the fake zero confirmation passed."""
    return result.get("within_2v") is True


def _operator_warning(flow: str, operator_ack_required: bool, operator_ack: bool) -> list[str]:
    """Warn when a destructive/operator-visible fake flow lacks acknowledgement."""
    if operator_ack_required and not operator_ack:
        return [
            f"{flow} is operator-visible/destructive; operator_ack=False was recorded "
            "for client gating."
        ]
    return []


def _parse_correction_types(correction_types: str) -> tuple[list[str], list[str]]:
    """Normalize CMU correction type labels and return warnings for unknown labels."""
    allowed = {"OPEN", "SHOR", "LOAD"}
    requested = [part.strip().upper() for part in correction_types.split(",") if part.strip()]
    accepted = [item for item in requested if item in allowed]
    rejected = [item for item in requested if item not in allowed]
    warnings = [f"Skipped unsupported CMU correction type: {item}." for item in rejected]
    return accepted, warnings


def _zero_all_confirm(records: list[dict], confirm_timeout_s: float) -> bool:
    """Run the common all-channel zero and confirmation prerequisite."""
    _atom_step(records, B_atom_output_b1500_zero_all)
    confirm = _atom_step(records, B_atom_output_b1500_confirm_zero, timeout_s=confirm_timeout_s)
    return _zero_confirmed(confirm)


def _zero_disable_confirm(records: list[dict], channels: str, confirm_timeout_s: float) -> bool:
    """Run the common selected/all-channel zero, disable, and confirmation bracket."""
    _atom_step(records, B_atom_output_b1500_zero_outputs, channels=channels)
    _atom_step(records, B_atom_output_b1500_disable_channels, channels=channels)
    confirm = _atom_step(records, B_atom_output_b1500_confirm_zero, timeout_s=confirm_timeout_s)
    return _zero_confirmed(confirm)


def B_flow_emergency_b1500_abort_zero(confirm_timeout_s: float = 5.0) -> dict:
    """Abort direct B1500A activity, force all outputs to zero, and confirm zero."""
    records: list[dict] = []
    _atom_step(records, B_atom_safety_b1500_abort)
    _atom_step(records, B_atom_output_b1500_zero_all)
    confirm = _atom_step(records, B_atom_output_b1500_confirm_zero, timeout_s=confirm_timeout_s)
    confirmed = _zero_confirmed(confirm)
    warnings = []
    if not confirmed:
        warnings.append("Emergency zero confirmation did not pass in the fake atom payload.")
    return _b_flow_response(
        "B_flow_emergency_b1500_abort_zero",
        "emergency",
        "b1500",
        "abort_zero",
        records,
        "Core direct B1500A emergency bracket: abort, zero/disable all, then confirm zero.",
        destructive=True,
        fixture_sensitive=False,
        operator_ack_required=False,
        ok=confirmed,
        partial=not confirmed,
        inputs={"confirm_timeout_s": confirm_timeout_s},
        outputs={"zero_confirmed": confirmed},
        warnings=warnings,
    )


def B_flow_emergency_wgfmu_abort_disconnect(channel_ids: str = "501,502") -> dict:
    """Abort the WGFMU sequencer and disconnect declared WGFMU channels."""
    records: list[dict] = []
    parsed_channel_ids = _parse_channels(channel_ids)
    warnings = []
    _atom_step(records, B_atom_lifecycle_wgfmu_abort)
    if parsed_channel_ids:
        for channel_id in parsed_channel_ids:
            _atom_step(records, B_atom_output_wgfmu_disconnect, channel_id=channel_id)
    else:
        _skip_atom(
            records,
            B_atom_output_wgfmu_disconnect,
            "channel_ids parsed empty; no declared WGFMU outputs to disconnect",
            channel_id=None,
        )
        warnings.append("No WGFMU channel_ids were declared, so only abort was called.")
    partial = not bool(parsed_channel_ids)
    return _b_flow_response(
        "B_flow_emergency_wgfmu_abort_disconnect",
        "emergency",
        "wgfmu",
        "abort_disconnect",
        records,
        "Stop the WGFMU sequencer and disconnect each declared WGFMU output channel.",
        destructive=True,
        fixture_sensitive=False,
        operator_ack_required=False,
        ok=not partial,
        partial=partial,
        inputs={"channel_ids": channel_ids},
        outputs={"disconnected_channel_ids": parsed_channel_ids},
        warnings=warnings,
    )


def B_flow_emergency_easyexpert_abort_standby(standby_enabled: bool = True) -> dict:
    """Abort the selected EasyEXPERT measurement and set the requested standby state."""
    records: list[dict] = []
    _atom_step(records, B_atom_safety_easyexpert_abort_measurement)
    standby = _atom_step(
        records,
        B_atom_output_easyexpert_set_standby,
        enabled=standby_enabled,
    )
    return _b_flow_response(
        "B_flow_emergency_easyexpert_abort_standby",
        "emergency",
        "easyexpert",
        "abort_standby",
        records,
        "Abort EasyEXPERT selected measurement and set the requested standby state.",
        destructive=True,
        fixture_sensitive=False,
        operator_ack_required=False,
        inputs={"standby_enabled": standby_enabled},
        outputs={"standby_enabled": standby.get("enabled")},
    )


def B_flow_safe_state_b1500_zero_disable(
    channels: str = "",
    confirm_timeout_s: float = 5.0,
) -> dict:
    """Run the standard non-emergency B1500A zero/disable/confirm cleanup bracket."""
    records: list[dict] = []
    confirmed = _zero_disable_confirm(records, channels, confirm_timeout_s)
    warnings = []
    if not confirmed:
        warnings.append("Safe-state zero confirmation did not pass after zero/disable.")
    return _b_flow_response(
        "B_flow_safe_state_b1500_zero_disable",
        "safe_state",
        "b1500",
        "zero_disable",
        records,
        "Standard non-emergency output cleanup bracket: zero, disable, and confirm zero.",
        destructive=True,
        fixture_sensitive=False,
        operator_ack_required=False,
        ok=confirmed,
        partial=not confirmed,
        inputs={"channels": channels, "confirm_timeout_s": confirm_timeout_s},
        outputs={"zero_confirmed": confirmed},
        warnings=warnings,
    )


def B_flow_preflight_b1500_gate(
    device_type: str = "unknown",
    pin_map_known: bool = False,
) -> dict:
    """Run the explicit B-only safety/readiness gate."""
    records: list[dict] = []
    interlock = _atom_step(records, B_atom_safety_b1500_check_interlock)
    preflight = _atom_step(
        records,
        B_atom_safety_b1500_preflight,
        device_type=device_type,
        pin_map_known=pin_map_known,
    )
    passed = bool(preflight.get("passed"))
    warnings = []
    if not passed:
        warnings.append("B1500 preflight gate did not pass; do not proceed to measurement flows.")
    return _b_flow_response(
        "B_flow_preflight_b1500_gate",
        "preflight",
        "b1500",
        "gate",
        records,
        "Explicit B-only safety/readiness gate before any stateful measurement workflow.",
        destructive=False,
        fixture_sensitive=False,
        operator_ack_required=False,
        ok=passed,
        partial=False,
        inputs={"device_type": device_type, "pin_map_known": pin_map_known},
        outputs={
            "interlock_closed": interlock.get("interlock_closed"),
            "high_voltage_allowed": interlock.get("high_voltage_allowed"),
            "preflight_passed": passed,
        },
        warnings=warnings,
    )


def B_flow_baseline_b1500_known_state(
    confirm_timeout_s: float = 5.0,
    initialize: bool = False,
    set_auto_calibration: bool = False,
    auto_calibration_enabled: bool = False,
    operator_ack: bool = False,
) -> dict:
    """Zero/confirm, reset B1500A state, then optionally initialize and set CM policy."""
    flow = "B_flow_baseline_b1500_known_state"
    records: list[dict] = []
    warnings = _operator_warning(flow, True, operator_ack)
    confirmed = _zero_all_confirm(records, confirm_timeout_s)
    partial = False
    if confirmed:
        _atom_step(records, B_atom_lifecycle_b1500_reset)
        if initialize:
            _atom_step(records, B_atom_lifecycle_b1500_initialize)
        else:
            _skip_atom(records, B_atom_lifecycle_b1500_initialize, "initialize=False")
        if set_auto_calibration:
            _atom_step(
                records,
                B_atom_policy_b1500_set_auto_calibration,
                enabled=auto_calibration_enabled,
            )
        else:
            _skip_atom(
                records,
                B_atom_policy_b1500_set_auto_calibration,
                "set_auto_calibration=False",
                enabled=auto_calibration_enabled,
            )
    else:
        partial = True
        warnings.append("Zero/confirm prerequisite failed; reset/initialize/policy steps skipped.")
        _skip_atom(records, B_atom_lifecycle_b1500_reset, "zero confirmation failed")
        _skip_atom(records, B_atom_lifecycle_b1500_initialize, "zero confirmation failed")
        _skip_atom(
            records,
            B_atom_policy_b1500_set_auto_calibration,
            "zero confirmation failed",
            enabled=auto_calibration_enabled,
        )
    return _b_flow_response(
        flow,
        "baseline",
        "b1500",
        "known_state",
        records,
        "Known-state reset bracket after all outputs are zeroed and confirmed.",
        destructive=True,
        fixture_sensitive=False,
        operator_ack_required=True,
        ok=confirmed,
        partial=partial,
        inputs={
            "confirm_timeout_s": confirm_timeout_s,
            "initialize": initialize,
            "set_auto_calibration": set_auto_calibration,
            "auto_calibration_enabled": auto_calibration_enabled,
            "operator_ack": operator_ack,
        },
        outputs={"zero_confirmed": confirmed, "reset_performed": confirmed},
        warnings=warnings,
    )


def B_flow_baseline_wgfmu_known_state(
    set_warning_policy: bool = False,
    warnings_as_errors: bool = False,
) -> dict:
    """Initialize WGFMU state and optionally set warning-as-error policy."""
    records: list[dict] = []
    _atom_step(records, B_atom_lifecycle_wgfmu_initialize)
    if set_warning_policy:
        _atom_step(
            records,
            B_atom_policy_wgfmu_treat_warnings_as_errors,
            enabled=warnings_as_errors,
        )
    else:
        _skip_atom(
            records,
            B_atom_policy_wgfmu_treat_warnings_as_errors,
            "set_warning_policy=False",
            enabled=warnings_as_errors,
        )
    return _b_flow_response(
        "B_flow_baseline_wgfmu_known_state",
        "baseline",
        "wgfmu",
        "known_state",
        records,
        "WGFMU initialized baseline and optional warning policy for an existing session.",
        destructive=True,
        fixture_sensitive=False,
        operator_ack_required=False,
        inputs={
            "set_warning_policy": set_warning_policy,
            "warnings_as_errors": warnings_as_errors,
        },
        outputs={"initialized": True, "warning_policy_set": set_warning_policy},
        warnings=["Requires a pre-existing WGFMU session; this fake flow does not open one."],
    )


def B_flow_baseline_smu_housekeeping(
    set_auto_calibration: bool = False,
    auto_calibration_enabled: bool = False,
    set_adc_zero: bool = False,
    adc_zero_enabled: bool = False,
    filter_channels: str = "",
    filter_enabled: bool = False,
    series_resistor_channels: str = "",
    series_resistor_enabled: bool = False,
) -> dict:
    """Apply optional SMU housekeeping policy without enabling outputs."""
    records: list[dict] = []
    filter_channel_list = _parse_channels(filter_channels)
    series_channel_list = _parse_channels(series_resistor_channels)
    if set_auto_calibration:
        _atom_step(
            records,
            B_atom_policy_b1500_set_auto_calibration,
            enabled=auto_calibration_enabled,
        )
    else:
        _skip_atom(
            records,
            B_atom_policy_b1500_set_auto_calibration,
            "set_auto_calibration=False",
            enabled=auto_calibration_enabled,
        )
    if set_adc_zero:
        _atom_step(records, B_atom_calibration_smu_set_adc_zero, enabled=adc_zero_enabled)
    else:
        _skip_atom(
            records,
            B_atom_calibration_smu_set_adc_zero,
            "set_adc_zero=False",
            enabled=adc_zero_enabled,
        )
    if filter_channel_list:
        for channel in filter_channel_list:
            _atom_step(records, B_atom_output_smu_set_filter, channel=channel, enabled=filter_enabled)
    else:
        _skip_atom(
            records,
            B_atom_output_smu_set_filter,
            "filter_channels parsed empty",
            channel=None,
            enabled=filter_enabled,
        )
    if series_channel_list:
        for channel in series_channel_list:
            _atom_step(
                records,
                B_atom_output_smu_set_series_resistor,
                channel=channel,
                enabled=series_resistor_enabled,
            )
    else:
        _skip_atom(
            records,
            B_atom_output_smu_set_series_resistor,
            "series_resistor_channels parsed empty",
            channel=None,
            enabled=series_resistor_enabled,
        )
    state_changed = any(
        [set_auto_calibration, set_adc_zero, bool(filter_channel_list), bool(series_channel_list)]
    )
    return _b_flow_response(
        "B_flow_baseline_smu_housekeeping",
        "baseline",
        "smu",
        "housekeeping",
        records,
        "Establish repeatable SMU housekeeping policy without enabling outputs.",
        destructive=state_changed,
        fixture_sensitive=False,
        operator_ack_required=False,
        inputs={
            "set_auto_calibration": set_auto_calibration,
            "auto_calibration_enabled": auto_calibration_enabled,
            "set_adc_zero": set_adc_zero,
            "adc_zero_enabled": adc_zero_enabled,
            "filter_channels": filter_channels,
            "filter_enabled": filter_enabled,
            "series_resistor_channels": series_resistor_channels,
            "series_resistor_enabled": series_resistor_enabled,
        },
        outputs={
            "filter_channels": filter_channel_list,
            "series_resistor_channels": series_channel_list,
            "state_changed": state_changed,
        },
    )


def B_flow_maintenance_b1500_self_test_calibration(
    confirm_timeout_s: float = 5.0,
    run_self_calibration: bool = False,
    repeat_self_test_after_calibration: bool = True,
    force_calibration_after_self_test_failure: bool = False,
    operator_ack: bool = False,
) -> dict:
    """Run B1500A zeroed self-test and optional self-calibration bracket."""
    flow = "B_flow_maintenance_b1500_self_test_calibration"
    records: list[dict] = []
    warnings = _operator_warning(flow, True, operator_ack)
    confirmed = _zero_all_confirm(records, confirm_timeout_s)
    partial = False
    calibration_performed = False
    first_self_test_passed = False
    if not confirmed:
        partial = True
        warnings.append("Zero/confirm prerequisite failed; self-test/calibration steps skipped.")
        _skip_atom(records, B_atom_diagnostic_b1500_self_test, "zero confirmation failed")
        _skip_atom(records, B_atom_calibration_b1500_self_calibration, "zero confirmation failed")
    else:
        first_self_test = _atom_step(records, B_atom_diagnostic_b1500_self_test)
        first_self_test_passed = _atom_ok(first_self_test)
        calibration_allowed = first_self_test_passed or force_calibration_after_self_test_failure
        if run_self_calibration and calibration_allowed:
            _atom_step(records, B_atom_calibration_b1500_self_calibration)
            calibration_performed = True
            if repeat_self_test_after_calibration:
                _atom_step(records, B_atom_diagnostic_b1500_self_test)
            else:
                _skip_atom(
                    records,
                    B_atom_diagnostic_b1500_self_test,
                    "repeat_self_test_after_calibration=False",
                )
        elif run_self_calibration:
            partial = True
            warnings.append("Initial self-test failed; calibration skipped without force override.")
            _skip_atom(
                records,
                B_atom_calibration_b1500_self_calibration,
                "initial self-test failed",
            )
            _skip_atom(records, B_atom_diagnostic_b1500_self_test, "calibration skipped")
        else:
            _skip_atom(
                records,
                B_atom_calibration_b1500_self_calibration,
                "run_self_calibration=False",
            )
            _skip_atom(records, B_atom_diagnostic_b1500_self_test, "self-calibration not run")
    ok = confirmed and first_self_test_passed and not partial
    if confirmed and not run_self_calibration and first_self_test_passed:
        ok = True
    return _b_flow_response(
        flow,
        "maintenance",
        "b1500",
        "self_test_calibration",
        records,
        "B1500A self-test/calibration bracket after outputs are zeroed and confirmed.",
        destructive=run_self_calibration,
        fixture_sensitive=False,
        operator_ack_required=True,
        ok=ok,
        partial=partial,
        inputs={
            "confirm_timeout_s": confirm_timeout_s,
            "run_self_calibration": run_self_calibration,
            "repeat_self_test_after_calibration": repeat_self_test_after_calibration,
            "force_calibration_after_self_test_failure": force_calibration_after_self_test_failure,
            "operator_ack": operator_ack,
        },
        outputs={
            "zero_confirmed": confirmed,
            "initial_self_test_passed": first_self_test_passed,
            "calibration_performed": calibration_performed,
        },
        warnings=warnings,
    )


def B_flow_maintenance_wgfmu_self_test_calibration(
    set_warning_policy: bool = False,
    warnings_as_errors: bool = False,
    initialize: bool = False,
    run_self_calibration: bool = False,
    repeat_self_test_after_calibration: bool = True,
    force_calibration_after_self_test_failure: bool = False,
    operator_ack: bool = False,
) -> dict:
    """Run WGFMU self-test and optional self-calibration bracket."""
    flow = "B_flow_maintenance_wgfmu_self_test_calibration"
    records: list[dict] = []
    warnings = _operator_warning(flow, True, operator_ack)
    if set_warning_policy:
        _atom_step(
            records,
            B_atom_policy_wgfmu_treat_warnings_as_errors,
            enabled=warnings_as_errors,
        )
    else:
        _skip_atom(
            records,
            B_atom_policy_wgfmu_treat_warnings_as_errors,
            "set_warning_policy=False",
            enabled=warnings_as_errors,
        )
    if initialize:
        _atom_step(records, B_atom_lifecycle_wgfmu_initialize)
    else:
        _skip_atom(records, B_atom_lifecycle_wgfmu_initialize, "initialize=False")
    first_self_test = _atom_step(records, B_atom_diagnostic_wgfmu_self_test)
    first_self_test_passed = _atom_ok(first_self_test)
    partial = False
    calibration_performed = False
    calibration_allowed = first_self_test_passed or force_calibration_after_self_test_failure
    if run_self_calibration and calibration_allowed:
        _atom_step(records, B_atom_calibration_wgfmu_self_calibration)
        calibration_performed = True
        if repeat_self_test_after_calibration:
            _atom_step(records, B_atom_diagnostic_wgfmu_self_test)
        else:
            _skip_atom(
                records,
                B_atom_diagnostic_wgfmu_self_test,
                "repeat_self_test_after_calibration=False",
            )
    elif run_self_calibration:
        partial = True
        warnings.append("Initial WGFMU self-test failed; calibration skipped without force override.")
        _skip_atom(records, B_atom_calibration_wgfmu_self_calibration, "initial self-test failed")
        _skip_atom(records, B_atom_diagnostic_wgfmu_self_test, "calibration skipped")
    else:
        _skip_atom(
            records,
            B_atom_calibration_wgfmu_self_calibration,
            "run_self_calibration=False",
        )
        _skip_atom(records, B_atom_diagnostic_wgfmu_self_test, "self-calibration not run")
    return _b_flow_response(
        flow,
        "maintenance",
        "wgfmu",
        "self_test_calibration",
        records,
        "WGFMU maintenance bracket for self-test and optional self-calibration.",
        destructive=initialize or run_self_calibration or set_warning_policy,
        fixture_sensitive=False,
        operator_ack_required=True,
        ok=first_self_test_passed and not partial,
        partial=partial,
        inputs={
            "set_warning_policy": set_warning_policy,
            "warnings_as_errors": warnings_as_errors,
            "initialize": initialize,
            "run_self_calibration": run_self_calibration,
            "repeat_self_test_after_calibration": repeat_self_test_after_calibration,
            "force_calibration_after_self_test_failure": force_calibration_after_self_test_failure,
            "operator_ack": operator_ack,
        },
        outputs={
            "initial_self_test_passed": first_self_test_passed,
            "calibration_performed": calibration_performed,
        },
        warnings=warnings + ["Requires a pre-existing WGFMU session; this fake flow does not open one."],
    )


def B_flow_preparation_asu_low_current_path(
    channel: int,
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
) -> dict:
    """Safely prepare an ASU low-current path after zero/disable/confirm."""
    records: list[dict] = []
    warnings = []
    confirmed = _zero_disable_confirm(records, channels, confirm_timeout_s)
    gate_ok = confirmed and fixture_ack
    partial = not gate_ok
    if not confirmed:
        warnings.append("Zero/confirm prerequisite failed; ASU routing steps skipped.")
    if not fixture_ack:
        warnings.append("fixture_ack=False; ASU topology-sensitive routing steps skipped.")
    if gate_ok:
        _atom_step(records, B_atom_routing_asu_set_path, channel=channel, path=path)
        if set_1pa_range:
            _atom_step(
                records,
                B_atom_routing_asu_set_1pa_range,
                channel=channel,
                enabled=range_1pa_enabled,
            )
        else:
            _skip_atom(records, B_atom_routing_asu_set_1pa_range, "set_1pa_range=False")
        if set_indicator:
            _atom_step(
                records,
                B_atom_routing_asu_set_indicator,
                channel=channel,
                enabled=indicator_enabled,
            )
        else:
            _skip_atom(records, B_atom_routing_asu_set_indicator, "set_indicator=False")
        if set_smu_filter:
            _atom_step(
                records,
                B_atom_output_smu_set_filter,
                channel=channel,
                enabled=smu_filter_enabled,
            )
        else:
            _skip_atom(records, B_atom_output_smu_set_filter, "set_smu_filter=False")
    else:
        _skip_atom(records, B_atom_routing_asu_set_path, "zero/fixture gate not satisfied")
        _skip_atom(records, B_atom_routing_asu_set_1pa_range, "zero/fixture gate not satisfied")
        _skip_atom(records, B_atom_routing_asu_set_indicator, "zero/fixture gate not satisfied")
        _skip_atom(records, B_atom_output_smu_set_filter, "zero/fixture gate not satisfied")
    return _b_flow_response(
        "B_flow_preparation_asu_low_current_path",
        "preparation",
        "asu",
        "low_current_path",
        records,
        "Safe bracket for ASU low-current routing after B1500 outputs are zeroed.",
        destructive=True,
        fixture_sensitive=True,
        operator_ack_required=False,
        ok=gate_ok,
        partial=partial,
        inputs={
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
        },
        outputs={"zero_confirmed": confirmed, "routing_performed": gate_ok},
        warnings=warnings,
    )


def B_flow_preparation_scuu_signal_path(
    channel: int,
    path_mode: str = "open",
    channels: str = "",
    confirm_timeout_s: float = 5.0,
    fixture_ack: bool = False,
    set_indicator: bool = False,
    indicator_enabled: bool = True,
) -> dict:
    """Safely prepare an SCUU signal path after zero/disable/confirm."""
    records: list[dict] = []
    warnings = []
    confirmed = _zero_disable_confirm(records, channels, confirm_timeout_s)
    gate_ok = confirmed and fixture_ack
    partial = not gate_ok
    if not confirmed:
        warnings.append("Zero/confirm prerequisite failed; SCUU routing steps skipped.")
    if not fixture_ack:
        warnings.append("fixture_ack=False; SCUU topology-sensitive routing steps skipped.")
    if gate_ok:
        _atom_step(records, B_atom_routing_scuu_set_path, channel=channel, path_mode=path_mode)
        if set_indicator:
            _atom_step(
                records,
                B_atom_routing_scuu_set_indicator,
                channel=channel,
                enabled=indicator_enabled,
            )
        else:
            _skip_atom(records, B_atom_routing_scuu_set_indicator, "set_indicator=False")
    else:
        _skip_atom(records, B_atom_routing_scuu_set_path, "zero/fixture gate not satisfied")
        _skip_atom(records, B_atom_routing_scuu_set_indicator, "zero/fixture gate not satisfied")
    return _b_flow_response(
        "B_flow_preparation_scuu_signal_path",
        "preparation",
        "scuu",
        "signal_path",
        records,
        "Safe bracket for SCUU routing after B1500 outputs are zeroed.",
        destructive=True,
        fixture_sensitive=True,
        operator_ack_required=False,
        ok=gate_ok,
        partial=partial,
        inputs={
            "channel": channel,
            "path_mode": path_mode,
            "channels": channels,
            "confirm_timeout_s": confirm_timeout_s,
            "fixture_ack": fixture_ack,
            "set_indicator": set_indicator,
            "indicator_enabled": indicator_enabled,
        },
        outputs={"zero_confirmed": confirmed, "routing_performed": gate_ok},
        warnings=warnings,
    )


def B_flow_correction_cmu_open_short_load(
    channel: int,
    correction_types: str = "OPEN,SHOR,LOAD",
    confirm_timeout_s: float = 5.0,
    clear_existing: bool = False,
    fixture_condition_ack: bool = False,
) -> dict:
    """Run gated CMU open/short/load correction data capture."""
    records: list[dict] = []
    parsed_types, warnings = _parse_correction_types(correction_types)
    confirmed = _zero_all_confirm(records, confirm_timeout_s)
    gate_ok = confirmed and fixture_condition_ack and bool(parsed_types)
    partial = not gate_ok or bool(warnings)
    if not confirmed:
        warnings.append("Zero/confirm prerequisite failed; CMU correction steps skipped.")
    if not fixture_condition_ack:
        warnings.append("fixture_condition_ack=False; CMU correction steps skipped.")
    if not parsed_types:
        warnings.append("No supported CMU correction_types were requested.")
    if gate_ok:
        if clear_existing:
            _atom_step(records, B_atom_correction_cmu_clear)
        else:
            _skip_atom(records, B_atom_correction_cmu_clear, "clear_existing=False")
        for correction_type in parsed_types:
            _atom_step(
                records,
                B_atom_correction_cmu_set_correction,
                correction_type=correction_type,
                enabled=False,
            )
            _atom_step(
                records,
                B_atom_correction_cmu_measure_data,
                correction_type=correction_type,
                channel=channel,
            )
            _atom_step(
                records,
                B_atom_correction_cmu_set_correction,
                correction_type=correction_type,
                enabled=True,
            )
    else:
        _skip_atom(records, B_atom_correction_cmu_clear, "zero/fixture/type gate not satisfied")
        _skip_atom(
            records,
            B_atom_correction_cmu_set_correction,
            "zero/fixture/type gate not satisfied",
            correction_type=None,
            enabled=False,
        )
        _skip_atom(
            records,
            B_atom_correction_cmu_measure_data,
            "zero/fixture/type gate not satisfied",
            correction_type=None,
            channel=channel,
        )
        _skip_atom(
            records,
            B_atom_correction_cmu_set_correction,
            "zero/fixture/type gate not satisfied",
            correction_type=None,
            enabled=True,
        )
    return _b_flow_response(
        "B_flow_correction_cmu_open_short_load",
        "correction",
        "cmu",
        "open_short_load",
        records,
        "CMU open/short/load correction capture with fixture acknowledgement required.",
        destructive=True,
        fixture_sensitive=True,
        operator_ack_required=False,
        ok=gate_ok and not warnings,
        partial=partial,
        inputs={
            "channel": channel,
            "correction_types": correction_types,
            "confirm_timeout_s": confirm_timeout_s,
            "clear_existing": clear_existing,
            "fixture_condition_ack": fixture_condition_ack,
        },
        outputs={
            "zero_confirmed": confirmed,
            "correction_types_processed": parsed_types if gate_ok else [],
        },
        warnings=warnings,
    )


def B_flow_correction_cmu_phase_compensation(
    channel: int,
    mode: str = "auto",
    confirm_timeout_s: float = 5.0,
    fixture_condition_ack: bool = False,
) -> dict:
    """Run gated MFCMU phase compensation after zero/confirm."""
    records: list[dict] = []
    warnings = []
    confirmed = _zero_all_confirm(records, confirm_timeout_s)
    gate_ok = confirmed and fixture_condition_ack
    if not confirmed:
        warnings.append("Zero/confirm prerequisite failed; CMU phase compensation skipped.")
    if not fixture_condition_ack:
        warnings.append("fixture_condition_ack=False; CMU phase compensation skipped.")
    if gate_ok:
        _atom_step(records, B_atom_correction_cmu_set_phase_mode, channel=channel, mode=mode)
        _atom_step(records, B_atom_correction_cmu_perform_phase_comp, channel=channel)
    else:
        _skip_atom(records, B_atom_correction_cmu_set_phase_mode, "zero/fixture gate not satisfied")
        _skip_atom(records, B_atom_correction_cmu_perform_phase_comp, "zero/fixture gate not satisfied")
    return _b_flow_response(
        "B_flow_correction_cmu_phase_compensation",
        "correction",
        "cmu",
        "phase_compensation",
        records,
        "MFCMU phase compensation bracket with fixture/open-terminal acknowledgement.",
        destructive=True,
        fixture_sensitive=True,
        operator_ack_required=False,
        ok=gate_ok,
        partial=not gate_ok,
        inputs={
            "channel": channel,
            "mode": mode,
            "confirm_timeout_s": confirm_timeout_s,
            "fixture_condition_ack": fixture_condition_ack,
        },
        outputs={"zero_confirmed": confirmed, "phase_compensation_performed": gate_ok},
        warnings=warnings,
    )


def B_flow_correction_qscv_offset_cancel(
    channel: int,
    confirm_timeout_s: float = 5.0,
    fixture_condition_ack: bool = False,
) -> dict:
    """Run gated QSCV offset/zero cancellation after zero/confirm."""
    records: list[dict] = []
    warnings = []
    confirmed = _zero_all_confirm(records, confirm_timeout_s)
    gate_ok = confirmed and fixture_condition_ack
    if not confirmed:
        warnings.append("Zero/confirm prerequisite failed; QSCV offset cancel skipped.")
    if not fixture_condition_ack:
        warnings.append("fixture_condition_ack=False; QSCV offset cancel skipped.")
    if gate_ok:
        _atom_step(records, B_atom_correction_qscv_offset_cancel, channel=channel)
    else:
        _skip_atom(records, B_atom_correction_qscv_offset_cancel, "zero/fixture gate not satisfied")
    return _b_flow_response(
        "B_flow_correction_qscv_offset_cancel",
        "correction",
        "qscv",
        "offset_cancel",
        records,
        "QSCV offset/zero cancel precursor; it does not execute a QSCV measurement.",
        destructive=True,
        fixture_sensitive=True,
        operator_ack_required=False,
        ok=gate_ok,
        partial=not gate_ok,
        inputs={
            "channel": channel,
            "confirm_timeout_s": confirm_timeout_s,
            "fixture_condition_ack": fixture_condition_ack,
        },
        outputs={"zero_confirmed": confirmed, "offset_cancel_performed": gate_ok},
        warnings=warnings,
    )


def B_flow_correction_easyexpert_zero_cancel(
    channel: str = "all",
    disable_before_measure: bool = False,
    measure_zero_cancel: bool = False,
    fixture_condition_ack: bool = False,
    operator_ack: bool = False,
) -> dict:
    """Query, optionally refresh, enable, and re-query EasyEXPERT zero cancel state."""
    flow = "B_flow_correction_easyexpert_zero_cancel"
    records: list[dict] = []
    warnings = _operator_warning(flow, True, operator_ack)
    initial = _atom_step(
        records,
        B_atom_calibration_easyexpert_query_zero_cancel_state,
        channel=channel,
    )
    partial = False
    measurement_performed = False
    if disable_before_measure:
        _atom_step(records, B_atom_calibration_easyexpert_zero_cancel_off, channel=channel)
    else:
        _skip_atom(
            records,
            B_atom_calibration_easyexpert_zero_cancel_off,
            "disable_before_measure=False",
            channel=channel,
        )
    if measure_zero_cancel and fixture_condition_ack:
        _atom_step(records, B_atom_calibration_easyexpert_measure_zero_cancel, channel=channel)
        measurement_performed = True
    elif measure_zero_cancel:
        partial = True
        warnings.append(
            "fixture_condition_ack=False; EasyEXPERT zero-cancel measurement skipped."
        )
        _skip_atom(
            records,
            B_atom_calibration_easyexpert_measure_zero_cancel,
            "fixture_condition_ack=False",
            channel=channel,
        )
    else:
        _skip_atom(
            records,
            B_atom_calibration_easyexpert_measure_zero_cancel,
            "measure_zero_cancel=False",
            channel=channel,
        )
    _atom_step(records, B_atom_calibration_easyexpert_zero_cancel_on, channel=channel)
    final = _atom_step(
        records,
        B_atom_calibration_easyexpert_query_zero_cancel_state,
        channel=channel,
    )
    return _b_flow_response(
        flow,
        "correction",
        "easyexpert",
        "zero_cancel",
        records,
        "EasyEXPERT zero-cancel calibration/state bracket with optional measurement refresh.",
        destructive=True,
        fixture_sensitive=measure_zero_cancel,
        operator_ack_required=True,
        ok=not partial,
        partial=partial,
        inputs={
            "channel": channel,
            "disable_before_measure": disable_before_measure,
            "measure_zero_cancel": measure_zero_cancel,
            "fixture_condition_ack": fixture_condition_ack,
            "operator_ack": operator_ack,
        },
        outputs={
            "initial_enabled": initial.get("enabled"),
            "final_enabled": final.get("enabled"),
            "measurement_performed": measurement_performed,
        },
        warnings=warnings,
    )


B_FLOW_FUNCTIONS = [
    B_flow_emergency_b1500_abort_zero,
    B_flow_emergency_wgfmu_abort_disconnect,
    B_flow_emergency_easyexpert_abort_standby,
    B_flow_safe_state_b1500_zero_disable,
    B_flow_preflight_b1500_gate,
    B_flow_baseline_b1500_known_state,
    B_flow_baseline_wgfmu_known_state,
    B_flow_baseline_smu_housekeeping,
    B_flow_maintenance_b1500_self_test_calibration,
    B_flow_maintenance_wgfmu_self_test_calibration,
    B_flow_preparation_asu_low_current_path,
    B_flow_preparation_scuu_signal_path,
    B_flow_correction_cmu_open_short_load,
    B_flow_correction_cmu_phase_compensation,
    B_flow_correction_qscv_offset_cancel,
    B_flow_correction_easyexpert_zero_cancel,
]


def register_b_flows(mcp: FastMCP) -> None:
    """Register all B_flow_* tools on a FastMCP instance."""
    for tool in B_FLOW_FUNCTIONS:
        mcp.tool(tool)
