"""B-class fake MCP atom tools."""

from fastmcp import FastMCP

from .common import _fake_response, _parse_channels


# ---------------------------------------------------------------------------
# B class — b1500/smu targets: lifecycle, safety, diagnostic, calibration,
#     policy, output, routing, correction atoms
# ---------------------------------------------------------------------------


def B_atom_lifecycle_b1500_reset() -> dict:
    """Pretend to reset B1500A to initial settings.

    Basis: B1500A Programming Guide `*RST`.
    """
    return _fake_response(
        "B_atom_lifecycle_b1500_reset",
        ["*RST"],
        status="fake_reset_complete",
        caution="Real implementation must not concatenate *RST with other FLEX commands.",
    )


def B_atom_lifecycle_b1500_initialize() -> dict:
    """Pretend to initialize B1500A state.

    Basis: B1500A Programming Guide `IN`.
    """
    return _fake_response("B_atom_lifecycle_b1500_initialize", ["IN"], status="fake_initialized")


def B_atom_safety_b1500_abort() -> dict:
    """Pretend to abort the active operation.

    Basis: B1500A Programming Guide `AB`.
    """
    return _fake_response(
        "B_atom_safety_b1500_abort",
        ["AB"],
        status="fake_aborted",
        caution="Real implementation should follow abort with safe cleanup and error readback.",
    )


def B_atom_diagnostic_b1500_self_test() -> dict:
    """Return fake B1500A self-test result.

    Basis: B1500A Programming Guide `*TST?`.
    """
    return _fake_response("B_atom_diagnostic_b1500_self_test", ["*TST?"], result_code=0, passed=True)


def B_atom_calibration_b1500_self_calibration() -> dict:
    """Return fake B1500A self-calibration result.

    Basis: B1500A Programming Guide `*CAL?`.
    """
    return _fake_response(
        "B_atom_calibration_b1500_self_calibration",
        ["*CAL?"],
        result_code=0,
        passed=True,
        caution="Real calibration should be scheduled and recorded in metadata.",
    )


def B_atom_diagnostic_b1500_diagnostics(item: int = 0) -> dict:
    """Return fake B1500A diagnostics result.

    Basis: B1500A Programming Guide `DIAG? item`.
    """
    return _fake_response("B_atom_diagnostic_b1500_diagnostics", ["DIAG?"], item=item, result_code=0, passed=True)


def B_atom_policy_b1500_set_auto_calibration(enabled: bool) -> dict:
    """Pretend to set B1500A auto-calibration policy.

    Basis: B1500A Programming Guide `CM`.
    """
    return _fake_response(
        "B_atom_policy_b1500_set_auto_calibration",
        ["CM"],
        enabled=enabled,
        caution="Long batch jobs should make auto-calibration policy explicit.",
    )


def B_atom_output_b1500_enable_channels(channels: str) -> dict:
    """Pretend to enable source/measurement channels.

    Basis: B1500A Programming Guide `CN ch1[,ch2,...]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "B_atom_output_b1500_enable_channels",
        ["CN"],
        channels=parsed,
        outputs_enabled=bool(parsed),
        caution="Real implementation must validate module installation and role before CN.",
    )


def B_atom_output_b1500_disable_channels(channels: str = "") -> dict:
    """Pretend to disable selected or all source/measurement channels.

    Basis: B1500A Programming Guide `CL [ch1,ch2,...]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "B_atom_output_b1500_disable_channels",
        ["CL"],
        channels=parsed or "all",
        outputs_enabled=False,
    )


def B_atom_output_b1500_zero_outputs(channels: str = "") -> dict:
    """Pretend to force selected or all channels to 0 V.

    Basis: B1500A Programming Guide `DZ [ch]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response("B_atom_output_b1500_zero_outputs", ["DZ"], channels=parsed or "all", status="fake_zeroed")


def B_atom_output_b1500_zero_all() -> dict:
    """Pretend to force all outputs to 0 V and disable all channels.

    Basis: B1500A Programming Guide `DZ` and `CL`.
    """
    return _fake_response(
        "B_atom_output_b1500_zero_all",
        ["DZ", "CL"],
        status="fake_zeroed_and_disabled",
        outputs_enabled=False,
        channels="all",
    )


def B_atom_output_b1500_confirm_zero(timeout_s: float = 5.0) -> dict:
    """Pretend to confirm all outputs are within the zero-voltage threshold.

    Basis: B1500A Programming Guide `WZ? [timeout]`.
    """
    return _fake_response("B_atom_output_b1500_confirm_zero", ["WZ?"], timeout_s=timeout_s, within_2v=True)


def B_atom_safety_b1500_check_interlock() -> dict:
    """Return fake high-voltage interlock state.

    Basis: B1500A design safety notes and `INTLKVTH?` reference.
    """
    return _fake_response(
        "B_atom_safety_b1500_check_interlock",
        ["INTLKVTH?"],
        interlock_closed="unknown",
        high_voltage_allowed=False,
        threshold_v=42.0,
    )


def B_atom_safety_b1500_set_interlock_threshold(voltage_v: float = 42.0) -> dict:
    """Pretend to set the high-voltage interlock allowable-voltage threshold.

    Complements the read-only ``B_atom_safety_b1500_check_interlock`` (``INTLKVTH?``)
    with the write side. The real station external limit is +/-42 V, so the safety
    layer should set this explicitly rather than relying on the post-reset default.

    Basis: B1500A Programming Guide ``INTLKVTH voltage``.
    """
    return _fake_response(
        "B_atom_safety_b1500_set_interlock_threshold",
        ["INTLKVTH"],
        threshold_v=voltage_v,
        caution="Interlock threshold is safety-critical; above it, the interlock circuit must be closed.",
    )


def B_atom_safety_b1500_preflight(device_type: str = "unknown", pin_map_known: bool = False) -> dict:
    """Run fake readiness checks before any measurement recipe."""
    checks = [
        {"name": "mcp_server_loaded", "passed": True},
        {"name": "real_transport_available", "passed": False},
        {"name": "pin_map_known", "passed": pin_map_known},
        {"name": "device_type_declared", "passed": device_type != "unknown"},
        {"name": "raw_flex_disabled", "passed": True},
    ]
    return _fake_response(
        "B_atom_safety_b1500_preflight",
        ["UNT?", "ERRX?", "*STB?", "*LRN?", "INTLKVTH?"],
        device_type=device_type,
        passed=all(check["passed"] for check in checks),
        checks=checks,
        next_step="Implement real station profile and PyVISA transport before hardware use.",
    )


def B_atom_output_b1500_recover_zeroed(channels: str = "") -> dict:
    """Pretend to restore channel settings saved by `DZ`.

    Basis: B1500A Programming Guide `RZ [ch]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "B_atom_output_b1500_recover_zeroed",
        ["RZ"],
        channels=parsed or "all",
        status="fake_recovered",
        caution="Real implementation requires a prior DZ; otherwise error 205 is expected.",
    )


def B_atom_output_spgu_enable_channels(channels: str = "1") -> dict:
    """Pretend to enable SPGU output channels.

    Basis: B1500A Programming Guide `CNX ch1[,ch2,...]`.
    """
    parsed = _parse_channels(channels)
    return _fake_response(
        "B_atom_output_spgu_enable_channels",
        ["CNX"],
        channels=parsed,
        outputs_enabled=bool(parsed),
        caution="Real implementation must verify SPGU/HVSPGU modules and selector path before CNX.",
    )


def B_atom_output_smu_set_filter(channel: int, enabled: bool = False) -> dict:
    """Pretend to set SMU filter state.

    Basis: B1500A Programming Guide `FL`; initial setting table lists SMU filter off.
    """
    return _fake_response(
        "B_atom_output_smu_set_filter",
        ["FL"],
        channel=channel,
        enabled=enabled,
    )


def B_atom_output_smu_set_series_resistor(channel: int, enabled: bool = False) -> dict:
    """Pretend to set SMU series resistor state.

    Basis: B1500A Programming Guide `SSR`; initial setting table lists series resistor off.
    """
    return _fake_response(
        "B_atom_output_smu_set_series_resistor",
        ["SSR"],
        channel=channel,
        enabled=enabled,
    )


def B_atom_output_smu_set_compliance_limit(
    channel: int = 1,
    comp_polarity: str = "auto",
    current_limit_a: float | None = None,
) -> dict:
    """Pretend to set an SMU current compliance polarity/limit.

    ``LIM`` constrains the overall compliance polarity/limit independently of the
    compliance embedded in ``DV``/``DI``/``WV``/``WI``. For leakage-sensitive HRSMU
    work this prevents bipolar compliance search from disturbing the DUT; for MPSMU
    it is a safety-layer guard.

    Basis: B1500A Programming Guide ``LIM chnum,comp_polarity[,current_limit]``
    (ASU/SCUU/SMU conditioning group).
    """
    return _fake_response(
        "B_atom_output_smu_set_compliance_limit",
        ["LIM"],
        channel=channel,
        comp_polarity=comp_polarity,
        current_limit_a=current_limit_a,
        caution="Compliance polarity/limit restricts how the SMU may push current; verify before sourcing.",
    )


def B_atom_output_smu_set_output_switch_type(channel: int = 1, switch_type: str = "normal") -> dict:
    """Pretend to set the SMU output switch type (normal vs trigger-synchronized).

    ``OSX`` provides output-switch control with external-trigger synchronization
    (``OS`` is the obsolete predecessor). Useful for timing-sensitive pulsed MPSMU
    work or synchronized output-on events with an external trigger.

    Basis: B1500A Programming Guide ``OSX`` (``OS`` obsolete), external trigger group.
    """
    return _fake_response(
        "B_atom_output_smu_set_output_switch_type",
        ["OSX", "OS"],
        channel=channel,
        switch_type=switch_type,
        note="OS is obsolete; OSX adds external-trigger synchronized output switching.",
        caution="Output switch changes when/how the channel connects to the DUT.",
    )


def B_atom_calibration_smu_set_adc_zero(enabled: bool = False) -> dict:
    """Pretend to set SMU ADC zero function.

    Basis: B1500A Programming Guide `AZ`; initial setting table lists ADC zero off.
    """
    return _fake_response("B_atom_calibration_smu_set_adc_zero", ["AZ"], enabled=enabled)


def B_atom_routing_asu_set_path(channel: int, path: str = "SMU") -> dict:
    """Pretend to switch ASU path.

    Basis: B1500A Programming Guide `SAP`; initial state is SMU side.
    """
    return _fake_response(
        "B_atom_routing_asu_set_path",
        ["SAP"],
        channel=channel,
        path=path,
        caution="Real implementation must verify ASU topology and DUT safety before switching.",
    )


def B_atom_routing_asu_set_1pa_range(channel: int, enabled: bool = False) -> dict:
    """Pretend to enable/disable ASU 1 pA auto-ranging.

    Basis: B1500A Programming Guide `SAR`.
    """
    return _fake_response(
        "B_atom_routing_asu_set_1pa_range",
        ["SAR"],
        channel=channel,
        enabled=enabled,
    )


def B_atom_routing_asu_set_indicator(channel: int, enabled: bool = True) -> dict:
    """Pretend to set ASU indicator state.

    Basis: B1500A Programming Guide `SAL`.
    """
    return _fake_response(
        "B_atom_routing_asu_set_indicator",
        ["SAL"],
        channel=channel,
        enabled=enabled,
    )


def B_atom_routing_scuu_set_path(channel: int, path_mode: str = "open") -> dict:
    """Pretend to switch SCUU path.

    Basis: B1500A Programming Guide `SSP`; use SSP instead of CN for SCUU modules.
    """
    return _fake_response(
        "B_atom_routing_scuu_set_path",
        ["SSP"],
        channel=channel,
        path_mode=path_mode,
        caution="Real implementation must validate SMU/CMU path and force safe state before switching.",
    )


def B_atom_routing_scuu_set_indicator(channel: int, enabled: bool = True) -> dict:
    """Pretend to set SCUU indicator state.

    Basis: B1500A Programming Guide `SSL`.
    """
    return _fake_response(
        "B_atom_routing_scuu_set_indicator",
        ["SSL"],
        channel=channel,
        enabled=enabled,
    )


def B_atom_routing_spgu_set_pulse_switch(
    channel: int = 1,
    enabled: bool = False,
    contact: str = "normally_open",
    delay_s: float = 0.0,
    width_s: float = 1e-7,
) -> dict:
    """Pretend to set the SPGU pulse output switch (semiconductor relay).

    The pulse switch has its own timing envelope (initial delay 0 s, width 100 ns)
    separate from the SPGU pulse timing.

    Basis: B1500A Programming Guide `ODSW`.
    """
    return _fake_response(
        "B_atom_routing_spgu_set_pulse_switch",
        ["ODSW"],
        channel=channel,
        enabled=enabled,
        contact=contact,
        delay_s=delay_s,
        width_s=width_s,
        caution="ODSW controls the SPGU pulse relay path to the DUT.",
    )


def B_atom_routing_selector_set_mode(mode: int = 0, description: str = "normal_dio") -> dict:
    """Pretend to set the module selector / DIO operation mode.

    Basis: B1500A Programming Guide `ERMOD`.
    """
    return _fake_response(
        "B_atom_routing_selector_set_mode",
        ["ERMOD"],
        mode=mode,
        description=description,
        caution="Selector mode must match the connected selector or expander before ER* routing.",
    )


def B_atom_routing_selector_set_smu_pg_path(channel: int = 1, path: str = "smu") -> dict:
    """Pretend to switch a 16440A SMU/Pulse Generator selector path.

    Basis: B1500A Programming Guide `ERSSP`.
    """
    return _fake_response(
        "B_atom_routing_selector_set_smu_pg_path",
        ["ERSSP"],
        channel=channel,
        path=path,
        caution="Physical relay switching; verify zeroed outputs and DUT topology first.",
    )


def B_atom_routing_dio_set_mode(bit_mask: int = 0, output_mask: int = 0) -> dict:
    """Pretend to set DIO bit direction/mode for relay control.

    Basis: B1500A Programming Guide `ERM`.
    """
    return _fake_response(
        "B_atom_routing_dio_set_mode",
        ["ERM"],
        bit_mask=bit_mask,
        output_mask=output_mask,
        caution="DIO mode changes external relay/trigger control direction.",
    )


def B_atom_output_dio_set_relay_bits(bit_mask: int = 0) -> dict:
    """Pretend to drive external relay control output bits.

    Basis: B1500A Programming Guide `ERC`.
    """
    return _fake_response(
        "B_atom_output_dio_set_relay_bits",
        ["ERC"],
        bit_mask=bit_mask,
        caution="ERC can drive external relay hardware in a real station.",
    )


def B_atom_correction_cmu_set_correction(correction_type: str, enabled: bool = False) -> dict:
    """Pretend to enable/disable CMU open/short/load correction.

    Basis: B1500A Programming Guide `CORRST` / `CORRST?`.
    """
    return _fake_response(
        "B_atom_correction_cmu_set_correction",
        ["CORRST", "CORRST?"],
        correction_type=correction_type,
        enabled=enabled,
        note="OPEN/SHOR/LOAD are CORRST type labels, not standalone commands.",
    )


def B_atom_correction_cmu_measure_data(correction_type: str, channel: int) -> dict:
    """Pretend to measure CMU open/short/load correction data.

    Basis: B1500A Programming Guide `CORR?`.
    """
    return _fake_response(
        "B_atom_correction_cmu_measure_data",
        ["CORR?"],
        correction_type=correction_type,
        channel=channel,
        result_code=0,
        caution="Real implementation must require correct open/short/load fixture condition.",
    )


def B_atom_correction_cmu_set_phase_mode(channel: int, mode: str = "auto") -> dict:
    """Pretend to select MFCMU phase compensation mode.

    Basis: B1500A Programming Guide `ADJ`.
    """
    return _fake_response(
        "B_atom_correction_cmu_set_phase_mode",
        ["ADJ"],
        channel=channel,
        mode=mode,
    )


def B_atom_correction_cmu_perform_phase_comp(channel: int) -> dict:
    """Pretend to perform MFCMU phase compensation.

    Basis: B1500A Programming Guide `ADJ?`.
    """
    return _fake_response(
        "B_atom_correction_cmu_perform_phase_comp",
        ["ADJ?"],
        channel=channel,
        result_code=0,
        caution="Real manual notes open measurement terminals at device side; operation may take about 30 seconds.",
    )


def B_atom_correction_cmu_clear() -> dict:
    """Pretend to clear CMU correction data.

    Basis: B1500A Programming Guide `CLCORR`.
    """
    return _fake_response("B_atom_correction_cmu_clear", ["CLCORR"], cleared=True)


def B_atom_correction_cmu_add_frequency(channel: int = 7, frequency_hz: float = 1e6) -> dict:
    """Pretend to add a frequency to the MFCMU correction data set.

    `CORRL` registers the frequencies at which open/short/load correction data is
    measured by `CORR?`. Correction data is frequency-specific, so the user's test
    frequencies (1 kHz-1 MHz) must be registered before measuring correction data.

    Basis: B1500A Programming Guide `CORRL chnum,freq`.
    """
    return _fake_response(
        "B_atom_correction_cmu_add_frequency",
        ["CORRL"],
        channel=channel,
        frequency_hz=frequency_hz,
        note="Register all measurement frequencies before CORR? so correction covers them.",
    )


def B_atom_correction_cmu_set_load_standard(
    channel: int = 7,
    mode: int = 100,
    primary: float = 50.0,
    secondary: float = 0.0,
) -> dict:
    """Pretend to set MFCMU load-correction standard reference values.

    `DCORR` defines the calibration/reference values (e.g. Cp-G or Z-theta) for the
    load standard, required when using load correction for high-accuracy CV work.

    Basis: B1500A Programming Guide `DCORR chnum,corr,mode,prim,sec`.
    """
    return _fake_response(
        "B_atom_correction_cmu_set_load_standard",
        ["DCORR"],
        channel=channel,
        mode=mode,
        primary=primary,
        secondary=secondary,
        caution="Reference values must match the physical load standard used for correction.",
    )


def B_atom_correction_cmu_set_correction_data(
    channel: int = 7,
    correction_type: str = "open",
    frequency_hz: float = 1e6,
    primary: float = 0.0,
    secondary: float = 0.0,
) -> dict:
    """Pretend to set MFCMU correction data directly (restore without re-measuring).

    `CORRDT` writes correction data for a frequency, allowing a known correction
    state to be restored from previously saved measurements.

    Basis: B1500A Programming Guide `CORRDT chnum,freq,open1,open2,short1,short2,load1,load2`.
    """
    return _fake_response(
        "B_atom_correction_cmu_set_correction_data",
        ["CORRDT"],
        channel=channel,
        correction_type=correction_type,
        frequency_hz=frequency_hz,
        primary=primary,
        secondary=secondary,
        note="Use to restore saved correction data instead of remeasuring open/short/load fixtures.",
    )


def B_atom_correction_cmu_measure_series_resistance(channel: int = 7) -> dict:
    """Pretend to measure SCUU/MFCMU cable series resistance.

    `CORRSER?` performs a series-correction measurement and returns the cable
    series resistance between SMU/SCUU and the MFCMU, needed to compensate cable
    resistance in the user's SCUU-based configuration. It performs an active
    measurement, analogous to `CORR?`, so it is a B-class correction atom.

    Basis: B1500A Programming Guide `CORRSER?`.
    """
    return _fake_response(
        "B_atom_correction_cmu_measure_series_resistance",
        ["CORRSER?"],
        channel=channel,
        result_code=0,
        series_resistance_ohm=None,
        caution="Active measurement; requires the correct SCUU short/series fixture condition.",
    )


def B_atom_correction_qscv_offset_cancel(channel: int) -> dict:
    """Pretend to perform QSCV zero/offset cancellation.

    Basis: B1500A Programming Guide QSCV command group `QSZ`.
    """
    return _fake_response("B_atom_correction_qscv_offset_cancel", ["QSZ"], channel=channel, result_code=0)


def B_atom_correction_spgu_set_open_comp(channel: int = 1, enabled: bool = False) -> dict:
    """Pretend to enable/disable SPGU open (output) compensation.

    `SOPC` enables open compensation of the SPGU output, structurally analogous to
    CMU `CORRST`. Correction state control is B-class by existing convention.

    Basis: B1500A Programming Guide `SOPC` / `SOPC?`.
    """
    return _fake_response(
        "B_atom_correction_spgu_set_open_comp",
        ["SOPC", "SOPC?"],
        channel=channel,
        enabled=enabled,
        note="Open compensation of SPGU output; readback is A-class (SOPC?).",
    )


def B_atom_correction_spgu_set_short_comp(channel: int = 1, enabled: bool = False) -> dict:
    """Pretend to enable/disable SPGU short (voltage) compensation.

    `SOVC` enables short/voltage compensation of the SPGU output, structurally
    analogous to CMU `CORRST`. Correction state control is B-class.

    Basis: B1500A Programming Guide `SOVC` / `SOVC?`.
    """
    return _fake_response(
        "B_atom_correction_spgu_set_short_comp",
        ["SOVC", "SOVC?"],
        channel=channel,
        enabled=enabled,
        note="Short/voltage compensation of SPGU output; readback is A-class (SOVC?).",
    )


def B_atom_correction_spgu_measure_series(channel: int = 1) -> dict:
    """Pretend to measure SPGU output-path series resistance correction.

    `CORRSER?` performs an active series-resistance correction measurement for the
    SPGU output path, used in the reference SPGU calibration workflow. Performs a
    measurement like `CORR?`, so it is a B-class correction atom.

    Basis: B1500A Programming Guide `CORRSER?`.

    Note: `CORRSER?` is also exposed in the MFCMU/SCUU context via
    `B_atom_correction_cmu_measure_series_resistance`; both wrap the same command for
    their respective workflows (intentional per-unit redundancy).
    """
    return _fake_response(
        "B_atom_correction_spgu_measure_series",
        ["CORRSER?"],
        channel=channel,
        result_code=0,
        series_resistance_ohm=None,
        caution="Active correction measurement; requires correct SPGU output-path fixture condition.",
    )


# ---------------------------------------------------------------------------
# B class — wgfmu targets: lifecycle, calibration, diagnostic, policy, output atoms
# ---------------------------------------------------------------------------


def B_atom_lifecycle_wgfmu_initialize() -> dict:
    """Pretend to reset all WGFMU channels.

    Basis: B1530A WGFMU `WGFMU_initialize`.
    """
    return _fake_response("B_atom_lifecycle_wgfmu_initialize", ["WGFMU_initialize"], status="fake_initialized")


def B_atom_calibration_wgfmu_self_calibration() -> dict:
    """Pretend to run WGFMU/mainframe self-calibration.

    Basis: B1530A WGFMU `WGFMU_doSelfCalibration`.
    """
    return _fake_response(
        "B_atom_calibration_wgfmu_self_calibration",
        ["WGFMU_doSelfCalibration"],
        result_code=0,
        detail="fake pass",
        timeout_auto_s=600,
    )


def B_atom_diagnostic_wgfmu_self_test() -> dict:
    """Pretend to run WGFMU/mainframe self-test.

    Basis: B1530A WGFMU `WGFMU_doSelfTest`.
    """
    return _fake_response(
        "B_atom_diagnostic_wgfmu_self_test",
        ["WGFMU_doSelfTest"],
        result_code=0,
        detail="fake pass",
        timeout_auto_s=600,
    )


def B_atom_policy_wgfmu_treat_warnings_as_errors(enabled: bool = False) -> dict:
    """Pretend to set WGFMU warning-as-error policy.

    Basis: B1530A WGFMU `WGFMU_treatWarningsAsErrors`.
    """
    return _fake_response(
        "B_atom_policy_wgfmu_treat_warnings_as_errors",
        ["WGFMU_treatWarningsAsErrors"],
        enabled=enabled,
    )


def B_atom_output_wgfmu_connect(channel_id: int = 501) -> dict:
    """Pretend to enable a WGFMU channel and connected RSU.

    Basis: B1530A WGFMU `WGFMU_connect`.
    """
    return _fake_response(
        "B_atom_output_wgfmu_connect",
        ["WGFMU_connect"],
        channel_id=channel_id,
        connected=False,
        note="Enables WGFMU channel output through RSU. B-class: channel output control.",
    )


def B_atom_output_wgfmu_disconnect(channel_id: int = 501) -> dict:
    """Pretend to disable a WGFMU channel and connected RSU.

    Basis: B1530A WGFMU `WGFMU_disconnect`.
    """
    return _fake_response(
        "B_atom_output_wgfmu_disconnect",
        ["WGFMU_disconnect"],
        channel_id=channel_id,
        connected=False,
        note="Disables WGFMU channel output. B-class: channel output control.",
    )


def B_atom_lifecycle_wgfmu_abort() -> dict:
    """Pretend to stop WGFMU sequencer on all channels.

    Basis: B1530A WGFMU `WGFMU_abort`.
    """
    return _fake_response(
        "B_atom_lifecycle_wgfmu_abort",
        ["WGFMU_abort"],
        status="fake_aborted",
        note="Channels keep output voltage at moment of abort.",
    )


def B_atom_lifecycle_wgfmu_abort_channel(channel_id: int = 501) -> dict:
    """Pretend to stop the WGFMU sequencer on one channel.

    Per-channel abort: stops a single channel while others keep running, important
    for multi-channel reliability where one channel must terminate early. The
    channel keeps its output voltage at the moment of abort.

    Basis: B1530A WGFMU `WGFMU_abortChannel`.
    """
    return _fake_response(
        "B_atom_lifecycle_wgfmu_abort_channel",
        ["WGFMU_abortChannel"],
        channel_id=channel_id,
        status="fake_aborted",
        note="Stops one channel only; it keeps output voltage at moment of abort.",
    )


# ---------------------------------------------------------------------------
# B class — easyexpert targets: safety, output, calibration atoms
# ---------------------------------------------------------------------------


def B_atom_safety_easyexpert_abort_measurement() -> dict:
    """Pretend to abort the selected EasyEXPERT measurement.

    Basis: EasyEXPERT `[:BENCh][:SELected]:ABORt`.
    """
    return _fake_response(
        "B_atom_safety_easyexpert_abort_measurement",
        ["[:BENCh][:SELected]:ABORt"],
        status="fake_aborted",
    )


def B_atom_output_easyexpert_set_standby(enabled: bool = False) -> dict:
    """Pretend to set EasyEXPERT standby state.

    Basis: EasyEXPERT `:STANDby:STATe 0|OFF|1|ON`.
    """
    return _fake_response("B_atom_output_easyexpert_set_standby", [":STANDby:STATe"], enabled=enabled)


def B_atom_calibration_easyexpert_zero_cancel_on(channel: str = "all") -> dict:
    """Pretend to enable EasyEXPERT SMU zero cancel.

    Basis: EasyEXPERT CALibration subsystem `ON` / `ON:ALL`.
    """
    return _fake_response("B_atom_calibration_easyexpert_zero_cancel_on", [":CALibration:...:ON"], channel=channel)


def B_atom_calibration_easyexpert_zero_cancel_off(channel: str = "all") -> dict:
    """Pretend to disable EasyEXPERT SMU zero cancel.

    Basis: EasyEXPERT CALibration subsystem `OFF:ALL`.
    """
    return _fake_response("B_atom_calibration_easyexpert_zero_cancel_off", [":CALibration:...:OFF:ALL"], channel=channel)


def B_atom_calibration_easyexpert_measure_zero_cancel(channel: str = "all") -> dict:
    """Pretend to measure EasyEXPERT SMU zero-cancel data.

    Basis: EasyEXPERT CALibration subsystem `MEASure`.
    """
    return _fake_response(
        "B_atom_calibration_easyexpert_measure_zero_cancel",
        [":CALibration:...:MEASure"],
        channel=channel,
        result_code=0,
    )


def B_atom_calibration_easyexpert_query_zero_cancel_state(channel: str = "all") -> dict:
    """Pretend to query EasyEXPERT SMU zero-cancel state.

    Basis: EasyEXPERT CALibration subsystem `STATe?`.
    """
    return _fake_response(
        "B_atom_calibration_easyexpert_query_zero_cancel_state",
        [":CALibration:...:STATe?"],
        channel=channel,
        enabled=False,
    )


B_ATOM_FUNCTIONS = [
    B_atom_lifecycle_b1500_reset,
    B_atom_lifecycle_b1500_initialize,
    B_atom_safety_b1500_abort,
    B_atom_diagnostic_b1500_self_test,
    B_atom_calibration_b1500_self_calibration,
    B_atom_diagnostic_b1500_diagnostics,
    B_atom_policy_b1500_set_auto_calibration,
    B_atom_output_b1500_enable_channels,
    B_atom_output_b1500_disable_channels,
    B_atom_output_b1500_zero_outputs,
    B_atom_output_b1500_zero_all,
    B_atom_output_b1500_confirm_zero,
    B_atom_safety_b1500_check_interlock,
    B_atom_safety_b1500_set_interlock_threshold,
    B_atom_safety_b1500_preflight,
    B_atom_output_b1500_recover_zeroed,
    B_atom_output_spgu_enable_channels,
    B_atom_output_smu_set_filter,
    B_atom_output_smu_set_series_resistor,
    B_atom_output_smu_set_compliance_limit,
    B_atom_output_smu_set_output_switch_type,
    B_atom_calibration_smu_set_adc_zero,
    B_atom_routing_asu_set_path,
    B_atom_routing_asu_set_1pa_range,
    B_atom_routing_asu_set_indicator,
    B_atom_routing_scuu_set_path,
    B_atom_routing_scuu_set_indicator,
    B_atom_routing_spgu_set_pulse_switch,
    B_atom_routing_selector_set_mode,
    B_atom_routing_selector_set_smu_pg_path,
    B_atom_routing_dio_set_mode,
    B_atom_output_dio_set_relay_bits,
    B_atom_correction_cmu_set_correction,
    B_atom_correction_cmu_measure_data,
    B_atom_correction_cmu_set_phase_mode,
    B_atom_correction_cmu_perform_phase_comp,
    B_atom_correction_cmu_clear,
    B_atom_correction_cmu_add_frequency,
    B_atom_correction_cmu_set_load_standard,
    B_atom_correction_cmu_set_correction_data,
    B_atom_correction_cmu_measure_series_resistance,
    B_atom_correction_qscv_offset_cancel,
    B_atom_correction_spgu_set_open_comp,
    B_atom_correction_spgu_set_short_comp,
    B_atom_correction_spgu_measure_series,
    B_atom_lifecycle_wgfmu_initialize,
    B_atom_calibration_wgfmu_self_calibration,
    B_atom_diagnostic_wgfmu_self_test,
    B_atom_policy_wgfmu_treat_warnings_as_errors,
    B_atom_output_wgfmu_connect,
    B_atom_output_wgfmu_disconnect,
    B_atom_lifecycle_wgfmu_abort,
    B_atom_lifecycle_wgfmu_abort_channel,
    B_atom_safety_easyexpert_abort_measurement,
    B_atom_output_easyexpert_set_standby,
    B_atom_calibration_easyexpert_zero_cancel_on,
    B_atom_calibration_easyexpert_zero_cancel_off,
    B_atom_calibration_easyexpert_measure_zero_cancel,
    B_atom_calibration_easyexpert_query_zero_cancel_state,
]


def register_b_atoms(mcp: FastMCP) -> None:
    """Register all B_atom_* tools on a FastMCP instance."""
    for tool in B_ATOM_FUNCTIONS:
        mcp.tool(tool)
