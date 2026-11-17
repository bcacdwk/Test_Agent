# Migration from v0.2 (fake 379-tool MCP server) to v1

The v0.2 design (282 atom and 97 flow MCP tools returning synthetic data) is preserved by the annotated tag
`archive/v0.2-fake-mcp` (commit `6bc9f3e`); recover any removed file with `git show archive/v0.2-fake-mcp:<path>`.
The plan of record is [`docs/design/blueprint.md`](design/blueprint.md). This file starts with the token baseline
(WP0.3); WP0.6 adds the path-by-path migration table (blueprint §1).

## Baseline

Tool-schema budget of the legacy server, measured once in WP0.3 (2026-11-17) with the blueprint §5.2 counter:

```text
uv run b1500 dev tool-budget --app b1500_test_agent.mcp.server:mcp
```

Method: the FastMCP app is built in-process and its tools are listed through the in-memory client; per tool, the
fields `name, description, inputSchema, outputSchema, annotations` are serialized as compact JSON and counted with
`tiktoken` `o200k_base`; the total is the sum over tools. Environment: fastmcp 4.2.0, tiktoken 0.14.0,
CPython 3.12.7. The legacy server's `instructions` string is not part of the tool schemas and is listed separately.

| Metric | v0.2 legacy (measured) | v1 target (blueprint §5.1–5.2) |
|---|---|---|
| Tools | **379** (282 atoms, 97 flows) | 10 (hard cap 20) |
| Tool-schema tokens, `o200k_base` | **104,691** | target ≤ 3,500; test cap 4,500 |
| Cross-check `ceil(chars / 4)` | 104,902 | — |
| Serialized characters | 419,029 | — |
| Largest tool | 3,678 (`CD_flow_analyze_iv_transfer`) | ≤ 700 per tool |
| Mean / median per tool | 276 / 115 | — |
| Server `instructions` | 1,304 chars (287 tokens) | ≤ 400 chars |

Per family (tools / tokens): A atoms 82 / 7,229 · B atoms 59 / 5,817 · C atoms 99 / 13,032 · D atoms 42 / 34,543 ·
A flows 20 / 2,512 · B flows 16 / 1,794 · C flows 31 / 14,636 · AB flows 19 / 2,978 · D flows 7 / 8,875 ·
CD flows 4 / 13,275.

To reproduce after WP0.5 has removed the legacy code, check out the WP0.3 commit (listed in
[`docs/design/progress.md`](design/progress.md)), where the legacy server and the counter coexist, run `uv sync`
and the command above.

The after-value (10-tool v1 server, same counter, `uv run b1500 dev tool-budget`) is recorded when WP1.8 lands.
