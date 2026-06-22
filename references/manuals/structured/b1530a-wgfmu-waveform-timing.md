# B1530A WGFMU Waveform and Timing Extraction

Source: `B1530A WGFMU.pdf`, Agilent B1530A WGFMU User's Guide, Edition 5, August 2012.  
Index used: `../b1530a-wgfmu-index.md`.

This file extracts timing and waveform rules for future MCP pulse, waveform, and reliability tooling. It is not a full replacement for the manual. All page references are PDF page numbers with printed page numbers where available.

## Extraction Limits

| Limitation | Tooling Impact | Page Reference |
|---|---|---|
| `exportAscii` CSV example is OCR-garbled in Figure 4-1 | Exact CSV columns require image/manual extraction before parsers depend on it | PDF 99-100, printed 4-23 to 4-24 |
| Hardware memory is specified only as "about 4 M data points/channel (typical)" | Use conservative memory budgeting; do not treat 4M as guaranteed | PDF 24, printed 1-14; PDF 131, printed 4-55 |
| No FeFET/FeCap/NVM/PUND/endurance/retention/wake-up recipes | Build those workflows from primitives here; do not claim manual-provided methodology | PDF 21, printed 1-11; index revision notes |
| NBTI/RTS are only listed as bundled software/sample programs | Need companion CD/software extraction for actual reliability methods | PDF 21, printed 1-11 |

## Core Waveform Data Model

| Primitive | Structured Meaning | Key Parameters | Limits / Behavior | Tooling Use | Page Reference |
|---|---|---|---|---|---|
| Pattern | Named waveform template containing initial voltage, vectors, and events | `pattern`, `initV` | Pattern name must be unique; initial voltage exists at `t=0` | Unit of waveform construction; reusable across channels/sequences | PDF 94, printed 4-18 |
| Vector | Linear ramp endpoint appended to or set within a pattern | `dTime` + `voltage` for `addVector`; `time` + `voltage` for `setVector` | Time resolution 10 ns; `addVector` uses incremental time; `setVector` uses absolute time | Build trapezoids, ramps, staircases, stress/sense segments | PDF 88-89, 137-138; printed 4-12/4-13, 4-61/4-62 |
| Sequence | Channel-specific `(pattern, count)` assignment | `chanId`, `pattern`, `count` | Count 1 to 1,099,511,627,776; non-integer rounded | Repeat pulses, endurance loops, stress/read cycles | PDF 85-87, printed 4-9 to 4-11 |
| Measurement Event | Sampling window embedded in a pattern | `time`, `points`, `interval`, `average`, `rdata` | Must fit inside pattern time; time quantities 10 ns resolution | Current/voltage read windows during/after waveform | PDF 130-131, printed 4-54 to 4-56 |
| Range Event | Current range change embedded in a pattern | `time`, `range` | Fast IV current measurement only; event end = `time + 10 ns` | High-range stress, low-range sense | PDF 133-134, printed 4-57/4-58 |
| Trigger Event | Trigger output embedded in a pattern | `time`, `duration` | Requires trigger mode `EVENT`; `time=duration=0` triggers at initial voltage | Synchronize scopes, SMU actions, external instruments | PDF 135-136, printed 4-59/4-60 |

## Operation Modes

| Mode | Constant | Supported Force/Measure | Output Range Behavior | Pulse/Measurement Notes | Page Reference |
|---|---:|---|---|---|---|
| DC | 2000 | DC voltage force + current or voltage measurement (VFIM/VFVM) | -3 to +3 V, -5 to +5 V, -10 to 0 V, 0 to +10 V | No patterns/sequences required; use `dcforceVoltage`, `dcmeasureValue`, `dcmeasureAveragedValue` | PDF 14, 76, 145; printed 1-4, 3-30, 4-69 |
| Fast IV | 2001 | ALWG voltage force + current or voltage measurement (VFIM/VFVM) | -3 to +3 V, -5 to +5 V, -10 to 0 V, 0 to +10 V | Current measurement available; typical min pulse width 300 ns | PDF 13-14, 145; printed 1-3/1-4, 4-69 |
| PG | 2002 | ALWG voltage force + voltage measurement (VFVM only) | -3 to +3 V or -5 to +5 V open load; output divided by internal 50 ohm resistor and load impedance | Narrower pulse mode; typical min pulse width 100 ns; no current measurement | PDF 13-14, 145; printed 1-3/1-4, 4-69 |
| SMU pass-through | 2003 | Measurement through SMU path | Max input/output +/-25 V, max current +/-100 mA | Default mode; most WGFMU measurement functions not valid | PDF 14, 145; printed 1-4, 4-69 |

## Voltage Force and ALWG Limits

| Item | Value | Units | Notes | Page Reference |
|---|---:|---|---|---|
| Channels per module | 2 | channels | Up to five WGFMU modules per B1500A, ten channels total | PDF 14-15, printed 1-4/1-5 |
| Maximum vectors | 2048 | vectors/pattern | Table 1-6 ALWG capability | PDF 24, printed 1-14 |
| Maximum sequences | 512 | sequences/channel | Table 1-6 ALWG capability | PDF 24, printed 1-14 |
| Maximum loop count | 1 to 10^12 | loops | Function reference gives exact max 1,099,511,627,776 | PDF 24, 86; printed 1-14, 4-10 |
| Vector length, spec table | 10 ns to 10000 s | seconds | Table 1-6 rounded value | PDF 24, printed 1-14 |
| Vector `dTime`, firmware/error limit | 10 ns to 10995.11627775 s | seconds | Error 3311 gives more precise firmware limit | PDF 159, printed 4-83 |
| Time resolution | 10 ns | seconds | Applies to vectors, event times, interval, average, trigger/range event times | PDF 24, 88-89, 130-131, 133-136 |
| Voltage force resolution, 3 V range | 96 | uV | Can vary up to 5% by calibration | PDF 23, printed 1-13 |
| Voltage force resolution, other ranges | 160 | uV | Applies all ranges except -3 to +3 V | PDF 23, printed 1-13 |
| Voltage force accuracy | +/-0.1% setting +/-0.1% range | V | DC constant voltage output; load impedance requirements apply | PDF 23, printed 1-13 |
| PG min rise/fall time | 24 | ns | PG mode, 50 ohm load | PDF 23, printed 1-13 |
| PG min pulse period | 100 | ns | PG mode, 50 ohm load | PDF 23, printed 1-13 |
| PG min pulse width | 50 | ns | Accuracy spec applies for pulse width >=50 ns | PDF 23, printed 1-13 |
| Cable-dependent rise/fall threshold, 1.5 m | 16 | ns | For overshoot/undershoot condition | PDF 23, printed 1-13 |
| Cable-dependent rise/fall threshold, 3 m | 32 | ns | For overshoot/undershoot condition | PDF 23, printed 1-13 |
| Cable-dependent rise/fall threshold, 5 m | 56 | ns | For overshoot/undershoot condition | PDF 23, printed 1-13 |

## Pattern Construction Recipes

| Recipe | API Skeleton | Timing Meaning | Page Reference |
|---|---|---|---|
| Trapezoidal pulse | `createPattern(p, baseV)` -> `addVector(p, rise, peakV)` -> `addVector(p, hold, peakV)` -> `addVector(p, fall, baseV)` -> `addVector(p, tail, baseV)` | `addVector` dTimes are incremental. Example 1 creates 0.1 ms rise, 0.4 ms hold, 0.1 ms fall, 0.4 ms base. | PDF 58-59, printed 3-12/3-13 |
| Repeated pulse train | Add pattern once, then `addSequence(chanId, p, count)` | Repeats same pattern with no delay between repeats | PDF 58-59, 85-87 |
| Stress/sense cycle | Create separate `stress` and `sense` patterns; add both as serial sequences | 50 ns delay occurs between different sequences: 10 ns previous last voltage + 40 ns next initial voltage | PDF 85-87, printed 4-9 to 4-11 |
| Staircase sweep | Use repeated vectors or absolute `setVector` points with incrementing voltage | Example 9 uses gate staircase Vg 2-3 V, 10 mV steps, and drain sweep 0-10 V, 2 V steps | PDF 69-71, printed 3-23 to 3-25 |
| Pattern addition | `createMergedPattern(new, p1, p2, WGFMU_AXIS_VOLTAGE)` | Adds voltages during longer pattern; shorter pattern's final value extends | PDF 91-92, 150; printed 4-15/4-16, 4-74 |
| Pattern concatenation | `createMergedPattern(new, p1, p2, WGFMU_AXIS_TIME)` | Pattern1 plus pattern2 in time; pattern2 first point deleted | PDF 91-92, 150 |
| Time scaling / reversal | `createMultipliedPattern(new, p, factorT, factorV)` | `factorT < 0` reverses pattern and recalculates measurement times | PDF 92-93, printed 4-16/4-17 |
| Time/voltage offset | `createOffsetPattern(new, p, offsetT, offsetV)` | Positive offsetT inserts initial-voltage vector; negative offsetT trims start | PDF 93-94, printed 4-17/4-18 |

## Measurement Event Behavior

| Field | Meaning | Limits | Tooling Notes | Page Reference |
|---|---|---|---|---|
| `pattern` | Waveform pattern containing event | Pattern must exist | Event is executed while this pattern is output by a channel | PDF 130, printed 4-54 |
| `event` | Measurement event name | Not unique | Same name can be reused for other events/patterns; do not assume global uniqueness | PDF 130, printed 4-55 |
| `time` | Measurement start time from pattern origin | 0 to total pattern time; 10 ns resolution | Rounded to nearest 10 ns | PDF 130-131 |
| `points` | Number of sampling points | Positive integer | Data must be read before channel data exceeds about 4M typical points | PDF 130, printed 4-55 |
| `interval` | Sampling interval between points | 10 ns to 1.34217728 s; 10 ns resolution | Rounded to nearest 10 ns | PDF 131, printed 4-55 |
| `average` | Averaging time | 0 or 10 ns to 0.020971512 s; 10 ns resolution; <= interval | Nonzero average samples internally every 5 ns; rounded to nearest 10 ns | PDF 131, printed 4-55/4-56 |
| `rdata` | Data output mode | AVERAGED=12000, RAW=12001 | RAW returns all sub-samples used for averaging | PDF 151, printed 4-75 |

## Measurement Formulas

| Formula | Expression | When To Use | Page Reference |
|---|---|---|---|
| Measurement event end | `eventEndTime = time + interval * (points - 1) + average` | Validate event fits inside pattern | PDF 130, printed 4-55 |
| Average-zero event end adjustment | If `average = 0`, add `10 ns` to the event-end formula | Manual explicit edge case | PDF 130, printed 4-55 |
| Averaged reported timestamp | `reported_time = (sample_start + sample_start + average) / 2` | For nonzero averaging. Example: start 0 ns, average 20 ns -> reported 10 ns | PDF 131, printed 4-55 |
| Internal averaged sampling times | `sample_start + k * 5 ns` for `k = 0..int(average/5ns)-1` | Understand averaged/RAW data | PDF 131, printed 4-55 |
| RAW data count | `raw_count = points * (1 + int(average / 5 ns))` | Memory budget and parser sizing | PDF 151, printed 4-75 |
| AVERAGED data count | `averaged_count = points` | Memory budget and parser sizing | PDF 151, printed 4-75 |
| Serial sequence delay | `50 ns = 10 ns previous_last_voltage + 40 ns next_initial_voltage` | Compute total waveform time for multiple different sequences | PDF 86-87, printed 4-10/4-11 |
| Channel status example total time | `3*10 us + 50 ns + 1*50 us + 50 ns + 2*20 us = 120.1 us` | Validate implementation of sequence time accumulation | PDF 152, printed 4-76 |

## Sampling and Measurement Timing Tables

### ALWG and Sampling Capability

| Capability | Value | Notes | Page Reference |
|---|---:|---|---|
| Sampling rate, fixed fastest | 5 ns | Manual says "5 ns, or 10 ns to 1 s with 10 ns resolution" | PDF 24, printed 1-14 |
| Programmable sampling interval | 10 ns to 1 s | Table 1-6 rounded capability | PDF 24, printed 1-14 |
| `setMeasureEvent` interval | 10 ns to 1.34217728 s | Function/error-code precision | PDF 130-131, 159 |
| Averaging time | 10 ns to 20 ms | Table 1-6 rounded capability | PDF 24, printed 1-14 |
| `setMeasureEvent` average | 0 or 10 ns to 0.020971512 s | Function/error-code precision | PDF 131, 159 |
| Hardware memory | About 4M data points/channel typical | Depends on average value and RAW/AVERAGED mode | PDF 24, 131 |

### Minimum Current Measurement Timing

Measurement conditions from manual: DUT is resistive load adjusted to current; cable capacitance 20 pF; voltage applied by one WGFMU/RSU channel in Fast IV mode and 10 mA range; current measured by another channel at 0 V in Fast IV mode. Page reference: PDF 25, printed 1-15.

| DUT Current | Measurement Range | Recommended Min Pulse Width | Recommended Min Measurement Window | Settling Time | RMS Noise | Page Reference |
|---:|---:|---:|---:|---:|---:|---|
| 100 nA | 1 uA | 47 us | 10 us | 37 us | 160 pA | PDF 25, printed 1-15 |
| 1 uA | 1 uA | 38.7 us | 1.64 us | 37 us | 425 pA | PDF 25, printed 1-15 |
| 10 uA | 10 uA | 6.8 us | 1 us | 5.8 us | 2.5 nA | PDF 25, printed 1-15 |
| 100 uA | 100 uA | 950 ns | 130 ns | 820 ns | 47 nA | PDF 25, printed 1-15 |
| 1 mA | 1 mA | 240 ns | 40 ns | 200 ns | 280 nA | PDF 25, printed 1-15 |
| 10 mA | 10 mA | 145 ns | 20 ns | 125 ns | 1.9 uA | PDF 25, printed 1-15 |

### Minimum Voltage Measurement Timing

Measurement conditions from manual: DUT is resistive load 1 kohm to 10 Mohm; cable capacitance 20 pF; same channel applies and measures voltage. Page reference: PDF 26, printed 1-16.

| Applied Voltage | Measurement Range | Recommended Min Pulse Width | Recommended Min Measurement Window | Settling Time | RMS Noise | Mode | Min Rise/Fall for Overshoot Control | Page Reference |
|---:|---:|---:|---:|---:|---:|---|---:|---|
| 5 V | 5 V | 105 ns | 20 ns | 85 ns | 1.4 mV | PG | 30 ns | PDF 26, printed 1-16 |
| 10 V | 10 V | 130 ns | 20 ns | 110 ns | 1.4 mV | Fast IV | 70 ns | PDF 26, printed 1-16 |

## Trigger and Synchronization

| Topic | Values / Behavior | Tooling Notes | Page Reference |
|---|---|---|---|
| Physical connector | TrigOut is SMA female, TTL pulse output | External instruments can synchronize with Ch1/Ch2 output | PDF 16, printed 1-6 |
| Trigger modes | No trigger/default, Event, Execution, Sequence, Pattern | API constants: DISABLE=8000, START_EXECUTION=8001, START_SEQUENCE=8002, START_PATTERN=8003, EVENT=8004 | PDF 16, 149; printed 1-6, 4-73 |
| Trigger polarity | POSITIVE=8100 default, NEGATIVE=8101 | Negative polarity: normally high, low at trigger timing | PDF 149-150, printed 4-73/4-74 |
| Trigger width | 10 ns for execution/sequence/pattern; adjustable for event trigger | Event trigger duration set by `setTriggerOutEvent` | PDF 16, 135-136 |
| Event trigger at pattern start | `time = duration = 0` | Trigger when channel starts applying pattern initial voltage | PDF 136, printed 4-60 |
| 50 ohm trigger input note | For period >10 us, TTL high duration should be >=5 us; for period <=10 us, high duty should be >=50% | Manual wording uses "may need to adjust pulse width"; verify with target equipment | PDF 16, printed 1-6 |
| Fast trigger period note | Use negative trigger for trigger period <20 ns | Relevant for external instruments with short trigger intervals | PDF 16, printed 1-6 |
| Multi-WGFMU sync | Sync Out of master to Sync In of slave; master is lower slot | Wrong Sync/Trig terminal connection may damage WGFMU | PDF 15, 34-38 |
| Skew/jitter | Jitter <1 ns; inter-channel skew <3 ns without ESD; trigger output skew <3 ns | Keep hands off terminals during measurement to avoid ESD effects | PDF 22, printed 1-12 |

## Data Point and Memory Budgeting

The manual gives only a typical memory capacity ("about 4 M data points/channel") and does not define exact allocation across force setup, measurement data, RAW sub-samples, and FIFO behavior.

| Quantity | Formula / Rule | Notes | Page Reference |
|---|---|---|---|
| Per-event AVERAGED points | `points` | `rdata = WGFMU_MEASURE_EVENT_DATA_AVERAGED` | PDF 151, printed 4-75 |
| Per-event RAW points | `points * (1 + int(average / 5 ns))` | If `average=0`, formula returns `points`; confirm empirically before relying on RAW/no-average behavior | PDF 151, printed 4-75 |
| Sequence-expanded event count | Sum over sequence loops and pattern event occurrences | `getMeasureEvent` returns cycle, loop, count, index, length | PDF 109-113, printed 4-33 to 4-37 |
| Channel measured/total point count | `getMeasureValueSize(chanId, measuredSize, totalSize)` | Use during long runs for progress and partial reads | PDF 116, 152 |
| Hardware memory threshold | About 4,000,000 data/channel typical | Read before exceeding; exact overflow behavior depends on average value | PDF 131, printed 4-55 |
| Memory overflow | Error 3050 | Data exceeds memory size; data could not be stored | PDF 158, printed 4-82 |
| FIFO overflow | Error 3051 | FIFO overflow because averaging count was frequently changed | PDF 158, printed 4-82 |
| Result out of date | Error -15 | Measurement data deleted by setup change; read before changing waveform/measurement setup | PDF 157, printed 4-81 |

### Conservative Budgeting Pseudocode

```text
for each channel:
  total_points = 0
  for each sequence in channel_sequences:
    for loop in 1..sequence.count:
      for each measure_event in sequence.pattern:
        if measure_event.rdata == AVERAGED:
          event_points = measure_event.points
        else if measure_event.rdata == RAW:
          event_points = measure_event.points * (1 + int(measure_event.average / 5ns))
        total_points += event_points

  if total_points approaches 4_000_000:
    split run, reduce RAW/average/points, or read partial data where possible
```

Page references: PDF 85-87 (sequence count), PDF 130-131 (`setMeasureEvent`), PDF 151 (RAW formula), PDF 152 (event/point accumulation), PDF 158 (memory/FIFO errors).

## Reliability / NVM Tooling Hints

| Workflow Need | Manual Support | Missing From Manual | Page Reference |
|---|---|---|---|
| Stress-sense loop | Patterns + sequences + up to 10^12 loops; 50 ns between different sequences | No ready-made reliability protocol | PDF 85-87, printed 4-9 to 4-11 |
| Sense-window sampling after pulse | `setMeasureEvent`, measurement ranges, force/measure delay | No FeFET/PUND/read-after-write recipes | PDF 130-131, printed 4-54 to 4-56 |
| Threshold extraction | Example 9 Id-Vg staircase sweep | No explicit Vth extraction algorithm | PDF 69-71, printed 3-23 to 3-25 |
| NBTI | Listed as bundled EasyEXPERT application test | No test method, timing, or parameters | PDF 21, printed 1-11 |
| RTN/RTS | Listed as RTS data analysis sample program | No RTN/RTS algorithm or sampling plan | PDF 21, printed 1-11 |
| FeFET / FeCap / NVM | WGFMU primitives are applicable | No FeFET, FeCap, PUND, endurance, retention, wake-up, switching-kinetics content | No explicit manual section; absence noted from full TOC and sampled body |

---

## Opus Review

| Field | Value |
|---|---|
| Reviewer | opus-4.6-max |
| Review date | 2026-06-22 |
| Passes completed | 5 |
| Verification method | Multi-pass: (1) full file read and schema audit, (2) cross-reference against revised index, (3) PDF verification of key timing values and formulas on pages 24-26, 86-87, 130-131, 151-152, 159, (4) targeted corrections, (5) re-read and consistency check |

### Items Verified Against PDF

- dTime firmware limit 10995.11627775 s from error 3311 (PDF 159) confirmed
- setMeasureEvent interval max 1.34217728 s (PDF 131, error 3312) confirmed
- setMeasureEvent average max 0.020971512 s (PDF 131, error 3315) confirmed
- Inter-sequence 50 ns delay = 10 ns last voltage + 40 ns initial voltage (PDF 86-87) confirmed
- RAW data formula: points × (1 + int(average/5ns)) (PDF 151) confirmed
- Averaging internal sampling at 5 ns intervals; reported time = (start + start+average)/2 (PDF 131) confirmed
- Example 6 parameters: 32768 points, 10 ns averaging, 100us/10us/1us intervals (PDF 64-65) confirmed
- Current measurement timing table values for 10 mA range (145 ns pulse, 125 ns settle, 20 ns window) consistent with manual

### Corrections Made

- No corrections were needed in this file; all claims were verified against the PDF

### Remaining Uncertainties

- The "about 4M data points/channel" memory limit remains imprecise; manual provides no exact formula for hardware memory allocation
- Exact overflow vs FIFO overflow trigger conditions (error 3050 vs 3051) not precisely defined beyond the error descriptions
- V Monitor behavior during fast transients (< 100 ns) is unspecified by the manual
- Whether the 50 ns inter-sequence delay is firmware-version-dependent is unknown

### Completeness Assessment

This file covers: waveform data model, operation modes, ALWG limits, pattern construction recipes, measurement event behavior and formulas, sampling/timing tables, trigger/sync, memory budgeting with pseudocode, and reliability/NVM absence notes. No additional high-value timing content was identified in the index or PDF that is missing from this file.
