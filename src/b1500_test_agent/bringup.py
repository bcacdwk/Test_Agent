"""Lab bring-up helpers (blueprint v2 2.1, 7.1): ``propose_station`` (``b1500 bringup propose-station``, agent ok).

Imports only ``service`` and ``models`` (layering test): the instrument is read through the service's read-only
inventory reading (``B1500Admin.read_inventory``: ``*IDN?`` and ``UNT?``, queries only), the configuration through
``B1500Service.config``. Nothing here writes ``config/local/``: the proposal goes to ``work/bringup/`` and only the
human adopts it (``b1500 config adopt FILE --as station``, human-only, blocked for agents).

**The proposal** = the active station profile (``config/local/station.yaml``; the committed example while there is
none) fitted to the live inventory:

- ``modules`` = every installed module ``UNT?`` lists (slot, model, type, channels per PG Table 4-1); the alias of
  the base module in the same slot with the same type is kept, otherwise ``SMU<slot>``, ``CMU<slot>``,
  ``SPGU<slot>`` or ``WGFMU<slot>``; a model this kernel does not know is left out with a note;
- ``mainframe.model`` from ``*IDN?`` (anything but a B1500A is refused);
- switches are copied from the base: wiring the base does not know stays ``null`` (the example's selector inputs),
  an input whose module is no longer installed becomes ``null``, a switch whose own module (RSU WGFMU channel,
  SCUU/ASU SMU) is missing is dropped, and every changed switch is ``certainty: unverified``; when the base is the
  committed example every switch is ``unverified``;
- cables and correction standards of aliases that no longer exist are dropped (noted);
- one provenance note (``*IDN?``, time, backend) replaces the previous one.

The result is validated as a ``StationProfile`` and written to ``work/bringup/station.proposed.yaml``; the unified
diff against the active local station file (both normalised by the same YAML dump, comments and the provenance note
dropped) is returned.
WP6.3 adds ``bringup status | capture | record`` here.
"""

from __future__ import annotations

import difflib
from datetime import UTC, datetime
from typing import Any

import yaml
from pydantic import ValidationError

from b1500_test_agent.models.bringup import StationProposal
from b1500_test_agent.models.common import Backend, ErrorCode
from b1500_test_agent.models.routing import SwitchSpec
from b1500_test_agent.models.station import (
    ASU_SCUU_SMU_TYPES,
    MODULE_TYPE_BY_MODEL,
    SMU_TYPES,
    SWITCH_INPUT_TYPES,
    TWO_CHANNEL_TYPES,
    ModuleInventory,
    ModuleSlot,
    StationProfile,
)
from b1500_test_agent.service import B1500Admin, B1500Service

BRINGUP_DIR = "bringup"
PROPOSAL_FILE = "station.proposed.yaml"
PROVENANCE = "Proposed by b1500 bringup propose-station"
"""Prefix of the provenance note; a new proposal replaces the old note."""

ALIAS_PREFIX = {"MFCMU": "CMU", "HVSPGU": "SPGU", "WGFMU": "WGFMU"}
"""Default alias prefix per module type (SMU types: ``SMU``), followed by the slot number as in the lab code."""

HEADER = """\
# Station profile PROPOSED by `b1500 bringup propose-station` (blueprint v2 7.1); schema: StationProfile.
# Generated from the live *IDN? / UNT? answers and the base profile named below; not used until a human reviews it
# and adopts it into config/local/station.yaml (human only). Switch wiring stays null / unverified until a human
# records it (bring-up L7).
# base: {base}
# backend: {backend}{simulated}
"""


def _default_alias(module_type: str, slot: int) -> str:
    return f"{'SMU' if module_type in SMU_TYPES else ALIAS_PREFIX.get(module_type, module_type)}{slot}"


def _modules(inventory: ModuleInventory, base: StationProfile, notes: list[str]) -> list[ModuleSlot]:
    """The installed modules as station entries (see the module docstring)."""
    by_slot = {m.slot: m for m in base.modules}
    taken = {s.id for s in base.switches}
    modules: list[ModuleSlot] = []
    for installed in sorted(inventory.modules, key=lambda m: m.slot):
        module_type = MODULE_TYPE_BY_MODEL.get(installed.model)
        if module_type is None:
            notes.append(f"slot {installed.slot}: model {installed.model} is not a module type this kernel knows; "
                         "left out (a reviewed code change adds it)")
            continue
        slot = installed.slot
        channels = [slot * 100 + 1, slot * 100 + 2] if module_type in TWO_CHANNEL_TYPES else [slot]
        previous = by_slot.get(slot)
        alias = previous.alias if previous is not None and previous.type == module_type else None
        if alias is None or alias in taken:
            alias = _default_alias(module_type, slot)
            while alias in taken:
                alias += "x"
        taken.add(alias)
        if previous is None:
            notes.append(f"slot {slot}: {installed.model} added (not in the base profile)")
        elif previous.model != installed.model:
            notes.append(f"slot {slot}: {previous.model} in the base profile, {installed.model} installed")
        modules.append(ModuleSlot(slot=slot, model=installed.model, type=module_type, channels=channels,
                                  alias=alias))
    for slot, previous in sorted(by_slot.items()):
        if not any(m.slot == slot for m in modules) and not any(i.slot == slot for i in inventory.modules):
            notes.append(f"slot {slot}: {previous.model} in the base profile, nothing installed; removed")
    return modules


def _fit_switch(switch: SwitchSpec, modules: list[ModuleSlot], *, force_unverified: bool,
                notes: list[str]) -> dict[str, Any] | None:
    """The switch as a station entry fitted to ``modules`` (``None`` = dropped; see the module docstring)."""

    def module_of(channel: int) -> ModuleSlot | None:
        normalized = channel * 100 + 1 if channel <= 10 else channel
        return next((m for m in modules if any((c * 100 + 1 if c <= 10 else c) == normalized for c in m.channels)),
                    None)

    data = switch.model_dump(mode="json")
    changed = False
    for output, port in data["ports"].items():
        if switch.kind != "selector_16440a":
            owner = module_of(port["index"])
            fits = owner is not None and (owner.type == "WGFMU" if switch.kind == "rsu"
                                          else owner.type in ASU_SCUU_SMU_TYPES)
            if not fits:
                notes.append(f"switch {switch.id}: its channel {port['index']} is not installed; switch left out")
                return None
        for side, channel in port["inputs"].items():
            if channel is None:
                continue
            owner = module_of(channel)
            allowed = ASU_SCUU_SMU_TYPES if side == "smu" and switch.kind in ("asu", "scuu") else \
                SWITCH_INPUT_TYPES[side]
            if owner is None or owner.type not in allowed:
                port["inputs"][side] = None
                changed = True
                notes.append(f"switch {switch.id}.{output}: input {side} -> channel {channel} is not installed; set "
                             "to null (unknown)")
    if changed or force_unverified:
        data["certainty"] = "unverified"
    return data


def _normalized(station: StationProfile, *, provenance: bool = True) -> str:
    """The profile as YAML (one dump for the file and both sides of the diff); ``provenance=False`` leaves out the
    provenance note, so two proposals of the same station compare equal whenever they were made."""
    data = station.model_dump(mode="json")
    if not provenance:
        data["notes"] = [n for n in data["notes"] if not n.startswith(PROVENANCE)]
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _failure(message: str, code: ErrorCode, backend: Backend = "sim") -> StationProposal:
    return StationProposal(ok=False, status="busy" if code == "instrument_busy" else "error", error_code=code,
                           backend=backend, simulated=backend == "sim", message=message,
                           next_steps=["fix the reported problem, then run b1500 bringup propose-station again"])


def propose_station(service: B1500Service, *, now: datetime | None = None) -> StationProposal:
    """Read ``*IDN?``/``UNT?`` read-only and write ``work/bringup/station.proposed.yaml`` (module docstring)."""
    report = service.config.check()
    if not report.ok:
        problems = "; ".join(f"{p.file or 'config'}: {p.message}" for p in report.problems[:3])
        return _failure(f"configuration invalid: {problems} (b1500 config check)", "invalid_config",
                        report.backend or "sim")
    bundle = service.config.get()
    backend = bundle.backend
    reading = B1500Admin(service).read_inventory()
    if not reading.ok or reading.identity is None or reading.inventory is None:
        return _failure(f"cannot read the instrument: {reading.message}", reading.error_code or "internal",
                        backend)
    identity, inventory = reading.identity, reading.inventory
    if identity.model.strip() != "B1500A":
        return _failure(f"the instrument identifies as {identity.raw!r}; this kernel supports the B1500A "
                                 "only", "instrument_error", backend)
    used = bundle.files["station"]
    base = bundle.station
    from_example = used.source == "example"
    notes: list[str] = []
    modules = _modules(inventory, base, notes)
    if not modules:
        return _failure("the instrument lists no module this kernel knows; nothing to propose",
                        "instrument_error", backend)
    same_inventory = {(m.slot, m.model) for m in modules} == {(m.slot, m.model) for m in base.modules}
    switches = [fitted for switch in base.switches
                if (fitted := _fit_switch(switch, modules, force_unverified=from_example or not same_inventory,
                                          notes=notes)) is not None]
    aliases = {m.alias for m in modules}
    cmu_aliases = {m.alias for m in modules if m.type == "MFCMU"}
    data = base.model_dump(mode="json")
    dropped_cables = sorted(set(base.topology.cables) - aliases)
    dropped_corrections = sorted(set(base.corrections) - cmu_aliases)
    if dropped_cables:
        notes.append(f"cable records of {', '.join(dropped_cables)} dropped (alias no longer present)")
    if dropped_corrections:
        notes.append(f"correction standards of {', '.join(dropped_corrections)} dropped (no such MFCMU alias)")
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    provenance = (f"{PROVENANCE} at {stamp} from the live identity {identity.raw!r} and module list (backend "
                  f"{backend}{', SIMULATED' if backend == 'sim' else ''}); base {used.path}.")
    data.update(
        name=base.name.removesuffix("-example") if from_example else base.name,
        modules=[m.model_dump(mode="json") for m in modules],
        switches=switches,
        notes=[n for n in base.notes if not n.startswith(PROVENANCE)] + [provenance],
    )
    data["topology"]["cables"] = {k: v for k, v in data["topology"]["cables"].items() if k in aliases}
    data["corrections"] = {k: v for k, v in data["corrections"].items() if k in cmu_aliases}
    try:
        station = StationProfile.model_validate(data)
    except ValidationError as exc:
        return _failure(f"the fitted profile does not validate: {exc.errors()[0]['msg']}", "internal",
                        backend)
    folder = bundle.paths.work_dir / BRINGUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / PROPOSAL_FILE
    header = HEADER.format(base=used.path, backend=backend, simulated=" (SIMULATED: a rehearsal, not hardware)"
                           if backend == "sim" else "")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + _normalized(station))
    shown = bundle.paths.display(path)
    diff: list[str] | None = None
    local: str | None = None
    if used.source in ("local", "override"):
        local = used.path
        diff = list(difflib.unified_diff(_normalized(base, provenance=False).splitlines(),
                                         _normalized(station, provenance=False).splitlines(),
                                         fromfile=f"{local} (normalised)", tofile=shown, lineterm=""))
    matches = None if diff is None else not diff
    if diff is None:
        verdict = "no config/local/station.yaml yet: adopting it creates one"
    elif matches:
        verdict = f"identical to {local}"
    else:
        verdict = f"differs from {local} (diff below)"
    flag = "SIMULATED " if backend == "sim" else ""
    message = f"{flag}proposal for {len(modules)} modules written to {shown}; {verdict}"
    steps = [(f"show the human {shown} and the diff; only the human adopts it: b1500 config adopt {shown} --as "
              "station (human only), then b1500 config check")]
    if any(s.get("certainty") == "unverified" for s in switches):
        steps.append("switch wiring stays null/unverified until the human records it at bring-up L7")
    return StationProposal(ok=True, status="ok", backend=backend, simulated=backend == "sim", message=message,
                           next_steps=steps, path=shown, base=used.path, local=local, diff=diff, notes=notes,
                           identity=identity, inventory=inventory, station=station, matches_local=matches)

