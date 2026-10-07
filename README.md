# Wyld Together for Dark Souls III

An MIT-licensed project working toward co-op that survives player deaths and boss victories. **Stage 1 is a development foundation, not a playable seamless co-op mod.** Nothing in this repository currently hooks into DS3 or changes its multiplayer behavior.

## What works today

- A durable SQLite party-state library with up to six members. Simulated deaths and boss victories retain the party; a shared checkpoint reset revives its members.
- Reconnect handling, host-loss pause/resume, process-restart recovery, command deduplication, and atomic updates with revision checks.
- A pinned source build of [ds3os](https://github.com/TLeonardUK/ds3os), an existing open-source alternative server. The development patch fixes compilation on modern Linux compilers and binds its game and admin listeners to localhost.
- Automated party-policy tests and a native server smoke test for startup, loopback listeners, admin authentication, and clean shutdown.

The Python library and ds3os server are **separate components** at this stage. There is no event bridge between them, Windows injector build, authenticated party transport, in-game respawn logic, boss flag synchronization, or two-player gameplay validation. Boss and checkpoint names in the demo are illustrative identifiers, not reverse-engineered game addresses.

## Try the policy simulation

Python 3.10 or later, with its standard library, is sufficient. Run from this directory:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m wyld_together
```

The demo explicitly reports `simulation_only: true` and `game_adapter_connected: false`. For a persistent demonstration database, add `--database runtime/demo.sqlite`.

## Build the upstream native server

Linux prerequisites: Git, CMake, a C/C++ compiler, make, libuuid development files, and `ss` from iproute2 for the smoke test. The smoke test was run with Steam installed and signed in.

```sh
python3 -B tools/build_upstream.py
python3 -B tools/smoke_upstream.py
```

The builder fetches the exact author repository commit in `upstream.lock.json`, checks the patch SHA-256, and refuses to overwrite unexpected tracked source changes. It builds only the native server, with `WYLD_LOOPBACK_ONLY=ON`. Vendored dependencies still produce compiler warnings; a successful build is not a security audit or proof of game compatibility.

On the original development machine, reuse the existing checkout and build:

```sh
python3 -B tools/build_upstream.py --source ../upstream/ds3os --build ../build/ds3os
python3 -B tools/smoke_upstream.py --build ../build/ds3os
```

The smoke test creates a temporary runtime with public advertising disabled and fresh admin credentials, checks the listeners, then stops its own process and removes the temporary runtime. It does not connect DS3. No background service is installed. Do not expose this development build to the internet.

## Stages and acceptance criteria

1. **Foundation (implemented):** persistent party policy, tests, pinned ds3os source build, and local server smoke test.
2. **Game adapter:** audit the upstream Windows injector/loader; add supported-build checks, an authenticated event bridge, separate experimental saves, and an explicit private-server launch path. Verify two legitimately owned Steam clients connect and normal Steam launch remains unaffected.
3. **Deaths:** observe genuine host/guest death events, keep the connection alive, coordinate respawn at a valid checkpoint, and require acknowledgments from all clients. Test individual deaths, whole-party wipes, and disconnects during respawn.
4. **Bosses:** identify and validate world/progression flags, synchronize only supported changes, prevent normal boss-clear disconnects, and verify consistent saves after restarting both clients.
5. **Travel and recovery:** area transitions, bonfires, reconnect snapshots, mixed-version rejection, failure recovery, and long-session testing.

Each gameplay stage needs two DS3 owners testing the same supported Steam build. Current target: app 374320, build 10167187, version 1.15.2. A future adapter must check the executable itself; the Python version field alone does not establish compatibility.

## Adapter contract

`SessionStore` is an internal policy API, not a secure network endpoint. Actor strings are trusted inputs: accepting an arbitrary remote `actor` would permit impersonation. The future transport must authenticate identities and authorize party admission before invoking it.

- Call `recover_after_restart()` once, before accepting peers, when a coordinator starts. Connections cannot survive a crashed process.
- Translate verified game events into `join`, `reconnect`, `disconnect`, `leave`, `death`, `rest`, and `boss_defeated` commands.
- Scope request IDs to the party and actor. Retrying an identical request returns the current snapshot without replaying it; conflicting reuse is rejected.
- Use `expected_revision` when a command depends on a particular snapshot. A stale revision rejects the entire change.
- `epoch` identifies checkpoint resets. An accepted policy command is not confirmation that a game applied it; the future bridge must track application acknowledgments and recover partial failures.
- The host authorizes shared progress. Host loss pauses the party; there is no host migration. Disconnected players retain their slots until an explicit leave; timeout/removal policy is deferred.

## License and provenance

New project code is under [MIT](LICENSE). The upstream patch includes ds3os code under its [MIT notice](licenses/ds3os-MIT.txt); see [third-party notices](THIRD_PARTY_NOTICES.md). This is an independent project, not Yui's Seamless Co-op. It contains no copied proprietary mod code or game files, and keeps Steam ownership checks in the upstream server intact.

Only this `together` directory is intended for eventual publication. The surrounding DS3 setup contains machine-specific configuration, logs, and private backups. No public repository or binary release has been published as part of this setup.
