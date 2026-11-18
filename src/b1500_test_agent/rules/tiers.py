"""Tiers, the hard-limit code ceiling and the canonical plan summary (blueprint v1 2.5, 4.3; v2 2.9).

The ceiling constants live in ``models.policy`` so that the config loader (which validates ``policy.hard_limits``
against them, rule R-CFG-01) does not depend on ``rules``; they are re-exported here as the rules' public API.

Tier: any ``block`` finding → ``blocked``; else any ``confirm`` → ``needs_confirmation``; else ``ok``.

``plan_summary`` is the one line a human approves: ``run_confirmed_plan`` must echo it and the server recomputes it
from the stored plan and a fresh plan-phase evaluation. It is built only from hashed plan content (recipe id and
version, the per-channel envelope and its role binding, the kind's source plan, routes, mode and estimate, DUT
profile and pin-map names, backend) and plan-phase findings that depend on config alone: the ``confirm``/``block``
flags, the short-circuit bound of every HV-SPGU channel (R-SPGU-01 info) and the age of the MFCMU corrections in use
(R-CORR-01 info); never labels, messages, timestamps or live state. Format (fields separated by `` | ``)::

    mosfet.idvg@1 | drain=SMU3(HRSMU) bias 0.05 V Icomp 1 mA; gate=SMU5(MPSMU) sweep -1..3 V Icomp 1 uA |
    DUT nmos-generic | pins mosfet-4t | sim | R-PIN-02 unverified_pin_map

v2 channel forms (blueprint 2.9)::

    gate=SPGU1:101 via SEL1.OUT1 pulse 0->4 V 1 us x1000 @10 kHz SER 1 MOhm Isc<=0.08 A residual
    gate=CMU1:H 1 MHz 30 mVrms DC -2..2 V corr 2h; bulk=CMU1:L low
    top=WGFMU1:201 via RSU201.OUT dc_sample 0.5 V 504000 pts @100 ns
    force=SMU3(HRSMU) bias I<=1 mA Vcomp 5 V

followed, when they apply, by ``routes SEL1.OUT1->smu,pgu`` (routes no role uses) and, after the backend,
``async ~42 min``. Channels are sorted by role name; flags follow the rule-table order, one per (rule, reason) pair,
``blocked`` for a block. The result is printable ASCII and at most 400 characters: when the full form is too long the
channels are written compactly, then the flags are reduced to their distinct reasons, and only then is the text cut.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Final

from pydantic import ValidationError

from b1500_test_agent.driver import flex
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
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import PulseTrain, SourcePlan, source_plan, total_pulses
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

_ACTION = {
    "sweep_v": "sweep", "step_v": "step", "bias_v": "bias", "ground": "ground", "measure_only": "measure at",
    "sync_v": "sync", "sweep_i": "sweep", "bias_i": "bias", "step_i": "step",
}  # fmt: skip
_CURRENT_FUNCTIONS = frozenset({"sweep_i", "bias_i", "step_i"})
_PULSE_FUNCTIONS = frozenset({"pulse_v", "pgu"})
_CURRENT_PREFIXES = ((1.0, "A"), (1e-3, "mA"), (1e-6, "uA"), (1e-9, "nA"), (1e-12, "pA"), (1e-15, "fA"))
_TIME_PREFIXES = ((1.0, "s"), (1e-3, "ms"), (1e-6, "us"), (1e-9, "ns"), (1e-12, "ps"))
_FREQ_PREFIXES = ((1e6, "MHz"), (1e3, "kHz"), (1.0, "Hz"), (1e-3, "mHz"))
_OHM_PREFIXES = ((1e6, "MOhm"), (1e3, "kOhm"), (1.0, "Ohm"), (1e-3, "mOhm"))


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


def _si(value: float, prefixes: tuple[tuple[float, str], ...], *, space: bool = True) -> str:
    """``value`` with the largest prefix it reaches, e.g. ``20 mA``, ``1 us``, ``10 kHz``; ``0 <unit>`` for zero."""
    sep = " " if space else ""
    magnitude = abs(value)
    if magnitude == 0:
        return f"0{sep}{prefixes[0][1]}"
    for scale, unit in prefixes:
        if magnitude >= scale * (1 - 1e-9):
            return f"{_num(value / scale)}{sep}{unit}"
    scale, unit = prefixes[-1]
    return f"{_num(value / scale)}{sep}{unit}"


def _amps(value: float, *, space: bool = True) -> str:
    """Current with an SI prefix, e.g. ``20 mA``, ``1 uA``; ``0 A`` for zero."""
    return _si(value, _CURRENT_PREFIXES, space=space)


def _seconds(value: float, *, space: bool = True) -> str:
    return _si(value, _TIME_PREFIXES, space=space)


def _hertz(value: float, *, space: bool = True) -> str:
    return _si(value, _FREQ_PREFIXES, space=space)


def _ohms(value: float) -> str:
    return _si(value, _OHM_PREFIXES)


def _span(values: Iterable[float], fmt: object = _num) -> str:
    """``a`` for one distinct value, ``low..high`` for several."""
    items = sorted(set(values))
    render = fmt if callable(fmt) else _num
    return render(items[0]) if len(items) == 1 else f"{render(items[0])}..{render(items[-1])}"


def _duration(seconds: float) -> str:
    return f"{seconds / 3600:.1f} h" if seconds >= 7200 else f"{max(round(seconds / 60), 1)} min"


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


class _Context:
    """What the channel texts need besides the envelope: the source plan and the config-derived info findings."""

    def __init__(self, plan: PlanRecord, findings: Sequence[RuleFinding]) -> None:
        try:
            self.sources = source_plan(plan.program)
        except ValidationError:
            self.sources = SourcePlan()
        self.isc: dict[str, tuple[float, bool]] = {}
        self.corr_age: dict[str, float] = {}
        for f in findings:
            if f.severity != "info" or f.subject is None or not isinstance(f.observed, int | float):
                continue
            if f.rule_id == "R-SPGU-01":
                self.isc[f.subject] = (float(f.observed), f.limit is None)
            elif f.rule_id == "R-CORR-01":
                self.corr_age[f.subject] = float(f.observed)


def _pulse(entry: ChannelEnvelope, trains: list[PulseTrain], isc: tuple[float, bool] | None, *, compact: bool,
           pgu: bool) -> str:
    if trains:
        base = _span(t.base_v for t in trains)
        peak = _span(t.peak_v for t in trains)
        width = _span((t.width_s for t in trains), lambda w: _seconds(w, space=not compact))
        count = total_pulses(trains)
        text = f"{base}->{peak}V {width} x{count}" if compact else f"pulse {base}->{peak} V {width} x{count}"
        periods = {t.period_s for t in trains}
        if not compact and len(periods) == 1:
            text += f" @{_hertz(1 / periods.pop())}"
        loads = {t.load_ohm for t in trains if t.load_ohm is not None}
        if pgu and not compact and loads:
            text += f" {flex.SER_SETTING} {_span(loads, _ohms)}"
    else:
        pulse = entry.pulse
        level = _volts(pulse.max_abs_v_dut if pulse is not None else entry.max_abs_v)
        if pulse is None:
            text = f"pulse<={level}V" if compact else f"pulse max {level} V"
        else:
            width = _span((pulse.min_width_s, pulse.max_width_s), lambda w: _seconds(w, space=not compact))
            text = (f"pulse<={level}V {width} x{pulse.max_count}" if compact
                    else f"pulse max {level} V {width} x{pulse.max_count}")
    if isc is not None:
        value, residual = isc
        text += (f" Isc<={_num(value)}A" + (" res" if residual else "") if compact
                 else f" Isc<={_num(value)} A" + (" residual" if residual else ""))
    return text


def _cmu(entry: ChannelEnvelope, age: float | None, *, compact: bool) -> str:
    ac = entry.ac
    if ac is None:
        return f"<={_volts(entry.max_abs_v)}V" if compact else f"cmu max {_volts(entry.max_abs_v)} V"
    freq = _span((ac.f_min_hz, ac.f_max_hz), lambda f: _hertz(f, space=not compact))
    if entry.v_start is not None and entry.v_stop is not None:
        dc = _span((entry.v_start, entry.v_stop)) if entry.v_start != entry.v_stop else _volts(entry.v_start)
    else:
        dc = f"<={_volts(ac.max_dc_v)}"
    corr = "" if age is None else ("<1h" if age < 1 else f"{math.floor(age)}h")
    if compact:
        return f"{freq} {_num(ac.max_vrms * 1e3)}mV DC{dc}V" + (f" corr{corr}" if corr else "")
    return f"{freq} {_num(ac.max_vrms * 1e3)} mVrms DC {dc} V" + (f" corr {corr}" if corr else "")


def _wgfmu(entry: ChannelEnvelope, sources: SourcePlan, channel: int, *, compact: bool) -> str:
    program = sources.waveform
    if program is None or channel not in program.channels:
        return f"<={_volts(entry.max_abs_v)}V" if compact else f"waveform max {_volts(entry.max_abs_v)} V"
    levels = _span(program.levels(channel) or [0.0])
    points = program.points(channel)
    if compact:
        return f"{program.builder} {levels}V {points}pts"
    text = f"{program.builder} {levels} V"
    intervals = program.intervals(channel)
    if points:
        text += f" {points} pts" + (f" @{_seconds(min(intervals))}" if intervals else "")
    return text


def _channel(plan: PlanRecord, channel: int, entry: ChannelEnvelope, ctx: _Context, *, compact: bool) -> str:
    bound = plan.binding.roles.get(entry.role)
    alias = bound.alias if bound is not None and bound.alias else None
    function = entry.function
    if bound is not None and bound.cmu_side is not None:
        name = f"{alias or f'ch{channel}'}:{bound.cmu_side}"
    elif channel > 10 and alias:
        name = f"{alias}:{channel}"
    else:
        name = alias or f"ch{channel}"
    module = bound.module_type if bound is not None and bound.module_type else "?"
    smu_like = function is None or function in _ACTION or function == "pulse_v"
    head = f"{entry.role}={name}" + ("" if compact or not smu_like else f"({module})")
    if bound is not None and bound.via is not None:
        head += f"@{bound.via.target}" if compact else f" via {bound.via.target}"
    if function in _PULSE_FUNCTIONS or entry.pulse is not None:
        body = _pulse(entry, ctx.sources.trains(channel), ctx.isc.get(entry.role), compact=compact,
                      pgu=function == "pgu")
    elif function == "wgfmu":
        body = _wgfmu(entry, ctx.sources, channel, compact=compact)
    elif function == "cmu_high":
        corr_alias = alias or f"CH{channel}"
        return f"{head} {_cmu(entry, ctx.corr_age.get(corr_alias), compact=compact)}"  # the MFCMU has no Icomp
    elif function == "cmu_low":
        return f"{head} low"
    elif function in _CURRENT_FUNCTIONS:
        i_text = _amps(entry.max_abs_i or 0.0, space=not compact)
        return (f"{head} I<={i_text} Vc{_volts(entry.max_abs_v)}V" if compact
                else f"{head} {_ACTION[function]} I<={i_text} Vcomp {_volts(entry.max_abs_v)} V")
    else:
        body = _levels(entry, compact=compact)
    if entry.max_abs_i is None:
        if function in ("pgu", "wgfmu"):
            return f"{head} {body}"
        return f"{head} {body} {'noIcomp' if compact else 'no Icomp'}"
    current = _amps(entry.max_abs_i, space=False) if compact else f"Icomp {_amps(entry.max_abs_i)}"
    return f"{head} {body} {current}"


def _channels(plan: PlanRecord, *, compact: bool, findings: Sequence[RuleFinding] = ()) -> str:
    ctx = _Context(plan, findings)
    entries = sorted(plan.envelope.channels.items(), key=lambda item: (item[1].role, item[0]))
    parts = [_channel(plan, channel, entry, ctx, compact=compact) for channel, entry in entries]
    for bound in sorted(plan.binding.roles.values(), key=lambda b: b.role):
        if bound.channel is not None and bound.cmu_side == "L" and not any(
                e.role == bound.role for e in plan.envelope.channels.values()):
            name = f"{bound.alias or f'ch{bound.channel}'}:L"
            parts.append(f"{bound.role}={name}" + (f"@{bound.via.target}" if compact and bound.via else "") + " low")
    parts.sort(key=lambda text: text.split("=", 1)[0])
    return "; ".join(parts) if parts else "no outputs"


def _routes(plan: PlanRecord) -> str:
    """``routes SEL1.OUT1->smu,pgu`` for the allowed routes no role reaches its terminal through ("" when none)."""
    vias = {b.via for b in plan.binding.roles.values() if b.via is not None}
    by_target: dict[str, list[str]] = {}
    for route in sorted(plan.envelope.routes - vias, key=Route.sort_key):
        by_target.setdefault(route.target, []).append(route.state)
    return "routes " + "; ".join(f"{t}->{','.join(states)}" for t, states in by_target.items()) if by_target else ""


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
    """Canonical one-line summary from hashed plan content + config-derived plan-phase findings; at most 400
    characters, printable ASCII, deterministic (see the module docstring for the format)."""
    head = f"{plan.recipe_id}@{plan.recipe_version}"
    tail = [f"DUT {plan.request.dut_profile or 'none'}", f"pins {plan.binding.pin_map}", plan.backend]
    if plan.mode == "async":
        tail.append(f"async ~{_duration(plan.estimate.duration_s)}")
    routes = _routes(plan)
    flags = summary_flags(findings)
    full_flags = ", ".join(f"{rule_id} {label}" for rule_id, label in flags)
    labels: list[str] = []
    for _, label in flags:
        if label not in labels:
            labels.append(label)
    short_flags = ",".join(labels)
    text = ""
    for compact, flag_text in ((False, full_flags), (True, full_flags), (True, short_flags)):
        parts = [head, _channels(plan, compact=compact, findings=findings)]
        if routes:
            parts.append(routes)
        parts.extend(tail)
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
