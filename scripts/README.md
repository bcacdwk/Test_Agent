# Scripts

Utility scripts should be deterministic helpers that Codex can run or inspect.

- `build_driver_map.py`: builds and checks (`--check`) `references/driver-map/flex-driver-map.yaml` from git tag
  `archive/v0.2-fake-mcp` (WP0.4).
- `hooks/b1500_guard.py`: Claude Code `PreToolUse` guard hook wired in `.claude/settings.json` (WP1.9); standard
  library only, reads the hook JSON on stdin, exits 2 to block (blueprint 5.4).

Manual extraction is the CLI command `b1500 manual build` (`docs/manuals.md`), not a script.

Planned scripts:

- Plot generation.
- Dataset export.
- Validation and lint helpers.
