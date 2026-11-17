---
name: b1500-test
description: Test fixture for b1500 dev lint-skills (positive tree), not a real skill. Plans and analyzes simulated MOSFET Id-Vg measurements through one test card.
---

# Fixture entry skill

Pick a card from the [card index](#card-index), read it, then validate its
[example plan](cards/mosfet-idvg.md#4-recipe-and-parameters) before anything runs.

## Card index

| intent | card | recipe | status |
|---|---|---|---|
| Vth, gm, SS, Ion/Ioff | [mosfet-idvg](cards/mosfet-idvg.md) | `mosfet.idvg` | sim_validated |

New cards start from the [template][template]; reserved measurements are listed in
[reserved cards](cards/reserved/README.md).

## Knowledge map

- [Knowledge index](knowledge/README.md)
- [Vth by linear extrapolation](knowledge/06-analysis-extraction.md#vth-linear-extrapolation)
- [Subthreshold swing](./knowledge/06-analysis-extraction.md#subthreshold-swing-ss)
- External links are not checked: [Keysight](https://www.keysight.com/).

Links inside code are not links: `[x](missing.md)` and

```text
[y](also-missing.md)
```

[template]: cards/_TEMPLATE.md
