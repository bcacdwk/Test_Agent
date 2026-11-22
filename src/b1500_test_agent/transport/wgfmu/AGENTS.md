# WGFMU library link (`transport/wgfmu/`): safety-critical

The second instrument link next to FLEX (blueprint v2 §2.4, decision 6): the `WgfmuApi` protocol, `wgfmu.h`
constants, limits and `WgfmuError` (`api.py`), the audit wrapper (`audit.py`, `ev: wgfmu_call`) and the ctypes
binding `WgfmuDll` (`dll.py`). The simulator implements the same protocol in `transport/sim/wgfmu.py`.

- Lint ownership: `ctypes` and every DLL loader only in `dll.py` (`tests/unit/test_lint_ctypes.py`); `WGFMU_*`
  symbols only in this package and `transport/sim/wgfmu.py` (`tests/unit/test_lint_wgfmu_symbols.py`). Code
  elsewhere uses `WgfmuApi` and its Python literals.
- Bind exactly `api.C_FUNCTIONS`. `C_SIGNATURES` in `dll.py` is generated from the API extract and the manual
  corpus: `uv run python scripts/gen_wgfmu_signatures.py` (`--check` in `tests/wgfmu_abi/test_signatures.py`).
  Never hand-edit the block; a new protocol method adds its C functions to `C_FUNCTIONS`, then regenerate.
- Load only after the probe says loadable: x64 DLL, 64-bit Python, every export. x86 = "install library >=
  A.03.00"; no 32-bit bridge. `locate()`/`probe()` read the file in pure Python, never raise, never load.
- Never load a real `wgfmu.dll` in tests, on any OS: inject `loader=` (the fake ABI `tests/wgfmu_abi/fake_lib.py`)
  and `platform=`; on Windows replace `ctypes.WinDLL`. visa-loop gets the binding from `LoopBus.wgfmu_library`.
- Strings are ASCII `c_char_p`, arrays numpy float64 buffers, outputs `byref`; readback at most 100,000 values per
  `WGFMU_getMeasureValues` call. Every function returns `int`.
- rc < 0 -> `WgfmuError` with the library's error string (kept for `errors()`; firmware code parsed from a
  `WGFMU_FW_ERROR` string); an argument C cannot take -> `ArgumentRefused` before the library, same code.
- The library opens its own VISA session: release the FLEX exclusive lock (transaction WGFMU phase, pre-execute
  channel read) or close the FLEX link (probe session check) first (ATV-14, ATV-16); close the library session on
  every path. The transaction's WGFMU phase and cleanup step 3 belong to `session/` (WP10.3).
- Hardware facts stay `TODO(verify)` until bring-up L0/L8: error-string format, version resource form, firmware
  codes, load from `System32` (ATV-15).
