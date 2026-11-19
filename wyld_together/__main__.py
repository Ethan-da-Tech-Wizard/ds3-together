# ==============================================================================
# Program: __main__.py
# Programmer: Ethan-da-Tech-Wizard
# Last Modified: November 18, 2026
# Purpose: CLI simulation harness for executing multi-actor game event sequences
#          against an in-memory or on-disk SQLite session store, validating
#          party synchronization without live game process injection.
# ==============================================================================

"""Run a local event simulation; this does not connect to a running game."""
import argparse
import json
from .session import GAME_BUILD, PROTOCOL, SessionStore


def main():
    # Step 1: Configure command-line arguments for database persistence location
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=":memory:",
                        help="Path to SQLite database file or :memory: for ephemeral session")
    args = parser.parse_args()

    # Step 2: Initialize SQLite session storage backend (WAL mode, ACID guarantees)
    # ":memory:" keeps the simulation ephemeral; a path persists it for inspection.
    store = SessionStore(args.database)
    try:
        # Step 3: Instantiate a fresh multiplayer party hosted at the starting checkpoint
        state = store.create("host", "cemetery-of-ash")
        party = state["id"]

        # Step 4: Define an ordered progression of simulated network & gameplay events
        # Demonstrates join authorization, player mortality, boss defeat sync,
        # bonfire checkpoint epoch reset, and network disconnect/reconnect recovery
        # Each tuple is (actor, request_id, command). Request ids are unique per actor
        # so none is treated as a retry.
        events = [
            ("guest", "join", {"type": "join", "build": GAME_BUILD, "protocol": PROTOCOL}),
            ("guest", "death", {"type": "death"}),
            ("host", "boss", {"type": "boss_defeated", "boss": "iudex-gundyr"}),
            ("host", "rest", {"type": "rest", "checkpoint": "firelink-shrine"}),
            ("host", "disconnect", {"type": "disconnect"}),
            ("host", "reconnect", {"type": "reconnect", "build": GAME_BUILD, "protocol": PROTOCOL}),
        ]

        # Step 5: Sequentially evaluate state machine transitions with idempotency checks
        for actor, request, event in events:
            state = store.apply(party, actor, request, event)

        # Step 6: Output serialized final session state to standard output
        print(json.dumps({"simulation_only": True, "game_adapter_connected": False, "state": state}, indent=2))
    finally:
        # Step 7: Cleanly close database connections and release file locks
        store.close()


if __name__ == "__main__":
    main()
