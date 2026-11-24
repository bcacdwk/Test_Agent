"""A small SPICE netlist parser for the export tests (WP7.7, blueprint v2 10.3 "netlist passes a SPICE-syntax parser
test"; no external simulator, OD-6).

It covers the grammar ``analysis/spice.py`` emits, checked the way SPICE3/ngspice and HSPICE read a deck: the first
line of a netlist is the title; ``*`` lines are comments; ``+`` continues the previous line (joined with a space);
elements ``M`` (MOSFET: 4 nodes, a model, ``W=``/``L=``), ``X`` (subcircuit instance: nodes, then the subcircuit
name), ``V`` (``n+ n- [DC] value``), ``R`` (two nodes, a non-zero value), ``B`` (ngspice behavioural source
``n+ n- I=expr``) and ``G`` (HSPICE ``n+ n- CUR='expr'``); dot cards ``.model name NMOS|PMOS (k=v ...)``,
``.subckt``/``.ends``, ``.dc`` (one or two ``source start stop step`` groups), ``.print dc``, ``.end`` (last,
netlist only). Numbers take the SPICE scale suffixes (``f p n u m k meg g t``). Expressions are parsed by recursive
descent (numbers, ``V(a[,b])``, ``+ - * /``, unary minus, parentheses and the functions ``exp abs min max sqrt`` plus
``ln`` (ngspice) or ``log`` (HSPICE), both natural logarithms) and can be evaluated, so a test can run the DC sweep
of a parsed deck and compare it with the analysis model.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

Dialect = Literal["ngspice", "hspice"]

SCALE = {"T": 1e12, "G": 1e9, "MEG": 1e6, "K": 1e3, "M": 1e-3, "MIL": 25.4e-6, "U": 1e-6, "N": 1e-9, "P": 1e-12,
         "F": 1e-15}
_NUMBER = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(MEG|MIL|[TGKMUNPF])?[A-Za-z]*$", re.IGNORECASE)
_NAME = re.compile(r"^[A-Za-z0-9_]+$")
FUNCTIONS = {"exp": 1, "abs": 1, "sqrt": 1, "min": 2, "max": 2}
LOG_FUNCTION: dict[Dialect, str] = {"ngspice": "ln", "hspice": "log"}


class SpiceSyntaxError(ValueError):
    """The deck violates the grammar (message names the logical line)."""


def number(text: str) -> float:
    """A SPICE number with an optional scale suffix (``1u`` = 1e-6, ``20MEG`` = 2e7)."""
    match = _NUMBER.match(text)
    if match is None:
        raise SpiceSyntaxError(f"not a SPICE number: {text!r}")
    value = float(match.group(1))
    suffix = (match.group(2) or "").upper()
    return value * SCALE.get(suffix, 1.0)


# -- expressions -----------------------------------------------------------------------------------------------------

Node = tuple  # expression tree: ("num", v) | ("v", a, b) | ("neg", x) | (op, x, y) | ("call", f, args)


class _Parser:
    def __init__(self, text: str, dialect: Dialect) -> None:
        self.tokens = re.findall(r"\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z0-9_]*|[()+\-*/,]",
                                 text)
        if "".join(self.tokens) != re.sub(r"\s+", "", text):
            raise SpiceSyntaxError(f"unexpected characters in expression {text[:60]!r}")
        self.pos = 0
        self.functions = {**FUNCTIONS, LOG_FUNCTION[dialect]: 1}

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise SpiceSyntaxError(f"expected {expected or 'a token'}, got {token!r}")
        self.pos += 1
        return token

    def parse(self) -> Node:
        tree = self.sum()
        if self.peek() is not None:
            raise SpiceSyntaxError(f"trailing tokens from {self.peek()!r}")
        return tree

    def sum(self) -> Node:
        tree = self.product()
        while self.peek() in ("+", "-"):
            op = self.take()
            tree = (op, tree, self.product())
        return tree

    def product(self) -> Node:
        tree = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            tree = (op, tree, self.unary())
        return tree

    def unary(self) -> Node:
        if self.peek() == "-":
            self.take()
            return ("neg", self.unary())
        if self.peek() == "+":
            self.take()
        return self.atom()

    def atom(self) -> Node:
        token = self.take()
        if token == "(":
            tree = self.sum()
            self.take(")")
            return tree
        if token[0].isdigit() or token[0] == ".":
            return ("num", float(token))
        if token.upper() == "V" and self.peek() == "(":
            self.take("(")
            a = self.take()
            b = "0"
            if self.peek() == ",":
                self.take(",")
                b = self.take()
            self.take(")")
            if not (_NAME.match(a) and _NAME.match(b)):
                raise SpiceSyntaxError(f"bad node in V({a},{b})")
            return ("v", a, b)
        if token in self.functions and self.peek() == "(":
            self.take("(")
            args = [self.sum()]
            while self.peek() == ",":
                self.take(",")
                args.append(self.sum())
            self.take(")")
            if len(args) != self.functions[token]:
                raise SpiceSyntaxError(f"{token} takes {self.functions[token]} argument(s), got {len(args)}")
            return ("call", token, args)
        raise SpiceSyntaxError(f"unknown name {token!r} in expression (functions: {sorted(self.functions)})")


def parse_expression(text: str, dialect: Dialect) -> Node:
    return _Parser(text, dialect).parse()


def evaluate(tree: Node, voltage: Callable[[str], float]) -> float:
    """Value of an expression tree with node voltages from ``voltage(node)`` (``0`` is ground)."""
    kind = tree[0]
    if kind == "num":
        return tree[1]
    if kind == "v":
        return voltage(tree[1]) - voltage(tree[2])
    if kind == "neg":
        return -evaluate(tree[1], voltage)
    if kind == "call":
        args = [evaluate(a, voltage) for a in tree[2]]
        name = tree[1]
        if name in ("ln", "log"):
            return math.log(args[0])
        return {"exp": math.exp, "abs": abs, "sqrt": math.sqrt, "min": min, "max": max}[name](*args)
    a, b = evaluate(tree[1], voltage), evaluate(tree[2], voltage)
    if kind == "+":
        return a + b
    if kind == "-":
        return a - b
    return a * b if kind == "*" else a / b


# -- decks -----------------------------------------------------------------------------------------------------------


@dataclass
class Element:
    name: str
    nodes: list[str]
    model: str | None = None
    value: float | None = None
    params: dict[str, float] = field(default_factory=dict)
    expression: Node | None = None


@dataclass
class Subckt:
    name: str
    ports: list[str]
    elements: dict[str, Element] = field(default_factory=dict)


@dataclass
class Deck:
    title: str | None
    models: dict[str, tuple[str, dict[str, float]]] = field(default_factory=dict)
    subckts: dict[str, Subckt] = field(default_factory=dict)
    elements: dict[str, Element] = field(default_factory=dict)
    dc: list[tuple[str, float, float, float]] = field(default_factory=list)
    prints: list[str] = field(default_factory=list)
    ended: bool = False


def logical_lines(text: str, *, title: bool) -> tuple[str | None, list[str]]:
    """The title (first line of a netlist) and the logical lines: comments dropped, ``+`` continuations joined."""
    raw = text.split("\n")
    if raw and raw[-1] == "":
        raw.pop()
    head = raw.pop(0) if title and raw else None
    lines: list[str] = []
    for line in raw:
        if not line.strip() or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not lines:
                raise SpiceSyntaxError("a continuation line has nothing to continue")
            lines[-1] += " " + line[1:].strip()
            continue
        if line[0].isspace():
            raise SpiceSyntaxError(f"line starts with white space: {line[:40]!r}")
        lines.append(line.strip())
    return head, lines


def _params(tokens: list[str], where: str) -> dict[str, float]:
    out = {}
    for token in tokens:
        key, sep, value = token.partition("=")
        if not sep or not _NAME.match(key):
            raise SpiceSyntaxError(f"{where}: expected name=value, got {token!r}")
        out[key.upper()] = number(value)
    return out


def _element(line: str, dialect: Dialect) -> Element:
    if line[0] in "BG":
        head, sep, expr = line.partition("I=" if line[0] == "B" else "CUR=")
        if not sep:
            raise SpiceSyntaxError(f"{line[:20]}: a {line[0]} source needs {'I=' if line[0] == 'B' else 'CUR='}")
        if line[0] == "B" and dialect != "ngspice":
            raise SpiceSyntaxError("B sources are ngspice syntax")
        if line[0] == "G":
            if dialect != "hspice":
                raise SpiceSyntaxError("G ... CUR= sources are HSPICE syntax")
            expr = expr.strip()
            if not (expr.startswith("'") and expr.endswith("'")):
                raise SpiceSyntaxError("an HSPICE CUR expression is quoted with ' ... '")
            expr = expr[1:-1]
        tokens = head.split()
        if len(tokens) != 3:
            raise SpiceSyntaxError(f"{tokens[0]}: needs exactly two nodes")
        return Element(tokens[0], tokens[1:3], expression=parse_expression(expr, dialect))
    tokens = line.split()
    name, kind = tokens[0], line[0].upper()
    if not _NAME.match(name):
        raise SpiceSyntaxError(f"bad element name {name!r}")
    if kind == "M":
        if len(tokens) < 6:
            raise SpiceSyntaxError(f"{name}: M needs d g s b and a model")
        return Element(name, tokens[1:5], model=tokens[5], params=_params(tokens[6:], name))
    if kind == "X":
        if len(tokens) < 3:
            raise SpiceSyntaxError(f"{name}: X needs nodes and a subcircuit")
        return Element(name, tokens[1:-1], model=tokens[-1])
    if kind == "V":
        rest = tokens[3:]
        if rest and rest[0].upper() == "DC":
            rest = rest[1:]
        if len(tokens) < 4 or len(rest) != 1:
            raise SpiceSyntaxError(f"{name}: V needs n+ n- [DC] value")
        return Element(name, tokens[1:3], value=number(rest[0]))
    if kind == "R":
        if len(tokens) != 4 or number(tokens[3]) == 0:
            raise SpiceSyntaxError(f"{name}: R needs two nodes and a non-zero value")
        return Element(name, tokens[1:3], value=number(tokens[3]))
    raise SpiceSyntaxError(f"unsupported element {name!r}")


def parse_deck(text: str, dialect: Dialect, *, netlist: bool) -> Deck:
    """Parse and check a ``.sp`` netlist (``netlist=True``: title line, ``.end`` last) or a ``.lib`` file."""
    if "\r" in text or "\t" in text:
        raise SpiceSyntaxError("CR or tab characters in the deck")
    title, lines = logical_lines(text, title=netlist)
    if netlist and not (title and title.strip() and not title.startswith((".", "+"))):
        raise SpiceSyntaxError("a netlist starts with a title line")
    deck = Deck(title=title)
    scope: Subckt | None = None
    for index, line in enumerate(lines):
        if deck.ended:
            raise SpiceSyntaxError(f"text after .end: {line[:40]!r}")
        word = line.split()[0].lower()
        if word == ".model":
            match = re.fullmatch(r"\.model\s+(\w+)\s+(NMOS|PMOS)\s*\((.*)\)", line, re.IGNORECASE)
            if match is None:
                raise SpiceSyntaxError(f"bad .model card: {line[:60]!r}")
            params = _params(match.group(3).split(), match.group(1))
            if params.get("LEVEL") != 1 or "VTO" not in params or "KP" not in params:
                raise SpiceSyntaxError(".model needs LEVEL=1, VTO and KP")
            deck.models[match.group(1)] = (match.group(2).upper(), params)
        elif word == ".subckt":
            if scope is not None:
                raise SpiceSyntaxError("nested .subckt")
            tokens = line.split()
            scope = Subckt(tokens[1], tokens[2:])
        elif word == ".ends":
            tokens = line.split()
            if scope is None or (len(tokens) > 1 and tokens[1] != scope.name):
                raise SpiceSyntaxError(".ends without its .subckt")
            deck.subckts[scope.name] = scope
            scope = None
        elif word == ".dc":
            tokens = line.split()[1:]
            if len(tokens) not in (4, 8):
                raise SpiceSyntaxError(".dc takes one or two groups of source start stop step")
            for k in range(0, len(tokens), 4):
                deck.dc.append((tokens[k], number(tokens[k + 1]), number(tokens[k + 2]), number(tokens[k + 3])))
        elif word == ".print":
            tokens = line.split()
            if len(tokens) < 3 or tokens[1].lower() != "dc":
                raise SpiceSyntaxError(".print dc <outputs>")
            deck.prints += tokens[2:]
        elif word == ".end":
            if index != len(lines) - 1:
                raise SpiceSyntaxError(".end must be the last line")
            deck.ended = True
        elif word.startswith("."):
            raise SpiceSyntaxError(f"unsupported dot card {word}")
        else:
            element = _element(line, dialect)
            target = scope.elements if scope is not None else deck.elements
            if element.name.upper() in {n.upper() for n in target}:
                raise SpiceSyntaxError(f"duplicate element {element.name}")
            target[element.name] = element
    if scope is not None:
        raise SpiceSyntaxError(f".subckt {scope.name} has no .ends")
    if netlist != deck.ended:
        raise SpiceSyntaxError("a netlist ends with .end; a library has no .end")
    _check_references(deck, netlist)
    return deck


def _check_references(deck: Deck, netlist: bool) -> None:
    for element in [*deck.elements.values(), *(e for s in deck.subckts.values() for e in s.elements.values())]:
        if element.name[0] == "M" and element.model not in deck.models:
            raise SpiceSyntaxError(f"{element.name}: model {element.model} is not defined")
        if element.name[0] == "X":
            sub = deck.subckts.get(element.model or "")
            if sub is None or len(sub.ports) != len(element.nodes):
                raise SpiceSyntaxError(f"{element.name}: subcircuit {element.model} missing or wrong node count")
    for sub in deck.subckts.values():
        for element in sub.elements.values():
            if element.expression is not None:
                for node in _nodes(element.expression):
                    if node not in sub.ports and node not in {n for e in sub.elements.values() for n in e.nodes}:
                        raise SpiceSyntaxError(f"{sub.name}/{element.name}: unknown node {node}")
    sources = {n.upper() for n in deck.elements if n[0] == "V"}
    for source, *_ in deck.dc:
        if source.upper() not in sources:
            raise SpiceSyntaxError(f".dc sweeps {source}, which is not a voltage source")
    for output in deck.prints:
        match = re.fullmatch(r"I\((\w+)\)", output, re.IGNORECASE)
        if match is None or match.group(1).upper() not in sources:
            raise SpiceSyntaxError(f".print output {output} is not I(<voltage source>)")
    if netlist and not any("0" in e.nodes for e in deck.elements.values()):
        raise SpiceSyntaxError("the netlist has no ground node 0")


def _nodes(tree: Node) -> set[str]:
    if tree[0] == "v":
        return {tree[1], tree[2]} - {"0"}
    if tree[0] == "num":
        return set()
    if tree[0] == "neg":
        return _nodes(tree[1])
    if tree[0] == "call":
        return set().union(*(_nodes(a) for a in tree[2]))
    return _nodes(tree[1]) | _nodes(tree[2])


# -- DC evaluation of the one-device decks the exporter writes -------------------------------------------------------


def device_current(deck: Deck, terminal: Mapping[str, float], level1: Callable[..., float] | None = None) -> float:
    """Current into the drain node ``d`` of the deck's one device for the terminal voltages ``terminal`` (nodes
    ``d g s b``): a level-1 ``M`` card through ``level1(vto, kp_w_over_l, lam, nmos, vg, vd, vs, vb)``, a subcircuit
    by solving its behavioural source (with the ``RD``/``RS`` drops, by bisection)."""
    [device] = [e for e in deck.elements.values() if e.name[0] in "MX"]
    voltage_of = dict(zip(("d", "g", "s", "b"), device.nodes, strict=True))
    v = {port: terminal[node] for port, node in voltage_of.items()}
    if device.name[0] == "M":
        kind, params = deck.models[device.model or ""]
        beta = params["KP"] * device.params["W"] / device.params["L"]
        assert level1 is not None
        return level1(params["VTO"], beta, params.get("LAMBDA", 0.0), kind == "NMOS", v["g"], v["d"], v["s"], v["b"])
    sub = deck.subckts[device.model or ""]
    ports = dict(zip(sub.ports, ("d", "g", "s", "b"), strict=True))
    [source] = [e for e in sub.elements.values() if e.expression is not None]
    rd = sub.elements.get("RD")
    rs = sub.elements.get("RS")
    r_d = rd.value if rd is not None else 0.0
    r_s = rs.value if rs is not None else 0.0
    plus, minus = source.nodes

    def through(i: float) -> float:
        nodes = {port: v[name] for port, name in ports.items()}
        nodes["di"] = v["d"] - i * (r_d or 0.0)
        nodes["si"] = v["s"] + i * (r_s or 0.0)
        value = evaluate(source.expression, lambda n: 0.0 if n == "0" else nodes[n])  # type: ignore[arg-type]
        return value if (plus, minus) in (("di", "si"), ("d", "s")) else -value

    i0 = through(0.0)
    if not (r_d or r_s):
        return i0
    lo, hi = min(i0, 0.0), max(i0, 0.0)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if mid - through(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def dc_points(deck: Deck) -> list[dict[str, float]]:
    """The node voltages of every point of the deck's ``.dc`` sweep (inner source fastest)."""
    sources = {e.name.upper(): e for e in deck.elements.values() if e.name[0] == "V"}
    base = {e.nodes[0]: float(e.value or 0.0) for e in sources.values()}

    def grid(start: float, stop: float, step: float) -> list[float]:
        count = round((stop - start) / step) + 1 if step else 1
        return [start + k * step for k in range(count)]

    inner = deck.dc[0]
    outer = deck.dc[1] if len(deck.dc) > 1 else None
    points = []
    for level in grid(*outer[1:]) if outer else [None]:
        for value in grid(*inner[1:]):
            node = dict(base)
            node[sources[inner[0].upper()].nodes[0]] = value
            if outer is not None and level is not None:
                node[sources[outer[0].upper()].nodes[0]] = level
            node.setdefault("s", 0.0)
            node.setdefault("b", node["s"])
            points.append(node)
    return points
