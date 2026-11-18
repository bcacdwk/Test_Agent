"""Markdown model of the skill lint: headings (GitHub-style ids), fences, links, ``<a id>`` anchors and frontmatter;
``MarkdownDoc.section`` finds a heading's line range."""


from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from b1500_test_agent.config import load_yaml
from b1500_test_agent.devtools.sync_harness import frontmatter_end, normalize_text

# == Markdown =========================================================================================================

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_INLINE_LINK = re.compile(
    r"!?\[(?:[^\[\]\\]|\\.|\[[^\[\]]*\])*\]"
    r"\(\s*(<[^<>\n]*>|[^\s()<>]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
_REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*(<[^<>\n]*>|\S+)")
_HTML_ANCHOR = re.compile(r"<a\s[^>]*\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_HEADING_MARKUP = re.compile(r"!?\[([^\]]*)\]\([^)]*\)|<[^>]+>")


def slugify(text: str) -> str:
    """GitHub-style heading id: link text kept, markup dropped, lowercase, spaces → ``-``."""
    plain = _HEADING_MARKUP.sub(lambda m: m.group(1) or "", text).replace("`", "")
    lowered = plain.strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum() or ch in " -_").replace(" ", "-")


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int
    slug: str


@dataclass(frozen=True)
class Fence:
    info: str
    line: int
    body: str


@dataclass
class MarkdownDoc:
    """A parsed Markdown file (1-based line numbers count the frontmatter lines)."""

    path: Path
    rel: str
    lines: list[str]
    has_front: bool = False
    front: Any = None
    front_error: str | None = None
    headings: list[Heading] = field(default_factory=list)
    links: list[tuple[str, int]] = field(default_factory=list)
    fences: list[Fence] = field(default_factory=list)
    fenced: set[int] = field(default_factory=set)
    anchors: set[str] = field(default_factory=set)

    def section(self, title: str, level: int = 2) -> tuple[int, int] | None:
        """1-based line range ``(heading line, end line exclusive)`` of the heading ``title`` at ``level``."""
        wanted = norm_title(title)
        for index, heading in enumerate(self.headings):
            if heading.level == level and norm_title(heading.text) == wanted:
                end = next((h.line for h in self.headings[index + 1:] if h.level <= level), len(self.lines) + 1)
                return heading.line, end
        return None


def norm_title(text: str) -> str:
    return " ".join(text.replace("->", "→").split()).casefold()


def parse_markdown(path: Path, rel: str) -> MarkdownDoc:
    """Parse ``path``; raises ``UnicodeDecodeError`` for non-UTF-8 bytes and ``OSError`` when unreadable."""
    lines = normalize_text(path.read_bytes()).split("\n")
    doc = MarkdownDoc(path=path, rel=rel, lines=lines)
    end = frontmatter_end(lines)
    start = 0
    if end is not None:
        doc.has_front, start = True, end + 1
        try:
            doc.front = load_yaml("\n".join(lines[1:end]).encode("utf-8"))
        except yaml.YAMLError as exc:
            doc.front_error = "invalid YAML: " + " ".join(str(exc).split())
    elif lines and lines[0].rstrip() == "---":
        doc.has_front, start = True, 1
        doc.front_error = "frontmatter is not closed by a '---' line"
    slugs: dict[str, int] = {}
    fence: tuple[str, int, str, int, list[str]] | None = None  # char, length, info, line, body
    for index in range(start, len(lines)):
        line, number = lines[index], index + 1
        if fence is not None:
            doc.fenced.add(number)
            close = _FENCE_CLOSE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1]:
                doc.fences.append(Fence(info=fence[2], line=fence[3], body="\n".join(fence[4])))
                fence = None
            else:
                fence[4].append(line)
            continue
        opening = _FENCE_OPEN.match(line)
        if opening:
            doc.fenced.add(number)
            fence = (opening.group(1)[0], len(opening.group(1)), opening.group(2).lower(), number, [])
            continue
        heading = _HEADING.match(line)
        if heading:
            text = _CLOSING_HASHES.sub("", heading.group(2) or "").strip()
            slug = slugify(text)
            count = slugs.get(slug, 0)
            slugs[slug] = count + 1
            unique = slug if count == 0 else f"{slug}-{count}"
            doc.headings.append(Heading(level=len(heading.group(1)), text=text, line=number, slug=unique))
            doc.anchors.add(unique)
        doc.anchors.update(_HTML_ANCHOR.findall(line))
        plain = _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)
        doc.links.extend((target, number) for target in _INLINE_LINK.findall(plain))
        reference = _REF_DEF.match(plain)
        if reference:
            doc.links.append((reference.group(1), number))
    if fence is not None:
        doc.fences.append(Fence(info=fence[2], line=fence[3], body="\n".join(fence[4])))
    return doc


