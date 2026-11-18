"""Plan and pre-execute rules, tiers and the canonical plan summary (blueprint 2.5, 4).

``engine`` holds the registry, ``RuleContext``, ``RulesEngine`` and the correction-record source protocol;
``builtin`` the blueprint v1 4.2 / v2 2.8 rules (imported here so that they are registered); ``tiers`` the tier
computation, the hard-limit code ceiling and ``plan_summary``.
"""

from b1500_test_agent.rules import builtin as builtin
from b1500_test_agent.rules.engine import (
    CalibrationState,
    CorrectionRecordSource,
    RuleContext,
    RulesEngine,
    config_findings,
    correction_records,
    registered_rules,
    rule,
)
from b1500_test_agent.rules.tiers import HARD_CEILING_A, HARD_CEILING_V, compute_tier, plan_summary, with_rules

__all__ = [
    "HARD_CEILING_A",
    "HARD_CEILING_V",
    "CalibrationState",
    "CorrectionRecordSource",
    "RuleContext",
    "RulesEngine",
    "compute_tier",
    "config_findings",
    "correction_records",
    "plan_summary",
    "registered_rules",
    "rule",
    "with_rules",
]
