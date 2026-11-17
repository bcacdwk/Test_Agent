"""Shared exception types. Each carries the ``ErrorCode`` that service results report (blueprint 2.1).

Layer-specific errors stay in their layer (``transport.TransportError``, ``driver.guard.EnvelopeViolation``);
services translate every exception into a ``ResultEnvelope`` and never raise to adapters.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from b1500_test_agent.models.common import ConfigProblem, ErrorCode


class B1500Error(Exception):
    """Base class of the package's own errors; ``code`` is the result ``error_code``."""

    code: ClassVar[ErrorCode] = "internal"


class InvalidInputError(B1500Error):
    """A request does not match its schema or names something that does not exist."""

    code: ClassVar[ErrorCode] = "invalid_input"


class InvalidConfigError(B1500Error):
    """The configuration is invalid (rule R-CFG-01); ``problems`` lists every reason, one per file and field."""

    code: ClassVar[ErrorCode] = "invalid_config"

    def __init__(self, problems: Sequence[ConfigProblem], message: str | None = None) -> None:
        self.problems: tuple[ConfigProblem, ...] = tuple(problems)
        if message is None:
            count = len(self.problems)
            message = f"invalid configuration ({count} problem{'s' if count != 1 else ''})"
            if self.problems:
                first = self.problems[0]
                where = f"{first.file}: " if first.file else ""
                message += f"; first: {where}{first.message}"
        super().__init__(message)
