# Public source release

This initial source release contains the web application, compiler adapters, tests, supported model examples, deployment scaffolding and curated documentation.

## Included

- Implemented deterministic compiler/build workflows and their explicit limitations.
- A detailed README and separate A1–A4 agent architecture proposal.
- Hardware contract distinctions and pinned SKY130 source/tool revisions.
- Incomplete, safe local-profile templates with physical programming disabled.
- CI for application checks; external hardware is not available in CI.

## Excluded

Credentials, `.env`, generated Django secrets, databases, uploaded project data, authenticated sessions, raw execution evidence, board/network inspection output, recordings, local caches, actual hardware profiles and generated fabric packages remain local. No existing deployed data is deleted by publication preparation.

Historical local compiler/hardware qualifications are summarized in the README. Their raw operational artifacts are not part of the public repository. A fresh checkout must rerun dependency probes and appropriate tests; it does not inherit the original machine's qualification status.

## Checks

Before publication, inspect the staged file list, run `python scripts/check_publication.py --staged`, run the regression suite from a clean source export, check Django configuration and migration consistency, and validate Markdown file links. No project-wide license is selected automatically.

After upload, verify that the destination repository is public and that its file/tree content matches the reviewed local source. Do not force-push over unrelated remote commits.

### Release verification: 13 November 2026

The staged source was exported into a separate directory without the live environment file, database, private media or hardware profiles. Checks used the existing Python environment.

| Check | Result |
| --- | --- |
| `python manage.py check` | Exit 0; 4.859 seconds |
| `python manage.py makemigrations --check --dry-run` | Exit 0; 3.859 seconds |
| `python manage.py test tests --verbosity 1` | Exit 0; 132.422 seconds; 109 passed, four skipped |
| Markdown file links | No missing local targets |
| Locked dependency dry-run resolution | Exit 0; no packages installed by this check |
| Staged publication scan | No findings |

Machine-specific command logs remain in the ignored local `.compiler-work/publication/` directory. These checks validate the application release, not a newly executed FPGA or FABulous qualification run.
