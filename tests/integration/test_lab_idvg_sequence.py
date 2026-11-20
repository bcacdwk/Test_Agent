"""The lab's Id-Vg FLEX sequence vs the ``mosfet.idvg`` preview on the lab pin map (blueprint v2 10.2 row 6.2 AC
"lwp Id-Vg FLEX sequence matched by the ``mosfet.idvg`` preview modulo documented FMT/range diffs").

The lab sequence is ``tests/fixtures/lab/lwp_test_idvg.txt`` (lwp ``test_IdVg.m`` + ``lib/IV_sweep.m``, read from
the code). The kernel's sequence is the FLEX preview of ``mosfet.idvg`` for the same measurement: pin map
``mosfet-3t-lab`` (gate SMU3, drain SMU4, source SMU5), gate -2..2 V in 61 steps, Vd 0.1 V, 1 PLC; every other
parameter at the recipe default. Both are reduced by a small FLEX interpreter to what the instrument holds when
``XE`` fires (``*RST`` returns to the initial settings, PG p180 (2-92) Table 2-13), and the two setups must agree
on every field except the ones listed in ``SETUP_DIFFERENCES``, which must differ exactly as listed. Commands that
are not part of the setup (``*RST``, selectors, synchronisation, queries, cleanup) are listed in
``FLOW_DIFFERENCES``; the visa-loop test ``tests/visa_loop/test_lab_idvg.py`` checks them on the wire. Every entry
says why the kernel's choice is deliberate. Summary for agents: knowledge file ``02-b1500-instrument.md`` section
"Lab scripts vs the kernel".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from b1500_test_agent.models.plan import PlanRequest
from tests.integration.helpers import World
from tests.unit.lab_fixtures import REAL_VD, load_sequence

LAB_PIN_MAP = "mosfet-3t-lab"
LAB_IDVG_REQUEST: dict[str, Any] = {
    "recipe_id": "mosfet.idvg", "pin_map": LAB_PIN_MAP, "dut_profile": "nmos-generic",
    "params": {"vg_start": -2.0, "vg_stop": 2.0, "vg_points": 61, "vd": REAL_VD},
}
"""``test_IdVg.m``'s measurement as a ``mosfet.idvg`` request (integration preset ``medium`` = the lab's
``AIT 0,2,1``)."""


@dataclass(frozen=True)
class Difference:
    lab: Any
    ours: Any
    why: str


SETUP_DIFFERENCES: dict[str, Difference] = {
    "format": Difference((21, 1), (1, 1), (
        "FMT 21 is the 13-digit 4155/4156 format with a 3-digit status number per value (PG p437 (4-119), "
        "p50 (1-30)), which the lab parser drops (IV_sweep.m:125: keep the value from its first sign on), so "
        "compliance and overflow go unnoticed; FMT 1 carries a status letter per element and the kernel keeps it "
        "(N/C/T/V/X columns, trust in the analysis). Mode 1 (source value per step) is the same.")),
    "bias.4.icomp": Difference(0.1, 0.001, (
        "the 100 mA pitfall: the lab drain runs at 100 mA compliance for a device whose on current is 0.42 uA; "
        "the recipe default is 1 mA (range up to 10 mA; the DUT profile and R-COMP rules decide), still 2,400x "
        "the on current, so a short is caught at 1 mA instead of 100 mA")),
    "bias.5.icomp": Difference(0.1, 0.001001, (
        "the grounded source SMU gets the sum of the sourcing roles' compliances (it returns at most their "
        "currents) instead of another 100 mA")),
    "measure.order": Difference((4, 3), (3, 4), (
        "the kernel puts the sweep role first, then recipe order; only the element order inside each step "
        "differs (same channels, same CMM 1)")),
    "range.3": Difference(11, 0, (
        "RI 11 = 1 nA limited auto ranging (PG p337 (4-19) Table 4-3): faster, but never below the 1 nA range "
        "(50 fA steps in the lab data); v1 recipes keep the initial auto ranging, which resolves the +-2e-13 A "
        "floor of the gate current; a range parameter is a later recipe option")),
    "range.4": Difference(11, 0, (
        "as range.3, for the drain current: the lab's off state (+-2e-13 A) is read on the 1 nA range, the "
        "kernel lets the HRSMU range down (10 pA range, 1 fA resolution, UG PDF 69-70)")),
    "timing.delay_s": Difference(0.01, 0.0, (
        "the lab waits 10 ms per step (WT 0,0.01); mosfet.idvg's delay_s defaults to 0 (WT 0,0, the v1 sequence): "
        "at 1 PLC the integration itself is 20 ms, and the displacement current the delay would let settle (about "
        "-0.4 pA in the lab curve's off state) sits at the floor; delay_s: 0.01 reproduces the lab timing "
        "(test_the_lab_delay_is_a_recipe_parameter)")),
    "sweep.range": Difference(12, 0, (
        "WV range 12 = 20 V limited auto ranging (PG p339 (4-21) Table 4-4) for a +-2 V sweep: the source never "
        "goes below the 20 V range; the kernel uses auto ranging (initial setting), i.e. the 2 V range with its "
        "finer source resolution")),
    "sweep.icomp": Difference(0.01, 1e-06, (
        "the lab gate sweeps with 10 mA compliance on a gate that leaks pA to 0.24 nA; the recipe default is "
        "1 uA (range up to 1 mA), so a gate-oxide breakdown is stopped at 1 uA")),
    "abort": Difference((1, 1), (2, 1), (
        "the lab leaves automatic abort off (initial WM 1); the kernel always sends WM 2,1: a compliance, "
        "overflow or oscillation stops the sweep, later steps read 199.999E+99 (status V) and the sweep source "
        "returns to the start value (PG p553 (4-235))")),
}
"""Setup fields where the kernel deliberately differs from ``test_IdVg.m`` (lab value, kernel value, why)."""

FLOW_DIFFERENCES: dict[str, str] = {
    "*RST": ("lab only (IV_sweep.m:55, before every setup): it resets the MFCMU corrections, sets the SPGU to "
             "free-run and resets the switch paths (PG p179-180 (2-91)) and hides what state the instrument was in "
             "(blueprint v2 1.1 pitfall); the kernel never sends it outside kind system (lint), sets every "
             "parameter it relies on and starts each transaction from a verified state (in-flight recovery, "
             "baseline ERRX? drain)"),
    "ERSSP": ("lab only (IV_sweep.m:35-38): four ERSSP p,0 without ERMOD 1 (commented out), so the selector "
              "control mode may be off; state 0 means open, not 'to SMU' (PG p433 (4-115)), and the *RST that "
              "follows resets the paths anyway; the lab pin map is SMU-direct, and selector routes belong to the "
              "switch kinds (ERMOD 1, routes verified with ERSSP?, rest after the run)"),
    "FMT": "lab sends FMT 21,1 twice (test_IdVg.m:61 and IV_sweep.m:56); the kernel once, after the lock",
    "AAD": ("kernel only: the ADC type is written for each measured channel (high-speed, the initial setting the "
            "lab relies on after its *RST) because the kernel never resets"),
    "WM": "kernel only: see setup field abort",
    "RI": "lab only: see setup fields range.3/range.4",
    "*OPC?": ("lab only (IV_sweep.m:105): the kernel's data read after XE blocks until the data are complete, with a "
              "timeout of 2 x estimate + 10 s"),
    "ERRX?": ("lab: once after the sweep, failing unless the answer starts with '+0,' (IV_sweep.m:107-110); the "
              "kernel drains before XE (setup errors abort before triggering), after CN, at the transaction start "
              "and in the cleanup, and accepts both '0,' (PG p432 (4-114)) and the lab firmware's '+0,'"),
    "*IDN?": ("lab: identity once at connect; the kernel reads *IDN?, UNT?, ERRX?, *STB?, LOP? and *LRN? 31 before "
              "each run (pre-execute rules: inventory R-INV-01, auto-calibration R-CAL-01, fault state)"),
    "LOP?": ("kernel only: the hardware positive control (outputs on after CN) and the cleanup's verification "
             "(all 00 after CL); the lab never checks the output state"),
    "cleanup": ("lab: DZ, CL in the script's finally block, unverified; kernel: AB if a measurement is pending, DZ, "
                "CL, ERRX? drain, LOP? verify, device clear and one retry, else the fault latch"),
}
"""Commands outside the setup where the flows differ (by mnemonic; ``cleanup`` = the end of the sequence)."""

INITIAL: dict[str, Any] = {"format": (1, 0), "abort": (1, 1), "timing.hold_s": 0.0, "timing.delay_s": 0.0,
                           "triggers": 0}
"""The initial settings the fields start from and ``*RST`` returns to (PG p180 (2-92) Table 2-13: ASCII with header
CR/LF, automatic abort off with the start value after the sweep, hold and delay 0; ranges auto and the high-speed
ADC are filled in per channel by ``setup_of``)."""

SETUP_MNEMONICS = frozenset({"FMT", "AAD", "AIT", "CN", "DV", "MM", "CMM", "RI", "WT", "WV", "WM", "XE"})


def _num(text: str) -> float:
    return float(text)


def setup_of(commands: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    """What the instrument holds when the sweep fires, as flat ``field -> value``, and the other commands in order.

    Fields: ``format``, ``adc.<ch>``, ``ait``, ``enabled``, ``bias.<ch>.v|icomp``, ``measure.mode``,
    ``measure.channels``, ``measure.order``, ``cmm.<ch>``, ``range.<ch>``, ``timing.hold_s|delay_s``,
    ``sweep.<field>``, ``abort``, ``triggers``. Channels in ``adc``/``range`` default to the initial settings
    (high-speed ADC 0, auto range 0) for every measured channel."""
    state: dict[str, Any] = dict(INITIAL)
    others: list[str] = []
    for command in commands:
        mnemonic, _, rest = command.partition(" ")
        args = rest.split(",") if rest else []
        if mnemonic == "*RST":
            state = dict(INITIAL)
            others.append(mnemonic)
        elif mnemonic not in SETUP_MNEMONICS:
            others.append(mnemonic)
        elif mnemonic == "FMT":
            state["format"] = (int(args[0]), int(args[1]) if len(args) > 1 else 0)
            others.append(mnemonic)  # also counted in the flow (the lab sends it twice)
        elif mnemonic == "AAD":
            state[f"adc.{int(args[0])}"] = int(args[1])
            others.append(mnemonic)
        elif mnemonic == "AIT":
            state["ait"] = tuple(_num(a) for a in args)
        elif mnemonic == "CN":
            state["enabled"] = frozenset(int(a) for a in args)
        elif mnemonic == "DV":
            ch = int(args[0])
            state[f"bias.{ch}.range"] = int(args[1])
            state[f"bias.{ch}.v"] = _num(args[2])
            state[f"bias.{ch}.icomp"] = _num(args[3])
        elif mnemonic == "MM":
            state["measure.mode"] = int(args[0])
            state["measure.order"] = tuple(int(a) for a in args[1:])
            state["measure.channels"] = frozenset(state["measure.order"])
        elif mnemonic == "CMM":
            state[f"cmm.{int(args[0])}"] = int(args[1])
        elif mnemonic == "RI":
            state[f"range.{int(args[0])}"] = int(args[1])
            others.append(mnemonic)
        elif mnemonic == "WT":
            state["timing.hold_s"], state["timing.delay_s"] = _num(args[0]), _num(args[1])
        elif mnemonic == "WV":
            for key, value in zip(("channel", "mode", "range", "start", "stop", "points", "icomp"), args,
                                  strict=True):
                state[f"sweep.{key}"] = int(value) if key in ("channel", "mode", "range", "points") else _num(value)
        elif mnemonic == "WM":
            state["abort"] = (int(args[0]), int(args[1]) if len(args) > 1 else 1)
            others.append(mnemonic)
        elif mnemonic == "XE":
            state["triggers"] += 1
    for ch in state.get("measure.order", ()):
        state.setdefault(f"adc.{ch}", 0)
        state.setdefault(f"range.{ch}", 0)
    return state, others


def kernel_preview(world: World) -> list[str]:
    """The ``mosfet.idvg`` FLEX preview of ``LAB_IDVG_REQUEST`` (planning only; no instrument I/O)."""
    world.use_scenario("lab_nmos_2025")
    executor = world.executor()
    try:
        record = executor.plan(PlanRequest.model_validate(LAB_IDVG_REQUEST))
    finally:
        executor.close()
    assert record.kind == "smu_staircase" and record.tier == "needs_confirmation"
    return list(record.flex_preview)


@pytest.fixture
def setups(world: World) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    lab, lab_others = setup_of(load_sequence("lwp_test_idvg").writes())
    ours, our_others = setup_of(kernel_preview(world))
    return lab, ours, lab_others, our_others


def test_the_preview_matches_the_lab_setup_except_the_documented_fields(setups: tuple) -> None:
    lab, ours, _, _ = setups
    assert set(lab) == set(ours)  # the same fields are programmed
    differing = {key for key in lab if lab[key] != ours[key]}
    assert differing == set(SETUP_DIFFERENCES)
    for key, difference in SETUP_DIFFERENCES.items():
        assert (lab[key], ours[key]) == (difference.lab, difference.ours), key
        assert len(difference.why) > 40, key


def test_the_measurement_itself_is_the_lab_one(setups: tuple) -> None:
    """The fields that define the measurement agree exactly (so the documented list is all that differs)."""
    lab, ours, _, _ = setups
    same = {key: lab[key] for key in lab if key not in SETUP_DIFFERENCES}
    assert same == {key: ours[key] for key in same}
    assert same["enabled"] == frozenset({3, 4, 5}) and same["measure.channels"] == frozenset({3, 4})
    assert same["measure.mode"] == 2 and same["cmm.3"] == same["cmm.4"] == 1
    assert same["bias.4.v"] == REAL_VD and same["bias.5.v"] == 0.0 and same["bias.4.range"] == 0
    assert (same["sweep.channel"], same["sweep.mode"], same["sweep.start"], same["sweep.stop"],
            same["sweep.points"]) == (3, 1, -2.0, 2.0, 61)
    assert same["ait"] == (0, 2, 1) and same["adc.3"] == same["adc.4"] == 0
    assert same["timing.hold_s"] == 0.0 and same["triggers"] == 1
    assert set(same) | set(SETUP_DIFFERENCES) == set(lab)


def test_every_command_outside_the_setup_is_documented(setups: tuple) -> None:
    _, _, lab_others, our_others = setups
    assert lab_others == ["FMT", "ERSSP", "ERSSP", "ERSSP", "ERSSP", "*RST", "FMT", "RI", "RI", "DZ", "CL"]
    assert our_others == ["FMT", "AAD", "AAD", "WM"]
    documented = set(FLOW_DIFFERENCES) | {"DZ", "CL"}  # DZ/CL: part of "cleanup"
    assert set(lab_others) | set(our_others) <= documented
    lab_queries = [s.mnemonic for s in load_sequence("lwp_test_idvg").steps if s.is_query]
    assert set(lab_queries) <= set(FLOW_DIFFERENCES)
    for mnemonic, why in FLOW_DIFFERENCES.items():
        assert len(why) > 30, mnemonic


def test_the_lab_compliances_are_outside_what_the_kernel_would_run_unasked(world: World) -> None:
    """The 100 mA / 10 mA lab compliances: the gate's 10 mA is outside the recipe range (blocked), the drain's
    100 mA too (recipe range 10 mA), so an agent cannot reproduce the pitfall through ``mosfet.idvg``."""
    world.use_scenario("lab_nmos_2025")
    executor = world.executor()
    try:
        for name, value in (("icomp_gate", 0.01), ("icomp_drain", 0.1)):
            request = {**LAB_IDVG_REQUEST, "params": {**LAB_IDVG_REQUEST["params"], name: value}}
            record = executor.plan(PlanRequest.model_validate(request))
            assert record.tier == "blocked", name
            assert any(f.rule_id == "R-PARAM-01" and f.severity == "block" for f in record.rules.findings), name
    finally:
        executor.close()


def test_the_lab_delay_is_a_recipe_parameter(world: World) -> None:
    """WP7.2 (WP6.2 handoff): ``mosfet.idvg`` takes ``hold_s``/``delay_s``; ``delay_s: 0.01`` removes the
    ``timing.delay_s`` difference and changes nothing else of the setup."""
    world.use_scenario("lab_nmos_2025")
    executor = world.executor()
    try:
        request = {**LAB_IDVG_REQUEST, "params": {**LAB_IDVG_REQUEST["params"], "delay_s": 0.01}}
        record = executor.plan(PlanRequest.model_validate(request))
    finally:
        executor.close()
    assert record.tier == "needs_confirmation" and "WT 0,0.01" in record.flex_preview
    lab, _ = setup_of(load_sequence("lwp_test_idvg").writes())
    ours, _ = setup_of(record.flex_preview)
    assert {key for key in lab if lab[key] != ours[key]} == set(SETUP_DIFFERENCES) - {"timing.delay_s"}
