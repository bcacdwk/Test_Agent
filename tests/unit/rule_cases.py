"""Shared row types of the table-driven rule tests (``test_rules_builtin.py`` v1 rows, ``test_rules_v2.py`` v2 rows):
an expected finding (severity, observed, limit, source, confirm reason) and one case (rule id, builder, phase)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.rules.engine import RuleContext


@dataclass(frozen=True)
class F:
    """Expected finding: severity, observed, limit, source and (for confirm) reason."""

    severity: str
    observed: Any
    limit: Any
    source: str
    reason: str | None = None


@dataclass(frozen=True)
class Case:
    id: str
    rule_id: str
    build: Callable[[], tuple[ConfigBundle, RuleContext]]
    expect: tuple[F, ...] = ()
    phase: str = "plan"
