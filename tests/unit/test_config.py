"""Config resolution, digests, digest-cached reload and rule R-CFG-01 (blueprint 4.1, 4.2, 2.9)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from b1500_test_agent.config import ConfigLoader, check_config, load_config, load_yaml
from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.paths import ENV_CONFIG_DIR, ENV_HOME, Paths
from tests.unit.helpers import read_yaml, write_yaml

LOCAL = ("config", "local")


def local(repo: Path, *parts: str) -> Path:
    return repo.joinpath(*LOCAL, *parts)


def copy_examples_to_local(repo: Path, items: tuple[str, ...] = ("settings", "station", "policy")) -> None:
    """What the owner does on the lab PC: copy examples into config/local/ (here: a temporary repository)."""
    for item in items:
        target = local(repo, f"{item}.yaml")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / "config" / f"{item}.example.yaml", target)


def set_backend(path: Path, backend: str) -> None:
    data = read_yaml(path)
    data["backend"] = backend
    write_yaml(path, data)


# -- Committed examples ----------------------------------------------------------------------------------------------


def test_committed_examples_validate(repo_paths: Paths) -> None:
    bundle = load_config(repo_paths)
    assert bundle.backend == "sim"
    assert "example" in bundle.backend_reason
    assert set(bundle.pin_maps) >= {"mosfet-4t"}
    assert set(bundle.dut_profiles) >= {"nmos-generic", "fefet-generic"}
    assert bundle.sim_scenario is not None and bundle.sim_scenario.name == "nmos_basic"
    assert {f.source for f in bundle.files.values()} == {"example"}
    assert bundle.warnings == []
    for key, info in bundle.files.items():
        raw = (repo_paths.repo_root / info.path).read_bytes()
        assert info.sha256 == hashlib.sha256(raw).hexdigest() == bundle.sha256(key)
    assert bundle.files["policy"].path == "config/policy.example.yaml"
    assert bundle.files["pinmaps/mosfet-4t"].path == "config/pinmaps/mosfet-4t.example.yaml"
    assert bundle.report().ok


def test_every_committed_config_file_is_used(repo_paths: Paths) -> None:
    """No committed example is silently ignored (e.g. a pin map without the .example suffix)."""
    bundle = load_config(repo_paths)
    used = {(repo_paths.repo_root / f.path).resolve() for f in bundle.files.values()}
    committed = {
        p.resolve()
        for p in repo_paths.config_dir.rglob("*.yaml")
        if "sim" not in p.relative_to(repo_paths.config_dir).parts
    }
    committed.add((repo_paths.config_dir / "sim" / "scenarios" / "nmos_basic.yaml").resolve())
    assert committed <= used


# -- Resolution order ------------------------------------------------------------------------------------------------


def test_local_file_wins_over_example(repo: Path, repo_paths: Paths) -> None:
    copy_examples_to_local(repo, ("policy",))
    policy = read_yaml(local(repo, "policy.yaml"))
    policy["soft_limits"]["voltage_v"] = 5.0
    write_yaml(local(repo, "policy.yaml"), policy)
    bundle = load_config(repo_paths)
    assert bundle.files["policy"].source == "local"
    assert bundle.files["policy"].path == "config/local/policy.yaml"
    assert bundle.policy.soft_limits.voltage_v == 5.0
    assert bundle.files["station"].source == "example"


def test_override_dir_wins_per_file(repo: Path, tmp_path: Path) -> None:
    override = tmp_path / "override"
    write_yaml(override / "policy.yaml", {"soft_limits": {"voltage_v": 2.0, "compliance_a": 0.001}})
    write_yaml(override / "pinmaps" / "mosfet-4t.yaml", {"certainty": "unverified", "terminals": {"gate": 2}})
    copy_examples_to_local(repo, ("station",))
    paths = Paths.from_env({ENV_CONFIG_DIR: str(override)}, repo_root=repo)
    bundle = load_config(paths)
    assert bundle.files["policy"].source == "override"
    assert bundle.policy.soft_limits.voltage_v == 2.0
    assert bundle.files["station"].source == "local"
    assert bundle.files["settings"].source == "example"
    assert bundle.pin_maps["mosfet-4t"].certainty == "unverified"
    assert bundle.files["pinmaps/mosfet-4t"].source == "override"


def test_override_settings_names_the_env_var(repo: Path, tmp_path: Path) -> None:
    write_yaml(tmp_path / "override" / "settings.yaml", {"backend": "sim"})
    bundle = load_config(Paths.from_env({ENV_CONFIG_DIR: str(tmp_path / "override")}, repo_root=repo))
    assert ENV_CONFIG_DIR in bundle.backend_reason


def test_settings_paths_are_applied(repo: Path, repo_paths: Paths) -> None:
    copy_examples_to_local(repo, ("settings",))
    settings = read_yaml(local(repo, "settings.yaml"))
    settings["paths"]["data_root"] = "archive"
    write_yaml(local(repo, "settings.yaml"), settings)
    bundle = load_config(repo_paths)
    assert bundle.paths.state_dir == repo.resolve() / "archive" / "state"
    assert bundle.report().paths["runs_dir"] == "archive/runs"


# -- R-CFG-01: backend selection ------------------------------------------------------------------------------------


def test_example_cannot_select_visa(repo: Path, repo_paths: Paths) -> None:
    set_backend(repo / "config" / "settings.example.yaml", "visa")
    report = check_config(repo_paths)
    assert not report.ok and report.error_code == "invalid_config"
    assert report.backend == "visa"
    assert any("example file can never select backend visa" in p.message for p in report.problems)
    with pytest.raises(InvalidConfigError) as info:
        load_config(repo_paths)
    assert info.value.code == "invalid_config"


def test_visa_without_local_files_is_invalid(repo: Path, repo_paths: Paths) -> None:
    copy_examples_to_local(repo, ("settings",))
    set_backend(local(repo, "settings.yaml"), "visa")
    report = check_config(repo_paths)
    assert not report.ok and report.error_code == "invalid_config"
    flagged = {p.file for p in report.problems}
    assert flagged == {"config/station.example.yaml", "config/policy.example.yaml"}
    assert all("requires config/local/" in p.message for p in report.problems)


def test_visa_with_local_files_is_valid_and_ignores_examples(repo: Path, repo_paths: Paths) -> None:
    copy_examples_to_local(repo)
    set_backend(local(repo, "settings.yaml"), "visa")
    bundle = load_config(repo_paths)
    assert bundle.backend == "visa"
    assert bundle.backend_reason.startswith("visa: selected by config/local/settings.yaml")
    assert {f.source for f in bundle.files.values()} == {"local"}
    assert bundle.pin_maps == {} and bundle.dut_profiles == {}  # example pin maps/DUT profiles never used on visa
    assert bundle.sim_scenario is None
    assert any("config/local/ only" in w for w in bundle.warnings)
    local(repo, "pinmaps").mkdir()
    shutil.copyfile(repo / "config" / "pinmaps" / "mosfet-4t.example.yaml", local(repo, "pinmaps", "mosfet-4t.yaml"))
    assert set(load_config(repo_paths).pin_maps) == {"mosfet-4t"}


def test_visa_refuses_the_override_dir(repo: Path, tmp_path: Path) -> None:
    copy_examples_to_local(repo)
    set_backend(local(repo, "settings.yaml"), "visa")
    (tmp_path / "override").mkdir()
    report = check_config(Paths.from_env({ENV_CONFIG_DIR: str(tmp_path / "override")}, repo_root=repo))
    assert not report.ok
    assert any(ENV_CONFIG_DIR in p.message for p in report.problems)


def test_visa_settings_in_override_dir_are_invalid(repo: Path, tmp_path: Path) -> None:
    copy_examples_to_local(repo)
    write_yaml(tmp_path / "override" / "settings.yaml", {"backend": "visa"})
    report = check_config(Paths.from_env({ENV_CONFIG_DIR: str(tmp_path / "override")}, repo_root=repo))
    assert not report.ok
    assert any("requires config/local/settings.yaml" in p.message for p in report.problems)


# -- R-CFG-01: schema and limits -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [("hard_limits", "max_abs_voltage_v", 50.0), ("hard_limits", "max_abs_compliance_a", 0.2)],
)
def test_hard_limits_above_code_ceiling_are_invalid(
    repo: Path, repo_paths: Paths, section: str, field: str, value: float
) -> None:
    copy_examples_to_local(repo, ("policy",))
    policy = read_yaml(local(repo, "policy.yaml"))
    policy[section][field] = value
    write_yaml(local(repo, "policy.yaml"), policy)
    report = check_config(repo_paths)
    assert not report.ok and report.error_code == "invalid_config"
    (problem,) = report.problems
    assert problem.file == "config/local/policy.yaml"
    assert problem.location == section
    assert "code ceiling" in problem.message


def test_schema_errors_are_structured(repo: Path, repo_paths: Paths) -> None:
    station = read_yaml(repo / "config" / "station.example.yaml")
    station["modules"][0]["model"] = "B1517A"  # an HRSMU declared as MPSMU
    station["shield"] = True  # unknown key
    write_yaml(local(repo, "station.yaml"), station)
    report = check_config(repo_paths)
    assert not report.ok
    locations = {p.location for p in report.problems}
    assert "shield" in locations and "modules.0" in locations
    assert {p.file for p in report.problems} == {"config/local/station.yaml"}
    assert report.files and report.backend == "sim"  # the failing report still shows what was used


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("backend: sim\nbackend: visa\n", "duplicate key"),
        ("backend: [sim\n", "Not valid UTF-8 YAML"),
        ("- sim\n", "top level must be a mapping"),
        ("", "top level must be a mapping"),
    ],
)
def test_yaml_problems_are_reported(repo: Path, repo_paths: Paths, text: str, message: str) -> None:
    local(repo, "settings.yaml").parent.mkdir(parents=True)
    local(repo, "settings.yaml").write_text(text, encoding="utf-8")
    report = check_config(repo_paths)
    assert not report.ok
    assert any(message in p.message and p.file == "config/local/settings.yaml" for p in report.problems)


def test_utf8_bom_is_accepted(repo: Path, repo_paths: Paths) -> None:
    local(repo, "settings.yaml").parent.mkdir(parents=True)
    local(repo, "settings.yaml").write_bytes(b"\xef\xbb\xbfbackend: sim  # Notepad BOM\n")
    assert check_config(repo_paths).ok


def test_load_yaml_rejects_duplicate_nested_keys() -> None:
    with pytest.raises(Exception, match="duplicate key"):
        load_yaml(b"hard_limits:\n  max_abs_voltage_v: 10\n  max_abs_voltage_v: 42\n")


def test_missing_core_file_lists_where_it_looked(repo: Path, repo_paths: Paths) -> None:
    (repo / "config" / "station.example.yaml").unlink()
    report = check_config(repo_paths)
    (problem,) = report.problems
    assert problem.file == "station"
    assert "config/local/station.yaml" in problem.message and "config/station.example.yaml" in problem.message


def test_name_must_match_file_name(repo: Path, repo_paths: Paths) -> None:
    write_yaml(local(repo, "duts", "nmos-a.yaml"), {"name": "nmos-b", "device_type": "nmos",
                                                   "terminals": {"gate": {"max_abs_v": 1, "max_abs_i": 1e-6}}})
    report = check_config(repo_paths)
    assert [p.location for p in report.problems] == ["name"]


def test_example_suffix_in_local_dir_is_flagged(repo: Path, repo_paths: Paths) -> None:
    target = local(repo, "pinmaps", "mosfet-4t.example.yaml")
    target.parent.mkdir(parents=True)
    shutil.copyfile(repo / "config" / "pinmaps" / "mosfet-4t.example.yaml", target)
    report = check_config(repo_paths)
    assert any("Rename it to mosfet-4t.yaml" in p.message for p in report.problems)


def test_missing_scenario_and_fault_profile(repo: Path, repo_paths: Paths) -> None:
    write_yaml(local(repo, "settings.yaml"), {"sim": {"scenario": "nope"}})
    report = check_config(repo_paths)
    assert [p.location for p in report.problems] == ["sim.scenario"]

    scenario = read_yaml(repo / "config" / "sim" / "scenarios" / "nmos_basic.yaml")
    scenario["faults"] = "flaky"
    write_yaml(local(repo, "sim", "scenarios", "faulty.yaml"), scenario)
    write_yaml(local(repo, "settings.yaml"), {"sim": {"scenario": "faulty"}})
    report = check_config(repo_paths)
    assert [p.location for p in report.problems] == ["faults"]
    write_yaml(repo / "config" / "sim" / "faults" / "flaky.yaml", {"errx": {"after_cmd": "XE", "code": 100}})
    report = check_config(repo_paths)  # not a SimFaultProfile (schema: models/sim.py)
    assert sorted(p.location for p in report.problems) == ["errx", "faults"]  # extra key, missing list
    write_yaml(repo / "config" / "sim" / "faults" / "flaky.yaml",
               {"faults": [{"kind": "errx", "after_cmd": "XE", "code": 100}]})
    bundle = load_config(repo_paths)
    assert bundle.sim_faults is not None and bundle.sim_faults.name == "flaky"
    assert bundle.sim_faults.faults[0].kind == "errx"
    assert bundle.files["sim/faults/flaky"].source == "example"
    assert bundle.files["sim/scenarios/faulty"].source == "local"


def test_pin_map_channel_without_module_warns(repo: Path, repo_paths: Paths) -> None:
    write_yaml(local(repo, "pinmaps", "odd.yaml"), {"certainty": "unverified", "terminals": {"gate": 9}})
    bundle = load_config(repo_paths)
    assert any("odd" in w and "channel 9" in w for w in bundle.warnings)


def test_bad_home_is_reported_not_raised(tmp_path: Path) -> None:
    report = ConfigLoader(environ={ENV_HOME: str(tmp_path / "missing")}).check()
    assert not report.ok and report.error_code == "invalid_config"
    assert ENV_HOME in report.problems[0].message


# -- Digest-cached reload --------------------------------------------------------------------------------------------


def test_loader_reloads_only_when_a_digest_changes(repo: Path, repo_paths: Paths) -> None:
    loader = ConfigLoader(repo_paths)
    first = loader.get()
    assert loader.get() is first  # unchanged files: cached bundle

    copy_examples_to_local(repo, ("policy",))  # same bytes, but a new file in a higher layer
    second = loader.get()
    assert second is not first and second.files["policy"].source == "local"
    assert second.files["policy"].sha256 == first.files["policy"].sha256
    assert second.digest != first.digest

    policy = read_yaml(local(repo, "policy.yaml"))
    policy["hard_limits"]["max_abs_voltage_v"] = 43.0
    write_yaml(local(repo, "policy.yaml"), policy)
    with pytest.raises(InvalidConfigError):
        loader.get()
    assert not loader.check().ok

    policy["hard_limits"]["max_abs_voltage_v"] = 20.0
    write_yaml(local(repo, "policy.yaml"), policy)
    third = loader.get()
    assert third.policy.hard_limits.max_abs_voltage_v == 20.0
    assert third.files["policy"].sha256 != second.files["policy"].sha256
