# C Flow Design Arbitration

Date: 2026-11-03

Status: accepted seven-family taxonomy; implementation contract for fake C flows.

## Scope and Principles

`C_flow_<measurement_family>_<object>_<subject>` composes C atoms serially.
Families: `spot`, `sweep`, `pulse`, `waveform`, `sampling`, `search`, `remote`.
The module/object axis follows C atoms. These flows model reusable measurement
operations, not device-specific experiments or complete safe transactions.

Sources: current `c_atoms.py`, `tmp/c_atom_arbitration.md`, the A/B/AB flow
contracts, and `references/manuals/structured/b1500a-command-parameters.md`
(including the required-command table before XE). This is a composition design
over existing fake interfaces, not newly validated hardware programming guidance.

## Composition Boundary

- Only C atoms are invoked. A/B dependencies are reported, never called implicitly.
- Connection, inventory, DUT/pin map, limits/compliance, interlock, output enabling,
  parser/buffer preparation, routing and correction belong to the outer transaction.
- Every future real transaction must install failure cleanup before any sourcing,
  including WGFMU update and CMU signal configuration. The fake runner does not
  claim that a cleanup plan has been executed or that outputs are safe.
- A synchronous fake completion permits a C-specific fake read. A started, pending
  or unknown completion state skips reads and hands completion checking to A/ABC.
- SPGU starts a bounded train/sequence; it does not immediately stop it or claim
  completion. Normal stop remains an existing C atom; emergency cleanup remains B.
- Missing source/compliance/mode details in existing atoms are explicit contract
  gaps. Such flows compose available configuration atoms but skip execution/read.
- Empty synthetic arrays are preserved as empty. No physical results, successful
  correction, validated station state or data quality are inferred from them.

## Catalog

Thirty flows cover all seven families. Exact ordered atom tables, request types,
and outputs are maintained in the formal `mcp-tools/c-flows.md` reference.

| Family | Objects | Subjects | Count |
|---|---|---|---:|
| spot | smu, wgfmu, cmu | smu: iv, high_speed; wgfmu: dc; cmu: impedance, high_speed | 5 |
| sweep | smu, cmu | smu: staircase, synchronous, multi_channel, qscv; cmu: cv, cf, ac_level | 7 |
| pulse | smu, spgu, cmu | smu: spot, sweep, staircase_pulsed_bias, multi_channel, quasi; spgu: train; cmu: spot, cv | 8 |
| waveform | wgfmu, spgu | wgfmu: acquire; spgu: sequence | 2 |
| sampling | smu, cmu | smu: iv_time, signal_monitor, spgu_bias; cmu: ct | 4 |
| search | smu | target (linear/binary parameter) | 1 |
| remote | easyexpert | selected_test, repeat, quick_sequence | 3 |

## Decisions

- Source voltage/current, linear/logarithmic sweep, two/three-level SPGU pulses,
  and linear/binary search are parameters, not duplicate flow names.
- Pulsed sweeps belong to pulse, and QSCV belongs to sweep/smu.
- WGFMU acquisition is waveform-centric; no duplicate sampling wrapper is added.
- SMU sampling with SPGU pulse bias is a C-only mixed-module operation on FLEX.
  Selector switching and sequential program/read experiments remain ABC.
- Remote flows are intentional thin execution adapters because selection and
  fetch are A. Repetition uses the existing repeat atom once, not an unbounded
  Python loop; quick sequence execution does not invent a software editor.
- No high-power wrapper-only flow is added: current HVSMU/HCSMU/UHCU/HVMCU/UHVU
  atoms lack an explicit mode/points/completion/data contract. Retain those atoms
  and reserve object-specific spot/sweep/pulse flows for a meaningful composition.
- Id-Vg/Id-Vd, FeFET write/read, PUND, endurance and retention remain recipes/ABC
  workflows over these primitives, with device limits and stop conditions.
- Waveform transforms, timer-start variants, event-partial reads and trigger
  wiring remain existing atoms rather than one new flow per command. The waveform
  acquisition flow accepts multiple channels, vectors and measurement events.

## Known Atom Gaps

Configuration-only flows must return `partial: true`, `measurement_completed:
false`, and exact `contract_gaps`, with execute/read steps recorded as skipped.

| Subject | Gap to close before an executable recipe |
|---|---|
| sweep/smu/synchronous | Synchronous source atom has no independent compliance/range contract. |
| sweep/smu/multi_channel | WNX wrapper omits per-channel source trajectories and compliance. |
| pulse/smu/sweep | PWV/PWI wrapper omits base level, compliance and source range. |
| pulse/smu/staircase_pulsed_bias | Combined wrapper omits separate sweep/bias compliance. |
| pulse/smu/multi_channel | MCP wrapper omits per-channel source, base/pulse levels and compliance. |
| pulse/smu/quasi | BD wrapper omits compliance and measurement-specific configuration. |
| sampling/smu/iv_time, spgu_bias | Sampling wrapper omits explicit MI/MV base/bias/compliance settings. |
| sampling/smu/signal_monitor | DSMPL wrapper lacks a dedicated execution/completion contract. Do not invent an MM mode. |
| search/smu/target | LS/BS wrapper omits source/sense functions, search start/step/tolerance and compliance. |

CMU and QSCV can exercise fake composition, but real execution remains blocked
until correction freshness, SCUU/topology and leakage validation exist. Even the
other executable fake examples are not certified hardware recipes.

## Response and Failure Contract

Keep the existing flow envelope: `flow`, `flow_class`, `category`, `object`,
`subject`, `fake`, `hardware_touched`, `ok`, `partial`, `destructive`, `consumptive`,
`atoms_called`, `atom_results`, `inputs`, `outputs`, `warnings`, `purpose`.

Add explicit `execution_state`, `measurement_completed` (always false for fake
tools), `simulation_completed`, `required_preconditions`, `contract_gaps`, and
`cleanup` (outer transaction responsibility, `performed: false`).

Preserve each child payload and timestamp. Catch atom exceptions and explicit
failure statuses, stop later configuration/execution/read, retain failed and
skipped records, and report failure without losing earlier evidence. Validate
requests before the first atom call. Do not continue after unexpected non-fake
atom results. Real I/O is not supported by this runner.

## Validation

- Discover all 30 tools through FastMCP with typed request schemas.
- Exercise every family and verify C-only ordered calls and fake markers.
- Verify configuration gaps, asynchronous handoff, no premature data read,
  bounded waveform/sequence inputs and no immediate SPGU stop.
- Inject configuration, execute and read failures; preserve audit and skip later work.
- Verify source/current compliance units, non-default channel forwarding, waveform
  event timing and duplicate channels/patterns, and unchanged legacy registration.
