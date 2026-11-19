"""Harness acceptance (blueprint 8.2; v2 runner WP6.6): scenario schema and selection, isolated runner, harness
transcripts with token usage, graders, report.

- ``scenario.py``: the scenario YAML schema (``tests/acceptance/scenarios/``, probes in ``tests/acceptance/probes/``)
- ``selection.py``: which scenarios a run launches (ids, ``--all``, ``--tag``, ``--affected``, pending scenarios)
- ``specs.py`` / ``graders.py``: grader specifications and implementations (``extraction.py``: the extraction grader
  and its simulator truths; ``bringup_graders.py``: S17; ``module_graders.py``: the v2 module scenarios)
- ``transcripts.py``: Codex ``exec --json`` and Claude Code ``stream-json`` parsed into one event model
- ``evidence.py``: session folder layout, ``session.json`` and the evidence graders read
- ``harnesses.py``: headless launch commands (never a bypass mode), per-turn MCP config, clean environment
- ``approver.py``: the runner's answer to Claude Code permission prompts (plays the human)
- ``runner.py``: isolation (temporary ``B1500_CONFIG_DIR``/``B1500_DATA_DIR``), seeds, snapshots, turns, grading
- ``report.py``: ``docs/acceptance/<date>-<harness>-<version>.md`` (verdicts, usage)
- ``cli.py``: ``b1500 dev acceptance run|grade|report|list``

How to run: ``docs/acceptance/README.md``.
"""
