"""Typed requests for fake CD flows: one C flow measurement interpreted by its D flow.

A CD request names its acquisition by a closed per-flow ``acquisition.kind`` (a discriminated
union, required, no default) whose ``request`` is the typed C flow request. Every validator
here runs before the first child call, so a violation is a ``ValidationError`` with zero child
calls. CD stays fake-only (user decision U7); nothing here authorizes or gates hardware.

Contract: ``tmp/cd_flow_design_arbitration.md`` sections 7-8 and 13 (U7, U8).
"""

from math import isclose
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from b1500_test_agent.schemas import c_flow as c
from b1500_test_agent.schemas.c_flow import FlowModel
from b1500_test_agent.schemas.d_atom import (
    ChannelRole,
    EnvelopeLimit,
    ImpModel,
    SourceRef,
    StationRef,
    TrustPolicy,
)
from b1500_test_agent.schemas.d_flow import (
    MAX_UPSTREAM_EVIDENCE,
    LeakageSpec,
    TransferSpec,
    check_leakage_against_request,
    check_transfer_against_request,
    measured_channels,
    unmapped_channels,
)

# Kinds whose C flow measures exactly one point per measured channel.
SPOT_KINDS = frozenset({"spot_smu_iv", "pulse_smu_spot", "spot_cmu_impedance", "pulse_cmu_spot"})


class _Acquisition(FlowModel):
    """One C flow selection: ``C_flow_<kind>`` is called once with ``request``."""

    def measured_channels(self) -> list[int]:
        return measured_channels(self.request.model_dump())  # type: ignore[attr-defined]

    def expected_points(self) -> int:
        return 1 if self.kind in SPOT_KINDS else self.request.steps  # type: ignore[attr-defined]


class AcqSpotSmuIv(_Acquisition):
    """``C_flow_spot_smu_iv``: one SMU source and one buffered spot read."""

    kind: Literal["spot_smu_iv"]
    request: c.SmuSpot


class AcqSweepSmuStaircase(_Acquisition):
    """``C_flow_sweep_smu_staircase``: one swept SMU channel and one buffered read."""

    kind: Literal["sweep_smu_staircase"]
    request: c.SmuSweep


class AcqPulseSmuSpot(_Acquisition):
    """``C_flow_pulse_smu_spot``: one pulsed SMU spot and one buffered read."""

    kind: Literal["pulse_smu_spot"]
    request: c.SmuPulse


class AcqSweepSmuStaircaseBiased(_Acquisition):
    """``C_flow_sweep_smu_staircase_biased``: swept channel, held biases, listed measured
    channels and one buffered read (U8 anchor for transfer curves)."""

    kind: Literal["sweep_smu_staircase_biased"]
    request: c.BiasedSweep


class AcqSpotCmuImpedance(_Acquisition):
    """``C_flow_spot_cmu_impedance`` (CMU stub)."""

    kind: Literal["spot_cmu_impedance"]
    request: c.CmuSetup


class AcqSweepCmuCv(_Acquisition):
    """``C_flow_sweep_cmu_cv`` (CMU stub; endpoints in V)."""

    kind: Literal["sweep_cmu_cv"]
    request: c.CmuSweep


class AcqSweepCmuCf(_Acquisition):
    """``C_flow_sweep_cmu_cf`` (CMU stub; positive endpoints in Hz, C schema)."""

    kind: Literal["sweep_cmu_cf"]
    request: c.CmuPositiveSweep


class AcqSweepCmuAcLevel(_Acquisition):
    """``C_flow_sweep_cmu_ac_level`` (CMU stub; positive endpoints in V, C schema)."""

    kind: Literal["sweep_cmu_ac_level"]
    request: c.CmuPositiveSweep


class AcqPulseCmuSpot(_Acquisition):
    """``C_flow_pulse_cmu_spot`` (CMU stub)."""

    kind: Literal["pulse_cmu_spot"]
    request: c.CmuPulse


class AcqPulseCmuCv(_Acquisition):
    """``C_flow_pulse_cmu_cv`` (CMU stub)."""

    kind: Literal["pulse_cmu_cv"]
    request: c.CmuPulseSweep


IvQualifyAcquisition = Annotated[
    AcqSpotSmuIv | AcqSweepSmuStaircase | AcqPulseSmuSpot, Field(discriminator="kind")
]
IvLeakageAcquisition = Annotated[AcqSpotSmuIv | AcqSweepSmuStaircase, Field(discriminator="kind")]
CvQualifyAcquisition = Annotated[
    AcqSpotCmuImpedance
    | AcqSweepCmuCv
    | AcqSweepCmuCf
    | AcqSweepCmuAcLevel
    | AcqPulseCmuSpot
    | AcqPulseCmuCv,
    Field(discriminator="kind"),
]


class EnvelopeSpec(FlowModel):
    """P1 opt-in post-hoc audit envelope; escalates only, never a safety gate."""

    limits: Annotated[list[EnvelopeLimit], Field(min_length=1, max_length=32)]
    criteria_source: SourceRef

    @model_validator(mode="after")
    def check_units(self) -> "EnvelopeSpec":
        for index, limit in enumerate(self.limits):
            unit = "V" if limit.quantity == "voltage" else "A"
            for bound in (limit.low, limit.high):
                if bound is not None and bound.unit != unit:
                    raise ValueError(f"limits[{index}] {limit.quantity} bounds must be in {unit}.")
        return self


class CdBase(FlowModel):
    """Shared CD request fields; ``acquisition`` is declared by each concrete request."""

    channel_roles: Annotated[list[ChannelRole], Field(min_length=1, max_length=20)]
    upstream_evidence: Annotated[list[dict[str, Any]], Field(max_length=MAX_UPSTREAM_EVIDENCE)] = (
        Field(
            default_factory=list,
            description="Caller-held A/B envelopes; marked evidence_unverified, never lift trust.",
        )
    )
    trust_policy: TrustPolicy = Field(default_factory=TrustPolicy)
    envelope: EnvelopeSpec | None = Field(
        default=None, description="P1 opt-in: D_atom_assess_dataset_check_envelope after interpret."
    )
    intent_note: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    station: StationRef | None = None

    def role_channels_allowed(self) -> set[int]:
        """Roles may name only measured channels (CD doc section 8)."""
        return set(self.acquisition.measured_channels())  # type: ignore[attr-defined]

    def role_of(self, channel: int) -> str | None:
        return next((r.terminal for r in self.channel_roles if r.channel == channel), None)

    @model_validator(mode="after")
    def check_acquisition_and_roles(self) -> "CdBase":
        acquisition = self.acquisition  # type: ignore[attr-defined]
        run = acquisition.request.run
        if not run.collect:
            raise ValueError("acquisition.request.run.collect must be true; D needs the read.")
        measured = acquisition.measured_channels()
        needed = acquisition.expected_points() * len(measured)
        if run.max_items < needed:
            raise ValueError(
                f"run.max_items {run.max_items} is below expected points x measured channels "
                f"({needed})."
            )
        channels = [role.channel for role in self.channel_roles]
        if len(set(channels)) != len(channels):
            raise ValueError("channel_roles must name each channel once.")
        missing = unmapped_channels(measured, channels)
        if missing:
            raise ValueError(f"Measured channels {missing} have no declared role; never inferred.")
        extra = sorted(set(channels) - self.role_channels_allowed())
        if extra:
            raise ValueError(f"channel_roles name channels {extra} the acquisition does not use.")
        for index, evidence in enumerate(self.upstream_evidence):
            # The archive phase records every upstream envelope by tool name (DArchiveRun);
            # an anonymous one would only fail there, after the C flow has measured.
            name = evidence.get("flow") or evidence.get("atom")
            if not isinstance(name, str) or not name:
                raise ValueError(f"upstream_evidence[{index}] names no tool (flow or atom).")
        terminals = {role.terminal for role in self.channel_roles}
        for limit in self.envelope.limits if self.envelope else []:
            if limit.terminal is not None and limit.terminal not in terminals:
                raise ValueError(f"envelope terminal {limit.terminal!r} is not a declared role.")
        return self


class CdQualifyIv(CdBase):
    """Measure one SMU IV dataset (spot, staircase or pulsed spot) and qualify it."""

    acquisition: IvQualifyAcquisition


class CdScreenIvLeakage(CdBase):
    """Measure a voltage-sourced spot or staircase and screen its leakage."""

    acquisition: IvLeakageAcquisition
    leakage: LeakageSpec

    @model_validator(mode="after")
    def check_leakage(self) -> "CdScreenIvLeakage":
        request = self.acquisition.request
        if request.source != "voltage":
            raise ValueError("Leakage screening needs a voltage source.")
        if request.ranging.measure_function != "current":
            raise ValueError("Leakage screening needs ranging.measure_function 'current'.")
        if self.leakage.terminal != self.role_of(request.channel):
            raise ValueError("leakage.terminal must be the role of the measured channel.")
        # Shared with D: bias points, window and limit < compliance (CD11) for this channel.
        check_leakage_against_request(self.leakage, request.model_dump(), request.channel)
        return self


class CdAnalyzeIvTransfer(CdBase):
    """Measure a gate sweep with held drain bias (biased staircase) and analyze the transfer."""

    acquisition: AcqSweepSmuStaircaseBiased
    transfer: TransferSpec

    def role_channels_allowed(self) -> set[int]:
        """Roles may name the swept, bias and measured channels of the biased staircase."""
        request = self.acquisition.request
        return {request.channel, *(b.channel for b in request.bias_channels)} | set(
            self.acquisition.measured_channels()
        )

    @model_validator(mode="after")
    def check_transfer(self) -> "CdAnalyzeIvTransfer":
        request = self.acquisition.request
        t = self.transfer
        if request.source != "voltage":
            raise ValueError("Transfer analysis needs a voltage-swept gate.")
        if t.gate_terminal != self.role_of(request.channel):
            raise ValueError("transfer.gate_terminal must be the role of the swept channel.")
        drains = [r.channel for r in self.channel_roles if r.terminal == t.drain_terminal]
        if len(drains) != 1:
            raise ValueError("transfer.drain_terminal must be the role of exactly one channel.")
        bias = {b.channel: b for b in request.bias_channels}.get(drains[0])
        if bias is None or bias.source != "voltage":
            raise ValueError("transfer.drain_terminal must be a voltage-biased channel.")
        measured = {m.channel: m for m in request.measured_channels}.get(drains[0])
        if measured is None or measured.ranging.measure_function != "current":
            raise ValueError("The drain channel must be measured with measure_function 'current'.")
        if not isclose(t.vds.value, bias.level, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"transfer.vds {t.vds.value} V must equal the drain bias {bias.level} V."
            )
        check_transfer_against_request(t, request.model_dump())
        return self


class CdQualifyCv(CdBase):
    """Measure one MFCMU dataset and qualify it (fake-only; CMU real use blocked)."""

    acquisition: CvQualifyAcquisition
    imp_model: ImpModel

    @model_validator(mode="after")
    def check_imp_model(self) -> "CdQualifyCv":
        if self.imp_model != self.acquisition.request.model:
            raise ValueError(
                f"imp_model {self.imp_model!r} must equal acquisition.request.model "
                f"{self.acquisition.request.model!r} (CG2)."
            )
        return self
