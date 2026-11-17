"""Tiers and the hard-limit code ceiling (blueprint 2.5, 4.3).

WP1.1 provides only the ceiling, re-exported from ``models.policy`` so that the config loader (which validates
``policy.hard_limits`` against it, rule R-CFG-01) does not depend on ``rules``. WP1.4 adds tier computation and
``plan_summary``.
"""

from __future__ import annotations

from b1500_test_agent.models.policy import HARD_CEILING_A, HARD_CEILING_V

__all__ = ["HARD_CEILING_A", "HARD_CEILING_V"]
