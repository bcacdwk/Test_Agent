"""Value, trust, method and provenance models shared by plans, recipes and the analysis layer.

Salvaged from the v0.2 ``schemas/d_atom.py`` (tag ``archive/v0.2-fake-mcp``) and trimmed: no placeholder products,
fake/hardware flags or atom ids remain. Uses in blueprint section 2: ``PlanRecord.resolved_params`` and
``MeasurementKind.compile`` take ``dict[str, Quantity]``; ``Recipe.provenance`` is a ``Provenance``;
``RunData.trusted`` takes a ``TrustPolicy``; ``ExtractionResult`` carries a ``MethodRecord`` and a ``QuantityRange``
window.
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field, JsonValue, model_validator

from b1500_test_agent.models.common import StrictModel

Unit = Literal[
    "V", "A", "s", "Hz", "F", "S", "Ohm", "H", "rad", "deg", "1", "C",
    "A/m", "A/m^2", "F/m^2", "V/dec", "mV/dec", "mV/V", "cm^-2", "cm^-2 eV^-1",
]  # fmt: skip
"""Closed unit vocabulary; ``"1"`` marks a dimensionless ratio, ``"C"`` a charge (WP7.6: charge injected by a stress),
``cm^-2``/``cm^-2 eV^-1`` an areal trap density and its density per energy (WP9.3: charge pumping). Units are never
inferred from magnitude."""

Bound = Literal["exact", "upper", "lower"]
"""``upper``/``lower``: the true value is at most/at least ``value`` (e.g. a current at the measurement floor)."""

ParamValue = bool | int | float | str | list[float]
"""Value types a resolved recipe parameter can take (``ParamSpec.type`` float, int, bool, enum, float_list)."""

StatusLetter = Literal["N", "T", "C", "V", "X", "F", "G", "S", "U", "D"]
"""Per-point measurement status letters of FMT 1/5/11/15 (Programming Guide Ed. 15 Table 1-10)."""

TrustLevel = Literal["ok", "limited", "untrusted"]
"""Per-point trust written to the ``trust`` column of ``data.csv``."""

ExtractionOutcome = Literal["ok", "refused", "failed"]
"""Outcome of one extraction: ``ok`` (value set), ``refused`` (untrusted data without ``force``) or ``failed`` (the
data does not allow the method, e.g. too few trusted points). Only ``ok`` carries a value."""

VthMethod = Literal["vth_linear_extrapolation", "vth_constant_current", "vth_max_gm"]
"""Threshold-voltage methods of blueprint section 2.8 (names as in ``ANALYSIS_METHODS``)."""

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
RunId = Annotated[str, Field(pattern=r"^[SH]\d{8}T\d{6}Z-[0-9a-f]{4}$")]
"""Archive run id: ``S`` (simulator) or ``H`` (hardware) + UTC ``YYYYMMDDThhmmssZ`` + ``-`` + 4 hex."""

PositiveFloat = Annotated[float, Field(gt=0)]


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


class Quantity(StrictModel):
    """A value with its unit: a resolved plan parameter, a criterion limit or a reported number.

    ``unit`` is ``None`` for values without a physical unit (counts, enum choices, flags); a value with a unit is
    numeric (a scalar or, for ``float_list`` parameters, a list). ``bound`` other than ``exact`` needs a numeric
    scalar.
    """

    value: ParamValue
    unit: Unit | None = None
    bound: Bound = "exact"

    @model_validator(mode="after")
    def _unit_and_bound_need_numbers(self) -> Quantity:
        numeric_list = isinstance(self.value, list)
        if self.unit is not None and not (_is_number(self.value) or numeric_list):
            raise ValueError(f"A {type(self.value).__name__} value cannot carry the unit {self.unit!r}.")
        if self.bound != "exact" and not _is_number(self.value):
            raise ValueError("Only a numeric scalar can be an upper or lower bound.")
        return self

    @property
    def is_number(self) -> bool:
        """True when ``value`` is a numeric scalar (not a bool, string or list)."""
        return _is_number(self.value)

    def as_float(self) -> float:
        """Return ``value`` as a float; raises ``TypeError`` unless it is a numeric scalar."""
        value = self.value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"Quantity value {value!r} is not a numeric scalar.")
        return float(value)


class QuantityRange(StrictModel):
    """A closed window ``[low, high]`` in one unit, e.g. the gate-voltage fit window of an extraction."""

    low: float
    high: float
    unit: Unit

    @model_validator(mode="after")
    def _ordered(self) -> QuantityRange:
        if not self.low < self.high:
            raise ValueError("low must be smaller than high.")
        return self

    def contains(self, value: float) -> bool:
        """True when ``low <= value <= high``."""
        return self.low <= value <= self.high


class TrustPolicy(StrictModel):
    """Which per-point status letters make a point ``limited`` or ``untrusted``.

    Field names match the recipe ``quality`` block. ``N`` is always ``ok``; every other Table 1-10 letter must be in
    exactly one list, and ``V`` (its data value 199.999E+99 has no meaning) is always ``untrusted``. Anything that
    is not a Table 1-10 letter (empty, ``W``/``E`` source-data codes, garbage) classifies as ``untrusted``.
    Defaults: compliance on this or another channel (``C``, ``T``) is ``limited``; over-range/aborted (``V``),
    oscillation (``X``), force saturation (``F``), CMU saturation/unbalance (``D``, ``U``) and search codes (``G``,
    ``S``; no search measurement in v1) are ``untrusted``.
    """

    limited: list[StatusLetter] = Field(default_factory=lambda: ["C", "T"])
    untrusted: list[StatusLetter] = Field(default_factory=lambda: ["V", "X", "F", "D", "G", "S", "U"])

    @model_validator(mode="after")
    def _partition_of_status_letters(self) -> TrustPolicy:
        for name, letters in (("limited", self.limited), ("untrusted", self.untrusted)):
            if len(set(letters)) != len(letters):
                raise ValueError(f"{name} lists a status letter twice.")
            if "N" in letters:
                raise ValueError("N (normal) is always ok.")
        if set(self.limited) & set(self.untrusted):
            raise ValueError("A status letter cannot be both limited and untrusted.")
        missing = sorted(set(get_args(StatusLetter)) - {"N"} - set(self.limited) - set(self.untrusted))
        if missing:
            raise ValueError(f"Status letters {missing} must be classified as limited or untrusted.")
        if "V" in self.limited:
            raise ValueError("V marks invalid data (199.999E+99) and is always untrusted.")
        return self

    def classify(self, status: str) -> TrustLevel:
        """Trust level of one measurement-data status letter."""
        if status == "N":
            return "ok"
        if status in self.limited:
            return "limited"
        return "untrusted"


class DerivativeMethod(StrictModel):
    """Declared numerical derivative (e.g. for gm); no smoothing beyond the declared window."""

    name: Literal["central_difference", "savitzky_golay"]
    window_points: Annotated[int, Field(ge=3, le=101)] | None = None
    polyorder: Annotated[int, Field(ge=1, le=5)] | None = None

    @model_validator(mode="after")
    def _window_matches_method(self) -> DerivativeMethod:
        if self.name == "savitzky_golay":
            if self.window_points is None or self.polyorder is None:
                raise ValueError("savitzky_golay requires window_points and polyorder.")
            if self.window_points % 2 == 0 or self.polyorder >= self.window_points:
                raise ValueError("window_points must be odd and larger than polyorder.")
        elif self.window_points is not None or self.polyorder is not None:
            raise ValueError("central_difference takes no window_points or polyorder.")
        return self


class VthSpec(StrictModel):
    """Declared threshold-voltage method, e.g. for ``memory_window(vth_method)``.

    ``vth_constant_current`` needs the critical current ``i_crit_a`` (A) and optionally ``w_over_l`` to scale it
    by geometry; the other methods take neither.
    """

    method: VthMethod
    i_crit_a: PositiveFloat | None = None
    w_over_l: PositiveFloat | None = None

    @model_validator(mode="after")
    def _options_match_method(self) -> VthSpec:
        if self.method == "vth_constant_current":
            if self.i_crit_a is None:
                raise ValueError("vth_constant_current requires i_crit_a.")
        elif self.i_crit_a is not None or self.w_over_l is not None:
            raise ValueError("i_crit_a and w_over_l apply only to vth_constant_current.")
        return self


class MethodRecord(StrictModel):
    """Which method produced a derived value: name, version and the exact options used.

    ``script`` is the repo-relative path of an ad-hoc agent script under ``work/`` when the value did not come from
    a registered method.
    """

    name: Identifier
    version: str = Field(min_length=1)
    params: dict[str, JsonValue] = Field(default_factory=dict)
    script: str | None = None


class Provenance(StrictModel):
    """Where a recipe's defaults and ranges come from, and which archived runs validated it.

    Example: ``{sources: ["deck slide 6", "Programming Guide WV/FMT pages"], validation_runs: []}``.
    """

    sources: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    validation_runs: list[RunId] = Field(default_factory=list)


class Criterion(StrictModel):
    """One acceptance criterion on an extracted quantity, e.g. ``vth within 0.3 V .. 0.7 V``.

    ``quantity`` names the ``ExtractionResult.quantity`` it applies to. Limits are exact numeric scalars with a unit;
    ``within`` needs ``limit_high`` in the same unit and above ``limit``.
    """

    quantity: Identifier
    comparator: Literal["le", "ge", "within"]
    limit: Quantity
    limit_high: Quantity | None = None

    @model_validator(mode="after")
    def _limits_are_consistent(self) -> Criterion:
        for limit in (self.limit, self.limit_high):
            if limit is not None and not (limit.is_number and limit.unit is not None and limit.bound == "exact"):
                raise ValueError("Criterion limits must be exact numeric scalars with a unit.")
        if self.comparator == "within":
            if self.limit_high is None:
                raise ValueError("within requires limit_high.")
            if self.limit_high.unit != self.limit.unit:
                raise ValueError("limit and limit_high must share a unit.")
            if not self.limit.as_float() < self.limit_high.as_float():
                raise ValueError("limit must be smaller than limit_high.")
        elif self.limit_high is not None:
            raise ValueError("limit_high applies only to within.")
        return self

    def check(self, value: float, unit: Unit) -> bool:
        """True when ``value`` meets the criterion; raises ``ValueError`` if ``unit`` differs from the limit's."""
        if unit != self.limit.unit:
            raise ValueError(f"Criterion on {self.quantity} is in {self.limit.unit}, got {unit}.")
        low = self.limit.as_float()
        if self.comparator == "le":
            return value <= low
        if self.comparator == "ge":
            return value >= low
        assert self.limit_high is not None
        return low <= value <= self.limit_high.as_float()


class QualityReport(StrictModel):
    """Post-run data-quality classification (blueprint 2.8 ``assess_quality``, rule R-QUAL-*; ``quality.json``).

    ``counts`` maps each status letter seen (unknown codes included verbatim) to its number of measured values over
    all measured columns, ``columns`` gives the same counts per measured column; ``points`` is the number of table
    rows and ``fractions`` the share of rows per trust level (a row takes the worst level of its measured values);
    ``noise`` holds a robust noise estimate per measured column (in the column's unit) and ``snr`` its signal range
    over that noise (omitted when the noise estimate is zero); ``verdict`` is the worst row trust level.
    """

    counts: dict[str, Annotated[int, Field(ge=0)]]
    fractions: dict[TrustLevel, Annotated[float, Field(ge=0, le=1)]]
    noise: dict[str, float] = Field(default_factory=dict)
    verdict: TrustLevel
    warnings: list[str] = Field(default_factory=list)
    points: Annotated[int, Field(ge=0)] = 0
    columns: dict[str, dict[str, Annotated[int, Field(ge=0)]]] = Field(default_factory=dict)
    snr: dict[str, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)


class ExtractionResult(StrictModel):
    """One derived value from an analysis method (blueprint 2.8); always ``derived``, never a measured value.

    ``window`` is the fit window (``None`` when the method has none); ``points_excluded`` counts excluded points by
    reason (e.g. status letter or ``outside_window``); ``fit`` holds named fit outputs (slope, intercept, r2 ...).
    ``forced_on_untrusted`` flags a value extracted from untrusted data on explicit request (``options.force``).
    ``outcome`` is ``ok`` exactly when ``value`` is set; otherwise ``error`` says why (refusal or failure), so a
    refusal is a result, never an exception (``analyze_run`` reports it as ``refused``). ``bound`` other than
    ``exact`` marks a limit, e.g. a leakage current at the measurement floor (``upper``) or a resistance bounded by
    the compliance (``upper``); ``classification`` is the categorical verdict of a classifying method (``resistance``:
    ``open``/``short``/``in_range``; ``leakage_at``: ``pass``/``fail``).
    """

    method: Identifier
    quantity: Identifier
    value: float | None
    unit: Unit
    derived: Literal[True] = True
    method_record: MethodRecord
    window: QuantityRange | None
    points_used: Annotated[int, Field(ge=0)]
    points_excluded: dict[str, Annotated[int, Field(ge=0)]]
    fit: dict[str, float]
    warnings: list[str]
    forced_on_untrusted: bool = False
    outcome: ExtractionOutcome = "ok"
    error: str | None = None
    bound: Bound = "exact"
    classification: Identifier | None = None

    @model_validator(mode="after")
    def _value_iff_ok(self) -> ExtractionResult:
        if (self.value is not None) != (self.outcome == "ok"):
            raise ValueError("value is set exactly when outcome is 'ok'.")
        if (self.outcome != "ok") != bool(self.error):
            raise ValueError("error explains every outcome other than 'ok' and only those.")
        if self.bound != "exact" and self.value is None:
            raise ValueError("Only a value can be an upper or lower bound.")
        return self
