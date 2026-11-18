# Driver layer (`driver/`): safety-critical

Owns FLEX builders (`flex/`: `core.py`, `smu.py`, one module per family), `B1500Driver` (`b1500.py`, a facade over
the `ops/` mixins `CoreOps` and `SmuOps` on `DriverBase`), `OutputGuard` (`guard.py`), the ASCII parser, discovery,
instrument errors and the module spec table. Spec: blueprint v2 §2.5 (v1 §2.3, §3); deck layer L3.

- FLEX mnemonics appear as string literals only in `flex/` (lint test); `flex/__init__.py` re-exports every builder
  (`flex.dv(...)`). Builders are pure: syntax and domain checks only, never policy; `flex/` imports only `models`.
  Recipes, kinds, service and adapters never assemble FLEX text. Only `b1500.py` imports `ops/`; everyone else uses
  `B1500Driver`. A new family adds `flex/<family>.py` + `ops/<family>.py` (see `docs/architecture.md`).
- `*RST` (`flex.RST`) is sent only by `B1500Driver.reset`, which only kind `system` calls (lint test).
- Every source operation (`DV`, `WV`, later `DI`/`WI`) passes `OutputGuard.check` before anything is written:
  channel in the plan allowlist, |level| and compliance within the compiled envelope, compliance non-zero; `CN`
  needs allowlisted channels too. Source methods refuse without a guard; a violation raises `EnvelopeViolation`
  and sends nothing. No bypass flag. Module limits and range codes live in `modules.py` (rule R-LIM-01).
- Imports: `transport` and `models` only. Never `pyvisa` (only `transport/visa.py`), never `fastmcp`.
- Send `AB` and `*RST` alone, never combined with other commands. Between `XE` and its read send only `AB`
  (`DZ`/`CL` abort first). Keep query reads separate from measurement-buffer reads.
- ASCII `FMT 1`/`FMT 5` only until a binary format is implemented and tested.
- Cite the manual: each builder docstring names the Programming Guide PDF page (and printed page) of its syntax.
  Read syntax from `B1500A Programming Guide.pdf` (repo parent folder or `$B1500_MANUALS_DIR`) or
  `references/manuals/structured/`; never modify `references/manuals/**`.
- Parser changes need golden fixtures in `tests/fixtures/flex/*.txt` (header convention and loader:
  `tests/unit/flex_fixtures.py`), each citing PDF pages. The simulator formatter shares no code with `parser.py`.
- Return structured errors (`InstrumentError`, status byte, error codes), never opaque strings or silent retries.
  Cleanup (`AB` → `DZ` → `CL` → verify) is orchestrated by `session/transaction.py`; the driver supplies the steps.
- Tests run on the simulator: `SimTransport`, or the real `VisaTransport` over `tests/visa_loop/`; never hardware.
- Legacy v0.2 atoms → driver methods: `references/driver-map/` (`flex-driver-map.yaml` is generated). When you
  add or re-attribute a command, update the tables in `scripts/build_driver_map.py` and regenerate; never
  hand-edit the YAML.
