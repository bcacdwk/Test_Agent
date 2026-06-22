# Roadmap

## Phase 0: Repository Skeleton

- Codex CLI project guidance.
- Repo skills and reference skeleton.
- Python package layout.
- Configuration examples.
- Local git initialization.

## Phase 1: Safe SMU Prototype

- PyVISA transport wrapper.
- Session lifecycle and instrument lock.
- `*IDN?`, `UNT?`, `ERRX?`, safe shutdown.
- Mock B1500A for development without hardware.
- Spot IV and staircase IV recipe skeletons promoted to tested code.

## Phase 2: MCP and Analysis Loop

- MCP server with connection, status, IV, and safe shutdown tools.
- Data persistence for raw traces, parsed traces, and metadata.
- Basic IV plotting and parameter extraction.
- Quality checks based on status codes and compliance hits.

## Phase 3: Pulse and Capacitance Expansion

- WGFMU pulse workflow after B1530A manual extraction.
- HVSPGU/SPGU program-read workflow after 16440A selector extraction.
- CMU/MFCMU C-V and QSCV only after correction and SCUU flows are encoded.

## Phase 4: Bounded Closed Loop

- Adaptive sweep envelopes.
- Stop conditions.
- Report generator.
- Verified recipe registry.
- Real hardware validation logs.
