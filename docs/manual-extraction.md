# Manual Extraction Plan

The repository should not rely on raw PDFs during normal agent workflows. Manuals need to be converted into structured references, validated against real hardware, and cited by topic.

## Current State

- `references/manuals/` holds per-manual indexes and `structured/` extracts (FLEX command summary and parameters, error codes, initial settings, WGFMU API and timing, EasyEXPERT catalogs). They are inputs for the v1 re-architecture and are not modified by it.
- Driver work reads exact command syntax from `B1500A Programming Guide.pdf` (in the repository's parent folder or `$B1500_MANUALS_DIR`) and records the PDF page in each builder docstring and in the generated `references/driver-map/flex-driver-map.yaml` (via `scripts/build_driver_map.py`).
- Parser and simulator tests use golden fixtures in `tests/fixtures/flex/`, transcribed from manual examples with a page citation.
- `scripts/extract_manuals.py` is still a placeholder.

## Priority Sources

- `B1500A Programming Guide.pdf`: FLEX command syntax, measurement modes, data formats, status codes, errors, and examples.
- `B1530A WGFMU.pdf`: waveform generation, fast measurement, trigger behavior, and reliability workflows.
- `Keysight 16440A SMUPulse Generator Selector.pdf`: SMU/SPGU switching topology, connection limits, and program-read recipes.
- `Keysight B1500A Configuration and Connection Guide.pdf`: cabling, Guard, Kelvin, ASU, SCUU, grounding, and interlock guidance.
- `B1500A User Guide.pdf`: safety, operation, calibration, and maintenance.

## Extraction Targets

- FLEX quick reference by capability.
- Module capability tables (input to `driver/modules.py` and rule R-LIM-01).
- Measurement transaction templates.
- Safety and interlock rules.
- Correction and calibration workflows.
- Preconditions for the reserved (`not_implemented`) WGFMU and SPGU recipes.
- 16440A selector connection profiles.

## Validation

Each extracted command or recipe should track:

- Source manual and section (PDF page and printed page).
- Implementation status.
- Simulator and golden-fixture test status.
- Real instrument validation status (M4 validation record).
- Known caveats.
