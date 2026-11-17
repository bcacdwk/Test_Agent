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
from b1500_test_agent.models.station import SimSlot

# -- Device models ---------------------------------------------------------------------------------------------------


class OpenParams(StrictModel):
    """``open``: nothing connected (probe not landed); every terminal current is zero, so only noise is measured."""


class ResistorParams(StrictModel):
    """``resistor``: ``I = (V_a - V_b) / r_ohm`` between terminals ``a`` and ``b``."""

    r_ohm: PositiveFloat


class ShortParams(StrictModel):
    """``short``: a resistor of ``r_ohm`` (contact plus wiring resistance) between ``a`` and ``b``."""

    r_ohm: PositiveFloat = 0.1


class MosfetEkvParams(StrictModel):
    """``mosfet_ekv``: EKV interpolation from subthreshold through linear to saturation (truth parameters).

    ``vth0`` is the threshold voltage in terminal polarity (positive for a usual n-channel, negative for a usual
    p-channel). ``slope_factor`` n sets the subthreshold swing ``n·ln10·kT/q``; ``beta`` = µ·Cox·W/L (A/V²);
    ``theta`` (1/V) degrades mobility with gate overdrive so gm peaks; ``lambda`` (1/V) is channel-length
    modulation; ``rs_ohm`` is the series resistance at the source and at the drain (each); ``gate_leak_s`` is the
    gate leakage conductance, split equally between gate-source and gate-drain.
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


class FefetParams(MosfetEkvParams):
    """``fefet``: a ``mosfet_ekv`` whose threshold follows a ferroelectric polarization state (truth parameters).

    ``Vth = vth0 - k_v·P`` with the normalised polarization ``P`` in [-1, 1] (positive ``P``, written by a positive
    gate voltage, lowers the threshold for both polarities). ``P`` follows a hysteretic tanh loop of the
    gate-source voltage ``V``: it never leaves the band between the ascending branch ``tanh((V - vc_v)/delta_v)`` and
    the descending branch ``tanh((V + vc_v)/delta_v)`` and otherwise keeps its value (rate-independent play
    operator). It starts at ``p_init`` and is persisted with the simulator state, so it survives transactions and
    processes. A full loop gives the memory window ``Vth_fwd - Vth_rev`` of about ``2·k_v``.
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


DEVICE_PARAMS: dict[str, type[StrictModel]] = {
    "open": OpenParams,
    "resistor": ResistorParams,
    "short": ShortParams,
    "mosfet_ekv": MosfetEkvParams,
    "diode": DiodeParams,
    "fefet": FefetParams,
    "mosfet_damaged": MosfetDamagedParams,
}
"""Device models the simulator implements (M1: open, resistor, short, mosfet_ekv; M2: diode, fefet, damaged)."""

_MOSFET_TERMINALS = frozenset({"gate", "drain", "source", "bulk"})

DEVICE_TERMINALS: dict[str, frozenset[str] | None] = {
    "open": None,
    "resistor": frozenset({"a", "b"}),
    "short": frozenset({"a", "b"}),
    "mosfet_ekv": _MOSFET_TERMINALS,
    "diode": frozenset({"anode", "cathode"}),
    "fefet": _MOSFET_TERMINALS,
    "mosfet_damaged": _MOSFET_TERMINALS,
}
"""Terminal names a scenario may wire per device model (``None``: any name, e.g. an unlanded probe)."""


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


SimFault = Annotated[
    ComplianceAt | ErrxFault | TimeoutFault | GarbageData | InterlockOpen | Disconnect | Oscillation | IdnOverride
    | ModulesOverride | IgnoreDz | CleanupFailure | Slow,
    Field(discriminator="kind"),
]
"""One simulator fault (blueprint 3); the ``kind`` key selects the type."""

FAULT_KINDS: tuple[str, ...] = (
    "compliance_at", "errx", "timeout", "garbage_data", "interlock_open", "disconnect", "oscillation",
    "idn_override", "modules_override", "ignore_dz", "cleanup_failure", "slow",
)  # fmt: skip
"""Every ``SimFault`` kind, in blueprint order."""


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
