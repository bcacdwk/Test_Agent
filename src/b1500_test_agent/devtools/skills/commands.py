"""Every ``b1500`` command named in the skills (stage files included) and the docs exists in the CLI (blueprint v2
6.2, 8.1 ``skills/``); problem code ``command``.

Commands are taken from fenced code blocks and inline code spans: every ``b1500`` token (also after ``uv run``)
starts a command whose following words are walked down the Typer command tree; options must belong to the command
reached, which must be listed by its parent's ``--help`` and answer its own ``--help`` listing every option.
Placeholders (``PLAN_ID``, ``<terms>``, ``...``) end the walk; ``a|b`` alternatives (``status|recipes``,
``--codex|--claude``) are checked one by one. Nothing is executed except ``--help``.

"Listed by ``--help``" is decided from the command tree (a command or option shows in the help unless it is
``hidden``), never by searching the rendered help text: Typer renders help through Rich, which colours and
re-wraps it whenever ``GITHUB_ACTIONS``, ``FORCE_COLOR`` or ``PY_COLORS`` is set or the terminal is narrow, so a
text search answered differently on CI than on the developer's machine (WP6.5). ``--help`` itself still runs once
per command and must exit 0.

Scope: ``.agents/skills/**/*.md``, ``docs/**/*.md`` except ``docs/design/`` (the plan of record and the WP log name
planned and retired commands) and the dated session reports ``docs/acceptance/<YYYY-MM-DD>-*.md`` (history),
``README.md``, ``AGENTS.md``, ``CLAUDE.md`` and the nested ``src/b1500_test_agent/**/*.md``.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

from b1500_test_agent.devtools.skills.common import Lint

CODE_SPAN = re.compile(r"`([^`\n]+)`")
COMMAND_START = re.compile(r"(?:^|(?<=[\s(]))b1500(?=\s|$)")
COMMAND_WORD = re.compile(r"^[a-z][a-z0-9-]*$")
NUMBER = re.compile(r"^-\d")
STOP_TOKENS = frozenset({";", "&&", "||", "|", "b1500", "uv"})
DESIGN_DOCS = "design"
DATED_REPORT = re.compile(r"^acceptance/\d{4}-\d{2}-\d{2}-[^/]+\.md$")


def code_snippets(text: str) -> list[tuple[int, str]]:
    """``(line, snippet)``: every line of a fenced code block and every inline code span outside the fences."""
    snippets: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        snippets.extend([(number, line)] if in_fence else [(number, span) for span in CODE_SPAN.findall(line)])
    return snippets


def named_commands_at(text: str) -> list[tuple[int, list[str]]]:
    """``(line, tokens)`` of every ``b1500`` command named in ``text`` (tokens without the program name)."""
    commands: list[tuple[int, list[str]]] = []
    for number, snippet in code_snippets(text):
        for match in COMMAND_START.finditer(snippet):
            rest = snippet[match.end():]
            try:
                tokens = shlex.split(rest, comments=True)
            except ValueError:
                tokens = rest.split()
            end = next((i for i, token in enumerate(tokens) if token in STOP_TOKENS), len(tokens))
            commands.append((number, tokens[:end]))
    return commands


def named_commands(text: str) -> list[list[str]]:
    """The argument tokens of every ``b1500`` command named in ``text`` (without the program name)."""
    return [tokens for _line, tokens in named_commands_at(text)]


def alternatives(tokens: list[str]) -> Iterator[list[str]]:
    """Expand ``a|b`` command words (``status|recipes``) into one token list per alternative."""
    for index, token in enumerate(tokens):
        parts = token.split("|")
        if len(parts) > 1 and all(COMMAND_WORD.match(part) for part in parts):
            for part in parts:
                yield from alternatives([*tokens[:index], part, *tokens[index + 1:]])
            return
    yield tokens


@cache
def _root_command() -> Any:
    import typer

    from b1500_test_agent.adapters.cli import app  # adapters.cli imports this package: import late

    return typer.main.get_command(app)


def resolve(tokens: list[str]) -> tuple[list[str], Any, list[str], str | None]:
    """Walk ``tokens`` down the CLI tree: (command path, command reached, option names, problem or ``None``).

    Typer ships its own copy of click, so groups are recognised by their ``commands`` mapping."""
    command: Any = _root_command()
    path: list[str] = []
    rest = list(tokens)
    while isinstance(getattr(command, "commands", None), dict) and rest and COMMAND_WORD.match(rest[0]):
        name = rest.pop(0)
        sub = command.commands.get(name)
        if sub is None:
            return path, command, [], f"no command `b1500 {' '.join([*path, name])}`"
        path.append(name)
        command = sub
    options = [part.split("=", 1)[0] for token in rest if token.startswith("-") and not NUMBER.match(token)
               for part in token.split("|") if part.startswith("-")]
    allowed = {"--help"} | {opt for param in command.params for opt in (*param.opts, *param.secondary_opts)}
    unknown = [option for option in options if option not in allowed]
    if unknown:
        return path, command, options, f"`b1500 {' '.join(path)}` has no option {', '.join(unknown)}"
    return path, command, options, None


@cache
def _help_exit_code(path: tuple[str, ...]) -> int:
    from typer.testing import CliRunner

    from b1500_test_agent.adapters.cli import app

    return CliRunner().invoke(app, [*path, "--help"]).exit_code


def _command_at(path: list[str]) -> Any | None:
    """The command the words ``path`` name in the CLI tree (``None`` when a word names no command)."""
    command: Any = _root_command()
    for name in path:
        sub = command.commands.get(name) if isinstance(getattr(command, "commands", None), dict) else None
        if sub is None:
            return None
        command = sub
    return command


def _listed_options(command: Any) -> set[str]:
    """Every option name the command's ``--help`` lists: its non-hidden parameters' names plus ``--help``."""
    listed = {"--help"}
    for param in command.params:
        if not getattr(param, "hidden", False):
            listed.update((*param.opts, *param.secondary_opts))
    return listed


def help_problem(path: list[str], options: list[str]) -> str | None:
    """The command appears in its parent's ``--help`` (it exists and is not hidden), its own ``--help`` exits 0 and
    lists every option (each belongs to a non-hidden parameter). Decided from the command tree, see the module
    docstring."""
    command = _command_at(path)
    if path and (command is None or getattr(command, "hidden", False)):
        return f"`b1500 {' '.join(path)}` is not listed by `b1500 {' '.join([*path[:-1], '--help'])}`"
    if command is None:  # the root itself cannot be missing; kept for type narrowing
        return "`b1500 --help` exits with no command tree"
    code = _help_exit_code(tuple(path))
    if code != 0:
        return f"`b1500 {' '.join([*path, '--help'])}` exits {code}"
    missing = [option for option in options if option not in _listed_options(command)]
    if missing:
        return f"`b1500 {' '.join([*path, '--help'])}` does not list {', '.join(missing)}"
    return None


def command_problems(tokens: list[str]) -> list[str]:
    """What is wrong with one named command (every alternative checked)."""
    problems: list[str] = []
    for variant in alternatives(tokens):
        path, _command, options, problem = resolve(variant)
        problem = problem or help_problem(path, sorted(set(options)))
        if problem and problem not in problems:
            problems.append(problem)
    return problems


def command_files(root: Path) -> list[Path]:
    """The files in scope (see the module docstring), sorted."""
    files: set[Path] = set()
    skills = root / ".agents" / "skills"
    if skills.is_dir():
        files.update(skills.rglob("*.md"))
    docs = root / "docs"
    if docs.is_dir():
        for path in docs.rglob("*.md"):
            rel = path.relative_to(docs)
            if rel.parts[0] != DESIGN_DOCS and not DATED_REPORT.match(rel.as_posix()):
                files.add(path)
    source = root / "src" / "b1500_test_agent"
    if source.is_dir():
        files.update(source.rglob("*.md"))
    files.update(p for p in (root / "README.md", root / "AGENTS.md", root / "CLAUDE.md") if p.is_file())
    return sorted(p for p in files if p.is_file() and not p.is_symlink())


def check_commands(lint: Lint) -> int:
    """Lint every ``b1500`` command under ``lint.root``; returns how many were checked."""
    count = 0
    for path in command_files(lint.root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable skill files are reported by the layout checks
        for line, tokens in named_commands_at(text):
            count += 1
            for problem in command_problems(tokens):
                lint.add("command", path, f"{problem} (from: b1500 {' '.join(tokens)})", line)
    lint.notes.append(f"b1500 commands: {count} checked against the CLI")
    return count
