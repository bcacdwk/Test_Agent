"""Built-in rules of blueprint 4.2 (v1) / 2.8 (v2), registered in table order (which is also the finding order).

Thresholds come only from ``policy.yaml``, the station profile, pin maps, DUT profiles, recipe ``ParamSpec.range``
and the code tables (module specs in ``driver/modules.py``, the hard-limit ceiling in ``rules/tiers.py``).
Limits compare magnitudes and are exclusive: a value equal to a limit passes (10 V with a 10 V soft limit is ``ok``).

Every voltage/current check runs over the plan's ``CompiledEnvelope`` (the per-channel |V| and |I| the
``OutputGuard`` will enforce), never over the raw request, so a rule and the guard can never disagree about what
may be applied. Live-state rules (R-INV-01, R-IL-01, R-ERRX-01) also run in the ``plan`` phase when a snapshot is
supplied and skip otherwise; they only block or warn, so the plan summary depends on config alone.

R-QUAL-* is the post-run classification of per-point status letters (``quality_findings``); it is not a phase of
``RulesEngine.evaluate`` and is reached through ``RulesEngine.quality``. It does not import ``analysis``, which
owns the detailed quality report and the extraction gate.

Modules, imported below in table order (import order = registration order = finding order): ``core`` (R-CFG-01 ...
R-INV-01), ``limits`` (R-LIM-01 ... R-IL-01, R-GNDU-01), ``run`` (R-RUN-01, R-RUN-02, R-ALWAYS-01, R-ERRX-01,
R-CAL-01, R-CAL-02, R-QUAL-*), ``pulse`` (R-PULSE-01 ... R-PULSE-03, R-SPGU-01, R-WG-01, R-WG-02), ``route``
(R-ROUTE-01, R-ROUTE-02, R-ASU-01), ``cmu`` (R-CMU-01, R-CORR-01); shared helpers in ``common``. A new rule family
module is imported at its place in the table.
"""

# Import order = registration order = finding order (the rule table); "isort: split" keeps it.
from b1500_test_agent.rules.builtin import core as core

# isort: split
from b1500_test_agent.rules.builtin import limits as limits

# isort: split
from b1500_test_agent.rules.builtin import run as run

# isort: split
from b1500_test_agent.rules.builtin import pulse as pulse

# isort: split
from b1500_test_agent.rules.builtin import route as route

# isort: split
from b1500_test_agent.rules.builtin import cmu as cmu

# isort: split
from b1500_test_agent.rules.builtin.common import (
    ASU_1PA_FULL_SCALE_A,
    ASU_1PA_SETTING,
    COMPLIANCE_SETTING,
    CURRENT_SOURCING_FUNCTIONS,
    INTERLOCK_ERRORS,
    MEASURE_RANGE_SETTING,
    SOURCING_FUNCTIONS,
    VOLTAGE_COMPLIANCE_SETTING,
    measure_range_a,
)
from b1500_test_agent.rules.builtin.limits import interlock_errors
from b1500_test_agent.rules.builtin.run import cmu_status_letter, quality_findings, wgfmu_status_letter

__all__ = [
    "ASU_1PA_FULL_SCALE_A",
    "ASU_1PA_SETTING",
    "COMPLIANCE_SETTING",
    "CURRENT_SOURCING_FUNCTIONS",
    "INTERLOCK_ERRORS",
    "MEASURE_RANGE_SETTING",
    "SOURCING_FUNCTIONS",
    "VOLTAGE_COMPLIANCE_SETTING",
    "cmu",
    "cmu_status_letter",
    "core",
    "interlock_errors",
    "limits",
    "measure_range_a",
    "pulse",
    "quality_findings",
    "route",
    "run",
    "wgfmu_status_letter",
]
