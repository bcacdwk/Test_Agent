# References

References are structured knowledge used by Codex skills, MCP resources, deterministic tools, and reports.

Keep this directory split between:

- Instrument knowledge: manuals, FLEX notes, modules, switching accessories.
- Device knowledge: expected behavior, common measurements.
- Physics and analysis notes.
- Debug records from real experiments: skill `b1500-debug` (`.agents/skills/b1500-debug/`: runbooks, cases).

Recipes (validated measurement flows and their envelopes) live in `recipes/` at the repository root, checked by
`b1500 dev recipe-check`. Station profile, cable topology, correction records, pin maps, DUT envelopes and the
safety policy are runtime configuration, not references: committed examples live in `config/` (`*.example.yaml`),
the live copies in the gitignored `config/local/` (see `b1500 config check`).

Do not put private credentials, unreleased sample identifiers, or unsafe station details in committed files.
