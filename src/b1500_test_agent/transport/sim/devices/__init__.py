"""Device models of the simulator and the wiring that connects them to channels (blueprint 4.2).

In v1 every driven terminal is voltage-forced (a channel with its output switch on, or the GNDU at 0 V), so each
terminal current is an explicit function of the terminal voltages; there is no nodal solve. A terminal wired to a
channel whose output switch is off, wired to nothing, or not listed in the wiring is floating (``None``).

Sign convention: currents flow from the instrument into the device terminal (an SMU forcing +V into a resistor
to ground measures a positive current). Truth parameters are exposed (``Device.params``) so tests can compare
extractions with the model; ``DiodeDevice.current`` and ``FefetDevice.loop_truth`` give model truth directly.

Models: ``open``, ``resistor``/``short``, ``mosfet_ekv`` (M1); ``diode``, ``fefet`` and ``mosfet_damaged`` (M2).
A device with internal state (``StatefulDevice``: the FeFET polarization) computes its currents for a trial voltage
set without changing that state; the instrument ``commit``s the voltages actually applied (each measurement step
and every DC output change), and the state is persisted in ``SimPersistentState.devices`` (``Circuit.export_state``
/ ``import_state``), so it survives transactions and processes.

Modules: ``base`` (protocols, types, helpers), ``basic`` (open, resistor/short, diode), ``mosfet`` (EKV, damaged),
``ferro`` (FeFET), ``circuit`` (``build_device``, ``Circuit``, ``canonical_channel``). Device classes are imported
from their family module; this package exports the circuit API.
"""

from b1500_test_agent.transport.sim.devices.base import Device, StatefulDevice
from b1500_test_agent.transport.sim.devices.circuit import Circuit, build_device, canonical_channel

__all__ = ["Circuit", "Device", "StatefulDevice", "build_device", "canonical_channel"]
