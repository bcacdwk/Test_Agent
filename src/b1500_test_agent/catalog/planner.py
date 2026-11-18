"""Planner: request → frozen ``PlanRecord`` (blueprint 2.1, 2.6, 4.3), plus the plan store and plan identity.

Steps of ``Planner.plan`` (no instrument I/O):

1. **Resolve** parameters: request values over recipe defaults; numerically equal int/float values are coerced to
   the declared type (``101.0`` → ``101``); units come from the ``ParamSpec``. A value of the wrong type is kept as
   given (unit dropped) so that rule R-PARAM-01 reports it. ``file`` parameters are read and hashed
   (``catalog/files.py``) into ``PlanRecord.files``; an unusable file skips compilation like a wrong type.
2. **Bind** each recipe role to the pin-map terminal of the same name: a channel (with the station profile's slot,
   module type, model and alias), an MFCMU side (``7H``/``7L``), a switch output (``SEL1.OUT1``: the route for the
   role's resource and the channel wired to that input, ``None`` when unknown) or the GNDU; unmapped roles stay
   unbound (R-PIN-01 decides).
3. **Compile** through the recipe's kind (pure): envelope (incl. allowed routes), estimate, FLEX preview, program
   and the routes per phase. When parameters have the wrong type compilation is skipped (empty envelope); a kind's
   ``CompileError`` is reported as ``invalid_input`` unless R-PARAM-01 already blocks the plan (then the blocked
   plan explains it).
4. **Hash**: ``plan_hash`` = sha256 of the canonical JSON of everything except the label, rule reports, tier,
   summary and timestamps; ``plan_id`` = ``"P-" + base32(sha256 digest)[:10]``. Identical requests give the same
   plan id whatever their label, so one plan serves a die batch.
5. **Rules**: a provisional ``ok`` report is attached, the plan-phase rules run on it, and ``with_rules`` stores
   their report, tier and the canonical summary. ``expires_at`` = ``created_at`` + ``policy.plans.ttl_h``.

``PlanStore`` keeps plans as ``<state_dir>/plans/<plan_id>.json`` and re-verifies every load: a file whose content
does not hash to its plan id is ``unknown_plan`` (tampered or corrupt).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ValidationError

from b1500_test_agent.catalog.files import FileRoots, resolve_param_files
from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.catalog.schema import CompiledKindPlan, CompileError
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.errors import B1500Error, InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import ErrorCode
from b1500_test_agent.models.plan import (
    BoundChannel,
    ChannelBinding,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
    PlanRequest,
    RulesReport,
)
from b1500_test_agent.models.policy import DutProfile
from b1500_test_agent.models.recipe import FILE_PARAM_PATTERN, FUNCTION_INPUT, ParamSpec, Recipe
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.run import FaultRecord
from b1500_test_agent.models.station import (
    LiveState,
    PinMap,
    StationProfile,
    channel_slot,
    cmu_side,
    switch_target,
)
from b1500_test_agent.rules import CalibrationState, RuleContext, RulesEngine, with_rules
from b1500_test_agent.session.lock import atomic_write_json

PLAN_ID_PREFIX = "P-"
PLANS_DIR = "plans"
PLACEHOLDER_SUMMARY = "pending plan-phase rules"
_HASH_EXCLUDE = frozenset({"plan_id", "plan_hash", "rules", "tier", "summary", "created_at", "expires_at"})


class PlanError(B1500Error):
    """A stored plan cannot be used (base class; ``code`` is the result error code)."""


class UnknownPlanError(PlanError):
    """No stored plan with this id, or its content does not hash to it (tampered or corrupt)."""

    code: ClassVar[ErrorCode] = "unknown_plan"


class PlanExpiredError(PlanError):
    """The plan's time to live (``policy.plans.ttl_h``) has passed; validate again."""

    code: ClassVar[ErrorCode] = "plan_expired"


class PlanStaleError(PlanError):
    """The recipe, a config file the plan is bound to, or the backend changed since validation."""

    code: ClassVar[ErrorCode] = "plan_stale"


# -- identity --------------------------------------------------------------------------------------------------------


def canonical_content(plan: PlanRecord) -> dict[str, Any]:
    """The hashed part of a plan: everything except the label, rule reports, tier, summary and timestamps."""
    data = plan.model_dump(mode="json", exclude=set(_HASH_EXCLUDE))
    data["request"].pop("label", None)
    return data


def plan_hash_of(plan: PlanRecord) -> str:
    """sha256 (hex) of the canonical JSON of ``canonical_content(plan)`` (sorted keys, compact separators)."""
    text = json.dumps(canonical_content(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def plan_id_for(plan_hash: str) -> str:
    """``"P-"`` + the first 10 characters of the RFC 4648 base32 encoding of the hash digest."""
    return PLAN_ID_PREFIX + base64.b32encode(bytes.fromhex(plan_hash)).decode("ascii")[:10]


class PlanStore:
    """Frozen plans in ``<state_dir>/plans/<plan_id>.json``."""

    def __init__(self, state_dir: Path) -> None:
        self.dir = Path(state_dir) / PLANS_DIR

    def path(self, plan_id: str) -> Path:
        return self.dir / f"{plan_id}.json"

    def save(self, plan: PlanRecord) -> Path:
        """Store ``plan`` atomically (a re-validated identical plan replaces the older record)."""
        target = self.path(plan.plan_id)
        atomic_write_json(target, plan.model_dump(mode="json"))
        return target

    def load(self, plan_id: str) -> PlanRecord:
        """Load and re-verify a plan; raises ``UnknownPlanError`` when it is missing, corrupt or tampered."""
        if not isinstance(plan_id, str) or not plan_id.startswith(PLAN_ID_PREFIX) or len(plan_id) != 12 \
                or not plan_id[2:].isalnum():
            raise UnknownPlanError(f"{plan_id!r} is not a plan id (P- + 10 base32 characters)")
        path = self.path(plan_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise UnknownPlanError(f"unknown plan {plan_id}: validate the request first") from None
        except OSError as exc:
            raise UnknownPlanError(f"plan {plan_id} cannot be read: {exc}") from None
        try:
            plan = PlanRecord.model_validate_json(text)
        except (ValueError, ValidationError) as exc:
            raise UnknownPlanError(f"stored plan {plan_id} is corrupt ({str(exc).splitlines()[0]}); validate "
                                   "again") from None
        recomputed = plan_hash_of(plan)
        if plan.plan_id != plan_id or recomputed != plan.plan_hash or plan_id_for(recomputed) != plan_id:
            raise UnknownPlanError(f"stored plan {plan_id} does not match its hash (tampered or corrupt); validate "
                                   "again")
        return plan


# -- resolution and binding ------------------------------------------------------------------------------------------


def _is_real(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def coerce_param(spec: ParamSpec, value: Any) -> tuple[Any, bool]:
    """``(value, well_typed)``: ``value`` in the declared type when that changes nothing numerically (int ↔ float,
    ints in a float list); ``well_typed`` says whether it now matches ``spec.type`` (choices included)."""
    if spec.type == "bool":
        return value, isinstance(value, bool)
    if spec.type == "enum":
        return value, isinstance(value, str) and value in (spec.choices or [])
    if spec.type == "file":
        return value, isinstance(value, str) and FILE_PARAM_PATTERN.match(value) is not None
    if spec.type == "int":
        if isinstance(value, float) and math.isfinite(value) and value == int(value):
            value = int(value)
        return value, isinstance(value, int) and not isinstance(value, bool)
    if spec.type == "float":
        if _is_real(value):
            return float(value), True
        return value, False
    if isinstance(value, list) and value and all(_is_real(v) for v in value):
        return [float(v) for v in value], True
    return value, False


def resolve_params(recipe: Recipe, params: dict[str, Any]) -> tuple[dict[str, Quantity], list[str]]:
    """Resolved parameters (request over defaults) and the names whose values have the wrong type. Unknown request
    parameters are not resolved (R-PARAM-01 blocks them); a required parameter without a value stays missing."""
    resolved: dict[str, Quantity] = {}
    mistyped: list[str] = []
    for name, spec in recipe.params.items():
        value = params.get(name, spec.default)
        if value is None:
            continue
        value, ok = coerce_param(spec, value)
        if not ok:
            mistyped.append(name)
        try:
            resolved[name] = Quantity(value=value, unit=spec.unit if ok else None)
        except ValidationError:
            resolved[name] = Quantity(value=repr(value))
            mistyped.append(name)
    return resolved, sorted(set(mistyped))


def _bound(name: str, channel: int | None, station: StationProfile, **extra: object) -> BoundChannel:
    """A role bound to ``channel`` (module facts from the station profile), or to no channel (``extra`` = route)."""
    if channel is None:
        return BoundChannel(role=name, terminal=name, **extra)  # type: ignore[arg-type]
    module = station.module_for_channel(channel)
    return BoundChannel(
        role=name, terminal=name, channel=channel,
        slot=module.slot if module is not None else channel_slot(channel),
        module_type=module.type if module is not None else None,
        module_model=module.model if module is not None else None,
        alias=module.alias if module is not None else None,
        **extra,  # type: ignore[arg-type]
    )


def bind_roles(recipe: Recipe, pin_map: PinMap | None, station: StationProfile, pin_map_name: str) -> ChannelBinding:
    """Bind every recipe role to the pin-map terminal of the same name (unmapped roles stay unbound).

    A switch target binds the role through the route ``(switch, output, state)`` whose state is the role's resource
    (``smu``, ``pgu``, ``cmu``, ``wgfmu``); the channel is the one the station wires to that input of the switch
    port (``None`` when the switch, the output or the wiring is unknown: R-PIN-01 blocks it)."""
    roles: dict[str, BoundChannel] = {}
    for name, role in recipe.roles.items():
        target = pin_map.terminals.get(name) if pin_map is not None else None
        if target is None:
            continue
        if target == "GNDU":
            roles[name] = BoundChannel(role=name, terminal=name, gndu=True)
        elif (ref := switch_target(target)) is not None:
            via = Route(switch=ref[0], output=ref[1], state=FUNCTION_INPUT[role.function])
            switch = station.switch(via.switch)
            channel = switch.input_channel(via.output, via.state) if switch is not None else None
            roles[name] = _bound(name, channel, station, via=via)
        elif (side := cmu_side(target)) is not None:
            roles[name] = _bound(name, side[0], station, cmu_side=side[1])
        elif isinstance(target, int):
            roles[name] = _bound(name, target, station)
    return ChannelBinding(pin_map=pin_map_name, roles=roles)


def config_hashes(bundle: ConfigBundle, pin_map: str, dut_profile: str | None) -> dict[str, str]:
    """sha256 of the station, policy, pin-map and DUT-profile files the plan is bound to (missing ones omitted)."""
    hashes = {"station": bundle.sha256("station"), "policy": bundle.sha256("policy")}
    pin_file = bundle.files.get(f"pinmaps/{pin_map}")
    if pin_file is not None and pin_map in bundle.pin_maps:
        hashes["pin_map"] = pin_file.sha256
    if dut_profile is not None:
        dut_file = bundle.files.get(f"duts/{dut_profile}")
        if dut_file is not None and dut_profile in bundle.dut_profiles:
            hashes["dut_profile"] = dut_file.sha256
    return hashes


def lookup(bundle: ConfigBundle, req: PlanRequest) -> tuple[PinMap | None, DutProfile | None]:
    """The request's pin map and DUT profile from the loaded config (``None`` when absent)."""
    pin_map = bundle.pin_maps.get(req.pin_map)
    dut = bundle.dut_profiles.get(req.dut_profile) if req.dut_profile is not None else None
    return pin_map, dut


# -- planner ---------------------------------------------------------------------------------------------------------


class Planner:
    """Builds and rule-checks plans for one registry (see the module docstring)."""

    def __init__(self, registry: RecipeRegistry, *, clock: Callable[[], datetime] | None = None) -> None:
        self.registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))

    def context(self, plan: PlanRecord, bundle: ConfigBundle, *, live: LiveState | None = None,
                fault: FaultRecord | None = None, inflight_unrecovered: bool = False,
                calibration: CalibrationState | None = None) -> RuleContext:
        """The rule context of ``plan`` under ``bundle`` (recipe from the registry)."""
        recipe = self.registry.get(plan.recipe_id)
        pin_map, dut = lookup(bundle, plan.request)
        return RuleContext(
            plan=plan, recipe=recipe, effective_status=self.registry.effective_status(recipe.id, bundle.backend),
            station=bundle.station, policy=bundle.policy, pin_map=pin_map, dut=dut, live=live,
            backend=bundle.backend, fault=fault, inflight_unrecovered=inflight_unrecovered,
            calibration=calibration, recipe_source=self.registry.source(recipe.id),
        )

    def draft(self, req: PlanRequest, bundle: ConfigBundle, *, now: datetime | None = None) \
            -> tuple[PlanRecord, CompileError | None]:
        """The plan record with a provisional ``ok`` report, and the kind's compile error if any."""
        recipe = self.registry.get(req.recipe_id)
        now = now or self._clock()
        params, mistyped = resolve_params(recipe, dict(req.params))
        files = resolve_param_files(recipe, params, FileRoots.of(self.registry.root, bundle.paths.work_dir))
        mistyped = sorted({*mistyped, *(name for name, f in files.items() if f.problem is not None)})
        pin_map, _ = lookup(bundle, req)
        binding = bind_roles(recipe, pin_map, bundle.station, req.pin_map)
        kind = self.registry.kinds.get(recipe.kind)
        compiled = CompiledKindPlan(envelope=CompiledEnvelope(channels={}), estimate=Estimate(points=0, duration_s=0))
        error: CompileError | None = None
        if kind is not None and not mistyped:
            try:
                compiled = kind.compile(recipe, params, binding, bundle.station)
            except CompileError as exc:
                error = exc
            except (ValueError, TypeError) as exc:
                error = CompileError(f"{recipe.kind} cannot compile {recipe.id}: {exc}")
        report = RulesReport.from_findings("plan", [], policy_digest=bundle.sha256("policy"), evaluated_at=now)
        fields: dict[str, Any] = {
            "request": req, "recipe_id": recipe.id, "recipe_version": recipe.version, "recipe_sha": recipe.sha256,
            "kind": recipe.kind, "resolved_params": params, "binding": binding, "envelope": compiled.envelope,
            "estimate": compiled.estimate, "flex_preview": list(compiled.flex_preview),
            "hashes": config_hashes(bundle, req.pin_map, req.dut_profile), "backend": bundle.backend,
            "program": dict(compiled.program), "routes_by_phase": dict(compiled.routes_by_phase), "files": files,
            "rules": report, "tier": report.tier, "summary": PLACEHOLDER_SUMMARY,
            "created_at": now, "expires_at": now + timedelta(hours=bundle.policy.plans.ttl_h),
        }
        provisional = PlanRecord(plan_id="P-AAAAAAAAAA", plan_hash="0" * 64, **fields)
        digest = plan_hash_of(provisional)
        return PlanRecord(plan_id=plan_id_for(digest), plan_hash=digest, **fields), error

    def plan(self, req: PlanRequest, bundle: ConfigBundle, engine: RulesEngine, *, live: LiveState | None = None,
             fault: FaultRecord | None = None, inflight_unrecovered: bool = False) -> PlanRecord:
        """A rule-checked plan (not stored). Raises ``UnknownRecipeError``/``InvalidInputError`` for requests that
        cannot become a plan at all."""
        draft, error = self.draft(req, bundle)
        ctx = self.context(draft, bundle, live=live, fault=fault, inflight_unrecovered=inflight_unrecovered)
        report = engine.evaluate(ctx, "plan")
        if error is not None:
            param_blocks = [f for f in report.findings if f.rule_id == "R-PARAM-01" and f.severity == "block"]
            if not param_blocks:
                raise InvalidInputError(str(error))
        if not draft.program and report.tier != "blocked" and self.registry.effective_status(
                draft.recipe_id, bundle.backend) != "not_implemented":
            # Fail closed: an implemented kind without a program must never reach a runnable tier.
            raise InvalidInputError(f"recipe {draft.recipe_id} could not be compiled for this request")
        return with_rules(draft, report)
