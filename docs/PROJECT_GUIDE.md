# Wyld Together

A persistent co-op party-state simulation with reconnect handling and a pinned ds3os development build.

**Status:** Stage 1 development foundation  
**Built with:** Python, SQLite, C/C++ upstream tools

## Reading order

1. Read the root README for project purpose and setup navigation.
2. Follow the entry points below to find the implementation.
3. Use the file guide to locate individual modules, tests, assets, and configuration.
4. Check component licenses before redistributing dependencies or assets.

## Important paths

- [wyld_together/session.py](../wyld_together/session.py) — Durable party policy. This module does not inject into or control DS3. Defines `Rejected`, `identifier`, `SessionStore`.
- [tests/test_session.py](../tests/test_session.py) — Automated checks for session. Defines `SessionTests`.
- [upstream.lock.json](../upstream.lock.json) — Structured upstream.lock data; top-level fields: `repository`, `commit`, `license`, `game_build`, `game_version`, `patch_sha256`.

## Structure

| Path | Role |
| --- | --- |
| [docs/](../docs/) | Project documentation, decisions, and reference material (5 tracked entries). |
| [licenses/](../licenses/) | Third-party license texts and attribution (1 tracked entries). |
| [patches/](../patches/) | Project-specific patches components (1 tracked entries). |
| [tests/](../tests/) | Automated checks and test fixtures (1 tracked entries). |
| [tools/](../tools/) | Developer utilities and supporting automation (2 tracked entries). |
| [wyld_together/](../wyld_together/) | Project-specific wyld together components (3 tracked entries). |

## Useful commands

Run from the repository root after following the documented prerequisites.

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m wyld_together
```

## Scope

This currently simulates party policy; it does not connect to the game or implement a playable seamless co-op mod. Preserve the upstream ds3os MIT notice.

## Maintaining the guide

The file catalog is a source-inspection snapshot, not proof that every runtime path works. Update it when moving files or changing module responsibilities. The 2026-10-12 documentation review did not run every application, deploy services, or validate all historical performance claims.
