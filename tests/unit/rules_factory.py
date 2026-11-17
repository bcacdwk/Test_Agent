"""In-test fixture factory for the rules, tier and plan-summary tests.

Builds recipes, pin maps, DUT profiles, config bundles, plan records (with a minimal stand-in for the WP1.7 planner:
bind roles through the pin map, compile a per-channel envelope from ``$param`` role settings) and rule contexts.
Everything is constructed in memory; nothing is written to ``config/local/``. Bundles name their files as
``config/local/<key>.yaml`` (or the committed ``*.example.yaml`` paths) so that finding sources can be asserted.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from b1500_test_agent.config import ConfigBundle, load_yaml
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import Backend, ConfigFile, ConfigSource, ValidationStatus
from b1500_test_agent.models.plan import (
    BoundChannel,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
    PlanRequest,
    RulesReport,
)
from b1500_test_agent.models.policy import DutProfile, Policy, TerminalEnvelope
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.models.run import FaultRecord
from b1500_test_agent.models.station import (
    Identity,
    InstalledModule,
    InstrumentError,
    LiveState,
    ModuleInventory,
    PinMap,
    Settings,
    StationProfile,
    StatusByte,
    channel_slot,
)
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules.engine import CalibrationState, RuleContext, RulesEngine
from tests.unit.helpers import CONFIG_DIR, REPO_ROOT

T0 = datetime(2026, 11, 17, 6, 30, 12, tzinfo=UTC)
ZERO_SHA = "0" * 64


def sha(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# -- Config models ---------------------------------------------------------------------------------------------------


def example_station() -> StationProfile:
    """The committed example station: SMU1/SMU2 MPSMU (slots 1-2), SMU3/SMU4 HRSMU (3-4), WGFMU 5, SPGU 6, CMU 7."""
    raw = (CONFIG_DIR / "station.example.yaml").read_bytes()
    return StationProfile.model_validate(load_yaml(raw))


def station(**changes: Any) -> StationProfile:
    """The example station with top-level fields replaced (``modules``, ``interlock``, ``corrections`` ...)."""
    data = example_station().model_dump(mode="json")
    data.update(changes)
    return StationProfile.model_validate(data)


def pin_map(name: str = "mosfet-4t", certainty: str = "verified", **terminals: Any) -> PinMap:
    """``mosfet-4t`` (gate 1, drain 3, source/bulk GNDU) with terminals replaced (``None`` = not connected); use
    ``pin_map_exact`` to leave a terminal out entirely."""
    mapping: dict[str, Any] = {"gate": 1, "drain": 3, "source": "GNDU", "bulk": "GNDU"}
    mapping.update(terminals)
    return PinMap(name=name, certainty=certainty, terminals=mapping)


def pin_map_exact(name: str, terminals: Mapping[str, Any], certainty: str = "verified") -> PinMap:
    return PinMap(name=name, certainty=certainty, terminals=dict(terminals))


def dut(name: str = "nmos-generic", device_type: str = "nmos", **terminals: tuple[float, float]) -> DutProfile:
    """``nmos-generic`` (gate/drain 3 V 1 mA, source/bulk 1 V 1 mA) with terminals replaced by ``(max_v, max_i)``."""
    limits = {"gate": (3.0, 1e-3), "drain": (3.0, 1e-3), "source": (1.0, 1e-3), "bulk": (1.0, 1e-3)}
    limits.update(terminals)
    return DutProfile(
        name=name,
        device_type=device_type,
        terminals={t: TerminalEnvelope(max_abs_v=v, max_abs_i=i) for t, (v, i) in limits.items()},
    )


def wide_dut(name: str = "wide", terminals: Iterable[str] = ("gate", "drain", "source", "bulk", "force")) -> DutProfile:
    """A DUT profile whose envelope (100 V, 1 A) never limits, to isolate policy bands."""
    return DutProfile(name=name, device_type="nmos",
                      terminals={t: TerminalEnvelope(max_abs_v=100.0, max_abs_i=1.0) for t in terminals})


# -- Recipes ---------------------------------------------------------------------------------------------------------

IDVG: dict[str, Any] = {
    "id": "mosfet.idvg",
    "version": 1,
    "title": "MOSFET transfer curve",
    "kind": "smu_staircase",
    "status": "sim_validated",
    "card": None,
    "device_types": ["nmos", "pmos", "igzo_tft"],
    "roles": {
        "gate": {"function": "sweep_v", "measure": ["I"], "module_types": ["MPSMU", "HRSMU", "HPSMU"],
                 "settings": {"start": "$vg_start", "stop": "$vg_stop", "points": "$vg_points",
                              "icomp": "$icomp_gate"}},
        "drain": {"function": "bias_v", "measure": ["I"], "module_types": ["MPSMU", "HRSMU", "HPSMU"],
                  "prefer": "HRSMU", "settings": {"v": "$vd", "icomp": "$icomp_drain"}},
        "source": {"function": "ground", "allow_gndu": True},
    },
    "params": {
        "vg_start": {"unit": "V", "default": -1.0, "recommended": [-2, 0], "range": [-10, 10]},
        "vg_stop": {"unit": "V", "default": 3.0, "recommended": [1, 5], "range": [-10, 10]},
        "vg_points": {"type": "int", "default": 101, "range": [11, 1001]},
        "vd": {"unit": "V", "default": 0.05, "recommended": [0.02, 0.1], "range": [-5, 5]},
        "icomp_gate": {"unit": "A", "default": 1.0e-6, "range": [1.0e-12, 1.0e-3]},
        "icomp_drain": {"unit": "A", "default": 1.0e-3, "range": [1.0e-12, 1.0e-2]},
        "integration": {"type": "enum", "choices": ["short", "medium", "long"], "default": "medium"},
    },
    "quality": {"limited": ["C", "T"], "untrusted": ["V", "X", "F", "D", "G", "S", "U"],
                "max_limited_fraction_in_fit": 0.05},
    "analysis_defaults": [{"method": "vth_linear_extrapolation", "options": {"window": "max_gm"}}],
    "provenance": {"sources": ["deck slide 6"], "validation_runs": []},
}
"""The blueprint 2.6 recipe example (``mosfet.idvg``)."""

IDVD: dict[str, Any] = {
    **copy.deepcopy(IDVG),
    "id": "mosfet.idvd",
    "title": "MOSFET output curve",
    "kind": "smu_stepped",
    "roles": {
        "drain": {"function": "sweep_v", "measure": ["I"], "module_types": ["MPSMU", "HRSMU", "HPSMU"],
                  "settings": {"start": "$vd_start", "stop": "$vd_stop", "points": "$vd_points",
                               "icomp": "$icomp_drain"}},
        "gate": {"function": "step_v", "measure": ["I"], "module_types": ["MPSMU", "HRSMU", "HPSMU"],
                 "settings": {"start": "$vg_start", "stop": "$vg_stop", "icomp": "$icomp_gate"}},
        "source": {"function": "ground", "allow_gndu": True},
    },
    "params": {
        "vd_start": {"unit": "V", "default": 0.0, "range": [-10, 10]},
        "vd_stop": {"unit": "V", "default": 3.0, "range": [-10, 10]},
        "vd_points": {"type": "int", "default": 61, "range": [11, 1001]},
        "vg_start": {"unit": "V", "default": 0.0, "range": [-10, 10]},
        "vg_stop": {"unit": "V", "default": 2.0, "range": [-10, 10]},
        "icomp_drain": {"unit": "A", "default": 2.0e-2, "range": [1.0e-12, 1.0e-1]},
        "icomp_gate": {"unit": "A", "default": 1.0e-6, "range": [1.0e-12, 1.0e-3]},
    },
}
"""An Id-Vd recipe shaped like the blueprint 2.5 summary example (drain sweep 0..3 V at 20 mA, gate step 0..2 V)."""

FORCE: dict[str, Any] = {
    **copy.deepcopy(IDVG),
    "id": "generic.smu_force",
    "title": "One forced channel against ground (wide ranges for limit tests)",
    "device_types": [],
    "roles": {
        "force": {"function": "bias_v", "measure": ["I"], "settings": {"v": "$v", "icomp": "$icomp"}},
        "source": {"function": "ground", "allow_gndu": True},
    },
    "params": {
        "v": {"unit": "V", "default": 1.0, "range": [-1000, 1000]},
        "icomp": {"unit": "A", "default": 1.0e-3, "range": [1.0e-12, 10.0]},
    },
    "analysis_defaults": [],
}
"""A one-channel bias recipe whose parameter ranges never limit, to isolate module, policy and DUT bands."""

SYSTEM: dict[str, Any] = {
    **copy.deepcopy(IDVG),
    "id": "system.self_test",
    "title": "Instrument self-test",
    "kind": "system",
    "device_types": [],
    "roles": {},
    "params": {},
    "analysis_defaults": [],
    "always_confirm": ["system_self_test"],
}

CMU: dict[str, Any] = {
    **copy.deepcopy(IDVG),
    "id": "mosfet.cgg_cv",
    "title": "Gate capacitance (declared)",
    "kind": "cmu_cv",
    "status": "not_implemented",
    "roles": {"gate": {"function": "sweep_v", "measure": [], "module_types": ["MFCMU"],
                       "settings": {"start": "$vg_start", "stop": "$vg_stop", "icomp": "$icomp_gate"}}},
    "params": {
        "vg_start": {"unit": "V", "default": -1.0, "range": [-10, 10]},
        "vg_stop": {"unit": "V", "default": 1.0, "range": [-10, 10]},
        "icomp_gate": {"unit": "A", "default": 1.0e-3, "range": [1.0e-12, 1.0e-1]},
        "freq": {"unit": "Hz", "default": 1.0e6, "range": [1.0e3, 5.0e6]},
    },
    "analysis_defaults": [],
}


def recipe(base: Mapping[str, Any] = IDVG, **changes: Any) -> Recipe:
    """A recipe from ``base`` with top-level fields replaced; ``sha256`` is derived from the content."""
    data = copy.deepcopy(dict(base))
    data.update(copy.deepcopy(changes))
    data.pop("sha256", None)
    data["sha256"] = sha(data)
    return Recipe.model_validate(data)


def recipe_with_role(base: Mapping[str, Any], role: str, **changes: Any) -> Recipe:
    """A recipe from ``base`` with fields of one role replaced (``settings`` replaces the whole mapping)."""
    data = copy.deepcopy(dict(base))
    data["roles"][role].update(copy.deepcopy(changes))
    return recipe(data)


# -- Config bundle ---------------------------------------------------------------------------------------------------


def _file_path(key: str, source: ConfigSource) -> str:
    if source == "example":
        return f"config/{key}.example.yaml"
    return f"config/local/{key}.yaml"


def bundle(
    *,
    policy: Policy | None = None,
    station_profile: StationProfile | None = None,
    pin_maps: Iterable[PinMap] = (),
    duts: Iterable[DutProfile] = (),
    backend: Backend = "sim",
    source: ConfigSource = "local",
    paths: Paths | None = None,
) -> ConfigBundle:
    """A config bundle built in memory, as the loader would return it for files at ``config/local/`` (or the
    committed example paths with ``source="example"``)."""
    settings = Settings(backend=backend)
    policy = policy if policy is not None else Policy()
    station_profile = station_profile if station_profile is not None else example_station()
    pin_maps = list(pin_maps)
    duts = list(duts)
    items: list[tuple[str, Any]] = [("settings", settings), ("station", station_profile), ("policy", policy)]
    items += [(f"pinmaps/{p.name}", p) for p in pin_maps]
    items += [(f"duts/{d.name}", d) for d in duts]
    files = {
        key: ConfigFile(key=key, path=_file_path(key, source), source=source,
                        sha256=sha(model.model_dump(mode="json")))
        for key, model in items
    }
    return ConfigBundle(
        paths=paths if paths is not None else Paths.from_env({}, repo_root=REPO_ROOT),
        settings=settings,
        station=station_profile,
        policy=policy,
        pin_maps={p.name: p for p in pin_maps},
        dut_profiles={d.name: d for d in duts},
        sim_scenario=None,
        files=files,
        backend_reason="test bundle",
        warnings=[],
        digest=sha({k: f.sha256 for k, f in files.items()}),
    )


# -- Plans -----------------------------------------------------------------------------------------------------------


def _setting(settings: Mapping[str, Any], key: str, resolved: Mapping[str, Quantity], default: float = 0.0) -> Any:
    raw = settings.get(key, default)
    if isinstance(raw, str) and raw.startswith("$"):
        quantity = resolved.get(raw[1:])
        return default if quantity is None else quantity.value
    return raw


def compile_plan(
    rec: Recipe,
    pm: PinMap | None,
    station_profile: StationProfile,
    *,
    pin_map_name: str | None = None,
    params: Mapping[str, Any] | None = None,
    request_params: Mapping[str, Any] | None = None,
    resolved_override: Mapping[str, Quantity] | None = None,
    dut_profile: str | None = "nmos-generic",
    backend: Backend = "sim",
    points: int | None = None,
    duration_s: float = 1.0,
    extra_envelope: Mapping[int, ChannelEnvelope] | None = None,
    drop_envelope: Iterable[int] = (),
    label: str | None = "W3-D12 batch",
    created_at: datetime = T0,
) -> PlanRecord:
    """A plan record as the planner would build it, with a provisional (empty, ``ok``) plan-phase report."""
    params = dict(params or {})
    resolved: dict[str, Quantity] = {}
    for name, spec in rec.params.items():
        value = params.get(name, spec.default)
        if value is not None:
            resolved[name] = Quantity(value=value, unit=spec.unit)
    if resolved_override is not None:
        resolved.update(resolved_override)
    name = pm.name if pm is not None else (pin_map_name or "mosfet-4t")
    roles: dict[str, BoundChannel] = {}
    for role_name in rec.roles:
        target = pm.terminals.get(role_name) if pm is not None else None
        if target is None:
            continue
        if target == "GNDU":
            roles[role_name] = BoundChannel(role=role_name, terminal=role_name, gndu=True)
            continue
        module = station_profile.module_for_channel(target)
        roles[role_name] = BoundChannel(
            role=role_name, terminal=role_name, channel=target,
            slot=module.slot if module else channel_slot(target),
            module_type=module.type if module else None, module_model=module.model if module else None,
            alias=module.alias if module else None,
        )
    channels: dict[int, ChannelEnvelope] = {}
    sweep_points = 1
    for role_name, bound in roles.items():
        if bound.channel is None:
            continue
        spec = rec.roles[role_name]
        icomp = abs(float(_setting(spec.settings, "icomp", resolved)))
        if spec.function in ("sweep_v", "step_v"):
            start = float(_setting(spec.settings, "start", resolved))
            stop = float(_setting(spec.settings, "stop", resolved))
            if spec.function == "sweep_v":
                sweep_points = max(sweep_points, int(_setting(spec.settings, "points", resolved, 1)))
        elif spec.function == "bias_v":
            start = stop = float(_setting(spec.settings, "v", resolved))
        else:
            start = stop = 0.0
        channels[bound.channel] = ChannelEnvelope(role=role_name, max_abs_v=max(abs(start), abs(stop)),
                                                  max_abs_i=icomp, function=spec.function, v_start=start,
                                                  v_stop=stop)
    for channel in drop_envelope:
        channels.pop(channel, None)
    channels.update(extra_envelope or {})
    report = RulesReport.from_findings("plan", [], policy_digest=ZERO_SHA, evaluated_at=created_at)
    request = PlanRequest(recipe_id=rec.id, params=dict(request_params if request_params is not None else params),
                          pin_map=name, dut_profile=dut_profile, label=label)
    return PlanRecord(
        plan_id="P-ABCDEFGH23",
        plan_hash="a" * 64,
        request=request,
        recipe_id=rec.id,
        recipe_version=rec.version,
        recipe_sha=rec.sha256,
        kind=rec.kind,
        resolved_params=resolved,
        binding=ChannelBinding(pin_map=name, roles=roles),
        envelope=CompiledEnvelope(channels=channels),
        estimate=Estimate(points=points if points is not None else sweep_points, duration_s=duration_s),
        flex_preview=[],
        hashes={"station": ZERO_SHA, "policy": ZERO_SHA, "pin_map": ZERO_SHA, "dut_profile": ZERO_SHA},
        backend=backend,
        rules=report,
        tier=report.tier,
        summary="pending",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=24),
    )


# -- Live state ------------------------------------------------------------------------------------------------------


def live_state(
    station_profile: StationProfile | None = None,
    *,
    backend: Backend = "sim",
    stb: int | None = 0,
    errors: Iterable[tuple[int, str]] = (),
    slots: Mapping[int, str | None] | None = None,
    model: str | None = "B1500A",
    inventory: bool = True,
) -> LiveState:
    """A snapshot matching ``station_profile`` (inventory per slot, ``slots`` overrides; ``None`` = empty slot)."""
    station_profile = station_profile or example_station()
    installed = {m.slot: m.model for m in station_profile.modules}
    installed.update(slots or {})
    modules = [InstalledModule(slot=s, model=m, revision="0") for s, m in sorted(installed.items()) if m]
    identity = None if model is None else Identity(vendor="Keysight Technologies", model=model, serial="SIM1",
                                                   firmware="A.06", raw=f"Keysight Technologies,{model},SIM1,A.06")
    return LiveState(
        backend=backend,
        resource="SIM::test",
        taken_at=T0,
        identity=identity,
        inventory=ModuleInventory(modules=modules) if inventory else None,
        errors=[InstrumentError(code=c, message=m) for c, m in errors],
        status_byte=None if stb is None else StatusByte(value=stb),
    )


CALIBRATED = CalibrationState(auto_calibration=True, last_self_calibration=T0 - timedelta(days=1),
                              last_self_calibration_run="S20261116T063012Z-00ab")


# -- Contexts --------------------------------------------------------------------------------------------------------


def context(
    *,
    rec: Recipe | None = None,
    pm: PinMap | None | str = "default",
    plan_pin_map: PinMap | None = None,
    du: DutProfile | None | str = "default",
    dut_profile: str | None = "default",
    cfg_policy: Policy | None = None,
    ctx_policy: Policy | None = None,
    station_profile: StationProfile | None = None,
    backend: Backend = "sim",
    cfg_backend: Backend | None = None,
    source: ConfigSource = "local",
    effective_status: ValidationStatus | None = None,
    live: LiveState | None = None,
    fault: FaultRecord | None = None,
    inflight_unrecovered: bool = False,
    calibration: CalibrationState | None = None,
    recipe_source: str | None = None,
    **plan_kwargs: Any,
) -> tuple[ConfigBundle, RuleContext]:
    """A bundle and rule context for one plan. Defaults: ``mosfet.idvg`` on pin map ``mosfet-4t`` (verified) with
    DUT ``nmos-generic`` on the example station, sim backend, effective status = recipe status: tier ``ok``.

    ``pm``/``du``: ``"default"`` = the standard object, ``None`` = the request names one that does not exist.
    ``plan_pin_map`` compiles the plan from a different pin map than the one in the config (binding mismatch).
    """
    rec = rec or recipe()
    station_profile = station_profile or example_station()
    pin = pin_map() if pm == "default" else pm
    device = dut() if du == "default" else du
    assert not isinstance(pin, str) and not isinstance(device, str)
    if dut_profile == "default":
        dut_profile = device.name if device is not None else "nmos-generic"
    pin_name = pin.name if pin is not None else plan_kwargs.pop("pin_map_name", "ghost-map")
    plan = compile_plan(rec, plan_pin_map or pin, station_profile, pin_map_name=pin_name, dut_profile=dut_profile,
                        backend=backend, **plan_kwargs)
    cfg = bundle(policy=cfg_policy, station_profile=station_profile, pin_maps=[pin] if pin else [],
                 duts=[device] if device else [], backend=cfg_backend or backend, source=source)
    ctx = RuleContext(
        plan=plan,
        recipe=rec,
        effective_status=effective_status or rec.status,
        station=station_profile,
        policy=ctx_policy if ctx_policy is not None else cfg.policy,
        pin_map=pin,
        dut=device,
        live=live,
        backend=backend,
        fault=fault,
        inflight_unrecovered=inflight_unrecovered,
        calibration=calibration,
        recipe_source=recipe_source,
    )
    return cfg, ctx


def engine(cfg: ConfigBundle) -> RulesEngine:
    return RulesEngine(cfg, clock=lambda: T0)


def force(v: float, i: float, *, channel: int = 1, **kw: Any) -> tuple[ConfigBundle, RuleContext]:
    """``generic.smu_force`` (one bias channel, wide parameter ranges) with a wide DUT, forcing ``v`` V at
    compliance ``i`` A on ``channel`` (default SMU1, an MPSMU) against the GNDU."""
    return context(rec=recipe(FORCE), pm=pin_map(name="force-1", force=channel), du=wide_dut(),
                   params={"v": v, "icomp": i}, **kw)
