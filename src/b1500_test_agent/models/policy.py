"""What is allowed: the human-owned policy, DUT profiles and the hard-limit code ceiling (blueprint 2.5, 4.1-4.2).

Config files: ``policy`` (``Policy``) and ``duts/<name>`` (``DutProfile``). ``Policy()`` equals the defaults of
``config/policy.example.yaml`` (blueprint 4.1), so a section left out of a local policy falls back to the
conservative example value. ``policy.hard_limits`` may only tighten the code ceiling; a policy above it does not
validate, which the config loader reports as ``invalid_config`` (rule R-CFG-01).
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

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


class RunLimits(StrictModel):
    """Per-run size limits (R-RUN-01): measurement points and the synchronous run-time estimate."""

    max_points: int = Field(default=10001, ge=1)
    max_sync_run_s: PositiveFloat = 300


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
    confirmation: ConfirmationPolicy = Field(default_factory=ConfirmationPolicy)
    plans: PlanPolicy = Field(default_factory=PlanPolicy)
    quality: QualityClasses = Field(default_factory=QualityClasses)

    @model_validator(mode="after")
    def _soft_within_hard(self) -> Policy:
        if self.soft_limits.voltage_v > self.hard_limits.max_abs_voltage_v:
            raise ValueError("soft_limits.voltage_v must not exceed hard_limits.max_abs_voltage_v.")
        if self.soft_limits.compliance_a > self.hard_limits.max_abs_compliance_a:
            raise ValueError("soft_limits.compliance_a must not exceed hard_limits.max_abs_compliance_a.")
        return self


class TerminalEnvelope(StrictModel):
    """Safe electrical envelope of one DUT terminal: max |V| (V) and max |I| (A, also the max compliance)."""

    max_abs_v: float = Field(ge=0)
    max_abs_i: PositiveFloat


class DutProfile(StrictModel):
    """Contents of ``duts/<name>.yaml``: device type, per-terminal envelope and nominal parameters (R-DUT-01).

    A plan outside the envelope needs confirmation (``dut_envelope``); a recipe with DUT roles and no profile is
    blocked. ``nominal`` holds typical values (e.g. ``vth``) that help choose recipe parameters; they are never
    reported as measurements. ``name`` is the file name without ``.yaml``.
    """

    name: ConfigName
    device_type: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    description: str = ""
    terminals: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")], TerminalEnvelope] = Field(min_length=1)
    nominal: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")], Quantity] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
