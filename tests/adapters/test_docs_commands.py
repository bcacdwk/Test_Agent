"""The M4 checklist docs (blueprint 9.5, WP4.1/4.2) name only ``b1500`` commands and options that exist in the CLI
("every command named exists in `b1500 --help` output") and keep the structure their acceptance criteria require.

Commands are taken from fenced code blocks and inline code spans: every ``b1500`` token (also after ``uv run``) starts
a command whose following words are walked down the Typer command tree; options must belong to the command reached.
Placeholders (``PLAN_ID``, ``RUN_ID``, ``...``) end the walk. The checks only read the docs and ask the CLI for help
text; nothing is executed.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from b1500_test_agent.adapters.cli import app

REPO_ROOT = Path(__file__).resolve().parents[2]
BRINGUP = REPO_ROOT / "docs" / "hardware-bringup.md"
DEPLOYMENT = REPO_ROOT / "docs" / "deployment-windows.md"
DOCS = (BRINGUP, DEPLOYMENT)

CODE_SPAN = re.compile(r"`([^`\n]+)`")
COMMAND_START = re.compile(r"(?:^|(?<=[\s(]))b1500(?=\s|$)")
COMMAND_WORD = re.compile(r"^[a-z][a-z0-9-]*$")
NUMBER = re.compile(r"^-\d")
STOP_TOKENS = frozenset({";", "&&", "||", "|", "b1500", "uv"})

runner = CliRunner()


def code_snippets(text: str) -> list[str]:
    """Every line of a fenced code block and every inline code span outside the fences."""
    snippets: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        snippets.extend([line] if in_fence else CODE_SPAN.findall(line))
    return snippets


def named_commands(text: str) -> list[list[str]]:
    """The argument tokens of every ``b1500`` command named in ``text`` (without the program name)."""
    commands: list[list[str]] = []
    for snippet in code_snippets(text):
        for match in COMMAND_START.finditer(snippet):
            rest = snippet[match.end():]
            try:
                tokens = shlex.split(rest, comments=True)
            except ValueError:
                tokens = rest.split()
            end = next((i for i, token in enumerate(tokens) if token in STOP_TOKENS), len(tokens))
            commands.append(tokens[:end])
    return commands


def resolve(tokens: list[str]) -> tuple[list[str], Any, list[str], str | None]:
    """Walk ``tokens`` down the CLI tree: (command path, command reached, option names, problem or ``None``).

    Typer ships its own copy of click, so groups are recognised by their ``commands`` mapping."""
    command: Any = typer.main.get_command(app)
    path: list[str] = []
    rest = list(tokens)
    while isinstance(getattr(command, "commands", None), dict) and rest and COMMAND_WORD.match(rest[0]):
        name = rest.pop(0)
        sub = command.commands.get(name)
        if sub is None:
            return path, command, [], f"no command `b1500 {' '.join([*path, name])}`"
        path.append(name)
        command = sub
    options = [token.split("=", 1)[0] for token in rest if token.startswith("-") and not NUMBER.match(token)]
    allowed = {"--help"} | {opt for param in command.params for opt in (*param.opts, *param.secondary_opts)}
    unknown = [option for option in options if option not in allowed]
    if unknown:
        return path, command, options, f"`b1500 {' '.join(path)}` has no option {', '.join(unknown)}"
    return path, command, options, None


def help_problem(path: list[str], options: list[str]) -> str | None:
    """The command appears in its parent's ``--help`` output, its own ``--help`` works and lists every option."""
    if path:
        parent = runner.invoke(app, [*path[:-1], "--help"])
        if parent.exit_code != 0 or not re.search(rf"(?<![\w-]){re.escape(path[-1])}(?![\w-])", parent.output):
            return f"`b1500 {' '.join(path)}` is not listed by `b1500 {' '.join([*path[:-1], '--help'])}`"
    own = runner.invoke(app, [*path, "--help"])
    if own.exit_code != 0:
        return f"`b1500 {' '.join([*path, '--help'])}` exits {own.exit_code}"
    missing = [option for option in options if option not in own.output]
    if missing:
        return f"`b1500 {' '.join([*path, '--help'])}` does not list {', '.join(missing)}"
    return None


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


# -- hardware-bringup.md (WP4.1) ------------------------------------------------------------------------------------

STAGES = ("Stage 0", "L0", "L1", "L2", "L3", "L4")
STAGE_FIELDS = ("Preconditions", "Commands", "Expected values", "Abort criteria", "Sign-off")
STAGE_ATVS = {"Stage 0": ("ATV-3",), "L0": ("ATV-2", "ATV-10", "ATV-4"), "L1": ("ATV-1",), "L4": ("ATV-11", "ATV-7")}
STAGE_COMMANDS = {
    "L0": ("doctor --probe", "status"),
    "L1": ("plan basic.contact_resistor", "run --confirm", "shutdown", "analyze"),
    "L2": ("plan basic.contact_resistor", "run --confirm"),
    "L3": ("plan basic.diode_iv", "run --confirm"),
    "L4": ("plan mosfet.idvg", "plan mosfet.idvd", "plan mosfet.gate_leakage", "dev recipe-check"),
}


def stage_sections() -> dict[str, str]:
    found: dict[str, str] = {}
    for heading, body in sections(BRINGUP.read_text(encoding="utf-8"), 2).items():
        stage = next((s for s in STAGES if heading == s or heading.startswith(f"{s} ")), None)
        if stage is not None:
            found[stage] = body
    return found


def test_bringup_has_every_stage_with_every_field() -> None:
    stages = stage_sections()
    assert list(stages) == list(STAGES)
    for stage, body in stages.items():
        fields = list(sections(body, 3))
        for field in STAGE_FIELDS:
            assert any(f == field or f.startswith(f"{field} ") for f in fields), f"{stage}: no '### {field}'"
        sign_off = sections(body, 3)[next(f for f in fields if f.startswith("Sign-off"))]
        assert "name ________ date ________" in sign_off, f"{stage}: sign-off line needs name and date"


def test_bringup_stages_name_their_commands() -> None:
    stages = stage_sections()
    for stage, needed in STAGE_COMMANDS.items():
        named = [" ".join(tokens) for tokens in named_commands(stages[stage])]
        for command in needed:
            assert any(n.startswith(command) for n in named), f"{stage}: `b1500 {command}` not named"


def test_bringup_attaches_each_atv_with_its_fallback() -> None:
    stages = stage_sections()
    for stage, atvs in STAGE_ATVS.items():
        body = stages[stage]
        for atv in atvs:
            assert re.search(rf"{atv}(?!\d)", body), f"{stage}: {atv} missing"
            assert "allback" in body[body.index(atv):], f"{stage}: no fallback after {atv}"


# -- deployment-windows.md (WP4.2) ----------------------------------------------------------------------------------

REQUIRED_FACTS = ("GPIB adapter", "VISA vendor", "Internet", "wheelhouse", "EasyEXPERT", "versions", "Backup")
PROCEDURE_ORDER = (  # blueprint 7: Python + uv + VISA -> clone -> sync -> config/local -> probe -> harness -> Codex
    "uv python install", "VISA stack", "git clone", "uv sync --frozen", "Copy-Item config\\settings.example.yaml",
    "b1500 doctor --probe", "b1500 harness init --codex", "```powershell\ncodex\n```",
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
