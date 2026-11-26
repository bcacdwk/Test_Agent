"""Debug cases of skill ``b1500-debug`` (v2.1 plan §3 items 2 and 5, WP21.4): every case's simulator reproduction runs
through ``B1500Service`` on temporary folders and shows its symptom signature and its discriminator (the runbook
check that separates the causes); this test is the authority the cases' "Simulator reproduction (SIMULATED)" sections
quote. The new scenarios meet their stated truth: ``nmos_unshielded`` (gate leakage 1e-11 S under a raised floor),
``moscap_leaky`` (1e-6 S oxide leakage), ``igzo_drift_repeat`` (the ATV-37 fallback: DC sweeps age the TFT) and the
gate-drain contact map ``mosfet-gd-2t`` on ``gd_short`` (1 kOhm short). Seeds are fixed, so a reproduction gives the
same values every time.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from b1500_test_agent.analysis import load_run
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.devtools.cases import (
    ReproductionReport,
    StepRecord,
    format_reproduction,
    load_cases,
    run_reproduction,
)
from b1500_test_agent.devtools.skills.cases import Case
from tests.integration.helpers import REPO_ROOT

CASES, PROBLEMS = load_cases(REPO_ROOT)
BY_ID: dict[str, Case] = {case.id: case for case in CASES}
SEED_CASES = ("example-current-orders-too-high", "example-cv-shape-abnormal", "example-igzo-vth-drift",
              "example-noisy-data")
"""The four illustrative example cases (v2.1 KD-5: written from the owner's planning deck, slide 17, which is
illustrative, not a lab record): the three v2 seeds and the C-V shape item added in v2.1."""
COX_F = 6.906e-11
"""Cox of the moscap_basic design (eps_ox 3.9, 5 nm, 1e4 um^2; config/sim/scenarios/moscap_basic.yaml)."""


@pytest.fixture(scope="module")
def registry() -> RecipeRegistry:
    return RecipeRegistry.load(REPO_ROOT / "recipes", repo_root=REPO_ROOT)


def reproduce(case_id: str, registry: RecipeRegistry, data_dir: Path) -> ReproductionReport:
    repro = BY_ID[case_id].front.reproduction
    assert repro is not None, case_id
    return run_reproduction(case_id, repro, root=REPO_ROOT, registry=registry, data_dir=data_dir)


def step(report: ReproductionReport, step_id: str) -> StepRecord:
    return next(s for s in report.steps if s.id == step_id)


def table(report: ReproductionReport, step_id: str, data_dir: Path) -> pd.DataFrame:
    run_id = step(report, step_id).run_id
    assert run_id is not None, step_id
    return load_run(run_id, data_root=data_dir).table


def test_the_four_example_cases_are_valid_drafts_with_a_reproduction() -> None:
    assert PROBLEMS == []
    assert sorted(BY_ID) == sorted(SEED_CASES)
    for case in CASES:
        front = case.front
        assert front.status == "draft" and front.reviewed_by is None, case.id
        assert front.origin == "illustrative" and front.title.startswith("Example: "), case.id
        assert front.backend == "none" and front.station == "none" and front.runs == [], case.id  # nothing observed
        assert front.reproduction is not None and front.open_questions > 0, case.id


# -- every reproduction ------------------------------------------------------------------------------------------------


def check_current_too_high(report: ReproductionReport, data_dir: Path) -> None:
    """``gd_short`` truth: a 1 kOhm gate-drain short; the gate-drain contact check reads it within 1 %."""
    contact = table(report, "contact", data_dir)
    slope = np.polyfit(contact["a_V"], contact["a_I"], 1)[0]
    assert 1.0 / slope == pytest.approx(1000.0, rel=0.01)
    symptom = table(report, "symptom", data_dir)
    assert list(symptom["gate_I_status"][:2]) == ["C", "V"]  # compliance at the first step, then the abort


def check_noisy_data(report: ReproductionReport, data_dir: Path) -> None:
    """``nmos_unshielded`` truth: gate leakage 1e-11 S (the long-integration gate current gives it within 10 %);
    the floor is raised: at short integration the same current scatters by more than its whole range."""
    long = table(report, "long", data_dir)
    assert np.polyfit(long["gate_V"], long["gate_I"], 1)[0] == pytest.approx(1e-11, rel=0.10)
    short = table(report, "symptom", data_dir)
    residual = short["gate_I"] - 1e-11 * short["gate_V"]
    assert np.std(residual) > 0.3 * 3e-11  # 15 pA of noise on a 30 pA signal


def check_igzo(report: ReproductionReport, data_dir: Path) -> None:
    """``igzo_drift_repeat`` truth: each sweep drifts towards 0.05 V/V of its top gate bias, so three sweeps to 3 V
    stay below 0.15 V of shift and three to 1.5 V below 0.075 V; the control (``igzo_transient``, quasi-static DC
    reads) does not drift."""
    assert all(s.outcome == "completed" for s in report.steps)
    vth = {line.split(" = ")[0]: float(line.split(" = ")[1])
           for record in (*report.expect, *report.discriminator) for line in record.terms}
    shift_full = vth["third.result('vth')"] - vth["first.result('vth')"]
    shift_narrow = vth["narrow_3.result('vth')"] - vth["narrow_1.result('vth')"]
    assert 0.0 < shift_full < 0.05 * 3.0 and 0.0 < shift_narrow < 0.05 * 1.5
    controls = [vth[f"control_{n}.result('vth')"] for n in (1, 2, 3)]
    assert max(controls) - min(controls) < 0.002
    first = table(report, "first", data_dir)
    assert len(first) == 101 and float(first["gate_V"].iloc[0]) == 0.0  # the plan of the reproduction


def check_cv(report: ReproductionReport, data_dir: Path) -> None:
    """``moscap_leaky`` truth: 1e-6 S of oxide leakage (the quasi-static C-V's leakage over +-0.5 V reads it within
    10 %), far above 0.1 wC at 1 kHz (D = G/(wC) > 0.1: the C-V criterion, not a fixed leakage current), and the
    moscap_basic capacitor (Cox at 1 MHz within 1 %); the lost corrections leave a refused run with no measurement
    table."""
    run_id = step(report, "leakage").run_id
    assert run_id is not None
    leakage_max = load_run(run_id, data_root=data_dir).manifest.kind_result["leakage_max_a"]
    assert isinstance(leakage_max, float) and leakage_max == pytest.approx(1e-6 * 0.45, rel=0.10)
    assert leakage_max / 0.5 > 0.1 * 2 * np.pi * 1e3 * COX_F  # G against wC at the 1 kHz C-V
    assert step(report, "cv_lost").outcome == "refused" and step(report, "cv_lost").error_code == "blocked_by_rules"
    assert "no run table" in step(report, "cv_lost").message
    assert step(report, "cv_blocked").run_id is None and step(report, "cv_blocked").tier == "blocked"
    leaky = table(report, "cv_leaky", data_dir)
    assert float(leaky["gate_Cp"].max()) > 1.25 * COX_F  # no S shape: Cp above Cox


CHECKS: dict[str, Callable[[ReproductionReport, Path], None]] = {
    "example-current-orders-too-high": check_current_too_high,
    "example-noisy-data": check_noisy_data,
    "example-igzo-vth-drift": check_igzo,
    "example-cv-shape-abnormal": check_cv,
}


@pytest.mark.parametrize("case_id", SEED_CASES)
def test_reproduction_shows_the_symptom_and_the_discriminator(case_id: str, registry: RecipeRegistry,
                                                              tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    report = reproduce(case_id, registry, data_dir)
    assert report.error is None, format_reproduction(report)
    assert report.expect and report.discriminator
    failed = [record for record in (*report.expect, *report.discriminator) if record.verdict != "pass"]
    assert failed == [], format_reproduction(report)
    assert report.ok and report.simulated is True and report.backend == "sim"
    assert report.data_dir == data_dir.as_posix()
    runs = [r for s in report.steps for r in ([s.run_id] if s.run_id else []) + s.corrections]
    assert runs and all(r.startswith("S") for r in runs)  # simulator runs only, never an H... id
    archived = {p.name for p in (data_dir / "runs").rglob("S*") if (p / "manifest.json").is_file()}
    assert set(runs) <= archived  # every run is in this reproduction's own data folder
    CHECKS[case_id](report, data_dir)


def test_a_reproduction_is_deterministic(registry: RecipeRegistry, tmp_path: Path) -> None:
    """Fixed seeds: two reproductions read the same values (the run ids differ)."""
    first = reproduce("example-noisy-data", registry, tmp_path / "one")
    second = reproduce("example-noisy-data", registry, tmp_path / "two")
    terms = [[record.terms for record in (*report.expect, *report.discriminator)] for report in (first, second)]
    assert terms[0] == terms[1] and first.ok and second.ok
