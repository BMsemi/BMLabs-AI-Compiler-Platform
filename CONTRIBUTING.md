# Contributing

Start with the README and current pipeline boundaries. Keep proposed capabilities distinct from executed evidence. Preserve upstream BM repositories; use adapters or reviewable private-copy patches rather than rewriting them without need.

## Development

Use Python 3.12, install the locked web requirements, configure a local `.env`, and run migrations. Use a `codex/`-prefixed branch for agent-authored changes. Do not reuse production data or hardware configuration for routine tests.

Run `python manage.py test tests`, `python manage.py check` and `python manage.py makemigrations --check --dry-run`. Regenerate/validate `schema.yaml` after API changes. Tests must fail on missing completion evidence and must distinguish mocked fixtures from external-tool/hardware results.

## Compiler changes

Document input/target schemas, numerical semantics, tool versions and execution scope. Add negative tests for invalid inputs, incompatible targets and failed processes. Preserve partial artifacts on failure. Do not label a synthesis result as simulation, a simulation as hardware execution, or a generated fabric configuration as a compatible board image without evidence.

## Pull requests

Explain the concrete behavior change, why it is needed, validation performed and remaining limitations. Include reproducible commands where practical. Do not attach credentials, raw board sessions, personal data, private model files or unreviewed logs to a public issue/PR.

## Licensing

This publication does not select a project-wide open-source license. Obtain appropriate permission before redistributing or contributing third-party material. Retain upstream notices and document dependency provenance. BM branding is not granted a separate trademark license.
