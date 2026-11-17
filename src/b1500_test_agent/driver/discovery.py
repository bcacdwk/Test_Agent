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

ATV-1 (``LOP?`` usable for cleanup verification) holds per the manual for SMU and MFCMU slots: after ``CL`` every
slot must read ``00``. Table 4-26 has no SPGU/WGFMU codes and reports per slot, not per subchannel, so those modules
(never sourced in v1) would need the ``*LRN? 0`` fallback (output-switch list). Hardware confirmation: M4 L1.
"""

from __future__ import annotations

import re

from b1500_test_agent.driver.commands import LOP_RESPONSE_PREFIX
from b1500_test_agent.driver.errors import FlexParseError
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
