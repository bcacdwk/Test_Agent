# Atom Taxonomy Proposal - Opus48

Date: 2026-06-22
Status: proposal only. No code, no production docs, no renames performed.
Scope: subcategory taxonomy for **A atoms** and **B atoms**. C atoms and flows are
considered only for forward-compatibility, not decided here.

---

## Diagnosis Of Current Taxonomy

### What the current scheme is

The current middle token is called `subsystem` and takes three values:

```
{A|B}_atom_{subsystem}_{action}      subsystem in {b1500, wgfmu, easyexpert}
```

### The core defect: the middle token mixes three different axes

The three values are **not peers on any single axis**. Each one is "the level that
happened to have its own PDF":

| Value | What it actually is | Real axis it belongs to |
|---|---|---|
| `b1500` | The native FLEX/GPIB command interface to the mainframe (and, loosely, the mainframe itself) | control interface **and** physical instrument, conflated |
| `wgfmu` | A **module** (B1530A WGFMU card) physically inside the mainframe, but driven through its **own** instrument library/session | physical module **and** a separate control interface, conflated |
| `easyexpert` | A **software application** offering a remote-control API over the same hardware | control interface (software/remote) |

So `b1500` is named after the *product*, `wgfmu` after a *module*, and `easyexpert`
after an *application*. That is exactly the "mechanically mirror the PDF sources"
problem: the taxonomy tracks `B1500A Programming Guide.pdf` / `B1530A WGFMU.pdf` /
`Keysight EasyEXPERT Software.pdf`, not a conceptual model.

### The two axes that are actually hiding in the data

Every atom independently answers two questions:

1. **WHERE / HOW** — which control interface (session/transport) carries the bytes,
   and which physical target (mainframe / module / accessory) is affected.
2. **WHAT** — the operation semantics and risk class (observe vs reset vs energize vs
   route vs calibrate ...).

The `A`/`B`/`C` class prefix is already a *coarse* WHAT axis (A = observe/context,
B = state-change/safety, C = measure). The current `subsystem` token is a *muddled*
WHERE axis. The redesign question is therefore: **what is the best secondary axis
inside A, and inside B?** They need not be the same.

### Conceptual model to anchor the redesign

```
Physical layer     : one B1500A mainframe
                     modules    = SMU (MPSMU/HRSMU/HVSMU), WGFMU, SPGU (HVSPGU), CMU (MFCMU)
                     accessories= ASU, SCUU, RSU
Interface layer    : three peer control paths to that hardware
                     FLEX  = native GPIB/VISA command set (drives mainframe + SMU + SPGU + CMU + ASU + SCUU)
                     WGFMU = B1530A WGFMU instrument library (separate session; drives ONLY the WGFMU card)
                     EEX   = EasyEXPERT remote control (software application over the same hardware)
```

Key consequence: **WGFMU sits at two different layers at once.** As *hardware* it is a
module inside the mainframe (so it must NOT be a peer of "B1500" on the hardware axis).
As an *interface/session* it is a genuine peer of FLEX and EasyEXPERT (separate
open/close, timeout, error queue, channel-ID namespace, and failure mode). The current
scheme's mistake is labeling the **interface axis** with a **hardware-flavored** word
(`b1500`), which makes WGFMU look mis-nested. Fix the label, and the confusion largely
dissolves — but only for A, where the interface axis is the right one (see below).

### Why A and B diverge

- **A atoms** are session-scoped: `connect`, `identify`, `read_error`, `wait_opc`,
  `fetch_result`, catalog/selection. The same *action* repeats across interfaces
  (identify exists for FLEX and EEX; read-error exists for all three; wait_opc for FLEX
  and EEX). The discriminator that matters is **which session/interface** — confirmed by
  `a_flow_arbitration.md`, which refuses to merge discovery across FLEX/WGFMU/EEX
  because they are "separate transports with separate failure modes." → A wants a
  **WHERE/interface-first** secondary axis.

- **B atoms** are overwhelmingly one interface (FLEX / mainframe): 29 of 42 are
  `b1500`, and `b_flow_arbitration.md` clusters them by **operation** (emergency-zero,
  reset-init, preflight-gate, self-test/cal, ASU/SCUU path, CMU correction), not by
  interface. The stated requirement is that B names make **risk obvious**. Grouping 29
  atoms under one `b1500` bucket hides risk; grouping by operation surfaces it. → B
  wants a **WHAT/operation-and-risk-first** secondary axis.

This asymmetry is the central finding: **A and B should use different schemes.**

---

## Candidate Taxonomies Compared

### Candidate 1 — Current `subsystem` taxonomy (`b1500` / `wgfmu` / `easyexpert`)

- **Naming pattern:** `{A|B}_atom_{b1500|wgfmu|easyexpert}_{action}`
- **Examples:** `A_atom_b1500_connect`, `A_atom_wgfmu_get_status`,
  `B_atom_b1500_zero_all_outputs`, `B_atom_easyexpert_set_standby`
- **Pros:**
  - Already shipped; zero churn.
  - Good for A: cleanly separates the three independent sessions.
  - Maps 1:1 to the manuals, so provenance is easy.
- **Cons:**
  - Middle token mixes product/module/application levels (not peers).
  - Makes WGFMU look like a peer of the mainframe on a hardware reading.
  - Bad for B: 29 atoms collapse into `b1500`; risk class is invisible until you read
    the whole name (`..._zero_all_outputs` vs `..._self_test` vs `..._set_smu_filter`).
  - Future SMU/SPGU/CMU have no home: they are FLEX too, so they would either pollute
    `b1500` or get incorrectly promoted to peer "subsystems."
- **Future scalability:** Poor on the hardware reading. Every new module tempts a new
  bogus top-level "subsystem," repeating the WGFMU mistake.

### Candidate 2 — Two-level interface taxonomy (`hardware` / `software`)

- **Naming pattern:** `{A|B}_atom_{hardware|software}_{action}`
- **Examples:** `A_atom_hardware_connect`, `A_atom_software_list_workspaces`,
  `B_atom_hardware_zero_all_outputs`, `B_atom_software_set_standby`
- **Pros:**
  - Correctly states that EasyEXPERT is software/remote, not hardware.
  - Only two buckets — trivially scannable.
- **Cons:**
  - Far too coarse. FLEX and WGFMU are both "hardware," yet they are *separate
    sessions* with separate failure modes; lumping them destroys the one distinction A
    most needs.
  - Does nothing for B risk legibility (`hardware` covers reset, zero, enable, route,
    calibrate — every risk class).
  - The hardware/software split is genuinely useful, but as a **boolean property/tag**,
    not as the primary name axis.
- **Future scalability:** Two buckets never grow, so they never help; everything piles
  into `hardware`.

### Candidate 3 — Hardware-layer taxonomy (`instrument` / `module` / `accessory` / `buffer` / `remote` ...)

- **Naming pattern:** `{A|B}_atom_{instrument|module|accessory|remote|...}_{action}`
- **Examples:** `B_atom_instrument_reset`, `B_atom_module_wgfmu_connect`,
  `B_atom_accessory_asu_path`, `B_atom_remote_standby`
- **Pros:**
  - Directly fixes the user's complaint: WGFMU lands under `module` (alongside
    SMU/SPGU/CMU), the mainframe under `instrument`, ASU/SCUU under `accessory`,
    EasyEXPERT under `remote`. WGFMU is no longer a peer of the mainframe.
  - Excellent forward story for hardware growth (new module → `module_<x>`).
- **Cons:**
  - The example list is **internally inconsistent**: `instrument`/`module`/`accessory`/
    `remote` are hardware layers, but `buffer` is an *operation* category. Mixing axes
    in one token is the very disease we are curing.
  - Not risk-forward for B: `module`/`accessory` do not tell you whether an op
    energizes the DUT. `B_atom_module_wgfmu_connect` (energizes) and
    `B_atom_module_wgfmu_self_test` (safe) sit together.
  - For A it is awkward: most A atoms are `instrument`-level session ops; `module` and
    `accessory` are nearly empty in A.
- **Future scalability:** Great for hardware, but only if the `buffer`-style operation
  leak is removed. Best used as a **target token inside the action**, not the primary
  axis.

### Candidate 4 — Operation-semantics taxonomy

- **Naming pattern:** `{A|B}_atom_{semantic_category}_{action}`
  - A example set: `session`, `identity`, `status`, `error`, `buffer`, `catalog`,
    `context`, `result`
  - B example set: `safety`, `reset`, `calibration`, `channel`, `path`, `correction`,
    `abort`
- **Examples:** `A_atom_status_read_status_byte`, `A_atom_catalog_list_app_tests`,
  `B_atom_safety_preflight`, `B_atom_channel_enable`, `B_atom_path_asu`
- **Pros:**
  - **Excellent for B:** risk class is the first thing you read; the dangerous family
    (`channel`/output) clusters; `safety` gates cluster.
  - Interface-independent, so it survives module growth without new top-level buckets.
- **Cons (for A specifically):**
  - **Hurts A.** It scatters one session across many buckets: `A_atom_session_connect`,
    `A_atom_identity_identify`, `A_atom_status_get_status`, `A_atom_error_read_error`
    no longer sit together, yet they are *one* discovery flow on *one* transport. You
    lose the "which session does this belong to?" grouping that A flows depend on.
  - Pure operation-semantics also hides the transport you must use (FLEX vs WGFMU lib
    vs EEX), which for A is first-class information.
- **Future scalability:** Very good (categories are stable; new modules ride in the
  action token). The catch is it is the *right* answer for B and the *wrong* primary
  axis for A.

### Candidate 5 — Hybrid (RECOMMENDED): interface-first for A, operation/risk-first for B

- **Naming pattern:**
  - A: `A_atom_{interface}_{action}` with `interface in {flex, wgfmu, eex}`
  - B: `B_atom_{risk_class}_{action}` with `risk_class in {safety, output, lifecycle,
    integrity, routing, correction}`, and the **hardware target** (`smu`, `asu`,
    `scuu`, `cmu`, `wgfmu`, `eex`, future `spgu`) carried as a token inside `{action}`.
- **Examples:** `A_atom_flex_connect`, `A_atom_wgfmu_get_status`,
  `A_atom_eex_list_workspaces`; `B_atom_output_zero_all`,
  `B_atom_safety_preflight`, `B_atom_routing_asu_path`,
  `B_atom_correction_cmu_phase_comp`, `B_atom_lifecycle_wgfmu_abort`.
- **Pros:**
  - Uses the correct axis for each class: A keeps per-session grouping (and relabels
    the axis honestly as *interface*, so WGFMU's peerhood is defensible, not accidental);
    B leads with risk, so the safety reading is immediate.
  - The hardware-layer concern (Candidate 3) is satisfied **inside B's action token**
    (`wgfmu`, `asu`, `scuu`, `cmu`, `spgu`) without making it the primary axis or
    leaking operation words into it.
  - The hardware/software concern (Candidate 2) is satisfied because A's `flex`/`wgfmu`
    are hardware interfaces and `eex` is the software interface — and it can also be a
    boolean tag in metadata.
  - Future modules and externals slot in cleanly (see each section below).
- **Cons:**
  - A and B no longer share one scheme (a teaching/consistency cost — but it is honest:
    they are different problems).
  - B no longer shows the transport in the primary token; it is recoverable from the
    target token in the action and from B-flow context.
  - Real churn, especially for B (all 42 B atoms change). Mitigated by an alias map.
- **Future scalability:** Best overall. A grows by adding interfaces (`prober`,
  `hspice`); B grows by adding target tokens, and only adds a new *category* if a
  genuinely new risk class appears.

---

## Recommended Taxonomy

### A atoms — interface-first (relabeled honestly)

#### Naming pattern

```
A_atom_{interface}_{action}
interface in { flex, wgfmu, eex }     # the control SESSION/transport, not the hardware module
```

- `flex` — native FLEX/SCPI over GPIB/VISA to the mainframe. Replaces `b1500`. It is
  the **command-interface** level, so it correctly owns future SMU/SPGU/CMU/ASU/SCUU
  A-atoms too (they are all FLEX).
- `wgfmu` — B1530A WGFMU instrument library session. **Unchanged.**
- `eex` — EasyEXPERT remote control. Replaces `easyexpert` (shorter for scanning;
  `easyexpert` is acceptable if clarity is preferred over alignment).

#### Subcategories (and why these are peers)

The axis is **interface/session**, not hardware. On this axis the three are true peers:
each has its own open/close lifecycle, identity, error queue, timeout, and failure mode.
This is the strong argument the brief asked for re WGFMU: *as a session/library, the
WGFMU interface is a sibling of FLEX, even though the WGFMU card is a child of the
mainframe in hardware.* The current `b1500` label wrongly invited a hardware reading;
`flex` removes that, because "FLEX vs WGFMU-lib vs EEX-remote" is unambiguously an
interface comparison.

#### Examples mapping existing atoms (rename rule is mechanical: only the middle token changes)

FLEX (`b1500` -> `flex`), all 18:

| Current | Proposed |
|---|---|
| `A_atom_b1500_connect` | `A_atom_flex_connect` |
| `A_atom_b1500_disconnect` | `A_atom_flex_disconnect` |
| `A_atom_b1500_identify` | `A_atom_flex_identify` |
| `A_atom_b1500_list_modules` | `A_atom_flex_list_modules` |
| `A_atom_b1500_get_status` | `A_atom_flex_get_status` |
| `A_atom_b1500_query_settings` | `A_atom_flex_query_settings` |
| `A_atom_b1500_read_error_queue` | `A_atom_flex_read_error_queue` |
| `A_atom_b1500_lookup_error` | `A_atom_flex_lookup_error` |
| `A_atom_b1500_read_status_byte` | `A_atom_flex_read_status_byte` |
| `A_atom_b1500_wait_opc` | `A_atom_flex_wait_opc` |
| `A_atom_b1500_set_data_format` | `A_atom_flex_set_data_format` |
| `A_atom_b1500_configure_timestamp` | `A_atom_flex_configure_timestamp` |
| `A_atom_b1500_reset_timestamp` | `A_atom_flex_reset_timestamp` |
| `A_atom_b1500_read_timestamp` | `A_atom_flex_read_timestamp` |
| `A_atom_b1500_clear_output_buffer` | `A_atom_flex_clear_output_buffer` |
| `A_atom_b1500_query_buffer_count` | `A_atom_flex_query_buffer_count` |
| `A_atom_b1500_read_output_buffer` | `A_atom_flex_read_output_buffer` |
| `A_atom_b1500_configure_srq` | `A_atom_flex_configure_srq` |

WGFMU (unchanged), examples: `A_atom_wgfmu_open_session`, `A_atom_wgfmu_get_status`,
`A_atom_wgfmu_get_channel_ids`, `A_atom_wgfmu_read_error_summary`,
`A_atom_wgfmu_export_ascii`, `A_atom_wgfmu_is_event_completed` (all 16 keep their names).

EEX (`easyexpert` -> `eex`), examples (all 26 follow the rule):

| Current | Proposed |
|---|---|
| `A_atom_easyexpert_identify` | `A_atom_eex_identify` |
| `A_atom_easyexpert_read_system_error` | `A_atom_eex_read_system_error` |
| `A_atom_easyexpert_list_workspaces` | `A_atom_eex_list_workspaces` |
| `A_atom_easyexpert_open_workspace` | `A_atom_eex_open_workspace` |
| `A_atom_easyexpert_get_workspace_state` | `A_atom_eex_get_workspace_state` |
| `A_atom_easyexpert_set_result_format` | `A_atom_eex_set_result_format` |
| `A_atom_easyexpert_fetch_result` | `A_atom_eex_fetch_result` |
| `A_atom_easyexpert_list_app_tests` | `A_atom_eex_list_app_tests` |
| `A_atom_easyexpert_select_app_test` | `A_atom_eex_select_app_test` |
| `A_atom_easyexpert_select_preset_setup` | `A_atom_eex_select_preset_setup` |

(That is 18 + 10 shown, well over 20, plus the 16 WGFMU names that do not change.)

#### Optional refinement for A (only if module-specific A atoms multiply)

If FLEX later accumulates many module-scoped reads (e.g., CMU/SPGU status), add the
target as a token in the action, keeping the interface primary:
`A_atom_flex_cmu_get_status`, `A_atom_flex_spgu_get_status`. The interface stays the
sort key; the module is a qualifier. Not needed today.

#### Why this is better for A

- Keeps each session's toolkit contiguous in a sorted MCP list (matches how A flows are
  built: one discovery flow per transport).
- Names the axis what it is (interface), so WGFMU's sibling status is *correct and
  explained*, not accidental.
- `flex` future-proofs SMU/SPGU/CMU (all native-command) without new top-level buckets.
- Minimal churn: only the middle token changes; every action suffix is preserved.

### B atoms — operation/risk-first

#### Naming pattern

```
B_atom_{risk_class}_{action}
risk_class in { safety, output, lifecycle, integrity, routing, correction }
{action} carries a hardware/interface target token when the target is not the generic
mainframe: smu, asu, scuu, cmu, qscv, wgfmu, eex  (future: spgu)
```

#### Subcategories (with explicit risk reading)

| Class | Meaning | Energizes DUT? | Read it as |
|---|---|---|---|
| `safety` | Gates and safe-state verification; never drives output | No | "do this first / proves safe" |
| `output` | DUT-facing output state: enable, disable, zero, recover, channel connect, standby | **Yes (highest direct risk)** | "this changes what the DUT sees" |
| `lifecycle` | Known-state and execution control: reset, initialize, abort | Indirect (drops/halts) | "recovery / wipes state" |
| `integrity` | Self-test, self-cal, diagnostics, cal/warning policy | Internal (may cycle ranges) | "instrument health / slow" |
| `routing` | Signal path + analog conditioning: ASU/SCUU path, SMU filter/SSR/ADC-zero | Indirect (changes connection) | "changes the signal path" |
| `correction` | Measurement calibration that needs a fixture condition: CMU open/short/load, phase comp, QSCV offset, EEX zero-cancel | Stimulus during cal | "requires a known fixture state" |

This set is MECE over the current 42 B atoms (verified below) and leads with the
information a safety reviewer wants. In a sorted tool list, all `B_atom_output_*` (the
genuinely dangerous family) sit together, and all `B_atom_safety_*` gates sit together.

#### Examples mapping all 42 existing B atoms

`safety` (3):

| Current | Proposed |
|---|---|
| `B_atom_b1500_check_interlock` | `B_atom_safety_check_interlock` |
| `B_atom_b1500_preflight` | `B_atom_safety_preflight` |
| `B_atom_b1500_confirm_zero` | `B_atom_safety_confirm_zero` |

`output` (8):

| Current | Proposed |
|---|---|
| `B_atom_b1500_enable_channels` | `B_atom_output_enable_channels` |
| `B_atom_b1500_disable_channels` | `B_atom_output_disable_channels` |
| `B_atom_b1500_zero_outputs` | `B_atom_output_zero_outputs` |
| `B_atom_b1500_zero_all_outputs` | `B_atom_output_zero_all` |
| `B_atom_b1500_recover_zeroed` | `B_atom_output_recover_zeroed` |
| `B_atom_wgfmu_connect` | `B_atom_output_wgfmu_connect` |
| `B_atom_wgfmu_disconnect` | `B_atom_output_wgfmu_disconnect` |
| `B_atom_easyexpert_set_standby` | `B_atom_output_eex_standby` |

`lifecycle` (6):

| Current | Proposed |
|---|---|
| `B_atom_b1500_reset` | `B_atom_lifecycle_reset` |
| `B_atom_b1500_initialize` | `B_atom_lifecycle_initialize` |
| `B_atom_b1500_abort` | `B_atom_lifecycle_abort` |
| `B_atom_wgfmu_initialize` | `B_atom_lifecycle_wgfmu_initialize` |
| `B_atom_wgfmu_abort` | `B_atom_lifecycle_wgfmu_abort` |
| `B_atom_easyexpert_abort_measurement` | `B_atom_lifecycle_eex_abort` |

`integrity` (7):

| Current | Proposed |
|---|---|
| `B_atom_b1500_self_test` | `B_atom_integrity_self_test` |
| `B_atom_b1500_self_calibration` | `B_atom_integrity_self_cal` |
| `B_atom_b1500_diagnostics` | `B_atom_integrity_diagnostics` |
| `B_atom_b1500_set_auto_calibration` | `B_atom_integrity_set_auto_cal` |
| `B_atom_wgfmu_self_test` | `B_atom_integrity_wgfmu_self_test` |
| `B_atom_wgfmu_self_calibration` | `B_atom_integrity_wgfmu_self_cal` |
| `B_atom_wgfmu_treat_warnings_as_errors` | `B_atom_integrity_wgfmu_warnings_as_errors` |

`routing` (8):

| Current | Proposed |
|---|---|
| `B_atom_b1500_set_smu_filter` | `B_atom_routing_smu_filter` |
| `B_atom_b1500_set_series_resistor` | `B_atom_routing_smu_series_resistor` |
| `B_atom_b1500_set_adc_zero` | `B_atom_routing_smu_adc_zero` |
| `B_atom_b1500_set_asu_path` | `B_atom_routing_asu_path` |
| `B_atom_b1500_set_asu_1pa_range` | `B_atom_routing_asu_1pa_range` |
| `B_atom_b1500_set_asu_indicator` | `B_atom_routing_asu_indicator` |
| `B_atom_b1500_set_scuu_path` | `B_atom_routing_scuu_path` |
| `B_atom_b1500_set_scuu_indicator` | `B_atom_routing_scuu_indicator` |

`correction` (10):

| Current | Proposed |
|---|---|
| `B_atom_b1500_set_cmu_correction` | `B_atom_correction_cmu_state` |
| `B_atom_b1500_measure_cmu_correction` | `B_atom_correction_cmu_measure` |
| `B_atom_b1500_set_cmu_phase_mode` | `B_atom_correction_cmu_phase_mode` |
| `B_atom_b1500_perform_cmu_phase_comp` | `B_atom_correction_cmu_phase_comp` |
| `B_atom_b1500_clear_cmu_correction` | `B_atom_correction_cmu_clear` |
| `B_atom_b1500_qscv_offset_cancel` | `B_atom_correction_qscv_offset` |
| `B_atom_easyexpert_zero_cancel_on` | `B_atom_correction_eex_zero_cancel_on` |
| `B_atom_easyexpert_zero_cancel_off` | `B_atom_correction_eex_zero_cancel_off` |
| `B_atom_easyexpert_measure_zero_cancel` | `B_atom_correction_eex_zero_cancel_measure` |
| `B_atom_easyexpert_query_zero_cancel_state` | `B_atom_correction_eex_zero_cancel_state` |

Counts: 3 + 8 + 6 + 7 + 8 + 10 = 42 (all B atoms mapped, MECE).

#### Why this is better for B

- Leads with risk: the brief's hard requirement. `output` (the only family that drives
  the DUT) is unmistakable and contiguous; `safety` gates are contiguous.
- Collapses the misleading single `b1500` bucket (29 atoms) into meaningful risk
  families.
- Puts the hardware target where it belongs for B — as a qualifier (`smu`, `asu`,
  `scuu`, `cmu`, `wgfmu`, `eex`) — so WGFMU is **not** a peer of the mainframe; it is a
  target inside a risk class. EasyEXPERT likewise appears only as a software target
  token (`eex`), never as hardware.
- Refines the brief's example B list sensibly: `reset`+`abort` -> `lifecycle`
  (both are known-state/execution control); `channel` -> `output` (the true risk unit
  is DUT-facing output, which also covers zero/disable/WGFMU-connect/standby);
  `calibration` -> `integrity` (instrument health/policy) kept distinct from
  `correction` (fixture-dependent measurement cal); `path` -> `routing` (path +
  analog conditioning).

#### Forward-compatibility (modules and externals)

- SMU / SPGU / CMU (future modules, FLEX-driven): A -> stays under `flex` (optionally
  with a module token); B -> new target tokens inside existing risk classes, e.g.
  `B_atom_output_spgu_enable`, `B_atom_routing_spgu_path`. Only add a new B *category*
  if a genuinely new risk type appears (none expected for SMU/SPGU/CMU).
- WGFMU: A interface `wgfmu` (peer session); B target token `wgfmu` inside risk classes.
- Prober (external hardware, future): A -> new interface `prober`; B -> target token
  `prober` (e.g. `B_atom_output_prober_contact` if it ever drives contact) or its own
  risk class if motion safety needs one.
- HSPICE (simulator, future): A -> new interface `hspice` (it is a separate session/
  back end). Most HSPICE work is C-class anyway.
- C atoms: reuse A's interface-first axis where C work is session-shaped (e.g.
  `C_atom_flex_*`, `C_atom_wgfmu_*`), or a measurement-semantics axis if that proves
  clearer; decide when C is designed. The A/B split above does not constrain C badly
  either way.

---

## Migration Impact

This is a proposal; nothing is renamed. If adopted, the impact is:

### What changes

- **A (60 atoms): low churn — middle token only.**
  - `A_atom_b1500_*` -> `A_atom_flex_*` (18).
  - `A_atom_easyexpert_*` -> `A_atom_eex_*` (26). Optional; keep `easyexpert` to avoid
    even this.
  - `A_atom_wgfmu_*` -> unchanged (16).
  - Every action suffix is preserved, so the diff is a pure token substitution.

- **B (42 atoms): high churn — middle token changes for all, and a few action tokens
  are normalized** (e.g. `zero_all_outputs` -> `output_zero_all`, `set_cmu_correction`
  -> `correction_cmu_state`). Every B name changes.

- **Downstream references update with the atoms:** `instrument-interaction-tools.md`
  tables, the three flow-arbitration docs (`a_/b_/ab_flow_arbitration.md`), and the
  `capabilities` resource enumeration. The flow docs reference atoms by exact name, so
  they must move in the same change.

### What should stay stable

- The `A_atom` / `B_atom` / `C_atom` **class prefixes** — these are the intentionally
  stable MCP surface (per `instrument-interaction-tools.md`).
- The `_atom_` infix and the underscore-delimited shape.
- The **action verbs/nouns** (the human-meaningful tail) wherever possible — keep
  `connect`, `identify`, `preflight`, `self_test`, `enable_channels` recognizable.
- The A/B classification *decisions* themselves (what is A vs B) — only the **subcategory
  axis** is being redesigned, not the class boundaries.

### Suggested rollout (if/when approved)

1. Land A first (cheap, low-risk token swap; optionally keep `easyexpert`).
2. Land B as one atomic change with its flow/doc updates.
3. If external consumers exist, ship a one-release **alias map** (old name -> new name)
   rather than silent breakage; the reference doc already discourages permanent legacy
   aliases, so treat aliases as temporary and time-boxed.

---

## Open Questions

1. **`flex` vs keeping `b1500`.** `flex` is the scientifically correct interface label
   and absorbs future FLEX modules; `b1500` is familiar but invites the hardware-nesting
   confusion. Keep `b1500` only if familiarity outweighs correctness (then document that
   it means "the FLEX interface," not "the mainframe hardware").
2. **`eex` vs `easyexpert`.** `eex` aligns/scans better; `easyexpert` is
   self-explanatory. Pick one convention and use it identically in A's interface token
   and B's target token.
3. **Is B's loss of transport-in-primary-token acceptable?** Today yes (target token +
   B-flow context recover it). If a future client must filter B atoms by transport,
   reconsider a `B_atom_{risk}_{interface}_{action}` three-token form (longer names).
4. **`output` direction split.** Should `output` distinguish energize (enable, recover,
   wgfmu_connect) from de-energize (zero, disable, disconnect, standby)? A risk-direction
   split (`arm` vs `safe`) is maximally safety-forward but fuzzier at the edges
   (`recover_zeroed` re-applies settings; path switches are ambiguous). Current proposal
   keeps one `output` class and expresses direction via a metadata risk tag instead.
5. **`integrity` policy items.** `set_auto_calibration` and
   `treat_warnings_as_errors` are policy, not health checks. Fold into `integrity` (as
   proposed) or split a tiny `policy` class? Two atoms do not justify a class yet.
6. **Standby placement.** `eex_standby` is filed under `output` (it changes bias/output
   state). If the team reads standby as execution-state, it could move to `lifecycle`.
7. **Risk metadata vs name.** Should each B atom also carry a structured
   `risk_tier` / `energizes_dut` field in its response (independent of the name) so
   tooling can gate without string-parsing names? Recommended regardless of the naming
   outcome.
8. **C-atom axis.** Decide later whether C uses interface-first (like A) or a
   measurement-semantics axis; this proposal intentionally leaves C open.
