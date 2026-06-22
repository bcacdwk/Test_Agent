# Architecture

The project separates knowledge, policy, execution, and analysis so the agent never needs to improvise raw hardware control.

## Layers

1. Physical safety: shielding, interlock, grounding, Guard, Kelvin, probe contact, and cable topology.
2. Transport: PyVISA session, GPIB address, timeout, terminator, and execution lock.
3. Driver kernel: FLEX builders, parsers, status handling, module discovery, and safety validation.
4. Recipes: complete measurement transactions such as spot IV, staircase IV, pulse stress, and CV sweep.
5. Analysis: deterministic extraction, plotting, quality scoring, and report generation.
6. MCP: tools, resources, and prompts exposed to Codex.
7. Codex guidance: `AGENTS.md`, repo skills, references, and policy files.

## Key Design Decision

The MCP surface should expose outcomes such as `measure_staircase_iv`, not operations such as `send_flex_command`.

Raw FLEX access may be useful for expert development, but it must be disabled by default, approval-gated, audited, and isolated from normal agent workflows.
