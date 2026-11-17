# Driver layer (`driver/`): safety-critical

Owns FLEX builders (`commands.py`), `B1500Driver` (`b1500.py`), `OutputGuard` (`guard.py`), the ASCII parser,
discovery, instrument errors and the module spec table. Spec: blueprint §2.3 and §3; deck layer L3.

- FLEX mnemonics appear as string literals only in `commands.py` (lint test). Builders are pure: syntax and domain
  checks only, never policy. Recipes, kinds, service and adapters never assemble FLEX text.
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
- Tests run on the simulator (`SimTransport`; pyvisa-sim only for `VisaTransport` conformance), never hardware.
- Legacy v0.2 atoms → driver methods: `references/driver-map/` (`flex-driver-map.yaml` is generated). When you
  add or re-attribute a command, update the tables in `scripts/build_driver_map.py` and regenerate; never
  hand-edit the YAML.
