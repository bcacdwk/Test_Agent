"""Typed requests for fake D flows: deterministic D-atom compositions over held evidence.

D flows interpret a C flow envelope the caller already holds. They never measure, never call
A/B/C tools and never gate hardware. Every validator here runs before the first atom call, so
a violation is a ``ValidationError`` with zero atom calls (C flow precedent). Under user
decision U1 every child atom is a placeholder stub; nothing here authorizes or approves.

Contract: ``tmp/d_flow_design_arbitration.md`` sections 4-7 (request and evidence rules) and
``tmp/cd_flow_design_arbitration.md`` section 6 (designated data record and handoff states).
"""

from collections.abc import Iterable
from datetime import datetime
from math import isclose
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from b1500_test_agent.schemas.c_flow import FlowModel
from b1500_test_agent.schemas.d_atom import (
    DATA_ORIGIN_ORDER,
    ChannelRole,
    Criterion,
    DataOrigin,
    DerivativeMethod,
    ImpModel,
    ProductRef,
    Quantity,
    QuantityRange,
    SegmentRule,
    SourceRef,
    StationRef,
    Terminal,
    TrustPolicy,
    VthSpec,
    WgfmuEventSpec,
)

SCHEMA_VERSION = "d_flow/1"
FLOW_VERSION = "d_flow-placeholder-0"
MAX_UPSTREAM_EVIDENCE = 16
# A CD run archives its expect, measure and interpret children plus every upstream envelope
# (CD doc section 7). Children that can reach the archive: one C flow, and three D children
# (the expect atom, the interpreting D flow and the optional envelope-audit atom).
CD_ARCHIVED_C_FLOWS = 1
CD_ARCHIVED_D_CHILDREN = 3
# Every envelope of the largest CD run must reach the manifest (AGENTS.md audit rule), so the
# cap is derived from the CD maximums; a direct call above it is rejected, never truncated.
MAX_ARCHIVE_ENVELOPES = CD_ARCHIVED_C_FLOWS + CD_ARCHIVED_D_CHILDREN + MAX_UPSTREAM_EVIDENCE
MAX_MANIFEST_PRODUCTS = 64
MAX_TABLE_DATASETS = 16
TABLE_SOURCES = frozenset({"dataset", "view", "derived"})

# D1: the domain is the data kind; each domain admits the C flow kinds whose designated read
# record is a buffered read the matching ingest atom understands (CD doc CD6 uniform handoff).
SOURCE_DOMAIN: dict[str, str] = {"smu": "iv", "cmu": "cv", "wgfmu": "timeseries"}
DOMAIN_KINDS: dict[str, tuple[str, ...]] = {
    "iv": ("spot_smu_iv", "sweep_smu_staircase", "sweep_smu_staircase_biased", "pulse_smu_spot"),
    "cv": (
        "spot_cmu_impedance",
        "sweep_cmu_cv",
        "sweep_cmu_cf",
        "sweep_cmu_ac_level",
        "pulse_cmu_spot",
        "pulse_cmu_cv",
    ),
    "timeseries": ("waveform_wgfmu_acquire",),
}
# The ingest_cmu sweep axis implied by each admitted CMU kind; never guessed from data.
CV_SWEEP_KIND: dict[str, str] = {
    "spot_cmu_impedance": "spot",
    "sweep_cmu_cv": "voltage",
    "sweep_cmu_cf": "frequency",
    "sweep_cmu_ac_level": "ac_level",
    "pulse_cmu_spot": "spot",
    "pulse_cmu_cv": "voltage",
}
# Catalog read atoms per source: the only records that can be the designated data record.
READ_ATOMS: dict[str, frozenset[str]] = {
    "smu": frozenset({"C_atom_smu_read_measurement_data"}),
    "cmu": frozenset({"C_atom_cmu_read_measurement_data"}),
    "wgfmu": frozenset(
        {"C_atom_wgfmu_read_measurement_values", "C_atom_wgfmu_read_measurement_values_partial"}
    ),
}
USABLE_HANDOFF: frozenset[str] = frozenset({"received", "empty"})

LEAKAGE_PARAMETERS = frozenset({"leakage_current", "leakage_current_max"})
TRANSFER_ORDER: tuple[str, ...] = ("gm_max", "vth", "ss", "on_off", "voltage_shift")
TransferParameter = Literal["gm_max", "vth", "ss", "on_off", "voltage_shift"]


# ---------------------------------------------------------------------------
# Pure evidence helpers (shared by D and CD runners; no tool imports)
# ---------------------------------------------------------------------------


def c_kind(envelope: dict[str, Any]) -> str | None:
    """``<category>_<object>_<subject>`` of a C flow envelope, read from its fields."""
    parts = [envelope.get(key) for key in ("category", "object", "subject")]
    return "_".join(parts) if all(isinstance(part, str) for part in parts) else None


def evidence_origin(envelope: dict[str, Any]) -> str:
    """Data origin of one evidence envelope; unmarked evidence counts as synthetic.

    Mirrors ``d_atoms._envelope_origin`` so request validation and atoms agree.
    """
    outputs = envelope.get("outputs")
    if (
        envelope.get("fake") is True
        or envelope.get("synthetic") is True
        or envelope.get("data_origin") == "synthetic"
        or (isinstance(outputs, dict) and outputs.get("synthetic") is True)
    ):
        return "synthetic"
    if envelope.get("data_origin") == "fixture":
        return "fixture"
    if envelope.get("fake") is False and envelope.get("data_origin") in (None, "instrument"):
        return "instrument"
    return "synthetic"


def weakest(origins: list[str]) -> str:
    """Weakest-wins origin aggregation; unknown values count as synthetic."""
    known = [o if o in DATA_ORIGIN_ORDER else "synthetic" for o in origins]
    return min(known, key=DATA_ORIGIN_ORDER.index) if known else "synthetic"


def stronger(origin: str, than: str) -> bool:
    """True when ``origin`` claims more than ``than`` (instrument > fixture > synthetic)."""
    return DATA_ORIGIN_ORDER.index(origin) > DATA_ORIGIN_ORDER.index(than)


def element_count(result: Any) -> int | None:
    """Count decoded elements in one read result without reading their content."""
    if not isinstance(result, dict):
        return None
    parameters = result.get("parameters")
    payload = {**result, **parameters} if isinstance(parameters, dict) else result
    for key in ("rows", "values", "items"):
        if isinstance(payload.get(key), list):
            return len(payload[key])
    if any(isinstance(payload.get(key), dict) for key in ("sample", "measurement")):
        return 1
    return None


def locate_handoff(envelope: Any, source: str) -> dict[str, Any]:
    """Classify a C flow result and locate its designated data record (CD doc section 6).

    The designated record is the single read-phase record of the source's catalog read atom
    with status ``ok``. ``outputs.data`` is never used: it can list configuration records.
    """
    base: dict[str, Any] = {
        "state": "no_data",
        "source_atom": None,
        "atom_index": None,
        "element_count": None,
        "reason": None,
    }
    if not isinstance(envelope, dict):
        return {**base, "reason": "c_failed"}
    state = envelope.get("execution_state")
    if envelope.get("ok") is False or state == "failed":
        return {**base, "reason": "c_failed"}
    if state == "configuration_only":
        return {**base, "reason": "c_configuration_only"}
    if state == "awaiting_completion":
        return {**base, "state": "pending", "reason": "c_awaiting_completion"}
    if state != "simulated_complete":
        return {**base, "reason": "c_unknown_execution_state"}
    records = envelope.get("atom_results")
    records = records if isinstance(records, list) else []
    reads = [
        index
        for index, record in enumerate(records)
        if isinstance(record, dict)
        and record.get("atom") in READ_ATOMS.get(source, frozenset())
        and record.get("phase") == "read"
        and record.get("status") == "ok"
    ]
    if not reads:
        return {**base, "reason": "c_no_data_record"}
    if len(reads) > 1:
        return {**base, "reason": "c_ambiguous_read_records"}
    index = reads[0]
    count = element_count(records[index].get("result"))
    located = {**base, "source_atom": records[index]["atom"], "atom_index": index}
    if count is None:
        return {**located, "reason": "c_read_record_without_data"}
    return {**located, "state": "received" if count else "empty", "element_count": count}


def _close(a: float, b: float) -> bool:
    return isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def _within(value: float, low: float, high: float) -> bool:
    tolerance = 1e-12 + 1e-9 * max(abs(low), abs(high))
    return low - tolerance <= value <= high + tolerance


def _voltage_axis(c_request: dict[str, Any], what: str) -> tuple[str, float, float]:
    """Return the programmed voltage axis of a C request: ('sweep'|'point', low, high)."""
    if c_request.get("source", "voltage") != "voltage":
        raise ValueError(f"{what} needs a voltage-sourced C request; never converted or guessed.")
    if isinstance(c_request.get("start"), (int, float)) and isinstance(
        c_request.get("stop"), (int, float)
    ):
        low, high = sorted((float(c_request["start"]), float(c_request["stop"])))
        return "sweep", low, high
    for key in ("level", "pulse"):
        if isinstance(c_request.get(key), (int, float)):
            return "point", float(c_request[key]), float(c_request[key])
    raise ValueError(f"{what} cannot be checked against this C request shape; D never guesses.")


def measured_channels(c_request: dict[str, Any]) -> list[int]:
    """Measured channels of a typed C request echo, in MM order (CD doc section 8).

    The biased staircase lists them, a WGFMU waveform names one ``channel_id`` per channel,
    and every other admitted kind measures its single ``channel``. Shared by D and CD.
    """
    listed = c_request.get("measured_channels")
    if isinstance(listed, list):
        return [m["channel"] for m in listed if isinstance(m, dict) and "channel" in m]
    waveforms = c_request.get("channels")
    if isinstance(waveforms, list) and waveforms and all(isinstance(w, dict) for w in waveforms):
        return [w["channel_id"] for w in waveforms if "channel_id" in w]
    channel = c_request.get("channel")
    return [channel] if isinstance(channel, int) else []


def unmapped_channels(measured: Iterable[int], role_channels: Iterable[int]) -> list[int]:
    """Measured channels without a declared role (roles are never inferred). Shared by D and CD:
    CD rejects them; standalone D reports ``pin_map_incomplete`` and caps trust."""
    declared = set(role_channels)
    return [channel for channel in measured if channel not in declared]


def _leakage_source(c_request: dict[str, Any], channel: int) -> tuple[str, float, float, Any, str]:
    """Programmed voltage and compliance of the leakage channel: (shape, low, high, compliance,
    description). A held-bias channel is evaluated at its held level, the swept channel along
    the sweep and a spot at its level; the swept trajectory never stands in for a bias channel.
    """
    if channel not in measured_channels(c_request):
        raise ValueError(
            f"leakage.terminal is on channel {channel}, which the C request does not measure; "
            "D never guesses."
        )
    for bias in c_request.get("bias_channels") or []:
        if not isinstance(bias, dict) or bias.get("channel") != channel:
            continue
        level = bias.get("level")
        if bias.get("source", "voltage") != "voltage" or not isinstance(level, (int, float)):
            raise ValueError(
                f"Leakage screening needs a voltage-sourced channel; bias channel {channel} is "
                "not voltage-sourced (never converted or guessed)."
            )
        where = f"the held bias level {float(level)} V of channel {channel}"
        return "point", float(level), float(level), bias.get("compliance"), where
    shape, low, high = _voltage_axis(c_request, "Leakage screening")
    where = f"[{low}, {high}] V" if shape == "sweep" else f"the spot level {low} V"
    return shape, low, high, c_request.get("compliance"), where


def _below_compliance(spec: "LeakageSpec", compliance: Any) -> None:
    """CD11: at or above compliance the reading clamps, so a fail is unobservable."""
    if not isinstance(compliance, (int, float)):
        # Pydantic turns only ValueError into a ValidationError at the MCP boundary.
        raise ValueError("Leakage screening needs the channel's programmed compliance.")  # noqa: TRY004
    for index, criterion in enumerate(spec.criteria):
        for bound in (criterion.limit, criterion.limit_high):
            if bound is not None and abs(bound.value) >= compliance:
                raise ValueError(
                    f"criteria[{index}] limit {bound.value} A is not below the compliance "
                    f"{compliance} A (CD11)."
                )


def check_leakage_against_request(
    spec: "LeakageSpec", c_request: dict[str, Any], channel: int
) -> None:
    """Shared D/CD leakage rule for the channel the leakage terminal maps to.

    Bias points lie inside the sweep (swept channel) or equal the spot or held bias level;
    the window lies inside the sweep or contains that level; every limit is below that
    channel's compliance (CD11). No extrapolation, no guessed channel.
    """
    shape, low, high, compliance, where = _leakage_source(c_request, channel)
    for point in spec.bias_points_v:
        ok = _within(point, low, high) if shape == "sweep" else _close(point, low)
        if not ok:
            raise ValueError(f"bias point {point} V is not within {where}; no extrapolation.")
    if spec.window_v is not None:
        w_low, w_high = spec.window_v
        if shape == "sweep" and not (_within(w_low, low, high) and _within(w_high, low, high)):
            raise ValueError(f"window_v {spec.window_v} is not inside the sweep {where}.")
        if shape == "point" and not _within(low, w_low, w_high):
            raise ValueError(f"window_v {spec.window_v} does not contain {where}.")
    _below_compliance(spec, compliance)


def check_transfer_against_request(spec: "TransferSpec", c_request: dict[str, Any]) -> None:
    """Transfer curves need a voltage sweep; on/off gate biases stay inside it."""
    shape, low, high = _voltage_axis(c_request, "Transfer analysis")
    if shape != "sweep":
        raise ValueError("Transfer analysis needs a swept C request (start/stop).")
    if spec.on_off is not None:
        for name in ("vg_on", "vg_off"):
            value = getattr(spec.on_off, name).value
            if not _within(value, low, high):
                raise ValueError(f"on_off.{name} {value} V is outside the sweep [{low}, {high}] V.")


def _unit(name: str, value: Quantity | QuantityRange | None, allowed: set[str]) -> None:
    if value is not None and value.unit not in allowed:
        raise ValueError(f"{name} has unit {value.unit!r}; expected {sorted(allowed)} exactly.")


def _unique_role_channels(roles: list[ChannelRole]) -> None:
    channels = [role.channel for role in roles]
    if len(set(channels)) != len(channels):
        raise ValueError("channel_roles must name each channel once.")


def _require_terminals(roles: list[ChannelRole], **terminals: str) -> None:
    declared = {role.terminal for role in roles}
    for name, terminal in terminals.items():
        if terminal not in declared:
            raise ValueError(f"{name} {terminal!r} is not a declared channel role; never inferred.")


def _role_channel(roles: list[ChannelRole], terminal: str, name: str) -> int:
    channels = [role.channel for role in roles if role.terminal == terminal]
    if len(channels) != 1:
        raise ValueError(f"{name} {terminal!r} must be the role of exactly one channel.")
    return channels[0]


def envelope_products(envelopes: list[dict[str, Any]]) -> list[dict]:
    """Placeholder refs carried by D envelopes (atom ``outputs.product``, flow
    ``outputs.products``), deduplicated by id; refs are passed on, never fabricated."""
    refs: list[dict] = []
    seen: set[str] = set()
    for envelope in envelopes:
        outputs = envelope.get("outputs")
        if not isinstance(outputs, dict):
            continue
        candidates = [outputs.get("product")]
        if isinstance(outputs.get("products"), dict):
            candidates += list(outputs["products"].values())
        for ref in candidates:
            if isinstance(ref, dict) and ref.get("ref_kind") == "placeholder":
                product_id = ref.get("product_id")
                if isinstance(product_id, str) and product_id not in seen:
                    seen.add(product_id)
                    refs.append(ref)
    return refs


# ---------------------------------------------------------------------------
# Evidence (D13: a C flow envelope only, this wave)
# ---------------------------------------------------------------------------


class _Evidence(FlowModel):
    """A held C flow envelope plus caller-passed upstream A/B evidence (unverified, DF2/M6)."""

    source: str
    c_flow_envelope: dict[str, Any] = Field(
        description="The unmodified C flow envelope; D reads only its designated read record."
    )
    upstream_evidence: Annotated[list[dict[str, Any]], Field(max_length=MAX_UPSTREAM_EVIDENCE)] = (
        Field(
            default_factory=list,
            description="Caller-held A/B envelopes: evidence_unverified, never lift trust.",
        )
    )
    declared_origin: DataOrigin | None = Field(
        default=None, description="May lower the evidence origin, never raise it."
    )

    def kind(self) -> str | None:
        return c_kind(self.c_flow_envelope)

    def handoff(self) -> dict[str, Any]:
        return locate_handoff(self.c_flow_envelope, self.source)

    def origin(self) -> str:
        """Weakest of the C evidence, upstream evidence and the declared origin."""
        envelopes = [self.c_flow_envelope, *self.upstream_evidence]
        derived = weakest([evidence_origin(envelope) for envelope in envelopes])
        return weakest([derived, self.declared_origin]) if self.declared_origin else derived

    @model_validator(mode="after")
    def check_handoff(self) -> "_Evidence":
        envelope = self.c_flow_envelope
        name, kind = envelope.get("flow"), c_kind(envelope)
        if envelope.get("flow_class") != "C" or kind is None or name != f"C_flow_{kind}":
            raise ValueError("c_flow_envelope must be a C flow envelope (flow_class 'C').")
        domain = SOURCE_DOMAIN[self.source]
        if kind not in DOMAIN_KINDS[domain]:
            raise ValueError(
                f"{name} is not an admitted {domain} source; admitted: {DOMAIN_KINDS[domain]}."
            )
        if not isinstance(envelope.get("inputs"), dict):
            # Pydantic turns only ValueError into a ValidationError at the MCP boundary.
            raise ValueError("c_flow_envelope.inputs (C request echo) is required.")  # noqa: TRY004
        handoff = locate_handoff(envelope, self.source)
        if handoff["state"] not in USABLE_HANDOFF:
            raise ValueError(
                f"evidence handoff is {handoff['state']!r} ({handoff['reason']}); D runs only on "
                "a received or empty designated read record."
            )
        derived = weakest([evidence_origin(e) for e in [envelope, *self.upstream_evidence]])
        if self.declared_origin and stronger(self.declared_origin, derived):
            raise ValueError(
                f"declared_origin {self.declared_origin!r} exceeds the evidence origin {derived!r}."
            )
        return self


class IvEvidence(_Evidence):
    """SMU evidence for the ``iv`` domain."""

    source: Literal["smu"]


class CvEvidence(_Evidence):
    """MFCMU evidence for the ``cv`` domain (stub-only; real C-V waits for correction)."""

    source: Literal["cmu"]


class TimeseriesEvidence(_Evidence):
    """WGFMU evidence for the ``timeseries`` domain (stub-only; real input blocked by G4)."""

    source: Literal["wgfmu"]


# ---------------------------------------------------------------------------
# Declared analysis specs (U4: mandatory, never repo defaults)
# ---------------------------------------------------------------------------


class LeakageSpec(FlowModel):
    """Declared leakage screen: terminal, bias points and/or window, criteria and their source."""

    terminal: Terminal
    bias_points_v: Annotated[list[float], Field(max_length=256)] = Field(default_factory=list)
    window_v: tuple[float, float] | None = None
    criteria: Annotated[list[Criterion], Field(min_length=1, max_length=32)]
    criteria_source: SourceRef

    @model_validator(mode="after")
    def check_spec(self) -> "LeakageSpec":
        if not self.bias_points_v and self.window_v is None:
            raise ValueError("Declare bias_points_v, window_v or both (U4).")
        if self.window_v is not None and not self.window_v[0] < self.window_v[1]:
            raise ValueError("window_v must be (low, high) with low < high.")
        for index, criterion in enumerate(self.criteria):
            if criterion.parameter not in LEAKAGE_PARAMETERS:
                raise ValueError(f"criteria[{index}].parameter must be a leakage parameter.")
            _unit(f"criteria[{index}].limit", criterion.limit, {"A"})
            _unit(f"criteria[{index}].limit_high", criterion.limit_high, {"A"})
        return self


class SsSpec(FlowModel):
    """Declared subthreshold-swing window and minimum decades."""

    current_window: QuantityRange
    min_decades: Annotated[float, Field(gt=0, le=12)]

    @model_validator(mode="after")
    def check_units(self) -> "SsSpec":
        _unit("ss.current_window", self.current_window, {"A"})
        return self


class OnOffSpec(FlowModel):
    """Declared on and off gate biases."""

    vg_on: Quantity
    vg_off: Quantity

    @model_validator(mode="after")
    def check_units(self) -> "OnOffSpec":
        _unit("on_off.vg_on", self.vg_on, {"V"})
        _unit("on_off.vg_off", self.vg_off, {"V"})
        return self


class TransferSpec(FlowModel):
    """Declared transfer-curve parameter set; every selected parameter needs its method spec."""

    gate_terminal: Terminal
    drain_terminal: Terminal
    polarity: Literal["n", "p"]
    vds: Quantity
    parameters: Annotated[list[TransferParameter], Field(min_length=1, max_length=5)]
    derivative: DerivativeMethod | None = None
    vth: VthSpec | None = None
    ss: SsSpec | None = None
    on_off: OnOffSpec | None = None
    segments: SegmentRule | None = None
    shift_at_current: Quantity | None = None
    criteria_source: SourceRef

    def selected(self) -> list[str]:
        """Selected parameters in catalog order (request order never reorders steps)."""
        return [name for name in TRANSFER_ORDER if name in self.parameters]

    @model_validator(mode="after")
    def check_spec(self) -> "TransferSpec":
        chosen = set(self.parameters)
        if len(chosen) != len(self.parameters):
            raise ValueError("parameters must be unique.")
        if self.gate_terminal == self.drain_terminal:
            raise ValueError("gate_terminal and drain_terminal must differ.")
        _unit("vds", self.vds, {"V"})
        _unit("shift_at_current", self.shift_at_current, {"A"})
        if "gm_max" in chosen and self.derivative is None:
            raise ValueError("gm_max requires a declared derivative method.")
        if "vth" in chosen:
            if self.vth is None:
                raise ValueError("vth requires a declared Vth method (U4).")
            _unit("vth.icc", self.vth.icc, {"A"})
            if self.vth.method == "max_gm_linear_extrapolation" and self.derivative is None:
                raise ValueError("max_gm_linear_extrapolation requires a derivative method.")
        if "ss" in chosen and self.ss is None:
            raise ValueError("ss requires a declared current window and minimum decades.")
        if "on_off" in chosen and self.on_off is None:
            raise ValueError("on_off requires declared vg_on and vg_off.")
        if "voltage_shift" in chosen and (self.segments is None or self.shift_at_current is None):
            raise ValueError("voltage_shift requires segments and shift_at_current.")
        unused = {
            "vth": self.vth,
            "ss": self.ss,
            "on_off": self.on_off,
            "voltage_shift": self.shift_at_current,
        }
        for name, value in unused.items():
            if value is not None and name not in chosen:
                raise ValueError(f"A spec for unselected parameter {name!r} was declared.")
        if self.derivative is not None and not chosen & {"gm_max", "vth"}:
            raise ValueError("derivative applies only to gm_max or vth.")
        return self


# ---------------------------------------------------------------------------
# D flow requests (one required ``request`` per tool; no omitted-request default)
# ---------------------------------------------------------------------------


class DQualifyIv(FlowModel):
    """Qualify one SMU dataset: ingest, status, completeness, compliance, resolution, trust."""

    evidence: IvEvidence
    channel_roles: Annotated[list[ChannelRole], Field(min_length=1, max_length=20)]
    expectation: ProductRef | None = Field(
        default=None, description="Supplied expectation; the flow then skips build_expectation."
    )
    trust_policy: TrustPolicy = Field(default_factory=TrustPolicy)
    source_tracking_tolerance: Quantity | None = Field(
        default=None, description="P1 opt-in: runs check_source_tracking when declared (V or A)."
    )

    @model_validator(mode="after")
    def check_roles(self) -> "DQualifyIv":
        _unique_role_channels(self.channel_roles)
        _unit("source_tracking_tolerance", self.source_tracking_tolerance, {"V", "A"})
        return self


class DScreenIvLeakage(DQualifyIv):
    """Qualify, extract leakage at declared biases and check it against declared criteria."""

    leakage: LeakageSpec

    @model_validator(mode="after")
    def check_leakage(self) -> "DScreenIvLeakage":
        terminal = self.leakage.terminal
        _require_terminals(self.channel_roles, **{"leakage.terminal": terminal})
        channel = _role_channel(self.channel_roles, terminal, "leakage.terminal")
        c_request = self.evidence.c_flow_envelope["inputs"]
        check_leakage_against_request(self.leakage, c_request, channel)
        return self


class DAnalyzeIvTransfer(DQualifyIv):
    """Qualify, then extract the selected transfer parameters; never a verdict."""

    transfer: TransferSpec

    @model_validator(mode="after")
    def check_transfer(self) -> "DAnalyzeIvTransfer":
        _require_terminals(
            self.channel_roles,
            gate_terminal=self.transfer.gate_terminal,
            drain_terminal=self.transfer.drain_terminal,
        )
        check_transfer_against_request(self.transfer, self.evidence.c_flow_envelope["inputs"])
        return self


class OutputMember(FlowModel):
    """One curve-family member: its C evidence and outer-parameter value."""

    evidence: IvEvidence
    outer_value: Quantity


class DAnalyzeIvOutput(FlowModel):
    """Qualify 2..16 output curves serially, stack them and extract Ron per segment."""

    members: Annotated[list[OutputMember], Field(min_length=2, max_length=16)]
    channel_roles: Annotated[list[ChannelRole], Field(min_length=1, max_length=20)]
    trust_policy: TrustPolicy = Field(default_factory=TrustPolicy)
    outer_parameter: Terminal = Field(
        description="Name of the outer parameter (for example vgs); required by stack_family."
    )
    drain_terminal: Terminal
    ron_window: QuantityRange
    criteria_source: SourceRef

    @model_validator(mode="after")
    def check_family(self) -> "DAnalyzeIvOutput":
        _unique_role_channels(self.channel_roles)
        _require_terminals(self.channel_roles, drain_terminal=self.drain_terminal)
        _unit("ron_window", self.ron_window, {"V"})
        units = {member.outer_value.unit for member in self.members}
        if len(units) != 1 or not units <= {"V", "A"}:
            raise ValueError(f"outer_value units must be one of V or A for all members: {units}.")
        values = [member.outer_value.value for member in self.members]
        if len(set(values)) != len(values):
            raise ValueError("outer_value values must be distinct.")
        for index, member in enumerate(self.members):
            shape, _, _ = _voltage_axis(
                member.evidence.c_flow_envelope["inputs"], f"members[{index}] output curve"
            )
            if shape != "sweep":
                raise ValueError(f"members[{index}] needs a swept C request (start/stop).")
        return self


class DQualifyCv(FlowModel):
    """Qualify one MFCMU dataset (CMU stub; real C-V waits for correction/SCUU/leakage)."""

    evidence: CvEvidence
    channel_roles: Annotated[list[ChannelRole], Field(min_length=1, max_length=20)]
    expectation: ProductRef | None = None
    trust_policy: TrustPolicy = Field(default_factory=TrustPolicy)
    imp_model: ImpModel
    sweep_kind: Literal["spot", "voltage", "frequency", "ac_level"]

    @model_validator(mode="after")
    def check_cmu(self) -> "DQualifyCv":
        _unique_role_channels(self.channel_roles)
        c_request = self.evidence.c_flow_envelope["inputs"]
        if c_request.get("model") != self.imp_model:
            raise ValueError(
                f"imp_model {self.imp_model!r} does not equal the C request model "
                f"{c_request.get('model')!r} (CG2)."
            )
        expected = CV_SWEEP_KIND[self.evidence.kind() or ""]
        if self.sweep_kind != expected:
            raise ValueError(
                f"sweep_kind {self.sweep_kind!r} does not match the C flow ({expected})."
            )
        return self


class DQualifyTimeseries(FlowModel):
    """Qualify one WGFMU series (stub; real input blocked by gap G4)."""

    evidence: TimeseriesEvidence
    channel_roles: Annotated[list[ChannelRole], Field(min_length=1, max_length=20)]
    expectation: ProductRef | None = None
    trust_policy: TrustPolicy = Field(default_factory=TrustPolicy)
    measure_mode: Literal["voltage", "current"]
    event_plan: Annotated[list[WgfmuEventSpec], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def check_roles(self) -> "DQualifyTimeseries":
        _unique_role_channels(self.channel_roles)
        return self


class DArchiveRun(FlowModel):
    """Manifest plus write-once bundle plan; there are no path fields (U2, D8)."""

    envelopes: Annotated[
        list[dict[str, Any]], Field(min_length=1, max_length=MAX_ARCHIVE_ENVELOPES)
    ]
    intent: Annotated[str, Field(min_length=1, max_length=500)]
    station: StationRef | None = None
    created_at: datetime | None = None
    include_table: bool = Field(
        default=False, description="P1 opt-in: render a CSV table of the envelopes' datasets."
    )

    def manifest_products(self) -> list[dict]:
        """Refs handed to build_manifest: deduplicated, at most ``MAX_MANIFEST_PRODUCTS``."""
        return envelope_products(self.envelopes)[:MAX_MANIFEST_PRODUCTS]

    def table_datasets(self) -> list[dict]:
        """Dataset, view and derived refs handed to render_dataset_build_table."""
        refs = [r for r in self.manifest_products() if r.get("product_type") in TABLE_SOURCES]
        return refs[:MAX_TABLE_DATASETS]

    @model_validator(mode="after")
    def check_envelopes(self) -> "DArchiveRun":
        for index, envelope in enumerate(self.envelopes):
            name = envelope.get("flow") or envelope.get("atom")
            if not isinstance(name, str) or not name:
                raise ValueError(f"envelopes[{index}] names no tool (flow or atom).")
        if self.include_table and not self.table_datasets():
            raise ValueError(
                "include_table needs at least one dataset, view or derived placeholder ref "
                "among the envelopes."
            )
        return self
