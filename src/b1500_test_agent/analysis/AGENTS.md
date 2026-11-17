# Analysis layer (`analysis/`)

Owns run loading, quality classification, parameter extraction, plots and the method registry. Spec: blueprint
§2.8; deck layer L5. Used by the `analyze_run` tool and by agent scripts in `work/`, so it must work without an
instrument.

- Never import `session`, `driver`, `transport`, `catalog`, `service` or `adapters` (layering test). Inputs are run
  folders (`load_run`) and `models`. Status letters arrive in the run table's `<role>_<qty>_status` columns (their
  meanings are documented in `driver/parser.py`).
- Measured vs derived: never modify measured columns. Every derived value is an `ExtractionResult`
  (`derived=True`) with unit, method, `MethodRecord`, fit window, points used and excluded, fit and warnings.
- Status-code trust policy (`TrustPolicy` from the recipe `quality:` block or `policy.quality`): `N` ok; `C`/`T`
  limited, excluded from fits; `V X F D G S U` untrusted, so extraction is refused unless forced, which sets
  `forced_on_untrusted` and a warning. `V` (incl. `199.999E+99`) is never limited; unknown letters are untrusted.
- Run `assess_quality` before any fit and report status-code counts with every result.
- Definitions (Vth methods, SS, gm, Ion/Ioff, memory window) must match skill `b1500-test` knowledge file
  `06-analysis-extraction.md`; change both together.
- Deterministic algorithms only; language-model text may narrate results, never compute them.
- Units on every quantity. Tables are pandas DataFrames.
- Plot raw data before extraction; use semilog axes for currents spanning decades.
- Run folders are written only by the server (`analyze_run`); ad-hoc results go to `work/<run_id>/` with the
  script path recorded.
- Register every method in `ANALYSIS_METHODS` (name, function, applicable recipes, `implemented` or `declared`);
  a declared-only method returns `not_implemented`.
- Tests use analytic curves with known truth (for example Vth error below 5 mV), C/T exclusion and untrusted
  refusal.
