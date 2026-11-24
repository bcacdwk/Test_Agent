"""SPICE export (``analysis/spice.py``, WP7.7): every exported ``.lib``/``.sp`` passes the SPICE-syntax parser of
``tests/unit/spice_syntax.py`` (blueprint v2 10.3 AC; no external simulator, OD-6) in both dialects, and the parsed
netlist's DC sweep, evaluated through its own model card or behavioural source, reproduces the built-in model
evaluation at every sweep point. The parser itself rejects broken decks."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.analysis.model import CompactModel, export_spice_netlist
from b1500_test_agent.analysis.spice import SpiceExport
from tests.unit import spice_syntax as spice
from tests.unit.analysis_helpers import iv_table, run_of

pytestmark = pytest.mark.smu

EKV = {"vt0": 0.42, "n": 1.3, "beta": 2.0e-3, "theta": 0.2, "lambda": 0.05, "rs": 20.0}
LEVEL1 = {"vto": 0.5, "beta": 1e-3, "lambda": 0.04}


def output_run(model: CompactModel, sign: float = 1.0, *, bulk: float | None = None):
    vd = sign * np.round(np.linspace(0.0, 2.0, 41), 9)
    levels = [sign * v for v in (0.8, 1.2, 1.6)]
    gate, drain = np.repeat(levels, vd.size), np.tile(vd, len(levels))
    source = {"drain_V": drain, "gate_V": gate}
    if bulk is not None:
        source["bulk_V"] = np.full(drain.size, bulk)
    current = model.current(gate, drain, 0.0, None if bulk is None else bulk)
    return run_of(iv_table(source, {"drain_I": current + sign * 1e-12}), "mosfet.idvd", kind="smu_stepped")


def level1_current(vto: float, beta: float, lam: float, nmos: bool, vg: float, vd: float, vs: float, vb: float):
    model = CompactModel("level1", {"vto": vto, "beta": beta, "lambda": lam}, polarity="n" if nmos else "p")
    return float(model.current(vg, vd, vs, vb))


def check_export(export: SpiceExport, model: CompactModel, dialect: spice.Dialect) -> spice.Deck:
    lib, netlist = export.files
    spice.parse_deck(lib.text, dialect, netlist=False)
    deck = spice.parse_deck(netlist.text, dialect, netlist=True)
    points = spice.dc_points(deck)
    assert len(points) == 41 * 3
    for node in points:
        built_in = float(model.current(node["g"], node["d"], node["s"], node["b"]))
        from_deck = spice.device_current(deck, node, level1_current)
        assert from_deck == pytest.approx(built_in, rel=1e-6, abs=1e-15), node
    assert all(len(line) <= 110 for line in netlist.text.splitlines() if not line.startswith("*"))
    return deck


@pytest.mark.parametrize("dialect", ["ngspice", "hspice"])
@pytest.mark.parametrize("rs", [0.0, 20.0])
def test_ekv_export_parses_and_reproduces_the_model(dialect: spice.Dialect, rs: float) -> None:
    params = {**EKV, "rs": rs}
    model = CompactModel("ekv", params)
    export = export_spice_netlist(output_run(model), params=params, dialect=dialect)
    deck = check_export(export, model, dialect)
    sub = deck.subckts["nch_ekv"]
    assert sub.ports == ["d", "g", "s", "b"] and ("RD" in sub.elements) == (rs > 0)
    assert deck.dc == [("VD", 0.0, 2.0, pytest.approx(0.05)), ("VG", 0.8, 1.6, pytest.approx(0.4))]
    assert deck.prints == ["I(VD)"] and deck.title and "reproduces run" in deck.title


@pytest.mark.parametrize("dialect", ["ngspice", "hspice"])
def test_p_channel_ekv_export_mirrors_the_voltages(dialect: spice.Dialect) -> None:
    params = {**EKV, "vt0": -0.42}
    model = CompactModel("ekv", params, polarity="p")
    export = export_spice_netlist(output_run(model, sign=-1.0), params=params, dialect=dialect)
    deck = check_export(export, model, dialect)
    assert "pch_ekv" in deck.subckts and "V(b,g)" in export.files[0].text


def test_level1_export_with_and_without_geometry() -> None:
    model = CompactModel("level1", LEVEL1)
    for geometry in ({"w_um": 10.0, "l_um": 2.0}, {}):
        export = export_spice_netlist(output_run(model), model="level1", params=LEVEL1, **geometry)
        deck = check_export(export, model, "ngspice")
        kind, card = deck.models["nch_level1"]
        assert kind == "NMOS" and card["LEVEL"] == 1 and card["VTO"] == 0.5
        m1 = deck.elements["M1"]
        assert card["KP"] * m1.params["W"] / m1.params["L"] == pytest.approx(1e-3)


def test_level1_p_channel_and_bulk_bias() -> None:
    params = {"vto": -0.5, "beta": 1e-3, "lambda": 0.04}
    model = CompactModel("level1", params, polarity="p")
    export = export_spice_netlist(output_run(model, sign=-1.0), model="level1", params=params)
    deck = check_export(export, model, "hspice")
    assert deck.models["pch_level1"][0] == "PMOS"
    biased = export_spice_netlist(output_run(CompactModel("ekv", EKV), bulk=-0.5), params=EKV)
    netlist = spice.parse_deck(biased.files[1].text, "ngspice", netlist=True)
    assert netlist.elements["VB"].value == -0.5 and netlist.elements["X1"].nodes == ["d", "g", "s", "b"]


def test_fitted_export_parses() -> None:
    model = CompactModel("ekv", EKV)
    export = export_spice_netlist(output_run(model), fit_rs=True)
    lib, netlist = export.files
    spice.parse_deck(lib.text, "ngspice", netlist=False)
    spice.parse_deck(netlist.text, "ngspice", netlist=True)
    assert "fitted by compact_model_fit to this run" in netlist.text


# -- the parser rejects broken decks ---------------------------------------------------------------------------------

GOOD = """title
.model n1 NMOS (LEVEL=1 VTO=0.5 KP=1e-3 LAMBDA=0)
M1 d g 0 0 n1 W=1u L=1u
VG g 0 DC 0
VD d 0 DC 0.1
.dc VG 0 1 0.1
.print dc I(VD)
.end
"""


@pytest.mark.parametrize("broken, message", [
    (GOOD.replace(".end\n", ""), "ends with .end"),
    (GOOD.replace("n1 W=", "n2 W="), "not defined"),
    (GOOD.replace("KP=1e-3", "KP=1e-3x3"), "not a SPICE number"),
    (GOOD.replace(".dc VG", ".dc VX"), "not a voltage source"),
    (GOOD.replace("I(VD)", "I(VQ)"), r"not I\(<voltage source>\)"),
    (GOOD.replace("M1 d g 0 0", " M1 d g 0 0"), "white space"),
    (GOOD.replace(".print dc", ".foo dc"), "unsupported dot card"),
    (GOOD + "VX x 0 DC 1\n", "must be the last line"),
])
def test_parser_rejects(broken: str, message: str) -> None:
    with pytest.raises(spice.SpiceSyntaxError, match=message):
        spice.parse_deck(broken, "ngspice", netlist=True)


def test_parser_accepts_the_reference_deck_and_scale_suffixes() -> None:
    deck = spice.parse_deck(GOOD, "ngspice", netlist=True)
    assert deck.models["n1"][1]["KP"] == 1e-3 and deck.elements["M1"].params["W"] == pytest.approx(1e-6)
    assert spice.number("20MEG") == 2e7 and spice.number("1.5k") == 1500 and spice.number("3pF") == pytest.approx(3e-12)


@pytest.mark.parametrize("expression, dialect, message", [
    ("ln(1+exp(V(g,b))", "ngspice", "expected \\)"),
    ("log(2)", "ngspice", "unknown name 'log'"),
    ("ln(2)", "hspice", "unknown name 'ln'"),
    ("min(1)", "ngspice", "takes 2"),
    ("2**3", "ngspice", "expected a token|unknown"),
])
def test_expression_errors(expression: str, dialect: spice.Dialect, message: str) -> None:
    with pytest.raises(spice.SpiceSyntaxError, match=message):
        spice.parse_expression(expression, dialect)


def test_expression_evaluation() -> None:
    tree = spice.parse_expression("2*ln(1+exp(V(g,b)))-min(V(d),3)/abs(-4)", "ngspice")
    volts = {"g": 1.0, "b": 0.0, "d": 2.0}
    value = spice.evaluate(tree, lambda n: 0.0 if n == "0" else volts[n])
    assert value == pytest.approx(2 * np.log1p(np.e) - 0.5)
