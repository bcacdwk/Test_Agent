"""The interlock label of ``station_status`` (blueprint v2 10.2 row 6.2; standing decision "interlock never used").

Status byte bit 3 means different things per backend: the simulator mirrors its scenario's interlock state, the
B1500A latches it only for a refused >42 V request (PG p76 (1-56); ATV-10). ``interlock_label`` says which, and that
the station never uses the interlock; it is a label only (no rule, limit or tier depends on it). The service-level
cases run ``station_status`` on sim and on visa (visa-loop) and the CLI line shows the label.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from b1500_test_agent.adapters.cli.core import status_lines
from b1500_test_agent.models.station import LiveState, StatusByte
from b1500_test_agent.service.status import interlock_label
from tests.integration.helpers import make_world
from tests.sim.helpers import load_scenario
from tests.unit.rules_factory import station
from tests.visa_loop.helpers import make_visa_world
from tests.visa_loop.loop import LoopBus


def live(stb: int | None, backend: str = "visa") -> LiveState:
    return LiveState(backend=backend, resource="GPIB0::17::INSTR", taken_at=datetime.now(UTC),  # type: ignore[arg-type]
                     status_byte=None if stb is None else StatusByte(value=stb))


NOT_USED = "not used at this station: kept open, the B1500A limits outputs to 42 V (the code ceiling)"
BIT_CLEAR = "STB bit 3 clear (it flags only a refused >42 V request, not the circuit state; ATV-10)"
BIT_SET = ("STB bit 3 SET: an output or compliance above 42 V was requested with the interlock open and refused (an "
           "event, cleared by a serial poll; see errors 202/203)")


@pytest.mark.parametrize(("backend", "stb", "available", "expected"), [
    ("sim", 8, None, "SIMULATED open (scenario): outputs limited to 42 V"),
    ("sim", 0, None, "SIMULATED closed (scenario)"),
    ("visa", 0, None, f"{NOT_USED}; {BIT_CLEAR}"),
    ("visa", 0, False, f"{NOT_USED}; {BIT_CLEAR}"),
    ("visa", 8 + 32, None, f"{NOT_USED}; {BIT_SET}"),
    ("visa", 0, True, f"wired and tested at stage S0 (station profile); {BIT_CLEAR}"),
])
def test_label_by_backend_status_bit_and_station_record(backend: str, stb: int, available: bool | None,
                                                         expected: str) -> None:
    profile = station(interlock={"available": available, "note": ""})
    assert interlock_label(backend, profile, live(stb, backend)) == expected


def test_no_status_byte_no_label() -> None:
    assert interlock_label("visa", station(), None) is None
    assert interlock_label("visa", station(), live(None)) is None


def test_hardware_never_reads_closed_from_a_clear_bit() -> None:
    """The v1 CLI printed ``interlock closed`` for a clear bit; on hardware that claim is never made."""
    for stb in (0, 8):
        text = interlock_label("visa", station(), live(stb)) or ""
        assert "closed" not in text and "42 V" in text


def test_station_status_and_the_cli_carry_the_label_on_visa(tmp_path: Path) -> None:
    """On the visa path (visa-loop over a scenario whose status byte has bit 3 clear) the label replaces "closed"."""
    world = make_visa_world(tmp_path)
    try:
        scenario = load_scenario("lab_station").model_copy(update={"interlock_closed": True})
        bus = LoopBus(world.bus_dir, scenario)
        status = world.service(bus).station_status()
        assert status.ok and status.backend == "visa" and status.interlock_open is False
        assert status.interlock is not None and status.interlock.startswith("not used at this station")
        line = next(line for line in status_lines(status) if line.startswith("live ("))
        assert f"interlock {status.interlock};" in line and "interlock closed" not in line
    finally:
        world.close()


def test_station_status_on_the_simulator_says_simulated(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    service = world.service()
    try:
        status = service.station_status()
        assert status.simulated and status.interlock == "SIMULATED open (scenario): outputs limited to 42 V"
        assert "interlock open (outputs limited to 42 V)" in status.message
    finally:
        service.close()
