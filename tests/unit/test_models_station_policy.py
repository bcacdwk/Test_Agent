"""Settings, station profile, pin maps, sim scenarios, live state, policy and DUT profiles (blueprint 2.1, 3, 4.1)."""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from b1500_test_agent.models.common import ConfigReport, ResultEnvelope
from b1500_test_agent.models.policy import HARD_CEILING_A, HARD_CEILING_V, DutGeometry, DutProfile, Policy
from b1500_test_agent.models.station import (
    ChannelOutput,
    CorrectionRecord,
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
    cmu_side,
    switch_target,
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


def test_visa_bus_lifecycle_settings_default_to_per_transaction() -> None:
    """Blueprint v2 2.4 / ATV-13: per-transaction session by default; ``process`` is the fallback switch."""
    settings = Settings.model_validate(example("settings.example.yaml"))
    assert (settings.visa.session, settings.visa.lock_timeout_ms, settings.visa.exclusive_lock) == (
        "transaction", 5000, True)
    assert Settings().visa.session == "transaction"
    fallback = Settings.model_validate({"visa": {"session": "process", "lock_timeout_ms": 0}})
    assert (fallback.visa.session, fallback.visa.lock_timeout_ms) == ("process", 0)


@pytest.mark.parametrize("data", [{"backend": "gpib"}, {"visa": {"read_termination": "\r"}}, {"extra": 1},
                                  {"visa": {"session": "thread"}}, {"visa": {"lock_timeout_ms": -1}},
                                  {"visa": {"lock_timeout_ms": 600_001}}])
def test_settings_reject_bad_values(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


# -- Station profile -------------------------------------------------------------------------------------------------


def test_station_example_is_the_lab_layout() -> None:
    """Blueprint v2 1.1/7.3: SPGU1 slot 1, WGFMU1 slot 2, HRSMU 3-4, MPSMU 5-6 (B1511B, A or B at L0), CMU1 slot 7."""
    station = StationProfile.model_validate(example("station.example.yaml"))
    assert [(m.slot, m.model, m.type, m.alias) for m in station.modules] == [
        (1, "B1525A", "HVSPGU", "SPGU1"), (2, "B1530A", "WGFMU", "WGFMU1"), (3, "B1517A", "HRSMU", "SMU3"),
        (4, "B1517A", "HRSMU", "SMU4"), (5, "B1511B", "MPSMU", "SMU5"), (6, "B1511B", "MPSMU", "SMU6"),
        (7, "B1520A", "MFCMU", "CMU1")]
    assert station.modules[0].channels == [101, 102] and station.modules[1].channels == [201, 202]
    assert station.mainframe.gndu and station.interlock.available is None
    assert station.module_for_channel(3).alias == "SMU3"
    assert station.module_for_channel(301).alias == "SMU3"  # Table 4-1: 301 or 3
    assert station.module_for_channel(202).type == "WGFMU"
    assert station.module_for_channel(1).type == "HVSPGU"  # 1 and 101 address the same subchannel
    assert station.module_for_channel(9) is None
    assert set(station.corrections) == {"CMU1"} and station.corrections["CMU1"].load is None
    assert_roundtrip(station)


@pytest.mark.spgu
def test_station_example_switches_are_lab_shaped_and_unverified() -> None:
    """Two 16440A selectors (ports 0/1 and 2/3, inputs null), RSU201/RSU202 (wgfmu 201/202), SCUU/ASU unknown; every
    switch carries ``certainty: unverified`` (no wiring is proven by the lab code)."""
    station = StationProfile.model_validate(example("station.example.yaml"))
    by_id = {s.id: s for s in station.switches}
    assert list(by_id) == ["SEL1", "SEL2", "RSU201", "RSU202", "SCUU1", "ASU3", "ASU4"]
    assert all(s.certainty == "unverified" for s in station.switches)
    assert {k: (s.kind, s.present) for k, s in by_id.items()} == {
        "SEL1": ("selector_16440a", True), "SEL2": ("selector_16440a", True), "RSU201": ("rsu", True),
        "RSU202": ("rsu", True), "SCUU1": ("scuu", None), "ASU3": ("asu", None), "ASU4": ("asu", None)}
    assert {o: p.index for o, p in by_id["SEL1"].ports.items()} == {"OUT1": 0, "OUT2": 1}
    assert {o: p.index for o, p in by_id["SEL2"].ports.items()} == {"OUT1": 2, "OUT2": 3}
    for sel in ("SEL1", "SEL2"):
        assert all(p.inputs == {"smu": None, "pgu": None} for p in by_id[sel].ports.values())
        assert by_id[sel].rest == "open"
    assert by_id["RSU201"].ports["OUT"].inputs == {"wgfmu": 201, "smu": None}
    assert by_id["SEL1"].allows("OUT1", "pgu_open") and not by_id["SEL1"].allows("OUT2", "pgu_open")
    assert by_id["SEL1"].input_channel("OUT1", "smu") is None  # wiring unknown
    assert by_id["RSU202"].input_channel("OUT", "wgfmu") == 202
    assert station.target_problem("SEL1.OUT1") is None and station.target_problem(3) is None
    assert "not declared" in (station.target_problem("SEL9.OUT1") or "")
    assert "no output 'OUT3'" in (station.target_problem("SEL1.OUT3") or "")


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


def _sel(index: int = 0, **inputs: Any) -> dict[str, Any]:
    return {"id": "SELX", "kind": "selector_16440a", "present": True, "ports": {"OUT1": {"index": index,
                                                                                      "inputs": inputs}}}


@pytest.mark.parametrize(
    "change",
    [
        {"modules": [{"slot": 1, "model": "B1511B", "type": "MPSMU", "channels": [1]}] * 2},
        {"topology": {"cables": {"SMU9": {"cable": "triax"}}}},
        {"topology": {"switching": {"asu": None}}},  # v1 field: switches are declared under switches:
        {"corrections": {"SMU3": {"load": None}}},  # not an MFCMU alias
        {"corrections": {"CMU1": {"open": {"status": "performed"}}}},  # records are server state, not station
        {"corrections": {"CMU1": {"load": {"rs_ohm": 0}}}},
        {"switches": [_sel(), _sel()]},  # duplicate switch id
        {"switches": [{**_sel(), "id": "SMU3"}]},  # switch id = module alias
        {"switches": [_sel(4)]},  # ERSSP ports are 0-3
        {"switches": [_sel(0), {**_sel(0), "id": "SELY"}]},  # one ERSSP port on two selectors
        {"switches": [_sel(smu=101)]},  # smu input wired to an SPGU channel
        {"switches": [_sel(pgu=3)]},  # pgu input wired to an SMU
        {"switches": [_sel(smu=8)]},  # no module there
        {"switches": [_sel(cmu=7)]},  # a selector has no cmu input
        {"switches": [{**_sel(smu=None), "certainty": "verified"}]},  # verified with unknown wiring
        {"switches": [{**_sel(), "rest": "wgfmu"}]},  # not a selector state
        {"switches": [{"id": "RSU9", "kind": "rsu", "present": True, "ports": {"OUT": {"index": 3}}}]},  # not WGFMU
        {"switches": [{"id": "RSU9", "kind": "rsu", "present": True,
                       "ports": {"OUT": {"index": 201, "inputs": {"wgfmu": 202}}}}]},
        {"switches": [{"id": "ASU9", "kind": "asu", "present": None,
                       "ports": {"OUT": {"index": 3, "inputs": {"smu": 4}}}}]},  # ASU smu input = its own SMU
        {"switches": [{"id": "SCUU9", "kind": "scuu", "present": None,
                       "ports": {"OUT1": {"index": 101, "inputs": {"cmu": 7}}}}]},  # index must be an SMU channel
    ],
)
def test_station_rejects_inconsistent_profiles(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StationProfile.model_validate({**example("station.example.yaml"), **change})


def test_station_accepts_recorded_wiring_and_a_load_standard() -> None:
    data = example("station.example.yaml")
    data["switches"][0] = {**data["switches"][0], "certainty": "verified",
                           "ports": {"OUT1": {"index": 0, "inputs": {"smu": 5, "pgu": 101}},
                                     "OUT2": {"index": 1, "inputs": {"smu": 6}}}}  # PGU input of CH 2 not connected
    data["corrections"] = {"CMU1": {"load": {"ls_h": 0.0, "rs_ohm": 100.0, "description": "100 Ohm standard"}}}
    station = StationProfile.model_validate(data)
    sel1 = station.switch("SEL1")
    assert sel1 is not None and sel1.input_channel("OUT1", "pgu") == 101 and sel1.input_channel("OUT2", "pgu") is None
    assert station.corrections["CMU1"].load is not None and station.corrections["CMU1"].load.rs_ohm == 100.0


# -- Pin maps --------------------------------------------------------------------------------------------------------


def test_pin_map_example() -> None:
    pin_map = PinMap.model_validate(named("mosfet-4t", example("pinmaps/mosfet-4t.example.yaml")))
    assert pin_map.terminals == {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}
    assert pin_map.certainty in ("verified", "unverified")
    assert_roundtrip(pin_map)


@pytest.mark.parametrize(("name", "terminals", "certainty"), [
    ("mosfet-4t", {"gate": 4, "drain": 3, "source": "GNDU", "bulk": "GNDU"}, "verified"),
    ("mosfet-4t-body", {"gate": 4, "drain": 3, "source": "GNDU", "bulk": 5}, "verified"),
    ("diode-2t", {"anode": 3, "cathode": "GNDU"}, "verified"),
    ("resistor-2t", {"a": 3, "b": "GNDU"}, "verified"),
    ("mosfet-3t-lab", {"gate": 3, "drain": 4, "source": 5}, "unverified"),
    ("fefet-sel", {"gate": "SEL1.OUT1", "drain": 4, "source": "GNDU"}, "unverified"),
    ("fecap-wgfmu", {"top": "RSU201.OUT", "bottom": "RSU202.OUT"}, "unverified"),
    ("moscap-cmu", {"gate": "7H", "bulk": "7L"}, "unverified"),
])
def test_pin_map_examples_follow_the_lab_layout(name: str, terminals: dict[str, Any], certainty: str) -> None:
    """Blueprint v2 7.3: the v1 maps keep their HRSMU slots 3/4 (identical in the lab layout); the lab maps use SMU5,
    selector, RSU and MFCMU-side targets and stay unverified; every switch target resolves in the station example."""
    pin_map = PinMap.model_validate(named(name, example(f"pinmaps/{name}.example.yaml")))
    assert (pin_map.terminals, pin_map.certainty) == (terminals, certainty)
    station = StationProfile.model_validate(example("station.example.yaml"))
    assert all(station.target_problem(t) is None for t in pin_map.terminals.values())
    assert_roundtrip(pin_map)


@pytest.mark.parametrize(
    "data",
    [
        {"name": "m", "terminals": {"gate": 1}},  # certainty required
        {"name": "m", "certainty": "probably", "terminals": {"gate": 1}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": 11}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": "SMU1"}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": "SEL1."}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": "SEL1.OUT1.X"}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": "7X"}},
        {"name": "m", "certainty": "verified", "terminals": {"gate": "11H"}},
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


def test_pin_map_targets_parse() -> None:
    pin_map = PinMap(name="m", certainty="unverified",
                     terminals={"a": 3, "b": "GNDU", "c": "7H", "d": "10L", "e": "SEL2.OUT2", "f": "RSU201.OUT"})
    assert pin_map.switch_targets() == {"e": ("SEL2", "OUT2"), "f": ("RSU201", "OUT")}
    assert [cmu_side(t) for t in pin_map.terminals.values()] == [None, None, (7, "H"), (10, "L"), None, None]
    assert [switch_target(t) for t in ("SEL1.OUT1", "GNDU", 3, "7H")] == [("SEL1", "OUT1"), None, None, None]


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
    assert scenario.wiring["dut"] == {"gate": 4, "drain": 3, "source": "GNDU", "bulk": 5}  # mosfet-4t-body (WP7.2)
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

BLUEPRINT_V2_POLICY = {
    "hard_limits": {"max_abs_voltage_v": 42.0, "max_abs_compliance_a": 0.1},
    "soft_limits": {"voltage_v": 10.0, "compliance_a": 0.01},
    "interlock": {"required_above_v": 42.0},
    "run_limits": {"max_points": {"smu": 10001, "cmu": 10001, "wgfmu": 4000000}, "max_sync_run_s": 300,
                   "long_run_confirm_s": 600, "max_async_run_s": 86400, "segment_max_s": 30},
    "pulse": {"soft_abs_v": 5.0, "soft_count": 10000, "soft_on_time_s": 60.0, "max_duty": 0.5},
    "cmu": {"soft_dc_bias_v": 10.0, "soft_ac_vrms": 0.05},
    "corrections": {"require": ["phase", "open", "short"], "max_age_h": 8.0},
    "confirmation": {"claude_require_user_interaction": True},
    "plans": {"ttl_h": 24},
    "quality": {"ok": ["N"], "limited": ["C", "T"], "untrusted": ["V", "X", "F", "D", "G", "S", "U"]},
}
"""Blueprint v1 4.1 plus the v2 sections with the OD-3 defaults (blueprint v2 2.3)."""


def test_policy_example_is_blueprint_v2_verbatim() -> None:
    raw = example("policy.example.yaml")
    assert raw == BLUEPRINT_V2_POLICY
    policy = Policy.model_validate(raw)
    assert policy == Policy()  # model defaults equal the example
    assert policy.model_dump(mode="json") == BLUEPRINT_V2_POLICY
    assert_roundtrip(policy)


def test_policy_accepts_the_v1_integer_max_points_for_every_family() -> None:
    """A v1 local policy (``max_points: 5000``) keeps validating; the integer caps every family (conservative)."""
    v1 = Policy.model_validate({"run_limits": {"max_points": 5000, "max_sync_run_s": 300}})
    assert v1.run_limits.max_points.model_dump() == {"smu": 5000, "cmu": 5000, "wgfmu": 5000}
    assert v1.run_limits.max_points.for_family("wgfmu") == 5000
    partial = Policy.model_validate({"run_limits": {"max_points": {"smu": 2000}}})
    assert partial.run_limits.max_points.model_dump() == {"smu": 2000, "cmu": 10001, "wgfmu": 4000000}
    assert_roundtrip(v1)


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
        {"run_limits": {"max_points": {"smu": 0}}},
        {"run_limits": {"max_points": {"hvspgu": 10}}},
        {"run_limits": {"max_points": True}},
        {"run_limits": {"long_run_confirm_s": 100}},  # below max_sync_run_s
        {"run_limits": {"max_async_run_s": 500}},  # below long_run_confirm_s
        {"run_limits": {"segment_max_s": 400}},  # above max_sync_run_s
        {"pulse": {"max_duty": 1.5}},
        {"pulse": {"soft_count": 0}},
        {"cmu": {"soft_ac_vrms": 0}},
        {"corrections": {"require": ["open", "short"]}},  # may not drop phase compensation
        {"corrections": {"require": ["phase", "open", "short", "short"]}},
        {"corrections": {"require": ["phase", "open", "short", "kelvin"]}},
        {"corrections": {"max_age_h": 0}},
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
         "soft_limits": {"voltage_v": 2.0, "compliance_a": 1e-4},
         "pulse": {"soft_abs_v": 3.0, "soft_count": 100, "soft_on_time_s": 1.0, "max_duty": 0.1},
         "cmu": {"soft_dc_bias_v": 2.0, "soft_ac_vrms": 0.03},
         "corrections": {"require": ["phase", "open", "short", "load"], "max_age_h": 2.0},
         "run_limits": {"max_points": {"wgfmu": 100000}, "max_sync_run_s": 60, "long_run_confirm_s": 60,
                        "max_async_run_s": 3600, "segment_max_s": 10}}
    )
    assert policy.hard_limits.max_abs_voltage_v == 5.0
    assert policy.corrections.require == ["phase", "open", "short", "load"]
    assert policy.run_limits.max_points.wgfmu == 100000 and policy.run_limits.segment_max_s == 10


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
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 0}},
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 1e-3, "impedance": "capacitive"}},
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 1e-3, "min_series_ohm": -1.0}},
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 1e-3, "pulse": {"max_abs_v": 3.0, "max_width_s": 1e-3}}},
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 1e-3,
               "pulse": {"max_abs_v": 3.0, "max_width_s": 1e-3, "max_duty": 2.0, "max_count": 10}}},
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 1e-3,
               "pulse": {"max_abs_v": 3.0, "max_width_s": 1e-3, "max_duty": 0.5, "max_count": 0}}},
     {"gate": {"max_abs_v": 1.0, "max_abs_i": 1e-3, "ac": {"max_vrms": 0}}}],
)
def test_dut_rejects_bad_envelopes(terminals: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DutProfile.model_validate({"name": "d", "device_type": "nmos", "terminals": terminals})


@pytest.mark.parametrize(("name", "device_type", "pulsed", "ac", "geometry"), [
    ("fefet-lab", "fefet", {"gate"}, set(), {"w_um", "l_um", "tox_nm"}),
    ("fecap-generic", "fecap", {"top", "bottom"}, {"top", "bottom"}, {"area_um2", "tox_nm"}),
    ("moscap-generic", "moscap", set(), {"gate", "bulk"}, {"area_um2", "tox_nm"}),
    ("capacitor-100p", "capacitor", set(), {"a", "b"}, None),
])
def test_dut_v2_examples(name: str, device_type: str, pulsed: set[str], ac: set[str],
                         geometry: set[str] | None) -> None:
    """Blueprint v2 7.3: the lab DUT examples carry impedance classes, pulse/AC envelopes and geometry."""
    dut = DutProfile.model_validate(named(name, example(f"duts/{name}.example.yaml")))
    assert dut.device_type == device_type
    assert {t for t, term in dut.terminals.items() if term.pulse is not None} == pulsed
    assert {t for t, term in dut.terminals.items() if term.ac is not None} == ac
    assert all(term.impedance != "unknown" for term in dut.terminals.values())
    if geometry is None:
        assert dut.geometry is None
    else:
        assert dut.geometry is not None
        assert {k for k, v in dut.geometry.model_dump().items() if v is not None} == geometry
    assert_roundtrip(dut)


def test_v1_dut_profiles_validate_unchanged_with_v2_defaults() -> None:
    dut = DutProfile.model_validate(named("nmos-generic", example("duts/nmos-generic.example.yaml")))
    gate = dut.terminals["gate"]
    assert (gate.impedance, gate.min_series_ohm, gate.pulse, gate.ac, dut.geometry) == (
        "unknown", None, None, None, None)
    with pytest.raises(ValidationError):
        DutGeometry()  # an empty geometry says nothing; leave it out


def test_correction_record_covers_frequencies_and_ages() -> None:
    record = CorrectionRecord(kind="open", freqs_hz=[1e6, 1e3, 1e5, 1e3], run_id="S20261117T053012Z-00cd",
                              ts=datetime(2026, 11, 17, 6, 0, tzinfo=UTC), idn="Keysight,B1500A,0,A.06",
                              pin_map_sha="a" * 64, station_sha="b" * 64, corr_state={"open": True})
    assert record.freqs_hz == [1e3, 1e5, 1e6]  # sorted, unique
    assert record.covers([1e5, 1e6]) and not record.covers([2e6])
    assert record.age_h(datetime(2026, 11, 17, 9, 0, tzinfo=UTC)) == pytest.approx(3.0)
    phase = record.model_copy(update={"kind": "phase", "freqs_hz": []})
    assert phase.covers([5e6])
    assert_roundtrip(record)
    with pytest.raises(ValidationError):
        CorrectionRecord.model_validate({**record.model_dump(), "freqs_hz": []})  # open needs its frequencies
    with pytest.raises(ValidationError):
        CorrectionRecord.model_validate({**record.model_dump(), "ts": "2026-11-17T06:00:00"})  # naive time


def test_settings_wgfmu_library_defaults_to_the_installer_path() -> None:
    settings = Settings.model_validate(example("settings.example.yaml"))
    assert settings.wgfmu.library == "" and Settings().wgfmu.library == ""
    assert Settings.model_validate({"wgfmu": {"library": "D:/keysight/wgfmu.dll"}}).wgfmu.library.endswith(".dll")
    with pytest.raises(ValidationError):
        Settings.model_validate({"wgfmu": {"path": "x"}})
