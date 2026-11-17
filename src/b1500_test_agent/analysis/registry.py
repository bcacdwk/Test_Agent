"""Analysis method registry (blueprint 2.8 ``ANALYSIS_METHODS``) and the uniform runner used by ``analyze_run``.

``run_method(name, data, options, criteria=...)`` returns ``list[ExtractionResult]`` (extraction methods) or a
``QualityReport`` (``quality_report``). It raises ``InvalidInputError`` for an unknown method, an unknown or invalid
option, or a method that does not apply to the run's recipe/kind, and ``MethodNotImplementedError`` (code
``not_implemented``) for a method that is only declared. Refusals on untrusted data are results (``outcome``
``refused``), not exceptions. ``options`` come from JSON (``analyze_run`` ``options{}`` or a recipe's
``analysis_defaults``); the trust policy is not an option: the caller passes the recipe's ``QualityCriteria`` as
``criteria``, so only ``force`` (flagged) can override a refusal.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Any, Literal

from pydantic import ValidationError

from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.analysis.errors import MethodNotImplementedError
from b1500_test_agent.analysis.mosfet import vth_linear_extrapolation
from b1500_test_agent.analysis.quality import assess_quality
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport, TrustPolicy

MethodStatus = Literal["implemented", "declared"]
MethodOutput = Literal["quality_report", "extraction", "plots"]
MethodResult = list[ExtractionResult] | QualityReport

_RESERVED_ARGS = frozenset({"d", "criteria"})

_TRANSFER = ("mosfet.idvg", "fefet.dual_sweep_mw", "generic.*")
_STAIRCASE = ("smu_staircase",)


@dataclass(frozen=True)
class AnalysisMethod:
    """One registered method: ``fn(data, *, criteria=None, **options)``; ``recipes`` are recipe-id patterns
    (``fnmatch``, e.g. ``generic.*``) and ``kinds`` measurement kinds it applies to (``*`` = any)."""

    name: str
    status: MethodStatus
    output: MethodOutput
    summary: str
    fn: Callable[..., Any]
    recipes: tuple[str, ...] = ("*",)
    kinds: tuple[str, ...] = ("*",)
    milestone: Literal["M1", "M2"] = "M1"

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


def _declare(name: str, output: MethodOutput, summary: str, recipes: tuple[str, ...],
             kinds: tuple[str, ...] = _STAIRCASE) -> AnalysisMethod:
    return AnalysisMethod(name=name, status="declared", output=output, summary=summary, fn=_declared(name, "M2"),
                          recipes=recipes, kinds=kinds, milestone="M2")


_METHODS = [
    AnalysisMethod(
        name="quality_report", status="implemented", output="quality_report", fn=_quality_report,
        summary="Status-letter counts, trust fractions, noise and SNR per measured column; verdict ok|limited|"
                "untrusted.",
    ),
    AnalysisMethod(
        name="vth_linear_extrapolation", status="implemented", output="extraction", fn=vth_linear_extrapolation,
        recipes=_TRANSFER, kinds=_STAIRCASE,
        summary="Vth = Vg-axis intercept of the tangent at max gm (or a given window) minus Vd/2.",
    ),
    _declare("vth_constant_current", "extraction", "Vth where Id = i_crit_a (x W/L if w_over_l is given).", _TRANSFER),
    _declare("vth_max_gm", "extraction", "Vth at the gate voltage of maximum gm.", _TRANSFER),
    _declare("subthreshold_swing", "extraction", "Minimum dVg/dlog10(Id) in mV/dec (over `decades`).", _TRANSFER),
    _declare("gm_max", "extraction", "Maximum transconductance and its gate voltage.", _TRANSFER),
    _declare("ion_ioff", "extraction", "Ion at v_on, Ioff at v_off and their ratio.", _TRANSFER),
    _declare("output_metrics", "extraction", "Output family: on-resistance and output conductance gds.",
             ("mosfet.idvd", "generic.*"), ("smu_stepped", "smu_staircase")),
    _declare("resistance", "extraction", "Resistance, offset and linearity of an I-V line.",
             ("basic.contact_resistor", "generic.*")),
    _declare("diode_fit", "extraction", "Diode saturation current Is, ideality n and series resistance Rs.",
             ("basic.diode_iv", "generic.*")),
    _declare("leakage_at", "extraction", "Leakage current at bias v compared with limit_a.",
             ("mosfet.gate_leakage", "basic.diode_iv", "generic.*")),
    _declare("memory_window", "extraction", "FeFET memory window: Vth(rev) - Vth(fwd) with vth_method.",
             ("fefet.dual_sweep_mw", "generic.*")),
    _declare("plot_iv", "plots", "I-V plots (linear/log scale) of the run table as PNG files.", ("*",), ("*",)),
]

ANALYSIS_METHODS: Mapping[str, AnalysisMethod] = MappingProxyType({m.name: m for m in _METHODS})
"""All analysis methods by name (implemented and declared)."""


def run_method(
    name: str, data: RunData, options: Mapping[str, Any] | None = None, *, criteria: TrustPolicy | None = None
) -> MethodResult:
    """Run registered method ``name`` on ``data`` with JSON ``options`` and the recipe's trust ``criteria``."""
    method = ANALYSIS_METHODS.get(name)
    if method is None:
        raise InvalidInputError(f"Unknown analysis method {name!r}; known: {sorted(ANALYSIS_METHODS)}.")
    return method.run(data, options, criteria=criteria)
