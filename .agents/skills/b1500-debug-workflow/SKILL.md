---
name: b1500-debug-workflow
description: Diagnose abnormal B1500A semiconductor measurements by checking physical connection, instrument state, correction, data status codes, and DUT failure modes. Use when data is noisy, impossible, compliance-limited, drifting, or inconsistent.
---

# B1500 Debug Workflow

## Triage Order

1. Physical path: probe contact, pad alignment, cables, shielding, ground, Guard, Kelvin, ASU/SCUU/selector state.
2. Instrument state: module inventory, channel mapping, ranges, compliance, ADC integration, calibration, correction, error queue.
3. Measurement data: status codes, noise, discontinuities, drift, leakage, compliance hits, unstable voltage.
4. DUT reality: damaged device, process defect, high leakage, hysteresis, temperature or humidity sensitivity.

## Output

Return a concise diagnosis with:

- Observed symptom.
- Most likely causes.
- Checks the user can do physically.
- Safe software checks.
- Whether the measurement result should be trusted.
