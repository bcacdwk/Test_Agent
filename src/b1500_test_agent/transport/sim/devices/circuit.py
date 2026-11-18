"""The simulator circuit: device objects of a scenario (``build_device``) and the wiring that connects their
terminals to channels or the GNDU (``Circuit``), blueprint 4.2."""

from __future__ import annotations

from collections.abc import Mapping

from b1500_test_agent.models.sim import (
    DiodeParams,
    FefetParams,
    MosfetDamagedParams,
    MosfetEkvParams,
    ResistorParams,
    ShortParams,
    device_params,
)
from b1500_test_agent.models.station import PinTarget, SimDeviceModel, SimScenario
from b1500_test_agent.transport.sim.devices.base import Device, DeviceState, StatefulDevice
from b1500_test_agent.transport.sim.devices.basic import DiodeDevice, OpenDevice, ResistorDevice
from b1500_test_agent.transport.sim.devices.ferro import FefetDevice
from b1500_test_agent.transport.sim.devices.mosfet import DamagedMosfet, MosfetEkv


def build_device(name: str, spec: SimDeviceModel) -> Device:
    """The device object of scenario entry ``spec`` (params validated against ``models.sim.DEVICE_PARAMS``)."""
    params = device_params(spec.model, dict(spec.params))
    if spec.model == "open":
        return OpenDevice(name)
    if spec.model in ("resistor", "short"):
        assert isinstance(params, ResistorParams | ShortParams)
        return ResistorDevice(name, spec.model, params)
    if spec.model == "fefet":
        assert isinstance(params, FefetParams)
        return FefetDevice(name, params)
    if spec.model == "mosfet_damaged":
        assert isinstance(params, MosfetDamagedParams)
        return DamagedMosfet(name, params)
    if spec.model == "mosfet_ekv":
        assert isinstance(params, MosfetEkvParams)
        return MosfetEkv(name, params)
    if spec.model == "diode":
        assert isinstance(params, DiodeParams)
        return DiodeDevice(name, params)
    raise ValueError(f"No simulator implementation for device model {spec.model!r}.")  # pragma: no cover


def canonical_channel(channel: int) -> int:
    """Canonical channel number: ``101``..``1001`` (subchannel 1) map to ``1``..``10`` (PG Table 4-1, PDF 334);
    subchannel 2 keeps its three/four-digit number."""
    return channel // 100 if channel > 10 and channel % 100 == 1 else channel


class Circuit:
    """All devices of a scenario and their physical wiring (independent of the agent's pin map)."""

    def __init__(self, scenario: SimScenario) -> None:
        self.devices: dict[str, Device] = {name: build_device(name, spec) for name, spec in scenario.models.items()}
        self.wiring: dict[str, dict[str, PinTarget]] = {
            device: {t: canonical_channel(c) if isinstance(c, int) else c for t, c in terminals.items()}
            for device, terminals in scenario.wiring.items()
        }
        self.stateful: dict[str, StatefulDevice] = {
            name: device for name, device in self.devices.items() if isinstance(device, StatefulDevice)
        }

    @property
    def has_state(self) -> bool:
        """True when a device has internal state (then the instrument commits applied voltages)."""
        return bool(self.stateful)

    def _voltages(self, name: str, levels: Mapping[int, float]) -> dict[str, float | None]:
        voltages: dict[str, float | None] = {}
        for terminal, target in self.wiring.get(name, {}).items():
            if target == "GNDU":
                voltages[terminal] = 0.0
            elif isinstance(target, int):
                voltages[terminal] = levels.get(target)
            else:
                voltages[terminal] = None
        return voltages

    def channel_currents(self, levels: Mapping[int, float]) -> dict[int, float]:
        """Current (A) delivered by each channel in ``levels`` (canonical channel → forced voltage, for the channels
        whose output switch is on). Terminals on other channels float; GNDU terminals are at 0 V. Device state is
        not changed (see ``commit``)."""
        currents = {channel: 0.0 for channel in levels}
        for name, device in self.devices.items():
            wiring = self.wiring.get(name, {})
            for terminal, current in device.terminal_currents(self._voltages(name, levels)).items():
                target = wiring.get(terminal)
                if isinstance(target, int) and target in currents:
                    currents[target] += current
        return currents

    def commit(self, levels: Mapping[int, float]) -> None:
        """Apply ``levels`` (the voltages actually forced) to every stateful device."""
        for name, device in self.stateful.items():
            device.commit(self._voltages(name, levels))

    def export_state(self) -> dict[str, DeviceState]:
        """Internal state of every stateful device (for ``SimPersistentState.devices``)."""
        return {name: device.export_state() for name, device in self.stateful.items()}

    def import_state(self, states: Mapping[str, Mapping[str, object]]) -> None:
        """Restore the stateful devices from ``states``; a device without an entry returns to its initial state and
        entries of other devices are ignored. Raises ``ValueError`` for malformed state."""
        for name, device in self.stateful.items():
            device.import_state(states.get(name))
