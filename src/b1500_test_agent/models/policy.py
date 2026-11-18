"""What is allowed: the human-owned policy, DUT profiles and the hard-limit code ceiling (blueprint v1 2.5, 4.1-4.2;
v2 2.3, OD-3).

Config files: ``policy`` (``Policy``) and ``duts/<name>`` (``DutProfile``). ``Policy()`` equals the defaults of
``config/policy.example.yaml``, so a section left out of a local policy falls back to the conservative example
value. ``policy.hard_limits`` may only tighten the code ceiling; a policy above it does not validate, which the
config loader reports as ``invalid_config`` (rule R-CFG-01).

v2 sections (defaults accepted by the owner as OD-3 on 2026-11-18): ``pulse`` (soft bands for pulse sources,
R-PULSE-03), ``cmu`` (soft bands for MFCMU DC bias and AC level, R-CMU-01), ``corrections`` (which MFCMU corrections
a C-V plan needs and how old they may be, R-CORR-01) and per-family ``run_limits`` (R-RUN-01/02). DUT terminals gain
an impedance class, a minimum series resistance, a pulse envelope and an AC envelope; DUT profiles gain a geometry
used only by analyses.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import Field, model_validator

from b1500_test_agent.models.analysis import PositiveFloat, Quantity, TrustPolicy
from b1500_test_agent.models.common import ConfigName, StrictModel

HARD_CEILING_V: Final = 42.0
"""Code ceiling for |V| on any channel in v1 (blueprint 2.5); ``rules.tiers`` re-exports it."""

HARD_CEILING_A: Final = 0.1
"""Code ceiling for |compliance| in A on any channel in v1 (blueprint 2.5); ``rules.tiers`` re-exports it."""


class HardLimits(StrictModel):
    """Above these → ``blocked`` (R-LIM-02). They may only tighten the code ceiling of 42 V / 0.1 A."""

    max_abs_voltage_v: PositiveFloat = HARD_CEILING_V
    max_abs_compliance_a: PositiveFloat = HARD_CEILING_A

    @model_validator(mode="after")
    def _within_code_ceiling(self) -> HardLimits:
        if self.max_abs_voltage_v > HARD_CEILING_V:
            raise ValueError(
                f"max_abs_voltage_v {self.max_abs_voltage_v} V exceeds the code ceiling {HARD_CEILING_V} V; "
                "hard limits may only tighten it."
            )
        if self.max_abs_compliance_a > HARD_CEILING_A:
            raise ValueError(
                f"max_abs_compliance_a {self.max_abs_compliance_a} A exceeds the code ceiling {HARD_CEILING_A} A; "
                "hard limits may only tighten it."
            )
        return self


class SoftLimits(StrictModel):
    """Above these → ``needs_confirmation`` with reason ``soft_limit`` (R-LIM-03)."""

    voltage_v: PositiveFloat = 10.0
    compliance_a: PositiveFloat = 0.01


class InterlockPolicy(StrictModel):
    """|V| above ``required_above_v`` needs a closed interlock (R-IL-01)."""

    required_above_v: PositiveFloat = 42.0


class PointLimits(StrictModel):
    """Largest number of measurement points per run and measuring family (R-RUN-01). ``wgfmu`` counts points per
    channel; the module stores about 4,000,000 per channel before readback (WG Ed. 8 PDF 125)."""

    smu: int = Field(default=10001, ge=1)
    cmu: int = Field(default=10001, ge=1)
    wgfmu: int = Field(default=4_000_000, ge=1)

    def for_family(self, family: str) -> int:
        """The limit of ``family`` (``smu``, ``cmu`` or ``wgfmu``)."""
        return int(getattr(self, family))


class RunLimits(StrictModel):
    """Per-run size and duration limits (R-RUN-01, R-RUN-02).

    ``max_points``: per measuring family; a single integer (the v1 form) is still accepted and applies to every
    family (the conservative reading of a v1 policy). An estimate above ``max_sync_run_s`` runs asynchronously, above
    ``long_run_confirm_s`` it needs confirmation (``long_run``), above ``max_async_run_s`` it is blocked; every
    segment between checkpoints lasts at most ``segment_max_s``.
    """

    max_points: PointLimits = Field(default_factory=PointLimits)
    max_sync_run_s: PositiveFloat = 300
    long_run_confirm_s: PositiveFloat = 600
    max_async_run_s: PositiveFloat = 86400
    segment_max_s: PositiveFloat = 30

    @model_validator(mode="before")
    @classmethod
    def _int_max_points(cls, data: Any) -> Any:
        if isinstance(data, dict):
            points = data.get("max_points")
            if isinstance(points, int) and not isinstance(points, bool):
                data = {**data, "max_points": {"smu": points, "cmu": points, "wgfmu": points}}
        return data

    @model_validator(mode="after")
    def _ordered(self) -> RunLimits:
        if not self.segment_max_s <= self.max_sync_run_s <= self.long_run_confirm_s <= self.max_async_run_s:
            raise ValueError("run_limits must satisfy segment_max_s <= max_sync_run_s <= long_run_confirm_s <= "
                             "max_async_run_s.")
        return self


class PulsePolicy(StrictModel):
    """Soft bands for pulse sources (SPGU, SMU pulse, WGFMU): above any → ``needs_confirmation`` with reason
    ``soft_pulse`` (R-PULSE-03). ``soft_abs_v`` is the pulse amplitude at the DUT, ``soft_count`` the number of
    pulses, ``soft_on_time_s`` the total time at the pulse level, ``max_duty`` the duty cycle."""

    soft_abs_v: PositiveFloat = 5.0
    soft_count: int = Field(default=10_000, ge=1)
    soft_on_time_s: PositiveFloat = 60.0
    max_duty: float = Field(default=0.5, gt=0, le=1)


class CmuPolicy(StrictModel):
    """Soft bands for the MFCMU: |DC bias| above ``soft_dc_bias_v`` or AC level above ``soft_ac_vrms`` →
    ``needs_confirmation`` with reason ``soft_cmu`` (R-CMU-01). The module itself stops at 25 V DC and 0.25 Vrms."""

    soft_dc_bias_v: PositiveFloat = 10.0
    soft_ac_vrms: PositiveFloat = 0.05


REQUIRED_CORRECTIONS: Final[frozenset[str]] = frozenset({"phase", "open", "short"})
"""Corrections every C-V measurement needs; a policy may add ``load`` but never drop these."""


class CorrectionPolicy(StrictModel):
    """MFCMU corrections a capacitance plan needs (R-CORR-01): records of every kind in ``require`` for the bound
    MFCMU, covering every plan frequency, at most ``max_age_h`` hours old, measured with the same mainframe, pin map
    and station profile. ``require`` must contain ``phase``, ``open`` and ``short``; ``load`` may be added."""

    require: list[Literal["phase", "open", "short", "load"]] = Field(
        default_factory=lambda: ["phase", "open", "short"])
    max_age_h: PositiveFloat = 8.0

    @model_validator(mode="after")
    def _keeps_the_minimum(self) -> CorrectionPolicy:
        if len(set(self.require)) != len(self.require):
            raise ValueError("corrections.require lists a correction twice.")
        missing = sorted(REQUIRED_CORRECTIONS - set(self.require))
        if missing:
            raise ValueError(f"corrections.require must include phase, open and short (missing {missing}); it may "
                             "only add load.")
        return self


class ConfirmationPolicy(StrictModel):
    """``claude_require_user_interaction``: put ``_meta["anthropic/requiresUserInteraction"]`` on
    ``run_confirmed_plan`` (blueprint 5.1); read at MCP server start."""

    claude_require_user_interaction: bool = True


class PlanPolicy(StrictModel):
    """Stored plans expire ``ttl_h`` hours after validation (``plan_expired``)."""

    ttl_h: PositiveFloat = 24


class QualityClasses(TrustPolicy):
    """Default per-point quality classes (R-QUAL-*); ``N`` is the only ``ok`` letter."""

    ok: list[Literal["N"]] = Field(default_factory=lambda: ["N"])

    @model_validator(mode="after")
    def _only_n_is_ok(self) -> QualityClasses:
        if self.ok != ["N"]:
            raise ValueError("ok must be exactly [N].")
        return self


class Policy(StrictModel):
    """Contents of ``policy.yaml`` (blueprint 4.1); thresholds for the built-in rules."""

    hard_limits: HardLimits = Field(default_factory=HardLimits)
    soft_limits: SoftLimits = Field(default_factory=SoftLimits)
    interlock: InterlockPolicy = Field(default_factory=InterlockPolicy)
    run_limits: RunLimits = Field(default_factory=RunLimits)
    pulse: PulsePolicy = Field(default_factory=PulsePolicy)
    cmu: CmuPolicy = Field(default_factory=CmuPolicy)
    corrections: CorrectionPolicy = Field(default_factory=CorrectionPolicy)
    confirmation: ConfirmationPolicy = Field(default_factory=ConfirmationPolicy)
    plans: PlanPolicy = Field(default_factory=PlanPolicy)
    quality: QualityClasses = Field(default_factory=QualityClasses)

    @model_validator(mode="after")
    def _soft_within_hard(self) -> Policy:
        """The DC soft limits lie inside the hard limits. The pulse and CMU soft bands are not tied to them: a hard
        limit below a soft band simply blocks before the band could ask for confirmation."""
        if self.soft_limits.voltage_v > self.hard_limits.max_abs_voltage_v:
            raise ValueError("soft_limits.voltage_v must not exceed hard_limits.max_abs_voltage_v.")
        if self.soft_limits.compliance_a > self.hard_limits.max_abs_compliance_a:
            raise ValueError("soft_limits.compliance_a must not exceed hard_limits.max_abs_compliance_a.")
        return self


class TerminalPulse(StrictModel):
    """Pulse envelope of one DUT terminal (R-PULSE-02): largest |pulse level| at the DUT (V), longest pulse width
    (s), largest duty cycle and number of pulses per run. A pulse role on a terminal without one is blocked."""

    max_abs_v: PositiveFloat
    max_width_s: PositiveFloat
    max_duty: float = Field(gt=0, le=1)
    max_count: int = Field(ge=1)


class TerminalAc(StrictModel):
    """AC envelope of one DUT terminal for MFCMU measurements (R-CMU-01): largest AC level (Vrms)."""

    max_vrms: PositiveFloat


class DutTerminal(StrictModel):
    """Safe electrical envelope of one DUT terminal (blueprint v2 2.3).

    ``max_abs_v`` (V) and ``max_abs_i`` (A, also the largest compliance) bound DC sourcing (R-DUT-01).
    ``impedance`` is the human's declaration of what the terminal looks like to a source without compliance (SPGU,
    WGFMU): ``high_z`` (an insulated gate or capacitor plate: the short-circuit current bound of R-SPGU-01 becomes a
    residual shown in the summary), ``resistive`` (a conducting path whose smallest series resistance is
    ``min_series_ohm``, used for the short-circuit current ``V_open / (50 Ohm + min_series_ohm)``) or ``unknown``
    (worst case: a short). ``pulse`` and ``ac`` are the pulse and AC envelopes; ``None`` = no pulse / AC allowed.
    """

    max_abs_v: float = Field(ge=0)
    max_abs_i: PositiveFloat
    impedance: Literal["unknown", "high_z", "resistive"] = "unknown"
    min_series_ohm: float | None = Field(default=None, ge=0)
    pulse: TerminalPulse | None = None
    ac: TerminalAc | None = None


class DutGeometry(StrictModel):
    """Device geometry for analyses only (normalising currents, Cox from area, doping profiles); never used by the
    safety rules. Methods that need a field refuse without it and name it."""

    w_um: PositiveFloat | None = None
    l_um: PositiveFloat | None = None
    area_um2: PositiveFloat | None = None
    tox_nm: PositiveFloat | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> DutGeometry:
        if all(v is None for v in (self.w_um, self.l_um, self.area_um2, self.tox_nm)):
            raise ValueError("geometry needs at least one of w_um, l_um, area_um2, tox_nm (or leave it out).")
        return self


class DutProfile(StrictModel):
    """Contents of ``duts/<name>.yaml``: device type, per-terminal envelope, geometry and nominal parameters
    (R-DUT-01, R-PULSE-02, R-SPGU-01, R-CMU-01).

    A plan outside the envelope needs confirmation (``dut_envelope``); a recipe with DUT roles and no profile is
    blocked. ``nominal`` holds typical values (e.g. ``vth``) that help choose recipe parameters; they are never
    reported as measurements. ``geometry`` is used by analyses only. ``name`` is the file name without ``.yaml``.
    """

    name: ConfigName
    device_type: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    description: str = ""
    terminals: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")], DutTerminal] = Field(min_length=1)
    geometry: DutGeometry | None = None
    nominal: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")], Quantity] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
