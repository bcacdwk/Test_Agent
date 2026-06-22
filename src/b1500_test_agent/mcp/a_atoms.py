"""A-class fake MCP atom tools."""

from fastmcp import FastMCP

from .common import _fake_response
from .fake_data import _EASYEXPERT_APPS, _FAKE_MODULES


# ---------------------------------------------------------------------------
# A class — flex: connection, communication, status, buffer atoms
# ---------------------------------------------------------------------------


def A_atom_flex_connect(
    gpib_address: int = 17,
    gpib_board: int = 0,
    timeout_ms: int = 600_000,
) -> dict:
    """Open a fake direct B1500A GPIB session and discover identity/modules.

    Basis: B1500A Programming Guide `*IDN?`, `UNT?`; PyVISA/GPIB setup.
    """
    return _fake_response(
        "A_atom_flex_connect",
        ["*IDN?", "UNT?"],
        connected=False,
        gpib_board=gpib_board,
        gpib_address=gpib_address,
        timeout_ms=timeout_ms,
        instrument_id="Keysight Technologies,B1500A,FAKE,0.0",
        modules=_FAKE_MODULES,
        warning="Fake connection only; real PyVISA transport is not implemented.",
    )


def A_atom_flex_disconnect() -> dict:
    """Close a fake direct B1500A session.

    Basis: direct session lifecycle. Real implementation should call B-class
    cleanup before closing transport.
    """
    return _fake_response(
        "A_atom_flex_disconnect",
        ["session.close"],
        connected=False,
        status="fake_disconnected",
        cleanup_note="Call B_atom_output_b1500_zero_all before real disconnect.",
    )


def A_atom_flex_identify() -> dict:
    """Return fake B1500A identity.

    Basis: B1500A Programming Guide `*IDN?`.
    """
    return _fake_response(
        "A_atom_flex_identify",
        ["*IDN?"],
        instrument_id="Keysight Technologies,B1500A,FAKE,0.0",
    )


def A_atom_flex_list_modules() -> dict:
    """Return fake installed B1500A module inventory.

    Basis: B1500A Programming Guide `UNT?`.
    """
    return _fake_response(
        "A_atom_flex_list_modules",
        ["UNT?"],
        modules=_FAKE_MODULES,
        channel_numbering="1-10 primary slot channels; 11-20 secondary channels.",
    )


def A_atom_flex_get_status() -> dict:
    """Return fake B1500A status, errors, module inventory, and settings summary.

    Basis: `UNT?`, `ERRX?`, `*STB?`, `*LRN?`.
    """
    return _fake_response(
        "A_atom_flex_get_status",
        ["UNT?", "ERRX?", "*STB?", "*LRN?"],
        connected=False,
        state="fake_offline",
        modules=_FAKE_MODULES,
        error_queue=[],
        status_byte=0,
        active_channels=[],
        current_settings={"format": "FMT 1,1", "timestamp": "disabled"},
    )


def A_atom_flex_query_settings() -> dict:
    """Return fake current B1500A settings.

    Basis: B1500A Programming Guide `*LRN?`.
    """
    return _fake_response(
        "A_atom_flex_query_settings",
        ["*LRN?"],
        settings={
            "format": "FMT 1,1",
            "timestamp": "disabled",
            "auto_calibration": "enabled",
            "active_channels": [],
        },
    )


def A_atom_flex_query_smu_settings(channel: int = 1, learn_type: int = 0) -> dict:
    """Return fake per-channel SMU source/range/compliance readback.

    Unlike the coarse ``A_atom_flex_query_settings`` (bare ``*LRN?``), this uses
    a ``*LRN? type`` query whose type value selects per-channel SMU state such as
    DV/DI output, measurement range, and compliance. Read-only verification after
    error recovery, recipe transitions, or DUT contact events; matters most for
    HRSMU where the active range sets measurement resolution.

    Basis: B1500A Programming Guide ``*LRN? type`` (types cover SMU output/range/
    compliance).
    """
    return _fake_response(
        "A_atom_flex_query_smu_settings",
        ["*LRN?"],
        channel=channel,
        learn_type=learn_type,
        settings={
            "output": None,
            "source_function": "unknown",
            "measure_range": "unknown",
            "compliance": None,
            "filter": None,
            "series_resistor": None,
        },
        note="Use *LRN? type to read SMU channel state; type map must follow the audited structured table.",
    )


def A_atom_flex_query_compliance_status(channel: int = 1) -> dict:
    """Return fake per-channel SMU compliance reached/polarity status.

    ``LIM?`` reports whether a channel reached its current/voltage compliance and
    ``LOP?`` reports the compliance/output operation side. Lets the agent check
    compliance explicitly without running a measurement cycle, which is important
    for safe MPSMU/HRSMU sourcing (compliance-limited current can indicate the DUT
    is drawing more than expected).

    Basis: B1500A Programming Guide ``LIM?``, ``LOP?``.
    """
    return _fake_response(
        "A_atom_flex_query_compliance_status",
        ["LIM?", "LOP?"],
        channel=channel,
        compliance_reached=False,
        compliance_side="unknown",
        operation="unknown",
        note="Read-only compliance/operation readback; setting compliance limit is B-class (LIM).",
    )


def A_atom_flex_read_error_queue(clear_after_read: bool = False) -> dict:
    """Read fake B1500A error queue.

    Basis: B1500A Programming Guide `ERR?`, `ERRX?`.
    """
    return _fake_response(
        "A_atom_flex_read_error_queue",
        ["ERR?", "ERRX?"],
        clear_after_read=clear_after_read,
        errors=[],
        message="No fake errors queued.",
    )


def A_atom_flex_lookup_error(error_code: int = 0) -> dict:
    """Return fake message text for a B1500A error code.

    Basis: B1500A Programming Guide `EMG? code`.
    """
    return _fake_response(
        "A_atom_flex_lookup_error",
        ["EMG?"],
        error_code=error_code,
        message="No error" if error_code == 0 else "Fake lookup; consult structured error table.",
        coverage="EMG? supports 0-999; use ERRX? for extended errors.",
    )


def A_atom_flex_read_status_byte() -> dict:
    """Return fake B1500A status byte decode.

    Basis: status byte section and `*STB?`.
    """
    return _fake_response(
        "A_atom_flex_read_status_byte",
        ["*STB?"],
        status_byte=0,
        decoded={
            "data_ready_bit0": False,
            "wait_bit1": False,
            "interlock_open_bit3": False,
            "message_available": False,
            "operation_complete": True,
        },
    )


def A_atom_flex_wait_opc(timeout_s: float = 60.0) -> dict:
    """Pretend to wait for current operation completion.

    Basis: `*OPC?`; EasyEXPERT remote also uses `*OPC?` after long operations.
    """
    return _fake_response(
        "A_atom_flex_wait_opc",
        ["*OPC?"],
        timeout_s=timeout_s,
        complete=True,
    )


def A_atom_flex_set_data_format(format_mode: int = 1, output_mode: int = 1) -> dict:
    """Pretend to set B1500A measurement data output format.

    Basis: B1500A Programming Guide `FMT mode[, output]`.
    """
    return _fake_response(
        "A_atom_flex_set_data_format",
        ["FMT"],
        format_mode=format_mode,
        output_mode=output_mode,
        recommended_for_initial_driver=format_mode in {1, 5, 11, 15, 21, 25},
        parser_note="Prefer ASCII formats with status headers until binary parsers are validated.",
    )


def A_atom_flex_configure_timestamp(enabled: bool = True) -> dict:
    """Pretend to enable or disable B1500A timestamp output.

    Basis: B1500A Programming Guide `TSC mode`.
    """
    return _fake_response("A_atom_flex_configure_timestamp", ["TSC"], enabled=enabled)


def A_atom_flex_reset_timestamp() -> dict:
    """Pretend to reset the B1500A timestamp timer.

    Basis: B1500A Programming Guide `TSR`.
    """
    return _fake_response("A_atom_flex_reset_timestamp", ["TSR"], timestamp_s=0.0)


def A_atom_flex_read_timestamp() -> dict:
    """Return a fake B1500A timestamp value.

    Basis: B1500A Programming Guide `TSQ`.
    """
    return _fake_response("A_atom_flex_read_timestamp", ["TSQ"], timestamp_s=0.0)


def A_atom_flex_clear_output_buffer() -> dict:
    """Pretend to clear the B1500A output data buffer.

    Basis: B1500A Programming Guide `BC`.
    """
    return _fake_response(
        "A_atom_flex_clear_output_buffer",
        ["BC"],
        output_buffer_items=0,
        note="This is the measurement output buffer, not the one-response query buffer.",
    )


def A_atom_flex_query_buffer_count() -> dict:
    """Return fake count of data items in the B1500A output data buffer.

    Basis: B1500A Programming Guide `NUB?`.
    """
    return _fake_response(
        "A_atom_flex_query_buffer_count",
        ["NUB?"],
        output_buffer_items=0,
    )


def A_atom_flex_read_output_buffer(max_items: int = 100) -> dict:
    """Return fake measurement output-buffer data.

    Basis: B1500A output data buffer read after `XE` or high-speed spot commands.
    """
    return _fake_response(
        "A_atom_flex_read_output_buffer",
        ["output data buffer read"],
        max_items=max_items,
        items=[],
        parser_note="Real implementation must parse according to FMT mode and status headers.",
    )


def A_atom_flex_configure_srq(enable_mask: int = 0) -> dict:
    """Pretend to configure B1500A service request/status-byte interrupt mask.

    Basis: B1500A Programming Guide `*SRE`.
    """
    return _fake_response(
        "A_atom_flex_configure_srq",
        ["*SRE"],
        enable_mask=enable_mask,
        note="Status byte bit definitions must follow the audited structured table.",
    )


def A_atom_flex_query_spgu_status(channel: int = 1) -> dict:
    """Return fake SPGU execution/output status.

    Basis: B1500A Programming Guide `SPST?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_status",
        ["SPST?"],
        channel=channel,
        status="idle",
        running=False,
        note="Read-only SPGU status readback; pulse setup/execution belongs to C atoms.",
    )


def A_atom_flex_query_spgu_setup(channel: int = 1) -> dict:
    """Return fake SPGU PG/ALWG and pulse setup readback.

    Includes ``SER?`` (load impedance) because load setting affects the achievable
    output voltage and compensation; verifying it is part of full setup readback.

    Basis: `SIM?`, `SPRM?`, `SPM?`, `SPPER?`, `SPT?`, `SPV?`, `SER?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_setup",
        ["SIM?", "SPRM?", "SPM?", "SPPER?", "SPT?", "SPV?", "SER?"],
        channel=channel,
        setup={
            "operation_mode": "PG",
            "channel_mode": "normal",
            "pulse_mode": "two_level",
            "period_s": 1e-3,
            "delay_s": 0.0,
            "width_s": 1e-6,
            "leading_s": 2e-8,
            "trailing_s": 2e-8,
            "base_v": 0.0,
            "peak_v": 1.0,
            "load_impedance_ohm": 50.0,
        },
        note="Composite A-class readback of SPGU source configuration including load impedance.",
    )


def A_atom_flex_query_spgu_load_impedance(channel: int = 1) -> dict:
    """Return fake SPGU DUT load impedance setting.

    Load impedance (initial 50 ohm) affects output voltage capability and
    SOPC/SOVC compensation. Read-only; setting it is the C atom
    ``C_atom_spgu_set_load_impedance``.

    Basis: B1500A Programming Guide `SER?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_load_impedance",
        ["SER?"],
        channel=channel,
        load_impedance_ohm=50.0,
        note="Read-only load readback; affects achievable pulse voltage.",
    )


def A_atom_flex_query_spgu_trigger_output(channel: int = 1) -> dict:
    """Return fake SPGU trigger-output configuration.

    Read-only counterpart to the C setter ``C_atom_spgu_set_trigger_output``.

    Basis: B1500A Programming Guide `STGP?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_trigger_output",
        ["STGP?"],
        channel=channel,
        port=0,
        enabled=False,
        trigger_type="unknown",
        polarity="positive",
        note="Read-only trigger-output readback.",
    )


def A_atom_flex_query_spgu_open_comp(channel: int = 1) -> dict:
    """Return fake SPGU open-compensation enable/state.

    Read-only counterpart to ``B_atom_correction_spgu_set_open_comp``.

    Basis: B1500A Programming Guide `SOPC?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_open_comp",
        ["SOPC?"],
        channel=channel,
        enabled=False,
        note="Read-only open-compensation readback; setting is B-class (SOPC).",
    )


def A_atom_flex_query_spgu_short_comp(channel: int = 1) -> dict:
    """Return fake SPGU short (voltage) compensation enable/state.

    Read-only counterpart to ``B_atom_correction_spgu_set_short_comp``.

    Basis: B1500A Programming Guide `SOVC?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_short_comp",
        ["SOVC?"],
        channel=channel,
        enabled=False,
        note="Read-only short-compensation readback; setting is B-class (SOVC).",
    )


def A_atom_flex_query_spgu_alwg_pattern(pattern: str = "alwg") -> dict:
    """Return fake SPGU ALWG waveform pattern definition for verification.

    Read-only counterpart to ``C_atom_spgu_create_alwg_pattern``.

    Basis: B1500A Programming Guide `ALW?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_alwg_pattern",
        ["ALW?"],
        pattern=pattern,
        data=[],
        note="Read-only ALWG pattern readback for debug/verification.",
    )


def A_atom_flex_query_spgu_alwg_sequence(channel: int = 1) -> dict:
    """Return fake SPGU ALWG channel/sequence assignment for verification.

    Read-only counterpart to ``C_atom_spgu_add_alwg_sequence``.

    Basis: B1500A Programming Guide `ALS?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_alwg_sequence",
        ["ALS?"],
        channel=channel,
        sequence=[],
        note="Read-only ALWG sequence readback for debug/verification.",
    )


def A_atom_flex_query_spgu_pulse_switch(channel: int = 1) -> dict:
    """Return fake SPGU pulse switch state.

    Basis: B1500A Programming Guide `ODSW?`.
    """
    return _fake_response(
        "A_atom_flex_query_spgu_pulse_switch",
        ["ODSW?"],
        channel=channel,
        enabled=False,
        contact="normally_open",
        note="Read-only relay/switch readback; setting ODSW is a B atom.",
    )


def A_atom_flex_query_selector_status(selector_id: int = 1) -> dict:
    """Return fake module selector status.

    Basis: B1500A Programming Guide `ERS?`.
    """
    return _fake_response(
        "A_atom_flex_query_selector_status",
        ["ERS?"],
        selector_id=selector_id,
        connected=False,
        status="fake_not_detected",
        note="Selector status readback only; path switching belongs to B atoms.",
    )


def A_atom_flex_query_selector_mode(channel: int = 1) -> dict:
    """Return fake module selector mode and SMU/PG selector path readback.

    Basis: B1500A Programming Guide `ERMOD?`, `ERSSP?`.
    """
    return _fake_response(
        "A_atom_flex_query_selector_mode",
        ["ERMOD?", "ERSSP?"],
        channel=channel,
        selector_mode="normal_dio",
        smu_pg_path="open",
        note="Read-only routing verification for selector/SPGU workflows.",
    )


# ---------------------------------------------------------------------------
# A class — flex: MFCMU correction/compensation readback atoms
# ---------------------------------------------------------------------------


def A_atom_flex_query_cmu_correction_status(channel: int = 7) -> dict:
    """Return fake MFCMU open/short/load correction enable state.

    Read-only counterpart to ``B_atom_correction_cmu_set_correction`` (``CORRST``);
    lets the agent verify which corrections are active before a CV measurement.

    Basis: B1500A Programming Guide ``CORRST?``.
    """
    return _fake_response(
        "A_atom_flex_query_cmu_correction_status",
        ["CORRST?"],
        channel=channel,
        open_enabled=False,
        short_enabled=False,
        load_enabled=False,
        note="Read-only; enabling/disabling corrections is B-class (CORRST).",
    )


def A_atom_flex_query_cmu_correction_freq_list(channel: int = 7) -> dict:
    """Return fake list of frequencies that have MFCMU correction data.

    Used to confirm that correction data covers the frequencies used in a sweep
    (the user's range is 1 kHz-1 MHz).

    Basis: B1500A Programming Guide ``CORRL?``.
    """
    return _fake_response(
        "A_atom_flex_query_cmu_correction_freq_list",
        ["CORRL?"],
        channel=channel,
        frequencies_hz=[],
        note="Correction data is frequency-specific; match it to the measurement frequencies.",
    )


def A_atom_flex_query_cmu_correction_data(channel: int = 7, correction_type: str = "open") -> dict:
    """Return fake stored MFCMU correction data for validation/export.

    Basis: B1500A Programming Guide ``CORRDT?``.
    """
    return _fake_response(
        "A_atom_flex_query_cmu_correction_data",
        ["CORRDT?"],
        channel=channel,
        correction_type=correction_type,
        data=[],
        note="Read-only correction-data readback; setting data is B-class (CORRDT).",
    )


def A_atom_flex_query_cmu_load_standard(channel: int = 7) -> dict:
    """Return fake MFCMU load-correction standard reference values.

    Basis: B1500A Programming Guide ``DCORR?``.
    """
    return _fake_response(
        "A_atom_flex_query_cmu_load_standard",
        ["DCORR?"],
        channel=channel,
        standard={"mode": "unknown", "primary": None, "secondary": None},
        note="Read-only load-standard readback; setting the standard is B-class (DCORR).",
    )


# ---------------------------------------------------------------------------
# A class — wgfmu: session, status, error/warning, logging atoms
# ---------------------------------------------------------------------------


def A_atom_wgfmu_open_session(address: str = "GPIB0::17::INSTR") -> dict:
    """Pretend to open a WGFMU instrument-library session.

    Basis: B1530A WGFMU `WGFMU_openSession`.
    """
    return _fake_response(
        "A_atom_wgfmu_open_session",
        ["WGFMU_openSession"],
        address=address,
        connected=False,
    )


def A_atom_wgfmu_close_session() -> dict:
    """Pretend to close a WGFMU instrument-library session.

    Basis: B1530A WGFMU `WGFMU_closeSession`.
    """
    return _fake_response("A_atom_wgfmu_close_session", ["WGFMU_closeSession"], connected=False)


def A_atom_wgfmu_set_timeout(timeout_s: float = 100.0) -> dict:
    """Pretend to set WGFMU session timeout.

    Basis: B1530A WGFMU `WGFMU_setTimeout`.
    """
    return _fake_response("A_atom_wgfmu_set_timeout", ["WGFMU_setTimeout"], timeout_s=timeout_s)


def A_atom_wgfmu_get_channel_ids() -> dict:
    """Return fake WGFMU channel IDs.

    Basis: B1530A WGFMU `WGFMU_getChannelIdSize` / `WGFMU_getChannelIds`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_channel_ids",
        ["WGFMU_getChannelIdSize", "WGFMU_getChannelIds"],
        channel_ids=[501, 502],
        note="WGFMU channel ID convention is slot*100 + channel.",
    )


def A_atom_wgfmu_get_status() -> dict:
    """Return fake overall WGFMU execution status.

    Basis: B1530A WGFMU `WGFMU_getStatus`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_status",
        ["WGFMU_getStatus"],
        status="IDLE",
        note="Overall WGFMU execution status; does not alter waveform or output state.",
    )


def A_atom_wgfmu_get_channel_status(channel_id: int = 501) -> dict:
    """Return fake per-channel WGFMU execution status.

    Basis: B1530A WGFMU `WGFMU_getChannelStatus`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_channel_status",
        ["WGFMU_getChannelStatus"],
        channel_id=channel_id,
        status="IDLE",
        elapsed_time_s=0.0,
        total_time_s=0.0,
    )


def A_atom_wgfmu_clear() -> dict:
    """Pretend to clear WGFMU software setup.

    Basis: B1530A WGFMU `WGFMU_clear`.
    """
    return _fake_response("A_atom_wgfmu_clear", ["WGFMU_clear"], status="fake_cleared")


def A_atom_wgfmu_open_log(file_name: str = "wgfmu.log") -> dict:
    """Pretend to open a WGFMU error/warning log file.

    Basis: B1530A WGFMU `WGFMU_openLogFile`.
    """
    return _fake_response("A_atom_wgfmu_open_log", ["WGFMU_openLogFile"], file_name=file_name)


def A_atom_wgfmu_close_log() -> dict:
    """Pretend to close the WGFMU log file.

    Basis: B1530A WGFMU `WGFMU_closeLogFile`.
    """
    return _fake_response("A_atom_wgfmu_close_log", ["WGFMU_closeLogFile"], closed=True)


def A_atom_wgfmu_read_error() -> dict:
    """Read fake WGFMU error queue entry.

    Basis: B1530A WGFMU `WGFMU_getErrorSize` / `WGFMU_getError`.
    """
    return _fake_response(
        "A_atom_wgfmu_read_error",
        ["WGFMU_getErrorSize", "WGFMU_getError"],
        errors=[],
    )


def A_atom_wgfmu_read_error_summary() -> dict:
    """Read fake WGFMU accumulated error summary.

    Basis: B1530A WGFMU `WGFMU_getErrorSummarySize` / `WGFMU_getErrorSummary`.
    """
    return _fake_response(
        "A_atom_wgfmu_read_error_summary",
        ["WGFMU_getErrorSummarySize", "WGFMU_getErrorSummary"],
        summary="",
    )


def A_atom_wgfmu_set_warning_level(level: str = "NORMAL") -> dict:
    """Pretend to set WGFMU warning level.

    Basis: B1530A WGFMU `WGFMU_setWarningLevel`.
    """
    return _fake_response("A_atom_wgfmu_set_warning_level", ["WGFMU_setWarningLevel"], level=level)


def A_atom_wgfmu_read_warning_summary() -> dict:
    """Read fake WGFMU accumulated warning summary.

    Basis: B1530A WGFMU `WGFMU_getWarningSummarySize` / `WGFMU_getWarningSummary`.
    """
    return _fake_response(
        "A_atom_wgfmu_read_warning_summary",
        ["WGFMU_getWarningSummarySize", "WGFMU_getWarningSummary"],
        summary="",
    )


def A_atom_wgfmu_export_ascii(file_name: str = "wgfmu_setup.csv") -> dict:
    """Pretend to export WGFMU setup summary to CSV for offline verification.

    Basis: B1530A WGFMU `WGFMU_exportAscii`.
    """
    return _fake_response(
        "A_atom_wgfmu_export_ascii",
        ["WGFMU_exportAscii"],
        file_name=file_name,
        note="Exports pattern, event, and sequence setup data to CSV. Essential for debugging.",
    )


def A_atom_wgfmu_get_completed_event_count(channel_id: int = 501) -> dict:
    """Return fake count of completed measurement events on a WGFMU channel.

    Basis: B1530A WGFMU `WGFMU_getCompletedMeasureEventSize`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_completed_event_count",
        ["WGFMU_getCompletedMeasureEventSize"],
        channel_id=channel_id,
        completed=0,
        total=0,
        note="Progress monitoring for long stress/measurement sequences.",
    )


def A_atom_wgfmu_is_event_completed(
    channel_id: int = 501, pattern: str = "", event: str = ""
) -> dict:
    """Check fake WGFMU measurement event completion status.

    Basis: B1530A WGFMU `WGFMU_isMeasureEventCompleted`.
    """
    return _fake_response(
        "A_atom_wgfmu_is_event_completed",
        ["WGFMU_isMeasureEventCompleted"],
        channel_id=channel_id,
        pattern=pattern,
        event=event,
        completed=False,
        data_index=0,
        data_size=0,
    )


def A_atom_wgfmu_get_measure_value_size(channel_id: int = 501) -> dict:
    """Return fake measured vs total measurement data count for a WGFMU channel.

    Distinct from the data-read C atom: this is the size query used to poll progress
    and to compute offsets for partial reads during long stress/reliability runs.

    Basis: B1530A WGFMU `WGFMU_getMeasureValueSize`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_measure_value_size",
        ["WGFMU_getMeasureValueSize"],
        channel_id=channel_id,
        measured=0,
        total=0,
        note="Use measured/total for progress polling and partial-read offsets.",
    )


def A_atom_wgfmu_get_measure_event_info(channel_id: int = 501, measure_id: int = 0) -> dict:
    """Return fake WGFMU measurement-event setup/attributes for preflight checks.

    Reads back pattern/event names, cycle/loop/count/index/length, and the raw
    setMeasureEvent attributes (time/points/interval/average/rdata). Useful for
    validation and partial-read offset calculation.

    Basis: B1530A WGFMU `WGFMU_getMeasureEventSize` / `WGFMU_getMeasureEvent` /
    `WGFMU_getMeasureEvents` / `WGFMU_getMeasureEventAttribute`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_measure_event_info",
        [
            "WGFMU_getMeasureEventSize",
            "WGFMU_getMeasureEvent",
            "WGFMU_getMeasureEvents",
            "WGFMU_getMeasureEventAttribute",
        ],
        channel_id=channel_id,
        measure_id=measure_id,
        events=[],
        note="Event-setup readback for preflight validation and offset math.",
    )


def A_atom_wgfmu_get_measure_times(channel_id: int = 501, max_points: int = 100) -> dict:
    """Return fake WGFMU sequence-level measurement start times.

    Sequence-level timing readback useful for validating measurement timing before
    execute.

    Basis: B1530A WGFMU `WGFMU_getMeasureTimeSize` / `WGFMU_getMeasureTime` /
    `WGFMU_getMeasureTimes`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_measure_times",
        ["WGFMU_getMeasureTimeSize", "WGFMU_getMeasureTime", "WGFMU_getMeasureTimes"],
        channel_id=channel_id,
        max_points=max_points,
        times_s=[],
    )


def A_atom_wgfmu_get_interpolated_force_value(channel_id: int = 501, time_s: float = 0.0) -> dict:
    """Return fake interpolated WGFMU force voltage at an arbitrary time.

    Correlates measured data with the applied waveform (used by the writeResults3
    helper in the Id-Vg example).

    Basis: B1530A WGFMU `WGFMU_getInterpolatedForceValue`.
    """
    return _fake_response(
        "A_atom_wgfmu_get_interpolated_force_value",
        ["WGFMU_getInterpolatedForceValue"],
        channel_id=channel_id,
        time_s=time_s,
        voltage_v=0.0,
        note="Interpolated applied voltage for measured-data correlation.",
    )


def A_atom_wgfmu_wait_until_completed(timeout_s: float = 100.0) -> dict:
    """Pretend to block until all connected WGFMU channels complete.

    A-class synchronization/wait primitive (does not change output state). Errors in
    real use if no sequencer is running or no Fast IV/PG channel is connected.

    Basis: B1530A WGFMU `WGFMU_waitUntilCompleted`.
    """
    return _fake_response(
        "A_atom_wgfmu_wait_until_completed",
        ["WGFMU_waitUntilCompleted"],
        timeout_s=timeout_s,
        complete=True,
        note="Blocking wait; data is ready for read after completion.",
    )


# ---------------------------------------------------------------------------
# A class — easyexpert: remote session, workspace, catalog, result atoms
# ---------------------------------------------------------------------------


def A_atom_easyexpert_identify() -> dict:
    """Return fake EasyEXPERT remote host identity.

    Basis: EasyEXPERT remote common `*IDN?`.
    """
    return _fake_response(
        "A_atom_easyexpert_identify",
        ["EasyEXPERT *IDN?"],
        host="EasyEXPERT-FAKE",
    )


def A_atom_easyexpert_clear_status() -> dict:
    """Pretend to clear EasyEXPERT remote status/error state.

    Basis: EasyEXPERT remote common `*CLS`.
    """
    return _fake_response("A_atom_easyexpert_clear_status", ["EasyEXPERT *CLS"], cleared=True)


def A_atom_easyexpert_wait_opc(timeout_s: float = 60.0) -> dict:
    """Pretend to wait for EasyEXPERT remote operation completion.

    Basis: EasyEXPERT remote common `*OPC?`.
    """
    return _fake_response(
        "A_atom_easyexpert_wait_opc",
        ["EasyEXPERT *OPC?"],
        timeout_s=timeout_s,
        complete=True,
    )


def A_atom_easyexpert_read_system_error() -> dict:
    """Read fake EasyEXPERT remote error queue.

    Basis: EasyEXPERT `:SYSTem:ERRor:NEXT?`.
    """
    return _fake_response(
        "A_atom_easyexpert_read_system_error",
        [":SYSTem:ERRor:NEXT?"],
        code=0,
        message="No error",
    )


def A_atom_easyexpert_list_workspaces() -> dict:
    """Return fake EasyEXPERT workspace catalog.

    Basis: EasyEXPERT `:WORKspace:CATalog?`.
    """
    return _fake_response(
        "A_atom_easyexpert_list_workspaces",
        [":WORKspace:CATalog?"],
        workspaces=["default"],
    )


def A_atom_easyexpert_open_workspace(workspace: str = "default") -> dict:
    """Pretend to open an EasyEXPERT workspace.

    Basis: EasyEXPERT `:WORKspace:OPEN`.
    """
    return _fake_response(
        "A_atom_easyexpert_open_workspace",
        [":WORKspace:OPEN"],
        workspace=workspace,
        opened=False,
    )


def A_atom_easyexpert_close_workspace() -> dict:
    """Pretend to close the active EasyEXPERT workspace.

    Basis: EasyEXPERT `:WORKspace:CLOSe`.
    """
    return _fake_response("A_atom_easyexpert_close_workspace", [":WORKspace:CLOSe"], closed=True)


def A_atom_easyexpert_get_workspace_state() -> dict:
    """Return fake EasyEXPERT workspace state.

    Basis: EasyEXPERT `:WORKspace:STATe?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_workspace_state",
        [":WORKspace:STATe?"],
        state="fake_no_workspace",
    )


def A_atom_easyexpert_get_workspace_name() -> dict:
    """Return fake EasyEXPERT active workspace name.

    Basis: EasyEXPERT `:WORKspace:NAME?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_workspace_name",
        [":WORKspace:NAME?"],
        name=None,
    )


def A_atom_easyexpert_set_result_format(format_name: str = "TEXT") -> dict:
    """Pretend to set EasyEXPERT remote result format.

    Basis: EasyEXPERT `:RESult:FORMat TEXT|XTR`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_result_format",
        [":RESult:FORMat"],
        format=format_name,
        supported=["TEXT", "XTR"],
    )


def A_atom_easyexpert_fetch_result() -> dict:
    """Return fake latest EasyEXPERT remote result block.

    Basis: EasyEXPERT `:RESult:FETch[:LATest]?`.
    """
    return _fake_response(
        "A_atom_easyexpert_fetch_result",
        [":RESult:FETch[:LATest]?"],
        result=None,
        parser_note="Real implementation must parse SCPI definite-length block data.",
    )


def A_atom_easyexpert_list_app_tests() -> dict:
    """Return fake EasyEXPERT application-test catalog.

    Basis: EasyEXPERT `:BENCh:APPlication:CATalog?` and Table 9-1.
    """
    return _fake_response(
        "A_atom_easyexpert_list_app_tests",
        [":BENCh:APPlication:CATalog?"],
        application_tests=_EASYEXPERT_APPS,
    )


def A_atom_easyexpert_select_app_test(test_name: str) -> dict:
    """Pretend to select an EasyEXPERT application-test definition.

    Basis: EasyEXPERT `[:BENCh]:APPlication:SELect "name"`.
    """
    return _fake_response(
        "A_atom_easyexpert_select_app_test",
        [":BENCh:APPlication:SELect"],
        test_name=test_name,
        selected=True,
        note="Software-context selection only; does not execute the test.",
    )


def A_atom_easyexpert_list_preset_groups() -> dict:
    """Return fake EasyEXPERT preset-group catalog.

    Basis: EasyEXPERT `:BENCh:PRESet:CATalog?`.
    """
    return _fake_response(
        "A_atom_easyexpert_list_preset_groups",
        [":BENCh:PRESet:CATalog?"],
        preset_groups=["My Favorite"],
    )


def A_atom_easyexpert_select_preset_group(preset_group: str = "My Favorite") -> dict:
    """Pretend to open/select an EasyEXPERT preset group.

    Basis: EasyEXPERT `[:BENCh]:PRESet:OPEN "name"`.
    """
    return _fake_response(
        "A_atom_easyexpert_select_preset_group",
        [":BENCh:PRESet:OPEN"],
        preset_group=preset_group,
        selected=True,
    )


def A_atom_easyexpert_list_preset_setups(preset_group: str = "My Favorite") -> dict:
    """Return fake EasyEXPERT setup catalog for a preset group.

    Basis: EasyEXPERT `:BENCh:PRESet:SETup:CATalog?`.
    """
    return _fake_response(
        "A_atom_easyexpert_list_preset_setups",
        [":BENCh:PRESet:SETup:CATalog?"],
        preset_group=preset_group,
        setups=[],
    )


def A_atom_easyexpert_select_preset_setup(setup_name: str) -> dict:
    """Pretend to select an EasyEXPERT preset setup.

    Basis: EasyEXPERT `[:BENCh]:PRESet:SETup:SELect "name"`.
    """
    return _fake_response(
        "A_atom_easyexpert_select_preset_setup",
        [":BENCh:PRESet:SETup:SELect"],
        setup_name=setup_name,
        selected=True,
        note="Software-context selection only; does not execute the setup.",
    )


def A_atom_easyexpert_get_selected_name() -> dict:
    """Return fake EasyEXPERT selected setup/test name.

    Basis: EasyEXPERT `[:BENCh][:SELected]:NAME?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_selected_name",
        [":BENCh:SELected:NAME?"],
        selected_name=None,
    )


def A_atom_easyexpert_set_device_tag(device_id: str = "") -> dict:
    """Pretend to set the EasyEXPERT Device ID tag for sample metadata.

    Basis: EasyEXPERT `[:BENCh]:TAG "deviceid"`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_device_tag",
        [":BENCh:TAG"],
        device_id=device_id,
    )


def A_atom_easyexpert_get_device_tag() -> dict:
    """Return fake EasyEXPERT Device ID tag.

    Basis: EasyEXPERT `[:BENCh]:TAG?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_device_tag",
        [":BENCh:TAG?"],
        device_id="",
    )


def A_atom_easyexpert_set_repeat_count(count: int = 1) -> dict:
    """Pretend to set EasyEXPERT measurement repeat count.

    Basis: EasyEXPERT `[:BENCh]:COUNt count`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_repeat_count",
        [":BENCh:COUNt"],
        count=count,
    )


def A_atom_easyexpert_get_repeat_count() -> dict:
    """Return fake EasyEXPERT measurement repeat count.

    Basis: EasyEXPERT `[:BENCh]:COUNt?`.
    """
    return _fake_response(
        "A_atom_easyexpert_get_repeat_count",
        [":BENCh:COUNt?"],
        count=1,
    )


def A_atom_easyexpert_reset_repeat_count() -> dict:
    """Pretend to reset EasyEXPERT repeat count field.

    Basis: EasyEXPERT `[:BENCh]:COUNt:RESet`.
    """
    return _fake_response(
        "A_atom_easyexpert_reset_repeat_count",
        [":BENCh:COUNt:RESet"],
        count=0,
    )


def A_atom_easyexpert_set_app_test_param(param_name: str = "", value: float = 0.0) -> dict:
    """Pretend to set a numeric parameter of the selected EasyEXPERT application test.

    Basis: EasyEXPERT `[:BENCh][:SELected]:NUMBer "param", value`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_app_test_param",
        [":BENCh:SELected:NUMBer"],
        param_name=param_name,
        value=value,
        note="Only works for application-test parameter names; not for classic-test fields.",
    )


def A_atom_easyexpert_set_app_test_string(param_name: str = "", value: str = "") -> dict:
    """Pretend to set a string parameter of the selected EasyEXPERT application test.

    Basis: EasyEXPERT `[:BENCh][:SELected]:STRing "param", "value"`.
    """
    return _fake_response(
        "A_atom_easyexpert_set_app_test_string",
        [":BENCh:SELected:STRing"],
        param_name=param_name,
        value=value,
        note="Used for resource strings like SMU1:HP or string parameters.",
    )


def A_atom_easyexpert_load_setup(format_type: str = "XTS") -> dict:
    """Pretend to load an EasyEXPERT setup from block data.

    Basis: EasyEXPERT `[:BENCh]:LOAD[:SETup] setup`.
    """
    return _fake_response(
        "A_atom_easyexpert_load_setup",
        [":BENCh:LOAD:SETup"],
        format_type=format_type,
        loaded=False,
        note="Real implementation requires SCPI definite-length block encoding of XTS/XTR data.",
    )


A_ATOM_FUNCTIONS = [
    A_atom_flex_connect,
    A_atom_flex_disconnect,
    A_atom_flex_identify,
    A_atom_flex_list_modules,
    A_atom_flex_get_status,
    A_atom_flex_query_settings,
    A_atom_flex_query_smu_settings,
    A_atom_flex_query_compliance_status,
    A_atom_flex_read_error_queue,
    A_atom_flex_lookup_error,
    A_atom_flex_read_status_byte,
    A_atom_flex_wait_opc,
    A_atom_flex_set_data_format,
    A_atom_flex_configure_timestamp,
    A_atom_flex_reset_timestamp,
    A_atom_flex_read_timestamp,
    A_atom_flex_clear_output_buffer,
    A_atom_flex_query_buffer_count,
    A_atom_flex_read_output_buffer,
    A_atom_flex_configure_srq,
    A_atom_flex_query_spgu_status,
    A_atom_flex_query_spgu_setup,
    A_atom_flex_query_spgu_pulse_switch,
    A_atom_flex_query_spgu_load_impedance,
    A_atom_flex_query_spgu_trigger_output,
    A_atom_flex_query_spgu_open_comp,
    A_atom_flex_query_spgu_short_comp,
    A_atom_flex_query_spgu_alwg_pattern,
    A_atom_flex_query_spgu_alwg_sequence,
    A_atom_flex_query_selector_status,
    A_atom_flex_query_selector_mode,
    A_atom_flex_query_cmu_correction_status,
    A_atom_flex_query_cmu_correction_freq_list,
    A_atom_flex_query_cmu_correction_data,
    A_atom_flex_query_cmu_load_standard,
    A_atom_wgfmu_open_session,
    A_atom_wgfmu_close_session,
    A_atom_wgfmu_set_timeout,
    A_atom_wgfmu_get_channel_ids,
    A_atom_wgfmu_get_status,
    A_atom_wgfmu_get_channel_status,
    A_atom_wgfmu_clear,
    A_atom_wgfmu_open_log,
    A_atom_wgfmu_close_log,
    A_atom_wgfmu_read_error,
    A_atom_wgfmu_read_error_summary,
    A_atom_wgfmu_set_warning_level,
    A_atom_wgfmu_read_warning_summary,
    A_atom_wgfmu_export_ascii,
    A_atom_wgfmu_get_completed_event_count,
    A_atom_wgfmu_is_event_completed,
    A_atom_wgfmu_get_measure_value_size,
    A_atom_wgfmu_get_measure_event_info,
    A_atom_wgfmu_get_measure_times,
    A_atom_wgfmu_get_interpolated_force_value,
    A_atom_wgfmu_wait_until_completed,
    A_atom_easyexpert_identify,
    A_atom_easyexpert_clear_status,
    A_atom_easyexpert_wait_opc,
    A_atom_easyexpert_read_system_error,
    A_atom_easyexpert_list_workspaces,
    A_atom_easyexpert_open_workspace,
    A_atom_easyexpert_close_workspace,
    A_atom_easyexpert_get_workspace_state,
    A_atom_easyexpert_get_workspace_name,
    A_atom_easyexpert_set_result_format,
    A_atom_easyexpert_fetch_result,
    A_atom_easyexpert_list_app_tests,
    A_atom_easyexpert_select_app_test,
    A_atom_easyexpert_list_preset_groups,
    A_atom_easyexpert_select_preset_group,
    A_atom_easyexpert_list_preset_setups,
    A_atom_easyexpert_select_preset_setup,
    A_atom_easyexpert_get_selected_name,
    A_atom_easyexpert_set_device_tag,
    A_atom_easyexpert_get_device_tag,
    A_atom_easyexpert_set_repeat_count,
    A_atom_easyexpert_get_repeat_count,
    A_atom_easyexpert_reset_repeat_count,
    A_atom_easyexpert_set_app_test_param,
    A_atom_easyexpert_set_app_test_string,
    A_atom_easyexpert_load_setup,
]


def register_a_atoms(mcp: FastMCP) -> None:
    """Register all A_atom_* tools on a FastMCP instance."""
    for tool in A_ATOM_FUNCTIONS:
        mcp.tool(tool)
