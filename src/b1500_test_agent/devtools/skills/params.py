"""Card parameter tables (section 4 of a test card): value, interval and list parsing with SI prefixes and units,
and the checks of each row against the recipe ``ParamSpec`` (default, recommended, recipe range)."""


from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from b1500_test_agent.devtools.skills.common import ProblemCode
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc
from b1500_test_agent.models.recipe import ParamSpec

PARAM_TABLE_COLUMNS = ("param", "default", "recommended", "recipe range")
NONE_MARKERS = frozenset({"", "-", "—", "–", "n/a", "none"})
REQUIRED_MARKERS = frozenset({"required", "(required)"})
SI_PREFIXES = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6,
               "G": 1e9}


# == Values of the card parameter table ===============================================================================

_NUMBER = re.compile(r"^\s*([+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?)\s*(.*?)\s*$")
MINUS_SIGN = "\u2212"  # typographic minus (U+2212), as written in the deck
_RANGE_SEP = re.compile(r"\s*(?:\.\.|…|\bto\b)\s*")
_BRACKETS = re.compile(r"^\[(.*)\]\s*(\S*)\s*$")


def _clean(cell: str) -> str:
    """A table cell without emphasis, backticks and surrounding blanks."""
    return cell.replace("`", "").replace("**", "").strip()


def _unit_factor(suffix: str, unit: str | None) -> float | None:
    """Scale of ``suffix`` (SI prefix + unit) for a parameter in ``unit``; ``None`` when it does not fit."""
    text = suffix.replace("Ω", "Ohm").replace("ohm", "Ohm")
    if text == "":
        return 1.0
    if unit is None or unit == "1":
        return None
    if text == unit:
        return 1.0
    prefix = text[: -len(unit)] if text.endswith(unit) else None
    return SI_PREFIXES.get(prefix) if prefix else None


def parse_value(text: str, unit: str | None) -> tuple[float, str]:
    """``(value in base units, suffix as written)`` of ``-1 V``, ``50 mV``, ``1e-6``; raises ``ValueError``."""
    match = _NUMBER.match(text.replace(MINUS_SIGN, "-"))
    if not match:
        raise ValueError(f"{text.strip()!r} is not a number")
    factor = _unit_factor(match.group(2), unit)
    if factor is None:
        raise ValueError(f"{text.strip()!r}: unit {match.group(2)!r} does not fit the parameter unit {unit or 'none'}")
    return float(match.group(1)) * factor, match.group(2)


def _split_items(text: str) -> list[str]:
    """Items of ``a, b`` or ``[a, b] unit`` (a unit after the bracket applies to unitless items)."""
    bracket = _BRACKETS.match(text.strip())
    if not bracket:
        return [part.strip() for part in text.split(",")]
    suffix = bracket.group(2)
    items = [part.strip() for part in bracket.group(1).split(",")]
    return [f"{item} {suffix}" if suffix and not _has_suffix(item) else item for item in items]


def _has_suffix(item: str) -> bool:
    match = _NUMBER.match(item.replace(MINUS_SIGN, "-"))
    return bool(match and match.group(2))


def parse_interval(text: str, unit: str | None) -> tuple[float, float]:
    """``(low, high)`` of ``a..b``, ``a … b``, ``a to b`` or ``[a, b]`` (a unitless low end takes the high end's
    unit); raises ``ValueError``."""
    stripped = text.strip()
    parts = _split_items(stripped) if stripped.startswith("[") else _RANGE_SEP.split(stripped)
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"{stripped!r} is not an interval low..high")
    high, high_suffix = parse_value(parts[1], unit)
    low, low_suffix = parse_value(parts[0], unit)
    if not low_suffix and high_suffix:
        low *= _unit_factor(high_suffix, unit) or 1.0
    if low > high:
        raise ValueError(f"{stripped!r}: low end above high end")
    return low, high


def parse_list(text: str, unit: str | None) -> list[float]:
    """Values of ``[a, b, c] V`` or ``a, b, c``; raises ``ValueError``."""
    return [parse_value(item, unit)[0] for item in _split_items(text)]


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=0.0)


def _fmt(value: float, unit: str | None) -> str:
    return f"{value:g} {unit}" if unit and unit != "1" else f"{value:g}"


def _fmt_interval(window: tuple[float, float], unit: str | None) -> str:
    return f"{window[0]:g}..{_fmt(window[1], unit)}"


def _is_none(cell: str, *, required_ok: bool = False) -> bool:
    text = _clean(cell).lower()
    return text in NONE_MARKERS or (required_ok and text in REQUIRED_MARKERS)


def _split_row(line: str) -> list[str]:
    text = line.strip().removeprefix("|")
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", text)]


_DELIMITER_ROW = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


@dataclass(frozen=True)
class ParamRow:
    name: str
    default: str
    recommended: str
    range: str
    line: int


def param_rows(doc: MarkdownDoc, start: int, end: int) -> tuple[list[ParamRow], list[tuple[int, str]]]:
    """Rows of every parameter table between 1-based lines ``start`` and ``end`` (exclusive), plus row problems."""
    rows: list[ParamRow] = []
    problems: list[tuple[int, str]] = []
    number = start
    while number < end:
        line = doc.lines[number - 1]
        cells = [_clean(c).lower() for c in _split_row(line)] if line.lstrip().startswith("|") else []
        if number in doc.fenced or tuple(cells[:4]) != PARAM_TABLE_COLUMNS:
            number += 1
            continue
        if number + 1 >= end or not _DELIMITER_ROW.match(doc.lines[number]):
            problems.append((number, "parameter table header is not followed by a |---| delimiter row"))
            number += 1
            continue
        number += 2
        while number < end and doc.lines[number - 1].lstrip().startswith("|") and number not in doc.fenced:
            row = _split_row(doc.lines[number - 1])
            if len(row) < 4:
                problems.append((number, f"parameter table row has {len(row)} cells; expected at least 4"))
            else:
                rows.append(ParamRow(name=_clean(row[0]), default=row[1], recommended=row[2], range=row[3],
                                     line=number))
            number += 1
    return rows, problems


def check_param_row(row: ParamRow, recipe_id: str, spec: ParamSpec) -> list[tuple[ProblemCode, str]]:
    """Problems of one table row against one recipe parameter (see the section-4 contract)."""
    out: list[tuple[ProblemCode, str]] = []

    def flag(code: ProblemCode, message: str) -> None:
        out.append((code, message))

    where = f"param {row.name} (recipe {recipe_id})"
    if spec.type == "enum":
        choices = list(spec.choices or [])
        if _is_none(row.default, required_ok=True):
            if spec.default is not None:
                flag("param_range", f"{where}: default is empty but the recipe default is {spec.default}")
        else:
            value = _clean(row.default)
            if value not in choices:
                flag("param_range", f"{where}: default {value!r} is not one of the recipe choices {choices}")
            elif value != spec.default:
                flag("param_range", f"{where}: default {value!r} differs from the recipe default "
                     f"{spec.default!r}")
        for column, cell in (("recommended", row.recommended), ("recipe range", row.range)):
            if _is_none(cell):
                continue
            items = [_clean(item) for item in re.split(r"[,|/]", _clean(cell).strip("[]{}")) if _clean(item)]
            unknown = [item for item in items if item not in choices]
            if unknown:
                flag("param_range", f"{where}: {column} {unknown} outside the recipe choices {choices}")
            elif column == "recipe range" and sorted(set(items)) != sorted(choices):
                flag("param_range", f"{where}: recipe range {items} differs from the recipe choices "
                     f"{choices}")
        return out
    if spec.type == "bool":
        if not _is_none(row.default, required_ok=True):
            value = _clean(row.default).lower()
            if value not in ("true", "false"):
                flag("param_table", f"{where}: default {row.default!r} is not true/false")
            elif (value == "true") != spec.default:
                flag("param_range", f"{where}: default {value} differs from the recipe default "
                     f"{str(spec.default).lower()}")
        for column, cell in (("recommended", row.recommended), ("recipe range", row.range)):
            if not _is_none(cell):
                flag("param_table", f"{where}: a bool parameter has no {column} (use -)")
        return out
    unit = spec.unit
    rng = spec.range
    # default
    if _is_none(row.default, required_ok=True):
        if spec.default is not None:
            flag("param_range", f"{where}: default is empty but the recipe default is "
                 f"{_fmt_default(spec.default, unit)}")
    else:
        try:
            values = parse_list(_clean(row.default), unit) if spec.type == "float_list" else \
                [parse_value(_clean(row.default), unit)[0]]
        except ValueError as exc:
            flag("param_table", f"{where}: cannot read default: {exc}")
            values = None
        if values is not None:
            expected = spec.default if isinstance(spec.default, list) else [spec.default]
            if rng is not None and any(not rng[0] <= v <= rng[1] for v in values):
                flag("param_range", f"{where}: default {_clean(row.default)} lies outside the recipe range "
                     f"{_fmt_interval(rng, unit)}")
            elif spec.default is None:
                flag("param_range", f"{where}: default {_clean(row.default)} given, but the recipe "
                     "parameter is required (no default)")
            elif len(values) != len(expected) or not all(_close(a, float(b)) for a, b in zip(values, expected,
                                                                                             strict=False)):
                flag("param_range", f"{where}: default {_clean(row.default)} differs from the recipe default "
                     f"{_fmt_default(spec.default, unit)}")
    # recommended
    if not _is_none(row.recommended):
        try:
            window = parse_interval(_clean(row.recommended), unit)
        except ValueError as exc:
            flag("param_table", f"{where}: cannot read recommended: {exc}")
        else:
            if rng is not None and not (rng[0] <= window[0] and window[1] <= rng[1]):
                flag("param_range", f"{where}: recommended {_fmt_interval(window, unit)} lies outside the "
                     f"recipe range {_fmt_interval(rng, unit)}")
    # recipe range
    if _is_none(row.range):
        if rng is not None:
            flag("param_range", f"{where}: recipe range is empty but the recipe range is "
                 f"{_fmt_interval(rng, unit)}")
    else:
        try:
            stated = parse_interval(_clean(row.range), unit)
        except ValueError as exc:
            flag("param_table", f"{where}: cannot read recipe range: {exc}")
        else:
            if rng is None:
                flag("param_range", f"{where}: recipe range {_fmt_interval(stated, unit)} stated, but the "
                     "recipe parameter has no range")
            elif not (_close(stated[0], rng[0]) and _close(stated[1], rng[1])):
                flag("param_range", f"{where}: recipe range {_fmt_interval(stated, unit)} differs from the "
                     f"recipe's range {_fmt_interval(rng, unit)}")
    return out


def _fmt_default(value: Any, unit: str | None) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(f"{v:g}" for v in value) + "]" + (f" {unit}" if unit and unit != "1" else "")
    return _fmt(float(value), unit) if isinstance(value, int | float) and not isinstance(value, bool) else str(value)


