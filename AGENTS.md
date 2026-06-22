# B1500A Test Agent Instructions

This repository targets Codex CLI. Do not add Cursor-specific `.cursor` files unless an explicit compatibility layer is requested.

## Core Operating Model

- Treat the B1500A as a safety-gated measurement kernel, not as a raw command endpoint.
- Build deterministic Python tools first, then expose them through MCP.
- Keep agent autonomy bounded by schemas, station profiles, safety policies, and validated recipes.
- Prefer structured YAML/JSON/Markdown references over unprocessed PDFs in runtime workflows.

## Safety Rules

- Never implement default raw FLEX command execution.
- Validate channel maps, module capabilities, voltage limits, current limits, compliance, interlock state, and correction state before any measurement.
- Every instrument transaction must define cleanup behavior and reach a safe state on failure.
- All real instrument actions must be auditable: record command intent, parameters, timestamps, module inventory, status codes, raw data, parsed data, and assumptions.
- Unknown DUTs, incomplete pin maps, stale compensation, high voltage, large current, and new recipes require human approval.

## Engineering Rules

- Write code comments and docstrings in English.
- Keep public APIs typed and schema-friendly.
- Use Pydantic models for shared request, policy, recipe, station, and result objects.
- Keep hardware transport independent of Codex, MCP, and skills.
- Do not encode private station details in committed defaults. Use `.example.yaml` files only.

## Measurement Priorities

- SMU IV workflows are the first implementation target.
- WGFMU and HVSPGU/SPGU are first-class pulse areas but remain stubs until manual extraction and validation.
- CMU/MFCMU is represented in the architecture, but C-V/QSCV execution must wait for correction, SCUU, and leakage validation flows.
