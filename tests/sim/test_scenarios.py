"""Committed simulator scenarios and fault profiles validate and run (blueprint 3); the config loader validates the
fault profile a scenario names."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.config import check_config, load_config
from b1500_test_agent.models.sim import FAULT_KINDS, SimFaultProfile
from b1500_test_agent.paths import Paths
from b1500_test_agent.transport.sim import SimTransport
from tests.sim.helpers import FAULT_DIR, REPO_ROOT, SCENARIO_DIR, load_scenario

SCENARIOS = sorted(p.stem for p in SCENARIO_DIR.glob("*.yaml"))
FAULT_FILES = sorted(FAULT_DIR.glob("*.yaml"))


def load_profile(path: Path) -> SimFaultProfile:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SimFaultProfile.model_validate({**data, "name": path.stem})


@pytest.mark.parametrize("name", SCENARIOS)
def test_committed_scenario_runs(name: str) -> None:
    scenario = load_scenario(name)
    if scenario.faults is not None:
        assert (FAULT_DIR / f"{scenario.faults}.yaml").is_file()
    transport = SimTransport(scenario, state_file=None)
    transport.open()
    assert transport.query("*IDN?") == scenario.idn
    transport.instrument.assert_safe()


@pytest.mark.parametrize("path", FAULT_FILES, ids=lambda p: p.stem)
def test_committed_fault_profile_validates(path: Path) -> None:
    profile = load_profile(path)
    assert profile.faults


def test_reference_profile_covers_every_fault_kind() -> None:
    profile = load_profile(FAULT_DIR / "reference.yaml")
    assert [f.kind for f in profile.faults] == list(FAULT_KINDS)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "config", root / "config", ignore=shutil.ignore_patterns("local"))
    (root / "pyproject.toml").write_text("[project]\nname = 'copy'\n", encoding="utf-8")
    return root


def test_config_bundle_carries_the_validated_fault_profile(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("B1500_HOME", "B1500_CONFIG_DIR", "B1500_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    paths = Paths.from_env({}, repo_root=repo)
    scenario_file = repo / "config" / "sim" / "scenarios" / "nmos_basic.yaml"
    scenario = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    assert load_config(paths).sim_faults is None
    scenario["faults"] = "flaky"
    scenario_file.write_text(yaml.safe_dump(scenario), encoding="utf-8")
    fault_file = repo / "config" / "sim" / "faults" / "flaky.yaml"
    fault_file.write_text(yaml.safe_dump({"faults": [{"kind": "slow", "factor": 0}]}), encoding="utf-8")
    report = check_config(paths)
    assert not report.ok and [p.location for p in report.problems] == ["faults.0.slow.factor"]
    fault_file.write_text(yaml.safe_dump({"faults": [{"kind": "oscillation"}]}), encoding="utf-8")
    bundle = load_config(paths)
    assert bundle.sim_faults is not None and bundle.sim_faults.faults[0].kind == "oscillation"
    assert "sim/faults/flaky" in bundle.files
