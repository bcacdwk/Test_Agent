# MCP Tool Reference Index

Detailed fake B1500A MCP tool references are split by family:

- [A atoms](a-atoms.md)
- [B atoms](b-atoms.md)
- [C atoms](c-atoms.md)
- [D atoms](d-atoms.md) (hardware-free analysis placeholder stubs)
- [A flows](a-flows.md)
- [B flows](b-flows.md)
- [C flows](c-flows.md)
- [AB flows](ab-flows.md)
- [D flows](d-flows.md) (D-atom-only analysis compositions over held C evidence)
- [CD flows](cd-flows.md) (expect -> one C flow -> its D flow -> archive; fake-only)

The parent overview remains at [`../instrument-interaction-tools.md`](../instrument-interaction-tools.md).

All listed tools are fake discovery surfaces. They return `fake: true` and `hardware_touched: false`; they must not be treated as real hardware control.
