# Analysis layer (`analysis/`)

Owns run loading, the run-table contract, quality, extraction, plots and the method registry. Spec: blueprint
§2.10; deck layer L5. Used by `analyze_run` and by agent scripts in `work/`, so it must work without an instrument.

- Never import `session`, `driver`, `transport`, `catalog`, `service` or `adapters` (layering test). Inputs are run
  folders (`load_run`) and `models`.
- **Data contract** (full text: `dataset.py` docstring; the archive writes only through its helpers): `data.csv`
  up to 200,000 rows, else `data.npz` (uncompressed, no pickle) + `preview.csv` (2,000 rows); `load_run` reads both.
  Columns: `step` (strictly increasing), `trust`, value columns `<role>_<V|I|Cp|G|Cs|Rs|D|Z|theta>` (V, A, F, S,
  Ohm, 1, Ohm, rad) each with an optional `<value>_status` letter (MFCMU values always have one), optional `t_s`,
  `cycle`, `segment` (fwd/rev), `phase` (stress read program erase recovery correction), `event`, `range`,
  `<role>_range`, `freq_hz`, `ac_vrms`, `dc_v`; nothing else. v1 tables keep their bytes (golden test).
- Measured vs derived: never modify measured columns. Every derived value is an `ExtractionResult`
  (`derived=True`) with unit, method, `MethodRecord`, fit window, points used/excluded, fit and warnings; `bound`
  marks floor- or compliance-limited values, `classification` a verdict (open/short/in_range, pass/fail).
- Trust (`TrustPolicy`: recipe `quality:` block or `policy.quality`; letters in `driver/parser.py`): `N` ok; `C`/`T`
  limited, excluded from fits; `V X F D G S U` and unknown letters untrusted: extraction refused unless forced (sets
  `forced_on_untrusted`, warns); `V` (incl. `199.999E+99`) never limited. `assess_quality` first; report the counts.
- A refusal or failure is a result (`outcome` `refused`/`failed`, `value=None`, `error`), never an exception;
  exceptions only for unusable calls (unknown run/column/option, declared method → `not_implemented`).
- Definitions live in the module docstrings (shared `common.py`) and match skill `b1500-test` knowledge `06-...`
  (`06b-...`: time series, pulses, `nvm.py`; `05-...`: `stress.py`; `08-...`: `cv*.py`, `qscv.py`, `dit.py`; `07-...`:
  `model.py`, `spice.py`; `10-...`: `noise.py`, `spectrum.py`); change both together. Two-run: option `reference_run`.
- Deterministic algorithms only (language-model text narrates, never computes). Units on every quantity; tables
  are pandas DataFrames. Plot raw data before extraction; semilog axes for currents over decades.
- Run folders are written only by the server (`analyze_run`); ad-hoc results go to `work/<run_id>/` with the
  script path recorded. Register every method in `ANALYSIS_METHODS` (name, function, `families` tags, recipes,
  kinds, `implemented` or `declared`; declared → `not_implemented`). Tests use analytic curves with known truth
  (e.g. Vth error < 5 mV), C/T exclusion and untrusted refusal.
