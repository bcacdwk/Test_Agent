"""Debug-case schema, expectation grammar and case lint (v2.1 plan §3 item 4, WP21.4; ``devtools/skills/cases.py``)
and the step views the reproduction runner evaluates them on (``devtools/cases.py``).

The lint runs on a copy of the repository's ``b1500-debug`` skill with the committed ``config/`` and ``recipes/``; each
test edits one case and expects exactly the named problem. The grammar is Python syntax restricted to comparisons,
arithmetic, ``abs``/``min``/``max`` and step attributes and methods with constant arguments.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.cases import StepRecord, StepView
from b1500_test_agent.devtools.skills.cases import (
    CASE_KEYS,
    CASE_SECTIONS,
    CaseFrontmatter,
    ExpectationError,
    check_cases,
    evaluate_expectation,
    parse_expectation,
)
from b1500_test_agent.devtools.skills.common import Lint
from b1500_test_agent.models.analysis import ExtractionResult, MethodRecord

ROOT = Path(__file__).resolve().parents[2]
DEBUG = ROOT / ".agents" / "skills" / "b1500-debug"
CASE = "example-noisy-data"
REGISTRY = RecipeRegistry.load(ROOT / "recipes", repo_root=ROOT)


@pytest.fixture
def debug_dir(tmp_path: Path) -> Path:
    target = tmp_path / ".agents" / "skills" / "b1500-debug"
    shutil.copytree(DEBUG, target)
    return target


def lint(debug_dir: Path) -> list[tuple[str, str, str]]:
    root = debug_dir.parents[2]
    work = Lint(root, ROOT / "recipes", ROOT / "config")
    runbooks = sorted(p.stem for p in (debug_dir / "runbooks").glob("*.md"))
    check_cases(work, debug_dir, REGISTRY, runbooks)
    return [(p.code, Path(p.file).name, p.message) for p in work.problems]


def edit(debug_dir: Path, old: str, new: str, name: str = CASE) -> None:
    path = debug_dir / "cases" / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def front(**changes: Any) -> dict[str, Any]:
    data = yaml.safe_load((DEBUG / "cases" / f"{CASE}.md").read_text(encoding="utf-8").split("---")[1])
    return {**data, **changes}


# -- the committed cases and the template ------------------------------------------------------------------------------


def test_committed_cases_and_template_are_clean(debug_dir: Path) -> None:
    assert lint(debug_dir) == []
    template = yaml.safe_load((DEBUG / "cases" / "_TEMPLATE.md").read_text(encoding="utf-8").split("---")[1])
    assert tuple(template) == CASE_KEYS and template["status"] == "draft" and template["reviewed_by"] is None
    assert template["origin"] == "observed" and "deck" not in str(template["sources"])
    assert CASE_SECTIONS[-2:] == ("Simulator reproduction (SIMULATED)", "Open questions for the owner")


@pytest.mark.parametrize(("old", "new", "message"), [
    ("origin: observed ", "origin: illustrative ", "the template starts every case as origin: observed"),
    ("sources: [<run notes>, <lab notebook page>]", "sources: [<run notes>, <deck slide N>]",
     "the owner's deck is illustrative, never a source of a case"),
])
def test_the_template_drafts_observed_cases_without_the_deck(debug_dir: Path, old: str, new: str,
                                                             message: str) -> None:
    """v2.1 KD-5: an agent drafts what it saw (``origin: observed``); the template never offers the deck as a source
    (it invited ``<deck slide N>`` before)."""
    edit(debug_dir, old, new, "_TEMPLATE")
    assert [(code, name) for code, name, _ in lint(debug_dir)] == [("case", "_TEMPLATE.md")]
    assert message in lint(debug_dir)[0][2]


# -- review rules (CaseFrontmatter) ------------------------------------------------------------------------------------


OBSERVED = {"origin": "observed", "id": "2026-11-04-noisy-data", "title": "Large noise",
            "sources": ["lab notebook 3, p. 12"], "station": "lab-b1500"}
"""An observed version of the example case (a lab record of 2026-11-04 from outside the agent)."""
ILLUSTRATIVE = "an illustrative case (an example: nothing was observed) needs "


@pytest.mark.parametrize(("changes", "message"), [
    ({"status": "reviewed"}, "status reviewed needs reviewed_by"),
    ({"reviewed_by": "A. Owner"}, "status draft needs reviewed_by: null"),
    ({"status": "reviewed", "reviewed_by": "A. Owner"}, "status reviewed needs open_questions: 0 (has 2)"),
    ({"id": "noisy-data"}, "id"),
    # v2.1 KD-5: an illustrative case shows itself as an example and claims no observation
    ({"id": "2026-11-04-noisy-data"}, ILLUSTRATIVE + "id example-<slug>"),
    ({"title": "Large noise"}, ILLUSTRATIVE + "a title starting 'Example: '"),
    ({"backend": "visa"}, ILLUSTRATIVE + "backend: none"),
    ({"station": "unknown"}, ILLUSTRATIVE + "station: none"),
    ({"runs": ["H20261126T055822Z-523b"]}, ILLUSTRATIVE + "runs: []"),
    ({"backend": "sim", "runs": ["S20261126T055822Z-523b"]}, ILLUSTRATIVE + "backend: none, runs: []"),
    # an observed case is dated, rests on records of the observation and lists the runs of its backend
    ({"origin": "observed"}, "an observed case is named <YYYY-MM-DD>-<slug>"),
    ({**OBSERVED, "sources": ["deck slide 17"]}, "the owner's deck is illustrative, never one"),
    ({**OBSERVED, "backend": "visa"}, "backend visa needs the observation's runs (H...) in runs"),
    ({**OBSERVED, "backend": "sim"}, "backend sim needs the observation's runs (S...) in runs"),
    ({**OBSERVED, "backend": "visa", "runs": ["S20261126T055822Z-523b"]}, "runs of backend visa start with H"),
    ({**OBSERVED, "backend": "sim", "runs": ["H20261126T055822Z-523b"]}, "runs of backend sim start with S"),
    ({**OBSERVED, "runs": ["H20261126T055822Z-523b"]}, "backend none has no runs"),
    ({"backend": "lab"}, "backend"),
    ({"origin": "seen"}, "origin"),
])
def test_review_origin_and_backend_rules(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)").replace("[", r"\[")
                       .replace("]", r"\]").replace(".", r"\.")):
        CaseFrontmatter.model_validate(front(**changes))


@pytest.mark.parametrize("changes", [
    OBSERVED,  # a lab record without runs of this agent (backend none)
    {**OBSERVED, "backend": "visa", "runs": ["H20261126T055822Z-523b"]},
    {**OBSERVED, "backend": "sim", "runs": ["S20261126T055822Z-523b"]},
])
def test_observed_cases_that_are_valid(changes: dict[str, Any]) -> None:
    assert CaseFrontmatter.model_validate(front(**changes)).origin == "observed"


def test_a_reviewed_case_with_its_questions_answered_is_valid(debug_dir: Path) -> None:
    """What the human does: answers the questions, sets the status with their name, zero open questions."""
    path = debug_dir / "cases" / f"{CASE}.md"
    text = path.read_text(encoding="utf-8")
    head, questions = text.split("## Open questions for the owner\n")
    assert sum(line[:3] in {f"{n}. " for n in range(1, 6)} for line in questions.splitlines()) == 2
    head = head.replace("status: draft\nreviewed_by: null", "status: reviewed\nreviewed_by: A. Owner")
    head = head.replace("open_questions: 2", "open_questions: 0")
    path.write_text(head + "## Open questions for the owner\n\nNone: answered in the sections above.\n",
                    encoding="utf-8")
    assert lint(debug_dir) == []


# -- lint rules -------------------------------------------------------------------------------------------------------


LEAKAGE_STEP = ("recipe: mosfet.gate_leakage, pin_map: mosfet-4t, dut_profile: nmos-generic,\n"
                "       params: {integration")


@pytest.mark.parametrize(("old", "new", "messages"), [
    ('title: "Example: Large noise and point-to-point scatter"\nstatus: draft',
     'status: draft\ntitle: "Example: Large noise and point-to-point scatter"',
     ["frontmatter keys are id, title, status"]),
    ("## DUT hypotheses\n", "## Device hypotheses\n", ["sections are ## Symptom"]),
    ("None (illustrative).", "None (illustrative). TODO(owner).", ["TODO(owner) outside the section"]),
    ("open_questions: 2", "open_questions: 1", ["open_questions is 1 but the section"]),
    ("runbook: noisy-data", "runbook: noisy-dataset", ["runbook 'noisy-dataset' is not a runbooks/<id>.md file"]),
    ("`uv run b1500 dev cases reproduce example-noisy-data`;", "it;",
     ["names the command to regenerate it"]),
    ("  scenario: nmos_unshielded\n", "  scenario: nmos_shielded\n",
     ["reproduction scenario 'nmos_shielded'"] + ["scenario 'nmos_shielded' is neither"] * 5),
    (LEAKAGE_STEP + ": short}", LEAKAGE_STEP.replace("gate_leakage", "gate_leak") + ": short}",
     ["recipe 'mosfet.gate_leak' is not registered"]),
    ("params: {integration: short}", "params: {integration: short, vd: 0.1}", ["has no parameter(s) ['vd']"]),
    ("dut_profile: resistor-generic}\n    - {id: landed_idvg", "dut_profile: resistor-x}\n    - {id: landed_idvg",
     ["DUT profile 'resistor-x' is not in config/duts/"]),
    ("params: {integration: long}}\n  expect:",
     "params: {integration: long},\n       analyze: [{method: fit_all}]}\n  expect:",
     ["analysis method 'fit_all' is not registered"]),
    ("params: {integration: medium}}", "params: {integration: medium},\n       analyze: [{method: leakage_at}]}",
     ["leakage_at is a default analysis of mosfet.gate_leakage already"]),
])
def test_case_lint_finds_the_defect(debug_dir: Path, old: str, new: str, messages: list[str]) -> None:
    edit(debug_dir, old, new)
    problems = lint(debug_dir)
    assert {name for _, name, _ in problems} == {f"{CASE}.md"}
    assert len(problems) == len(messages), problems
    for message in messages:
        assert any(message in found for _, _, found in problems), (message, problems)


def test_a_runbook_must_name_its_case(debug_dir: Path) -> None:
    runbook = debug_dir / "runbooks" / "noisy-data.md"
    text = runbook.read_text(encoding="utf-8")
    old = ", example case example-noisy-data (illustrative)]"
    assert text.count(old) == 1
    runbook.write_text(text.replace(old, "]"), encoding="utf-8")
    expected = "runbook noisy-data's sources do not name this case (example-noisy-data)"
    assert [p[2] for p in lint(debug_dir)] == [expected]


def test_an_alias_needs_a_committed_base_and_must_not_shadow_one(debug_dir: Path) -> None:
    name = "example-igzo-vth-drift"
    edit(debug_dir, "rested_narrow: {base: igzo_drift_repeat}", "igzo_transient: {base: igzo_nowhere}", name)
    edit(debug_dir, "rested_short: {base: igzo_drift_repeat}", "rested_short: {base: igzo_drift_repeat, faults: "
                    "[{kind: no_such_fault}]}", name)
    messages = [p[2] for p in lint(debug_dir)]
    assert len(messages) == 1 and "faults.0" in messages[0]  # an invalid fault stops the frontmatter first
    edit(debug_dir, "rested_short: {base: igzo_drift_repeat, faults: [{kind: no_such_fault}]}",
         "rested_short: {base: igzo_drift_repeat}", name)
    messages = sorted(p[2] for p in lint(debug_dir))
    assert any("alias 'igzo_transient' shadows the committed scenario" in m for m in messages)
    assert any("alias 'igzo_transient': scenario 'igzo_nowhere' is not in" in m for m in messages)
    assert any("scenario 'rested_narrow' is neither" in m for m in messages)


def test_a_misnamed_case_file(debug_dir: Path) -> None:
    source = debug_dir / "cases" / f"{CASE}.md"
    source.rename(debug_dir / "cases" / "noisy.md")
    messages = [p[2] for p in lint(debug_dir)]
    assert any("a case is named <YYYY-MM-DD>-<slug>.md (date of the observation) or example-<slug>.md" in m
               for m in messages)
    assert any("id 'example-noisy-data' differs from the file name 'noisy'" in m for m in messages)


def test_reproduction_null_needs_a_reason(debug_dir: Path) -> None:
    path = debug_dir / "cases" / f"{CASE}.md"
    text = path.read_text(encoding="utf-8")
    start, end = text.index("reproduction:\n"), text.index("open_questions:")
    body_start = text.index("## Simulator reproduction (SIMULATED)\n") + len("## Simulator reproduction (SIMULATED)\n")
    body_end = text.index("## Open questions for the owner")
    text = text[:start] + "reproduction: null\n" + text[end:body_start] + "\n" + text[body_end:]
    path.write_text(text, encoding="utf-8")
    expected = ("reproduction is null: the section 'Simulator reproduction (SIMULATED)' says why (no simulator model "
                "of the cause)")
    assert [p[2] for p in lint(debug_dir)] == [expected]


# -- grammar ----------------------------------------------------------------------------------------------------------


STEPS = ("a", "b")


@pytest.mark.parametrize("text", [
    "a.snr('drain_I') < 10",
    "a.result('vth') < b.result('vth') < 1.0",
    "abs(a.value('gate_I', 0) / b.value_at('gate_Cp', 'dc_v', -0.65) - 1) > 0.02",
    "'R-CORR-01' in a.blocked_by and a.outcome == 'refused' or not b.tier",
    "min(a.count('C'), b.count('V')) == 0 and max(1, 2) >= +1",
    "a.classification('resistance', 'resistance') in ['open', 'short']",
])
def test_grammar_accepts(text: str) -> None:
    assert isinstance(parse_expectation(text, STEPS), ast.Expression)


@pytest.mark.parametrize(("text", "message"), [
    ("c.snr('x') < 1", "'c' is not a step id"),
    ("a < 1", "'a' alone means nothing"),
    ("d < 1", "unknown name 'd'"),
    ("a.plan_hash == 'x'", "step attribute 'plan_hash' unknown"),
    ("a.delete('x')", "step method 'delete' unknown"),
    ("a.value('gate_I') > 0", "value() takes 2 constant argument(s)"),
    ("a.result('m', 'q', 'r') > 0", "result() takes 1 or 2 constant argument(s)"),
    ("a.value('gate_I', b.count('C')) > 0", "value() takes 2 constant argument(s)"),
    ("a.snr(column='x') > 0", "calls take positional arguments only"),
    ("__import__('os')", "only abs, max, min() and step methods can be called"),
    ("a.snr('x') ** 2 > 1", "only + - * / are operators"),
    ("[x for x in (1, 2)]", "ListComp is not allowed"),
    ("(lambda: 1)()", "only abs, max, min() and step methods can be called"),
    ("a.run_id.upper() == 'X'", "is not a step id"),
    ("a.snr('x') < ", "not an expression"),
    ("abs()", "abs() needs arguments"),
    ("1 is 1", "only == != < <= > >= in, not in compare"),
])
def test_grammar_refuses(text: str, message: str) -> None:
    with pytest.raises(ValueError) as info:
        parse_expectation(text, STEPS)
    assert message in str(info.value)


class FakeStep:
    def __init__(self, **values: Any) -> None:
        self.values = values

    def attribute(self, name: str) -> Any:
        return self.values[name]

    def call(self, method: str, args: tuple[Any, ...]) -> Any:
        if method == "count":
            raise ExpectationError("step has no run")
        return self.values[f"{method}{args}"]


def evaluate(text: str, **steps: FakeStep) -> tuple[Any, list[str]]:
    terms: list[str] = []
    value = evaluate_expectation(parse_expectation(text, list(steps)), dict(steps), terms)
    return value, terms


def test_evaluation_reads_each_term_once() -> None:
    a = FakeStep(**{"result('vth',)": 0.878}, tier="ok")
    b = FakeStep(**{"result('vth',)": 0.9292})
    value, terms = evaluate("a.result('vth') < b.result('vth') and b.result('vth') - a.result('vth') > 0.05", a=a,
                            b=b)
    assert value is True
    assert terms == ["a.result('vth') = 0.878", "b.result('vth') = 0.9292"]
    assert evaluate("a.tier == 'ok' and -1 < 0", a=a)[0] is True
    assert evaluate("a.result('vth') > 1 > 0", a=a)[0] is False  # a chain stops at the first false link


@pytest.mark.parametrize(("text", "message"), [
    ("a.count('C') == 0", "step has no run"),
    ("a.result('vth') / 0 > 1", "division by zero"),
    ("a.tier + 1 > 0", "'ok' is not a number"),
    ("a.tier < 1", "cannot compare 'ok' with 1"),
])
def test_evaluation_errors(text: str, message: str) -> None:
    a = FakeStep(**{"result('vth',)": 0.878}, tier="ok")
    with pytest.raises(ExpectationError, match=message):
        evaluate(text, a=a)


# -- step views (devtools/cases.py) -----------------------------------------------------------------------------------


def extraction(method: str, quantity: str, value: float | None, classification: str | None = None,
               error: str | None = None) -> ExtractionResult:
    return ExtractionResult(method=method, quantity=quantity, value=value, unit="1",
                            method_record=MethodRecord(name=method, version="1", params={}), window=None, points_used=1,
                            points_excluded={}, fit={}, warnings=[], outcome="ok" if error is None else "refused",
                            error=error, classification=classification)


def view(run_id: str | None = "S20261126T055822Z-523b") -> StepView:
    record = StepRecord(id="symptom", scenario="gd_short", recipe="mosfet.idvg", pin_map="mosfet-4t", tier="ok",
                        run_id=run_id, outcome="completed" if run_id else None, blocked_by=["R-X-01"])
    table = pd.DataFrame({"step": [0, 1, 2], "dc_v": [2.0, 0.0, -2.0], "gate_Cp": [1.0, 2.0, 3.0],
                          "gate_Cp_status": ["N", "C", "V"]})
    return StepView(record=record, table=table, snr={"gate_Cp": 4.5}, status_counts={"C": 1},
                    analyses=[extraction("resistance", "resistance", 999.9, "in_range"),
                              extraction("impedance_convert", "d", 1.9), extraction("cv_cox", "d", 2.0),
                              extraction("cv_cox", "cox", None, error="no plateau")],
                    kind_result={"leakage_max_a": 4.5e-7})


def test_step_view_reads_its_run() -> None:
    step = view()
    assert step.attribute("blocked_by") == ["R-X-01"] and step.attribute("tier") == "ok"
    assert step.call("status", ("gate_Cp", 1)) == "C" and step.call("value", ("gate_Cp", -1)) == 3.0
    assert step.call("value_at", ("gate_Cp", "dc_v", -1.9)) == 3.0
    assert step.call("value_at", ("gate_Cp", "dc_v", 0.4)) == 2.0
    assert step.call("snr", ("gate_Cp",)) == 4.5 and step.call("count", ("C",)) == 1 and step.call("count", ("V",)) == 0
    assert step.call("result", ("resistance",)) == 999.9
    assert step.call("classification", ("resistance", "resistance")) == "in_range"
    assert step.call("result", ("impedance_convert", "d")) == 1.9
    assert step.call("kind", ("leakage_max_a",)) == 4.5e-7


@pytest.mark.parametrize(("method", "args", "message"), [
    ("status", ("drain_I", 0), "no column 'drain_I' (has step, dc_v, gate_Cp)"),
    ("value", ("gate_Cp", 3), "row 3 outside 0..2"),
    ("value", ("gate_Cp", True), "row True outside"),
    ("value_at", ("gate_Cp", "dc_v", "x"), "value_at needs a number"),
    ("snr", ("drain_I",), "no SNR for 'drain_I' (known: gate_Cp)"),
    ("result", ("d",), "2 analysis results d (methods: cv_cox, impedance_convert); exactly one is needed"),
    ("result", ("cv_cox", "cox"), "cv_cox.cox refused: no plateau"),
    ("result", ("vth",), "0 analysis results vth"),
    ("kind", ("points",), "kind_result has no 'points'"),
])
def test_step_view_errors(method: str, args: tuple[Any, ...], message: str) -> None:
    with pytest.raises(ExpectationError) as info:
        view().call(method, args)
    assert message in str(info.value)


def test_a_step_without_a_run_has_only_its_validation() -> None:
    step = view(run_id=None)
    assert step.attribute("tier") == "ok" and step.attribute("outcome") is None
    with pytest.raises(ExpectationError, match="step symptom has no run"):
        step.call("count", ("C",))
