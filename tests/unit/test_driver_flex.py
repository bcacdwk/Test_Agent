"""FLEX builders (``driver/flex/``): exact syntax per the Programming Guide, domain checks, no combined commands,
page citations that agree with the generated driver map, and the package layout (one module per family, every
public builder and constant re-exported by ``flex/__init__.py``)."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.flex import cmu as flex_cmu
from b1500_test_agent.driver.flex import core as flex_core
from b1500_test_agent.driver.flex import pulsed as flex_pulsed
from b1500_test_agent.driver.flex import sampling as flex_sampling
from b1500_test_agent.driver.flex import search as flex_search
from b1500_test_agent.driver.flex import smu as flex_smu
from b1500_test_agent.driver.flex import spgu as flex_spgu
from b1500_test_agent.driver.flex import switch as flex_switch

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "references" / "driver-map" / "flex-driver-map.yaml"
FAMILY_MODULES: tuple[ModuleType, ...] = (flex_core, flex_smu, flex_sampling, flex_pulsed, flex_search, flex_cmu,
                                          flex_spgu, flex_switch)
COMMAND_CONSTANTS = ("XE", "AB", "IDN_Q", "UNT_Q", "ERRX_Q", "STB_Q", "OPC_Q", "LOP_Q", "RST", "TST_Q", "CAL_Q",
                     "ERMOD_Q", "SPST_Q", "SRP", "SPP")
"""Constants that are whole commands (each cites its manual page and has a driver-map entry)."""
_PDF = re.compile(r"PDF (\d+)(?:-(\d+))?")


def _own_functions(module: ModuleType) -> list[str]:
    return [name for name, obj in vars(module).items()
            if inspect.isfunction(obj) and not name.startswith("_") and obj.__module__ == module.__name__]


def _builders() -> list[str]:
    return [name for module in FAMILY_MODULES for name in _own_functions(module)]


def _constant_docstrings() -> dict[str, str]:
    """Attribute docstrings (the string literal right after ``NAME = ...``) of every family module."""
    docs: dict[str, str] = {}
    for module in FAMILY_MODULES:
        tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
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
        (flex.cn([1, 3]), "CN 1,3"),
        (flex.cl(), "CL"),
        (flex.cl([1, 2, 3, 5]), "CL 1,2,3,5"),  # PDF 378 example
        (flex.dz(), "DZ"),
        (flex.dz([101, 3]), "DZ 101,3"),
        (flex.fmt(), "FMT 1,1"),
        (flex.fmt(5, 0), "FMT 5,0"),
        (flex.mm(2, [1, 3]), "MM 2,1,3"),  # PDF 471 example
        (flex.mm(1, [1]), "MM 1,1"),
        (flex.cmm(1, 1), "CMM 1,1"),  # PDF 380 example
        (flex.aad(1, 0), "AAD 1,0"),  # PDF 351 example
        (flex.ait(1, 2, 3), "AIT 1,2,3"),
        (flex.ait(0, 3, 0.001), "AIT 0,3,0.001"),
        (flex.ri(2, -20), "RI 2,-20"),  # PDF 501 example
        (flex.rv(2, -15), "RV 2,-15"),  # PDF 504 example
        (flex.rv(1, 12), "RV 1,12"),  # PDF 504 example
        (flex.wt(5, 0.1, 0.1, 0.1, 0.1), "WT 5,0.1,0.1,0.1,0.1"),  # PDF 565 example
        (flex.wt(5, 0.2), "WT 5,0.2"),  # PDF 565 example
        (flex.wt(0, 0), "WT 0,0"),
        (flex.wt(0.5, 0.01, 0, 0.005), "WT 0.5,0.01,0,0.005"),
        (flex.wm(2, 1), "WM 2,1"),  # PDF 553 example "WM 2,2" form
        (flex.dv(2, 12, 10, 1e-3), "DV 2,12,10,0.001"),
        (flex.dv(1, 0, 20, 1e-6), "DV 1,0,20,1E-06"),
        (flex.wv(2, 1, 0, 0, 20, 101, 0.01), "WV 2,1,0,0,20,101,0.01"),  # PDF 570 example + Icomp
        (flex.wv(1, 2, 12, 1e-6, 10, 100, 0.1), "WV 1,2,12,1E-06,10,100,0.1"),  # PDF 570 example w/o Pcomp
        (flex.wv(1, 3, 0, -1.0, 3.0, 101, 1e-6), "WV 1,3,0,-1,3,101,1E-06"),
        (flex.mm(16, [1, 2]), "MM 16,1,2"),  # PDF 227 Table 3-13 "MM 16,base,collector"
        (flex.di(3, 14, 5e-7, 20), "DI 3,14,5E-07,20"),  # PDF 392 example "DI 3,14,5E-7,20,0,0" w/o polarity, vrange
        (flex.di(1, 0, 1e-6, 2), "DI 1,0,1E-06,2"),  # PDF 392 example "DI 1,0,1E-6" + Vcomp (always sent)
        (flex.wi(1, 1, 11, 0, 0.1, 100, 10), "WI 1,1,11,0,0.1,100,10"),  # PDF 552 example w/o Pcomp
        (flex.wi(2, 2, 15, 1e-6, 0.1, 100, 2), "WI 2,2,15,1E-06,0.1,100,2"),  # PDF 552 example + Vcomp
        (flex.wi(1, 4, 0, -1e-3, -1e-9, 61, 5), "WI 1,4,0,-0.001,-1E-09,61,5"),
        (flex.wsi(2, 0, 1e-3, 1e-2, 5), "WSI 2,0,0.001,0.01,5"),  # PDF 561 example w/o Pcomp
        (flex.wsi(1, 16, 0, 4e-5, 1), "WSI 1,16,0,4E-05,1"),  # PDF 561 example "WSI 1,16,0,4E-5" + Vcomp
        (flex.wsv(1, 0, 1, 100, 0.01), "WSV 1,0,1,100,0.01"),  # PDF 563 example w/o Pcomp
        (flex.wsv(2, 12, 0, 10, 1e-3), "WSV 2,12,0,10,0.001"),  # PDF 563 example "WSV 2,12,0,10" + Icomp
        (flex.wnx(2, 3, "V", 12, 0, 3, 1e-3), "WNX 2,3,1,12,0,3,0.001"),  # PDF 559 example w/o Pcomp
        (flex.wnx(3, 4, "I", 0, 1e-3, 1e-2, 3), "WNX 3,4,2,0,0.001,0.01,3"),  # PDF 559 example
        (flex.cm(0), "CM 0"),  # PDF 379 example
        (flex.cm(1), "CM 1"),  # PDF 379 example
        (flex.lrn_q(1), "*LRN? 1"),  # PDF 447 example
        (flex.lrn_q(flex.LRN_SETTINGS), "*LRN? 31"),
        (flex.erssp_q(1), "ERSSP? 1"),  # PDF 434 example
        (flex.erssp_q(0), "ERSSP? 0"),
        (flex.erssp_q(3), "ERSSP? 3"),
        (flex.corrst_q(9, "load"), "CORRST? 9,3"),  # PDF 388 example
        (flex.corrst_q(7, "open"), "CORRST? 7,1"),
        (flex.corrst_q(7, "short"), "CORRST? 7,2"),
        (flex.adj_q(7, flex.ADJ_READ_LAST), "ADJ? 7,0"),
        (flex.adj_q(9, 1), "ADJ? 9,1"),  # PDF 355-356 syntax with the mode written out
    ],
)
def test_builder_output(built: str, expected: str) -> None:
    assert built == expected


def test_constants_are_single_commands() -> None:
    assert (flex.XE, flex.AB, flex.RST) == ("XE", "AB", "*RST")
    assert (flex.IDN_Q, flex.UNT_Q, flex.ERRX_Q, flex.STB_Q) == ("*IDN?", "UNT?", "ERRX?", "*STB?")
    assert (flex.OPC_Q, flex.LOP_Q, flex.TST_Q, flex.CAL_Q) == ("*OPC?", "LOP?", "*TST?", "*CAL?")
    assert (flex.ERMOD_Q, flex.SPST_Q) == ("ERMOD?", "SPST?")


def test_probe_query_tables_follow_the_manual() -> None:
    """ERSSP status 0-3 (PDF 433-434), CORRST modes 1-3 (PDF 388), ADJ? results 0-3 (PDF 356), ERMOD bit 1."""
    assert flex.ERSSP_STATES == {0: "open", 1: "smu", 2: "pgu", 3: "pgu_open"}
    assert flex.CORRECTION_CODES == {"open": 1, "short": 2, "load": 3}
    assert sorted(flex.ADJ_RESULTS) == [0, 1, 2, 3] and "not been performed" in flex.ADJ_RESULTS[3]
    assert (flex.ERMOD_SELECTOR, flex.ERMOD_MAX, flex.ADJ_READ_LAST) == (1, 63, 0)
    assert flex.SPST_STATES == {0, 1}


def test_every_probe_builder_is_a_query() -> None:
    """The read-only probe sends only these: each is one query (header ends with ``?``)."""
    for text in (flex.ERMOD_Q, flex.SPST_Q, flex.erssp_q(2), flex.corrst_q(7, "short"), flex.adj_q(7, 0)):
        assert text.split()[0].endswith("?") and ";" not in text, text


def test_no_builder_combines_commands() -> None:
    """``AB`` and ``*RST`` are bare constants, and no builder output contains a command separator."""
    samples = [
        flex.cn([1, 2, 3]),
        flex.cl([1]),
        flex.dz(),
        flex.fmt(1, 1),
        flex.mm(2, [1, 2]),
        flex.cmm(1, 0),
        flex.aad(1, 1),
        flex.ait(0, 0, 1),
        flex.ri(1, 0),
        flex.rv(1, 0),
        flex.wt(1, 1, 0.5, 0.5, 1),
        flex.wm(1, 1),
        flex.dv(1, 0, 1, 1e-3),
        flex.wv(1, 1, 0, 0, 1, 11, 1e-3),
        flex.di(1, 0, 1e-6, 1),
        flex.wi(1, 2, 0, 1e-9, 1e-3, 61, 2),
        flex.wsv(2, 0, 0, 1, 1e-3),
        flex.wsi(2, 0, 0, 1e-6, 1),
        flex.wnx(2, 2, "V", 0, 0, 1, 1e-3),
    ]
    constants = [value for name, value in vars(flex).items() if name.isupper() and isinstance(value, str)]
    for text in samples + constants:
        assert ";" not in text and "\n" not in text, text
    assert flex.AB.split() == ["AB"] and flex.RST.split() == ["*RST"]


def test_numbers_are_round_trip_exact() -> None:
    value = 1.234567890123e-7
    built = flex.dv(1, 0, value, 1e-3)
    assert float(built.split(",")[2]) == value
    assert flex.dv(1, 0, -0.0, 1e-3) == "DV 1,0,0,0.001"


# -- domain checks ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: flex.cn([]),  # a bare CN would enable every module
        lambda: flex.cn(list(range(1, 11)) + [101, 201, 301, 401, 501, 601]),  # 16 > 15
        lambda: flex.cn([1, 1]),
        lambda: flex.cn([1, 101]),  # the same channel (PG Table 4-1)
        lambda: flex.cn([11]),
        lambda: flex.cl([0]),
        lambda: flex.dz([103]),
        lambda: flex.fmt(2, 0),  # only FMT 1 and 5
        lambda: flex.fmt(1, 11),
        lambda: flex.mm(6, [1]),  # no such measurement mode (PG Table 4-28)
        lambda: flex.mm(3, [1, 2]),  # pulsed spot takes one channel (WP7.3)
        lambda: flex.mm(17, [7, 3]),  # spot C takes one channel
        lambda: flex.mm(21, [7]),  # not a measurement mode
        lambda: flex.mm(2, []),
        lambda: flex.mm(2, list(range(1, 11)) + [101]),  # 11 > 10
        lambda: flex.cmm(1, 5),
        lambda: flex.aad(1, 3),
        lambda: flex.ait(1, 3, 0.001),  # high-resolution ADC has no time mode
        lambda: flex.ait(2, 0, 1),  # pulsed ADC has no auto mode
        lambda: flex.ait(0, 0, 1024),
        lambda: flex.ait(1, 0, 128),
        lambda: flex.ait(0, 2, 101),
        lambda: flex.ait(0, 0, 1.5),
        lambda: flex.ait(0, 3, 1e-6),  # below 2 us
        lambda: flex.ait(0, 3, 0.021),
        lambda: flex.ri(1, 7),
        lambda: flex.ri(1, 24),
        lambda: flex.ri(1, -26),  # expander-only code
        lambda: flex.rv(1, 3),
        lambda: flex.rv(1, 103),  # expander-only code
        lambda: flex.wt(655.36, 0),
        lambda: flex.wt(0, 65.536),
        lambda: flex.wt(0, 0, 1.0001),
        lambda: flex.wt(0, 0.1, 0, 0.2),  # Tdelay > delay
        lambda: flex.wt(0, 0, 0, 0, 65.536),
        lambda: flex.wt(-1, 0),
        lambda: flex.wm(0, 1),
        lambda: flex.wm(1, 3),
        lambda: flex.dv(1, 0, 1.0, 0.0),  # 0 A Icomp is not allowed
        lambda: flex.dv(1, -20, 1.0, 1e-3),  # output ranging has no fixed codes
        lambda: flex.dv(1, 0, float("nan"), 1e-3),
        lambda: flex.dv(1, 0, float("inf"), 1e-3),
        lambda: flex.wv(1, 5, 0, 0, 1, 11, 1e-3),
        lambda: flex.wv(1, 1, 0, 0, 1, 0, 1e-3),
        lambda: flex.wv(1, 1, 0, 0, 1, 10002, 1e-3),
        lambda: flex.wv(1, 2, 0, 0, 1, 11, 1e-3),  # log sweep through 0
        lambda: flex.wv(1, 4, 0, -1, 1, 11, 1e-3),  # log sweep across polarity
        lambda: flex.wv(1, 1, 0, 0, 1, 11, 0),
        lambda: flex.di(1, -14, 1e-6, 2),  # output ranging has no fixed codes
        lambda: flex.di(1, 24, 1e-6, 2),
        lambda: flex.di(1, 0, 1e-6, 0),  # 0 V Vcomp
        lambda: flex.di(1, 0, float("nan"), 2),
        lambda: flex.wi(1, 5, 0, 0, 1e-3, 11, 2),
        lambda: flex.wi(1, 2, 0, 0, 1e-3, 11, 2),  # log sweep through 0 A
        lambda: flex.wi(1, 4, 0, -1e-6, 1e-3, 11, 2),  # log sweep across polarity
        lambda: flex.wi(1, 1, 0, 0, 1e-3, 10002, 2),
        lambda: flex.wi(1, 1, 7, 0, 1e-3, 11, 2),
        lambda: flex.wi(1, 1, 0, 0, 1e-3, 11, 0),
        lambda: flex.wsv(1, 3, 0, 1, 1e-3),  # not a Table 4-4 code
        lambda: flex.wsv(1, 0, 0, 1, 0),
        lambda: flex.wsi(1, -11, 0, 1e-6, 1),
        lambda: flex.wsi(1, 0, 0, 1e-6, 0),
        lambda: flex.wnx(11, 3, "V", 0, 0, 1, 1e-3),  # N 1-10
        lambda: flex.wnx(0, 3, "V", 0, 0, 1, 1e-3),
        lambda: flex.wnx(2, 3, "P", 0, 0, 1, 1e-3),
        lambda: flex.wnx(2, 3, "I", -12, 0, 1e-3, 1),  # output ranging has no fixed codes
        lambda: flex.wnx(2, 3, "V", 7, 0, 1, 1e-3),
        lambda: flex.wnx(2, 3, "V", 0, 0, 1, 0),
        lambda: flex.cm(2),
        lambda: flex.cm(-1),
        lambda: flex.lrn_q(111),
        lambda: flex.lrn_q(-1),
        lambda: flex.erssp_q(4),  # ports 0-3 only
        lambda: flex.erssp_q(-1),
        lambda: flex.corrst_q(7, "phase"),  # phase compensation is ADJ, not CORRST
        lambda: flex.corrst_q(11, "open"),
        lambda: flex.adj_q(7, 2),  # modes 0 and 1 only
        lambda: flex.adj_q(0, 0),
    ],
)
def test_builders_reject_values_outside_the_manual_domain(call) -> None:
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize(
    "call",
    [
        lambda: flex.cn([True]),
        lambda: flex.mm(2.0, [1]),
        lambda: flex.wv(1, 1, 0, 0, 1, 11.0, 1e-3),
        lambda: flex.wi(1, 1, 0, 0, 1e-3, 11.0, 2),
        lambda: flex.wnx(2.0, 3, "V", 0, 0, 1, 1e-3),
        lambda: flex.di(1, True, 1e-6, 2),
        lambda: flex.dv(1, 0, True, 1e-3),
        lambda: flex.cm(True),
        lambda: flex.lrn_q(31.0),
        lambda: flex.erssp_q(True),
        lambda: flex.adj_q(7, 0.0),
    ],
)
def test_builders_reject_wrong_types(call) -> None:
    with pytest.raises(TypeError):
        call()


def test_ait_accepts_table_4_21_bounds() -> None:
    assert flex.ait(0, 0, 1023) == "AIT 0,0,1023"
    assert flex.ait(1, 1, 127) == "AIT 1,1,127"
    assert flex.ait(2, 2, 100) == "AIT 2,2,100"
    assert flex.ait(2, 3, 2e-6) == "AIT 2,3,2E-06"
    assert flex.ait(0, 0, 4.0) == "AIT 0,0,4"


def test_wt_sends_optional_delays_up_to_the_last_non_zero_one() -> None:
    assert flex.wt(0, 0, 0, 0, 0.5) == "WT 0,0,0,0,0.5"
    assert flex.wt(0, 0, 0.2) == "WT 0,0,0.2"


# -- citations ----------------------------------------------------------------------------------------------------


def test_every_builder_and_constant_cites_a_pdf_page() -> None:
    docs = _constant_docstrings()
    for name in _builders():
        assert _cited_pages(getattr(flex, name).__doc__ or ""), name
    for name in COMMAND_CONSTANTS:
        assert _cited_pages(docs.get(name, "")), name


def test_docstring_pages_match_the_driver_map() -> None:
    """Each driver-map command with a builder lists PDF pages, and the builder's docstring cites all of them."""
    doc = yaml.safe_load(MAP.read_text(encoding="utf-8"))
    docs = _constant_docstrings()
    with_builder = [entry for entry in doc["commands"] if "builder" in entry]
    assert {entry["builder"].removeprefix("flex.") for entry in with_builder} == set(_builders()) | set(
        COMMAND_CONSTANTS)
    for entry in with_builder:
        name = entry["builder"].removeprefix("flex.")
        obj = getattr(flex, name)
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


# -- package layout -----------------------------------------------------------------------------------------------


def _own_constants(module: ModuleType) -> list[str]:
    tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) \
            else []
        names += [t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("_")]
    return names


def test_the_package_re_exports_every_family_builder_and_constant() -> None:
    public = {name for module in FAMILY_MODULES for name in _own_functions(module) + _own_constants(module)}
    assert public == set(flex.__all__)
    families = {module.__name__.rsplit(".", 1)[-1] for module in FAMILY_MODULES}
    assert set(flex.__all__) == {name for name in vars(flex) if not name.startswith("_")} - families
    for name in flex.__all__:
        owners = [m for m in FAMILY_MODULES if name in _own_functions(m) + _own_constants(m)]
        assert len(owners) == 1 and getattr(flex, name) is getattr(owners[0], name), name


def test_family_modules_hold_disjoint_builders() -> None:
    assert not set(_own_functions(flex_core)) & set(_own_functions(flex_smu))
    assert {"cn", "cl", "dz", "fmt", "mm", "cm", "lrn_q", "tsc", "tsr"} == set(_own_functions(flex_core))
    assert {"mcc", "ml", "mt", "msc", "mv", "mi"} == set(_own_functions(flex_sampling))  # WP7.4
    assert {"pt", "pv", "pi", "pwv", "pwi", "mcpt", "mcpnt", "mcpnx", "mcpws", "mcpwnx"} == set(
        _own_functions(flex_pulsed))  # WP7.3
    assert {"lsv", "lsi", "lgv", "lgi", "lsm", "lstm", "lssv", "lssi", "lsvm", "bsv", "bsi", "bgv", "bgi", "bsm",
            "bst", "bssv", "bssi", "bsvm", "bdv", "bdt", "bdm"} == set(_own_functions(flex_search))  # WP7.5
    assert {"cmm", "aad", "ait", "ri", "rv", "wt", "wm", "dv", "wv", "di", "wi", "wsv", "wsi", "wnx"} == set(
        _own_functions(flex_smu))
    assert {"corrst_q", "adj_q", "imp", "fc", "acv", "dcv", "rc", "act", "lmn", "wdcv", "wtdcv", "wmdcv", "wfc",
            "wtfc", "wmfc", "wacv", "wtacv", "wmacv", "pdcv", "ptdcv", "pwdcv", "mdcv", "mtdcv", "adj", "corrl",
            "clcorr", "corr_q", "dcorr", "corrdt", "corrst", "corrl_q", "dcorr_q"} == set(
        _own_functions(flex_cmu))  # WP8.1; the set-up queries CORRL?, DCORR? WP8.2
    assert {"sim", "spm", "spt", "spv", "spper", "sprm", "ser", "spupd", "odsw", "stgp", "corrser_q", "alw",
            "als"} == set(_own_functions(flex_spgu))  # WP9.1
    assert {"SPST_Q", "SRP", "SPP"} <= set(_own_constants(flex_spgu))
    assert {"erssp_q", "sap", "sar", "sal", "ssp", "ssl", "ermod", "erssp"} == set(_own_functions(flex_switch))
    assert {"ERMOD_Q", "ASU_PATHS", "LRN_ASU_PATH", "LRN_ASU_1PA", "SSP_PATHS", "LRN_SCUU_PATH", "ERMOD_MODES",
            "ERSSP_CODES"} <= set(_own_constants(flex_switch))  # ERMOD/ERSSP: WP9.2
