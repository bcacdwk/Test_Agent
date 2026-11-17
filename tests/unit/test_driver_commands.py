"""FLEX builders (driver/commands.py): exact syntax per the Programming Guide, domain checks, no combined commands,
and page citations that agree with the generated driver map."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.driver import commands

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "references" / "driver-map" / "flex-driver-map.yaml"
COMMANDS_SRC = Path(commands.__file__)
_PDF = re.compile(r"PDF (\d+)(?:-(\d+))?")


def _builders() -> list[str]:
    return [name for name, obj in vars(commands).items() if inspect.isfunction(obj) and not name.startswith("_")]


def _constant_docstrings() -> dict[str, str]:
    """Attribute docstrings (the string literal right after ``NAME = ...``) of commands.py."""
    tree = ast.parse(COMMANDS_SRC.read_text(encoding="utf-8"))
    docs: dict[str, str] = {}
    for node, following in zip(tree.body, tree.body[1:], strict=False):
        if (
            isinstance(node, ast.Assign | ast.AnnAssign)
            and isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        ):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name):
                docs[target.id] = following.value.value
    return docs


def _cited_pages(text: str) -> set[int]:
    pages: set[int] = set()
    for first, last in _PDF.findall(text):
        pages.update(range(int(first), int(last or first) + 1))
    return pages


# -- exact syntax -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("built", "expected"),
    [
        (commands.cn([1, 3]), "CN 1,3"),
        (commands.cl(), "CL"),
        (commands.cl([1, 2, 3, 5]), "CL 1,2,3,5"),  # PDF 378 example
        (commands.dz(), "DZ"),
        (commands.dz([101, 3]), "DZ 101,3"),
        (commands.fmt(), "FMT 1,1"),
        (commands.fmt(5, 0), "FMT 5,0"),
        (commands.mm(2, [1, 3]), "MM 2,1,3"),  # PDF 471 example
        (commands.mm(1, [1]), "MM 1,1"),
        (commands.cmm(1, 1), "CMM 1,1"),  # PDF 380 example
        (commands.aad(1, 0), "AAD 1,0"),  # PDF 351 example
        (commands.ait(1, 2, 3), "AIT 1,2,3"),
        (commands.ait(0, 3, 0.001), "AIT 0,3,0.001"),
        (commands.ri(2, -20), "RI 2,-20"),  # PDF 501 example
        (commands.rv(2, -15), "RV 2,-15"),  # PDF 504 example
        (commands.rv(1, 12), "RV 1,12"),  # PDF 504 example
        (commands.wt(5, 0.1, 0.1, 0.1, 0.1), "WT 5,0.1,0.1,0.1,0.1"),  # PDF 565 example
        (commands.wt(5, 0.2), "WT 5,0.2"),  # PDF 565 example
        (commands.wt(0, 0), "WT 0,0"),
        (commands.wt(0.5, 0.01, 0, 0.005), "WT 0.5,0.01,0,0.005"),
        (commands.wm(2, 1), "WM 2,1"),  # PDF 553 example "WM 2,2" form
        (commands.dv(2, 12, 10, 1e-3), "DV 2,12,10,0.001"),
        (commands.dv(1, 0, 20, 1e-6), "DV 1,0,20,1E-06"),
        (commands.wv(2, 1, 0, 0, 20, 101, 0.01), "WV 2,1,0,0,20,101,0.01"),  # PDF 570 example + Icomp
        (commands.wv(1, 2, 12, 1e-6, 10, 100, 0.1), "WV 1,2,12,1E-06,10,100,0.1"),  # PDF 570 example w/o Pcomp
        (commands.wv(1, 3, 0, -1.0, 3.0, 101, 1e-6), "WV 1,3,0,-1,3,101,1E-06"),
    ],
)
def test_builder_output(built: str, expected: str) -> None:
    assert built == expected


def test_constants_are_single_commands() -> None:
    assert (commands.XE, commands.AB, commands.RST) == ("XE", "AB", "*RST")
    assert (commands.IDN_Q, commands.UNT_Q, commands.ERRX_Q, commands.STB_Q) == ("*IDN?", "UNT?", "ERRX?", "*STB?")
    assert (commands.OPC_Q, commands.LOP_Q, commands.TST_Q, commands.CAL_Q) == ("*OPC?", "LOP?", "*TST?", "*CAL?")


def test_no_builder_combines_commands() -> None:
    """``AB`` and ``*RST`` are bare constants, and no builder output contains a command separator."""
    samples = [
        commands.cn([1, 2, 3]),
        commands.cl([1]),
        commands.dz(),
        commands.fmt(1, 1),
        commands.mm(2, [1, 2]),
        commands.cmm(1, 0),
        commands.aad(1, 1),
        commands.ait(0, 0, 1),
        commands.ri(1, 0),
        commands.rv(1, 0),
        commands.wt(1, 1, 0.5, 0.5, 1),
        commands.wm(1, 1),
        commands.dv(1, 0, 1, 1e-3),
        commands.wv(1, 1, 0, 0, 1, 11, 1e-3),
    ]
    constants = [value for name, value in vars(commands).items() if name.isupper() and isinstance(value, str)]
    for text in samples + constants:
        assert ";" not in text and "\n" not in text, text
    assert commands.AB.split() == ["AB"] and commands.RST.split() == ["*RST"]


def test_numbers_are_round_trip_exact() -> None:
    value = 1.234567890123e-7
    built = commands.dv(1, 0, value, 1e-3)
    assert float(built.split(",")[2]) == value
    assert commands.dv(1, 0, -0.0, 1e-3) == "DV 1,0,0,0.001"


# -- domain checks ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: commands.cn([]),  # a bare CN would enable every module
        lambda: commands.cn(list(range(1, 11)) + [101, 201, 301, 401, 501, 601]),  # 16 > 15
        lambda: commands.cn([1, 1]),
        lambda: commands.cn([1, 101]),  # the same channel (PG Table 4-1)
        lambda: commands.cn([11]),
        lambda: commands.cl([0]),
        lambda: commands.dz([103]),
        lambda: commands.fmt(2, 0),  # only FMT 1 and 5
        lambda: commands.fmt(1, 11),
        lambda: commands.mm(3, [1]),  # only MM 1 and 2
        lambda: commands.mm(2, []),
        lambda: commands.mm(2, list(range(1, 11)) + [101]),  # 11 > 10
        lambda: commands.cmm(1, 5),
        lambda: commands.aad(1, 3),
        lambda: commands.ait(1, 3, 0.001),  # high-resolution ADC has no time mode
        lambda: commands.ait(2, 0, 1),  # pulsed ADC has no auto mode
        lambda: commands.ait(0, 0, 1024),
        lambda: commands.ait(1, 0, 128),
        lambda: commands.ait(0, 2, 101),
        lambda: commands.ait(0, 0, 1.5),
        lambda: commands.ait(0, 3, 1e-6),  # below 2 us
        lambda: commands.ait(0, 3, 0.021),
        lambda: commands.ri(1, 7),
        lambda: commands.ri(1, 24),
        lambda: commands.ri(1, -26),  # expander-only code
        lambda: commands.rv(1, 3),
        lambda: commands.rv(1, 103),  # expander-only code
        lambda: commands.wt(655.36, 0),
        lambda: commands.wt(0, 65.536),
        lambda: commands.wt(0, 0, 1.0001),
        lambda: commands.wt(0, 0.1, 0, 0.2),  # Tdelay > delay
        lambda: commands.wt(0, 0, 0, 0, 65.536),
        lambda: commands.wt(-1, 0),
        lambda: commands.wm(0, 1),
        lambda: commands.wm(1, 3),
        lambda: commands.dv(1, 0, 1.0, 0.0),  # 0 A Icomp is not allowed
        lambda: commands.dv(1, -20, 1.0, 1e-3),  # output ranging has no fixed codes
        lambda: commands.dv(1, 0, float("nan"), 1e-3),
        lambda: commands.dv(1, 0, float("inf"), 1e-3),
        lambda: commands.wv(1, 5, 0, 0, 1, 11, 1e-3),
        lambda: commands.wv(1, 1, 0, 0, 1, 0, 1e-3),
        lambda: commands.wv(1, 1, 0, 0, 1, 10002, 1e-3),
        lambda: commands.wv(1, 2, 0, 0, 1, 11, 1e-3),  # log sweep through 0
        lambda: commands.wv(1, 4, 0, -1, 1, 11, 1e-3),  # log sweep across polarity
        lambda: commands.wv(1, 1, 0, 0, 1, 11, 0),
    ],
)
def test_builders_reject_values_outside_the_manual_domain(call) -> None:
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize(
    "call",
    [
        lambda: commands.cn([True]),
        lambda: commands.mm(2.0, [1]),
        lambda: commands.wv(1, 1, 0, 0, 1, 11.0, 1e-3),
        lambda: commands.dv(1, 0, True, 1e-3),
    ],
)
def test_builders_reject_wrong_types(call) -> None:
    with pytest.raises(TypeError):
        call()


def test_ait_accepts_table_4_21_bounds() -> None:
    assert commands.ait(0, 0, 1023) == "AIT 0,0,1023"
    assert commands.ait(1, 1, 127) == "AIT 1,1,127"
    assert commands.ait(2, 2, 100) == "AIT 2,2,100"
    assert commands.ait(2, 3, 2e-6) == "AIT 2,3,2E-06"
    assert commands.ait(0, 0, 4.0) == "AIT 0,0,4"


def test_wt_sends_optional_delays_up_to_the_last_non_zero_one() -> None:
    assert commands.wt(0, 0, 0, 0, 0.5) == "WT 0,0,0,0,0.5"
    assert commands.wt(0, 0, 0.2) == "WT 0,0,0.2"


# -- citations ----------------------------------------------------------------------------------------------------


def test_every_builder_and_constant_cites_a_pdf_page() -> None:
    docs = _constant_docstrings()
    for name in _builders():
        assert _cited_pages(getattr(commands, name).__doc__ or ""), name
    for name in ("XE", "AB", "IDN_Q", "UNT_Q", "ERRX_Q", "STB_Q", "OPC_Q", "LOP_Q", "RST", "TST_Q", "CAL_Q"):
        assert _cited_pages(docs.get(name, "")), name


def test_docstring_pages_match_the_driver_map() -> None:
    """Each driver-map command with a builder lists PDF pages, and the builder's docstring cites all of them."""
    doc = yaml.safe_load(MAP.read_text(encoding="utf-8"))
    docs = _constant_docstrings()
    with_builder = [entry for entry in doc["commands"] if "builder" in entry]
    assert {entry["builder"].removeprefix("commands.") for entry in with_builder} == set(_builders()) | {
        "XE", "AB", "IDN_Q", "UNT_Q", "ERRX_Q", "STB_Q", "OPC_Q", "LOP_Q", "RST", "TST_Q", "CAL_Q",
    }  # fmt: skip
    for entry in with_builder:
        name = entry["builder"].removeprefix("commands.")
        obj = getattr(commands, name)
        text = obj.__doc__ if inspect.isfunction(obj) else docs[name]
        assert entry["pdf_pages"], entry["command"]
        missing = set(entry["pdf_pages"]) - _cited_pages(text or "")
        assert not missing, f"{name} docstring does not cite PDF {sorted(missing)} ({entry['command']})"


def test_section_2_3_commands_have_manual_pages_in_the_driver_map() -> None:
    doc = yaml.safe_load(MAP.read_text(encoding="utf-8"))
    by_command = {entry["command"]: entry for entry in doc["commands"]}
    expected = {
        "WV": [568, 569],
        "AIT": [356, 357, 358, 359],
        "RI": [501],
        "RV": [503, 504],
        "WT": [564, 565],
        "CMM": [380],
        "LOP?": [446, 447],
    }
    assert {name: by_command[name]["pdf_pages"] for name in expected} == expected
