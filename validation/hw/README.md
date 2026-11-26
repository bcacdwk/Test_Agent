# Hardware validation records (`validation/hw/`)

Reviewed records of the hardware bring-up (blueprint v2 7.1, 7.2, 7.4; skill `b1500-bringup`). This folder holds
human-reviewed records only. It is empty until the owner's hardware session: no record may exist without real
hardware runs, and none is ever written by a coding agent.

| File | Content |
|---|---|
| `<recipe_id>.yaml` | recipe record: the promotion evidence of one recipe (e.g. `mosfet.idvg.yaml`) |
| `stage-<stage>.yaml` | stage record: S0 checklist, L0 probe, L1 zero check, L10 handoff (e.g. `stage-l0.yaml`) |

Schema: `ValidationRecord` in `src/b1500_test_agent/models/validation.py`; annotated template:
`.agents/skills/b1500-bringup/records/_TEMPLATE.yaml`. Drafts are `schema_version: 2` (v2.1): they carry `steps`,
the step ledger's entries of the stage when the draft was made (step, how it was verified, verdict, time, who, the
evidence in one line, the entry's sha256). The ledger itself (`data/state/bringup/ledger-visa.jsonl`, written only by
`uv run b1500 bringup done`) stays on the lab PC; the step list travels with the record. Records without the key
(v2) are version 1 and still load.

## Review flow

1. On the lab PC the agent works a stage step by step (`uv run b1500 bringup next`, then `uv run b1500 bringup done
   STEP ...`, which verifies each step's evidence and records it in the step ledger), runs the stage's plans (each
   confirmed by the human) and drafts the record with
   `uv run b1500 bringup record STAGE --run H... --operator NAME` into `work/bringup/records/`. The command refuses
   simulator runs (`S...`), a station on backend sim, runs whose files or recipe changed since the run, and runs of
   another backend. Measured values are copied from the run archive; references the human gave are added with
   `--reference CHECK=VALUE`; the ledger's steps of the stage are copied into `steps`; `reviewer` stays empty. Draft
   the stage record last: a stage record lists every step of the stage except the ones that come with or after the
   draft (record and review steps, `after_record` in `steps.yaml`), and the draft names any step still missing.
2. The human reviewer opens the draft next to the raw runs (`data/runs/.../<run_id>/`: `manifest.json`,
   `audit.jsonl`, `raw/`, `data.csv`, `analysis/`) and checks every value, reference, tolerance and run id, and the
   step list against `uv run b1500 bringup check STAGE` (exit 0: every step of the stage passed and still
   verifies). Items the stage leaves to observation (S0 checklist, L1 drill) are filled in from the reviewer's own
   observations.
3. The reviewer sets `result` (`pass` or `fail`), fills `reviewer` and `reviewed_on` and moves the file to the
   name its header gives: `validation/hw/<recipe_id>.yaml` or `validation/hw/stage-<stage>.yaml`. A failing
   record is not moved; the stage is repeated.
4. `uv run b1500 bringup done <stage>.R --human "..." --by NAME` records the review step. `uv run b1500 bringup
   status` shows the stage `signed` only when every record of the stage is reviewed and every step passed (in the
   ledger of the lab PC, or in the step lists of the stage's reviewed records on another machine); a simulator
   rehearsal ends `rehearsed`, never `signed`. Fixtures from `uv run b1500 bringup capture` go to
   `tests/fixtures/hw/` after the same review.
5. Transfer (owner decision OD-7): commit `validation/hw/` and `tests/fixtures/hw/` on the lab PC to a branch
   `lab/bringup-<date>` and push it, or copy the folders to the shared OneDrive folder.
6. Promotion is a later developer change on the Mac: `status: hw_validated` in the recipe file (and the run ids in
   `provenance.validation_runs`).

## Promotion rule (`uv run b1500 dev recipe-check`)

- A recipe with `status: hw_validated` needs `validation/hw/<recipe_id>.yaml` that validates, is reviewed
  (`reviewer` and `reviewed_on` set), has `result: pass`, lists hardware runs (`H...`) and whose `recipe_sha256`
  equals the definition digest of the current recipe file. The digest covers what the recipe measures (roles,
  parameters, quality, analyses, kind, version) and leaves out `status`, `provenance` and `card`, so the promotion
  itself does not invalidate the record while any change to the measurement does.
- Every file here must be such a reviewed record (or this README); a draft, a failing record, an unknown recipe
  or a misnamed file is a problem.
- The hardware suite (`tests/hardware/test_records.py`) also needs every passing stage record of schema version 2 to
  list every step of its stage as passed (`tests/hardware/records.py` check 7).
- A reviewed record whose recipe is not promoted yet is reported as a note (promotion pending).
