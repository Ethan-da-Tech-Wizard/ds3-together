# Files 1 of 1 — Wyld Together

[All pages](../FILE_GUIDE.md) · [Project guide](../PROJECT_GUIDE.md)

| File | Role and useful details |
| --- | --- |
| [.gitattributes](../../.gitattributes) | Sets Git text/binary handling and repository-specific attributes. |
| [.gitignore](../../.gitignore) | Defines local data, credentials, dependencies, and generated outputs that Git should leave untracked. |
| [LICENSE](../../LICENSE) | Preserved license, copyright, or attribution terms; read the full text before reusing the covered component. |
| [PROJECT_NOTES.md](../../PROJECT_NOTES.md) | Preserved detailed setup, usage, architecture, and development notes from the earlier README. |
| [README.md](../../README.md) | Project overview, current status, entry points, setup navigation, and documentation links. |
| [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) | Preserved license, copyright, or attribution terms; read the full text before reusing the covered component. |
| [docs/DEPENDENCIES.csv](../../docs/DEPENDENCIES.csv) | Machine-readable inventory of declared and locked dependencies, versions, reported licenses, and evidence URLs. |
| [docs/FILE_GUIDE.md](../../docs/FILE_GUIDE.md) | Index of the complete tracked-file guide, with one entry for every file and links to the paginated descriptions. |
| [docs/LICENSE_REVIEW.md](../../docs/LICENSE_REVIEW.md) | Original-code license, preserved component notices, dependency-license evidence, and unresolved distribution questions. |
| [docs/PROJECT_GUIDE.md](../../docs/PROJECT_GUIDE.md) | Maintainer orientation: purpose, important entry points, source layout, commands, and project-specific boundaries. |
| [docs/file-guide/files-001.md](../../docs/file-guide/files-001.md) | One page of the tracked-file catalog; links each listed path to its role and source-derived details. |
| [licenses/ds3os-MIT.txt](../../licenses/ds3os-MIT.txt) | Reference notes for ds3os MIT: Copyright 2021 Tim Leonard Permission is hereby granted, free of charge, to any person obtaining a copy of. |
| [patches/ds3os-linux-development.patch](../../patches/ds3os-linux-development.patch) | Source patch for ds3os linux development; apply only to the documented upstream revision. |
| [tests/test_session.py](../../tests/test_session.py) | Automated checks for session. Defines `SessionTests`. |
| [tools/build_upstream.py](../../tools/build_upstream.py) | Build the pinned ds3os native development server, bound to localhost. Defines `run`, `main`. |
| [tools/smoke_upstream.py](../../tools/smoke_upstream.py) | Check a localhost ds3os build, admin authentication, and graceful shutdown. Defines `http`, `main`. |
| [upstream.lock.json](../../upstream.lock.json) | Structured upstream.lock data; top-level fields: `repository`, `commit`, `license`, `game_build`, `game_version`, `patch_sha256`. |
| [wyld_together/__init__.py](../../wyld_together/__init__.py) | Wyld Together: experimental DS3 party persistence core. |
| [wyld_together/__main__.py](../../wyld_together/__main__.py) | Run a local event simulation; this does not connect to a running game. Defines `main`. |
| [wyld_together/session.py](../../wyld_together/session.py) | Durable party policy. This module does not inject into or control DS3. Defines `Rejected`, `identifier`, `SessionStore`. |
