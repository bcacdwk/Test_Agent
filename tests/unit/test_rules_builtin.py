"""Table test per built-in rule id (blueprint 4.2, 8.1 ``unit/``): ok / confirm / block (and warn) cases with
severity, reason, observed value, limit and source asserted for every finding of the rule under test."""

from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Any
from unittest.mock import ANY

import pytest

from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.models.analysis import Quantity, TrustPolicy
from b1500_test_agent.models.plan import ChannelEnvelope, ParamFile
from b1500_test_agent.models.policy import (
    DutProfile,
    DutTerminal,
    HardLimits,
    InterlockPolicy,
    Policy,
    SoftLimits,
)
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.run import FaultRecord
from b1500_test_agent.models.station import CorrectionRecord, InstrumentError
from b1500_test_agent.paths import Paths
from b1500_test_agent.rules.builtin import interlock_errors, quality_findings
from b1500_test_agent.rules.engine import RuleContext, registered_rules
from b1500_test_agent.rules.tiers import HARD_CEILING_A, HARD_CEILING_V
from tests.unit.helpers import REPO_ROOT
from tests.unit.rule_cases import Case, F
from tests.unit.rules_factory import (
    CALIBRATED,
    CMU,
    FORCE,
    IDVG,
    SYSTEM,
    T0,
    ZERO_SHA,
    context,
    dut,
    engine,
    example_station,
    force,
    live_state,
    pin_map,
    pin_map_exact,
    recipe,
    recipe_with_role,
    station,
    wide_dut,
)

POL = "config/local/policy.yaml#"
STA = "config/local/station.yaml#"
PM = "config/local/pinmaps/mosfet-4t.yaml#"
DUT = "config/local/duts/nmos-generic.yaml#"
REC = "recipe:mosfet.idvg@1#"
NO_TARGET = "a channel, GNDU or switch output"
MPSMU_SPEC = "code:b1500_test_agent.driver.modules.MODULE_SPECS[MPSMU] (PG Tables 4-6/4-7, PDF 341-342)"


def above_ceiling_policy() -> Policy:
    """A policy object whose hard limit bypassed validation (the loader can never produce it)."""
    return Policy.model_construct(hard_limits=HardLimits.model_construct(max_abs_voltage_v=60.0,
                                                                         max_abs_compliance_a=0.1))


def with_override_dir() -> tuple[ConfigBundle, RuleContext]:
    cfg, ctx = context(backend="visa")
    paths = Paths.from_env({"B1500_CONFIG_DIR": str(REPO_ROOT / "tmp-override")}, repo_root=REPO_ROOT)
    return cfg.model_copy(update={"paths": paths}), ctx


def gndu_overload() -> tuple[ConfigBundle, RuleContext]:
    """Five 1 A HCSMU channels returning through the GNDU (5 A > 4.2 A)."""
    slots = (1, 3, 5, 7, 9)
    profile = station(
        modules=[{"slot": s, "model": "B1512A", "type": "HCSMU", "channels": [s], "alias": f"HC{s}"} for s in slots],
        topology={}, switches=[], corrections={},
    )
    bias = {"function": "bias_v", "measure": ["I"], "settings": {"v": "$v", "icomp": "$icomp"}}
    roles: dict[str, Any] = {f"r{s}": bias for s in slots}
    roles["source"] = {"function": "ground", "allow_gndu": True}
    rec = recipe(FORCE, roles=roles, params={"v": {"unit": "V", "default": 1.0, "range": [-10, 10]},
                                             "icomp": {"unit": "A", "default": 1.0, "range": [1e-12, 10.0]}})
    pm = pin_map_exact("hc-5", {**{f"r{s}": s for s in slots}, "source": "GNDU"})
    return context(rec=rec, pm=pm, du=wide_dut(terminals=[f"r{s}" for s in slots]), station_profile=profile)


GATE_ONLY_DUT = DutProfile(name="gate-only", device_type="nmos",
                           terminals={"gate": DutTerminal(max_abs_v=3.0, max_abs_i=1e-3)})
AVAILABLE = station(interlock={"available": True})
IL_POLICY = Policy(interlock=InterlockPolicy(required_above_v=5.0))
CORR_FILE = "data/state/corrections/CMU1.json"
PGU_ENVELOPE = ChannelEnvelope(role="pulse", max_abs_v=4.0, max_abs_i=None, function="pgu")
"""An SPGU output (no compliance): the DC current checks skip it, the pulse rules (R-PULSE-*, R-SPGU-01) bound it."""


def corr(kind: str, freqs: tuple[float, ...] = (1e3, 1e5, 1e6), *, age_h: float = 1.0,
         station_sha: str = ZERO_SHA) -> CorrectionRecord:
    """A correction record measured ``age_h`` hours before the plan (``T0``) on the factory's config hashes."""
    return CorrectionRecord(kind=kind, freqs_hz=[] if kind == "phase" else list(freqs), run_id="S20261117T053012Z-00cd",
                            ts=T0 - timedelta(hours=age_h), idn="Keysight Technologies,B1500A,SIM1,A.06",
                            pin_map_sha=ZERO_SHA, station_sha=station_sha,
                            corr_state={"open": True, "short": True, "load": False})


CORRECTED = {"CMU1": [corr("phase"), corr("open"), corr("short")]}


def cmu(**kw: Any) -> tuple[ConfigBundle, RuleContext]:
    """The CMU recipe (gate = cmu_high) on pin map ``cmu-1`` with the gate on CMU1 High (``7H``)."""
    kw.setdefault("rec", recipe(CMU))
    kw.setdefault("pm", pin_map(name="cmu-1", gate="7H"))
    return context(**kw)


SEL1_WIRED = station(switches=[{**example_station().switches[0].model_dump(mode="json"),
                                "ports": {"OUT1": {"index": 0, "inputs": {"smu": 5, "pgu": 101}},
                                          "OUT2": {"index": 1, "inputs": {"smu": 6, "pgu": 102}}}}])
SEL1_SMU = Route(switch="SEL1", output="OUT1", state="smu")
WAVE = {"wave": {"type": "file", "doc": "waveform table"}}
WORK_FILE = ParamFile(path="work/waveforms/a.csv", origin="work", sha256="b" * 64, size_bytes=120)
LIB_FILE = ParamFile(path="recipes/waveforms/a.csv", origin="library", sha256="c" * 64, size_bytes=120)


def wave(path: str, record: ParamFile | None, **kw: Any) -> tuple[ConfigBundle, RuleContext]:
    """``mosfet.idvg`` plus a ``file`` parameter ``wave`` = ``path`` and the planner's record of it."""
    return context(rec=recipe(params={**IDVG["params"], **WAVE}), params={"wave": path},
                   files={"wave": record} if record is not None else {}, **kw)


CASES: list[Case] = [
    # R-CFG-01
    Case("cfg-ok", "R-CFG-01", context),
    Case("cfg-ok-pre", "R-CFG-01", partial(context, live=live_state()), phase="pre_execute"),
    Case("cfg-hard-above-ceiling", "R-CFG-01", partial(context, cfg_policy=above_ceiling_policy()),
         (F("block", 60.0, HARD_CEILING_V, POL + "hard_limits.max_abs_voltage_v"),)),
    Case("cfg-visa-from-examples", "R-CFG-01", partial(context, backend="visa", source="example"),
         (F("block", "example", "local", "config/settings.example.yaml"),
          F("block", "example", "local", "config/station.example.yaml"),
          F("block", "example", "local", "config/policy.example.yaml"))),
    Case("cfg-visa-with-override-dir", "R-CFG-01", with_override_dir,
         (F("block", ANY, None, "config/local/settings.yaml#backend"),)),
    Case("cfg-plan-backend-stale", "R-CFG-01", partial(context, backend="sim", cfg_backend="visa"),
         (F("block", "sim", "visa", "config/local/settings.yaml#backend"),
          F("block", "sim", "visa", "config/local/settings.yaml#backend"))),
    Case("cfg-context-policy-differs", "R-CFG-01",
         partial(context, ctx_policy=Policy(soft_limits=SoftLimits(voltage_v=20.0))),
         (F("block", None, None, "config/local/policy.yaml"),)),
    # R-FAULT-01
    Case("fault-ok", "R-FAULT-01", context),
    Case("fault-latched", "R-FAULT-01",
         partial(context, fault=FaultRecord(reason="cleanup_unverified", set_at=T0)),
         (F("block", "cleanup_unverified", "no latched fault", "data/state/fault.json"),)),
    Case("fault-latched-pre", "R-FAULT-01",
         partial(context, live=live_state(), fault=FaultRecord(reason="cleanup_unverified", set_at=T0)),
         (F("block", "cleanup_unverified", "no latched fault", "data/state/fault.json"),), "pre_execute"),
    Case("fault-inflight", "R-FAULT-01", partial(context, inflight_unrecovered=True),
         (F("block", True, False, "data/state/inflight.json"),)),
    # R-REC-01
    Case("rec-ok-sim", "R-REC-01", context),
    Case("rec-ok-visa-hw-validated", "R-REC-01", partial(context, backend="visa", rec=recipe(status="hw_validated"))),
    Case("rec-kind-missing-on-backend", "R-REC-01", partial(context, runnable=False),
         (F("block", "smu_staircase", "a kind implemented on sim", REC + "kind"),)),
    Case("rec-kind-missing-on-visa", "R-REC-01", partial(context, backend="visa", runnable=False),
         (F("block", "smu_staircase", "a kind implemented on visa", REC + "kind"),)),
    Case("rec-source-is-recipe-file", "R-REC-01",
         partial(context, runnable=False, recipe_source="recipes/mosfet/idvg.yaml"),
         (F("block", "smu_staircase", "a kind implemented on sim", "recipes/mosfet/idvg.yaml#kind"),)),
    Case("rec-draft-visa", "R-REC-01", partial(context, backend="visa", rec=recipe(status="draft")),
         (F("confirm", "draft", "hw_validated", REC + "status", "draft_recipe"),)),
    Case("rec-first-hw-run", "R-REC-01", partial(context, backend="visa"),
         (F("confirm", "sim_validated", "hw_validated", REC + "status", "first_hw_run"),)),
    Case("rec-generic-visa", "R-REC-01", partial(context, backend="visa", rec=recipe(FORCE, status="hw_validated")),
         (F("confirm", "generic.smu_force", "device-specific recipe", "recipe:generic.smu_force@1#id",
            "adhoc_recipe"),)),
    Case("rec-draft-sim-warns", "R-REC-01", partial(context, rec=recipe(status="draft")),
         (F("warn", "draft", "sim_validated", REC + "status"),)),
    # R-PARAM-01
    Case("param-ok", "R-PARAM-01", context),
    Case("param-out-of-range", "R-PARAM-01", partial(context, params={"vg_stop": 12.0}),
         (F("block", 12.0, "-10..10", REC + "params.vg_stop.range"),)),
    Case("param-not-int", "R-PARAM-01", partial(context, params={"vg_points": 10.5}),
         (F("block", "10.5", "int", REC + "params.vg_points.type"),)),
    Case("param-bad-choice", "R-PARAM-01", partial(context, params={"integration": "fast"}),
         (F("block", "'fast'", "short, medium, long", REC + "params.integration.choices"),)),
    Case("param-unknown", "R-PARAM-01", partial(context, params={"foo": 1.0}),
         (F("block", "foo", "icomp_drain, icomp_gate, integration, vd, vg_points, vg_start, vg_stop",
            REC + "params"),)),
    Case("param-missing-required", "R-PARAM-01",
         partial(context, rec=recipe(params={**IDVG["params"], "vd": {"unit": "V", "range": [-5, 5]}})),
         (F("block", None, "a value", REC + "params.vd"),)),
    Case("param-resolved-differs", "R-PARAM-01",
         partial(context, params={"vg_stop": 3.0}, resolved_override={"vg_stop": Quantity(value=2.0, unit="V")}),
         (F("block", 2.0, 3.0, "plan:resolved_params.vg_stop"),)),
    Case("param-unit-mismatch", "R-PARAM-01",
         partial(context, resolved_override={"vd": Quantity(value=0.05, unit="A")}),
         (F("block", "A", "V", REC + "params.vd.unit"),)),
    Case("param-file-ok", "R-PARAM-01", partial(wave, WORK_FILE.path, WORK_FILE)),
    Case("param-file-not-a-csv-path", "R-PARAM-01", partial(wave, "/etc/passwd.csv", None),
         (F("block", "'/etc/passwd.csv'", "recipes/waveforms/<name>.csv or work/waveforms/<name>.csv",
            REC + "params.wave.type"),)),
    Case("param-file-not-read", "R-PARAM-01", partial(wave, WORK_FILE.path, None),
         (F("block", "work/waveforms/a.csv", "a read file", "plan:files.wave"),)),
    Case("param-file-unusable", "R-PARAM-01",
         partial(wave, WORK_FILE.path, ParamFile(path=WORK_FILE.path, origin="work",
                                                 problem="work/waveforms/a.csv does not exist")),
         (F("block", "work/waveforms/a.csv", "an existing CSV of at most 1 MiB in its folder", "plan:files.wave"),)),
    # R-PIN-01
    Case("pin-ok", "R-PIN-01", context),
    Case("pin-map-missing", "R-PIN-01", partial(context, pm=None),
         (F("block", "ghost-map", "an existing pin map", "config:pinmaps/ghost-map"),)),
    Case("pin-role-without-terminal", "R-PIN-01",
         partial(context, pm=pin_map_exact("partial", {"gate": 5, "source": "GNDU"})),
         (F("block", None, NO_TARGET, "config/local/pinmaps/partial.yaml#terminals.drain"),)),
    Case("pin-terminal-unconnected", "R-PIN-01", partial(context, pm=pin_map(drain=None)),
         (F("block", None, NO_TARGET, PM + "terminals.drain"),)),
    Case("pin-channel-twice", "R-PIN-01", partial(context, pm=pin_map(gate=3)),
         (F("block", 3, "one role per channel", PM + "terminals.gate"),)),
    Case("pin-channel-without-module", "R-PIN-01", partial(context, pm=pin_map(gate=8)),
         (F("block", 8, "101, 102, 201, 202, 3, 4, 5, 6, 7", STA + "modules"),)),
    Case("pin-module-type-not-allowed", "R-PIN-01", partial(context, pm=pin_map(gate=201)),
         (F("block", "WGFMU", "MPSMU, HRSMU, HPSMU", REC + "roles.gate.module_types"),)),
    Case("pin-spgu-is-not-an-smu", "R-PIN-01", partial(context, pm=pin_map(gate=1)),
         (F("block", "HVSPGU", "MPSMU, HRSMU, HPSMU", REC + "roles.gate.module_types"),)),
    Case("pin-low-current-needs-hrsmu", "R-PIN-01",
         partial(context, rec=recipe_with_role(IDVG, "drain", low_current=True), pm=pin_map(drain=6)),
         (F("block", "MPSMU", "HRSMU", REC + "roles.drain.low_current"),)),
    Case("pin-gndu-not-allowed", "R-PIN-01", partial(context, pm=pin_map(gate="GNDU")),
         (F("block", "GNDU", "an SMU channel", REC + "roles.gate.allow_gndu"),)),
    Case("pin-gndu-cannot-source", "R-PIN-01",
         partial(context, rec=recipe_with_role(IDVG, "drain", allow_gndu=True), pm=pin_map(drain="GNDU")),
         (F("block", "GNDU", "an SMU channel", REC + "roles.drain.function"),)),
    Case("pin-binding-differs", "R-PIN-01", partial(context, plan_pin_map=pin_map(gate=6)),
         (F("block", 6, 5, PM + "terminals.gate"), F("block", "B1511B", "B1511B", STA + "modules[4]"))),
    Case("pin-envelope-channel-unbound", "R-PIN-01",
         partial(context, extra_envelope={4: ChannelEnvelope(role="drain", max_abs_v=1.0, max_abs_i=1e-3)}),
         (F("block", 4, None, "plan:envelope.channels.4"),)),
    # R-PIN-01, v2 targets: switch outputs and MFCMU sides
    Case("pin-switch-ok-routed", "R-PIN-01",
         partial(context, pm=pin_map(gate="SEL1.OUT1"), station_profile=SEL1_WIRED, routes=[SEL1_SMU])),
    Case("pin-switch-wiring-unknown", "R-PIN-01", partial(context, pm=pin_map(gate="SEL1.OUT1")),
         (F("block", None, "a channel", STA + "switches[0].ports.OUT1.inputs.smu"),)),
    Case("pin-switch-kind-not-routing", "R-PIN-01",
         partial(context, pm=pin_map(gate="SEL1.OUT1"), station_profile=SEL1_WIRED),
         (F("block", None, "SEL1.OUT1->smu", "plan:envelope.routes"),)),
    Case("pin-switch-undeclared", "R-PIN-01", partial(context, pm=pin_map(gate="SEL9.OUT1")),
         (F("block", "SEL9.OUT1", "a declared switch output", STA + "switches"),)),
    Case("pin-switch-declared-absent", "R-PIN-01",
         partial(context, pm=pin_map(gate="SEL1.OUT1"), routes=[SEL1_SMU], station_profile=station(
             switches=[{**SEL1_WIRED.switches[0].model_dump(mode="json"), "present": False}])),
         (F("block", False, True, STA + "switches[0].present"),)),
    Case("pin-switch-cannot-connect-resource", "R-PIN-01",
         partial(context, rec=recipe(CMU), pm=pin_map(name="cmu-1", gate="SEL1.OUT1"), station_profile=SEL1_WIRED),
         (F("block", "selector_16440a", "open, pgu, pgu_open, smu", STA + "switches[0].kind"),)),
    Case("pin-cmu-ok", "R-PIN-01", cmu),
    Case("pin-cmu-needs-side", "R-PIN-01", partial(cmu, pm=pin_map(name="cmu-1", gate=7)),
         (F("block", 7, "7H", "config/local/pinmaps/cmu-1.yaml#terminals.gate"),)),
    Case("pin-cmu-wrong-side", "R-PIN-01", partial(cmu, pm=pin_map(name="cmu-1", gate="7L")),
         (F("block", "7L", "7H", "config/local/pinmaps/cmu-1.yaml#terminals.gate"),)),
    Case("pin-cmu-side-for-smu-role", "R-PIN-01", partial(context, pm=pin_map(gate="7H")),
         (F("block", "7H", NO_TARGET, PM + "terminals.gate"),
          F("block", "MFCMU", "MPSMU, HRSMU, HPSMU", REC + "roles.gate.module_types"))),
    # R-PIN-02
    Case("pin2-ok", "R-PIN-02", context),
    Case("pin2-unverified", "R-PIN-02", partial(context, pm=pin_map(certainty="unverified")),
         (F("confirm", "unverified", "verified", PM + "certainty", "unverified_pin_map"),)),
    # R-INV-01
    Case("inv-ok", "R-INV-01", partial(context, live=live_state()), phase="pre_execute"),
    Case("inv-plan-without-live", "R-INV-01", context),
    Case("inv-pre-without-live", "R-INV-01", context, (F("block", None, "a live snapshot", "live:snapshot"),),
         "pre_execute"),
    Case("inv-slot-model-differs", "R-INV-01", partial(context, live=live_state(slots={3: "B1511B"})),
         (F("block", "B1511B", "B1517A", STA + "modules[2].model"),), "pre_execute"),
    Case("inv-slot-empty", "R-INV-01", partial(context, live=live_state(slots={5: None})),
         (F("block", None, "B1511B", STA + "modules[4].model"),), "pre_execute"),
    Case("inv-identity-differs", "R-INV-01", partial(context, live=live_state(model="B1505A")),
         (F("block", "B1505A", "B1500A", STA + "mainframe.model"),), "pre_execute"),
    Case("inv-identity-missing", "R-INV-01", partial(context, live=live_state(model=None)),
         (F("block", None, "B1500A", "live:identity"),), "pre_execute"),
    Case("inv-inventory-missing", "R-INV-01", partial(context, live=live_state(inventory=False)),
         (F("block", None, "inventory", "live:inventory"),), "pre_execute"),
    Case("inv-backend-differs", "R-INV-01", partial(context, live=live_state(backend="visa")),
         (F("block", "visa", "sim", "live:backend"),), "pre_execute"),
    Case("inv-plan-with-live-snapshot", "R-INV-01", partial(context, live=live_state(slots={3: "B1511B"})),
         (F("block", "B1511B", "B1517A", STA + "modules[2].model"),)),
    # R-LIM-01
    Case("lim1-ok", "R-LIM-01", partial(force, 5.0, 1e-3)),
    Case("lim1-current-above-module", "R-LIM-01", partial(force, 5.0, 0.15), (F("block", 0.15, 0.1, MPSMU_SPEC),)),
    Case("lim1-voltage-above-module", "R-LIM-01", partial(force, 150.0, 1e-3), (F("block", 150.0, 100.0, MPSMU_SPEC),)),
    Case("lim1-outside-envelope-corner", "R-LIM-01", partial(force, 30.0, 0.08),
         (F("block", "30 V @ 0.08 A", "20 V @ 0.1 A, 40 V @ 0.05 A, 100 V @ 0.02 A", MPSMU_SPEC),)),
    Case("lim1-not-a-dc-source", "R-LIM-01", partial(force, 1.0, 1e-3, channel=7),
         (F("block", "bias_v", "cmu_high, cmu_low",
            "code:b1500_test_agent.driver.modules.CMU_SPEC.max_dc_v (UG p73 (2-33))"),)),
    Case("lim1-ok-spgu-in-spec", "R-LIM-01", partial(context, extra_envelope={101: PGU_ENVELOPE})),
    Case("lim1-spgu-above-open-load-max", "R-LIM-01",
         partial(context, extra_envelope={101: PGU_ENVELOPE.model_copy(update={"max_abs_v": 45.0})}),
         (F("block", 45.0, 40.0, "code:b1500_test_agent.driver.modules.SPGU_SPEC.max_open_v (UG p76 (2-36))"),)),
    Case("lim1-gndu-overload", "R-LIM-01", gndu_overload,
         (F("block", 5.0, 4.2, "code:b1500_test_agent.driver.modules.MODULE_SPECS[GNDU] (UG GNDU, PDF 58)"),)),
    # R-LIM-02
    Case("lim2-ok-at-hard-limit", "R-LIM-02", partial(force, 42.0, 0.1)),
    Case("lim2-voltage", "R-LIM-02", partial(force, 45.0, 1e-3),
         (F("block", 45.0, 42.0, POL + "hard_limits.max_abs_voltage_v"),)),
    Case("lim2-compliance", "R-LIM-02", partial(force, 5.0, 0.15),
         (F("block", 0.15, 0.1, POL + "hard_limits.max_abs_compliance_a"),)),
    Case("lim2-tightened-policy", "R-LIM-02",
         partial(force, 25.0, 1e-3, cfg_policy=Policy(hard_limits=HardLimits(max_abs_voltage_v=20.0),
                                                      soft_limits=SoftLimits(voltage_v=5.0))),
         (F("block", 25.0, 20.0, POL + "hard_limits.max_abs_voltage_v"),)),
    Case("lim2-code-ceiling-holds", "R-LIM-02", partial(force, 45.0, 1e-3, cfg_policy=above_ceiling_policy()),
         (F("block", 45.0, HARD_CEILING_V, "code:b1500_test_agent.rules.tiers.HARD_CEILING_V"),)),
    Case("lim2-non-finite-fails-closed", "R-LIM-02",
         partial(context, extra_envelope={3: ChannelEnvelope.model_construct(
             role="drain", max_abs_v=float("nan"), max_abs_i=1e-3, function=None, v_start=None, v_stop=None)}),
         (F("block", "nan", 42.0, POL + "hard_limits.max_abs_voltage_v"),)),
    Case("lim2-ok-compliance-free-channel", "R-LIM-02", partial(context, extra_envelope={101: PGU_ENVELOPE})),
    # R-LIM-03
    Case("lim3-ok-at-soft-limit", "R-LIM-03", partial(force, 10.0, 0.01)),
    Case("lim3-ok-compliance-free-channel", "R-LIM-03", partial(context, extra_envelope={101: PGU_ENVELOPE})),
    Case("lim3-voltage", "R-LIM-03", partial(force, 15.0, 1e-3),
         (F("confirm", 15.0, 10.0, POL + "soft_limits.voltage_v", "soft_limit"),)),
    Case("lim3-compliance", "R-LIM-03", partial(force, 5.0, 0.02),
         (F("confirm", 0.02, 0.01, POL + "soft_limits.compliance_a", "soft_limit"),)),
    # R-DUT-01
    Case("dut-ok", "R-DUT-01", context),
    Case("dut-ok-no-dut-roles", "R-DUT-01", partial(context, rec=recipe(SYSTEM), du=None, dut_profile=None)),
    Case("dut-missing", "R-DUT-01", partial(context, du=None, dut_profile=None),
         (F("block", None, "a DUT profile", "plan:request.dut_profile"),)),
    Case("dut-not-found", "R-DUT-01", partial(context, du=None, dut_profile="ghost"),
         (F("block", "ghost", "an existing DUT profile", "config:duts/ghost"),)),
    Case("dut-terminal-not-described", "R-DUT-01", partial(context, du=GATE_ONLY_DUT),
         (F("block", "drain", "gate", "config/local/duts/gate-only.yaml#terminals"),)),
    Case("dut-voltage-outside", "R-DUT-01", partial(context, params={"vg_stop": 5.0}),
         (F("confirm", 5.0, 3.0, DUT + "terminals.gate.max_abs_v", "dut_envelope"),)),
    Case("dut-compliance-outside", "R-DUT-01", partial(context, params={"icomp_drain": 5e-3}),
         (F("confirm", 5e-3, 1e-3, DUT + "terminals.drain.max_abs_i", "dut_envelope"),)),
    Case("dut-device-type-warns", "R-DUT-01", partial(context, du=dut(device_type="diode")),
         (F("warn", "diode", "nmos, pmos, igzo_tft", DUT + "device_type"),)),
    # R-COMP-01
    Case("comp-ok", "R-COMP-01", context),
    Case("comp-no-explicit-compliance", "R-COMP-01",
         partial(context, rec=recipe_with_role(IDVG, "drain", settings={"v": "$vd"})),
         (F("block", None, "non-zero compliance", REC + "roles.drain.settings.icomp"),
          F("block", 0.0, "> 0", "plan:envelope.channels.3.max_abs_i"))),
    Case("comp-zero-compliance", "R-COMP-01",
         partial(context, rec=recipe_with_role(IDVG, "drain", settings={"v": "$vd", "icomp": 0.0})),
         (F("block", 0.0, "non-zero compliance", REC + "roles.drain.settings.icomp"),
          F("block", 0.0, "> 0", "plan:envelope.channels.3.max_abs_i"))),
    Case("comp-connected-without-envelope", "R-COMP-01", partial(context, drop_envelope=[3]),
         (F("block", None, "non-zero compliance", "plan:envelope.channels"),)),
    # R-IL-01
    Case("il-ok-below-threshold", "R-IL-01", context),
    Case("il-ok-below-threshold-bit3-set", "R-IL-01",
         partial(force, 4.0, 1e-3, cfg_policy=IL_POLICY, live=live_state(stb=8)), phase="pre_execute"),
    Case("il-ok-closed", "R-IL-01",
         partial(force, 8.0, 1e-3, cfg_policy=IL_POLICY, station_profile=AVAILABLE, live=live_state()),
         phase="pre_execute"),
    Case("il-station-has-no-interlock", "R-IL-01", partial(force, 8.0, 1e-3, cfg_policy=IL_POLICY),
         (F("block", None, True, STA + "interlock.available"),)),
    Case("il-bit3-set", "R-IL-01",
         partial(force, 8.0, 1e-3, cfg_policy=IL_POLICY, station_profile=AVAILABLE, live=live_state(stb=8)),
         (F("block", 8, "bit 3 clear", "live:status_byte.bit3"),), "pre_execute"),
    Case("il-errx-202-atv10-fallback", "R-IL-01",
         partial(force, 8.0, 1e-3, cfg_policy=IL_POLICY, station_profile=AVAILABLE,
                 live=live_state(errors=[(202, "Interlock circuit must be closed.")])),
         (F("block", 202, "no error 202/203", "live:errors"),), "pre_execute"),
    Case("il-status-byte-missing", "R-IL-01",
         partial(force, 8.0, 1e-3, cfg_policy=IL_POLICY, station_profile=AVAILABLE, live=live_state(stb=None)),
         (F("block", None, "bit 3 clear", "live:status_byte"),), "pre_execute"),
    Case("il-pre-without-live", "R-IL-01",
         partial(force, 8.0, 1e-3, cfg_policy=IL_POLICY, station_profile=AVAILABLE),
         (F("block", None, "bit 3 clear", "live:status_byte"),), "pre_execute"),
    # R-RUN-01
    Case("run-ok", "R-RUN-01", context),
    Case("run-too-many-points", "R-RUN-01", partial(context, points=20000),
         (F("block", 20000, 10001, POL + "run_limits.max_points.smu"),)),
    Case("run-family-limit-cmu", "R-RUN-01",
         partial(cmu, points=200, cfg_policy=Policy(run_limits={"max_points": {"cmu": 100}})),
         (F("block", 200, 100, POL + "run_limits.max_points.cmu"),)),
    Case("run-int-max-points-applies-to-all", "R-RUN-01",
         partial(context, points=600, cfg_policy=Policy(run_limits={"max_points": 500})),
         (F("block", 600, 500, POL + "run_limits.max_points.smu"),)),
    Case("run-duration-is-r-run-02s", "R-RUN-01", partial(context, duration_s=400.0)),
    # R-ALWAYS-01
    Case("always-ok", "R-ALWAYS-01", context),
    Case("always-destructive", "R-ALWAYS-01", partial(context, rec=recipe(always_confirm=["destructive"])),
         (F("confirm", "destructive", None, REC + "always_confirm", "destructive"),)),
    Case("always-system-self-test", "R-ALWAYS-01", partial(context, rec=recipe(SYSTEM), du=None, dut_profile=None),
         (F("confirm", "system_self_test", None, "recipe:system.self_test@1#always_confirm", "system_self_test"),)),
    Case("always-library-file-ok", "R-ALWAYS-01", partial(wave, LIB_FILE.path, LIB_FILE)),
    Case("always-adhoc-work-file", "R-ALWAYS-01", partial(wave, WORK_FILE.path, WORK_FILE),
         (F("confirm", "work/waveforms/a.csv", "recipes/waveforms/", "plan:files.wave", "adhoc_recipe"),)),
    # R-ERRX-01
    Case("errx-ok", "R-ERRX-01", partial(context, live=live_state()), phase="pre_execute"),
    Case("errx-plan-without-live", "R-ERRX-01", context),
    Case("errx-preexisting", "R-ERRX-01", partial(context, live=live_state(errors=[(305, "Excess current")])),
         (F("warn", 305, 0, "live:errors"),), "pre_execute"),
    Case("errx-plan-with-live-snapshot", "R-ERRX-01",
         partial(context, live=live_state(errors=[(305, "Excess current")])), (F("warn", 305, 0, "live:errors"),)),
    # R-CAL-01
    Case("cal-plan-phase-not-run", "R-CAL-01", context),
    Case("cal-recorded", "R-CAL-01", partial(context, live=live_state(), calibration=CALIBRATED),
         (F("info", True, None, "live:auto_calibration"),
          F("info", "2026-11-16T06:30:12+00:00", None, "data/runs/index.jsonl")), "pre_execute"),
    Case("cal-unknown", "R-CAL-01", partial(context, live=live_state()),
         (F("warn", None, "recorded", "live:auto_calibration"), F("warn", None, "recorded", "data/runs/index.jsonl")),
         "pre_execute"),
    # R-CORR-01
    Case("corr-ok-not-cmu", "R-CORR-01", context),
    Case("corr-ok-records", "R-CORR-01", partial(cmu, corrections=CORRECTED),
         (F("info", 1.0, 8.0, CORR_FILE),)),
    Case("corr-ok-correction-recipe-exempt", "R-CORR-01", partial(cmu, rec=recipe(CMU, kind="cmu_correction"))),
    Case("corr-no-records", "R-CORR-01", cmu,
         (F("block", None, "phase", POL + "corrections.require"),
          F("block", None, "open", POL + "corrections.require"),
          F("block", None, "short", POL + "corrections.require"))),
    Case("corr-policy-adds-load", "R-CORR-01",
         partial(cmu, corrections=CORRECTED, cfg_policy=Policy(corrections={"require": ["phase", "open", "short",
                                                                                        "load"]})),
         (F("block", None, "load", POL + "corrections.require"),)),
    Case("corr-frequency-not-covered", "R-CORR-01",
         partial(cmu, corrections={"CMU1": [corr("phase"), corr("open", (1e3, 1e5)), corr("short", (1e3, 1e5))]}),
         (F("block", 1e6, "1000, 100000", CORR_FILE), F("block", 1e6, "1000, 100000", CORR_FILE))),
    Case("corr-stale", "R-CORR-01",
         partial(cmu, corrections={"CMU1": [corr("phase"), corr("open", age_h=9.0), corr("short")]}),
         (F("block", 9.0, 8.0, POL + "corrections.max_age_h"),)),
    Case("corr-other-landing", "R-CORR-01",
         partial(cmu, corrections={"CMU1": [corr("phase"), corr("open"), corr("short", station_sha="d" * 64)]}),
         (F("block", "S20261117T053012Z-00cd", "this station profile and pin map", CORR_FILE),)),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_rule_table(case: Case) -> None:
    cfg, ctx = case.build()
    report = engine(cfg).evaluate(ctx, case.phase)  # type: ignore[arg-type]
    mine = [f for f in report.findings if f.rule_id == case.rule_id]
    assert [F(f.severity, f.observed, f.limit, f.source, f.reason) for f in mine] == list(case.expect)
    for finding in mine:
        assert finding.message and finding.message.isascii()


def test_every_rule_has_ok_and_non_ok_cases() -> None:
    """Over the v1 rows here and the v2 rows of ``test_rules_v2.py``."""
    from tests.unit.test_rules_v2 import CASES as V2_CASES

    cases = [*CASES, *V2_CASES]
    ok = {c.rule_id for c in cases if not c.expect}
    flagged = {c.rule_id for c in cases if c.expect}
    ids = {spec.rule_id for spec in registered_rules()}
    assert ids <= ok
    assert ids <= flagged


def test_table_outcomes_are_covered() -> None:
    """Every outcome of the blueprint 4.2 table appears: block, confirm (per reason), warn."""
    seen = {(c.rule_id, f.severity, f.reason) for c in CASES for f in c.expect}
    for rule_id, severity, reason in [
        ("R-REC-01", "block", None), ("R-REC-01", "confirm", "draft_recipe"), ("R-REC-01", "confirm", "first_hw_run"),
        ("R-REC-01", "confirm", "adhoc_recipe"), ("R-REC-01", "warn", None), ("R-PIN-02", "confirm",
                                                                             "unverified_pin_map"),
        ("R-LIM-03", "confirm", "soft_limit"), ("R-DUT-01", "block", None), ("R-DUT-01", "confirm", "dut_envelope"),
        ("R-ALWAYS-01", "confirm", "destructive"), ("R-ERRX-01", "warn", None), ("R-CAL-01", "warn", None),
        ("R-ALWAYS-01", "confirm", "adhoc_recipe"), ("R-CORR-01", "block", None), ("R-PIN-01", "block", None),
    ]:
        assert (rule_id, severity, reason) in seen


def test_hard_ceiling_constants() -> None:
    assert (HARD_CEILING_V, HARD_CEILING_A) == (42.0, 0.1)
    assert HardLimits() == HardLimits(max_abs_voltage_v=HARD_CEILING_V, max_abs_compliance_a=HARD_CEILING_A)


def test_interlock_errors_selects_202_and_203() -> None:
    errors = [InstrumentError(code=c) for c in (305, 203, 202, 203)]
    assert [e.code for e in interlock_errors(errors)] == [202, 203]


# -- R-QUAL-* --------------------------------------------------------------------------------------------------------


def test_quality_classification_counts_and_flags() -> None:
    findings = quality_findings({"N": 90, "C": 5, "T": 3, "V": 2}, TrustPolicy(), source="p#quality")
    assert [(f.rule_id, f.severity, f.observed, f.limit) for f in findings] == [
        ("R-QUAL-01", "info", 100, None),
        ("R-QUAL-02", "warn", 8, 0),
        ("R-QUAL-03", "warn", 2, 0),
    ]
    assert "C 5, T 3" in findings[1].message
    assert all(f.source == "p#quality" for f in findings)


def test_quality_all_normal_is_only_recorded() -> None:
    findings = quality_findings({"N": 101}, TrustPolicy(), source="s")
    assert [(f.rule_id, f.severity) for f in findings] == [("R-QUAL-01", "info")]


def test_quality_unknown_letter_is_untrusted_and_recipe_classes_apply() -> None:
    findings = quality_findings({"N": 1, "Z": 1}, TrustPolicy(), source="s")
    assert findings[-1].rule_id == "R-QUAL-03" and "Z 1" in findings[-1].message
    strict = TrustPolicy(limited=["T"], untrusted=["C", "V", "X", "F", "D", "G", "S", "U"])
    assert [f.rule_id for f in quality_findings({"C": 1}, strict, source="s")] == ["R-QUAL-01", "R-QUAL-03"]


def test_engine_quality_uses_recipe_or_policy_classes() -> None:
    cfg, ctx = context()
    eng = engine(cfg)
    assert {f.source for f in eng.quality({"N": 3, "C": 1}, recipe=ctx.recipe)} == {REC + "quality"}
    assert {f.source for f in eng.quality({"N": 3})} == {POL + "quality"}
