# Scripts

Utility scripts should be deterministic helpers that Codex can run or inspect.

- `build_driver_map.py`: builds and checks (`--check`) `references/driver-map/flex-driver-map.yaml` from git tag
  `archive/v0.2-fake-mcp` (WP0.4): the coverage ledger, every legacy atom, flow and command mapped or out of scope
  with a reason; `--check` fails on an open entry and prints `... 0 unmapped (open)` (every family closed since
  WP11.2). `b1500 dev coverage` turns its counts into `docs/coverage.md`.
- `gen_wgfmu_signatures.py`: generates and checks (`--check`) `C_SIGNATURES`, the C prototypes of the WGFMU DLL
  binding in `src/b1500_test_agent/transport/wgfmu/dll.py`, from the API extract
  `references/manuals/structured/b1530a-wgfmu-api-reference.yaml` and the manual corpus (WP10.2).
- `hooks/b1500_guard.py`: Claude Code `PreToolUse` guard hook wired in `.claude/settings.json` (WP1.9); standard
  library only, reads the hook JSON on stdin, exits 2 to block (blueprint 5.4).

Manual extraction is the CLI command `b1500 manual build` (`docs/manuals.md`), not a script.
