"""Gate, stage markers and the service seam of the hardware suite (blueprint v2 7.1 ``tests/hardware/``, 7.4, 8.1).

The hardware suite reads the real B1500A on the lab PC and checks the bring-up records; it never sources (blueprint v2
decision 24: sourcing only through validate -> run). Every test carries the marker ``hardware`` and exactly one stage
marker ``hw_<stage>`` (``hw_s0``, ``hw_l0`` ... ``hw_l10``, the stage ids of ``devtools/skills/common.py``
``STAGES``, which hardware tests, records and cards share), so one stage runs alone::

    $env:B1500_HW = "1"; uv run pytest -m "hardware and hw_l0" -rs

``hardware_gate`` decides whether hardware tests run: only with ``B1500_HW=1`` AND a configuration whose settings select
backend ``visa`` (``config/local/settings.yaml``). Otherwise ``conftest.py`` skips every ``hardware`` test with the
reason from here; nothing reads the configuration while ``B1500_HW`` is not ``1``.

``make_service`` builds the service the suite reads the station through: exactly the service of ``b1500 doctor
--probe`` (adapter ``cli``, ``config/local/``, the real VISA stack). The read-only proof of the suite
(``test_readonly.py``) replaces it in a child pytest process by the visa-loop bus (``loop_plugin.py``); nothing else
does.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from b1500_test_agent.config import ConfigLoader
from b1500_test_agent.devtools.skills.common import STAGES
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.service import B1500Service

ENV_HW = "B1500_HW"
"""Environment switch of the hardware suite: ``1`` on the lab PC with the B1500A connected and the owner present."""

HARDWARE_MARKER = "hardware"
STAGE_IDS: tuple[str, ...] = tuple(STAGES)
"""Bring-up stage ids in order: ``S0``, ``L0`` ... ``L10`` (blueprint v2 7.4)."""

STAGE_MARKERS: dict[str, str] = {f"hw_{stage.lower()}": stage for stage in STAGE_IDS}
"""Stage marker -> stage id (``hw_l0`` -> ``L0``); registered in ``pyproject.toml``."""


def stage_marker(stage: str) -> str:
    """``L0`` -> ``hw_l0``."""
    if stage not in STAGE_IDS:
        raise ValueError(f"unknown bring-up stage {stage!r}; stages: {', '.join(STAGE_IDS)}")
    return f"hw_{stage.lower()}"


# -- the gate ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    """Whether hardware tests run (``enabled``) and why (``reason``: the skip reason when they do not)."""

    enabled: bool
    reason: str


def hardware_gate(environ: Mapping[str, str] | None = None) -> Gate:
    """Hardware tests run only with ``B1500_HW=1`` and settings that select backend ``visa``.

    The configuration is read only when ``B1500_HW`` is ``1``. A configuration that names backend ``visa`` but does not
    load (another file is invalid) still enables the suite: its tests then fail on the configuration problems instead
    of hiding them behind a skip.
    """
    env = os.environ if environ is None else environ
    value = env.get(ENV_HW)
    if value != "1":
        shown = "unset" if value is None else f"{value!r}"
        return Gate(False, f"hardware test: {ENV_HW} is {shown}, not 1 (set {ENV_HW}=1 only on the lab PC with the "
                           "B1500A connected and the owner present)")
    report = ConfigLoader(environ=env).check()
    if report.backend != "visa":
        if report.backend is None:
            found = "unreadable (" + "; ".join(p.message for p in report.problems[:2]) + ")"
        else:
            found = f"{report.backend!r} ({report.backend_reason})"
        return Gate(False, f"hardware test: {ENV_HW}=1 but the settings backend is {found}, not 'visa' (the human "
                           "selects backend visa in config/local/settings.yaml, blueprint v2 7.5 step 6)")
    return Gate(True, f"{ENV_HW}=1, {report.backend_reason}")


# -- stage markers -----------------------------------------------------------------------------------------------------


class MarkedItem(Protocol):
    """The part of a pytest item the marker check reads."""

    nodeid: str

    def iter_markers(self, name: str | None = None) -> Iterable[object]: ...


def marker_names(item: MarkedItem) -> set[str]:
    return {getattr(mark, "name", "") for mark in item.iter_markers()}


def stage_marker_problems(items: Iterable[MarkedItem]) -> list[str]:
    """Every ``hardware`` test needs exactly one stage marker (``hw_s0`` ... ``hw_l10``); returns what is wrong."""
    problems = []
    for item in items:
        names = marker_names(item)
        if HARDWARE_MARKER not in names:
            continue
        stages = sorted(names & set(STAGE_MARKERS))
        if len(stages) != 1:
            found = ", ".join(stages) or "none"
            problems.append(f"{item.nodeid}: a hardware test needs exactly one stage marker "
                            f"({', '.join(STAGE_MARKERS)}); found {found}")
    return problems


# -- the station service ---------------------------------------------------------------------------------------------


def default_service() -> B1500Service:
    """The service of ``b1500 doctor --probe``: adapter ``cli``, configuration and data from the environment."""
    return B1500Service(adapter="cli")


make_service = default_service
"""Factory of the suite's service (module attribute: ``loop_plugin.py`` swaps it in the read-only proof only)."""


# -- audit -------------------------------------------------------------------------------------------------------------


def audit_events_since(state_dir: Path, since: datetime, *, intent: str | None = None) -> list[AuditEvent]:
    """Events of the daily audit files (``<state_dir>/audit/YYYY-MM-DD.jsonl``) stamped at or after ``since``, in file
    order, optionally only those of one ``intent`` (the probe's is ``probe``)."""
    folder = state_dir / "audit"
    first = since.astimezone(UTC).date().isoformat()
    events: list[AuditEvent] = []
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        if path.stem < first:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = AuditEvent.from_json_line(line)
            if event.ts >= since and (intent is None or event.intent == intent):
                events.append(event)
    return events
