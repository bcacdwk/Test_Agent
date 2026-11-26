"""Parsers for the identification, inventory and output-state queries (blueprint 2.3 group A).

Formats from the Keysight B1500 Series Programming Guide, Edition 15 ("PG"; PDF pages are physical pages of
``B1500A Programming Guide.pdf``):

- ``*IDN?`` (PDF 440, printed 4-122): ``manufacturer,model,0,revision``; manual example
  ``Agilent Technologies,B1500A,0,A.04.03.2010.0130``.
- ``UNT? [mode]`` (PDF 545, printed 4-227): ``[FrameModel,FrameRevision;]Slot1Model,Slot1Revision;...;
  Slot10Model,Slot10Revision``. The manual prints no example; an empty slot is assumed to read ``0,0`` (model
  ``0``). Confirm with the raw capture at M4 L0.
- ``LOP?`` (PDF 446-447, printed 4-128 to 4-129): ``LOP`` followed by ten two-digit codes, one per slot (Table 4-26);
  manual example ``LOP00,11,00,00,00,00,00,00,00,00``. ``00`` = no module or output switch OFF; any other code means
  the switch is ON (01-03 forcing, 11-13 in compliance, 20 oscillating, 40/51/52 MFCMU states). A module occupying
  two slots (HPSMU, HCSMU, HVSMU) reports ``00`` in its first slot and its status in the second.

- ``*LRN? 31`` (PDF 448, printed 4-130): ``TM trigger mode;AV number[,mode];CM auto calibration mode;FMT format,
  mode[;MM mode[,chnum...]]`` (``;``-separated items, each a mnemonic followed by its comma-separated parameters).
  The manual prints the syntax with a blank after each mnemonic but no example; the parser accepts the item with
  or without the blank. TODO(verify) the exact response text with a raw capture at bring-up L1.

- Small-integer state queries of the bring-up probe (blueprint v2 7.1, WP6.1): ``ERMOD?`` (PDF 420-421, printed
  4-102 to 4-103: the sum of the enabled digital I/O control modes, 0-63), ``ERSSP? port`` (PDF 434, printed 4-116:
  0 open, 1 SMU, 2 PGU, 3 PGU open), ``SPST?`` (PDF 513-514, printed 4-195 to 4-196: 0 inactive, 1 active),
  ``CORRST? chnum,corr`` (PDF 388, printed 4-70: 0 OFF, 1 ON) and ``ADJ? chnum,mode`` (PDF 356, printed 4-38:
  0 completed, 1 failed, 2 aborted, 3 not performed). Each answers one integer; a leading ``+`` is accepted (the
  lab firmware signs ``ERRX?`` codes, so it may sign these too). TODO(verify) raw captures at bring-up L0.

- ASU state (WP7.1): ``*LRN? 62`` (PDF 451, printed 4-133) answers ``SAP chnum,path[;SAP chnum,path]...`` (path 0
  SMU, 1 AUX) and ``*LRN? 63`` ``SAR chnum,mode[;SAR chnum,mode]...`` (mode 0 = 1 pA auto ranging enabled, 1 =
  disabled), one item per SMU with an ASU. The manual prints no example and does not say what a mainframe without an
  ASU answers; the parser takes an empty answer (or the bare mnemonic) as "no ASU". TODO(verify) raw captures at
  bring-up L1/L2 (ATV-28, ASU presence).
- ``CORRSER? chnum,mode,delay,interval,count`` (PDF 386, printed 4-68): ``loadZ,voltage`` (the impedance calculated
  from the measured terminal voltage, and that voltage). Unused: no measurement kind calls
  ``SpguOps.measure_pulse_load``, so no bring-up stage sends or captures ``CORRSER?`` (v2.1 plan §4.6); the parser
  follows the manual's format, and a kind that starts to use it adds a capture step for its raw answer.

ATV-1 (``LOP?`` usable for cleanup verification) holds per the manual for SMU and MFCMU slots: after ``CL`` every
slot must read ``00``. Table 4-26 has no SPGU/WGFMU codes and reports per slot, not per subchannel, so those modules
(never sourced in v1) would need the ``*LRN? 0`` fallback (output-switch list). Hardware confirmation: M4 L1.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.flex import (
    ADJ_RESULTS,
    ASU_PATHS,
    ERMOD_MAX,
    ERMOD_Q,
    ERSSP_STATES,
    LOP_RESPONSE_PREFIX,
    LRN_ASU_1PA,
    LRN_ASU_PATH,
    LRN_AUTO_CALIBRATION,
    LRN_SETTINGS,
    SAP_RESPONSE,
    SAR_DISABLE_1PA,
    SAR_ENABLE_1PA,
    SAR_RESPONSE,
    SPST_Q,
    SPST_STATES,
    lrn_q,
)
from b1500_test_agent.models.routing import SwitchState
from b1500_test_agent.models.station import ChannelOutput, Identity, InstalledModule, ModuleInventory

SLOTS = 10
"""Number of module slots reported by ``UNT?`` and ``LOP?``."""

EMPTY_SLOT_MODEL = "0"
"""Model token of an empty slot in the ``UNT?`` answer (assumption; see the module docstring)."""

LOP_STATUS_CODES: dict[str, str] = {
    "00": "no module installed, or output switch OFF",
    "01": "SMU forces voltage, not in current compliance",
    "02": "SMU forces positive current, not in voltage compliance",
    "03": "SMU forces negative current, not in voltage compliance",
    "10": "not applicable",
    "11": "SMU reaches voltage compliance",
    "12": "SMU reaches positive current compliance",
    "13": "SMU reaches negative current compliance",
    "20": "SMU is oscillating",
    "30": "not applicable",
    "40": "MFCMU applies DC bias",
    "51": "MFCMU is in the NULL loop unbalance condition",
    "52": "MFCMU is in the IV amplifier saturation condition",
}
"""``LOP?`` status codes (PG Table 4-26, PDF 446)."""

OUTPUT_OFF_CODE = "00"

_LOP_RE = re.compile(rf"^{LOP_RESPONSE_PREFIX}\s?(?P<codes>\d{{2}}(?:,\d{{2}}){{{SLOTS - 1}}})$")
_LRN_ITEM_RE = re.compile(r"^(?P<mnemonic>\*?[A-Z]+)\s?(?P<params>[-+0-9.,Ee\s]*)$")
_SMALL_INT_RE = re.compile(r"^\+?(?P<value>\d{1,3})$")
_ASU_ITEM_RE = re.compile(r"^(?P<mnemonic>[A-Z]+)\s?\+?(?P<channel>\d{1,4}),\+?(?P<value>\d)$")


def parse_idn(text: str) -> Identity:
    """Parse ``*IDN?`` into ``Identity`` (vendor, model, serial field, firmware revision).

    Raises:
        FlexParseError: If the answer does not have exactly four comma-separated, non-empty fields.
    """
    stripped = text.strip()
    fields = [field.strip() for field in stripped.split(",")]
    if len(fields) != 4 or not fields[0] or not fields[1] or not fields[3]:
        raise FlexParseError(f"*IDN? answer is not 'manufacturer,model,0,revision': {text!r}", raw=text)
    return Identity(vendor=fields[0], model=fields[1], serial=fields[2], firmware=fields[3], raw=stripped)


def parse_unt(text: str, *, with_frame: bool = False) -> ModuleInventory:
    """Parse ``UNT?`` (``with_frame=False``, mode 0) or ``UNT? 1`` (``with_frame=True``) into ``ModuleInventory``.

    Empty slots (model ``0``) are left out; the frame entry of mode 1 is skipped.

    Raises:
        FlexParseError: If the answer does not list exactly ten slots (eleven entries with the frame) of
            ``model,revision`` pairs.
    """
    stripped = text.strip()
    entries = stripped.split(";")
    expected = SLOTS + (1 if with_frame else 0)
    if len(entries) != expected:
        raise FlexParseError(f"UNT? answer has {len(entries)} entries, expected {expected}: {text!r}", raw=text)
    modules: list[InstalledModule] = []
    for slot, entry in enumerate(entries[1:] if with_frame else entries, start=1):
        parts = [part.strip() for part in entry.split(",")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise FlexParseError(f"UNT? slot {slot} entry is not 'model,revision': {entry!r}", raw=text)
        model, revision = parts
        if model != EMPTY_SLOT_MODEL:
            modules.append(InstalledModule(slot=slot, model=model, revision=revision))
    return ModuleInventory(modules=modules, raw=stripped)


def parse_lop(text: str) -> dict[int, ChannelOutput]:
    """Parse ``LOP?`` into ``{slot: ChannelOutput}`` for slots 1-10 (the channel number of a one-slot module).

    ``output_on`` is ``False`` only for code ``00``; any other code, including codes the manual does not list, counts
    as ON so that verification fails safe.

    Raises:
        FlexParseError: If the answer is not ``LOP`` plus ten comma-separated two-digit codes.
    """
    stripped = text.strip()
    match = _LOP_RE.match(stripped)
    if match is None:
        raise FlexParseError(f"LOP? answer is not 'LOP' + ten two-digit codes: {text!r}", raw=text)
    codes = match.group("codes").split(",")
    return {
        slot: ChannelOutput(channel=slot, state=code, output_on=code != OUTPUT_OFF_CODE)
        for slot, code in enumerate(codes, start=1)
    }


def all_outputs_off(outputs: dict[int, ChannelOutput]) -> bool:
    """True when every reported slot is ``00`` (no module, or output switch OFF)."""
    return bool(outputs) and not any(output.output_on for output in outputs.values())


def parse_lrn_settings(text: str) -> dict[str, list[str]]:
    """Parse a ``*LRN?`` settings answer (type 31: ``TM...;AV...;CM...;FMT...[;MM...]``) into ``{mnemonic:
    [parameter, ...]}`` (parameters as text, blanks removed).

    Raises:
        FlexParseError: If an item is not a mnemonic followed by numeric parameters, or a mnemonic repeats.
    """
    stripped = text.strip()
    items = [item.strip() for item in stripped.split(";")]
    settings: dict[str, list[str]] = {}
    for item in items:
        match = _LRN_ITEM_RE.match(item)
        if match is None:
            raise FlexParseError(f"*LRN? item {item!r} is not a mnemonic with numeric parameters: {text!r}", raw=text)
        mnemonic = match.group("mnemonic")
        if mnemonic in settings:
            raise FlexParseError(f"*LRN? answer repeats {mnemonic}: {text!r}", raw=text)
        params = match.group("params").replace(" ", "")
        settings[mnemonic] = [p for p in params.split(",")] if params else []
    return settings


def parse_auto_calibration(text: str) -> bool:
    """The auto-calibration switch from a ``*LRN? 31`` answer: ``CM 1`` → ``True``, ``CM 0`` → ``False`` (PG PDF 379,
    448).

    Raises:
        FlexParseError: If the answer has no ``CM`` item or its mode is not 0 or 1.
    """
    settings = parse_lrn_settings(text)
    params = settings.get(LRN_AUTO_CALIBRATION)
    if params is None or len(params) != 1 or params[0].lstrip("+") not in ("0", "1"):
        raise FlexParseError(f"{lrn_q(LRN_SETTINGS)} answer has no '{LRN_AUTO_CALIBRATION} 0|1' item: {text!r}",
                             raw=text)
    return params[0].lstrip("+") == "1"


def _small_int(text: str, allowed: range | frozenset[int] | set[int], what: str) -> int:
    """One unsigned integer answer (optional ``+``) from ``allowed``; ``FlexParseError`` otherwise."""
    stripped = text.strip()
    match = _SMALL_INT_RE.match(stripped)
    value = int(match.group("value")) if match is not None else None
    if value is None or value not in allowed:
        raise FlexParseError(f"{what} answer is not one of {sorted(allowed)}: {text!r}", raw=text)
    return value


def parse_ermod(text: str) -> int:
    """``ERMOD?`` -> the sum of the enabled digital I/O control modes, 0 to 63 (PG PDF 421); bit value 1 is the
    16440A selector control mode (``flex.ERMOD_SELECTOR``).

    Raises:
        FlexParseError: If the answer is not an integer from 0 to 63.
    """
    return _small_int(text, range(ERMOD_MAX + 1), ERMOD_Q)


def parse_erssp(text: str) -> SwitchState:
    """``ERSSP? port`` -> the selector output state: ``open``, ``smu``, ``pgu`` or ``pgu_open`` (PG PDF 434).

    Raises:
        FlexParseError: If the answer is not 0, 1, 2 or 3.
    """
    return ERSSP_STATES[_small_int(text, set(ERSSP_STATES), "selector state (ERSSP?)")]


def parse_spst(text: str) -> bool:
    """``SPST?`` -> ``True`` while an SPGU pulse or ALWG sequence output is active (answer 1; PG PDF 513-514).

    Raises:
        FlexParseError: If the answer is not 0 or 1.
    """
    return _small_int(text, SPST_STATES, SPST_Q) == 1


def parse_corrst(text: str) -> bool:
    """``CORRST? chnum,corr`` -> ``True`` when the correction function is ON (answer 1; PG PDF 388).

    Raises:
        FlexParseError: If the answer is not 0 or 1.
    """
    return _small_int(text, {0, 1}, "correction state (CORRST?)") == 1


def parse_adj(text: str) -> int:
    """``ADJ? chnum,mode`` -> the phase compensation result code (PG PDF 356, ``flex.ADJ_RESULTS``): 0 completed,
    1 failed, 2 aborted, 3 not performed.

    Raises:
        FlexParseError: If the answer is not 0, 1, 2 or 3.
    """
    return _small_int(text, set(ADJ_RESULTS), "phase compensation result (ADJ?)")


def _asu_items(text: str, mnemonic: str, kind: int, allowed: set[int]) -> dict[int, int]:
    """``{channel: value}`` of a ``*LRN? 62|63`` answer (``<mnemonic> chnum,value`` items separated by ``;``)."""
    stripped = text.strip()
    if stripped in ("", mnemonic):
        return {}
    found: dict[int, int] = {}
    for item in (part.strip() for part in stripped.split(";")):
        match = _ASU_ITEM_RE.match(item)
        if match is None or match.group("mnemonic") != mnemonic:
            raise FlexParseError(f"{lrn_q(kind)} item {item!r} is not '{mnemonic} chnum,value': {text!r}", raw=text)
        channel, value = int(match.group("channel")), int(match.group("value"))
        channel = channel // 100 if channel > 10 and channel % 100 == 1 else channel
        if value not in allowed or channel in found:
            raise FlexParseError(f"{lrn_q(kind)} answer has a bad or repeated item {item!r}: {text!r}", raw=text)
        found[channel] = value
    return found


def parse_asu_paths(text: str) -> dict[int, SwitchState]:
    """``*LRN? 62`` -> ``{smu channel: "smu" | "cmu"}``, one entry per SMU with an ASU (path 0 = SMU, 1 = AUX, written
    ``cmu``; PG PDF 451, 505-506). An empty answer means no ASU (module docstring).

    Raises:
        FlexParseError: If an item is not ``SAP chnum,0|1`` or a channel repeats.
    """
    return {ch: ASU_PATHS[path] for ch, path in _asu_items(text, SAP_RESPONSE, LRN_ASU_PATH, set(ASU_PATHS)).items()}


def parse_asu_1pa(text: str) -> dict[int, bool]:
    """``*LRN? 63`` -> ``{smu channel: 1 pA auto ranging enabled}``, one entry per SMU with an ASU (``SAR`` mode 0 =
    enabled, 1 = disabled; PG PDF 451, 506).

    Raises:
        FlexParseError: If an item is not ``SAR chnum,0|1`` or a channel repeats.
    """
    items = _asu_items(text, SAR_RESPONSE, LRN_ASU_1PA, {SAR_ENABLE_1PA, SAR_DISABLE_1PA})
    return {ch: mode == SAR_ENABLE_1PA for ch, mode in items.items()}


@dataclass(frozen=True)
class LoadMeasurement:
    """``CORRSER?`` answer: the load impedance the SPGU calculated (Ohm) and the terminal voltage it measured (V)."""

    load_ohm: float
    voltage_v: float


def parse_corrser(text: str) -> LoadMeasurement:
    """``CORRSER? ...`` -> ``LoadMeasurement`` from ``loadZ,voltage`` (PG PDF 386).

    Raises:
        FlexParseError: If the answer is not two finite numbers with a positive impedance.
    """
    parts = [part.strip() for part in text.strip().split(",")]
    try:
        load, voltage = (float(part) for part in parts) if len(parts) == 2 else (math.nan, math.nan)
    except ValueError:
        load = voltage = math.nan
    if not (math.isfinite(load) and math.isfinite(voltage) and load > 0):
        raise FlexParseError(f"CORRSER? answer is not 'loadZ,voltage' with a positive impedance: {text!r}",
                             raw=text)
    return LoadMeasurement(load_ohm=load, voltage_v=voltage)
