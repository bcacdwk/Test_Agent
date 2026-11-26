"""Switches and routes (blueprint v2 2.3, decision 8): station topology and the compiled, guarded route element.

A **switch** is a declared accessory between instrument channels and DUT terminals: the Keysight 16440A SMU/PGU
selector (up to two, ports 0-3 driven by ``ERMOD 1`` + ``ERSSP port,status``; PG p433-434 (4-115, 4-116)), the SCUU
(``SSP``; PG p520 (4-202)), the ASU (``SAP``; PG p505 (4-187)) and the WGFMU RSU (``WGFMU_connect``). The station
profile lists them under ``switches:``; a pin map reaches a DUT terminal through one with the target
``"<SWITCH>.<OUTPUT>"`` (e.g. ``SEL1.OUT1``, ``RSU201.OUT``).

A **route** is one switch output in one state. Plans carry the routes they need (per phase); the ``OutputGuard``
refuses any route outside the compiled envelope unless it is the switch's ``rest`` (cleanup) state, and the
transaction cleanup returns every declared output to ``rest``.

Facts encoded here: ``ERSSP`` status 0 = all open, 1 = SMU, 2 = PGU, 3 = PGU open (semiconductor relay open), port 0/1
= first selector output 1/2, port 2/3 = second selector output 1/2 (PG p433 (4-115)); the PGU-open state exists only
on CH 1 of each selector, i.e. ports 0 and 2, and the SMU path carries Force only, Sense stays open (PG p154 (2-66)).
An RSU's ``smu`` input is its "From SMU" terminal (WG p20 (1-8)): ``rsu_smu_inputs`` lists which SMU is cabled there,
the channels R-RSU-01 and the ``OutputGuard`` hold to the input's +-25 V and 100 mA whatever the RSU's state.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Final, Literal, NamedTuple

from pydantic import Field, model_validator

from b1500_test_agent.models.common import Alias, StrictModel
from b1500_test_agent.models.measurement import Channel

SwitchKind = Literal["selector_16440a", "scuu", "asu", "rsu"]
"""Declared switch accessories: 16440A SMU/PGU selector, SMU CMU unify unit, atto sense and switch unit, WGFMU RSU."""

SwitchState = Literal["open", "smu", "pgu", "pgu_open", "cmu", "wgfmu"]
"""What a switch output connects to: nothing, the SMU, PGU, MFCMU or WGFMU input; ``pgu_open`` = 16440A CH 1 with the
PGU-side mechanical relay closed and the semiconductor relay open."""

SwitchInput = Literal["smu", "pgu", "cmu", "wgfmu"]
"""Input side of a switch port (the instrument resource wired to it)."""

SwitchOutput = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,15}$")]
"""DUT-side output name of a switch (``OUT1``, ``OUT2``, ``OUT``)."""

SwitchTarget = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}\.[A-Za-z][A-Za-z0-9_]{0,15}$")]
"""Pin-map target through a switch: ``"<switch id>.<output>"``, e.g. ``SEL1.OUT1``."""

SWITCH_STATES: Final[dict[str, frozenset[str]]] = {
    "selector_16440a": frozenset({"open", "smu", "pgu", "pgu_open"}),
    "scuu": frozenset({"open", "smu", "cmu"}),
    "asu": frozenset({"smu", "cmu"}),
    "rsu": frozenset({"open", "smu", "wgfmu"}),
}
"""States each switch kind can take (``ERSSP`` 0-3; SCUU paths per output of PG Table 4-30; ASU ``SAP`` 0 = SMU,
1 = AUX, written ``cmu`` when the AUX input carries the MFCMU; RSU connected to the WGFMU, the SMU or open)."""

SWITCH_INPUTS: Final[dict[str, frozenset[str]]] = {
    "selector_16440a": frozenset({"smu", "pgu"}),
    "scuu": frozenset({"smu", "cmu"}),
    "asu": frozenset({"smu", "cmu"}),
    "rsu": frozenset({"smu", "wgfmu"}),
}
"""Input sides each switch kind has."""

STATE_INPUT: Final[dict[str, str | None]] = {
    "open": None, "smu": "smu", "pgu": "pgu", "pgu_open": "pgu", "cmu": "cmu", "wgfmu": "wgfmu",
}  # fmt: skip
"""The input a state connects to the output (``None`` for ``open``)."""

SELECTOR_PORTS: Final = range(4)
"""``ERSSP`` ports: 0/1 = first selector output 1/2, 2/3 = second selector output 1/2 (PG p433 (4-115))."""

PGU_OPEN_PORTS: Final = frozenset({0, 2})
"""Selector ports with the PGU-open state: CH 1 of each selector (PG p154 (2-66))."""

SELECTOR_SETTLE_S: Final = 0.01
"""Time a 16440A output needs after an ``ERSSP`` change before the new path carries the signal (mechanical relays;
break before make, so the output is open meanwhile). The manual gives no switching time (SEL p27-29 list none):
10 ms is a conservative relay figure, TODO(verify)[L7.A4] (``relay_settle``, by scope). The transaction waits it
after every selector change; the simulator keeps a switched output open for this long."""

SELECTOR_KIND: Final = "selector_16440a"
"""``SwitchSpec.kind`` of the 16440A SMU/PGU selector."""

RSU_KIND: Final = "rsu"
"""``SwitchSpec.kind`` of the B1531A remote-sense and switch unit of a WGFMU channel."""


def split_switch_target(target: str) -> tuple[str, str] | None:
    """``("SEL1", "OUT1")`` for a switch target ``"SEL1.OUT1"``; ``None`` for anything else (channels, ``GNDU``)."""
    if not isinstance(target, str) or target.count(".") != 1:
        return None
    switch, output = target.split(".")
    return (switch, output) if switch and output else None


class SwitchPort(StrictModel):
    """One DUT-side output of a switch: its hardware index and the channel wired to each input side.

    ``index`` is the ``ERSSP`` port (0-3) for a selector, the SMU channel for an SCUU or ASU output and the WGFMU
    channel for an RSU. ``inputs`` maps an input side to the channel wired to it; ``None`` means the wiring is unknown
    (routes through it are blocked on hardware until a human records it), an absent side is not connected.
    """

    index: int = Field(ge=0)
    inputs: dict[SwitchInput, Channel | None] = Field(default_factory=dict)


class SwitchSpec(StrictModel):
    """A switch accessory in ``station.yaml#switches`` (blueprint v2 2.3).

    ``present``: ``True`` installed, ``False`` declared absent, ``None`` unknown (routes through it are blocked on the
    visa backend, R-ROUTE-01). ``certainty: verified`` only after a human has checked the wiring; then no input may be
    ``None``. Any plan involving an ``unverified`` switch needs confirmation (``unverified_topology``, R-ROUTE-02).
    ``rest`` is the state the transaction cleanup restores and verifies on every declared output.
    """

    id: Alias
    kind: SwitchKind
    present: bool | None
    certainty: Literal["verified", "unverified"] = "unverified"
    ports: dict[SwitchOutput, SwitchPort] = Field(min_length=1)
    rest: SwitchState = "open"
    note: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> SwitchSpec:
        states, inputs = SWITCH_STATES[self.kind], SWITCH_INPUTS[self.kind]
        if self.rest not in states:
            raise ValueError(f"A {self.kind} has no state {self.rest!r}; states: {sorted(states)}.")
        indices = [port.index for port in self.ports.values()]
        if len(set(indices)) != len(indices):
            raise ValueError(f"Switch {self.id}: a port index is used twice.")
        for output, port in self.ports.items():
            unknown = sorted(set(port.inputs) - inputs)
            if unknown:
                raise ValueError(f"{self.id}.{output}: a {self.kind} has no input {unknown}; inputs: {sorted(inputs)}.")
            if self.kind == "selector_16440a" and port.index not in SELECTOR_PORTS:
                raise ValueError(f"{self.id}.{output}: selector port {port.index} is not 0-3 (ERSSP).")
            if self.kind == "rsu" and port.inputs.get("wgfmu", port.index) != port.index:
                raise ValueError(f"{self.id}.{output}: an RSU's wgfmu input is the WGFMU channel of its index.")
            if self.certainty == "verified" and any(ch is None for ch in port.inputs.values()):
                raise ValueError(f"{self.id}.{output}: a verified switch cannot have unknown (null) inputs.")
            if not self.allows(output, self.rest):
                raise ValueError(f"{self.id}.{output}: the rest state {self.rest!r} is not available on this output.")
        if self.kind == "asu" and self.rest != "smu":
            raise ValueError(f"Switch {self.id}: an ASU rests on its SMU side (rest smu): CL and CN return its path "
                             "there (PG p505 (4-187)), so no cleanup could keep another rest state.")
        return self

    def states(self) -> frozenset[str]:
        """The states this switch's outputs can take."""
        return SWITCH_STATES[self.kind]

    def allows(self, output: str, state: str) -> bool:
        """True when ``output`` exists and can take ``state`` (``pgu_open`` only on selector CH 1 ports 0 and 2)."""
        port = self.ports.get(output)
        if port is None or state not in self.states():
            return False
        return not (state == "pgu_open" and port.index not in PGU_OPEN_PORTS)

    def at_rest(self, output: str, state: str) -> bool:
        """True when ``state`` read back on ``output`` counts as rest: the ``rest`` state itself, or, for an SCUU,
        both outputs open (the power-on and ``*RST`` state: no ``SSP`` path sets it, it connects nothing, and the
        cleanup leaves it alone rather than switch an SMU on just to reach ``rest``; PG p520 (4-202))."""
        if output not in self.ports:
            return False
        return state == self.rest or (self.kind == "scuu" and state == "open")

    def input_channel(self, output: str, state: str) -> Channel | None:
        """The channel ``state`` connects to ``output`` (``None`` when open, not wired or unknown)."""
        port = self.ports.get(output)
        side = STATE_INPUT.get(state)
        if port is None or side is None:
            return None
        return port.inputs.get(side)  # type: ignore[call-overload]


class RsuSmuInput(NamedTuple):
    """The "From SMU" input of one RSU output (WG p20 (1-8)): ``channel`` is the SMU whose Force is cabled there,
    ``None`` when the station records the wiring as unknown (``inputs.smu: null``)."""

    switch: str
    output: str
    channel: int | None

    @property
    def target(self) -> str:
        """The RSU output, e.g. ``RSU201.OUT``."""
        return f"{self.switch}.{self.output}"


def same_channel(a: int, b: int) -> bool:
    """True when ``a`` and ``b`` address the same channel (PG Table 4-1: ``n`` and ``n*100+1`` are one subchannel)."""
    return (a * 100 + 1 if 1 <= a <= 10 else a) == (b * 100 + 1 if 1 <= b <= 10 else b)


def rsu_smu_inputs(switches: Iterable[SwitchSpec]) -> list[RsuSmuInput]:
    """The From SMU inputs of every RSU output the station does not record absent (``present`` true or unknown), in
    declaration order. An output without an ``smu`` input side has nothing cabled there and is left out; ``null``
    comes back as ``channel=None`` (unknown wiring).

    The input takes at most +-25 V ("Or the RSU will be damaged", WG p20 (1-8)) and the SMU path 100 mA (WG p16
    (1-4) "SMU mode") whatever the RSU's state: the SMU cabled there sees the input even while the RSU is on its
    WGFMU path or open. R-RSU-01 and ``OutputGuard`` hold that SMU to it."""
    found: list[RsuSmuInput] = []
    for switch in switches:
        if switch.kind != RSU_KIND or switch.present is False:
            continue
        for output, port in switch.ports.items():
            if "smu" in port.inputs:
                found.append(RsuSmuInput(switch.id, output, port.inputs["smu"]))
    return found


def rsu_inputs_of(switches: Iterable[SwitchSpec], channel: int) -> list[RsuSmuInput]:
    """The RSU From SMU inputs (``rsu_smu_inputs``) that the station records ``channel`` as cabled to."""
    return [item for item in rsu_smu_inputs(switches)
            if item.channel is not None and same_channel(item.channel, channel)]


class Route(StrictModel):
    """One switch output in one state; frozen and hashable, so plans keep routes in sets."""

    switch: Alias
    output: SwitchOutput
    state: SwitchState

    @property
    def target(self) -> str:
        """The pin-map target this route serves, e.g. ``SEL1.OUT1``."""
        return f"{self.switch}.{self.output}"

    def sort_key(self) -> tuple[str, str, str]:
        """Deterministic order for serialisation and summaries."""
        return (self.switch, self.output, self.state)

    def __str__(self) -> str:
        return f"{self.switch}.{self.output}->{self.state}"
