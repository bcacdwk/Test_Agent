"""Step verifiers and the step ledger on backend visa (v2.1 plan §4.1; WP21.5).

The runs are real ``VisaTransport`` runs over the visa-loop (run ids ``H…``, backend visa, cleanups verified with
``LOP?`` behind the positive control), so the verifiers read what they read on the lab PC: ``run`` (pass; a simulator
run ``S…`` copied into the hardware archive, a changed run file, an unverified cleanup and a failed positive control
fail), ``probe`` (a visa-loop probe passes, a simulator probe fails), ``config`` (the adopted local files equal to the
file adopted; a differing or missing one fails; a missing ``--draft`` is refused), ``record`` (drafts of
``bringup record``; another stage's or a failing one fails), ``capture`` (fixtures of ``bringup capture``; a stray file
fails), ``review`` and ``station``; ``check`` notes drafts and fixtures that moved after review; ``bringup record``
embeds the ledger's steps (schema version 2) and names the steps a stage record still lacks; ``bringup status`` signs a
stage from its reviewed records and the ledger or the records' embedded steps, never from schema-1 records alone.
Everything stays in the test's temporary world.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent import bringup, bringup_steps
from b1500_test_agent.bringup_ledger import append_entry, ledger_path, load_steps, make_entry
from b1500_test_agent.bringup_verify import VERIFIERS, Ctx, Refused, StepArgs, reverify
from b1500_test_agent.models.validation import (
    STAGE_FILES_DIR,
    STEPS_FILE,
    EvidenceItem,
    LedgerEntry,
    StepSpec,
    ValidationRecord,
)
from b1500_test_agent.service import B1500Admin, B1500Service
from tests.integration.helpers import make_world
from tests.visa_loop.helpers import MEASUREMENT_CASES, REPO_ROOT, VisaWorld, run_case

CONTACT = next(c for c in MEASUREMENT_CASES if c["recipe_id"] == "basic.contact_resistor")
STEPS = load_steps(REPO_ROOT)


@pytest.fixture
def lab(world: VisaWorld) -> VisaWorld:
    """The visa world with the committed stage files and ``steps.yaml``."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    shutil.copy2(REPO_ROOT.joinpath(*STEPS_FILE), world.root.joinpath(*STEPS_FILE))
    return world


def spec(**fields: Any) -> StepSpec:
    values: dict[str, Any] = {"id": "L2.A3", "who": "agent", "verify": "run", "rehearsal": "run_sim",
                              "recipes": ["basic.contact_resistor"]}
    values.update(fields)
    return StepSpec.model_validate(values)


def verify(service: B1500Service, step: StepSpec, args: StepArgs) -> tuple[str, str]:
    ctx = Ctx(service, service.config.get(), STEPS, step, step.verify, args)
    return VERIFIERS[step.verify](ctx)


def hardware_run(service: B1500Service) -> str:
    result = run_case(service, CONTACT)
    assert result.ok and result.run_id is not None and result.run_id.startswith("H"), result.message
    return result.run_id


def resistance(world: VisaWorld, run_id: str) -> float:
    payload = json.loads(next((world.run_dir(run_id) / "analysis").glob("resistance-*.json")).read_text("utf-8"))
    return next(r["value"] for r in payload["results"] if r["quantity"] == "resistance")


def seed(service: B1500Service, step_ids: list[str], **fields: Any) -> list[LedgerEntry]:
    """Ledger entries ``pass`` for ``step_ids`` on this station's backend (test set-up of a recorded history)."""
    bundle = service.config.get()
    out = []
    for step_id in step_ids:
        step = STEPS.get(step_id)
        assert step is not None
        out.append(append_entry(ledger_path(bundle), lambda seq, prev, s=step: make_entry(
            seq, prev, step=s.id, ts=datetime.now(UTC), backend=bundle.backend, actor="agent", verify=s.verify,
            verdict="pass", reason="seeded", **fields)))
    return out


def review_into(world: VisaWorld, draft: ValidationRecord, *, steps: bool = True) -> Path:
    """The human's review: reviewer, date, result pass, moved to ``validation/hw/`` (optionally as schema 1)."""
    data = draft.model_copy(update={"reviewer": "A. Reviewer", "reviewed_on": date(2026, 12, 2),
                                    "result": "pass"}).model_dump(mode="json")
    if not steps:
        data.pop("steps")
        data.pop("schema_version")
    target = world.root / "validation" / "hw" / draft.file_name()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


# -- run, probe, station ----------------------------------------------------------------------------------------------


def test_run_verifier_on_hardware_runs(lab: VisaWorld, tmp_path: Path) -> None:
    service = lab.service(lab.bus(CONTACT["scenario"]))
    run_id = hardware_run(service)
    verdict, reason = verify(service, spec(), StepArgs(runs=(run_id,)))
    assert verdict == "pass" and f"{run_id} basic.contact_resistor" in reason
    sim = make_world(tmp_path / "sim")
    sim_service = sim.service()
    plan = sim_service.validate_plan(recipe_id="basic.contact_resistor", params={"v_start": 0, "v_stop": 0},
                                     pin_map="resistor-2t", dut_profile="resistor-generic")
    assert plan.plan_id is not None
    sim_run = sim_service.run_plan(plan.plan_id).run_id
    assert sim_run is not None and sim_run.startswith("S")
    folder = next(p for p in sim.runs_dir.rglob(sim_run) if p.is_dir())
    shutil.copytree(folder, lab.data / "runs" / folder.relative_to(sim.runs_dir))
    sim_service.close()
    verdict, reason = verify(service, spec(), StepArgs(runs=(sim_run,)))
    assert verdict == "fail" and f"run {sim_run} ran on backend sim: the visa ledger takes hardware runs (H...) " \
                                 "only" in reason
    manifest_path = lab.run_dir(run_id) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["cleanup"]["verified"] == "lop" and manifest["cleanup"]["positive_control"]["ok"]
    manifest["cleanup"]["positive_control"]["ok"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    verdict, reason = verify(service, spec(), StepArgs(runs=(run_id,)))
    assert verdict == "fail" and "the LOP? positive control failed" in reason
    manifest["cleanup"]["verified"] = "unverified"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    verdict, reason = verify(service, spec(), StepArgs(runs=(run_id,)))
    assert verdict == "fail" and "cleanup verified 'unverified'" in reason and "needs 'lop'" in reason
    (lab.run_dir(run_id) / "data.csv").write_text("step\n0\n", encoding="utf-8")
    verdict, reason = verify(service, spec(), StepArgs(runs=(run_id,)))
    assert "files changed since the run (data.csv)" in reason


def test_probe_and_station_verifiers_on_hardware(lab: VisaWorld, tmp_path: Path) -> None:
    service = lab.service(lab.bus("lab_station"))
    report = B1500Admin(service).probe()
    assert report.ok and not report.simulated, report.message
    probe = spec(id="L0.A2", verify="probe", recipes=[])
    verdict, reason = verify(service, probe, StepArgs(probe="latest"))
    assert verdict == "pass" and "no FAIL" in reason
    sim = make_world(tmp_path / "sim")
    sim_service = sim.service()
    assert B1500Admin(sim_service).probe().ok
    sim_probe = next((sim.root / "work" / "bringup").glob("probe-*.json"))
    target = lab.root / "work" / "bringup" / "probe-29991231T235959Z.json"
    shutil.copy2(sim_probe, target)
    sim_service.close()
    verdict, reason = verify(service, probe, StepArgs(probe="latest"))
    assert verdict == "fail" and "is a probe on backend sim, not visa" in reason
    station = spec(id="L1.A1", verify="station", recipes=[])
    verdict, reason = verify(service, station, StepArgs())
    assert verdict == "pass" and reason == "station_status clean"


# -- config, record, capture, review ----------------------------------------------------------------------------------


def test_config_verifier_compares_the_adopted_files(lab: VisaWorld, tmp_path: Path) -> None:
    service = lab.service(lab.bus(CONTACT["scenario"]))
    adopt = spec(id="L1.P2", who="human", verify="config", recipes=[], config=["pinmap", "dut"])
    pin_map = "config/pinmaps/open-smus.example.yaml"
    dut = "config/duts/open-circuit.example.yaml"
    verdict, reason = verify(service, adopt, StepArgs(drafts=(pin_map, dut)))
    assert verdict == "pass" and "pinmaps/open-smus" in reason and "duts/open-circuit" in reason
    with pytest.raises(Refused, match="name the adopted dut file"):
        verify(service, adopt, StepArgs(drafts=(pin_map,)))
    proposal = lab.root / "work" / "bringup" / "open-smus.yaml"
    proposal.parent.mkdir(parents=True, exist_ok=True)
    proposal.write_text((lab.root / pin_map).read_text(encoding="utf-8") + "# reviewed\n", encoding="utf-8")
    verdict, reason = verify(service, adopt, StepArgs(drafts=(str(proposal), dut)))
    assert verdict == "fail"
    assert "config/local/pinmaps/open-smus.yaml differs from work/bringup/open-smus.yaml" in reason
    data = yaml.safe_load((lab.root / pin_map).read_text(encoding="utf-8"))
    data["name"] = "never-adopted"
    proposal.write_text(yaml.safe_dump(data), encoding="utf-8")
    verdict, reason = verify(service, adopt, StepArgs(drafts=(str(proposal), dut)))
    assert verdict == "fail" and "pinmaps/never-adopted is not in the configuration (not adopted)" in reason
    settings = spec(id="L0.P1", who="human", verify="config", recipes=[], config=["settings"])
    verdict, reason = verify(service, settings, StepArgs())
    assert verdict == "pass" and "settings" in reason


def test_record_capture_and_review_verifiers(lab: VisaWorld) -> None:
    service = lab.service(lab.bus(CONTACT["scenario"]))
    run_id = hardware_run(service)
    measured = resistance(lab, run_id)
    draft = bringup.record(service, "L2", [run_id], references=[f"r_dmm={measured}"], operator="owner")
    assert draft.ok and draft.path is not None and draft.record is not None, draft.message
    records = spec(id="L2.A9", verify="record", recipes=[])
    verdict, reason = verify(service, records, StepArgs(drafts=(draft.path,)))
    assert verdict == "pass" and "1 draft record(s)" in reason
    other_stage = spec(id="L3.A6", verify="record", recipes=[])
    verdict, reason = verify(service, other_stage, StepArgs(drafts=(draft.path,)))
    assert verdict == "fail" and "stage L3 records basic.diode_iv, basic.iv_force_i" in reason
    failing = bringup.record(service, "L2", [run_id], references=[f"r_dmm={measured * 1.05}"])
    assert failing.path is not None
    verdict, reason = verify(service, records, StepArgs(drafts=(failing.path,)))
    assert verdict == "fail" and "result fail" in reason
    with pytest.raises(Refused, match="a draft record lies under"):
        verify(service, records, StepArgs(drafts=("config/station.example.yaml",)))
    captured = bringup.capture(service, [run_id])
    assert captured.ok and captured.folder is not None, captured.message
    fixtures = f"{captured.folder}/{run_id}"
    capture = spec(id="L1.A8", verify="capture")
    verdict, reason = verify(service, capture, StepArgs(runs=(run_id,), fixtures=fixtures))
    assert verdict == "pass" and "fixture file(s)" in reason
    with pytest.raises(Refused, match="give the capture"):
        verify(service, capture, StepArgs(fixtures=fixtures))
    (lab.root / fixtures / "note.txt").write_text("hand-written\n", encoding="utf-8")
    verdict, reason = verify(service, capture, StepArgs(runs=(run_id,), fixtures=fixtures))
    assert verdict == "fail" and "not written by `uv run b1500 bringup capture`: note.txt" in reason
    review = spec(id="L2.R", who="human", verify="review", recipes=[])
    verdict, reason = verify(service, review, StepArgs())
    assert verdict == "fail" and "validation/hw/basic.contact_resistor.yaml missing" in reason


def test_check_notes_drafts_and_fixtures_moved_after_review(lab: VisaWorld) -> None:
    service = lab.service(lab.bus(CONTACT["scenario"]))
    run_id = hardware_run(service)
    draft = bringup.record(service, "L2", [run_id], references=[f"r_dmm={resistance(lab, run_id)}"])
    captured = bringup.capture(service, [run_id])
    assert draft.path is not None and draft.record is not None and captured.folder is not None
    bundle = service.config.get()
    records = STEPS.get("L2.A9")
    capture = STEPS.get("L1.A8")
    assert records is not None and capture is not None
    for step, args in ((records, StepArgs(drafts=(draft.path,))),
                       (capture.model_copy(update={"recipes": ["basic.contact_resistor"]}),
                        StepArgs(runs=(run_id,), fixtures=f"{captured.folder}/{run_id}"))):
        ctx = Ctx(service, bundle, STEPS, step, step.verify, args)
        assert VERIFIERS[step.verify](ctx)[0] == "pass"
        entry = make_entry(1, "0" * 64, step=step.id, ts=datetime.now(UTC), backend="visa", actor="agent",
                           verify=step.verify, verdict="pass", reason="test",
                           evidence={k: v for k, v in ctx.ev.items() if k in ("runs", "drafts", "fixtures", "facts")})
        assert reverify(Ctx(service, bundle, STEPS, step, step.verify, StepArgs()), entry) == ([], [])
        if step.verify == "record":
            review_into(lab, draft.record)
            (lab.root / draft.path).unlink()
            problems, notes = reverify(Ctx(service, bundle, STEPS, step, step.verify, StepArgs()), entry)
            assert problems == [] and notes == [f"{draft.path} moved to validation/hw/ after review"]
        else:
            source = lab.root / captured.folder / run_id
            shutil.move(source, lab.root / "tests" / "fixtures" / "hw" / run_id)
            problems, notes = reverify(Ctx(service, bundle, STEPS, step, step.verify, StepArgs()), entry)
            assert problems == [] and notes == [f"{captured.folder}/{run_id} moved to tests/fixtures/hw/ after review"]


# -- records embed the steps; status signs from records and steps ----------------------------------------------------


def test_records_embed_the_stage_steps_and_name_the_missing_ones(lab: VisaWorld) -> None:
    service = lab.service(lab.bus(CONTACT["scenario"]))
    run_id = hardware_run(service)
    seed(service, ["L2.A1", "L2.A2"])
    seed(service, ["L2.A3"], evidence={"runs": [EvidenceItem(ref=run_id)]})
    draft = bringup.record(service, "L2", [run_id], references=[f"r_dmm={resistance(lab, run_id)}"])
    assert draft.ok and draft.record is not None and draft.path is not None
    record = draft.record
    assert record.schema_version == 2 and [s.step for s in record.steps] == ["L2.A1", "L2.A2", "L2.A3"]
    assert record.steps[2].evidence.startswith(f"runs {run_id}") and record.steps[2].verify == "run"
    text = (lab.root / draft.path).read_text(encoding="utf-8")
    assert ValidationRecord.model_validate(yaml.safe_load(text)) == record
    stage = bringup.record(service, "S0", operator="owner")
    assert stage.ok and stage.record is not None and stage.record.steps == []
    assert any("steps of S0 not passed yet: S0.A1, S0.A2" in note for note in stage.notes)
    assert not any("S0.A5" in note or "S0.A6" in note for note in stage.notes)  # with or after the draft


def test_status_signs_a_stage_only_with_its_steps(lab: VisaWorld) -> None:
    service = lab.service(lab.bus(CONTACT["scenario"]))
    s0 = [s.id for s in STEPS.stages["S0"]]
    draft = bringup.record(service, "S0", operator="owner")
    assert draft.record is not None
    review_into(lab, draft.record, steps=False)  # a v2 (schema 1) record: loads and counts as a record
    status = bringup.bringup_status(service)
    first = next(s for s in status.stages if s.stage == "S0")
    assert first.records[0].state == "reviewed" and first.state == "review"
    assert (first.steps_done, first.steps_total) == (3, 15)  # A5 record, A6 after the record, R review
    seed(service, [s for s in s0 if s not in ("S0.A5", "S0.A6", "S0.R")])
    signed = next(s for s in bringup.bringup_status(service).stages if s.stage == "S0")
    assert signed.state == "signed" and (signed.steps_done, signed.steps_total) == (15, 15)
    ledger_path(service.config.get()).unlink()  # the developer's machine: no hardware ledger, steps in the record
    assert next(s for s in bringup.bringup_status(service).stages if s.stage == "S0").state == "review"
    seed(service, [s for s in s0 if s not in ("S0.A5", "S0.A6", "S0.R")])
    with_steps = bringup.record(service, "S0", operator="owner")
    assert with_steps.record is not None and len(with_steps.record.steps) == 12 and not with_steps.notes
    review_into(lab, with_steps.record)
    ledger_path(service.config.get()).unlink()
    travelled = bringup.bringup_status(service)
    s0_state = next(s for s in travelled.stages if s.stage == "S0")
    assert s0_state.state == "signed" and travelled.next_stage == "L0"


def test_done_on_the_hardware_ledger_through_the_service(lab: VisaWorld) -> None:
    service = lab.service(lab.bus(CONTACT["scenario"]))
    human = {"human": "installed yesterday", "by": "Owner"}
    first = bringup_steps.done(service, "D2", StepArgs(**human), actor="human_via_agent")
    assert first.ok and first.entry is not None and first.entry.backend == "visa" and not first.simulated
    assert first.entry.actor == "human_via_agent" and first.ledger is not None
    assert first.ledger.endswith("data/state/bringup/ledger-visa.jsonl")
    assert first.next is not None and first.next.id == "D1"
    refused = bringup_steps.done(service, "D10", StepArgs(**human))
    assert refused.status == "refused" and "needs --observe update=<VALUE> qualify_windows=<VALUE>" in refused.message
    progress = bringup_steps.next_step(service)
    assert progress.progress["D"] == "1/12" and progress.progress["S0"] == "0/15" and progress.notes == []
