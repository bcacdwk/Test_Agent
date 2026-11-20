"""Analysis method registry (blueprint 2.8 ``ANALYSIS_METHODS``) and the uniform runner used by ``analyze_run``.

``run_method(name, data, options, criteria=...)`` returns ``list[ExtractionResult]`` (extraction methods), a
``QualityReport`` (``quality_report``) or a ``PlotSet`` (``plot_iv``: PNG bytes the caller stores through the archive
as ``plots/<name>-<n>.png``). It raises ``InvalidInputError`` for an unknown method, an unknown or invalid
option, or a method that does not apply to the run's recipe/kind, and ``MethodNotImplementedError`` (code
``not_implemented``) for a method that is only declared. Refusals on untrusted data are results (``outcome``
``refused``), not exceptions. ``options`` come from JSON (``analyze_run`` ``options{}`` or a recipe's
``analysis_defaults``); the trust policy is not an option: the caller passes the recipe's ``QualityCriteria`` as
``criteria``, so only ``force`` (flagged) can override a refusal.

Every method carries ``families`` (blueprint v2 2.10): the recipe families (``smu cmu spgu wgfmu nvm reliability
system``, ``Recipe.family``) whose runs it serves; ``methods_for(family)`` lists them. A method applicable (by
``recipes``/``kinds``) to a runnable recipe lists that recipe's family (a registry test checks it).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Any, Literal, get_args

from pydantic import ValidationError

from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.analysis.diode import diode_fit, forward_voltage
from b1500_test_agent.analysis.errors import MethodNotImplementedError
from b1500_test_agent.analysis.fefet import memory_window
from b1500_test_agent.analysis.floor import zero_floor
from b1500_test_agent.analysis.leakage import leakage_at
from b1500_test_agent.analysis.mosfet import (
    gm_max,
    ion_ioff,
    output_metrics,
    subthreshold_swing,
    vth_constant_current,
    vth_linear_extrapolation,
    vth_max_gm,
)
from b1500_test_agent.analysis.mosfet_family import body_effect, dibl
from b1500_test_agent.analysis.plots import PlotSet, plot_iv_method
from b1500_test_agent.analysis.quality import assess_quality
from b1500_test_agent.analysis.reliability import plot_timeseries_method, sampling_summary, time_to_breakdown
from b1500_test_agent.analysis.resistor import kelvin_resistance, resistance
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport, TrustPolicy
from b1500_test_agent.models.recipe import RecipeFamily

MethodStatus = Literal["implemented", "declared"]
Milestone = Literal["M1", "M2", "M5", "M6", "M7", "M8", "M9", "M10", "M11"]
FAMILIES: tuple[RecipeFamily, ...] = get_args(RecipeFamily)
MethodOutput = Literal["quality_report", "extraction", "plots"]
MethodResult = list[ExtractionResult] | QualityReport | PlotSet

_RESERVED_ARGS = frozenset({"d", "criteria"})

_TRANSFER = ("mosfet.idvg", "mosfet.idvg_sync", "fefet.dual_sweep_mw", "generic.*")
_STAIRCASE = ("smu_staircase",)
_SWEEPS = ("smu_staircase", "smu_stepped")
_SPOT = ("smu_spot",)
_SMU: tuple[RecipeFamily, ...] = ("smu",)
_SMU_NVM: tuple[RecipeFamily, ...] = ("smu", "nvm")
_SMU_RELIABILITY: tuple[RecipeFamily, ...] = ("smu", "reliability")
_SAMPLING = ("generic.smu_sampling", "mosfet.id_t_sampling", "reliability.tddb_cvs", "generic.*")
_SAMPLING_KINDS = ("smu_sampling",)
_SYSTEM: tuple[RecipeFamily, ...] = ("system",)
_TABLES: tuple[RecipeFamily, ...] = ("smu", "cmu", "spgu", "wgfmu", "nvm", "reliability", "system")
"""Families whose runs archive a measurement table (``system`` since ``system.zero_check``; self-test and
self-calibration runs still archive none)."""


@dataclass(frozen=True)
class AnalysisMethod:
    """One registered method: ``fn(data, *, criteria=None, **options)``; ``recipes`` are recipe-id patterns
    (``fnmatch``, e.g. ``generic.*``) and ``kinds`` measurement kinds it applies to (``*`` = any); ``families`` the
    recipe families whose runs it serves (at least one)."""

    name: str
    status: MethodStatus
    output: MethodOutput
    summary: str
    fn: Callable[..., Any]
    families: tuple[RecipeFamily, ...]
    recipes: tuple[str, ...] = ("*",)
    kinds: tuple[str, ...] = ("*",)
    milestone: Milestone = "M1"

    def __post_init__(self) -> None:
        unknown = sorted(set(self.families) - set(FAMILIES))
        if not self.families or unknown or len(set(self.families)) != len(self.families):
            raise ValueError(f"{self.name}: families must be distinct values of {list(FAMILIES)}; got "
                             f"{list(self.families)}.")

    @property
    def options(self) -> tuple[str, ...]:
        """Option names ``run`` accepts (keyword parameters of ``fn`` except ``criteria``); empty when declared."""
        if self.status == "declared":
            return ()
        parameters = inspect.signature(self.fn).parameters.values()
        return tuple(p.name for p in parameters if p.kind is p.KEYWORD_ONLY and p.name not in _RESERVED_ARGS)

    def applies_to(self, recipe_id: str, kind: str) -> bool:
        """True when ``recipe_id`` matches one of ``recipes`` and ``kind`` one of ``kinds``."""
        return any(fnmatchcase(recipe_id, p) for p in self.recipes) and any(fnmatchcase(kind, k) for k in self.kinds)

    def run(
        self, data: RunData, options: Mapping[str, Any] | None = None, *, criteria: TrustPolicy | None = None
    ) -> MethodResult:
        """Run the method on ``data`` (see the module docstring for errors and refusals)."""
        if self.status == "declared":
            raise MethodNotImplementedError(_not_implemented_message(self.name, self.milestone))
        opts = dict(options or {})
        unknown = sorted(set(opts) - set(self.options))
        if unknown:
            raise InvalidInputError(f"{self.name} has no option(s) {unknown}; options: {list(self.options)}.")
        recipe_id, kind = data.manifest.recipe_id, data.manifest.plan.kind
        if not self.applies_to(recipe_id, kind):
            raise InvalidInputError(
                f"{self.name} does not apply to run {data.run_id} (recipe {recipe_id}, kind {kind}); it applies to "
                f"recipes {list(self.recipes)} of kinds {list(self.kinds)}."
            )
        try:
            out = self.fn(data, criteria=criteria, **opts)
        except ValidationError as exc:
            raise InvalidInputError(f"Invalid options for {self.name}: {exc}") from exc
        return [out] if isinstance(out, ExtractionResult) else out


def _not_implemented_message(name: str, milestone: str) -> str:
    implemented = sorted(n for n, m in ANALYSIS_METHODS.items() if m.status == "implemented")
    return f"Analysis method {name} is declared but not implemented yet (planned for {milestone}); implemented: " \
        f"{implemented}."


def _declared(name: str, milestone: str) -> Callable[..., Any]:
    def stub(d: RunData, **options: Any) -> MethodResult:
        raise MethodNotImplementedError(_not_implemented_message(name, milestone))

    stub.__name__ = stub.__qualname__ = name
    stub.__doc__ = f"Declared only: raises MethodNotImplementedError (code not_implemented) until {milestone}."
    return stub


def _quality_report(d: RunData, *, criteria: TrustPolicy | None = None) -> QualityReport:
    return assess_quality(d, criteria)


def _method(name: str, output: MethodOutput, fn: Callable[..., Any], summary: str, recipes: tuple[str, ...],
            kinds: tuple[str, ...] = _STAIRCASE, *, families: tuple[RecipeFamily, ...],
            milestone: Milestone = "M2") -> AnalysisMethod:
    return AnalysisMethod(name=name, status="implemented", output=output, summary=summary, fn=fn,
                          families=families, recipes=recipes, kinds=kinds, milestone=milestone)


_METHODS = [
    AnalysisMethod(
        name="quality_report", status="implemented", output="quality_report", fn=_quality_report, families=_TABLES,
        summary="Status-letter counts, trust fractions, noise and SNR per measured column; verdict ok|limited|"
                "untrusted.",
    ),
    AnalysisMethod(
        name="vth_linear_extrapolation", status="implemented", output="extraction", fn=vth_linear_extrapolation,
        families=_SMU_NVM, recipes=_TRANSFER, kinds=_STAIRCASE,
        summary="Vth = Vg-axis intercept of the tangent at max gm (or a given window) minus Vd/2.",
    ),
    _method("vth_constant_current", "extraction", vth_constant_current,
            "Vth where |Id| first reaches i_crit_a (x w_over_l when given).", _TRANSFER, families=_SMU_NVM),
    _method("vth_max_gm", "extraction", vth_max_gm,
            "Vth at the maximum of dgm/dVg (transconductance change) minus Vd/2.", _TRANSFER, families=_SMU_NVM),
    _method("subthreshold_swing", "extraction", subthreshold_swing,
            "Minimum dVg/dlog10|Id| in mV/dec over fit_points points (or `decades` decades).", _TRANSFER,
            families=_SMU_NVM),
    _method("gm_max", "extraction", gm_max, "Maximum transconductance and its gate voltage.", _TRANSFER,
            families=_SMU_NVM),
    _method("ion_ioff", "extraction", ion_ioff, "Ion at v_on, Ioff at v_off (default: sweep ends) and their ratio.",
            _TRANSFER, families=_SMU_NVM),
    _method("output_metrics", "extraction", output_metrics,
            "Output family per step: Ron at the lowest |Vd|, gds in saturation, saturation onset Vd_sat.",
            ("mosfet.idvd", "generic.*"), _SWEEPS, families=_SMU),
    _method("resistance", "extraction", resistance,
            "Resistance, linearity and offset of an I-V line; classification open|short|in_range.",
            ("basic.contact_resistor", "generic.*"), (*_STAIRCASE, *_SPOT), families=_SMU),
    _method("kelvin_resistance", "extraction", kelvin_resistance,
            "Four-wire R = slope of sensed V vs forced I, offset voltage, linearity; open|short|in_range.",
            ("resistor.kelvin_4w", "generic.*"), _SPOT, families=_SMU, milestone="M7"),
    _method("zero_floor", "extraction", zero_floor,
            "Zero check: offset and noise floor of every measured current per range; optional pass/fail limits.",
            ("system.zero_check", "generic.*"), _SPOT, families=(*_SYSTEM, *_SMU), milestone="M7"),
    _method("diode_fit", "extraction", diode_fit,
            "Diode ideality n, saturation current Is and series resistance Rs from the forward branch.",
            ("basic.diode_iv", "basic.iv_force_i", "generic.*"), families=_SMU),
    _method("forward_voltage", "extraction", forward_voltage,
            "Diode forward voltage Vf at a current (i_a or the plan parameter i_param; default 1 mA).",
            ("basic.diode_iv", "basic.iv_force_i", "generic.*"), families=_SMU, milestone="M7"),
    _method("dibl", "extraction", dibl,
            "DIBL in mV/V from constant-current Vth of transfer curves at the lowest and highest drain bias.",
            ("mosfet.idvg_family", "generic.*"), ("smu_stepped",), families=_SMU, milestone="M7"),
    _method("body_effect", "extraction", body_effect,
            "Body-effect coefficient dVth/dVsb from constant-current Vth of transfer curves at several body biases.",
            ("mosfet.body_effect", "generic.*"), ("smu_stepped",), families=_SMU, milestone="M7"),
    _method("leakage_at", "extraction", leakage_at, "|I| at bias v against limit_a; classification pass|fail.",
            ("mosfet.gate_leakage", "basic.diode_iv", "generic.*"), families=_SMU),
    _method("memory_window", "extraction", memory_window,
            "FeFET memory window Vth(fwd) - Vth(rev) of a double sweep, per-branch Vth, Ion and Ioff.",
            ("fefet.dual_sweep_mw", "generic.*"), families=_SMU_NVM),
    _method("plot_iv", "plots", plot_iv_method,
            "I-V plots (linear and/or log scale) stored as PNG files under the run folder's plots/.", ("*",),
            ("*",), families=("smu", "spgu", "wgfmu", "nvm", "reliability", "system")),
    _method("plot_timeseries", "plots", plot_timeseries_method,
            "Measured values against time t_s (else cycle or step), per phase, linear/log; PNGs under plots/.",
            ("*",), ("*",), families=_TABLES, milestone="M5"),
    _method("sampling_summary", "extraction", sampling_summary,
            "Initial/final/mean/std/drift of a sampled column vs t_s; optional stretched-exponential tau, beta.",
            _SAMPLING, _SAMPLING_KINDS, families=_SMU_RELIABILITY, milestone="M7"),
    _method("time_to_breakdown", "extraction", time_to_breakdown,
            "Time to breakdown under constant stress (compliance, current jump or threshold); censored if none.",
            _SAMPLING, _SAMPLING_KINDS, families=_SMU_RELIABILITY, milestone="M7"),
]

ANALYSIS_METHODS: Mapping[str, AnalysisMethod] = MappingProxyType({m.name: m for m in _METHODS})
"""All analysis methods by name (implemented and declared)."""


def methods_for(family: RecipeFamily) -> list[AnalysisMethod]:
    """The registered methods tagged with ``family``, in registry order."""
    if family not in FAMILIES:
        raise InvalidInputError(f"Unknown recipe family {family!r}; families: {list(FAMILIES)}.")
    return [m for m in ANALYSIS_METHODS.values() if family in m.families]


def run_method(
    name: str, data: RunData, options: Mapping[str, Any] | None = None, *, criteria: TrustPolicy | None = None
) -> MethodResult:
    """Run registered method ``name`` on ``data`` with JSON ``options`` and the recipe's trust ``criteria``."""
    method = ANALYSIS_METHODS.get(name)
    if method is None:
        raise InvalidInputError(f"Unknown analysis method {name!r}; known: {sorted(ANALYSIS_METHODS)}.")
    return method.run(data, options, criteria=criteria)
