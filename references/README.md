# References

Source material for developers and for the agent's knowledge files. Nothing here is auto-loaded by a harness.

| Folder | Content | Used by |
|---|---|---|
| `manuals/` | `catalog.yaml` (the 16 indexed Keysight PDFs; the PDFs live outside the repository), `synonyms.yaml`, the committed page corpus `corpus/` (built by `b1500 manual build`), index files and `manuals/structured/`: command, parameter, error-code, initial-setting, WGFMU and EasyEXPERT extracts with PDF page references | `b1500 manual search\|page\|toc`, the citation lint, driver and simulator code, knowledge files (cited by path); indexes and `structured/` are never modified, see `docs/manuals.md` |
| `driver-map/` | `flex-driver-map.yaml` (every v0.2 atom and manual command mapped to a driver method) and the frozen v0.2 tool catalogs | developers working on FLEX code only |

Where the rest lives:

- Agent-facing domain knowledge (device physics, B1500A instrument, probe station and wiring, ferroelectric and
  oxide devices, reliability, analysis and extraction, compact models and SPICE export) is in the skill:
  `.agents/skills/b1500-test/knowledge/` (index `knowledge/README.md`). The former
  `references/{instruments,physics,hspice}/` notes and the measurement-mode stub were folded into these knowledge
  files and removed; history: `git show archive/v0.2-fake-mcp:references/`.
- Debug know-how and case records from real experiments: skill `b1500-debug` (`.agents/skills/b1500-debug/`:
  runbooks, cases).
- Recipes (validated measurement flows and their envelopes): `recipes/`, checked by `b1500 dev recipe-check`.
- Station profile, cable topology, correction records, pin maps, DUT envelopes and the safety policy are runtime
  configuration, not references: committed examples live in `config/` (`*.example.yaml`), the live copies in the
  gitignored `config/local/` (see `b1500 config check`).

Do not put private credentials, unreleased sample identifiers, or unsafe station details in committed files.
