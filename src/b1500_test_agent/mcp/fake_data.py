"""Shared fake data returned by the fake B1500A MCP tools."""

# Module inventory mirrors the user's real station: 2x B1511B MPSMU,
# 2x B1517A HRSMU, 1x B1530A WGFMU, 1x B1525A HV-SPGU, 1x B1520A MFCMU.
# Channel numbering follows the simplified fake convention: 1-10 primary slot
# channels, 11-20 secondary channels for two-subchannel modules.
_FAKE_MODULES = [
    {"slot": 1, "type": "MPSMU", "model": "B1511B", "channels": [1], "priority": "P0"},
    {"slot": 2, "type": "MPSMU", "model": "B1511B", "channels": [2], "priority": "P0"},
    {"slot": 3, "type": "HRSMU", "model": "B1517A", "channels": [3], "priority": "P0"},
    {"slot": 4, "type": "HRSMU", "model": "B1517A", "channels": [4], "priority": "P0"},
    {"slot": 5, "type": "WGFMU", "model": "B1530A", "channels": [5, 15], "priority": "P1"},
    {"slot": 6, "type": "HVSPGU", "model": "B1525A", "channels": [6, 16], "priority": "P1"},
    {"slot": 7, "type": "MFCMU", "model": "B1520A", "channels": [7], "priority": "P2"},
]

# Practical (measured) operating limits for the real station. These are the
# safe envelopes the agent should respect; they are usually tighter than the
# absolute module specifications. Exposed by atoms as schema/caution hints only.
_SYSTEM_LIMITS = {
    "smu": {
        "external_max_voltage_v": 42.0,
        "max_current_a": 0.1,
        "note": "B1511B/B1517A practical envelope; module spec is +/-100 V but station is +/-42 V.",
    },
    "mfcmu": {
        "min_frequency_hz": 1_000.0,
        "max_frequency_hz": 1_000_000.0,
        "max_dc_bias_internal_v": 25.0,
        "min_ac_level_v": 0.010,
        "max_ac_level_v": 0.250,
        "note": "B1520A usable range 1 kHz-1 MHz, internal DC bias +/-25 V; >25 V needs SMU/SCUU path.",
    },
    "spgu": {
        "max_voltage_v": 40.0,
        "channels": 2,
        "note": "B1525A HV-SPGU measured +/-40 V across two pulse channels.",
    },
    "wgfmu": {
        "max_pulse_voltage_v": 10.0,
        "min_pulse_width_no_measure_s": 1e-8,
        "min_pulse_width_with_measure_s": 1e-7,
        "note": "B1530A measured +/-10 V; 10 ns min pulse (no measure), 100 ns min pulse (with measure).",
    },
}

# Per-model SMU current measurement range hints (Table 4-3). HRSMU reaches far
# lower current ranges than MPSMU, which matters for leakage/low-current work.
_SMU_RANGE_HINTS = {
    "MPSMU": {
        "min_current_range": "1 nA (range 11)",
        "max_current_range": "100 mA (range 19)",
        "voltage_ranges": ["0.5 V", "2 V", "5 V", "20 V", "40 V", "100 V"],
        "note": "B1511B medium-power SMU; lowest current range is 1 nA.",
    },
    "HRSMU": {
        "min_current_range": "10 pA (range 9); 1 pA (range 8) with ASU",
        "max_current_range": "100 mA (range 19)",
        "voltage_ranges": ["0.5 V", "2 V", "5 V", "20 V", "40 V", "100 V"],
        "note": "B1517A high-resolution SMU; preferred for leakage/sub-nA work, especially with ASU.",
    },
}

_EASYEXPERT_APPS = [
    "Id-Vg",
    "Id-Vd",
    "Vth gmMax",
    "C-V Sweep",
    "QSCV",
    "NandFlash IV-Write-IV",
]
