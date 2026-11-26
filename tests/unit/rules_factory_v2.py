"""In-test plans for the v2 rules (pulse, SPGU, routes, MFCMU, WGFMU, run mode, GNDU, ASU) on the lab-shaped example
station: what a v2 kind would compile (channel envelopes with pulse/AC/waveform sub-envelopes, routes per phase, the
``SourcePlan`` under ``plan.program["sources"]``), built in memory on top of ``rules_factory.context``. Nothing is
written to ``config/local/``.

Defaults are in spec and inside every band, so each builder's default plan is ``ok`` on the simulator; a test changes
one thing to reach a confirm or block row.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from datetime import timedelta
from typing import Any

from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, PulseEnvelope, WaveformLimits
from b1500_test_agent.models.policy import DutProfile, DutTerminal, TerminalAc, TerminalPulse
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import SOURCE_PLAN_KEY, PulseTrain, SourcePlan, WaveformProgram, pulse_envelope
from b1500_test_agent.models.station import CmuCorrectionLive, CorrectionRecord, DllProbe, LiveState, StationProfile
from b1500_test_agent.rules.engine import RuleContext
from tests.unit.rules_factory import (
    IDVG,
    T0,
    ZERO_SHA,
    context,
    example_station,
    live_state,
    pin_map_exact,
    recipe,
    station,
)

Ctx = tuple[ConfigBundle, RuleContext]

QUALITY = {"limited": ["C", "T"], "untrusted": ["V", "X", "F", "D", "G", "S", "U"], "max_limited_fraction_in_fit": 0.05}
PROVENANCE = {"sources": ["WP5.4 rules test"], "validation_runs": []}


# -- Station ---------------------------------------------------------------------------------------------------------


def _switch(switch_id: str) -> dict[str, Any]:
    return next(s for s in example_station().switches if s.id == switch_id).model_dump(mode="json")


def lab_station(*, sel1: Mapping[str, Any] | None = None, rsu: Mapping[str, Any] | None = None,
                asu3: Mapping[str, Any] | None = None, rsu_smu: Mapping[int, int | None] | None = None
                ) -> StationProfile:
    """The example station with SEL1 wired (OUT1: SMU5/SPGU 101, OUT2: SMU6/SPGU 102), both RSUs and SEL1 verified
    and present; ``sel1``/``rsu``/``asu3`` replace fields of those switches. ``rsu_smu`` (WP21.13) records the SMU on
    an RSU's "From SMU" input by WGFMU channel (``{202: 3}``; ``None`` = unknown, which makes that RSU unverified);
    without it the RSUs have no SMU input (nothing cabled)."""
    switches = []
    for spec in example_station().switches:
        data = spec.model_dump(mode="json")
        if spec.id == "SEL1":
            data.update(certainty="verified", present=True,
                        ports={"OUT1": {"index": 0, "inputs": {"smu": 5, "pgu": 101}},
                               "OUT2": {"index": 1, "inputs": {"smu": 6, "pgu": 102}}})
            data.update(sel1 or {})
        elif spec.kind == "rsu":
            index = data["ports"]["OUT"]["index"]
            inputs: dict[str, int | None] = {"wgfmu": index}
            if rsu_smu is not None and index in rsu_smu:
                inputs["smu"] = rsu_smu[index]
            certainty = "unverified" if inputs.get("smu", 0) is None else "verified"
            data.update(certainty=certainty, ports={"OUT": {"index": index, "inputs": inputs}})
            data.update(rsu or {})
        elif spec.id == "ASU3":
            data.update(asu3 or {})
        switches.append(data)
    return station(switches=switches)


SEL1_PGU = Route(switch="SEL1", output="OUT1", state="pgu")
SEL1_SMU = Route(switch="SEL1", output="OUT1", state="smu")
SEL1_OPEN = Route(switch="SEL1", output="OUT1", state="open")
RSU201 = Route(switch="RSU201", output="OUT", state="wgfmu")
RSU202 = Route(switch="RSU202", output="OUT", state="wgfmu")


def at_rest(profile: StationProfile, **changes: str) -> dict[str, str]:
    """Live switch states: every declared output at rest, ``changes`` (``SEL1_OUT1="pgu"``) applied."""
    states = {f"{s.id}.{o}": s.rest for s in profile.switches for o in s.ports}
    states.update({k.replace("_", "."): v for k, v in changes.items()})
    return states


def live(profile: StationProfile | None = None, **fields: Any) -> LiveState:
    """``rules_factory.live_state`` plus v2 live fields."""
    base = live_state(profile or lab_station(), backend=fields.pop("backend", "sim"))
    return base.model_copy(update=fields)


# -- HV-SPGU pulse plans ---------------------------------------------------------------------------------------------

SPGU_REC: dict[str, Any] = {
    "id": "spgu.pulse_train",
    "version": 1,
    "title": "SPGU pulse train through SEL1",
    "family": "spgu",
    "kind": "spgu_pulse",
    "status": "sim_validated",
    "card": None,
    "device_types": ["fefet"],
    "roles": {
        "gate": {"function": "pgu", "module_types": ["HVSPGU"],
                 "settings": {"base": "$v_base", "peak": "$v_pulse", "width": "$width", "period": "$period",
                              "count": "$count", "load_ohm": "$load_ohm"}},
        "source": {"function": "ground", "allow_gndu": True},
    },
    "params": {
        "v_base": {"unit": "V", "default": 0.0, "range": [-40, 40]},
        "v_pulse": {"unit": "V", "default": 4.0, "range": [-40, 40]},
        "width": {"unit": "s", "default": 1e-6, "range": [1e-8, 10]},
        "period": {"unit": "s", "default": 1e-4, "range": [2e-8, 10]},
        "count": {"type": "int", "default": 1000, "range": [1, 1000000]},
        "load_ohm": {"unit": "Ohm", "default": 1e6, "range": [0.1, 1e6]},
    },
    "quality": QUALITY,
    "analysis_defaults": [],
    "provenance": PROVENANCE,
}

TRAIN = PulseTrain(base_v=0.0, peak_v=4.0, width_s=1e-6, period_s=1e-4, count=1000, load_ohm=1e6)
"""The blueprint 2.9 example: 0 -> 4 V, 1 us, x1000 at 10 kHz, SER 1 MOhm."""

FEFET_GATE = DutTerminal(max_abs_v=5.0, max_abs_i=1e-3, impedance="high_z",
                         pulse=TerminalPulse(max_abs_v=5.0, max_width_s=1e-3, max_duty=0.5, max_count=1_000_000))
RESISTIVE = DutTerminal(max_abs_v=1.0, max_abs_i=1e-3, impedance="resistive", min_series_ohm=1000.0)


def terminal(base: DutTerminal = FEFET_GATE, **changes: Any) -> DutTerminal:
    return base.model_copy(update=changes)


def spgu(trains: Iterable[PulseTrain] = (TRAIN,), *, gate: DutTerminal | None = FEFET_GATE,
         envelope: PulseEnvelope | None | str = "auto", entry_v: float | None = None,
         pm_certainty: str = "verified", station_profile: StationProfile | None = None,
         sources: Mapping[str, Any] | None = None, **kw: Any) -> Ctx:
    """``spgu.pulse_train`` on pin map ``fefet-sel`` (gate = SEL1.OUT1 -> SPGU 101, source GNDU) with DUT
    ``fefet-lab`` (gate high_z with a pulse envelope). ``envelope``: ``"auto"`` = the kind's envelope from the trains
    (``pulse_envelope`` with the SPGU's 50 Ohm), ``None`` = no pulse envelope; ``sources`` replaces the program's
    source plan (raw JSON)."""
    trains = list(trains)
    pulse = pulse_envelope(trains, source_ohm=50.0) if envelope == "auto" else envelope
    assert not isinstance(pulse, str)
    v_max = entry_v if entry_v is not None else (pulse.max_abs_v_dut if pulse is not None else 4.0)
    entry = ChannelEnvelope(role="gate", max_abs_v=v_max, max_abs_i=None, function="pgu", pulse=pulse)
    terminals = {"source": RESISTIVE}
    if gate is not None:
        terminals["gate"] = gate
    du = DutProfile(name="fefet-lab", device_type="fefet", terminals=terminals)
    pm = pin_map_exact("fefet-sel", {"gate": "SEL1.OUT1", "source": "GNDU"}, certainty=pm_certainty)
    program = {SOURCE_PLAN_KEY: dict(sources) if sources is not None
               else SourcePlan(pulses={101: trains}).model_dump(mode="json")}
    kw.setdefault("routes", [SEL1_PGU])
    kw.setdefault("routes_by_phase", {"main": [SEL1_PGU]})
    return context(rec=recipe(SPGU_REC), pm=pm, du=du, station_profile=station_profile or lab_station(),
                   extra_envelope={101: entry}, program=program, **kw)


# -- SMU pulse plans -------------------------------------------------------------------------------------------------

SMU_PULSE_REC: dict[str, Any] = {
    **copy.deepcopy(SPGU_REC),
    "id": "mosfet.idvg_pulsed",
    "title": "Pulsed gate on an SMU",
    "family": "smu",
    "kind": "smu_pulsed",
    "device_types": ["nmos"],
    "roles": {
        "gate": {"function": "pulse_v", "measure": ["I"], "module_types": ["MPSMU", "HRSMU"],
                 "settings": {"base": "$v_base", "peak": "$v_pulse", "width": "$width", "period": "$period",
                              "count": "$count", "icomp": "$icomp"}},
        "source": {"function": "ground", "allow_gndu": True},
    },
    "params": {
        "v_base": {"unit": "V", "default": 0.0, "range": [-10, 10]},
        "v_pulse": {"unit": "V", "default": 2.0, "range": [-10, 10]},
        "width": {"unit": "s", "default": 1e-3, "range": [1e-6, 2]},
        "period": {"unit": "s", "default": 1e-2, "range": [1e-3, 5]},
        "count": {"type": "int", "default": 10, "range": [1, 1000]},
        "icomp": {"unit": "A", "default": 1e-3, "range": [1e-9, 0.1]},
    },
}

SMU_TRAIN = PulseTrain(base_v=0.0, peak_v=2.0, width_s=1e-3, period_s=1e-2, count=10)
NMOS_GATE = DutTerminal(max_abs_v=3.0, max_abs_i=1e-3,
                        pulse=TerminalPulse(max_abs_v=3.0, max_width_s=1.0, max_duty=0.5, max_count=1000))


def smu_pulse(trains: Iterable[PulseTrain] = (SMU_TRAIN,), **kw: Any) -> Ctx:
    """``mosfet.idvg_pulsed``: an SMU pulse source (``pulse_v``) on SMU5 against the GNDU."""
    trains = list(trains)
    pulse = pulse_envelope(trains, source_ohm=None)
    entry = ChannelEnvelope(role="gate", max_abs_v=pulse.max_abs_v_dut, max_abs_i=1e-3, function="pulse_v",
                            pulse=pulse)
    du = DutProfile(name="nmos-pulse", device_type="nmos", terminals={"gate": NMOS_GATE, "source": RESISTIVE})
    pm = pin_map_exact("gate-5", {"gate": 5, "source": "GNDU"})
    program = {SOURCE_PLAN_KEY: SourcePlan(pulses={5: trains}).model_dump(mode="json")}
    return context(rec=recipe(SMU_PULSE_REC), pm=pm, du=du, station_profile=lab_station(),
                   extra_envelope={5: entry}, program=program, **kw)


# -- WGFMU plans -----------------------------------------------------------------------------------------------------

WG_REC: dict[str, Any] = {
    **copy.deepcopy(SPGU_REC),
    "id": "fecap.pund",
    "title": "PUND on the WGFMU",
    "family": "nvm",
    "kind": "wgfmu_waveform",
    "device_types": ["fecap"],
    "roles": {
        "top": {"function": "wgfmu", "module_types": ["WGFMU"]},
        "bottom": {"function": "wgfmu", "module_types": ["WGFMU"]},
    },
    "params": {"v_pulse": {"unit": "V", "default": 3.0, "range": [-10, 10]}},
}

FECAP = DutTerminal(max_abs_v=4.0, max_abs_i=1e-3, impedance="high_z",
                    pulse=TerminalPulse(max_abs_v=4.0, max_width_s=1e-3, max_duty=0.5, max_count=10_000_000),
                    ac=TerminalAc(max_vrms=0.1))


def wave(**changes: Any) -> dict[str, Any]:
    """A two-channel PUND-like program (JSON): 201 forces a 3 V triangle pair in Fast IV (voltage measured), 202 holds
    0 V and measures current (1 mA range); one measure event per channel pattern, 10 sequences each. ``changes``
    replace top-level fields."""
    program: dict[str, Any] = {
        "builder": "pund",
        "channels": {
            "201": {"mode": "fastiv", "force_range": "5v", "measure": "voltage", "voltage_range": "5v"},
            "202": {"mode": "fastiv", "force_range": "5v", "measure": "current", "current_range": "1ma"},
        },
        "patterns": {
            "drive": {"v0": 0.0, "vectors": [[1e-6, 3.0], [1e-6, 0.0], [1e-6, 3.0], [1e-6, 0.0]]},
            "sense": {"v0": 0.0, "vectors": [[4e-6, 0.0]]},
        },
        "events": [
            {"kind": "measure", "pattern": "drive", "event": "v", "t": 0.0, "points": 400, "interval": 1e-8,
             "average": 0.0},
            {"kind": "measure", "pattern": "sense", "event": "i", "t": 0.0, "points": 400, "interval": 1e-8,
             "average": 1e-8},
        ],
        "sequences": {"201": [["drive", 10]], "202": [["sense", 10]]},
    }
    program.update(copy.deepcopy(changes))
    return program


def wg_limits(**changes: Any) -> WaveformLimits:
    data = {"max_vectors": 2048, "max_points": 4_000_000, "total_time_s": 1.0}
    data.update(changes)
    return WaveformLimits(**data)


def wgfmu(program: Mapping[str, Any] | None | str = "default", *, top_target: Any = "RSU201.OUT",
          limits: Mapping[int, WaveformLimits] | None = None, entry_v: float = 3.0,
          top_pulse: PulseEnvelope | None = None, trains: Iterable[PulseTrain] = (),
          station_profile: StationProfile | None = None, mutate: Callable[[dict[str, Any]], None] | None = None,
          **kw: Any) -> Ctx:
    """``fecap.pund`` on pin map ``fecap-wgfmu`` (top = RSU201.OUT, bottom = RSU202.OUT) with DUT ``fecap-generic``.
    ``program``: the waveform program JSON (``"default"`` = ``wave()``, ``None`` = none); ``mutate`` edits it in
    place; ``top_pulse``/``trains`` make the top channel a pulse channel."""
    data: dict[str, Any] | None = wave() if program == "default" else (dict(program) if program else None)
    if data is not None and mutate is not None:
        mutate(data)
    sources: dict[str, Any] = {}
    if data is not None:
        sources["waveform"] = data
    trains = list(trains)
    if trains:
        sources["pulses"] = {"201": [t.model_dump(mode="json") for t in trains]}
    entries = {
        201: ChannelEnvelope(role="top", max_abs_v=entry_v, max_abs_i=None, function="wgfmu", pulse=top_pulse),
        202: ChannelEnvelope(role="bottom", max_abs_v=entry_v, max_abs_i=None, function="wgfmu"),
    }
    du = DutProfile(name="fecap-generic", device_type="fecap", terminals={"top": FECAP, "bottom": FECAP})
    pm = pin_map_exact("fecap-wgfmu", {"top": top_target, "bottom": "RSU202.OUT"})
    routes = [r for r in (RSU201, RSU202) if top_target == "RSU201.OUT" or r is RSU202]
    kw.setdefault("routes", routes)
    kw.setdefault("routes_by_phase", {"main": routes})
    return context(rec=recipe(WG_REC), pm=pm, du=du, station_profile=station_profile or lab_station(),
                   extra_envelope=entries, waveform=dict(limits) if limits is not None else
                   {201: wg_limits(), 202: wg_limits()}, program={SOURCE_PLAN_KEY: sources}, **kw)


def program_model(**changes: Any) -> WaveformProgram:
    return WaveformProgram.model_validate(wave(**changes))


# -- MFCMU plans -----------------------------------------------------------------------------------------------------

CV_REC: dict[str, Any] = {
    **copy.deepcopy(SPGU_REC),
    "id": "moscap.cv",
    "title": "MOS-C C-V",
    "family": "cmu",
    "kind": "cmu_measure",
    "device_types": ["moscap"],
    "roles": {
        "gate": {"function": "cmu_high", "module_types": ["MFCMU"]},
        "bulk": {"function": "cmu_low", "module_types": ["MFCMU"]},
    },
    "params": {"freq": {"unit": "Hz", "default": 1e6, "range": [1e3, 5e6]},
               "v_start": {"unit": "V", "default": -2.0, "range": [-25, 25]},
               "v_stop": {"unit": "V", "default": 2.0, "range": [-25, 25]}},
}

MOSCAP = DutTerminal(max_abs_v=3.0, max_abs_i=1e-6, impedance="high_z", ac=TerminalAc(max_vrms=0.1))


def corr(kind: str, *, age_h: float = 2.5, freqs: tuple[float, ...] = (1e3, 1e5, 1e6),
         idn: str = "Keysight Technologies,B1500A,SIM1,A.06") -> CorrectionRecord:
    return CorrectionRecord(kind=kind, freqs_hz=[] if kind == "phase" else list(freqs),
                            run_id="S20261117T053012Z-00cd", ts=T0 - timedelta(hours=age_h), idn=idn,
                            pin_map_sha=ZERO_SHA, station_sha=ZERO_SHA,
                            corr_state={"open": True, "short": True, "load": False})


CORRECTED = {"CMU1": [corr("phase"), corr("open"), corr("short")]}
CORR_ON = {"CMU1": CmuCorrectionLive(corr_state={"open": True, "short": True, "load": False}, phase=True)}


def cv(ac: AcEnvelope | None | str = "default", *, gate: DutTerminal = MOSCAP, bulk: DutTerminal = MOSCAP,
       v: tuple[float, float] = (-2.0, 2.0), corrections: Mapping[str, list[CorrectionRecord]] | None = None,
       **kw: Any) -> Ctx:
    """``moscap.cv`` on pin map ``moscap-cmu`` (gate = 7H, bulk = 7L) with DUT ``moscap-generic``: 1 MHz, 30 mVrms,
    DC -2..2 V; correction records 2.5 h old unless ``corrections`` is given."""
    envelope = AcEnvelope(max_vrms=0.03, max_dc_v=2.0, f_min_hz=1e6, f_max_hz=1e6) if ac == "default" else ac
    assert not isinstance(envelope, str)
    dc = envelope.max_dc_v if envelope is not None else max(abs(v[0]), abs(v[1]))
    entry = ChannelEnvelope(role="gate", max_abs_v=max(dc, abs(v[0]), abs(v[1])), max_abs_i=1e-6,
                            function="cmu_high", v_start=v[0], v_stop=v[1], ac=envelope)
    du = DutProfile(name="moscap-generic", device_type="moscap", terminals={"gate": gate, "bulk": bulk})
    pm = pin_map_exact("moscap-cmu", {"gate": "7H", "bulk": "7L"})
    kw.setdefault("rec", recipe(CV_REC))
    return context(pm=pm, du=du, station_profile=lab_station(), extra_envelope={7: entry},
                   corrections=CORRECTED if corrections is None else corrections, **kw)


# -- Misc ------------------------------------------------------------------------------------------------------------


def probe(**changes: Any) -> DllProbe:
    data = {"path": "C:/Windows/System32/wgfmu.dll", "exists": True, "machine": "x64", "python_bits": 64,
            "loadable": True}
    data.update(changes)
    return DllProbe(**data)


IRANGE_REC = recipe(IDVG, roles={**IDVG["roles"], "drain": {**IDVG["roles"]["drain"],
                                                          "settings": {"v": "$vd", "icomp": "$icomp_drain",
                                                                       "irange": "$irange"}}},
                    params={**IDVG["params"], "irange": {"unit": "A", "default": 1e-9, "range": [1e-12, 1.0]}})
"""``mosfet.idvg`` whose drain measures in a fixed current range (setting ``irange``)."""
