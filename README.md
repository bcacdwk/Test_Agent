# B1500A Test Agent

B1500A Test Agent is a Codex CLI oriented framework for building a safe, auditable, and extensible semiconductor test agent around the Keysight B1500A Semiconductor Device Analyzer.

The project is intentionally structured as an experimental operating layer, not as a chatbot that sends raw FLEX commands. Natural language intent should flow through skills, rules, typed schemas, deterministic Python tools, safety policies, and only then reach the instrument.

## What This Repository Contains

- A Python package skeleton for the B1500A driver kernel, MCP server, data schemas, and analysis layer.
- Codex CLI project guidance through `AGENTS.md` and scoped nested `AGENTS.md` files.
- Repo-scoped Codex skills under `.agents/skills`.
- Example Codex MCP configuration under `.codex/config.example.toml`.
- Structured reference stubs for instrument manuals, station profiles, device profiles, recipes, physics, HSPICE, and debugging notes.
- Test and mock-instrument placeholders for safe development before real hardware validation.

## System Boundaries

```text
User intent
  -> Codex skills
  -> AGENTS.md rules and project memory
  -> MCP tools
  -> Python driver kernel
  -> PyVISA / GPIB
  -> B1500A and DUT
```

## Module Roadmap

This skeleton keeps SMU, WGFMU, SPGU/HVSPGU, and CMU/MFCMU as first-class areas so the repository can grow cleanly.

Current implementation maturity:

- SMU: first implementation target for connection, preflight, spot IV, staircase IV, and gate leakage checks.
- WGFMU: high-priority pulse and reliability direction; command details are stubbed pending manual extraction.
- SPGU/HVSPGU: pulse programming and SMU readback workflows are stubbed, including 16440A selector references.
- CMU/MFCMU: represented in the architecture, but C-V/QSCV implementation is delayed until correction and SCUU flows are verified.

## Safety Position

No code in this initial skeleton should control real hardware. The first real implementation must start with transport, session state, safety validation, audit logging, and mock-instrument tests.

Safety rules that must become executable policy:

- Never expose raw FLEX command execution by default.
- Validate channel maps, voltage/current limits, interlock state, and compliance before sourcing.
- Use typed command builders instead of ad hoc command strings.
- Ensure every measurement transaction has cleanup behavior that reaches `DZ` and `CL` where appropriate.
- Persist raw data, parsed data, metadata, status codes, and assumptions for every run.

## Codex CLI Integration

Codex reads project guidance from `AGENTS.md`. This repo also includes nested `AGENTS.md` files for driver and analysis subtrees.

Repo skills live in `.agents/skills`. They are intended for task-specific workflows, such as B1500A semiconductor testing and debug triage.

The example MCP configuration is in `.codex/config.example.toml`. Copy relevant parts into a trusted project `.codex/config.toml` or into `~/.codex/config.toml` when the MCP server is implemented.

## Development Status

This is a skeleton repository. Most files are intentionally placeholders that document boundaries and naming. The next meaningful milestone is a safe local prototype:

1. Mock B1500A session and parser tests.
2. PyVISA transport wrapper.
3. Module discovery through `UNT?`.
4. Safety policy validation.
5. Spot IV and staircase IV recipes.
6. MCP tools for connect, status, IV measurement, and safe shutdown.

## License

License is TBD. Choose an open-source license before publishing.
