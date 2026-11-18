"""Relative link and anchor checks of the skill lint: every link resolves, with exact case, inside its own skill
folder; ``#anchors`` are heading ids of the target."""


from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

from b1500_test_agent.devtools.skills.common import Lint
from b1500_test_agent.devtools.skills.markdown import MarkdownDoc

URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def exists_exact(base: Path, target: Path) -> bool:
    """``target`` (inside ``base``) exists with exactly this spelling of every path component."""
    current = base
    for part in target.relative_to(base).parts:
        try:
            names = os.listdir(current)
        except OSError:
            return False
        if part not in names:
            return False
        current = current / part
    return True


def check_links(lint: Lint, doc: MarkdownDoc, skill_dir: Path) -> None:
    for raw_target, line in doc.links:
        target = raw_target[1:-1].strip() if raw_target.startswith("<") else raw_target
        if not target:
            lint.add("link", doc.path, "empty link target", line)
            continue
        if WINDOWS_ABSOLUTE.match(target) or target.startswith(("/", "\\")):
            lint.add("link", doc.path, f"absolute link {target!r}; link relative to the skill folder", line)
            continue
        if URL_SCHEME.match(target):
            continue  # external URL (https:, mailto: ...)
        path_part, _, anchor = target.partition("#")
        path_part = unquote(path_part.split("?", 1)[0])
        if not path_part:
            if anchor and anchor not in doc.anchors:
                lint.add("anchor", doc.path, f"link #{anchor}: no heading with this id in this file", line)
            continue
        resolved = Path(os.path.normpath(doc.path.parent / path_part))
        if not resolved.is_relative_to(skill_dir):
            lint.add("link", doc.path, f"link {target!r} leaves the skill folder {lint.rel(skill_dir)}", line)
            continue
        if not exists_exact(skill_dir, resolved):
            lint.add("link", doc.path, f"broken link {target!r}: {lint.rel(resolved)} does not exist", line)
            continue
        if anchor and resolved.is_file() and resolved.suffix.lower() == ".md":
            target_doc = lint.doc(resolved)
            if target_doc is not None and anchor not in target_doc.anchors:
                lint.add("anchor", doc.path, f"link {target!r}: {lint.rel(resolved)} has no heading id {anchor!r}",
                         line)


