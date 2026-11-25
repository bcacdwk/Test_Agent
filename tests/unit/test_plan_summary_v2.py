"""``plan_summary`` v2 (blueprint v2 2.9): routes, pulses with SER and the ``Isc<=X A residual`` of a high_z
terminal, MFCMU with correction age, WGFMU programs, current forcing, ``async ~N min``; exact forms, compaction,
ASCII and at most 400 characters, determinism (only hashed plan content and config-derived findings)."""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope, PlanRecord, RuleFinding
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import PulseTrain
from b1500_test_agent.rules.tiers import SUMMARY_MAX_CHARS, _channels, _hertz, _ohms, _seconds, plan_summary, with_rules
from tests.unit import rules_factory_v2 as v2
from tests.unit.rules_factory import FORCE, context, engine, live_state, pin_map, recipe, wide_dut

Ctx = tuple[Any, Any]


def summarize(cfg_ctx: Ctx) -> tuple[str, list[RuleFinding]]:
    cfg, ctx = cfg_ctx
    report = engine(cfg).evaluate(ctx, "plan")
    return plan_summary(ctx.plan, report.findings), report.findings


def train(**changes: Any) -> PulseTrain:
    return v2.TRAIN.model_copy(update=changes)


# -- Exact v2 forms --------------------------------------------------------------------------------------------------


@pytest.mark.spgu
def test_spgu_pulse_through_a_selector_is_the_blueprint_example() -> None:
    text, _ = summarize(v2.spgu())
    assert text == ("spgu.pulse_train@1 | gate=SPGU1:101 via SEL1.OUT1 pulse 0->4 V 1 us x1000 @10 kHz SER 1 MOhm "
                    "Isc<=0.08 A residual | DUT fefet-lab | pins fefet-sel | sim")


@pytest.mark.spgu
def test_resistive_terminal_shows_its_bound_without_residual() -> None:
    text, _ = summarize(v2.spgu(gate=v2.terminal(impedance="resistive", min_series_ohm=1000.0)))
    assert "SER 1 MOhm Isc<=0.00381 A |" in text and "residual" not in text


@pytest.mark.spgu
def test_pulse_grid_shows_spans_and_total_pulses() -> None:
    trains = [train(peak_v=p, width_s=w, period_s=1e-4, count=10) for p in (2.0, 3.0, 4.0) for w in (1e-8, 1e-6)]
    text, _ = summarize(v2.spgu(trains))
    assert ("gate=SPGU1:101 via SEL1.OUT1 pulse 0->2..4 V 10 ns..1 us x60 @10 kHz SER 1 MOhm Isc<=0.08 A residual"
            in text)


@pytest.mark.spgu
def test_duration_trains_and_mixed_periods() -> None:
    trains = [train(count=None, duration_s=1e-3), train(period_s=2e-4, count=5)]
    text, _ = summarize(v2.spgu(trains))
    assert "pulse 0->4 V 1 us x15 SER 1 MOhm" in text  # 10 + 5 pulses; two periods -> no frequency


def test_smu_pulse_keeps_module_and_compliance() -> None:
    text, _ = summarize(v2.smu_pulse())
    assert text == ("mosfet.idvg_pulsed@1 | gate=SMU5(MPSMU) pulse 0->2 V 1 ms x10 @100 Hz Icomp 1 mA | DUT nmos-pulse "
                    "| pins gate-5 | sim")


def test_mfcmu_sides_frequency_ac_dc_and_correction_age() -> None:
    text, _ = summarize(v2.cv())
    assert text == ("moscap.cv@1 | bulk=CMU1:L low; gate=CMU1:H 1 MHz 30 mVrms DC -2..2 V corr 2h | "
                    "DUT moscap-generic | pins moscap-cmu | sim")


def test_fresh_corrections_read_below_one_hour() -> None:
    fresh = {"CMU1": [v2.corr(k, age_h=0.25) for k in ("phase", "open", "short")]}
    assert "corr <1h" in summarize(v2.cv(corrections=fresh))[0]


def test_wgfmu_channels_name_builder_levels_points_and_interval() -> None:
    text, _ = summarize(v2.wgfmu())
    assert text == ("fecap.pund@1 | bottom=WGFMU1:202 via RSU202.OUT pund 0 V 4000 pts @10 ns; top=WGFMU1:201 via "
                    "RSU201.OUT pund 0..3 V 4000 pts @10 ns | DUT fecap-generic | pins fecap-wgfmu | sim")


def test_wgfmu_dc_sample_like_the_blueprint() -> None:
    program = v2.wave(builder="dc_sample",
                      patterns={"hold": {"v0": 0.5, "vectors": [[0.0504, 0.5]]},
                                "sense": {"v0": 0.0, "vectors": [[0.0504, 0.0]]}},
                      events=[{"kind": "measure", "pattern": "hold", "event": "i", "t": 0.0, "points": 504000,
                               "interval": 1e-7, "average": 0.0},
                              {"kind": "measure", "pattern": "sense", "event": "i2", "t": 0.0, "points": 504000,
                               "interval": 1e-7, "average": 0.0}],
                      sequences={"201": [["hold", 1]], "202": [["sense", 1]]})
    cfg, ctx = v2.wgfmu(program)
    report = engine(cfg).evaluate(ctx, "plan")
    assert report.tier == "ok", [f.message for f in report.findings if f.severity == "block"]
    assert "top=WGFMU1:201 via RSU201.OUT dc_sample 0.5 V 504000 pts @100 ns" in plan_summary(ctx.plan,
                                                                                             report.findings)


def test_current_forcing_names_current_and_voltage_compliance() -> None:
    roles = {"force": {"function": "bias_i", "measure": ["V"], "settings": {"i": "$icomp", "vcomp": "$v"}},
             "source": {"function": "ground", "allow_gndu": True}}
    entry = ChannelEnvelope(role="force", max_abs_v=5.0, max_abs_i=1e-3, function="bias_i")
    text, _ = summarize(context(rec=recipe(FORCE, roles=roles), pm=pin_map(name="force-1", force=5), du=wide_dut(),
                                extra_envelope={5: entry}))
    assert "force=SMU5(MPSMU) bias I<=1 mA Vcomp 5 V |" in text


def test_async_plans_show_the_estimate() -> None:
    text, _ = summarize(context(duration_s=2520.0, mode="async", max_segment_s=10.0))
    assert "| sim | async ~42 min | R-RUN-02 long_run" in text
    text, _ = summarize(context(duration_s=4 * 3600.0, mode="async", max_segment_s=10.0))
    assert "async ~4.0 h" in text


@pytest.mark.spgu
def test_routes_no_role_uses_are_listed() -> None:
    sel = [Route(switch="SEL1", output="OUT1", state=s) for s in ("smu", "pgu", "pgu_open")]
    _, ctx = context(rec=recipe(FORCE, roles={}, params={}), du=None, dut_profile=None, routes=sel,
                     station_profile=v2.lab_station(), routes_by_phase={f"p{i}": [r] for i, r in enumerate(sel)})
    assert plan_summary(ctx.plan, []).split(" | ")[1:3] == ["no outputs", "routes SEL1.OUT1->pgu,pgu_open,smu"]


def test_v2_flags_follow_the_rule_table() -> None:
    text, _ = summarize(v2.spgu([train(count=20000)], pm_certainty="unverified",
                                station_profile=v2.lab_station(sel1={"certainty": "unverified"})))
    assert text.endswith("| sim | R-PIN-02 unverified_pin_map, R-PULSE-03 soft_pulse, R-ROUTE-02 unverified_topology")


@pytest.mark.parametrize(
    ("value", "fmt", "text"),
    [(1e-6, _seconds, "1 us"), (5e-7, _seconds, "500 ns"), (2.0, _seconds, "2 s"), (1e-8, _seconds, "10 ns"),
     (1e4, _hertz, "10 kHz"), (1e6, _hertz, "1 MHz"), (100.0, _hertz, "100 Hz"), (1e6, _ohms, "1 MOhm"),
     (50.0, _ohms, "50 Ohm"), (1500.0, _ohms, "1.5 kOhm")],
)
def test_unit_formatting(value: float, fmt: Any, text: str) -> None:
    assert fmt(value) == text


# -- Canonical, bounded, ASCII ---------------------------------------------------------------------------------------


def test_compact_forms() -> None:
    _, ctx = v2.spgu()
    _, findings = summarize(v2.spgu())
    assert _channels(ctx.plan, compact=True, findings=findings) == ("gate=SPGU1:101@SEL1.OUT1 0->4V 1us x1000 "
                                                                    "Isc<=0.08A res")
    _, ctx = v2.cv()
    _, findings = summarize(v2.cv())
    assert _channels(ctx.plan, compact=True, findings=findings) == ("bulk=CMU1:L low; gate=CMU1:H 1MHz 30mV "
                                                                    "DC-2..2V corr2h")
    _, ctx = v2.wgfmu()
    assert _channels(ctx.plan, compact=True) == ("bottom=WGFMU1:202@RSU202.OUT pund 0V 4000pts; "
                                                 "top=WGFMU1:201@RSU201.OUT pund 0..3V 4000pts")


def _crowded() -> Ctx:
    trains = [train(peak_v=p, width_s=w, period_s=1e-4 + i * 1e-8, count=10, load_ohm=1e3 + i)
              for i, (p, w) in enumerate((p, w) for p in (1.0, 2.0, 3.0) for w in (1e-7, 1e-6))]
    return v2.spgu(trains, pm_certainty="unverified", backend="visa",
                   station_profile=v2.lab_station(sel1={"certainty": "unverified", "present": None}))


@pytest.mark.parametrize("build", [v2.spgu, v2.smu_pulse, v2.wgfmu, v2.cv, _crowded], ids=lambda b: b.__name__)
def test_ascii_bounded_and_storable(build: Any) -> None:
    cfg, ctx = build()
    report = engine(cfg).evaluate(ctx, "plan")
    text = plan_summary(ctx.plan, report.findings)
    assert len(text) <= SUMMARY_MAX_CHARS and text.isascii() and text.isprintable()
    assert with_rules(ctx.plan, report).summary == text
    for entry in ctx.plan.envelope.channels.values():
        assert f"{entry.role}=" in text


def test_overlong_v2_content_is_compacted_then_cut() -> None:
    _, ctx = v2.spgu()
    roles = {f"{'p' * 70}{c}": c for c in (101, 102, 201, 202, 301, 401)}
    entries = {c: ChannelEnvelope(role=r, max_abs_v=4.5, max_abs_i=None, function="pgu",
                                  pulse=ctx.plan.envelope.channels[101].pulse) for r, c in roles.items()}
    plan = PlanRecord.model_validate({**ctx.plan.model_dump(), "envelope": CompiledEnvelope(channels=entries)})
    text = plan_summary(plan, [])
    assert len(text) == SUMMARY_MAX_CHARS and text.endswith("...") and text.isascii()


def test_live_state_and_labels_never_change_the_summary() -> None:
    base = summarize(v2.spgu())[0]
    assert summarize(v2.spgu(live=live_state(errors=[(305, "x")]), label="other die"))[0] == base


def test_the_summary_changes_with_the_pulses_the_terminal_or_the_corrections() -> None:
    base = summarize(v2.spgu())[0]
    assert summarize(v2.spgu([train(count=999)]))[0] != base
    assert summarize(v2.spgu(gate=v2.terminal(impedance="unknown")))[0] != base  # no longer a residual
    assert summarize(v2.cv())[0] != summarize(v2.cv(corrections={
        "CMU1": [v2.corr(k, age_h=5.5) for k in ("phase", "open", "short")]}))[0]
