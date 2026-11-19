"""The ``extraction`` grader (specification: ``specs.ExtractionSpec``) and its simulator truths.

Extractions come from the run archive (``<run>/analysis/*.json`` written by ``analyze_run``, the default analysis of
``run_plan`` included), attributed to turns by their ``created_at``. A valid extraction is ``outcome: ok`` with a
numeric value and not forced on untrusted data. Truths (``specs.Truth``): a number, a parameter of the selected sim
scenario's models, the FeFET loop truth of a run's own sweep, or a truth accessor of a fresh simulator device called
with the run's own plan parameters (``sim_call``; the v2 device models of blueprint 4.2 expose ``truth()``,
``pund_truth(v_max)``, ``memory_window_truth(v_program, v_erase, width)`` ...).

Answer checks: values in the answer are read with their unit and an SI prefix (``69.0 pF`` = 6.9e-11 F); the
dimensionless unit ``1`` matches a bare number (``n = 0.25``); ``expect: present`` only needs the quantity named next
to a number, whatever the unit spelling.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from b1500_test_agent.devtools.acceptance.evidence import Evidence, RunEvidence
from b1500_test_agent.devtools.acceptance.specs import ExtractionSpec, Truth
from b1500_test_agent.transport.sim.devices import Circuit
from b1500_test_agent.transport.sim.devices.ferro import FefetDevice

Outcome = tuple[bool | None, str, list[str]]
DETAIL_LIMIT = 12
_SI = {"": 1.0, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "k": 1e3}
_NUMBER = r"[-+−]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
WINDOW = re.compile(
    rf"{_NUMBER}\s*(?:[munpkµμ]?V)?\s*(?:\.\.|…|–|—|-|\bto\b|~)\s*{_NUMBER}\s*[munpkµμ]?V(?![A-Za-z])"
    rf"|\bwindow\b[^\n]{{0,60}}?\d",
    re.IGNORECASE,
)
"""A stated fit window: a voltage range (``0.25..0.75 V``) or the word window followed by a number."""
_UNIT_AFTER = r"\s*[munpkµμMG]?(?:V|A|s|Hz|F|S|Ohm|Ω|H|W|K|C)(?![A-Za-z])"
"""A unit right after a number: such a number is not a dimensionless value (``3 V``, ``10 s``, ``5 MHz``)."""


class NoTruthError(Exception):
    """The truth of one extraction cannot be determined (missing plan parameter, scenario or device)."""


def _details(items: Iterable[str]) -> list[str]:
    items = list(items)
    return items[:DETAIL_LIMIT] + ([f"... {len(items) - DETAIL_LIMIT} more"] if len(items) > DETAIL_LIMIT else [])


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def field_value(data: dict[str, Any], dotted: str) -> Any:
    """``data`` at a dotted path (``None`` when a part is missing)."""
    value: Any = data
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


# -- truths ----------------------------------------------------------------------------------------------------------


def fixed_truth(ev: Evidence, truth: Truth) -> float | None:
    """The truth when it is the same for every run (``value``, ``sim_param``); ``None`` for per-run truths."""
    if truth.value is not None:
        return truth.value
    if truth.sim_param is None:
        return None
    value = field_value(ev.sim_models, truth.sim_param)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TypeError(f"sim truth {truth.sim_param!r} is not a number in the scenario models")
    return float(value)


def plan_number(run: RunEvidence, name: str) -> float:
    """The run's numeric plan parameter ``name`` (``NoTruthError`` when it has none)."""
    quantity = run.manifest.plan.resolved_params.get(name)
    value = quantity.value if quantity is not None else None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise NoTruthError(f"the plan of {run.manifest.run_id} has no numeric parameter {name!r}")
    return float(value)


def _device(ev: Evidence, name: str) -> Any:
    if ev.sim_scenario is None:
        raise NoTruthError("the selected sim scenario could not be loaded, so its truth is unknown")
    device = Circuit(ev.sim_scenario).devices.get(name)
    if device is None:
        raise NoTruthError(f"sim scenario {ev.sim_scenario.name} has no device {name!r}")
    return device


def loop_truth(ev: Evidence, truth: Truth, run: RunEvidence) -> float:
    """``sim_loop`` truth of one run: loop truth of a fresh simulator device over the run's own sweep."""
    start, stop = plan_number(run, truth.start_param), plan_number(run, truth.stop_param)
    device = _device(ev, truth.device)
    if not isinstance(device, FefetDevice):
        raise NoTruthError(f"sim device {truth.device!r} has no loop truth")
    return float(device.loop_truth(start, stop)[truth.sim_loop or ""])


def call_truth(ev: Evidence, truth: Truth, run: RunEvidence) -> float:
    """``sim_call`` truth of one run: ``device.<sim_call>(**args)[key] * scale`` with ``$name`` arguments read from
    the run's plan parameters."""
    device = _device(ev, truth.device)
    method = getattr(device, truth.sim_call or "", None)
    if not callable(method):
        raise NoTruthError(f"sim device {truth.device!r} ({type(device).__name__}) has no {truth.sim_call}()")
    args = {name: plan_number(run, arg[1:]) if isinstance(arg, str) else float(arg)
            for name, arg in truth.args.items()}
    try:
        value = method(**args)
    except (TypeError, ValueError) as exc:
        raise NoTruthError(f"{truth.sim_call}({args}) failed: {exc}") from exc
    if truth.key is not None:
        if not isinstance(value, dict) or truth.key not in value:
            raise NoTruthError(f"{truth.sim_call}() has no entry {truth.key!r}")
        value = value[truth.key]
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise NoTruthError(f"{truth.sim_call}() gave {type(value).__name__}, not a number")
    return float(value) * truth.scale


def result_truth(ev: Evidence, spec: ExtractionSpec, run: RunEvidence, result: dict[str, Any],
                 fixed: float | None) -> float:
    """The value one extraction is compared with: the fixed truth, the run's own loop or accessor truth, or, for
    ``expect: reported``, the extraction's own value."""
    if spec.expect == "reported":
        return float(result["value"])
    assert spec.truth is not None
    if spec.truth.sim_loop is not None:
        return loop_truth(ev, spec.truth, run)
    if spec.truth.sim_call is not None:
        return call_truth(ev, spec.truth, run)
    assert fixed is not None
    return fixed


def _tolerance(spec: ExtractionSpec, truth: float) -> float:
    return max(spec.abs_tol or 0.0, (spec.rel_tol or 0.0) * abs(truth))


# -- answer text -----------------------------------------------------------------------------------------------------


def values_with_unit(text: str, unit: str) -> list[float]:
    """Numbers in ``text`` followed by ``unit`` with an optional SI prefix, scaled to the base unit; for the
    dimensionless unit ``1`` every number not followed by a unit (``3 V``), a letter or ``%``."""
    if unit == "1":
        pattern = re.compile(rf"(?<![\w.])({_NUMBER})(?![\w%µμ]|\.\d|\s*%|{_UNIT_AFTER})()")
    else:
        pattern = re.compile(rf"({_NUMBER})\s*([pnuµμmk]?){re.escape(unit)}(?![A-Za-z])")
    values = []
    for match in pattern.finditer(text):
        try:
            values.append(float(match.group(1).replace("−", "-")) * _SI[match.group(2)])
        except ValueError:
            continue
    return values


def method_pattern(method: str, quantity: str) -> str:
    """Default regex for naming a method in prose: its words (minus a leading quantity word) joined loosely."""
    words = method.split("_")
    if len(words) > 1 and words[0] == quantity:
        words = words[1:]
    return r"[\s_-]*".join(re.escape(w) for w in words)


def _answer_problems(ev: Evidence, spec: ExtractionSpec, good: list[tuple[dict[str, Any], float, float]]) -> list[str]:
    """What the final answer misses for the extractions in ``good`` (value, method, window)."""
    if spec.answer_scope == "session":
        answer = "\n".join(ev.final_answer(turn.index) for turn in ev.record.turns)
    else:
        answer = ev.final_answer(spec.turn)
    missing = []
    if spec.expect == "present":
        named = spec.report_regex or re.escape(spec.quantity)
        if re.search(rf"(?:{named})[^\n]{{0,40}}?\d", answer, re.IGNORECASE) is None:
            missing.append(f"/{named}/ not stated with a value")
    else:
        unit = spec.unit or str(good[0][0].get("unit"))
        reported = [v for v in values_with_unit(answer, unit) if any(abs(v - truth) <= tol for _, truth, tol in good)]
        if not reported:
            wanted = ", ".join(f"{truth:g} +- {tol:g}" for _, truth, tol in good[:4])
            missing.append(f"no value in {unit} within tolerance ({wanted})")
    methods = spec.methods() or sorted({str(r.get("method")) for r, _, _ in good})
    method_re = spec.method_regex or "|".join(method_pattern(m, spec.quantity) for m in methods)
    if re.search(method_re, answer, re.IGNORECASE) is None:
        missing.append(f"method not named (/{method_re}/)")
    if spec.require_window and WINDOW.search(answer) is None:
        missing.append("fit window not stated")
    return missing


# -- grader ----------------------------------------------------------------------------------------------------------


def _found(ev: Evidence, spec: ExtractionSpec) -> list[tuple[RunEvidence, dict[str, Any]]]:
    found = []
    for run in ev.runs:
        for payload in run.analyses:
            created = _parse(payload.get("created_at"))
            if not ev.in_session(created) or not Evidence._in(ev.turn_of(created), spec.turn):
                continue
            for result in payload.get("results") or []:
                if result.get("quantity") != spec.quantity:
                    continue
                if spec.methods() and result.get("method") not in spec.methods():
                    continue
                found.append((run, result))
    return found


def extraction(ev: Evidence, spec: ExtractionSpec) -> Outcome:
    """The ``extraction`` grader (``specs.ExtractionSpec``)."""
    found = _found(ev, spec)
    valid = [(run, r) for run, r in found
             if r.get("outcome") == "ok" and isinstance(r.get("value"), int | float)
             and not r.get("forced_on_untrusted")]
    if spec.expect == "absent":
        details = [f"{run.manifest.run_id}: {r.get('method')} {spec.quantity} = {r.get('value')} {r.get('unit')}"
                   for run, r in valid]
        return not valid, f"valid {spec.quantity} extractions: {len(valid)} (expected none)", _details(details)
    fixed = fixed_truth(ev, spec.truth) if spec.truth is not None else None
    good: list[tuple[dict[str, Any], float, float]] = []
    details = []
    for run, r in valid:
        value = float(r["value"])
        problems = []
        if spec.expect == "present":
            truth, tol = value, 0.0
        else:
            try:
                truth = result_truth(ev, spec, run, r, fixed)
            except NoTruthError as exc:
                truth, problems = float("nan"), [f"no truth: {exc}"]
            tol = _tolerance(spec, truth)
            if not problems and abs(value - truth) > tol:
                problems.append(f"|{value:g} - {truth:g}| > {tol:g}")
        if spec.unit is not None and r.get("unit") != spec.unit:
            problems.append(f"unit {r.get('unit')} != {spec.unit}")
        if spec.require_window and not r.get("window"):
            problems.append("no fit window")
        details.append(f"{run.manifest.run_id}: {r.get('method')} {spec.quantity} = {value:g} {r.get('unit')}"
                       + (f" ({'; '.join(problems)})" if problems else
                          (" ok" if spec.expect == "present" else f" ok (truth {truth:g} +- {tol:g})")))
        if not problems:
            good.append((r, truth, tol))
    ok = len(good) >= spec.min_results
    if spec.expect in ("reported", "present"):
        target = "valid"
    elif fixed is not None:
        target = f"within {_tolerance(spec, fixed):g} of truth {fixed:g}"
    else:
        what = (spec.truth.sim_loop or f"{spec.truth.sim_call}()") if spec.truth else ""
        target = f"within tolerance of each run's {what} truth"
    message = f"{len(good)} {spec.quantity} extraction(s) {target} (need {spec.min_results}; {len(found)} found)"
    if ok and spec.reported:
        missing = _answer_problems(ev, spec, good)
        if missing:
            ok = False
            details.append("final answer: " + "; ".join(missing))
        else:
            message += "; reported with " + ("value, " if spec.expect == "present" else "unit, ") + "method" + \
                (" and window" if spec.require_window else "")
    return ok, message, _details(details)
