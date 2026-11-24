"""Table test per v2 rule id (blueprint v2 2.8, 8.1 ``unit/``): ok / confirm / block (and info) rows for R-PULSE-01..03,
R-SPGU-01, R-ROUTE-01/02, R-CMU-01, R-CORR-01 (live part, multi-record coverage), R-WG-01/02, R-RUN-02, R-GNDU-01,
R-ASU-01, R-CAL-02 and the v1 changes (R-LIM-01 module rows and I-forcing, R-COMP-01, R-ALWAYS-01 physical setup,
R-PIN-01 on both MFCMU sides); the SER arithmetic table; the correction-record source protocol; the R-QUAL-* letters
of MFCMU status codes and WGFMU flags. Live parts are tested with synthetic ``LiveState`` values."""

from __future__ import annotations

import copy
from functools import partial
from typing import Any
from unittest.mock import ANY

import pytest

from b1500_test_agent.driver.modules import SPGU_SPEC
from b1500_test_agent.driver.parser import CmuStatus
from b1500_test_agent.models.analysis import TrustPolicy
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, PulseEnvelope
from b1500_test_agent.models.policy import HardLimits, Policy, SoftLimits, TerminalPulse
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import PulseTrain, open_load_voltage, short_circuit_current
from b1500_test_agent.models.station import CmuCorrectionLive, CorrectionRecord
from b1500_test_agent.rules import correction_records
from b1500_test_agent.rules.builtin import cmu_status_letter, quality_findings, wgfmu_status_letter
from b1500_test_agent.rules.engine import CorrectionRecordSource
from tests.unit import rules_factory_v2 as v2
from tests.unit.rule_cases import Case, F
from tests.unit.rules_factory import (
    CALIBRATED,
    CMU,
    FORCE,
    context,
    engine,
    live_state,
    pin_map,
    recipe,
    wide_dut,
)

POL = "config/local/policy.yaml#"
STA = "config/local/station.yaml#"
DUTF = "config/local/duts/fefet-lab.yaml#"
DUTN = "config/local/duts/nmos-pulse.yaml#"
DUTM = "config/local/duts/moscap-generic.yaml#"
SPEC = "code:b1500_test_agent.driver.modules"
SPGU_SRC = f"{SPEC}.SPGU_SPEC"
WG = f"{SPEC}.WGFMU_SPEC"
CMU_SRC = f"{SPEC}.CMU_SPEC (UG p73 (2-33))"
WAVE = "plan:program.sources.waveform"
CORR_FILE = "data/state/corrections/CMU1.json"
HARD_A = POL + "hard_limits.max_abs_compliance_a"
V_TRAIN = v2.TRAIN.open_load_v(source_ohm=50.0)
"""Open-load voltage of the blueprint example train (4 V at SER 1 MOhm: 4.0002 V)."""


def train(**changes: Any) -> PulseTrain:
    return v2.TRAIN.model_copy(update=changes)


def smu_train(**changes: Any) -> PulseTrain:
    return v2.SMU_TRAIN.model_copy(update=changes)


WG_TRAIN = PulseTrain(base_v=0.0, peak_v=3.0, width_s=1e-7, period_s=1e-6, count=10)
GATE_TALL = v2.terminal(max_abs_v=10.0, pulse=TerminalPulse(max_abs_v=10.0, max_width_s=1e-3, max_duty=0.5,
                                                            max_count=1_000_000))


def big_pulse(isc: float = 2.5) -> PulseEnvelope:
    return PulseEnvelope(max_abs_v_dut=40.0, min_width_s=1e-6, max_width_s=1e-6, max_duty=0.1, max_count=1,
                         max_on_time_s=1e-6, max_short_circuit_a=isc)


def pgu_entry(role: str, isc: float = 2.5) -> ChannelEnvelope:
    return ChannelEnvelope(role=role, max_abs_v=40.0, max_abs_i=None, function="pgu", pulse=big_pulse(isc))


def mutate(fn: Any) -> Any:
    """A ``wgfmu(mutate=...)`` editor from a function of the program dict."""
    return fn


def _set(path: tuple[Any, ...], value: Any) -> Any:
    def edit(data: dict[str, Any]) -> None:
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return edit


def _event(index: int, **changes: Any) -> Any:
    def edit(data: dict[str, Any]) -> None:
        data["events"][index].update(changes)
    return edit


def _add_event(**event: Any) -> Any:
    def edit(data: dict[str, Any]) -> None:
        data["events"].append(event)
    return edit


def _chain(*edits: Any) -> Any:
    def edit(data: dict[str, Any]) -> None:
        for fn in edits:
            fn(data)
    return edit


def _dc_top(levels: list[float], force_range: str = "3v") -> Any:
    """Channel 201 in DC mode forcing ``levels`` (builder ``dc_spot``, WP10.4) instead of its sequence."""
    def edit(data: dict[str, Any]) -> None:
        data["channels"]["201"] = {"mode": "dc", "force_range": force_range, "measure": "current",
                                   "current_range": "1ma"}
        data["sequences"].pop("201")
        data["events"] = [e for e in data["events"] if e["pattern"] != "drive"]
        data["dc"] = {"201": levels}
    return edit


SEL1_PGU_OPEN_CH2 = Route(switch="SEL1", output="OUT2", state="pgu_open")
SEL9 = Route(switch="SEL9", output="OUT1", state="smu")
CURRENT_FORCE = {"force": {"function": "bias_i", "measure": ["V"], "settings": {"i": "$icomp", "vcomp": "$v"}},
                 "source": {"function": "ground", "allow_gndu": True}}
CURRENT_ENTRY = ChannelEnvelope(role="force", max_abs_v=5.0, max_abs_i=1e-3, function="bias_i")
KELVIN = {"force": {**FORCE["roles"]["force"], "kelvin": True}, "source": FORCE["roles"]["source"]}
TWO_FREQ = recipe(v2.CV_REC, params={**v2.CV_REC["params"], "freq2": {"unit": "Hz", "default": 1e3}})


def corr_split() -> dict[str, list[CorrectionRecord]]:
    """Each plan frequency (1 kHz, 1 MHz) is covered by a fresh open record, none covers both (WP5.7 report)."""
    return {"CMU1": [v2.corr("phase"), v2.corr("open", freqs=(1e3,)), v2.corr("open", freqs=(1e6,), age_h=1.0),
                     v2.corr("short", freqs=(1e3, 1e6))]}


CASES: list[Case] = [
    # R-PULSE-01
    Case("pulse1-ok-spgu", "R-PULSE-01", v2.spgu),
    Case("pulse1-ok-smu", "R-PULSE-01", v2.smu_pulse),
    Case("pulse1-ok-wgfmu-pulses", "R-PULSE-01",
         partial(v2.wgfmu, trains=[WG_TRAIN], top_pulse=v2.pulse_envelope([WG_TRAIN], source_ohm=None))),
    Case("pulse1-ok-no-pulse-roles", "R-PULSE-01", context),
    Case("pulse1-spgu-width-below-leading", "R-PULSE-01", partial(v2.spgu, [train(width_s=1e-8)]),
         (F("block", 1e-8, 2.5e-8, SPGU_SRC),)),
    Case("pulse1-spgu-period-too-long", "R-PULSE-01", partial(v2.spgu, [train(period_s=20.0)]),
         (F("block", 20.0, "2e-08..10", SPGU_SRC),)),
    Case("pulse1-spgu-count-above-module", "R-PULSE-01", partial(v2.spgu, [train(count=2_000_000)]),
         (F("block", 2_000_000, "1..1000000", SPGU_SRC),)),
    Case("pulse1-spgu-slow-edge-resolution", "R-PULSE-01",
         partial(v2.spgu, [train(lead_s=1e-5, trail_s=1e-5, width_s=2.0025e-5)]),
         (F("block", 2.0025e-5, 1e-8, SPGU_SRC),)),
    Case("pulse1-spgu-ser-out-of-range", "R-PULSE-01", partial(v2.spgu, [train(load_ohm=2e6)]),
         (F("block", 2e6, "0.1..1e+06", SPGU_SRC),)),
    Case("pulse1-no-pulse-envelope", "R-PULSE-01", partial(v2.spgu, envelope=None),
         (F("block", None, "a pulse envelope", "plan:envelope.channels.101.pulse"),)),
    Case("pulse1-no-trains", "R-PULSE-01", partial(v2.spgu, sources={"pulses": {}}),
         (F("block", None, "a pulse train", "plan:program.sources.pulses"),)),
    Case("pulse1-trains-on-another-channel", "R-PULSE-01",
         partial(v2.spgu, sources={"pulses": {"101": [v2.TRAIN.model_dump(mode="json")],
                                              "102": [v2.TRAIN.model_dump(mode="json")]}}),
         (F("block", 102, "101", "plan:program.sources.pulses.102"),)),
    Case("pulse1-free-run-cannot-be-expressed", "R-PULSE-01",
         partial(v2.spgu, sources={"pulses": {"101": [{"base_v": 0, "peak_v": 4, "width_s": 1e-6,
                                                       "period_s": 1e-4}]}}),
         (F("block", None, "a valid source plan", "plan:program.sources"),)),
    Case("pulse1-envelope-does-not-admit", "R-PULSE-01",
         partial(v2.spgu, envelope=PulseEnvelope(max_abs_v_dut=4.001, min_width_s=1e-6, max_width_s=1e-6,
                                                 max_duty=0.5, max_count=100, max_on_time_s=1.0,
                                                 max_short_circuit_a=0.08)),
         (F("block", 1000, 100, "plan:envelope.channels.101.pulse.max_count"),)),
    Case("pulse1-smu-width-below-table", "R-PULSE-01", partial(v2.smu_pulse, [smu_train(width_s=1e-4)]),
         (F("block", 1e-4, "0.0005..2", f"{SPEC}.SMU_PULSE_SPECS[MPSMU] (PG p486-487 (4-168))"),)),
    Case("pulse1-smu-period-margin", "R-PULSE-01",
         partial(v2.smu_pulse, [smu_train(width_s=5e-3, period_s=6e-3)]),
         (F("block", 6e-3, ANY, f"{SPEC}.SMU_PULSE_SPECS[MPSMU] (PG p486-487 (4-168))"),)),
    Case("pulse1-wgfmu-off-grid", "R-PULSE-01",
         partial(v2.wgfmu, trains=[WG_TRAIN.model_copy(update={"width_s": 1.5e-8})],
                 top_pulse=v2.pulse_envelope([WG_TRAIN.model_copy(update={"width_s": 1.5e-8})], source_ohm=None)),
         (F("block", 1.5e-8, 1e-8, WG),)),
    # R-PULSE-02
    Case("pulse2-ok", "R-PULSE-02", v2.spgu),
    Case("pulse2-terminal-without-pulse-envelope", "R-PULSE-02", partial(v2.spgu, gate=v2.terminal(pulse=None)),
         (F("block", None, "a pulse envelope", DUTF + "terminals.gate.pulse"),)),
    Case("pulse2-level-above-dut", "R-PULSE-02",
         partial(v2.spgu, gate=v2.terminal(pulse=TerminalPulse(max_abs_v=3.0, max_width_s=1e-3, max_duty=0.5,
                                                               max_count=1_000_000))),
         (F("confirm", V_TRAIN, 3.0, DUTF + "terminals.gate.pulse.max_abs_v", "dut_envelope"),)),
    Case("pulse2-pulses-per-run-above-dut", "R-PULSE-02", partial(v2.spgu, [train(repeat=2000)]),
         (F("confirm", 2_000_000, 1_000_000, DUTF + "terminals.gate.pulse.max_count", "dut_envelope"),)),
    Case("pulse2-width-and-duty-above-dut", "R-PULSE-02",
         partial(v2.smu_pulse, [smu_train(width_s=1.2, period_s=1.5)]),
         (F("confirm", 1.2, 1.0, DUTN + "terminals.gate.pulse.max_width_s", "dut_envelope"),
          F("confirm", ANY, 0.5, DUTN + "terminals.gate.pulse.max_duty", "dut_envelope"))),
    # R-PULSE-03
    Case("pulse3-ok", "R-PULSE-03", v2.spgu),
    Case("pulse3-level", "R-PULSE-03", partial(v2.spgu, [train(peak_v=6.0)], gate=GATE_TALL),
         (F("confirm", ANY, 5.0, POL + "pulse.soft_abs_v", "soft_pulse"),)),
    Case("pulse3-count", "R-PULSE-03", partial(v2.spgu, [train(count=20000)]),
         (F("confirm", 20000, 10000, POL + "pulse.soft_count", "soft_pulse"),)),
    Case("pulse3-on-time", "R-PULSE-03", partial(v2.smu_pulse, [smu_train(width_s=1.0, period_s=2.0, count=100)]),
         (F("confirm", 100.0, 60.0, POL + "pulse.soft_on_time_s", "soft_pulse"),)),
    Case("pulse3-duty", "R-PULSE-03", partial(v2.smu_pulse, [smu_train(width_s=6e-3, period_s=1e-2)]),
         (F("confirm", ANY, 0.5, POL + "pulse.max_duty", "soft_pulse"),)),
    # R-SPGU-01
    Case("spgu-ok-no-spgu", "R-SPGU-01", v2.smu_pulse),
    Case("spgu-ok-high-z-residual", "R-SPGU-01", v2.spgu,
         (F("info", V_TRAIN / 50.0, None, DUTF + "terminals.gate.impedance"),)),
    Case("spgu-ok-resistive-bounded", "R-SPGU-01",
         partial(v2.spgu, gate=v2.terminal(impedance="resistive", min_series_ohm=1000.0)),
         (F("info", V_TRAIN / 1050.0, 0.1, HARD_A),)),
    Case("spgu-no-ser-load", "R-SPGU-01", partial(v2.spgu, [train(load_ohm=None)]),
         (F("block", None, "load_ohm", "plan:program.sources.pulses.101[0].load_ohm"),
          F("block", 8.0, 5.0, DUTF + "terminals.gate.pulse.max_abs_v"),
          F("block", 50.0, 1000.0, f"{SPGU_SRC}.high_z_min_load_ohm"),
          F("info", 0.16, None, DUTF + "terminals.gate.impedance"))),
    Case("spgu-open-load-above-module", "R-SPGU-01",
         partial(v2.spgu, [train(peak_v=21.0, load_ohm=50.0)],
                 gate=v2.terminal(GATE_TALL, impedance="unknown",
                                  pulse=TerminalPulse(max_abs_v=50.0, max_width_s=1e-3, max_duty=0.5,
                                                      max_count=1_000_000))),
         (F("block", 42.0, 40.0, f"{SPGU_SRC}.max_open_v (UG p76 (2-36))"),
          F("block", 0.84, 0.1, HARD_A))),
    Case("spgu-short-circuit-unknown-impedance", "R-SPGU-01",
         partial(v2.spgu, [train(peak_v=6.0)], gate=v2.terminal(GATE_TALL, impedance="unknown")),
         (F("block", ANY, 0.1, HARD_A),)),
    Case("spgu-high-z-with-small-ser", "R-SPGU-01", partial(v2.spgu, [train(peak_v=2.0, load_ohm=999.0)]),
         (F("block", 999.0, 1000.0, f"{SPGU_SRC}.high_z_min_load_ohm"),
          F("info", ANY, None, DUTF + "terminals.gate.impedance"))),
    Case("spgu-open-load-above-hard-limit", "R-SPGU-01",
         partial(v2.spgu, [train(peak_v=12.0, load_ohm=50.0)],
                 gate=v2.terminal(GATE_TALL, impedance="resistive", min_series_ohm=1000.0,
                                  pulse=TerminalPulse(max_abs_v=30.0, max_width_s=1e-3, max_duty=0.5,
                                                      max_count=1_000_000)),
                 cfg_policy=Policy(hard_limits=HardLimits(max_abs_voltage_v=20.0),
                                   soft_limits=SoftLimits(voltage_v=5.0))),
         (F("block", 24.0, 20.0, POL + "hard_limits.max_abs_voltage_v"), F("info", ANY, 0.1, HARD_A))),
    # R-ROUTE-01
    Case("route1-ok", "R-ROUTE-01", v2.spgu),
    Case("route1-ok-no-routes", "R-ROUTE-01", context),
    Case("route1-ok-rest-in-phase", "R-ROUTE-01",
         partial(v2.spgu, routes_by_phase={"main": [v2.SEL1_PGU, v2.SEL1_OPEN]})),
    Case("route1-ok-pre-at-rest", "R-ROUTE-01",
         partial(v2.spgu, live=v2.live(switch_states=v2.at_rest(v2.lab_station()))), phase="pre_execute"),
    Case("route1-pgu-open-on-ch2", "R-ROUTE-01",
         partial(v2.spgu, routes=[v2.SEL1_PGU, SEL1_PGU_OPEN_CH2],
                 routes_by_phase={"main": [v2.SEL1_PGU], "idle": [SEL1_PGU_OPEN_CH2]}),
         (F("block", "pgu_open", "open, pgu, pgu_open, smu", STA + "switches[0].ports.OUT2"),)),
    Case("route1-undeclared-switch", "R-ROUTE-01",
         partial(v2.spgu, routes=[v2.SEL1_PGU, SEL9], routes_by_phase={"main": [v2.SEL1_PGU], "x": [SEL9]}),
         (F("block", "SEL9.OUT1->smu", "SEL1, SEL2, RSU201, RSU202, SCUU1, ASU3, ASU4", STA + "switches"),)),
    Case("route1-visa-presence-unknown", "R-ROUTE-01",
         partial(v2.spgu, backend="visa", station_profile=v2.lab_station(sel1={"present": None})),
         (F("block", None, True, STA + "switches[0].present"),)),
    Case("route1-phase-route-outside-envelope", "R-ROUTE-01",
         partial(v2.spgu, routes_by_phase={"main": [v2.SEL1_PGU], "read": [v2.SEL1_SMU]}),
         (F("block", "SEL1.OUT1->smu", "envelope.routes", "plan:routes_by_phase.read[0]"),)),
    Case("route1-two-sources-in-one-phase", "R-ROUTE-01",
         partial(v2.spgu, routes=[v2.SEL1_PGU, v2.SEL1_SMU], routes_by_phase={"main": [v2.SEL1_PGU, v2.SEL1_SMU]}),
         (F("block", "pgu, smu", "one source", "plan:routes_by_phase.main"),)),
    Case("route1-allowed-route-unused", "R-ROUTE-01",
         partial(v2.spgu, routes=[v2.SEL1_PGU, v2.SEL1_SMU], routes_by_phase={"main": [v2.SEL1_PGU]}),
         (F("block", "SEL1.OUT1->smu", "a phase that applies it", "plan:envelope.routes"),)),
    Case("route1-routes-without-phases", "R-ROUTE-01", partial(v2.spgu, routes_by_phase={}),
         (F("block", None, "routes per phase", "plan:routes_by_phase"),)),
    Case("route1-kelvin-through-selector", "R-ROUTE-01",
         partial(context, rec=recipe(FORCE, roles=KELVIN), pm=pin_map(name="force-1", force="SEL1.OUT1"),
                 du=wide_dut(), station_profile=v2.lab_station(), routes=[v2.SEL1_SMU],
                 routes_by_phase={"main": [v2.SEL1_SMU]}, params={"v": 1.0, "icomp": 1e-3}),
         (F("block", "SEL1.OUT1->smu", "a direct SMU connection", "recipe:generic.smu_force@1#roles.force.kelvin"),)),
    Case("route1-pre-no-snapshot", "R-ROUTE-01", v2.spgu, (F("block", None, "a live snapshot", "live:snapshot"),),
         "pre_execute"),
    Case("route1-pre-states-not-read", "R-ROUTE-01", partial(v2.spgu, live=v2.live()),
         (F("block", None, "every declared output at rest", "live:switch_states"),), "pre_execute"),
    Case("route1-pre-not-at-rest", "R-ROUTE-01",
         partial(v2.spgu, live=v2.live(switch_states=v2.at_rest(v2.lab_station(), SEL2_OUT1="pgu"))),
         (F("block", "pgu", "open", "live:switch_states.SEL2.OUT1"),), "pre_execute"),
    Case("route1-pre-unreadable", "R-ROUTE-01",
         partial(v2.spgu, live=v2.live(switch_states={k: s for k, s in v2.at_rest(v2.lab_station()).items()
                                                      if k != "SEL1.OUT2"})),
         (F("block", None, "open", "live:switch_states.SEL1.OUT2"),), "pre_execute"),
    # R-ROUTE-02
    Case("route2-ok", "R-ROUTE-02", v2.spgu),
    Case("route2-ok-no-routes", "R-ROUTE-02", context),
    Case("route2-unverified-switch", "R-ROUTE-02",
         partial(v2.spgu, station_profile=v2.lab_station(sel1={"certainty": "unverified"})),
         (F("confirm", "unverified", "verified", STA + "switches[0].certainty", "unverified_topology"),)),
    Case("route2-unverified-pin-map", "R-ROUTE-02", partial(v2.spgu, pm_certainty="unverified"),
         (F("confirm", "unverified", "verified", "config/local/pinmaps/fefet-sel.yaml#certainty",
            "unverified_topology"),)),
    # R-CMU-01
    Case("cmu1-ok", "R-CMU-01", v2.cv),
    Case("cmu1-ok-no-cmu", "R-CMU-01", context),
    Case("cmu1-frequency-above-module", "R-CMU-01",
         partial(v2.cv, AcEnvelope(max_vrms=0.03, max_dc_v=2.0, f_min_hz=1e6, f_max_hz=1e7)),
         (F("block", 1e7, "1000..5e+06", CMU_SRC),)),
    Case("cmu1-ac-above-module-and-dut", "R-CMU-01",
         partial(v2.cv, AcEnvelope(max_vrms=0.3, max_dc_v=2.0, f_min_hz=1e6, f_max_hz=1e6)),
         (F("block", 0.3, "0.01..0.25", CMU_SRC), F("block", 0.3, 0.1, DUTM + "terminals.bulk.ac.max_vrms"),
          F("block", 0.3, 0.1, DUTM + "terminals.gate.ac.max_vrms"),
          F("confirm", 0.3, 0.05, POL + "cmu.soft_ac_vrms", "soft_cmu"))),
    Case("cmu1-dc-above-module", "R-CMU-01",
         partial(v2.cv, AcEnvelope(max_vrms=0.03, max_dc_v=30.0, f_min_hz=1e6, f_max_hz=1e6), v=(-30.0, 30.0)),
         (F("block", 30.0, 25.0, CMU_SRC), F("confirm", 30.0, 10.0, POL + "cmu.soft_dc_bias_v", "soft_cmu"))),
    Case("cmu1-terminal-without-ac", "R-CMU-01", partial(v2.cv, bulk=v2.MOSCAP.model_copy(update={"ac": None})),
         (F("block", None, "an ac envelope", DUTM + "terminals.bulk.ac"),)),
    Case("cmu1-no-ac-envelope", "R-CMU-01", partial(v2.cv, None),
         (F("block", None, "an AC envelope", "plan:envelope.channels.7.ac"),)),
    Case("cmu1-soft-dc-bias", "R-CMU-01",
         partial(v2.cv, AcEnvelope(max_vrms=0.03, max_dc_v=12.0, f_min_hz=1e6, f_max_hz=1e6), v=(-12.0, 12.0)),
         (F("confirm", 12.0, 10.0, POL + "cmu.soft_dc_bias_v", "soft_cmu"),)),
    Case("cmu1-soft-ac-level", "R-CMU-01",
         partial(v2.cv, AcEnvelope(max_vrms=0.08, max_dc_v=2.0, f_min_hz=1e6, f_max_hz=1e6)),
         (F("confirm", 0.08, 0.05, POL + "cmu.soft_ac_vrms", "soft_cmu"),)),
    # R-CORR-01 (v2: records in use, multi-record coverage, live part)
    Case("corr2-ok-in-use", "R-CORR-01", v2.cv, (F("info", 2.5, 8.0, CORR_FILE),)),
    Case("corr2-ok-each-frequency-covered-by-some-record", "R-CORR-01",
         partial(v2.cv, rec=TWO_FREQ, corrections=corr_split()), (F("info", 2.5, 8.0, CORR_FILE),)),
    Case("corr2-frequency-covered-by-no-record", "R-CORR-01",
         partial(v2.cv, rec=TWO_FREQ, corrections={"CMU1": [v2.corr("phase"), v2.corr("open", freqs=(1e6,)),
                                                            v2.corr("short", freqs=(1e3, 1e6))]}),
         (F("block", 1e3, "1e+06", CORR_FILE),)),
    Case("corr2-ok-pre", "R-CORR-01", partial(v2.cv, live=v2.live(cmu_corrections=v2.CORR_ON)),
         phase="pre_execute"),
    Case("corr2-pre-no-snapshot", "R-CORR-01", v2.cv, (F("block", None, "a live snapshot", "live:snapshot"),),
         "pre_execute"),
    Case("corr2-pre-state-not-read", "R-CORR-01", partial(v2.cv, live=v2.live()),
         (F("block", None, "corrections on", "live:cmu_corrections"),), "pre_execute"),
    Case("corr2-pre-open-lost", "R-CORR-01",
         partial(v2.cv, live=v2.live(cmu_corrections={"CMU1": CmuCorrectionLive(
             corr_state={"open": False, "short": True}, phase=True)})),
         (F("block", False, True, "live:cmu_corrections.CMU1.corr_state.open"),), "pre_execute"),
    Case("corr2-pre-phase-lost", "R-CORR-01",
         partial(v2.cv, live=v2.live(cmu_corrections={"CMU1": CmuCorrectionLive(
             corr_state={"open": True, "short": True}, phase=False)})),
         (F("block", False, True, "live:cmu_corrections.CMU1.phase"),), "pre_execute"),
    Case("corr2-pre-other-mainframe", "R-CORR-01",
         partial(v2.cv, live=v2.live(cmu_corrections=v2.CORR_ON),
                 corrections={"CMU1": [v2.corr(k, idn="Keysight Technologies,B1500A,OTHER,A.06")
                                       for k in ("phase", "open", "short")]}),
         tuple(F("block", "Keysight Technologies,B1500A,SIM1,A.06", "Keysight Technologies,B1500A,OTHER,A.06",
                 "live:identity") for _ in range(3)), "pre_execute"),
    Case("corr2-plan-with-live-state", "R-CORR-01",
         partial(v2.cv, live=v2.live(cmu_corrections={"CMU1": CmuCorrectionLive(corr_state={"open": True},
                                                                                phase=True)})),
         (F("info", 2.5, 8.0, CORR_FILE), F("block", None, True, "live:cmu_corrections.CMU1.corr_state.short"))),
    # R-WG-01
    Case("wg1-ok", "R-WG-01", v2.wgfmu),
    Case("wg1-ok-no-wgfmu", "R-WG-01", context),
    Case("wg1-ok-pre", "R-WG-01", partial(v2.wgfmu, live=v2.live(wgfmu_channels=[201, 202])), phase="pre_execute"),
    Case("wg1-not-through-rsu", "R-WG-01", partial(v2.wgfmu, top_target=201),
         (F("block", 201, "an RSU route to wgfmu", "config/local/pinmaps/fecap-wgfmu.yaml#terminals.top"),)),
    Case("wg1-pre-no-snapshot", "R-WG-01", v2.wgfmu, (F("block", None, "a live snapshot", "live:snapshot"),),
         "pre_execute"),
    Case("wg1-pre-channels-not-read", "R-WG-01", partial(v2.wgfmu, live=v2.live()),
         (F("block", None, "the bound channels", "live:wgfmu_channels"),), "pre_execute"),
    Case("wg1-pre-channel-missing", "R-WG-01", partial(v2.wgfmu, live=v2.live(wgfmu_channels=[201])),
         (F("block", 202, "201", "live:wgfmu_channels"),), "pre_execute"),
    Case("wg1-visa-32-bit-library", "R-WG-01",
         partial(v2.wgfmu, backend="visa", live=v2.live(backend="visa", wgfmu_channels=[201, 202],
                                                        wgfmu_library=v2.probe(machine="x86", loadable=False))),
         (F("block", "x86", "a loadable x64 library", "live:wgfmu_library"),)),
    Case("wg1-pre-visa-not-probed", "R-WG-01",
         partial(v2.wgfmu, backend="visa", live=v2.live(backend="visa", wgfmu_channels=[201, 202])),
         (F("block", None, "a loadable x64 library", "live:wgfmu_library"),), "pre_execute"),
    Case("wg1-ok-pre-visa", "R-WG-01",
         partial(v2.wgfmu, backend="visa", live=v2.live(backend="visa", wgfmu_channels=[201, 202],
                                                        wgfmu_library=v2.probe())), phase="pre_execute"),
    # R-WG-02
    Case("wg2-ok", "R-WG-02", v2.wgfmu),
    Case("wg2-ok-no-wgfmu", "R-WG-02", context),
    Case("wg2-no-program", "R-WG-02", partial(v2.wgfmu, None),
         (F("block", None, "a waveform program", WAVE),)),
    Case("wg2-no-waveform-envelope", "R-WG-02", partial(v2.wgfmu, limits={201: v2.wg_limits()}),
         (F("block", 202, "waveform limits", "plan:envelope.waveform"),)),
    Case("wg2-program-drives-an-unbound-channel", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("channels", "101"), {"mode": "fastiv"})),
         (F("block", 101, "201, 202", WAVE + ".channels"),)),
    Case("wg2-pg-mode-range-3302", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("channels", "201"), {"mode": "pg", "force_range": "10v"})),
         (F("block", "10v", "3v, 5v, auto", WG),)),
    Case("wg2-current-in-pg-mode-3303", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("channels", "202", "mode"), "pg")),
         (F("block", "pg", "fastiv, dc", WG),)),
    Case("wg2-2049-vectors-3307", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("patterns", "drive", "vectors"), [[1e-8, 0.0]] * 2049)),
         (F("block", 2049, 2048, WG), F("block", 2049, 2048, "plan:envelope.waveform.201"))),
    Case("wg2-ok-2048-vectors", "R-WG-02",
         partial(v2.wgfmu, mutate=_chain(_set(("patterns", "drive", "vectors"), [[1e-8, 0.0]] * 2048),
                                         _event(0, points=2047)))),
    Case("wg2-off-grid-vector-3311", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("patterns", "drive", "vectors", 3), [1.0015e-6, 0.0])),
         (F("block", 1.0015e-6, 1e-8, WG),)),
    Case("wg2-level-outside-range-3310", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("channels", "201", "force_range"), "-10v")),
         (F("block", 3.0, "-10..0", WG),)),
    Case("wg2-level-above-envelope", "R-WG-02", partial(v2.wgfmu, entry_v=2.5),
         (F("block", 3.0, 2.5, "plan:envelope.channels.201.max_abs_v"),)),
    Case("wg2-513-sequences-3305", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("sequences", "201"), [["drive", 1]] * 513)),
         (F("block", 513, 512, WG),)),
    Case("wg2-ok-512-sequences", "R-WG-02",
         partial(v2.wgfmu, mutate=_set(("sequences", "201"), [["drive", 1]] * 512))),
    Case("wg2-sequence-count-3309", "R-WG-02", partial(v2.wgfmu, mutate=_set(("sequences", "201"), [["drive", 0]])),
         (F("block", 0.0, ANY, WG),)),
    Case("wg2-empty-pattern-3306", "R-WG-02",
         partial(v2.wgfmu, mutate=_chain(_set(("patterns", "idle"), {"v0": 0.0, "vectors": []}),
                                         _set(("sequences", "201"), [["drive", 10], ["idle", 1]]))),
         (F("block", "idle", "at least one vector", WG),)),
    Case("wg2-interval-3312", "R-WG-02", partial(v2.wgfmu, mutate=_event(0, points=1, interval=2.0)),
         (F("block", 2.0, "1e-08..1.34218", WG),)),
    Case("wg2-average-range-3315", "R-WG-02",
         partial(v2.wgfmu, mutate=_chain(_event(1, points=1, interval=0.05, average=0.03),
                                         _set(("patterns", "sense", "vectors"), [[0.04, 0.0]]))),
         (F("block", 0.03, "0 or 1e-08..0.0209715", WG),)),
    Case("wg2-average-above-interval-3316", "R-WG-02",
         partial(v2.wgfmu, mutate=_event(1, points=10, interval=1e-8, average=2e-8)),
         (F("block", 2e-8, 1e-8, WG),)),
    Case("wg2-event-time-off-grid", "R-WG-02", partial(v2.wgfmu, mutate=_event(0, t=5e-9, points=300)),
         (F("block", 5e-9, 1e-8, WG),)),
    Case("wg2-event-after-pattern", "R-WG-02", partial(v2.wgfmu, mutate=_event(0, points=1000)),
         (F("block", ANY, ANY, WG),)),
    Case("wg2-range-event-on-voltage-channel", "R-WG-02",
         partial(v2.wgfmu, mutate=_add_event(kind="range", pattern="drive", event="r", t=1e-6, range="10ma")),
         (F("block", "fastiv/voltage", "fastiv/current", WG),)),
    Case("wg2-ok-range-event", "R-WG-02",
         partial(v2.wgfmu, mutate=_chain(_event(1, average=0.0),
                                         _add_event(kind="range", pattern="sense", event="r", t=1e-6,
                                                    range="10ma")))),
    Case("wg2-ok-dc-levels", "R-WG-02", partial(v2.wgfmu, mutate=_dc_top([-1.0, 0.0, 2.5]))),
    Case("wg2-dc-level-outside-range", "R-WG-02", partial(v2.wgfmu, mutate=_dc_top([0.0, 3.5])),
         (F("block", 3.5, "-3..3", WG), F("block", 3.5, 3.0, "plan:envelope.channels.201.max_abs_v"))),
    Case("wg2-dc-level-in-the-negative-range", "R-WG-02", partial(v2.wgfmu, mutate=_dc_top([-0.5, 0.5], "-10v")),
         (F("block", 0.5, "-10..0", WG),)),
    Case("wg2-range-events-too-close", "R-WG-02",
         partial(v2.wgfmu, mutate=_chain(_event(1, average=0.0), *(
             _add_event(kind="range", pattern="sense", event=f"r{i}", t=i * 1e-6, range="10ma") for i in range(3)))),
         (F("block", 1e-6, 2e-6, WG),)),
    Case("wg2-range-event-inside-averaging", "R-WG-02",
         partial(v2.wgfmu, mutate=_chain(_event(1, points=40, interval=1e-7, average=5e-8),
                                         _add_event(kind="range", pattern="sense", event="r", t=1.2e-7,
                                                    range="10ma"))),
         (F("block", 1.2e-7, "outside 1e-07..1.5e-07 s", WG),)),
    Case("wg2-points-above-policy", "R-WG-02",
         partial(v2.wgfmu, cfg_policy=Policy(run_limits={"max_points": {"wgfmu": 1000}})),
         (F("block", 4000, 1000, POL + "run_limits.max_points.wgfmu"),
          F("block", 4000, 1000, POL + "run_limits.max_points.wgfmu"))),
    Case("wg2-points-above-module", "R-WG-02", partial(v2.wgfmu, mutate=_set(("sequences", "201"), [["drive", 20000]])),
         (F("block", 8_000_000, 4_000_000, POL + "run_limits.max_points.wgfmu"),
          F("block", 8_000_000, 4_000_000, "plan:envelope.waveform.201"))),
    Case("wg2-time-above-envelope", "R-WG-02",
         partial(v2.wgfmu, limits={201: v2.wg_limits(total_time_s=1e-5), 202: v2.wg_limits()}),
         (F("block", ANY, 1e-5, "plan:envelope.waveform.201"),)),
    Case("wg2-envelope-grid", "R-WG-02",
         partial(v2.wgfmu, limits={201: v2.wg_limits(grid_s=2e-8), 202: v2.wg_limits()}),
         (F("block", 2e-8, 1e-8, "plan:envelope.waveform.201"),)),
    # R-RUN-02
    Case("run2-ok-sync", "R-RUN-02", partial(context, duration_s=100.0)),
    Case("run2-sync-too-long", "R-RUN-02", partial(context, duration_s=400.0),
         (F("block", 400.0, 300.0, POL + "run_limits.max_sync_run_s"),)),
    Case("run2-async-info", "R-RUN-02", partial(context, duration_s=400.0, mode="async", max_segment_s=10.0),
         (F("info", 400.0, 300.0, POL + "run_limits.max_sync_run_s"),)),
    Case("run2-long-run-confirm", "R-RUN-02", partial(context, duration_s=700.0, mode="async", max_segment_s=10.0),
         (F("info", 700.0, 300.0, POL + "run_limits.max_sync_run_s"),
          F("confirm", 700.0, 600.0, POL + "run_limits.long_run_confirm_s", "long_run"))),
    Case("run2-above-async-limit", "R-RUN-02",
         partial(context, duration_s=90000.0, mode="async", max_segment_s=10.0),
         (F("block", 90000.0, 86400.0, POL + "run_limits.max_async_run_s"),)),
    Case("run2-async-without-checkpoints", "R-RUN-02", partial(context, duration_s=400.0, mode="async"),
         (F("info", 400.0, 300.0, POL + "run_limits.max_sync_run_s"),
          F("block", None, 30.0, "plan:estimate.max_segment_s"))),
    Case("run2-segment-too-long", "R-RUN-02",
         partial(context, duration_s=400.0, mode="async", max_segment_s=60.0),
         (F("info", 400.0, 300.0, POL + "run_limits.max_sync_run_s"),
          F("block", 60.0, 30.0, POL + "run_limits.segment_max_s"))),
    # R-CAL-02
    Case("cal2-sync-nothing", "R-CAL-02", partial(context, live=live_state()), phase="pre_execute"),
    Case("cal2-async-recorded", "R-CAL-02",
         partial(context, duration_s=400.0, mode="async", max_segment_s=10.0, live=live_state(),
                 calibration=CALIBRATED),
         (F("info", True, False, "live:auto_calibration"),), "pre_execute"),
    Case("cal2-async-unknown", "R-CAL-02",
         partial(context, duration_s=400.0, mode="async", max_segment_s=10.0, live=live_state()),
         (F("info", None, False, "live:auto_calibration"),), "pre_execute"),
    # R-GNDU-01
    Case("gndu-ok", "R-GNDU-01", context),
    Case("gndu-ok-spgu-into-gndu", "R-GNDU-01", v2.spgu),
    Case("gndu-pulse-currents", "R-GNDU-01",
         partial(context, extra_envelope={101: pgu_entry("p1"), 102: pgu_entry("p2")}),
         (F("block", 5.001001, 4.2, f"{SPEC}.MODULE_SPECS[GNDU] (UG GNDU, PDF 58)"),)),
    Case("gndu-spgu-without-pulse-envelope", "R-GNDU-01",
         partial(context, extra_envelope={ch: ChannelEnvelope(role=f"p{ch}", max_abs_v=40.0, max_abs_i=None,
                                                              function="pgu")
                                          for ch in (101, 102, 301, 401, 501, 601)}),
         (F("block", ANY, 4.2, f"{SPEC}.MODULE_SPECS[GNDU] (UG GNDU, PDF 58)"),)),
    Case("gndu-ok-no-role-on-gndu", "R-GNDU-01",
         partial(context, pm=pin_map(source=6), extra_envelope={101: pgu_entry("p1"), 102: pgu_entry("p2")})),
    # R-ASU-01
    Case("asu-ok-nanoamp-range", "R-ASU-01", partial(context, rec=v2.IRANGE_REC)),
    Case("asu-ok-picoamp-with-asu", "R-ASU-01",
         partial(context, rec=v2.IRANGE_REC, params={"irange": 1e-12},
                 station_profile=v2.lab_station(asu3={"present": True}))),
    Case("asu-picoamp-asu-presence-unknown", "R-ASU-01", partial(context, rec=v2.IRANGE_REC, params={"irange": 1e-12}),
         (F("block", None, True, STA + "switches[5].present"),)),
    Case("asu-picoamp-without-asu", "R-ASU-01",
         partial(context, rec=v2.IRANGE_REC, params={"irange": 1e-11}, pm=pin_map(drain=6)),
         (F("block", None, "an asu switch on channel 6", STA + "switches"),)),
    Case("asu-no-such-range", "R-ASU-01", partial(context, rec=v2.IRANGE_REC, params={"irange": 1.0}),
         (F("block", 1.0, ANY, f"{SPEC}.MODULE_SPECS[HRSMU]"),)),
    # v1 rules, v2 changes
    Case("lim1-ok-wgfmu-in-spec", "R-LIM-01", v2.wgfmu),
    Case("lim1-ok-cmu-in-spec", "R-LIM-01", v2.cv),
    Case("lim1-wgfmu-above-10v", "R-LIM-01", partial(v2.wgfmu, entry_v=12.0),
         (F("block", 12.0, 10.0, f"{SPEC}.WGFMU_SPEC.max_abs_v (WG p16 (1-4))"),
          F("block", 12.0, 10.0, f"{SPEC}.WGFMU_SPEC.max_abs_v (WG p16 (1-4))"))),
    Case("lim1-current-forcing-uses-i-corners", "R-LIM-01",
         partial(context, rec=recipe(FORCE, roles=CURRENT_FORCE), pm=pin_map(name="force-1", force=5),
                 du=wide_dut(), extra_envelope={5: CURRENT_ENTRY.model_copy(update={"max_abs_v": 30.0,
                                                                                   "max_abs_i": 0.08})}),
         (F("block", "0.08 A @ 30 V", "0.02 A @ 100 V, 0.05 A @ 40 V, 0.1 A @ 20 V",
            f"{SPEC}.MODULE_SPECS[MPSMU] (PG Tables 4-6/4-7, PDF 341-342)"),)),
    Case("comp-ok-current-source-with-vcomp", "R-COMP-01",
         partial(context, rec=recipe(FORCE, roles=CURRENT_FORCE), pm=pin_map(name="force-1", force=5),
                 du=wide_dut(), extra_envelope={5: CURRENT_ENTRY})),
    Case("comp-current-source-without-vcomp", "R-COMP-01",
         partial(context, rec=recipe(FORCE, roles={**CURRENT_FORCE, "force": {**CURRENT_FORCE["force"],
                                                                              "settings": {"i": "$icomp"}}}),
                 pm=pin_map(name="force-1", force=5), du=wide_dut(), extra_envelope={5: CURRENT_ENTRY}),
         (F("block", None, "non-zero compliance", "recipe:generic.smu_force@1#roles.force.settings.vcomp"),)),
    Case("comp-ok-pgu-exempt", "R-COMP-01", v2.spgu),
    Case("comp-ok-wgfmu-exempt", "R-COMP-01", v2.wgfmu),
    Case("always-physical-setup-for-correction-kinds", "R-ALWAYS-01",
         partial(context, rec=recipe(CMU, kind="cmu_correction")),
         (F("confirm", "cmu_correction", None, "code:b1500_test_agent.rules.builtin.run.PHYSICAL_SETUP_KINDS",
            "physical_setup"),)),
    Case("always-physical-setup-declared-once", "R-ALWAYS-01",
         partial(context, rec=recipe(CMU, kind="cmu_correction", always_confirm=["physical_setup"])),
         (F("confirm", "physical_setup", None, "recipe:mosfet.cgg_cv@1#always_confirm", "physical_setup"),)),
    Case("pin-ok-both-mfcmu-sides", "R-PIN-01", v2.cv),
    Case("pin-ok-spgu-through-selector", "R-PIN-01", v2.spgu),
    Case("pin-ok-wgfmu-through-rsu", "R-PIN-01", v2.wgfmu),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_rule_table_v2(case: Case) -> None:
    cfg, ctx = case.build()
    report = engine(cfg).evaluate(ctx, case.phase)  # type: ignore[arg-type]
    mine = [f for f in report.findings if f.rule_id == case.rule_id]
    assert [F(f.severity, f.observed, f.limit, f.source, f.reason) for f in mine] == list(case.expect)
    for finding in mine:
        assert finding.message and finding.message.isascii()
    assert not [f for f in report.findings if "failed (" in f.message], "a rule crashed (fail closed)"


@pytest.mark.parametrize("build", [v2.spgu, v2.smu_pulse, v2.wgfmu, v2.cv], ids=["spgu", "smu", "wgfmu", "cv"])
def test_default_v2_plans_are_ok(build: Any) -> None:
    """Each builder's default plan is in spec and inside every band: tier ok, no block or confirm anywhere."""
    cfg, ctx = build()
    report = engine(cfg).evaluate(ctx, "plan")
    assert report.tier == "ok", [(f.rule_id, f.message) for f in report.findings if f.severity != "info"]


def test_new_rule_outcomes_are_covered() -> None:
    """Every outcome of the blueprint v2 2.8 table appears in the rows: block, confirm per new reason, info."""
    seen = {(c.rule_id, f.severity, f.reason) for c in CASES for f in c.expect}
    for row in [
        ("R-PULSE-01", "block", None), ("R-PULSE-02", "block", None), ("R-PULSE-02", "confirm", "dut_envelope"),
        ("R-PULSE-03", "confirm", "soft_pulse"), ("R-SPGU-01", "block", None), ("R-SPGU-01", "info", None),
        ("R-ROUTE-01", "block", None), ("R-ROUTE-02", "confirm", "unverified_topology"),
        ("R-CMU-01", "block", None), ("R-CMU-01", "confirm", "soft_cmu"), ("R-CORR-01", "block", None),
        ("R-CORR-01", "info", None), ("R-WG-01", "block", None), ("R-WG-02", "block", None),
        ("R-RUN-02", "info", None), ("R-RUN-02", "confirm", "long_run"), ("R-RUN-02", "block", None),
        ("R-GNDU-01", "block", None), ("R-ASU-01", "block", None), ("R-CAL-02", "info", None),
        ("R-ALWAYS-01", "confirm", "physical_setup"),
    ]:
        assert row in seen, row
    phases = {(c.rule_id, c.phase) for c in CASES if c.expect}
    for rule_id in ("R-ROUTE-01", "R-CORR-01", "R-WG-01"):
        assert (rule_id, "pre_execute") in phases and (rule_id, "plan") in phases


# -- SER arithmetic (R-SPGU-01, decision 9, ATV-20) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("v_set", "ser", "open_v"),
    [(4.0, 50.0, 8.0), (2.0, 50.0, 4.0), (20.0, 50.0, 40.0), (-3.0, 50.0, 6.0), (4.0, 1e6, 4.0002),
     (2.0, 1000.0, 2.1), (1.0, 0.1, 501.0), (4.0, None, 8.0)],
)
def test_ser_open_load_voltage(v_set: float, ser: float | None, open_v: float) -> None:
    """``|V| (SER + 50) / SER``: 50 Ohm declared on an open (high_z) load doubles the set level; without a SER the
    initial 50 Ohm applies (the 2x worst case)."""
    assert SPGU_SPEC.open_load_v(abs(v_set), ser) == pytest.approx(open_v, rel=1e-12)
    assert open_load_voltage(v_set, load_ohm=ser, source_ohm=50.0) == pytest.approx(open_v, rel=1e-12)
    assert open_load_voltage(v_set, load_ohm=ser, source_ohm=None) == abs(v_set)  # SMU pulse / WGFMU: set level


@pytest.mark.parametrize(
    ("open_v", "series", "isc"),
    [(8.0, 0.0, 0.16), (4.0002, 0.0, 0.080004), (4.0002, 1000.0, 4.0002 / 1050), (40.0, 0.0, 0.8),
     (5.0, 0.0, 0.1)],
)
def test_short_circuit_current_table(open_v: float, series: float, isc: float) -> None:
    """``V_open / (50 + min_series_ohm)``: a short at the output of a 40 V SPGU draws 0.8 A."""
    assert short_circuit_current(open_v, source_ohm=50.0, series_ohm=series) == pytest.approx(isc, rel=1e-12)


@pytest.mark.parametrize(
    ("peak", "ser", "impedance", "series", "tier", "blocked"),
    [
        (2.0, 50.0, "high_z", None, "blocked", {"R-SPGU-01"}),            # 50 Ohm on high_z: x2 -> blocked
        (2.0, 1e6, "high_z", None, "ok", set()),                          # residual Isc 0.04 A, shown in the summary
        (4.0, 1e6, "resistive", 1000.0, "ok", set()),                     # 3.8 mA into the series resistance
        (6.0, 1e6, "resistive", 0.0, "blocked", {"R-SPGU-01"}),           # 0.12 A into a short
        (4.0, 1e6, "unknown", None, "ok", set()),                         # 0.08 A <= 0.1 A
        (6.0, 1e6, "unknown", None, "blocked", {"R-SPGU-01"}),            # unknown = a short: 0.12 A
        (3.0, 1000.0, "high_z", None, "ok", set()),                       # 3.15 V open load inside 5 V
        (2.5, 50.0, "unknown", None, "ok", set()),                        # 5 V open, 0.1 A: at the limit
    ],
)
def test_spgu_outcome_table(peak: float, ser: float, impedance: str, series: float | None, tier: str,
                            blocked: set[str]) -> None:
    gate = v2.terminal(impedance=impedance, min_series_ohm=series)
    cfg, ctx = v2.spgu([train(peak_v=peak, load_ohm=ser)], gate=gate)
    report = engine(cfg).evaluate(ctx, "plan")
    assert report.tier == tier
    assert {f.rule_id for f in report.findings if f.severity == "block"} == blocked


# -- Correction-record source ----------------------------------------------------------------------------------------


def test_correction_records_reads_every_mfcmu_from_the_source() -> None:
    calls: list[str] = []

    def records_for(cmu_alias: str) -> list[CorrectionRecord]:  # the archive/corrections.py shape
        calls.append(cmu_alias)
        return v2.CORRECTED.get(cmu_alias, [])

    source: CorrectionRecordSource = records_for
    records = correction_records(v2.lab_station(), source)
    assert calls == ["CMU1"] and records == {"CMU1": v2.CORRECTED["CMU1"]}
    assert correction_records(v2.lab_station(), None) == {}


def test_store_backed_context_lets_r_corr_01_pass() -> None:
    cfg, ctx = v2.cv(corrections={})
    blocked = engine(cfg).evaluate(ctx, "plan")
    assert {f.rule_id for f in blocked.findings if f.severity == "block"} == {"R-CORR-01"}
    stored = ctx.model_copy(update={"corrections": correction_records(ctx.station, v2.CORRECTED.__getitem__)})
    assert engine(cfg).evaluate(stored, "plan").tier == "ok"


# -- R-QUAL-*: MFCMU status codes and WGFMU flags --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("eee", "letter"),
    [(0, "N"), (128, "N"), (1, "V"), (2, "U"), (4, "D"), (64, "V"), (2 | 4, "D"), (1 | 2, "V"), (4 | 128, "D")],
)
def test_cmu_status_letters(eee: int, letter: str) -> None:
    assert cmu_status_letter(eee) == letter
    assert cmu_status_letter(int(CmuStatus(eee))) == letter


@pytest.mark.parametrize("eee", [8, 16, 32, 256, -1])
def test_cmu_status_letters_refuse_unassigned_bits(eee: int) -> None:
    with pytest.raises(ValueError):
        cmu_status_letter(eee)


def test_wgfmu_flags_map_to_v_and_x() -> None:
    assert wgfmu_status_letter(range_overflow=False, error=False) == "N"
    assert wgfmu_status_letter(range_overflow=True, error=False) == "V"
    assert wgfmu_status_letter(range_overflow=True, error=True) == "X"
    assert wgfmu_status_letter(range_overflow=False, error=True) == "X"


def test_quality_names_cmu_and_wgfmu_meanings() -> None:
    findings = quality_findings({"N": 10, "U": 2, "D": 1, "V": 3, "X": 1}, TrustPolicy(), source="s")
    assert [(f.rule_id, f.observed) for f in findings] == [("R-QUAL-01", 17), ("R-QUAL-03", 7)]
    text = findings[-1].message
    assert "CMU NULL loop unbalance" in text and "CMU IV amplifier saturation" in text
    assert "over range or aborted" in text and "oscillation or error" in text


def test_plan_routes_are_read_from_every_place() -> None:
    from b1500_test_agent.rules.builtin.common import plan_routes

    _, ctx = v2.spgu(routes_by_phase={"main": [v2.SEL1_PGU, v2.SEL1_OPEN]})
    where = [(str(r.route), r.where) for r in plan_routes(ctx)]
    assert where == [("SEL1.OUT1->pgu", "envelope.routes"), ("SEL1.OUT1->pgu", "routes_by_phase.main[0]"),
                     ("SEL1.OUT1->open", "routes_by_phase.main[1]"), ("SEL1.OUT1->pgu", "binding.roles.gate.via")]


def test_factory_programs_are_valid_models() -> None:
    program = v2.program_model()
    assert program.points(201) == 4000 and program.points(202) == 4000
    assert program.sequence_time_s(201) == pytest.approx(4e-5)
    data = copy.deepcopy(v2.wave())
    assert data["builder"] == "pund"
