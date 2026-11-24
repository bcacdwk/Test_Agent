<!-- GENERATED from .agents/skills by b1500 dev sync-harness; edit the source -->
# Reserved measurement slots

These measurements are planned but **not implemented** in v1. Each one is registered as a recipe with status
`not_implemented` in `recipes/reserved/` (the registry source), so `list_recipes` shows it and `validate_plan`
blocks it (R-REC-01) with zero instrument I/O. There is no card for them yet.

When a request needs one of them:

- Say plainly that it is reserved (`not_implemented`) in v1 and name the recipe id.
- Offer the validated alternative from the table below, if one fits, through its card.
- Never emulate a reserved measurement with another recipe (`generic.smu_staircase`, repeated or long sweeps,
  higher voltages), never write FLEX or PyVISA code, never edit recipes to change a status.

## Slots

| recipe | measurement | validated alternative today |
|---|---|---|
| `wgfmu.fast_bti` | WGFMU fast BTI with on-the-fly Vth monitoring (destructive) | SMU stress-measure-stress (slower reads): [bti-stress-measure](../reliability/bti-stress-measure.md) |
| `fecap.pund` | Ferroelectric capacitor PUND (Pr, Ec) | coercive voltage only: C-V butterfly, [fecap-pund](../nvm/fecap-pund.md) (FeFET: [fefet-dual-sweep-mw](../nvm/fefet-dual-sweep-mw.md)) |

Retired slot: `hspice.compare` (WP7.7). A simulation comparison is analysis, not a measurement: fit and compare a
compact model and export a SPICE netlist with the card [compact-model-spice](../smu/compact-model-spice.md); running
a simulator stays with the human (OD-6). Un-reserved: `moscap.qscv` (WP8.5, card
[moscap-dit](../cmu/moscap-dit.md)).

## Preconditions to un-reserve

From each recipe's `preconditions` list (the recipe file is authoritative). Common to all: a human-reviewed status
change, a card from [the template](../_TEMPLATE.md), a passing `b1500 dev lint-skills` and the M3 suite re-run;
`sim_validated` only after a simulator test against model truth, `hw_validated` only with an M4 validation record.

- `wgfmu.fast_bti`: `wgfmu.pulsed_iv` validated first (done: card [wgfmu-pulsed-iv](../wgfmu/wgfmu-pulsed-iv.md));
  asynchronous runs (`outcome: running`, `get_run` progress) for stresses
  longer than `policy.run_limits.max_sync_run_s`; stress-envelope rules and a DUT-profile stress budget; knowledge
  05 reviewed by a human; sim and hardware validation.
- `fecap.pund`: WGFMU pulse sequences with fast current sampling; PUND charge-integration analysis (Pr, Ec)
  documented in knowledge 04; capacitor DUT profiles with field limits; sim model; sim and hardware validation.
