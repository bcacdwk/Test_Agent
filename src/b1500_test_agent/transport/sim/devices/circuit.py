"""The simulator circuit: device objects of a scenario (``build_device``) and the wiring that connects their
terminals to channels, MFCMU sides (``"7H"``/``"7L"``, WP8.1), 16440A selector outputs (``"SELPORT0"``, WP9.2) or the
GNDU (``Circuit``), blueprint 4.2.

Selector outputs are routed nodes: ``Circuit.router`` (set by the instrument) returns, for every cabled selector
output, the node its present ``ERSSP`` state connects (the SMU or SPGU channel on that input) or ``None`` (open,
PGU open, an uncabled input, a relay still settling). Every evaluation resolves a terminal wired to a selector output
through it, so the terminal sees that channel's level and its current counts as that channel's, or it floats.

GNDU accounting (WP8.5): every evaluation sums the currents of the terminals that reach the GNDU into
``last_ground_a`` (signed, into the terminals); ``advance`` (always an applied state) and ``note_ground`` (called by the
instrument after the final solve of an applied state) keep the largest magnitude in ``ground_peak_a``. The GNDU sinks
up to ``GNDU_MAX_A`` (UG p58 (2-18)); rule R-GNDU-01 bounds the plan before a run."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.sim import (
    CapacitorParams,
    DielectricParams,
    DiodeParams,
    FecapParams,
    FefetParams,
    FixtureParams,
    MoscapParams,
    MosfetDamagedParams,
    MosfetEkvParams,
    MosfetParams,
    NoiseParams,
    ResistorParams,
    ShortParams,
    device_params,
)
from b1500_test_agent.models.station import PinTarget, SimDeviceModel, SimScenario, selector_port
from b1500_test_agent.transport.sim.devices.base import (
    Device,
    DeviceState,
    DynamicDevice,
    PeriodicDrive,
    PumpedDevice,
    StatefulDevice,
)
from b1500_test_agent.transport.sim.devices.basic import CapacitorDevice, DiodeDevice, OpenDevice, ResistorDevice
from b1500_test_agent.transport.sim.devices.dielectric import DielectricDevice
from b1500_test_agent.transport.sim.devices.ferro import FecapDevice, FefetDevice
from b1500_test_agent.transport.sim.devices.fixture import FixtureDevice
from b1500_test_agent.transport.sim.devices.moscap import MoscapDevice
from b1500_test_agent.transport.sim.devices.mosfet import DamagedMosfet, Mosfet, MosfetEkv
from b1500_test_agent.transport.sim.devices.noise import NoiseSource

P = TypeVar("P", bound=StrictModel)

Node = int | str
"""A circuit node with a forced level: a canonical channel number or an MFCMU side target (``"7H"``, ``"7L"``)."""

Router = Callable[[], Mapping[str, "Node | None"]]

GNDU_MAX_A = 4.2
"""The GNDU sinks up to 4.2 A (UG p58 (2-18) "4.2 A"; ``driver/modules.py`` GNDU row)."""
"""Selector output (``"SELPORT0"``) -> the node it connects now, ``None`` = open (``Circuit.router``)."""


def _typed(params: StrictModel, schema: type[P]) -> P:
    assert isinstance(params, schema)
    return params


DEVICE_BUILDERS: dict[str, Callable[[str, StrictModel], Device]] = {
    "open": lambda name, _: OpenDevice(name),
    "resistor": lambda name, p: ResistorDevice(name, "resistor", _typed(p, ResistorParams)),
    "short": lambda name, p: ResistorDevice(name, "short", _typed(p, ShortParams)),
    "mosfet_ekv": lambda name, p: MosfetEkv(name, _typed(p, MosfetEkvParams)),
    "diode": lambda name, p: DiodeDevice(name, _typed(p, DiodeParams)),
    "fefet": lambda name, p: FefetDevice(name, _typed(p, FefetParams)),
    "mosfet_damaged": lambda name, p: DamagedMosfet(name, _typed(p, MosfetDamagedParams)),
    "mosfet": lambda name, p: Mosfet(name, _typed(p, MosfetParams)),
    "moscap": lambda name, p: MoscapDevice(name, _typed(p, MoscapParams)),
    "capacitor": lambda name, p: CapacitorDevice(name, _typed(p, CapacitorParams)),
    "fixture": lambda name, p: FixtureDevice(name, _typed(p, FixtureParams)),
    "dielectric": lambda name, p: DielectricDevice(name, _typed(p, DielectricParams)),
    "fecap": lambda name, p: FecapDevice(name, _typed(p, FecapParams)),
    "noise": lambda name, p: NoiseSource(name, _typed(p, NoiseParams)),
}
"""Device model name (``models.sim.DEVICE_PARAMS``) → constructor of its simulator object."""


def build_device(name: str, spec: SimDeviceModel) -> Device:
    """The device object of scenario entry ``spec`` (params validated against ``models.sim.DEVICE_PARAMS``)."""
    params = device_params(spec.model, dict(spec.params))
    builder = DEVICE_BUILDERS.get(spec.model)
    if builder is None:  # pragma: no cover - DEVICE_PARAMS and DEVICE_BUILDERS list the same models (test)
        raise ValueError(f"No simulator implementation for device model {spec.model!r}.")
    return builder(name, params)


def canonical_channel(channel: int) -> int:
    """Canonical channel number: ``101``..``1001`` (subchannel 1) map to ``1``..``10`` (PG Table 4-1, PDF 334);
    subchannel 2 keeps its three/four-digit number."""
    return channel // 100 if channel > 10 and channel % 100 == 1 else channel


class Circuit:
    """All devices of a scenario and their physical wiring (independent of the agent's pin map).

    Units evaluate it three ways: ``channel_currents`` (a quasi-static trial, state unchanged), ``commit`` (apply DC
    levels quasi-statically) and ``advance`` (hold levels for a time step: kinetics, self-heating, ageing,
    breakdown, displacement currents); ``pumped_currents`` adds what a periodic drive pumps (charge pumping).
    Small-signal models are reached through ``devices`` (``AcDevice``, ``Mosfet.gate_admittance``,
    ``FixtureDevice``); attached noise through ``noise_on``.
    """

    def __init__(self, scenario: SimScenario) -> None:
        self.devices: dict[str, Device] = {name: build_device(name, spec) for name, spec in scenario.models.items()}
        self.wiring: dict[str, dict[str, PinTarget]] = {
            device: {t: canonical_channel(c) if isinstance(c, int) else c for t, c in terminals.items()}
            for device, terminals in scenario.wiring.items()
        }
        self.stateful: dict[str, StatefulDevice] = {
            name: device for name, device in self.devices.items() if isinstance(device, StatefulDevice)
        }
        self.dynamic: dict[str, DynamicDevice] = {
            name: device for name, device in self.devices.items() if isinstance(device, DynamicDevice)
        }
        self.noise: dict[str, NoiseSource] = {
            name: device for name, device in self.devices.items() if isinstance(device, NoiseSource)
        }
        self.router: Router | None = None
        """Where the selector outputs connect now (set by the instrument; ``None`` = every selector output open)."""
        self._routed = frozenset(target for terminals in self.wiring.values() for target in terminals.values()
                                 if selector_port(target) is not None)
        self.grounded = any(target == "GNDU" for terminals in self.wiring.values() for target in terminals.values())
        """True when some device terminal is wired to the GNDU."""
        self.last_ground_a = 0.0
        """Current (A) into the GNDU-wired terminals at the last evaluation (module docstring)."""
        self.ground_peak_a = 0.0
        """Largest ``|last_ground_a|`` of an applied state (``advance``, ``note_ground``)."""
        for name, source in self.noise.items():
            target = self.devices.get(source.params.attach)
            if target is None or isinstance(target, NoiseSource):
                raise ValueError(f"noise {name}: attach {source.params.attach!r} is not a device of the scenario")
            if source.params.terminal not in self.wiring.get(source.params.attach, {}):
                raise ValueError(f"noise {name}: {source.params.attach} has no wired terminal "
                                 f"{source.params.terminal!r}")

    @property
    def has_state(self) -> bool:
        """True when a device has internal state (then the instrument commits applied voltages)."""
        return bool(self.stateful)

    def routes(self) -> Mapping[str, Node | None]:
        """Selector output -> the node it connects now (empty without selector-wired terminals or a router)."""
        if not self._routed or self.router is None:
            return {}
        return self.router()

    def _resolve(self, target: PinTarget, routes: Mapping[str, Node | None]) -> PinTarget:
        """``target`` with a selector output replaced by the node it connects (``None`` = open)."""
        if isinstance(target, str) and target in self._routed:
            return routes.get(target)  # type: ignore[return-value]
        return target

    def wired_to(self, node: Node) -> bool:
        """True when some device terminal reaches ``node`` now (directly or through a selector output)."""
        routes = self.routes()
        return any(self._resolve(target, routes) == node
                   for terminals in self.wiring.values() for target in terminals.values())

    def terminal_voltages(self, name: str, levels: Mapping[Node, float],
                          routes: Mapping[str, Node | None] | None = None) -> dict[str, float | None]:
        """Voltage of each wired terminal of device ``name`` for ``levels`` (``None`` = floating): GNDU 0 V, a
        channel or MFCMU side its level, a selector output the level of the node it connects (``routes``, default
        ``self.routes()``), anything else (or a node without a level) floating."""
        if routes is None:
            routes = self.routes()
        voltages: dict[str, float | None] = {}
        for terminal, target in self.wiring.get(name, {}).items():
            target = self._resolve(target, routes)
            if target == "GNDU":
                voltages[terminal] = 0.0
            elif target is not None:
                voltages[terminal] = levels.get(target)
            else:
                voltages[terminal] = None
        return voltages

    def _collect(self, levels: Mapping[Node, float], evaluate: Callable[[str, Device, dict[str, float | None]],
                                                                        dict[str, float]]) -> dict[Node, float]:
        currents: dict[Node, float] = {node: 0.0 for node in levels}
        routes = self.routes()
        ground = 0.0
        for name, device in self.devices.items():
            wiring = self.wiring.get(name, {})
            for terminal, current in evaluate(name, device, self.terminal_voltages(name, levels, routes)).items():
                target = self._resolve(wiring.get(terminal), routes)
                if target == "GNDU":
                    ground += current
                elif target is not None and target in currents:
                    currents[target] += current
        self.last_ground_a = ground
        return currents

    def note_ground(self) -> None:
        """The last evaluation was an applied state: keep its GNDU current in ``ground_peak_a``."""
        self.ground_peak_a = max(self.ground_peak_a, abs(self.last_ground_a))

    def channel_currents(self, levels: Mapping[Node, float]) -> dict[Node, float]:
        """Current (A) delivered by each node in ``levels`` (canonical channel or MFCMU side ``"7H"``/``"7L"`` →
        forced voltage, for the outputs that are on). Terminals on other nodes float; GNDU terminals are at 0 V.
        Device state is not changed (see ``commit``)."""
        return self._collect(levels, lambda _name, device, v: device.terminal_currents(v))

    def commit(self, levels: Mapping[Node, float]) -> None:
        """Apply ``levels`` (the voltages actually forced) to every stateful device."""
        routes = self.routes()
        for name, device in self.stateful.items():
            device.commit(self.terminal_voltages(name, levels, routes))

    def advance(self, dt: float, levels: Mapping[Node, float]) -> dict[Node, float]:
        """Hold ``levels`` for ``dt`` seconds (≥ 0): every dynamic device evolves; returns the current (A) of each
        channel in ``levels`` at the end of the interval plus the mean displacement current over it."""
        if dt < 0.0:
            raise ValueError(f"advance needs dt >= 0, got {dt}")

        def evaluate(name: str, device: Device, v: dict[str, float | None]) -> dict[str, float]:
            dynamic = self.dynamic.get(name)
            return dynamic.advance(dt, v) if dynamic is not None else device.terminal_currents(v)

        currents = self._collect(levels, evaluate)
        self.note_ground()
        return currents

    def pumped_currents(self, levels: Mapping[Node, float], drives: Mapping[Node, PeriodicDrive]) -> dict[Node, float]:
        """Time-averaged extra current (A) of each node in ``levels`` while the nodes in ``drives`` (an SPGU channel's
        pulse train at the DUT, WP9.3) drive the terminals that reach them now (directly or through a selector):
        every ``PumpedDevice`` (MOSFET charge pumping) with a driven terminal, its other terminals at ``levels``."""
        currents: dict[Node, float] = {}
        routes = self.routes()
        for name, device in self.devices.items():
            if not isinstance(device, PumpedDevice):
                continue
            wiring = self.wiring.get(name, {})
            driven = {terminal: drives[node] for terminal, target in wiring.items()
                      if (node := self._resolve(target, routes)) is not None and node in drives}
            if not driven:
                continue
            for terminal, current in device.pumped_currents(self.terminal_voltages(name, levels, routes),
                                                            driven).items():
                target = self._resolve(wiring.get(terminal), routes)
                if target is not None and target in levels:
                    currents[target] = currents.get(target, 0.0) + current
        return currents

    def noise_on(self, target: PinTarget) -> list[NoiseSource]:
        """Noise sources attached to a device terminal wired to ``target`` (a canonical channel number or
        ``"GNDU"``; through a selector output while it connects ``target``), in scenario order."""
        target = canonical_channel(target) if isinstance(target, int) else target
        routes = self.routes()
        return [source for source in self.noise.values()
                if self._resolve(self.wiring.get(source.params.attach, {}).get(source.params.terminal), routes)
                == target]

    def export_state(self) -> dict[str, DeviceState]:
        """Internal state of every stateful device (for ``SimPersistentState.devices``)."""
        return {name: device.export_state() for name, device in self.stateful.items()}

    def import_state(self, states: Mapping[str, Mapping[str, object]]) -> None:
        """Restore the stateful devices from ``states``; a device without an entry returns to its initial state and
        entries of other devices are ignored. Raises ``ValueError`` for malformed state."""
        for name, device in self.stateful.items():
            device.import_state(states.get(name))
