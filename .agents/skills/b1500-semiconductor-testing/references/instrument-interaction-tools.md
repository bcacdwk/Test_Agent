# Instrument Interaction MCP Tools

This is the short index for the fake-but-loadable B1500A MCP tool surface. The detailed tool tables are split by category so future agents can read only the relevant section.

## Tool Families

- [A atoms](mcp-tools/a-atoms.md): interface/session/context/readback/discovery tools.
- [B atoms](mcp-tools/b-atoms.md): safety/state-control tools categorized by risk or operation type.
- [A flows](mcp-tools/a-flows.md): A-only orchestration flows that compose A atoms serially.

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

**Future C atoms/flows** are measurement tools and are intentionally not implemented yet.

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
- A/B atom names and A flow names are intentionally stable MCP surface names. Do not expose legacy unprefixed aliases unless a migration layer is explicitly requested.
