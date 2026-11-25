"""Simulator schemas: typed device-model parameters and the fault profile (blueprint 3).

``SimScenario`` (``models/station.py``) names device models by string; ``DEVICE_PARAMS`` types their ``params``
and ``DEVICE_TERMINALS`` lists the terminal names a scenario may wire. Faults come from a fault profile
(``config/sim/faults/<name>.yaml``, schema ``SimFaultProfile``, named by ``SimScenario.faults``) or are injected at
run time with ``SimInstrument.inject()``; both use the ``SimFault`` discriminated union (key ``kind``).

Step indices are 0-based positions in the measurement (a spot measurement has the single step 0). Counters such as
``nth`` start when the fault becomes active (instrument creation for profile faults, ``inject()`` otherwise).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from b1500_test_agent.models.analysis import PositiveFloat
from b1500_test_agent.models.common import ConfigName, StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.sim_devices import (
    CapacitorParams,
    DielectricParams,
    FecapParams,
    FerroKineticsParams,
    FixtureParams,
    MoscapParams,
    MosfetDynamicsParams,
    NoiseParams,
)
from b1500_test_agent.models.station import SimSlot

# -- Device models ---------------------------------------------------------------------------------------------------


class OpenParams(StrictModel):
    """``open``: nothing connected (probe not landed); every terminal current is zero, so only noise is measured."""


class ResistorParams(StrictModel):
    """``resistor``: ``I = (V_a - V_b) / r_ohm`` between terminals ``a`` and ``b`` as seen at the pads.

    v2 (WP7.1, four-wire sensing): ``lead_ohm`` is the force-path resistance of each terminal (cable, probe and
    contact); ``kelvin`` names the terminals whose Sense line is landed at the pad as well (``none``, ``a``, ``b``,
    ``both``). An instrument channel regulates and measures the voltage at its sense point, so a Kelvin terminal's
    lead drop is outside the reading and a two-wire terminal's is inside it: the channel sees
    ``r_ohm + lead_ohm x (two-wire terminals)``. Truth for a four-wire measurement is ``r_ohm``; with the defaults
    (no lead resistance) the model is the v1 resistor.
    """

    r_ohm: PositiveFloat
    lead_ohm: float = Field(default=0.0, ge=0.0, le=1.0e3)
    kelvin: Literal["none", "a", "b", "both"] = "none"

    def seen_ohm(self) -> float:
        """The resistance the instrument channels see (``r_ohm`` plus the lead of every two-wire terminal)."""
        two_wire = {"none": 2, "a": 1, "b": 1, "both": 0}[self.kelvin]
        return self.r_ohm + self.lead_ohm * two_wire


class ShortParams(StrictModel):
    """``short``: a resistor of ``r_ohm`` (contact plus wiring resistance) between ``a`` and ``b``."""

    r_ohm: PositiveFloat = 0.1


class MosfetEkvParams(StrictModel):
    """``mosfet_ekv``: EKV interpolation from subthreshold through linear to saturation (truth parameters).

    ``vth0`` is the threshold voltage in terminal polarity (positive for a usual n-channel, negative for a usual
    p-channel). ``slope_factor`` n sets the subthreshold swing ``n·ln10·kT/q``; ``beta`` = µ·Cox·W/L (A/V²);
    ``theta`` (1/V) degrades mobility with gate overdrive so gm peaks; ``lambda`` (1/V) is channel-length
    modulation; ``rs_ohm`` is the series resistance at the source and at the drain (each); ``gate_leak_s`` is the
    gate leakage conductance, split equally between gate-source and gate-drain; ``dibl`` (V/V, default 0 = long
    channel) is the drain-induced barrier lowering: the threshold falls by ``dibl·|V_DS|`` (the truth of the
    ``dibl`` analysis, WP7.2).
    """

    polarity: Literal["n", "p"] = "n"
    vth0: float
    slope_factor: float = Field(default=1.3, ge=1.0, le=5.0)
    beta: PositiveFloat = 2.0e-3
    theta: float = Field(default=0.0, ge=0.0, le=10.0)
    lambda_: float = Field(default=0.0, ge=0.0, le=5.0, alias="lambda")
    rs_ohm: float = Field(default=0.0, ge=0.0, le=1.0e6)
    gate_leak_s: float = Field(default=0.0, ge=0.0, le=1.0)
    temperature_k: float = Field(default=300.0, gt=0.0, le=600.0)
    dibl: float = Field(default=0.0, ge=0.0, le=0.5)

    model_config = ConfigDict(
        **StrictModel.model_config, validate_by_name=True, validate_by_alias=True, serialize_by_alias=True
    )


class DiodeParams(StrictModel):
    """``diode``: Shockley junction with series resistance, shunt leakage and soft reverse breakdown (truth).

    With ``U_T = k·T/q`` and the junction voltage ``Vj`` (anode minus cathode, less the drop over ``rs_ohm``), the
    anode current is ``I = is_a·(exp(Vj/(n·U_T)) - 1) + leak_s·Vj - I_bv`` with the soft breakdown current
    ``I_bv = ibv_a·(exp(-(Vj + bv_v)/bv_width_v) - exp(-bv_v/bv_width_v))`` (zero at 0 V, ``ibv_a`` at
    ``Vj = -bv_v``; omitted when ``bv_v`` is null). ``rs_ohm`` makes ``I`` implicit; the simulator solves it by
    Newton's method. ``leak_s`` is the reverse leakage (a shunt conductance across the junction).
    """

    is_a: PositiveFloat
    n: float = Field(default=1.0, ge=0.5, le=10.0)
    rs_ohm: float = Field(default=0.0, ge=0.0, le=1.0e6)
    leak_s: float = Field(default=0.0, ge=0.0, le=1.0)
    bv_v: PositiveFloat | None = None
    ibv_a: PositiveFloat = 1.0e-6
    bv_width_v: PositiveFloat = 0.5
    temperature_k: float = Field(default=300.0, gt=0.0, le=600.0)


class FefetParams(FerroKineticsParams, MosfetEkvParams):
    """``fefet``: a ``mosfet_ekv`` whose threshold follows a ferroelectric polarization state (truth parameters).

    ``Vth = vth0 - k_v·P`` with the normalised polarization ``P`` in [-1, 1] (positive ``P``, written by a positive
    gate voltage, lowers the threshold for both polarities). ``P`` follows a hysteretic tanh loop of the
    gate-source voltage ``V``: it never leaves the band between the ascending branch ``tanh((V - vc_v)/delta_v)`` and
    the descending branch ``tanh((V + vc_v)/delta_v)`` and otherwise keeps its value (rate-independent play
    operator). It starts at ``p_init`` and is persisted with the simulator state, so it survives transactions and
    processes. A full loop gives the memory window ``Vth_fwd - Vth_rev`` of about ``2·k_v``.

    Timed gate pulses (``advance``) switch with NLS kinetics, and retention and endurance follow
    ``FerroKineticsParams`` (``models/sim_devices.py``, v2); their defaults leave the v1 DC behaviour unchanged.
    """

    k_v: float = Field(default=0.5, ge=0.0, le=10.0)
    vc_v: PositiveFloat = 2.8
    delta_v: PositiveFloat = 0.45
    p_init: float = Field(default=-1.0, ge=-1.0, le=1.0)


class MosfetDamagedParams(MosfetEkvParams):
    """``mosfet_damaged``: a ``mosfet_ekv`` with one damage (truth parameters).

    - ``gate_drain_short``: a resistor ``short_r_ohm`` between gate and drain (gate current mirrors into the drain);
    - ``open_drain``: the drain is not connected to the channel (probe not landed or broken contact): the drain
      terminal carries no current, so only noise is measured there; the gate-source half of the gate leakage stays;
    - ``leaky_gate``: an extra gate leakage conductance ``leak_s``, split equally between gate-source and gate-drain.
    """

    damage: Literal["gate_drain_short", "open_drain", "leaky_gate"]
    short_r_ohm: PositiveFloat = 1000.0
    leak_s: float = Field(default=1.0e-7, ge=0.0, le=1.0)


class MosfetParams(MosfetDynamicsParams, MosfetEkvParams):
    """``mosfet`` (v2): ``mosfet_ekv`` plus self-heating, BTI, HCI, IGZO bias-stress drift and gate capacitances
    (``MosfetDynamicsParams`` in ``models/sim_devices.py``); with every effect off it equals ``mosfet_ekv``."""


DEVICE_PARAMS: dict[str, type[StrictModel]] = {
    "open": OpenParams,
    "resistor": ResistorParams,
    "short": ShortParams,
    "mosfet_ekv": MosfetEkvParams,
    "diode": DiodeParams,
    "fefet": FefetParams,
    "mosfet_damaged": MosfetDamagedParams,
    "mosfet": MosfetParams,
    "moscap": MoscapParams,
    "capacitor": CapacitorParams,
    "fixture": FixtureParams,
    "dielectric": DielectricParams,
    "fecap": FecapParams,
    "noise": NoiseParams,
}
"""Device models the simulator implements (M1: open, resistor, short, mosfet_ekv; M2: diode, fefet, damaged; v2
WP5.9: mosfet, moscap, capacitor, fixture, dielectric, fecap, noise)."""

_MOSFET_TERMINALS = frozenset({"gate", "drain", "source", "bulk"})

DEVICE_TERMINALS: dict[str, frozenset[str] | None] = {
    "open": None,
    "resistor": frozenset({"a", "b"}),
    "short": frozenset({"a", "b"}),
    "mosfet_ekv": _MOSFET_TERMINALS,
    "diode": frozenset({"anode", "cathode"}),
    "fefet": _MOSFET_TERMINALS,
    "mosfet_damaged": _MOSFET_TERMINALS,
    "mosfet": _MOSFET_TERMINALS,
    "moscap": frozenset({"gate", "bulk"}),
    "capacitor": frozenset({"a", "b"}),
    "fixture": frozenset({"high", "low"}),
    "dielectric": frozenset({"top", "bottom"}),
    "fecap": frozenset({"top", "bottom"}),
    "noise": frozenset(),
}
"""Terminal names a scenario may wire per device model (``None``: any name, e.g. an unlanded probe; ``noise`` has
none and is wired as ``{}``)."""


def device_params(model: str, params: dict[str, object]) -> StrictModel:
    """Validate ``params`` of device ``model``; raises ``ValueError`` for an unknown model or bad parameters."""
    schema = DEVICE_PARAMS.get(model)
    if schema is None:
        raise ValueError(f"Unknown sim device model {model!r}; known: {', '.join(sorted(DEVICE_PARAMS))}.")
    try:
        return schema.model_validate(params)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'params'}: {err['msg']}"
            for err in exc.errors(include_url=False, include_input=False)
        )
        raise ValueError(f"Invalid {model} params: {details}.") from None


# -- Faults ----------------------------------------------------------------------------------------------------------

Step = Annotated[int, Field(ge=0, le=100_000)]
Mnemonic = Annotated[str, Field(pattern=r"^\*?[A-Z]{1,12}\??$")]


class ComplianceAt(StrictModel):
    """At measurement step ``step`` channel ``ch`` reports compliance (``C``, value ±Icomp); the others get ``T``."""

    kind: Literal["compliance_at"] = "compliance_at"
    step: Step
    ch: Channel


class ErrxFault(StrictModel):
    """After the ``nth`` execution of ``after_cmd`` (a mnemonic such as ``XE``), error ``code`` is queued for
    ``ERRX?``. One-shot."""

    kind: Literal["errx"] = "errx"
    after_cmd: Mnemonic
    code: int = Field(ge=1, le=99_999)
    nth: int = Field(default=1, ge=1)


class TimeoutFault(StrictModel):
    """One-shot hang, selected by ``on``:

    - a command mnemonic, e.g. ``XE``: the ``nth`` execution never completes; the instrument stays busy (an ``XE``
      measurement returns no data) and holds later commands, until ``AB`` sent alone or a device clear;
    - ``read``: the ``nth`` read call times out (the data stays buffered);
    - ``query:<mnemonic>``, e.g. ``query:*OPC?``: the ``nth`` execution of that query never answers; reads time out
      until a device clear, ``BC`` or ``*RST``.
    """

    kind: Literal["timeout"] = "timeout"
    on: Annotated[str, Field(pattern=r"^(read|query:\*?[A-Z]{1,12}\?|\*?[A-Z]{1,12}\??)$")]
    nth: int = Field(default=1, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _yaml_on_key(cls, data: object) -> object:
        """YAML 1.1 reads a bare ``on:`` key as boolean true; accept it as the ``on`` field."""
        if isinstance(data, dict) and True in data and "on" not in data:
            data = {("on" if key is True else key): value for key, value in data.items()}
        return data


class GarbageData(StrictModel):
    """The first data element of step ``at_step`` is replaced by unparsable text (every measurement)."""

    kind: Literal["garbage_data"] = "garbage_data"
    at_step: Step


class InterlockOpen(StrictModel):
    """The interlock opens: immediately (``at_step`` null) or when a measurement reaches step ``at_step``. In the
    high-voltage state (any output above 42 V) all outputs drop to 0 V, error 202 is queued and the sweep aborts."""

    kind: Literal["interlock_open"] = "interlock_open"
    at_step: Step | None = None


class Disconnect(StrictModel):
    """The link drops after ``after_writes`` more writes: every later I/O raises ``TransportError`` and the
    instrument keeps its outputs (nothing reaches it any more)."""

    kind: Literal["disconnect"] = "disconnect"
    after_writes: int = Field(ge=0)


class Oscillation(StrictModel):
    """Measured channels report ``X`` at the listed steps (null = every step) of every measurement."""

    kind: Literal["oscillation"] = "oscillation"
    steps: list[Step] | None = None


class IdnOverride(StrictModel):
    """``*IDN?`` answers ``idn`` instead of the scenario identity."""

    kind: Literal["idn_override"] = "idn_override"
    idn: str = Field(min_length=1)


class ModulesOverride(StrictModel):
    """The mainframe holds ``slots`` instead of the scenario modules (``UNT?`` and channel validation follow)."""

    kind: Literal["modules_override"] = "modules_override"
    slots: list[SimSlot]

    @model_validator(mode="after")
    def _unique(self) -> ModulesOverride:
        slots = [s.slot for s in self.slots]
        if len(set(slots)) != len(slots):
            raise ValueError("A slot is listed twice.")
        return self


class IgnoreDz(StrictModel):
    """Stuck output: zeroing is accepted without error but the listed channels (null = all) keep forcing their
    voltage with the relay closed, through ``DZ``, ``CL``, ``*RST``, ``*TST?``/``*CAL?`` and device clear, so
    cleanup verification fails."""

    kind: Literal["ignore_dz"] = "ignore_dz"
    channels: list[Channel] | None = None


class CleanupFailure(StrictModel):
    """Writes containing ``DZ`` or ``CL`` time out and never reach the instrument (``count`` times; null =
    always)."""

    kind: Literal["cleanup_failure"] = "cleanup_failure"
    count: int | None = Field(default=None, ge=1)


class Slow(StrictModel):
    """Measurements take ``factor`` times their nominal duration (reads with a short timeout then time out)."""

    kind: Literal["slow"] = "slow"
    factor: float = Field(gt=0.0, le=1.0e6)


class RunInterrupt(StrictModel):
    """The host is interrupted while measurement ``segment`` runs (0-based count of ``XE`` triggers since the fault
    became active; one per segment of a stepped run): the read of that measurement raises ``SimulatedInterrupt`` (a
    ``KeyboardInterrupt``, as a Ctrl-C or a signal stopping the server would) with the measurement still pending, so
    the transaction cleanup must abort it, zero, disconnect and verify (blueprint v2 4.3). One-shot."""

    kind: Literal["run_interrupt"] = "run_interrupt"
    segment: int = Field(ge=0, le=100_000)


class AbortIgnored(StrictModel):
    """``AB`` has no effect from its ``nth`` execution on (``count`` executions; null = every later one): a running
    measurement keeps running, so commands sent after the ``AB`` wait behind it (blueprint v2 4.3). The cleanup must
    still verify the safe state (device clear and retry) or latch the fault."""

    kind: Literal["abort_ignored"] = "abort_ignored"
    nth: int = Field(default=1, ge=1)
    count: int | None = Field(default=None, ge=1)


class BusLockedFault(StrictModel):
    """Another client (EasyEXPERT, a second VISA program) holds the instrument's exclusive bus lock (blueprint v2
    4.3): starting with the ``nth`` bus-lock request, ``count`` requests (null = every later one) are refused
    (``BusLocked``, result ``instrument_busy``) and nothing reaches the instrument. A request is
    ``SimTransport.lock()`` on the simulator and the VISA ``lock_excl`` on visa-loop, i.e. one per transaction or
    status snapshot (more inside a WGFMU phase, which relocks). A transaction already holding the lock is never
    interrupted."""

    kind: Literal["bus_locked"] = "bus_locked"
    nth: int = Field(default=1, ge=1)
    count: int | None = Field(default=None, ge=1)


class BreakdownAt(StrictModel):
    """Forced dielectric breakdown (blueprint v2 4.3): every ``dielectric`` device of the scenario (or only
    ``device``) breaks down at the first sampled point (``MM 10``) taken ``t_s`` seconds or more after the first
    sampled point since the fault became active, whatever its accumulated damage; afterwards its ohmic breakdown path
    conducts (``r_bd_ohm``), so the stress source runs into compliance. One-shot."""

    kind: Literal["breakdown_at"] = "breakdown_at"
    t_s: float = Field(ge=0.0, le=1.0e7)
    device: str | None = None


class CmuCorrectionLost(StrictModel):
    """After the ``nth`` execution of ``after_cmd`` (a mnemonic such as ``UNT?`` or ``XE``) every MFCMU loses its
    corrections and phase compensation as a power cycle of the module would: correction functions OFF, correction
    data, frequency list and standard references cleared, compensation result 3 and mode auto (blueprint v2 4.3;
    R-CORR-01 must then refuse a C-V run before it starts). One-shot."""

    kind: Literal["cmu_correction_lost"] = "cmu_correction_lost"
    after_cmd: Mnemonic
    nth: int = Field(default=1, ge=1)


class CmuOverload(StrictModel):
    """At measurement step ``at_step`` of every MFCMU measurement the module overloads (blueprint v2 4.3):
    ``saturation`` reports status ``D`` (IV amplifier saturation), ``unbalance`` status ``U`` (NULL loop unbalance;
    PG Table 1-10, PDF 53), ``excess_current`` queues error 320 and switches the MFCMU output OFF (PG PDF 583), the
    step and the rest of the measurement reading ``199.999E+99``. With the automatic abort on, ``D``/``U`` end the
    sweep too."""

    kind: Literal["cmu_overload"] = "cmu_overload"
    at_step: Step
    condition: Literal["saturation", "unbalance", "excess_current"] = "saturation"


class SpguNoStop(StrictModel):
    """The HV-SPGU output does not stop (blueprint v2 4.3): ``SPST?`` keeps answering 1 through the end of its count or
    duration, a closed output switch, ``SIM``/``SPRM``/``SPUPD``/``SRP``/``CORRSER?``, ``*RST`` and a device clear,
    and the first ``spp_ignored`` ``SPP`` commands are ignored too (null = every one: the output never stops). The
    ``SPP`` after those stops it and ends the fault, so a cleanup whose ``SPP`` retry is honoured verifies, and one
    that never gets there latches the fault (``cleanup_unverified``)."""

    kind: Literal["spgu_no_stop"] = "spgu_no_stop"
    spp_ignored: int | None = Field(default=None, ge=1)


class SpguLoadMismatch(StrictModel):
    """The HV-SPGU channel ``channel`` (null = every SPGU channel) drives a load of ``load_ohm`` (to ground) instead of
    the scenario's wiring (blueprint v2 4.3): the level reaching it is the open-load level ``|V| (SER + 50) / SER``
    divided by ``(load + 50) / load``, so a declared ``SER`` that differs from the real load delivers more or less
    than the set level (never more than the open-load level the guard checks); ``CORRSER?`` reads ``load_ohm``."""

    kind: Literal["spgu_load_mismatch"] = "spgu_load_mismatch"
    channel: Channel | None = None
    load_ohm: float = Field(gt=0.0, le=1.0e12)


class SelectorStuck(StrictModel):
    """A 16440A selector output that does not follow ``ERSSP`` (blueprint v2 4.3): ``port`` (0-3, PG p433 (4-115))
    stays in ``state`` through every ``ERSSP``, ``ERMOD``, ``*RST`` and device clear, ``ERSSP?`` reports that state
    and the DUT terminal behind it stays on that path (a welded relay or a selector whose control the B1500A lost).
    The transaction cannot return it to rest, so its cleanup verification fails and the fault latches
    (``cleanup_unverified``). ``pgu_open`` exists only on CH 1 (ports 0 and 2, PG p154 (2-66))."""

    kind: Literal["selector_stuck"] = "selector_stuck"
    port: int = Field(ge=0, le=3)
    state: Literal["open", "smu", "pgu", "pgu_open"]

    @model_validator(mode="after")
    def _ch1_only(self) -> SelectorStuck:
        if self.state == "pgu_open" and self.port not in (0, 2):
            raise ValueError(f"port {self.port} is CH 2 of its selector, which has no PGU-open state (ports 0, 2)")
        return self


LIBRARY_FUNCTIONS: tuple[str, ...] = (
    "open_session", "close_session", "initialize", "clear", "set_timeout", "channel_ids", "set_operation_mode",
    "set_force_voltage_range", "set_measure_mode", "set_measure_current_range", "set_measure_voltage_range",
    "set_measure_enabled", "create_pattern", "add_vectors", "set_measure_event", "set_range_event", "add_sequence",
    "update", "connect", "disconnect", "execute", "wait_until_completed", "abort", "status", "channel_status",
    "measure_value_size", "measure_values", "dc_force_voltage", "dc_measure_value", "self_test", "self_calibration",
    "errors", "set_warning_level", "warning_level", "treat_warnings_as_errors", "warnings",
)  # fmt: skip
"""The methods of the WGFMU instrument-library protocol (``transport.wgfmu.api.WgfmuApi``, blueprint v2 2.4) that
the WGFMU faults can target (test: equal to the protocol's methods; the warning queue since WP10.8)."""

LibraryFunction = Annotated[str, Field(pattern=r"^[a-z][a-z_]{1,39}$")]


def _known_function(fn: str) -> str:
    if fn not in LIBRARY_FUNCTIONS:
        raise ValueError(f"fn {fn!r} is not a WGFMU library function ({', '.join(LIBRARY_FUNCTIONS)})")
    return fn


class WgfmuErrorFault(StrictModel):
    """The ``nth`` call of library function ``fn`` (a ``WgfmuApi`` method such as ``execute``) fails with ``code``
    and has no effect (blueprint v2 4.3): a library error (-15 .. -1) or a firmware error (3000-3999, e.g. 3001 RSU
    not connected, 3050 memory overflow; the call returns the firmware-error code). One-shot."""

    kind: Literal["wgfmu_error"] = "wgfmu_error"
    fn: LibraryFunction
    code: int
    nth: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _valid(self) -> WgfmuErrorFault:
        _known_function(self.fn)
        if not (-15 <= self.code <= -1 or 3000 <= self.code <= 3999):
            raise ValueError(f"code {self.code} is neither a library error (-15..-1) nor a firmware error (3000-3999)")
        return self


class WgfmuHang(StrictModel):
    """The ``nth`` call of library function ``fn`` never completes: it blocks for the session timeout
    (``set_timeout``, default 100 s, virtual time) and then fails with a communication error; on ``execute`` or
    ``wait_until_completed`` the sequencer also stays running until ``abort`` or ``initialize`` (blueprint v2 4.3).
    One-shot."""

    kind: Literal["wgfmu_hang"] = "wgfmu_hang"
    fn: LibraryFunction
    nth: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _valid(self) -> WgfmuHang:
        _known_function(self.fn)
        return self


class WgfmuDisconnectFails(StrictModel):
    """Stuck RSU relay: ``disconnect`` of the listed WGFMU channels (null = all) fails with a firmware error and the
    channel stays connected to the DUT, also through ``initialize`` (``count`` failing ``disconnect`` calls; null =
    always), so the cleanup cannot verify the WGFMU part of the safe state (blueprint v2 4.3)."""

    kind: Literal["wgfmu_disconnect_fails"] = "wgfmu_disconnect_fails"
    channels: list[Channel] | None = None
    count: int | None = Field(default=None, ge=1)


class WgfmuDllMissing(StrictModel):
    """The WGFMU instrument library cannot be loaded (blueprint v2 4.3): the simulated bus has no library session
    (``Bus.wgfmu`` is ``None``); injected later, ``open_session`` fails with a library error."""

    kind: Literal["wgfmu_dll_missing"] = "wgfmu_dll_missing"


SimFault = Annotated[
    ComplianceAt | ErrxFault | TimeoutFault | GarbageData | InterlockOpen | Disconnect | Oscillation | IdnOverride
    | ModulesOverride | IgnoreDz | CleanupFailure | Slow | RunInterrupt | BusLockedFault | AbortIgnored
    | BreakdownAt | CmuCorrectionLost | CmuOverload | SpguNoStop | SpguLoadMismatch
    | WgfmuErrorFault | WgfmuHang | WgfmuDisconnectFails | WgfmuDllMissing | SelectorStuck,
    Field(discriminator="kind"),
]
"""One simulator fault (blueprint 3, v2 4.3); the ``kind`` key selects the type."""

FAULT_KINDS: tuple[str, ...] = (
    "compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
    "idn_override", "modules_override", "ignore_dz", "cleanup_failure", "slow", "run_interrupt", "bus_locked",
    "abort_ignored", "breakdown_at", "cmu_correction_lost", "cmu_overload", "spgu_no_stop", "spgu_load_mismatch",
    "wgfmu_error", "wgfmu_hang", "wgfmu_disconnect_fails", "wgfmu_dll_missing", "selector_stuck",
)  # fmt: skip
"""Every ``SimFault`` kind, in blueprint order (v1 kinds, then the v2 additions of blueprint 4.3)."""


class SimFaultProfile(StrictModel):
    """Contents of ``config/sim/faults/<name>.yaml``: a description and the faults active from instrument start."""

    name: ConfigName
    description: str = ""
    faults: list[SimFault] = Field(min_length=1)


class _FaultHolder(BaseModel):
    fault: SimFault


def parse_fault(data: object) -> SimFault:
    """Validate one fault mapping (``{"kind": ..., ...}``); raises ``pydantic.ValidationError``."""
    return _FaultHolder.model_validate({"fault": data}).fault
