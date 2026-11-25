"""Recipe validation of ``wgfmu.fast_bti`` (kind ``stress_measure``, WGFMU path) on the simulator (WP10.7; blueprint v2
10.6 row 10.7, per-recipe AC: tier, run, default analysis vs the 4.2 ``mosfet`` + ``bti`` target). These tests set
``status: sim_validated`` of ``wgfmu.fast_bti``.

- Fast-BTI dVth vs the model with recovery suppressed (the WP AC): every read's shift equals the model's power law
  A V^gamma t^n (no recovery term) within 3 %, the fit recovers n +-0.02 and A +-10 % (4.2); on a device whose shift
  recovers within 100 us, the microsecond reads still see >= 95 % of it while millisecond reads (the same recipe with
  1 ms steps) lose more than 15 %. (The simulator's SMU sweeps are quasi-static: only timed holds and WGFMU
  executions age a device, so the SMU recipe shows no read-induced recovery there.)
- Spot reads (one level, ~1 us) give the shift through the reference read's curve; recovery reads follow the
  log-recovery law; the schedule runs in WGFMU executions of at most 25 s.
- SMU + WGFMU in one run (WG Ex. 10/11): an SMU body bias held through the WGFMU phase and read between executions;
  the FLEX and library calls interleave in the run's audit. The RSU's SMU path (ATV-32 on the simulator): a DC Id-Vg
  on pin map ``mosfet-4t`` reaches the same transistor (same Vth as the fast reference read; after the stress it sees
  the shift).
- Long runs are asynchronous and cancel at a checkpoint (after the reference read, or while the sequencer holds the
  stress) with verified cleanup on both buses and the rows of the completed executions; a saturated reference read
  stops the run before any stress.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from b1500_test_agent.analysis import load_run
from b1500_test_agent.catalog.kinds.stress_wgfmu import WgfmuStressProgram
from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.session import Transaction
from b1500_test_agent.session.abort import AbortFile
from tests.integration.async_helpers import assert_async_invariant, partial_rows, progress_of, run_events
from tests.integration.helpers import REPO_ROOT, World
from tests.integration.test_async_cancel import abort_at
from tests.integration.test_recipes_sampling import run_request

pytestmark = pytest.mark.wgfmu

FAST = {"recipe_id": "wgfmu.fast_bti", "pin_map": "mosfet-wgfmu", "dut_profile": "nmos-wgfmu"}
BODY = {**FAST, "pin_map": "mosfet-wgfmu-body"}
SMU_BTI = {"recipe_id": "reliability.bti_sms", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
EXAMPLE = {"vg_stress": 2.0, "stress_time": 100.0}
I_CRIT = 1e-6
COLUMNS = ["step", "t_s", "cycle", "phase", "gate_V", "drain_V", "drain_I", "drain_I_status", "trust"]


def by_quantity(results: list[ExtractionResult]) -> dict[str, ExtractionResult]:
    return {r.quantity: r for r in results}


def device(world: World, name: str = "dut") -> Any:
    from b1500_test_agent.config import load_config
    from b1500_test_agent.transport.sim.devices import Circuit

    return Circuit(load_config(world.paths).sim_scenario).devices[name]  # type: ignore[arg-type]


def read_vth(rows: pd.DataFrame, i_crit: float = I_CRIT) -> float:
    """Constant-current Vth of one read: log10 Id through the four sense levels around the crossing as a cubic (a
    coarse 50 mV staircase: linear interpolation would bias the shift by a few percent), solved on the bracket."""
    rows = rows.sort_values("gate_V")
    x = rows["gate_V"].to_numpy(dtype=float)
    y = np.log10(np.abs(rows["drain_I"].to_numpy(dtype=float)))
    target = math.log10(i_crit)
    k = int(np.searchsorted(y, target))
    lo = max(0, min(k - 2, len(x) - 4))
    roots = np.roots(np.polyfit(x[lo:lo + 4], y[lo:lo + 4], 3) - np.array([0.0, 0.0, 0.0, target]))
    inside = [r.real for r in roots if abs(r.imag) < 1e-12 and x[k - 1] - 1e-12 <= r.real <= x[k] + 1e-12]
    return float(inside[0])


def shifts(table: pd.DataFrame) -> list[tuple[float, float]]:
    """``(t_s, dVth)`` of every stress read against the reference read."""
    reads = table[table["phase"] == "read"]
    vth0 = read_vth(reads[reads["cycle"] == 0])
    holds = table[table["phase"] != "read"].groupby("cycle")["phase"].first()
    out = []
    for cycle, rows in reads.groupby("cycle"):
        if cycle == 0 or holds.get(cycle) != "stress":
            continue
        out.append((float(rows["t_s"].iloc[0]), read_vth(rows) - vth0))
    return out


def scenario_variant(world: World, name: str, **params: Any) -> str:
    """A copy of ``nmos_bti`` named ``name`` with the transistor's parameters changed; selected."""
    scenario = yaml.safe_load((REPO_ROOT / "config/sim/scenarios/nmos_bti.yaml").read_text(encoding="utf-8"))
    scenario["models"]["dut"]["params"].update(params)
    world.write_config(f"sim/scenarios/{name}.yaml", scenario)
    world.use_scenario(name)
    return name


def library_calls(world: World, run_id: str) -> list[str]:
    """The ``WgfmuApi`` methods the run called, in order (``wgfmu_call`` audit events)."""
    return [str((e.data or {}).get("fn")) for e in run_events(world, run_id) if e.ev == "wgfmu_call"]


# -- the WP AC: dVth vs the model with recovery suppressed -----------------------------------------------------------


def test_fast_bti_reads_the_model_shift_without_recovery(world: World) -> None:
    """The card example (2 V, 100 s, 3 reads per decade from 1 ms): every read's dVth = A V^gamma t^n of the model
    within 3 % (the model's recovery term never enters: the gate leaves the stress for 19 us per read), and the fit
    recovers n +-0.02, A +-10 % (4.2)."""
    world.use_scenario("nmos_bti")
    service = world.service()
    validation, result = run_request(service, FAST, **EXAMPLE)
    assert validation.tier == "needs_confirmation"
    assert sorted(validation.confirm_reasons) == ["destructive", "unverified_topology"]
    summary = validation.summary or ""
    assert "gate=WGFMU1:201 via RSU201.OUT fast_bti 0..2 V stress 2 V" in summary
    assert "stress 100 s x16 reads" in summary and validation.resolved is not None
    assert validation.resolved.mode == "sync" and result.outcome == "completed", result.message
    assert result.cleanup_verified == "sim_state" and result.quality_verdict == "ok"
    data = load_run(result.run_id or "", data_root=world.data)
    assert list(data.table.columns) == COLUMNS
    assert result.status_counts == {"N": len(data.table)} == {"N": 17 * 17 + 16}
    facts = data.manifest.kind_result
    assert (facts["path"], facts["reads_done"], facts["holds_done"], facts["stopped_early"]) == ("wgfmu", 17, 16,
                                                                                                 False)
    assert facts["read_s"] == pytest.approx(17 * 1.1e-6 + 1e-7) and facts["runs_done"] == facts["runs_planned"] >= 3
    dut = device(world)
    found = shifts(data.table)
    assert len(found) == 16 and found[0][0] == pytest.approx(1e-3) and found[-1][0] == pytest.approx(100.0)
    for t, dvth in found:
        truth = dut.bti_truth(2.0, t)
        assert dvth == pytest.approx(truth, rel=0.03, abs=3e-4), (t, dvth, truth)
    defaults = by_quantity(result.analyses)
    assert defaults["n"].value == pytest.approx(dut.params.bti_n, abs=0.02)
    assert defaults["a"].value == pytest.approx(dut.bti_truth(2.0, 1.0), rel=0.10)
    assert defaults["dvth"].value == pytest.approx(dut.bti_truth(2.0, 100.0), rel=0.03)
    assert defaults["n"].fit["read_fraction"] < 0.02 and defaults["n"].warnings == []
    power = service.analyze_run(result.run_id or "", "bti_power_law", {"i_crit_a": I_CRIT})  # same table contract
    assert power.ok and by_quantity(power.results)["n"].value == pytest.approx(dut.params.bti_n, abs=0.02)
    service.close()


def test_recovery_is_suppressed_where_slower_reads_lose_the_shift(world: World) -> None:
    """A device whose shift recovers within 100 us (log recovery 0.15 per decade from 1e-4 s): the 19 us reads keep
    >= 95 % of the model's shift; the same schedule with 1 ms steps (17 ms per read, the speed of a fast SMU sweep)
    loses more than 15 % and fast_bti_shift warns about it. Separate scenario copies: each run starts fresh."""
    fast_recovery = {"bti_recovery": 0.15, "bti_recovery_t0_s": 1e-4}
    scenario_variant(world, "nmos_bti_fastrec_a", **fast_recovery)
    service = world.service()
    _, fast = run_request(service, FAST, **EXAMPLE)
    dut = device(world)
    truth = dut.bti_truth(2.0, 100.0)
    fast_dvth = by_quantity(fast.analyses)["dvth"].value
    assert fast_dvth is not None and 0.95 * truth <= fast_dvth <= 1.01 * truth
    scenario_variant(world, "nmos_bti_fastrec_b", **fast_recovery)
    _, slow = run_request(service, FAST, **EXAMPLE, width=1e-3, settle=5e-4)
    found = by_quantity(slow.analyses)
    slow_dvth = found["dvth"].value
    assert slow_dvth is not None and slow_dvth < 0.85 * truth < 0.95 * truth <= fast_dvth
    assert found["dvth"].fit["read_s"] == pytest.approx(17 * 1.0001e-3 + 1e-7)
    assert any("early reads may include recovery" in w for w in found["dvth"].warnings)
    service.close()


def test_spot_reads_give_the_shift_through_the_reference_curve(world: World) -> None:
    """read_kind spot: one sense level (vg_read 0.5 V, 1.2 us off the stress); fast_bti_shift picks the reference
    read's curve: dVth within 3 % of the model, n +-0.02."""
    world.use_scenario("nmos_bti")
    service = world.service()
    _, result = run_request(service, FAST, **EXAMPLE, read_kind="spot")
    data = load_run(result.run_id or "", data_root=world.data)
    reads = data.table[data.table["phase"] == "read"]
    assert len(reads[reads["cycle"] == 0]) == 17 and set(reads[reads["cycle"] > 0]["gate_V"]) == {0.5}
    assert data.manifest.kind_result["read_s"] == pytest.approx(1.2e-6)
    found = by_quantity(result.analyses)
    assert found["n"].method_record.params["vth_method"] == "reference_curve"
    dut = device(world)
    assert found["dvth"].value == pytest.approx(dut.bti_truth(2.0, 100.0), rel=0.03)
    assert found["n"].value == pytest.approx(dut.params.bti_n, abs=0.02)
    service.close()


def test_recovery_reads_follow_the_log_recovery_law(world: World) -> None:
    """recovery_time 10 s at 0 V: the recovered fraction at the last recovery read = 0.1 log10(1 + 10 s / 1 s) of the
    model, +-0.01."""
    world.use_scenario("nmos_bti")
    service = world.service()
    _, result = run_request(service, FAST, **EXAMPLE, recovery_time=10.0)
    data = load_run(result.run_id or "", data_root=world.data)
    assert set(data.table["phase"]) == {"read", "stress", "recovery"}
    found = by_quantity(result.analyses)
    dut = device(world)
    expected = 1.0 - dut.bti_recovery_truth(1.0, 10.0)
    assert found["recovery"].value == pytest.approx(expected, abs=0.01)
    assert found["recovery_rate"].outcome == "ok"
    service.close()


def test_the_schedule_runs_in_executions_of_at_most_25_s(world: World) -> None:
    world.use_scenario("nmos_bti")
    service = world.service()
    validation = service.validate_plan(**FAST, params=EXAMPLE)
    plan = world.executor().load_plan(validation.plan_id or "")
    program = WgfmuStressProgram.model_validate({k: v for k, v in plan.program.items() if k != "sources"})
    assert program.runs[0] == (0, 1)  # the reference read alone: a saturated reference stops before any stress
    assert [stop for _, stop in program.runs[:-1]] == [start for start, _ in program.runs[1:]]
    assert program.runs[-1][1] == len(program.ops) + 1  # the last execution ends with the tail
    holds = {i: op.seconds for i, op in enumerate(program.ops) if op.kind == "hold"}
    for start, stop in program.runs[1:]:
        end = min(stop, len(program.ops))  # the tail entry is no operation
        assert program.ops[end - 1].kind == "read"
        total = sum(holds.get(i, 0.0) for i in range(start, end))
        assert total <= 25.0 or end - start == 2  # one hold longer than 25 s runs alone with its read
    assert plan.estimate.max_segment_s is not None and plan.estimate.max_segment_s <= 30.0
    service.close()


# -- SMU + WGFMU in one run (WG Ex. 10/11) and the RSU SMU path (ATV-32) ---------------------------------------------


def test_an_smu_body_bias_is_held_and_read_between_executions(world: World) -> None:
    """WG Ex. 10/11: the bulk SMU5 is switched on and biased inside the WGFMU phase (after initialize), held through
    every execution and read once between two (monitor facts in kind_result, each reading in the audit); the FLEX and
    library calls interleave in the run's audit; a negative body bias raises the reference Vth."""
    world.use_scenario("nmos_bti")
    service = world.service()
    validation, result = run_request(service, BODY, **EXAMPLE, vb=-0.5)
    assert "bulk=SMU5(MPSMU) bias -0.5 V Icomp 100 uA" in (validation.summary or "")
    assert result.outcome == "completed" and result.cleanup_verified == "sim_state", result.message
    run_id = result.run_id or ""
    data = load_run(run_id, data_root=world.data)
    assert "bulk_V" in data.table.columns and "bulk_I" not in data.table.columns  # monitor values: kind_result
    facts = data.manifest.kind_result
    assert facts["bulk_I_reads"] == facts["runs_done"] - 1 >= 2 and facts["bulk_I_status"] == "N"
    assert isinstance(facts["bulk_I_max_abs"], float) and facts["bulk_I_max_abs"] < 1e-4
    assert (data.table["bulk_V"] == -0.5).all()
    events = run_events(world, run_id)
    order = [(e.ev, str((e.data or {}).get("fn")) if e.ev == "wgfmu_call" else str(e.cmd)) for e in events
             if e.ev == "wgfmu_call" or (e.ev in ("write", "query") and e.cmd)]
    names = [name for _, name in order]
    first_cn = names.index("CN 5")
    assert names.index("open_session") < names.index("initialize") < first_cn < names.index("execute")
    assert names.index("DV 5,0,-0.5,0.0001") < names.index("execute")
    executes = [i for i, n in enumerate(names) if n == "execute"]
    xes = [i for i, n in enumerate(names) if n == "XE"]
    assert len(xes) == len(executes) - 1 and all(executes[k] < xes[k] < executes[k + 1] for k in range(len(xes)))
    assert data.manifest.assumptions is not None and any("flex_io" in a for a in data.manifest.assumptions)
    reads = data.table[data.table["phase"] == "read"]
    biased_vth0 = read_vth(reads[reads["cycle"] == 0])
    world.use_scenario("nmos_bti")
    service.close()
    other = scenario_variant(world, "nmos_bti_fresh")
    assert other
    service = world.service()
    _, flat = run_request(service, FAST, **EXAMPLE)
    flat_data = load_run(flat.run_id or "", data_root=world.data)
    flat_reads = flat_data.table[flat_data.table["phase"] == "read"]
    assert biased_vth0 > read_vth(flat_reads[flat_reads["cycle"] == 0]) + 0.02
    service.close()


def test_the_rsu_smu_path_reaches_the_same_transistor(world: World) -> None:
    """ATV-32 on the simulator: a DC Id-Vg through the RSUs' SMU inputs (pin map mosfet-4t: SMU4 gate, SMU3 drain)
    reads the fast reference read's Vth (same 1 uA criterion) within 5 mV; after the fast stress the DC read sees the
    shift (a slow read: up to 15 % recovered)."""
    world.use_scenario("nmos_bti")
    service = world.service()
    dc = {"recipe_id": "mosfet.idvg", "pin_map": "mosfet-4t", "dut_profile": "nmos-generic"}
    sweep = {"vd": 0.1, "vg_start": 0.2, "vg_stop": 1.0, "vg_points": 17}
    _, before = run_request(service, dc, **sweep)
    _, fast = run_request(service, FAST, **EXAMPLE)
    _, after = run_request(service, dc, **sweep)
    dc0 = read_vth(load_run(before.run_id or "", data_root=world.data).table)
    dc1 = read_vth(load_run(after.run_id or "", data_root=world.data).table)
    table = load_run(fast.run_id or "", data_root=world.data).table
    reads = table[table["phase"] == "read"]
    assert read_vth(reads[reads["cycle"] == 0]) == pytest.approx(dc0, abs=5e-3)
    fast_dvth = by_quantity(fast.analyses)["dvth"].value
    assert fast_dvth is not None and 0.85 * fast_dvth <= dc1 - dc0 <= 1.001 * fast_dvth
    service.close()


# -- long runs, cancel, stops ----------------------------------------------------------------------------------------


def test_a_long_fast_bti_is_asynchronous_and_cancels_after_the_reference_read(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """30 min: destructive + long_run + unverified_topology, async; an abort seen at checkpoint 1 (the reference read's
    execution) cancels there: outputs zero and the WGFMU safe state verified, the 17 reference rows kept as PARTIAL,
    no stress execution started."""
    world.use_scenario("nmos_bti")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**FAST, params={"vg_stress": 2.0, "stress_time": 1800.0})
    assert sorted(validation.confirm_reasons) == ["destructive", "long_run", "unverified_topology"]
    assert validation.resolved is not None and validation.resolved.mode == "async"
    abort_at(monkeypatch, world, 1)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert started.outcome == "running"
    final = service.follow_run(started.run_id or "")
    assert final is not None and (final.outcome, final.error_code) == ("cancelled", "run_cancelled")
    assert final.cleanup_verified == "sim_state"
    run_id = final.run_id or ""
    assert partial_rows(world, run_id) == 17
    assert library_calls(world, run_id).count("execute") == 1
    manifest = assert_async_invariant(world, run_id, scenario="nmos_bti")
    assert manifest.outcome == "cancelled" and manifest.plan.mode == "async"
    service.close()


def test_a_cancel_while_the_sequencer_holds_the_stress_aborts_it(world: World,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """An abort requested at the first progress checkpoint inside an execution (no rows: the sequencer still holds
    the stress) cancels within that status poll: WGFMU aborted, initialized, disconnected, session closed, FLEX
    relocked, outputs zero; the rows of the executions completed before stay as PARTIAL."""
    world.use_scenario("nmos_bti")
    service = world.service(adapter="mcp")
    validation = service.validate_plan(**FAST, params={"vg_stress": 2.0, "stress_time": 1800.0})
    original = Transaction.checkpoint
    seen: list[int] = []

    def checkpoint(self: Transaction, done: int, total: int, phase: str = "", rows: Any = None) -> None:
        if rows is None and phase == "stress" and not seen:
            seen.append(done)
            AbortFile(world.state_dir).request("test abort inside an execution", adapter="cli")
        original(self, done, total, phase, rows)

    monkeypatch.setattr(Transaction, "checkpoint", checkpoint)
    started = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    final = service.follow_run(started.run_id or "")
    assert final is not None and final.outcome == "cancelled" and final.cleanup_verified == "sim_state"
    run_id = final.run_id or ""
    calls = library_calls(world, run_id)
    last_execute = len(calls) - 1 - calls[::-1].index("execute")
    assert "abort" in calls[last_execute:] and "close_session" in calls[last_execute:]
    progress = progress_of(world, run_id)
    assert seen and seen[0] > 1 and progress is not None and progress.done == seen[0]
    assert progress.state == "cancelled"
    assert partial_rows(world, run_id) == 17  # the reference read's execution completed, the stress one was aborted
    assert_async_invariant(world, run_id, scenario="nmos_bti")
    service.close()


def test_a_saturated_reference_read_stops_the_run_before_any_stress(world: World) -> None:
    """irange 1ua: the reference read saturates above 1 uA (status V): the run stops after its first execution, no
    stress execution starts, kind_result says why."""
    world.use_scenario("nmos_bti")
    service = world.service()
    validation = service.validate_plan(**FAST, params={**EXAMPLE, "irange": "1ua"})
    result = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert result.outcome == "completed_with_flags" and result.cleanup_verified == "sim_state", result.message
    assert result.quality_verdict == "untrusted"
    data = load_run(result.run_id or "", data_root=world.data)
    facts = data.manifest.kind_result
    assert facts["stopped_early"] is True and facts["holds_done"] == 0 and facts["stress_s_done"] == 0.0
    assert "status V" in facts["stop_reason"] and facts["runs_done"] == 1
    assert library_calls(world, result.run_id or "").count("execute") == 1
    assert set(data.table["phase"]) == {"read"} and "V" in set(data.table["drain_I_status"])
    service.close()


def test_the_wgfmu_waveform_kind_runs_the_fast_bti_builder_in_one_execution(world: World, tmp_path: Any) -> None:
    """Builder ``fast_bti`` of kind wgfmu_waveform (a raw view: one execution, events ``sense``/``monitor``); a
    test-only recipe, since the committed one runs in stress_measure."""
    recipes = tmp_path / "recipes"
    import shutil

    shutil.copytree(REPO_ROOT / "recipes", recipes)
    data = yaml.safe_load((recipes / "wgfmu" / "fast_bti.yaml").read_text(encoding="utf-8"))
    data.update(id="wgfmu.fast_bti_raw", kind="wgfmu_waveform", family="wgfmu", card=None, analysis_defaults=[],
                status="draft")
    data["params"]["builder"] = {"type": "enum", "choices": ["fast_bti"], "default": "fast_bti", "doc": "builder"}
    del data["roles"]["bulk"]
    (recipes / "wgfmu" / "fast_bti_raw.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    world.recipes = recipes
    world.use_scenario("nmos_bti")
    service = world.service()
    validation = service.validate_plan(**{**FAST, "recipe_id": "wgfmu.fast_bti_raw"},
                                       params={"vg_stress": 2.0, "stress_time": 1.0})
    assert validation.ok, validation.message
    result = service.run_confirmed_plan(validation.plan_id or "", validation.summary or "")
    assert result.outcome == "completed" and result.cleanup_verified == "sim_state", result.message
    table = load_run(result.run_id or "", data_root=world.data).table
    assert set(table["event"]) == {"sense", "monitor"}
    assert (table["event"] == "monitor").sum() == 10 and (table["event"] == "sense").sum() == 11 * 17
    assert library_calls(world, result.run_id or "").count("execute") == 1
    service.close()
