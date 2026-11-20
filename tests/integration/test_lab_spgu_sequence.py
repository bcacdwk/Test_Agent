"""The lab's SPGU FLEX sequence vs the kernel's FLEX preview of the same output (blueprint v2 10.5 row 9.1 AC "lwp
``test_SPGU`` config B reproduced as a FLEX preview"; fixture ``tests/fixtures/lab/lwp_test_spgu.txt`` from WP6.2).

The lab sequence is ``lwp/matlab_B1500/test_SPGU.m`` configuration B through ``lib/SPGU_pulse.m`` (read from the code):
SPGU 101 and 102, three-level pulses 0 -> +3 V (delay 0, 2 us) and 0 -> -3 V (delay 3 us, 2 us), transitions 100 ns,
period 10 us, 2 pulses, load 1 MOhm. The kernel's sequence is ``CN`` (the guarded enable) plus
``SpguOps.spgu_preview(program)`` of the ``SpguPulseProgram`` that states the same output. Both are reduced by a small
interpreter to what the SPGU holds when ``SRP`` fires (unset fields at their initial settings, PG p179 (2-91) Table
2-12); the two setups must be identical (numbers compared as values: MATLAB writes ``1e-05`` where the builders write
``1E-05``). Commands outside the setup are listed in ``FLOW_DIFFERENCES`` with the reason; the visa-loop test
``tests/visa_loop/test_spgu_visa.py`` runs the kernel's sequence on the wire and checks the cleanup."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.ops.spgu import SpguOps
from b1500_test_agent.models.spgu import SpguPulseProgram
from tests.unit.lab_fixtures import load_sequence
from tests.unit.test_models_spgu import lwp_config_b

pytestmark = pytest.mark.spgu

INITIAL: dict[str, Any] = {"mode": 0, "period": 1e-6, "run": (0,), "enabled": frozenset(), "applied": frozenset(),
                           "started": 0}
"""Initial SPGU settings (PG p179 (2-91) Table 2-12): PG mode, 1 us period, free run, nothing enabled or applied."""

CHANNEL_INITIAL: dict[str, Any] = {"ser": 50.0, "spm": 1, "odsw": (0,), "stgp": 0,
                                   "spt.1": (0.0, 1e-7, 2e-8, 2e-8), "spt.2": (0.0, 1e-7, 2e-8, 2e-8),
                                   "spv.1": (-0.5, 0.5), "spv.2": (-0.5, 0.5)}
"""Initial channel settings (Table 2-12): SER 50 Ohm, two-level from source 1, pulse switch disabled, trigger off,
delay 0, width 100 ns, transitions 20 ns, base -0.5 V, peak 0.5 V."""

SETUP_MNEMONICS = frozenset({"SIM", "SPRM", "SPPER", "CN", "SER", "SPM", "SPT", "SPV", "ODSW", "STGP", "SPUPD", "SRP"})

FLOW_DIFFERENCES: dict[str, str] = {
    "ERMOD": ("lab only (SPGU_pulse.m:23): the 16440A control mode; selector routes are the switch work package's "
              "guarded route steps (ERMOD 1, ERSSP per declared port, verified with ERSSP?, rest after the run; "
              "WP9.2/9.3), not part of the SPGU driver"),
    "ERSSP": ("lab only (SPGU_pulse.m:26-29, 106-109): all four selector ports to PGU before and to SMU after, without "
              "reading them back; the kernel routes only the declared ports a plan names (R-ROUTE-01) and returns "
              "them to rest in the cleanup"),
    "ODSW": ("kernel only: the pulse switch is written for every channel (disabled here, the initial setting the lab "
             "relies on), because the kernel never sends *RST and sets every parameter it relies on"),
    "STGP": "kernel only: the trigger output is written for every channel (off), for the same reason as ODSW",
    "CN": ("both, at different places: the lab enables 101/102 after SPPER (SPGU_pulse.m:48-49); the kernel's guarded "
           "enable comes first (the channels output 0 V until SPUPD either way, PG p508 (4-190) SIM)"),
    "*IDN?": ("lab: identity once at connect; the kernel reads *IDN?, UNT?, ERRX?, *STB?, LOP? and *LRN? 31 in its "
              "pre-execute snapshot (the inventory also tells the cleanup that an SPGU is installed)"),
    "SPST?": ("both poll until 0: the lab every 0.1 s with a period x count + 5 s deadline (SPGU_pulse.m:95-98); the "
              "kernel's wait_pulses_stopped polls with host waits, checks the abort file at least once a second and "
              "raises SpguStillActive at its deadline; the cleanup reads it again (step 2 and the verification)"),
    "ERRX?": ("lab: once after the train, failing unless the answer starts with '+0,' (SPGU_pulse.m:102); the kernel "
              "drains at the transaction start, before the output starts and in the cleanup, and accepts '0,' and "
              "'+0,'"),
    "SPP": ("lab: unconditionally in the script's finally block (test_SPGU.m:121); the kernel's cleanup step 2 sends "
            "it when SPST? reads 1 (and once more on the retry), then DZ, CL, ERRX? and the verification SPST? 0 + "
            "LOP? (blueprint v2 2.6)"),
    "cleanup": ("lab: SPP only, no CL (test_SPGU.m:122 fails on an undefined variable, so the SPGU output switches "
                "stay on: the blueprint v2 1.1 pitfall); kernel: SPST?/SPP, DZ, CL, ERRX? drain, verify, device clear "
                "and one retry, else the fault latch"),
}
"""Commands outside the setup where the flows differ (by mnemonic; ``cleanup`` = the end of the sequence)."""


def _nums(args: Iterable[str]) -> tuple[float, ...]:
    return tuple(float(a) for a in args)


def setup_of(commands: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    """What the SPGU holds when ``SRP`` fires, as flat ``field -> value``, and the other commands in order."""
    state: dict[str, Any] = dict(INITIAL)
    others: list[str] = []
    for command in commands:
        mnemonic, _, rest = command.partition(" ")
        args = [a.strip() for a in rest.split(",")] if rest else []
        if mnemonic not in SETUP_MNEMONICS:
            others.append(mnemonic)
            continue
        if mnemonic in ("CN", "SPUPD", "SER", "SPM", "SPT", "SPV", "ODSW", "STGP"):
            channels = [int(a) for a in args] if mnemonic in ("CN", "SPUPD") else [int(args[0])]
            for ch in channels:
                for key, value in CHANNEL_INITIAL.items():
                    state.setdefault(f"{ch}.{key}", value)
        if mnemonic == "CN":
            others.append(mnemonic)
            state["enabled"] = state["enabled"] | frozenset(int(a) for a in args)
        elif mnemonic == "SIM":
            state["mode"] = int(args[0])
        elif mnemonic == "SPRM":
            state["run"] = (int(args[0]), *_nums(args[1:]))
        elif mnemonic == "SPPER":
            state["period"] = float(args[0])
        elif mnemonic == "SER":
            state[f"{int(args[0])}.ser"] = float(args[1])
        elif mnemonic == "SPM":
            state[f"{int(args[0])}.spm"] = int(args[1])
        elif mnemonic == "SPT":
            delay, width, lead, *trail = _nums(args[2:])
            state[f"{int(args[0])}.spt.{int(args[1])}"] = (delay, width, lead, trail[0] if trail else lead)
        elif mnemonic == "SPV":
            base, *peak = _nums(args[2:])
            state[f"{int(args[0])}.spv.{int(args[1])}"] = (base, peak[0] if peak else base)
        elif mnemonic == "ODSW":
            state[f"{int(args[0])}.odsw"] = (int(args[1]), *_nums(args[2:])) if int(args[1]) else (0,)
        elif mnemonic == "STGP":
            state[f"{int(args[0])}.stgp"] = int(args[1])
        elif mnemonic == "SPUPD":
            state["applied"] = state["applied"] | frozenset(int(a) for a in args)
        elif mnemonic == "SRP":
            state["started"] += 1
    return state, others


def kernel_sequence(program: SpguPulseProgram) -> list[str]:
    """What a kernel transaction writes for ``program``: the guarded ``CN``, then the preview."""
    return [flex.cn(sorted(program.channels)), *SpguOps.spgu_preview(program)]


def test_the_lab_sequence_is_configuration_b() -> None:
    lab = load_sequence("lwp_test_spgu")
    assert lab.kind == "lwp_sequence" and "configuration B" in lab.source
    assert "2 cycles" in lab.configuration and "load 1 MOhm" in lab.configuration


def test_the_preview_reproduces_the_lab_setup_exactly() -> None:
    lab, _ = setup_of(load_sequence("lwp_test_spgu").writes())
    ours, _ = setup_of(kernel_sequence(lwp_config_b()))
    assert ours == lab
    assert lab["mode"] == 0 and lab["run"] == (1, 2.0) and lab["period"] == 1e-5 and lab["started"] == 1
    assert lab["enabled"] == lab["applied"] == frozenset({101, 102})
    for ch in (101, 102):
        assert lab[f"{ch}.ser"] == 1e6 and lab[f"{ch}.spm"] == 3
        assert lab[f"{ch}.spt.1"] == (0.0, 2e-6, 1e-7, 1e-7) and lab[f"{ch}.spv.1"] == (0.0, 3.0)
        assert lab[f"{ch}.spt.2"] == (3e-6, 2e-6, 1e-7, 1e-7) and lab[f"{ch}.spv.2"] == (0.0, -3.0)


def test_every_command_outside_the_setup_is_documented() -> None:
    lab = load_sequence("lwp_test_spgu")
    _, lab_others = setup_of(lab.writes())
    _, our_others = setup_of(kernel_sequence(lwp_config_b()))
    assert lab_others == ["ERMOD", "ERSSP", "ERSSP", "ERSSP", "ERSSP", "CN", "ERSSP", "ERSSP", "ERSSP", "ERSSP", "SPP"]
    assert our_others == ["CN"]
    kernel_only = {"ODSW", "STGP"} - {c.split(" ")[0] for c in lab.writes()}
    assert kernel_only == {"ODSW", "STGP"}
    documented = set(FLOW_DIFFERENCES)
    assert set(lab_others) | set(our_others) | kernel_only <= documented
    assert {s.mnemonic for s in lab.steps if s.is_query} <= documented
    for mnemonic, why in FLOW_DIFFERENCES.items():
        assert len(why) > 40, mnemonic


def test_the_kernel_guards_what_the_lab_left_open() -> None:
    """The lab's configuration B is inside the module spec, never free-running, and its open-load level at SER
    1 MOhm is 3.00015 V; the same set level at the initial 50 Ohm would double (what the guard checks)."""
    from b1500_test_agent.driver.modules import SPGU_SPEC

    program = lwp_config_b()
    assert SPGU_SPEC.program_problems(program) == []
    train = program.guard_train(101)
    assert train.count == 2 and SPGU_SPEC.open_load_v(train.max_abs_set_v, train.load_ohm) == 3.0 * 1000050 / 1e6
    assert SPGU_SPEC.open_load_v(train.max_abs_set_v, None) == 6.0
