"""What is physically there and how to reach it: runtime settings, station profile, pin maps, simulator scenarios
and the live instrument state read back from the mainframe (blueprint v1 2.2, 2.4, 3, 4.1; v2 2.3, 7.3).

Config files: ``settings`` (``Settings``), ``station`` (``StationProfile``), ``pinmaps/<name>`` (``PinMap``) and
``sim/scenarios/<name>`` (``SimScenario``). Module models and channel numbers follow the Keysight B1500 Series
Programming Guide, Edition 15 ("PG"): Table 4-1 (PDF 334) for channel numbers, ``UNT?`` (PDF 545) for the inventory,
the status byte table (PDF 76) for bit 3 = interlock open.

v2 (blueprint 2.3): the station declares its switches (``switches``: 16440A selectors, SCUU, ASU, RSU; see
``models/routing.py``) instead of the v1 ``topology.switching`` booleans; a pin-map terminal may target a channel,
the GNDU, an MFCMU side (``"7H"``/``"7L"``) or a switch output (``"SEL1.OUT1"``); MFCMU correction *records* are
server state (``CorrectionRecord``, written to ``data/state/corrections/<cmu alias>.json`` by the correction
recipes) and only the static reference values of the load standard stay in ``station.yaml#corrections``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from b1500_test_agent.models.analysis import PositiveFloat, RunId
from b1500_test_agent.models.common import Alias, Backend, ConfigName, Sha256Hex, StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.routing import SwitchSpec, SwitchState, SwitchTarget, split_switch_target

ModuleType = Literal["HPSMU", "MPSMU", "HRSMU", "MCSMU", "HCSMU", "HVSMU", "MFCMU", "HVSPGU", "WGFMU"]
"""Plug-in module types a station profile and a recipe role may name (``RoleSpec.module_types``)."""

MODULE_TYPE_BY_MODEL: dict[str, ModuleType] = {
    "B1510A": "HPSMU",
    "B1511A": "MPSMU",
    "B1511B": "MPSMU",
    "B1512A": "HCSMU",
    "B1513A": "HVSMU",
    "B1513B": "HVSMU",
    "B1513C": "HVSMU",
    "B1514A": "MCSMU",
    "B1517A": "HRSMU",
    "B1520A": "MFCMU",
    "B1525A": "HVSPGU",
    "B1530A": "WGFMU",
}
"""Module model number (as reported by ``UNT?``) to module type. A model missing here is rejected, so a new module
type needs a reviewed code change before any rule can reason about it."""

SMU_TYPES: frozenset[str] = frozenset({"HPSMU", "MPSMU", "HRSMU", "MCSMU", "HCSMU", "HVSMU"})
"""Source/measure unit types (one channel per module, channel number = slot)."""

TWO_CHANNEL_TYPES: frozenset[str] = frozenset({"HVSPGU", "WGFMU"})
"""Module types with two subchannels, addressed as ``slot*100+1`` and ``slot*100+2`` (PG Table 4-1)."""

MeasureFamily = Literal["smu", "cmu", "wgfmu"]
"""Measuring module families with their own point limit (``policy.run_limits.max_points``)."""

MODULE_FAMILY: Final[dict[str, MeasureFamily]] = {
    **{t: "smu" for t in sorted(SMU_TYPES)}, "MFCMU": "cmu", "WGFMU": "wgfmu",
}  # fmt: skip
"""Measuring family of each module type (the HV-SPGU only sources pulses and measures nothing)."""

SWITCH_INPUT_TYPES: Final[dict[str, frozenset[str]]] = {
    "smu": SMU_TYPES, "pgu": frozenset({"HVSPGU"}), "cmu": frozenset({"MFCMU"}), "wgfmu": frozenset({"WGFMU"}),
}  # fmt: skip
"""Module types that may feed each switch input side."""

ASU_SCUU_SMU_TYPES: Final = frozenset({"HRSMU", "MPSMU"})
"""SMU types an ASU or SCUU works with (UG PDF 44-45, 103; PG p390 (4-72) DCV: SCUU with MPSMU or HRSMU)."""

Slot = Annotated[int, Field(ge=1, le=10)]

PinTarget = Channel | Literal["GNDU"] | None
"""Physical wiring target of a simulated DUT terminal (``SimScenario.wiring``): a channel number, the mainframe
ground unit, or ``None`` (not connected). Pin maps use the wider ``TerminalTarget``."""

CmuSideTarget = Annotated[str, Field(pattern=r"^(10|[1-9])[HL]$")]
"""An MFCMU terminal pair: ``"7H"`` = High (Hc/Hp) and ``"7L"`` = Low (Lc/Lp) of the MFCMU in slot 7."""

TerminalTarget = Channel | Literal["GNDU"] | CmuSideTarget | SwitchTarget | None
"""Where a pin-map terminal is wired (blueprint v2 2.3): a channel number, the GNDU, an MFCMU side (``"7H"``,
``"7L"``), a switch output (``"SEL1.OUT1"``, resolved through ``StationProfile.switches``), or ``None``."""


def cmu_side(target: object) -> tuple[int, Literal["H", "L"]] | None:
    """``(7, "H")`` for the MFCMU side target ``"7H"``; ``None`` for anything else."""
    if isinstance(target, str) and len(target) >= 2 and target[-1] in "HL" and target[:-1].isdigit():
        channel = int(target[:-1])
        if 1 <= channel <= 10:
            return channel, "H" if target[-1] == "H" else "L"
    return None


def switch_target(target: object) -> tuple[str, str] | None:
    """``("SEL1", "OUT1")`` for the switch target ``"SEL1.OUT1"``; ``None`` for anything else."""
    return split_switch_target(target) if isinstance(target, str) else None


def channel_slot(channel: int) -> int:
    """Slot number of a PG Table 4-1 channel number (``3`` and ``301``/``302`` are all slot 3)."""
    return channel if channel <= 10 else channel // 100


def _check_model(model: str) -> ModuleType:
    try:
        return MODULE_TYPE_BY_MODEL[model]
    except KeyError:
        known = ", ".join(sorted(MODULE_TYPE_BY_MODEL))
        raise ValueError(f"Unknown module model {model!r}; known models: {known}.") from None


# -- Runtime settings (config/settings*.yaml) ------------------------------------------------------------------------


class VisaSettings(StrictModel):
    """VISA connection of the real instrument; used only when ``backend`` is ``visa`` (blueprint 2.2, ATV-2).

    ``library`` is passed to ``pyvisa.ResourceManager`` (empty = PyVISA default, i.e. the vendor ``@ivi`` stack);
    set it when two VISA stacks are installed. ``timeout_ms`` is the default I/O timeout; reads after a measurement
    trigger use ``2 x estimate + 10 s`` instead (blueprint 7).

    Bus lifecycle (blueprint v2 2.4): with ``session: transaction`` (default) every transaction and status snapshot
    opens the VISA session, takes the exclusive lock (``exclusive_lock``), and unlocks and closes it at the end, so
    no process holds the instrument between calls. ``session: process`` is the ATV-13 fallback for a slow or
    unstable open: the session stays open for the process, the lock is still taken and released per transaction.
    ``lock_timeout_ms`` is how long a lock request waits for another VISA client (EasyEXPERT, a second program)
    before the call is refused as ``instrument_busy``.
    """

    resource: str = Field(default="GPIB0::17::INSTR", min_length=1)
    library: str = ""
    timeout_ms: int = Field(default=10_000, ge=100, le=3_600_000)
    exclusive_lock: bool = True
    lock_timeout_ms: int = Field(default=5_000, ge=0, le=600_000)
    session: Literal["transaction", "process"] = "transaction"
    write_termination: Literal["\n", "\r\n"] = "\n"
    read_termination: Literal["\n", "\r\n"] = "\n"


class SimSettings(StrictModel):
    """Simulator selection: the scenario file ``config/sim/scenarios/<scenario>.yaml``."""

    scenario: ConfigName = "nmos_basic"


class PathSettings(StrictModel):
    """Runtime directories; relative paths resolve against the repository root (owner decision D1).

    ``data_root`` holds ``runs/`` and ``state/``; ``work_dir`` is the agent scratch area for ad-hoc analysis. The
    environment variable ``B1500_DATA_DIR`` (tests and the M3 runner only) overrides ``data_root``.
    """

    data_root: str = Field(default="data", min_length=1)
    work_dir: str = Field(default="work", min_length=1)


class WgfmuSettings(StrictModel):
    """Keysight B1530A WGFMU instrument library (blueprint v2 2.4, decision 6).

    ``library`` is the path of ``wgfmu.dll``; empty = the library installer's default, the 64-bit
    ``%SystemRoot%\\System32\\wgfmu.dll`` of library A.03.00 or later. Only ``transport/wgfmu/dll.py`` loads it, and
    only with ``backend: visa`` on Windows.
    """

    library: str = ""


class Settings(StrictModel):
    """Contents of ``settings.yaml``: backend, transport, simulator scenario and runtime paths.

    ``backend: visa`` is accepted only from ``config/local/settings.yaml`` (rule R-CFG-01); an example file always
    runs the simulator.
    """

    backend: Backend = "sim"
    sim: SimSettings = Field(default_factory=SimSettings)
    visa: VisaSettings = Field(default_factory=VisaSettings)
    wgfmu: WgfmuSettings = Field(default_factory=WgfmuSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    manuals_dir: str = Field(default="..", min_length=1)
    """Folder with the Keysight manual PDFs (``references/manuals/catalog.yaml`` paths are relative to it); relative
    to the repository root, default its parent. ``B1500_MANUALS_DIR`` overrides it. Optional: the committed corpus
    answers ``b1500 manual`` queries without the PDFs (blueprint 5.2)."""


# -- Station profile (config/station*.yaml) --------------------------------------------------------------------------


class Mainframe(StrictModel):
    """The mainframe; the B1500A has a built-in ground unit (GNDU) that pin maps may use."""

    model: Literal["B1500A"] = "B1500A"
    gndu: bool = True


class ModuleSlot(StrictModel):
    """One installed plug-in module. ``model`` must equal the ``UNT?`` entry of its slot (rule R-INV-01)."""

    slot: Slot
    model: str
    type: ModuleType
    channels: list[Channel] = Field(min_length=1, max_length=2)
    alias: Alias | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ModuleSlot:
        expected_type = _check_model(self.model)
        if self.type != expected_type:
            raise ValueError(f"Module {self.model} is a {expected_type}, not a {self.type}.")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("A channel is listed twice.")
        for channel in self.channels:
            if channel_slot(channel) != self.slot:
                raise ValueError(f"Channel {channel} does not belong to slot {self.slot} (PG Table 4-1).")
        if self.type in TWO_CHANNEL_TYPES:
            allowed = {self.slot * 100 + 1, self.slot * 100 + 2}
            if not set(self.channels) <= allowed:
                raise ValueError(f"{self.type} channels are {sorted(allowed)} (subchannels 1 and 2 of the slot).")
        elif len(self.channels) != 1:
            raise ValueError(f"A {self.type} has one channel.")
        return self


class InterlockInfo(StrictModel):
    """Interlock circuit of the station; ``available`` is ``None`` until it has been wired and tested (M4 Stage 0).

    Outputs above ``policy.interlock.required_above_v`` need a closed interlock (rule R-IL-01).
    """

    available: bool | None = None
    note: str = ""


class CablePath(StrictModel):
    """Cabling from one module to the prober; ``None`` means unknown."""

    cable: Literal["triax", "coax", "unknown"] = "unknown"
    length_m: PositiveFloat | None = None
    guard: bool | None = None
    kelvin: bool | None = None
    note: str = ""


class Topology(StrictModel):
    """Shielding and cabling around the mainframe; ``cables`` is keyed by module alias. Switching accessories are
    declared in ``StationProfile.switches`` (v2; replaces the v1 ``topology.switching`` booleans)."""

    shield_box: bool | None = None
    guard: bool | None = None
    kelvin: bool | None = None
    cables: dict[str, CablePath] = Field(default_factory=dict)


CorrectionKind = Literal["phase", "open", "short", "load"]
"""MFCMU corrections: phase compensation (``ADJ``) and open/short/load data correction (``CORR?``)."""

CorrectionFunction = Literal["open", "short", "load"]
"""Data-correction functions switched by ``CORRST`` and read back by ``CORRST?``."""


class LoadStandard(StrictModel):
    """Reference value of the MFCMU load standard, sent as ``DCORR chnum,3,400,Ls,Rs`` (Ls-Rs mode; PG p389 (4-71)).

    Static station data (the standard on the bench); the correction record itself is server state.
    """

    ls_h: float = 0.0
    rs_ohm: PositiveFloat
    description: str = ""


class CmuStandards(StrictModel):
    """Static correction-standard values of one MFCMU (``station.yaml#corrections.<cmu alias>``). ``load`` is
    ``None`` until a human records the load standard; ``cmu.correction_load`` is blocked without it."""

    load: LoadStandard | None = None


class CorrectionRecord(StrictModel):
    """One completed MFCMU correction (blueprint v2 2.6), written by the executor after a successful correction run
    to ``data/state/corrections/<cmu alias>.json`` (a list of records; never edited by hand).

    ``freqs_hz``: the frequencies the correction data were measured at (empty only for ``phase``, which ``ADJ``
    performs for the whole range). ``idn``: ``*IDN?`` of the mainframe; ``pin_map_sha``/``station_sha``: the
    sha256 of the pin map and station profile the correction was measured with (a re-landing or rewiring makes it
    stale). ``corr_state``: the ``CORRST?`` answers (open/short/load correction on or off) read back after the run.
    """

    kind: CorrectionKind
    freqs_hz: list[PositiveFloat] = Field(default_factory=list)
    run_id: RunId
    ts: AwareDatetime
    idn: str = Field(min_length=1)
    pin_map_sha: Sha256Hex
    station_sha: Sha256Hex
    corr_state: dict[CorrectionFunction, bool] = Field(default_factory=dict)

    @field_validator("freqs_hz")
    @classmethod
    def _sorted_unique(cls, freqs: list[float]) -> list[float]:
        return sorted(set(freqs))

    @model_validator(mode="after")
    def _frequencies(self) -> CorrectionRecord:
        if self.kind != "phase" and not self.freqs_hz:
            raise ValueError(f"A {self.kind} correction record lists the frequencies it was measured at.")
        return self

    def covers(self, freqs: list[float], *, rel_tol: float = 1e-9) -> bool:
        """True when every frequency in ``freqs`` was corrected (phase compensation covers all frequencies)."""
        if self.kind == "phase":
            return True
        return all(any(abs(f - g) <= rel_tol * max(abs(f), abs(g)) for g in self.freqs_hz) for f in freqs)

    def age_h(self, now: datetime) -> float:
        """Hours since the correction (negative when ``ts`` lies after ``now``)."""
        return (now - self.ts).total_seconds() / 3600.0


CorrectionState = Literal["fresh", "missing", "other_setup", "other_instrument", "stale", "uncovered"]
"""Freshness of one required correction kind, in the order the checks run (``archive/corrections.py``)."""


class CorrectionCheck(StrictModel):
    """Freshness of one required correction kind of one MFCMU (correction store query; R-CORR-01, ``station_status``).

    ``state``: ``fresh`` (a record passes every check), ``missing`` (no record of the kind), ``other_setup`` (only
    records measured with another station profile or pin map), ``other_instrument`` (only records of another
    mainframe ``*IDN?``), ``stale`` (older than the age limit), ``uncovered`` (the fresh records miss a frequency,
    listed in ``missing_hz``). ``run_id``/``age_h`` describe the deciding record: the newest one that passed every
    check before the failing one (``None`` when there is none).
    """

    kind: CorrectionKind
    state: CorrectionState
    run_id: RunId | None = None
    age_h: float | None = None
    missing_hz: list[PositiveFloat] = Field(default_factory=list)


class CorrectionFreshness(StrictModel):
    """Answer of a correction-store freshness query for one MFCMU (``archive.corrections.freshness``): one check
    per required kind; ``fresh`` is true exactly when every check is ``fresh``."""

    cmu: Alias
    checked_at: AwareDatetime
    max_age_h: PositiveFloat
    freqs_hz: list[PositiveFloat] = Field(default_factory=list)
    checks: list[CorrectionCheck]
    fresh: bool

    @model_validator(mode="after")
    def _fresh_matches_checks(self) -> CorrectionFreshness:
        if self.fresh != all(check.state == "fresh" for check in self.checks):
            raise ValueError("fresh must be true exactly when every check is fresh.")
        return self

    def failing(self) -> list[CorrectionCheck]:
        """The checks that are not ``fresh``, in ``require`` order."""
        return [check for check in self.checks if check.state != "fresh"]


class StationProfile(StrictModel):
    """Contents of ``station.yaml``: inventory, interlock, topology, switches and correction standards (blueprint v1
    4.1, v2 2.3).

    The inventory must match the live ``*IDN?``/``UNT?`` answers for every bound channel (rule R-INV-01); pin maps
    and rules resolve channels to module types through it. ``switches`` declares the switch accessories; every
    switch input must be a channel of a module type that can feed it (SMU → ``smu``, HV-SPGU → ``pgu``, MFCMU →
    ``cmu``, WGFMU → ``wgfmu``). ``corrections`` holds static MFCMU standard values keyed by the MFCMU alias.
    """

    name: str = Field(min_length=1)
    mainframe: Mainframe = Field(default_factory=Mainframe)
    modules: list[ModuleSlot] = Field(min_length=1)
    interlock: InterlockInfo = Field(default_factory=InterlockInfo)
    topology: Topology = Field(default_factory=Topology)
    switches: list[SwitchSpec] = Field(default_factory=list)
    corrections: dict[Alias, CmuStandards] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_and_resolvable(self) -> StationProfile:
        slots = [m.slot for m in self.modules]
        if len(set(slots)) != len(slots):
            raise ValueError("A slot is listed twice.")
        channels = [ch for m in self.modules for ch in m.channels]
        if len(set(channels)) != len(channels):
            raise ValueError("A channel is listed twice.")
        aliases = [m.alias for m in self.modules if m.alias is not None]
        if len(set(aliases)) != len(aliases):
            raise ValueError("A module alias is used twice.")
        unknown = sorted(set(self.topology.cables) - set(aliases))
        if unknown:
            raise ValueError(f"topology.cables names unknown module aliases: {unknown}.")
        cmus = {m.alias for m in self.modules if m.type == "MFCMU" and m.alias is not None}
        not_cmu = sorted(set(self.corrections) - cmus)
        if not_cmu:
            raise ValueError(f"corrections names {not_cmu}, which are not MFCMU aliases ({sorted(cmus) or 'none'}).")
        self._check_switches(set(aliases))
        return self

    def _check_switches(self, aliases: set[str]) -> None:
        ids = [s.id for s in self.switches]
        if len(set(ids)) != len(ids):
            raise ValueError("A switch id is used twice.")
        clash = sorted(set(ids) & aliases)
        if clash:
            raise ValueError(f"Switch ids {clash} are also module aliases; use distinct names.")
        selector_ports: dict[int, str] = {}
        for switch in self.switches:
            for output, port in switch.ports.items():
                where = f"switches.{switch.id}.{output}"
                if switch.kind == "selector_16440a":
                    other = selector_ports.setdefault(port.index, where)
                    if other != where:
                        raise ValueError(f"{where}: ERSSP port {port.index} is already used by {other}.")
                else:
                    self._check_switch_index(switch.kind, port.index, where)
                for side, channel in port.inputs.items():
                    if channel is None:
                        continue
                    module = self.module_for_channel(channel)
                    if module is None:
                        raise ValueError(f"{where}: input {side} -> channel {channel} has no module in the station.")
                    allowed = SWITCH_INPUT_TYPES[side]
                    if side == "smu" and switch.kind in ("asu", "scuu"):
                        allowed = ASU_SCUU_SMU_TYPES
                    if module.type not in allowed:
                        raise ValueError(f"{where}: input {side} -> channel {channel} is a {module.type}; "
                                         f"needs {', '.join(sorted(allowed))}.")
                    if side == "smu" and switch.kind in ("asu", "scuu") and channel != port.index:
                        raise ValueError(f"{where}: the smu input of an {switch.kind} output is its index "
                                         f"channel {port.index}.")

    def _check_switch_index(self, kind: str, index: int, where: str) -> None:
        module = self.module_for_channel(index) if index >= 1 else None
        found = "no module" if module is None else f"a {module.type}"
        if kind == "rsu":
            if module is None or module.type != "WGFMU" or index <= 10:
                raise ValueError(f"{where}: an RSU index is a WGFMU subchannel (e.g. 201); channel {index} is "
                                 f"{found} in this station.")
        elif module is None or module.type not in ASU_SCUU_SMU_TYPES or index > 10:
            raise ValueError(f"{where}: an {kind} index is the channel of an HRSMU or MPSMU; channel {index} is "
                             f"{found} in this station.")

    def module_for_channel(self, channel: int) -> ModuleSlot | None:
        """The module that owns ``channel`` (``1`` and ``101`` both address slot 1's first subchannel)."""
        normalized = channel * 100 + 1 if channel <= 10 else channel
        for module in self.modules:
            for own in module.channels:
                if (own * 100 + 1 if own <= 10 else own) == normalized:
                    return module
        return None

    def module_by_alias(self, alias: str) -> ModuleSlot | None:
        """The module with alias ``alias``."""
        return next((m for m in self.modules if m.alias == alias), None)

    def switch(self, switch_id: str) -> SwitchSpec | None:
        """The declared switch ``switch_id``."""
        return next((s for s in self.switches if s.id == switch_id), None)

    def target_problem(self, target: object) -> str | None:
        """Why a pin-map switch target does not resolve in this station (``None`` when it does or is no switch
        target): an undeclared switch or an output the switch does not have (``b1500 config check``, R-CFG-01)."""
        ref = switch_target(target)
        if ref is None:
            return None
        switch_id, output = ref
        spec = self.switch(switch_id)
        if spec is None:
            declared = ", ".join(s.id for s in self.switches) or "none"
            return f"switch {switch_id!r} is not declared in the station profile (switches: {declared})"
        if output not in spec.ports:
            return f"switch {switch_id} has no output {output!r} (outputs: {', '.join(spec.ports)})"
        return None


# -- Pin maps (config/pinmaps/*.yaml) --------------------------------------------------------------------------------


class PinMap(StrictModel):
    """Where each DUT terminal is wired; recipe roles bind to terminals of the same name (R-PIN-01).

    A target is a channel number, ``GNDU``, an MFCMU side (``"7H"``/``"7L"``, for ``cmu_high``/``cmu_low`` roles)
    or a switch output ``"<switch>.<output>"`` declared in the station profile (an unknown switch or output makes
    the configuration invalid). ``certainty: unverified`` makes every plan using this map need confirmation
    (``unverified_pin_map``, R-PIN-02); set ``verified`` only after a human has checked the wiring. ``name`` is the
    file name without ``.yaml``.
    """

    name: ConfigName
    description: str = ""
    certainty: Literal["verified", "unverified"]
    terminals: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")], TerminalTarget] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)

    def switch_targets(self) -> dict[str, tuple[str, str]]:
        """Terminal → ``(switch id, output)`` for every terminal wired through a switch."""
        return {t: ref for t, target in self.terminals.items() if (ref := switch_target(target)) is not None}


# -- Simulator scenarios (config/sim/scenarios/*.yaml) ---------------------------------------------------------------


class SimSlot(StrictModel):
    """One module the simulated mainframe reports in ``UNT?``."""

    slot: Slot
    model: str
    revision: str = "0"

    @model_validator(mode="after")
    def _known_model(self) -> SimSlot:
        _check_model(self.model)
        return self


class SimDeviceModel(StrictModel):
    """A device model instance (``open``, ``resistor``, ``short``, ``mosfet_ekv`` in M1) with its truth parameters.

    The simulator (WP1.2) owns the parameter schema of each model; here only ``mosfet_ekv`` must state its threshold
    voltage ``vth0`` (V) explicitly, because tests compare extracted Vth against it. ``params`` must also validate
    against the model's typed schema in ``models/sim.py`` (``DEVICE_PARAMS``); unknown models are rejected.
    """

    model: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    params: dict[str, float | int | bool | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ekv_has_vth0(self) -> SimDeviceModel:
        if self.model == "mosfet_ekv":
            vth0 = self.params.get("vth0")
            if isinstance(vth0, bool) or not isinstance(vth0, int | float):
                raise ValueError("mosfet_ekv needs a numeric vth0 (V).")
        from b1500_test_agent.models.sim import device_params  # local: models.sim imports this module

        device_params(self.model, dict(self.params))
        return self


class SimNoise(StrictModel):
    """Measurement noise: absolute current floor per module type (A), relative noise, and the RNG seed."""

    floor_a: dict[ModuleType, PositiveFloat] = Field(default_factory=dict)
    rel: float = Field(default=0.0, ge=0, le=1)
    seed: int = 0


class SimScenario(StrictModel):
    """A simulated station and DUT (blueprint 3); consumed by the simulator from WP1.2 on.

    ``wiring`` is the physical wiring of the simulated prober (device name -> terminal -> channel/GNDU) and is
    independent of the agent's pin map, so a wrong pin map behaves like mis-wiring. ``models`` maps the same device
    names to device models. ``faults`` names a file in ``config/sim/faults/`` (schema
    ``models.sim.SimFaultProfile``).
    """

    name: ConfigName
    description: str = ""
    idn: str = Field(min_length=1)
    slots: list[SimSlot] = Field(min_length=1)
    interlock_closed: bool = False
    wiring: dict[str, dict[str, PinTarget]]
    models: dict[str, SimDeviceModel]
    noise: SimNoise = Field(default_factory=SimNoise)
    faults: ConfigName | None = None
    timing: Literal["instant", "scaled"] = "instant"

    @model_validator(mode="after")
    def _consistent(self) -> SimScenario:
        slots = [s.slot for s in self.slots]
        if len(set(slots)) != len(slots):
            raise ValueError("A slot is listed twice.")
        if set(self.wiring) != set(self.models):
            raise ValueError("wiring and models must name the same devices.")
        for device, terminals in self.wiring.items():
            for terminal, target in terminals.items():
                if isinstance(target, int) and channel_slot(target) not in slots:
                    raise ValueError(f"{device}.{terminal} is wired to channel {target} in an empty slot.")
        from b1500_test_agent.models.sim import DEVICE_TERMINALS  # local: models.sim imports this module

        for device, terminals in self.wiring.items():
            allowed = DEVICE_TERMINALS.get(self.models[device].model)
            unknown = sorted(set(terminals) - allowed) if allowed is not None else []
            if unknown:
                raise ValueError(f"{device} ({self.models[device].model}) has no terminal(s) {unknown}; "
                                 f"terminals: {sorted(allowed or ())}.")
        return self


# -- Live instrument state (read back by the driver; blueprint 2.3, 2.4) ---------------------------------------------


class Identity(StrictModel):
    """Parsed ``*IDN?`` answer (``vendor,model,serial,firmware``) plus the raw text."""

    vendor: str
    model: str
    serial: str
    firmware: str
    raw: str


class InstalledModule(StrictModel):
    """One occupied slot of the ``UNT?`` answer (model and revision)."""

    slot: Slot
    model: str
    revision: str


class ModuleInventory(StrictModel):
    """Parsed ``UNT?`` answer: occupied slots only, plus the raw text."""

    modules: list[InstalledModule]
    raw: str = ""

    def model_in_slot(self, slot: int) -> str | None:
        """Model number installed in ``slot``, or ``None`` when the slot is empty."""
        return next((m.model for m in self.modules if m.slot == slot), None)


class InstrumentError(StrictModel):
    """One ``ERRX?`` entry (code 0 never appears here)."""

    code: int
    message: str = ""


class StatusByte(StrictModel):
    """Status byte from ``*STB?`` or a serial poll; bit 3 (value 8) = interlock open (PG PDF 76; ATV-10)."""

    value: int = Field(ge=0, le=255)

    @property
    def interlock_open(self) -> bool:
        """True when the interlock circuit is open and a high-voltage setup was requested."""
        return bool(self.value & 0b1000)


class ChannelOutput(StrictModel):
    """Output state of one channel (``LOP?`` on hardware, simulator state on sim; ATV-1); ``state`` is the raw
    code."""

    channel: Channel
    state: str
    output_on: bool


class DllProbe(StrictModel):
    """Where the WGFMU instrument library is and whether this Python can load it (blueprint v2 2.4; produced by
    ``WgfmuDll.locate`` without loading anything risky, read by R-WG-01 and ``doctor``).

    ``machine``: the PE header machine of the DLL (``x64`` = 0x8664, ``x86`` = 0x14c); ``loadable``: a 64-bit
    library for this 64-bit Python with every export the binding needs (``missing_exports`` lists the others).
    ``message`` says what to do when it is not loadable (e.g. "install library >= A.03.00" for a 32-bit DLL).
    """

    path: str | None = None
    exists: bool = False
    machine: Literal["x64", "x86", "unknown"] | None = None
    file_version: str | None = None
    python_bits: int = 64
    loadable: bool = False
    missing_exports: list[str] = Field(default_factory=list)
    message: str = ""


class CmuCorrectionLive(StrictModel):
    """MFCMU correction state read back before a capacitance run (R-CORR-01 pre-execute): ``CORRST?`` per data
    correction (``True`` = on) and whether phase-compensation data are in effect (``None`` = not readable). A
    ``*RST`` or a power cycle turns the corrections off and clears their data (PG p388 (4-70) "CORRST?")."""

    corr_state: dict[CorrectionFunction, bool] = Field(default_factory=dict)
    phase: bool | None = None


class LiveState(StrictModel):
    """Read-only snapshot of the instrument (blueprint 2.4 ``Session.snapshot``): IDN, inventory, drained errors,
    status byte and per-channel output state. Fields stay ``None``/empty when not read.

    v2 (filled by the module WPs' snapshots; ``None`` = not read): ``switch_states`` = the state of every declared
    switch output read back (``ERSSP?`` after ``ERMOD 1`` for selectors, ``SSP?``/``SAP?`` paths, RSU connection),
    keyed ``"<switch>.<output>"`` (R-ROUTE-01); ``cmu_corrections`` = correction state per MFCMU alias (R-CORR-01);
    ``wgfmu_library`` = the WGFMU library probe and ``wgfmu_channels`` = ``WGFMU_getChannelIds`` (R-WG-01).
    """

    backend: Backend
    resource: str
    taken_at: AwareDatetime
    identity: Identity | None = None
    inventory: ModuleInventory | None = None
    errors: list[InstrumentError] = Field(default_factory=list)
    status_byte: StatusByte | None = None
    outputs: dict[Channel, ChannelOutput] = Field(default_factory=dict)
    switch_states: dict[SwitchTarget, SwitchState] | None = None
    cmu_corrections: dict[Alias, CmuCorrectionLive] | None = None
    wgfmu_library: DllProbe | None = None
    wgfmu_channels: list[Channel] | None = None

    @property
    def interlock_open(self) -> bool | None:
        """Interlock bit of the status byte, or ``None`` when the status byte was not read."""
        return None if self.status_byte is None else self.status_byte.interlock_open
