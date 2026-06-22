# Contributing

This project is intended to become open-source, but the first versions should be conservative.

## Contribution Priorities

- Safety policy and station metadata schemas.
- Manual extraction into structured references.
- Mock-instrument tests.
- Deterministic analysis helpers.
- Small, validated measurement recipes.

## Requirements

- Do not add private lab configuration unless it is explicitly safe to share.
- Do not add unverified real-hardware control paths without tests and safety review.
- Keep code comments and docstrings in English.
- Keep recipes auditable and reproducible.

## Commit Hygiene

Use concise commit messages that describe why the change matters. Avoid committing raw measurement outputs unless they are small, anonymized fixtures.
