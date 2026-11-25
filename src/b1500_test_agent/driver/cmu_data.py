"""MFCMU measurement data and query answers: impedance pairs per ``IMP`` model, monitor values, CMU status codes,
and the small MFCMU/SCUU answers ``CORR?``, ``*LRN? 81`` (SCUU path) and ``*LRN? 90`` (phase compensation mode)
(blueprint v2 2.5, 2.10; WP8.1), plus the correction set-up queries ``CORRL?`` and ``DCORR?`` (WP8.2) and the
correction data query ``CORRDT?`` (WP8.6).

Formats from the Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages):

- A CMU data item is ``Para1,Para2[,Osc_level,Dc_bias]`` (PDF 47-48): the primary and secondary parameter of the
  ``IMP`` mode (Table 4-16, PDF 347), then, with ``LMN 1`` and only in MM 17, 18, 22, 23, the monitored oscillator
  level and DC bias (both data type ``V``). Per block (one spot, one sweep step, one sample) the elements are
  ``[Sampling_no,][Time,]Para1,Para2[,Osc_level,Dc_bias][,[Time,]SMU data ...][,Source_data]``: ``Sampling_no``
  (type ``X``) only in C-t sampling (MM 26) with ``FMT`` mode != 0 (PDF 49), ``Time`` (type ``T``) when ``TSC 1``
  is on (PDF 46), SMU data only in MM 18 after the MFCMU (MM order, PDF 471), ``Source_data`` (status ``W``/``E``;
  type ``V`` for a DC or AC level, ``F`` for a frequency) with ``FMT`` mode 1 in the sweep modes 18, 20, 22, 23
  (PDF 48). The manual's examples confirm the layouts: spot C (5 elements with ``TSC 1`` + ``LMN 1``, PDF 255),
  C-V sweep (6 per step with ``FMT 1,1``, PDF 259), pulsed sweep C-V (4 per step: no monitor in MM 20, PDF 268), C-f
  and AC level sweeps (6 per step, PDF 273, 278), C-t sampling (index, time, Cp, G, PDF 283); their printed result
  rows show the element headers ``NJC``/``NGC`` (Cp), ``NJY``/``NGY`` (G) and ``NJV``/``NGV`` (monitors).
- Data type letters (Table 1-12, PDF 55) of each parameter: R, X, Z, Rp, Rs ``Z``; G, B, Y ``Y``; Cp, Cs ``C``;
  Lp, Ls ``L``; theta ``R`` (radian) or ``P`` (degree); D ``D``; Q ``Q``.
- CMU status letters (Table 1-10, PDF 53): ``N`` no error, ``U`` NULL loop unbalance, ``D`` IV amplifier saturation,
  ``V`` over range or sweep aborted (value ``199.999E+99``); the three-digit FMT 21/25 codes are
  ``parser.CmuStatus`` (Table 1-9, PDF 52). The manual ranks only SMU statuses; the CMU order used here is
  ``N < U < D < X < V`` (an invalid value is the worst).

The run table (``analysis/dataset.py`` contract) keeps the MFCMU quantities ``Cp``, ``G``, ``Cs``, ``Rs``, ``D``,
``Z`` and ``theta`` (radian): ``TABLE_IMP_MODES`` maps the ``IMP`` modes that produce them (100, 101, 200, 201,
10, 11) and ``CmuReading.table_values`` converts mode 11's degrees to radian (WP5.7 handoff). The parser shares no
code with the simulator's formatter (``transport/sim/units/cmu_engine.py``). ATV-22: the layouts come from the
manual's example programs; TODO(verify) against raw FMT 1 blocks captured at bring-up L6 (``bringup capture``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.flex import CORR_RESULTS, IMP_MODES, LRN_ADJ_ITEM, LRN_SCUU_ITEM
from b1500_test_agent.driver.parser import MeasurementPoint, SourceDataStatus


@dataclass(frozen=True)
class ImpedanceParameter:
    """One parameter of an ``IMP`` mode: Table 4-16 name, Table 1-12 data-type letter, unit, and the run-table
    quantity it becomes (``None`` when the data contract has no column for it)."""

    name: str
    data_type: str
    unit: str
    table: str | None


_PARAMETERS: Final[dict[str, ImpedanceParameter]] = {
    "R": ImpedanceParameter("R", "Z", "Ohm", None),
    "X": ImpedanceParameter("X", "Z", "Ohm", None),
    "G": ImpedanceParameter("G", "Y", "S", "G"),
    "B": ImpedanceParameter("B", "Y", "S", None),
    "Z": ImpedanceParameter("Z", "Z", "Ohm", "Z"),
    "Y": ImpedanceParameter("Y", "Y", "S", None),
    "theta_rad": ImpedanceParameter("theta", "R", "rad", "theta"),
    "theta_deg": ImpedanceParameter("theta", "P", "deg", "theta"),
    "Cp": ImpedanceParameter("Cp", "C", "F", "Cp"),
    "Cs": ImpedanceParameter("Cs", "C", "F", "Cs"),
    "Lp": ImpedanceParameter("Lp", "L", "H", None),
    "Ls": ImpedanceParameter("Ls", "L", "H", None),
    "D": ImpedanceParameter("D", "D", "1", "D"),
    "Q": ImpedanceParameter("Q", "Q", "1", None),
    "Rp": ImpedanceParameter("Rp", "Z", "Ohm", None),
    "Rs": ImpedanceParameter("Rs", "Z", "Ohm", "Rs"),
}

IMP_PARAMETERS: Final[dict[int, tuple[ImpedanceParameter, ImpedanceParameter]]] = {
    mode: (_PARAMETERS[primary], _PARAMETERS[secondary]) for mode, (primary, secondary) in IMP_MODES.items()
}
"""Every ``IMP`` mode (Table 4-16, PDF 347) -> its (primary, secondary) parameter with data type and unit."""

TABLE_IMP_MODES: Final = frozenset(m for m, (p, s) in IMP_PARAMETERS.items() if p.table and s.table)
"""``IMP`` modes whose both parameters are run-table quantities: 10, 11 (Z-theta), 100 (Cp-G), 101 (Cp-D), 200
(Cs-Rs), 201 (Cs-D)."""

MONITOR_MODES: Final = frozenset({17, 18, 22, 23})
"""Measurement modes where ``LMN 1`` adds ``Osc_level``/``Dc_bias`` to each MFCMU item (PG PDF 445)."""

SOURCE_MODES: Final = frozenset({18, 20, 22, 23})
"""MFCMU sweep modes that append ``Source_data`` with ``FMT`` mode 1 (PDF 48)."""

SOURCE_DATA_TYPES: Final[dict[int, str]] = {18: "V", 20: "V", 22: "F", 23: "V"}
"""Data type of the sweep source value per mode: the DC bias (18, 20) and AC level (23) in V, the frequency (22) in
Hz (Table 1-12, PDF 55)."""

CMU_STATUS_SEVERITY: Final = "NUDXV"
"""CMU status letters, least severe first (see the module docstring; ``V`` = the value has no meaning)."""


def worst_cmu_status(points: Sequence[MeasurementPoint]) -> str:
    """The most severe CMU status letter of ``points`` (``N`` when empty); letters outside ``CMU_STATUS_SEVERITY``
    (SMU-only letters) rank just below ``V``."""
    rank = {letter: i for i, letter in enumerate(CMU_STATUS_SEVERITY)}
    letters = [point.status.value for point in points]
    return max(letters, key=lambda s: rank.get(s, len(CMU_STATUS_SEVERITY) - 1.5), default="N")


@dataclass(frozen=True)
class CmuLayout:
    """Which elements a CMU data block holds (see the module docstring): ``imp`` the ``IMP`` mode, ``mode`` the
    ``MM`` mode, ``monitor`` = ``LMN 1``, ``source`` = ``FMT`` mode 1 (source data), ``timestamp`` = ``TSC 1``,
    ``index`` = ``FMT`` mode != 0 (sampling index, C-t only), ``smu_channels`` the extra SMU channels of MM 18."""

    imp: int
    mode: int
    monitor: bool = False
    source: bool = False
    timestamp: bool = False
    index: bool = False
    smu_channels: int = 0

    def __post_init__(self) -> None:
        if self.imp not in IMP_PARAMETERS:
            raise ValueError(f"IMP mode {self.imp} is not in PG Table 4-16")
        if self.mode not in (17, 18, 19, 20, 22, 23, 26):
            raise ValueError(f"measurement mode {self.mode} is not an MFCMU mode (17-26)")
        if self.smu_channels and self.mode != 18:
            raise ValueError("only the C-V (DC bias) sweep, mode 18, has SMU measurement channels")
        if not 0 <= self.smu_channels <= 9:
            raise ValueError("mode 18 takes at most nine SMU channels after the MFCMU")

    @property
    def has_monitor(self) -> bool:
        return self.monitor and self.mode in MONITOR_MODES

    @property
    def has_source(self) -> bool:
        return self.source and self.mode in SOURCE_MODES

    @property
    def has_index(self) -> bool:
        return self.index and self.mode == 26

    @property
    def width(self) -> int:
        """Elements per block."""
        stamp = 1 if self.timestamp else 0
        return (int(self.has_index) + stamp + 2 + 2 * int(self.has_monitor) + self.smu_channels * (1 + stamp)
                + int(self.has_source))


@dataclass(frozen=True)
class CmuReading:
    """One block of MFCMU data: the parameter pair and the optional elements around it (all ``MeasurementPoint``s,
    so status, channel and raw text stay available)."""

    imp: int
    primary: MeasurementPoint
    secondary: MeasurementPoint
    osc: MeasurementPoint | None = None
    dc: MeasurementPoint | None = None
    time: MeasurementPoint | None = None
    index: MeasurementPoint | None = None
    smu: tuple[MeasurementPoint, ...] = ()
    source: MeasurementPoint | None = None

    @property
    def parameters(self) -> tuple[ImpedanceParameter, ImpedanceParameter]:
        return IMP_PARAMETERS[self.imp]

    @property
    def status(self) -> str:
        """The worst CMU status of the parameter pair."""
        return worst_cmu_status([self.primary, self.secondary])

    @property
    def invalid(self) -> bool:
        """True when a parameter carries the meaningless ``199.999E+99`` (status ``V``)."""
        return self.primary.invalid or self.secondary.invalid

    def table_values(self) -> dict[str, tuple[float, str]]:
        """Run-table quantities of the pair: ``{quantity: (value, status letter)}``, theta in radian (mode 11's
        degrees converted; an invalid value stays ``199.999E+99``).

        Raises:
            ValueError: If the ``IMP`` mode has no run-table quantities (``TABLE_IMP_MODES``).
        """
        if self.imp not in TABLE_IMP_MODES:
            raise ValueError(f"impedance mode {self.imp} ({'-'.join(p.name for p in self.parameters)}) has no "
                             f"run-table columns; use one of {sorted(TABLE_IMP_MODES)}")
        values: dict[str, tuple[float, str]] = {}
        for point, parameter in zip((self.primary, self.secondary), self.parameters, strict=True):
            value = point.value
            if parameter.unit == "deg" and not point.invalid:
                value = math.radians(value)
            values[str(parameter.table)] = (value, point.status.value)
        return values


class _Block:
    """The elements of one block, consumed in order by ``take``."""

    def __init__(self, points: Sequence[MeasurementPoint]) -> None:
        self.points = list(points)
        self.raw = ",".join(p.raw for p in self.points)

    def take(self, data_types: str, what: str, *, source: bool = False) -> MeasurementPoint:
        point = self.points.pop(0)
        if point.data_type not in data_types:
            raise FlexParseError(f"{what}: data type {point.data_type!r} where {data_types!r} was expected",
                                 raw=self.raw)
        if isinstance(point.status, SourceDataStatus) != source:
            raise FlexParseError(f"{what}: status {point.status.value!r} does not fit", raw=self.raw)
        return point


def parse_cmu_blocks(points: Sequence[MeasurementPoint], layout: CmuLayout) -> list[CmuReading]:
    """Group the elements of one MFCMU data response (``parser.parse_data`` output) into readings.

    Checks the element count (a multiple of ``layout.width``), every data-type letter against the layout and the
    ``IMP`` mode (Table 1-12, PDF 55), that all parameter elements name one channel, and that only ``Source_data``
    carries ``W``/``E``.

    Raises:
        FlexParseError: On any mismatch; ``raw`` holds the offending elements.
    """
    width = layout.width
    if len(points) % width:
        raise FlexParseError(f"{len(points)} elements are not a multiple of the {width}-element MFCMU block",
                             raw=",".join(p.raw for p in points))
    first, second = IMP_PARAMETERS[layout.imp]
    readings: list[CmuReading] = []
    channel: str | None = None
    for start in range(0, len(points), width):
        block = _Block(points[start:start + width])
        index = block.take("X", "sampling index") if layout.has_index else None
        time = block.take("T", "time stamp") if layout.timestamp else None
        primary = block.take(first.data_type, f"primary {first.name}")
        secondary = block.take(second.data_type, f"secondary {second.name}")
        channel = channel or primary.channel
        if {primary.channel, secondary.channel} != {channel}:
            raise FlexParseError("MFCMU parameters of one response name different channels", raw=block.raw)
        osc = block.take("V", "oscillator level monitor") if layout.has_monitor else None
        dc = block.take("V", "DC bias monitor") if layout.has_monitor else None
        smu: list[MeasurementPoint] = []
        for n in range(layout.smu_channels):
            if layout.timestamp:
                block.take("T", f"time stamp of SMU data {n + 1}")
            smu.append(block.take("IV", f"SMU data {n + 1}"))
        source = (block.take(SOURCE_DATA_TYPES[layout.mode], "source data", source=True) if layout.has_source
                  else None)
        readings.append(CmuReading(imp=layout.imp, primary=primary, secondary=secondary, osc=osc, dc=dc, time=time,
                                   index=index, smu=tuple(smu), source=source))
    return readings


# -- small query answers ---------------------------------------------------------------------------------------------

_INT_RE = re.compile(r"^\+?(?P<value>\d+)$")
_LRN_ITEM_RE = re.compile(r"^(?P<mnemonic>[A-Z]+)\s*(?P<params>[-+0-9.,E ]*)$")


def parse_corr_result(text: str) -> int:
    """``CORR? chnum,corr`` -> 0 completed, 1 failed, 2 aborted (PG PDF 383, ``flex.CORR_RESULTS``).

    Raises:
        FlexParseError: If the answer is not one of those integers (a leading ``+`` is accepted).
    """
    match = _INT_RE.match(text.strip())
    value = int(match.group("value")) if match else None
    if value not in CORR_RESULTS:
        raise FlexParseError(f"correction data measurement result (CORR?) is not 0, 1 or 2: {text!r}", raw=text)
    return value


def parse_corrl_count(text: str) -> int:
    """``CORRL? chnum`` -> the number of frequencies in the correction frequency list (PG PDF 385).

    Raises:
        FlexParseError: If the answer is not a non-negative integer (a leading ``+`` is accepted).
    """
    match = _INT_RE.match(text.strip())
    if match is None:
        raise FlexParseError(f"correction frequency count (CORRL?) is not a non-negative integer: {text!r}", raw=text)
    return int(match.group("value"))


def _number(text: str, what: str) -> float:
    try:
        value = float(text.strip())
    except ValueError:
        value = math.nan
    if not math.isfinite(value):
        raise FlexParseError(f"{what} is not a finite number: {text!r}", raw=text)
    return value


def parse_corrl_frequency(text: str) -> float:
    """``CORRL? chnum,index`` -> the frequency (Hz) at that position of the correction list (PG PDF 385).

    Raises:
        FlexParseError: If the answer is not a positive finite number.
    """
    value = _number(text, "correction list frequency (CORRL?)")
    if value <= 0:
        raise FlexParseError(f"correction list frequency (CORRL?) is not positive: {text!r}", raw=text)
    return value


def parse_dcorr(text: str) -> tuple[int, float, float]:
    """``DCORR? chnum,corr`` -> ``(mode, primary, secondary)`` of the standard's reference value: mode 100 (open: Cp
    in F, G in S) or 400 (short/load: Ls in H, Rs in Ohm) (PG PDF 389-390).

    Raises:
        FlexParseError: If the answer is not three comma-separated numbers with mode 100 or 400.
    """
    parts = text.strip().split(",")
    if len(parts) != 3:
        raise FlexParseError(f"standard reference value (DCORR?) is not mode,primary,secondary: {text!r}", raw=text)
    mode = _number(parts[0], "standard reference mode (DCORR?)")
    if mode not in (100.0, 400.0):
        raise FlexParseError(f"standard reference mode (DCORR?) is not 100 or 400: {text!r}", raw=text)
    return int(mode), _number(parts[1], "standard primary value (DCORR?)"), \
        _number(parts[2], "standard secondary value (DCORR?)")


@dataclass(frozen=True)
class CorrectionData:
    """The correction data of one listed frequency (``CORRDT?``; PG PDF 384): the open as admittance ``G + jB`` (S),
    the short and the load as impedance ``R + jX`` (Ohm), as measured by ``CORR?`` (or set by ``CORRDT``). A
    correction never measured answers 0 (TODO(verify) at bring-up L6)."""

    freq_hz: float
    open_g: float
    open_b: float
    short_r: float
    short_x: float
    load_r: float
    load_x: float

    @property
    def open_cp_f(self) -> float:
        """Stray capacitance of the open path, ``B / (2 pi f)`` (F)."""
        return self.open_b / (2.0 * math.pi * self.freq_hz)

    @property
    def short_ls_h(self) -> float:
        """Series inductance of the short path, ``X / (2 pi f)`` (H)."""
        return self.short_x / (2.0 * math.pi * self.freq_hz)

    @property
    def load_ls_h(self) -> float:
        """Series inductance of the load reading, ``X / (2 pi f)`` (H)."""
        return self.load_x / (2.0 * math.pi * self.freq_hz)


def parse_correction_data(text: str) -> CorrectionData:
    """``CORRDT? chnum,index`` -> ``CorrectionData`` from ``freq,open_r,open_i,short_r,short_i,load_r,load_i`` (PG PDF
    384).

    Raises:
        FlexParseError: If the answer is not seven finite numbers with a positive frequency.
    """
    parts = text.strip().split(",")
    if len(parts) != 7:
        raise FlexParseError(f"correction data (CORRDT?) is not freq and six values: {text!r}", raw=text)
    values = [_number(part, "correction data value (CORRDT?)") for part in parts]
    if values[0] <= 0:
        raise FlexParseError(f"correction data frequency (CORRDT?) is not positive: {text!r}", raw=text)
    return CorrectionData(*values)


def _canonical(channel: int) -> int:
    return channel // 100 if channel > 10 and channel % 100 == 1 else channel


def parse_lrn_channel_items(text: str, mnemonic: str) -> dict[int, list[float]]:
    """``{channel: [parameters after it]}`` of every ``<mnemonic> chnum,value...`` item of a ``*LRN?`` answer
    (``;``-separated, with or without a blank after the mnemonic; PG PDF 452). Other items are ignored; an empty
    answer has none. Channels ``701`` and ``7`` are the same channel (Table 4-1).

    Raises:
        FlexParseError: If an item of ``mnemonic`` is malformed or names a channel twice.
    """
    found: dict[int, list[float]] = {}
    for item in (part.strip() for part in text.strip().split(";")):
        match = _LRN_ITEM_RE.match(item) if item else None
        if match is None or match.group("mnemonic") != mnemonic:
            continue
        try:
            numbers = [float(p) for p in match.group("params").replace(" ", "").split(",")]
        except ValueError:
            raise FlexParseError(f"*LRN? item {item!r} has non-numeric parameters", raw=text) from None
        if len(numbers) < 2 or numbers[0] != int(numbers[0]):
            raise FlexParseError(f"*LRN? item {item!r} lacks 'chnum,value'", raw=text)
        channel = _canonical(int(numbers[0]))
        if channel in found:
            raise FlexParseError(f"*LRN? answer names channel {channel} twice for {mnemonic}", raw=text)
        found[channel] = numbers[1:]
    return found


def parse_adj_mode(text: str, ch: int) -> int:
    """The phase compensation mode of MFCMU ``ch`` from a ``*LRN? 90`` answer (``ADJ chnum,mode``; 0 auto, 1 manual,
    2 load adaptive; PG PDF 452, 355).

    Raises:
        FlexParseError: If the answer has no valid ``ADJ`` item for ``ch``.
    """
    items = parse_lrn_channel_items(text, LRN_ADJ_ITEM)
    values = items.get(_canonical(ch))
    if values is None or len(values) != 1 or values[0] not in (0, 1, 2):
        raise FlexParseError(f"the learn answer of the phase compensation mode has no item for channel {ch} with "
                             f"mode 0, 1 or 2: {text!r}", raw=text)
    return int(values[0])


def parse_scuu_path(text: str, ch: int) -> int | None:
    """The SCUU path (``SSP`` 1-4) of the SCUU on MFCMU ``ch`` from a ``*LRN? 81`` answer (``SSP chnum,mode``; PG
    PDF 452, 520); ``None`` when the answer has no item for ``ch`` or reports 0 (outputs open: the power-on state
    that no ``SSP`` sets). TODO(verify) at bring-up L6 (SCUU present) what the instrument answers for the open state.

    Raises:
        FlexParseError: If the item is malformed or its path is not 0-4.
    """
    values = parse_lrn_channel_items(text, LRN_SCUU_ITEM).get(_canonical(ch))
    if values is None:
        return None
    if len(values) != 1 or values[0] not in (0, 1, 2, 3, 4):
        raise FlexParseError(f"the learn answer of the SCUU path for channel {ch} is not one path 0-4: {text!r}",
                             raw=text)
    return int(values[0]) or None
