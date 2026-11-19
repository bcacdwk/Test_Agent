"""Bring-up records on the lab PC, stage by stage (blueprint v2 7.1, 7.2, 7.4; WP6.4).

One test per stage (``hw_s0`` ... ``hw_l10``) checks every record of that stage: the reviewed records in
``validation/hw/`` and the drafts in ``work/bringup/records/``. ``records.py`` lists the checks: the WP6.3 schema,
hardware runs (``H...``) that exist in ``data/runs`` on backend visa with intact files, recipe digests that match the
current recipes, verified cleanups and passing ``LOP?`` positive controls behind every passing record, and a reviewer
on every committed record. A stage without records yet is skipped. The checks only read files; they never touch
the instrument.

Run at the end of a bring-up day on the lab PC, before the records are reviewed and transferred (7.5 step 10):
``$env:B1500_HW = "1"; uv run pytest -m hardware -rs``.
"""

from __future__ import annotations

import pytest

from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.models.recipe import Recipe
from tests.hardware.records import (
    RecordFile,
    RecordInvalid,
    RecordSchema,
    RunArchive,
    check_file,
    read_record,
    record_files,
    stage_of,
    stray_files,
)
from tests.hardware.support import STAGE_IDS, stage_marker

pytestmark = pytest.mark.hardware

STAGES = [pytest.param(stage, id=stage, marks=getattr(pytest.mark, stage_marker(stage))) for stage in STAGE_IDS]


@pytest.fixture(scope="session")
def files(hw_config: ConfigBundle) -> list[RecordFile]:
    return record_files(hw_config.paths.repo_root, hw_config.paths.work_dir)


@pytest.mark.parametrize("stage", STAGES)
def test_stage_records(stage: str, files: list[RecordFile], record_schema: RecordSchema | None,
                       run_archive: RunArchive, recipes: dict[str, Recipe], hw_config: ConfigBundle) -> None:
    mine = [f for f in files if stage_of(f.path) == stage]
    if not mine:
        pytest.skip(f"no record of stage {stage} yet (validation/hw/, work/bringup/records/)")
    problems: list[str] = []
    for file in mine:
        problems += check_file(file, record_schema, archive=run_archive, recipes=recipes,
                               repo_root=hw_config.paths.repo_root)
    assert not problems, f"{len(problems)} problem(s) in the stage {stage} records:\n" + "\n".join(problems)


@pytest.mark.hw_l10
def test_every_record_file_belongs_to_a_stage(files: list[RecordFile], hw_config: ConfigBundle) -> None:
    """Stage L10 (records reviewed and transferred): no record file escapes the per-stage checks."""
    stray = stray_files(hw_config.paths.repo_root)
    if not files and not stray:
        pytest.skip("no record files yet")
    problems = [f"{shown}: not a *.yaml record (validation/hw/ holds README.md and records only)" for shown in stray]
    for file in files:
        try:
            stage = read_record(file.path).get("stage")
        except RecordInvalid as exc:
            problems.append(f"{file.shown}: {exc}")
            continue
        if stage not in STAGE_IDS:
            problems.append(f"{file.shown}: stage {stage!r} is not one of {', '.join(STAGE_IDS)}")
    assert not problems, "\n".join(problems)
