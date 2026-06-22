# Analysis Layer Instructions

This subtree owns deterministic data analysis, plotting, quality checks, and reporting helpers.

## Analysis Rules

- Separate raw measured values, derived parameters, assumptions, and recommendations.
- Always carry units in result objects and reports.
- Inspect B1500A measurement status codes before trusting data.
- Exclude or flag compliance-limited, overvoltage, oscillation, and invalid points before fitting.
- Report extraction methods for parameters such as `Vth`, `gm`, `SS`, `Cox`, and `Vfb`.
- Prefer deterministic algorithms for calculations; use LLM output only for narrative explanation.

## Plotting Rules

- Plot raw data before parameter extraction.
- For current data that spans decades, provide semilog views where useful.
- Save figure metadata alongside generated files so reports are reproducible.
