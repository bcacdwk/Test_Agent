"""C-class fake MCP atom tools for measurement/source primitives."""

from fastmcp import FastMCP

from .common import _fake_response
from .fake_data import _SMU_RANGE_HINTS, _SYSTEM_LIMITS


_C_FAKE_WARNING = (
    "Fake C atom only; no real B1500A/WGFMU/EasyEXPERT hardware operation is executed."
)

_SMU_PRE = [
    "A_atom_flex_connect",
    "A_atom_flex_list_modules",
    "B_atom_safety_b1500_preflight",
]
_WGFMU_PRE = [
    "A_atom_wgfmu_open_session",
    "A_atom_wgfmu_get_channel_ids",
    "B_atom_safety_b1500_preflight",
]
_SPGU_PRE = [
    "A_atom_flex_connect",
    "A_atom_flex_query_selector_mode",
    "B_atom_safety_b1500_preflight",
    "B_atom_output_spgu_enable_channels",
    "B_atom_routing_spgu_set_pulse_switch",
]
# Additional preconditions for 16440A SMU/Pulse-Generator-Selector-equipped
# stations: the selector DIO mode and SMU<->PG path must be set before SPGU output.
_SPGU_SELECTOR_PRE = [
    "B_atom_routing_selector_set_mode",
    "B_atom_routing_selector_set_smu_pg_path",
]
_CMU_PRE = [
    "A_atom_flex_connect",
    "A_atom_flex_list_modules",
    "B_atom_safety_b1500_preflight",
]
_HIGH_POWER_PRE = [
    "A_atom_flex_connect",
    "B_atom_safety_b1500_check_interlock",
    "B_atom_safety_b1500_preflight",
]
_EASYEXPERT_PRE = [
    "A_atom_easyexpert_identify",
    "A_atom_easyexpert_get_workspace_state",
    "A_atom_easyexpert_get_selected_name",
]


def _c_response(
    atom: str,
    object_name: str,
    basis: list[str],
    required_preconditions: list[str],
    *,
    caution: str = "",
    **parameters: object,
) -> dict:
    """Build a standard fake C atom response."""
    payload = {
        "class": "C",
        "object": object_name,
        "parameters": parameters,
        "required_preconditions": required_preconditions,
        "warning": _C_FAKE_WARNING,
    }
    if caution:
        payload["caution"] = caution
    return _fake_response(atom, basis, **payload)


# ---------------------------------------------------------------------------
# C class — SMU measurement/source/configuration/execution atoms
# ---------------------------------------------------------------------------


def C_atom_smu_set_measurement_mode(mode: int = 1, channels: str = "1") -> dict:
    """Pretend to set SMU measurement mode and participating channels."""
    return _c_response(
        "C_atom_smu_set_measurement_mode", "smu", ["MM"], _SMU_PRE, mode=mode, channels=channels
    )


def C_atom_smu_set_measurement_operation(channel: int = 1, operation: str = "voltage") -> dict:
    """Pretend to set per-channel SMU measurement/source operation."""
    return _c_response(
        "C_atom_smu_set_measurement_operation",
        "smu",
        ["CMM"],
        _SMU_PRE,
        channel=channel,
        operation=operation,
    )


def C_atom_smu_configure_integration(
    adc: str = "high_resolution",
    integration_time: str = "medium",
    averaging_count: int = 1,
    post_adc_delay_s: float = 0.0,
) -> dict:
    """Pretend to configure SMU ADC/integration/averaging.

    ``adc`` selects the ADC type via ``AAD`` and should be ``"high_speed"`` or
    ``"high_resolution"``. For HRSMU sub-nA / leakage work the high-resolution ADC
    is the recommended choice; ``AIT`` integration-time options depend on ADC type.
    """
    return _c_response(
        "C_atom_smu_configure_integration",
        "smu",
        ["AAD", "AIT", "AV"],
        _SMU_PRE,
        adc=adc,
        integration_time=integration_time,
        averaging_count=averaging_count,
        post_adc_delay_s=post_adc_delay_s,
        adc_choices=["high_speed", "high_resolution"],
        model_hint="HRSMU (B1517A) + high_resolution ADC is recommended for sub-nA/leakage measurements.",
    )


def C_atom_smu_set_measurement_ranging(
    channel: int = 1,
    measure_function: str = "current",
    range_mode: str = "auto",
    range_value: float = 0.0,
    module_type: str = "MPSMU",
) -> dict:
    """Pretend to configure SMU current/voltage measurement ranging.

    ``module_type`` (MPSMU or HRSMU) selects model-specific available ranges so the
    agent picks a valid range: MPSMU bottoms out at 1 nA, while HRSMU reaches 10 pA
    (1 pA with ASU). ``RM`` controls auto/limited-auto ranging behavior.
    """
    range_hint = _SMU_RANGE_HINTS.get(module_type.upper(), _SMU_RANGE_HINTS["MPSMU"])
    return _c_response(
        "C_atom_smu_set_measurement_ranging",
        "smu",
        ["RI", "RV", "RM"],
        _SMU_PRE,
        channel=channel,
        measure_function=measure_function,
        range_mode=range_mode,
        range_value=range_value,
        module_type=module_type,
        range_hint=range_hint,
    )


def C_atom_smu_force_voltage(
    channel: int = 1,
    voltage_v: float = 0.0,
    compliance_a: float = 0.01,
    range_mode: str = "auto",
    comp_polarity: str = "auto",
    irange: float = 0.0,
) -> dict:
    """Pretend to force a DC voltage from an SMU.

    Full ``DV`` syntax is ``DV chnum,vrange,voltage[,Icomp[,comp_polarity[,irange]]]``.
    ``comp_polarity`` constrains the compliance side (auto/positive/negative) and
    ``irange`` selects an explicit compliance current range; both matter for HRSMU
    leakage work where bipolar compliance search must be avoided.
    """
    return _c_response(
        "C_atom_smu_force_voltage",
        "smu",
        ["DV"],
        _SMU_PRE,
        channel=channel,
        voltage_v=voltage_v,
        compliance_a=compliance_a,
        range_mode=range_mode,
        comp_polarity=comp_polarity,
        irange=irange,
        external_max_voltage_v=_SYSTEM_LIMITS["smu"]["external_max_voltage_v"],
        caution="Real DV can bias the DUT; require channel enable, +/-42 V limit, and pin-map validation.",
    )


def C_atom_smu_force_current(
    channel: int = 1,
    current_a: float = 0.0,
    compliance_v: float = 1.0,
    range_mode: str = "auto",
    comp_polarity: str = "auto",
) -> dict:
    """Pretend to force a DC current from an SMU.

    Full ``DI`` syntax is ``DI chnum,irange,current[,Vcomp[,comp_polarity]]``.
    ``range_mode`` maps to ``irange`` and ``comp_polarity`` constrains the voltage
    compliance side (auto/positive/negative).
    """
    return _c_response(
        "C_atom_smu_force_current",
        "smu",
        ["DI"],
        _SMU_PRE,
        channel=channel,
        current_a=current_a,
        compliance_v=compliance_v,
        range_mode=range_mode,
        comp_polarity=comp_polarity,
        external_max_voltage_v=_SYSTEM_LIMITS["smu"]["external_max_voltage_v"],
        caution="Real DI can bias the DUT; require channel enable, limits, and pin-map validation.",
    )


def C_atom_smu_measure_high_speed_spot(
    channel: int = 1,
    measure_type: str = "iv",
    timestamp: bool = True,
) -> dict:
    """Pretend to run an SMU high-speed spot measurement."""
    return _c_response(
        "C_atom_smu_measure_high_speed_spot",
        "smu",
        ["TI", "TV", "TIV", "TTI", "TTV", "TTIV"],
        _SMU_PRE,
        channel=channel,
        measure_type=measure_type,
        timestamp=timestamp,
        sample={"voltage_v": 0.0, "current_a": 0.0, "timestamp_s": 0.0},
    )


def C_atom_smu_configure_staircase_sweep(
    channel: int = 1,
    source: str = "voltage",
    start: float = 0.0,
    stop: float = 1.0,
    steps: int = 11,
    compliance: float = 0.01,
    sweep_type: str = "linear",
    comp_polarity: str = "auto",
) -> dict:
    """Pretend to configure a primary SMU staircase sweep.

    ``WV``/``WI`` support both linear and logarithmic sweeps via ``sweep_type``
    (linear / log_positive / log_negative); log sweeps are common for MOSFET
    sub-threshold Id-Vg (a primary HRSMU use case). ``comp_polarity`` constrains the
    compliance side as in ``DV``/``DI``.
    """
    return _c_response(
        "C_atom_smu_configure_staircase_sweep",
        "smu",
        ["WV", "WI"],
        _SMU_PRE,
        channel=channel,
        source=source,
        start=start,
        stop=stop,
        steps=steps,
        compliance=compliance,
        sweep_type=sweep_type,
        comp_polarity=comp_polarity,
        sweep_type_choices=["linear", "log_positive", "log_negative"],
    )


def C_atom_smu_configure_sweep_timing(
    hold_s: float = 0.0,
    delay_s: float = 0.0,
    step_delay_s: float = 0.0,
    trigger_delay_s: float = 0.0,
    measure_delay_s: float = 0.0,
) -> dict:
    """Pretend to configure SMU sweep timing.

    Full ``WT`` syntax is ``WT hold,delay[,Sdelay[,Tdelay[,Mdelay]]]``:
    ``trigger_delay_s`` is the step source-to-trigger delay (Tdelay) and
    ``measure_delay_s`` is the trigger-to-measurement delay (Mdelay).
    """
    return _c_response(
        "C_atom_smu_configure_sweep_timing",
        "smu",
        ["WT"],
        _SMU_PRE,
        hold_s=hold_s,
        delay_s=delay_s,
        step_delay_s=step_delay_s,
        trigger_delay_s=trigger_delay_s,
        measure_delay_s=measure_delay_s,
    )


def C_atom_smu_execute(operation: str = "configured_measurement", timeout_s: float = 60.0) -> dict:
    """Pretend to execute the currently configured SMU measurement."""
    return _c_response(
        "C_atom_smu_execute",
        "smu",
        ["XE"],
        _SMU_PRE,
        operation=operation,
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_smu_read_measurement_data(max_items: int = 100, format_hint: str = "FMT1") -> dict:
    """Pretend to read and decode SMU measurement data."""
    return _c_response(
        "C_atom_smu_read_measurement_data",
        "smu",
        ["output data buffer read"],
        _SMU_PRE + ["A_atom_flex_set_data_format", "A_atom_flex_query_buffer_count"],
        max_items=max_items,
        format_hint=format_hint,
        rows=[],
        parser_note="C-specific decode wrapper over A-class output-buffer primitives.",
    )


def C_atom_smu_configure_pulse_timing(
    delay_s: float = 0.0,
    width_s: float = 1e-6,
    period_s: float = 1e-3,
) -> dict:
    """Pretend to configure SMU pulse timing."""
    return _c_response(
        "C_atom_smu_configure_pulse_timing",
        "smu",
        ["PT"],
        _SMU_PRE,
        delay_s=delay_s,
        width_s=width_s,
        period_s=period_s,
    )


def C_atom_smu_configure_pulsed_spot_source(
    channel: int = 1,
    source: str = "voltage",
    base: float = 0.0,
    pulse: float = 1.0,
    compliance: float = 0.01,
) -> dict:
    """Pretend to configure an SMU pulsed spot source."""
    return _c_response(
        "C_atom_smu_configure_pulsed_spot_source",
        "smu",
        ["PV", "PI"],
        _SMU_PRE + ["C_atom_smu_configure_pulse_timing"],
        channel=channel,
        source=source,
        base=base,
        pulse=pulse,
        compliance=compliance,
    )


def C_atom_smu_configure_sweep_abort(
    abort_mode: str = "continue",
    post_output: str = "hold",
) -> dict:
    """Pretend to configure SMU sweep abort/post-output behavior."""
    return _c_response(
        "C_atom_smu_configure_sweep_abort",
        "smu",
        ["WM"],
        _SMU_PRE,
        abort_mode=abort_mode,
        post_output=post_output,
    )


def C_atom_smu_configure_synchronous_sweep_source(
    channel: int = 2,
    source: str = "voltage",
    start: float = 0.0,
    stop: float = 1.0,
) -> dict:
    """Pretend to configure a synchronous SMU sweep source."""
    return _c_response(
        "C_atom_smu_configure_synchronous_sweep_source",
        "smu",
        ["WSV", "WSI"],
        _SMU_PRE,
        channel=channel,
        source=source,
        start=start,
        stop=stop,
    )


def C_atom_smu_configure_pulsed_sweep(
    channel: int = 1,
    source: str = "voltage",
    start: float = 0.0,
    stop: float = 1.0,
    steps: int = 11,
) -> dict:
    """Pretend to configure an SMU pulsed sweep."""
    return _c_response(
        "C_atom_smu_configure_pulsed_sweep",
        "smu",
        ["PWV", "PWI"],
        _SMU_PRE + ["C_atom_smu_configure_pulse_timing"],
        channel=channel,
        source=source,
        start=start,
        stop=stop,
        steps=steps,
    )


def C_atom_smu_execute_pulsed_spot(timeout_s: float = 60.0) -> dict:
    """Pretend to execute configured SMU pulsed spot mode."""
    return _c_response(
        "C_atom_smu_execute_pulsed_spot",
        "smu",
        ["MM", "XE"],
        _SMU_PRE + ["C_atom_smu_configure_pulsed_spot_source"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_smu_execute_pulsed_sweep(timeout_s: float = 60.0) -> dict:
    """Pretend to execute configured SMU pulsed sweep mode."""
    return _c_response(
        "C_atom_smu_execute_pulsed_sweep",
        "smu",
        ["MM", "XE"],
        _SMU_PRE + ["C_atom_smu_configure_pulsed_sweep"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_smu_configure_sampling(
    channels: str = "1",
    interval_s: float = 1e-3,
    samples: int = 100,
    source_channel: int = 1,
    mode: str = "linear",
    hold_base_s: float = 0.0,
    post_output: str = "base",
) -> dict:
    """Pretend to configure SMU sampling measurement (MM 10).

    ``mode`` selects linear vs logarithmic sampling (``ML``), ``hold_base_s`` is the
    base-source hold time before sampling (``MT``), and ``post_output`` sets the
    source output after sampling completes (``MSP``: base / bias / start).
    """
    return _c_response(
        "C_atom_smu_configure_sampling",
        "smu",
        ["MCC", "ML", "MT", "MSC", "MI", "MV", "MSP"],
        _SMU_PRE,
        channels=channels,
        interval_s=interval_s,
        samples=samples,
        source_channel=source_channel,
        mode=mode,
        hold_base_s=hold_base_s,
        post_output=post_output,
        mode_choices=["linear", "log"],
        post_output_choices=["base", "bias", "start"],
    )


def C_atom_smu_execute_sampling(timeout_s: float = 60.0) -> dict:
    """Pretend to execute configured SMU sampling mode."""
    return _c_response(
        "C_atom_smu_execute_sampling",
        "smu",
        ["MM", "XE"],
        _SMU_PRE + ["C_atom_smu_configure_sampling"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_smu_configure_multi_sweep(
    channels: str = "1,2",
    primary_channel: int = 1,
    steps: int = 11,
) -> dict:
    """Pretend to configure multi-channel SMU sweep settings."""
    return _c_response(
        "C_atom_smu_configure_multi_sweep",
        "smu",
        ["WNX"],
        _SMU_PRE,
        channels=channels,
        primary_channel=primary_channel,
        steps=steps,
    )


def C_atom_smu_configure_multi_pulsed(
    channels: str = "1,2",
    mode: str = "pulsed_spot",
    pulse_width_s: float = 1e-6,
) -> dict:
    """Pretend to configure multi-channel pulsed spot/sweep settings."""
    return _c_response(
        "C_atom_smu_configure_multi_pulsed",
        "smu",
        ["MCPT", "MCPNT", "MCPNX", "MCPWS", "MCPWNX"],
        _SMU_PRE,
        channels=channels,
        mode=mode,
        pulse_width_s=pulse_width_s,
    )


def C_atom_smu_configure_quasi_pulse(
    channel: int = 1,
    base_v: float = 0.0,
    peak_v: float = 1.0,
    width_s: float = 1e-6,
) -> dict:
    """Pretend to configure SMU quasi-pulse source settings."""
    return _c_response(
        "C_atom_smu_configure_quasi_pulse",
        "smu",
        ["BD*"],
        _SMU_PRE,
        channel=channel,
        base_v=base_v,
        peak_v=peak_v,
        width_s=width_s,
    )


def C_atom_smu_configure_search(
    channel: int = 1,
    search_type: str = "linear",
    target: float = 0.0,
    limit: float = 1.0,
) -> dict:
    """Pretend to configure SMU linear/binary search measurement."""
    return _c_response(
        "C_atom_smu_configure_search",
        "smu",
        ["LS*", "BS*"],
        _SMU_PRE,
        channel=channel,
        search_type=search_type,
        target=target,
        limit=limit,
    )


def C_atom_smu_configure_signal_monitor(
    channels: str = "1",
    interval_s: float = 1e-6,
    samples: int = 100,
) -> dict:
    """Pretend to configure SMU signal-monitor acquisition."""
    return _c_response(
        "C_atom_smu_configure_signal_monitor",
        "smu",
        ["DSMPL*"],
        _SMU_PRE,
        channels=channels,
        interval_s=interval_s,
        samples=samples,
    )


def C_atom_smu_force_timer_start_voltage(
    channel: int = 1,
    voltage_v: float = 0.0,
    compliance_a: float = 0.01,
) -> dict:
    """Pretend to source voltage using a timer-start variant."""
    return _c_response(
        "C_atom_smu_force_timer_start_voltage",
        "smu",
        ["TDV"],
        _SMU_PRE,
        channel=channel,
        voltage_v=voltage_v,
        compliance_a=compliance_a,
    )


def C_atom_smu_force_timer_start_current(
    channel: int = 1,
    current_a: float = 0.0,
    compliance_v: float = 1.0,
) -> dict:
    """Pretend to source current using a timer-start variant."""
    return _c_response(
        "C_atom_smu_force_timer_start_current",
        "smu",
        ["TDI"],
        _SMU_PRE,
        channel=channel,
        current_a=current_a,
        compliance_v=compliance_v,
    )


def C_atom_smu_configure_qscv(
    channel: int = 1,
    start_v: float = 0.0,
    stop_v: float = 1.0,
    steps: int = 11,
    integration_leak_s: float = 0.0,
    measurement_volt_v: float = 0.1,
) -> dict:
    """Pretend to configure SMU quasi-static CV (MM 13).

    QSCV measures capacitance from SMU charge integration without a CMU. HRSMU is
    ideal here thanks to its low-current resolution for leakage compensation. Setup
    commands cover the QSCV source/timing/measurement group; QSZ offset cancel is a
    B atom (``B_atom_correction_qscv_offset_cancel``).

    Basis: B1500A Programming Guide ``QSV``, ``QST``, ``QSM``, ``QSL``, ``QSO``,
    ``QSC``, ``QSR`` (Quasi-static CV group); MM 13.
    """
    return _c_response(
        "C_atom_smu_configure_qscv",
        "smu",
        ["QSV", "QST", "QSM", "QSL", "QSO", "QSC", "QSR"],
        _SMU_PRE + ["B_atom_correction_qscv_offset_cancel"],
        channel=channel,
        start_v=start_v,
        stop_v=stop_v,
        steps=steps,
        integration_leak_s=integration_leak_s,
        measurement_volt_v=measurement_volt_v,
        note="HRSMU recommended for QSCV leakage compensation; run QSZ offset cancel first.",
    )


def C_atom_smu_execute_qscv(timeout_s: float = 60.0) -> dict:
    """Pretend to execute configured SMU quasi-static CV (MM 13 + XE).

    Basis: B1500A Programming Guide ``MM 13``, ``XE``.
    """
    return _c_response(
        "C_atom_smu_execute_qscv",
        "smu",
        ["MM13", "XE"],
        _SMU_PRE + ["C_atom_smu_configure_qscv"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_smu_configure_staircase_sweep_pulsed_bias(
    sweep_channel: int = 1,
    bias_channel: int = 2,
    sweep_source: str = "voltage",
    start: float = 0.0,
    stop: float = 1.0,
    steps: int = 11,
    bias_base: float = 0.0,
    bias_pulse: float = 1.0,
) -> dict:
    """Pretend to configure a staircase sweep with pulsed bias (MM 5).

    MM 5 combines a staircase sweep on one channel with a pulsed bias on another,
    e.g. MOSFET Id-Vd with pulsed gate bias. Requires pulse timing (``PT``) plus the
    sweep (``WV``/``WI``) and pulsed source (``PV``/``PI``).

    Basis: B1500A Programming Guide ``WV``/``WI``, ``PT``, ``PV``/``PI``; MM 5.
    """
    return _c_response(
        "C_atom_smu_configure_staircase_sweep_pulsed_bias",
        "smu",
        ["WV", "WI", "PT", "PV", "PI"],
        _SMU_PRE + ["C_atom_smu_configure_pulse_timing"],
        sweep_channel=sweep_channel,
        bias_channel=bias_channel,
        sweep_source=sweep_source,
        start=start,
        stop=stop,
        steps=steps,
        bias_base=bias_base,
        bias_pulse=bias_pulse,
        note="Execute via C_atom_smu_set_measurement_mode(5,...) then C_atom_smu_execute.",
    )


def C_atom_smu_set_parallel_measurement(
    channels: str = "1,2",
    enabled: bool = True,
) -> dict:
    """Pretend to enable parallel A/D conversion for multi-channel SMU measurement.

    ``PAD`` enables parallel measurement and ``PCH`` selects participating channels,
    cutting total time for 2xMPSMU + 2xHRSMU multi-channel runs. Conditions:
    high-speed ADC, non-pulsed mode, fixed measurement range.

    Basis: B1500A Programming Guide ``PAD``, ``PCH``.
    """
    return _c_response(
        "C_atom_smu_set_parallel_measurement",
        "smu",
        ["PAD", "PCH"],
        _SMU_PRE,
        channels=channels,
        enabled=enabled,
        constraints="Requires high-speed ADC, non-pulsed mode, and fixed measurement range.",
    )


def C_atom_smu_configure_trigger_io(
    trigger_period_s: float = 0.0,
    input_port: int = 0,
    output_port: int = 0,
    polarity: str = "positive",
    sync_mode: str = "step",
) -> dict:
    """Pretend to configure SMU trigger input/output ports for synchronization.

    Enables synchronized multi-SMU measurements (e.g. gate-sweep MPSMU with
    per-step drain measurement) and SPGU/SMU synchronization (HRSMU leakage read
    after SPGU stress). Trigger configuration directly shapes measurement timing, so
    it is a C-class measurement-setup atom.

    Basis: B1500A Programming Guide ``TGP``, ``TGPC``, ``TGSI``, ``TGSO``,
    ``TGXO``, ``TGMO`` (external trigger group).
    """
    return _c_response(
        "C_atom_smu_configure_trigger_io",
        "smu",
        ["TGP", "TGPC", "TGSI", "TGSO", "TGXO", "TGMO"],
        _SMU_PRE,
        trigger_period_s=trigger_period_s,
        input_port=input_port,
        output_port=output_port,
        polarity=polarity,
        sync_mode=sync_mode,
    )


def C_atom_smu_set_trigger_mode(channels: str = "1", mode: str = "off") -> dict:
    """Pretend to set the SMU trigger function (start/step) per channel.

    ``TM`` enables/disables the trigger function that gates source/measurement
    start and step events. Pairs with ``C_atom_smu_configure_trigger_io``.

    Basis: B1500A Programming Guide ``TM``.
    """
    return _c_response(
        "C_atom_smu_set_trigger_mode",
        "smu",
        ["TM"],
        _SMU_PRE,
        channels=channels,
        mode=mode,
        mode_choices=["off", "start", "step", "start_step"],
    )


def C_atom_smu_configure_high_speed_spot(measurement: str = "current") -> dict:
    """Pretend to configure which high-speed spot measurement is the standard.

    ``HSS`` selects the high-speed spot measurement returned by ``TI``/``TV``/
    ``TIV`` in high-speed ADC mode; configuring it before
    ``C_atom_smu_measure_high_speed_spot`` gives controlled behavior.

    Basis: B1500A Programming Guide ``HSS`` (PDF 434-439 / printed 4-117 to 4-122).
    """
    return _c_response(
        "C_atom_smu_configure_high_speed_spot",
        "smu",
        ["HSS"],
        _SMU_PRE,
        measurement=measurement,
        measurement_choices=["current", "voltage", "current_voltage"],
    )


# ---------------------------------------------------------------------------
# C class — WGFMU measurement/source/waveform atoms
# ---------------------------------------------------------------------------


_WGFMU_MAX_PULSE_V = _SYSTEM_LIMITS["wgfmu"]["max_pulse_voltage_v"]
_WGFMU_NO_COMPLIANCE = "WGFMU has no output current limiter (no compliance); guard the DUT externally."


def C_atom_wgfmu_set_operation_mode(channel_id: int = 501, mode: str = "fast_iv") -> dict:
    """Pretend to set WGFMU channel operation mode.

    ``mode`` maps to API constants DC=2000, FASTIV=2001, PG=2002, SMU=2003. Current
    measurement requires Fast IV or DC mode. PG mode is VFVM only and divides output
    through the 50 ohm source/load impedance; force range in PG mode is 3 V or 5 V
    (the +/-10 V range is not available in PG).

    Basis: B1530A WGFMU ``WGFMU_setOperationMode``.
    """
    return _c_response(
        "C_atom_wgfmu_set_operation_mode",
        "wgfmu",
        ["WGFMU_setOperationMode"],
        _WGFMU_PRE,
        channel_id=channel_id,
        mode=mode,
        mode_constants={"dc": 2000, "fast_iv": 2001, "pg": 2002, "smu": 2003},
        max_pulse_voltage_v=_WGFMU_MAX_PULSE_V,
        caution=_WGFMU_NO_COMPLIANCE,
    )


def C_atom_wgfmu_configure_force_measure_ranges(
    channel_id: int = 501,
    force_range: str = "auto",
    measure_range: str = "auto",
) -> dict:
    """Pretend to configure WGFMU force voltage range and measure current range.

    ``force_range`` constants: AUTO=3000, 3V=3001, 5V=3002, -10V=3003, +10V=3004
    (PG mode only supports 3V/5V). ``measure_range`` (current) constants:
    1uA=6001, 10uA=6002, 100uA=6003, 1mA=6004, 10mA=6005. Measurement *mode* and
    *voltage* range are set by ``C_atom_wgfmu_set_measure_mode`` and
    ``C_atom_wgfmu_set_measure_voltage_range``.

    Basis: B1530A WGFMU ``WGFMU_setForceVoltageRange``, ``WGFMU_setMeasureCurrentRange``.
    """
    return _c_response(
        "C_atom_wgfmu_configure_force_measure_ranges",
        "wgfmu",
        ["WGFMU_setForceVoltageRange", "WGFMU_setMeasureCurrentRange"],
        _WGFMU_PRE,
        channel_id=channel_id,
        force_range=force_range,
        measure_range=measure_range,
        force_range_constants={"auto": 3000, "3V": 3001, "5V": 3002, "-10V": 3003, "+10V": 3004},
        current_range_constants={"1uA": 6001, "10uA": 6002, "100uA": 6003, "1mA": 6004, "10mA": 6005},
        max_pulse_voltage_v=_WGFMU_MAX_PULSE_V,
    )


def C_atom_wgfmu_set_measure_mode(channel_id: int = 501, mode: str = "current") -> dict:
    """Pretend to set WGFMU measurement mode (voltage vs current).

    Constants VOLTAGE=4000, CURRENT=4001. CURRENT mode requires Fast IV or DC
    operation mode and auto-sets the voltage range to 5 V.

    Basis: B1530A WGFMU ``WGFMU_setMeasureMode``.
    """
    return _c_response(
        "C_atom_wgfmu_set_measure_mode",
        "wgfmu",
        ["WGFMU_setMeasureMode"],
        _WGFMU_PRE,
        channel_id=channel_id,
        mode=mode,
        mode_constants={"voltage": 4000, "current": 4001},
        note="CURRENT mode requires Fast IV/DC and auto-sets voltage range to 5 V.",
    )


def C_atom_wgfmu_set_measure_voltage_range(channel_id: int = 501, range_v: str = "10V") -> dict:
    """Pretend to set WGFMU voltage measurement range.

    Constants 5V=5001, 10V=5002 (default 10 V). Not effective in current
    measurement mode.

    Basis: B1530A WGFMU ``WGFMU_setMeasureVoltageRange``.
    """
    return _c_response(
        "C_atom_wgfmu_set_measure_voltage_range",
        "wgfmu",
        ["WGFMU_setMeasureVoltageRange"],
        _WGFMU_PRE,
        channel_id=channel_id,
        range_v=range_v,
        range_constants={"5V": 5001, "10V": 5002},
    )


def C_atom_wgfmu_set_measure_enabled(channel_id: int = 501, enabled: bool = True) -> dict:
    """Pretend to enable/disable WGFMU measurement on a channel.

    Constants DISABLE=7000, ENABLE=7001 (default ENABLE). DISABLE prevents
    measurement even if the pattern contains measure events -- used for force-only
    channels in multi-channel setups. Not available in DC mode.

    Basis: B1530A WGFMU ``WGFMU_setMeasureEnabled`` / ``WGFMU_isMeasureEnabled``.
    """
    return _c_response(
        "C_atom_wgfmu_set_measure_enabled",
        "wgfmu",
        ["WGFMU_setMeasureEnabled"],
        _WGFMU_PRE,
        channel_id=channel_id,
        enabled=enabled,
        state_constants={"disable": 7000, "enable": 7001},
    )


def C_atom_wgfmu_set_trigger_out_mode(
    channel_id: int = 501,
    mode: str = "event",
    polarity: str = "positive",
) -> dict:
    """Pretend to set WGFMU trigger output mode and polarity.

    Mode constants DISABLE=8000, START_EXECUTION=8001, START_SEQUENCE=8002,
    START_PATTERN=8003, EVENT=8004; polarity POSITIVE=8100, NEGATIVE=8101. EVENT
    mode is the required prerequisite for ``C_atom_wgfmu_set_trigger_event``.

    Basis: B1530A WGFMU ``WGFMU_setTriggerOutMode``.
    """
    return _c_response(
        "C_atom_wgfmu_set_trigger_out_mode",
        "wgfmu",
        ["WGFMU_setTriggerOutMode"],
        _WGFMU_PRE,
        channel_id=channel_id,
        mode=mode,
        polarity=polarity,
        mode_constants={
            "disable": 8000,
            "start_execution": 8001,
            "start_sequence": 8002,
            "start_pattern": 8003,
            "event": 8004,
        },
        polarity_constants={"positive": 8100, "negative": 8101},
        note="EVENT mode is required before C_atom_wgfmu_set_trigger_event.",
    )


def C_atom_wgfmu_create_pattern(
    pattern: str = "pulse",
    initial_voltage_v: float = 0.0,
    initial_time_s: float = 0.0,
) -> dict:
    """Pretend to create a WGFMU waveform pattern.

    Pattern names must be unique (duplicate raises API error -12). Initial voltage
    must fit the force range at validation time. Max 2048 vectors per pattern.

    Basis: B1530A WGFMU ``WGFMU_createPattern``.
    """
    return _c_response(
        "C_atom_wgfmu_create_pattern",
        "wgfmu",
        ["WGFMU_createPattern"],
        _WGFMU_PRE,
        pattern=pattern,
        initial_voltage_v=initial_voltage_v,
        initial_time_s=initial_time_s,
        max_pulse_voltage_v=_WGFMU_MAX_PULSE_V,
        max_vectors_per_pattern=2048,
        note="Pattern name must be unique; initial voltage must fit the force range.",
    )


def C_atom_wgfmu_add_vectors(
    pattern: str = "pulse",
    delta_time_s: float = 1e-6,
    voltage_v: float = 1.0,
    count: int = 1,
) -> dict:
    """Pretend to append WGFMU waveform vectors (incremental time/voltage).

    ``delta_time_s`` is incremental from the previous vector: range 10 ns to
    10995.116 s at 10 ns resolution (non-10 ns values are rounded). Max 2048 vectors
    per pattern. The 10 ns minimum sets the minimum generated pulse width with no
    measurement; voltage must fit the +/-10 V force envelope.

    Basis: B1530A WGFMU ``WGFMU_addVector`` / ``WGFMU_addVectors``.
    """
    return _c_response(
        "C_atom_wgfmu_add_vectors",
        "wgfmu",
        ["WGFMU_addVector", "WGFMU_addVectors"],
        _WGFMU_PRE + ["C_atom_wgfmu_create_pattern"],
        pattern=pattern,
        delta_time_s=delta_time_s,
        voltage_v=voltage_v,
        count=count,
        d_time_min_s=1e-8,
        d_time_max_s=10995.11627775,
        time_resolution_s=1e-8,
        max_vectors_per_pattern=2048,
        max_pulse_voltage_v=_WGFMU_MAX_PULSE_V,
        caution=_WGFMU_NO_COMPLIANCE,
    )


def C_atom_wgfmu_add_sequence(
    channel_id: int = 501,
    pattern: str = "pulse",
    repeat_count: float = 1,
) -> dict:
    """Pretend to assign a WGFMU pattern to a channel sequence.

    ``repeat_count`` (loop count) ranges 1 to 1,099,511,627,776 (~1e12) and is typed
    as float to avoid overflow; it is rounded to the nearest integer. Max 512
    sequences per channel. No delay between repeats of the same sequence, but a 50 ns
    delay (10 ns last + 40 ns next) occurs between different sequences.

    Basis: B1530A WGFMU ``WGFMU_addSequence`` / ``WGFMU_addSequences``.
    """
    return _c_response(
        "C_atom_wgfmu_add_sequence",
        "wgfmu",
        ["WGFMU_addSequence"],
        _WGFMU_PRE + ["C_atom_wgfmu_create_pattern"],
        channel_id=channel_id,
        pattern=pattern,
        repeat_count=repeat_count,
        loop_count_min=1,
        loop_count_max=1099511627776,
        max_sequences_per_channel=512,
        inter_sequence_delay_s=5e-8,
    )


def C_atom_wgfmu_set_measure_event(
    channel_id: int = 501,
    pattern: str = "pulse",
    event: str = "meas",
    time_s: float = 1e-6,
    points: int = 1,
    interval_s: float = 1e-7,
    average_s: float = 0.0,
    rdata: str = "averaged",
) -> dict:
    """Pretend to define a WGFMU sampling measurement event.

    Full ``setMeasureEvent`` signature is (pattern, event, time, points, interval,
    average, rdata). Constraints: ``interval_s`` 10 ns-1.342 s (10 ns res);
    ``average_s`` 0 or 10 ns-20.97 ms (<= interval, 10 ns res); ``rdata``
    AVERAGED=12000 or RAW=12001. eventEndTime = time + interval*(points-1) + average
    (+10 ns if average=0). Internal sampling is 5 ns; RAW count =
    points*(1 + int(average / 5 ns)). Adjacent events that change averaging need
    >=100 ns between start times. Total stored data is ~4M points/channel (typical).
    The 100 ns minimum measured-pulse width comes from settling + measurement window.

    Basis: B1530A WGFMU ``WGFMU_setMeasureEvent``.
    """
    return _c_response(
        "C_atom_wgfmu_set_measure_event",
        "wgfmu",
        ["WGFMU_setMeasureEvent"],
        _WGFMU_PRE + ["C_atom_wgfmu_create_pattern"],
        channel_id=channel_id,
        pattern=pattern,
        event=event,
        time_s=time_s,
        points=points,
        interval_s=interval_s,
        average_s=average_s,
        rdata=rdata,
        rdata_constants={"averaged": 12000, "raw": 12001},
        interval_min_s=1e-8,
        interval_max_s=1.34217728,
        average_max_s=0.020971512,
        min_pulse_width_with_measure_s=_SYSTEM_LIMITS["wgfmu"]["min_pulse_width_with_measure_s"],
        memory_typical_points_per_channel=4_000_000,
        raw_count_formula="points * (1 + int(average_s / 5ns))",
    )


def C_atom_wgfmu_update(update_mode: str = "apply_and_output_initial") -> dict:
    """Pretend to apply WGFMU setup and initial output voltage."""
    return _c_response(
        "C_atom_wgfmu_update",
        "wgfmu",
        ["WGFMU_update"],
        _WGFMU_PRE,
        update_mode=update_mode,
        caution="WGFMU_update can apply output state on real hardware.",
    )


def C_atom_wgfmu_execute(timeout_s: float = 60.0) -> dict:
    """Pretend to execute the configured WGFMU sequence."""
    return _c_response(
        "C_atom_wgfmu_execute",
        "wgfmu",
        ["WGFMU_execute"],
        _WGFMU_PRE + ["C_atom_wgfmu_update"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_wgfmu_read_measurement_values(
    channel_id: int = 501,
    max_points: int = 100,
) -> dict:
    """Pretend to read WGFMU measurement arrays."""
    return _c_response(
        "C_atom_wgfmu_read_measurement_values",
        "wgfmu",
        ["WGFMU_getMeasureValue", "WGFMU_getMeasureValues"],
        _WGFMU_PRE + ["C_atom_wgfmu_execute"],
        channel_id=channel_id,
        max_points=max_points,
        values=[],
    )


def C_atom_wgfmu_set_vectors(
    pattern: str = "pulse",
    time_s: float = 1e-6,
    voltage_v: float = 1.0,
) -> dict:
    """Pretend to set absolute-time WGFMU waveform vectors."""
    return _c_response(
        "C_atom_wgfmu_set_vectors",
        "wgfmu",
        ["WGFMU_setVector", "WGFMU_setVectors"],
        _WGFMU_PRE + ["C_atom_wgfmu_create_pattern"],
        pattern=pattern,
        time_s=time_s,
        voltage_v=voltage_v,
    )


def C_atom_wgfmu_transform_pattern(
    pattern: str = "pulse",
    operation: str = "offset",
    value: float = 0.0,
) -> dict:
    """Pretend to transform a WGFMU pattern."""
    return _c_response(
        "C_atom_wgfmu_transform_pattern",
        "wgfmu",
        ["WGFMU_mergePatterns", "WGFMU_multiplyPattern", "WGFMU_offsetPattern"],
        _WGFMU_PRE + ["C_atom_wgfmu_create_pattern"],
        pattern=pattern,
        operation=operation,
        value=value,
    )


def C_atom_wgfmu_set_range_event(
    channel_id: int = 501,
    pattern: str = "pulse",
    event: str = "range",
    range_value: str = "10mA",
    time_s: float = 0.0,
) -> dict:
    """Pretend to define a WGFMU current-measurement range-change event.

    Fast IV current measurement only. Current range constants 1uA=6001 .. 10mA=6005.
    Range events must be outside a measurement event's averaging period, and three or
    more consecutive range changes need >2 us spacing. Range change time is < 150 us.

    Basis: B1530A WGFMU ``WGFMU_setRangeEvent``.
    """
    return _c_response(
        "C_atom_wgfmu_set_range_event",
        "wgfmu",
        ["WGFMU_setRangeEvent"],
        _WGFMU_PRE + ["C_atom_wgfmu_create_pattern"],
        channel_id=channel_id,
        pattern=pattern,
        event=event,
        range_value=range_value,
        time_s=time_s,
        current_range_constants={"1uA": 6001, "10uA": 6002, "100uA": 6003, "1mA": 6004, "10mA": 6005},
        consecutive_range_min_spacing_s=2e-6,
        constraints="Must be outside averaging period; >2 us spacing for 3+ consecutive changes.",
    )


def C_atom_wgfmu_set_trigger_event(
    channel_id: int = 501,
    pattern: str = "pulse",
    event: str = "trigger",
    time_s: float = 1e-6,
    duration_s: float = 1e-7,
) -> dict:
    """Pretend to define a WGFMU trigger output event.

    Full signature is ``setTriggerOutEvent(pattern, event, time, duration)``;
    ``duration_s`` is the trigger output pulse width. If time=duration=0 the trigger
    fires when the pattern's initial voltage starts. Requires trigger-out mode EVENT
    (``C_atom_wgfmu_set_trigger_out_mode``).

    Basis: B1530A WGFMU ``WGFMU_setTriggerOutEvent``.
    """
    return _c_response(
        "C_atom_wgfmu_set_trigger_event",
        "wgfmu",
        ["WGFMU_setTriggerOutEvent"],
        _WGFMU_PRE + ["C_atom_wgfmu_create_pattern", "C_atom_wgfmu_set_trigger_out_mode"],
        channel_id=channel_id,
        pattern=pattern,
        event=event,
        time_s=time_s,
        duration_s=duration_s,
    )


def C_atom_wgfmu_configure_force_measure_delay(
    channel_id: int = 501,
    force_delay_s: float = 0.0,
    measure_delay_s: float = 0.0,
) -> dict:
    """Pretend to configure WGFMU force/measurement device delays.

    ``WGFMU_setForceDelay`` and ``WGFMU_setMeasureDelay`` each accept -50 ns to
    +50 ns at 625 ps resolution (values not multiples of 625 ps are rounded). Used to
    align force/measure timing in Fast IV or PG mode.

    Basis: B1530A WGFMU ``WGFMU_setForceDelay``, ``WGFMU_setMeasureDelay``.
    """
    return _c_response(
        "C_atom_wgfmu_configure_force_measure_delay",
        "wgfmu",
        ["WGFMU_setForceDelay", "WGFMU_setMeasureDelay"],
        _WGFMU_PRE,
        channel_id=channel_id,
        force_delay_s=force_delay_s,
        measure_delay_s=measure_delay_s,
        delay_min_s=-5e-8,
        delay_max_s=5e-8,
        delay_resolution_s=6.25e-10,
    )


def C_atom_wgfmu_read_force_values(channel_id: int = 501, max_points: int = 100) -> dict:
    """Pretend to read WGFMU force waveform values."""
    return _c_response(
        "C_atom_wgfmu_read_force_values",
        "wgfmu",
        ["WGFMU_getForceValue", "WGFMU_getForceValues"],
        _WGFMU_PRE,
        channel_id=channel_id,
        max_points=max_points,
        values=[],
    )


def C_atom_wgfmu_dc_force_measure(
    channel_id: int = 501,
    voltage_v: float = 0.0,
    measure_range: str = "auto",
) -> dict:
    """Pretend to perform WGFMU DC force + measure (DC mode).

    Forces DC voltage then reads a single value; the simplified DC flow avoids
    pattern/sequence creation. Requires DC operation mode.

    Basis: B1530A WGFMU ``WGFMU_dcforceVoltage`` + ``WGFMU_dcmeasureValue``.
    """
    return _c_response(
        "C_atom_wgfmu_dc_force_measure",
        "wgfmu",
        ["WGFMU_dcforceVoltage", "WGFMU_dcmeasureValue"],
        _WGFMU_PRE,
        channel_id=channel_id,
        voltage_v=voltage_v,
        measure_range=measure_range,
        measurement={"voltage_v": voltage_v, "current_a": 0.0},
        max_pulse_voltage_v=_WGFMU_MAX_PULSE_V,
        caution=_WGFMU_NO_COMPLIANCE,
    )


def C_atom_wgfmu_dc_measure_value(channel_id: int = 501) -> dict:
    """Pretend to perform a single-point WGFMU DC measurement (non-averaged).

    Reads one voltage or current value (per measure mode) without changing the
    forced output. Requires DC operation mode.

    Basis: B1530A WGFMU ``WGFMU_dcmeasureValue``.
    """
    return _c_response(
        "C_atom_wgfmu_dc_measure_value",
        "wgfmu",
        ["WGFMU_dcmeasureValue"],
        _WGFMU_PRE,
        channel_id=channel_id,
        measurement={"value": 0.0},
        note="Single immediate spot measurement; value is V or A depending on measure mode.",
    )


def C_atom_wgfmu_dc_measure_averaged(
    channel_id: int = 501,
    averaging_count: int = 16,
    points: int = 16,
    interval_ticks: int = 1,
) -> dict:
    """Pretend to perform averaged WGFMU DC measurement (DC mode).

    ``points`` (1-65535) is the sample count and ``interval_ticks`` (1-65535, each
    5 ns) is the sampling interval; the returned value is the average. Requires DC
    operation mode.

    Basis: B1530A WGFMU ``WGFMU_dcmeasureAveragedValue``.
    """
    return _c_response(
        "C_atom_wgfmu_dc_measure_averaged",
        "wgfmu",
        ["WGFMU_dcmeasureAveragedValue"],
        _WGFMU_PRE,
        channel_id=channel_id,
        averaging_count=averaging_count,
        points=points,
        interval_ticks=interval_ticks,
        points_max=65535,
        interval_tick_s=5e-9,
        measurement={"current_a": 0.0},
    )


def C_atom_wgfmu_read_measurement_values_partial(
    channel_id: int = 501,
    event: str = "meas",
    start_index: int = 0,
    count: int = 100,
) -> dict:
    """Pretend to read event-specific partial WGFMU measurement data."""
    return _c_response(
        "C_atom_wgfmu_read_measurement_values_partial",
        "wgfmu",
        ["WGFMU_getMeasureValues"],
        _WGFMU_PRE + ["A_atom_wgfmu_is_event_completed"],
        channel_id=channel_id,
        event=event,
        start_index=start_index,
        count=count,
        values=[],
    )


def C_atom_wgfmu_configure_alwg_cycle(
    channel_id: int = 501,
    pattern: str = "cycle",
    repeat_count: int = 1,
) -> dict:
    """Pretend to configure a WGFMU ALWG-style pattern cycle."""
    return _c_response(
        "C_atom_wgfmu_configure_alwg_cycle",
        "wgfmu",
        ["WGFMU_createPattern", "WGFMU_addSequence"],
        _WGFMU_PRE,
        channel_id=channel_id,
        pattern=pattern,
        repeat_count=repeat_count,
    )


# ---------------------------------------------------------------------------
# C class — SPGU source/pulse atoms
# ---------------------------------------------------------------------------


def C_atom_spgu_set_operation_mode(channel: int = 1, mode: str = "PG") -> dict:
    """Pretend to set SPGU PG/ALWG operation mode."""
    return _c_response(
        "C_atom_spgu_set_operation_mode", "spgu", ["SIM"], _SPGU_PRE, channel=channel, mode=mode
    )


def C_atom_spgu_set_load_impedance(channel: int = 1, load_ohm: float = 50.0) -> dict:
    """Pretend to set the SPGU DUT load impedance (``SER``).

    Load impedance (typically 50 ohm or 1 Mohm) directly shapes the achievable
    output voltage and the SOPC/SOVC compensation calculation, so this is a C-class
    source-configuration atom (analogous to CMU ``IMP``). Read it back with the A
    atom ``A_atom_flex_query_spgu_load_impedance`` (``SER?``).

    Basis: B1500A Programming Guide ``SER``.
    """
    return _c_response(
        "C_atom_spgu_set_load_impedance",
        "spgu",
        ["SER"],
        _SPGU_PRE,
        channel=channel,
        load_ohm=load_ohm,
        note="50 ohm load halves effective output vs 1 Mohm; affects achievable +/-40 V.",
    )


def C_atom_spgu_configure_pg_pulse(
    channel: int = 1,
    pulse_mode: str = "two_level",
    source_number: int = 1,
    period_s: float = 1e-3,
    delay_s: float = 0.0,
    width_s: float = 1e-6,
    leading_s: float = 2e-8,
    trailing_s: float = 2e-8,
    base_v: float = 0.0,
    peak_v: float = 1.0,
    peak2_v: float = 0.0,
) -> dict:
    """Pretend to configure an SPGU pulse generator pulse.

    Full ``SPT`` timing exposes delay, width, leading edge, and trailing edge
    (initial leading/trailing 20 ns) -- needed for NVM/FeFET pulse shaping.
    ``source_number`` selects the pulse source (1 or 2 for two-level; 1/2/3 for
    three-level); ``peak2_v`` is the second peak used in three-level mode. ``SPM``
    sets the output mode (two_level / three_level / alwg).

    Basis: B1500A Programming Guide ``SPM``, ``SPPER``, ``SPT``, ``SPV``, ``SPRM``.
    """
    return _c_response(
        "C_atom_spgu_configure_pg_pulse",
        "spgu",
        ["SPM", "SPPER", "SPT", "SPV", "SPRM"],
        _SPGU_PRE + ["C_atom_spgu_set_operation_mode"],
        channel=channel,
        pulse_mode=pulse_mode,
        source_number=source_number,
        period_s=period_s,
        delay_s=delay_s,
        width_s=width_s,
        leading_s=leading_s,
        trailing_s=trailing_s,
        base_v=base_v,
        peak_v=peak_v,
        peak2_v=peak2_v,
        pulse_mode_choices=["two_level", "three_level", "alwg"],
        max_voltage_v=_SYSTEM_LIMITS["spgu"]["max_voltage_v"],
        caution="Real SPGU pulse levels (+/-40 V max) must be checked against DUT load and selector path.",
    )


def C_atom_spgu_update_output(channel: int = 1) -> dict:
    """Pretend to apply SPGU settings."""
    return _c_response(
        "C_atom_spgu_update_output",
        "spgu",
        ["SPUPD"],
        _SPGU_PRE + ["C_atom_spgu_configure_pg_pulse"],
        channel=channel,
        status="fake_updated",
        caution="SPUPD applies source setup on real hardware.",
    )


def C_atom_spgu_start_output(channel: int = 1, count: int = 0, timeout_s: float = 60.0) -> dict:
    """Pretend to start SPGU pulse output.

    ``count`` selects a limited-run pulse count; ``0`` means free-run until
    explicitly stopped (``C_atom_spgu_stop_output``).

    Basis: B1500A Programming Guide ``SRP``.
    """
    return _c_response(
        "C_atom_spgu_start_output",
        "spgu",
        ["SRP"],
        _SPGU_PRE + _SPGU_SELECTOR_PRE + ["C_atom_spgu_update_output"],
        channel=channel,
        count=count,
        timeout_s=timeout_s,
        status="fake_started",
        caution="SRP starts pulse output on real hardware; count=0 is free-run.",
        selector_note="16440A stations must route the selector to PGU (ERSSP) before SPGU output.",
    )


def C_atom_spgu_stop_output(channel: int = 1) -> dict:
    """Pretend to stop normal SPGU pulse output."""
    return _c_response(
        "C_atom_spgu_stop_output",
        "spgu",
        ["SPP"],
        _SPGU_PRE,
        channel=channel,
        status="fake_stopped",
        caution="Normal run stop only; emergency cleanup remains B-class abort/zero/disable.",
    )


def C_atom_spgu_create_alwg_pattern(
    channel: int = 1,
    pattern: str = "alwg",
    initial_voltage_v: float = 0.0,
    period_s: float = 1e-6,
    levels_v: list[float] | None = None,
) -> dict:
    """Pretend to define an SPGU ALWG pattern.

    ``levels_v`` carries the per-time-slot voltage level array that defines the
    actual ALWG waveform; ``channel`` binds the pattern to a pulse channel.

    Basis: B1500A Programming Guide ``ALW``.
    """
    return _c_response(
        "C_atom_spgu_create_alwg_pattern",
        "spgu",
        ["ALW"],
        _SPGU_PRE + ["C_atom_spgu_set_operation_mode"],
        channel=channel,
        pattern=pattern,
        initial_voltage_v=initial_voltage_v,
        period_s=period_s,
        levels_v=list(levels_v or []),
        max_voltage_v=_SYSTEM_LIMITS["spgu"]["max_voltage_v"],
    )


def C_atom_spgu_add_alwg_sequence(
    channel: int = 1,
    pattern: str = "alwg",
    repeat_count: int = 1,
    loop_start: int = 0,
    loop_count: int = 1,
) -> dict:
    """Pretend to assign an SPGU ALWG pattern sequence.

    ``loop_start``/``loop_count`` express multi-loop sequence control in addition to
    the simple ``repeat_count``.

    Basis: B1500A Programming Guide ``ALS``.
    """
    return _c_response(
        "C_atom_spgu_add_alwg_sequence",
        "spgu",
        ["ALS"],
        _SPGU_PRE + ["C_atom_spgu_create_alwg_pattern"],
        channel=channel,
        pattern=pattern,
        repeat_count=repeat_count,
        loop_start=loop_start,
        loop_count=loop_count,
    )


def C_atom_spgu_configure_sampling_pulse(
    channel: int = 1,
    base_v: float = 0.0,
    pulse_v: float = 1.0,
    width_s: float = 1e-6,
) -> dict:
    """Pretend to configure an SPGU pulse for use within SMU sampling (MM 10).

    ``MSP`` configures the SPGU pulse output that provides pulse bias during an SMU
    sampling measurement. Initial state is cleared.

    Basis: B1500A Programming Guide ``MSP``.
    """
    return _c_response(
        "C_atom_spgu_configure_sampling_pulse",
        "spgu",
        ["MSP"],
        _SPGU_PRE,
        channel=channel,
        base_v=base_v,
        pulse_v=pulse_v,
        width_s=width_s,
        max_voltage_v=_SYSTEM_LIMITS["spgu"]["max_voltage_v"],
        note="Used when SPGU provides pulse bias during SMU sampling (MM 10).",
    )


def C_atom_spgu_set_trigger_output(
    channel: int = 1,
    enabled: bool = False,
    port: int = 0,
    trigger_type: str = "pulse",
    polarity: str = "positive",
) -> dict:
    """Pretend to configure SPGU trigger output tied to pulse execution.

    ``STGP`` exposes the trigger port, trigger type, and polarity in addition to a
    simple enable; needed for synchronized SPGU+SMU NVM read workflows.

    Basis: B1500A Programming Guide ``STGP``.
    """
    return _c_response(
        "C_atom_spgu_set_trigger_output",
        "spgu",
        ["STGP"],
        _SPGU_PRE,
        channel=channel,
        enabled=enabled,
        port=port,
        trigger_type=trigger_type,
        polarity=polarity,
        caution="Trigger output can affect external hardware timing.",
    )


# ---------------------------------------------------------------------------
# C class — CMU capacitance/impedance atoms
# ---------------------------------------------------------------------------


def C_atom_cmu_set_impedance_model(model: str = "Cp-G", channel: int = 7) -> dict:
    """Pretend to set CMU impedance model.

    ``IMP`` takes ``chnum,mode``; ``channel`` is the MFCMU chnum (slot number).
    """
    return _c_response(
        "C_atom_cmu_set_impedance_model", "cmu", ["IMP"], _CMU_PRE, model=model, channel=channel
    )


def C_atom_cmu_configure_signal(
    frequency_hz: float = 1e6,
    ac_level_v: float = 0.03,
    dc_bias_v: float = 0.0,
    channel: int = 7,
) -> dict:
    """Pretend to configure CMU frequency, AC level, and DC bias.

    ``FC``/``ACV``/``DCV`` each take a ``chnum``. Limits below reflect the B1520A
    usable envelope: frequency 1 kHz-1 MHz, internal DC bias +/-25 V (>25 V needs
    the SMU/SCUU path), and AC level ~10-250 mV. Correction data and frequency
    resolution are frequency-band dependent.
    """
    limits = _SYSTEM_LIMITS["mfcmu"]
    return _c_response(
        "C_atom_cmu_configure_signal",
        "cmu",
        ["FC", "ACV", "DCV"],
        _CMU_PRE,
        frequency_hz=frequency_hz,
        ac_level_v=ac_level_v,
        dc_bias_v=dc_bias_v,
        channel=channel,
        min_frequency_hz=limits["min_frequency_hz"],
        max_frequency_hz=limits["max_frequency_hz"],
        max_dc_bias_internal_v=limits["max_dc_bias_internal_v"],
        min_ac_level_v=limits["min_ac_level_v"],
        max_ac_level_v=limits["max_ac_level_v"],
        scuu_note="DC bias beyond +/-25 V (or Kelvin/4-terminal-pair) requires the SMU/SCUU path (SSP).",
        frequency_resolution_note="0.001 Hz (1-10 kHz), 0.01 Hz (10-100 kHz), 0.1 Hz (100 kHz-1 MHz).",
    )


def C_atom_cmu_set_ranging_integration(
    range_mode: str = "auto",
    integration_time: str = "medium",
    channel: int = 7,
    range_value: float = 0.0,
) -> dict:
    """Pretend to configure CMU range and integration time.

    ``RC`` takes ``chnum,range`` (fixed impedance ranges 50 ohm-300 kohm are
    frequency-dependent); ``range_value`` selects a fixed range when ``range_mode``
    is not auto. ``ACT`` sets integration time/averaging.
    """
    return _c_response(
        "C_atom_cmu_set_ranging_integration",
        "cmu",
        ["RC", "ACT"],
        _CMU_PRE,
        range_mode=range_mode,
        integration_time=integration_time,
        channel=channel,
        range_value=range_value,
        range_note="Fixed RC ranges 50, 100, 300, 1k, 3k, 10k, 30k, 100k, 300k ohm; availability is frequency-dependent.",
    )


def C_atom_cmu_set_monitor_output(channel: int = 7, enabled: bool = True) -> dict:
    """Pretend to enable MFCMU AC level / DC bias monitor output (``LMN``).

    ``LMN`` appends the actual oscillator (AC) level and DC bias monitor data to the
    impedance measurement result, letting the agent verify that the applied levels
    match the programmed values (DUT impedance can cause them to differ).

    Basis: B1500A Programming Guide ``LMN`` (MFCMU setup group).
    """
    return _c_response(
        "C_atom_cmu_set_monitor_output",
        "cmu",
        ["LMN"],
        _CMU_PRE,
        channel=channel,
        enabled=enabled,
        note="Adds actual AC level + DC bias monitor data alongside impedance results.",
    )


def C_atom_cmu_read_measurement_data(max_items: int = 100, format_hint: str = "FMT1") -> dict:
    """Pretend to read and decode MFCMU measurement data.

    CMU output differs from SMU data: primary + secondary impedance parameters,
    optional ``LMN`` monitor data, and per-step frequency/bias for sweeps. This is a
    CMU-specific decode wrapper over the A-class output-buffer primitives, parallel
    to ``C_atom_smu_read_measurement_data``.
    """
    return _c_response(
        "C_atom_cmu_read_measurement_data",
        "cmu",
        ["output data buffer read"],
        _CMU_PRE + ["A_atom_flex_set_data_format", "A_atom_flex_query_buffer_count"],
        max_items=max_items,
        format_hint=format_hint,
        rows=[],
        parser_note="Decode primary/secondary impedance params, optional LMN monitor, and sweep frequency/bias.",
    )


def C_atom_cmu_configure_cv_dc_sweep(
    start_v: float = -1.0,
    stop_v: float = 1.0,
    steps: int = 21,
    hold_s: float = 0.0,
    delay_s: float = 0.0,
    step_delay_s: float = 0.0,
    measure_delay_s: float = 0.0,
    abort_mode: str = "continue",
) -> dict:
    """Pretend to configure a DC-bias C-V sweep (MM 18).

    Uses CMU-specific sweep timing (``WTDCV``, which includes a measurement-delay
    ``Mdelay``) and CMU sweep abort (``WMDCV``), not the generic SMU ``WT``/``WM``.
    """
    return _c_response(
        "C_atom_cmu_configure_cv_dc_sweep",
        "cmu",
        ["WDCV", "WTDCV", "WMDCV"],
        _CMU_PRE + ["C_atom_cmu_configure_signal"],
        start_v=start_v,
        stop_v=stop_v,
        steps=steps,
        hold_s=hold_s,
        delay_s=delay_s,
        step_delay_s=step_delay_s,
        measure_delay_s=measure_delay_s,
        abort_mode=abort_mode,
    )


def C_atom_cmu_execute(operation: str = "configured_cmu_measurement", timeout_s: float = 60.0) -> dict:
    """Pretend to execute the configured CMU measurement."""
    return _c_response(
        "C_atom_cmu_execute",
        "cmu",
        ["XE"],
        _CMU_PRE,
        operation=operation,
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_measure_high_speed_spot(
    channel: int = 1,
    timestamp: bool = True,
) -> dict:
    """Pretend to run a high-speed spot C/impedance measurement."""
    return _c_response(
        "C_atom_cmu_measure_high_speed_spot",
        "cmu",
        ["TC", "TTC", "TMACV", "TMDCV"],
        _CMU_PRE,
        channel=channel,
        timestamp=timestamp,
        measurement={"capacitance_f": 0.0, "conductance_s": 0.0, "timestamp_s": 0.0},
    )


def C_atom_cmu_execute_spot_c(timeout_s: float = 60.0) -> dict:
    """Pretend to execute normal Spot C mode."""
    return _c_response(
        "C_atom_cmu_execute_spot_c",
        "cmu",
        ["MM17", "XE"],
        _CMU_PRE + ["C_atom_cmu_configure_signal"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_execute_cv_dc_sweep(timeout_s: float = 60.0) -> dict:
    """Pretend to execute a DC-bias C-V sweep."""
    return _c_response(
        "C_atom_cmu_execute_cv_dc_sweep",
        "cmu",
        ["MM18", "XE"],
        _CMU_PRE + ["C_atom_cmu_configure_cv_dc_sweep"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_configure_cf_sweep(
    start_hz: float = 1e3,
    stop_hz: float = 1e6,
    steps: int = 21,
    hold_s: float = 0.0,
    delay_s: float = 0.0,
    step_delay_s: float = 0.0,
    measure_delay_s: float = 0.0,
    abort_mode: str = "continue",
) -> dict:
    """Pretend to configure a C-f sweep (MM 22).

    Uses C-f-specific sweep timing (``WTFC``) and abort (``WMFC``), not the generic
    SMU ``WT``/``WM``. Default span 1 kHz-1 MHz matches the B1520A usable range.
    """
    return _c_response(
        "C_atom_cmu_configure_cf_sweep",
        "cmu",
        ["WFC", "WTFC", "WMFC"],
        _CMU_PRE + ["C_atom_cmu_configure_signal"],
        start_hz=start_hz,
        stop_hz=stop_hz,
        steps=steps,
        hold_s=hold_s,
        delay_s=delay_s,
        step_delay_s=step_delay_s,
        measure_delay_s=measure_delay_s,
        abort_mode=abort_mode,
        min_frequency_hz=_SYSTEM_LIMITS["mfcmu"]["min_frequency_hz"],
        max_frequency_hz=_SYSTEM_LIMITS["mfcmu"]["max_frequency_hz"],
    )


def C_atom_cmu_execute_cf_sweep(timeout_s: float = 60.0) -> dict:
    """Pretend to execute a C-f sweep."""
    return _c_response(
        "C_atom_cmu_execute_cf_sweep",
        "cmu",
        ["MM22", "XE"],
        _CMU_PRE + ["C_atom_cmu_configure_cf_sweep"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_configure_ac_level_sweep(
    start_v: float = 0.01,
    stop_v: float = 0.1,
    steps: int = 10,
    hold_s: float = 0.0,
    delay_s: float = 0.0,
    step_delay_s: float = 0.0,
    measure_delay_s: float = 0.0,
    abort_mode: str = "continue",
) -> dict:
    """Pretend to configure a CMU AC-level sweep (MM 23).

    Uses AC-level-specific sweep timing (``WTACV``) and abort (``WMACV``) in
    addition to ``WACV``.
    """
    return _c_response(
        "C_atom_cmu_configure_ac_level_sweep",
        "cmu",
        ["WACV", "WTACV", "WMACV"],
        _CMU_PRE + ["C_atom_cmu_configure_signal"],
        start_v=start_v,
        stop_v=stop_v,
        steps=steps,
        hold_s=hold_s,
        delay_s=delay_s,
        step_delay_s=step_delay_s,
        measure_delay_s=measure_delay_s,
        abort_mode=abort_mode,
    )


def C_atom_cmu_execute_ac_level_sweep(timeout_s: float = 60.0) -> dict:
    """Pretend to execute a CMU AC-level sweep (MM 23 + XE)."""
    return _c_response(
        "C_atom_cmu_execute_ac_level_sweep",
        "cmu",
        ["MM23", "XE"],
        _CMU_PRE + ["C_atom_cmu_configure_ac_level_sweep"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_configure_pulsed_spot_c(
    pulse_base_v: float = 0.0,
    pulse_bias_v: float = 1.0,
    pulse_width_s: float = 1e-6,
    pulse_period_s: float = 1e-3,
) -> dict:
    """Pretend to configure pulsed Spot C (MM 19).

    Uses CMU pulse commands ``PTDCV`` (pulse timing) and ``PDCV`` (pulsed DC bias),
    not the SMU ``PT``/``PV`` commands. Requires the impedance model and signal to be
    set first.
    """
    return _c_response(
        "C_atom_cmu_configure_pulsed_spot_c",
        "cmu",
        ["PTDCV", "PDCV"],
        _CMU_PRE + ["C_atom_cmu_set_impedance_model", "C_atom_cmu_configure_signal"],
        pulse_base_v=pulse_base_v,
        pulse_bias_v=pulse_bias_v,
        pulse_width_s=pulse_width_s,
        pulse_period_s=pulse_period_s,
    )


def C_atom_cmu_execute_pulsed_spot_c(timeout_s: float = 60.0) -> dict:
    """Pretend to execute pulsed Spot C (MM 19 + XE)."""
    return _c_response(
        "C_atom_cmu_execute_pulsed_spot_c",
        "cmu",
        ["MM19", "XE"],
        _CMU_PRE + ["C_atom_cmu_configure_pulsed_spot_c"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_configure_pulsed_cv_sweep(
    start_v: float = -1.0,
    stop_v: float = 1.0,
    steps: int = 21,
    pulse_width_s: float = 1e-6,
    pulse_period_s: float = 1e-3,
) -> dict:
    """Pretend to configure a pulsed C-V sweep (MM 20).

    Uses CMU pulse timing ``PTDCV`` (not SMU ``PT``) with ``PWDCV`` pulsed sweep DC
    bias.
    """
    return _c_response(
        "C_atom_cmu_configure_pulsed_cv_sweep",
        "cmu",
        ["PWDCV", "PTDCV"],
        _CMU_PRE + ["C_atom_cmu_set_impedance_model", "C_atom_cmu_configure_signal"],
        start_v=start_v,
        stop_v=stop_v,
        steps=steps,
        pulse_width_s=pulse_width_s,
        pulse_period_s=pulse_period_s,
    )


def C_atom_cmu_execute_pulsed_cv_sweep(timeout_s: float = 60.0) -> dict:
    """Pretend to execute a pulsed C-V sweep (MM 20 + XE)."""
    return _c_response(
        "C_atom_cmu_execute_pulsed_cv_sweep",
        "cmu",
        ["MM20", "XE"],
        _CMU_PRE + ["C_atom_cmu_configure_pulsed_cv_sweep"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_configure_ct_sampling(
    interval_s: float = 1e-3,
    samples: int = 100,
    dc_bias_v: float = 0.0,
) -> dict:
    """Pretend to configure capacitance-time sampling (MM 26).

    Uses ``MDCV`` (DC bias for C-t sampling) and ``MTDCV`` (sampling timing:
    interval and points), not a vague placeholder.
    """
    return _c_response(
        "C_atom_cmu_configure_ct_sampling",
        "cmu",
        ["MDCV", "MTDCV"],
        _CMU_PRE + ["C_atom_cmu_configure_signal"],
        interval_s=interval_s,
        samples=samples,
        dc_bias_v=dc_bias_v,
    )


def C_atom_cmu_execute_ct_sampling(timeout_s: float = 60.0) -> dict:
    """Pretend to execute capacitance-time sampling (MM 26 + XE)."""
    return _c_response(
        "C_atom_cmu_execute_ct_sampling",
        "cmu",
        ["MM26", "XE"],
        _CMU_PRE + ["C_atom_cmu_configure_ct_sampling"],
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_cmu_measure_timer_start_ac_voltage(channel: int = 1, ac_level_v: float = 0.03) -> dict:
    """Pretend to run timer-start CMU AC-level measurement."""
    return _c_response(
        "C_atom_cmu_measure_timer_start_ac_voltage",
        "cmu",
        ["TACV"],
        _CMU_PRE,
        channel=channel,
        ac_level_v=ac_level_v,
        measurement={"capacitance_f": 0.0},
    )


def C_atom_cmu_measure_timer_start_dc_voltage(channel: int = 1, dc_bias_v: float = 0.0) -> dict:
    """Pretend to run timer-start CMU DC-bias measurement."""
    return _c_response(
        "C_atom_cmu_measure_timer_start_dc_voltage",
        "cmu",
        ["TDCV"],
        _CMU_PRE,
        channel=channel,
        dc_bias_v=dc_bias_v,
        measurement={"capacitance_f": 0.0},
    )


# ---------------------------------------------------------------------------
# C class — high-power resource wrapper atoms
# ---------------------------------------------------------------------------


def C_atom_hvsmu_set_operation_mode(channel: int = 1, mode: str = "standard") -> dict:
    """Pretend to set HVSMU operation mode."""
    return _c_response(
        "C_atom_hvsmu_set_operation_mode",
        "hvsmu",
        ["HVSMUOP"],
        _HIGH_POWER_PRE,
        channel=channel,
        mode=mode,
        caution="HVSMU mode can affect high-voltage sourcing limits on real hardware.",
    )


def C_atom_hvsmu_execute_iv(
    channel: int = 1,
    start_v: float = 0.0,
    stop_v: float = 10.0,
    compliance_a: float = 0.001,
) -> dict:
    """Pretend to execute an HVSMU IV wrapper over SMU-family primitives."""
    return _c_response(
        "C_atom_hvsmu_execute_iv",
        "hvsmu",
        ["HVSMUOP", "SMU IV wrapper"],
        _HIGH_POWER_PRE + ["C_atom_hvsmu_set_operation_mode"],
        channel=channel,
        start_v=start_v,
        stop_v=stop_v,
        compliance_a=compliance_a,
        caution="Schema wrapper only; it does not introduce a separate low-level command path.",
    )


def C_atom_hcsmu_execute_iv(
    channel: int = 1,
    start_v: float = 0.0,
    stop_v: float = 5.0,
    compliance_a: float = 1.0,
) -> dict:
    """Pretend to execute an HCSMU IV wrapper over SMU-family primitives."""
    return _c_response(
        "C_atom_hcsmu_execute_iv",
        "hcsmu",
        ["HCSMU IV wrapper"],
        _HIGH_POWER_PRE,
        channel=channel,
        start_v=start_v,
        stop_v=stop_v,
        compliance_a=compliance_a,
        caution="High-current wrapper requires fixture and cabling validation in a real station.",
    )


def C_atom_uhcu_execute_iv(
    channel: int = 1,
    start_v: float = 0.0,
    stop_v: float = 2.0,
    compliance_a: float = 10.0,
) -> dict:
    """Pretend to execute a UHC expander IV wrapper."""
    return _c_response(
        "C_atom_uhcu_execute_iv",
        "uhcu",
        ["UHC expander IV wrapper"],
        _HIGH_POWER_PRE + ["B_atom_routing_selector_set_mode"],
        channel=channel,
        start_v=start_v,
        stop_v=stop_v,
        compliance_a=compliance_a,
        caution="UHC wrapper assumes expander mode/routing have been verified by B atoms.",
    )


def C_atom_hvmcu_execute_iv(
    channel: int = 1,
    start_v: float = 0.0,
    stop_v: float = 10.0,
    compliance_a: float = 1.0,
) -> dict:
    """Pretend to execute an HVMC expander IV wrapper."""
    return _c_response(
        "C_atom_hvmcu_execute_iv",
        "hvmcu",
        ["HVMC expander IV wrapper"],
        _HIGH_POWER_PRE + ["B_atom_routing_selector_set_mode"],
        channel=channel,
        start_v=start_v,
        stop_v=stop_v,
        compliance_a=compliance_a,
        caution="HVMC wrapper assumes high-voltage/current expander routing is already safe.",
    )


def C_atom_uhvu_execute_iv(
    channel: int = 1,
    start_v: float = 0.0,
    stop_v: float = 100.0,
    compliance_a: float = 0.001,
) -> dict:
    """Pretend to execute a UHV expander IV wrapper."""
    return _c_response(
        "C_atom_uhvu_execute_iv",
        "uhvu",
        ["UHV expander IV wrapper"],
        _HIGH_POWER_PRE + ["B_atom_routing_selector_set_mode"],
        channel=channel,
        start_v=start_v,
        stop_v=stop_v,
        compliance_a=compliance_a,
        caution="UHV wrapper requires interlock, discharge, and fixture validation in real use.",
    )


# ---------------------------------------------------------------------------
# C class — EasyEXPERT software-mediated execution atoms
# ---------------------------------------------------------------------------


def C_atom_easyexpert_run_selected_test(timeout_s: float = 300.0) -> dict:
    """Pretend to execute the selected EasyEXPERT application/setup test."""
    return _c_response(
        "C_atom_easyexpert_run_selected_test",
        "easyexpert",
        [":BENCh:SELected:RUN"],
        _EASYEXPERT_PRE,
        timeout_s=timeout_s,
        status="fake_complete",
        caution="Software-mediated execution can still bias hardware in a real station.",
    )


def C_atom_easyexpert_run_quick_test_sequence(
    sequence_name: str = "quick_test",
    timeout_s: float = 300.0,
) -> dict:
    """Pretend to execute an EasyEXPERT quick-test sequence."""
    return _c_response(
        "C_atom_easyexpert_run_quick_test_sequence",
        "easyexpert",
        [":QUICKTest:RUN"],
        _EASYEXPERT_PRE,
        sequence_name=sequence_name,
        timeout_s=timeout_s,
        status="fake_complete",
    )


def C_atom_easyexpert_repeat_run_selected_test(
    repeat_count: int = 1,
    timeout_s: float = 300.0,
) -> dict:
    """Pretend to repeat the selected EasyEXPERT test."""
    return _c_response(
        "C_atom_easyexpert_repeat_run_selected_test",
        "easyexpert",
        [":BENCh:COUNt", ":BENCh:SELected:RUN"],
        _EASYEXPERT_PRE + ["A_atom_easyexpert_set_repeat_count"],
        repeat_count=repeat_count,
        timeout_s=timeout_s,
        status="fake_complete",
    )


C_ATOM_FUNCTIONS = [
    C_atom_smu_set_measurement_mode,
    C_atom_smu_set_measurement_operation,
    C_atom_smu_configure_integration,
    C_atom_smu_set_measurement_ranging,
    C_atom_smu_force_voltage,
    C_atom_smu_force_current,
    C_atom_smu_measure_high_speed_spot,
    C_atom_smu_configure_staircase_sweep,
    C_atom_smu_configure_sweep_timing,
    C_atom_smu_execute,
    C_atom_smu_read_measurement_data,
    C_atom_smu_configure_pulse_timing,
    C_atom_smu_configure_pulsed_spot_source,
    C_atom_smu_configure_sweep_abort,
    C_atom_smu_configure_synchronous_sweep_source,
    C_atom_smu_configure_pulsed_sweep,
    C_atom_smu_execute_pulsed_spot,
    C_atom_smu_execute_pulsed_sweep,
    C_atom_smu_configure_sampling,
    C_atom_smu_execute_sampling,
    C_atom_smu_configure_multi_sweep,
    C_atom_smu_configure_multi_pulsed,
    C_atom_smu_configure_quasi_pulse,
    C_atom_smu_configure_search,
    C_atom_smu_configure_signal_monitor,
    C_atom_smu_force_timer_start_voltage,
    C_atom_smu_force_timer_start_current,
    C_atom_smu_configure_qscv,
    C_atom_smu_execute_qscv,
    C_atom_smu_configure_staircase_sweep_pulsed_bias,
    C_atom_smu_set_parallel_measurement,
    C_atom_smu_configure_trigger_io,
    C_atom_smu_set_trigger_mode,
    C_atom_smu_configure_high_speed_spot,
    C_atom_wgfmu_set_operation_mode,
    C_atom_wgfmu_configure_force_measure_ranges,
    C_atom_wgfmu_set_measure_mode,
    C_atom_wgfmu_set_measure_voltage_range,
    C_atom_wgfmu_set_measure_enabled,
    C_atom_wgfmu_set_trigger_out_mode,
    C_atom_wgfmu_create_pattern,
    C_atom_wgfmu_add_vectors,
    C_atom_wgfmu_add_sequence,
    C_atom_wgfmu_set_measure_event,
    C_atom_wgfmu_update,
    C_atom_wgfmu_execute,
    C_atom_wgfmu_read_measurement_values,
    C_atom_wgfmu_set_vectors,
    C_atom_wgfmu_transform_pattern,
    C_atom_wgfmu_set_range_event,
    C_atom_wgfmu_set_trigger_event,
    C_atom_wgfmu_configure_force_measure_delay,
    C_atom_wgfmu_read_force_values,
    C_atom_wgfmu_dc_force_measure,
    C_atom_wgfmu_dc_measure_value,
    C_atom_wgfmu_dc_measure_averaged,
    C_atom_wgfmu_read_measurement_values_partial,
    C_atom_wgfmu_configure_alwg_cycle,
    C_atom_spgu_set_operation_mode,
    C_atom_spgu_set_load_impedance,
    C_atom_spgu_configure_pg_pulse,
    C_atom_spgu_update_output,
    C_atom_spgu_start_output,
    C_atom_spgu_stop_output,
    C_atom_spgu_create_alwg_pattern,
    C_atom_spgu_add_alwg_sequence,
    C_atom_spgu_configure_sampling_pulse,
    C_atom_spgu_set_trigger_output,
    C_atom_cmu_set_impedance_model,
    C_atom_cmu_configure_signal,
    C_atom_cmu_set_ranging_integration,
    C_atom_cmu_set_monitor_output,
    C_atom_cmu_read_measurement_data,
    C_atom_cmu_configure_cv_dc_sweep,
    C_atom_cmu_execute,
    C_atom_cmu_measure_high_speed_spot,
    C_atom_cmu_execute_spot_c,
    C_atom_cmu_execute_cv_dc_sweep,
    C_atom_cmu_configure_cf_sweep,
    C_atom_cmu_execute_cf_sweep,
    C_atom_cmu_configure_ac_level_sweep,
    C_atom_cmu_execute_ac_level_sweep,
    C_atom_cmu_configure_pulsed_spot_c,
    C_atom_cmu_execute_pulsed_spot_c,
    C_atom_cmu_configure_pulsed_cv_sweep,
    C_atom_cmu_execute_pulsed_cv_sweep,
    C_atom_cmu_configure_ct_sampling,
    C_atom_cmu_execute_ct_sampling,
    C_atom_cmu_measure_timer_start_ac_voltage,
    C_atom_cmu_measure_timer_start_dc_voltage,
    C_atom_hvsmu_set_operation_mode,
    C_atom_hvsmu_execute_iv,
    C_atom_hcsmu_execute_iv,
    C_atom_uhcu_execute_iv,
    C_atom_hvmcu_execute_iv,
    C_atom_uhvu_execute_iv,
    C_atom_easyexpert_run_selected_test,
    C_atom_easyexpert_run_quick_test_sequence,
    C_atom_easyexpert_repeat_run_selected_test,
]


def register_c_atoms(mcp: FastMCP) -> None:
    """Register all C_atom_* tools on a FastMCP instance."""
    for tool in C_ATOM_FUNCTIONS:
        mcp.tool(tool)
