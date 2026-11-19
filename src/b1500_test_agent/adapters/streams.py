"""Console streams that never fail on a character they cannot encode (blueprint v2 7.1 "Windows CI", WP6.5).

On Windows without UTF-8 mode (``PYTHONUTF8`` unset), a redirected stdout or stderr (a pipe to a coding harness,
``> file``, ``| Out-File``) uses the ANSI code page: cp1252 on a western Windows, cp936 on a Chinese one. Python then
raises ``UnicodeEncodeError`` at the first character outside that code page (``Ω`` in a manual page, ``≤`` in a
``doctor`` line, CJK text in a manual search) and the command dies with a traceback in the middle of its output.
``safe_streams()`` keeps each stream's encoding but switches its error handler to ``backslashreplace``
(``Ω`` → ``\\u03a9``): the output degrades visibly instead of failing. UTF-8 streams are left alone: ``PYTHONUTF8=1``
(the documented lab setting, checked by ``b1500 doctor``), macOS and Linux, and an interactive Windows console
(Python writes it through the console's UTF-16 API, PEP 528).

The MCP server's JSON-RPC channel is not affected: the stdio transport writes UTF-8 to the binary buffer itself.
"""

from __future__ import annotations

import codecs
import sys

STREAMS = ("stdout", "stderr")
ERRORS = "backslashreplace"


def is_utf(encoding: str | None) -> bool:
    """True for any UTF encoding name (``utf-8``, ``UTF8``, ``utf_8_sig``, ``utf-16`` ...)."""
    try:
        return codecs.lookup(encoding or "").name.startswith("utf")
    except LookupError:
        return False


def safe_streams() -> list[str]:
    """Give ``sys.stdout``/``sys.stderr`` the ``backslashreplace`` error handler when their encoding is not a UTF
    encoding (see the module docstring); returns the names of the streams changed. Never raises."""
    changed: list[str] = []
    for name in STREAMS:
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None or is_utf(getattr(stream, "encoding", None)):
            continue
        if getattr(stream, "errors", None) == ERRORS:
            continue
        try:
            reconfigure(errors=ERRORS)
        except (ValueError, OSError, TypeError):
            continue
        changed.append(name)
    return changed
