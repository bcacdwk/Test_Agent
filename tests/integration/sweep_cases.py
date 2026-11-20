"""Shared requests, test scenarios and test-only config of the WP7.2 sweep recipes (blueprint v2 10.3 row 7.2).

- ``CASES``: the five v2 sweep recipes with their card example requests on their §3.1 scenarios (the integration,
  visa-loop and CLI tests use them; the shape matches ``tests/integration/test_plan_goldens.CASES``).
- ``TWO_RESISTORS``: a test scenario on the lab slot layout with R_A = 10 kOhm from terminal a (SMU3, HRSMU) to the
  GNDU and R_B = 100 kOhm from terminal b (SMU5, MPSMU) to the GNDU, for the test-only recipes of
  ``tests/fixtures/recipes/generic/`` (``bias_current``, ``current_family``, ``sync_current``, ``multi_mixed``) that
  exercise current sources (``DI``, ``WI``, ``WSI``, ``WNX`` mode 2) against Ohm's law.
- ``GENERIC_MULTI_*``: test-only pin maps and DUT profiles naming the ``c``/``d`` terminals of
  ``generic.smu_multi_sweep`` (no committed example has them, on purpose: generic recipes need the human's map).
- ``PG_TABLE_3_13``: the setup commands of the Programming Guide's multi-channel sweep example (Table 3-13,
  PDF 226-228, printed 3-46 to 3-48), with the example's channels t(0) emitter, t(1) base, t(2) collector.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from tests.integration.helpers import REPO_ROOT, World

CASES: list[dict[str, Any]] = [
    {"recipe_id": "basic.iv_force_i", "scenario": "diode_basic", "source": "card diode-iv",
     "request": {"params": {}, "pin_map": "diode-2t", "dut_profile": "diode-generic"}},
    {"recipe_id": "mosfet.idvg_family", "scenario": "nmos_basic", "source": "card mosfet-idvg",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}},
    {"recipe_id": "mosfet.idvg_sync", "scenario": "nmos_basic", "source": "card mosfet-idvg",
     "request": {"params": {}, "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}},
    {"recipe_id": "mosfet.body_effect", "scenario": "nmos_basic", "source": "card mosfet-idvg",
     "request": {"params": {}, "pin_map": "mosfet-4t-body", "dut_profile": "nmos-generic"}},
    {"recipe_id": "generic.smu_multi_sweep", "scenario": "resistor_100k", "source": "card smu-spot-kelvin",
     "request": {"params": {}, "pin_map": "resistor-2t", "dut_profile": "resistor-generic"}},
]
"""The WP7.2 recipes with the request their card shows (example plan or variant command) on their scenario."""

R_A, R_B = 1.0e4, 1.0e5
A_CH, B_CH = 3, 5

TWO_RESISTORS_NAME = "two_resistors"
TWO_RESISTORS: dict[str, Any] = {
    "description": "Test scenario (WP7.2): 10 kOhm a (SMU3) to GNDU, 100 kOhm b (SMU5) to GNDU; noiseless.",
    "idn": "Keysight Technologies,B1500A,SIM0000001,A.06.01.2024.0101",
    "slots": [{"slot": 1, "model": "B1525A"}, {"slot": 2, "model": "B1530A"}, {"slot": 3, "model": "B1517A"},
              {"slot": 4, "model": "B1517A"}, {"slot": 5, "model": "B1511B"}, {"slot": 6, "model": "B1511B"},
              {"slot": 7, "model": "B1520A"}],
    "interlock_closed": False,
    "wiring": {"ra": {"a": A_CH, "b": "GNDU"}, "rb": {"a": B_CH, "b": "GNDU"}},
    "models": {"ra": {"model": "resistor", "params": {"r_ohm": R_A}},
               "rb": {"model": "resistor", "params": {"r_ohm": R_B}}},
    "noise": {"floor_a": {}, "rel": 0.0, "seed": 11},
    "faults": None,
    "timing": "instant",
}

TWO_TERMINAL_CONFIG: dict[str, Any] = {
    "pinmaps/two-r.yaml": {"certainty": "verified", "terminals": {"a": A_CH, "b": B_CH, "g": "GNDU"}},
    "duts/two-r.yaml": {"device_type": "resistor", "terminals": {
        "a": {"max_abs_v": 2.0, "max_abs_i": 1e-3}, "b": {"max_abs_v": 2.0, "max_abs_i": 1e-3},
        "g": {"max_abs_v": 0.0, "max_abs_i": 1e-2}}},
    f"sim/scenarios/{TWO_RESISTORS_NAME}.yaml": TWO_RESISTORS,
}
"""Pin map ``two-r``, DUT profile ``two-r`` and the scenario file, written into a world's ``B1500_CONFIG_DIR``."""

FIXTURE_RECIPES = ("bias_current", "current_family", "sync_current", "multi_mixed")
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "recipes" / "generic"

GENERIC_MULTI_RESISTOR: dict[str, Any] = {
    "pinmaps/multi-r.yaml": {"certainty": "verified", "terminals": {"a": 3, "c": 4, "b": "GNDU"}},
    "duts/multi-r.yaml": {"device_type": "resistor", "terminals": {
        "a": {"max_abs_v": 1.0, "max_abs_i": 1e-3}, "c": {"max_abs_v": 1.0, "max_abs_i": 1e-3},
        "b": {"max_abs_v": 1.0, "max_abs_i": 1e-3}}},
}
"""``generic.smu_multi_sweep`` on ``resistor_100k`` with a second sweep terminal c on SMU4 (wired to nothing)."""

GENERIC_MULTI_NMOS: dict[str, Any] = {
    "pinmaps/multi-nmos.yaml": {"certainty": "verified", "terminals": {"a": 4, "c": 3, "b": "GNDU"}},
    "duts/multi-nmos.yaml": {"device_type": "nmos", "terminals": {
        "a": {"max_abs_v": 3.0, "max_abs_i": 1e-3}, "c": {"max_abs_v": 3.0, "max_abs_i": 1e-3},
        "b": {"max_abs_v": 1.0, "max_abs_i": 1e-3}}},
}
"""``generic.smu_multi_sweep`` on ``nmos_basic``: a = the gate (SMU4), c = the drain (SMU3) swept with it."""

PG_EXAMPLE_CHANNELS = {"emitter": 5, "base": 3, "collector": 4}
"""t(0), t(1), t(2) of Table 3-13 placed on the lab station: emitter SMU5, base SMU3, collector SMU4."""

GENERIC_MULTI_PG: dict[str, Any] = {
    "pinmaps/pg-3-13.yaml": {"certainty": "verified", "terminals": {
        "a": PG_EXAMPLE_CHANNELS["base"], "d": PG_EXAMPLE_CHANNELS["collector"], "b": PG_EXAMPLE_CHANNELS["emitter"]}},
    "duts/pg-3-13.yaml": {"device_type": "other", "terminals": {
        "a": {"max_abs_v": 1.0, "max_abs_i": 0.1}, "d": {"max_abs_v": 3.0, "max_abs_i": 0.1},
        "b": {"max_abs_v": 0.0, "max_abs_i": 0.1}}},
}
"""Table 3-13's bipolar transistor as ``generic.smu_multi_sweep`` terminals: base a (primary sweep), collector d (DC
bias), emitter b (an SMU at 0 V)."""

PG_EXAMPLE_PARAMS: dict[str, Any] = {"start": 0.1, "stop": 0.9, "points": 11, "icomp": 0.05, "bias_v": 3.0,
                                     "bias_icomp": 0.05}
"""Table 3-13's values (vb1 0.1 V, vb2 0.9 V, nop1 11, collector 3 V); compliances 50 mA instead of 100 mA (see
``PG_TABLE_3_13_DIFFERENCES``)."""


def pg_table_3_13() -> list[str]:
    """The example's setup and trigger commands (PDF 227, lines 31-49) with its channels resolved, in order."""
    e, b, c = (PG_EXAMPLE_CHANNELS[k] for k in ("emitter", "base", "collector"))
    return ["FMT 1,1", "TSC 1", "FL 1", "AV 10,1", f"MM 16,{b},{c}", f"CMM {b},1", f"CMM {c},1", f"RI {b},-19",
            f"RI {c},-19", "WT 0,0,0", "WM 2,1", f"WV {b},1,0,0.1,0.9,11,0.1,0.1", f"DV {c},0,3,0.1",
            f"DV {e},0,0,0.1", "TSR", "XE"]


PG_TABLE_3_13_DIFFERENCES: dict[str, str] = {
    "TSC 1": "time stamps are not used by the staircase kinds (the example reads them as Tb/Tc)",
    "TSR": "time stamp reset: no time stamps",
    "FL 1": "SMU filter stays at its initial setting (off) as in every v1 sweep",
    "AV 10,1": "integration through AAD/AIT presets (PG p225 (3-45): 'B1500 can use AAD/AIT instead of AV')",
    "RI": "auto ranging (initial setting) instead of the fixed 100 mA range",
    "WT 0,0,0": "WT sends only up to the last non-zero parameter: WT 0,0 sets the same timing",
    "Pcomp": "power compliance (the WV's eighth parameter) is not used by the kernel",
    "compliance": "50 mA instead of 100 mA on base and collector, so the emitter SMU's summed compliance is the "
                  "example's 100 mA (two 100 mA sources would give 200 mA there, blocked by R-LIM-02)",
    "order": "the kernel forces the DC biases (collector, emitter) right after CN, before the sweep setup; the "
             "example sets them after WV; both are in place when XE fires",
}
"""Documented differences between the kernel's preview and Table 3-13 (every other command is identical)."""


def install_fixture_recipes(world: World) -> None:
    """A temporary recipes folder with ``recipes/`` plus the WP7.2 test-only recipes; the world uses it."""
    recipes = world.root / "recipes"
    if not recipes.exists():
        shutil.copytree(REPO_ROOT / "recipes", recipes)
    for name in FIXTURE_RECIPES:
        shutil.copy(FIXTURE_DIR / f"{name}.yaml", recipes / "generic" / f"{name}.yaml")
    world.recipes = recipes


def use_two_resistors(world: World) -> None:
    """Select the ``two_resistors`` scenario with its pin map and DUT profile, and the test-only recipes."""
    for rel, data in TWO_TERMINAL_CONFIG.items():
        world.write_config(rel, data)
    settings = yaml.safe_load((REPO_ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"))
    settings["sim"]["scenario"] = TWO_RESISTORS_NAME
    world.write_config("settings.yaml", settings)
    install_fixture_recipes(world)


def fixture_recipe_dir(tmp: Path) -> Path:
    """A recipes folder under ``tmp`` with the repository recipes and the WP7.2 test-only recipes."""
    recipes = tmp / "recipes"
    shutil.copytree(REPO_ROOT / "recipes", recipes)
    for name in FIXTURE_RECIPES:
        shutil.copy(FIXTURE_DIR / f"{name}.yaml", recipes / "generic" / f"{name}.yaml")
    return recipes
