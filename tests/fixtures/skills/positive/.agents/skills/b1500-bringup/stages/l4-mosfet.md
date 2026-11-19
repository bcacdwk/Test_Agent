---
stage: L4
title: MOSFET DC set against EasyEXPERT (fixture)
recipes: [mosfet.idvg]
checks:
  - {id: vth, recipe: mosfet.idvg, quantity: vth, method: vth_linear_extrapolation, unit: V, reference: EasyEXPERT file, tolerance: {absolute: 0.01}, text: '+-10 mV'}
version: 1
---

# L4 — MOSFET DC set (fixture)

## 1. Preconditions

- L3 signed off; `uv run b1500 status` clean.

## 2. Physical steps (human)

1. Land the known-good MOSFET; confirm in chat.

## 3. Agent steps

1. `mosfet.idvg` with pin map `mosfet-4t`, DUT profile `nmos-generic`: `needs_confirmation (first_hw_run)`.

## 4. Expected values

| check | expected | tolerance | source |
|---|---|---|---|
| `vth` | EasyEXPERT value | ±10 mV | EasyEXPERT file |

## 5. Abort criteria

- Gate current near its compliance → `safe_shutdown`, report, wait for the human.

## 6. Record

One draft record for `mosfet.idvg` from `H...` runs.
