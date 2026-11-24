"""The lab's Id(t) sampling FLEX sequence vs the ``mosfet.id_t_sampling`` preview on the lab pin map (blueprint v2
10.3 row 7.4 AC "lwp IVt sequence reproduced"; 1.1 IVt sampling facts).

The lab sequence is ``tests/fixtures/lab/lwp_test_ivt_sampling.txt`` (lwp ``test_IVt_sampling.m`` +
``lib/IVt_sampling.m``, read from the code, WP6.2). The kernel's sequence is the FLEX preview of
``mosfet.id_t_sampling`` with its defaults (the lab's gate 0 -> 3 V step, Vd 5 V, ``MT 0.01,0.004,10001,0.1``, 1 PLC)
on pin map ``mosfet-3t-lab`` (gate SMU3, drain SMU4, source SMU5). Both are reduced by a small FLEX interpreter to
what the instrument holds when ``XE`` fires (``*RST`` returns to the initial settings, PG p180 (2-92) Table 2-13:
``ML 1``, ``MT`` 2 ms / 1000 points, ``MSC`` abort off with the bias after the measurement, ``TSC 0``, no sampling
sources); the two setups agree on every field except those in ``SETUP_DIFFERENCES``, which differ exactly as
listed, and every command outside the setup is listed in ``FLOW_DIFFERENCES``. Each entry says why the kernel's
choice is deliberate. Summary for agents: knowledge file ``02-b1500-instrument.md`` section "Lab scripts vs the
kernel".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from b1500_test_agent.models.plan import PlanRequest
from tests.integration.helpers import World
from tests.unit.lab_fixtures import load_sequence

pytestmark = pytest.mark.smu

LAB_IVT_REQUEST: dict[str, Any] = {
    "recipe_id": "mosfet.id_t_sampling", "pin_map": "mosfet-3t-lab", "dut_profile": "nmos-generic", "params": {},
}
"""``test_IVt_sampling.m``'s measurement as a ``mosfet.id_t_sampling`` request: the recipe defaults are the lab's."""


@dataclass(frozen=True)
class Difference:
    lab: Any
    ours: Any
    why: str


SETUP_DIFFERENCES: dict[str, Difference] = {
    "format": Difference((21, 0), (1, 1), (
        "FMT 21 is the 13-digit 4155/4156 format with a 3-digit status number per value (PG p437 (4-119)), which the "
        "lab parser drops (IVt_sampling.m:75 keeps only the numbers), so a compliance or an aborted sample looks "
        "like a reading; FMT 1 keeps a status letter per element, and mode 1 adds the sampling index to every "
        "sample, so skipped grid points (measurement longer than the interval, PG p49 (1-29)) are visible")),
    "bias.4.icomp": Difference(0.1, 0.001, (
        "the 100 mA pitfall (blueprint v2 1.1): the lab's drain compliance is 100 mA for a sub-uA to uA TFT; the "
        "recipe default is 1 mA (range up to 10 mA), so a drain short stops at 1 mA")),
    "bias.5.icomp": Difference(0.1, 0.001001, (
        "the grounded source SMU gets the sum of the sourcing roles' compliances (it returns at most their "
        "currents) instead of another 100 mA")),
    "mv.3.icomp": Difference(0.01, 1e-06, (
        "the lab's stepped gate runs at 10 mA compliance; the recipe default is 1 uA (range up to 1 mA), so a gate "
        "oxide breakdown during the stress is stopped at 1 uA (and aborts the sampling)")),
    "abort": Difference((1, 2), (2, 2), (
        "the lab leaves the automatic abort off (initial MSC 1); the kernel always sends MSC 2,2: compliance on "
        "any channel, overflow or oscillation stops the sampling and the sources go to their base value (PG p473 "
        "(4-155)); the post value (bias after a normal end) is the lab's")),
}
"""Setup fields where the kernel deliberately differs from ``test_IVt_sampling.m`` (lab value, kernel value, why)."""

FLOW_DIFFERENCES: dict[str, str] = {
    "*RST": ("lab only (IVt_sampling.m:33): it resets the MFCMU corrections, the SPGU and the switch paths and hides "
             "the instrument's prior state (PG p179-180 (2-91)); the kernel never sends it outside kind system "
             "(lint), sets every sampling parameter it relies on and clears stale sampling sources with MCC"),
    "MCC": ("kernel only: clears MV/MI/MSP sources an earlier program left (the lab relies on *RST for that)"),
    "TSR": ("kernel only: clears the timer right before the trigger; the lab's time stamps run from its *RST, the "
            "kernel's from the TSR, and t_s is taken from the first sample's stamp either way"),
    "AAD": ("kernel only: the ADC type is written for the measured channel (high-speed, the initial setting the "
            "lab relies on after its *RST) because the kernel never resets"),
    "MSC": "kernel only: see setup field abort",
    "FMT": "both send it once; see setup field format",
    "RI": ("lab only (IVt_sampling.m:60): RI 4,0 is auto ranging, the initial setting, which the kernel keeps (CL "
           "at every cleanup resets the ranges)"),
    "*OPC?": ("lab only (IVt_sampling.m:68): the kernel's data read after XE blocks until the data are complete, "
              "with a timeout of 2 x the block estimate + 10 s"),
    "ERRX?": ("lab: once after the sampling, failing unless the answer starts with '+0,' (IVt_sampling.m:70); the "
              "kernel drains before XE (setup errors abort before triggering), after CN, at the transaction start "
              "and in the cleanup, and accepts both '0,' (PG p432 (4-114)) and the lab firmware's '+0,'"),
    "*IDN?": ("lab: identity once at connect; the kernel reads *IDN?, UNT?, ERRX?, *STB?, LOP? and *LRN? 31 before "
              "each run (pre-execute rules)"),
    "LOP?": "kernel only: the hardware positive control after CN and the cleanup's verification",
    "cleanup": ("lab: DZ, CL in the script's finally block, unverified; kernel: AB if a measurement is pending, DZ, "
                "CL, ERRX? drain, LOP? verify, device clear and one retry, else the fault latch"),
}
"""Commands outside the setup where the flows differ (by mnemonic; ``cleanup`` = the end of the sequence)."""

INITIAL: dict[str, Any] = {"format": (1, 0), "tsc": 0, "ml": 1, "mt": (0.0, 0.002, 1000, 0.0), "abort": (1, 2),
                           "triggers": 0}
"""Initial settings (PG p180 (2-92) Table 2-13): ASCII with header, no time stamps, linear sampling, MT 2 ms /
1000 points, automatic abort off with the bias value after the measurement."""

SETUP_MNEMONICS = frozenset({"FMT", "TSC", "AAD", "AIT", "ML", "MT", "MSC", "CN", "DV", "MV", "MM", "CMM", "RI",
                             "MCC", "XE"})


def _num(text: str) -> float:
    return float(text)


def setup_of(commands: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    """What the instrument holds when the sampling fires, as flat ``field -> value``, and the other commands.

    Fields: ``format``, ``tsc``, ``adc.<ch>``, ``ait``, ``ml``, ``mt``, ``abort``, ``enabled``,
    ``bias.<ch>.range|v|icomp``, ``mv.<ch>.range|base|bias|icomp``, ``measure.mode``, ``measure.channels``,
    ``cmm.<ch>``, ``range.<ch>``, ``triggers``; measured channels default to the high-speed ADC and auto ranging."""
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
            others.append(mnemonic)
        elif mnemonic == "TSC":
            state["tsc"] = int(args[0])
        elif mnemonic == "AAD":
            state[f"adc.{int(args[0])}"] = int(args[1])
            others.append(mnemonic)
        elif mnemonic == "AIT":
            state["ait"] = tuple(_num(a) for a in args)
        elif mnemonic == "ML":
            state["ml"] = int(args[0])
        elif mnemonic == "MT":
            state["mt"] = (_num(args[0]), _num(args[1]), int(args[2]), _num(args[3]) if len(args) > 3 else 0.0)
        elif mnemonic == "MSC":
            state["abort"] = (int(args[0]), int(args[1]) if len(args) > 1 else 2)
            others.append(mnemonic)
        elif mnemonic == "MCC":
            for key in [k for k in state if k.startswith("mv.")]:
                del state[key]
            others.append(mnemonic)
        elif mnemonic == "CN":
            state["enabled"] = frozenset(int(a) for a in args)
        elif mnemonic == "DV":
            ch = int(args[0])
            state[f"bias.{ch}.range"], state[f"bias.{ch}.v"], state[f"bias.{ch}.icomp"] = (
                int(args[1]), _num(args[2]), _num(args[3]))
        elif mnemonic == "MV":
            ch = int(args[0])
            for key, value in zip(("range", "base", "bias", "icomp"), args[1:], strict=True):
                state[f"mv.{ch}.{key}"] = int(value) if key == "range" else _num(value)
        elif mnemonic == "MM":
            state["measure.mode"] = int(args[0])
            state["measure.channels"] = tuple(int(a) for a in args[1:])
        elif mnemonic == "CMM":
            state[f"cmm.{int(args[0])}"] = int(args[1])
        elif mnemonic == "RI":
            state[f"range.{int(args[0])}"] = int(args[1])
            others.append(mnemonic)
        elif mnemonic == "XE":
            state["triggers"] += 1
    for ch in state.get("measure.channels", ()):
        state.setdefault(f"adc.{ch}", 0)
        state.setdefault(f"range.{ch}", 0)
    return state, others


def kernel_preview(world: World) -> list[str]:
    """The ``mosfet.id_t_sampling`` FLEX preview of ``LAB_IVT_REQUEST`` (planning only; no instrument I/O)."""
    world.use_scenario("lab_nmos_2025")
    executor = world.executor()
    try:
        record = executor.plan(PlanRequest.model_validate(LAB_IVT_REQUEST))
    finally:
        executor.close()
    assert record.kind == "smu_sampling" and record.tier == "needs_confirmation"  # unverified lab pin map, 5 V drain
    assert record.mode == "sync"
    return list(record.flex_preview)


@pytest.fixture
def setups(world: World) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    lab, lab_others = setup_of(load_sequence("lwp_test_ivt_sampling").writes())
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
    """The fields that define the measurement agree exactly: one MM 10 trigger on the drain with time stamps, the
    gate step 0 -> 3 V after 0.1 s, the first sample 10 ms later, 10001 samples every 4 ms at 1 PLC, Vd 5 V."""
    lab, ours, _, _ = setups
    same = {key: lab[key] for key in lab if key not in SETUP_DIFFERENCES}
    assert same == {key: ours[key] for key in same}
    assert same["enabled"] == frozenset({3, 4, 5}) and same["measure.channels"] == (4,)
    assert same["measure.mode"] == 10 and same["cmm.4"] == 1 and same["tsc"] == 1 and same["ml"] == 1
    assert same["mt"] == (0.01, 0.004, 10001, 0.1)
    assert (same["mv.3.range"], same["mv.3.base"], same["mv.3.bias"]) == (0, 0.0, 3.0)
    assert (same["bias.4.v"], same["bias.5.v"]) == (5.0, 0.0)
    assert same["ait"] == (0, 2, 1) and same["adc.4"] == 0 and same["range.4"] == 0 and same["triggers"] == 1
    assert set(same) | set(SETUP_DIFFERENCES) == set(lab)


def test_every_command_outside_the_setup_is_documented(setups: tuple) -> None:
    _, _, lab_others, our_others = setups
    assert lab_others == ["*RST", "FMT", "RI", "DZ", "CL"]
    assert our_others == ["FMT", "AAD", "MCC", "MSC", "TSR"]
    documented = set(FLOW_DIFFERENCES) | {"DZ", "CL"}  # DZ/CL: part of "cleanup"
    assert set(lab_others) | set(our_others) <= documented
    lab_queries = [s.mnemonic for s in load_sequence("lwp_test_ivt_sampling").steps if s.is_query]
    assert set(lab_queries) <= set(FLOW_DIFFERENCES)
    for mnemonic, why in FLOW_DIFFERENCES.items():
        assert len(why) > 30, mnemonic


def test_the_lab_compliances_are_outside_what_the_kernel_would_run_unasked(world: World) -> None:
    """The lab's 100 mA drain and 10 mA gate compliances exceed the recipe ranges (10 mA, 1 mA): blocked."""
    world.use_scenario("lab_nmos_2025")
    executor = world.executor()
    try:
        for name, value in (("icomp_gate", 0.01), ("icomp_drain", 0.1)):
            request = {**LAB_IVT_REQUEST, "params": {name: value}}
            record = executor.plan(PlanRequest.model_validate(request))
            assert record.tier == "blocked", name
            assert any(f.rule_id == "R-PARAM-01" and f.severity == "block" for f in record.rules.findings), name
    finally:
        executor.close()
