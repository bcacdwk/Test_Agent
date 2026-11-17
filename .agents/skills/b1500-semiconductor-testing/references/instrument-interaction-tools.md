# Instrument Interaction MCP Tools

This is the short index for the fake-but-loadable B1500A MCP tool surface. The detailed per-family tool tables were moved out of this skill in WP0.4 as frozen history (they are no longer agent references); this legacy skill is removed in WP0.5.

## Tool Families

- A atoms: interface/session/context/readback/discovery tools.
- B atoms: safety/state-control tools categorized by risk or operation type.
- C atoms: source, measurement configuration, execution and data-read primitives.
- D atoms: hardware-free post-acquisition analysis placeholders (ingest, qualify, shape, derive, extract, assess, archive, render).
- A flows: A-only orchestration flows that compose A atoms serially.
- B flows: B-only safety/state-control compositions.
- C flows: C-only measurement compositions across seven families.
- AB flows: observe/act/verify workflow orchestration.
- D flows: D-atom-only qualify/screen/analyze/archive compositions over a held C flow envelope.
- CD flows: expect -> measure (one C flow) -> interpret (its D flow) -> archive; fake-only.

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

**D atoms**

```text
D_atom_<stage>_<subject>_<action>
```

Stages (ordered): `ingest`, `qualify`, `shape`, `derive`, `extract`, `assess`, `archive`, `render`.
Each stage has a closed subject set (for example `extract`: `leakage`, `transfer`, `output`, `cv`).
D atoms consume evidence that A/C already returned and never touch hardware, never call A/B/C tools
and never decode instrument bytes: A owns parser/buffer plumbing, C owns measurement-specific reads,
D owns what the data means. Under U1 every D atom is a fake placeholder stub that returns a
content-free `ProductRef` (`content: null`, deterministic id); synthetic data is labelled
`synthetic_only` and can never pass. `ok: false` means a tool error only; data verdicts live in
`check_outcome`, `trust_level`, `verdict` and `findings`. The only writer,
`D_atom_archive_run_write_bundle`, returns planned paths and a refusal; no file is written.

**D and CD flows**

```text
D_flow_<operation>_<domain>_<subject>
CD_flow_<operation>_<domain>_<subject>
```

Operations: `qualify`, `screen`, `analyze` (D also `archive`); domains are data kinds:
`iv`, `cv`, `timeseries` (D also `run`). D flows call only D atoms, serially and in
catalog order, over a C flow envelope the caller already holds, and read only its
designated read record (handoff `received` or `empty`). A CD flow calls exactly one
`C_flow_<acquisition.kind>`, the D flow with the same name, and
`D_flow_archive_run_bundle`; it never calls A/B tools or C atoms directly, reports A/B
prerequisites, and treats caller-passed A/B evidence as unverified. Configuration-only,
pending and failed C states skip interpretation with a reason but still plan the
archive. `ok: false` means a composition error or taint violation, never a data
verdict; synthetic data can never pass; cleanup stays with the outer transaction;
nothing is written. CD stays fake-only (U7).

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
