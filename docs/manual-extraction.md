# Manual Extraction Plan

The repository should not rely on raw PDFs during normal agent workflows. Manuals need to be converted into structured references, validated against real hardware, and cited by topic.

## Priority Sources

- `B1500A Programming Guide.pdf`: FLEX command syntax, measurement modes, data formats, status codes, errors, and examples.
- `B1530A WGFMU.pdf`: waveform generation, fast measurement, trigger behavior, and reliability workflows.
- `Keysight 16440A SMUPulse Generator Selector.pdf`: SMU/SPGU switching topology, connection limits, and program-read recipes.
- `Keysight B1500A Configuration and Connection Guide.pdf`: cabling, Guard, Kelvin, ASU, SCUU, grounding, and interlock guidance.
- `B1500A User Guide.pdf`: safety, operation, calibration, and maintenance.

## Extraction Targets

- FLEX quick reference by capability.
- Module capability tables.
- Measurement transaction templates.
- Safety and interlock rules.
- Correction and calibration workflows.
- WGFMU and SPGU recipe stubs.
- 16440A selector connection profiles.

## Validation

Each extracted command or recipe should track:

- Source manual and section.
- Implementation status.
- Mock test status.
- Real instrument validation status.
- Known caveats.
