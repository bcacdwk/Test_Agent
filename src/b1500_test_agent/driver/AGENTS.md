# Driver layer (`driver/`): safety-critical

Owns FLEX builders (`flex/`: one module per family), `B1500Driver` (`b1500.py`, a facade over the `ops/` mixins on
`DriverBase`: core, smu, cmu, spgu, switch), `WgfmuDriver` (`wgfmu.py`, guarded, over `WgfmuApi`), `OutputGuard`,
the ASCII parser (+ `cmu_data.py`), discovery, errors and the module spec table. Spec: blueprint v2 §2.5; layer L3.

- FLEX mnemonics appear as string literals only in `flex/` (lint test); `flex/__init__.py` re-exports every builder
  (`flex.dv(...)`). Builders are pure: syntax and domain checks only, never policy; `flex/` imports only `models`.
  Recipes, kinds, service and adapters never assemble FLEX text. Only `b1500.py` imports `ops/`; everyone else uses
  `B1500Driver`. A new family adds `flex/<family>.py` + `ops/<family>.py` (see `docs/architecture.md`).
- `*RST` (`flex.RST`) is sent only by `B1500Driver.reset`, which only kind `system` calls (lint test).
- Every source operation passes the guard before anything is written: `check` (SMU), `check_pulse` (SPGU, SMU
  pulse; open-load level with `SER`), `check_ac` (MFCMU), `check_route` (switches; pass the station's switches),
  `check_waveform` + `check_sequence` (WGFMU: whole program before its first library call; RSU connect via
  `check_route`); `CN` needs allowlisted channels. No guard → refused; a violation raises `EnvelopeViolation` and
  sends nothing; no bypass. Module specs and range codes: `modules.py` (R-LIM-01 ...).
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
  Cleanup (`AB` → `DZ` → `CL` → verify) is orchestrated by `session/cleanup.py`; the driver supplies the steps.
- Tests run on the simulator: `SimTransport`, or the real `VisaTransport` over `tests/visa_loop/`; never hardware.
- Legacy v0.2 atoms → driver methods: `references/driver-map/` (generated `flex-driver-map.yaml`). A new or
  re-attributed command: update the tables in `scripts/build_driver_map.py`, regenerate; never hand-edit the YAML.
