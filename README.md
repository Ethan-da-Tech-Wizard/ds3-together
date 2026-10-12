# Wyld Together

A persistent co-op party-state simulation with reconnect handling and a pinned ds3os development build.

**Status:** Stage 1 development foundation  
**Built with:** Python, SQLite, C/C++ upstream tools

[Project guide](docs/PROJECT_GUIDE.md) · [Every file explained](docs/FILE_GUIDE.md) · [Licenses and dependencies](docs/LICENSE_REVIEW.md)

## Start here

- [wyld_together/session.py](wyld_together/session.py) — Durable party policy. This module does not inject into or control DS3. Defines `Rejected`, `identifier`, `SessionStore`.
- [tests/test_session.py](tests/test_session.py) — Automated checks for session. Defines `SessionTests`.
- [upstream.lock.json](upstream.lock.json) — Structured upstream.lock data; top-level fields: `repository`, `commit`, `license`, `game_build`, `game_version`, `patch_sha256`.

The following commands are taken from this project’s source/configuration. Install its prerequisites first.

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m wyld_together
```

[Detailed setup, usage, and development notes](PROJECT_NOTES.md) preserve the previous project documentation.

## Repository layout

| Path | Role |
| --- | --- |
| [docs/](docs/) | Project documentation, decisions, and reference material (5 tracked entries). |
| [licenses/](licenses/) | Third-party license texts and attribution (1 tracked entries). |
| [patches/](patches/) | Project-specific patches components (1 tracked entries). |
| [tests/](tests/) | Automated checks and test fixtures (1 tracked entries). |
| [tools/](tools/) | Developer utilities and supporting automation (2 tracked entries). |
| [wyld_together/](wyld_together/) | Project-specific wyld together components (3 tracked entries). |

## Scope and current limits

This currently simulates party policy; it does not connect to the game or implement a playable seamless co-op mod. Preserve the upstream ds3os MIT notice.

## License

Original project code retains **MIT** terms in [LICENSE](LICENSE). Third-party libraries, media, data, models, and tools retain their own terms. See the [license review](docs/LICENSE_REVIEW.md) and [dependency inventory](docs/DEPENDENCIES.csv).
