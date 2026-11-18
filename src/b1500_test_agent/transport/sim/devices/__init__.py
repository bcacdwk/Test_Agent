"""Device models of the simulator and the wiring that connects them to channels (blueprint 4.1, 4.2).

In v1 every driven terminal is voltage-forced (a channel with its output switch on, or the GNDU at 0 V), so each
terminal current is an explicit function of the terminal voltages; there is no nodal solve. A terminal wired to a
channel whose output switch is off, wired to nothing, or not listed in the wiring is floating (``None``).

Sign convention: currents flow from the instrument into the device terminal (an SMU forcing +V into a resistor
to ground measures a positive current). Truth parameters are exposed (``Device.params``) so tests can compare
extractions with the model; ``DiodeDevice.current`` and ``FefetDevice.loop_truth`` give model truth directly, and
every v2 model has ``truth()`` plus the accessors its §4.2 fidelity targets are checked against.

Models: ``open``, ``resistor``/``short``, ``mosfet_ekv`` (M1); ``diode``, ``fefet`` and ``mosfet_damaged`` (M2);
v2 (WP5.9): ``mosfet`` (self-heating, BTI, HCI, IGZO drift, split C-V), ``moscap``, ``capacitor``, ``fixture`` (CMU
parasitics and corrections), ``dielectric`` (FN leakage, TDDB, BDV), ``fecap``, ``noise`` (attachable white, 1/f,
RTN) and FeFET pulse kinetics, retention and endurance.

Common interface (``base``): ``terminal_currents(v)`` is a quasi-static trial that changes nothing; a device with
internal state (``StatefulDevice``) also has ``commit(v)`` (quasi-static application) and ``export_state`` /
``import_state`` (JSON scalars persisted in ``SimPersistentState.devices``, so the state survives transactions and
processes); a device with time-dependent physics (``DynamicDevice``) has ``advance(dt, v)``; a two-terminal device
with a small-signal model (``AcDevice``) has ``admittance(v, f)``/``capacitance(v, f)``. The instrument commits the
voltages actually applied (each measurement step and every DC output change); the units that need virtual time
(sampling, pulses, stress-measure, CMU, WGFMU) call ``Circuit.advance``.

Modules: ``base`` (protocols, types, constants, helpers), ``kinetics`` (shared time laws and the play operator),
``basic`` (open, resistor/short, diode, capacitor), ``mosfet`` (EKV, damaged, v2 mosfet), ``moscap`` (MOS
electrostatics, MOS capacitor), ``fixture`` (CMU path parasitics, compensation), ``dielectric``, ``ferro`` (FeFET,
FeCap), ``noise``, ``circuit`` (``build_device``, ``Circuit``, ``canonical_channel``). Device classes are imported
from their family module; this package exports the circuit API and the protocols.
"""

from b1500_test_agent.transport.sim.devices.base import AcDevice, Device, DynamicDevice, StatefulDevice
from b1500_test_agent.transport.sim.devices.circuit import Circuit, build_device, canonical_channel

__all__ = ["AcDevice", "Circuit", "Device", "DynamicDevice", "StatefulDevice", "build_device", "canonical_channel"]
