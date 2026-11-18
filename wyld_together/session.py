# Program: ds3-together - session.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Stores each multiplayer party in a SQLite database and enforces the rules (host, reconnecting, bosses, rests, build checks) for every event applied to it.

"""Durable party policy. This module does not inject into or control DS3.

A future game adapter must authenticate identities and translate real game
events to these commands. A successful command is not proof a game applied it.
"""
# ---------------- Imports ----------------
# contextmanager lets us write a "with" block helper (used for transactions).
from contextlib import contextmanager
# hashlib makes a fingerprint (digest) of each command to spot reused request ids.
import hashlib
# json turns the party state dictionary into text for the database and back.
import json
# Path handles file locations (used to create the database folder).
from pathlib import Path
# re is for pattern matching, used to validate identifiers.
import re
# sqlite3 is the built-in database library; the whole party is stored in one file.
import sqlite3
# uuid creates a random unique id for each new party.
import uuid

# ---------------- Constants ----------------
# PROTOCOL is the version of the message format; everyone in a party must match.
PROTOCOL = 1
# GAME_BUILD is the game version number (a string) that all members must share.
GAME_BUILD = "10167187"
# MAX_PLAYERS is the largest party size (disconnected members still count).
MAX_PLAYERS = 6


class Rejected(ValueError):
    """The entire command was rejected; state remains unchanged."""


def identifier(value):
    """Check that `value` is a safe identifier string and return it, or raise Rejected."""
    # Accept only text made of letters, digits and . _ : - (1 to 96 characters);
    # anything else is rejected so odd input cannot reach the database.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value):
        raise Rejected("Expected a non-empty identifier of at most 96 characters")
    return value


# ---------------- The session store ----------------
class SessionStore:
    """Saves parties in SQLite and applies events to them one safe step at a time."""
    def __init__(self, database):
        """Open (or create) the database file and make sure the two tables exist.

        `database` is a file path, or ":memory:" for a throwaway in-RAM database."""
        # For a real file, make sure its folder exists first.
        if str(database) != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None means we control transactions ourselves (see transaction()).
        # timeout=5 waits up to 5 seconds if another connection has the database locked.
        self.db = sqlite3.connect(database, isolation_level=None, timeout=5)
        # WAL mode lets readers and a writer work at the same time.
        self.db.execute("PRAGMA journal_mode=WAL")
        # Make SQLite enforce links between tables.
        self.db.execute("PRAGMA foreign_keys=ON")
        # parties table: one row per party; "state" holds the whole party as JSON text.
        self.db.execute("CREATE TABLE IF NOT EXISTS parties (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
        # events table: a record of every request already applied, keyed by party, actor and request id.
        # This is how a repeated (retried) request is recognised and not applied twice.
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            party TEXT NOT NULL REFERENCES parties(id), actor TEXT NOT NULL,
            request_id TEXT NOT NULL, digest TEXT NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY (party, actor, request_id))""")

    def close(self):
        """Close the database connection."""
        self.db.close()

    # Used as "with self.transaction():". Everything inside succeeds together or is undone together.
    @contextmanager
    def transaction(self):
        """Run a block of changes as one all-or-nothing database transaction."""
        # BEGIN IMMEDIATE takes the write lock right away so two writers cannot interleave.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            # The block finished without errors: save the changes.
            self.db.execute("COMMIT")
        except BaseException:
            # Something went wrong: undo every change from this block, then pass the error on.
            self.db.execute("ROLLBACK")
            raise

    def create(self, host, checkpoint, *, build=GAME_BUILD, protocol=PROTOCOL):
        """Start a new party owned by `host` at `checkpoint` and return its state dictionary."""
        # Validate the inputs before using them.
        identifier(host)
        identifier(checkpoint)
        # Only the supported game version and protocol may create a party.
        if build != GAME_BUILD or protocol != PROTOCOL:
            raise Rejected("Unsupported game build or protocol")
        # Random unique id for the new party.
        party = uuid.uuid4().hex
        # Starting state: nothing defeated yet, host connected and alive.
        # revision counts changes; epoch counts how many times the party has rested.
        state = {"id": party, "host": host, "build": build, "protocol": protocol,
                 "revision": 0, "epoch": 0, "checkpoint": checkpoint,
                 "status": "active", "bosses": [],
                 "players": {host: {"connected": True, "alive": True, "checkpoint": checkpoint}}}
        # Save the new party in the database.
        with self.transaction():
            self.db.execute("INSERT INTO parties VALUES (?, ?)", (party, json.dumps(state)))
        return state

    def snapshot(self, party):
        """Return the current saved state of `party`, or raise Rejected if it does not exist."""
        # Look the party up by id (the id is validated first).
        row = self.db.execute("SELECT state FROM parties WHERE id = ?", (identifier(party),)).fetchone()
        # No such party.
        if row is None:
            raise Rejected("Unknown party")
        # Turn the saved JSON text back into a dictionary.
        return json.loads(row[0])

    def recover_after_restart(self):
        """Call once when the future coordinator starts, before accepting peers.

        Transport connections do not survive a process crash. Keep world progress
        and membership, but require everyone to reconnect and the host to resume.
        """
        # Go through every saved party inside a single transaction.
        with self.transaction():
            for party, serialized in self.db.execute("SELECT id, state FROM parties").fetchall():
                state = json.loads(serialized)
                # Closed parties stay closed.
                if state["status"] == "closed":
                    continue
                # Only touch parties that are not already paused with everyone disconnected.
                changed = state["status"] != "paused" or any(p["connected"] for p in state["players"].values())
                if not changed:
                    continue
                # Pause the party and mark every member as disconnected;
                # the host must reconnect to resume it.
                state["status"] = "paused"
                for player in state["players"].values():
                    player["connected"] = False
                # Count this change.
                state["revision"] += 1
                self.db.execute("UPDATE parties SET state = ? WHERE id = ?", (json.dumps(state), party))

    def apply(self, party, actor, request_id, command, *, expected_revision=None):
        """Atomically apply one event; retries return current state without replay.

        Identity and transport authorization belong to the not-yet-built adapter.
        request_id is scoped to this party and actor. Reusing an ID for a different
        command fails. expected_revision provides optimistic concurrency control.
        """
        # Validate who is acting and which request this is.
        identifier(actor)
        identifier(request_id)
        # A command must be a dictionary such as {"type": "death"}.
        if not isinstance(command, dict):
            raise Rejected("Command must be an object")
        # Fingerprint the command so we can tell whether a repeated request id carries the same command.
        digest = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
        with self.transaction():
            # Load the latest state inside the transaction.
            state = self.snapshot(party)
            # Has this actor already sent this request id?
            existing = self.db.execute(
                "SELECT digest FROM events WHERE party = ? AND actor = ? AND request_id = ?",
                (party, actor, request_id)).fetchone()
            # Same id and same command: a retry, so return the state unchanged.
            # Same id with a different command: refuse.
            if existing:
                if existing[0] != digest:
                    raise Rejected("A request ID cannot be reused for a different command")
                return state
            # Optional guard: the caller says which revision it expects, and a mismatch means it is out of date.
            if expected_revision is not None and expected_revision != state["revision"]:
                raise Rejected("Stale revision; fetch the current snapshot")
            # Apply the rules for this command (raises Rejected if not allowed).
            self._change(state, actor, command)
            state["revision"] += 1
            # Save the new state and record the request so it is never applied twice.
            self.db.execute("UPDATE parties SET state = ? WHERE id = ?", (json.dumps(state), party))
            self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                            (party, actor, request_id, digest, state["revision"]))
        return state

    # A static method does not use "self"; it only edits the dictionary it is given.
    @staticmethod
    def _change(state, actor, command):
        """Apply one command to the in-memory `state` for `actor`, or raise Rejected.

        The leading underscore marks this as an internal helper of SessionStore."""
        # Which kind of event is it?
        kind = command.get("type")
        # For each command type, the exact set of fields allowed. Extra or missing fields are errors.
        schemas = {"join": {"type", "build", "protocol"}, "reconnect": {"type", "build", "protocol"},
                   "disconnect": {"type"}, "leave": {"type"}, "death": {"type"},
                   "rest": {"type", "checkpoint"}, "boss_defeated": {"type", "boss"}}
        # Reject unknown types and wrong field sets.
        if kind not in schemas or set(command) != schemas[kind]:
            raise Rejected("Unknown command or invalid fields")
        # Nothing can happen in a party that was closed on purpose.
        if state["status"] == "closed":
            raise Rejected("Party was intentionally closed")
        # Shortcut to the dictionary of party members.
        players = state["players"]
        # ---- Joining or reconnecting ----
        if kind in {"join", "reconnect"}:
            # Everyone must run the same game build and protocol as the party.
            if command["build"] != state["build"] or command["protocol"] != state["protocol"]:
                raise Rejected("Party members must have the same game build and protocol")
            # Only people already in the party may reconnect, and existing members must use reconnect instead of join.
            if kind == "reconnect" and actor not in players:
                raise Rejected("Only existing members can reconnect")
            if kind == "join" and actor in players:
                raise Rejected("Existing members must reconnect")
            # A brand new member: refuse if the party is full, otherwise add them alive at the shared checkpoint.
            if actor not in players:
                if len(players) >= MAX_PLAYERS:
                    raise Rejected("Party is full, including disconnected members")
                players[actor] = {"connected": True, "alive": True, "checkpoint": state["checkpoint"]}
            else:
                # An existing member simply comes back online.
                players[actor]["connected"] = True
            # The host returning un-pauses the party.
            if actor == state["host"]:
                state["status"] = "active"
            return
        # ---- Every other command needs a connected member ----
        if actor not in players or not players[actor]["connected"]:
            raise Rejected("This command requires a connected party member")
        # Mark them offline; if it is the host, pause the whole party.
        if kind == "disconnect":
            players[actor]["connected"] = False
            if actor == state["host"]:
                state["status"] = "paused"
        # Leaving on purpose: the host leaving closes the party, a guest is removed.
        elif kind == "leave":
            if actor == state["host"]:
                state["status"] = "closed"
            else:
                del players[actor]
        # A death only marks this one player as not alive; they stay in the party.
        elif kind == "death":
            if state["status"] != "active":
                raise Rejected("Wait for the host to reconnect")
            players[actor]["alive"] = False
        else:
            # ---- Rest and boss defeats change the shared world, so only the connected host may do them ----
            if actor != state["host"] or state["status"] != "active":
                raise Rejected("Only the connected host can change shared world progress")
            # Resting sets a new shared checkpoint, raises the epoch, and revives the whole party there.
            if kind == "rest":
                state["checkpoint"] = identifier(command["checkpoint"])
                state["epoch"] += 1
                for player in players.values():
                    player["alive"] = True
                    player["checkpoint"] = state["checkpoint"]
            # Record the defeated boss once and keep the list sorted.
            elif kind == "boss_defeated":
                boss = identifier(command["boss"])
                if boss not in state["bosses"]:
                    state["bosses"].append(boss)
                    state["bosses"].sort()
