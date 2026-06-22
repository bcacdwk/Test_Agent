---
name: b1500-semiconductor-testing
description: Plan, validate, execute, and analyze semiconductor measurements with a Keysight B1500A test-agent stack. Use for B1500A, SMU, WGFMU, SPGU, CMU, FLEX, FeFET, MOSFET, IV, CV, pulse, reliability, or measurement-debug tasks.
---

# B1500 Semiconductor Testing

## Workflow

1. Read `AGENTS.md` and relevant references before proposing or running measurement work.
2. Identify the DUT, terminal map, station profile, module inventory, safety limits, and measurement objective.
3. Choose the smallest safe measurement that can answer the question.
4. Validate the plan against safety policy and recipe constraints.
5. For capacitance work, require leakage checks and correction metadata before trusting results.
6. Run deterministic tools through MCP only after the driver layer and policies support the operation.
7. Interpret status codes and data quality before extracting parameters.
8. Report measured values, derived values, assumptions, warnings, and next steps separately.

## Knowledge Map

- B1500A equipment and FLEX command references: `references/instruments/`
- Station, cable, pin-map, and compensation profiles: `references/station/`
- Device and recipe profiles: `references/devices/` and `references/recipes/`
- Physics, FeFET, reliability, and HSPICE notes: `references/physics/` and `references/hspice/`
- Debug runbooks: `references/debug/`
