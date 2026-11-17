"""M3 harness acceptance (blueprint 8.2): scenario schema, isolated runner, harness transcripts, graders, report.

- ``scenario.py``: the scenario YAML schema (``tests/acceptance/scenarios/``, probes in ``tests/acceptance/probes/``)
- ``specs.py`` / ``graders.py``: grader specifications and implementations
- ``transcripts.py``: Codex ``exec --json`` and Claude Code ``stream-json`` parsed into one event model
- ``evidence.py``: session folder layout, ``session.json`` and the evidence graders read
- ``harnesses.py``: headless launch commands (never a bypass mode), per-turn MCP config, clean environment
- ``approver.py``: the runner's answer to Claude Code permission prompts (plays the human)
- ``runner.py``: isolation (temporary ``B1500_CONFIG_DIR``/``B1500_DATA_DIR``), seeds, snapshots, turns, grading
- ``report.py``: ``docs/acceptance/<date>-<harness>-<version>.md``
- ``cli.py``: ``b1500 dev acceptance run|grade|report|list``

How to run: ``docs/acceptance/README.md``.
"""
