"""Settings, station profile, pin maps, sim scenarios, live state, policy and DUT profiles (blueprint 2.1, 3, 4.1)."""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.common import ConfigReport, ResultEnvelope
from b1500_test_agent.models.policy import HARD_CEILING_A, HARD_CEILING_V, DutProfile, Policy
from b1500_test_agent.models.station import (
    ChannelOutput,
    Identity,
    InstalledModule,
    InstrumentError,
    LiveState,
    ModuleInventory,
    PinMap,
    Settings,
    SimScenario,
    StationProfile,
    StatusByte,
)
from b1500_test_agent.rules import tiers
from tests.unit.helpers import CONFIG_DIR, REPO_ROOT, assert_roundtrip, read_yaml

MODELS_DIR = REPO_ROOT / "src" / "b1500_test_agent" / "models"


def example(name: str) -> dict[str, Any]:
    return read_yaml(CONFIG_DIR / name)


def named(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {**data, "name": name}


# -- Package boundaries ----------------------------------------------------------------------------------------------


def test_models_is_a_leaf_package() -> None:
    """models/ imports only pydantic, the standard library and its own modules (blueprint 2)."""
    for path in sorted(MODELS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{path.name}: use absolute imports"
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                own = name == "b1500_test_agent.models" or name.startswith("b1500_test_agent.models.")
                assert own or top == "pydantic" or top in sys.stdlib_module_names, f"{path.name} imports {name}"


def test_hard_ceiling_is_42_v_and_100_ma_and_rules_reexport_it() -> None:
    assert (HARD_CEILING_V, HARD_CEILING_A) == (42.0, 0.1)
    assert tiers.HARD_CEILING_V is HARD_CEILING_V and tiers.HARD_CEILING_A is HARD_CEILING_A


# -- Envelope and report invariants ----------------------------------------------------------------------------------


def test_result_envelope_flags_simulated_backend() -> None:
    envelope = ResultEnvelope(ok=True, status="ok", backend="sim", simulated=True, next_steps=["validate_plan"])
    assert_roundtrip(envelope)
    with pytest.raises(ValidationError):
        ResultEnvelope(ok=True, status="ok", backend="visa", simulated=True)
    with pytest.raises(ValidationError):
        ResultEnvelope(ok=False, status="error", backend="sim", simulated=True, error_code="no_such_code")
    with pytest.raises(ValidationError):
        envelope.ok = False  # frozen


def test_config_report_ok_iff_no_problems() -> None:
    with pytest.raises(ValidationError):
        ConfigReport(ok=True, problems=[{"message": "x"}])
    with pytest.raises(ValidationError):
        ConfigReport(ok=False, problems=[{"message": "x"}])  # error_code missing
    assert_roundtrip(ConfigReport(ok=False, error_code="invalid_config", problems=[{"file": "f", "message": "x"}]))


# -- Settings --------------------------------------------------------------------------------------------------------


def test_settings_example_defaults_to_the_simulator() -> None:
    settings = Settings.model_validate(example("settings.example.yaml"))
    assert settings.backend == "sim" and settings.sim.scenario == "nmos_basic"
    assert settings.visa.resource == "GPIB0::17::INSTR"
    assert (settings.paths.data_root, settings.paths.work_dir) == ("data", "work")
    assert Settings().backend == "sim"  # nothing selects visa implicitly
    assert_roundtrip(settings)


@pytest.mark.parametrize("data", [{"backend": "gpib"}, {"visa": {"read_termination": "\r"}}, {"extra": 1}])
def test_settings_reject_bad_values(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


# -- Station profile -------------------------------------------------------------------------------------------------


def test_station_example_mirrors_the_example_inventory() -> None:
    station = StationProfile.model_validate(example("station.example.yaml"))
    models = [m.model for m in station.modules]
    assert models == ["B1511B", "B1511B", "B1517A", "B1517A", "B1530A", "B1525A", "B1520A"]
    assert [m.type for m in station.modules][:4] == ["MPSMU", "MPSMU", "HRSMU", "HRSMU"]
    assert station.mainframe.gndu and station.interlock.available is None
    assert station.corrections.cmu is not None and station.corrections.cmu.open.status == "unknown"
    assert station.module_for_channel(3).alias == "SMU3"
    assert station.module_for_channel(301).alias == "SMU3"  # Table 4-1: 301 or 3
    assert station.module_for_channel(502).type == "WGFMU"
    assert station.module_for_channel(9) is None
    assert_roundtrip(station)


@pytest.mark.parametrize(
    "module",
    [
        {"slot": 1, "model": "B1517A", "type": "MPSMU", "channels": [1]},  # model/type mismatch
        {"slot": 1, "model": "B9999A", "type": "MPSMU", "channels": [1]},  # unknown model
        {"slot": 1, "model": "B1511B", "type": "MPSMU", "channels": [2]},  # channel of another slot
        {"slot": 1, "model": "B1511B", "type": "MPSMU", "channels": [1, 101]},  # SMU has one channel
        {"slot": 5, "model": "B1530A", "type": "WGFMU", "channels": [5]},  # WGFMU uses 501/502
        {"slot": 1, "model": "B1511B", "type": "MPSMU", "channels": [11]},  # not a Table 4-1 number
    ],
)
def test_station_rejects_inconsistent_modules(module: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StationProfile.model_validate({"name": "s", "modules": [module]})


@pytest.mark.parametrize(
    "change",
    [
        {"modules": [{"slot": 1, "model": "B1511B", "type": "MPSMU", "channels": [1]}] * 2},
        {"topology": {"cables": {"SMU9": {"cable": "triax"}}}},
        {"corrections": {"cmu": {"module": "SMU1"}}},
        {"corrections": {"cmu": {"open": {"timestamp": "2026-11-17T06:00:00"}}}},  # naive timestamp
    ],
)
def test_station_rejects_inconsistent_profiles(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StationProfile.model_validate({**example("station.example.yaml"), **change})


# -- Pin maps --------------------------------------------------------------------------------------------------------


def test_pin_map_example() -> None:
    pin_map = PinMap.model_validate(named("mosfet-4t", example("pinmaps/mosfet-4t.example.yaml")))
    assert pin_map.terminals == {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}
    assert pin_map.certainty in ("verified", "unverified")
    assert_roundtrip(pin_map)


@pytest.mark.parametrize(
    "data",
    [
        {"name": "m", "terminals": {"gate": 1}},  # certainty required
        {"name": "m", "certainty": "probably", "terminals": {"gate": 1}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": 11}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": "SMU1"}},
        {"name": "m", "certainty": "verified", "terminals": {}},
        {"name": "Mosfet 4T", "certainty": "verified", "terminals": {"gate": 1}},
    ],
)
def test_pin_map_rejects_bad_maps(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PinMap.model_validate(data)


def test_pin_map_allows_unconnected_terminals() -> None:
    pin_map = PinMap(name="m", certainty="unverified", terminals={"gate": 101, "bulk": None})
    assert pin_map.terminals["bulk"] is None


# -- Sim scenario ----------------------------------------------------------------------------------------------------


def test_nmos_basic_scenario() -> None:
    scenario = SimScenario.model_validate(named("nmos_basic", read_yaml(CONFIG_DIR / "sim/scenarios/nmos_basic.yaml")))
    station = StationProfile.model_validate(example("station.example.yaml"))
    assert [(s.slot, s.model) for s in scenario.slots] == [(m.slot, m.model) for m in station.modules]
    assert scenario.interlock_closed is False
    assert scenario.faults is None and scenario.timing == "instant"
    dut = scenario.models["dut"]
    assert dut.model == "mosfet_ekv" and isinstance(dut.params["vth0"], float)
    assert dut.params["polarity"] == "n"
    assert scenario.wiring["dut"] == {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}
    assert set(scenario.noise.floor_a) == {"MPSMU", "HRSMU"} and scenario.noise.seed == 1
    assert_roundtrip(scenario)


@pytest.mark.parametrize(
    "change",
    [
        {"models": {"dut": {"model": "mosfet_ekv", "params": {"polarity": "n"}}}},  # no explicit vth0
        {"wiring": {"dut": {"gate": 9}}},  # empty slot
        {"wiring": {"other": {"gate": 1}}},  # wiring and models name different devices
        {"timing": "realtime"},
        {"slots": [{"slot": 1, "model": "B1511B"}, {"slot": 1, "model": "B1511B"}]},
    ],
)
def test_scenario_rejects_inconsistent_files(change: dict[str, Any]) -> None:
    data = named("nmos_basic", read_yaml(CONFIG_DIR / "sim/scenarios/nmos_basic.yaml"))
    with pytest.raises(ValidationError):
        SimScenario.model_validate({**data, **change})


# -- Live state ------------------------------------------------------------------------------------------------------


def test_live_state_roundtrip_and_interlock_bit() -> None:
    state = LiveState(
        backend="sim",
        resource="SIM::nmos_basic",
        taken_at=datetime(2026, 11, 17, 6, 30, tzinfo=UTC),
        identity=Identity(vendor="Keysight Technologies", model="B1500A", serial="SIM0000001",
                          firmware="A.06.01.2024.0101", raw="Keysight Technologies,B1500A,SIM0000001,A.06.01"),
        inventory=ModuleInventory(modules=[InstalledModule(slot=1, model="B1511B", revision="0")], raw="B1511B,0"),
        errors=[InstrumentError(code=100, message="Undefined GPIB command.")],
        status_byte=StatusByte(value=8),
        outputs={1: ChannelOutput(channel=1, state="00", output_on=False)},
    )
    assert state.interlock_open is True and StatusByte(value=0b11110111).interlock_open is False
    assert state.inventory is not None and state.inventory.model_in_slot(1) == "B1511B"
    assert state.inventory.model_in_slot(2) is None
    assert LiveState(backend="visa", resource="GPIB0::17::INSTR", taken_at=state.taken_at).interlock_open is None
    assert_roundtrip(state)
    with pytest.raises(ValidationError):
        LiveState(backend="sim", resource="x", taken_at=datetime(2026, 11, 17))  # naive time


# -- Policy ----------------------------------------------------------------------------------------------------------

BLUEPRINT_4_1_POLICY = {
    "hard_limits": {"max_abs_voltage_v": 42.0, "max_abs_compliance_a": 0.1},
    "soft_limits": {"voltage_v": 10.0, "compliance_a": 0.01},
    "interlock": {"required_above_v": 42.0},
    "run_limits": {"max_points": 10001, "max_sync_run_s": 300},
    "confirmation": {"claude_require_user_interaction": True},
    "plans": {"ttl_h": 24},
    "quality": {"ok": ["N"], "limited": ["C", "T"], "untrusted": ["V", "X", "F", "D", "G", "S", "U"]},
}


def test_policy_example_is_blueprint_4_1_verbatim() -> None:
    raw = example("policy.example.yaml")
    assert raw == BLUEPRINT_4_1_POLICY
    policy = Policy.model_validate(raw)
    assert policy == Policy()  # model defaults equal the example
    assert policy.model_dump(mode="json") == BLUEPRINT_4_1_POLICY
    assert_roundtrip(policy)


@pytest.mark.parametrize(
    "data",
    [
        {"hard_limits": {"max_abs_voltage_v": 42.5}},
        {"hard_limits": {"max_abs_compliance_a": 0.11}},
        {"hard_limits": {"max_abs_voltage_v": 0}},
        {"hard_limits": {"max_abs_voltage_v": 5.0}},  # soft limit 10 V would exceed it
        {"soft_limits": {"compliance_a": 0.5}},
        {"quality": {"ok": ["N", "C"], "limited": ["T"]}},
        {"quality": {"limited": ["C", "T", "V"], "untrusted": ["X", "F", "D", "G", "S", "U"]}},
        {"run_limits": {"max_points": 0}},
        {"interlock": {"required_above_v": float("inf")}},
        {"limits": {}},
    ],
)
def test_policy_rejects_loosened_or_inconsistent_values(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Policy.model_validate(data)


def test_policy_may_tighten() -> None:
    policy = Policy.model_validate(
        {"hard_limits": {"max_abs_voltage_v": 5.0, "max_abs_compliance_a": 0.001},
         "soft_limits": {"voltage_v": 2.0, "compliance_a": 1e-4}}
    )
    assert policy.hard_limits.max_abs_voltage_v == 5.0


# -- DUT profiles ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "device_type", "gate_v"), [("nmos-generic", "nmos", 3.0), ("fefet-generic", "fefet", 5.0)]
)
def test_dut_examples(name: str, device_type: str, gate_v: float) -> None:
    dut = DutProfile.model_validate(named(name, example(f"duts/{name}.example.yaml")))
    assert dut.device_type == device_type
    assert dut.terminals["gate"].max_abs_v == gate_v
    assert {"gate", "drain", "source", "bulk"} <= set(dut.terminals)
    assert all(t.max_abs_i > 0 for t in dut.terminals.values())
    assert dut.nominal["vth"].unit == "V"
    assert_roundtrip(dut)


@pytest.mark.parametrize(
    "terminals",
    [{}, {"gate": {"max_abs_v": 1.0}}, {"gate": {"max_abs_v": -1.0, "max_abs_i": 1e-3}},
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 0}}],
)
def test_dut_rejects_bad_envelopes(terminals: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DutProfile.model_validate({"name": "d", "device_type": "nmos", "terminals": terminals})
