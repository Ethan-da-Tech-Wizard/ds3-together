"""Durable party policy. This module does not inject into or control DS3.

A future game adapter must authenticate identities and translate real game
events to these commands. A successful command is not proof a game applied it.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

PROTOCOL = 1
GAME_BUILD = "10167187"
MAX_PLAYERS = 6


class Rejected(ValueError):
    """The entire command was rejected; state remains unchanged."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value):
        raise Rejected("Expected a non-empty identifier of at most 96 characters")
    return value


class SessionStore:
    def __init__(self, database):
        if str(database) != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, isolation_level=None, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS parties (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            party TEXT NOT NULL REFERENCES parties(id), actor TEXT NOT NULL,
            request_id TEXT NOT NULL, digest TEXT NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY (party, actor, request_id))""")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def create(self, host, checkpoint, *, build=GAME_BUILD, protocol=PROTOCOL):
        identifier(host)
        identifier(checkpoint)
        if build != GAME_BUILD or protocol != PROTOCOL:
            raise Rejected("Unsupported game build or protocol")
        party = uuid.uuid4().hex
        state = {"id": party, "host": host, "build": build, "protocol": protocol,
                 "revision": 0, "epoch": 0, "checkpoint": checkpoint,
                 "status": "active", "bosses": [],
                 "players": {host: {"connected": True, "alive": True, "checkpoint": checkpoint}}}
        with self.transaction():
            self.db.execute("INSERT INTO parties VALUES (?, ?)", (party, json.dumps(state)))
        return state

    def snapshot(self, party):
        row = self.db.execute("SELECT state FROM parties WHERE id = ?", (identifier(party),)).fetchone()
        if row is None:
            raise Rejected("Unknown party")
        return json.loads(row[0])

    def recover_after_restart(self):
        """Call once when the future coordinator starts, before accepting peers.

        Transport connections do not survive a process crash. Keep world progress
        and membership, but require everyone to reconnect and the host to resume.
        """
        with self.transaction():
            for party, serialized in self.db.execute("SELECT id, state FROM parties").fetchall():
                state = json.loads(serialized)
                if state["status"] == "closed":
                    continue
                changed = state["status"] != "paused" or any(p["connected"] for p in state["players"].values())
                if not changed:
                    continue
                state["status"] = "paused"
                for player in state["players"].values():
                    player["connected"] = False
                state["revision"] += 1
                self.db.execute("UPDATE parties SET state = ? WHERE id = ?", (json.dumps(state), party))

    def apply(self, party, actor, request_id, command, *, expected_revision=None):
        """Atomically apply one event; retries return current state without replay.

        Identity and transport authorization belong to the not-yet-built adapter.
        request_id is scoped to this party and actor. Reusing an ID for a different
        command fails. expected_revision provides optimistic concurrency control.
        """
        identifier(actor)
        identifier(request_id)
        if not isinstance(command, dict):
            raise Rejected("Command must be an object")
        digest = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
        with self.transaction():
            state = self.snapshot(party)
            existing = self.db.execute(
                "SELECT digest FROM events WHERE party = ? AND actor = ? AND request_id = ?",
                (party, actor, request_id)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise Rejected("A request ID cannot be reused for a different command")
                return state
            if expected_revision is not None and expected_revision != state["revision"]:
                raise Rejected("Stale revision; fetch the current snapshot")
            self._change(state, actor, command)
            state["revision"] += 1
            self.db.execute("UPDATE parties SET state = ? WHERE id = ?", (json.dumps(state), party))
            self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                            (party, actor, request_id, digest, state["revision"]))
        return state

    @staticmethod
    def _change(state, actor, command):
        kind = command.get("type")
        schemas = {"join": {"type", "build", "protocol"}, "reconnect": {"type", "build", "protocol"},
                   "disconnect": {"type"}, "leave": {"type"}, "death": {"type"},
                   "rest": {"type", "checkpoint"}, "boss_defeated": {"type", "boss"}}
        if kind not in schemas or set(command) != schemas[kind]:
            raise Rejected("Unknown command or invalid fields")
        if state["status"] == "closed":
            raise Rejected("Party was intentionally closed")
        players = state["players"]
        if kind in {"join", "reconnect"}:
            if command["build"] != state["build"] or command["protocol"] != state["protocol"]:
                raise Rejected("Party members must have the same game build and protocol")
            if kind == "reconnect" and actor not in players:
                raise Rejected("Only existing members can reconnect")
            if kind == "join" and actor in players:
                raise Rejected("Existing members must reconnect")
            if actor not in players:
                if len(players) >= MAX_PLAYERS:
                    raise Rejected("Party is full, including disconnected members")
                players[actor] = {"connected": True, "alive": True, "checkpoint": state["checkpoint"]}
            else:
                players[actor]["connected"] = True
            if actor == state["host"]:
                state["status"] = "active"
            return
        if actor not in players or not players[actor]["connected"]:
            raise Rejected("This command requires a connected party member")
        if kind == "disconnect":
            players[actor]["connected"] = False
            if actor == state["host"]:
                state["status"] = "paused"
        elif kind == "leave":
            if actor == state["host"]:
                state["status"] = "closed"
            else:
                del players[actor]
        elif kind == "death":
            if state["status"] != "active":
                raise Rejected("Wait for the host to reconnect")
            players[actor]["alive"] = False
        else:
            if actor != state["host"] or state["status"] != "active":
                raise Rejected("Only the connected host can change shared world progress")
            if kind == "rest":
                state["checkpoint"] = identifier(command["checkpoint"])
                state["epoch"] += 1
                for player in players.values():
                    player["alive"] = True
                    player["checkpoint"] = state["checkpoint"]
            elif kind == "boss_defeated":
                boss = identifier(command["boss"])
                if boss not in state["bosses"]:
                    state["bosses"].append(boss)
                    state["bosses"].sort()
