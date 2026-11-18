"""Tiers, the hard-limit code ceiling and the canonical plan summary (blueprint 2.5, 4.3).

The ceiling constants live in ``models.policy`` so that the config loader (which validates ``policy.hard_limits``
against them, rule R-CFG-01) does not depend on ``rules``; they are re-exported here as the rules' public API.

Tier: any ``block`` finding → ``blocked``; else any ``confirm`` → ``needs_confirmation``; else ``ok``.

``plan_summary`` is the one line a human approves: ``run_confirmed_plan`` must echo it and the server recomputes it
from the stored plan and a fresh plan-phase evaluation. It is built only from hashed plan content (recipe id and
version, the per-channel envelope and its role binding, DUT profile and pin-map names, backend) and the plan-phase
``confirm``/``block`` findings, never from labels, messages, timestamps or live state, so it changes only when the
plan or the config changes. Format (fields separated by `` | ``)::

    mosfet.idvg@1 | drain=SMU3(HRSMU) bias 0.05 V Icomp 1 mA; gate=SMU5(MPSMU) sweep -1..3 V Icomp 1 uA |
    DUT nmos-generic | pins mosfet-4t | sim | R-PIN-02 unverified_pin_map

Channels are sorted by role name; flags follow the rule-table order, one per (rule, reason) pair, ``blocked`` for a
block. The result is printable ASCII and at most 400 characters: when the full form is too long the channels are
written compactly, then the flags are reduced to their distinct reasons, and only then is the text cut.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Final

from b1500_test_agent.models.common import ConfirmReason, Tier
from b1500_test_agent.models.plan import (
    ChannelEnvelope,
    PlanRecord,
    RuleFinding,
    RulesReport,
    confirm_reasons_of,
    tier_from_findings,
)
from b1500_test_agent.models.policy import HARD_CEILING_A, HARD_CEILING_V
from b1500_test_agent.rules.engine import rule_rank

__all__ = [
    "HARD_CEILING_A",
    "HARD_CEILING_V",
    "SUMMARY_MAX_CHARS",
    "compute_tier",
    "confirm_reasons",
    "plan_summary",
    "summary_flags",
    "with_rules",
]

SUMMARY_MAX_CHARS: Final = 400

_ACTION = {"sweep_v": "sweep", "step_v": "step", "bias_v": "bias", "ground": "ground", "measure_only": "measure at"}
_CURRENT_PREFIXES = ((1.0, "A"), (1e-3, "mA"), (1e-6, "uA"), (1e-9, "nA"), (1e-12, "pA"), (1e-15, "fA"))


def compute_tier(findings: Iterable[RuleFinding]) -> Tier:
    """Any ``block`` → ``blocked``; else any ``confirm`` → ``needs_confirmation``; else ``ok`` (blueprint 4.3)."""
    return tier_from_findings(findings)


def confirm_reasons(findings: Iterable[RuleFinding]) -> list[ConfirmReason]:
    """Distinct confirm reasons in first-seen order."""
    return confirm_reasons_of(findings)


# -- Number formatting -----------------------------------------------------------------------------------------------


def _num(value: float) -> str:
    text = f"{value:.4g}"
    return "0" if text in ("0", "-0") else text


def _volts(value: float) -> str:
    return _num(value)


def _amps(value: float, *, space: bool = True) -> str:
    """Current with an SI prefix, e.g. ``20 mA``, ``1 uA``; ``0 A`` for zero."""
    sep = " " if space else ""
    magnitude = abs(value)
    if magnitude == 0:
        return f"0{sep}A"
    for scale, unit in _CURRENT_PREFIXES:
        if magnitude >= scale * (1 - 1e-9):
            return f"{_num(value / scale)}{sep}{unit}"
    scale, unit = _CURRENT_PREFIXES[-1]
    return f"{_num(value / scale)}{sep}{unit}"


# -- Summary parts ---------------------------------------------------------------------------------------------------


def _levels(entry: ChannelEnvelope, *, compact: bool) -> str:
    """What the channel does: ``sweep -1..3 V`` (compact ``-1..3V``) or ``max 3 V`` (compact ``<=3V``)."""
    if entry.v_start is None or entry.v_stop is None:
        return f"<={_volts(entry.max_abs_v)}V" if compact else f"max {_volts(entry.max_abs_v)} V"
    start, stop = entry.v_start, entry.v_stop
    span = _volts(start) if start == stop else f"{_volts(start)}..{_volts(stop)}"
    covered = max(abs(start), abs(stop))
    if compact:
        text = f"{span}V"
        return text if math.isclose(covered, entry.max_abs_v) else f"{text}(<={_volts(entry.max_abs_v)})"
    action = _ACTION.get(entry.function or "", "levels")
    text = f"{action} {span} V"
    return text if math.isclose(covered, entry.max_abs_v) else f"{text} (max {_volts(entry.max_abs_v)} V)"


def _channels(plan: PlanRecord, *, compact: bool) -> str:
    parts = []
    entries = sorted(plan.envelope.channels.items(), key=lambda item: (item[1].role, item[0]))
    for channel, entry in entries:
        bound = plan.binding.roles.get(entry.role)
        name = bound.alias if bound is not None and bound.alias else f"ch{channel}"
        module = bound.module_type if bound is not None and bound.module_type else "?"
        if compact:
            current = "noIcomp" if entry.max_abs_i is None else _amps(entry.max_abs_i, space=False)
            parts.append(f"{entry.role}={name} {_levels(entry, compact=True)} {current}")
        else:
            current = "no Icomp" if entry.max_abs_i is None else f"Icomp {_amps(entry.max_abs_i)}"
            parts.append(f"{entry.role}={name}({module}) {_levels(entry, compact=False)} {current}")
    return "; ".join(parts) if parts else "no outputs"


def summary_flags(findings: Iterable[RuleFinding]) -> list[tuple[str, str]]:
    """``(rule_id, reason or "blocked")`` of the ``confirm``/``block`` findings, deduplicated, in rule-table order
    (then rule id, then label), so the order of ``findings`` does not matter."""
    flags = {
        (f.rule_id, f.reason if f.severity == "confirm" and f.reason else "blocked")
        for f in findings
        if f.severity in ("confirm", "block")
    }
    return sorted(flags, key=lambda flag: (rule_rank(flag[0]), flag[0], flag[1]))


def _ascii(text: str) -> str:
    return "".join(ch if " " <= ch <= "~" else "?" for ch in text)


def plan_summary(plan: PlanRecord, findings: Sequence[RuleFinding]) -> str:
    """Canonical one-line summary from hashed plan content + plan-phase confirm/block findings; at most 400
    characters, printable ASCII, deterministic (see the module docstring for the format)."""
    head = f"{plan.recipe_id}@{plan.recipe_version}"
    tail = [f"DUT {plan.request.dut_profile or 'none'}", f"pins {plan.binding.pin_map}", plan.backend]
    flags = summary_flags(findings)
    full_flags = ", ".join(f"{rule_id} {label}" for rule_id, label in flags)
    labels: list[str] = []
    for _, label in flags:
        if label not in labels:
            labels.append(label)
    short_flags = ",".join(labels)
    text = ""
    for compact, flag_text in ((False, full_flags), (True, full_flags), (True, short_flags)):
        parts = [head, _channels(plan, compact=compact), *tail]
        if flag_text:
            parts.append(flag_text)
        text = _ascii(" | ".join(parts))
        if len(text) <= SUMMARY_MAX_CHARS:
            return text
    return text[: SUMMARY_MAX_CHARS - 3] + "..."


def with_rules(plan: PlanRecord, report: RulesReport) -> PlanRecord:
    """A validated copy of ``plan`` carrying a plan-phase ``report``, its tier and the matching summary.

    The planner builds the plan with a provisional report, evaluates the rules on it (they never read ``rules``,
    ``tier`` or ``summary``), then stores ``with_rules(plan, report)``.
    """
    if report.phase != "plan":
        raise ValueError("a plan record carries the plan-phase report")
    data = plan.model_dump()
    data.update(rules=report, tier=report.tier, summary=plan_summary(plan, report.findings))
    return PlanRecord.model_validate(data)
