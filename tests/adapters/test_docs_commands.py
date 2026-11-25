"""The lab docs (blueprint 9.5, WP4.1/4.2; v2 7.1: ``hardware-bringup.md`` is a one-page overview of the bring-up
stage files since WP6.3) name only ``b1500`` commands and options that exist in the CLI ("every command named exists
in `b1500 --help` output") and keep the structure their acceptance criteria require.

Commands are taken from fenced code blocks and inline code spans: every ``b1500`` token (also after ``uv run``) starts
a command whose following words are walked down the Typer command tree; options must belong to the command reached.
Placeholders (``PLAN_ID``, ``RUN_ID``, ``...``) end the walk. The checks only read the docs and ask the CLI for help
text; nothing is executed. The walk lives in ``devtools/skills/commands.py`` (WP5.10), where ``b1500 dev lint-skills``
applies it to every skill, stage file and doc.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from b1500_test_agent.devtools.skills.commands import help_problem, named_commands, resolve
from b1500_test_agent.models.validation import STAGE_FILES_DIR, STAGES, stage_file_name

REPO_ROOT = Path(__file__).resolve().parents[2]
BRINGUP = REPO_ROOT / "docs" / "hardware-bringup.md"
DEPLOYMENT = REPO_ROOT / "docs" / "deployment-windows.md"
DOCS = (BRINGUP, DEPLOYMENT)


def sections(text: str, level: int) -> dict[str, str]:
    """Body of every heading of exactly ``level`` hashes, keyed by the heading text."""
    pattern = re.compile(rf"^{'#' * level} (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if level > 1:
            parent = re.compile(rf"^#{{1,{level - 1}}} ", re.MULTILINE).search(text, match.end(), end)
            end = parent.start() if parent else end
        result[match.group(1).strip()] = text[match.end():end]
    return result


# -- helpers --------------------------------------------------------------------------------------------------------


def test_extraction_reads_code_only_and_stops_at_placeholders() -> None:
    text = (
        "Prose b1500 status is not code; `mcp__b1500__run_plan` and `b1500-mcp` are not commands.\n"
        "Run `uv run b1500 run --confirm PLAN_ID` or `b1500 dev`.\n"
        "```powershell\n"
        "uv run b1500 plan basic.contact_resistor -p v_start=0 --pin-map x  # comment --bogus\n"
        "```\n"
    )
    assert named_commands(text) == [["run", "--confirm", "PLAN_ID"], ["dev"],
                                    ["plan", "basic.contact_resistor", "-p", "v_start=0", "--pin-map", "x"]]


def test_resolve_rejects_unknown_commands_and_options() -> None:
    assert resolve(["harness", "init", "--codex", "--check"])[3] is None
    assert resolve(["dev"])[3] is None
    assert resolve(["status", "--no-refresh"])[3] is None
    assert "no command `b1500 stauts`" in (resolve(["stauts"])[3] or "")
    assert "no option --yolo" in (resolve(["doctor", "--yolo"])[3] or "")
    assert "no command `b1500 harness setup`" in (resolve(["harness", "setup"])[3] or "")


# -- every doc ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_named_command_exists(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    commands = named_commands(text)
    assert len(commands) >= 10, f"{doc.name}: expected the checklist to name its commands in code"
    problems: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for tokens in commands:
        path, _, options, problem = resolve(tokens)
        if problem is None and (key := (*path, *sorted(set(options)))) not in seen:
            seen.add(key)
            problem = help_problem(path, options)
        if problem is not None:
            problems.append(f"{problem}  (from: b1500 {' '.join(tokens)})")
    assert not problems, f"{doc.name}:\n" + "\n".join(problems)


# -- hardware-bringup.md (WP4.1; one-page overview since WP6.3) ----------------------------------------------------

STAGE_DIR = REPO_ROOT.joinpath(*STAGE_FILES_DIR)
OVERVIEW_MAX_LINES = 80
OVERVIEW_COMMANDS = ("bringup status", "bringup propose-station", "bringup capture", "bringup record",
                     "doctor --probe", "con" + "fig init", "con" + "fig adopt", "lock status", "shutdown",
                     "dev recipe-check")
STAGE_ATVS = {"S0": ("ATV-3",), "L0": ("ATV-2", "ATV-10", "ATV-13"), "L1": ("ATV-1",), "L4": ("ATV-11", "ATV-7")}
"""v1 ATVs of the M4 checklist, now attached (with their fallback) to the stage files, the single source."""


def test_bringup_overview_is_one_page_pointing_to_the_stage_files() -> None:
    text = BRINGUP.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= OVERVIEW_MAX_LINES
    assert "the procedure itself lives in one place, the stage files of skill `b1500-bringup`" in " ".join(text.split())
    rows = [line for line in text.splitlines() if line.startswith("| ") and not line.startswith("| Stage")]
    ids = [row.split("|")[1].strip() for row in rows]
    expected = [s for s in STAGES if s != "L8"]  # L5 and L9: WP7.7; L6: WP8.6; L7: WP9.6
    assert [i for i in ids if i != "L8"] == expected and "L8" in ids
    for stage in expected:
        link = f"../.agents/skills/b1500-bringup/stages/{stage_file_name(stage)}"
        assert f"]({link})" in text, stage
        assert (BRINGUP.parent / link).resolve().is_file(), stage
    assert "](../validation/hw/README.md)" in text and (REPO_ROOT / "validation" / "hw" / "README.md").is_file()


def test_bringup_overview_names_the_commands_and_keeps_its_anchors() -> None:
    text = BRINGUP.read_text(encoding="utf-8")
    named = [" ".join(tokens) for tokens in named_commands(text)]
    for command in OVERVIEW_COMMANDS:
        assert any(n.startswith(command) for n in named), f"`b1500 {command}` not named"
    headings = list(sections(text, 2))
    for heading in ("Stages", "Who does what", "CLI and harness coexist", "If cleanup fails",
                    "Rehearsal on the simulator"):
        assert heading in headings, heading  # deployment-windows.md links to these sections


def test_stage_files_attach_each_atv_with_its_fallback() -> None:
    for stage, atvs in STAGE_ATVS.items():
        body = (STAGE_DIR / stage_file_name(stage)).read_text(encoding="utf-8")
        for atv in atvs:
            assert re.search(rf"{atv}(?!\d)", body), f"{stage}: {atv} missing"
            assert "allback" in body[body.index(atv):], f"{stage}: no fallback after {atv}"


# -- deployment-windows.md (WP4.2) ----------------------------------------------------------------------------------

REQUIRED_FACTS = ("GPIB adapter", "VISA vendor", "Internet", "wheelhouse", "EasyEXPERT", "versions", "Backup")
PROCEDURE_ORDER = (  # blueprint v2 7.5: Python + uv + VISA -> clone -> sync -> config init -> probe -> proposal ->
    # adoption -> harness -> Codex (the bootstrap commands are the human's; WP6.1)
    "uv python install", "VISA stack", "git clone", "uv sync --frozen", "uv run b1500 config init --visa",
    "uv run b1500 doctor --probe", "uv run b1500 bringup propose-station",
    "uv run b1500 config adopt work\\bringup\\station.proposed.yaml --as station", "b1500 harness init --codex",
    "```powershell\ncodex\n```",
)
DEPLOYMENT_ATVS = ("ATV-4", "ATV-7", "ATV-8", "ATV-11")


def deployment_sections() -> dict[str, str]:
    return sections(DEPLOYMENT.read_text(encoding="utf-8"), 2)


def table_rows(body: str) -> list[list[str]]:
    rows = [line.strip().strip("|").split("|") for line in body.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in row] for row in rows if not set("".join(row)) <= set("-: ")]


def test_deployment_facts_each_have_a_default() -> None:
    facts = next(body for heading, body in deployment_sections().items() if heading.startswith("Facts to collect"))
    header, *rows = table_rows(facts)
    column = header.index("Default if unknown")
    assert rows, "no facts listed"
    for row in rows:
        assert len(row) == len(header) and row[column], f"fact without a default: {row[0]}"
    for fact in REQUIRED_FACTS:
        assert any(fact in row[0] for row in rows), f"fact missing: {fact}"


def test_deployment_procedure_is_ordered() -> None:
    procedure = deployment_sections()["Procedure"]
    steps = [int(n) for n in re.findall(r"^### Step (\d+) ", procedure, re.MULTILINE)]
    assert steps == list(range(1, len(steps) + 1)) and len(steps) >= 7
    positions = [procedure.find(marker) for marker in PROCEDURE_ORDER]
    assert all(position >= 0 for position in positions), dict(zip(PROCEDURE_ORDER, positions, strict=True))
    assert positions == sorted(positions), dict(zip(PROCEDURE_ORDER, positions, strict=True))


def test_deployment_checks_sandbox_risks_and_one_hardening_note() -> None:
    text = DEPLOYMENT.read_text(encoding="utf-8")
    headings = list(deployment_sections())
    assert "codex doctor --summary" in text and "workspace-write" in text and "danger-full-access" in text
    assert "--yolo" in text and "approve the project MCP server `b1500` once" in text.replace("**", "")
    assert any(h.startswith("Residual risks") for h in headings)
    hardening = [h for h in headings if h.startswith("Optional future hardening")]
    assert len(hardening) == 1 and "administrator-managed" in deployment_sections()[hardening[0]]
    for atv in DEPLOYMENT_ATVS:
        assert re.search(rf"{atv}(?!\d)", text), f"{atv} missing"
        assert "allback" in text[text.index(atv):], f"no fallback after {atv}"


# -- deployment-windows.md v2 (WP6.5) -------------------------------------------------------------------------------

BRINGUP_PROMPT = "Use skill b1500-bringup and continue the hardware bring-up from the current stage."
FIRST_SESSION = (  # blueprint v2 7.5, in this order
    "git push", "winget install astral-sh.uv", "uv python install 3.12", "IO Libraries", "A.03.00", "System32",
    "setx PYTHONUTF8 1", "git clone", "C:\\b1500\\test_agent", "B1500_MANUALS_DIR", "uv sync --frozen",
    "uv run b1500 manual status", "uv run b1500 doctor", "Exit EasyEXPERT", "GPIB address 17",
    "uv run b1500 con" + "fig init --visa", "uv run b1500 doctor --probe", "uv run b1500 bringup propose-station",
    "uv run b1500 con" + "fig adopt work\\bringup\\station.proposed.yaml --as station", "uv run b1500 config check",
    "uv run b1500 harness init --codex", BRINGUP_PROMPT, "$env:B1500_HW = \"1\"; uv run pytest -m hardware",
    "data\\runs\\", "validation\\hw\\",
    "tests\\fixtures\\hw\\", "OD-7", "lab/bringup-<date>", "OneDrive", "hw_validated",
)
WHEELHOUSE = (  # the procedure checked on the Mac, in order
    "uv export --frozen --no-hashes --no-emit-project",
    ("uv pip compile requirements.txt --no-deps --python-platform x86_64-pc-windows-msvc --python-version 3.12"),
    "--platform win_amd64 --python-version 3.12",
    '"setuptools>=69" wheel', "--target wheelhouse-check", "never commit wheels", "Checked on the Mac",
    "setx UV_OFFLINE 1", "--no-index --find-links ..\\wheelhouse -r ..\\requirements-win.txt", "--no-deps -e .",
    "uv sync --frozen",
)


def _ordered(body: str, markers: tuple[str, ...]) -> dict[str, int]:
    """Position of each marker, each searched after the previous one (-1 = missing or out of order)."""
    positions, start = {}, 0
    for marker in markers:
        found = body.find(marker, start)
        positions[marker] = found
        if found >= 0:
            start = found + len(marker)
    return positions


def test_deployment_first_session_is_the_blueprint_script() -> None:
    raw = deployment_sections()["First session"]
    items = re.findall(r"^(\d+)\. ", raw, re.MULTILINE)
    assert [int(n) for n in items] == list(range(1, 12))  # blueprint v2 7.5 lines 1-11
    positions = _ordered(" ".join(raw.split()), FIRST_SESSION)  # markers may wrap across lines
    assert all(p >= 0 for p in positions.values()), {m: p for m, p in positions.items() if p < 0}
    procedure = deployment_sections()["Procedure"]
    assert "### Step 10 — Bring the instrument up with the agent" in procedure
    assert "### Step 11 — End of the measurement day" in procedure


def test_deployment_hardware_suite_sets_b1500_hw() -> None:
    """Without ``B1500_HW=1`` every hardware test only skips (WP6.4): each mention runs it with the variable."""
    text = DEPLOYMENT.read_text(encoding="utf-8")
    runs = [m.start() for m in re.finditer(r"pytest -m hardware", text)]
    assert runs and all("B1500_HW" in text[max(0, at - 40):at] for at in runs)


def test_deployment_offline_wheelhouse_is_the_checked_procedure() -> None:
    body = " ".join(deployment_sections()["Offline wheelhouse"].replace("\\\n", " ").split())
    positions = _ordered(body, WHEELHOUSE)
    assert all(p >= 0 for p in positions.values()), {m: p for m, p in positions.items() if p < 0}
    for size_fact in ("98 wheels", "81 MB", "12.6 MB", "96 packages"):
        assert size_fact in body, size_fact  # within the 50 MB per file / 500 MB total download budget


def test_deployment_keeps_what_the_stage_files_point_to() -> None:
    """Stage files point here: S0 "up to `uv sync --frozen`", L4 records results, L10 the harness wiring."""
    text = DEPLOYMENT.read_text(encoding="utf-8")
    assert "uv sync --frozen" in text and "## Recorded results" in text and "### Step 7 — Wire the harness" in text
