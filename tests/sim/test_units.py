"""Simulator units (blueprint 4.1): FLEX handlers registered by mnemonic, one handler per supported mnemonic.

``SimInstrument`` dispatches through ``units.base.handler_table``; ``units/core.py`` holds the family-independent
handlers, ``units/smu.py`` the SMU handlers and measurement engine, ``units/sampling.py`` the SMU sampling setup and
engine (WP7.4), ``units/{cmu,spgu,switch}.py`` the family state queries of the read-only probe (WP6.1).
"""

from __future__ import annotations

import pytest

from b1500_test_agent.transport.sim import SimInstrument, flex
from b1500_test_agent.transport.sim.units.base import HANDLES_ATTR, handler_table, handles
from b1500_test_agent.transport.sim.units.cmu import CmuUnit
from b1500_test_agent.transport.sim.units.core import CoreUnit
from b1500_test_agent.transport.sim.units.sampling import SamplingUnit
from b1500_test_agent.transport.sim.units.smu import SmuUnit
from b1500_test_agent.transport.sim.units.spgu import SpguUnit
from b1500_test_agent.transport.sim.units.switch import SwitchUnit

CORE = {"*IDN?", "UNT?", "ERRX?", "*STB?", "*OPC?", "*RST", "LOP?", "*TST?", "*CAL?", "NUB?", "FMT", "BC", "TSC",
        "CN", "CL", "DZ", "AB", "AAD", "AIT", "AV", "CM", "*LRN?"}
SMU = {"RI", "RV", "MM", "CMM", "DV", "WV", "WT", "WM", "XE", "DI", "WI", "WSV", "WSI", "WNX", "WNCC"}
SAMPLING = {"MCC", "ML", "MT", "MSC", "MV", "MI", "TSR"}
CMU = {"CORRST?", "ADJ?"}
SPGU = {"SPST?"}
SWITCH = {"ERMOD?", "ERSSP?", "SAP", "SAR", "SAL"}


def test_every_supported_mnemonic_has_exactly_one_handler() -> None:
    table = handler_table(SimInstrument)
    assert set(table) == flex.SUPPORTED
    assert all(callable(getattr(SimInstrument, name)) for name in table.values())


def test_units_split_the_supported_subset_by_family() -> None:
    families = {CoreUnit: CORE, SmuUnit: SMU, SamplingUnit: SAMPLING, CmuUnit: CMU, SpguUnit: SPGU, SwitchUnit: SWITCH}
    for unit, mnemonics in families.items():
        assert set(handler_table(unit)) == mnemonics, unit.__name__
    assert set().union(*families.values()) == flex.SUPPORTED
    assert sum(len(m) for m in families.values()) == len(flex.SUPPORTED)  # disjoint


def test_instance_dispatch_uses_the_registered_methods(make_sim) -> None:
    sim = make_sim()
    handlers = sim.instrument._handlers  # dispatch table internals
    assert set(handlers) == flex.SUPPORTED
    assert handlers["DV"].__func__ is SmuUnit._cmd_dv and handlers["*IDN?"].__func__ is CoreUnit._cmd_idn


def test_a_mnemonic_claimed_twice_is_refused() -> None:
    class A:
        @handles("XE")
        def first(self) -> None: ...

    class B(A):
        @handles("XE")
        def second(self) -> None: ...

    with pytest.raises(TypeError, match="XE is handled by both"):
        handler_table(B)


def test_an_override_replaces_the_base_handler() -> None:
    class A:
        @handles("XE")
        def run(self) -> None: ...

    class B(A):
        @handles("XE")
        def run(self) -> None: ...

    assert handler_table(B) == {"XE": "run"}
    assert getattr(B.run, HANDLES_ATTR) == ("XE",)


def test_handles_needs_a_mnemonic() -> None:
    with pytest.raises(ValueError):
        handles()
