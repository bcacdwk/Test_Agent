"""Results of the plug-in-and-go kit (blueprint v2 7.1): the read-only probe, the station proposal and the local
configuration bootstrap (``b1500 doctor --probe``, ``b1500 bringup propose-station``, ``b1500 config init|adopt``).

These are CLI-only results (no MCP tool returns them). ``ProbeReport`` and ``StationProposal`` carry the common
``ResultEnvelope`` head (backend, ``simulated``), so simulator answers are never mistaken for hardware.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from b1500_test_agent.models.common import ConfigReport, ResultEnvelope, StrictModel
from b1500_test_agent.models.routing import SwitchState
from b1500_test_agent.models.station import CmuCorrectionLive, DllProbe, Identity, ModuleInventory, StationProfile

ProbeStatus = Literal["PASS", "INFO", "WARN", "FAIL"]
"""Verdict of one probe line: ``INFO`` = nothing to fix (not applicable, or a state to note)."""

ConfigKind = Literal["settings", "station", "policy", "pinmap", "dut"]
"""What ``b1500 config adopt FILE --as KIND`` installs."""


class ProbeCheck(StrictModel):
    """One probe line: name, verdict and what was found."""

    name: str
    status: ProbeStatus
    detail: str


class ProbeExchange(StrictModel):
    """One query of the probe with its raw answer (``None`` when it failed; ``error`` says why)."""

    cmd: str
    resp: str | None = None
    error: str | None = None


class ProbeReport(ResultEnvelope):
    """Result of ``b1500 doctor --probe``: PASS/INFO/WARN/FAIL lines, the parsed identity and inventory, every raw
    exchange in order, and where the raw record was written (``work/bringup/probe-<UTC>.json``). ``ok`` is false
    exactly when a line FAILs. ``wgfmu_library``: the WGFMU DLL probe (backend visa); ``wgfmu_channels``: the channel
    ids the library reported in the ``--wgfmu-session`` check (WP10.2; the library calls are in the audit, not in
    ``transcript``, which holds FLEX exchanges only)."""

    resource: str = ""
    taken_at: AwareDatetime | None = None
    checks: list[ProbeCheck] = Field(default_factory=list)
    identity: Identity | None = None
    inventory: ModuleInventory | None = None
    visa_resources: list[str] | None = None
    switch_states: dict[str, SwitchState] | None = None
    cmu_corrections: dict[str, CmuCorrectionLive] | None = None
    wgfmu_library: DllProbe | None = None
    wgfmu_channels: list[int] | None = None
    transcript: list[ProbeExchange] = Field(default_factory=list)
    record: str | None = None


class InventoryReading(ResultEnvelope):
    """``*IDN?`` and ``UNT?`` read through a read-only session (the input of ``bringup propose-station``)."""

    resource: str = ""
    taken_at: AwareDatetime | None = None
    identity: Identity | None = None
    inventory: ModuleInventory | None = None


class StationProposal(ResultEnvelope):
    """Result of ``b1500 bringup propose-station``: the proposed ``station.yaml`` (written to ``path``), the file it
    was based on, the unified diff against ``config/local/station.yaml`` (``None`` when there is no local file) and
    what was changed or dropped while fitting the base to the live inventory (``notes``)."""

    path: str | None = None
    base: str | None = None
    local: str | None = None
    diff: list[str] | None = None
    notes: list[str] = Field(default_factory=list)
    identity: Identity | None = None
    inventory: ModuleInventory | None = None
    station: StationProfile | None = None
    matches_local: bool | None = None


class ConfigInitReport(StrictModel):
    """Result of ``b1500 config init [--visa]``: which examples were copied into the local directory and which
    local files already existed (never overwritten)."""

    ok: bool
    target_dir: str
    copied: list[str] = Field(default_factory=list)
    kept: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    check: ConfigReport | None = None


class ConfigAdoptReport(StrictModel):
    """Result of ``b1500 config adopt FILE --as KIND``: the schema verdict of the file, the diff against the local
    file it replaces, where it went (and the backup of the previous one) and the configuration check afterwards."""

    ok: bool
    kind: ConfigKind
    source: str
    target: str | None = None
    adopted: bool = False
    unchanged: bool = False
    backup: str | None = None
    diff: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    check: ConfigReport | None = None
