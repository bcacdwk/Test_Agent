"""Recipe schema (blueprint v1 2.6, v2 2.3): parameters, roles, quality criteria, default analyses and the recipe.

A recipe is registry source YAML under ``recipes/``; ``sha256`` is computed by the registry at load (WP1.7) and is
not written in the file. Role ``settings`` values may reference parameters as ``$name``; there is no other
expression language.

v2: ``family`` files a recipe under one of seven families (the card folder); role functions cover current forcing,
synchronous and pulsed SMU roles, SPGU, WGFMU and MFCMU roles; a ``file`` parameter names a CSV waveform/table under
``recipes/waveforms/`` (committed library) or ``work/waveforms/`` (ad-hoc, always confirmed as ``adhoc_recipe``),
at most ``FILE_PARAM_MAX_BYTES``; the planner records its sha256 in the plan, so the plan hash changes with the
file content.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Final, Literal

from pydantic import Field, JsonValue, model_validator

from b1500_test_agent.models.analysis import Identifier, Provenance, TrustPolicy, Unit
from b1500_test_agent.models.common import ConfirmReason, Sha256Hex, StrictModel, ValidationStatus
from b1500_test_agent.models.routing import SwitchInput
from b1500_test_agent.models.station import SMU_TYPES, ModuleType

RecipeId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")]
"""Dotted recipe id, e.g. ``mosfet.idvg``, ``generic.smu_staircase``, ``system.self_test``."""

PARAM_REF = re.compile(r"^\$([a-z][a-z0-9_]{0,63})$")
"""A role-setting value that references a recipe parameter, e.g. ``$vg_start``."""

RoleFunction = Literal[
    "sweep_v", "bias_v", "step_v", "ground", "measure_only",
    "sweep_i", "bias_i", "step_i", "sync_v", "pulse_v", "pgu", "wgfmu", "cmu_high", "cmu_low",
]  # fmt: skip
"""What a recipe role does on its channel (v1 blueprint 2.6, v2 2.1): voltage sweep, constant voltage bias,
host-stepped voltage list, 0 V reference, measurement only; v2: current sweep, current bias, host-stepped current
list, synchronous voltage sweep (``WSV``), SMU pulse source, HV-SPGU pulse output, WGFMU channel, MFCMU High and Low
side."""

SMU_FUNCTIONS: Final[frozenset[str]] = frozenset({
    "sweep_v", "bias_v", "step_v", "ground", "measure_only", "sweep_i", "bias_i", "step_i", "sync_v", "pulse_v",
})  # fmt: skip
"""Role functions served by an SMU."""

FUNCTION_INPUT: Final[dict[str, SwitchInput]] = {
    **{f: "smu" for f in sorted(SMU_FUNCTIONS)}, "pgu": "pgu", "wgfmu": "wgfmu", "cmu_high": "cmu", "cmu_low": "cmu",
}  # fmt: skip
"""The instrument resource behind each role function, i.e. the switch input (and route state) a role needs when
its terminal is wired through a switch."""

FUNCTION_MODULE_TYPES: Final[dict[str, frozenset[str]]] = {
    **{f: SMU_TYPES for f in sorted(SMU_FUNCTIONS)}, "pgu": frozenset({"HVSPGU"}), "wgfmu": frozenset({"WGFMU"}),
    "cmu_high": frozenset({"MFCMU"}), "cmu_low": frozenset({"MFCMU"}),
}  # fmt: skip
"""Module types that can serve each role function (``RoleSpec.module_types`` must be a subset)."""

CMU_SIDES: Final[dict[str, Literal["H", "L"]]] = {"cmu_high": "H", "cmu_low": "L"}
"""MFCMU side of each MFCMU role function (pin-map target ``<channel>H`` / ``<channel>L``)."""

COMPLIANCE_FREE_FUNCTIONS: Final[frozenset[str]] = frozenset({"pgu", "wgfmu"})
"""Sources without a compliance (50 Ohm outputs): their envelope has no current limit; R-PULSE-*/R-SPGU-01/R-WG-*
bound them instead (blueprint v2 decision 9)."""

RecipeFamily = Literal["smu", "cmu", "spgu", "wgfmu", "nvm", "reliability", "system"]
"""Recipe family = card folder (blueprint v2 6.3); ``list_recipes`` filters by it."""

FILE_PARAM_DIRS: Final[dict[str, Literal["library", "work"]]] = {
    "recipes/waveforms/": "library", "work/waveforms/": "work",
}  # fmt: skip
"""Allowed homes of a ``file`` parameter's CSV: the committed waveform library (next to the recipes) and the agent's
ad-hoc folder (under the configured ``paths.work_dir``)."""

FILE_PARAM_MAX_BYTES: Final = 1_048_576
"""Largest ``file`` parameter CSV (1 MiB)."""

_FILE_SEGMENT = r"[A-Za-z0-9_-][A-Za-z0-9_.-]*"
FILE_PARAM_PATTERN = re.compile(rf"^(recipes|work)/waveforms/({_FILE_SEGMENT}/)*{_FILE_SEGMENT}\.csv$")
"""A ``file`` parameter value: ``recipes/waveforms/<name>.csv`` or ``work/waveforms/<name>.csv`` (sub-folders allowed,
POSIX separators, no ``..``, no absolute paths)."""


def file_param_origin(value: object) -> Literal["library", "work"] | None:
    """``library`` or ``work`` for a well-formed ``file`` parameter value, else ``None``."""
    if not isinstance(value, str) or not FILE_PARAM_PATTERN.match(value):
        return None
    return next(origin for prefix, origin in FILE_PARAM_DIRS.items() if value.startswith(prefix))


def _is_real(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


class ParamSpec(StrictModel):
    """One recipe parameter. ``range`` is the hard recipe envelope (R-PARAM-01); ``recommended`` is advisory and
    shown to the agent. ``default`` ``None`` means the parameter is required. A ``file`` parameter is a CSV path
    (``FILE_PARAM_PATTERN``); its default may only name a committed library file under ``recipes/waveforms/``."""

    type: Literal["float", "int", "bool", "enum", "float_list", "file"] = "float"
    unit: Unit | None = None
    default: Any = None
    recommended: tuple[float, float] | None = None
    range: tuple[float, float] | None = None
    choices: list[str] | None = None
    doc: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> ParamSpec:
        numeric = self.type in ("float", "int", "float_list")
        for name, window in (("range", self.range), ("recommended", self.recommended)):
            if window is not None:
                if not numeric:
                    raise ValueError(f"A {self.type} parameter takes no {name}.")
                if window[0] > window[1]:
                    raise ValueError(f"{name} must be [low, high].")
        if (
            self.recommended is not None
            and self.range is not None
            and not (self.range[0] <= self.recommended[0] and self.recommended[1] <= self.range[1])
        ):
            raise ValueError("recommended must lie inside range.")
        if self.unit is not None and not numeric:
            raise ValueError(f"A {self.type} parameter has no unit.")
        if (self.choices is not None) != (self.type == "enum"):
            raise ValueError("choices are required for enum parameters and allowed only there.")
        if self.choices is not None and (not self.choices or len(set(self.choices)) != len(self.choices)):
            raise ValueError("choices must be a non-empty list without duplicates.")
        if self.default is not None:
            self._check_default()
        return self

    def _check_default(self) -> None:
        value = self.default
        if self.type == "bool":
            ok = isinstance(value, bool)
        elif self.type == "enum":
            ok = isinstance(value, str) and value in (self.choices or [])
        elif self.type == "int":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif self.type == "float":
            ok = _is_real(value)
        elif self.type == "file":
            ok = file_param_origin(value) == "library"
        else:
            ok = isinstance(value, list) and all(_is_real(v) for v in value)
        if not ok:
            expected = "a recipes/waveforms/<name>.csv path" if self.type == "file" else f"type {self.type}"
            raise ValueError(f"default {value!r} does not match {expected}.")
        if self.range is not None:
            values = value if isinstance(value, list) else [value]
            if any(not self.range[0] <= v <= self.range[1] for v in values):
                raise ValueError(f"default {value!r} lies outside range {list(self.range)}.")


class RoleSpec(StrictModel):
    """One DUT role of a recipe (``gate``, ``drain`` ...); bound to the pin-map terminal of the same name.

    ``module_types`` must fit the function (SMU functions on SMUs, ``pgu`` on an HV-SPGU, ``wgfmu`` on a WGFMU,
    ``cmu_high``/``cmu_low`` on an MFCMU); R-PIN-01 refuses the GNDU for anything but a plain ``ground`` role.
    """

    function: RoleFunction
    measure: list[Literal["I", "V"]] = Field(default_factory=list)
    module_types: list[ModuleType] = Field(default_factory=list)
    prefer: ModuleType | None = None
    allow_gndu: bool = False
    optional: bool = False
    low_current: bool = False
    settings: dict[str, str | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> RoleSpec:
        if len(set(self.measure)) != len(self.measure):
            raise ValueError("measure lists a quantity twice.")
        if self.prefer is not None and self.module_types and self.prefer not in self.module_types:
            raise ValueError("prefer must be one of module_types.")
        fitting = FUNCTION_MODULE_TYPES[self.function]
        wrong = sorted(set(self.module_types) - fitting)
        if wrong:
            raise ValueError(f"a {self.function} role cannot use {wrong}; module types: {sorted(fitting)}.")
        for key, value in self.settings.items():
            if isinstance(value, str) and value.startswith("$") and not PARAM_REF.match(value):
                raise ValueError(f"settings.{key}: {value!r} is not a valid $parameter reference.")
        return self

    @property
    def resource(self) -> SwitchInput:
        """The instrument resource behind the role (``smu``, ``pgu``, ``wgfmu`` or ``cmu``)."""
        return FUNCTION_INPUT[self.function]

    def param_refs(self) -> set[str]:
        """Names of the recipe parameters referenced by ``$name`` in ``settings``."""
        refs = set()
        for value in self.settings.values():
            match = PARAM_REF.match(value) if isinstance(value, str) else None
            if match:
                refs.add(match.group(1))
        return refs


class QualityCriteria(TrustPolicy):
    """Recipe ``quality`` block: status-letter classes plus the largest tolerated share of ``limited`` points inside
    an extraction's fit window."""

    max_limited_fraction_in_fit: float = Field(default=0.05, ge=0, le=1)


class AnalysisSpec(StrictModel):
    """A default analysis run after acquisition, e.g. ``{method: vth_linear_extrapolation, options: {...}}``."""

    method: Identifier
    options: dict[str, JsonValue] = Field(default_factory=dict)


class Recipe(StrictModel):
    """A recipe (blueprint v1 2.6, v2 2.3). Every executable action, including self-test and self-calibration, is
    one. ``family`` is the card family folder it belongs to."""

    id: RecipeId
    version: int = Field(ge=1)
    title: str = Field(min_length=1)
    family: RecipeFamily
    kind: Identifier
    status: ValidationStatus
    card: str | None
    device_types: list[Identifier]
    roles: dict[Identifier, RoleSpec]
    params: dict[Identifier, ParamSpec]
    quality: QualityCriteria
    analysis_defaults: list[AnalysisSpec] = Field(default_factory=list)
    always_confirm: list[ConfirmReason] = Field(default_factory=list)
    provenance: Provenance
    preconditions: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    """What must exist before a reserved (``not_implemented``) recipe may be un-reserved: manual extraction,
    correction/SCUU/leakage flows, validation (blueprint 6.4). Shown to the agent by ``list_recipes``."""
    sha256: Sha256Hex

    @model_validator(mode="after")
    def _references_resolve(self) -> Recipe:
        for role_name, role in self.roles.items():
            missing = sorted(role.param_refs() - set(self.params))
            if missing:
                raise ValueError(f"roles.{role_name}.settings reference undeclared parameters {missing}.")
        if len(set(self.always_confirm)) != len(self.always_confirm):
            raise ValueError("always_confirm lists a reason twice.")
        return self


class RecipeSummary(StrictModel):
    """One ``list_recipes`` index entry; ``status`` is the effective status for the active backend."""

    id: RecipeId
    title: str
    family: RecipeFamily
    kind: Identifier
    status: ValidationStatus
    card: str | None
    device_types: list[Identifier] = Field(default_factory=list)
