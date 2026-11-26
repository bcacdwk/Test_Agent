"""The bring-up rehearsal of S0-L2 on the visa-loop (v2.1 plan §4.4; WP21.7): the walker of
``tests/integration/rehearsal.py`` on backend visa, so every step is verified as on the lab PC.

The deployment, the session start, S0, L0, L1 and L2 in the order ``b1500 bringup next`` names them: real
``VisaTransport`` runs (``H...``, cleanup verified with ``LOP?`` behind the positive control), the probes of the
visa-loop, the station proposal adopted by the scripted human (``config.adopt``, the function behind the human-only
CLI command), the pin map and DUT proposals and adoptions, draft records (``bringup record``) and fixtures
(``bringup capture``) checked by ``bringup done``, the human's review of each finished stage into ``validation/hw/``,
the drills (the abort file at a checkpoint, as ``b1500 shutdown`` in a second window writes it). Then ``bringup check``
of each stage has no gap, ``bringup status`` says ``signed`` for S0-L2, and everything was written inside the test's
temporary folders: the repository's ``work/``, ``validation/``, ``tests/fixtures/hw/``, ``config/local/`` and ``data/``
are untouched. Marker ``rehearsal``.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent import bringup, bringup_steps, config
from b1500_test_agent.bringup_ledger import ledger_path, load_stage, read_ledger
from b1500_test_agent.models.station import SimScenario
from b1500_test_agent.models.validation import STAGE_FILES_DIR, STEPS_FILE, RecordDraft, StepDone, StepSpec
from b1500_test_agent.service import B1500Service
from tests.integration.rehearsal import ADOPTED, OWNER, STEPS, Rehearsal, Variant, scenario_data
from tests.visa_loop.helpers import REPO_ROOT, VisaWorld
from tests.visa_loop.loop import LoopBus

pytestmark = pytest.mark.rehearsal

GUARDED = ("work", "validation", "tests/fixtures/hw", "config/local", "data")
"""Repository folders the walk must never write (it writes only the test's temporary world)."""


class VisaRehearsal(Rehearsal):
    """The walk on backend visa: a landing is a new ``LoopBus`` of that scenario (and a service over it); the
    configuration is adopted, records drafted and reviewed, fixtures captured."""

    backend = "visa"

    def __init__(self, world: VisaWorld) -> None:
        super().__init__(world.root, world.state_dir)
        self.world = world
        self._service: B1500Service | None = None
        self.drafts: dict[tuple[str, str | None], RecordDraft] = {}
        self.reviewed: list[str] = []
        self.land("lab_station")

    @property
    def service(self) -> B1500Service:
        assert self._service is not None
        return self._service

    def write_config(self, rel: str, data: Any) -> None:
        self.world.write_local(rel, data)

    def land(self, scenario: str, variant: Variant | None = None) -> None:
        name, data = scenario_data(scenario, variant)
        if name != self.landed:
            # one bus folder per landing: the loop instrument keeps its state per scenario
            bus = LoopBus(self.world.bus_dir / name, SimScenario.model_validate({**data, "name": name}))
            self._service = self.world.service(bus)
            self.landed = name

    # -- the visa kinds ----------------------------------------------------------------------------------------------

    def do_config(self, spec: StepSpec) -> StepDone:
        """The human adopts: the station proposal (L0.P2), the stage's pin maps and DUT profiles (its proposals where
        the agent wrote some, else the committed examples); the local settings and station need no file."""
        drafts: list[str] = []
        if spec.id == "L0.P2":
            drafts.append(self.adopt(self.root / "work" / "bringup" / "station.proposed.yaml", "station"))
        for item in ADOPTED.get(spec.id, ()):
            folder, name = item.split("/")
            proposal = self.root / "work" / "bringup" / f"{name}.yaml"
            source = proposal if proposal.is_file() else self.root / "config" / folder / f"{name}.example.yaml"
            drafts.append(self.adopt(source, "pinmap" if folder == "pinmaps" else "dut"))
        return self.done(spec.id, drafts=tuple(drafts))

    def adopt(self, source: Path, kind: str) -> str:
        report = config.adopt(source, kind, self.world.paths)  # type: ignore[arg-type]
        assert report.ok, report.problems
        return source.relative_to(self.root).as_posix()

    def do_record(self, spec: StepSpec) -> StepDone:
        drafts = self.draft_records(spec.group)
        return self.done(spec.id, drafts=tuple(d.path for d in drafts if d.path))

    def do_capture(self, spec: StepSpec) -> StepDone:
        sources = self.capture_sources(spec)
        report = bringup.capture(self.service, sources)
        assert report.ok and report.folder is not None and report.written, report.message
        tags = sorted({Path(w.path).relative_to(report.folder).parts[0] for w in report.written})
        runs = tuple(s for s in sources if s != "probe")
        return self.done(spec.id, runs=runs, probe=None if runs else "latest",
                         fixtures=tuple(f"{report.folder}/{tag}" for tag in tags))

    def do_review(self, spec: StepSpec) -> StepDone:
        """The agent drafts what the stage still lacks; the human reviews every draft of the stage, fills reviewer
        and date and moves it to ``validation/hw/``."""
        self.draft_records(spec.group)
        for (stage, _key), draft in self.drafts.items():
            if stage != spec.group or draft.record is None or draft.path is None:
                continue
            reviewed = draft.record.model_copy(update={"reviewer": "A. Reviewer", "reviewed_on": date(2026, 12, 2),
                                                       "result": "pass"})
            target = self.root / "validation" / "hw" / reviewed.file_name()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(yaml.safe_dump(reviewed.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
            (self.root / draft.path).unlink()
            self.reviewed.append(target.relative_to(self.root).as_posix())
        return self.done(spec.id)

    def draft_records(self, stage: str) -> list[RecordDraft]:
        """``bringup record`` for every record the stage needs and has no draft yet: one per recipe with checks
        (its first completed run of the stage), the stage record (L0: from the newest probe)."""
        front = load_stage(self.root, stage)[1]
        assert front is not None
        made = []
        for key in front.record_keys():
            if (stage, key) in self.drafts:
                continue
            if key is None:
                draft = bringup.record(self.service, stage, probe="latest" if stage == "L0" else None,
                                       operator=OWNER)
            else:
                draft = bringup.record(self.service, stage, self.stage_runs(stage, key)[:1], recipe_id=key,
                                       operator=OWNER)
            assert draft.ok and draft.path is not None and draft.record is not None, draft.message
            assert draft.record.result != "fail", (draft.path, draft.record.measurements)
            self.drafts[(stage, key)] = draft
            made.append(draft)
        return made


def snapshot(root: Path) -> dict[str, int]:
    """``path -> mtime_ns`` of every file under the guarded repository folders."""
    found: dict[str, int] = {}
    for rel in GUARDED:
        folder = root / rel
        if folder.is_dir():
            found.update({p.relative_to(root).as_posix(): p.stat().st_mtime_ns for p in folder.rglob("*")
                          if p.is_file()})
    return found


@pytest.fixture
def lab(world: VisaWorld) -> VisaWorld:
    """The visa world with the committed stage files and ``steps.yaml``."""
    shutil.copytree(REPO_ROOT.joinpath(*STAGE_FILES_DIR), world.root.joinpath(*STAGE_FILES_DIR))
    shutil.copy2(REPO_ROOT.joinpath(*STEPS_FILE), world.root.joinpath(*STEPS_FILE))
    return world


def test_s0_to_l2_on_the_visa_loop_signs_every_stage_inside_the_temporary_world(lab: VisaWorld,
                                                                                tmp_path: Path) -> None:
    before = snapshot(REPO_ROOT)
    rehearsal = VisaRehearsal(lab)
    walked = rehearsal.walk(until="L3.A1")
    stages = ("S0", "L0", "L1", "L2")
    expected = [s.id for s in STEPS.deployment] + [s.id for s in STEPS.session_start]
    for stage in stages:  # the review step of a finished stage comes before the next stage's first step
        expected += [s.id for s in STEPS.stages[stage] if not s.is_review] + [f"{stage}.R"]
    assert walked == expected and len(walked) == 12 + 4 + 15 + 12 + 13 + 17

    service = rehearsal.service
    path = ledger_path(service.config.get())
    assert path.name == "ledger-visa.jsonl" and path.is_relative_to(tmp_path)
    entries = read_ledger(path).entries
    assert [e.step for e in entries] == walked and {e.verdict for e in entries} == {"pass"}
    assert {e.backend for e in entries} == {"visa"}
    runs = [r.ref for e in entries for r in e.evidence.runs]
    assert runs and all(r.startswith("H") for r in runs)
    assert rehearsal.facts[rehearsal.runs["L1.A6"][0]][1] == "cancelled"
    fixtures = [f.ref for e in entries for f in e.evidence.fixtures]
    assert len(fixtures) == 1 + 1 + 2 and all(f.startswith("work/bringup/fixtures/") for f in fixtures)
    adopted = [d.ref for e in entries if e.verify == "config" for d in e.evidence.drafts]
    assert adopted[0] == "work/bringup/station.proposed.yaml" and "work/bringup/open-smus.yaml" in adopted
    for stage in stages:
        checked = bringup_steps.check(service, stage)
        assert checked.ok and checked.scope == stage, [g.reason for g in checked.gaps]
    moved = [n.split(":")[0] for n in bringup_steps.check(service).notes if "moved to validation/hw/" in n]
    assert moved == ["S0.A5"] + ["L2.A11"] * 4  # the drafts of the record steps, reviewed and moved by the human
    status = bringup.bringup_status(service)
    states = {s.stage: s.state for s in status.stages}
    assert [states[s] for s in stages] == ["signed"] * 4 and states["L3"] != "signed"
    assert status.next_stage == "L3"
    reviewed = sorted(rehearsal.reviewed)
    fronts = [(stage, load_stage(lab.root, stage)[1]) for stage in stages]
    keys = [(stage, key) for stage, front in fronts if front is not None for key in front.record_keys()]
    assert reviewed == sorted(f"validation/hw/{key or 'stage-' + stage.lower()}.yaml" for stage, key in keys)
    assert reviewed == ["validation/hw/basic.contact_resistor.yaml", "validation/hw/generic.smu_multi_sweep.yaml",
                        "validation/hw/generic.smu_spot.yaml", "validation/hw/resistor.kelvin_4w.yaml",
                        "validation/hw/stage-l0.yaml", "validation/hw/stage-l1.yaml", "validation/hw/stage-s0.yaml",
                        "validation/hw/system.self_cal.yaml", "validation/hw/system.self_test.yaml"]
    assert all((lab.root / r).is_file() for r in reviewed)
    assert snapshot(REPO_ROOT) == before
