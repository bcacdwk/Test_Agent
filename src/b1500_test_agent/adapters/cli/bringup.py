"""`b1500 bringup` group (blueprint v2 7.1; CLI only, no MCP tool; agents may run it).

- ``propose-station``: reads ``*IDN?`` and ``UNT?`` read-only and writes ``work/bringup/station.proposed.yaml``
  fitted to the live inventory, plus the diff against ``config/local/station.yaml`` (``bringup.propose_station``).
  Only the human adopts it (``b1500 config adopt FILE --as station``).

WP6.3 adds ``status``, ``capture`` and ``record`` to this group.
"""

from __future__ import annotations

import typer

from b1500_test_agent import bringup
from b1500_test_agent.adapters.cli import core
from b1500_test_agent.adapters.cli.core import JsonOption, emit
from b1500_test_agent.models.bringup import StationProposal

bringup_app = typer.Typer(help="Hardware bring-up helpers (read-only; proposals go to work/bringup/).",
                          no_args_is_help=True)


def proposal_lines(result: StationProposal) -> list[str]:
    """The proposed modules, the notes and the diff against the local station file."""
    lines: list[str] = []
    if result.station is not None:
        lines.append("modules:")
        lines += [f"  slot {m.slot}: {m.model} {m.type} channels {','.join(map(str, m.channels))} alias {m.alias}"
                  for m in result.station.modules]
        unverified = [s.id for s in result.station.switches if s.certainty == "unverified"]
        if unverified:
            lines.append(f"switches unverified (wiring null until recorded at L7): {', '.join(unverified)}")
    lines += [f"note: {note}" for note in result.notes]
    if result.diff:
        lines += ["diff:", *[f"  {line}" for line in result.diff]]
    return lines


@bringup_app.command("propose-station")
def propose_station_command(as_json: JsonOption = False) -> None:
    """Read *IDN? and UNT? (queries only) and write work/bringup/station.proposed.yaml plus the diff against
    config/local/station.yaml. The human reviews and adopts it."""
    result = bringup.propose_station(core.make_service())
    emit(result, as_json, proposal_lines(result))
