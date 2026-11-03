# Instrument Interaction MCP Tools

This is the short index for the fake-but-loadable B1500A MCP tool surface. The detailed tool tables are split by category so future agents can read only the relevant section.

## Tool Families

- [A atoms](mcp-tools/a-atoms.md): interface/session/context/readback/discovery tools.
- [B atoms](mcp-tools/b-atoms.md): safety/state-control tools categorized by risk or operation type.
- [C atoms](mcp-tools/c-atoms.md): source, measurement configuration, execution and data-read primitives.
- [A flows](mcp-tools/a-flows.md): A-only orchestration flows that compose A atoms serially.
- [B flows](mcp-tools/b-flows.md): B-only safety/state-control compositions.
- [C flows](mcp-tools/c-flows.md): C-only measurement compositions across seven families.
- [AB flows](mcp-tools/ab-flows.md): observe/act/verify workflow orchestration.

## Naming Taxonomy

**A atoms**

```text
A_atom_<interface>_<action>
```

Interfaces: `flex`, `wgfmu`, `easyexpert`.

**B atoms**

```text
B_atom_<risk_category>_<target>_<action>
```

Categories: `safety`, `output`, `lifecycle`, `diagnostic`, `calibration`, `routing`, `correction`, `policy`.
Targets: `b1500`, `smu`, `asu`, `scuu`, `cmu`, `qscv`, `wgfmu`, `easyexpert`.

**A flows**

```text
A_flow_<operation>_<interface>_<subject>
```

Operations currently include `discover`, `snapshot`, `drain`, `collect`, `prepare`, `select`, and `teardown`.

**C atoms and flows**

```text
C_atom_<object>_<action>
C_flow_<measurement_family>_<object>_<subject>
```

Flow families: `spot`, `sweep`, `pulse`, `waveform`, `sampling`, `search`, `remote`.
C flows call only C atoms and report external A/B prerequisites. They distinguish
synthetic completion, configuration-only gaps, and pending completion. All tools
remain fake; real hardware execution and complete ABC transactions are not implemented.

**B and AB flows**

```text
B_flow_<category>_<target>_<subject>
AB_flow_<category>_<scope>_<subject>
```

## Primary Sources

- `B1500A Programming Guide.pdf`
- `B1530A WGFMU.pdf`
- `Keysight EasyEXPERT Software.pdf`
- `test_agent/references/manuals/*-index.md`
- `test_agent/references/manuals/structured/*`

## Implementation Notes

- Do not add a default `send_raw_flex_command` tool.
- If an expert raw command path is added later, it must be disabled by default, approval-gated, and audited.
- Query responses and measurement data buffers are different. Real tools must consume query responses promptly and not assume measurement data is available after errors.
- Atom and flow names are stable MCP surface names. Do not expose legacy unprefixed aliases unless a migration layer is explicitly requested.
